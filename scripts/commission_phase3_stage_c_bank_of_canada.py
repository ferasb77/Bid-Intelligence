"""Phase 3 / Stage C commissioning: run the real production
`extractor.reconcile_package_facts()` (Stage C: conflict detection &
governance) exactly once against the persisted, fresh, REMEDIATED Stage B
normalized output for the authoritative 16-document Bank of Canada RFP
2026-026 corpus.

Neither Stage A (extract_document_facts) nor Stage B (normalize_package_facts)
is invoked. The remediated Phase 2 run's `stage_b_normalized_result.json` is
loaded unchanged and used as Stage C's `normalized_facts` input, verbatim.
The 2 records already quarantined into `_provenance_rejections` by the
remediation are never read by any Stage C code path (confirmed by code
inspection: reconcile_package_facts only reads requirements/dates/
evaluation_criteria/submission_rules/deliverables/commercial_clauses/
_contract_hygiene/_canonical_opportunity -- never _provenance_rejections),
so they structurally cannot re-enter Stage C.

No Stage D, Canonical Opportunity synthesis beyond Stage C's own resolution
pass, Opportunity Intelligence, Buyer Brief, Executive Opportunity Brief, or
Executive Briefing Pack is invoked.

Stage C is verified by code inspection to be fully deterministic with zero
LLM/API calls (detect_document_conflicts, structured_deliverable_conflicts,
resolve_canonical_opportunity, apply_legacy_conflict_fallback, and every
helper they call are pure Python -- no client.messages.create / get_
anthropic_client anywhere in this call graph).
"""
import copy, json, secrets, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PHASE1_RUN_ID = "phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5"
# NOTE: superseded during the Section-9 hardening investigation. The
# originally-authoritative phase2-boc-2026-026-stageb-20260912T111643Z-1da5ab
# was regenerated (same frozen Phase 1 / Stage A input, Stage A NOT rerun)
# after a proven Stage B structural defect was fixed (submission_rules
# cross-appendix merge silently discarded D1/D3's own page limits) -- see
# BANK_OF_CANADA_PHASE_3_STAGE_C_HARDENING_REPORT.md Section 0 for the
# full justification. This is the new authoritative Stage B artifact.
PHASE2_RUN_ID = "phase2-boc-2026-026-stageb-20260912T125051Z-91a22b"
PHASE1_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase1_commissioning" / PHASE1_RUN_ID
PHASE2_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase2_commissioning" / PHASE2_RUN_ID
MASTER_RFP_FILENAME = "RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf"
ORIGINAL_D2 = "OriginalRevision/RFP 2026-026 - Appendix D2 - Rated Criteria Response Form.docx"
REVISED_D2 = "Amendment1/RFP 2026-026 - Appendix D2 - Rated Criteria Response REVISED.docx"
RECOVERED_TRUNCATED_DOCS = {
    "abstract.pdf",
    "OriginalRevision/RFP 2026-026 - Appendix D1 - Rated criteria response form.docx",
    "OriginalRevision/RFP 2026-06 - Appendix G - Form of Agreement.docx",
    MASTER_RFP_FILENAME,
}

PHASE3_RUN_ID = f"phase3-boc-2026-026-stagec-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
OUT = ROOT / "evaluation/bank_of_canada_briefing_pack/phase3_commissioning" / PHASE3_RUN_ID
OUT.mkdir(parents=True, exist_ok=False)


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n",
                             encoding="utf-8")


from extractor import reconcile_package_facts

# --- 1. Input lock: load the persisted remediated Stage B output verbatim --

source_manifest = json.loads((PHASE1_DIR / "phase1_source_manifest.json").read_text(encoding="utf-8"))
package_files = [item["path"] for item in source_manifest["files"]]
assert len(package_files) == 16

normalized_facts = json.loads((PHASE2_DIR / "stage_b_normalized_result.json").read_text(encoding="utf-8"))
pristine = copy.deepcopy(normalized_facts)

input_lock = {
    "phase1_run_id": PHASE1_RUN_ID,
    "phase2_run_id": PHASE2_RUN_ID,
    "requirements": len(normalized_facts["requirements"]),
    "dates": len(normalized_facts["dates"]),
    "evaluation_criteria": len(normalized_facts["evaluation_criteria"]),
    "submission_rules": len(normalized_facts["submission_rules"]),
    "deliverables": len(normalized_facts["deliverables"]),
    "commercial_clauses": len(normalized_facts["commercial_clauses"]),
    "canonical_opportunity_observations": len(normalized_facts["_canonical_opportunity"]["observations"]),
    "provenance_rejections_present_in_input": len(normalized_facts.get("_provenance_rejections", [])),
    "stage_a_rerun": False,
    "stage_b_recomputed": "Stage B's own deterministic function was re-run against the SAME frozen "
                          "Phase 1 Stage A output (Stage A itself was never re-invoked) after a proven "
                          "Stage B structural defect was fixed; see the hardening report Section 0.",
}
expected = {"requirements": 427, "dates": 23, "evaluation_criteria": 83, "submission_rules": 68,
            "deliverables": 23, "commercial_clauses": 91, "canonical_opportunity_observations": 120,
            "provenance_rejections_present_in_input": 2}
mismatches = {k: (input_lock[k], v) for k, v in expected.items() if input_lock[k] != v}
if mismatches:
    raise RuntimeError(f"PHASE 2 INPUT LOCK: FAIL -- counts do not match the authoritative remediated "
                       f"Stage B run: {mismatches}")
save("input_lock.json", input_lock)
print("PHASE 2 INPUT LOCK: PASS")
print(json.dumps(input_lock, indent=2, sort_keys=True))

rejected_ids_before = {json.dumps(item, sort_keys=True) for item in normalized_facts.get("_provenance_rejections", [])}

# --- 2. Run Stage C exactly once --------------------------------------------

t0 = time.monotonic()
conflicts = reconcile_package_facts(normalized_facts, package_files)
stage_c_elapsed = round(time.monotonic() - t0, 6)

save("stage_c_conflicts.json", conflicts)
save("stage_c_canonical_opportunity_resolved.json", normalized_facts["_canonical_opportunity"])

# Confirm the 2 rejected records were never touched / never re-entered.
rejected_ids_after = {json.dumps(item, sort_keys=True) for item in normalized_facts.get("_provenance_rejections", [])}
provenance_rejections_untouched = (
    rejected_ids_before == rejected_ids_after
    and normalized_facts.get("_provenance_rejections") == pristine.get("_provenance_rejections")
)

run_metadata = {
    "phase3_run_id": PHASE3_RUN_ID,
    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    "git_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
    "git_working_tree_dirty": bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                                   capture_output=True, text=True).stdout.strip()),
    "input_phase2_run_id": PHASE2_RUN_ID,
    "production_entry_point": "scripts/commission_phase3_stage_c_bank_of_canada.py -> extractor.reconcile_package_facts()",
    "stage_c_functions": ["extractor.reconcile_package_facts", "extractor.detect_document_conflicts",
                          "contract_hygiene.structured_deliverable_conflicts",
                          "canonical_opportunity.resolve_canonical_opportunity",
                          "canonical_opportunity.apply_legacy_conflict_fallback"],
    "stage_c_elapsed_seconds": stage_c_elapsed,
    "llm_calls_made_this_run": 0,
    "model_used": None,
    "token_usage": "not applicable -- Stage C is fully deterministic; verified by code inspection "
                   "(no client.messages.create / get_anthropic_client anywhere in reconcile_package_facts, "
                   "detect_document_conflicts, structured_deliverable_conflicts, "
                   "resolve_canonical_opportunity, apply_legacy_conflict_fallback, or any function they call)",
    "api_cost": "not applicable, same reason",
    "provenance_rejections_untouched": provenance_rejections_untouched,
    "stage_a_rerun": False,
    "stage_b_recomputed": False,
}
save("run_metadata.json", run_metadata)
print(f"STAGE C EXECUTION: PASS. Elapsed: {stage_c_elapsed}s")

# --- 3. Conflict summary by type/classification -----------------------------
# NOTE: reconcile_package_facts() returns one flat list mixing TWO distinct
# conflict record shapes: the legacy/structured detector's shape (conflict_
# type, classification, source_a/source_b, ...) and canonical_opportunity's
# own shape (state, semantic_kind, affected_fields, incompatible_values,
# resolution_basis, ...) with no "conflict_type"/"classification" keys at
# all. Both are tabulated below, distinctly, rather than assumed uniform.

by_type = {}
by_classification = {}
for c in conflicts:
    if "conflict_type" in c:
        by_type.setdefault(c.get("conflict_type"), 0)
        by_type[c.get("conflict_type")] += 1
        by_classification.setdefault(c.get("classification"), 0)
        by_classification[c.get("classification")] += 1
    else:
        by_type.setdefault("CANONICAL_OPPORTUNITY_CONFLICT", 0)
        by_type["CANONICAL_OPPORTUNITY_CONFLICT"] += 1
        by_classification.setdefault(f"CANONICAL:{c.get('semantic_kind')}", 0)
        by_classification[f"CANONICAL:{c.get('semantic_kind')}"] += 1

canonical = normalized_facts["_canonical_opportunity"]
resolved_summary = {field: state.get("status") for field, state in canonical.get("resolved", {}).items()}
resolution_basis_summary = {field: state.get("resolution_basis") for field, state in canonical.get("resolved", {}).items()}

conflict_summary = {
    "total_conflicts_from_legacy_detector": len(conflicts) - len(canonical.get("conflicts", [])),
    "total_canonical_opportunity_conflicts": len(canonical.get("conflicts", [])),
    "total_conflicts_all_sources": len(conflicts),
    "by_conflict_type": by_type,
    "by_classification": by_classification,
    "canonical_resolved_field_status": resolved_summary,
    "canonical_resolved_field_basis": resolution_basis_summary,
    "supersession_relationships_applied": sum(
        1 for o in canonical["observations"] if o.get("supersession_state") == "SUPERSEDED"),
    "explicit_supersession_declarations_in_input": sum(
        1 for o in canonical["observations"] if o.get("supersession")),
}
save("conflict_summary.json", conflict_summary)

# --- 4. D2 original vs revised audit ----------------------------------------

def refs_docs(rec):
    return {ref.get("source_doc") for ref in (rec.get("source_refs") or []) if isinstance(ref, dict)}


def family_records_for(doc, family):
    return [r for r in normalized_facts.get(family, []) if doc in refs_docs(r)]


d2_audit = {"original_d2": {}, "revised_d2": {}, "semantic_matches": [], "conflicts_involving_either_d2": []}
for label, doc in (("original_d2", ORIGINAL_D2), ("revised_d2", REVISED_D2)):
    d2_audit[label] = {
        "requirements": [{"description": r.get("description"), "req_id": r.get("req_id")}
                         for r in family_records_for(doc, "requirements")],
        "submission_rules": [{"item": r.get("item")} for r in family_records_for(doc, "submission_rules")],
        "evaluation_criteria": [{"stage": r.get("stage"), "weight": r.get("weight")}
                                for r in family_records_for(doc, "evaluation_criteria")],
    }

orig_desc = {r.get("description") for r in family_records_for(ORIGINAL_D2, "requirements")}
rev_desc = {r.get("description") for r in family_records_for(REVISED_D2, "requirements")}
d2_audit["semantic_matches"] = sorted(orig_desc & rev_desc)
d2_audit["unique_to_original"] = sorted(orig_desc - rev_desc)
d2_audit["unique_to_revised"] = sorted(rev_desc - orig_desc)

obs_by_id = {o["observation_id"]: o for o in canonical["observations"]}
for c in conflicts:
    if "conflict_type" in c:
        docs = {c.get("source_a", {}).get("doc"), c.get("source_b", {}).get("doc")}
    else:
        docs = {obs_by_id[oid].get("source_doc") for oid in c.get("affected_observation_ids", []) if oid in obs_by_id}
    if docs & {ORIGINAL_D2, REVISED_D2}:
        d2_audit["conflicts_involving_either_d2"].append(c)

d2_supersession = [
    {"observation_id": o["observation_id"], "family": o["family"], "semantic_kind": o["semantic_kind"],
     "source_doc": o.get("source_doc"), "supersession": o.get("supersession"),
     "supersession_state": o.get("supersession_state")}
    for o in canonical["observations"]
    if o.get("source_doc") in (ORIGINAL_D2, REVISED_D2) or (o.get("supersession") or {}).get("source_refs")
       and any(ref.get("source_doc") in (ORIGINAL_D2, REVISED_D2) for ref in (o.get("supersession") or {}).get("source_refs", []))
]
d2_audit["canonical_observations_touching_d2"] = d2_supersession
save("d2_original_vs_revised_audit.json", d2_audit)

# --- 5. Conflict vs duplicate / corroboration audit -------------------------

conflict_vs_duplicate = {
    "true_conflicts": [c["conflict_id"] for c in conflicts if c.get("classification") == "TRUE_CONFLICT"],
    "review_items": [c["conflict_id"] for c in conflicts if c.get("classification") == "REVIEW_ITEM"],
    "canonical_conflicts": [c["conflict_id"] for c in canonical.get("conflicts", [])],
}
save("conflict_vs_duplicate_audit.json", conflict_vs_duplicate)

# --- 6. Master RFP conflict contribution ------------------------------------

def conflict_docs(c):
    if "conflict_type" in c:
        return {c.get("source_a", {}).get("doc"), c.get("source_b", {}).get("doc")}
    return {obs_by_id[oid].get("source_doc") for oid in c.get("affected_observation_ids", []) if oid in obs_by_id}


master_conflicts = [c for c in conflicts if MASTER_RFP_FILENAME in conflict_docs(c)]
master_canonical_obs = [o for o in canonical["observations"] if o.get("source_doc") == MASTER_RFP_FILENAME]
master_summary = {
    "conflicts_involving_master_rfp": [c["conflict_id"] for c in master_conflicts],
    "conflict_count": len(master_conflicts),
    "canonical_observations_from_master": len(master_canonical_obs),
    "canonical_observations_from_master_conflicted": sum(
        1 for o in master_canonical_obs if o["conflict_ids"]),
    "canonical_observations_from_master_superseded": sum(
        1 for o in master_canonical_obs if o.get("supersession_state") == "SUPERSEDED"),
}
save("master_rfp_conflict_contribution.json", master_summary)

# --- 7. Stage C validators --------------------------------------------------

warnings = []
seen_ids = set()
for c in conflicts:
    cid = c.get("conflict_id")
    if cid in seen_ids:
        warnings.append({"type": "DUPLICATE_CONFLICT_ID", "conflict_id": cid})
    seen_ids.add(cid)
    if "conflict_type" in c:
        src_a, src_b = c.get("source_a") or {}, c.get("source_b") or {}
        if not src_a or not src_b:
            warnings.append({"type": "FEWER_THAN_TWO_CANDIDATES", "conflict_id": cid})
        if src_a.get("text") == src_b.get("text") and src_a.get("doc") == src_b.get("doc"):
            warnings.append({"type": "IDENTICAL_VALUES_MASQUERADING_AS_CONFLICT", "conflict_id": cid})
        for side, src in (("a", src_a), ("b", src_b)):
            doc = src.get("doc")
            if doc and doc not in package_files:
                warnings.append({"type": "SOURCE_NOT_IN_EVIDENCE_UNIVERSE", "conflict_id": cid, "side": side, "doc": doc})
    else:
        if len(c.get("affected_observation_ids", [])) < 2:
            warnings.append({"type": "FEWER_THAN_TWO_CANDIDATES", "conflict_id": cid})
        values = c.get("incompatible_values", [])
        if len(values) < 2 or len({json.dumps(v, sort_keys=True) for v in values}) < 2:
            warnings.append({"type": "IDENTICAL_VALUES_MASQUERADING_AS_CONFLICT", "conflict_id": cid})
        for ref in c.get("source_refs", []) or []:
            doc = ref.get("source_doc") if isinstance(ref, dict) else None
            if doc and doc not in package_files:
                warnings.append({"type": "SOURCE_NOT_IN_EVIDENCE_UNIVERSE", "conflict_id": cid, "doc": doc})

for field, state in canonical.get("resolved", {}).items():
    if state.get("status") == "RESOLVED" and not state.get("resolution_basis"):
        warnings.append({"type": "RESOLVED_WITHOUT_GOVERNED_BASIS", "field": field})
    if state.get("status") != "CONFLICTED" and state.get("conflict_ids"):
        warnings.append({"type": "NON_CONFLICTED_STATUS_CARRYING_CONFLICT_IDS", "field": field})
    if state.get("status") == "RESOLVED" and state.get("value") is None:
        warnings.append({"type": "RESOLVED_WITH_NULL_VALUE", "field": field})

observation_ids = {o["observation_id"] for o in canonical["observations"]}
for field, state in canonical.get("resolved", {}).items():
    for oid in state.get("observation_ids", []):
        if oid not in observation_ids:
            warnings.append({"type": "DANGLING_OBSERVATION_ID", "field": field, "observation_id": oid})

superseded_by_map = {o["observation_id"]: o.get("superseded_by") for o in canonical["observations"]
                     if o.get("supersession_state") == "SUPERSEDED"}


def has_cycle():
    visiting, visited = set(), set()
    def visit(node):
        if node in visiting:
            return True
        if node in visited or node not in superseded_by_map:
            return False
        visiting.add(node)
        result = visit(superseded_by_map[node])
        visiting.discard(node)
        visited.add(node)
        return result
    return any(visit(node) for node in superseded_by_map)


if has_cycle():
    warnings.append({"type": "CIRCULAR_SUPERSESSION"})
if canonical["integrity_diagnostics"].get("collision_ids"):
    warnings.append({"type": "OBSERVATION_IDENTITY_COLLISION", "ids": canonical["integrity_diagnostics"]["collision_ids"]})
if canonical["integrity_diagnostics"].get("supersession_cycles"):
    warnings.append({"type": "SUPERSESSION_CYCLE_DETECTED_BY_PRODUCTION_CODE",
                     "ids": canonical["integrity_diagnostics"]["supersession_cycles"]})

save("stage_c_validation_warnings.json", warnings)
print(f"Validation warnings: {len(warnings)}")

# --- 8. Final summary --------------------------------------------------------

summary = {
    "phase3_run_id": PHASE3_RUN_ID,
    "phase2_run_id": PHASE2_RUN_ID,
    "total_conflicts": len(conflicts),
    "true_conflicts": by_classification.get("TRUE_CONFLICT", 0),
    "review_items": by_classification.get("REVIEW_ITEM", 0),
    "canonical_conflicts": len(canonical.get("conflicts", [])),
    "supersession_relationships_applied": conflict_summary["supersession_relationships_applied"],
    "explicit_supersession_declarations": conflict_summary["explicit_supersession_declarations_in_input"],
    "master_rfp_conflicts": len(master_conflicts),
    "d2_conflicts": len(d2_audit["conflicts_involving_either_d2"]),
    "validation_warnings": len(warnings),
    "provenance_rejections_untouched": provenance_rejections_untouched,
    "stage_c_elapsed_seconds": stage_c_elapsed,
}
save("summary.json", summary)
print(json.dumps(summary, indent=2, sort_keys=True))
print(f"PHASE 3 / STAGE C: PASS. Dumps at: {OUT.relative_to(ROOT)}")
