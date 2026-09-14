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
                      get_documents, save_upload, update_bid, get_latest_analysis_result,
                      get_latest_analysis_run, download_file as _download_stored_file)
from components.ui import (stage_badge, days_until, days_label, metric_card,
                           readiness_bar, STAGES, SENSITIVITY)
import analysis_service
from config import get_api_key, api_key_configured


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


def _evidence_label(item):
    refs = item.get("source_refs") or [] if isinstance(item, dict) else []
    parts = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        location = ref.get("source_doc") or "Source"
        for key in ("page", "sheet", "section", "rows", "cell_range"):
            if ref.get(key) not in (None, ""):
                location += f" · {key} {ref[key]}"
        parts.append(location)
    state = item.get("evidence_state", "UNVERIFIED") if isinstance(item, dict) else "UNVERIFIED"
    return state, "; ".join(parts)


def _source_view_expander(label, source_refs, key_suffix=""):
    """Phase 2: per-fact 'View Source' progressive disclosure, per
    docs/BID_INTELLIGENCE_TARGET_ARCHITECTURE.md's Stage 1 spec ("Every
    intelligence section provides an expandable 'View Source & Details'
    toggle displaying extracted verbatim RFP excerpts"). Reads the
    OpportunityIntelligence contract's source_refs (doc/page/excerpt) --
    no-ops when a fact carries no real source refs."""
    refs = [r for r in (source_refs or []) if isinstance(r, dict)]
    if not refs:
        return
    with st.expander(f"🔎 View Source — {label}" if label else "🔎 View Source"):
        for ref in refs:
            doc = ref.get("source_doc") or "Source document"
            loc_parts = []
            for key in ("page", "sheet", "section"):
                if ref.get(key) not in (None, ""):
                    loc_parts.append(f"{key}: {ref[key]}")
            loc = " · ".join(loc_parts)
            excerpt = ref.get("excerpt")
            st.markdown(f"**{doc}**{' — ' + loc if loc else ''}")
            if excerpt:
                st.markdown(f"> {excerpt}")


# ═════════════════════════════════════════════════════════════════════════════
# FAST ANALYSIS PANEL — Product Integration Phase 1 / Phase 2 (progressive UX)
# ═════════════════════════════════════════════════════════════════════════════
# Relocated here from app.py (Phase 3 commissioning fix, instruction 15:
# "fix only the smallest integration defect necessary"): this panel was
# originally wired into app.py's page_bid_overview(), but no route in
# app.py's router ever calls page_bid_overview -- "stage_understand" and
# "bid_overview" both resolve to page_understand() (this function). The
# panel was therefore unreachable through any real user path since Phase 1.
# Placing it in the page that is actually reached also matches Phase 2's
# own "enhance the existing UNDERSTAND stage" decision.
_ANALYSIS_STATUS_LABEL = {
    "QUEUED": "⏳ Queued",
    "PREPARING": "📄 Preparing documents…",
    "ANALYZING": "🧠 Analyzing… (typically 2–4 minutes)",
    "ASSEMBLING": "📝 Assembling report…",
    "COMPLETE": "✅ Complete",
    "FAILED": "❌ Failed",
}
_ANALYSIS_NON_TERMINAL = ("QUEUED", "PREPARING", "ANALYZING", "ASSEMBLING")

# Smallest appropriate refresh mechanism for this Streamlit app (instruction
# 6): a fragment re-run, not WebSockets/Supabase Realtime/a queue platform.
# 6s keeps the panel feeling live across a typical 2-4 minute run without
# hammering Supabase (~20-40 lightweight reads per active viewer per run).
ANALYSIS_POLL_INTERVAL_SECONDS = 6


def _should_poll(run: dict | None) -> bool:
    """True only while a run is genuinely non-terminal. Governs whether the
    auto-refresh fragment keeps re-arming itself -- polling always stops the
    moment a run reaches COMPLETE or FAILED."""
    return bool(run) and run.get("status") in _ANALYSIS_NON_TERMINAL


def _render_milestone_checklist(run: dict) -> None:
    """Instruction 4/7: real, durable progression -- never a bare spinner,
    never internal route/task names. Reads run['progress'] (persisted by
    analysis_service._ProgressTracker from real task-completion events) and
    renders it against the fixed canonical MILESTONE_ORDER, since the order
    milestones are actually reached in is not guaranteed (concurrent
    tasks)."""
    progress = run.get("progress") or {}
    reached = {m.get("milestone") for m in (progress.get("milestones") or [])}
    rows = []
    for milestone in analysis_service.MILESTONE_ORDER:
        label = analysis_service.MILESTONE_UI_LABEL.get(milestone, milestone)
        mark = "✅" if milestone in reached else "⏳"
        rows.append(f'<div style="font-size:.82rem;padding:.15rem 0;color:{"#EDEAE3" if milestone in reached else "#6E6C66"}">{mark} {label}</div>')
    st.markdown('<div style="margin:.5rem 0">' + "".join(rows) + '</div>', unsafe_allow_html=True)

    early = progress.get("early_facts") or {}
    known = []
    if early.get("title"):
        known.append(f"<strong>{early['title']}</strong>")
    if early.get("buyer"):
        known.append(f"Buyer: {early['buyer']}")
    if early.get("submission_deadline"):
        known.append(f"Submission: {early['submission_deadline']}")
    if early.get("procurement_mechanic"):
        known.append(early["procurement_mechanic"])
    if known:
        st.markdown(
            '<div class="info-box" style="margin-top:.3rem;font-size:.82rem">'
            '🔎 <strong>What we know so far:</strong><br>' + " · ".join(known) + '</div>',
            unsafe_allow_html=True)


def _render_active_run_progress(bid_id: int) -> None:
    """The active-run view's actual rendering logic -- kept as a plain,
    directly-testable function (an @st.fragment-decorated function's body
    does not execute outside a real Streamlit script run context, so the
    fragment wrapper below is kept as a thin, untested pass-through).
    Re-fetches the run fresh from the database every call so progress is
    always DB-truthful, matching exactly what a manual refresh, a different
    browser tab, or a reconnect after navigating away would see (instruction
    2/5) -- nothing here lives only in this thread's memory or in
    session_state. Stops polling the instant the run is no longer
    non-terminal by triggering one full-page rerun (instruction 6), after
    which this is no longer entered at all."""
    run = get_latest_analysis_run(bid_id, "FAST")
    if not _should_poll(run):
        st.rerun()
        return

    st.markdown(f'<div class="info-box">{_ANALYSIS_STATUS_LABEL.get(run["status"], run["status"])} '
                f'— started {run.get("started_at") or run.get("created_at") or ""}</div>',
                unsafe_allow_html=True)
    _render_milestone_checklist(run)
    if st.button("🔄 Refresh now", key=f"refresh_analysis_{bid_id}"):
        pass  # any interaction inside a fragment already reruns it, re-fetching run above

    # Phase 2 stuck-run safety net: bounded, user-initiated only -- never
    # automatic. Only offered once a run has run far longer than any
    # observed real run, so a merely slow run is never mistaken for one
    # whose background thread died with the process.
    if analysis_service.is_run_stuck(run):
        st.markdown('<div class="warn-box">⚠️ This run has been active far longer than expected '
                    'and may be stuck (for example, if the app process restarted while it was '
                    'running). You can mark it as failed to try again.</div>', unsafe_allow_html=True)
        if st.button("⚠️ Mark as Failed (stuck)", key=f"mark_stuck_{bid_id}"):
            analysis_service.mark_run_failed_as_stuck(run["id"])
            st.rerun()  # full-page rerun -- falls through to the FAILED branch below


@st.fragment(run_every=ANALYSIS_POLL_INTERVAL_SECONDS)
def _poll_active_analysis(bid_id: int) -> None:
    """Smallest appropriate Streamlit auto-refresh mechanism (instruction 6):
    re-runs only this fragment every ANALYSIS_POLL_INTERVAL_SECONDS, not the
    whole page -- no WebSockets, no Supabase Realtime, no queue platform."""
    _render_active_run_progress(bid_id)


def _render_fast_analysis_panel(bid_id: int, rfp_docs: list):
    """Status + start/retry UI for the Fast Analysis engine. Goes through
    analysis_service.py exclusively; never touches fast_analysis.py or the
    report adapters directly. The active/non-terminal case is delegated to
    the auto-polling _poll_active_analysis fragment (Phase 2); every other
    branch below is unchanged from Phase 1."""
    st.markdown("### ⚡ Fast Analysis")
    run = get_latest_analysis_run(bid_id, "FAST")

    if not rfp_docs:
        st.markdown('<div class="info-box">Upload at least one RFP / Source document above to run Fast Analysis.</div>', unsafe_allow_html=True)
        return

    if _should_poll(run):
        _poll_active_analysis(bid_id)
        return

    if run and run["status"] == "FAILED":
        st.markdown(f'<div class="warn-box">❌ The last Fast Analysis run failed: '
                    f'{run.get("failure_reason") or "unknown error"}</div>', unsafe_allow_html=True)
        if st.button("🔁 Retry Fast Analysis", key=f"retry_analysis_{bid_id}", type="primary"):
            _start_fast_analysis(bid_id)
        return

    if run and run["status"] == "COMPLETE":
        telemetry = run.get("telemetry") or {}
        duration = telemetry.get("wall_seconds")
        st.markdown(
            f'<div class="info-box">✅ Fast Analysis complete'
            f'{f" in {duration:.0f}s" if isinstance(duration, (int, float)) else ""} '
            f'— see the <strong>UNDERSTAND</strong> stage for the intelligence report.</div>',
            unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        if run.get("report_storage_path"):
            pdf_bytes = _download_stored_file(run["report_storage_path"])
            if pdf_bytes:
                c1.download_button("⬇ Download Report PDF", data=pdf_bytes,
                                   file_name=f"bid_intelligence_preview_{bid_id}.pdf",
                                   mime="application/pdf", key=f"dl_analysis_{bid_id}",
                                   use_container_width=True)
        if c2.button("🔁 Re-run Fast Analysis", key=f"rerun_analysis_{bid_id}", use_container_width=True):
            _start_fast_analysis(bid_id)
        return

    # No run yet.
    st.markdown('<div style="font-size:.82rem;color:#A9A69D">Runs the default analysis engine '
                '(evaluation criteria, pricing structure, ambiguities, commercial terms) in the '
                'background and populates the UNDERSTAND stage automatically. Typically 2–4 minutes.</div>',
                unsafe_allow_html=True)
    if st.button("⚡ Run Fast Analysis", key=f"start_analysis_{bid_id}", type="primary"):
        _start_fast_analysis(bid_id)


def _start_fast_analysis(bid_id: int):
    if not st.session_state.get("anthropic_api_key") and not api_key_configured():
        st.error("Add your Anthropic API key first (see New Bid page or Settings).")
        return
    api_key = st.session_state.get("anthropic_api_key") or get_api_key()
    try:
        analysis_service.start_fast_analysis(bid_id, api_key, created_by="app-ui")
        st.success("Fast Analysis started.")
        st.rerun()
    except analysis_service.DuplicateAnalysisRunError as e:
        st.warning(f"An analysis is already in progress for this bid (run {e.existing_run.get('id')}).")
        st.rerun()
    except analysis_service.NoCorpusError as e:
        st.error(str(e))
    except Exception as e:
        st.error(f"Could not start Fast Analysis: {e}")


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

    # ── FAST ANALYSIS: START / LIVE PROGRESS ──────────────────────────────────
    # Phase 3 commissioning fix: this is the only reachable place in the
    # product a user can actually start/observe Fast Analysis (see the panel
    # functions above for why). Runs before the completed-intelligence
    # section further down, which continues to render only once a run is
    # COMPLETE.
    rfp_docs = [d for d in docs if d.get("doc_type") == "RFP / Source"]
    _render_fast_analysis_panel(bid_id, rfp_docs)
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

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
                evidence_state, evidence = _evidence_label(d)
                st.markdown(
                    f'<div style="background:#111118;border:1px solid #292832;border-radius:4px;'
                    f'padding:.6rem .9rem;margin:.3rem 0;font-size:.85rem">'
                    f'<strong>{d.get("title","Deliverable")}</strong>{cat_tag}'
                    f'{"<br><span style=font-size:.76rem;color:#A9A69D>" + d.get("description","") + "</span>" if d.get("description") else ""}'
                    f'<div style="font-size:.7rem;color:#6E6C66;margin-top:.2rem">SOURCE / EVIDENCE: {evidence_state}{" · " + evidence if evidence else ""}</div>'
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
                evidence_state, evidence = _evidence_label(cm)
                st.markdown(
                    f'<div style="background:#111118;border:1px solid #292832;border-radius:4px;'
                    f'padding:.6rem .9rem;margin:.3rem 0;font-size:.85rem">'
                    f'<strong style="color:#C9A96E">{cm.get("topic","Commercial Item")}</strong>'
                    f'<div style="font-size:.78rem;color:#EDEAE3;margin-top:.2rem">{cm.get("source_fact") or cm.get("details","")}</div>'
                    f'<div style="font-size:.7rem;color:#6E6C66;margin-top:.2rem">SOURCE / EVIDENCE: {evidence_state}{" · " + evidence if evidence else ""}</div>'
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
            evidence_state, evidence = _evidence_label(rk)
            legacy = rk.get("assessment_basis") == "LEGACY_EXTRACTION"
            sc_col = "#6E6C66" if legacy else "#E67E22"
            source_fact = rk.get("source_fact") or rk.get("risk", "")
            assessments = rk.get("assessment") or []
            interpretation = "; ".join(a.get("why_it_matters", "") for a in assessments if isinstance(a, dict) and a.get("why_it_matters"))
            st.markdown(
                f'<div style="background:#111118;border:1px solid #292832;border-left:3px solid {sc_col};'
                f'border-radius:0 4px 4px 0;padding:.6rem 1rem;margin:.35rem 0;font-size:.85rem">'
                f'<span style="color:{sc_col};font-weight:700;font-size:.75rem">{"LEGACY EXTRACTION" if legacy else "SOURCE FACT"}</span> '
                f'<strong>{rk.get("topic") or source_fact}</strong>'
                f'<div style="font-size:.78rem;color:#EDEAE3;margin-top:.2rem">{rk.get("details") or source_fact}</div>'
                f'{"<div style=font-size:.78rem;color:#A9A69D;margin-top:.2rem><strong>SYSTEM INTERPRETATION:</strong> " + interpretation + "</div>" if interpretation else ""}'
                f'<div style="font-size:.7rem;color:#6E6C66;margin-top:.2rem">SOURCE / EVIDENCE: {evidence_state}{" · " + evidence if evidence else ""}</div>'
                f'</div>',
                unsafe_allow_html=True
            )
    else:
        st.markdown('<div class="info-box">No source-grounded contract-risk clauses were identified in the extracted evidence. This does not confirm that none exist.</div>', unsafe_allow_html=True)

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

    # ── FAST ANALYSIS: FULL STRUCTURED INTELLIGENCE (Product Integration Phase 2) ──
    # Additive to the bid_briefs-driven sections above -- reads the durable
    # OpportunityIntelligence contract straight from analysis_results, with
    # no re-extraction. Renders only when a completed Fast Analysis run
    # exists for this bid; otherwise the page behaves exactly as before.
    analysis_result = get_latest_analysis_result(bid_id, "FAST")
    if analysis_result and analysis_result.get("structured_intelligence"):
        oi = _ensure_dict(analysis_result["structured_intelligence"])
        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
        st.markdown("## ⚡ Fast Analysis — Full Intelligence")
        st.markdown(
            '<div style="font-size:.82rem;color:#A9A69D;margin-bottom:.6rem">'
            'Detailed, source-traceable output from the default analysis engine. '
            'Expand any "View Source" panel to see the exact document, page, and excerpt a fact came from.'
            '</div>',
            unsafe_allow_html=True
        )

        dates_and_mechanics = _ensure_dict(oi.get("dates_and_mechanics"))
        raw_dates = _ensure_list(dates_and_mechanics.get("raw_date_observations"))
        if raw_dates:
            st.markdown("### 📅 Key Dates — Full Detail")
            for i, obs in enumerate(raw_dates):
                label = obs.get("semantic_kind") or "Date"
                value = obs.get("date") or obs.get("original_value") or ""
                scope = obs.get("scope") or {}
                scope_str = next((v for v in scope.values() if v), None) if isinstance(scope, dict) else None
                st.markdown(
                    f'<div style="background:#111118;border:1px solid #292832;border-radius:4px;'
                    f'padding:.5rem .8rem;margin:.25rem 0;font-size:.84rem">'
                    f'{label}{" (" + scope_str + ")" if scope_str else ""} — <strong style="color:#C9A96E">{value}</strong>'
                    f'</div>',
                    unsafe_allow_html=True
                )
                _source_view_expander(f"{label} · {value}", obs.get("source_refs"), key_suffix=f"date_{i}")

        evaluation = _ensure_dict(oi.get("evaluation"))
        raw_occ = _ensure_list(evaluation.get("raw_occurrences"))
        if raw_occ:
            st.markdown("### 📊 Evaluation Criteria — Full Detail by Category")
            categories = {}
            for occ in raw_occ:
                cat = occ.get("category_scope") or "Uncategorized"
                categories.setdefault(cat, []).append(occ)
            for cat, occs in categories.items():
                st.markdown(f"**{cat}**")
                for i, occ in enumerate(occs):
                    label = occ.get("criterion_label") or "Criterion"
                    weight = occ.get("weight") or ""
                    st.markdown(
                        f'<div style="background:#111118;border:1px solid #292832;border-radius:4px;'
                        f'padding:.5rem .8rem;margin:.25rem 0;font-size:.84rem">'
                        f'{label} {("— <strong style=color:#27AE60>" + weight + "</strong>") if weight else ""}'
                        f'</div>',
                        unsafe_allow_html=True
                    )
                    _source_view_expander(f"{cat} · {label}", occ.get("source_refs"), key_suffix=f"eval_{cat}_{i}")

        ambiguities = _ensure_list(oi.get("ambiguities"))
        if ambiguities:
            st.markdown("### ❓ Ambiguities & Clarification Questions")
            for amb in ambiguities:
                st.markdown(
                    f'<div style="background:#1A0F00;border:1px solid #3A2A00;border-left:3px solid #E67E22;'
                    f'border-radius:0 4px 4px 0;padding:.65rem 1rem;margin:.35rem 0;font-size:.85rem">'
                    f'<span style="color:#E67E22;font-weight:700;font-size:.74rem">{amb.get("type","AMBIGUITY")}</span>'
                    f'<div style="margin-top:.25rem;color:#EDEAE3"><strong>{amb.get("issue","")}</strong></div>'
                    f'{"<div style=font-size:.78rem;color:#A9A69D;margin-top:.2rem><strong>Why it matters:</strong> " + amb.get("why_it_matters","") + "</div>" if amb.get("why_it_matters") else ""}'
                    f'{"<div style=font-size:.78rem;color:#6E6C66;margin-top:.2rem>Source: " + amb.get("source","") + "</div>" if amb.get("source") else ""}'
                    f'{"<div style=font-size:.78rem;color:#27AE60;margin-top:.3rem>💬 <strong>Suggested clarification question:</strong> " + amb.get("clarification_question","") + "</div>" if amb.get("clarification_question") else ""}'
                    f'</div>',
                    unsafe_allow_html=True
                )

        pricing = _ensure_dict(oi.get("pricing_and_commercial"))
        pricing_points = _ensure_list(pricing.get("points"))
        raw_pricing_occ = _ensure_list(pricing.get("raw_pricing_occurrences"))
        if pricing_points or raw_pricing_occ:
            st.markdown("### 💰 Pricing & Commercial Detail")
            for p in pricing_points:
                st.markdown(
                    f'<div style="background:#111118;border:1px solid #292832;border-radius:4px;'
                    f'padding:.55rem .85rem;margin:.3rem 0;font-size:.84rem">'
                    f'<strong style="color:#C9A96E">{p.get("topic","")}</strong>'
                    f'<div style="font-size:.78rem;color:#EDEAE3;margin-top:.2rem">{p.get("detail","")}</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
            for i, occ in enumerate(raw_pricing_occ):
                label = occ.get("raw_wording") or occ.get("semantic_kind") or "Pricing detail"
                _source_view_expander(str(label)[:80], occ.get("source_refs"), key_suffix=f"pricing_{i}")
            raw_commercial = _ensure_list(pricing.get("raw_commercial_clauses"))
            for i, c in enumerate(raw_commercial):
                label = c.get("topic") or c.get("clause_kind") or "Commercial clause"
                _source_view_expander(str(label)[:80], c.get("source_refs"), key_suffix=f"commercial_{i}")

        buyer_intel = _ensure_dict(oi.get("buyer_intelligence"))
        verified_facts = _ensure_list(buyer_intel.get("verified_facts"))
        relevant_signals = _ensure_list(buyer_intel.get("relevant_signals"))
        bid_relevance = _ensure_list(buyer_intel.get("bid_relevance"))
        if verified_facts or relevant_signals or bid_relevance:
            st.markdown("### 🏛️ Buyer Intelligence")
            if buyer_intel.get("intro"):
                st.markdown(f'<div style="font-size:.85rem;color:#EDEAE3;margin-bottom:.4rem">{buyer_intel["intro"]}</div>', unsafe_allow_html=True)
            b1, b2 = st.columns(2)
            with b1:
                if verified_facts:
                    st.markdown("**Verified Facts**")
                    for f in verified_facts:
                        st.markdown(
                            f'<div style="background:#111118;border:1px solid #292832;border-radius:4px;'
                            f'padding:.5rem .8rem;margin:.25rem 0;font-size:.82rem">'
                            f'<strong>{f.get("topic","")}</strong><br>'
                            f'<span style="color:#A9A69D">{f.get("detail","")}</span>'
                            f'{"<div style=font-size:.68rem;color:#6E6C66;margin-top:.15rem>" + f.get("source","") + "</div>" if f.get("source") else ""}'
                            f'</div>',
                            unsafe_allow_html=True
                        )
            with b2:
                if bid_relevance:
                    st.markdown("**What This Means for the Bid**")
                    for b in bid_relevance:
                        st.markdown(
                            f'<div style="background:#111118;border:1px solid #292832;border-radius:4px;'
                            f'padding:.5rem .8rem;margin:.25rem 0;font-size:.82rem">'
                            f'<strong>{b.get("signal","")}</strong><br>'
                            f'<span style="color:#A9A69D">{b.get("interpretation","")}</span>'
                            f'</div>',
                            unsafe_allow_html=True
                        )
            if buyer_intel.get("facts_note") or buyer_intel.get("sources_note"):
                note = buyer_intel.get("facts_note") or buyer_intel.get("sources_note")
                st.markdown(f'<div style="font-size:.7rem;color:#6E6C66;margin-top:.3rem">{note}</div>', unsafe_allow_html=True)

        source_map = _ensure_dict(oi.get("source_map"))
        ref_table = _ensure_list(source_map.get("reference_table"))
        if ref_table:
            with st.expander("🗺️ View Full Source Map"):
                for row in ref_table:
                    st.markdown(f"• **{row.get('finding','')}**: {row.get('reference','')}")

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
