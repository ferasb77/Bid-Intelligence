"""Continue commissioning past Opportunity Structure Publication: Opportunity
Intelligence and Opportunity Intelligence Publication, using real production
Evidence, Canonical Opportunity, and Opportunity Structure publications
already reconstructible from a completed commission_original_bank_of_canada.py
run. No fixtures, no replay, no synthetic bindings -- every
OpportunitySupportBinding.entity_reference is resolved against the real,
already-published governed references of the admitted publications; a
support entity with no real governed reference anywhere fails closed rather
than being invented.
"""
import json, sys, time, traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--input-dir", required=True, type=Path)
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
from canonical_observation_binding import build_observation_bindings, ObservationBindingError
from canonical_opportunity_publication import (
    identity_object_id, publish_canonical_opportunity,
    validate_canonical_opportunity_publication, CanonicalOpportunityPublicationError,
)
from opportunity_structure import build_opportunity_structure
from opportunity_structure_binding import build_structure_bindings, StructureBindingError
from opportunity_structure_publication import (
    publish_opportunity_structure, validate_opportunity_structure_publication,
    OpportunityStructurePublicationError,
)
from opportunity_intelligence import ANALYST_VERSION, analyze_opportunity
from opportunity_intelligence_publication import (
    OpportunityPublicationError, OpportunitySupportBinding,
    publish_opportunity_intelligence, validate_opportunity_intelligence_publication,
)
from executive_opportunity_understanding import (
    ExecutiveUnderstandingInput, build_executive_opportunity_understanding,
    validate_executive_opportunity_understanding,
)
from executive_opportunity_brief import (
    build_executive_opportunity_brief, render_executive_opportunity_brief,
    validate_executive_opportunity_brief,
)
from decision_intelligence import ContractValidationError
from governed_reference_resolution import create_resolution_context

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
conflicts = json.loads((args.input_dir / "stage-c-conflicts.json").read_text(encoding="utf-8"))
canonical = facts.get("_canonical_opportunity")

OPPORTUNITY_ID = "opportunity:bank-of-canada-rfp-2026-026-original"

records = []


def emit(boundary, status, t0, **extra):
    record = {"boundary": boundary, "status": status, "elapsed_seconds": round(time.monotonic() - t0, 3), **extra}
    records.append(record)
    save("boundaries.json", records)
    print(json.dumps(record, sort_keys=True), flush=True)


current = "Evidence (reconstruction)"
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
    evidence_publication = validate_evidence_publication(publish_evidence(evidence_snapshot))
    emit(current, "PASS", t, objects=len(evidence_snapshot.objects))

    current = "Canonical Opportunity Publication (reconstruction)"
    t = time.monotonic()
    if not isinstance(canonical, dict) or not canonical.get("input_digest"):
        raise RuntimeError("canonical opportunity absent from real Stage B/C output")
    observation_bindings = build_observation_bindings(canonical, evidence_snapshot, evidence_publication)
    canonical_publication = validate_canonical_opportunity_publication(publish_canonical_opportunity(
        canonical, opportunity_id=OPPORTUNITY_ID, observation_bindings=observation_bindings))
    emit(current, "PASS", t, objects=len(canonical_publication.snapshot.objects))

    current = "Opportunity Structure Publication (reconstruction)"
    t = time.monotonic()
    structure = build_opportunity_structure(facts, metadata)
    structure_bindings = build_structure_bindings(structure, evidence_snapshot, evidence_publication)
    structure_publication = validate_opportunity_structure_publication(publish_opportunity_structure(
        structure, opportunity_id=OPPORTUNITY_ID, record_bindings=structure_bindings))
    emit(current, "PASS", t, objects=len(structure_publication.snapshot.objects))

    current = "Opportunity Intelligence"
    t = time.monotonic()
    # The analysis's root CANONICAL_FACT support must resolve against the
    # real, governed Opportunity identity object Canonical Opportunity
    # Publication now publishes (canonical_opportunity_publication.py
    # 1.2.0) -- not an arbitrary human-chosen label. context_id is
    # therefore that object's own deterministic identity, not OPPORTUNITY_ID.
    analysis_context_id = identity_object_id(OPPORTUNITY_ID, canonical["input_digest"])
    analysis = analyze_opportunity(facts, conflicts, context_id=analysis_context_id)
    emit(current, "PASS", t,
         evidence_used=len(analysis.evidence_used), computed_facts=len(analysis.computed_facts),
         inferences=len(analysis.inferences), hypotheses=len(analysis.hypotheses))

    current = "Opportunity Intelligence Support Binding Derivation"
    t = time.monotonic()
    authoritative_context = create_resolution_context(
        context_id="opportunity-intelligence-context-" + OPPORTUNITY_ID,
        context_version="1.0.0",
        snapshots=(evidence_publication.snapshot, canonical_publication.snapshot, structure_publication.snapshot),
    )
    reference_by_object_id: dict[str, list] = {}
    for publication in (evidence_publication, canonical_publication, structure_publication):
        for reference in publication.references:
            reference_by_object_id.setdefault(reference.object_id, []).append(reference)

    unresolved = []
    ambiguous = []
    support_bindings = []
    for support in sorted(analysis.evidence_used, key=lambda item: (item.entity_type.value, item.entity_id)):
        if support.evidence_ids:
            unresolved.append({"entity_type": support.entity_type.value, "entity_id": support.entity_id,
                                "reason": f"support declares evidence_ids {support.evidence_ids!r} but no "
                                          "evidence-reference derivation is implemented for this boundary"})
            continue
        candidates = reference_by_object_id.get(support.entity_id, [])
        if len(candidates) == 0:
            unresolved.append({"entity_type": support.entity_type.value, "entity_id": support.entity_id,
                                "reason": "no governed reference exists for this entity_id in any admitted publication"})
            continue
        if len(candidates) > 1:
            ambiguous.append({"entity_type": support.entity_type.value, "entity_id": support.entity_id,
                               "candidates": [c.identity_key for c in candidates]})
            continue
        support_bindings.append(OpportunitySupportBinding(support, candidates[0], ()))

    save("unresolved_support.json", unresolved)
    save("ambiguous_support.json", ambiguous)
    if unresolved or ambiguous:
        raise RuntimeError(
            f"{len(unresolved)} evidence_used entities have no governed reference in any admitted "
            f"publication and {len(ambiguous)} are ambiguous; refusing to invent or guess bindings "
            f"(see unresolved_support.json / ambiguous_support.json)")
    emit(current, "PASS", t, bindings=len(support_bindings))

    current = "Opportunity Intelligence Publication"
    t = time.monotonic()
    publication = publish_opportunity_intelligence(
        analysis, analyst_version=ANALYST_VERSION,
        authoritative_context=authoritative_context,
        support_bindings=tuple(sorted(support_bindings, key=lambda item: (
            item.support.entity_type.value, item.support.entity_id, item.support.evidence_ids))))
    publication = validate_opportunity_intelligence_publication(publication)
    save("opportunity_intelligence_publication.json", publication.to_dict())
    emit(current, "PASS", t, objects=len(publication.snapshot.objects), references=len(publication.references))

    current = "Executive Opportunity Understanding"
    t = time.monotonic()
    understanding = build_executive_opportunity_understanding(
        ExecutiveUnderstandingInput(OPPORTUNITY_ID, publication))
    understanding = validate_executive_opportunity_understanding(understanding)
    save("executive_opportunity_understanding.json", understanding.to_dict()
         if hasattr(understanding, "to_dict") else str(understanding))
    emit(current, "PASS", t, index_sections=len(understanding.executive_index),
         detail_references=len(understanding.detail_register.references()),
         coverage_records=len(understanding.coverage_ledger))

    current = "Executive Opportunity Brief"
    t = time.monotonic()
    brief = validate_executive_opportunity_brief(build_executive_opportunity_brief(understanding))
    markdown = render_executive_opportunity_brief(brief)
    (OUT / "executive_opportunity_brief.md").write_text(markdown, encoding="utf-8")
    emit(current, "PASS", t, sections=len(brief.sections), markdown_chars=len(markdown))
except (ObservationBindingError, CanonicalOpportunityPublicationError, StructureBindingError,
        OpportunityStructurePublicationError, OpportunityPublicationError,
        ContractValidationError, RuntimeError) as exc:
    emit(current, "FAIL", t, exception_type=type(exc).__name__, exception=str(exc),
         traceback=traceback.format_exc())
    sys.exit(1)
except Exception as exc:
    emit(current, "FAIL", t, exception_type=type(exc).__name__, exception=str(exc),
         traceback=traceback.format_exc())
    raise
