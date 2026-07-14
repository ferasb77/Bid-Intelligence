"""
Central config — reads API key from:
  1. Streamlit secrets (st.secrets) — used on Streamlit Cloud
  2. .env file — used locally
  3. Session state — set manually via UI
"""
import os
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
    return st.session_state.get("anthropic_api_key") or None

def api_key_configured() -> bool:
    return bool(get_api_key())
