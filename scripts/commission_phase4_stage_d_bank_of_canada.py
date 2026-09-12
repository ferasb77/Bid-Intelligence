"""Phase 4 / Stage D commissioning: run the real production
`extractor.synthesize_bid_brief()` exactly once against the persisted,
hardened Stage C conflicts and the regenerated, remediated Stage B
normalized facts.

Neither Stage A, Stage B, nor Stage C is re-invoked. `stage_c_conflicts.json`
and the regenerated `stage_b_normalized_result.json` are loaded unchanged and
used verbatim as `reconcile_package_facts()`'s own output pair
(normalized_facts mutated by Stage C to carry the resolved
_canonical_opportunity, plus the conflicts list) would have been.

Stage D DOES invoke a real LLM (claude-haiku-4-5-20251001, per extractor.py),
with a bounded 2-attempt retry and extensive deterministic
evidence-ownership/citation validation (stage_d_projection.py). This run
captures whatever telemetry the production code actually exposes -- no
token/cost instrumentation exists beyond what is checkpointed.
"""
import copy, json, secrets, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PHASE1_RUN_ID = "phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5"
PHASE2_RUN_ID = "phase2-boc-2026-026-stageb-20260912T125051Z-91a22b"
PHASE3_RUN_ID = "phase3-boc-2026-026-stagec-20260912T130007Z-dd391b"
PHASE2_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase2_commissioning" / PHASE2_RUN_ID
PHASE3_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase3_commissioning" / PHASE3_RUN_ID
MASTER_RFP_FILENAME = "RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf"
RECOVERED_TRUNCATED_DOCS = {
    "abstract.pdf",
    "OriginalRevision/RFP 2026-026 - Appendix D1 - Rated criteria response form.docx",
    "OriginalRevision/RFP 2026-06 - Appendix G - Form of Agreement.docx",
    MASTER_RFP_FILENAME,
}

PHASE4_RUN_ID = f"phase4-boc-2026-026-staged-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
OUT = ROOT / "evaluation/bank_of_canada_briefing_pack/phase4_commissioning" / PHASE4_RUN_ID
OUT.mkdir(parents=True, exist_ok=False)


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n",
                             encoding="utf-8")


from config import get_api_key
from extractor import synthesize_bid_brief, StageDContextTooLargeError
from stage_d_projection import ProjectionValidationError

# --- 1. Input lock -----------------------------------------------------------

normalized_facts = json.loads((PHASE2_DIR / "stage_b_normalized_result.json").read_text(encoding="utf-8"))
conflicts = json.loads((PHASE3_DIR / "stage_c_conflicts.json").read_text(encoding="utf-8"))
canonical_resolved = json.loads((PHASE3_DIR / "stage_c_canonical_opportunity_resolved.json").read_text(encoding="utf-8"))
# reconcile_package_facts() mutates normalized_facts["_canonical_opportunity"]
# in place to the resolved copy; replay that exact mutation here since we are
# loading Stage B's pre-Stage-C snapshot and Stage C's own resolved output
# from two separate persisted files, not re-running reconcile_package_facts.
# NOTE: resolve_canonical_opportunity() legitimately mutates each conflicted
# observation's own conflict_ids list in place (_resolve_simple appends the
# new conflict_id to every contributing observation), so its own recomputed
# input_digest correctly differs from Stage B's pre-resolution digest -- that
# is expected, not an inconsistency. The real integrity check is that the
# two files describe the same underlying document/observation ledger.
assert normalized_facts["_canonical_opportunity"]["documents"] == canonical_resolved["documents"]
assert len(normalized_facts["_canonical_opportunity"]["observations"]) == len(canonical_resolved["observations"])
assert {o["observation_id"] for o in normalized_facts["_canonical_opportunity"]["observations"]} == \
       {o["observation_id"] for o in canonical_resolved["observations"]}
normalized_facts["_canonical_opportunity"] = canonical_resolved
pristine_rejections = copy.deepcopy(normalized_facts.get("_provenance_rejections", []))

input_lock = {
    "phase1_run_id": PHASE1_RUN_ID, "phase2_run_id": PHASE2_RUN_ID, "phase3_run_id": PHASE3_RUN_ID,
    "requirements": len(normalized_facts["requirements"]), "dates": len(normalized_facts["dates"]),
    "evaluation_criteria": len(normalized_facts["evaluation_criteria"]),
    "submission_rules": len(normalized_facts["submission_rules"]),
    "deliverables": len(normalized_facts["deliverables"]),
    "commercial_clauses": len(normalized_facts["commercial_clauses"]),
    "canonical_opportunity_observations": len(normalized_facts["_canonical_opportunity"]["observations"]),
    "provenance_rejections_present_in_input": len(normalized_facts.get("_provenance_rejections", [])),
    "total_conflicts": len(conflicts),
    "canonical_conflicts_in_normalized_facts": len(normalized_facts["_canonical_opportunity"]["conflicts"]),
    "stage_a_rerun": False, "stage_b_regenerated_here": False, "stage_c_rerun_here": False,
}
expected = {"requirements": 427, "dates": 23, "evaluation_criteria": 83, "submission_rules": 68,
            "deliverables": 23, "commercial_clauses": 91, "canonical_opportunity_observations": 120,
            "provenance_rejections_present_in_input": 2, "total_conflicts": 7}
mismatches = {k: (input_lock[k], v) for k, v in expected.items() if input_lock[k] != v}
if mismatches:
    raise RuntimeError(f"PHASE 3 INPUT LOCK: FAIL -- {mismatches}")
save("input_lock.json", input_lock)
print("PHASE 3 INPUT LOCK: PASS")
print(json.dumps(input_lock, indent=2, sort_keys=True))

# --- 2. Run Stage D exactly once ---------------------------------------------

key = get_api_key()
if not key:
    raise RuntimeError("ANTHROPIC_API_KEY is unavailable")

t0 = time.monotonic()
status = "PASS"
error_detail = None
try:
    result = synthesize_bid_brief(normalized_facts, conflicts, key)
except (ProjectionValidationError, StageDContextTooLargeError) as exc:
    status = "FAIL"
    error_detail = {"type": type(exc).__name__, "code": getattr(exc, "code", None), "message": str(exc)}
    result = None
stage_d_elapsed = round(time.monotonic() - t0, 3)

if result is not None:
    save("stage_d_synthesis_result.json", result)
save("stage_d_status.json", {"status": status, "error": error_detail, "elapsed_seconds": stage_d_elapsed})

rejections_untouched = normalized_facts.get("_provenance_rejections", []) == pristine_rejections

git_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
git_dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
run_metadata = {
    "phase4_run_id": PHASE4_RUN_ID, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    "git_commit": git_commit or "unavailable", "git_working_tree_dirty": bool(git_dirty.strip()),
    "input_phase2_run_id": PHASE2_RUN_ID, "input_phase3_run_id": PHASE3_RUN_ID,
    "production_entry_point": "scripts/commission_phase4_stage_d_bank_of_canada.py -> extractor.synthesize_bid_brief()",
    "stage_d_model": "claude-haiku-4-5-20251001", "stage_d_max_tokens": 8000, "stage_d_max_attempts": 2,
    "stage_d_context_char_limit": 580000,
    "token_usage": "not captured by the production code path -- extractor.py's Stage D client.messages.create() "
                   "call does not read/log response.usage anywhere in this call graph (same gap already "
                   "documented for Stage A in the Phase 1 report). Not fabricated here.",
    "api_cost": "not captured, same reason.",
    "stage_d_elapsed_seconds": stage_d_elapsed, "stage_d_status": status,
    "provenance_rejections_untouched": rejections_untouched,
}
save("run_metadata.json", run_metadata)
print(f"STAGE D EXECUTION: {status}. Elapsed: {stage_d_elapsed}s")
if status == "FAIL":
    print(json.dumps(error_detail, indent=2))
    print(f"Dumps at: {OUT.relative_to(ROOT)}")
    sys.exit(1)

# --- 3. Output inspection -----------------------------------------------------

brief = result["brief"]
counts = {
    "qualification_gates": len(brief.get("qualification_gates") or []),
    "evaluation_breakdown": len(brief.get("evaluation_breakdown") or []),
    "submission_requirements": len(brief.get("submission_requirements") or []),
    "key_dates": len(brief.get("key_dates") or []),
    "commercial_structure": len(brief.get("commercial_structure") or []),
    "contract_risks": len(brief.get("contract_risks") or []),
    "deliverables_summary": len(brief.get("deliverables_summary") or []),
    "outline": len(result.get("outline") or []),
    "citations": len(result.get("citations") or []),
}
save("output_counts.json", counts)

# --- 4. D1/D2/D3 page-limit trace --------------------------------------------

d1_d2_d3 = [item for item in brief.get("submission_requirements", [])
           if "rated criteria response form" in (item.get("item") or "").lower()]
save("d1_d2_d3_page_limit_trace.json", d1_d2_d3)

# --- 5. Master RFP contribution ----------------------------------------------

def refs_docs(item):
    return {ref.get("source_doc") for ref in (item.get("source_refs") or []) if isinstance(ref, dict)}


master_support = {"qualification_gates": [], "evaluation_breakdown": [], "submission_requirements": [],
                  "key_dates": [], "commercial_structure": [], "deliverables_summary": []}
for section in master_support:
    for item in brief.get(section) or []:
        docs = refs_docs(item)
        if not docs and item.get("rfp_ref"):
            docs = {item["rfp_ref"]}
        if not docs and item.get("source_doc"):
            docs = {item["source_doc"]}
        if MASTER_RFP_FILENAME in docs:
            master_support[section].append({"identity": item.get("requirement") or item.get("stage")
                                            or item.get("item") or item.get("milestone") or item.get("topic")
                                            or item.get("title"), "sole_source": docs == {MASTER_RFP_FILENAME}})
save("master_rfp_contribution.json", {
    section: {"count": len(items), "sole_source_count": sum(1 for i in items if i["sole_source"])}
    for section, items in master_support.items()
})

# --- 6. RECOVERED_TRUNCATED lineage -------------------------------------------

lineage = {"exclusively_clean": 0, "mixed": 0, "exclusively_truncated": 0, "no_source_doc": 0}
for section in ("qualification_gates", "submission_requirements", "key_dates", "commercial_structure",
               "deliverables_summary"):
    for item in brief.get(section) or []:
        docs = refs_docs(item)
        if not docs and item.get("source_doc"):
            docs = {item["source_doc"]}
        if not docs:
            lineage["no_source_doc"] += 1
            continue
        truncated_hit = bool(docs & RECOVERED_TRUNCATED_DOCS)
        clean_hit = bool(docs - RECOVERED_TRUNCATED_DOCS)
        if truncated_hit and clean_hit:
            lineage["mixed"] += 1
        elif truncated_hit:
            lineage["exclusively_truncated"] += 1
        else:
            lineage["exclusively_clean"] += 1
save("recovered_truncated_lineage.json", lineage)

# --- 7. Upstream-to-downstream accounting ------------------------------------

accounting = {
    "requirements": {"input": len(normalized_facts["requirements"]),
                     "qualification_gates_output": counts["qualification_gates"]},
    "dates": {"input": len(normalized_facts["dates"]), "key_dates_output": counts["key_dates"]},
    "evaluation_criteria": {"input": len(normalized_facts["evaluation_criteria"]),
                            "evaluation_breakdown_output": counts["evaluation_breakdown"]},
    "submission_rules": {"input": len(normalized_facts["submission_rules"]),
                         "submission_requirements_output": counts["submission_requirements"]},
    "deliverables": {"input": len(normalized_facts["deliverables"]),
                     "deliverables_summary_output": counts["deliverables_summary"]},
    "commercial_clauses": {"input": len(normalized_facts["commercial_clauses"]),
                           "commercial_structure_output": counts["commercial_structure"]},
    "canonical_observations": {"input": len(normalized_facts["_canonical_opportunity"]["observations"]),
                               "note": "not directly projected into brief sections; feeds bid/brief scalar "
                                       "fields (title/client/file_number/dates/contract_term/opportunity_type/"
                                       "procurement_model) via apply_authoritative_values"},
    "conflicts": {"input": len(conflicts), "note": "not projected as a brief section; feeds prompt context "
                                                    "and the AUTHORITATIVE bid/brief scalar overrides"},
}
save("upstream_downstream_accounting.json", accounting)

# --- 8. Bid/brief scalar disposition (unresolved-conflict representation) ---

canonical_field_disposition = {
    field: normalized_facts["_canonical_opportunity"]["resolved"].get(field, {}).get("status")
    for field in ("title", "client", "file_number", "submission_deadline", "clarification_deadline",
                 "contract_term", "headline_value", "opportunity_type", "procurement_model")
}
bid_brief_scalars = {"bid": result.get("bid"), "brief_scalars": {k: brief.get(k) for k in
    ("executive_summary", "opportunity_type", "contract_term", "procurement_model", "scope_categories")}}
save("canonical_field_disposition_and_output.json", {
    "canonical_resolved_status": canonical_field_disposition,
    "stage_d_bid_brief_output": bid_brief_scalars,
})

# --- 9. Evaluation-breakdown conflict representation (the 4 REVIEW_ITEMs) ---

eval_conflict_records = [item for item in brief.get("evaluation_breakdown", [])
                         if item.get("weight_conflict") is True]
save("evaluation_conflict_representation.json", eval_conflict_records)

print(json.dumps(counts, indent=2, sort_keys=True))
print(f"PHASE 4 / STAGE D: {status}. Dumps at: {OUT.relative_to(ROOT)}")
