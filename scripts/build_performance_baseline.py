"""Assemble the performance/observability baseline artifacts for the
frozen Bank of Canada commissioned baseline (tag bid-intelligence-rc2).

Read-only with respect to production code and every existing commissioning
run. Makes zero LLM calls. Pulls exclusively from real, already-persisted
commissioning artifacts (phase1/phase4 commissioning directories, the
freeze-time Executive Briefing Pack commissioning boundaries.json) and from
BANK_OF_CANADA_STAGE_D_NARRATIVE_COMPLETENESS_AUDIT.md's own already-real,
already-measured Stage D token-usage table. Nothing here is estimated or
invented; every field is either MEASURED (cited to its source artifact) or
explicitly null/"UNAVAILABLE".
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluation/bank_of_canada_briefing_pack/performance_baseline"
OUT.mkdir(parents=True, exist_ok=True)

PHASE1_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase1_commissioning/phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5"
PHASE4_AUTH_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase4_commissioning/phase4-boc-2026-026-staged-20260912T131303Z-2cc8af"
PACK_RUN_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/executive_briefing_pack_commissioning/briefingpack-boc-2026-026-20260912T184942Z-f775ca"

report = json.loads((PHASE1_DIR / "phase1_stage_a_report.json").read_text(encoding="utf-8"))
parsing = {d["path"]: d for d in json.loads((PHASE1_DIR / "phase1_document_parsing.json").read_text(encoding="utf-8"))}
phase1_boundaries = json.loads((PHASE1_DIR / "boundaries.json").read_text(encoding="utf-8"))
phase4_status = json.loads((PHASE4_AUTH_DIR / "stage_d_status.json").read_text(encoding="utf-8"))
phase4_meta = json.loads((PHASE4_AUTH_DIR / "run_metadata.json").read_text(encoding="utf-8"))
upstream_downstream = json.loads((PHASE4_AUTH_DIR / "upstream_downstream_accounting.json").read_text(encoding="utf-8"))
pack_boundaries = json.loads((PACK_RUN_DIR / "boundaries.json").read_text(encoding="utf-8"))

# --- Stage A per-document table ------------------------------------------------

stage_a_docs = []
for r in report:
    p = parsing.get(r["path"], {})
    stage_a_docs.append({
        "sequence": r["sequence"],
        "path": r["path"],
        "role": r["role"],
        "bytes": p.get("bytes"),
        "parsed_characters": p.get("extracted_character_count"),
        "total_records": r["total_records"],
        "record_counts_by_family": r["record_counts"],
        "recovery_status": r["extraction_diagnostic"]["status"],
        "input_tokens": None,
        "output_tokens": None,
        "llm_seconds": None,
        "total_document_seconds": None,
        "retries": None,
        "cost": None,
        "measurement_note": "Per-document time/tokens/retries/cost were never captured by this run "
                            "(no telemetry existed in extractor.py at the time it executed). Bytes, "
                            "parsed characters, record counts, and recovery status ARE measured, from "
                            "phase1_document_parsing.json / phase1_stage_a_report.json.",
    })
stage_a_docs.sort(key=lambda x: x["sequence"])

recovered = [d for d in stage_a_docs if d["recovery_status"] == "RECOVERED_TRUNCATED"]
highest_records = max(stage_a_docs, key=lambda d: d["total_records"])
highest_chars = max(stage_a_docs, key=lambda d: d["parsed_characters"])
lowest_chars = min(stage_a_docs, key=lambda d: d["parsed_characters"])

stage_a_boundary = next(b for b in phase1_boundaries if b["boundary"] == "Stage A")

# --- Deterministic stage timings (freeze-time pack run) ------------------------

deterministic_stages = [
    {"stage": b["boundary"], "wall_seconds": b["elapsed_seconds"], "status": b["status"],
     "extra": {k: v for k, v in b.items() if k not in ("boundary", "elapsed_seconds", "status")}}
    for b in pack_boundaries
]
deterministic_total = round(sum(s["wall_seconds"] for s in deterministic_stages), 3)

# --- Critical path (deterministic chain, ranked) --------------------------------

ranked = sorted(deterministic_stages, key=lambda s: s["wall_seconds"], reverse=True)
cumulative = 0.0
critical_path = []
for rank, s in enumerate(ranked, 1):
    cumulative += s["wall_seconds"]
    critical_path.append({
        "rank": rank, "stage": s["stage"], "wall_seconds": s["wall_seconds"],
        "pct_of_deterministic_total": round(100 * s["wall_seconds"] / deterministic_total, 2),
        "cumulative_pct": round(100 * cumulative / deterministic_total, 2),
    })

# --- LLM call telemetry (only what is genuinely measured) ----------------------

llm_calls = [
    {
        "stage": "Stage D",
        "run_id": "phase4-narrative-diag-boc-2026-026-20260912T133437Z-2a74e2",
        "attempt": 1,
        "model": "claude-haiku-4-5-20251001",
        "input_tokens": 146601,
        "output_tokens": 1411,
        "stop_reason": "end_turn",
        "validation_result": "FAILED / UNKNOWN_EVIDENCE_SELECTOR",
        "source": "evaluation/bank_of_canada_briefing_pack/BANK_OF_CANADA_STAGE_D_NARRATIVE_COMPLETENESS_AUDIT.md Section E",
        "lineage_note": "Diagnostic rerun against Stage B phase2-boc-2026-026-stageb-20260912T125051Z-91a22b / "
                        "Stage C phase3-boc-2026-026-stagec-20260912T130007Z-dd391b -- SUPERSEDED, not the "
                        "current frozen baseline lineage. Stage D is architecturally decoupled from the "
                        "EOB->Pack chain (confirmed: zero references) and was not rerun against the final lineage.",
    },
    {
        "stage": "Stage D",
        "run_id": "phase4-narrative-diag-boc-2026-026-20260912T133437Z-2a74e2",
        "attempt": 2,
        "model": "claude-haiku-4-5-20251001",
        "input_tokens": 146624,
        "output_tokens": 1535,
        "stop_reason": "end_turn",
        "validation_result": "FAILED / UNKNOWN_EVIDENCE_SELECTOR",
        "source": "evaluation/bank_of_canada_briefing_pack/BANK_OF_CANADA_STAGE_D_NARRATIVE_COMPLETENESS_AUDIT.md Section E",
        "lineage_note": "Same as attempt 1.",
    },
]
(OUT / "llm_calls.jsonl").write_text(
    "\n".join(json.dumps(c, sort_keys=True) for c in llm_calls) + "\n", encoding="utf-8")

# --- stage_timings.json ---------------------------------------------------------

stage_timings = {
    "stage_a": {
        "run_id": "phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5",
        "wall_seconds": stage_a_boundary["elapsed_seconds"],
        "documents": stage_a_boundary["documents"],
        "documents_with_warnings": stage_a_boundary["documents_with_warnings"],
        "total_records": stage_a_boundary["total_records"],
        "zero_output_documents": stage_a_boundary["zero_output_documents"],
        "measured": True,
        "llm_backed": True,
        "note": "One-time, frozen extraction against the current authoritative 16-document corpus. "
                "Per-document/per-call timing and token counts were not captured by this run.",
    },
    "stage_b_stage_c": {
        "note": "Deterministic; both complete in well under 1s per the provenance-granularity and "
                "conflict-identity remediation reports' own full-suite timing context. Not independently "
                "re-measured in isolation for this baseline (folded into the deterministic chain below).",
        "measured": False,
        "llm_backed": False,
    },
    "stage_d": {
        "authoritative_pass_run_id": "phase4-boc-2026-026-staged-20260912T131303Z-2cc8af",
        "authoritative_pass_wall_seconds": phase4_status["elapsed_seconds"],
        "authoritative_pass_lineage": {
            "phase2_run_id": phase4_meta["input_phase2_run_id"],
            "phase3_run_id": phase4_meta["input_phase3_run_id"],
        },
        "diagnostic_rerun_run_id": "phase4-narrative-diag-boc-2026-026-20260912T133437Z-2a74e2",
        "diagnostic_rerun_wall_seconds": 48.638,
        "diagnostic_rerun_tokens": {"attempt_1": {"input": 146601, "output": 1411},
                                    "attempt_2": {"input": 146624, "output": 1535}},
        "lineage_superseded": True,
        "part_of_eob_to_pack_chain": False,
        "measured": True,
        "llm_backed": True,
        "payload_composition_records": upstream_downstream,
        "note": "Both the authoritative PASS run and the token-instrumented diagnostic rerun used an "
                "intermediate, now-superseded Stage B/C snapshot -- NOT the final "
                "phase2-boc-2026-026-stageb-canonterm-fix-20260912T142551Z-34a031 / "
                "phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8 lineage. Stage D is "
                "architecturally decoupled from Canonical Opportunity / Opportunity Structure / Opportunity "
                "Intelligence / Buyer Brief / Executive Opportunity Brief / Executive Briefing Pack (zero "
                "references, confirmed by exhaustive grep in the Stage D Narrative Completeness Audit) and "
                "was never rerun against the final lineage -- this baseline does not rerun it either.",
    },
    "deterministic_chain": {
        "run_id": "briefingpack-boc-2026-026-20260912T184942Z-f775ca",
        "total_wall_seconds": deterministic_total,
        "stages": deterministic_stages,
        "measured": True,
        "llm_backed": False,
        "note": "Full replay of Evidence -> Canonical Opportunity Publication -> Opportunity Structure "
                "Publication -> Opportunity Intelligence -> Opportunity Intelligence Publication -> "
                "Executive Opportunity Understanding -> Executive Opportunity Brief -> Buyer Brief -> "
                "Executive Briefing Pack against the CURRENT frozen authoritative lineage. This is the same "
                "run used for Section 15's correctness-invariance check (final pack identity/revision/digest "
                "confirmed unchanged).",
    },
}
(OUT / "stage_timings.json").write_text(json.dumps(stage_timings, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

# --- PERFORMANCE_BASELINE.json (top-level) --------------------------------------

baseline = {
    "baseline_fingerprint": {
        "git_tag": "bid-intelligence-rc2",
        "commissioned_code_commit_sha": "1526c2cb1199eebb9992b593cf0c322d377af6ca",
        "pack_id": "pack-b11fe92992b988d51edba6077dc7f1999d864838a7e01acd7e332b3b3faeb600",
        "pack_revision_id": "pack-revision-8b3b21c79dd82605e7ea70ad5d622905aae826dddd1ce4b343fdb4ad8e945ebe",
        "pack_digest": "pack-digest-1b119bfe385002e2505b416ece164f5b8c4b28c60dda8d8c726dc4542519f943",
        "corpus_manifest_sha256": "5493933d2bba7ce80ede3c367e865635c4bd410d702b64a103d916d4573b95f2",
    },
    "measurement_methodology": "No new LLM calls were made to produce this baseline. Stage A and Stage D "
        "figures are read from already-persisted, real commissioning artifacts from when those stages were "
        "originally run against the real corpus. The deterministic chain (Evidence through Executive "
        "Briefing Pack) WAS freshly re-executed (zero LLM calls, $0 cost) as part of both the "
        "instrumentation-correctness check (Section 15) and this baseline. Stage A and the deterministic "
        "chain reflect the CURRENT frozen authoritative lineage; Stage D's only measured data (both the one "
        "PASS run and the token-instrumented diagnostic rerun) predates the final Stage B/C hardening and "
        "is explicitly flagged superseded-lineage below -- Stage D is not part of the EOB->Pack chain and "
        "was not rerun for this baseline.",
    "totals": {
        "stage_a_wall_seconds": stage_a_boundary["elapsed_seconds"],
        "stage_a_llm_calls_measured": None,
        "stage_a_input_tokens_measured": None,
        "stage_a_output_tokens_measured": None,
        "stage_a_cost": "UNAVAILABLE (no token telemetry captured by the run that produced this baseline's Stage A data; new instrumentation now exists in extractor.py but was not exercised, to avoid new LLM spend)",
        "stage_d_wall_seconds_authoritative_pass": phase4_status["elapsed_seconds"],
        "stage_d_wall_seconds_diagnostic": 48.638,
        "stage_d_llm_calls_measured": 2,
        "stage_d_input_tokens_measured": 146601 + 146624,
        "stage_d_output_tokens_measured": 1411 + 1535,
        "stage_d_cost": "UNAVAILABLE (no authoritative per-token pricing encoded anywhere in this repository; "
                        "reporting a dollar figure would require inventing a price assumption, which this "
                        "baseline does not do)",
        "deterministic_chain_wall_seconds": deterministic_total,
        "combined_cross_lineage_approximate_wall_seconds": round(
            stage_a_boundary["elapsed_seconds"] + phase4_status["elapsed_seconds"] + deterministic_total, 3),
        "combined_total_caveat": "NOT a single coherent end-to-end timed run -- Stage A, Stage D, and the "
            "deterministic chain were measured at three different points against two different lineage "
            "snapshots (see measurement_methodology). This sum is an approximation for order-of-magnitude "
            "purposes only.",
        "total_api_cost": "UNAVAILABLE -- see stage_a_cost / stage_d_cost",
    },
    "stage_a_documents": stage_a_docs,
    "stage_a_summary": {
        "documents_recovered_truncated": [d["path"] for d in recovered],
        "documents_recovered_truncated_count": len(recovered),
        "highest_record_count_document": highest_records["path"],
        "highest_record_count": highest_records["total_records"],
        "highest_parsed_character_document": highest_chars["path"],
        "highest_parsed_characters": highest_chars["parsed_characters"],
        "lowest_parsed_character_document": lowest_chars["path"],
        "lowest_parsed_characters": lowest_chars["parsed_characters"],
        "fastest_slowest_document_by_time": "UNAVAILABLE -- per-document wall time was never captured",
        "highest_token_document": "UNAVAILABLE -- per-document token counts were never captured",
        "tokens_per_parsed_character": "UNAVAILABLE -- no token counts exist to compute this ratio",
        "time_per_stage_a_record": "UNAVAILABLE at document granularity; aggregate only: "
            f"{round(stage_a_boundary['elapsed_seconds'] / stage_a_boundary['total_records'], 4)} s/record "
            "across all 16 documents combined",
    },
    "critical_path_deterministic_chain": critical_path,
    "instrumentation_added": {
        "files_changed": ["extractor.py", "tests/test_stage_a_extraction_reliability.py"],
        "description": "Added an optional, additive `telemetry: list | None = None` parameter to "
            "extract_document_facts()/_extract_chunk_facts(), mirroring the existing, already-tested Stage D "
            "response-checkpoint token-usage capture pattern. Default None is a complete no-op for every "
            "existing caller. When supplied, each chunk-level API call appends one record (filename, "
            "chunk_chars, latency_seconds, input_tokens, output_tokens, stop_reason) to the caller-owned "
            "list -- never written to disk, never part of the returned facts dict, never required for "
            "successful execution.",
        "exercised_in_this_baseline": False,
        "reason_not_exercised": "Exercising it requires a live Stage A rerun (16 documents, 2245.556s "
            "measured previously) -- real API cost. Not spent for this measurement-only baseline; the "
            "capability now exists for a future, explicitly-authorized instrumented rerun.",
    },
    "correctness_invariance": {
        "final_pack_id_before": "pack-b11fe92992b988d51edba6077dc7f1999d864838a7e01acd7e332b3b3faeb600",
        "final_pack_id_after": "pack-b11fe92992b988d51edba6077dc7f1999d864838a7e01acd7e332b3b3faeb600",
        "final_pack_revision_before": "pack-revision-8b3b21c79dd82605e7ea70ad5d622905aae826dddd1ce4b343fdb4ad8e945ebe",
        "final_pack_revision_after": "pack-revision-8b3b21c79dd82605e7ea70ad5d622905aae826dddd1ce4b343fdb4ad8e945ebe",
        "final_pack_digest_before": "pack-digest-1b119bfe385002e2505b416ece164f5b8c4b28c60dda8d8c726dc4542519f943",
        "final_pack_digest_after": "pack-digest-1b119bfe385002e2505b416ece164f5b8c4b28c60dda8d8c726dc4542519f943",
        "identical": True,
        "verification_run_id": "briefingpack-boc-2026-026-20260912T184942Z-f775ca",
        "full_suite_result": {"passed": 1249, "skipped": 2, "failed": 0, "subtests_passed": 19},
    },
}
(OUT / "PERFORMANCE_BASELINE.json").write_text(json.dumps(baseline, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

print("Wrote:")
print(" ", OUT / "PERFORMANCE_BASELINE.json")
print(" ", OUT / "stage_timings.json")
print(" ", OUT / "llm_calls.jsonl")
print()
print("Stage A wall seconds:", stage_a_boundary["elapsed_seconds"])
print("Stage D authoritative-pass wall seconds:", phase4_status["elapsed_seconds"])
print("Deterministic chain total:", deterministic_total)
print("Recovered/truncated docs:", [d["path"] for d in recovered])
