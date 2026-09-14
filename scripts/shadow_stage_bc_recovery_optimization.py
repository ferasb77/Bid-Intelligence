"""Stage A Recovery-Path Optimization Package 2 -- shadow Stage B/C comparison.

Non-authoritative. Builds Stage B (normalize_package_facts) + Stage C
(reconcile_package_facts, which internally resolves the canonical opportunity)
TWICE, from two different Stage A input sets, using the real deterministic
production code -- no LLM calls in this script:

  BASELINE : all 16 documents' Stage A facts from the accepted control run
             (stagea-perf-boc-2026-026-20260912T224533Z-cf5a4d), unmodified.
  SHADOW   : the 5 pilot documents' Stage A facts from the recovery-path-
             optimization pilot run, substituted in place of their control-run
             counterparts; the other 11 documents' facts are the SAME control
             facts as BASELINE (unchanged).

This isolates the effect of the optimization on governed Stage B/C semantics
from any other source of variance (both runs share the same 11 untouched
documents' facts). Not promoted into any authoritative lineage.

Usage: py -3.13 scripts/shadow_stage_bc_recovery_optimization.py <pilot_run_id>
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from extractor import extract_document_with_metadata, normalize_package_facts, reconcile_package_facts

CORPUS = ROOT / "evaluation/bank_of_canada_briefing_pack/corrected_procurement_corpus"
CONTROL_RUN_ID = "stagea-perf-boc-2026-026-20260912T224533Z-cf5a4d"
TELEMETRY_ROOT = ROOT / "evaluation/bank_of_canada_briefing_pack/performance_telemetry"

PILOT_DOCUMENTS = [
    "RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf",
    "OriginalRevision/RFP 2026-06 - Appendix G - Form of Agreement.docx",
    "OriginalRevision/RFP 2026-026 - Appendix E - Pricing Form.xlsx",
    "OriginalRevision/RFP 2026-026 - Appendix D1 - Rated criteria response form.docx",
    "abstract.pdf",
]


def load_control_facts():
    control_dir = TELEMETRY_ROOT / CONTROL_RUN_ID
    return json.loads((control_dir / "stage_a_document_facts.json").read_text(encoding="utf-8"))


def build_package_metadata(file_names):
    metadata = {"files": [], "doc_metadata": {}, "doc_texts": {}}
    for name in file_names:
        payload = (CORPUS / name).read_bytes()
        text, meta = extract_document_with_metadata(payload, name)
        metadata["files"].append(name)
        metadata["doc_metadata"][name] = meta
        metadata["doc_texts"][name] = text
    return metadata


def run_stage_bc(doc_facts_by_name, file_order, label):
    metadata = build_package_metadata(file_order)
    doc_facts_list = [doc_facts_by_name[name] for name in file_order]
    normalized = normalize_package_facts(doc_facts_list, metadata)
    conflicts = reconcile_package_facts(normalized, file_order)
    summary = {
        "label": label,
        "family_counts": {k: len(v) for k, v in normalized.items()
                          if isinstance(v, list) and not k.startswith("_")},
        "conflict_count": len(conflicts),
        "conflict_types": sorted(set(c.get("conflict_type") or c.get("type") or "UNKNOWN" for c in conflicts)),
        "doc_metadata": normalized.get("doc_metadata"),
        "canonical_opportunity_present": normalized.get("_canonical_opportunity") is not None,
    }
    canonical = normalized.get("_canonical_opportunity")
    if isinstance(canonical, dict):
        summary["canonical_top_level_keys"] = sorted(canonical.keys())
        summary["canonical_conflict_count"] = len(canonical.get("conflicts") or [])
    return summary, normalized, conflicts


if __name__ == "__main__":
    control_facts = load_control_facts()
    file_order = sorted(control_facts.keys())  # deterministic order for this shadow comparison only

    baseline_summary, baseline_normalized, baseline_conflicts = run_stage_bc(control_facts, file_order, "BASELINE (all-control)")
    print("=== BASELINE (16 control-run documents) ===")
    print(json.dumps(baseline_summary, indent=2, default=str))

    if len(sys.argv) > 1:
        pilot_run_id = sys.argv[1]
        pilot_dir = TELEMETRY_ROOT / pilot_run_id
        pilot_facts = json.loads((pilot_dir / "stage_a_document_facts.json").read_text(encoding="utf-8"))
        shadow_facts = dict(control_facts)
        for name in PILOT_DOCUMENTS:
            shadow_facts[name] = pilot_facts[name]
        shadow_summary, shadow_normalized, shadow_conflicts = run_stage_bc(shadow_facts, file_order, "SHADOW (5 optimized + 11 control)")
        print()
        print("=== SHADOW (5 pilot-optimized + 11 control documents) ===")
        print(json.dumps(shadow_summary, indent=2, default=str))

        print()
        print("=== DELTA (shadow - baseline) ===")
        for k in baseline_summary["family_counts"]:
            b, s = baseline_summary["family_counts"][k], shadow_summary["family_counts"][k]
            if b != s:
                print(f"  family_counts.{k}: {b} -> {s} (delta {s-b})")
        if baseline_summary["conflict_count"] != shadow_summary["conflict_count"]:
            print(f"  conflict_count: {baseline_summary['conflict_count']} -> {shadow_summary['conflict_count']}")
        if baseline_summary["conflict_types"] != shadow_summary["conflict_types"]:
            print(f"  conflict_types changed: {baseline_summary['conflict_types']} -> {shadow_summary['conflict_types']}")
        if baseline_summary["doc_metadata"] != shadow_summary["doc_metadata"]:
            print(f"  doc_metadata changed: {baseline_summary['doc_metadata']} -> {shadow_summary['doc_metadata']}")
        out_dir = TELEMETRY_ROOT / f"shadow-stage-bc-{pilot_run_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "baseline_summary.json").write_text(json.dumps(baseline_summary, indent=2, default=str), encoding="utf-8")
        (out_dir / "shadow_summary.json").write_text(json.dumps(shadow_summary, indent=2, default=str), encoding="utf-8")
        print()
        print("Shadow comparison persisted at:", out_dir)
    else:
        print()
        print("(No pilot_run_id given -- baseline only. Rerun with the pilot run ID once it completes.)")
