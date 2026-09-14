"""Analysis pass over the Stage A live telemetry acquisition run.
Read-only; produces the derived tables the report needs (recovery tax,
token/wall-time distribution, master RFP trace, historical comparison).
No LLM calls -- this only reads already-persisted telemetry JSON/JSONL.
"""
import json
import sys
from pathlib import Path

RUN_ID = sys.argv[1] if len(sys.argv) > 1 else "stagea-perf-boc-2026-026-20260912T224533Z-cf5a4d"
ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/performance_telemetry" / RUN_ID

docs = json.loads((RUN_DIR / "stage_a_document_telemetry.json").read_text(encoding="utf-8"))
calls = [json.loads(line) for line in (RUN_DIR / "stage_a_llm_calls.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
totals = json.loads((RUN_DIR / "stage_a_totals.json").read_text(encoding="utf-8"))

print("=== Recovery tax per recovered document ===")
recovery_summary = []
for d in docs:
    if d["recovery_status"] != "RECOVERED_TRUNCATED":
        continue
    doc_calls = [c for c in calls if c["call_index"] in d["call_indices"]]
    initial = [c for c in doc_calls if c["call_kind"] == "initial"]
    recovery = [c for c in doc_calls if c["call_kind"] != "initial"]
    initial_in = sum(c["input_tokens"] or 0 for c in initial)
    initial_out = sum(c["output_tokens"] or 0 for c in initial)
    recovery_in = sum(c["input_tokens"] or 0 for c in recovery)
    recovery_out = sum(c["output_tokens"] or 0 for c in recovery)
    initial_lat = sum(c["latency_seconds"] for c in initial)
    recovery_lat = sum(c["latency_seconds"] for c in recovery)
    doc_total_tokens = initial_in + initial_out + recovery_in + recovery_out
    doc_total_time = initial_lat + recovery_lat
    entry = {
        "document": d["path"], "call_kinds": d["call_kinds"],
        "initial_input_tokens": initial_in, "initial_output_tokens": initial_out,
        "recovery_input_tokens": recovery_in, "recovery_output_tokens": recovery_out,
        "initial_latency": round(initial_lat, 3), "recovery_latency": round(recovery_lat, 3),
        "pct_tokens_from_recovery": round(100 * (recovery_in + recovery_out) / doc_total_tokens, 2) if doc_total_tokens else 0,
        "pct_time_from_recovery": round(100 * recovery_lat / doc_total_time, 2) if doc_total_time else 0,
        "records": d["total_records"],
    }
    recovery_summary.append(entry)
    print(json.dumps(entry, indent=2))

corpus_recovery_input = sum(e["recovery_input_tokens"] for e in recovery_summary)
corpus_recovery_output = sum(e["recovery_output_tokens"] for e in recovery_summary)
corpus_recovery_latency = sum(e["recovery_latency"] for e in recovery_summary)
print()
print("=== Corpus-wide recovery tax ===")
print("RECOVERY TOKEN TAX (input):", corpus_recovery_input, "/", totals["total_input_tokens"],
      "=", round(100 * corpus_recovery_input / totals["total_input_tokens"], 2), "%")
print("RECOVERY TOKEN TAX (output):", corpus_recovery_output, "/", totals["total_output_tokens"],
      "=", round(100 * corpus_recovery_output / totals["total_output_tokens"], 2), "%")
print("RECOVERY TIME TAX:", round(corpus_recovery_latency, 2), "/", round(totals["total_api_seconds"], 2),
      "=", round(100 * corpus_recovery_latency / totals["total_api_seconds"], 2), "%")

print()
print("=== Token distribution (ranked, cumulative %) ===")
by_tokens = sorted(docs, key=lambda d: -d["input_tokens"])
cum = 0
for rank, d in enumerate(by_tokens, 1):
    cum += d["input_tokens"]
    pct = round(100 * d["input_tokens"] / totals["total_input_tokens"], 2)
    cumpct = round(100 * cum / totals["total_input_tokens"], 2)
    print(f"{rank:2d}. {d['path'][:70]:70s} tokens={d['input_tokens']:7d} pct={pct:6.2f}% cum={cumpct:6.2f}%")

print()
print("=== Wall-time distribution (ranked, cumulative %) ===")
by_time = sorted(docs, key=lambda d: -d["total_document_seconds"])
cum = 0
total_doc_seconds = sum(d["total_document_seconds"] for d in docs)
for rank, d in enumerate(by_time, 1):
    cum += d["total_document_seconds"]
    pct = round(100 * d["total_document_seconds"] / total_doc_seconds, 2)
    cumpct = round(100 * cum / total_doc_seconds, 2)
    print(f"{rank:2d}. {d['path'][:70]:70s} sec={d['total_document_seconds']:8.2f} pct={pct:6.2f}% cum={cumpct:6.2f}%")

print()
print("=== Master RFP trace ===")
master = next(d for d in docs if d["path"].startswith("RFP 2026-026 - Talent"))
print(json.dumps({
    "input_tokens": master["input_tokens"], "output_tokens": master["output_tokens"],
    "calls": master["calls"], "latency_seconds": master["total_document_seconds"],
    "records": master["total_records"], "recovery": master["recovery_status"],
    "pct_of_total_stage_a_time": round(100 * master["total_document_seconds"] / total_doc_seconds, 2),
    "pct_of_total_input_tokens": round(100 * master["input_tokens"] / totals["total_input_tokens"], 2),
    "call_kinds": master["call_kinds"], "stop_reasons": master["stop_reasons"],
}, indent=2))

print()
print("=== call sequences for the 4 historically-recovered documents ===")
for path_prefix in ("abstract.pdf", "Appendix D1", "Appendix G", "RFP 2026-026 - Talent"):
    d = next(x for x in docs if path_prefix in x["path"])
    doc_calls = [c for c in calls if c["call_index"] in d["call_indices"]]
    print(f"--- {d['path']} ---")
    for c in doc_calls:
        print(f"  call_index={c['call_index']:3d} kind={c['call_kind']:30s} parse_status={c['parse_status']:20s} "
              f"in={c['input_tokens'] or 0:6d} out={c['output_tokens'] or 0:6d} lat={c['latency_seconds']:7.3f}s "
              f"stop={c['stop_reason']}")
