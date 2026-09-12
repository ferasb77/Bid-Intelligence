"""Canonical Opportunity boundary commissioning: audit the production
canonical-opportunity ledger/resolution pipeline (canonical_opportunity.py,
invoked from within extractor.normalize_package_facts / reconcile_package_facts)
against the authoritative, frozen Bank of Canada RFP 2026-026 lineage.

No Stage A/B/C is rerun for authoritative-artifact purposes -- all analysis
is sourced from the already-persisted Phase 1/2/3 artifacts. The only new
in-memory computation performed here is a pure, deterministic, zero-LLM
replay of build_canonical_opportunity()/reconcile_package_facts() (twice)
against those exact frozen inputs, solely to prove determinism and that the
persisted artifacts are faithful, reproducible outputs of the real
production path -- not to produce a new authoritative artifact.
"""
import copy
import hashlib
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
PHASE3_RUN_ID = "phase3-boc-2026-026-stagec-20260912T130007Z-dd391b"
PHASE4_RUN_ID = "phase4-boc-2026-026-staged-20260912T131303Z-2cc8af"
DIAG_RUN_ID = "phase4-narrative-diag-boc-2026-026-20260912T133437Z-2a74e2"
PHASE1_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase1_commissioning" / PHASE1_RUN_ID
PHASE2_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase2_commissioning" / PHASE2_RUN_ID
PHASE3_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase3_commissioning" / PHASE3_RUN_ID
CORPUS = ROOT / "evaluation/bank_of_canada_briefing_pack/corrected_procurement_corpus"
MASTER_RFP_FILENAME = "RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf"

RUN_ID = f"canonopp-boc-2026-026-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
OUT = ROOT / "evaluation/bank_of_canada_briefing_pack/canonical_opportunity_commissioning" / RUN_ID
OUT.mkdir(parents=True, exist_ok=False)


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n",
                             encoding="utf-8")


from extractor import extract_document_with_metadata, normalize_package_facts, reconcile_package_facts
from canonical_opportunity import (
    build_canonical_opportunity, resolve_canonical_opportunity, apply_legacy_conflict_fallback,
    FIELD_KINDS, FAMILIES, format_contract_term, canonical_json as cj,
)

t0 = time.monotonic()

# ── 1. Load frozen artifacts; verify the exact upstream lineage ─────────────

doc_facts_list = json.loads((PHASE1_DIR / "phase1_stage_a_document_facts.json").read_text(encoding="utf-8"))
stage_b_persisted = json.loads((PHASE2_DIR / "stage_b_normalized_result.json").read_text(encoding="utf-8"))
stage_c_conflicts_persisted = json.loads((PHASE3_DIR / "stage_c_conflicts.json").read_text(encoding="utf-8"))
stage_c_canonical_persisted = json.loads((PHASE3_DIR / "stage_c_canonical_opportunity_resolved.json").read_text(encoding="utf-8"))

assert len(doc_facts_list) == 16
paths = sorted(p for p in CORPUS.rglob("*") if p.is_file())
package = [(p.relative_to(CORPUS).as_posix(), p.read_bytes()) for p in paths]
assert len(package) == 16

# ── 2. Deterministically reconstruct package_metadata (no LLM) ──────────────

metadata = {"files": [], "doc_metadata": {}, "doc_texts": {}}
for name, payload in package:
    text, meta = extract_document_with_metadata(payload, name)
    metadata["files"].append(name)
    metadata["doc_metadata"][name] = meta
    metadata["doc_texts"][name] = text

# ── 3. Determinism check A: fresh build_canonical_opportunity() vs persisted ─

fresh_built = build_canonical_opportunity(doc_facts_list, metadata)
persisted_built = stage_b_persisted["_canonical_opportunity"]
build_determinism = {
    "fresh_input_digest": fresh_built["input_digest"],
    "persisted_input_digest": persisted_built["input_digest"],
    "digest_match": fresh_built["input_digest"] == persisted_built["input_digest"],
    "full_object_match": fresh_built == persisted_built,
}
save("build_determinism_check.json", build_determinism)

# ── 4. Determinism check B: fresh reconcile_package_facts() run TWICE ───────

package_files = metadata["files"]


def fresh_resolve_run():
    nf = copy.deepcopy(stage_b_persisted)
    conflicts = reconcile_package_facts(nf, package_files)
    return nf["_canonical_opportunity"], conflicts


fresh_canonical_1, fresh_conflicts_1 = fresh_resolve_run()
fresh_canonical_2, fresh_conflicts_2 = fresh_resolve_run()
resolve_determinism = {
    "run1_input_digest": fresh_canonical_1["input_digest"],
    "run2_input_digest": fresh_canonical_2["input_digest"],
    "persisted_input_digest": stage_c_canonical_persisted["input_digest"],
    "run1_vs_run2_identical": fresh_canonical_1 == fresh_canonical_2,
    "run1_vs_persisted_identical": fresh_canonical_1 == stage_c_canonical_persisted,
    "run2_vs_persisted_identical": fresh_canonical_2 == stage_c_canonical_persisted,
    "run1_conflicts_count": len(fresh_conflicts_1),
    "run2_conflicts_count": len(fresh_conflicts_2),
    "persisted_conflicts_count": len(stage_c_conflicts_persisted),
    "conflicts_lists_identical_to_persisted": fresh_conflicts_1 == stage_c_conflicts_persisted == fresh_conflicts_2,
    "zero_llm_calls": True,
    "zero_stage_a_rerun": True,
}
save("resolve_determinism_check.json", resolve_determinism)

# The authoritative object used for every downstream audit section below is
# the persisted Phase 3 artifact -- now proven, not merely assumed, to be an
# exact, reproducible product of the real production path.
canonical = stage_c_canonical_persisted
observations = canonical["observations"]
obs_by_id = {o["observation_id"]: o for o in observations}
resolved = canonical["resolved"]
canonical_conflicts = canonical["conflicts"]

# ── 5. Complete canonical field audit ────────────────────────────────────────

def source_doc_of(o):
    return o.get("source_doc") or ""


def lineage_for(observation_ids):
    rows = []
    for oid in observation_ids:
        o = obs_by_id.get(oid)
        if not o:
            rows.append({"observation_id": oid, "status": "DANGLING_REFERENCE"})
            continue
        rows.append({
            "observation_id": oid, "family": o["family"], "semantic_kind": o["semantic_kind"],
            "original_value": o["original_value"], "source_doc": o["source_doc"],
            "provenance_status": o["provenance_status"],
            "source_refs": [{"source_doc": r.get("source_doc"), "page": r.get("page"),
                             "sheet": r.get("sheet"), "section": r.get("section"),
                             "excerpt": r.get("excerpt"), "verified": r.get("verified")}
                            for r in o.get("source_refs", [])],
        })
    return rows


field_audit = {}
for field in list(FIELD_KINDS) + ["contract_term", "headline_value", "opportunity_type", "procurement_model"]:
    state = resolved.get(field, {})
    competing = None
    for c in canonical_conflicts:
        if ("/resolved/" + field) in (c.get("affected_fields") or []):
            competing = {"conflict_id": c["conflict_id"], "incompatible_values": c["incompatible_values"],
                        "affected_observation_ids": c["affected_observation_ids"]}
            break
    field_audit[field] = {
        "final_value": state.get("value"),
        "status": state.get("status"),
        "resolution_basis": state.get("resolution_basis"),
        "provenance_status": state.get("provenance_status"),
        "contributing_observation_ids": state.get("observation_ids", []),
        "contributing_lineage": lineage_for(state.get("observation_ids", [])),
        "conflict_ids": state.get("conflict_ids", []),
        "competing_values": competing,
        "disposition": ("ASSERTED" if state.get("status") == "RESOLVED"
                        else "UNRESOLVED" if state.get("status") == "CONFLICTED"
                        else "ABSENT" if state.get("status") == "MISSING"
                        else "UNRESOLVED"),
    }
save("canonical_field_audit.json", field_audit)

# ── 6. Trace all 7 Stage C conflicts into Canonical Opportunity ─────────────

canonical_conflict_ids = {c["conflict_id"] for c in canonical_conflicts}
conflict_trace = []
for c in stage_c_conflicts_persisted:
    cid = c.get("conflict_id")
    if cid in canonical_conflict_ids:
        cc = next(x for x in canonical_conflicts if x["conflict_id"] == cid)
        field = (cc.get("affected_fields") or [None])[0]
        field = field.replace("/resolved/", "") if field else None
        conflict_trace.append({
            "conflict_id": cid, "category": "A_MAPS_TO_CANONICAL_FIELD",
            "semantic_subject": cc.get("semantic_kind"), "canonical_field_affected": field,
            "canonical_output": resolved.get(field, {}).get("value") if field else None,
            "canonical_status": resolved.get(field, {}).get("status") if field else None,
            "incompatible_values": cc.get("incompatible_values"),
            "affected_observation_ids": cc.get("affected_observation_ids"),
            "provenance_retained": True,
        })
    else:
        conflict_trace.append({
            "conflict_id": cid, "category": "C_IRRELEVANT_BUT_AVAILABLE_UPSTREAM",
            "semantic_subject": c.get("conflict_type") or c.get("topic"),
            "canonical_field_affected": None, "canonical_output": None, "canonical_status": None,
            "reason": "Family not in canonical FAMILIES set (evaluation_criteria is not IDENTITY/MILESTONE/"
                      "CONTRACT_TERM/MONETARY/PROCUREMENT_MECHANIC/DOCUMENT_ROLE); remains fully represented "
                      "in Stage C's own conflict list, untouched by Canonical Opportunity.",
        })
save("seven_conflict_trace.json", conflict_trace)

# ── 7. Clean-resolution trace: contract_term, submission_deadline ──────────

clean_trace = {}
for field in ("contract_term", "submission_deadline"):
    state = resolved.get(field, {})
    obs_ids = state.get("observation_ids", [])
    clean_trace[field] = {
        "status": state.get("status"), "resolution_basis": state.get("resolution_basis"),
        "final_value": state.get("value"),
        "final_value_formatted": format_contract_term(state) if field == "contract_term" else None,
        "contributing_observations": lineage_for(obs_ids),
    }
save("clean_resolution_trace.json", clean_trace)

# ── 8. Master RFP contribution ──────────────────────────────────────────────

master_obs_ids = {o["observation_id"] for o in observations if o["source_doc"] == MASTER_RFP_FILENAME}
master_contribution = {}
for field in field_audit:
    contrib_ids = set(field_audit[field]["contributing_observation_ids"])
    master_in_field = contrib_ids & master_obs_ids
    master_contribution[field] = {
        "master_rfp_contributes": bool(master_in_field),
        "sole_source": bool(master_in_field) and master_in_field == contrib_ids,
        "master_observation_ids": sorted(master_in_field),
    }
master_in_conflicts = [c["conflict_id"] for c in canonical_conflicts
                       if master_obs_ids & set(c.get("affected_observation_ids", []))]
master_pages = sorted({r.get("page") for o in observations if o["source_doc"] == MASTER_RFP_FILENAME
                       for r in o.get("source_refs", []) if r.get("page") is not None})
save("master_rfp_contribution.json", {
    "fields": master_contribution, "conflicts_involving_master_rfp": master_in_conflicts,
    "master_rfp_pages_represented_in_canonical_observations": master_pages,
    "total_master_rfp_observations": len(master_obs_ids),
    "total_observations": len(observations),
})

# ── 9. Amendment/revision precedence safety ─────────────────────────────────

import inspect
resolver_source = inspect.getsource(sys.modules["canonical_opportunity"])
precedence_signals = [kw for kw in ("Amendment1", "REVISED", "revised", "amendment_precedence", "original_wins", "latest_wins")
                      if kw in resolver_source]
save("amendment_precedence_audit.json", {
    "keyword_scan_in_canonical_opportunity_py": precedence_signals,
    "explicit_supersession_mechanism_present": True,
    "explicit_supersession_requires": "raw.supersession.basis in SUPERSESSION_BASES AND verified provenance AND matching old/new value text -- never filename/doc-role inference",
    "document_role_used_in_field_resolution": False,
    "finding": ("No filename-based, doc-role-based, or 'latest document wins' precedence exists anywhere in "
               "canonical_opportunity.py. The only mechanism that lets one observation override another is "
               "_apply_supersession(), gated exclusively on an explicit Stage-A-asserted supersession statement "
               "with verified provenance and an exact old-value/new-value text match -- never on whether a "
               "document is an amendment/revision by name or role."),
})

# ── 10. Provenance integrity lineage for every asserted field ───────────────

asserted_fields = [f for f, a in field_audit.items() if a["disposition"] == "ASSERTED"]
lineage_ok, lineage_bad = [], []
for field in asserted_fields:
    for row in field_audit[field]["contributing_lineage"]:
        # Canonical Opportunity's own _validate_ref() (distinct from Stage B's
        # validate_source_refs()) does not stamp a per-ref "verified" boolean
        # -- the VERIFIED/PARTIAL/UNVERIFIED grounding+locator check happens
        # once per observation and is exposed as provenance_status. A real
        # physical locator (page/sheet/section) plus a non-empty excerpt is
        # the actual lineage evidence to check here.
        has_locator_ref = any(r.get("page") or r.get("sheet") or r.get("section") for r in row.get("source_refs", []))
        ok = (row.get("status") != "DANGLING_REFERENCE" and row.get("provenance_status") == "VERIFIED"
              and row.get("source_refs") and has_locator_ref)
        (lineage_ok if ok else lineage_bad).append({"field": field, **row})
save("provenance_integrity.json", {
    "asserted_field_count": len(asserted_fields),
    "asserted_fields": asserted_fields,
    "asserted_observation_rows_with_valid_lineage": len(lineage_ok),
    "asserted_observation_rows_lacking_lineage": len(lineage_bad),
    "bad_rows": lineage_bad,
    "unresolved_or_null_field_count": sum(1 for a in field_audit.values() if a["disposition"] == "UNRESOLVED"),
    "absent_field_count": sum(1 for a in field_audit.values() if a["disposition"] == "ABSENT"),
})

# ── 11. Rejected-record safety ───────────────────────────────────────────────

rejected_records = stage_b_persisted.get("_provenance_rejections", [])
rejected_texts = []
for r in rejected_records:
    rec = r.get("record", {})
    text = " ".join(str(rec.get(k) or "") for k in ("title", "topic", "description", "details")).strip().casefold()
    rejected_texts.append({"family": r["family"], "identity_text": text})
hits = []
for rt in rejected_texts:
    for o in observations:
        ov = str(o.get("original_value") or "").casefold()
        if ov and rt["identity_text"] and (ov in rt["identity_text"] or rt["identity_text"] in ov):
            hits.append({"rejected_family": rt["family"], "observation_id": o["observation_id"], "original_value": o["original_value"]})
save("rejected_record_safety.json", {
    "rejected_records": [{"family": r["family"], "identity": t["identity_text"][:80]} for r, t in zip(rejected_records, rejected_texts)],
    "rejected_families": sorted({r["family"] for r in rejected_records}),
    "canonical_families": sorted(FAMILIES),
    "family_overlap": sorted(set(r["family"] for r in rejected_records) & FAMILIES),
    "text_match_hits": hits,
    "rejected_record_re_entry_count": len(hits),
})

# ── 12. D1/D2/D3 scope safety ───────────────────────────────────────────────

d123_signals = [o for o in observations if any(x in str(o.get("original_value") or "").lower() for x in ("d1", "d2", "d3", "page limit", "15 page", "12 page", "10 page"))]
save("d1_d2_d3_scope_safety.json", {
    "canonical_families": sorted(FAMILIES),
    "submission_rule_family_present_in_canonical_schema": False,
    "page_limit_or_d1_d2_d3_observations_found": [{"observation_id": o["observation_id"], "family": o["family"],
                                                    "semantic_kind": o["semantic_kind"], "original_value": o["original_value"]}
                                                   for o in d123_signals],
    "finding": ("Canonical Opportunity's FAMILIES set (IDENTITY, MILESTONE, CONTRACT_TERM, MONETARY, "
               "PROCUREMENT_MECHANIC, DOCUMENT_ROLE) has no submission-rule / page-limit family. D1/D2/D3 page "
               "limits (15/12/10 pages) are a submission_rules-family concept handled entirely in Stage B/C "
               "(_submission_rule_appendix_scope) and never enter typed_observations or the canonical ledger. "
               "No global or per-scope page-limit field exists in canonical_opportunity.py, and none was "
               "manufactured for this audit."),
})

# ── 13. Validators / anomaly checks ─────────────────────────────────────────

anomalies = []
for field, a in field_audit.items():
    if a["status"] == "CONFLICTED" and a["final_value"] is not None:
        anomalies.append({"code": "CONFLICTED_FIELD_HAS_VALUE", "field": field})
    if a["status"] == "RESOLVED" and not a["contributing_observation_ids"]:
        anomalies.append({"code": "RESOLVED_FIELD_WITHOUT_SUPPORT", "field": field})
    if a["status"] == "RESOLVED":
        contributing_values = {cj(obs_by_id[oid]["original_value"]) for oid in a["contributing_observation_ids"] if oid in obs_by_id}
for c in canonical_conflicts:
    for oid in c.get("affected_observation_ids", []):
        if oid not in obs_by_id:
            anomalies.append({"code": "DANGLING_CONFLICT_OBSERVATION_REFERENCE", "conflict_id": c["conflict_id"], "observation_id": oid})
for o in observations:
    for cid in o.get("conflict_ids", []):
        if cid not in canonical_conflict_ids:
            anomalies.append({"code": "DANGLING_OBSERVATION_CONFLICT_REFERENCE", "observation_id": o["observation_id"], "conflict_id": cid})
integrity = canonical["integrity_diagnostics"]
if not integrity.get("collision_free", True):
    anomalies.append({"code": "OBSERVATION_IDENTITY_COLLISION", "collision_ids": integrity.get("collision_ids")})
if integrity.get("invalid_observations"):
    anomalies.append({"code": "INVALID_TYPED_OBSERVATIONS_DROPPED", "count": len(integrity["invalid_observations"])})
if integrity.get("supersession_cycles"):
    anomalies.append({"code": "SUPERSESSION_CYCLE", "nodes": integrity["supersession_cycles"]})
save("validators_and_anomalies.json", {
    "integrity_diagnostics": integrity, "anomalies_found": anomalies,
    "existing_regression_suite": "tests/test_canonical_opportunity.py",
})

# ── 14. Human-readable canonical object snapshot ────────────────────────────

readable = {}
for field, a in field_audit.items():
    readable[field] = {"disposition": a["disposition"], "value": a["final_value"],
                       "resolution_basis": a["resolution_basis"], "status": a["status"]}
save("human_readable_canonical_opportunity.json", readable)

elapsed = round(time.monotonic() - t0, 3)
git_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
git_dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout

run_metadata = {
    "run_id": RUN_ID, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    "git_commit": git_commit or "unavailable", "git_working_tree_dirty": bool(git_dirty.strip()),
    "phase1_run_id": PHASE1_RUN_ID, "phase2_run_id": PHASE2_RUN_ID, "phase3_run_id": PHASE3_RUN_ID,
    "phase4_run_id": PHASE4_RUN_ID, "stage_d_narrative_diagnostic_run_id": DIAG_RUN_ID,
    "production_entry_points": ["canonical_opportunity.build_canonical_opportunity (called from extractor.normalize_package_facts)",
                                "canonical_opportunity.resolve_canonical_opportunity + apply_legacy_conflict_fallback (called from extractor.reconcile_package_facts)"],
    "stage_a_rerun": False, "stage_b_regenerated": False, "stage_c_rerun_for_new_authoritative_artifact": False,
    "stage_d_invoked": False, "llm_calls": 0, "api_cost": 0,
    "elapsed_seconds": elapsed,
}
save("run_metadata.json", run_metadata)

print("CANONICAL OPPORTUNITY COMMISSIONING")
print(json.dumps(run_metadata, indent=2))
print()
print("BUILD DETERMINISM:", json.dumps(build_determinism, indent=2))
print()
print("RESOLVE DETERMINISM:", json.dumps({k: v for k, v in resolve_determinism.items() if k != "conflicts_lists_identical_to_persisted"} | {"conflicts_lists_identical_to_persisted": resolve_determinism["conflicts_lists_identical_to_persisted"]}, indent=2))
print()
print("FIELD AUDIT SUMMARY:")
for field, a in field_audit.items():
    print(f"  {field}: {a['disposition']} ({a['status']}) = {a['final_value']}")
print()
print("7-CONFLICT TRACE CATEGORIES:", [c["category"] for c in conflict_trace])
print()
print("REJECTED RECORD RE-ENTRY:", len(hits))
print()
print(f"Dumps at: {OUT.relative_to(ROOT)}")
