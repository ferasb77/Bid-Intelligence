"""Fresh Phase 1 commissioning run for the authoritative 16-document Bank of
Canada RFP 2026-026 corpus (the master RFP restored), using the real
production ingestion/extraction path only.

Phase 1 = corpus discovery -> document parsing/preprocessing ->
Procurement Evidence Adapter -> Evidence Publication -> Stage A (per-document
fact extraction). This script stops at the end of Stage A. It does not call
normalize_package_facts (Stage B), reconcile_package_facts (Stage C), or
synthesize_bid_brief (Stage D).

No fixtures. No cached Stage A/B/C/D reuse from any prior run (this repo's
15-document corpus, the historical `corrected_pipeline/` evaluation-harness
artifacts, or any external checkpoint). Every one of the 16 documents is
parsed and sent to the live Anthropic API fresh in this process. A brand
new, uniquely-named CHECKPOINT_ROOT is used; `resume_procurement_checkpoint`
and `load_verified_checkpoint` are never called.
"""
import hashlib, json, secrets, subprocess, sys, time, traceback
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RUN_ID = f"phase1-boc-2026-026-corrected16-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
DUMP_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase1_commissioning" / RUN_ID
STAGE_A_DIR = DUMP_DIR / "stage_a_documents"
DUMP_DIR.mkdir(parents=True, exist_ok=False)
STAGE_A_DIR.mkdir(parents=True, exist_ok=False)

import os
os.environ["CHECKPOINT_MODE"] = "off"  # This script writes its own fresh, uniquely-named dumps directly.

records = []
started = time.monotonic()


def save(name, value):
    (DUMP_DIR / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n",
                                  encoding="utf-8")


def emit(boundary, status, t0, **extra):
    record = {"boundary": boundary, "status": status, "elapsed_seconds": round(time.monotonic() - t0, 3), **extra}
    records.append(record)
    save("boundaries.json", records)
    print(json.dumps(record, sort_keys=True), flush=True)


from config import get_api_key
from extractor import extract_document_facts, extract_document_with_metadata
from procurement_evidence_adapter import adapt_procurement_corpus, ProcurementEvidenceAdapterError
from evidence_publication import publish_evidence, validate_evidence_publication, EvidencePublicationError
from evidence import EvidenceArtifact, EvidenceExtract, EvidenceOccurrence, EvidenceSource

CORPUS = ROOT / "evaluation/bank_of_canada_briefing_pack/corrected_procurement_corpus"
MASTER_RFP_FILENAME = "RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf"
MASTER_RFP_SHA256 = "78d96ef927e19fa431c187f9287777b755bd80603f42734c69e0c2603f035ee4"
SOLICITATION_NUMBER = "2026-026"

SOURCE = {"source_id": "source:bank-of-canada-procurement", "publisher_name": "Bank of Canada",
          "base_url": "https://www.bankofcanada.ca/"}
ACQ = {"retrieved_on": "2026-09-08"}
CORPUS_ID = "bank-of-canada-rfp-2026-026-corrected-16doc"


def role_for(path: str) -> str:
    if path == MASTER_RFP_FILENAME:
        return "MASTER_RFP"
    if path == "abstract.pdf":
        return "NOTICE_AND_DOCUMENT_INVENTORY"
    if path.startswith("Amendment"):
        return "AMENDMENT"
    return "PROCUREMENT_ATTACHMENT"


current = "Corpus Gate"
t = time.monotonic()
try:
    paths = sorted(p for p in CORPUS.rglob("*") if p.is_file())
    package = [(p.relative_to(CORPUS).as_posix(), p.read_bytes()) for p in paths]
    print(f"Corpus path: {CORPUS}")
    print(f"Files discovered ({len(package)}):")
    digests = {}
    for name, payload in package:
        digests[name] = hashlib.sha256(payload).hexdigest()
        print(f"  - {name}  ({len(payload)} bytes, sha256={digests[name]})")

    if len(package) != 16:
        raise RuntimeError(f"CORPUS GATE: FAIL — expected 16 source documents, found {len(package)}")
    if len(set(digests.values())) != 16:
        raise RuntimeError("CORPUS GATE: FAIL — duplicate content digest among discovered files "
                            "(a document would be double-counted)")
    if MASTER_RFP_FILENAME not in digests:
        raise RuntimeError(f"CORPUS GATE: FAIL — master RFP filename not found: {MASTER_RFP_FILENAME!r}")
    if digests[MASTER_RFP_FILENAME] != MASTER_RFP_SHA256:
        raise RuntimeError("CORPUS GATE: FAIL — master RFP content digest does not match the authoritative "
                            f"identity ({digests[MASTER_RFP_FILENAME]} != {MASTER_RFP_SHA256})")
    if SOLICITATION_NUMBER not in MASTER_RFP_FILENAME and not any(
            SOLICITATION_NUMBER in name for name in digests):
        raise RuntimeError(f"CORPUS GATE: FAIL — solicitation number {SOLICITATION_NUMBER!r} not found "
                            "in any discovered filename")

    manifest = {
        "corpus_id": CORPUS_ID, "language": "English",
        "files": [{"path": name, "bytes": len(payload), "sha256": digests[name], "role": role_for(name)}
                  for name, payload in package],
    }
    save("phase1_source_manifest.json", manifest)

    print(f"Master RFP identified: {MASTER_RFP_FILENAME}")
    print(f"Master RFP SHA-256: {digests[MASTER_RFP_FILENAME]}")
    print(f"Master RFP role assigned by production adapter role map: {role_for(MASTER_RFP_FILENAME)}")
    print(f"Solicitation number confirmed present in corpus filenames: {SOLICITATION_NUMBER}")
    print("No Outlook-cache duplicate occurrence is present in this directory listing "
          "(verified: exactly 16 unique content digests among 16 discovered files).")
    print(f"Master RFP will be passed through adapt_procurement_corpus()/extract_document_facts() "
          f"identically to the other {len(package) - 1} files: same role-map dispatch, same "
          f"extract_document_with_metadata() call, same extract_document_facts() call, no "
          f"Bank-of-Canada-specific or master-RFP-specific branch exists in the production code.")
    print("CORPUS GATE: PASS — 16/16 authoritative source documents present.")
    emit(current, "PASS", t, objects=len(package), master_rfp_sha256=digests[MASTER_RFP_FILENAME])

    current = "Fresh Run Identity"
    t = time.monotonic()
    git_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    git_dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
    run_metadata = {
        "run_id": RUN_ID,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit or "unavailable",
        "git_working_tree_dirty": bool(git_dirty.strip()),
        "git_working_tree_changed_files": len(git_dirty.strip().splitlines()) if git_dirty.strip() else 0,
        "production_entry_point": "scripts/commission_phase1_bank_of_canada.py "
                                   "(direct calls to extract_document_with_metadata, "
                                   "adapt_procurement_corpus, publish_evidence, "
                                   "validate_evidence_publication, extract_document_facts "
                                   "-- the same functions scripts/commission_original_bank_of_canada.py "
                                   "uses for its own Procurement Corpus through Stage A boundaries)",
        "stage_a_model": "claude-haiku-4-5-20251001",
        "corpus_path": str(CORPUS.relative_to(ROOT)),
        "corpus_id": CORPUS_ID,
        "document_count": 16,
        "acquisition_retrieved_on": ACQ["retrieved_on"],
        "cache_bypass_measures": [
            "CHECKPOINT_MODE=off: this script never invokes the repository's opt-in "
            "checkpoint/resume system (stage_d_checkpoints.py); resume_procurement_checkpoint() "
            "and load_verified_checkpoint() are never called, so no prior checkpoint directory "
            "can be replayed into this run.",
            "A brand new, timestamp+random-suffixed output directory "
            f"({DUMP_DIR.relative_to(ROOT)}) is used; nothing is read from "
            "evaluation/bank_of_canada_briefing_pack/corrected_pipeline/ (the historical "
            "evaluation-harness Stage A-D outputs) or from tests/fixtures/local/"
            "bank_of_canada_2026_026 (the superseded 15-document corpus).",
            "extract_document_facts()/_extract_chunk_facts() were read in extractor.py before this "
            "run: they call client.messages.create(...) unconditionally on every invocation with no "
            "memoization, content-hash lookup, or response cache in the code path -- temperature=0.0 "
            "makes the model deterministic given identical input, but every call in this run is a "
            "genuine live request, not a cache hit.",
        ],
        "api_key_present": True,
    }
    save("run_metadata.json", run_metadata)
    emit(current, "PASS", t, run_id=RUN_ID)

    current = "Document Parsing"
    t = time.monotonic()
    metadata = {"files": [], "doc_metadata": {}, "doc_texts": {}}
    parsing_report = []
    for name, payload in package:
        text, meta = extract_document_with_metadata(payload, name)
        metadata["files"].append(name)
        metadata["doc_metadata"][name] = meta
        metadata["doc_texts"][name] = text
        parsing_report.append({
            "path": name, "role": role_for(name), "bytes": len(payload),
            "sha256": digests[name],
            "page_count": meta.get("page_count"),
            "sections": len(meta.get("sections", [])) if "sections" in meta else None,
            "tables_count": meta.get("tables_count"),
            "sheets": list(meta.get("sheets", {}).keys()) if isinstance(meta.get("sheets"), dict) else meta.get("sheets"),
            "extracted_character_count": len(text),
            "text_excerpt_head": text[:300],
            "text_excerpt_tail": text[-300:],
        })
    save("phase1_document_parsing.json", parsing_report)
    (DUMP_DIR / "master_rfp_extracted_text.txt").write_text(
        metadata["doc_texts"][MASTER_RFP_FILENAME], encoding="utf-8")
    emit(current, "PASS", t, objects=len(package),
         master_rfp_characters=len(metadata["doc_texts"][MASTER_RFP_FILENAME]))

    current = "Procurement Evidence Adapter"
    t = time.monotonic()
    evidence_snapshot = adapt_procurement_corpus(package, metadata, manifest, ACQ, SOURCE)
    save("phase1_evidence_snapshot.json", evidence_snapshot.to_dict())
    by_class = {}
    for obj in evidence_snapshot.objects:
        by_class.setdefault(obj.object_class.value, 0)
        by_class[obj.object_class.value] += 1
    emit(current, "PASS", t, total_objects=len(evidence_snapshot.objects), objects_by_class=by_class,
         snapshot_id=evidence_snapshot.snapshot_id)

    current = "Evidence Publication"
    t = time.monotonic()
    evidence_publication = validate_evidence_publication(publish_evidence(evidence_snapshot))
    save("phase1_evidence_publication.json", evidence_publication.to_dict())
    emit(current, "PASS", t, objects=len(evidence_publication.snapshot.objects),
         references=len(evidence_publication.references), publication_id=evidence_publication.publication_id)

    current = "Stage A"
    t = time.monotonic()
    key = get_api_key()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is unavailable")
    document_facts = []
    stage_a_report = []
    for i, (name, _) in enumerate(package, 1):
        print(json.dumps({"progress": "Stage A", "document": i, "of": len(package), "name": name}), flush=True)
        facts = extract_document_facts(metadata["doc_texts"][name], name, key)
        document_facts.append(facts)
        safe_name = "".join(c if c.isalnum() or c in "-._" else "_" for c in name)
        (STAGE_A_DIR / f"{i:02d}-{safe_name}.json").write_text(
            json.dumps(facts, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")
        record_counts = {key_name: len(facts.get(key_name, []))
                          for key_name in ("requirements", "dates", "evaluation_criteria",
                                           "submission_rules", "deliverables", "commercial_clauses",
                                           "typed_observations")}
        stage_a_report.append({
            "sequence": i, "path": name, "role": role_for(name),
            "parse_status": facts.get("_parse_status"),
            "extraction_diagnostic": facts.get("_extraction_diagnostic"),
            "record_counts": record_counts,
            "total_records": sum(record_counts.values()),
        })
    save("phase1_stage_a_document_facts.json", document_facts)
    save("phase1_stage_a_report.json", stage_a_report)
    total_records = sum(item["total_records"] for item in stage_a_report)
    warnings = [item for item in stage_a_report
                if item["extraction_diagnostic"] and item["extraction_diagnostic"].get("status") != "VERIFIED_ADEQUATE"]
    zero_output = [item for item in stage_a_report if item["total_records"] == 0]
    save("phase1_validation_anomalies.json", {"warnings": warnings, "zero_output_documents": zero_output})
    emit(current, "PASS", t, documents=len(document_facts), total_records=total_records,
         documents_with_warnings=len(warnings), zero_output_documents=len(zero_output))

except (ProcurementEvidenceAdapterError, EvidencePublicationError, RuntimeError) as exc:
    emit(current, "FAIL", t, exception_type=type(exc).__name__, exception=str(exc), traceback=traceback.format_exc())
    print(f"PHASE 1: FAIL at boundary '{current}': {exc}")
    sys.exit(1)
except Exception as exc:
    emit(current, "FAIL", t, exception_type=type(exc).__name__, exception=str(exc), traceback=traceback.format_exc())
    raise

total_elapsed = round(time.monotonic() - started, 3)
save("completion.json", {"status": "PASS", "elapsed_seconds": total_elapsed, "run_id": RUN_ID})
print(f"PHASE 1: PASS. Elapsed: {total_elapsed}s. Dumps at: {DUMP_DIR.relative_to(ROOT)}")
