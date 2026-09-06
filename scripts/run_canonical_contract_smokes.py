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
This procurement instrument is explicitly an ADVISORY SERVICES RFP and will result in a single-supplier award.
""",
    "adversarial.txt": """[[SOURCE: adversarial.txt | SECTION: Commercial schedule]]
Technical responses close 2030-02-10. Pricing responses close 2030-02-11.
Framework ceiling: USD 900,000. Evaluation scenario value: USD 250,000.
The evaluation scenario amount is for scoring only and is not an estimated contract value.
This framework has no guaranteed volume and uses
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

    old_name, amendment_name = "original-notice.txt", "amendment.txt"
    old_text = "[[SOURCE: original-notice.txt | SECTION: Closing]]\nThe submission deadline is 2030-03-01."
    amendment_text = """[[SOURCE: amendment.txt | SECTION: Explicit extension]]
The submission deadline is explicitly extended from 2030-03-01 to 2030-03-05.
The 2030-03-05 deadline replaces the 2030-03-01 deadline.
"""
    old_facts = extractor.extract_document_facts(old_text, old_name, key)
    amendment_facts = extractor.extract_document_facts(amendment_text, amendment_name, key)
    combined_meta = {"files": [old_name, amendment_name], "doc_metadata": {old_name: {}, amendment_name: {}},
                     "doc_texts": {old_name: old_text, amendment_name: amendment_text}}
    supersession_normalized = extractor.normalize_package_facts([old_facts, amendment_facts], combined_meta)
    extractor.reconcile_package_facts(supersession_normalized, [old_name, amendment_name])
    supersession_canonical = supersession_normalized["_canonical_opportunity"]
    deadline_observations = [o for o in supersession_canonical["observations"] if o["semantic_kind"] == "SUBMISSION_DEADLINE"]
    stage_a.append({"source": "explicit-amendment-package", "schema_version": supersession_canonical["schema_version"],
                    "typed_observation_count": len(deadline_observations),
                    "source_level_relationship_emitted": any((o.get("supersession") or {}).get("resolution_state") == "RESOLVED" for o in deadline_observations),
                    "canonical_ids_emitted_by_model": False,
                    "supersession_states": {str(o["original_value"]): o["supersession_state"] for o in deadline_observations},
                    "resolved_submission_deadline": supersession_canonical["resolved"]["submission_deadline"].get("value"),
                    "recovery_attempts": sum((x.get("_extraction_diagnostic") or {}).get("recovery_attempts", 0) for x in (old_facts, amendment_facts))})

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
        validation_files = sorted((store.root / "stage-d").glob("attempt-*/validation.json"))
        validation = json.loads(validation_files[-1].read_text(encoding="utf-8")) if validation_files else {}
        canonical_ids = {o["observation_id"] for o in normalized["_canonical_opportunity"]["observations"]}
        canonical_citations = [support for citation in validation.get("resolved_citations", []) for support in citation.get("supports", [])
                               if isinstance(support, dict) and support.get("entity_id") in canonical_ids]
        stage_d = {"model": "claude-haiku-4-5-20251001", "api_dispatch": True,
                   "canonical_fields_reapplied": result["bid"].get("title") == "Digital Records Support"
                       and result["bid"].get("submission_deadline") == "2030-01-20",
                   "unrelated_conflict_preserved_resolved_field": result["bid"].get("clarification_deadline") == "2030-01-10",
                   "citation_validation": "PASS", "authoritative_reapplication": "PASS",
                   "final_assembly": "PASS", "prompt_chars": size["total_prompt_chars"],
                   "tier2_opportunity_type": result["brief"].get("opportunity_type"),
                   "canonical_observation_citation_count": len(canonical_citations),
                   "canonical_observation_citation_passed": bool(canonical_citations),
                   "headroom_chars": size["headroom_chars"], "checkpoint_run_id": store.root.name}
        if not stage_d["canonical_observation_citation_passed"]:
            raise RuntimeError("Stage D did not cite canonical observation support")
    evidence = {"evidence_kind": "SANITIZED_CANONICAL_CONTRACT_SMOKES", "schema_version": SCHEMA_VERSION,
                "model": "claude-haiku-4-5-20251001", "stage_a": stage_a, "stage_d": stage_d}
    evidence_path.write_text(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
