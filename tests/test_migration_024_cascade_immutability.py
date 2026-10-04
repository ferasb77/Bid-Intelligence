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
from tenancy import AccessDeniedError, BidStorageCleanupError


class TestListBidStorageObjects(unittest.TestCase):
    """Tests for recursive, prefix-guarded Supabase Storage listing."""

    def test_list_empty_folder(self):
        client = MagicMock()
        client.storage.from_.return_value.list.return_value = []
        files = tenancy.list_bid_storage_objects(123, client=client, bucket="bid-documents")
        self.assertEqual(files, [])
        client.storage.from_.return_value.list.assert_called_once_with("123")

    def test_list_flat_files_filters_placeholder(self):
        client = MagicMock()
        client.storage.from_.return_value.list.return_value = [
            {"name": "doc1.pdf", "id": "uuid-1"},
            {"name": ".emptyFolderPlaceholder", "id": "uuid-2"},
            {"name": "doc2.docx", "id": "uuid-3"},
        ]
        files = tenancy.list_bid_storage_objects(123, client=client, bucket="bid-documents")
        self.assertEqual(files, ["123/doc1.pdf", "123/doc2.docx"])

    def test_list_nested_folders_recursively(self):
        client = MagicMock()

        def mock_list(folder):
            if folder == "123":
                return [
                    {"name": "source.pdf", "id": "uuid-1"},
                    {"name": "analysis_reports", "id": None},  # folder
                ]
            elif folder == "123/analysis_reports":
                return [
                    {"name": "subfolder", "id": None},  # nested folder
                    {"name": "report.pdf", "id": "uuid-2"},
                ]
            elif folder == "123/analysis_reports/subfolder":
                return [
                    {"name": "deep.pdf", "id": "uuid-3"},
                ]
            return []

        client.storage.from_.return_value.list.side_effect = mock_list
        files = tenancy.list_bid_storage_objects(123, client=client, bucket="bid-documents")
        self.assertEqual(
            files,
            [
                "123/source.pdf",
                "123/analysis_reports/subfolder/deep.pdf",
                "123/analysis_reports/report.pdf",
            ],
        )


class TestDeleteBidForOrganization(unittest.TestCase):
    """Unit tests for the delete_bid_for_organization service boundary."""

    def test_rejects_missing_organization_id(self):
        with self.assertRaises(ValueError) as ctx:
            tenancy.delete_bid_for_organization(123, "")
        self.assertIn("explicit organization_id", str(ctx.exception))

    @patch("tenancy.authorize_bid_access")
    def test_b_wrong_org_access_denied(self, mock_auth):
        mock_auth.return_value = False
        with patch("database.get_client") as mock_client:
            sb = MagicMock()
            mock_client.return_value = sb
            with self.assertRaises(AccessDeniedError):
                tenancy.delete_bid_for_organization(123, "org-other")
            # Verify DB and Storage were never touched
            sb.table.assert_not_called()
            sb.storage.assert_not_called()

    @patch("database.get_client")
    @patch("tenancy.authorize_bid_access")
    def test_c_active_analysis_rejected(self, mock_auth, mock_client):
        mock_auth.return_value = True
        sb = MagicMock()
        mock_client.return_value = sb

        # Active run with status ANALYZING
        sb.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": 42, "status": "ANALYZING"}]
        )

        with self.assertRaises(RuntimeError) as ctx:
            tenancy.delete_bid_for_organization(123, "org-test")
        self.assertIn("active analysis run 42 has status 'ANALYZING'", str(ctx.exception))
        # Verify parent bid delete and storage removal were never called
        sb.table.return_value.delete.assert_not_called()
        sb.storage.from_.return_value.remove.assert_not_called()

    @patch("database.get_client")
    @patch("tenancy.authorize_bid_access")
    def test_d_db_cascade_failure_storage_untouched(self, mock_auth, mock_client):
        mock_auth.return_value = True
        sb = MagicMock()
        mock_client.return_value = sb

        # 1. Runs check: terminal run
        runs_response = MagicMock(data=[{"id": 1, "status": "COMPLETE"}])
        # 2. Storage listing: 1 file
        sb.storage.from_.return_value.list.return_value = [{"name": "file.pdf", "id": "uuid"}]
        # 3. Post-delete bid check: gone
        post_delete_bid = MagicMock(data=[])
        # 4. Cascade child runs check: still has 1 run!
        cascade_child_runs = MagicMock(data=[{"id": 1}])

        sb.table.return_value.select.return_value.eq.return_value.execute.side_effect = [
            runs_response,
            post_delete_bid,
            cascade_child_runs,
        ]

        with self.assertRaises(RuntimeError) as ctx:
            tenancy.delete_bid_for_organization(123, "org-test")
        self.assertIn("Cascade verification failed", str(ctx.exception))
        # Storage remove must NOT be called if cascade verification failed
        sb.storage.from_.return_value.remove.assert_not_called()

    @patch("database.get_client")
    @patch("tenancy.authorize_bid_access")
    def test_e_db_delete_and_storage_succeed(self, mock_auth, mock_client):
        mock_auth.return_value = True
        sb = MagicMock()
        mock_client.return_value = sb

        # 1. Runs check: terminal runs
        runs_response = MagicMock(data=[
            {"id": 1, "status": "COMPLETE"},
            {"id": 2, "status": "FAILED"},
            {"id": 3, "status": "PARTIAL"},
            {"id": 4, "status": "STOPPED"},
        ])
        # 2. Storage listing: initial inventory has 1 file, post-delete listing is empty
        sb.storage.from_.return_value.list.side_effect = [
            [{"name": "rfp.pdf", "id": "uuid-1"}],
            [],  # post-delete verification
        ]
        # 3. Post-delete check response: empty (bid gone)
        post_delete_bid = MagicMock(data=[])
        # 4. Post-delete child runs: empty
        child_runs_response = MagicMock(data=[])

        sb.table.return_value.select.return_value.eq.return_value.execute.side_effect = [
            runs_response,
            post_delete_bid,
            child_runs_response,
        ]

        result = tenancy.delete_bid_for_organization(123, "org-test")
        self.assertEqual(
            result,
            {
                "bid_id": 123,
                "organization_id": "org-test",
                "deleted_db": True,
                "deleted_storage_files": 1,
            },
        )

        # Verify parent bid delete was executed with organization scope
        sb.table.assert_any_call("bids")
        sb.table.return_value.delete.return_value.eq.return_value.eq.assert_called_with(
            "organization_id", "org-test"
        )
        # Verify storage remove was called with inventoried files
        sb.storage.from_.return_value.remove.assert_called_once_with(["123/rfp.pdf"])

    @patch("database.get_client")
    @patch("tenancy.authorize_bid_access")
    def test_f_db_succeeds_storage_fails_raises_cleanup_error(self, mock_auth, mock_client):
        mock_auth.return_value = True
        sb = MagicMock()
        mock_client.return_value = sb

        # 1. Runs check: terminal run
        runs_response = MagicMock(data=[{"id": 1, "status": "COMPLETE"}])
        # 2. Storage inventory
        sb.storage.from_.return_value.list.return_value = [{"name": "rfp.pdf", "id": "uuid-1"}]
        # 3. Post-delete bid check: gone
        post_delete_bid = MagicMock(data=[])
        # 4. Post-delete child runs: gone
        child_runs_response = MagicMock(data=[])

        sb.table.return_value.select.return_value.eq.return_value.execute.side_effect = [
            runs_response,
            post_delete_bid,
            child_runs_response,
        ]

        # Storage remove raises network error
        sb.storage.from_.return_value.remove.side_effect = Exception("Storage connection error")

        with self.assertRaises(BidStorageCleanupError) as ctx:
            tenancy.delete_bid_for_organization(123, "org-test")

        self.assertEqual(ctx.exception.bid_id, 123)
        self.assertEqual(ctx.exception.remaining_files, ["123/rfp.pdf"])
        self.assertIn("Supabase Storage removal failed", str(ctx.exception))
        # Ensure database delete was called only once (no retry)
        self.assertEqual(sb.table.return_value.delete.call_count, 1)

    @patch("database.get_client")
    @patch("tenancy.authorize_bid_access")
    def test_g_fails_if_post_delete_verification_detects_bid_remains(self, mock_auth, mock_client):
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
        sb.storage.from_.return_value.list.return_value = []

        with self.assertRaises(RuntimeError) as ctx:
            tenancy.delete_bid_for_organization(123, "org-test")
        self.assertIn("Deletion failed: bid 123 still exists", str(ctx.exception))
        sb.storage.from_.return_value.remove.assert_not_called()

    @patch("tenancy.delete_bid_for_organization")
    def test_database_py_wrapper_delegates_to_tenancy(self, mock_tenancy_delete):
        mock_tenancy_delete.return_value = {"deleted_db": True}
        res = database.delete_bid_for_organization(123, "org-test")
        self.assertEqual(res, {"deleted_db": True})
        mock_tenancy_delete.assert_called_once_with(123, "org-test")


class TestAppBidDeleteRegression(unittest.TestCase):
    """Regression tests verifying app.py customer delete path integrity."""

    def setUp(self):
        self.app_path = Path(__file__).resolve().parent.parent / "app.py"
        self.app_source = self.app_path.read_text(encoding="utf-8")

    def test_app_does_not_import_or_call_delete_bid(self):
        # Assert delete_bid is not imported from database
        self.assertNotRegex(
            self.app_source,
            r"from\s+database\s+import\s+[^)]*\bdelete_bid\b",
            "app.py must not import delete_bid from database",
        )
        # Assert delete_bid is not called anywhere in app.py
        self.assertNotRegex(
            self.app_source,
            r"(?<!def\s)\bdelete_bid\(",
            "app.py must not call delete_bid()",
        )

    def test_app_delete_ui_routes_through_tenancy_with_confirmation(self):
        # Must call _tenancy.delete_bid_for_organization
        self.assertIn(
            "_tenancy.delete_bid_for_organization(bid_id, _ctx.organization_id)",
            self.app_source,
            "app.py must route bid deletion through _tenancy.delete_bid_for_organization",
        )
        # Must include two-step confirmation copy
        self.assertIn(
            "This permanently deletes this opportunity, its analyses, reports and uploaded documents. This cannot be undone.",
            self.app_source,
            "app.py must display required confirmation warning copy",
        )
        # Must include friendly active-analysis error message
        self.assertIn(
            "This opportunity is currently being analyzed and cannot be deleted until the analysis finishes.",
            self.app_source,
            "app.py must display friendly active-analysis refusal copy",
        )
        # Must have Confirm permanent deletion button
        self.assertIn(
            "Confirm permanent deletion",
            self.app_source,
        )


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
