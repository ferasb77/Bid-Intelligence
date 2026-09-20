"""
tests/test_proposal_intelligence_tenancy.py

Proposal Intelligence PI-1.1: the authorization boundary
(tenancy.run_proposal_intelligence_for_organization) in front of the
EXISTING Proposal Alignment Analyzer, now persisting atomically via
database.create_proposal_intelligence_bundle, plus the authenticated read
helpers including the new latest-USABLE-run distinction. No provider/
model call anywhere in this file -- analyst's analyzer is always patched
at the module boundary, never invoked for real.
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
        with patch("tenancy.db.create_proposal_intelligence_bundle") as mock_bundle:
            with self.assertRaises(tenancy.AccessDeniedError):
                tenancy.run_proposal_intelligence_for_organization(
                    8, "org-999-unrelated", package_files=[], requirements=[],
                    rfp_text="ctx", bid_info={"title": "T"})
            mock_bundle.assert_not_called()


class TestAtomicPersistence(unittest.TestCase):

    def _package_files(self):
        return [{"file_id": "f1", "content_hash": "h1", "included": True, "role": "primary",
                "filename": "Tech.pdf", "package_path": "Tech.pdf", "file_type": "pdf",
                "text": "proposal text", "analyzable": True, "unusable_reason": None,
                "extraction_meta": {}}]

    def _full_manifest(self):
        # Includes an EXCLUDED file the analyzer never sees, proving
        # full_package_manifest is genuinely distinct from package_files.
        return self._package_files() + [
            {"file_id": "f2", "content_hash": "h2", "included": False, "role": None,
            "filename": "Excluded.pdf", "package_path": "Excluded.pdf", "file_type": "pdf",
            "text": "excluded text", "analyzable": True, "unusable_reason": None,
            "extraction_meta": {}}]

    def _requirements(self):
        return [{"id": 101, "req_id": "R1", "category": "Technical", "description": "Deliver on time"}]

    @patch("tenancy.db.create_proposal_intelligence_bundle")
    @patch("extractor.build_report_manifest")
    @patch("tenancy.db.get_or_create_proposal_package_snapshot")
    @patch("tenancy.db.get_bid_procurement_state")
    @patch("tenancy.db.get_client")
    def test_run_and_children_persist_through_one_bundle_call(
        self, mock_get_client, mock_proc_state, mock_get_snapshot, mock_manifest, mock_bundle,
    ):
        mock_get_client.return_value = _owning_client()
        mock_proc_state.return_value = {"procurement_revision": 3, "procurement_truth_status": "governed"}
        mock_get_snapshot.return_value = {"id": 55, "package_version": 1}
        mock_manifest.return_value = [{"file_id": "f1", "filename": "Tech.pdf"},
                                      {"file_id": "f2", "filename": "Excluded.pdf"}]
        mock_bundle.return_value = {"id": 900, "status": "COMPLETE"}

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
                rfp_text="ctx", bid_info={"title": "T"}, full_package_manifest=self._full_manifest(),
                user_id="u-1")

        mock_analyze.assert_called_once()
        # Analyzer received ONLY the included subset, never the excluded file.
        analyzer_files = mock_analyze.call_args[1]["package_files"]
        self.assertEqual([f["file_id"] for f in analyzer_files], ["f1"])

        mock_bundle.assert_called_once()
        run_arg, assessments_arg, findings_arg = mock_bundle.call_args[0]
        self.assertEqual(run_arg["bid_id"], 8)
        self.assertEqual(run_arg["proposal_package_snapshot_id"], 55)
        self.assertEqual(run_arg["status"], "COMPLETE")
        self.assertEqual(assessments_arg[0]["req_id"], "R1")
        self.assertEqual(result["run"], {"id": 900, "status": "COMPLETE"})

    @patch("tenancy.db.create_proposal_intelligence_bundle")
    @patch("extractor.build_report_manifest")
    @patch("tenancy.db.get_or_create_proposal_package_snapshot")
    @patch("tenancy.db.get_bid_procurement_state")
    @patch("tenancy.db.get_client")
    def test_full_manifest_digest_computed_over_full_list_not_included_only(
        self, mock_get_client, mock_proc_state, mock_get_snapshot, mock_manifest, mock_bundle,
    ):
        mock_get_client.return_value = _owning_client()
        mock_proc_state.return_value = {"procurement_revision": 3, "procurement_truth_status": "governed"}
        mock_get_snapshot.return_value = {"id": 55}
        mock_manifest.return_value = []
        mock_bundle.return_value = {"id": 900, "status": "COMPLETE"}

        with patch("analyst.analyze_proposal_alignment_package",
                  return_value={"status": "complete", "coverage_metadata": {}}):
            tenancy.run_proposal_intelligence_for_organization(
                8, "org-1", package_files=self._package_files(), requirements=self._requirements(),
                rfp_text="ctx", bid_info={"title": "T"}, full_package_manifest=self._full_manifest())

        # build_report_manifest (and therefore the digest, computed
        # earlier in the same function from the same source) was built
        # from the FULL manifest (2 files), not just the included subset (1 file).
        mock_manifest.assert_called_once()
        self.assertEqual(len(mock_manifest.call_args[0][0]), 2)

    @patch("tenancy.db.create_proposal_intelligence_bundle")
    @patch("extractor.build_report_manifest")
    @patch("tenancy.db.get_or_create_proposal_package_snapshot")
    @patch("tenancy.db.get_bid_procurement_state")
    @patch("tenancy.db.get_client")
    def test_full_package_manifest_defaults_to_package_files_when_omitted(
        self, mock_get_client, mock_proc_state, mock_get_snapshot, mock_manifest, mock_bundle,
    ):
        mock_get_client.return_value = _owning_client()
        mock_proc_state.return_value = {"procurement_revision": 3, "procurement_truth_status": "governed"}
        mock_get_snapshot.return_value = {"id": 55}
        mock_manifest.return_value = []
        mock_bundle.return_value = {"id": 900, "status": "COMPLETE"}

        with patch("analyst.analyze_proposal_alignment_package",
                  return_value={"status": "complete", "coverage_metadata": {}}):
            tenancy.run_proposal_intelligence_for_organization(
                8, "org-1", package_files=self._package_files(), requirements=self._requirements(),
                rfp_text="ctx", bid_info={"title": "T"})  # no full_package_manifest passed
        self.assertEqual(len(mock_manifest.call_args[0][0]), 1)

    @patch("tenancy.db.create_proposal_intelligence_bundle")
    @patch("extractor.build_report_manifest")
    @patch("tenancy.db.get_or_create_proposal_package_snapshot")
    @patch("tenancy.db.get_bid_procurement_state")
    @patch("tenancy.db.get_client")
    def test_started_at_precedes_completed_at_and_both_are_real(
        self, mock_get_client, mock_proc_state, mock_get_snapshot, mock_manifest, mock_bundle,
    ):
        mock_get_client.return_value = _owning_client()
        mock_proc_state.return_value = {"procurement_revision": 3, "procurement_truth_status": "governed"}
        mock_get_snapshot.return_value = {"id": 55}
        mock_manifest.return_value = []
        mock_bundle.return_value = {"id": 900, "status": "COMPLETE"}

        with patch("analyst.analyze_proposal_alignment_package",
                  return_value={"status": "complete", "coverage_metadata": {}}):
            tenancy.run_proposal_intelligence_for_organization(
                8, "org-1", package_files=self._package_files(), requirements=[],
                rfp_text="ctx", bid_info={"title": "T"})

        run_arg = mock_bundle.call_args[0][0]
        self.assertIsNotNone(run_arg["started_at"])
        self.assertIsNotNone(run_arg["completed_at"])
        self.assertLessEqual(run_arg["started_at"], run_arg["completed_at"])


class TestSnapshotReuse(unittest.TestCase):

    @patch("tenancy.db.create_proposal_intelligence_bundle")
    @patch("extractor.build_report_manifest")
    @patch("tenancy.db.get_or_create_proposal_package_snapshot")
    @patch("tenancy.db.get_bid_procurement_state")
    @patch("tenancy.db.get_client")
    def test_snapshot_creation_delegated_to_the_atomic_get_or_create(
        self, mock_get_client, mock_proc_state, mock_get_snapshot, mock_manifest, mock_bundle,
    ):
        """No separate lookup-then-insert from tenancy.py -- the race this
        function exists to close (PI-1.1 instruction 4) cannot be closed
        if the orchestration layer does its own two-step logic."""
        mock_get_client.return_value = _owning_client()
        mock_proc_state.return_value = {"procurement_revision": 3, "procurement_truth_status": "governed"}
        mock_get_snapshot.return_value = {"id": 55, "package_version": 1}
        mock_manifest.return_value = []
        mock_bundle.return_value = {"id": 901, "status": "INCOMPLETE"}

        with patch("analyst.analyze_proposal_alignment_package",
                  return_value={"status": "incomplete", "reason": "x", "coverage_metadata": {}}):
            tenancy.run_proposal_intelligence_for_organization(
                8, "org-1", package_files=[], requirements=[], rfp_text="ctx", bid_info={"title": "T"})
        mock_get_snapshot.assert_called_once()


class TestFailedRunPersistence(unittest.TestCase):

    def _package_files(self):
        return [{"file_id": "f1", "content_hash": "h1", "included": True, "role": "primary",
                "filename": "Tech.pdf", "package_path": "Tech.pdf", "file_type": "pdf",
                "text": "proposal text", "analyzable": True, "unusable_reason": None,
                "extraction_meta": {}}]

    @patch("tenancy.db.create_proposal_intelligence_bundle")
    @patch("extractor.build_report_manifest")
    @patch("tenancy.db.get_or_create_proposal_package_snapshot")
    @patch("tenancy.db.get_bid_procurement_state")
    @patch("tenancy.db.get_client")
    def test_provider_exception_creates_a_failed_run_with_no_fabricated_findings(
        self, mock_get_client, mock_proc_state, mock_get_snapshot, mock_manifest, mock_bundle,
    ):
        mock_get_client.return_value = _owning_client()
        mock_proc_state.return_value = {"procurement_revision": 3, "procurement_truth_status": "governed"}
        mock_get_snapshot.return_value = {"id": 55}
        mock_manifest.return_value = []
        mock_bundle.return_value = {"id": 902, "status": "FAILED"}

        with patch("analyst.analyze_proposal_alignment_package",
                  side_effect=RuntimeError("credit balance too low")):
            with self.assertRaises(RuntimeError):
                tenancy.run_proposal_intelligence_for_organization(
                    8, "org-1", package_files=self._package_files(), requirements=[],
                    rfp_text="ctx", bid_info={"title": "T"})

        mock_bundle.assert_called_once()
        failed_run_arg = mock_bundle.call_args[0][0]
        self.assertEqual(failed_run_arg["status"], "FAILED")
        self.assertEqual(failed_run_arg["proposal_package_snapshot_id"], 55)
        self.assertIn("credit balance too low", failed_run_arg["failure_reason"])
        self.assertIsNotNone(failed_run_arg["started_at"])
        self.assertIsNotNone(failed_run_arg["completed_at"])
        # No assessments/findings positional args were passed at all for
        # the failure path -- nothing fabricated on failure.
        call_args = mock_bundle.call_args[0]
        self.assertEqual(len(call_args), 1)


class TestAuthenticatedReadHelpers(unittest.TestCase):

    def _client(self, rows):
        client = MagicMock()
        table = client.table.return_value
        table.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=rows)
        table.select.return_value.eq.return_value.order.return_value.order.return_value.limit.return_value.execute.return_value = \
            MagicMock(data=rows)
        table.select.return_value.eq.return_value.in_.return_value.order.return_value.order.return_value.limit.return_value.execute.return_value = \
            MagicMock(data=rows)
        table.select.return_value.eq.return_value.order.return_value.order.return_value.execute.return_value = MagicMock(data=rows)
        table.select.return_value.eq.return_value.execute.return_value = MagicMock(data=rows)
        return client

    @patch("tenancy.auth_client.get_authenticated_client")
    def test_latest_run_of_any_status_uses_authenticated_client(self, mock_auth_client):
        mock_auth_client.return_value = self._client([{"id": 900, "status": "FAILED"}])
        result = tenancy.get_latest_proposal_intelligence_run_authenticated("token-x", 8)
        self.assertEqual(result["status"], "FAILED")
        q = mock_auth_client.return_value.table.return_value.select.return_value.eq.return_value
        q.order.assert_called_once_with("created_at", desc=True)
        q.order.return_value.order.assert_called_once_with("id", desc=True)
        mock_auth_client.assert_called_once_with("token-x")

    @patch("tenancy.auth_client.get_authenticated_client")
    def test_latest_usable_run_filters_by_status(self, mock_auth_client):
        client = self._client([{"id": 899, "status": "COMPLETE"}])
        mock_auth_client.return_value = client
        result = tenancy.get_latest_usable_proposal_intelligence_run_authenticated("token-x", 8)
        self.assertEqual(result["id"], 899)
        q = client.table.return_value.select.return_value.eq.return_value.in_.return_value
        q.order.assert_called_once_with("created_at", desc=True)
        q.order.return_value.order.assert_called_once_with("id", desc=True)
        client.table.return_value.select.return_value.eq.return_value.in_.assert_called_once_with(
            "status", ["COMPLETE", "INCOMPLETE"])

    @patch("tenancy.auth_client.get_authenticated_client")
    def test_latest_usable_run_returns_none_when_none_usable(self, mock_auth_client):
        mock_auth_client.return_value = self._client([])
        self.assertIsNone(tenancy.get_latest_usable_proposal_intelligence_run_authenticated("token-x", 8))

    @patch("tenancy.auth_client.get_authenticated_client")
    def test_snapshot_by_id_scoped_to_bid(self, mock_auth_client):
        client = self._client([{"id": 55, "bid_id": 8, "manifest": [{"file_id": "f1"}]}])
        mock_auth_client.return_value = client
        result = tenancy.get_proposal_package_snapshot_authenticated("token-x", 8, 55)
        self.assertEqual(result["id"], 55)

    @patch("tenancy.auth_client.get_authenticated_client")
    def test_findings_read_scoped_by_run_id(self, mock_auth_client):
        client = self._client([{"id": 1, "finding_type": "OTHER"}])
        mock_auth_client.return_value = client
        tenancy.get_proposal_intelligence_findings_authenticated("token-x", 900)
        client.table.assert_called_with("proposal_intelligence_findings")


if __name__ == "__main__":
    unittest.main()
