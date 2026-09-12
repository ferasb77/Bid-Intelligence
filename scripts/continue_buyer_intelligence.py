"""Continue commissioning past Buyer Evidence Acquisition + Canonical Buyer
construction: run the real Buyer Intelligence analyst (analyze_buyer) using
the real Canonical Buyer / Buyer Evidence built from the real, live-fetched
Bank of Canada source material, plus the real Canonical Opportunity already
commissioned for the Bank of Canada RFP 2026-026 corpus. No fixtures, no
fabricated evidence, no reuse of the hand-authored evaluation script.
"""
import json, sys, time, traceback
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--opportunity-dir", required=True, type=Path,
                     help="Directory containing the real stage-c-normalized-facts.json")
parser.add_argument("--output", required=True, type=Path)
args = parser.parse_args()

OUT = args.output.resolve()
if OUT == ROOT or ROOT in OUT.parents:
    raise ValueError("Commissioning artifacts must remain outside the repository")
OUT.mkdir(parents=True, exist_ok=True)

import buyer_intelligence as bi
from real_bank_of_canada_buyer_evidence import build_real_buyer_evidence, build_real_canonical_buyer

records = []


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n",
                             encoding="utf-8")


def emit(boundary, status, t0, **extra):
    record = {"boundary": boundary, "status": status, "elapsed_seconds": round(time.monotonic() - t0, 3), **extra}
    records.append(record)
    save("boundaries.json", records)
    print(json.dumps(record, sort_keys=True), flush=True)


current = "Reconstruct Canonical Buyer / Buyer Evidence (real)"
t = time.monotonic()
try:
    evidence = build_real_buyer_evidence()
    buyer = build_real_canonical_buyer(evidence)
    emit(current, "PASS", t, extracts=len(evidence.extracts))

    current = "Opportunity linkage (real Bank of Canada corpus)"
    t = time.monotonic()
    facts = json.loads((args.opportunity_dir / "stage-c-normalized-facts.json").read_text(encoding="utf-8"))
    canonical = facts.get("_canonical_opportunity")
    if not isinstance(canonical, dict) or not canonical.get("input_digest"):
        raise RuntimeError("real canonical opportunity absent from Stage B/C output")
    canonical_digest = canonical["input_digest"].removeprefix("input_")
    opportunity_entity_ids = tuple(sorted(o["observation_id"] for o in canonical["observations"]))
    emit(current, "PASS", t, observations=len(opportunity_entity_ids))

    current = "Buyer Intelligence GovernedBuyerInputs construction"
    t = time.monotonic()
    inputs = bi.GovernedBuyerInputs(
        buyer=buyer, evidence=evidence,
        opportunity_id="opportunity:bank-of-canada-rfp-2026-026-original",
        canonical_opportunity_version="canonical-opportunity/1",
        canonical_opportunity_digest=canonical_digest,
        opportunity_entity_ids=opportunity_entity_ids,
        procurement_evidence_ids=opportunity_entity_ids,
        procurement_package_digest=canonical_digest,
        evaluation_context_id="evaluation:bank-of-canada-buyer-intelligence-2026-09-12",
        source_date=date(2026, 9, 12),
    )
    emit(current, "PASS", t, evidence_ids=len(inputs.evidence_ids))

    current = "Buyer Intelligence analysis (producer)"
    t = time.monotonic()
    analysis = bi.analyze_buyer(inputs)
    save("buyer_intelligence_analysis.json", analysis.to_dict())
    emit(current, "PASS", t, analysis_id=analysis.analysis_id,
         buyer_facts=len(analysis.buyer_facts),
         public_organizational_information=len(analysis.public_organizational_information),
         verified_procurement_context=len(analysis.verified_procurement_context),
         computed_facts=len(analysis.computed_facts), unknowns=len(analysis.unknowns),
         management_questions=len(analysis.management_questions),
         limitations=len(analysis.limitations), evidence_used=len(analysis.evidence_used))

    current = "Buyer Intelligence analysis independent re-validation"
    t = time.monotonic()
    bi.validate_buyer_intelligence(inputs, analysis)
    emit(current, "PASS", t)
except bi.BuyerIntelligenceValidationError as exc:
    emit(current, "FAIL", t, exception_type=type(exc).__name__, exception=str(exc),
         traceback=traceback.format_exc())
    sys.exit(1)
except Exception as exc:
    emit(current, "FAIL", t, exception_type=type(exc).__name__, exception=str(exc),
         traceback=traceback.format_exc())
    raise
