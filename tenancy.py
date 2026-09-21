"""
tenancy.py — organization/tenant context and tenant-aware bid primitives.

Phase 8 remediation package 2. Introduces the stable application-facing
identity contract (AuthContext) the rest of the application should
eventually depend on instead of passing arbitrary user/org IDs around
independently, plus the deterministic server-side logic that resolves a
Supabase Auth user into that context via `organization_members`.

This module intentionally does NOT enforce anything by itself -- no RLS
policy exists yet (Phase 8 remediation package 3), and no code path in the
current commissioned application calls into this module yet (package 3
will wire it in once a real user/membership exists). It exists so the
schema, the identity contract, and the tenant-scoped data-access primitives
are in place and tested ahead of that switch-over -- see instruction 11's
explicit requirement not to lock the existing internal app out before a
real member is provisioned.

All reads here go through database.py's existing service-role client
(`database.get_client()`), the same as every other current server-side
database operation -- resolving "which organization does this
already-authenticated user belong to" is itself a privileged, internal
lookup, not something that should depend on a not-yet-written RLS policy.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

import auth_client
import database as db
from database import format_requirement_payload

# ── Roles ─────────────────────────────────────────────────────────────────
VALID_ROLES = ("owner", "admin", "member")


# ── AuthContext contract ─────────────────────────────────────────────────
@dataclass(frozen=True)
class AuthContext:
    """The one stable identity+tenancy structure downstream application
    code should eventually depend on. Nothing beyond what package 2 needs:
    a user, the single organization they are currently operating as, and
    their role in it. No permissions model beyond `role` itself."""
    user_id: str
    email: str
    organization_id: str
    organization_name: str
    role: str


@dataclass(frozen=True)
class NoOrganizationAccess:
    """Zero memberships for this user -- the required fail-closed result
    (instruction 9). Callers must not fall back to any default
    organization."""
    user_id: str


@dataclass(frozen=True)
class OrganizationSelectionRequired:
    """More than one membership exists for this user. Callers must not
    silently pick one -- present `candidates` for an explicit selection
    (instruction 9: 'do not overbuild the selector UI yet' -- this package
    only guarantees the data shape a selector needs, not the UI itself)."""
    user_id: str
    candidates: list[dict] = field(default_factory=list)
    # each candidate: {"organization_id": str, "organization_name": str, "role": str}


OrganizationResolution = AuthContext | NoOrganizationAccess | OrganizationSelectionRequired


def resolve_organization_context(user_id: str, email: str) -> OrganizationResolution:
    """Deterministic server-side resolution: auth user_id -> memberships ->
    organization -> role. See instruction 9 for the required zero/one/many
    behavior; this function returns the typed result for each case, and
    does not choose for the caller when more than one membership exists."""
    sb = db.get_client()
    memberships = (
        sb.table("organization_members")
        .select("organization_id, role")
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    )

    if not memberships:
        return NoOrganizationAccess(user_id=user_id)

    org_ids = [m["organization_id"] for m in memberships]
    orgs = (
        sb.table("organizations")
        .select("id, name")
        .in_("id", org_ids)
        .execute()
        .data
        or []
    )
    org_names = {o["id"]: o["name"] for o in orgs}

    if len(memberships) == 1:
        m = memberships[0]
        return AuthContext(
            user_id=user_id,
            email=email,
            organization_id=m["organization_id"],
            organization_name=org_names.get(m["organization_id"], ""),
            role=m["role"],
        )

    return OrganizationSelectionRequired(
        user_id=user_id,
        candidates=[
            {
                "organization_id": m["organization_id"],
                "organization_name": org_names.get(m["organization_id"], ""),
                "role": m["role"],
            }
            for m in memberships
        ],
    )


# ── Tenant-aware bid primitives ──────────────────────────────────────────
# Deliberately separate names from database.py's existing get_all_bids() /
# get_bid() / create_bid() -- those remain unchanged, unscoped compatibility
# wrappers the current commissioned internal app keeps using (instruction
# 11/12) until package 3 switches the product over to enforced authenticated
# access. New code written against an AuthContext should use these instead.

def list_bids_for_organization(organization_id: str) -> list[dict]:
    """The organization-scoped equivalent of database.get_all_bids() --
    same per-bid req/task rollup, filtered to one organization."""
    sb = db.get_client()
    bids = (
        sb.table("bids")
        .select("*")
        .eq("organization_id", organization_id)
        .order("submission_deadline")
        .execute()
        .data
        or []
    )
    for b in bids:
        b["id"] = int(b["id"])
        reqs = (sb.table("requirements").select("id,status").eq("bid_id", b["id"])
                .eq("lifecycle_status", "active").execute().data or [])
        tasks = sb.table("tasks").select("id,status").eq("bid_id", b["id"]).execute().data or []
        b["req_count"] = len(reqs)
        b["req_done"] = sum(1 for r in reqs if r["status"] == "Complete")
        b["task_count"] = len(tasks)
        b["task_done"] = sum(1 for t in tasks if t["status"] == "Complete")
    return bids


def get_bid_for_organization(bid_id: int, organization_id: str) -> dict | None:
    """Fetch a bid only if it belongs to the given organization. A bid_id
    that exists but belongs to a different organization returns None --
    the same shape as 'not found', not a distinguishable error, so callers
    cannot use response shape to probe for the existence of other
    organizations' bid IDs."""
    sb = db.get_client()
    rows = (
        sb.table("bids")
        .select("*")
        .eq("id", bid_id)
        .eq("organization_id", organization_id)
        .execute()
        .data
    )
    return rows[0] if rows else None


def create_bid_for_organization(data: dict, organization_id: str) -> int | None:
    """The organization-scoped equivalent of database.create_bid(). Unlike
    database.create_bid(), organization_id is a required, explicit
    argument -- there is no default, and this function will not silently
    fall back to the legacy 'emg-internal' organization (instruction 12).
    A caller with no resolved AuthContext has no organization_id to pass
    and cannot call this function at all, which is the intended fail-closed
    shape until a real authenticated/tenant-aware create path exists."""
    if not organization_id:
        raise ValueError("create_bid_for_organization requires an explicit organization_id")
    sb = db.get_client()
    clean = {k: data.get(k) for k in
             ["title", "client", "file_number", "stage", "sensitivity", "owner",
              "value_cad", "submission_deadline", "clarification_deadline", "notes"]}
    clean["organization_id"] = organization_id
    rows = sb.table("bids").insert(clean).execute().data
    row = rows[0] if rows else None
    return int(row["id"]) if row else None


# ── Privileged-operation authorization boundary (Phase 8 remediation ────
#    package 3, instructions 16-18) ──────────────────────────────────────
# These functions are the application-layer authorization gate in front of
# privileged, service-role-executed operations (starting a Fast Analysis
# run; regenerating/retrieving a report). They exist as DEFENSE IN DEPTH,
# independent of the migration 008 RLS policies: analysis_runs/
# analysis_results/bid_briefs are deliberately NOT authenticated-writable
# under RLS at all (category B, server-write-only -- see migration 008's
# own comments), so a user-initiated request to create one of those rows
# can *only* ever happen through this explicit check, never by a client
# request that RLS might otherwise have permitted. The shape is always:
#   authenticated user -> verify access to bid -> authorize operation ->
#   privileged server/background action
# never "user supplied bid ID -> privileged operation executes" without
# the verification step in between (instruction 16).

class AccessDeniedError(Exception):
    """Raised when an authenticated caller's organization does not own the
    target bid. No privileged operation may proceed past this exception --
    every function below raises it BEFORE touching analysis_service.py or
    any privileged write."""


def authorize_bid_access(bid_id: int, organization_id: str) -> bool:
    """True iff bid_id belongs to organization_id. A thin, explicit wrapper
    around get_bid_for_organization() -- kept as its own named function so
    the privileged-operation call sites below read as an authorization
    check, not an incidental side effect of a data fetch."""
    return get_bid_for_organization(bid_id, organization_id) is not None


def require_bid_access(bid_id: int, organization_id: str) -> None:
    """Raises AccessDeniedError, doing nothing else, if organization_id
    does not own bid_id. Call this FIRST, before any privileged action."""
    if not authorize_bid_access(bid_id, organization_id):
        raise AccessDeniedError(
            f"organization {organization_id} does not have access to bid {bid_id}"
        )


def start_fast_analysis_for_organization(
    bid_id: int, organization_id: str, api_key: str, created_by: str | None = None
) -> dict:
    """Authorization boundary in front of analysis_service.start_fast_analysis()
    (instruction 17). Verifies bid_id belongs to organization_id BEFORE any
    analysis_runs row is created and before any LLM call is made -- an
    unauthorized call raises AccessDeniedError and creates nothing,
    starts nothing. Fast Analysis itself (analysis_service.py,
    fast_analysis.py) is completely untouched; this function only wraps
    its existing, frozen entry point."""
    require_bid_access(bid_id, organization_id)
    import analysis_service
    return analysis_service.start_fast_analysis(bid_id, api_key, created_by=created_by)


def get_report_for_organization(bid_id: int, run_id: int, organization_id: str) -> bytes:
    """Authorization boundary in front of analysis_service.regenerate_report()
    (instruction 18). Verifies the caller's organization owns bid_id, AND
    that run_id actually belongs to bid_id (so a guessed/adjacent run_id
    from a DIFFERENT bid the caller legitimately owns cannot be used to
    read a run that in fact belongs to someone else's bid) -- both checks
    happen before any report bytes are read or regenerated."""
    require_bid_access(bid_id, organization_id)
    run = db.get_analysis_run(run_id)
    if not run or int(run.get("bid_id")) != int(bid_id):
        raise AccessDeniedError(f"run {run_id} does not belong to bid {bid_id}")
    import analysis_service
    return analysis_service.regenerate_report(run_id)


def get_raw_snapshot_report_for_organization(
    bid_id: int, run_id: int, organization_id: str, buyer_intelligence: dict | None = None
) -> bytes:
    """Authorization boundary in front of
    analysis_service.regenerate_report_from_raw_snapshot() -- the raw-
    FastAnalysisResult-snapshot regeneration path added for durability.
    Same two checks as get_report_for_organization() above, in the same
    order, before any privileged (service-role) read: the caller's
    organization must own bid_id, AND run_id must actually belong to
    bid_id (never trust a guessed/adjacent run_id from a different bid the
    caller legitimately owns). This is the only sanctioned way for
    request-scoped/interactive code to reach the raw snapshot -- it must
    never call analysis_service.regenerate_report_from_raw_snapshot() or
    database.get_analysis_result() directly."""
    require_bid_access(bid_id, organization_id)
    run = db.get_analysis_run(run_id)
    if not run or int(run.get("bid_id")) != int(bid_id):
        raise AccessDeniedError(f"run {run_id} does not belong to bid {bid_id}")
    import analysis_service
    return analysis_service.regenerate_report_from_raw_snapshot(run_id, buyer_intelligence=buyer_intelligence)


def analyze_section_for_organization(
    bid_id: int, section_id: int, section_text: str, mapped_requirement_ids: list[int],
    organization_id: str, user_id: str | None = None,
) -> dict:
    """Authorization boundary in front of section_analyzer.analyze_section()
    -- the Section Analyzer's own model-invoking action, gated exactly like
    start_fast_analysis_for_organization/get_raw_snapshot_report_for_organization
    above (organization ownership of bid_id, AND section_id actually
    belongs to bid_id, checked before any privileged read or model call).
    `section_text` must be the caller's CURRENT editor text -- this
    function does not re-fetch section content from the database (see
    section_analyzer.analyze_section's own docstring)."""
    require_bid_access(bid_id, organization_id)
    section = db.get_outline(bid_id)
    section = next((s for s in section if int(s["id"]) == int(section_id)), None)
    if not section:
        raise AccessDeniedError(f"section {section_id} does not belong to bid {bid_id}")
    import section_analyzer
    return section_analyzer.analyze_section(
        bid_id, section, section_text, mapped_requirement_ids, created_by_user_id=user_id)


def upload_document_for_organization(
    bid_id: int, organization_id: str, filename: str, file_bytes: bytes,
    doc_type: str = "RFP / Source", owner: str | None = None, doc_id: int | None = None,
):
    """Authorization boundary in front of database.save_upload() (final
    interactive-surface cutover pass, package 3). `documents` has no
    authenticated write policy in migration 008 -- reads are category A
    (RLS-gated), but writes, like Storage itself, remain server-only by
    that migration's own already-live, deliberate design (category B) and
    are explicitly out of scope for this pass (Storage/report-object
    authorization is Package 4). This wrapper does not touch Storage or
    save_upload()'s own logic at all; it only adds the missing explicit
    tenant-authorization check immediately before the privileged call, so
    the remaining service-role use is authorization-gated rather than a
    bare, ungated convenience call."""
    require_bid_access(bid_id, organization_id)
    return db.save_upload(bid_id, filename, file_bytes, doc_type=doc_type, owner=owner, doc_id=doc_id)


def set_document_mandatory_for_organization(
    bid_id: int, organization_id: str, doc_id: int, mandatory: int
) -> None:
    """Authorization boundary in front of database.upsert_document() for the
    single narrow field write pages/stage_submit.py performs (resolving an
    UNKNOWN mandatory-document classification). Same rationale as
    upload_document_for_organization() above: `documents` writes stay
    server-side under the currently-live RLS policy set, so this is a
    privileged operation, tenant-authorized immediately before the call."""
    require_bid_access(bid_id, organization_id)
    db.upsert_document({"id": doc_id, "mandatory": mandatory})


def create_document_record_for_organization(
    bid_id: int, organization_id: str, data: dict
) -> None:
    """Authorization boundary in front of database.upsert_document() for
    creating expected-document checklist rows (no file bytes -- the
    RFP-extraction review screen's per-item submission checklist). Same
    `documents`-stays-server-side rationale as the two functions above."""
    require_bid_access(bid_id, organization_id)
    db.upsert_document(data)


def save_bid_brief_for_organization(
    bid_id: int, organization_id: str, data: dict
) -> None:
    """Authorization boundary in front of database.upsert_bid_brief().
    `bid_briefs` is category B (select-only via RLS; writes stay
    server-side alongside the analysis pipeline that normally produces
    them) -- tenant-authorized immediately before the privileged call.

    NOTE (migration 010): this remains the intake-wizard's own write path
    (app.py's RFP-extraction review screen, synthesize_bid_brief() ->
    save_bid_brief_for_organization()) -- a brand-new bid has no
    procurement-revision history yet, so its first bid_briefs write is
    not "divergence" the way Fast Analysis's REPEATED unconditional
    overwrite was. Fast Analysis itself no longer calls this path at all
    (see analysis_service.py) -- bid_briefs is a governed projection,
    rebuilt only inside apply_procurement_update_review()/
    resolve_procurement_conflict()'s own transaction from that point
    forward."""
    require_bid_access(bid_id, organization_id)
    db.upsert_bid_brief(data)


# ── Procurement Revision & Addendum Governance (migration 010) ─────────────
# Every function below is an authorization boundary in front of one of
# database.py's governed RPC wrappers -- require_bid_access() runs FIRST,
# before any privileged/service-role call, exactly like every other
# wrapper in this section. The RPCs themselves additionally re-validate
# the actor belongs to the target organization (defense in depth, per
# migration 010's own design) -- this wrapper is the primary application-
# level gate, not a decorative one.

def get_procurement_state_for_organization(bid_id: int, organization_id: str) -> dict:
    require_bid_access(bid_id, organization_id)
    return db.get_bid_procurement_state(bid_id)


def get_procurement_update_reviews_for_organization(bid_id: int, organization_id: str) -> list[dict]:
    require_bid_access(bid_id, organization_id)
    return db.get_procurement_update_reviews(bid_id)


def get_procurement_changes_for_organization(bid_id: int, organization_id: str, review_id: int) -> list[dict]:
    require_bid_access(bid_id, organization_id)
    changes = db.get_procurement_changes(review_id)
    # Defense in depth: never return a change row that doesn't actually
    # belong to this bid, even if review_id were somehow mismatched.
    return [c for c in changes if int(c.get("bid_id", -1)) == int(bid_id)]


def get_procurement_conflicts_for_organization(
    bid_id: int, organization_id: str, status: str | None = None
) -> list[dict]:
    require_bid_access(bid_id, organization_id)
    return db.get_procurement_conflicts(bid_id, status=status)


def create_procurement_update_review_for_organization(
    bid_id: int, organization_id: str, review_kind: str,
    document_ids: list[int], document_roles: list[str],
    buyer_update_type: str | None = None, buyer_issued_date: str | None = None,
    conflict_id: int | None = None, idempotency_key: str | None = None,
) -> dict:
    require_bid_access(bid_id, organization_id)
    return db.create_procurement_update_review(
        bid_id, organization_id, review_kind, document_ids, document_roles,
        buyer_update_type=buyer_update_type, buyer_issued_date=buyer_issued_date,
        conflict_id=conflict_id, idempotency_key=idempotency_key,
    )


def propose_procurement_changes_for_organization(
    bid_id: int, organization_id: str, review_id: int, api_key: str | None = None
) -> list[dict]:
    """Authorization boundary in front of the change-proposal analysis
    step (analyst.propose_procurement_changes() -- pure LLM-proposal
    function, never writes to the database itself). This wrapper is what
    actually persists the resulting proposals as pending
    procurement_changes rows and transitions the review to
    'ready_for_review' -- the LLM function itself has no database access
    at all (see analyst.py)."""
    require_bid_access(bid_id, organization_id)
    reviews = [r for r in db.get_procurement_update_reviews(bid_id)
               if r["id"] == review_id and int(r.get("bid_id", -1)) == int(bid_id)]
    if not reviews:
        raise AccessDeniedError(f"review {review_id} does not belong to bid {bid_id}")
    review = reviews[0]
    review_docs = db.get_client().table("procurement_update_review_documents").select(
        "document_id,role"
    ).eq("review_id", review_id).execute().data or []
    documents = db.get_documents(bid_id)
    docs_by_id = {d["id"]: d for d in documents}
    review_documents = []
    for rd in review_docs:
        doc = docs_by_id.get(rd["document_id"])
        if not doc:
            continue
        storage_path = doc.get("storage_path")
        file_bytes = db.download_file(storage_path) if storage_path else None
        text = ""
        if file_bytes:
            from extractor import extract_text_from_file
            text = extract_text_from_file(file_bytes, doc["name"])
        review_documents.append({
            "document_id": doc["id"], "filename": doc["name"],
            "content_hash": doc.get("content_hash"), "role": rd["role"], "text": text,
        })

    current_requirements = db.get_requirements(bid_id)
    bid = db.get_bid(bid_id)
    # analyst.propose_procurement_changes is a pure LLM function with no
    # database access -- it only ever knows a requirement by its
    # human-readable req_id (entity_id), never the internal bigint primary
    # key. Resolving that to target_requirement_id is this wrapper's job:
    # without it, apply_procurement_update_review()'s MODIFIED/SUPERSEDED/
    # REMOVED/UNCHANGED branches (which all key off target_requirement_id)
    # would silently no-op on every approved change against an EXISTING
    # requirement.
    req_id_to_pk = {r.get("req_id"): r.get("id") for r in current_requirements if r.get("req_id")}

    try:
        import analyst
        proposals = analyst.propose_procurement_changes(
            review_documents=review_documents,
            current_requirements=current_requirements,
            bid_info=bid or {},
            buyer_update_type=review.get("buyer_update_type") or "Original RFP",
        )

        rows = []
        for p in proposals:
            entity_type = p.get("entity_type", "requirement")
            change_type = p.get("change_type", "UNCHANGED")
            target_requirement_id = p.get("target_requirement_id")
            if entity_type == "requirement" and change_type != "ADDED" and target_requirement_id is None:
                target_requirement_id = req_id_to_pk.get(p.get("entity_id"))
            rows.append({
                "review_id": review_id, "bid_id": bid_id, "organization_id": organization_id,
                "review_decision": "pending",
                "source_document_id": p.get("source_document_id"),
                "source_document_hash": p.get("source_document_hash"),
                "physical_source_ref": p.get("physical_source_ref"),
                "entity_type": entity_type,
                "entity_id": p.get("entity_id"),
                "target_requirement_id": target_requirement_id,
                "related_requirement_ids": p.get("related_requirement_ids"),
                "change_type": change_type,
                "canonical_effect": p.get("canonical_effect", "evidence_only"),
                "previous_value": p.get("previous_value"),
                "new_value": p.get("new_value"),
                "extraction_evidence": p.get("extraction_evidence"),
                "proposed_by": "system",
            })

        db.insert_proposed_procurement_changes(rows)
        db.mark_review_ready_for_review(review_id)
        return proposals
    except Exception as e:
        # Analysis-failure-only terminal state (never left stuck in
        # 'analyzing' with no recovery path) -- matches
        # analysis_service._execute_fast_analysis_run's own
        # never-stuck-non-terminal guarantee.
        db.mark_review_failed(review_id, str(e)[:500])
        raise


def record_change_review_decision_for_organization(
    bid_id: int, organization_id: str, change_id: int, decision: str,
    actor_user_id: str, review_note: str | None = None,
) -> None:
    require_bid_access(bid_id, organization_id)
    changes = [c for c in db.get_client().table("procurement_changes").select("id,bid_id")
               .eq("id", change_id).execute().data or [] if int(c["bid_id"]) == int(bid_id)]
    if not changes:
        raise AccessDeniedError(f"change {change_id} does not belong to bid {bid_id}")
    db.record_change_review_decision(change_id, decision, actor_user_id, review_note=review_note)


def apply_procurement_update_review_for_organization(
    bid_id: int, organization_id: str, review_id: int,
    expected_base_revision: int, actor_user_id: str,
) -> dict:
    require_bid_access(bid_id, organization_id)
    reviews = [r for r in db.get_procurement_update_reviews(bid_id)
               if r["id"] == review_id and int(r.get("bid_id", -1)) == int(bid_id)]
    if not reviews:
        raise AccessDeniedError(f"review {review_id} does not belong to bid {bid_id}")
    return db.apply_procurement_update_review(review_id, expected_base_revision, actor_user_id)


def resolve_procurement_conflict_for_organization(
    bid_id: int, organization_id: str, conflict_id: int, expected_base_revision: int,
    resolution_value: dict, resolution_reason: str, actor_user_id: str,
) -> dict:
    require_bid_access(bid_id, organization_id)
    conflicts = [c for c in db.get_procurement_conflicts(bid_id)
                 if c["id"] == conflict_id and int(c.get("bid_id", -1)) == int(bid_id)]
    if not conflicts:
        raise AccessDeniedError(f"conflict {conflict_id} does not belong to bid {bid_id}")
    return db.resolve_procurement_conflict(
        conflict_id, expected_base_revision, resolution_value, resolution_reason, actor_user_id
    )


# ── Authenticated user-scoped reads (Phase 8 remediation package 3, ─────
#    interactive cutover) ─────────────────────────────────────────────────
# Everything above this line still reads through the privileged
# service-role client (database.get_client()) -- appropriate for
# server-side authorization checks and background work, but it does NOT
# exercise the live RLS policies from migration 008 at all (service-role
# bypasses RLS by definition). The three functions below are different in
# kind: they take the caller's own access_token and read through
# auth_client.get_authenticated_client(access_token), so the rows that
# come back are determined ENTIRELY by Postgres evaluating the real RLS
# policies for that real request -- no application-level organization_id
# filter is applied here at all, unlike list_bids_for_organization() above.
# This is what actually proves "the RLS layer gates this read", not just
# "the service-role code happens to filter correctly."

def list_bids_authenticated(access_token: str) -> list[dict]:
    """The bids visible to whoever access_token belongs to, determined
    entirely by RLS (bids_select_org_member, migration 008) -- no
    organization_id argument exists here because none is needed or
    trusted; the policy alone decides. Includes the same req_count/
    req_done/task_count/task_done rollup as database.get_all_bids(), via
    the SAME authenticated client (requirements/tasks are bid-owned
    tables with their own RLS policies -- the rollup counts are
    themselves RLS-scoped, not just the bid list), so page_dashboard()/
    page_all_bids() can swap their data source with zero change to their
    own rendering logic."""
    client = auth_client.get_authenticated_client(access_token)
    rows = (
        client.table("bids")
        .select("*")
        .order("submission_deadline")
        .execute()
        .data
        or []
    )
    for b in rows:
        b["id"] = int(b["id"])
        reqs = (client.table("requirements").select("id,status").eq("bid_id", b["id"])
                .eq("lifecycle_status", "active").execute().data or [])
        tasks = client.table("tasks").select("id,status").eq("bid_id", b["id"]).execute().data or []
        b["req_count"] = len(reqs)
        b["req_done"] = sum(1 for r in reqs if r["status"] == "Complete")
        b["task_count"] = len(tasks)
        b["task_done"] = sum(1 for t in tasks if t["status"] == "Complete")
    return rows


def get_bid_authenticated(access_token: str, bid_id: int) -> dict | None:
    """A single bid, RLS-gated. A bid_id outside the caller's organization
    returns None (RLS excludes the row from the result set entirely) --
    indistinguishable from a bid_id that doesn't exist, exactly like
    get_bid_for_organization()'s own shape, but this time the exclusion is
    enforced by Postgres itself, not by an application-level .eq() filter."""
    client = auth_client.get_authenticated_client(access_token)
    rows = client.table("bids").select("*").eq("id", bid_id).execute().data
    return rows[0] if rows else None


def update_bid_authenticated(access_token: str, bid_id: int, data: dict) -> None:
    """RLS-gated equivalent of database.update_bid() -- identical partial-
    update semantics (only keys actually present in `data` are written; a
    present key with value None still writes NULL, matching the Edit Bid
    form's explicit-None-means-clear convention). The bids_update_org_member
    policy's WITH CHECK clause is what actually prevents writing an
    organization_id this function doesn't even accept as a field -- see
    migration 008 -- so no separate application-level guard is needed here
    for tenant-escape via this path specifically."""
    keys = ["title", "client", "file_number", "stage", "sensitivity", "owner",
            "value_cad", "submission_deadline", "clarification_deadline", "notes"]
    clean = {k: data[k] for k in keys if k in data}
    if not clean:
        return
    auth_client.get_authenticated_client(access_token).table("bids").update(clean).eq("id", bid_id).execute()


def get_bid_analysis_authenticated(access_token: str, bid_id: int) -> dict:
    """Analysis runs and the latest structured result for one bid, both
    RLS-gated (analysis_runs_select_bid_access / analysis_results_select_
    bid_access, migration 008). Returns empty lists/None if bid_id is
    outside the caller's organization -- RLS excludes the underlying
    analysis_runs/analysis_results rows the same way it excludes the bid
    itself, independent of whatever get_bid_authenticated() returned."""
    client = auth_client.get_authenticated_client(access_token)
    runs = (
        client.table("analysis_runs")
        .select("*")
        .eq("bid_id", bid_id)
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )
    latest_result = None
    for run in runs:
        if run.get("status") == "COMPLETE":
            rows = (
                client.table("analysis_results")
                .select("*")
                .eq("run_id", run["id"])
                .execute()
                .data
            )
            if rows:
                latest_result = rows[0]
            break
    return {"runs": runs, "latest_result": latest_result}


def get_latest_analysis_run_authenticated(
    access_token: str, bid_id: int, analysis_mode: str | None = None
) -> dict | None:
    """RLS-gated equivalent of database.get_latest_analysis_run() -- same
    exact semantics (most recent run for a bid, optionally filtered to one
    mode), same ordering, same COMPLETE/FAILED/in-progress status returned
    as-is (this function does not interpret status, only fetches -- Fast
    Analysis's own status semantics are completely unchanged). Used by the
    normal routed UNDERSTAND-stage status panel instead of the service-role
    original."""
    client = auth_client.get_authenticated_client(access_token)
    q = client.table("analysis_runs").select("*").eq("bid_id", bid_id)
    if analysis_mode:
        q = q.eq("analysis_mode", analysis_mode)
    rows = q.order("created_at", desc=True).limit(1).execute().data
    return rows[0] if rows else None


def get_latest_analysis_result_authenticated(
    access_token: str, bid_id: int, analysis_mode: str = "FAST"
) -> dict | None:
    """RLS-gated equivalent of database.get_latest_analysis_result() --
    identical two-step lookup (most recent COMPLETE run for bid+mode, then
    that run's structured_intelligence), same ordering by completed_at.
    Used by the normal routed UNDERSTAND-stage content rendering instead
    of the service-role original."""
    client = auth_client.get_authenticated_client(access_token)
    runs = (
        client.table("analysis_runs")
        .select("id")
        .eq("bid_id", bid_id)
        .eq("analysis_mode", analysis_mode)
        .eq("status", "COMPLETE")
        .order("completed_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    if not runs:
        return None
    rows = client.table("analysis_results").select("*").eq("run_id", runs[0]["id"]).execute().data
    return rows[0] if rows else None


# ══════════════════════════════════════════════════════════════════════════
# Phase 8 remediation package 3 — final interactive-surface cutover
# ══════════════════════════════════════════════════════════════════════════
# Every function below reads/writes through auth_client.get_authenticated_
# client(access_token) -- never database.get_client() -- for exactly the
# tables migration 008 granted `authenticated` real CRUD policies on.
# Each one deliberately mirrors its database.py counterpart's exact field
# allowlist, fallback behavior, and payload shaping (reusing
# format_requirement_payload()/format_bid_brief_payload() directly where
# database.py itself does) -- this is an authorization/data-access
# cutover, not a redesign; the two pure-data-shaping helpers imported
# above have no client dependency of their own, so reusing them verbatim
# costs nothing and guarantees identical behavior.
#
# Category boundary, precisely (matches migration 008's own live policy
# set, not guessed): requirements/tasks/outline_sections/deliverables/
# clarifications have full authenticated CRUD; debriefs and bid_decisions
# have select+insert only (no update/delete policy exists for either, and
# no delete_debrief()/update path for bid_decisions exists in the product
# either, so nothing is missing); content_library has full CRUD but ONLY
# for bid_id-scoped rows (bid_id IS NULL "global" rows have no
# authenticated policy at all -- an unresolved product decision, not
# fixed here); documents/document_versions/bid_briefs are authenticated
# SELECT only (their writes remain server-side, exactly as migration 008
# already decided, alongside Storage authorization -- package 4 scope);
# firm_profiles is organization-scoped (via organization_id, not bid_id)
# with full authenticated CRUD; coaches has NO authenticated policy at
# all (migration 008 left it untouched -- no bid_id, no organization_id,
# cannot be correctly tenant-scoped without a schema change that is out
# of a policy-only migration's scope) and stays entirely server-side,
# gated only by the application's own mandatory-authentication
# requirement (every page, including the coach roster, is unreachable
# without a real signed-in session and a resolved AuthContext -- see
# app.py's gate) rather than by any per-row RLS check, since none can
# exist for this table yet.


# ── requirements (category A: full CRUD) ─────────────────────────────────
def get_requirements_authenticated(access_token: str, bid_id: int, include_retired: bool = False) -> list[dict]:
    """Migration 010: current-truth reads default to lifecycle_status=
    'active' only -- see database.get_requirements()'s docstring for the
    full rationale (a superseded/removed requirement must never silently
    continue affecting DECIDE/CHECK/SUBMIT scoring or the compliance
    matrix). include_retired=True is for an explicit history/audit view."""
    client = auth_client.get_authenticated_client(access_token)
    query = client.table("requirements").select("*").eq("bid_id", bid_id)
    if not include_retired:
        query = query.eq("lifecycle_status", "active")
    return query.order("category").order("req_id").execute().data or []


def upsert_requirement_authenticated(access_token: str, data: dict) -> None:
    """Category A (RLS-only, no explicit require_bid_access -- Postgres RLS
    itself is the access boundary for the write below). The canonical-field
    governance guard is still service-role plumbing, not a privilege
    escalation: it only READS bids.procurement_truth_status to decide
    whether to allow the write, mirroring database.upsert_requirement()'s
    own guard (see db._guard_canonical_requirement_write's docstring) --
    the actual write still goes through the caller's own RLS-scoped
    `client`, never the service client."""
    client = auth_client.get_authenticated_client(access_token)
    db._guard_canonical_requirement_write(db.get_client(), data)
    keys_with_integrity = ["req_id", "category", "description", "rfso_ref", "weight",
                           "evidence", "owner", "deadline", "status", "notes",
                           "qual_status", "gap_action", "qual_notes",
                           "evidence_status", "source_refs"]
    keys_with_qual = ["req_id", "category", "description", "rfso_ref", "weight",
                      "evidence", "owner", "deadline", "status", "notes",
                      "qual_status", "gap_action", "qual_notes"]
    keys_basic = ["req_id", "category", "description", "rfso_ref", "weight",
                  "evidence", "owner", "deadline", "status", "notes"]

    def _do_upsert(keys):
        clean = format_requirement_payload(data, keys)
        if data.get("id"):
            client.table("requirements").update(clean).eq("id", data["id"]).execute()
        else:
            if "bid_id" in data:
                clean["bid_id"] = data["bid_id"]
            client.table("requirements").insert(clean).execute()

    try:
        _do_upsert(keys_with_integrity)
    except Exception as e:
        err = str(e).lower()
        if any(w in err for w in ["column", "schema", "evidence_status", "source_refs", "pgrst"]):
            try:
                _do_upsert(keys_with_qual)
            except Exception as e2:
                err2 = str(e2).lower()
                if any(w in err2 for w in ["column", "schema", "qual_", "gap_action", "pgrst"]):
                    _do_upsert(keys_basic)
                else:
                    raise
        else:
            raise


def delete_requirement_authenticated(access_token: str, req_id: int) -> None:
    sb = db.get_client()
    row = db._one(sb.table("requirements").select("bid_id").eq("id", req_id).execute())
    if row and db._bid_is_governed(sb, row.get("bid_id")):
        raise db.GovernedRequirementMutationError(
            "This bid's procurement truth is already governed -- requirements can only be retired "
            "through a governed procurement review (Procurement Documents & Addenda), never deleted directly."
        )
    auth_client.get_authenticated_client(access_token).table("requirements").delete().eq("id", req_id).execute()


# ── tasks (category A: full CRUD) ─────────────────────────────────────────
def get_tasks_authenticated(access_token: str, bid_id: int) -> list[dict]:
    client = auth_client.get_authenticated_client(access_token)
    return (
        client.table("tasks").select("*").eq("bid_id", bid_id)
        .order("due_date").order("priority").execute().data or []
    )


def upsert_task_authenticated(access_token: str, data: dict) -> None:
    client = auth_client.get_authenticated_client(access_token)
    keys = ["title", "description", "owner", "due_date", "priority", "status"]
    if data.get("id"):
        client.table("tasks").update({k: data.get(k) for k in keys}).eq("id", data["id"]).execute()
    else:
        client.table("tasks").insert({k: data.get(k) for k in ["bid_id"] + keys}).execute()


def delete_task_authenticated(access_token: str, task_id: int) -> None:
    auth_client.get_authenticated_client(access_token).table("tasks").delete().eq("id", task_id).execute()


# ── outline_sections (category A: full CRUD) ──────────────────────────────
def get_outline_authenticated(access_token: str, bid_id: int) -> list[dict]:
    client = auth_client.get_authenticated_client(access_token)
    return client.table("outline_sections").select("*").eq("bid_id", bid_id).order("sort_order").execute().data or []


def upsert_section_authenticated(access_token: str, data: dict) -> None:
    client = auth_client.get_authenticated_client(access_token)
    keys = ["sort_order", "section_num", "title", "owner", "word_limit", "status", "notes"]
    if data.get("id"):
        client.table("outline_sections").update({k: data.get(k) for k in keys}).eq("id", data["id"]).execute()
    else:
        client.table("outline_sections").insert({k: data.get(k) for k in ["bid_id"] + keys}).execute()


def delete_section_authenticated(access_token: str, sec_id: int) -> None:
    auth_client.get_authenticated_client(access_token).table("outline_sections").delete().eq("id", sec_id).execute()


# ── Section Analyzer: durable mapping + review history (category A: full CRUD) ──
# The analyzer's actual model-invoking action, analyze_section_for_organization,
# lives further below as a category-B (service-role, require_bid_access-gated)
# privileged call -- it mirrors start_fast_analysis_for_organization's
# authorization shape for the same reason: it spends a model call, this
# read/write CRUD does not.

def get_section_requirement_ids_authenticated(access_token: str, section_id: int) -> list[int]:
    client = auth_client.get_authenticated_client(access_token)
    rows = client.table("outline_section_requirements").select("requirement_id") \
        .eq("section_id", section_id).execute().data or []
    return [r["requirement_id"] for r in rows]


def set_section_requirement_mapping_authenticated(access_token: str, bid_id: int, section_id: int,
                                                   requirement_ids: list[int]) -> None:
    client = auth_client.get_authenticated_client(access_token)
    client.table("outline_section_requirements").delete().eq("section_id", section_id).execute()
    if requirement_ids:
        client.table("outline_section_requirements").insert([
            {"bid_id": bid_id, "section_id": section_id, "requirement_id": rid}
            for rid in sorted(set(requirement_ids))
        ]).execute()


def get_section_reviews_authenticated(access_token: str, bid_id: int, section_id: int) -> list[dict]:
    client = auth_client.get_authenticated_client(access_token)
    return (
        client.table("section_reviews").select("*")
        .eq("bid_id", bid_id).eq("section_id", section_id)
        .order("created_at", desc=True).execute().data or []
    )


# ── deliverables (category A: full CRUD) ──────────────────────────────────
def get_deliverables_authenticated(access_token: str, bid_id: int) -> list[dict]:
    client = auth_client.get_authenticated_client(access_token)
    return (
        client.table("deliverables").select("*").eq("bid_id", bid_id)
        .order("sort_order").order("category").execute().data or []
    )


def upsert_deliverable_authenticated(access_token: str, data: dict) -> None:
    client = auth_client.get_authenticated_client(access_token)
    keys = ["sort_order", "service_id", "title", "description", "category",
            "duration", "volume", "unit", "price_ai", "price_non_ai",
            "optional", "linked_req_ids", "notes"]
    if data.get("id"):
        client.table("deliverables").update({k: data.get(k) for k in keys}).eq("id", data["id"]).execute()
    else:
        client.table("deliverables").insert({k: data.get(k) for k in ["bid_id"] + keys}).execute()


def delete_deliverable_authenticated(access_token: str, del_id: int) -> None:
    auth_client.get_authenticated_client(access_token).table("deliverables").delete().eq("id", del_id).execute()


# ── clarifications (category A: full CRUD) ────────────────────────────────
def get_clarifications_authenticated(access_token: str, bid_id: int) -> list[dict]:
    client = auth_client.get_authenticated_client(access_token)
    return client.table("clarifications").select("*").eq("bid_id", bid_id).order("id").execute().data or []


def upsert_clarification_authenticated(access_token: str, data: dict) -> None:
    client = auth_client.get_authenticated_client(access_token)
    keys = ["question_id", "question", "rationale", "priority", "linked_req_ids",
            "submitted_date", "answer", "answer_date", "changes_matrix", "status", "notes"]
    if data.get("id"):
        client.table("clarifications").update({k: data.get(k) for k in keys}).eq("id", data["id"]).execute()
    else:
        client.table("clarifications").insert({k: data.get(k) for k in ["bid_id"] + keys}).execute()


def delete_clarification_authenticated(access_token: str, clar_id: int) -> None:
    auth_client.get_authenticated_client(access_token).table("clarifications").delete().eq("id", clar_id).execute()


# ── debriefs (category A, partial: select + insert + update only -- no ──
#    delete_debrief() exists anywhere in the product, so no delete policy
#    was granted and none is needed here) ──────────────────────────────────
def get_debriefs_authenticated(access_token: str, bid_id: int) -> list[dict]:
    client = auth_client.get_authenticated_client(access_token)
    return client.table("debriefs").select("*").eq("bid_id", bid_id).order("id").execute().data or []


def upsert_debrief_authenticated(access_token: str, data: dict) -> None:
    client = auth_client.get_authenticated_client(access_token)
    keys = ["outcome", "score_technical", "score_financial", "score_total",
            "rank", "competitors", "evaluator_feedback", "win_factors",
            "loss_factors", "lessons", "notes"]
    if data.get("id"):
        client.table("debriefs").update({k: data.get(k) for k in keys}).eq("id", data["id"]).execute()
    else:
        client.table("debriefs").insert({k: data.get(k) for k in ["bid_id"] + keys}).execute()


# ── bid_decisions (category A, partial: select + insert only -- ─────────
#    save_bid_decision() only ever inserts, append-only by pre-existing
#    product design, not a Package 3 choice) ──────────────────────────────
def get_bid_decision_authenticated(access_token: str, bid_id: int) -> dict | None:
    client = auth_client.get_authenticated_client(access_token)
    rows = (
        client.table("bid_decisions").select("*").eq("bid_id", bid_id)
        .order("id", desc=True).limit(1).execute().data
    )
    return rows[0] if rows else None


def save_bid_decision_authenticated(access_token: str, data: dict) -> None:
    client = auth_client.get_authenticated_client(access_token)
    keys = ["bid_id", "ai_recommendation", "ai_confidence", "overall_score",
            "dimension_scores", "hard_blockers", "conditions", "win_themes",
            "red_flags", "human_decision", "override_reason", "decided_by", "decided_at"]
    clean = {}
    for k in keys:
        if k in data:
            v = data.get(k)
            clean[k] = json.dumps(v) if isinstance(v, (list, dict)) else v
    try:
        client.table("bid_decisions").insert(clean).execute()
    except Exception:
        try:
            client.table("bid_decisions").insert(
                {k: v for k, v in clean.items() if k != "decided_at"}
            ).execute()
        except Exception:
            pass


# ── content_library (category A, scoped: bid_id-scoped rows only -- ─────
#    bid_id IS NULL "global" rows have no authenticated policy, per
#    migration 008's own documented, deliberate, unresolved decision) ────
def get_library_items_authenticated(access_token: str, bid_id: int) -> list[dict]:
    client = auth_client.get_authenticated_client(access_token)
    return (
        client.table("content_library").select("*").eq("bid_id", bid_id)
        .order("category").order("title").execute().data or []
    )


def semantic_library_search_authenticated(
    access_token: str, query: str, bid_id: int, top_k: int = 5
) -> tuple[list[dict], bool]:
    """Authenticated equivalent of database.semantic_library_search() --
    same embeddings.semantic_search() call, but sourced from the
    bid-scoped, RLS-gated read above rather than the service-role read."""
    items = get_library_items_authenticated(access_token, bid_id)
    try:
        from embeddings import semantic_search
        return semantic_search(query, items, top_k=top_k)
    except Exception:
        return items[:top_k], False


def upsert_library_item_authenticated(access_token: str, data: dict) -> None:
    """Bid-scoped content_library rows only -- data['bid_id'] must be set
    (the RLS INSERT/UPDATE policy requires bid_id IS NOT NULL); embedding
    generation is intentionally NOT attempted here (embeddings.py's Voyage
    call is an external, non-tenant-relevant side effect out of this
    cutover's scope -- callers needing it still use the service-role
    upsert_library_item() for genuinely global items, which remains
    correctly server-side)."""
    client = auth_client.get_authenticated_client(access_token)
    keys = ["title", "category", "content", "source", "bid_id", "tags", "approved", "notes"]
    row = {k: data.get(k) for k in keys}
    if data.get("id"):
        client.table("content_library").update(row).eq("id", data["id"]).execute()
    else:
        client.table("content_library").insert(row).execute()


def delete_library_item_authenticated(access_token: str, item_id: int) -> None:
    auth_client.get_authenticated_client(access_token).table("content_library").delete().eq("id", item_id).execute()


# ── content_library, organization-scoped privileged variant (final ──────
#    interactive-surface cutover, package 3) -- pages_extra.py's
#    page_content_library() is a cross-bid browse/manage view ("every
#    reusable item this organization should see"), not a single bid_id's
#    own rows (get_library_items_authenticated() above already covers
#    that shape). No RLS policy expresses "every row across many of my
#    own bids plus global rows" -- content_library RLS is single-bid_id
#    scoped, and bid_id IS NULL rows have no authenticated policy at all
#    (see module comment above). This stays a privileged, service-role
#    read/write, but is explicitly scoped server-side to this
#    organization's own bid_ids (plus true bid_id IS NULL global items,
#    matching the page's original, intended "my library + shared global
#    content" behavior) rather than the previous ungated read of the
#    entire table across every organization that will ever exist. -────
def list_library_items_for_organization(organization_id: str, category: str | None = None) -> list[dict]:
    sb = db.get_client()
    bid_ids = [b["id"] for b in list_bids_for_organization(organization_id)]
    q = sb.table("content_library").select("*")
    if bid_ids:
        or_clause = ",".join([f"bid_id.eq.{bid}" for bid in bid_ids] + ["bid_id.is.null"])
        q = q.or_(or_clause)
    else:
        q = q.is_("bid_id", "null")
    if category:
        q = q.eq("category", category)
    return q.order("category").order("title").execute().data or []


def upsert_library_item_for_organization(organization_id: str, data: dict) -> None:
    """Authorization boundary: if data['bid_id'] is set, it must belong to
    this organization (require_bid_access); bid_id=None (global item) is
    unrestricted, matching content_library's own pre-existing,
    deliberately-undecided global-library design -- not something this
    pass resolves or redesigns."""
    bid_id = data.get("bid_id")
    if bid_id:
        require_bid_access(bid_id, organization_id)
    db.upsert_library_item(data)


def delete_library_item_for_organization(organization_id: str, item_id: int) -> None:
    """Authorization boundary: verifies the item belongs to a bid owned by
    this organization before deleting it; a true global (bid_id IS NULL)
    item is unrestricted to any authenticated org member, matching its
    pre-existing shared-across-all-organizations design."""
    sb = db.get_client()
    rows = sb.table("content_library").select("bid_id").eq("id", item_id).execute().data
    if rows and rows[0].get("bid_id") is not None:
        require_bid_access(rows[0]["bid_id"], organization_id)
    db.delete_library_item(item_id)


# ── documents / document_versions / bid_briefs (category B: select ──────
#    only -- writes remain server-side alongside Storage, per migration
#    008's own already-live decision; not revisited here) ─────────────────
def get_documents_authenticated(access_token: str, bid_id: int) -> list[dict]:
    client = auth_client.get_authenticated_client(access_token)
    return (
        client.table("documents").select("*").eq("bid_id", bid_id)
        .order("doc_type").order("name").execute().data or []
    )


def get_document_versions_authenticated(access_token: str, doc_id: int) -> list[dict]:
    client = auth_client.get_authenticated_client(access_token)
    return (
        client.table("document_versions").select("*").eq("document_id", doc_id)
        .order("version", desc=True).execute().data or []
    )


def get_bid_brief_authenticated(access_token: str, bid_id: int) -> dict | None:
    client = auth_client.get_authenticated_client(access_token)
    try:
        rows = client.table("bid_briefs").select("*").eq("bid_id", bid_id).execute().data
        return rows[0] if rows else None
    except Exception:
        return None


def get_readiness_authenticated(access_token: str, bid_id: int) -> dict:
    """RLS-gated equivalent of database.get_readiness() -- requirements
    and tasks are authenticated-select-able (category A); documents is
    authenticated-select-only (category B) -- all three reads here use
    the same authenticated client, identical aggregation logic."""
    client = auth_client.get_authenticated_client(access_token)
    reqs = (client.table("requirements").select("category,status").eq("bid_id", bid_id)
            .eq("lifecycle_status", "active").execute().data or [])
    tsks = client.table("tasks").select("status").eq("bid_id", bid_id).execute().data or []
    docs = client.table("documents").select("doc_type,status").eq("bid_id", bid_id).execute().data or []
    mand = [r for r in reqs if r["category"] == "Mandatory"]
    rated = [r for r in reqs if r["category"] != "Mandatory"]
    sub = [d for d in docs if d["doc_type"] == "Submission"]
    return {
        "m_total": len(mand), "m_done": sum(1 for r in mand if r["status"] == "Complete"),
        "r_total": len(rated), "r_done": sum(1 for r in rated if r["status"] == "Complete"),
        "t_total": len(tsks), "t_done": sum(1 for t in tsks if t["status"] == "Complete"),
        "d_total": len(sub), "d_done": sum(1 for d in sub if d["status"] in ("Uploaded", "Approved", "Submitted", "Complete")),
    }


# ── firm_profiles (category D: organization-scoped, full CRUD via ───────
#    organization_id, not bid_id) ──────────────────────────────────────────
def get_firm_profile_authenticated(access_token: str, organization_id: str) -> dict:
    """Unlike database.get_firm_profile() (a global .limit(1) singleton
    with no tenant scoping at all), this filters explicitly by
    organization_id -- redundant with the RLS policy itself, but precise
    and intentional rather than relying on RLS alone to narrow a
    deliberately-unscoped query."""
    client = auth_client.get_authenticated_client(access_token)
    try:
        rows = (
            client.table("firm_profiles").select("*")
            .eq("organization_id", organization_id).limit(1).execute().data
        )
        if rows:
            return {**db.DEFAULT_FIRM_PROFILE, **rows[0]}
    except Exception:
        pass
    return db.DEFAULT_FIRM_PROFILE.copy()


def save_firm_profile_authenticated(access_token: str, organization_id: str, data: dict) -> None:
    client = auth_client.get_authenticated_client(access_token)
    keys = ["company_name", "overview", "core_capabilities", "key_sectors",
            "languages", "locations", "certifications", "insurance_defaults",
            "ai_disclosure_policy"]
    clean = {k: data.get(k) for k in keys if k in data}
    clean["organization_id"] = organization_id
    try:
        existing = (
            client.table("firm_profiles").select("id")
            .eq("organization_id", organization_id).limit(1).execute().data
        )
        if existing:
            client.table("firm_profiles").update(clean).eq("id", existing[0]["id"]).execute()
        else:
            client.table("firm_profiles").insert(clean).execute()
    except Exception:
        pass


# ── coaches (category D->A: organization-owned team/personnel data, ─────
#    full CRUD via organization_id, not bid_id -- migration 009). An
#    explicit semantic audit (schema columns are real personal contact
#    info -- email, phone, a named client reference contact -- populated
#    from a firm's OWN past-proposal extraction, not shared/global
#    reference values) determined `coaches` is organization-owned, the
#    same as firm_profiles, not platform-global data. See migration 009's
#    own header comment for the full audit and the three explicit
#    questions/answers it was based on.) ──────────────────────────────────
def get_coaches_authenticated(access_token: str) -> list[dict]:
    client = auth_client.get_authenticated_client(access_token)
    return client.table("coaches").select("*").order("name").execute().data or []


def upsert_coach_authenticated(access_token: str, organization_id: str, data: dict) -> None:
    """Mirrors database.upsert_coach()'s exact key allowlist. Unlike the
    update path (RLS's own USING clause already confines an update to a
    row the caller's organization owns), a genuinely new row has no
    organization_id yet until this call supplies one explicitly -- set
    here rather than trusted from the caller's own data dict, so a client
    cannot insert a coach into a different organization_id than the one
    its own resolved AuthContext says it belongs to."""
    client = auth_client.get_authenticated_client(access_token)
    keys = ["name", "credentials", "icf_level", "sectors", "languages", "location",
            "availability", "email", "phone", "cv_summary", "reference_contact", "notes"]
    row = {k: data.get(k) for k in keys}
    if data.get("id"):
        client.table("coaches").update(row).eq("id", data["id"]).execute()
    else:
        row["organization_id"] = organization_id
        client.table("coaches").insert(row).execute()


def delete_coach_authenticated(access_token: str, coach_id: int) -> None:
    auth_client.get_authenticated_client(access_token).table("coaches").delete().eq("id", coach_id).execute()


# ── Proposal Intelligence (PI-1, migrations/015_proposal_intelligence.sql) ────
# Authorization boundary in front of the EXISTING Proposal Alignment
# Analyzer -- adds NO new LLM call, does not touch analyst.py's prompts,
# schema, scoring, chunking, or recovery behavior. Writes are privileged
# (service-role, via database.py) and only ever reached through
# run_proposal_intelligence_for_organization() below -- never exposed
# directly to UI code. Reads are split the usual way: an
# authenticated/RLS-scoped path for pages/stage_check.py, and this same
# privileged path also available for service-side use.

def run_proposal_intelligence_for_organization(
    bid_id: int, organization_id: str, package_files: list[dict],
    requirements: list[dict], rfp_text: str, bid_info: dict,
    full_package_manifest: list[dict] | None = None,
    user_id: str | None = None,
) -> dict:
    """Establishes/reuses the proposal package snapshot identity, runs the
    existing analyst.analyze_proposal_alignment_package() unchanged, adapts
    its result into durable Proposal Intelligence rows
    (proposal_intelligence.py's adapter), and persists the run + its
    assessments + its findings ATOMICALLY (PI-1.1 instruction 3, via
    database.create_proposal_intelligence_bundle -- never three
    independent inserts a partial failure could leave inconsistent).
    Returns {"run", "alignment_result"} (the run row already carries its
    persisted id; assessments/findings are read back via
    get_proposal_requirement_assessments_authenticated/
    get_proposal_intelligence_findings_authenticated by callers that need
    them, matching every other read path in this module).

    `package_files` must be the caller's CURRENT, already-filtered
    (included-only) list in analyze_proposal_alignment_package's own
    expected shape -- this is exactly what the analyzer receives, never
    widened. `full_package_manifest` (PI-1.1 instruction 5) is the
    COMPLETE submitted package -- every file, included and excluded,
    duplicate, rejected, and unsupported alike, in
    extractor.build_report_manifest()'s report-safe shape -- used ONLY
    for the durable package-snapshot identity/manifest, never passed to
    the analyzer. Defaults to `package_files` when omitted (keeps the
    function usable exactly as before if a caller has no broader manifest
    available), but callers that DO have the full submitted package
    (pages/stage_check.py) must pass it explicitly so an excluded file
    remains part of the historical audit record (see
    proposal_intelligence.compute_package_digest's docstring for why this
    makes "excluded" and "never supplied" different package identities).

    On a genuine provider/model exception from the analyzer, persists a
    FAILED run (the package snapshot identity already exists by that
    point, so this satisfies instruction 13's "only where sufficient run
    identity already exists") with no fabricated findings, then re-raises
    -- callers must not treat a FAILED run as a silently-swallowed error.
    started_at/completed_at (PI-1.1 instruction 7) are captured around the
    actual analyzer invocation, for both the successful and FAILED cases."""
    require_bid_access(bid_id, organization_id)
    import analyst
    import extractor
    import proposal_intelligence as pi

    manifest_source = full_package_manifest if full_package_manifest is not None else package_files
    procurement_state = db.get_bid_procurement_state(bid_id)

    digest = pi.compute_package_digest(manifest_source)
    manifest = extractor.build_report_manifest(manifest_source)
    snapshot = db.get_or_create_proposal_package_snapshot(
        bid_id, digest, manifest, created_by_user_id=user_id)

    started_at = datetime.now(timezone.utc).isoformat()
    try:
        alignment_result = analyst.analyze_proposal_alignment_package(
            package_files=package_files, requirements=requirements,
            rfp_text=rfp_text, bid_info=bid_info,
        )
    except Exception as exc:
        completed_at = datetime.now(timezone.utc).isoformat()
        failed_payload = pi.build_failed_run_payload(
            procurement_state=procurement_state, failure_reason=f"{type(exc).__name__}: {exc}",
            started_at=started_at, completed_at=completed_at)
        failed_payload.update({
            "bid_id": bid_id, "proposal_package_snapshot_id": snapshot["id"],
            "created_by_user_id": user_id,
        })
        db.create_proposal_intelligence_bundle(failed_payload)
        raise
    completed_at = datetime.now(timezone.utc).isoformat()

    # PI-2B1: the ONE whole-package reasoning call is enrichment ON TOP OF
    # an already-valid local PI-2A alignment_result (step 19) -- it never
    # runs when the local analyzer produced no result at all (the
    # exception path above already returned/raised), and a package-call
    # failure here must never destroy or downgrade the local result.
    # analyze_proposal_package_intelligence() itself never raises (it
    # fail-closes internally to package_reasoning_status "FAILED"), but a
    # bounding try/except is kept anyway so a genuinely unexpected defect
    # in this brand-new PI-2B1 code path can never take down an otherwise-
    # successful PI-2A run.
    # PI-2B2: Response Guidelines are used ONLY when they already exist,
    # exactly as Fast Analysis's own deterministic (no-LLM) table parser
    # extracted them (fast_analysis.extract_response_guideline_sections) --
    # never inferred or reconstructed here. The audited-existing source is
    # a raw Fast Analysis snapshot (there is no governed/canonical version
    # of a Response Guideline anywhere in this schema -- see section_
    # analyzer.procurement_basis's own docstring for the same finding),
    # reached the same way BUILD's section_analyzer.py already reaches it,
    # reused rather than reimplemented. A bid with no complete Fast
    # Analysis run, or one whose snapshot carries no guidelines, yields []
    # here -- never a fabricated guideline.
    import section_analyzer
    response_guidelines = []
    try:
        basis = section_analyzer.procurement_basis(bid_id)
        raw_snapshot = basis.get("raw_snapshot")
        if raw_snapshot is not None:
            response_guidelines = list(getattr(raw_snapshot, "deterministic_response_guidelines", None) or [])
    except Exception:
        response_guidelines = []

    try:
        package_intelligence = analyst.analyze_proposal_package_intelligence(
            alignment_result, requirements, bid_info, bid_id=bid_id,
            response_guidelines=response_guidelines,
        )
    except Exception as exc:
        package_intelligence = {
            "package_findings": [], "package_reasoning_status": "FAILED",
            "package_ledger_digest": None, "rejected_count": 0,
            "claims_dropped_for_budget": 0,
            "failure_reason": f"{type(exc).__name__}: {exc}",
            "guideline_assessments": [], "rejected_guideline_count": 0,
        }

    run_payload = pi.build_run_payload(alignment_result, procurement_state=procurement_state,
                                       started_at=started_at, completed_at=completed_at,
                                       package_intelligence=package_intelligence)
    run_payload.update({
        "bid_id": bid_id, "proposal_package_snapshot_id": snapshot["id"],
        "created_by_user_id": user_id,
    })
    assessments = pi.adapt_requirement_assessments(alignment_result, requirements)
    findings = pi.adapt_findings(alignment_result, requirements)
    findings += pi.adapt_package_findings(package_intelligence, requirements)
    findings += pi.adapt_guideline_assessments(package_intelligence, requirements)
    run = db.create_proposal_intelligence_bundle(run_payload, assessments, findings)

    return {"run": run, "alignment_result": alignment_result, "package_intelligence": package_intelligence}


def get_latest_proposal_intelligence_run_authenticated(access_token: str, bid_id: int) -> dict | None:
    """The literal latest run of ANY status, including FAILED. CHECK's
    reload path should use get_latest_usable_proposal_intelligence_run_
    authenticated() instead (PI-1.1 instruction 9)."""
    client = auth_client.get_authenticated_client(access_token)
    rows = (client.table("proposal_intelligence_runs").select("*")
           .eq("bid_id", bid_id)
           .order("created_at", desc=True).order("id", desc=True)
           .limit(1).execute().data or [])
    return rows[0] if rows else None


def get_latest_usable_proposal_intelligence_run_authenticated(access_token: str, bid_id: int) -> dict | None:
    """The latest COMPLETE or INCOMPLETE run -- a later FAILED attempt
    never hides the most recent genuinely usable intelligence. Run
    history (get_proposal_intelligence_runs_authenticated) still returns
    every status, including FAILED -- this helper only affects what
    reload/display code treats as "the current result"."""
    client = auth_client.get_authenticated_client(access_token)
    rows = (client.table("proposal_intelligence_runs").select("*")
           .eq("bid_id", bid_id).in_("status", ["COMPLETE", "INCOMPLETE"])
           .order("created_at", desc=True).order("id", desc=True)
           .limit(1).execute().data or [])
    return rows[0] if rows else None


def get_proposal_intelligence_runs_authenticated(access_token: str, bid_id: int) -> list[dict]:
    client = auth_client.get_authenticated_client(access_token)
    return (client.table("proposal_intelligence_runs").select("*")
           .eq("bid_id", bid_id)
           .order("created_at", desc=True).order("id", desc=True)
           .execute().data or [])


def get_proposal_requirement_assessments_authenticated(access_token: str, run_id: int) -> list[dict]:
    client = auth_client.get_authenticated_client(access_token)
    return (client.table("proposal_requirement_assessments").select("*")
           .eq("run_id", run_id).execute().data or [])


def get_proposal_intelligence_findings_authenticated(access_token: str, run_id: int) -> list[dict]:
    client = auth_client.get_authenticated_client(access_token)
    return (client.table("proposal_intelligence_findings").select("*")
           .eq("run_id", run_id).execute().data or [])


def get_proposal_package_snapshots_authenticated(access_token: str, bid_id: int) -> list[dict]:
    client = auth_client.get_authenticated_client(access_token)
    return (client.table("proposal_package_snapshots").select("*")
           .eq("bid_id", bid_id).order("package_version", desc=True).execute().data or [])


def get_proposal_package_snapshot_authenticated(access_token: str, bid_id: int, snapshot_id: int) -> dict | None:
    """One snapshot by id, scoped to bid_id (defense in depth alongside
    RLS -- a snapshot_id that exists but belongs to a different bid is
    excluded by the .eq("bid_id", ...) filter even before RLS would also
    exclude it). Used by CHECK to restore the historical, full submitted-
    package manifest (included/excluded/duplicate/rejected/unsupported
    alike) on reload (PI-1.1 instruction 8)."""
    client = auth_client.get_authenticated_client(access_token)
    rows = (client.table("proposal_package_snapshots").select("*")
           .eq("bid_id", bid_id).eq("id", snapshot_id).execute().data or [])
    return rows[0] if rows else None


# ═══════════════════════════════════════════════════════════════════════════
# Organizational Memory (OM-1)
# ═══════════════════════════════════════════════════════════════════════════
# Organization-scoped (never bid-scoped) -- every function below takes an
# explicit organization_id and either (a) forces it into the write payload
# server-side (create_organizational_memory_item_for_organization), so a
# caller can never write into a different organization's memory even by
# accident, or (b) filters strictly by it before ever returning a row
# (list_/retrieve_..._for_organization). This mirrors the SAME
# *_for_organization (service-role, ownership-checked) vs *_authenticated
# (RLS-scoped) split every other subsystem in this file already uses.
def create_organizational_memory_item_for_organization(
    organization_id: str, item: dict, created_by_user_id: str | None = None,
) -> dict | None:
    """Writes exactly one Organizational Memory item, forced into
    organization_id regardless of anything the caller's `item` dict might
    have included for that key -- the same "never trust a caller-supplied
    tenant column" discipline create_bid_for_organization already applies.
    content_hash is ALWAYS recomputed server-side from `item['content']`
    via organizational_memory.content_hash() -- never accepted verbatim
    from the caller -- so a caller cannot claim a content_hash that does
    not match the content actually being stored.

    This generic path REJECTS memory_class = 'APPROVED_FIRM_KNOWLEDGE'
    outright (defense-in-depth alongside migration 016's own RPC-level
    rejection) -- a caller cannot manufacture trusted firm knowledge merely
    by supplying approved_by/approved_at/derived_from_item_id as ordinary
    parameters. Approved-knowledge creation is reserved for a separate,
    explicit human-approval write path that this phase does not build; a
    future OM-2 approval function is where that belongs, not here."""
    if not organization_id:
        raise ValueError(
            "create_organizational_memory_item_for_organization requires an explicit organization_id")
    import organizational_memory as om

    if item.get("memory_class") == om.MemoryClass.APPROVED_FIRM_KNOWLEDGE.value:
        raise ValueError(
            "create_organizational_memory_item_for_organization: APPROVED_FIRM_KNOWLEDGE "
            "creation is reserved for the explicit human-approval flow, not this generic "
            "create path")

    content = item.get("content") or ""
    clean = dict(item)
    clean["organization_id"] = organization_id
    clean["content_hash"] = om.content_hash(content)
    clean["created_by_user_id"] = created_by_user_id
    return db.create_organizational_memory_item(clean)


def list_organizational_memory_for_organization(
    organization_id: str, memory_class: str | None = None,
) -> list[dict]:
    if not organization_id:
        raise ValueError(
            "list_organizational_memory_for_organization requires an explicit organization_id")
    return db.list_organizational_memory_items(organization_id, memory_class=memory_class)


def _row_to_memory_item(row: dict):
    """Adapts a raw organizational_memory_items DB row into the retrieval
    contract's OrganizationalMemoryItem shape. Never fabricates a field --
    every provenance value is passed through as-is (None stays None)."""
    import organizational_memory as om

    approved_at = row.get("approved_at")
    if isinstance(approved_at, str):
        try:
            approved_at = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
        except ValueError:
            approved_at = None

    return om.OrganizationalMemoryItem(
        id=str(row["id"]),
        organization_id=row["organization_id"],
        memory_class=om.MemoryClass(row["memory_class"]),
        title=row.get("title") or "",
        content=row.get("content") or "",
        provenance=om.SourceProvenance(
            file_id=row.get("source_file_id"),
            content_hash=row.get("source_content_hash"),
            filename=row.get("source_filename"),
            package_path=row.get("source_package_path"),
            locator=row.get("source_locator"),
            source_bid_id=row.get("source_bid_id"),
        ),
        approved_by=row.get("approved_by_user_id"),
        approved_at=approved_at,
        derived_from_item_id=(
            str(row["derived_from_item_id"]) if row.get("derived_from_item_id") else None
        ),
        source_document_id=(
            str(row["source_document_id"]) if row.get("source_document_id") else None
        ),
        embedding=None,   # never decoded here; retrieval degrades to keyword filtering
                           # unless a caller supplies item_embed_fn explicitly (zero live
                           # embedding calls in this phase -- see organizational_memory.py).
        metadata=row.get("metadata") or {},
        item_content_hash=row.get("content_hash"),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Organizational Memory (OM-2: source ingestion + human approval lifecycle)
# ═══════════════════════════════════════════════════════════════════════════

def list_organizational_source_documents_for_organization(organization_id: str) -> list[dict]:
    if not organization_id:
        raise ValueError(
            "list_organizational_source_documents_for_organization requires an explicit organization_id")
    return db.list_organizational_source_documents(organization_id)


def ingest_organizational_source_document_for_organization(
    organization_id: str, filename: str, file_bytes: bytes,
    created_by_user_id: str | None = None,
    target_chunk_chars: int | None = None,
    content_type: str | None = None,
) -> dict:
    """Single-file, human-initiated source ingestion: extracts text from
    the uploaded file, splits it into deterministic bounded chunks
    (organizational_memory.split_source_into_chunks), uploads the ORIGINAL
    bytes to Supabase Storage, and persists the parent
    organizational_source_documents record + every SOURCE_MEMORY chunk row
    in ONE atomic database call (db.ingest_organizational_source_document
    -> migration 016's ingest_organizational_source_document() RPC) --
    never a parent-create-then-per-chunk-insert loop across separate round
    trips (commissioning-review fix #1). If any chunk insert fails inside
    that RPC, the entire transaction (parent row included) rolls back --
    a partially-ingested document can never be visible.

    Deterministic and idempotent: the same bytes + filename always produce
    the same content_hash and the same chunk boundaries; the RPC itself
    resolves a repeat/concurrent upload of byte-identical content to the
    same organization via a (organization_id, content_hash) advisory lock
    plus get-or-create semantics -- this function does not need its own
    locking, only a fast pre-check to avoid re-extracting text/re-uploading
    bytes for a file this organization has already fully ingested (an
    OPTIMIZATION only; the RPC's own lock+get-or-create is the actual
    correctness guarantee even if this pre-check is skipped or races).

    content_hash used for identity/dedup is the sha256 of the RAW UPLOADED
    BYTES, computed before any extraction -- never re-derived from
    extracted text, which can differ across extraction runs.

    Uses extractor.extract_text_from_file -- the same extraction entry
    point already used elsewhere in this codebase -- so file-type handling
    (PDF/DOCX/XLSX/XLS/CSV/plain text) is not reinvented here.
    """
    if not organization_id:
        raise ValueError(
            "ingest_organizational_source_document_for_organization requires an explicit organization_id")
    if not filename:
        raise ValueError("ingest_organizational_source_document_for_organization requires a filename")

    import hashlib
    import organizational_memory as om
    from extractor import extract_text_from_file

    raw_content_hash = hashlib.sha256(file_bytes or b"").hexdigest()

    # Fast, NON-authoritative pre-check: avoids re-extracting text/re-
    # uploading bytes for a file we already know is fully ingested.
    # Authoritative atomicity/idempotency is enforced by the RPC's advisory
    # lock + one-transaction insert below, not by this check.
    existing_docs = db.list_organizational_source_documents(organization_id)
    existing = next((d for d in existing_docs if d.get("content_hash") == raw_content_hash), None)
    if existing is not None and (existing.get("chunk_count") or 0) > 0:
        existing_items = [
            row for row in db.list_organizational_memory_items(organization_id, memory_class="SOURCE_MEMORY")
            if row.get("source_document_id") == existing.get("id")
        ]
        if len(existing_items) >= (existing.get("chunk_count") or 0):
            return {"document": existing, "items": existing_items, "reused_existing": True}

    text = extract_text_from_file(file_bytes, filename) or ""
    chunk_size = target_chunk_chars or om.SOURCE_CHUNK_TARGET_CHARS
    chunks = om.split_source_into_chunks(text, target_chunk_chars=chunk_size)

    # Final commissioning-review pass fix #3 (Python-layer courtesy check):
    # fail early, before any Storage upload, when extraction yielded no
    # usable text and therefore zero chunks. This is NOT the authoritative
    # guard -- migration 016's ingest_organizational_source_document() RPC
    # independently rejects a zero-chunk call at the DB boundary regardless
    # of this check -- but failing here avoids an unnecessary Storage upload
    # for a document that can never be ingested.
    if not chunks:
        raise ValueError(
            "ingest_organizational_source_document_for_organization: extraction yielded no "
            "usable text/chunks for this file -- refusing to ingest a zero-chunk document")

    # Original artifact -> Supabase Storage (never a Postgres bytea
    # column). Second commissioning-review hardening pass fix #2: this now
    # FAILS CLOSED -- db.upload_organizational_source_file() raises on any
    # Storage failure, and that exception is deliberately NOT caught here,
    # so a Storage failure prevents db.ingest_organizational_source_document
    # below from ever being called at all. No organizational_source_
    # documents/organizational_memory_items row can exist without a real,
    # durably-stored backing file.
    storage_path = db.upload_organizational_source_file(
        organization_id, raw_content_hash, file_bytes, content_type=content_type)

    chunk_payloads = [
        {
            "title": f"{filename} — chunk {chunk['chunk_index'] + 1}/{len(chunks)}",
            "content": chunk["text"],
            "content_hash": om.content_hash(chunk["text"]),
            "source_locator": f"chars:{chunk['char_start']}-{chunk['char_end']}",
        }
        for chunk in chunks
    ]

    result = db.ingest_organizational_source_document(
        organization_id, filename, raw_content_hash, chunk_payloads,
        storage_path=storage_path, file_size=len(file_bytes or b""),
        content_type=content_type, extracted_char_count=len(text),
        uploaded_by_user_id=created_by_user_id,
    )
    if result is None or result.get("document") is None:
        raise ValueError(
            "ingest_organizational_source_document_for_organization: atomic ingestion RPC "
            "failed to return a document")

    return {
        "document": result["document"],
        "items": result.get("items") or [],
        "reused_existing": bool(result.get("reused_existing")),
    }


def approve_organizational_memory_item_for_organization(
    organization_id: str, source_item_id: int, approved_by_user_id: str,
    fact_title: str | None = None, fact_content: str | None = None,
) -> dict:
    """The ONLY path allowed to create an APPROVED_FIRM_KNOWLEDGE item --
    genuinely separate from create_organizational_memory_item_for_
    organization (which continues to reject that class outright). This
    function:

      * fetches the SOURCE_MEMORY parent server-side, by id, via the
        service-role read path (db.get_organizational_memory_item) --
        never trusts a client-supplied copy of the parent's content;
      * verifies the parent belongs to the SAME organization_id as the
        approving request (rejects otherwise, before ever calling the DB
        RPC -- application-layer defense-in-depth alongside the RPC's own
        organization_id-scoped lookup);
      * verifies the parent's memory_class is ACTUALLY SOURCE_MEMORY
        (rejects any other class, e.g. approving an already-approved
        item or a PROPOSAL_MEMORY item);
      * requires an explicit approved_by_user_id from the CALLER's
        authenticated context (this function never defaults or infers
        it -- the caller, e.g. app.py, must pass the real signed-in
        user's id, exactly like every other *_for_organization write
        path in this file uses created_by/ctx.user_id);
      * never accepts an approved_at from the caller at all -- migration
        016's approve_organizational_memory_item() RPC sets it via now()
        inside the database, server-side, unconditionally;
      * creates a NEW APPROVED_FIRM_KNOWLEDGE row -- the parent
        SOURCE_MEMORY row is never mutated, deleted, or reclassified (the
        migration's immutable-provenance trigger would reject a mutation
        attempt regardless);
      * copies source_file_id/source_content_hash/source_filename/
        source_package_path/source_locator/source_bid_id/
        source_document_id from the fetched PARENT row automatically
        (inside the RPC, server-side) -- this function does not, and
        cannot, pass provenance fields itself;
      * lets the human optionally tighten/clarify the approved FACT TEXT
        (fact_title/fact_content) -- this changes only content/title, and
        derived_from_item_id still points at the exact reviewed
        SOURCE_MEMORY id regardless of any text edit.
    """
    if not organization_id:
        raise ValueError(
            "approve_organizational_memory_item_for_organization requires an explicit organization_id")
    if not source_item_id:
        raise ValueError(
            "approve_organizational_memory_item_for_organization requires an explicit source_item_id")
    if not approved_by_user_id:
        raise ValueError(
            "approve_organizational_memory_item_for_organization requires an explicit "
            "approved_by_user_id from the authenticated caller -- it is never inferred or defaulted")

    import organizational_memory as om

    parent = db.get_organizational_memory_item(source_item_id)
    if parent is None:
        raise ValueError(
            f"approve_organizational_memory_item_for_organization: source item {source_item_id} not found")
    if str(parent.get("organization_id")) != str(organization_id):
        raise ValueError(
            "approve_organizational_memory_item_for_organization: source item does not belong to "
            "this organization")
    if parent.get("memory_class") != om.MemoryClass.SOURCE_MEMORY.value:
        raise ValueError(
            "approve_organizational_memory_item_for_organization: source item is not SOURCE_MEMORY "
            f"(found {parent.get('memory_class')!r}) -- only a genuine SOURCE_MEMORY item may be approved")

    row = db.approve_organizational_memory_item(
        source_item_id=source_item_id,
        organization_id=organization_id,
        approved_by_user_id=approved_by_user_id,
        fact_title=fact_title,
        fact_content=fact_content,
    )
    if row is None:
        raise ValueError(
            "approve_organizational_memory_item_for_organization: approval write failed")
    return row


def retrieve_organizational_memory_for_organization(
    organization_id: str, query: str, *,
    memory_classes: list[str] | None = None,
    trusted_only: bool = False,
    top_k: int = 10,
    min_score: float = 0.0,
    embed_fn=None,
) -> list[dict]:
    """The OM-1 retrieval contract, wired to real persistence: fetches this
    organization's own memory items ONLY (list_organizational_memory_for_
    organization already filters by organization_id server-side) and hands
    them to organizational_memory.retrieve() for deterministic ranking/
    filtering. embed_fn defaults to None (zero live calls) -- a caller MAY
    pass embeddings.embed_query to opt into semantic ranking; any failure
    there still degrades to the deterministic keyword fallback inside
    retrieve() itself."""
    import organizational_memory as om

    if not organization_id:
        raise ValueError(
            "retrieve_organizational_memory_for_organization requires an explicit organization_id")
    rows = db.list_organizational_memory_items(organization_id)
    items = [_row_to_memory_item(row) for row in rows]
    classes = (
        [om.MemoryClass(c) for c in memory_classes] if memory_classes is not None else None
    )
    results = om.retrieve(
        organization_id=organization_id, query=query, items=items,
        memory_classes=classes, trusted_only=trusted_only,
        top_k=top_k, min_score=min_score, embed_fn=embed_fn,
    )
    return [r.to_dict() for r in results]


# ═══════════════════════════════════════════════════════════════════════════
# Organizational Memory (OM-3: requirement evidence strengthening)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class _MemoryItemIdentity:
    """Minimal duck-typed stand-in for organizational_memory.
    OrganizationalMemoryItem, carrying ONLY the three fields
    evidence_strengthening.compute_input_fingerprint() actually reads
    (`id`, `memory_class`, `item_content_hash`) -- never content/embedding/
    metadata/provenance. Lets OM-3B's freshness check compute a fingerprint
    from database.list_organizational_memory_item_identities' cheap
    projection without needing a full OrganizationalMemoryItem (which
    requires non-empty content and would defeat the point)."""

    id: str
    memory_class: "om.MemoryClass"
    item_content_hash: str | None = None


def _enrichment_row_to_dict(row: dict) -> dict:
    """Adapts a persisted `requirement_evidence_enrichments` row (migration
    017, OM-3B) into the SAME dict shape evidence_strengthening.
    EvidenceEnrichmentResult.to_dict() produces -- a cache hit and a fresh
    computation are indistinguishable to a caller."""
    return {
        "requirement_id": row.get("requirement_id"),
        "req_id": row.get("req_id"),
        "evidence_state_before": row.get("evidence_state_before") or {},
        "organizational_evidence": row.get("organizational_evidence") or [],
        "evidence_state_after": row.get("evidence_state_after") or {},
        "remaining_gaps": row.get("remaining_gaps") or [],
        "requires_human_confirmation": bool(row.get("requires_human_confirmation")),
        "retrieval_skipped_reason": row.get("retrieval_skipped_reason"),
    }


def _requirement_evidence_context(bid_id: int, req_id: str) -> tuple:
    """Shared by OM-3B (strengthen_requirement_evidence_for_organization)
    and PI-3A (draft_section_for_organization): the requirement's latest
    usable Proposal Intelligence assessment row for `req_id` (or None) and
    every finding from that SAME run related to `req_id`. Never triggers a
    new Proposal Intelligence run -- read-only against the latest
    already-COMPLETE/INCOMPLETE run, exactly as before this was factored
    out (no behavior change, see git history)."""
    assessment = None
    related_findings = []
    run = db.get_latest_usable_proposal_intelligence_run(bid_id)
    if run is not None:
        assessments = db.get_proposal_requirement_assessments(run["id"])
        assessment = next((a for a in assessments if a.get("req_id") == req_id), None)
        findings = db.get_proposal_intelligence_findings(run["id"])
        related_findings = [f for f in findings if f.get("related_req_id") == req_id]
    return assessment, related_findings


def _requirement_evidence_state_from_assessment(assessment: dict | None, related_findings: list):
    """assessment/related_findings (from _requirement_evidence_context)
    -> evidence_strengthening.RequirementEvidenceState -- the SAME
    construction strengthen_requirement_evidence_for_organization always
    performed inline, now shared with PI-3A's brief assembly."""
    import evidence_strengthening as es
    import proposal_intelligence as pi

    has_contradiction = any(
        f.get("finding_type") in (pi.FINDING_TYPE_CONTRADICTION, pi.FINDING_TYPE_INTERNAL_INCONSISTENCY)
        for f in related_findings
    )
    return es.RequirementEvidenceState(
        assessment_status=(assessment or {}).get("assessment_status"),
        evidence_strength=(assessment or {}).get("evidence_strength"),
        has_contradiction_finding=has_contradiction,
    )


def strengthen_requirement_evidence_for_organization(
    bid_id: int, organization_id: str, requirement_id: int,
    top_k: int = 5, embed_fn=None, created_by_user_id: str | None = None,
) -> dict:
    """OM-3B: "reason once, persist structured intelligence, reuse
    downstream" -- the requirement-aware Organizational Memory strengthening
    boundary (evidence_strengthening.strengthen_requirement_evidence), wired
    to real, durable persistence (migrations/017_requirement_evidence_
    enrichment.sql). Verifies bid ownership FIRST, before any read.

    Derives the requirement's CURRENT-BID evidence state (hierarchy tier 2)
    entirely from its own canonical row (database.get_requirements_by_ids,
    defensively bid_id-scoped) and its latest usable Proposal Intelligence
    assessment/findings -- never from Organizational Memory, and never from
    a caller-supplied query.

    An already-sufficient requirement (evidence_state.needs_strengthening is
    False) is answered directly, exactly like OM-3A -- it never reads
    organizational_memory_items, never computes a fingerprint, and is never
    persisted (nothing worth caching).

    Otherwise: the freshness CHECK itself must stay cheap -- it fetches
    ONLY the organization-scoped Organizational Memory candidate pool's
    IDENTITY (database.list_organizational_memory_item_identities:
    id/memory_class/content_hash, never content/embedding/metadata/
    provenance text), computes evidence_strengthening.compute_input_
    fingerprint() over the requirement/evidence-state/candidate-identity
    set, and checks this requirement's PERSISTED history (database.
    get_requirement_evidence_enrichments) for a row matching that EXACT
    fingerprint. A match is returned directly -- this is a genuine cheap
    metadata query, never a semantic retrieval or model call, and a cache
    HIT never once calls list_organizational_memory_items (the full-row
    read) at all. No match means the requirement text, its current-bid
    evidence state, or the relevant Organizational Memory pool has
    materially changed (or this requirement has never been enriched) --
    ONLY THEN does this function fetch the full candidate rows (content
    included -- genuinely required for retrieval/ranking and the
    adjudication prompt) and call evidence_strengthening.
    strengthen_requirement_evidence() to recompute, reusing the SAME
    fingerprint already computed from the identity pass (never
    recomputed a second time, so a miss can never persist under a
    different fingerprint than the one it was found stale against), then
    persists via database.get_or_create_requirement_evidence_enrichment
    (concurrency-safe; a race against another caller computing the SAME
    fingerprint returns the winner's row, never a duplicate). A genuine
    exception during recomputation propagates to the caller WITHOUT
    writing anything -- any previously persisted row for a different
    (now-stale) fingerprint is left completely untouched, never corrupted
    or silently replaced by a failed attempt.

    Read-only with respect to Organizational Memory end to end: writes
    nothing to organizational_memory_items, mutates no Organizational
    Memory item, creates no APPROVED_FIRM_KNOWLEDGE row, drafts no proposal
    text. The only table this function ever writes to is
    requirement_evidence_enrichments itself."""
    require_bid_access(bid_id, organization_id)
    if not organization_id:
        raise ValueError(
            "strengthen_requirement_evidence_for_organization requires an explicit organization_id")

    import evidence_strengthening as es
    import organizational_memory as om

    reqs = db.get_requirements_by_ids(bid_id, [requirement_id])
    if not reqs:
        raise ValueError(
            f"strengthen_requirement_evidence_for_organization: requirement {requirement_id} "
            f"not found for bid {bid_id}")
    requirement = reqs[0]
    req_id = requirement.get("req_id")

    _assessment, _related_findings = _requirement_evidence_context(bid_id, req_id)
    evidence_state = _requirement_evidence_state_from_assessment(_assessment, _related_findings)

    if not evidence_state.needs_strengthening:
        result = es.strengthen_requirement_evidence(
            organization_id=organization_id, bid_id=bid_id, requirement=requirement,
            evidence_state=evidence_state, candidate_items=[],
        )
        return result.to_dict()

    identity_rows = []
    for memory_class in (om.MemoryClass.APPROVED_FIRM_KNOWLEDGE.value, om.MemoryClass.SOURCE_MEMORY.value):
        identity_rows.extend(
            db.list_organizational_memory_item_identities(organization_id, memory_class=memory_class))
    candidate_identities = [
        _MemoryItemIdentity(
            id=str(row["id"]), memory_class=om.MemoryClass(row["memory_class"]),
            item_content_hash=row.get("content_hash"),
        )
        for row in identity_rows
    ]

    fingerprint = es.compute_input_fingerprint(requirement, evidence_state, candidate_identities)

    # Reuse: search this requirement's FULL persisted history (bid-scoped,
    # never another bid's rows -- database.get_requirement_evidence_
    # enrichments already filters by bid_id) for a row matching the exact
    # fingerprint just computed. A match means retrieval and the
    # adjudication model call are both skipped entirely -- and note this
    # entire check above never read a single memory item's content.
    for existing_row in db.get_requirement_evidence_enrichments(bid_id, req_id):
        if existing_row.get("input_fingerprint") == fingerprint:
            return _enrichment_row_to_dict(existing_row)

    # No fresh row -- recompute. Only now is the FULL candidate pool
    # (content/embedding included) actually read -- genuinely required for
    # retrieval/ranking and the adjudication prompt, unlike the identity-
    # only fetch above. Reuses the SAME `fingerprint` already computed;
    # never recomputed from the full rows. Any exception here propagates
    # untouched; nothing is written below unless this call returns
    # successfully, so a failed attempt can never corrupt or replace a
    # prior valid row.
    rows = []
    for memory_class in (om.MemoryClass.APPROVED_FIRM_KNOWLEDGE.value, om.MemoryClass.SOURCE_MEMORY.value):
        rows.extend(db.list_organizational_memory_items(organization_id, memory_class=memory_class))
    candidate_items = [_row_to_memory_item(row) for row in rows]

    result = es.strengthen_requirement_evidence(
        organization_id=organization_id, bid_id=bid_id, requirement=requirement,
        evidence_state=evidence_state, candidate_items=candidate_items,
        top_k=top_k, embed_fn=embed_fn,
    )

    persisted = db.get_or_create_requirement_evidence_enrichment(
        bid_id=bid_id, req_id=req_id, input_fingerprint=fingerprint,
        contract_version=es.EVIDENCE_STRENGTHENING_CONTRACT_VERSION,
        evidence_state_before=result.evidence_state_before,
        evidence_state_after=result.evidence_state_after,
        requirement_id=result.requirement_id,
        organizational_evidence=[c.to_dict() for c in result.organizational_evidence],
        remaining_gaps=list(result.remaining_gaps),
        requires_human_confirmation=result.requires_human_confirmation,
        retrieval_skipped_reason=result.retrieval_skipped_reason,
        created_by_user_id=created_by_user_id,
    )
    if persisted is None:
        # Persistence itself failed -- still return the freshly computed,
        # correct result rather than losing it; only the cache for next
        # time is missing, nothing about this response is wrong.
        return result.to_dict()
    return _enrichment_row_to_dict(persisted)


# ═══════════════════════════════════════════════════════════════════════════
# Proposal Intelligence (PI-3A: evidence-aware section drafting)
# ═══════════════════════════════════════════════════════════════════════════

def draft_section_for_organization(
    bid_id: int, organization_id: str, requirement_id: int,
    outline_section: dict | None = None,
    max_related_requirements: int = 5, max_findings: int = 5,
) -> dict:
    """PI-3A: evidence-aware section drafting for ONE requirement, wired to
    real, already-persisted intelligence. Verifies bid ownership FIRST.

    Assembles a bounded section_drafting.SectionDraftingBrief from
    EXISTING, ALREADY-COMPUTED intelligence only:
      - the requirement's own canonical row (database.get_requirements_by_ids,
        bid-scoped);
      - sibling requirements sharing the same category, context only
        (database.get_requirements), capped at max_related_requirements;
      - the requirement's latest Proposal Intelligence assessment/findings
        (tier 2), via the SAME _requirement_evidence_context/
        _requirement_evidence_state_from_assessment helpers OM-3B uses --
        never re-run here;
      - Fast Analysis's evaluation_criteria/response_guidelines, via
        section_analyzer.procurement_basis plus the SAME matching
        functions section_analyzer.build_section_context already uses
        (section_analyzer._match_evaluation_criterion/
        _matching_response_guideline -- reused, not reimplemented; never
        re-runs Fast Analysis itself, only reads an already-persisted raw
        snapshot exactly like section_analyzer.procurement_basis always
        has);
      - the requirement's LATEST ALREADY-PERSISTED OM-3B enrichment
        (database.get_requirement_evidence_enrichments) -- this function
        NEVER triggers a fresh OM-3A/OM-3B computation. A caller that
        wants fresh Organizational Memory enrichment first must call
        strengthen_requirement_evidence_for_organization separately, as
        its own prior step ("analyze once, persist, draft from persisted
        intelligence" -- instruction 6);
      - `outline_section`, ONLY when the caller supplies one (an
        outline_sections row/dict) for word_limit/title/notes -- never
        fetched by this function itself, so this has no dependency on
        migration 013's (still unapplied) outline_section_requirements
        mapping table.

    Then calls section_drafting.draft_section() (the ONE new bounded model
    call) and section_drafting.assure_section_draft() (bounded,
    deterministic, no second model call). Returns
    {"brief", "result", "assurance"} as plain dicts.

    Read-only end to end: writes nothing anywhere, mutates no
    Organizational Memory item, creates no requirement_evidence_
    enrichments row, persists no draft -- PI-3A is compute-and-return only
    (see docs/current/SYSTEM_STATE.md)."""
    require_bid_access(bid_id, organization_id)
    if not organization_id:
        raise ValueError("draft_section_for_organization requires an explicit organization_id")

    import section_drafting as sd

    reqs = db.get_requirements_by_ids(bid_id, [requirement_id])
    if not reqs:
        raise ValueError(
            f"draft_section_for_organization: requirement {requirement_id} not found for bid {bid_id}")
    requirement = reqs[0]
    req_id = requirement.get("req_id")

    all_requirements = db.get_requirements(bid_id)
    related = [
        r for r in all_requirements
        if r.get("category") == requirement.get("category") and r.get("id") != requirement.get("id")
    ]

    assessment, related_findings = _requirement_evidence_context(bid_id, req_id)
    evidence_state = _requirement_evidence_state_from_assessment(assessment, related_findings)

    evaluation_criterion = None
    response_guideline = None
    try:
        import section_analyzer as sa
        basis = sa.procurement_basis(bid_id)
        raw = basis.get("raw_snapshot")
        if raw is not None:
            evaluation_criteria = raw.evaluation_criteria or []
            response_guidelines = raw.deterministic_response_guidelines or []
            evaluation_criterion = sa._match_evaluation_criterion(requirement, evaluation_criteria)
            if evaluation_criterion:
                response_guideline = sa._matching_response_guideline(
                    evaluation_criterion, evaluation_criteria, response_guidelines)
    except Exception:
        # Advisory-only context (exactly like section_analyzer.
        # procurement_basis's own treatment of evaluation/response-
        # guideline data) -- a failure to resolve it must never block
        # drafting, only omit this optional context.
        evaluation_criterion = None
        response_guideline = None

    enrichment_history = db.get_requirement_evidence_enrichments(bid_id, req_id)
    persisted_enrichment = enrichment_history[0] if enrichment_history else None

    response_constraints = sd.ResponseConstraints(
        word_limit=(outline_section or {}).get("word_limit"),
        section_title=(outline_section or {}).get("title"),
        section_guidance=(outline_section or {}).get("notes"),
    )

    brief = sd.build_brief(
        organization_id=organization_id, bid_id=bid_id, requirement=requirement,
        related_requirements=related, evaluation_criterion=evaluation_criterion,
        response_guideline=response_guideline, evidence_state=evidence_state.to_dict(),
        assessment=assessment, persisted_enrichment=persisted_enrichment,
        proposal_intelligence_findings=related_findings,
        response_constraints=response_constraints,
        max_related_requirements=max_related_requirements, max_findings=max_findings,
    )

    result = sd.draft_section(brief=brief)
    assurance = sd.assure_section_draft(brief, result)

    return {"brief": brief.to_dict(), "result": result.to_dict(), "assurance": assurance.to_dict()}
