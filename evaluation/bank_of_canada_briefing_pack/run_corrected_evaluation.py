"""Evaluation-only Bank of Canada RFP 2026-026 regeneration.

This runner writes evidence and pipeline artifacts under the evaluation folder.
It deliberately does not persist to the application database or alter fixtures.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
CORPUS = OUT / "corrected_procurement_corpus"
RESULTS = OUT / "corrected_pipeline"
sys.path.insert(0, str(ROOT))

import config
from extractor import (
    build_stage_d_context,
    extract_document_facts,
    extract_document_with_metadata,
    normalize_package_facts,
    reconcile_package_facts,
    synthesize_bid_brief,
)


MASTER_NAME = "RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf"
MODEL = "claude-haiku-4-5-20251001"


def dump(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def digest_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def git_value(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def source_refs(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "source_refs" and isinstance(child, list):
                yield from child
            yield from source_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from source_refs(child)


def main() -> None:
    api_key = config.get_api_key()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is unavailable")
    RESULTS.mkdir(parents=True, exist_ok=True)

    paths = sorted(p for p in CORPUS.rglob("*") if p.is_file())
    raw_files = [(p.relative_to(CORPUS).as_posix(), p.read_bytes()) for p in paths]
    if len(raw_files) != 16 or MASTER_NAME not in {name for name, _ in raw_files}:
        raise RuntimeError("Corrected corpus must contain the master RFP and 15 retained documents")

    started = datetime.now(timezone.utc).isoformat()
    t_total = time.monotonic()
    print(f"CORPUS files={len(raw_files)} aggregate={digest_bytes(''.join(digest_bytes(b) for _, b in raw_files).encode())}", flush=True)

    t0 = time.monotonic()
    metadata = {"files": [], "doc_metadata": {}, "doc_texts": {}}
    for name, payload in raw_files:
        text, meta = extract_document_with_metadata(payload, name)
        metadata["files"].append(name)
        metadata["doc_metadata"][name] = meta
        metadata["doc_texts"][name] = text
        print(f"PARSED {name} chars={len(text)}", flush=True)
    parse_seconds = time.monotonic() - t0
    dump(RESULTS / "document_metadata.json", {
        "files": metadata["files"],
        "doc_metadata": metadata["doc_metadata"],
        "text_sha256": {name: digest_bytes(text.encode("utf-8")) for name, text in metadata["doc_texts"].items()},
        "text_characters": {name: len(text) for name, text in metadata["doc_texts"].items()},
    })

    t0 = time.monotonic()
    document_facts = []
    stage_a_dir = RESULTS / "stage_a_documents"
    stage_a_dir.mkdir(exist_ok=True)
    resume_stage_a = os.environ.get("BID_EVAL_REUSE_STAGE_A") == "1"
    for index, (name, _) in enumerate(raw_files, 1):
        saved = stage_a_dir / f"{index:02d}.json"
        if resume_stage_a and saved.exists():
            entry = json.loads(saved.read_text(encoding="utf-8"))
            if entry.get("file") != name:
                raise RuntimeError(f"Stage A checkpoint identity mismatch at {index}")
            print(f"STAGE_A_REUSED {index}/{len(raw_files)} {name}", flush=True)
        else:
            print(f"STAGE_A {index}/{len(raw_files)} {name}", flush=True)
            facts = extract_document_facts(metadata["doc_texts"][name], name, api_key)
            entry = {"file": name, "facts": facts}
            dump(saved, entry)
        document_facts.append(entry)
    stage_a_seconds = time.monotonic() - t0
    dump(RESULTS / "stage_a_document_facts.json", document_facts)

    t0 = time.monotonic()
    normalized = normalize_package_facts([entry["facts"] for entry in document_facts], metadata)
    stage_b_seconds = time.monotonic() - t0
    dump(RESULTS / "stage_b_normalized_facts.json", normalized)
    print(f"STAGE_B requirements={len(normalized.get('requirements', []))}", flush=True)

    t0 = time.monotonic()
    conflicts = reconcile_package_facts(normalized, metadata["files"])
    stage_c_seconds = time.monotonic() - t0
    dump(RESULTS / "stage_c_conflicts.json", conflicts)
    print(f"STAGE_C conflicts={len(conflicts)}", flush=True)

    context = build_stage_d_context(normalized, conflicts)
    context_json = json.dumps(context, ensure_ascii=False, sort_keys=True, default=str)
    master_refs = [r for r in source_refs(normalized) if isinstance(r, dict) and r.get("source_doc") == MASTER_NAME]
    context_measurements = {
        "serialized_characters": len(context_json),
        "measurement_scope": "diagnostic context including sidecar; not the guarded provider request",
        "master_source_reference_occurrences_in_normalized_facts": len(master_refs),
        "master_filename_occurrences_in_stage_d_context": context_json.count(MASTER_NAME),
    }
    dump(RESULTS / "diagnostic_context_with_sidecar_measurements.json", context_measurements)
    print(f"STAGE_D_CONTEXT chars={len(context_json)} master_refs={len(master_refs)}", flush=True)

    t0 = time.monotonic()
    synthesis = synthesize_bid_brief(normalized, conflicts, api_key)
    stage_d_seconds = time.monotonic() - t0
    dump(RESULTS / "stage_d_bid_brief.json", synthesis)
    print("STAGE_D complete", flush=True)

    timings = {
        "parsing": parse_seconds,
        "stage_a": stage_a_seconds,
        "stage_b": stage_b_seconds,
        "stage_c": stage_c_seconds,
        "stage_d": stage_d_seconds,
        "total": time.monotonic() - t_total,
    }
    requirements = normalized.get("requirements", [])
    refs = list(source_refs(normalized))
    stats = {
        "source_files": len(raw_files),
        "requirements": len(requirements),
        "requirement_categories": {
            category: sum(1 for req in requirements if req.get("category") == category)
            for category in ("Mandatory", "Rated", "Financial", "Supporting")
        },
        "source_reference_occurrences": len(refs),
        "verified_source_reference_occurrences": sum(1 for ref in refs if isinstance(ref, dict) and ref.get("verified") is True),
        "unverified_source_reference_occurrences": sum(1 for ref in refs if isinstance(ref, dict) and ref.get("verified") is not True),
        "conflicts": len(conflicts),
        "master_rfp": {
            "filename": MASTER_NAME,
            "sha256": digest_bytes(dict(raw_files)[MASTER_NAME]),
            "stage_a_facts_present": any(x["file"] == MASTER_NAME and bool(x["facts"]) for x in document_facts),
            "normalized_source_reference_occurrences": len(master_refs),
            "stage_d_context_filename_occurrences": context_json.count(MASTER_NAME),
        },
    }
    execution = {
        "evaluation_only": True,
        "started_at": started,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "branch": git_value("branch", "--show-current"),
        "commit_sha": git_value("rev-parse", "HEAD"),
        "model": MODEL,
        "calls": {
            "stage_a_live": 0 if resume_stage_a else len(raw_files),
            "stage_a_reused_from_same_evaluation_run": len(raw_files) if resume_stage_a else 0,
            "stage_d": 1,
            "total_live_this_invocation": 1 if resume_stage_a else len(raw_files) + 1,
        },
        "timings_seconds": timings,
        "statistics": stats,
        "stage_d_context": context_measurements,
    }
    dump(RESULTS / "execution_summary.json", execution)
    dump(RESULTS / "complete_pipeline_result.json", {
        "execution": execution,
        "normalized_facts": normalized,
        "conflicts": conflicts,
        "synthesis": synthesis,
    })
    print(json.dumps(execution, indent=2), flush=True)


if __name__ == "__main__":
    main()
