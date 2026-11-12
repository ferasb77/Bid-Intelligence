"""Phoenix reporting & document intelligence upgrade.

* INJAZ Design Thinking ToR regression: the FAST Opportunity Snapshot and the
  FULL Bid Opportunity Assessment state what the RFP actually says (submission
  emails, required documents, scope/deliverables, evaluation criteria and
  weights) and never claim those are missing.
* Addendum scenario: an addendum that changes the deadline and adds a
  condition, plus a pricing workbook it references.
* No recommendation / scoring language in either PDF. Zero model calls.
"""
import io
import json
import re
from pathlib import Path

import pytest

import buyer_research
import change_tracking as ct
import phoenix_reports as pr
import procurement_digest as pdg
import workbook_intelligence as wbi

FIX = Path(__file__).parent / "fixtures"
TOR = "tor_for_gil_trainer_-design_thinking.pdf"
ADD = "Addendum_1_GIL_PR0018.pdf"
XLS = "GIL_Pricing_Schedule.xlsx"

ADDENDUM_TEXT = f"""[[SOURCE: {ADD} | PAGE: 1]]
ADDENDUM No. 1
Reference: IL/GIL2026/PR0018- Trainer for Design Thinking
This addendum amends the Terms of Reference issued for the above request.
1. The submission deadline is extended to November 20, 2026.
2. All applicants must submit a signed PSEA Code of Conduct declaration with their proposal.
3. The Quotation must be prepared using the Excel workbook GIL_Pricing_Schedule.xlsx (Annex 1), sheet Rates.
"""

FORBIDDEN = re.compile(
    r"(\bwe recommend\b|\brecommend(ed|ation)? (to )?(bid|not)\b|\bno-?bid\b|\bgo/no|win probability|"
    r"probability of (winning|award)|attractiveness|suitability score|\bshould (bid|pursue)\b)", re.I)
FALSE_ABSENCE = re.compile(
    r"(not specified|not stated|not provided|not defined|absent|no evaluation criteria|"
    r"no submission (method|documents)|missing information|does not (state|specify))", re.I)


def _injaz():
    result = json.loads((FIX / "injaz_fast_result.json").read_text(encoding="utf-8"))
    text = (FIX / "injaz_design_thinking_tor.txt").read_text(encoding="utf-8")
    return result, [(TOR, text)]


def _bid(**kw):
    b = {"id": 15, "title": "Trainer for Design Thinking", "client": "INJAZ Lebanon",
         "file_number": None, "submission_deadline": None}
    b.update(kw)
    return b


def _pdf_text(pdf: bytes) -> str:
    import pypdf
    return "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)


def _pages(pdf: bytes) -> int:
    import pypdf
    return len(pypdf.PdfReader(io.BytesIO(pdf)).pages)


def _workbook_bytes() -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Rates"
    ws.append(["Item", "Rate per training hour (USD)", "Hours", "Total cost"])
    ws.append(["Design Thinking track", None, 15, "=B2*C2"])
    ws.append(["Grand total", None, None, "=SUM(D2:D2)"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── digest ────────────────────────────────────────────────────────────────

def test_digest_recovers_injaz_sections_with_pages():
    _, docs = _injaz()
    secs = pdg.by_key(pdg.sections(docs))
    for key in ("overview", "scope", "deliverables", "timeline", "qualifications", "submission",
                "evaluation", "payment"):
        assert key in secs, key
    deliverables = [i for s in secs["deliverables"] for i in s["items"]]
    assert sum("(Session" in i["text"] for i in deliverables) == 6
    assert all(i["page"] == 2 for i in deliverables)


def test_submission_instructions_find_email_method_and_rules():
    _, docs = _injaz()
    sub = pdg.submission_instructions(docs)
    assert sub["channel"] == "Email"
    assert [e["email"] for e in sub["emails"]] == ["applicant.one@example.org", "applicant.two@example.org"]
    assert sub["emails"][0]["page"] == 3
    assert "subject line" in sub["subject_rule"]["text"]
    assert "shall not be considered" in sub["late_rule"]["text"]


# ── INJAZ regression: no false omission claims ─────────────────────────────

@pytest.fixture(scope="module")
def injaz_reports():
    result, docs = _injaz()
    f = pr.build_facts(bid=_bid(), fast_result=result, documents=docs, analysis_date="2026-11-12", run_id=10)
    snap = pr.render_snapshot(f)
    assess = pr.render_assessment(f, full_status="PARTIAL", research=None)
    return f, _pdf_text(snap["pdf"]), _pdf_text(assess["pdf"]), snap, assess


def test_injaz_facts_are_document_grounded(injaz_reports):
    f = injaz_reports[0]
    assert f["identity"]["organization"] == "INJAZ Lebanon"
    assert f["identity"]["reference"] == "IL/GIL2026/PR0018"
    assert f["deadline"]["effective"] == "2026-10-30" and f["deadline"]["extracted_ref"]["page"] == 3
    weights = {c["stage"]: c["weight"] for c in f["criteria"]}
    assert weights["Technical Evaluation"] == "60%" and weights["Financial Evaluation"] == "40%"
    assert pr.required_document_names(f)[:1] and any("Quotation" in d for d in pr.required_document_names(f))
    assert f["changes"] == []


@pytest.mark.parametrize("which", [1, 2])
def test_injaz_pdfs_state_what_the_rfp_says(injaz_reports, which):
    text = re.sub(r"\s+", " ", injaz_reports[which])
    for needle in ("applicant.one@example.org", "applicant.two@example.org", "Updated CV", "Technical Proposal",
                   "Quotation", "Availability Statement", "Validated Problem Statement", "Final 5-minute Pitch Deck",
                   "Curriculum Facilitation", "Technical Evaluation", "60%", "Financial Evaluation", "40%",
                   "25%", "15%", "October 2026", "wire transfer"):
        assert needle in text, needle
    assert not FALSE_ABSENCE.search(text), FALSE_ABSENCE.search(text)
    assert not FORBIDDEN.search(text), FORBIDDEN.search(text)
    assert "CRIT-" not in text and "REQ-" not in text and "OBL-" not in text  # no canonical IDs


def test_injaz_page_budgets(injaz_reports):
    _, _, _, snap, assess = injaz_reports
    assert _pages(snap["pdf"]) <= 2
    assert 3 <= _pages(assess["pdf"]) <= 6
    assert snap["filename"].endswith("_Opportunity_Snapshot.pdf")
    assert assess["filename"].endswith("_Bid_Opportunity_Assessment.pdf")


def test_assessment_discloses_partial_and_missing_research(injaz_reports):
    text = re.sub(r"\s+", " ", injaz_reports[2])
    assert "completed partially" in text
    assert "External buyer research has not yet been run" in text
    assert "does not recommend whether to bid" in text


def test_empty_ai_fields_are_not_reported_as_absent():
    """FAST extracted no evaluation criteria -> the digest's verbatim
    evaluation section is used, never 'no evaluation criteria'."""
    result, docs = _injaz()
    result = dict(result, evaluation_criteria=[], commercial_clauses=[], requirements=[])
    f = pr.build_facts(bid=_bid(), fast_result=result, documents=docs)
    text = re.sub(r"\s+", " ", _pdf_text(pr.render_snapshot(f)["pdf"]))
    assert "Technical Evaluation" in text and "60%" in text
    assert not FALSE_ABSENCE.search(text)


# ── addendum + spreadsheet scenario ─────────────────────────────────────────

def _addendum_case(previous=False):
    result, docs = _injaz()
    docs = docs + [(ADD, ADDENDUM_TEXT)]
    wb_bytes = _workbook_bytes()
    import extractor
    xtext, _ = extractor.extract_document_with_metadata(wb_bytes, XLS)
    docs.append((XLS, xtext))
    cur = dict(result)
    cur["doc_metadata_by_doc"] = dict(result["doc_metadata_by_doc"],
                                      **{ADD: {"file_number": "IL/GIL2026/PR0018", "submission_deadline": "2026-11-20"}})
    f = pr.build_facts(bid=_bid(), fast_result=cur, documents=docs, files=[(XLS, wb_bytes)],
                       previous_result=result if previous else None,
                       previous_doc_names=[TOR] if previous else None, analysis_date="2026-11-12")
    return f


def test_addendum_deadline_is_updated_with_old_value_and_source():
    f = _addendum_case()
    assert f["deadline"]["effective"] == "2026-11-20"
    assert f["deadline"]["amended_from"]["value"] == "2026-10-30"
    upd = [c for c in f["changes"] if c["kind"] == "UPDATED" and c["topic"] == "Submission deadline"]
    assert len(upd) == 1
    assert upd[0]["previous"] == "2026-10-30" and upd[0]["source"]["doc"] == ADD
    assert upd[0]["supersedes"]["doc"] == TOR and upd[0]["supersedes"]["page"] == 3


def test_addendum_deadline_read_from_text_when_fast_metadata_missing():
    result, docs = _injaz()
    dl = ct.effective_deadline(result, docs + [(ADD, ADDENDUM_TEXT)])
    assert dl["value"] == "2026-11-20" and dl["doc"] == ADD and dl["ref"]["page"] == 1
    assert dl["amended_from"]["value"] == "2026-10-30"
    assert ct.parse_date("closing on 5 March 2027 at noon") == "2027-03-05"
    assert ct.parse_date("no date here") is None


def test_addendum_new_condition_is_labelled_new_and_restatements_are_not():
    f = _addendum_case(previous=True)
    new = [c for c in f["changes"] if c["kind"] == "NEW"]
    assert any("PSEA Code of Conduct" in c["current"] for c in new)
    # the reference line restating the solicitation is not a change
    assert not any("Reference: IL/GIL2026/PR0018" in str(c["current"]) for c in f["changes"])


def test_changes_use_document_wording_once_and_ignore_ai_paraphrase():
    """Live finding: FAST paraphrased a workbook row into an invented
    '$15' rate and restated the addendum condition. Only the document's own
    words are published, once."""
    result, docs = _injaz()
    docs = docs + [(ADD, ADDENDUM_TEXT), (XLS, f"[[SOURCE: {XLS} | SHEET: Rates | ROWS: 1-2]]\nRow 2: Design Thinking track | 15")]
    psea = "All applicants must submit a signed PSEA Code of Conduct declaration with their proposal."
    cur = dict(result, requirements=list(result["requirements"]) + [
        {"description": "Applicants are required to provide a PSEA declaration.", "source_refs": [
            {"source_doc": ADD, "page": 1, "excerpt": psea}]},
        {"description": "Pricing uses a rate of $15 USD per hour.", "source_refs": [
            {"source_doc": XLS, "sheet": "Rates", "excerpt": "Row 2: Design Thinking track | 15"}]},
        {"description": "Invented condition.", "source_refs": [
            {"source_doc": ADD, "page": 1, "excerpt": "Bidders must hold ISO 9001 certification for all trainers."}]},
    ])
    changes = ct.detect_changes(cur, docs, result, [TOR])
    texts = [str(c["current"]) for c in changes]
    assert sum("PSEA Code of Conduct" in t for t in texts) == 1
    assert not any("$15" in t or "ISO 9001" in t or "Invented" in t for t in texts)


def test_workbook_purpose_formulas_and_addendum_link():
    f = _addendum_case()
    (wb,) = f["workbooks"]
    assert wb["purpose"] == "Pricing / financial schedule" and wb["purpose_status"] == "identified"
    sheet = wb["sheets"][0]
    assert sheet["name"] == "Rates" and sheet["header_row"] == 1 and sheet["formula_count"] == 2
    assert sheet["formula_samples"][0] == {"cell": "D2", "formula": "=B2*C2"}
    assert wb["references"][0]["status"] == "linked" and wb["references"][0]["doc"] == ADD


def test_unverifiable_workbook_purpose_is_unconfirmed():
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.append(["Alpha", "Beta"])
    buf = io.BytesIO()
    wb.save(buf)
    prof = wbi.profile_workbook("data.xlsx", buf.getvalue())
    assert prof["purpose"] is None and prof["purpose_status"] == "unconfirmed"
    assert wbi.find_references(prof, [("rfp.pdf", "[[SOURCE: rfp.pdf | PAGE: 1]]\nNothing relevant here.")]) == []


def test_addendum_pdfs_show_labels_and_no_invented_values():
    f = _addendum_case(previous=True)
    snap = re.sub(r"\s+", " ", _pdf_text(pr.render_snapshot(f)["pdf"]))
    full = re.sub(r"\s+", " ", _pdf_text(pr.render_assessment(f, full_status="COMPLETE")["pdf"]))
    assert "20 November 2026" in snap and "UPDATED INFORMATION" in snap and "previously 30 October 2026" in snap
    for needle in ("UPDATED INFORMATION", "NEW INFORMATION", "PSEA Code of Conduct", "GIL_Pricing_Schedule.xlsx",
                   "Pricing / financial schedule", "=B2*C2"):
        assert needle in full, needle
    assert not FORBIDDEN.search(snap + full)


def test_manual_deadline_is_flagged_and_original_kept():
    result, docs = _injaz()
    f = pr.build_facts(bid=_bid(submission_deadline="2026-12-01"), fast_result=result, documents=docs)
    assert f["deadline"]["effective"] == "2026-12-01" and f["deadline"]["extracted"] == "2026-10-30"
    text = re.sub(r"\s+", " ", _pdf_text(pr.render_snapshot(f)["pdf"]))
    assert "MANUALLY ENTERED BY PHOENIX" in text and "Documents state 30 October 2026" in text


def test_is_amending_document():
    assert ct.is_amending_document("Addendum_1.pdf")
    assert ct.is_amending_document("x.pdf", "[[SOURCE: x.pdf | PAGE: 1]]\nCORRIGENDUM No 2")
    assert not ct.is_amending_document("tor_for_gil_trainer.pdf", "Terms of Reference")


# ── buyer research: only URLs the search really returned ───────────────────

class _Resp:
    def __init__(self, content, stop="end_turn"):
        self._d = {"content": content, "stop_reason": stop}
        self.usage = None

    def model_dump(self):
        return self._d


class _Client:
    def __init__(self, resp):
        self.calls = []
        self.resp = resp
        self.beta = self
        self.messages = self

    def with_options(self, **kw):
        return self

    def create(self, **kw):
        self.calls.append(kw)
        return self.resp


def test_buyer_research_keeps_only_returned_urls():
    content = [
        {"type": "web_search_tool_result", "content": [
            {"type": "web_search_result", "url": "https://injaz-lebanon.org/about", "title": "About INJAZ",
             "page_age": "March 3, 2025"}]},
        {"type": "text", "text": '<items>[{"topic":"profile","statement":"INJAZ Lebanon is a member of INJAZ Al-Arab.",'
                                 '"url":"https://injaz-lebanon.org/about/","published":null},'
                                 '{"topic":"news","statement":"Invented fact.","url":"https://made-up.example/x",'
                                 '"published":"2026"}]</items>'},
    ]
    client = _Client(_Resp(content))
    out = buyer_research.run_research("INJAZ Lebanon", "Trainer for Design Thinking", "IL/GIL2026/PR0018",
                                      None, anthropic_client=client)
    assert out["status"] == "COMPLETE"
    assert [i["url"] for i in out["items"]] == ["https://injaz-lebanon.org/about"]
    assert out["items"][0]["published"] == "2025-03-03"
    call = client.calls[0]
    assert call["tools"][0]["type"] == "web_search_20260209" and call["tools"][0]["max_uses"] <= 5
    assert call["model"] == "claude-opus-5-5"
    assert "Never infer" in call["system"]


def test_buyer_research_in_assessment_has_url_and_date(injaz_reports):
    f = injaz_reports[0]
    research = {"status": "COMPLETE", "researched_at": "2026-11-12T10:00:00+00:00", "items": [
        {"topic": "profile", "statement": "INJAZ Lebanon is a member of INJAZ Al-Arab.",
         "url": "https://injaz-lebanon.org/about", "source_title": "About INJAZ", "published": "2025-03-03",
         "connection": "The page names the GIL programme."},
        {"topic": "news", "statement": "INJAZ Lebanon held a youth summit.", "url": "https://injaz-lebanon.org/news",
         "source_title": "News", "published": None, "connection": None}]}
    text = re.sub(r"\s+", " ", _pdf_text(pr.render_assessment(f, research=research)["pdf"]))
    assert "https://injaz-lebanon.org/about" in text and "2025-03-03" in text
    assert "do not indicate the buyer's preferences" in text
    assert "The page names the GIL programme." in text and "Background on the buyer" in text
    assert "undated" in text and "2 verified external finding(s)" in text


# ── V2: evaluation weight hierarchy (generic, arithmetic-first) ─────────────

def test_child_weight_basis_rule():
    assert pr.child_weight_basis("Technical Evaluation", "60%", ["25%", "15%", "10%", "10%"], []) == "overall"
    assert pr.child_weight_basis("Financial Evaluation", "40%", ["40%"], []) == "overall"
    assert pr.child_weight_basis("Technical Proposal", "70%", ["50%", "30%", "20%"], []) == "within"
    assert pr.child_weight_basis("Technical", "60%", ["30%", "20%"], ["Approach (30% of the technical score)"]) == "within"
    assert pr.child_weight_basis("Technical", "60%", ["30%", "20%"], []) == "published"
    assert pr.child_weight_basis("Technical", "60%", ["30%", None], []) == "published"


def test_injaz_weights_are_overall_shares_without_parent_qualifier(injaz_reports):
    f, snap, full = injaz_reports[0], injaz_reports[1], injaz_reports[2]
    kids = [c for c in f["criteria"] if c["level"] == 1]
    assert len(kids) == 5 and all(c["basis"] == "overall" for c in kids)
    for text in (snap, full):
        t = re.sub(r"\s+", " ", text)
        assert "of Technical Evaluation" not in t and "of Financial Evaluation" not in t
        assert "Technical Evaluation 60% = 25% + 15% + 10% + 10%" in t
        assert "Financial Evaluation 40% = 40%" in t


def test_calgary_weights_and_pricing_form_excluded():
    """Independent package: Key/Other Personnel 10% + 10% = Team 20% are
    overall shares; the price form's 55/35/10 item weights are price
    calculation, not evaluation criteria."""
    snap = json.loads((FIX / "calgary_26_1603_run34_raw_snapshot.json").read_text(encoding="utf-8"))["result"]
    docs = []
    for ec in snap["evaluation_criteria"]:
        for r in ec.get("source_refs") or []:
            if r.get("excerpt"):
                docs.append((r.get("source_doc") or "rfp.docx", f"[[SOURCE: {r.get('source_doc')} | PAGE: 1]]\n{r['excerpt']}"))
    f = pr.build_facts(bid={"id": 1, "title": "Leadership L&D", "client": None}, fast_result=snap, documents=docs)
    stages = [c["stage"] for c in f["criteria"]]
    assert not any(s.startswith("Item ") for s in stages)
    team = [c for c in f["criteria"] if c["level"] == 1 and "Personnel" in c["stage"]]
    assert team and all(c["basis"] == "overall" for c in team)
    assert len({(c["stage"], c["weight"]) for c in f["criteria"]}) == len(f["criteria"])  # no duplicates
    text = re.sub(r"\s+", " ", _pdf_text(pr.render_snapshot(f)["pdf"]))
    assert "of Team Experience" not in text and "Pricing Form" not in text


# ── V2: concise, non-repeating reports ─────────────────────────────────────

SNAP_TITLES = ("1. Opportunity at a Glance", "2. Scope and Delivery Essentials", "3. Evaluation and Eligibility",
               "4. Commercial and Submission Essentials")
FULL_TITLES = ("1. Executive Intelligence Summary", "2. Opportunity and Delivery Requirements", "3. Buyer Intelligence",
               "4. Evaluation and Commercial Intelligence", "5. Material Information and Amendments",
               "6. Management Decision Reference")


def test_section_structure(injaz_reports):
    snap, full = (re.sub(r"\s+", " ", t) for t in injaz_reports[1:3])
    for t in SNAP_TITLES:
        assert t in snap, t
    assert "Additional Material Facts" not in snap  # nothing left to add for the original ToR
    for t in FULL_TITLES:
        assert t in full, t


@pytest.mark.parametrize("which", [1, 2])
def test_statements_are_printed_once(injaz_reports, which):
    t = re.sub(r"\s+", " ", injaz_reports[which])
    for needle in ("inclusive of all costs", "Total estimated cost", "shall not be considered",
                   "won't handle any transfer", "30 October 2026", "Payment shall be made by wire transfer",
                   "within 5 days of track completion"):
        assert t.lower().count(needle.lower()) == 1, (needle, t.lower().count(needle.lower()))
    assert not re.search(r"\b\d+ stated\b", t)
    assert "for whatever reason" not in t  # late rule summarised, not quoted
    assert "Please submit the following documents via email" not in t  # no verbatim submission instruction


def test_quantities_presented_as_published(injaz_reports):
    f = injaz_reports[0]
    snap = re.sub(r"\s+", " ", injaz_reports[1])
    assert "6-session" in snap and "aged 18" in snap
    assert "5 days × 3 hours per day" in snap and "five (5)-days" in snap
    assert any("five 5 days" in pdg.fold(x["text"]) for x in f["quantities"])
    assert all(x["page"] for x in f["quantities"])


def test_pricing_kept_apart_from_required_documents(injaz_reports):
    f = injaz_reports[0]
    assert pr.required_document_names(f) == ["Updated CV", "Technical Proposal (Brief)", "Quotation",
                                             "Availability Statement"]
    assert [p["text"][:20] for p in f["pricing"]] == ["The rate per trainin", "Total estimated cost"]


def test_addendum_snapshot_lists_new_facts_once_with_labels():
    f = _addendum_case(previous=True)
    snap_pdf = pr.render_snapshot(f)["pdf"]
    snap = re.sub(r"\s+", " ", _pdf_text(snap_pdf))
    full = re.sub(r"\s+", " ", _pdf_text(pr.render_assessment(f, full_status="COMPLETE")["pdf"]))
    assert "5. Additional Material Facts" in snap and "NEW INFORMATION" in snap
    assert snap.count("PSEA Code of Conduct") == 1 and full.count("PSEA Code of Conduct") == 1
    assert "$15" not in snap + full
    assert _pages(snap_pdf) <= 2


# ── V2: independent fictional package with a different structure ───────────

LIB = "RFT-2027-014_Digital_Literacy.pdf"


def _library():
    text = (FIX / "fictional_library_rft.txt").read_text(encoding="utf-8")

    def ec(stage, weight, parent, excerpt, page=2):
        return {"stage": stage, "weight": weight, "parent_stage": parent, "weight_basis": "Overall",
                "source_refs": [{"source_doc": LIB, "page": page, "excerpt": excerpt}]}
    result = {
        "doc_metadata_by_doc": {LIB: {"client": "Harbourview Municipal Library Board", "file_number": "RFT-2027-014",
                                      "submission_deadline": "2027-03-15"}},
        "evaluation_criteria": [
            ec("Technical Proposal", "70%", "Evaluation Criteria", "Technical Proposal – 70%"),
            ec("Methodology", "50%", "Technical Proposal", "Methodology (50%) - approach to adult learners"),
            ec("Team", "30%", "Technical Proposal", "Team (30%) - facilitator qualifications and bilingual capacity."),
            ec("Experience", "20%", "Technical Proposal", "Experience (20%) - comparable workshop programmes"),
            ec("Price", "30%", "Evaluation Criteria", "Price – 30%"),
        ],
        "requirements": [], "commercial_clauses": [], "canonical_milestones": [],
    }
    bid = {"id": 99, "title": "Digital Literacy Workshop Series for Older Adults",
           "client": "Harbourview Municipal Library Board", "file_number": None, "submission_deadline": None}
    return pr.build_facts(bid=bid, fast_result=result, documents=[(LIB, text)], analysis_date="2026-11-12")


def test_independent_package_reports():
    f = _library()
    assert f["deadline"]["effective"] == "2027-03-15"
    assert all(c["basis"] == "within" for c in f["criteria"] if c["level"] == 1)  # 50 + 30 + 20 = 100
    snap_pdf = pr.render_snapshot(f)["pdf"]
    snap = re.sub(r"\s+", " ", _pdf_text(snap_pdf))
    full = re.sub(r"\s+", " ", _pdf_text(pr.render_assessment(f, full_status="COMPLETE",
                                                              research={"status": "FAILED"})["pdf"]))
    assert _pages(snap_pdf) <= 2
    assert "50% of Technical Proposal" in snap and "15 March 2027" in snap
    assert "Electronic submission" in snap
    assert "CAD 45,000" in snap and "net 30 days" in snap
    assert "40 workshops of 2 hours" in snap
    for t in FULL_TITLES:
        assert t in full, t
    assert "attempted" in full and "did not complete" in full
    for text in (snap, full):
        assert not FALSE_ABSENCE.search(text) and not FORBIDDEN.search(text)


# ── V2: buyer research states, persistence and reuse (no network) ──────────

@pytest.mark.parametrize("research,needle", [
    (None, "has not yet been run"),
    ({"status": "RUNNING", "started_at": "2026-11-12T10:00:00+00:00"}, "was in progress"),
    ({"status": "FAILED", "started_at": "2026-11-12T10:00:00+00:00"}, "did not complete"),
    ({"status": "SKIPPED"}, "buyer organisation is not identified"),
    ({"status": "COMPLETE", "items": [], "researched_at": "2026-11-12T10:00:00+00:00"}, "found no public sources"),
])
def test_assessment_states_research_state(injaz_reports, research, needle):
    text = re.sub(r"\s+", " ", _pdf_text(pr.render_assessment(injaz_reports[0], research=research)["pdf"]))
    assert needle in text


class _Store:
    def __init__(self, runs):
        self.files, self.runs = {}, runs

    def install(self, monkeypatch):
        import database as db
        monkeypatch.setattr(db, "download_file", lambda p: self.files.get(p))
        monkeypatch.setattr(db, "upload_json_object", lambda p, d: self.files.__setitem__(p, json.dumps(d).encode()))
        monkeypatch.setattr(db, "list_analysis_runs", lambda b: self.runs)
        monkeypatch.setattr(db, "get_bid", lambda b: {"id": b, "client": "INJAZ Lebanon",
                                                      "title": "Trainer for Design Thinking", "file_number": None})


def test_research_reused_across_runs_of_same_bid(monkeypatch):
    store = _Store([{"id": 21, "analysis_mode": "FULL", "created_at": "2026-11-10"},
                    {"id": 22, "analysis_mode": "FULL", "created_at": "2026-11-11"}])
    store.install(monkeypatch)
    started = []
    monkeypatch.setattr(buyer_research, "start_background", lambda *a: started.append(a) or True)
    store.files["15/buyer_research/21.json"] = json.dumps({
        "status": "COMPLETE", "items": [{"statement": "x", "url": "https://e.org"}],
        "query": {"client": "INJAZ Lebanon", "title": "Trainer for Design Thinking"}}).encode()
    out = buyer_research.ensure(15, 22, "key")
    assert out["status"] == "COMPLETE" and out["reused_from_run"] == 21 and not started
    assert json.loads(store.files["15/buyer_research/22.json"])["reused_from_run"] == 21
    assert buyer_research.for_report(15, 22)["items"][0]["url"] == "https://e.org"


def test_research_started_once_and_failed_not_retried(monkeypatch):
    from datetime import datetime, timedelta, timezone
    store = _Store([{"id": 30, "analysis_mode": "FULL", "created_at": "2026-11-12"}])
    store.install(monkeypatch)
    started = []
    monkeypatch.setattr(buyer_research, "start_background", lambda *a: started.append(a) or True)
    assert buyer_research.ensure(15, 30, None) is None and not started  # no key -> nothing paid
    buyer_research.ensure(15, 30, "key")
    assert started == [(15, 30, "key")]
    old = (datetime.now(timezone.utc) - timedelta(seconds=buyer_research.STALE_AFTER_SECONDS + 5)).isoformat()
    store.files["15/buyer_research/30.json"] = json.dumps({"status": "RUNNING", "started_at": old}).encode()
    assert buyer_research.load(15, 30)["status"] == "FAILED"  # orphaned by a restart
    assert buyer_research.ensure(15, 30, "key")["status"] == "FAILED" and len(started) == 1
    assert buyer_research.STALE_AFTER_SECONDS < 300


def test_research_prompt_targets_procurement_context_and_keeps_connection():
    content = [
        {"type": "web_search_tool_result", "content": [
            {"type": "web_search_result", "url": "https://injaz-lebanon.org/gil", "title": "GIL", "page_age": None}]},
        {"type": "text", "text": '<items>[{"topic":"initiative","statement":"GIL runs in Akkar.",'
                                 '"connection":"The page describes the GIL programme named in the ToR.",'
                                 '"url":"https://injaz-lebanon.org/gil","published":"2026-02"}]</items>'},
    ]
    client = _Client(_Resp(content))
    out = buyer_research.run_research("INJAZ Lebanon", "Trainer for Design Thinking", None, None,
                                      anthropic_client=client, context="The GIL 2026-2028 program ...")
    assert out["items"][0]["connection"].startswith("The page describes")
    assert out["items"][0]["published"] == "2026-02" and out["items"][0]["topic"] == "initiative"
    prompt = client.calls[0]["messages"][0]["content"]
    assert "The GIL 2026-2028 program" in prompt and "connection" in prompt
