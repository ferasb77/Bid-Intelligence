"""
Stage 1: UNDERSTAND — Bid Brief
Transforms raw RFP / tender documents into structured executive intelligence.
Answers:
1. What is this opportunity?
2. What are they actually procuring?
3. What do we need to deliver?
4. What conditions must we satisfy to qualify (Hard Gates)?
5. How will the bid be evaluated?
6. What commercial / contractual conditions matter?
7. What are the main risks?
8. What needs to be submitted and when?
"""
import json
import streamlit as st
from database import (get_bid, get_bid_brief, upsert_bid_brief, get_requirements,
                      get_documents, save_upload, update_bid)
from components.ui import (stage_badge, days_until, days_label, metric_card,
                           readiness_bar, STAGES, SENSITIVITY)


def _ensure_dict(val):
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            pass
    return {}


def _ensure_list(val):
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
    return []


def page_understand(bid_id: int):
    bid = get_bid(bid_id)
    if not bid:
        st.error("Opportunity not found.")
        return

    brief_row = get_bid_brief(bid_id) or {}
    reqs = get_requirements(bid_id)
    docs = get_documents(bid_id)

    # Decode JSON fields from brief_row if present
    exec_summary = brief_row.get("executive_summary") or bid.get("notes") or "Executive summary pending synthesis."
    opp_type = brief_row.get("opportunity_type") or "Not classified"
    contract_term = brief_row.get("contract_term") or "Not stated"
    proc_model = brief_row.get("procurement_model") or "Not classified"
    scope_cats = _ensure_list(brief_row.get("scope_categories"))
    deliverables = _ensure_list(brief_row.get("deliverables_summary"))
    qual_gates = _ensure_list(brief_row.get("qualification_gates"))
    eval_breakdown = _ensure_list(brief_row.get("evaluation_breakdown"))
    commercial = _ensure_list(brief_row.get("commercial_structure"))
    contract_risks = _ensure_list(brief_row.get("contract_risks"))
    sub_reqs = _ensure_list(brief_row.get("submission_requirements"))
    key_dates = _ensure_list(brief_row.get("key_dates"))
    citations = _ensure_dict(brief_row.get("source_citations"))

    # ── HEADER & OPPORTUNITY IDENTITY ─────────────────────────────────────────
    st.markdown('<div style="font-size:.72rem;color:#C9A96E;text-transform:uppercase;letter-spacing:.12em;font-weight:600">STAGE 1 · UNDERSTAND</div>', unsafe_allow_html=True)
    c1, c2 = st.columns([4, 1.2])
    c1.markdown(f"# {bid['client']}")
    c1.markdown(f'<div style="font-size:1.15rem;color:#EDEAE3;font-weight:500;margin-top:-.3rem">{bid["title"]}</div>', unsafe_allow_html=True)
    if bid.get("file_number"):
        c1.markdown(f'<span style="font-size:.78rem;color:#6E6C66">Solicitation Ref: <strong>#{bid["file_number"]}</strong></span>', unsafe_allow_html=True)

    c2.markdown(f'<div style="text-align:right">{stage_badge(bid["stage"])}</div>', unsafe_allow_html=True)
    sc = "#C0392B" if bid.get("sensitivity") == "Sensitive" else "#27AE60"
    c2.markdown(f'<div style="text-align:right;font-size:.75rem;color:{sc};margin-top:.3rem">● {bid.get("sensitivity","Standard")}</div>', unsafe_allow_html=True)

    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)

    # ── TOP KPI SUMMARY CARDS ──────────────────────────────────────────────────
    sub_days = days_until(bid.get("submission_deadline"))
    clar_days = days_until(bid.get("clarification_deadline"))
    val_str = f"CAD {bid['value_cad']:,.0f}" if bid.get("value_cad") else "Not stated"

    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(metric_card("Submission Deadline", bid.get("submission_deadline") or "—", days_label(sub_days) if sub_days is not None else "Date unconfirmed"), unsafe_allow_html=True)
    k2.markdown(metric_card("Enquiry Deadline", bid.get("clarification_deadline") or "—", days_label(clar_days) if clar_days is not None else "Date unconfirmed"), unsafe_allow_html=True)
    k3.markdown(metric_card("Est. Value / Term", val_str, contract_term[:32]), unsafe_allow_html=True)
    k4.markdown(metric_card("Procurement Model", proc_model[:22], f"Lead: {bid.get('owner') or 'Unassigned'}"), unsafe_allow_html=True)
    st.markdown("")

    # ── SECTION A0: CROSS-DOCUMENT CONFLICTS & DISCREPANCIES ──────────────────
    document_conflicts = _ensure_list(brief_row.get("document_conflicts"))
    if document_conflicts:
        st.markdown("### ⚠️ Document Discrepancies & Cross-Document Conflicts")
        st.markdown(
            '<div class="warn-box">'
            '<strong>Discrepancies Detected Across Procurement Package:</strong> Contradictions or differing instructions were identified between source documents. '
            'Review these discrepancies and submit formal clarification questions before the enquiry deadline.'
            '</div>',
            unsafe_allow_html=True
        )
        for dc in document_conflicts:
            s_a = dc.get("source_a", {}) if isinstance(dc.get("source_a"), dict) else {"doc": "Source A", "text": str(dc.get("source_a",""))}
            s_b = dc.get("source_b", {}) if isinstance(dc.get("source_b"), dict) else {"doc": "Source B", "text": str(dc.get("source_b",""))}
            classification = dc.get("classification", "TRUE_CONFLICT" if dc.get("conflict_type") else "REVIEW_ITEM")
            is_review = classification == "REVIEW_ITEM"
            badge_col = "#E67E22" if is_review else "#C0392B"
            badge_label = "REVIEW ITEM" if is_review else "TRUE CONFLICT"
            
            st.markdown(
                f'<div style="background:#1A0F00;border:1px solid #3A2A00;border-left:4px solid {badge_col};'
                f'border-radius:0 4px 4px 0;padding:.7rem 1.1rem;margin:.4rem 0">'
                f'<span style="color:{badge_col};font-weight:700;font-size:.76rem">[{badge_label}]</span> '
                f'<span style="color:#A9A69D;font-size:.74rem">[{dc.get("conflict_type","CONFLICT")}]</span> '
                f'<strong>{dc.get("topic","Discrepancy")}</strong>'
                f'<div style="font-size:.8rem;color:#EDEAE3;margin-top:.3rem">'
                f'<strong>Source A ({s_a.get("doc","Doc A")}):</strong> {s_a.get("text","")}<br>'
                f'<strong>Source B ({s_b.get("doc","Doc B")}):</strong> {s_b.get("text","")}'
                f'</div>'
                f'{"<div style=font-size:.76rem;color:#C9A96E;margin-top:.2rem><strong>Reason:</strong> " + dc.get("reason","") + "</div>" if dc.get("reason") else ""}'
                f'<div style="font-size:.76rem;color:#E67E22;margin-top:.3rem"><strong>Assessment:</strong> {dc.get("assessment","")}</div>'
                f'<div style="font-size:.76rem;color:#27AE60;margin-top:.2rem">💡 <strong>Action:</strong> {dc.get("recommended_action","Submit clarification question")}</div>'
                f'</div>',
                unsafe_allow_html=True
            )
        st.markdown("")

    # ── SECTION A: EXECUTIVE SUMMARY ──────────────────────────────────────────
    st.markdown("### 💡 Executive Synthesis: What Is the Buyer Procuring?")
    st.markdown(
        f'<div style="background:#111118;border:1px solid #292832;border-left:4px solid #C9A96E;'
        f'border-radius:0 6px 6px 0;padding:1.1rem 1.4rem;font-size:.95rem;line-height:1.6;color:#EDEAE3">'
        f'{exec_summary}'
        f'</div>',
        unsafe_allow_html=True
    )
    st.markdown("")

    # ── SECTION B: SCOPE & DELIVERABLES ───────────────────────────────────────
    c_scope, c_deliv = st.columns(2)
    with c_scope:
        st.markdown("### 🎯 What They Want (Scope)")
        if scope_cats:
            for s in scope_cats:
                st.markdown(
                    f'<div style="background:#111118;border:1px solid #292832;border-radius:4px;'
                    f'padding:.6rem .9rem;margin:.3rem 0;font-size:.85rem">'
                    f'<span style="color:#C9A96E;font-weight:600">▪</span> {s}</div>',
                    unsafe_allow_html=True
                )
        else:
            st.markdown('<div class="info-box">Scope details extracted from Statement of Work.</div>', unsafe_allow_html=True)

    with c_deliv:
        st.markdown("### 📦 Main Deliverables (Outputs)")
        if deliverables:
            for d in deliverables:
                cat_tag = f'<span style="font-size:.68rem;color:#C9A96E;margin-left:.4rem">[{d.get("category","Core")}]</span>' if d.get("category") else ""
                st.markdown(
                    f'<div style="background:#111118;border:1px solid #292832;border-radius:4px;'
                    f'padding:.6rem .9rem;margin:.3rem 0;font-size:.85rem">'
                    f'<strong>{d.get("title","Deliverable")}</strong>{cat_tag}'
                    f'{"<br><span style=font-size:.76rem;color:#A9A69D>" + d.get("description","") + "</span>" if d.get("description") else ""}'
                    f'</div>',
                    unsafe_allow_html=True
                )
        else:
            st.markdown('<div class="info-box">Deliverable outputs extracted from RFP requirements.</div>', unsafe_allow_html=True)

    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

    # ── SECTION C: CONDITIONS TO QUALIFY (HARD GATES) ─────────────────────────
    st.markdown("### ⚖️ Conditions to Qualify (Mandatory Gates vs Scored Criteria)")
    st.markdown(
        '<div class="info-box">'
        '<strong>Critical Gate Rule:</strong> True pass/fail mandatory qualification conditions are separated from competitive scored criteria. '
        'Any mandatory gate must be satisfied or the bid will be disqualified.'
        '</div>',
        unsafe_allow_html=True
    )

    from components.ui import qual_badge, evidence_badge
    from requirement_semantics import select_qualification_requirements, normalize_requirement_identity_text

    # Match authoritative brief qualification gates to persisted requirements
    matched_qual_reqs = select_qualification_requirements(reqs, qual_gates)

    if matched_qual_reqs:
        for idx, r in enumerate(matched_qual_reqs, 1):
            ref_str = f' <span style="font-size:.72rem;color:#6E6C66">({r.get("rfso_ref","Gate")})</span>' if r.get("rfso_ref") else ""
            q_status = r.get("qual_status", "UNKNOWN")
            e_status = r.get("evidence_status", "MISSING")
            st.markdown(
                f'<div style="background:#1A0F00;border:1px solid #3A2A00;border-left:3px solid #E67E22;'
                f'border-radius:0 4px 4px 0;padding:.6rem 1rem;margin:.35rem 0;font-size:.85rem">'
                f'<div style="display:flex;justify-content:space-between;align-items:center">'
                f'<span style="color:#E67E22;font-weight:700">GATE #{idx} [{r.get("req_id","M")}]</span>'
                f'<span>{qual_badge(q_status)} {evidence_badge(e_status)}</span>'
                f'</div>'
                f'<div style="margin-top:.2rem;color:#EDEAE3">{r.get("description","")}{ref_str}</div>'
                f'</div>',
                unsafe_allow_html=True
            )
    elif qual_gates:
        # Gates exist in brief but did not match database rows (e.g. before requirement persistence)
        for idx, g in enumerate(qual_gates, 1):
            ref_str = f' <span style="font-size:.72rem;color:#6E6C66">({g.get("rfp_ref","Ref")})</span>' if g.get("rfp_ref") else ""
            st.markdown(
                f'<div style="background:#1A0F00;border:1px solid #3A2A00;border-left:3px solid #E67E22;'
                f'border-radius:0 4px 4px 0;padding:.6rem 1rem;margin:.35rem 0;font-size:.85rem">'
                f'<span style="color:#E67E22;font-weight:700">GATE #{idx} [{g.get("type","Supplier Qualification")}]</span>{ref_str}'
                f'<div style="margin-top:.2rem;color:#EDEAE3">{g.get("requirement","")}</div>'
                f'</div>',
                unsafe_allow_html=True
            )
    else:
        st.markdown(
            '<div class="empty-state">'
            'No explicit pass/fail supplier qualification gates were identified. '
            'Mandatory compliance requirements remain tracked in the compliance register.'
            '</div>',
            unsafe_allow_html=True
        )

    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

    # ── SECTION D: EVALUATION & COMMERCIAL STRUCTURE ──────────────────────────
    c_eval, c_comm = st.columns(2)
    with c_eval:
        st.markdown("### 📊 How We Will Be Evaluated")
        if eval_breakdown:
            from evaluation_hierarchy import (
                format_evaluation_for_display,
                STATUS_VALID,
                STATUS_SOURCE_DISCREPANCY,
                STATUS_UNRESOLVED_HIERARCHY,
                STATUS_MIXED_UNITS,
                STATUS_INSUFFICIENT_DATA,
                BASIS_WITHIN_PARENT,
            )
            display_rows, totals = format_evaluation_for_display(eval_breakdown)

            for ev in display_rows:
                raw_wt = ev.get("weight") or ""
                val = ev.get("weight_value")
                unit = ev.get("weight_unit")
                basis = ev.get("weight_basis")
                indent = ev.get("indent", 0)

                # Format weight badge
                if raw_wt:
                    basis_suffix = f" (Within {ev.get('parent_stage', 'Parent')})" if basis == BASIS_WITHIN_PARENT else ""
                    wt_html = f'<span style="color:#27AE60;font-weight:700">{raw_wt}{basis_suffix}</span>'
                else:
                    wt_html = ""

                th_html = f' · Threshold: {ev.get("threshold")}' if ev.get("threshold") else ""
                margin_left = f"{indent * 1.5}rem"
                bg_col = "#111118" if indent == 0 else "#151520"
                border_style = "border:1px solid #292832" if indent == 0 else "border:1px solid #222230;border-left:2px solid #C9A96E"

                st.markdown(
                    f'<div style="background:{bg_col};{border_style};border-radius:4px;'
                    f'padding:.55rem .9rem;margin:.3rem 0;margin-left:{margin_left};font-size:.85rem">'
                    f'<strong>{ev.get("stage","Evaluation Stage")}</strong> {("— " + wt_html) if wt_html else ""}{th_html}'
                    f'{"<br><span style=font-size:.76rem;color:#A9A69D>" + ev.get("notes","") + "</span>" if ev.get("notes") else ""}'
                    f'</div>',
                    unsafe_allow_html=True
                )

            # Overall total and status presentation
            status = totals.get("status")
            overall_tot = totals.get("overall_total")
            overall_unit = totals.get("overall_unit")

            if status == STATUS_VALID:
                tot_str = f"{overall_tot:.0f}%" if overall_unit == "Percent" else f"{overall_tot} {overall_unit}"
                st.markdown(
                    f'<div style="background:#0F1F15;border:1px solid #27AE60;border-radius:4px;padding:.5rem .8rem;margin-top:.6rem;font-size:.84rem;color:#2ECC71;font-weight:600">'
                    f'✓ Top-level weighting: {tot_str}'
                    f'</div>',
                    unsafe_allow_html=True
                )
            elif status == STATUS_SOURCE_DISCREPANCY:
                tot_str = f"{overall_tot:.1f}%" if overall_unit == "Percent" else f"{overall_tot} {overall_unit}"
                st.markdown(
                    f'<div style="background:#2A1A10;border:1px solid #E67E22;border-radius:4px;padding:.5rem .8rem;margin-top:.6rem;font-size:.84rem;color:#E67E22;font-weight:600">'
                    f'⚠ Source weighting totals {tot_str} — review procurement documents for discrepancy.'
                    f'</div>',
                    unsafe_allow_html=True
                )
            elif status == STATUS_UNRESOLVED_HIERARCHY:
                st.markdown(
                    '<div style="background:#201A24;border:1px solid #9B59B6;border-radius:4px;padding:.5rem .8rem;margin-top:.6rem;font-size:.84rem;color:#D2B4DE;font-weight:600">'
                    '⚠ Overall weighting cannot be safely calculated from the source structure.'
                    '</div>',
                    unsafe_allow_html=True
                )
            elif status == STATUS_MIXED_UNITS:
                st.markdown(
                    '<div style="background:#201A24;border:1px solid #3498DB;border-radius:4px;padding:.5rem .8rem;margin-top:.6rem;font-size:.84rem;color:#85C1E9;font-weight:600">'
                    'ℹ Percent and point-based scoring are shown separately.'
                    '</div>',
                    unsafe_allow_html=True
                )
            elif status == STATUS_INSUFFICIENT_DATA:
                st.markdown(
                    '<div style="background:#1C1C24;border:1px solid #566573;border-radius:4px;padding:.5rem .8rem;margin-top:.6rem;font-size:.84rem;color:#A6ACAF">'
                    'ℹ Evaluation weighting details incomplete in tender instructions.'
                    '</div>',
                    unsafe_allow_html=True
                )
        else:
            st.markdown('<div class="info-box">Evaluation weighting details extracted from RFP instructions.</div>', unsafe_allow_html=True)

    with c_comm:
        st.markdown("### 💼 Commercial & Contracting Structure")
        if commercial:
            for cm in commercial:
                st.markdown(
                    f'<div style="background:#111118;border:1px solid #292832;border-radius:4px;'
                    f'padding:.6rem .9rem;margin:.3rem 0;font-size:.85rem">'
                    f'<strong style="color:#C9A96E">{cm.get("topic","Commercial Item")}</strong>'
                    f'<div style="font-size:.78rem;color:#EDEAE3;margin-top:.2rem">{cm.get("details","")}</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
        else:
            st.markdown('<div class="info-box">Commercial rules (pricing model, option periods, call-up mechanics) summarized from RFP terms.</div>', unsafe_allow_html=True)

    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

    # ── SECTION E: CONTRACT & DELIVERY RISKS ──────────────────────────────────
    st.markdown("### ⚠️ Contract & Delivery Risks")
    st.markdown(
        '<div style="font-size:.82rem;color:#A9A69D;margin-bottom:.5rem">'
        'Conditions that could materially affect delivery, liability, or margin. Review before committing writing resources.'
        '</div>',
        unsafe_allow_html=True
    )
    if contract_risks:
        for rk in contract_risks:
            sev = rk.get("severity", "Medium")
            sc_col = "#C0392B" if sev == "High" else "#E67E22" if sev == "Medium" else "#6E6C66"
            st.markdown(
                f'<div style="background:#111118;border:1px solid #292832;border-left:3px solid {sc_col};'
                f'border-radius:0 4px 4px 0;padding:.6rem 1rem;margin:.35rem 0;font-size:.85rem">'
                f'<span style="color:{sc_col};font-weight:700;font-size:.75rem">RISK [{sev.upper()}]</span> '
                f'<strong>{rk.get("risk","")}</strong>'
                f'<div style="font-size:.78rem;color:#A9A69D;margin-top:.2rem">{rk.get("details","")}</div>'
                f'</div>',
                unsafe_allow_html=True
            )
    else:
        st.markdown('<div class="success-box">No critical contract liability blockers extracted.</div>', unsafe_allow_html=True)

    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

    # ── SECTION F: SUBMISSION REQUIREMENTS & KEY DATES ────────────────────────
    c_subreq, c_dates = st.columns(2)
    with c_subreq:
        st.markdown("### 📋 Submission Requirements Checklist")
        if sub_reqs:
            for sr in sub_reqs:
                st.markdown(
                    f'<div style="background:#111118;border:1px solid #292832;border-radius:4px;'
                    f'padding:.5rem .8rem;margin:.3rem 0;font-size:.82rem">'
                    f'☐ <strong>{sr.get("item","")}</strong> '
                    f'{"<span style=color:#C9A96E;font-size:.72rem>(" + sr.get("format","") + ")</span>" if sr.get("format") else ""}'
                    f'{"<br><span style=font-size:.74rem;color:#A9A69D>" + sr.get("details","") + "</span>" if sr.get("details") else ""}'
                    f'</div>',
                    unsafe_allow_html=True
                )
        else:
            st.markdown('<div class="info-box">No explicit submission documents were identified in the procurement package.</div>', unsafe_allow_html=True)

    with c_dates:
        st.markdown("### 📅 Key Procurement Dates")
        if key_dates:
            for kd in key_dates:
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;background:#111118;'
                    f'border:1px solid #292832;border-radius:4px;padding:.5rem .8rem;margin:.3rem 0;font-size:.82rem">'
                    f'<span>{kd.get("milestone","")}</span>'
                    f'<strong style="color:#C9A96E">{kd.get("date","")}</strong>'
                    f'</div>',
                    unsafe_allow_html=True
                )
        else:
            st.markdown(
                f'<div style="background:#111118;border:1px solid #292832;border-radius:4px;padding:.6rem .8rem;font-size:.82rem">'
                f'Submission deadline: <strong>{bid.get("submission_deadline") or "—"}</strong><br>'
                f'Enquiry deadline: <strong>{bid.get("clarification_deadline") or "—"}</strong>'
                f'</div>',
                unsafe_allow_html=True
            )

    # ── PROGRESSIVE DISCLOSURE: SOURCE CITATIONS & VERBATIM DETAILS ───────────
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    with st.expander("🔍 View Extracted Source Citations & RFP Details"):
        st.markdown(f"**RFP Documents in Registry ({len(docs)} files):**")
        for d in docs:
            st.markdown(f"📄 **{d['name']}** ({d.get('doc_type','Document')}) — v{d.get('version',1)} [{d.get('status','Expected')}]")
        if citations:
            st.markdown("**Key Section Citations:**")
            for k, v in citations.items():
                st.markdown(f"• `{k}`: {v}")

    # ── NEXT STAGE CALL TO ACTION ─────────────────────────────────────────────
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    c1, c2 = st.columns([3, 1])
    c1.markdown(
        '<div style="color:#A9A69D;font-size:.85rem;padding-top:.4rem">'
        'Ready to assess qualification gates, clarify ambiguities, and decide whether to pursue?'
        '</div>',
        unsafe_allow_html=True
    )
    if c2.button("Proceed to DECIDE →", use_container_width=True, type="primary"):
        st.session_state.page = "stage_decide"
        st.rerun()
