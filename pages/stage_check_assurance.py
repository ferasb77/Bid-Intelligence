"""
CHECK: Proposal Assurance workspace (CHECK-2C) -- the first client-facing
view of the durable CHECK-2B result for one bid.

Reached from the active-bid sidebar ("CHECK: Proposal Assurance",
page == "stage_check_assurance") and from the existing CHECK page.

Hard rule: this page RENDERS the persisted CHECK run. It never imports or
calls check_coverage.py's adjudication core, never calls a model, and
never starts work on its own. Every read goes through tenancy's CHECK-2B
wrappers (get_check_run_status_for_organization /
get_check_run_result_for_organization) and CHECK-1.1's read-only
load_submission_evidence_package_for_organization (bounded evidence
excerpts from the bid's own registry). The ONLY execution path is an
explicit click on "Run CHECK" / "Run CHECK again", which calls
tenancy.start_check_run_for_organization and therefore inherits CHECK-2B's
five start outcomes (CREATED / ACTIVE_RUN_EXISTS / REUSED_COMPLETE /
EXISTING_FAILED / EXISTING_PARTIAL) unchanged -- identical inputs reuse the
existing COMPLETE run with zero model calls.

Durable-state model: the run status is re-read from persistence on every
render (truthful header, never inferred from result rows). A terminal
run's adjudications + evidence index are immutable, so they are cached in
st.session_state per (bid, run) -- filters, tabs, expanders and reruns
re-render from that cache without touching the database again.
"""
from __future__ import annotations

import streamlit as st

import auth_session
import tenancy
from components import check_workspace_view as cwv
from config import api_key_configured, get_api_key

_START_INFLIGHT = "chk_start_inflight_{bid}"
_OUTCOME_NOTE = "chk_outcome_{bid}"
_BUNDLE = "chk_bundle_{bid}_{run}"
#: Every session key this page writes starts with this (app.py clears them on logout).
SESSION_PREFIX = "chk_"
POLL_INTERVAL_SECONDS = 5
ATTENTION_SHOWN = 8


def _ctx():
    session = auth_session.current_session()
    ctx = auth_session.current_auth_context()
    return session["access_token"], ctx.organization_id, getattr(ctx, "user_id", None)


# ═══════════════════════════════════════════════════════════════════════
# Controller (plain functions -- unit-tested with a dict as session)
# ═══════════════════════════════════════════════════════════════════════

def load_status(bid_id: int, organization_id: str) -> dict:
    """{"status": dict|None, "error": str|None} for the bid's latest CHECK
    run (any status). Access denial propagates; a transient read failure is
    reported, never acted on."""
    try:
        return {"status": tenancy.get_check_run_status_for_organization(bid_id, organization_id), "error": None}
    except tenancy.AccessDeniedError:
        raise
    except Exception as exc:
        return {"status": None, "error": f"{type(exc).__name__}: {exc}"}


def load_bundle(bid_id: int, organization_id: str, run_id: int | None, session) -> dict:
    """The persisted adjudication of `run_id` (None = the service default:
    latest COMPLETE, else latest PARTIAL), plus a bounded evidence index
    resolved in THIS bid's persisted submission registry. Zero provider
    calls. Cached per (bid, run): a terminal CHECK run is immutable."""
    if run_id is not None:
        cached = session.get(_BUNDLE.format(bid=bid_id, run=run_id))
        if cached:
            return cached
    try:
        res = tenancy.get_check_run_result_for_organization(bid_id, organization_id, run_id)
    except tenancy.AccessDeniedError:
        raise
    except Exception as exc:
        return {"error": f"Could not load the CHECK result ({type(exc).__name__}: {exc})."}
    if not res or res.get("result") is None:
        return {"error": "No persisted CHECK result is available for this run."}
    run = res["run"]
    if int(run.get("bid_id")) != int(bid_id):  # defence in depth; the service already checks
        raise tenancy.AccessDeniedError("CHECK run does not belong to this bid")
    adjs = cwv.adjudications(res["result"])
    index, files, evidence_error = {}, [], None
    snapshot_id = run.get("source_package_snapshot_id")
    if snapshot_id is not None:
        try:
            package = tenancy.load_submission_evidence_package_for_organization(bid_id, organization_id,
                                                                                int(snapshot_id))
            ids = [e for a in adjs for e in cwv.cited_evidence_ids(a)]
            index = cwv.build_evidence_index(package, bid_id, ids)
            files = cwv.submitted_files(package)
        except tenancy.AccessDeniedError:
            raise
        except Exception as exc:
            evidence_error = f"{type(exc).__name__}: {exc}"
    bundle = {"run": run, "run_id": run.get("id"), "run_status": run.get("status"), "adjs": adjs,
              "index": index, "files": files, "payload": res.get("result_payload") or {},
              "digest_verified": bool(res.get("result_digest_verified")), "evidence_error": evidence_error,
              "error": None}
    if run.get("status") in cwv.TERMINAL_RUN and not evidence_error:
        session[_BUNDLE.format(bid=bid_id, run=run.get("id"))] = bundle
    return bundle


def request_start(bid_id: int, organization_id: str, api_key: str | None, session, *,
                  retry: bool = False, user_id: str | None = None) -> dict:
    """The ONLY execution path, reached only by an explicit click. Calls
    tenancy.start_check_run_for_organization (CHECK-2B semantics unchanged)
    at most once per click; a second call while one is in flight returns
    {"outcome": "IN_FLIGHT"} without touching the service."""
    key = _START_INFLIGHT.format(bid=bid_id)
    if session.get(key):
        return {"outcome": "IN_FLIGHT"}
    session[key] = True
    try:
        response = tenancy.start_check_run_for_organization(
            bid_id, organization_id, created_by_user_id=user_id, retry=retry, api_key=api_key)
    except tenancy.AccessDeniedError:
        return {"error": "You do not have access to that bid."}
    except Exception as exc:
        if type(exc).__name__ == "NoCheckInputsError":
            return {"error": ("CHECK needs a completed Fast Analysis of the buyer package and a persisted "
                              f"submission package for this bid. {exc}")}
        return {"error": f"Could not start CHECK: {exc}"}
    finally:
        session[key] = False
    session[_OUTCOME_NOTE.format(bid=bid_id)] = response.get("outcome")
    return response


# ═══════════════════════════════════════════════════════════════════════
# Rendering
# ═══════════════════════════════════════════════════════════════════════

def _html(inner: str) -> None:
    st.markdown(f'<div class="ck">{inner}</div>', unsafe_allow_html=True)


def _api_key():
    if not st.session_state.get("anthropic_api_key") and not api_key_configured():
        return None
    return st.session_state.get("anthropic_api_key") or get_api_key()


def _click_start(bid_id: int, *, retry: bool = False) -> None:
    _, org, user_id = _ctx()
    key = _api_key()
    if key is None:  # a CREATED run would otherwise be left without a provider client
        st.error("Add your Anthropic API key first (see New Bid page or Settings).")
        return
    with st.spinner("Checking the current buyer package and submission…"):
        resp = request_start(bid_id, org, key, st.session_state, retry=retry, user_id=user_id)
    if resp.get("error"):
        st.error(resp["error"])
        return
    st.rerun()


def _outcome_note(bid_id: int) -> None:
    outcome = st.session_state.pop(_OUTCOME_NOTE.format(bid=bid_id), None)
    tone, text = cwv.START_OUTCOME_NOTES.get(outcome, (None, None))
    if text:
        _html(cwv.render_banner(tone, text))


@st.fragment(run_every=POLL_INTERVAL_SECONDS)
def _poll_running(bid_id: int) -> None:
    _, org, _ = _ctx()
    loaded = load_status(bid_id, org)
    status = loaded["status"]
    if loaded["error"] or status is None:
        st.caption("Status read failed. Retrying on the next refresh; the CHECK run is unaffected.")
        return
    rv = cwv.run_view(status)
    if rv["is_terminal"] or rv["stuck"]:
        st.rerun()
        return
    _html(cwv.render_banner("info", f"CHECK run {rv['run_id']} is {rv['label'].lower()}.",
                            [cwv.progress_text(status), "This page updates when the run finishes."]))


def _render_finding(a: dict, index: dict, bid_id: int, where: str) -> None:
    _html(cwv.render_card(a, index))
    label = ("Trace to buyer source and bidder evidence" if a.get("status") != cwv.NOT_APPLICABLE
             else "Show buyer source")
    with st.expander(label, expanded=False):
        # The card already shows elements / reasons for every non-ADDRESSED finding.
        detail, overflow = cwv.render_detail(a, index, include_elements=a.get("status") == cwv.ADDRESSED)
        _html(detail)
        if overflow:
            st.caption("More cited evidence")
            _html(overflow)


def _render_criteria(adjs: list, index: dict, bid_id: int) -> None:
    crits = cwv.criteria(adjs)
    _html('<div class="ck-hn">Every scoped evaluation criterion, with the weight the buyer stated. Buyer weight '
          'is buyer metadata, not a predicted mark: CHECK never estimates evaluator scores. Items needing '
          'attention come first.</div>')
    if not crits:
        _html('<div class="ck-none">This buyer package has no scoped evaluation criteria.</div>')
    for a in crits:
        _render_finding(a, index, bid_id, "crit")


def _render_findings(adjs: list, index: dict, bid_id: int) -> None:
    opts = cwv.filter_options(adjs)
    type_labels = {"Requirements": [cwv.OBJECT_REQUIREMENT], "Evaluation criteria": [cwv.OBJECT_CRITERION],
                   "Both": [cwv.OBJECT_REQUIREMENT, cwv.OBJECT_CRITERION]}
    c1, c2 = st.columns([2, 1])
    default_status = [s for s in cwv.ATTENTION_STATUSES if s in opts["statuses"]]
    statuses = c1.multiselect("Status", opts["statuses"], default=default_status,
                              format_func=lambda s: f'{cwv.STATUS_META[s]["mark"]} {cwv.STATUS_META[s]["label"]}',
                              key=f"chk_f_status_{bid_id}")
    obj = c2.selectbox("Buyer object type", list(type_labels), index=0, key=f"chk_f_type_{bid_id}")
    c3, c4, c5 = st.columns([1.3, 1.3, 1])
    scopes = c3.multiselect("Assurance scope", opts["scopes"], format_func=lambda s: cwv.SCOPE_LABEL.get(s, s),
                            key=f"chk_f_scope_{bid_id}")
    roles = c4.multiselect("Expected evidence in", opts["roles"], format_func=lambda r: cwv.ROLE_LABEL.get(r, r),
                           key=f"chk_f_role_{bid_id}")
    mand = c5.checkbox("Mandatory / submission-wide only", key=f"chk_f_mand_{bid_id}")
    rows = cwv.filter_findings(adjs, statuses=statuses, object_types=type_labels[obj], scopes=scopes,
                               roles=roles, mandatory_only=mand)
    st.caption(f"{len(rows)} finding(s) match. Clear the status filter to include everything.")
    for a in rows:
        _render_finding(a, index, bid_id, "req")


def _render_non_submission(adjs: list) -> None:
    items = cwv.non_submission(adjs)
    _html('<div class="ck-hn">Buyer objects the scope rules classified as not being proposal obligations. '
          'They are listed for completeness and are never counted as gaps.</div>')
    if not items:
        _html('<div class="ck-none">None.</div>')
        return
    by_scope: dict = {}
    for a in items:
        by_scope.setdefault(a.get("assurance_scope"), []).append(a)
    for scope, group in by_scope.items():
        with st.expander(f"{cwv.SCOPE_LABEL.get(scope, scope)} ({len(group)})"):
            rows = "".join(
                f'<div class="ck-att-row" style="--c:var(--dim)"><div class="ck-att-m">–</div><div>'
                f'<div class="ck-att-t">{cwv.esc(a.get("buyer_object_id"))}</div>'
                f'<div class="ck-att-d">{cwv.esc(cwv.clip(a.get("buyer_expectation"), 260))}</div>'
                f'<div class="ck-att-d"><b>Why:</b> {cwv.esc("; ".join(cwv.review_notes(a)) or a.get("scope_basis"))}</div>'
                f'</div></div>' for a in group)
            _html(f'<div class="ck-att">{rows}</div>')


def _render_workspace(bid_id: int, bid: dict | None, status: dict, bundle: dict, *, shown_note: str | None) -> None:
    shown_status = {**status, "run_id": bundle["run_id"], "status": bundle["run_status"],
                    "completed_at": bundle["run"].get("completed_at"), "failed_at": bundle["run"].get("failed_at"),
                    "started_at": bundle["run"].get("started_at"), "created_at": bundle["run"].get("created_at"),
                    "source_package_snapshot_id": bundle["run"].get("source_package_snapshot_id"),
                    "failure_reason": bundle["run"].get("failure_reason")} \
        if bundle["run_id"] != status.get("run_id") else status
    rv = cwv.run_view(shown_status)
    adjs, index = bundle["adjs"], bundle["index"]
    _html(cwv.render_header(bid, rv, bundle["files"]))
    if shown_note:
        _html(cwv.render_banner("gap", shown_note))
    if rv["status"] == cwv.RUN_PARTIAL:
        _html(cwv.render_banner("caution", "Partial CHECK: some adjudication stages did not complete. "
                                           "This is not complete assurance.",
                                cwv.partial_disclosure(shown_status, bundle["payload"])))
    elif rv["status"] == cwv.RUN_COMPLETE:
        _html(cwv.render_banner("ok", "Complete. Every adjudication stage finished.",
                                ["Shown from the saved CHECK run; opening, filtering and tracing never re-run it."]))
    if not bundle["digest_verified"]:
        _html(cwv.render_banner("warn", "The saved result did not pass its integrity digest check. "
                                        "Treat it with caution and run CHECK again."))
    if bundle.get("evidence_error"):
        _html(cwv.render_banner("warn", "Submission evidence could not be loaded, so evidence excerpts are "
                                        "not shown.", [bundle["evidence_error"]]))

    ov = cwv.overview(adjs)
    _html(cwv.render_counts(ov) + cwv.render_legend())

    attention = cwv.attention_items(adjs)
    _html('<h2 class="ck-h">Where to look first</h2><div class="ck-hn">Ordered by buyer facts only: evaluation '
          'criteria first, then the weight the buyer stated, a stated minimum threshold, mandatory or '
          'submission-wide requirements, then status. No hidden risk score.</div>'
          + cwv.render_attention(attention[:ATTENTION_SHOWN]))
    if len(attention) > ATTENTION_SHOWN:
        with st.expander(f"{len(attention) - ATTENTION_SHOWN} more items needing attention"):
            _html(cwv.render_attention(attention[ATTENTION_SHOWN:]))

    crit_n = ov["criteria"]
    req_n = len(cwv.submission_requirements(adjs))
    tab_c, tab_r, tab_n, tab_f = st.tabs([f"Evaluation criteria ({crit_n})", f"Requirements and filters ({req_n})",
                                          f"Non-submission ({ov['excluded']})", f"Submitted files ({len(bundle['files'])})"])
    with tab_c:
        _render_criteria(adjs, index, bid_id)
    with tab_r:
        _render_findings(adjs, index, bid_id)
    with tab_n:
        _render_non_submission(adjs)
    with tab_f:
        _html('<div class="ck-hn">The authoritative submitted artifacts CHECK assessed (one per logical '
              'artifact; alternate representations and duplicates are not double-counted).</div>'
              + cwv.render_files(bundle["files"]))


def _render_controls(bid_id: int, run_status: str | None, inflight: bool) -> None:
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    cta = cwv.rerun_cta(run_status)
    st.caption(cta["caption"])
    if st.button(cta["label"], key=f"chk_{'retry' if cta['retry'] else 'again'}_{bid_id}", disabled=inflight):
        _click_start(bid_id, retry=cta["retry"])


def page_check_assurance(bid_id: int) -> None:
    token, org, _ = _ctx()
    st.markdown(cwv.CSS, unsafe_allow_html=True)
    bid = tenancy.get_bid_authenticated(token, bid_id)
    if not bid:
        st.error("Opportunity not found.")
        return
    _outcome_note(bid_id)
    inflight = bool(st.session_state.get(_START_INFLIGHT.format(bid=bid_id)))
    try:
        loaded = load_status(bid_id, org)
    except tenancy.AccessDeniedError:
        st.error("You do not have access to that bid.")
        return
    if loaded["error"]:
        st.warning("Could not read CHECK status right now. Refresh to try again; nothing was started.")
        return
    status = loaded["status"]

    if status is None:
        _html(cwv.render_header(bid, cwv.run_view(None), []))
        _html(cwv.render_banner("info", "No CHECK has run for this bid yet.",
                                ["CHECK compares the persisted submission package against the canonical buyer "
                                 "requirements and evaluation criteria (at most 12 bounded model calls). "
                                 "Nothing runs unless you click."]))
        if st.button("Run CHECK", key=f"chk_start_{bid_id}", type="primary", disabled=inflight):
            _click_start(bid_id)
        return

    rv = cwv.run_view(status)
    if not rv["is_terminal"]:
        _html(cwv.render_header(bid, rv, []))
        if rv["stuck"]:
            _html(cwv.render_banner("warn", f"CHECK run {rv['run_id']} stopped reporting progress.",
                                    ["It has not been re-run. Mark it as stopped, then run CHECK again."]))
            if st.button("Mark this run as stopped", key=f"chk_mark_stuck_{bid_id}"):
                try:
                    tenancy.mark_check_run_stuck_for_organization(bid_id, org, int(rv["run_id"]))
                except Exception as exc:
                    st.error(f"Could not mark the run as stopped: {exc}")
                    return
                st.rerun()
            return
        _poll_running(bid_id)
        return

    shown_note = None
    if rv["status"] == cwv.RUN_FAILED:
        why = f" ({rv['failure_reason']})" if rv.get("failure_reason") else ""
        bundle = load_bundle(bid_id, org, None, st.session_state)
        if bundle.get("error"):
            _html(cwv.render_header(bid, rv, []))
            _html(cwv.render_banner("gap", f"CHECK run {rv['run_id']} failed{why}.",
                                    ["No complete or partial CHECK result exists to show."]))
            _render_controls(bid_id, rv["status"], inflight)
            return
        shown_note = (f"The latest CHECK run ({rv['run_id']}) failed{why}. Showing the most recent saved "
                      f"{'complete' if bundle['run_status'] == cwv.RUN_COMPLETE else 'partial'} run "
                      f"({bundle['run_id']}) instead.")
    else:
        bundle = load_bundle(bid_id, org, int(rv["run_id"]), st.session_state)
        if bundle.get("error"):
            _html(cwv.render_header(bid, rv, []))
            _html(cwv.render_banner("warn", bundle["error"]))
            return
    _render_workspace(bid_id, bid, status, bundle, shown_note=shown_note)
    _render_controls(bid_id, rv["status"], inflight)
