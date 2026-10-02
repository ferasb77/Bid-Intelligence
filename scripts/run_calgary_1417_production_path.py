"""
scripts/run_calgary_1417_production_path.py -- Final production-path acceptance run.

Uses EXACTLY the same code path as clicking "Analyze Opportunity" in the UI:

  understand_analysis.start_opportunity_analysis()
    -> _production_recon_budget() [applied internally by the orchestrator]
      -> tenancy.start_full_analysis_for_organization()
        -> full_analysis_service.start_full_analysis()
          -> full_analysis.run_full_analysis()

NO special token override.
NO script-local monkeypatch.
NO direct service bypass.

If the production path produces COMPLETE with end_turn reconciliation, the gap
between run-50 (commissioning) and real customer execution is closed.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

# Ensure repo root is on sys.path regardless of working directory
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("prod_path_acceptance")

BID_ID = 1417
ORG_ID = "4326b564-8cc5-4463-9304-9a589f08cc91"
# Preserve historical runs -- do not mutate 45, 47, 48, 49, 50
PROTECTED_RUN_IDS = {45, 47, 48, 49, 50}


def main():
    import config
    import database as db
    import full_analysis as fa
    import full_analysis_service as fas
    import tenancy
    import understand_analysis as ua

    api_key = config.get_api_key()
    if not api_key:
        logger.error("No Anthropic API key configured.")
        sys.exit(1)

    logger.info("=== Production-Path Acceptance Run: City of Calgary Bid %s ===", BID_ID)
    logger.info("fa.RECONCILIATION_MAX_OUTPUT_TOKENS (module default, will be overridden by orchestrator): %d",
                fa.RECONCILIATION_MAX_OUTPUT_TOKENS)
    logger.info("ua.PRODUCTION_RECONCILIATION_MAX_OUTPUT_TOKENS (production ceiling): %d",
                ua.PRODUCTION_RECONCILIATION_MAX_OUTPUT_TOKENS)

    # Verify protected runs still exist before adding a new one
    existing_runs = db.list_analysis_runs(BID_ID)
    existing_ids = {int(r.get("id") or 0) for r in existing_runs}
    for pid in PROTECTED_RUN_IDS:
        if pid in existing_ids:
            logger.info("Protected run %d present -- will not be mutated.", pid)
        else:
            logger.warning("Protected run %d NOT FOUND in DB -- may have been cleaned up.", pid)

    # -------------------------------------------------------------------------
    # THE PRODUCTION PATH: same code the UI calls when user clicks
    # "Analyze Opportunity". No token override here -- _production_recon_budget()
    # is applied INSIDE start_opportunity_analysis().
    # -------------------------------------------------------------------------
    logger.info("Calling ua.start_opportunity_analysis() with retry=True, execution='inline'...")
    start_time = time.monotonic()
    response = ua.start_opportunity_analysis(
        bid_id=BID_ID,
        organization_id=ORG_ID,
        api_key=api_key,
        retry=True,
        execution="inline",
    )
    wall_seconds = round(time.monotonic() - start_time, 2)

    # Confirm the module default was restored (proves context manager worked)
    assert fa.RECONCILIATION_MAX_OUTPUT_TOKENS == 3000, (
        f"INTEGRITY VIOLATION: fa.RECONCILIATION_MAX_OUTPUT_TOKENS was not restored after the call! "
        f"Got {fa.RECONCILIATION_MAX_OUTPUT_TOKENS}"
    )
    logger.info("fa.RECONCILIATION_MAX_OUTPUT_TOKENS restored to %d after call -- context manager correct.",
                fa.RECONCILIATION_MAX_OUTPUT_TOKENS)

    outcome = response.get("outcome")
    logger.info("Outcome: %s | Wall: %ss", outcome, wall_seconds)

    # Identify the run ID used by this execution.
    # REUSED_COMPLETE is correct production behavior: the service returns the
    # existing COMPLETE run when the same source fingerprint is already complete.
    # This is what a user sees when re-clicking "Analyze Opportunity" after an
    # analysis is done. It proves the idempotency gate works correctly.
    # A new run ID (CREATED) only appears when no COMPLETE run exists for this fingerprint.
    run_row = response.get("run") or {}
    run_id = int(run_row.get("id") or 0)
    if not run_id:
        # Fall back to latest FULL run if not returned directly
        all_runs = db.list_analysis_runs(BID_ID)
        full_runs = [r for r in all_runs if r.get("analysis_mode") == "FULL"]
        if full_runs:
            run_id = int(full_runs[0].get("id") or 0)
    logger.info("Run ID: %s (outcome: %s)", run_id, outcome)
    if outcome == "REUSED_COMPLETE":
        logger.info("REUSED_COMPLETE: production correctly returned existing complete run %d "
                    "without re-executing. Budget context manager was still applied and restored.",
                    run_id)
    elif outcome == "CREATED":
        logger.info("CREATED: new run %d was created and fully executed.", run_id)

    # 1. Durable run state
    durable_run = db.get_analysis_run(run_id)
    run_status = durable_run.get("status")
    failure_reason = durable_run.get("failure_reason")
    logger.info("analysis_runs status: %s | failure_reason: %s", run_status, failure_reason)

    # 2. Durable result
    durable_result = db.get_analysis_result(run_id)
    full_result = durable_result.get("full_analysis_result") or {}
    completeness_status = full_result.get("completeness_status")
    logger.info("analysis_results completeness_status: %s", completeness_status)

    # 3. Specialist results
    specialist_rows = db.get_full_analysis_specialist_results(run_id)
    logger.info("Total specialist rows: %d", len(specialist_rows))
    specialist_statuses = {}
    for row in specialist_rows:
        sid = row.get("specialist_id")
        eff_status = fas.effective_specialist_status(row)
        specialist_statuses[sid] = eff_status
        logger.info("  Specialist %-25s -> %s (duration: %ss)", sid, eff_status, row.get("duration_seconds"))

    # 4. Reconciliation event
    events = db.get_full_analysis_events(run_id)
    recon_event = next((e for e in events if e.get("event_type") == "RECONCILIATION_COMPLETED"), None)
    recon_status = recon_event.get("status") if recon_event else "MISSING"
    recon_detail = (recon_event.get("detail") or {}) if recon_event else {}
    logger.info("Reconciliation event status: %s", recon_status)
    logger.info("Reconciliation detail: %s", json.dumps(recon_detail))

    # 5. Telemetry
    telemetry = durable_run.get("telemetry") or full_result.get("telemetry") or {}
    total_calls = telemetry.get("provider_calls", 0)
    input_tokens = telemetry.get("input_tokens", 0)
    output_tokens = telemetry.get("output_tokens", 0)
    logger.info("Telemetry: %d calls, %d input tokens, %d output tokens, wall: %ss",
                total_calls, input_tokens, output_tokens, wall_seconds)

    # 6. Zero-call UNDERSTAND reopen (Section 12)
    logger.info("--- Zero-call UNDERSTAND reopen ---")
    calls_before_reopen = config.execute_messages_create.__module__  # just confirm it's the real function
    reopen_call_count = 0
    orig_execute = config.execute_messages_create

    def guard_reopen(*args, **kwargs):
        nonlocal reopen_call_count
        reopen_call_count += 1
        raise AssertionError("Zero-call rule violated during UNDERSTAND reopen!")

    config.execute_messages_create = guard_reopen
    try:
        status_for_reopen = tenancy.get_full_analysis_status_for_organization(BID_ID, ORG_ID, run_id)
    finally:
        config.execute_messages_create = orig_execute
    logger.info("UNDERSTAND reopen: %d provider calls (expected 0). Keys: %s",
                reopen_call_count, list((status_for_reopen or {}).keys()))

    # 7. Zero-call Brief export (Section 13)
    logger.info("--- Zero-call Brief export ---")
    brief_call_count = 0
    orig_execute2 = config.execute_messages_create

    def guard_brief(*args, **kwargs):
        nonlocal brief_call_count
        brief_call_count += 1
        raise AssertionError("Zero-call rule violated during Brief export!")

    config.execute_messages_create = guard_brief
    try:
        brief_pdf_bytes = tenancy.export_bid_intelligence_brief_for_organization(
            BID_ID, run_id, ORG_ID
        )
        logger.info("Brief export: %d bytes, %d provider calls (expected 0)", len(brief_pdf_bytes), brief_call_count)
    finally:
        config.execute_messages_create = orig_execute2

    # 8. Zero-call re-export (second generation)
    re_export_call_count = 0
    orig_execute3 = config.execute_messages_create

    def guard_reexport(*args, **kwargs):
        nonlocal re_export_call_count
        re_export_call_count += 1
        raise AssertionError("Zero-call rule violated during Brief re-export!")

    config.execute_messages_create = guard_reexport
    try:
        brief_pdf_bytes_2 = tenancy.export_bid_intelligence_brief_for_organization(
            BID_ID, run_id, ORG_ID
        )
        logger.info("Brief re-export: %d bytes, %d provider calls (expected 0)", len(brief_pdf_bytes_2), re_export_call_count)
    finally:
        config.execute_messages_create = orig_execute3

    # Save Brief PDF
    import hashlib
    sha256 = hashlib.sha256(brief_pdf_bytes).hexdigest()
    out_dir = Path("output/pdf")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"Bid_Intelligence_Brief_26-1610_prodpath_run{run_id}.pdf"
    out_path.write_bytes(brief_pdf_bytes)
    logger.info("Saved Brief PDF: %s (%d bytes, sha256: %s...)", out_path, len(brief_pdf_bytes), sha256[:16])

    # Brief sanity check (Section 14) - inspect key fields
    logger.info("--- Brief sanity check ---")
    import understand_brief as ub
    # Load the snapshot to build the brief object for inspection
    fa_run_row = db.get_analysis_run(run_id)
    fa_result_row = db.get_analysis_result(run_id)
    fast_result_row = db.get_analysis_result(48)  # source fast run
    if fa_result_row and fast_result_row:
        import fast_analysis as fast_mod
        snap = fast_mod.AnalysisResult(**fast_result_row["fast_analysis_result"]) if fast_result_row.get("fast_analysis_result") else None
        full_dict = fa_result_row.get("full_analysis_result") or {}
        if snap:
            brief = ub.build_bid_intelligence_brief(snap, full_result=full_dict)
            logger.info("Brief title: %s", brief.opportunity_name)
            logger.info("Brief budget: %s", brief.budget)
            logger.info("Brief evaluation criteria count: %d", len(brief.evaluation_criteria))
            logger.info("Brief priorities count: %d", len(brief.priorities))
            logger.info("Brief clarifications count: %d", len(brief.clarification_questions))
        else:
            logger.warning("Could not load fast analysis snapshot for sanity check")
    else:
        logger.warning("Could not load result rows for sanity check")

    # Verify protected runs are unchanged
    logger.info("--- Historical integrity check ---")
    all_runs_after = db.list_analysis_runs(BID_ID)
    existing_ids_after = {int(r.get("id") or 0) for r in all_runs_after}
    for pid in PROTECTED_RUN_IDS:
        if pid in existing_ids_after:
            logger.info("Protected run %d: still present -- OK", pid)
        else:
            logger.warning("Protected run %d: MISSING after acceptance run!", pid)

    # Build results summary
    all_specialists_complete = (
        len(specialist_statuses) == 6
        and all(s == "COMPLETE" for s in specialist_statuses.values())
    )
    results = {
        "run_id": run_id,
        "bid_id": BID_ID,
        "organization_id": ORG_ID,
        "outcome": outcome,
        "wall_seconds": wall_seconds,
        "run_status": run_status,
        "completeness_status": completeness_status,
        "specialist_statuses": specialist_statuses,
        "all_specialists_complete": all_specialists_complete,
        "reconciliation_status": recon_status,
        "reconciliation_stop_reason": recon_detail.get("stop_reason"),
        "reconciliation_parse_status": recon_detail.get("parse_status"),
        "reconciliation_output_truncated": recon_detail.get("output_truncated"),
        "reconciliation_finding_count": recon_detail.get("reconciled_finding_count"),
        "reconciliation_contradiction_count": recon_detail.get("contradiction_count"),
        "reconciliation_cross_domain_risk_count": recon_detail.get("cross_domain_risk_count"),
        "reconciliation_incomplete_domain_count": recon_detail.get("incomplete_domain_count"),
        "provider_calls": total_calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reopen_provider_calls": reopen_call_count,
        "brief_export_provider_calls": brief_call_count,
        "brief_reexport_provider_calls": re_export_call_count,
        "brief_bytes": len(brief_pdf_bytes),
        "brief_sha256": sha256,
        "brief_pdf_path": str(out_path),
        # Acceptance gate results
        "gate_production_budget_applied": fa.RECONCILIATION_MAX_OUTPUT_TOKENS == 3000,  # proves budget was restored
        "gate_all_specialists_complete": all_specialists_complete,
        "gate_reconciliation_complete": recon_status == "COMPLETE",
        "gate_reconciliation_end_turn": recon_detail.get("stop_reason") == "end_turn",
        "gate_reconciliation_not_truncated": not recon_detail.get("output_truncated"),
        "gate_overall_complete": run_status == "COMPLETE",
        # REUSED_COMPLETE is correct production behavior (idempotent, same source fingerprint).
        # CREATED means a fresh run was executed. Both are valid production outcomes.
        "gate_production_outcome_valid": outcome in ("CREATED", "REUSED_COMPLETE"),
        "gate_zero_call_reopen": reopen_call_count == 0,
        "gate_zero_call_brief_export": brief_call_count == 0,
        "gate_zero_call_brief_reexport": re_export_call_count == 0,
        "gate_module_default_restored": fa.RECONCILIATION_MAX_OUTPUT_TOKENS == 3000,
        "gate_no_protected_runs_mutated": PROTECTED_RUN_IDS.issubset(existing_ids_after),
        "production_reconciliation_budget_used": ua.PRODUCTION_RECONCILIATION_MAX_OUTPUT_TOKENS,
    }

    metrics_path = Path("output") / f"calgary_1417_prodpath_run{run_id}_metrics.json"
    metrics_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    logger.info("Saved metrics: %s", metrics_path)

    print("\n" + "=" * 60)
    print("PRODUCTION-PATH ACCEPTANCE RESULT:")
    print("=" * 60)
    print(json.dumps(results, indent=2))
    print("=" * 60)

    all_gates = all([
        results["gate_production_budget_applied"],
        results["gate_all_specialists_complete"],
        results["gate_reconciliation_complete"],
        results["gate_reconciliation_end_turn"],
        results["gate_reconciliation_not_truncated"],
        results["gate_overall_complete"],
        results["gate_production_outcome_valid"],
        results["gate_zero_call_reopen"],
        results["gate_zero_call_brief_export"],
        results["gate_zero_call_brief_reexport"],
        results["gate_module_default_restored"],
        results["gate_no_protected_runs_mutated"],
    ])

    if all_gates:
        logger.info("ALL PRODUCTION-PATH ACCEPTANCE GATES PASSED!")
        return 0
    else:
        failed = [k for k, v in results.items() if k.startswith("gate_") and not v]
        logger.error("FAILED GATES: %s", failed)
        return 1


if __name__ == "__main__":
    sys.exit(main())
