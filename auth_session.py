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
    if not email or not password:
        return AuthResult(ok=False, error="email and password are required")
    try:
        client = get_auth_client()
        resp = client.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as e:
        return AuthResult(ok=False, error=_safe_auth_error(e))

    session = getattr(resp, "session", None)
    user = getattr(resp, "user", None)
    if not session or not user:
        return AuthResult(ok=False, error="invalid credentials")

    import streamlit as st
    st.session_state[SESSION_KEY] = {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "user_id": user.id,
        "email": user.email,
        "expires_at": getattr(session, "expires_at", None),
    }
    return AuthResult(ok=True, user_id=user.id, email=user.email)


def sign_out() -> None:
    """Clears local session state unconditionally, even if the remote
    sign-out call fails -- a failed remote call must never leave the UI
    looking signed-in when the user asked to sign out."""
    try:
        client = get_auth_client()
        client.auth.sign_out()
    except Exception:
        pass
    import streamlit as st
    st.session_state.pop(SESSION_KEY, None)


def current_session() -> dict | None:
    import streamlit as st
    return st.session_state.get(SESSION_KEY)


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
