"""Generate the Commissioned Baseline manifest (JSON + human-readable MD)
and the compact baseline fingerprint for the Bank of Canada RFP 2026-026
end-to-end commissioning. Read-only with respect to production code; only
writes the three baseline documentation artifacts. No LLM calls, no
production behavior change.
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CORPUS_MANIFEST = json.loads((ROOT / "evaluation/bank_of_canada_briefing_pack/corrected_corpus_manifest.json").read_text(encoding="utf-8"))
PHASE3_FACTS = json.loads((ROOT / "evaluation/bank_of_canada_briefing_pack/phase3_commissioning/phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8/stage_c_normalized_facts.json").read_text(encoding="utf-8"))
PHASE3_CONFLICTS = json.loads((ROOT / "evaluation/bank_of_canada_briefing_pack/phase3_commissioning/phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8/stage_c_conflicts.json").read_text(encoding="utf-8"))

import hashlib


def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


git_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
git_dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip())
python_version = sys.version.split()[0]

canonical = PHASE3_FACTS["_canonical_opportunity"]

BASELINE_TIMESTAMP = datetime.now(timezone.utc).isoformat()

manifest = {
    "baseline_name": "Bid Intelligence — Commissioned Baseline 1",
    "baseline_timestamp_utc": BASELINE_TIMESTAMP,
    "baseline_version_tag_candidate": "commissioned-baseline-2026-09-12",
    "corpus": {
        "corpus_id": CORPUS_MANIFEST["corpus_id"],
        "file_count": CORPUS_MANIFEST["file_count"],
        "manifest_path": "evaluation/bank_of_canada_briefing_pack/corrected_corpus_manifest.json",
        "manifest_sha256": sha("evaluation/bank_of_canada_briefing_pack/corrected_corpus_manifest.json"),
        "files": [{"path": f["path"], "sha256": f["sha256"]} for f in CORPUS_MANIFEST["files"]],
    },
    "code_state": {
        "git_commit": git_commit,
        "git_working_tree_dirty_at_manifest_time": git_dirty,
        "python_version": python_version,
        "dependency_lockfile": "requirements.txt",
        "dependency_lockfile_sha256": sha("requirements.txt"),
        "note": "git_commit above reflects HEAD at manifest-generation time, BEFORE the baseline commit. "
                "The actual baseline commit SHA is recorded separately once created (see FINAL RESPONSE / "
                "COMMISSIONED_BASELINE.md 'Baseline commit' field, added after this manifest is generated "
                "and the freeze commit is made).",
    },
    "accepted_run_lineage": [
        {
            "stage": "Phase 1 / Evidence corpus (real, real corpus, deterministic parse)",
            "run_id": "phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5",
            "path": "evaluation/bank_of_canada_briefing_pack/phase1_commissioning/phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5",
            "parent_inputs": ["corrected_procurement_corpus (16 real documents)"],
            "deterministic": True,
            "llm_generated": False,
            "authoritative": True,
        },
        {
            "stage": "Stage B (normalization, canon-term-fix)",
            "run_id": "phase2-boc-2026-026-stageb-canonterm-fix-20260912T142551Z-34a031",
            "path": "evaluation/bank_of_canada_briefing_pack/phase2_commissioning/phase2-boc-2026-026-stageb-canonterm-fix-20260912T142551Z-34a031",
            "output_digest_sha256": sha("evaluation/bank_of_canada_briefing_pack/phase2_commissioning/phase2-boc-2026-026-stageb-canonterm-fix-20260912T142551Z-34a031/stage_b_normalized_result.json"),
            "parent_inputs": ["phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5 (Stage A output, frozen)"],
            "deterministic": True,
            "llm_generated": False,
            "authoritative": True,
            "note": "The current authoritative Stage B artifact after the canonical-term/provenance work. "
                    "6 earlier phase2-boc-2026-026-stageb-* runs exist and are superseded (see superseded_artifacts).",
        },
        {
            "stage": "Stage C (cross-document reconciliation, hardened + refreshed)",
            "run_id": "phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8",
            "path": "evaluation/bank_of_canada_briefing_pack/phase3_commissioning/phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8",
            "output_digest_sha256": sha("evaluation/bank_of_canada_briefing_pack/phase3_commissioning/phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8/stage_c_normalized_facts.json"),
            "conflict_count": len(PHASE3_CONFLICTS),
            "governed_conflict_count": len(canonical.get("conflicts", [])),
            "advisory_conflict_count": len(PHASE3_CONFLICTS) - len(canonical.get("conflicts", [])),
            "parent_inputs": ["phase2-boc-2026-026-stageb-canonterm-fix-20260912T142551Z-34a031"],
            "deterministic": True,
            "llm_generated": False,
            "authoritative": True,
            "regenerated_by_provenance_granularity_remediation": False,
            "regenerated_by_conflict_identity_remediation": False,
            "note": "Stage C was NOT regenerated by either the provenance-granularity remediation or the "
                    "conflict-identity remediation -- neither touched canonical_opportunity.py's or "
                    "opportunity_structure.py's own content-producing logic (only the downstream binding/ "
                    "publication and Opportunity Intelligence support-linking layers changed). This exact "
                    "Stage C output remains authoritative and was reused, unmodified, by both remediations "
                    "and by Executive Briefing Pack commissioning.",
        },
        {
            "stage": "Canonical Opportunity (ledger, resolved)",
            "run_id": "canonopp-boc-2026-026-20260912T142551Z-34a031",
            "path": "evaluation/bank_of_canada_briefing_pack/canonical_opportunity_commissioning/canonopp-boc-2026-026-20260912T142551Z-34a031",
            "input_digest": canonical["input_digest"],
            "observation_count": len(canonical.get("observations", [])),
            "governed_conflict_count": len(canonical.get("conflicts", [])),
            "parent_inputs": ["phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8"],
            "deterministic": True,
            "llm_generated": False,
            "authoritative": True,
            "note": "canonical_opportunity.py's own ledger-building/resolution logic was never modified by "
                    "either remediation; this ledger content is identical whether read from this standalone "
                    "run or recomputed inline within the EOB/pack commissioning scripts (byte-identical, "
                    "reconfirmed at freeze time). What changed downstream was the binding/publication layer "
                    "(evidence_grounding.py) and Opportunity Intelligence's conflict-support linking "
                    "(opportunity_intelligence.py), not this ledger itself.",
        },
        {
            "stage": "Canonical Opportunity Publication (governed binding + publication)",
            "run_id": "embedded in eob-boc-2026-026-20260912T173422Z-783064 and briefingpack-boc-2026-026-20260912T181328Z-c41ed9",
            "path": "evaluation/bank_of_canada_briefing_pack/executive_briefing_pack_commissioning/briefingpack-boc-2026-026-20260912T181328Z-c41ed9",
            "object_count": 134,
            "parent_inputs": ["canonical Opportunity ledger", "Evidence Publication (evidence_grounding.py-based bindings, post-provenance-remediation)"],
            "deterministic": True,
            "llm_generated": False,
            "authoritative": True,
            "note": "Not separately persisted as its own standalone commissioning directory in the current "
                    "lineage -- it is rebuilt inline, deterministically, on every EOB/pack commissioning run "
                    "from the frozen Canonical Opportunity ledger and Evidence snapshot. This is the boundary "
                    "the provenance-granularity remediation fixed and re-validated as PASS.",
        },
        {
            "stage": "Opportunity Structure (ledger)",
            "run_id": "oppstruct-boc-2026-026-20260912T144353Z-dd4b10",
            "path": "evaluation/bank_of_canada_briefing_pack/opportunity_structure_commissioning/oppstruct-boc-2026-026-20260912T144353Z-dd4b10",
            "parent_inputs": ["phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8"],
            "deterministic": True,
            "llm_generated": False,
            "authoritative": True,
            "note": "opportunity_structure.py was never modified by either remediation; identical to the "
                    "content recomputed inline in the EOB/pack commissioning scripts.",
        },
        {
            "stage": "Opportunity Structure Publication (governed binding + publication)",
            "run_id": "embedded in eob-boc-2026-026-20260912T173422Z-783064 and briefingpack-boc-2026-026-20260912T181328Z-c41ed9",
            "path": "evaluation/bank_of_canada_briefing_pack/executive_briefing_pack_commissioning/briefingpack-boc-2026-026-20260912T181328Z-c41ed9",
            "object_count": 696,
            "parent_inputs": ["Opportunity Structure ledger", "Evidence Publication"],
            "deterministic": True,
            "llm_generated": False,
            "authoritative": True,
            "note": "This is the boundary that failed before the provenance-granularity remediation "
                    "(350/692 DOCX-cited records) and passes cleanly (696 objects) after it.",
        },
        {
            "stage": "Opportunity Intelligence (analysis)",
            "run_id": "oppint-boc-2026-026-20260912T161717Z-50ab1a (historical standalone run, pre-conflict-identity-fix) "
                      "-- superseded by the corrected conflict-linking logic recomputed inline in "
                      "eob-boc-2026-026-20260912T173422Z-783064 and briefingpack-boc-2026-026-20260912T181328Z-c41ed9",
            "path": "evaluation/bank_of_canada_briefing_pack/executive_briefing_pack_commissioning/briefingpack-boc-2026-026-20260912T181328Z-c41ed9",
            "evidence_used_count": 817,
            "unresolved_conflict_ids_count": 8,
            "parent_inputs": ["Stage C conflicts + facts", "Canonical Opportunity ledger"],
            "deterministic": True,
            "llm_generated": False,
            "authoritative": True,
            "note": "The standalone oppint-* commissioning runs predate the conflict-identity remediation's "
                    "fix to opportunity_intelligence.py (governed-vs-advisory conflict linking). The "
                    "authoritative Opportunity Intelligence analysis is the one recomputed inline within the "
                    "final accepted EOB and pack runs, which include that fix. Not separately persisted as "
                    "its own standalone directory in the current lineage.",
        },
        {
            "stage": "Executive Opportunity Understanding",
            "run_id": "embedded in eob-boc-2026-026-20260912T173422Z-783064 and briefingpack-boc-2026-026-20260912T181328Z-c41ed9",
            "path": "evaluation/bank_of_canada_briefing_pack/executive_briefing_pack_commissioning/briefingpack-boc-2026-026-20260912T181328Z-c41ed9",
            "index_sections": 13,
            "coverage_records": 33,
            "deterministic": True,
            "llm_generated": False,
            "authoritative": True,
        },
        {
            "stage": "Buyer Brief",
            "run_id": "buyerbrief-boc-2026-026-20260912T162735Z-118d60",
            "path": "evaluation/bank_of_canada_briefing_pack/buyer_brief_commissioning/buyerbrief-boc-2026-026-20260912T162735Z-118d60",
            "brief_id": "buyer-brief:fe087ac591d49f2f47532e9f8d07385e78536cde0107909498a7b87ef23558eb",
            "brief_version": "buyer-brief/1",
            "parent_inputs": ["real_bank_of_canada_buyer_evidence.py (already-fetched, frozen)", "Canonical Opportunity digest"],
            "deterministic": True,
            "llm_generated": False,
            "authoritative": True,
        },
        {
            "stage": "Executive Opportunity Brief",
            "run_id": "eob-boc-2026-026-20260912T173422Z-783064",
            "path": "evaluation/bank_of_canada_briefing_pack/executive_opportunity_brief_commissioning/eob-boc-2026-026-20260912T173422Z-783064",
            "brief_id": "executive-brief-629c785ebbb8417871fc99fea4b371ec83ad0f83bb5a1cc03db7addb419b81f6",
            "brief_version": "executive-opportunity-brief/2.0.0",
            "sections": 13,
            "parent_inputs": ["Opportunity Intelligence Publication", "Executive Opportunity Understanding"],
            "deterministic": True,
            "llm_generated": False,
            "authoritative": True,
            "reproduced_at_freeze_time": True,
        },
        {
            "stage": "Executive Briefing Pack",
            "run_id": "briefingpack-boc-2026-026-20260912T181328Z-c41ed9 (freeze-time reproduction; first accepted run was briefingpack-boc-2026-026-20260912T175851Z-9d3ad5)",
            "path": "evaluation/bank_of_canada_briefing_pack/executive_briefing_pack_commissioning/briefingpack-boc-2026-026-20260912T181328Z-c41ed9",
            "pack_id": "pack-b11fe92992b988d51edba6077dc7f1999d864838a7e01acd7e332b3b3faeb600",
            "pack_revision_id": "pack-revision-8b3b21c79dd82605e7ea70ad5d622905aae826dddd1ce4b343fdb4ad8e945ebe",
            "pack_digest": "pack-digest-1b119bfe385002e2505b416ece164f5b8c4b28c60dda8d8c726dc4542519f943",
            "member_count": 2,
            "parent_inputs": ["Executive Opportunity Brief (eob-boc-2026-026-20260912T173422Z-783064)",
                              "Buyer Brief (buyerbrief-boc-2026-026-20260912T162735Z-118d60)"],
            "deterministic": True,
            "llm_generated": False,
            "authoritative": True,
        },
    ],
    "superseded_artifacts": [
        {"category": "corpus", "identifier": "old 15-document corpus (tests/fixtures/local/bank_of_canada_2026_026)",
         "reason": "superseded by the corrected 16-document corpus"},
        {"category": "pipeline", "identifier": "evaluation/bank_of_canada_briefing_pack/corrected_pipeline/",
         "reason": "historical corrected_pipeline directory, superseded by the phase1-4 + remediation lineage"},
        {"category": "pipeline", "identifier": "evaluation/bank_of_canada_briefing_pack/full_chain_commissioning/",
         "reason": "an earlier, incomplete full-chain attempt (only reaches Evidence Publication); superseded"},
        {"category": "stage_b", "identifier": "phase2-boc-2026-026-stageb-20260912T094351Z-b489a1 and 4 other "
         "pre-canonterm-fix phase2-boc-2026-026-stageb-* runs (20260912T111430Z, T111606Z, T111643Z, T125051Z, T142534Z)",
         "reason": "superseded by phase2-boc-2026-026-stageb-canonterm-fix-20260912T142551Z-34a031"},
        {"category": "stage_c", "identifier": "phase3-boc-2026-026-stagec-20260912T122355Z-4624ac, "
         "T122454Z-3b1dd9, T122912Z-0999a0, T130007Z-dd391b",
         "reason": "superseded (pre-hardening) by phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8"},
        {"category": "canonical_opportunity", "identifier": "canonopp-boc-2026-026-20260912T134859Z-97b845, "
         "T135304Z-a240c5, T135357Z-060143, T142406Z-a21a55, T142534Z-9a22dd",
         "reason": "superseded (pre-contract-term-fix) by canonopp-boc-2026-026-20260912T142551Z-34a031"},
        {"category": "opportunity_intelligence", "identifier": "oppint-boc-2026-026-20260912T161309Z-339310",
         "reason": "superseded by oppint-boc-2026-026-20260912T161717Z-50ab1a"},
        {"category": "eob_attempt", "identifier": "eob-boc-2026-026-20260912T163804Z-af7d20",
         "reason": "FAILED -- original EOB attempt that exposed the DOCX provenance-granularity defect "
                   "(Opportunity Structure Publication FAIL). Superseded, never accepted."},
        {"category": "eob_attempt", "identifier": "eob-boc-2026-026-20260912T170659Z-92ea9f",
         "reason": "FAILED -- first post-provenance-fix attempt, exposed the unrelated float/DECIMAL "
                   "serialization bug in opportunity_structure_publication.py. Superseded, never accepted."},
        {"category": "eob_attempt", "identifier": "eob-boc-2026-026-20260912T170835Z-d69370",
         "reason": "FAILED -- both publications passed, but Opportunity Intelligence Support Binding "
                   "Derivation failed on CONF-EVAL-1..4 (the conflict-identity defect). Superseded, never "
                   "accepted; the fix produced eob-boc-2026-026-20260912T173422Z-783064."},
        {"category": "pack_attempt", "identifier": "first pack script draft (context-id string mismatch, "
         "see BANK_OF_CANADA_EXECUTIVE_BRIEFING_PACK_COMMISSIONING_REPORT.md Section S)",
         "reason": "produced semantically equivalent but differently-identified briefs; not persisted as a "
                   "named run, fixed before the first accepted briefingpack-boc-2026-026-20260912T175851Z-9d3ad5 run"},
        {"category": "legacy_script", "identifier": "scripts/commission_executive_briefing_pack.py",
         "reason": "LEGACY/SUPERSEDED -- targets the superseded 15-document original corpus and invokes live "
                   "LLM Stage A/D calls. The authoritative commissioning harness for the frozen baseline is "
                   "scripts/commission_executive_briefing_pack_bank_of_canada.py. Not rewritten or deleted "
                   "per explicit instruction; documented here so it is not mistaken for the canonical harness."},
        {"category": "render_artifacts", "identifier": "output/ and tmp/ directories "
         "(Bank_of_Canada_Bid_Intelligence_Briefing_Pack.docx/.pdf and tmp/bank-pack-render/*.png)",
         "reason": "produced by evaluation/bank_of_canada_briefing_pack/render_pack.py rendering "
                   "BANK_OF_CANADA_BID_INTELLIGENCE_BRIEFING_PACK.md (an earlier product-design mockup "
                   "document) -- NOT output of executive_briefing_pack.py (which has no renderer in v1.0.0). "
                   "Unrelated to the commissioned lineage; excluded from the baseline commit."},
    ],
    "final_pack_identity": {
        "pack_id": "pack-b11fe92992b988d51edba6077dc7f1999d864838a7e01acd7e332b3b3faeb600",
        "pack_revision_id": "pack-revision-8b3b21c79dd82605e7ea70ad5d622905aae826dddd1ce4b343fdb4ad8e945ebe",
        "pack_digest": "pack-digest-1b119bfe385002e2505b416ece164f5b8c4b28c60dda8d8c726dc4542519f943",
    },
    "test_suite_result": {
        "passed": 1246, "skipped": 2, "failed": 0, "subtests_passed": 19,
        "command": "py -3.13 -m pytest -q",
    },
    "known_architectural_debt": [
        {"id": "stage_d_token_volume", "area": "Stage D", "summary": "High input-token volume, ~146k input tokens per diagnostic call observed. Not optimized in this freeze."},
        {"id": "opportunity_intelligence_status_understanding", "area": "Opportunity Intelligence", "summary": "Does not independently understand VERIFIED/PARTIAL/UNVERIFIED for most fact families. Currently conservative enough not to violate commissioning, but architectural debt."},
        {"id": "opportunity_intelligence_no_consumer", "area": "Opportunity Intelligence integration", "summary": "Currently standalone / no live application consumer."},
        {"id": "buyer_brief_v1_scope", "area": "Buyer Brief v1", "summary": "External organizational-fact brief only; procurement-context/interpretation sections intentionally empty."},
        {"id": "detail_register_conflicts_dead_field", "area": "Executive Opportunity Understanding", "summary": "DetailRegister.conflicts is dead/unrouted; conflicts currently represented through detail_register.unknowns."},
        {"id": "legacy_pack_script", "area": "Executive Briefing Pack commissioning", "summary": "Old scripts/commission_executive_briefing_pack.py targets superseded 15-document corpus/live LLM workflow."},
        {"id": "docx_evidence_granularity", "area": "Evidence Adapter", "summary": "Hierarchical SECTION binding now works (provenance-granularity remediation), but Evidence Adapter remains coarser than semantic section labels for many DOCX documents. Binding is constitutionally safe; the underlying adapter granularity limitation remains."},
        {"id": "conf_eval_advisory_identity", "area": "Conflict identity", "summary": "CONF-EVAL-N remains Stage-C-local advisory identity, not a governed citable entity. This distinction must remain explicit."},
    ],
    "known_non_blocking_limitations": [
        {"id": "source_segment_first_match", "summary": "canonical_opportunity.py's _source_segment stops at the first _locator_matches-satisfying marker rather than searching exhaustively -- a documented, safe-direction (under- not over-verification) divergence from evidence_grounding.py's exhaustive search."},
        {"id": "legacy_conflict_fallback_dormant_risk", "summary": "apply_legacy_conflict_fallback's text-keyword field matching could, if it ever fires for evaluation_criteria-shaped legacy conflicts, inject an ungoverned ordinal id into a resolved field's conflict_ids -- confirmed dormant/inactive in this corpus."},
        {"id": "float_decimal_gap_other_publications", "summary": "float/DECIMAL support is still missing from 6 other publication modules' own independent _semantic_value copies (fixed only in opportunity_structure_publication.py, where it was actually hit)."},
    ],
}

OUT_JSON = ROOT / "evaluation/bank_of_canada_briefing_pack/COMMISSIONED_BASELINE_MANIFEST.json"
OUT_JSON.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
print("Wrote", OUT_JSON)
print("git_commit (pre-freeze-commit):", git_commit)
print("git_dirty:", git_dirty)
print("python_version:", python_version)
