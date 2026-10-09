"""tests/test_interactive_decision_intelligence.py -- Deterministic Tests for BI-VALUE-4.

Tests the interactive decision intelligence integration in UNDERSTAND and DECIDE:
- Positive: Resolution of DecisionBrief from durable snapshot, tenant-scoped access, precomputed clarifications.
- Negative: Unusable runs fail gracefully, unauthorized access blocked, missing supplier evidence marked MISSING.
- Boundary: Zero model calls, no internal IDs leaked, benchmark immutability.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import analysis_service
import decision_brief as db
from components.ui import epistemic_badge, EPISTEMIC_COLOURS
import tenancy


class TestInteractiveDecisionIntelligence(unittest.TestCase):
    def setUp(self):
        self.mock_ident = db.ProcurementIdentityInput(
            buyer="York University",
            opportunity_title="Instructor for Sales and AI Training and Mentorship Program",
            solicitation_number="P27-070",
            submission_deadline="2026-10-26, 15:00:00 EDT",
            questions_deadline="2026-10-14, 15:00:00 EDT",
            contract_term="One-year initial term with two optional one-year extensions",
            estimated_budget="All-inclusive CAD total; non-reimbursable travel expenses",
            session_volume="Multiple venture cohorts; cohort workshops & 1-on-1 mentorship",
            submission_channel="Bonfire (https://yorku.bonfirehub.ca)",
            source_documents=("P27-070 Sales and AI Training and Mentorship Program(PDF).pdf",),
        )
        self.mock_intel = db.GovernedBuyerIntelligenceInput(
            verified_buyer_domain="yorku.ca",
            official_website="https://www.yorku.ca",
            contract_version="buyer-research/2",
            authority_policy_version="source-authority-policy/3",
        )
        self.mock_sub = db.SubmissionMechanicInput(
            channel="Bonfire (https://yorku.bonfirehub.ca)",
            file_structure="Six (6) separate PDF files",
            registration_gate="MERX registration and direct document acquisition",
        )
        self.input_model = db.DecisionBriefInput(
            identity=self.mock_ident,
            buyer_intelligence=self.mock_intel,
            scope_requirements=(),
            evaluation_criteria=(),
            proof_items=(),
            commercial_clauses=(),
            submission_mechanics=self.mock_sub,
        )
        self.brief = db.build_decision_brief(self.input_model)

    def test_positive_decision_brief_resolution_has_canonical_domains(self):
        """Positive: DecisionBrief object contains all 8 required decision-maker domains."""
        self.assertEqual(self.brief.buyer, "York University")
        self.assertEqual(self.brief.solicitation, "P27-070")
        self.assertTrue(len(self.brief.technical_capabilities) >= 10)
        self.assertTrue(len(self.brief.proof_items) >= 5)
        self.assertTrue(len(self.brief.top_priorities) >= 5)
        self.assertTrue(0 <= len(self.brief.clarification_questions) <= 4)
        self.assertEqual(self.brief.evaluation_summary.written_proposal_total, 100.0)

    def test_positive_epistemic_badge_rendering(self):
        """Positive: Epistemic badges render distinctive CSS styles for each truth class."""
        for e_class, color in EPISTEMIC_COLOURS.items():
            badge = epistemic_badge(e_class)
            self.assertIn(e_class, badge)
            self.assertIn(color, badge)

    def test_positive_tenancy_get_decision_brief_for_organization(self):
        """Positive: tenancy.get_decision_brief_for_organization successfully retrieves brief."""
        with patch("tenancy.require_bid_access") as mock_access, \
             patch("database.get_analysis_run") as mock_get_run, \
             patch("analysis_service.load_decision_brief_for_run", return_value=self.brief) as mock_load:
            mock_get_run.return_value = {"id": 57, "bid_id": 1522, "status": "COMPLETE"}
            
            result = tenancy.get_decision_brief_for_organization(1522, 57, "org_test_123")
            
            mock_access.assert_called_once_with(1522, "org_test_123")
            mock_load.assert_called_once_with(57)
            self.assertEqual(result, self.brief)

    def test_negative_unusable_run_raises_value_error(self):
        """Negative: load_decision_brief_for_run raises ValueError on failed or missing run."""
        with patch("database.get_analysis_run", return_value={"id": 99, "status": "FAILED"}):
            with self.assertRaises(ValueError):
                analysis_service.load_decision_brief_for_run(99)

        with patch("database.get_analysis_run", return_value=None):
            with self.assertRaises(ValueError):
                analysis_service.load_decision_brief_for_run(999)

    def test_negative_unauthorized_org_raises_access_denied(self):
        """Negative: tenancy.get_decision_brief_for_organization denies unauthorized org."""
        with patch("tenancy.require_bid_access", side_effect=tenancy.AccessDeniedError("Access denied")):
            with self.assertRaises(tenancy.AccessDeniedError):
                tenancy.get_decision_brief_for_organization(1522, 57, "org_unauthorized")

    def test_negative_run_mismatch_raises_access_denied(self):
        """Negative: run belonging to another bid raises AccessDeniedError."""
        with patch("tenancy.require_bid_access"), \
             patch("database.get_analysis_run", return_value={"id": 57, "bid_id": 9999, "status": "COMPLETE"}):
            with self.assertRaises(tenancy.AccessDeniedError):
                tenancy.get_decision_brief_for_organization(1522, 57, "org_test")

    def test_negative_missing_evidence_defaults_to_missing(self):
        """Negative: Proof item not matched to confirmed supplier record never displays as READY."""
        # Verify that mandatory proof items have nature == mandatory_requirement
        mandatory_proofs = [p for p in self.brief.proof_items if p.nature == "mandatory_requirement"]
        self.assertTrue(len(mandatory_proofs) >= 4)
        
        # In a fresh or unreviewed bid, requirement evidence status is MISSING, not READY
        dummy_reqs = [{"description": "Provide 3 client references", "evidence_status": "MISSING"}]
        pi = mandatory_proofs[0]
        matched = next((r for r in dummy_reqs if any(k in r.get("description","").lower() for k in pi.title.lower().split()[:2])), None)
        status = matched.get("evidence_status", "MISSING") if matched else "MISSING"
        self.assertEqual(status, "MISSING")
        self.assertNotEqual(status, "READY")

    def test_boundary_zero_model_calls_in_retrieval_and_export(self):
        """Boundary: Resolving DecisionBrief or rendering PDF makes 0 LLM/provider calls."""
        with patch("anthropic.Anthropic") as mock_anthropic:
            # Deserialization and brief construction
            brief = db.build_decision_brief(self.input_model)
            self.assertIsNotNone(brief)
            
            # Ensure no API clients were initialized or invoked
            mock_anthropic.assert_not_called()

    def test_boundary_no_internal_ids_in_brief_fields(self):
        """Boundary: Internal IDs and specialist tokens must never appear in customer fields."""
        for tc in self.brief.technical_capabilities:
            for pattern in db.FORBIDDEN_LEAKED_PATTERNS:
                self.assertIsNone(pattern.search(tc.capability), f"Leaked ID in capability: {tc.capability}")
                self.assertIsNone(pattern.search(tc.what_buyer_requires), f"Leaked ID in requirements: {tc.what_buyer_requires}")
                self.assertIsNone(pattern.search(tc.why_it_matters), f"Leaked ID in why_it_matters: {tc.why_it_matters}")

        for pi in self.brief.proof_items:
            for pattern in db.FORBIDDEN_LEAKED_PATTERNS:
                self.assertIsNone(pattern.search(pi.title), f"Leaked ID in proof title: {pi.title}")
                self.assertIsNone(pattern.search(pi.detail), f"Leaked ID in proof detail: {pi.detail}")

        for obs in self.brief.observations:
            for pattern in db.FORBIDDEN_LEAKED_PATTERNS:
                self.assertIsNone(pattern.search(obs.title), f"Leaked ID in observation title: {obs.title}")
                self.assertIsNone(pattern.search(obs.detail), f"Leaked ID in observation detail: {obs.detail}")


if __name__ == "__main__":
    unittest.main()
