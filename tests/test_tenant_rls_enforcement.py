"""
tests/test_tenant_rls_enforcement.py

Deterministic tests for Phase 8 remediation package 3 (tenant RLS policy
enforcement & authenticated access cutover). No live LLM calls anywhere in
this file.

Two kinds of coverage, kept clearly separate (same convention established
in tests/test_auth_tenancy.py's TestMigration007SchemaContract):

  * RLS policy existence/scoping (`TestMigration008PolicyContract`): static
    assertions on migration 008's own SQL text -- proves the migration
    *declares* the intended policy for the intended table/operation/role,
    not that Postgres is enforcing it end-to-end. Live enforcement (the
    actual database RLS boundary) is verified separately, outside pytest,
    via live SQL transaction + JWT-claim simulation and documented
    precisely in BID_INTELLIGENCE_PHASE8_TENANT_RLS_ENFORCEMENT.md -- see
    that file for exactly what was and was not live-proven, and why (no
    real auth.users row exists yet to test the positive membership case
    end-to-end; see instruction 21/23's own bootstrap-gating language).

  * Application-layer authorization boundary
    (`TestPrivilegedOperationAuthorization`) and client separation
    (`TestClientSeparation`): ordinary mocked unit tests of real Python
    code in tenancy.py/auth_client.py/database.py.
"""
import os
import unittest
from unittest.mock import MagicMock, patch

import database
import tenancy
from tenancy import AccessDeniedError

MIGRATION_008_PATH = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "008_tenant_rls_policy_enforcement.sql"
)


def _migration_008_text() -> str:
    with open(MIGRATION_008_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _strip_sql_line_comments(text: str) -> str:
    """Remove every `-- ...` line comment. Several assertions below check
    for the ABSENCE of a pattern (e.g. 'using (true)', a table name with no
    policy) -- this file's own explanatory comments legitimately discuss
    those exact strings in prose (e.g. 'does not use USING (true)'), so
    checks that must not be fooled by documentation use this comment-
    stripped text instead of the raw SQL text."""
    return "\n".join(
        line for line in text.splitlines()
        if not line.strip().startswith("--")
    )


class TestMigration008PolicyContract(unittest.TestCase):

    def setUp(self):
        self.raw = _migration_008_text()
        self.sql = self.raw.lower()
        self.code = _strip_sql_line_comments(self.raw).lower()

    # ── No anon access anywhere (instruction 12) ─────────────────────────
    def test_no_policy_targets_anon_role(self):
        self.assertNotIn(" to anon", self.code)
        self.assertNotIn(",anon", self.code.replace(" ", ""))

    def test_every_policy_explicitly_scoped_to_authenticated(self):
        import re
        policy_blocks = re.findall(r"^create policy.*?;", self.code, re.DOTALL | re.MULTILINE)
        self.assertGreater(len(policy_blocks), 20)  # sanity: policies were actually found
        for block in policy_blocks:
            self.assertIn("to authenticated", block, msg=f"policy missing explicit role: {block[:80]}")

    def test_no_unconditional_true_policy(self):
        self.assertNotIn("using (true)", self.code)
        self.assertNotIn("with check (true)", self.code)

    def test_no_grant_or_revoke_of_broad_privilege(self):
        # The two helper functions' own EXECUTE grant/revoke is expected and
        # narrowly scoped (function-level, to `authenticated` only) --
        # assert there is no *table*-level GRANT/REVOKE anywhere.
        self.assertNotIn("grant select", self.sql)
        self.assertNotIn("grant insert", self.sql)
        self.assertNotIn("grant update", self.sql)
        self.assertNotIn("grant delete", self.sql)
        self.assertNotIn("grant all", self.sql)

    def test_no_destructive_ddl_or_data_mutation(self):
        for forbidden in ("drop table", "drop column", "truncate", "delete from",
                           "update public.bids set", "insert into public.bids"):
            self.assertNotIn(forbidden, self.sql)

    def test_migrations_001_through_007_not_touched(self):
        self.assertNotIn("alter table public.organizations add column", self.sql)
        self.assertNotIn("alter table public.bids add column", self.sql)
        self.assertNotIn("alter table public.bids alter column", self.sql)

    # ── Helper function safety (instruction 4) ───────────────────────────
    def test_is_organization_member_function_is_safe(self):
        self.assertIn("create or replace function public.is_organization_member", self.sql)
        self.assertIn("stable", self.sql)
        self.assertIn("security definer", self.sql)
        self.assertIn("set search_path = public", self.sql)
        self.assertIn("returns boolean", self.sql)
        self.assertIn("revoke all on function public.is_organization_member(uuid) from public", self.sql)
        self.assertIn("revoke execute on function public.is_organization_member(uuid) from anon", self.sql)
        self.assertIn("grant execute on function public.is_organization_member(uuid) to authenticated", self.sql)

    def test_can_access_bid_function_is_safe(self):
        self.assertIn("create or replace function public.can_access_bid", self.sql)
        self.assertIn("returns boolean", self.sql)
        self.assertIn("revoke all on function public.can_access_bid(bigint) from public", self.sql)
        self.assertIn("revoke execute on function public.can_access_bid(bigint) from anon", self.sql)
        self.assertIn("grant execute on function public.can_access_bid(bigint) to authenticated", self.sql)

    # ── Category A: organizations / organization_members ─────────────────
    def test_organizations_select_only_own_membership(self):
        self.assertIn("organizations_select_own_membership", self.sql)
        self.assertNotIn("organizations_insert", self.sql)
        self.assertNotIn("organizations_update", self.sql)
        self.assertNotIn("organizations_delete", self.sql)

    def test_organization_members_select_own_rows_only(self):
        self.assertIn("organization_members_select_own_rows", self.sql)
        self.assertIn("user_id = auth.uid()", self.sql)
        self.assertNotIn("organization_members_insert", self.sql)
        self.assertNotIn("organization_members_update", self.sql)
        self.assertNotIn("organization_members_delete", self.sql)

    # ── bids: full CRUD except DELETE ─────────────────────────────────────
    def test_bids_select_insert_update_policies_exist(self):
        for name in ("bids_select_org_member", "bids_insert_org_member", "bids_update_org_member"):
            self.assertIn(name, self.sql)

    def test_bids_has_no_delete_policy(self):
        self.assertNotIn("bids_delete", self.sql)

    def test_bids_update_with_check_prevents_org_reassignment(self):
        # Must have BOTH a USING and a WITH CHECK on the update policy,
        # both gated by is_organization_member(organization_id) -- this is
        # what stops a member from moving a bid into an org they don't
        # belong to.
        import re
        m = re.search(r"create policy bids_update_org_member.*?;", self.sql, re.DOTALL)
        self.assertIsNotNone(m)
        block = m.group(0)
        self.assertIn("using (public.is_organization_member(organization_id))", block)
        self.assertIn("with check (public.is_organization_member(organization_id))", block)

    # ── Downstream bid-owned tables ────────────────────────────────────────
    def test_downstream_full_crud_tables(self):
        for table in ("requirements", "tasks", "outline_sections", "deliverables", "clarifications"):
            for op in ("select", "insert", "update", "delete"):
                self.assertIn(f"{table}_{op}_bid_access", self.sql, msg=f"missing {table}.{op} policy")

    def test_debriefs_has_no_delete_policy(self):
        for op in ("select", "insert", "update"):
            self.assertIn(f"debriefs_{op}_bid_access", self.sql)
        self.assertNotIn("debriefs_delete", self.sql)

    def test_bid_decisions_select_and_insert_only(self):
        self.assertIn("bid_decisions_select_bid_access", self.sql)
        self.assertIn("bid_decisions_insert_bid_access", self.sql)
        self.assertNotIn("bid_decisions_update", self.sql)
        self.assertNotIn("bid_decisions_delete", self.sql)

    def test_content_library_requires_non_null_bid_id(self):
        for op in ("select", "insert", "update", "delete"):
            m_pattern = f"content_library_{op}_bid_access"
            self.assertIn(m_pattern, self.sql)
        # Every content_library policy must explicitly exclude the
        # unresolved global (bid_id IS NULL) rows: select(1) + insert(1) +
        # update(2 -- USING and WITH CHECK) + delete(1) = 5 occurrences.
        self.assertEqual(self.sql.count("bid_id is not null and public.can_access_bid(bid_id)"), 5)

    # ── Category B: user read / server write ──────────────────────────────
    def test_documents_select_only_no_write_policy(self):
        self.assertIn("documents_select_bid_access", self.sql)
        self.assertNotIn("documents_insert", self.sql)
        self.assertNotIn("documents_update", self.sql)
        self.assertNotIn("documents_delete_bid_access", self.sql)

    def test_document_versions_select_only_inherits_via_documents(self):
        self.assertIn("document_versions_select_bid_access", self.sql)
        self.assertIn("document_id in (select id from public.documents", self.sql)
        self.assertNotIn("document_versions_insert", self.sql)
        self.assertNotIn("document_versions_update", self.sql)
        self.assertNotIn("document_versions_delete", self.sql)

    def test_bid_briefs_analysis_runs_analysis_results_select_only(self):
        for table in ("bid_briefs", "analysis_runs", "analysis_results"):
            self.assertIn(f"{table}_select_bid_access", self.sql)
            self.assertNotIn(f"{table}_insert", self.sql)
            self.assertNotIn(f"{table}_update", self.sql)
            self.assertNotIn(f"{table}_delete", self.sql)

    # ── Category D: firm_profiles ───────────────────────────────────────────
    def test_firm_profiles_organization_scoped_no_delete(self):
        for op in ("select", "insert", "update"):
            self.assertIn(f"firm_profiles_{op}_org_member", self.sql)
        self.assertNotIn("firm_profiles_delete", self.sql)

    # ── Category C: coaches deliberately untouched ─────────────────────────
    def test_coaches_has_no_policy_at_all(self):
        """'coaches' is discussed in this migration's own explanatory
        comments (why it's excluded) -- what must never appear is an
        actual `create policy coaches_...` statement."""
        self.assertNotIn("create policy coaches", self.code)
        self.assertNotIn("on public.coaches", self.code)


def _mock_client_for_bid_ownership(owned: bool):
    sb = MagicMock()
    data = [{"id": 8, "organization_id": "org-1", "title": "Some Bid"}] if owned else []
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=data)
    return sb


class TestPrivilegedOperationAuthorization(unittest.TestCase):

    @patch("tenancy.db.get_client")
    def test_authorize_bid_access_true_when_owned(self, mock_get_client):
        mock_get_client.return_value = _mock_client_for_bid_ownership(owned=True)
        self.assertTrue(tenancy.authorize_bid_access(8, "org-1"))

    @patch("tenancy.db.get_client")
    def test_authorize_bid_access_false_when_not_owned(self, mock_get_client):
        mock_get_client.return_value = _mock_client_for_bid_ownership(owned=False)
        self.assertFalse(tenancy.authorize_bid_access(8, "org-999-unrelated"))

    @patch("tenancy.db.get_client")
    def test_require_bid_access_raises_on_denial(self, mock_get_client):
        mock_get_client.return_value = _mock_client_for_bid_ownership(owned=False)
        with self.assertRaises(AccessDeniedError):
            tenancy.require_bid_access(8, "org-999-unrelated")

    @patch("tenancy.db.get_client")
    def test_require_bid_access_silent_on_success(self, mock_get_client):
        mock_get_client.return_value = _mock_client_for_bid_ownership(owned=True)
        tenancy.require_bid_access(8, "org-1")  # must not raise

    @patch("analysis_service.start_fast_analysis")
    @patch("tenancy.db.get_client")
    def test_authorized_user_can_request_analysis(self, mock_get_client, mock_start):
        mock_get_client.return_value = _mock_client_for_bid_ownership(owned=True)
        mock_start.return_value = {"id": 99, "status": "QUEUED"}

        result = tenancy.start_fast_analysis_for_organization(8, "org-1", "sk-ant-test", created_by="app-ui")

        self.assertEqual(result["id"], 99)
        mock_start.assert_called_once_with(8, "sk-ant-test", created_by="app-ui")

    @patch("analysis_service.start_fast_analysis")
    @patch("tenancy.db.get_client")
    def test_unauthorized_user_cannot_request_analysis(self, mock_get_client, mock_start):
        """The core Phase 8 remediation package 3 negative test (instruction
        17): a user from an unrelated organization attempting to start
        analysis on someone else's bid must be denied, with ZERO run
        created and ZERO calls into the privileged analysis service --
        i.e. zero possibility of an LLM call being started."""
        mock_get_client.return_value = _mock_client_for_bid_ownership(owned=False)

        with self.assertRaises(AccessDeniedError):
            tenancy.start_fast_analysis_for_organization(8, "org-999-unrelated", "sk-ant-test")

        mock_start.assert_not_called()

    @patch("analysis_service.regenerate_report")
    @patch("tenancy.db.get_analysis_run")
    @patch("tenancy.db.get_client")
    def test_authorized_report_retrieval_works(self, mock_get_client, mock_get_run, mock_regen):
        mock_get_client.return_value = _mock_client_for_bid_ownership(owned=True)
        mock_get_run.return_value = {"id": 6, "bid_id": 8}
        mock_regen.return_value = b"%PDF-1.4 fake bytes"

        result = tenancy.get_report_for_organization(8, 6, "org-1")

        self.assertEqual(result, b"%PDF-1.4 fake bytes")
        mock_regen.assert_called_once_with(6)

    @patch("analysis_service.regenerate_report")
    @patch("tenancy.db.get_analysis_run")
    @patch("tenancy.db.get_client")
    def test_unauthorized_report_retrieval_fails_bid_not_owned(self, mock_get_client, mock_get_run, mock_regen):
        mock_get_client.return_value = _mock_client_for_bid_ownership(owned=False)

        with self.assertRaises(AccessDeniedError):
            tenancy.get_report_for_organization(8, 6, "org-999-unrelated")

        mock_get_run.assert_not_called()
        mock_regen.assert_not_called()

    @patch("analysis_service.regenerate_report")
    @patch("tenancy.db.get_analysis_run")
    @patch("tenancy.db.get_client")
    def test_unauthorized_report_retrieval_fails_run_belongs_to_different_bid(
        self, mock_get_client, mock_get_run, mock_regen
    ):
        """The caller owns bid 8, but run_id 6 actually belongs to bid 999
        (a different bid, possibly in a different organization) -- a
        guessed/adjacent run_id must not leak that run's report just
        because the caller happens to legitimately own SOME bid."""
        mock_get_client.return_value = _mock_client_for_bid_ownership(owned=True)
        mock_get_run.return_value = {"id": 6, "bid_id": 999}

        with self.assertRaises(AccessDeniedError):
            tenancy.get_report_for_organization(8, 6, "org-1")

        mock_regen.assert_not_called()


class TestClientSeparation(unittest.TestCase):

    def test_database_module_exposes_explicit_service_client_name(self):
        self.assertTrue(hasattr(database, "get_service_client"))

    @patch("database.create_client")
    def test_get_service_client_uses_service_role_value(self, mock_create_client):
        with patch.dict(os.environ, {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_KEY": "service-role-secret-value",
        }, clear=False):
            with patch("database.st") as mock_st:
                mock_st.secrets = {}
                database.get_service_client()
        args, _ = mock_create_client.call_args
        self.assertEqual(args[1], "service-role-secret-value")

    def test_auth_client_module_never_reads_service_role_key(self):
        source = open(
            os.path.join(os.path.dirname(__file__), "..", "auth_client.py"), "r", encoding="utf-8"
        ).read()
        self.assertNotIn('os.getenv("SUPABASE_SERVICE_KEY")', source)
        self.assertNotIn('st.secrets["SUPABASE_SERVICE_KEY"]', source)

    @patch.dict(os.environ, {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_KEY": "service-role-secret-value",
        "SUPABASE_ANON_KEY": "anon-public-value",
    }, clear=False)
    @patch("auth_client.create_client")
    def test_authenticated_client_uses_anon_key_never_service_role_key(self, mock_create_client):
        import auth_client
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        with patch("streamlit.secrets", {}):
            result = auth_client.get_authenticated_client("user-own-access-token-abc123")

        args, _ = mock_create_client.call_args
        self.assertEqual(args[1], "anon-public-value")
        self.assertNotEqual(args[1], "service-role-secret-value")
        mock_client.postgrest.auth.assert_called_once_with("user-own-access-token-abc123")
        self.assertIs(result, mock_client)

    def test_authenticated_client_requires_a_token(self):
        import auth_client
        with self.assertRaises(ValueError):
            auth_client.get_authenticated_client("")
        with self.assertRaises(ValueError):
            auth_client.get_authenticated_client(None)

    def test_service_role_key_never_referenced_in_auth_session_module(self):
        """The service client must never be reachable from the Streamlit
        session-handling module -- session state may hold only the user's
        own tokens (see auth_session.py's own module docstring)."""
        source = open(
            os.path.join(os.path.dirname(__file__), "..", "auth_session.py"), "r", encoding="utf-8"
        ).read()
        self.assertNotIn("SUPABASE_SERVICE_KEY", source)
        self.assertNotIn("get_service_client", source)
        self.assertNotIn("database.get_client", source)
        self.assertNotIn("import database", source)

    def test_tenancy_module_authorization_functions_use_service_client_only_server_side(self):
        """tenancy.py's privileged-operation functions are server-side
        code (they call the background analysis service directly) -- they
        must use the service client, never construct or accept a raw
        service-role key themselves, and must never appear in
        auth_session.py's session-state-facing code."""
        source = open(
            os.path.join(os.path.dirname(__file__), "..", "tenancy.py"), "r", encoding="utf-8"
        ).read()
        self.assertNotIn("SUPABASE_SERVICE_KEY", source)
        self.assertNotIn("st.session_state", source)


def _mock_authenticated_client_for(table_data: dict):
    """table_data: {table_name: canned .execute().data list}. Every query
    chain shape used by the authenticated-read functions is covered."""
    client = MagicMock()

    def table_side_effect(name):
        m = MagicMock()
        data = table_data.get(name, [])
        m.select.return_value.order.return_value.execute.return_value = MagicMock(data=data)
        m.select.return_value.eq.return_value.execute.return_value = MagicMock(data=data)
        m.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(data=data)
        # Migration 010: requirements/readiness reads chain a second
        # .eq("lifecycle_status", "active") onto the bid_id filter.
        m.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=data)
        return m

    client.table.side_effect = table_side_effect
    return client


class TestAuthenticatedReads(unittest.TestCase):
    """tenancy.py's RLS-only read functions (Phase 8 remediation package 3
    interactive cutover): list_bids_authenticated / get_bid_authenticated /
    get_bid_analysis_authenticated. These read through
    auth_client.get_authenticated_client(access_token) -- no
    organization_id argument exists anywhere in this group, unlike the
    service-role tenant-aware primitives earlier in this file, because
    none is needed or trusted: whatever RLS lets the token's owner see is
    exactly what comes back."""

    @patch("tenancy.auth_client.get_authenticated_client")
    def test_list_bids_authenticated_uses_the_users_own_token(self, mock_get_authenticated_client):
        mock_client = _mock_authenticated_client_for({
            "bids": [{"id": 8, "title": "RFP"}],
            "requirements": [{"id": 1, "status": "Complete"}, {"id": 2, "status": "Not Started"}],
            "tasks": [{"id": 1, "status": "Complete"}],
        })
        mock_get_authenticated_client.return_value = mock_client

        bids = tenancy.list_bids_authenticated("real-users-own-access-token")

        mock_get_authenticated_client.assert_called_once_with("real-users-own-access-token")
        self.assertEqual(len(bids), 1)
        self.assertEqual(bids[0]["id"], 8)
        # req/task rollup matches database.get_all_bids()'s own shape --
        # page_dashboard()/page_all_bids() render this without any change.
        self.assertEqual(bids[0]["req_count"], 2)
        self.assertEqual(bids[0]["req_done"], 1)
        self.assertEqual(bids[0]["task_count"], 1)
        self.assertEqual(bids[0]["task_done"], 1)

    @patch("tenancy.auth_client.get_authenticated_client")
    def test_get_bid_authenticated_returns_row_rls_permits(self, mock_get_authenticated_client):
        mock_client = _mock_authenticated_client_for({"bids": [{"id": 8, "title": "RFP"}]})
        mock_get_authenticated_client.return_value = mock_client

        bid = tenancy.get_bid_authenticated("token", 8)

        self.assertEqual(bid["id"], 8)

    @patch("tenancy.auth_client.get_authenticated_client")
    def test_get_bid_authenticated_returns_none_when_rls_excludes_the_row(self, mock_get_authenticated_client):
        """No organization_id filter is applied by this function at all --
        an empty result here can only mean RLS itself excluded the row
        (cross-tenant bid, or one that doesn't exist -- indistinguishable,
        by design)."""
        mock_client = _mock_authenticated_client_for({"bids": []})
        mock_get_authenticated_client.return_value = mock_client

        bid = tenancy.get_bid_authenticated("token", 999)

        self.assertIsNone(bid)

    @patch("tenancy.auth_client.get_authenticated_client")
    def test_get_bid_analysis_authenticated_returns_runs_and_latest_result(self, mock_get_authenticated_client):
        mock_client = _mock_authenticated_client_for({
            "analysis_runs": [
                {"id": 1, "bid_id": 8, "status": "COMPLETE", "created_at": "2026-09-01T00:00:00Z"},
            ],
            "analysis_results": [{"id": 1, "run_id": 1, "structured_intelligence": {}}],
        })
        mock_get_authenticated_client.return_value = mock_client

        analysis = tenancy.get_bid_analysis_authenticated("token", 8)

        self.assertEqual(len(analysis["runs"]), 1)
        self.assertIsNotNone(analysis["latest_result"])

    @patch("tenancy.auth_client.get_authenticated_client")
    def test_get_bid_analysis_authenticated_empty_when_rls_excludes_bid(self, mock_get_authenticated_client):
        mock_client = _mock_authenticated_client_for({"analysis_runs": [], "analysis_results": []})
        mock_get_authenticated_client.return_value = mock_client

        analysis = tenancy.get_bid_analysis_authenticated("token", 999)

        self.assertEqual(analysis["runs"], [])
        self.assertIsNone(analysis["latest_result"])


class TestLogoutClearsAllUserScopedState(unittest.TestCase):
    """Instruction: logout must clear auth context, organization context,
    tokens/session state, active bid, and any user-scoped cached state --
    tested at the app.py level (the only place 'active_bid' and the
    Package-3 authenticated-view selection actually live)."""

    def test_app_py_sign_out_handler_clears_active_bid_and_selection_state(self):
        """app.py has three 'Sign out' entry points (the mandatory gate's
        no-access screen, its multi-org-selection screen, and the normal
        sidebar) -- all three share one function, _clear_all_user_scoped_
        state(), so the full logout contract is defined exactly once. This
        checks that shared function's own body, plus that every 'Sign out'
        button actually calls it (not auth_session.sign_out() directly,
        which would skip the app-level state)."""
        source = open(
            os.path.join(os.path.dirname(__file__), "..", "app.py"), "r", encoding="utf-8"
        ).read()

        def_start = source.index("def _clear_all_user_scoped_state():")
        def_end = source.index("\n\n\n", def_start)
        clear_fn_body = source[def_start:def_end]
        self.assertIn("_auth_session.sign_out()", clear_fn_body)
        self.assertIn('"active_bid"', clear_fn_body)
        self.assertIn('"pkg3_selected_bid"', clear_fn_body)
        self.assertIn('"pkg3_org_choice"', clear_fn_body)

        sign_out_button_count = source.count('if st.button("Sign out"')
        self.assertGreaterEqual(sign_out_button_count, 1, "expected at least one Sign out button")
        clear_call_count = source.count("_clear_all_user_scoped_state()")
        # One call inside the shared function's own definition, plus one
        # per "Sign out" button that invokes it.
        self.assertEqual(clear_call_count, 1 + sign_out_button_count)

    def test_auth_session_sign_out_clears_session_and_context(self):
        """Re-confirms (already tested in test_auth_tenancy.py) that
        auth_session.sign_out() itself clears SESSION_KEY and
        AUTH_CONTEXT_KEY -- the auth-module half of the full logout
        contract app.py's handler completes."""
        import streamlit as st
        import auth_session
        st.session_state[auth_session.SESSION_KEY] = {"access_token": "at", "user_id": "u1"}
        st.session_state[auth_session.AUTH_CONTEXT_KEY] = object()
        with patch("auth_session.get_auth_client") as mock_get_auth_client:
            mock_get_auth_client.return_value = MagicMock()
            auth_session.sign_out()
        self.assertNotIn(auth_session.SESSION_KEY, st.session_state)
        self.assertNotIn(auth_session.AUTH_CONTEXT_KEY, st.session_state)


if __name__ == "__main__":
    unittest.main()
