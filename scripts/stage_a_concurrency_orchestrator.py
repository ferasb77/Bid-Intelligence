"""Bounded document-level concurrency orchestrator for Stage A (Package 4).

Each document's own extraction remains fully serial internally -- this module
never touches extractor.py's chunk/recovery/merge order. The only concurrency
introduced is across independent documents, bounded by max_document_concurrency,
via a ThreadPoolExecutor:

  * Each document gets its own telemetry list, never shared across threads --
    extract_document_facts() already accepts a caller-supplied `telemetry`
    list; giving each worker a fresh one makes cross-document telemetry
    interference structurally impossible (no shared mutable object between
    threads), with zero changes to extractor.py.
  * Each document gets its own Anthropic client -- extract_document_facts()
    already constructs one internally via get_anthropic_client() on every
    call (confirmed: config.get_anthropic_client returns a brand-new
    anthropic.Anthropic(...) instance every call, no caching/singleton), so
    no client is ever shared between concurrent document workers, with zero
    changes to extractor.py or config.py.
  * Results are always reconstructed in corpus order (by document index),
    never by completion order -- ThreadPoolExecutor's as_completed() yields
    futures in completion order, but this module only uses that order to
    detect completion; final assembly indexes back into corpus order.
  * A worker never lets an extraction exception escape uncaught -- it is
    captured onto that document's own DocumentResult.error, so one
    document's failure can never cancel or hide another, already-completed
    document's result. The caller (pilot script) decides whether to halt
    after inspecting the returned results for any errors -- this module
    itself never silently retries or swallows.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field


@dataclass
class DocumentJob:
    index: int
    name: str
    doc_text: str


@dataclass
class DocumentResult:
    index: int
    name: str
    facts: dict | None
    telemetry: list = field(default_factory=list)
    error: str | None = None
    wall_seconds: float = 0.0
    started_at: float = 0.0
    ended_at: float = 0.0
    worker_thread: str = ""


class RetryLogCapture(logging.Handler):
    """Thread-safe capture of the anthropic SDK's own retry/status-code log
    records (it logs "Retrying due to status code %i" and "Retrying request
    to %s in %f seconds" via the stdlib `logging` module -- see
    anthropic._base_client). Python's logging module guarantees emit() is
    safe to call concurrently from multiple threads, so no extra locking is
    required around the underlying list beyond a defensive lock for the
    append itself."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self._lock = threading.Lock()
        self.records: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        entry = {"logger": record.name, "level": record.levelname, "message": record.getMessage()}
        with self._lock:
            self.records.append(entry)


def run_concurrent_documents(jobs: list[DocumentJob], extract_fn, api_key: str,
                              max_document_concurrency: int = 2) -> tuple[list[DocumentResult], list[dict]]:
    """Run `extract_fn` (extractor.extract_document_facts, injected for
    testability) over `jobs`, at most `max_document_concurrency` at once.

    Returns (results_in_corpus_order, retry_log_records). Never raises for a
    per-document extraction failure -- inspect each DocumentResult.error.
    Only re-raises if the orchestration harness itself misbehaves in a way
    that could otherwise silently lose a job (defensive, not expected).
    """
    capture = RetryLogCapture()
    anthropic_logger = logging.getLogger("anthropic")
    prior_level = anthropic_logger.level
    anthropic_logger.addHandler(capture)
    anthropic_logger.setLevel(logging.DEBUG)

    def worker(job: DocumentJob) -> DocumentResult:
        doc_telemetry: list = []
        started_at = time.time()
        t0 = time.monotonic()
        try:
            facts = extract_fn(job.doc_text, job.name, api_key, telemetry=doc_telemetry)
            error = None
        except Exception as exc:
            facts = None
            error = f"{type(exc).__name__}: {exc}"
        return DocumentResult(
            index=job.index, name=job.name, facts=facts, telemetry=doc_telemetry,
            error=error, wall_seconds=round(time.monotonic() - t0, 6),
            started_at=started_at, ended_at=time.time(),
            worker_thread=threading.current_thread().name,
        )

    results_by_index: dict[int, DocumentResult] = {}
    try:
        with ThreadPoolExecutor(max_workers=max_document_concurrency) as pool:
            futures = {pool.submit(worker, job): job for job in jobs}
            for fut in as_completed(futures):
                job = futures[fut]
                try:
                    res = fut.result()
                except Exception as exc:  # orchestration-level failure, not an extraction failure
                    res = DocumentResult(index=job.index, name=job.name, facts=None,
                                          error=f"ORCHESTRATOR_ERROR: {type(exc).__name__}: {exc}")
                results_by_index[res.index] = res
    finally:
        anthropic_logger.removeHandler(capture)
        anthropic_logger.setLevel(prior_level)

    ordered = [results_by_index[job.index] for job in jobs]
    return ordered, capture.records


def merge_telemetry_deterministic(results: list[DocumentResult]) -> list[dict]:
    """Merge per-document telemetry lists into one corpus-ordered list,
    tagging each record with document_id/document_index/original per-document
    call_index, and a new globally-unique merged_call_index reflecting
    (document_index, per-document call_index) order -- NOT wall-clock
    completion order. Deterministic given the same `results` (which is
    itself already corpus-index-ordered by run_concurrent_documents)."""
    merged = []
    for doc_result in results:  # already corpus order
        for rec in doc_result.telemetry:  # already per-document call_index order
            merged_rec = dict(rec)
            merged_rec["document_id"] = doc_result.name
            merged_rec["document_index"] = doc_result.index
            merged_rec["per_document_call_index"] = rec.get("call_index")
            merged_rec["merged_call_index"] = len(merged)
            merged_rec["worker_thread"] = doc_result.worker_thread
            merged.append(merged_rec)
    return merged


def observed_max_simultaneous_requests(merged_telemetry: list[dict]) -> int:
    """Post-hoc, deterministic sweep-line over each call's own
    call_started_at/call_ended_at (already-captured, unmodified telemetry
    fields) -- counts the maximum number of calls whose [start, end)
    intervals overlap at any instant. No orchestrator-level locking or
    counter is needed to answer this; it is fully reconstructable from the
    timestamps every call already records."""
    from datetime import datetime
    events = []
    for rec in merged_telemetry:
        if not rec.get("call_started_at") or not rec.get("call_ended_at"):
            continue
        start = datetime.fromisoformat(rec["call_started_at"])
        end = datetime.fromisoformat(rec["call_ended_at"])
        events.append((start, 1))
        events.append((end, -1))
    events.sort(key=lambda e: (e[0], -e[1]))  # process starts before ends at the same instant
    running = 0
    peak = 0
    for _, delta in events:
        running += delta
        peak = max(peak, running)
    return peak
