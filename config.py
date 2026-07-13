"""
Central config — reads API key from .env file first, session state second.
To set up: create a file called .env in the bid_platform/ folder containing:
  ANTHROPIC_API_KEY=sk-ant-...
"""
import os
from dotenv import load_dotenv
import streamlit as st

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

def get_api_key() -> str | None:
    """Return key from .env → session state → None."""
    return (
        os.getenv("ANTHROPIC_API_KEY")
        or st.session_state.get("anthropic_api_key")
        or None
    )

def api_key_configured() -> bool:
    return bool(get_api_key())
