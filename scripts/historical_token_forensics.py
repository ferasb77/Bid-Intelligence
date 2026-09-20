"""
scripts/historical_token_forensics.py -- offline forensics over EXISTING
historical Fast Analysis / Deep Verify telemetry and persisted extraction
output (BI Token Optimization Program, Phase 5C).

Makes ZERO provider calls. Reads only local, already-persisted artifacts:
  * "<workflow>_llm_calls.jsonl" -- per-call telemetry (call_kind, tokens,
    stop_reason, parse_status, ...). Pure metadata, no prompt/document text.
  * "<workflow>_totals.json" -- per-run aggregate summaries.
  * a parsed extraction-output JSON (e.g. fast_analysis_facts.json /
    stage_a_document_facts.json) for payload-composition forensics
    (JSON-key overhead, repeated values, source_refs, evidence text,
    object-family cardinality).

This script never prints full document/RFP/proposal text. Evidence/quote
fields from a facts file are measured (byte counts, repetition) but never
printed in full -- only short, explicitly-truncated samples when a --json
report is NOT requested (human-readable mode), and even then capped hard.

Never re-adds, modifies, deletes, or regenerates any evaluation/ artifact --
purely read-only.

Usage:
    python scripts/historical_token_forensics.py --evaluation-root evaluation
    python scripts/historical_token_forensics.py --run-dir <path to one run>
    python scripts/historical_token_forensics.py --facts-file <path to a facts.json>
    python scripts/historical_token_forensics.py --evaluation-root evaluation --json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Call taxonomy (instruction 5): PRIMARY / TARGETED_FOLLOWUP /
# TRUNCATION_SPLIT / PARSE_RECOVERY / OTHER_RETRY -- derived from the known
# call_kind vocabulary used by fast_analysis.py and extractor.py's Stage A
# (see model_telemetry.py's authoritative (workflow, operation) inventory).
# ---------------------------------------------------------------------------
_PRIMARY_KINDS = {"initial", "batch"}
_TARGETED_FOLLOWUP_KINDS = {"targeted_retry"}
_TRUNCATION_SPLIT_KINDS = {"split_recovery_a", "split_recovery_b", "split_exhausted",
                          "recovery_subchunk_truncated"}
_PARSE_RECOVERY_KINDS = {"recovery_subchunk_failed"}
_OTHER_RETRY_KINDS = {"coverage_guard_recovery"}


def classify_call(call: dict) -> str:
    """PRIMARY / TARGETED_FOLLOWUP / TRUNCATION_SPLIT / PARSE_RECOVERY /
    OTHER_RETRY, from the call's own call_kind (falling back to a focused-
    task-prefixed variant, e.g. focused_rated_criteria_initial -> PRIMARY,
    focused_pricing_stage_split_recovery_a -> TRUNCATION_SPLIT)."""
    kind = call.get("call_kind") or "unknown"
    if kind in _PRIMARY_KINDS or kind.endswith("_initial"):
        return "PRIMARY"
    if kind in _TARGETED_FOLLOWUP_KINDS:
        return "TARGETED_FOLLOWUP"
    if kind in _TRUNCATION_SPLIT_KINDS or "split_recovery" in kind or kind.endswith("_split_exhausted"):
        return "TRUNCATION_SPLIT"
    if kind in _PARSE_RECOVERY_KINDS:
        return "PARSE_RECOVERY"
    if kind in _OTHER_RETRY_KINDS:
        return "OTHER_RETRY"
    return "OTHER_RETRY"  # unknown call_kind -- never silently drop from taxonomy


def is_real_api_call(call: dict) -> bool:
    """False for bookkeeping-only telemetry rows with no actual request
    (e.g. split_exhausted / BOUNDED_SPLIT_EXHAUSTED -- input_tokens,
    output_tokens and stop_reason are all null, confirming no call was
    made). Token-burden sums must exclude these; call-count taxonomy
    includes them (they are real recovery-attempt outcomes)."""
    return call.get("input_tokens") is not None or call.get("output_tokens") is not None


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_runs(root: Path) -> list[Path]:
    """Every directory under `root` containing at least one
    *_llm_calls.jsonl file -- workflow-agnostic (fast_analysis_llm_calls /
    stage_a_llm_calls / any future *_llm_calls.jsonl)."""
    return sorted({p.parent for p in root.rglob("*_llm_calls.jsonl")})


def load_run(run_dir: Path) -> dict:
    calls_files = sorted(run_dir.glob("*_llm_calls.jsonl"))
    totals_files = sorted(run_dir.glob("*_totals.json"))
    calls: list[dict] = []
    for cf in calls_files:
        with cf.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    calls.append(json.loads(line))
    totals = None
    if totals_files:
        totals = json.loads(totals_files[0].read_text(encoding="utf-8"))
    return {"run_dir": str(run_dir), "run_id": run_dir.name, "calls": calls, "totals": totals}


# ---------------------------------------------------------------------------
# Section 4/5: run table + recovery tax
# ---------------------------------------------------------------------------

def summarize_run(run: dict) -> dict:
    calls = run["calls"]
    totals = run.get("totals") or {}
    taxonomy = Counter(classify_call(c) for c in calls)
    real_calls = [c for c in calls if is_real_api_call(c)]
    base = taxonomy["PRIMARY"]
    retry = len(calls) - base
    ending_max_tokens = sum(1 for c in real_calls if c.get("stop_reason") == "max_tokens")
    parse_failures = sum(1 for c in real_calls if c.get("parse_status")
                         not in ("COMPLETE", None) and c.get("parse_status") != "RECOVERED_TRUNCATED")
    split_recoveries = sum(1 for c in calls if classify_call(c) == "TRUNCATION_SPLIT")
    targeted_retries = taxonomy["TARGETED_FOLLOWUP"]
    successful_first_pass = sum(1 for c in real_calls
                                if classify_call(c) == "PRIMARY" and c.get("stop_reason") == "end_turn"
                                and c.get("parse_status") == "COMPLETE")
    total_input = sum(c.get("input_tokens") or 0 for c in real_calls)
    total_output = sum(c.get("output_tokens") or 0 for c in real_calls)
    return {
        "run_id": run["run_id"],
        "run_dir": run["run_dir"],
        "documents": totals.get("documents_total") if totals else None,
        "calls_telemetry_rows": len(calls),
        "real_api_calls": len(real_calls),
        "base_calls": base,
        "retry_or_recovery_calls": retry,
        "retry_percentage": round(100 * retry / len(calls), 1) if calls else None,
        "input_tokens": total_input or (totals.get("total_input_tokens") if totals else None),
        "output_tokens": total_output or (totals.get("total_output_tokens") if totals else None),
        "output_input_ratio": round(total_output / total_input, 3) if total_input else None,
        "wall_seconds": totals.get("total_wall_seconds") if totals else None,
        "calls_ending_max_tokens": ending_max_tokens,
        "parse_failures": parse_failures,
        "split_recoveries": split_recoveries,
        "targeted_retries": targeted_retries,
        "successful_first_pass_calls": successful_first_pass,
        "taxonomy": dict(taxonomy),
    }


def recovery_tax(run: dict) -> dict:
    """Instruction 5: RECOVERY_INPUT_TOKENS / RECOVERY_OUTPUT_TOKENS /
    RECOVERY_TOTAL_TOKENS and their percentage of the run's total -- only
    from real (non-null-token) calls; call-count burden is reported
    separately for taxonomy categories with no token data."""
    calls = run["calls"]
    real_calls = [c for c in calls if is_real_api_call(c)]
    by_category_tokens: dict[str, dict] = defaultdict(lambda: {"input": 0, "output": 0, "calls": 0})
    by_category_call_count: Counter = Counter()
    for c in calls:
        cat = classify_call(c)
        by_category_call_count[cat] += 1
        if is_real_api_call(c):
            by_category_tokens[cat]["input"] += c.get("input_tokens") or 0
            by_category_tokens[cat]["output"] += c.get("output_tokens") or 0
            by_category_tokens[cat]["calls"] += 1

    total_input = sum(c.get("input_tokens") or 0 for c in real_calls)
    total_output = sum(c.get("output_tokens") or 0 for c in real_calls)
    recovery_input = sum(v["input"] for k, v in by_category_tokens.items() if k != "PRIMARY")
    recovery_output = sum(v["output"] for k, v in by_category_tokens.items() if k != "PRIMARY")

    return {
        "run_id": run["run_id"],
        "call_count_by_category": dict(by_category_call_count),
        "token_totals_by_category": dict(by_category_tokens),
        "RECOVERY_INPUT_TOKENS": recovery_input,
        "RECOVERY_OUTPUT_TOKENS": recovery_output,
        "RECOVERY_TOTAL_TOKENS": recovery_input + recovery_output,
        "TOTAL_INPUT_TOKENS": total_input,
        "TOTAL_OUTPUT_TOKENS": total_output,
        "recovery_pct_of_input": round(100 * recovery_input / total_input, 1) if total_input else None,
        "recovery_pct_of_output": round(100 * recovery_output / total_output, 1) if total_output else None,
    }


# ---------------------------------------------------------------------------
# Section 6: truncation forensics
# ---------------------------------------------------------------------------

def truncation_forensics(run: dict) -> dict:
    calls = [c for c in run["calls"] if is_real_api_call(c)]
    max_tokens_stops = [c for c in calls if c.get("stop_reason") == "max_tokens"]
    parse_recovered = [c for c in calls if c.get("parse_status") == "RECOVERED_TRUNCATED"]
    other_parse_issue = [c for c in calls if c.get("parse_status")
                         not in ("COMPLETE", "RECOVERED_TRUNCATED", None)]
    non_primary = [c for c in calls if classify_call(c) != "PRIMARY"]
    # A recovery call's OWN stop_reason is often "end_turn" (it succeeded
    # on a shorter chunk) even though it exists BECAUSE a prior call
    # truncated -- causation lives in split_trigger_reason (Fast Analysis)
    # or the call_kind name itself (Stage A's recovery_subchunk_truncated
    # has no split_trigger_reason field at all).
    driven_by_truncation = sum(1 for c in non_primary if (
        c.get("split_trigger_reason") == "max_tokens"
        or c.get("stop_reason") == "max_tokens"
        or "truncat" in (c.get("call_kind") or "")))
    dominant_cause = "UNKNOWN"
    if non_primary:
        if driven_by_truncation / len(non_primary) >= 0.6:
            dominant_cause = "OUTPUT_TRUNCATION"
        elif other_parse_issue and len(other_parse_issue) / len(non_primary) >= 0.4:
            dominant_cause = "JSON_PARSE_FAILURE"
        else:
            dominant_cause = "OTHER"
    return {
        "run_id": run["run_id"],
        "calls_with_stop_reason_max_tokens": len(max_tokens_stops),
        "calls_with_parse_status_recovered_truncated": len(parse_recovered),
        "calls_with_other_parse_issue": len(other_parse_issue),
        "non_primary_calls": len(non_primary),
        "non_primary_calls_driven_by_truncation": driven_by_truncation,
        "dominant_recovery_cause": dominant_cause,
    }


# ---------------------------------------------------------------------------
# Section 14: route analysis
# ---------------------------------------------------------------------------

def route_breakdown(run: dict) -> dict:
    calls = run["calls"]
    by_route: dict[str, dict] = defaultdict(lambda: {
        "calls": 0, "retries": 0, "input_tokens": 0, "output_tokens": 0, "max_tokens_stops": 0})
    for c in calls:
        route = c.get("route") or ("focused" if "focused" in (c.get("call_kind") or "") else "unknown")
        entry = by_route[route]
        entry["calls"] += 1
        if classify_call(c) != "PRIMARY":
            entry["retries"] += 1
        if is_real_api_call(c):
            entry["input_tokens"] += c.get("input_tokens") or 0
            entry["output_tokens"] += c.get("output_tokens") or 0
            if c.get("stop_reason") == "max_tokens":
                entry["max_tokens_stops"] += 1
    return dict(by_route)


# ---------------------------------------------------------------------------
# Section 18: max_tokens utilization
# ---------------------------------------------------------------------------

def max_tokens_utilization(run: dict, configured_max_tokens: int, near_limit_ratio: float = 0.9) -> dict:
    calls = [c for c in run["calls"] if is_real_api_call(c) and c.get("output_tokens") is not None]
    if not calls:
        return {"run_id": run["run_id"], "classification": "UNKNOWN", "sample_size": 0}
    near_limit = sum(1 for c in calls if c["output_tokens"] >= configured_max_tokens * near_limit_ratio)
    pct = 100 * near_limit / len(calls)
    classification = "FREQUENTLY_NEAR_LIMIT" if pct >= 25 else "COMFORTABLY_BELOW_LIMIT"
    return {
        "run_id": run["run_id"], "configured_max_tokens": configured_max_tokens,
        "sample_size": len(calls), "calls_near_limit": near_limit,
        "pct_near_limit": round(pct, 1), "classification": classification,
    }


# ---------------------------------------------------------------------------
# Sections 7-13: payload composition forensics over a parsed facts.json
# ---------------------------------------------------------------------------

_EVIDENCE_LIKE_KEYS = {"excerpt", "section_evidence", "raw_wording", "original_value",
                      "source_fact", "description", "notes", "summary"}
_SOURCE_ID_KEYS = {"source_doc", "filename", "page", "sheet", "section"}


def _walk(obj, key_name=None):
    """Yields (key_name, value) for every scalar leaf and every dict key
    encountered, depth-first. Never yields more than what's structurally
    present -- no content is summarized/altered."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield ("__key__", k)
            yield from _walk(v, k)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk(item, key_name)
    else:
        yield (key_name, obj)


def key_byte_overhead(obj) -> dict:
    """Section 8: bytes attributable purely to repeated JSON key names
    (the key string itself, not its value), key by key."""
    counts: Counter = Counter()
    for tag, value in _walk(obj):
        if tag == "__key__":
            counts[value] += 1
    # Each occurrence costs len(key)+2 quote chars + 1 colon in the
    # serialized form -- count the key-name bytes only (excludes value
    # bytes and structural punctuation, which are reported separately).
    total_bytes = sum(len(k.encode("utf-8")) * n for k, n in counts.items())
    by_key = [{"key": k, "occurrences": n, "bytes": len(k.encode("utf-8")) * n}
             for k, n in counts.most_common(30)]
    return {"total_key_name_bytes": total_bytes, "top_keys": by_key}


def repeated_value_overhead(obj, min_len: int = 6) -> dict:
    """Section 9: repeated STRING values (min_len chars, to skip trivial
    enum-like tokens already covered elsewhere) -- unique vs. total
    occurrences vs. bytes if replaced by a short dictionary reference."""
    counts: Counter = Counter()
    for tag, value in _walk(obj):
        if tag == "__key__":
            continue
        if isinstance(value, str) and len(value) >= min_len:
            counts[value] += 1
    repeated = {v: n for v, n in counts.items() if n > 1}
    total_repeated_bytes = sum(len(v.encode("utf-8")) * n for v, n in repeated.items())
    # A dictionary reference costs roughly the bytes of a short id per
    # occurrence (e.g. "d3") plus the value stored once.
    ref_cost_per_occurrence = 4  # '"d3"' -- conservative, not tuned
    projected_bytes_with_dictionary = sum(
        len(v.encode("utf-8")) + ref_cost_per_occurrence * n for v, n in repeated.items())
    top = sorted(repeated.items(), key=lambda kv: len(kv[0].encode("utf-8")) * kv[1], reverse=True)[:20]
    return {
        "unique_values_total": len(counts),
        "repeated_values": len(repeated),
        "total_occurrences_of_repeated_values": sum(repeated.values()),
        "bytes_consumed_by_repeated_values": total_repeated_bytes,
        "projected_bytes_with_dictionary_reference": projected_bytes_with_dictionary,
        "projected_byte_reduction": total_repeated_bytes - projected_bytes_with_dictionary,
        "top_repeated_values_by_bytes": [
            {"occurrences": n, "chars": len(v), "bytes_consumed": len(v.encode("utf-8")) * n,
             "sample_prefix": v[:40]} for v, n in top],
    }


def source_refs_forensics(obj) -> dict:
    """Section 10: source_refs specifically."""
    refs = []

    def _collect(o):
        if isinstance(o, dict):
            if "source_refs" in o and isinstance(o["source_refs"], list):
                refs.extend(o["source_refs"])
            for v in o.values():
                _collect(v)
        elif isinstance(o, list):
            for item in o:
                _collect(item)

    _collect(obj)
    if not refs:
        return {"total_source_ref_occurrences": 0}
    identity_keys = [tuple(sorted((k, json.dumps(v, sort_keys=True)) for k, v in r.items()
                                   if k != "excerpt")) if isinstance(r, dict) else None for r in refs]
    unique_identities = len(set(k for k in identity_keys if k is not None))
    total_bytes = sum(len(json.dumps(r, sort_keys=True).encode("utf-8")) for r in refs if isinstance(r, dict))
    excerpt_bytes = sum(len((r.get("excerpt") or "").encode("utf-8")) for r in refs if isinstance(r, dict))
    return {
        "total_source_ref_occurrences": len(refs),
        "unique_source_identities_excluding_excerpt": unique_identities,
        "repeated_identity_occurrences": len(refs) - unique_identities,
        "total_source_refs_bytes": total_bytes,
        "total_excerpt_bytes": excerpt_bytes,
        "total_identity_bytes_excluding_excerpt": total_bytes - excerpt_bytes,
    }


def evidence_text_forensics(obj) -> dict:
    """Section 11: evidence/quote-like fields -- measures duplication,
    never removes or prints full text (only short, capped samples)."""
    texts: list[str] = []

    def _collect(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in _EVIDENCE_LIKE_KEYS and isinstance(v, str) and v.strip():
                    texts.append(v)
                else:
                    _collect(v)
        elif isinstance(o, list):
            for item in o:
                _collect(item)

    _collect(obj)
    counts = Counter(texts)
    duplicates = {t: n for t, n in counts.items() if n > 1}
    duplicate_bytes = sum(len(t.encode("utf-8")) * n for t, n in duplicates.items())
    total_bytes = sum(len(t.encode("utf-8")) for t in texts)
    return {
        "evidence_like_field_occurrences": len(texts),
        "unique_evidence_texts": len(counts),
        "exact_duplicate_texts": len(duplicates),
        "bytes_in_exact_duplicates": duplicate_bytes,
        "total_evidence_bytes": total_bytes,
        "duplicate_pct_of_evidence_bytes": round(100 * duplicate_bytes / total_bytes, 1) if total_bytes else None,
    }


def cardinality_analysis(obj: dict) -> dict:
    """Section 12: object-family counts and average bytes/object -- answers
    which family dominates output bytes, not just which has the biggest
    schema."""
    if not isinstance(obj, dict):
        return {}
    families = {}
    for key, value in obj.items():
        if isinstance(value, list):
            count = len(value)
            total_bytes = len(json.dumps(value, sort_keys=True).encode("utf-8"))
            families[key] = {
                "object_count": count,
                "total_bytes": total_bytes,
                "avg_bytes_per_object": round(total_bytes / count, 1) if count else 0,
            }
    ranked = sorted(families.items(), key=lambda kv: kv[1]["total_bytes"], reverse=True)
    return {"families": dict(ranked)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-root", help="Scan every historical run under this directory")
    parser.add_argument("--run-dir", help="Analyze one specific run directory")
    parser.add_argument("--facts-file", help="Payload-composition forensics over one parsed facts JSON")
    parser.add_argument("--max-tokens", type=int, default=4000,
                        help="Configured max_tokens for utilization classification (default: Fast Analysis's 4000)")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args()

    report: dict = {}

    if args.evaluation_root or args.run_dir:
        run_dirs = ([Path(args.run_dir)] if args.run_dir
                   else discover_runs(Path(args.evaluation_root)))
        runs = [load_run(d) for d in run_dirs]
        report["runs"] = [summarize_run(r) for r in runs]
        report["recovery_tax"] = [recovery_tax(r) for r in runs]
        report["truncation_forensics"] = [truncation_forensics(r) for r in runs]
        report["route_breakdown"] = {r["run_id"]: route_breakdown(r) for r in runs}
        report["max_tokens_utilization"] = [max_tokens_utilization(r, args.max_tokens) for r in runs]

    if args.facts_file:
        facts = json.loads(Path(args.facts_file).read_text(encoding="utf-8"))
        report["payload_forensics"] = {
            "key_byte_overhead": key_byte_overhead(facts),
            "repeated_value_overhead": repeated_value_overhead(facts),
            "source_refs_forensics": source_refs_forensics(facts),
            "evidence_text_forensics": evidence_text_forensics(facts),
            "cardinality_analysis": cardinality_analysis(facts),
        }

    if not report:
        print("Nothing to do -- pass --evaluation-root, --run-dir, and/or --facts-file.", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        if "runs" in report:
            print(f"{'RUN':<45} {'CALLS':>6} {'BASE':>5} {'RETRY':>6} {'RETRY%':>7} {'IN_TOK':>8} {'OUT_TOK':>8}")
            for row in report["runs"]:
                print(f"{row['run_id']:<45} {row['calls_telemetry_rows']:>6} {row['base_calls']:>5} "
                     f"{row['retry_or_recovery_calls']:>6} {str(row['retry_percentage']):>7} "
                     f"{str(row['input_tokens']):>8} {str(row['output_tokens']):>8}")
            print()
        if "payload_forensics" in report:
            pf = report["payload_forensics"]
            print("PAYLOAD FORENSICS")
            print("  key_byte_overhead.total_key_name_bytes:", pf["key_byte_overhead"]["total_key_name_bytes"])
            print("  repeated_value_overhead.bytes_consumed_by_repeated_values:",
                 pf["repeated_value_overhead"]["bytes_consumed_by_repeated_values"])
            print("  source_refs_forensics:", pf["source_refs_forensics"])
            print("  evidence_text_forensics:", pf["evidence_text_forensics"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
