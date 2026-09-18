"""Recovery routing and password updates; no live credentials or emails."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import auth_session as auth


@pytest.fixture(autouse=True)
def isolated_session():
    st.session_state.clear()
    try:
        from streamlit.delta_generator_singletons import context_dg_stack, get_default_dg_stack_value
        context_dg_stack.set(get_default_dg_stack_value())
        st._main._form_data = None
    except Exception:
        pass
    yield
    st.session_state.clear()
    try:
        from streamlit.delta_generator_singletons import context_dg_stack, get_default_dg_stack_value
        context_dg_stack.set(get_default_dg_stack_value())
        st._main._form_data = None
    except Exception:
        pass


@pytest.fixture
def client():
    session = SimpleNamespace(access_token="test-access", refresh_token="test-refresh")
    user = SimpleNamespace(id="test-user", email="test@example.com")
    client = MagicMock()
    client.auth.verify_otp.return_value = SimpleNamespace(session=session, user=user)
    client.auth.set_session.return_value = SimpleNamespace(session=session, user=user)
    client.auth.update_user.return_value = SimpleNamespace(user=user)
    with patch.object(auth, "get_auth_client", return_value=client):
        yield client


@pytest.mark.parametrize("flow", ["hash", "fragment"])
def test_recovery_does_not_grant_application_session(flow, client):
    st.session_state[auth.SESSION_KEY] = {"user_id": "previous-user"}
    st.session_state[auth.AUTH_CONTEXT_KEY] = "previous-organization"
    params = ({"token_hash": "test-hash", "type": "recovery"} if flow == "hash"
              else {"sb_at": "test-access", "sb_rt": "test-refresh", "sb_type": "recovery"})
    params["unrelated"] = "keep"
    with patch.object(st, "query_params", params), patch("tenancy.resolve_organization_context") as resolve:
        result = (auth.handle_invite_callback() if flow == "hash"
                  else auth.handle_fragment_session_callback())
    assert result.ok
    assert st.session_state[auth.RECOVERY_SESSION_KEY]["user_id"] == "test-user"
    assert not auth.restore_session().ok
    assert auth.AUTH_CONTEXT_KEY not in st.session_state
    assert params == {"unrelated": "keep"}
    resolve.assert_not_called()


def prepare_recovery(client):
    response = client.auth.verify_otp.return_value
    auth._store_recovery_session(response.session, response.user)


def test_password_update_requires_recovery_session(client):
    result = auth.update_recovered_password("long-password", "long-password")
    assert not result.ok
    client.auth.update_user.assert_not_called()


@pytest.mark.parametrize("password,confirmation", [("short", "short"), ("long-password", "different")])
def test_invalid_password_input_never_calls_provider(password, confirmation, client):
    prepare_recovery(client)
    assert not auth.update_recovered_password(password, confirmation).ok
    client.auth.set_session.assert_not_called()
    client.auth.update_user.assert_not_called()


def test_update_uses_recovery_credentials_and_clears_them(client):
    prepare_recovery(client)
    assert auth.update_recovered_password("long-password", "long-password").ok
    client.auth.set_session.assert_called_once_with("test-access", "test-refresh")
    client.auth.update_user.assert_called_once_with({"password": "long-password"})
    client.auth.sign_out.assert_called_once_with({"scope": "local"})
    assert auth.RECOVERY_SESSION_KEY not in st.session_state
    assert not auth.restore_session().ok


def test_failed_update_keeps_rotated_tokens_for_retry(client):
    prepare_recovery(client)
    client.auth.set_session.return_value.session = SimpleNamespace(
        access_token="rotated-access", refresh_token="rotated-refresh")
    client.auth.update_user.side_effect = Exception("sensitive provider details")
    result = auth.update_recovered_password("long-password", "long-password")
    assert not result.ok
    assert "sensitive" not in result.error
    assert st.session_state[auth.RECOVERY_SESSION_KEY]["refresh_token"] == "rotated-refresh"


def test_expired_recovery_session_cannot_update_password(client):
    prepare_recovery(client)
    client.auth.set_session.side_effect = Exception("expired")
    assert not auth.update_recovered_password("long-password", "long-password").ok
    client.auth.update_user.assert_not_called()
    assert auth.RECOVERY_SESSION_KEY not in st.session_state


def test_identity_mismatch_cannot_update_password(client):
    prepare_recovery(client)
    client.auth.set_session.return_value.user = SimpleNamespace(id="someone-else")
    assert not auth.update_recovered_password("long-password", "long-password").ok
    client.auth.update_user.assert_not_called()


@pytest.mark.parametrize("flow", ["hash", "fragment"])
def test_expired_callback_is_rejected_and_credentials_removed(flow, client):
    params = ({"token_hash": "expired", "type": "recovery"} if flow == "hash"
              else {"sb_at": "expired", "sb_rt": "expired", "sb_type": "recovery"})
    client.auth.verify_otp.side_effect = Exception("sensitive")
    client.auth.set_session.side_effect = Exception("sensitive")
    with patch.object(st, "query_params", params):
        result = (auth.handle_invite_callback() if flow == "hash"
                  else auth.handle_fragment_session_callback())
    assert not result.ok
    assert "sensitive" not in result.error
    assert not params
    assert auth.RECOVERY_SESSION_KEY not in st.session_state


def test_partial_fragment_is_removed(client):
    params = {"sb_at": "test-access", "sb_type": "recovery"}
    with patch.object(st, "query_params", params):
        assert not auth.handle_fragment_session_callback().ok
    assert not params
    client.auth.set_session.assert_not_called()


def test_expired_link_error_is_safe_and_removed(client):
    params = {"error": "access_denied", "error_description": "sensitive", "sb_type": "recovery"}
    with patch.object(st, "query_params", params):
        result = auth.handle_fragment_session_callback()
    assert not result.ok
    assert "expired" in result.error
    assert "sensitive" not in result.error
    assert not params
    client.auth.set_session.assert_not_called()


def test_partial_hash_callback_is_removed(client):
    params = {"token_hash": "test-hash"}
    with patch.object(st, "query_params", params):
        assert not auth.handle_invite_callback().ok
    assert not params
    client.auth.verify_otp.assert_not_called()


def test_form_success_returns_to_sign_in(client):
    app = AppTest.from_string('''
import auth_session as auth
import streamlit as st
if "initialized" not in st.session_state:
    st.session_state["initialized"] = True
    st.session_state[auth.RECOVERY_SESSION_KEY] = {
        "user_id": "test-user", "access_token": "test-access", "refresh_token": "test-refresh"}
if st.session_state.get(auth.RECOVERY_SESSION_KEY):
    auth.render_password_recovery()
if st.session_state.pop("bi_password_reset_complete", False):
    st.success("Password updated")
st.markdown("Sign in")
''').run()
    app.text_input[0].input("long-password")
    app.text_input[1].input("long-password")
    app.button[0].click().run()
    assert not app.exception
    assert app.success[0].value == "Password updated"
    assert len(app.text_input) == 0
    client.auth.update_user.assert_called_once_with({"password": "long-password"})


def test_reset_form_survives_rerun_and_shows_validation_error(client):
    app = AppTest.from_string('''
import auth_session as auth
import streamlit as st
if auth.RECOVERY_SESSION_KEY not in st.session_state:
    st.session_state[auth.RECOVERY_SESSION_KEY] = {"user_id": "test-user"}
auth.render_password_recovery()
st.error("Application data must not render")
''').run()
    assert not app.exception
    assert "Reset your password" in app.markdown[0].value
    app.text_input[0].input("long-password")
    app.text_input[1].input("different")
    app.button[0].click().run()
    assert not app.exception
    assert [error.value for error in app.error] == ["The passwords do not match."]
    client.auth.update_user.assert_not_called()


def test_recovery_form_precedes_application_auth_gate():
    source = (Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8")
    assert source.index("_auth_session.render_password_recovery()") < source.index("_auth_session.restore_session()")
