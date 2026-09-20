"""
tests/test_telemetry_taxonomy.py

BI Token Optimization Program, Phase 5E: Telemetry Taxonomy Hardening.

Proves fast_analysis.classify_telemetry_entry()/_is_provider_call()/
_telemetry_audit_summary() correctly distinguish genuine paid provider
calls from planned focused calls and zero-cost bookkeeping rows, using
the exact historical Fast Analysis V4 call_kind distribution (verified in
Phase 5C/5D against the real evaluation/.../fastanalysis-v4-.../
fast_analysis_llm_calls.jsonl artifact): 23 telemetry rows, 20 provider
calls, 7 genuine recovery provider calls, 3 non-provider bookkeeping
rows, 2 planned focused provider calls.

No provider call is made anywhere in this file -- every fixture is a
hand-built telemetry row, never a real or mocked Anthropic client call.
"""
import analysis_service
import fast_analysis as fa


def _row(call_kind, input_tokens=None, output_tokens=None, stop_reason=None):
    return {"call_kind": call_kind, "input_tokens": input_tokens,
           "output_tokens": output_tokens, "stop_reason": stop_reason}


def _v4_pattern_telemetry():
    """Reconstructs the exact call_kind distribution of the real historical
    V4 run (initial:10, batch:1, split_recovery_a:3, split_recovery_b:3,
    split_exhausted:3, focused_rated_criteria_initial:1,
    focused_pricing_stage_initial:1, targeted_retry:1 = 23 rows) with
    representative (not necessarily byte-identical) token values -- the
    split_exhausted rows correctly carry null tokens, matching how
    extract_fast_document()/run_focused_task() actually construct them."""
    rows = []
    for _ in range(10):
        rows.append(_row("initial", input_tokens=1500, output_tokens=1200, stop_reason="end_turn"))
    rows.append(_row("batch", input_tokens=2272, output_tokens=4000, stop_reason="max_tokens"))
    for _ in range(3):
        rows.append(_row("split_recovery_a", input_tokens=3000, output_tokens=3500, stop_reason="end_turn"))
    for _ in range(3):
        rows.append(_row("split_recovery_b", input_tokens=3200, output_tokens=3800, stop_reason="end_turn"))
    for _ in range(3):
        rows.append(_row("split_exhausted"))  # bookkeeping -- no call, all fields null
    rows.append(_row("focused_rated_criteria_initial", input_tokens=1169, output_tokens=3853, stop_reason="end_turn"))
    rows.append(_row("focused_pricing_stage_initial", input_tokens=804, output_tokens=761, stop_reason="end_turn"))
    rows.append(_row("targeted_retry", input_tokens=618, output_tokens=85, stop_reason="end_turn"))
    assert len(rows) == 23
    return rows


class TestClassifyTelemetryEntry:

    def test_initial_and_batch_are_planned_primary(self):
        assert fa.classify_telemetry_entry(_row("initial")) == "PLANNED_PRIMARY"
        assert fa.classify_telemetry_entry(_row("batch")) == "PLANNED_PRIMARY"

    def test_focused_initial_is_planned_focused_not_recovery(self):
        assert fa.classify_telemetry_entry(_row("focused_rated_criteria_initial")) == "PLANNED_FOCUSED"
        assert fa.classify_telemetry_entry(_row("focused_pricing_stage_initial")) == "PLANNED_FOCUSED"

    def test_split_recovery_is_truncation_recovery(self):
        assert fa.classify_telemetry_entry(_row("split_recovery_a")) == "TRUNCATION_RECOVERY"
        assert fa.classify_telemetry_entry(_row("split_recovery_b")) == "TRUNCATION_RECOVERY"
        assert fa.classify_telemetry_entry(_row("focused_rated_criteria_split_recovery_a")) == "TRUNCATION_RECOVERY"

    def test_split_exhausted_is_bookkeeping_not_recovery(self):
        assert fa.classify_telemetry_entry(_row("split_exhausted")) == "BOOKKEEPING"
        assert fa.classify_telemetry_entry(_row("focused_pricing_stage_split_exhausted")) == "BOOKKEEPING"

    def test_targeted_retry_is_its_own_category(self):
        assert fa.classify_telemetry_entry(_row("targeted_retry")) == "TARGETED_RETRY"

    def test_unrecognized_call_kind_is_unknown_never_silently_dropped(self):
        assert fa.classify_telemetry_entry(_row("some_future_call_kind")) == "UNKNOWN"


class TestIsProviderCall:

    def test_row_with_tokens_is_a_provider_call(self):
        assert fa._is_provider_call(_row("initial", input_tokens=10, output_tokens=5)) is True

    def test_bookkeeping_row_with_null_tokens_is_not_a_provider_call(self):
        assert fa._is_provider_call(_row("split_exhausted")) is False


class TestV4HistoricalPatternTaxonomy:
    """The primary acceptance proof: the exact historical V4 counts."""

    def test_telemetry_rows(self):
        summary = fa._telemetry_audit_summary(_v4_pattern_telemetry(), wall_seconds=202.3)
        assert summary["telemetry_rows"] == 23

    def test_provider_calls(self):
        summary = fa._telemetry_audit_summary(_v4_pattern_telemetry(), wall_seconds=202.3)
        assert summary["provider_calls"] == 20

    def test_recovery_provider_calls(self):
        summary = fa._telemetry_audit_summary(_v4_pattern_telemetry(), wall_seconds=202.3)
        assert summary["recovery_provider_calls"] == 7

    def test_non_provider_bookkeeping_rows(self):
        summary = fa._telemetry_audit_summary(_v4_pattern_telemetry(), wall_seconds=202.3)
        assert summary["non_provider_bookkeeping_rows"] == 3
        assert summary["split_exhausted_rows"] == 3

    def test_planned_focused_provider_calls(self):
        summary = fa._telemetry_audit_summary(_v4_pattern_telemetry(), wall_seconds=202.3)
        assert summary["planned_focused_provider_calls"] == 2

    def test_planned_primary_and_recovery_breakdown(self):
        summary = fa._telemetry_audit_summary(_v4_pattern_telemetry(), wall_seconds=202.3)
        assert summary["planned_primary_provider_calls"] == 11  # 10 initial + 1 batch
        assert summary["truncation_recovery_provider_calls"] == 6  # 3 split_recovery_a + 3 split_recovery_b
        assert summary["targeted_retry_provider_calls"] == 1
        assert summary["other_provider_calls"] == 0

    def test_taxonomy_is_exhaustive_and_self_consistent(self):
        """Every provider call must land in exactly one precise bucket --
        the buckets must sum to provider_calls with no double-counting
        and no silent loss."""
        summary = fa._telemetry_audit_summary(_v4_pattern_telemetry(), wall_seconds=202.3)
        bucket_sum = (summary["planned_primary_provider_calls"]
                     + summary["planned_focused_provider_calls"]
                     + summary["recovery_provider_calls"]
                     + summary["other_provider_calls"])
        assert bucket_sum == summary["provider_calls"]

    def test_token_totals_exclude_bookkeeping_rows(self):
        """Instruction 4: token totals must include provider calls only
        and cannot be affected by null-token bookkeeping records."""
        telemetry = _v4_pattern_telemetry()
        summary = fa._telemetry_audit_summary(telemetry, wall_seconds=202.3)
        provider_rows = [r for r in telemetry if r.get("input_tokens") is not None]
        expected_input = sum(r["input_tokens"] for r in provider_rows)
        expected_output = sum(r["output_tokens"] for r in provider_rows)
        assert summary["input_tokens"] == expected_input
        assert summary["output_tokens"] == expected_output
        # Sanity: the 3 null-token bookkeeping rows contributed exactly 0.
        assert all(r.get("input_tokens") is None for r in telemetry if r["call_kind"] == "split_exhausted")


class TestBackwardCompatibility:
    """The legacy `recovery_or_retry_calls`/`total_calls` fields must
    still exist and still equal exactly what they always computed --
    Phase 5E adds fields, it does not redefine historical semantics."""

    def test_legacy_total_calls_unchanged(self):
        summary = fa._telemetry_audit_summary(_v4_pattern_telemetry(), wall_seconds=202.3)
        assert summary["total_calls"] == 23
        assert summary["total_calls"] == summary["telemetry_rows"]

    def test_legacy_recovery_or_retry_calls_reproduces_old_ambiguous_count(self):
        """This is the exact (known-imprecise) historical value: every row
        whose call_kind isn't literally "initial"/"batch" -- 23 - 11 = 12,
        matching the real V4 totals.json's own persisted field and Phase
        5C/5D's documented investigation. Phase 5E does not change this
        number; it explains it and adds the precise fields alongside it."""
        summary = fa._telemetry_audit_summary(_v4_pattern_telemetry(), wall_seconds=202.3)
        assert summary["recovery_or_retry_calls"] == 12

    def test_both_precise_and_legacy_fields_present_simultaneously(self):
        summary = fa._telemetry_audit_summary(_v4_pattern_telemetry(), wall_seconds=202.3)
        for legacy_field in ("total_calls", "recovery_or_retry_calls"):
            assert legacy_field in summary
        for precise_field in ("telemetry_rows", "provider_calls", "planned_primary_provider_calls",
                              "planned_focused_provider_calls", "recovery_provider_calls",
                              "truncation_recovery_provider_calls", "targeted_retry_provider_calls",
                              "non_provider_bookkeeping_rows", "split_exhausted_rows"):
            assert precise_field in summary


class TestAnalysisServiceReusesSharedTaxonomy:
    """analysis_service._telemetry_summary must delegate to fast_analysis's
    corrected function rather than keep its own separate (and previously
    identically-buggy) counting logic -- guards against the same defect
    reappearing independently in the two modules."""

    def test_telemetry_summary_exposes_precise_fields(self):
        result = fa.FastAnalysisResult()
        result.telemetry = _v4_pattern_telemetry()
        result.wall_seconds = 202.3
        result.skipped_documents = []
        result.batched_documents = []
        summary = analysis_service._telemetry_summary(result)
        assert summary["telemetry_rows"] == 23
        assert summary["provider_calls"] == 20
        assert summary["recovery_provider_calls"] == 7
        assert summary["non_provider_bookkeeping_rows"] == 3
        assert summary["planned_focused_provider_calls"] == 2
        # application-layer fields are still present alongside the shared taxonomy
        assert summary["engine_version"] == analysis_service.FAST_ANALYSIS_ENGINE_VERSION
        assert "cost_note" in summary

    def test_telemetry_summary_legacy_fields_unchanged(self):
        result = fa.FastAnalysisResult()
        result.telemetry = _v4_pattern_telemetry()
        result.wall_seconds = 202.3
        result.skipped_documents = []
        result.batched_documents = []
        summary = analysis_service._telemetry_summary(result)
        assert summary["total_calls"] == 23
        assert summary["recovery_or_retry_calls"] == 12


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
