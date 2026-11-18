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


@pytest.mark.parametrize("flow", ["hash", "invite", "fragment"])
def test_recovery_does_not_grant_application_session(flow, client):
    st.session_state[auth.SESSION_KEY] = {"user_id": "previous-user"}
    st.session_state[auth.AUTH_CONTEXT_KEY] = "previous-organization"
    params = ({"token_hash": "test-hash", "type": "recovery"} if flow == "hash"
              else {"token_hash": "test-hash", "type": "invite"} if flow == "invite"
              else {"sb_at": "test-access", "sb_rt": "test-refresh", "sb_type": "recovery"})
    params["unrelated"] = "keep"
    with patch.object(st, "query_params", params), patch("tenancy.resolve_organization_context") as resolve:
        result = (auth.handle_fragment_session_callback() if flow == "fragment"
                  else auth.handle_invite_callback())
    assert result.ok
    assert auth.password_setup_required()
    if flow == "fragment":
        assert st.session_state[auth.RECOVERY_SESSION_KEY]["user_id"] == "test-user"
    else:
        # Setup links are NOT redeemed on open -- only when a password is saved.
        client.auth.verify_otp.assert_not_called()
        expected_type = "recovery" if flow == "hash" else "invite"
        assert st.session_state[auth.PENDING_SETUP_KEY]["type"] == expected_type
    assert not auth.restore_session().ok
    assert auth.AUTH_CONTEXT_KEY not in st.session_state
    assert params == {"unrelated": "keep"}
    resolve.assert_not_called()


def open_setup_link(link_type="recovery"):
    params = {"token_hash": "test-hash", "type": link_type}
    with patch.object(st, "query_params", params):
        assert auth.handle_invite_callback().ok
    assert not params


def test_opening_link_without_saving_leaves_token_unspent(client):
    """Root-cause regression: opening the link, then refreshing / closing the
    tab before saving a password, must not consume the single-use token."""
    open_setup_link()
    st.session_state.clear()  # refresh or new browser session
    client.auth.verify_otp.assert_not_called()
    open_setup_link()  # the same link works again
    assert auth.update_recovered_password("long-password", "long-password").ok
    client.auth.verify_otp.assert_called_once_with({"token_hash": "test-hash", "type": "recovery"})


@pytest.mark.parametrize("password,confirmation", [("short", "short"), ("long-password", "different")])
def test_invalid_input_does_not_spend_pending_link(password, confirmation, client):
    open_setup_link()
    assert not auth.update_recovered_password(password, confirmation).ok
    client.auth.verify_otp.assert_not_called()
    assert auth.password_setup_required()


@pytest.mark.parametrize("link_type", ["recovery", "invite"])
def test_pending_link_redeemed_with_password_then_signed_out(link_type, client):
    open_setup_link(link_type)
    assert auth.update_recovered_password("long-password", "long-password").ok
    client.auth.verify_otp.assert_called_once_with({"token_hash": "test-hash", "type": link_type})
    sent = client.auth.update_user.call_args.args[0]
    assert sent["password"] == "long-password"
    assert sent["data"][auth.PASSWORD_SET_METADATA_KEY]
    client.auth.sign_out.assert_called_once_with({"scope": "local"})
    assert not auth.password_setup_required()
    assert not auth.restore_session().ok


def test_unusable_pending_link_fails_safely(client):
    open_setup_link()
    client.auth.verify_otp.side_effect = Exception("sensitive provider details")
    result = auth.update_recovered_password("long-password", "long-password")
    assert not result.ok
    assert result.error == auth.SETUP_LINK_UNUSABLE_MESSAGE
    client.auth.update_user.assert_not_called()
    assert not auth.password_setup_required()


def test_pending_link_is_isolated_per_browser_session(client):
    """The pending token lives only in the opening browser's Streamlit
    session; another session (different browser/user) cannot redeem it."""
    script = '''
import auth_session as auth
import streamlit as st
auth.handle_invite_callback()
st.markdown("setup" if auth.password_setup_required() else "sign-in")
'''
    opener = AppTest.from_string(script)
    opener.query_params["token_hash"] = "test-hash"
    opener.query_params["type"] = "recovery"
    opener.run()
    other = AppTest.from_string(script).run()
    assert opener.markdown[0].value == "setup"
    assert other.markdown[0].value == "sign-in"
    assert auth.PENDING_SETUP_KEY not in other.session_state
    assert not opener.query_params.get("token_hash") and not opener.query_params.get("type")


def test_existing_password_user_sign_in_unaffected(client):
    session = SimpleNamespace(access_token="a", refresh_token="r", expires_at=None)
    user = SimpleNamespace(id="existing", email="existing@example.com")
    client.auth.sign_in_with_password.return_value = SimpleNamespace(session=session, user=user)
    assert auth.sign_in("existing@example.com", "their-password").ok
    assert auth.restore_session().user_id == "existing"
    client.auth.verify_otp.assert_not_called()
    client.auth.update_user.assert_not_called()
    assert not auth.password_setup_required()


def test_sign_in_and_sign_out_clear_pending_link(client):
    open_setup_link()
    auth.sign_out()
    assert not auth.password_setup_required()


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
    assert client.auth.update_user.call_args.args[0]["password"] == "long-password"
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


@pytest.mark.parametrize("flow", ["email", "fragment"])
def test_expired_callback_is_rejected_and_credentials_removed(flow, client):
    params = ({"token_hash": "expired", "type": "email"} if flow == "email"
              else {"sb_at": "expired", "sb_rt": "expired", "sb_type": "recovery"})
    client.auth.verify_otp.side_effect = Exception("sensitive")
    client.auth.set_session.side_effect = Exception("sensitive")
    with patch.object(st, "query_params", params):
        result = (auth.handle_invite_callback() if flow == "email"
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
    assert client.auth.update_user.call_args.args[0]["password"] == "long-password"


def test_first_time_setup_end_to_end_in_app_shell(client):
    """Link open -> password form (no app session) -> save -> sign-in page ->
    sign in -> sign out -> sign in again, through the same callbacks/gates
    app.py uses (provider mocked)."""
    script = '''
import auth_session as auth
import streamlit as st
auth.handle_invite_callback()
if auth.password_setup_required():
    auth.render_password_recovery()
if auth.restore_session().ok:
    st.markdown("APP HOME")
    if st.button("Sign out"):
        auth.sign_out()
        st.rerun()
    st.stop()
if st.session_state.pop("bi_password_reset_complete", False):
    st.success("Password saved")
with st.form("sign_in"):
    e = st.text_input("Email address")
    p = st.text_input("Password", type="password")
    go = st.form_submit_button("Sign in")
if go and auth.sign_in(e, p).ok:
    st.rerun()
'''
    session = SimpleNamespace(access_token="a", refresh_token="r", expires_at=None)
    user = SimpleNamespace(id="test-user", email="test@example.com")
    client.auth.sign_in_with_password.return_value = SimpleNamespace(session=session, user=user)
    app = AppTest.from_string(script)
    app.query_params["token_hash"] = "test-hash"
    app.query_params["type"] = "recovery"
    app.run()
    assert not app.exception
    assert "Set your password" in app.markdown[0].value
    assert not any(m.value == "APP HOME" for m in app.markdown)
    client.auth.verify_otp.assert_not_called()
    app.text_input[0].input("long-password")
    app.text_input[1].input("long-password")
    app.button[0].click().run()
    assert app.success[0].value == "Password saved"
    client.auth.verify_otp.assert_called_once()
    for _ in range(2):  # sign in, sign out, sign in again
        app.text_input[0].input("test@example.com")
        app.text_input[1].input("long-password")
        app.button[0].click().run()
        assert any(m.value == "APP HOME" for m in app.markdown)
        app.button[0].click().run()
        assert not any(m.value == "APP HOME" for m in app.markdown)
    assert client.auth.sign_in_with_password.call_count == 2


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
    assert "Set your password" in app.markdown[0].value
    app.text_input[0].input("long-password")
    app.text_input[1].input("different")
    app.button[0].click().run()
    assert not app.exception
    assert [error.value for error in app.error] == ["The passwords do not match."]
    client.auth.update_user.assert_not_called()


def test_recovery_form_precedes_application_auth_gate():
    source = (Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8")
    assert source.index("_auth_session.render_password_recovery()") < source.index("_auth_session.restore_session()")
    assert "if _auth_session.password_setup_required():" in source
