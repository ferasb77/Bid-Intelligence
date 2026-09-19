"""
scripts/run_phoenix_client_ready_acceptance.py

Genuine End-to-End Phoenix Fast Analysis Acceptance Script.
Performs:
1. Source document fetch from Supabase (Bid ID 1083, 3 documents)
2. Ingestion via extract_document_with_metadata (deterministic)
3. Live Fast Analysis via run_fast_analysis_corpus (frozen engine)
4. Attachment of generic, externally researched Buyer Intelligence payload
5. Report assembly via build_fast_report_content
6. PDF rendering via build_boc_bid_intelligence_preview_pdf.build
7. Telemetry, page count, and structural validation
"""
import json
import os
import sys
import time
from pathlib import Path

# Ensure repo root is on sys.path
_repo_root = str(Path(__file__).resolve().parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import config
import database as db
from extractor import extract_document_with_metadata
from fast_analysis import run_fast_analysis_corpus, FastAnalysisResult
from scripts.fast_analysis_report_adapter import build_fast_report_content
from scripts.build_boc_bid_intelligence_preview_pdf import build
import pypdf

PHOENIX_BID_ID = 1083
OUT_PDF_NAME = "PHOENIX_RFP2026_09_28_BID_INTELLIGENCE_PREVIEW_CLIENT_READY_V3.pdf"
BI_PATH = Path("evaluation/buyer_intelligence/ldb_buyer_intelligence.json")


def main():
    print("=" * 60)
    print("PHOENIX CLIENT-READY ACCEPTANCE: GENUINE END-TO-END RUN")
    print("=" * 60)

    # 1. Obtain API Key
    api_key = config.get_api_key()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")
    print(f"[OK] Anthropic API key verified (prefix: {api_key[:10]}...)")

    # 2. Download source documents for Bid 1083
    print(f"\nDownloading source documents for Bid {PHOENIX_BID_ID} from Supabase...")
    doc_records = db.get_documents(PHOENIX_BID_ID)
    print(f"Found {len(doc_records)} documents attached to bid {PHOENIX_BID_ID}:")
    for d in doc_records:
        print(f"  - {d['name']} ({d.get('doc_type', 'unspecified')})")

    # Filter to the 3 Phoenix procurement documents
    target_docs = [
        d for d in doc_records
        if any(k in d["name"] for k in ("Appendix_A", "Appendix_B", "Coaching_and_Leadership_Development_Services"))
    ]
    if len(target_docs) != 3:
        raise RuntimeError(f"Expected 3 Phoenix documents, found {len(target_docs)}")

    raw_documents: list[tuple[str, str]] = []
    for d in target_docs:
        print(f"Extracting {d['name']}...")
        storage_path = d.get("storage_path") or d.get("file_path")
        file_bytes = db.download_file(storage_path)
        if not file_bytes:
            raise RuntimeError(f"Failed to download {d['name']}")
        t0 = time.perf_counter()
        doc_text, meta = extract_document_with_metadata(file_bytes, d["name"])
        dt = time.perf_counter() - t0
        print(f"  Extracted {len(doc_text)} chars in {dt:.3f}s (type: {meta.get('detected_type')})")
        raw_documents.append((d["name"], doc_text))

    # 3. Run Live Fast Analysis Corpus
    print("\nExecuting live run_fast_analysis_corpus...")
    t_start = time.perf_counter()
    result: FastAnalysisResult = run_fast_analysis_corpus(
        raw_documents,
        api_key=api_key,
        max_document_concurrency=2,
    )
    t_run = time.perf_counter() - t_start
    print(f"\n[OK] Fast Analysis finished in {t_run:.2f}s (reported wall: {result.wall_seconds:.2f}s)")

    # 4. Attach researched Buyer Intelligence payload
    if not BI_PATH.exists():
        raise RuntimeError(f"Buyer intelligence payload not found at {BI_PATH}")
    with open(BI_PATH, "r", encoding="utf-8") as f:
        bi_payload = json.load(f)
    result.buyer_intelligence = bi_payload
    print(f"[OK] Attached generic Buyer Intelligence for: {bi_payload.get('buyer_identity')}")

    # 5. Assemble report content
    print("\nBuilding report content via build_fast_report_content...")
    content = build_fast_report_content(result)

    # 6. Render PDF
    out_path = Path(OUT_PDF_NAME)
    print(f"Rendering PDF to {out_path}...")
    build(content, str(out_path))

    reader = pypdf.PdfReader(str(out_path))
    num_pages = len(reader.pages)
    file_size = out_path.stat().st_size
    print(f"\n[OK] PDF rendered successfully:")
    print(f"  Path: {out_path.resolve()}")
    print(f"  Pages: {num_pages} (target budget: 12-13 pages)")
    print(f"  File size: {file_size:,} bytes")

    # 7. Telemetry & Summary
    print("\nTelemetry Breakdown:")
    total_calls = len(result.telemetry)
    total_in = sum((t.get("input_tokens") or 0) for t in result.telemetry)
    total_out = sum((t.get("output_tokens") or 0) for t in result.telemetry)
    print(f"  Model calls: {total_calls}")
    print(f"  Input tokens: {total_in:,}")
    print(f"  Output tokens: {total_out:,}")
    for i, t in enumerate(result.telemetry, 1):
        print(f"    Call {i}: {t.get('task')} on {t.get('doc')} -> in: {t.get('input_tokens')}, out: {t.get('output_tokens')}, latency: {t.get('latency_ms')}ms")

    print("\nSection Validation:")
    print(f"  Buyer Intelligence available: {getattr(content, 'BUYER_INTEL_AVAILABLE', False)}")
    print(f"  Verified buyer facts: {len(getattr(content, 'VERIFIED_BUYER_FACTS', []))}")
    print(f"  Relevant signals: {len(getattr(content, 'RELEVANT_BUYER_SIGNALS', []))}")
    print(f"  Bid relevance items: {len(getattr(content, 'BID_RELEVANCE_ITEMS', []))}")
    print(f"  External sources: {len(getattr(content, 'EXTERNAL_BUYER_SOURCES', []))}")
    print(f"  Eval weights categories: {list(content.EVAL_WEIGHTS.keys())}")
    for k, v in content.EVAL_WEIGHTS.items():
        print(f"    {k}: {len(v)} items")
    print(f"  Commercial points: {len(content.COMMERCIAL_POINTS)} items")
    comm_dict = dict(content.COMMERCIAL_POINTS)
    print(f"    Governing Law: {comm_dict.get('Governing Law')}")
    print(f"  Attention points: {len(content.ATTENTION_POINTS)} items")
    print(f"  Submission structure: {content.PROCURED_STRUCTURE}")

    # Save structured run metrics to JSON for reference
    metrics = {
        "out_pdf": str(out_path.resolve()),
        "num_pages": num_pages,
        "file_size": file_size,
        "wall_seconds": t_run,
        "model_calls": total_calls,
        "input_tokens": total_in,
        "output_tokens": total_out,
        "eval_categories": list(content.EVAL_WEIGHTS.keys()),
        "governing_law": comm_dict.get("Governing Law"),
        "procured_structure": content.PROCURED_STRUCTURE,
    }
    with open("phoenix_client_ready_run_metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    return num_pages, t_run, total_calls


if __name__ == "__main__":
    main()
