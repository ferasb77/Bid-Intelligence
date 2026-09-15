"""
auth_client.py — Bid Intelligence authentication client.

Phase 8 remediation package 2 (auth/tenancy foundation) establishes a hard
separation between two Supabase clients that must never share a credential:

  * database.py:get_client()  — the existing, privileged SERVICE-ROLE client.
    Used for all current server-side database operations and Fast Analysis's
    background thread. Bypasses RLS by definition. Never touches auth.

  * auth_client.py:get_auth_client() (this module) — the PUBLIC/ANON client.
    Used only for authentication: sign in, session/token validation, sign
    out. Subject to RLS like any other non-service-role caller. Never used
    for ordinary application data access.

This module reads SUPABASE_ANON_KEY (the anon/publishable key -- safe by
Supabase's own design to embed in a browser-facing client, unlike the
service-role key) and never reads SUPABASE_SERVICE_KEY. database.py, in
turn, never reads SUPABASE_ANON_KEY. tests/test_auth_tenancy.py's
TestAuthDataClientSeparation regression-tests both directions of this
boundary so it cannot silently drift.

Neither client's credential is ever placed into Streamlit session state or
any other browser-visible location -- both are read once per call, from
server-side environment/secrets, directly into the `supabase-py` client
constructor.
"""
import os
from supabase import create_client, Client


def get_auth_client() -> Client:
    """Public/anon Supabase client for authentication only. Never uses the
    service-role key -- see the module docstring and database.py:get_client()
    for the separate, privileged server data client."""
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
    return create_client(url, key)


def auth_configured() -> bool:
    """True if enough config exists to construct the auth client -- lets
    calling code (e.g. the sign-in UI) degrade gracefully instead of
    raising, mirroring config.py's api_key_configured() pattern."""
    try:
        get_auth_client()
        return True
    except Exception:
        return False
