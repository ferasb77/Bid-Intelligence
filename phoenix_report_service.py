"""Loads the persisted inputs for the Phoenix reports and the document-update
state of a bid. Read-only; never starts an analysis and never calls a model.

Callers must have verified organization ownership of the bid first
(tenancy.*_for_organization wrappers do this).
"""
from __future__ import annotations

from datetime import datetime

import database as db
import phoenix_reports as pr
import workbook_intelligence as wbi

SOURCE_TYPE = "RFP / Source"


def _ts(v) -> datetime | None:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def source_documents(bid_id: int) -> list[dict]:
    return [d for d in db.get_documents(bid_id) if d.get("doc_type") == SOURCE_TYPE]


def documents_for_run(bid_id: int, run: dict) -> list[dict]:
    """The source documents a FAST run analysed: every 'RFP / Source'
    document that existed when the run was created (FAST reads exactly that
    set). Documents uploaded later belong to the next analysis."""
    created = _ts(run.get("created_at"))
    docs = source_documents(bid_id)
    if not created:
        return docs
    return [d for d in docs if (_ts(d.get("created_at")) or created) <= created]


def fast_runs(bid_id: int) -> list[dict]:
    """COMPLETE FAST runs, oldest first."""
    runs = [r for r in db.list_analysis_runs(bid_id)
            if r.get("analysis_mode") == "FAST" and r.get("status") == "COMPLETE"]
    return sorted(runs, key=lambda r: (str(r.get("created_at")), r["id"]))


def pending_documents(bid_id: int) -> list[dict]:
    """Source documents added after the latest COMPLETE FAST run -- i.e. not
    yet included in an analysis. Every source document if none completed."""
    runs = fast_runs(bid_id)
    docs = source_documents(bid_id)
    if not runs:
        return docs
    created = _ts(runs[-1].get("created_at"))
    return [d for d in docs if created and (_ts(d.get("created_at")) or created) > created]


def _load_texts(docs: list[dict]) -> tuple[list[tuple[str, str]], list[tuple[str, bytes]]]:
    from extractor import extract_document_with_metadata
    texts, files = [], []
    for d in docs:
        data = db.download_file(d.get("storage_path"))
        if not data:
            continue
        text, _ = extract_document_with_metadata(data, d["name"])
        texts.append((d["name"], text))
        if wbi.is_workbook(d["name"]):
            files.append((d["name"], data))
    return texts, files


def _fast_result(run_id: int) -> dict:
    res = db.get_analysis_result(run_id) or {}
    return ((res.get("fast_analysis_result_snapshot") or {}).get("result")) or {}


def build_facts_for_run(bid_id: int, run_id: int) -> dict:
    run = db.get_analysis_run(run_id)
    if not run or int(run.get("bid_id")) != int(bid_id) or run.get("analysis_mode") != "FAST":
        raise ValueError(f"run {run_id} is not a FAST run of bid {bid_id}")
    docs = documents_for_run(bid_id, run)
    texts, files = _load_texts(docs)
    previous = [r for r in fast_runs(bid_id) if (str(r.get("created_at")), r["id"]) < (str(run.get("created_at")), run["id"])]
    prev_result, prev_names = None, None
    if previous:
        p = previous[-1]
        prev_result = _fast_result(p["id"])
        prev_names = [d["name"] for d in documents_for_run(bid_id, p)]
    return pr.build_facts(
        bid=db.get_bid(bid_id) or {"id": bid_id}, fast_result=_fast_result(run_id), documents=texts,
        files=files, previous_result=prev_result, previous_doc_names=prev_names,
        analysis_date=str(run.get("completed_at") or run.get("created_at") or "")[:10] or None, run_id=run_id)


def snapshot_pdf(bid_id: int, run_id: int) -> dict:
    return pr.render_snapshot(build_facts_for_run(bid_id, run_id))


def assessment_pdf(bid_id: int, full_run_id: int) -> dict:
    import buyer_research
    import full_analysis_service
    status = full_analysis_service.get_full_analysis_status(bid_id, full_run_id) or {}
    source = status.get("source_analysis_run_id")
    if not source:
        bundle = full_analysis_service.get_full_analysis_result(bid_id, full_run_id) or {}
        source = (bundle.get("result") or {}).get("source_analysis_run_id")
    if not source:
        raise ValueError("this Full Analysis run has no source FAST analysis")
    facts = build_facts_for_run(bid_id, int(source))
    return pr.render_assessment(facts, full_status=status.get("status"),
                                research=buyer_research.for_report(bid_id, full_run_id))
