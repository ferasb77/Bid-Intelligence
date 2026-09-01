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
from database import (get_bid, get_requirements, upsert_requirement,
                      get_clarifications, upsert_clarification, delete_clarification,
                      get_bid_decision, save_bid_decision, get_firm_profile,
                      update_bid)
from analyst import generate_clarification_questions, bid_no_bid_score
from config import api_key_configured
from components.ui import (qual_badge, decision_badge, days_until, days_label,
                           metric_card, QUAL_STATUSES, CATEGORIES)


def page_decide(bid_id: int):
    bid = get_bid(bid_id)
    if not bid:
        st.error("Opportunity not found.")
        return

    reqs = get_requirements(bid_id)
    clars = get_clarifications(bid_id)
    latest_decision = get_bid_decision(bid_id)
    firm_profile = get_firm_profile()

    st.markdown('<div style="font-size:.72rem;color:#C9A96E;text-transform:uppercase;letter-spacing:.12em;font-weight:600">STAGE 2 · DECIDE</div>', unsafe_allow_html=True)
    c1, c2 = st.columns([4, 1.2])
    c1.markdown(f"# Qualification & Bid Decision")
    c1.markdown(f'<div style="font-size:1rem;color:#A9A69D">{bid["client"]} — {bid["title"]}</div>', unsafe_allow_html=True)
    if latest_decision and latest_decision.get("human_decision"):
        c2.markdown(f'<div style="text-align:right;padding-top:.5rem">{decision_badge(latest_decision["human_decision"])}</div>', unsafe_allow_html=True)

    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)

    # ── QUALIFICATION STATUS COUNTS & HARD-GATE ALERT ─────────────────────────
    mandatory_reqs = [r for r in reqs if r.get("category") == "Mandatory"]
    m_pass = sum(1 for r in mandatory_reqs if r.get("qual_status") == "PASS")
    m_concern = sum(1 for r in mandatory_reqs if r.get("qual_status") == "CONCERN")
    m_fail = sum(1 for r in mandatory_reqs if r.get("qual_status") == "FAIL")
    m_unknown = sum(1 for r in mandatory_reqs if r.get("qual_status", "UNKNOWN") == "UNKNOWN")

    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(metric_card("Mandatory Gates", len(mandatory_reqs), f"{m_pass} verified PASS"), unsafe_allow_html=True)
    k2.markdown(metric_card("Verified PASS", m_pass, f"{round(m_pass/len(mandatory_reqs)*100) if mandatory_reqs else 0}% verified"), unsafe_allow_html=True)
    k3.markdown(metric_card("Concerns / Risks", m_concern, "need resolution", "#E67E22" if m_concern else "#27AE60"), unsafe_allow_html=True)
    k4.markdown(metric_card("Blockers (FAIL / UNKNOWN)", f"{m_fail}F / {m_unknown}U", "prevent qualification", "#C0392B" if (m_fail or m_unknown) else "#27AE60"), unsafe_allow_html=True)
    st.markdown("")

    # Hard-gate blocker warning
    if m_fail > 0:
        st.markdown(
            f'<div class="warn-box">'
            f'⛔ <strong>DISQUALIFICATION RISK:</strong> {m_fail} mandatory requirement(s) are currently marked as <strong>FAIL</strong>. '
            f'Submitting without resolving these hard gates will result in formal rejection.'
            f'</div>',
            unsafe_allow_html=True
        )
    elif m_unknown > 0:
        st.markdown(
            f'<div class="info-box">'
            f'⚠️ <strong>UNVERIFIED QUALIFICATION GATES:</strong> {m_unknown} mandatory requirement(s) have status <strong>UNKNOWN</strong>. '
            f'The system does not assume compliance without evidence. Verify qualifying credentials before committing to bid.'
            f'</div>',
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            '<div class="success-box">'
            '✅ <strong>ALL MANDATORY GATES VERIFIED:</strong> All mandatory eligibility criteria are confirmed with PASS status.'
            '</div>',
            unsafe_allow_html=True
        )

    st.markdown("")

    tab_qual, tab_clars, tab_decision = st.tabs([
        "🛡️ Hard-Gate Qualification Matrix",
        "❓ Strategic Clarifications",
        "🎯 Bid / No-Bid Decision Console"
    ])

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 1: QUALIFICATION MATRIX
    # ══════════════════════════════════════════════════════════════════════════
    with tab_qual:
        st.markdown("### Qualification Matrix: Hard Gates vs Evidence")
        st.markdown(
            '<div style="font-size:.82rem;color:#A9A69D;margin-bottom:.8rem">'
            'Assess each mandatory and scored requirement against verified corporate evidence. '
            'Assign clear qualification statuses: <code>PASS</code>, <code>CONCERN</code>, <code>FAIL</code>, or <code>UNKNOWN</code>.'
            '</div>',
            unsafe_allow_html=True
        )

        # Filters
        c_f1, c_f2 = st.columns([2, 2])
        cat_filter = c_f1.selectbox("Filter Category", ["All", "Mandatory", "Rated", "Financial", "Supporting"], key="qm_cat_filter")
        status_filter = c_f2.selectbox("Filter Qualification Status", ["All", "PASS", "CONCERN", "FAIL", "UNKNOWN"], key="qm_stat_filter")

        filtered_reqs = reqs
        if cat_filter != "All":
            filtered_reqs = [r for r in filtered_reqs if r.get("category") == cat_filter]
        if status_filter != "All":
            filtered_reqs = [r for r in filtered_reqs if r.get("qual_status", "UNKNOWN") == status_filter]

        if not filtered_reqs:
            st.markdown('<div class="empty-state">No requirements match the selected filter.</div>', unsafe_allow_html=True)
        else:
            hcols = st.columns([0.8, 0.9, 3.2, 1.3, 1.8, 1.6, 0.6])
            for h, hc in zip(["ID", "Category", "Requirement & Ref", "Our Status", "Evidence / Capability", "Gap / Action", ""], hcols):
                hc.markdown(f'<span style="font-size:.68rem;color:#6E6C66;font-weight:700;text-transform:uppercase">{h}</span>', unsafe_allow_html=True)
            st.markdown('<hr class="section-divider" style="margin:.2rem 0">', unsafe_allow_html=True)

            for req in filtered_reqs:
                c1, c2, c3, c4, c5, c6, c7 = st.columns([0.8, 0.9, 3.2, 1.3, 1.8, 1.6, 0.6])
                c1.markdown(f'<span style="font-size:.82rem;color:#C9A96E;font-weight:700">{req.get("req_id","—")}</span>', unsafe_allow_html=True)
                c2.markdown(f'<span style="font-size:.78rem;color:#A9A69D">{req.get("category","")}</span>', unsafe_allow_html=True)

                ref_str = f' <span style="font-size:.72rem;color:#6E6C66">[{req.get("rfso_ref","")}]</span>' if req.get("rfso_ref") else ""
                c3.markdown(f'<div style="font-size:.82rem">{req.get("description","")}{ref_str}</div>', unsafe_allow_html=True)

                current_q = req.get("qual_status", "UNKNOWN")
                c4.markdown(qual_badge(current_q), unsafe_allow_html=True)

                c5.markdown(f'<span style="font-size:.78rem;color:#A9A69D">{req.get("evidence") or "No evidence linked"}</span>', unsafe_allow_html=True)
                c6.markdown(f'<span style="font-size:.78rem;color:#EDEAE3">{req.get("gap_action") or "—"}</span>', unsafe_allow_html=True)

                if c7.button("✏", key=f"eq_{req['id']}", help="Update qualification status & evidence"):
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
                    c1, c2 = st.columns([1, 2])
                    new_qstat = c1.selectbox("Qualification Status *", QUAL_STATUSES,
                                             index=QUAL_STATUSES.index(target_req.get("qual_status", "UNKNOWN"))
                                             if target_req.get("qual_status") in QUAL_STATUSES else 3)
                    new_owner = c2.text_input("Assigned Owner", value=target_req.get("owner") or "")
                    new_evidence = st.text_area("Linked Evidence & Qualifications", value=target_req.get("evidence") or "", height=70,
                                                placeholder="e.g. Reference projects 2023-2025, ISO certifications, key expert CVs")
                    new_gap = st.text_area("Gap / Remediation Action Required", value=target_req.get("gap_action") or "", height=60,
                                           placeholder="e.g. Obtain client reference confirmation, request partner clearance")
                    new_notes = st.text_area("Internal Notes", value=target_req.get("qual_notes") or target_req.get("notes") or "", height=50)

                    c_save, c_cancel = st.columns([2, 1])
                    if c_save.form_submit_button("Save Assessment", use_container_width=True, type="primary"):
                        upsert_requirement({
                            **target_req,
                            "qual_status": new_qstat,
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
                                upsert_clarification({
                                    "bid_id": bid_id,
                                    "question_id": q.get("id", ""),
                                    "question": q.get("question", ""),
                                    "rationale": f"{q.get('rationale','')} | Risk: {q.get('risk_if_unanswered','')}",
                                    "priority": q.get("priority", "Medium"),
                                    "linked_req_ids": ", ".join(q.get("relates_to", [])),
                                    "status": "Draft",
                                    "notes": f"Category: {q.get('category','General')}"
                                })
                            st.success(f"Generated and saved {len(cq_res.get('questions', []))} clarification questions.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Generation failed: {e}")

        # List saved questions
        if clars:
            st.markdown(f"#### Clarification Tracker ({len(clars)} questions)")
            for q in clars:
                pri = q.get("priority", "Medium")
                pri_col = {"Critical": "#C0392B", "High": "#E67E22", "Medium": "#C9A96E"}.get(pri, "#6E6C66")
                with st.expander(f"**{q.get('question_id','')}** · {q.get('question','')[:80]}…"):
                    st.markdown(f"**Question:** {q.get('question','')}")
                    if q.get("rationale"):
                        st.markdown(f'<div style="font-size:.78rem;color:#A9A69D;font-style:italic">Internal Rationale: {q["rationale"]}</div>', unsafe_allow_html=True)
                    if q.get("answer"):
                        st.markdown(f'<div class="success-box"><strong>Answer:</strong> {q["answer"]}</div>', unsafe_allow_html=True)

                    c_q1, c_q2 = st.columns([3, 1])
                    new_ans = c_q1.text_input("Record Client Answer", value=q.get("answer") or "", key=f"ans_{q['id']}")
                    if c_q2.button("Save Answer", key=f"save_ans_{q['id']}"):
                        upsert_clarification({**q, "answer": new_ans, "status": "Answered" if new_ans else q.get("status", "Draft")})
                        st.rerun()
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
            'Human commercial judgment remains the ultimate authority.'
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
                        bn_res = bid_no_bid_score(bid, reqs, firm_summary)
                        save_bid_decision({
                            "bid_id": bid_id,
                            "ai_recommendation": bn_res.get("recommendation", "NEEDS MORE INFORMATION"),
                            "ai_confidence": bn_res.get("confidence", "Medium"),
                            "overall_score": bn_res.get("overall_score", 0),
                            "dimension_scores": bn_res.get("dimensions", {}),
                            "hard_blockers": bn_res.get("hard_blockers", []),
                            "conditions": bn_res.get("conditions", []),
                            "win_themes": bn_res.get("win_themes", []),
                            "red_flags": bn_res.get("red_flags", []),
                            "human_decision": latest_decision.get("human_decision") if latest_decision else bn_res.get("recommendation"),
                            "override_reason": latest_decision.get("override_reason") if latest_decision else "",
                            "decided_by": bid.get("owner") or "Bid Lead"
                        })
                        st.success("Pursuit evaluation updated.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Evaluation failed: {e}")

        latest_decision = get_bid_decision(bid_id)
        if latest_decision:
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
            with st.form("human_decision_form"):
                c_h1, c_h2 = st.columns([1.5, 2.5])
                current_h = latest_decision.get("human_decision") or ai_rec
                options = ["GO", "GO WITH CONDITIONS", "NO-GO", "NEEDS MORE INFORMATION"]
                chosen_h = c_h1.selectbox("Official Decision *", options, index=options.index(current_h) if current_h in options else 0)
                decided_by = c_h2.text_input("Decided By (Proposal Lead / Executive)", value=latest_decision.get("decided_by") or bid.get("owner") or "")
                override_notes = st.text_area("Decision Rationale & Commercial Justification", value=latest_decision.get("override_reason") or "", height=80,
                                              placeholder="Document rationale, risk tolerance, and conditions agreed by executive leadership...")

                if st.form_submit_button("Confirm & Save Official Decision", use_container_width=True, type="primary"):
                    save_bid_decision({
                        **latest_decision,
                        "human_decision": chosen_h,
                        "override_reason": override_notes,
                        "decided_by": decided_by,
                    })
                    # Update bid stage if NO-GO
                    if chosen_h == "NO-GO":
                        update_bid(bid_id, {**bid, "stage": "No Bid"})
                    elif chosen_h in ("GO", "GO WITH CONDITIONS") and bid.get("stage") in ("Identified", "Qualifying"):
                        update_bid(bid_id, {**bid, "stage": "In Progress"})
                    st.success("Official pursuit decision recorded.")
                    st.rerun()

    # ── NEXT STAGE CTA ────────────────────────────────────────────────────────
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    c1, c2 = st.columns([3, 1])
    c1.markdown('<div style="color:#A9A69D;font-size:.85rem;padding-top:.4rem">Qualified to proceed? Advance to proposal construction.</div>', unsafe_allow_html=True)
    if c2.button("Proceed to BUILD →", use_container_width=True, type="primary"):
        st.session_state.page = "stage_build"
        st.rerun()
