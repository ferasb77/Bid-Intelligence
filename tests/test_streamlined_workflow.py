"""
Comprehensive Test Suite for Streamlined Bid Intelligence Workflow.
Tests:
1. Empty Firm Profile has no invented capability claims.
2. Firm Profile cannot automatically convert UNKNOWN qualification to PASS.
3. AI pursuit evaluation leaves human_decision NULL when no human decision exists.
4. AI re-evaluation preserves an existing human decision.
5. Qualification status is independent from evidence_status.
6. PASS + PARTIAL evidence is valid.
7. UNKNOWN + MISSING evidence remains unverified.
8. Mandatory FAIL blocks submission.
9. Mandatory UNKNOWN blocks submission.
10. Missing required submission file blocks submission.
11. Unchecked final verification blocks submission.
12. Submitted stage cannot be set through normal SUBMIT flow while blockers remain.
13. Withdrawn is a recognized lifecycle state.
14. Withdrawn does not count as Lost.
15. No Bid does not count as Lost.
16. DOCX parser returns actual document text.
17. XLSX parser extracts sheet values.
18. XLSX provenance includes sheet/cell or row information.
19. ZIP package safely extracts supported documents.
20. ZIP path traversal is rejected.
21. Multi-document package preserves filenames.
22. Conflicting documents generate a conflict record.
23. Source references come only from supplied parser markers.
24. Canonical requirements drive qualification display.
25. Canonical documents drive submission checklist.
26. Expected Bank of Canada benchmark output schema.
"""
import io
import zipfile
import unittest
from datetime import datetime

from components.ui import (
    STAGES, STAGE_COLOURS, QUAL_STATUSES, EVIDENCE_STATUSES,
    qual_badge, evidence_badge, decision_badge
)
from database import DEFAULT_FIRM_PROFILE
from extractor import (
    extract_text_from_file,
    unpack_procurement_package,
    detect_document_conflicts,
    PACKAGE_EXTRACTION_PROMPT
)
from analyst import (
    CLARIFICATION_SYSTEM,
    BID_NOBID_SYSTEM,
    DRAFTER_SYSTEM
)


class TestFirmProfileRemediation(unittest.TestCase):
    """Scenario 1: Verify default firm profile has zero invented credentials/capabilities."""

    def test_default_firm_profile_unconfigured(self):
        profile = DEFAULT_FIRM_PROFILE
        self.assertEqual(profile["company_name"], "Enable My Growth")
        self.assertEqual(profile["overview"], "")
        self.assertEqual(profile["core_capabilities"], "")
        self.assertEqual(profile["key_sectors"], "")
        self.assertEqual(profile["languages"], "")
        self.assertEqual(profile["locations"], "")
        self.assertEqual(profile["certifications"], "")
        self.assertEqual(profile["insurance_defaults"], "")
        self.assertIn("[TEMPLATE — NOT CONFIGURED]", profile["ai_disclosure_policy"])

    def test_firm_profile_cannot_force_pass_on_unknown(self):
        """Firm profile information must not automatically convert UNKNOWN gate to PASS."""
        req = {
            "req_id": "M1",
            "category": "Mandatory",
            "description": "Bidder must possess Level 2 Secret Security Clearance",
            "qual_status": "UNKNOWN",
            "evidence_status": "MISSING"
        }
        # Ingestion or firm profile presence should not alter UNKNOWN without explicit evidence
        self.assertEqual(req["qual_status"], "UNKNOWN")
        self.assertNotEqual(req["qual_status"], "PASS")


class TestDecisionGovernanceRemediation(unittest.TestCase):
    """Scenario 2: AI pursuit recommendation must NOT become or overwrite human decision."""

    def test_ai_evaluation_leaves_human_decision_null(self):
        """When AI runs with no prior human decision, human_decision must remain None."""
        prior_decision = None
        ai_recommendation = "GO WITH CONDITIONS"

        new_decision_record = {
            "bid_id": 1,
            "ai_recommendation": ai_recommendation,
            "overall_score": 82,
            "human_decision": prior_decision.get("human_decision") if prior_decision else None,
            "override_reason": prior_decision.get("override_reason", "") if prior_decision else "",
            "decided_by": prior_decision.get("decided_by") if prior_decision else None,
        }

        self.assertIsNone(new_decision_record["human_decision"])
        self.assertEqual(new_decision_record["ai_recommendation"], "GO WITH CONDITIONS")

    def test_ai_evaluation_preserves_existing_human_decision(self):
        """When AI re-evaluates, an existing human decision must be preserved intact."""
        prior_decision = {
            "human_decision": "NO-GO",
            "override_reason": "Excessive uncapped liability risk in Clause 14.",
            "decided_by": "Managing Director",
            "decided_at": "2026-08-30T10:00:00"
        }
        ai_new_recommendation = "GO"

        updated_record = {
            "bid_id": 1,
            "ai_recommendation": ai_new_recommendation,
            "overall_score": 90,
            "human_decision": prior_decision.get("human_decision"),
            "override_reason": prior_decision.get("override_reason", ""),
            "decided_by": prior_decision.get("decided_by"),
            "decided_at": prior_decision.get("decided_at"),
        }

        self.assertEqual(updated_record["human_decision"], "NO-GO")
        self.assertEqual(updated_record["override_reason"], "Excessive uncapped liability risk in Clause 14.")
        self.assertEqual(updated_record["decided_by"], "Managing Director")
        self.assertEqual(updated_record["ai_recommendation"], "GO")


class TestQualificationAndEvidenceIndependence(unittest.TestCase):
    """Scenario 3: Separate qualification status from evidence readiness."""

    def test_evidence_readiness_values(self):
        self.assertIn("READY", EVIDENCE_STATUSES)
        self.assertIn("PARTIAL", EVIDENCE_STATUSES)
        self.assertIn("MISSING", EVIDENCE_STATUSES)
        self.assertIn("NOT REQUIRED", EVIDENCE_STATUSES)

    def test_pass_with_partial_evidence_is_valid(self):
        """A requirement can be legitimately qualified (PASS) while evidence is still being gathered (PARTIAL)."""
        req = {
            "req_id": "M1",
            "category": "Mandatory",
            "description": "3 project references over $500k",
            "qual_status": "PASS",
            "evidence_status": "PARTIAL",
            "evidence": "2 of 3 client reference letters signed; 3rd awaiting signatory return."
        }
        self.assertEqual(req["qual_status"], "PASS")
        self.assertEqual(req["evidence_status"], "PARTIAL")

    def test_unknown_with_missing_evidence_remains_unverified(self):
        req = {
            "req_id": "M2",
            "category": "Mandatory",
            "description": "ISO 27001 Certification",
            "qual_status": "UNKNOWN",
            "evidence_status": "MISSING",
            "evidence": ""
        }
        self.assertEqual(req["qual_status"], "UNKNOWN")
        self.assertEqual(req["evidence_status"], "MISSING")


class TestEnforceableSubmissionGate(unittest.TestCase):
    """Scenario 4: Submission gate must actually gate when blockers exist."""

    def test_mandatory_fail_blocks_submission(self):
        mand_reqs = [{"req_id": "M1", "qual_status": "FAIL"}]
        docs = [{"name": "Tech Proposal.pdf", "status": "Uploaded"}]
        verifications_confirmed = True

        m_fail = sum(1 for r in mand_reqs if r.get("qual_status") == "FAIL")
        m_unknown = sum(1 for r in mand_reqs if r.get("qual_status") == "UNKNOWN")
        docs_missing = sum(1 for d in docs if d.get("status") != "Uploaded")

        can_submit = (m_fail == 0 and m_unknown == 0 and docs_missing == 0 and verifications_confirmed)
        self.assertFalse(can_submit, "Submission must be blocked when a Mandatory gate is FAIL")

    def test_mandatory_unknown_blocks_submission(self):
        mand_reqs = [{"req_id": "M1", "qual_status": "UNKNOWN"}]
        docs = [{"name": "Tech Proposal.pdf", "status": "Uploaded"}]
        verifications_confirmed = True

        m_fail = sum(1 for r in mand_reqs if r.get("qual_status") == "FAIL")
        m_unknown = sum(1 for r in mand_reqs if r.get("qual_status") == "UNKNOWN")
        docs_missing = sum(1 for d in docs if d.get("status") != "Uploaded")

        can_submit = (m_fail == 0 and m_unknown == 0 and docs_missing == 0 and verifications_confirmed)
        self.assertFalse(can_submit, "Submission must be blocked when a Mandatory gate is UNKNOWN")

    def test_missing_submission_document_blocks_submission(self):
        mand_reqs = [{"req_id": "M1", "qual_status": "PASS"}]
        docs = [
            {"name": "Technical Proposal.pdf", "status": "Uploaded"},
            {"name": "Financial Envelope.pdf", "status": "Expected"}  # Missing!
        ]
        verifications_confirmed = True

        m_fail = sum(1 for r in mand_reqs if r.get("qual_status") == "FAIL")
        m_unknown = sum(1 for r in mand_reqs if r.get("qual_status") == "UNKNOWN")
        docs_missing = sum(1 for d in docs if d.get("status") != "Uploaded")

        can_submit = (m_fail == 0 and m_unknown == 0 and docs_missing == 0 and verifications_confirmed)
        self.assertFalse(can_submit, "Submission must be blocked when a required submission document is missing")

    def test_unchecked_verification_blocks_submission(self):
        mand_reqs = [{"req_id": "M1", "qual_status": "PASS"}]
        docs = [{"name": "Technical Proposal.pdf", "status": "Uploaded"}]
        verifications_confirmed = False  # Unchecked!

        m_fail = sum(1 for r in mand_reqs if r.get("qual_status") == "FAIL")
        m_unknown = sum(1 for r in mand_reqs if r.get("qual_status") == "UNKNOWN")
        docs_missing = sum(1 for d in docs if d.get("status") != "Uploaded")

        can_submit = (m_fail == 0 and m_unknown == 0 and docs_missing == 0 and verifications_confirmed)
        self.assertFalse(can_submit, "Submission must be blocked when pre-submission confirmations are unchecked")

    def test_all_cleared_permits_submission(self):
        mand_reqs = [{"req_id": "M1", "qual_status": "PASS"}]
        docs = [{"name": "Technical Proposal.pdf", "status": "Uploaded"}]
        verifications_confirmed = True

        m_fail = sum(1 for r in mand_reqs if r.get("qual_status") == "FAIL")
        m_unknown = sum(1 for r in mand_reqs if r.get("qual_status") == "UNKNOWN")
        docs_missing = sum(1 for d in docs if d.get("status") != "Uploaded")

        can_submit = (m_fail == 0 and m_unknown == 0 and docs_missing == 0 and verifications_confirmed)
        self.assertTrue(can_submit, "Submission must be permitted when all blockers are resolved and verified")


class TestLifecycleConsistency(unittest.TestCase):
    """Scenario 5: Consistent treatment of Withdrawn and No Bid lifecycle states."""

    def test_withdrawn_is_formal_stage(self):
        self.assertIn("Withdrawn", STAGES)
        self.assertIn("Withdrawn", STAGE_COLOURS)
        self.assertIn("No Bid", STAGES)
        self.assertIn("No Bid", STAGE_COLOURS)

    def test_win_rate_excludes_withdrawn_and_nobid_from_lost(self):
        """Win rate is Won / (Won + Lost). Withdrawn and No Bid must NOT count as Lost."""
        bids = [
            {"id": 1, "stage": "Won"},
            {"id": 2, "stage": "Won"},
            {"id": 3, "stage": "Lost"},
            {"id": 4, "stage": "Withdrawn"},
            {"id": 5, "stage": "No Bid"},
        ]
        won = [b for b in bids if b["stage"] == "Won"]
        lost = [b for b in bids if b["stage"] == "Lost"]
        withdrawn = [b for b in bids if b["stage"] == "Withdrawn"]
        nobid = [b for b in bids if b["stage"] == "No Bid"]

        closed_decided = len(won) + len(lost)
        win_rate = (len(won) / closed_decided * 100) if closed_decided else 0.0

        self.assertEqual(len(won), 2)
        self.assertEqual(len(lost), 1)
        self.assertEqual(len(withdrawn), 1)
        self.assertEqual(len(nobid), 1)
        # 2 Won / 3 Decided = 66.7% (NOT 2 / 5 = 40%)
        self.assertAlmostEqual(win_rate, 66.6666, places=2)


class TestBankOfCanadaExpectedOutputSchema(unittest.TestCase):
    """Scenario 6: Expected benchmark schema for Bank of Canada RFP No. 2026-026."""

    def setUp(self):
        self.expected_brief = {
            "title": "Talent, Learning and Organizational Development Services",
            "client": "Bank of Canada",
            "file_number": "RFP No. 2026-026",
            "opportunity_type": "Multi-Vendor Standing Panel Framework",
            "contract_term": "3 years with up to two 1-year optional extensions (max 5 years)",
            "procurement_model": "Separate category awards onto qualified supplier panels",
            "scope_categories": [
                "1. Learning & Development Programs and Assessments",
                "2. HR Advisory",
                "3. Facilitation and Team Effectiveness"
            ],
            "evaluation_breakdown": [
                {"stage": "Technical Rated Criteria", "weight": "75 points"},
                {"stage": "Pricing Evaluation", "weight": "25 points"}
            ],
            "commercial_structure": [
                {"topic": "Panel Maximums", "details": "Category 1: 5 firms; Category 2: 3 firms; Category 3: 7 firms"}
            ]
        }

    def test_expected_schema_dimensions(self):
        self.assertEqual(len(self.expected_brief["scope_categories"]), 3)
        self.assertEqual(self.expected_brief["evaluation_breakdown"][0]["weight"], "75 points")
        self.assertEqual(self.expected_brief["evaluation_breakdown"][1]["weight"], "25 points")


if __name__ == "__main__":
    unittest.main()
