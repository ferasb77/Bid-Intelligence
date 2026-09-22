"""
MA-2A.2: Specialist output truncation integrity.

Fully deterministic and synthetic: ZERO live provider calls. Provider
responses are mocked, including responses carrying the Anthropic Messages
API termination field `stop_reason="max_tokens"` with a JSON body cut off
mid-structure, exactly as a real output-ceiling truncation arrives.
Persistence uses MA-2A's in-memory stand-in for migration 020.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import full_analysis as fa
import full_analysis_service as fas
from tests.test_full_analysis_ma1 import _payload_for, finding, make_result
from tests.test_full_analysis_ma2a import builder_for, fake, start  # noqa: F401 (fixture)

EVAL = fa.SPECIALIST_EVALUATION_INTELLIGENCE
COMM = fa.SPECIALIST_COMMERCIAL_CONTRACTUAL


class _Resp:
    def __init__(self, text, stop_reason, output_tokens=300):
        self.content = [SimpleNamespace(text=text)]
        self.usage = SimpleNamespace(input_tokens=1200, output_tokens=output_tokens)
        self.stop_reason = stop_reason


def _truncated_text(payload: dict) -> str:
    """Full JSON cut in the middle of its last list item (mid-structure)."""
    text = json.dumps(payload)
    return text[: int(len(text) * 0.8)]


class TruncClient:
    """`truncate_for`: prompt markers whose call ends stop_reason=max_tokens
    with a mid-structure-truncated body. `garbage_for`: markers whose call
    ends max_tokens with no recoverable JSON. `malformed_for`: normal stop
    but unparseable body (existing malformed-output behavior)."""

    def __init__(self, truncate_for=(), garbage_for=(), malformed_for=(), fail_for=()):
        self.truncate_for, self.garbage_for = tuple(truncate_for), tuple(garbage_for)
        self.malformed_for, self.fail_for = tuple(malformed_for), tuple(fail_for)
        self.prompts: list[str] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        prompt = kwargs["messages"][0]["content"][0]["text"]
        self.prompts.append(prompt)
        head = prompt[:200]
        if any(m in head for m in self.fail_for):
            raise RuntimeError("simulated provider failure")
        if any(m in head for m in self.garbage_for):
            return _Resp('{"findings": [{"finding_type": "FA', "max_tokens", 3000)
        if any(m in head for m in self.malformed_for):
            return _Resp("not json at all", "end_turn")
        payload = _payload_for(prompt)
        if "RECONCILIATION" in head:
            # completeness_note first, then several risks so a cut keeps some.
            ids = payload["cross_domain_risks"][0]["canonical_ids"]
            payload = {"completeness_note": "Note.",
                       "cross_domain_risks": [dict(payload["cross_domain_risks"][0],
                                                   title=f"Risk {i}", canonical_ids=ids)
                                              for i in range(4)],
                       "contradictions": [], "unresolved_ambiguities": [],
                       "human_confirmation_required": []}
        elif "findings" in payload:
            payload["findings"] = payload["findings"] * 2
        if any(m in head for m in self.truncate_for):
            return _Resp(_truncated_text(payload), "max_tokens", 3000)
        return _Resp(json.dumps(payload), "end_turn")


def _package():
    return fa.build_canonical_package(make_result(), bid_id=8, analysis_run_id=19)


# ── 1. provider metadata -> specialist status ─────────────────────────────

def test_max_tokens_is_not_treated_as_complete_and_valid_findings_survive():
    res = fa.run_specialist(_package(), EVAL, client=TruncClient(truncate_for=("EVALUATION",)),
                            telemetry=[])
    assert res.status == fa.STATUS_PARTIAL
    assert res.output_truncated is True and res.stop_reason == "max_tokens"
    assert res.parse_status == "RECOVERED_TRUNCATED"
    assert res.findings, "valid partial structured output must be preserved"
    assert res.failure_reason.startswith(fa.OUTPUT_TRUNCATED_REASON)


def test_normal_stop_reason_remains_complete():
    res = fa.run_specialist(_package(), EVAL, client=TruncClient(), telemetry=[])
    assert res.status == fa.STATUS_COMPLETE
    assert res.output_truncated is False and res.stop_reason == "end_turn"
    assert res.failure_reason is None


def test_truncation_with_nothing_recoverable_fails():
    res = fa.run_specialist(_package(), EVAL, client=TruncClient(garbage_for=("EVALUATION",)),
                            telemetry=[])
    assert res.status == fa.STATUS_FAILED and res.findings == []
    assert fa.OUTPUT_TRUNCATED_REASON in res.failure_reason


def test_malformed_output_keeps_existing_behavior():
    # Pre-MA-2A.2 behaviour for an unparseable end_turn body is unchanged:
    # an empty-findings COMPLETE result (no truncation signal exists).
    res = fa.run_specialist(_package(), EVAL, client=TruncClient(malformed_for=("EVALUATION",)),
                            telemetry=[])
    assert res.status == fa.STATUS_COMPLETE and res.findings == []
    assert res.parse_status == "FAILED" and res.output_truncated is False


def test_provider_failure_behavior_unchanged():
    res = fa.run_specialist(_package(), EVAL, client=TruncClient(fail_for=("EVALUATION",)),
                            telemetry=[])
    assert res.status == fa.STATUS_FAILED
    assert res.failure_reason.startswith("RuntimeError")
    assert res.output_truncated is False


# ── 2. overall run semantics ─────────────────────────────────────────────

def test_truncated_specialist_makes_overall_partial_and_preserves_others():
    events = []
    result = fa.run_full_analysis(_package(), client=TruncClient(truncate_for=("EVALUATION",)),
                                  on_event=lambda t, p: events.append((t, p)))
    assert result.completeness_status == fa.COMPLETENESS_PARTIAL
    assert result.specialist_statuses[EVAL] == fa.STATUS_PARTIAL
    for sid in fa.SPECIALIST_IDS:
        if sid != EVAL:
            assert result.specialist_statuses[sid] == fa.STATUS_COMPLETE
    # reconciliation knows the domain is incomplete
    incomplete = result.reconciliation["incomplete_domains"]
    assert [d["specialist_id"] for d in incomplete] == [EVAL]
    assert incomplete[0]["status"] == fa.STATUS_PARTIAL
    # the truncated specialist's preserved findings are still reconciled
    assert any(EVAL in f["produced_by"] for f in result.reconciled_findings)
    assert any(g["title"] == f"Incomplete domain: {EVAL}" and "truncated" in g["detail"]
               for g in result.unresolved_gaps)


def test_reconciliation_payload_marks_truncated_domain():
    pkg = _package()
    client = TruncClient(truncate_for=("EVALUATION",))
    fa.run_full_analysis(pkg, client=client)
    rec_prompt = next(p for p in client.prompts if "RECONCILIATION" in p[:200])
    body = json.loads(rec_prompt.split("CANONICAL INDEX:\n", 1)[1])
    dom = next(d for d in body["domains"] if d["specialist_id"] == EVAL)
    assert dom["status"] == "PARTIAL" and dom["domain_complete"] is False
    assert dom["output_truncated"] is True


def test_truncated_reconciliation_makes_overall_partial():
    result = fa.run_full_analysis(_package(), client=TruncClient(truncate_for=("RECONCILIATION",)))
    rec = result.reconciliation
    assert rec["status"] == fa.STATUS_PARTIAL and rec["output_truncated"] is True
    assert rec["cross_domain_risks"], "recovered reconciliation output preserved"
    assert result.completeness_status == fa.COMPLETENESS_PARTIAL
    assert all(s == fa.STATUS_COMPLETE for s in result.specialist_statuses.values())


def test_all_normal_is_complete():
    result = fa.run_full_analysis(_package(), client=TruncClient())
    assert result.completeness_status == fa.COMPLETENESS_COMPLETE
    assert result.reconciliation["output_truncated"] is False


# ── 3. durable persistence / status / events ──────────────────────────────

def _run_status(fake, client):
    out = start(client=client)
    run_id = out["run"]["id"]
    return run_id, fake.runs[run_id], fas.get_full_analysis_status(8, run_id)


def test_persisted_run_is_partial_with_truncation_state(fake):
    run_id, run, _ = _run_status(fake, TruncClient(truncate_for=("EVALUATION",)))
    assert run["status"] == fas.RUN_PARTIAL
    assert "EVALUATION_INTELLIGENCE (output truncated)" in run["failure_reason"]
    assert run["telemetry"]["truncated_stages"] == [EVAL]
    stored = fake.results[run_id]["full_analysis_result"]
    spec = next(s for s in stored["specialist_results"] if s["specialist_id"] == EVAL)
    assert spec["status"] == "PARTIAL" and spec["output_truncated"] is True
    assert spec["stop_reason"] == "max_tokens" and spec["findings"]
    assert fake.results[run_id]["structured_intelligence"]["truncated_stages"] == [EVAL]


def test_result_api_exposes_effective_status(fake):
    run_id, _, _ = _run_status(fake, TruncClient(truncate_for=("EVALUATION",)))
    got = fas.get_full_analysis_result(8, run_id)
    assert got["is_complete"] is False
    by_id = {r["specialist_id"]: r for r in got["specialist_results"]}
    assert by_id[EVAL]["effective_status"] == "PARTIAL"
    assert by_id[EVAL]["result"]["output_truncated"] is True
    assert by_id[COMM]["effective_status"] == "COMPLETE"


def test_status_api_and_events_expose_partial_truthfully(fake):
    run_id, _, status = _run_status(fake, TruncClient(truncate_for=("EVALUATION",
                                                                   "RECONCILIATION")))
    assert status["status"] == fas.RUN_PARTIAL
    assert status["specialists"][EVAL]["status"] == fas.SPEC_PARTIAL
    assert status["specialists"][EVAL]["detail"]["output_truncated"] is True
    assert status["specialists"][EVAL]["detail"]["stop_reason"] == "max_tokens"
    assert status["specialists"][COMM]["status"] == fas.SPEC_COMPLETE
    assert status["reconciliation"]["status"] == fas.SPEC_PARTIAL
    assert status["reconciliation"]["detail"]["output_truncated"] is True
    ev = [e for e in fake.events if e["run_id"] == run_id and e["specialist_id"] == EVAL
          and e["event_type"] == fa.EVENT_SPECIALIST_COMPLETED]
    assert len(ev) == 1 and ev[0]["status"] == "PARTIAL"
    # every status value written is within migration 020's CHECK vocabulary
    assert all(e["status"] in (None, "QUEUED", "RUNNING", "COMPLETE", "PARTIAL", "FAILED",
                               "SKIPPED") for e in fake.events)
    assert not any("percent" in json.dumps(e["detail"]).lower() for e in fake.events)


def test_normal_run_events_stay_complete(fake):
    _, run, status = _run_status(fake, TruncClient())
    assert run["status"] == fas.RUN_COMPLETE
    assert all(s["status"] == fas.SPEC_COMPLETE for s in status["specialists"].values())
    assert status["reconciliation"]["status"] == fas.SPEC_COMPLETE


def test_partial_run_is_never_reused_as_complete(fake):
    run_id, _, _ = _run_status(fake, TruncClient(truncate_for=("EVALUATION",)))
    again = TruncClient()
    out = start(client=again)
    assert out["outcome"] == fas.OUTCOME_EXISTING_PARTIAL
    assert out["run"]["id"] == run_id and out["run"]["status"] == fas.RUN_PARTIAL
    assert again.prompts == []
    assert fake.runs[run_id]["status"] == fas.RUN_PARTIAL


def test_identical_complete_run_reuse_still_works(fake):
    run_id, _, _ = _run_status(fake, TruncClient())
    again = TruncClient()
    out = start(client=again)
    assert out["outcome"] == fas.OUTCOME_REUSED_COMPLETE and out["run"]["id"] == run_id
    assert again.prompts == []


def test_legacy_rows_without_truncation_state_are_unchanged():
    row = {"status": "COMPLETE", "result": {"specialist_id": EVAL, "findings": []}}
    assert fas.effective_specialist_status(row) == "COMPLETE"


# ── 4. bounded output contract ────────────────────────────────────────────

def test_prompts_carry_explicit_output_bounds():
    pkg = _package()
    client = TruncClient()
    fa.run_full_analysis(pkg, client=client)
    for p in client.prompts:
        assert "OUTPUT BOUNDS" in p
    assert "AT MOST 12 findings" in fa._SHARED_RULES
    assert "NEVER quote or restate" in fa._SHARED_RULES
    assert '{"completeness_note"' in fa._RECONCILIATION_RULES
    assert fa.SPECIALIST_MAX_OUTPUT_TOKENS == 3000
    assert fa.RECONCILIATION_MAX_OUTPUT_TOKENS == 3000
