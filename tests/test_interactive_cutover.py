"""
tests/test_interactive_cutover.py

Deterministic tests for Phase 8 remediation package 3's final acceptance
pass: the actual normal-UI authenticated cutover (not the earlier additive
diagnostic panel). No live LLM calls. No live network calls -- every
Supabase interaction is mocked; app.py is imported once, at module level,
with a faked authenticated session (the same pattern
tests/smoke/test_all_pages_runtime.py already uses), since app.py is a
flat top-level script whose auth gate runs at import time.

Two kinds of coverage, consistent with every other test file in this
engagement:

  * Structural/source-level checks (`TestCutoverArchitecture`): prove the
    gate, Dashboard, bid-open, and bid-creation code paths are wired the
    way the instructions require -- e.g. that page_dashboard() reads via
    tenancy.list_bids_authenticated(), never database.get_all_bids().
  * Behavioral checks against the already-imported app module
    (`TestGoAuthorizesBidOpen`, `TestLoginGateBehavior`): call app.go()
    and the login-gate logic directly with controlled mocks.
"""
import importlib
import os
import time
import unittest
from unittest.mock import MagicMock, patch

import streamlit as st

_FAKE_USER_ID = "00000000-0000-0000-0000-000000000001"
_FAKE_ORG_ID = "00000000-0000-0000-0000-000000000002"


def _fake_authenticated_session_state():
    st.session_state["bi_auth_session"] = {
        "access_token": "test-interactive-cutover-token",
        "refresh_token": "test-interactive-cutover-refresh",
        "user_id": _FAKE_USER_ID,
        "email": "cutover-test@example.com",
        "expires_at": time.time() + 3600,
    }
    from tenancy import AuthContext
    st.session_state["bi_auth_context"] = AuthContext(
        user_id=_FAKE_USER_ID, email="cutover-test@example.com",
        organization_id=_FAKE_ORG_ID, organization_name="Cutover Test Org", role="owner",
    )


_fake_authenticated_session_state()

# Scoped tightly to the import itself -- app.py's mandatory auth gate runs
# at import time and would otherwise attempt a live call with a fake
# token. Every test method below either needs no authenticated-client call
# at all (TestCutoverArchitecture is source-only) or applies its own
# narrowly-scoped @patch (TestGoAuthorizesBidOpen) / explicit `with
# patch(...)` block (TestLoginGateBehavior) -- so nothing stays globally
# patched after this import completes, avoiding any cross-test-file
# interference with tests that exercise the REAL, unpatched
# get_authenticated_client() (e.g. TestClientSeparation in
# test_tenant_rls_enforcement.py).
with patch(
    "tenancy.auth_client.get_authenticated_client",
    return_value=MagicMock(**{
        "table.return_value.select.return_value.order.return_value.execute.return_value": MagicMock(data=[]),
        "table.return_value.select.return_value.eq.return_value.execute.return_value": MagicMock(data=[]),
    }),
):
    import database
    import app
    import tenancy


APP_SOURCE_PATH = os.path.join(os.path.dirname(__file__), "..", "app.py")


def _app_source() -> str:
    with open(APP_SOURCE_PATH, "r", encoding="utf-8") as f:
        return f.read()


class TestCutoverArchitecture(unittest.TestCase):
    """Source-level proof of the wiring instructions 1-6 require."""

    def setUp(self):
        self.source = _app_source()

    def test_mandatory_gate_exists_before_any_page_function(self):
        gate_idx = self.source.index("if not _session_result.ok:")
        first_page_def_idx = self.source.index("def page_dashboard():")
        self.assertLess(gate_idx, first_page_def_idx,
                         "the auth gate must appear before page_dashboard is even defined/reachable")
        self.assertIn("_render_login_gate()", self.source[gate_idx:gate_idx + 200])
        self.assertIn("st.stop()", self.source[gate_idx:gate_idx + 200])

    def test_login_gate_never_renders_bid_data(self):
        gate_fn_start = self.source.index("def _render_login_gate():")
        gate_fn_end = self.source.index("\n\n\n", gate_fn_start)
        gate_fn_body = self.source[gate_fn_start:gate_fn_end]
        self.assertNotIn("list_bids_authenticated", gate_fn_body)
        self.assertNotIn("get_all_bids", gate_fn_body)
        self.assertNotIn("page_dashboard", gate_fn_body)

    def test_no_public_signup_in_login_gate(self):
        gate_fn_start = self.source.index("def _render_login_gate():")
        gate_fn_end = self.source.index("\n\n\n", gate_fn_start)
        gate_fn_body = self.source[gate_fn_start:gate_fn_end]
        self.assertIn("should_create_user", gate_fn_body)
        self.assertIn("False", self.source[self.source.index("should_create_user"):self.source.index("should_create_user") + 40])
        self.assertNotIn("sign_up", gate_fn_body.lower().replace("should_create_user", ""))

    def test_zero_membership_fails_closed_in_gate(self):
        self.assertIn("NoOrganizationAccess", self.source)
        idx = self.source.index("isinstance(_ctx, _tenancy.NoOrganizationAccess)")
        block = self.source[idx:idx + 500]
        self.assertIn("st.stop()", block)
        self.assertIn("not a member of any organization", self.source)

    def test_multi_membership_requires_explicit_selection_never_silent(self):
        idx = self.source.index("isinstance(_ctx, _tenancy.OrganizationSelectionRequired)")
        block = self.source[idx:idx + 1500]
        self.assertIn("st.selectbox", block)
        self.assertIn("st.stop()", block)
        # The selection must come from a button click (explicit continue),
        # not be applied automatically as soon as the selectbox has a value.
        self.assertIn('st.button("Continue"', block)

    def test_dashboard_uses_authenticated_client_not_service_role(self):
        fn_start = self.source.index("def page_dashboard():")
        fn_end = self.source.index("\ndef ", fn_start + 10)
        body = self.source[fn_start:fn_end]
        self.assertIn("_tenancy.list_bids_authenticated(_access_token)", body)
        self.assertNotIn("get_all_bids()", body)

    def test_all_bids_page_uses_authenticated_client_not_service_role(self):
        fn_start = self.source.index("def page_all_bids():")
        fn_end = self.source.index("\ndef ", fn_start + 10)
        body = self.source[fn_start:fn_end]
        self.assertIn("_tenancy.list_bids_authenticated(_access_token)", body)
        self.assertNotIn("get_all_bids()", body)

    def test_go_uses_authenticated_client_to_authorize_bid_open(self):
        fn_start = self.source.index("def go(page, bid_id=None):")
        fn_end = self.source.index("\n\n", fn_start)
        body = self.source[fn_start:fn_end]
        self.assertIn("_tenancy.get_bid_authenticated(_access_token, bid_id)", body)
        self.assertIn("st.error", body)

    def test_bid_creation_requires_explicit_organization_no_emg_internal_fallback(self):
        self.assertNotIn("emg-internal", self.source)
        creation_calls = [
            i for i in range(len(self.source))
            if self.source.startswith("_tenancy.create_bid_for_organization(", i)
        ]
        self.assertEqual(len(creation_calls), 2, "expected exactly the two known bid-creation call sites")
        for idx in creation_calls:
            surrounding = self.source[idx:idx + 400]
            self.assertIn("organization_id=_ctx.organization_id", surrounding)

    def test_database_create_bid_no_longer_called_from_app_py(self):
        """The normal interactive create-bid path must not call
        database.create_bid() (the pre-auth compatibility path) at all --
        confirmed by checking the import line and absence of any bare
        create_bid( call (as opposed to create_bid_for_organization())."""
        self.assertNotIn("import create_bid,", self.source)
        self.assertNotIn("import create_bid\n", self.source)
        # No bare `= create_bid(` call anywhere (only the _for_organization variant).
        self.assertNotIn(" create_bid({", self.source)

    def test_start_fast_analysis_authorization_boundary_wired(self):
        """The privileged, user-triggered 'Run Fast Analysis' action must
        cross tenancy's authorization boundary before analysis_service is
        ever called (instruction: architecture note on privileged ops)."""
        source = open(
            os.path.join(os.path.dirname(__file__), "..", "pages", "stage_understand.py"),
            "r", encoding="utf-8",
        ).read()
        fn_start = source.index("def _start_fast_analysis(bid_id: int):")
        fn_end = source.index("\n\n\n", fn_start)
        body = source[fn_start:fn_end]
        # Strip the docstring (which legitimately mentions
        # analysis_service.start_fast_analysis() in prose, explaining why
        # it is no longer called directly) before checking the real code.
        code_only = body[body.index('"""', body.index('"""') + 3) + 3:]
        self.assertIn("tenancy.start_fast_analysis_for_organization(", code_only)
        self.assertIn("AccessDeniedError", code_only)
        self.assertNotIn("analysis_service.start_fast_analysis(", code_only)

    def test_sign_out_present_in_sidebar_for_normal_authenticated_use(self):
        self.assertIn('st.button("Sign out", key="pkg3_sidebar_signout"', self.source)

    def test_team_roster_reachable_from_global_sidebar_navigation(self):
        """page_team_roster() (coaches -- migration 009's organization-
        scoped tenancy) has always been routable ('team_roster' has been
        in the router's page-dispatch table since it was added), but had
        no sidebar button pointing at it -- a normal authenticated user
        had no way to actually reach it through the UI. This is a
        reachability regression guard, not a new authorization check."""
        nav_start = self.source.index("# ── Global Navigation ──")
        nav_end = self.source.index("}.items():", nav_start)
        nav_block = self.source[nav_start:nav_end]
        self.assertIn('"team_roster"', nav_block,
                       "no global sidebar nav entry routes to team_roster")

        router_idx = self.source.index('page in ("team_roster", "coach_roster")')
        router_block = self.source[router_idx:router_idx + 120]
        self.assertIn("page_team_roster()", router_block)


class TestGoAuthorizesBidOpen(unittest.TestCase):
    """Behavioral: app.go() is the single choke point for opening a bid --
    it must consult the authenticated, RLS-backed lookup and fail closed
    on denial, using the already-imported, live app module."""

    def setUp(self):
        st.session_state["page"] = "dashboard"
        st.session_state["active_bid"] = None

    @patch("app._tenancy.get_bid_authenticated")
    @patch("streamlit.rerun")
    def test_authorized_bid_id_navigates(self, mock_rerun, mock_get_bid):
        mock_get_bid.return_value = {"id": 8, "title": "Authorized Bid"}
        app.go("stage_understand", 8)
        mock_get_bid.assert_called_once_with(app._access_token, 8)
        self.assertEqual(st.session_state["active_bid"], 8)
        self.assertEqual(st.session_state["page"], "stage_understand")
        mock_rerun.assert_called_once()

    @patch("app._tenancy.get_bid_authenticated", return_value=None)
    @patch("streamlit.error")
    @patch("streamlit.rerun")
    def test_unauthorized_or_nonexistent_bid_id_fails_closed(self, mock_rerun, mock_error, mock_get_bid):
        """A guessed/unauthorized bid_id: no navigation, no state change,
        an inline error instead -- instruction 3's exact requirement."""
        st.session_state["active_bid"] = None
        st.session_state["page"] = "dashboard"

        app.go("stage_understand", 999)

        mock_error.assert_called_once()
        self.assertIsNone(st.session_state["active_bid"])
        self.assertEqual(st.session_state["page"], "dashboard")  # unchanged
        mock_rerun.assert_not_called()

    @patch("streamlit.rerun")
    def test_navigation_without_a_bid_id_never_calls_authorization(self, mock_rerun):
        """Global nav (Dashboard, Content Library, etc.) passes bid_id=None
        -- no bid-access check should ever be attempted for those."""
        with patch("app._tenancy.get_bid_authenticated") as mock_get_bid:
            app.go("content_library")
            mock_get_bid.assert_not_called()
        self.assertEqual(st.session_state["page"], "content_library")


class TestLoginGateBehavior(unittest.TestCase):
    """Behavioral: with no session, importing app.py must reach the login
    gate and never reach dashboard-rendering code. Performed via a fresh,
    isolated reload -- session_state cleared, no live network calls
    (auth_client/tenancy calls mocked) -- so this proves actual behavior,
    not just source text."""

    def test_no_session_reaches_login_gate_not_dashboard(self):
        original_session = st.session_state.pop("bi_auth_session", None)
        original_context = st.session_state.pop("bi_auth_context", None)
        try:
            with patch("streamlit.text_input", return_value="") as mock_text_input, \
                 patch("streamlit.button", return_value=False), \
                 patch("streamlit.markdown"), \
                 patch("streamlit.success"), \
                 patch("streamlit.error"), \
                 patch("streamlit.stop") as mock_stop, \
                 patch("tenancy.list_bids_authenticated") as mock_list_bids:
                mock_stop.side_effect = RuntimeError("st.stop() called -- this is the expected halt")
                with self.assertRaises(RuntimeError):
                    importlib.reload(app)
                # The login screen's own email input must have been
                # rendered (proves _render_login_gate() actually ran)...
                mock_text_input.assert_called()
                # ...and the authenticated, RLS-backed bid listing must
                # NEVER have been reached.
                mock_list_bids.assert_not_called()
        finally:
            # Restore the faked authenticated session for every other test
            # in this process (module-level state, shared across files).
            if original_session is not None:
                st.session_state["bi_auth_session"] = original_session
            if original_context is not None:
                st.session_state["bi_auth_context"] = original_context
            with patch("tenancy.auth_client.get_authenticated_client",
                       return_value=MagicMock(**{
                           "table.return_value.select.return_value.order.return_value.execute.return_value": MagicMock(data=[]),
                           "table.return_value.select.return_value.eq.return_value.execute.return_value": MagicMock(data=[]),
                       })):
                importlib.reload(app)


if __name__ == "__main__":
    unittest.main()
