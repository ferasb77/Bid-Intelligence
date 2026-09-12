"""Probe: run the real, deterministic Opportunity Intelligence analyst
against real Stage B/C output and report what it actually produces --
before designing the publication wiring around assumptions.
"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--input-dir", required=True, type=Path)
args = parser.parse_args()

from opportunity_intelligence import analyze_opportunity

normalized = json.loads((args.input_dir / "stage-c-normalized-facts.json").read_text(encoding="utf-8"))
conflicts = json.loads((args.input_dir / "stage-c-conflicts.json").read_text(encoding="utf-8"))

analysis = analyze_opportunity(normalized, conflicts, context_id="opportunity:bank-of-canada-rfp-2026-026-original")

print("analysis_id:", analysis.analysis_id)
print("overall_confidence:", analysis.overall_confidence)
print("evidence_used count:", len(analysis.evidence_used))
entity_types = sorted({item.entity_type.value for item in analysis.evidence_used})
print("evidence_used entity_types:", entity_types)
print("computed_facts:", len(analysis.computed_facts))
print("inferences:", len(analysis.inferences))
print("hypotheses:", len(analysis.hypotheses))
print("assumptions:", len(analysis.assumptions))
print("unanswered_questions:", len(analysis.unanswered_questions))
print("unknowns.missing_evidence:", len(analysis.unknowns.missing_evidence))
print("unknowns.unresolved_conflict_ids:", len(analysis.unknowns.unresolved_conflict_ids))
print("unknowns.ambiguous_observation_ids:", len(analysis.unknowns.ambiguous_observation_ids))
print("limitations:", len(analysis.limitations))

# Which entity_types actually get cited by the substantive conclusions
# (computed_facts / inferences / hypotheses), not just declared available?
cited_types = set()
for fact in analysis.computed_facts:
    for link in fact.evidence_support:
        cited_types.add(link.entity_type.value)
for inf in analysis.inferences:
    for link in inf.statement.evidence_support:
        cited_types.add(link.entity_type.value)
for hyp in analysis.hypotheses:
    for link in hyp.supporting_evidence + hyp.contradicting_evidence:
        cited_types.add(link.entity_type.value)
print("entity_types actually cited by conclusions:", sorted(cited_types))
