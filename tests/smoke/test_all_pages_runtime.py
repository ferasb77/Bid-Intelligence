"""
Smoke Test: Verify all page render functions execute without NameError/SyntaxError
"""
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

import streamlit as st
import database
from tenancy import AuthContext

# Phase 8 remediation package 3: app.py's mandatory auth gate runs at
# import time -- simulate an already-authenticated, already-resolved
# session BEFORE importing app, so `import app` (which this smoke test has
# always relied on to verify the whole file has no syntax/import errors)
# continues to exercise the full file exactly as a real signed-in user's
# script run would, instead of hitting the login gate. user_id matches
# between the two so app.py's own reuse-path skips a live
# resolve_organization_context() call entirely (no network call).
_FAKE_USER_ID = "00000000-0000-0000-0000-000000000001"
st.session_state["bi_auth_session"] = {
    "access_token": "smoke-test-fake-access-token",
    "refresh_token": "smoke-test-fake-refresh-token",
    "user_id": _FAKE_USER_ID,
    "email": "smoke-test@example.com",
    "expires_at": time.time() + 3600,
}
st.session_state["bi_auth_context"] = AuthContext(
    user_id=_FAKE_USER_ID, email="smoke-test@example.com",
    organization_id="00000000-0000-0000-0000-000000000002",
    organization_name="Smoke Test Org", role="owner",
)

# The fake access_token above is not a real, signed Supabase JWT -- a real
# auth_client.get_authenticated_client() call with it would be rejected by
# Supabase outright. For this smoke test's purpose (does the RENDERING
# code run without a NameError/SyntaxError -- RLS enforcement itself is
# exhaustively covered by tests/test_tenant_rls_enforcement.py), the
# "authenticated" client is transparently the same real service-role
# client every other read in this test already uses, so real data (e.g.
# bid 8's actual persisted Fast Analysis result) still flows through and
# the full rendering body is still exercised, not just an early-return
# "not found" branch.
_patch_authenticated_client = patch(
    "tenancy.auth_client.get_authenticated_client", side_effect=lambda access_token: database.get_client()
)
_patch_authenticated_client.start()

import app
import pages.stage_understand as understand
import pages.stage_decide as decide
import pages.stage_build as build
import pages.stage_check as check
import pages.stage_submit as submit
import pages.stage_debrief as debrief
import pages.settings_firm as settings_firm
import pages_extra


def tearDownModule():
    _patch_authenticated_client.stop()


def mock_cols(spec, *args, **kwargs):
    count = spec if isinstance(spec, int) else (len(spec) if isinstance(spec, list) else 2)
    cols = []
    for _ in range(count):
        col = MagicMock()
        col.button.return_value = False
        col.form_submit_button.return_value = False
        col.checkbox.return_value = False
        col.download_button.return_value = False
        cols.append(col)
    return cols


def mock_tabs(tab_list, *args, **kwargs):
    return [MagicMock() for _ in range(len(tab_list))]


class TestAllPagesRuntime(unittest.TestCase):

    def setUp(self):
        self.bid_id = 8

    @patch("streamlit.markdown")
    @patch("streamlit.columns", side_effect=mock_cols)
    @patch("streamlit.button", return_value=False)
    @patch("streamlit.text_input", return_value="")
    @patch("streamlit.text_area", return_value="")
    @patch("streamlit.form")
    def test_settings_firm_page_executes(self, *args):
        mock_form = MagicMock()
        mock_form.__enter__.return_value = mock_form
        mock_form.form_submit_button.return_value = False
        args[0].return_value = mock_form
        settings_firm.page_settings_firm()

    @patch("streamlit.markdown")
    @patch("streamlit.columns", side_effect=mock_cols)
    @patch("streamlit.button", return_value=False)
    @patch("streamlit.tabs", side_effect=mock_tabs)
    def test_stage_understand_page_executes(self, *args):
        understand.page_understand(self.bid_id)

    @patch("streamlit.markdown")
    @patch("streamlit.columns", side_effect=mock_cols)
    @patch("streamlit.button", return_value=False)
    @patch("streamlit.tabs", side_effect=mock_tabs)
    def test_stage_decide_page_executes(self, *args):
        decide.page_decide(self.bid_id)

    @patch("streamlit.markdown")
    @patch("streamlit.columns", side_effect=mock_cols)
    @patch("streamlit.button", return_value=False)
    @patch("streamlit.tabs", side_effect=mock_tabs)
    def test_stage_build_page_executes(self, *args):
        build.page_build(self.bid_id)

    @patch("streamlit.markdown")
    @patch("streamlit.columns", side_effect=mock_cols)
    @patch("streamlit.button", return_value=False)
    @patch("streamlit.tabs", side_effect=mock_tabs)
    def test_stage_check_page_executes(self, *args):
        check.page_check(self.bid_id)

    @patch("streamlit.markdown")
    @patch("streamlit.columns", side_effect=mock_cols)
    @patch("streamlit.button", return_value=False)
    @patch("streamlit.checkbox", return_value=False)
    def test_stage_submit_page_executes(self, *args):
        submit.page_submit(self.bid_id)

    @patch("streamlit.markdown")
    @patch("streamlit.columns", side_effect=mock_cols)
    @patch("streamlit.button", return_value=False)
    @patch("streamlit.number_input", return_value=0.0)
    @patch("streamlit.selectbox", return_value="Pending")
    @patch("streamlit.form")
    def test_stage_debrief_page_executes(self, *args):
        mock_form = MagicMock()
        mock_form.__enter__.return_value = mock_form
        mock_form.form_submit_button.return_value = False
        args[0].return_value = mock_form
        debrief.page_debrief(self.bid_id)


if __name__ == "__main__":
    unittest.main()
