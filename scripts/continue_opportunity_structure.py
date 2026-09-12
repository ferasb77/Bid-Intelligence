"""Continue commissioning past Canonical Opportunity Publication: Opportunity
Structure and Opportunity Structure Publication, using real production
Evidence, Evidence Publication, and Stage B/C outputs already on disk from a
completed commission_original_bank_of_canada.py run. No fixtures, no
replay, no synthetic bindings -- record bindings are derived by
opportunity_structure_binding.build_structure_bindings from the real
Evidence Snapshot and Evidence Publication reconstructed for the identical
corpus, exactly as continue_canonical_publication.py already does for
Canonical Opportunity.
"""
import json, sys, time, traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--input-dir", required=True, type=Path,
                     help="Directory containing stage-c-normalized-facts.json")
parser.add_argument("--output", required=True, type=Path)
parser.add_argument("--corpus", choices=["corrected", "original"], default="original")
args = parser.parse_args()

OUT = args.output.resolve()
if OUT == ROOT or ROOT in OUT.parents:
    raise ValueError("Commissioning artifacts must remain outside the repository")
OUT.mkdir(parents=True, exist_ok=True)


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n",
                             encoding="utf-8")


from extractor import extract_document_with_metadata
from procurement_evidence_adapter import adapt_procurement_corpus
from evidence_publication import publish_evidence, validate_evidence_publication
from opportunity_structure import build_opportunity_structure
from opportunity_structure_binding import build_structure_bindings, StructureBindingError
from opportunity_structure_publication import (
    publish_opportunity_structure, validate_opportunity_structure_publication,
    OpportunityStructurePublicationError,
)

import hashlib

SOURCE = {"source_id": "source:bank-of-canada-procurement", "publisher_name": "Bank of Canada",
          "base_url": "https://www.bankofcanada.ca/"}

if args.corpus == "corrected":
    CORPUS = ROOT / "evaluation/bank_of_canada_briefing_pack/corrected_procurement_corpus"
    MANIFEST = json.loads((ROOT / "evaluation/bank_of_canada_briefing_pack/corrected_corpus_manifest.json").read_text(encoding="utf-8"))
    ACQ_FULL = json.loads((ROOT / "evaluation/bank_of_canada_briefing_pack/acquisition_manifest.json").read_text(encoding="utf-8"))
    ACQ = {"retrieved_on": ACQ_FULL["retrieved_on"]}
    EXPECTED_COUNT = 16
else:
    CORPUS = ROOT / "tests/fixtures/local/bank_of_canada_2026_026"
    ACQ = {"retrieved_on": "2026-09-01"}
    EXPECTED_COUNT = 15

    def _role_for(path: str) -> str:
        if path == "abstract.pdf":
            return "NOTICE_AND_DOCUMENT_INVENTORY"
        if path.startswith("Amendment"):
            return "AMENDMENT"
        return "PROCUREMENT_ATTACHMENT"

    _paths = sorted(p for p in CORPUS.rglob("*") if p.is_file())
    _package = [(p.relative_to(CORPUS).as_posix(), p.read_bytes()) for p in _paths]
    MANIFEST = {
        "corpus_id": "bank-of-canada-rfp-2026-026-original-15doc",
        "language": "English",
        "files": [
            {"path": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "role": _role_for(name)}
            for name, payload in _package
        ],
    }

facts = json.loads((args.input_dir / "stage-c-normalized-facts.json").read_text(encoding="utf-8"))

records = []


def emit(boundary, status, t0, **extra):
    record = {"boundary": boundary, "status": status, "elapsed_seconds": round(time.monotonic() - t0, 3), **extra}
    records.append(record)
    save("boundaries.json", records)
    print(json.dumps(record, sort_keys=True), flush=True)


current = "Evidence (reconstruction for binding)"
t = time.monotonic()
try:
    paths = sorted(p for p in CORPUS.rglob("*") if p.is_file())
    package = [(p.relative_to(CORPUS).as_posix(), p.read_bytes()) for p in paths]
    if len(package) != EXPECTED_COUNT or {n for n, _ in package} != {x["path"] for x in MANIFEST["files"]}:
        raise RuntimeError("corpus identity mismatch")
    metadata = {"files": [], "doc_metadata": {}, "doc_texts": {}}
    for name, payload in package:
        text, meta = extract_document_with_metadata(payload, name)
        metadata["files"].append(name); metadata["doc_metadata"][name] = meta; metadata["doc_texts"][name] = text
    evidence_snapshot = adapt_procurement_corpus(package, metadata, MANIFEST, ACQ, SOURCE)
    emit(current, "PASS", t, objects=len(evidence_snapshot.objects), snapshot_id=evidence_snapshot.snapshot_id)

    current = "Evidence Publication (reconstruction for binding)"
    t = time.monotonic()
    evidence_publication = validate_evidence_publication(publish_evidence(evidence_snapshot))
    emit(current, "PASS", t, references=len(evidence_publication.references))

    current = "Opportunity Structure"
    t = time.monotonic()
    structure = build_opportunity_structure(facts, metadata)
    save("opportunity-structure.json", structure)
    emit(current, "PASS", t,
         records=len(structure["records"]), conflicts=len(structure["conflicts"]),
         collision_free=structure["integrity_diagnostics"]["collision_free"],
         collision_count=len(structure["integrity_diagnostics"]["collision_ids"]),
         input_digest=structure["input_digest"])

    current = "Opportunity Structure Record Binding Derivation"
    t = time.monotonic()
    bindings = build_structure_bindings(structure, evidence_snapshot, evidence_publication)
    save("structure_bindings_summary.json", {
        "count": len(bindings),
        "with_source": sum(1 for b in bindings if b.evidence_references or b.provenance_references),
        "without_source": sum(1 for b in bindings if not b.evidence_references and not b.provenance_references),
    })
    emit(current, "PASS", t, bindings=len(bindings))

    current = "Opportunity Structure Publication"
    t = time.monotonic()
    publication = publish_opportunity_structure(
        structure, opportunity_id="opportunity:bank-of-canada-rfp-2026-026-original",
        record_bindings=bindings)
    publication = validate_opportunity_structure_publication(publication)
    save("opportunity_structure_publication.json", publication.to_dict())
    emit(current, "PASS", t,
         objects=len(publication.snapshot.objects), references=len(publication.references))
except (StructureBindingError, OpportunityStructurePublicationError, RuntimeError) as exc:
    emit(current, "FAIL", t, exception_type=type(exc).__name__, exception=str(exc),
         traceback=traceback.format_exc())
    sys.exit(1)
except Exception as exc:
    emit(current, "FAIL", t, exception_type=type(exc).__name__, exception=str(exc),
         traceback=traceback.format_exc())
    raise
