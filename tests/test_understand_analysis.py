"""
tests/test_understand_analysis.py -- Deterministic tests for understand_analysis.py.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

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


if __name__ == "__main__":
    unittest.main()
