"""Arabic and bilingual procurement documents -- focused functional tests.

Covers the six fixture types (tests/fixtures/arabic, built by
build_fixtures.py; fictional content):

1. searchable Arabic PDF (two producer styles)   4. Arabic evaluation table with % weights
2. Arabic DOCX                                     5. Arabic addendum changing the deadline
3. bilingual Arabic/English DOCX and XLSX          6. scanned Arabic PDF (OCR fallback)

The end-to-end test drives the real pipeline: ZIP unpacking -> extraction ->
analysis_service._execute_fast_analysis_run (real FAST engine routing,
merging and canonicalization, real translation module) -> persisted raw
snapshot -> phoenix_report_service (re-extracts the stored documents) ->
FAST Snapshot and FULL Assessment PDFs. Only the model is scripted: a fake
Anthropic client answers like a compliant model would (English descriptive
fields, verbatim Arabic excerpts, line translations) and includes one
hallucinated excerpt and one wrong translation, which must NOT reach the
reports. No network, no database.
"""
from __future__ import annotations

import io
import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import arabic_text as at
import extractor as ex
import procurement_digest as pdg
import source_translation as sx

FIX = Path(__file__).parent / "fixtures" / "arabic"


def _read(name: str) -> bytes:
    return (FIX / name).read_bytes()


def _pdf_text(pdf: bytes) -> str:
    import pymupdf
    return "\n".join(p.get_text() for p in pymupdf.open(stream=pdf, filetype="pdf"))


# ═══════════════════════════════════════════════════════════════════════
# arabic_text
# ═══════════════════════════════════════════════════════════════════════

class TestArabicText:
    def test_language_detection(self):
        assert at.detect_language("The consultant shall deliver six sessions.") == "en"
        assert at.detect_language("يلتزم الاستشاري بتنفيذ ست جلسات تدريبية") == "ar"
        assert at.detect_language("Scope of Work / نطاق العمل: The consultant shall deliver. يلتزم الاستشاري") == "mixed"

    def test_match_key_folds_variants_and_digits_but_not_meaning(self):
        assert at.match_key("أخرُ موعدٍ ٣٠٪") == "اخر موعد 30%"
        assert at.match_key("ﺍﻟﻌﺮﺽ") == "العرض"  # presentation forms

    def test_fold_keeps_arabic_so_excerpts_verify(self):
        docs = [("a.pdf", "[[SOURCE: a.pdf | PAGE: 1]]\nآخر موعد لتقديم العروض هو ٣٠ تشرين الثاني ٢٠٢٦")]
        assert pdg.corpus_contains(docs, "آخر موعد لتقديم العروض هو ٣٠ تشرين الثاني ٢٠٢٦")
        assert pdg.corpus_contains(docs, "اخر موعد لتقديم العروض")  # alef variant
        # An Arabic excerpt that is NOT in the document must not verify on its digits alone
        assert not pdg.corpus_contains(docs, "يجب تقديم ضمان ابتدائي ٣٠")
        assert pdg.fold("Technical Proposal 70%") == "technical proposal 70%"  # English unchanged

    @pytest.mark.parametrize("english,ok", [
        ("The deadline for submission of proposals is 30 November 2026", True),
        ("The deadline for submission of proposals is 30 December 2026", False),
        ("The deadline for submission of proposals is 3 November 2026", False),
        ("The deadline for submission of proposals is 2026-11-30", True),
    ])
    def test_translation_check_on_the_deadline_example(self, english, ok):
        original = "آخر موعد لتقديم العروض هو ٣٠ تشرين الثاني ٢٠٢٦"
        assert (at.check_translation(original, english) == []) is ok

    def test_translation_check_numbers_percent_hijri_address(self):
        assert at.check_translation("العرض الفني ٧٠٪", "Technical Proposal 70%") == []
        assert at.check_translation("العرض الفني ٧٠٪", "Technical Proposal 70") != []
        assert at.check_translation("تنفيذ ست جلسات", "Deliver seven sessions") != []
        assert at.check_translation("الموعد ١٥ جمادى الأولى ١٤٤٨هـ", "15 Jumada al-Awwal 1448 AH") == []
        assert at.check_translation("الموعد ١٥ جمادى الأولى ١٤٤٨هـ", "15 November 1448") != []
        assert at.check_translation("إلى a@b.org", "to a@c.org") != []

    def test_visual_to_logical_keeps_numbers_and_addresses(self):
        visual = list("tenders@x.org ىلإ ٢٠٢٦ يناثلا نيرشت ٣٠ وه دعوملا")
        assert at.logical_from_visual(visual) == "الموعد هو ٣٠ تشرين الثاني ٢٠٢٦ إلى tenders@x.org"
        # space-separated date parts stay in their own order
        assert at.logical_from_visual(list("2026 / 11 / 9 خيراتلا")) == "التاريخ 9 / 11 / 2026"
        assert at.logical_from_visual(list("٪٣٠ ينفلا")) == "الفني ٣٠٪"


# ═══════════════════════════════════════════════════════════════════════
# Extraction
# ═══════════════════════════════════════════════════════════════════════

class TestExtraction:
    @pytest.mark.parametrize("name", ["arabic_rfp_visual.pdf", "arabic_rfp_logical.pdf"])
    def test_searchable_arabic_pdf_in_logical_order_with_correct_numbers(self, name):
        text, meta = ex.extract_document_with_metadata(_read(name), name)
        key = at.match_key(text)
        assert f"[[SOURCE: {name} | PAGE: 1]]" in text and f"[[SOURCE: {name} | PAGE: 2]]" in text
        assert "اخر موعد لتقديم العروض هو 30 تشرين الثاني 2026" in key  # digits not reversed
        assert "العرض الفني 70%" in key and "المنهجيه 25%" in key
        assert "tenders@rural" in text
        assert not re.search(r"[ﭐ-﷿ﹰ-﻿]", text)  # no presentation forms
        assert meta["arabic_pages"] == [1, 2] and meta["ocr"]["status"] == "NOT_NEEDED"

    def test_arabic_docx_headings_and_weight_table(self):
        text, meta = ex.extract_document_with_metadata(_read("arabic_tor.docx"), "arabic_tor.docx")
        assert "[[SOURCE: arabic_tor.docx | SECTION: معايير التقييم]]" in text
        assert "[[SOURCE: arabic_tor.docx | TABLE]] الخبرة السابقة | ٣٠٪" in text
        assert meta["sections"] == ["كراسة الشروط والمواصفات", "نطاق العمل", "معايير التقييم"]

    def test_bilingual_docx_and_xlsx(self):
        text, _ = ex.extract_document_with_metadata(_read("bilingual_tor.docx"), "b.docx")
        assert "The consultant shall deliver six training sessions." in text
        assert "يلتزم الاستشاري بتنفيذ ست جلسات تدريبية." in text
        assert at.detect_language(text) == "mixed"
        text, _ = ex.extract_document_with_metadata(_read("bilingual_pricing.xlsx"), "p.xlsx")
        assert "SHEET: جدول الكميات" in text and "جلسة تدريبية / Training session | 6" in text

    def test_zip_with_arabic_names_without_utf8_flag(self):
        files, warnings = ex.unpack_procurement_package([("pkg.zip", _read("arabic_package.zip"))])
        assert [n for n, _ in files] == ["كراسة الشروط.pdf", "ملحق تعديل رقم 1.pdf", "جدول الكميات.xlsx"]
        assert warnings == []

    def test_csv_in_windows_arabic_code_page(self):
        data = "البند,الكمية\nجلسة,6\n".encode("cp1256")
        text, _ = ex.extract_document_with_metadata(data, "q.csv")
        assert "Row 2: جلسة | 6" in text

    def test_scanned_pdf_ocr_fallback(self, monkeypatch):
        status = ex.ocr_status()
        if status["available"]:  # real Tesseract with Arabic data (e.g. the Oracle image)
            text, meta = ex.extract_document_with_metadata(_read("arabic_rfp_scanned.pdf"), "s.pdf")
            assert meta["ocr"]["status"] == "APPLIED" and "| OCR: tesseract" in text
            assert "العرض" in at.match_key(text)
        else:
            text, meta = ex.extract_document_with_metadata(_read("arabic_rfp_scanned.pdf"), "s.pdf")
            assert meta["ocr"]["status"] == "UNAVAILABLE" and meta["ocr"]["pages"] == [1, 2]
            assert "Arabic OCR is not available" in text
        # The fallback path itself (engine stubbed): only image-only pages are OCR'd.
        monkeypatch.setattr(ex, "ocr_status", lambda: {"available": True})
        monkeypatch.setattr(ex, "_ocr_page", lambda page, key: "آخر موعد لتقديم العروض " * 3)
        text, meta = ex.extract_document_with_metadata(_read("arabic_rfp_scanned.pdf"), "s.pdf")
        assert meta["ocr"]["status"] == "APPLIED" and meta["ocr"]["pages"] == [1, 2]
        assert "[[SOURCE: s.pdf | PAGE: 1 | OCR: tesseract]]" in text
        text, meta = ex.extract_document_with_metadata(_read("arabic_rfp_visual.pdf"), "v.pdf")
        assert meta["ocr"]["status"] == "NOT_NEEDED"  # text layer present -> never OCR'd

    def test_english_pdf_extraction_unchanged(self):
        import pymupdf
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Submission deadline: November 30, 2026.")
        data = doc.tobytes()
        text, meta = ex.extract_document_with_metadata(data, "e.pdf")
        assert text == "[[SOURCE: e.pdf | PAGE: 1]]\n" + pymupdf.open(stream=data).load_page(0).get_text().strip()
        assert meta["arabic_pages"] == []


# ═══════════════════════════════════════════════════════════════════════
# Scripted model (translation + FAST extraction)
# ═══════════════════════════════════════════════════════════════════════

RFP, ADD, XLS = "كراسة الشروط.pdf", "ملحق تعديل رقم 1.pdf", "جدول الكميات.xlsx"

TRANSLATIONS = {
    "وزارة التنمية الريفية": "Ministry of Rural Development",
    "طلب عروض رقم ٢٠٢٦/٤٥": "Request for Proposals No. 2026/45",
    "تقديم خدمات التدريب على ريادة الأعمال للشباب": "Provision of Entrepreneurship Training Services for Youth",
    "١. مقدمة": "1. Introduction",
    "تدعو وزارة التنمية الريفية الشركات المؤهلة إلى تقديم عروضها لتنفيذ برنامج تدريبي.":
        "The Ministry of Rural Development invites qualified companies to submit proposals to implement a training programme.",
    "آخر موعد لتقديم العروض هو ٣٠ تشرين الثاني ٢٠٢٦ الساعة ١٢:٠٠ ظهرا.":
        "The deadline for submission of proposals is 30 November 2026 at 12:00 noon.",
    "٢. نطاق العمل": "2. Scope of Work",
    "تنفيذ ست جلسات تدريبية للشباب من عمر ١٨ إلى ٢٨ سنة.": "Deliver six training sessions for young people aged 18 to 28 years.",
    "إعداد المواد التدريبية باللغة العربية.": "Prepare the training materials in Arabic.",
    "تقديم تقرير ختامي خلال ١٥ يوما من انتهاء التدريب.": "Submit a final report within 15 days of the end of the training.",
    "٣. شروط الأهلية": "3. Eligibility Requirements",
    "يجب أن يكون لدى المتنافس سجل تجاري ساري المفعول.": "The bidder must hold a valid commercial registration.",
    "يجب ألا تقل خبرة المدرب الرئيسي عن خمس سنوات.": "The lead trainer must have at least five years of experience.",
    "٤. معايير التقييم": "4. Evaluation Criteria",
    "العرض الفني ٧٠٪": "Technical Proposal 70%",
    "الخبرة السابقة ٣٠٪": "Previous Experience 30%",
    "المنهجية ٢٥٪": "Methodology 25%",
    "فريق العمل ١٥٪": "Team 15%",
    "العرض المالي ٣٠٪": "Financial Proposal 30%",
    "٥. العرض المالي": "5. Financial Proposal",
    "يجب أن تكون الأسعار شاملة لجميع الضرائب والرسوم.": "Prices must be inclusive of all taxes and fees.",
    "٦. شروط الدفع": "6. Payment Terms",
    # Deliberately WRONG rendering (60/40 instead of 50/50): must be withheld.
    "يتم الدفع على دفعتين: ٥٠٪ بعد التدريب و٥٠٪ بعد قبول التقرير الختامي.":
        "Payment is made in two instalments: 60% after the training and 40% after acceptance of the final report.",
    "٧. تقديم العروض": "7. Submission of Proposals",
    "ترسل العروض عبر البريد الإلكتروني إلى tenders@rural-dev.example.org":
        "Proposals are to be submitted by e-mail to tenders@rural-dev.example.org",
    "ملحق تعديل رقم (١)": "Amendment Addendum No. (1)",
    "تم تمديد آخر موعد لتقديم العروض ليصبح ١٥ كانون الأول ٢٠٢٦.":
        "The deadline for submission of proposals has been extended to 15 December 2026.",
    "يجب إرفاق شهادة عدم محكومية للمدرب الرئيسي.": "A certificate of no criminal record for the lead trainer must be attached.",
    "Row 1: البند / Item | الكمية / Quantity | سعر الوحدة / Unit price | المجموع / Total":
        "Row 1: Item / Item | Quantity / Quantity | Unit price / Unit price | Total / Total",
    "Row 2: جلسة تدريبية / Training session | 6": "Row 2: Training session / Training session | 6",
    "Row 3: تقرير ختامي / Final report | 1": "Row 3: Final report / Final report | 1",
}
_TR = {at.match_key(k): v for k, v in TRANSLATIONS.items()}


def _ref(doc, page, excerpt):
    return [{"source_doc": doc, "page": page, "sheet": None, "section": None, "excerpt": excerpt}]


def _fast_answer(prompt: str) -> dict:
    doc = re.search(r"DOCUMENT TO PROCESS \((.+?)\):", prompt).group(1)
    if "Extract ONLY commercial_clauses" in prompt:
        if doc != RFP:
            return {"commercial_clauses": []}
        return {"commercial_clauses": [
            {"clause_kind": "PAYMENT_WITHHOLDING_SETOFF", "topic": "Payment schedule",
             "source_fact": "Two instalments of 50%.",
             "source_refs": _ref(RFP, 2, "يتم الدفع على دفعتين: ٥٠٪ بعد التدريب و٥٠٪ بعد قبول التقرير الختامي.")},
            # Hallucinated: not in the document -> must never be published.
            {"clause_kind": "GUARANTEE_BOND", "topic": "Bid bond", "source_fact": "A 5% bid bond is required.",
             "source_refs": _ref(RFP, 2, "يجب تقديم ضمان ابتدائي بنسبة ٥٪ من قيمة العرض.")},
        ]}
    if doc == RFP:
        return {
            "doc_metadata": {"title": "Provision of Entrepreneurship Training Services for Youth",
                             "title_original": "تقديم خدمات التدريب على ريادة الأعمال للشباب",
                             "client": "Ministry of Rural Development", "client_original": "وزارة التنمية الريفية",
                             "file_number": "2026/45", "submission_deadline": "2026-11-30", "submission_time": "12:00"},
            "typed_observations": [
                {"family": "MILESTONE", "semantic_kind": "SUBMISSION_DEADLINE",
                 "original_value": "30 November 2026 at 12:00", "date": "2026-11-30",
                 "source_refs": _ref(RFP, 1, "آخر موعد لتقديم العروض هو ٣٠ تشرين الثاني ٢٠٢٦")}],
            "evaluation_criteria": [
                {"stage": "Technical Proposal", "parent_stage": None, "weight": "70%", "weight_unit": "Percent",
                 "evaluation_role": "Award Criterion", "source_refs": _ref(RFP, 2, "العرض الفني ٧٠٪")},
                {"stage": "Previous Experience", "parent_stage": "Technical Proposal", "weight": "30%",
                 "evaluation_role": "Award Criterion", "source_refs": _ref(RFP, 2, "الخبرة السابقة ٣٠٪")},
                {"stage": "Methodology", "parent_stage": "Technical Proposal", "weight": "٢٥٪",
                 "evaluation_role": "Award Criterion", "source_refs": _ref(RFP, 2, "المنهجية ٢٥٪")},
                {"stage": "Team", "parent_stage": "Technical Proposal", "weight": "15%",
                 "evaluation_role": "Award Criterion", "source_refs": _ref(RFP, 2, "فريق العمل ١٥٪")},
                {"stage": "Financial Proposal", "parent_stage": None, "weight": "30%",
                 "evaluation_role": "Award Criterion", "source_refs": _ref(RFP, 2, "العرض المالي ٣٠٪")},
            ],
            "requirements": [
                {"category": "Mandatory", "description": "The bidder must hold a valid commercial registration.",
                 "source_refs": _ref(RFP, 2, "يجب أن يكون لدى المتنافس سجل تجاري ساري المفعول.")}],
        }
    if doc == ADD:
        return {
            "doc_metadata": {"title": None, "client": None, "submission_deadline": "2026-12-15"},
            "typed_observations": [],
            "evaluation_criteria": [],
            "requirements": [
                {"category": "Mandatory",
                 "description": "A certificate of no criminal record for the lead trainer must be attached.",
                 "source_refs": _ref(ADD, 1, "يجب إرفاق شهادة عدم محكومية للمدرب الرئيسي.")}],
        }
    return {"doc_metadata": {}, "typed_observations": [], "evaluation_criteria": [], "requirements": []}


def _translation_answer(prompt: str) -> dict:
    body = prompt.split("\nLINES:\n", 1)[1]
    out = {}
    for row in body.splitlines():
        n, _, original = row.partition("\t")
        if at.match_key(original) in _TR:
            out[n] = _TR[at.match_key(original)]
    return {"lines": out}


class ScriptedModel:
    """Stands in for the Anthropic client: answers FAST extraction prompts
    like a compliant model and translation prompts from TRANSLATIONS."""

    def __init__(self):
        self.prompts: list[str] = []
        self.messages = self

    def create(self, **kwargs):
        prompt = kwargs["messages"][0]["content"][0]["text"]
        self.prompts.append(prompt)
        data = _translation_answer(prompt) if prompt.startswith(sx.TRANSLATION_PROMPT) else _fast_answer(prompt)
        return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(data, ensure_ascii=False))],
                               usage=SimpleNamespace(input_tokens=10, output_tokens=10), stop_reason="end_turn")


# ═══════════════════════════════════════════════════════════════════════
# Controlled translation and evidence linking
# ═══════════════════════════════════════════════════════════════════════

def _documents(names=(RFP, ADD, XLS)) -> tuple[list, dict]:
    files, _ = ex.unpack_procurement_package([("pkg.zip", _read("arabic_package.zip"))])
    files = [(n, b) for n, b in files if n in names]
    return [(n, ex.extract_document_with_metadata(b, n)[0]) for n, b in files], dict(files)


class TestControlledTranslation:
    def test_checked_withheld_and_english_view(self):
        docs, _ = _documents()
        payload = sx.translate_documents(docs, client=ScriptedModel())
        assert payload["status"] == "COMPLETE"
        s = payload["summary"]
        assert s["withheld"] == 1 and s["not_translated"] == 0 and s["checked"] == s["segments"] - 1
        view = dict(sx.english_view(docs, payload))
        assert "The deadline for submission of proposals is 30 November 2026 at 12:00 noon." in view[RFP]
        assert "60%" not in view[RFP]  # the wrong rendering never enters the English view
        assert "[[SOURCE: كراسة الشروط.pdf | PAGE: 2]]" in view[RFP]  # markers/pages unchanged
        assert not at.has_arabic(re.sub(r"\[\[[^\]]*\]\]", "", view[RFP]))

    def test_excerpt_localisation_links_original_evidence(self):
        docs, _ = _documents()
        payload = sx.translate_documents(docs, client=ScriptedModel())
        result = {"evaluation_criteria": [{"stage": "Technical Proposal", "weight": "٧٠٪",
                                           "source_refs": _ref(RFP, 2, "العرض الفني ٧٠٪")}],
                  "commercial_clauses": [{"topic": "Bid bond", "source_refs": _ref(RFP, 2, "يجب تقديم ضمان ابتدائي")}]}
        out = sx.localize_fast_result(result, docs, payload)
        ref = out["evaluation_criteria"][0]["source_refs"][0]
        assert ref["excerpt"] == "Technical Proposal 70%" and ref["excerpt_original"] == "العرض الفني ٧٠٪"
        ev = ref["evidence"]
        assert ev["original_text"] == "العرض الفني ٧٠٪" and ev["doc"] == RFP and ev["page"] == 2
        assert ev["status"] == "VERIFIED_ORIGINAL_CHECKED_TRANSLATION" and ev["match_key"] == "العرض الفني 70%"
        assert out["evaluation_criteria"][0]["weight"] == "70%"
        # an excerpt that is not in the document cannot be supported
        bad = out["commercial_clauses"][0]["source_refs"][0]
        assert bad["excerpt"] == "" and bad["evidence_status"] == "UNSUPPORTED_TRANSLATION"
        assert result["evaluation_criteria"][0]["source_refs"][0]["excerpt"] == "العرض الفني ٧٠٪"  # input untouched

    def test_display_rendering_for_an_excerpt(self):
        docs, _ = _documents()
        payload = sx.translate_documents(docs, client=ScriptedModel())
        assert sx.rendering_for_excerpt(payload, RFP, "آخر موعد لتقديم العروض هو ٣٠ تشرين الثاني ٢٠٢٦") == \
            "The deadline for submission of proposals is 30 November 2026 at 12:00 noon."
        assert sx.rendering_for_excerpt(payload, RFP, "يتم الدفع على دفعتين") is None  # withheld line

    def test_english_package_needs_no_translation(self):
        assert not sx.needs_translation([("e.pdf", "[[SOURCE: e.pdf | PAGE: 1]]\nScope of work: deliver six sessions.")])
        payload = sx.translate_documents([("e.pdf", "Scope of work")], client=MagicMock())
        assert payload["status"] == "NOT_NEEDED"


# ═══════════════════════════════════════════════════════════════════════
# End-to-end pipeline
# ═══════════════════════════════════════════════════════════════════════

def _run_pipeline(names=(RFP, ADD, XLS)):
    """Upload (ZIP) -> FAST run via analysis_service -> raw snapshot."""
    import analysis_service as svc
    files, _ = ex.unpack_procurement_package([("pkg.zip", _read("arabic_package.zip"))])
    files = [(n, b) for n, b in files if n in names]
    stored = {f"1/{i}.bin": b for i, (_, b) in enumerate(files)}
    docs = [{"id": i + 1, "bid_id": 1, "name": n, "doc_type": "RFP / Source", "version": 1,
             "storage_path": f"1/{i}.bin", "created_at": "2026-11-01T00:00:00+00:00"}
            for i, (n, _) in enumerate(files)]
    model = ScriptedModel()
    with patch("analysis_service.db") as mock_db, \
            patch("fast_analysis.get_anthropic_client", return_value=model), \
            patch("config.get_anthropic_client", return_value=model):
        mock_db.download_file.side_effect = lambda p: stored[p]
        mock_db.upload_analysis_report.return_value = "1/analysis_reports/1.pdf"
        mock_db.get_bid_procurement_state.return_value = {"procurement_revision": 0}
        mock_db.get_reviewed_document_hashes.return_value = set()
        svc._execute_fast_analysis_run(run_id=1, bid_id=1, docs=docs, api_key="fake")
        statuses = [c.args[1].get("status") for c in mock_db.update_analysis_run.call_args_list if "status" in c.args[1]]
        assert statuses[-1] == "COMPLETE", mock_db.update_analysis_run.call_args_list[-1]
        snapshot = mock_db.create_analysis_result.call_args.kwargs["fast_analysis_result_snapshot"]
        identity = mock_db.fill_placeholder_bid_identity.call_args
    return snapshot, docs, stored, model, identity


def _report_facts(snapshot, docs, stored):
    """The Phoenix report service, reading the stored documents back."""
    import phoenix_report_service as prs
    run = {"id": 1, "bid_id": 1, "analysis_mode": "FAST", "status": "COMPLETE",
           "created_at": "2026-11-02T00:00:00+00:00", "completed_at": "2026-11-02T00:05:00+00:00"}
    with patch("phoenix_report_service.db") as db:
        db.get_analysis_run.return_value = run
        db.get_documents.return_value = docs
        db.download_file.side_effect = lambda p: stored[p]
        db.list_analysis_runs.return_value = [run]
        db.get_analysis_result.return_value = {"fast_analysis_result_snapshot": snapshot}
        db.get_bid.return_value = {"id": 1, "title": "Untitled Opportunity", "client": "Organization not identified"}
        return prs.build_facts_for_run(1, 1)


@pytest.fixture(scope="module")
def pipeline():
    snapshot, docs, stored, model, identity = _run_pipeline()
    facts = _report_facts(snapshot, docs, stored)
    import phoenix_reports as pr
    snap_pdf = pr.render_snapshot(facts)["pdf"]
    full_pdf = pr.render_assessment(facts, full_status="COMPLETE", research=None)["pdf"]
    return SimpleNamespace(snapshot=snapshot, facts=facts, model=model, identity=identity,
                           snap=_pdf_text(snap_pdf), full=_pdf_text(full_pdf))


class TestEndToEnd:
    def test_languages_detected_and_translation_persisted_in_snapshot(self, pipeline):
        r = pipeline.snapshot["result"]
        assert pipeline.snapshot["schema_version"] == "1.3"
        assert r["source_languages"] == {RFP: "ar", ADD: "ar", XLS: "mixed"}
        assert r["source_translations"]["status"] == "COMPLETE"
        assert r["source_translations"]["summary"]["withheld"] == 1

    def test_fast_prompts_carry_arabic_language_rules_and_verbatim_excerpts(self, pipeline):
        fast = [p for p in pipeline.model.prompts if not p.startswith(sx.TRANSLATION_PROMPT)]
        assert fast and all("LANGUAGE RULES (this text is wholly or partly in Arabic)" in p for p in fast)
        r = pipeline.snapshot["result"]  # persisted evidence stays in the original Arabic
        assert r["evaluation_criteria"][0]["source_refs"][0]["excerpt"] == "العرض الفني ٧٠٪"

    def test_bid_identity_filled_in_english_grounded_in_arabic(self, pipeline):
        args = pipeline.identity.args
        assert args[1] == "Provision of Entrepreneurship Training Services for Youth"
        assert args[2] == "Ministry of Rural Development"

    def test_fact_model_fields_and_source_references(self, pipeline):
        f = pipeline.facts
        assert f["identity"]["organization"] == "Ministry of Rural Development"
        assert f["identity"]["reference"] == "2026/45"
        d = f["deadline"]
        assert d["effective"] == "2026-12-15" and d["extracted_ref"]["doc"] == ADD
        assert d["amended_from"]["value"] == "2026-11-30" and d["amended_from"]["ref"]["doc"] == RFP
        crit = {c["stage"]: c for c in f["criteria"]}
        assert crit["Technical Proposal"]["weight"] == "70%" and crit["Methodology"]["weight"] == "25%"
        assert crit["Technical Proposal"]["children_basis"] == "overall"  # 70 = 30 + 25 + 15
        assert crit["Methodology"]["ref"]["page"] == 2 and crit["Methodology"]["ref"]["doc"] == RFP
        assert crit["Methodology"]["ref"]["original"] == "المنهجية ٢٥٪"
        assert [c["text"] for c in f["clauses"]] == []  # payment line withheld; bid bond hallucinated
        assert any("valid commercial registration" in q["text"] for q in f["qualifications"])
        assert any("six training sessions" in s["text"] for s in f["scope"])
        assert f["submission"]["emails"][0]["email"] == "tenders@rural-dev.example.org"
        assert any("inclusive of all taxes" in p["text"] for p in f["pricing"])
        kinds = {(c["kind"], c["topic"]) for c in f["changes"]}
        assert ("UPDATED", "Submission deadline") in kinds
        new = [c for c in f["changes"] if c["kind"] == "NEW"]
        assert any("no criminal record" in str(c["current"]) and c["source"]["doc"] == ADD for c in new)

    def test_original_arabic_evidence_is_attached(self, pipeline):
        f = pipeline.facts
        scope = next(s for s in f["scope"] if "six training sessions" in s["text"])
        assert scope["original"] == "تنفيذ ست جلسات تدريبية للشباب من عمر ١٨ إلى ٢٨ سنة."
        assert scope["doc"] == RFP and scope["page"] == 1
        assert "آخر موعد" in f["deadline"]["amended_from"]["ref"]["original"]
        upd = next(c for c in f["changes"] if c["topic"] == "Submission deadline")
        assert "تم تمديد آخر موعد" in upd["source"]["original"]

    def test_fast_snapshot_pdf_is_english_and_complete(self, pipeline):
        t = re.sub(r"\s+", " ", pipeline.snap)
        assert "OPPORTUNITY SNAPSHOT" in t
        for expected in ("Ministry of Rural Development", "15 December 2026", "30 November 2026",
                         "Technical Proposal", "70%", "Methodology", "six training sessions",
                         "tenders@rural-dev.example.org", "inclusive of all taxes"):
            assert expected in t, expected
        self._common(t)

    def test_full_assessment_pdf_is_english_and_complete(self, pipeline):
        t = re.sub(r"\s+", " ", pipeline.full)
        assert "BID OPPORTUNITY ASSESSMENT" in t
        for expected in ("UPDATED INFORMATION", "15 December 2026", "30 November 2026", "Financial Proposal",
                         "no criminal record", "valid commercial registration", "NEW INFORMATION"):
            assert expected in t, expected
        self._common(t)

    @staticmethod
    def _common(t: str):
        assert not at.has_arabic(t) and not re.search(r"[٠-٩]", t)  # English only
        assert "60%" not in t and "bid bond" not in t.lower()  # withheld / unsupported never printed
        assert "Arabic or bilingual" in t  # the document basis states how Arabic text was handled
        assert not re.search(r"\b(recommend(ed|ation)? to bid|win probability|suitability score)\b", t, re.I)

    def test_full_specialist_prompt_gets_arabic_rules_only_for_arabic_objects(self):
        import full_analysis as fa
        sid = next(iter(fa.SPECIALIST_BRIEFS))
        ar = fa._build_specialist_prompt(sid, {"objects": {"x": [{"canonical_id": "A", "text": "العرض الفني ٧٠٪"}]}})
        en = fa._build_specialist_prompt(sid, {"objects": {"x": [{"canonical_id": "A", "text": "Technical 70%"}]}})
        assert "LANGUAGE: some canonical objects quote Arabic" in ar
        assert "LANGUAGE:" not in en

    def test_full_canonical_package_builds_from_arabic_result(self, pipeline):
        import fast_analysis
        import full_analysis
        result = fast_analysis.deserialize_fast_analysis_result(pipeline.snapshot)
        pkg = full_analysis.build_canonical_package(result, bid_id=1, analysis_run_id=1, documents=None)
        assert pkg


class TestEnglishPackageUnaffected:
    def test_english_prompt_and_facts_identical_without_arabic(self):
        import fast_analysis as fa
        assert fa._language_rules("Scope of Work: six sessions") == ""
        import phoenix_reports as pr
        docs = [("rfp.pdf", "[[SOURCE: rfp.pdf | PAGE: 1]]\nScope of Work\n- Deliver six training sessions.\n")]
        f = pr.build_facts(bid={"id": 1}, fast_result={}, documents=docs)
        assert f["translation_note"] is None and f["languages"] == {}
        assert "original" not in f["scope"][0]
