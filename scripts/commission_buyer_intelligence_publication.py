"""Commission Buyer Evidence Publication, Canonical Buyer Publication, and
Buyer Intelligence Publication in sequence, using the real, live-fetched
Bank of Canada Buyer Evidence and the real, already-commissioned
BuyerIntelligenceAnalysis. Continues downstream to Buyer Brief. No
fixtures, no fabricated evidence.
"""
import json, sys, time, traceback
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

from real_bank_of_canada_buyer_evidence import build_real_buyer_evidence, build_real_canonical_buyer
from buyer_evidence_publication import (
    BuyerEvidencePublicationError, publish_buyer_evidence, validate_buyer_evidence_publication,
)
from canonical_buyer_publication import (
    CanonicalBuyerPublicationError, publish_canonical_buyer, validate_canonical_buyer_publication,
)
import buyer_intelligence as bi
from buyer_intelligence_publication import (
    BuyerIntelligencePublicationError, publish_buyer_intelligence,
    validate_buyer_intelligence_publication,
)
from buyer_brief import build_buyer_brief, render_buyer_brief
from buyer_intelligence import BuyerIntelligenceValidationError

records = []


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n",
                             encoding="utf-8")


def emit(boundary, status, t0, **extra):
    record = {"boundary": boundary, "status": status, "elapsed_seconds": round(time.monotonic() - t0, 3), **extra}
    records.append(record)
    save("boundaries.json", records)
    print(json.dumps(record, sort_keys=True), flush=True)


current = "Buyer Evidence Publication"
t = time.monotonic()
try:
    evidence = build_real_buyer_evidence()
    evidence_pub = validate_buyer_evidence_publication(publish_buyer_evidence(evidence))
    save("buyer_evidence_publication.json", evidence_pub.to_dict())
    emit(current, "PASS", t, objects=len(evidence_pub.snapshot.objects))

    current = "Canonical Buyer Publication"
    t = time.monotonic()
    buyer = build_real_canonical_buyer(evidence)
    buyer_pub = validate_canonical_buyer_publication(
        publish_canonical_buyer(buyer, evidence_publication=evidence_pub))
    save("canonical_buyer_publication.json", buyer_pub.to_dict())
    emit(current, "PASS", t, objects=len(buyer_pub.snapshot.objects))

    current = "Buyer Intelligence Analysis (real)"
    t = time.monotonic()
    inputs = bi.GovernedBuyerInputs(
        buyer=buyer, evidence=evidence,
        opportunity_id="opportunity:bank-of-canada-rfp-2026-026-original",
        canonical_opportunity_version="canonical-opportunity/1",
        canonical_opportunity_digest="a" * 64, opportunity_entity_ids=("obs:1",),
        procurement_evidence_ids=("procurement:notice",), procurement_package_digest="b" * 64,
        evaluation_context_id="evaluation:bank-of-canada-buyer-intelligence-2026-09-12",
        source_date=date(2026, 9, 12),
    )
    analysis = bi.analyze_buyer(inputs)
    emit(current, "PASS", t, analysis_id=analysis.analysis_id, buyer_facts=len(analysis.buyer_facts))

    current = "Buyer Intelligence Publication"
    t = time.monotonic()
    bi_pub = validate_buyer_intelligence_publication(publish_buyer_intelligence(
        analysis, buyer_evidence_publication=evidence_pub, canonical_buyer_publication=buyer_pub))
    save("buyer_intelligence_publication.json", bi_pub.to_dict())
    emit(current, "PASS", t, objects=len(bi_pub.snapshot.objects), references=len(bi_pub.references))

    current = "Buyer Brief"
    t = time.monotonic()
    brief = build_buyer_brief(inputs, analysis)
    markdown = render_buyer_brief(brief)
    (OUT / "buyer_brief.md").write_text(markdown, encoding="utf-8")
    emit(current, "PASS", t, markdown_chars=len(markdown))
except (BuyerEvidencePublicationError, CanonicalBuyerPublicationError,
        BuyerIntelligencePublicationError, BuyerIntelligenceValidationError, RuntimeError) as exc:
    emit(current, "FAIL", t, exception_type=type(exc).__name__, exception=str(exc),
         traceback=traceback.format_exc())
    sys.exit(1)
except Exception as exc:
    emit(current, "FAIL", t, exception_type=type(exc).__name__, exception=str(exc),
         traceback=traceback.format_exc())
    raise
