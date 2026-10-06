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
from tenancy import (
    AccessDeniedError,
    BidStorageCleanupError,
    BidStorageInventoryError,
)


class TestListBidStorageObjects(unittest.TestCase):
    """Tests for recursive, prefix-guarded Supabase Storage listing with fail-closed semantics."""

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

    def test_list_root_failure_raises_inventory_error(self):
        client = MagicMock()
        client.storage.from_.return_value.list.side_effect = Exception("Storage API unavailable")
        with self.assertRaises(BidStorageInventoryError) as ctx:
            tenancy.list_bid_storage_objects(123, client=client, bucket="bid-documents")
        self.assertEqual(ctx.exception.bid_id, 123)
        self.assertIn("Failed to list Supabase Storage objects", str(ctx.exception))
        self.assertIn("Storage API unavailable", str(ctx.exception))

    def test_list_nested_failure_raises_inventory_error(self):
        client = MagicMock()

        def mock_list(folder):
            if folder == "123":
                return [{"name": "analysis_reports", "id": None}]
            elif folder == "123/analysis_reports":
                raise Exception("Storage 500 on nested folder")
            return []

        client.storage.from_.return_value.list.side_effect = mock_list
        with self.assertRaises(BidStorageInventoryError) as ctx:
            tenancy.list_bid_storage_objects(123, client=client, bucket="bid-documents")
        self.assertEqual(ctx.exception.bid_id, 123)
        self.assertIn("folder '123/analysis_reports'", str(ctx.exception))
        self.assertIn("Storage 500 on nested folder", str(ctx.exception))


class TestDeleteBidForOrganization(unittest.TestCase):
    """Unit tests for the delete_bid_for_organization service boundary."""

    def test_rejects_missing_organization_id(self):
        with self.assertRaises(ValueError) as ctx:
            tenancy.delete_bid_for_organization(123, "")
        self.assertIn("explicit organization_id", str(ctx.exception))

    @patch("database.get_client")
    @patch("tenancy.authorize_bid_access")
    def test_a_root_storage_list_failure_aborts_deletion(self, mock_auth, mock_client):
        mock_auth.return_value = True
        sb = MagicMock()
        mock_client.return_value = sb

        # Terminal runs
        sb.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": 1, "status": "COMPLETE"}]
        )
        # Storage listing fails at root
        sb.storage.from_.return_value.list.side_effect = Exception("Root storage timeout")

        with self.assertRaises(BidStorageInventoryError) as ctx:
            tenancy.delete_bid_for_organization(123, "org-test")

        self.assertEqual(ctx.exception.bid_id, 123)
        # DB delete must NOT be called
        sb.table.return_value.delete.assert_not_called()
        # Storage remove must NOT be called
        sb.storage.from_.return_value.remove.assert_not_called()

    @patch("database.get_client")
    @patch("tenancy.authorize_bid_access")
    def test_b_nested_storage_list_failure_aborts_deletion(self, mock_auth, mock_client):
        mock_auth.return_value = True
        sb = MagicMock()
        mock_client.return_value = sb

        # Terminal runs
        sb.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": 1, "status": "COMPLETE"}]
        )
        # Root lists subfolder, subfolder fails
        def mock_list(folder):
            if folder == "123":
                return [{"name": "analysis_reports", "id": None}]
            raise Exception("Nested folder storage failure")

        sb.storage.from_.return_value.list.side_effect = mock_list

        with self.assertRaises(BidStorageInventoryError) as ctx:
            tenancy.delete_bid_for_organization(123, "org-test")

        self.assertEqual(ctx.exception.bid_id, 123)
        # DB delete must NOT be called
        sb.table.return_value.delete.assert_not_called()
        # Storage remove must NOT be called
        sb.storage.from_.return_value.remove.assert_not_called()

    @patch("database.get_client")
    @patch("tenancy.authorize_bid_access")
    def test_c_successful_empty_prefix_allows_db_deletion(self, mock_auth, mock_client):
        mock_auth.return_value = True
        sb = MagicMock()
        mock_client.return_value = sb

        runs_response = MagicMock(data=[{"id": 1, "status": "COMPLETE"}])
        post_delete_bid = MagicMock(data=[])
        child_runs_response = MagicMock(data=[])

        sb.table.return_value.select.return_value.eq.return_value.execute.side_effect = [
            runs_response,
            post_delete_bid,
            child_runs_response,
        ]
        # Empty prefix on pre-inventory and post-delete verification
        sb.storage.from_.return_value.list.return_value = []

        result = tenancy.delete_bid_for_organization(123, "org-test")
        self.assertEqual(
            result,
            {
                "bid_id": 123,
                "organization_id": "org-test",
                "deleted_db": True,
                "deleted_storage_files": 0,
            },
        )
        # DB delete was called with org scope
        sb.table.assert_any_call("bids")
        sb.table.return_value.delete.return_value.eq.return_value.eq.assert_called_with(
            "organization_id", "org-test"
        )
        # Storage remove was not called (nothing to remove)
        sb.storage.from_.return_value.remove.assert_not_called()

    @patch("database.get_client")
    @patch("tenancy.authorize_bid_access")
    def test_d_db_succeeds_storage_remove_succeeds_verification_fails(self, mock_auth, mock_client):
        mock_auth.return_value = True
        sb = MagicMock()
        mock_client.return_value = sb

        runs_response = MagicMock(data=[{"id": 1, "status": "COMPLETE"}])
        post_delete_bid = MagicMock(data=[])
        child_runs_response = MagicMock(data=[])

        sb.table.return_value.select.return_value.eq.return_value.execute.side_effect = [
            runs_response,
            post_delete_bid,
            child_runs_response,
        ]

        # First list (pre-inventory) succeeds; second list (post-delete verification) throws
        sb.storage.from_.return_value.list.side_effect = [
            [{"name": "doc.pdf", "id": "uuid-1"}],
            Exception("Verification connection timeout"),
        ]

        with self.assertRaises(BidStorageCleanupError) as ctx:
            tenancy.delete_bid_for_organization(123, "org-test")

        self.assertEqual(ctx.exception.bid_id, 123)
        self.assertIn("post-delete Storage verification failed", str(ctx.exception))
        # Ensure DB delete was called once (no retry)
        self.assertEqual(sb.table.return_value.delete.call_count, 1)

    @patch("database.get_client")
    @patch("tenancy.authorize_bid_access")
    def test_e_normal_recursive_inventory_delete_verification(self, mock_auth, mock_client):
        mock_auth.return_value = True
        sb = MagicMock()
        mock_client.return_value = sb

        runs_response = MagicMock(data=[
            {"id": 1, "status": "COMPLETE"},
            {"id": 2, "status": "FAILED"},
            {"id": 3, "status": "PARTIAL"},
            {"id": 4, "status": "STOPPED"},
        ])
        post_delete_bid = MagicMock(data=[])
        child_runs_response = MagicMock(data=[])

        sb.table.return_value.select.return_value.eq.return_value.execute.side_effect = [
            runs_response,
            post_delete_bid,
            child_runs_response,
        ]

        def mock_list(folder):
            if folder == "123":
                return [
                    {"name": "root.pdf", "id": "uuid-1"},
                    {"name": "analysis_reports", "id": None},
                ]
            elif folder == "123/analysis_reports":
                return [{"name": "report.pdf", "id": "uuid-2"}]
            return []

        # First pre-inventory traversal, then post-delete verification (empty)
        sb.storage.from_.return_value.list.side_effect = [
            mock_list("123"),
            mock_list("123/analysis_reports"),
            [],  # post-delete verification
        ]

        result = tenancy.delete_bid_for_organization(123, "org-test")
        self.assertEqual(
            result,
            {
                "bid_id": 123,
                "organization_id": "org-test",
                "deleted_db": True,
                "deleted_storage_files": 2,
            },
        )
        sb.storage.from_.return_value.remove.assert_called_once_with(
            ["123/root.pdf", "123/analysis_reports/report.pdf"]
        )

    @patch("tenancy.authorize_bid_access")
    def test_f_wrong_tenant_never_attempts_storage_listing(self, mock_auth):
        mock_auth.return_value = False
        with patch("database.get_client") as mock_client:
            sb = MagicMock()
            mock_client.return_value = sb
            with self.assertRaises(AccessDeniedError):
                tenancy.delete_bid_for_organization(123, "org-other")
            # Storage listing is NEVER attempted
            sb.storage.assert_not_called()
            sb.table.assert_not_called()

    @patch("database.get_client")
    @patch("tenancy.authorize_bid_access")
    def test_g_active_run_never_attempts_storage_listing(self, mock_auth, mock_client):
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
        # Storage listing is NEVER attempted
        sb.storage.assert_not_called()
        sb.table.return_value.delete.assert_not_called()

    @patch("database.get_client")
    @patch("tenancy.authorize_bid_access")
    def test_h_db_cascade_failure_storage_untouched(self, mock_auth, mock_client):
        mock_auth.return_value = True
        sb = MagicMock()
        mock_client.return_value = sb

        runs_response = MagicMock(data=[{"id": 1, "status": "COMPLETE"}])
        sb.storage.from_.return_value.list.return_value = [{"name": "file.pdf", "id": "uuid"}]
        post_delete_bid = MagicMock(data=[])
        cascade_child_runs = MagicMock(data=[{"id": 1}])

        sb.table.return_value.select.return_value.eq.return_value.execute.side_effect = [
            runs_response,
            post_delete_bid,
            cascade_child_runs,
        ]

        with self.assertRaises(RuntimeError) as ctx:
            tenancy.delete_bid_for_organization(123, "org-test")
        self.assertIn("Cascade verification failed", str(ctx.exception))
        sb.storage.from_.return_value.remove.assert_not_called()

    @patch("database.get_client")
    @patch("tenancy.authorize_bid_access")
    def test_i_db_succeeds_storage_remove_fails_raises_cleanup_error(self, mock_auth, mock_client):
        mock_auth.return_value = True
        sb = MagicMock()
        mock_client.return_value = sb

        runs_response = MagicMock(data=[{"id": 1, "status": "COMPLETE"}])
        sb.storage.from_.return_value.list.return_value = [{"name": "rfp.pdf", "id": "uuid-1"}]
        post_delete_bid = MagicMock(data=[])
        child_runs_response = MagicMock(data=[])

        sb.table.return_value.select.return_value.eq.return_value.execute.side_effect = [
            runs_response,
            post_delete_bid,
            child_runs_response,
        ]

        sb.storage.from_.return_value.remove.side_effect = Exception("Storage connection error")

        with self.assertRaises(BidStorageCleanupError) as ctx:
            tenancy.delete_bid_for_organization(123, "org-test")

        self.assertEqual(ctx.exception.bid_id, 123)
        self.assertEqual(ctx.exception.remaining_files, ["123/rfp.pdf"])
        self.assertIn("Supabase Storage removal failed", str(ctx.exception))
        self.assertEqual(sb.table.return_value.delete.call_count, 1)

    @patch("database.get_client")
    @patch("tenancy.authorize_bid_access")
    def test_j_fails_if_post_delete_verification_detects_bid_remains(self, mock_auth, mock_client):
        mock_auth.return_value = True
        sb = MagicMock()
        mock_client.return_value = sb

        runs_response = MagicMock(data=[{"id": 1, "status": "COMPLETE"}])
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
        # Extract page_all_bids function body
        all_bids_start = self.app_source.index("def page_all_bids():")
        all_bids_end = self.app_source.index("def page_new_bid():", all_bids_start)
        self.all_bids_body = self.app_source[all_bids_start:all_bids_end]
        # Extract page_bid_overview function body
        ov_start = self.app_source.index("def page_bid_overview(bid_id):")
        ov_end = self.app_source.index("def page_compliance(bid_id):", ov_start)
        self.bid_overview_body = self.app_source[ov_start:ov_end]

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

    def test_bids_directory_row_exposes_delete_action_with_inline_confirmation(self):
        # Must expose Delete button in each row
        self.assertIn(
            'c6.button("🗑 Delete"',
            self.all_bids_body,
            "Bids Directory rows must expose Delete action",
        )
        # First click sets bid-scoped confirmation state and does not call deletion
        self.assertIn(
            'st.session_state[confirm_key] = True',
            self.all_bids_body,
            "Delete button click must set bid-scoped confirmation state",
        )
        # Two-step confirmation copy must be present in directory
        self.assertIn(
            "This permanently deletes this opportunity, its analyses, reports and uploaded documents. This cannot be undone.",
            self.all_bids_body,
            "Bids Directory must display required confirmation warning copy",
        )
        # Must have Confirm permanent deletion button in directory
        self.assertIn(
            "Confirm permanent deletion",
            self.all_bids_body,
            "Bids Directory must have Confirm permanent deletion button",
        )
        # Must have Cancel button in directory
        self.assertIn(
            'c_cancel.button("Cancel"',
            self.all_bids_body,
            "Bids Directory must have Cancel button",
        )

    def test_directory_confirm_deletion_calls_service_with_authenticated_context(self):
        # Confirm calls delete_bid_for_organization with bid_id and _ctx.organization_id
        self.assertIn(
            "_tenancy.delete_bid_for_organization(bid_id, _ctx.organization_id)",
            self.all_bids_body,
            "Bids Directory must route deletion through _tenancy.delete_bid_for_organization",
        )

    def test_directory_cancel_clears_confirmation_state_only(self):
        # Cancel sets confirm_key to False and reruns
        self.assertIn(
            'st.session_state[confirm_key] = False',
            self.all_bids_body,
            "Cancel must clear confirmation state",
        )

    def test_directory_error_handling_active_run_inventory_and_cleanup(self):
        # Active analysis friendly refusal
        self.assertIn(
            "This opportunity is currently being analyzed and cannot be deleted until the analysis finishes.",
            self.all_bids_body,
            "Must display friendly active analysis error message",
        )
        # Storage inventory failure
        self.assertIn(
            "except _tenancy.BidStorageInventoryError",
            self.all_bids_body,
            "Must catch BidStorageInventoryError",
        )
        self.assertIn(
            "Storage could not be verified, so the opportunity was not deleted. Please try again.",
            self.all_bids_body,
            "Must display storage inventory failure message",
        )
        # Partial storage cleanup error
        self.assertIn(
            "except _tenancy.BidStorageCleanupError",
            self.all_bids_body,
            "Must catch BidStorageCleanupError",
        )
        self.assertIn(
            "Opportunity deleted, but document storage cleanup could not be fully completed.",
            self.all_bids_body,
            "Must display partial cleanup message",
        )
        # Access denied error
        self.assertIn(
            "except _tenancy.AccessDeniedError",
            self.all_bids_body,
            "Must catch AccessDeniedError",
        )

    def test_app_no_longer_depends_on_unreachable_page_bid_overview_for_customer_deletion(self):
        # page_bid_overview must not contain customer delete controls
        self.assertNotIn(
            "_tenancy.delete_bid_for_organization",
            self.bid_overview_body,
            "page_bid_overview must not contain delete service calls",
        )
        self.assertNotIn(
            "Confirm permanent deletion",
            self.bid_overview_body,
            "page_bid_overview must not contain deletion confirmation controls",
        )
        self.assertNotIn(
            "🗑 Delete Bid",
            self.bid_overview_body,
            "page_bid_overview must not contain Delete Bid button",
        )
        # Router must route stage_understand and bid_overview to page_understand
        router_start = self.app_source.index("# ROUTER")
        router_body = self.app_source[router_start:]
        self.assertIn('page in ("stage_understand", "bid_overview"):', router_body)
        self.assertIn('page_understand(bid_id)', router_body)
        self.assertNotIn('page_bid_overview(bid_id)', router_body)



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
    """Executes the full 15-step matrix (A through O) in a real PostgreSQL engine."""

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
            "ALL 15 TESTS (A THROUGH O) PASSED ON REAL POSTGRESQL ENGINE!",
            res.stdout,
        )
        # Verify specific tests reported PASS
        for letter in [
            "A", "B", "C", "D", "E", "F", "G", "H",
            "I.1", "I.2", "I.3", "I.4", "J", "K", "L", "M", "N", "O"
        ]:
            self.assertIn(f"PASS Test {letter}:", res.stdout)
