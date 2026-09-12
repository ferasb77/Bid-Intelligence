"""Production commissioning run — full chain, corrected Bank of Canada corpus.

This is a commissioning harness, not a fixture or a replay. It calls only
existing production entry points against the real, already-acquired 16-file
corrected corpus and the real, already-acquired external Buyer Evidence
documents. It performs no fabrication: every manifest value below is either
read from an existing manifest already committed to this evaluation
directory (corrected_corpus_manifest.json, acquisition_manifest.json) or
computed directly from the real files on disk.

Run stage-by-stage. Each stage prints PASS/FAIL and, on the first failure,
the harness stops immediately (per the commissioning protocol) rather than
continuing with fallback logic or synthetic substitutes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
CORPUS = OUT / "corrected_procurement_corpus"
RESULTS = OUT / "full_chain_commissioning"
sys.path.insert(0, str(ROOT))

from extractor import extract_document_with_metadata


def dump(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def digest_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


class BoundaryFailure(Exception):
    def __init__(self, boundary: str, exc: BaseException):
        self.boundary = boundary
        self.exc = exc
        super().__init__(str(exc))


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    log: list[dict] = []
    last_ok = None

    def record(boundary: str, ok: bool, detail: dict) -> None:
        log.append({
            "boundary": boundary,
            "status": "PASS" if ok else "FAIL",
            "detail": detail,
            "at": datetime.now(timezone.utc).isoformat(),
        })

    try:
        # ---- Boundary 1: Procurement Corpus (real files on disk) ----
        paths = sorted(p for p in CORPUS.rglob("*") if p.is_file())
        raw_files = [(p.relative_to(CORPUS).as_posix(), p.read_bytes()) for p in paths]
        corpus_manifest = json.loads((OUT / "corrected_corpus_manifest.json").read_text(encoding="utf-8"))
        declared_paths = {f["path"] for f in corpus_manifest["files"]}
        on_disk_paths = {name for name, _ in raw_files}
        if declared_paths != on_disk_paths:
            raise BoundaryFailure(
                "Procurement Corpus",
                RuntimeError(f"manifest/disk mismatch: manifest-only={declared_paths - on_disk_paths} "
                              f"disk-only={on_disk_paths - declared_paths}"),
            )
        if len(raw_files) != 16:
            raise BoundaryFailure("Procurement Corpus", RuntimeError(f"expected 16 files, found {len(raw_files)}"))
        last_ok = "Procurement Corpus"
        record("Procurement Corpus", True, {"file_count": len(raw_files), "manifest": "corrected_corpus_manifest.json"})
        print(f"PASS  Procurement Corpus  files={len(raw_files)}", flush=True)

        # ---- preprocess (existing production entry point) ----
        # Note: unpack_procurement_package() is not used here — it reduces every
        # entry to os.path.basename(), which is correct for flat/ZIP uploads but
        # would collapse this corpus's real "OriginalRevision/"/"Amendment1/"
        # subdirectory identity and silently mismatch the corpus manifest's
        # declared paths. The already-validated Stage A-D harness
        # (run_corrected_evaluation.py) uses the same full relative paths
        # directly for this exact reason; this harness follows that precedent.
        unpacked = raw_files
        metadata = {"files": [], "doc_metadata": {}, "doc_texts": {}}
        for name, payload in unpacked:
            text, meta = extract_document_with_metadata(payload, name)
            metadata["files"].append(name)
            metadata["doc_metadata"][name] = meta
            metadata["doc_texts"][name] = text
        dump(RESULTS / "01_document_metadata.json", {
            "files": metadata["files"],
            "text_characters": {name: len(text) for name, text in metadata["doc_texts"].items()},
        })

        # ---- Boundary 2: Evidence (procurement_evidence_adapter.py) ----
        from procurement_evidence_adapter import adapt_procurement_corpus, ProcurementEvidenceAdapterError

        acquisition_manifest_full = json.loads((OUT / "acquisition_manifest.json").read_text(encoding="utf-8"))
        acquisition_manifest = {"retrieved_on": acquisition_manifest_full["retrieved_on"]}
        source_manifest = {
            "source_id": "source:bank-of-canada-procurement",
            "publisher_name": "Bank of Canada",
            "base_url": "https://www.bankofcanada.ca/",
        }
        try:
            snapshot = adapt_procurement_corpus(
                unpacked, metadata, corpus_manifest, acquisition_manifest, source_manifest,
            )
        except ProcurementEvidenceAdapterError as exc:
            raise BoundaryFailure("Evidence", exc)
        dump(RESULTS / "02_evidence_snapshot.json", snapshot.to_dict())
        last_ok = "Evidence"
        record("Evidence", True, {"snapshot_id": snapshot.snapshot_id, "object_count": len(snapshot.objects)})
        print(f"PASS  Evidence  objects={len(snapshot.objects)} snapshot_id={snapshot.snapshot_id}", flush=True)

        # ---- Boundary 3: Evidence Publication ----
        from evidence_publication import publish_evidence, validate_evidence_publication, EvidencePublicationError

        try:
            publication = publish_evidence(snapshot)
            publication = validate_evidence_publication(publication)
        except EvidencePublicationError as exc:
            raise BoundaryFailure("Evidence Publication", exc)
        dump(RESULTS / "03_evidence_publication.json", publication.to_dict() if hasattr(publication, "to_dict") else publication)
        last_ok = "Evidence Publication"
        record("Evidence Publication", True, {"publication_id": getattr(publication, "publication_id", None)})
        print("PASS  Evidence Publication", flush=True)

        # ---- Boundary 4: Stage A (fresh live extraction, no reuse/replay) ----
        import config as app_config
        from extractor import extract_document_facts, normalize_package_facts, reconcile_package_facts, synthesize_bid_brief

        api_key = app_config.get_api_key()
        if not api_key:
            raise BoundaryFailure("Stage A", RuntimeError("ANTHROPIC_API_KEY is unavailable"))

        document_facts = []
        stage_a_dir = RESULTS / "stage_a_documents"
        stage_a_dir.mkdir(exist_ok=True)
        for index, (name, _) in enumerate(unpacked, 1):
            print(f"STAGE_A {index}/{len(unpacked)} {name}", flush=True)
            facts = extract_document_facts(metadata["doc_texts"][name], name, api_key)
            entry = {"file": name, "facts": facts}
            dump(stage_a_dir / f"{index:02d}.json", entry)
            document_facts.append(entry)
        dump(RESULTS / "04_stage_a_document_facts.json", document_facts)
        last_ok = "Stage A"
        record("Stage A", True, {"documents": len(document_facts)})
        print(f"PASS  Stage A  documents={len(document_facts)}", flush=True)

        # ---- Boundary 5: Stage B ----
        normalized = normalize_package_facts([e["facts"] for e in document_facts], metadata)
        dump(RESULTS / "05_stage_b_normalized_facts.json", normalized)
        last_ok = "Stage B"
        record("Stage B", True, {"requirements": len(normalized.get("requirements", []))})
        print(f"PASS  Stage B  requirements={len(normalized.get('requirements', []))}", flush=True)

        # ---- Boundary 6: Stage C ----
        conflicts = reconcile_package_facts(normalized, metadata["files"])
        dump(RESULTS / "06_stage_c_conflicts.json", conflicts)
        last_ok = "Stage C"
        record("Stage C", True, {"conflicts": len(conflicts)})
        print(f"PASS  Stage C  conflicts={len(conflicts)}", flush=True)

        # ---- Boundary 7: Stage D ----
        from stage_d_projection import ProjectionValidationError
        from extractor import StageDContextTooLargeError
        try:
            synthesis = synthesize_bid_brief(normalized, conflicts, api_key)
        except (ProjectionValidationError, StageDContextTooLargeError) as exc:
            raise BoundaryFailure("Stage D", exc)
        dump(RESULTS / "07_stage_d_bid_brief.json", synthesis)
        last_ok = "Stage D"
        record("Stage D", True, {})
        print("PASS  Stage D", flush=True)

        dump(RESULTS / "complete_pipeline_result.json", {
            "normalized_facts": normalized, "conflicts": conflicts, "synthesis": synthesis,
        })
        print("STOPPING HERE FOR THIS PASS — Canonical Opportunity onward is the next boundary.", flush=True)
        return 0

    except BoundaryFailure as bf:
        record(bf.boundary, False, {
            "exception_type": type(bf.exc).__name__,
            "exception_message": str(bf.exc),
            "traceback": "".join(traceback.format_exception(type(bf.exc), bf.exc, bf.exc.__traceback__)),
        })
        dump(RESULTS / "boundary_log.json", {"last_successful_boundary": last_ok, "entries": log})
        print(f"FAIL  {bf.boundary}: {type(bf.exc).__name__}: {bf.exc}", flush=True)
        return 1
    except Exception as exc:  # unexpected — still capture, do not mask
        record("UNEXPECTED", False, {
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "traceback": traceback.format_exc(),
        })
        dump(RESULTS / "boundary_log.json", {"last_successful_boundary": last_ok, "entries": log})
        print(f"FAIL  UNEXPECTED: {type(exc).__name__}: {exc}", flush=True)
        return 1
    finally:
        dump(RESULTS / "boundary_log.json", {"last_successful_boundary": last_ok, "entries": log})


if __name__ == "__main__":
    sys.exit(main())
