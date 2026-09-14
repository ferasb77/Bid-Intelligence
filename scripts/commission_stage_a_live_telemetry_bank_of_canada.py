"""STAGE A LIVE TELEMETRY ACQUISITION -- NON_AUTHORITATIVE_TELEMETRY_RUN.

Authorized, single, live Stage A execution over the frozen, authoritative
16-document Bank of Canada RFP 2026-026 corpus, using the observability
instrumentation added to extractor.py's extract_document_facts()/
_extract_chunk_facts() (the `telemetry` list parameter). This is a
measurement-only run:

  * Zero production behavior is changed -- same model
    (claude-haiku-4-5-20251001), same prompt (STAGE_A_FACT_EXTRACTION_PROMPT,
    unmodified), same temperature (0.0), same max_tokens (8000), same
    chunking (_STAGE_A_MAX_CHUNK_CHARS, unmodified), same bounded
    recovery/coverage-guard cascade, same document ordering, same serial
    (no-concurrency) execution, same client construction path
    (get_anthropic_client). Only the `telemetry` list is new, and it is
    purely additive (see extract_document_facts' own docstring: default
    None is a complete no-op for every other caller).
  * This run's own output is NOT promoted into the authoritative lineage.
    It does not write to, or read from, phase1_commissioning/
    phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5/ (the frozen
    Phase 1 artifact) at all. It is persisted under its own, separate
    performance/telemetry directory, run-ID-prefixed to make its
    non-authoritative status unambiguous.
  * Stage B/C/Canonical Opportunity/Opportunity Structure/EOB/Pack are NOT
    regenerated from this run's Stage A output. Only enough validation is
    performed to confirm Stage A itself completed (document count,
    zero-output check, record counts) -- nothing downstream is touched.

One execution only. No manual re-run of any single document. Normal
production retry/recovery behavior is allowed to fire exactly as already
configured (this is the point of the measurement).
"""
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
FROZEN_PHASE1_RUN_ID = "phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5"
FROZEN_GIT_TAG = "bid-intelligence-rc2"
EXPECTED_COUNT = 16

RUN_ID = f"stagea-perf-boc-2026-026-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
OUT = ROOT / "evaluation/bank_of_canada_briefing_pack/performance_telemetry" / RUN_ID
OUT.mkdir(parents=True, exist_ok=False)

import hashlib

from config import get_api_key
from extractor import extract_document_with_metadata, extract_document_facts, STAGE_A_FACT_EXTRACTION_PROMPT

# --- Step 3: corpus identity gate (fail closed before spending anything) ---

manifest_bytes = MANIFEST_PATH.read_bytes()
manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
if manifest_digest != FROZEN_CORPUS_DIGEST:
    raise RuntimeError(
        f"corpus manifest digest mismatch: {manifest_digest} != frozen {FROZEN_CORPUS_DIGEST}; "
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
    raise RuntimeError("ANTHROPIC_API_KEY is unavailable; cannot perform the authorized live run")

run_metadata = {
    "run_id": RUN_ID,
    "run_classification": "NON_AUTHORITATIVE_TELEMETRY_RUN",
    "purpose": "Stage A live telemetry acquisition only -- measurement, not baseline replacement",
    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    "frozen_baseline_reference": {
        "git_tag": FROZEN_GIT_TAG,
        "authoritative_phase1_run_id": FROZEN_PHASE1_RUN_ID,
        "corpus_digest": FROZEN_CORPUS_DIGEST,
        "historical_stage_a_wall_seconds": 2245.556,
        "historical_stage_a_records": 916,
        "historical_recovered_truncated_documents": 4,
    },
    "corpus_identity_verified": True,
    "corpus_manifest_digest": manifest_digest,
    "document_count": len(package),
    "production_configuration": {
        "model": "claude-haiku-4-5-20251001",
        "temperature": 0.0,
        "max_tokens": 8000,
        "prompt_sha256": hashlib.sha256(STAGE_A_FACT_EXTRACTION_PROMPT.encode("utf-8")).hexdigest(),
        "prompt_chars": len(STAGE_A_FACT_EXTRACTION_PROMPT),
        "chunking_strategy": "extractor.chunk_document_text (marker-aware, unmodified)",
        "retry_policy": "Anthropic SDK default (unmodified client construction via get_anthropic_client)",
        "recovery_policy": "extractor.py bounded sub-chunk + coverage-guard recovery cascade (unmodified)",
        "concurrency": "serial -- one document at a time, one chunk call at a time (unmodified)",
        "document_ordering": "sorted by corpus-relative path (matches Phase 1)",
        "production_entry_point": "extractor.extract_document_facts (identical to Phase 1's entry point, "
                                   "plus the additive telemetry= parameter)",
        "instrumentation_files_changed": ["extractor.py"],
        "instrumentation_is_additive_confirmed_by": "tests/test_stage_a_extraction_reliability.py::TestStageATelemetryCapture "
                                                     "(35 tests, including test_telemetry_default_none_is_a_complete_no_op)",
    },
    "no_downstream_promotion": True,
    "authoritative_lineage_untouched": True,
}
(OUT / "run_metadata.json").write_text(json.dumps(run_metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
print("NON_AUTHORITATIVE_TELEMETRY_RUN:", RUN_ID)
print(json.dumps(run_metadata["frozen_baseline_reference"], indent=2))

# --- Document parsing (deterministic, no LLM) -- same as Phase 1 ---

metadata = {"files": [], "doc_metadata": {}, "doc_texts": {}}
t_parse_start = time.monotonic()
for name, payload in package:
    text, meta = extract_document_with_metadata(payload, name)
    metadata["files"].append(name)
    metadata["doc_metadata"][name] = meta
    metadata["doc_texts"][name] = text
parsing_seconds = time.monotonic() - t_parse_start

document_records = []
document_facts_by_name = {}
telemetry: list[dict] = []  # ONE shared list across the whole run -> globally unique call_index

stage_a_wall_start = time.monotonic()
for sequence, name in enumerate(metadata["files"], start=1):
    # metadata["files"] is already in exactly the same order Phase 1 used
    # (built by appending, in order, while iterating `package`, which was
    # itself built from `sorted(p for p in CORPUS.rglob("*") if p.is_file())`
    # -- the identical expression scripts/commission_phase1_bank_of_canada.py
    # uses). Re-sorting it here by any other key risks silently diverging
    # from Phase 1's document ordering; iterating it as-is cannot.
    doc_text = metadata["doc_texts"][name]
    file_bytes = next(len(payload) for fname, payload in package if fname == name)
    calls_before = len(telemetry)
    t0 = time.monotonic()
    facts = extract_document_facts(doc_text, name, api_key, telemetry=telemetry)
    doc_seconds = time.monotonic() - t0
    calls_after = len(telemetry)
    doc_calls = telemetry[calls_before:calls_after]

    document_facts_by_name[name] = facts
    diagnostic = facts.get("_extraction_diagnostic", {})
    record_counts = {k: len(v) for k, v in facts.items()
                     if isinstance(v, list) and not k.startswith("_")}
    total_records = sum(record_counts.values())
    document_records.append({
        "sequence": sequence, "path": name, "file_bytes": file_bytes,
        "parsed_characters": len(doc_text),
        "calls": len(doc_calls), "call_indices": [c["call_index"] for c in doc_calls],
        "input_tokens": sum(c["input_tokens"] or 0 for c in doc_calls),
        "output_tokens": sum(c["output_tokens"] or 0 for c in doc_calls),
        "api_seconds": round(sum(c["latency_seconds"] for c in doc_calls), 6),
        "total_document_seconds": round(doc_seconds, 6),
        "total_records": total_records, "record_counts_by_family": record_counts,
        "recovery_status": diagnostic.get("status", "VERIFIED_ADEQUATE"),
        "extraction_diagnostic": diagnostic,
        "call_kinds": [c["call_kind"] for c in doc_calls],
        "stop_reasons": [c["stop_reason"] for c in doc_calls],
    })
    print(json.dumps({"sequence": sequence, "document": name, "calls": len(doc_calls),
                      "input_tokens": document_records[-1]["input_tokens"],
                      "output_tokens": document_records[-1]["output_tokens"],
                      "seconds": round(doc_seconds, 3), "records": total_records,
                      "recovery_status": document_records[-1]["recovery_status"]}, sort_keys=True), flush=True)
    # Persist incrementally so a mid-run interruption still leaves partial, honest telemetry.
    (OUT / "stage_a_document_telemetry.json").write_text(
        json.dumps(document_records, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")
    (OUT / "stage_a_llm_calls.jsonl").write_text(
        "\n".join(json.dumps(c, sort_keys=True, default=str) for c in telemetry) + "\n", encoding="utf-8")

stage_a_wall_seconds = time.monotonic() - stage_a_wall_start

t_write_start = time.monotonic()
(OUT / "stage_a_document_facts.json").write_text(
    json.dumps(document_facts_by_name, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")
serialization_seconds = time.monotonic() - t_write_start

totals = {
    "documents": len(document_records),
    "total_calls": len(telemetry),
    "total_input_tokens": sum(c["input_tokens"] or 0 for c in telemetry),
    "total_output_tokens": sum(c["output_tokens"] or 0 for c in telemetry),
    "total_api_seconds": round(sum(c["latency_seconds"] for c in telemetry), 6),
    "stage_a_wall_seconds": round(stage_a_wall_seconds, 6),
    "corpus_parsing_seconds": round(parsing_seconds, 6),
    "artifact_serialization_seconds": round(serialization_seconds, 6),
    "total_records": sum(d["total_records"] for d in document_records),
    "recovered_truncated_documents": [d["path"] for d in document_records if d["recovery_status"] == "RECOVERED_TRUNCATED"],
    "recovered_truncated_count": sum(1 for d in document_records if d["recovery_status"] == "RECOVERED_TRUNCATED"),
    "zero_output_documents": [d["path"] for d in document_records if d["total_records"] == 0],
    "calls_with_errors": sum(1 for c in telemetry if c.get("error")),
}
(OUT / "stage_a_totals.json").write_text(json.dumps(totals, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
print()
print("STAGE A LIVE TELEMETRY TOTALS")
print(json.dumps(totals, indent=2, sort_keys=True))
print()
print("Non-authoritative telemetry run persisted at:", OUT)
