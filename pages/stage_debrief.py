"""
Contextual Post-Submission Debrief
Records procurement outcome, evaluator feedback, scores, and institutional win-loss lessons.
"""
import streamlit as st
from database import get_bid, get_debriefs, upsert_debrief, update_bid
from components.ui import metric_card, stage_badge

DEBRIEF_OUTCOMES = ["Won", "Lost", "Shortlisted", "Withdrawn", "Pending", "Cancelled"]


def page_debrief(bid_id: int):
    bid = get_bid(bid_id)
    if not bid:
        st.error("Opportunity not found.")
        return

    debriefs = get_debriefs(bid_id)

    st.markdown('<div style="font-size:.72rem;color:#C9A96E;text-transform:uppercase;letter-spacing:.12em;font-weight:600">POST-SUBMISSION · DEBRIEF</div>', unsafe_allow_html=True)
    st.markdown(f"# Win / Loss Debrief")
    st.markdown(f'<div style="font-size:1rem;color:#A9A69D">{bid["client"]} — {bid["title"]}</div>', unsafe_allow_html=True)
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)

    st.markdown(
        '<div class="info-box">'
        'Record the official procurement outcome, scoring breakdown, evaluator comments, and competitive intelligence. '
        'Over time, this builds institutional bidding intelligence to optimize pricing, win rates, and capability investments.'
        '</div>',
        unsafe_allow_html=True
    )

    if debriefs:
        d = debriefs[0]
        outcome_col = {"Won": "#27AE60", "Lost": "#C0392B", "Shortlisted": "#2980B9", "Pending": "#C9A96E"}.get(
            d.get("outcome", "Pending"), "#6E6C66"
        )
        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(metric_card("Outcome", d.get("outcome", "Pending"), f"Stage: {bid.get('stage','')}", outcome_col), unsafe_allow_html=True)
        c2.markdown(metric_card("Technical Score", d.get("score_technical") or "—", "out of 100"), unsafe_allow_html=True)
        c3.markdown(metric_card("Financial Score", d.get("score_financial") or "—", "out of 100"), unsafe_allow_html=True)
        c4.markdown(metric_card("Total Score / Rank", d.get("score_total") or "—", f"Rank #{d['rank']}" if d.get("rank") else "Rank not stated"), unsafe_allow_html=True)

        if d.get("evaluator_feedback"):
            st.markdown("### 💬 Evaluator Feedback")
            st.markdown(f'<div class="info-box" style="white-space:pre-wrap">{d["evaluator_feedback"]}</div>', unsafe_allow_html=True)

        c_wf, c_lf = st.columns(2)
        if d.get("win_factors"):
            c_wf.markdown("### ✅ What Worked (Win Factors)")
            for wf in str(d["win_factors"]).split("\n"):
                if wf.strip():
                    c_wf.markdown(f'<span style="color:#27AE60;font-size:.85rem">✓ {wf.strip()}</span>', unsafe_allow_html=True)
        if d.get("loss_factors"):
            c_lf.markdown("### ❌ What Needs Improvement")
            for lf in str(d["loss_factors"]).split("\n"):
                if lf.strip():
                    c_lf.markdown(f'<span style="color:#C0392B;font-size:.85rem">✗ {lf.strip()}</span>', unsafe_allow_html=True)

        if d.get("lessons"):
            st.markdown("### 💡 Institutional Lessons Learned")
            st.markdown(f'<div class="info-box" style="white-space:pre-wrap">{d["lessons"]}</div>', unsafe_allow_html=True)

        if d.get("competitors"):
            st.markdown(f'<div style="font-size:.8rem;color:#A9A69D;margin-top:.5rem"><strong>Competitors Identified:</strong> {d["competitors"]}</div>', unsafe_allow_html=True)

        if st.button("✏️ Edit Debrief Record", key="btn_edit_deb"):
            st.session_state["editing_debrief"] = d["id"]
            st.rerun()
    else:
        st.markdown('<div class="empty-state">No debrief recorded yet. Fill in the debrief record once the procurement authority publishes the award decision.</div>', unsafe_allow_html=True)

    show_form = not debriefs or st.session_state.get("editing_debrief")
    if show_form:
        d = debriefs[0] if (debriefs and st.session_state.get("editing_debrief")) else {}
        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
        st.markdown("### ✍️ Record / Update Procurement Outcome")
        with st.form("debrief_entry_form"):
            c1, c2, c3, c4 = st.columns(4)
            outcome = c1.selectbox("Official Outcome *", DEBRIEF_OUTCOMES,
                                   index=DEBRIEF_OUTCOMES.index(d.get("outcome", "Pending"))
                                   if d.get("outcome") in DEBRIEF_OUTCOMES else 4)
            t_score = c2.number_input("Technical Score", value=float(d.get("score_technical") or 0), min_value=0.0, max_value=100.0, step=0.5)
            f_score = c3.number_input("Financial Score", value=float(d.get("score_financial") or 0), min_value=0.0, max_value=100.0, step=0.5)
            rank = c4.number_input("Final Rank", value=int(d.get("rank") or 0), min_value=0, step=1)

            feedback = st.text_area("Formal Evaluator Feedback / Scoring Notes", value=d.get("evaluator_feedback") or "", height=80)
            c_w, c_l = st.columns(2)
            win_fac = c_w.text_area("Win Factors (one per line)", value=d.get("win_factors") or "", height=80)
            loss_fac = c_l.text_area("Loss / Scoring Gap Factors (one per line)", value=d.get("loss_factors") or "", height=80)
            lessons = st.text_area("Strategic Lessons for Future Pursuits", value=d.get("lessons") or "", height=70)
            competitors = st.text_input("Winning Bidder / Competitors Mentioned", value=d.get("competitors") or "")

            c_save, c_cancel = st.columns([2, 1])
            if c_save.form_submit_button("Save Debrief Record", use_container_width=True, type="primary"):
                total_score = (t_score + f_score) if (t_score or f_score) else None
                upsert_debrief({
                    "id": d.get("id"),
                    "bid_id": bid_id,
                    "outcome": outcome,
                    "score_technical": t_score if t_score > 0 else None,
                    "score_financial": f_score if f_score > 0 else None,
                    "score_total": total_score,
                    "rank": rank if rank > 0 else None,
                    "evaluator_feedback": feedback,
                    "win_factors": win_fac,
                    "loss_factors": loss_fac,
                    "lessons": lessons,
                    "competitors": competitors,
                })
                # Update bid stage if outcome is Won or Lost
                if outcome in ("Won", "Lost") and bid.get("stage") != outcome:
                    update_bid(bid_id, {**bid, "stage": outcome})
                st.session_state.pop("editing_debrief", None)
                st.success("Debrief record saved.")
                st.rerun()
            if c_cancel.form_submit_button("Cancel", use_container_width=True):
                st.session_state.pop("editing_debrief", None)
                st.rerun()
