"""LEGACY / SUPERSEDED — targets the superseded 15-document original corpus
and invokes live LLM Stage A/D calls. This is NOT the authoritative
baseline commissioning harness. Use
scripts/commission_executive_briefing_pack_bank_of_canada.py instead, which
replays the accepted, deterministic, zero-LLM 16-document corpus lineage.
See evaluation/bank_of_canada_briefing_pack/COMMISSIONED_BASELINE.md.

Commission the Executive Briefing Pack boundary on real production data,
in one process so every upstream real artifact stays a live Python object
through composition (no serialize/reconstruct round-trip).

Chain: real 15-document Bank of Canada procurement corpus -> Evidence
Publication -> Stage A-D extraction -> Canonical Opportunity -> Canonical
Opportunity Publication -> Opportunity Structure Publication -> Opportunity
Intelligence -> Opportunity Intelligence Publication -> Executive
Opportunity Understanding -> Executive Opportunity Brief, together with the
real, live-fetched Bank of Canada Buyer Evidence -> Canonical Buyer
Publication -> Buyer Intelligence Analysis -> Buyer Intelligence
Publication -> Buyer Brief; then build_executive_briefing_pack() composes
the two real briefs. No fixtures, no fabricated evidence, no invented
governed bindings.
"""
import hashlib, json, sys, time, traceback
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--output", required=True, type=Path)
args = parser.parse_args()

OUT = args.output.resolve()
if OUT == ROOT or ROOT in OUT.parents:
    raise ValueError("Commissioning artifacts must remain outside the repository")
OUT.mkdir(parents=True, exist_ok=True)

records = []


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n",
                             encoding="utf-8")


def emit(boundary, status, t0, **extra):
    record = {"boundary": boundary, "status": status, "elapsed_seconds": round(time.monotonic() - t0, 3), **extra}
    records.append(record)
    save("boundaries.json", records)
    print(json.dumps(record, sort_keys=True), flush=True)


from config import get_api_key
from extractor import (
    extract_document_facts, extract_document_with_metadata, normalize_package_facts,
    reconcile_package_facts, synthesize_bid_brief,
)
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

from real_bank_of_canada_buyer_evidence import build_real_buyer_evidence, build_real_canonical_buyer
from buyer_evidence_publication import BuyerEvidencePublicationError, publish_buyer_evidence, validate_buyer_evidence_publication
from canonical_buyer_publication import CanonicalBuyerPublicationError, publish_canonical_buyer, validate_canonical_buyer_publication
import buyer_intelligence as bi
from buyer_intelligence_publication import (
    BuyerIntelligencePublicationError, publish_buyer_intelligence, validate_buyer_intelligence_publication,
)
from buyer_brief import build_buyer_brief, render_buyer_brief
from buyer_intelligence import BuyerIntelligenceValidationError

from executive_briefing_pack import ExecutiveBriefingPackError, build_executive_briefing_pack

CORPUS = ROOT / "tests/fixtures/local/bank_of_canada_2026_026"


def role_for(path: str) -> str:
    if path == "abstract.pdf":
        return "NOTICE_AND_DOCUMENT_INVENTORY"
    if path.startswith("Amendment"):
        return "AMENDMENT"
    return "PROCUREMENT_ATTACHMENT"


SOURCE = {"source_id": "source:bank-of-canada-procurement", "publisher_name": "Bank of Canada",
          "base_url": "https://www.bankofcanada.ca/"}
ACQ = {"retrieved_on": "2026-09-01"}
OPPORTUNITY_ID = "opportunity:bank-of-canada-rfp-2026-026-original"

current = "initialization"
t = time.monotonic()
started = t
try:
    key = get_api_key()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is unavailable")

    current = "Procurement Corpus"
    t = time.monotonic()
    paths = sorted(p for p in CORPUS.rglob("*") if p.is_file())
    package = [(p.relative_to(CORPUS).as_posix(), p.read_bytes()) for p in paths]
    if len(package) != 15:
        raise RuntimeError(f"expected 15 files in original corpus, found {len(package)}")
    manifest = {
        "corpus_id": "bank-of-canada-rfp-2026-026-original-15doc", "language": "English",
        "files": [{"path": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
                   "role": role_for(name)} for name, payload in package],
    }
    save("source-manifest.json", manifest)
    emit(current, "PASS", t, objects=len(package))

    current = "Procurement Evidence Adapter"
    t = time.monotonic()
    metadata = {"files": [], "doc_metadata": {}, "doc_texts": {}}
    for name, payload in package:
        text, meta = extract_document_with_metadata(payload, name)
        metadata["files"].append(name)
        metadata["doc_metadata"][name] = meta
        metadata["doc_texts"][name] = text
    evidence_snapshot = adapt_procurement_corpus(package, metadata, manifest, ACQ, SOURCE)
    emit(current, "PASS", t, objects=len(evidence_snapshot.objects))

    current = "Evidence Publication"
    t = time.monotonic()
    evidence_publication = validate_evidence_publication(publish_evidence(evidence_snapshot))
    emit(current, "PASS", t, objects=len(evidence_publication.snapshot.objects))

    current = "Stage A"
    t = time.monotonic()
    document_facts = []
    for i, (name, _) in enumerate(package, 1):
        print(json.dumps({"progress": "Stage A", "document": i, "of": len(package), "name": name}), flush=True)
        document_facts.append(extract_document_facts(metadata["doc_texts"][name], name, key))
    emit(current, "PASS", t, objects=len(document_facts))

    current = "Stage B"
    t = time.monotonic()
    normalized = normalize_package_facts(document_facts, metadata)
    emit(current, "PASS", t)

    current = "Stage C"
    t = time.monotonic()
    conflicts = reconcile_package_facts(normalized, metadata["files"])
    save("stage-c-conflicts.json", conflicts)
    save("stage-c-normalized-facts.json", normalized)
    emit(current, "PASS", t, objects=len(conflicts))

    current = "Stage D"
    t = time.monotonic()
    synthesis = synthesize_bid_brief(normalized, conflicts, key)
    emit(current, "PASS", t)

    current = "Canonical Opportunity"
    t = time.monotonic()
    canonical = normalized.get("_canonical_opportunity")
    if not isinstance(canonical, dict) or not canonical.get("input_digest"):
        raise RuntimeError("canonical opportunity absent from real Stage B/C output")
    emit(current, "PASS", t, input_digest=canonical["input_digest"])

    current = "Canonical Opportunity Publication"
    t = time.monotonic()
    observation_bindings = build_observation_bindings(canonical, evidence_snapshot, evidence_publication)
    canonical_publication = validate_canonical_opportunity_publication(publish_canonical_opportunity(
        canonical, opportunity_id=OPPORTUNITY_ID, observation_bindings=observation_bindings))
    emit(current, "PASS", t, objects=len(canonical_publication.snapshot.objects))

    current = "Opportunity Structure Publication"
    t = time.monotonic()
    structure = build_opportunity_structure(normalized, metadata)
    structure_bindings = build_structure_bindings(structure, evidence_snapshot, evidence_publication)
    structure_publication = validate_opportunity_structure_publication(publish_opportunity_structure(
        structure, opportunity_id=OPPORTUNITY_ID, record_bindings=structure_bindings))
    emit(current, "PASS", t, objects=len(structure_publication.snapshot.objects))

    current = "Opportunity Intelligence"
    t = time.monotonic()
    analysis_context_id = identity_object_id(OPPORTUNITY_ID, canonical["input_digest"])
    analysis = analyze_opportunity(normalized, conflicts, context_id=analysis_context_id)
    emit(current, "PASS", t, evidence_used=len(analysis.evidence_used))

    current = "Opportunity Intelligence Support Binding Derivation"
    t = time.monotonic()
    authoritative_context = create_resolution_context(
        context_id="opportunity-intelligence-context-" + OPPORTUNITY_ID, context_version="1.0.0",
        snapshots=(evidence_publication.snapshot, canonical_publication.snapshot, structure_publication.snapshot),
    )
    reference_by_object_id: dict[str, list] = {}
    for publication in (evidence_publication, canonical_publication, structure_publication):
        for reference in publication.references:
            reference_by_object_id.setdefault(reference.object_id, []).append(reference)
    unresolved, ambiguous, support_bindings = [], [], []
    for support in sorted(analysis.evidence_used, key=lambda item: (item.entity_type.value, item.entity_id)):
        if support.evidence_ids:
            unresolved.append({"entity_type": support.entity_type.value, "entity_id": support.entity_id,
                                "reason": "evidence-reference derivation not implemented for this boundary"})
            continue
        candidates = reference_by_object_id.get(support.entity_id, [])
        if len(candidates) == 0:
            unresolved.append({"entity_type": support.entity_type.value, "entity_id": support.entity_id,
                                "reason": "no governed reference exists for this entity_id"})
            continue
        if len(candidates) > 1:
            ambiguous.append({"entity_type": support.entity_type.value, "entity_id": support.entity_id})
            continue
        support_bindings.append(OpportunitySupportBinding(support, candidates[0], ()))
    save("unresolved_support.json", unresolved)
    save("ambiguous_support.json", ambiguous)
    if unresolved or ambiguous:
        raise RuntimeError(f"{len(unresolved)} unresolved and {len(ambiguous)} ambiguous support entities; "
                            "refusing to invent bindings")
    emit(current, "PASS", t, bindings=len(support_bindings))

    current = "Opportunity Intelligence Publication"
    t = time.monotonic()
    oi_publication = validate_opportunity_intelligence_publication(publish_opportunity_intelligence(
        analysis, analyst_version=ANALYST_VERSION, authoritative_context=authoritative_context,
        support_bindings=tuple(sorted(support_bindings, key=lambda item: (
            item.support.entity_type.value, item.support.entity_id, item.support.evidence_ids)))))
    emit(current, "PASS", t, objects=len(oi_publication.snapshot.objects))

    current = "Executive Opportunity Understanding"
    t = time.monotonic()
    understanding = validate_executive_opportunity_understanding(build_executive_opportunity_understanding(
        ExecutiveUnderstandingInput(OPPORTUNITY_ID, oi_publication)))
    emit(current, "PASS", t, index_sections=len(understanding.executive_index))

    current = "Executive Opportunity Brief"
    t = time.monotonic()
    eob = validate_executive_opportunity_brief(build_executive_opportunity_brief(understanding))
    (OUT / "executive_opportunity_brief.md").write_text(render_executive_opportunity_brief(eob), encoding="utf-8")
    emit(current, "PASS", t, sections=len(eob.sections))

    current = "Buyer Evidence Publication"
    t = time.monotonic()
    buyer_evidence = build_real_buyer_evidence()
    buyer_evidence_pub = validate_buyer_evidence_publication(publish_buyer_evidence(buyer_evidence))
    emit(current, "PASS", t, objects=len(buyer_evidence_pub.snapshot.objects))

    current = "Canonical Buyer Publication"
    t = time.monotonic()
    buyer = build_real_canonical_buyer(buyer_evidence)
    buyer_pub = validate_canonical_buyer_publication(
        publish_canonical_buyer(buyer, evidence_publication=buyer_evidence_pub))
    emit(current, "PASS", t, objects=len(buyer_pub.snapshot.objects))

    current = "Buyer Intelligence Analysis"
    t = time.monotonic()
    buyer_inputs = bi.GovernedBuyerInputs(
        buyer=buyer, evidence=buyer_evidence, opportunity_id=OPPORTUNITY_ID,
        canonical_opportunity_version="canonical-opportunity/1",
        canonical_opportunity_digest=canonical["input_digest"], opportunity_entity_ids=("obs:1",),
        procurement_evidence_ids=("procurement:notice",), procurement_package_digest="b" * 64,
        evaluation_context_id="evaluation:bank-of-canada-buyer-intelligence-2026-09-12",
        source_date=date(2026, 9, 12),
    )
    buyer_analysis = bi.analyze_buyer(buyer_inputs)
    emit(current, "PASS", t, buyer_facts=len(buyer_analysis.buyer_facts))

    current = "Buyer Intelligence Publication"
    t = time.monotonic()
    bi_pub = validate_buyer_intelligence_publication(publish_buyer_intelligence(
        buyer_analysis, buyer_evidence_publication=buyer_evidence_pub, canonical_buyer_publication=buyer_pub))
    emit(current, "PASS", t, objects=len(bi_pub.snapshot.objects))

    current = "Buyer Brief"
    t = time.monotonic()
    buyer_brief = build_buyer_brief(buyer_inputs, buyer_analysis)
    (OUT / "buyer_brief.md").write_text(render_buyer_brief(buyer_brief), encoding="utf-8")
    emit(current, "PASS", t, markdown_chars=len(render_buyer_brief(buyer_brief)))

    current = "Executive Briefing Pack"
    t = time.monotonic()
    pack = build_executive_briefing_pack(eob, buyer_brief=buyer_brief)
    save("executive_briefing_pack.json", pack.to_dict())
    emit(current, "PASS", t, pack_id=pack.pack_id, pack_revision_id=pack.pack_revision_id,
         pack_digest=pack.pack_digest, members=len(pack.manifest.members))
except (ObservationBindingError, CanonicalOpportunityPublicationError, StructureBindingError,
        OpportunityStructurePublicationError, OpportunityPublicationError, ContractValidationError,
        BuyerEvidencePublicationError, CanonicalBuyerPublicationError, BuyerIntelligencePublicationError,
        BuyerIntelligenceValidationError, ExecutiveBriefingPackError, RuntimeError) as exc:
    emit(current, "FAIL", t, exception_type=type(exc).__name__, exception=str(exc), traceback=traceback.format_exc())
    sys.exit(1)
except Exception as exc:
    emit(current, "FAIL", t, exception_type=type(exc).__name__, exception=str(exc), traceback=traceback.format_exc())
    raise
