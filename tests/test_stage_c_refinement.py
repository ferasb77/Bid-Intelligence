"""
Stage C Cross-Document Reconciliation Refinement Test Suite.
Verifies:
1. Bank of Canada Regression Cases (False positive date and submission dimension suppression; removal of tender-specific heuristics).
2. Evaluation Criteria Same-Metric Normalization (Explicit ID precedence, pipeline-realistic stage strings, category-scoped weighting).
3. Mandatory Requirement Subject Identity (Role-scoped experience & clearance comparison; M1 vs M2 corporate criteria isolation).
4. Source-Aware Opposing Pair Selection & Internal Inconsistency Handling (Envelope, channel, commercial caps, insurance, deliverables).
5. Submission Dimension Precedence (Portal registration vs submission channel).
6. Scope / Deliverable Conflict Identity & Operational Scope (Like-with-like deliverable type & category scope).
7. Panel / Commercial Cap Normalization (Panel vendors vs Annual rate increase = NO CONFLICT; Panel 5 vs 8 = TRUE CONFLICT).
8. Security Clearance Priority & Contradictions (TOP_SECRET -> SECRET -> RELIABILITY).
9. Insurance Monetary Amount Normalization & Year Safety ($2M vs $2,000,000 = NO CONFLICT; 2026 ignored).
10. Source Validity & Provenance Grounding (Physical vs Synthesized vs Partial).
11. Pipeline-Realistic Integration Test (Raw document facts -> normalize_package_facts -> reconcile_package_facts preserving deliverable source identity).
12. Frozen Bank of Canada Reconciliation Replay (Replays to empty list []).
"""
import os
import json
import unittest

from extractor import (
    classify_date_milestone,
    classify_submission_rule_dimension,
    classify_insurance_class,
    classify_commercial_topic,
    extract_commercial_limit,
    classify_security_clearance,
    extract_monetary_amount,
    select_opposing_pair,
    validate_conflict_source_validity,
    detect_document_conflicts,
    reconcile_package_facts,
    normalize_package_facts,
    _extract_eval_criterion_identity,
    _extract_evaluation_scope,
    _extract_requirement_subject,
    _extract_deliverable_scope,
    _extract_operational_scope
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
        self.assertEqual(len(conflicts), 0)


class TestStageCEvaluationCriteriaIdentity(unittest.TestCase):
    """Scenario 2: Evaluation criteria comparison on same metric & explicit ID only."""

    def test_overall_technical_weight_contradiction_is_true_conflict(self):
        """Overall Technical Weight = 75% vs Overall Technical Weight = 70% -> TRUE_CONFLICT."""
        normalized = {
            "evaluation_criteria": [
                {"stage": "Overall Scoring Ratio", "criterion": "Overall Technical Weight", "weight": "75%", "source_doc": "Main_RFP.pdf"},
                {"stage": "Overall Scoring Ratio", "criterion": "Overall Technical Weight", "weight": "70%", "source_doc": "Addendum_1.pdf"}
            ]
        }
        pkg_files = ["Main_RFP.pdf", "Addendum_1.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        eval_conflicts = [c for c in conflicts if c.get("conflict_type") == "EVALUATION_CONFLICT" and c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(eval_conflicts), 1)
        self.assertNotEqual(eval_conflicts[0]["source_a"]["text"], eval_conflicts[0]["source_b"]["text"])

    def test_same_criterion_name_differing_points_is_true_conflict(self):
        """Criterion 'Methodology' = 25 points vs 'Methodology' = 30 points -> TRUE_CONFLICT."""
        normalized = {
            "evaluation_criteria": [
                {"stage": "Rated Criteria", "criterion": "Technical Methodology", "weight": "25 points", "source_doc": "Main_RFP.pdf"},
                {"stage": "Rated Criteria", "criterion": "Technical Methodology", "weight": "30 points", "source_doc": "Addendum_2.pdf"}
            ]
        }
        pkg_files = ["Main_RFP.pdf", "Addendum_2.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        eval_conflicts = [c for c in conflicts if c.get("conflict_type") == "EVALUATION_CONFLICT" and c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(eval_conflicts), 1)

    def test_different_criteria_names_no_conflict(self):
        """Technical Approach = 30 points vs Team Experience = 20 points -> NO CONFLICT."""
        normalized = {
            "evaluation_criteria": [
                {"stage": "Rated Criteria", "criterion": "Technical Approach & Methodology", "weight": "30 points", "source_doc": "Main_RFP.pdf"},
                {"stage": "Rated Criteria", "criterion": "Key Personnel & Team Experience", "weight": "20 points", "source_doc": "Main_RFP.pdf"}
            ]
        }
        pkg_files = ["Main_RFP.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        eval_conflicts = [c for c in conflicts if c.get("conflict_type") == "EVALUATION_CONFLICT"]
        self.assertEqual(len(eval_conflicts), 0)

    def test_evaluation_criterion_id_regex_recognition(self):
        """Verify R1, CR1, TC2 criterion IDs are properly recognized without character class bugs."""
        self.assertEqual(_extract_eval_criterion_identity({"criterion_id": "R1"}), "CRITERION_R1")
        self.assertEqual(_extract_eval_criterion_identity({"criterion_id": "CR1"}), "CRITERION_CR1")
        self.assertEqual(_extract_eval_criterion_identity({"criterion_id": "TC2"}), "CRITERION_TC2")

    def test_r1_vs_r2_same_broad_keyword_no_conflict(self):
        """Pipeline-realistic stage strings: R1 - Methodology vs R2 - Technical Approach -> NO CONFLICT."""
        normalized = {
            "evaluation_criteria": [
                {"stage": "R1 - Methodology", "weight": "20 points", "threshold": "70%", "notes": "", "source_doc": "Main_RFP.pdf"},
                {"stage": "R2 - Technical Approach", "weight": "30 points", "threshold": "70%", "notes": "", "source_doc": "Main_RFP.pdf"}
            ]
        }
        pkg_files = ["Main_RFP.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        eval_conflicts = [c for c in conflicts if c.get("conflict_type") == "EVALUATION_CONFLICT"]
        self.assertEqual(len(eval_conflicts), 0)

    def test_same_r1_differing_weights_is_true_conflict(self):
        """Pipeline-realistic stage strings: R1 - Methodology = 20 vs R1 - Methodology = 30 across docs -> TRUE_CONFLICT."""
        normalized = {
            "evaluation_criteria": [
                {"stage": "R1 - Methodology", "weight": "20 points", "threshold": "70%", "notes": "", "source_doc": "Main_RFP.pdf"},
                {"stage": "R1 - Methodology", "weight": "30 points", "threshold": "70%", "notes": "", "source_doc": "Addendum_1.pdf"}
            ]
        }
        pkg_files = ["Main_RFP.pdf", "Addendum_1.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        eval_conflicts = [c for c in conflicts if c.get("conflict_type") == "EVALUATION_CONFLICT" and c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(eval_conflicts), 1)

    def test_same_criterion_across_different_categories_no_conflict(self):
        """Category 1 Methodology = 30 vs Category 2 Methodology = 25 -> NO CONFLICT."""
        normalized = {
            "evaluation_criteria": [
                {"stage": "Category 1 Technical Evaluation", "criterion": "Technical Methodology", "weight": "30 points", "source_doc": "Main_RFP.pdf"},
                {"stage": "Category 2 Technical Evaluation", "criterion": "Technical Methodology", "weight": "25 points", "source_doc": "Main_RFP.pdf"}
            ]
        }
        pkg_files = ["Main_RFP.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        eval_conflicts = [c for c in conflicts if c.get("conflict_type") == "EVALUATION_CONFLICT"]
        self.assertEqual(len(eval_conflicts), 0)

    def test_same_criterion_same_category_differing_weights_is_true_conflict(self):
        """Category 1 Methodology = 30 vs Category 1 Addendum Methodology = 25 -> TRUE_CONFLICT."""
        normalized = {
            "evaluation_criteria": [
                {"stage": "Category 1 Technical Evaluation", "criterion": "Technical Methodology", "weight": "30 points", "source_doc": "Main_RFP.pdf"},
                {"stage": "Category 1 Technical Evaluation", "criterion": "Technical Methodology", "weight": "25 points", "source_doc": "Addendum_1.pdf"}
            ]
        }
        pkg_files = ["Main_RFP.pdf", "Addendum_1.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        eval_conflicts = [c for c in conflicts if c.get("conflict_type") == "EVALUATION_CONFLICT" and c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(eval_conflicts), 1)


class TestStageCMandatorySubjectIdentity(unittest.TestCase):
    """Scenario 3: Mandatory requirement comparison by subject / role identity."""

    def test_different_roles_same_category_no_conflict(self):
        """Category 1: Project Manager (10 yrs) vs Facilitator (5 yrs) -> NO CONFLICT."""
        normalized = {
            "requirements": [
                {
                    "req_id": "M1",
                    "category": "Mandatory",
                    "description": "Category 1: Project Manager must possess minimum 10 years experience.",
                    "source_refs": [{"source_doc": "Appendix_B1.xlsx"}]
                },
                {
                    "req_id": "M2",
                    "category": "Mandatory",
                    "description": "Category 1: Facilitator must possess minimum 5 years experience.",
                    "source_refs": [{"source_doc": "Appendix_B1.xlsx"}]
                }
            ]
        }
        pkg_files = ["Appendix_B1.xlsx"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        mand_conflicts = [c for c in conflicts if c.get("conflict_type") == "MANDATORY_REQUIREMENT_CONFLICT"]
        self.assertEqual(len(mand_conflicts), 0)

    def test_same_role_differing_thresholds_is_true_conflict(self):
        """Category 1: Project Manager (10 yrs) vs Addendum Project Manager (7 yrs) -> TRUE_CONFLICT."""
        normalized = {
            "requirements": [
                {
                    "req_id": "M1",
                    "category": "Mandatory",
                    "description": "Category 1: Project Manager must possess minimum 10 years experience.",
                    "source_refs": [{"source_doc": "Appendix_B1.xlsx"}]
                },
                {
                    "req_id": "M1",
                    "category": "Mandatory",
                    "description": "Category 1: Project Manager must possess minimum 7 years experience.",
                    "source_refs": [{"source_doc": "Addendum_1.docx"}]
                }
            ]
        }
        pkg_files = ["Appendix_B1.xlsx", "Addendum_1.docx"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        mand_conflicts = [c for c in conflicts if c.get("conflict_type") == "MANDATORY_REQUIREMENT_CONFLICT" and c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(mand_conflicts), 1)

    def test_clearance_different_roles_no_conflict(self):
        """Project Manager requires Secret vs Consultant requires Reliability -> NO CONFLICT."""
        normalized = {
            "requirements": [
                {
                    "req_id": "M1",
                    "category": "Mandatory",
                    "description": "Project Manager requires Secret security clearance.",
                    "source_refs": [{"source_doc": "Appendix_B1.docx"}]
                },
                {
                    "req_id": "M2",
                    "category": "Mandatory",
                    "description": "Consultant requires Reliability status screening.",
                    "source_refs": [{"source_doc": "Appendix_B1.docx"}]
                }
            ]
        }
        pkg_files = ["Appendix_B1.docx"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        mand_conflicts = [c for c in conflicts if c.get("conflict_type") == "MANDATORY_REQUIREMENT_CONFLICT"]
        self.assertEqual(len(mand_conflicts), 0)

    def test_clearance_same_role_contradiction_is_true_conflict(self):
        """Project Manager requires Secret vs Project Manager requires Top Secret -> TRUE_CONFLICT."""
        normalized = {
            "requirements": [
                {
                    "req_id": "M1",
                    "category": "Mandatory",
                    "description": "Project Manager requires Secret security clearance.",
                    "source_refs": [{"source_doc": "Main_RFP.pdf"}]
                },
                {
                    "req_id": "M1",
                    "category": "Mandatory",
                    "description": "Project Manager requires Top Secret security clearance.",
                    "source_refs": [{"source_doc": "Addendum_1.pdf"}]
                }
            ]
        }
        pkg_files = ["Main_RFP.pdf", "Addendum_1.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        mand_conflicts = [c for c in conflicts if c.get("conflict_type") == "MANDATORY_REQUIREMENT_CONFLICT" and c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(mand_conflicts), 1)

    def test_m1_corporate_experience_vs_m2_corporate_experience_no_conflict(self):
        """M1 Firm must have 10 years consulting experience vs M2 Firm must have 5 years training experience -> NO CONFLICT."""
        normalized = {
            "requirements": [
                {
                    "req_id": "M1",
                    "category": "Mandatory",
                    "description": "M1: Firm must have minimum 10 years consulting experience.",
                    "source_refs": [{"source_doc": "Main_RFP.pdf"}]
                },
                {
                    "req_id": "M2",
                    "category": "Mandatory",
                    "description": "M2: Firm must have minimum 5 years training experience.",
                    "source_refs": [{"source_doc": "Main_RFP.pdf"}]
                }
            ]
        }
        pkg_files = ["Main_RFP.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        mand_conflicts = [c for c in conflicts if c.get("conflict_type") == "MANDATORY_REQUIREMENT_CONFLICT"]
        self.assertEqual(len(mand_conflicts), 0)

    def test_same_m1_differing_threshold_is_true_conflict(self):
        """M1 Firm 10 years experience vs M1 Addendum 7 years experience -> TRUE_CONFLICT."""
        normalized = {
            "requirements": [
                {
                    "req_id": "M1",
                    "category": "Mandatory",
                    "description": "M1: Firm must have minimum 10 years experience in public sector advisory.",
                    "source_refs": [{"source_doc": "Main_RFP.pdf"}]
                },
                {
                    "req_id": "M1",
                    "category": "Mandatory",
                    "description": "M1: Firm must have minimum 7 years experience in public sector advisory.",
                    "source_refs": [{"source_doc": "Addendum_1.docx"}]
                }
            ]
        }
        pkg_files = ["Main_RFP.pdf", "Addendum_1.docx"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        mand_conflicts = [c for c in conflicts if c.get("conflict_type") == "MANDATORY_REQUIREMENT_CONFLICT" and c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(mand_conflicts), 1)


class TestStageCSourceAwareOpposingPairSelection(unittest.TestCase):
    """Scenario 4: Source-aware opposing pair selection and internal inconsistency separation."""

    def test_internal_inconsistency_with_duplicate_in_other_doc_is_review_item(self):
        """A.pdf -> 10 pages, A.pdf -> 15 pages, B.pdf -> 10 pages -> REVIEW_ITEM for A.pdf, NOT cross-document TRUE_CONFLICT."""
        normalized = {
            "submission_rules": [
                {"item": "Proposal Format", "format": "PDF", "details": "Technical proposal maximum 10 pages", "source_doc": "A.pdf"},
                {"item": "Proposal Format", "format": "PDF", "details": "Technical proposal maximum 15 pages", "source_doc": "A.pdf"},
                {"item": "Proposal Format", "format": "PDF", "details": "Technical proposal maximum 10 pages", "source_doc": "B.pdf"}
            ]
        }
        pkg_files = ["A.pdf", "B.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["classification"], "REVIEW_ITEM")
        self.assertIn("A.pdf", conflicts[0]["source_a"]["doc"])
        self.assertIn("A.pdf", conflicts[0]["source_b"]["doc"])

    def test_cross_document_distinct_values_is_true_conflict(self):
        """A.pdf -> 10 pages, B.pdf -> 15 pages, C.pdf -> 10 pages -> TRUE_CONFLICT with different source files."""
        normalized = {
            "submission_rules": [
                {"item": "Proposal Format", "format": "PDF", "details": "Technical proposal maximum 10 pages", "source_doc": "A.pdf"},
                {"item": "Proposal Format", "format": "PDF", "details": "Technical proposal maximum 15 pages", "source_doc": "B.pdf"},
                {"item": "Proposal Format", "format": "PDF", "details": "Technical proposal maximum 10 pages", "source_doc": "C.pdf"}
            ]
        }
        pkg_files = ["A.pdf", "B.pdf", "C.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        true_conflicts = [c for c in conflicts if c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(true_conflicts), 1)
        self.assertNotEqual(true_conflicts[0]["source_a"]["doc"], true_conflicts[0]["source_b"]["doc"])
        self.assertNotEqual(true_conflicts[0]["source_a"]["text"], true_conflicts[0]["source_b"]["text"])

    def test_same_file_envelope_contradiction_is_review_item(self):
        """A.pdf: 'financial response separate' + A.pdf: 'technical and financial combined' -> REVIEW_ITEM."""
        normalized = {
            "submission_rules": [
                {"item": "Financial Envelope", "format": "Separate Envelopes", "details": "financial response separate", "source_doc": "A.pdf"},
                {"item": "Proposal Structure", "format": "Single Combined PDF", "details": "technical and financial combined", "source_doc": "A.pdf"}
            ]
        }
        pkg_files = ["A.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["classification"], "REVIEW_ITEM")
        self.assertEqual(conflicts[0]["source_a"]["doc"], "A.pdf")
        self.assertEqual(conflicts[0]["source_b"]["doc"], "A.pdf")

    def test_cross_file_envelope_contradiction_is_true_conflict(self):
        """A.pdf: 'financial response separate' + B.pdf: 'technical and financial combined' -> TRUE_CONFLICT."""
        normalized = {
            "submission_rules": [
                {"item": "Financial Envelope", "format": "Separate Envelopes", "details": "financial response separate", "source_doc": "A.pdf"},
                {"item": "Proposal Structure", "format": "Single Combined PDF", "details": "technical and financial combined", "source_doc": "B.pdf"}
            ]
        }
        pkg_files = ["A.pdf", "B.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        true_conflicts = [c for c in conflicts if c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(true_conflicts), 1)
        self.assertEqual(true_conflicts[0]["source_a"]["doc"], "A.pdf")
        self.assertEqual(true_conflicts[0]["source_b"]["doc"], "B.pdf")

    def test_same_file_submission_channel_contradiction_is_review_item(self):
        """A.pdf: 'submit through MERX' + A.pdf: 'email only' -> REVIEW_ITEM."""
        normalized = {
            "submission_rules": [
                {"item": "Bid Submission", "format": "Electronic", "details": "Upload bid through MERX", "source_doc": "A.pdf"},
                {"item": "Transmission Channel", "format": "Email", "details": "Submit proposal by email only", "source_doc": "A.pdf"}
            ]
        }
        pkg_files = ["A.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["classification"], "REVIEW_ITEM")

    def test_cross_file_submission_channel_contradiction_is_true_conflict(self):
        """A.pdf: 'submit through MERX' + B.pdf: 'email only' -> TRUE_CONFLICT."""
        normalized = {
            "submission_rules": [
                {"item": "Bid Submission", "format": "Electronic", "details": "Upload bid through MERX", "source_doc": "A.pdf"},
                {"item": "Transmission Channel", "format": "Email", "details": "Submit proposal by email only", "source_doc": "B.pdf"}
            ]
        }
        pkg_files = ["A.pdf", "B.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        true_conflicts = [c for c in conflicts if c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(true_conflicts), 1)
        self.assertEqual(true_conflicts[0]["source_a"]["doc"], "A.pdf")
        self.assertEqual(true_conflicts[0]["source_b"]["doc"], "B.pdf")


class TestStageCInternalInconsistencies(unittest.TestCase):
    """Scenario 5: Explicit same-document REVIEW_ITEM handling for commercial caps, insurance, and deliverables."""

    def test_same_file_insurance_discrepancy_is_review_item(self):
        """Agreement.pdf: CGL $2M + CGL $5M -> REVIEW_ITEM."""
        normalized = {
            "commercial_clauses": [
                {"topic": "Commercial General Liability Insurance", "details": "CGL coverage of $2M", "source_doc": "Agreement.pdf"},
                {"topic": "Commercial General Liability Insurance", "details": "CGL coverage of $5M", "source_doc": "Agreement.pdf"}
            ]
        }
        pkg_files = ["Agreement.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["classification"], "REVIEW_ITEM")
        self.assertEqual(conflicts[0]["source_a"]["doc"], "Agreement.pdf")
        self.assertEqual(conflicts[0]["source_b"]["doc"], "Agreement.pdf")

    def test_same_file_panel_cap_discrepancy_is_review_item(self):
        """RFP.pdf: panel max 5 + panel max 8 -> REVIEW_ITEM."""
        normalized = {
            "commercial_clauses": [
                {"topic": "Panel Vendor Cap", "details": "Maximum panel vendors: 5", "source_doc": "RFP.pdf"},
                {"topic": "Panel Vendor Cap", "details": "Maximum panel vendors: 8", "source_doc": "RFP.pdf"}
            ]
        }
        pkg_files = ["RFP.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["classification"], "REVIEW_ITEM")
        self.assertEqual(conflicts[0]["source_a"]["doc"], "RFP.pdf")
        self.assertEqual(conflicts[0]["source_b"]["doc"], "RFP.pdf")

    def test_same_file_deliverable_quantity_discrepancy_is_review_item(self):
        """SOW.pdf: Leadership cohorts = 12 + Leadership cohorts = 20 -> REVIEW_ITEM."""
        normalized = {
            "deliverables": [
                {"title": "Leadership Cohorts", "description": "Leadership cohorts: 12 cohorts to be delivered", "source_doc": "SOW.pdf"},
                {"title": "Leadership Cohorts", "description": "Leadership cohorts: 20 cohorts to be delivered", "source_doc": "SOW.pdf"}
            ]
        }
        pkg_files = ["SOW.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["classification"], "REVIEW_ITEM")
        self.assertEqual(conflicts[0]["source_a"]["doc"], "SOW.pdf")
        self.assertEqual(conflicts[0]["source_b"]["doc"], "SOW.pdf")


class TestStageCSubmissionDimensionPrecedence(unittest.TestCase):
    """Scenario 6: Precedence of PORTAL_REQUIREMENT over SUBMISSION_CHANNEL."""

    def test_dimension_classification_precedence(self):
        """Verify dimension precedence classification."""
        self.assertEqual(classify_submission_rule_dimension("MERX registration required"), "PORTAL_REQUIREMENT")
        self.assertEqual(classify_submission_rule_dimension("Supplier must maintain a MERX account"), "PORTAL_REQUIREMENT")
        self.assertEqual(classify_submission_rule_dimension("Upload bid through MERX"), "SUBMISSION_CHANNEL")

    def test_portal_registration_and_email_only_no_conflict(self):
        """'MERX registration required' + 'Submit proposal by email only' -> NO SUBMISSION CHANNEL CONFLICT."""
        normalized = {
            "submission_rules": [
                {"item": "Vendor Portal", "format": "Account", "details": "MERX registration required", "source_doc": "Main_RFP.pdf"},
                {"item": "Transmission Channel", "format": "Email", "details": "Submit proposal by email only", "source_doc": "Instructions.docx"}
            ]
        }
        pkg_files = ["Main_RFP.pdf", "Instructions.docx"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        chan_conflicts = [c for c in conflicts if c.get("conflict_type") == "SUBMISSION_RULE_CONFLICT"]
        self.assertEqual(len(chan_conflicts), 0)

    def test_upload_merx_and_email_only_is_true_conflict(self):
        """'Upload bid through MERX' + 'Submit proposal by email only' -> TRUE_CONFLICT."""
        normalized = {
            "submission_rules": [
                {"item": "Bid Submission", "format": "Electronic", "details": "Upload bid through MERX", "source_doc": "Main_RFP.pdf"},
                {"item": "Transmission Channel", "format": "Email", "details": "Submit proposal by email only", "source_doc": "Instructions.docx"}
            ]
        }
        pkg_files = ["Main_RFP.pdf", "Instructions.docx"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        chan_conflicts = [c for c in conflicts if c.get("conflict_type") == "SUBMISSION_RULE_CONFLICT" and c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(chan_conflicts), 1)


class TestStageCScopeDeliverableIdentity(unittest.TestCase):
    """Scenario 7: Like-with-like deliverable reconciliation with category scoping."""

    def test_different_deliverable_types_no_conflict(self):
        """Leadership cohort: 20 participants vs Executive coaching: 10 sessions -> NO CONFLICT."""
        normalized = {
            "deliverables": [
                {"title": "Leadership Cohorts", "description": "Leadership cohort: 20 participants per session", "source_doc": "SOW.pdf"},
                {"title": "Executive Coaching", "description": "Executive coaching sessions: 10 sessions for executives", "source_doc": "SOW.pdf"}
            ]
        }
        pkg_files = ["SOW.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        scope_conflicts = [c for c in conflicts if c.get("conflict_type") == "SCOPE_CONFLICT"]
        self.assertEqual(len(scope_conflicts), 0)

    def test_same_deliverable_differing_quantities_is_true_conflict(self):
        """Leadership cohorts: 20 cohorts vs Leadership cohorts: 12 cohorts -> TRUE_CONFLICT."""
        normalized = {
            "deliverables": [
                {"title": "Leadership Cohorts", "description": "Leadership cohorts: 20 cohorts to be delivered", "source_doc": "SOW.pdf"},
                {"title": "Leadership Cohorts", "description": "Leadership cohorts: 12 cohorts to be delivered", "source_doc": "Pricing_Schedule.xlsx"}
            ]
        }
        pkg_files = ["SOW.pdf", "Pricing_Schedule.xlsx"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        scope_conflicts = [c for c in conflicts if c.get("conflict_type") == "SCOPE_CONFLICT" and c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(scope_conflicts), 1)

    def test_same_deliverable_different_categories_no_conflict(self):
        """Category 1 Leadership Cohorts (12 cohorts) vs Category 2 Leadership Cohorts (20 cohorts) -> NO CONFLICT."""
        normalized = {
            "deliverables": [
                {"title": "Leadership Cohorts", "description": "Category 1 Leadership Cohorts: 12 cohorts to be delivered", "source_doc": "SOW.pdf"},
                {"title": "Leadership Cohorts", "description": "Category 2 Leadership Cohorts: 20 cohorts to be delivered", "source_doc": "SOW.pdf"}
            ]
        }
        pkg_files = ["SOW.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        scope_conflicts = [c for c in conflicts if c.get("conflict_type") == "SCOPE_CONFLICT"]
        self.assertEqual(len(scope_conflicts), 0)

    def test_same_deliverable_same_category_differing_quantity_is_true_conflict(self):
        """Category 1 Leadership Cohorts (12 cohorts) vs Category 1 Addendum Leadership Cohorts (20 cohorts) -> TRUE_CONFLICT."""
        normalized = {
            "deliverables": [
                {"title": "Leadership Cohorts", "description": "Category 1 Leadership Cohorts: 12 cohorts to be delivered", "source_doc": "SOW.pdf"},
                {"title": "Leadership Cohorts", "description": "Category 1 Leadership Cohorts: 20 cohorts to be delivered", "source_doc": "Addendum_1.pdf"}
            ]
        }
        pkg_files = ["SOW.pdf", "Addendum_1.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        scope_conflicts = [c for c in conflicts if c.get("conflict_type") == "SCOPE_CONFLICT" and c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(scope_conflicts), 1)


class TestStageCCommercialCapNormalization(unittest.TestCase):
    """Scenario 8: Commercial term cap classification and reconciliation."""

    def test_commercial_topic_classification(self):
        self.assertEqual(classify_commercial_topic("Panel Size", "Maximum panel vendors: 5"), "PANEL_VENDOR_CAP")
        self.assertEqual(classify_commercial_topic("Annual Increase", "Maximum annual rate increase: 3%"), "ANNUAL_ESCALATION_CAP")
        self.assertEqual(classify_commercial_topic("Rate Ceiling", "Maximum per diem rate of $1,500"), "RATE_CAP")

    def test_different_commercial_topics_no_conflict(self):
        """Maximum panel vendors = 5 vs Maximum annual rate increase = 3% -> NO CONFLICT."""
        normalized = {
            "commercial_clauses": [
                {"topic": "Panel Size", "details": "Maximum panel vendors: 5", "source_doc": "RFP.pdf"},
                {"topic": "Rate Escalation", "details": "Maximum annual rate increase: 3%", "source_doc": "RFP.pdf"}
            ]
        }
        pkg_files = ["RFP.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        comm_conflicts = [c for c in conflicts if c.get("conflict_type") == "COMMERCIAL_TERM_CONFLICT"]
        self.assertEqual(len(comm_conflicts), 0)

    def test_same_commercial_topic_differing_caps_is_true_conflict(self):
        """Maximum panel vendors = 5 vs Maximum panel vendors = 8 -> TRUE_CONFLICT."""
        normalized = {
            "commercial_clauses": [
                {"topic": "Panel Vendor Cap", "details": "Maximum panel vendors: 5", "source_doc": "Main_RFP.pdf"},
                {"topic": "Panel Vendor Cap", "details": "Maximum panel vendors: 8", "source_doc": "Addendum_1.pdf"}
            ]
        }
        pkg_files = ["Main_RFP.pdf", "Addendum_1.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        comm_conflicts = [c for c in conflicts if c.get("conflict_type") == "COMMERCIAL_TERM_CONFLICT" and c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(comm_conflicts), 1)


class TestStageCSecurityClearancePriority(unittest.TestCase):
    """Scenario 9: Security clearance classifier priority and contradiction checking."""

    def test_top_secret_classified_first(self):
        """Top Secret security clearance required -> TOP_SECRET."""
        self.assertEqual(classify_security_clearance("Top Secret security clearance required"), "TOP_SECRET")
        self.assertEqual(classify_security_clearance("Valid Secret clearance required"), "SECRET")
        self.assertEqual(classify_security_clearance("Reliability status screening required"), "RELIABILITY")


class TestStageCInsuranceAmountNormalization(unittest.TestCase):
    """Scenario 10: Monetary amount parsing, year protection, and like-with-like insurance reconciliation."""

    def test_monetary_amount_extraction(self):
        self.assertEqual(extract_monetary_amount("CGL coverage of $2,000,000"), 2000000.0)
        self.assertEqual(extract_monetary_amount("CGL insurance minimum $2M including bodily injury"), 2000000.0)
        self.assertEqual(extract_monetary_amount("CGL coverage of $5M"), 5000000.0)
        self.assertEqual(extract_monetary_amount("Coverage of CAD 5,000,000"), 5000000.0)
        self.assertEqual(extract_monetary_amount("2 million liability"), 2000000.0)
        self.assertEqual(extract_monetary_amount("2M coverage"), 2000000.0)

    def test_year_not_interpreted_as_monetary_amount(self):
        """Policy effective in 2026; evidence of insurance required -> None (not 2026.0)."""
        self.assertIsNone(extract_monetary_amount("Policy effective in 2026; evidence of insurance required"))
        self.assertIsNone(extract_monetary_amount("Solicitation number RFP 2026-026"))

    def test_matching_monetary_limits_with_differing_prose_no_conflict(self):
        """CGL coverage of $2,000,000 vs CGL insurance minimum $2M including bodily injury -> NO CONFLICT."""
        normalized = {
            "commercial_clauses": [
                {"topic": "Commercial General Liability Insurance", "details": "CGL coverage of $2,000,000", "source_doc": "Agreement.docx"},
                {"topic": "Commercial General Liability", "details": "CGL insurance minimum $2M including bodily injury", "source_doc": "Addendum_1.pdf"}
            ]
        }
        pkg_files = ["Agreement.docx", "Addendum_1.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        ins_conflicts = [c for c in conflicts if c.get("conflict_type") == "COMMERCIAL_TERM_CONFLICT"]
        self.assertEqual(len(ins_conflicts), 0)

    def test_differing_monetary_limits_same_class_is_true_conflict(self):
        """CGL coverage of $2M vs CGL coverage of $5M -> TRUE CONFLICT."""
        normalized = {
            "commercial_clauses": [
                {"topic": "Commercial General Liability Insurance", "details": "CGL coverage of $2M", "source_doc": "Agreement.docx"},
                {"topic": "Commercial General Liability Insurance", "details": "CGL coverage of $5M", "source_doc": "Addendum_2.pdf"}
            ]
        }
        pkg_files = ["Agreement.docx", "Addendum_2.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        ins_conflicts = [c for c in conflicts if c.get("conflict_type") == "COMMERCIAL_TERM_CONFLICT" and c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(ins_conflicts), 1)
        self.assertEqual(ins_conflicts[0]["source_validity"], "PHYSICAL_BOTH")


class TestStageCSourceValidityAndProvenance(unittest.TestCase):
    """Scenario 11: Source validity classifications and synthetic reference downgrades."""

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


class TestStageCPipelineRealisticIntegration(unittest.TestCase):
    """Scenario 12: Pipeline-realistic end-to-end fact flow from raw document facts through normalization to reconciliation."""

    def test_deliverable_source_identity_survives_normalization_to_reconciliation(self):
        """Verify deliverable objects tagged in document facts retain source_doc through normalization and Stage C."""
        doc1_facts = {
            "doc_metadata": {"title": "SOW Statement of Work"},
            "deliverables": [
                {"title": "Leadership Cohorts", "description": "Deliver 20 leadership training cohorts", "source_doc": "SOW_Main.pdf"}
            ],
            "requirements": [],
            "dates": [],
            "evaluation_criteria": [],
            "submission_rules": [],
            "commercial_clauses": []
        }
        doc2_facts = {
            "doc_metadata": {"title": "Pricing & Deliverables Schedule"},
            "deliverables": [
                {"title": "Leadership Cohorts", "description": "Deliver 12 leadership training cohorts", "source_doc": "Pricing_Schedule.xlsx"}
            ],
            "requirements": [],
            "dates": [],
            "evaluation_criteria": [],
            "submission_rules": [],
            "commercial_clauses": []
        }

        pkg_metadata = {
            "files": ["SOW_Main.pdf", "Pricing_Schedule.xlsx"],
            "page_counts": {"SOW_Main.pdf": 10},
            "sheet_names": {"Pricing_Schedule.xlsx": ["Sheet1"]}
        }

        # Run Stage B normalization
        normalized = normalize_package_facts([doc1_facts, doc2_facts], pkg_metadata)

        # Verify source_doc preserved on deliverables
        self.assertEqual(len(normalized["deliverables"]), 2)
        self.assertEqual(normalized["deliverables"][0]["source_doc"], "SOW_Main.pdf")
        self.assertEqual(normalized["deliverables"][1]["source_doc"], "Pricing_Schedule.xlsx")

        # Run Stage C reconciliation
        conflicts = reconcile_package_facts(normalized, pkg_metadata["files"])
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["conflict_type"], "SCOPE_CONFLICT")
        self.assertEqual(conflicts[0]["classification"], "TRUE_CONFLICT")
        self.assertEqual(conflicts[0]["source_a"]["doc"], "SOW_Main.pdf")
        self.assertEqual(conflicts[0]["source_b"]["doc"], "Pricing_Schedule.xlsx")


class TestBankOfCanadaStageCReplay(unittest.TestCase):
    """Scenario 13: Replay refined Stage C reconciliation against frozen Bank of Canada normalized facts."""

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


class TestStageCGenericScopeExtraction(unittest.TestCase):
    """
    Scenario 14: Generic operational scope extraction.

    Verifies that _extract_operational_scope uses only explicit procurement
    scope markers (Category N, Stream N, Lot N, Work Package N) and never
    infers a numbered category from subject-matter keywords such as
    'HR Advisory', 'Facilitation', or 'Learning & Development'.

    Also confirms that bare filename characters like 'd1', 'd2', 'd3' are
    not treated as scope markers.
    """

    # A. Service domain without explicit category -> GENERAL_SCOPE
    def test_a_hr_advisory_without_category_marker_is_general_scope(self):
        """'HR Advisory Services' without an explicit category -> GENERAL_SCOPE."""
        self.assertEqual(_extract_operational_scope("HR Advisory Services"), "GENERAL_SCOPE")

    # B. Service domain without explicit category -> GENERAL_SCOPE
    def test_b_facilitation_without_category_marker_is_general_scope(self):
        """'Facilitation Services' without an explicit category -> GENERAL_SCOPE."""
        self.assertEqual(_extract_operational_scope("Facilitation Services"), "GENERAL_SCOPE")

    # C. Service domain without explicit category -> GENERAL_SCOPE
    def test_c_learning_and_development_without_category_marker_is_general_scope(self):
        """'Learning & Development Services' without an explicit category -> GENERAL_SCOPE."""
        self.assertEqual(_extract_operational_scope("Learning & Development Services"), "GENERAL_SCOPE")
        self.assertEqual(_extract_operational_scope("Learning and Development"), "GENERAL_SCOPE")

    # D. Explicit category wins over any domain keyword in the same text
    def test_d_category_2_facilitation_is_category_2_not_category_3(self):
        """'Category 2 - Facilitation Services' -> CATEGORY_2 (not CATEGORY_3)."""
        result = _extract_operational_scope("Category 2 - Facilitation Services")
        self.assertEqual(result, "CATEGORY_2")

    # E. Explicit category wins over any domain keyword in the same text
    def test_e_category_1_hr_advisory_is_category_1_not_category_2(self):
        """'Category 1 - HR Advisory' -> CATEGORY_1 (not CATEGORY_2)."""
        result = _extract_operational_scope("Category 1 - HR Advisory")
        self.assertEqual(result, "CATEGORY_1")

    # F. Stream markers are parsed correctly
    def test_f_stream_3_learning_development_is_stream_3(self):
        """'Stream 3 - Learning & Development' -> STREAM_3."""
        result = _extract_operational_scope("Stream 3 - Learning & Development")
        self.assertEqual(result, "STREAM_3")

    # G. Bare 'd1' in filename must NOT produce CATEGORY_1
    def test_g_bare_d1_in_filename_is_not_category_1(self):
        """Filename 'RFP-2026-026-Appendix-d1-evaluation-criteria.xlsx' -> GENERAL_SCOPE."""
        result = _extract_operational_scope("evaluation criteria", "RFP-2026-026-Appendix-d1-evaluation-criteria.xlsx")
        self.assertNotEqual(result, "CATEGORY_1")

    def test_g2_bare_d2_in_filename_is_not_category_2(self):
        """Filename 'pkg-ref-d2-form.docx' -> GENERAL_SCOPE (not CATEGORY_2)."""
        result = _extract_operational_scope("rated criteria response form", "pkg-ref-d2-form.docx")
        self.assertNotEqual(result, "CATEGORY_2")

    def test_g3_bare_d3_in_filename_is_not_category_3(self):
        """Filename 'section-d3-pricing.xlsx' -> GENERAL_SCOPE (not CATEGORY_3)."""
        result = _extract_operational_scope("pricing schedule", "section-d3-pricing.xlsx")
        self.assertNotEqual(result, "CATEGORY_3")

    # Additional positive-path tests for other markers
    def test_lot_marker_is_recognized(self):
        """'Lot 2 - Software Development' -> LOT_2."""
        self.assertEqual(_extract_operational_scope("Lot 2 - Software Development"), "LOT_2")

    def test_work_package_marker_is_recognized(self):
        """'Work Package 3 requirements' -> WORK_PACKAGE_3."""
        self.assertEqual(_extract_operational_scope("Work Package 3 requirements"), "WORK_PACKAGE_3")

    def test_service_category_marker_is_recognized(self):
        """'Service Category 2 evaluation criteria' -> CATEGORY_2."""
        self.assertEqual(_extract_operational_scope("Service Category 2 evaluation criteria"), "CATEGORY_2")

    # End-to-end: deliverables across different services are scoped GENERAL and do NOT conflict
    def test_hr_advisory_deliverable_and_facilitation_deliverable_same_qty_no_conflict(self):
        """HR Advisory 10 sessions vs Facilitation 10 sessions -> NO CONFLICT (both GENERAL_SCOPE, same qty)."""
        normalized = {
            "deliverables": [
                {"title": "HR Advisory Sessions", "description": "HR Advisory sessions: 10 sessions", "source_doc": "SOW.pdf"},
                {"title": "Facilitation Sessions", "description": "Facilitation sessions: 10 sessions", "source_doc": "SOW.pdf"}
            ]
        }
        pkg_files = ["SOW.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        scope_conflicts = [c for c in conflicts if c.get("conflict_type") == "SCOPE_CONFLICT"]
        self.assertEqual(len(scope_conflicts), 0)

    def test_hr_advisory_deliverable_and_facilitation_deliverable_diff_qty_no_false_conflict(self):
        """HR Advisory 10 sessions vs Facilitation 5 sessions -> NO CONFLICT (different deliverable types)."""
        normalized = {
            "deliverables": [
                {"title": "HR Advisory Sessions", "description": "HR Advisory sessions: 10 sessions per year", "source_doc": "SOW.pdf"},
                {"title": "Facilitation Sessions", "description": "Facilitation sessions: 5 sessions per engagement", "source_doc": "SOW.pdf"}
            ]
        }
        pkg_files = ["SOW.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        scope_conflicts = [c for c in conflicts if c.get("conflict_type") == "SCOPE_CONFLICT"]
        self.assertEqual(len(scope_conflicts), 0)


class TestStageCDateNullSafety(unittest.TestCase):
    """
    Tests ensuring Stage C date reconciliation safely handles null, missing,
    blank, and whitespace date values without raising AttributeError.
    """

    # A. date=None does not crash
    def test_null_date_does_not_crash_no_conflict(self):
        normalized = {
            "dates": [
                {
                    "milestone": "Submission Deadline",
                    "date": None,
                    "source_doc": "Main.pdf"
                }
            ]
        }
        pkg_files = ["Main.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        date_conflicts = [c for c in conflicts if c.get("conflict_type") == "DATE_CONFLICT"]
        self.assertEqual(len(date_conflicts), 0)

    # B. missing "date" does not crash
    def test_missing_date_key_does_not_crash_no_conflict(self):
        normalized = {
            "dates": [
                {
                    "milestone": "Submission Deadline",
                    "source_doc": "Main.pdf"
                }
            ]
        }
        pkg_files = ["Main.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        date_conflicts = [c for c in conflicts if c.get("conflict_type") == "DATE_CONFLICT"]
        self.assertEqual(len(date_conflicts), 0)

    # C. blank date "" does not crash
    def test_blank_date_does_not_crash_no_conflict(self):
        normalized = {
            "dates": [
                {
                    "milestone": "Submission Deadline",
                    "date": "",
                    "source_doc": "Main.pdf"
                }
            ]
        }
        pkg_files = ["Main.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        date_conflicts = [c for c in conflicts if c.get("conflict_type") == "DATE_CONFLICT"]
        self.assertEqual(len(date_conflicts), 0)

    # D. whitespace date "   " does not crash
    def test_whitespace_date_does_not_crash_no_conflict(self):
        normalized = {
            "dates": [
                {
                    "milestone": "Submission Deadline",
                    "date": "   \t\n  ",
                    "source_doc": "Main.pdf"
                }
            ]
        }
        pkg_files = ["Main.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        date_conflicts = [c for c in conflicts if c.get("conflict_type") == "DATE_CONFLICT"]
        self.assertEqual(len(date_conflicts), 0)

    # E. null record alongside valid date -> no conflict caused by null, valid date usable
    def test_null_date_alongside_valid_date_no_false_conflict(self):
        normalized = {
            "dates": [
                {
                    "milestone": "Submission Deadline",
                    "date": None,
                    "source_doc": "Main.pdf"
                },
                {
                    "milestone": "Submission Deadline",
                    "date": "2026-10-01",
                    "source_doc": "Addendum.pdf"
                }
            ]
        }
        pkg_files = ["Main.pdf", "Addendum.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        date_conflicts = [c for c in conflicts if c.get("conflict_type") == "DATE_CONFLICT"]
        self.assertEqual(len(date_conflicts), 0)

    # F. two valid identical dates -> no conflict
    def test_two_valid_identical_dates_no_conflict(self):
        normalized = {
            "dates": [
                {
                    "milestone": "Submission Deadline",
                    "date": "2026-10-01",
                    "source_doc": "Main.pdf"
                },
                {
                    "milestone": "Submission Deadline",
                    "date": "2026-10-01",
                    "source_doc": "Addendum.pdf"
                }
            ]
        }
        pkg_files = ["Main.pdf", "Addendum.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        date_conflicts = [c for c in conflicts if c.get("conflict_type") == "DATE_CONFLICT"]
        self.assertEqual(len(date_conflicts), 0)

    # G. two valid differing dates across physical documents -> TRUE_CONFLICT
    def test_two_valid_differing_dates_across_physical_docs_conflict(self):
        normalized = {
            "dates": [
                {
                    "milestone": "Submission Deadline",
                    "date": "2026-10-01",
                    "source_doc": "Main.pdf"
                },
                {
                    "milestone": "Submission Deadline",
                    "date": "2026-10-15",
                    "source_doc": "Addendum.pdf"
                }
            ]
        }
        pkg_files = ["Main.pdf", "Addendum.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        date_conflicts = [c for c in conflicts if c.get("conflict_type") == "DATE_CONFLICT"]
        self.assertEqual(len(date_conflicts), 1)
        self.assertEqual(date_conflicts[0]["classification"], "TRUE_CONFLICT")
        self.assertEqual(date_conflicts[0]["source_validity"], "PHYSICAL_BOTH")

    # H. internal valid differing dates -> REVIEW_ITEM
    def test_internal_valid_differing_dates_review_item(self):
        normalized = {
            "dates": [
                {
                    "milestone": "Submission Deadline",
                    "date": "2026-10-01",
                    "source_doc": "Main.pdf"
                },
                {
                    "milestone": "Submission Deadline",
                    "date": "2026-10-15",
                    "source_doc": "Main.pdf"
                }
            ]
        }
        pkg_files = ["Main.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        date_conflicts = [c for c in conflicts if c.get("conflict_type") == "DATE_CONFLICT"]
        self.assertEqual(len(date_conflicts), 1)
        self.assertEqual(date_conflicts[0]["classification"], "REVIEW_ITEM")


if __name__ == "__main__":
    unittest.main()
