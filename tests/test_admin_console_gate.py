"""Super Admin MVP — admin console entry gate and client-app revalidation
placement. No live credentials, no network."""
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

import auth_session as auth
import platform_admin as pa

ROOT = Path(__file__).parents[1]
CONSOLE = str(ROOT / "admin_console.py")
ADMIN_ID = "11111111-1111-4111-8111-111111111111"
MEMBER_ID = "22222222-2222-4222-8222-222222222222"


def _signed_in(at, user_id, email):
    at.session_state[auth.SESSION_KEY] = {
        "access_token": "a", "refresh_token": "r", "user_id": user_id, "email": email, "expires_at": None}
    return at


def test_console_refuses_to_run_without_enable_flag():
    with patch.dict(os.environ, {"PLATFORM_ADMIN_CONSOLE_ENABLED": ""}), \
            patch.object(pa, "is_platform_admin") as is_admin:
        at = _signed_in(AppTest.from_file(CONSOLE), ADMIN_ID, "owner@example.com").run()
    assert not at.exception
    assert [e.value for e in at.error] == ["The platform admin console is not enabled in this deployment."]
    assert len(at.text_input) == 0
    is_admin.assert_not_called()


def test_unauthenticated_visitor_sees_only_sign_in():
    with patch.dict(os.environ, {"PLATFORM_ADMIN_CONSOLE_ENABLED": "1"}), \
            patch.object(pa, "list_users") as list_users:
        at = AppTest.from_file(CONSOLE).run()
    assert not at.exception
    assert "Platform admin sign-in" in at.markdown[0].value
    assert len(at.tabs) == 0
    list_users.assert_not_called()


def test_non_platform_admin_session_is_denied_and_signed_out():
    with patch.dict(os.environ, {"PLATFORM_ADMIN_CONSOLE_ENABLED": "1"}), \
            patch.object(pa, "require_platform_admin", side_effect=pa.PlatformAdminDenied("no")), \
            patch.object(pa, "list_users") as list_users, \
            patch.object(auth, "sign_out") as sign_out:
        at = _signed_in(AppTest.from_file(CONSOLE), MEMBER_ID, "member@phoenix.example").run()
    assert not at.exception
    assert "not a platform administrator" in at.error[0].value
    assert len(at.tabs) == 0
    sign_out.assert_called_once()
    list_users.assert_not_called()


def test_platform_admin_session_renders_console():
    with patch.dict(os.environ, {"PLATFORM_ADMIN_CONSOLE_ENABLED": "1"}), \
            patch.object(pa, "require_platform_admin", return_value=pa.PlatformAdminActor(ADMIN_ID, "o")), \
            patch.object(pa, "list_organizations", return_value=[]), \
            patch.object(pa, "list_users", return_value=[]), \
            patch.object(pa, "list_audit_log", return_value=[]):
        at = _signed_in(AppTest.from_file(CONSOLE), ADMIN_ID, "owner@example.com").run()
    assert not at.exception
    assert [t.label for t in at.tabs] == ["Users", "Organizations", "Audit trail"]


def test_client_app_revalidates_before_rendering_any_application_content():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    reval = src.index("_tenancy.revalidate_session_access(")
    assert src.index("_session_result = _auth_session.restore_session()") < reval
    assert reval < src.index("if isinstance(_ctx, _tenancy.NoOrganizationAccess):")
    block = src[reval: src.index("if isinstance(_ctx, _tenancy.NoOrganizationAccess):")]
    assert "_clear_all_user_scoped_state()" in block and "st.rerun()" in block
