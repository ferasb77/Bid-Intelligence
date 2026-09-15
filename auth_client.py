"""
auth_client.py — Bid Intelligence authentication & user-scoped data clients.

Phase 8 remediation packages 2 and 3 establish a hard separation between
THREE Supabase clients that must never share a credential:

  * database.py:get_service_client() (alias of get_client())  — the
    existing, privileged SERVICE-ROLE client. Used for all current
    server-side database operations and Fast Analysis's background thread.
    Bypasses RLS by definition. Never touches auth.

  * auth_client.py:get_auth_client() (this module) — the PUBLIC/ANON client
    with no user token attached. Used only for authentication: sign in,
    session/token validation, sign out. Subject to RLS like any other
    non-service-role caller. Never used for ordinary application data
    access.

  * auth_client.py:get_authenticated_client(access_token) (this module,
    package 3) — the PUBLIC/ANON client WITH a signed-in user's own access
    token attached. Every request made through this client executes AS
    that user, subject to every RLS policy in migration 008 -- this is the
    "user-scoped data client" instruction 13 requires for interactive
    application reads/writes once cutover happens (package 3 §15/§21;
    not yet wired into any page in this package -- see the package 3
    report's bootstrap-gating section for why).

This module reads SUPABASE_ANON_KEY (the anon/publishable key -- safe by
Supabase's own design to embed in a browser-facing client, unlike the
service-role key) and never reads SUPABASE_SERVICE_KEY. database.py, in
turn, never reads SUPABASE_ANON_KEY. tests/test_auth_tenancy.py's
TestAuthDataClientSeparation regression-tests every direction of this
boundary so it cannot silently drift.

No credential from any of the three clients above is ever placed into
Streamlit session state as anything other than the user's OWN short-lived
access/refresh token (see auth_session.py) -- the service-role key is never
stored in session state, never returned to browser-visible state, and never
used to construct either of the other two clients.
"""
import os
from supabase import create_client, Client


def _resolve_url_and_anon_key() -> tuple[str, str]:
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
    except Exception:
        pass
    try:
        import streamlit as st
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_ANON_KEY"]
    except Exception:
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_ANON_KEY", "")
    if not url or not key:
        raise RuntimeError(
            "Supabase auth credentials not found. Add SUPABASE_URL and "
            "SUPABASE_ANON_KEY (the publishable/anon key -- never the "
            "service-role key) to Streamlit secrets or .env file.")
    return url, key


def get_auth_client() -> Client:
    """Public/anon Supabase client for authentication only -- no user token
    attached. Never uses the service-role key -- see the module docstring
    and database.py:get_service_client() for the separate, privileged
    server data client."""
    url, key = _resolve_url_and_anon_key()
    return create_client(url, key)


def get_authenticated_client(access_token: str) -> Client:
    """The user-scoped, RLS-respecting data client (Phase 8 remediation
    package 3, instruction 13). Built from the SAME anon/publishable key as
    get_auth_client() -- never the service-role key -- with the signed-in
    user's own access token attached via PostgREST's Authorization header,
    so every request this client makes executes as that specific user and
    is subject to every RLS policy in migration 008, exactly as if that
    user's own browser session had made the request directly. This is the
    client interactive application code should eventually use for
    dashboard bid listing, opening a bid, and every other user-facing read/
    write instruction 15 names -- once wired in (package 3's own cutover is
    explicitly gated behind a real user existing; see the accompanying
    report)."""
    if not access_token:
        raise ValueError("get_authenticated_client requires a non-empty access_token")
    url, key = _resolve_url_and_anon_key()
    client = create_client(url, key)
    client.postgrest.auth(access_token)
    return client


def auth_configured() -> bool:
    """True if enough config exists to construct the auth client -- lets
    calling code (e.g. the sign-in UI) degrade gracefully instead of
    raising, mirroring config.py's api_key_configured() pattern."""
    try:
        get_auth_client()
        return True
    except Exception:
        return False
