"""
tests/test_historical_token_forensics.py

BI Token Optimization Program, Phase 5C: forensic tooling only -- no
analytical behavior touched. Tests scripts/historical_token_forensics.py
against a small synthetic fixture (deterministic, hand-built) and against
one real historical artifact still present on local disk from Phase 5A's
evaluation/ untracking (read-only; this file never re-adds, modifies, or
deletes anything under evaluation/).
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import historical_token_forensics as htf  # noqa: E402

_REAL_RUN_DIR = (Path(__file__).resolve().parents[1] / "evaluation" / "bank_of_canada_briefing_pack"
                / "fast_analysis" / "fastanalysis-v4-boc-2026-026-20260914T130015Z-e0720d")
_REAL_FACTS_FILE = _REAL_RUN_DIR / "fast_analysis_facts.json"

requires_real_artifact = pytest.mark.skipif(
    not _REAL_RUN_DIR.exists(),
    reason="Real historical evaluation/ artifact not present on this machine "
          "(untracked-but-local per Phase 5A; not guaranteed on every checkout)")


# ---------------------------------------------------------------------------
# Synthetic fixture -- fully deterministic, no dependency on local artifacts
# ---------------------------------------------------------------------------

def _synthetic_calls():
    return [
        {"call_index": 0, "call_kind": "initial", "route": "EVAL_ONLY", "filename": "a.pdf",
         "model": "claude-haiku-4-5-20251001", "input_tokens": 1000, "output_tokens": 4000,
         "stop_reason": "max_tokens", "parse_status": "RECOVERED_TRUNCATED", "error": None,
         "parent_call_index": None, "split_trigger_reason": None, "request_bytes": 5000,
         "chunk_chars": 20000, "latency_seconds": 10.0},
        {"call_index": 1, "call_kind": "split_recovery_a", "route": "EVAL_ONLY", "filename": "a.pdf",
         "model": "claude-haiku-4-5-20251001", "input_tokens": 500, "output_tokens": 1200,
         "stop_reason": "end_turn", "parse_status": "COMPLETE", "error": None,
         "parent_call_index": 0, "split_trigger_reason": "max_tokens", "request_bytes": 2500,
         "chunk_chars": 10000, "latency_seconds": 5.0},
        {"call_index": 2, "call_kind": "split_recovery_b", "route": "EVAL_ONLY", "filename": "a.pdf",
         "model": "claude-haiku-4-5-20251001", "input_tokens": 520, "output_tokens": 1100,
         "stop_reason": "end_turn", "parse_status": "COMPLETE", "error": None,
         "parent_call_index": 0, "split_trigger_reason": "max_tokens", "request_bytes": 2600,
         "chunk_chars": 10000, "latency_seconds": 5.0},
        {"call_index": 3, "call_kind": "initial", "route": "COMMERCIAL_ONLY", "filename": "b.docx",
         "model": "claude-haiku-4-5-20251001", "input_tokens": 800, "output_tokens": 700,
         "stop_reason": "end_turn", "parse_status": "COMPLETE", "error": None,
         "parent_call_index": None, "split_trigger_reason": None, "request_bytes": 4000,
         "chunk_chars": 6000, "latency_seconds": 4.0},
        {"call_index": 4, "call_kind": "targeted_retry", "route": "COMMERCIAL_ONLY", "filename": "b.docx",
         "model": "claude-haiku-4-5-20251001", "input_tokens": 300, "output_tokens": 90,
         "stop_reason": "end_turn", "parse_status": "COMPLETE", "error": None,
         "parent_call_index": None, "split_trigger_reason": None, "request_bytes": 1500,
         "chunk_chars": 6000, "latency_seconds": 2.0},
    ]


def _synthetic_run():
    return {"run_id": "synthetic-test-run", "run_dir": "synthetic",
           "calls": _synthetic_calls(),
           "totals": {"documents_total": 2, "total_wall_seconds": 26.0}}


class TestClassifyCall:

    def test_initial_and_batch_are_primary(self):
        assert htf.classify_call({"call_kind": "initial"}) == "PRIMARY"
        assert htf.classify_call({"call_kind": "batch"}) == "PRIMARY"

    def test_focused_initial_is_primary(self):
        assert htf.classify_call({"call_kind": "focused_rated_criteria_initial"}) == "PRIMARY"

    def test_split_recovery_is_truncation_split(self):
        assert htf.classify_call({"call_kind": "split_recovery_a"}) == "TRUNCATION_SPLIT"
        assert htf.classify_call({"call_kind": "split_recovery_b"}) == "TRUNCATION_SPLIT"
        assert htf.classify_call({"call_kind": "split_exhausted"}) == "TRUNCATION_SPLIT"

    def test_stage_a_recovery_kinds_classify_correctly(self):
        assert htf.classify_call({"call_kind": "recovery_subchunk_truncated"}) == "TRUNCATION_SPLIT"
        assert htf.classify_call({"call_kind": "recovery_subchunk_failed"}) == "PARSE_RECOVERY"
        assert htf.classify_call({"call_kind": "coverage_guard_recovery"}) == "OTHER_RETRY"

    def test_targeted_retry_is_targeted_followup(self):
        assert htf.classify_call({"call_kind": "targeted_retry"}) == "TARGETED_FOLLOWUP"

    def test_unknown_kind_falls_back_to_other_retry_never_dropped(self):
        assert htf.classify_call({"call_kind": "something_new"}) == "OTHER_RETRY"


class TestIsRealApiCall:

    def test_call_with_tokens_is_real(self):
        assert htf.is_real_api_call({"input_tokens": 10, "output_tokens": 5}) is True

    def test_split_exhausted_bookkeeping_row_is_not_real(self):
        assert htf.is_real_api_call({"input_tokens": None, "output_tokens": None}) is False


class TestSummarizeRunSynthetic:

    def test_counts_and_taxonomy(self):
        summary = htf.summarize_run(_synthetic_run())
        assert summary["calls_telemetry_rows"] == 5
        assert summary["base_calls"] == 2  # the two "initial" calls
        assert summary["retry_or_recovery_calls"] == 3
        assert summary["taxonomy"] == {"PRIMARY": 2, "TRUNCATION_SPLIT": 2, "TARGETED_FOLLOWUP": 1}

    def test_token_totals_are_exact_sums(self):
        summary = htf.summarize_run(_synthetic_run())
        assert summary["input_tokens"] == 1000 + 500 + 520 + 800 + 300
        assert summary["output_tokens"] == 4000 + 1200 + 1100 + 700 + 90

    def test_calls_ending_max_tokens(self):
        summary = htf.summarize_run(_synthetic_run())
        assert summary["calls_ending_max_tokens"] == 1


class TestRecoveryTaxSynthetic:

    def test_recovery_tokens_exclude_primary(self):
        tax = htf.recovery_tax(_synthetic_run())
        assert tax["RECOVERY_INPUT_TOKENS"] == 500 + 520 + 300
        assert tax["RECOVERY_OUTPUT_TOKENS"] == 1200 + 1100 + 90
        assert tax["RECOVERY_TOTAL_TOKENS"] == tax["RECOVERY_INPUT_TOKENS"] + tax["RECOVERY_OUTPUT_TOKENS"]

    def test_percentages_computed_against_true_totals(self):
        tax = htf.recovery_tax(_synthetic_run())
        total_in = 1000 + 500 + 520 + 800 + 300
        expected_pct = round(100 * (500 + 520 + 300) / total_in, 1)
        assert tax["recovery_pct_of_input"] == expected_pct


class TestTruncationForensicsSynthetic:

    def test_dominant_cause_output_truncation(self):
        result = htf.truncation_forensics(_synthetic_run())
        assert result["dominant_recovery_cause"] == "OUTPUT_TRUNCATION"
        assert result["non_primary_calls_driven_by_truncation"] == 2  # the two split_recovery_* calls

    def test_targeted_retry_alone_is_not_truncation_driven(self):
        run = {"run_id": "r", "calls": [
            {"call_kind": "initial", "input_tokens": 10, "output_tokens": 10, "stop_reason": "end_turn"},
            {"call_kind": "targeted_retry", "input_tokens": 5, "output_tokens": 5, "stop_reason": "end_turn"},
        ], "totals": {}}
        result = htf.truncation_forensics(run)
        assert result["non_primary_calls_driven_by_truncation"] == 0


class TestRouteBreakdownSynthetic:

    def test_per_route_calls_and_retries(self):
        breakdown = htf.route_breakdown(_synthetic_run())
        assert breakdown["EVAL_ONLY"]["calls"] == 3
        assert breakdown["EVAL_ONLY"]["retries"] == 2
        assert breakdown["COMMERCIAL_ONLY"]["calls"] == 2
        assert breakdown["COMMERCIAL_ONLY"]["retries"] == 1


class TestMaxTokensUtilizationSynthetic:

    def test_frequently_near_limit_classification(self):
        result = htf.max_tokens_utilization(_synthetic_run(), configured_max_tokens=4000)
        # 1 of 5 real calls (the first, output_tokens=4000) is >= 90% of 4000
        assert result["calls_near_limit"] == 1
        assert result["sample_size"] == 5


class TestPayloadForensicsSynthetic:

    def test_key_byte_overhead_counts_key_occurrences_not_values(self):
        obj = {"requirements": [{"source_refs": [{"source_doc": "a.pdf", "page": 1}]},
                                {"source_refs": [{"source_doc": "a.pdf", "page": 2}]}]}
        result = htf.key_byte_overhead(obj)
        keys = {row["key"]: row["occurrences"] for row in result["top_keys"]}
        assert keys["source_refs"] == 2
        assert keys["source_doc"] == 2

    def test_repeated_value_overhead_finds_duplicates(self):
        obj = {"a": [{"label": "Appendix D1 - Rated criteria"}, {"label": "Appendix D1 - Rated criteria"},
                     {"label": "unique one"}]}
        result = htf.repeated_value_overhead(obj)
        assert result["repeated_values"] == 1
        assert result["total_occurrences_of_repeated_values"] == 2

    def test_source_refs_forensics_counts_unique_identities(self):
        obj = {"requirements": [
            {"source_refs": [{"source_doc": "a.pdf", "page": 1, "excerpt": "text one"}]},
            {"source_refs": [{"source_doc": "a.pdf", "page": 1, "excerpt": "text two (different quote)"}]},
        ]}
        result = htf.source_refs_forensics(obj)
        assert result["total_source_ref_occurrences"] == 2
        assert result["unique_source_identities_excluding_excerpt"] == 1  # same doc+page, different excerpt
        assert result["repeated_identity_occurrences"] == 1

    def test_evidence_text_forensics_finds_exact_duplicates(self):
        obj = {"requirements": [{"description": "Submit a signed form."},
                                {"description": "Submit a signed form."},
                                {"description": "A different requirement."}]}
        result = htf.evidence_text_forensics(obj)
        assert result["exact_duplicate_texts"] == 1
        assert result["evidence_like_field_occurrences"] == 3

    def test_cardinality_analysis_ranks_by_bytes_not_count(self):
        obj = {"small_many": [{"x": 1}] * 100, "big_few": [{"y": "z" * 500}] * 2}
        result = htf.cardinality_analysis(obj)
        families = list(result["families"].keys())
        assert families[0] == "big_few"  # fewer objects, but far more bytes

    def test_no_full_document_text_leaks_into_a_report(self):
        """Guards the "never print full proposal/RFP content" requirement:
        payload forensics must summarize, never echo, large text fields."""
        secret_clause = "CONFIDENTIAL CLAUSE TEXT " * 50
        obj = {"commercial_clauses": [{"source_fact": secret_clause}]}
        result = htf.evidence_text_forensics(obj)
        assert secret_clause not in json.dumps(result)


@requires_real_artifact
class TestAgainstRealHistoricalArtifact:
    """Read-only against the real, locally-present (untracked) Fast Analysis
    V4 run -- proves the tool works on genuine historical telemetry, not
    just the synthetic fixture. Never writes to, modifies, or re-adds
    anything under evaluation/."""

    def test_run_discovery_finds_the_real_run(self):
        runs = htf.discover_runs(_REAL_RUN_DIR.parent)
        assert _REAL_RUN_DIR in runs

    def test_load_and_summarize_matches_known_verified_totals(self):
        run = htf.load_run(_REAL_RUN_DIR)
        summary = htf.summarize_run(run)
        # These exact figures were independently verified in the Phase 5C
        # report against fast_analysis_totals.json's own persisted totals.
        assert summary["calls_telemetry_rows"] == 23
        assert summary["input_tokens"] == 56673
        assert summary["output_tokens"] == 51875

    def test_recovery_tax_is_a_measured_fraction_of_real_totals(self):
        run = htf.load_run(_REAL_RUN_DIR)
        tax = htf.recovery_tax(run)
        assert tax["TOTAL_INPUT_TOKENS"] == 56673
        assert 0 < tax["RECOVERY_TOTAL_TOKENS"] < tax["TOTAL_INPUT_TOKENS"] + tax["TOTAL_OUTPUT_TOKENS"]

    def test_truncation_is_the_dominant_recovery_cause(self):
        run = htf.load_run(_REAL_RUN_DIR)
        result = htf.truncation_forensics(run)
        assert result["dominant_recovery_cause"] == "OUTPUT_TRUNCATION"

    def test_payload_forensics_on_real_facts_file_does_not_raise(self):
        if not _REAL_FACTS_FILE.exists():
            pytest.skip("real facts.json not present on this machine")
        facts = json.loads(_REAL_FACTS_FILE.read_text(encoding="utf-8"))
        assert htf.key_byte_overhead(facts)["total_key_name_bytes"] > 0
        assert htf.source_refs_forensics(facts)["total_source_ref_occurrences"] > 0
        cardinality = htf.cardinality_analysis(facts)
        assert "commercial_clauses" in cardinality["families"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
