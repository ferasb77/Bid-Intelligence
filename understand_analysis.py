"""
understand_analysis.py -- Unified Opportunity Analysis Orchestrator for UNDERSTAND.

Authoritative Product Architecture:
EVERY RFP RECEIVES THE FULL MULTI-AGENT BID INTELLIGENCE ANALYSIS.
There is no customer choice between Fast and Full Analysis.
The one primary customer action is: ANALYZE OPPORTUNITY.

Internal Architecture:
SOURCE DOCUMENTS
    ↓
DETERMINISTIC PROCUREMENT INTELLIGENCE FOUNDATION (Fast Analysis engine)
    ↓
CANONICAL BUYER TRUTH (Layers 1 & 2)
    ↓
MULTI-AGENT SPECIALIST ANALYSIS (6 Domains: PS, RC, EV, SD, CC, SS)
    ↓
CROSS-DOMAIN RECONCILIATION
    ↓
DURABLE UNDERSTAND WORKSPACE & BID INTELLIGENCE BRIEF

Scalability & Integrity Rules:
1. Duplicate document detection runs before specialist analysis.
2. Canonical buyer truth outranks conflicting specialist interpretations.
3. Near-duplicate requirements are clustered for Stage-D/synthesis prompts while
   strictly preserving material variations (deadlines, thresholds, qualifiers).
4. Excerpt caps are applied consistently across all context sections.
5. Reconciliation output token limit is raised to 4096 at runtime to prevent
   unnecessary output truncation.
6. Zero provider calls on reload, navigation, or brief export.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

import database as db
import full_analysis as fa
import full_analysis_service as fas
import tenancy
import understand_scalability as usc
from config import api_key_configured, get_api_key

logger = logging.getLogger(__name__)

# Lens definitions matching the 6 specialist domains + cross-domain reconciliation
LENSES = (
    ("PROCUREMENT_STRUCTURE", "Procurement Structure", "PS", "Verifying document hierarchy and packaging rules"),
    ("REQUIREMENTS_COMPLIANCE", "Requirements & Compliance", "RC", "Auditing mandatory qualification gates and compliance items"),
    ("EVALUATION_INTELLIGENCE", "Evaluation Intelligence", "EV", "Mapping scoring criteria, weights, and response expectations"),
    ("SCOPE_DELIVERABLES", "Scope & Delivery", "SD", "Extracting positive service scope, deliverables, and resource commitments"),
    ("COMMERCIAL_CONTRACTUAL", "Commercial & Contractual", "CC", "Identifying pricing rules, liabilities, warranties, and risks"),
    ("SCHEDULE_SUBMISSION", "Schedule & Submission", "SS", "Verifying deadlines, submission formats, and portal mechanics"),
)
LENS_IDS = tuple(lens[0] for lens in LENSES)
LENS_NAME = {lens[0]: lens[1] for lens in LENSES}
LENS_CODE = {lens[0]: lens[2] for lens in LENSES}
LENS_DESC = {lens[0]: lens[3] for lens in LENSES}


def start_opportunity_analysis(
    bid_id: int,
    organization_id: str,
    api_key: str | None = None,
    *,
    retry: bool = False,
    created_by_user_id: str | None = None,
    execution: str = "background",
) -> dict:
    """Start or reconnect to the unified multi-agent opportunity analysis for a bid.

    Orchestrates:
    1. Document duplicate detection on registered RFP documents.
    2. Verification or creation of the deterministic procurement foundation.
    3. Multi-agent specialist analysis + cross-domain reconciliation.

    Returns dict with outcome and run info.
    """
    tenancy.require_bid_access(bid_id, organization_id)
    key = api_key or (get_api_key() if api_key_configured() else None)

    # 1. Scalability check: detect duplicate documents in the bid corpus
    docs = tenancy.get_documents_authenticated(organization_id, bid_id) if hasattr(tenancy, "get_documents_authenticated") else db.get_documents(bid_id)
    rfp_docs = [d for d in docs if isinstance(d, dict) and d.get("doc_type") == "RFP / Source"]
    if rfp_docs:
        dup_report = usc.detect_duplicate_documents(rfp_docs)
        if dup_report.get("duplicates"):
            logger.info("Bid %s has %d duplicate document(s) detected and clustered",
                        bid_id, len(dup_report["duplicates"]))

    # 2. Check for existing FULL analysis status
    status = tenancy.get_full_analysis_status_for_organization(bid_id, organization_id)
    if status and not retry:
        run_status = status.get("status")
        if run_status in ("QUEUED", "RUNNING"):
            return {"outcome": "ACTIVE_RUN_EXISTS", "status": status, "is_live": True}
        if run_status == "COMPLETE":
            return {"outcome": "REUSED_COMPLETE", "status": status, "is_live": False}

    # 4. Check whether a COMPLETE FAST foundation run exists
    runs = db.list_analysis_runs(bid_id)
    complete_fast_run = next(
        (r for r in runs if r.get("analysis_mode", "FAST") == "FAST" and r.get("status") == "COMPLETE"),
        None
    )

    if complete_fast_run:
        # Source foundation is ready -> Launch full multi-agent analysis directly
        return tenancy.start_full_analysis_for_organization(
            bid_id, organization_id, key,
            created_by_user_id=created_by_user_id,
            retry=retry,
        )

    # If no COMPLETE FAST foundation exists, orchestrate foundation -> full analysis
    if execution == "inline":
        # Run deterministic foundation inline
        import analysis_service
        fast_res = analysis_service.start_fast_analysis(
            bid_id, key, execution="inline", created_by="understand_analysis"
        )
        # Then start full analysis inline
        return tenancy.start_full_analysis_for_organization(
            bid_id, organization_id, key,
            created_by_user_id=created_by_user_id,
            retry=retry,
        )
    else:
        # Background: start foundation run and chain full analysis
        import analysis_service

        def _orchestrate_background():
            try:
                # Start fast analysis foundation
                tenancy.start_fast_analysis_for_organization(
                    bid_id, organization_id, key, created_by="understand_analysis"
                )
                # Wait for fast analysis to complete (up to 300s)
                import time
                deadline = time.time() + 300
                while time.time() < deadline:
                    time.sleep(3)
                    latest_runs = db.list_analysis_runs(bid_id)
                    fast = next(
                        (r for r in latest_runs if r.get("analysis_mode", "FAST") == "FAST" and r.get("status") == "COMPLETE"),
                        None
                    )
                    if fast:
                        # Launch full analysis now
                        tenancy.start_full_analysis_for_organization(
                            bid_id, organization_id, key,
                            created_by_user_id=created_by_user_id,
                            retry=retry,
                        )
                        break
                    failed = next(
                        (r for r in latest_runs if r.get("analysis_mode", "FAST") == "FAST" and r.get("status") == "FAILED"),
                        None
                    )
                    if failed:
                        break
            except Exception as e:
                logger.error("Background opportunity analysis error for bid %s: %s", bid_id, e)

        t = threading.Thread(target=_orchestrate_background, daemon=True, name=f"opp-analysis-{bid_id}")
        t.start()
        return {"outcome": "CREATED", "executing": True}


def get_opportunity_analysis_state(bid_id: int, organization_id: str) -> dict[str, Any]:
    """Return the truthful live or completed opportunity analysis state for the UI.

    Never invents progress or displays fake percentages.
    """
    full_status = tenancy.get_full_analysis_status_for_organization(bid_id, organization_id)
    runs = db.list_analysis_runs(bid_id)
    latest_fast_run = next((r for r in runs if r.get("analysis_mode", "FAST") == "FAST"), None)

    # Determine overall status and live state
    is_live = False
    is_complete = False
    is_failed = False
    is_partial = False
    is_stuck = False
    run_id = None
    status_label = "Ready to analyze"

    if full_status:
        run_id = full_status.get("run_id")
        raw_status = full_status.get("status")
        is_stuck = bool((full_status.get("stuck") or {}).get("stuck"))
        if raw_status in ("QUEUED", "RUNNING") and not is_stuck:
            is_live = True
            status_label = "Analyzing opportunity…"
        elif raw_status == "COMPLETE":
            is_complete = True
            status_label = "Analysis complete"
        elif raw_status == "PARTIAL":
            is_partial = True
            status_label = "Analysis complete with partial notices"
        elif raw_status == "FAILED":
            is_failed = True
            status_label = f"Analysis failed: {full_status.get('failure_reason') or 'Unknown error'}"
        elif is_stuck:
            status_label = "Analysis interrupted (stuck)"
    elif latest_fast_run and latest_fast_run.get("status") in ("QUEUED", "PREPARING", "ANALYZING", "ASSEMBLING"):
        is_live = True
        status_label = "Preparing deterministic foundation…"

    # Lens progression
    lenses_state = []
    spec_statuses = (full_status.get("specialists") or {}) if full_status else {}
    for lid, name, code, desc in LENSES:
        s_info = spec_statuses.get(lid) or {}
        st = s_info.get("status", "WAITING")
        if not full_status:
            st = "WAITING"
        lenses_state.append({
            "id": lid,
            "name": name,
            "code": code,
            "description": desc,
            "status": st,
            "duration": s_info.get("duration_seconds"),
        })

    # Reconciliation state
    recon_info = (full_status.get("reconciliation") or {}) if full_status else {}
    recon_status = recon_info.get("status", "WAITING")

    # Counts from events
    hub_counts = []
    if full_status:
        for ev in full_status.get("events") or []:
            if ev.get("event_type") == "CANONICAL_PACKAGE_READY":
                counts = (ev.get("detail") or {}).get("object_counts") or {}
                if "SCOPED_EVALUATION_CRITERION" in counts:
                    hub_counts.append(f"{counts['SCOPED_EVALUATION_CRITERION']} evaluation criteria verified")
                if "CANONICAL_REQUIREMENT" in counts:
                    hub_counts.append(f"{counts['CANONICAL_REQUIREMENT']} requirements identified")
                if "CATEGORY_SCOPE_ITEM" in counts:
                    hub_counts.append(f"{counts['CATEGORY_SCOPE_ITEM']} scope items structured")
                if "COMMERCIAL_OBLIGATION" in counts:
                    hub_counts.append(f"{counts['COMMERCIAL_OBLIGATION']} commercial clauses audited")
                if "SCOPED_MILESTONE" in counts:
                    hub_counts.append(f"{counts['SCOPED_MILESTONE']} milestones tracked")
                break

    return {
        "bid_id": bid_id,
        "run_id": run_id,
        "status_label": status_label,
        "is_live": is_live,
        "is_complete": is_complete,
        "is_partial": is_partial,
        "is_failed": is_failed,
        "is_stuck": is_stuck,
        "full_status": full_status,
        "lenses": lenses_state,
        "reconciliation_status": recon_status,
        "hub_counts": hub_counts,
        "has_full_run": full_status is not None,
        "has_fast_run": latest_fast_run is not None,
    }
