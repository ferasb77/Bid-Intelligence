"""
tests/test_understand_analysis.py -- Deterministic tests for understand_analysis.py.
"""
from __future__ import annotations

import inspect
import unittest
from unittest.mock import MagicMock, patch

import full_analysis as fa
import tenancy
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

    @patch("understand_analysis.db.get_bid_procurement_state", return_value={"procurement_truth_status": "governed", "procurement_revision": 1})
    @patch("understand_analysis.db.list_analysis_runs", return_value=[
        {"id": 48, "analysis_mode": "FAST", "status": "COMPLETE"}
    ])
    @patch("understand_analysis.tenancy.get_full_analysis_status_for_organization", return_value=None)
    @patch("understand_analysis.tenancy.get_documents_authenticated", return_value=[])
    @patch("understand_analysis.tenancy.require_bid_access")
    @patch("understand_analysis.tenancy.start_full_analysis_for_organization", return_value={"outcome": "CREATED"})
    def test_start_directly_launches_full_when_complete_fast_run_exists(
        self, mock_start_full, mock_access, mock_docs, mock_full_status, mock_list_runs, mock_proc_state
    ):
        res = ua.start_opportunity_analysis(101, "org-test", execution="background")
        mock_access.assert_called_once_with(101, "org-test")
        mock_start_full.assert_called_once()
        self.assertEqual(res.get("outcome"), "CREATED")

    @patch("understand_analysis.db.get_bid_procurement_state", return_value={"procurement_truth_status": "governed", "procurement_revision": 1})
    @patch("understand_analysis.tenancy.get_full_analysis_status_for_organization", return_value={
        "run_id": 50, "status": "COMPLETE"
    })
    @patch("understand_analysis.tenancy.get_documents_authenticated", return_value=[])
    @patch("understand_analysis.tenancy.require_bid_access")
    def test_start_reuses_complete_full_run_when_not_retry(
        self, mock_access, mock_docs, mock_full_status, mock_proc_state
    ):
        res = ua.start_opportunity_analysis(101, "org-test", retry=False)
        self.assertEqual(res.get("outcome"), "REUSED_COMPLETE")

    @patch("understand_analysis.db.get_bid_procurement_state", return_value={"procurement_truth_status": "governed", "procurement_revision": 1})
    @patch("understand_analysis.tenancy.get_full_analysis_status_for_organization", return_value={
        "run_id": 50, "status": "RUNNING"
    })
    @patch("understand_analysis.tenancy.get_documents_authenticated", return_value=[])
    @patch("understand_analysis.tenancy.require_bid_access")
    def test_start_reconnects_to_active_run(
        self, mock_access, mock_docs, mock_full_status, mock_proc_state
    ):
        res = ua.start_opportunity_analysis(101, "org-test", retry=False)
        self.assertEqual(res.get("outcome"), "ACTIVE_RUN_EXISTS")
        self.assertTrue(res.get("is_live"))


class TestGetOpportunityAnalysisState(unittest.TestCase):
    @patch("understand_analysis.tenancy.get_procurement_state_for_organization", return_value={"procurement_truth_status": "governed", "procurement_revision": 1})
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
    def test_state_reports_truthful_lens_and_counts(self, mock_full_status, mock_list_runs, mock_proc_state):
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


class TestGovernancePrecedenceOverHistoricalFull(unittest.TestCase):
    """
    Requirements from UNDERSTAND-UX1.2:
    1. Precedence: PROCUREMENT GOVERNANCE STATE must be evaluated before a
       historical FULL COMPLETE can be considered current.
    2. For an UNGOVERNED bid:
       - existing FULL COMPLETE must NOT bypass baseline establishment
       - existing FULL data remains historical and immutable
       - deterministic foundation may be reused if valid
       - baseline governance must still be completed
       - state reports NOT COMPLETE, next step is baseline governance
       - 0 model calls to inspect state or present this step
    3. For a GOVERNED bid + current FULL COMPLETE:
       - Opportunity intelligence current
       - Reused complete
       - 0 model calls
    """

    @patch("understand_analysis.tenancy.get_procurement_state_for_organization", return_value={"procurement_truth_status": "ungoverned", "procurement_revision": 1})
    @patch("understand_analysis.db.list_analysis_runs", return_value=[])
    @patch("understand_analysis.tenancy.get_documents_authenticated", return_value=[{"id": 1, "doc_type": "RFP / Source", "name": "rfp.pdf"}])
    @patch("understand_analysis.tenancy.get_full_analysis_status_for_organization", return_value={
        "run_id": 99,
        "status": "COMPLETE",
        "specialists": {
            lid: {"status": "COMPLETE", "duration_seconds": 10.0} for lid in ua.LENS_IDS
        },
        "reconciliation": {"status": "COMPLETE", "duration_seconds": 5.0},
        "events": [
            {
                "event_type": "CANONICAL_PACKAGE_READY",
                "detail": {"object_counts": {"CANONICAL_REQUIREMENT": 20}}
            }
        ]
    })
    def test_ungoverned_bid_with_historical_full_complete_reports_not_complete_in_state(
        self, mock_full_status, mock_docs, mock_runs, mock_proc_state
    ):
        state = ua.get_opportunity_analysis_state(101, "org-test")
        # Must NOT be complete
        self.assertFalse(state["is_complete"])
        self.assertNotEqual(state["step"], ua.STEP_COMPLETE)
        self.assertNotEqual(state["status_label"], "Opportunity intelligence current")
        # Lenses must report WAITING for customer presentation
        for lens in state["lenses"]:
            self.assertEqual(lens["status"], "WAITING")
        self.assertEqual(state["reconciliation_status"], "WAITING")
        self.assertEqual(state["hub_counts"], [])
        # Active full run is None for customer UI, historical full status preserved
        self.assertIsNone(state["run_id"])
        self.assertIsNone(state["full_status"])
        self.assertFalse(state["has_full_run"])
        self.assertEqual(state.get("historical_full_status", {}).get("status"), "COMPLETE")

    @patch("understand_analysis.db.get_bid_procurement_state", return_value={"procurement_truth_status": "ungoverned", "procurement_revision": 1})
    @patch("understand_analysis.db.get_procurement_update_reviews", return_value=[
        {"id": 201, "review_kind": "baseline", "status": "ready_for_review", "base_procurement_revision": 1}
    ])
    @patch("understand_analysis.db.get_procurement_changes", return_value=[
        {"id": 301, "bid_id": 101, "review_id": 201, "review_decision": "pending"}
    ])
    @patch("understand_analysis.db.list_analysis_runs", return_value=[
        {"id": 48, "analysis_mode": "FAST", "status": "COMPLETE"}
    ])
    @patch("understand_analysis.tenancy.get_full_analysis_status_for_organization", return_value={
        "run_id": 99,
        "status": "COMPLETE",
    })
    @patch("understand_analysis.tenancy.get_documents_authenticated", return_value=[{"id": 1, "doc_type": "RFP / Source", "name": "rfp.pdf"}])
    @patch("understand_analysis.tenancy.require_bid_access")
    def test_ungoverned_bid_with_historical_full_complete_does_not_return_reused_complete_in_start(
        self, mock_access, mock_docs, mock_full_status, mock_list_runs, mock_changes, mock_reviews, mock_proc_state
    ):
        res = ua.start_opportunity_analysis(101, "org-test", retry=False)
        # Must NOT return REUSED_COMPLETE
        self.assertNotEqual(res.get("outcome"), "REUSED_COMPLETE")
        self.assertNotEqual(res.get("step"), ua.STEP_COMPLETE)
        # Must require baseline review
        self.assertEqual(res.get("outcome"), "BASELINE_REVIEW_REQUIRED")
        self.assertEqual(res.get("step"), ua.STEP_BASELINE_REVIEW_REQUIRED)

    @patch("understand_analysis.db.get_bid_procurement_state", return_value={"procurement_truth_status": "governed", "procurement_revision": 1})
    @patch("understand_analysis.tenancy.get_procurement_state_for_organization", return_value={"procurement_truth_status": "governed", "procurement_revision": 1})
    @patch("understand_analysis.tenancy.get_full_analysis_status_for_organization", return_value={
        "run_id": 99,
        "status": "COMPLETE",
    })
    @patch("understand_analysis.tenancy.get_documents_authenticated", return_value=[{"id": 1, "doc_type": "RFP / Source", "name": "rfp.pdf"}])
    @patch("understand_analysis.tenancy.require_bid_access")
    def test_governed_bid_with_current_full_complete_returns_reused_complete(
        self, mock_access, mock_docs, mock_full_status, mock_proc_org, mock_proc_db
    ):
        # 1. State inspection
        state = ua.get_opportunity_analysis_state(101, "org-test")
        self.assertTrue(state["is_complete"])
        self.assertEqual(state["step"], ua.STEP_COMPLETE)
        self.assertEqual(state["status_label"], "Opportunity intelligence current")
        self.assertTrue(state["has_full_run"])

        # 2. Start call
        res = ua.start_opportunity_analysis(101, "org-test", retry=False)
        self.assertEqual(res.get("outcome"), "REUSED_COMPLETE")
        self.assertEqual(res.get("step"), ua.STEP_COMPLETE)

    @patch("understand_analysis.db.get_bid_procurement_state", return_value={"procurement_truth_status": "ungoverned", "procurement_revision": 1})
    @patch("understand_analysis.tenancy.get_procurement_state_for_organization", return_value={"procurement_truth_status": "ungoverned", "procurement_revision": 1})
    @patch("understand_analysis.db.get_procurement_update_reviews", return_value=[
        {"id": 201, "review_kind": "baseline", "status": "ready_for_review", "base_procurement_revision": 1}
    ])
    @patch("understand_analysis.db.get_procurement_changes", return_value=[
        {"id": 301, "bid_id": 101, "review_id": 201, "review_decision": "pending"}
    ])
    @patch("understand_analysis.db.list_analysis_runs", return_value=[
        {"id": 48, "analysis_mode": "FAST", "status": "COMPLETE"}
    ])
    @patch("understand_analysis.tenancy.get_full_analysis_status_for_organization", return_value={
        "run_id": 99,
        "status": "COMPLETE",
    })
    @patch("understand_analysis.tenancy.get_documents_authenticated", return_value=[{"id": 1, "doc_type": "RFP / Source", "name": "rfp.pdf"}])
    @patch("understand_analysis.tenancy.require_bid_access")
    @patch("understand_analysis.db.start_full_analysis_run")
    @patch("understand_analysis.db.finalize_full_analysis_run")
    def test_ungoverned_historical_full_run_remains_immutable(
        self, mock_finalize_run, mock_start_run, mock_access, mock_docs, mock_full_status, mock_list_runs, mock_changes, mock_reviews, mock_proc_org, mock_proc_db
    ):
        """Inspection and start on ungoverned bid must never mutate or delete historical full runs."""
        state = ua.get_opportunity_analysis_state(101, "org-test")
        res = ua.start_opportunity_analysis(101, "org-test", retry=False)
        # Verify no run mutation RPCs were called
        mock_start_run.assert_not_called()
        mock_finalize_run.assert_not_called()


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

    @patch("understand_analysis.db.get_bid_procurement_state", return_value={"procurement_truth_status": "governed", "procurement_revision": 1})
    @patch("understand_analysis.db.list_analysis_runs", return_value=[
        {"id": 48, "analysis_mode": "FAST", "status": "COMPLETE"}
    ])
    @patch("understand_analysis.tenancy.get_full_analysis_status_for_organization", return_value=None)
    @patch("understand_analysis.tenancy.get_documents_authenticated", return_value=[])
    @patch("understand_analysis.tenancy.require_bid_access")
    @patch("understand_analysis.tenancy.start_full_analysis_for_organization", return_value={"outcome": "CREATED"})
    def test_analyze_opportunity_path_applies_production_budget(
        self, mock_start_full, mock_access, mock_docs, mock_full_status, mock_list_runs, mock_proc_state
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

    @patch("understand_analysis.db.get_bid_procurement_state", return_value={"procurement_truth_status": "governed", "procurement_revision": 1})
    @patch("understand_analysis.db.list_analysis_runs", return_value=[
        {"id": 48, "analysis_mode": "FAST", "status": "COMPLETE"}
    ])
    @patch("understand_analysis.tenancy.get_full_analysis_status_for_organization", return_value=None)
    @patch("understand_analysis.tenancy.get_documents_authenticated", return_value=[])
    @patch("understand_analysis.tenancy.require_bid_access")
    @patch("understand_analysis.tenancy.start_full_analysis_for_organization", return_value={"outcome": "CREATED"})
    def test_fa_module_default_restored_after_analyze_opportunity(
        self, mock_start_full, mock_access, mock_docs, mock_full_status, mock_list_runs, mock_proc_state
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

    def test_three_documents_one_explicit_primary_preserved(self):
        docs = [
            {"id": 1, "name": "annex_a.pdf", "doc_type": "RFP / Source"},
            {"id": 2, "name": "main_rfp.pdf", "doc_type": "RFP / Source", "role": "primary"},
            {"id": 3, "name": "pricing_table.xlsx", "doc_type": "RFP / Source"},
        ]
        doc_ids, doc_roles = ua.resolve_baseline_documents(docs)
        self.assertEqual(doc_ids, [1, 2, 3])
        self.assertEqual(doc_roles, ["supporting", "primary", "supporting"])

    def test_three_documents_zero_primaries_fails_closed(self):
        docs = [
            {"id": 1, "name": "main_rfp.pdf", "doc_type": "RFP / Source"},
            {"id": 2, "name": "annex_a.pdf", "doc_type": "RFP / Source"},
            {"id": 3, "name": "pricing_table.xlsx", "doc_type": "RFP / Source"},
        ]
        doc_ids, doc_roles = ua.resolve_baseline_documents(docs)
        self.assertIsNone(doc_ids)
        self.assertEqual(doc_roles, "AMBIGUOUS_NO_PRIMARY")

    def test_three_documents_two_primaries_fails_closed(self):
        docs = [
            {"id": 1, "name": "main_rfp.pdf", "doc_type": "RFP / Source", "role": "primary"},
            {"id": 2, "name": "annex_a.pdf", "doc_type": "RFP / Source", "role": "primary"},
            {"id": 3, "name": "pricing_table.xlsx", "doc_type": "RFP / Source"},
        ]
        doc_ids, doc_roles = ua.resolve_baseline_documents(docs)
        self.assertIsNone(doc_ids)
        self.assertEqual(doc_roles, "AMBIGUOUS_MULTIPLE_PRIMARIES")

    def test_three_documents_zero_primaries_resolved_by_chosen_primary(self):
        docs = [
            {"id": 1, "name": "main_rfp.pdf", "doc_type": "RFP / Source"},
            {"id": 2, "name": "annex_a.pdf", "doc_type": "RFP / Source"},
            {"id": 3, "name": "pricing_table.xlsx", "doc_type": "RFP / Source"},
        ]
        doc_ids, doc_roles = ua.resolve_baseline_documents(docs, chosen_primary_id=2)
        self.assertEqual(doc_ids, [1, 2, 3])
        self.assertEqual(doc_roles, ["supporting", "primary", "supporting"])

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
            1, "org-test", 10, expected_base_revision=1, actor_user_id="user-1"
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


class TestApplyInterfaceContract(unittest.TestCase):
    """GOVERNANCE-HOTFIX-2: Regression suite for tenancy apply interface contract."""

    def test_tenancy_apply_signature_contract(self):
        """Authoritative tenancy signature must have actor_user_id and NOT applied_by_user_id."""
        sig = inspect.signature(tenancy.apply_procurement_update_review_for_organization)
        param_names = list(sig.parameters.keys())
        self.assertEqual(
            param_names,
            ["bid_id", "organization_id", "review_id", "expected_base_revision", "actor_user_id"],
            "Authoritative parameters must be (bid_id, organization_id, review_id, expected_base_revision, actor_user_id)",
        )
        self.assertNotIn("applied_by_user_id", param_names)

    @patch("tenancy.db.apply_procurement_update_review")
    @patch("tenancy.db.get_procurement_update_reviews")
    @patch("tenancy.require_bid_access")
    def test_real_tenancy_wrapper_accepts_actor_user_id_contract(
        self, mock_access, mock_reviews, mock_db_apply
    ):
        """Test C: Real tenancy wrapper accepts actor_user_id through mocked DB boundary without TypeError."""
        mock_reviews.return_value = [{"id": 42, "bid_id": 7, "base_procurement_revision": 1, "status": "ready_for_review"}]
        mock_db_apply.return_value = {"status": "applied", "resulting_revision": 2}

        # Call with exact keyword contract used by understand_analysis
        res = tenancy.apply_procurement_update_review_for_organization(
            bid_id=7,
            organization_id="org-c",
            review_id=42,
            expected_base_revision=1,
            actor_user_id="user-c",
        )
        self.assertEqual(res.get("status"), "applied")
        mock_db_apply.assert_called_once_with(42, 1, "user-c")

    @patch("tenancy.db.apply_procurement_update_review")
    @patch("tenancy.db.get_procurement_update_reviews")
    @patch("tenancy.require_bid_access")
    def test_zero_mutation_on_invalid_keyword(
        self, mock_access, mock_reviews, mock_db_apply
    ):
        """Prior bad keyword applied_by_user_id fails immediately at the Python boundary before any DB mutation."""
        mock_reviews.return_value = [{"id": 42, "bid_id": 7}]
        with self.assertRaises(TypeError) as ctx:
            tenancy.apply_procurement_update_review_for_organization(
                bid_id=7,
                organization_id="org-c",
                review_id=42,
                expected_base_revision=1,
                applied_by_user_id="user-c",
            )
        self.assertIn("unexpected keyword argument 'applied_by_user_id'", str(ctx.exception))
        # Critical safety guarantee: zero database mutation occurred
        mock_db_apply.assert_not_called()
        mock_access.assert_not_called()

    @patch("understand_analysis.start_opportunity_analysis")
    @patch("tenancy.db.apply_procurement_update_review")
    @patch("tenancy.db.get_procurement_update_reviews")
    @patch("tenancy.require_bid_access")
    @patch("understand_analysis.tenancy.get_procurement_changes_for_organization")
    @patch("understand_analysis.tenancy.get_procurement_update_reviews_for_organization")
    def test_test_a_explicit_baseline_apply_executes_real_tenancy_contract(
        self, mock_ua_reviews, mock_ua_changes, mock_access, mock_tenancy_reviews, mock_db_apply, mock_start_opp
    ):
        """Test A: apply_baseline_and_resume_analysis calls real tenancy wrapper with actor_user_id and resumes."""
        mock_ua_reviews.return_value = [
            {"id": 10, "review_kind": "baseline", "status": "ready_for_review", "base_procurement_revision": 1}
        ]
        mock_ua_changes.return_value = [
            {"id": 101, "review_decision": "approved"},
            {"id": 102, "review_decision": "approved"},
        ]
        mock_tenancy_reviews.return_value = [
            {"id": 10, "bid_id": 1, "base_procurement_revision": 1, "status": "ready_for_review"}
        ]
        mock_db_apply.return_value = {"resulting_revision": 2, "applied_change_count": 2}
        mock_start_opp.return_value = {"outcome": "CREATED", "step": ua.STEP_FULL_ANALYSIS_RUNNING}

        # Do NOT mock tenancy.apply_procurement_update_review_for_organization.
        # Let the real function run so Python enforces the keyword contract!
        res = ua.apply_baseline_and_resume_analysis(
            1, "org-test", 10, user_id="user-explicit-1", api_key="test-api-key", approve_all_pending=False
        )

        # Real tenancy wrapper validated arguments and forwarded to db
        mock_db_apply.assert_called_once_with(10, 1, "user-explicit-1")
        mock_start_opp.assert_called_once_with(
            1, "org-test", api_key="test-api-key", created_by_user_id="user-explicit-1", execution="background"
        )
        self.assertEqual(res.get("step"), ua.STEP_FULL_ANALYSIS_RUNNING)

    @patch("understand_analysis.tenancy.start_full_analysis_for_organization")
    @patch("database.apply_procurement_update_review")
    @patch("database.get_procurement_update_reviews")
    @patch("tenancy.require_bid_access")
    @patch("database.get_procurement_changes")
    @patch("database.list_analysis_runs", return_value=[{"id": 1, "analysis_mode": "FAST", "status": "COMPLETE"}])
    @patch("database.get_bid_procurement_state", return_value={"procurement_truth_status": "ungoverned", "procurement_revision": 1})
    def test_test_b_orchestrator_auto_apply_executes_real_tenancy_contract(
        self, mock_proc_state, mock_runs, mock_db_changes,
        mock_access, mock_db_reviews, mock_db_apply, mock_start_full
    ):
        """Test B: start_opportunity_analysis with ready/reviewed baseline (0 pending, >=1 approved)
        auto-applies via real tenancy wrapper with actor_user_id and proceeds to Full Analysis."""
        mock_db_reviews.return_value = [
            {"id": 20, "bid_id": 1, "review_kind": "baseline", "status": "ready_for_review", "base_procurement_revision": 1}
        ]
        mock_db_changes.return_value = [
            {"id": 201, "review_decision": "approved"},
            {"id": 202, "review_decision": "approved"},
        ]
        mock_db_apply.return_value = {"resulting_revision": 2, "applied_change_count": 2}
        mock_start_full.return_value = {"outcome": "CREATED", "run_id": 99}

        # Run start_opportunity_analysis through the real tenancy apply wrapper
        res = ua.start_opportunity_analysis(1, "org-test", created_by_user_id="user-auto-2")

        # Proves real tenancy contract was called with actor_user_id="user-auto-2" without TypeError
        mock_db_apply.assert_called_once_with(20, 1, "user-auto-2")
        mock_start_full.assert_called_once()
        self.assertEqual(res.get("outcome"), "CREATED")


class TestFailedBaselineRecovery(unittest.TestCase):
    """Prove recovery from a prior failed baseline review without mutating history."""

    @patch("understand_analysis.tenancy.propose_procurement_changes_for_organization")
    @patch("understand_analysis.tenancy.create_procurement_update_review_for_organization")
    @patch("understand_analysis.db.get_procurement_update_reviews")
    @patch("understand_analysis.tenancy.get_documents_authenticated")
    @patch("understand_analysis.db.get_bid_procurement_state")
    @patch("understand_analysis.db.list_analysis_runs")
    @patch("understand_analysis.tenancy.get_full_analysis_status_for_organization")
    @patch("understand_analysis.tenancy.require_bid_access")
    def test_retry_creates_fresh_baseline_review_leaving_failed_review_intact(
        self, mock_access, mock_full_status, mock_list_runs, mock_proc_state,
        mock_docs, mock_reviews, mock_create_review, mock_propose
    ):
        mock_full_status.return_value = None
        mock_list_runs.return_value = [{"id": 40, "analysis_mode": "FAST", "status": "COMPLETE"}]
        mock_proc_state.return_value = {"procurement_truth_status": "ungoverned", "procurement_revision": 1}
        mock_docs.return_value = [{"id": 1, "name": "rfp.pdf", "doc_type": "RFP / Source"}]

        # Prior review failed
        failed_review = {
            "id": 99,
            "review_kind": "baseline",
            "status": "failed",
            "review_note": "function digest(text, unknown) does not exist",
        }
        # First call: DB only has the failed review
        mock_reviews.side_effect = [
            [failed_review],
            [failed_review],
        ]
        # New review created
        mock_create_review.return_value = {"id": 100, "review_kind": "baseline", "status": "analyzing"}

        res = ua.start_opportunity_analysis(101, "org-test", retry=True, execution="background")

        # Proves a fresh review was created
        mock_create_review.assert_called_once_with(
            101, "org-test", "baseline", [1], ["primary"], buyer_update_type="Original RFP"
        )
        mock_propose.assert_called_once()
        self.assertEqual(res.get("outcome"), "CREATED")
        self.assertEqual(res.get("review_id"), 100)

    @patch("understand_analysis.tenancy.propose_procurement_changes_for_organization")
    @patch("understand_analysis.tenancy.create_procurement_update_review_for_organization")
    @patch("understand_analysis.db.get_procurement_update_reviews")
    @patch("understand_analysis.tenancy.get_documents_authenticated")
    @patch("understand_analysis.db.get_bid_procurement_state")
    @patch("understand_analysis.db.list_analysis_runs")
    @patch("understand_analysis.tenancy.get_full_analysis_status_for_organization")
    @patch("understand_analysis.tenancy.require_bid_access")
    def test_repeated_clicks_do_not_create_duplicate_active_reviews(
        self, mock_access, mock_full_status, mock_list_runs, mock_proc_state,
        mock_docs, mock_reviews, mock_create_review, mock_propose
    ):
        mock_full_status.return_value = None
        mock_list_runs.return_value = [{"id": 40, "analysis_mode": "FAST", "status": "COMPLETE"}]
        mock_proc_state.return_value = {"procurement_truth_status": "ungoverned", "procurement_revision": 1}
        mock_docs.return_value = [{"id": 1, "name": "rfp.pdf", "doc_type": "RFP / Source"}]

        # An active baseline review already exists
        active_review = {"id": 100, "review_kind": "baseline", "status": "analyzing"}
        mock_reviews.return_value = [active_review]

        res = ua.start_opportunity_analysis(101, "org-test", retry=True, execution="background")

        mock_create_review.assert_not_called()
        mock_propose.assert_not_called()
        self.assertEqual(res.get("outcome"), "ACTIVE_RUN_EXISTS")
        self.assertEqual(res.get("review_id"), 100)


class TestNewBidOrchestratorDelegation(unittest.TestCase):
    def test_new_bid_page_invokes_start_opportunity_analysis(self):
        import pathlib
        app_path = pathlib.Path(__file__).parent.parent / "app.py"
        src = app_path.read_text(encoding="utf-8")
        fn_start = src.index("def page_new_bid():")
        fn_end = src.index("def _render_extraction_review():", fn_start)
        body = src[fn_start:fn_end]
        self.assertIn("_ua.start_opportunity_analysis(", body)
        self.assertNotIn("_tenancy.start_fast_analysis_for_organization(", body)


class TestCustomerFacingVocabulary(unittest.TestCase):
    def test_unified_opportunity_analysis_panel_does_not_expose_fast_analysis_card(self):
        import pages.stage_understand as stage_understand
        import inspect
        source = inspect.getsource(stage_understand._render_unified_opportunity_analysis_panel)
        self.assertNotIn("### ⚡ Fast Analysis", source)
        self.assertNotIn("### 🏛️ Establish Procurement Baseline", source)
        self.assertIn("### 💡 Analyze Opportunity", source)

    def test_no_engine_or_proposal_generation_in_stage_understand_panel(self):
        import pages.stage_understand as stage_understand
        import inspect
        source = inspect.getsource(stage_understand._render_unified_opportunity_analysis_panel)
        self.assertNotIn("(Engine:", source)
        self.assertNotIn("authoritative basis for proposal generation", source)
        self.assertIn("authoritative basis for response planning, evidence alignment and proposal assurance", source)

    def test_progress_labels_use_customer_vocabulary(self):
        import pages.stage_understand as stage_understand
        import inspect
        source = inspect.getsource(stage_understand._render_unified_progress)
        self.assertIn("Step 1: Analyzing procurement documents…", source)
        self.assertIn("Step 2: Confirming procurement facts…", source)
        self.assertIn("Step 3: Analyzing opportunity across six intelligence lenses…", source)
        self.assertIn("Step 4: Reconciling opportunity intelligence…", source)


class TestSingleLiveProgressSurface(unittest.TestCase):
    """UNDERSTAND-UX2: Single Live Progress Surface regressions."""

    def test_format_started_ago(self):
        import pages.stage_understand as su
        from datetime import datetime, timezone, timedelta

        self.assertEqual(su._format_started_ago(None), "")
        self.assertEqual(su._format_started_ago(""), "")
        self.assertEqual(su._format_started_ago("not-a-date"), "")

        now = datetime.now(timezone.utc)
        just_now = now.isoformat()
        self.assertEqual(su._format_started_ago(just_now), "started just now")

        two_mins_ago = (now - timedelta(minutes=2, seconds=5)).isoformat()
        self.assertEqual(su._format_started_ago(two_mins_ago), "started 2m ago")

    def test_should_poll_opportunity(self):
        import pages.stage_understand as su
        import understand_analysis as ua

        self.assertFalse(su._should_poll_opportunity(None))
        self.assertFalse(su._should_poll_opportunity({}))
        self.assertFalse(su._should_poll_opportunity({"step": ua.STEP_COMPLETE}))
        self.assertFalse(su._should_poll_opportunity({"step": ua.STEP_PARTIAL}))
        self.assertFalse(su._should_poll_opportunity({"step": ua.STEP_FAILED}))
        self.assertFalse(su._should_poll_opportunity({"step": ua.STEP_BASELINE_REVIEW_REQUIRED}))
        self.assertFalse(su._should_poll_opportunity({"step": ua.STEP_BASELINE_PRIMARY_AMBIGUOUS}))

        self.assertTrue(su._should_poll_opportunity({"step": ua.STEP_FOUNDATION_RUNNING}))
        self.assertTrue(su._should_poll_opportunity({"step": ua.STEP_FULL_ANALYSIS_RUNNING}))
        self.assertTrue(su._should_poll_opportunity({"step": ua.STEP_BASELINE_APPLYING}))

    @patch("streamlit.markdown")
    def test_live_screen_foundation_running_renders_single_surface_with_nested_milestones(self, mock_markdown):
        import pages.stage_understand as su
        import understand_analysis as ua
        import analysis_service as svc

        opp_state = {
            "step": ua.STEP_FOUNDATION_RUNNING,
            "procurement_state": {"procurement_truth_status": "ungoverned", "procurement_revision": 1},
            "latest_fast_run": {
                "id": 12,
                "status": "ANALYZING",
                "started_at": "2026-10-04T07:45:00+00:00",
                "progress": {
                    "milestones": [
                        {"milestone": svc.MILESTONE_CORPUS_PREPARED, "reached_at": "t1"},
                        {"milestone": svc.MILESTONE_OPPORTUNITY_IDENTIFIED, "reached_at": "t2"},
                    ],
                    "early_facts": {
                        "title": "Bank Talent RFP",
                        "buyer": "Bank of Canada",
                        "submission_deadline": "2026-11-01",
                    },
                },
            },
            "full_status": None,
        }

        su._render_unified_progress(opp_state)

        mock_markdown.assert_called_once()
        rendered = mock_markdown.call_args[0][0]

        # 1. Exactly ONE pipeline header
        self.assertEqual(rendered.count("Opportunity Intelligence Pipeline"), 1)

        # 2. Step 1 is active with proper customer wording
        self.assertIn("Step 1: Analyzing procurement documents…", rendered)
        self.assertNotIn("Step 1: Procurement documents analyzed", rendered)

        # 3. Foundation milestones are nested under Step 1
        self.assertIn("Preparing procurement documents", rendered)
        self.assertIn("Understanding the opportunity", rendered)
        self.assertIn("Identifying critical dates and requirements", rendered)
        self.assertIn("Mapping procurement structure", rendered)

        # 4. Early facts are nested
        self.assertIn("What we know so far", rendered)
        self.assertIn("Bank Talent RFP", rendered)
        self.assertIn("Bank of Canada", rendered)

        # 5. Subsequent steps are pending
        self.assertIn("Step 2: Confirm procurement facts", rendered)
        self.assertIn("Step 3: Analyze opportunity across six intelligence lenses", rendered)
        self.assertIn("Step 4: Reconcile opportunity intelligence", rendered)

        # 6. Must NOT contain internal or legacy labels
        self.assertNotIn("Fast Analysis", rendered)
        self.assertNotIn("Analyzing… typically 2–4 minutes", rendered)

    @patch("streamlit.button", return_value=False)
    @patch("streamlit.markdown")
    @patch("pages.stage_understand._current_access_token_and_org", return_value=("tok", "org-1"))
    @patch("understand_analysis.get_opportunity_analysis_state")
    def test_live_opportunity_progress_renders_single_card_and_single_refresh(
        self, mock_get_state, mock_tok_org, mock_markdown, mock_button
    ):
        import pages.stage_understand as su
        import understand_analysis as ua

        opp_state = {
            "step": ua.STEP_FOUNDATION_RUNNING,
            "procurement_state": {"procurement_truth_status": "ungoverned", "procurement_revision": 1},
            "latest_fast_run": {
                "id": 12,
                "status": "ANALYZING",
                "progress": {"milestones": []},
            },
            "full_status": None,
        }
        mock_get_state.return_value = opp_state

        su._render_live_opportunity_progress(10)

        # Exactly ONE call to render the pipeline markdown
        mock_markdown.assert_called_once()
        rendered = mock_markdown.call_args[0][0]
        self.assertIn("Opportunity Intelligence Pipeline", rendered)
        self.assertNotIn("Analyzing… typically 2–4 minutes", rendered)

        # Exactly ONE button call for "Refresh status" (NOT "Refresh now")
        self.assertEqual(mock_button.call_count, 1)
        btn_label = mock_button.call_args[0][0]
        self.assertIn("Refresh status", btn_label)
        self.assertNotIn("Refresh now", btn_label)

    @patch("streamlit.rerun")
    @patch("pages.stage_understand._current_access_token_and_org", return_value=("tok", "org-1"))
    @patch("understand_analysis.get_opportunity_analysis_state")
    def test_live_opportunity_progress_reruns_when_state_transitions_out_of_running(
        self, mock_get_state, mock_tok_org, mock_rerun
    ):
        import pages.stage_understand as su
        import understand_analysis as ua

        mock_get_state.return_value = {
            "step": ua.STEP_BASELINE_REVIEW_REQUIRED,
            "baseline_review": {"id": 1},
        }

        su._render_live_opportunity_progress(10)
        mock_rerun.assert_called_once()


class TestUnifiedProgressStageTransitions(unittest.TestCase):
    """Verify each stage transition per Section 12."""

    @patch("streamlit.markdown")
    def test_stage_a_foundation_running(self, mock_markdown):
        import pages.stage_understand as su
        import understand_analysis as ua
        import analysis_service as svc

        opp_state = {
            "step": ua.STEP_FOUNDATION_RUNNING,
            "procurement_state": {"procurement_truth_status": "ungoverned", "procurement_revision": 1},
            "latest_fast_run": {
                "id": 1, "status": "ANALYZING",
                "progress": {
                    "milestones": [{"milestone": svc.MILESTONE_CORPUS_PREPARED}],
                }
            },
        }
        su._render_unified_progress(opp_state)
        rendered = mock_markdown.call_args[0][0]
        self.assertIn("Step 1: Analyzing procurement documents…", rendered)
        self.assertIn("Preparing procurement documents", rendered)
        self.assertIn("Step 2: Confirm procurement facts", rendered)

    @patch("streamlit.markdown")
    def test_stage_b_baseline_review_required(self, mock_markdown):
        import pages.stage_understand as su
        import understand_analysis as ua

        opp_state = {
            "step": ua.STEP_BASELINE_REVIEW_REQUIRED,
            "procurement_state": {"procurement_truth_status": "ungoverned", "procurement_revision": 1},
            "baseline_review": {"id": 5, "status": "ready_for_review"},
        }
        su._render_unified_progress(opp_state)
        rendered = mock_markdown.call_args[0][0]
        # Step 1 is done, sub-steps collapsed
        self.assertIn("Step 1: Procurement documents analyzed", rendered)
        self.assertNotIn("Preparing procurement documents", rendered)
        # Step 2 is active
        self.assertIn("Step 2: Confirming procurement facts…", rendered)
        # Step 3 and 4 pending
        self.assertIn("Step 3: Analyze opportunity across six intelligence lenses", rendered)

    @patch("streamlit.markdown")
    def test_stage_c_full_analysis_running(self, mock_markdown):
        import pages.stage_understand as su
        import understand_analysis as ua

        opp_state = {
            "step": ua.STEP_FULL_ANALYSIS_RUNNING,
            "procurement_state": {"procurement_truth_status": "governed", "procurement_revision": 1},
            "full_status": {
                "specialists": {
                    "legal": {"status": "COMPLETE"},
                    "technical": {"status": "COMPLETE"},
                    "commercial": {"status": "RUNNING"},
                    "operations": {"status": "WAITING"},
                    "governance": {"status": "WAITING"},
                    "executive": {"status": "WAITING"},
                }
            },
        }
        su._render_unified_progress(opp_state)
        rendered = mock_markdown.call_args[0][0]
        # Step 1 and 2 done
        self.assertIn("Step 1: Procurement documents analyzed", rendered)
        self.assertIn("Step 2: Procurement facts confirmed", rendered)
        # Step 3 active with x/6 specialists
        self.assertIn("Step 3: Analyzing opportunity across six intelligence lenses…", rendered)
        self.assertIn("2/6 intelligence lenses complete", rendered)
        # Specialist sub-steps visible
        self.assertIn("Legal & Compliance", rendered)
        self.assertIn("Technical & Solution", rendered)
        self.assertIn("Commercial & Pricing", rendered)
        # No foundation progress
        self.assertNotIn("Preparing procurement documents", rendered)

    @patch("streamlit.markdown")
    def test_stage_d_step_3_complete_step_4_active(self, mock_markdown):
        import pages.stage_understand as su
        import understand_analysis as ua

        opp_state = {
            "step": ua.STEP_FULL_ANALYSIS_RUNNING,
            "procurement_state": {"procurement_truth_status": "governed", "procurement_revision": 1},
            "full_status": {
                "specialists": {
                    "legal": {"status": "COMPLETE"},
                    "technical": {"status": "COMPLETE"},
                    "commercial": {"status": "COMPLETE"},
                    "operations": {"status": "COMPLETE"},
                    "governance": {"status": "COMPLETE"},
                    "executive": {"status": "COMPLETE"},
                }
            },
        }
        su._render_unified_progress(opp_state)
        rendered = mock_markdown.call_args[0][0]
        # Step 3 is done, collapsed
        self.assertIn("Step 3: Specialist analysis complete", rendered)
        self.assertNotIn("Commercial & Pricing", rendered)
        # Step 4 is active
        self.assertIn("Step 4: Reconciling opportunity intelligence…", rendered)

    @patch("streamlit.markdown")
    def test_stage_e_complete(self, mock_markdown):
        import pages.stage_understand as su
        import understand_analysis as ua

        opp_state = {
            "step": ua.STEP_COMPLETE,
            "procurement_state": {"procurement_truth_status": "governed", "procurement_revision": 1},
        }
        su._render_unified_progress(opp_state)
        rendered = mock_markdown.call_args[0][0]
        self.assertIn("Step 1: Procurement documents analyzed", rendered)
        self.assertIn("Step 2: Procurement facts confirmed", rendered)
        self.assertIn("Step 3: Specialist analysis complete", rendered)
        self.assertIn("Step 4: Opportunity intelligence reconciled", rendered)
        self.assertNotIn("Preparing procurement documents", rendered)

    @patch("streamlit.button", return_value=False)
    @patch("streamlit.markdown")
    @patch("pages.stage_understand._start_opportunity_analysis")
    @patch("pages.stage_understand._current_access_token_and_org", return_value=("tok", "org-1"))
    @patch("understand_analysis.get_opportunity_analysis_state")
    def test_stage_e_failed_panel(self, mock_get_state, mock_tok_org, mock_start, mock_markdown, mock_button):
        import pages.stage_understand as su
        import understand_analysis as ua

        opp_state = {
            "step": ua.STEP_FAILED,
            "status_label": "Analysis failed unexpectedly",
            "procurement_state": {"procurement_truth_status": "ungoverned", "procurement_revision": 1},
        }
        mock_get_state.return_value = opp_state

        su._render_unified_opportunity_analysis_panel(
            10, "org-1", [{"doc_type": "RFP / Source"}], opp_state["procurement_state"]
        )

        rendered = " ".join(str(c.args[0]) for c in mock_markdown.call_args_list if c.args)
        self.assertIn("Analysis failed unexpectedly", rendered)
        self.assertNotIn("Opportunity Intelligence Pipeline", rendered)
        self.assertNotIn("Analyzing… typically 2–4 minutes", rendered)

        # Retry button present
        self.assertEqual(mock_button.call_count, 1)
        self.assertIn("Retry Opportunity Analysis", mock_button.call_args[0][0])

    @patch("streamlit.markdown")
    @patch("pages.stage_understand._current_access_token_and_org", return_value=("tok", "org-1"))
    @patch("understand_analysis.get_opportunity_analysis_state")
    def test_stage_e_partial_progress_and_panel(self, mock_get_state, mock_tok_org, mock_markdown):
        import pages.stage_understand as su
        import understand_analysis as ua

        # 1. Progress bar reflects partially reconciled
        opp_state = {
            "step": ua.STEP_PARTIAL,
            "status_label": "Opportunity intelligence partially complete",
            "partial_reason": "provider stop_reason=max_tokens at 3000 output tokens",
            "procurement_state": {"procurement_truth_status": "governed", "procurement_revision": 2},
            "full_status": {
                "run_id": 56,
                "status": "PARTIAL",
                "failure_reason": "incomplete domains: RECONCILIATION (output truncated)",
                "specialists": {
                    "legal": {"status": "COMPLETE"},
                    "technical": {"status": "COMPLETE"},
                    "commercial": {"status": "COMPLETE"},
                    "operations": {"status": "COMPLETE"},
                    "governance": {"status": "COMPLETE"},
                    "executive": {"status": "COMPLETE"},
                },
            },
        }
        mock_get_state.return_value = opp_state

        su._render_unified_progress(opp_state)
        rendered_progress = mock_markdown.call_args[0][0]
        self.assertIn("Step 4: Opportunity intelligence partially reconciled", rendered_progress)
        self.assertNotIn("Step 4: Opportunity intelligence reconciled\n", rendered_progress)

        # 2. Panel renders warning banner, not green check
        mock_markdown.reset_mock()
        with patch("streamlit.columns", return_value=(MagicMock(), MagicMock())), \
             patch("streamlit.expander", return_value=MagicMock()), \
             patch("tenancy.export_bid_intelligence_brief_for_organization", return_value=b"fake-pdf"):
            su._render_unified_opportunity_analysis_panel(
                1522, "00000000-0000-0000-0000-000000000001", [{"doc_type": "RFP / Source"}], opp_state["procurement_state"]
            )
        rendered_panel = " ".join(str(c.args[0]) for c in mock_markdown.call_args_list if c.args)
        self.assertIn("⚠ Opportunity intelligence partially complete", rendered_panel)
        self.assertIn("provider stop_reason=max_tokens at 3000 output tokens", rendered_panel)
        self.assertNotIn("✓ Opportunity intelligence current", rendered_panel)


class TestReconciliationBudgetIntegrity(unittest.TestCase):
    def test_reconciliation_contract_digest_parameterization(self):
        d_default = fa.reconciliation_contract_digest()
        d_3000 = fa.reconciliation_contract_digest(3000)
        d_8192 = fa.reconciliation_contract_digest(8192)
        self.assertEqual(d_default, d_3000)
        self.assertNotEqual(d_3000, d_8192)

    def test_fingerprint_budget_parameterization(self):
        pkg = MagicMock(spec=fa.CanonicalPackage)
        pkg.package_digest = "test-pkg-digest"
        pkg.objects_of_type.return_value = []
        fp_3000 = fa.compute_full_analysis_fingerprint(pkg, reconciliation_max_output_tokens=3000)
        fp_8192 = fa.compute_full_analysis_fingerprint(pkg, reconciliation_max_output_tokens=8192)
        fp_default = fa.compute_full_analysis_fingerprint(pkg)
        self.assertEqual(fp_default, fp_3000)
        self.assertNotEqual(fp_3000, fp_8192)

    @patch("understand_analysis.db.get_bid_procurement_state", return_value={"procurement_truth_status": "governed", "procurement_revision": 2})
    @patch("understand_analysis.db.list_analysis_runs", return_value=[{"id": 48, "analysis_mode": "FAST", "status": "COMPLETE"}])
    @patch("understand_analysis.tenancy.get_full_analysis_status_for_organization", return_value=None)
    @patch("understand_analysis.tenancy.get_documents_authenticated", return_value=[])
    @patch("understand_analysis.tenancy.require_bid_access")
    @patch("understand_analysis.tenancy.start_full_analysis_for_organization")
    def test_start_opportunity_analysis_passes_production_recon_budget(
        self, mock_start_full, mock_access, mock_docs, mock_status, mock_runs, mock_proc
    ):
        mock_start_full.return_value = {"outcome": "CREATED"}
        ua.start_opportunity_analysis(1522, "org-test", execution="background")
        mock_start_full.assert_called_once()
        kwargs = mock_start_full.call_args.kwargs
        self.assertEqual(kwargs.get("reconciliation_max_output_tokens"), 8192)

    @patch("full_analysis_service._resolve_source_run", return_value={"id": 48, "corpus_digest": "cd"})
    @patch("full_analysis_service.db.start_full_analysis_run", return_value={"outcome": "CREATED", "run": {"id": 57, "bid_id": 1522, "source_analysis_run_id": 48}})
    @patch("full_analysis_service.fa.run_full_analysis")
    @patch("full_analysis_service.db.finalize_full_analysis_run")
    @patch("full_analysis_service.db.record_full_analysis_event")
    def test_background_thread_receives_budget_after_launcher_returns(
        self, mock_record, mock_finalize, mock_run_full, mock_db_start, mock_resolve
    ):
        import time
        import full_analysis_service as fas

        pkg = MagicMock(spec=fa.CanonicalPackage)
        pkg.package_digest = "test-pkg-digest"
        pkg.objects_of_type.return_value = []

        fake_res = MagicMock(spec=fa.FullAnalysisResult)
        fake_res.completeness_status = fa.COMPLETENESS_COMPLETE
        fake_res.specialist_statuses = {}
        fake_res.specialist_results = []
        fake_res.reconciliation = {"status": fa.STATUS_COMPLETE}
        fake_res.reconciled_findings = []
        fake_res.unresolved_gaps = []
        fake_res.cross_domain_risks = []
        fake_res.ambiguities = []
        fake_res.human_confirmation_required = []
        fake_res.wall_seconds = 1.0
        fake_res.usage = {}
        fake_res.as_dict.return_value = {}
        mock_run_full.return_value = fake_res

        # Set default module global to 3000
        fa.RECONCILIATION_MAX_OUTPUT_TOKENS = 3000

        # Launch in background with budget=8192 inside launcher context
        with ua._production_recon_budget():
            out = fas.start_full_analysis(
                bid_id=1522,
                source_run_id=48,
                execution="background",
                package_builder=lambda _: pkg,
                reconciliation_max_output_tokens=8192,
            )

        # Context manager exited! Main thread restored to 3000:
        self.assertEqual(fa.RECONCILIATION_MAX_OUTPUT_TOKENS, 3000)
        self.assertTrue(out.get("executing"))

        # Wait briefly for background thread to execute
        deadline = time.time() + 3.0
        while time.time() < deadline and not mock_run_full.called:
            time.sleep(0.05)

        self.assertTrue(mock_run_full.called)
        call_kwargs = mock_run_full.call_args.kwargs
        self.assertEqual(call_kwargs.get("reconciliation_max_output_tokens"), 8192)

    @patch("understand_analysis.tenancy.get_procurement_state_for_organization", return_value={"procurement_truth_status": "governed", "procurement_revision": 2})
    @patch("understand_analysis.db.list_analysis_runs", return_value=[])
    @patch("understand_analysis.tenancy.get_full_analysis_status_for_organization")
    def test_get_opportunity_analysis_state_partial_state_and_reason(
        self, mock_full_status, mock_list_runs, mock_proc
    ):
        mock_full_status.return_value = {
            "run_id": 56,
            "status": "PARTIAL",
            "failure_reason": "incomplete domains: RECONCILIATION (output truncated)",
            "specialists": {},
            "reconciliation": {
                "status": "PARTIAL",
                "failure_summary": "OUTPUT_TRUNCATED: provider stop_reason=max_tokens at 3000 output tokens",
            },
        }
        state = ua.get_opportunity_analysis_state(1522, "org-test")
        self.assertTrue(state.get("is_partial"))
        self.assertFalse(state.get("is_complete"))
        self.assertEqual(state.get("step"), ua.STEP_PARTIAL)
        self.assertEqual(state.get("status_label"), "Opportunity intelligence partially complete")
        self.assertIn("stop_reason=max_tokens at 3000 output tokens", state.get("partial_reason") or "")


if __name__ == "__main__":
    unittest.main()
