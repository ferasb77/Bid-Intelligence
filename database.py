"""
Bid Intelligence Platform — Supabase database layer.
Replaces SQLite. All data persists across Streamlit Cloud redeploys.
File uploads go to Supabase Storage.
"""
import os
import streamlit as st
from supabase import create_client, Client

# ── Connection ────────────────────────────────────────────────────────────────
def get_client() -> Client:
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
        reqs  = _rows(sb.table("requirements").select("id,status").eq("bid_id", b["id"]).execute())
        tasks = _rows(sb.table("tasks").select("id,status").eq("bid_id", b["id"]).execute())
        b["req_count"]  = len(reqs)
        b["req_done"]   = sum(1 for r in reqs if r["status"]=="Complete")
        b["task_count"] = len(tasks)
        b["task_done"]  = sum(1 for t in tasks if t["status"]=="Complete")
    return bids

def get_bid(bid_id):
    return _one(get_client().table("bids").select("*").eq("id", bid_id).execute())

def create_bid(data):
    clean = {k: data.get(k) for k in
             ["title","client","file_number","stage","sensitivity","owner",
              "value_cad","submission_deadline","clarification_deadline","notes"]}
    row = _one(get_client().table("bids").insert(clean).execute())
    return int(row["id"]) if row else None

def update_bid(bid_id, data):
    clean = {k: data.get(k) for k in
             ["title","client","file_number","stage","sensitivity","owner",
              "value_cad","submission_deadline","clarification_deadline","notes"]}
    get_client().table("bids").update(clean).eq("id", bid_id).execute()

def delete_bid(bid_id):
    get_client().table("bids").delete().eq("id", bid_id).execute()

# ── Requirements ──────────────────────────────────────────────────────────────
def get_requirements(bid_id):
    return _rows(get_client().table("requirements")
                 .select("*").eq("bid_id", bid_id)
                 .order("category").order("req_id").execute())

def upsert_requirement(data):
    sb = get_client()
    keys = ["req_id","category","description","rfso_ref","weight",
            "evidence","owner","deadline","status","notes"]
    if data.get("id"):
        clean = {k: data.get(k) for k in keys}
        sb.table("requirements").update(clean).eq("id", data["id"]).execute()
    else:
        clean = {k: data.get(k) for k in ["bid_id"] + keys}
        sb.table("requirements").insert(clean).execute()

def delete_requirement(req_id):
    get_client().table("requirements").delete().eq("id", req_id).execute()

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
    """Upload file to Supabase Storage and create/update document record."""
    sb = get_client()

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
            }).eq("id", doc_id).execute()
        return file_path, doc_id
    else:
        row = _one(sb.table("documents").insert({
            "bid_id": bid_id, "name": filename,
            "doc_type": doc_type, "owner": owner,
            "file_path": file_path, "storage_path": storage_path,
            "file_size": len(file_bytes), "version": 1,
            "status": "Uploaded",
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

# ── Readiness ─────────────────────────────────────────────────────────────────
def get_readiness(bid_id):
    sb   = get_client()
    reqs = _rows(sb.table("requirements").select("category,status").eq("bid_id", bid_id).execute())
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
