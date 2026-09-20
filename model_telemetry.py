"""
model_telemetry.py -- the one normalized, provider-neutral telemetry event
for every model/embedding call this application makes (Phase 4 of the BI
Context & Token Optimization Program).

Design contract:
  * One provider invocation -> one normalized event. Never duplicated,
    never fabricated.
  * Token fields are ALWAYS provider-reported when populated -- never
    derived from character/byte counts. `request_bytes`/`input_chars` are
    separate, explicitly-labeled measured fields, never relabeled as
    "tokens" (instruction 4).
  * No prompt text, no response text, no RFP/proposal content, no
    credentials are ever placed into an event. `metadata` is reserved for
    small, structured execution context only (see `_MAX_METADATA_BYTES`).
  * Telemetry recording NEVER raises and NEVER alters a caller's return
    value or a re-raised exception -- see the module docstring's "failure
    policy" section below for the deliberate reasoning.
  * Fast Analysis and Deep Verify already have their OWN rich, per-call,
    list-based telemetry mechanisms (fast_analysis.py's `telemetry` list;
    extractor.py's identical pattern in `_extract_chunk_facts`). This
    module does NOT duplicate that capture at their call sites -- it
    BRIDGES their already-built lists into normalized events exactly once,
    via `bridge_fast_analysis_telemetry()` / `bridge_deep_verify_telemetry()`,
    so there is never a second, competing telemetry system and never a
    double-counted call. Every other caller (analyst.py, section_analyzer.py,
    extractor.py's Stage D, embeddings.py) uses the direct
    `telemetry_context=` parameter on config.execute_messages_create (or
    `record_voyage_usage` for the separate embedding provider) instead.

Failure policy (instruction 16): analytical work must never be destroyed
solely because usage-accounting persistence failed. `record_usage_event()`
catches and swallows any persistence exception, but is NOT silent about
it -- it always returns the built (but possibly unpersisted) event dict,
and a persistence failure is recorded in-process via `_last_persistence_error`
(inspectable by tests and, if a future UI wants it, by an ops surface) so
the failure is visible and recoverable rather than invisibly dropped. This
is deliberately DIFFERENT from Fast Analysis's raw-snapshot persistence,
which fails the whole run closed -- that rule exists because a missing raw
snapshot silently degrades a FUTURE report-regeneration guarantee callers
depend on. A missing usage-accounting row has no equivalent correctness
consequence for the analytical result the user is waiting on right now.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

TELEMETRY_SCHEMA_VERSION = "1.0"

# Small, deliberate ceiling on `metadata` -- if a caller passes something
# large, it is dropped rather than silently bloating a supposedly-compact
# accounting table (and rather than ever storing prompt/response content by
# accident under a permissive field name).
_MAX_METADATA_BYTES = 2000

# The one place a persistence failure is recorded for visibility (instruction
# 16: "the failure must be visible and recoverable") -- inspected by tests;
# a future ops surface could read this too. Never raised, never silent.
_last_persistence_error: str | None = None


def get_last_persistence_error() -> str | None:
    return _last_persistence_error


def _clamp_metadata(metadata: dict | None) -> dict | None:
    if not metadata:
        return None
    try:
        encoded = json.dumps(metadata)
    except (TypeError, ValueError):
        return None
    if len(encoded.encode("utf-8")) > _MAX_METADATA_BYTES:
        return None
    return metadata


def build_usage_event(
    *,
    workflow: str,
    operation: str,
    provider: str,
    model: str,
    status: str,
    bid_id: int | None = None,
    analysis_run_id: int | None = None,
    section_review_id: int | None = None,
    document_id: str | None = None,
    call_index: int | None = None,
    retry_number: int = 0,
    parent_event_id: int | None = None,
    request_bytes: int | None = None,
    input_chars: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_creation_tokens: int | None = None,
    cache_read_tokens: int | None = None,
    reasoning_tokens: int | None = None,
    latency_ms: int | None = None,
    stop_reason: str | None = None,
    error_category: str | None = None,
    parse_status: str | None = None,
    metadata: dict | None = None,
    created_at: str | None = None,
) -> dict:
    """Pure, side-effect-free construction of one normalized telemetry
    event dict -- JSON-safe, no persistence. `status` must be 'SUCCESS' or
    'FAILURE'. Every token-count field defaults to None (nullable) and is
    NEVER derived here from request_bytes/input_chars -- callers pass only
    what the provider itself reported."""
    if status not in ("SUCCESS", "FAILURE"):
        raise ValueError(f"status must be 'SUCCESS' or 'FAILURE', got {status!r}")
    return {
        "schema_version": TELEMETRY_SCHEMA_VERSION,
        "workflow": workflow,
        "operation": operation,
        "provider": provider,
        "model": model,
        "status": status,
        "bid_id": bid_id,
        "analysis_run_id": analysis_run_id,
        "section_review_id": section_review_id,
        "document_id": document_id,
        "call_index": call_index,
        "retry_number": retry_number,
        "parent_event_id": parent_event_id,
        "request_bytes": request_bytes,
        "input_chars": input_chars,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_tokens": cache_creation_tokens,
        "cache_read_tokens": cache_read_tokens,
        "reasoning_tokens": reasoning_tokens,
        "latency_ms": latency_ms,
        "stop_reason": stop_reason,
        "error_category": error_category,
        "parse_status": parse_status,
        "metadata": _clamp_metadata(metadata),
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
    }


def record_usage_event(event: dict) -> dict | None:
    """The one place a normalized event is persisted. Never raises --
    catches any persistence exception, records it (visibly, via
    get_last_persistence_error()), and returns None on failure so a caller
    that checks the return value can know without a try/except. Analytical
    work already completed by the time this is called is never affected
    either way (see module docstring's failure policy)."""
    global _last_persistence_error
    try:
        import database as db
        row = db.create_model_usage_event(event)
        if row is not None:
            _last_persistence_error = None
        return row
    except Exception as exc:
        _last_persistence_error = f"{type(exc).__name__}: {exc}"
        return None


def _extract_anthropic_usage(response: Any) -> dict:
    usage = getattr(response, "usage", None)
    details = getattr(usage, "output_tokens_details", None)
    return {
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "cache_creation_tokens": getattr(usage, "cache_creation_input_tokens", None),
        "cache_read_tokens": getattr(usage, "cache_read_input_tokens", None),
        "reasoning_tokens": getattr(details, "thinking_tokens", None) if details is not None else None,
        "stop_reason": getattr(response, "stop_reason", None),
    }


def record_from_anthropic_response(
    context: dict, model: str, response: Any, latency_ms: int, *,
    request_bytes: int | None = None, retry_number: int = 0,
) -> dict | None:
    """Builds and persists a SUCCESS event from a real Anthropic
    `Message` response object. `context` supplies workflow/operation/ids
    -- see config.execute_messages_create's `telemetry_context` parameter."""
    usage_fields = _extract_anthropic_usage(response)
    event = build_usage_event(
        workflow=context.get("workflow", "unknown"),
        operation=context.get("operation", "unknown"),
        provider="anthropic",
        model=model,
        status="SUCCESS",
        bid_id=context.get("bid_id"),
        analysis_run_id=context.get("analysis_run_id"),
        section_review_id=context.get("section_review_id"),
        document_id=context.get("document_id"),
        call_index=context.get("call_index"),
        retry_number=retry_number,
        parent_event_id=context.get("parent_event_id"),
        request_bytes=request_bytes,
        input_chars=context.get("input_chars"),
        latency_ms=latency_ms,
        metadata=context.get("metadata"),
        **usage_fields,
    )
    return record_usage_event(event)


def record_failure(
    context: dict, model: str, error: BaseException, latency_ms: int, *,
    request_bytes: int | None = None, retry_number: int = 0,
) -> dict | None:
    """Builds and persists a FAILURE event -- never with fabricated usage
    (all token fields stay None; no response was received)."""
    try:
        from config import classify_anthropic_error
        category = classify_anthropic_error(error).get("category")
    except Exception:
        category = "UNKNOWN"
    event = build_usage_event(
        workflow=context.get("workflow", "unknown"),
        operation=context.get("operation", "unknown"),
        provider="anthropic",
        model=model,
        status="FAILURE",
        bid_id=context.get("bid_id"),
        analysis_run_id=context.get("analysis_run_id"),
        section_review_id=context.get("section_review_id"),
        document_id=context.get("document_id"),
        call_index=context.get("call_index"),
        retry_number=retry_number,
        parent_event_id=context.get("parent_event_id"),
        request_bytes=request_bytes,
        input_chars=context.get("input_chars"),
        latency_ms=latency_ms,
        error_category=category,
        metadata=context.get("metadata"),
    )
    return record_usage_event(event)


def record_voyage_usage(
    *, workflow: str, operation: str, status: str, item_count: int,
    input_chars: int | None = None, latency_ms: int | None = None,
    total_tokens: int | None = None, error_category: str | None = None,
    bid_id: int | None = None,
) -> dict | None:
    """Voyage AI embedding calls -- a separate provider with a different
    usage-reporting shape. `total_tokens` is passed through only when the
    installed SDK's response object actually exposed it (see
    embeddings.py); otherwise left None rather than estimated from
    character counts (instruction 10)."""
    event = build_usage_event(
        workflow=workflow, operation=operation, provider="voyage",
        model="voyage-3-lite", status=status, bid_id=bid_id,
        input_chars=input_chars, input_tokens=total_tokens,
        latency_ms=latency_ms, error_category=error_category,
        metadata={"item_count": item_count},
    )
    return record_usage_event(event)


# ---------------------------------------------------------------------------
# Bridges: convert an already-built, rich, module-owned telemetry list into
# normalized events, exactly once, without altering or duplicating the
# source list's own role for that module's existing logic.
# ---------------------------------------------------------------------------

def bridge_fast_analysis_telemetry(
    telemetry: list[dict], *, bid_id: int | None = None, analysis_run_id: int | None = None,
) -> list[dict]:
    """fast_analysis.py's own `telemetry` list (call_index, call_kind,
    filename, route, model, input_tokens, output_tokens, latency_seconds,
    stop_reason, parse_status, error, parent_call_index, ...) -> one
    normalized event per entry. Called once, after a Fast Analysis run
    completes (analysis_service.py), never from inside fast_analysis.py's
    own call sites -- so this can never double-count a call already
    captured there."""
    recorded = []
    for entry in telemetry:
        status = "FAILURE" if entry.get("error") else "SUCCESS"
        latency_ms = None
        if entry.get("latency_seconds") is not None:
            latency_ms = round(entry["latency_seconds"] * 1000)
        error_category = None
        if entry.get("error"):
            error_category = "PROCESSING_ERROR"
        event = build_usage_event(
            workflow="fast_analysis",
            operation=entry.get("call_kind") or "unknown",
            provider="anthropic",
            model=entry.get("model") or "unknown",
            status=status,
            bid_id=bid_id,
            analysis_run_id=analysis_run_id,
            document_id=entry.get("filename"),
            call_index=entry.get("call_index"),
            parent_event_id=None,  # parent_call_index refers to fast_analysis's own indexing,
                                    # not a model_usage_events id -- kept in metadata instead.
            request_bytes=entry.get("request_bytes"),
            input_chars=entry.get("chunk_chars"),
            input_tokens=entry.get("input_tokens"),
            output_tokens=entry.get("output_tokens"),
            latency_ms=latency_ms,
            stop_reason=entry.get("stop_reason"),
            error_category=error_category,
            parse_status=entry.get("parse_status"),
            metadata=_clamp_metadata({
                "route": entry.get("route"),
                "parent_call_index": entry.get("parent_call_index"),
                "split_trigger_reason": entry.get("split_trigger_reason"),
            }),
        )
        row = record_usage_event(event)
        recorded.append(row or event)
    return recorded


# ---------------------------------------------------------------------------
# Cost accounting: deterministic aggregation over already-persisted events.
# Pure Python over rows database.get_model_usage_events() already filtered
# -- no SQL aggregation logic embedded in a migration, easy to test without
# a live database. Token/call/retry/latency totals only; no dollar amounts
# anywhere here (instruction 13 -- pricing must stay a separable, versioned
# concern from raw usage accounting).
# ---------------------------------------------------------------------------

_SUM_FIELDS = ("input_tokens", "output_tokens", "cache_creation_tokens",
              "cache_read_tokens", "reasoning_tokens", "latency_ms")


def _summarize_events(events: list[dict]) -> dict:
    totals = {f: 0 for f in _SUM_FIELDS}
    have_any = {f: False for f in _SUM_FIELDS}
    calls = len(events)
    retries = sum(1 for e in events if (e.get("retry_number") or 0) > 0)
    failures = sum(1 for e in events if e.get("status") == "FAILURE")
    for e in events:
        for f in _SUM_FIELDS:
            v = e.get(f)
            if v is not None:
                totals[f] += v
                have_any[f] = True
    # A field with zero contributing events stays None (never a fabricated
    # 0 that looks like "provider reported zero") -- distinguishes "no
    # events had this field" from "events had it and it summed to zero".
    result = {f: (totals[f] if have_any[f] else None) for f in _SUM_FIELDS}
    result.update({"calls": calls, "retries": retries, "failures": failures})
    return result


def summarize_for_run(analysis_run_id: int) -> dict:
    import database as db
    events = db.get_model_usage_events(analysis_run_id=analysis_run_id, limit=10000)
    return _summarize_events(events)


def summarize_for_workflow(workflow: str, *, since: str | None = None, until: str | None = None) -> dict:
    import database as db
    events = db.get_model_usage_events(workflow=workflow, since=since, until=until, limit=10000)
    return _summarize_events(events)


def summarize_for_bid(bid_id: int) -> dict:
    """Totals for one bid, broken down by workflow."""
    import database as db
    events = db.get_model_usage_events(bid_id=bid_id, limit=10000)
    by_workflow: dict[str, list[dict]] = {}
    for e in events:
        by_workflow.setdefault(e.get("workflow") or "unknown", []).append(e)
    return {wf: _summarize_events(evs) for wf, evs in sorted(by_workflow.items())}


def summarize_for_period(since: str, until: str | None = None) -> dict:
    """Totals for a time period, broken down by (provider, model, workflow)."""
    import database as db
    events = db.get_model_usage_events(since=since, until=until, limit=10000)
    by_key: dict[tuple, list[dict]] = {}
    for e in events:
        key = (e.get("provider") or "unknown", e.get("model") or "unknown", e.get("workflow") or "unknown")
        by_key.setdefault(key, []).append(e)
    return {
        f"{provider}/{model}/{workflow}": _summarize_events(evs)
        for (provider, model, workflow), evs in sorted(by_key.items())
    }


def top_operations_for_workflow(workflow: str, *, since: str | None = None, until: str | None = None,
                                limit: int = 10) -> list[tuple[str, dict]]:
    """Per-operation breakdown within one workflow, sorted by total tokens
    (input+output) descending -- the "TOP OPERATIONS" section of
    scripts/model_usage_report.py."""
    import database as db
    events = db.get_model_usage_events(workflow=workflow, since=since, until=until, limit=10000)
    by_op: dict[str, list[dict]] = {}
    for e in events:
        by_op.setdefault(e.get("operation") or "unknown", []).append(e)
    summarized = [(op, _summarize_events(evs)) for op, evs in by_op.items()]
    summarized.sort(key=lambda x: (x[1]["input_tokens"] or 0) + (x[1]["output_tokens"] or 0), reverse=True)
    return summarized[:limit]


def bridge_deep_verify_telemetry(
    telemetry: list[dict], *, bid_id: int | None = None,
) -> list[dict]:
    """extractor.py's Stage A `telemetry` list (the same additive,
    caller-owned diagnostic pattern as Fast Analysis's -- call_index,
    call_kind, filename, model, request_bytes, chunk_chars, latency_seconds,
    input_tokens, output_tokens, stop_reason, parse_status, error,
    record_counts) -> one normalized event per entry. Closes the Phase 1
    durability gap (the list was built but never activated -- see
    extractor.py's `_extract_procurement_package`, which now passes a
    `telemetry=[]` list through to `extract_document_facts`)."""
    recorded = []
    for entry in telemetry:
        status = "FAILURE" if entry.get("error") else "SUCCESS"
        latency_ms = None
        if entry.get("latency_seconds") is not None:
            latency_ms = round(entry["latency_seconds"] * 1000)
        event = build_usage_event(
            workflow="deep_verify",
            operation=entry.get("call_kind") or "stage_a_document_facts",
            provider="anthropic",
            model=entry.get("model") or "unknown",
            status=status,
            bid_id=bid_id,
            document_id=entry.get("filename"),
            call_index=entry.get("call_index"),
            request_bytes=entry.get("request_bytes"),
            input_chars=entry.get("chunk_chars"),
            input_tokens=entry.get("input_tokens"),
            output_tokens=entry.get("output_tokens"),
            latency_ms=latency_ms,
            stop_reason=entry.get("stop_reason"),
            error_category="PROCESSING_ERROR" if entry.get("error") else None,
            parse_status=entry.get("parse_status"),
            metadata=_clamp_metadata({"record_counts": entry.get("record_counts")}),
        )
        row = record_usage_event(event)
        recorded.append(row or event)
    return recorded
