"""
run_bc_submission_replay.py

Portable British Council Benchmark Replay focusing on Submission Artifact Projection & Provenance.
Runs Stage A -> Stage B -> Stage C -> Stage D -> deterministic projection (build_submission_documents)
against the British Council procurement package fixture.

Outputs:
  tests/acceptance/results/bc_submission_artifact_projection_replay.json
"""
import pathlib
import sys
import time
import json
import hashlib
import datetime
import subprocess

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
import extractor

# 1. Provenance: git commit SHA
try:
    git_proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=True
    )
    code_sha = git_proc.stdout.strip()
except Exception as e:
    code_sha = "unknown"

run_started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
model_name = "claude-haiku-4-5-20251001"

fixture_dir = PROJECT_ROOT / "tests" / "fixtures" / "local" / "british_council_ir67tvet42026"
if not fixture_dir.exists():
    sys.exit(f"ERROR: Fixture directory not found: {fixture_dir}")

target_files = [
    "annex_1_-_terms_and_condition_of_contract_ir67tvet42026.pdf",
    "annex_2_-_procurement_specific_questionnaire_1.docx",
    "annex_2a_procurement_specific_questionnaire_ratio_analysis_1.xls",
    "annex_3_-_supplier_response_ir67tvet42026.docx",
    "annex_4_-_pricing_approach_ir67tvet42026.xlsx",
    "appendix_1_-_service_level_agreement_template.pdf",
    "itt_-_ir67tvet42026_-_smart_classroom_setup_-_updated.pdf",
    "itt_-_ir67tvet42026_-_smart_classroom_setup_-_updated_0.pdf",
]

print("=" * 75)
print(f"BRITISH COUNCIL SUBMISSION ARTIFACT PROJECTION REPLAY - {run_started_at}")
print(f"Code SHA: {code_sha}")
print(f"Fixture: {fixture_dir}")
print("=" * 75)

# Preprocessing & file hashes
t0 = time.perf_counter()
package_files = []
input_files_meta = []
package_meta = {
    "files": [],
    "doc_metadata": {},
    "doc_texts": {},
}

for fname in target_files:
    fpath = fixture_dir / fname
    if not fpath.exists():
        print(f"Warning: File {fname} not found in fixture directory, skipping.")
        continue
    fbytes = fpath.read_bytes()
    h = hashlib.sha256(fbytes).hexdigest()
    text, meta = extractor.extract_document_with_metadata(fbytes, fname)
    package_files.append((fname, fbytes))
    package_meta["files"].append(fname)
    package_meta["doc_metadata"][fname] = meta
    package_meta["doc_texts"][fname] = text
    input_files_meta.append({
        "filename": fname,
        "sha256": h,
        "chars": len(text),
    })

preprocessing_sec = time.perf_counter() - t0
print(f"Preprocessed {len(package_files)} files in {preprocessing_sec:.2f}s")

# Stage A Document Facts
# Check if frozen Stage A document facts exist to enable fast deterministic replay or live extraction
frozen_stage_a_path = PROJECT_ROOT / "tests" / "acceptance" / "results" / "bc_ir67tvet42026_attempt2_document_facts.json"

t_a_start = time.perf_counter()
if frozen_stage_a_path.exists():
    print(f"\n--- Loading Document Facts from {frozen_stage_a_path.name} ---")
    raw_doc_entries = json.loads(frozen_stage_a_path.read_text(encoding="utf-8"))
    doc_facts_list = [entry["facts"] if "facts" in entry else entry for entry in raw_doc_entries]
    stage_a_sec = 0.001
else:
    api_key = config.get_api_key()
    if not api_key:
        raise RuntimeError("No Anthropic API key found in configuration and no frozen facts found.")
    print(f"\n--- Executing Stage A Live Fact Extraction ---")
    doc_facts_list = []
    for fname, fbytes in package_files:
        doc_text = package_meta["doc_texts"][fname]
        print(f"Extracting {fname}...")
        facts = extractor.extract_document_facts(doc_text, fname, api_key)
        doc_facts_list.append(facts)
    stage_a_sec = time.perf_counter() - t_a_start

raw_submission_rules = []
for df in doc_facts_list:
    if isinstance(df, dict):
        raw_submission_rules.extend(df.get("submission_rules", []))
print(f"Stage A completed: {len(raw_submission_rules)} raw submission rules")

# Stage B: Package Normalization
print("\n--- Running Stage B Normalization ---")
t_b_start = time.perf_counter()
normalized_facts = extractor.normalize_package_facts(doc_facts_list, package_meta)
stage_b_sec = time.perf_counter() - t_b_start
norm_submission_rules = normalized_facts.get("submission_rules", [])
print(f"Stage B completed in {stage_b_sec:.4f}s: {len(norm_submission_rules)} normalized submission rules")

# Stage C: Reconciliation
print("\n--- Running Stage C Reconciliation ---")
t_c_start = time.perf_counter()
conflicts = extractor.reconcile_package_facts(normalized_facts, package_meta["files"])
stage_c_sec = time.perf_counter() - t_c_start
print(f"Stage C completed in {stage_c_sec:.4f}s: {len(conflicts)} conflicts")

# Stage D: Synthesis (or Authoritative Projection Rebuild)
print("\n--- Running Stage D Rebuild & Deterministic Document Projection ---")
t_d_start = time.perf_counter()
# Check if frozen attempt2 bid brief exists for stage D synthesis base
frozen_brief_path = PROJECT_ROOT / "tests" / "acceptance" / "results" / "bc_ir67tvet42026_attempt2_bid_brief.json"
if frozen_brief_path.exists():
    synth_data = json.loads(frozen_brief_path.read_text(encoding="utf-8"))
else:
    synth_data = {"bid": {}, "brief": {}}

# Apply deterministic authoritative sections
synth_data = extractor.apply_stage_d_authoritative_sections(synth_data, normalized_facts)
stage_d_sec = time.perf_counter() - t_d_start

# Deterministic Projection: build_submission_documents
t_proj_start = time.perf_counter()
bid = synth_data.get("bid", {})
projected_documents = extractor.build_submission_documents(
    norm_submission_rules,
    submission_deadline=bid.get("submission_deadline"),
)
proj_sec = time.perf_counter() - t_proj_start

# Classifications of all normalized rules
classifications = []
excluded_rules = []
for sr in norm_submission_rules:
    c = extractor.classify_submission_rule(
        item=sr.get("item", ""),
        fmt=sr.get("format"),
        details=sr.get("details"),
        artifact_type=sr.get("artifact_type"),
        file_format=sr.get("file_format"),
        submission_channel=sr.get("submission_channel"),
    )
    rule_summary = {
        "item": sr.get("item"),
        "format": sr.get("format"),
        "details": sr.get("details"),
        "mandatory": sr.get("mandatory"),
        "classification": c["classification"],
        "is_concrete_document": c["is_concrete_document"],
        "resolved_artifact_type": c["artifact_type"],
        "resolved_file_format": c["file_format"],
        "resolved_submission_channel": c["submission_channel"],
    }
    classifications.append(rule_summary)
    if not c["is_concrete_document"]:
        excluded_rules.append(rule_summary)

# Provenance verification state
provenance_summary = {
    "total_projected_documents": len(projected_documents),
    "verified_documents": sum(1 for d in projected_documents if d.get("provenance_state") == "VERIFIED"),
    "unverified_documents": sum(1 for d in projected_documents if d.get("provenance_state") == "UNVERIFIED"),
    "all_projected_have_provenance_state": all("provenance_state" in d for d in projected_documents),
}

output_stats = {
    "execution_metadata": {
        "code_commit_sha": code_sha,
        "run_started_at": run_started_at,
        "model": model_name,
        "fixture": "british_council_ir67tvet42026",
        "pipeline_stages": ["A", "B", "C", "D", "projection"],
        "projection_mode": "orthogonal_submission_semantics",
    },
    "input_files": input_files_meta,
    "timings": {
        "preprocessing_sec": round(preprocessing_sec, 4),
        "stage_a_sec": round(stage_a_sec, 4),
        "stage_b_sec": round(stage_b_sec, 4),
        "stage_c_sec": round(stage_c_sec, 4),
        "stage_d_sec": round(stage_d_sec, 4),
        "projection_sec": round(proj_sec, 4),
        "total_pipeline_sec": round(preprocessing_sec + stage_a_sec + stage_b_sec + stage_c_sec + stage_d_sec + proj_sec, 4),
    },
    "raw_submission_rules_count": len(raw_submission_rules),
    "normalized_submission_rules_count": len(norm_submission_rules),
    "projected_submission_documents_count": len(projected_documents),
    "classification_results": classifications,
    "projected_submission_documents": projected_documents,
    "excluded_rules": excluded_rules,
    "provenance_validation_state": provenance_summary,
}

out_path = PROJECT_ROOT / "tests" / "acceptance" / "results" / "bc_submission_artifact_projection_replay.json"
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(output_stats, indent=2), encoding="utf-8")

print("\n" + "=" * 75)
print("PROJECTED SUBMISSION DOCUMENTS SUMMARY")
print("=" * 75)
print(f"Total Projected: {len(projected_documents)}")
for doc in projected_documents:
    print(f"  - [{doc.get('doc_type')}] {doc.get('name')} | Format: {doc.get('file_format')} | Channel: {doc.get('submission_channel')} | Prov: {doc.get('provenance_state')}")

print(f"\nSaved fresh replay results to {out_path}")
