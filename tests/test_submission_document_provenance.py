"""
tests/test_submission_document_provenance.py

Deterministic tests for build_submission_documents() and the submission
document projection layer introduced in fix/submission-document-provenance.

All tests are offline -- no Anthropic call, no database, no Streamlit.
"""
import json
import pathlib
import unittest

from extractor import (
    build_submission_documents,
    _is_concrete_submission_document,
)

_BOC_FIXTURE = pathlib.Path(
    "tests/acceptance/results/boc_2026_026_normalized_facts.json"
)


class TestSubmissionDocumentProvenance(unittest.TestCase):
    """Cases A-H as specified in the scope directive."""

    # A: empty rules -> empty documents
    def test_A_empty_submission_rules_yields_empty_documents(self):
        docs = build_submission_documents([])
        self.assertEqual(docs, [],
            "Empty submission_rules must produce documents=[], not invented defaults")

    # A2: no Technical Proposal.pdf / Financial Envelope.pdf invented
    def test_A2_no_invented_default_documents(self):
        docs = build_submission_documents([])
        names = [d["name"] for d in docs]
        self.assertNotIn("Technical Proposal.pdf", names)
        self.assertNotIn("Financial Envelope.pdf", names)

    # B: pure portal rule -> documents = []
    def test_B_portal_submission_rule_excluded(self):
        rules = [{"item": "Submit through MERX", "details": "Electronic portal submission required"}]
        docs = build_submission_documents(rules)
        self.assertEqual(docs, [],
            "A portal submission instruction must not produce a document record")

    # B2: electronic submission only -> excluded
    def test_B2_electronic_submission_only_excluded(self):
        rules = [{"item": "Electronic submission only", "details": "No paper submissions accepted"}]
        docs = build_submission_documents(rules)
        self.assertEqual(docs, [])

    # C: page limit rule -> documents = []
    def test_C_page_limit_rule_excluded(self):
        rules = [{"item": "Maximum response length 50 pages",
                  "details": "Responses must not exceed 50 pages"}]
        docs = build_submission_documents(rules)
        self.assertEqual(docs, [],
            "A page-limit rule must not produce a document record")

    # C2: registration required -> excluded
    def test_C2_registration_required_excluded(self):
        rules = [{"item": "Registration required", "details": "Bidders must register on the portal"}]
        docs = build_submission_documents(rules)
        self.assertEqual(docs, [])

    # D: explicit Pricing Form with mandatory=1 -> one document, correct fields
    def test_D_pricing_form_explicit_document_produced(self):
        rules = [{
            "item": "Pricing Form",
            "format": "XLSX",
            "details": "Complete all tabs",
            "mandatory": 1,
        }]
        docs = build_submission_documents(rules)
        self.assertEqual(len(docs), 1)
        d = docs[0]
        self.assertEqual(d["name"], "Pricing Form",
            "Document name must be the normalized item text with no extension appended")
        self.assertEqual(d.get("mandatory"), 1)
        self.assertEqual(d["doc_type"], "Financial")
        self.assertEqual(d["status"], "Expected")

    # E: Technical Proposal without .pdf in source -> name stays unchanged
    def test_E_technical_proposal_name_not_mutated_with_extension(self):
        rules = [{
            "item": "Technical Proposal",
            "format": "PDF",
            "details": "Submit in PDF format, max 50 pages",
            "mandatory": 1,
        }]
        docs = build_submission_documents(rules)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["name"], "Technical Proposal",
            "Name must remain Technical Proposal not Technical Proposal.pdf")

    # E2: if source name already contains .pdf, preserve it as-is
    def test_E2_name_with_pdf_extension_preserved_as_is(self):
        rules = [{"item": "Proposal.pdf", "format": "PDF", "mandatory": 1}]
        docs = build_submission_documents(rules)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["name"], "Proposal.pdf")

    # F: mandatory field absent -> key absent in output (not defaulted to 1)
    def test_F_missing_mandatory_not_defaulted_to_one(self):
        rules = [{"item": "Technical Proposal", "format": "PDF"}]
        docs = build_submission_documents(rules)
        self.assertEqual(len(docs), 1)
        self.assertNotIn("mandatory", docs[0],
            "mandatory must not be defaulted to 1 when absent from normalized facts")

    # F2: mandatory=0 preserved
    def test_F2_mandatory_zero_preserved(self):
        rules = [{"item": "ESG Questionnaire Response", "mandatory": 0}]
        docs = build_submission_documents(rules)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].get("mandatory"), 0)

    # G: mixed package with portal rule, page limit, Pricing Form, Signed Declaration
    def test_G_mixed_package_exactly_two_concrete_documents(self):
        rules = [
            {"item": "Submit via Government Portal",
             "details": "All submissions must be made through the procurement portal"},
            {"item": "Maximum 50 pages",
             "details": "Responses must not exceed fifty pages"},
            {"item": "Pricing Form", "format": "XLSX", "mandatory": 1},
            {"item": "Signed Declaration", "format": "PDF", "mandatory": 1},
        ]
        docs = build_submission_documents(rules)
        names = [d["name"] for d in docs]
        self.assertEqual(len(docs), 2,
            "Mixed package must yield exactly 2 concrete documents, not 4")
        self.assertIn("Pricing Form", names)
        self.assertIn("Signed Declaration", names)

    # H: no concrete documents -> returns [] without error
    def test_H_no_concrete_documents_returns_empty_without_error(self):
        rules = [
            {"item": "Submit via portal", "details": "Electronic portal only"},
            {"item": "Page limit 20 pages", "details": "Must not exceed 20 pages"},
            {"item": "Registration required", "details": "Register before submitting"},
        ]
        docs = build_submission_documents(rules)
        self.assertIsInstance(docs, list)
        self.assertEqual(len(docs), 0,
            "Package with only process rules must produce documents=[], not invented defaults")


class TestIsConcreteSubmissionDocument(unittest.TestCase):
    """Unit tests for the _is_concrete_submission_document predicate."""

    def _yes(self, item, details=None):
        self.assertTrue(
            _is_concrete_submission_document(item, details),
            "Expected DOCUMENT for item=" + repr(item)
        )

    def _no(self, item, details=None):
        self.assertFalse(
            _is_concrete_submission_document(item, details),
            "Expected EXCLUDED for item=" + repr(item)
        )

    def test_form_is_document(self):
        self._yes("Appendix A Submission Form")

    def test_declaration_is_document(self):
        self._yes("Conflict of Interest Declaration")

    def test_questionnaire_is_document(self):
        self._yes("ESG Questionnaire Response")

    def test_profile_is_document(self):
        self._yes("Key Personnel Profiles")

    def test_pricing_is_document(self):
        self._yes("Pricing Form")

    def test_portal_instruction_is_not_document(self):
        self._no("Submit through MERX")

    def test_page_limit_is_not_document(self):
        self._no("Maximum response length 50 pages")

    def test_electronic_only_is_not_document(self):
        self._no("Electronic submission only")

    def test_empty_item_is_not_document(self):
        self._no("")

    def test_none_item_handled(self):
        self.assertFalse(_is_concrete_submission_document(None, None))

    def test_details_trigger_when_item_ambiguous(self):
        self._yes("Supplementary Material",
                  "Completed template with all fields filled")


class TestBoCFrozenSubmissionReplay(unittest.TestCase):
    """
    Bank of Canada frozen submission document provenance replay.
    Uses existing frozen normalized_facts fixture only.
    No Stage A/B/C re-run. No Anthropic call.
    """

    @classmethod
    def setUpClass(cls):
        if not _BOC_FIXTURE.exists():
            raise unittest.SkipTest("Frozen fixture not found: " + str(_BOC_FIXTURE))
        with open(_BOC_FIXTURE, encoding="utf-8") as f:
            nf = json.load(f)
        cls.submission_rules = nf.get("submission_rules", [])
        cls.documents = build_submission_documents(cls.submission_rules)
        cls.doc_names = {d["name"] for d in cls.documents}
        cls.excluded = [
            sr["item"] for sr in cls.submission_rules
            if sr.get("item") not in cls.doc_names
        ]

    def test_boc_total_rules_present(self):
        self.assertEqual(len(self.submission_rules), 40)

    def test_boc_concrete_documents_count(self):
        self.assertEqual(len(self.documents), 39,
            "39 of 40 BoC rules must be classified as concrete submission documents")

    def test_boc_excluded_count(self):
        self.assertEqual(len(self.excluded), 1,
            "Exactly 1 BoC rule must be excluded as a non-document process instruction")

    def test_boc_excluded_is_page_format_rule(self):
        self.assertIn("Response Format and Page Limit", self.excluded)

    def test_boc_no_invented_defaults(self):
        self.assertNotIn("Technical Proposal.pdf", self.doc_names)
        self.assertNotIn("Financial Envelope.pdf", self.doc_names)

    def test_boc_envelope_1_present(self):
        self.assertIn("Envelope 1 - Identity & Proposal", self.doc_names)

    def test_boc_envelope_2_pricing_present(self):
        self.assertIn("Envelope 2 - Pricing", self.doc_names)

    def test_boc_appendix_a_present(self):
        self.assertIn("Appendix A Submission Form", self.doc_names)

    def test_boc_pricing_form_classified_financial(self):
        financial_names = {d["name"] for d in self.documents if d["doc_type"] == "Financial"}
        self.assertIn("Pricing Form - All Applicable Sections", financial_names)
        self.assertIn("Envelope 2 - Pricing", financial_names)

    def test_boc_mandatory_field_not_invented(self):
        for d in self.documents:
            if "mandatory" in d:
                self.assertIn(d["mandatory"], (0, 1))

    def test_boc_no_pdf_extension_appended(self):
        for d in self.documents:
            if not d["name"].lower().endswith(".pdf"):
                self.assertFalse(d["name"].lower().endswith(".pdf"))


if __name__ == "__main__":
    unittest.main()
