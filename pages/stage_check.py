"""
Stage 4: CHECK — Bid Review & Compliance Audit
Consolidated quality gate answering:
1. Are we compliant?
2. Are we competitive?
3. Are we complete?
4. What could cause disqualification?
5. What is still weak or missing?
"""
import io
import streamlit as st
from database import (get_bid, get_requirements, upsert_requirement,
                      get_documents, get_outline, get_clarifications,
                      download_file)
from analyst import (analyze_proposal_alignment, missing_evidence,
                     compliance_review)
from extractor import extract_text_from_file
from config import api_key_configured
from components.ui import (qual_badge, status_badge, readiness_bar,
                           metric_card, QUAL_STATUSES)


def page_check(bid_id: int):
    bid = get_bid(bid_id)
    if not bid:
        st.error("Opportunity not found.")
        return

    reqs = get_requirements(bid_id)
    docs = get_documents(bid_id)
    outline = get_outline(bid_id)
    clars = get_clarifications(bid_id)

    st.markdown('<div style="font-size:.72rem;color:#C9A96E;text-transform:uppercase;letter-spacing:.12em;font-weight:600">STAGE 4 · CHECK</div>', unsafe_allow_html=True)
    st.markdown(f"# Bid Review & Quality Gate")
    st.markdown(f'<div style="font-size:1rem;color:#A9A69D">{bid["client"]} — {bid["title"]}</div>', unsafe_allow_html=True)
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)

    # ── READINESS SCORE STRIP ─────────────────────────────────────────────────
    mand_reqs = [r for r in reqs if r.get("category") == "Mandatory"]
    m_pass = sum(1 for r in mand_reqs if r.get("qual_status") == "PASS")
    m_fail = sum(1 for r in mand_reqs if r.get("qual_status") == "FAIL")
    m_unknown = sum(1 for r in mand_reqs if r.get("qual_status", "UNKNOWN") == "UNKNOWN")

    readiness_pct = (m_pass / len(mand_reqs) * 100) if mand_reqs else 100

    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(metric_card("Mandatory Coverage", f"{m_pass}/{len(mand_reqs)}", f"{readiness_pct:.0f}% verified"), unsafe_allow_html=True)
    k2.markdown(metric_card("Hard Blockers (FAIL)", m_fail, "critical", "#C0392B" if m_fail else "#27AE60"), unsafe_allow_html=True)
    k3.markdown(metric_card("Unverified Gates", m_unknown, "needs proof", "#E67E22" if m_unknown else "#27AE60"), unsafe_allow_html=True)
    k4.markdown(metric_card("Draft Outline Done", f"{sum(1 for s in outline if s.get('status')=='Complete')}/{len(outline)}", "sections"), unsafe_allow_html=True)
    st.markdown("")

    tab_alignment, tab_risk, tab_matrix, tab_clar_audit = st.tabs([
        "🔬 Proposal Alignment Analyzer",
        "🛡️ Compliance & Evidence Risk Scan",
        "📋 Full Compliance Matrix Sheet",
        "❓ Clarification & Addenda Audit"
    ])

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 1: PROPOSAL ALIGNMENT ANALYZER
    # ══════════════════════════════════════════════════════════════════════════
    with tab_alignment:
        st.markdown("### Proposal Alignment & Tender Document Audit")
        st.markdown(
            '<div style="font-size:.82rem;color:#A9A69D;margin-bottom:.8rem">'
            'Upload a draft or final proposal document (PDF / Word / Text). Claude audits it against tender documents '
            'and compliance criteria, classifying findings into Proposal Submission, Negotiation, Execution, or Delivery stages.'
            '</div>',
            unsafe_allow_html=True
        )

        c_up1, c_up2 = st.columns([2, 1])
        prop_file = c_up1.file_uploader("Upload draft or final proposal (PDF, DOCX, TXT)", type=["pdf", "docx", "txt", "doc"], key="prop_align_file")
        proposal_text = ""
        if prop_file:
            proposal_text = extract_text_from_file(prop_file.read(), prop_file.name)
            st.info(f"Loaded proposal text: {len(proposal_text):,} characters.")

        if c_up2.button("🚀 Run Alignment Audit", use_container_width=True, type="primary", key="btn_run_align"):
            if not proposal_text:
                st.error("Please upload a proposal file first.")
            elif not (api_key_configured() or st.session_state.get("anthropic_api_key")):
                st.error("Configure Anthropic API key.")
            else:
                with st.spinner("Analyzing proposal alignment against tender criteria… 20–35s"):
                    try:
                        align_res = analyze_proposal_alignment(
                            proposal_text=proposal_text,
                            requirements=reqs,
                            rfp_text=bid.get("notes", ""),
                            bid_info=bid
                        )
                        st.session_state["align_result"] = align_res
                        st.success("Audit complete.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Audit failed: {e}")

        # Display alignment results
        align_data = st.session_state.get("align_result")
        if align_data:
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            o_score = align_data.get("overall_score", 0)
            rec = align_data.get("recommendation", "REVISE")
            rec_col = "#27AE60" if "SUBMIT" in rec else "#E67E22" if "REVISE" in rec else "#C0392B"

            c_sc1, c_sc2 = st.columns([1, 3])
            c_sc1.markdown(
                f'<div style="text-align:center;background:#111118;border:2px solid {rec_col};border-radius:6px;padding:1rem">'
                f'<div style="font-size:.7rem;color:#A9A69D;text-transform:uppercase">Alignment Score</div>'
                f'<div style="font-size:2.2rem;font-weight:700;color:{rec_col}">{o_score}/100</div>'
                f'<div style="font-size:.8rem;color:#EDEAE3;font-weight:600;margin-top:.3rem">{rec}</div>'
                f'</div>',
                unsafe_allow_html=True
            )
            with c_sc2:
                st.markdown(f"**Executive Summary:** {align_data.get('executive_summary','')}")
                strengths = align_data.get("strengths", [])
                if strengths:
                    st.markdown("**Identified Strengths:** " + " · ".join(f"<span style='color:#27AE60'>✓ {s}</span>" for s in strengths), unsafe_allow_html=True)

            # Findings grouped by stage
            findings = align_data.get("findings", [])
            if findings:
                st.markdown(f"#### Audit Findings ({len(findings)} items)")
                for f in findings:
                    sev = f.get("severity", "Medium")
                    stage = f.get("stage", "Proposal Submission")
                    sev_col = "#C0392B" if sev == "Critical" else "#E67E22" if sev == "High" else "#2980B9"
                    st.markdown(
                        f'<div style="background:#111118;border:1px solid #292832;border-left:3px solid {sev_col};'
                        f'border-radius:0 4px 4px 0;padding:.6rem 1rem;margin:.35rem 0">'
                        f'<span style="color:{sev_col};font-weight:700;font-size:.72rem">[{sev.upper()}]</span> '
                        f'<span style="color:#C9A96E;font-size:.72rem">Stage: {stage}</span> '
                        f'<strong>{f.get("title","")}</strong>'
                        f'<div style="font-size:.8rem;color:#EDEAE3;margin-top:.2rem">{f.get("issue","")}</div>'
                        f'<div style="font-size:.76rem;color:#27AE60;margin-top:.2rem">💡 Action: {f.get("recommendation","")}</div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 2: MISSING EVIDENCE SCAN
    # ══════════════════════════════════════════════════════════════════════════
    with tab_risk:
        st.markdown("### Compliance & Evidence Risk Scan")
        if st.button("🔍 Scan Compliance Matrix for At-Risk Items", key="btn_scan_ev", type="primary"):
            if not (api_key_configured() or st.session_state.get("anthropic_api_key")):
                st.error("Configure Anthropic API key.")
            else:
                with st.spinner("Scanning requirement matrix…"):
                    try:
                        ev_res = missing_evidence(reqs, bid)
                        st.session_state["evidence_scan"] = ev_res
                        st.rerun()
                    except Exception as e:
                        st.error(f"Scan failed: {e}")

        ev_data = st.session_state.get("evidence_scan")
        if ev_data:
            st.markdown(f"**Risk Assessment:** {ev_data.get('summary','')}")
            crit = ev_data.get("critical", [])
            if crit:
                for c_ in crit:
                    st.markdown(
                        f'<div class="warn-box">'
                        f'⛔ <strong>[{c_.get("req_id","")}] Critical Risk:</strong> {c_.get("reason","")}'
                        f'<br><strong>Action:</strong> {c_.get("action","")} (by {c_.get("by_when","ASAP")})'
                        f'</div>',
                        unsafe_allow_html=True
                    )

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 3: FULL COMPLIANCE MATRIX SHEET
    # ══════════════════════════════════════════════════════════════════════════
    with tab_matrix:
        st.markdown("### Compliance Matrix Control Sheet")
        c_m1, c_m2 = st.columns([3, 1])
        c_m1.markdown(f"Total requirements tracked: **{len(reqs)}**")

        # PDF Export
        from pdf_export import generate_compliance_pdf
        pdf_buf = generate_compliance_pdf(bid, reqs)
        c_m2.download_button("📥 Export Matrix PDF", data=pdf_buf.getvalue(), file_name=f"compliance_matrix_{bid_id}.pdf", mime="application/pdf", use_container_width=True)

        for r in reqs:
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;align-items:center;background:#111118;'
                f'border:1px solid #292832;border-radius:4px;padding:.5rem .9rem;margin:.25rem 0">'
                f'<span><strong style="color:#C9A96E">{r.get("req_id","")}</strong> [{r.get("category","")}] {r.get("description","")[:75]}…</span>'
                f'<span>{qual_badge(r.get("qual_status","UNKNOWN"))} {status_badge(r.get("status","Not Started"))}</span>'
                f'</div>',
                unsafe_allow_html=True
            )

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 4: CLARIFICATION & ADDENDA AUDIT
    # ══════════════════════════════════════════════════════════════════════════
    with tab_clar_audit:
        st.markdown("### Clarification & Addenda Audit")
        if clars:
            answered = sum(1 for q in clars if q.get("answer"))
            st.markdown(f"Clarifications Status: **{answered}/{len(clars)} answered**")
            for q in clars:
                st.markdown(f"• **{q.get('question_id','Q')}**: {q.get('question','')} → *{q.get('answer') or 'Awaiting client response'}*")
        else:
            st.markdown('<div class="empty-state">No clarification questions submitted.</div>', unsafe_allow_html=True)

    # ── NEXT STAGE CTA ────────────────────────────────────────────────────────
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    c1, c2 = st.columns([3, 1])
    c1.markdown('<div style="color:#A9A69D;font-size:.85rem;padding-top:.4rem">Checks passed? Proceed to final submission assembly and release.</div>', unsafe_allow_html=True)
    if c2.button("Proceed to SUBMIT →", use_container_width=True, type="primary"):
        st.session_state.page = "stage_submit"
        st.rerun()
