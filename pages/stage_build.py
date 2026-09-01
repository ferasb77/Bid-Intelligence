"""
Stage 3: BUILD — Proposal Workspace
Consolidated working environment for proposal construction:
1. Proposal Outline & Integrated Section Drafter
2. Criteria In-View & Semantic Content Reuse
3. Services & Deliverables Register (SOW & Pricing)
4. Working Document Registry & Versions
5. Action Tasks & Assignments
"""
import streamlit as st
from database import (get_bid, get_requirements, get_outline, upsert_section, delete_section,
                      get_library_items, semantic_library_search, get_deliverables,
                      upsert_deliverable, delete_deliverable, get_documents, upsert_document,
                      delete_document, save_upload, get_tasks, upsert_task, delete_task,
                      get_firm_profile)
from analyst import draft_proposal_section
from config import api_key_configured
from components.ui import (status_badge, priority_badge, readiness_bar,
                           STATUSES, PRIORITIES, DOC_TYPES)


def page_build(bid_id: int):
    bid = get_bid(bid_id)
    if not bid:
        st.error("Opportunity not found.")
        return

    reqs = get_requirements(bid_id)
    sections = get_outline(bid_id)
    dels = get_deliverables(bid_id)
    docs = get_documents(bid_id)
    tasks = get_tasks(bid_id)
    firm_profile = get_firm_profile()

    st.markdown('<div style="font-size:.72rem;color:#C9A96E;text-transform:uppercase;letter-spacing:.12em;font-weight:600">STAGE 3 · BUILD</div>', unsafe_allow_html=True)
    st.markdown(f"# Proposal Workspace")
    st.markdown(f'<div style="font-size:1rem;color:#A9A69D">{bid["client"]} — {bid["title"]}</div>', unsafe_allow_html=True)
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)

    # ── PROGRESS SUMMARY ──────────────────────────────────────────────────────
    total_sec = len(sections)
    done_sec = sum(1 for s in sections if s.get("status") == "Complete")
    sec_pct = (done_sec / total_sec * 100) if total_sec else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(metric_card("Outline Sections", f"{done_sec}/{total_sec}", f"{sec_pct:.0f}% complete"), unsafe_allow_html=True)
    c1.markdown(readiness_bar(sec_pct), unsafe_allow_html=True)

    c2.markdown(metric_card("SOW Deliverables", len(dels), "services defined"), unsafe_allow_html=True)
    c3.markdown(metric_card("Working Documents", len(docs), f"{sum(1 for d in docs if d.get('status')=='Uploaded')} uploaded"), unsafe_allow_html=True)
    c4.markdown(metric_card("Active Tasks", sum(1 for t in tasks if t.get('status') != 'Complete'), f"{len(tasks)} total tasks"), unsafe_allow_html=True)
    st.markdown("")

    tab_outline, tab_deliv, tab_docs, tab_tasks = st.tabs([
        "📝 Proposal Outline & Section Drafter",
        "📦 Deliverables & SOW Detail",
        "📁 Working Document Registry",
        "☑️ Action Tasks"
    ])

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 1: PROPOSAL OUTLINE & INTEGRATED DRAFTER
    # ══════════════════════════════════════════════════════════════════════════
    with tab_outline:
        st.markdown("### Proposal Outline & Integrated Section Drafter")
        st.markdown(
            '<div style="font-size:.82rem;color:#A9A69D;margin-bottom:.8rem">'
            'Select any proposal section to view its mapped evaluation criteria, pull semantically matched library content, '
            'and draft or refine text in-place.'
            '</div>',
            unsafe_allow_html=True
        )

        c_sec_list, c_sec_draft = st.columns([1.3, 2])

        with c_sec_list:
            st.markdown("#### Sections")
            if not sections:
                st.markdown('<div class="empty-state">No sections defined yet.</div>', unsafe_allow_html=True)
            else:
                for sec in sections:
                    s_id = sec["id"]
                    is_active = (st.session_state.get("active_draft_sec") == s_id)
                    num_str = f"[{sec.get('section_num','')}] " if sec.get("section_num") else ""
                    st_col = {"Complete": "#27AE60", "In Progress": "#2980B9", "Draft": "#C9A96E"}.get(sec.get("status"), "#6E6C66")

                    c_btn, c_stat = st.columns([3, 1])
                    if c_btn.button(f"{num_str}{sec['title']}", key=f"sec_sel_{s_id}", use_container_width=True):
                        st.session_state["active_draft_sec"] = s_id
                        st.rerun()
                    c_stat.markdown(f'<span style="font-size:.7rem;color:{st_col};font-weight:600">{sec.get("status","Not Started")}</span>', unsafe_allow_html=True)

            with st.expander("➕ Add Outline Section"):
                with st.form("add_outline_sec_form", clear_on_submit=True):
                    n_title = st.text_input("Section Title *")
                    c_n1, c_n2 = st.columns(2)
                    n_num = c_n1.text_input("Section Number", placeholder="e.g. 1.0 or §2")
                    n_owner = c_n2.text_input("Section Owner")
                    n_wlimit = st.number_input("Word Count Target", value=500, step=50)
                    n_notes = st.text_area("Scope / Guidance", height=50)
                    if st.form_submit_button("Add Section", use_container_width=True):
                        if n_title:
                            upsert_section({
                                "id": None, "bid_id": bid_id, "title": n_title,
                                "section_num": n_num, "owner": n_owner, "word_limit": n_wlimit,
                                "sort_order": len(sections), "status": "Not Started", "notes": n_notes
                            })
                            st.rerun()

        # Integrated drafting panel for active section
        with c_sec_draft:
            active_s_id = st.session_state.get("active_draft_sec")
            active_sec = next((s for s in sections if s["id"] == active_s_id), None) if active_s_id else (sections[0] if sections else None)

            if not active_sec:
                st.markdown('<div class="info-box">Select or add a section to start drafting.</div>', unsafe_allow_html=True)
            else:
                st.markdown(f"#### ✍️ Drafting: [{active_sec.get('section_num','')}] {active_sec['title']}")
                st.markdown(f'<div style="font-size:.78rem;color:#A9A69D;margin-bottom:.5rem">Owner: <strong>{active_sec.get("owner") or "Unassigned"}</strong> · Target: <strong>{active_sec.get("word_limit") or 500} words</strong></div>', unsafe_allow_html=True)

                # Requirements mapped in-view
                with st.expander("🎯 Evaluation Criteria In View (Mapped Requirements)", expanded=True):
                    st.markdown(
                        '<div style="font-size:.75rem;color:#A9A69D;margin-bottom:.3rem">'
                        'Select requirements this section must satisfy:'
                        '</div>',
                        unsafe_allow_html=True
                    )
                    req_options = {f"[{r.get('req_id','—')}] ({r.get('category','')}) {r.get('description','')[:65]}": r for r in reqs}
                    selected_req_keys = st.multiselect("Mapped Requirements", list(req_options.keys()), key=f"req_map_{active_sec['id']}")
                    mapped_reqs = [req_options[k] for k in selected_req_keys]

                # Semantic Content Reuse
                with st.expander("📚 Relevant Content Library Blocks (Semantic Search)", expanded=False):
                    lib_results, used_semantic = semantic_library_search(active_sec["title"], bid_id=bid_id, top_k=4)
                    if lib_results:
                        for lib_item in lib_results:
                            st.markdown(f"**[{lib_item.get('category','')}] {lib_item.get('title','')}**")
                            st.markdown(f'<div style="font-size:.78rem;color:#EDEAE3;background:#111118;border:1px solid #292832;border-radius:4px;padding:.5rem;max-height:120px;overflow-y:auto;white-space:pre-wrap">{lib_item.get("content","")[:300]}…</div>', unsafe_allow_html=True)
                    else:
                        st.markdown('<div style="font-size:.75rem;color:#6E6C66">No library items found. Add items to the Content Library.</div>', unsafe_allow_html=True)

                # AI Draft Action
                c_d1, c_d2 = st.columns([2, 1])
                if c_d1.button("✨ Draft / Refine Section with Claude", key=f"btn_draft_{active_sec['id']}", use_container_width=True, type="primary"):
                    if not (api_key_configured() or st.session_state.get("anthropic_api_key")):
                        st.error("Configure Anthropic API key to use Section Drafter.")
                    else:
                        with st.spinner("Drafting section against criteria… 15–25s"):
                            try:
                                firm_summary = f"{firm_profile.get('company_name','')}: {firm_profile.get('overview','')} Capabilities: {firm_profile.get('core_capabilities','')}"
                                draft_res = draft_proposal_section(
                                    section_title=active_sec["title"],
                                    requirements=mapped_reqs if mapped_reqs else reqs[:4],
                                    library_items=lib_results if lib_results else [],
                                    bid_context=bid,
                                    firm_context=firm_summary,
                                    word_limit=active_sec.get("word_limit") or 500
                                )
                                st.session_state[f"draft_text_{active_sec['id']}"] = draft_res.get("draft", "")
                                st.success("Draft generated successfully.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Drafting failed: {e}")

                # Section Editor Form
                current_draft = st.session_state.get(f"draft_text_{active_sec['id']}") or active_sec.get("notes") or ""
                edited_draft = st.text_area("Section Content", value=current_draft, height=260, key=f"txt_draft_{active_sec['id']}")

                c_s1, c_s2, c_s3 = st.columns([1.5, 1.5, 1])
                new_sec_stat = c_s1.selectbox("Status", STATUSES, index=STATUSES.index(active_sec.get("status", "Draft")) if active_sec.get("status") in STATUSES else 2, key=f"stat_{active_sec['id']}")
                if c_s2.button("💾 Save Section", key=f"save_sec_{active_sec['id']}", use_container_width=True):
                    upsert_section({
                        **active_sec,
                        "notes": edited_draft,
                        "status": new_sec_stat
                    })
                    st.success("Saved.")
                    st.rerun()
                if c_s3.button("🗑", key=f"del_sec_{active_sec['id']}", help="Delete section"):
                    delete_section(active_sec["id"])
                    st.session_state.pop("active_draft_sec", None)
                    st.rerun()

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 2: DELIVERABLES & SOW DETAIL
    # ══════════════════════════════════════════════════════════════════════════
    with tab_deliv:
        st.markdown("### Services & Deliverables Register (SOW)")
        st.markdown(
            '<div style="font-size:.82rem;color:#A9A69D;margin-bottom:.8rem">'
            'Capture tangible SOW outputs, volume assumptions, and pricing options.'
            '</div>',
            unsafe_allow_html=True
        )
        if dels:
            for d in dels:
                with st.expander(f"**{d.get('service_id','S')}** · {d['title']} ({d.get('category','Core Service')})"):
                    st.markdown(f"**Description:** {d.get('description','—')}")
                    c_d1, c_d2, c_d3 = st.columns(3)
                    c_d1.markdown(f"**Duration:** {d.get('duration','—')}")
                    c_d2.markdown(f"**Volume / Unit:** {d.get('volume','—')} {d.get('unit','')}")
                    price_str = f"AI: CAD {d['price_ai']:,.2f}" if d.get("price_ai") else ""
                    c_d3.markdown(f"**Pricing:** {price_str if price_str else 'To be priced'}")
                    if st.button("Delete Service", key=f"del_d_{d['id']}"):
                        delete_deliverable(d["id"])
                        st.rerun()
        else:
            st.markdown('<div class="info-box">No SOW deliverables defined yet. Add deliverables below.</div>', unsafe_allow_html=True)

        with st.expander("➕ Add SOW Deliverable"):
            with st.form("add_deliv_form", clear_on_submit=True):
                c_dt1, c_dt2 = st.columns([1, 3])
                d_id = c_dt1.text_input("Service ID", placeholder="S1, D1...")
                d_title = c_dt2.text_input("Deliverable Title *")
                d_desc = st.text_area("Scope / Description", height=60)
                c_dp1, c_dp2, c_dp3 = st.columns(3)
                d_dur = c_dp1.text_input("Duration", placeholder="e.g. 12 months")
                d_vol = c_dp2.text_input("Volume / Unit", placeholder="e.g. 24 hours per cohort")
                d_cat = c_dp3.selectbox("Category", ["Core Service", "Optional Service", "Reporting", "Call-off Mechanic"])
                if st.form_submit_button("Add Deliverable", use_container_width=True):
                    if d_title:
                        upsert_deliverable({
                            "id": None, "bid_id": bid_id, "service_id": d_id,
                            "title": d_title, "description": d_desc, "duration": d_dur,
                            "volume": d_vol, "category": d_cat, "sort_order": len(dels)
                        })
                        st.rerun()

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 3: WORKING DOCUMENT REGISTRY
    # ══════════════════════════════════════════════════════════════════════════
    with tab_docs:
        st.markdown("### Working Document Registry")
        st.markdown(
            '<div style="font-size:.82rem;color:#A9A69D;margin-bottom:.8rem">'
            'Upload draft proposals, partner declarations, CVs, and supporting files.'
            '</div>',
            unsafe_allow_html=True
        )

        up_file = st.file_uploader("Upload proposal working document", type=["pdf", "docx", "xlsx", "doc", "txt", "pptx"], key="build_up_file")
        if up_file:
            up_key = f"uploaded_build_{bid_id}_{up_file.name}_{up_file.size}"
            if not st.session_state.get(up_key):
                fb = up_file.read()
                save_upload(bid_id, up_file.name, fb, doc_type="Submission")
                st.session_state[up_key] = True
                st.success(f"Uploaded: {up_file.name}")
                st.rerun()

        if docs:
            for d in docs:
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;align-items:center;background:#111118;'
                    f'border:1px solid #292832;border-radius:4px;padding:.5rem .9rem;margin:.3rem 0">'
                    f'<span>📄 <strong>{d["name"]}</strong> <span style="font-size:.72rem;color:#A9A69D">[{d.get("doc_type","")}] v{d.get("version",1)}</span></span>'
                    f'<span>{status_badge(d.get("status","Expected"))}</span>'
                    f'</div>',
                    unsafe_allow_html=True
                )

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 4: ACTION TASKS
    # ══════════════════════════════════════════════════════════════════════════
    with tab_tasks:
        st.markdown("### Action Tasks Board")
        if tasks:
            for t in tasks:
                d_until = days_until(t.get("due_date"))
                pri_b = priority_badge(t.get("priority", "Medium"))
                stat_b = status_badge(t.get("status", "Not Started"))
                c_t1, c_t2, c_t3 = st.columns([3, 1.5, 1])
                c_t1.markdown(f"**{t['title']}** <span style='font-size:.75rem;color:#A9A69D'>({t.get('owner','Unassigned')})</span>", unsafe_allow_html=True)
                c_t2.markdown(f"{pri_b} {stat_b}", unsafe_allow_html=True)
                if c_t3.button("Delete", key=f"del_t_{t['id']}"):
                    delete_task(t["id"])
                    st.rerun()
        else:
            st.markdown('<div class="empty-state">No action tasks logged.</div>', unsafe_allow_html=True)

        with st.expander("➕ Add Task"):
            with st.form("add_task_build_form", clear_on_submit=True):
                t_title = st.text_input("Task Title *")
                c_tk1, c_tk2 = st.columns(2)
                t_owner = c_tk1.text_input("Owner")
                t_due = c_tk2.text_input("Due Date", placeholder="YYYY-MM-DD")
                t_pri = st.selectbox("Priority", PRIORITIES, index=1)
                if st.form_submit_button("Add Task", use_container_width=True):
                    if t_title:
                        upsert_task({"id": None, "bid_id": bid_id, "title": t_title, "owner": t_owner, "due_date": t_due, "priority": t_pri, "status": "Not Started"})
                        st.rerun()

    # ── NEXT STAGE CTA ────────────────────────────────────────────────────────
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    c1, c2 = st.columns([3, 1])
    c1.markdown('<div style="color:#A9A69D;font-size:.85rem;padding-top:.4rem">Draft complete? Review compliance and proposal alignment.</div>', unsafe_allow_html=True)
    if c2.button("Proceed to CHECK →", use_container_width=True, type="primary"):
        st.session_state.page = "stage_check"
        st.rerun()
