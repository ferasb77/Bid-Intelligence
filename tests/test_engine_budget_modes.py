"""Per-mode budgets, worst-case reservations, stage refusals, checkpoints and
the FAST pipeline. Scripted answers routed through the real ledger -- no
network, no live model call."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import engine_synthetic as S  # noqa: E402

from engine import budget, pipeline  # noqa: E402
from engine.checkpoints import CachingAnalyst, MemoryStore, checkpoint_key, with_checkpoints  # noqa: E402
from engine.package import build_package  # noqa: E402
from engine.providers import (CostLimitExceeded, RoutedAnalyst, ScriptedAnalyst, StageBudgetExceeded,  # noqa: E402
                              Usage, UsageLedger, worst_case_usd)


class Priced(ScriptedAnalyst):
    """Scripted answers, but a priced, non-synthetic model: every call reserves
    its worst case on the ledger first, exactly like the real providers."""

    def __init__(self, responder, model="claude-haiku-5-5", name="p", tokens=(1000, 500)):
        super().__init__(responder, name=name, provider="anthropic", model=model)
        self.synthetic = False
        self.config = {"effort": "low"}
        self.tokens, self.calls = tokens, []

    def call_json(self, system, user, schema, *, purpose, ledger, data_class, max_tokens=32000):
        rid = ledger.before_call(self.provider, self.model, purpose, len(system) + len(str(user)), max_tokens)
        self.calls.append(purpose)
        data = self.responder(purpose, system, user if isinstance(user, str) else "\n\n".join(user), schema)
        ledger.add(Usage(self.provider, self.model, purpose, input_tokens=self.tokens[0],
                         output_tokens=self.tokens[1], reservation=rid))
        return data


def pkg():
    return build_package(S.documents(), data_class="CLIENT")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("ENGINE_MAX_COST_USD", "ENGINE_FAST_MAX_COST_USD", "ENGINE_FULL_MAX_COST_USD"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


# ── ledger: reservations and stage allotments ──────────────────────────────

def test_worst_case_counts_full_output_and_web_searches():
    w = worst_case_usd("anthropic", "claude-opus-5-5", 3500, 1000)        # 1000 in at $5 (cache write) + 1000 out
    assert w == pytest.approx(0.005 + 0.02)
    assert worst_case_usd("anthropic", "claude-opus-5-5", 0, 0, web_searches=3) == pytest.approx(0.03)
    assert worst_case_usd("anthropic", "unpriced", 10, 10) is None


def test_concurrent_reservations_cannot_overcommit_the_cap():
    lg = UsageLedger("t", path="", max_cost_usd=0.05)
    lg.before_call("anthropic", "claude-opus-5-5", "adjudicate", 0, 1000)   # reserves $0.02
    lg.before_call("anthropic", "claude-opus-5-5", "adjudicate", 0, 1000)   # $0.04 reserved
    with pytest.raises(CostLimitExceeded):
        lg.before_call("anthropic", "claude-opus-5-5", "adjudicate", 0, 1000)
    assert lg.committed_usd() == pytest.approx(0.04) and lg.spent_usd() == 0


def test_released_reservation_frees_the_budget():
    lg = UsageLedger("t", path="", max_cost_usd=0.03)
    rid = lg.before_call("anthropic", "claude-opus-5-5", "analysis", 0, 1000)
    lg.release(rid)
    assert lg.committed_usd() == 0
    lg.before_call("anthropic", "claude-opus-5-5", "analysis", 0, 1000)


def test_stage_allotment_refuses_without_stopping_the_run():
    lg = UsageLedger("t", path="", max_cost_usd=1.0, stage_budgets={"adjudicate": 0.01, "analysis": 0.5,
                                                                     "reserve": 0.0})
    with pytest.raises(StageBudgetExceeded, match="refused before sending"):
        lg.before_call("anthropic", "claude-opus-5-5", "adjudicate", 0, 1000)
    assert lg.cost_limit_hit is None and lg.refusals[0]["kind"] == "STAGE_BUDGET"
    lg.before_call("anthropic", "claude-opus-5-5", "analysis", 0, 1000)       # other stages still run


def test_stage_may_draw_on_the_shared_reserve_once():
    lg = UsageLedger("t", path="", max_cost_usd=1.0, stage_budgets={"conflicts": 0.0, "reserve": 0.03})
    rid = lg.before_call("anthropic", "claude-opus-5-5", "conflicts", 0, 1000)  # $0.02 from the reserve
    lg.add(Usage("anthropic", "claude-opus-5-5", "conflicts", output_tokens=1000, reservation=rid))
    with pytest.raises(StageBudgetExceeded):
        lg.before_call("anthropic", "claude-opus-5-5", "conflicts", 0, 1000)    # only $0.01 of reserve left


def test_mode_caps_and_budgets():
    assert budget.cap("FAST") == 0.50 and budget.cap("FULL") == 2.00
    for mode in budget.MODES:
        assert sum(budget.stage_budgets(mode).values()) <= budget.cap(mode) + 1e-9
    assert "buyer_research" not in budget.STAGE_BUDGETS["FAST"]
    with pytest.raises(ValueError):
        budget.cap("MEDIUM")


def test_lowered_cap_scales_the_allotments(clean_env):
    clean_env.setenv("ENGINE_FULL_MAX_COST_USD", "1.00")
    b = budget.stage_budgets("FULL")
    assert budget.cap("FULL") == 1.00 and sum(b.values()) == pytest.approx(1.00, abs=1e-3)


def test_mode_cap_never_exceeds_the_application_cap(clean_env):
    clean_env.setenv("ENGINE_MAX_COST_USD", "0.30")
    clean_env.setenv("ENGINE_FAST_MAX_COST_USD", "5")
    assert budget.cap("FAST") == 0.30


# ── checkpoints ────────────────────────────────────────────────────────────

def test_identical_request_is_served_from_the_checkpoint_at_zero_cost():
    inner = Priced(S.responder("A"))
    a, lg = CachingAnalyst(inner, MemoryStore()), UsageLedger("t", path="")
    u = "SOURCE: x\nAccount for each SECTION_ID: S1"
    first = a.call_json("sys", u, {}, purpose="extract:U1", ledger=lg, data_class="CLIENT", max_tokens=100)
    again = a.call_json("sys", u, {}, purpose="extract:U1", ledger=lg, data_class="CLIENT", max_tokens=100)
    assert first == again and inner.calls == ["extract:U1"]
    s = lg.summary()["by_stage"]["extract"]
    assert s["calls"] == 1 and s["from_checkpoint"] == 1


def test_any_change_to_the_request_misses_the_checkpoint():
    a = Priced(S.responder("A"))
    k = checkpoint_key(a, "sys", "user", {}, 100)
    assert k != checkpoint_key(a, "sys", "user2", {}, 100)
    assert k != checkpoint_key(a, "sys2", "user", {}, 100)
    assert k != checkpoint_key(a, "sys", "user", {}, 200)
    b = Priced(S.responder("A"), model="claude-opus-5-5")
    assert k != checkpoint_key(b, "sys", "user", {}, 100)


def test_synthetic_answers_are_never_checkpointed():
    store = MemoryStore()
    a = with_checkpoints(ScriptedAnalyst(S.adjudicator(), name="adj"), store)
    a.call_json("s", "u", {}, purpose="final_review", ledger=UsageLedger("t", path=""), data_class="SYNTHETIC")
    assert store.data == {}


# ── FAST and FULL runs ─────────────────────────────────────────────────────

def _fast_roles():
    return pipeline.EngineRoles(primary=Priced(S.responder("A"), name="extractor"), independent=None,
                                adjudicator=None, writer=Priced(S.adjudicator(), "claude-sonnet-5-5", "writer"))


def test_fast_run_is_single_analyst_with_no_opus_and_no_review():
    roles = _fast_roles()
    r = pipeline.run(pkg(), roles, mode="FAST", ledger=pipeline.new_ledger("FAST", path=""))
    rec = r.record
    assert rec["status"] == "COMPLETE", rec.get("error")
    assert rec["mode"] == "FAST" and rec["verification"] == "SINGLE_ANALYST"
    assert set(roles.writer.calls) == {"analysis"}
    assert not any(p in ("package_review", "adjudicate", "conflicts", "final_review")
                   for p in roles.primary.calls + roles.writer.calls)
    assert rec["stages"]["review"]["status"] == "DETERMINISTIC_ONLY"
    assert rec["usage"]["total_cost_usd"] <= budget.cap("FAST")
    assert r.composed["full"] is None and r.composed["fast"]["verification"]["status"] == "SINGLE_ANALYST"
    assert any("FAST triage" in x for x in rec["limitations"])
    assert "opus" not in str(rec["models"]).lower()


def test_full_run_reuses_the_fast_extraction():
    store = MemoryStore()
    fast = _fast_roles()
    r1 = pipeline.run(pkg(), fast, mode="FAST", ledger=pipeline.new_ledger("FAST", path=""), store=store)
    assert r1.record["status"] == "COMPLETE"
    n_extract = len(fast.primary.calls)

    extractor = Priced(S.responder("A"), name="extractor")       # same model, effort and prompts as FAST's
    reviewer = Priced(S.responder("A"), "claude-opus-5-5", "primary-review")
    adj = Priced(S.adjudicator(), "claude-opus-5-5", "adj")
    full = pipeline.EngineRoles(primary=RoutedAnalyst(extractor, reviewer, name="primary"), independent=None,
                                adjudicator=adj)
    lg = pipeline.new_ledger("FULL", path="")
    r2 = pipeline.run(pkg(), full, mode="FULL", ledger=lg, store=store)
    assert r2.record["status"] == "COMPLETE", r2.record.get("error")
    assert extractor.calls == []                                   # every page came from FAST's checkpoints
    assert lg.summary()["by_stage"]["extract"]["from_checkpoint"] == n_extract
    assert reviewer.calls == ["package_review"] and "final_review" in adj.calls
    assert r2.record["mode"] == "FULL"


def test_exhausted_adjudication_allotment_is_disclosed_not_hidden(clean_env):
    full = pipeline.EngineRoles(primary=RoutedAnalyst(Priced(S.responder("A"), name="x"),
                                                      Priced(S.responder("A"), "claude-opus-5-5", "r"),
                                                      name="primary"),
                                independent=Priced(S.responder("B"), name="b"),
                                adjudicator=Priced(S.adjudicator(), "claude-opus-5-5", "adj"))
    lg = UsageLedger("t", path="", max_cost_usd=2.0,
                     stage_budgets=dict(budget.STAGE_BUDGETS["FULL"], adjudicate=0.0, reserve=0.0))
    r = pipeline.run(pkg(), full, mode="FULL", ledger=lg)
    adj_stage = r.record["stages"]["adjudicate"]
    assert adj_stage["targets"] > 0
    assert adj_stage["status"] == "PARTIAL" and adj_stage["deferred_batches"] >= 1
    assert any("adjudication budget" in x for x in r.record["limitations"])
    assert "adjudicate" not in full.adjudicator.calls
    assert any(x["kind"] == "STAGE_BUDGET" for x in lg.summary()["refusals"])
    assert r.record["verification"] != "INDEPENDENTLY_VERIFIED"


def test_run_stops_before_any_call_when_nothing_fits():
    roles = _fast_roles()
    lg = UsageLedger("t", path="", max_cost_usd=0.001)
    r = pipeline.run(pkg(), roles, mode="FAST", ledger=lg)
    assert r.record["status"] == "FAILED" and r.record["error"]["kind"] == "COST_LIMIT_EXCEEDED"
    assert roles.primary.calls == [] and roles.writer.calls == []


def test_unknown_mode_is_refused():
    with pytest.raises(ValueError):
        pipeline.run(pkg(), _fast_roles(), mode="MEDIUM")


# ── preflight ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("mode", budget.MODES)
def test_preflight_fits_a_small_package(mode):
    pf = budget.preflight(pkg(), mode, extract_model="claude-haiku-5-5", synthesis_model="claude-opus-5-5",
                          writer_model="claude-sonnet-5-5")
    assert pf["ok"], pf["problems"]
    assert pf["worst_case_required_usd"] <= pf["cap_usd"]


# ── buyer research under the run's ledger ──────────────────────────────────

class _Resp:
    def __init__(self, content, stop="end_turn", usage=None):
        self._d = {"content": content, "stop_reason": stop,
                   "usage": usage or {"input_tokens": 2000, "output_tokens": 500,
                                      "server_tool_use": {"web_search_requests": 2}}}

    def model_dump(self):
        return self._d


class _Client:
    def __init__(self, *resps):
        self.calls, self.resps = [], list(resps)
        self.beta = self.messages = self

    def with_options(self, **kw):
        return self

    def create(self, **kw):
        self.calls.append(kw)
        return self.resps.pop(0)


def test_buyer_research_is_reserved_and_recorded_on_the_ledger():
    import buyer_research
    lg = pipeline.new_ledger("FULL", path="")
    client = _Client(_Resp([{"type": "text", "text": "<items>[]</items>"}]))
    out = buyer_research.run_research("Buyer", "Title", None, None, anthropic_client=client,
                                      fetch=lambda u: None, ledger=lg)
    assert out["status"] == "COMPLETE"
    kw = client.calls[0]
    assert kw["max_tokens"] == buyer_research.LEDGER_MAX_TOKENS
    assert kw["tools"][0]["max_uses"] == buyer_research.LEDGER_MAX_SEARCHES
    st = lg.summary()["by_stage"]["buyer_research"]
    assert st["calls"] == 1 and st["web_search_requests"] == 2
    assert st["cost_usd"] == pytest.approx((2000 * 4 + 500 * 20) / 1e6 + 0.02)
    assert lg.committed_usd() == pytest.approx(lg.spent_usd())         # no reservation left behind


def test_buyer_research_is_skipped_when_its_budget_is_gone():
    import buyer_research
    lg = UsageLedger("t", path="", max_cost_usd=2.0, stage_budgets={"buyer_research": 0.0, "reserve": 0.0})
    client = _Client()
    out = buyer_research.run_research("Buyer", "Title", None, None, anthropic_client=client,
                                      fetch=lambda u: None, ledger=lg)
    assert out["status"] == "SKIPPED" and "refused before sending" in out["error"]
    assert client.calls == []


def test_buyer_research_stops_paused_turns_at_the_budget():
    import buyer_research
    lg = UsageLedger("t", path="", max_cost_usd=2.0, stage_budgets={"buyer_research": 0.20, "reserve": 0.0})
    client = _Client(_Resp([{"type": "text", "text": "<items>[]</items>"}], stop="pause_turn",
                           usage={"input_tokens": 30000, "output_tokens": 3000,
                                  "server_tool_use": {"web_search_requests": 3}}))
    out = buyer_research.run_research("Buyer", "Title", None, None, anthropic_client=client,
                                      fetch=lambda u: None, ledger=lg)
    assert len(client.calls) == 1 and out["status"] == "COMPLETE" and out.get("budget_note")
    assert lg.spent_usd() <= 0.20 + 0.11      # one round's actual cost; the second round was never sent


def test_research_runs_after_final_review_and_only_in_full():
    seen = []

    def research_fn(analysis, ledger):
        seen.append(ledger.remaining_usd("buyer_research"))
        return {"status": "SKIPPED"}
    full = pipeline.EngineRoles(primary=RoutedAnalyst(Priced(S.responder("A"), name="x"),
                                                      Priced(S.responder("A"), "claude-opus-5-5", "r"),
                                                      name="primary"),
                                independent=None, adjudicator=Priced(S.adjudicator(), "claude-opus-5-5", "adj"))
    r = pipeline.run(pkg(), full, mode="FULL", ledger=pipeline.new_ledger("FULL", path=""), research_fn=research_fn)
    stages = list(r.record["stages"])
    assert stages.index("buyer_research") > stages.index("review") and seen and seen[0] > 0
    r2 = pipeline.run(pkg(), _fast_roles(), mode="FAST", ledger=pipeline.new_ledger("FAST", path=""),
                      research_fn=research_fn)
    assert "buyer_research" not in r2.record["stages"] and len(seen) == 1


# ── service: one active run per bid, pre-flight before anything is created ─

class _DB:
    def __init__(self, runs):
        self.runs, self.created = runs, []

    def get_engine_runs(self, bid_id):
        return self.runs

    def create_engine_run(self, *a, **kw):
        self.created.append(kw)
        return {"id": 99}


def _service(monkeypatch, runs):
    from engine import service
    db = _DB(runs)
    monkeypatch.setitem(sys.modules, "database", db)
    monkeypatch.setattr(service, "load_bid_package", lambda bid_id: pkg())
    monkeypatch.setattr(service, "_execute", lambda *a: None)
    return service, db


def test_service_refuses_a_second_active_run(monkeypatch):
    from datetime import datetime, timezone
    service, db = _service(monkeypatch, [{"id": 5, "status": "RUNNING",
                                          "last_progress_at": datetime.now(timezone.utc).isoformat()}])
    with pytest.raises(service.EngineBusy):
        service.start(1, "org", mode="FAST", roles=_fast_roles(), execution="inline")
    assert db.created == []


def test_service_refuses_a_run_whose_preflight_fails(monkeypatch, clean_env):
    service, db = _service(monkeypatch, [])
    clean_env.setenv("ENGINE_FAST_MAX_COST_USD", "0.001")
    with pytest.raises(service.EngineBudgetRefused):
        service.start(1, "org", mode="FAST", roles=_fast_roles(), execution="inline")
    assert db.created == []


def test_service_records_the_mode(monkeypatch):
    service, db = _service(monkeypatch, [{"id": 4, "status": "COMPLETE", "model_config": {"mode": "FAST"}}])
    monkeypatch.setattr(service, "engine_api_key", lambda: None)
    service.start(1, "org", mode="FULL", roles=pipeline.EngineRoles(
        primary=RoutedAnalyst(Priced(S.responder("A")), Priced(S.responder("A"), "claude-opus-5-5"), name="p"),
        independent=None, adjudicator=Priced(S.adjudicator(), "claude-opus-5-5")), execution="background")
    cfg = db.created[0]["model_config"]
    assert cfg["mode"] == "FULL" and cfg["cap_usd"] == 2.0 and cfg["preflight_worst_usd"] <= 2.0
    assert service.run_mode({"model_config": cfg}) == "FULL" and service.run_mode({}) is None
