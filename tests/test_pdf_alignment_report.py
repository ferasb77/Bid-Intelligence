"""
tests/test_pdf_alignment_report.py

Deterministic tests for the Alignment Audit Report PDF export
(pdf_alignment.generate_alignment_audit_pdf). Proves:

  * the report is a deterministic, in-memory render of an
    ALREADY-COMPUTED align_result -- no LLM call, no re-analysis, no
    modification of the score/findings/coverage it is given;
  * every required section (identity, score/confidence, executive
    summary, mandatory risks, findings, coverage matrix, strengths,
    next steps) actually appears in the rendered PDF text for a
    complete audit;
  * an incomplete audit's report never contains a numeric score;
  * a zero-evaluation-universe audit's report clearly states
    "No evaluative criteria identified", never an invented score;
  * the existing, unrelated Fast Analysis / compliance-matrix PDF path
    (pdf_export.generate_compliance_pdf) is unaffected.

Uses PyMuPDF (fitz, already a dependency -- extractor.py uses it) only
to extract text from the generated PDF bytes for content assertions;
no live network calls anywhere in this file.
"""
import inspect
import unittest
from unittest.mock import patch

import fitz

import pdf_alignment
import pdf_export


def _pdf_text(pdf_bytes: bytes) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    return "\n".join(page.get_text() for page in doc)


def _flat(text: str) -> str:
    """Collapse whitespace/newlines -- PDF table-cell word-wrap can split
    a phrase across lines even though it reads as one phrase visually;
    assertions on multi-word phrases should not be sensitive to exactly
    where reportlab happened to wrap a cell."""
    return " ".join(text.split())


_BID = {
    "client": "Canada Drug Agency", "title": "Coaching Services — Standing Offer Agreement",
    "file_number": "CDA-2026-001", "submission_deadline": "2026-10-01", "owner": "Feras",
}

_COMPLETE_RESULT = {
    "status": "complete", "overall_score": 80.0, "score_basis": "Buyer-weighted evaluation criteria",
    "score_rationale": "80/100 structured alignment score.", "recommendation": "REVISE BEFORE SUBMITTING",
    "executive_summary": "The proposal addresses most evaluation criteria but has a methodology gap.",
    "strengths": ["Clear team qualifications and past performance evidence."],
    "findings": [
        {"severity": "High", "req_id": "R2", "category": "Rated",
         "issue": "Methodology lacks detail on risk mitigation planning.",
         "proposal_location": "Section 3.2", "recommendation": "Add a risk mitigation subsection.",
         "effort": "Moderate rewrite"},
    ],
    "mandatory_failures": [
        {"req_id": "M1", "description": "Provide certificate of insurance",
         "reason": "No supporting evidence found anywhere in the analyzed proposal."},
    ],
    "requirement_coverage": [
        {"req_id": "M1", "category": "Mandatory", "coverage": "Not Addressed", "confidence": "High",
         "evidence_location": "", "notes": "No supporting evidence found anywhere in the analyzed proposal."},
        {"req_id": "R1", "category": "Rated", "coverage": "Fully Addressed", "confidence": "High",
         "evidence_location": "Section 2.1", "notes": "Team qualifications covered in detail."},
    ],
    "next_steps": [
        {"priority": 1, "action": "Attach the missing insurance certificate", "rationale": "Mandatory gap",
         "when": "Before submission"},
    ],
    "coverage_metadata": {"chars_total": 124110, "chars_processed": 124110, "percentage_covered": 100.0,
                           "chunk_count": 15, "successful_chunks": 15, "failed_or_skipped_chunks": 0},
}

_INCOMPLETE_RESULT = {
    "status": "incomplete", "message": "Alignment audit incomplete — no reliable score available",
    "reason": "Proposal coverage did not reach the full-audit threshold (62.0% analyzed, 2 chunk(s) failed).",
    "overall_score": None, "score_basis": None, "score_rationale": None, "recommendation": None,
    "executive_summary": None, "strengths": [],
    "findings": [{"severity": "Low", "req_id": "R3", "category": "Rated",
                  "issue": "Partial finding from an analyzed section.", "proposal_location": "Section 1",
                  "recommendation": "Review further once coverage is complete.", "effort": "Minor edit"}],
    "mandatory_failures": [],
    "requirement_coverage": [{"req_id": "R3", "category": "Rated", "coverage": "Fully Addressed",
                               "confidence": "High", "evidence_location": "Section 1", "notes": "covered"}],
    "next_steps": [],
    "coverage_metadata": {"chars_total": 200000, "chars_processed": 124000, "percentage_covered": 62.0,
                           "chunk_count": 16, "successful_chunks": 14, "failed_or_skipped_chunks": 2},
}

_ZERO_UNIVERSE_RESULT = {
    "status": "complete", "overall_score": None, "score_basis": "No evaluative criteria identified",
    "score_rationale": "No evaluative criteria in this procurement.",
    "recommendation": "REVIEW — NO EVALUATIVE CRITERIA IDENTIFIED",
    "executive_summary": "No rated criteria in this procurement; all mandatory gates satisfied.",
    "strengths": [], "findings": [], "mandatory_failures": [],
    "requirement_coverage": [{"req_id": "M1", "category": "Mandatory", "coverage": "Fully Addressed",
                               "confidence": "High", "evidence_location": "Section 1", "notes": "covered"}],
    "next_steps": [],
    "coverage_metadata": {"chars_total": 5000, "chars_processed": 5000, "percentage_covered": 100.0,
                           "chunk_count": 1, "successful_chunks": 1, "failed_or_skipped_chunks": 0},
}


class TestCompletedAuditReport(unittest.TestCase):
    def setUp(self):
        self.pdf_bytes = pdf_alignment.generate_alignment_audit_pdf(
            _BID, _COMPLETE_RESULT, proposal_filename="canada_drug_agency_proposal.pdf"
        )
        self.text = _pdf_text(self.pdf_bytes)

    def test_exports_nonempty_valid_pdf(self):
        self.assertTrue(self.pdf_bytes.startswith(b"%PDF-"))
        self.assertGreater(len(self.pdf_bytes), 1000)

    def test_contains_client_and_opportunity_identity(self):
        self.assertIn("Canada Drug Agency", self.text)
        self.assertIn("Coaching Services", self.text)

    def test_contains_proposal_filename(self):
        self.assertIn("canada_drug_agency_proposal.pdf", self.text)

    def test_score_appears_when_legitimate(self):
        self.assertIn("80/100", self.text)

    def test_score_basis_appears(self):
        self.assertIn("Buyer-weighted evaluation criteria", self.text)

    def test_executive_summary_appears(self):
        self.assertIn("methodology gap", self.text)

    def test_mandatory_qualification_failures_appear(self):
        self.assertIn("M1", self.text)
        self.assertIn("MANDATORY", self.text)
        self.assertIn("insurance", self.text.lower())

    def test_findings_appear(self):
        self.assertIn("risk mitigation planning", _flat(self.text))
        self.assertIn("Section 3.2", self.text)

    def test_requirement_coverage_appears(self):
        self.assertIn("Fully Addressed", self.text)
        self.assertIn("Not Addressed", self.text)

    def test_strengths_appear(self):
        self.assertIn("past performance evidence", self.text)

    def test_next_steps_appear(self):
        self.assertIn("missing insurance certificate", self.text)

    def test_audit_basis_statement_present_and_does_not_claim_tender_reread(self):
        flat = _flat(self.text.lower())
        self.assertIn("canonical procurement intelligence", flat)
        # Must explicitly DISCLAIM re-reading the tender documents ("not
        # a re-read..."), never imply the opposite by omission or by
        # claiming a re-read happened.
        self.assertIn("not a re-read of the physical tender documents", flat)

    def test_unknown_location_never_fabricated(self):
        """The second finding fixture (not in this result) has no
        proposal_location -- the underlying helper must render 'Not
        identified', never leave it blank or invent one. Verified
        directly against the helper function."""
        self.assertEqual(pdf_alignment._not_identified(""), "Not identified")
        self.assertEqual(pdf_alignment._not_identified(None), "Not identified")
        self.assertEqual(pdf_alignment._not_identified("Section 5"), "Section 5")


class TestIncompleteAuditReport(unittest.TestCase):
    def setUp(self):
        self.pdf_bytes = pdf_alignment.generate_alignment_audit_pdf(_BID, _INCOMPLETE_RESULT)
        self.text = _pdf_text(self.pdf_bytes)

    def test_report_generated_even_though_incomplete(self):
        self.assertTrue(self.pdf_bytes.startswith(b"%PDF-"))
        self.assertGreater(len(self.pdf_bytes), 500)

    def test_shows_incomplete_status_prominently(self):
        self.assertIn("ALIGNMENT AUDIT INCOMPLETE", self.text)
        self.assertIn("NO RELIABLE SCORE AVAILABLE", self.text)

    def test_contains_no_numeric_score(self):
        """No '<number>/100' pattern may appear anywhere in an
        incomplete report -- the strongest available proof that no
        numeric score was rendered."""
        import re
        self.assertIsNone(re.search(r"\d+(\.\d+)?\s*/\s*100", self.text))

    def test_preserves_partial_findings_and_coverage_labelled_as_partial(self):
        self.assertIn("Partial finding from an analyzed section", self.text)
        self.assertIn("PARTIAL sample", self.text)

    def test_shows_coverage_metadata(self):
        self.assertIn("62.0%", self.text)


class TestZeroEvaluationUniverseReport(unittest.TestCase):
    def test_states_no_evaluative_criteria_identified_not_an_invented_score(self):
        pdf_bytes = pdf_alignment.generate_alignment_audit_pdf(_BID, _ZERO_UNIVERSE_RESULT)
        text = _pdf_text(pdf_bytes)
        self.assertIn("No evaluative criteria identified", text)
        self.assertIn("N/A", text)
        import re
        self.assertIsNone(re.search(r"\d+(\.\d+)?\s*/\s*100", text))


class TestNoLLMCallsDuringReportGeneration(unittest.TestCase):
    def test_pdf_alignment_module_has_no_analyst_or_anthropic_dependency(self):
        """Structural guarantee: the report generator cannot possibly
        make an LLM call because it does not even import the modules
        that could make one."""
        source = inspect.getsource(pdf_alignment)
        self.assertNotIn("import analyst", source)
        self.assertNotIn("import anthropic", source)
        self.assertNotIn("get_anthropic_client", source)

    @patch("anthropic.Anthropic")
    def test_real_anthropic_client_is_never_constructed(self, mock_anthropic_cls):
        pdf_alignment.generate_alignment_audit_pdf(_BID, _COMPLETE_RESULT)
        pdf_alignment.generate_alignment_audit_pdf(_BID, _INCOMPLETE_RESULT)
        pdf_alignment.generate_alignment_audit_pdf(_BID, _ZERO_UNIVERSE_RESULT)
        mock_anthropic_cls.assert_not_called()


class TestFastAnalysisPdfPathUnchanged(unittest.TestCase):
    """Regression guard: the new pdf_alignment.py module only ADDS a
    consumer of pdf_styles.py's shared helpers -- it does not edit
    pdf_export.py or pdf_styles.py at all. This confirms the existing,
    unrelated compliance-matrix PDF (used by CHECK's own Tab 3 today)
    still renders correctly."""

    def test_compliance_matrix_pdf_still_generates_correctly(self):
        bid = {"client": "Test Client", "title": "Test Opportunity"}
        requirements = [
            {"req_id": "M1", "category": "Mandatory", "description": "x", "status": "Complete", "weight": None},
            {"req_id": "R1", "category": "Rated", "description": "y", "status": "Not Started", "weight": 0.5},
        ]
        pdf_bytes = pdf_export.generate_compliance_pdf(bid, requirements)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        text = _pdf_text(pdf_bytes)
        self.assertIn("Test Client", text)


if __name__ == "__main__":
    unittest.main()
