"""Enable My Growth identity for the Bid Intelligence application."""

from __future__ import annotations

import base64
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"

PRODUCT_NAME = "Bid Intelligence"
PRODUCT_EDITION = "Decision & Proposal Platform"
PRODUCT_DESCRIPTOR = (
    "A structured environment for examining bid decisions, evidence, "
    "and proposal readiness before committing resources."
)
BRAND_LINE = "Perspective changes what becomes possible."


def asset_data_uri(filename: str) -> str:
    path = ASSETS / filename
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def sidebar_brand_html() -> str:
    return f"""
    <div class="emg-sidebar-brand">
      <img src="{asset_data_uri('emg-3d-mark.png')}" alt="Enable My Growth Möbius mark">
      <div>
        <div class="emg-product-name">{PRODUCT_NAME}</div>
        <div class="emg-edition">{PRODUCT_EDITION}</div>
      </div>
    </div>
    <div class="emg-endorsement">BY ENABLE MY GROWTH · FERAS BANNA</div>
    <hr class="section-divider">
    """


def dashboard_brand_html() -> str:
    return f"""
    <div class="emg-dashboard-brand">
      <div class="emg-dashboard-kicker">AN ENABLE MY GROWTH APPLICATION</div>
      <div class="emg-dashboard-name">Bid <span>Intelligence</span></div>
      <div class="emg-dashboard-descriptor">{PRODUCT_DESCRIPTOR}</div>
      <div class="emg-dashboard-line">{BRAND_LINE}</div>
    </div>
    """
