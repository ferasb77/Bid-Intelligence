"""MA-2B: Animated multi-agent Full Analysis experience -- presentation
and interaction tests. Fully deterministic: every service/database call is
mocked, and no provider/model call is possible (asserted)."""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

import tenancy
from components import full_analysis_view as fav
from pages import stage_full_analysis as page

ROOT = pathlib.Path(__file__).resolve().parents[1]
IDS = fav.SPECIALIST_IDS


# ─── fixture / replay builders ────────────────────────────────────────

def _ev(seq, et, sid=None, status=None, detail=None):
    return {"sequence": seq, "event_type": et, "specialist_id": sid, "status": status,
            "detail": detail or {}, "occurred_at": f"2026-09-22T20:30:{seq:02d}+00:00"}


PACKAGE_COUNTS = {"CANONICAL_REQUIREMENT": 41, "SCOPED_EVALUATION_CRITERION": 23,
                  "CATEGORY_SCOPE_ITEM": 22, "SCOPED_MILESTONE": 15, "COMMERCIAL_OBLIGATION": 112}


def replay(events, run_status="RUNNING", *, stuck=False, run_id=77):
    """Build a get_full_analysis_status-shaped dict by running the REAL
    service derivation (full_analysis_service.derive_execution_state) --
    pure, no DB -- over a replayed event list."""
    import full_analysis_service as fas
    run = {"id": run_id, "status": run_status}
    state = fas.derive_execution_state(run, events)
    return {"run_id": run_id, "bid_id": 8, "status": run_status,
            "is_terminal": run_status in fas.TERMINAL_RUN_STATUSES,
            "stuck": {"stuck": stuck, "reason": "NO_PROGRESS" if stuck else None},
            "specialists": state["specialists"], "reconciliation": state["reconciliation"],
            "events": events, "last_sequence": max((e["sequence"] for e in events), default=0),
            "failure_reason": None}


def base_events():
    ev = [_ev(1, "RUN_CREATED", status="QUEUED"),
          _ev(2, "CANONICAL_PACKAGE_READY", status="RUNNING", detail={"object_counts": PACKAGE_COUNTS})]
    for i, sid in enumerate(IDS):
        ev.append(_ev(3 + i, "SPECIALIST_QUEUED", sid, "QUEUED"))
    return ev


def seq_after(ev):
    return max(e["sequence"] for e in ev) + 1


def add(ev, et, sid=None, status=None, detail=None):
    ev.append(_ev(seq_after(ev), et, sid, status, detail))
    return ev


def all_complete_events(partial=(), failed=(), recon="COMPLETE"):
    ev = base_events()
    for sid in IDS:
        add(ev, "SPECIALIST_STARTED", sid, "RUNNING")
        if sid in failed:
            add(ev, "SPECIALIST_FAILED", sid, "FAILED")
        else:
            add(ev, "SPECIALIST_COMPLETED", sid, "PARTIAL" if sid in partial else "COMPLETE")
    add(ev, "RECONCILIATION_STARTED", status="RUNNING")
    if recon == "FAILED":
        add(ev, "RECONCILIATION_FAILED", status="FAILED")
    elif recon:
        add(ev, "RECONCILIATION_COMPLETED", status=recon)
    return ev


def row(sid, raw="COMPLETE", inner="COMPLETE", findings=None):
    return {"specialist_id": sid, "status": raw,
            "result": {"status": inner, "findings": findings or [
                {"finding_id": f"{sid}:0", "finding_type": "FACT", "title": f"{sid} headline",
                 "detail": "d", "severity": "HIGH", "canonical_ids": ["REQ-1"],
                 "produced_by": [sid], "authority": "CANONICAL"}]},
            "effective_status": None}


def with_effective(rows):
    import full_analysis_service as fas
    for r in rows:
        r["effective_status"] = fas.effective_specialist_status(r)
    return rows


# Historical run 32 (bid 8, Bank of Canada) -- compact excerpt of the real
# persisted shape read-only from the live DB (MA-2B smoke). Its rows carry
# inner status COMPLETE; nothing is retroactively made PARTIAL.
RUN32_RESULT = {
    "completeness_status": "COMPLETE",
    "specialist_statuses": {sid: "COMPLETE" for sid in IDS},
    "reconciliation": {"status": "COMPLETE", "completeness_note": ""},
    "reconciled_findings": [
        {"finding_id": "PROCUREMENT_STRUCTURE:1", "finding_type": "ATTENTION_ITEM",
         "title": "Multi-award contracting with category-specific winner caps and no minimum volume guarantee",
         "detail": "The procurement awards to a maximum of 5 proponents (Category 1)...", "severity": "HIGH",
         "canonical_ids": ["IDENT"], "produced_by": ["PROCUREMENT_STRUCTURE", "SCOPE_DELIVERABLES"],
         "authority": "SPECIALIST_INTERPRETATION", "human_confirmation_required": False, "category_scope": ""},
        {"finding_id": "EVALUATION_INTELLIGENCE:0", "finding_type": "ATTENTION_ITEM",
         "title": "Curriculum & Program Design Capability dominates D1 scoring (35/75 points)",
         "detail": "...", "severity": "HIGH",
         "canonical_ids": ["CRIT-appendix-d1-learning-development-programs-and-assessments-curriculum-pro"],
         "produced_by": ["EVALUATION_INTELLIGENCE"], "authority": "SPECIALIST_INTERPRETATION",
         "category_scope": "Appendix D1 – Learning & Development Programs and Assessments"},
        {"finding_id": "COMMERCIAL_CONTRACTUAL:2", "finding_type": "ATTENTION_ITEM",
         "title": "Insurance Minimums Are Non-Negotiable: $3M CGL and $3M E&O Combined",
         "detail": "OBL-3 ...", "severity": "HIGH", "canonical_ids": ["OBL-3", "OBL-4"],
         "produced_by": ["COMMERCIAL_CONTRACTUAL"], "authority": "SPECIALIST_INTERPRETATION",
         "human_confirmation_required": True},
    ],
    "cross_domain_risks": [{"title": "D2 Rated Criteria Form Ambiguity Creates Submission Compliance Risk",
                            "detail": "...", "domains": ["PROCUREMENT_STRUCTURE", "REQUIREMENTS_COMPLIANCE"],
                            "severity": "HIGH", "finding_ids": ["PROCUREMENT_STRUCTURE:0"],
                            "canonical_ids": ["CAT-appendix-d2-hr-advisory"]}],
    "unresolved_gaps": [{"title": "No submission method specified in canonical procurement documents",
                         "detail": "...", "canonical_ids": ["SUBMISSION"], "severity": "HIGH",
                         "produced_by": ["PROCUREMENT_STRUCTURE"]}],
    "ambiguities": [], "human_confirmation_required": [],
}


# ─── fixtures: states ────────────────────────────────────────────────

class TestFixtureStates:
    def test_fresh_run_all_six_queued(self):
        view = fav.build_view(replay(base_events()))
        assert set(view["bots"].values()) == {"QUEUED"}
        assert view["reconciliation"] == "WAITING"
        assert view["stage"] == "Preparing"
        assert view["live"] is True

    def test_no_events_yet_is_waiting_never_fabricated(self):
        view = fav.build_view(replay([_ev(1, "RUN_CREATED", status="QUEUED")], "QUEUED"))
        assert set(view["bots"].values()) == {"WAITING"}

    def test_parallel_three_running_three_queued_from_events(self):
        ev = base_events()
        # deliberately NOT the first three -- the UI renders what events say
        for sid in (IDS[1], IDS[3], IDS[5]):
            add(ev, "SPECIALIST_STARTED", sid, "RUNNING")
        view = fav.build_view(replay(ev))
        running = [s for s, st in view["bots"].items() if st == "RUNNING"]
        assert running == [IDS[1], IDS[3], IDS[5]]
        assert sum(1 for st in view["bots"].values() if st == "QUEUED") == 3
        html = fav.render_constellation(view)
        assert html.count('data-state="RUNNING"') == 3
        assert "3 working now" in view["progress"]

    def test_transition_one_completes_next_starts_draws_one_packet(self):
        ev = base_events()
        for sid in IDS[:3]:
            add(ev, "SPECIALIST_STARTED", sid, "RUNNING")
        before = fav.build_view(replay(ev))
        add(ev, "SPECIALIST_COMPLETED", IDS[0], "COMPLETE")
        add(ev, "SPECIALIST_STARTED", IDS[3], "RUNNING")
        after = fav.build_view(replay(ev))
        assert after["bots"][IDS[0]] == "COMPLETE" and after["bots"][IDS[3]] == "RUNNING"
        packets = fav.packet_transitions(before["bots"], after["bots"])
        assert packets == [IDS[0]]
        html = fav.render_constellation(after, packets)
        assert html.count('data-packet="1"') == 1
        # next poll with no new transition: no packet, no endless replay
        assert fav.packet_transitions(after["bots"], after["bots"]) == []

    def test_reconnect_does_not_replay_packets(self):
        view = fav.build_view(replay(all_complete_events(), "COMPLETE"))
        assert fav.packet_transitions(None, view["bots"]) == []

    def test_partial_specialist_distinct_from_complete(self):
        view = fav.build_view(replay(all_complete_events(partial=(IDS[2],)), "PARTIAL"))
        assert view["bots"][IDS[2]] == "PARTIAL"
        html = fav.render_constellation(view)
        assert 'data-specialist="EVALUATION_INTELLIGENCE" data-state="PARTIAL"' in html
        assert "Partial output" in html
        assert ".s-PARTIAL{" in html and ".s-COMPLETE{" in html
        assert view["stage"] == "Partial"
        assert "1 partial" in view["progress"]

    def test_failed_specialist_rendered_truthfully_others_complete(self):
        view = fav.build_view(replay(all_complete_events(failed=(IDS[4],)), "PARTIAL"))
        assert view["bots"][IDS[4]] == "FAILED"
        assert all(view["bots"][s] == "COMPLETE" for s in IDS if s != IDS[4])
        prev = {s: "RUNNING" for s in IDS}
        packets = fav.packet_transitions(prev, view["bots"])
        assert IDS[4] not in packets  # no pretend-success packet
        msgs = fav.incomplete_domain_messages(view["bots"], view["reconciliation"])
        assert any("Commercial & Contractual failed" in m for m in msgs)


class TestReconciliationStates:
    def _events_through_specialists(self):
        ev = base_events()
        for sid in IDS:
            add(ev, "SPECIALIST_STARTED", sid, "RUNNING")
            add(ev, "SPECIALIST_COMPLETED", sid, "COMPLETE")
        return ev

    def test_waiting_until_backend_says_started(self):
        view = fav.build_view(replay(self._events_through_specialists()))
        assert view["reconciliation"] == "WAITING"
        assert view["stage"] == "Analyzing"
        assert "Reconciliation pending" in view["progress"]

    def test_running_only_after_reconciliation_started_event(self):
        ev = add(self._events_through_specialists(), "RECONCILIATION_STARTED", status="RUNNING")
        view = fav.build_view(replay(ev))
        assert view["reconciliation"] == "RUNNING" and view["stage"] == "Reconciling"

    @pytest.mark.parametrize("final,expected", [("COMPLETE", "COMPLETE"), ("PARTIAL", "PARTIAL"),
                                                ("FAILED", "FAILED")])
    def test_terminal_reconciliation(self, final, expected):
        view = fav.build_view(replay(all_complete_events(recon=final),
                                     "COMPLETE" if final == "COMPLETE" else "PARTIAL"))
        assert view["reconciliation"] == expected
        html = fav.render_constellation(view)
        assert f'class="fa-recon s-{expected}"' in html

    def test_reconciliation_failure_preserves_specialists(self):
        view = fav.build_view(replay(all_complete_events(recon="FAILED"), "PARTIAL"))
        assert all(s == "COMPLETE" for s in view["bots"].values())
        assert any("Reconciliation & Assurance failed" in m
                   for m in fav.incomplete_domain_messages(view["bots"], view["reconciliation"]))


class TestTerminalAndStuck:
    def test_complete_result_stops_polling(self):
        assert fav.should_poll(replay(all_complete_events(), "COMPLETE")) is False

    def test_partial_and_failed_stop_polling(self):
        assert fav.should_poll(replay(all_complete_events(partial=(IDS[0],)), "PARTIAL")) is False
        assert fav.should_poll(replay(base_events(), "FAILED")) is False

    def test_failed_run_unfinished_specialists_skipped(self):
        view = fav.build_view(replay(base_events(), "FAILED"))
        assert set(view["bots"].values()) == {"SKIPPED"}
        assert view["stage"] == "Failed"

    def test_stuck_run_stops_animation_and_polling(self):
        ev = base_events()
        add(ev, "SPECIALIST_STARTED", IDS[0], "RUNNING")
        status = replay(ev, stuck=True)
        view = fav.build_view(status)
        assert fav.should_poll(status) is False and view["live"] is False and view["stuck"]
        html = fav.render_constellation(view)
        assert 'class="fa-wrap fa-still fa-stuck"' in html
        assert "Analysis interrupted" in html
        assert "animation:none!important" in html  # stuck selector disables motion


class TestEffectiveStatus:
    def test_row_effective_partial_overrides_raw_complete(self):
        # migration 020 raw column says COMPLETE; the result JSON says PARTIAL
        rows = with_effective([row(IDS[2], raw="COMPLETE", inner="PARTIAL")])
        status = replay(all_complete_events(), "PARTIAL")  # event log says COMPLETE (worst case)
        view = fav.build_view(status, rows)
        assert view["bots"][IDS[2]] == "PARTIAL"

    def test_raw_status_column_never_read(self):
        # raw says FAILED but effective says COMPLETE -> COMPLETE; and a row
        # with only a raw status and no effective_status is ignored
        r = row(IDS[0], raw="FAILED", inner="COMPLETE")
        r["effective_status"] = "COMPLETE"
        bogus = {"specialist_id": IDS[1], "status": "COMPLETE"}  # no effective_status
        ev = base_events()
        add(ev, "SPECIALIST_STARTED", IDS[1], "RUNNING")
        view = fav.build_view(replay(ev), [r, bogus])
        assert view["bots"][IDS[0]] == "COMPLETE"
        assert view["bots"][IDS[1]] == "RUNNING"
        src = (ROOT / "components" / "full_analysis_view.py").read_text(encoding="utf-8")
        assert 'row.get("status")' not in src and "row['status']" not in src

    def test_historical_run32_not_retroactively_partial(self):
        rows = with_effective([row(sid) for sid in IDS])  # inner COMPLETE like run 32
        view = fav.build_view(replay(all_complete_events(), "COMPLETE", run_id=32), rows)
        assert set(view["bots"].values()) == {"COMPLETE"}

    def test_pre_ma2a2_row_without_inner_status_falls_back_via_service(self):
        r = {"specialist_id": IDS[0], "status": "COMPLETE", "result": {}}
        with_effective([r])
        assert fav.bot_state(IDS[0], None, {IDS[0]: r}) == "COMPLETE"


class TestNoFakeProgress:
    def test_no_percentages_anywhere(self):
        for events, st in ((base_events(), "RUNNING"), (all_complete_events(), "COMPLETE"),
                           (all_complete_events(partial=(IDS[1],)), "PARTIAL")):
            view = fav.build_view(replay(events, st))
            html = fav.render_constellation(view)
            text = re.sub(r"<style>.*?</style>", "", html, flags=re.S)
            text = re.sub(r"<[^>]+>", " ", text)
            assert "%" not in text
            assert "%" not in view["progress"]

    def test_progress_is_real_counts(self):
        view = fav.build_view(replay(all_complete_events(partial=(IDS[0],)), "PARTIAL"))
        assert view["progress"].startswith("6 of 6 specialists finished")


class TestHubAndPresentation:
    def test_hub_counts_come_from_persisted_package_event(self):
        view = fav.build_view(replay(base_events()))
        assert (41, "requirements") in view["hub_counts"]
        assert "Shared Truth" in fav.render_constellation(view)

    def test_hub_without_event_does_not_invent_counts(self):
        view = fav.build_view(replay([_ev(1, "RUN_CREATED", status="QUEUED")], "QUEUED"))
        assert view["hub_counts"] == []

    def test_every_bot_has_text_state_for_reduced_motion(self):
        view = fav.build_view(replay(all_complete_events(partial=(IDS[0],), failed=(IDS[1],)), "PARTIAL"))
        html = fav.render_constellation(view)
        for sid in IDS:
            assert f"{fav.SPECIALIST_NAME[sid]}".replace("&", "&amp;") in html
        for label in ("Partial output", "Failed", "Complete"):
            assert label in html
        assert "prefers-reduced-motion:reduce" in html

    def test_responsive_fallback_present(self):
        html = fav.render_constellation(fav.build_view(replay(base_events())))
        assert "@media (max-width:860px)" in html and "grid-template-columns:1fr" in html

    def test_render_is_deterministic(self):
        view = fav.build_view(replay(base_events()))
        assert fav.render_constellation(view) == fav.render_constellation(view)

    def test_html_escaped(self):
        f = {"title": "<script>x</script>", "detail": "a&b", "severity": "HIGH"}
        out = fav.finding_html(f)
        assert "<script>" not in out and "&lt;script&gt;" in out


class TestCompletedResult:
    def test_historical_run32_groups_safely(self):
        grouped = fav.group_result(RUN32_RESULT)
        assert grouped["domains"]["PROCUREMENT_STRUCTURE"][0]["title"].startswith("Multi-award")
        assert grouped["domains"]["EVALUATION_INTELLIGENCE"]
        assert grouped["domains"]["SCOPE_DELIVERABLES"] == []  # merged finding shown once
        assert grouped["cross_domain_risks"] and grouped["gaps"]
        html = fav.finding_html(grouped["domains"]["PROCUREMENT_STRUCTURE"][0], primary="PROCUREMENT_STRUCTURE")
        assert "Also raised by Scope &amp; Deliverables" in html

    def test_valid_findings_survive_partial_result(self):
        rows = with_effective([row(IDS[2], inner="PARTIAL")] + [row(s) for s in IDS if s != IDS[2]])
        # no reconciled findings (reconciliation failed) -> fall back to rows
        grouped = fav.group_result({"completeness_status": "PARTIAL"}, rows)
        assert grouped["domains"][IDS[2]][0]["title"] == f"{IDS[2]} headline"

    def test_traceability_rows(self):
        grouped = fav.group_result(RUN32_RESULT)
        trace = fav.trace_rows(grouped["cross_domain_risks"])
        assert trace[0][1] == ["CAT-appendix-d2-hr-advisory"] and trace[0][2] == ["PROCUREMENT_STRUCTURE:0"]

    def test_specialist_preview_uses_persisted_findings_only(self):
        assert fav.specialist_preview(row(IDS[0])) == [f"{IDS[0]} headline"]
        assert fav.specialist_preview(None) == []


# ─── controller: service wiring, debounce, reconnect ─────────────────

class FakeService:
    def __init__(self, outcome="CREATED", status=None, result=None, fail_status=0):
        self.start_calls, self.status_calls, self.result_calls = [], 0, 0
        self.outcome, self.status, self.result, self.fail_status = outcome, status, result, fail_status

    def start(self, bid_id, org, key, **kw):
        self.start_calls.append((bid_id, org, kw))
        return {"outcome": self.outcome, "run": {"id": 77}, "executing": self.outcome == "CREATED"}

    def get_status(self, bid_id, org, run_id=None, **kw):
        self.status_calls += 1
        if self.fail_status:
            self.fail_status -= 1
            raise ConnectionError("transient")
        return self.status

    def get_result(self, bid_id, org, run_id=None):
        self.result_calls += 1
        return self.result


@pytest.fixture
def svc(monkeypatch):
    s = FakeService()
    monkeypatch.setattr(tenancy, "start_full_analysis_for_organization", s.start)
    monkeypatch.setattr(tenancy, "get_full_analysis_status_for_organization", s.get_status)
    monkeypatch.setattr(tenancy, "get_full_analysis_result_for_organization", s.get_result)
    return s


class TestController:
    def test_start_uses_canonical_service(self, svc):
        session = {}
        resp = page.request_start(8, "org", "k", session, user_id="u1")
        assert resp["outcome"] == "CREATED"
        assert svc.start_calls == [(8, "org", {"created_by_user_id": "u1", "retry": False})]
        assert session["fa_outcome_8"] == "CREATED"

    def test_duplicate_click_while_in_flight_does_not_start_twice(self, svc):
        session = {"fa_start_inflight_8": True}
        assert page.request_start(8, "org", "k", session) == {"outcome": "IN_FLIGHT"}
        assert svc.start_calls == []

    def test_repeated_presses_each_hit_idempotent_service_once(self, svc):
        session = {}
        svc.outcome = "ACTIVE_RUN_EXISTS"
        page.request_start(8, "org", "k", session)
        page.request_start(8, "org", "k", session)
        assert len(svc.start_calls) == 2  # one call per completed click, never concurrent
        assert all(c[2]["retry"] is False for c in svc.start_calls)  # never escalates to retry
        assert session["fa_start_inflight_8"] is False

    @pytest.mark.parametrize("outcome", ["CREATED", "ACTIVE_RUN_EXISTS", "REUSED_COMPLETE",
                                         "EXISTING_FAILED", "EXISTING_PARTIAL"])
    def test_every_outcome_has_a_note_and_no_second_call(self, svc, outcome):
        svc.outcome = outcome
        session = {}
        page.request_start(8, "org", "k", session)
        assert len(svc.start_calls) == 1
        assert outcome in fav.START_OUTCOME_NOTES
        if outcome in ("EXISTING_FAILED", "EXISTING_PARTIAL"):
            assert "not re-run automatically" in fav.START_OUTCOME_NOTES[outcome][1]

    def test_reused_complete_opens_result_without_animation(self, svc):
        svc.outcome = "REUSED_COMPLETE"
        svc.status = replay(all_complete_events(), "COMPLETE")
        svc.result = {"specialist_results": with_effective([row(s) for s in IDS]), "result": RUN32_RESULT}
        page.request_start(8, "org", "k", {})
        frame = page.live_frame(8, "org", {})
        assert frame["view"]["live"] is False  # page goes straight to result view
        assert frame["packets"] == []  # nothing replayed

    def test_active_run_exists_reconnects_to_live_state(self, svc):
        ev = base_events()
        add(ev, "SPECIALIST_STARTED", IDS[0], "RUNNING")
        svc.outcome, svc.status = "ACTIVE_RUN_EXISTS", replay(ev)
        page.request_start(8, "org", "k", {})
        frame = page.live_frame(8, "org", {})
        assert frame["view"]["live"] is True and frame["view"]["bots"][IDS[0]] == "RUNNING"

    def test_refresh_reconstructs_from_service_not_session(self, svc):
        ev = all_complete_events(partial=(IDS[3],))
        svc.status = replay(ev, "PARTIAL")
        svc.result = {"specialist_results": with_effective([row(s, inner="PARTIAL" if s == IDS[3] else "COMPLETE")
                                                            for s in IDS])}
        fresh_session = {}  # brand-new browser session: nothing cached
        frame = page.live_frame(8, "org", fresh_session)
        assert frame["view"]["bots"][IDS[3]] == "PARTIAL"
        assert svc.status_calls == 1 and svc.result_calls == 1

    def test_rows_fetched_only_on_transition(self, svc):
        ev = base_events()
        for sid in IDS[:3]:
            add(ev, "SPECIALIST_STARTED", sid, "RUNNING")
        add(ev, "SPECIALIST_COMPLETED", IDS[0], "COMPLETE")
        svc.status = replay(ev)
        svc.result = {"specialist_results": with_effective([row(IDS[0])])}
        session = {}
        page.live_frame(8, "org", session)
        page.live_frame(8, "org", session)
        page.live_frame(8, "org", session)
        assert svc.status_calls == 3 and svc.result_calls == 1

    def test_transient_poll_failure_tolerated_and_never_restarts(self, svc):
        svc.fail_status = 1
        svc.status = replay(base_events())
        frame = page.live_frame(8, "org", {})
        assert frame["error"] and frame["view"] is None
        frame = page.live_frame(8, "org", {})
        assert frame["view"]["live"] is True
        assert svc.start_calls == []

    def test_live_packet_only_once_per_transition(self, svc):
        ev = base_events()
        for sid in IDS[:3]:
            add(ev, "SPECIALIST_STARTED", sid, "RUNNING")
        svc.status = replay(ev)
        session = {}
        assert page.live_frame(8, "org", session)["packets"] == []
        add(ev, "SPECIALIST_COMPLETED", IDS[1], "COMPLETE")
        svc.status = replay(ev)
        svc.result = {"specialist_results": with_effective([row(IDS[1])])}
        assert page.live_frame(8, "org", session)["packets"] == [IDS[1]]
        assert page.live_frame(8, "org", session)["packets"] == []

    def test_no_complete_fast_analysis_reported_cleanly(self, monkeypatch):
        class NoCompleteFastAnalysisError(Exception):
            pass

        def boom(*a, **k):
            raise NoCompleteFastAnalysisError("x")
        monkeypatch.setattr(tenancy, "start_full_analysis_for_organization", boom)
        session = {}
        resp = page.request_start(8, "org", "k", session)
        assert "Fast Analysis" in resp["error"] and session["fa_start_inflight_8"] is False


# ─── MA-2B.1: PARTIAL vs STOPPED semantics (run 33 / bid 1295 shape) ───

def _run33_view():
    """Six specialists COMPLETE, reconciliation PARTIAL (max_tokens), run PARTIAL."""
    ev = all_complete_events(recon="PARTIAL")
    status = replay(ev, "PARTIAL", run_id=33)
    rows = with_effective([row(s) for s in IDS])
    return fav.build_view(status, rows), status


class TestPartialVsStoppedSemantics:
    def test_partial_mark_and_tone_distinct_from_stop_failed(self):
        p = fav.STATE_MARK[fav.PARTIAL]
        assert p not in (fav.STATE_MARK[fav.STUCK], fav.STATE_MARK[fav.FAILED])
        assert fav.STATE_TONE[fav.PARTIAL] == "caution"
        assert fav.STATE_TONE[fav.FAILED] == "error"
        assert fav.STATE_TONE[fav.STUCK] == "stopped"
        assert fav.STATE_TONE[fav.COMPLETE] == "success"
        assert fav.STATE_TONE[fav.RUNNING] == "active"
        assert fav.STATE_TONE[fav.QUEUED] == "neutral" and fav.STATE_TONE[fav.SKIPPED] == "skipped"
        assert len({fav.STATE_MARK[s] for s in (fav.COMPLETE, fav.PARTIAL, fav.FAILED, fav.STUCK)}) == 4

    def test_partial_run_never_renders_stop_or_stuck(self):
        view, status = _run33_view()
        assert view["stuck"] is False and view["stage"] == "Partial"
        tone, mark, title, body = fav.overall_banner(view, status)
        assert (tone, mark, title) == ("caution", fav.STATE_MARK[fav.PARTIAL], "Partial Analysis")
        html_out = (fav.render_banner(tone, mark, title, body)
                    + fav.render_strip(view["bots"], view["reconciliation"]).replace(fav.CSS, ""))
        assert fav.STATE_MARK[fav.STUCK] not in html_out
        assert "tone-stopped" not in html_out and "tone-error" not in html_out
        assert "interrupted" not in html_out.lower() and "stopped" not in html_out.lower()
        const = fav.render_constellation(view).replace(fav.CSS, "")
        assert "fa-stuck" not in const and "interrupted" not in const.lower()

    def test_recon_only_partial_explanation(self):
        view, status = _run33_view()
        _, _, _, body = fav.overall_banner(view, status)
        assert body == [fav.RECON_ONLY_PARTIAL_BODY]
        assert "All six specialist analyses completed" in body[0]
        assert "lost" not in body[0].lower() and "not analyzed" not in body[0].lower()

    def test_failed_is_distinct_from_partial(self):
        status = replay(all_complete_events(recon="FAILED"), "FAILED")
        status["failure_reason"] = "boom"
        view = fav.build_view(status, with_effective([row(s) for s in IDS]))
        tone, mark, title, _ = fav.overall_banner(view, status)
        assert (tone, mark) == ("error", fav.STATE_MARK[fav.FAILED]) and "failed" in title.lower()

    def test_stuck_is_distinct_from_partial(self):
        ev = base_events()
        add(ev, "SPECIALIST_STARTED", IDS[0], "RUNNING")
        view = fav.build_view(replay(ev, stuck=True))
        tone, mark, title, _ = fav.overall_banner(view)
        assert (tone, mark, title) == ("stopped", fav.STATE_MARK[fav.STUCK], "Analysis interrupted")
        assert "fa-stuck" in fav.render_constellation(view)

    def test_partial_with_partial_specialist_lists_domains(self):
        status = replay(all_complete_events(partial=(IDS[2],)), "PARTIAL")
        view = fav.build_view(status)
        tone, _, _, body = fav.overall_banner(view, status)
        assert tone == "caution" and any(fav.SPECIALIST_NAME[IDS[2]] in b for b in body)

    def test_partial_result_visible_and_rerun_explicit(self):
        cta = fav.terminal_cta(fav.PARTIAL)
        assert cta["label"] == "Run Full Analysis Again" and cta["retry"] is True
        assert "current partial result" in cta["caption"] and "seven model calls" in cta["caption"]
        view, status = _run33_view()
        assert view["live"] is False  # result view, no polling, no auto-rerun
        assert fav.group_result({"reconciled_findings": RUN32_RESULT["reconciled_findings"]})["domains"]

    def test_complete_cta_unchanged(self):
        cta = fav.terminal_cta(fav.COMPLETE)
        assert cta["label"] == "Check for updates" and cta["retry"] is False

    def test_viewing_partial_makes_no_start_call(self, svc):
        view, status = _run33_view()
        svc.status = status
        svc.result = {"specialist_results": with_effective([row(s) for s in IDS]), "result": RUN32_RESULT}
        frame = page.live_frame(8, "org", {})
        assert frame["view"]["live"] is False and svc.start_calls == []

    def test_existing_partial_note_is_caution_not_warn(self):
        assert fav.START_OUTCOME_NOTES["EXISTING_PARTIAL"][0] == "caution"


# ─── architecture guards: no provider / specialist call from the UI ───

class TestNoProviderCalls:
    @pytest.mark.parametrize("path", ["components/full_analysis_view.py", "pages/stage_full_analysis.py"])
    def test_presentation_never_imports_execution_or_provider(self, path):
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                names.add(node.module or "")
        forbidden = {"full_analysis", "full_analysis_service", "anthropic", "analysis_service", "database"}
        assert not (names & forbidden), names & forbidden
        src = (ROOT / path).read_text(encoding="utf-8")
        for token in ("run_specialist", "run_reconciliation", "run_full_analysis", "get_anthropic_client",
                      "execute_messages_create", "messages.create"):
            assert token not in src

    def test_rendering_whole_flow_makes_no_model_call(self, svc, monkeypatch):
        import full_analysis as fa

        def explode(*a, **k):
            raise AssertionError("provider/specialist call from presentation layer")
        for name in ("run_specialist", "run_reconciliation", "run_full_analysis", "_call_model"):
            monkeypatch.setattr(fa, name, explode)
        svc.status = replay(all_complete_events(partial=(IDS[0],)), "PARTIAL")
        svc.result = {"specialist_results": with_effective([row(s) for s in IDS]), "result": RUN32_RESULT}
        frame = page.live_frame(8, "org", {})
        fav.render_constellation(frame["view"])
        fav.render_strip(frame["view"]["bots"], frame["view"]["reconciliation"])
        fav.group_result(RUN32_RESULT, frame["rows"])

    def test_page_start_only_via_tenancy_wrapper(self):
        src = (ROOT / "pages" / "stage_full_analysis.py").read_text(encoding="utf-8")
        assert src.count("tenancy.start_full_analysis_for_organization(") == 1


class TestNavigationWiring:
    def test_app_routes_full_analysis_page(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        assert "from pages.stage_full_analysis import page_full_analysis" in src
        assert '"stage_full_analysis"' in src and "page_full_analysis(bid_id)" in src

    def test_understand_links_without_starting(self):
        src = (ROOT / "pages" / "stage_understand.py").read_text(encoding="utf-8")
        assert 'st.session_state.page = "stage_full_analysis"' in src
        assert "start_full_analysis" not in src
