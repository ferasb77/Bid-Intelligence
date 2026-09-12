"""Buyer Brief boundary commissioning against the latest authoritative
lineage (post canonical-term-fix Canonical Opportunity).

Buyer Evidence / Canonical Buyer: reuses the real, already live-fetched
Bank of Canada "About us" page content frozen in
real_bank_of_canada_buyer_evidence.py (retrieved via a real browser
navigation on 2026-09-12; every quote independently re-verified verbatim
against the real fetched page text by buyer_evidence_acquisition.py). No new
external fetch is performed by this script.

GovernedBuyerInputs' procurement-side fields (canonical_opportunity_digest,
opportunity_entity_ids, procurement_evidence_ids, procurement_package_digest)
are real values drawn directly from the latest, accepted Canonical
Opportunity artifact -- the exact same pattern already established in
scripts/continue_buyer_intelligence.py, pointed at the corrected 16-document
lineage instead of the superseded original-corpus one.

opportunity_analysis_id/opportunity_analysis_version (the optional slot that
could reference Opportunity Intelligence) are deliberately left unset: this
audit does not manufacture a connection analyze_buyer() itself never reads.

Zero LLM calls anywhere in this script or in analyze_buyer()/build_buyer_brief().
"""
import json
import secrets
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

PHASE3_RUN_ID = "phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8"
CANONOPP_RUN_ID = "canonopp-boc-2026-026-20260912T142551Z-34a031"
PHASE3_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase3_commissioning" / PHASE3_RUN_ID

RUN_ID = f"buyerbrief-boc-2026-026-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
OUT = ROOT / "evaluation/bank_of_canada_briefing_pack/buyer_brief_commissioning" / RUN_ID
OUT.mkdir(parents=True, exist_ok=False)


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n",
                             encoding="utf-8")


import buyer_intelligence as bi
from buyer_brief import build_buyer_brief, render_buyer_brief
from real_bank_of_canada_buyer_evidence import build_real_buyer_evidence, build_real_canonical_buyer

t0 = time.monotonic()

# --- 1. Real Buyer Evidence / Canonical Buyer (no new fetch) ----------------

evidence = build_real_buyer_evidence()
buyer = build_real_canonical_buyer(evidence)
save("buyer_evidence_set.json", evidence.to_dict())
save("canonical_buyer.json", buyer.to_dict())

# --- 2. Real Canonical Opportunity linkage (latest, accepted lineage) -------

canonical = json.loads((PHASE3_DIR / "stage_c_normalized_facts.json").read_text(encoding="utf-8"))["_canonical_opportunity"]
canonical_digest = canonical["input_digest"].removeprefix("input_")
opportunity_entity_ids = tuple(sorted(o["observation_id"] for o in canonical["observations"]))

inputs = bi.GovernedBuyerInputs(
    buyer=buyer, evidence=evidence,
    opportunity_id="opportunity:bank-of-canada-rfp-2026-026-corrected16",
    canonical_opportunity_version="canonical-opportunity/1",
    canonical_opportunity_digest=canonical_digest,
    opportunity_entity_ids=opportunity_entity_ids,
    procurement_evidence_ids=opportunity_entity_ids,
    procurement_package_digest=canonical_digest,
    evaluation_context_id=f"evaluation:bank-of-canada-buyer-brief-{RUN_ID}",
    source_date=date(2026, 9, 12),
)
save("governed_buyer_inputs_summary.json", {
    "opportunity_id": inputs.opportunity_id, "canonical_opportunity_digest": inputs.canonical_opportunity_digest,
    "opportunity_entity_ids_count": len(inputs.opportunity_entity_ids),
    "procurement_evidence_ids_count": len(inputs.procurement_evidence_ids),
    "procurement_package_digest": inputs.procurement_package_digest,
    "evaluation_context_id": inputs.evaluation_context_id, "source_date": inputs.source_date.isoformat(),
    "opportunity_analysis_id": inputs.opportunity_analysis_id,
    "opportunity_analysis_version": inputs.opportunity_analysis_version,
    "canonical_opportunity_run_id_source": CANONOPP_RUN_ID, "stage_c_run_id_source": PHASE3_RUN_ID,
})

# --- 3. Buyer Intelligence analysis (deterministic, zero LLM) ---------------

analysis = bi.analyze_buyer(inputs)
bi.validate_buyer_intelligence(inputs, analysis)
save("buyer_intelligence_analysis.json", analysis.to_dict())

# --- 4. Determinism: rebuild twice in-memory --------------------------------

analysis_2 = bi.analyze_buyer(inputs)
determinism = {
    "run1_analysis_id": analysis.analysis_id, "run2_analysis_id": analysis_2.analysis_id,
    "identical": analysis == analysis_2,
}
save("determinism_check.json", determinism)

# --- 5. Buyer Brief (deterministic presentation) ----------------------------

brief = build_buyer_brief(inputs, analysis)
save("buyer_brief.json", brief.to_dict())
markdown = render_buyer_brief(brief)
(OUT / "buyer_brief.md").write_text(markdown, encoding="utf-8")

elapsed = round(time.monotonic() - t0, 3)
git_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
run_metadata = {
    "run_id": RUN_ID, "timestamp_utc": datetime.now(timezone.utc).isoformat(), "git_commit": git_commit or "unavailable",
    "canonical_opportunity_run_id": CANONOPP_RUN_ID, "stage_c_run_id": PHASE3_RUN_ID,
    "production_entry_points": ["buyer_evidence_acquisition.adapt_buyer_evidence/build_canonical_buyer_identity (reused, real, no new fetch)",
                                "buyer_intelligence.analyze_buyer", "buyer_brief.build_buyer_brief", "buyer_brief.render_buyer_brief"],
    "llm_used": False, "llm_calls": 0, "api_cost": 0, "new_external_fetch_performed": False,
    "elapsed_seconds": elapsed,
    "counts": {
        "evidence_sources": len(evidence.sources), "evidence_documents": len(evidence.documents),
        "evidence_extracts": len(evidence.extracts),
        "buyer_facts": len(analysis.buyer_facts),
        "public_organizational_information": len(analysis.public_organizational_information),
        "verified_procurement_context": len(analysis.verified_procurement_context),
        "computed_facts": len(analysis.computed_facts),
        "interpretations": len(analysis.interpretations),
        "competing_hypotheses": len(analysis.competing_hypotheses),
        "assumptions": len(analysis.assumptions),
        "unknowns": len(analysis.unknowns),
        "conflicts": len(analysis.conflicts),
        "management_questions": len(analysis.management_questions),
        "limitations": len(analysis.limitations),
        "evidence_used": len(analysis.evidence_used),
        "evidence_register_entries": len(brief.evidence_register),
    },
}
save("run_metadata.json", run_metadata)

print("BUYER BRIEF COMMISSIONING")
print(json.dumps(run_metadata, indent=2))
print()
print("DETERMINISM:", json.dumps(determinism, indent=2))
print()
print(f"Dumps at: {OUT.relative_to(ROOT)}")
