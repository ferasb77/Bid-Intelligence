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
5. The reconciliation output token ceiling is PRODUCTION_RECONCILIATION_MAX_OUTPUT_TOKENS
   (8192). This is applied by the orchestrator around every service call so the
   customer-facing Analyze Opportunity path gets the same headroom as any
   commissioning tool. The full_analysis module default (3000) is a test-safety
   floor for isolated unit tests only -- it is NEVER the production value.
   Truncation detection remains fail-closed: if output exceeds even 8192 tokens
   the run is marked PARTIAL, not COMPLETE.
6. Zero provider calls on reload, navigation, or brief export.
"""
from __future__ import annotations

import contextlib
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

# ---------------------------------------------------------------------------
# Production reconciliation output budget
# ---------------------------------------------------------------------------
#: Single authoritative production ceiling for reconciliation output tokens.
#: Applied by the orchestrator around EVERY customer-facing full-analysis call.
#:
#: Rationale for 8192:
#:   Calgary Bid 1417 (run 50) produced 57 findings + 5 contradictions +
#:   8 cross-domain risks. That output completed with stop_reason=end_turn at
#:   13,238 total output tokens across 7 calls (specialists + reconciliation).
#:   At 3000 (module default) reconciliation truncates and the run is PARTIAL.
#:   At 4096 (run 49) it still truncated. 8192 provided sufficient headroom
#:   for run 50 to complete fully. Larger tenders are bounded by the existing
#:   scalability controls (duplicate-document detection, near-duplicate
#:   clustering, excerpt bounding) -- if those controls are insufficient,
#:   truncation still fails closed to PARTIAL.
#:
#: This constant MUST match what the commissioning script uses.
#: The full_analysis module default (3000) is NOT changed -- it is the
#: test-safety floor asserted by test_prompts_carry_explicit_output_bounds,
#: which calls fa.run_full_analysis() in isolation, bypassing this orchestrator.
PRODUCTION_RECONCILIATION_MAX_OUTPUT_TOKENS: int = 8192


@contextlib.contextmanager
def _production_recon_budget():
    """Context manager: set fa.RECONCILIATION_MAX_OUTPUT_TOKENS to the
    production ceiling for the duration of a service call, then restore it.

    Thread-safety note: fa.RECONCILIATION_MAX_OUTPUT_TOKENS is a module-level
    integer. For background (threaded) execution this is set in the spawned
    thread before the service call, which is safe because each analysis run
    owns its own thread and the module-level value is read at call time.
    For inline execution the caller holds the GIL during the assignment and
    the service call is synchronous.
    """
    original = fa.RECONCILIATION_MAX_OUTPUT_TOKENS
    fa.RECONCILIATION_MAX_OUTPUT_TOKENS = PRODUCTION_RECONCILIATION_MAX_OUTPUT_TOKENS
    try:
        yield
    finally:
        fa.RECONCILIATION_MAX_OUTPUT_TOKENS = original

# ---------------------------------------------------------------------------
# Unified opportunity analysis workflow steps (UNDERSTAND-UX1)
# ---------------------------------------------------------------------------
STEP_READY: str = "READY"
STEP_FOUNDATION_RUNNING: str = "FOUNDATION_RUNNING"
STEP_BASELINE_PRIMARY_AMBIGUOUS: str = "BASELINE_PRIMARY_AMBIGUOUS"
STEP_BASELINE_REVIEW_REQUIRED: str = "BASELINE_REVIEW_REQUIRED"
STEP_BASELINE_APPLYING: str = "BASELINE_APPLYING"
STEP_FULL_ANALYSIS_RUNNING: str = "FULL_ANALYSIS_RUNNING"
STEP_COMPLETE: str = "COMPLETE"
STEP_PARTIAL: str = "PARTIAL"
STEP_FAILED: str = "FAILED"

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


def resolve_baseline_documents(
    docs: list[dict],
    chosen_primary_id: int | None = None,
) -> tuple[list[int] | None, list[str] | str]:
    """Resolve document IDs and roles for baseline review without array-order guessing (UX1.1).

    Rules:
    - Default to all registered documents with doc_type == 'RFP / Source'.
    - If none have doc_type == 'RFP / Source', fall back to all registered docs.
    - If empty: return ([], []).
    - If exactly 1 document: assign role = 'primary'.
    - If chosen_primary_id is provided and valid:
        assign role = 'primary' to chosen document, 'supporting' (or explicit non-primary role) to the rest.
    - If multiple documents and chosen_primary_id is None:
        * Count documents with role == 'primary':
          - If exactly 1 document has role == 'primary': preserve it; others become 'supporting' (or explicit non-primary role).
          - If 0 documents have role == 'primary': return (None, "AMBIGUOUS_NO_PRIMARY").
          - If >1 documents have role == 'primary': return (None, "AMBIGUOUS_MULTIPLE_PRIMARIES").
    """
    if not docs:
        return [], []
    rfp_docs = [d for d in docs if isinstance(d, dict) and d.get("doc_type") == "RFP / Source"]
    if not rfp_docs:
        rfp_docs = [d for d in docs if isinstance(d, dict)]
    if not rfp_docs:
        return [], []

    valid_docs = [d for d in rfp_docs if "id" in d]
    if not valid_docs:
        return [], []

    if len(valid_docs) == 1:
        return [valid_docs[0]["id"]], ["primary"]

    if chosen_primary_id is not None and any(d["id"] == chosen_primary_id for d in valid_docs):
        doc_ids = []
        roles = []
        for d in valid_docs:
            doc_ids.append(d["id"])
            if d["id"] == chosen_primary_id:
                roles.append("primary")
            else:
                existing_role = d.get("role")
                if existing_role in ("supporting", "replacement", "attachment"):
                    roles.append(existing_role)
                else:
                    roles.append("supporting")
        return doc_ids, roles

    primary_docs = [d for d in valid_docs if d.get("role") == "primary"]
    if len(primary_docs) == 1:
        target_primary_id = primary_docs[0]["id"]
        doc_ids = []
        roles = []
        for d in valid_docs:
            doc_ids.append(d["id"])
            if d["id"] == target_primary_id:
                roles.append("primary")
            else:
                existing_role = d.get("role")
                if existing_role in ("supporting", "replacement", "attachment"):
                    roles.append(existing_role)
                else:
                    roles.append("supporting")
        return doc_ids, roles
    elif len(primary_docs) == 0:
        return None, "AMBIGUOUS_NO_PRIMARY"
    else:
        return None, "AMBIGUOUS_MULTIPLE_PRIMARIES"


def _get_bid_documents(bid_id: int, organization_id: str) -> list[dict]:
    try:
        if hasattr(tenancy, "get_documents_authenticated"):
            return tenancy.get_documents_authenticated(organization_id, bid_id)
        return db.get_documents(bid_id)
    except Exception:
        try:
            return db.get_documents(bid_id)
        except Exception:
            return []


def _continue_orchestration_after_fast(
    bid_id: int,
    organization_id: str,
    key: str | None,
    *,
    chosen_primary_doc_id: int | None = None,
    created_by_user_id: str | None = None,
    retry: bool = False,
    execution: str = "background",
) -> dict:
    """Step 2 & 3 in unified flow (B5, B6):
    Once the deterministic foundation (Fast Analysis) has completed:
    1. Check if bid's procurement_truth_status == 'governed'.
    2. If ungoverned:
       - Check for an active baseline review (analyzing, ready_for_review, reviewed).
       - If no active review exists (fresh bid or prior review failed), create a fresh review on retry/trigger.
       - If baseline review has pending proposals: yield cleanly with state BASELINE_REVIEW_REQUIRED.
       - If all proposals decided & at least one approved: apply baseline review.
    3. Once governed:
       - Run/launch Full Analysis with _production_recon_budget().
    """
    proc_state = db.get_bid_procurement_state(bid_id)
    truth_status = proc_state.get("procurement_truth_status", "ungoverned")

    if truth_status != "governed":
        reviews = db.get_procurement_update_reviews(bid_id)
        baseline_reviews = [r for r in reviews if r.get("review_kind") == "baseline"]

        # Look for an ACTIVE baseline review (analyzing, ready_for_review, reviewed)
        active_review = next(
            (r for r in baseline_reviews if r.get("status") in ("analyzing", "ready_for_review", "reviewed")),
            None
        )
        baseline_review = active_review

        created_fresh = False
        # If no active baseline review exists (fresh bid or prior review failed), create a fresh review
        if not baseline_review:
            docs = _get_bid_documents(bid_id, organization_id)
            doc_ids, doc_roles = resolve_baseline_documents(docs, chosen_primary_id=chosen_primary_doc_id)
            if doc_ids is None:
                return {
                    "outcome": "BASELINE_PRIMARY_AMBIGUOUS",
                    "step": STEP_BASELINE_PRIMARY_AMBIGUOUS,
                    "ambiguity_reason": doc_roles,
                    "eligible_docs": [d for d in docs if isinstance(d, dict) and d.get("doc_type") == "RFP / Source"] or docs,
                }
            if doc_ids:
                created = tenancy.create_procurement_update_review_for_organization(
                    bid_id, organization_id, "baseline", doc_ids, doc_roles,
                    buyer_update_type="Original RFP",
                )
                created_fresh = True
                baseline_review = created
                review_id = created.get("id") or created.get("review_id")
                if review_id:
                    try:
                        tenancy.propose_procurement_changes_for_organization(
                            bid_id, organization_id, review_id, api_key=key
                        )
                    except Exception as exc:
                        logger.error("Failed to propose baseline procurement changes for bid %s: %s", bid_id, exc)
                    reviews = db.get_procurement_update_reviews(bid_id)
                    baseline_review = next((r for r in reviews if r.get("id") == review_id), created)

        if baseline_review:
            b_status = baseline_review.get("status")
            if b_status == "analyzing":
                return {
                    "outcome": "CREATED" if created_fresh else "ACTIVE_RUN_EXISTS",
                    "step": STEP_FOUNDATION_RUNNING,
                    "review_id": baseline_review.get("id"),
                    "status_label": "Confirming procurement facts…",
                    "is_live": True,
                }
            if b_status in ("ready_for_review", "reviewed"):
                changes = db.get_procurement_changes(baseline_review["id"])
                pending = [c for c in changes if c.get("review_decision") == "pending"]
                approved = [c for c in changes if c.get("review_decision") == "approved"]
                if pending:
                    return {
                        "outcome": "BASELINE_REVIEW_REQUIRED",
                        "step": STEP_BASELINE_REVIEW_REQUIRED,
                        "review_id": baseline_review["id"],
                        "pending_count": len(pending),
                        "approved_count": len(approved),
                        "total_count": len(changes),
                    }
                elif approved:
                    # All decided and at least 1 approved -> Apply baseline review
                    try:
                        base_rev = baseline_review.get("base_procurement_revision", 1)
                        tenancy.apply_procurement_update_review_for_organization(
                            bid_id, organization_id, baseline_review["id"],
                            expected_base_revision=base_rev,
                            applied_by_user_id=created_by_user_id,
                        )
                    except Exception as exc:
                        logger.error("Failed to apply baseline review %s: %s", baseline_review["id"], exc)
                        return {
                            "outcome": "BASELINE_APPLY_FAILED",
                            "step": STEP_FAILED,
                            "error": str(exc),
                        }
                else:
                    return {
                        "outcome": "BASELINE_REVIEW_REQUIRED",
                        "step": STEP_BASELINE_REVIEW_REQUIRED,
                        "review_id": baseline_review["id"],
                        "pending_count": 0,
                        "approved_count": 0,
                        "total_count": len(changes),
                    }
            elif b_status == "failed":
                return {
                    "outcome": "BASELINE_FAILED",
                    "step": STEP_FAILED,
                    "error": baseline_review.get("review_note") or "Baseline analysis failed",
                }

    # Once baseline is applied (governed), proceed directly to Full Analysis!
    with _production_recon_budget():
        res = tenancy.start_full_analysis_for_organization(
            bid_id, organization_id, key,
            created_by_user_id=created_by_user_id,
            retry=retry,
            execution=execution,
        )
        if isinstance(res, dict) and "step" not in res:
            out = res.get("outcome")
            if out in ("CREATED", "ACTIVE_RUN_EXISTS"):
                res["step"] = STEP_FULL_ANALYSIS_RUNNING
            elif out == "REUSED_COMPLETE":
                res["step"] = STEP_COMPLETE
        return res


def apply_baseline_and_resume_analysis(
    bid_id: int,
    organization_id: str,
    review_id: int,
    *,
    user_id: str | None = None,
    api_key: str | None = None,
    approve_all_pending: bool = False,
    execution: str = "background",
) -> dict:
    """Approve pending proposals (if requested), apply the baseline review,
    and automatically resume Full Analysis (B8).
    """
    tenancy.require_bid_access(bid_id, organization_id)
    key = api_key or (get_api_key() if api_key_configured() else None)

    reviews = [r for r in tenancy.get_procurement_update_reviews_for_organization(bid_id, organization_id)
               if r.get("id") == review_id]
    if not reviews:
        raise ValueError(f"Review {review_id} not found for bid {bid_id}")
    review = reviews[0]

    changes = tenancy.get_procurement_changes_for_organization(bid_id, organization_id, review_id)
    if approve_all_pending:
        for c in changes:
            if c.get("review_decision") == "pending":
                tenancy.record_change_review_decision_for_organization(
                    bid_id, organization_id, c["id"], "approved", user_id
                )
        changes = tenancy.get_procurement_changes_for_organization(bid_id, organization_id, review_id)

    pending_count = sum(1 for c in changes if c.get("review_decision") == "pending")
    approved_count = sum(1 for c in changes if c.get("review_decision") == "approved")
    if pending_count > 0:
        raise ValueError(f"Cannot apply baseline review: {pending_count} proposal(s) still pending.")
    if approved_count < 1:
        raise ValueError("Cannot apply baseline review: at least one proposal must be approved.")

    base_rev = review.get("base_procurement_revision", 1)
    apply_result = tenancy.apply_procurement_update_review_for_organization(
        bid_id, organization_id, review_id,
        expected_base_revision=base_rev,
        applied_by_user_id=user_id,
    )

    # Immediately launch/resume Full Analysis!
    full_res = start_opportunity_analysis(
        bid_id, organization_id, api_key=key,
        created_by_user_id=user_id, execution=execution
    )
    return {
        "apply_result": apply_result,
        "analysis_result": full_res,
        "step": full_res.get("step") or STEP_FULL_ANALYSIS_RUNNING,
    }


def start_opportunity_analysis(
    bid_id: int,
    organization_id: str,
    api_key: str | None = None,
    *,
    retry: bool = False,
    created_by_user_id: str | None = None,
    execution: str = "background",
    chosen_primary_doc_id: int | None = None,
) -> dict:
    """Start or reconnect to the unified multi-agent opportunity analysis for a bid.

    Orchestrates (B5, B6):
    1. Document duplicate detection on registered RFP documents.
    2. Verification or creation of the deterministic procurement foundation (Fast Analysis).
    3. Baseline procurement review proposal and apply (governance).
    4. Multi-agent specialist analysis + cross-domain reconciliation (Full Analysis).

    Returns dict with outcome and run info.
    """
    tenancy.require_bid_access(bid_id, organization_id)
    key = api_key or (get_api_key() if api_key_configured() else None)

    # 1. Scalability check: detect duplicate documents in the bid corpus.
    docs = _get_bid_documents(bid_id, organization_id)
    rfp_docs = [d for d in docs if isinstance(d, dict) and d.get("doc_type") == "RFP / Source"]
    if rfp_docs:
        # detect_duplicate_documents expects (filename, content) tuples
        doc_tuples = [
            (d.get("name") or d.get("filename") or str(d.get("id", "")),
             d.get("content") or d.get("text") or d.get("raw_text") or "")
            for d in rfp_docs
            if isinstance(d, dict)
        ]
        if doc_tuples:
            try:
                dup_report = usc.detect_duplicate_documents(doc_tuples)
                if dup_report.get("duplicates"):
                    logger.info("Bid %s has %d duplicate document(s) detected and clustered",
                                bid_id, len(dup_report["duplicates"]))
            except Exception as exc:
                logger.warning("Duplicate detection skipped for bid %s: %s", bid_id, exc)

    # 2. Check for existing FULL analysis status
    status = tenancy.get_full_analysis_status_for_organization(bid_id, organization_id)
    if status and not retry:
        run_status = status.get("status")
        if run_status in ("QUEUED", "RUNNING") and not (status.get("stuck") or {}).get("stuck"):
            return {
                "outcome": "ACTIVE_RUN_EXISTS",
                "status": status,
                "is_live": True,
                "step": STEP_FULL_ANALYSIS_RUNNING,
            }
        if run_status == "COMPLETE":
            return {
                "outcome": "REUSED_COMPLETE",
                "status": status,
                "is_live": False,
                "step": STEP_COMPLETE,
            }

    # Fail closed upfront if baseline document primary selection is ambiguous
    doc_ids, doc_roles = resolve_baseline_documents(docs, chosen_primary_id=chosen_primary_doc_id)
    if doc_ids is None:
        proc_state = db.get_bid_procurement_state(bid_id)
        truth_status = proc_state.get("procurement_truth_status", "ungoverned")
        if truth_status != "governed":
            reviews = db.get_procurement_update_reviews(bid_id)
            baseline_reviews = [r for r in reviews if r.get("review_kind") == "baseline"]
            active_baseline = next(
                (r for r in baseline_reviews if r.get("status") in ("analyzing", "ready_for_review", "reviewed")),
                None
            )
            if not active_baseline:
                return {
                    "outcome": "BASELINE_PRIMARY_AMBIGUOUS",
                    "step": STEP_BASELINE_PRIMARY_AMBIGUOUS,
                    "ambiguity_reason": doc_roles,
                    "eligible_docs": [d for d in docs if isinstance(d, dict) and d.get("doc_type") == "RFP / Source"] or docs,
                }

    # 3. Check whether a COMPLETE FAST foundation run exists
    runs = db.list_analysis_runs(bid_id)
    complete_fast_run = next(
        (r for r in runs if r.get("analysis_mode", "FAST") == "FAST" and r.get("status") == "COMPLETE"),
        None
    )
    active_fast_run = next(
        (r for r in runs if r.get("analysis_mode", "FAST") == "FAST" and r.get("status") in ("QUEUED", "PREPARING", "ANALYZING", "ASSEMBLING")),
        None
    )

    if active_fast_run:
        return {
            "outcome": "ACTIVE_RUN_EXISTS",
            "status": active_fast_run,
            "is_live": True,
            "step": STEP_FOUNDATION_RUNNING,
        }

    if complete_fast_run:
        # Foundation complete -> proceed to baseline governance and full analysis
        return _continue_orchestration_after_fast(
            bid_id, organization_id, key,
            chosen_primary_doc_id=chosen_primary_doc_id,
            created_by_user_id=created_by_user_id,
            retry=retry,
            execution=execution,
        )

    # If no COMPLETE FAST foundation exists, orchestrate foundation -> baseline -> full analysis
    if execution == "inline":
        import analysis_service
        analysis_service.start_fast_analysis(
            bid_id, key, execution="inline", created_by="understand_analysis"
        )
        return _continue_orchestration_after_fast(
            bid_id, organization_id, key,
            chosen_primary_doc_id=chosen_primary_doc_id,
            created_by_user_id=created_by_user_id,
            retry=retry,
            execution="inline",
        )
    else:
        # Background: start foundation run and chain baseline + full analysis
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
                        _continue_orchestration_after_fast(
                            bid_id, organization_id, key,
                            chosen_primary_doc_id=chosen_primary_doc_id,
                            created_by_user_id=created_by_user_id,
                            retry=retry,
                            execution="background",
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
        return {"outcome": "CREATED", "executing": True, "step": STEP_FOUNDATION_RUNNING}


def get_opportunity_analysis_state(bid_id: int, organization_id: str) -> dict[str, Any]:
    """Return the truthful live or completed opportunity analysis state for the UI.

    Determines the current unified step across:
    FOUNDATION_RUNNING -> BASELINE_REVIEW_REQUIRED -> BASELINE_APPLYING ->
    FULL_ANALYSIS_RUNNING -> COMPLETE (or PARTIAL / FAILED / READY).

    Never invents progress or displays fake percentages.
    """
    try:
        full_status = tenancy.get_full_analysis_status_for_organization(bid_id, organization_id)
    except Exception:
        full_status = None

    try:
        runs = db.list_analysis_runs(bid_id)
    except Exception:
        runs = []

    try:
        proc_state = tenancy.get_procurement_state_for_organization(bid_id, organization_id)
    except Exception:
        proc_state = {"procurement_truth_status": "ungoverned", "procurement_revision": 1}

    truth_status = proc_state.get("procurement_truth_status", "ungoverned")

    try:
        reviews = tenancy.get_procurement_update_reviews_for_organization(bid_id, organization_id)
    except Exception:
        reviews = []
    baseline_reviews = [r for r in reviews if r.get("review_kind") == "baseline"]
    active_baseline = next(
        (r for r in baseline_reviews if r.get("status") in ("analyzing", "ready_for_review", "reviewed")),
        None
    )
    baseline_review = active_baseline or (baseline_reviews[0] if baseline_reviews else None)

    latest_fast_run = next((r for r in runs if r.get("analysis_mode", "FAST") == "FAST"), None)

    docs = _get_bid_documents(bid_id, organization_id)
    rfp_docs = [d for d in docs if isinstance(d, dict) and d.get("doc_type") == "RFP / Source"]
    target_docs = rfp_docs or docs
    doc_ids, doc_roles = resolve_baseline_documents(target_docs)
    eligible_docs = [d for d in target_docs if isinstance(d, dict)]

    # Determine overall status and live state
    is_live = False
    is_complete = False
    is_failed = False
    is_partial = False
    is_stuck = False
    run_id = None
    step = STEP_READY
    status_label = "Ready to analyze"
    baseline_changes: list[dict] = []
    pending_changes_count = 0
    approved_changes_count = 0

    if full_status:
        run_id = full_status.get("run_id")
        raw_status = full_status.get("status")
        is_stuck = bool((full_status.get("stuck") or {}).get("stuck"))
        if raw_status in ("QUEUED", "RUNNING") and not is_stuck:
            is_live = True
            step = STEP_FULL_ANALYSIS_RUNNING
            status_label = "Analyzing opportunity across six intelligence lenses…"
        elif raw_status == "COMPLETE":
            is_complete = True
            step = STEP_COMPLETE
            status_label = "Opportunity intelligence current"
        elif raw_status == "PARTIAL":
            is_partial = True
            step = STEP_PARTIAL
            status_label = "Opportunity intelligence complete (partial notices)"
        elif raw_status == "FAILED":
            is_failed = True
            step = STEP_FAILED
            status_label = f"Analysis failed: {full_status.get('failure_reason') or 'Unknown error'}"
        elif is_stuck:
            is_stuck = True
            step = STEP_FAILED
            status_label = "Analysis interrupted (stuck)"
    elif latest_fast_run and latest_fast_run.get("status") in ("QUEUED", "PREPARING", "ANALYZING", "ASSEMBLING"):
        is_live = True
        step = STEP_FOUNDATION_RUNNING
        status_label = "Analyzing procurement documents…"
    elif latest_fast_run and latest_fast_run.get("status") == "FAILED":
        is_failed = True
        step = STEP_FAILED
        status_label = f"Procurement analysis failed: {latest_fast_run.get('failure_reason') or 'Unknown error'}"
    elif truth_status != "governed":
        if active_baseline:
            b_status = active_baseline.get("status")
            if b_status == "analyzing":
                is_live = True
                step = STEP_FOUNDATION_RUNNING
                status_label = "Confirming procurement facts…"
            elif b_status in ("ready_for_review", "reviewed"):
                try:
                    baseline_changes = tenancy.get_procurement_changes_for_organization(
                        bid_id, organization_id, active_baseline["id"]
                    )
                except Exception:
                    baseline_changes = []
                pending = [c for c in baseline_changes if c.get("review_decision") == "pending"]
                approved = [c for c in baseline_changes if c.get("review_decision") == "approved"]
                pending_changes_count = len(pending)
                approved_changes_count = len(approved)
                step = STEP_BASELINE_REVIEW_REQUIRED
                if pending:
                    status_label = "Confirm procurement facts to continue"
                else:
                    status_label = "Procurement facts ready to apply"
        elif doc_ids is None:
            step = STEP_BASELINE_PRIMARY_AMBIGUOUS
            status_label = "Primary solicitation document selection required"
        elif baseline_review and baseline_review.get("status") == "failed":
            is_failed = True
            step = STEP_FAILED
            status_label = f"Baseline analysis failed: {baseline_review.get('review_note') or 'Unknown error'}"
        elif latest_fast_run and latest_fast_run.get("status") == "COMPLETE":
            step = STEP_READY
            status_label = "Ready to confirm procurement facts"
        else:
            step = STEP_READY
            status_label = "Ready to analyze opportunity"
    else:
        step = STEP_READY
        status_label = "Ready to analyze opportunity"

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
        "step": step,
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
        "procurement_state": proc_state,
        "baseline_review": baseline_review,
        "baseline_changes": baseline_changes,
        "pending_changes_count": pending_changes_count,
        "approved_changes_count": approved_changes_count,
        "latest_fast_run": latest_fast_run,
        "eligible_docs": eligible_docs,
        "ambiguity_reason": doc_roles if doc_ids is None else None,
    }
