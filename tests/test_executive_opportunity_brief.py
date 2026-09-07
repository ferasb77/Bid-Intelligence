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
    assert brief.opportunity_at_a_glance and brief.engagement_workstreams
    assert tuple(item.observation_id for item in brief.executive_attention_areas) == tuple(item.statement.statement_id for item in analysis.inferences)
    assert tuple(item.related_analysis_ids for item in brief.kickoff_questions) == tuple(item.related_analysis_ids for item in analysis.unanswered_questions)
    assert brief.known_unknowns.missing_evidence == ("Team evidence remains outstanding for 1 documented requirement across Bid Team.",)
    assert brief.known_unknowns.unresolved_conflicts == ("Submission time: Two times are stated.",)


def test_evidence_is_preserved_for_facts_observations_and_team_inputs():
    facts, synthesis, analysis = inputs()
    brief = build_executive_opportunity_brief(facts, synthesis, analysis)
    preparations = tuple(item for group in brief.preparation_by_owner for item in group.items)
    assert all(item.evidence for item in (*brief.opportunity_at_a_glance, *brief.engagement_workstreams, *brief.opportunity_characteristics, *brief.opportunity_timeline, *brief.executive_attention_areas, *preparations))
    assert any("e-cv" in link.evidence_ids for item in preparations for link in item.evidence)


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
    assert brief.known_unknowns.unresolved_conflicts == ("Submission time: Two times are stated.",)


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
    assert not any(token in rendered for token in ("pipeline", "engine", "internal identifier"))
    assert "r-case" not in rendered and "r-cv" not in rendered


def test_stable_ordering_follows_authoritative_and_analysis_order():
    facts, synthesis, analysis = inputs()
    brief = build_executive_opportunity_brief(facts, synthesis, analysis)
    assert [item.value for item in brief.engagement_workstreams] == ["Leadership Development", "Executive Coaching"]
    assert [item.observation_id for item in brief.executive_attention_areas] == [item.statement.statement_id for item in analysis.inferences]
    rendered = render_executive_opportunity_brief(brief)
    headings = ["## Opportunity at a Glance", "## Engagement Workstreams", "## Opportunity Characteristics", "## Opportunity Timeline", "## Executive Attention Areas", "## Preparation by Owner", "## Kickoff Questions", "## Clarification Candidates", "## Known Unknowns", "## Limitations"]
    assert [rendered.index(value) for value in headings] == sorted(rendered.index(value) for value in headings)
