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
        reqs = sb.table("requirements").select("id,status").eq("bid_id", b["id"]).execute().data or []
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
    them) -- tenant-authorized immediately before the privileged call."""
    require_bid_access(bid_id, organization_id)
    db.upsert_bid_brief(data)


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
        reqs = client.table("requirements").select("id,status").eq("bid_id", b["id"]).execute().data or []
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
def get_requirements_authenticated(access_token: str, bid_id: int) -> list[dict]:
    client = auth_client.get_authenticated_client(access_token)
    return (
        client.table("requirements").select("*").eq("bid_id", bid_id)
        .order("category").order("req_id").execute().data or []
    )


def upsert_requirement_authenticated(access_token: str, data: dict) -> None:
    client = auth_client.get_authenticated_client(access_token)
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
    reqs = client.table("requirements").select("category,status").eq("bid_id", bid_id).execute().data or []
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
