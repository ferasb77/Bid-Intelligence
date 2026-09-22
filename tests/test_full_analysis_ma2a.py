"""
MA-2A: Durable Full Analysis runs & progress events.

Fully deterministic and synthetic: ZERO live provider calls (every model
call goes through MA-1's MockClient), no live database -- migration 020's
three RPCs and two tables are simulated by `FakeFullAnalysisDB`, an
in-memory stand-in that implements the SAME contract the SQL enforces
(advisory-locked get-or-create outcomes, bid-scoped ownership checks,
gap-free sequencing, terminal-run refusal, COMPLETE-must-be-complete,
append-only events, write-once specialist results). Static checks at the
bottom assert the migration SQL actually states those rules.
"""
from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import database
import full_analysis as fa
import full_analysis_service as fas
import tenancy
from tests.test_full_analysis_ma1 import (
    make_result, MockClient, _payload_for, finding, CAT_1, CAT_2,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATION_020 = (ROOT / "migrations" / "020_full_analysis_runs.sql").read_text(encoding="utf-8")

TERMINAL = ("COMPLETE", "PARTIAL", "FAILED")


# ═══════════════════════════════════════════════════════════════════════
# In-memory stand-in for migration 020 (same contract as the SQL)
# ═══════════════════════════════════════════════════════════════════════

class FakeFullAnalysisDB:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
        self.runs: dict[int, dict] = {}
        self.results: dict[int, dict] = {}
        self.events: list[dict] = []
        self.specialist_results: list[dict] = []
        self._next_run = 100
        self.start_calls = 0

    def now(self):
        return self.clock.isoformat()

    # -- seed data ------------------------------------------------------
    def add_fast_run(self, bid_id: int, run_id: int, status: str = "COMPLETE"):
        self.runs[run_id] = {"id": run_id, "bid_id": bid_id, "analysis_mode": "FAST",
                             "status": status, "created_at": self.now(),
                             "corpus_digest": f"corpus-{run_id}"}

    # -- read helpers used by the service --------------------------------
    def get_analysis_run(self, run_id):
        run = self.runs.get(run_id)
        return dict(run) if run else None

    def list_analysis_runs(self, bid_id):
        rows = [dict(r) for r in self.runs.values() if r["bid_id"] == bid_id]
        return sorted(rows, key=lambda r: r["id"], reverse=True)

    def get_full_analysis_runs(self, bid_id, *, limit=50):
        rows = [dict(r) for r in self.runs.values()
                if r["bid_id"] == bid_id and r["analysis_mode"] == "FULL"]
        return sorted(rows, key=lambda r: r["id"], reverse=True)[:limit]

    def get_full_analysis_events(self, run_id, *, after_sequence=0):
        return sorted((dict(e) for e in self.events
                       if e["run_id"] == run_id and e["sequence"] > after_sequence),
                      key=lambda e: e["sequence"])

    def get_full_analysis_specialist_results(self, run_id):
        return [dict(r) for r in self.specialist_results if r["run_id"] == run_id]

    def get_analysis_result(self, run_id):
        row = self.results.get(run_id)
        return dict(row) if row else None

    # -- RPC: start_full_analysis_run --------------------------------------
    def start_full_analysis_run(self, bid_id, source_analysis_run_id, input_fingerprint,
                                engine_version, *, corpus_digest=None, created_by_user_id=None,
                                retry=False, detail=None):
        with self.lock:
            self.start_calls += 1
            src = self.runs.get(source_analysis_run_id)
            if (not src or src["bid_id"] != bid_id or src["analysis_mode"] != "FAST"
                    or src["status"] != "COMPLETE"):
                raise RuntimeError("source run is not a COMPLETE FAST run of bid")
            full = sorted((r for r in self.runs.values()
                           if r["bid_id"] == bid_id and r["analysis_mode"] == "FULL"),
                          key=lambda r: r["id"], reverse=True)
            active = [r for r in full if r["status"] not in TERMINAL]
            if active:
                return {"outcome": "ACTIVE_RUN_EXISTS", "run": dict(active[0])}
            done = [r for r in full if r["status"] == "COMPLETE"
                    and r["input_fingerprint"] == input_fingerprint]
            if done:
                return {"outcome": "REUSED_COMPLETE", "run": dict(done[0])}
            if not retry:
                same = [r for r in full if r["input_fingerprint"] == input_fingerprint]
                if same:
                    return {"outcome": "EXISTING_" + same[0]["status"], "run": dict(same[0])}
            run_id = self._next_run
            self._next_run += 1
            run = {"id": run_id, "bid_id": bid_id, "analysis_mode": "FULL",
                   "engine_version": engine_version, "status": "QUEUED",
                   "input_fingerprint": input_fingerprint,
                   "source_analysis_run_id": source_analysis_run_id,
                   "corpus_digest": corpus_digest, "created_by_user_id": created_by_user_id,
                   "created_at": self.now(), "started_at": None, "completed_at": None,
                   "failed_at": None, "failure_reason": None, "failure_detail": None,
                   "telemetry": None, "last_progress_at": self.now()}
            self.runs[run_id] = run
            self.events.append({"run_id": run_id, "bid_id": bid_id, "sequence": 1,
                                "event_type": "RUN_CREATED", "specialist_id": None,
                                "status": "QUEUED", "duration_seconds": None,
                                "failure_summary": None, "detail": dict(detail or {}),
                                "occurred_at": self.now()})
            return {"outcome": "CREATED", "run": dict(run)}

    def _next_seq(self, run_id):
        return max((e["sequence"] for e in self.events if e["run_id"] == run_id), default=0) + 1

    # -- RPC: record_full_analysis_event -------------------------------
    def record_full_analysis_event(self, run_id, bid_id, event_type, *, specialist_id=None,
                                   status=None, duration_seconds=None, failure_summary=None,
                                   detail=None, specialist_result=None):
        with self.lock:
            if event_type in ("RUN_CREATED", "RUN_COMPLETED", "RUN_PARTIAL", "RUN_FAILED"):
                raise RuntimeError("written only by start/finalize")
            if event_type not in fas.EVENT_TYPES:
                raise RuntimeError("invalid event_type")
            run = self.runs.get(run_id)
            if not run or run["bid_id"] != bid_id or run["analysis_mode"] != "FULL":
                raise RuntimeError(f"run {run_id} is not a FULL run of bid {bid_id}")
            if run["status"] in TERMINAL:
                raise RuntimeError(f"run {run_id} is terminal ({run['status']})")
            ev = {"run_id": run_id, "bid_id": bid_id, "sequence": self._next_seq(run_id),
                  "event_type": event_type, "specialist_id": specialist_id, "status": status,
                  "duration_seconds": duration_seconds, "failure_summary": failure_summary,
                  "detail": dict(detail or {}), "occurred_at": self.now()}
            assert len(str(ev["detail"])) <= 4000
            self.events.append(ev)
            if specialist_result is not None:
                if any(r["run_id"] == run_id and r["specialist_id"] == specialist_id
                       for r in self.specialist_results):
                    raise RuntimeError("duplicate specialist result (write-once)")
                self.specialist_results.append({
                    "run_id": run_id, "bid_id": bid_id, "specialist_id": specialist_id,
                    "status": "COMPLETE" if event_type == "SPECIALIST_COMPLETED" else "FAILED",
                    "specialist_version": specialist_result.get("specialist_version"),
                    "input_digest": specialist_result.get("input_digest"),
                    "result": specialist_result})
            run["status"] = "RUNNING"
            run["started_at"] = run["started_at"] or self.now()
            run["last_progress_at"] = self.now()
            return dict(ev)

    # -- RPC: finalize_full_analysis_run --------------------------------
    def finalize_full_analysis_run(self, run_id, bid_id, status, *, result=None, summary=None,
                                   failure_reason=None, failure_detail=None, telemetry=None):
        with self.lock:
            if status not in TERMINAL:
                raise RuntimeError("invalid terminal status")
            if status in ("COMPLETE", "PARTIAL") and result is None:
                raise RuntimeError("requires a result")
            if status == "COMPLETE" and (result or {}).get("completeness_status") != "COMPLETE":
                raise RuntimeError("result is not COMPLETE; refusing to mark run COMPLETE")
            run = self.runs.get(run_id)
            if not run or run["bid_id"] != bid_id or run["analysis_mode"] != "FULL":
                raise RuntimeError("not a FULL run of bid")
            if run["status"] in TERMINAL:
                raise RuntimeError(f"run {run_id} is already terminal ({run['status']})")
            if status == "COMPLETE" and any(
                    r is not run and r["analysis_mode"] == "FULL" and r["status"] == "COMPLETE"
                    and r["bid_id"] == bid_id and r["input_fingerprint"] == run["input_fingerprint"]
                    for r in self.runs.values()):
                raise RuntimeError("unique violation idx_analysis_runs_full_complete_fingerprint")
            if result is not None:
                self.results[run_id] = {"run_id": run_id, "bid_id": bid_id,
                                        "structured_intelligence": dict(summary or {}),
                                        "full_analysis_result": result}
            self.events.append({"run_id": run_id, "bid_id": bid_id,
                                "sequence": self._next_seq(run_id),
                                "event_type": {"COMPLETE": "RUN_COMPLETED",
                                               "PARTIAL": "RUN_PARTIAL"}.get(status, "RUN_FAILED"),
                                "specialist_id": None, "status": status,
                                "duration_seconds": None, "failure_summary": failure_reason,
                                "detail": dict(summary or {}), "occurred_at": self.now()})
            run.update(status=status, failure_reason=failure_reason or run["failure_reason"],
                       failure_detail=failure_detail or run["failure_detail"],
                       telemetry=telemetry or run["telemetry"], last_progress_at=self.now())
            if status == "FAILED":
                run["failed_at"] = self.now()
            else:
                run["completed_at"] = self.now()
            return dict(run)


@pytest.fixture
def fake(monkeypatch):
    f = FakeFullAnalysisDB()
    f.add_fast_run(8, 19)
    f.add_fast_run(9, 29)
    for name in ("get_analysis_run", "list_analysis_runs", "get_full_analysis_runs",
                 "get_full_analysis_events", "get_full_analysis_specialist_results",
                 "get_analysis_result", "start_full_analysis_run",
                 "record_full_analysis_event", "finalize_full_analysis_run"):
        monkeypatch.setattr(database, name, getattr(f, name))
    # model_usage_events persistence must never touch a real database here
    monkeypatch.setattr(database, "create_model_usage_event", lambda event: None)
    return f


def builder_for(result_factory=make_result):
    """package_builder: source Fast run id -> the frozen canonical package."""
    calls = []

    def build(source_run_id):
        calls.append(source_run_id)
        return fa.build_canonical_package(result_factory(), bid_id=8,
                                          analysis_run_id=source_run_id)
    build.calls = calls
    return build


def start(bid_id=8, client=None, builder=None, **kw):
    kw.setdefault("execution", fas.EXECUTION_INLINE)
    return fas.start_full_analysis(bid_id, None, client=client or MockClient(_payload_for),
                                   package_builder=builder or builder_for(), **kw)


# ═══════════════════════════════════════════════════════════════════════
# 1. Freshness / fingerprint
# ═══════════════════════════════════════════════════════════════════════

def test_first_full_request_creates_and_completes_a_run(fake):
    client = MockClient(_payload_for)
    out = start(client=client)
    assert out["outcome"] == fas.OUTCOME_CREATED
    run = fake.runs[out["run"]["id"]]
    assert run["analysis_mode"] == "FULL" and run["status"] == "COMPLETE"
    assert run["source_analysis_run_id"] == 19
    assert len(client.prompts) == 7


def test_same_fingerprint_reuses_completed_result_with_zero_provider_calls(fake):
    first = start()
    client = MockClient(_payload_for)
    second = start(client=client)
    assert second["outcome"] == fas.OUTCOME_REUSED_COMPLETE
    assert second["run"]["id"] == first["run"]["id"]
    assert client.prompts == []                      # cache hit: zero provider calls
    assert len([r for r in fake.runs.values() if r["analysis_mode"] == "FULL"]) == 1


def test_changed_canonical_digest_invalidates(fake):
    first = start()
    changed = builder_for(lambda: make_result(page_limits={"x.docx": 3}))
    client = MockClient(_payload_for)
    second = start(builder=changed, client=client)
    assert second["outcome"] == fas.OUTCOME_CREATED
    assert second["input_fingerprint"] != first["input_fingerprint"]
    assert len(client.prompts) == 7
    # immutable history: the prior run and its result are untouched
    assert fake.runs[first["run"]["id"]]["status"] == "COMPLETE"
    assert first["run"]["id"] in fake.results


def test_change_outside_ma1_package_digest_still_invalidates(fake):
    """package_completeness reaches the PROCUREMENT_STRUCTURE specialist but
    is not in MA-1's package_digest -- the fingerprint must still move."""
    a = fa.build_canonical_package(make_result(), bid_id=8)
    b = fa.build_canonical_package(make_result(package_completeness={"status": "INCOMPLETE"}),
                                   bid_id=8)
    assert a.package_digest == b.package_digest
    assert fa.compute_full_analysis_fingerprint(a) != fa.compute_full_analysis_fingerprint(b)


@pytest.mark.parametrize("attr,value", [
    ("SPECIALIST_VERSION", "ma-9.9"),
    ("RECONCILIATION_VERSION", "ma-9.9"),
    ("FULL_ANALYSIS_VERSION", "ma-9"),
    ("_RECONCILIATION_RULES", "different reconciliation prompt"),
])
def test_changed_architecture_specialist_or_reconciliation_version_invalidates(
        monkeypatch, attr, value):
    pkg = fa.build_canonical_package(make_result(), bid_id=8)
    before = fa.compute_full_analysis_fingerprint(pkg)
    monkeypatch.setattr(fa, attr, value)
    assert fa.compute_full_analysis_fingerprint(pkg) != before


def test_changed_specialist_prompt_invalidates(monkeypatch):
    pkg = fa.build_canonical_package(make_result(), bid_id=8)
    before = fa.compute_full_analysis_fingerprint(pkg)
    briefs = dict(fa.SPECIALIST_BRIEFS)
    briefs[fa.SPECIALIST_SCOPE_DELIVERABLES] += " (edited)"
    monkeypatch.setattr(fa, "SPECIALIST_BRIEFS", briefs)
    assert fa.compute_full_analysis_fingerprint(pkg) != before


def test_unrelated_data_does_not_invalidate(fake):
    """Buyer intelligence, telemetry, timing and the source run id are not
    canonical procurement input -- none of them may move the fingerprint."""
    a = fa.build_canonical_package(make_result(), bid_id=8, analysis_run_id=19)
    b = fa.build_canonical_package(
        make_result(buyer_intelligence={"summary": "external"}, telemetry=[{"x": 1}],
                    wall_seconds=999.0, skipped_documents=["ignored.pdf"]),
        bid_id=8, analysis_run_id=77)
    assert fa.compute_full_analysis_fingerprint(a) == fa.compute_full_analysis_fingerprint(b)
    first = start()
    fake.add_fast_run(8, 20)               # a newer Fast run with identical canonical output
    client = MockClient(_payload_for)
    again = start(client=client)
    assert again["outcome"] == fas.OUTCOME_REUSED_COMPLETE
    assert again["run"]["id"] == first["run"]["id"]
    assert client.prompts == []


def test_fingerprint_is_deterministic():
    a = fa.build_canonical_package(make_result(), bid_id=8)
    b = fa.build_canonical_package(make_result(), bid_id=8)
    assert fa.compute_full_analysis_fingerprint(a) == fa.compute_full_analysis_fingerprint(b)
    inputs = fa.full_analysis_fingerprint_inputs(a)
    assert set(inputs["specialists"]) == set(fa.SPECIALIST_IDS)
    assert inputs["canonical_snapshot_digest"] == a.package_digest


# ═══════════════════════════════════════════════════════════════════════
# 2. Idempotency / duplicate-run protection
# ═══════════════════════════════════════════════════════════════════════

def test_duplicate_start_while_running_returns_existing_run_and_makes_no_calls(fake):
    created = fake.start_full_analysis_run(8, 19, "fp-running", "e")   # an in-flight run
    client = MockClient(_payload_for)
    out = start(client=client)
    assert out["outcome"] == fas.OUTCOME_ACTIVE_RUN_EXISTS
    assert out["run"]["id"] == created["run"]["id"]
    assert out["fingerprint_matches"] is False
    assert client.prompts == []
    assert len([r for r in fake.runs.values() if r["analysis_mode"] == "FULL"]) == 1


def test_rapid_concurrent_clicks_launch_exactly_one_analysis(fake):
    client = MockClient(_payload_for)
    gate = threading.Event()
    real_builder = builder_for()

    def slow_builder(sid):
        gate.wait(2)
        return real_builder(sid)

    outcomes = []

    def click():
        outcomes.append(fas.start_full_analysis(
            8, None, client=client, package_builder=slow_builder,
            execution=fas.EXECUTION_INLINE)["outcome"])

    threads = [threading.Thread(target=click) for _ in range(5)]
    for t in threads:
        t.start()
    gate.set()
    for t in threads:
        t.join(30)
    assert outcomes.count(fas.OUTCOME_CREATED) == 1
    assert len(client.prompts) == 7          # one six-agent analysis, not five
    assert len([r for r in fake.runs.values() if r["analysis_mode"] == "FULL"]) == 1


def test_failed_run_is_not_silently_retried(fake):
    failing = MockClient(_payload_for, fail_for=tuple(fa.SPECIALIST_BRIEFS[s][:40]
                                                      for s in fa.SPECIALIST_IDS))
    first = start(client=failing)
    assert fake.runs[first["run"]["id"]]["status"] == "FAILED"
    client = MockClient(_payload_for)
    again = start(client=client)
    assert again["outcome"] == fas.OUTCOME_EXISTING_FAILED
    assert again["run"]["id"] == first["run"]["id"]
    assert client.prompts == []
    retried = start(client=client, retry=True)          # explicit retry contract
    assert retried["outcome"] == fas.OUTCOME_CREATED
    assert len(client.prompts) == 7
    assert fake.runs[first["run"]["id"]]["status"] == "FAILED"     # history preserved


def test_partial_run_requires_explicit_retry(fake):
    marker = fa.SPECIALIST_BRIEFS[fa.SPECIALIST_COMMERCIAL_CONTRACTUAL][:40]
    first = start(client=MockClient(_payload_for, fail_for=(marker,)))
    assert fake.runs[first["run"]["id"]]["status"] == "PARTIAL"
    client = MockClient(_payload_for)
    assert start(client=client)["outcome"] == fas.OUTCOME_EXISTING_PARTIAL
    assert client.prompts == []


def test_background_execution_starts_one_thread_and_persists_independently(fake):
    client = MockClient(_payload_for)
    out = start(client=client, execution=fas.EXECUTION_BACKGROUND)
    assert out["executing"] is True
    for t in threading.enumerate():
        if t.name == f"full-analysis-run-{out['run']['id']}":
            t.join(30)
    assert fake.runs[out["run"]["id"]]["status"] == "COMPLETE"
    # a "page refresh": state comes back entirely from durable rows
    status = fas.get_full_analysis_status(8)
    assert status["status"] == "COMPLETE" and status["is_terminal"]


def test_no_complete_fast_run_starts_nothing(fake):
    fake.runs.clear()
    fake.add_fast_run(8, 19, status="FAILED")
    with pytest.raises(fas.NoCompleteFastAnalysisError):
        start()
    assert fake.start_calls == 0


# ═══════════════════════════════════════════════════════════════════════
# 3. Progress events
# ═══════════════════════════════════════════════════════════════════════

def _events(fake, run_id):
    return fake.get_full_analysis_events(run_id)


def test_real_specialist_state_transitions_are_recorded_in_order(fake):
    out = start()
    events = _events(fake, out["run"]["id"])
    seqs = [e["sequence"] for e in events]
    assert seqs == list(range(1, len(events) + 1))          # gap-free, strictly ordered
    types = [e["event_type"] for e in events]
    assert types[0] == "RUN_CREATED" and types[1] == "CANONICAL_PACKAGE_READY"
    assert types[-1] == "RUN_COMPLETED"
    for sid in fa.SPECIALIST_IDS:
        mine = [e["event_type"] for e in events if e["specialist_id"] == sid]
        assert mine == ["SPECIALIST_QUEUED", "SPECIALIST_STARTED", "SPECIALIST_COMPLETED"]
    rec_start = types.index("RECONCILIATION_STARTED")
    assert all(types.index(t) < rec_start for t in ("SPECIALIST_COMPLETED",))
    assert max(i for i, t in enumerate(types) if t.startswith("SPECIALIST_")) < rec_start
    assert types.index("RECONCILIATION_COMPLETED") > rec_start
    assert len(events) == 2 + 6 * 3 + 2 + 1


def test_specialist_started_is_recorded_before_its_model_call(fake):
    seen = []

    class ObservingClient(MockClient):
        def _create(self, **kwargs):
            prompt = kwargs["messages"][0]["content"][0]["text"]
            started = {e["specialist_id"] for e in fake.events
                       if e["event_type"] == "SPECIALIST_STARTED"}
            seen.append((prompt, set(started)))
            return super()._create(**kwargs)

    start(client=ObservingClient(_payload_for))
    for prompt, started in seen:
        if "RECONCILIATION" in prompt:
            assert started == set(fa.SPECIALIST_IDS)
            continue
        owner = next(s for s in fa.SPECIALIST_IDS if fa.SPECIALIST_BRIEFS[s][:40] in prompt)
        assert owner in started            # STARTED is durable before the call happens


def test_no_timer_based_percentages_in_events(fake):
    out = start()
    for e in _events(fake, out["run"]["id"]):
        text = str(e["detail"]).lower()
        assert "percent" not in text and "%" not in text and "progress_pct" not in text


def test_events_never_contain_model_reasoning_or_document_text(fake):
    reasoning = "SECRET-CHAIN-OF-THOUGHT"

    def payload(prompt):
        data = _payload_for(prompt)
        for f in data.get("findings", []):
            f["detail"] = reasoning
        return data

    out = start(client=MockClient(payload))
    for e in _events(fake, out["run"]["id"]):
        assert reasoning not in str(e)
        assert "Proponents are to describe" not in str(e)


def test_specialist_failure_produces_failed_event_and_partial_run(fake):
    marker = fa.SPECIALIST_BRIEFS[fa.SPECIALIST_EVALUATION_INTELLIGENCE][:40]
    out = start(client=MockClient(_payload_for, fail_for=(marker,)))
    run = fake.runs[out["run"]["id"]]
    assert run["status"] == "PARTIAL"
    failed = [e for e in _events(fake, run["id"]) if e["event_type"] == "SPECIALIST_FAILED"]
    assert [e["specialist_id"] for e in failed] == [fa.SPECIALIST_EVALUATION_INTELLIGENCE]
    assert "simulated provider failure" in failed[0]["failure_summary"]
    assert _events(fake, run["id"])[-1]["event_type"] == "RUN_PARTIAL"
    assert "EVALUATION_INTELLIGENCE" in run["failure_reason"]


def test_reconciliation_receives_incomplete_domain_information(fake):
    marker = fa.SPECIALIST_BRIEFS[fa.SPECIALIST_SCOPE_DELIVERABLES][:40]
    out = start(client=MockClient(_payload_for, fail_for=(marker,)))
    ev = next(e for e in _events(fake, out["run"]["id"])
              if e["event_type"] == "RECONCILIATION_STARTED")
    assert ev["detail"]["incomplete_domains"] == [fa.SPECIALIST_SCOPE_DELIVERABLES]
    result = fake.results[out["run"]["id"]]["full_analysis_result"]
    assert [d["specialist_id"] for d in result["reconciliation"]["incomplete_domains"]] == \
        [fa.SPECIALIST_SCOPE_DELIVERABLES]


def test_status_derives_specialist_states_and_supports_incremental_polling(fake):
    out = start()
    status = fas.get_full_analysis_status(8, out["run"]["id"])
    assert {s["status"] for s in status["specialists"].values()} == {fas.SPEC_COMPLETE}
    assert status["reconciliation"]["status"] == fas.SPEC_COMPLETE
    assert status["last_sequence"] == len(status["events"])
    newer = fas.get_full_analysis_status(8, out["run"]["id"], after_sequence=20)
    assert [e["sequence"] for e in newer["events"]] == list(range(21, status["last_sequence"] + 1))


def test_live_run_states_are_truthful_mid_execution(fake):
    """A run observed mid-flight: queued/running/complete per specialist
    come only from recorded events, never inferred."""
    run = fake.start_full_analysis_run(8, 19, "fp", "e")["run"]
    rid = run["id"]
    fake.record_full_analysis_event(rid, 8, "CANONICAL_PACKAGE_READY", status="RUNNING")
    for sid in fa.SPECIALIST_IDS:
        fake.record_full_analysis_event(rid, 8, "SPECIALIST_QUEUED", specialist_id=sid,
                                        status="QUEUED")
    fake.record_full_analysis_event(rid, 8, "SPECIALIST_STARTED",
                                    specialist_id=fa.SPECIALIST_IDS[0], status="RUNNING")
    state = fas.get_full_analysis_status(8, rid)["specialists"]
    assert state[fa.SPECIALIST_IDS[0]]["status"] == fas.SPEC_RUNNING
    assert {state[s]["status"] for s in fa.SPECIALIST_IDS[1:]} == {fas.SPEC_QUEUED}


# ═══════════════════════════════════════════════════════════════════════
# 4. Persistence round trip
# ═══════════════════════════════════════════════════════════════════════

def test_six_specialist_results_round_trip(fake):
    out = start()
    stored = fas.get_full_analysis_result(8)
    assert stored["is_complete"] and stored["run"]["id"] == out["run"]["id"]
    rows = stored["specialist_results"]
    assert sorted(r["specialist_id"] for r in rows) == sorted(fa.SPECIALIST_IDS)
    for row in rows:
        assert row["status"] == "COMPLETE"
        assert row["specialist_version"] == fa.SPECIALIST_VERSION
        assert row["result"]["findings"]
        # canonical ids survive; the canonical package itself is never copied
        for f in row["result"]["findings"]:
            if f["finding_type"] != fa.FINDING_INTERPRETATION:
                assert f["canonical_ids"]
        assert "requirements" not in row["result"]
        assert "scoped_criteria" not in row["result"]


def test_reconciliation_and_result_contract_round_trip(fake):
    out = start()
    result = fas.get_full_analysis_result(8)["result"]
    for key in ("specialist_statuses", "specialist_results", "reconciliation",
                "reconciled_findings", "unresolved_gaps", "cross_domain_risks", "ambiguities",
                "completeness_status", "human_confirmation_required", "source_refs",
                "started_at", "completed_at", "wall_seconds", "usage",
                "canonical_snapshot_digest", "input_fingerprint", "fingerprint_inputs",
                "architecture_version", "specialist_versions", "reconciliation_version"):
        assert key in result, key
    assert result["input_fingerprint"] == out["input_fingerprint"]
    assert result["full_analysis_run_id"] == out["run"]["id"]
    assert result["source_analysis_run_id"] == 19
    assert result["reconciliation"]["status"] == fa.STATUS_COMPLETE
    assert result["cross_domain_risks"]
    assert "telemetry" not in result                     # raw per-call rows not duplicated
    assert result["source_refs"]                         # provenance survives


def test_model_usage_metadata_survives(fake):
    out = start()
    tel = fake.runs[out["run"]["id"]]["telemetry"]
    assert tel["provider_calls"] == 7
    assert tel["input_tokens"] == 7 * 1200 and tel["output_tokens"] == 7 * 300
    assert set(tel["by_specialist"]) == set(fa.SPECIALIST_IDS)
    assert tel["reconciliation"]["calls"] == 1
    completed = [e for e in _events(fake, out["run"]["id"])
                 if e["event_type"] == "SPECIALIST_COMPLETED"]
    assert all(e["detail"]["calls"] == 1 and e["detail"]["input_tokens"] == 1200
               for e in completed)


def test_telemetry_links_every_call_to_the_full_run_and_its_specialist(fake, monkeypatch):
    recorded = []
    import model_telemetry
    monkeypatch.setattr(model_telemetry, "record_usage_event",
                        lambda event: recorded.append(event) or event)
    out = start()
    assert len(recorded) == 7
    assert {e["workflow"] for e in recorded} == {"full_analysis"}
    assert {e["analysis_run_id"] for e in recorded} == {out["run"]["id"]}
    assert {e["bid_id"] for e in recorded} == {8}
    ops = sorted(e["operation"] for e in recorded)
    assert ops == sorted([f"specialist_{s.lower()}" for s in fa.SPECIALIST_IDS]
                         + ["reconciliation"])
    assert all(e["input_tokens"] == 1200 and e["model"] == fa.FULL_ANALYSIS_MODEL
               for e in recorded)


# ═══════════════════════════════════════════════════════════════════════
# 5. Failure behaviour
# ═══════════════════════════════════════════════════════════════════════

def test_one_specialist_failure_preserves_other_results(fake):
    marker = fa.SPECIALIST_BRIEFS[fa.SPECIALIST_COMMERCIAL_CONTRACTUAL][:40]
    out = start(client=MockClient(_payload_for, fail_for=(marker,)))
    rows = {r["specialist_id"]: r for r in fake.get_full_analysis_specialist_results(
        out["run"]["id"])}
    assert rows[fa.SPECIALIST_COMMERCIAL_CONTRACTUAL]["status"] == "FAILED"
    assert all(rows[s]["status"] == "COMPLETE" and rows[s]["result"]["findings"]
               for s in fa.SPECIALIST_IDS if s != fa.SPECIALIST_COMMERCIAL_CONTRACTUAL)


def test_failed_reconciliation_preserves_specialist_results(fake):
    out = start(client=MockClient(_payload_for, fail_for=("CROSS-DOMAIN RECONCILIATION",)))
    run = fake.runs[out["run"]["id"]]
    assert run["status"] == "PARTIAL"
    events = [e["event_type"] for e in _events(fake, run["id"])]
    assert "RECONCILIATION_FAILED" in events
    assert len(fake.get_full_analysis_specialist_results(run["id"])) == 6
    result = fake.results[run["id"]]["full_analysis_result"]
    assert result["reconciliation"]["status"] == fa.STATUS_FAILED
    assert result["reconciled_findings"]       # deterministic assurance survived


def test_failed_run_cannot_masquerade_as_complete(fake):
    run = fake.start_full_analysis_run(8, 19, "fp", "e")["run"]
    with pytest.raises(RuntimeError, match="refusing"):
        fake.finalize_full_analysis_run(run["id"], 8, "COMPLETE",
                                        result={"completeness_status": "PARTIAL"})
    assert fake.runs[run["id"]]["status"] == "QUEUED"
    # and the service maps a PARTIAL/FAILED completeness to the matching status
    assert fas._terminal_status_for(fa.COMPLETENESS_PARTIAL) == "PARTIAL"
    assert fas._terminal_status_for(fa.COMPLETENESS_FAILED) == "FAILED"
    assert "result->>'completeness_status'" in MIGRATION_020


def test_exception_during_execution_marks_run_failed(fake):
    def exploding_builder(_sid):
        return fa.build_canonical_package(make_result(), bid_id=8)

    class Boom(MockClient):
        pass

    def broken_run_full_analysis(*a, **k):
        raise RuntimeError("orchestrator crashed")

    import full_analysis
    orig = full_analysis.run_full_analysis
    full_analysis.run_full_analysis = broken_run_full_analysis
    try:
        out = start(builder=exploding_builder, client=Boom(_payload_for))
    finally:
        full_analysis.run_full_analysis = orig
    run = fake.runs[out["run"]["id"]]
    assert run["status"] == "FAILED"
    assert "orchestrator crashed" in run["failure_reason"]
    assert _events(fake, run["id"])[-1]["event_type"] == "RUN_FAILED"


def test_stuck_run_is_detectable_and_only_explicitly_failed(fake):
    run = fake.start_full_analysis_run(8, 19, "fp", "e")["run"]
    fake.record_full_analysis_event(run["id"], 8, "CANONICAL_PACKAGE_READY", status="RUNNING")
    now = fake.clock + timedelta(seconds=60)
    assert fas.get_full_analysis_status(8, run["id"], now=now)["stuck"]["stuck"] is False
    with pytest.raises(fas.RunNotStuckError):
        fas.mark_full_analysis_run_stuck(8, run["id"], now=now)
    later = fake.clock + timedelta(seconds=fas.STUCK_NO_PROGRESS_SECONDS + 1)
    info = fas.get_full_analysis_status(8, run["id"], now=later)["stuck"]
    assert info["stuck"] is True and info["reason"] == "NO_PROGRESS"
    # detection alone never changes state or launches anything
    assert fake.runs[run["id"]]["status"] == "RUNNING" and fake.start_calls == 1
    fas.mark_full_analysis_run_stuck(8, run["id"], now=later)
    assert fake.runs[run["id"]]["status"] == "FAILED"
    assert fake.runs[run["id"]]["failure_detail"]["marked_stuck_by_user"] is True
    assert fake.start_calls == 1                         # no automatic relaunch
    status = fas.get_full_analysis_status(8, run["id"], now=later)
    assert {s["status"] for s in status["specialists"].values()} == {fas.SPEC_SKIPPED}


def test_late_thread_cannot_write_to_a_run_marked_stuck(fake):
    run = fake.start_full_analysis_run(8, 19, "fp", "e")["run"]
    fake.finalize_full_analysis_run(run["id"], 8, "FAILED", failure_reason="stuck")
    with pytest.raises(RuntimeError, match="terminal"):
        fake.record_full_analysis_event(run["id"], 8, "SPECIALIST_STARTED",
                                        specialist_id=fa.SPECIALIST_IDS[0])
    recorder = fas._EventRecorder(run["id"], 8)
    recorder.record("SPECIALIST_STARTED", specialist_id=fa.SPECIALIST_IDS[0])
    assert recorder.aborted is True
    with pytest.raises(RuntimeError, match="already terminal"):
        fake.finalize_full_analysis_run(run["id"], 8, "COMPLETE",
                                        result={"completeness_status": "COMPLETE"})


def test_max_run_age_stuck_rule():
    now = datetime(2026, 9, 22, 13, 0, tzinfo=timezone.utc)
    run = {"status": "RUNNING", "created_at": (now - timedelta(hours=1)).isoformat(),
           "last_progress_at": (now - timedelta(seconds=5)).isoformat()}
    assert fas.is_full_run_stuck(run, now=now)["reason"] == "MAX_RUN_AGE_EXCEEDED"
    assert fas.is_full_run_stuck(dict(run, status="COMPLETE"), now=now)["stuck"] is False


# ═══════════════════════════════════════════════════════════════════════
# 6. Security / tenancy
# ═══════════════════════════════════════════════════════════════════════

def test_cross_bid_isolation(fake):
    out = start()
    # bid 9 has its own Fast run; bid 8's completed result is never reused for it
    client = MockClient(_payload_for)
    other = start(bid_id=9, client=client)
    assert other["outcome"] == fas.OUTCOME_CREATED
    assert other["run"]["id"] != out["run"]["id"]
    # a bid-8 run id cannot be read through bid 9
    with pytest.raises(fas.RunNotFoundError):
        fas.get_full_analysis_status(9, out["run"]["id"])
    with pytest.raises(fas.RunNotFoundError):
        fas.get_full_analysis_result(9, out["run"]["id"])
    # a bid-9 source run cannot seed a bid-8 analysis
    with pytest.raises(fas.NoCompleteFastAnalysisError):
        start(bid_id=8, source_run_id=29)


def test_cross_org_access_is_denied_before_any_work(fake, monkeypatch):
    monkeypatch.setattr(tenancy, "get_bid_for_organization",
                        lambda bid_id, org: {"id": bid_id} if org == "org-a" else None)
    with pytest.raises(tenancy.AccessDeniedError):
        tenancy.start_full_analysis_for_organization(8, "org-b", "key")
    with pytest.raises(tenancy.AccessDeniedError):
        tenancy.get_full_analysis_status_for_organization(8, "org-b")
    with pytest.raises(tenancy.AccessDeniedError):
        tenancy.get_full_analysis_result_for_organization(8, "org-b")
    with pytest.raises(tenancy.AccessDeniedError):
        tenancy.mark_full_analysis_run_stuck_for_organization(8, "org-b", 100)
    assert fake.start_calls == 0 and not fake.events
    # an authorized org asking for another bid's run id is denied too
    out = start()
    with pytest.raises(tenancy.AccessDeniedError):
        tenancy.get_full_analysis_status_for_organization(9, "org-a", out["run"]["id"])


def test_rpc_refuses_cross_bid_event_or_result_forgery(fake):
    run = fake.start_full_analysis_run(8, 19, "fp", "e")["run"]
    with pytest.raises(RuntimeError):
        fake.record_full_analysis_event(run["id"], 9, "SPECIALIST_COMPLETED",
                                        specialist_id=fa.SPECIALIST_IDS[0])
    with pytest.raises(RuntimeError):
        fake.finalize_full_analysis_run(run["id"], 9, "COMPLETE",
                                        result={"completeness_status": "COMPLETE"})
    with pytest.raises(RuntimeError):
        fake.record_full_analysis_event(run["id"], 8, "RUN_COMPLETED")


def test_migration_denies_authenticated_writes_and_anon_access():
    sql = MIGRATION_020
    for fn in ("start_full_analysis_run", "record_full_analysis_event",
               "finalize_full_analysis_run"):
        assert re.search(rf"revoke all on function public\.{fn}\([^)]*\) from anon, authenticated",
                         sql), fn
        assert re.search(rf"grant execute on function public\.{fn}\([^)]*\) to service_role", sql)
        assert re.search(rf"function public\.{fn}\([^;]*?security definer", sql, re.S)
    for table in ("full_analysis_events", "full_analysis_specialist_results"):
        assert f"alter table public.{table} enable row level security" in sql
        assert re.search(rf"on public\.{table} for select to authenticated\s+using "
                         rf"\(public\.can_access_bid\(bid_id\)\)", sql)
        assert not re.search(rf"on public\.{table} for (insert|update|delete|all)", sql)
    assert "to anon" not in sql.replace("from anon", "")
    # append-only / immutable terminal runs, enforced even for service_role
    assert "before update or delete on public.full_analysis_events" in sql
    assert "trg_analysis_runs_guard_full_run" in sql
    # composite same-bid FKs
    assert sql.count("references public.analysis_runs (id, bid_id)") == 2


def test_migration_adds_full_mode_and_keeps_existing_values():
    sql = MIGRATION_020
    assert "check (analysis_mode in ('FAST', 'DEEP_VERIFY', 'FULL'))" in sql
    assert ("'QUEUED', 'PREPARING', 'ANALYZING', 'ASSEMBLING',\n"
            "                      'RUNNING', 'COMPLETE', 'PARTIAL', 'FAILED'") in sql
    assert "where status not in ('COMPLETE', 'PARTIAL', 'FAILED')" in sql
    assert "idx_analysis_runs_full_complete_fingerprint" in sql
    assert "pg_advisory_xact_lock(hashtext('full_analysis_run:'" in sql
    assert "pg_advisory_xact_lock(hashtext('full_analysis_events:'" in sql
    # no canonical Layer 1/2 table is touched
    for forbidden in ("alter table public.requirements", "alter table public.bids",
                      "update public.requirements", "insert into public.requirements"):
        assert forbidden not in sql


def test_committed_migrations_are_unmodified_and_020_is_next():
    names = sorted(p.name for p in (ROOT / "migrations").glob("*.sql"))
    assert names[-1] == "020_full_analysis_runs.sql"
    assert names[-2] == "019_section_draft_claim_mappings.sql"


def test_model_results_never_write_canonical_layers(fake, monkeypatch):
    for name in ("upsert_requirement", "update_bid", "upsert_bid_brief",
                 "create_analysis_result", "update_analysis_run"):
        monkeypatch.setattr(database, name, lambda *a, **k: pytest.fail(f"{name} called"))
    start()


# ═══════════════════════════════════════════════════════════════════════
# 7. MA-1 residual hardening: category-label / id normalization
# ═══════════════════════════════════════════════════════════════════════

CATS = [("CAT-appendix-d1-learning-and-development", CAT_1),
        ("CAT-appendix-d2-hr-advisory", CAT_2),
        ("CAT-appendix-d3-facilitation", "Appendix D3 - Facilitation")]


@pytest.mark.parametrize("raw,expected,status", [
    ("", "", fa.CATEGORY_SCOPE_EMPTY),
    (CAT_1, CAT_1, fa.CATEGORY_SCOPE_EXACT),
    ("CAT-appendix-d2-hr-advisory", CAT_2, fa.CATEGORY_SCOPE_NORMALIZED),
    ("appendix d1 learning and development", CAT_1, fa.CATEGORY_SCOPE_NORMALIZED),
    ("HR Advisory", CAT_2, fa.CATEGORY_SCOPE_NORMALIZED),
    ("Category 1", "Category 1", fa.CATEGORY_SCOPE_UNRECOGNIZED),     # renumbering: fail closed
    ("Appendix", "Appendix", fa.CATEGORY_SCOPE_UNRECOGNIZED),         # ambiguous: 3 labels
    ("D", "D", fa.CATEGORY_SCOPE_UNRECOGNIZED),                       # too short to be safe
    ("Cybersecurity Services", "Cybersecurity Services", fa.CATEGORY_SCOPE_UNRECOGNIZED),
])
def test_category_label_normalization_is_bounded_and_fails_closed(raw, expected, status):
    assert fa.normalize_category_scope(raw, CATS) == (expected, status)


def test_normalization_never_creates_a_category(package_ids=("REQ-0",)):
    accepted, _ = fa.validate_findings(
        [finding(fa.FINDING_FACT, "t", ["REQ-0"], category_scope="Brand New Category")],
        {"REQ-0"}, produced_by="X", categories=CATS)
    assert accepted[0]["category_scope"] == "Brand New Category"
    assert accepted[0]["category_scope_status"] == fa.CATEGORY_SCOPE_UNRECOGNIZED
    assert accepted[0]["human_confirmation_required"] is True


def test_normalized_finding_records_its_original_label():
    accepted, _ = fa.validate_findings(
        [finding(fa.FINDING_FACT, "t", ["REQ-0"], category_scope="HR Advisory")],
        {"REQ-0"}, produced_by="X", categories=CATS)
    assert accepted[0]["category_scope"] == CAT_2
    assert accepted[0]["category_scope_normalized_from"] == "HR Advisory"


def test_canonical_id_normalization_is_unique_match_only():
    permitted = {"REQ-0", "CRIT-appendix-d1-x"}
    assert fa.normalize_canonical_id("req-0", permitted) == "REQ-0"
    assert fa.normalize_canonical_id(" CRIT-APPENDIX-D1-X ", permitted) == "CRIT-appendix-d1-x"
    assert fa.normalize_canonical_id("REQ-99", permitted) is None
    assert fa.normalize_canonical_id("Corporate Profile", permitted) is None
    accepted, rejected = fa.validate_findings(
        [finding(fa.FINDING_RISK, "r", ["req-0"]),
         finding(fa.FINDING_RISK, "bad", ["Corporate Profile"])],
        permitted, produced_by="X")
    assert accepted[0]["canonical_ids"] == ["REQ-0"]
    assert accepted[0]["canonical_id_normalizations"] == [{"from": "req-0", "to": "REQ-0"}]
    assert rejected[0]["reason"] == "UNCITED_OR_UNKNOWN_CANONICAL_ID"     # still fails closed


def test_specialist_prompts_list_allowed_category_ids():
    pkg = fa.build_canonical_package(make_result(), bid_id=8)
    for sid in fa.SPECIALIST_IDS:
        slice_payload = fa.build_specialist_input(pkg, sid)
        prompt = fa._build_specialist_prompt(sid, slice_payload)
        if fa.OBJ_SERVICE_CATEGORY in fa.SPECIALIST_INPUT_TYPES[sid]:
            for cat in pkg.service_categories:
                assert f'{cat["canonical_id"]}  =  {cat["label"]}' in prompt
            assert "Category 1" in prompt and "NOT valid" in prompt
        else:
            assert '"category_scope" MUST be the empty string' in prompt


def test_run_specialist_normalizes_paraphrased_labels_end_to_end():
    pkg = fa.build_canonical_package(make_result(), bid_id=8)
    crit = next(c for c in pkg.scoped_criteria if c["category_scope"] == CAT_1)

    def payload(prompt):
        return {"findings": [finding(fa.FINDING_FACT, "f", [crit["canonical_id"]],
                                     category_scope="learning and development")]}

    res = fa.run_specialist(pkg, fa.SPECIALIST_EVALUATION_INTELLIGENCE,
                            client=MockClient(payload), telemetry=[])
    assert res.findings[0]["category_scope"] == CAT_1
    issues = fa.detect_category_scope_inconsistencies(pkg, [res])
    assert issues == []


# ═══════════════════════════════════════════════════════════════════════
# 8. Regression: FAST untouched, MA-1 behaviour and CI layers untouched
# ═══════════════════════════════════════════════════════════════════════

def test_fast_analysis_start_path_is_unchanged():
    import analysis_service
    import fast_analysis
    src = Path(analysis_service.__file__).read_text(encoding="utf-8")
    fast_part = src.split("FULL_ANALYSIS_PERSISTENCE_GAP = (")[0]
    assert "full_analysis" not in fast_part
    assert "full_analysis" not in Path(fast_analysis.__file__).read_text(encoding="utf-8")
    assert 'db.create_analysis_run(bid_id, "FAST"' in src
    assert analysis_service.FAST_ANALYSIS_ENGINE_VERSION == "fast-analysis-v4"


def test_active_fast_run_lookup_treats_partial_as_terminal():
    src = Path(database.__file__).read_text(encoding="utf-8")
    assert '.not_.in_("status", ["COMPLETE", "PARTIAL", "FAILED"])' in src


def test_legacy_mode_less_latest_result_ignores_full_runs(monkeypatch):
    class Q:
        def __init__(self, rows):
            self.rows = rows

        def __getattr__(self, name):
            return lambda *a, **k: self

        def execute(self):
            return type("R", (), {"data": self.rows})()

    tables = {"analysis_runs": [{"id": 2, "analysis_mode": "FULL", "status": "COMPLETE"},
                                {"id": 1, "analysis_mode": "FAST", "status": "COMPLETE"}],
              "analysis_results": [{"run_id": 1, "structured_intelligence": {"fast": True}}]}

    class Client:
        def table(self, name):
            return Q(tables[name])

    monkeypatch.setattr(tenancy.auth_client, "get_authenticated_client", lambda t: Client())
    out = tenancy.get_bid_analysis_authenticated("tok", 8)
    assert len(out["runs"]) == 2
    assert out["latest_result"]["structured_intelligence"] == {"fast": True}


def test_ma1_compute_and_return_path_still_makes_seven_calls_without_persistence():
    pkg = fa.build_canonical_package(make_result(), bid_id=8)
    client = MockClient(_payload_for)
    result = fa.run_full_analysis(pkg, client=client)       # no on_event, no telemetry ctx
    assert len(client.prompts) == 7
    assert result.completeness_status == fa.COMPLETENESS_COMPLETE


def test_frozen_canonical_layers_untouched_by_ma2a():
    import subprocess
    diff = subprocess.run(
        ["git", "diff", "--name-only", "ee1cf42", "--", "canonical_procurement.py",
         "procurement_normalization.py", "document_provenance.py", "fast_analysis.py"],
        cwd=ROOT, capture_output=True, text=True)
    if diff.returncode != 0:
        pytest.skip("git history unavailable")
    assert diff.stdout.strip() == ""
