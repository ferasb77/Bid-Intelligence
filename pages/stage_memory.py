"""
Organizational Memory (OM-2) — Source Ingestion & Human Approval Lifecycle
Minimal, organization-scoped management surface. Not a bid workflow stage
(Organizational Memory is deliberately NOT bid-scoped -- see migrations/
016_organizational_memory.sql) -- this page is reached from the global
sidebar navigation, the same way Content Library is.

Lets a user:
  * upload a source file (deterministic extraction/chunking -> SOURCE_MEMORY
    items, one durable organizational_source_documents parent record);
  * browse SOURCE_MEMORY chunks for the organization;
  * review one source chunk's content + provenance before deciding whether
    to approve it;
  * explicitly approve a reusable fact (creates a NEW APPROVED_FIRM_
    KNOWLEDGE item via tenancy.approve_organizational_memory_item_for_
    organization -- the parent SOURCE_MEMORY row is never mutated);
  * browse APPROVED_FIRM_KNOWLEDGE and PROPOSAL_MEMORY with clear trust
    labels so no memory class is ever mistaken for another.

Deliberately excluded from this phase (see the OM-2 task authorization):
no auto-insertion into proposals, no auto-approval, no proposal drafting
from memory, no Section Analyzer / Proposal Intelligence integration, no
archive-wide bulk ingestion, no scoring.
"""
import streamlit as st
import auth_session
import tenancy


_TRUST_LABELS = {
    "APPROVED_FIRM_KNOWLEDGE": ("✅ APPROVED FIRM KNOWLEDGE",
                                 "Human-approved reusable fact. Traceable to its exact source."),
    "SOURCE_MEMORY": ("📄 SOURCE MATERIAL (unapproved)",
                       "Raw uploaded source content. NOT yet reviewed/approved -- "
                       "may only SUPPORT a claim, never prove one on its own."),
    "PROPOSAL_MEMORY": ("✍️ PROPOSAL LANGUAGE",
                         "Reusable prior-proposal wording. Marketing language, never "
                         "usable as proof of a fact."),
}


def _current_access_and_org():
    session = auth_session.current_session()
    ctx = auth_session.current_auth_context()
    return session["access_token"], ctx.organization_id, ctx.user_id


def _trust_badge(memory_class: str) -> str:
    label, _ = _TRUST_LABELS.get(memory_class, (memory_class, ""))
    return label


def page_memory():
    _token, org_id, user_id = _current_access_and_org()

    st.markdown("# 🧠 Organizational Memory")
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="info-box">Upload real source material (case studies, capability '
        'statements, resumes), review specific source content, and explicitly approve '
        'reusable firm knowledge. Nothing here is auto-approved, auto-inserted into a '
        'proposal, or auto-scored -- every APPROVED FIRM KNOWLEDGE item requires an '
        'explicit human approval action.</div>', unsafe_allow_html=True)

    tab_upload, tab_source, tab_approved, tab_proposal = st.tabs(
        ["⬆️ Upload Source", "📄 Source Material", "✅ Approved Firm Knowledge", "✍️ Proposal Memory"])

    # ── Upload ──────────────────────────────────────────────────────────
    with tab_upload:
        st.markdown("### Upload a source file")
        st.caption(
            "One file at a time, human-initiated. The file is extracted, split into "
            "deterministic bounded chunks, and each chunk becomes its own SOURCE_MEMORY "
            "item with exact provenance (filename, content hash, char range) -- not one "
            "giant blob.")
        uploaded = st.file_uploader(
            "Source file", type=["pdf", "docx", "xlsx", "xls", "csv", "txt"], key="om_upload")
        if uploaded is not None and st.button("Ingest file", type="primary", key="om_ingest_btn"):
            file_bytes = uploaded.getvalue()
            with st.spinner("Extracting and chunking..."):
                try:
                    result = tenancy.ingest_organizational_source_document_for_organization(
                        org_id, uploaded.name, file_bytes, created_by_user_id=user_id)
                except Exception as e:
                    st.error(f"Ingestion failed: {e}")
                    result = None
            if result is not None:
                if result.get("reused_existing"):
                    st.info(
                        f"This exact file was already ingested — reusing the existing "
                        f"{len(result['items'])} SOURCE_MEMORY chunk(s) rather than duplicating them.")
                else:
                    st.success(
                        f"Ingested '{uploaded.name}' — created {len(result['items'])} "
                        f"SOURCE_MEMORY chunk(s).")

    # ── Source Material (browse + review + approve) ────────────────────
    with tab_source:
        st.markdown("### Source material chunks")
        source_items = tenancy.list_organizational_memory_for_organization(
            org_id, memory_class="SOURCE_MEMORY")
        if not source_items:
            st.caption("No source material uploaded yet.")
        for item in source_items:
            label, desc = _TRUST_LABELS["SOURCE_MEMORY"]
            with st.expander(f"{item.get('title', '(untitled)')}  ·  {label}"):
                st.caption(desc)
                st.text_area("Content", value=item.get("content", ""), height=150,
                             key=f"om_src_content_{item['id']}", disabled=True)
                st.markdown(
                    f"**Provenance** — file: `{item.get('source_filename')}` · "
                    f"content hash: `{(item.get('source_content_hash') or '')[:16]}…` · "
                    f"locator: `{item.get('source_locator')}`")

                st.markdown("**Approve as reusable firm knowledge**")
                fact_title = st.text_input(
                    "Fact title", value=item.get("title", ""), key=f"om_fact_title_{item['id']}")
                fact_content = st.text_area(
                    "Fact text (you may tighten/clarify the wording — it stays traceable "
                    "to this exact source)",
                    value=item.get("content", ""), height=120, key=f"om_fact_content_{item['id']}")
                if st.button("✅ Approve as Firm Knowledge", key=f"om_approve_{item['id']}"):
                    try:
                        approved = tenancy.approve_organizational_memory_item_for_organization(
                            org_id, item["id"], user_id,
                            fact_title=fact_title, fact_content=fact_content)
                        st.success(f"Approved — created APPROVED_FIRM_KNOWLEDGE item #{approved['id']}.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Approval failed: {e}")

    # ── Approved Firm Knowledge (browse only) ───────────────────────────
    with tab_approved:
        st.markdown("### Approved firm knowledge")
        approved_items = tenancy.list_organizational_memory_for_organization(
            org_id, memory_class="APPROVED_FIRM_KNOWLEDGE")
        if not approved_items:
            st.caption("Nothing approved yet.")
        for item in approved_items:
            label, desc = _TRUST_LABELS["APPROVED_FIRM_KNOWLEDGE"]
            with st.expander(f"{item.get('title', '(untitled)')}  ·  {label}"):
                st.caption(desc)
                st.text_area("Content", value=item.get("content", ""), height=120,
                             key=f"om_appr_content_{item['id']}", disabled=True)
                st.markdown(
                    f"Approved by `{item.get('approved_by_user_id')}` at "
                    f"`{item.get('approved_at')}` · derived from source item "
                    f"`#{item.get('derived_from_item_id')}`")

    # ── Proposal Memory (browse only, this phase builds no writer for it) ─
    with tab_proposal:
        st.markdown("### Proposal memory")
        st.caption(
            "Reusable prior-proposal language. Marketing content, never usable as proof "
            "of a fact. This phase does not build an ingestion path for this class.")
        proposal_items = tenancy.list_organizational_memory_for_organization(
            org_id, memory_class="PROPOSAL_MEMORY")
        if not proposal_items:
            st.caption("No proposal memory items yet.")
        for item in proposal_items:
            label, desc = _TRUST_LABELS["PROPOSAL_MEMORY"]
            with st.expander(f"{item.get('title', '(untitled)')}  ·  {label}"):
                st.caption(desc)
                st.text_area("Content", value=item.get("content", ""), height=120,
                             key=f"om_prop_content_{item['id']}", disabled=True)
