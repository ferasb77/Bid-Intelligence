"""
Stage 2: DECIDE — Qualification & Pursuit Decision
Answers:
1. What conditions must we satisfy to qualify?
2. Can we legitimately qualify? (PASS / CONCERN / FAIL / UNKNOWN)
3. What ambiguities must be clarified before the question deadline?
4. Should we bid? (GO / GO WITH CONDITIONS / NO-GO / NEEDS MORE INFO)
5. Accountable Human Decision Override & Rationale.
"""
import json
import streamlit as st
from datetime import datetime
from analyst import generate_clarification_questions, bid_no_bid_score
from config import api_key_configured
from components.ui import (qual_badge, evidence_badge, decision_badge, days_until, days_label,
                           metric_card, procurement_staleness_banner, QUAL_STATUSES, EVIDENCE_STATUSES, CATEGORIES)
import auth_session
import tenancy


def _current_access_token_and_org() -> tuple[str, str]:
    """Phase 8 remediation package 3: every read/write on this page goes
    through the authenticated, RLS-backed client -- app.py's mandatory
    auth gate guarantees a real session and resolved AuthContext exist by
    the time this page is ever reached."""
    session = auth_session.current_session()
    ctx = auth_session.current_auth_context()
    return session["access_token"], ctx.organization_id


def _ensure_list(val):
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
        return [v.strip() for v in val.split("\n") if v.strip()]
    return []


def page_decide(bid_id: int):
    _token, _org_id = _current_access_token_and_org()
    bid = tenancy.get_bid_authenticated(_token, bid_id)
    if not bid:
        st.error("Opportunity not found.")
        return

    reqs = tenancy.get_requirements_authenticated(_token, bid_id)
    clars = tenancy.get_clarifications_authenticated(_token, bid_id)
    latest_decision = tenancy.get_bid_decision_authenticated(_token, bid_id)
    firm_profile = tenancy.get_firm_profile_authenticated(_token, _org_id)
    brief_row = tenancy.get_bid_brief_authenticated(_token, bid_id) or {}

    st.markdown('<div style="font-size:.72rem;color:#C9A96E;text-transform:uppercase;letter-spacing:.12em;font-weight:600">STAGE 2 · DECIDE</div>', unsafe_allow_html=True)
    c1, c2 = st.columns([3.8, 1.4])
    c1.markdown(f"# Qualification & Bid Decision")
    c1.markdown(f'<div style="font-size:1rem;color:#A9A69D">{bid["client"]} — {bid["title"]}</div>', unsafe_allow_html=True)
    if latest_decision and latest_decision.get("human_decision"):
        c2.markdown(f'<div style="text-align:right;padding-top:.5rem">{decision_badge(latest_decision["human_decision"])}</div>', unsafe_allow_html=True)
    else:
        c2.markdown('<div style="text-align:right;padding-top:.7rem"><span style="background:#111118;border:1px solid #353129;color:#A9A69D;padding:.3rem .7rem;border-radius:4px;font-size:.78rem;font-weight:600">Decision: Not Yet Recorded</span></div>', unsafe_allow_html=True)

    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)

    procurement_state = tenancy.get_procurement_state_for_organization(bid_id, _org_id)
    if latest_decision:
        # A decision exists -- pass its stored basis explicitly, even if
        # that stored value is NULL (a decision made before revision
        # tracking existed), so the banner can distinguish "unknown basis"
        # from "no decision to compare at all".
        banner_html = procurement_staleness_banner(
            procurement_state, latest_decision.get("based_on_procurement_revision"),
            context_label="This bid/no-bid decision",
        )
    else:
        banner_html = procurement_staleness_banner(procurement_state, context_label="This bid/no-bid decision")
    if banner_html:
        st.markdown(banner_html, unsafe_allow_html=True)

    from requirement_semantics import (
        select_qualification_requirements,
        resolve_requirement_type,
        get_qualification_gate_ui_alert,
    )

    qual_gates = _ensure_list(brief_row.get("qualification_gates"))
    qual_reqs = select_qualification_requirements(reqs, qual_gates)

    q_total = len(qual_reqs)
    q_pass = sum(1 for r in qual_reqs if r.get("qual_status") == "PASS")
    q_concern = sum(1 for r in qual_reqs if r.get("qual_status") == "CONCERN")
    q_fail = sum(1 for r in qual_reqs if r.get("qual_status") == "FAIL")
    q_unknown = sum(1 for r in qual_reqs if r.get("qual_status", "UNKNOWN") == "UNKNOWN")

    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(metric_card("Qualification Gates", q_total, f"{q_pass} verified PASS"), unsafe_allow_html=True)
    k2.markdown(metric_card("Verified PASS", q_pass, f"{round(q_pass/q_total*100) if q_total else 0}% verified"), unsafe_allow_html=True)
    k3.markdown(metric_card("Concerns / Risks", q_concern, "need resolution", "#E67E22" if q_concern else "#27AE60"), unsafe_allow_html=True)
    k4.markdown(metric_card("Blockers (FAIL / UNKNOWN)", f"{q_fail}F / {q_unknown}U", "prevent qualification", "#C0392B" if (q_fail or q_unknown) else "#27AE60"), unsafe_allow_html=True)
    st.markdown("")

    # Qualification gate status warning / zero-state alert
    alert_info = get_qualification_gate_ui_alert(q_total, q_fail, q_unknown)
    st.markdown(alert_info["html"], unsafe_allow_html=True)

    st.markdown("")

    tab_qual, tab_clars, tab_decision = st.tabs([
        "🛡️ Requirement Assessment Matrix",
        "❓ Strategic Clarifications",
        "🎯 Bid / No-Bid Decision Console"
    ])

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 1: REQUIREMENT ASSESSMENT MATRIX
    # ══════════════════════════════════════════════════════════════════════════
    with tab_qual:
        st.markdown("### Requirement Assessment Matrix: Compliance & Evidence")
        st.markdown(
            '<div style="font-size:.82rem;color:#A9A69D;margin-bottom:.8rem">'
            'Assess each mandatory and scored requirement against verified corporate evidence. '
            'Assign clear compliance statuses: <code>PASS</code>, <code>CONCERN</code>, <code>FAIL</code>, or <code>UNKNOWN</code>.'
            '</div>',
            unsafe_allow_html=True
        )

        # Filters
        c_f1, c_f2 = st.columns([2, 2])
        cat_filter = c_f1.selectbox("Filter Category", ["All", "Mandatory", "Rated", "Financial", "Supporting"], key="qm_cat_filter")
        status_filter = c_f2.selectbox("Filter Compliance Status", ["All", "PASS", "CONCERN", "FAIL", "UNKNOWN"], key="qm_stat_filter")

        filtered_reqs = reqs
        if cat_filter != "All":
            filtered_reqs = [r for r in filtered_reqs if r.get("category") == cat_filter]
        if status_filter != "All":
            filtered_reqs = [r for r in filtered_reqs if r.get("qual_status", "UNKNOWN") == status_filter]

        if not filtered_reqs:
            st.markdown('<div class="empty-state">No requirements match the selected filter.</div>', unsafe_allow_html=True)
        else:
            hcols = st.columns([0.7, 1.4, 2.8, 1.2, 1.3, 1.6, 1.5, 0.5])
            for h, hc in zip(["ID", "Category / Type", "Requirement & Ref", "Compliance Status", "Evidence Readiness", "Evidence Details", "Gap / Action", ""], hcols):
                hc.markdown(f'<span style="font-size:.68rem;color:#6E6C66;font-weight:700;text-transform:uppercase">{h}</span>', unsafe_allow_html=True)
            st.markdown('<hr class="section-divider" style="margin:.2rem 0">', unsafe_allow_html=True)

            for req in filtered_reqs:
                c1, c2, c3, c4, c5, c6, c7, c8 = st.columns([0.7, 1.4, 2.8, 1.2, 1.3, 1.6, 1.5, 0.5])
                c1.markdown(f'<span style="font-size:.82rem;color:#C9A96E;font-weight:700">{req.get("req_id","—")}</span>', unsafe_allow_html=True)
                sem_type = req.get("requirement_type") or resolve_requirement_type(req)
                c2.markdown(f'<span style="font-size:.78rem;color:#EDEAE3">{req.get("category","")}</span><br><span style="font-size:.70rem;color:#A9A69D">{sem_type}</span>', unsafe_allow_html=True)

                ref_str = f' <span style="font-size:.72rem;color:#6E6C66">[{req.get("rfso_ref","")}]</span>' if req.get("rfso_ref") else ""
                c3.markdown(f'<div style="font-size:.82rem">{req.get("description","")}{ref_str}</div>', unsafe_allow_html=True)

                current_q = req.get("qual_status", "UNKNOWN")
                c4.markdown(qual_badge(current_q), unsafe_allow_html=True)

                current_e = req.get("evidence_status", "MISSING")
                c5.markdown(evidence_badge(current_e), unsafe_allow_html=True)

                c6.markdown(f'<span style="font-size:.78rem;color:#A9A69D">{req.get("evidence") or "No evidence linked"}</span>', unsafe_allow_html=True)
                c7.markdown(f'<span style="font-size:.78rem;color:#EDEAE3">{req.get("gap_action") or "—"}</span>', unsafe_allow_html=True)

                if c8.button("✏", key=f"eq_{req['id']}", help="Update compliance status & evidence"):
                    st.session_state["editing_qual_id"] = req["id"]
                    st.rerun()

                st.markdown('<hr class="section-divider" style="margin:.15rem 0">', unsafe_allow_html=True)

        # Edit drawer
        eid = st.session_state.get("editing_qual_id")
        if eid:
            target_req = next((r for r in reqs if r["id"] == eid), None)
            if target_req:
                st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
                st.markdown(f"### ✏️ Assess Requirement: {target_req.get('req_id','')} — {target_req.get('description','')[:50]}")
                with st.form("edit_qual_form"):
                    c1, c2, c3 = st.columns([1, 1, 1.5])
                    new_qstat = c1.selectbox("Compliance Status *", QUAL_STATUSES,
                                             index=QUAL_STATUSES.index(target_req.get("qual_status", "UNKNOWN"))
                                             if target_req.get("qual_status") in QUAL_STATUSES else 3)
                    new_estat = c2.selectbox("Evidence Readiness *", EVIDENCE_STATUSES,
                                             index=EVIDENCE_STATUSES.index(target_req.get("evidence_status", "MISSING"))
                                             if target_req.get("evidence_status") in EVIDENCE_STATUSES else 2)
                    new_owner = c3.text_input("Assigned Owner", value=target_req.get("owner") or "")
                    new_evidence = st.text_area("Linked Evidence & Compliance Notes", value=target_req.get("evidence") or "", height=70,
                                                placeholder="e.g. Reference projects 2023-2025, ISO certifications, key expert CVs")
                    new_gap = st.text_area("Gap / Remediation Action Required", value=target_req.get("gap_action") or "", height=60,
                                           placeholder="e.g. Obtain client reference confirmation, request partner clearance")
                    new_notes = st.text_area("Internal Notes", value=target_req.get("qual_notes") or target_req.get("notes") or "", height=50)

                    c_save, c_cancel = st.columns([2, 1])
                    if c_save.form_submit_button("Save Assessment", use_container_width=True, type="primary"):
                        tenancy.upsert_requirement_authenticated(_token, {
                            **target_req,
                            "qual_status": new_qstat,
                            "evidence_status": new_estat,
                            "owner": new_owner,
                            "evidence": new_evidence,
                            "gap_action": new_gap,
                            "qual_notes": new_notes,
                        })
                        del st.session_state["editing_qual_id"]
                        st.success("Assessment saved.")
                        st.rerun()
                    if c_cancel.form_submit_button("Cancel", use_container_width=True):
                        del st.session_state["editing_qual_id"]
                        st.rerun()

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 2: STRATEGIC CLARIFICATIONS
    # ══════════════════════════════════════════════════════════════════════════
    with tab_clars:
        st.markdown("### Strategic Clarification Questions")
        clar_dl = days_until(bid.get("clarification_deadline"))
        if clar_dl is not None:
            col = "#C0392B" if clar_dl <= 3 else "#E67E22" if clar_dl <= 7 else "#2471A3"
            st.markdown(
                f'<div style="background:{col}22;border:1px solid {col}55;border-radius:6px;'
                f'padding:.7rem 1.1rem;margin-bottom:.8rem;display:flex;justify-content:space-between;align-items:center">'
                f'<div><span style="color:{col};font-weight:700">Enquiry Deadline: {bid.get("clarification_deadline","")}</span>'
                f'<br><span style="color:#A9A69D;font-size:.76rem">Formal Q&A responses become binding tender addenda for all bidders.</span></div>'
                f'<span style="font-size:1.1rem;font-weight:700;color:{col}">{days_label(clar_dl)}</span></div>',
                unsafe_allow_html=True
            )

        # AI Generator Button & Options
        with st.expander("🤖 AI Clarification Question Generator", expanded=not clars):
            st.markdown(
                '<div style="font-size:.82rem;color:#A9A69D;margin-bottom:.5rem">'
                'Claude analyzes RFP requirements, mandatory thresholds, and your specific commercial concerns '
                'to produce strategic questions formatted for submission.'
                '</div>',
                unsafe_allow_html=True
            )
            c_ctx1, c_ctx2 = st.columns(2)
            extra_rfp = c_ctx1.text_area("RFP ambiguity excerpts (optional)", height=80, key="cq_extra_rfp",
                                         placeholder="Paste ambiguous clause excerpts...")
            firm_conc = c_ctx2.text_area("Bidder internal concerns (internal only)", height=80, key="cq_firm_conc",
                                         placeholder="e.g. Subcontractor arrangements, pricing structure, staffing...")

            if st.button("✨ Generate Strategic Clarification Questions", use_container_width=True, type="primary", key="btn_gen_clars"):
                if not (api_key_configured() or st.session_state.get("anthropic_api_key")):
                    st.error("Please configure your Anthropic API key in Settings or .env.")
                else:
                    with st.spinner("Analyzing RFP ambiguities and formulating strategic questions… 15–25s"):
                        try:
                            cq_res = generate_clarification_questions(bid, reqs, extra_rfp, firm_conc)
                            for q in cq_res.get("questions", []):
                                tenancy.upsert_clarification_authenticated(_token, {
                                    "bid_id": bid_id,
                                    "question_id": q.get("id", ""),
                                    "question": q.get("question", ""),
                                    "rfp_reference": q.get("rfp_reference", ""),
                                    "rationale": q.get("strategic_rationale", ""),
                                    "priority": q.get("priority", "Medium"),
                                    "category": q.get("category", "General"),
                                    "status": "Draft",
                                })
                            st.success(f"Generated {len(cq_res.get('questions',[]))} strategic clarification questions.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Clarification generation failed: {e}")

        # List existing clarifications
        if clars:
            st.markdown(f"#### Logged Clarification Inquiries ({len(clars)})")
            for c_ in clars:
                st.markdown(
                    f'<div style="background:#111118;border:1px solid #292832;border-radius:4px;padding:.6rem 1rem;margin:.3rem 0">'
                    f'<strong>{c_.get("question_id","Q")}</strong>: {c_.get("question","")}'
                    f'<br><span style="font-size:.75rem;color:#A9A69D">Ref: {c_.get("rfp_reference","—")} · Priority: {c_.get("priority","Medium")} · Status: {c_.get("status","Draft")}</span>'
                    f'</div>',
                    unsafe_allow_html=True
                )
        else:
            st.markdown('<div class="empty-state">No clarification questions tracked yet.</div>', unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 3: BID / NO-BID DECISION CONSOLE
    # ══════════════════════════════════════════════════════════════════════════
    with tab_decision:
        st.markdown("### Pursuit Decision Console")
        st.markdown(
            '<div style="font-size:.82rem;color:#A9A69D;margin-bottom:.8rem">'
            'Combine AI multi-dimensional pursuit scoring with accountable executive judgment. '
            'Human commercial judgment remains the ultimate authority. <strong>The AI recommendation never replaces or creates an official human decision.</strong>'
            '</div>',
            unsafe_allow_html=True
        )

        c_dec_run, c_dec_space = st.columns([2, 2])
        if c_dec_run.button("🎯 Run AI Pursuit Evaluation", use_container_width=True, type="primary", key="btn_run_bn"):
            if not (api_key_configured() or st.session_state.get("anthropic_api_key")):
                st.error("Please configure your Anthropic API key.")
            else:
                with st.spinner("Evaluating pursuit viability against firm capabilities… 15–25s"):
                    try:
                        firm_summary = f"{firm_profile.get('company_name','')}: {firm_profile.get('overview','')} Capabilities: {firm_profile.get('core_capabilities','')}"
                        bn_res = bid_no_bid_score(bid, reqs, firm_summary, qualification_requirements=qual_reqs)
                        existing_dec = tenancy.get_bid_decision_authenticated(_token, bid_id)
                        tenancy.save_bid_decision_authenticated(_token, {
                            "bid_id": bid_id,
                            "ai_recommendation": bn_res.get("recommendation", "NEEDS MORE INFORMATION"),
                            "ai_confidence": bn_res.get("confidence", "Medium"),
                            "overall_score": bn_res.get("overall_score", 0),
                            "dimension_scores": bn_res.get("dimensions", {}),
                            "hard_blockers": bn_res.get("hard_blockers", []),
                            "conditions": bn_res.get("conditions", []),
                            "win_themes": bn_res.get("win_themes", []),
                            "red_flags": bn_res.get("red_flags", []),
                            # CRITICAL: Preserve existing human decision if present; DO NOT populate with AI recommendation if null!
                            "human_decision": existing_dec.get("human_decision") if existing_dec else None,
                            "override_reason": existing_dec.get("override_reason", "") if existing_dec else "",
                            "decided_by": existing_dec.get("decided_by") if existing_dec else None,
                            "decided_at": existing_dec.get("decided_at") if existing_dec else None,
                        })
                        st.success("Pursuit evaluation updated. Official human decision remains unchanged.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Evaluation failed: {e}")

        latest_decision = tenancy.get_bid_decision_authenticated(_token, bid_id)
        if latest_decision and (latest_decision.get("ai_recommendation") or latest_decision.get("overall_score")):
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            ai_rec = latest_decision.get("ai_recommendation") or "NEEDS MORE INFORMATION"
            score = latest_decision.get("overall_score") or 0

            c_rec1, c_rec2 = st.columns([1.2, 3])
            c_rec1.markdown(
                f'<div style="text-align:center;background:#111118;border:2px solid #C9A96E;border-radius:6px;padding:1.1rem">'
                f'<div style="font-size:.72rem;color:#A9A69D;text-transform:uppercase">AI Recommendation</div>'
                f'<div style="margin:.4rem 0">{decision_badge(ai_rec)}</div>'
                f'<div style="font-size:1.8rem;font-weight:700;color:#EDEAE3">{score:.0f}</div>'
                f'<div style="font-size:.68rem;color:#6E6C66">Confidence: {latest_decision.get("ai_confidence","Medium")}</div>'
                f'</div>',
                unsafe_allow_html=True
            )

            with c_rec2:
                conditions = _ensure_list(latest_decision.get("conditions"))
                blockers = _ensure_list(latest_decision.get("hard_blockers"))
                win_themes = _ensure_list(latest_decision.get("win_themes"))
                red_flags = _ensure_list(latest_decision.get("red_flags"))

                if blockers:
                    for b_ in blockers:
                        st.markdown(f'<div class="warn-box">⛔ <strong>Hard Blocker:</strong> {b_}</div>', unsafe_allow_html=True)
                if conditions:
                    for c_ in conditions:
                        st.markdown(f'<div style="background:#1A0F00;border-left:3px solid #E67E22;padding:.4rem .8rem;margin:.2rem 0;font-size:.82rem;color:#EDEAE3">⚡ <strong>Condition:</strong> {c_}</div>', unsafe_allow_html=True)
                if win_themes:
                    st.markdown("**Key Win Themes:** " + " · ".join(f"<span style='color:#27AE60'>✓ {wt}</span>" for wt in win_themes), unsafe_allow_html=True)

            # Accountable Human Decision Override
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            st.markdown("### ✍️ Record Official Pursuit Decision (Human Accountable)")
            
            human_dec_recorded = latest_decision.get("human_decision")
            if not human_dec_recorded:
                st.markdown('<div class="info-box">ℹ️ <strong>No Official Human Decision Recorded Yet.</strong> Select an option below and submit to record the binding executive pursuit decision.</div>', unsafe_allow_html=True)
            
            with st.form("human_decision_form"):
                c_h1, c_h2 = st.columns([1.5, 2.5])
                current_h = human_dec_recorded or "GO"
                options = ["GO", "GO WITH CONDITIONS", "NO-GO", "NEEDS MORE INFORMATION"]
                chosen_h = c_h1.selectbox("Official Decision *", options, index=options.index(current_h) if current_h in options else 0)
                decided_by = c_h2.text_input("Decided By (Proposal Lead / Executive) *", value=latest_decision.get("decided_by") or bid.get("owner") or "")
                override_notes = st.text_area("Decision Rationale & Commercial Justification", value=latest_decision.get("override_reason") or "", height=80,
                                              placeholder="Document rationale, risk tolerance, and conditions agreed by executive leadership...")

                if st.form_submit_button("Confirm & Save Official Decision", use_container_width=True, type="primary"):
                    tenancy.save_bid_decision_authenticated(_token, {
                        **latest_decision,
                        "human_decision": chosen_h,
                        "override_reason": override_notes,
                        "decided_by": decided_by,
                        "decided_at": datetime.now().isoformat(),
                    })
                    # Update bid stage if NO-GO
                    if chosen_h == "NO-GO":
                        tenancy.update_bid_authenticated(_token, bid_id, {**bid, "stage": "No Bid"})
                    elif chosen_h in ("GO", "GO WITH CONDITIONS") and bid.get("stage") in ("Identified", "Qualifying"):
                        tenancy.update_bid_authenticated(_token, bid_id, {**bid, "stage": "In Progress"})
                    st.success("Official pursuit decision recorded.")
                    st.rerun()

    # ── NEXT STAGE CTA ────────────────────────────────────────────────────────
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    c1, c2 = st.columns([3, 1])
    c1.markdown('<div style="color:#A9A69D;font-size:.85rem;padding-top:.4rem">Qualified to proceed? Advance to proposal construction.</div>', unsafe_allow_html=True)
    if c2.button("Proceed to BUILD →", use_container_width=True, type="primary"):
        st.session_state.page = "stage_build"
        st.rerun()
