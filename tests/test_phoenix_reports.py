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
    assert 2 <= _pages(snap["pdf"]) <= 3
    assert 3 <= _pages(assess["pdf"]) <= 6
    assert snap["filename"].endswith("_Opportunity_Snapshot.pdf")
    assert assess["filename"].endswith("_Bid_Opportunity_Assessment.pdf")


def test_assessment_discloses_partial_and_missing_research(injaz_reports):
    text = re.sub(r"\s+", " ", injaz_reports[2])
    assert "completed partially" in text
    assert "External buyer research is not available" in text
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
         "url": "https://injaz-lebanon.org/about", "source_title": "About INJAZ", "published": "2025-03-03"}]}
    text = re.sub(r"\s+", " ", _pdf_text(pr.render_assessment(f, research=research)["pdf"]))
    assert "https://injaz-lebanon.org/about" in text and "2025-03-03" in text
    assert "do not indicate the buyer's preferences" in text
