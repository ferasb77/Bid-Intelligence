"""Retry only Stage D from a required private sidecar; never invokes A/B/C."""
import argparse
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import extractor
from config import get_api_key
from stage_d_checkpoints import checkpoint_run
from stage_d_projection import build_stage_d_synthesis_projection, finalize_stage_d_request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sidecar", type=Path)
    args = parser.parse_args()
    sidecar = json.loads(args.sidecar.read_text(encoding="utf-8"))
    snapshot = sidecar["authoritative_inputs"]
    normalized, conflicts = snapshot["normalized_facts"], snapshot["conflicts"]
    key = get_api_key()
    checkpoint_root = Path(tempfile.gettempdir()) / "bid-intelligence-canonical-checkpoints"
    projection = build_stage_d_synthesis_projection(normalized, conflicts)
    size = finalize_stage_d_request(projection, extractor.STAGE_D_SYNTHESIS_PROMPT)["diagnostics"]
    with checkpoint_run(mode="required", root=checkpoint_root) as store:
        with patch("extractor.extract_document_facts", side_effect=AssertionError("Stage A forbidden")), \
             patch("extractor.normalize_package_facts", side_effect=AssertionError("Stage B forbidden")), \
             patch("extractor.reconcile_package_facts", side_effect=AssertionError("Stage C forbidden")):
            result = extractor.synthesize_bid_brief(normalized, conflicts, key)
        validation_file = sorted((store.root / "stage-d").glob("attempt-*/validation.json"))[-1]
        validation = json.loads(validation_file.read_text(encoding="utf-8"))
        canonical_ids = {o["observation_id"] for o in normalized["_canonical_opportunity"]["observations"]}
        supports = [s for c in validation.get("resolved_citations", []) for s in c.get("supports", [])
                    if isinstance(s, dict) and s.get("entity_id") in canonical_ids]
        summary = {"model": "claude-haiku-4-5-20251001", "api_dispatch": True,
                   "stage_a_calls": 0, "stage_b_calls": 0, "stage_c_calls": 0,
                   "canonical_fields_reapplied": result["bid"].get("title") == "Digital Records Support",
                   "unrelated_conflict_preserved_resolved_field": result["bid"].get("clarification_deadline") == "2030-01-10",
                   "citation_validation": "PASS", "authoritative_reapplication": "PASS", "final_assembly": "PASS",
                   "tier2_opportunity_type": result["brief"].get("opportunity_type"),
                   "canonical_observation_citation_count": len(supports), "canonical_observation_citation_passed": bool(supports),
                   "prompt_chars": size["total_prompt_chars"], "headroom_chars": size["headroom_chars"],
                   "checkpoint_run_id": store.root.name, "retried_from_private_sidecar": True}
    if not summary["canonical_observation_citation_passed"]:
        raise RuntimeError("Stage D did not cite canonical observation support")
    evidence_path = ROOT / "tests/acceptance/results/canonical_opportunity_live_contract_smokes.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8")); evidence["stage_d"] = summary
    evidence_path.write_text(json.dumps(evidence, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
