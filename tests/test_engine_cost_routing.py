"""Model routing (Haiku extraction, Opus synthesis at medium effort, Sonnet
FAST writer) and the per-run cost circuit breaker (ENGINE_MAX_COST_USD). Fake provider clients only -- no
network, no live model call."""
from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import engine_synthetic as S  # noqa: E402

from engine import pipeline  # noqa: E402
from engine.package import build_package  # noqa: E402
from engine.providers import (AnthropicAnalyst, CostLimitExceeded, RoutedAnalyst, ScriptedAnalyst,  # noqa: E402
                              UsageLedger, max_cost_usd)


class _Stream:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.msg


class FakeAnthropic:
    """Records every request; answers with `answer(text)` and fixed usage."""

    def __init__(self, answer=lambda text: {}, input_tokens=100, output_tokens=100):
        self.calls, self.answer = [], answer
        self.usage = (input_tokens, output_tokens)
        self.messages = NS(stream=self._stream)

    def _stream(self, **kw):
        self.calls.append(kw)
        text = "\n\n".join(b["text"] for b in kw["messages"][0]["content"]) \
            if isinstance(kw["messages"][0]["content"], list) else kw["messages"][0]["content"]
        return _Stream(NS(stop_reason="end_turn", _request_id="req",
                          content=[NS(type="text", text=json.dumps(self.answer(text)))],
                          usage=NS(input_tokens=self.usage[0], output_tokens=self.usage[1],
                                   cache_read_input_tokens=0, cache_creation_input_tokens=0)))


def ledger(**kw):
    return UsageLedger("test", path="", **kw)


def call(analyst, purpose, lg=None, max_tokens=32000):
    return analyst.call_json("system", ("context", "body"), {}, purpose=purpose, ledger=lg or ledger(),
                             data_class="SYNTHETIC", max_tokens=max_tokens)


@pytest.fixture
def clean_env(monkeypatch):
    for k in ("ENGINE_EXTRACT_MODEL", "ENGINE_EXTRACT_EFFORT", "ENGINE_MAX_COST_USD", "ENGINE_SYNTHESIS_EFFORT",
              "ENGINE_WRITER_MODEL", "ENGINE_WRITER_EFFORT", "ENGINE_FAST_MAX_COST_USD", "ENGINE_FULL_MAX_COST_USD"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def _wire(roles):
    """Fake clients on every Anthropic model behind the default roles."""
    fakes = {}
    for a in (roles.primary.extractor, roles.primary.default, roles.adjudicator):
        a._client = fakes[a.name] = FakeAnthropic()
    return fakes


# ── (a) routing ────────────────────────────────────────────────────────────

def test_extraction_uses_haiku_low_effort_and_synthesis_uses_opus_medium(clean_env):
    roles = pipeline.default_roles(anthropic_key="test-key", independent=None)
    fakes = _wire(roles)
    assert isinstance(roles.primary, RoutedAnalyst) and roles.primary.provider == "anthropic"

    call(roles.primary, "extract:U1")
    call(roles.primary, "extract:U1s2")
    call(roles.primary, "package_review")
    for purpose in ("adjudicate", "conflicts", "analysis", "review"):
        call(roles.adjudicator, purpose)

    ext = fakes["claude-extractor"].calls
    assert len(ext) == 2
    assert {c["model"] for c in ext} == {"claude-haiku-5-5"}
    assert {c["output_config"]["effort"] for c in ext} == {"low"}
    review = fakes["claude-primary-review"].calls
    synth = fakes["claude-adjudicator"].calls
    assert len(review) == 1 and len(synth) == 4
    assert {c["model"] for c in review + synth} == {"claude-opus-5-5"}
    assert {c["output_config"]["effort"] for c in review + synth} == {"medium"}
    assert roles.adjudicator.model == "claude-opus-5-5"


def test_extraction_model_and_effort_are_configurable(clean_env):
    clean_env.setenv("ENGINE_EXTRACT_MODEL", "claude-opus-5-5")
    clean_env.setenv("ENGINE_EXTRACT_EFFORT", "medium")
    roles = pipeline.default_roles(anthropic_key="test-key", independent=None)
    fakes = _wire(roles)
    call(roles.primary, "extract:U3")
    kw = fakes["claude-extractor"].calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["output_config"]["effort"] == "medium"


def test_run_record_names_both_primary_models(clean_env):
    roles = pipeline.default_roles(anthropic_key="test-key", independent=None)
    cfg = roles.primary.describe()["config"]
    assert cfg["extract"]["model"] == "claude-haiku-5-5" and cfg["default"]["model"] == "claude-opus-5-5"


def test_fast_roles_use_no_opus(clean_env):
    roles = pipeline.default_roles(anthropic_key="test-key", independent="openai", mode="FAST")
    assert roles.independent is None
    assert roles.primary.model == "claude-haiku-5-5" and roles.primary.config.get("effort") == "low"
    assert roles.writer.model == "claude-sonnet-5-5" and roles.writer.config.get("effort") == "medium"
    assert "opus" not in json.dumps([roles.primary.describe(), roles.writer.describe()])


def test_synthesis_effort_is_configurable(clean_env):
    clean_env.setenv("ENGINE_SYNTHESIS_EFFORT", "high")
    roles = pipeline.default_roles(anthropic_key="test-key", independent=None)
    fakes = _wire(roles)
    call(roles.adjudicator, "adjudicate")
    assert fakes["claude-adjudicator"].calls[0]["output_config"]["effort"] == "high"


# ── (b) cost circuit breaker ───────────────────────────────────────────────

def test_default_cap_is_two_dollars(clean_env):
    assert max_cost_usd() == 2.00 and ledger().max_cost_usd == 2.00
    clean_env.setenv("ENGINE_MAX_COST_USD", "0.75")
    assert ledger().max_cost_usd == 0.75


def test_call_is_refused_before_it_is_sent_when_its_worst_case_does_not_fit(clean_env):
    # worst case of each call: 2000 out x $20/M = $0.04 (+ a few input tokens);
    # actual: 1000 in x $4/M + 1500 out x $20/M = $0.034
    fake = FakeAnthropic(input_tokens=1000, output_tokens=1500)
    a = AnthropicAnalyst("claude-opus-5-5", client=fake, name="adj")
    lg = ledger(max_cost_usd=0.05)
    call(a, "adjudicate", lg, max_tokens=2000)
    with pytest.raises(CostLimitExceeded, match="refused before sending"):
        call(a, "conflicts", lg, max_tokens=2000)   # $0.034 + up to $0.04 > $0.05
    assert len(fake.calls) == 1              # the refused request was never sent
    assert lg.spent_usd() == pytest.approx(0.034) and lg.spent_usd() <= 0.05
    s = lg.summary()
    assert s["cost_limit_hit"] and s["max_cost_usd"] == 0.05 and s["refusals"][0]["purpose"] == "conflicts"


def test_unpriced_model_is_refused_because_the_cap_cannot_be_enforced(clean_env):
    fake = FakeAnthropic()
    a = AnthropicAnalyst("claude-unpriced-model", client=fake, name="x")
    with pytest.raises(CostLimitExceeded, match="no price"):
        call(a, "extract:U1")
    assert fake.calls == []


def test_exceeding_the_cap_aborts_the_run_cleanly(clean_env):
    clean_env.setenv("ENGINE_MAX_COST_USD", "0.05")
    clean_env.setenv("ENGINE_CONCURRENCY", "1")
    respond = S.responder("A")

    def answer(text):
        purpose = "package_review" if "YOUR FINDINGS:" in text else "extract:x"
        return respond(purpose, "", text, {})
    fake = FakeAnthropic(answer, input_tokens=1000, output_tokens=2000)
    primary = AnthropicAnalyst("claude-opus-5-5", client=fake, name="primary")
    roles = pipeline.EngineRoles(primary=primary, independent=None,
                                 adjudicator=ScriptedAnalyst(S.adjudicator(), name="adj"))
    lg = ledger()
    r = pipeline.run(build_package(S.documents(), data_class="SYNTHETIC"), roles, ledger=lg)

    assert r.record["status"] == "FAILED" and r.record["verification"] == "FAILED"
    assert r.record["error"]["kind"] == "COST_LIMIT_EXCEEDED"
    assert "refused before sending" in r.record["error"]["message"]
    assert fake.calls == []                  # one extraction call could cost more than the cap: none was sent
    assert r.record["usage"]["total_cost_usd"] == 0
    assert not r.composed                    # no report is produced from an aborted run
