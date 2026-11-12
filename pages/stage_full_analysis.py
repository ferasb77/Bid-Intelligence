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

import re

import streamlit as st

import auth_session
import phoenix_reports as pr
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


def prepare_export(bid_id: int, organization_id: str, run_id: int, run_status: str | None, session,
                   variant: str = "") -> dict:
    """Phoenix: the FULL "Bid Opportunity Assessment" PDF for the persisted
    run. {"pdf", "filename"} or {"error"}. `variant` (the Buyer Intelligence
    research state) is part of the cache key so the report is rebuilt once
    research completes.
    Only for a terminal COMPLETE/PARTIAL run; goes through tenancy's
    authorized, read-only export wrapper (never a model, never a rerun).
    The rendered bytes are cached per run in this browser session, so
    repeated downloads do not even re-render."""
    if run_status not in EXPORTABLE:
        return {"error": "The report can be exported once the analysis is complete or partial."}
    key = _EXPORT_CACHE.format(run=run_id) + (f"_{variant}" if variant else "")
    cached = session.get(key)
    if cached:
        return cached
    try:
        out = tenancy.export_bid_opportunity_assessment_for_organization(bid_id, organization_id, run_id)
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
    if not auth_session.session_access_still_valid():
        st.rerun()  # full app run: app.py's revalidation signs the user out
        return
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


def _ensure_research(bid_id: int, run_id: int) -> dict | None:
    """Research state for this FULL run. The first time a result without
    research is opened in this session, completed research of the same bid is
    reused or one background search is started (never blocks the page)."""
    _, org, _ = _ctx()
    flag = f"fa_research_ensured_{bid_id}_{run_id}"
    try:
        if not st.session_state.get(flag):
            st.session_state[flag] = True
            return tenancy.ensure_buyer_research_for_organization(bid_id, org, run_id, _api_key())
        return tenancy.get_buyer_research_for_organization(bid_id, org, run_id)
    except Exception:
        return None


def _render_buyer_research(bid_id: int, run_id: int, research: dict | None) -> str:
    """Buyer Intelligence (bounded web research) status for this FULL run;
    returns the research state used as the report cache variant."""
    _, org, _ = _ctx()
    state = (research or {}).get("status") or "NONE"
    if state == "COMPLETE":
        n = len(research.get("items") or [])
        st.caption(f"Buyer Intelligence: {n} verified external source(s) included in the assessment."
                   if n else "Buyer Intelligence: research completed; no verifiable public sources were found.")
    elif state == "RUNNING":
        st.caption("Buyer Intelligence web research is running in the background (about 1–2 minutes); "
                   "this panel refreshes automatically and the assessment is rebuilt when it completes.")
    else:
        note = {"FAILED": "Buyer Intelligence research did not complete.",
                "SKIPPED": "Buyer Intelligence research needs the issuing organization (Opportunity details)."
                }.get(state, "Buyer Intelligence web research has not been run for this analysis "
                             "(an Anthropic API key is needed to start it).")
        c1, c2 = st.columns([3, 1.4])
        c1.caption(note)
        if c2.button("Run buyer research", key=f"fa_research_{bid_id}_{run_id}"):
            key = _api_key()
            if key is None:
                st.error("Add your Anthropic API key first (see New Bid page or Settings).")
            else:
                try:
                    tenancy.start_buyer_research_for_organization(bid_id, org, run_id, key)
                except Exception as exc:
                    st.error(f"Could not start buyer research: {exc}")
                st.rerun()
    return f"{state}_{(research or {}).get('researched_at') or ''}"


def _render_export(bid_id: int, status: dict) -> None:
    """The FULL stage presents one PDF: the Bid Opportunity Assessment."""
    run_id, run_status = status.get("run_id"), status.get("status")
    if run_status not in EXPORTABLE:
        return
    _, org, _ = _ctx()
    research = _ensure_research(bid_id, run_id)
    running = (research or {}).get("status") == "RUNNING"

    def body():
        current = research
        if running:
            try:
                current = tenancy.get_buyer_research_for_organization(bid_id, org, run_id)
            except Exception:
                current = research
            if (current or {}).get("status") != "RUNNING":
                st.rerun()  # research finished: leave the polling fragment
        variant = _render_buyer_research(bid_id, run_id, current)
        out = prepare_export(bid_id, org, run_id, run_status, st.session_state, variant)
        if out.get("error"):
            st.error(out["error"])
            return
        st.download_button("⬇ Download Bid Opportunity Assessment (PDF)", data=out["pdf"],
                           file_name=out["filename"], mime="application/pdf",
                           key=f"fa_dl_{bid_id}_{run_id}", type="primary")

    if running:
        st.fragment(run_every=10)(body)()  # poll while the background research runs
    else:
        body()


RESULT_TABS = ("Overview", "Requirements", "Evaluation", "Commercial", "Buyer Intelligence", "Detailed Findings")
_FACTS_CACHE = "fa_facts_{run}"
# Specialist text that asserts information is missing is never shown as a
# verified fact (the documents often state it; an empty AI field is not absence).
_ABSENCE = (r"(not specified|not stated|not provided|not defined|\babsent\b|\bmissing\b|"
                      r"does not (state|specify|include)|no (evaluation|submission|payment) )")


def load_facts(bid_id: int, organization_id: str, run_id: int, session) -> dict:
    """{"facts"} or {"error"}: the verified fact model shared with the PDF
    (document text read once per run per session; errors are not cached)."""
    key = _FACTS_CACHE.format(run=run_id)
    if key in session:
        return session[key]
    try:
        out = {"facts": tenancy.get_full_analysis_facts_for_organization(bid_id, organization_id, run_id)}
    except Exception as exc:
        return {"error": str(exc)}
    session[key] = out
    return out


def _ref(item) -> str:
    r = pr.ref_text(item) if item else ""
    return f' <span style="color:#8C8A84;font-size:.74rem">[{fav.esc(r)}]</span>' if r else ""


def _heading(text: str) -> None:
    st.markdown(f'<div style="font-size:.9rem;color:#C9A96E;margin:.9rem 0 .25rem">{fav.esc(text)}</div>',
                unsafe_allow_html=True)


def _facts_list(items: list, n: int = 220) -> None:
    if not items:
        return
    lis = "".join(f'<li style="margin:.12rem 0">{fav.esc(pr.brief(it["text"], n))}{_ref(it)}</li>' for it in items)
    st.markdown(f'<ul style="font-size:.84rem;margin:.1rem 0 .4rem 1.1rem;line-height:1.45">{lis}</ul>',
                unsafe_allow_html=True)


def _kv_table(rows: list) -> None:
    if not rows:
        return
    trs = "".join(f'<tr><td style="color:#A9A69D;padding:.3rem .8rem .3rem 0;vertical-align:top;white-space:nowrap">'
                  f'{fav.esc(k)}</td><td style="padding:.3rem 0;vertical-align:top">{v}</td></tr>' for k, v in rows)
    st.markdown(f'<table style="font-size:.84rem;border-collapse:collapse;width:100%">{trs}</table>',
                unsafe_allow_html=True)


def _deadline_html(f: dict) -> str:
    d = f["deadline"]
    if d["manual"]:
        out = (f"<strong>{fav.esc(pr.fmt_date(d['manual']))}</strong> — manually entered by a Phoenix user"
               + (f"; documents state {fav.esc(pr.fmt_date(d['extracted']))}{_ref(d['extracted_ref'])}"
                  if d["extracted"] else ""))
    elif d["extracted"]:
        out = f"<strong>{fav.esc(pr.fmt_date(d['extracted']))}</strong>{_ref(d['extracted_ref'])}"
    else:
        return ""
    if d["amended_from"]:
        out += (f'<br><span style="color:#D9A441">Updated</span> — previously '
                f'{fav.esc(pr.fmt_date(d["amended_from"]["value"]))}{_ref(d["amended_from"]["ref"])}')
    return out


def _tab_overview(bid_id: int, status: dict, view: dict, f: dict | None) -> None:
    st.markdown(fav.render_strip(view["bots"], view["reconciliation"]), unsafe_allow_html=True)
    st.markdown(fav.render_banner(*fav.overall_banner(view, status)), unsafe_allow_html=True)
    _render_export(bid_id, status)  # PDF download + Buyer Intelligence state (starts/reuses research)
    if not f:
        return
    _, org, _ = _ctx()
    try:
        research = tenancy.get_buyer_research_for_organization(bid_id, org, status["run_id"])
    except Exception:
        research = None
    _heading("Executive summary")
    ident, rows = f["identity"], []
    if ident.get("organization"):
        rows.append(("Buyer", fav.esc(ident["organization"])))
    if ident.get("reference"):
        rows.append(("Reference", fav.esc(ident["reference"])))
    if _deadline_html(f):
        rows.append(("Submission deadline", _deadline_html(f)))
    if f["synopsis"]:
        rows.append(("Synopsis", fav.esc(" ".join(s["text"] for s in f["synopsis"])) + _ref(f["synopsis"][0])))
    top = [c for c in f["criteria"] if c["level"] == 0 and c["weight"]]
    if top:
        rows.append(("Evaluation basis", fav.esc(" / ".join(f"{c['stage']} {c['weight']}" for c in top))
                     + _ref(top[0]["ref"])))
    if f["pricing"]:
        p = f["pricing"][0]
        rows.append(("Pricing basis", fav.esc(pr.brief(p["text"], 200)) + _ref(p)))
    if f["changes"]:
        k = {kind: sum(1 for c in f["changes"] if c["kind"] == kind) for kind in ("NEW", "UPDATED", "CONFLICT")}
        rows.append(("Changes in later documents",
                     fav.esc(", ".join(f"{v} {kk.lower()}" for kk, v in k.items() if v)) + " — see Commercial"))
    rows.append(("External buyer research", fav.esc(pr._research_status_line(research).replace("section 3", "see Buyer Intelligence"))))
    _kv_table(rows)


def _tab_requirements(f: dict) -> None:
    groups = pr._groups(f["scope"])
    if groups:
        _heading("Scope of work")
        for g in groups:
            if g["heading"]:
                st.markdown(f'<div style="font-size:.82rem;color:#EDEAE3;margin-top:.3rem">{fav.esc(g["heading"])}</div>',
                            unsafe_allow_html=True)
            _facts_list(g["items"])
    for title, key in (("Workflow and timeline", "timeline"), ("Deliverables", "deliverables"),
                       ("Stated quantities and durations", "quantities"), ("Qualifications sought", "qualifications"),
                       ("General requirements", "general")):
        items = [it for it in f[key] if not (key == "timeline" and pr._is_subhead(it["text"]))]
        if items:
            _heading(title)
            _facts_list(items)
    if f["required_docs"]:
        _heading("Required submission documents")
        _facts_list([dict(d, text=d["name"] + (": " + "; ".join(x["text"].rstrip(".") for x in d["details"])
                                               if d["details"] else "")) for d in f["required_docs"]], n=400)


def _tab_evaluation(f: dict) -> None:
    if f["criteria"]:
        _heading("Evaluation criteria and weights")
        trs = []
        for c in f["criteria"]:
            name = fav.esc(c["stage"])
            name = (f'<span style="padding-left:{1.2 * c["level"]}rem">— {name}</span>' if c["level"]
                    else f"<strong>{name}</strong>")
            w = fav.esc(c["weight"] or "—")
            if c["level"] and c["weight"] and c.get("basis") == "within":
                w += f' <span style="color:#8C8A84">of {fav.esc(c["parent"])}</span>'
            trs.append(f'<tr><td style="padding:.3rem .6rem .3rem 0">{name}</td>'
                       f'<td style="padding:.3rem .6rem;white-space:nowrap">{w}</td>'
                       f'<td style="padding:.3rem 0;color:#8C8A84;font-size:.74rem">{fav.esc(pr.ref_text(c["ref"]))}</td></tr>')
        st.markdown('<table style="font-size:.84rem;border-collapse:collapse;width:100%">'
                    '<tr style="color:#A9A69D"><td>Criterion</td><td style="padding:0 .6rem">Weight</td><td>Source</td></tr>'
                    + "".join(trs) + "</table>", unsafe_allow_html=True)
        notes = []
        for p in f["criteria"]:
            if p.get("children_basis") == "overall":
                kids = [c for c in f["criteria"] if c["level"] and c.get("parent") == p["stage"]]
                notes.append(f"{p['stage']} {p['weight']} = " + " + ".join(str(k["weight"]) for k in kids))
        if notes:
            st.caption("Sub-criterion weights are shares of the total score, as their sums show: " + "; ".join(notes) + ".")
    elif f["eval_text"]:
        _heading("Evaluation criteria and weights")
        _facts_list(f["eval_text"])
    evidence = [dict(x, text=f"{d['name']}: {x['text']}") for d in f["required_docs"]
                if not pr._PRICING.search(d["name"]) for x in d["details"]]
    if evidence:
        _heading("What the proposal must contain")
        _facts_list(evidence)
    if not (f["criteria"] or f["eval_text"] or evidence):
        st.caption("No evaluation section could be located in the document text; see the source documents.")


def _tab_commercial(f: dict) -> None:
    for title, key, n in (("Pricing", "pricing", 240), ("Budget (as stated)", "budget", 240),
                          ("Payment terms", "payment", 300)):
        if f[key]:
            _heading(title)
            _facts_list(f[key], n)
    if f["clauses"]:
        _heading("Material contract terms")
        _facts_list([{"text": c["text"], **(c["ref"] or {})} for c in f["clauses"]])
    sub, rows = f["submission"], []
    if sub.get("channel"):
        ms = (sub.get("method_sentences") or [None])[0]
        rows.append(("Method", f"<strong>{fav.esc(sub['channel'])}</strong>"
                     + (" to " + ", ".join(fav.esc(e["email"]) for e in sub["emails"]) if sub.get("emails") else "")
                     + _ref(ms)))
    if pr._subject_text(sub):
        rows.append(("Subject line", fav.esc(pr._subject_text(sub)) + _ref(sub["subject_rule"])))
    if pr._late_text(sub):
        rows.append(("Late submissions", fav.esc(pr._late_text(sub)) + _ref(sub["late_rule"])))
    if _deadline_html(f):
        rows.append(("Deadline", _deadline_html(f)))
    for k in f["key_dates"]:
        rows.append((k["label"], fav.esc(pr.fmt_date(k["value"])) + _ref(k["ref"])))
    if rows:
        _heading("Submission")
        _kv_table(rows)
    if f["changes"]:
        _heading("Changes introduced by later documents")
        color = {"NEW": "#7FBF94", "UPDATED": "#D9A441", "CONFLICT": "#E07A6B"}
        label = {"NEW": "New information", "UPDATED": "Updated information", "CONFLICT": "Unresolved conflict"}
        lis = []
        for c in f["changes"]:
            cur = pr.fmt_date(c["current"]) if c["topic"] == "Submission deadline" else pr.brief(str(c["current"]), 260)
            prev = ""
            if c.get("previous"):
                pv = pr.fmt_date(c["previous"]) if c["topic"] == "Submission deadline" else pr.brief(str(c["previous"]), 200)
                prev = f" — previously {fav.esc(pv)}{_ref(c.get('supersedes'))}"
            lis.append(f'<li><span style="color:{color.get(c["kind"], "#A9A69D")}">{label.get(c["kind"], c["kind"])}</span> · '
                       f'{fav.esc(c["topic"])}: {fav.esc(cur)}{_ref(c.get("source"))}{prev}</li>')
        st.markdown(f'<ul style="font-size:.84rem;margin:.1rem 0 .4rem 1.1rem">{"".join(lis)}</ul>', unsafe_allow_html=True)
    if f["workbooks"]:
        _heading("Spreadsheets in the package")
        lis = []
        for wb in f["workbooks"]:
            purpose = fav.esc(wb["purpose"]) if wb.get("purpose") else "purpose unconfirmed"
            link = wb.get("references") or []
            ref = (f" — {'referenced in' if link[0]['status'] == 'linked' else 'possible reference in'} "
                   f"{fav.esc(pr.ref_text(link[0]))}") if link else " — link to RFP/addendum unconfirmed"
            lis.append(f"<li><strong>{fav.esc(wb['name'])}</strong>: {purpose}{ref}</li>")
        st.markdown(f'<ul style="font-size:.84rem;margin:.1rem 0 .4rem 1.1rem">{"".join(lis)}</ul>', unsafe_allow_html=True)


def _tab_buyer(f: dict | None, research: dict | None) -> None:
    if f and f["about"]:
        _heading("As stated in the procurement documents")
        _facts_list([dict(it, text=(pr.sentences_of(it["text"]) or [it["text"]])[0]) for it in f["about"]], 300)
    _heading("External sources")
    state = (research or {}).get("status") or "NONE"
    items = (research or {}).get("items") or []
    if state != "COMPLETE" or not items:
        st.caption({"RUNNING": "Web research is in progress; the Overview tab refreshes automatically.",
                    "FAILED": "Web research did not complete; it can be re-run from the Overview tab.",
                    "SKIPPED": "Web research needs the issuing organization (Understand → Opportunity details).",
                    "COMPLETE": "Web research completed; no public sources could be verified as being about this buyer."
                    }.get(state, "Web research has not been run for this analysis yet."))
        return
    st.caption(f"Public sources found by targeted web research on "
               f"{pr.fmt_date(str(research.get('researched_at') or '')[:10])}. External facts about the buyer, separate "
               "from the procurement requirements; a connection is shown only where the source itself states it.")
    for it in items:
        conn = it.get("connection")
        st.markdown(
            f'<div style="font-size:.84rem;margin:.45rem 0;padding:.45rem .7rem;border-left:2px solid #C9A96E">'
            f'{fav.esc(it["statement"])}'
            f'<div style="color:#A9A69D;font-size:.78rem;margin-top:.15rem">'
            f'{("Connection: " + fav.esc(conn)) if conn else "Background on the buyer"}</div>'
            f'<div style="font-size:.74rem;margin-top:.15rem"><a href="{fav.esc(it["url"])}" target="_blank">'
            f'{fav.esc(pr.clip(it.get("source_title") or it["url"], 90))}</a> · '
            f'<span style="color:#8C8A84">{fav.esc(it.get("published") or "undated")}</span></div></div>',
            unsafe_allow_html=True)


def _grounded(findings: list) -> list:
    """Only document-grounded findings: canonical authority, with evidence
    references, and not a claim that information is missing."""
    return [x for x in findings
            if x.get("authority") == "CANONICAL" and (x.get("canonical_ids") or x.get("finding_ids"))
            and not re.search(_ABSENCE, f"{x.get('title') or ''} {x.get('detail') or ''}", re.I)]


def _tab_detailed(bid_id: int, grouped: dict) -> None:
    st.caption("Additional source-grounded findings from the specialist analyses, each tied to canonical evidence. "
               "Specialist interpretations, risk assessments and gap claims are working notes and are not shown "
               "here as verified facts.")
    shown = 0
    for sid, title, blurb in fav.RESULT_SECTIONS:
        items = _grounded(grouped["domains"][sid])
        if not items:
            continue
        shown += len(items)
        with st.expander(f"{title} ({len(items)})"):
            st.caption(blurb)
            st.markdown("".join(fav.finding_html(x, primary=sid) for x in items), unsafe_allow_html=True)
            st.caption("Evidence: " + "; ".join(f"{t[:60]} → {', '.join(c + i)}"
                                                 for t, c, i in fav.trace_rows(items)[:40]))
    if not shown:
        st.caption("The specialist analyses produced no additional document-grounded findings beyond the facts in "
                    "the other tabs.")
    if grouped["completeness_note"]:
        st.caption(grouped["completeness_note"])


def _render_result(bid_id: int, status: dict) -> None:
    _, org, _ = _ctx()
    try:
        res = tenancy.get_full_analysis_result_for_organization(bid_id, org, status["run_id"]) or {}
    except Exception as exc:
        st.warning(f"Could not load the Full Analysis result ({exc}). Refresh to try again.")
        return
    rows = res.get("specialist_results") or []
    view = fav.build_view(status, rows)
    grouped = fav.group_result(res.get("result") or {}, rows)
    facts = None
    if status.get("status") in EXPORTABLE:
        loaded = load_facts(bid_id, org, status["run_id"], st.session_state)
        facts = loaded.get("facts")
        if facts:
            pr._set_alias(facts)
    tabs = st.tabs(list(RESULT_TABS))
    with tabs[0]:
        _tab_overview(bid_id, status, view, facts)
    if not facts:
        msg = ("The verified document facts could not be loaded right now; refresh to try again."
               if status.get("status") in EXPORTABLE else
               "Verified document facts are shown once the Full Analysis completes.")
        for t in tabs[1:5]:
            with t:
                st.caption(msg)
    else:
        with tabs[1]:
            _tab_requirements(facts)
        with tabs[2]:
            _tab_evaluation(facts)
        with tabs[3]:
            _tab_commercial(facts)
    if facts:
        with tabs[4]:
            try:
                research = tenancy.get_buyer_research_for_organization(bid_id, org, status["run_id"])
            except Exception:
                research = None
            _tab_buyer(facts, research)
    with tabs[5]:
        _tab_detailed(bid_id, grouped)


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
