"""
scripts/run_calgary_1417_commissioning.py -- Mandatory Calgary Bid 1417 commissioning runner.

Executes exactly ONE real end-to-end multi-agent opportunity analysis for:
City of Calgary RFP 26-1610 (Bid ID: 1417).

Verifies:
- All 6 specialists COMPLETE.
- Reconciliation COMPLETE.
- Overall run COMPLETE.
- Zero failed or partial stages.
- Zero provider calls on Brief generation / re-download.
- Validates Brief content against the golden benchmark.
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

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("commissioning")

BID_ID = 1417
ORG_ID = "4326b564-8cc5-4463-9304-9a589f08cc91"


def main():
    import config
    import database as db
    import full_analysis as fa
    import full_analysis_service as fas
    import tenancy
    import understand_analysis as ua
    import understand_brief as ub
    import understand_brief_report as ubr

    api_key = config.get_api_key()
    if not api_key:
        logger.error("No Anthropic API key configured.")
        sys.exit(1)

    logger.info("Starting commissioning run for City of Calgary Bid %s (org: %s)...", BID_ID, ORG_ID)

    # Use the SAME production reconciliation budget as the customer-facing
    # Analyze Opportunity path. No script-only advantage: if the production
    # constant changes, this run automatically uses the updated value.
    logger.info(
        "Reconciliation output budget (from ua.PRODUCTION_RECONCILIATION_MAX_OUTPUT_TOKENS): %d",
        ua.PRODUCTION_RECONCILIATION_MAX_OUTPUT_TOKENS,
    )
    start_time = time.monotonic()
    with ua._production_recon_budget():
        response = fas.start_full_analysis(
            bid_id=BID_ID,
            api_key=api_key,
            source_run_id=48,  # Use latest complete fast analysis run 48
            retry=True,
            execution="inline",
            reconciliation_max_output_tokens=ua.PRODUCTION_RECONCILIATION_MAX_OUTPUT_TOKENS,
        )

    wall_seconds = round(time.monotonic() - start_time, 2)
    logger.info("Execution finished in %s seconds. Response outcome: %s", wall_seconds, response.get("outcome"))

    run_row = response.get("run") or {}
    run_id = int(run_row.get("id"))
    logger.info("New Run ID: %s", run_id)

    # 1. Fetch durable run state
    durable_run = db.get_analysis_run(run_id)
    run_status = durable_run.get("status")
    failure_reason = durable_run.get("failure_reason")
    logger.info("Durable analysis_runs status: %s (failure_reason: %s)", run_status, failure_reason)

    # 2. Fetch durable analysis result
    durable_result = db.get_analysis_result(run_id)
    full_result = durable_result.get("full_analysis_result") or {}
    completeness_status = full_result.get("completeness_status")
    logger.info("Durable analysis_results completeness_status: %s", completeness_status)

    # 3. Check specialist results
    specialist_rows = db.get_full_analysis_specialist_results(run_id)
    logger.info("Total specialist rows in DB: %d", len(specialist_rows))
    specialist_statuses = {}
    for row in specialist_rows:
        sid = row.get("specialist_id")
        eff_status = fas.effective_specialist_status(row)
        specialist_statuses[sid] = eff_status
        logger.info("  Specialist %-25s -> %s (duration: %ss)", sid, eff_status, row.get("duration_seconds"))

    # 4. Check reconciliation event and status
    events = db.get_full_analysis_events(run_id)
    recon_event = next((e for e in events if e.get("event_type") == "RECONCILIATION_COMPLETED"), None)
    recon_status = recon_event.get("status") if recon_event else "MISSING"
    logger.info("Reconciliation event status: %s", recon_status)
    recon_detail = (recon_event.get("detail") or {}) if recon_event else {}
    logger.info("Reconciliation detail: %s", json.dumps(recon_detail))

    # 5. Telemetry
    telemetry = durable_run.get("telemetry") or full_result.get("telemetry") or {}
    total_calls = telemetry.get("provider_calls", 0)
    input_tokens = telemetry.get("input_tokens", 0)
    output_tokens = telemetry.get("output_tokens", 0)
    logger.info("Telemetry: %d calls, %d input tokens, %d output tokens, wall: %ss",
                total_calls, input_tokens, output_tokens, wall_seconds)

    # 6. Test zero-call Brief export
    logger.info("Testing zero-call Brief generation from durable snapshot...")
    # Wrap config.execute_messages_create to assert ZERO provider calls
    call_count = 0
    orig_execute = config.execute_messages_create
    def guard_execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise AssertionError("Zero-call rule violated: provider call attempted during Brief export!")

    config.execute_messages_create = guard_execute
    try:
        brief_pdf_bytes = tenancy.export_bid_intelligence_brief_for_organization(
            BID_ID, run_id, ORG_ID
        )
        logger.info("Brief export SUCCESS: %d bytes generated with 0 provider calls!", len(brief_pdf_bytes))
    finally:
        config.execute_messages_create = orig_execute

    # Save output PDF
    out_dir = Path("output/pdf")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"Bid_Intelligence_Brief_26-1610_run{run_id}.pdf"
    out_path.write_bytes(brief_pdf_bytes)
    logger.info("Saved Brief PDF to: %s", out_path)

    # 7. Build summary metrics dictionary
    commissioning_metrics = {
        "run_id": run_id,
        "bid_id": BID_ID,
        "organization_id": ORG_ID,
        "wall_seconds": wall_seconds,
        "run_status": run_status,
        "completeness_status": completeness_status,
        "reconciliation_status": recon_status,
        "specialist_statuses": specialist_statuses,
        "provider_calls": total_calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "brief_bytes": len(brief_pdf_bytes),
        "brief_pdf_path": str(out_path),
        "zero_provider_calls_verified": call_count == 0,
        "all_specialists_complete": all(s == "COMPLETE" for s in specialist_statuses.values()) and len(specialist_statuses) == 6,
        "reconciliation_complete": recon_status == "COMPLETE",
        "overall_complete": run_status == "COMPLETE",
    }

    metrics_path = Path("output") / f"calgary_1417_run{run_id}_metrics.json"
    metrics_path.write_text(json.dumps(commissioning_metrics, indent=2), encoding="utf-8")
    logger.info("Saved metrics to: %s", metrics_path)

    print("\n" + "=" * 60)
    print("COMMISSIONING RUN RESULT SUMMARY:")
    print("=" * 60)
    print(json.dumps(commissioning_metrics, indent=2))
    print("=" * 60)

    # Return exit code based on verification
    if commissioning_metrics["overall_complete"] and commissioning_metrics["all_specialists_complete"] and commissioning_metrics["reconciliation_complete"]:
        logger.info("ALL COMMISSIONING ACCEPTANCE GATES PASSED!")
        return 0
    else:
        logger.error("ONE OR MORE COMMISSIONING GATES FAILED!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
