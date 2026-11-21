"""Application integration: start, track and read engine analyses of a bid.

Every public function here is reached only through tenancy.py wrappers that
call require_bid_access(bid_id, organization_id) first. The engine reads only
the bid's own source documents; it never reads another bid, another tenant,
organisational memory or a content library (constraint C1).

Credentials: ENGINE_ANTHROPIC_API_KEY (a dedicated key, so rebuild costs are
tracked separately) or the application's Anthropic key. The independent
OpenAI analyst runs only when ENGINE_OPENAI_CLIENT_DATA_AUTHORIZED=yes and its
key/model are configured; otherwise runs are recorded as SINGLE_ANALYST."""
from __future__ import annotations

import json
import os
import threading
import traceback
from datetime import datetime, timezone

from engine import ENGINE_VERSION, pipeline
from engine.package import build_package
from engine.providers import UsageLedger
from engine.render import render

SOURCE_TYPE = "RFP / Source"
_ACTIVE: dict[int, threading.Thread] = {}


class EngineUnavailable(RuntimeError):
    """Persistence (migration 027) or credentials are not available."""


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
    def fn(analysis: dict) -> dict:
        import buyer_research
        subj = buyer_research.research_subject(bid_id)
        client = subj.get("client") or analysis.get("buyer") or ""
        title = subj.get("title") or analysis.get("title") or ""
        if not client:
            return {"status": "SKIPPED"}
        ctx = " ".join(s.get("text", "") for s in analysis.get("summary") or [])[:600]
        return buyer_research.run_research(client, title, subj.get("reference") or analysis.get("reference") or None,
                                           api_key, context=ctx)
    return fn


def start(bid_id: int, organization_id: str, *, created_by: str | None = None, execution: str = "background",
          roles: pipeline.EngineRoles | None = None) -> dict:
    """Creates an engine run for the bid's current package and executes it."""
    import database as db
    key = engine_api_key()
    if roles is None and not key:
        raise EngineUnavailable("no Anthropic API key is configured for the engine")
    package = load_bid_package(bid_id)
    if not package.documents:
        raise ValueError("this bid has no source documents to analyse")
    roles = roles or pipeline.default_roles(anthropic_key=key)
    previous = next((r for r in db.get_engine_runs(bid_id) if r.get("status") == "COMPLETE"), None)
    config_ = {k: v.describe() for k, v in (("primary", roles.primary), ("independent", roles.independent),
                                            ("adjudicator", roles.adjudicator)) if v}
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
    args = (bid_id, run_id, package, roles, key, previous)
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


def _execute(bid_id, run_id, package, roles, key, previous) -> None:
    import database as db
    db.update_engine_run(run_id, bid_id, {"status": "RUNNING", "started_at": _now(), "last_progress_at": _now()})
    ledger = UsageLedger(f"bid{bid_id}-run{run_id}", path=os.getenv("ENGINE_COST_LEDGER"))

    def progress(*a):
        try:
            db.update_engine_run(run_id, bid_id, {"last_progress_at": _now()})
        except Exception:
            pass
    try:
        result = pipeline.run(package, roles, ledger=ledger, progress=progress,
                              research_fn=_research_fn(bid_id, key), previous=_load_previous(bid_id, previous))
        base = f"{int(bid_id)}/engine/{int(run_id)}"
        fields = {"record": result.record, "verification": result.record.get("verification"),
                  "completed_at": _now(), "status": result.record.get("status", "FAILED")}
        if result.record.get("status") == "COMPLETE":
            fields["result_path"] = db.upload_bytes_object(f"{base}/result.json",
                                                           json.dumps(result.to_dict(), default=str).encode("utf-8"),
                                                           "application/json")
            fields["fast_pdf_path"] = db.upload_bytes_object(f"{base}/fast.pdf", render(result.composed["fast"]),
                                                             "application/pdf")
            fields["full_pdf_path"] = db.upload_bytes_object(f"{base}/full.pdf", render(result.composed["full"]),
                                                             "application/pdf")
        else:
            fields["failure_reason"] = json.dumps(result.record.get("error"))[:500]
        db.update_engine_run(run_id, bid_id, fields)
    except Exception as exc:
        db.update_engine_run(run_id, bid_id, {"status": "FAILED", "verification": "FAILED", "completed_at": _now(),
                                              "failure_reason": f"{type(exc).__name__}: {exc}"[:500],
                                              "record": {"traceback": traceback.format_exc()[-2000:],
                                                         "usage": ledger.summary()}})
    finally:
        _ACTIVE.pop(run_id, None)


def status(bid_id: int, run_id: int | None = None) -> dict | None:
    import database as db
    runs = db.get_engine_runs(bid_id)
    row = next((r for r in runs if run_id is None or int(r["id"]) == int(run_id)), None)
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
