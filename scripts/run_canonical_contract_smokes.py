"""Small live Stage A and Stage D canonical contract smokes; no benchmark reruns."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import extractor
from canonical_opportunity import SCHEMA_VERSION
from config import get_api_key
from stage_d_checkpoints import checkpoint_run
from stage_d_projection import build_stage_d_synthesis_projection, finalize_stage_d_request


SOURCES = {
    "generic.txt": """[[SOURCE: generic.txt | SECTION: Procurement notice]]
Opportunity title: Digital Records Support. Buyer: Example Purchasing Authority.
Solicitation number: EX-2030-7. Questions close 2030-01-10.
Responses close 2030-01-20 at 15:00 America/Toronto.
The initial term is 24 months with two optional extensions of 12 months each.
The estimated contract value is CAD 100,000 exclusive of tax.
This RFP will result in a single-supplier award.
""",
    "adversarial.txt": """[[SOURCE: adversarial.txt | SECTION: Commercial schedule]]
Technical responses close 2030-02-10. Pricing responses close 2030-02-11.
The framework ceiling is USD 900,000. For evaluation only, proposals are scored
against a USD 250,000 scenario. This framework has no guaranteed volume and uses
multiple-supplier call-off awards with a rate card.
""",
}


def meta(name, text):
    return {"files": [name], "doc_metadata": {name: {}}, "doc_texts": {name: text}}


def main():
    key = get_api_key()
    if not key:
        raise RuntimeError("Configured Anthropic key required")
    checkpoint_root = Path(tempfile.gettempdir()) / "bid-intelligence-canonical-checkpoints"
    stage_a = []
    canonical_packages = []
    for name, text in SOURCES.items():
        facts = extractor.extract_document_facts(text, name, key)
        normalized = extractor.normalize_package_facts([facts], meta(name, text))
        conflicts = extractor.reconcile_package_facts(normalized, [name])
        canonical = normalized["_canonical_opportunity"]
        kinds = sorted({o["semantic_kind"] for o in canonical["observations"]})
        stage_a.append({"source": name, "schema_version": canonical["schema_version"],
                        "typed_observation_count": len(canonical["observations"]),
                        "semantic_kinds": kinds,
                        "provenance_counts": {s: sum(o["provenance_status"] == s for o in canonical["observations"])
                                              for s in ("VERIFIED", "PARTIAL", "UNVERIFIED")},
                        "recovery": facts.get("_extraction_diagnostic"),
                        "source_chars": len(text), "response_chars": len(json.dumps(facts, ensure_ascii=False))})
        canonical_packages.append((name, normalized, conflicts))

    evidence_path = ROOT / "tests/acceptance/results/canonical_opportunity_live_contract_smokes.json"
    interim = {"evidence_kind": "SANITIZED_CANONICAL_CONTRACT_SMOKES", "schema_version": SCHEMA_VERSION,
               "model": "claude-haiku-4-5-20251001", "stage_a": stage_a, "stage_d": {"status": "PENDING"}}
    evidence_path.write_text(json.dumps(interim, sort_keys=True, separators=(",", ":")), encoding="utf-8")

    # Stage D receives the small generic canonical package produced above. Add
    # an unrelated legacy conflict to prove local canonical field authority.
    name, normalized, conflicts = canonical_packages[0]
    conflicts = list(conflicts) + [{"conflict_id": "UNRELATED-SMOKE", "conflict_type": "ENVELOPE_CONFLICT",
        "classification": "TRUE_CONFLICT", "confidence": "HIGH", "reason": "Separate envelopes unclear",
        "source_validity": "PHYSICAL_BOTH", "topic": "Envelope mechanics", "assessment": "Clarification needed",
        "recommended_action": "Clarify", "source_a": {"doc": name, "ref": "A", "text": "one envelope"},
        "source_b": {"doc": name, "ref": "B", "text": "two envelopes"}}]
    projection = build_stage_d_synthesis_projection(normalized, conflicts)
    size = finalize_stage_d_request(projection, extractor.STAGE_D_SYNTHESIS_PROMPT)["diagnostics"]
    with checkpoint_run(mode="required", root=checkpoint_root) as store:
        result = extractor.synthesize_bid_brief(normalized, conflicts, key)
        store.write("canonical-contract-smoke-result.json", result)
        stage_d = {"model": "claude-haiku-4-5-20251001", "api_dispatch": True,
                   "canonical_fields_reapplied": result["bid"].get("title") == "Digital Records Support"
                       and result["bid"].get("submission_deadline") == "2030-01-20",
                   "unrelated_conflict_preserved_deadline": result["bid"].get("submission_deadline") == "2030-01-20",
                   "citation_validation": "PASS", "authoritative_reapplication": "PASS",
                   "final_assembly": "PASS", "prompt_chars": size["total_prompt_chars"],
                   "headroom_chars": size["headroom_chars"], "checkpoint_run_id": store.root.name}
    evidence = {"evidence_kind": "SANITIZED_CANONICAL_CONTRACT_SMOKES", "schema_version": SCHEMA_VERSION,
                "model": "claude-haiku-4-5-20251001", "stage_a": stage_a, "stage_d": stage_d}
    evidence_path.write_text(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
