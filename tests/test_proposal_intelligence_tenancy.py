"""
tests/test_proposal_intelligence_tenancy.py

Proposal Intelligence PI-1: the authorization boundary
(tenancy.run_proposal_intelligence_for_organization) in front of the
EXISTING Proposal Alignment Analyzer, and the authenticated read helpers.
No provider/model call anywhere in this file -- analyst's analyzer is
always patched at the module boundary, never invoked for real.
"""
import unittest
from unittest.mock import MagicMock, patch

import tenancy


def _owning_client(bid_id=8, organization_id="org-1"):
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = \
        MagicMock(data=[{"id": bid_id, "organization_id": organization_id}])
    return sb


def _non_owning_client():
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = \
        MagicMock(data=[])
    return sb


class TestAuthorizationBoundary(unittest.TestCase):

    def test_run_never_calls_get_client_directly(self):
        import inspect
        src = inspect.getsource(tenancy.run_proposal_intelligence_for_organization)
        self.assertNotIn("get_client()", src)

    @patch("tenancy.db.get_client")
    def test_unauthorized_organization_cannot_reach_the_analyzer_at_all(self, mock_get_client):
        mock_get_client.return_value = _non_owning_client()
        with patch("analyst.analyze_proposal_alignment_package") as mock_analyze:
            with self.assertRaises(tenancy.AccessDeniedError):
                tenancy.run_proposal_intelligence_for_organization(
                    8, "org-999-unrelated", package_files=[], requirements=[],
                    rfp_text="ctx", bid_info={"title": "T"})
            mock_analyze.assert_not_called()

    @patch("tenancy.db.get_client")
    def test_unauthorized_organization_never_persists_anything(self, mock_get_client):
        mock_get_client.return_value = _non_owning_client()
        with patch("tenancy.db.create_proposal_intelligence_run") as mock_create_run:
            with self.assertRaises(tenancy.AccessDeniedError):
                tenancy.run_proposal_intelligence_for_organization(
                    8, "org-999-unrelated", package_files=[], requirements=[],
                    rfp_text="ctx", bid_info={"title": "T"})
            mock_create_run.assert_not_called()


class TestSuccessfulRunPersistence(unittest.TestCase):

    def _package_files(self):
        return [{"file_id": "f1", "content_hash": "h1", "included": True, "role": "primary",
                "filename": "Tech.pdf", "package_path": "Tech.pdf", "file_type": "pdf",
                "text": "proposal text", "analyzable": True, "unusable_reason": None,
                "extraction_meta": {}}]

    def _requirements(self):
        return [{"id": 101, "req_id": "R1", "category": "Technical", "description": "Deliver on time"}]

    @patch("tenancy.db.create_proposal_intelligence_findings")
    @patch("tenancy.db.create_proposal_requirement_assessments")
    @patch("tenancy.db.create_proposal_intelligence_run")
    @patch("extractor.build_report_manifest")
    @patch("tenancy.db.create_proposal_package_snapshot")
    @patch("tenancy.db.get_latest_proposal_package_version")
    @patch("tenancy.db.get_proposal_package_snapshot_by_digest")
    @patch("tenancy.db.get_bid_procurement_state")
    @patch("tenancy.db.get_client")
    def test_new_package_creates_a_new_snapshot_then_run_then_assessments_and_findings(
        self, mock_get_client, mock_proc_state, mock_get_snapshot, mock_latest_version,
        mock_create_snapshot, mock_manifest, mock_create_run, mock_create_assessments,
        mock_create_findings,
    ):
        mock_get_client.return_value = _owning_client()
        mock_proc_state.return_value = {"procurement_revision": 3, "procurement_truth_status": "governed"}
        mock_get_snapshot.return_value = None  # no existing snapshot -- must create one
        mock_latest_version.return_value = 0
        mock_manifest.return_value = [{"file_id": "f1", "filename": "Tech.pdf"}]
        mock_create_snapshot.return_value = {"id": 55, "package_version": 1}
        mock_create_run.return_value = {"id": 900, "status": "COMPLETE"}
        mock_create_assessments.return_value = [{"id": 1}]
        mock_create_findings.return_value = []

        alignment_result = {
            "status": "complete", "overall_score": 88.0, "recommendation": "SUBMIT",
            "executive_summary": "Solid.", "strengths": [], "next_steps": [],
            "requirement_coverage": [{"req_id": "R1", "coverage": "Fully Addressed", "confidence": "High",
                                      "evidence_location": "Tech.pdf — Approach", "notes": "on time delivery"}],
            "mandatory_failures": [], "findings": [], "coverage_metadata": {},
        }
        with patch("analyst.analyze_proposal_alignment_package", return_value=alignment_result) as mock_analyze:
            result = tenancy.run_proposal_intelligence_for_organization(
                8, "org-1", package_files=self._package_files(), requirements=self._requirements(),
                rfp_text="ctx", bid_info={"title": "T"}, user_id="u-1")

        mock_analyze.assert_called_once()
        mock_create_snapshot.assert_called_once()
        self.assertEqual(mock_create_snapshot.call_args[0][0]["bid_id"], 8)
        self.assertEqual(mock_create_snapshot.call_args[0][0]["package_version"], 1)

        run_payload = mock_create_run.call_args[0][0]
        self.assertEqual(run_payload["bid_id"], 8)
        self.assertEqual(run_payload["proposal_package_snapshot_id"], 55)
        self.assertEqual(run_payload["based_on_procurement_revision"], 3)
        self.assertEqual(run_payload["based_on_procurement_truth_status"], "governed")
        self.assertEqual(run_payload["status"], "COMPLETE")

        assessments_arg = mock_create_assessments.call_args[0][0]
        self.assertEqual(assessments_arg[0]["run_id"], 900)
        self.assertEqual(assessments_arg[0]["bid_id"], 8)

        self.assertEqual(result["run"], {"id": 900, "status": "COMPLETE"})

    @patch("tenancy.db.get_proposal_package_snapshot_by_digest")
    @patch("tenancy.db.get_bid_procurement_state")
    @patch("tenancy.db.get_client")
    def test_identical_package_reuses_existing_snapshot_never_duplicates(
        self, mock_get_client, mock_proc_state, mock_get_snapshot,
    ):
        mock_get_client.return_value = _owning_client()
        mock_proc_state.return_value = {"procurement_revision": 3, "procurement_truth_status": "governed"}
        mock_get_snapshot.return_value = {"id": 55, "package_version": 1}  # already exists

        with patch("tenancy.db.create_proposal_package_snapshot") as mock_create_snapshot, \
             patch("tenancy.db.create_proposal_intelligence_run",
                  return_value={"id": 901, "status": "INCOMPLETE"}), \
             patch("tenancy.db.create_proposal_requirement_assessments", return_value=[]), \
             patch("tenancy.db.create_proposal_intelligence_findings", return_value=[]), \
             patch("analyst.analyze_proposal_alignment_package",
                  return_value={"status": "incomplete", "reason": "x", "coverage_metadata": {}}):
            tenancy.run_proposal_intelligence_for_organization(
                8, "org-1", package_files=self._package_files(), requirements=self._requirements(),
                rfp_text="ctx", bid_info={"title": "T"})
        mock_create_snapshot.assert_not_called()


class TestFailedRunPersistence(unittest.TestCase):

    def _package_files(self):
        return [{"file_id": "f1", "content_hash": "h1", "included": True, "role": "primary",
                "filename": "Tech.pdf", "package_path": "Tech.pdf", "file_type": "pdf",
                "text": "proposal text", "analyzable": True, "unusable_reason": None,
                "extraction_meta": {}}]

    @patch("tenancy.db.create_proposal_intelligence_findings")
    @patch("tenancy.db.create_proposal_requirement_assessments")
    @patch("tenancy.db.create_proposal_intelligence_run")
    @patch("extractor.build_report_manifest")
    @patch("tenancy.db.create_proposal_package_snapshot")
    @patch("tenancy.db.get_latest_proposal_package_version")
    @patch("tenancy.db.get_proposal_package_snapshot_by_digest")
    @patch("tenancy.db.get_bid_procurement_state")
    @patch("tenancy.db.get_client")
    def test_provider_exception_creates_a_failed_run_with_no_fabricated_findings(
        self, mock_get_client, mock_proc_state, mock_get_snapshot, mock_latest_version,
        mock_create_snapshot, mock_manifest, mock_create_run, mock_create_assessments,
        mock_create_findings,
    ):
        mock_get_client.return_value = _owning_client()
        mock_proc_state.return_value = {"procurement_revision": 3, "procurement_truth_status": "governed"}
        mock_get_snapshot.return_value = None
        mock_latest_version.return_value = 0
        mock_manifest.return_value = []
        mock_create_snapshot.return_value = {"id": 55, "package_version": 1}
        mock_create_run.return_value = {"id": 902, "status": "FAILED"}

        with patch("analyst.analyze_proposal_alignment_package",
                  side_effect=RuntimeError("credit balance too low")):
            with self.assertRaises(RuntimeError):
                tenancy.run_proposal_intelligence_for_organization(
                    8, "org-1", package_files=self._package_files(), requirements=[],
                    rfp_text="ctx", bid_info={"title": "T"})

        # The package snapshot identity DOES already exist (sufficient run
        # identity, per instruction 13) -- a FAILED run row is persisted...
        mock_create_run.assert_called_once()
        failed_payload = mock_create_run.call_args[0][0]
        self.assertEqual(failed_payload["status"], "FAILED")
        self.assertEqual(failed_payload["proposal_package_snapshot_id"], 55)
        self.assertIn("credit balance too low", failed_payload["failure_reason"])
        # ...but no findings/assessments are ever fabricated on failure.
        mock_create_assessments.assert_not_called()
        mock_create_findings.assert_not_called()


class TestAuthenticatedReadHelpers(unittest.TestCase):

    def _client(self, rows):
        client = MagicMock()
        table = client.table.return_value
        table.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = \
            MagicMock(data=rows)
        table.select.return_value.eq.return_value.order.return_value.execute.return_value = \
            MagicMock(data=rows)
        table.select.return_value.eq.return_value.execute.return_value = MagicMock(data=rows)
        return client

    @patch("tenancy.auth_client.get_authenticated_client")
    def test_latest_run_uses_authenticated_client_not_service_role(self, mock_auth_client):
        mock_auth_client.return_value = self._client([{"id": 900, "status": "COMPLETE"}])
        result = tenancy.get_latest_proposal_intelligence_run_authenticated("token-x", 8)
        self.assertEqual(result["id"], 900)
        mock_auth_client.assert_called_once_with("token-x")

    @patch("tenancy.auth_client.get_authenticated_client")
    def test_latest_run_returns_none_when_no_runs_exist(self, mock_auth_client):
        mock_auth_client.return_value = self._client([])
        result = tenancy.get_latest_proposal_intelligence_run_authenticated("token-x", 8)
        self.assertIsNone(result)

    @patch("tenancy.auth_client.get_authenticated_client")
    def test_findings_read_scoped_by_run_id(self, mock_auth_client):
        client = self._client([{"id": 1, "finding_type": "OTHER"}])
        mock_auth_client.return_value = client
        tenancy.get_proposal_intelligence_findings_authenticated("token-x", 900)
        client.table.assert_called_with("proposal_intelligence_findings")


if __name__ == "__main__":
    unittest.main()
