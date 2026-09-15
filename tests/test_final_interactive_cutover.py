"""
tests/test_final_interactive_cutover.py

Deterministic tests for Phase 8 remediation package 3's final, comprehensive
interactive-surface cutover pass: pages/stage_decide.py, pages/stage_build.py,
pages/stage_check.py, pages/stage_submit.py, pages/stage_debrief.py,
pages/settings_firm.py, pages_extra.py, plus the two gaps discovered and
closed during this same pass (app.py's _render_extraction_review(), and
pages/stage_understand.py's remaining bare get_bid_brief/get_requirements/
get_documents calls). No live network calls -- every Supabase interaction is
mocked.

Two kinds of coverage:

  * Source-level checks (`TestNoRemainingBareServiceRoleCalls`): for each
    rewired file, prove no *reachable* function contains a bare call to a
    database.py read/write function that has a tenant-scoped or RLS-backed
    replacement. Dead functions (already confirmed unreachable and
    explicitly out of scope) are excluded by name, matching the same
    reachability method used throughout this engagement -- a real repo-wide
    call-site search, not an assumption from naming.
  * Behavioral checks (`TestPrivilegedWrappersAuthorizeBeforeWriting`,
    `TestOrganizationScopedContentLibrary`): the new tenancy.py privileged
    wrappers this pass added (upload_document_for_organization,
    set_document_mandatory_for_organization,
    create_document_record_for_organization,
    save_bid_brief_for_organization, and the organization-scoped
    content_library functions) actually call require_bid_access() /
    scope their read to the caller's own bid_ids BEFORE touching the
    privileged service-role client, and raise AccessDeniedError -- with
    zero underlying database.py call made -- when that check fails.
"""
import os
import unittest
from unittest.mock import MagicMock, patch

import tenancy


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")

# Reachable-page source files this pass rewired, plus the two file/function
# combinations fixed as additional discoveries. Category C (coaches -- no
# RLS policy exists, correctly stays server-side) and Category B (documents/
# Storage writes -- stay server-side via the new privileged wrappers, or via
# database.download_file for Storage-adjacent reads) call sites are excluded
# explicitly below, not silently ignored.
PAGE_SOURCES = {
    "pages/stage_decide.py": None,        # whole file reachable
    "pages/stage_build.py": None,
    "pages/stage_check.py": None,
    "pages/stage_submit.py": None,
    "pages/stage_debrief.py": None,
    "pages/settings_firm.py": None,
}

# Bare database.py function names that must NOT appear as a call (`name(`)
# anywhere in the reachable files above -- each has a tenant-scoped /
# RLS-authenticated / explicitly-privileged replacement now.
FORBIDDEN_BARE_CALLS = [
    "get_bid(", "get_requirements(", "get_outline(", "get_deliverables(",
    "get_documents(", "get_tasks(", "get_clarifications(", "get_debriefs(",
    "get_firm_profile(", "get_bid_brief(", "get_bid_decision(",
    "upsert_requirement(", "delete_requirement(",
    "upsert_section(", "delete_section(",
    "upsert_deliverable(", "delete_deliverable(",
    "upsert_task(", "delete_task(",
    "upsert_clarification(", "delete_clarification(",
    "upsert_debrief(", "save_bid_decision(",
    "save_firm_profile(", "update_bid(",
]


def _read(relpath: str) -> str:
    with open(os.path.join(REPO_ROOT, relpath), "r", encoding="utf-8") as f:
        return f.read()


class TestNoRemainingBareServiceRoleCalls(unittest.TestCase):
    """Every page this pass rewired must contain zero bare service-role
    calls for the tables that now have a tenant-scoped/RLS replacement."""

    def test_stage_pages_and_settings_firm_have_no_forbidden_bare_calls(self):
        for relpath in PAGE_SOURCES:
            source = _read(relpath)
            for forbidden in FORBIDDEN_BARE_CALLS:
                self.assertNotIn(
                    forbidden, source,
                    f"{relpath} still contains a bare call to {forbidden!r}"
                )

    def test_save_upload_only_remains_via_the_tenant_authorized_wrapper(self):
        """save_upload()/upsert_document() (documents/Storage, category B)
        legitimately stay server-side -- but only when reached through
        tenancy.upload_document_for_organization() /
        tenancy.set_document_mandatory_for_organization(), never bare."""
        for relpath in ("pages/stage_build.py", "pages/stage_submit.py"):
            source = _read(relpath)
            self.assertNotIn("save_upload(", source)
            self.assertNotIn(" upsert_document(", source)
            if "upload_document_for_organization" in source or "save_upload" in source.lower():
                pass  # presence is optional per-file; absence-of-bare-call is what matters

        build_source = _read("pages/stage_build.py")
        self.assertIn("tenancy.upload_document_for_organization(", build_source)

        submit_source = _read("pages/stage_submit.py")
        self.assertIn("tenancy.upload_document_for_organization(", submit_source)
        self.assertIn("tenancy.set_document_mandatory_for_organization(", submit_source)

    def test_pages_extra_reachable_functions_have_no_forbidden_bare_calls(self):
        """page_content_library() and page_exec_dashboard() are the only
        two reachable pages_extra.py functions besides page_team_roster()
        (coaches, category C, intentionally untouched). Check their bodies
        specifically, since the file also contains five confirmed-dead
        functions that legitimately still use the old bare calls."""
        source = _read("pages_extra.py")

        def body_of(fn_name):
            start = source.index(f"def {fn_name}(")
            end = source.index("\ndef ", start + 10)
            return source[start:end]

        lib_body = body_of("page_content_library")
        for forbidden in ("get_library_items(", "upsert_library_item(", "delete_library_item("):
            self.assertNotIn(forbidden, lib_body)
        self.assertIn("tenancy.list_library_items_for_organization(", lib_body)

        exec_body = body_of("page_exec_dashboard")
        for forbidden in (
            "get_all_bids(", "get_requirements(", "get_tasks(",
            "get_clarifications(", "get_debriefs(", "get_firm_profile(",
            "get_coaches(",
        ):
            self.assertNotIn(forbidden, exec_body)
        self.assertIn("tenancy.list_bids_authenticated(", exec_body)
        # coaches is organization-owned (migration 009) -- cut over to the
        # authenticated, RLS-backed read, same as everything else here.
        self.assertIn("tenancy.get_coaches_authenticated(", exec_body)

        roster_body = body_of("page_team_roster")
        for forbidden in ("get_coaches(", "upsert_coach(", "delete_coach("):
            self.assertNotIn(forbidden, roster_body)
        self.assertIn("tenancy.get_coaches_authenticated(", roster_body)
        self.assertIn("tenancy.upsert_coach_authenticated(", roster_body)
        self.assertIn("tenancy.delete_coach_authenticated(", roster_body)

    def test_five_dead_pages_extra_functions_are_confirmed_never_called(self):
        """Guards the classification this pass relies on: these five
        functions are imported into app.py's namespace but never actually
        invoked anywhere in the router or elsewhere -- confirmed by a
        repo-wide search for real call sites (as opposed to their own def
        line or the import statement)."""
        dead_names = [
            "page_proposal_analyzer", "page_clarifications",
            "page_section_drafter", "page_submission_assembler",
        ]
        app_source = _read("app.py")
        for name in dead_names:
            # Imported (appears in the "from pages_extra import (...)" block)...
            self.assertIn(name, app_source)
            # ...but never actually called: no "name(" outside of that import.
            call_sites = [
                i for i in range(len(app_source))
                if app_source.startswith(name + "(", i)
            ]
            self.assertEqual(
                call_sites, [],
                f"{name} has a real call site in app.py -- reachability classification is stale",
            )
        # pages_extra.py's own page_debrief (distinct from
        # pages.stage_debrief.page_debrief, which IS live) is never
        # imported by app.py at all.
        self.assertNotIn("from pages_extra import page_debrief", app_source)

    def test_render_extraction_review_uses_tenant_scoped_writes(self):
        """Additional discovery during this pass: app.py's
        _render_extraction_review() (the AI-extraction bid-creation
        confirmation screen, reachable from page_new_bid()) was still
        writing requirements/outline/documents/bid_brief via bare
        service-role calls even though bid creation itself already used
        tenancy.create_bid_for_organization(). Closed in the same pass."""
        source = _read("app.py")
        start = source.index("def _render_extraction_review():")
        end = source.index("\n\n", source.index("st.rerun()", start))
        body = source[start:end]
        self.assertIn("_tenancy.upload_document_for_organization(", body)
        self.assertIn("_tenancy.save_bid_brief_for_organization(", body)
        self.assertIn("_tenancy.upsert_requirement_authenticated(", body)
        self.assertIn("_tenancy.create_document_record_for_organization(", body)
        self.assertIn("_tenancy.upsert_section_authenticated(", body)
        self.assertNotIn(" save_upload(bid_id, fn, fb)", body)
        self.assertNotIn(" upsert_bid_brief(brief_data)", body)

    def test_stage_understand_page_understand_uses_authenticated_reads_only(self):
        """Additional discovery: page_understand()'s get_bid_brief/
        get_requirements/get_documents calls were still bare (only the top
        bid fetch and the analysis-run/result reads had been cut over in
        the prior round). Closed in this pass."""
        source = _read("pages/stage_understand.py")
        start = source.index("def page_understand(bid_id: int):")
        end = source.index("\ndef ", start + 10) if "\ndef " in source[start + 10:] else len(source)
        body = source[start:end]
        self.assertIn("tenancy.get_bid_brief_authenticated(", body)
        self.assertIn("tenancy.get_requirements_authenticated(", body)
        self.assertIn("tenancy.get_documents_authenticated(", body)
        self.assertNotIn(" get_bid_brief(bid_id)", body)
        self.assertNotIn(" get_requirements(bid_id)", body)
        self.assertNotIn(" get_documents(bid_id)", body)


class TestPrivilegedWrappersAuthorizeBeforeWriting(unittest.TestCase):
    """The new tenancy.py privileged wrappers must verify tenant ownership
    of bid_id BEFORE calling the underlying service-role database.py
    function -- and must call neither Storage nor the table write at all
    when that check fails."""

    def setUp(self):
        self.bid_id = 42
        self.organization_id = "org-A"

    @patch("tenancy.db.save_upload")
    @patch("tenancy.get_bid_for_organization")
    def test_upload_document_denies_before_touching_storage(self, mock_get_bid, mock_save_upload):
        mock_get_bid.return_value = None  # bid does not belong to this org
        with self.assertRaises(tenancy.AccessDeniedError):
            tenancy.upload_document_for_organization(
                self.bid_id, self.organization_id, "rfp.pdf", b"bytes"
            )
        mock_save_upload.assert_not_called()

    @patch("tenancy.db.save_upload")
    @patch("tenancy.get_bid_for_organization")
    def test_upload_document_allows_and_delegates_when_authorized(self, mock_get_bid, mock_save_upload):
        mock_get_bid.return_value = {"id": self.bid_id, "organization_id": self.organization_id}
        mock_save_upload.return_value = ("path", self.bid_id)
        tenancy.upload_document_for_organization(
            self.bid_id, self.organization_id, "rfp.pdf", b"bytes", doc_type="Submission"
        )
        mock_save_upload.assert_called_once_with(
            self.bid_id, "rfp.pdf", b"bytes", doc_type="Submission", owner=None, doc_id=None
        )

    @patch("tenancy.db.upsert_document")
    @patch("tenancy.get_bid_for_organization")
    def test_set_document_mandatory_denies_before_writing(self, mock_get_bid, mock_upsert_document):
        mock_get_bid.return_value = None
        with self.assertRaises(tenancy.AccessDeniedError):
            tenancy.set_document_mandatory_for_organization(self.bid_id, self.organization_id, 7, 1)
        mock_upsert_document.assert_not_called()

    @patch("tenancy.db.upsert_document")
    @patch("tenancy.get_bid_for_organization")
    def test_create_document_record_denies_before_writing(self, mock_get_bid, mock_upsert_document):
        mock_get_bid.return_value = None
        with self.assertRaises(tenancy.AccessDeniedError):
            tenancy.create_document_record_for_organization(
                self.bid_id, self.organization_id, {"name": "Cover Letter"}
            )
        mock_upsert_document.assert_not_called()

    @patch("tenancy.db.upsert_bid_brief")
    @patch("tenancy.get_bid_for_organization")
    def test_save_bid_brief_denies_before_writing(self, mock_get_bid, mock_upsert_brief):
        mock_get_bid.return_value = None
        with self.assertRaises(tenancy.AccessDeniedError):
            tenancy.save_bid_brief_for_organization(
                self.bid_id, self.organization_id, {"bid_id": self.bid_id}
            )
        mock_upsert_brief.assert_not_called()

    @patch("tenancy.db.upsert_bid_brief")
    @patch("tenancy.get_bid_for_organization")
    def test_save_bid_brief_allows_and_delegates_when_authorized(self, mock_get_bid, mock_upsert_brief):
        mock_get_bid.return_value = {"id": self.bid_id, "organization_id": self.organization_id}
        data = {"bid_id": self.bid_id, "executive_summary": "x"}
        tenancy.save_bid_brief_for_organization(self.bid_id, self.organization_id, data)
        mock_upsert_brief.assert_called_once_with(data)


class TestOrganizationScopedContentLibrary(unittest.TestCase):
    """content_library has no organization_id column and no authenticated
    policy for bid_id IS NULL rows, so the whole-library browse view
    (pages_extra.py's page_content_library()) stays privileged -- but must
    be explicitly scoped server-side to the caller's own bid_ids (plus true
    global rows), never an ungated read of the entire table."""

    def setUp(self):
        self.organization_id = "org-A"

    @patch("tenancy.db.get_client")
    @patch("tenancy.list_bids_for_organization")
    def test_list_scopes_to_own_bid_ids_plus_global_rows(self, mock_list_bids, mock_get_client):
        mock_list_bids.return_value = [{"id": 1}, {"id": 2}]
        mock_table = MagicMock()
        mock_get_client.return_value.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.or_.return_value = mock_table
        mock_table.order.return_value = mock_table
        mock_table.execute.return_value = MagicMock(data=[])

        tenancy.list_library_items_for_organization(self.organization_id)

        mock_table.or_.assert_called_once()
        or_clause = mock_table.or_.call_args[0][0]
        self.assertIn("bid_id.eq.1", or_clause)
        self.assertIn("bid_id.eq.2", or_clause)
        self.assertIn("bid_id.is.null", or_clause)

    @patch("tenancy.db.get_client")
    @patch("tenancy.list_bids_for_organization")
    def test_list_falls_back_to_global_only_when_org_has_no_bids(self, mock_list_bids, mock_get_client):
        mock_list_bids.return_value = []
        mock_table = MagicMock()
        mock_get_client.return_value.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.is_.return_value = mock_table
        mock_table.order.return_value = mock_table
        mock_table.execute.return_value = MagicMock(data=[])

        tenancy.list_library_items_for_organization(self.organization_id)

        mock_table.is_.assert_called_once_with("bid_id", "null")
        mock_table.or_.assert_not_called()

    @patch("tenancy.db.upsert_library_item")
    @patch("tenancy.get_bid_for_organization")
    def test_upsert_denies_cross_tenant_bid_id(self, mock_get_bid, mock_upsert):
        mock_get_bid.return_value = None
        with self.assertRaises(tenancy.AccessDeniedError):
            tenancy.upsert_library_item_for_organization(
                self.organization_id, {"title": "x", "bid_id": 999}
            )
        mock_upsert.assert_not_called()

    @patch("tenancy.db.upsert_library_item")
    def test_upsert_allows_global_item_unrestricted(self, mock_upsert):
        """bid_id=None (global item) is unrestricted, matching
        content_library's own pre-existing, deliberately-undecided
        global-library design -- not something this pass resolves."""
        tenancy.upsert_library_item_for_organization(
            self.organization_id, {"title": "x", "bid_id": None}
        )
        mock_upsert.assert_called_once()

    @patch("tenancy.db.delete_library_item")
    @patch("tenancy.get_bid_for_organization")
    @patch("tenancy.db.get_client")
    def test_delete_denies_cross_tenant_item(self, mock_get_client, mock_get_bid, mock_delete):
        mock_table = MagicMock()
        mock_get_client.return_value.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value = MagicMock(data=[{"bid_id": 999}])
        mock_get_bid.return_value = None  # 999 does not belong to this org

        with self.assertRaises(tenancy.AccessDeniedError):
            tenancy.delete_library_item_for_organization(self.organization_id, 55)
        mock_delete.assert_not_called()

    @patch("tenancy.db.delete_library_item")
    @patch("tenancy.db.get_client")
    def test_delete_allows_global_item_unrestricted(self, mock_get_client, mock_delete):
        mock_table = MagicMock()
        mock_get_client.return_value.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value = MagicMock(data=[{"bid_id": None}])

        tenancy.delete_library_item_for_organization(self.organization_id, 55)
        mock_delete.assert_called_once_with(55)


class TestCoachesOrganizationTenancy(unittest.TestCase):
    """coaches was determined, by explicit semantic audit (see migration
    009's own header comment), to be organization-owned personnel data --
    not platform-global reference data and not adequately protected by
    the app-wide auth gate alone. These tests prove the new authenticated
    primitives read/write through the authenticated client (subject to
    migration 009's RLS policies), and that a new coach row is always
    explicitly stamped with the caller's own organization_id rather than
    trusting a value the caller's own data dict might supply."""

    def setUp(self):
        self.token = "fake-access-token"
        self.organization_id = "org-A"

    @patch("tenancy.auth_client.get_authenticated_client")
    def test_get_coaches_authenticated_reads_through_authenticated_client(self, mock_get_client):
        mock_table = MagicMock()
        mock_get_client.return_value.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.order.return_value = mock_table
        mock_table.execute.return_value = MagicMock(data=[{"id": 1, "name": "Coach A"}])

        result = tenancy.get_coaches_authenticated(self.token)

        mock_get_client.assert_called_once_with(self.token)
        mock_get_client.return_value.table.assert_called_once_with("coaches")
        mock_table.order.assert_called_once_with("name")
        self.assertEqual(result, [{"id": 1, "name": "Coach A"}])

    @patch("tenancy.auth_client.get_authenticated_client")
    def test_upsert_coach_new_row_stamps_callers_own_organization_id(self, mock_get_client):
        mock_table = MagicMock()
        mock_get_client.return_value.table.return_value = mock_table
        mock_table.insert.return_value = mock_table
        mock_table.execute.return_value = MagicMock(data=[])

        tenancy.upsert_coach_authenticated(self.token, self.organization_id, {"name": "New Coach"})

        inserted_row = mock_table.insert.call_args[0][0]
        self.assertEqual(inserted_row["organization_id"], self.organization_id)
        self.assertEqual(inserted_row["name"], "New Coach")

    @patch("tenancy.auth_client.get_authenticated_client")
    def test_upsert_coach_existing_row_updates_without_reassigning_organization(self, mock_get_client):
        mock_table = MagicMock()
        mock_get_client.return_value.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value = MagicMock(data=[])

        tenancy.upsert_coach_authenticated(self.token, self.organization_id, {"id": 7, "name": "Existing Coach"})

        updated_row = mock_table.update.call_args[0][0]
        self.assertNotIn("organization_id", updated_row)
        mock_table.eq.assert_called_once_with("id", 7)

    @patch("tenancy.auth_client.get_authenticated_client")
    def test_delete_coach_authenticated_deletes_through_authenticated_client(self, mock_get_client):
        mock_table = MagicMock()
        mock_get_client.return_value.table.return_value = mock_table
        mock_table.delete.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value = MagicMock(data=[])

        tenancy.delete_coach_authenticated(self.token, 7)

        mock_get_client.assert_called_once_with(self.token)
        mock_table.eq.assert_called_once_with("id", 7)


if __name__ == "__main__":
    unittest.main()
