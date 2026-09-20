"""
tests/test_proposal_intelligence_database.py

Proposal Intelligence PI-1.1: database.py's atomic, concurrency-safe
persistence helpers (migrations/015_proposal_intelligence.sql). No
provider/model call, no live Supabase connection -- get_client() is
always mocked. Migration 015 is NOT applied, so true database-enforced
atomicity/cross-bid-integrity cannot be exercised live this phase; these
tests prove (a) the Python layer calls the atomic RPC boundary rather
than issuing multiple independent inserts, and (b) the migration's own
SQL text expresses the intended composite-FK/atomic-function DDL (PI-1.1
instruction 2's "test the exact DDL intent").
"""
import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import database as db

_MIGRATION_015 = (Path(__file__).resolve().parents[1] / "migrations"
                 / "015_proposal_intelligence.sql").read_text(encoding="utf-8")


class TestNonAtomicWritePathRemoved(unittest.TestCase):
    """The old three-independent-insert functions must no longer exist --
    proves the non-atomic path was actually removed, not just
    supplemented by the new one."""

    def test_old_separate_insert_functions_are_gone(self):
        for name in ("create_proposal_package_snapshot", "create_proposal_intelligence_run",
                    "create_proposal_requirement_assessments", "create_proposal_intelligence_findings",
                    "get_proposal_package_snapshot_by_digest", "get_latest_proposal_package_version"):
            self.assertFalse(hasattr(db, name), f"{name} should have been replaced by the atomic RPC boundary")

    def test_no_mutation_functions_exist(self):
        forbidden_prefixes = ("update_proposal_", "delete_proposal_")
        offenders = [name for name in dir(db) if name.startswith(forbidden_prefixes)]
        self.assertEqual(offenders, [])


class TestAtomicBundlePersistence(unittest.TestCase):

    @patch("database.get_client")
    def test_bundle_is_a_single_rpc_call_not_three_inserts(self, mock_get_client):
        sb = MagicMock()
        sb.rpc.return_value.execute.return_value = MagicMock(
            data=[{"id": 900, "status": "COMPLETE", "bid_id": 8}])
        mock_get_client.return_value = sb

        db.create_proposal_intelligence_bundle(
            {"bid_id": 8, "proposal_package_snapshot_id": 55, "analysis_version": "v1", "status": "COMPLETE"},
            assessments=[{"req_id": "R1", "assessment_status": "Fully Addressed"}],
            findings=[{"finding_type": "OTHER", "title": "t"}],
        )
        sb.rpc.assert_called_once()
        self.assertEqual(sb.rpc.call_args[0][0], "create_proposal_intelligence_bundle")
        # Never falls back to direct .table(...).insert(...) for these rows.
        sb.table.assert_not_called()

    @patch("database.get_client")
    def test_bundle_payload_never_includes_run_id_or_bid_id_on_children(self, mock_get_client):
        """The Python allowlist for assessments/findings deliberately
        excludes run_id/bid_id -- the SQL function supplies both itself,
        from the run it just created, never from caller-supplied child
        payloads (defense in depth alongside the composite FK)."""
        sb = MagicMock()
        sb.rpc.return_value.execute.return_value = MagicMock(data=[{"id": 900}])
        mock_get_client.return_value = sb

        db.create_proposal_intelligence_bundle(
            {"bid_id": 8, "proposal_package_snapshot_id": 55, "analysis_version": "v1", "status": "COMPLETE"},
            assessments=[{"run_id": 999, "bid_id": 999, "req_id": "R1", "assessment_status": "Fully Addressed"}],
            findings=[{"run_id": 999, "bid_id": 999, "finding_type": "OTHER", "title": "t"}],
        )
        params = sb.rpc.call_args[0][1]
        self.assertNotIn("run_id", params["p_assessments"][0])
        self.assertNotIn("bid_id", params["p_assessments"][0])
        self.assertNotIn("run_id", params["p_findings"][0])
        self.assertNotIn("bid_id", params["p_findings"][0])

    @patch("database.get_client")
    def test_empty_assessments_and_findings_still_call_rpc_once(self, mock_get_client):
        sb = MagicMock()
        sb.rpc.return_value.execute.return_value = MagicMock(data=[{"id": 901}])
        mock_get_client.return_value = sb

        db.create_proposal_intelligence_bundle(
            {"bid_id": 8, "proposal_package_snapshot_id": 55, "analysis_version": "v1", "status": "FAILED"})
        sb.rpc.assert_called_once()
        params = sb.rpc.call_args[0][1]
        self.assertEqual(params["p_assessments"], [])
        self.assertEqual(params["p_findings"], [])

    @patch("database.get_client")
    def test_rpc_response_unwrapping_handles_list_and_bare_dict(self, mock_get_client):
        sb = MagicMock()
        mock_get_client.return_value = sb

        sb.rpc.return_value.execute.return_value = MagicMock(data=[{"id": 1}])
        self.assertEqual(db.create_proposal_intelligence_bundle(
            {"bid_id": 8, "proposal_package_snapshot_id": 55, "analysis_version": "v1", "status": "COMPLETE"}),
            {"id": 1})

        sb.rpc.return_value.execute.return_value = MagicMock(data={"id": 2})
        self.assertEqual(db.create_proposal_intelligence_bundle(
            {"bid_id": 8, "proposal_package_snapshot_id": 55, "analysis_version": "v1", "status": "COMPLETE"}),
            {"id": 2})

        sb.rpc.return_value.execute.return_value = MagicMock(data=[])
        self.assertIsNone(db.create_proposal_intelligence_bundle(
            {"bid_id": 8, "proposal_package_snapshot_id": 55, "analysis_version": "v1", "status": "COMPLETE"}))


class TestSnapshotGetOrCreateIsAnRpcCall(unittest.TestCase):

    @patch("database.get_client")
    def test_get_or_create_calls_the_concurrency_safe_function(self, mock_get_client):
        sb = MagicMock()
        sb.rpc.return_value.execute.return_value = MagicMock(
            data=[{"id": 55, "bid_id": 8, "package_version": 1, "package_digest": "abc"}])
        mock_get_client.return_value = sb

        result = db.get_or_create_proposal_package_snapshot(8, "abc", [{"file_id": "f1"}], created_by_user_id="u-1")
        sb.rpc.assert_called_once_with("get_or_create_proposal_package_snapshot", {
            "p_bid_id": 8, "p_package_digest": "abc", "p_manifest": [{"file_id": "f1"}],
            "p_created_by_user_id": "u-1",
        })
        self.assertEqual(result["id"], 55)

    @patch("database.get_client")
    def test_never_issues_a_separate_select_then_insert_from_python(self, mock_get_client):
        """The race this function exists to close cannot be closed if
        Python does its own SELECT-then-INSERT -- there must be exactly
        one call into the database layer."""
        sb = MagicMock()
        sb.rpc.return_value.execute.return_value = MagicMock(data=[{"id": 55}])
        mock_get_client.return_value = sb

        db.get_or_create_proposal_package_snapshot(8, "abc", [])
        sb.table.assert_not_called()
        self.assertEqual(sb.rpc.call_count, 1)


class TestLatestUsableRun(unittest.TestCase):

    @patch("database.get_client")
    def test_filters_to_complete_and_incomplete_only(self, mock_get_client):
        sb = MagicMock()
        chain = sb.table.return_value.select.return_value.eq.return_value.in_.return_value.order.return_value.limit.return_value
        chain.execute.return_value = MagicMock(data=[{"id": 5, "status": "COMPLETE"}])
        mock_get_client.return_value = sb

        result = db.get_latest_usable_proposal_intelligence_run(8)
        self.assertEqual(result["id"], 5)
        sb.table.return_value.select.return_value.eq.return_value.in_.assert_called_once_with(
            "status", ["COMPLETE", "INCOMPLETE"])

    @patch("database.get_client")
    def test_returns_none_when_only_failed_runs_exist(self, mock_get_client):
        sb = MagicMock()
        chain = sb.table.return_value.select.return_value.eq.return_value.in_.return_value.order.return_value.limit.return_value
        chain.execute.return_value = MagicMock(data=[])
        mock_get_client.return_value = sb

        self.assertIsNone(db.get_latest_usable_proposal_intelligence_run(8))

    @patch("database.get_client")
    def test_latest_run_of_any_status_still_available_separately(self, mock_get_client):
        sb = MagicMock()
        chain = sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value
        chain.execute.return_value = MagicMock(data=[{"id": 6, "status": "FAILED"}])
        mock_get_client.return_value = sb

        result = db.get_latest_proposal_intelligence_run(8)
        self.assertEqual(result["status"], "FAILED")


class TestMigrationDDLIntent(unittest.TestCase):
    """PI-1.1 instruction 2: 'Test the exact DDL intent.' Migration 015 is
    not applied live, so these assert the migration FILE's own text
    expresses the intended composite-FK/atomic-function shape -- not that
    Postgres actually enforces it (unverifiable without a live apply)."""

    def test_snapshot_table_has_composite_unique_id_bid_id(self):
        self.assertIn("unique (id, bid_id)", _MIGRATION_015)

    def test_run_table_has_composite_fk_to_snapshot(self):
        self.assertRegex(
            _MIGRATION_015,
            re.compile(r"foreign key\s*\(proposal_package_snapshot_id,\s*bid_id\)\s*"
                      r"references proposal_package_snapshots\s*\(id,\s*bid_id\)", re.IGNORECASE))

    def test_assessment_table_has_composite_fk_to_run(self):
        matches = re.findall(
            r"foreign key\s*\(run_id,\s*bid_id\)\s*references proposal_intelligence_runs\s*\(id,\s*bid_id\)",
            _MIGRATION_015, re.IGNORECASE)
        self.assertGreaterEqual(len(matches), 2)  # assessments AND findings tables

    def test_no_single_column_fk_from_run_to_snapshot(self):
        """The old single-column FK on proposal_package_snapshot_id must
        be gone -- only the composite FK should govern that column now."""
        self.assertNotRegex(
            _MIGRATION_015,
            re.compile(r"proposal_package_snapshot_id\s+bigint not null references proposal_package_snapshots\(id\)"))

    def test_no_single_column_fk_from_children_to_run(self):
        self.assertNotRegex(
            _MIGRATION_015,
            re.compile(r"run_id\s+bigint not null references proposal_intelligence_runs\(id\)"))

    def test_atomic_bundle_function_exists_and_is_service_role_only(self):
        self.assertIn("create_proposal_intelligence_bundle", _MIGRATION_015)
        self.assertIn("revoke all on function public.create_proposal_intelligence_bundle", _MIGRATION_015)
        self.assertIn("grant execute on function public.create_proposal_intelligence_bundle", _MIGRATION_015)
        self.assertIn("to service_role", _MIGRATION_015)

    def test_snapshot_get_or_create_function_exists_and_is_service_role_only(self):
        self.assertIn("get_or_create_proposal_package_snapshot", _MIGRATION_015)
        self.assertIn("revoke all on function public.get_or_create_proposal_package_snapshot", _MIGRATION_015)

    def test_snapshot_function_uses_advisory_lock_not_a_distributed_lock_service(self):
        self.assertIn("pg_advisory_xact_lock", _MIGRATION_015)

    def test_bundle_function_never_issues_an_update_statement(self):
        # Extract just the bundle function body to avoid false positives
        # from unrelated UPDATE-shaped comments elsewhere in the file.
        start = _MIGRATION_015.index("create or replace function public.create_proposal_intelligence_bundle")
        end = _MIGRATION_015.index("revoke all on function public.create_proposal_intelligence_bundle")
        body = _MIGRATION_015[start:end]
        self.assertNotIn("update public.", body.lower())
        self.assertNotIn("delete from", body.lower())

    def test_rls_comment_correctly_attributes_protection_to_policy_absence_not_grants(self):
        """PI-1.1 instruction 11: the comment must say RLS-enabled-plus-
        no-write-policy is the mechanism, not 'absence of a table GRANT'."""
        self.assertIn("ABSENCE OF A WRITE POLICY", _MIGRATION_015)
        self.assertNotIn("absence of any grant", _MIGRATION_015)


if __name__ == "__main__":
    unittest.main()
