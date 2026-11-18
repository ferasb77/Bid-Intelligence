"""Long, form-based tender packages (first real case: a 189-page ITB, Phoenix
runs 21/22, 2026-11-18). Everything here is deterministic -- no model calls.

Defects reproduced from that package, on a fictional package of the same
layout (the client document itself is not stored in the repository):

1. a running page header ("Tender No. / Page n of m / Exhibit II - Schedule
   of Compensation") opened a section on every page;
2. an INDEX page became the opportunity synopsis;
3. clause numbers printed on their own line ("5A.", "3.2.") became
   deliverables;
4. a contact e-mail printed under the postal address for sealed,
   hand-delivered bids became "Submission method: Email";
5. fill-in forms (resume format, bank guarantee template) became
   "Qualifications sought";
6. liability caps ("shall not exceed the Contract Price") became the budget;
7. bid-bond amounts had no category of their own;
8. passages FAST could not read in full were not disclosed;
9. the FAST commercial pass truncated at 4000 output tokens and ran its
   chunks one after another.
"""
from __future__ import annotations

import io
import json
import re
from unittest.mock import MagicMock

import pytest

import fast_analysis as fa
import phoenix_reports as pr
import procurement_digest as pdg

DOC = "ITB - Provision of Advisory Services.pdf"


def _page(n: int, total: int, part: str, body: str) -> str:
    return (f"[[SOURCE: {DOC} | PAGE: {n}]]\n"
            f"Tender Number: NW-ADV-27-0042\n"
            f"Page {n} of {total}\n"
            f"Provision of Advisory Services for Northwind Utilities\n"
            f"{part}\n{body}\n")


PAGES = [
    ("Form (A)", "INVITATION TO BID\nBid Closing Date: 15 March 2027\n"
                 "Please note the following:\n"
                 "• Bid submission must be in English only.\n"
                 "• Bid submission must by hand and /or courier and delivered to the below address.\n"
                 "• Bid Bond Value is USD: 25,000.00\n"),
    ("Form (A)", "INDEX\n1.0\nIntroduction\n2.0\nDefinitions\n3.0\nSubmission of Bid Proposal\n"
                 "4.0\nBid Validity\n5.0\nOther Conditions Regarding The Bid\n"),
    ("Form (A)", "1.0\nINTRODUCTION\n1.1\nNorthwind Utilities is hereby soliciting a competitive Bid Proposal "
                 "for the Provision of Advisory Services for its network reorganisation.\n"
                 "2.0\nDEFINITIONS\n2.1\n“Bid” shall mean the proposal submitted by Bidder.\n"),
    ("Form (A)", "3.0\nSUBMISSION OF BID PROPOSAL\n3.1\nBidder shall submit the Bid Proposal to the following address:\n"
                 "Tender Secretary,\nSupply Chain Department.\nNorthwind Utilities.\nHarbour Road 12, Port Vale\n"
                 "Email: tenders@northwind.example\n"
                 "NOTE: BIDDER MUST ENSURE THAT EACH SEALED ENVELOPE SUBMITTED IS CLEARLY MARKED.\n"
                 "3.2\nBid Proposal received after the Bid Closing Date will not be considered.\n"),
    ("Exhibit II – Schedule of Compensation", "1.11\nExpected Deliverables\n"
                 "The Consultant shall, at a minimum, submit the following deliverables:\n"
                 "Phase\nRef.\nDeliverable title\nPhase 1\n1A\nProject Work Plan and Governance Charter\n"
                 "1B\nCurrent-State Assessment Report\nPhase 2\n2A\nWorkload Analysis\n"),
    ("Exhibit II – Schedule of Compensation", "2.0\nDELIVERABLE SUBMISSION AND REVIEW\n2.1.\nThe Consultant shall submit "
                 "each deliverable in the approved format.\n3.2.\nThe Consultant shall address the consolidated "
                 "comments.\n5A.\nImplementation Roadmap and Governance Framework\n"),
    ("Exhibit II – Schedule of Compensation", "PRICES SCHEDULE\nThe Rates are inclusive of all costs.\n"),
    ("Contract Form", "14.5 If this Article is void, the liability of Contractor shall not exceed the "
                      "Contract Price.\nThe total budget for the assignment shall not exceed USD 400,000.\n"
                      "16.4 Notices shall be deemed received at the time of delivery if delivered by hand, "
                      "or when sent by e-mail to notices@northwind.example.\n"),
    ("Exhibit V", "RESUME FORMAT\nNAME\nEXPERIENCE:\nA) TOTAL EXPERIENCE\nDescribe your past employment history.\n"
                  "__________________\nPersonnel's Signature\n___________\nDate\n"),
    ("Exhibit VI", "BANK GUARANTEE FORMAT\nIn response to the request made by Contractor, we (Name of Banker :) "
                   "duly registered under the laws of XXXXXX guarantee ……….. the sum.\n"),
]
TEXT = "".join(_page(i + 1, len(PAGES), part, body) for i, (part, body) in enumerate(PAGES))
DOCS = [(DOC, TEXT)]


@pytest.fixture(scope="module")
def facts():
    return pr.build_facts(bid={"id": 1, "title": "Provision of Advisory Services", "client": "Northwind Utilities"},
                          fast_result={}, documents=DOCS, analysis_date="2026-11-18",
                          coverage={"split_exhausted_rows": 0, "coverage_gaps": [
                              {"filename": DOC, "route": "COMMERCIAL_ONLY", "pages": "7-8", "reason": "OUTPUT_LIMIT"},
                              {"filename": DOC, "route": "COMMERCIAL_ONLY", "pages": "9", "reason": "UNREADABLE_RESPONSE"}]})


@pytest.fixture(scope="module")
def snapshot_text(facts):
    import pymupdf
    pdf = pr.render_snapshot(facts)["pdf"]
    return re.sub(r"\s+", " ", "\n".join(p.get_text() for p in pymupdf.open(stream=pdf, filetype="pdf")))


# ── page furniture ──────────────────────────────────────────────────────────

def test_running_header_is_not_content():
    texts = [ln["text"] for ln in pdg.content_lines(DOCS)]
    assert not any(t.startswith(("Tender Number", "Page ")) for t in texts)
    assert "Exhibit II – Schedule of Compensation" not in texts
    assert not any(s["heading"].startswith("Exhibit II") for s in pdg.sections(DOCS))


def test_index_page_is_not_the_synopsis(facts):
    assert not any("Definitions" in ln["text"] for ln in pdg.content_lines(DOCS) if ln["page"] == 2)
    assert facts["synopsis"][0]["text"].startswith("Northwind Utilities is hereby soliciting")
    assert facts["synopsis"][0]["page"] == 3


def test_located_lines_still_count_every_page(facts):
    assert facts["documents"][0]["pages"] == len(PAGES)


# ── clause numbers and deliverables ─────────────────────────────────────────

def test_clause_numbers_never_become_items(facts):
    every = [i["text"] for s in pdg.sections(DOCS) for i in s["items"]]
    assert not [t for t in every if pdg._CLAUSE_NO.match(t) or re.match(r"^\d+(\.\d+)*\.?\s*$", t)]
    assert not [d for d in facts["deliverables"] if re.fullmatch(r"[\dA-Z.]+", d["text"])]


def test_deliverables_list_from_reference_code_table(facts):
    names = [d["text"] for d in facts["deliverables_primary"]]
    assert names == ["Project Work Plan and Governance Charter", "Current-State Assessment Report",
                     "Workload Analysis"]


def test_deliverable_procedure_heading_is_not_a_deliverables_section():
    assert "deliverables" not in [pdg._heading_key(h) for h in
                                  ("Deliverable Submission", "Deliverable title", "Submission milestone")]
    assert pdg._heading_key("Expected Deliverables") == "deliverables"
    assert pdg._heading_key("Phase 3 Deliverables") == "deliverables"


# ── submission method vs contact ────────────────────────────────────────────

def test_sealed_delivery_with_contact_email_is_physical(facts):
    sub = facts["submission"]
    assert sub["channel"] == "Physical delivery"
    assert sub["emails"] == []
    assert [c["email"] for c in sub["contact_emails"]] == ["tenders@northwind.example"]
    assert "by hand" in sub["method_sentences"][0]["text"]


def test_email_submission_still_email():
    docs = [("rfp.pdf", "[[SOURCE: rfp.pdf | PAGE: 1]]\nProposals must be sent by email to bids@client.example "
                        "no later than 5 March 2027.\n")]
    sub = pdg.submission_instructions(docs)
    assert sub["channel"] == "Email"
    assert [e["email"] for e in sub["emails"]] == ["bids@client.example"]


def test_snapshot_states_method_and_contact_separately(snapshot_text):
    assert "SUBMISSION METHOD Physical delivery" in snapshot_text
    assert "Email to" not in snapshot_text
    assert "CONTACT E-MAIL (AS PRINTED) tenders@northwind.example" in snapshot_text
    assert "LATE SUBMISSIONS Will not be considered" in snapshot_text


# ── forms, budget, securities ───────────────────────────────────────────────

def test_fill_in_forms_are_not_qualifications(facts, snapshot_text):
    assert facts["qualifications"] == []
    assert "Qualifications sought" not in snapshot_text
    assert "Name of Banker" not in snapshot_text and "Describe your past" not in snapshot_text


def test_liability_cap_is_not_budget(facts):
    assert [b["text"] for b in facts["budget"]] == [
        "The total budget for the assignment shall not exceed USD 400,000."]


def test_bid_bond_reported_as_security(facts, snapshot_text):
    assert [s["text"] for s in facts["securities"]] == ["Bid Bond Value is USD: 25,000.00"]
    assert "SECURITIES AND GUARANTEES Bid Bond Value is USD: 25,000.00" in snapshot_text


# ── coverage disclosure ─────────────────────────────────────────────────────

def test_coverage_limitation_lists_pages(snapshot_text):
    assert ("COVERAGE LIMITATION FAST could not read 2 passages of the source in full "
            f"(pages 7-8, 9 of {DOC})") in snapshot_text


def test_coverage_limitation_for_runs_without_page_ranges():
    note = pr.coverage_limitation({"split_exhausted_rows": 7})
    assert note.startswith("FAST could not read 7 passages of the source in full "
                           "(the pages concerned were not recorded")
    assert pr.coverage_limitation({"split_exhausted_rows": 0, "coverage_gaps": []}) is None
    assert pr.coverage_limitation(None) is None


# ── FAST: output ceiling, chunk concurrency, recorded gaps ──────────────────

def _resp(payload, stop="end_turn", text=None):
    r = MagicMock()
    r.content = [MagicMock(text=text if text is not None else json.dumps(payload))]
    r.stop_reason = stop
    r.usage = MagicMock(input_tokens=10, output_tokens=10)
    return r


def _pages_doc(n_pages: int, chars: int = 9000) -> str:
    return "".join(f"[[SOURCE: x.pdf | PAGE: {p}]]\n" + (f"clause text page {p}. " * (chars // 20)) + "\n"
                   for p in range(1, n_pages + 1))


def test_fast_output_ceiling_is_16000():
    client = MagicMock()
    client.messages.create.return_value = _resp({"commercial_clauses": [{"topic": "t"}]})
    fa.extract_fast_document("x.pdf", _pages_doc(1, 2000), "k", route=fa.ROUTE_COMMERCIAL_ONLY, client=client)
    assert client.messages.create.call_args.kwargs["max_tokens"] == 16000 == fa.FAST_MAX_OUTPUT_TOKENS


def test_chunks_run_concurrently_but_merge_in_document_order():
    doc = _pages_doc(12)
    chunks = fa._deep_chunk_document_text(doc, max_chunk_chars=fa.FAST_MAX_CHUNK_CHARS)
    assert len(chunks) >= 3

    def create(**kw):
        text = kw["messages"][0]["content"][0]["text"]
        first = re.search(r"PAGE: (\d+)", text.split("DOCUMENT TO PROCESS")[1]).group(1)
        return _resp({"commercial_clauses": [{"topic": f"from page {first}"}]})
    client = MagicMock()
    client.messages.create.side_effect = create
    telemetry = []
    out = fa.extract_fast_document("x.pdf", doc, "k", route=fa.ROUTE_COMMERCIAL_ONLY, client=client,
                                   telemetry=telemetry)
    firsts = [int(re.search(r"PAGE: (\d+)", c).group(1)) for c in chunks]
    assert [c["topic"] for c in out["commercial_clauses"]] == [f"from page {p}" for p in firsts]
    assert [t["call_index"] for t in telemetry] == list(range(len(chunks)))
    assert [t["pages"].split("-")[0] for t in telemetry] == [str(p) for p in firsts]


def test_split_exhausted_and_unreadable_chunks_are_recorded_as_gaps():
    telemetry = [
        {"call_index": 0, "call_kind": "initial", "filename": "x.pdf", "route": "COMMERCIAL_ONLY", "pages": "1-4",
         "parse_status": "RECOVERED_TRUNCATED", "error": None, "provider_call_attempted": True,
         "stop_reason": "max_tokens", "input_tokens": 1, "output_tokens": 1},
        {"call_index": 1, "call_kind": "split_recovery_a", "filename": "x.pdf", "route": "COMMERCIAL_ONLY",
         "pages": "1-2", "parse_status": "RECOVERED_TRUNCATED", "error": None, "provider_call_attempted": True,
         "stop_reason": "max_tokens", "input_tokens": 1, "output_tokens": 1},
        {"call_index": 2, "call_kind": "split_exhausted", "filename": "x.pdf", "route": "COMMERCIAL_ONLY",
         "pages": "1-2", "parse_status": "BOUNDED_SPLIT_EXHAUSTED", "error": None,
         "provider_call_attempted": False},
        {"call_index": 3, "call_kind": "initial", "filename": "x.pdf", "route": "COMMERCIAL_ONLY", "pages": "5-9",
         "parse_status": "FAILED", "error": None, "provider_call_attempted": True, "input_tokens": 1, "output_tokens": 1},
        {"call_index": 4, "call_kind": "targeted_retry", "filename": "x.pdf", "route": "COMMERCIAL_ONLY",
         "pages": "5-9", "parse_status": "FAILED", "error": None, "provider_call_attempted": True,
         "input_tokens": 1, "output_tokens": 1},
        {"call_index": 5, "call_kind": "initial", "filename": "x.pdf", "route": "COMMERCIAL_ONLY", "pages": "10",
         "parse_status": "FAILED", "error": None, "provider_call_attempted": True, "input_tokens": 1, "output_tokens": 1},
        {"call_index": 6, "call_kind": "targeted_retry", "filename": "x.pdf", "route": "COMMERCIAL_ONLY",
         "pages": "10", "parse_status": "COMPLETE", "error": None, "provider_call_attempted": True,
         "input_tokens": 1, "output_tokens": 1},
    ]
    gaps = fa._telemetry_audit_summary(telemetry, 1.0)["coverage_gaps"]
    assert [(g["pages"], g["reason"]) for g in gaps] == [("1-2", "OUTPUT_LIMIT"), ("5-9", "UNREADABLE_RESPONSE")]


def test_unreadable_response_end_to_end_produces_a_gap():
    client = MagicMock()
    client.messages.create.return_value = _resp(None, text="not json at all {")
    telemetry = []
    fa.extract_fast_document("x.pdf", _pages_doc(1, 2000), "k", route=fa.ROUTE_COMMERCIAL_ONLY, client=client,
                             telemetry=telemetry)
    gaps = fa._telemetry_audit_summary(telemetry, 1.0)["coverage_gaps"]
    assert [(g["pages"], g["reason"]) for g in gaps] == [("1", "UNREADABLE_RESPONSE")]


def test_titles_listed_after_a_lead_in_are_list_entries_not_sections():
    # "Detailed technical proposal covering at least the following areas:" followed by
    # "Background" / "Timeline" -- the proposal's required contents, not the RFP's own sections
    docs = [("rfp.pdf", "[[SOURCE: rfp.pdf | PAGE: 1]]\n- \nSome bullet before any section.\n"
                        "B5. Proposal Requirements\nThe technical proposal must include at least the following areas:\n"
                        "Background\nProposed Methodology\nTimeline\nOverview of Deliverables\n"
                        "References for three clients.\n2. Financial Proposal Requirements\n"
                        "Detailed financial proposal with breakdown of costs per training day.\n")]
    keys = [(s["key"], s["heading"]) for s in pdg.sections(docs)]
    assert keys == [("pricing", "Financial Proposal Requirements")]
    assert pr.build_facts(bid={"id": 2}, fast_result={}, documents=docs, analysis_date="2026-11-18")["synopsis"] == []
