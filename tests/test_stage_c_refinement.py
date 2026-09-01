"""
Stage C Cross-Document Reconciliation Refinement Test Suite.
Verifies:
1. Bank of Canada Regression Cases (False positive date and submission dimension suppression; removal of tender-specific heuristics).
2. Positive True Conflict Cases (Contradictory dates, submission channels, envelope separation, insurance, page limits).
3. Like-with-Like Insurance Comparison (Distinct classes = NO CONFLICT; same class = TRUE CONFLICT).
4. Same-Document Same-Milestone Date Inconsistencies (Classified as REVIEW_ITEM).
5. Source Validity & Provenance Grounding (Physical vs Synthesized vs Partial).
6. Frozen Bank of Canada Reconciliation Replay.
"""
import os
import json
import unittest

from extractor import (
    classify_date_milestone,
    classify_submission_rule_dimension,
    classify_insurance_class,
    validate_conflict_source_validity,
    detect_document_conflicts,
    reconcile_package_facts
)


class TestStageCBankOfCanadaRegression(unittest.TestCase):
    """Scenario 1: Regression tests ensuring RC1 false positives and tender-specific heuristics are eliminated."""

    def test_regression_a_question_deadline_vs_bid_closing_suppressed(self):
        """TEST A: Question Acceptance Deadline 2026-09-10 vs Bid Closing Date 2026-09-30 -> NO TRUE CONFLICT."""
        normalized = {
            "dates": [
                {"milestone": "Question Acceptance Deadline", "date": "2026-09-10", "source_doc": "abstract.pdf"},
                {"milestone": "Bid Closing Date", "date": "2026-09-30", "source_doc": "abstract.pdf"}
            ]
        }
        pkg_files = ["abstract.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        # Must NOT generate a DATE_CONFLICT for distinct sequential milestones
        date_conflicts = [c for c in conflicts if c.get("conflict_type") == "DATE_CONFLICT"]
        self.assertEqual(len(date_conflicts), 0)

    def test_regression_b_electronic_submission_vs_excel_format_suppressed(self):
        """TEST B: Electronic Bid Submission vs Excel Spreadsheet -> NO TRUE CONFLICT."""
        normalized = {
            "submission_rules": [
                {"item": "Electronic Bid Submission", "format": "Electronic", "details": "Upload via portal", "source_doc": "abstract.pdf"},
                {"item": "Pricing Form", "format": "Excel Spreadsheet", "details": "Complete all tabs", "source_doc": "Appendix_E.xlsx"}
            ]
        }
        pkg_files = ["abstract.pdf", "Appendix_E.xlsx"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        # Must NOT generate SUBMISSION_RULE_CONFLICT for complementary rules across different dimensions
        sub_conflicts = [c for c in conflicts if c.get("conflict_type") == "SUBMISSION_RULE_CONFLICT"]
        self.assertEqual(len(sub_conflicts), 0)

    def test_regression_c_attachment_specific_requirement_not_spurious_conflict(self):
        """TEST C: Requirement in specific attachment without contradiction is normal procurement structure -> 0 conflicts."""
        normalized = {
            "requirements": [
                {
                    "req_id": "M4",
                    "category": "Mandatory",
                    "description": "Bilingualism - Each proposal must provide written confirmation of ability to provide all services in English and French.",
                    "source_refs": [{"source_doc": "Appendix_B3.xlsx"}]
                }
            ]
        }
        pkg_files = ["abstract.pdf", "Appendix_B3.xlsx", "Appendix_A.docx"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        # No artificial ambiguity or conflict manufactured from standard appendix structure
        self.assertEqual(len(conflicts), 0)


class TestStageCLikeWithLikeInsuranceComparison(unittest.TestCase):
    """Scenario 2: Like-with-like insurance comparison logic."""

    def test_distinct_insurance_classes_no_conflict(self):
        """Commercial General Liability $2M vs Professional Liability / E&O $5M -> NO CONFLICT."""
        normalized = {
            "commercial_clauses": [
                {"topic": "Commercial General Liability Insurance", "details": "$2,000,000 commercial general liability policy", "source_doc": "Agreement.docx"},
                {"topic": "Professional Liability / Errors & Omissions", "details": "$5,000,000 professional liability policy", "source_doc": "Addendum_2.pdf"}
            ]
        }
        pkg_files = ["Agreement.docx", "Addendum_2.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        ins_conflicts = [c for c in conflicts if c.get("conflict_type") == "COMMERCIAL_TERM_CONFLICT"]
        self.assertEqual(len(ins_conflicts), 0)

    def test_same_insurance_class_contradiction_is_true_conflict(self):
        """Commercial General Liability $2M vs Commercial General Liability $5M across docs -> TRUE CONFLICT."""
        normalized = {
            "commercial_clauses": [
                {"topic": "Commercial General Liability Insurance", "details": "$2,000,000 commercial general liability policy", "source_doc": "Agreement.docx"},
                {"topic": "Commercial General Liability Insurance", "details": "$5,000,000 commercial general liability policy", "source_doc": "Addendum_2.pdf"}
            ]
        }
        pkg_files = ["Agreement.docx", "Addendum_2.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        ins_conflicts = [c for c in conflicts if c.get("conflict_type") == "COMMERCIAL_TERM_CONFLICT" and c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(ins_conflicts), 1)
        self.assertEqual(ins_conflicts[0]["source_validity"], "PHYSICAL_BOTH")


class TestStageCSameDocumentSameMilestoneDates(unittest.TestCase):
    """Scenario 3: Same physical document containing differing dates for the same semantic milestone."""

    def test_same_document_differing_dates_is_review_item(self):
        """Bid Closing Date 2026-09-15 vs Bid Closing Date 2026-09-30 in same document -> REVIEW_ITEM."""
        normalized = {
            "dates": [
                {"milestone": "Bid Closing Date", "date": "2026-09-15", "source_doc": "Main_RFP.pdf"},
                {"milestone": "Bid Closing Date", "date": "2026-09-30", "source_doc": "Main_RFP.pdf"}
            ]
        }
        pkg_files = ["Main_RFP.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["classification"], "REVIEW_ITEM")
        self.assertEqual(conflicts[0]["source_validity"], "PHYSICAL_BOTH")
        self.assertIn("Internal source inconsistency", conflicts[0]["reason"])


class TestStageCPositiveTrueConflicts(unittest.TestCase):
    """Scenario 4: Positive tests ensuring legitimate contradictions are captured as TRUE_CONFLICT."""

    def test_positive_a_closing_date_contradiction_across_docs(self):
        """Positive Case A: Bid Closing Date 2026-09-15 vs Bid Closing Date 2026-09-30 across docs -> TRUE CONFLICT."""
        normalized = {
            "dates": [
                {"milestone": "Bid Closing Date", "date": "2026-09-15", "source_doc": "Main_RFP.pdf"},
                {"milestone": "Bid Closing Date", "date": "2026-09-30", "source_doc": "Addendum_1.pdf"}
            ]
        }
        pkg_files = ["Main_RFP.pdf", "Addendum_1.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)

        date_conflicts = [c for c in conflicts if c.get("conflict_type") == "DATE_CONFLICT" and c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(date_conflicts), 1)
        self.assertEqual(date_conflicts[0]["source_validity"], "PHYSICAL_BOTH")
        self.assertEqual(date_conflicts[0]["confidence"], "HIGH")

    def test_positive_b_submission_channel_contradiction(self):
        """Positive Case B: Submission via MERX vs Submission via email only -> TRUE CONFLICT."""
        normalized = {
            "submission_rules": [
                {"item": "Transmission Channel", "format": "MERX electronic upload", "details": "Upload proposal on MERX", "source_doc": "Main_RFP.pdf"},
                {"item": "Transmission Channel", "format": "Email submission only", "details": "Submit via email only to procurement officer", "source_doc": "Appendix_Instructions.docx"}
            ]
        }
        pkg_files = ["Main_RFP.pdf", "Appendix_Instructions.docx"]
        conflicts = detect_document_conflicts(normalized, pkg_files)

        chan_conflicts = [c for c in conflicts if c.get("conflict_type") == "SUBMISSION_RULE_CONFLICT" and c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(chan_conflicts), 1)
        self.assertEqual(chan_conflicts[0]["source_validity"], "PHYSICAL_BOTH")

    def test_positive_c_envelope_separation_contradiction(self):
        """Positive Case C: Financial proposal must be separate vs Financial and technical combined -> TRUE CONFLICT."""
        normalized = {
            "submission_rules": [
                {"item": "Proposal Envelopes", "format": "Separate Envelopes", "details": "Financial proposal must be separate from technical", "source_doc": "Main_RFP.pdf"},
                {"item": "Proposal Package", "format": "Single Combined PDF", "details": "Combined technical and financial package in single file", "source_doc": "Appendix_A.docx"}
            ]
        }
        pkg_files = ["Main_RFP.pdf", "Appendix_A.docx"]
        conflicts = detect_document_conflicts(normalized, pkg_files)

        env_conflicts = [c for c in conflicts if c.get("conflict_type") == "SUBMISSION_RULE_CONFLICT" and c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(env_conflicts), 1)
        self.assertEqual(env_conflicts[0]["source_validity"], "PHYSICAL_BOTH")

    def test_positive_d_insurance_requirement_contradiction(self):
        """Positive Case D: Commercial general liability $2M vs $5M -> TRUE CONFLICT."""
        normalized = {
            "commercial_clauses": [
                {"topic": "Commercial General Liability Insurance", "details": "$2,000,000 commercial general liability policy", "source_doc": "Agreement.docx"},
                {"topic": "Commercial General Liability Insurance", "details": "$5,000,000 commercial general liability policy", "source_doc": "Addendum_2.pdf"}
            ]
        }
        pkg_files = ["Agreement.docx", "Addendum_2.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)

        ins_conflicts = [c for c in conflicts if c.get("conflict_type") == "COMMERCIAL_TERM_CONFLICT" and c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(ins_conflicts), 1)
        self.assertEqual(ins_conflicts[0]["source_validity"], "PHYSICAL_BOTH")

    def test_positive_e_page_limit_contradiction(self):
        """Positive Case E: Page limit 10 pages vs Page limit 15 pages for same section -> TRUE CONFLICT."""
        normalized = {
            "submission_rules": [
                {"item": "RFP Response Document", "format": "PDF", "details": "Maximum 10 pages for technical proposal", "source_doc": "Main_RFP.pdf"},
                {"item": "RFP Response Document", "format": "PDF", "details": "Responses must not exceed 15 pages for technical proposal", "source_doc": "General_Instructions.docx"}
            ]
        }
        pkg_files = ["Main_RFP.pdf", "General_Instructions.docx"]
        conflicts = detect_document_conflicts(normalized, pkg_files)

        page_conflicts = [c for c in conflicts if c.get("conflict_type") == "SUBMISSION_RULE_CONFLICT" and c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(page_conflicts), 1)
        self.assertEqual(page_conflicts[0]["source_validity"], "PHYSICAL_BOTH")


class TestStageCSourceValidityAndProvenance(unittest.TestCase):
    """Scenario 5: Source validity classifications and synthetic reference downgrades."""

    def test_physical_both_when_both_filenames_resolve_to_physical_files(self):
        src_a = {"doc": "RFP.pdf", "text": "2026-09-15"}
        src_b = {"doc": "Addendum.pdf", "text": "2026-09-30"}
        pkg_files = ["RFP.pdf", "Addendum.pdf"]
        sv = validate_conflict_source_validity(src_a, src_b, pkg_files)
        self.assertEqual(sv, "PHYSICAL_BOTH")

    def test_physical_and_synthesized_overview_is_physical_partial(self):
        src_a = {"doc": "Appendix_B3.xlsx", "text": "Bilingual mandatory"}
        src_b = {"doc": "General RFP Overview", "text": "Omission in overview"}
        pkg_files = ["Appendix_B3.xlsx", "RFP.pdf"]
        sv = validate_conflict_source_validity(src_a, src_b, pkg_files)
        self.assertEqual(sv, "PHYSICAL_PARTIAL")

    def test_synthesized_overview_downgrades_to_review_item(self):
        normalized = {
            "dates": [
                {"milestone": "Submission Deadline", "date": "2026-09-15", "source_doc": "RFP.pdf"},
                {"milestone": "Submission Deadline", "date": "2026-09-30", "source_doc": "Executive Brief"}
            ]
        }
        pkg_files = ["RFP.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["classification"], "REVIEW_ITEM")
        self.assertEqual(conflicts[0]["source_validity"], "PHYSICAL_PARTIAL")

    def test_missing_or_invalid_filename_downgraded(self):
        normalized = {
            "dates": [
                {"milestone": "Submission Deadline", "date": "2026-09-15", "source_doc": "Nonexistent_File.pdf"},
                {"milestone": "Submission Deadline", "date": "2026-09-30", "source_doc": "RFP.pdf"}
            ]
        }
        pkg_files = ["RFP.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["classification"], "REVIEW_ITEM")
        self.assertEqual(conflicts[0]["source_validity"], "PHYSICAL_PARTIAL")


class TestBankOfCanadaStageCReplay(unittest.TestCase):
    """Scenario 6: Replay refined Stage C reconciliation against frozen Bank of Canada normalized facts."""

    def test_bank_of_canada_frozen_replay(self):
        fixture_path = os.path.join(
            os.path.dirname(__file__), "acceptance", "results", "boc_2026_026_normalized_facts.json"
        )
        if not os.path.exists(fixture_path):
            self.skipTest(f"Frozen Bank of Canada normalized facts fixture not found at: {fixture_path}")

        with open(fixture_path, "r", encoding="utf-8") as f:
            boc_normalized_facts = json.load(f)

        pkg_files = [
            "abstract.pdf",
            "OriginalRevision/RFP 2026-026 - Appendix A - Submission Form.docx",
            "OriginalRevision/RFP 2026-026 - Appendix B1 - Mandatory criteria.xlsx",
            "OriginalRevision/RFP 2026-026 - Appendix B2 - Mandatory criteria.xlsx",
            "OriginalRevision/RFP 2026-026 - Appendix B3 - Mandatory criteria.xlsx",
            "OriginalRevision/RFP 2026-026 - Appendix C1 - Minimum qualification requirements.xlsx",
            "OriginalRevision/RFP 2026-026 - Appendix C2 - Minimum qualification requirements.xlsx",
            "OriginalRevision/RFP 2026-026 - Appendix C3 - Minimum qualification requirement.xlsx",
            "OriginalRevision/RFP 2026-026 - Appendix D1 - Rated criteria response form.docx",
            "OriginalRevision/RFP 2026-026 - Appendix D2 - Rated Criteria Response Form.docx",
            "OriginalRevision/RFP 2026-026 - Appendix D3 - Rated Criteria Response Form.docx",
            "OriginalRevision/RFP 2026-026 - Appendix E - Pricing Form.xlsx",
            "OriginalRevision/DP 2026-026 - Annexe F - Questionnaire ESG.xlsx",
            "OriginalRevision/RFP 2026-06 - Appendix G - Form of Agreement.docx",
            "Amendment1/RFP 2026-026 - Appendix D2 - Rated Criteria Response REVISED.docx"
        ]

        replayed_conflicts = reconcile_package_facts(boc_normalized_facts, pkg_files)

        # 1. False positive CONF-DATE-1 (Question Deadline vs Bid Closing) must be SUPPRESSED
        date_conflicts = [c for c in replayed_conflicts if c.get("conflict_type") == "DATE_CONFLICT"]
        self.assertEqual(len(date_conflicts), 0, f"Expected 0 date conflicts, found: {date_conflicts}")

        # 2. False positive CONF-SUB-2 (Electronic Submission vs Excel Workbook) must be SUPPRESSED
        sub_conflicts = [c for c in replayed_conflicts if c.get("conflict_type") == "SUBMISSION_RULE_CONFLICT"]
        self.assertEqual(len(sub_conflicts), 0, f"Expected 0 submission conflicts, found: {sub_conflicts}")

        # 3. Tender-specific bilingual heuristic eliminated; generic logic produces 0 spurious mandatory conflicts
        mand_conflicts = [c for c in replayed_conflicts if c.get("conflict_type") == "MANDATORY_REQUIREMENT_CONFLICT"]
        self.assertEqual(len(mand_conflicts), 0, f"Expected 0 mandatory conflicts, found: {mand_conflicts}")

        # 4. Total replayed items = exactly 0 (0 known false positives remain in the frozen Bank of Canada replay)
        self.assertEqual(len(replayed_conflicts), 0, f"Expected 0 conflicts/review items, found: {replayed_conflicts}")


if __name__ == "__main__":
    unittest.main()
