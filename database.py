"""
Bid Intelligence Platform — Supabase database layer.
Replaces SQLite. All data persists across Streamlit Cloud redeploys.
File uploads go to Supabase Storage.

Phase 8 remediation package 3: this module's client is the PRIVILEGED
SERVICE-ROLE client -- it bypasses RLS by definition and must never be
confused with the user-scoped, RLS-respecting client
(auth_client.py:get_authenticated_client()). get_service_client() is the
explicit, unambiguous name for what get_client() has always done; get_client()
is kept as-is (same function, not a copy) so none of this module's ~60
existing call sites need to change -- see get_service_client()'s own
docstring and tests/test_auth_tenancy.py's TestAuthDataClientSeparation for
the regression guard that keeps these two clients from ever sharing a
credential.
"""
import os
import streamlit as st
from supabase import create_client, Client

# ── Connection ────────────────────────────────────────────────────────────────
def get_client() -> Client:
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
    except Exception:
        pass
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_SERVICE_KEY"]
    except Exception:
        url = os.getenv("SUPABASE_URL","")
        key = os.getenv("SUPABASE_SERVICE_KEY", os.getenv("SUPABASE_KEY",""))
    if not url or not key:
        raise RuntimeError(
            "Supabase credentials not found. Add SUPABASE_URL and "
            "SUPABASE_SERVICE_KEY to Streamlit secrets or .env file.")
    return create_client(url, key)


def get_service_client() -> Client:
    """Explicit-name alias for get_client() -- the privileged, RLS-bypassing
    service-role client. Prefer this name in any new code so privileged and
    user-scoped access are difficult to confuse at a glance (instruction 14);
    existing call sites are not required to migrate off get_client()."""
    return get_client()

BUCKET = "bid-documents"

def init_db():
    """No-op — schema is created via supabase_schema.sql in Supabase dashboard."""
    pass

# ── Generic helpers ───────────────────────────────────────────────────────────
def _rows(response) -> list:
    return response.data or []

def _one(response):
    data = response.data
    return data[0] if data else None

# ── Bids ──────────────────────────────────────────────────────────────────────
def get_all_bids():
    sb = get_client()
    bids = _rows(sb.table("bids").select("*").order("submission_deadline").execute())
    for b in bids:
        b["id"] = int(b["id"])
        reqs  = _rows(sb.table("requirements").select("id,status").eq("bid_id", b["id"])
                      .eq("lifecycle_status", "active").execute())
        tasks = _rows(sb.table("tasks").select("id,status").eq("bid_id", b["id"]).execute())
        b["req_count"]  = len(reqs)
        b["req_done"]   = sum(1 for r in reqs if r["status"]=="Complete")
        b["task_count"] = len(tasks)
        b["task_done"]  = sum(1 for t in tasks if t["status"]=="Complete")
    return bids

def get_bid(bid_id):
    return _one(get_client().table("bids").select("*").eq("id", bid_id).execute())

_LEGACY_ORGANIZATION_SLUG = "emg-internal"

def _resolve_legacy_organization_id(sb):
    """PRE-AUTH DEVELOPMENT-ONLY COMPATIBILITY PATH (Phase 8 remediation
    package 2; status re-evaluated and RETAINED in package 3).

    As of Phase 8 remediation package 3, the NORMAL INTERACTIVE application
    no longer calls create_bid() at all -- both of app.py's bid-creation
    call sites (the manual form and the extracted-package review) now call
    tenancy.create_bid_for_organization() directly, with the authenticated
    caller's real, resolved organization_id -- never inferred, never
    defaulted to this legacy org. The mandatory auth gate in app.py
    guarantees no unauthenticated request ever reaches those call sites.

    This function -- and create_bid() below -- is kept ONLY because
    create_bid() still has real, demonstrated internal (non-interactive,
    non-user) callers that are out of scope for this package to touch:
    tests/acceptance/populate_supabase_and_stats.py,
    tests/acceptance/process_frozen_pipeline.py,
    tests/acceptance/run_blind_acceptance.py, and the live smoke tests in
    tests/smoke/test_live_supabase_migration_003.py (which this exact
    compatibility path was written in package 2 to keep passing against
    the live database once bids.organization_id became NOT NULL). Removing
    this now would break all of them for no corresponding benefit, since
    they are test/acceptance infrastructure, not the interactive UI this
    package's cutover was about. Per the package 3 instruction's own
    criterion ('retain only if you can demonstrate a still-required
    internal non-user path; otherwise remove it') -- this demonstrates
    exactly that, so it is retained, not removed.

    This resolves the legacy organization by its known, deterministic
    slug (never a hardcoded UUID). This is the ONLY place in the codebase
    allowed to do this; tenancy.py's own create_bid_for_organization()
    explicitly never references this slug (tests/test_auth_tenancy.py
    enforces that)."""
    row = _one(sb.table("organizations").select("id").eq("slug", _LEGACY_ORGANIZATION_SLUG).execute())
    return row["id"] if row else None

def create_bid(data):
    clean = {k: data.get(k) for k in
             ["title","client","file_number","stage","sensitivity","owner",
              "value_cad","submission_deadline","clarification_deadline","notes"]}
    sb = get_client()
    legacy_org_id = _resolve_legacy_organization_id(sb)
    if legacy_org_id:
        clean["organization_id"] = legacy_org_id
    row = _one(sb.table("bids").insert(clean).execute())
    return int(row["id"]) if row else None

def update_bid(bid_id, data):
    """Partial update: only writes keys the caller actually included in
    `data`. A key that's absent is left untouched on the row; a key that's
    present with value None is written as NULL -- several call sites (the
    Edit Bid form, in particular) rely on that explicit-None-means-clear
    semantic for value_cad/submission_deadline/clarification_deadline, so
    presence (not truthiness) is what decides inclusion here."""
    keys = ["title","client","file_number","stage","sensitivity","owner",
            "value_cad","submission_deadline","clarification_deadline","notes"]
    clean = {k: data[k] for k in keys if k in data}
    if not clean:
        return
    get_client().table("bids").update(clean).eq("id", bid_id).execute()

def delete_bid(bid_id):
    get_client().table("bids").delete().eq("id", bid_id).execute()

# ── Requirements ──────────────────────────────────────────────────────────────
def get_requirements(bid_id, include_retired: bool = False):
    """Migration 010: current-truth reads default to lifecycle_status='active'
    only -- a superseded/removed requirement (retired via a governed
    procurement_changes apply) must never silently continue participating
    in scoring, qualification gates, or compliance display. Pass
    include_retired=True only for an explicit history/audit view that
    genuinely wants to see retired rows too."""
    query = get_client().table("requirements").select("*").eq("bid_id", bid_id)
    if not include_retired:
        query = query.eq("lifecycle_status", "active")
    return _rows(query.order("category").order("req_id").execute())


def get_requirements_by_ids(bid_id: int, requirement_ids: list[int]) -> list[dict]:
    """Fetch a specific set of requirements by internal id, scoped to
    bid_id defensively (a requirement_id passed to this function must
    actually belong to the bid it's being used for -- callers never trust
    an id list without this). Returns [] for an empty/None id list rather
    than querying with an empty IN clause."""
    if not requirement_ids:
        return []
    return _rows(get_client().table("requirements").select("*")
                .eq("bid_id", bid_id).in_("id", list(requirement_ids)).execute())


class GovernedRequirementMutationError(Exception):
    """Raised when a direct (non-governed) write would change a canonical
    procurement-truth field on a requirement belonging to a bid whose
    procurement_truth_status is 'governed'. Once governed, canonical
    requirement facts (what the buyer's procurement actually requires) may
    change only through the procurement-governance RPCs (migration 010) --
    see tenancy.propose_procurement_changes_for_organization() /
    apply_procurement_update_review_for_organization(). Supplier-side
    assessment fields (qual_status, evidence_status, owner, gap_action,
    qual_notes, status, deadline, notes) are never blocked -- they track
    OUR compliance posture against an unchanged requirement, not the
    requirement's own definition, and remain freely editable regardless of
    governance state."""


# The requirement fields that describe WHAT the buyer's procurement
# actually requires -- exactly the fields apply_procurement_update_review()
# writes for an ADDED/MODIFIED change (migration 010, PART 3). Any other
# field on `requirements` is supplier-side/administrative and is never
# gated by governance state.
_CANONICAL_REQUIREMENT_FIELDS = {"description", "category", "rfso_ref", "weight"}


def _bid_is_governed(sb, bid_id) -> bool:
    if bid_id is None:
        return False
    row = _one(sb.table("bids").select("procurement_truth_status").eq("id", bid_id).execute())
    return bool(row) and row.get("procurement_truth_status") == "governed"


def _guard_canonical_requirement_write(sb, data: dict) -> None:
    """Call before any direct (non-RPC) write to `requirements` that could
    touch a canonical field. Resolves bid_id from the payload, or from the
    target row when only an id is given (an UPDATE need not repeat bid_id).
    No-ops if the bid is not yet governed (the legitimate
    ungoverned-baseline-construction path).

    Critically, for an UPDATE this compares against the CURRENT stored
    value of each canonical field, not merely whether the key is PRESENT
    in `data` -- the only live caller of upsert_requirement()
    (stage_decide.py's Assess Requirement drawer) spreads the FULL
    existing row (`**target_req`) and only actually intends to change
    supplier-side assessment fields; description/category/rfso_ref/weight
    are present in that payload, unchanged, on every single save. Treating
    mere key-presence as an edit would incorrectly block that page's only
    live requirement-editing UI the moment a bid becomes governed. A
    brand-new INSERT (no `id`) has nothing to compare against, so any
    canonical field supplied there is always a real write of that field."""
    canonical_fields = _CANONICAL_REQUIREMENT_FIELDS & set(data.keys())
    if not canonical_fields:
        return
    bid_id = data.get("bid_id")
    req_id = data.get("id")
    if req_id:
        current = _one(sb.table("requirements").select(
            "bid_id," + ",".join(sorted(_CANONICAL_REQUIREMENT_FIELDS))
        ).eq("id", req_id).execute())
        if not current:
            return
        if bid_id is None:
            bid_id = current.get("bid_id")
        canonical_fields = {f for f in canonical_fields if data.get(f) != current.get(f)}
        if not canonical_fields:
            return
    if _bid_is_governed(sb, bid_id):
        raise GovernedRequirementMutationError(
            "This bid's procurement truth is already governed -- "
            f"{sorted(canonical_fields)} can only change through a governed procurement review "
            "(Procurement Documents & Addenda), not a direct edit."
        )


def format_requirement_payload(data, keys):
    """Format payload for requirements table. Preserves native list/dict for JSONB source_refs."""
    clean = {}
    for k in keys:
        if k in data:
            v = data.get(k)
            if k == "source_refs":
                # JSONB column: pass Python list/dict directly to Supabase client
                clean[k] = v if isinstance(v, (list, dict)) else ([] if v is None else v)
            else:
                clean[k] = v
    return clean

def upsert_requirement(data):
    sb = get_client()
    _guard_canonical_requirement_write(sb, data)
    keys_with_integrity = ["req_id","category","description","rfso_ref","weight",
                           "evidence","owner","deadline","status","notes",
                           "qual_status","gap_action","qual_notes",
                           "evidence_status","source_refs"]
    keys_with_qual = ["req_id","category","description","rfso_ref","weight",
                      "evidence","owner","deadline","status","notes",
                      "qual_status","gap_action","qual_notes"]
    keys_basic = ["req_id","category","description","rfso_ref","weight",
                  "evidence","owner","deadline","status","notes"]

    def _do_upsert(keys):
        clean = format_requirement_payload(data, keys)
        if data.get("id"):
            sb.table("requirements").update(clean).eq("id", data["id"]).execute()
        else:
            if "bid_id" in data:
                clean["bid_id"] = data["bid_id"]
            sb.table("requirements").insert(clean).execute()

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

def delete_requirement(req_id):
    sb = get_client()
    row = _one(sb.table("requirements").select("bid_id").eq("id", req_id).execute())
    if row and _bid_is_governed(sb, row.get("bid_id")):
        raise GovernedRequirementMutationError(
            "This bid's procurement truth is already governed -- requirements can only be retired "
            "through a governed procurement review (Procurement Documents & Addenda), never deleted directly."
        )
    sb.table("requirements").delete().eq("id", req_id).execute()

# ── Tasks ─────────────────────────────────────────────────────────────────────
def get_tasks(bid_id):
    return _rows(get_client().table("tasks")
                 .select("*").eq("bid_id", bid_id)
                 .order("due_date").order("priority").execute())

def upsert_task(data):
    sb = get_client()
    keys = ["title","description","owner","due_date","priority","status"]
    if data.get("id"):
        sb.table("tasks").update({k: data.get(k) for k in keys}).eq("id", data["id"]).execute()
    else:
        sb.table("tasks").insert({k: data.get(k) for k in ["bid_id"] + keys}).execute()

def delete_task(task_id):
    get_client().table("tasks").delete().eq("id", task_id).execute()

# ── Documents ─────────────────────────────────────────────────────────────────
def get_documents(bid_id):
    return _rows(get_client().table("documents")
                 .select("*").eq("bid_id", bid_id)
                 .order("doc_type").order("name").execute())

def upsert_document(data):
    sb = get_client()
    keys = ["name","doc_type","owner","due_date","status","notes",
            "linked_req_ids","mandatory","file_path","file_size",
            "storage_path","version"]
    if data.get("id"):
        clean = {k: data.get(k) for k in keys if data.get(k) is not None}
        sb.table("documents").update(clean).eq("id", data["id"]).execute()
    else:
        clean = {k: data.get(k) for k in ["bid_id"] + keys}
        sb.table("documents").insert(clean).execute()

def delete_document(doc_id):
    get_client().table("documents").delete().eq("id", doc_id).execute()

def get_document_versions(doc_id):
    return _rows(get_client().table("document_versions")
                 .select("*").eq("document_id", doc_id)
                 .order("version", desc=True).execute())

def create_expected_document(bid_id, name, doc_type, owner=None,
                              due_date=None, linked_req_ids=None,
                              mandatory=0, notes=""):
    row = _one(get_client().table("documents").insert({
        "bid_id": bid_id, "name": name, "doc_type": doc_type,
        "owner": owner, "due_date": due_date,
        "linked_req_ids": linked_req_ids,
        "mandatory": mandatory, "status": "Expected", "notes": notes,
        "version": 1,
    }).execute())
    return int(row["id"]) if row else None

def save_upload(bid_id, filename, file_bytes, doc_type="RFP / Source",
                owner=None, doc_id=None):
    """Upload file to Supabase Storage and create/update document record.
    Migration 010: content_hash is computed server-side from the exact raw
    uploaded bytes (never trusted from the browser) and persisted at
    creation/upload time -- this is the ONLY place a NEW document's hash
    is established. A re-upload against an existing doc_id (a genuinely
    new version, different bytes) gets its own fresh hash; this is
    distinct from ensure_document_hash()'s lazy legacy-document path,
    which only ever fills a NULL hash for bytes that already existed
    before migration 010 and never overwrites a hash once set."""
    sb = get_client()
    content_hash = hash_document_bytes(file_bytes)

    # Build storage path
    import uuid
    ext = os.path.splitext(filename)[1]
    unique_name = f"{bid_id}/{uuid.uuid4().hex}{ext}"

    # Upload to Supabase Storage
    try:
        sb.storage.from_(BUCKET).upload(
            unique_name, file_bytes,
            file_options={"content-type": "application/octet-stream",
                          "upsert": "true"})
        storage_path = unique_name
        # Get public/signed URL as file_path proxy
        file_path = f"supabase://{BUCKET}/{unique_name}"
    except Exception:
        # Fallback: save locally if storage fails
        upload_dir = os.path.join(os.path.dirname(__file__), "uploads", str(bid_id))
        os.makedirs(upload_dir, exist_ok=True)
        local_path = os.path.join(upload_dir, filename)
        with open(local_path, "wb") as f:
            f.write(file_bytes)
        storage_path = None
        file_path = local_path

    if doc_id:
        # Version update — archive current
        doc = _one(sb.table("documents").select("*").eq("id", doc_id).execute())
        if doc:
            new_ver = (doc.get("version") or 1) + 1
            sb.table("document_versions").insert({
                "document_id": doc_id,
                "version": doc.get("version", 1),
                "file_path": doc.get("file_path"),
                "storage_path": doc.get("storage_path"),
                "file_size": doc.get("file_size") or 0,
                "is_current": 0,
            }).execute()
            sb.table("documents").update({
                "file_path": file_path,
                "storage_path": storage_path,
                "file_size": len(file_bytes),
                "version": new_ver,
                "status": "Uploaded",
                "content_hash": content_hash,
            }).eq("id", doc_id).execute()
        return file_path, doc_id
    else:
        row = _one(sb.table("documents").insert({
            "bid_id": bid_id, "name": filename,
            "doc_type": doc_type, "owner": owner,
            "file_path": file_path, "storage_path": storage_path,
            "file_size": len(file_bytes), "version": 1,
            "status": "Uploaded",
            "content_hash": content_hash,
        }).execute())
        new_id = int(row["id"]) if row else None
        return file_path, new_id

def download_file(storage_path: str) -> bytes:
    """Download file bytes from Supabase Storage."""
    sb = get_client()
    try:
        response = sb.storage.from_(BUCKET).download(storage_path)
        return response
    except Exception:
        return None

def get_signed_url(storage_path: str, expires_in: int = 3600) -> str:
    """Get a temporary signed URL for a stored file."""
    sb = get_client()
    try:
        result = sb.storage.from_(BUCKET).create_signed_url(storage_path, expires_in)
        return result.get("signedURL") or result.get("signedUrl","")
    except Exception:
        return ""

# ── Outline ───────────────────────────────────────────────────────────────────
def get_outline(bid_id):
    return _rows(get_client().table("outline_sections")
                 .select("*").eq("bid_id", bid_id)
                 .order("sort_order").execute())

def upsert_section(data):
    sb = get_client()
    keys = ["sort_order","section_num","title","owner","word_limit","status","notes"]
    if data.get("id"):
        sb.table("outline_sections").update(
            {k: data.get(k) for k in keys}).eq("id", data["id"]).execute()
    else:
        sb.table("outline_sections").insert(
            {k: data.get(k) for k in ["bid_id"] + keys}).execute()

def delete_section(sec_id):
    get_client().table("outline_sections").delete().eq("id", sec_id).execute()


# ── Section Analyzer: durable requirement mapping & review history ────────────
# migrations/013_section_analyzer.sql. The durable replacement for the
# session-state-only "Mapped Requirements" multiselect in
# pages/stage_build.py -- see section_analyzer.py for how these are used.

def get_section_requirement_ids(section_id: int) -> list[int]:
    rows = _rows(get_client().table("outline_section_requirements")
                .select("requirement_id").eq("section_id", section_id).execute())
    return [r["requirement_id"] for r in rows]


def set_section_requirement_mapping(bid_id: int, section_id: int, requirement_ids: list[int]) -> None:
    """Replace-ALL semantics for one section's mapping, matching the UI
    multiselect's own "this IS the current set" behavior exactly -- not an
    incremental add/remove. Deletes then reinserts inside no explicit
    transaction (Supabase's REST client has no cross-statement transaction
    control here); the delete-then-insert order means a mid-failure can
    only ever leave the mapping temporarily EMPTY, never duplicated or
    pointing at stale ids -- an acceptable, self-healing failure mode for
    a re-savable mapping (unlike section_reviews, which must never be
    partially written)."""
    sb = get_client()
    sb.table("outline_section_requirements").delete().eq("section_id", section_id).execute()
    if requirement_ids:
        sb.table("outline_section_requirements").insert([
            {"bid_id": bid_id, "section_id": section_id, "requirement_id": rid}
            for rid in sorted(set(requirement_ids))
        ]).execute()


def create_section_review(data: dict) -> dict | None:
    """Insert-only -- section_reviews rows are immutable (instruction 11);
    no update_section_review/delete_section_review function exists on
    purpose. Returns the inserted row (echoed back by Supabase), or None
    if the insert failed."""
    keys = ["bid_id", "section_id", "section_content_snapshot", "section_content_hash",
            "mapped_requirement_ids", "based_on_procurement_revision",
            "based_on_procurement_truth_status", "based_on_analysis_run_id",
            "based_on_analysis_result_id", "raw_snapshot_schema_version",
            "review_schema_version", "direction", "review_result", "created_by_user_id"]
    clean = {k: data.get(k) for k in keys}
    return _one(get_client().table("section_reviews").insert(clean).execute())


def get_section_reviews(bid_id: int, section_id: int) -> list[dict]:
    """Most recent first -- callers that want "the current review" take
    index 0 after their own staleness check; callers building history UI
    use the full ordered list as-is."""
    return _rows(get_client().table("section_reviews").select("*")
                .eq("bid_id", bid_id).eq("section_id", section_id)
                .order("created_at", desc=True).execute())


# ── Readiness ─────────────────────────────────────────────────────────────────
def get_readiness(bid_id):
    sb   = get_client()
    reqs = _rows(sb.table("requirements").select("category,status").eq("bid_id", bid_id)
                 .eq("lifecycle_status", "active").execute())
    tsks = _rows(sb.table("tasks").select("status").eq("bid_id", bid_id).execute())
    docs = _rows(sb.table("documents").select("doc_type,status").eq("bid_id", bid_id).execute())
    mand = [r for r in reqs if r["category"]=="Mandatory"]
    rated= [r for r in reqs if r["category"]!="Mandatory"]
    sub  = [d for d in docs if d["doc_type"]=="Submission"]
    return {
        "m_total": len(mand),
        "m_done":  sum(1 for r in mand  if r["status"]=="Complete"),
        "r_total": len(rated),
        "r_done":  sum(1 for r in rated if r["status"]=="Complete"),
        "t_total": len(tsks),
        "t_done":  sum(1 for t in tsks  if t["status"]=="Complete"),
        "d_total": len(sub),
        "d_done":  sum(1 for d in sub   if d["status"] in ("Uploaded","Approved","Submitted","Complete")),
    }

# ── Deliverables ──────────────────────────────────────────────────────────────
def get_deliverables(bid_id):
    return _rows(get_client().table("deliverables")
                 .select("*").eq("bid_id", bid_id)
                 .order("sort_order").order("category").execute())

def upsert_deliverable(data):
    sb = get_client()
    keys = ["sort_order","service_id","title","description","category",
            "duration","volume","unit","price_ai","price_non_ai",
            "optional","linked_req_ids","notes"]
    if data.get("id"):
        sb.table("deliverables").update(
            {k: data.get(k) for k in keys}).eq("id", data["id"]).execute()
    else:
        sb.table("deliverables").insert(
            {k: data.get(k) for k in ["bid_id"] + keys}).execute()

def delete_deliverable(del_id):
    get_client().table("deliverables").delete().eq("id", del_id).execute()

# ── Content Library ───────────────────────────────────────────────────────────
def get_library_items(bid_id=None, category=None):
    sb = get_client()
    q  = sb.table("content_library").select("*")
    if bid_id:
        q = q.or_(f"bid_id.eq.{bid_id},bid_id.is.null")
    if category:
        q = q.eq("category", category)
    return _rows(q.order("category").order("title").execute())

def upsert_library_item(data: dict) -> None:
    """Save a library item. Generates and stores an embedding if Voyage is configured."""
    sb = get_client()

    # Generate embedding if content/title present and Voyage is configured
    if data.get("content") or data.get("title"):
        try:
            from embeddings import embed_library_item, voyage_configured
            if voyage_configured():
                emb = embed_library_item(data)
                if emb:
                    data = {**data, "embedding": emb}
        except Exception:
            pass  # embedding failure is non-fatal

    # Try saving with embedding column first; fall back without it if column missing
    keys_with_emb    = ["title", "category", "content", "source", "bid_id",
                         "tags", "approved", "notes", "embedding"]
    keys_without_emb = ["title", "category", "content", "source", "bid_id",
                         "tags", "approved", "notes"]

    def _do_upsert(keys):
        row = {k: data.get(k) for k in keys}
        if data.get("id"):
            sb.table("content_library").update(row).eq("id", data["id"]).execute()
        else:
            sb.table("content_library").insert(row).execute()

    try:
        _do_upsert(keys_with_emb)
    except Exception as e:
        err = str(e).lower()
        # Column doesn't exist yet — retry without embedding field
        if "embedding" in err or "column" in err or "schema" in err or "apierror" in err:
            _do_upsert(keys_without_emb)
        else:
            raise


def semantic_library_search(
    query: str,
    bid_id: str = None,
    top_k: int = 5,
) -> tuple[list[dict], bool]:
    """
    Return the top_k most semantically relevant library items for a query.
    Returns (items, used_semantic) — used_semantic=False means keyword fallback.
    """
    items = get_library_items(bid_id=bid_id)
    try:
        from embeddings import semantic_search
        return semantic_search(query, items, top_k=top_k)
    except Exception:
        return items[:top_k], False

def delete_library_item(item_id):
    get_client().table("content_library").delete().eq("id", item_id).execute()

# ── Coach Roster ──────────────────────────────────────────────────────────────
def get_coaches():
    return _rows(get_client().table("coaches").select("*").order("name").execute())

def upsert_coach(data):
    sb   = get_client()
    keys = ["name","credentials","icf_level","sectors","languages","location",
            "availability","email","phone","cv_summary","reference_contact","notes"]
    if data.get("id"):
        sb.table("coaches").update(
            {k: data.get(k) for k in keys}).eq("id", data["id"]).execute()
    else:
        sb.table("coaches").insert({k: data.get(k) for k in keys}).execute()

def delete_coach(coach_id):
    get_client().table("coaches").delete().eq("id", coach_id).execute()

# ── Clarification Tracker ─────────────────────────────────────────────────────
def get_clarifications(bid_id):
    return _rows(get_client().table("clarifications")
                 .select("*").eq("bid_id", bid_id)
                 .order("id").execute())

def upsert_clarification(data):
    sb   = get_client()
    keys = ["question_id","question","rationale","priority","linked_req_ids",
            "submitted_date","answer","answer_date","changes_matrix","status","notes"]
    if data.get("id"):
        sb.table("clarifications").update(
            {k: data.get(k) for k in keys}).eq("id", data["id"]).execute()
    else:
        sb.table("clarifications").insert(
            {k: data.get(k) for k in ["bid_id"] + keys}).execute()

def delete_clarification(clar_id):
    get_client().table("clarifications").delete().eq("id", clar_id).execute()

# ── Win/Loss Debrief ──────────────────────────────────────────────────────────
def get_debriefs(bid_id):
    return _rows(get_client().table("debriefs")
                 .select("*").eq("bid_id", bid_id).order("id").execute())

def upsert_debrief(data):
    sb   = get_client()
    keys = ["outcome","score_technical","score_financial","score_total",
            "rank","competitors","evaluator_feedback","win_factors",
            "loss_factors","lessons","notes"]
    if data.get("id"):
        sb.table("debriefs").update(
            {k: data.get(k) for k in keys}).eq("id", data["id"]).execute()
    else:
        sb.table("debriefs").insert(
            {k: data.get(k) for k in ["bid_id"] + keys}).execute()


# ── Bid Briefs ────────────────────────────────────────────────────────────────
def get_bid_brief(bid_id: int) -> dict | None:
    """Retrieve structured Bid Brief for a bid. Returns None if table/record missing."""
    sb = get_client()
    try:
        row = _one(sb.table("bid_briefs").select("*").eq("bid_id", bid_id).execute())
        return row
    except Exception:
        return None

def format_bid_brief_payload(data: dict, keys: list) -> dict:
    """Format payload for bid_briefs table. Preserves native list/dict for JSONB document_conflicts."""
    import json
    clean = {}
    for k in keys:
        if k in data:
            v = data.get(k)
            if k == "document_conflicts":
                # JSONB column: pass Python list/dict directly to Supabase client
                clean[k] = v if isinstance(v, (list, dict)) else ([] if v is None else v)
            elif isinstance(v, (list, dict)):
                clean[k] = json.dumps(v)
            else:
                clean[k] = v
    return clean

def upsert_bid_brief(data: dict) -> None:
    """Insert or update structured Bid Brief with fallback."""
    sb = get_client()
    keys = ["bid_id", "executive_summary", "opportunity_type", "contract_term",
            "procurement_model", "scope_categories", "deliverables_summary",
            "qualification_gates", "evaluation_breakdown", "commercial_structure",
            "contract_risks", "submission_requirements", "key_dates", "source_citations",
            "document_conflicts"]
    
    clean = format_bid_brief_payload(data, keys)

    try:
        existing = _one(sb.table("bid_briefs").select("id").eq("bid_id", data["bid_id"]).execute())
        if existing:
            sb.table("bid_briefs").update(clean).eq("id", existing["id"]).execute()
        else:
            sb.table("bid_briefs").insert(clean).execute()
    except Exception:
        # If document_conflicts column missing, fallback without it
        try:
            clean_fallback = {k: v for k, v in clean.items() if k != "document_conflicts"}
            existing = _one(sb.table("bid_briefs").select("id").eq("bid_id", data["bid_id"]).execute())
            if existing:
                sb.table("bid_briefs").update(clean_fallback).eq("id", existing["id"]).execute()
            else:
                sb.table("bid_briefs").insert(clean_fallback).execute()
        except Exception:
            pass


# ── Bid Decisions ─────────────────────────────────────────────────────────────
def get_bid_decision(bid_id: int) -> dict | None:
    """Retrieve the latest bid pursuit decision record for a bid."""
    sb = get_client()
    try:
        rows = _rows(sb.table("bid_decisions").select("*")
                     .eq("bid_id", bid_id).order("id", desc=True).limit(1).execute())
        return rows[0] if rows else None
    except Exception:
        return None

def save_bid_decision(data: dict) -> None:
    """Save an AI recommendation or human pursuit decision."""
    sb = get_client()
    import json
    keys = ["bid_id", "ai_recommendation", "ai_confidence", "overall_score",
            "dimension_scores", "hard_blockers", "conditions", "win_themes",
            "red_flags", "human_decision", "override_reason", "decided_by", "decided_at"]
    
    clean = {}
    for k in keys:
        if k in data:
            v = data.get(k)
            if isinstance(v, (list, dict)):
                clean[k] = json.dumps(v)
            else:
                clean[k] = v

    try:
        sb.table("bid_decisions").insert(clean).execute()
    except Exception:
        # Fallback if decided_at column is not yet present
        try:
            clean_fallback = {k: v for k, v in clean.items() if k != "decided_at"}
            sb.table("bid_decisions").insert(clean_fallback).execute()
        except Exception:
            pass


# ── Firm Profile ──────────────────────────────────────────────────────────────
DEFAULT_FIRM_PROFILE = {
    "company_name": "Enable My Growth",
    "overview": "",
    "core_capabilities": "",
    "key_sectors": "",
    "languages": "",
    "locations": "",
    "certifications": "",
    "insurance_defaults": "",
    "ai_disclosure_policy": "[TEMPLATE — NOT CONFIGURED] Transparent and governed AI assistance with mandatory human accountable review, strict confidentiality safeguards, and zero client data retention for model training.",
}

def get_firm_profile() -> dict:
    """Retrieve the configured firm profile or return defaults."""
    sb = get_client()
    try:
        row = _one(sb.table("firm_profiles").select("*").limit(1).execute())
        if row:
            return {**DEFAULT_FIRM_PROFILE, **row}
    except Exception:
        pass
    return DEFAULT_FIRM_PROFILE.copy()


# ── Analysis Runs (Fast Analysis / Deep Verify integration) ──────────────────
def create_analysis_run(bid_id: int, analysis_mode: str, engine_version: str,
                        corpus_document_ids: list, corpus_digest: str | None = None,
                        created_by: str | None = None) -> dict | None:
    """Create a new analysis_runs row in QUEUED status. Relies on the
    partial unique index idx_analysis_runs_one_active for the durable,
    race-safe duplicate-start guard -- if a non-terminal run already exists
    for this (bid_id, analysis_mode), the insert raises and this returns
    None; callers must check for that before assuming a new run started."""
    sb = get_client()
    try:
        row = _one(sb.table("analysis_runs").insert({
            "bid_id": bid_id, "analysis_mode": analysis_mode,
            "engine_version": engine_version, "status": "QUEUED",
            "corpus_document_ids": corpus_document_ids or [],
            "corpus_digest": corpus_digest, "created_by": created_by,
        }).execute())
        return row
    except Exception as e:
        err = str(e).lower()
        if "duplicate" in err or "unique" in err or "idx_analysis_runs_one_active" in err:
            return None
        raise


def get_active_analysis_run(bid_id: int, analysis_mode: str) -> dict | None:
    """Return the current non-terminal run for (bid_id, analysis_mode), if
    any -- mirrors the partial unique index's own definition of 'active'."""
    sb = get_client()
    rows = _rows(sb.table("analysis_runs").select("*")
                 .eq("bid_id", bid_id).eq("analysis_mode", analysis_mode)
                 .not_.in_("status", ["COMPLETE", "FAILED"])
                 .order("created_at", desc=True).limit(1).execute())
    return rows[0] if rows else None


def get_analysis_run(run_id: int) -> dict | None:
    return _one(get_client().table("analysis_runs").select("*").eq("id", run_id).execute())


def get_latest_analysis_run(bid_id: int, analysis_mode: str | None = None) -> dict | None:
    """Most recent run for a bid, optionally filtered to one mode -- COMPLETE,
    FAILED, or in-progress, whichever was created last."""
    sb = get_client()
    q = sb.table("analysis_runs").select("*").eq("bid_id", bid_id)
    if analysis_mode:
        q = q.eq("analysis_mode", analysis_mode)
    rows = _rows(q.order("created_at", desc=True).limit(1).execute())
    return rows[0] if rows else None


def list_analysis_runs(bid_id: int) -> list:
    return _rows(get_client().table("analysis_runs").select("*")
                .eq("bid_id", bid_id).order("created_at", desc=True).execute())


def update_analysis_run(run_id: int, data: dict) -> None:
    """Update lifecycle/status fields. Callers pass only the fields they
    intend to change (e.g. {"status": "ANALYZING", "started_at": ...})."""
    keys = ["status", "started_at", "completed_at", "failed_at", "failure_reason",
            "failure_detail", "telemetry", "report_storage_path", "corpus_digest",
            "progress"]
    clean = {k: data[k] for k in keys if k in data}
    if not clean:
        return
    get_client().table("analysis_runs").update(clean).eq("id", run_id).execute()


def create_analysis_result(run_id: int, bid_id: int, structured_intelligence: dict,
                           fact_origins: dict | None = None,
                           report_content_snapshot: dict | None = None,
                           fast_analysis_result_snapshot: dict | None = None) -> dict | None:
    """fast_analysis_result_snapshot: the durable, JSON-safe raw-result
    envelope from fast_analysis.serialize_fast_analysis_result(), or None
    for a caller that hasn't produced one (e.g. Deep Verify runs, which
    don't use FastAnalysisResult at all). This is ANALYTICAL OUTPUT, kept
    on the same row as -- not a replacement for -- structured_intelligence/
    report_content_snapshot, and inherits this table's existing
    bid_id-scoped RLS policy; no new policy or table was introduced for it
    (migrations/012_fast_analysis_result_snapshot.sql)."""
    return _one(get_client().table("analysis_results").insert({
        "run_id": run_id, "bid_id": bid_id,
        "structured_intelligence": structured_intelligence,
        "fact_origins": fact_origins or {},
        "report_content_snapshot": report_content_snapshot,
        "fast_analysis_result_snapshot": fast_analysis_result_snapshot,
    }).execute())


def get_analysis_result(run_id: int) -> dict | None:
    return _one(get_client().table("analysis_results").select("*").eq("run_id", run_id).execute())


def upload_analysis_report(bid_id: int, run_id: int, pdf_bytes: bytes) -> str:
    """Upload a rendered analysis-run report PDF to the same Storage bucket
    and convention as `save_upload` uses for source documents. Returns the
    storage_path to persist on the analysis_runs row."""
    sb = get_client()
    storage_path = f"{bid_id}/analysis_reports/{run_id}.pdf"
    sb.storage.from_(BUCKET).upload(
        storage_path, pdf_bytes,
        file_options={"content-type": "application/pdf", "upsert": "true"})
    return storage_path


def get_latest_analysis_result(bid_id: int, analysis_mode: str = "FAST") -> dict | None:
    """Convenience: the structured result of the most recent COMPLETE run
    for a bid+mode, or None if no run has ever completed."""
    sb = get_client()
    runs = _rows(sb.table("analysis_runs").select("id")
                .eq("bid_id", bid_id).eq("analysis_mode", analysis_mode)
                .eq("status", "COMPLETE")
                .order("completed_at", desc=True).limit(1).execute())
    if not runs:
        return None
    return get_analysis_result(runs[0]["id"])


def save_firm_profile(data: dict) -> None:
    """Save or update the global bidding firm profile."""
    sb = get_client()
    keys = ["company_name", "overview", "core_capabilities", "key_sectors",
            "languages", "locations", "certifications", "insurance_defaults",
            "ai_disclosure_policy"]
    clean = {k: data.get(k) for k in keys if k in data}
    try:
        existing = _one(sb.table("firm_profiles").select("id").limit(1).execute())
        if existing:
            sb.table("firm_profiles").update(clean).eq("id", existing["id"]).execute()
        else:
            sb.table("firm_profiles").insert(clean).execute()
    except Exception:
        pass


# ── Procurement Revision & Addendum Governance (migration 010) ─────────────
# Every WRITE below is a single call into one of migration 010's
# SECURITY DEFINER RPCs -- this module never performs a sequence of
# separate .update()/.insert() calls against the governance tables and
# calls it transactional. All four RPCs are granted to service_role only
# (REVOKE'd from authenticated/anon at the database level), matching this
# module's own privileged-client contract -- tenancy.py's authorization
# wrappers call these AFTER require_bid_access(), never before.

def hash_document_bytes(file_bytes: bytes) -> str:
    """SHA-256 of raw bytes -- the one place this hash is computed. Never
    trust a browser-computed hash as authoritative."""
    import hashlib
    return hashlib.sha256(file_bytes).hexdigest()


def ensure_document_hash(document_id: int) -> str | None:
    """Server-side lazy hashing for a legacy document with a NULL
    content_hash: download bytes through the existing authorized
    service-role Storage path, compute SHA-256, persist ONLY if the
    column is still NULL (never overwrite an existing hash -- if a
    freshly-computed hash ever disagreed with an already-stored one for
    the same document_id, that would mean the underlying bytes changed
    out from under an existing hash, which is an integrity problem, not
    something to silently paper over by replacing history). Returns the
    resulting hash (existing or newly computed), or None if the document
    has no storage_path / bytes could not be downloaded."""
    sb = get_client()
    row = _one(sb.table("documents").select("content_hash,storage_path").eq("id", document_id).execute())
    if not row:
        return None
    if row.get("content_hash"):
        return row["content_hash"]
    storage_path = row.get("storage_path")
    if not storage_path:
        return None
    file_bytes = download_file(storage_path)
    if not file_bytes:
        return None
    new_hash = hash_document_bytes(file_bytes)
    # Guard against a concurrent hashing race: only write if still NULL.
    current = _one(sb.table("documents").select("content_hash").eq("id", document_id).execute())
    if current and not current.get("content_hash"):
        sb.table("documents").update({"content_hash": new_hash}).eq("id", document_id).execute()
        return new_hash
    return (current or {}).get("content_hash") or new_hash


def create_procurement_update_review(
    bid_id: int, organization_id: str, review_kind: str,
    document_ids: list[int], document_roles: list[str],
    buyer_update_type: str | None = None, buyer_issued_date: str | None = None,
    conflict_id: int | None = None, idempotency_key: str | None = None,
) -> dict:
    """Calls migration 010's create_procurement_update_review RPC. For
    baseline/buyer_update reviews, ensures every target document has a
    content_hash BEFORE the RPC call (the RPC itself cannot reach Supabase
    Storage -- see the RPC's own migration comment) -- this is the
    Python-side pre-step that makes the RPC's document_not_ready
    validation meaningful rather than a permanent blocker for legacy
    documents."""
    if review_kind in ("baseline", "buyer_update"):
        for doc_id in document_ids:
            ensure_document_hash(doc_id)
    sb = get_client()
    result = sb.rpc("create_procurement_update_review", {
        "p_bid_id": bid_id, "p_organization_id": organization_id, "p_review_kind": review_kind,
        "p_buyer_update_type": buyer_update_type, "p_buyer_issued_date": buyer_issued_date,
        "p_document_ids": document_ids, "p_document_roles": document_roles,
        "p_conflict_id": conflict_id, "p_idempotency_key": idempotency_key,
    }).execute()
    rows = result.data or []
    return rows[0] if rows else {}


def get_procurement_update_reviews(bid_id: int) -> list[dict]:
    return _rows(get_client().table("procurement_update_reviews").select("*")
                 .eq("bid_id", bid_id).order("created_at", desc=True).execute())


def get_procurement_changes(review_id: int) -> list[dict]:
    return _rows(get_client().table("procurement_changes").select("*")
                 .eq("review_id", review_id).order("id").execute())


def insert_proposed_procurement_changes(rows: list[dict]) -> None:
    """Inserts LLM-proposed changes as review_decision='pending' rows --
    the only field this function writes beyond what the proposal function
    itself supplies. Never sets applied_at, never mutates canonical truth;
    this is pure staging, an ordinary table insert (allowed for
    service-role, matching every other write in this module) -- it is
    NOT one of the four governed RPCs because it creates no canonical
    effect by itself and is naturally paired with the review's own
    'analyzing' -> 'ready_for_review' status transition."""
    if not rows:
        return
    get_client().table("procurement_changes").insert(rows).execute()


def mark_review_ready_for_review(review_id: int) -> None:
    get_client().table("procurement_update_reviews").update(
        {"status": "ready_for_review", "analyzed_at": _now_iso()}
    ).eq("id", review_id).execute()


def mark_review_failed(review_id: int, reason: str) -> None:
    """Analysis-failure only -- never used to represent an apply failure
    (an apply failure leaves the review row untouched; see migration
    010's own comment on why 'failed' is reserved for proposal-generation
    failure)."""
    get_client().table("procurement_update_reviews").update(
        {"status": "failed", "review_note": reason}
    ).eq("id", review_id).execute()


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def record_change_review_decision(
    change_id: int, decision: str, actor_user_id: str | None, review_note: str | None = None
) -> None:
    get_client().rpc("record_change_review_decision", {
        "p_change_id": change_id, "p_decision": decision,
        "p_actor_user_id": actor_user_id, "p_review_note": review_note,
    }).execute()


def apply_procurement_update_review(
    review_id: int, expected_base_revision: int, actor_user_id: str | None
) -> dict:
    result = get_client().rpc("apply_procurement_update_review", {
        "p_review_id": review_id, "p_expected_base_revision": expected_base_revision,
        "p_actor_user_id": actor_user_id,
    }).execute()
    rows = result.data or []
    return rows[0] if rows else {}


def get_procurement_conflicts(bid_id: int, status: str | None = None) -> list[dict]:
    query = get_client().table("procurement_conflicts").select("*").eq("bid_id", bid_id)
    if status:
        query = query.eq("status", status)
    return _rows(query.order("created_at").execute())


def resolve_procurement_conflict(
    conflict_id: int, expected_base_revision: int, resolution_value: dict,
    resolution_reason: str, actor_user_id: str | None,
) -> dict:
    result = get_client().rpc("resolve_procurement_conflict", {
        "p_conflict_id": conflict_id, "p_expected_base_revision": expected_base_revision,
        "p_resolution_value": resolution_value, "p_resolution_reason": resolution_reason,
        "p_actor_user_id": actor_user_id,
    }).execute()
    rows = result.data or []
    return rows[0] if rows else {}


def get_bid_procurement_state(bid_id: int) -> dict:
    """{'procurement_revision': int, 'procurement_truth_status': str} for
    the staleness banner -- a small, focused read, not a full bid fetch."""
    row = _one(get_client().table("bids").select("procurement_revision,procurement_truth_status")
               .eq("id", bid_id).execute())
    return row or {"procurement_revision": 1, "procurement_truth_status": "ungoverned"}


def get_reviewed_document_hashes(bid_id: int) -> set[tuple[int, str]]:
    """(document_id, content_hash) pairs covered by at least one APPLIED
    baseline/buyer_update review for this bid -- the set
    analysis_runs.unreviewed_document_count (Fast Analysis advisory
    staleness signal) is computed against. Conflict-resolution and
    pending/failed reviews never count -- they establish no canonical
    procurement truth for the document (per migration 010's review_kind
    semantics)."""
    sb = get_client()
    reviews = _rows(sb.table("procurement_update_reviews").select("id")
                     .eq("bid_id", bid_id).eq("status", "applied")
                     .in_("review_kind", ["baseline", "buyer_update"]).execute())
    review_ids = [r["id"] for r in reviews]
    if not review_ids:
        return set()
    docs = _rows(sb.table("procurement_update_review_documents").select("document_id,document_hash")
                 .in_("review_id", review_ids).execute())
    return {(d["document_id"], d["document_hash"]) for d in docs if d.get("document_hash")}

