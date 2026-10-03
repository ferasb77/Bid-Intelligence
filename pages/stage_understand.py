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
from database import download_file as _download_stored_file
from components.ui import (stage_badge, days_until, days_label, metric_card,
                           readiness_bar, STAGES, SENSITIVITY)
import analysis_service
import auth_session
import tenancy
from config import get_api_key, api_key_configured


def _current_access_token_and_org() -> tuple[str, str]:
    """Phase 8 remediation package 3: the normal routed UNDERSTAND stage
    reads bid/analysis data through the authenticated, RLS-backed client,
    never the service-role client -- app.py's mandatory auth gate
    guarantees a real session and resolved AuthContext exist by the time
    this page is ever reached, so both lookups here are non-optional."""
    session = auth_session.current_session()
    ctx = auth_session.current_auth_context()
    return session["access_token"], ctx.organization_id


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
    _token, _ = _current_access_token_and_org()
    run = tenancy.get_latest_analysis_run_authenticated(_token, bid_id, "FAST")
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


def _render_fast_analysis_governance_note(run: dict, procurement_state: dict) -> None:
    """Migration 010 follow-up correction: a completed run's own stamped
    based_on_procurement_revision/unreviewed_document_count. NULL means
    the run predates procurement-revision tracking (basis unknown) -- it
    is never displayed as revision 1 or as 0 documents outstanding. An
    ungoverned bid's stronger message takes precedence over an ordinary
    stale-revision comparison, matching procurement_staleness_banner."""
    based_on = run.get("based_on_procurement_revision")
    unreviewed = run.get("unreviewed_document_count")
    truth_status = procurement_state.get("procurement_truth_status", "ungoverned")
    current_revision = procurement_state.get("procurement_revision", 1)

    if truth_status != "governed":
        st.markdown(
            '<div class="warn-box">⚠️ Procurement truth has not yet been governed -- this run is advisory '
            'only and may reflect an unverified initial extraction.</div>', unsafe_allow_html=True)
    elif based_on is None:
        st.markdown(
            '<div class="warn-box">⚠️ Procurement revision basis is unknown for this run — it predates '
            'procurement-revision tracking. Re-analysis is required before treating it as current.</div>',
            unsafe_allow_html=True)
    elif based_on != current_revision:
        st.markdown(
            f'<div class="warn-box">⚠️ This run was based on procurement revision {based_on}; the current '
            f'revision is {current_revision}. Re-analyze opportunity to reflect the latest procurement truth.</div>',
            unsafe_allow_html=True)

    if unreviewed is None:
        st.markdown(
            '<div style="font-size:.78rem;color:#6E6C66">Unreviewed-document basis is unknown for this run.</div>',
            unsafe_allow_html=True)
    elif unreviewed > 0:
        st.markdown(
            f'<div class="warn-box">⚠️ {unreviewed} corpus document(s) have not yet been through a governed '
            'review — this output is advisory only.</div>', unsafe_allow_html=True)
    else:
        st.markdown(
            '<div style="font-size:.78rem;color:#27AE60">✅ Every corpus document is covered by a governed review.</div>',
            unsafe_allow_html=True)


def _render_unified_progress(opp_state: dict) -> None:
    """Renders the durable 4-step progress breakdown for live opportunity analysis (B4)."""
    import understand_analysis as ua
    step = opp_state.get("step")
    full_status = opp_state.get("full_status") or {}
    proc_state = opp_state.get("procurement_state") or {}
    truth_status = proc_state.get("procurement_truth_status", "ungoverned")

    # Step 1: Structuring procurement package
    s1_done = step in (
        ua.STEP_BASELINE_REVIEW_REQUIRED,
        ua.STEP_BASELINE_APPLYING,
        ua.STEP_FULL_ANALYSIS_RUNNING,
        ua.STEP_COMPLETE,
        ua.STEP_PARTIAL,
    ) or (truth_status == "governed")
    s1_active = step == ua.STEP_FOUNDATION_RUNNING

    # Step 2: Establishing procurement baseline
    s2_done = truth_status == "governed" or step in (
        ua.STEP_FULL_ANALYSIS_RUNNING,
        ua.STEP_COMPLETE,
        ua.STEP_PARTIAL,
    )
    s2_active = step in (
        ua.STEP_BASELINE_REVIEW_REQUIRED,
        ua.STEP_BASELINE_APPLYING,
    )

    # Step 3: Running multi-specialist intelligence
    specs = full_status.get("specialists") or {}
    spec_complete = sum(1 for s in specs.values() if s.get("status") == "COMPLETE")
    s3_done = spec_complete == 6 or step in (ua.STEP_COMPLETE, ua.STEP_PARTIAL)
    s3_active = step == ua.STEP_FULL_ANALYSIS_RUNNING and not s3_done

    # Step 4: Reconciling bid intelligence
    s4_done = step in (ua.STEP_COMPLETE, ua.STEP_PARTIAL)
    s4_active = step == ua.STEP_FULL_ANALYSIS_RUNNING and s3_done and not s4_done

    def _row(done, active, label, detail=""):
        if done:
            icon = "✅"
            color = "#27AE60"
        elif active:
            icon = "⏳"
            color = "#C9A96E"
        else:
            icon = "⏸"
            color = "#6E6C66"
        det_html = f' <span style="font-size:.76rem;color:#A9A69D">({detail})</span>' if detail else ''
        return f'<div style="font-size:.85rem;padding:.22rem 0;color:{color}">{icon} <strong>{label}</strong>{det_html}</div>'

    s3_detail = f"{spec_complete}/6 specialists complete" if (s3_active or (s3_done and not s4_done)) else ""
    html = '<div style="background:#111118;border:1px solid #292832;border-radius:6px;padding:.85rem 1.15rem;margin:.5rem 0">'
    html += '<div style="font-size:.74rem;color:#C9A96E;text-transform:uppercase;letter-spacing:.08em;margin-bottom:.4rem;font-weight:700">Opportunity Intelligence Pipeline</div>'
    html += _row(s1_done, s1_active, "Step 1: Analyzing procurement documents…")
    html += _row(s2_done, s2_active, "Step 2: Confirming procurement facts…")
    html += _row(s3_done, s3_active, "Step 3: Analyzing opportunity across six intelligence lenses…", s3_detail)
    html += _row(s4_done, s4_active, "Step 4: Reconciling opportunity intelligence…")
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)


def _render_unified_opportunity_analysis_panel(
    bid_id: int, organization_id: str, docs: list, procurement_state: dict
) -> None:
    """The ONE unified initial RFP analysis panel (UNDERSTAND-UX1).
    Replaces separate Fast Analysis and Establish Baseline cards with
    a single coherent customer experience.
    """
    import understand_analysis as ua
    _token, org_id = _current_access_token_and_org()
    opp_state = ua.get_opportunity_analysis_state(bid_id, org_id)
    step = opp_state.get("step")

    rfp_docs = [d for d in docs if isinstance(d, dict) and d.get("doc_type") == "RFP / Source"]
    if not rfp_docs and not docs:
        st.markdown(
            '<div class="info-box">Upload at least one RFP / Source document above to analyze opportunity.</div>',
            unsafe_allow_html=True,
        )
        return

    # COMPLETE or PARTIAL: Compact status bar + exports
    if step in (ua.STEP_COMPLETE, ua.STEP_PARTIAL):
        rev = procurement_state.get("procurement_revision", 1)
        full_status = opp_state.get("full_status") or {}
        telemetry = full_status.get("telemetry") or {}
        completed_at = full_status.get("completed_at") or full_status.get("created_at") or ""
        duration = telemetry.get("wall_seconds")
        dur_str = f" in {duration:.0f}s" if isinstance(duration, (int, float)) else ""
        time_str = f" | Last analyzed: {completed_at[:19].replace('T', ' ')}" if completed_at else ""

        st.markdown(
            f'<div style="background:#0F1A12;border:1px solid #1E3A25;border-radius:6px;padding:.7rem 1.1rem;margin-bottom:.7rem;'
            f'display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.5rem">'
            f'<div><span style="color:#27AE60;font-weight:700">✓ Opportunity intelligence current</span>'
            f'<span style="color:#A9A69D;font-size:.82rem"> | Procurement revision: Baseline (v{rev}){time_str}{dur_str}</span></div>'
            f'</div>',
            unsafe_allow_html=True
        )
        _render_fast_analysis_governance_note(opp_state.get("latest_fast_run") or full_status, procurement_state)
        c1, c2 = st.columns(2)
        try:
            export_run_id = full_status.get("run_id") or (opp_state.get("latest_fast_run") or {}).get("id")
            brief_bytes = tenancy.export_bid_intelligence_brief_for_organization(
                bid_id, export_run_id, org_id
            )
            c1.download_button(
                "⬇ Download Bid Intelligence Brief",
                data=brief_bytes,
                file_name=f"bid_intelligence_brief_{bid_id}.pdf",
                mime="application/pdf",
                key=f"dl_brief_{bid_id}",
                use_container_width=True,
                type="primary",
            )
        except (ValueError, tenancy.AccessDeniedError) as exc:
            c1.caption(f"Brief export is unavailable: {exc}")

        latest_fast = opp_state.get("latest_fast_run") or {}
        if latest_fast.get("report_storage_path"):
            appendix_bytes = _download_stored_file(latest_fast["report_storage_path"])
            if appendix_bytes:
                c1.download_button(
                    "Download Full Intelligence Appendix",
                    data=appendix_bytes,
                    file_name=f"full_intelligence_appendix_{bid_id}.pdf",
                    mime="application/pdf",
                    key=f"dl_analysis_{bid_id}",
                    use_container_width=True,
                )
        if c2.button("🔁 Re-analyze Opportunity", key=f"rerun_analysis_{bid_id}", use_container_width=True):
            _start_opportunity_analysis(bid_id, retry=True)

        with st.expander("🧬 View Specialist Constellation & Details", expanded=False):
            if full_status:
                from components import full_analysis_view as fav
                view = fav.build_view(full_status)
                st.markdown(fav.render_constellation(view), unsafe_allow_html=True)
            if opp_state.get("hub_counts"):
                st.markdown("**Canonical Intelligence Summary:**")
                for count_line in opp_state["hub_counts"]:
                    st.markdown(f"• {count_line}")
            if st.button("🔬 Open Full Specialist Debug View", key=f"open_full_analysis_{bid_id}"):
                st.session_state.page = "stage_full_analysis"
                st.rerun()
        return

    # BASELINE_PRIMARY_AMBIGUOUS: Prompt user to choose primary solicitation document
    if step == ua.STEP_BASELINE_PRIMARY_AMBIGUOUS:
        st.markdown("### 📄 Select Main Solicitation Document")
        st.caption("Multiple procurement documents were uploaded. Please confirm which document is the main solicitation.")
        eligible_docs = opp_state.get("eligible_docs") or rfp_docs or docs
        doc_options = {}
        for d in eligible_docs:
            d_id = d.get("id")
            d_name = d.get("name") or d.get("filename") or f"Document {d_id}"
            doc_options[d_name] = d_id

        selected_name = st.radio(
            "Which document is the main solicitation?",
            options=list(doc_options.keys()),
            key=f"primary_doc_select_{bid_id}"
        )
        selected_doc_id = doc_options.get(selected_name) if selected_name else None

        if st.button("Confirm & Analyze Opportunity →", key=f"confirm_primary_{bid_id}", type="primary"):
            _start_opportunity_analysis(bid_id, chosen_primary_doc_id=selected_doc_id)
        return

    # BASELINE_REVIEW_REQUIRED: In-place baseline review
    if step == ua.STEP_BASELINE_REVIEW_REQUIRED:
        st.markdown("### 🏛️ Confirm Procurement Facts")
        st.caption("Confirm the extracted procurement facts before finalizing bid intelligence.")
        _render_unified_progress(opp_state)
        review = opp_state.get("baseline_review")
        if review:
            _render_review_decision_and_apply(bid_id, org_id, review, "baseline")
        return

    # RUNNING: Active progress with auto-polling
    if step in (
        ua.STEP_FOUNDATION_RUNNING,
        ua.STEP_FULL_ANALYSIS_RUNNING,
        ua.STEP_BASELINE_APPLYING,
    ):
        st.markdown("### 💡 Analyzing Opportunity…")
        st.caption("Analyzing procurement documents, confirming procurement facts, and analyzing opportunity across six intelligence lenses.")
        _render_unified_progress(opp_state)
        full_status = opp_state.get("full_status")
        if full_status and full_status.get("specialists"):
            from components import full_analysis_view as fav
            view = fav.build_view(full_status)
            st.markdown(fav.render_constellation(view), unsafe_allow_html=True)
        if st.button("🔄 Refresh status", key=f"refresh_opp_{bid_id}"):
            st.rerun()
        _poll_active_analysis(bid_id)
        return

    # FAILED:
    if step == ua.STEP_FAILED:
        st.markdown(
            f'<div class="warn-box">❌ {opp_state.get("status_label") or "Analysis interrupted or failed"}</div>',
            unsafe_allow_html=True,
        )
        if st.button("🔁 Retry Opportunity Analysis", key=f"retry_analysis_{bid_id}", type="primary"):
            _start_opportunity_analysis(bid_id, retry=True)
        return

    # READY: Prominent action card
    st.markdown("### 💡 Analyze Opportunity")
    st.caption("Complete multi-lens intelligence across six specialist lenses with cross-domain reconciliation.")
    st.markdown(
        '<div style="background:#111118;border:1px solid #292832;border-radius:8px;padding:1.2rem 1.4rem;margin:.5rem 0 .9rem 0">'
        '<div style="font-size:.9rem;color:#EDEAE3;font-weight:600;margin-bottom:.4rem">'
        'Run the unified opportunity intelligence engine to extract and verify:'
        '</div>'
        '<ul style="font-size:.85rem;color:#A9A69D;margin:.3rem 0;padding-left:1.2rem;line-height:1.6">'
        '<li><strong>Structured requirements & commercial terms</strong> — extracted from all RFP source documents</li>'
        '<li><strong>Governed procurement baseline</strong> — verified qualification gates, scoring criteria, and commercial terms</li>'
        '<li><strong>Multi-specialist intelligence & risk analysis</strong> — 6 specialist lenses with cross-domain reconciliation</li>'
        '<li><strong>Canonical procurement foundation</strong> — authoritative basis for response planning, evidence alignment and proposal assurance</li>'
        '</ul>'
        '</div>',
        unsafe_allow_html=True,
    )
    if st.button("⚡ Analyze Opportunity", key=f"start_analysis_{bid_id}", type="primary"):
        _start_opportunity_analysis(bid_id)

    # Optional Deep Verification & Package Synthesis expander
    with st.expander("🔬 Deep Verification & Cross-Document Synthesis (Optional / In-Depth)", expanded=False):
        st.markdown(
            '<div style="font-size:.82rem;color:#A9A69D">'
            'Runs the legacy 4-stage Deep Extraction pipeline (Stages A–D: detailed item-by-item extraction, '
            '6-type conflict reconciliation, and executive brief synthesis). This is an intensive process (~5–10 min) '
            'and is purely optional for deeper cross-document auditing. Opportunity Analysis above remains the primary '
            'advisory intelligence engine.'
            '</div>',
            unsafe_allow_html=True
        )
        if st.button("🔬 Run Deep Verification & Package Synthesis", key=f"deep_verify_{bid_id}"):
            if not st.session_state.get("anthropic_api_key") and not api_key_configured():
                st.error("Add your Anthropic API key first (see New Bid page or Settings).")
            else:
                api_key = st.session_state.get("anthropic_api_key") or get_api_key()
                from extractor import extract_procurement_package
                pkg_files_to_extract = []
                for d in rfp_docs:
                    fp = d.get("file_path")
                    fn = d.get("filename")
                    if fp and fn:
                        fb = _download_stored_file(fp)
                        if fb:
                            pkg_files_to_extract.append((fn, fb))
                if not pkg_files_to_extract:
                    st.error("No RFP document files could be retrieved for deep verification.")
                else:
                    with st.spinner(f"Running multi-stage deep verification on {len(pkg_files_to_extract)} document(s)…"):
                        try:
                            result, model_used = extract_procurement_package(pkg_files_to_extract, api_key)
                            brief_data = result.get("brief") or {}
                            brief_data["bid_id"] = bid_id
                            _, org_id = _current_access_token_and_org()
                            tenancy.save_bid_brief_for_organization(bid_id, org_id, brief_data)
                            st.success(f"Deep verification completed using {model_used}. Executive brief updated.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Deep verification failed: {e}")


def _start_opportunity_analysis(
    bid_id: int,
    retry: bool = False,
    chosen_primary_doc_id: int | None = None,
):
    """Start or retry unified opportunity analysis via understand_analysis."""
    if not st.session_state.get("anthropic_api_key") and not api_key_configured():
        st.error("Add your Anthropic API key first (see New Bid page or Settings).")
        return
    api_key = st.session_state.get("anthropic_api_key") or get_api_key()
    _, organization_id = _current_access_token_and_org()
    try:
        import understand_analysis as ua
        ua.start_opportunity_analysis(
            bid_id, organization_id, api_key=api_key,
            created_by_user_id=_current_user_id(),
            retry=retry,
            execution="background",
            chosen_primary_doc_id=chosen_primary_doc_id,
        )
        st.success("Opportunity analysis started.")
        st.rerun()
    except tenancy.AccessDeniedError:
        st.error("You do not have access to that bid.")
    except Exception as e:
        st.error(f"Could not start opportunity analysis: {e}")


def _render_fast_analysis_panel(bid_id: int, rfp_docs: list, procurement_state: dict):
    """Backward-compatible wrapper for tests; delegates to the unified panel."""
    _token, org_id = _current_access_token_and_org()
    docs = tenancy.get_documents_authenticated(_token, bid_id) if hasattr(tenancy, "get_documents_authenticated") else rfp_docs
    _render_unified_opportunity_analysis_panel(bid_id, org_id, docs, procurement_state)


def _start_fast_analysis(bid_id: int):
    """Start Fast Analysis through the authenticated tenancy wrapper.
    Never calls analysis_service directly."""
    if not _governance_llm_ready():
        st.error("Add your Anthropic API key first (see New Bid page or Settings).")
        return
    api_key = st.session_state.get("anthropic_api_key") or get_api_key()
    _, organization_id = _current_access_token_and_org()
    try:
        tenancy.start_fast_analysis_for_organization(bid_id, organization_id, api_key, created_by="app-ui")
        st.success("Fast Analysis started.")
        st.rerun()
    except tenancy.AccessDeniedError:
        st.error("You do not have access to that bid.")
    except Exception as e:
        st.error(f"Could not start Fast Analysis: {e}")


# ═════════════════════════════════════════════════════════════════════════════
# PROCUREMENT REVISION & ADDENDUM GOVERNANCE (migration 010)
# ═════════════════════════════════════════════════════════════════════════════
# "Establish Procurement Baseline" (ungoverned bids) and "Procurement
# Documents & Addenda" (governed bids) -- the human-reviewed workflow that
# makes procurement truth an explicitly governed process instead of the
# silent, unreviewed extraction the CDA-AMC audit found. Every write here
# goes through tenancy.py's governance wrappers, which themselves call
# only the migration-010 SECURITY DEFINER RPCs -- this module never writes
# to requirements/bid_briefs/procurement_changes directly. No material
# change is ever auto-approved; Apply is only ever reachable once every
# proposed change for the review has an explicit human decision. Document
# selection only ever shows names/types -- raw Storage bytes are never
# surfaced to the browser (extraction happens server-side inside
# tenancy.propose_procurement_changes_for_organization()).

_GOVERNANCE_BUYER_UPDATE_TYPES = [
    "Bulletin", "Addendum", "Amendment", "Clarification/Q&A",
    "Revised Schedule", "Revised Pricing Form", "Revised Submission Form", "Other",
]
_DOCUMENT_ROLES = ["primary", "supporting", "replacement", "attachment"]


def _current_user_id() -> str | None:
    session = auth_session.current_session()
    return (session or {}).get("user_id")


def _governance_llm_ready() -> bool:
    return bool(st.session_state.get("anthropic_api_key")) or api_key_configured()


def _render_document_role_picker(bid_id: int, organization_id: str, docs: list, key_prefix: str):
    """Shared step-1 widget for both baseline and buyer-update workflows:
    upload new buyer document(s) and/or select from already-registered
    'RFP / Source' documents, then assign each selected document a role.
    Returns (document_ids, document_roles) once the selection is valid
    (>=1 document, exactly one primary); otherwise None. Only ever shows a
    document's name/type/version -- never a preview or download of its
    bytes."""
    up_files = st.file_uploader(
        "Upload new buyer document(s)", accept_multiple_files=True,
        type=["pdf", "docx", "doc", "xlsx", "txt"], key=f"{key_prefix}_upload_{bid_id}",
    )
    if up_files and st.button("⬆ Add uploaded file(s) to the document registry",
                               key=f"{key_prefix}_upload_btn_{bid_id}"):
        for uf in up_files:
            tenancy.upload_document_for_organization(
                bid_id, organization_id, uf.name, uf.read(), doc_type="RFP / Source")
        st.success(f"{len(up_files)} document(s) uploaded.")
        st.rerun()

    rfp_docs = [d for d in docs if d.get("doc_type") == "RFP / Source"]
    if not rfp_docs:
        st.markdown(
            '<div class="info-box">No RFP / Source documents are in the registry yet -- upload at '
            'least one above.</div>', unsafe_allow_html=True)
        return None

    options = {f"{d['name']} (v{d.get('version', 1)})": d["id"] for d in rfp_docs}
    selected_labels = st.multiselect(
        "Documents in this review", list(options.keys()), key=f"{key_prefix}_select_{bid_id}")
    if not selected_labels:
        return None

    st.markdown('<div style="font-size:.8rem;color:#A9A69D;margin-top:.4rem">'
                'Assign a role to each selected document — exactly one must be Primary.</div>',
                unsafe_allow_html=True)
    roles = {}
    for label in selected_labels:
        doc_id = options[label]
        default_idx = 0 if len(selected_labels) == 1 else 0
        roles[doc_id] = st.selectbox(label, _DOCUMENT_ROLES, index=default_idx,
                                     key=f"{key_prefix}_role_{bid_id}_{doc_id}")

    primary_count = sum(1 for r in roles.values() if r == "primary")
    if primary_count != 1:
        st.markdown(
            f'<div class="warn-box">Exactly one selected document must be marked Primary '
            f'(currently {primary_count}).</div>', unsafe_allow_html=True)
        return None

    return list(roles.keys()), list(roles.values())


def _render_change_proposal_row(change: dict, bid_id: int, organization_id: str, key_prefix: str) -> None:
    """One proposed change: entity, current vs. proposed value, change
    type, canonical effect (always shown, called out specifically for
    CLARIFIED rows), physical source, and an evidence-excerpt expander
    (text only, never raw file bytes). Renders Approve/Reject for a
    pending row, or the recorded decision otherwise. Never auto-approves
    -- the only way review_decision changes is an explicit button click
    routed through tenancy.record_change_review_decision_for_organization,
    which stamps the real authenticated user id, never auth.uid()."""
    change_type = change.get("change_type", "")
    canonical_effect = change.get("canonical_effect", "")
    prev = change.get("previous_value") or {}
    new = change.get("new_value") or {}
    effect_color = "#E67E22" if canonical_effect == "canonical_change" else "#6E6C66"
    effect_label = "CANONICAL CHANGE" if canonical_effect == "canonical_change" else "EVIDENCE ONLY — no truth change"
    decision = change.get("review_decision", "pending")

    st.markdown(
        f'<div style="background:#111118;border:1px solid #292832;border-left:3px solid {effect_color};'
        f'border-radius:0 4px 4px 0;padding:.7rem 1rem;margin:.4rem 0">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.4rem">'
        f'<span style="font-weight:600;color:#EDEAE3">{(change.get("entity_type") or "requirement").replace("_"," ").title()} '
        f'— {change.get("entity_id") or "New"}</span>'
        f'<span style="background:{effect_color};color:#0B0B0F;padding:.15rem .55rem;border-radius:3px;'
        f'font-size:.68rem;font-weight:700;white-space:nowrap">{change_type} · {effect_label}</span>'
        f'</div>'
        + ('<div style="font-size:.72rem;color:#C9A96E;margin-top:.35rem">⚠ Clarification — confirm whether '
           'this is CANONICAL CHANGE (changes how the requirement is interpreted going forward) or EVIDENCE '
           'ONLY (confirms existing truth, no change) before approving.</div>' if change_type == "CLARIFIED" else '')
        + f'<div style="display:flex;gap:1.2rem;margin-top:.5rem;flex-wrap:wrap">'
        f'<div style="flex:1;min-width:200px"><div style="font-size:.72rem;color:#A9A69D;text-transform:uppercase">Current value</div>'
        f'<div style="font-size:.84rem">{prev.get("description") or "— (new)"}</div></div>'
        f'<div style="flex:1;min-width:200px"><div style="font-size:.72rem;color:#A9A69D;text-transform:uppercase">Proposed value</div>'
        f'<div style="font-size:.84rem;color:#EDEAE3">{new.get("description") or "—"}</div></div>'
        f'</div>'
        + (f'<div style="font-size:.72rem;color:#6E6C66;margin-top:.4rem">Source: {change["physical_source_ref"]}</div>'
           if change.get("physical_source_ref") else '')
        + '</div>',
        unsafe_allow_html=True,
    )

    evidence = change.get("extraction_evidence") or {}
    sources = evidence.get("sources") if isinstance(evidence, dict) else None
    if sources:
        with st.expander("🔎 View evidence excerpt", expanded=False):
            for s in sources:
                if not isinstance(s, dict):
                    continue
                loc = f"page {s['page']}" if s.get("page") else (s.get("section") or "")
                st.markdown(f"**{loc or 'Source excerpt'}**")
                if s.get("excerpt"):
                    st.markdown(f"> {s['excerpt']}")

    if decision == "pending":
        c_approve, c_reject = st.columns(2)
        if c_approve.button("✅ Approve", key=f"{key_prefix}_approve_{change['id']}", use_container_width=True):
            tenancy.record_change_review_decision_for_organization(
                bid_id, organization_id, change["id"], "approved", _current_user_id())
            st.rerun()
        if c_reject.button("❌ Reject", key=f"{key_prefix}_reject_{change['id']}", use_container_width=True):
            tenancy.record_change_review_decision_for_organization(
                bid_id, organization_id, change["id"], "rejected", _current_user_id())
            st.rerun()
    else:
        badge_color = "#27AE60" if decision == "approved" else "#C0392B"
        st.markdown(f'<span style="color:{badge_color};font-size:.78rem;font-weight:600">'
                    f'Decision: {decision.upper()}</span>', unsafe_allow_html=True)


def _render_review_decision_and_apply(bid_id: int, organization_id: str, review: dict, key_prefix: str) -> None:
    """Step 5-9 (baseline) / 4-8 (buyer update) shared across both review
    kinds: list every proposed change with its decision control, then a
    governed Apply gated on zero remaining pending decisions."""
    changes = tenancy.get_procurement_changes_for_organization(bid_id, organization_id, review["id"])
    if not changes:
        st.markdown('<div class="info-box">Analysis found no material or confirmable facts in the '
                    'selected document(s).</div>', unsafe_allow_html=True)
        return

    st.markdown(f"**{len(changes)} proposed fact(s) from this document set**")
    for change in changes:
        _render_change_proposal_row(change, bid_id, organization_id, key_prefix)

    pending_count = sum(1 for c in changes if c.get("review_decision") == "pending")
    approved_count = sum(1 for c in changes if c.get("review_decision") == "approved")
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    if pending_count:
        st.markdown(f'<div class="info-box">{pending_count} decision(s) still pending — '
                    f'Apply unlocks once every proposal has been approved or rejected.</div>',
                    unsafe_allow_html=True)
    if key_prefix == "baseline" and pending_count > 0:
        if st.button("✅ Approve All & Commit Baseline", key=f"{key_prefix}_approve_all_{review['id']}",
                     type="primary", use_container_width=True):
            try:
                import understand_analysis as ua
                api_key = st.session_state.get("anthropic_api_key") or get_api_key()
                res = ua.apply_baseline_and_resume_analysis(
                    bid_id, organization_id, review["id"],
                    user_id=_current_user_id(), api_key=api_key,
                    approve_all_pending=True,
                )
                st.session_state[f"{key_prefix}_apply_result_{bid_id}"] = res.get("apply_result")
                st.rerun()
            except Exception as e:
                st.error(f"Could not apply baseline: {e}")

    if st.button("🔒 Apply — commit governed procurement truth", key=f"{key_prefix}_apply_{review['id']}",
                 type="primary", disabled=pending_count > 0, use_container_width=True):
        try:
            if key_prefix == "baseline":
                import understand_analysis as ua
                api_key = st.session_state.get("anthropic_api_key") or get_api_key()
                res = ua.apply_baseline_and_resume_analysis(
                    bid_id, organization_id, review["id"],
                    user_id=_current_user_id(), api_key=api_key,
                    approve_all_pending=False,
                )
                st.session_state[f"{key_prefix}_apply_result_{bid_id}"] = res.get("apply_result")
            else:
                result = tenancy.apply_procurement_update_review_for_organization(
                    bid_id, organization_id, review["id"], review.get("base_procurement_revision"),
                    _current_user_id(),
                )
                st.session_state[f"{key_prefix}_apply_result_{bid_id}"] = result
            st.rerun()
        except Exception as e:
            reason = str(e)
            if "no_approved_material_proposal" in reason:
                st.error("At least one proposal must be approved before this review can be applied.")
            elif "stale_revision" in reason:
                st.error("Procurement truth changed since this review was created. Refresh and start again.")
            else:
                st.error(f"Apply failed: {reason}")

    applied = st.session_state.pop(f"{key_prefix}_apply_result_{bid_id}", None)
    if applied is not None:
        st.markdown(
            f'<div class="info-box">✅ Procurement truth is now <strong>governed</strong>. '
            f'Resulting procurement revision: <strong>{applied.get("resulting_revision")}</strong> '
            f'({applied.get("applied_change_count", 0)} change(s) applied).</div>',
            unsafe_allow_html=True)


def _render_baseline_workflow(bid_id: int, organization_id: str, docs: list, revision: int) -> None:
    """Establish Procurement Baseline (ungoverned bids)."""
    st.markdown("### 🏛️ Establish Procurement Baseline")
    st.markdown(
        '<div class="warn-box">⚠ <strong>Procurement truth is not yet governed.</strong> The intelligence '
        'shown on this page comes from an unreviewed initial extraction. Establish a governed baseline below '
        'so a human confirms it before it is relied on.</div>', unsafe_allow_html=True)

    reviews = tenancy.get_procurement_update_reviews_for_organization(bid_id, organization_id)
    active = next((r for r in reviews if r["review_kind"] == "baseline"
                   and r["status"] in ("ready_for_review", "reviewed")), None)
    failed = next((r for r in reviews if r["review_kind"] == "baseline" and r["status"] == "failed"), None)

    if active:
        st.markdown(f'<div style="font-size:.82rem;color:#A9A69D">Baseline review #{active["id"]} — '
                    f'awaiting human decisions.</div>', unsafe_allow_html=True)
        _render_review_decision_and_apply(bid_id, organization_id, active, "baseline")
        return

    if failed:
        st.markdown(f'<div class="warn-box">The last baseline analysis failed: '
                    f'{failed.get("review_note") or "unknown error"}. You may start a new one below.</div>',
                    unsafe_allow_html=True)

    picker = _render_document_role_picker(bid_id, organization_id, docs, "baseline")
    if not picker:
        return
    document_ids, document_roles = picker

    if not _governance_llm_ready():
        st.error("Add your Anthropic API key first (see New Bid page or Settings) to run baseline analysis.")
        return

    if st.button("🏛️ Create Baseline Review & Analyze", key=f"baseline_create_{bid_id}", type="primary"):
        try:
            created = tenancy.create_procurement_update_review_for_organization(
                bid_id, organization_id, "baseline", document_ids, document_roles,
                buyer_update_type="Original RFP",
            )
            review_id = created.get("review_id")
            with st.spinner("Analyzing selected document(s) against the extracted compliance matrix…"):
                tenancy.propose_procurement_changes_for_organization(bid_id, organization_id, review_id)
            st.rerun()
        except Exception as e:
            st.error(f"Could not create/analyze baseline review: {e}")


def _render_buyer_update_workflow(bid_id: int, organization_id: str, docs: list, revision: int) -> None:
    """Procurement Documents & Addenda (governed bids)."""
    st.markdown("### 📬 Procurement Documents & Addenda")
    st.markdown(
        f'<div style="font-size:.82rem;color:#A9A69D">Procurement truth is governed — current revision '
        f'<strong>{revision}</strong>. Use this to incorporate a buyer-issued bulletin, addendum, amendment, '
        f'or clarification against the CURRENT governed truth.</div>', unsafe_allow_html=True)

    reviews = tenancy.get_procurement_update_reviews_for_organization(bid_id, organization_id)
    active = next((r for r in reviews if r["review_kind"] == "buyer_update"
                   and r["status"] in ("ready_for_review", "reviewed")), None)
    failed = next((r for r in reviews if r["review_kind"] == "buyer_update" and r["status"] == "failed"), None)

    if active:
        st.markdown(
            f'<div style="font-size:.82rem;color:#A9A69D">Buyer update review #{active["id"]} '
            f'({active.get("buyer_update_type") or "—"}) — awaiting human decisions.</div>',
            unsafe_allow_html=True)
        _render_review_decision_and_apply(bid_id, organization_id, active, "buyer_update")
        return

    if failed:
        st.markdown(f'<div class="warn-box">The last buyer-update analysis failed: '
                    f'{failed.get("review_note") or "unknown error"}. You may start a new one below.</div>',
                    unsafe_allow_html=True)

    with st.expander("📬 Incorporate a buyer-issued update document", expanded=False):
        update_type = st.selectbox("Update type", _GOVERNANCE_BUYER_UPDATE_TYPES, key=f"buyer_update_type_{bid_id}")
        picker = _render_document_role_picker(bid_id, organization_id, docs, "buyer_update")
        if not picker:
            return
        document_ids, document_roles = picker

        if not _governance_llm_ready():
            st.error("Add your Anthropic API key first (see New Bid page or Settings) to run this analysis.")
            return

        if st.button("📬 Create Update Review & Analyze", key=f"buyer_update_create_{bid_id}", type="primary"):
            try:
                created = tenancy.create_procurement_update_review_for_organization(
                    bid_id, organization_id, "buyer_update", document_ids, document_roles,
                    buyer_update_type=update_type,
                )
                review_id = created.get("review_id")
                with st.spinner("Analyzing against CURRENT governed procurement truth…"):
                    tenancy.propose_procurement_changes_for_organization(bid_id, organization_id, review_id)
                st.rerun()
            except Exception as e:
                st.error(f"Could not create/analyze update review: {e}")


def _render_procurement_governance_panel(bid_id: int, organization_id: str, docs: list) -> dict:
    """Returns the fetched procurement_state so callers elsewhere on this
    page don't need a second, redundant fetch. In the unified flow, baseline
    review is handled in-place within the Analyze Opportunity panel."""
    state = tenancy.get_procurement_state_for_organization(bid_id, organization_id)
    truth_status = state.get("procurement_truth_status", "ungoverned")
    revision = state.get("procurement_revision", 1)

    if truth_status == "governed":
        _render_buyer_update_workflow(bid_id, organization_id, docs, revision)
    else:
        st.markdown(
            '<div class="warn-box">⚠ <strong>Procurement truth is not yet governed.</strong> The intelligence '
            'for this opportunity will establish and confirm a governed baseline.</div>', unsafe_allow_html=True)

    return state


def _is_internal_benchmark_text(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(tok in low for tok in (
        "check-1", "check-2", "migration 021", "migration 022", "benchmark bid",
        "test fixture", "fixture", "commissioning", "canonical check",
    ))


def _resolve_canonical_deadlines(bid: dict, brief_row: dict, analysis_result: dict | None) -> tuple[str | None, str | None]:
    """Retrieve canonical submission and clarification deadlines without hardcoding dates.
    Reads bid -> brief_row -> canonical procurement identity merge -> canonical milestones."""
    sub_deadline = bid.get("submission_deadline")
    clar_deadline = bid.get("clarification_deadline")

    if not sub_deadline or not clar_deadline:
        if not sub_deadline:
            sub_deadline = brief_row.get("submission_deadline")
        if not clar_deadline:
            clar_deadline = brief_row.get("clarification_deadline")

    if (not sub_deadline or not clar_deadline) and analysis_result:
        snap = analysis_result.get("fast_analysis_result_snapshot") or {}
        r_snap = snap.get("result") or {}
        doc_meta = r_snap.get("doc_metadata_by_doc") or {}
        if doc_meta:
            try:
                import canonical_procurement as cp
                merged_ident = cp.merge_identity_fields(doc_meta)
                if not sub_deadline:
                    sub_deadline = merged_ident.get("submission_deadline")
                if not clar_deadline:
                    clar_deadline = merged_ident.get("clarification_deadline")
            except Exception:
                pass

        if not sub_deadline or not clar_deadline:
            cms = r_snap.get("canonical_milestones") or []
            for m in cms:
                lbl = (m.get("label") or "").upper()
                d_val = m.get("normalized_date_start")
                if not sub_deadline and lbl == "SUBMISSION_DEADLINE" and d_val:
                    sub_deadline = d_val
                if not clar_deadline and lbl == "CLARIFICATION_DEADLINE" and d_val:
                    clar_deadline = d_val

        if not sub_deadline or not clar_deadline:
            oi = analysis_result.get("structured_intelligence") or {}
            dm = oi.get("dates_and_mechanics") or {}
            raw_dates = dm.get("raw_date_observations") or []
            for o in raw_dates:
                kind = (o.get("semantic_kind") or "").upper()
                d_val = o.get("date")
                if not sub_deadline and kind == "SUBMISSION_DEADLINE" and d_val:
                    sub_deadline = d_val
                if not clar_deadline and kind in ("CLARIFICATION_DEADLINE", "ENQUIRY_DEADLINE") and d_val:
                    clar_deadline = d_val

    return sub_deadline, clar_deadline


def _resolve_customer_safe_summary(bid: dict, brief_row: dict, analysis_result: dict | None) -> str:
    """Resolve customer-facing executive summary. Never renders internal benchmark,
    migration, or QA fixture wording."""
    raw_summary = brief_row.get("executive_summary")
    if not raw_summary or _is_internal_benchmark_text(raw_summary):
        candidate_notes = bid.get("notes")
        if candidate_notes and not _is_internal_benchmark_text(candidate_notes):
            raw_summary = candidate_notes
        else:
            ps_intro = None
            if analysis_result:
                oi = analysis_result.get("structured_intelligence") or {}
                ps = oi.get("procurement_scope") or {}
                rc = analysis_result.get("report_content_snapshot") or {}
                ps_intro = ps.get("intro") or rc.get("PROCURED_INTRO")
            if ps_intro and not _is_internal_benchmark_text(ps_intro):
                raw_summary = ps_intro
            else:
                client = bid.get("client") or "The buyer"
                title = bid.get("title") or "services"
                ref = f" under solicitation #{bid['file_number']}" if bid.get("file_number") else ""
                raw_summary = f"{client} is procuring {title}{ref}."
    return raw_summary or "Executive summary pending synthesis."


def page_understand(bid_id: int):
    _token, _org_id = _current_access_token_and_org()
    bid = tenancy.get_bid_authenticated(_token, bid_id)
    if not bid:
        st.error("Opportunity not found.")
        return

    brief_row = tenancy.get_bid_brief_authenticated(_token, bid_id) or {}
    reqs = tenancy.get_requirements_authenticated(_token, bid_id)
    docs = tenancy.get_documents_authenticated(_token, bid_id)
    analysis_result = tenancy.get_latest_analysis_result_authenticated(_token, bid_id, "FAST")

    # Decode JSON fields from brief_row if present
    exec_summary = _resolve_customer_safe_summary(bid, brief_row, analysis_result)
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

    # ── PROCUREMENT REVISION & ADDENDUM GOVERNANCE (migration 010) ───────────
    # Rendered before everything else on this page: whether procurement
    # truth is governed shapes how much trust the rest of the page's
    # intelligence deserves (an ungoverned bid must never visually imply
    # its revision 1 is verified truth).
    procurement_state = _render_procurement_governance_panel(bid_id, _org_id, docs)
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

    # ── TOP KPI SUMMARY CARDS ──────────────────────────────────────────────────
    sub_deadline, clar_deadline = _resolve_canonical_deadlines(bid, brief_row, analysis_result)
    sub_days = days_until(sub_deadline)
    clar_days = days_until(clar_deadline)
    val_str = f"CAD {bid['value_cad']:,.0f}" if bid.get("value_cad") else "Not stated"

    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(metric_card("Submission Deadline", sub_deadline or "—", days_label(sub_days) if sub_days is not None else "Date unconfirmed"), unsafe_allow_html=True)
    k2.markdown(metric_card("Enquiry Deadline", clar_deadline or "—", days_label(clar_days) if clar_days is not None else "Date unconfirmed"), unsafe_allow_html=True)
    k3.markdown(metric_card("Est. Value / Term", val_str, contract_term[:32]), unsafe_allow_html=True)
    k4.markdown(metric_card("Procurement Model", proc_model[:22], f"Lead: {bid.get('owner') or 'Unassigned'}"), unsafe_allow_html=True)
    st.markdown("")

    # ── OPPORTUNITY ANALYSIS: START / LIVE PROGRESS (UNDERSTAND-UX1) ───────────
    # Unified single customer-facing workflow: Fast Analysis foundation ->
    # baseline review governance -> Full Bid Intelligence.
    _render_unified_opportunity_analysis_panel(bid_id, _org_id, docs, procurement_state)
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
    analysis_result = tenancy.get_latest_analysis_result_authenticated(_token, bid_id, "FAST")
    if analysis_result and analysis_result.get("structured_intelligence"):
        oi = _ensure_dict(analysis_result["structured_intelligence"])
        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
        st.markdown("## ⚡ Opportunity Intelligence — Detailed Findings")
        st.markdown(
            '<div style="font-size:.82rem;color:#A9A69D;margin-bottom:.6rem">'
            'Detailed, source-traceable output from the opportunity intelligence engine. '
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
