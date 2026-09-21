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
import auth_session
import tenancy
import section_analyzer
import proposal_outline
from config import api_key_configured
from components.ui import (metric_card, status_badge, priority_badge, readiness_bar,
                           STATUSES, PRIORITIES, DOC_TYPES)
from pages.section_drafting_workspace import render_requirement_drafting_workspace


def _current_access_token_and_org():
    session = auth_session.current_session()
    ctx = auth_session.current_auth_context()
    return session["access_token"], ctx.organization_id


_DIRECTION_LABEL = {
    "ON_TRACK": ("✅ On Track", "#27AE60"),
    "NEEDS_ADJUSTMENT": ("⚠️ Needs Adjustment", "#C9A96E"),
    "HIGH_RISK": ("🔴 High Risk", "#C0392B"),
    "INSUFFICIENT_CONTEXT": ("❔ Insufficient Context", "#6E6C66"),
}
_REQ_STATUS_COLOR = {
    "COVERED": "#27AE60", "PARTIAL": "#C9A96E", "MISSING": "#C0392B",
    "CONTRADICTED": "#C0392B", "CANNOT_ASSESS": "#6E6C66",
}
# PI-3D: BUILD section-list/detail intelligence rollup labels (see
# proposal_outline.summarize_section_intelligence).
_READINESS_COLOR = {"Strong": "#27AE60", "Moderate": "#C9A96E", "Weak": "#E67E22", "None": "#6E6C66"}
_DRAFT_STATUS_LABEL = {
    "NOT_APPLICABLE": "—", "NOT_GENERATED": "Not generated",
    "PARTIAL": "Partially drafted", "GENERATED": "Drafted",
}


def _render_section_review(review: dict, stale: bool, key_prefix: str = ""):
    """Progressive-disclosure rendering of one persisted section_reviews
    row (instruction 17). The first screen answers, immediately: are we
    heading in the right direction, why, and what to change next --
    everything else is behind an expander."""
    result = review.get("review_result") or {}
    direction = review.get("direction", "INSUFFICIENT_CONTEXT")
    label, color = _DIRECTION_LABEL.get(direction, _DIRECTION_LABEL["INSUFFICIENT_CONTEXT"])

    status_html = '<span style="color:#C9A96E">● Stale — section or requirements changed since this review</span>' \
        if stale else '<span style="color:#27AE60">● Current</span>'
    st.markdown(
        f'<div style="background:#111118;border:1px solid #292832;border-radius:6px;padding:.8rem 1rem;margin:.5rem 0">'
        f'<div style="font-size:1.1rem;font-weight:700;color:{color}">{label}</div>'
        f'<div style="font-size:.72rem;margin-top:.2rem">{status_html}</div>'
        f'<div style="font-size:.85rem;color:#EDEAE3;margin-top:.5rem">{result.get("summary","")}</div>'
        f'</div>', unsafe_allow_html=True)

    top_changes = result.get("top_changes") or []
    if top_changes:
        st.markdown("**Top Changes Before Writing More**")
        for i, c in enumerate(top_changes, 1):
            st.markdown(f"{i}. {c}")

    req_assessments = result.get("requirement_assessments") or []
    if req_assessments:
        with st.expander(f"📋 Requirement Coverage ({len(req_assessments)})", expanded=False):
            for ra in req_assessments:
                c = _REQ_STATUS_COLOR.get(ra.get("status"), "#6E6C66")
                st.markdown(
                    f'<div style="border-left:3px solid {c};padding:.3rem .6rem;margin:.3rem 0">'
                    f'<strong>{ra.get("criterion","")}</strong> '
                    f'<span style="color:{c};font-size:.75rem;font-weight:600">{ra.get("status","")}</span>'
                    f'</div>', unsafe_allow_html=True)
                if ra.get("gap"):
                    st.markdown(f'<div style="font-size:.78rem;color:#A9A69D">Gap: {ra["gap"]}</div>', unsafe_allow_html=True)
                if ra.get("recommended_action"):
                    st.markdown(f'<div style="font-size:.78rem;color:#A9A69D">Action: {ra["recommended_action"]}</div>', unsafe_allow_html=True)

    rg_assessments = result.get("response_guideline_assessments") or []
    if rg_assessments:
        with st.expander(f"📐 Response Guideline Coverage ({len(rg_assessments)})", expanded=False):
            for rga in rg_assessments:
                st.markdown(f'**{rga.get("guideline","")}** — {rga.get("status","")}')
                if rga.get("prompt"):
                    st.markdown(f'<div style="font-size:.78rem;color:#A9A69D">{rga["prompt"]}</div>', unsafe_allow_html=True)

    evidence = result.get("evidence_assessment") or {}
    if evidence:
        with st.expander("🔬 Evidence Strength", expanded=False):
            if evidence.get("strong_evidence"):
                st.markdown("**Strong evidence:**")
                for e in evidence["strong_evidence"]:
                    st.markdown(f"- {e}")
            if evidence.get("unsupported_claims"):
                st.markdown("**Unsupported claims:**")
                for e in evidence["unsupported_claims"]:
                    st.markdown(f"- {e}")
            if evidence.get("missing_evidence"):
                st.markdown("**Missing evidence:**")
                for e in evidence["missing_evidence"]:
                    st.markdown(f"- {e}")

    clarity = result.get("clarity_and_structure") or []
    if clarity:
        with st.expander("🧭 Clarity & Evaluator Usability", expanded=False):
            for c in clarity:
                st.markdown(f"- {c}")

    diff = result.get("differentiation") or []
    if diff:
        with st.expander("✨ Differentiation", expanded=False):
            for d in diff:
                st.markdown(f'- **{d.get("assessment","")}**: {d.get("statement","")}')

    buyer_ctx = result.get("buyer_context") or []
    if buyer_ctx:
        with st.expander("🌐 Buyer Context (External — not a stated requirement)", expanded=False):
            for b in buyer_ctx:
                st.markdown(f'<div style="font-size:.8rem"><em>External signal:</em> {b.get("external_fact","")}</div>', unsafe_allow_html=True)
                st.markdown(f'<div style="font-size:.8rem;color:#A9A69D"><em>Analytical implication:</em> {b.get("implication","")}</div>', unsafe_allow_html=True)

    cross_section = [ra for ra in req_assessments if ra.get("dependency") and ra.get("dependency") != "IN_SECTION"]
    if cross_section:
        with st.expander("🔗 Cross-Section Dependencies", expanded=False):
            for ra in cross_section:
                st.markdown(f'- **{ra.get("criterion","")}** — {ra.get("dependency","")}')


def page_build(bid_id: int):
    _token, _org_id = _current_access_token_and_org()
    bid = tenancy.get_bid_authenticated(_token, bid_id)
    if not bid:
        st.error("Opportunity not found.")
        return

    reqs = tenancy.get_requirements_authenticated(_token, bid_id)
    sections = tenancy.get_outline_authenticated(_token, bid_id)
    dels = tenancy.get_deliverables_authenticated(_token, bid_id)
    docs = tenancy.get_documents_authenticated(_token, bid_id)
    tasks = tenancy.get_tasks_authenticated(_token, bid_id)

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
            'BI can propose a grounded proposal structure from this bid\'s analyzed requirements and '
            'evaluation criteria, then draft each section\'s response from persisted, evidence-aware '
            'intelligence — or you can build and draft the outline manually.'
            '</div>',
            unsafe_allow_html=True
        )

        # ── PI-3D: cheap, read-only BUILD intelligence context (bulk) ────────
        # Reused by the section list (requirement/criteria/evidence rollups)
        # AND the active section's detail panel below -- computed ONCE per
        # page render, never once per section. Advisory-only: a failure here
        # (e.g. no Fast Analysis snapshot yet) never blocks the manual
        # workflow, it only omits the AI-assisted rollups/outline generation.
        try:
            build_ctx = tenancy.get_build_intelligence_context_for_organization(bid_id, _org_id)
        except tenancy.AccessDeniedError as e:
            st.error(f"Not authorized: {e}")
            build_ctx = None
        except Exception:
            build_ctx = None
        section_req_map = tenancy.get_section_requirement_map_authenticated(_token, bid_id)

        # ── Primary/secondary workflow toggle ─────────────────────────────
        # AI-Assisted Build is the default/primary path once the bid has
        # analyzed requirements to build a structure from; Manual stays one
        # click away and every manual capability below remains functional
        # regardless of which mode is selected.
        default_mode = "ai" if reqs else "manual"
        build_mode = st.session_state.get("build_workflow_mode", default_mode)
        c_m1, c_m2 = st.columns(2)
        if c_m1.button("🤖 AI-Assisted Build", key="mode_ai", use_container_width=True,
                       type="primary" if build_mode == "ai" else "secondary"):
            st.session_state["build_workflow_mode"] = "ai"
            st.rerun()
        if c_m2.button("✍️ Build Manually", key="mode_manual", use_container_width=True,
                       type="primary" if build_mode == "manual" else "secondary"):
            st.session_state["build_workflow_mode"] = "manual"
            st.rerun()

        c_sec_list, c_sec_draft = st.columns([1.3, 2])

        with c_sec_list:
            st.markdown("#### Sections")
            if not sections:
                if reqs and build_mode == "ai":
                    # ── AI-assisted empty state (instruction 8) ──────────
                    n_crit = len(build_ctx["criterion_by_req_id"]) if build_ctx else 0
                    crit_note = f" and {n_crit} matched evaluation criteria" if n_crit else ""
                    st.markdown(
                        f'<div class="info-box">🧠 <strong>BI has analyzed this RFP</strong> — '
                        f'{len(reqs)} requirements{crit_note}. BI can propose a submission-ready response '
                        f'structure from the RFP\'s own response architecture and evaluation intelligence.</div>',
                        unsafe_allow_html=True)
                    if st.button("🪄 Generate Proposal Structure", type="primary",
                                use_container_width=True, key="gen_outline_btn"):
                        with st.spinner("Deriving a proposal-ready structure from BI's analysis…"):
                            try:
                                st.session_state["proposed_outline"] = \
                                    tenancy.derive_proposal_outline_for_organization(bid_id, _org_id)
                            except tenancy.AccessDeniedError as e:
                                st.error(f"Not authorized: {e}")
                            except Exception as e:
                                st.error(f"Could not derive a proposal structure: {e}")
                        st.session_state.pop("proposed_outline_removed_ids", None)
                        st.rerun()
                elif not reqs:
                    st.markdown(
                        '<div class="info-box">No analyzed requirements found for this bid yet. '
                        'Complete DECIDE-stage analysis (Fast Analysis) first — BI can then propose a '
                        'response structure here. You can still add a section manually below.</div>',
                        unsafe_allow_html=True)
                else:
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

                    # ── PI-3D: per-section intelligence rollup (instruction 5) ──
                    mapped_ids = section_req_map.get(s_id, [])
                    if build_ctx:
                        s_sum = proposal_outline.summarize_section_intelligence(
                            mapped_ids, build_ctx.get("criterion_by_req_id"), build_ctx.get("assessment_by_req_id"))
                        readiness_c = _READINESS_COLOR.get(s_sum["evidence_readiness"], "#6E6C66")
                        st.markdown(
                            f'<div style="font-size:.7rem;color:#A9A69D;margin:-.3rem 0 .5rem .1rem">'
                            f'{s_sum["requirement_count"]} reqs · {s_sum["evaluation_criteria_count"]} criteria · '
                            f'Evidence: <span style="color:{readiness_c};font-weight:600">{s_sum["evidence_readiness"]}</span>'
                            f'</div>', unsafe_allow_html=True)
                    else:
                        st.markdown(
                            f'<div style="font-size:.7rem;color:#A9A69D;margin:-.3rem 0 .5rem .1rem">{len(mapped_ids)} reqs</div>',
                            unsafe_allow_html=True)

            # ── Proposed-outline review/edit/approve (instruction 4/7) ────
            # Nothing above is persisted automatically -- the user must
            # explicitly approve, and may rename/reorder/remove/add sections
            # first. Approval reuses the EXISTING outline_sections/
            # outline_section_requirements CRUD verbatim (no new table).
            if st.session_state.get("proposed_outline"):
                outline = st.session_state["proposed_outline"]
                proposed = outline["sections"]
                removed_ids = st.session_state.setdefault("proposed_outline_removed_ids", [])

                st.markdown("---")
                st.markdown("#### 🪄 Proposed Structure — review before creating")
                method_label = proposal_outline.DERIVATION_METHOD_LABELS.get(
                    outline.get("derivation_method"), outline.get("derivation_method"))
                st.caption(f"{method_label}. Nothing is created yet — rename, reorder, remove, or add sections, then approve.")
                if outline.get("model_refinement_attempted") and not outline.get("model_refinement_failure"):
                    st.caption("🧠 AI refinement was used to improve this structure (deterministic derivation alone was insufficient).")
                elif outline.get("model_refinement_failure"):
                    st.caption(f"⚠ AI refinement was attempted but did not complete ({outline['model_refinement_failure']}); showing the deterministic structure instead.")

                cov = outline.get("coverage") or {}
                ready = cov.get("is_ready", True)
                cov_color = "#27AE60" if ready else "#C0392B"
                st.markdown(
                    f'<div style="background:#111118;border:1px solid #292832;border-radius:6px;'
                    f'padding:.6rem .9rem;margin:.4rem 0;font-size:.8rem;color:#A9A69D">'
                    f'<strong style="color:#EDEAE3">{cov.get("mapped_requirement_count",0)}</strong>/'
                    f'<strong style="color:#EDEAE3">{cov.get("total_requirement_count",0)}</strong> requirements mapped · '
                    f'<strong style="color:#EDEAE3">{cov.get("orphaned_requirement_count",0)}</strong> unresolved · '
                    f'Status: <strong style="color:{cov_color}">{"Ready" if ready else "Not ready — mandatory requirements unresolved"}</strong>'
                    f'</div>', unsafe_allow_html=True)
                if not ready:
                    st.warning(
                        f"{cov.get('orphaned_mandatory_count',0)} mandatory requirement(s) are not yet mapped to any "
                        f"section — resolve them (map manually after creation, or adjust the structure below) before "
                        f"treating this outline as submission-ready.")

                struct_warnings = proposal_outline.surface_high_weight_structural_warnings(proposed)
                if struct_warnings:
                    with st.expander(f"⚠ {len(struct_warnings)} structural prominence note(s)", expanded=False):
                        for w in struct_warnings:
                            st.caption(w["message"])

                for i, psec in enumerate(proposed):
                    c_p1, c_p2, c_p3, c_p4 = st.columns([3, 1.3, 0.5, 0.5])
                    psec["title"] = c_p1.text_input(
                        "Title", value=psec["title"], key=f"prop_title_{i}", label_visibility="collapsed")
                    n_reqs = len(psec.get("mapped_requirement_ids") or [])
                    n_checklist = len(psec.get("checklist_items") or [])
                    extent = f"{n_reqs} reqs" if n_reqs else (f"{n_checklist} items" if n_checklist else "0 reqs")
                    c_p2.caption(extent)
                    if c_p3.button("↑", key=f"prop_up_{i}", disabled=(i == 0), help="Move up"):
                        proposed[i - 1], proposed[i] = proposed[i], proposed[i - 1]
                        st.rerun()
                    if c_p4.button("🗑", key=f"prop_del_{i}", help="Remove"):
                        removed = proposed.pop(i)
                        newly_orphaned = removed.get("mapped_requirement_ids") or []
                        if newly_orphaned:
                            removed_ids.extend(newly_orphaned)
                            st.warning(
                                f'Removed "{removed["title"]}" — {len(newly_orphaned)} requirement(s) it covered '
                                f'are now unmapped. Map them to another section below, or resolve them manually '
                                f'after creating the outline.')
                        st.rerun()
                    if psec.get("rationale"):
                        st.caption(psec["rationale"])

                if removed_ids:
                    st.caption(
                        f"⚠ {len(removed_ids)} requirement(s) from removed sections are currently unmapped in this proposal.")

                c_a1, c_a2, c_a3 = st.columns([1.3, 1, 1.7])
                if c_a1.button("➕ Add Blank Section", key="prop_add_blank", use_container_width=True):
                    proposed.append({
                        "title": "New Section", "section_num": f"{len(proposed) + 1}.0",
                        "source_basis": None, "derivation_method": None,
                        "mapped_requirement_ids": [], "rationale": "", "word_limit": proposal_outline.DEFAULT_WORD_LIMIT,
                    })
                    st.rerun()
                if c_a2.button("❌ Cancel", key="prop_cancel", use_container_width=True):
                    st.session_state.pop("proposed_outline", None)
                    st.session_state.pop("proposed_outline_removed_ids", None)
                    st.rerun()
                if c_a3.button("✅ Approve & Create Sections", type="primary",
                               use_container_width=True, key="prop_approve"):
                    created = 0
                    for i, psec in enumerate(proposed):
                        if not (psec.get("title") or "").strip():
                            continue
                        new_id = tenancy.upsert_section_authenticated(_token, {
                            "id": None, "bid_id": bid_id, "title": psec["title"].strip(),
                            "section_num": psec.get("section_num") or f"{i + 1}.0",
                            "owner": "", "word_limit": psec.get("word_limit") or proposal_outline.DEFAULT_WORD_LIMIT,
                            "sort_order": i, "status": "Not Started", "notes": "",
                        })
                        mapped_ids = psec.get("mapped_requirement_ids") or []
                        if new_id and mapped_ids:
                            try:
                                tenancy.set_section_requirement_mapping_authenticated(
                                    _token, bid_id, new_id, mapped_ids)
                            except tenancy.SectionMappingUnavailableError as e:
                                st.caption(f"⚠ {e}")
                        created += 1
                    st.session_state.pop("proposed_outline", None)
                    st.session_state.pop("proposed_outline_removed_ids", None)
                    st.success(f"Created {created} proposal section(s) from BI's analysis.")
                    st.rerun()

            with st.expander("➕ Add Section Manually", expanded=(not sections and not reqs)):
                with st.form("add_outline_sec_form", clear_on_submit=True):
                    n_title = st.text_input("Section Title *")
                    c_n1, c_n2 = st.columns(2)
                    n_num = c_n1.text_input("Section Number", placeholder="e.g. 1.0 or §2")
                    n_owner = c_n2.text_input("Section Owner")
                    n_wlimit = st.number_input("Word Count Target", value=500, step=50)
                    n_notes = st.text_area("Scope / Guidance", height=50)
                    if st.form_submit_button("Add Section", use_container_width=True):
                        if n_title:
                            tenancy.upsert_section_authenticated(_token, {
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
                st.markdown(f"#### [{active_sec.get('section_num','')}] {active_sec['title']}")
                st.markdown(f'<div style="font-size:.78rem;color:#A9A69D;margin-bottom:.5rem">Owner: <strong>{active_sec.get("owner") or "Unassigned"}</strong> · Target: <strong>{active_sec.get("word_limit") or 500} words</strong></div>', unsafe_allow_html=True)

                # Requirements mapped in-view -- durably persisted (migrations/
                # 013_section_analyzer.sql), not session-state only: reopening
                # this bid later shows the same mapping.
                with st.expander("🎯 Evaluation Criteria In View (Mapped Requirements)", expanded=True):
                    st.markdown(
                        '<div style="font-size:.75rem;color:#A9A69D;margin-bottom:.3rem">'
                        'Select requirements this section must satisfy:'
                        '</div>',
                        unsafe_allow_html=True
                    )
                    req_options = {f"[{r.get('req_id','—')}] ({r.get('category','')}) {r.get('description','')[:65]}": r for r in reqs}
                    persisted_req_ids = tenancy.get_section_requirement_ids_authenticated(_token, active_sec["id"])
                    default_req_keys = [k for k, r in req_options.items() if r.get("id") in persisted_req_ids]
                    selected_req_keys = st.multiselect("Mapped Requirements", list(req_options.keys()),
                                                       default=default_req_keys, key=f"req_map_{active_sec['id']}")
                    mapped_reqs = [req_options[k] for k in selected_req_keys]
                    mapped_req_ids = sorted(r["id"] for r in mapped_reqs if r.get("id"))
                    if set(mapped_req_ids) != set(persisted_req_ids):
                        try:
                            tenancy.set_section_requirement_mapping_authenticated(
                                _token, bid_id, active_sec["id"], mapped_req_ids)
                            persisted_req_ids = mapped_req_ids
                        except tenancy.SectionMappingUnavailableError as e:
                            st.caption(f"⚠ {e} Drafting below still uses all bid requirements meanwhile.")

                # ── PI-3D: section intelligence summary (instruction 5) ──────
                # Pure rollup (proposal_outline.summarize_section_intelligence)
                # over the bulk context fetched once above plus a bounded,
                # section-scoped draft-existence read -- never a new evidence
                # model, never a per-requirement Anthropic/OM call.
                try:
                    draft_exists_by_req_id = tenancy.get_draft_existence_map_for_organization(
                        bid_id, _org_id, mapped_reqs) if mapped_reqs else {}
                except tenancy.AccessDeniedError:
                    draft_exists_by_req_id = {}
                sec_summary = proposal_outline.summarize_section_intelligence(
                    mapped_req_ids,
                    build_ctx.get("criterion_by_req_id") if build_ctx else None,
                    build_ctx.get("assessment_by_req_id") if build_ctx else None,
                    draft_exists_by_req_id,
                )
                readiness_c = _READINESS_COLOR.get(sec_summary["evidence_readiness"], "#6E6C66")
                st.markdown(
                    f'<div style="background:#111118;border:1px solid #292832;border-radius:6px;'
                    f'padding:.6rem .9rem;margin:.4rem 0;font-size:.78rem;color:#A9A69D">'
                    f'<strong style="color:#EDEAE3">{sec_summary["requirement_count"]}</strong> requirements · '
                    f'<strong style="color:#EDEAE3">{sec_summary["evaluation_criteria_count"]}</strong> evaluation criteria · '
                    f'Evidence: <strong style="color:{readiness_c}">{sec_summary["evidence_readiness"]}</strong> · '
                    f'<strong style="color:#EDEAE3">{sec_summary["unresolved_gap_count"]}</strong> unresolved · '
                    f'Draft: <strong style="color:#EDEAE3">{_DRAFT_STATUS_LABEL.get(sec_summary["draft_status"], sec_summary["draft_status"])}</strong>'
                    f'</div>', unsafe_allow_html=True)

                # ── PI-3D: AI-assisted drafting, made prominent (instructions
                # 6/7) -- reuses PI-3C's render_requirement_drafting_workspace
                # verbatim, one requirement at a time (never a whole-section or
                # whole-proposal call). Was previously buried in a collapsed,
                # third-level nested expander below a competing, non-evidence-
                # aware "quick draft" button -- this is now the primary,
                # expanded-by-default AI drafting surface for this section.
                st.markdown("##### 🧠 Draft with BI — Evidence-Aware Section Drafting")
                workspace_pool = mapped_reqs if mapped_reqs else reqs
                if not workspace_pool:
                    st.caption("Map requirements to this section above to enable evidence-aware drafting.")
                else:
                    ws_options = {
                        f"[{r.get('req_id','—')}] {r.get('description','')[:70]}": r
                        for r in workspace_pool if r.get("id")
                    }
                    ws_choice = st.selectbox(
                        "Requirement:", list(ws_options.keys()), key=f"ws_req_pick_{active_sec['id']}")
                    if ws_choice:
                        render_requirement_drafting_workspace(
                            bid_id, ws_options[ws_choice], outline_section=active_sec)

                # Semantic Content Reuse
                with st.expander("📚 Relevant Content Library Blocks (Semantic Search)", expanded=False):
                    lib_results, used_semantic = tenancy.semantic_library_search_authenticated(_token, active_sec["title"], bid_id, top_k=4)
                    if lib_results:
                        for lib_item in lib_results:
                            st.markdown(f"**[{lib_item.get('category','')}] {lib_item.get('title','')}**")
                            st.markdown(f'<div style="font-size:.78rem;color:#EDEAE3;background:#111118;border:1px solid #292832;border-radius:4px;padding:.5rem;max-height:120px;overflow-y:auto;white-space:pre-wrap">{lib_item.get("content","")[:300]}…</div>', unsafe_allow_html=True)
                    else:
                        st.markdown('<div style="font-size:.75rem;color:#6E6C66">No library items found. Add items to the Content Library.</div>', unsafe_allow_html=True)

                # ── Manual section content (instruction 2: manual control
                # preserved) -- direct authoring/editing, independent of the
                # AI drafting workspace above (never auto-populated from it).
                st.markdown("##### ✍️ Manual Section Content")
                current_draft = active_sec.get("notes") or ""
                edited_draft = st.text_area("Section Content", value=current_draft, height=260, key=f"txt_draft_{active_sec['id']}")

                c_s1, c_s2, c_s3 = st.columns([1.5, 1.5, 1])
                new_sec_stat = c_s1.selectbox("Status", STATUSES, index=STATUSES.index(active_sec.get("status", "Draft")) if active_sec.get("status") in STATUSES else 2, key=f"stat_{active_sec['id']}")
                if c_s2.button("💾 Save Section", key=f"save_sec_{active_sec['id']}", use_container_width=True):
                    tenancy.upsert_section_authenticated(_token, {
                        **active_sec,
                        "notes": edited_draft,
                        "status": new_sec_stat
                    })
                    st.success("Saved.")
                    st.rerun()
                if c_s3.button("🗑", key=f"del_sec_{active_sec['id']}", help="Delete section"):
                    tenancy.delete_section_authenticated(_token, active_sec["id"])
                    st.session_state.pop("active_draft_sec", None)
                    st.rerun()

                # ── SECTION ANALYZER ─────────────────────────────────────────
                # Formative review of the CURRENT editor text (`edited_draft`,
                # the text_area's own live value from this exact run -- never
                # the last-saved DB value) against this section's mapped
                # requirements. Lives in BUILD, not CHECK -- see
                # section_analyzer.py's module docstring for why.
                st.markdown("")
                if st.button("🔎 Analyze This Section", key=f"analyze_sec_{active_sec['id']}", use_container_width=True):
                    if not (api_key_configured() or st.session_state.get("anthropic_api_key")):
                        st.error("Configure Anthropic API key to use the Section Analyzer.")
                    else:
                        with st.spinner("Analyzing section direction against buyer requirements… 15–45s"):
                            try:
                                session = auth_session.current_session()
                                tenancy.analyze_section_for_organization(
                                    bid_id, active_sec["id"], edited_draft, mapped_req_ids,
                                    _org_id, user_id=session.get("user_id"))
                                st.rerun()
                            except section_analyzer.SectionAnalyzerError as e:
                                st.error(f"Analysis could not be completed ({e.category}): {e}")
                            except tenancy.AccessDeniedError as e:
                                st.error(f"Not authorized: {e}")
                            except Exception as e:
                                st.error(f"Analysis failed: {e}")

                reviews = tenancy.get_section_reviews_authenticated(_token, bid_id, active_sec["id"])
                if reviews:
                    latest = reviews[0]
                    basis = section_analyzer.procurement_basis(bid_id)
                    current_hash = section_analyzer.content_hash(edited_draft)
                    stale = section_analyzer.is_section_review_stale(latest, current_hash, set(mapped_req_ids), basis)
                    _render_section_review(latest, stale)
                    if len(reviews) > 1:
                        with st.expander(f"Previous Reviews ({len(reviews) - 1})", expanded=False):
                            for r in reviews[1:]:
                                st.markdown(
                                    f'<div style="font-size:.78rem;color:#A9A69D;padding:.3rem 0;border-bottom:1px solid #292832">'
                                    f'{r["created_at"][:19].replace("T"," ")} · <strong>{r["direction"].replace("_"," ").title()}</strong> · '
                                    f'content {r["section_content_hash"][:10]}…'
                                    f'</div>', unsafe_allow_html=True)
                                if st.button("Open", key=f"open_review_{r['id']}"):
                                    _render_section_review(r, stale=True, key_prefix=f"hist_{r['id']}_")

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
                        tenancy.delete_deliverable_authenticated(_token, d["id"])
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
                        tenancy.upsert_deliverable_authenticated(_token, {
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
                tenancy.upload_document_for_organization(bid_id, _org_id, up_file.name, fb, doc_type="Submission")
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
                    tenancy.delete_task_authenticated(_token, t["id"])
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
                        tenancy.upsert_task_authenticated(_token, {"id": None, "bid_id": bid_id, "title": t_title, "owner": t_owner, "due_date": t_due, "priority": t_pri, "status": "Not Started"})
                        st.rerun()

    # ── NEXT STAGE CTA ────────────────────────────────────────────────────────
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    c1, c2 = st.columns([3, 1])
    c1.markdown('<div style="color:#A9A69D;font-size:.85rem;padding-top:.4rem">Draft complete? Review compliance and proposal alignment.</div>', unsafe_allow_html=True)
    if c2.button("Proceed to CHECK →", use_container_width=True, type="primary"):
        st.session_state.page = "stage_check"
        st.rerun()
