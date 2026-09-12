"""Canonical Opportunity contract-term candidacy and scope audit.

Investigates why the opportunity-wide 3-year contract-term observations
(abstract.pdf, the master RFP) were excluded from contract_term candidacy
while a 12-week, HR-Advisory-scoped observation was admitted. Root-causes
the exclusion, fixes canonical_opportunity.py at the smallest scope if the
exclusion is proven to be a defect (not a genuine provenance gap), and -- if
the fix changes canonical build output -- regenerates Stage B's
_canonical_opportunity sub-object deterministically (zero LLM, same frozen
Stage A facts) since observation-level provenance_status is computed once at
build time and cannot be refreshed by re-resolving a stale build.

No Stage A call. No LLM. No change to any Stage B family other than
_canonical_opportunity (verified explicitly below).
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
PHASE2_RUN_ID = "phase2-boc-2026-026-stageb-20260912T125051Z-91a22b"
PHASE1_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase1_commissioning" / PHASE1_RUN_ID
PHASE2_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase2_commissioning" / PHASE2_RUN_ID
CORPUS = ROOT / "evaluation/bank_of_canada_briefing_pack/corrected_procurement_corpus"
PRIOR_CANONICAL_RUN_ID = "canonopp-boc-2026-026-20260912T135357Z-060143"

RUN_ID = f"canonopp-boc-2026-026-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
OUT = ROOT / "evaluation/bank_of_canada_briefing_pack/canonical_opportunity_commissioning" / RUN_ID
OUT.mkdir(parents=True, exist_ok=False)
STAGE_B_REGEN_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase2_commissioning" / f"phase2-boc-2026-026-stageb-canonterm-fix-{RUN_ID.split('-', 4)[-1]}"


def save(name, value, out=OUT):
    (out / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n",
                             encoding="utf-8")


from extractor import extract_document_with_metadata, normalize_package_facts, reconcile_package_facts
from canonical_opportunity import FIELD_KINDS, format_contract_term

doc_facts_list = json.loads((PHASE1_DIR / "phase1_stage_a_document_facts.json").read_text(encoding="utf-8"))
stage_b_before = json.loads((PHASE2_DIR / "stage_b_normalized_result.json").read_text(encoding="utf-8"))

paths = sorted(p for p in CORPUS.rglob("*") if p.is_file())
package = [(p.relative_to(CORPUS).as_posix(), p.read_bytes()) for p in paths]
metadata = {"files": [], "doc_metadata": {}, "doc_texts": {}}
for name, payload in package:
    text, meta = extract_document_with_metadata(payload, name)
    metadata["files"].append(name)
    metadata["doc_metadata"][name] = meta
    metadata["doc_texts"][name] = text

# --- 1. Regenerate Stage B deterministically (fixed canonical_opportunity.py) --

t0 = time.monotonic()
stage_b_after = normalize_package_facts(doc_facts_list, metadata)
build_elapsed = round(time.monotonic() - t0, 3)

STAGE_B_REGEN_DIR.mkdir(parents=True, exist_ok=True)
save("stage_b_normalized_result.json", stage_b_after, out=STAGE_B_REGEN_DIR)

# Verify the fix's blast radius: every OTHER Stage B family must be byte-identical.
non_canonical_keys = [k for k in stage_b_before if k != "_canonical_opportunity"]
ripple = {k: (stage_b_before[k] == stage_b_after[k]) for k in non_canonical_keys}
save("stage_b_ripple_check.json", {
    "keys_checked": non_canonical_keys,
    "all_other_families_unchanged": all(ripple.values()),
    "per_key": ripple,
})

# --- 2. Full contract_term candidate inventory (before vs after) -------------

def contract_term_observations(canonical):
    return [o for o in canonical["observations"] if o["family"] == "CONTRACT_TERM"]


def candidate_row(o, terms_used_in_resolution):
    return {
        "observation_id": o["observation_id"], "source_doc": o["source_doc"],
        "semantic_kind": o["semantic_kind"], "original_value": o["original_value"],
        "normalized_value": o["normalized_value"], "normalization_state": o["normalization_state"],
        "scope": o["scope"], "provenance_status": o["provenance_status"],
        "supersession_state": o["supersession_state"], "source_refs": o["source_refs"],
        "admitted_to_resolution_candidacy": o["observation_id"] in terms_used_in_resolution,
    }


before_obs = contract_term_observations(stage_b_before["_canonical_opportunity"])
after_obs = contract_term_observations(stage_b_after["_canonical_opportunity"])
before_ids_by_prov = {o["observation_id"]: o["provenance_status"] for o in before_obs}
after_ids_by_prov = {o["observation_id"]: o["provenance_status"] for o in after_obs}

save("contract_term_observation_provenance_before_after.json", {
    "before": before_ids_by_prov, "after": after_ids_by_prov,
    "changed": {oid: {"before": before_ids_by_prov.get(oid), "after": after_ids_by_prov.get(oid)}
               for oid in after_ids_by_prov if before_ids_by_prov.get(oid) != after_ids_by_prov.get(oid)},
})

# --- 3. Run Stage C (reconcile_package_facts) on the regenerated Stage B -----

package_files = metadata["files"]


def resolve(stage_b_snapshot):
    nf = copy.deepcopy(stage_b_snapshot)
    conflicts = reconcile_package_facts(nf, package_files)
    return nf["_canonical_opportunity"], conflicts


canonical_before, conflicts_before = resolve(stage_b_before)
canonical_after_1, conflicts_after_1 = resolve(stage_b_after)
canonical_after_2, conflicts_after_2 = resolve(stage_b_after)  # determinism check

resolve_determinism = {
    "after_run1_vs_run2_identical": canonical_after_1 == canonical_after_2,
    "after_run1_input_digest": canonical_after_1["input_digest"],
    "after_run2_input_digest": canonical_after_2["input_digest"],
    "conflicts_run1_vs_run2_identical": conflicts_after_1 == conflicts_after_2,
}
save("resolve_determinism_after_fix.json", resolve_determinism)

terms_after_ids = set(canonical_after_1["resolved"]["contract_term"].get("observation_ids", []))
terms_before_ids = set(canonical_before["resolved"]["contract_term"].get("observation_ids", []))

candidate_inventory = {
    "before": [candidate_row(o, terms_before_ids) for o in before_obs],
    "after": [candidate_row(o, terms_after_ids) for o in after_obs],
}
save("contract_term_candidate_inventory.json", candidate_inventory)

# --- 4. Before/after summary --------------------------------------------------

def summarize(canonical, conflicts):
    ct = canonical["resolved"]["contract_term"]
    obs = contract_term_observations(canonical)
    return {
        "candidate_count_total": len(obs),
        "verified_count": sum(1 for o in obs if o["provenance_status"] == "VERIFIED"),
        "opportunity_wide_candidates": sum(1 for o in obs if not o["scope"] and o["provenance_status"] == "VERIFIED"),
        "scoped_candidates": sum(1 for o in obs if o["scope"] and o["provenance_status"] == "VERIFIED"),
        "rejected_candidate_count": sum(1 for o in obs if o["provenance_status"] != "VERIFIED"),
        "contract_term_status": ct["status"],
        "contract_term_resolution_basis": ct.get("resolution_basis"),
        "contract_term_value": ct.get("value"),
        "contract_term_formatted": format_contract_term(ct),
        "conflict_count": len(conflicts),
        "conflicted_canonical_fields": [f for f, r in canonical["resolved"].items() if r.get("status") == "CONFLICTED"],
    }


before_summary = summarize(canonical_before, conflicts_before)
after_summary = summarize(canonical_after_1, conflicts_after_1)
save("before_after_summary.json", {"before": before_summary, "after": after_summary})

# --- 5. Full canonical field audit (post-fix), all 9 fields ------------------

resolved_after = canonical_after_1["resolved"]
field_audit_after = {}
for field in list(FIELD_KINDS) + ["contract_term", "headline_value", "opportunity_type", "procurement_model"]:
    state = resolved_after.get(field, {})
    field_audit_after[field] = {
        "status": state.get("status"), "value": state.get("value"),
        "resolution_basis": state.get("resolution_basis"),
        "provenance_status": state.get("provenance_status"),
        "observation_ids": state.get("observation_ids", []),
    }
save("canonical_field_audit_after_fix.json", field_audit_after)

# provenance-valid asserted-field count, post-fix
asserted_after = [f for f, a in field_audit_after.items() if a["status"] == "RESOLVED"]
save("provenance_summary_after_fix.json", {
    "asserted_field_count": len(asserted_after), "asserted_fields": asserted_after,
})

# --- 6. Rejected-record safety, re-verified post-fix --------------------------

rejected_records = stage_b_after.get("_provenance_rejections", [])
rejected_texts = [" ".join(str((r.get("record") or {}).get(k) or "") for k in ("title", "topic", "description", "details")).strip().casefold()
                  for r in rejected_records]
hits = []
for rt, rr in zip(rejected_texts, rejected_records):
    for o in canonical_after_1["observations"]:
        ov = str(o.get("original_value") or "").casefold()
        if ov and rt and (ov in rt or rt in ov):
            hits.append({"rejected_family": rr["family"], "observation_id": o["observation_id"]})
save("rejected_record_safety_after_fix.json", {"rejected_record_re_entry_count": len(hits), "hits": hits})

elapsed = round(time.monotonic() - t0, 3)
git_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
run_metadata = {
    "run_id": RUN_ID, "timestamp_utc": datetime.now(timezone.utc).isoformat(), "git_commit": git_commit or "unavailable",
    "phase1_run_id": PHASE1_RUN_ID, "phase2_run_id_before": PHASE2_RUN_ID,
    "phase2_run_id_regenerated": STAGE_B_REGEN_DIR.name, "prior_canonical_commissioning_run_id": PRIOR_CANONICAL_RUN_ID,
    "stage_a_rerun": False, "llm_calls": 0, "api_cost": 0,
    "stage_b_regeneration_reason": "canonical_opportunity.py provenance-validation defect fix changes observation-level "
                                   "provenance_status, which is computed once at build_canonical_opportunity() time and "
                                   "cannot be refreshed by re-resolving a stale, pre-fix Stage B artifact.",
    "stage_b_non_canonical_families_unchanged": all(ripple.values()),
    "elapsed_seconds": elapsed,
}
save("run_metadata.json", run_metadata)

print("CANONICAL CONTRACT-TERM AUDIT")
print(json.dumps(run_metadata, indent=2))
print()
print("STAGE B RIPPLE CHECK (all other families unchanged?):", all(ripple.values()))
print()
print("BEFORE:", json.dumps(before_summary, indent=2, default=str))
print()
print("AFTER:", json.dumps(after_summary, indent=2, default=str))
print()
print("RESOLVE DETERMINISM (after fix, run twice):", json.dumps(resolve_determinism, indent=2))
print()
print("REJECTED RECORD RE-ENTRY (after fix):", len(hits))
print()
print(f"Dumps at: {OUT.relative_to(ROOT)}")
print(f"Regenerated Stage B at: {STAGE_B_REGEN_DIR.relative_to(ROOT)}")
