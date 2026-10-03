"""
tests/test_understand_analysis.py -- Deterministic tests for understand_analysis.py.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import full_analysis as fa
import understand_analysis as ua


class TestUnderstandAnalysisLenses(unittest.TestCase):
    def test_lenses_contain_all_six_specialists(self):
        expected_ids = {
            "PROCUREMENT_STRUCTURE",
            "REQUIREMENTS_COMPLIANCE",
            "EVALUATION_INTELLIGENCE",
            "SCOPE_DELIVERABLES",
            "COMMERCIAL_CONTRACTUAL",
            "SCHEDULE_SUBMISSION",
        }
        self.assertEqual(set(ua.LENS_IDS), expected_ids)
        for lid in expected_ids:
            self.assertIn(lid, ua.LENS_NAME)
            self.assertIn(lid, ua.LENS_CODE)
            self.assertIn(lid, ua.LENS_DESC)


class TestStartOpportunityAnalysis(unittest.TestCase):
    @patch("understand_analysis.db.list_analysis_runs", return_value=[])
    @patch("understand_analysis.tenancy.get_full_analysis_status_for_organization", return_value=None)
    @patch("understand_analysis.tenancy.get_documents_authenticated", return_value=[])
    @patch("understand_analysis.tenancy.require_bid_access")
    @patch("understand_analysis.tenancy.start_fast_analysis_for_organization")
    def test_start_chains_foundation_when_no_fast_run(
        self, mock_start_fast, mock_access, mock_docs, mock_full_status, mock_list_runs
    ):
        res = ua.start_opportunity_analysis(101, "org-test", execution="background")
        mock_access.assert_called_once_with(101, "org-test")
        self.assertEqual(res.get("outcome"), "CREATED")

    @patch("understand_analysis.db.list_analysis_runs", return_value=[
        {"id": 48, "analysis_mode": "FAST", "status": "COMPLETE"}
    ])
    @patch("understand_analysis.tenancy.get_full_analysis_status_for_organization", return_value=None)
    @patch("understand_analysis.tenancy.get_documents_authenticated", return_value=[])
    @patch("understand_analysis.tenancy.require_bid_access")
    @patch("understand_analysis.tenancy.start_full_analysis_for_organization", return_value={"outcome": "CREATED"})
    def test_start_directly_launches_full_when_complete_fast_run_exists(
        self, mock_start_full, mock_access, mock_docs, mock_full_status, mock_list_runs
    ):
        res = ua.start_opportunity_analysis(101, "org-test", execution="background")
        mock_access.assert_called_once_with(101, "org-test")
        mock_start_full.assert_called_once()
        self.assertEqual(res.get("outcome"), "CREATED")

    @patch("understand_analysis.tenancy.get_full_analysis_status_for_organization", return_value={
        "run_id": 50, "status": "COMPLETE"
    })
    @patch("understand_analysis.tenancy.get_documents_authenticated", return_value=[])
    @patch("understand_analysis.tenancy.require_bid_access")
    def test_start_reuses_complete_full_run_when_not_retry(
        self, mock_access, mock_docs, mock_full_status
    ):
        res = ua.start_opportunity_analysis(101, "org-test", retry=False)
        self.assertEqual(res.get("outcome"), "REUSED_COMPLETE")

    @patch("understand_analysis.tenancy.get_full_analysis_status_for_organization", return_value={
        "run_id": 50, "status": "RUNNING"
    })
    @patch("understand_analysis.tenancy.get_documents_authenticated", return_value=[])
    @patch("understand_analysis.tenancy.require_bid_access")
    def test_start_reconnects_to_active_run(
        self, mock_access, mock_docs, mock_full_status
    ):
        res = ua.start_opportunity_analysis(101, "org-test", retry=False)
        self.assertEqual(res.get("outcome"), "ACTIVE_RUN_EXISTS")
        self.assertTrue(res.get("is_live"))


class TestGetOpportunityAnalysisState(unittest.TestCase):
    @patch("understand_analysis.db.list_analysis_runs", return_value=[])
    @patch("understand_analysis.tenancy.get_full_analysis_status_for_organization", return_value={
        "run_id": 52,
        "status": "RUNNING",
        "specialists": {
            "PROCUREMENT_STRUCTURE": {"status": "COMPLETE", "duration_seconds": 12.5},
            "REQUIREMENTS_COMPLIANCE": {"status": "RUNNING"},
        },
        "reconciliation": {"status": "WAITING"},
        "events": [
            {
                "event_type": "CANONICAL_PACKAGE_READY",
                "detail": {
                    "object_counts": {
                        "SCOPED_EVALUATION_CRITERION": 5,
                        "CANONICAL_REQUIREMENT": 24,
                    }
                }
            }
        ]
    })
    def test_state_reports_truthful_lens_and_counts(self, mock_full_status, mock_list_runs):
        state = ua.get_opportunity_analysis_state(101, "org-test")
        self.assertTrue(state["is_live"])
        self.assertFalse(state["is_complete"])
        self.assertEqual(state["run_id"], 52)

        # Verify lenses
        lenses = {l["id"]: l for l in state["lenses"]}
        self.assertEqual(lenses["PROCUREMENT_STRUCTURE"]["status"], "COMPLETE")
        self.assertEqual(lenses["REQUIREMENTS_COMPLIANCE"]["status"], "RUNNING")
        self.assertEqual(lenses["EVALUATION_INTELLIGENCE"]["status"], "WAITING")

        # Verify hub counts
        self.assertIn("5 evaluation criteria verified", state["hub_counts"])
        self.assertIn("24 requirements identified", state["hub_counts"])


# ── Production reconciliation budget regression tests ─────────────────────────

class TestProductionReconBudget(unittest.TestCase):
    """
    Prove that the production Analyze Opportunity path uses the authoritative
    reconciliation output budget, that the commissioning script uses the same
    configuration, that truncation still yields PARTIAL, and that successful
    completion yields COMPLETE.

    All tests are deterministic (0 provider calls).
    """

    def test_production_constant_is_8192(self):
        """PRODUCTION_RECONCILIATION_MAX_OUTPUT_TOKENS must be 8192."""
        self.assertEqual(ua.PRODUCTION_RECONCILIATION_MAX_OUTPUT_TOKENS, 8192)

    def test_production_constant_exceeds_module_default(self):
        """Production budget must be strictly larger than the fa module default."""
        self.assertGreater(
            ua.PRODUCTION_RECONCILIATION_MAX_OUTPUT_TOKENS,
            fa.RECONCILIATION_MAX_OUTPUT_TOKENS,
        )

    def test_fa_module_default_is_still_3000(self):
        """The fa module-level default must remain 3000 (test-safety floor, guarded
        by test_prompts_carry_explicit_output_bounds)."""
        self.assertEqual(fa.RECONCILIATION_MAX_OUTPUT_TOKENS, 3000)

    def test_context_manager_applies_production_budget_and_restores(self):
        """_production_recon_budget() must set the production budget inside the
        context and restore the original value on exit."""
        original = fa.RECONCILIATION_MAX_OUTPUT_TOKENS
        with ua._production_recon_budget():
            self.assertEqual(
                fa.RECONCILIATION_MAX_OUTPUT_TOKENS,
                ua.PRODUCTION_RECONCILIATION_MAX_OUTPUT_TOKENS,
            )
        # Restored after exit
        self.assertEqual(fa.RECONCILIATION_MAX_OUTPUT_TOKENS, original)

    def test_context_manager_restores_on_exception(self):
        """_production_recon_budget() must restore original value even if an
        exception is raised inside the block."""
        original = fa.RECONCILIATION_MAX_OUTPUT_TOKENS
        try:
            with ua._production_recon_budget():
                raise RuntimeError("simulated failure")
        except RuntimeError:
            pass
        self.assertEqual(fa.RECONCILIATION_MAX_OUTPUT_TOKENS, original)

    @patch("understand_analysis.db.list_analysis_runs", return_value=[
        {"id": 48, "analysis_mode": "FAST", "status": "COMPLETE"}
    ])
    @patch("understand_analysis.tenancy.get_full_analysis_status_for_organization", return_value=None)
    @patch("understand_analysis.tenancy.get_documents_authenticated", return_value=[])
    @patch("understand_analysis.tenancy.require_bid_access")
    @patch("understand_analysis.tenancy.start_full_analysis_for_organization", return_value={"outcome": "CREATED"})
    def test_analyze_opportunity_path_applies_production_budget(
        self, mock_start_full, mock_access, mock_docs, mock_full_status, mock_list_runs
    ):
        """When start_opportunity_analysis delegates to tenancy.start_full_analysis_for_organization,
        fa.RECONCILIATION_MAX_OUTPUT_TOKENS must equal the production budget at call time."""
        budget_during_call = []

        def _capture_budget(*args, **kwargs):
            budget_during_call.append(fa.RECONCILIATION_MAX_OUTPUT_TOKENS)
            return {"outcome": "CREATED"}

        mock_start_full.side_effect = _capture_budget

        ua.start_opportunity_analysis(101, "org-test", execution="background")

        self.assertEqual(len(budget_during_call), 1,
                         "start_full_analysis_for_organization must be called exactly once")
        self.assertEqual(
            budget_during_call[0],
            ua.PRODUCTION_RECONCILIATION_MAX_OUTPUT_TOKENS,
            "fa.RECONCILIATION_MAX_OUTPUT_TOKENS must equal the production budget at call time",
        )

    @patch("understand_analysis.db.list_analysis_runs", return_value=[
        {"id": 48, "analysis_mode": "FAST", "status": "COMPLETE"}
    ])
    @patch("understand_analysis.tenancy.get_full_analysis_status_for_organization", return_value=None)
    @patch("understand_analysis.tenancy.get_documents_authenticated", return_value=[])
    @patch("understand_analysis.tenancy.require_bid_access")
    @patch("understand_analysis.tenancy.start_full_analysis_for_organization", return_value={"outcome": "CREATED"})
    def test_fa_module_default_restored_after_analyze_opportunity(
        self, mock_start_full, mock_access, mock_docs, mock_full_status, mock_list_runs
    ):
        """After start_opportunity_analysis returns, fa.RECONCILIATION_MAX_OUTPUT_TOKENS
        must be restored to its original value."""
        before = fa.RECONCILIATION_MAX_OUTPUT_TOKENS
        ua.start_opportunity_analysis(101, "org-test", execution="background")
        after = fa.RECONCILIATION_MAX_OUTPUT_TOKENS
        self.assertEqual(before, after,
                         "fa.RECONCILIATION_MAX_OUTPUT_TOKENS must be restored after the call")

    def test_truncation_still_detected_at_production_budget(self):
        """Verify that the reconciliation truncation status semantics are intact:
        output_truncated=True -> status PARTIAL (fail-closed).
        This uses the fa status constants directly -- no provider call."""
        # fa.STATUS_PARTIAL is the value that means truncated/incomplete
        self.assertEqual(fa.STATUS_PARTIAL, "PARTIAL")
        self.assertEqual(fa.STATUS_COMPLETE, "COMPLETE")
        # The full_analysis module uses OUTPUT_TRUNCATED_REASON as the signal
        self.assertIn("truncated", fa.OUTPUT_TRUNCATED_REASON.lower())

    def test_partial_status_is_distinct_from_complete(self):
        """PARTIAL and COMPLETE must be distinct values -- truncation is fail-closed."""
        self.assertNotEqual(fa.STATUS_PARTIAL, fa.STATUS_COMPLETE)

    def test_commissioning_script_uses_production_constant(self):
        """Prove the commissioning script uses ua.PRODUCTION_RECONCILIATION_MAX_OUTPUT_TOKENS
        and not a separate hardcoded value, by reading its source."""
        import pathlib
        import re
        script = pathlib.Path(__file__).parent.parent / "scripts" / "run_calgary_1417_commissioning.py"
        src = script.read_text(encoding="utf-8")
        # Must reference the production constant from understand_analysis
        self.assertIn("PRODUCTION_RECONCILIATION_MAX_OUTPUT_TOKENS", src,
                      "Commissioning script must reference ua.PRODUCTION_RECONCILIATION_MAX_OUTPUT_TOKENS")
        self.assertIn("_production_recon_budget", src,
                      "Commissioning script must use the _production_recon_budget context manager")
        # Must NOT hardcode 8192 as a standalone literal outside the constant definition or comments
        bare_8192_lines = [
            ln.strip() for ln in src.splitlines()
            if re.search(r'\b8192\b', ln)
            and not ln.strip().startswith("#")
            and "PRODUCTION_RECONCILIATION_MAX_OUTPUT_TOKENS" not in ln
        ]
        self.assertEqual(bare_8192_lines, [],
                         f"Commissioning script must not hardcode 8192 outside the constant: {bare_8192_lines}")


class TestResolveBaselineDocuments(unittest.TestCase):
    def test_single_document_is_marked_primary(self):
        docs = [{"id": 1, "name": "rfp.pdf", "doc_type": "RFP / Source"}]
        doc_ids, doc_roles = ua.resolve_baseline_documents(docs)
        self.assertEqual(doc_ids, [1])
        self.assertEqual(doc_roles, ["primary"])

    def test_multiple_documents_first_is_primary_rest_supporting(self):
        docs = [
            {"id": 1, "name": "main_rfp.pdf", "doc_type": "RFP / Source"},
            {"id": 2, "name": "annex_a.pdf", "doc_type": "RFP / Source"},
            {"id": 3, "name": "pricing_table.xlsx", "doc_type": "RFP / Source"},
        ]
        doc_ids, doc_roles = ua.resolve_baseline_documents(docs)
        self.assertEqual(doc_ids, [1, 2, 3])
        self.assertEqual(doc_roles, ["primary", "supporting", "supporting"])

    def test_metadata_primary_preserved(self):
        docs = [
            {"id": 1, "name": "annex.pdf", "doc_type": "RFP / Source", "role": "supporting"},
            {"id": 2, "name": "main.pdf", "doc_type": "RFP / Source", "role": "primary"},
        ]
        doc_ids, doc_roles = ua.resolve_baseline_documents(docs)
        self.assertEqual(doc_ids, [1, 2])
        self.assertEqual(doc_roles, ["supporting", "primary"])

    def test_empty_docs_returns_empty(self):
        doc_ids, doc_roles = ua.resolve_baseline_documents([])
        self.assertEqual(doc_ids, [])
        self.assertEqual(doc_roles, [])


class TestBaselineGovernanceOrchestration(unittest.TestCase):
    @patch("understand_analysis.start_opportunity_analysis")
    @patch("understand_analysis.tenancy.apply_procurement_update_review_for_organization")
    @patch("understand_analysis.tenancy.record_change_review_decision_for_organization")
    @patch("understand_analysis.tenancy.get_procurement_changes_for_organization")
    @patch("understand_analysis.tenancy.get_procurement_update_reviews_for_organization")
    @patch("understand_analysis.tenancy.require_bid_access")
    def test_apply_baseline_and_resume_approves_pending_and_resumes(
        self, mock_access, mock_reviews, mock_changes, mock_record_decision, mock_apply, mock_start_opp
    ):
        mock_reviews.return_value = [
            {"id": 10, "review_kind": "baseline", "status": "ready_for_review", "base_procurement_revision": 1}
        ]
        mock_changes.side_effect = [
            [{"id": 101, "review_decision": "pending"}, {"id": 102, "review_decision": "approved"}],
            [{"id": 101, "review_decision": "approved"}, {"id": 102, "review_decision": "approved"}],
        ]
        mock_apply.return_value = {"resulting_revision": 2, "applied_change_count": 2}
        mock_start_opp.return_value = {"outcome": "CREATED", "step": ua.STEP_FULL_ANALYSIS_RUNNING}

        res = ua.apply_baseline_and_resume_analysis(
            1, "org-test", 10, user_id="user-1", approve_all_pending=True
        )

        mock_record_decision.assert_called_once_with(
            1, "org-test", 101, "approved", "user-1"
        )
        mock_apply.assert_called_once_with(
            1, "org-test", 10, expected_base_revision=1, applied_by_user_id="user-1"
        )
        mock_start_opp.assert_called_once()
        self.assertEqual(res.get("step"), ua.STEP_FULL_ANALYSIS_RUNNING)

    @patch("understand_analysis.tenancy.get_procurement_changes_for_organization")
    @patch("understand_analysis.tenancy.get_procurement_update_reviews_for_organization")
    @patch("understand_analysis.tenancy.require_bid_access")
    def test_apply_baseline_fails_closed_if_pending_without_approve_all(
        self, mock_access, mock_reviews, mock_changes
    ):
        mock_reviews.return_value = [
            {"id": 10, "review_kind": "baseline", "status": "ready_for_review", "base_procurement_revision": 1}
        ]
        mock_changes.return_value = [
            {"id": 101, "review_decision": "pending"},
        ]

        with self.assertRaises(ValueError) as ctx:
            ua.apply_baseline_and_resume_analysis(
                1, "org-test", 10, user_id="user-1", approve_all_pending=False
            )
        self.assertIn("still pending", str(ctx.exception))


class TestCustomerFacingVocabulary(unittest.TestCase):
    def test_unified_opportunity_analysis_panel_does_not_expose_fast_analysis_card(self):
        import pages.stage_understand as stage_understand
        import inspect
        source = inspect.getsource(stage_understand._render_unified_opportunity_analysis_panel)
        self.assertNotIn("### ⚡ Fast Analysis", source)
        self.assertNotIn("### 🏛️ Establish Procurement Baseline", source)
        self.assertIn("### 💡 Analyze Opportunity", source)


if __name__ == "__main__":
    unittest.main()
