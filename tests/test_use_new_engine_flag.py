"""USE_NEW_ENGINE: the Fast / Full pages serve the engine/ pipeline's PDFs,
falling back to the legacy flows only when the engine is unavailable."""
from pathlib import Path
from types import SimpleNamespace

import pytest

import config
import tenancy
from pages import stage_engine

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("value,expected", [(None, True), ("1", True), ("0", False), ("", False), (" 1 ", True)])
def test_flag_defaults_on_and_can_be_disabled(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("USE_NEW_ENGINE", raising=False)
    else:
        monkeypatch.setenv("USE_NEW_ENGINE", value)
    assert config.use_new_engine() is expected


@pytest.fixture
def org(monkeypatch):
    monkeypatch.setattr(stage_engine.auth_session, "current_auth_context",
                        lambda: SimpleNamespace(organization_id="org-a", user_id="u1"))


def test_panel_falls_back_when_engine_unavailable(monkeypatch, org):
    def boom(*a, **k):
        raise RuntimeError("relation engine_runs does not exist")
    monkeypatch.setattr(tenancy, "get_engine_status_for_organization", boom)
    assert stage_engine.render_engine_report_panel(7, "FAST") is False


def test_panel_handles_access_denied_without_fallback(monkeypatch, org):
    def denied(*a, **k):
        raise tenancy.AccessDeniedError("no")
    monkeypatch.setattr(tenancy, "get_engine_status_for_organization", denied)
    assert stage_engine.render_engine_report_panel(7, "FULL") is True


@pytest.mark.parametrize("kind", ["FAST", "FULL"])
def test_complete_run_serves_matching_pdf(monkeypatch, org, kind):
    calls = []
    monkeypatch.setattr(tenancy, "get_engine_status_for_organization",
                        lambda b, o, r=None: {"id": 11, "status": "COMPLETE", "verification": "SINGLE_ANALYST"})

    def export(b, o, run_id, k):
        calls.append((b, o, run_id, k))
        return b"%PDF-1.4"
    monkeypatch.setattr(tenancy, "export_engine_pdf_for_organization", export)
    assert stage_engine.render_engine_report_panel(7, kind) is True
    assert calls == [(7, "org-a", 11, kind)]


def test_pages_are_wired_to_the_engine_panel():
    understand = (ROOT / "pages" / "stage_understand.py").read_text(encoding="utf-8")
    full = (ROOT / "pages" / "stage_full_analysis.py").read_text(encoding="utf-8")
    assert 'render_engine_report_panel(bid_id, "FAST"' in understand and "use_new_engine()" in understand
    assert 'render_engine_report_panel(bid_id, "FULL"' in full and "use_new_engine()" in full


def test_sidebar_build_sha_caption():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "getenv('BUILD_SHA', 'local')" in app
