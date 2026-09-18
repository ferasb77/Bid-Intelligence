"""
tests/test_auth_tenancy.py

Deterministic tests for Phase 8 remediation package 2 (authentication &
tenancy foundation). No live Supabase connection anywhere in this file --
database.get_client() / auth_client.get_auth_client() are mocked, same
pattern as tests/test_database.py. No live LLM calls.

Two kinds of coverage, kept clearly separate:

  * Schema/migration correctness (`TestMigration007SchemaContract`): this
    repo has no precedent for a live-Postgres pytest fixture -- every
    earlier migration (004/005/006) was verified by a live query after
    applying it, not by a unit test. These tests follow that same
    convention for anything genuinely enforced by Postgres itself (unique
    constraints, check constraints, NOT NULL) by asserting the migration
    file's own SQL text contains the expected DDL -- they prove the
    migration *declares* the right constraints, not that Postgres is
    enforcing them; live enforcement is confirmed separately in
    BID_INTELLIGENCE_PHASE8_AUTH_TENANCY_FOUNDATION.md's live
    post-migration verification section.

  * Application-code correctness (everything else): tenancy.py's
    resolution/primitive functions, auth_client.py/auth_session.py's
    client separation and session handling -- ordinary mocked unit tests
    of real Python code.
"""
import os
import time
import unittest
from unittest.mock import MagicMock, patch

import database
import tenancy
from tenancy import AuthContext, NoOrganizationAccess, OrganizationSelectionRequired

MIGRATION_007_PATH = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "007_auth_tenancy_foundation.sql"
)


def _migration_007_text() -> str:
    with open(MIGRATION_007_PATH, "r", encoding="utf-8") as f:
        return f.read()


class TestMigration007SchemaContract(unittest.TestCase):
    """Static assertions on migration 007's own SQL text -- see module
    docstring for exactly what this does and does not prove."""

    def setUp(self):
        self.sql = _migration_007_text().lower()

    def test_organization_creation_model(self):
        self.assertIn("create table if not exists public.organizations", self.sql)
        self.assertIn("id          uuid primary key default gen_random_uuid()", self.sql)
        self.assertIn("name        text not null", self.sql)

    def test_organization_slug_uniqueness(self):
        self.assertIn("constraint organizations_slug_unique unique (slug)", self.sql)

    def test_membership_uniqueness(self):
        self.assertIn("create table if not exists public.organization_members", self.sql)
        self.assertIn("primary key (organization_id, user_id)", self.sql)

    def test_membership_references_auth_users(self):
        self.assertIn("references auth.users(id) on delete cascade", self.sql)

    def test_valid_roles_only(self):
        self.assertIn("check (role in ('owner', 'admin', 'member'))", self.sql)

    def test_bid_requires_valid_organization_after_backfill(self):
        # The NOT NULL is only applied after a guard that aborts the whole
        # migration if any bid is still unbackfilled.
        self.assertIn("raise exception", self.sql)
        self.assertIn("alter column organization_id set not null", self.sql)

    def test_backfill_is_deterministic_and_idempotent(self):
        # No hardcoded UUID -- referenced only via the unique slug.
        self.assertNotRegex(self.sql, r"organization_id\s*=\s*'[0-9a-f]{8}-[0-9a-f]{4}-")
        self.assertIn("on conflict (slug) do nothing", self.sql)
        self.assertIn("where organization_id is null", self.sql)
        self.assertIn("'emg-internal'", self.sql)

    def test_migration_006_and_earlier_not_modified(self):
        # This test only proves migration 007 doesn't literally redeclare/
        # touch the earlier migrations' own tables in a way that would
        # collide; the git-status-based non-modification check itself is
        # performed procedurally, not via pytest (see the Phase 8 report).
        for earlier_table in ("analysis_runs", "analysis_results"):
            self.assertNotIn(f"drop table {earlier_table}", self.sql)
            self.assertNotIn(f"alter table public.{earlier_table} drop", self.sql)

    def test_new_tables_rls_enabled_no_policies_created(self):
        self.assertIn("alter table public.organizations       enable row level security", self.sql)
        self.assertIn("alter table public.organization_members enable row level security", self.sql)
        self.assertNotIn("create policy", self.sql)

    def test_no_destructive_ddl(self):
        for forbidden in ("drop table", "drop column", "truncate", "delete from"):
            self.assertNotIn(forbidden, self.sql)

    def test_firm_profiles_organization_id_nullable_additive(self):
        self.assertIn(
            "alter table public.firm_profiles\n    add column if not exists organization_id",
            _migration_007_text(),
        )
        # Deliberately not forced NOT NULL -- see decision write-up.
        self.assertNotIn("alter table public.firm_profiles alter column organization_id set not null", self.sql)

    def test_analysis_runs_created_by_untouched_new_column_added(self):
        self.assertIn("add column if not exists created_by_user_id", self.sql)
        self.assertNotIn("drop column created_by", self.sql)
        self.assertNotIn("alter table public.analysis_runs alter column created_by", self.sql)


def _mock_client_for_membership_resolution(memberships, orgs):
    sb = MagicMock()

    def table_side_effect(name):
        m = MagicMock()
        if name == "organization_members":
            m.select.return_value.eq.return_value.execute.return_value = MagicMock(data=memberships)
        elif name == "organizations":
            m.select.return_value.in_.return_value.execute.return_value = MagicMock(data=orgs)
        else:
            raise AssertionError(f"unexpected table() call: {name}")
        return m

    sb.table.side_effect = table_side_effect
    return sb


class TestOrganizationMembershipResolution(unittest.TestCase):

    @patch("tenancy.db.get_client")
    def test_zero_memberships_fails_closed(self, mock_get_client):
        mock_get_client.return_value = _mock_client_for_membership_resolution([], [])

        result = tenancy.resolve_organization_context("user-1", "user1@example.com")

        self.assertIsInstance(result, NoOrganizationAccess)
        self.assertEqual(result.user_id, "user-1")

    @patch("tenancy.db.get_client")
    def test_one_membership_resolves_to_auth_context(self, mock_get_client):
        mock_get_client.return_value = _mock_client_for_membership_resolution(
            memberships=[{"organization_id": "org-1", "role": "owner"}],
            orgs=[{"id": "org-1", "name": "Enable My Growth Internal"}],
        )

        result = tenancy.resolve_organization_context("user-1", "user1@example.com")

        self.assertIsInstance(result, AuthContext)
        self.assertEqual(result.user_id, "user-1")
        self.assertEqual(result.email, "user1@example.com")
        self.assertEqual(result.organization_id, "org-1")
        self.assertEqual(result.organization_name, "Enable My Growth Internal")
        self.assertEqual(result.role, "owner")

    @patch("tenancy.db.get_client")
    def test_multiple_memberships_do_not_silently_select(self, mock_get_client):
        mock_get_client.return_value = _mock_client_for_membership_resolution(
            memberships=[
                {"organization_id": "org-1", "role": "member"},
                {"organization_id": "org-2", "role": "admin"},
            ],
            orgs=[
                {"id": "org-1", "name": "Org One"},
                {"id": "org-2", "name": "Org Two"},
            ],
        )

        result = tenancy.resolve_organization_context("user-1", "user1@example.com")

        self.assertIsInstance(result, OrganizationSelectionRequired)
        self.assertEqual(result.user_id, "user-1")
        self.assertEqual(len(result.candidates), 2)
        org_ids = {c["organization_id"] for c in result.candidates}
        self.assertEqual(org_ids, {"org-1", "org-2"})
        # Every candidate carries what a selector needs -- name and role.
        for c in result.candidates:
            self.assertIn("organization_name", c)
            self.assertIn("role", c)


class TestAuthContextConstruction(unittest.TestCase):

    def test_auth_context_is_frozen_and_carries_exactly_the_required_fields(self):
        ctx = AuthContext(
            user_id="u1", email="a@b.com", organization_id="o1",
            organization_name="Org", role="member",
        )
        self.assertEqual(ctx.user_id, "u1")
        self.assertEqual(ctx.email, "a@b.com")
        self.assertEqual(ctx.organization_id, "o1")
        self.assertEqual(ctx.organization_name, "Org")
        self.assertEqual(ctx.role, "member")
        with self.assertRaises(Exception):
            ctx.role = "owner"  # frozen dataclass -- must not be mutable


class TestTenantAwareBidPrimitives(unittest.TestCase):

    @patch("tenancy.db.get_client")
    def test_list_bids_for_organization_scopes_by_organization_id(self, mock_get_client):
        sb = MagicMock()

        def table_side_effect(name):
            m = MagicMock()
            if name == "bids":
                m.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
                    data=[{"id": 1, "title": "Bid One"}]
                )
            elif name in ("requirements", "tasks"):
                m.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
            else:
                raise AssertionError(f"unexpected table() call: {name}")
            return m

        sb.table.side_effect = table_side_effect
        mock_get_client.return_value = sb

        bids = tenancy.list_bids_for_organization("org-1")

        self.assertEqual(len(bids), 1)
        self.assertEqual(bids[0]["id"], 1)
        self.assertEqual(bids[0]["req_count"], 0)
        self.assertEqual(bids[0]["task_count"], 0)

    @patch("tenancy.db.get_client")
    def test_get_bid_for_organization_returns_bid_when_owned(self, mock_get_client):
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": 8, "organization_id": "org-1", "title": "Owned Bid"}]
        )
        mock_get_client.return_value = sb

        result = tenancy.get_bid_for_organization(8, "org-1")

        self.assertIsNotNone(result)
        self.assertEqual(result["id"], 8)

    @patch("tenancy.db.get_client")
    def test_cross_organization_bid_lookup_rejected_at_application_boundary(self, mock_get_client):
        """A bid_id that exists but belongs to a different organization
        must come back as None -- the double .eq(id).eq(organization_id)
        filter means Postgres itself would return zero rows; this test
        proves the application code surfaces that as None, not an
        exception, and not the other organization's row."""
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[]  # Postgres found no row matching BOTH id and this organization_id
        )
        mock_get_client.return_value = sb

        result = tenancy.get_bid_for_organization(8, "org-999-not-the-owner")

        self.assertIsNone(result)

    @patch("tenancy.db.get_client")
    def test_create_bid_for_organization_requires_explicit_organization_id(self, mock_get_client):
        with self.assertRaises(ValueError):
            tenancy.create_bid_for_organization({"title": "x", "client": "y"}, organization_id=None)
        with self.assertRaises(ValueError):
            tenancy.create_bid_for_organization({"title": "x", "client": "y"}, organization_id="")
        mock_get_client.assert_not_called()

    @patch("tenancy.db.get_client")
    def test_create_bid_for_organization_never_defaults_to_legacy_org(self, mock_get_client):
        """No code path in tenancy.py may ever set organization_id to the
        legacy 'emg-internal' slug/org itself -- a new bid must always
        carry an explicit caller-supplied organization_id. ('emg-internal'
        appears only in this module's own docstring prose explaining that
        fact, which is fine; this checks there is no executable reference
        such as a default-parameter value or a literal assignment.)"""
        source = open(
            os.path.join(os.path.dirname(__file__), "..", "tenancy.py"), "r", encoding="utf-8"
        ).read()
        self.assertNotIn('organization_id="emg-internal"', source)
        self.assertNotIn("organization_id = 'emg-internal'", source)
        self.assertNotRegex(source, r"organization_id\s*[:=]\s*['\"]emg-internal")

    @patch("tenancy.db.get_client")
    def test_create_bid_for_organization_writes_the_given_organization_id(self, mock_get_client):
        sb = MagicMock()
        sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": 55}])
        mock_get_client.return_value = sb

        new_id = tenancy.create_bid_for_organization({"title": "New", "client": "Buyer"}, organization_id="org-1")

        self.assertEqual(new_id, 55)
        inserted = sb.table.return_value.insert.call_args[0][0]
        self.assertEqual(inserted["organization_id"], "org-1")


class TestAuthDataClientSeparation(unittest.TestCase):
    """Regression guard (instruction 7): the auth client and the server
    data client must never share a credential, and neither module may read
    the other's key."""

    def test_auth_client_never_reads_service_role_key(self):
        """'SUPABASE_SERVICE_KEY' appears in this module's own docstring
        prose (explaining the separation this test enforces), which is
        fine -- what must never appear is an actual access pattern that
        would read it."""
        source = open(
            os.path.join(os.path.dirname(__file__), "..", "auth_client.py"), "r", encoding="utf-8"
        ).read()
        self.assertNotIn('os.getenv("SUPABASE_SERVICE_KEY")', source)
        self.assertNotIn('st.secrets["SUPABASE_SERVICE_KEY"]', source)
        self.assertNotIn("st.secrets.get(\"SUPABASE_SERVICE_KEY\")", source)

    def test_database_module_never_reads_anon_key(self):
        source = open(
            os.path.join(os.path.dirname(__file__), "..", "database.py"), "r", encoding="utf-8"
        ).read()
        self.assertNotIn('os.getenv("SUPABASE_ANON_KEY")', source)
        self.assertNotIn('st.secrets["SUPABASE_ANON_KEY"]', source)

    @patch.dict(os.environ, {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_KEY": "service-role-secret-value",
        "SUPABASE_ANON_KEY": "anon-public-value",
    }, clear=False)
    @patch("database.create_client")
    def test_database_get_client_uses_service_role_value(self, mock_create_client):
        # Force the .env-loading / st.secrets branch to fall through to os.environ.
        with patch("database.st") as mock_st:
            mock_st.secrets = {}
            database.get_client()
        args, _ = mock_create_client.call_args
        self.assertEqual(args[1], "service-role-secret-value")

    @patch.dict(os.environ, {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_KEY": "service-role-secret-value",
        "SUPABASE_ANON_KEY": "anon-public-value",
    }, clear=False)
    @patch("auth_client.create_client")
    def test_auth_client_uses_anon_value_not_service_role_value(self, mock_create_client):
        import auth_client
        # auth_client.get_auth_client() imports streamlit locally and reads
        # st.secrets first -- replace it with an empty dict so the lookup
        # raises (no secrets.toml in this test process) and the function
        # falls through to the os.environ values patched above, the same
        # fallback path database.get_client()'s own test exercises.
        with patch("streamlit.secrets", {}):
            auth_client.get_auth_client()
        args, _ = mock_create_client.call_args
        self.assertEqual(args[1], "anon-public-value")
        self.assertNotEqual(args[1], "service-role-secret-value")


class TestAuthSession(unittest.TestCase):

    @patch("auth_session.get_auth_client")
    def test_sign_in_success_populates_session_state(self, mock_get_auth_client):
        mock_client = MagicMock()
        mock_session = MagicMock(access_token="at-1", refresh_token="rt-1", expires_at=time.time() + 3600)
        mock_user = MagicMock(id="user-1", email="a@b.com")
        mock_client.auth.sign_in_with_password.return_value = MagicMock(session=mock_session, user=mock_user)
        mock_get_auth_client.return_value = mock_client

        import streamlit as st
        st.session_state.clear()
        import auth_session
        result = auth_session.sign_in("a@b.com", "correct-password")

        self.assertTrue(result.ok)
        self.assertEqual(result.user_id, "user-1")
        stored = st.session_state[auth_session.SESSION_KEY]
        self.assertEqual(stored["access_token"], "at-1")
        self.assertNotIn("password", stored)

    @patch("auth_session.get_auth_client")
    def test_sign_in_invalid_credentials_returns_generic_error_not_raw_exception_text(self, mock_get_auth_client):
        mock_client = MagicMock()
        mock_client.auth.sign_in_with_password.side_effect = Exception("Invalid login credentials: user@internal.example detail=xyz")
        mock_get_auth_client.return_value = mock_client

        import auth_session
        result = auth_session.sign_in("a@b.com", "wrong-password")

        self.assertFalse(result.ok)
        self.assertNotIn("xyz", result.error)
        self.assertNotIn("user@internal.example", result.error)

    def test_sign_in_missing_fields_never_calls_auth_client(self):
        import auth_session
        with patch("auth_session.get_auth_client") as mock_get_auth_client:
            result = auth_session.sign_in("", "")
            self.assertFalse(result.ok)
            mock_get_auth_client.assert_not_called()

    def test_missing_token_session_restoration_fails_closed(self):
        import streamlit as st
        import auth_session
        st.session_state.clear()
        result = auth_session.restore_session()
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "no session")

    def test_expired_token_session_restoration_fails_closed(self):
        import streamlit as st
        import auth_session
        st.session_state.clear()
        st.session_state[auth_session.SESSION_KEY] = {
            "access_token": "at-1", "refresh_token": "rt-1",
            "user_id": "user-1", "email": "a@b.com",
            "expires_at": time.time() - 10,  # already expired
        }
        result = auth_session.restore_session()
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "session expired")

    def test_valid_token_session_restoration_succeeds(self):
        import streamlit as st
        import auth_session
        st.session_state.clear()
        st.session_state[auth_session.SESSION_KEY] = {
            "access_token": "at-1", "refresh_token": "rt-1",
            "user_id": "user-1", "email": "a@b.com",
            "expires_at": time.time() + 3600,
        }
        result = auth_session.restore_session()
        self.assertTrue(result.ok)
        self.assertEqual(result.user_id, "user-1")

    @patch("auth_session.get_auth_client")
    def test_sign_out_clears_session_state_even_if_remote_call_fails(self, mock_get_auth_client):
        mock_client = MagicMock()
        mock_client.auth.sign_out.side_effect = Exception("network error")
        mock_get_auth_client.return_value = mock_client

        import streamlit as st
        import auth_session
        st.session_state[auth_session.SESSION_KEY] = {"access_token": "at-1", "user_id": "user-1"}

        auth_session.sign_out()

        self.assertNotIn(auth_session.SESSION_KEY, st.session_state)

    def test_no_password_or_service_role_credential_ever_stored_in_session_state(self):
        source = open(
            os.path.join(os.path.dirname(__file__), "..", "auth_session.py"), "r", encoding="utf-8"
        ).read()
        self.assertNotIn("password\"] =", source)
        self.assertNotIn("SUPABASE_SERVICE_KEY", source)


class TestInviteCallback(unittest.TestCase):
    """Phase 8 remediation package 3 authenticated-cutover bootstrap:
    auth_session.handle_invite_callback() -- the token_hash-based flow a
    Streamlit server CAN read (unlike the fragment-based #access_token
    implicit flow, which it cannot)."""

    def _mock_query_params(self, **kwargs):
        # st.query_params supports .get()/.pop() -- a plain dict satisfies
        # both for these tests.
        return dict(kwargs)

    @patch("auth_session.get_auth_client")
    def test_no_callback_params_is_a_safe_no_op(self, mock_get_auth_client):
        import streamlit as st
        import auth_session
        with patch.object(st, "query_params", self._mock_query_params()):
            result = auth_session.handle_invite_callback()
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "no invite callback present")
        mock_get_auth_client.assert_not_called()

    @patch("auth_session.get_auth_client")
    def test_unsupported_callback_type_rejected_without_processing(self, mock_get_auth_client):
        import streamlit as st
        import auth_session
        # 'recovery' is a real EmailOtpType but not one this bootstrap
        # accepts (only 'invite' and 'email' are -- see
        # INVITE_CALLBACK_ACCEPTED_TYPES).
        qp = self._mock_query_params(token_hash="abc123", type="recovery")
        with patch.object(st, "query_params", qp):
            result = auth_session.handle_invite_callback()
        self.assertFalse(result.ok)
        self.assertIn("unsupported callback type", result.error)
        mock_get_auth_client.assert_not_called()
        # stripped from the (mocked) query params even though rejected
        self.assertNotIn("token_hash", qp)
        self.assertNotIn("type", qp)

    @patch("tenancy.resolve_organization_context")
    @patch("auth_session.get_auth_client")
    def test_successful_invite_verification_resolves_authcontext(self, mock_get_auth_client, mock_resolve):
        import streamlit as st
        import auth_session
        from tenancy import AuthContext

        mock_client = MagicMock()
        mock_session = MagicMock(access_token="at-invite", refresh_token="rt-invite", expires_at=time.time() + 3600)
        mock_user = MagicMock(id="ed5ccf11-8f6e-4975-85db-f2d1cf84660b", email="feras@enablemygrowth.com")
        mock_client.auth.verify_otp.return_value = MagicMock(session=mock_session, user=mock_user)
        mock_get_auth_client.return_value = mock_client
        mock_resolve.return_value = AuthContext(
            user_id="ed5ccf11-8f6e-4975-85db-f2d1cf84660b", email="feras@enablemygrowth.com",
            organization_id="4326b564-8cc5-4463-9304-9a589f08cc91",
            organization_name="Enable My Growth Internal", role="owner",
        )

        qp = self._mock_query_params(token_hash="real-token-hash-value", type="invite")
        st.session_state.clear()
        with patch.object(st, "query_params", qp):
            result = auth_session.handle_invite_callback()

        self.assertTrue(result.ok)
        self.assertEqual(result.user_id, "ed5ccf11-8f6e-4975-85db-f2d1cf84660b")
        mock_client.auth.verify_otp.assert_called_once_with(
            {"token_hash": "real-token-hash-value", "type": "invite"}
        )
        stored_session = st.session_state[auth_session.SESSION_KEY]
        self.assertEqual(stored_session["access_token"], "at-invite")
        context = st.session_state[auth_session.AUTH_CONTEXT_KEY]
        self.assertEqual(context.organization_id, "4326b564-8cc5-4463-9304-9a589f08cc91")
        self.assertEqual(context.role, "owner")
        # one-time token stripped from the URL after processing
        self.assertNotIn("token_hash", qp)
        self.assertNotIn("type", qp)

    @patch("tenancy.resolve_organization_context")
    @patch("auth_session.get_auth_client")
    def test_successful_email_type_verification_passes_through_the_correct_type(
        self, mock_get_auth_client, mock_resolve
    ):
        """Regression guard: verify_otp() must be called with the type
        actually present in the URL (`email` -- the token_hash type
        Supabase's verify_otp() expects for a magic-link sign-in, NOT the
        `magiclink` literal), never a hardcoded 'invite' -- a real bug
        caught during this bootstrap (Supabase rejects a second invite for
        an already-registered user with a 422, so magic-link sign-in via
        `type=email` was added as the fallback for every later sign-in of
        the same real user; the call must use the matching type or
        Supabase rejects the verification)."""
        import streamlit as st
        import auth_session
        from tenancy import AuthContext

        mock_client = MagicMock()
        mock_session = MagicMock(access_token="at-magic", refresh_token="rt-magic", expires_at=time.time() + 3600)
        mock_user = MagicMock(id="ed5ccf11-8f6e-4975-85db-f2d1cf84660b", email="feras@enablemygrowth.com")
        mock_client.auth.verify_otp.return_value = MagicMock(session=mock_session, user=mock_user)
        mock_get_auth_client.return_value = mock_client
        mock_resolve.return_value = AuthContext(
            user_id="ed5ccf11-8f6e-4975-85db-f2d1cf84660b", email="feras@enablemygrowth.com",
            organization_id="4326b564-8cc5-4463-9304-9a589f08cc91",
            organization_name="Enable My Growth Internal", role="owner",
        )

        qp = self._mock_query_params(token_hash="fresh-magiclink-token-hash", type="email")
        st.session_state.clear()
        with patch.object(st, "query_params", qp):
            result = auth_session.handle_invite_callback()

        self.assertTrue(result.ok)
        mock_client.auth.verify_otp.assert_called_once_with(
            {"token_hash": "fresh-magiclink-token-hash", "type": "email"}
        )
        self.assertEqual(st.session_state[auth_session.AUTH_CONTEXT_KEY].role, "owner")

    @patch("auth_session.get_auth_client")
    def test_magiclink_literal_type_is_not_accepted(self, mock_get_auth_client):
        """The literal string 'magiclink' is NOT the correct type for this
        token_hash flow (that was an initial mistake, corrected to 'email'
        -- see INVITE_CALLBACK_ACCEPTED_TYPES) -- it must be rejected the
        same as any other unsupported type."""
        import streamlit as st
        import auth_session
        qp = self._mock_query_params(token_hash="abc123", type="magiclink")
        with patch.object(st, "query_params", qp):
            result = auth_session.handle_invite_callback()
        self.assertFalse(result.ok)
        self.assertIn("unsupported callback type", result.error)
        mock_get_auth_client.assert_not_called()

    @patch("auth_session.get_auth_client")
    def test_invalid_or_expired_token_fails_closed_and_strips_url(self, mock_get_auth_client):
        import streamlit as st
        import auth_session

        mock_client = MagicMock()
        mock_client.auth.verify_otp.side_effect = Exception("Token has expired or is invalid")
        mock_get_auth_client.return_value = mock_client

        qp = self._mock_query_params(token_hash="stale-token", type="invite")
        with patch.object(st, "query_params", qp):
            result = auth_session.handle_invite_callback()

        self.assertFalse(result.ok)
        self.assertIn("invalid or expired", result.error)
        self.assertNotIn("token_hash", qp)
        self.assertNotIn("type", qp)

    def test_sign_out_clears_auth_context_too(self):
        import streamlit as st
        import auth_session
        st.session_state[auth_session.SESSION_KEY] = {"access_token": "at", "user_id": "u1"}
        st.session_state[auth_session.AUTH_CONTEXT_KEY] = object()
        with patch("auth_session.get_auth_client") as mock_get_auth_client:
            mock_get_auth_client.return_value = MagicMock()
            auth_session.sign_out()
        self.assertNotIn(auth_session.SESSION_KEY, st.session_state)
        self.assertNotIn(auth_session.AUTH_CONTEXT_KEY, st.session_state)

    def test_callback_never_logs_or_prints_raw_token_values(self):
        source = open(
            os.path.join(os.path.dirname(__file__), "..", "auth_session.py"), "r", encoding="utf-8"
        ).read()
        # No print()/logging call anywhere in the module that could echo a
        # token/token_hash/access_token/refresh_token value.
        self.assertNotIn("print(", source)
        self.assertNotIn("logging.", source)
        self.assertNotIn("logger.", source)


class TestFragmentSessionCallback(unittest.TestCase):
    """auth_session.handle_fragment_session_callback() -- the bridge for
    Supabase's implicit-flow #access_token=...&refresh_token=... links
    (dashboard-triggered password recovery, and some magic-link
    configurations), which a Streamlit server can never see directly
    since a URL fragment is never sent in the HTTP request. Diagnosed
    live via a real magic-link/recovery URL landing on staging as
    #access_token=...&refresh_token=...&type=recovery -- the callback
    below is the server-side half; render_fragment_session_bridge() is
    the client-side JS half that moves the pair into sb_at/sb_rt query
    params before this ever runs."""

    def _mock_query_params(self, **kwargs):
        return dict(kwargs)

    @patch("auth_session.get_auth_client")
    def test_no_callback_params_is_a_safe_no_op(self, mock_get_auth_client):
        import streamlit as st
        import auth_session
        with patch.object(st, "query_params", self._mock_query_params()):
            result = auth_session.handle_fragment_session_callback()
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "no fragment session callback present")
        mock_get_auth_client.assert_not_called()

    @patch("tenancy.resolve_organization_context")
    @patch("auth_session.get_auth_client")
    def test_successful_fragment_session_resolves_authcontext(self, mock_get_auth_client, mock_resolve):
        import streamlit as st
        import auth_session
        from tenancy import AuthContext

        mock_client = MagicMock()
        mock_session = MagicMock(access_token="at-fragment", refresh_token="rt-fragment",
                                  expires_at=time.time() + 3600)
        mock_user = MagicMock(id="ed5ccf11-8f6e-4975-85db-f2d1cf84660b", email="feras@enablemygrowth.com")
        mock_client.auth.set_session.return_value = MagicMock(session=mock_session, user=mock_user)
        mock_get_auth_client.return_value = mock_client
        mock_resolve.return_value = AuthContext(
            user_id="ed5ccf11-8f6e-4975-85db-f2d1cf84660b", email="feras@enablemygrowth.com",
            organization_id="4326b564-8cc5-4463-9304-9a589f08cc91",
            organization_name="Enable My Growth Internal", role="owner",
        )

        qp = self._mock_query_params(sb_at="real-access-token", sb_rt="real-refresh-token")
        st.session_state.clear()
        with patch.object(st, "query_params", qp):
            result = auth_session.handle_fragment_session_callback()

        self.assertTrue(result.ok)
        self.assertEqual(result.user_id, "ed5ccf11-8f6e-4975-85db-f2d1cf84660b")
        # set_session(), NOT verify_otp() -- these are already-issued,
        # already-valid tokens, not a one-time code to redeem.
        mock_client.auth.set_session.assert_called_once_with("real-access-token", "real-refresh-token")
        mock_client.auth.verify_otp.assert_not_called()
        stored_session = st.session_state[auth_session.SESSION_KEY]
        self.assertEqual(stored_session["access_token"], "at-fragment")
        context = st.session_state[auth_session.AUTH_CONTEXT_KEY]
        self.assertEqual(context.organization_id, "4326b564-8cc5-4463-9304-9a589f08cc91")
        # one-time tokens stripped from the URL after processing
        self.assertNotIn("sb_at", qp)
        self.assertNotIn("sb_rt", qp)

    @patch("auth_session.get_auth_client")
    def test_invalid_or_expired_token_fails_closed_and_strips_url(self, mock_get_auth_client):
        import streamlit as st
        import auth_session

        mock_client = MagicMock()
        mock_client.auth.set_session.side_effect = Exception("Token has expired or is invalid")
        mock_get_auth_client.return_value = mock_client

        qp = self._mock_query_params(sb_at="stale-access-token", sb_rt="stale-refresh-token")
        with patch.object(st, "query_params", qp):
            result = auth_session.handle_fragment_session_callback()

        self.assertFalse(result.ok)
        self.assertIn("invalid or expired", result.error)
        self.assertNotIn("sb_at", qp)
        self.assertNotIn("sb_rt", qp)

    def test_bridge_component_only_activates_on_a_real_fragment_token(self):
        """The client-side JS snippet must gate its own redirect on the
        fragment actually containing access_token= -- never an
        unconditional redirect on every page load."""
        source = open(
            os.path.join(os.path.dirname(__file__), "..", "auth_session.py"), "r", encoding="utf-8"
        ).read()
        bridge_start = source.index("def render_fragment_session_bridge")
        bridge_end = source.index("def handle_fragment_session_callback")
        bridge_body = source[bridge_start:bridge_end]
        self.assertIn("access_token=", bridge_body)
        self.assertIn("window.parent.location.replace", bridge_body)
        self.assertIn("sb_at", bridge_body)
        self.assertIn("sb_rt", bridge_body)

    def test_bridge_reads_and_writes_the_parent_frame_never_the_iframe(self):
        """st.components.v1.html() renders inside a same-origin IFRAME --
        every location read/write must target window.parent, never a bare
        window.location, or the redirect would only ever affect the
        invisible iframe and never the actual browser tab (the exact bug
        caught live: the bridge never fired because of this)."""
        source = open(
            os.path.join(os.path.dirname(__file__), "..", "auth_session.py"), "r", encoding="utf-8"
        ).read()
        bridge_start = source.index("def render_fragment_session_bridge")
        bridge_end = source.index("def handle_fragment_session_callback")
        script_start = source.index("<script>", bridge_start)
        script_end = source.index("</script>", bridge_start)
        script_body = source[script_start:script_end]
        self.assertIn("window.parent.location", script_body)
        self.assertNotIn("window.location", script_body)

    def test_callback_never_logs_or_prints_raw_fragment_token_values(self):
        source = open(
            os.path.join(os.path.dirname(__file__), "..", "auth_session.py"), "r", encoding="utf-8"
        ).read()
        self.assertNotIn("print(", source)
        self.assertNotIn("logging.", source)
        self.assertNotIn("logger.", source)


class TestNoPublicSignUp(unittest.TestCase):
    """Instruction 6: no open self-registration in this package."""

    def test_auth_session_module_exposes_no_sign_up_function(self):
        import auth_session
        self.assertFalse(hasattr(auth_session, "sign_up"))
        self.assertFalse(hasattr(auth_session, "register"))
        self.assertFalse(hasattr(auth_session, "create_account"))


class TestAppWiresTheFragmentSessionBridge(unittest.TestCase):
    """Static structural check that app.py actually calls the fragment
    bridge -- and calls it BEFORE handle_invite_callback()/
    handle_fragment_session_callback() -- since app.py's top-level
    Streamlit script body isn't otherwise unit-testable the way a plain
    function is (same constraint noted by this repo's other app.py
    wiring checks)."""

    def _app_source(self) -> str:
        return open(
            os.path.join(os.path.dirname(__file__), "..", "app.py"), "r", encoding="utf-8"
        ).read()

    def test_bridge_is_rendered(self):
        source = self._app_source()
        self.assertIn("_auth_session.render_fragment_session_bridge()", source)

    def test_fragment_callback_is_invoked(self):
        source = self._app_source()
        self.assertIn("_auth_session.handle_fragment_session_callback()", source)

    def test_bridge_renders_before_either_callback_is_read(self):
        source = self._app_source()
        bridge_idx = source.index("_auth_session.render_fragment_session_bridge()")
        invite_idx = source.index("_auth_session.handle_invite_callback()")
        fragment_idx = source.index("_auth_session.handle_fragment_session_callback()")
        self.assertLess(bridge_idx, invite_idx)
        self.assertLess(bridge_idx, fragment_idx)

    def test_login_gate_surfaces_fragment_callback_errors(self):
        source = self._app_source()
        gate_idx = source.index("def _render_login_gate")
        gate_body = source[gate_idx:gate_idx + 1500]
        self.assertIn("_fragment_result", gate_body)
        self.assertIn("no fragment session callback present", gate_body)


if __name__ == "__main__":
    unittest.main()
