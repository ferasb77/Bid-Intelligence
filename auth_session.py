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


def render_fragment_session_bridge() -> None:
    """Supabase can issue a session via the URL FRAGMENT
    (#access_token=...&refresh_token=...&type=...) instead of the
    token_hash query-param flow handle_invite_callback() expects -- this
    happens for a Supabase-dashboard-triggered password-recovery link,
    and can happen for a magic-link email too depending on this
    project's currently configured Auth flow type. A browser's URL
    fragment is never sent to the server (an HTTP fact, not a bug), so
    Streamlit's server-side st.query_params can never see it directly --
    without this bridge, such a link silently strands the user back at
    the sign-in page with no error, no matter how Site URL/Redirect URLs
    are configured (this was diagnosed live: the previously-documented
    "tokens exposed in the browser's URL fragment during troubleshooting"
    incident in this module's docstring is exactly this same gap
    recurring).

    Renders an invisible (zero-height), purely client-side JS snippet
    that -- ONLY when the fragment actually contains `access_token=` --
    moves the token pair into short-named query params (sb_at/sb_rt) and
    reloads, so handle_fragment_session_callback() below can pick it up
    server-side on the next run. A no-op on every ordinary page load:
    the fragment check happens entirely in the browser, and nothing is
    sent to the server unless a token was actually present. Call this
    once, unconditionally, as early as possible in the script -- before
    handle_invite_callback()/handle_fragment_session_callback() -- so a
    fragment-token redirect happens before anything else renders.

    st.components.v1.html() renders this snippet inside a same-origin
    IFRAME, not the top-level page -- and confirmed live, this project's
    Streamlit Cloud hosting wraps the whole app in its OWN outer
    "streamlitApp" iframe first, so our component actually sits TWO
    levels deep (tab -> streamlitApp iframe -> this component's iframe).
    A first version of this read plain `window.location` (the
    component's own blank location -- fixed, but still wrong) and a
    second read `window.parent.location`, which only reaches the
    streamlitApp iframe, one level short of the real tab -- confirmed
    live via direct DOM inspection of the deployed page (an <iframe
    title="streamlitApp"> containing an <iframe title="st.iframe">, our
    component). `window.top` always resolves to the OUTERMOST browsing
    context no matter how many iframes are nested in between, so every
    reference below is `window.top.location` -- the one form that is
    correct regardless of exactly how many levels Streamlit Cloud's own
    hosting happens to nest at any given time.

    Confirmed live (2026-09-18), in order: (1) a single
    `window.top.location.replace()` call was not enough -- manually
    re-running the exact same logic via direct DOM access always
    redirected correctly with no error, but the natural, unforced page
    load left the tab sitting on the original fragment URL indefinitely,
    even after several seconds; (2) adding a same-mount retry loop (up to
    20 attempts, 250ms apart) did not help either -- continuous polling
    of the top frame's URL across a 7-second natural load showed *zero*
    navigation attempts, not even a brief flicker, meaning the script's
    IIFE was never actually executing on its own at all, retried or not;
    (3) a synthetic same-page test (two directly-created, non-Streamlit
    srcdoc iframes, one height=0 and one height=20, both appended to
    `document.body`) showed BOTH execute their script within 1.5s --
    ruling out a generic browser rule against zero-height iframes ever
    running script. The remaining, most likely explanation is specific to
    Streamlit's OWN component-iframe wrapper: a component reporting
    height=0 is plausibly treated by Streamlit's frontend as "not yet
    sized" and its srcdoc activation delayed indefinitely under normal
    (non-forced) conditions -- consistent with the fact that manually
    reading `.contentDocument`/`.contentWindow` from outside (which
    forces a layout/activation pass) is exactly what made the identical
    script run correctly every time it was tried. Using `height=1`
    (visually negligible, but never zero) avoids relying on that
    internal Streamlit behavior entirely. The retry loop above is kept
    regardless, since it is harmless and still guards against any
    genuine remount-vs-navigation race on top of the height fix."""
    import streamlit.components.v1 as components
    components.html(
        """
        <script>
        (function() {
            function attemptBridge() {
                var hash = window.top.location.hash;
                var errorParams = new URLSearchParams((hash || '').substring(1));
                if (errorParams.has('error') || errorParams.has('error_code')) {
                    var errorUrl = new URL(window.top.location.href);
                    errorUrl.hash = '';
                    errorUrl.searchParams.set('sb_error', 'invalid_link');
                    window.top.location.replace(errorUrl.toString());
                    return true;
                }
                if (hash && hash.indexOf('access_token=') !== -1) {
                    var params = new URLSearchParams(hash.substring(1));
                    var accessToken = params.get('access_token');
                    var refreshToken = params.get('refresh_token');
                    if (accessToken && refreshToken) {
                        var url = new URL(window.top.location.href);
                        url.hash = '';
                        url.searchParams.set('sb_at', accessToken);
                        url.searchParams.set('sb_rt', refreshToken);
                        url.searchParams.set('sb_type', params.get('type') || '');
                        window.top.location.replace(url.toString());
                        return true;
                    }
                }
                return false;
            }
            if (attemptBridge()) { return; }
            var attempts = 0;
            var intervalId = setInterval(function() {
                attempts += 1;
                if (attemptBridge() || attempts >= 20) {
                    clearInterval(intervalId);
                }
            }, 250);
        })();
        </script>
        """,
        height=1,
    )


def handle_fragment_session_callback() -> AuthResult:
    """Server-side half of the fragment-token bridge (see
    render_fragment_session_bridge() above for why this exists). Once the
    client-side JS has moved an already-issued access_token/refresh_token
    pair from the URL fragment into sb_at/sb_rt query params and
    reloaded, this establishes the session via Supabase's set_session()
    -- NOT verify_otp(), since these are already-valid tokens, not a
    one-time code to redeem. Immediately strips both params from the
    visible URL, regardless of outcome, so neither token can be re-used,
    bookmarked, or re-shared from the browser's address bar or history
    (same discipline as handle_invite_callback()'s token_hash stripping).
    Uses ONLY the anon/public auth client -- never the service-role
    client. Never logs or prints either token anywhere. A safe no-op
    (ok=False, error='no fragment session callback present') whenever the
    expected query params are absent, so it never affects an ordinary
    page load."""
    import streamlit as st

    callback_error = st.query_params.get("sb_error") or st.query_params.get("error") or st.query_params.get("error_code")
    if callback_error:
        for key in ("sb_error", "error", "error_code", "error_description", "sb_at", "sb_rt", "sb_type", "token_hash", "type"):
            st.query_params.pop(key, None)
        return AuthResult(ok=False, error="This authentication link is invalid or expired. Request a fresh link.")

    access_token = st.query_params.get("sb_at")
    refresh_token = st.query_params.get("sb_rt")
    callback_type = st.query_params.get("sb_type")
    if access_token or refresh_token or callback_type:
        for key in ("sb_at", "sb_rt", "sb_type"):
            st.query_params.pop(key, None)
        if not access_token or not refresh_token:
            return AuthResult(ok=False, error="incomplete authentication link; request a fresh link")
    if not access_token or not refresh_token:
        return AuthResult(ok=False, error="no fragment session callback present")

    try:
        client = get_auth_client()
        resp = client.auth.set_session(access_token, refresh_token)
    except Exception:
        st.query_params.pop("sb_at", None)
        st.query_params.pop("sb_rt", None)
        return AuthResult(ok=False, error="session could not be established: invalid or expired link")

    st.query_params.pop("sb_at", None)
    st.query_params.pop("sb_rt", None)

    session = getattr(resp, "session", None)
    user = getattr(resp, "user", None)
    if not session or not user:
        return AuthResult(ok=False, error="fragment session callback did not return a valid session")

    if callback_type == "recovery":
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
