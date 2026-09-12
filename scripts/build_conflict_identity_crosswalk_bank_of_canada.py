"""Conflict identity crosswalk for the Bank of Canada RFP 2026-026
conflict-identity remediation. No Stage A rerun, no LLM calls -- rebuilds
only the deterministic Canonical Opportunity / Opportunity Structure ledgers
from the already-frozen Stage C facts, exactly as
scripts/diagnose_provenance_granularity_bank_of_canada.py already does.

Produces conflict_identity_crosswalk.json: for every entry in Stage C's
merged `conflicts` list (stage_c_conflicts.json), records whether it is a
GOVERNED conflict (published by Canonical Opportunity Publication under this
exact conflict_id) or an ADVISORY review item (extractor.
detect_document_conflicts / contract_hygiene.structured_*_conflicts'
ordinal, Stage-C-local output with no governed publication anywhere), plus
its participating observation/record ids, semantic family, and scope where
applicable.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PHASE3_RUN_ID = "phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8"
PHASE3_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase3_commissioning" / PHASE3_RUN_ID
CORPUS = ROOT / "evaluation/bank_of_canada_briefing_pack/corrected_procurement_corpus"

OUT = ROOT / "evaluation/bank_of_canada_briefing_pack/conflict_identity_remediation"
OUT.mkdir(parents=True, exist_ok=True)

from extractor import extract_document_with_metadata
from opportunity_structure import build_opportunity_structure

paths = sorted(p for p in CORPUS.rglob("*") if p.is_file())
package = [(p.relative_to(CORPUS).as_posix(), p.read_bytes()) for p in paths]
metadata = {"files": [], "doc_metadata": {}, "doc_texts": {}}
for name, payload in package:
    text, meta = extract_document_with_metadata(payload, name)
    metadata["files"].append(name); metadata["doc_metadata"][name] = meta; metadata["doc_texts"][name] = text

facts = json.loads((PHASE3_DIR / "stage_c_normalized_facts.json").read_text(encoding="utf-8"))
canonical = facts.get("_canonical_opportunity")
structure = build_opportunity_structure(facts, metadata)
stage_c_conflicts = json.loads((PHASE3_DIR / "stage_c_conflicts.json").read_text(encoding="utf-8"))

governed_conflicts_by_id = {c["conflict_id"]: c for c in canonical.get("conflicts", []) or []}
structure_conflicts_by_id = {c["conflict_id"]: c for c in structure.get("conflicts", []) or []}

crosswalk = []
for entry in stage_c_conflicts:
    conflict_id = entry.get("conflict_id")
    is_governed = conflict_id in governed_conflicts_by_id
    row = {
        "stage_c_conflict_id": conflict_id,
        "population": "GOVERNED" if is_governed else "ADVISORY",
        "conflict_type_or_semantic_kind": entry.get("conflict_type") or governed_conflicts_by_id.get(conflict_id, {}).get("semantic_kind"),
        "governed_conflict_id": conflict_id if is_governed else None,
        "canonical_opportunity_publication_object_id": conflict_id if is_governed else None,
        "opportunity_structure_representation_id": None,  # none of the 8 real conflicts are EVALUATION_CRITERION-role conflicts
        "affected_observation_ids": governed_conflicts_by_id.get(conflict_id, {}).get("affected_observation_ids") if is_governed else None,
        "scope": governed_conflicts_by_id.get(conflict_id, {}).get("scope") if is_governed else None,
        "citable_as_future_entity_evidence_used": is_governed,
        "legacy_display_only": not is_governed,
        "topic_or_reason": entry.get("topic") or entry.get("reason"),
    }
    crosswalk.append(row)

(OUT / "conflict_identity_crosswalk.json").write_text(
    json.dumps({
        "total_conflicts": len(crosswalk),
        "governed_count": sum(1 for r in crosswalk if r["population"] == "GOVERNED"),
        "advisory_count": sum(1 for r in crosswalk if r["population"] == "ADVISORY"),
        "opportunity_structure_own_conflicts_unrelated_to_conf_eval": [
            {"conflict_id": cid, "family": c["family"], "field": c["field"],
             "affected_record_ids": c["affected_record_ids"], "incompatible_values": c["incompatible_values"]}
            for cid, c in sorted(structure_conflicts_by_id.items())
        ],
        "rows": crosswalk,
    }, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

print("TOTAL", len(crosswalk))
print("GOVERNED", sum(1 for r in crosswalk if r["population"] == "GOVERNED"))
print("ADVISORY", sum(1 for r in crosswalk if r["population"] == "ADVISORY"))
print("OUT_DIR", str(OUT))
