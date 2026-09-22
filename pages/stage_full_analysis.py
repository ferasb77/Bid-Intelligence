"""
Full Bid Intelligence (MA-2B) -- the animated multi-agent Full Analysis
experience for one bid.

Reached from the active-bid sidebar ("Full Bid Intelligence",
page == "stage_full_analysis") and from the Fast Analysis panel in
UNDERSTAND. Distinct from Fast Analysis, which it never replaces.

Every read/write goes through tenancy's MA-2A wrappers, which call
full_analysis_service -- the one canonical orchestration boundary. This
page never imports full_analysis.py, never calls a specialist, and never
makes a model call of its own: it renders persisted state only.

Durable-state model:
  * canonical run state is ALWAYS re-read from the service
    (get_full_analysis_status / get_full_analysis_result) on every render
    and every poll, so refresh / navigate-away / new browser all
    reconstruct the same view;
  * st.session_state holds presentation details only: the previous poll's
    bot states (to draw one packet per real transition), the last start
    outcome note, and a start-in-flight debounce flag.

Polling: an @st.fragment(run_every=POLL_INTERVAL_SECONDS) re-renders only
the constellation while the run is non-terminal and not stuck; the moment
it is terminal (or stuck) the fragment triggers one full rerun and is not
entered again.
"""
from __future__ import annotations

import streamlit as st

import auth_session
import tenancy
from components import full_analysis_view as fav
from config import api_key_configured, get_api_key

_START_INFLIGHT = "fa_start_inflight_{bid}"
_OUTCOME_NOTE = "fa_outcome_{bid}"
_PREV_BOTS = "fa_prev_bots_{run}"
_ROWS_CACHE = "fa_rows_{run}"
_EXPORT_CACHE = "fa_export_{run}"
EXPORTABLE = (fav.COMPLETE, fav.PARTIAL)


def _ctx():
    session = auth_session.current_session()
    ctx = auth_session.current_auth_context()
    return session["access_token"], ctx.organization_id, getattr(ctx, "user_id", None)


# ═══════════════════════════════════════════════════════════════════════
# Controller (plain functions -- unit-tested with a dict as session)
# ═══════════════════════════════════════════════════════════════════════

def request_start(bid_id: int, organization_id: str, api_key: str | None, session, *,
                  retry: bool = False, user_id: str | None = None) -> dict:
    """The ONLY start path. Calls tenancy.start_full_analysis_for_organization
    (-> full_analysis_service.start_full_analysis) at most once per click:
    a second call while one is in flight in this session returns
    {"outcome": "IN_FLIGHT"} without touching the service. Returns the
    service response (outcome in CREATED / ACTIVE_RUN_EXISTS /
    REUSED_COMPLETE / EXISTING_FAILED / EXISTING_PARTIAL) or {"error": ...}."""
    key = _START_INFLIGHT.format(bid=bid_id)
    if session.get(key):
        return {"outcome": "IN_FLIGHT"}
    session[key] = True
    try:
        response = tenancy.start_full_analysis_for_organization(
            bid_id, organization_id, api_key, created_by_user_id=user_id, retry=retry)
    except tenancy.AccessDeniedError:
        return {"error": "You do not have access to that bid."}
    except Exception as exc:  # includes NoCompleteFastAnalysisError
        name = type(exc).__name__
        if name == "NoCompleteFastAnalysisError":
            return {"error": "Run Fast Analysis to completion first. Full Bid Intelligence builds on its canonical package."}
        return {"error": f"Could not start Full Analysis: {exc}"}
    finally:
        session[key] = False
    session[_OUTCOME_NOTE.format(bid=bid_id)] = response.get("outcome")
    return response


def load_status(bid_id: int, organization_id: str, run_id: int | None = None) -> dict:
    """{"status": dict|None, "error": str|None}. A transient read failure
    is reported, never acted on (no restart, no state change)."""
    try:
        return {"status": tenancy.get_full_analysis_status_for_organization(
            bid_id, organization_id, run_id), "error": None}
    except tenancy.AccessDeniedError:
        raise
    except Exception as exc:
        return {"status": None, "error": f"{type(exc).__name__}: {exc}"}


def load_rows(bid_id: int, organization_id: str, status: dict, session) -> list:
    """Persisted specialist rows (with effective_status) for the run.
    Re-fetched only when the number of finished specialists changed since
    the cached read -- one extra read per real transition, not per poll."""
    run_id = status.get("run_id")
    finished = sum(1 for s in (status.get("specialists") or {}).values()
                   if (s or {}).get("status") in fav.FINISHED)
    key = _ROWS_CACHE.format(run=run_id)
    cached = session.get(key)
    if cached and cached[0] == finished and not status.get("is_terminal"):
        return cached[1]
    if finished == 0 and not status.get("is_terminal"):
        return []
    try:
        res = tenancy.get_full_analysis_result_for_organization(bid_id, organization_id, run_id) or {}
    except tenancy.AccessDeniedError:
        raise
    except Exception:
        return cached[1] if cached else []
    rows = res.get("specialist_results") or []
    session[key] = (finished, rows)
    return rows


def live_frame(bid_id: int, organization_id: str, session, run_id: int | None = None) -> dict:
    """One poll: durable status -> rows -> view -> packets. Returns
    {"view", "status", "rows", "packets", "error"}."""
    loaded = load_status(bid_id, organization_id, run_id)
    status = loaded["status"]
    if status is None:
        return {"view": None, "status": None, "rows": [], "packets": [], "error": loaded["error"]}
    rows = load_rows(bid_id, organization_id, status, session)
    view = fav.build_view(status, rows)
    prev_key = _PREV_BOTS.format(run=view["run_id"])
    packets = fav.packet_transitions(session.get(prev_key), view["bots"])
    session[prev_key] = dict(view["bots"])
    return {"view": view, "status": status, "rows": rows, "packets": packets, "error": None}


def prepare_export(bid_id: int, organization_id: str, run_id: int, run_status: str | None, session) -> dict:
    """MA-2C: the persisted run as a PDF. {"pdf", "filename"} or {"error"}.
    Only for a terminal COMPLETE/PARTIAL run; goes through tenancy's
    authorized, read-only export wrapper (never a model, never a rerun).
    The rendered bytes are cached per run in this browser session, so
    repeated downloads do not even re-render."""
    if run_status not in EXPORTABLE:
        return {"error": "The report can be exported once the analysis is complete or partial."}
    key = _EXPORT_CACHE.format(run=run_id)
    cached = session.get(key)
    if cached:
        return cached
    try:
        out = tenancy.export_full_analysis_report_for_organization(bid_id, organization_id, run_id)
    except tenancy.AccessDeniedError:
        return {"error": "You do not have access to that analysis."}
    except Exception as exc:
        return {"error": f"Could not build the report: {exc}"}
    session[key] = out
    return out


# ═══════════════════════════════════════════════════════════════════════
# Rendering
# ═══════════════════════════════════════════════════════════════════════

def _api_key():
    if not st.session_state.get("anthropic_api_key") and not api_key_configured():
        return None
    return st.session_state.get("anthropic_api_key") or get_api_key()


def _click_start(bid_id: int, *, retry: bool = False) -> None:
    _, org, user_id = _ctx()
    key = _api_key()
    if key is None:
        st.error("Add your Anthropic API key first (see New Bid page or Settings).")
        return
    resp = request_start(bid_id, org, key, st.session_state, retry=retry, user_id=user_id)
    if resp.get("error"):
        st.error(resp["error"])
        return
    st.rerun()


def _outcome_note(bid_id: int) -> None:
    outcome = st.session_state.pop(_OUTCOME_NOTE.format(bid=bid_id), None)
    kind, text = fav.START_OUTCOME_NOTES.get(outcome, (None, None))
    if text:
        box = {"info": "info-box", "success": "success-box", "warn": "warn-box"}.get(kind)
        if box:
            st.markdown(f'<div class="{box}">{fav.esc(text)}</div>', unsafe_allow_html=True)
        else:  # "caution": amber, never the red failure box (MA-2B.1)
            st.markdown(fav.CSS + fav.render_banner("caution", fav.STATE_MARK[fav.PARTIAL], "Partial result",
                                                    [text]), unsafe_allow_html=True)


def _render_live(bid_id: int) -> None:
    _, org, _ = _ctx()
    frame = live_frame(bid_id, org, st.session_state)
    if frame["error"]:
        st.caption(f"Status read failed ({frame['error']}). Retrying on the next refresh; the analysis is unaffected.")
        return
    view = frame["view"]
    if view is None or not view["live"]:
        st.rerun()  # terminal or stuck: stop polling, render the full page once
        return
    st.markdown(fav.render_constellation(view, frame["packets"]), unsafe_allow_html=True)
    _render_previews(view, frame["rows"])


@st.fragment(run_every=fav.POLL_INTERVAL_SECONDS)
def _poll_live(bid_id: int) -> None:
    _render_live(bid_id)


def _render_previews(view: dict, rows: list) -> None:
    rows_map = fav.rows_by_specialist(rows)
    finished = [sid for sid in fav.SPECIALIST_IDS if view["bots"][sid] in fav.USABLE and sid in rows_map]
    if not finished:
        return
    with st.expander(f"Early findings from {len(finished)} finished specialist(s)"):
        for sid in finished:
            titles = fav.specialist_preview(rows_map[sid])
            partial = " (partial output)" if view["bots"][sid] == fav.PARTIAL else ""
            items = "".join(f"<li>{fav.esc(t)}</li>" for t in titles)
            st.markdown(f'<div style="font-size:.82rem"><strong>{fav.esc(fav.SPECIALIST_NAME[sid])}</strong>'
                        f'{partial}<ul style="margin:.2rem 0 .5rem 1rem">{items}</ul></div>',
                        unsafe_allow_html=True)


def _render_stuck(bid_id: int, view: dict) -> None:
    st.markdown(fav.render_constellation(view), unsafe_allow_html=True)
    st.markdown(fav.render_banner(*fav.overall_banner(view)), unsafe_allow_html=True)
    if st.button("Mark this run as stopped", key=f"fa_mark_stuck_{bid_id}"):
        _, org, _ = _ctx()
        try:
            tenancy.mark_full_analysis_run_stuck_for_organization(bid_id, org, view["run_id"])
        except Exception as exc:
            st.error(f"Could not mark the run as stopped: {exc}")
            return
        st.rerun()


def _render_section(title: str, blurb: str, findings: list, primary: str | None, key: str) -> None:
    st.markdown(f"#### {title}")
    st.caption(blurb)
    if not findings:
        st.markdown('<div style="font-size:.82rem;color:#6E6C66">No findings in this domain.</div>',
                    unsafe_allow_html=True)
        return
    st.markdown("".join(fav.finding_html(f, primary=primary) for f in findings[:12]), unsafe_allow_html=True)
    if len(findings) > 12:
        with st.expander(f"{len(findings) - 12} more"):
            st.markdown("".join(fav.finding_html(f, primary=primary) for f in findings[12:]),
                        unsafe_allow_html=True)
    trace = fav.trace_rows(findings)
    if trace:
        with st.expander("Evidence references"):
            for t, cids, fids in trace:
                refs = ", ".join(cids + fids)
                st.markdown(f'<div style="font-size:.76rem;color:#A9A69D;margin:.15rem 0">'
                            f'<span style="color:#EDEAE3">{fav.esc(t)}</span><br>{fav.esc(refs)}</div>',
                            unsafe_allow_html=True)


def _render_export(bid_id: int, status: dict) -> None:
    """Download the persisted result as the Full Intelligence PDF report."""
    run_id, run_status = status.get("run_id"), status.get("status")
    if run_status not in EXPORTABLE:
        return
    _, org, _ = _ctx()
    key = _EXPORT_CACHE.format(run=run_id)
    if not st.session_state.get(key):
        if st.button("Export Full Intelligence Report (PDF)", key=f"fa_export_{bid_id}_{run_id}"):
            out = prepare_export(bid_id, org, run_id, run_status, st.session_state)
            if out.get("error"):
                st.error(out["error"])
                return
        else:
            st.caption("Builds a PDF from this saved result. It does not re-run the analysis.")
            return
    out = st.session_state[key]
    st.download_button("Download Full Intelligence Report (PDF)", data=out["pdf"], file_name=out["filename"],
                       mime="application/pdf", key=f"fa_dl_{bid_id}_{run_id}", type="primary")


def _render_result(bid_id: int, status: dict) -> None:
    _, org, _ = _ctx()
    try:
        res = tenancy.get_full_analysis_result_for_organization(bid_id, org, status["run_id"]) or {}
    except Exception as exc:
        st.warning(f"Could not load the Full Analysis result ({exc}). Refresh to try again.")
        return
    rows = res.get("specialist_results") or []
    view = fav.build_view(status, rows)
    result = res.get("result") or {}
    grouped = fav.group_result(result, rows)

    st.markdown(fav.render_strip(view["bots"], view["reconciliation"]), unsafe_allow_html=True)
    st.markdown(fav.render_banner(*fav.overall_banner(view, status)), unsafe_allow_html=True)
    _render_export(bid_id, status)

    for sid, title, blurb in fav.RESULT_SECTIONS:
        _render_section(title, blurb, grouped["domains"][sid], sid, f"{bid_id}_{sid}")

    st.markdown("#### Cross-Domain Risks & Gaps")
    st.caption("Reconciled across specialists, plus gaps, ambiguities and items needing human confirmation.")
    for label, items in (("Cross-domain risks", grouped["cross_domain_risks"]),
                         ("Gaps", grouped["gaps"]),
                         ("Ambiguities", grouped["ambiguities"]),
                         ("Needs human confirmation", grouped["human_confirmation"])):
        if not items:
            continue
        with st.expander(f"{label} ({len(items)})", expanded=(label == "Cross-domain risks")):
            st.markdown("".join(fav.finding_html(f) for f in items), unsafe_allow_html=True)
            trace = fav.trace_rows(items)
            if trace:
                st.caption("References: " + "; ".join(
                    f"{t[:60]} → {', '.join(c + f)}" for t, c, f in trace[:40]))
    if grouped["completeness_note"]:
        st.caption(grouped["completeness_note"])


def page_full_analysis(bid_id: int) -> None:
    _, org, _ = _ctx()
    st.markdown("# Full Bid Intelligence")
    st.markdown('<div class="gold-rule"></div>', unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:.84rem;color:#A9A69D;max-width:760px;line-height:1.55">'
        '<strong style="color:#EDEAE3">Fast Analysis</strong> gives a quick, lower-cost orientation. '
        '<strong style="color:#EDEAE3">Full Bid Intelligence</strong> runs six specialist analyses over the '
        'same canonical package, then reconciles them into deeper decision, build and check intelligence.'
        '</div>', unsafe_allow_html=True)
    _outcome_note(bid_id)

    try:
        loaded = load_status(bid_id, org)
    except tenancy.AccessDeniedError:
        st.error("You do not have access to that bid.")
        return
    if loaded["error"]:
        st.warning("Could not read Full Analysis status right now. Refresh to try again; nothing was started.")
        return
    status = loaded["status"]
    inflight = bool(st.session_state.get(_START_INFLIGHT.format(bid=bid_id)))

    if status is None:
        st.markdown('<div class="info-box">No Full Analysis has run for this bid yet. It uses the latest '
                    'completed Fast Analysis as its canonical input and takes about 90 seconds.</div>',
                    unsafe_allow_html=True)
        if st.button("Run Full Analysis", key=f"fa_start_{bid_id}", type="primary", disabled=inflight):
            _click_start(bid_id)
        return

    view = fav.build_view(status)
    if view["live"]:
        _poll_live(bid_id)
        return
    if view["stuck"]:
        _render_stuck(bid_id, view)
        return

    _render_result(bid_id, status)
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    cta = fav.terminal_cta(status.get("status"))
    st.caption(cta["caption"])
    if st.button(cta["label"], key=f"fa_{'retry' if cta['retry'] else 'refresh'}_{bid_id}",
                 type="primary" if cta["primary"] else "secondary", disabled=inflight):
        _click_start(bid_id, retry=cta["retry"])
