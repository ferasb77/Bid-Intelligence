"""
auth_session.py — Streamlit-facing authentication session abstraction.

Phase 8 remediation package 2. The smallest robust session handling this
package needs: sign in, sign out, and best-effort session restoration
across Streamlit reruns. Authentication is NOT mandatory anywhere in the
application yet (instruction 11) -- no page currently calls into this
module; it exists, tested, ahead of that switch-over.

What this module does NOT do, deliberately:
  * No public self-registration / "Create Account" flow (instruction 6).
    Only sign_in() against an already-provisioned Supabase Auth user.
  * No password is ever stored -- sign_in() takes one as a plain argument,
    hands it directly to Supabase Auth over the auth_client (anon-key)
    connection, and never retains it (not in Streamlit session state, not
    logged, not in any exception message -- see _safe_auth_error()).
  * No service-role credential is ever stored in Streamlit session state --
    only the signed-in user's own access/refresh tokens are, and only
    because Supabase Auth's own session object requires them to support
    later calls (e.g. sign-out, token refresh) without re-authenticating.

Session lifecycle and risk, documented precisely per instruction 16:
  * On successful sign-in, `st.session_state[SESSION_KEY]` holds a plain
    dict: {"access_token", "refresh_token", "user_id", "email"}. These are
    the *user's own* short-lived Supabase Auth tokens (the same tokens any
    Supabase client-side app would hold after sign-in) -- not a privileged
    credential, and scoped to whatever RLS eventually grants that user
    (currently nothing, since no policy exists yet -- package 3).
  * Streamlit's `session_state` lives only in the server process's memory
    for that browser session; it is not persisted to disk, not shared
    across browser sessions, and is lost on a full process restart -- the
    same limitation already documented for Fast Analysis's background
    threads (analysis_service.py) and for the same underlying reason (this
    app has no external session store). restore_session() only ever
    restores from that in-memory dict; it does not independently validate
    the token against Supabase on every rerun (no network call on every
    page load) -- token expiry is surfaced the next time an authenticated
    Supabase call actually fails, not proactively.
  * sign_out() clears the dict and calls Supabase Auth's own sign-out
    (best-effort; a failure there still clears local state so the UI
    cannot get stuck "signed in" locally after a successful local
    sign-out intent).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from auth_client import get_auth_client

SESSION_KEY = "bi_auth_session"
AUTH_CONTEXT_KEY = "bi_auth_context"
RECOVERY_SESSION_KEY = "bi_recovery_session"
# 'invite' -- the original Supabase Auth invite-acceptance flow, valid only
# once per user (Supabase's invite endpoint refuses to re-send once an
# account is confirmed -- see 'email' below for the fallback that covers
# every later sign-in of an already-registered user).
# 'email' -- the token_hash type Supabase's verify_otp() expects for a
# passwordless magic-link sign-in (sign_in_with_otp()) for an EXISTING,
# already-registered user; added for exactly that reason: the bootstrap
# real user's first invite was already accepted (and its session then
# revoked after the tokens were exposed in the browser's URL fragment
# during troubleshooting), so a second 'invite' call is rejected by
# Supabase's own API (HTTP 422, 'already been registered') -- magic-link
# sign-in is the correct, still-token-hash-based, still-never-exposes-a-
# raw-token-to-this-server mechanism for that case, and for every future
# passwordless sign-in this real user performs.
INVITE_CALLBACK_ACCEPTED_TYPES = ("invite", "email", "recovery")


@dataclass(frozen=True)
class AuthResult:
    ok: bool
    user_id: str | None = None
    email: str | None = None
    error: str | None = None


def _safe_auth_error(exc: Exception) -> str:
    """Never echo raw provider exception text back to the UI/logs -- it can
    include request detail we don't need to retain. A short, fixed,
    non-identifying message is enough for a sign-in failure."""
    return "sign-in failed: invalid credentials or authentication service unavailable"


def sign_in(email: str, password: str) -> AuthResult:
    """Sign in an already-provisioned Supabase Auth user. Never creates an
    account (instruction 6) -- Supabase's sign_in_with_password() call
    itself only authenticates an existing user; it cannot create one."""
    email_clean = email.strip() if email else ""
    if not email_clean or not password:
        return AuthResult(ok=False, error="email and password are required")
    try:
        client = get_auth_client()
        resp = client.auth.sign_in_with_password({"email": email_clean, "password": password})
    except Exception as e:
        return AuthResult(ok=False, error=_safe_auth_error(e))

    session = getattr(resp, "session", None)
    user = getattr(resp, "user", None)
    if not session or not user:
        return AuthResult(ok=False, error="invalid credentials")

    import streamlit as st
    st.session_state.pop(RECOVERY_SESSION_KEY, None)
    st.session_state.pop(AUTH_CONTEXT_KEY, None)
    st.session_state[SESSION_KEY] = {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "user_id": user.id,
        "email": user.email,
        "expires_at": getattr(session, "expires_at", None),
    }
    return AuthResult(ok=True, user_id=user.id, email=user.email)


def request_password_reset(email: str, redirect_to: str | None = None) -> AuthResult:
    """Request a Supabase password reset email.
    Safe failure: never reveals whether the email exists.
    Uses only the public anon client, never the service role client."""
    email_clean = email.strip() if email else ""
    if not email_clean:
        return AuthResult(ok=False, error="Email is required")
    try:
        client = get_auth_client()
        options = {}
        if redirect_to:
            options["redirect_to"] = redirect_to
        client.auth.reset_password_for_email(email_clean, options=options)
    except Exception:
        # Never leak provider details or user existence
        pass
    return AuthResult(ok=True, email=email_clean)


def sign_out() -> None:
    """Clears local session state unconditionally, even if the remote
    sign-out call fails -- a failed remote call must never leave the UI
    looking signed-in when the user asked to sign out. Clears the resolved
    AuthContext/organization context too -- no privileged or
    organization-scoped data may remain reachable after logout."""
    import streamlit as st
    stored = st.session_state.get(RECOVERY_SESSION_KEY) or current_session()
    try:
        client = get_auth_client()
        if stored and stored.get("access_token") and stored.get("refresh_token"):
            client.auth.set_session(stored["access_token"], stored["refresh_token"])
        client.auth.sign_out()
    except Exception:
        pass
    import streamlit as st
    st.session_state.pop(SESSION_KEY, None)
    st.session_state.pop(AUTH_CONTEXT_KEY, None)
    st.session_state.pop(RECOVERY_SESSION_KEY, None)


def current_session() -> dict | None:
    import streamlit as st
    return st.session_state.get(SESSION_KEY)


def handle_invite_callback() -> AuthResult:
    """Handles Supabase's token_hash-based auth callback for this
    bootstrap (Phase 8 remediation package 3 authenticated cutover): the
    original `type=invite` flow, and `type=email` (the token_hash type
    Supabase's verify_otp() expects for a magic-link sign-in) for every
    sign-in after a user's first invite has already been accepted
    (Supabase's own invite endpoint refuses to re-send once an account is
    confirmed, so magic-link sign-in is the correct mechanism for any
    later sign-in of the same real user -- see
    INVITE_CALLBACK_ACCEPTED_TYPES). Call this once,
    early -- before rendering any normal page content. It is a safe no-op
    (returns ok=False, error='no invite callback present') whenever the
    expected query parameters are absent, so it never affects ordinary
    page loads.

    Only the types in INVITE_CALLBACK_ACCEPTED_TYPES are accepted.
    Recovery sessions are isolated from ordinary application sessions.
    This uses ONLY the anon/public auth client
    (auth_client.get_auth_client()) to call verify_otp -- never the
    service-role client. On success, resolves the real AuthContext via
    tenancy.resolve_organization_context() and stores both the session and
    the AuthContext in st.session_state. The one-time token_hash/type pair
    is stripped from the visible URL immediately after processing --
    success or failure -- so it can never be re-used, bookmarked, or
    reshared from the browser's address bar or history. Never logs or
    prints token_hash, access_token, or refresh_token anywhere."""
    import streamlit as st

    params = st.query_params
    token_hash = params.get("token_hash")
    otp_type = params.get("type")

    if not token_hash and not otp_type:
        return AuthResult(ok=False, error="no invite callback present")
    if not token_hash or not otp_type:
        st.query_params.pop("token_hash", None)
        st.query_params.pop("type", None)
        return AuthResult(ok=False, error="incomplete authentication link; request a fresh link")

    if otp_type not in INVITE_CALLBACK_ACCEPTED_TYPES:
        # Not an accepted bootstrap flow -- reject without processing, but
        # still strip the params so an unsupported token_hash never sits
        # in the visible URL.
        st.query_params.pop("token_hash", None)
        st.query_params.pop("type", None)
        return AuthResult(ok=False, error=f"unsupported callback type: {otp_type}")

    try:
        client = get_auth_client()
        resp = client.auth.verify_otp({"token_hash": token_hash, "type": otp_type})
    except Exception:
        st.query_params.pop("token_hash", None)
        st.query_params.pop("type", None)
        return AuthResult(ok=False, error="invite verification failed: invalid or expired link")

    # Always strip the one-time token from the visible URL immediately,
    # regardless of outcome.
    st.query_params.pop("token_hash", None)
    st.query_params.pop("type", None)

    session = getattr(resp, "session", None)
    user = getattr(resp, "user", None)
    if not session or not user:
        return AuthResult(ok=False, error="invite verification did not return a valid session")

    if otp_type == "recovery":
        return _store_recovery_session(session, user)

    st.session_state.pop(RECOVERY_SESSION_KEY, None)
    st.session_state[SESSION_KEY] = {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "user_id": user.id,
        "email": user.email,
        "expires_at": getattr(session, "expires_at", None),
    }

    import tenancy
    st.session_state[AUTH_CONTEXT_KEY] = tenancy.resolve_organization_context(user.id, user.email)

    return AuthResult(ok=True, user_id=user.id, email=user.email)


def current_auth_context():
    """The AuthContext/NoOrganizationAccess/OrganizationSelectionRequired
    resolved by handle_invite_callback() (or, once wired, by a future
    sign_in()-time resolution) -- None if nothing has been resolved yet
    this session."""
    import streamlit as st
    return st.session_state.get(AUTH_CONTEXT_KEY)


def _store_recovery_session(session, user) -> AuthResult:
    """Only called after Supabase has authenticated the recovery credentials."""
    import streamlit as st
    st.session_state.pop(SESSION_KEY, None)
    st.session_state.pop(AUTH_CONTEXT_KEY, None)
    st.session_state[RECOVERY_SESSION_KEY] = {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "user_id": user.id,
    }
    return AuthResult(ok=True, user_id=user.id, email=user.email)


def update_recovered_password(password: str, confirmation: str) -> AuthResult:
    """Update only the verified recovery user, through the public auth client."""
    import streamlit as st
    stored = st.session_state.get(RECOVERY_SESSION_KEY)
    if not stored:
        return AuthResult(ok=False, error="Open a fresh password-reset link first.")
    if not password or len(password) < 8:
        return AuthResult(ok=False, error="Use a password with at least 8 characters.")
    if password != confirmation:
        return AuthResult(ok=False, error="The passwords do not match.")
    try:
        client = get_auth_client()
        response = client.auth.set_session(stored["access_token"], stored["refresh_token"])
        if not response.session or not response.user or response.user.id != stored["user_id"]:
            raise ValueError("Invalid recovery session")
        # Preserve rotated refresh credentials if the password update needs a retry.
        stored["access_token"] = response.session.access_token
        stored["refresh_token"] = response.session.refresh_token
    except Exception:
        st.session_state.pop(RECOVERY_SESSION_KEY, None)
        return AuthResult(ok=False, error="Your reset session has expired. Request a fresh password-reset link.")
    try:
        response = client.auth.update_user({"password": password})
        if not response.user or response.user.id != stored["user_id"]:
            raise ValueError("Password update did not return the recovery user")
    except Exception:
        return AuthResult(ok=False, error="Password could not be updated. Use a different password that meets your organization's password policy, or request a fresh reset link.")
    try:
        client.auth.sign_out({"scope": "local"})
    except Exception:
        pass
    st.session_state.pop(RECOVERY_SESSION_KEY, None)
    st.session_state.pop(SESSION_KEY, None)
    st.session_state.pop(AUTH_CONTEXT_KEY, None)
    return AuthResult(ok=True)


def render_password_recovery() -> None:
    """Render before normal authentication/tenancy gates; survives form reruns."""
    import streamlit as st
    st.markdown("## Reset your password")
    st.caption("Choose a new password for your account.")
    with st.form("password_recovery", clear_on_submit=True):
        password = st.text_input("New password", type="password")
        confirmation = st.text_input("Confirm new password", type="password")
        submitted = st.form_submit_button("Update password", type="primary")
    if submitted:
        result = update_recovered_password(password, confirmation)
        if result.ok:
            st.session_state["bi_password_reset_complete"] = True
            st.rerun()
        else:
            st.error(result.error)
    if st.button("Back to sign in"):
        sign_out()
        st.rerun()
    st.stop()


def restore_session() -> AuthResult:
    """Best-effort restoration from Streamlit's own session_state -- see
    the module docstring for what this does and does not guarantee. Return
    an explicit failure (not an exception) for the 'no prior session',
    'missing token', and 'expired token' cases so calling UI code has one
    uniform result type to branch on for every case (success, invalid
    login, missing token, expired token). Expiry is checked only against
    the locally-stored `expires_at` timestamp from the original sign-in --
    no network call is made on every rerun (see module docstring)."""
    stored = current_session()
    if not stored:
        return AuthResult(ok=False, error="no session")
    if not stored.get("access_token") or not stored.get("user_id"):
        return AuthResult(ok=False, error="stored session is missing required token/identity fields")
    expires_at = stored.get("expires_at")
    if expires_at is not None and time.time() >= expires_at:
        return AuthResult(ok=False, error="session expired")
    return AuthResult(ok=True, user_id=stored.get("user_id"), email=stored.get("email"))
