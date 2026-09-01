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
