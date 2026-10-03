"""
full_analysis_service.py -- MA-2A: Durable Full Analysis runs & progress events.

The ONE canonical orchestration boundary for Full Analysis. A future UI
(MA-2B) must call this module -- via tenancy.py's `*_for_organization`
wrappers -- and never full_analysis.py directly.

    start_full_analysis(...)       freshness lookup -> idempotent run
                                   get-or-create -> (background) execution
    get_full_analysis_status(...)  durable run state + ordered event log +
                                   per-specialist state + stuck detection
    get_full_analysis_result(...)  the persisted FullAnalysisResult
    mark_full_analysis_run_stuck(...)  explicit, user-initiated FAILED
                                   marking of a genuinely stuck run

It owns freshness, run creation, orchestration, progress recording,
persistence, status and retrieval. It does NOT duplicate any MA-1
specialist logic: the canonical package is assembled by
analysis_service.build_full_analysis_package (MA-1's own path) and the
analysis itself is full_analysis.run_full_analysis, observed through its
`on_event` hook, which fires only at real execution boundaries.

Persistence reuses analysis_runs / analysis_results (analysis_mode='FULL')
plus migration 020's append-only full_analysis_events and
full_analysis_specialist_results. Every write is one of migration 020's
three service_role-only RPCs (database.start_full_analysis_run /
record_full_analysis_event / finalize_full_analysis_run).

Background execution -- honest statement of what the runtime supports:
this repository has no job queue (no Celery/RQ/APScheduler/worker
process). Its established long-running pattern (analysis_service.
start_fast_analysis) is an in-process daemon thread inside the long-lived
Streamlit server process, which outlives the triggering request/rerun. MA-2A
reuses exactly that pattern (execution="background") and adds what makes it
safe to rely on: the run and every execution event are durable BEFORE and
AS work happens (each specialist's validated result is persisted the moment
it finishes), so a browser refresh loses nothing, and a process death
mid-run leaves a visibly non-terminal run whose finished specialists are
still durable, which `is_full_run_stuck` detects from last_progress_at and
which a user can explicitly mark FAILED and explicitly retry. The thread is
NOT resilient to a process restart and nothing here pretends otherwise;
execution="inline" runs the same code synchronously for callers (scripts,
tests) that want to block.
"""
from __future__ import annotations

import threading
import traceback
from datetime import datetime, timezone

import database as db
import full_analysis as fa

#: Engine identifier persisted on analysis_runs.engine_version for FULL runs.
FULL_ANALYSIS_ENGINE_VERSION = (
    f"full-analysis-{fa.FULL_ANALYSIS_VERSION}"
    f"/specialist-{fa.SPECIALIST_VERSION}/reconciliation-{fa.RECONCILIATION_VERSION}")

MODE_FULL = "FULL"

# Run statuses (analysis_runs.status for analysis_mode='FULL').
RUN_QUEUED = "QUEUED"
RUN_RUNNING = "RUNNING"
RUN_COMPLETE = "COMPLETE"
RUN_PARTIAL = "PARTIAL"
RUN_FAILED = "FAILED"
RUN_STATUSES = (RUN_QUEUED, RUN_RUNNING, RUN_COMPLETE, RUN_PARTIAL, RUN_FAILED)
TERMINAL_RUN_STATUSES = (RUN_COMPLETE, RUN_PARTIAL, RUN_FAILED)

# Closed specialist / reconciliation state vocabulary.
SPEC_QUEUED = "QUEUED"
SPEC_RUNNING = "RUNNING"
SPEC_COMPLETE = "COMPLETE"
#: MA-2A.2: finished with usable output that the provider truncated at the
#: output-token ceiling (stop_reason=max_tokens). Never shown as COMPLETE.
SPEC_PARTIAL = "PARTIAL"
SPEC_FAILED = "FAILED"
SPEC_SKIPPED = "SKIPPED"
SPECIALIST_STATUSES = (SPEC_QUEUED, SPEC_RUNNING, SPEC_COMPLETE, SPEC_PARTIAL, SPEC_FAILED,
                       SPEC_SKIPPED)
_FINISHED_SPEC_STATUSES = (SPEC_COMPLETE, SPEC_PARTIAL, SPEC_FAILED)

# Event vocabulary (mirrors migration 020's CHECK constraint exactly).
EVENT_RUN_CREATED = "RUN_CREATED"
EVENT_CANONICAL_PACKAGE_READY = "CANONICAL_PACKAGE_READY"
EVENT_RUN_COMPLETED = "RUN_COMPLETED"
EVENT_RUN_PARTIAL = "RUN_PARTIAL"
EVENT_RUN_FAILED = "RUN_FAILED"
EVENT_TYPES = (
    EVENT_RUN_CREATED, EVENT_CANONICAL_PACKAGE_READY,
    fa.EVENT_SPECIALIST_QUEUED, fa.EVENT_SPECIALIST_STARTED,
    fa.EVENT_SPECIALIST_COMPLETED, fa.EVENT_SPECIALIST_FAILED,
    fa.EVENT_RECONCILIATION_STARTED, fa.EVENT_RECONCILIATION_COMPLETED,
    fa.EVENT_RECONCILIATION_FAILED,
    EVENT_RUN_COMPLETED, EVENT_RUN_PARTIAL, EVENT_RUN_FAILED,
)

# Start outcomes (returned by migration 020's start_full_analysis_run RPC).
OUTCOME_CREATED = "CREATED"
OUTCOME_ACTIVE_RUN_EXISTS = "ACTIVE_RUN_EXISTS"
OUTCOME_REUSED_COMPLETE = "REUSED_COMPLETE"
OUTCOME_EXISTING_FAILED = "EXISTING_FAILED"
OUTCOME_EXISTING_PARTIAL = "EXISTING_PARTIAL"

# Stuck-run semantics. A real Bank of Canada run is ~90s end to end and a
# single bounded specialist call is well under two minutes, so a run with
# no durable progress for 10 minutes -- or alive for 30 -- is not merely
# slow. Detection only: nothing here ever auto-fails or auto-relaunches.
STUCK_NO_PROGRESS_SECONDS = 10 * 60
STUCK_MAX_RUN_AGE_SECONDS = 30 * 60

EXECUTION_BACKGROUND = "background"
EXECUTION_INLINE = "inline"


class FullAnalysisError(RuntimeError):
    """Base error for this service."""


class NoCompleteFastAnalysisError(FullAnalysisError):
    """No COMPLETE Fast Analysis run exists to build the canonical package from."""


class FullAnalysisBaselineRequiredError(FullAnalysisError):
    """A prior COMPLETE Full Analysis run is required for incremental revision execution."""


class RevisionNotCurrentError(FullAnalysisError):
    """The requested revision is not the latest applied revision (Requirement 1: REVISION_NOT_CURRENT)."""


class RunNotFoundError(FullAnalysisError):
    """The requested FULL run does not exist for this bid."""


class RunNotStuckError(FullAnalysisError):
    """mark_full_analysis_run_stuck was called on a run that is not stuck."""


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _resolve_source_run(bid_id: int, source_run_id: int | None) -> dict:
    """The COMPLETE FAST run whose raw snapshot is the canonical input."""
    if source_run_id is not None:
        run = db.get_analysis_run(source_run_id)
        if (not run or int(run.get("bid_id")) != int(bid_id)
                or run.get("analysis_mode", "FAST") != "FAST" or run.get("status") != "COMPLETE"):
            raise NoCompleteFastAnalysisError(
                f"analysis run {source_run_id} is not a COMPLETE Fast Analysis run of bid {bid_id}")
        return run
    for run in db.list_analysis_runs(bid_id):
        if run.get("analysis_mode", "FAST") == "FAST" and run.get("status") == "COMPLETE":
            return run
    raise NoCompleteFastAnalysisError(f"bid {bid_id} has no COMPLETE Fast Analysis run")


def _default_package_builder(source_run_id: int):
    import analysis_service
    return analysis_service.build_full_analysis_package(
        source_run_id, include_documents=True, documents_only_if_needed=True)


def _package_detail(package, fingerprint: str) -> dict:
    """Bounded execution metadata for CANONICAL_PACKAGE_READY: digests and
    object counts only -- never canonical content."""
    return {
        "canonical_snapshot_digest": package.package_digest,
        "canonical_content_digest": fa.canonical_content_digest(package),
        "input_fingerprint": fingerprint,
        "object_counts": {t: len(package.objects_of_type(t)) for t in fa.CANONICAL_OBJECT_TYPES},
    }


def _specialist_result_payload(result) -> dict:
    """SpecialistResult for durable storage: validated structured output
    only (findings reference canonical ids; no canonical package copy, no
    prompt, no raw model text)."""
    return result.as_dict()


def _specialist_event_detail(result) -> dict:
    usage = result.usage or {}
    return {
        "specialist_version": result.specialist_version,
        "input_digest": result.input_digest,
        "finding_count": len(result.findings),
        "rejected_finding_count": len(result.rejected_findings),
        "confidence": result.confidence,
        "stop_reason": getattr(result, "stop_reason", None),
        "parse_status": getattr(result, "parse_status", None),
        "output_truncated": bool(getattr(result, "output_truncated", False)),
        "calls": usage.get("calls", 0),
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "model": usage.get("model"),
    }


def _result_payload(result, *, run_id: int, source_run_id: int, fingerprint: str,
                    fingerprint_inputs: dict) -> dict:
    """The persisted FullAnalysisResult. Raw per-call telemetry rows are
    dropped (they duplicate model_usage_events and the usage summary);
    everything MA-1 produced analytically is kept."""
    payload = result.as_dict()
    payload.pop("telemetry", None)
    payload["full_analysis_run_id"] = run_id
    payload["source_analysis_run_id"] = source_run_id
    payload["input_fingerprint"] = fingerprint
    payload["fingerprint_inputs"] = fingerprint_inputs
    payload["architecture_version"] = fa.FULL_ANALYSIS_VERSION
    payload["specialist_versions"] = {sid: fa.SPECIALIST_VERSION for sid in fa.SPECIALIST_IDS}
    payload["reconciliation_version"] = fa.RECONCILIATION_VERSION
    return payload


def _result_summary(result) -> dict:
    return {
        "analysis_mode": MODE_FULL,
        "completeness_status": result.completeness_status,
        "specialist_statuses": dict(result.specialist_statuses),
        "reconciliation_status": (result.reconciliation or {}).get("status"),
        "truncated_stages": _truncated_stages(result),
        "reconciled_finding_count": len(result.reconciled_findings),
        "unresolved_gap_count": len(result.unresolved_gaps),
        "cross_domain_risk_count": len(result.cross_domain_risks),
        "ambiguity_count": len(result.ambiguities),
        "human_confirmation_count": len(result.human_confirmation_required),
    }


def _truncated_stages(result) -> list:
    """Stages whose provider call ended with stop_reason=max_tokens."""
    out = [s.get("specialist_id") for s in (result.specialist_results or [])
           if s.get("output_truncated")]
    if (result.reconciliation or {}).get("output_truncated"):
        out.append("RECONCILIATION")
    return out


def effective_specialist_status(row: dict) -> str | None:
    """MA-2A.2 read-side status of a persisted full_analysis_specialist_results
    row. Migration 020's `status` column only allows COMPLETE/FAILED/SKIPPED
    and its RPC writes COMPLETE for every SPECIALIST_COMPLETED event, so a
    truncated specialist's column reads COMPLETE ("finished with a result").
    The authoritative completion-integrity state is the SpecialistResult's
    own `status` inside the persisted `result` JSON (PARTIAL when truncated),
    which is what this returns. Pre-MA-2A.2 rows carry no such distinction
    and are returned unchanged (historical immutability)."""
    payload = row.get("result") or {}
    inner = payload.get("status") if isinstance(payload, dict) else None
    if inner in (SPEC_COMPLETE, SPEC_PARTIAL, SPEC_FAILED):
        return inner
    return row.get("status")


def _telemetry_summary(result) -> dict:
    usage = dict(result.usage or {})
    return {
        "engine_version": FULL_ANALYSIS_ENGINE_VERSION,
        "model": usage.get("model"),
        "provider_calls": usage.get("total_calls", 0),
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "request_bytes": usage.get("request_bytes", 0),
        "wall_seconds": result.wall_seconds,
        "by_specialist": usage.get("by_specialist", {}),
        "reconciliation": usage.get("reconciliation", {}),
        "truncated_stages": _truncated_stages(result),
        "per_call_rows": "model_usage_events (workflow='full_analysis', analysis_run_id=<this run>)",
    }


def _terminal_status_for(completeness: str) -> str:
    if completeness == fa.COMPLETENESS_COMPLETE:
        return RUN_COMPLETE
    if completeness == fa.COMPLETENESS_PARTIAL:
        return RUN_PARTIAL
    return RUN_FAILED


# ═══════════════════════════════════════════════════════════════════════
# Execution (runs inline or in the background thread)
# ═══════════════════════════════════════════════════════════════════════

class _EventRecorder:
    """Translates full_analysis.run_full_analysis's real execution events
    into durable, sequenced full_analysis_events rows. Called from worker
    threads concurrently: a local lock serializes the writes (the RPC's
    per-run advisory lock is the durable authority on sequence order).

    If a write is refused because the run became terminal underneath us
    (e.g. a user marked it stuck/FAILED), `aborted` is set and nothing
    further is written -- a late thread can never resurrect or overwrite a
    terminal run."""

    _STATUS_FOR = {
        fa.EVENT_SPECIALIST_QUEUED: SPEC_QUEUED,
        fa.EVENT_SPECIALIST_STARTED: SPEC_RUNNING,
        fa.EVENT_SPECIALIST_COMPLETED: SPEC_COMPLETE,
        fa.EVENT_SPECIALIST_FAILED: SPEC_FAILED,
        fa.EVENT_RECONCILIATION_STARTED: SPEC_RUNNING,
        fa.EVENT_RECONCILIATION_COMPLETED: SPEC_COMPLETE,
        fa.EVENT_RECONCILIATION_FAILED: SPEC_FAILED,
    }

    def __init__(self, run_id: int, bid_id: int):
        self.run_id = run_id
        self.bid_id = bid_id
        self.aborted = False
        self.write_errors: list[str] = []
        self._lock = threading.Lock()

    def record(self, event_type: str, **kwargs) -> None:
        with self._lock:
            if self.aborted:
                return
            try:
                db.record_full_analysis_event(self.run_id, self.bid_id, event_type, **kwargs)
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                self.write_errors.append(message[:300])
                if "terminal" in message.lower() or "not a full run" in message.lower():
                    self.aborted = True

    def __call__(self, event_type: str, payload: dict) -> None:
        status = self._STATUS_FOR.get(event_type)
        if event_type in (fa.EVENT_SPECIALIST_COMPLETED, fa.EVENT_SPECIALIST_FAILED):
            result = payload["result"]
            if event_type == fa.EVENT_SPECIALIST_COMPLETED and result.status == fa.STATUS_PARTIAL:
                status = SPEC_PARTIAL  # truthful: finished, but output truncated
            self.record(event_type, specialist_id=result.specialist_id, status=status,
                        duration_seconds=result.duration_seconds,
                        failure_summary=result.failure_reason,
                        detail=_specialist_event_detail(result),
                        specialist_result=_specialist_result_payload(result))
        elif event_type in (fa.EVENT_SPECIALIST_QUEUED, fa.EVENT_SPECIALIST_STARTED):
            self.record(event_type, specialist_id=payload["specialist_id"], status=status)
        elif event_type == fa.EVENT_RECONCILIATION_STARTED:
            self.record(event_type, status=status,
                        detail={"incomplete_domains": list(payload.get("incomplete_domains") or [])})
        elif event_type in (fa.EVENT_RECONCILIATION_COMPLETED, fa.EVENT_RECONCILIATION_FAILED):
            rec = payload["reconciliation"]
            if event_type == fa.EVENT_RECONCILIATION_COMPLETED and rec.status == fa.STATUS_PARTIAL:
                status = SPEC_PARTIAL
            self.record(event_type, status=status, duration_seconds=rec.duration_seconds,
                        failure_summary=rec.failure_reason,
                        detail={"reconciliation_version": rec.reconciliation_version,
                                "incomplete_domain_count": len(rec.incomplete_domains),
                                "cross_domain_risk_count": len(rec.cross_domain_risks),
                                "contradiction_count": len(rec.contradictions),
                                "reconciled_finding_count": len(rec.reconciled_findings),
                                "stop_reason": rec.stop_reason,
                                "parse_status": rec.parse_status,
                                "output_truncated": bool(rec.output_truncated),
                                "calls": (rec.usage or {}).get("calls", 0)})


def _execute_full_analysis_run(run: dict, package, *, fingerprint: str,
                               fingerprint_inputs: dict, api_key: str | None,
                               client=None) -> None:
    """Execute one already-created FULL run to a terminal state. Never
    raises: every failure is persisted as a FAILED run (with whatever
    specialist work already finished still durable in
    full_analysis_specialist_results)."""
    run_id, bid_id = int(run["id"]), int(run["bid_id"])
    source_run_id = int(run["source_analysis_run_id"])
    recorder = _EventRecorder(run_id, bid_id)
    try:
        recorder.record(EVENT_CANONICAL_PACKAGE_READY, status=RUN_RUNNING,
                        detail=_package_detail(package, fingerprint))
        if recorder.aborted:
            return
        telemetry_context = {
            "workflow": "full_analysis", "bid_id": bid_id, "analysis_run_id": run_id,
            "metadata": {"input_fingerprint": fingerprint[:16]},
        }
        result = fa.run_full_analysis(package, api_key, client=client,
                                      telemetry_context=telemetry_context,
                                      on_event=recorder)
        if recorder.aborted:
            return  # run was made terminal externally (e.g. marked stuck)
        status = _terminal_status_for(result.completeness_status)
        failure_reason = None
        if status == RUN_FAILED:
            failure_reason = "no specialist completed; Full Analysis failed"
        elif status == RUN_PARTIAL:
            incomplete = [sid + (" (output truncated)" if st == fa.STATUS_PARTIAL else "")
                          for sid, st in result.specialist_statuses.items()
                          if st != fa.STATUS_COMPLETE]
            rec_status = (result.reconciliation or {}).get("status")
            if rec_status != fa.STATUS_COMPLETE:
                incomplete.append("RECONCILIATION" + (" (output truncated)"
                                                      if rec_status == fa.STATUS_PARTIAL else ""))
            failure_reason = "incomplete domains: " + ", ".join(incomplete)
        db.finalize_full_analysis_run(
            run_id, bid_id, status,
            result=_result_payload(result, run_id=run_id, source_run_id=source_run_id,
                                   fingerprint=fingerprint,
                                   fingerprint_inputs=fingerprint_inputs),
            summary=_result_summary(result), failure_reason=failure_reason,
            telemetry=_telemetry_summary(result))
    except Exception as exc:
        if recorder.aborted:
            return
        try:
            db.finalize_full_analysis_run(
                run_id, bid_id, RUN_FAILED,
                failure_reason=f"{type(exc).__name__}: {exc}"[:500],
                failure_detail={"traceback": traceback.format_exc()[-4000:],
                                "event_write_errors": recorder.write_errors[-5:]})
        except Exception:
            # Already terminal (or DB unreachable): the run then remains
            # non-terminal and `is_full_run_stuck` will surface it.
            pass


# ═══════════════════════════════════════════════════════════════════════
# Public service API
# ═══════════════════════════════════════════════════════════════════════

def start_full_analysis(bid_id: int, api_key: str | None = None, *,
                        source_run_id: int | None = None,
                        created_by_user_id: str | None = None,
                        retry: bool = False,
                        execution: str = EXECUTION_BACKGROUND,
                        client=None,
                        package_builder=None) -> dict:
    """Start (or reuse) the canonical Full Analysis for a bid.

    Authorization is NOT performed here -- call it only through
    tenancy.start_full_analysis_for_organization (require_bid_access first).

    1. Resolve the source COMPLETE Fast Analysis run and build the frozen
       canonical package (deterministic, zero model calls).
    2. Compute the Full Analysis fingerprint.
    3. One idempotent, advisory-locked RPC decides: reuse an active run,
       reuse a fresh COMPLETE result, return an existing FAILED/PARTIAL
       result for this fingerprint (explicit `retry=True` required to spend
       again), or create exactly one new QUEUED run.
    4. Only for CREATED: execute (background thread by default).

    Returns {"outcome", "run", "input_fingerprint", "fingerprint_matches",
    "executing", "source_analysis_run_id"}. A reuse outcome makes ZERO
    provider calls."""
    if execution not in (EXECUTION_BACKGROUND, EXECUTION_INLINE):
        raise ValueError(f"unknown execution mode {execution!r}")
    source = _resolve_source_run(bid_id, source_run_id)
    builder = package_builder or _default_package_builder
    package = builder(int(source["id"]))
    fingerprint_inputs = fa.full_analysis_fingerprint_inputs(package)
    fingerprint = fa.compute_full_analysis_fingerprint(package)

    response = db.start_full_analysis_run(
        bid_id, int(source["id"]), fingerprint, FULL_ANALYSIS_ENGINE_VERSION,
        corpus_digest=source.get("corpus_digest"), created_by_user_id=created_by_user_id,
        retry=retry,
        detail={"source_analysis_run_id": int(source["id"]),
                "canonical_snapshot_digest": package.package_digest,
                "engine_version": FULL_ANALYSIS_ENGINE_VERSION})
    if not response or "outcome" not in response:
        raise FullAnalysisError("start_full_analysis_run returned no outcome")
    outcome, run = response["outcome"], response["run"]
    out = {
        "outcome": outcome,
        "run": run,
        "input_fingerprint": fingerprint,
        "fingerprint_matches": run.get("input_fingerprint") == fingerprint,
        "source_analysis_run_id": int(source["id"]),
        "executing": False,
    }
    if outcome != OUTCOME_CREATED:
        return out

    kwargs = dict(fingerprint=fingerprint, fingerprint_inputs=fingerprint_inputs,
                  api_key=api_key, client=client)
    if execution == EXECUTION_INLINE:
        _execute_full_analysis_run(run, package, **kwargs)
    else:
        thread = threading.Thread(target=_execute_full_analysis_run, args=(run, package),
                                  kwargs=kwargs, daemon=True,
                                  name=f"full-analysis-run-{run['id']}")
        thread.start()
        out["executing"] = True
    return out


def is_full_run_stuck(run: dict, *, now: datetime | None = None) -> dict:
    """Pure stuck detection. Returns {"stuck": bool, "reason": str|None,
    "seconds_since_progress": float|None, "run_age_seconds": float|None}.
    Only a non-terminal run can be stuck."""
    now = now or _now()
    created = _parse_ts(run.get("created_at"))
    progress = _parse_ts(run.get("last_progress_at")) or _parse_ts(run.get("started_at")) or created
    age = (now - created).total_seconds() if created else None
    idle = (now - progress).total_seconds() if progress else None
    info = {"stuck": False, "reason": None, "seconds_since_progress": idle,
            "run_age_seconds": age,
            "no_progress_threshold_seconds": STUCK_NO_PROGRESS_SECONDS,
            "max_run_age_seconds": STUCK_MAX_RUN_AGE_SECONDS}
    if run.get("status") in TERMINAL_RUN_STATUSES:
        return info
    if idle is not None and idle > STUCK_NO_PROGRESS_SECONDS:
        info.update(stuck=True, reason="NO_PROGRESS")
    elif age is not None and age > STUCK_MAX_RUN_AGE_SECONDS:
        info.update(stuck=True, reason="MAX_RUN_AGE_EXCEEDED")
    return info


def derive_execution_state(run: dict, events: list[dict]) -> dict:
    """Pure: per-specialist and reconciliation state from the ordered event
    log. The latest event for a specialist wins. For a TERMINAL run, a
    specialist with no COMPLETE/FAILED event is reported SKIPPED (it never
    ran to completion -- e.g. the run failed or was marked stuck before it
    started). A specialist with no event yet on a live run is None (not yet
    queued), never a fabricated state."""
    specialists = {sid: {"status": None, "queued_at": None, "started_at": None,
                         "finished_at": None, "duration_seconds": None,
                         "failure_summary": None, "detail": {}}
                   for sid in fa.SPECIALIST_IDS}
    reconciliation = {"status": None, "started_at": None, "finished_at": None,
                      "duration_seconds": None, "failure_summary": None, "detail": {}}
    for ev in sorted(events, key=lambda e: e.get("sequence") or 0):
        et, sid = ev.get("event_type"), ev.get("specialist_id")
        if sid in specialists:
            s = specialists[sid]
            if et == fa.EVENT_SPECIALIST_QUEUED:
                s["status"], s["queued_at"] = SPEC_QUEUED, ev.get("occurred_at")
            elif et == fa.EVENT_SPECIALIST_STARTED:
                s["status"], s["started_at"] = SPEC_RUNNING, ev.get("occurred_at")
            elif et in (fa.EVENT_SPECIALIST_COMPLETED, fa.EVENT_SPECIALIST_FAILED):
                if et == fa.EVENT_SPECIALIST_FAILED:
                    s["status"] = SPEC_FAILED
                else:
                    s["status"] = SPEC_PARTIAL if ev.get("status") == SPEC_PARTIAL else SPEC_COMPLETE
                s["finished_at"] = ev.get("occurred_at")
                s["duration_seconds"] = ev.get("duration_seconds")
                s["failure_summary"] = ev.get("failure_summary")
                s["detail"] = ev.get("detail") or {}
        elif et == fa.EVENT_RECONCILIATION_STARTED:
            reconciliation.update(status=SPEC_RUNNING, started_at=ev.get("occurred_at"),
                                  detail=ev.get("detail") or {})
        elif et in (fa.EVENT_RECONCILIATION_COMPLETED, fa.EVENT_RECONCILIATION_FAILED):
            reconciliation.update(
                status=(SPEC_FAILED if et == fa.EVENT_RECONCILIATION_FAILED
                        else SPEC_PARTIAL if ev.get("status") == SPEC_PARTIAL else SPEC_COMPLETE),
                finished_at=ev.get("occurred_at"), duration_seconds=ev.get("duration_seconds"),
                failure_summary=ev.get("failure_summary"), detail=ev.get("detail") or {})
    if run.get("status") in TERMINAL_RUN_STATUSES:
        for s in specialists.values():
            if s["status"] not in _FINISHED_SPEC_STATUSES:
                s["status"] = SPEC_SKIPPED
        if reconciliation["status"] not in _FINISHED_SPEC_STATUSES:
            reconciliation["status"] = SPEC_SKIPPED
    return {"specialists": specialists, "reconciliation": reconciliation}


def _get_full_run(bid_id: int, run_id: int | None) -> dict | None:
    if run_id is None:
        runs = db.get_full_analysis_runs(bid_id, limit=1)
        return runs[0] if runs else None
    run = db.get_analysis_run(run_id)
    if not run or int(run.get("bid_id")) != int(bid_id) or run.get("analysis_mode") != MODE_FULL:
        raise RunNotFoundError(f"FULL run {run_id} does not exist for bid {bid_id}")
    return run


def get_full_analysis_status(bid_id: int, run_id: int | None = None, *,
                             after_sequence: int = 0, now: datetime | None = None) -> dict | None:
    """Durable, refresh-safe execution state for one FULL run (default: the
    bid's latest). Reads only persisted rows -- never calls a model, never
    starts work. `after_sequence` returns only newer events for
    incremental polling; the derived specialist state always reflects the
    FULL log. Returns None if the bid has no FULL run."""
    run = _get_full_run(bid_id, run_id)
    if run is None:
        return None
    all_events = db.get_full_analysis_events(int(run["id"]))
    state = derive_execution_state(run, all_events)
    stuck = is_full_run_stuck(run, now=now)
    return {
        "run_id": run["id"],
        "bid_id": run["bid_id"],
        "analysis_mode": MODE_FULL,
        "status": run.get("status"),
        "is_terminal": run.get("status") in TERMINAL_RUN_STATUSES,
        "input_fingerprint": run.get("input_fingerprint"),
        "source_analysis_run_id": run.get("source_analysis_run_id"),
        "engine_version": run.get("engine_version"),
        "created_at": run.get("created_at"),
        "started_at": run.get("started_at"),
        "completed_at": run.get("completed_at"),
        "failed_at": run.get("failed_at"),
        "last_progress_at": run.get("last_progress_at"),
        "failure_reason": run.get("failure_reason"),
        "stuck": stuck,
        "specialists": state["specialists"],
        "reconciliation": state["reconciliation"],
        "last_sequence": max((e.get("sequence") or 0 for e in all_events), default=0),
        "events": [e for e in all_events if (e.get("sequence") or 0) > after_sequence],
        "telemetry": run.get("telemetry"),
    }


def get_full_analysis_result(bid_id: int, run_id: int | None = None) -> dict | None:
    """The persisted structured FullAnalysisResult. Default: the bid's most
    recent COMPLETE run, falling back to the most recent PARTIAL run (a
    FAILED run is never returned by default -- ask for it by run_id).
    Returns {"run", "result", "specialist_results", "is_complete"} or None."""
    if run_id is None:
        runs = db.get_full_analysis_runs(bid_id)
        run = (next((r for r in runs if r.get("status") == RUN_COMPLETE), None)
               or next((r for r in runs if r.get("status") == RUN_PARTIAL), None))
        if run is None:
            return None
    else:
        run = _get_full_run(bid_id, run_id)
    stored = db.get_analysis_result(int(run["id"]))
    rows = []
    for row in db.get_full_analysis_specialist_results(int(run["id"])) or []:
        row = dict(row)
        row["effective_status"] = effective_specialist_status(row)
        rows.append(row)
    return {
        "run": run,
        "result": (stored or {}).get("full_analysis_result"),
        "specialist_results": rows,
        "is_complete": run.get("status") == RUN_COMPLETE,
    }


def mark_full_analysis_run_stuck(bid_id: int, run_id: int, *, now: datetime | None = None) -> dict:
    """Explicit, user-initiated action (never automatic): marks a run that
    `is_full_run_stuck` reports as stuck FAILED, preserving every
    already-durable specialist result. Does NOT start a new run -- the
    caller must explicitly call start_full_analysis(..., retry=True)."""
    run = _get_full_run(bid_id, run_id)
    stuck = is_full_run_stuck(run, now=now)
    if not stuck["stuck"]:
        raise RunNotStuckError(f"FULL run {run_id} is not stuck (status {run.get('status')})")
    return db.finalize_full_analysis_run(
        int(run["id"]), int(bid_id), RUN_FAILED,
        failure_reason=(f"Marked failed by user action: run appears stuck ({stuck['reason']}; "
                        f"no durable progress for {int(stuck['seconds_since_progress'] or 0)}s)."),
        failure_detail={"marked_stuck_by_user": True, "prior_status": run.get("status"),
                        "stuck": {k: stuck[k] for k in ("reason", "seconds_since_progress",
                                                         "run_age_seconds")}})


# ═══════════════════════════════════════════════════════════════════════
# Revision Full Analysis (PCI-B2B)
# ═══════════════════════════════════════════════════════════════════════

def revision_full_analysis_fingerprint_inputs(
    prior_run: dict,
    package,
    revision,
    impact_plan,
    contexts: dict[str, Any],
) -> dict:
    """Exact semantic inputs for incremental revision Full Analysis."""
    return {
        "fingerprint_version": "pci-b2b-fp-1",
        "engine_version": FULL_ANALYSIS_ENGINE_VERSION,
        "prior_full_analysis_run_id": int(prior_run.get("id") or 0),
        "prior_input_fingerprint": str(prior_run.get("input_fingerprint") or ""),
        "base_package_digest": str(getattr(package, "package_digest", "") or ""),
        "revision_id": str(getattr(revision, "revision_id", "") or ""),
        "revision_number": int(getattr(revision, "revision_number", 0) or 0),
        "state_fingerprint": str(getattr(impact_plan, "state_fingerprint", "") or ""),
        "impact_plan_fingerprint": str(getattr(impact_plan, "fingerprint", "") or ""),
        "affected_domains": sorted(getattr(impact_plan, "affected_domains", []) or []),
        "context_fingerprints": {
            d: str(getattr(ctx, "context_fingerprint", ""))
            for d, ctx in sorted(contexts.items())
        },
    }


def compute_revision_full_analysis_fingerprint(
    prior_run: dict,
    package,
    revision,
    impact_plan,
    contexts: dict[str, Any],
) -> str:
    """Deterministic sha256 for incremental revision Full Analysis."""
    return fa._digest(revision_full_analysis_fingerprint_inputs(
        prior_run=prior_run,
        package=package,
        revision=revision,
        impact_plan=impact_plan,
        contexts=contexts,
    ))


def _execute_revision_full_analysis_run(
    run: dict,
    package,
    contexts: dict[str, Any],
    prior_spec_results: dict[str, Any],
    prior_run: dict,
    impact_plan,
    revision,
    *,
    fingerprint: str,
    fingerprint_inputs: dict,
    api_key: str | None,
    client = None,
    canonical_view = None,
) -> None:
    """Execute one already-created revision FULL run to a terminal state."""
    run_id, bid_id = int(run["id"]), int(run["bid_id"])
    source_run_id = int(run["source_analysis_run_id"])
    recorder = _EventRecorder(run_id, bid_id)
    try:
        recorder.record(EVENT_CANONICAL_PACKAGE_READY, status=RUN_RUNNING,
                        detail=_package_detail(canonical_view or package, fingerprint))
        if recorder.aborted:
            return
        telemetry_context = {
            "workflow": "full_analysis",
            "bid_id": bid_id,
            "analysis_run_id": run_id,
            "metadata": {
                "execution_kind": "PCI_INCREMENTAL",
                "revision_id": str(getattr(revision, "revision_id", "")),
                "input_fingerprint": fingerprint[:16],
            },
        }

        # Collect revision facts and removed IDs across contexts
        all_rev_facts = []
        seen_fact_ids = set()
        removed_ids = set()
        for domain, ctx in contexts.items():
            for rf in getattr(ctx, "revision_facts", ()):
                fid = getattr(rf, "fact_id", None) or getattr(rf, "canonical_id", None)
                if fid and fid not in seen_fact_ids:
                    seen_fact_ids.add(fid)
                    all_rev_facts.append(rf)
            for ch in getattr(ctx, "relevant_changes", ()):
                if ch.get("change_type") == "REMOVES" and ch.get("entity_id"):
                    removed_ids.add(ch["entity_id"])

        revision_update_meta = {
            "execution_kind": "PCI_INCREMENTAL",
            "revision_id": str(getattr(revision, "revision_id", "")),
            "procurement_revision": int(getattr(revision, "revision_number", 0)),
            "impact_plan_fingerprint": getattr(impact_plan, "fingerprint", ""),
            "prior_full_analysis_run_id": int(prior_run["id"]),
            "prior_input_fingerprint": prior_run.get("input_fingerprint"),
            "affected_domains": list(getattr(impact_plan, "affected_domains", [])),
            "carried_forward_domains": [
                d for d in fa.SPECIALIST_IDS if d not in getattr(impact_plan, "affected_domains", [])
            ],
            "context_fingerprints": {
                d: getattr(ctx, "context_fingerprint", "") for d, ctx in contexts.items()
            },
        }

        result = fa.run_revision_full_analysis(
            package,
            contexts=contexts,
            prior_specialist_results=prior_spec_results,
            affected_domains=list(getattr(impact_plan, "affected_domains", [])),
            api_key=api_key,
            client=client,
            telemetry_context=telemetry_context,
            on_event=recorder,
            revision_facts=all_rev_facts,
            removed_ids=removed_ids,
            revision_update_metadata=revision_update_meta,
            canonical_view=canonical_view,
        )

        delta_summaries = {}
        for s in (result.specialist_results or []):
            sid = s.get("specialist_id")
            if sid in contexts and s.get("delta_audit"):
                delta_summaries[sid] = s["delta_audit"]
        revision_update_meta["delta_summaries"] = delta_summaries
        result.revision_update = revision_update_meta

        if recorder.aborted:
            return

        status = _terminal_status_for(result.completeness_status)
        failure_reason = None
        if status == RUN_FAILED:
            failure_reason = "no specialist completed; revision Full Analysis failed"
        elif status == RUN_PARTIAL:
            incomplete = [
                sid + (" (output truncated)" if st == fa.STATUS_PARTIAL else "")
                for sid, st in result.specialist_statuses.items()
                if st != fa.STATUS_COMPLETE
            ]
            rec_status = (result.reconciliation or {}).get("status")
            if rec_status != fa.STATUS_COMPLETE:
                incomplete.append("RECONCILIATION" + (" (output truncated)"
                                                      if rec_status == fa.STATUS_PARTIAL else ""))
            failure_reason = "incomplete domains: " + ", ".join(incomplete)

        db.finalize_full_analysis_run(
            run_id, bid_id, status,
            result=_result_payload(result, run_id=run_id, source_run_id=source_run_id,
                                   fingerprint=fingerprint,
                                   fingerprint_inputs=fingerprint_inputs),
            summary=_result_summary(result), failure_reason=failure_reason,
            telemetry=_telemetry_summary(result),
        )
    except Exception as exc:
        if recorder.aborted:
            return
        try:
            db.finalize_full_analysis_run(
                run_id, bid_id, RUN_FAILED,
                failure_reason=f"{type(exc).__name__}: {exc}"[:500],
                failure_detail={"traceback": traceback.format_exc()[-4000:],
                                "event_write_errors": recorder.write_errors[-5:]})
        except Exception:
            pass


def start_revision_full_analysis(
    bid_id: int,
    revision_target: int | str | Any,
    api_key: str | None = None,
    *,
    prior_run_id: int | None = None,
    created_by_user_id: str | None = None,
    retry: bool = False,
    execution: str = EXECUTION_BACKGROUND,
    client = None,
    package_builder = None,
    pci_storage = None,
    organization_id: str | None = None,
) -> dict:
    """Start (or reuse) an incremental revision Full Analysis for an applied buyer revision.

    1. Enforce prior COMPLETE Full Analysis baseline (fail closed before any provider calls).
    2. Load the applied ProcurementRevision and verify applied status and resolved chronology.
    3. Generate RevisionImpactPlan. If affected_domains is empty, return
       NO_INTELLIGENCE_REFRESH_REQUIRED with 0 provider calls.
    4. Assemble RevisionSpecialistContext for each affected domain and verify is_executable.
    5. Compute revision Full Analysis fingerprint and call db.start_full_analysis_run.
    6. Execute (or return reused run).
    """
    if execution not in (EXECUTION_BACKGROUND, EXECUTION_INLINE):
        raise ValueError(f"unknown execution mode {execution!r}")

    # 1. Tenancy / Organization ID
    org_id = organization_id
    if not org_id:
        bid = db.get_bid(bid_id)
        if bid:
            org_id = bid.get("organization_id")
    if not org_id:
        org_id = "default"

    import procurement_change_intelligence as pci

    mgr = pci.get_pci_manager(bid_id, organization_id=org_id, storage=pci_storage)

    # 2. Resolve target revision
    if isinstance(revision_target, pci.ProcurementRevision):
        rev = revision_target
    elif isinstance(revision_target, str):
        rev = mgr.get_revision_by_id(revision_target)
    elif isinstance(revision_target, int):
        matching = [r for r in mgr.get_all_revisions() if r.revision_number == revision_target]
        if len(matching) == 1:
            rev = matching[0]
        elif len(matching) > 1:
            raise pci.PCIEngineError(f"Ambiguous revision_number {revision_target} matches multiple revisions")
        else:
            rev = None
    else:
        raise TypeError(f"Target must be int, str, or ProcurementRevision, got {type(revision_target).__name__}")

    if rev is None:
        raise pci.PCIEngineError(f"Revision {revision_target} not found for bid {bid_id}")

    if rev.review_status != "applied":
        raise pci.PCIContextNotEligibleError(
            f"Revision {rev.revision_id} is not applied (review_status='{rev.review_status}')"
        )
    if rev.chronology_unresolved:
        raise pci.PCIContextNotEligibleError(
            f"Revision {rev.revision_id} has unresolved chronology"
        )

    # 2b. Current-Revision Gate (Fail closed if a later applied revision exists)
    applied_revs = [
        r for r in mgr.get_all_revisions()
        if r.is_applied and r.review_status == "applied" and not r.chronology_unresolved
    ]
    if applied_revs:
        target_key = (
            rev.buyer_chronology_index if rev.buyer_chronology_index is not None else -1,
            rev.revision_number,
        )
        latest_applied = sorted(
            applied_revs,
            key=lambda r: (
                r.buyer_chronology_index if r.buyer_chronology_index is not None else -1,
                r.revision_number,
            )
        )[-1]
        latest_key = (
            latest_applied.buyer_chronology_index if latest_applied.buyer_chronology_index is not None else -1,
            latest_applied.revision_number,
        )
        if target_key < latest_key:
            raise RevisionNotCurrentError(
                f"REVISION_NOT_CURRENT: revision {rev.revision_id} (rev #{rev.revision_number}) is not the latest "
                f"applied revision (latest is {latest_applied.revision_id}, rev #{latest_applied.revision_number})"
            )

    # 3. Resolve prior COMPLETE Full Analysis
    if prior_run_id is not None:
        prior_run = _get_full_run(bid_id, prior_run_id)
        if prior_run is None or prior_run.get("status") != RUN_COMPLETE:
            raise FullAnalysisBaselineRequiredError(
                f"FULL_ANALYSIS_BASELINE_REQUIRED: run {prior_run_id} is not a COMPLETE Full Analysis"
            )
    else:
        runs = db.get_full_analysis_runs(bid_id)
        prior_run = None
        for r in runs:
            if r.get("status") != RUN_COMPLETE:
                continue
            res_row = db.get_analysis_result(r["id"])
            rev_up = (res_row.get("full_analysis_result") or {}).get("revision_update") if res_row else None
            if rev_up and rev_up.get("revision_id") == rev.revision_id:
                prior_base_id = rev_up.get("prior_full_analysis_run_id")
                if prior_base_id:
                    prior_run = _get_full_run(bid_id, prior_base_id)
                    break
            elif not rev_up or rev_up.get("revision_id") != rev.revision_id:
                prior_run = r
                break
        if prior_run is None:
            raise FullAnalysisBaselineRequiredError(
                f"FULL_ANALYSIS_BASELINE_REQUIRED: bid {bid_id} has no COMPLETE Full Analysis baseline"
            )

    # 4. Load all six prior specialist results
    prior_spec_rows = db.get_full_analysis_specialist_results(int(prior_run["id"])) or []
    prior_spec_results = {}
    for row in prior_spec_rows:
        res = row.get("result") or {}
        sid = row.get("specialist_id")
        if sid:
            prior_spec_results[sid] = res

    for sid in fa.SPECIALIST_IDS:
        if sid not in prior_spec_results or prior_spec_results[sid].get("status") != fa.STATUS_COMPLETE:
            raise FullAnalysisBaselineRequiredError(
                f"FULL_ANALYSIS_BASELINE_REQUIRED: domain {sid} is missing or incomplete in prior run"
            )

    prior_findings = []
    for sid in fa.SPECIALIST_IDS:
        prior_findings.extend(prior_spec_results[sid].get("findings") or [])

    # 5. Build RevisionImpactPlan
    impact_plan = mgr.get_revision_impact_plan(rev, existing_findings=prior_findings)

    # 5b. Enforce stale / unresolved finding domain coverage before execution
    finding_to_producer = {}
    for sid, sres in prior_spec_results.items():
        for f in (sres.get("findings") or []):
            fid = f.get("finding_id")
            if fid:
                prod = f.get("produced_by") or sid
                if isinstance(prod, (list, tuple)) and prod:
                    prod = prod[0]
                finding_to_producer[fid] = prod

    effective_affected_domains = set(impact_plan.affected_domains)

    for fid in getattr(impact_plan, "stale_finding_ids", ()):
        prod = finding_to_producer.get(fid)
        if prod and prod in fa.SPECIALIST_IDS:
            effective_affected_domains.add(prod)

    for fid in getattr(impact_plan, "unresolved_finding_ids", ()):
        prod = finding_to_producer.get(fid)
        if not prod or prod not in fa.SPECIALIST_IDS:
            raise pci.PCIEngineError(
                f"Cannot establish producing specialist domain for unresolved finding {fid}"
            )
        effective_affected_domains.add(prod)

    import dataclasses
    if set(effective_affected_domains) != set(impact_plan.affected_domains):
        impact_plan = dataclasses.replace(
            impact_plan,
            affected_domains=sorted(effective_affected_domains),
            fingerprint="",
        )
        impact_plan.__post_init__()

    # 6. Zero-Impact check
    if not impact_plan.affected_domains:
        return {
            "outcome": "NO_INTELLIGENCE_REFRESH_REQUIRED",
            "revision_id": rev.revision_id,
            "revision_number": rev.revision_number,
            "impact_plan_fingerprint": impact_plan.fingerprint,
            "affected_domains": [],
            "executing": False,
            "run": None,
        }

    # 7. Assemble CanonicalPackage and CurrentCanonicalView
    builder = package_builder or _default_package_builder
    source_run_id = int(prior_run["source_analysis_run_id"])
    package = builder(source_run_id)
    current_canonical_view = mgr.get_current_canonical_view(package, up_to_revision=rev)

    # 8. Build and verify RevisionSpecialistContext for each affected domain
    contexts = {}
    for domain in impact_plan.affected_domains:
        ctx = mgr.get_revision_specialist_context(
            rev, specialist_id=domain, canonical_package=package,
            prior_findings=prior_findings, impact_plan=impact_plan,
            current_canonical_view=current_canonical_view,
        )
        if not ctx.is_executable:
            raise pci.PCIContextNotEligibleError(
                f"Context for {domain} is not executable: {ctx.blocking_reason}"
            )
        contexts[domain] = ctx

    # 9. Compute execution fingerprint
    fingerprint = compute_revision_full_analysis_fingerprint(
        prior_run=prior_run, package=package, revision=rev, impact_plan=impact_plan, contexts=contexts
    )
    fingerprint_inputs = revision_full_analysis_fingerprint_inputs(
        prior_run=prior_run, package=package, revision=rev, impact_plan=impact_plan, contexts=contexts
    )

    # 10. Start or reuse via Migration 020 RPC
    detail = {
        "execution_kind": "PCI_INCREMENTAL",
        "revision_id": rev.revision_id,
        "revision_number": rev.revision_number,
        "prior_full_analysis_run_id": int(prior_run["id"]),
        "prior_input_fingerprint": prior_run.get("input_fingerprint"),
        "impact_plan_fingerprint": impact_plan.fingerprint,
        "affected_domains": list(impact_plan.affected_domains),
        "carried_forward_domains": [d for d in fa.SPECIALIST_IDS if d not in impact_plan.affected_domains],
        "context_fingerprints": {d: ctx.context_fingerprint for d, ctx in contexts.items()},
        "engine_version": FULL_ANALYSIS_ENGINE_VERSION,
    }

    response = db.start_full_analysis_run(
        bid_id, source_run_id, fingerprint, FULL_ANALYSIS_ENGINE_VERSION,
        corpus_digest=prior_run.get("corpus_digest"), created_by_user_id=created_by_user_id,
        retry=retry, detail=detail
    )
    if not response or "outcome" not in response:
        raise FullAnalysisError("start_full_analysis_run returned no outcome")

    outcome, run = response["outcome"], response["run"]
    out = {
        "outcome": outcome,
        "run": run,
        "input_fingerprint": fingerprint,
        "fingerprint_matches": run.get("input_fingerprint") == fingerprint,
        "source_analysis_run_id": source_run_id,
        "revision_id": rev.revision_id,
        "executing": False,
    }
    if outcome != OUTCOME_CREATED:
        return out

    kwargs = dict(
        run=run, package=package, contexts=contexts, prior_spec_results=prior_spec_results,
        prior_run=prior_run, impact_plan=impact_plan, revision=rev,
        fingerprint=fingerprint, fingerprint_inputs=fingerprint_inputs,
        api_key=api_key, client=client,
        canonical_view=current_canonical_view,
    )
    if execution == EXECUTION_INLINE:
        _execute_revision_full_analysis_run(**kwargs)
    else:
        thread = threading.Thread(
            target=_execute_revision_full_analysis_run, kwargs=kwargs, daemon=True,
            name=f"pci-revision-run-{run['id']}"
        )
        thread.start()
        out["executing"] = True
    return out
