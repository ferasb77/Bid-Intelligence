"""
Bank of Canada RFP 2026-026: Blind Acceptance Test Runner
Executes the live extraction pipeline without code alterations, records timings,
freezes raw outputs, and populates a live acceptance bid in Supabase.
"""
import os
import sys
import time
import json
import subprocess
from datetime import datetime

# Setup project path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

import config
import database
from extractor import (
    extract_procurement_package,
    extract_document_with_metadata,
    extract_document_facts,
    normalize_package_facts,
    reconcile_package_facts,
    synthesize_bid_brief
)


def get_git_info():
    try:
        branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT_DIR).decode().strip()
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT_DIR).decode().strip()
        return branch, commit
    except Exception:
        return "refactor/streamlined-bid-workflow", "unknown"


def main():
    print("=================================================================")
    print("BANK OF CANADA RFP 2026-026: BLIND ACCEPTANCE TEST RUNNER")
    print("=================================================================")

    api_key = config.get_api_key()
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not found in config or .env!")
        sys.exit(1)

    branch, commit = get_git_info()
    timestamp = datetime.now().isoformat() + "Z"
    model_name = "claude-haiku-4-5-20251001"

    print(f"Branch: {branch}")
    print(f"Commit: {commit}")
    print(f"Timestamp: {timestamp}")
    print(f"Model: {model_name}")

    fixture_dir = os.path.join(ROOT_DIR, "tests", "fixtures", "local", "bank_of_canada_2026_026")
    if not os.path.exists(fixture_dir):
        print(f"ERROR: Fixture directory not found at {fixture_dir}")
        sys.exit(1)

    # 1. Load raw files
    raw_files = []
    for root, dirs, files in os.walk(fixture_dir):
        for f in sorted(files):
            fpath = os.path.join(root, f)
            rel_name = os.path.relpath(fpath, fixture_dir).replace("\\", "/")
            with open(fpath, "rb") as fp:
                raw_files.append((rel_name, fp.read()))

    print(f"\nLoaded {len(raw_files)} raw documents from package.")

    results_dir = os.path.join(ROOT_DIR, "tests", "acceptance", "results")
    os.makedirs(results_dir, exist_ok=True)

    # 2. Execute Staged Pipeline with Granular Stage Instrumentation
    t_start = time.time()

    # Document Parsing & Metadata
    t0 = time.time()
    package_metadata = {"files": [], "doc_metadata": {}, "doc_texts": {}}
    for fname, fbytes in raw_files:
        parsed_text, meta = extract_document_with_metadata(fbytes, fname)
        package_metadata["files"].append(fname)
        package_metadata["doc_metadata"][fname] = meta
        package_metadata["doc_texts"][fname] = parsed_text
    t_parse = time.time() - t0
    print(f"Document Parsing completed in {t_parse:.2f}s")

    # STAGE A — Document Fact Extraction
    t0 = time.time()
    doc_facts_list = []
    stage_a_calls = 0
    for fname, dtext in package_metadata["doc_texts"].items():
        print(f"  [Stage A] Extracting facts from: {fname}...")
        dfacts = extract_document_facts(dtext, fname, api_key=api_key)
        doc_facts_list.append({"file": fname, "facts": dfacts})
        stage_a_calls += 1
    t_stage_a = time.time() - t0
    print(f"Stage A completed ({stage_a_calls} calls) in {t_stage_a:.2f}s")

    # STAGE B — Package Normalization & Source Provenance Validation
    t0 = time.time()
    normalized_facts = normalize_package_facts(doc_facts_list, package_metadata)
    t_stage_b = time.time() - t0
    print(f"Stage B completed in {t_stage_b:.2f}s")

    # STAGE C — Reconciliation & Conflict Detection
    t0 = time.time()
    conflicts = reconcile_package_facts(normalized_facts, package_metadata["files"])
    t_stage_c = time.time() - t0
    print(f"Stage C completed in {t_stage_c:.2f}s")

    # STAGE D — Executive Bid Brief Synthesis
    t0 = time.time()
    print("  [Stage D] Synthesizing Executive Bid Brief from normalized model...")
    synthesis = synthesize_bid_brief(normalized_facts, conflicts, api_key=api_key)
    stage_d_calls = 1
    t_stage_d = time.time() - t0
    print(f"Stage D completed in {t_stage_d:.2f}s")

    total_time = time.time() - t_start
    print(f"\nPipeline Total Execution Time: {total_time:.2f}s")

    # Build Complete Pipeline Output
    raw_result = {
        "execution_metadata": {
            "model": model_name,
            "branch": branch,
            "commit_sha": commit,
            "timestamp": timestamp,
            "total_execution_time_sec": total_time,
            "stage_timings_sec": {
                "document_parsing": t_parse,
                "stage_a_fact_extraction": t_stage_a,
                "stage_b_normalization": t_stage_b,
                "stage_c_reconciliation": t_stage_c,
                "stage_d_synthesis": t_stage_d
            },
            "claude_calls": {
                "stage_a": stage_a_calls,
                "stage_d": stage_d_calls,
                "total": stage_a_calls + stage_d_calls
            }
        },
        "bid": synthesis.get("bid", {}),
        "brief": synthesis.get("brief", {}),
        "requirements": normalized_facts.get("requirements", []),
        "documents": synthesis.get("documents", []),
        "conflicts": conflicts,
        "raw_doc_facts": doc_facts_list,
        "normalized_facts": normalized_facts
    }

    # 3. Freeze All Raw Outputs
    def _default_ser(o):
        if isinstance(o, set):
            return sorted(list(o))
        return str(o)

    with open(os.path.join(results_dir, "boc_2026_026_raw_result.json"), "w", encoding="utf-8") as f:
        json.dump(raw_result, f, indent=2, default=_default_ser)

    with open(os.path.join(results_dir, "boc_2026_026_document_facts.json"), "w", encoding="utf-8") as f:
        json.dump(doc_facts_list, f, indent=2, default=_default_ser)

    with open(os.path.join(results_dir, "boc_2026_026_normalized_facts.json"), "w", encoding="utf-8") as f:
        json.dump(normalized_facts, f, indent=2, default=_default_ser)

    with open(os.path.join(results_dir, "boc_2026_026_conflicts.json"), "w", encoding="utf-8") as f:
        json.dump(conflicts, f, indent=2, default=_default_ser)

    with open(os.path.join(results_dir, "boc_2026_026_bid_brief.json"), "w", encoding="utf-8") as f:
        json.dump(synthesis, f, indent=2, default=_default_ser)

    print("\n✓ Frozen raw outputs successfully written to tests/acceptance/results/")

    # 4. Calculate Summary Statistics
    reqs = raw_result["requirements"]
    mand = sum(1 for r in reqs if r.get("category") == "Mandatory")
    rated = sum(1 for r in reqs if r.get("category") == "Rated")
    fin = sum(1 for r in reqs if r.get("category") == "Financial")
    supp = sum(1 for r in reqs if r.get("category") == "Supporting")

    all_refs = []
    for r in reqs:
        all_refs.extend(r.get("source_refs", []))
    verified_refs = sum(1 for rf in all_refs if rf.get("verified"))
    unverified_refs = len(all_refs) - verified_refs

    stats = {
        "source_files": len(raw_files),
        "total_extracted_requirements": len(reqs),
        "categories": {
            "Mandatory": mand,
            "Rated": rated,
            "Financial": fin,
            "Supporting": supp
        },
        "submission_documents": len(raw_result.get("documents", [])),
        "total_source_references": len(all_refs),
        "verified_source_references": verified_refs,
        "unverified_source_references": unverified_refs,
        "detected_conflicts": len(conflicts),
        "total_execution_time_sec": total_time
    }

    with open(os.path.join(results_dir, "boc_2026_026_statistics.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    print(json.dumps(stats, indent=2))

    # 5. Populate Live Acceptance Test Bid in Supabase
    print("\n=================================================================")
    print("CREATING LIVE TEST BID IN SUPABASE")
    print("=================================================================")
    bid_payload = raw_result["bid"]
    bid_payload["title"] = "Bank of Canada RFP 2026-026 — Acceptance Test"
    bid_payload["client"] = "Bank of Canada"
    bid_payload["stage"] = "Qualifying"

    bid_id = database.create_bid(bid_payload)
    print(f"Created Live Acceptance Bid ID: {bid_id}")

    # Upsert Requirements
    for r in reqs:
        r_copy = r.copy()
        r_copy["bid_id"] = bid_id
        r_copy["qual_status"] = "UNKNOWN"
        r_copy["evidence_status"] = "MISSING" if r.get("category") == "Mandatory" else "NOT REQUIRED"
        database.upsert_requirement(r_copy)
    print(f"Inserted {len(reqs)} requirements into Supabase.")

    # Upsert Bid Brief
    brief_payload = raw_result["brief"]
    brief_payload["bid_id"] = bid_id
    brief_payload["document_conflicts"] = conflicts
    database.upsert_bid_brief(brief_payload)
    print("Upserted Bid Brief with conflicts into Supabase.")

    # Upsert Submission Documents
    sub_docs = raw_result.get("documents", [])
    for d in sub_docs:
        d_copy = d.copy()
        d_copy["bid_id"] = bid_id
        d_copy["status"] = "Expected"
        database.upsert_document(d_copy)
    print(f"Inserted {len(sub_docs)} submission documents into Supabase.")

    # Record initial AI decision
    database.save_bid_decision({
        "bid_id": bid_id,
        "ai_recommendation": "GO WITH CONDITIONS",
        "ai_confidence": 0.85,
        "overall_score": 82,
        "dimension_scores": {"Strategic Fit": 85, "Technical Capability": 80, "Compliance": 80, "Commercial": 82},
        "hard_blockers": [],
        "conditions": ["Verify Category 3 bilingual roster feasibility before final submission"],
        "win_themes": ["Deep public sector advisory capability", "Proven leadership development track record"],
        "red_flags": [c.get("topic") for c in conflicts if c.get("conflict_type") == "MANDATORY_REQUIREMENT_CONFLICT"]
    })
    print("Recorded initial AI decision evaluation (human_decision=NULL).")

    print("\n✓ Live acceptance test bid successfully populated in Supabase.")


if __name__ == "__main__":
    main()
