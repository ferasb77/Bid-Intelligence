"""Regression tests for the three defects found by the Phoenix Beta live runs
of b81e5a9 (2026-11-17), plus the scanned-page (OCR) number rule.

The inputs are the live runs' own saved outputs, not new model calls:

* fixtures/arabic/live_fast_snapshot_run16.json -- the raw FAST snapshot of
  the live Arabic run (synthetic fixture package, real model output);
* fixtures/injaz_run15_evaluation_criteria.json -- the evaluation criteria of
  the live English INJAZ run, which carried heading-only duplicates.

1. Opportunity identity comes from the primary solicitation; an addendum
   (recognised by an Arabic or English file name, or by its own amendment
   heading) never supplies the title.
2. The submission e-mail stated in the Arabic RFP ("Proposals are to be sent
   by email to ...") reaches both PDFs with its source reference.
3. Duplicate extractions of one criterion are merged without merging
   distinct criteria or changing any weight.
4. Numbers on OCR'd (scanned) pages are never reported as checked facts.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import canonical_procurement as cp
import change_tracking as ct
import extractor as ex
import procurement_digest as pdg
import procurement_normalization as pn
import source_translation as sx

FIX = Path(__file__).parent / "fixtures"
RFP, ADD, XLS = "كراسة الشروط.pdf", "ملحق تعديل رقم 1.pdf", "جدول الكميات.xlsx"
RFP_TITLE = "Request for Proposals No. 2026/45: Provision of Entrepreneurship Training Services for Youth"
EMAIL = "tenders@rural-dev.example.org"


def _snapshot() -> dict:
    return json.loads((FIX / "arabic" / "live_fast_snapshot_run16.json").read_text(encoding="utf-8"))


def _package():
    files, _ = ex.unpack_procurement_package(
        [("arabic_package.zip", (FIX / "arabic" / "arabic_package.zip").read_bytes())])
    files = [(n, b) for n, b in files if n in (RFP, ADD, XLS)]
    docs = [(n, ex.extract_document_with_metadata(b, n)[0]) for n, b in files]
    return files, docs


def _pdf_text(pdf: bytes) -> str:
    import pymupdf
    return re.sub(r"\s+", " ", "\n".join(p.get_text() for p in pymupdf.open(stream=pdf, filetype="pdf")))


@pytest.fixture(scope="module")
def live_reports():
    import bid_identity
    import phoenix_reports as pr
    files, docs = _package()
    # as in analysis_service: the placeholder bid identity is filled from FAST's grounded identity
    ident = bid_identity.resolve_from_fast_result(
        SimpleNamespace(doc_metadata_by_doc=_snapshot()["result"]["doc_metadata_by_doc"]), [t for _, t in docs])
    facts = pr.build_facts(bid={"id": 17, "title": ident["title"] or bid_identity.PLACEHOLDER_TITLE,
                                "client": ident["client"] or bid_identity.PLACEHOLDER_CLIENT},
                           fast_result=_snapshot()["result"], documents=docs, files=files,
                           analysis_date="2026-11-17", run_id=16)
    return SimpleNamespace(facts=facts, snap=_pdf_text(pr.render_snapshot(facts)["pdf"]),
                           full=_pdf_text(pr.render_assessment(facts, full_status="COMPLETE")["pdf"]))


# ═══════════════════════════════════════════════════════════════════════
# 1. Opportunity identity
# ═══════════════════════════════════════════════════════════════════════

class TestIdentityFromPrimarySolicitation:
    def test_arabic_names_classified(self):
        assert cp.classify_identity_role(ADD) == cp.IDENTITY_ROLE_AMENDMENT
        assert cp.classify_identity_role(RFP) == cp.IDENTITY_ROLE_PRIMARY_SOLICITATION
        assert cp.classify_identity_role(XLS) == cp.IDENTITY_ROLE_SUPPORTING
        assert cp.classify_identity_role("محضر الرد على الاستفسارات.pdf") == cp.IDENTITY_ROLE_QA_LOG
        # "تعديل" alone also means "modification": a genuine opportunity name stays primary
        assert cp.classify_identity_role("خدمات تعديل المباني.pdf") == cp.IDENTITY_ROLE_PRIMARY_SOLICITATION

    @pytest.mark.parametrize("reverse", [False, True])
    def test_live_arabic_metadata_any_order(self, reverse):
        meta = _snapshot()["result"]["doc_metadata_by_doc"]
        if reverse:
            meta = dict(reversed(list(meta.items())))
        merged = cp.merge_identity_fields(meta)
        assert merged["title"] == RFP_TITLE
        assert merged["client"] == "Ministry of Rural Development"
        # the addendum still governs the deadline it amends
        assert cp.merge_identity_fields_with_provenance(meta)["submission_deadline"] == ("2026-12-15", ADD)

    def test_generic_file_names_use_the_documents_own_heading(self):
        meta = {"doc1.pdf": {"title": "Addendum No. 2 to RFP 2026-026", "file_number": "2026-026"},
                "doc2.pdf": {"title": "Janitorial Services for City Hall", "client": "City of Example"}}
        assert cp.merge_identity_fields(meta)["title"] == "Janitorial Services for City Hall"
        meta_ar = {"a.pdf": {"title": "Notice", "title_original": "ملحق تعديل رقم (٢)"},
                   "b.pdf": {"title": "Supply of Office Furniture"}}
        assert cp.merge_identity_fields(meta_ar)["title"] == "Supply of Office Furniture"

    def test_genuine_titles_are_not_demoted(self):
        for title in ("Amendment of Zoning By-law Consulting Services", "Request for Proposals No. 2026/45",
                      "Errata Management Platform Implementation"):
            assert not cp.is_amendment_title(title), title
        meta = {"rfp.pdf": {"title": "Amendment of Zoning By-law Consulting Services"}}
        assert cp.merge_identity_fields(meta)["title"] == "Amendment of Zoning By-law Consulting Services"

    def test_addendum_only_package_still_gets_best_available_title(self):
        assert cp.merge_identity_fields({"x.pdf": {"title": "Addendum No. 1"}})["title"] == "Addendum No. 1"

    def test_bid_identity_fill_uses_rfp_title(self):
        import bid_identity
        _, docs = _package()
        result = SimpleNamespace(doc_metadata_by_doc=_snapshot()["result"]["doc_metadata_by_doc"])
        got = bid_identity.resolve_from_fast_result(result, [t for _, t in docs])
        assert got["title"] == "Provision of Entrepreneurship Training Services for Youth"
        assert got["client"] == "Ministry of Rural Development"

    def test_reports_carry_rfp_title(self, live_reports):
        assert live_reports.facts["identity"]["title"] == "Provision of Entrepreneurship Training Services for Youth"
        for text in (live_reports.snap, live_reports.full):
            assert "Provision of Entrepreneurship Training Services for Youth" in text
            assert "Addendum No. 1" not in text


# ═══════════════════════════════════════════════════════════════════════
# 2. Submission e-mail
# ═══════════════════════════════════════════════════════════════════════

class TestSubmissionEmail:
    @pytest.mark.parametrize("sentence", [
        "Proposals are to be sent by email to tenders@rural-dev.example.org",
        "Bids shall be emailed to tenders@rural-dev.example.org before the deadline.",
        "Offers must be delivered to tenders@rural-dev.example.org.",
        "Submit your proposal to tenders@rural-dev.example.org.",
    ])
    def test_method_phrasings(self, sentence):
        docs = [("rfp.pdf", f"[[SOURCE: rfp.pdf | PAGE: 2]]\n{sentence}")]
        sub = pdg.submission_instructions(docs)
        assert [e["email"] for e in sub["emails"]] == [EMAIL]
        e = sub["emails"][0]
        assert (e["doc"], e["page"]) == ("rfp.pdf", 2) and EMAIL in e["sentence"]["text"]
        assert sub["channel"] == "Email"

    def test_enquiry_contact_is_not_the_submission_channel(self):
        docs = [("rfp.pdf", "[[SOURCE: rfp.pdf | PAGE: 1]]\nQuestions must be sent to info@buyer.example.org.\n"
                            "Questions about the proposal should be sent to info@buyer.example.org.")]
        assert pdg.submission_instructions(docs)["emails"] == []

    def test_live_arabic_email_with_reference(self, live_reports):
        sub = live_reports.facts["submission"]
        assert [e["email"] for e in sub["emails"]] == [EMAIL]
        e = sub["emails"][0]
        assert e["doc"] == RFP and e["page"] == 2
        assert "ترسل العروض" in (e["sentence"].get("original") or "")  # the original Arabic line
        for text in (live_reports.snap, live_reports.full):
            assert EMAIL in text
            assert re.search(r"Email to tenders@rural-dev\.example\.org.{0,40}D\d p\.2", text), text[:4000]


# ═══════════════════════════════════════════════════════════════════════
# 3. Duplicate evaluation criteria
# ═══════════════════════════════════════════════════════════════════════

def _run15():
    return json.loads((FIX / "injaz_run15_evaluation_criteria.json").read_text(encoding="utf-8"))["evaluation_criteria"]


def _crit(stage, weight, parent, excerpt, doc="d.pdf"):
    return {"stage": stage, "weight": weight, "parent_stage": parent, "source_doc": doc,
            "source_refs": [{"source_doc": doc, "page": 3, "excerpt": excerpt}]}


class TestCriteriaDedupe:
    def test_live_injaz_duplicates_merged_weights_unchanged(self):
        raw = _run15()
        out = pn.dedupe_evaluation_criteria(raw)
        assert len(raw) == 14 and len(out) == 7
        weights = sorted((c["parent_stage"] or "", c["weight"]) for c in out)
        assert weights == sorted([("", "60%"), ("", "40%"), ("Technical Evaluation", "25%"),
                                  ("Technical Evaluation", "15%"), ("Technical Evaluation", "10%"),
                                  ("Technical Evaluation", "10%"), ("Financial Evaluation", "40%")])
        stages = [c["stage"] for c in out]
        assert any(s.startswith("Soft Skills:") for s in stages) and any(s.startswith("Technical Literacy:") for s in stages)
        assert "Expertise" not in stages  # heading-only copy merged into the descriptive one
        assert raw == _run15()  # input not mutated

    def test_distinct_and_conflicting_criteria_are_kept(self):
        same_weight = [_crit("Soft Skills", "10%", "Technical", "Soft Skills: storytelling (10%)"),
                       _crit("Technical Literacy", "10%", "Technical", "Technical Literacy: digital tools (10%)")]
        assert len(pn.dedupe_evaluation_criteria(same_weight)) == 2
        conflict = [_crit("Methodology", "25%", "Technical", "Methodology 25%"),
                    _crit("Methodology", "30%", "Technical", "Methodology 30%")]
        assert len(pn.dedupe_evaluation_criteria(conflict)) == 2
        other_section = [_crit("Experience", "20%", "Technical", "Experience 20% of the technical score"),
                         _crit("Experience: years of relevant work", "20%", "Technical",
                               "Key personnel: years of relevant work (20%)")]
        assert len(pn.dedupe_evaluation_criteria(other_section)) == 2  # no shared passage
        other_doc = [_crit("Price", "40%", None, "Price 40%", doc="a.pdf"),
                     _crit("Price", "40%", None, "Price 40%", doc="b.pdf")]
        assert len(pn.dedupe_evaluation_criteria(other_doc)) == 2

    def test_reports_show_each_criterion_once(self):
        import phoenix_reports as pr
        result = json.loads((FIX / "injaz_fast_result.json").read_text(encoding="utf-8"))
        result["evaluation_criteria"] = _run15()
        text = (FIX / "injaz_design_thinking_tor.txt").read_text(encoding="utf-8")
        facts = pr.build_facts(bid={"id": 15, "title": "Trainer for Design Thinking", "client": "INJAZ Lebanon"},
                               fast_result=result, documents=[("tor_for_gil_trainer_-design_thinking.pdf", text)],
                               analysis_date="2026-11-17", run_id=15)
        labels = [pdg.fold(re.split(r"[:(–-]", c["stage"])[0]) for c in facts["criteria"]]
        assert len(labels) == len(set(labels)), labels
        assert {c["weight"] for c in facts["criteria"]} >= {"60%", "40%", "25%", "15%", "10%"}
        for pdf in (pr.render_snapshot(facts)["pdf"], pr.render_assessment(facts, full_status="COMPLETE")["pdf"]):
            t = _pdf_text(pdf)
            assert t.count("— Knowledge") == 1 and t.count("— Soft Skills") == 1, t
            assert "Technical Evaluation 60% = 25% + 15% + 10% + 10%" in t

    def test_fast_merge_applies_dedupe(self):
        import inspect
        import fast_analysis
        assert "dedupe_evaluation_criteria(result.evaluation_criteria)" in inspect.getsource(
            fast_analysis.run_fast_analysis_corpus)


# ═══════════════════════════════════════════════════════════════════════
# 4. Scanned (OCR) pages: numbers are never checked facts
# ═══════════════════════════════════════════════════════════════════════

OCR_DOC = ("scan.pdf", "[[SOURCE: scan.pdf | PAGE: 1 | OCR: tesseract]]\n"
                       "آخر موعد لتقديم العروض هو ٣٠ تشرين الثاني ٢٠٢٦\n"
                       "المنهجية\n"
                       "١٠٠١١\n"
                       "[[SOURCE: scan.pdf | PAGE: 2]]\n"
                       "العرض الفني ٧٠٪")


class TestOcrNumbers:
    def test_ocr_lines_with_numbers_are_withheld_and_flagged(self):
        segs = sx.segment_documents([OCR_DOC])["scan.pdf"]["segments"]
        by_line = {s["original"]: s for s in segs}
        assert by_line["المنهجية"].get("ocr") and by_line["آخر موعد لتقديم العروض هو ٣٠ تشرين الثاني ٢٠٢٦"].get("ocr")
        assert not by_line["العرض الفني ٧٠٪"].get("ocr")  # page 2 has a text layer
        s = sx.apply_translation(by_line["آخر موعد لتقديم العروض هو ٣٠ تشرين الثاني ٢٠٢٦"],
                                 "The deadline for proposals is 30 November 2026")
        assert s["status"] == sx.WITHHELD and s["issues"][0] == sx.OCR_NUMERIC_ISSUE
        assert sx.apply_translation(by_line["المنهجية"], "Methodology")["status"] == sx.CHECKED
        assert sx.apply_translation(by_line["العرض الفني ٧٠٪"], "Technical Proposal 70%")["status"] == sx.CHECKED

    def test_english_view_and_report_note(self):
        segs = sx.segment_documents([OCR_DOC])
        for seg, en in zip(segs["scan.pdf"]["segments"],
                           ["The deadline for proposals is 30 November 2026", "Methodology", "Technical Proposal 70%"]):
            sx.apply_translation(seg, en)
        payload = {"documents": segs}
        view = sx.english_view([OCR_DOC], payload)[0][1]
        assert "30 November" not in view and "10011" not in view  # OCR'd digits never reach the reports
        assert "Methodology" in view and "Technical Proposal 70%" in view
        assert sx.summarize(payload)["ocr_uncertain"] == 1
        assert "UNVERIFIED: 1 line(s) from scanned pages" in sx.payload_summary_line(payload)

    def test_ocr_only_deadline_is_marked_unverified(self):
        docs = [("scan.pdf", "[[SOURCE: scan.pdf | PAGE: 1 | OCR: tesseract]]\nMethodology")]
        dl = ct.effective_deadline({"doc_metadata_by_doc": {"scan.pdf": {"submission_deadline": "2026-11-30"}}}, docs)
        assert dl["value"] == "2026-11-30" and dl["unverified"] == "OCR"
        text = [("rfp.pdf", "[[SOURCE: rfp.pdf | PAGE: 1]]\nThe deadline for submission is 30 November 2026.")]
        dl = ct.effective_deadline({"doc_metadata_by_doc": {"rfp.pdf": {"submission_deadline": "2026-11-30"}}}, text)
        assert "unverified" not in dl


# ═══════════════════════════════════════════════════════════════════════
# Existing behaviour on the live Arabic output stays correct
# ═══════════════════════════════════════════════════════════════════════

def test_live_arabic_deadline_amendment_and_weights_unchanged(live_reports):
    f = live_reports.facts
    assert f["deadline"]["effective"] == "2026-12-15" and f["deadline"]["extracted_ref"]["doc"] == ADD
    assert f["deadline"]["amended_from"]["value"] == "2026-11-30"
    assert "آخر موعد" in f["deadline"]["amended_from"]["ref"]["original"]
    crit = {c["stage"]: c for c in f["criteria"]}
    assert crit["Technical Proposal"]["weight"] == "70%" and crit["Financial Proposal"]["weight"] == "30%"
    assert crit["Methodology"]["weight"] == "25%" and crit["Methodology"]["ref"]["original"] == "المنهجية ٢٥٪"
    for text in (live_reports.snap, live_reports.full):
        assert "15 December 2026" in text and "30 November 2026" in text
        assert "60%" not in text  # the withheld payment line stays out
