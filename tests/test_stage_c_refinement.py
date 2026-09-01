"""
Stage C Cross-Document Reconciliation Refinement Test Suite.
Verifies:
1. Bank of Canada Regression Cases (False positive date and submission dimension suppression; removal of tender-specific heuristics).
2. Mandatory Requirement Scope Normalization (Category/stream scoped years of experience & security clearance).
3. Top Secret Priority & Security Clearance Contradictions (TOP_SECRET -> SECRET -> RELIABILITY).
4. Insurance Monetary Amount Normalization & Year Safety (Safe parsing; $2M vs $2,000,000 = NO CONFLICT; year 2026 ignored).
5. Multi-Source Opposing Pair Selection (3+ records with duplicates: source_a.text != source_b.text).
6. Positive True Conflict Cases (Contradictory dates, submission channels, envelope separation, insurance, page limits).
7. Same-Document Same-Milestone Date Inconsistencies (Classified as REVIEW_ITEM).
8. Source Validity & Provenance Grounding (Physical vs Synthesized vs Partial).
9. Frozen Bank of Canada Reconciliation Replay.
"""
import os
import json
import unittest

from extractor import (
    classify_date_milestone,
    classify_submission_rule_dimension,
    classify_insurance_class,
    classify_security_clearance,
    extract_monetary_amount,
    select_opposing_pair,
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


class TestStageCMandatoryScopeNormalization(unittest.TestCase):
    """Scenario 2: Mandatory requirement scope and category normalization."""

    def test_different_categories_different_years_experience_no_conflict(self):
        """Category 1 requires 5 years experience vs Category 2 requires 10 years experience -> NO CONFLICT."""
        normalized = {
            "requirements": [
                {
                    "req_id": "M1",
                    "category": "Mandatory",
                    "description": "Category 1: Minimum 5 years of organizational advisory experience required.",
                    "source_refs": [{"source_doc": "Appendix_B1.xlsx"}]
                },
                {
                    "req_id": "M2",
                    "category": "Mandatory",
                    "description": "Category 2: Minimum 10 years of executive coaching experience required.",
                    "source_refs": [{"source_doc": "Appendix_B2.xlsx"}]
                }
            ]
        }
        pkg_files = ["Appendix_B1.xlsx", "Appendix_B2.xlsx"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        mand_conflicts = [c for c in conflicts if c.get("conflict_type") == "MANDATORY_REQUIREMENT_CONFLICT"]
        self.assertEqual(len(mand_conflicts), 0)

    def test_same_category_different_years_experience_is_true_conflict(self):
        """Category 1 requires 5 years experience vs Category 1 addendum requires 10 years experience -> TRUE CONFLICT."""
        normalized = {
            "requirements": [
                {
                    "req_id": "M1",
                    "category": "Mandatory",
                    "description": "Category 1: Minimum 5 years of organizational advisory experience required.",
                    "source_refs": [{"source_doc": "Appendix_B1.xlsx"}]
                },
                {
                    "req_id": "M1",
                    "category": "Mandatory",
                    "description": "Category 1: Minimum 10 years of organizational advisory experience required.",
                    "source_refs": [{"source_doc": "Addendum_1.docx"}]
                }
            ]
        }
        pkg_files = ["Appendix_B1.xlsx", "Addendum_1.docx"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        mand_conflicts = [c for c in conflicts if c.get("conflict_type") == "MANDATORY_REQUIREMENT_CONFLICT" and c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(mand_conflicts), 1)
        self.assertEqual(mand_conflicts[0]["source_validity"], "PHYSICAL_BOTH")


class TestStageCSecurityClearancePriority(unittest.TestCase):
    """Scenario 3: Security clearance classifier priority and contradiction checking."""

    def test_top_secret_classified_first(self):
        """Top Secret security clearance required -> TOP_SECRET."""
        self.assertEqual(classify_security_clearance("Top Secret security clearance required"), "TOP_SECRET")
        self.assertEqual(classify_security_clearance("Valid Secret clearance required"), "SECRET")
        self.assertEqual(classify_security_clearance("Reliability status screening required"), "RELIABILITY")

    def test_top_secret_vs_secret_for_same_scope_is_true_conflict(self):
        """Top Secret vs Secret for same scope across documents -> TRUE CONFLICT."""
        normalized = {
            "requirements": [
                {
                    "req_id": "M1",
                    "category": "Mandatory",
                    "description": "Category 1: Resources must hold valid Secret security clearance.",
                    "source_refs": [{"source_doc": "Main_RFP.pdf"}]
                },
                {
                    "req_id": "M1",
                    "category": "Mandatory",
                    "description": "Category 1: Resources must hold valid Top Secret security clearance.",
                    "source_refs": [{"source_doc": "Addendum_2.pdf"}]
                }
            ]
        }
        pkg_files = ["Main_RFP.pdf", "Addendum_2.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        mand_conflicts = [c for c in conflicts if c.get("conflict_type") == "MANDATORY_REQUIREMENT_CONFLICT" and c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(mand_conflicts), 1)
        self.assertEqual(mand_conflicts[0]["source_validity"], "PHYSICAL_BOTH")

    def test_top_secret_for_cat1_vs_secret_for_cat2_no_conflict(self):
        """Top Secret for Category 1 vs Secret for Category 2 -> NO CONFLICT."""
        normalized = {
            "requirements": [
                {
                    "req_id": "M1",
                    "category": "Mandatory",
                    "description": "Category 1: Resources must hold valid Top Secret security clearance.",
                    "source_refs": [{"source_doc": "Appendix_B1.docx"}]
                },
                {
                    "req_id": "M2",
                    "category": "Mandatory",
                    "description": "Category 2: Resources must hold valid Secret security clearance.",
                    "source_refs": [{"source_doc": "Appendix_B2.docx"}]
                }
            ]
        }
        pkg_files = ["Appendix_B1.docx", "Appendix_B2.docx"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        mand_conflicts = [c for c in conflicts if c.get("conflict_type") == "MANDATORY_REQUIREMENT_CONFLICT"]
        self.assertEqual(len(mand_conflicts), 0)


class TestStageCInsuranceAmountNormalization(unittest.TestCase):
    """Scenario 4: Monetary amount parsing, year protection, and like-with-like insurance reconciliation."""

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


class TestStageCMultiSourceOpposingPairSelection(unittest.TestCase):
    """Scenario 5: Multi-source record sets (3+ records) with duplicate values ensuring opposing source pairing."""

    def test_multi_source_date_conflict_pairs_differing_values(self):
        """A.pdf -> Sep 15, B.pdf -> Sep 30, C.pdf -> Sep 15: source_a.text != source_b.text (Sep 15 vs Sep 30)."""
        normalized = {
            "dates": [
                {"milestone": "Bid Closing Date", "date": "2026-09-15", "source_doc": "A.pdf"},
                {"milestone": "Bid Closing Date", "date": "2026-09-30", "source_doc": "B.pdf"},
                {"milestone": "Bid Closing Date", "date": "2026-09-15", "source_doc": "C.pdf"}
            ]
        }
        pkg_files = ["A.pdf", "B.pdf", "C.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        date_conflicts = [c for c in conflicts if c.get("conflict_type") == "DATE_CONFLICT" and c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(date_conflicts), 1)
        self.assertNotEqual(date_conflicts[0]["source_a"]["text"], date_conflicts[0]["source_b"]["text"])
        pair_dates = {date_conflicts[0]["source_a"]["text"], date_conflicts[0]["source_b"]["text"]}
        self.assertEqual(pair_dates, {"2026-09-15", "2026-09-30"})

    def test_multi_source_experience_threshold_pairs_differing_values(self):
        """Category 1: A.pdf -> 5 years, B.pdf -> 10 years, C.pdf -> 5 years: displayed sources 5 vs 10, not 5 vs 5."""
        normalized = {
            "requirements": [
                {"req_id": "M1", "category": "Mandatory", "description": "Category 1: Minimum 5 years of advisory experience required.", "source_refs": [{"source_doc": "A.pdf"}]},
                {"req_id": "M1", "category": "Mandatory", "description": "Category 1: Minimum 10 years of advisory experience required.", "source_refs": [{"source_doc": "B.pdf"}]},
                {"req_id": "M1", "category": "Mandatory", "description": "Category 1: Minimum 5 years of advisory experience required.", "source_refs": [{"source_doc": "C.pdf"}]}
            ]
        }
        pkg_files = ["A.pdf", "B.pdf", "C.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        mand_conflicts = [c for c in conflicts if c.get("conflict_type") == "MANDATORY_REQUIREMENT_CONFLICT" and c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(mand_conflicts), 1)
        self.assertNotEqual(mand_conflicts[0]["source_a"]["text"], mand_conflicts[0]["source_b"]["text"])
        self.assertIn("5", mand_conflicts[0]["source_a"]["text"])
        self.assertIn("10", mand_conflicts[0]["source_b"]["text"])

    def test_multi_source_insurance_pairs_differing_limits(self):
        """CGL: A.pdf -> $2M, B.pdf -> $5M, C.pdf -> $2M with extra wording: displayed pair normalizes to 2M vs 5M."""
        normalized = {
            "commercial_clauses": [
                {"topic": "Commercial General Liability Insurance", "details": "CGL coverage of $2,000,000", "source_doc": "A.pdf"},
                {"topic": "Commercial General Liability Insurance", "details": "CGL coverage of $5,000,000", "source_doc": "B.pdf"},
                {"topic": "Commercial General Liability Insurance", "details": "CGL insurance minimum $2M including bodily injury", "source_doc": "C.pdf"}
            ]
        }
        pkg_files = ["A.pdf", "B.pdf", "C.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        ins_conflicts = [c for c in conflicts if c.get("conflict_type") == "COMMERCIAL_TERM_CONFLICT" and c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(ins_conflicts), 1)
        amt_a = extract_monetary_amount(ins_conflicts[0]["source_a"]["text"])
        amt_b = extract_monetary_amount(ins_conflicts[0]["source_b"]["text"])
        self.assertNotEqual(amt_a, amt_b)
        self.assertEqual({amt_a, amt_b}, {2000000.0, 5000000.0})

    def test_multi_source_page_limits_pairs_differing_limits(self):
        """A.pdf -> 10 pages, B.pdf -> 15 pages, C.pdf -> 10 pages: displayed pair is 10 vs 15."""
        normalized = {
            "submission_rules": [
                {"item": "Proposal Format", "format": "PDF", "details": "Technical proposal must not exceed 10 pages", "source_doc": "A.pdf"},
                {"item": "Proposal Format", "format": "PDF", "details": "Technical proposal must not exceed 15 pages", "source_doc": "B.pdf"},
                {"item": "Proposal Format", "format": "PDF", "details": "Technical proposal must not exceed 10 pages", "source_doc": "C.pdf"}
            ]
        }
        pkg_files = ["A.pdf", "B.pdf", "C.pdf"]
        conflicts = detect_document_conflicts(normalized, pkg_files)
        page_conflicts = [c for c in conflicts if c.get("conflict_type") == "SUBMISSION_RULE_CONFLICT" and c.get("classification") == "TRUE_CONFLICT"]
        self.assertEqual(len(page_conflicts), 1)
        self.assertNotEqual(page_conflicts[0]["source_a"]["text"], page_conflicts[0]["source_b"]["text"])
        self.assertEqual({page_conflicts[0]["source_a"]["text"], page_conflicts[0]["source_b"]["text"]}, {"10 pages", "15 pages"})


class TestStageCSameDocumentSameMilestoneDates(unittest.TestCase):
    """Scenario 6: Same physical document containing differing dates for the same semantic milestone."""

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
    """Scenario 7: Positive tests ensuring legitimate contradictions are captured as TRUE_CONFLICT."""

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
    """Scenario 8: Source validity classifications and synthetic reference downgrades."""

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
    """Scenario 9: Replay refined Stage C reconciliation against frozen Bank of Canada normalized facts."""

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
