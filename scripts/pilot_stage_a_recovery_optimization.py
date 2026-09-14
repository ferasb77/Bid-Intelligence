"""STAGE A RECOVERY-PATH OPTIMIZATION -- FIVE-DOCUMENT CONTROLLED PILOT.

NON_AUTHORITATIVE_TELEMETRY_RUN. One live execution of exactly the five
recovery-heavy documents identified by the accepted Stage A live telemetry
control run, using the SAME corpus bytes, SAME model/temperature/chunking/
recovery-cascade/document-ordering/serial-execution, with the SINGLE change
under test: _STAGE_A_MAX_OUTPUT_TOKENS raised from 8000 to 16000 in
extractor.py (Stage A Recovery-Path Optimization Package 2).

Control run (do not overwrite, do not rerun):
  stagea-perf-boc-2026-026-20260912T224533Z-cf5a4d

No retries beyond normal production recovery behavior. Not promoted into
any authoritative lineage. Does not touch Stage B/C/Canonical Opportunity.
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

PILOT_DOCUMENTS = [
    "RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf",
    "OriginalRevision/RFP 2026-06 - Appendix G - Form of Agreement.docx",
    "OriginalRevision/RFP 2026-026 - Appendix E - Pricing Form.xlsx",
    "OriginalRevision/RFP 2026-026 - Appendix D1 - Rated criteria response form.docx",
    "abstract.pdf",
]

RUN_ID = f"stagea-pilot-recovery-opt2-boc-2026-026-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
OUT = ROOT / "evaluation/bank_of_canada_briefing_pack/performance_telemetry" / RUN_ID
OUT.mkdir(parents=True, exist_ok=False)

from config import get_api_key
from extractor import (
    extract_document_with_metadata, extract_document_facts,
    STAGE_A_FACT_EXTRACTION_PROMPT, _STAGE_A_MAX_OUTPUT_TOKENS, _STAGE_A_MAX_CHUNK_CHARS,
)

# --- corpus identity gate (fail closed before spending anything) ---
manifest_bytes = MANIFEST_PATH.read_bytes()
manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
if manifest_digest != FROZEN_CORPUS_DIGEST:
    raise RuntimeError(f"corpus manifest digest mismatch: refusing to spend on an unverified corpus")

manifest = json.loads(manifest_bytes)
manifest_digests = {item["path"]: item["sha256"] for item in manifest["files"]}
for name in PILOT_DOCUMENTS:
    p = CORPUS / name
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    if digest != manifest_digests.get(name):
        raise RuntimeError(f"pilot document digest mismatch for {name}; refusing to dispatch")

api_key = get_api_key()
if not api_key:
    raise RuntimeError("ANTHROPIC_API_KEY is unavailable; cannot perform the authorized pilot run")

run_metadata = {
    "run_id": RUN_ID,
    "run_classification": "NON_AUTHORITATIVE_TELEMETRY_RUN",
    "purpose": "Stage A Recovery-Path Optimization Package 2 -- five-document controlled pilot",
    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    "control_run_id": CONTROL_RUN_ID,
    "pilot_documents": PILOT_DOCUMENTS,
    "candidate_change": {
        "parameter": "_STAGE_A_MAX_OUTPUT_TOKENS",
        "control_value": 8000,
        "candidate_value": _STAGE_A_MAX_OUTPUT_TOKENS,
        "unchanged": ["prompt", "chunking (_STAGE_A_MAX_CHUNK_CHARS=%d)" % _STAGE_A_MAX_CHUNK_CHARS,
                      "recovery cascade logic", "model", "temperature", "concurrency (serial, 1)",
                      "document ordering"],
    },
    "corpus_manifest_digest": manifest_digest,
}
(OUT / "run_metadata.json").write_text(json.dumps(run_metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
print("NON_AUTHORITATIVE_TELEMETRY_RUN (pilot):", RUN_ID)

document_records = []
document_facts_by_name = {}
telemetry: list[dict] = []

pilot_wall_start = time.monotonic()
for sequence, name in enumerate(PILOT_DOCUMENTS, start=1):
    file_bytes = (CORPUS / name).read_bytes()
    doc_text, _ = extract_document_with_metadata(file_bytes, name)
    calls_before = len(telemetry)
    t0 = time.monotonic()
    facts = extract_document_facts(doc_text, name, api_key, telemetry=telemetry)
    doc_seconds = time.monotonic() - t0
    doc_calls = telemetry[calls_before:len(telemetry)]

    document_facts_by_name[name] = facts
    diagnostic = facts.get("_extraction_diagnostic", {})
    record_counts = {k: len(v) for k, v in facts.items() if isinstance(v, list) and not k.startswith("_")}
    total_records = sum(record_counts.values())
    document_records.append({
        "sequence": sequence, "path": name, "file_bytes": len(file_bytes),
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
    (OUT / "stage_a_document_telemetry.json").write_text(
        json.dumps(document_records, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")
    (OUT / "stage_a_llm_calls.jsonl").write_text(
        "\n".join(json.dumps(c, sort_keys=True, default=str) for c in telemetry) + "\n", encoding="utf-8")

pilot_wall_seconds = time.monotonic() - pilot_wall_start
(OUT / "stage_a_document_facts.json").write_text(
    json.dumps(document_facts_by_name, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")

totals = {
    "documents": len(document_records),
    "total_calls": len(telemetry),
    "total_input_tokens": sum(c["input_tokens"] or 0 for c in telemetry),
    "total_output_tokens": sum(c["output_tokens"] or 0 for c in telemetry),
    "total_api_seconds": round(sum(c["latency_seconds"] for c in telemetry), 6),
    "pilot_wall_seconds": round(pilot_wall_seconds, 6),
    "total_records": sum(d["total_records"] for d in document_records),
    "recovered_truncated_documents": [d["path"] for d in document_records if d["recovery_status"] == "RECOVERED_TRUNCATED"],
    "recovered_truncated_count": sum(1 for d in document_records if d["recovery_status"] == "RECOVERED_TRUNCATED"),
    "zero_output_documents": [d["path"] for d in document_records if d["total_records"] == 0],
    "calls_with_errors": sum(1 for c in telemetry if c.get("error")),
    "recovery_call_count": sum(1 for c in telemetry if c["call_kind"] != "initial"),
    "initial_call_count": sum(1 for c in telemetry if c["call_kind"] == "initial"),
}
(OUT / "stage_a_totals.json").write_text(json.dumps(totals, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
print()
print("PILOT TOTALS")
print(json.dumps(totals, indent=2, sort_keys=True))
print()
print("Pilot persisted at:", OUT)
