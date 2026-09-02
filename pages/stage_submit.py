"""
Stage 5: SUBMIT — Submission Control
Final gatekeeper ensuring zero-defect package assembly:
1. Final Gate Status: READY TO SUBMIT / READY WITH WARNINGS / NOT READY
2. Critical Deadline Watch & Submission Portal
3. Dynamic RFP-Derived Submission Package Checklist
4. File Verification & Upload Status
5. Formal "Mark as Submitted" Action (unlocks Debrief)
"""
from datetime import datetime
import streamlit as st
from database import (get_bid, get_requirements, get_documents, get_outline,
                      update_bid, save_upload)
from analyst import submission_readiness_check
from config import api_key_configured
from components.ui import (days_until, days_label, status_badge,
                           metric_card)


def page_submit(bid_id: int):
    bid = get_bid(bid_id)
    if not bid:
        st.error("Opportunity not found.")
        return

    reqs = get_requirements(bid_id)
    docs = get_documents(bid_id)
    outline = get_outline(bid_id)

    st.markdown('<div style="font-size:.72rem;color:#C9A96E;text-transform:uppercase;letter-spacing:.12em;font-weight:600">STAGE 5 · SUBMIT</div>', unsafe_allow_html=True)
    st.markdown(f"# Submission Control")
    st.markdown(f'<div style="font-size:1rem;color:#A9A69D">{bid["client"]} — {bid["title"]}</div>', unsafe_allow_html=True)
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)

    # ── READINESS STATUS EVALUATION ───────────────────────────────────────────
    READY_DOC_STATUSES = {"Uploaded", "Approved", "Complete", "Submitted"}
    # Submission document mandatory semantics:
    #   mandatory == 1/True  -> REQUIRED
    #   mandatory == 0/False -> OPTIONAL
    #   mandatory absent/None -> UNKNOWN (requires human resolution)
    sub_docs = [d for d in docs if d.get("doc_type") in ("Submission", "Financial")]
    required_sub_docs  = [d for d in sub_docs if d.get("mandatory") in (1, True, "1", "true")]
    unknown_mand_docs  = [d for d in sub_docs if d.get("mandatory") is None]
    docs_missing = sum(1 for d in required_sub_docs if d.get("status") not in READY_DOC_STATUSES)

    mand_reqs = [r for r in reqs if r.get("category") == "Mandatory"]
    m_fail = sum(1 for r in mand_reqs if r.get("qual_status") == "FAIL")
    m_unknown = sum(1 for r in mand_reqs if r.get("qual_status", "UNKNOWN") == "UNKNOWN")
    docs_unknown_mand = len(unknown_mand_docs)

    sub_dl = days_until(bid.get("submission_deadline"))

    if m_fail > 0 or docs_missing > 0:
        gate_status = "NOT READY \u2014 BLOCKERS EXIST"
        gate_col = "#C0392B"
    elif m_unknown > 0 or docs_unknown_mand > 0:
        gate_status = "READY WITH WARNINGS (Unverified Gates)"
        gate_col = "#E67E22"
    else:
        gate_status = "READY TO SUBMIT"
        gate_col = "#27AE60"

    c_g1, c_g2 = st.columns([2.5, 1.5])
    c_g1.markdown(
        f'<div style="background:#111118;border:2px solid {gate_col};border-radius:6px;padding:1.1rem 1.5rem">'
        f'<div style="font-size:.72rem;color:#A9A69D;text-transform:uppercase">Final Gate Status</div>'
        f'<div style="font-size:1.5rem;font-weight:700;color:{gate_col};margin:.2rem 0">{gate_status}</div>'
        f'<div style="font-size:.8rem;color:#EDEAE3">{len(required_sub_docs)-docs_missing}/{len(required_sub_docs)} required submission files ready'
        f'{" · " + str(docs_unknown_mand) + " unknown mandatory status" if docs_unknown_mand else ""}'
        f' · {m_fail} blockers</div>'
        f'</div>',
        unsafe_allow_html=True
    )

    with c_g2:
        st.markdown(metric_card("Submission Deadline", bid.get("submission_deadline") or "\u2014", days_label(sub_dl)), unsafe_allow_html=True)
    st.markdown("")

    # ── SUBMISSION PACKAGE CHECKLIST ──────────────────────────────────────────
    st.markdown("### \U0001f4e6 Dynamic Submission Package Checklist")
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
                mand_tag = '<span style="color:#E67E22;font-size:.72rem">[UNKNOWN \u2014 review status]</span>'
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;align-items:center;background:#111118;'
                f'border:1px solid #292832;border-radius:4px;padding:.6rem 1rem;margin:.3rem 0">'
                f'<div>\U0001f4c4 <strong>{doc["name"]}</strong> {mand_tag} <span style="font-size:.75rem;color:#A9A69D">[{doc.get("doc_type","")}]</span>'
                f'{"<div style=font-size:.74rem;color:#6E6C66>" + doc.get("notes","") + "</div>" if doc.get("notes") else ""}'
                f'</div>'
                f'<span>{status_badge(doc.get("status","Expected"))}</span>'
                f'</div>',
                unsafe_allow_html=True
            )
    else:
        st.markdown('<div class="info-box">No explicit submission documents were identified in the procurement package. Upload submission files below or add them manually.</div>', unsafe_allow_html=True)

    with st.expander("➕ Upload / Add Submission Package File"):
        up_file = st.file_uploader("Upload finalized submission document (PDF, DOCX, XLSX, CSV, TXT, ZIP)", type=["pdf", "docx", "xlsx", "csv", "txt", "zip"], key="sub_pkg_file")
        if up_file:
            up_key = f"uploaded_sub_{bid_id}_{up_file.name}_{up_file.size}"
            if not st.session_state.get(up_key):
                save_upload(bid_id, up_file.name, up_file.read(), doc_type="Submission")
                st.session_state[up_key] = True
                st.success(f"Added {up_file.name} to submission package.")
                st.rerun()

    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

    # ── PRE-SUBMISSION VERIFICATION GATES (HUMAN ATTESTATIONS DEFAULT FALSE) ─
    st.markdown("### 🛡️ Final Gate Verifications")
    chk1 = st.checkbox("Technical and Financial proposals formatted and separated according to RFP instructions", value=False)
    chk2 = st.checkbox("All mandatory qualification criteria verified with PASS status", value=False)
    chk3 = st.checkbox("All formal tender addenda and Q&A bulletins acknowledged", value=False)
    chk4 = st.checkbox("Authorized executive sign-off confirmed", value=False)

    # ── CRITICAL BLOCKER AGGREGATION ──────────────────────────────────────────
    critical_blockers = []
    if m_fail > 0:
        critical_blockers.append(f"{m_fail} Mandatory Qualification Gate(s) marked as FAIL")
    if m_unknown > 0:
        critical_blockers.append(f"{m_unknown} Mandatory Qualification Gate(s) remain UNKNOWN (Unverified)")
    if docs_missing > 0:
        critical_blockers.append(f"{docs_missing} Required Submission Document(s) missing or not uploaded")
    if not chk1:
        critical_blockers.append("Technical/Financial proposal separation verification unchecked")
    if not chk2:
        critical_blockers.append("Mandatory qualification criteria confirmation unchecked")
    if not chk3:
        critical_blockers.append("Tender addenda & bulletins acknowledgement unchecked")
    if not chk4:
        critical_blockers.append("Executive sign-off confirmation unchecked")

    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

    # ── FORMAL SUBMISSION ACTION ──────────────────────────────────────────────
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
        if critical_blockers:
            st.markdown(
                f'<div class="warn-box" style="border-left:4px solid #C0392B">'
                f'⛔ <strong>SUBMISSION BLOCKED:</strong> The following {len(critical_blockers)} critical issue(s) prevent official submission:'
                f'<ul style="margin-top:.4rem;margin-bottom:0;padding-left:1.2rem">'
                + "".join(f"<li>{cb}</li>" for cb in critical_blockers) +
                f'</ul>'
                f'<div style="font-size:.78rem;color:#A9A69D;margin-top:.5rem">All mandatory blockers, missing documents, and verifications must be satisfied before submission can be executed.</div>'
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
                update_bid(bid_id, {
                    **bid,
                    "stage": "Submitted"
                })
                st.success("Bid officially marked as Submitted!")
                st.session_state.page = "stage_debrief"
                st.rerun()
