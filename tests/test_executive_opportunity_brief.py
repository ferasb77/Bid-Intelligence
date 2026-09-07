from dataclasses import fields
import copy

from executive_opportunity_brief import build_executive_opportunity_brief, render_executive_opportunity_brief
from opportunity_intelligence import analyze_opportunity


def inputs():
    facts = {
        "requirements": [
            {"req_id": "r-cv", "category": "Mandatory", "evidence_status": "READY", "description": "Provide CVs and personnel credentials", "evidence_id": "e-cv"},
            {"req_id": "r-case", "category": "Mandatory", "evidence_status": "MISSING", "description": "Provide two case studies and client references", "evidence_id": "e-case"},
        ],
        "evaluation_criteria": [{"criterion_id": "c1", "hierarchy_level": 2, "weight": "60%"}],
        "submission_rules": [{"artifact_id": "a1", "mandatory": None, "submission_channel": "Portal"}],
        "dates": [], "deliverables": [], "commercial_clauses": [],
        "conflicts": [{"conflict_id": "conflict-1", "conflict_type": "DATE_CONFLICT", "topic": "Submission time", "reason": "Two times are stated."}],
        "_canonical_opportunity": {"observations": [], "resolved": {}, "conflicts": []},
    }
    synthesis = {"bid": {"title": "Leadership Services", "client": "Example Buyer", "file_number": "RFP-1", "submission_deadline": "2030-02-01"},
                 "brief": {"executive_summary": "Leadership development services.", "opportunity_type": "Services RFP", "contract_term": "Three years", "scope_categories": ["Leadership Development", "Executive Coaching"]}}
    analysis = analyze_opportunity(facts, facts["conflicts"], context_id="opportunity-1")
    return facts, synthesis, analysis


def test_sections_preserve_fact_observation_question_and_unknown_boundaries():
    facts, synthesis, analysis = inputs()
    brief = build_executive_opportunity_brief(facts, synthesis, analysis)
    assert brief.executive_snapshot and brief.opportunity_structure
    assert tuple(item.text for item in brief.key_observations) == tuple(item.statement.statement for item in analysis.inferences)
    assert tuple(item.text for item in brief.management_questions) == tuple(item.question for item in analysis.unanswered_questions)
    assert brief.known_unknowns.missing_evidence == ("r-case",)
    assert brief.known_unknowns.unresolved_conflicts == ("conflict-1",)


def test_evidence_is_preserved_for_facts_observations_and_team_inputs():
    facts, synthesis, analysis = inputs()
    brief = build_executive_opportunity_brief(facts, synthesis, analysis)
    assert all(item.evidence for item in (*brief.executive_snapshot, *brief.opportunity_structure, *brief.key_observations, *brief.information_required_from_team))
    assert any("e-cv" in link.evidence_ids for item in brief.information_required_from_team for link in item.evidence)


def test_clarification_candidates_preserve_conflict_without_advice():
    facts, synthesis, analysis = inputs()
    brief = build_executive_opportunity_brief(facts, synthesis, analysis)
    assert brief.clarification_candidates[0].candidate_id == "conflict-1"
    assert brief.clarification_candidates[0].reason == "Two times are stated."


def test_separate_pipeline_conflicts_are_supported():
    facts, synthesis, analysis = inputs()
    conflicts = facts.pop("conflicts")
    brief = build_executive_opportunity_brief(
        facts, synthesis, analysis, conflicts=conflicts)
    assert brief.clarification_candidates[0].candidate_id == "conflict-1"
    assert brief.known_unknowns.unresolved_conflicts == ("conflict-1",)


def test_output_is_stable_and_input_is_not_mutated():
    facts, synthesis, analysis = inputs()
    before = copy.deepcopy((facts, synthesis, analysis))
    first = build_executive_opportunity_brief(facts, synthesis, analysis)
    second = build_executive_opportunity_brief(copy.deepcopy(facts), copy.deepcopy(synthesis), copy.deepcopy(analysis))
    assert first == second
    assert render_executive_opportunity_brief(first) == render_executive_opportunity_brief(second)
    assert (facts, synthesis, analysis) == before


def test_brief_contract_has_no_recommendation_score_or_decision_fields():
    brief = build_executive_opportunity_brief(*inputs())
    names = {item.name for item in fields(brief)}
    assert not names & {"recommendations", "recommendation", "score", "ranking", "decision", "bid_no_bid", "win_probability"}
    rendered = render_executive_opportunity_brief(brief).casefold()
    assert "win probability" not in rendered and "bid / no bid" not in rendered


def test_stable_ordering_follows_authoritative_and_analysis_order():
    facts, synthesis, analysis = inputs()
    brief = build_executive_opportunity_brief(facts, synthesis, analysis)
    assert [item.value for item in brief.opportunity_structure] == ["Leadership Development", "Executive Coaching"]
    assert [item.observation_id for item in brief.key_observations] == [item.statement.statement_id for item in analysis.inferences]
