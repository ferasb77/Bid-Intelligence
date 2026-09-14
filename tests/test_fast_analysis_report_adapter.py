"""
tests/test_fast_analysis_report_adapter.py

Deterministic tests for scripts/fast_analysis_report_adapter.py's Phase 4
generalization fix: _merged_doc_metadata() / build_fast_report_content()
must identify the buyer/title/dates from whichever document actually
carries them, not from a hardcoded Bank of Canada filename constant. No
live API calls -- every FastAnalysisResult below is synthetic.

Root cause this guards against: the pre-Phase-4 code did
`result.doc_metadata_by_doc.get(MASTER_RFP, {})` where MASTER_RFP is the
literal Bank of Canada master RFP filename. For any corpus where no
document happens to have that exact name, this returned {}, and the
report/UI then silently fell back to Bank-of-Canada-shaped defaults (e.g.
buyer defaulting to the literal string "Bank of Canada") even though the
engine had correctly extracted the real buyer under a different document
key.
"""
import unittest

from fast_analysis import FastAnalysisResult, route_document, ROUTE_IDENTITY_EVAL_REQ
from scripts.fast_analysis_report_adapter import _merged_doc_metadata, build_fast_report_content


def _result_with_docs(doc_metadata_by_doc: dict) -> FastAnalysisResult:
    r = FastAnalysisResult()
    r.doc_metadata_by_doc = doc_metadata_by_doc
    return r


class TestMergedDocMetadata(unittest.TestCase):

    def test_single_document_with_a_generic_filename_is_found(self):
        """No Bank of Canada filename anywhere -- identity must still be
        picked up from whichever document actually has it."""
        result = _result_with_docs({
            "document1.pdf": {"client": "Canada's Drug Agency (CDA-AMC)",
                              "title": "Coaching Services", "file_number": "C-262700410"},
        })
        meta = _merged_doc_metadata(result)
        self.assertEqual(meta["client"], "Canada's Drug Agency (CDA-AMC)")
        self.assertEqual(meta["title"], "Coaching Services")

    def test_merges_across_multiple_documents_first_value_wins(self):
        """A corpus where no single document matched a narrow route (so
        every document was asked for identity) may return partial identity
        facts from more than one document -- these must be merged, not
        just read from one arbitrarily-chosen document."""
        result = _result_with_docs({
            "Bulletin 02.pdf": {"client": None, "title": None, "submission_deadline": "2026-08-06"},
            "Main Document.pdf": {"client": "Canada's Drug Agency (CDA-AMC)",
                                  "title": "Coaching Services", "submission_deadline": None},
            "Bulletin 03.pdf": {},
        })
        meta = _merged_doc_metadata(result)
        self.assertEqual(meta["client"], "Canada's Drug Agency (CDA-AMC)")
        self.assertEqual(meta["title"], "Coaching Services")
        self.assertEqual(meta["submission_deadline"], "2026-08-06")

    def test_first_non_empty_value_wins_on_conflict(self):
        """If two documents both report a value for the same field, the
        first one encountered (insertion order) is kept -- deterministic,
        not a silent overwrite race."""
        result = _result_with_docs({
            "a.pdf": {"client": "First Buyer Name"},
            "b.pdf": {"client": "Second Buyer Name"},
        })
        meta = _merged_doc_metadata(result)
        self.assertEqual(meta["client"], "First Buyer Name")

    def test_empty_result_produces_empty_metadata_not_a_crash(self):
        result = FastAnalysisResult()
        self.assertEqual(_merged_doc_metadata(result), {})

    def test_non_dict_metadata_values_are_skipped_not_fatal(self):
        result = _result_with_docs({"a.pdf": None, "b.pdf": {"client": "Real Buyer"}})
        meta = _merged_doc_metadata(result)
        self.assertEqual(meta["client"], "Real Buyer")


class TestBuildFastReportContentGeneralization(unittest.TestCase):
    """Filenames covering the Phase 4 instruction 15 list: arbitrary user
    filenames, spaces, punctuation, mixed casing, generic names, renamed
    PDFs -- none of these should change whether identity is found."""

    def _assert_identity_found(self, filename: str):
        result = _result_with_docs({
            filename: {"client": "Canada's Drug Agency (CDA-AMC)", "title": "Coaching Services",
                      "file_number": "C-262700410"},
        })
        content = build_fast_report_content(result)
        facts = dict(content.SNAPSHOT_FACTS)
        self.assertEqual(facts["Buyer"], "Canada's Drug Agency (CDA-AMC)", filename)
        self.assertNotEqual(facts["Buyer"], "Bank of Canada", filename)
        self.assertEqual(facts["Solicitation Number"], "C-262700410", filename)
        self.assertNotEqual(facts["Solicitation Number"], "RFP 2026-026", filename)

    def test_generic_filename(self):
        self._assert_identity_found("document1.pdf")

    def test_filename_with_spaces_and_punctuation(self):
        self._assert_identity_found("C-262700410 CDA-AMC Coaching Services RFSO Main Document FINAL(PDF) (1).pdf")

    def test_mixed_case_filename(self):
        self._assert_identity_found("Main_Document.PDF")

    def test_renamed_pdf_with_no_relation_to_original_name(self):
        self._assert_identity_found("scan_2026_final_v3.pdf")

    def test_bank_of_canada_master_filename_still_works_unchanged(self):
        """Regression: the exact original Bank of Canada filename must
        still resolve identity correctly -- this fix is additive, not a
        behavior change for the commissioned corpus."""
        self._assert_identity_found(
            "RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf")

    def test_no_document_carries_identity_falls_back_gracefully(self):
        """Superseded by Product Integration Phase 5 (generic intelligence
        assembly): this test originally asserted that, when truly nothing
        was extracted, the adapter falls back to the literal string "Bank
        of Canada" as the buyer -- correct for Phase 4's narrower fix
        (stop a WRONG buyer from being silently shown), but itself still a
        cross-corpus fallback: it substituted a specific, real buyer's
        identity for ANY corpus with no extracted identity, including one
        that is genuinely not Bank of Canada. Phase 5's non-negotiable
        principle (instruction 0) forbids this -- the honest behavior for
        truly missing identity is the generic not-extracted marker, for
        every corpus including Bank of Canada's own (which never actually
        takes this path in practice, since its real corpus always yields
        an extracted buyer)."""
        result = FastAnalysisResult()
        content = build_fast_report_content(result)
        facts = dict(content.SNAPSHOT_FACTS)
        self.assertEqual(facts["Buyer"], "Not stated in the extracted data.")


class TestRouteDocumentGeneralization(unittest.TestCase):
    """Phase 4 instruction 15: routing must not depend on absolute/local
    repository paths, and any unrecognized filename shape -- arbitrary
    user filenames, spaces, punctuation, mixed casing, generic names,
    multiple similarly-named appendices -- must resolve to the documented,
    safe generic fallback (ROUTE_IDENTITY_EVAL_REQ), never raise, and
    never depend on where the file happens to live on disk. This is a
    read-only characterization of route_document()'s existing, unmodified
    behavior (fast_analysis.py itself was not changed in Phase 4) --
    it guards against a future change accidentally narrowing the fallback."""

    def test_arbitrary_generic_filename_falls_back_safely(self):
        for name in ("document1.pdf", "file.pdf", "untitled.docx", "Scan001.PDF"):
            self.assertEqual(route_document(name), ROUTE_IDENTITY_EVAL_REQ, name)

    def test_filename_with_spaces_and_punctuation_falls_back_safely(self):
        self.assertEqual(
            route_document("C-262700410 CDA-AMC Coaching Services RFSO Main Document FINAL(PDF) (1).pdf"),
            ROUTE_IDENTITY_EVAL_REQ)

    def test_mixed_casing_falls_back_safely(self):
        self.assertEqual(route_document("MAIN DOCUMENT.PDF"), ROUTE_IDENTITY_EVAL_REQ)

    def test_multiple_similarly_named_appendices_all_fall_back_safely(self):
        for name in ("Bulletin #02 Final(PDF).pdf", "Bulletin #03 Final(PDF).pdf",
                     "Bulletin #04 Final(PDF).pdf", "Bulletin #05 Final(PDF).pdf"):
            self.assertEqual(route_document(name), ROUTE_IDENTITY_EVAL_REQ, name)

    def test_routing_does_not_depend_on_an_absolute_or_local_path_prefix(self):
        """The same basename must route identically whether or not it
        carries a local filesystem prefix -- routing is a pure function of
        the filename string the engine is given, never of where a caller's
        copy of the file happens to sit on disk."""
        bare = route_document("document1.pdf")
        with_windows_path = route_document(r"C:\Users\someone\Downloads\document1.pdf")
        with_posix_path = route_document("/tmp/uploads/3/document1.pdf")
        self.assertEqual(bare, with_windows_path)
        self.assertEqual(bare, with_posix_path)


if __name__ == "__main__":
    unittest.main()
