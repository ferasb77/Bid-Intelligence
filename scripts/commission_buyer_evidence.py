"""Commission the Buyer Evidence Acquisition + Canonical Buyer construction
boundary using REAL, live-fetched content from the Bank of Canada's own
official website (see real_bank_of_canada_buyer_evidence.py for the exact
retrieved text and retrieval date).

No fixtures, no fabricated evidence, no reuse of the hand-authored
evaluation script.
"""
import json, sys
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

from buyer_evidence_acquisition import BuyerEvidenceAcquisitionError
from real_bank_of_canada_buyer_evidence import build_real_buyer_evidence, build_real_canonical_buyer


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n",
                             encoding="utf-8")


try:
    evidence = build_real_buyer_evidence()
    save("buyer_evidence_set.json", evidence.to_dict())
    print(json.dumps({"boundary": "Buyer Evidence Acquisition", "status": "PASS",
                      "sources": len(evidence.sources), "documents": len(evidence.documents),
                      "citations": len(evidence.citations), "extracts": len(evidence.extracts)}, sort_keys=True))

    buyer = build_real_canonical_buyer(evidence)
    save("canonical_buyer.json", buyer.to_dict())
    print(json.dumps({"boundary": "Canonical Buyer construction", "status": "PASS",
                      "buyer_id": buyer.buyer_id, "evidence_ids": list(buyer.evidence_ids)}, sort_keys=True))
except BuyerEvidenceAcquisitionError as exc:
    print(json.dumps({"boundary": "Buyer Evidence Acquisition / Canonical Buyer construction",
                      "status": "FAIL", "exception_type": type(exc).__name__, "exception": str(exc)},
                     sort_keys=True))
    sys.exit(1)
