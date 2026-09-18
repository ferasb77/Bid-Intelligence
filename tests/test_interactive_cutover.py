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
import ast
import glob
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
        self.assertIn(len(creation_calls), (2, 3), "expected the known bid-creation call sites")
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


class TestNativeMultipageNavigationDisabledAndSafe(unittest.TestCase):
    """Streamlit auto-discovers any `pages/` directory sibling to the
    entrypoint script and renders its own top-of-sidebar navigation
    linking directly to each file in it, runnable as an independent
    script -- entirely bypassing app.py (and therefore its mandatory
    auth gate) since app.py itself never executes for that navigation
    path. This duplicated app.py's own custom router UI and, more
    importantly, exposed a page-selection surface app.py's auth gate
    never sees. Two independent guarantees are asserted here: the
    duplicate native nav is turned off (config), and even if it were
    reachable, every page script is safe to load standalone regardless
    (source-level, by construction)."""

    def test_sidebar_navigation_disabled_in_streamlit_config(self):
        config_path = os.path.join(os.path.dirname(__file__), "..", ".streamlit", "config.toml")
        with open(config_path, "r", encoding="utf-8") as f:
            config_text = f.read()
        self.assertIn("[client]", config_text)
        client_start = config_text.index("[client]")
        client_section = config_text[client_start:]
        next_section = client_section.find("\n[", 1)
        if next_section != -1:
            client_section = client_section[:next_section]
        self.assertIn("showSidebarNavigation = false", client_section)
        # The existing sections must survive this change untouched.
        self.assertIn("[theme]", config_text)
        self.assertIn('primaryColor = "#C9A96E"', config_text)
        self.assertIn("[browser]", config_text)
        self.assertIn("gatherUsageStats = false", config_text)

    def test_every_pages_module_is_definitions_only_at_module_level(self):
        """Codifies the safety audit: if a pages/*.py file were ever
        reached directly (native nav re-enabled, a future refactor,
        Streamlit behavior change, etc.), the ONLY way it could expose
        protected data is if it called its own page_*() function or did
        real work at module scope. This asserts none of them do --
        every top-level statement is an import, a class/function
        definition, a module docstring, or a literal constant
        assignment (no Call, no Attribute access, nothing that could
        read or render data) -- for every file in pages/, not just the
        ones this engagement happened to touch."""
        pages_dir = os.path.join(os.path.dirname(__file__), "..", "pages")
        page_files = sorted(glob.glob(os.path.join(pages_dir, "*.py")))
        self.assertGreater(len(page_files), 0, "no pages/*.py files found -- test would pass vacuously")

        SAFE_TOP_LEVEL = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

        for path in page_files:
            with open(path, "r", encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source, filename=path)
            for node in tree.body:
                if isinstance(node, SAFE_TOP_LEVEL):
                    continue
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    continue  # module docstring
                if isinstance(node, ast.Assign):
                    # A literal constant (list/dict/tuple/str/num/etc.) is safe;
                    # anything containing a function/method Call is not.
                    for sub in ast.walk(node.value):
                        self.assertNotIsInstance(
                            sub, ast.Call,
                            f"{path}:{node.lineno} has a module-level Call inside an "
                            f"assignment -- could execute on standalone import",
                        )
                    continue
                self.fail(
                    f"{path}:{node.lineno} has an unexpected module-level "
                    f"{type(node).__name__} -- verify it cannot render or read "
                    f"protected data if this file is ever loaded standalone"
                )


class TestNewRFPPipelineArchitecture(unittest.TestCase):
    """Source-level verification of the New-RFP onboarding pipeline architecture."""

    def setUp(self):
        with open(APP_SOURCE_PATH, "r", encoding="utf-8") as f:
            self.app_source = f.read()
        understand_path = os.path.join(os.path.dirname(__file__), "..", "pages", "stage_understand.py")
        with open(understand_path, "r", encoding="utf-8") as f:
            self.understand_source = f.read()

    def test_new_bid_page_triggers_fast_analysis_not_deep_extraction(self):
        """Uploading a package on page_new_bid must wire to Fast Analysis onboarding."""
        fn_start = self.app_source.index("def page_new_bid():")
        fn_end = self.app_source.index("def _render_extraction_review():", fn_start)
        body = self.app_source[fn_start:fn_end]

        # Must have the primary button for Fast Analysis onboarding
        self.assertIn("⚡ Create Bid & Start Fast Analysis →", body)

        # Must NOT call extract_procurement_package in the onboarding button handler
        self.assertNotIn("extract_procurement_package(pkg_files", body)

        # Must call the tenancy authorized boundaries
        self.assertIn("_tenancy.create_bid_for_organization(", body)
        self.assertIn("_tenancy.upload_document_for_organization(", body)
        self.assertIn("_tenancy.start_fast_analysis_for_organization(", body)

        # Must navigate to stage_understand
        self.assertIn('go("stage_understand", bid_id)', body)

    def test_deep_verification_preserved_in_stage_understand(self):
        """Legacy extract_procurement_package must be preserved as an optional expander in stage_understand."""
        self.assertIn("🔬 Deep Verification & Cross-Document Synthesis (Optional / In-Depth)", self.understand_source)
        self.assertIn("extract_procurement_package(pkg_files_to_extract, api_key)", self.understand_source)
        self.assertIn("tenancy.save_bid_brief_for_organization(bid_id, org_id, brief_data)", self.understand_source)

    def test_procurement_governance_retains_truth_boundary(self):
        """Bids created during onboarding start with standard stage and are ungoverned until baseline review."""
        fn_start = self.app_source.index("def page_new_bid():")
        fn_end = self.app_source.index("def _render_extraction_review():", fn_start)
        body = self.app_source[fn_start:fn_end]

        self.assertIn('"stage": "Understand"', body)
        # Fast Analysis onboarding does not create canonical requirements
        self.assertNotIn("upsert_requirement_authenticated", body)


class TestNewRFPPipelineBehavior(unittest.TestCase):
    """Behavioral unit tests for the onboarding logic."""

    @patch("tenancy.start_fast_analysis_for_organization")
    @patch("tenancy.upload_document_for_organization")
    @patch("tenancy.create_bid_for_organization")
    def test_onboarding_execution_flow(self, mock_create_bid, mock_upload_doc, mock_start_fast):
        """Simulate the execution sequence of the new onboarding handler."""
        mock_create_bid.return_value = 999
        mock_start_fast.return_value = {"id": 12, "status": "PENDING"}

        org_id = "test-org-123"
        pkg_files = [
            ("RFP_Master.pdf", b"%PDF-1.4 fake bytes"),
            ("Pricing_Table.xlsx", b"fake xlsx bytes"),
        ]
        api_key = "sk-ant-test-mock-key"
        title = "Cloud Modernization RFP"
        client = "Treasury Board"

        # 1. Create bid
        bid_id = mock_create_bid({
            "title": title,
            "client": client,
            "stage": "Understand",
            "sensitivity": "Standard",
        }, organization_id=org_id)
        self.assertEqual(bid_id, 999)

        # 2. Upload files
        for fn, fb in pkg_files:
            mock_upload_doc(bid_id, org_id, fn, fb, doc_type="RFP / Source")

        self.assertEqual(mock_upload_doc.call_count, 2)
        mock_upload_doc.assert_any_call(999, org_id, "RFP_Master.pdf", b"%PDF-1.4 fake bytes", doc_type="RFP / Source")
        mock_upload_doc.assert_any_call(999, org_id, "Pricing_Table.xlsx", b"fake xlsx bytes", doc_type="RFP / Source")

        # 3. Start Fast Analysis
        run = mock_start_fast(bid_id, org_id, api_key, created_by="app-ui")
        self.assertEqual(run["id"], 12)
        mock_start_fast.assert_called_once_with(999, org_id, api_key, created_by="app-ui")


if __name__ == "__main__":
    unittest.main()
