"""Executive Opportunity Brief (EOB) boundary commissioning against the
latest authoritative, canonical-term-fixed lineage.

This is the exact real production chain (adapted from the already-working
scripts/continue_opportunity_intelligence.py, corrected-corpus branch, with
its own frozen Stage C artifact swapped in for the latest lineage and its
tail stopped immediately after Executive Opportunity Brief -- no Opportunity
Intelligence Publication content is skipped, but nothing beyond EOB is
built):

Evidence (real corpus) -> Evidence Publication -> Canonical Opportunity
Publication -> Opportunity Structure Publication -> Opportunity Intelligence
(analyze_opportunity, already commissioned separately) -> Opportunity
Intelligence Support Binding derivation -> Opportunity Intelligence
Publication -> Executive Opportunity Understanding -> Executive Opportunity
Brief. STOP.

No Buyer Brief is consumed anywhere in this chain (confirmed by exhaustive
code reading before this script was written -- zero "buyer" references in
executive_opportunity_understanding.py, executive_opportunity_brief.py, or
opportunity_intelligence_publication.py).

Zero LLM calls anywhere in this chain (confirmed by code reading of every
module involved -- this is a deterministic evidence-resolution and
presentation pipeline, not a generative one).
"""
import hashlib
import json
import secrets
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PHASE1_RUN_ID = "phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5"
PHASE2_RUN_ID = "phase2-boc-2026-026-stageb-canonterm-fix-20260912T142551Z-34a031"
PHASE3_RUN_ID = "phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8"
CANONOPP_RUN_ID = "canonopp-boc-2026-026-20260912T142551Z-34a031"
OPPSTRUCT_RUN_ID = "oppstruct-boc-2026-026-20260912T144353Z-dd4b10"
OPPINT_RUN_ID = "oppint-boc-2026-026-20260912T161717Z-50ab1a"
PHASE3_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase3_commissioning" / PHASE3_RUN_ID
CORPUS = ROOT / "evaluation/bank_of_canada_briefing_pack/corrected_procurement_corpus"
MANIFEST = json.loads((ROOT / "evaluation/bank_of_canada_briefing_pack/corrected_corpus_manifest.json").read_text(encoding="utf-8"))
ACQ_FULL = json.loads((ROOT / "evaluation/bank_of_canada_briefing_pack/acquisition_manifest.json").read_text(encoding="utf-8"))
ACQ = {"retrieved_on": ACQ_FULL["retrieved_on"]}
SOURCE = {"source_id": "source:bank-of-canada-procurement", "publisher_name": "Bank of Canada",
          "base_url": "https://www.bankofcanada.ca/"}
EXPECTED_COUNT = 16

RUN_ID = f"eob-boc-2026-026-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
OUT = ROOT / "evaluation/bank_of_canada_briefing_pack/executive_opportunity_brief_commissioning" / RUN_ID
OUT.mkdir(parents=True, exist_ok=False)

OPPORTUNITY_ID = "opportunity:bank-of-canada-rfp-2026-026-corrected16"

records = []


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n",
                             encoding="utf-8")


def emit(boundary, status, t0, **extra):
    record = {"boundary": boundary, "status": status, "elapsed_seconds": round(time.monotonic() - t0, 3), **extra}
    records.append(record)
    save("boundaries.json", records)
    print(json.dumps(record, sort_keys=True), flush=True)


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

facts = json.loads((PHASE3_DIR / "stage_c_normalized_facts.json").read_text(encoding="utf-8"))
conflicts = json.loads((PHASE3_DIR / "stage_c_conflicts.json").read_text(encoding="utf-8"))
canonical = facts.get("_canonical_opportunity")

current = "Evidence (real corpus, deterministic parse)"
t = time.monotonic()
try:
    paths = sorted(p for p in CORPUS.rglob("*") if p.is_file())
    package = [(p.relative_to(CORPUS).as_posix(), p.read_bytes()) for p in paths]
    if len(package) != EXPECTED_COUNT or {n for n, _ in package} != {x["path"] for x in MANIFEST["files"]}:
        raise RuntimeError("corpus identity mismatch")
    fresh_digests = {name: hashlib.sha256(payload).hexdigest() for name, payload in package}
    manifest_digests = {item["path"]: item["sha256"] for item in MANIFEST["files"]}
    if fresh_digests != manifest_digests:
        raise RuntimeError("corpus content digest drift vs corrected_corpus_manifest.json")
    metadata = {"files": [], "doc_metadata": {}, "doc_texts": {}}
    for name, payload in package:
        text, meta = extract_document_with_metadata(payload, name)
        metadata["files"].append(name); metadata["doc_metadata"][name] = meta; metadata["doc_texts"][name] = text
    evidence_snapshot = adapt_procurement_corpus(package, metadata, MANIFEST, ACQ, SOURCE)
    evidence_publication = validate_evidence_publication(publish_evidence(evidence_snapshot))
    emit(current, "PASS", t, objects=len(evidence_snapshot.objects))

    current = "Canonical Opportunity Publication"
    t = time.monotonic()
    if not isinstance(canonical, dict) or not canonical.get("input_digest"):
        raise RuntimeError("canonical opportunity absent from real Stage B/C output")
    observation_bindings = build_observation_bindings(canonical, evidence_snapshot, evidence_publication)
    canonical_publication = validate_canonical_opportunity_publication(publish_canonical_opportunity(
        canonical, opportunity_id=OPPORTUNITY_ID, observation_bindings=observation_bindings))
    emit(current, "PASS", t, objects=len(canonical_publication.snapshot.objects))

    current = "Opportunity Structure Publication"
    t = time.monotonic()
    structure = build_opportunity_structure(facts, metadata)
    structure_bindings = build_structure_bindings(structure, evidence_snapshot, evidence_publication)
    structure_publication = validate_opportunity_structure_publication(publish_opportunity_structure(
        structure, opportunity_id=OPPORTUNITY_ID, record_bindings=structure_bindings))
    emit(current, "PASS", t, objects=len(structure_publication.snapshot.objects))

    current = "Opportunity Intelligence (real analyst, already independently commissioned)"
    t = time.monotonic()
    analysis_context_id = identity_object_id(OPPORTUNITY_ID, canonical["input_digest"])
    analysis = analyze_opportunity(facts, conflicts, context_id=analysis_context_id)
    save("opportunity_intelligence_analysis.json", analysis.to_dict() if hasattr(analysis, "to_dict") else None)
    emit(current, "PASS", t,
         evidence_used=len(analysis.evidence_used), computed_facts=len(analysis.computed_facts),
         inferences=len(analysis.inferences), hypotheses=len(analysis.hypotheses),
         unresolved_conflict_ids=len(analysis.unknowns.unresolved_conflict_ids))

    current = "Opportunity Intelligence Support Binding Derivation"
    t = time.monotonic()
    authoritative_context = create_resolution_context(
        context_id="executive-opportunity-brief-context-" + OPPORTUNITY_ID,
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
                                "reason": "support declares evidence_ids but no evidence-reference derivation is implemented for this boundary"})
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
            f"publication and {len(ambiguous)} are ambiguous; refusing to invent or guess bindings")
    emit(current, "PASS", t, bindings=len(support_bindings))

    current = "Opportunity Intelligence Publication"
    t = time.monotonic()
    oi_publication = publish_opportunity_intelligence(
        analysis, analyst_version=ANALYST_VERSION,
        authoritative_context=authoritative_context,
        support_bindings=tuple(sorted(support_bindings, key=lambda item: (
            item.support.entity_type.value, item.support.entity_id, item.support.evidence_ids))))
    oi_publication = validate_opportunity_intelligence_publication(oi_publication)
    save("opportunity_intelligence_publication.json", oi_publication.to_dict())
    emit(current, "PASS", t, objects=len(oi_publication.snapshot.objects), references=len(oi_publication.references))

    current = "Executive Opportunity Understanding"
    t = time.monotonic()
    understanding = build_executive_opportunity_understanding(
        ExecutiveUnderstandingInput(OPPORTUNITY_ID, oi_publication))
    understanding = validate_executive_opportunity_understanding(understanding)
    save("executive_opportunity_understanding.json", understanding.to_dict())
    emit(current, "PASS", t, index_sections=len(understanding.executive_index),
         detail_references=len(understanding.detail_register.references()),
         coverage_records=len(understanding.coverage_ledger))

    current = "Executive Opportunity Brief"
    t = time.monotonic()
    brief_1 = validate_executive_opportunity_brief(build_executive_opportunity_brief(understanding))
    brief_2 = validate_executive_opportunity_brief(build_executive_opportunity_brief(understanding))
    determinism = {"brief_id_1": brief_1.brief_id, "brief_id_2": brief_2.brief_id,
                   "identical": brief_1.to_dict() == brief_2.to_dict()}
    save("determinism_check.json", determinism)
    save("executive_opportunity_brief.json", brief_1.to_dict())
    markdown = render_executive_opportunity_brief(brief_1)
    (OUT / "executive_opportunity_brief.md").write_text(markdown, encoding="utf-8")
    emit(current, "PASS", t, sections=len(brief_1.sections), markdown_chars=len(markdown),
         detail_register=len(brief_1.detail_register), coverage_ledger=len(brief_1.coverage_ledger))
except (ObservationBindingError, CanonicalOpportunityPublicationError, StructureBindingError,
        OpportunityStructurePublicationError, OpportunityPublicationError,
        ContractValidationError, RuntimeError) as exc:
    emit(current, "FAIL", t, exception_type=type(exc).__name__, exception=str(exc))
    raise
