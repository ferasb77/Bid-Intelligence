"""Report facts (procurement_facts.py) and the reports built from them.

Synthetic, fictional documents only; every model call is mocked. What is
tested is the general mechanism: facts are classified by meaning (by the
model), every fact is verified against the source (quote located, figures
and wording supported), and the reports print verified facts only -- never a
keyword guess.
"""
from __future__ import annotations

import json
import re
from unittest.mock import MagicMock

import pytest

import phoenix_reports as pr
import procurement_facts as pf

DOC = "RFQ-77 Network Survey.pdf"
TEXT = (
    f"[[SOURCE: {DOC} | PAGE: 1]]\n"
    "Tender No. RFQ-77\nPage 1 of 2\n"
    "Riverside Utilities Board\nHead Office: 9 Mill Lane, Easton\nEmail: info@riverside.example\n"
    "REQUEST FOR QUOTATION RFQ-77\n"
    "The Board invites quotations for a condition survey of 40 km of trunk mains.\n"
    "All survey work shall be performed on site in the Western Network; reporting may be done remotely.\n"
    "Training sessions will be delivered in an interactive style built around participants' own cases.\n"
    "Deliverables:\n1- Inception Report within 2 weeks.\n2- Condition Survey Report.\n"
    "Evaluation: methodology; experience; price.\n"
    f"[[SOURCE: {DOC} | PAGE: 2]]\n"
    "Tender No. RFQ-77\nPage 2 of 2\n"
    "Quotations may be submitted either through the e-tender portal at https://etender.riverside.example "
    "or by hand delivery to Room 12, 9 Mill Lane, Easton.\n"
    "Questions may be e-mailed to queries@riverside.example until 1 March 2027.\n"
    "The successful bidder shall provide a performance guarantee of 10% of the contract value.\n"
    "Bidders must have completed at least three pipe condition surveys in the last five years.\n"
    "An advance payment of 15% may be made only against an advance payment guarantee.\n"
)
DOCS = [(DOC, TEXT)]


def fact(cat, statement, quote, page, **kw):
    return dict({"category": cat, "statement": statement, "quote": quote, "page": page, "doc": DOC}, **kw)


GOOD = [
    {"category": "ASSIGNMENT", "doc": DOC,
     "statement": "Riverside Utilities Board invites quotations for a condition survey of 40 km of trunk mains.",
     "quotes": [{"quote": "The Board invites quotations for a condition survey of 40 km of trunk mains.", "page": 1}]},
    fact("DELIVERY_LOCATION", "Survey work is performed on site in the Western Network; reporting may be remote.",
         "All survey work shall be performed on site in the Western Network; reporting may be done remotely.", 1,
         priority=1),
    fact("SUBMISSION_METHOD", "Quotations may be submitted through the e-tender portal at "
         "https://etender.riverside.example.", "Quotations may be submitted either through the e-tender portal at "
         "https://etender.riverside.example", 2, priority=1),
    fact("SUBMISSION_METHOD", "Alternatively, quotations may be hand delivered to Room 12, 9 Mill Lane, Easton.",
         "or by hand delivery to Room 12, 9 Mill Lane, Easton.", 2, priority=1),
    fact("CLARIFICATION", "Questions may be e-mailed to queries@riverside.example until 1 March 2027.",
         "Questions may be e-mailed to queries@riverside.example until 1 March 2027.", 2),
    fact("DELIVERABLE", "Inception Report within 2 weeks.", "Inception Report within 2 weeks.", 1, priority=1),
    fact("DELIVERABLE", "Condition Survey Report.", "Condition Survey Report.", 1, priority=1),
    fact("GUARANTEE", "A performance guarantee of 10% of the contract value is required from the successful bidder.",
         "The successful bidder shall provide a performance guarantee of 10% of the contract value.", 2),
    fact("QUALIFICATION", "Bidders must have completed at least three pipe condition surveys in the last five years.",
         "Bidders must have completed at least three pipe condition surveys in the last five years.", 2),
    fact("PAYMENT", "An advance payment of 15% may be made only against an advance payment guarantee.",
         "An advance payment of 15% may be made only against an advance payment guarantee.", 2),
    fact("EVALUATION", "Quotations are evaluated on methodology, experience and price.",
         "Evaluation: methodology; experience; price.", 1),
]


# ── verification ────────────────────────────────────────────────────────────

def test_quotes_are_located_with_list_numbers_and_page_breaks_skipped():
    idx = pf._Index(DOCS)
    assert idx.locate(DOC, 1, "Deliverables: Inception Report within 2 weeks. Condition Survey Report.")["page"] == 1
    # a quote cut off mid-word at its end, and one joining two passages with an ellipsis
    assert idx.locate(DOC, 2, "Questions may be e-mailed to queries@riverside.example until 1 Mar") is not None
    assert idx.locate(DOC, 2, "Quotations may be submitted either through the e-tender portal ... "
                              "Questions may be e-mailed to queries@riverside.example") is not None


def test_a_changed_number_or_invented_text_is_not_located():
    idx = pf._Index(DOCS)
    assert idx.locate(DOC, 2, "or by hand delivery to Room 13, 9 Mill Lane, Easton.") is None
    assert idx.locate(DOC, 2, "The successful bidder shall provide a performance guarantee of 5% of the "
                              "contract value.") is None
    assert idx.locate(DOC, 1, "All survey work shall be performed in the capital city.") is None


def test_statement_with_unsupported_figure_or_content_falls_back_to_the_quote():
    q = "The successful bidder shall provide a performance guarantee of 10% of the contract value."
    assert pf.supported("A performance guarantee of 10% of the contract value is required.", q)
    assert not pf.supported("A performance guarantee of 12% of the contract value is required.", q)
    assert not pf.supported("A performance guarantee of 10% is required, issued by a bank in Easton within "
                            "30 days, with an option to substitute insurance cover.", q)
    v = pf.verify({"facts": [fact("GUARANTEE", "A bid bond of USD 50,000 is required.", q, 2)]}, DOCS)
    assert v["facts"][0]["text"] == q and v["facts"][0]["verbatim"]


def test_evidence_gates_by_category():
    v = pf.verify({"facts": [
        fact("SUBMISSION_METHOD", "Submit to the Board.", "Evaluation: methodology; experience; price.", 1),
        fact("GUARANTEE", "Guarantee required.", "Bidders must have completed at least three pipe condition "
                                                 "surveys in the last five years.", 2),
        fact("OTHER", "Request for quotation.", "REQUEST FOR QUOTATION RFQ-77", 1),
    ]}, DOCS)
    assert v["facts"] == [] and v["dropped"] == 3


def test_unlocatable_and_unknown_category_facts_are_dropped():
    v = pf.verify({"facts": [fact("SCOPE", "Survey 400 km.", "The Board invites quotations for a survey of 400 km.", 1),
                             fact("MADE_UP", "x", "Condition Survey Report.", 1)]}, DOCS)
    assert v["facts"] == [] and v["dropped"] == 2


def test_assignment_and_priority_order_and_page_correction():
    v = pf.verify({"facts": GOOD + [fact("DELIVERABLE", "Survey report.", "Condition Survey Report.", 2, priority=3)]},
                  DOCS, context=["Riverside Utilities Board"])
    assert v["assignment"]["text"].startswith("Riverside Utilities Board invites quotations")
    assert not v["assignment"]["verbatim"]
    cats = pf.by_category(v)
    assert [f["priority"] for f in cats["SUBMISSION_METHOD"]] == [1, 1]
    assert all(f["page"] == 1 for f in cats["DELIVERABLE"])  # page 2 claimed, found on page 1


# ── extraction (mocked model) ───────────────────────────────────────────────

def _resp(text, stop="end_turn"):
    r = MagicMock()
    r.content = [MagicMock(text=text)]
    r.stop_reason = stop
    r.usage = MagicMock(input_tokens=100, output_tokens=50)
    return r


def test_extract_reads_json_lines_and_survives_a_cut_off_last_line():
    lines = "\n".join(json.dumps(f) for f in GOOD) + '\n{"category": "SCOPE", "statement": "unfini'
    client = MagicMock()
    client.messages.create.return_value = _resp(lines, stop="max_tokens")
    payload = pf.extract(DOCS, client=client)
    assert len(payload["facts"]) == len(GOOD)
    assert payload["coverage_gaps"] == [{"filename": DOC, "route": "REPORT_FACTS", "pages": "1-2",
                                         "reason": "OUTPUT_LIMIT"}]
    sent = client.messages.create.call_args.kwargs
    assert sent["max_tokens"] == pf.MAX_OUTPUT_TOKENS and sent["model"] == pf.FACTS_MODEL
    body = sent["messages"][0]["content"][0]["text"]
    assert "[[PAGE 1]]" in body and "[[PAGE 2]]" in body and "Condition Survey Report." in body


def test_extract_records_failed_and_unreadable_calls_as_gaps():
    client = MagicMock()
    client.messages.create.return_value = _resp("I cannot help with that.")
    assert pf.extract(DOCS, client=client)["coverage_gaps"][0]["reason"] == "UNREADABLE_RESPONSE"
    client.messages.create.side_effect = RuntimeError("overloaded")
    assert pf.extract(DOCS, client=client)["coverage_gaps"][0]["reason"] == "CALL_FAILED"


def test_long_documents_are_chunked_by_page():
    words = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike".split()
    pages = "".join(f"[[SOURCE: x.pdf | PAGE: {p}]]\n" + "".join(
        f"The contractor shall {words[(p + k) % 13]} the {words[(p * k) % 13]} works and report to the "
        f"{words[(k * 7 + p) % 13]} committee for page {p} item {k} without delay.\n" for k in range(80))
        for p in range(1, 9))
    parts = pf.chunks([("x.pdf", pages)], max_chars=40000)
    assert len(parts) > 1 and parts[0]["pages"].startswith("1-")
    assert all(len(c["text"]) <= 40000 for c in parts)


# ── reports from verified facts ─────────────────────────────────────────────

@pytest.fixture(scope="module")
def built():
    import pymupdf
    f = pr.build_facts(bid={"id": 5, "title": "Trunk Main Condition Survey", "client": "Riverside Utilities Board"},
                       fast_result={"report_facts": {"schema": pf.SCHEMA, "facts": GOOD, "coverage_gaps": []}},
                       documents=DOCS, analysis_date="2026-11-18")
    text = lambda pdf: re.sub(r"\s+", " ", " ".join(p.get_text() for p in pymupdf.open(stream=pdf, filetype="pdf")))  # noqa: E731
    return f, text(pr.render_snapshot(f)["pdf"]), text(pr.render_assessment(f, full_status="COMPLETE")["pdf"])


def test_reports_use_verified_facts_not_keyword_guesses(built):
    f, snap, full = built
    assert f["mode"] == "facts"
    assert f["identity"]["location"]["text"].startswith("Survey work is performed on site in the Western Network")
    assert "interactive style" not in snap  # a methodology sentence is never the location
    assert "9 Mill Lane, Easton Email" not in snap and "info@riverside.example" not in snap


def test_both_submission_methods_and_the_contact_are_kept_apart(built):
    _, snap, full = built
    assert "SUBMISSION METHODS" in snap
    assert "e-tender portal at https://etender.riverside.example" in snap
    assert "hand delivered to Room 12, 9 Mill Lane, Easton" in snap
    assert "QUESTIONS Questions may be e-mailed to queries@riverside.example" in snap
    assert "2 permitted submission methods" in full


def test_guarantee_conditions_and_unweighted_criteria(built):
    f, snap, full = built
    assert [s["text"] for s in f["securities"]][0].startswith("A performance guarantee of 10%")
    assert "guarantee" not in " ".join(q["text"] for q in f["qualifications"]).lower()
    assert "may be made only against an advance payment guarantee" in snap  # the condition is kept
    assert "Evaluation criteria and weights" not in snap  # no weight published -> no weights table
    assert "evaluated on methodology, experience and price" in snap


def test_basis_note_describes_checked_statements(built):
    _, snap, _ = built
    assert "was checked against the quoted source text on the cited page" in snap


def test_runs_without_report_facts_keep_the_digest_reading():
    f = pr.build_facts(bid={"id": 6}, fast_result={}, documents=DOCS, analysis_date="2026-11-18")
    assert f["mode"] == "digest"
    failed = pr.build_facts(bid={"id": 6}, fast_result={"report_facts": {"status": "FAILED", "facts": []}},
                            documents=DOCS, analysis_date="2026-11-18")
    assert failed["mode"] == "digest"


def test_coverage_gaps_of_the_facts_pass_are_disclosed():
    f = pr.build_facts(bid={"id": 7}, documents=DOCS, analysis_date="2026-11-18",
                       fast_result={"report_facts": {"facts": GOOD, "coverage_gaps": [
                           {"filename": DOC, "route": "REPORT_FACTS", "pages": "2", "reason": "OUTPUT_LIMIT"}]}})
    assert f["coverage_note"].startswith(f"FAST could not read 1 passage of the source in full (page 2 of {DOC})")


# ── FAST integration ────────────────────────────────────────────────────────

def test_fast_run_attaches_report_facts_to_the_persisted_result():
    import analysis_service as svc
    import fast_analysis as fa
    from concurrent.futures import Future
    result = fa.FastAnalysisResult(requirements=[], ambiguities={}, page_limits={}, batched_documents=[],
                                   skipped_documents=[], documents_by_route={})
    fut = Future()
    fut.set_result({"schema": pf.SCHEMA, "facts": GOOD, "coverage_gaps": [], "telemetry": [{"x": 1}]})
    svc._attach_report_facts(result, fut)
    assert result.report_facts["facts"] == GOOD and "telemetry" not in result.report_facts
    snap = fa.serialize_fast_analysis_result(result, engine_version="t")
    assert snap["schema_version"] == "1.4" and snap["result"]["report_facts"]["facts"] == GOOD
    bad = Future()
    bad.set_exception(RuntimeError("boom"))
    svc._attach_report_facts(result, bad)
    assert result.report_facts["status"] == "FAILED" and result.report_facts["facts"] == []


def test_assignment_delivery_field_becomes_a_verified_location_fact():
    a = dict(GOOD[0], delivery={"statement": "Survey work is on site in the Western Network.",
                                "quote": "All survey work shall be performed on site in the Western Network", "page": 1})
    v = pf.verify({"facts": [a]}, DOCS)
    loc = pf.by_category(v)["DELIVERY_LOCATION"]
    assert len(loc) == 1 and loc[0]["page"] == 1 and loc[0]["priority"] == 1
    # a delivery passage that is not in the document is dropped like any other fact
    bad = dict(GOOD[0], delivery={"statement": "Easton.", "quote": "Work is performed at the Easton head office.",
                                  "page": 1})
    assert "DELIVERY_LOCATION" not in pf.by_category(pf.verify({"facts": [bad]}, DOCS))
    f = pr.build_facts(bid={"id": 8}, documents=DOCS, analysis_date="2026-11-18",
                       fast_result={"report_facts": {"facts": [GOOD[0], GOOD[2]], "coverage_gaps": []}})
    assert f["identity"]["location"] is None  # missing -> disclosed as not identified, never guessed
