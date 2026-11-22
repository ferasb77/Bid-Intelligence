"""Evidence-Based Analysis -- the dual-analyst intelligence engine for one bid.

Every read/write goes through tenancy's engine wrappers (organization
ownership verified first). This page renders persisted state only and makes
no model call of its own.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import auth_session
import tenancy

POLL_SECONDS = 10
_VERIFY_TEXT = {
    "INDEPENDENTLY_VERIFIED": ("✅", "Independently verified by two analysts"),
    "VERIFIED_WITH_LIMITATIONS": ("🟠", "Dual-analyst analysis with limitations"),
    "SINGLE_ANALYST": ("🟠", "Single-analyst analysis (not independently confirmed)"),
    "SYNTHETIC": ("🧪", "Synthetic development run"),
    "FAILED": ("⛔", "Failed"),
}


def _org() -> tuple[str, str | None]:
    ctx = auth_session.current_auth_context()
    return ctx.organization_id, getattr(ctx, "user_id", None)


def _items_table(sec: dict) -> list[dict]:
    rows = []
    for g in sec.get("groups") or [{"title": "", "items": sec.get("items") or []}]:
        for it in g.get("items") or []:
            rows.append({"Topic": g.get("title") or sec["title"], "Provision": it["text"],
                         "Source": "; ".join(it.get("refs") or []), "Flags": ", ".join(it.get("labels") or []),
                         "Entries": ", ".join(it["entry_ids"])})
    return rows


def _render_report(rep: dict) -> None:
    ver = rep.get("verification") or {}
    icon, label = _VERIFY_TEXT.get(ver.get("status"), ("", ver.get("status")))
    st.info(f"{icon} {label}. {ver.get('text', '')}")
    for lim in ver.get("limitations") or []:
        st.caption(f"• {lim}")
    for k, v in rep.get("identity") or []:
        st.markdown(f"**{k}:** {v}")
    if rep.get("summary"):
        st.write(" ".join(rep["summary"]))
    for sec in rep["sections"]:
        st.subheader(sec["title"])
        if sec.get("items") or sec.get("groups"):
            st.dataframe(pd.DataFrame(_items_table(sec)), use_container_width=True, hide_index=True)
        if sec.get("analysis"):
            st.caption("Analysis grounded in the cited provisions -- interpretation, not a document fact.")
            for p in sec["analysis"]:
                st.markdown(f"- **{p['heading']}** ({p.get('kind', '').title()}): {p['analysis']} "
                            f"_[{'; '.join(p.get('refs') or [])}]_")
        if "research" in sec:
            items = (sec["research"] or {}).get("items") or []
            if not items:
                st.caption("No verified external buyer facts for this analysis.")
            for it in items:
                st.markdown(f"- {it.get('statement')} _({it.get('url', '')[:80]})_")


_PANEL_LABEL = {"FAST": "Opportunity Snapshot", "FULL": "Bid Opportunity Assessment"}
_PDF_CACHE = "engine_pdf_{bid}_{run}_{kind}"


def render_engine_report_panel(bid_id: int, kind: str, organization_id: str | None = None,
                               user_id: str | None = None) -> bool:
    """Compact engine panel used by the UNDERSTAND (kind="FAST") and Full Bid
    Intelligence (kind="FULL") pages when USE_NEW_ENGINE is on: start/re-run
    the engine, follow its progress, and serve the run's persisted fast.pdf
    or full.pdf. Makes no model call itself (starting a run hands off to the
    engine through tenancy).

    Returns False only when the engine is not available in this environment
    (e.g. engine persistence not applied), so the caller can fall back to the
    legacy flow; True when the panel handled the page."""
    org, user = (organization_id, user_id) if organization_id else _org()
    try:
        status = tenancy.get_engine_status_for_organization(bid_id, org)
    except tenancy.AccessDeniedError:
        st.error("You do not have access to this bid.")
        return True
    except Exception as exc:
        st.caption(f"Evidence-based engine unavailable here ({type(exc).__name__}); showing the legacy analysis.")
        return False

    active = bool(status and status.get("status") in ("QUEUED", "RUNNING"))
    label = _PANEL_LABEL[kind]
    if st.button("⚡ Run analysis" if not status else "🔁 Re-run on current package", disabled=active,
                 type="primary" if not status else "secondary", key=f"engine_start_{kind}_{bid_id}"):
        try:
            tenancy.start_engine_analysis_for_organization(bid_id, org, created_by=user)
            st.rerun()
        except Exception as exc:
            st.error(f"Could not start the analysis: {exc}")
    if not status:
        st.markdown('<div class="info-box">No analysis has run for this bid yet. One run produces both the '
                    'Opportunity Snapshot (FAST) and the Bid Opportunity Assessment (FULL).</div>',
                    unsafe_allow_html=True)
        return True

    run_id = int(status["id"])
    st.caption(f"Run {run_id} · {status['status']} · started {str(status.get('started_at') or '')[:19]}")
    if active:
        if status.get("possibly_interrupted"):
            st.warning("This run has made no progress for 15 minutes and may have been interrupted.")
            if st.button("Close interrupted run", key=f"engine_close_{kind}_{bid_id}"):
                tenancy.close_interrupted_engine_run_for_organization(bid_id, org, run_id)
                st.rerun()
        else:
            st.info("Analysis in progress. This page refreshes automatically.")

            @st.fragment(run_every=POLL_SECONDS)
            def _poll():
                s = tenancy.get_engine_status_for_organization(bid_id, org, run_id)
                if s and s.get("status") not in ("QUEUED", "RUNNING"):
                    st.rerun()
            _poll()
        return True
    if status["status"] != "COMPLETE":
        st.error(f"The analysis failed: {status.get('failure_reason') or 'unknown error'}. No report was produced.")
        return True

    ver = status.get("verification")
    icon, text = _VERIFY_TEXT.get(ver, ("", ver or ""))
    if text:
        st.caption(f"{icon} {text}")
    key = _PDF_CACHE.format(bid=bid_id, run=run_id, kind=kind)
    data = st.session_state.get(key)
    if data is None:
        try:
            data = tenancy.export_engine_pdf_for_organization(bid_id, org, run_id, kind)
        except Exception as exc:  # never break the page over an export
            st.caption(f"{label} is unavailable: {exc}")
            return True
        if data:
            st.session_state[key] = data
    if data:
        st.download_button(f"⬇ Download {label} (PDF)", data=data,
                           file_name=f"bid{bid_id}_{kind.lower()}_run{run_id}.pdf", mime="application/pdf",
                           key=f"engine_dl_{kind}_{bid_id}_{run_id}", type="primary", use_container_width=True)
    else:
        st.caption(f"{label} PDF is not available for this run.")
    return True


def page_engine(bid_id: int) -> None:
    st.title("🔬 Evidence-Based Analysis")
    st.caption("Two independent analysts read the complete package; findings are reconciled into an evidence "
               "register, adjudicated against the source, checked for conflicts and amendments, and reviewed "
               "before the FAST and FULL reports are produced.")
    org, user = _org()
    try:
        status = tenancy.get_engine_status_for_organization(bid_id, org)
    except tenancy.AccessDeniedError:
        st.error("You do not have access to this bid.")
        return
    except Exception as exc:
        st.warning(f"The analysis engine is not available in this environment: {exc}")
        return
    active = status and status.get("status") in ("QUEUED", "RUNNING")
    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button("Run analysis" if not status else "Re-run on current package", disabled=bool(active),
                     type="primary"):
            try:
                tenancy.start_engine_analysis_for_organization(bid_id, org, created_by=user)
                st.rerun()
            except Exception as exc:
                st.error(f"Could not start: {exc}")
    if not status:
        st.info("No evidence-based analysis has been run for this bid yet.")
        return
    with c2:
        st.caption(f"Run {status['id']} · {status['status']} · started {str(status.get('started_at') or '')[:19]}")
    if active:
        if status.get("possibly_interrupted"):
            st.warning("This run has made no progress for 15 minutes and may have been interrupted.")
            if st.button("Close interrupted run"):
                tenancy.close_interrupted_engine_run_for_organization(bid_id, org, int(status["id"]))
                st.rerun()
        else:
            st.info("Analysis in progress. This page refreshes automatically.")

            @st.fragment(run_every=POLL_SECONDS)
            def _poll():
                s = tenancy.get_engine_status_for_organization(bid_id, org, int(status["id"]))
                if s and s.get("status") not in ("QUEUED", "RUNNING"):
                    st.rerun()
            _poll()
        return
    if status["status"] == "FAILED":
        st.error(f"The analysis failed: {status.get('failure_reason') or 'unknown error'}. No report was produced.")
        return
    run_id = int(status["id"])
    res = tenancy.get_engine_result_for_organization(bid_id, org, run_id) or {}
    composed = res.get("composed") or {}
    d1, d2 = st.columns(2)
    for col, kind, label in ((d1, "FAST", "Opportunity Snapshot"), (d2, "FULL", "Bid Opportunity Assessment")):
        with col:
            data = tenancy.export_engine_pdf_for_organization(bid_id, org, run_id, kind)
            if data:
                st.download_button(f"⬇ {label} (PDF)", data=data, file_name=f"bid{bid_id}_{kind.lower()}_run{run_id}.pdf",
                                   mime="application/pdf", use_container_width=True)
    t_fast, t_full, t_reg, t_conf, t_run = st.tabs(["FAST", "FULL", "Evidence register", "Conflicts & amendments",
                                                    "Coverage & run record"])
    with t_fast:
        if composed.get("fast"):
            _render_report(composed["fast"])
    with t_full:
        if composed.get("full"):
            _render_report(composed["full"])
    with t_reg:
        entries = (res.get("register") or {}).get("entries") or []
        df = pd.DataFrame([{"Entry": e["entry_id"], "Category": e.get("category"), "Force": e.get("modality"),
                            "Materiality": e.get("materiality"), "Status": e.get("status"),
                            "Applies": e.get("applicability"), "Statement": e.get("statement"),
                            "Quote": e.get("quote"), "Source": f"{e.get('document')} {e.get('page')}"}
                           for e in entries])
        if not df.empty:
            cats = st.multiselect("Category", sorted(df["Category"].dropna().unique()))
            st.dataframe(df[df["Category"].isin(cats)] if cats else df, use_container_width=True, hide_index=True)
    with t_conf:
        conf = res.get("conflicts") or {}
        for a in conf.get("amendments") or []:
            st.markdown(f"- **Amendment** {a.get('issue')}: {a['prevailing']} replaces {', '.join(a['superseded'])} "
                        f"— “{a.get('authority_quote')}” [{a.get('authority_ref')}]")
        for c in conf.get("conflicts") or []:
            st.markdown(f"- **Unresolved** {c.get('issue')} ({', '.join(c['entry_ids'])}). "
                        f"Question: {c.get('clarification_question') or '—'}")
        if not conf.get("amendments") and not conf.get("conflicts"):
            st.caption("No conflicts or amendments were identified.")
    with t_run:
        rec = res.get("record") or {}
        st.json({"verification": rec.get("verification"), "limitations": rec.get("limitations"),
                 "models": rec.get("models"), "stages": rec.get("stages"), "usage": rec.get("usage"),
                 "readability": (res.get("package") or {}).get("readability"),
                 "documents": (res.get("package") or {}).get("documents")}, expanded=False)
        ledger = composed.get("ledger") or {}
        st.caption(f"Omission ledger: {'complete' if ledger.get('complete') else 'violations: ' + ', '.join(ledger.get('violations') or [])}")
