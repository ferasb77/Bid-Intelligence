"""Executive Briefing Pack boundary commissioning against the latest
authoritative, post-conflict-identity-remediation lineage.

This is pure composition commissioning: it rebuilds the two already-accepted
member artifacts in-memory by replaying their own already-commissioned,
deterministic, zero-LLM production chains verbatim --

  Executive Opportunity Brief chain (identical to
  scripts/commission_executive_opportunity_brief_bank_of_canada.py, whose
  latest accepted run is eob-boc-2026-026-20260912T173422Z-783064):
  Evidence -> Canonical Opportunity Publication -> Opportunity Structure
  Publication -> Opportunity Intelligence -> Opportunity Intelligence
  Publication -> Executive Opportunity Understanding -> Executive
  Opportunity Brief.

  Buyer Brief chain (identical to
  scripts/commission_buyer_brief_bank_of_canada.py, whose latest accepted
  run is buyerbrief-boc-2026-026-20260912T162735Z-118d60): real,
  already-fetched Buyer Evidence / Canonical Buyer (no new fetch) -> Buyer
  Intelligence Analysis -> Buyer Brief.

-- then calls executive_briefing_pack.build_executive_briefing_pack() and
validate_executive_briefing_pack() completely unchanged. Because both chains
are proven deterministic (each already has its own passing determinism
check), replaying them in-process reproduces byte-identical members to the
accepted runs without re-parsing any persisted JSON back into typed
dataclasses (for which no deserializer exists) -- this is the only way to
obtain live ExecutiveOpportunityBrief / BuyerBrief objects for the pack's
own strongly-typed, reference-holding constructor.

No Stage A rerun. No Stage D. No new buyer research or external fetch. No
LLM/API calls anywhere in this script or in any function it calls (every
function above already carries its own "zero LLM calls" commissioning
report). No new intelligence, no submission/proposal content, no
optimization work.
"""
import json
import secrets
import subprocess
import sys
import time
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PHASE1_RUN_ID = "phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5"
PHASE3_RUN_ID = "phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8"
CANONOPP_RUN_ID = "canonopp-boc-2026-026-20260912T142551Z-34a031"
EOB_RUN_ID_SOURCE = "eob-boc-2026-026-20260912T173422Z-783064"
BUYER_BRIEF_RUN_ID_SOURCE = "buyerbrief-boc-2026-026-20260912T162735Z-118d60"
PHASE3_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase3_commissioning" / PHASE3_RUN_ID
CORPUS = ROOT / "evaluation/bank_of_canada_briefing_pack/corrected_procurement_corpus"
MANIFEST = json.loads((ROOT / "evaluation/bank_of_canada_briefing_pack/corrected_corpus_manifest.json").read_text(encoding="utf-8"))
ACQ_FULL = json.loads((ROOT / "evaluation/bank_of_canada_briefing_pack/acquisition_manifest.json").read_text(encoding="utf-8"))
ACQ = {"retrieved_on": ACQ_FULL["retrieved_on"]}
SOURCE = {"source_id": "source:bank-of-canada-procurement", "publisher_name": "Bank of Canada",
          "base_url": "https://www.bankofcanada.ca/"}
EXPECTED_COUNT = 16
OPPORTUNITY_ID = "opportunity:bank-of-canada-rfp-2026-026-corrected16"

RUN_ID = f"briefingpack-boc-2026-026-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
OUT = ROOT / "evaluation/bank_of_canada_briefing_pack/executive_briefing_pack_commissioning" / RUN_ID
OUT.mkdir(parents=True, exist_ok=False)

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

import buyer_intelligence as bi
from buyer_brief import build_buyer_brief, render_buyer_brief
from real_bank_of_canada_buyer_evidence import build_real_buyer_evidence, build_real_canonical_buyer

from executive_briefing_pack import (
    ExecutiveBriefingPackError, PackFailureCode,
    build_executive_briefing_pack, validate_executive_briefing_pack,
)

facts = json.loads((PHASE3_DIR / "stage_c_normalized_facts.json").read_text(encoding="utf-8"))
conflicts = json.loads((PHASE3_DIR / "stage_c_conflicts.json").read_text(encoding="utf-8"))
canonical = facts.get("_canonical_opportunity")

current = "Evidence (real corpus, deterministic parse)"
t = time.monotonic()
try:
    import hashlib
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

    current = "Opportunity Intelligence"
    t = time.monotonic()
    analysis_context_id = identity_object_id(OPPORTUNITY_ID, canonical["input_digest"])
    analysis = analyze_opportunity(facts, conflicts, context_id=analysis_context_id)
    emit(current, "PASS", t, evidence_used=len(analysis.evidence_used),
         unresolved_conflict_ids=len(analysis.unknowns.unresolved_conflict_ids))

    current = "Opportunity Intelligence Support Binding Derivation"
    t = time.monotonic()
    authoritative_context = create_resolution_context(
        # Must match scripts/commission_executive_opportunity_brief_bank_of_canada.py
        # exactly -- this context_id is part of the deterministic identity
        # chain that produces the Executive Opportunity Brief's own brief_id.
        # Reusing it verbatim is what makes this replay reproduce the exact
        # already-accepted eob-boc-2026-026-20260912T173422Z-783064 brief,
        # rather than a merely equivalent but differently-identified one.
        context_id="executive-opportunity-brief-context-" + OPPORTUNITY_ID,
        context_version="1.0.0",
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
    emit(current, "PASS", t, objects=len(oi_publication.snapshot.objects))

    current = "Executive Opportunity Understanding"
    t = time.monotonic()
    understanding = build_executive_opportunity_understanding(
        ExecutiveUnderstandingInput(OPPORTUNITY_ID, oi_publication))
    understanding = validate_executive_opportunity_understanding(understanding)
    emit(current, "PASS", t, index_sections=len(understanding.executive_index),
         coverage_records=len(understanding.coverage_ledger))

    current = "Executive Opportunity Brief"
    t = time.monotonic()
    eob = validate_executive_opportunity_brief(build_executive_opportunity_brief(understanding))
    eob_replay = validate_executive_opportunity_brief(build_executive_opportunity_brief(understanding))
    if eob.brief_id != eob_replay.brief_id or eob.to_json() != eob_replay.to_json():
        raise RuntimeError("Executive Opportunity Brief is not deterministic across replay within this run")
    (OUT / "executive_opportunity_brief.md").write_text(render_executive_opportunity_brief(eob), encoding="utf-8")
    emit(current, "PASS", t, brief_id=eob.brief_id, sections=len(eob.sections),
         source_eob_run_id=EOB_RUN_ID_SOURCE)

    current = "Buyer Evidence / Canonical Buyer (no new fetch)"
    t = time.monotonic()
    buyer_evidence = build_real_buyer_evidence()
    buyer = build_real_canonical_buyer(buyer_evidence)
    emit(current, "PASS", t, evidence_sources=len(buyer_evidence.sources),
         evidence_documents=len(buyer_evidence.documents))

    current = "Buyer Intelligence Analysis"
    t = time.monotonic()
    canonical_digest = canonical["input_digest"].removeprefix("input_")
    opportunity_entity_ids = tuple(sorted(o["observation_id"] for o in canonical["observations"]))
    buyer_inputs = bi.GovernedBuyerInputs(
        buyer=buyer, evidence=buyer_evidence, opportunity_id=OPPORTUNITY_ID,
        canonical_opportunity_version="canonical-opportunity/1",
        canonical_opportunity_digest=canonical_digest,
        opportunity_entity_ids=opportunity_entity_ids,
        procurement_evidence_ids=opportunity_entity_ids,
        procurement_package_digest=canonical_digest,
        # Must match the exact literal persisted in the accepted Buyer Brief
        # run's own governed_buyer_inputs_summary.json (it embeds that run's
        # own RUN_ID, so it cannot be re-derived from anything else) --
        # reusing it verbatim is what makes this replay reproduce the exact
        # already-accepted buyerbrief-boc-2026-026-20260912T162735Z-118d60
        # brief, rather than a merely equivalent but differently-identified one.
        evaluation_context_id=f"evaluation:bank-of-canada-buyer-brief-{BUYER_BRIEF_RUN_ID_SOURCE}",
        source_date=date(2026, 9, 12),
    )
    buyer_analysis = bi.analyze_buyer(buyer_inputs)
    bi.validate_buyer_intelligence(buyer_inputs, buyer_analysis)
    buyer_analysis_replay = bi.analyze_buyer(buyer_inputs)
    if buyer_analysis != buyer_analysis_replay:
        raise RuntimeError("Buyer Intelligence analysis is not deterministic across replay within this run")
    emit(current, "PASS", t, buyer_facts=len(buyer_analysis.buyer_facts),
         canonical_opportunity_run_id_source=CANONOPP_RUN_ID, stage_c_run_id_source=PHASE3_RUN_ID)

    current = "Buyer Brief"
    t = time.monotonic()
    buyer_brief = build_buyer_brief(buyer_inputs, buyer_analysis)
    buyer_brief_replay = build_buyer_brief(buyer_inputs, buyer_analysis)
    if buyer_brief.brief_id != buyer_brief_replay.brief_id or buyer_brief.to_json() != buyer_brief_replay.to_json():
        raise RuntimeError("Buyer Brief is not deterministic across replay within this run")
    (OUT / "buyer_brief.md").write_text(render_buyer_brief(buyer_brief), encoding="utf-8")
    emit(current, "PASS", t, brief_id=buyer_brief.brief_id, opportunity_id=buyer_brief.opportunity_id,
         source_buyer_brief_run_id=BUYER_BRIEF_RUN_ID_SOURCE)

    current = "Executive Briefing Pack (composition)"
    t = time.monotonic()
    pack_1 = build_executive_briefing_pack(eob, buyer_brief=buyer_brief)
    validate_executive_briefing_pack(pack_1)
    pack_2 = build_executive_briefing_pack(eob, buyer_brief=buyer_brief)
    validate_executive_briefing_pack(pack_2)
    determinism = {
        "pack_id_1": pack_1.pack_id, "pack_id_2": pack_2.pack_id,
        "pack_revision_id_1": pack_1.pack_revision_id, "pack_revision_id_2": pack_2.pack_revision_id,
        "pack_digest_1": pack_1.pack_digest, "pack_digest_2": pack_2.pack_digest,
        "manifest_digest_1": pack_1.manifest.manifest_digest, "manifest_digest_2": pack_2.manifest.manifest_digest,
        "to_json_identical": pack_1.to_json() == pack_2.to_json(),
        "identical": (pack_1.pack_id == pack_2.pack_id and pack_1.pack_revision_id == pack_2.pack_revision_id
                      and pack_1.pack_digest == pack_2.pack_digest and pack_1.to_json() == pack_2.to_json()),
    }
    save("determinism_check.json", determinism)
    if not determinism["identical"]:
        raise RuntimeError("Executive Briefing Pack is not deterministic across replay within this run")

    # Member-immutability proof: the exact same live objects are held by
    # reference (never copied) -- `is` identity, not just equality.
    immutability = {
        "eob_held_by_reference": pack_1.executive_opportunity_brief is eob,
        "buyer_brief_held_by_reference": pack_1.buyer_brief is buyer_brief,
    }
    save("member_immutability_check.json", immutability)
    if not all(immutability.values()):
        raise RuntimeError("pack did not hold member artifacts by reference")

    # Tamper-detection proof: mutate one manifest member's digest and prove
    # the pack fails closed rather than silently accepting it.
    tamper_results = {}
    tampered_eob_member = replace(pack_1.manifest.members[0], artifact_digest="0" * 64)
    tampered_manifest = replace(pack_1.manifest, members=(tampered_eob_member, pack_1.manifest.members[1]))
    try:
        replace(pack_1, manifest=tampered_manifest)
        tamper_results["digest_tamper_detected"] = False
    except ExecutiveBriefingPackError as exc:
        tamper_results["digest_tamper_detected"] = exc.code == PackFailureCode.DIGEST_MISMATCH

    duplicate_manifest = replace(pack_1.manifest, members=(pack_1.manifest.members[0], pack_1.manifest.members[0]))
    try:
        replace(pack_1, manifest=duplicate_manifest)
        tamper_results["duplicate_member_detected"] = False
    except ExecutiveBriefingPackError as exc:
        tamper_results["duplicate_member_detected"] = exc.code == PackFailureCode.DUPLICATE_MEMBER

    missing_manifest = replace(pack_1.manifest, members=(pack_1.manifest.members[0],))
    try:
        replace(pack_1, manifest=missing_manifest)
        tamper_results["missing_member_detected"] = False
    except ExecutiveBriefingPackError as exc:
        tamper_results["missing_member_detected"] = exc.code == PackFailureCode.MISSING_MEMBER

    save("tamper_test_results.json", tamper_results)
    if not all(tamper_results.values()):
        raise RuntimeError(f"a tamper/negative test did not fail closed as expected: {tamper_results}")

    pack = pack_1
    save("executive_briefing_pack.json", pack.to_dict())
    manifest_table = [
        {"order": i, "slot": m.slot, "volume_class": m.volume_class, "contract_version": m.contract_version,
         "artifact_id": m.artifact_id, "revision_id": m.revision_id, "artifact_digest": m.artifact_digest,
         "opportunity_id": m.opportunity_id, "buyer_id": m.buyer_id,
         "evidence_cutoff": m.evidence_cutoff.isoformat() if m.evidence_cutoff else None,
         "evidence_cutoff_governed_absence": m.evidence_cutoff_governed_absence}
        for i, m in enumerate(pack.manifest.members)
    ]
    save("manifest_table.json", manifest_table)
    emit(current, "PASS", t, pack_id=pack.pack_id, pack_revision_id=pack.pack_revision_id,
         pack_digest=pack.pack_digest, members=len(pack.manifest.members))
except (ObservationBindingError, CanonicalOpportunityPublicationError, StructureBindingError,
        OpportunityStructurePublicationError, OpportunityPublicationError,
        ContractValidationError, ExecutiveBriefingPackError, RuntimeError) as exc:
    emit(current, "FAIL", t, exception_type=type(exc).__name__, exception=str(exc))
    raise
