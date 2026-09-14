"""Repeatable, unprofiled wall-clock benchmark for the deterministic chain's
three measured hotspots (Opportunity Intelligence Publication, Executive
Opportunity Understanding, Executive Opportunity Brief) plus the complete
Evidence->Pack replay, against the frozen authoritative Bank of Canada
lineage. 1 warm-up + 5 measured runs per stage, reporting min/median/mean/max.

No cProfile (its own overhead would distort wall-clock comparisons). Zero
LLM calls. Read-only with respect to production code.
"""
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PHASE3_RUN_ID = "phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8"
PHASE3_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase3_commissioning" / PHASE3_RUN_ID
CORPUS = ROOT / "evaluation/bank_of_canada_briefing_pack/corrected_procurement_corpus"
MANIFEST = json.loads((ROOT / "evaluation/bank_of_canada_briefing_pack/corrected_corpus_manifest.json").read_text(encoding="utf-8"))
ACQ_FULL = json.loads((ROOT / "evaluation/bank_of_canada_briefing_pack/acquisition_manifest.json").read_text(encoding="utf-8"))
ACQ = {"retrieved_on": ACQ_FULL["retrieved_on"]}
SOURCE = {"source_id": "source:bank-of-canada-procurement", "publisher_name": "Bank of Canada",
          "base_url": "https://www.bankofcanada.ca/"}
OPPORTUNITY_ID = "opportunity:bank-of-canada-rfp-2026-026-corrected16"

from extractor import extract_document_with_metadata
from procurement_evidence_adapter import adapt_procurement_corpus
from evidence_publication import publish_evidence, validate_evidence_publication
from canonical_observation_binding import build_observation_bindings
from canonical_opportunity_publication import identity_object_id, publish_canonical_opportunity, validate_canonical_opportunity_publication
from opportunity_structure import build_opportunity_structure
from opportunity_structure_binding import build_structure_bindings
from opportunity_structure_publication import publish_opportunity_structure, validate_opportunity_structure_publication
from opportunity_intelligence import ANALYST_VERSION, analyze_opportunity
from opportunity_intelligence_publication import OpportunitySupportBinding, publish_opportunity_intelligence, validate_opportunity_intelligence_publication
from executive_opportunity_understanding import ExecutiveUnderstandingInput, build_executive_opportunity_understanding, validate_executive_opportunity_understanding
from executive_opportunity_brief import build_executive_opportunity_brief, validate_executive_opportunity_brief
from governed_reference_resolution import create_resolution_context
import buyer_intelligence as bi
from buyer_brief import build_buyer_brief
from real_bank_of_canada_buyer_evidence import build_real_buyer_evidence, build_real_canonical_buyer
from executive_briefing_pack import build_executive_briefing_pack, validate_executive_briefing_pack
from datetime import date

facts = json.loads((PHASE3_DIR / "stage_c_normalized_facts.json").read_text(encoding="utf-8"))
conflicts = json.loads((PHASE3_DIR / "stage_c_conflicts.json").read_text(encoding="utf-8"))
canonical = facts.get("_canonical_opportunity")

paths = sorted(p for p in CORPUS.rglob("*") if p.is_file())
package = [(p.relative_to(CORPUS).as_posix(), p.read_bytes()) for p in paths]
metadata = {"files": [], "doc_metadata": {}, "doc_texts": {}}
for name, payload in package:
    text, meta = extract_document_with_metadata(payload, name)
    metadata["files"].append(name); metadata["doc_metadata"][name] = meta; metadata["doc_texts"][name] = text


def build_evidence():
    snapshot = adapt_procurement_corpus(package, metadata, MANIFEST, ACQ, SOURCE)
    publication = validate_evidence_publication(publish_evidence(snapshot))
    return snapshot, publication


def build_canonical_pub(evidence_snapshot, evidence_publication):
    observation_bindings = build_observation_bindings(canonical, evidence_snapshot, evidence_publication)
    return validate_canonical_opportunity_publication(publish_canonical_opportunity(
        canonical, opportunity_id=OPPORTUNITY_ID, observation_bindings=observation_bindings))


def build_structure_pub(evidence_snapshot, evidence_publication):
    structure = build_opportunity_structure(facts, metadata)
    structure_bindings = build_structure_bindings(structure, evidence_snapshot, evidence_publication)
    return validate_opportunity_structure_publication(publish_opportunity_structure(
        structure, opportunity_id=OPPORTUNITY_ID, record_bindings=structure_bindings))


def build_analysis():
    analysis_context_id = identity_object_id(OPPORTUNITY_ID, canonical["input_digest"])
    return analyze_opportunity(facts, conflicts, context_id=analysis_context_id)


def build_support_bindings(analysis, evidence_publication, canonical_publication, structure_publication):
    reference_by_object_id = {}
    for publication in (evidence_publication, canonical_publication, structure_publication):
        for reference in publication.references:
            reference_by_object_id.setdefault(reference.object_id, []).append(reference)
    support_bindings = []
    for support in sorted(analysis.evidence_used, key=lambda item: (item.entity_type.value, item.entity_id)):
        if support.evidence_ids:
            continue
        candidates = reference_by_object_id.get(support.entity_id, [])
        if len(candidates) == 1:
            support_bindings.append(OpportunitySupportBinding(support, candidates[0], ()))
    return tuple(sorted(support_bindings, key=lambda item: (
        item.support.entity_type.value, item.support.entity_id, item.support.evidence_ids)))


def time_runs(fn, n=5):
    t0 = time.perf_counter()
    fn()  # warm-up -- excluded from min/median/mean/max, but its own time is recorded
    warmup_seconds = time.perf_counter() - t0
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        result = fn()
        samples.append(time.perf_counter() - t0)
    return samples, result, warmup_seconds


def summarize(samples, warmup_seconds):
    return {"warmup_seconds": round(warmup_seconds, 4),
            "min": round(min(samples), 4), "median": round(statistics.median(samples), 4),
            "mean": round(statistics.mean(samples), 4), "max": round(max(samples), 4),
            "samples": [round(s, 4) for s in samples]}


results = {}

evidence_snapshot, evidence_publication = build_evidence()
canonical_publication = build_canonical_pub(evidence_snapshot, evidence_publication)
structure_publication = build_structure_pub(evidence_snapshot, evidence_publication)
analysis = build_analysis()
support_bindings = build_support_bindings(analysis, evidence_publication, canonical_publication, structure_publication)
authoritative_context = create_resolution_context(
    context_id="executive-opportunity-brief-context-" + OPPORTUNITY_ID, context_version="1.0.0",
    snapshots=(evidence_publication.snapshot, canonical_publication.snapshot, structure_publication.snapshot),
)

samples, oi_pub, warmup = time_runs(lambda: validate_opportunity_intelligence_publication(
    publish_opportunity_intelligence(analysis, analyst_version=ANALYST_VERSION,
                                     authoritative_context=authoritative_context, support_bindings=support_bindings)))
results["opportunity_intelligence_publication"] = summarize(samples, warmup)
print("Opportunity Intelligence Publication:", results["opportunity_intelligence_publication"])

samples, understanding, warmup = time_runs(lambda: validate_executive_opportunity_understanding(
    build_executive_opportunity_understanding(ExecutiveUnderstandingInput(OPPORTUNITY_ID, oi_pub))))
results["executive_opportunity_understanding"] = summarize(samples, warmup)
print("Executive Opportunity Understanding:", results["executive_opportunity_understanding"])

samples, eob, warmup = time_runs(lambda: validate_executive_opportunity_brief(build_executive_opportunity_brief(understanding)))
results["executive_opportunity_brief"] = summarize(samples, warmup)
print("Executive Opportunity Brief:", results["executive_opportunity_brief"])


def full_chain():
    es, ep = build_evidence()
    cp = build_canonical_pub(es, ep)
    sp = build_structure_pub(es, ep)
    an = build_analysis()
    sb = build_support_bindings(an, ep, cp, sp)
    ctx = create_resolution_context(
        context_id="executive-opportunity-brief-context-" + OPPORTUNITY_ID, context_version="1.0.0",
        snapshots=(ep.snapshot, cp.snapshot, sp.snapshot),
    )
    oip = validate_opportunity_intelligence_publication(publish_opportunity_intelligence(
        an, analyst_version=ANALYST_VERSION, authoritative_context=ctx, support_bindings=sb))
    und = validate_executive_opportunity_understanding(build_executive_opportunity_understanding(
        ExecutiveUnderstandingInput(OPPORTUNITY_ID, oip)))
    eob = validate_executive_opportunity_brief(build_executive_opportunity_brief(und))

    buyer_evidence = build_real_buyer_evidence()
    buyer = build_real_canonical_buyer(buyer_evidence)
    canonical_digest = canonical["input_digest"].removeprefix("input_")
    opportunity_entity_ids = tuple(sorted(o["observation_id"] for o in canonical["observations"]))
    buyer_inputs = bi.GovernedBuyerInputs(
        buyer=buyer, evidence=buyer_evidence, opportunity_id=OPPORTUNITY_ID,
        canonical_opportunity_version="canonical-opportunity/1",
        canonical_opportunity_digest=canonical_digest,
        opportunity_entity_ids=opportunity_entity_ids, procurement_evidence_ids=opportunity_entity_ids,
        procurement_package_digest=canonical_digest,
        evaluation_context_id="evaluation:bank-of-canada-buyer-brief-buyerbrief-boc-2026-026-20260912T162735Z-118d60",
        source_date=date(2026, 9, 12),
    )
    buyer_analysis = bi.analyze_buyer(buyer_inputs)
    buyer_brief = build_buyer_brief(buyer_inputs, buyer_analysis)
    pack = validate_executive_briefing_pack(build_executive_briefing_pack(eob, buyer_brief=buyer_brief))
    return eob, pack


samples_raw = []
last = None
t0 = time.perf_counter()
full_chain()  # warm-up -- excluded from min/median/mean/max, but its own time is recorded
full_chain_warmup = time.perf_counter() - t0
for _ in range(5):
    t0 = time.perf_counter()
    last = full_chain()
    samples_raw.append(time.perf_counter() - t0)
results["full_deterministic_chain_evidence_to_pack"] = summarize(samples_raw, full_chain_warmup)
print("Full deterministic chain (Evidence->Pack):", results["full_deterministic_chain_evidence_to_pack"])

final_eob, final_pack = last
results["brief_id"] = final_eob.brief_id
results["pack_id"] = final_pack.pack_id
results["pack_revision_id"] = final_pack.pack_revision_id
results["pack_digest"] = final_pack.pack_digest
print()
print("brief_id:", final_eob.brief_id)
print("pack_id:", final_pack.pack_id)
print("pack_revision_id:", final_pack.pack_revision_id)
print("pack_digest:", final_pack.pack_digest)

OUT_PATH = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "evaluation/bank_of_canada_briefing_pack/performance_baseline/_benchmark_result.json")
OUT_PATH.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("Wrote", OUT_PATH)
