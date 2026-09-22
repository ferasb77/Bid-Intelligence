"""
analysis_service.py

The single application-level service boundary for invoking the Fast
Analysis engine (frozen V4 behavior, fast_analysis.py) against a bid's
persisted document corpus, and for managing the resulting analysis_runs
lifecycle.

UI/API code must go through this module -- never call fast_analysis.py,
scripts/fast_analysis_report_adapter.py, or fast_analysis_app_adapter.py
directly (instruction 10). This module contains no extraction routes,
prompts, chunking, focused-task internals, or ambiguity-detection details
-- those remain entirely inside fast_analysis.py, unmodified.

Deep Verify (extractor.extract_procurement_package, called from
app.py's page_new_bid) is NOT invoked from here and is NOT modified by this
module -- it remains its own separate, explicit, synchronous path,
unchanged (instruction 18).

Background execution: this repo has no existing job-queue infrastructure
(no Celery/RQ/APScheduler; see FAST_ANALYSIS_PRODUCT_INTEGRATION_PHASE1_REPORT.md
S1 for the full architecture inspection). The smallest production-safe
mechanism for this Streamlit+Supabase deployment is an in-process daemon
thread: Streamlit Community Cloud and a local `streamlit run` both keep one
long-lived Python process per app instance (not one process per request),
so a thread started during one request's execution keeps running after
that request/rerun completes and is visible to later reruns of the same
process. This is NOT resilient to a process restart while a run is
in-flight -- see the module docstring's "Known limitations" note in the
Phase 1 report. It does not introduce a new dependency, and it reuses the
same threading pattern fast_analysis.py's own run_fast_analysis_corpus()
already uses one level down for concurrent document calls.

Phase 2 adds a minimal, bounded stuck-run safety net (is_run_stuck /
mark_run_failed_as_stuck) for exactly that scenario -- a run whose thread
died with the process, leaving it stranded in a non-terminal status with
no thread left to finish it. This is a user-initiated, deliberate action
surfaced in the UI, never an automatic background sweep or silent retry
(instruction 20: any application-level retry must be bounded and
deliberate).
"""
from __future__ import annotations

import hashlib
import threading
import time
import traceback
from datetime import datetime, timezone

import database as db
from extractor import extract_document_with_metadata
from fast_analysis import (
    run_fast_analysis_corpus, FastAnalysisResult, route_document, find_section,
    BATCH_GROUP, ROUTE_SKIP, ROUTE_EVAL_ONLY, ROUTE_IDENTITY_EVAL_REQ, ROUTE_COMMERCIAL_ONLY,
    serialize_fast_analysis_result, deserialize_fast_analysis_result, RawSnapshotSchemaError,
    _telemetry_audit_summary,
)
from fast_analysis_app_adapter import build_opportunity_intelligence
from scripts.fast_analysis_report_adapter import build_fast_report_content
from scripts.build_boc_bid_intelligence_preview_pdf import build as _render_pdf

# Stable engine/version identifier persisted on every run -- historical
# analyses remain attributable to the engine that produced them regardless
# of what source code is deployed when they're later read back
# (instruction 9).
FAST_ANALYSIS_ENGINE_VERSION = "fast-analysis-v4"

# Sentinel explicit state for load_raw_fast_analysis_result() when a run has
# no durably persisted raw snapshot at all -- e.g. any run created before
# migrations/012_fast_analysis_result_snapshot.sql existed (Phoenix run 13
# is the concrete example that motivated this feature). Never conflate this
# with an incompatible-schema snapshot that IS present (see
# RawSnapshotSchemaError) -- those are different failure modes.
RAW_FAST_ANALYSIS_SNAPSHOT_UNAVAILABLE = "RAW_FAST_ANALYSIS_SNAPSHOT_UNAVAILABLE"

# Frozen V4 accepted behavior (instruction 2) -- do not change.
MAX_DOCUMENT_CONCURRENCY = 2

_LIFECYCLE_STATES = ("QUEUED", "PREPARING", "ANALYZING", "ASSEMBLING", "COMPLETE", "FAILED")
_NON_TERMINAL_STATES = ("QUEUED", "PREPARING", "ANALYZING", "ASSEMBLING")

# Phase 2 stuck-run safety net (instruction 20: bounded, deliberate --
# never an automatic silent retry). The V4 benchmark's own live run was
# ~200s; this threshold gives a wide, deliberately generous margin before a
# run is even offered as "possibly stuck" to a user, so a merely slow run
# is never mistaken for a crashed one.
STUCK_RUN_THRESHOLD_SECONDS = 15 * 60

# ---------------------------------------------------------------------------
# Phase 2: durable, truthful progress while a run is still ANALYZING.
#
# Each constant below is only ever marked reached in response to a REAL Fast
# Analysis task-completion event delivered through run_fast_analysis_corpus's
# `on_task_done` hook (see fast_analysis.py) or another genuine lifecycle
# boundary this service already controls (corpus preparation, ambiguity
# detection completing, report assembly completing) -- never from elapsed
# time. See _ProgressTracker below for exactly which event maps to which
# milestone, and FAST_ANALYSIS_PRODUCT_INTEGRATION_PHASE2_REPORT.md for the
# full rationale, including which candidate early facts were judged NOT
# safe to expose before COMPLETE.
# ---------------------------------------------------------------------------
MILESTONE_CORPUS_PREPARED = "CORPUS_PREPARED"
MILESTONE_OPPORTUNITY_IDENTIFIED = "OPPORTUNITY_IDENTIFIED"
MILESTONE_DATES_READY = "DATES_READY"
MILESTONE_PROCUREMENT_STRUCTURE_READY = "PROCUREMENT_STRUCTURE_READY"
MILESTONE_QUALIFICATION_READY = "QUALIFICATION_READY"
MILESTONE_EVALUATION_READY = "EVALUATION_READY"
MILESTONE_COMMERCIAL_READY = "COMMERCIAL_READY"
MILESTONE_AMBIGUITIES_READY = "AMBIGUITIES_READY"
MILESTONE_REPORT_ASSEMBLED = "REPORT_ASSEMBLED"

# Canonical DISPLAY order -- the order milestones are actually reached in is
# NOT guaranteed to match this (tasks complete concurrently, in whatever
# order the LLM calls happen to return), so the UI checks each milestone's
# membership in the persisted reached-set against this fixed list rather
# than assuming reach-order.
MILESTONE_ORDER = [
    MILESTONE_CORPUS_PREPARED, MILESTONE_OPPORTUNITY_IDENTIFIED, MILESTONE_DATES_READY,
    MILESTONE_PROCUREMENT_STRUCTURE_READY, MILESTONE_QUALIFICATION_READY,
    MILESTONE_EVALUATION_READY, MILESTONE_COMMERCIAL_READY, MILESTONE_AMBIGUITIES_READY,
    MILESTONE_REPORT_ASSEMBLED,
]

# User-facing copy (instruction 4: no internal route/task names in the UI).
MILESTONE_UI_LABEL = {
    MILESTONE_CORPUS_PREPARED: "Preparing procurement documents",
    MILESTONE_OPPORTUNITY_IDENTIFIED: "Understanding the opportunity",
    MILESTONE_DATES_READY: "Identifying critical dates and requirements",
    MILESTONE_PROCUREMENT_STRUCTURE_READY: "Mapping procurement structure",
    MILESTONE_QUALIFICATION_READY: "Reviewing qualification requirements",
    MILESTONE_EVALUATION_READY: "Mapping evaluation criteria",
    MILESTONE_COMMERCIAL_READY: "Reviewing commercial terms",
    MILESTONE_AMBIGUITIES_READY: "Checking ambiguities and bid risks",
    MILESTONE_REPORT_ASSEMBLED: "Preparing your intelligence report",
}


def _compute_eval_tasks_total(documents: list[tuple[str, str]]) -> int:
    """How many real task-completion events EVALUATION_READY must wait for,
    computed BEFORE the engine runs. Mirrors (read-only -- calls only the
    engine's own public, deterministic functions, duplicates no extraction
    or merge logic) run_fast_analysis_corpus's own task-list construction
    (its steps 2/2b) so this number is always exactly the number of tasks
    that actually contribute evaluation data for THIS corpus, not a guess."""
    names = [n for n, _ in documents]
    batch_members = [n for n in BATCH_GROUP if n in names]
    total = 1 if batch_members else 0
    for name, _ in documents:
        route = route_document(name)
        if route == ROUTE_SKIP or name in batch_members:
            continue
        if route in (ROUTE_EVAL_ONLY, ROUTE_IDENTITY_EVAL_REQ):
            total += 1
    # Focused rated_criteria jobs (engine step 2b) are located independently
    # of routing/batching -- ANY non-skipped document's text can contain the
    # heading, including one that was also batched above.
    for name, doc_text in documents:
        if route_document(name) == ROUTE_SKIP:
            continue
        if find_section(doc_text, "rated_criteria"):
            total += 1
    return total


def _compute_commercial_tasks_total(documents: list[tuple[str, str]]) -> int:
    """How many real task-completion events COMMERCIAL_READY must wait for.
    Phase 5: also counts the additive 'commercial_supplement' task
    run_fast_analysis_corpus now dispatches for every ROUTE_IDENTITY_EVAL_REQ
    document (see fast_analysis.py step 2c) -- mirrors that same,
    unmodified, public routing logic, not a guess."""
    return sum(1 for name, _ in documents
              if route_document(name) in (ROUTE_COMMERCIAL_ONLY, ROUTE_IDENTITY_EVAL_REQ))


class _ProgressTracker:
    """Accumulates milestones and a small set of early, already-extracted
    facts from REAL run_fast_analysis_corpus task-completion events (via
    `on_task_done`), persisting to analysis_runs.progress as they happen so
    a page refresh or a different browser tab mid-run reads current state
    (instruction 2: progress must survive refresh/navigate-away/reconnect,
    not live only in thread memory).

    A bug in this tracker must never fail the underlying analysis -- every
    method that can raise is wrapped so a milestone-mapping mistake is, at
    worst, a missed UI update, never a FAILED run (instruction: this is a
    non-critical, additive UX feature, not part of the engine's own
    correctness contract).

    Early facts are read directly off the master document's own
    `doc_metadata` / `typed_observations` -- the model's literal extracted
    values, never re-derived through scripts/fast_analysis_report_adapter.py.
    That adapter's SERVICE_CATEGORIES/GATE_EXAMPLES helpers fall back to
    static placeholder content (FACT_ORIGINS "SAFETY_NET_FALLBACK") when a
    field is genuinely missing -- correct behavior for a FINAL report where
    that's a rare edge case, but unsafe to invoke on a deliberately partial,
    still-in-progress result, where most fields are expected to be missing
    and the fallback would fire constantly, showing placeholder content as
    if it were real early intelligence. This is why "procurement/category
    structure" (which depends on that adapter) is NOT exposed as an early
    fact here -- see the Phase 2 report."""

    def __init__(self, run_id: int, documents: list[tuple[str, str]]):
        self.run_id = run_id
        self._milestones: list[dict] = []
        self._reached: set[str] = set()
        self._early_facts: dict = {}
        self._eval_tasks_total = _compute_eval_tasks_total(documents)
        self._eval_tasks_done = 0
        self._commercial_tasks_total = _compute_commercial_tasks_total(documents)
        self._commercial_tasks_done = 0

    def mark(self, milestone: str) -> None:
        """Hardening pass: wrapped here, at the single choke point every
        caller (on_task_done, and _execute_fast_analysis_run's own direct
        calls for CORPUS_PREPARED/AMBIGUITIES_READY/REPORT_ASSEMBLED) goes
        through -- not just inside on_task_done's own wrapper -- so the
        'never fails the underlying analysis' promise holds regardless of
        which code path calls mark()."""
        try:
            if milestone in self._reached:
                return
            self._reached.add(milestone)
            self._milestones.append({
                "milestone": milestone,
                "reached_at": datetime.now(timezone.utc).isoformat(),
            })
            self._persist()
        except Exception:
            pass

    def set_early_facts(self, **facts) -> None:
        """Only ever ADDS a field the first time a truthy value for it
        arrives -- never overwrites with a later, possibly-empty value, and
        never invents a value for a field that hasn't actually been
        extracted yet (instruction 3: 'do not expose ... unvalidated
        intermediate output'). Wrapped defensively for the same reason as
        mark() above."""
        try:
            changed = False
            for key, value in facts.items():
                if value and not self._early_facts.get(key):
                    self._early_facts[key] = value
                    changed = True
            if changed:
                self._persist()
        except Exception:
            pass

    def _persist(self) -> None:
        try:
            db.update_analysis_run(self.run_id, {
                "progress": {"milestones": self._milestones, "early_facts": self._early_facts},
            })
        except Exception:
            pass

    def _eval_task_done(self) -> None:
        self._eval_tasks_done += 1
        if self._eval_tasks_total and self._eval_tasks_done >= self._eval_tasks_total:
            self.mark(MILESTONE_EVALUATION_READY)

    def _commercial_task_done(self) -> None:
        """Phase 5: COMMERCIAL_READY is now a counter, not a single-completion
        trigger -- a corpus can have more than one commercial-contributing
        task (a dedicated ROUTE_COMMERCIAL_ONLY document, the additive
        'commercial_supplement' pass on ROUTE_IDENTITY_EVAL_REQ documents,
        or both), so it must wait for all of them, exactly like
        _eval_task_done already does for evaluation."""
        self._commercial_tasks_done += 1
        if self._commercial_tasks_total and self._commercial_tasks_done >= self._commercial_tasks_total:
            self.mark(MILESTONE_COMMERCIAL_READY)

    def mark_vacuous_milestones(self) -> None:
        """Called once, right after CORPUS_PREPARED: a milestone whose
        required task count is genuinely zero for this corpus (e.g. no
        commercial-only document was uploaded) is vacuously reached
        immediately rather than waiting forever for an event that will
        never happen."""
        if self._eval_tasks_total == 0:
            self.mark(MILESTONE_EVALUATION_READY)
        if self._commercial_tasks_total == 0:
            self.mark(MILESTONE_COMMERCIAL_READY)

    def on_task_done(self, kind: str, payload, task_result) -> None:
        try:
            self._handle(kind, payload, task_result)
        except Exception:
            pass

    def _handle(self, kind: str, payload, task_result) -> None:
        if kind == "focused":
            name, section_kind, _ = payload
            if section_kind == "rated_criteria":
                self._eval_task_done()
            return

        if kind == "commercial_supplement":
            self._commercial_task_done()
            return

        if kind == "batch":
            # The whole batch is exactly one eval-contributing task (matches
            # the single "batch" task the engine itself dispatches); batched
            # documents never carry identity/commercial data.
            self._eval_task_done()
            return

        # kind == "single"
        name = payload[0]
        data = (task_result or {}).get(name) or {}
        route = route_document(name)

        if route == ROUTE_IDENTITY_EVAL_REQ:
            meta = data.get("doc_metadata") or {}
            if meta.get("title") or meta.get("client"):
                self.mark(MILESTONE_OPPORTUNITY_IDENTIFIED)
                self.set_early_facts(title=meta.get("title"), buyer=meta.get("client"),
                                      file_number=meta.get("file_number"))
            if meta.get("submission_deadline") or meta.get("clarification_deadline"):
                self.mark(MILESTONE_DATES_READY)
                self.set_early_facts(submission_deadline=meta.get("submission_deadline"),
                                      clarification_deadline=meta.get("clarification_deadline"))
            mechanic = next(
                (o.get("original_value") for o in data.get("typed_observations", [])
                 if isinstance(o, dict) and o.get("family") == "PROCUREMENT_MECHANIC"
                 and o.get("original_value")),
                None)
            if mechanic:
                self.set_early_facts(procurement_mechanic=mechanic)
            if data.get("requirements"):
                self.mark(MILESTONE_PROCUREMENT_STRUCTURE_READY)
                self.mark(MILESTONE_QUALIFICATION_READY)
            self._eval_task_done()
        elif route == ROUTE_EVAL_ONLY:
            self._eval_task_done()
        elif route == ROUTE_COMMERCIAL_ONLY:
            self._commercial_task_done()


class _NullProgressTracker:
    """Final-acceptance hardening: used only if _ProgressTracker itself
    fails to CONSTRUCT (e.g. a future bug in _compute_eval_tasks_total
    against malformed document text) -- every method it needs to stand in
    for is a no-op, so the analysis proceeds with zero progress reporting
    rather than the run being marked FAILED over a progress-tracking bug.
    _ProgressTracker's own methods are already individually defensive
    (instruction: 'never fails the underlying analysis'); this closes the
    one remaining gap, construction itself, which happens outside any of
    those methods."""

    def mark(self, milestone: str) -> None:
        pass

    def mark_vacuous_milestones(self) -> None:
        pass

    def set_early_facts(self, **facts) -> None:
        pass

    def on_task_done(self, kind: str, payload, task_result) -> None:
        pass


class DuplicateAnalysisRunError(RuntimeError):
    """Raised when a non-terminal run already exists for this bid+mode.
    Callers should surface the existing run's status instead of retrying
    (instruction 7)."""

    def __init__(self, existing_run: dict):
        self.existing_run = existing_run
        super().__init__(
            f"analysis run {existing_run.get('id')} is already "
            f"{existing_run.get('status')} for this bid/mode")


class NoCorpusError(ValueError):
    """Raised when a bid has no 'RFP / Source' documents attached yet."""


def _corpus_snapshot(documents: list[dict]) -> tuple[list[dict], str]:
    """A stable, ordered snapshot of exactly which persisted documents (by
    id and the version they were at) belong to this run, plus a combined
    digest -- instruction 8. A later file add/replace does not retroactively
    change what an already-created run is attributed to; it would require a
    new run."""
    ids = sorted(
        ({"document_id": d["id"], "version": d.get("version", 1), "name": d["name"]}
         for d in documents),
        key=lambda x: x["document_id"])
    digest_input = "|".join(f"{d['document_id']}:{d['version']}" for d in ids).encode("utf-8")
    return ids, hashlib.sha256(digest_input).hexdigest()


def _telemetry_summary(result: FastAnalysisResult) -> dict:
    """Compact, application-level telemetry (instruction 22) -- never
    exposed in the client-facing report, available for operational
    diagnostics. Individual per-call detail is not persisted here; the
    per-call shape lives only in the in-memory result.telemetry list for
    the duration of the run.

    Phase 5E: delegates the call-taxonomy computation to fast_analysis's
    _telemetry_audit_summary (single source of truth) instead of keeping
    its own separate, independently-buggy copy of the same counting
    logic -- adds only the fields specific to this application layer
    (engine_version, documents_skipped/batched, cost_note)."""
    base = _telemetry_audit_summary(result.telemetry, result.wall_seconds)
    return {
        "engine_version": FAST_ANALYSIS_ENGINE_VERSION,
        **base,
        "documents_skipped": len(result.skipped_documents),
        "documents_batched": len(result.batched_documents),
        # Provider-reported cost is not exposed by the current Anthropic API
        # response objects this codebase reads -- token counts are reported
        # instead of an invented dollar figure (instruction 23).
        "cost_note": "token counts only; no reliable per-call cost figure is available from the provider response",
    }


def start_fast_analysis(bid_id: int, api_key: str, created_by: str | None = None) -> dict:
    """Create a durable analysis run and begin executing it in a background
    thread. Returns the created analysis_runs row (status=QUEUED).

    Raises DuplicateAnalysisRunError if a non-terminal FAST run already
    exists for this bid, and NoCorpusError if no 'RFP / Source' documents
    are attached yet. Both are checked before any API spend."""
    existing = db.get_active_analysis_run(bid_id, "FAST")
    if existing:
        raise DuplicateAnalysisRunError(existing)

    docs = [d for d in db.get_documents(bid_id) if d.get("doc_type") == "RFP / Source"]
    if not docs:
        raise NoCorpusError("no 'RFP / Source' documents are attached to this bid yet")

    corpus_ids, corpus_digest = _corpus_snapshot(docs)
    run = db.create_analysis_run(bid_id, "FAST", FAST_ANALYSIS_ENGINE_VERSION,
                                 corpus_ids, corpus_digest, created_by)
    if run is None:
        # Lost a race against a concurrent request between the check above
        # and the insert. The DB-level partial unique index
        # (idx_analysis_runs_one_active) is the real, atomic guard; the
        # pre-check above is only a fast, friendly path for the common case.
        existing = db.get_active_analysis_run(bid_id, "FAST")
        raise DuplicateAnalysisRunError(existing or {"id": "?", "status": "IN_PROGRESS"})

    thread = threading.Thread(
        target=_execute_fast_analysis_run,
        args=(run["id"], bid_id, docs, api_key),
        daemon=True, name=f"fast-analysis-run-{run['id']}",
    )
    thread.start()
    return run


def _execute_fast_analysis_run(run_id: int, bid_id: int, docs: list[dict], api_key: str) -> None:
    """Runs in a background thread. Every exception is caught and persisted
    as a FAILED run with diagnostic detail (instruction 19) -- this
    function must never leave a run stuck QUEUED/ANALYZING forever, and
    must never mark a run COMPLETE from partial data."""
    try:
        db.update_analysis_run(run_id, {
            "status": "PREPARING",
            "started_at": datetime.now(timezone.utc).isoformat(),
        })

        documents: list[tuple[str, str]] = []
        for d in docs:
            storage_path = d.get("storage_path")
            if not storage_path:
                raise RuntimeError(f"document '{d.get('name')}' has no storage_path; cannot analyze")
            file_bytes = db.download_file(storage_path)
            if not file_bytes:
                raise RuntimeError(f"could not download document '{d.get('name')}' from storage")
            text, _ = extract_document_with_metadata(file_bytes, d["name"])
            documents.append((d["name"], text))

        # Hardening: constructing the tracker itself sits outside every
        # individually-defensive method on it, so it gets its own guard --
        # a bug here must fall back to no progress reporting, never fail
        # the run (same promise _ProgressTracker's own methods already keep).
        try:
            progress = _ProgressTracker(run_id, documents)
            progress.mark(MILESTONE_CORPUS_PREPARED)
            progress.mark_vacuous_milestones()
        except Exception:
            progress = _NullProgressTracker()

        db.update_analysis_run(run_id, {"status": "ANALYZING"})
        # Frozen V4 engine call -- unmodified signature, unmodified behavior.
        # on_task_done is a purely observational Phase 2 hook (see
        # fast_analysis.py's docstring for that parameter) -- it does not
        # change what is extracted, routed, chunked, or how many calls are
        # made.
        result: FastAnalysisResult = run_fast_analysis_corpus(
            documents, api_key, max_document_concurrency=MAX_DOCUMENT_CONCURRENCY,
            on_task_done=progress.on_task_done)
        # Ambiguity detection (engine step 4) has already run, synchronously,
        # inside the call above by the time it returns -- this is a real
        # completion event, not a guess.
        progress.mark(MILESTONE_AMBIGUITIES_READY)

        # Phase 4 (BI Context & Token Optimization Program): bridge Fast
        # Analysis's own rich, already-complete per-call telemetry list
        # into durable, normalized model_usage_events rows -- once, here,
        # never at fast_analysis.py's own call sites (which never pass
        # telemetry_context), so a call already captured in result.telemetry
        # can never be double-counted. Wrapped so a telemetry-persistence
        # failure can never affect this run (see model_telemetry.py's
        # "failure policy").
        try:
            import model_telemetry
            model_telemetry.bridge_fast_analysis_telemetry(
                result.telemetry, bid_id=bid_id, analysis_run_id=run_id)
        except Exception:
            pass

        # Durability: serialize the raw analytical result BEFORE the lossy
        # structured_intelligence/report_content transformation below, so a
        # future report-layout revision or acceptance run can regenerate
        # this run's PDF from durable storage with zero LLM calls, even
        # after today's adapter logic changes (see
        # fast_analysis.serialize_fast_analysis_result and
        # regenerate_report_from_raw_snapshot below).
        raw_snapshot = serialize_fast_analysis_result(result, engine_version=FAST_ANALYSIS_ENGINE_VERSION)

        db.update_analysis_run(run_id, {"status": "ASSEMBLING"})
        opportunity_intelligence = build_opportunity_intelligence(result)

        content = build_fast_report_content(result)
        pdf_bytes = _render_pdf_bytes(content)
        report_storage_path = db.upload_analysis_report(bid_id, run_id, pdf_bytes)
        progress.mark(MILESTONE_REPORT_ASSEMBLED)

        created_result = db.create_analysis_result(
            run_id, bid_id, opportunity_intelligence,
            opportunity_intelligence.get("fact_origins"),
            report_content_snapshot=_content_to_dict(content),
            fast_analysis_result_snapshot=raw_snapshot)

        # Fail closed (instruction 6): a run whose raw analytical snapshot
        # did not durably persist must not be marked COMPLETE -- a future
        # report regeneration or audit for it would otherwise be silently
        # lossy (or force re-running the LLM) with no visible sign anything
        # was ever wrong. This reuses the existing FAILED lifecycle path
        # (the except block below) rather than inventing a new state.
        if not created_result or not created_result.get("fast_analysis_result_snapshot"):
            raise RuntimeError(
                "failed to durably persist the raw Fast Analysis snapshot for "
                "this run; refusing to mark it COMPLETE")

        # Fast Analysis is advisory-only (Procurement Revision & Addendum
        # Governance, migration 010): it renders exclusively from its own
        # analysis_results.structured_intelligence and NEVER writes
        # bid_briefs -- canonical procurement truth is established only
        # through a governed baseline/buyer-update review and apply. The
        # run is instead stamped with the procurement revision it ran
        # against and how many of its corpus documents have not yet gone
        # through a governed review, so the UI can flag it as advisory
        # and potentially stale relative to canonical truth.
        procurement_state = db.get_bid_procurement_state(bid_id)
        reviewed_hashes = db.get_reviewed_document_hashes(bid_id)
        unreviewed_document_count = sum(
            1 for d in docs if (d["id"], d.get("content_hash")) not in reviewed_hashes
        )

        db.update_analysis_run(run_id, {
            "status": "COMPLETE",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "telemetry": _telemetry_summary(result),
            "report_storage_path": report_storage_path,
            "based_on_procurement_revision": procurement_state["procurement_revision"],
            "unreviewed_document_count": unreviewed_document_count,
        })
    except Exception as exc:
        db.update_analysis_run(run_id, {
            "status": "FAILED",
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "failure_reason": str(exc)[:500],
            "failure_detail": {"traceback": traceback.format_exc()[-4000:]},
        })


def _content_to_dict(content) -> dict:
    """A JSON-safe dict snapshot of the report-content SimpleNamespace --
    every attribute build_fast_report_content() sets is already a plain
    str/list/dict/tuple, so this is a direct, lossless conversion."""
    return dict(vars(content))


def _dict_to_content(data: dict):
    """Inverse of _content_to_dict -- rebuild the SimpleNamespace the PDF
    renderer expects directly from a persisted snapshot."""
    from types import SimpleNamespace
    return SimpleNamespace(**data)


def _render_pdf_bytes(content) -> bytes:
    """Render the report PDF to bytes via a temp file -- the shared
    renderer (scripts/build_boc_bid_intelligence_preview_pdf.build) writes
    to a filesystem path; this wraps that for in-memory upload."""
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "report.pdf"
        _render_pdf(content=content, out_path=out_path)
        return out_path.read_bytes()


def regenerate_report(run_id: int) -> bytes:
    """Rebuild the report PDF from a COMPLETE run's already-persisted
    report_content_snapshot -- zero extraction calls, zero re-derivation
    through the report adapter (instruction 16/17). Raises if the run isn't
    COMPLETE or has no persisted snapshot."""
    run = db.get_analysis_run(run_id)
    if not run or run.get("status") != "COMPLETE":
        raise ValueError(f"analysis run {run_id} is not COMPLETE; cannot regenerate its report")
    stored = db.get_analysis_result(run_id)
    if not stored or not stored.get("report_content_snapshot"):
        raise ValueError(f"analysis run {run_id} has no persisted report content snapshot")

    content = _dict_to_content(stored["report_content_snapshot"])
    return _render_pdf_bytes(content)


def load_raw_fast_analysis_result(run_id: int):
    """Returns a reconstructed FastAnalysisResult if a compatible raw
    snapshot is durably persisted for this run (see
    fast_analysis.serialize_fast_analysis_result /
    migrations/012_fast_analysis_result_snapshot.sql), or the sentinel
    string RAW_FAST_ANALYSIS_SNAPSHOT_UNAVAILABLE if none exists at all --
    e.g. any run created before that column existed, such as Phoenix run
    13. Never fabricated, never silently reconstructed from
    structured_intelligence/report_content_snapshot (those use a
    different, lossy, downstream schema).

    A snapshot that IS present but uses an incompatible schema version
    raises fast_analysis.RawSnapshotSchemaError (fail closed) rather than
    being treated the same as "absent" -- those are different failure
    modes and callers must not conflate them."""
    stored = db.get_analysis_result(run_id)
    if not stored or not stored.get("fast_analysis_result_snapshot"):
        return RAW_FAST_ANALYSIS_SNAPSHOT_UNAVAILABLE
    return deserialize_fast_analysis_result(stored["fast_analysis_result_snapshot"])


def regenerate_report_from_raw_snapshot(run_id: int, buyer_intelligence: dict | None = None) -> bytes:
    """Deterministic, zero-LLM-call report regeneration from a durably
    persisted raw FastAnalysisResult snapshot: load -> deserialize ->
    optionally attach/override a Buyer Intelligence payload ->
    build_fast_report_content -> render PDF, using the exact same adapter
    and renderer a live run uses. This is the path for future report-layout
    revisions and acceptance testing -- it never reruns analysis, even when
    a valid, compatible snapshot exists.

    `buyer_intelligence`, when given, overrides whatever the snapshot's own
    `buyer_intelligence` field holds (which may be None -- the live app-UI
    run path does not currently attach one; only the standalone acceptance
    script does, as an external enrichment layer). When omitted, whatever
    was already embedded in the snapshot at serialization time is used
    as-is.

    Raises ValueError if the run isn't COMPLETE or has no durably persisted
    raw snapshot (message includes RAW_FAST_ANALYSIS_SNAPSHOT_UNAVAILABLE).
    Raises fast_analysis.RawSnapshotSchemaError if a snapshot IS present
    but incompatible (fail closed) -- never silently substitutes a
    reconstruction from structured_intelligence/report_content_snapshot."""
    run = db.get_analysis_run(run_id)
    if not run or run.get("status") != "COMPLETE":
        raise ValueError(f"analysis run {run_id} is not COMPLETE; cannot regenerate its report")

    result = load_raw_fast_analysis_result(run_id)
    if isinstance(result, str):
        raise ValueError(
            f"analysis run {run_id} has no durably persisted raw Fast Analysis "
            f"snapshot ({result})")

    if buyer_intelligence is not None:
        result.buyer_intelligence = buyer_intelligence

    content = build_fast_report_content(result)
    return _render_pdf_bytes(content)


# ---------------------------------------------------------------------------
# MA-1: Full Analysis (bounded specialist multi-agent analysis).
#
# DELIBERATELY SEPARATE from Fast Analysis (task section 17). Fast Analysis
# above is unchanged: it does not call any of this, it does not dispatch
# specialist work, and no ingestion path reaches here. Full Analysis is an
# EXPLICIT action a caller takes against an already-COMPLETE Fast Analysis
# run, whose durable raw snapshot IS the canonical package input.
#
# PERSISTENCE (task section 16): MA-1 is compute-and-return. The existing
# analysis_runs/analysis_results architecture was inspected first and is a
# good future home, but analysis_runs.analysis_mode is constrained by
# migrations/004_analysis_runs.sql to ('FAST','DEEP_VERIFY') and
# analysis_results has no Full Analysis column -- persisting a FULL run
# therefore requires schema work, which MA-1 does not perform. The gap is
# reported explicitly rather than worked around by writing a Full Analysis
# result into a column that means something else.
# ---------------------------------------------------------------------------

FULL_ANALYSIS_PERSISTENCE_GAP = (
    "MA-1's run_full_analysis_for_run is compute-and-return. MA-2A adds the "
    "durable path: full_analysis_service.start_full_analysis (analysis_mode "
    "'FULL', migrations/020_full_analysis_runs.sql -- written, NOT yet applied "
    "live). This compute-and-return entry point is kept for one-off smokes."
)


def run_full_analysis_for_run(run_id: int, api_key: str, *, include_documents: bool = True):
    """Run MA-1 Full Analysis against a COMPLETE Fast Analysis run's durable
    canonical snapshot. Returns a `full_analysis.FullAnalysisResult`.

    Makes exactly six specialist provider calls plus one reconciliation
    call. Performs NO extraction: the canonical package is built from the
    already-persisted raw Fast Analysis snapshot (and, for a snapshot that
    predates a CI-1.1 canonical field, from the corpus text only to
    re-derive that frozen Layer-2 field deterministically -- the
    specialists themselves never receive document text).

    Nothing is persisted (see FULL_ANALYSIS_PERSISTENCE_GAP)."""
    import full_analysis

    package = build_full_analysis_package(run_id, include_documents=include_documents)
    return full_analysis.run_full_analysis(package, api_key)


def build_full_analysis_package(run_id: int, *, include_documents: bool = True,
                                documents_only_if_needed: bool = False):
    """The ONE canonical-package assembly path for Full Analysis (MA-1's
    compute-and-return entry point above and MA-2A's durable service both
    use it). Deterministic, zero model calls. Raises ValueError if run_id
    is not a COMPLETE FAST run with a durable raw snapshot.

    `documents_only_if_needed` (MA-2A): corpus text is only ever used by
    build_canonical_package to re-derive CI-1.1 `category_scope_items` for
    a snapshot that predates that field -- when the snapshot already has
    it, downloading/extracting every source document is skipped, which
    keeps a freshness check cheap."""
    import full_analysis

    run = db.get_analysis_run(run_id)
    if not run or run.get("status") != "COMPLETE" or run.get("analysis_mode", "FAST") != "FAST":
        raise ValueError(f"analysis run {run_id} is not a COMPLETE FAST run; cannot run Full Analysis")
    result = load_raw_fast_analysis_result(run_id)
    if isinstance(result, str):
        raise ValueError(
            f"analysis run {run_id} has no durably persisted raw Fast Analysis snapshot ({result})")

    bid_id = run.get("bid_id")
    if documents_only_if_needed and getattr(result, "category_scope_items", None):
        include_documents = False
    documents: list[tuple[str, str]] | None = None
    if include_documents:
        documents = []
        for d in db.get_documents(bid_id):
            if d.get("doc_type") != "RFP / Source" or not d.get("storage_path"):
                continue
            file_bytes = db.download_file(d["storage_path"])
            if not file_bytes:
                continue
            text, _ = extract_document_with_metadata(file_bytes, d["name"])
            documents.append((d["name"], text))

    return full_analysis.build_canonical_package(
        result, bid_id=bid_id, analysis_run_id=run_id, documents=documents)


def _parse_timestamp(value: str | None):
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except Exception:
        return None


def is_run_stuck(run: dict) -> bool:
    """A run is 'possibly stuck' if it is still in a non-terminal status
    and has been running (or queued) for longer than
    STUCK_RUN_THRESHOLD_SECONDS -- the expected signature of a background
    thread that died with its process (S8/known limitation 1 in the Phase 1
    report), not a merely slow run. Pure, no side effects -- callers decide
    whether/when to offer the mark-as-failed action."""
    if not run or run.get("status") not in _NON_TERMINAL_STATES:
        return False
    reference = _parse_timestamp(run.get("started_at")) or _parse_timestamp(run.get("created_at"))
    if reference is None:
        return False
    elapsed = (datetime.now(timezone.utc) - reference).total_seconds()
    return elapsed > STUCK_RUN_THRESHOLD_SECONDS


def mark_run_failed_as_stuck(run_id: int) -> None:
    """Bounded, deliberate, user-initiated action (instruction 20) -- never
    called automatically. Marks a run FAILED with a distinct, honest
    failure_reason rather than silently retrying or leaving it stranded.
    The user can then use the normal FAILED-state 'Retry' action, which
    creates a genuinely new run (the stuck one's own thread, if it somehow
    still completes later, writes to a run_id no UI path is watching
    anymore, so it cannot clobber the retry)."""
    run = db.get_analysis_run(run_id)
    if not run or run.get("status") not in _NON_TERMINAL_STATES:
        raise ValueError(f"analysis run {run_id} is not in a non-terminal state; nothing to mark")
    db.update_analysis_run(run_id, {
        "status": "FAILED",
        "failed_at": datetime.now(timezone.utc).isoformat(),
        "failure_reason": (
            f"Marked failed by user action: exceeded {STUCK_RUN_THRESHOLD_SECONDS}s "
            f"without completing (possible process restart or crash of the background thread)."
        ),
        "failure_detail": {"marked_stuck_by_user": True, "prior_status": run.get("status")},
    })
