"""
Fresh British Council Benchmark Replay focusing on Evaluation Hierarchy & Weighting Integrity.
Runs Stage A -> Stage B -> Stage C -> Stage D against committed code at REPLAY_CODE_SHA.
Source files:
1. itt_-_ir67tvet42026_-_smart_classroom_setup_-_updated.pdf
2. annex_2_-_procurement_specific_questionnaire_1.docx
Outputs: tests/acceptance/results/bc_evaluation_hierarchy_replay.json
"""
import pathlib
import sys
import time
import json
import hashlib
import datetime
import subprocess

PROJECT_ROOT = pathlib.Path(r"C:\Users\feras\Documents\Projects\Bid-Intelligence")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
import extractor
import evaluation_hierarchy

api_key = config.get_api_key()
if not api_key:
    raise RuntimeError("No Anthropic API key found in configuration.")

# Provenance: code_sha
git_proc = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    cwd=str(PROJECT_ROOT),
    capture_output=True,
    text=True,
    check=True
)
code_sha = git_proc.stdout.strip()

run_started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
model_name = "claude-haiku-4-5-20251001"

fixture_dir = PROJECT_ROOT / "tests" / "fixtures" / "local" / "british_council_ir67tvet42026"
p_itt = fixture_dir / "itt_-_ir67tvet42026_-_smart_classroom_setup_-_updated.pdf"
p_a2 = fixture_dir / "annex_2_-_procurement_specific_questionnaire_1.docx"

h_itt = hashlib.sha256(p_itt.read_bytes()).hexdigest()
h_a2 = hashlib.sha256(p_a2.read_bytes()).hexdigest()

print("=" * 70)
print(f"BRITISH COUNCIL EVALUATION HIERARCHY REPLAY - {run_started_at}")
print(f"Code SHA: {code_sha}")
print(f"Model: {model_name}")
print("=" * 70)

# Preprocessing
t0 = time.perf_counter()
t_itt, meta_itt = extractor.extract_document_with_metadata(p_itt.read_bytes(), p_itt.name)
t_a2, meta_a2 = extractor.extract_document_with_metadata(p_a2.read_bytes(), p_a2.name)

package_meta = {
    "files": [p_itt.name, p_a2.name],
    "doc_metadata": {p_itt.name: meta_itt, p_a2.name: meta_a2},
    "doc_texts": {p_itt.name: t_itt, p_a2.name: t_a2},
}
print(f"Preprocessed in {time.perf_counter() - t0:.2f}s")
print(f"  {p_itt.name}: {len(t_itt)} chars (SHA-256: {h_itt})")
print(f"  {p_a2.name}: {len(t_a2)} chars (SHA-256: {h_a2})")

# Stage A: Extract document facts
print("\n--- Running Stage A Extraction ---")
t0 = time.perf_counter()
print(f"Extracting {p_itt.name} via {model_name}...")
facts_itt = extractor.extract_document_facts(t_itt, p_itt.name, api_key=api_key)
raw_eval_itt = len(facts_itt.get("evaluation_criteria", []))
print(f"  ITT extracted: {len(facts_itt.get('requirements', []))} reqs, {raw_eval_itt} eval criteria")

print(f"Extracting {p_a2.name} via {model_name}...")
facts_a2 = extractor.extract_document_facts(t_a2, p_a2.name, api_key=api_key)
raw_eval_a2 = len(facts_a2.get("evaluation_criteria", []))
print(f"  Annex 2 extracted: {len(facts_a2.get('requirements', []))} reqs, {raw_eval_a2} eval criteria")
stage_a_duration = time.perf_counter() - t0
print(f"Stage A completed in {stage_a_duration:.2f}s")

# Stage B: Package Normalization
print("\n--- Running Stage B Normalization ---")
t0 = time.perf_counter()
doc_facts_list = [facts_itt, facts_a2]
normalized_facts = extractor.normalize_package_facts(doc_facts_list, package_meta)
stage_b_duration = time.perf_counter() - t0
norm_eval = normalized_facts.get("evaluation_criteria", [])
print(f"Stage B completed in {stage_b_duration:.4f}s: {len(norm_eval)} normalized eval criteria")

# Stage C: Reconciliation
print("\n--- Running Stage C Reconciliation ---")
t0 = time.perf_counter()
conflicts = extractor.reconcile_package_facts(normalized_facts, package_meta["files"])
stage_c_duration = time.perf_counter() - t0
print(f"Stage C completed in {stage_c_duration:.4f}s: {len(conflicts)} conflicts")

# Stage D: Synthesis & Authoritative Rebuild
print("\n--- Running Stage D Synthesis & Authoritative Rebuild ---")
t0 = time.perf_counter()
synth_result = extractor.synthesize_bid_brief(normalized_facts, conflicts, api_key=api_key)
stage_d_duration = time.perf_counter() - t0
print(f"Stage D completed in {stage_d_duration:.2f}s")

# Extract evaluation hierarchy breakdown from Brief
brief = synth_result.get("brief", {})
eval_breakdown = brief.get("evaluation_breakdown", [])

# Build full hierarchy and calculate totals
hierarchy = evaluation_hierarchy.build_evaluation_hierarchy(eval_breakdown)
totals = evaluation_hierarchy.calculate_evaluation_totals(hierarchy)
display_rows, _ = evaluation_hierarchy.format_evaluation_for_display(eval_breakdown)

output_stats = {
    "provenance": {
        "code_sha": code_sha,
        "run_started_at": run_started_at,
        "model": model_name,
        "input_files": [
            {
                "filename": p_itt.name,
                "sha256": h_itt,
                "chars": len(t_itt),
            },
            {
                "filename": p_a2.name,
                "sha256": h_a2,
                "chars": len(t_a2),
            },
        ],
    },
    "timings": {
        "stage_a_sec": round(stage_a_duration, 2),
        "stage_b_sec": round(stage_b_duration, 4),
        "stage_c_sec": round(stage_c_duration, 4),
        "stage_d_sec": round(stage_d_duration, 2),
        "total_pipeline_sec": round(stage_a_duration + stage_b_duration + stage_c_duration + stage_d_duration, 2),
    },
    "raw_evaluation_criteria": {
        "itt_pdf": facts_itt.get("evaluation_criteria", []),
        "annex_2_docx": facts_a2.get("evaluation_criteria", []),
        "total_raw_count": raw_eval_itt + raw_eval_a2,
    },
    "normalized_evaluation_criteria": norm_eval,
    "evaluation_breakdown": eval_breakdown,
    "evaluation_hierarchy": {
        "roots": hierarchy.get("roots", []),
        "unresolved": hierarchy.get("unresolved", []),
        "all_criteria_count": len(hierarchy.get("all_criteria", [])),
    },
    "evaluation_totals": {
        "status": totals.get("status"),
        "overall_total": totals.get("overall_total"),
        "overall_unit": totals.get("overall_unit"),
        "root_details": totals.get("root_details", []),
        "child_details": totals.get("child_details", {}),
        "warnings": totals.get("warnings", []),
    },
    "display_rows": display_rows,
}

print("\n" + "=" * 70)
print("EVALUATION HIERARCHY BENCHMARK RESULTS")
print("=" * 70)
print(json.dumps(output_stats["evaluation_totals"], indent=2))

out_path = PROJECT_ROOT / "tests" / "acceptance" / "results" / "bc_evaluation_hierarchy_replay.json"
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(output_stats, indent=2), encoding="utf-8")
print(f"\nSaved fresh replay results to {out_path}")
