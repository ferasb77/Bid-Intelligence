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

from dataclasses import dataclass, field

import database as db

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
