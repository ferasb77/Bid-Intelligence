"""Application integration: start, track and read engine analyses of a bid.

Every public function here is reached only through tenancy.py wrappers that
call require_bid_access(bid_id, organization_id) first. The engine reads only
the bid's own source documents; it never reads another bid, another tenant,
organisational memory or a content library (constraint C1).

Credentials: ENGINE_ANTHROPIC_API_KEY (a dedicated key, so rebuild costs are
tracked separately) or the application's Anthropic key. The independent
OpenAI analyst runs only when ENGINE_OPENAI_CLIENT_DATA_AUTHORIZED=yes and its
key/model are configured; otherwise runs are recorded as SINGLE_ANALYST.

Modes: a FAST run produces the Opportunity Snapshot (fast.pdf) only; a FULL
run produces both reports. Each run is checked by the pre-flight before it is
created (a run that could exceed its cap never starts), spends within its
mode's ledger, and checkpoints every model answer under its own storage
prefix; a new run of the same bid reads the earlier runs' checkpoints, so a
stopped run resumes and FULL reuses FAST's extraction. The mode is kept in
the run's model_config (no schema change)."""
from __future__ import annotations

import json
import os
import threading
import traceback
from datetime import datetime, timezone

from engine import ENGINE_VERSION, budget, pipeline
from engine.checkpoints import StorageStore
from engine.package import build_package
from engine.render import render

SOURCE_TYPE = "RFP / Source"
_ACTIVE: dict[int, threading.Thread] = {}


class EngineUnavailable(RuntimeError):
    """Persistence (migration 027) or credentials are not available."""


class EngineBudgetRefused(RuntimeError):
    """The pre-flight found that this run could exceed its mode's cost cap; nothing was sent."""


class EngineBusy(RuntimeError):
    """Another engine run of this bid is still queued or running."""


def run_mode(row: dict | None) -> str | None:
    """FAST / FULL; None for runs made before modes existed (they produced both reports)."""
    return ((row or {}).get("model_config") or {}).get("mode")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def engine_api_key() -> str | None:
    import config
    return os.getenv("ENGINE_ANTHROPIC_API_KEY") or config.get_api_key()


def load_bid_package(bid_id: int) -> tuple:
    """The bid's own source documents, extracted with the application's
    extractor (text, page markers, OCR metadata). Returns (package, manifest)."""
    import database as db
    from extractor import extract_document_with_metadata
    import hashlib
    docs = [d for d in db.get_documents(bid_id) if d.get("doc_type") == SOURCE_TYPE]
    docs.sort(key=lambda d: (str(d.get("created_at") or ""), d.get("id") or 0))
    out = []
    for d in docs:
        data = db.download_file(d.get("storage_path"))
        if not data:
            out.append({"name": d["name"], "text": f"[[SOURCE: {d['name']}]]\n[Unsupported file format. The stored "
                                                   f"file could not be downloaded]", "meta": {},
                        "uploaded_at": str(d.get("created_at") or "")})
            continue
        text, meta = extract_document_with_metadata(data, d["name"])
        out.append({"name": d["name"], "text": text, "meta": meta, "uploaded_at": str(d.get("created_at") or ""),
                    "sha256": hashlib.sha256(data).hexdigest()})
    return build_package(out, data_class="CLIENT")


def _research_fn(bid_id: int, api_key: str | None):
    def fn(analysis: dict, ledger=None) -> dict:
        import buyer_research
        subj = buyer_research.research_subject(bid_id)
        client = subj.get("client") or analysis.get("buyer") or ""
        title = subj.get("title") or analysis.get("title") or ""
        if not client:
            return {"status": "SKIPPED"}
        ctx = " ".join(s.get("text", "") for s in analysis.get("summary") or [])[:600]
        return buyer_research.run_research(client, title, subj.get("reference") or analysis.get("reference") or None,
                                           api_key, context=ctx, ledger=ledger)
    return fn


def _models(roles: pipeline.EngineRoles) -> dict:
    def model_of(a, purpose):
        if a is None:
            return None
        route = getattr(a, "route", None)
        return (route(purpose) if route else a).model
    return {"extract": model_of(roles.primary, "extract:x"),
            "synthesis": model_of(roles.adjudicator, "analysis"),
            "writer": model_of(roles.writer or roles.adjudicator, "analysis")}


def start(bid_id: int, organization_id: str, *, mode: str = "FULL", created_by: str | None = None,
          execution: str = "background", roles: pipeline.EngineRoles | None = None) -> dict:
    """Creates an engine run of `mode` for the bid's current package and executes it.
    Refused (nothing created, nothing sent) while another run of the bid is
    active, or when the pre-flight worst case exceeds the mode's cap."""
    import database as db
    if mode not in budget.MODES:
        raise ValueError(f"unknown engine mode {mode!r}")
    key = engine_api_key()
    if roles is None and not key:
        raise EngineUnavailable("no Anthropic API key is configured for the engine")
    runs = db.get_engine_runs(bid_id)
    if any(r.get("status") in ("QUEUED", "RUNNING") and not (status(bid_id, r["id"]) or {}).get("possibly_interrupted")
           for r in runs):
        raise EngineBusy("an analysis of this bid is already running")
    package = load_bid_package(bid_id)
    if not package.documents:
        raise ValueError("this bid has no source documents to analyse")
    roles = roles or pipeline.default_roles(anthropic_key=key, mode=mode)
    m = _models(roles)
    pf = budget.preflight(package, mode, extract_model=m["extract"], synthesis_model=m["synthesis"],
                          writer_model=m["writer"])
    if not pf["ok"]:
        raise EngineBudgetRefused("; ".join(pf["problems"]))
    previous = next((r for r in runs if r.get("status") == "COMPLETE" and run_mode(r) in (mode, None)), None)
    config_ = {k: v.describe() for k, v in (("primary", roles.primary), ("independent", roles.independent),
                                            ("adjudicator", roles.adjudicator), ("writer", roles.writer)) if v}
    config_.update(mode=mode, cap_usd=pf["cap_usd"], preflight_worst_usd=pf["worst_case_required_usd"])
    try:
        row = db.create_engine_run(bid_id, organization_id, engine_version=ENGINE_VERSION,
                                   package_hash=package.package_hash, documents=package.manifest(),
                                   model_config=config_, created_by=created_by,
                                   previous_run_id=previous["id"] if previous else None)
    except Exception as exc:
        if "engine_runs" in str(exc):
            raise EngineUnavailable("engine persistence (migration 027) is not applied to this database") from exc
        raise
    run_id = int(row["id"])
    earlier = [int(r["id"]) for r in runs if int(r["id"]) != run_id]     # newest first
    args = (bid_id, run_id, package, roles, key, previous, mode, earlier, pf)
    if execution == "inline":
        _execute(*args)
    else:
        t = threading.Thread(target=_execute, args=args, daemon=True, name=f"engine-{bid_id}-{run_id}")
        _ACTIVE[run_id] = t
        t.start()
    return {"run_id": run_id, "status": "RUNNING" if execution != "inline" else (db.get_engine_run(run_id, bid_id) or {}).get("status")}


def _load_previous(bid_id: int, previous: dict | None) -> dict | None:
    if not previous or not previous.get("result_path"):
        return None
    import database as db
    try:
        data = json.loads(db.download_file(previous["result_path"]).decode("utf-8"))
        return {"run_id": previous["id"], "register": data.get("register") or {},
                "documents": [d["name"] for d in previous.get("documents") or []]}
    except Exception:
        return None


def _execute(bid_id, run_id, package, roles, key, previous, mode="FULL", earlier=(), preflight=None) -> None:
    import database as db
    db.update_engine_run(run_id, bid_id, {"status": "RUNNING", "started_at": _now(), "last_progress_at": _now()})
    ledger = pipeline.new_ledger(mode, f"bid{bid_id}-run{run_id}", path=os.getenv("ENGINE_COST_LEDGER"))
    store = StorageStore(bid_id, run_id, list(earlier))

    def progress(*a):
        try:
            db.update_engine_run(run_id, bid_id, {"last_progress_at": _now()})
        except Exception:
            pass
    try:
        result = pipeline.run(package, roles, mode=mode, ledger=ledger, progress=progress,
                              research_fn=_research_fn(bid_id, key) if mode == "FULL" else None,
                              previous=_load_previous(bid_id, previous), store=store, preflight=preflight)
        base = f"{int(bid_id)}/engine/{int(run_id)}"
        fields = {"record": result.record, "verification": result.record.get("verification"),
                  "completed_at": _now(), "status": result.record.get("status", "FAILED")}
        if result.record.get("status") == "COMPLETE":
            fields["result_path"] = db.upload_bytes_object(f"{base}/result.json",
                                                           json.dumps(result.to_dict(), default=str).encode("utf-8"),
                                                           "application/json")
            fields["fast_pdf_path"] = db.upload_bytes_object(f"{base}/fast.pdf", render(result.composed["fast"]),
                                                             "application/pdf")
            if result.composed.get("full"):
                fields["full_pdf_path"] = db.upload_bytes_object(f"{base}/full.pdf", render(result.composed["full"]),
                                                                 "application/pdf")
        else:
            fields["failure_reason"] = json.dumps(result.record.get("error"))[:500]
            # what a failed run did (stages, usage, refusals) is kept for diagnosis -- never exported
            try:
                db.upload_bytes_object(f"{base}/partial.json",
                                       json.dumps({"record": result.record, "exportable": False},
                                                  default=str).encode("utf-8"), "application/json")
            except Exception:
                pass
        db.update_engine_run(run_id, bid_id, fields)
    except Exception as exc:
        db.update_engine_run(run_id, bid_id, {"status": "FAILED", "verification": "FAILED", "completed_at": _now(),
                                              "failure_reason": f"{type(exc).__name__}: {exc}"[:500],
                                              "record": {"traceback": traceback.format_exc()[-2000:],
                                                         "usage": ledger.summary()}})
    finally:
        _ACTIVE.pop(run_id, None)


def status(bid_id: int, run_id: int | None = None, mode: str | None = None) -> dict | None:
    """The run `run_id`, or the newest run of `mode` (runs made before modes
    existed count for both), or the newest run."""
    import database as db
    runs = db.get_engine_runs(bid_id)
    row = next((r for r in runs if (run_id is None or int(r["id"]) == int(run_id))
                and (mode is None or run_mode(r) in (mode, None))), None)
    if row and row.get("status") in ("QUEUED", "RUNNING") and int(row["id"]) not in _ACTIVE:
        last = row.get("last_progress_at") or row.get("created_at")
        try:
            stale = (datetime.now(timezone.utc) - datetime.fromisoformat(str(last).replace("Z", "+00:00"))).total_seconds()
        except Exception:
            stale = 0
        row = dict(row, possibly_interrupted=stale > 900)
    return row


def result(bid_id: int, run_id: int) -> dict | None:
    import database as db
    row = db.get_engine_run(run_id, bid_id)
    if not row or not row.get("result_path"):
        return None
    return json.loads(db.download_file(row["result_path"]).decode("utf-8"))


def pdf(bid_id: int, run_id: int, kind: str) -> bytes | None:
    import database as db
    row = db.get_engine_run(run_id, bid_id)
    path = (row or {}).get("fast_pdf_path" if kind == "FAST" else "full_pdf_path")
    return db.download_file(path) if path else None


def mark_interrupted(bid_id: int, run_id: int) -> None:
    """A run whose process died (no live thread, no progress for 15 minutes)
    is closed as FAILED so a new run can start; nothing is reported as verified."""
    import database as db
    row = status(bid_id, run_id)
    if row and row.get("possibly_interrupted"):
        db.update_engine_run(run_id, bid_id, {"status": "FAILED", "verification": "FAILED", "completed_at": _now(),
                                              "failure_reason": "interrupted: no progress for 15 minutes"})
