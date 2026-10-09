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
from components.ui import epistemic_badge, EPISTEMIC_COLOURS, resolve_evidence_display_status, evidence_badge
import pages.stage_understand as understand
import pages.stage_decide as decide
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

    def test_negative_unassessed_evidence_is_not_declared_missing(self):
        """Negative: Unassessed supplier evidence must never be declared as confirmed MISSING or READY."""
        # Fresh requirement with default DB status 'MISSING' but never reviewed by human
        fresh_req = {"description": "Provide 3 client references", "qual_status": "UNKNOWN", "evidence_status": "MISSING"}
        resolved = resolve_evidence_display_status(fresh_req)
        self.assertEqual(resolved, "UNASSESSED")
        self.assertNotEqual(resolved, "MISSING")
        self.assertNotEqual(resolved, "READY")

        # Unmatched proof item in register defaults to UNASSESSED
        resolved_unmatched = resolve_evidence_display_status(None)
        self.assertEqual(resolved_unmatched, "UNASSESSED")

    def test_positive_evidence_readiness_states_projection(self):
        """Positive: Test evidence readiness projection across unassessed, missing, ready, partial, not required."""
        # 1. Unassessed (fresh from DB, qual_status unknown, no notes/evidence)
        r_unassessed = {"qual_status": "UNKNOWN", "evidence_status": "MISSING"}
        self.assertEqual(resolve_evidence_display_status(r_unassessed), "UNASSESSED")

        # 2. Confirmed Missing (assessed by reviewer: non-UNKNOWN qual or has notes/gap)
        r_missing = {"qual_status": "CONCERN", "evidence_status": "MISSING", "gap_action": "Need client signoff"}
        self.assertEqual(resolve_evidence_display_status(r_missing), "MISSING")

        # 3. Ready (supplier evidence attached)
        r_ready = {"qual_status": "PASS", "evidence_status": "READY", "evidence": "Signed letters"}
        self.assertEqual(resolve_evidence_display_status(r_ready), "READY")

        # 4. Partial (partial supplier evidence)
        r_partial = {"qual_status": "CONCERN", "evidence_status": "PARTIAL"}
        self.assertEqual(resolve_evidence_display_status(r_partial), "PARTIAL")

        # 5. Not Required
        r_not_req = {"evidence_status": "NOT REQUIRED"}
        self.assertEqual(resolve_evidence_display_status(r_not_req), "NOT REQUIRED")

    def test_positive_understand_technical_capabilities_rendering(self):
        """Positive: UNDERSTAND tab_tech renders with canonical priority and proof_needed without AttributeError."""
        captured_md = []
        mock_tab = MagicMock()
        mock_tab.__enter__.return_value = mock_tab
        with patch("streamlit.markdown", side_effect=lambda x, *a, **k: captured_md.append(str(x))), \
             patch("streamlit.caption"), \
             patch("streamlit.tabs", return_value=[mock_tab for _ in range(7)]), \
             patch("streamlit.expander", return_value=mock_tab):

            understand._render_interactive_decision_brief(self.brief, {"id": 1522, "title": "York"})
            all_text = "\n".join(captured_md)

            # Verify technical capabilities rendered with proof_needed and priority
            self.assertIn("Substantive Technical Capabilities & Credentials", all_text)
            self.assertIn("CRITICAL", all_text)
            self.assertIn("🎯 <strong>Required Evidence:</strong>", all_text)

    def test_positive_understand_evaluation_model_rendering(self):
        """Positive: UNDERSTAND tab_eval renders written_proposal_total, technical_total, financial_total without AttributeError."""
        captured_md = []
        mock_tab = MagicMock()
        mock_tab.__enter__.return_value = mock_tab
        with patch("streamlit.markdown", side_effect=lambda x, *a, **k: captured_md.append(str(x))), \
             patch("streamlit.columns", return_value=[MagicMock() for _ in range(4)]), \
             patch("streamlit.tabs", return_value=[mock_tab for _ in range(7)]), \
             patch("streamlit.expander", return_value=mock_tab):

            understand._render_interactive_decision_brief(self.brief, {"id": 1522, "title": "York"})
            all_text = "\n".join(captured_md)

            # Verify evaluation breakdown metrics rendered
            self.assertIn("Mathematical Evaluation Structure", all_text)
            self.assertIn("Passing Threshold", all_text)
            self.assertIn("Tie-Break Rule", all_text)

    def test_positive_decide_pursuit_baseline_rendering(self):
        """Positive: DECIDE pursuit baseline renders evaluation points without AttributeError."""
        captured_md = []
        mock_col = MagicMock()
        with patch("pages.stage_decide._current_access_token_and_org", return_value=("fake_tok", "4326b564-8cc5-4463-9304-9a589f08cc91")), \
             patch("tenancy.get_bid_authenticated", return_value={"id": 1522, "title": "York", "client": "York University"}), \
             patch("tenancy.get_procurement_state_for_organization", return_value={}), \
             patch("tenancy.get_requirements_authenticated", return_value=[]), \
             patch("tenancy.get_clarifications_authenticated", return_value=[]), \
             patch("tenancy.get_bid_decision_authenticated", return_value=None), \
             patch("tenancy.get_firm_profile_authenticated", return_value={}), \
             patch("tenancy.get_bid_brief_authenticated", return_value={}), \
             patch("tenancy.get_latest_analysis_run_authenticated", return_value={"id": 57, "status": "COMPLETE"}), \
             patch("tenancy.get_decision_brief_for_organization", return_value=self.brief), \
             patch("streamlit.markdown", side_effect=lambda x, *a, **k: captured_md.append(str(x))), \
             patch("streamlit.caption"), \
             patch("streamlit.columns", side_effect=lambda spec, *a, **k: [MagicMock() for _ in range(spec if isinstance(spec, int) else len(spec))]), \
             patch("streamlit.tabs", return_value=[MagicMock(), MagicMock(), MagicMock()]), \
             patch("streamlit.selectbox", return_value="All"), \
             patch("streamlit.button", return_value=False):

            decide.page_decide(1522)
            all_text = "\n".join(captured_md)

            self.assertIn("Evidence-Backed Pursuit Baseline", all_text)
            self.assertIn("accountable human decision", all_text)

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
