"""MA-2C: Full Bid Intelligence PDF report export. Deterministic: every
service/database read is mocked, every write path and every provider /
specialist / reconciliation / Fast Analysis entry point is booby-trapped."""
from __future__ import annotations

import ast
import copy
import io
import pathlib
import re

import pypdf
import pytest

import full_analysis_report as far
import tenancy
from components import full_analysis_view as fav
from pages import stage_full_analysis as page

ROOT = pathlib.Path(__file__).resolve().parents[1]
IDS = fav.SPECIALIST_IDS


def _finding(sid, i, sev="MEDIUM", **kw):
    f = {"title": f"{sid} finding {i}", "detail": f"Detail for {sid} {i}.", "severity": sev,
         "authority": "SPECIALIST_INTERPRETATION", "finding_id": f"{sid}:{i}", "produced_by": [sid],
         "finding_type": "ATTENTION_ITEM", "canonical_ids": [f"REQ-{i}"], "category_scope": "",
         "human_confirmation_required": False}
    f.update(kw)
    return f


def make_bundle(*, run_status="PARTIAL", recon_status="PARTIAL", spec_status=None, n=3,
                row_raw_status="COMPLETE", truncated=True):
    spec_status = spec_status or {}
    rows, findings = [], []
    for sid in IDS:
        eff = spec_status.get(sid, "COMPLETE")
        fs = [] if eff == "FAILED" else [_finding(sid, i, "HIGH" if i == 0 else "MEDIUM") for i in range(n)]
        findings += fs
        rows.append({"specialist_id": sid, "status": "FAILED" if eff == "FAILED" else row_raw_status,
                     "effective_status": eff, "result": {"status": eff, "findings": fs}})
    if findings:
        findings[0]["produced_by"] = [IDS[0], IDS[1]]
    result = {
        "reconciled_findings": findings,
        "cross_domain_risks": [{"title": "Cross risk alpha", "detail": "Spans two domains.", "severity": "HIGH",
                                "authority": "SPECIALIST_INTERPRETATION", "domains": [IDS[0], IDS[5]],
                                "finding_ids": [f"{IDS[0]}:0"], "canonical_ids": ["MS-3", "MS-4"]}],
        "unresolved_gaps": [dict(findings[1], finding_type="GAP")] if n > 1 else [],
        "ambiguities": [], "human_confirmation_required": findings[1:2],
        "completeness_status": run_status,
        "source_refs": [{"source_doc": "RFP Main.pdf", "page": 3, "sheet": None, "section": None,
                         "excerpt": "Submission deadline September 30."}],
        "reconciliation": {"status": recon_status, "output_truncated": truncated, "stop_reason": "max_tokens",
                           "failure_reason": "OUTPUT_TRUNCATED: provider stop_reason=max_tokens",
                           "contradictions": [], "orphaned_requirements": [
                               {"canonical_id": "REQ-99", "description": "Orphan requirement text",
                                "applicability": "CATEGORY_SPECIFIC"}],
                           "completeness_note": "Note from reconciliation."},
    }
    run = {"id": 33, "bid_id": 1295, "status": run_status, "completed_at": "2026-09-22T21:35:23+00:00"}
    status = {"run_id": 33, "bid_id": 1295, "status": run_status, "is_terminal": True,
              "source_analysis_run_id": 20, "completed_at": run["completed_at"],
              "specialists": {sid: {"status": spec_status.get(sid, "COMPLETE")} for sid in IDS},
              "reconciliation": {"status": recon_status}, "events": [], "stuck": {"stuck": False}}
    return status, {"run": run, "result": result, "specialist_results": rows,
                    "is_complete": run_status == "COMPLETE"}


FACTS = [["Buyer", "Bank"], ["Solicitation Number", "2026-026"], ["Opportunity", "RFP 2026-026 Addendum #2"],
         ["Service Categories", "3 — D1, D2, D3"]]
TABLES = {"EVAL_WEIGHTS": {"Category 2": [["Methodology", "35 points"]]},
          "KEY_DATES": [["Submission deadline", "2026-09-30"]]}


def text_of(pdf: bytes) -> str:
    r = pypdf.PdfReader(io.BytesIO(pdf))
    return re.sub(r"\s+", " ", " ".join(p.extract_text() or "" for p in r.pages))


def render(status, bundle, **kw):
    kw.setdefault("identity_facts", FACTS)
    kw.setdefault("canonical_tables", TABLES)
    return far.render_report(status, bundle, bid={"id": 1295, "title": "Bid", "client": "BOC"}, **kw)


# ─── export content / truthfulness ───────────────────────────────────

def test_complete_export():
    status, bundle = make_bundle(run_status="COMPLETE", recon_status="COMPLETE", truncated=False)
    out = render(status, bundle)
    assert out["pdf"].startswith(b"%PDF")
    t = text_of(out["pdf"])
    assert "FULL BID INTELLIGENCE COMPLETE" in t
    assert far.PARTIAL_TITLE not in t and "PARTIAL OUTPUT" not in t


def test_partial_recon_only_disclosed():
    status, bundle = make_bundle()
    out = render(status, bundle)
    t = text_of(out["pdf"])
    assert far.PARTIAL_TITLE in t
    assert "All six specialist analyses completed" in t
    assert "Reconciliation & Assurance returned partial output" in t
    assert t.count("COMPLETE") >= 6 and "PARTIAL OUTPUT" in t
    assert out["model"]["reconciliation"] == "PARTIAL"
    assert all(v == "COMPLETE" for v in out["model"]["specialists"].values())
    # reconciled findings persisted are included; no stopped/failed semantics, no internals
    assert "Cross risk alpha" in t
    for bad in ("interrupted", "stopped", "OUTPUT_TRUNCATED", "stop_reason", "max_tokens"):
        assert bad not in t


def test_effective_status_used_over_raw_column():
    status, bundle = make_bundle(spec_status={IDS[2]: "PARTIAL"}, row_raw_status="COMPLETE")
    status["specialists"][IDS[2]]["status"] = "COMPLETE"  # even if events disagree
    out = render(status, bundle)
    assert out["model"]["specialists"][IDS[2]] == "PARTIAL"
    t = text_of(out["pdf"])
    assert "domain's analysis is incomplete" in t


def test_failed_specialist_represented():
    status, bundle = make_bundle(spec_status={IDS[4]: "FAILED"})
    out = render(status, bundle)
    assert out["model"]["specialists"][IDS[4]] == "FAILED"
    t = text_of(out["pdf"])
    assert "FAILED" in t and "domain analysis is unavailable" in t
    assert f"{IDS[3]} finding 1" in t  # successful domains preserved


def test_traceability_refs_survive():
    status, bundle = make_bundle()
    bundle["result"]["reconciled_findings"][2]["canonical_ids"] = ["DOC-rfp-2026-026-appendix-d2-very-long-id"]
    t = text_of(render(status, bundle)["pdf"])
    assert "Appendix A" in t and "Evidence:" in t
    assert "DOC-rfp-2026-026-appendix-d2-very-long-id" in t.replace(" ", "")  # full id in appendix
    assert "RFP Main.pdf" in t and "Submission deadline September 30." in t
    assert "Also raised by" in t


def test_empty_optional_sections_safe():
    status, bundle = make_bundle(n=0)
    bundle["result"].update(cross_domain_risks=[], unresolved_gaps=[], human_confirmation_required=[],
                            source_refs=[], reconciliation={"status": "PARTIAL"})
    out = far.render_report(status, bundle, bid=None)
    t = text_of(out["pdf"])
    assert "No findings were recorded in this domain." in t
    assert out["filename"].endswith("_Full_Analysis.pdf")


def test_large_result_not_truncated():
    status, bundle = make_bundle(n=70)
    for f in bundle["result"]["reconciled_findings"]:
        f["detail"] = "Long detail sentence. " * 40
    out = render(status, bundle)
    t = text_of(out["pdf"])
    for sid in IDS:
        for i in (0, 35, 69):
            assert f"{sid} finding {i}" in t
    assert len(pypdf.PdfReader(io.BytesIO(out["pdf"])).pages) > 40


def test_deterministic_safe_filename():
    assert far.report_filename({"solicitation": "RFP 2026/026: A*B?"}) == \
        "Bid_Intelligence_RFP_2026_026_A_B_Full_Analysis.pdf"
    assert far.report_filename({"solicitation": None, "opportunity": "Big Job"}) == \
        "Bid_Intelligence_Big_Job_Full_Analysis.pdf"
    assert far.report_filename({"bid_id": 1295}) == "Bid_Intelligence_Bid_1295_Full_Analysis.pdf"
    status, bundle = make_bundle()
    a, b = render(status, bundle), render(status, bundle)
    assert a["filename"] == b["filename"] == "Bid_Intelligence_2026-026_Full_Analysis.pdf"
    assert a["pdf"] == b["pdf"]  # invariant render
    assert "33" not in a["filename"]


@pytest.mark.parametrize("st", ["RUNNING", "QUEUED", "FAILED"])
def test_non_terminal_or_failed_run_not_exportable(st):
    status, bundle = make_bundle(run_status=st)
    with pytest.raises(far.ReportNotExportableError):
        render(status, bundle)


def test_historical_compatible_run_exports():
    status, bundle = make_bundle(run_status="COMPLETE", recon_status="COMPLETE")
    for r in bundle["specialist_results"]:  # pre-MA-2A.2: no inner status
        r["result"].pop("status")
        r["effective_status"] = r["status"]
    for k in ("source_refs", "reconciliation", "unresolved_gaps"):
        bundle["result"].pop(k)
    out = far.render_report(None, bundle)
    assert out["model"]["reconciliation"] == "SKIPPED" or out["pdf"].startswith(b"%PDF")
    assert out["pdf"].startswith(b"%PDF")


# ─── tenancy / zero provider calls / no mutation ─────────────────────

def _trap(*a, **k):
    raise AssertionError("forbidden call during export")


@pytest.fixture
def export_env(monkeypatch):
    import anthropic
    import analysis_service
    import database as db
    import full_analysis
    import full_analysis_service as fas
    for mod, names in ((anthropic, ("Anthropic",)),
                       (full_analysis, ("run_specialist", "run_reconciliation", "run_full_analysis")),
                       (analysis_service, ("start_fast_analysis", "run_full_analysis_for_run")),
                       (fas, ("start_full_analysis", "mark_full_analysis_run_stuck")),
                       (db, ("start_full_analysis_run", "record_full_analysis_event",
                             "finalize_full_analysis_run", "update_analysis_run", "create_analysis_result",
                             "create_analysis_run"))):
        for n in names:
            if hasattr(mod, n):
                monkeypatch.setattr(mod, n, _trap)
    status, bundle = make_bundle()
    calls = {"status": 0, "result": 0}

    def get_status(bid_id, run_id=None, **k):
        calls["status"] += 1
        if run_id != 33:
            raise fas.RunNotFoundError("no")
        return copy.deepcopy(status)

    def get_result(bid_id, run_id=None):
        calls["result"] += 1
        return copy.deepcopy(bundle)

    monkeypatch.setattr(fas, "get_full_analysis_status", get_status)
    monkeypatch.setattr(fas, "get_full_analysis_result", get_result)
    monkeypatch.setattr(tenancy, "get_bid_for_organization",
                        lambda b, o: {"id": b} if o == "org-a" else None)
    monkeypatch.setattr(db, "get_bid", lambda b: {"id": b, "title": "T", "client": "C"})
    monkeypatch.setattr(db, "get_analysis_run", lambda r: {"id": r, "bid_id": 1295})
    monkeypatch.setattr(db, "get_analysis_result",
                        lambda r: {"report_content_snapshot": {"SNAPSHOT_FACTS": FACTS, **TABLES}})
    return {"calls": calls, "status": status, "bundle": bundle}


def test_export_zero_provider_calls_and_repeatable(export_env):
    before = copy.deepcopy(export_env["bundle"])
    a = tenancy.export_full_analysis_report_for_organization(1295, "org-a", 33)
    b = tenancy.export_full_analysis_report_for_organization(1295, "org-a", 33)
    assert a["pdf"] == b["pdf"] and a["filename"] == "Bid_Intelligence_2026-026_Full_Analysis.pdf"
    assert export_env["bundle"] == before  # persisted payload untouched


def test_unauthorized_org_cannot_export(export_env):
    with pytest.raises(tenancy.AccessDeniedError):
        tenancy.export_full_analysis_report_for_organization(1295, "org-b", 33)
    assert export_env["calls"] == {"status": 0, "result": 0}


def test_run_of_other_bid_cannot_export(export_env):
    with pytest.raises(tenancy.AccessDeniedError):
        tenancy.export_full_analysis_report_for_organization(1295, "org-a", 999)


def test_source_snapshot_of_other_bid_never_used(export_env, monkeypatch):
    import database as db
    monkeypatch.setattr(db, "get_analysis_run", lambda r: {"id": r, "bid_id": 4242})
    out = tenancy.export_full_analysis_report_for_organization(1295, "org-a", 33)
    assert out["filename"] == "Bid_Intelligence_T_Full_Analysis.pdf"


def test_page_prepare_export_caches_and_never_starts(monkeypatch):
    calls = []

    def fake_export(bid_id, org, run_id):
        calls.append(run_id)
        return {"pdf": b"%PDF-x", "filename": "f.pdf"}

    monkeypatch.setattr(tenancy, "export_full_analysis_report_for_organization", fake_export)
    monkeypatch.setattr(tenancy, "start_full_analysis_for_organization", _trap)
    session = {}
    assert page.prepare_export(1295, "org", 33, "PARTIAL", session)["filename"] == "f.pdf"
    assert page.prepare_export(1295, "org", 33, "PARTIAL", session)["filename"] == "f.pdf"
    assert calls == [33]
    assert "error" in page.prepare_export(1295, "org", 34, "RUNNING", session)
    assert calls == [33]


def test_page_prepare_export_denied(monkeypatch):
    def deny(*a):
        raise tenancy.AccessDeniedError("x")
    monkeypatch.setattr(tenancy, "export_full_analysis_report_for_organization", deny)
    session = {}
    assert "error" in page.prepare_export(1, "org", 2, "COMPLETE", session)
    assert not session


def test_report_module_is_pure_presentation():
    tree = ast.parse((ROOT / "full_analysis_report.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    for bad in ("anthropic", "full_analysis", "full_analysis_service", "analysis_service", "fast_analysis",
                "database", "tenancy", "streamlit"):
        assert bad not in imported
