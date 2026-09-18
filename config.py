"""
Central config — reads API key and workspace configuration from:
  1. Streamlit secrets (st.secrets) — used on Streamlit Cloud
  2. .env file — used locally
  3. Session state — set manually via UI
"""
import os
import json
import streamlit as st

# Load .env if present (local dev)
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

def get_api_key() -> str | None:
    # 1. Streamlit Cloud secrets
    try:
        key = st.secrets.get("ANTHROPIC_API_KEY")
        if key:
            return key
    except Exception:
        pass
    # 2. Environment variable / .env file
    key = os.getenv("ANTHROPIC_API_KEY")
    if key:
        return key
    # 3. Session state (entered via UI)
    try:
        return st.session_state.get("anthropic_api_key") or None
    except Exception:
        return None

def get_workspace_id() -> str | None:
    try:
        ws = st.secrets.get("ANTHROPIC_WORKSPACE_ID")
        if ws:
            return ws
    except Exception:
        pass
    ws = os.getenv("ANTHROPIC_WORKSPACE_ID")
    if ws:
        return ws
    try:
        return st.session_state.get("anthropic_workspace_id") or None
    except Exception:
        return None

def get_anthropic_client(api_key: str | None = None):
    import anthropic
    key = api_key or get_api_key()
    headers = {}
    ws_id = get_workspace_id()
    if ws_id:
        headers["anthropic-workspace-id"] = ws_id

    custom_headers = os.getenv("ANTHROPIC_CUSTOM_HEADERS")
    if custom_headers:
        try:
            parsed = json.loads(custom_headers)
            if isinstance(parsed, dict):
                headers.update(parsed)
        except Exception:
            for pair in custom_headers.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    headers[k.strip()] = v.strip()
                elif ":" in pair:
                    k, v = pair.split(":", 1)
                    headers[k.strip()] = v.strip()

    return anthropic.Anthropic(api_key=key, default_headers=headers if headers else None)

def api_key_configured() -> bool:
    return bool(get_api_key())

def get_app_base_url() -> str | None:
    """Phase 8 remediation package 3: this deployment's own public base
    URL, used as email_redirect_to when the login gate requests a
    magic-link sign-in. Must match an entry already in Supabase Auth's
    Redirect URLs allowlist -- if unset, the login gate omits
    email_redirect_to and Supabase falls back to its own configured Site
    URL, which may not match this specific deployment (e.g. staging)."""
    try:
        url = st.secrets.get("APP_BASE_URL")
        if url:
            return url
    except Exception:
        pass
    return os.getenv("APP_BASE_URL") or None


# Disallowed sampling parameters across modern Claude reasoning / custom gateway paths
_DISALLOWED_SAMPLING_KEYS = {"temperature", "top_p", "top_k"}


def sanitize_anthropic_kwargs(kwargs: dict) -> dict:
    """Return a shallow copy of kwargs with unsupported sampling parameters removed."""
    return {k: v for k, v in kwargs.items() if k not in _DISALLOWED_SAMPLING_KEYS}


def execute_messages_create(client, **kwargs):
    """Central invocation helper for Anthropic messages.create.
    Strips unsupported sampling parameters (temperature, top_p, top_k)
    before delegating to client.messages.create, ensuring consistent model
    compatibility across all workflows.
    """
    clean_kwargs = sanitize_anthropic_kwargs(kwargs)
    return client.messages.create(**clean_kwargs)


def classify_anthropic_error(exc: Exception) -> dict:
    """Classifies an API/model exception into user-safe categories without
    leaking tokens, prompt texts, or customer document content.

    Returns a dict with:
      - category: "AUTHENTICATION", "INVALID_REQUEST", "RATE_LIMIT",
                  "NOT_FOUND", "PROVIDER_UNAVAILABLE", or "PROCESSING_ERROR"
      - message: User-safe summary message
      - advice: Recommended next step or diagnostic hint
    """
    import anthropic

    if isinstance(exc, anthropic.AuthenticationError):
        return {
            "category": "AUTHENTICATION",
            "message": "Anthropic API authentication failed.",
            "advice": "Verify that your Anthropic API key and workspace configuration are valid and active."
        }
    if isinstance(exc, anthropic.RateLimitError):
        return {
            "category": "RATE_LIMIT",
            "message": "Anthropic API rate limit exceeded.",
            "advice": "Please wait a moment before retrying this operation."
        }
    if isinstance(exc, anthropic.NotFoundError):
        return {
            "category": "NOT_FOUND",
            "message": "Requested Anthropic model or endpoint was not found.",
            "advice": "Check the configured model identifier."
        }
    if isinstance(exc, TypeError) and "temperature" in str(exc).lower():
        return {
            "category": "INVALID_REQUEST",
            "message": "Unsupported model parameter in request configuration.",
            "advice": "Ensure no disallowed sampling parameters (such as temperature) are supplied."
        }
    if isinstance(exc, anthropic.BadRequestError):
        return {
            "category": "INVALID_REQUEST",
            "message": "Anthropic API rejected the request format or parameters.",
            "advice": "Check the prompt size, document structure, or parameter compatibility."
        }
    if isinstance(exc, (anthropic.APIConnectionError, anthropic.InternalServerError)):
        return {
            "category": "PROVIDER_UNAVAILABLE",
            "message": "Anthropic service is temporarily unavailable or unreachable.",
            "advice": "Check network connectivity or retry after a brief pause."
        }
    return {
        "category": "PROCESSING_ERROR",
        "message": "Document extraction processing error.",
        "advice": "Review the uploaded document format or try again."
    }
