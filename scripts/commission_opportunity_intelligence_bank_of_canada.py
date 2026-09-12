"""Opportunity Intelligence boundary commissioning against the latest
authoritative lineage. Stops immediately after opportunity_intelligence.
analyze_opportunity() -- no Opportunity Intelligence Publication, Executive
Opportunity Understanding, Executive Opportunity Brief, Buyer Brief, or
Executive Briefing Pack is invoked, per instruction.

opportunity_intelligence.py's analyze() is 100% deterministic Python (no
anthropic/client.messages/get_anthropic_client reference anywhere in the
module or its decision_intelligence.py / decision_analyst.py dependencies,
confirmed by direct code reading before this script was written) -- there is
no LLM to commission here, so Section 21 of the audit spec (one real LLM
commissioning run with telemetry) does not apply; this is documented in the
report rather than assumed.
"""
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
PHASE2_RUN_ID = "phase2-boc-2026-026-stageb-canonterm-fix-20260912T142551Z-34a031"
PHASE3_RUN_ID = "phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8"
CANONOPP_RUN_ID = "canonopp-boc-2026-026-20260912T142551Z-34a031"
OPPSTRUCT_RUN_ID = "oppstruct-boc-2026-026-20260912T144353Z-dd4b10"
PHASE3_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase3_commissioning" / PHASE3_RUN_ID

RUN_ID = f"oppint-boc-2026-026-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
OUT = ROOT / "evaluation/bank_of_canada_briefing_pack/opportunity_intelligence_commissioning" / RUN_ID
OUT.mkdir(parents=True, exist_ok=False)


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n",
                             encoding="utf-8")


import copy as _copy
from decision_intelligence import Confidence, StatementType
from opportunity_intelligence import ANALYST_VERSION, analyze_opportunity

t0 = time.monotonic()

facts = json.loads((PHASE3_DIR / "stage_c_normalized_facts.json").read_text(encoding="utf-8"))
conflicts = json.loads((PHASE3_DIR / "stage_c_conflicts.json").read_text(encoding="utf-8"))
pristine_facts = _copy.deepcopy(facts)
pristine_conflicts = _copy.deepcopy(conflicts)

CONTEXT_ID = "opportunity:bank-of-canada-rfp-2026-026-corrected16"

analysis = analyze_opportunity(facts, conflicts, context_id=CONTEXT_ID)

input_mutated = facts != pristine_facts or conflicts != pristine_conflicts

elapsed = round(time.monotonic() - t0, 3)


def dump_evidence_support(link):
    return {"entity_type": link.entity_type.value, "entity_id": link.entity_id, "evidence_ids": list(link.evidence_ids)}


def dump_statement(s):
    return {
        "statement_id": s.statement_id, "statement_type": s.statement_type.value, "statement": s.statement,
        "source_type": s.source.source_type.value, "source_id": s.source.source_id,
        "confidence": s.confidence.value if s.confidence else None,
        "reasoning_status": s.reasoning_status.value,
        "evidence_ids": list(s.evidence_ids), "supporting_fact_ids": list(s.supporting_fact_ids),
        "evidence_support": [dump_evidence_support(x) for x in s.evidence_support],
        "assumptions": list(s.assumptions), "limitations": list(s.limitations),
    }


full_dump = {
    "analysis_id": analysis.analysis_id, "analyst_id": analysis.analyst_id,
    "execution_timestamp": analysis.execution_timestamp.isoformat(),
    "overall_confidence": analysis.overall_confidence.value,
    "evidence_used": [dump_evidence_support(x) for x in analysis.evidence_used],
    "computed_facts": [dump_statement(x) for x in analysis.computed_facts],
    "inferences": [{"support_status": inf.support_status.value, **dump_statement(inf.statement)} for inf in analysis.inferences],
    "hypotheses": [{
        "hypothesis_id": h.hypothesis_id, "description": h.description,
        "supporting_evidence": [dump_evidence_support(x) for x in h.supporting_evidence],
        "contradicting_evidence": [dump_evidence_support(x) for x in h.contradicting_evidence],
        "confidence": h.confidence.value, "support_status": h.support_status.value,
        "limitations": list(h.limitations),
    } for h in analysis.hypotheses],
    "recommendations": list(analysis.recommendations),
    "limitations": list(analysis.limitations),
    "assumptions": [{"assumption_id": a.assumption_id, "description": a.description} for a in analysis.assumptions],
    "unanswered_questions": [{"question_id": q.question_id, "question": q.question,
                              "related_analysis_ids": list(q.related_analysis_ids)} for q in analysis.unanswered_questions],
    "unknowns": {
        "missing_evidence": list(analysis.unknowns.missing_evidence),
        "unavailable_datasets": list(analysis.unknowns.unavailable_datasets),
        "unavailable_history": list(analysis.unknowns.unavailable_history),
        "unresolved_conflict_ids": list(analysis.unknowns.unresolved_conflict_ids),
        "ambiguous_observation_ids": list(analysis.unknowns.ambiguous_observation_ids),
    },
}
save("opportunity_intelligence_full.json", full_dump)

# --- Determinism: build twice in-memory, zero LLM, no duplicate persisted run

analysis_2 = analyze_opportunity(_copy.deepcopy(pristine_facts), _copy.deepcopy(pristine_conflicts), context_id=CONTEXT_ID)
determinism = {
    "run1_analysis_id": analysis.analysis_id, "run2_analysis_id": analysis_2.analysis_id,
    "computed_facts_identical": analysis.computed_facts == analysis_2.computed_facts,
    "inferences_identical": analysis.inferences == analysis_2.inferences,
    "hypotheses_identical": analysis.hypotheses == analysis_2.hypotheses,
    "unknowns_identical": analysis.unknowns == analysis_2.unknowns,
}
save("determinism_check.json", determinism)

git_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
run_metadata = {
    "run_id": RUN_ID, "timestamp_utc": datetime.now(timezone.utc).isoformat(), "git_commit": git_commit or "unavailable",
    "phase1_run_id": PHASE1_RUN_ID, "phase2_run_id": PHASE2_RUN_ID, "phase3_run_id": PHASE3_RUN_ID,
    "canonical_opportunity_run_id": CANONOPP_RUN_ID, "opportunity_structure_run_id": OPPSTRUCT_RUN_ID,
    "production_entry_point": "opportunity_intelligence.analyze_opportunity(normalized_facts, conflicts, context_id=...)",
    "analyst_id": "opportunity-intelligence", "analyst_version": ANALYST_VERSION,
    "llm_used": False, "llm_calls": 0, "api_cost": 0,
    "input_mutated": input_mutated,
    "elapsed_seconds": elapsed,
    "counts": {
        "evidence_used": len(analysis.evidence_used), "computed_facts": len(analysis.computed_facts),
        "inferences": len(analysis.inferences), "hypotheses": len(analysis.hypotheses),
        "recommendations": len(analysis.recommendations), "assumptions": len(analysis.assumptions),
        "unanswered_questions": len(analysis.unanswered_questions),
        "unresolved_conflict_ids": len(analysis.unknowns.unresolved_conflict_ids),
        "missing_evidence": len(analysis.unknowns.missing_evidence),
        "ambiguous_observation_ids": len(analysis.unknowns.ambiguous_observation_ids),
    },
}
save("run_metadata.json", run_metadata)

print("OPPORTUNITY INTELLIGENCE COMMISSIONING")
print(json.dumps(run_metadata, indent=2))
print()
print("DETERMINISM:", json.dumps(determinism, indent=2))
print()
print("overall_confidence:", analysis.overall_confidence.value)
print("input_mutated:", input_mutated)
print(f"Dumps at: {OUT.relative_to(ROOT)}")
