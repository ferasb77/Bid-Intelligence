"""Opportunity Structure boundary commissioning against the latest
canonical-term-fixed lineage.

Part 1: refresh Stage C (deterministic, zero LLM) from the latest
regenerated Stage B artifact, since the canonical-term audit changed
_canonical_opportunity's resolved state (contract_term now CONFLICTED,
procurement_model now RESOLVED) and therefore changed Stage C's own
conflicts list (title/client/file_number conflict_ids are content-addressed
over the observation set, which grew; a new contract_term conflict now
exists). This refresh does NOT rerun Stage A and does NOT change any of the
5 families (requirements/evaluation_criteria/commercial_clauses/
deliverables/submission_rules) Opportunity Structure itself reads -- those
were already verified byte-identical between the old and regenerated Stage B
artifacts.

Part 2: build the real production opportunity_structure.build_opportunity_structure()
from the latest regenerated Stage B + deterministically-reconstructed
package_metadata, and run every requested cross-reference audit.

Zero LLM calls anywhere in this script.
"""
import copy
import json
import secrets
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PHASE1_RUN_ID = "phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5"
PHASE2_RUN_ID = "phase2-boc-2026-026-stageb-canonterm-fix-20260912T142551Z-34a031"
PHASE3_OLD_RUN_ID = "phase3-boc-2026-026-stagec-20260912T130007Z-dd391b"
CANONOPP_RUN_ID = "canonopp-boc-2026-026-20260912T142551Z-34a031"
PHASE1_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase1_commissioning" / PHASE1_RUN_ID
PHASE2_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase2_commissioning" / PHASE2_RUN_ID
PHASE3_OLD_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase3_commissioning" / PHASE3_OLD_RUN_ID
CORPUS = ROOT / "evaluation/bank_of_canada_briefing_pack/corrected_procurement_corpus"
MASTER_RFP_FILENAME = "RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf"

PHASE3_RUN_ID = f"phase3-boc-2026-026-stagec-refresh-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
PHASE3_OUT = ROOT / "evaluation/bank_of_canada_briefing_pack/phase3_commissioning" / PHASE3_RUN_ID
PHASE3_OUT.mkdir(parents=True, exist_ok=False)

STRUCT_RUN_ID = f"oppstruct-boc-2026-026-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
OUT = ROOT / "evaluation/bank_of_canada_briefing_pack/opportunity_structure_commissioning" / STRUCT_RUN_ID
OUT.mkdir(parents=True, exist_ok=False)


def save(name, value, out=OUT):
    (out / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n",
                             encoding="utf-8")


from extractor import extract_document_with_metadata, reconcile_package_facts
from opportunity_structure import build_opportunity_structure, FAMILIES, SECTION_BY_FAMILY, CONFLICT_FIELDS_BY_FAMILY

t0 = time.monotonic()

# --- Part 1: Stage C refresh --------------------------------------------------

source_manifest = json.loads((PHASE1_DIR / "phase1_source_manifest.json").read_text(encoding="utf-8"))
package_files = [item["path"] for item in source_manifest["files"]]
assert len(package_files) == 16

stage_b = json.loads((PHASE2_DIR / "stage_b_normalized_result.json").read_text(encoding="utf-8"))
nf = copy.deepcopy(stage_b)
fresh_conflicts = reconcile_package_facts(nf, package_files)
save("stage_c_conflicts.json", fresh_conflicts, out=PHASE3_OUT)
save("stage_c_normalized_facts.json", nf, out=PHASE3_OUT)

old_conflicts = json.loads((PHASE3_OLD_DIR / "stage_c_conflicts.json").read_text(encoding="utf-8"))
old_eval = sorted((c for c in old_conflicts if c.get("conflict_type") == "EVALUATION_CONFLICT"), key=lambda c: c["conflict_id"])
new_eval = sorted((c for c in fresh_conflicts if c.get("conflict_type") == "EVALUATION_CONFLICT"), key=lambda c: c["conflict_id"])
stage_c_refresh_verification = {
    "old_run_id": PHASE3_OLD_RUN_ID, "new_run_id": PHASE3_RUN_ID,
    "old_total_conflicts": len(old_conflicts), "new_total_conflicts": len(fresh_conflicts),
    "evaluation_conflicts_stable": old_eval == new_eval,
    "old_evaluation_conflict_ids": [c["conflict_id"] for c in old_eval],
    "new_evaluation_conflict_ids": [c["conflict_id"] for c in new_eval],
    "reason_for_refresh": "title/client/file_number conflict_ids are content-addressed over the canonical "
                          "observation set, which grew after the contract-term provenance fix (more VERIFIED "
                          "observations correctly admitted); contract_term itself gained a new conflict; "
                          "procurement_model newly resolved. None of this touches the 5 families Opportunity "
                          "Structure reads, which remain byte-identical, but the conflict list itself is stale.",
}
save("stage_c_refresh_verification.json", stage_c_refresh_verification, out=PHASE3_OUT)

phase3_run_metadata = {
    "phase3_run_id": PHASE3_RUN_ID, "phase1_run_id": PHASE1_RUN_ID, "phase2_run_id": PHASE2_RUN_ID,
    "stage_a_rerun": False, "stage_b_regenerated_here": False, "llm_calls": 0,
    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
}
save("run_metadata.json", phase3_run_metadata, out=PHASE3_OUT)

# --- Part 2: reconstruct package_metadata (deterministic, no LLM) -----------

paths = sorted(p for p in CORPUS.rglob("*") if p.is_file())
package = [(p.relative_to(CORPUS).as_posix(), p.read_bytes()) for p in paths]
metadata = {"files": [], "doc_metadata": {}, "doc_texts": {}}
for name, payload in package:
    text, meta = extract_document_with_metadata(payload, name)
    metadata["files"].append(name)
    metadata["doc_metadata"][name] = meta
    metadata["doc_texts"][name] = text

# --- Part 3: build Opportunity Structure, twice, for determinism ------------

structure_1 = build_opportunity_structure(nf, metadata)
structure_2 = build_opportunity_structure(nf, metadata)
determinism = {
    "run1_input_digest": structure_1["input_digest"], "run2_input_digest": structure_2["input_digest"],
    "identical": structure_1 == structure_2,
    "record_order_stable": [r["record_id"] for r in structure_1["records"]] == [r["record_id"] for r in structure_2["records"]],
}
save("determinism_check.json", determinism)

structure = structure_1
save("opportunity_structure_full.json", structure)

records = structure["records"]
by_family = {}
for r in records:
    by_family.setdefault(r["family"], []).append(r)

# --- 6. Upstream accounting ---------------------------------------------------

accounting = {}
for family in sorted(FAMILIES):
    section = SECTION_BY_FAMILY[family]
    input_count = len(nf.get(section) or [])
    fam_records = by_family.get(family, [])
    grouped_count = sum(r["occurrence_count"] for r in fam_records)
    accounting[family] = {
        "section": section, "input_record_count": input_count,
        "structure_record_count": len(fam_records),
        "total_occurrences_absorbed": grouped_count,
        "accounted_for": grouped_count == input_count,
    }
save("upstream_accounting.json", accounting)

# --- 7. D1/D2/D3 scope regression check --------------------------------------

d123 = [r for r in by_family.get("SUBMISSION_RULE", [])
       if "rated criteria response form" in str(r["fields"].get("item", "")).lower()]
save("d1_d2_d3_scope_check.json", [{
    "record_id": r["record_id"], "item": r["fields"].get("item"), "details": r["fields"].get("details"),
    "source_refs_docs": sorted({ref.get("source_doc") for ref in r["source_refs"]}),
} for r in d123])

# --- 8. Contract-term scope safety text search -------------------------------

needles = ["12 weeks", "3 years", "three years", "contract duration", "engagement duration", "agreement term", "contract term"]
hits = []
for r in records:
    blob = json.dumps(r["fields"]).lower()
    for n in needles:
        if n in blob:
            hits.append({"record_id": r["record_id"], "family": r["family"], "needle": n,
                        "fields": r["fields"], "scope_bearing_keys": {k: v for k, v in r["fields"].items()
                                                                       if k in ("scope", "component", "category")}})
save("contract_term_text_search.json", hits)

# --- 9. Procurement model check ----------------------------------------------

mech_needles = ["multi-vendor", "call-off", "call off", "standing offer", "panel agreement", "single contract", "procurement model", "procurement mechanic"]
mech_hits = []
for r in records:
    blob = json.dumps(r["fields"]).lower()
    for n in mech_needles:
        if n in blob:
            mech_hits.append({"record_id": r["record_id"], "family": r["family"], "needle": n})
save("procurement_model_text_search.json", {
    "family_present_in_schema": False,
    "note": "opportunity_structure.py's FAMILIES set has no PROCUREMENT_MECHANIC-equivalent family; "
           "PROCUREMENT_MECHANIC typed_observations belong exclusively to canonical_opportunity.py.",
    "incidental_text_hits": mech_hits,
})

elapsed = round(time.monotonic() - t0, 3)
git_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
run_metadata = {
    "run_id": STRUCT_RUN_ID, "timestamp_utc": datetime.now(timezone.utc).isoformat(), "git_commit": git_commit or "unavailable",
    "phase1_run_id": PHASE1_RUN_ID, "phase2_run_id": PHASE2_RUN_ID, "phase3_refresh_run_id": PHASE3_RUN_ID,
    "canonical_opportunity_run_id": CANONOPP_RUN_ID,
    "production_entry_point": "opportunity_structure.build_opportunity_structure(stage_facts, package_metadata)",
    "stage_a_rerun": False, "llm_calls": 0, "api_cost": 0,
    "record_count": len(records), "conflict_count": len(structure["conflicts"]),
    "families_present": sorted(by_family.keys()),
    "elapsed_seconds": elapsed,
}
save("run_metadata.json", run_metadata)

print("OPPORTUNITY STRUCTURE COMMISSIONING")
print(json.dumps(run_metadata, indent=2))
print()
print("STAGE C REFRESH VERIFICATION:", json.dumps(stage_c_refresh_verification, indent=2))
print()
print("DETERMINISM:", json.dumps(determinism, indent=2))
print()
print("UPSTREAM ACCOUNTING:", json.dumps(accounting, indent=2))
print()
print("D1/D2/D3:", json.dumps(json.load(open(OUT / "d1_d2_d3_scope_check.json", encoding="utf-8")), indent=2))
print()
print("CONTRACT TERM TEXT SEARCH HITS:", len(hits))
for h in hits:
    print(' -', h['record_id'], h['family'], h['needle'], h['scope_bearing_keys'])
print()
print("PROCUREMENT MODEL: family present in schema =", False, "| incidental hits:", len(mech_hits))
print()
print(f"Structure dumps at: {OUT.relative_to(ROOT)}")
print(f"Stage C refresh at: {PHASE3_OUT.relative_to(ROOT)}")
