"""
tests/test_migration_024_cascade_immutability.py

Deterministic tests for Migration 024: Cascade-Aware Immutability
and the delete_bid_for_organization service boundary.

Proves:
1. Migration 024 SQL schema contract (triggers, functions, cascade-awareness,
   no weakening of immutability).
2. Real PostgreSQL execution test matrix (A through K) verifying actual PostgreSQL
   cascade ordering and immutability trigger behavior.
3. delete_bid_for_organization service boundary authorization, active-run gating,
   and clean parent-bid deletion verification.
"""
import os
import re
import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import database
import tenancy
from tenancy import AccessDeniedError

MIGRATION_024_PATH = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "024_fix_bid_cascade_immutability.sql"
)


def _strip_sql_line_comments(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("--")
    )


class TestMigration024SchemaContract(unittest.TestCase):
    """Static SQL contract assertions for Migration 024."""

    def setUp(self):
        self.raw = MIGRATION_024_PATH.read_text(encoding="utf-8")
        self.code = _strip_sql_line_comments(self.raw).lower()

    def test_migration_file_exists(self):
        self.assertTrue(MIGRATION_024_PATH.exists())

    def test_all_six_cascade_aware_functions_defined(self):
        expected_functions = [
            "public.full_analysis_reject_mutation()",
            "public.check_run_reject_mutation()",
            "public.prevent_applied_change_mutation()",
            "public.prevent_applied_review_mutation()",
            "public.prevent_applied_review_document_mutation()",
            "public.prevent_resolved_conflict_mutation()",
        ]
        for fn in expected_functions:
            self.assertIn(
                f"create or replace function {fn}",
                self.code,
                f"Migration 024 missing {fn}",
            )

    def test_all_triggers_remain_before_update_or_delete(self):
        expected_triggers = [
            ("trg_full_analysis_events_append_only", "full_analysis_events"),
            ("trg_check_run_events_append_only", "check_run_events"),
            ("guard_applied_change_immutability", "procurement_changes"),
            ("guard_applied_review_immutability", "procurement_update_reviews"),
            ("guard_applied_review_document_immutability", "procurement_update_review_documents"),
            ("guard_resolved_conflict_immutability", "procurement_conflicts"),
        ]
        for trigger, table in expected_triggers:
            self.assertIn(f"create trigger {trigger}", self.code)
            idx = self.code.index(f"create trigger {trigger}")
            block = self.code[idx : idx + 250]
            self.assertIn(
                "before update or delete",
                block,
                f"Trigger {trigger} must be BEFORE UPDATE OR DELETE, not weakened",
            )
            self.assertIn(f"on public.{table}", block)

    def test_cascade_checks_parent_bid_existence_on_delete(self):
        """Must check if parent bid still exists when handling DELETE."""
        normalized = re.sub(r"\s+", " ", self.code)
        self.assertIn("select 1 from public.bids where id = old.bid_id", normalized)

    def test_applied_review_document_checks_parent_review_status(self):
        """Review document membership must check parent review status."""
        normalized = re.sub(r"\s+", " ", self.code)
        self.assertIn("select status into v_status from public.procurement_update_reviews where id = old.review_id", normalized)

    def test_preserves_all_original_exception_messages(self):
        for msg in [
            "rows are append-only",
            "rows are immutable",
            "applied_change_immutable",
            "applied_review_immutable",
            "applied_review_document_immutable",
            "resolved_conflict_immutable",
        ]:
            self.assertIn(msg, self.code)


class TestRealPostgresCascadeExecution(unittest.TestCase):
    """Executes the full 11-step matrix (A through K) in a real PostgreSQL engine."""

    def test_real_postgresql_cascade_matrix(self):
        script_path = (
            Path(__file__).resolve().parent.parent
            / "scripts"
            / "test_postgres_cascade_matrix.js"
        )
        self.assertTrue(script_path.exists())

        res = subprocess.run(
            ["node", str(script_path)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            res.returncode,
            0,
            f"Real PostgreSQL test matrix failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}",
        )
        self.assertIn(
            "ALL 11 TESTS (A THROUGH K) PASSED ON REAL POSTGRESQL ENGINE!",
            res.stdout,
        )
        # Verify specific tests reported PASS
        for letter in ["A", "B", "C", "D", "E", "F", "G", "H", "I.1", "I.2", "J", "K"]:
            self.assertIn(f"PASS Test {letter}:", res.stdout)


class TestDeleteBidForOrganization(unittest.TestCase):
    """Unit tests for the delete_bid_for_organization service boundary."""

    def test_rejects_missing_organization_id(self):
        with self.assertRaises(ValueError) as ctx:
            tenancy.delete_bid_for_organization(123, "")
        self.assertIn("explicit organization_id", str(ctx.exception))

    @patch("tenancy.authorize_bid_access")
    def test_rejects_unowned_bid(self, mock_auth):
        mock_auth.return_value = False
        with self.assertRaises(AccessDeniedError):
            tenancy.delete_bid_for_organization(123, "org-other")

    @patch("database.get_client")
    @patch("tenancy.authorize_bid_access")
    def test_fails_when_active_run_exists(self, mock_auth, mock_client):
        mock_auth.return_value = True
        sb = MagicMock()
        mock_client.return_value = sb

        # Active run with status RUNNING
        sb.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": 42, "status": "RUNNING"}]
        )

        with self.assertRaises(RuntimeError) as ctx:
            tenancy.delete_bid_for_organization(123, "org-test")
        self.assertIn("active analysis run 42 has status 'RUNNING'", str(ctx.exception))

    @patch("database.get_client")
    @patch("tenancy.authorize_bid_access")
    def test_succeeds_when_runs_are_terminal(self, mock_auth, mock_client):
        mock_auth.return_value = True
        sb = MagicMock()
        mock_client.return_value = sb

        # Terminal runs
        runs_response = MagicMock(data=[
            {"id": 1, "status": "COMPLETE"},
            {"id": 2, "status": "FAILED"},
            {"id": 3, "status": "PARTIAL"},
            {"id": 4, "status": "STOPPED"},
        ])
        # Post-delete check response: empty (bid gone)
        post_delete_response = MagicMock(data=[])

        sb.table.return_value.select.return_value.eq.return_value.execute.side_effect = [
            runs_response,
            post_delete_response,
        ]

        result = tenancy.delete_bid_for_organization(123, "org-test")
        self.assertTrue(result)

        # Verify parent bid delete was executed with organization scope
        sb.table.assert_any_call("bids")
        sb.table.return_value.delete.return_value.eq.return_value.eq.assert_called_with(
            "organization_id", "org-test"
        )

    @patch("database.get_client")
    @patch("tenancy.authorize_bid_access")
    def test_fails_if_post_delete_verification_detects_bid_remains(self, mock_auth, mock_client):
        mock_auth.return_value = True
        sb = MagicMock()
        mock_client.return_value = sb

        # Terminal runs
        runs_response = MagicMock(data=[{"id": 1, "status": "COMPLETE"}])
        # Post-delete check response: bid still exists!
        post_delete_response = MagicMock(data=[{"id": 123}])

        sb.table.return_value.select.return_value.eq.return_value.execute.side_effect = [
            runs_response,
            post_delete_response,
        ]

        with self.assertRaises(RuntimeError) as ctx:
            tenancy.delete_bid_for_organization(123, "org-test")
        self.assertIn("Deletion failed: bid 123 still exists", str(ctx.exception))

    @patch("tenancy.delete_bid_for_organization")
    def test_database_py_wrapper_delegates_to_tenancy(self, mock_tenancy_delete):
        mock_tenancy_delete.return_value = True
        res = database.delete_bid_for_organization(123, "org-test")
        self.assertTrue(res)
        mock_tenancy_delete.assert_called_once_with(123, "org-test")
