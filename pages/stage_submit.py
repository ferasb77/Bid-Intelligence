"""
Stage 5: SUBMIT — Submission Control
Final gatekeeper ensuring zero-defect package assembly:
1. Final Gate Status: READY TO SUBMIT / READY WITH WARNINGS / NOT READY (authoritative from evaluator)
2. Critical Deadline Watch & Submission Portal
3. Dynamic RFP-Derived Submission Package Checklist & UNKNOWN Document Resolution
4. File Verification & Upload Status
5. Pre-submission Attestations
6. Formal "Mark as Submitted" Action (unlocks Debrief)
"""
from datetime import datetime
import streamlit as st
import auth_session
import tenancy
from analyst import submission_readiness_check
from config import api_key_configured
from components.ui import (days_until, days_label, status_badge,
                           metric_card)
from evaluator import evaluate_submission_state


def _current_access_token_and_org():
    session = auth_session.current_session()
    ctx = auth_session.current_auth_context()
    return session["access_token"], ctx.organization_id


def page_submit(bid_id: int):
    _token, _org_id = _current_access_token_and_org()
    bid = tenancy.get_bid_authenticated(_token, bid_id)
    if not bid:
        st.error("Opportunity not found.")
        return

    reqs = tenancy.get_requirements_authenticated(_token, bid_id)
    docs = tenancy.get_documents_authenticated(_token, bid_id)
    outline = tenancy.get_outline_authenticated(_token, bid_id)

    st.markdown('<div style="font-size:.72rem;color:#C9A96E;text-transform:uppercase;letter-spacing:.12em;font-weight:600">STAGE 5 · SUBMIT</div>', unsafe_allow_html=True)
    st.markdown(f"# Submission Control")
    st.markdown(f'<div style="font-size:1rem;color:#A9A69D">{bid["client"]} — {bid["title"]}</div>', unsafe_allow_html=True)
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)

    # ── SUBMISSION PACKAGE DOCUMENTS ──────────────────────────────────────────
    sub_docs = [d for d in docs if d.get("doc_type") in ("Submission", "Financial")]

    # ── SUBMISSION PACKAGE CHECKLIST & UNKNOWN RESOLUTION ─────────────────────
    st.markdown("### 📦 Dynamic Submission Package Checklist")
    st.markdown(
        '<div style="font-size:.82rem;color:#A9A69D;margin-bottom:.8rem">'
        'Ensure all required submission envelopes, signed forms, and pricing files are uploaded and approved.'
        '</div>',
        unsafe_allow_html=True
    )

    if sub_docs:
        for doc in sub_docs:
            mand_val = doc.get("mandatory")
            if mand_val in (1, True, "1", "true"):
                mand_tag = '<span style="color:#C0392B;font-weight:700;font-size:.72rem">[REQUIRED]</span>'
            elif mand_val in (0, False, "0", "false"):
                mand_tag = '<span style="color:#6E6C66;font-size:.72rem">[OPTIONAL]</span>'
            else:
                mand_tag = '<span style="color:#E67E22;font-size:.72rem">[UNKNOWN — review status]</span>'

            st.markdown(
                f'<div style="display:flex;justify-content:space-between;align-items:center;background:#111118;'
                f'border:1px solid #292832;border-radius:4px;padding:.6rem 1rem;margin:.3rem 0">'
                f'<div>📄 <strong>{doc["name"]}</strong> {mand_tag} <span style="font-size:.75rem;color:#A9A69D">[{doc.get("doc_type","")}]</span>'
                f'{"<div style=font-size:.74rem;color:#6E6C66>" + doc.get("notes","") + "</div>" if doc.get("notes") else ""}'
                f'</div>'
                f'<span>{status_badge(doc.get("status","Expected"))}</span>'
                f'</div>',
                unsafe_allow_html=True
            )

            # Human resolution UI for UNKNOWN submission document mandatory status
            if mand_val is None:
                r_col1, r_col2, r_col3 = st.columns([3, 1, 1])
                r_col1.caption("⚠️ Requirement status not established from source evidence. Please classify:")
                if r_col2.button("Mark Required", key=f"btn_mand_req_{doc.get('id')}", use_container_width=True):
                    tenancy.set_document_mandatory_for_organization(bid_id, _org_id, doc["id"], 1)
                    st.success(f"Classified '{doc['name']}' as Required.")
                    st.rerun()
                if r_col3.button("Mark Optional", key=f"btn_mand_opt_{doc.get('id')}", use_container_width=True):
                    tenancy.set_document_mandatory_for_organization(bid_id, _org_id, doc["id"], 0)
                    st.info(f"Classified '{doc['name']}' as Optional.")
                    st.rerun()
    else:
        st.markdown('<div class="info-box">No explicit submission documents were identified in the procurement package. Upload submission files below or add them manually.</div>', unsafe_allow_html=True)

    with st.expander("➕ Upload / Add Submission Package File"):
        up_file = st.file_uploader("Upload finalized submission document (PDF, DOCX, XLSX, CSV, TXT, ZIP)", type=["pdf", "docx", "xlsx", "csv", "txt", "zip"], key="sub_pkg_file")
        if up_file:
            up_key = f"uploaded_sub_{bid_id}_{up_file.name}_{up_file.size}"
            if not st.session_state.get(up_key):
                tenancy.upload_document_for_organization(bid_id, _org_id, up_file.name, up_file.read(), doc_type="Submission")
                st.session_state[up_key] = True
                st.success(f"Added {up_file.name} to submission package.")
                st.rerun()

    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

    # ── PRE-SUBMISSION VERIFICATION GATES (HUMAN ATTESTATIONS DEFAULT FALSE) ─
    st.markdown("### 🛡️ Final Gate Verifications")
    chk1 = st.checkbox("Technical and Financial proposals formatted and separated according to RFP instructions", value=False, key="chk_att_separation")
    chk2 = st.checkbox("All mandatory qualification criteria verified with PASS status", value=False, key="chk_att_criteria")
    chk3 = st.checkbox("All formal tender addenda and Q&A bulletins acknowledged", value=False, key="chk_att_addenda")
    chk4 = st.checkbox("Authorized executive sign-off confirmed", value=False, key="chk_att_signoff")

    attestations = {
        "proposal_separation": chk1,
        "mandatory_criteria_pass": chk2,
        "addenda_acknowledged": chk3,
        "executive_signoff": chk4,
    }

    # ── AUTHORITATIVE READINESS EVALUATION (SINGLE SOURCE OF TRUTH) ───────────
    eval_res = evaluate_submission_state(reqs, docs, attestations)
    status = eval_res["status"]
    can_submit = eval_res["can_submit"]
    blockers = eval_res["blockers"]
    warnings = eval_res["warnings"]
    counts = eval_res["counts"]

    # ── TOP BANNER RENDERING (DRIVEN BY AUTHORITATIVE EVALUATOR) ──────────────
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    st.markdown("### 🚦 Final Gate Assessment")

    sub_dl = days_until(bid.get("submission_deadline"))

    if status == "NOT_READY":
        gate_status = "NOT READY — BLOCKERS EXIST"
        gate_col = "#C0392B"
    elif status == "READY_WITH_WARNINGS":
        gate_status = "READY WITH WARNINGS"
        gate_col = "#E67E22"
    else:  # READY_TO_SUBMIT
        gate_status = "READY TO SUBMIT"
        gate_col = "#27AE60"

    c_g1, c_g2 = st.columns([2.5, 1.5])
    c_g1.markdown(
        f'<div style="background:#111118;border:2px solid {gate_col};border-radius:6px;padding:1.1rem 1.5rem">'
        f'<div style="font-size:.72rem;color:#A9A69D;text-transform:uppercase">Final Gate Status</div>'
        f'<div style="font-size:1.5rem;font-weight:700;color:{gate_col};margin:.2rem 0">{gate_status}</div>'
        f'<div style="font-size:.8rem;color:#EDEAE3">'
        f'{counts["required_documents_ready"]}/{counts["required_documents"]} required submission files ready'
        f'{" · " + str(counts["unknown_document_mandatory"]) + " unknown mandatory status" if counts["unknown_document_mandatory"] else ""}'
        f'{" · " + str(counts["mandatory_concern"]) + " concern mandatory reqs" if counts.get("mandatory_concern") else ""}'
        f'{" · " + str(counts["mandatory_unknown"]) + " unverified mandatory reqs" if counts["mandatory_unknown"] else ""}'
        f' · {len(blockers)} blocker(s)'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True
    )

    with c_g2:
        st.markdown(metric_card("Submission Deadline", bid.get("submission_deadline") or "—", days_label(sub_dl)), unsafe_allow_html=True)
    st.markdown("")

    # If there are CONCERN mandatory qualification requirements, provide direct guidance to DECIDE
    if counts.get("mandatory_concern", 0) > 0:
        st.warning(
            f"⚠️ {counts['mandatory_concern']} Mandatory Qualification requirement(s) remain CONCERN. "
            "Return to Stage 2 (DECIDE) to resolve them before submission."
        )

    # If there are UNKNOWN mandatory qualification requirements, provide direct guidance to DECIDE
    if counts["mandatory_unknown"] > 0:
        st.warning(
            f"ℹ️ {counts['mandatory_unknown']} Mandatory Qualification requirement(s) remain UNKNOWN. "
            "Please return to Stage 2 (DECIDE) to verify PASS / FAIL qualification status."
        )

    # Display warnings if present and no blockers
    if warnings and not blockers:
        st.markdown(
            f'<div class="warn-box" style="border-left:4px solid #E67E22">'
            f'⚠️ <strong>ADVISORY WARNINGS:</strong> The following {len(warnings)} non-blocking advisory note(s) were identified:'
            f'<ul style="margin-top:.4rem;margin-bottom:0;padding-left:1.2rem">'
            + "".join(f"<li>{w}</li>" for w in warnings) +
            f'</ul>'
            f'</div>',
            unsafe_allow_html=True
        )

    # ── FORMAL SUBMISSION ACTION (DRIVEN BY CAN_SUBMIT) ───────────────────────
    st.markdown("### 🚀 Execute Submission")
    if bid.get("stage") == "Submitted":
        st.markdown(
            '<div class="success-box">'
            '🏆 <strong>PROPOSAL SUBMITTED:</strong> This bid has been marked as officially submitted. '
            'Post-submission Debrief is now active.'
            '</div>',
            unsafe_allow_html=True
        )
        if st.button("View Win / Loss Debrief →", use_container_width=True, type="primary"):
            st.session_state.page = "stage_debrief"
            st.rerun()
    else:
        if not can_submit:
            st.markdown(
                f'<div class="warn-box" style="border-left:4px solid #C0392B">'
                f'⛔ <strong>SUBMISSION BLOCKED:</strong> The following {len(blockers)} critical issue(s) prevent official submission:'
                f'<ul style="margin-top:.4rem;margin-bottom:0;padding-left:1.2rem">'
                + "".join(f"<li>{b}</li>" for b in blockers) +
                f'</ul>'
                f'<div style="font-size:.78rem;color:#A9A69D;margin-top:.5rem">All mandatory blockers, missing documents, unverified gates, and verifications must be satisfied before submission can be executed.</div>'
                f'</div>',
                unsafe_allow_html=True
            )
            st.button("🔒 Submission Blocked (Resolve Gates Above)", disabled=True, use_container_width=True, key="btn_mark_sub_disabled")
        else:
            st.markdown(
                '<div class="success-box">'
                '✅ <strong>ALL GATES CLEARED:</strong> All mandatory requirements are verified, required submission files are uploaded, and final confirmations are checked.'
                '</div>',
                unsafe_allow_html=True
            )
            st.markdown(
                '<div style="font-size:.82rem;color:#A9A69D;margin-bottom:.8rem">'
                'Once you have uploaded or emailed the proposal package through the official procurement portal, '
                'mark this bid as officially submitted to lock proposal status and activate the post-submission debrief.'
                '</div>',
                unsafe_allow_html=True
            )
            if st.button("✅ Mark Bid as Officially Submitted", use_container_width=True, type="primary", key="btn_mark_sub"):
                tenancy.update_bid_authenticated(_token, bid_id, {
                    **bid,
                    "stage": "Submitted"
                })
                st.success("Bid officially marked as Submitted!")
                st.session_state.page = "stage_debrief"
                st.rerun()

    # ── ADVISORY AI COMPLIANCE AUDIT (NON-AUTHORITATIVE) ─────────────────────
    if api_key_configured():
        with st.expander("🤖 Advisory AI Compliance Audit (Optional Quality Review)"):
            st.caption(
                "Notice: This automated check provides advisory quality suggestions only. "
                "It does NOT alter the authoritative gate status, document requirements, or submission blockers."
            )
            if st.button("Run AI Pre-Submission Audit", key="btn_run_ai_readiness"):
                with st.spinner("Analyzing package compliance..."):
                    ai_audit = submission_readiness_check(bid, reqs, docs, outline)
                    if ai_audit:
                        st.json(ai_audit)
