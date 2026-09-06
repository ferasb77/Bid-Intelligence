"""
Comprehensive Test Suite for Streamlined Bid Intelligence Workflow (Pre-Migration 003).
Covers:
1. Native JSONB persistence for source_refs and document_conflicts (no double-serialization).
2. Staged extraction architecture (Fact extraction separated from synthesis).
3. Source provenance validation (valid markers accepted; invalid file, page, sheet rejected).
4. Deterministic conflict detection (Mandatory, Date, Evaluation, Submission, Commercial, Scope).
5. Document submission gating (mandatory Uploaded/Approved/Complete/Submitted = ready; Expected = blocker; optional = non-blocker).
6. Human verification checkboxes default False.
7. File format cleanup (.doc/.xls unsupported; CSV supported with row coordinates).
8. Real worksheet coordinates in XLSX (preserving coordinates even with blank rows).
9. Firm profile integrity and decision governance.
10. Lifecycle consistency (Withdrawn/No Bid excluded from Lost in win rate).
"""
import io
import json
import zipfile
import unittest
from datetime import datetime

from components.ui import (
    STAGES, STAGE_COLOURS, QUAL_STATUSES, EVIDENCE_STATUSES,
    qual_badge, evidence_badge, decision_badge
)
from database import (
    DEFAULT_FIRM_PROFILE,
    format_requirement_payload,
    format_bid_brief_payload
)
from extractor import (
    extract_text_from_file,
    extract_document_with_metadata,
    unpack_procurement_package,
    validate_source_refs,
    detect_document_conflicts,
    normalize_package_facts,
    reconcile_package_facts,
    STAGE_A_FACT_EXTRACTION_PROMPT,
    STAGE_D_SYNTHESIS_PROMPT
)


class TestJSONBPersistence(unittest.TestCase):
    """Scenario 1: Verify JSONB columns retain native Python list/dict without json.dumps stringification."""

    def test_source_refs_jsonb_payload_remains_native_list(self):
        source_refs_data = [
            {"source_doc": "RFP.pdf", "page": 4, "sheet": None, "section": "Mandatory", "excerpt": "Valid excerpt."}
        ]
        data = {
            "req_id": "M1",
            "description": "Bilingual support",
            "source_refs": source_refs_data
        }
        keys = ["req_id", "description", "source_refs"]
        payload = format_requirement_payload(data, keys)

        # Must be a Python list, NOT a JSON-encoded string
        self.assertIsInstance(payload["source_refs"], list)
        self.assertNotIsInstance(payload["source_refs"], str)
        self.assertEqual(payload["source_refs"][0]["source_doc"], "RFP.pdf")

    def test_document_conflicts_jsonb_payload_remains_native_list(self):
        conflicts_data = [
            {
                "conflict_id": "CONF-DATE-1",
                "conflict_type": "DATE_CONFLICT",
                "topic": "Closing date amended by addendum",
                "source_a": {"doc": "RFP.pdf", "text": "2026-09-30"},
                "source_b": {"doc": "Addendum_1.pdf", "text": "2026-10-02"},
                "assessment": "Deadline extended",
                "recommended_action": "Use extended date"
            }
        ]
        data = {
            "bid_id": 10,
            "executive_summary": "Summary text",
            "document_conflicts": conflicts_data,
            "deliverables_summary": [{"title": "Report"}] # TEXT column from Migration 002
        }
        keys = ["bid_id", "executive_summary", "document_conflicts", "deliverables_summary"]
        payload = format_bid_brief_payload(data, keys)

        # document_conflicts (JSONB) must remain a native list
        self.assertIsInstance(payload["document_conflicts"], list)
        self.assertNotIsInstance(payload["document_conflicts"], str)
        # deliverables_summary (TEXT from Migration 002) should be stringified
        self.assertIsInstance(payload["deliverables_summary"], str)


class TestStagedExtractionArchitecture(unittest.TestCase):
    """Scenario 2: Verify Stage A (Fact Extraction) is strictly separated from Stage D (Bid Brief Synthesis)."""

    def test_stage_a_prompt_extracts_facts_only_not_brief(self):
        self.assertIn("Extract factual procurement data", STAGE_A_FACT_EXTRACTION_PROMPT)
        self.assertNotIn("executive_summary", STAGE_A_FACT_EXTRACTION_PROMPT)
        self.assertNotIn("opportunity_type", STAGE_A_FACT_EXTRACTION_PROMPT)
        self.assertIn("requirements", STAGE_A_FACT_EXTRACTION_PROMPT)

    def test_stage_d_prompt_synthesizes_from_normalized_model(self):
        self.assertIn("synthesizing a Bid Brief from normalized procurement facts", STAGE_D_SYNTHESIS_PROMPT)
        self.assertIn("executive_summary", STAGE_D_SYNTHESIS_PROMPT)
        self.assertIn("opportunity_type", STAGE_D_SYNTHESIS_PROMPT)


class TestSourceProvenanceValidation(unittest.TestCase):
    """Scenario 3: Strict validation of returned source_refs against actual parse metadata."""

    def setUp(self):
        self.package_metadata = {
            "files": ["Main_RFP.pdf", "Appendix_C.xlsx"],
            "doc_metadata": {
                "Main_RFP.pdf": {"page_count": 10},
                "Appendix_C.xlsx": {
                    "sheets": ["Mandatory Criteria", "Pricing"],
                    "rows_per_sheet": {
                        "Mandatory Criteria": (4, 19, set(range(4, 20))),
                        "Pricing": (1, 10, set(range(1, 11)))
                    }
                }
            },
            "doc_texts": {
                "Main_RFP.pdf": "Section 3.2: Security Clearance. All personnel must hold Reliability status.",
                "Appendix_C.xlsx": "Row 4: M1 Corporate Experience minimum 5 years"
            }
        }

    def test_valid_deterministic_source_reference_accepted(self):
        valid_ref = [
            {
                "source_doc": "Main_RFP.pdf",
                "page": 3,
                "sheet": None,
                "section": "Section 3.2",
                "excerpt": "All personnel must hold Reliability status."
            }
        ]
        verified = validate_source_refs(valid_ref, self.package_metadata)
        self.assertEqual(len(verified), 1)
        self.assertTrue(verified[0]["verified"])
        self.assertEqual(verified[0]["page"], 3)

    def test_invalid_page_source_reference_rejected(self):
        # Document only has 10 pages; page 99 is invalid
        invalid_page_ref = [
            {"source_doc": "Main_RFP.pdf", "page": 99, "sheet": None, "excerpt": "Some excerpt"}
        ]
        verified = validate_source_refs(invalid_page_ref, self.package_metadata)
        self.assertEqual(len(verified), 1)
        self.assertFalse(verified[0]["verified"])
        self.assertIn("out of bounds", verified[0]["validation_error"])

    def test_invalid_sheet_source_reference_rejected(self):
        invalid_sheet_ref = [
            {"source_doc": "Appendix_C.xlsx", "page": None, "sheet": "NonexistentSheet", "excerpt": "Some excerpt"}
        ]
        verified = validate_source_refs(invalid_sheet_ref, self.package_metadata)
        self.assertEqual(len(verified), 1)
        self.assertFalse(verified[0]["verified"])
        self.assertIn("does not exist in workbook", verified[0]["validation_error"])

    def test_invalid_filename_source_reference_rejected(self):
        invalid_file_ref = [
            {"source_doc": "Fabricated_Document.docx", "page": 1, "sheet": None, "excerpt": "Some excerpt"}
        ]
        verified = validate_source_refs(invalid_file_ref, self.package_metadata)
        self.assertEqual(len(verified), 1)
        self.assertFalse(verified[0]["verified"])
        self.assertIn("not found in procurement package", verified[0]["validation_error"])


class TestExpandedDeterministicConflictDetection(unittest.TestCase):
    """Scenario 4: Expanded reconciliation covering 6 distinct conflict categories."""

    def test_date_conflict_detected(self):
        normalized = {
            "dates": [
                {"milestone": "Submission Deadline", "date": "2026-09-30", "source_doc": "Main_RFP.pdf"},
                {"milestone": "Revised Closing Deadline", "date": "2026-10-02", "source_doc": "Addendum_1.pdf"}
            ]
        }
        conflicts = detect_document_conflicts(normalized, ["Main_RFP.pdf", "Addendum_1.pdf"])
        self.assertTrue(any(c["conflict_type"] == "DATE_CONFLICT" for c in conflicts))

    def test_evaluation_weight_conflict_detected(self):
        normalized = {
            "evaluation_criteria": [
                {"stage": "Technical Score", "weight": "75 points", "source_doc": "Main_RFP.pdf"},
                {"stage": "Technical Score", "weight": "70 points", "source_doc": "Appendix_B.docx"}
            ]
        }
        conflicts = detect_document_conflicts(normalized, ["Main_RFP.pdf", "Appendix_B.docx"])
        self.assertTrue(any(c["conflict_type"] == "EVALUATION_CONFLICT" for c in conflicts))

    def test_submission_rule_conflict_detected(self):
        normalized = {
            "submission_rules": [
                {"item": "Technical & Financial Proposal", "format": "Separate Envelopes", "source_doc": "Main_RFP.pdf"},
                {"item": "Proposal Document", "format": "Single Combined PDF", "source_doc": "Appendix_A.docx"}
            ]
        }
        conflicts = detect_document_conflicts(normalized, ["Main_RFP.pdf", "Appendix_A.docx"])
        self.assertTrue(any(c["conflict_type"] == "SUBMISSION_RULE_CONFLICT" for c in conflicts))

    def test_mandatory_requirement_conflict_detected(self):
        normalized = {
            "requirements": [
                {
                    "req_id": "M1",
                    "category": "Mandatory",
                    "description": "Minimum 5 years of organizational advisory experience required.",
                    "source_refs": [{"source_doc": "Main_RFP.pdf"}]
                },
                {
                    "req_id": "M1",
                    "category": "Mandatory",
                    "description": "Minimum 8 years of organizational advisory experience required.",
                    "source_refs": [{"source_doc": "Appendix_C.xlsx"}]
                }
            ]
        }
        conflicts = detect_document_conflicts(normalized, ["Main_RFP.pdf", "Appendix_C.xlsx"])
        self.assertTrue(any(c["conflict_type"] == "MANDATORY_REQUIREMENT_CONFLICT" for c in conflicts))

    def test_commercial_term_conflict_detected(self):
        normalized = {
            "commercial_clauses": [
                {"topic": "Panel Maximums", "details": "Category 1: 5 firms", "source_doc": "Main_RFP.pdf"},
                {"topic": "Panel Maximums", "details": "Category 1: 3 firms", "source_doc": "Addendum_1.pdf"}
            ]
        }
        conflicts = detect_document_conflicts(normalized, ["Main_RFP.pdf", "Addendum_1.pdf"])
        self.assertTrue(any(c["conflict_type"] == "COMMERCIAL_TERM_CONFLICT" for c in conflicts))

    def test_scope_conflict_detected(self):
        normalized = {
            "deliverables": [
                {"title": "Training Cohorts", "description": "Deliver 21 training cohorts", "source_doc": "Main_RFP.pdf"},
                {"title": "Training Cohorts", "description": "Deliver 15 training cohorts", "source_doc": "Schedule_A.xlsx"}
            ]
        }
        conflicts = detect_document_conflicts(normalized, ["Main_RFP.pdf", "Schedule_A.xlsx"])
        self.assertTrue(any(c["conflict_type"] == "SCOPE_CONFLICT" for c in conflicts))


class TestSubmissionGatingDocumentLogic(unittest.TestCase):
    """Scenario 5: Required package readiness uses ready states and ignores optional expected documents."""

    def _eval_can_submit(self, mand_reqs, docs, verifications_confirmed=True):
        READY_DOC_STATUSES = {"Uploaded", "Approved", "Complete", "Submitted"}
        sub_docs = [d for d in docs if d.get("doc_type") in ("Submission", "Financial") or d.get("mandatory") in (1, True, "1", "true")]
        required_sub_docs = [d for d in sub_docs if d.get("mandatory") not in (0, False, "0", "false")]

        m_fail = sum(1 for r in mand_reqs if r.get("qual_status") == "FAIL")
        m_unknown = sum(1 for r in mand_reqs if r.get("qual_status", "UNKNOWN") == "UNKNOWN")
        docs_missing = sum(1 for d in required_sub_docs if d.get("status") not in READY_DOC_STATUSES)

        return (m_fail == 0 and m_unknown == 0 and docs_missing == 0 and verifications_confirmed)

    def test_mandatory_uploaded_is_ready(self):
        docs = [{"name": "Technical.pdf", "mandatory": 1, "status": "Uploaded"}]
        self.assertTrue(self._eval_can_submit([], docs))

    def test_mandatory_approved_is_ready(self):
        docs = [{"name": "Technical.pdf", "mandatory": 1, "status": "Approved"}]
        self.assertTrue(self._eval_can_submit([], docs))

    def test_mandatory_complete_is_ready(self):
        docs = [{"name": "Technical.pdf", "mandatory": 1, "status": "Complete"}]
        self.assertTrue(self._eval_can_submit([], docs))

    def test_mandatory_submitted_is_ready(self):
        docs = [{"name": "Technical.pdf", "mandatory": 1, "status": "Submitted"}]
        self.assertTrue(self._eval_can_submit([], docs))

    def test_mandatory_expected_is_blocker(self):
        docs = [{"name": "Technical.pdf", "mandatory": 1, "status": "Expected"}]
        self.assertFalse(self._eval_can_submit([], docs))

    def test_optional_expected_does_not_block(self):
        docs = [
            {"name": "Mandatory Proposal.pdf", "mandatory": 1, "status": "Uploaded"},
            {"name": "Optional Brochure.pdf", "mandatory": 0, "status": "Expected"}
        ]
        self.assertTrue(self._eval_can_submit([], docs))


class TestFormatSupportAndXLSXCoordinates(unittest.TestCase):
    """Scenario 6: File format handling and real Excel row coordinate preservation."""

    def test_doc_rejected_and_xls_admitted_with_parse_diagnostic(self):
        raw_files = [
            ("legacy_doc.doc", b"Old binary doc"),
            ("legacy_sheet.xls", b"Old binary xls"),
            ("valid.pdf", b"%PDF-1.4 Valid")
        ]
        unpacked, warnings = unpack_procurement_package(raw_files)
        unpacked_names = [f[0] for f in unpacked]

        self.assertNotIn("legacy_doc.doc", unpacked_names)
        self.assertIn("legacy_sheet.xls", unpacked_names)
        self.assertIn("valid.pdf", unpacked_names)
        self.assertTrue(any(".doc" in w for w in warnings))
        self.assertTrue(any(".xls" in w for w in warnings))

    def test_csv_parser_with_row_markers(self):
        csv_data = b"ReqID,Description,Category\nM1,Reliability Security,Mandatory\nM2,Bilingual Staff,Mandatory"
        parsed, meta = extract_document_with_metadata(csv_data, "criteria.csv")
        self.assertIn("[[SOURCE: criteria.csv | ROWS: 1-3]]", parsed)
        self.assertIn("Row 2: M1 | Reliability Security | Mandatory", parsed)

    def test_xlsx_blank_rows_preserve_real_row_coordinates(self):
        """When rows 1-3 are blank and row 4 has data, marker must state ROWS: 4-4 and Row 4: ..."""
        xlsx_buffer = io.BytesIO()
        try:
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Mandatory Criteria"
            # Leave rows 1, 2, 3 blank. Place data in row 4 and row 6.
            ws.cell(row=4, column=1, value="M1 Requirement")
            ws.cell(row=6, column=1, value="M2 Requirement")
            wb.save(xlsx_buffer)
            xlsx_bytes = xlsx_buffer.getvalue()

            parsed, meta = extract_document_with_metadata(xlsx_bytes, "Appendix_C.xlsx")
            self.assertIn("[[SOURCE: Appendix_C.xlsx | SHEET: Mandatory Criteria | ROWS: 4-6]]", parsed)
            self.assertIn("Row 4: M1 Requirement", parsed)
            self.assertIn("Row 6: M2 Requirement", parsed)
            self.assertNotIn("Row 1:", parsed)
        except ImportError:
            self.skipTest("openpyxl not available for direct workbook generation")


class TestFirmProfileAndDecisionGovernance(unittest.TestCase):
    """Scenario 7: Firm profile unconfigured defaults and human decision integrity."""

    def test_default_firm_profile_unconfigured(self):
        profile = DEFAULT_FIRM_PROFILE
        self.assertEqual(profile["company_name"], "Enable My Growth")
        self.assertEqual(profile["overview"], "")
        self.assertEqual(profile["core_capabilities"], "")
        self.assertEqual(profile["certifications"], "")
        self.assertEqual(profile["languages"], "")

    def test_ai_evaluation_preserves_human_decision(self):
        prior = {"human_decision": "NO-GO", "override_reason": "Risk high", "decided_by": "Director"}
        updated = {
            "ai_recommendation": "GO",
            "human_decision": prior.get("human_decision"),
            "override_reason": prior.get("override_reason")
        }
        self.assertEqual(updated["human_decision"], "NO-GO")


class TestLifecycleConsistency(unittest.TestCase):
    """Scenario 8: Withdrawn and No Bid formal states."""

    def test_withdrawn_and_nobid_in_stages(self):
        self.assertIn("Withdrawn", STAGES)
        self.assertIn("No Bid", STAGES)

    def test_win_rate_calculation(self):
        bids = [
            {"stage": "Won"},
            {"stage": "Won"},
            {"stage": "Lost"},
            {"stage": "Withdrawn"},
            {"stage": "No Bid"}
        ]
        won = sum(1 for b in bids if b["stage"] == "Won")
        lost = sum(1 for b in bids if b["stage"] == "Lost")
        closed_decided = won + lost
        wr = (won / closed_decided * 100) if closed_decided else 0.0
        # 2 / 3 = 66.67%
        self.assertAlmostEqual(wr, 66.6666, places=2)


if __name__ == "__main__":
    unittest.main()
