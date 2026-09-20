"""
tests/test_proposal_intelligence_database.py

Proposal Intelligence PI-1: database.py's privileged persistence helpers
(migrations/015_proposal_intelligence.sql). No provider/model call, no
live Supabase connection -- get_client() is always mocked.
"""
import unittest
from unittest.mock import MagicMock, patch

import database as db


class TestAllowlistFiltering(unittest.TestCase):
    """An unexpected extra key must never reach the insert -- same
    discipline as create_model_usage_event's own allowlist."""

    @patch("database.get_client")
    def test_package_snapshot_insert_drops_unknown_keys(self, mock_get_client):
        sb = MagicMock()
        sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": 1}])
        mock_get_client.return_value = sb

        db.create_proposal_package_snapshot({
            "bid_id": 8, "package_version": 1, "package_digest": "abc",
            "manifest": [], "created_by_user_id": "u-1",
            "raw_proposal_text": "SHOULD NEVER BE PERSISTED",
        })
        inserted = sb.table.return_value.insert.call_args[0][0]
        self.assertNotIn("raw_proposal_text", inserted)
        self.assertEqual(inserted["package_digest"], "abc")

    @patch("database.get_client")
    def test_run_insert_drops_unknown_keys(self, mock_get_client):
        sb = MagicMock()
        sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": 900}])
        mock_get_client.return_value = sb

        db.create_proposal_intelligence_run({
            "bid_id": 8, "proposal_package_snapshot_id": 55, "status": "COMPLETE",
            "analysis_version": "proposal-intelligence-v1", "bogus_field": "x",
        })
        inserted = sb.table.return_value.insert.call_args[0][0]
        self.assertNotIn("bogus_field", inserted)

    @patch("database.get_client")
    def test_assessment_bulk_insert_drops_unknown_keys(self, mock_get_client):
        sb = MagicMock()
        sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": 1}])
        mock_get_client.return_value = sb

        db.create_proposal_requirement_assessments([
            {"run_id": 900, "bid_id": 8, "req_id": "R1", "assessment_status": "Fully Addressed",
            "internal_debug_note": "drop me"},
        ])
        inserted = sb.table.return_value.insert.call_args[0][0]
        self.assertNotIn("internal_debug_note", inserted[0])

    @patch("database.get_client")
    def test_finding_bulk_insert_drops_unknown_keys(self, mock_get_client):
        sb = MagicMock()
        sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": 1}])
        mock_get_client.return_value = sb

        db.create_proposal_intelligence_findings([
            {"run_id": 900, "bid_id": 8, "finding_type": "OTHER", "title": "t", "leaked": "x"},
        ])
        inserted = sb.table.return_value.insert.call_args[0][0]
        self.assertNotIn("leaked", inserted[0])


class TestEmptyBulkInsertsAreNoOps(unittest.TestCase):

    @patch("database.get_client")
    def test_empty_assessments_list_never_calls_insert(self, mock_get_client):
        result = db.create_proposal_requirement_assessments([])
        self.assertEqual(result, [])
        mock_get_client.assert_not_called()

    @patch("database.get_client")
    def test_empty_findings_list_never_calls_insert(self, mock_get_client):
        result = db.create_proposal_intelligence_findings([])
        self.assertEqual(result, [])
        mock_get_client.assert_not_called()


class TestImmutability(unittest.TestCase):
    """No update_*/delete_* function exists for any of the four PI tables
    -- immutability enforced by the absence of a code path, matching
    section_reviews/model_usage_events."""

    def test_no_mutation_functions_exist(self):
        forbidden_prefixes = ("update_proposal_", "delete_proposal_")
        offenders = [name for name in dir(db) if name.startswith(forbidden_prefixes)]
        self.assertEqual(offenders, [])


class TestSnapshotIdempotentReuseLookup(unittest.TestCase):

    @patch("database.get_client")
    def test_lookup_by_digest_queries_both_bid_and_digest(self, mock_get_client):
        sb = MagicMock()
        chain = sb.table.return_value.select.return_value.eq.return_value.eq.return_value
        chain.execute.return_value = MagicMock(data=[{"id": 55}])
        mock_get_client.return_value = sb

        result = db.get_proposal_package_snapshot_by_digest(8, "digest-abc")
        self.assertEqual(result, {"id": 55})

    @patch("database.get_client")
    def test_lookup_returns_none_when_absent(self, mock_get_client):
        sb = MagicMock()
        chain = sb.table.return_value.select.return_value.eq.return_value.eq.return_value
        chain.execute.return_value = MagicMock(data=[])
        mock_get_client.return_value = sb

        result = db.get_proposal_package_snapshot_by_digest(8, "digest-missing")
        self.assertIsNone(result)

    @patch("database.get_client")
    def test_latest_version_defaults_to_zero_for_a_new_bid(self, mock_get_client):
        sb = MagicMock()
        chain = sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value
        chain.execute.return_value = MagicMock(data=[])
        mock_get_client.return_value = sb

        self.assertEqual(db.get_latest_proposal_package_version(8), 0)


if __name__ == "__main__":
    unittest.main()
