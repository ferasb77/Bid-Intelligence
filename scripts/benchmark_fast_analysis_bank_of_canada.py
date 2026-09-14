"""FAST ANALYSIS V1 -- first live benchmark against the authoritative
16-document Bank of Canada RFP 2026-026 corpus, concurrency=2 (matching the
Deep Verify baseline's validated concurrency level for a fair comparison).

NON_AUTHORITATIVE_TELEMETRY_RUN. Does not touch, rerun, or overwrite any
Deep Verify artifact. Deep Verify baseline for comparison:
  concurrency=2 : 1227.524433s (stagea-concurrency2-full-boc-2026-026-20260913T054732Z-48564b)
  serial        : 2213.868837s (stagea-perf-boc-2026-026-20260912T224533Z-cf5a4d)
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
DEEP_CONCURRENCY2_BASELINE_SECONDS = 1227.524433
DEEP_SERIAL_BASELINE_SECONDS = 2213.868837
EXPECTED_COUNT = 16
MAX_DOCUMENT_CONCURRENCY = 2

RUN_ID = f"fastanalysis-v1-boc-2026-026-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
OUT = ROOT / "evaluation/bank_of_canada_briefing_pack/performance_telemetry" / RUN_ID
OUT.mkdir(parents=True, exist_ok=False)

from config import get_api_key
from extractor import extract_document_with_metadata
from fast_analysis import run_fast_analysis_corpus, FastAnalysisResult

manifest_bytes = MANIFEST_PATH.read_bytes()
manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
if manifest_digest != FROZEN_CORPUS_DIGEST:
    raise RuntimeError("corpus manifest digest mismatch: refusing to spend on an unverified corpus")

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

print("FAST ANALYSIS V1 benchmark:", RUN_ID)

t_parse_start = time.monotonic()
documents = []
for name, payload in package:
    text, _ = extract_document_with_metadata(payload, name)
    documents.append((name, text))
parsing_seconds = time.monotonic() - t_parse_start

result: FastAnalysisResult = run_fast_analysis_corpus(documents, api_key,
                                                       max_document_concurrency=MAX_DOCUMENT_CONCURRENCY)

# ---- persist raw telemetry ----
(OUT / "fast_analysis_llm_calls.jsonl").write_text(
    "\n".join(json.dumps(c, sort_keys=True, default=str) for c in result.telemetry) + "\n", encoding="utf-8")

recovery_calls = [c for c in result.telemetry if c.get("call_kind") != "initial" and c.get("call_kind") != "batch"]
total_input = sum(c.get("input_tokens") or 0 for c in result.telemetry)
total_output = sum(c.get("output_tokens") or 0 for c in result.telemetry)
total_calls = len(result.telemetry)
total_records = (len(result.typed_observations) + len(result.evaluation_criteria)
                + len(result.requirements) + len(result.commercial_clauses))

totals = {
    "run_id": RUN_ID,
    "run_classification": "NON_AUTHORITATIVE_TELEMETRY_RUN",
    "corpus_manifest_digest": manifest_digest,
    "documents_total": EXPECTED_COUNT,
    "documents_skipped": result.skipped_documents,
    "documents_skipped_count": len(result.skipped_documents),
    "documents_batched": result.batched_documents,
    "documents_by_route": result.documents_by_route,
    "page_limits_deterministic": result.page_limits,
    "total_calls": total_calls,
    "recovery_or_retry_calls": len(recovery_calls),
    "total_input_tokens": total_input,
    "total_output_tokens": total_output,
    "total_evaluation_criteria_records": len(result.evaluation_criteria),
    "total_typed_observations_records": len(result.typed_observations),
    "total_requirements_records": len(result.requirements),
    "total_commercial_clauses_records": len(result.commercial_clauses),
    "total_records": total_records,
    "ambiguities_detected": {k: len(v) for k, v in result.ambiguities.items()},
    "corpus_parsing_seconds": round(parsing_seconds, 6),
    "deterministic_extraction_seconds": result.deterministic_seconds,
    "fast_analysis_wall_seconds": result.wall_seconds,
    "total_wall_seconds": round(parsing_seconds + result.wall_seconds, 6),
    "deep_concurrency2_baseline_seconds": DEEP_CONCURRENCY2_BASELINE_SECONDS,
    "deep_serial_baseline_seconds": DEEP_SERIAL_BASELINE_SECONDS,
    "speedup_vs_deep_concurrency2": round(DEEP_CONCURRENCY2_BASELINE_SECONDS / max(result.wall_seconds, 0.001), 3),
    "speedup_vs_deep_serial": round(DEEP_SERIAL_BASELINE_SECONDS / max(result.wall_seconds, 0.001), 3),
}
(OUT / "fast_analysis_totals.json").write_text(json.dumps(totals, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")

(OUT / "fast_analysis_facts.json").write_text(json.dumps({
    "doc_metadata_by_doc": result.doc_metadata_by_doc,
    "typed_observations": result.typed_observations,
    "evaluation_criteria": result.evaluation_criteria,
    "requirements": result.requirements,
    "commercial_clauses": result.commercial_clauses,
    "page_limits": result.page_limits,
    "ambiguities": result.ambiguities,
}, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")

print()
print("FAST ANALYSIS V1 TOTALS")
print(json.dumps(totals, indent=2, sort_keys=True, default=str))
print()
print("Persisted at:", OUT)

# ---- build the Fast Analysis PDF via the shared renderer ----
from scripts.fast_analysis_report_adapter import build_fast_report_content
from scripts.build_boc_bid_intelligence_preview_pdf import build as build_pdf

fast_content = build_fast_report_content(result)
fast_pdf_path = ROOT / "BANK_OF_CANADA_RFP_2026_026_BID_INTELLIGENCE_PREVIEW_FAST.pdf"
t_report_start = time.monotonic()
build_pdf(content=fast_content, out_path=fast_pdf_path)
report_seconds = time.monotonic() - t_report_start
print("Fast Analysis PDF written to:", fast_pdf_path, f"({report_seconds:.3f}s)")

totals["report_assembly_seconds"] = round(report_seconds, 6)
(OUT / "fast_analysis_totals.json").write_text(json.dumps(totals, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")
print("run_dir:", OUT)
