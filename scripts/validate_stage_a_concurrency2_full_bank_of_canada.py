"""STAGE A OPTIMIZATION PACKAGE 4 -- FULL 16-DOCUMENT CONCURRENCY VALIDATION.

NON_AUTHORITATIVE_TELEMETRY_RUN. One live execution of the full, authoritative
16-document Bank of Canada corpus at max_document_concurrency=2. Everything
inside each document's own extraction is byte-for-byte unchanged from the
accepted serial control (same prompt, max_tokens=8000, chunk size, recovery
trigger/order, merge/dedup). The only behavioral variable is that up to 2 of
the 16 documents may be in flight on the Anthropic API at once, via
scripts.stage_a_concurrency_orchestrator (already validated on the
five-document pilot, stagea-pilot-concurrency2-boc-2026-026-20260913T052312Z-b981a2).

Control (do not rerun, do not overwrite): stagea-perf-boc-2026-026-20260912T224533Z-cf5a4d
"""
import hashlib
import json
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CORPUS = ROOT / "evaluation/bank_of_canada_briefing_pack/corrected_procurement_corpus"
MANIFEST_PATH = ROOT / "evaluation/bank_of_canada_briefing_pack/corrected_corpus_manifest.json"
FROZEN_CORPUS_DIGEST = "5493933d2bba7ce80ede3c367e865635c4bd410d702b64a103d916d4573b95f2"
CONTROL_RUN_ID = "stagea-perf-boc-2026-026-20260912T224533Z-cf5a4d"
MAX_DOCUMENT_CONCURRENCY = 2
EXPECTED_COUNT = 16

RUN_ID = f"stagea-concurrency2-full-boc-2026-026-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
OUT = ROOT / "evaluation/bank_of_canada_briefing_pack/performance_telemetry" / RUN_ID
OUT.mkdir(parents=True, exist_ok=False)

from config import get_api_key
from extractor import extract_document_with_metadata, extract_document_facts, _STAGE_A_MAX_OUTPUT_TOKENS, _STAGE_A_MAX_CHUNK_CHARS
from scripts.stage_a_concurrency_orchestrator import (
    DocumentJob, run_concurrent_documents, merge_telemetry_deterministic, observed_max_simultaneous_requests,
)

# --- corpus identity gate (fail closed before spending anything) ---
manifest_bytes = MANIFEST_PATH.read_bytes()
manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
if manifest_digest != FROZEN_CORPUS_DIGEST:
    raise RuntimeError(f"corpus manifest digest mismatch: {manifest_digest} != frozen {FROZEN_CORPUS_DIGEST}; "
                       "refusing to spend on an unverified corpus")

manifest = json.loads(manifest_bytes)
paths = sorted(p for p in CORPUS.rglob("*") if p.is_file())
package = [(p.relative_to(CORPUS).as_posix(), p.read_bytes()) for p in paths]
if len(package) != EXPECTED_COUNT:
    raise RuntimeError(f"expected {EXPECTED_COUNT} documents, found {len(package)}; refusing to dispatch")
fresh_digests = {name: hashlib.sha256(payload).hexdigest() for name, payload in package}
manifest_digests = {item["path"]: item["sha256"] for item in manifest["files"]}
if fresh_digests != manifest_digests:
    raise RuntimeError("per-file corpus digests do not match the frozen manifest; refusing to dispatch")

api_key = get_api_key()
if not api_key:
    raise RuntimeError("ANTHROPIC_API_KEY is unavailable; cannot perform the authorized run")

run_metadata = {
    "run_id": RUN_ID,
    "run_classification": "NON_AUTHORITATIVE_TELEMETRY_RUN",
    "purpose": "Stage A Optimization Package 4 -- full 16-document concurrency=2 validation",
    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    "control_run_id": CONTROL_RUN_ID,
    "pilot_run_id_precursor": "stagea-pilot-concurrency2-boc-2026-026-20260913T052312Z-b981a2",
    "max_document_concurrency": MAX_DOCUMENT_CONCURRENCY,
    "document_count": len(package),
    "corpus_manifest_digest": manifest_digest,
    "unchanged": {
        "max_tokens": _STAGE_A_MAX_OUTPUT_TOKENS, "chunk_size": _STAGE_A_MAX_CHUNK_CHARS,
        "model": "claude-haiku-4-5-20251001", "temperature": 0.0,
        "prompt": "unchanged (see tests/test_stage_a_concurrency_pilot.py hash pin)",
        "recovery_trigger_and_order": "unchanged -- documents call the unmodified extract_document_facts()",
    },
}
(OUT / "run_metadata.json").write_text(json.dumps(run_metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
print("NON_AUTHORITATIVE_TELEMETRY_RUN (full concurrency validation):", RUN_ID)

t_parse_start = time.monotonic()
jobs = []
for i, (name, payload) in enumerate(package):
    text, _ = extract_document_with_metadata(payload, name)
    jobs.append(DocumentJob(index=i, name=name, doc_text=text))
parsing_seconds = time.monotonic() - t_parse_start

wall_start = time.monotonic()
results, retry_log = run_concurrent_documents(jobs, extract_document_facts, api_key,
                                               max_document_concurrency=MAX_DOCUMENT_CONCURRENCY)
wall_seconds = time.monotonic() - wall_start

# Verify deterministic corpus-order reconstruction
expected_order = [j.name for j in jobs]
actual_order = [r.name for r in results]
if actual_order != expected_order:
    raise RuntimeError(f"CORPUS ORDER VIOLATION: expected {expected_order}, got {actual_order}")
print("Corpus-order reconstruction verified:", actual_order == expected_order)

failed = [r for r in results if r.error is not None]

document_records = []
document_facts_by_name = {}
for r in results:
    if r.facts is None:
        document_records.append({"sequence": r.index + 1, "path": r.name, "error": r.error,
                                  "wall_seconds": r.wall_seconds, "worker_thread": r.worker_thread})
        continue
    diagnostic = r.facts.get("_extraction_diagnostic", {})
    record_counts = {k: len(v) for k, v in r.facts.items() if isinstance(v, list) and not k.startswith("_")}
    document_facts_by_name[r.name] = r.facts
    document_records.append({
        "sequence": r.index + 1, "path": r.name,
        "calls": len(r.telemetry), "call_indices": [c["call_index"] for c in r.telemetry],
        "input_tokens": sum(c["input_tokens"] or 0 for c in r.telemetry),
        "output_tokens": sum(c["output_tokens"] or 0 for c in r.telemetry),
        "api_seconds": round(sum(c["latency_seconds"] for c in r.telemetry), 6),
        "total_document_seconds": r.wall_seconds,
        "total_records": sum(record_counts.values()), "record_counts_by_family": record_counts,
        "recovery_status": diagnostic.get("status", "VERIFIED_ADEQUATE"),
        "extraction_diagnostic": diagnostic,
        "call_kinds": [c["call_kind"] for c in r.telemetry],
        "stop_reasons": [c["stop_reason"] for c in r.telemetry],
        "worker_thread": r.worker_thread,
    })
    print(json.dumps({"sequence": r.index + 1, "document": r.name, "calls": len(r.telemetry),
                      "input_tokens": document_records[-1]["input_tokens"],
                      "output_tokens": document_records[-1]["output_tokens"],
                      "seconds": round(r.wall_seconds, 3), "records": document_records[-1]["total_records"],
                      "recovery_status": document_records[-1]["recovery_status"],
                      "worker_thread": r.worker_thread}, sort_keys=True), flush=True)

    (OUT / "stage_a_document_telemetry.json").write_text(
        json.dumps(document_records, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")

merged_telemetry = merge_telemetry_deterministic(results)
max_simultaneous = observed_max_simultaneous_requests(merged_telemetry)

(OUT / "stage_a_document_telemetry.json").write_text(
    json.dumps(document_records, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")
(OUT / "stage_a_llm_calls.jsonl").write_text(
    "\n".join(json.dumps(c, sort_keys=True, default=str) for c in merged_telemetry) + "\n", encoding="utf-8")
(OUT / "stage_a_document_facts.json").write_text(
    json.dumps(document_facts_by_name, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")
(OUT / "retry_log.json").write_text(json.dumps(retry_log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

import re
statuses = re.findall(r'HTTP Response: POST [^"]+"(\d+) ',
                       " ".join(r["message"] for r in retry_log if r["message"].startswith("HTTP Response")))
from collections import Counter
status_counts = Counter(statuses)
real_retries = [r for r in retry_log if "Retrying due to status code" in r["message"]
                or re.search(r"Retrying request to .+ in .+ seconds", r["message"])]
timeout_errors = [c for c in merged_telemetry if c.get("error") and
                  ("timeout" in c["error"].lower() or "connection" in c["error"].lower())]

totals = {
    "documents": len(document_records),
    "total_calls": len(merged_telemetry),
    "total_input_tokens": sum(c["input_tokens"] or 0 for c in merged_telemetry),
    "total_output_tokens": sum(c["output_tokens"] or 0 for c in merged_telemetry),
    "total_api_seconds": round(sum(c["latency_seconds"] for c in merged_telemetry), 6),
    "corpus_parsing_seconds": round(parsing_seconds, 6),
    "stage_a_wall_seconds": round(wall_seconds, 6),
    "total_records": sum(d.get("total_records", 0) for d in document_records),
    "recovered_truncated_documents": [d["path"] for d in document_records if d.get("recovery_status") == "RECOVERED_TRUNCATED"],
    "recovered_truncated_count": sum(1 for d in document_records if d.get("recovery_status") == "RECOVERED_TRUNCATED"),
    "zero_output_documents": [d["path"] for d in document_records if d.get("total_records") == 0],
    "documents_with_errors": [d["path"] for d in document_records if d.get("error")],
    "recovery_call_count": sum(1 for c in merged_telemetry if c.get("call_kind") != "initial"),
    "initial_call_count": sum(1 for c in merged_telemetry if c.get("call_kind") == "initial"),
    "observed_max_simultaneous_requests": max_simultaneous,
    "http_status_code_counts": dict(status_counts),
    "real_sdk_retry_count": len(real_retries),
    "timeout_or_network_errors": len(timeout_errors),
    "status_429_count": status_counts.get("429", 0),
    "status_529_count": status_counts.get("529", 0),
    "max_document_concurrency_configured": MAX_DOCUMENT_CONCURRENCY,
    "corpus_order_verified": actual_order == expected_order,
}
(OUT / "stage_a_totals.json").write_text(json.dumps(totals, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
print()
print("FULL 16-DOCUMENT CONCURRENCY VALIDATION TOTALS")
print(json.dumps(totals, indent=2, sort_keys=True))
print()
print("Full concurrency validation run persisted at:", OUT)

if failed:
    print()
    print("FAILURES:", [(f.name, f.error) for f in failed])
    sys.exit(1)
