import copy
from dataclasses import replace

import pytest

from decision_intelligence import (
    Confidence, ContractValidationError, EvidenceSupport, StatementType,
    SupportedEntityType,
)
from decision_analyst import AnalystRecommendation, SupportStatus
from opportunity_intelligence import (
    OpportunityAnalysisContext, OpportunityIntelligenceAnalyst,
    analyze_opportunity, validate_opportunity_analysis,
)
from decision_intelligence import AnalystContext


def facts():
    return {
        "requirements": [
            {"req_id": "M1", "category": "Mandatory", "evidence_status": "READY"},
            {"req_id": "O1", "category": "Optional", "evidence_status": "MISSING"},
        ],
        "evaluation_criteria": [
            {"criterion_id": "c1", "hierarchy_level": 1, "weight": "60%", "threshold": "50%"},
            {"criterion_id": "c2", "hierarchy_level": 2, "weight": None, "threshold": None},
        ],
        "submission_rules": [
            {"artifact_id": "a1", "mandatory": True, "submission_channel": "Portal"},
            {"artifact_id": "a2", "mandatory": None, "submission_channel": "Email"},
        ],
        "dates": [],
        "deliverables": [{"deliverable_id": "d1", "evidence_state": "VERIFIED"}],
        "commercial_clauses": [
            {"clause_id": "cl1", "clause_kind": "LIABILITY_INDEMNITY", "evidence_state": "VERIFIED"},
            {"clause_id": "cl2", "clause_kind": "INSURANCE", "evidence_state": "UNVERIFIED"},
        ],
        "_canonical_opportunity": {
            "observations": [
                {"observation_id": "obs-clar", "family": "MILESTONE", "semantic_kind": "CLARIFICATION_DEADLINE", "date": "2030-01-01", "provenance_status": "VERIFIED"},
                {"observation_id": "obs-sub", "family": "MILESTONE", "semantic_kind": "SUBMISSION_DEADLINE", "date": "2030-01-11", "provenance_status": "VERIFIED"},
                {"observation_id": "obs-partial", "family": "MILESTONE", "semantic_kind": "AWARD_DATE", "normalized_value": "2030-02", "precision": "MONTH", "provenance_status": "PARTIAL"},
                {"observation_id": "obs-money", "family": "MONETARY", "semantic_kind": "ESTIMATED_CONTRACT_VALUE", "provenance_status": "VERIFIED"},
            ],
            "resolved": {
                "clarification_deadline": {"status": "RESOLVED", "value": {"date": "2030-01-01"}},
                "submission_deadline": {"status": "RESOLVED", "value": {"date": "2030-01-11"}},
            },
            "conflicts": [],
        },
    }


def metrics(output):
    return {item.statement_id.removeprefix("oi-computed-"): item.statement.split("=", 1)[1]
            for item in output.computed_facts}


def test_requirement_and_evaluation_computations():
    result = analyze_opportunity(facts(), context_id="opportunity-1")
    values = metrics(result)
    assert values["total_requirements"] == "2"
    assert values["mandatory_requirements"] == "1"
    assert values["optional_requirements"] == "1"
    assert values["evaluation_hierarchy_depth"] == "2"
    assert values["weighted_criteria"] == "1"
    assert values["criteria_missing_weights"] == "1"
    assert values["threshold_count"] == "1"


def test_total_conflicts_does_not_double_count_canonical_conflicts_already_merged():
    """reconcile_package_facts() (real Stage C) always merges canonical
    opportunity's own conflicts into the list it returns, so the `conflicts`
    parameter already contains them in every real invocation. Counting
    len(conflicts) + len(canonical conflicts) on top of that double-counts
    the same conflicts; the count must reflect distinct conflicts."""
    value = facts()
    canonical_conflict = {"conflict_id": "conf-shared", "state": "ACTIVE", "semantic_kind": "OPPORTUNITY_TITLE"}
    value["_canonical_opportunity"]["conflicts"] = [canonical_conflict]
    # Real Stage C behavior: the returned conflicts list already includes it.
    merged_conflicts = [canonical_conflict, {"conflict_id": "conf-eval-1", "conflict_type": "EVALUATION_CONFLICT"}]
    result = analyze_opportunity(value, merged_conflicts, context_id="opportunity-1")
    assert metrics(result)["total_conflicts"] == "2"


def test_total_conflicts_still_correct_when_conflicts_do_not_already_include_canonical():
    value = facts()
    value["_canonical_opportunity"]["conflicts"] = [{"conflict_id": "conf-canonical-only", "state": "ACTIVE"}]
    result = analyze_opportunity(value, [{"conflict_id": "conf-eval-1", "conflict_type": "EVALUATION_CONFLICT"}],
                                 context_id="opportunity-1")
    assert metrics(result)["total_conflicts"] == "2"


def test_unresolved_milestone_conflicts_counts_conflicted_term_and_deadline_fields():
    """The check must key on the resolved FIELD NAME (submission_deadline,
    clarification_deadline, contract_term), not the state dict's own
    stringified content -- a conflicted field's state dict never literally
    spells DATE/DEADLINE/TERM, so checking its content could never match."""
    value = facts()
    value["_canonical_opportunity"]["resolved"]["contract_term"] = {"status": "CONFLICTED", "value": None, "conflict_ids": ["conf-term"]}
    result = analyze_opportunity(value, context_id="opportunity-1")
    assert metrics(result)["unresolved_milestone_conflicts"] == "1"


def test_unresolved_milestone_conflicts_ignores_conflicted_non_date_fields():
    value = facts()
    value["_canonical_opportunity"]["resolved"]["client"] = {"status": "CONFLICTED", "value": None, "conflict_ids": ["conf-client"]}
    result = analyze_opportunity(value, context_id="opportunity-1")
    assert metrics(result)["unresolved_milestone_conflicts"] == "0"


def test_submission_timeline_and_commercial_computations():
    values = metrics(analyze_opportunity(facts(), context_id="opportunity-1"))
    assert values["submission_artifact_count"] == "2"
    assert values["submission_pathway_count"] == "2"
    assert values["mandatory_artifact_count"] == "1"
    assert values["unresolved_submission_ambiguity"] == "1"
    assert values["clarification_to_submission_days"] == "10"
    assert values["partial_date_count"] == "1"
    assert values["verified_clause_counts"] == '{"LIABILITY_INDEMNITY":1}'
    assert values["deliverable_count"] == "1"
    assert values["monetary_observation_count"] == "1"


def test_dates_entries_duplicating_a_canonical_milestone_are_not_double_counted():
    # Real production evidence: Stage A's legacy "dates" section frequently
    # restates a date already captured, independently and already
    # reconciled, as a typed_observations MILESTONE. Re-merging both must
    # not inflate milestone_completeness.observed.
    value = facts()
    value["dates"] = [{"milestone": "Question Deadline", "date": "2030-01-01", "source_doc": "a.pdf"},
                       {"milestone": "Bid Closing", "date": "2030-01-11", "source_doc": "a.pdf"}]
    values = metrics(analyze_opportunity(value, context_id="opportunity-1"))
    completeness = values["milestone_completeness"]
    # 2 canonical MILESTONE observations parse to a date (clarification,
    # submission -- the PARTIAL award-date has no parseable day); the two
    # duplicate "dates" entries add nothing further. Before this change,
    # "observed" summed the raw MILESTONE family count (3, including the
    # unparsed award-date) with len(dates) (2), inflating it to 5.
    assert completeness == '{"dated":2,"observed":2}'


def test_undated_dates_entry_is_preserved_not_lost():
    # A dates entry with no parseable date names a real milestone the
    # governed MILESTONE family cannot yet express -- this is the one piece
    # of information "dates" carries that is not already redundant, and it
    # must survive as visible, evidence-derived content rather than being
    # silently dropped.
    value = facts()
    value["dates"] = [{"milestone": "Agreement Commencement Date", "date": None, "source_doc": "g.docx"}]
    result = analyze_opportunity(value, context_id="opportunity-1")
    values = metrics(result)
    assert values["undated_milestone_labels"] == '["Agreement Commencement Date"]'
    completeness = values["milestone_completeness"]
    assert completeness == '{"dated":2,"observed":3}'
    assert any("Agreement Commencement Date" in item for item in result.limitations)


def test_dates_entries_never_require_their_own_governed_reference():
    # "dates" records must never appear as individually citable evidence --
    # no publication owns them, and none of the analyst's own computed
    # facts about milestones cite an individual dates record (they cite the
    # analysis-level root, exactly like every other package-level metric).
    value = facts()
    value["dates"] = [{"milestone": "Agreement Commencement Date", "date": None, "source_doc": "g.docx"},
                       {"milestone": "Question Deadline", "date": "2030-01-01", "source_doc": "a.pdf"}]
    result = analyze_opportunity(value, context_id="opportunity-1")
    # Before this change, each dates record got its own FUTURE_ENTITY
    # support keyed by an "oi-dates-..." hash -- no publication anywhere
    # can supply a governed reference for that id (confirmed by live
    # commissioning). No such entity may exist any more.
    assert not any(item.entity_id.startswith("oi-dates-") for item in result.evidence_used)


def test_evidence_closure_and_confidence_rules():
    result = analyze_opportunity(facts(), context_id="opportunity-1")
    declared = set(result.evidence_used)
    assert all(link in declared for item in result.computed_facts for link in item.evidence_support)
    assert all(item.confidence is None for item in result.computed_facts)
    assert all(item.statement.confidence in Confidence for item in result.inferences)


def test_hypotheses_are_unranked_and_linked():
    value = facts()
    value["requirements"] *= 11
    result = analyze_opportunity(value, context_id="opportunity-1")
    assert result.hypotheses
    assert all(not hasattr(item, "rank") and item.supporting_evidence for item in result.hypotheses)


def test_unknowns_and_management_question_preserve_conflicts():
    conflict = {"conflict_id": "conflict-1", "conflict_type": "DATE_CONFLICT"}
    result = analyze_opportunity(facts(), [conflict], context_id="opportunity-1")
    assert result.unknowns.unresolved_conflict_ids == ("conflict-1",)
    assert result.unanswered_questions
    assert "management" in result.unanswered_questions[0].question.lower()


def test_no_recommendations_or_decisions():
    result = analyze_opportunity(facts(), context_id="opportunity-1")
    assert result.recommendations == ()
    assert all(item.statement_type is not StatementType.HUMAN_DECISION for item in result.computed_facts)
    assert all(item.statement.statement_type is StatementType.AI_INFERENCE for item in result.inferences)


def test_identical_input_has_deterministic_content_and_ordering():
    first = analyze_opportunity(facts(), context_id="opportunity-1")
    second = analyze_opportunity(copy.deepcopy(facts()), context_id="opportunity-1")
    assert first.analysis_id == second.analysis_id
    assert first.computed_facts == second.computed_facts
    assert first.inferences == second.inferences
    assert first.hypotheses == second.hypotheses
    assert first.unknowns == second.unknowns


def test_input_is_not_mutated_and_replay_shape_is_compatible():
    value = facts()
    before = copy.deepcopy(value)
    analyze_opportunity(value, context_id="opportunity-1")
    assert value == before
    replay = copy.deepcopy(value)
    replay["commercial_clauses"].append({"clause_id": "old-unverified", "evidence_state": "UNVERIFIED"})
    result = analyze_opportunity(replay, context_id="opportunity-1")
    assert metrics(result)["verified_clause_counts"] == '{"LIABILITY_INDEMNITY":1}'


@pytest.mark.parametrize("bad", [
    {"requirements": "not-a-list"},
    {"requirements": ["not-a-record"]},
    {"_canonical_opportunity": "not-a-mapping"},
])
def test_invalid_input_rejected(bad):
    value = facts(); value.update(bad)
    with pytest.raises(ContractValidationError):
        analyze_opportunity(value, context_id="opportunity-1")


def test_validator_rejects_recommendations_and_omitted_conflicts():
    conflict = {"conflict_id": "conflict-1", "conflict_type": "DATE_CONFLICT"}
    context = OpportunityAnalysisContext(AnalystContext("opportunity-1", ("opportunity-1",)), facts(), (conflict,))
    result = OpportunityIntelligenceAnalyst().analyze(context)
    with pytest.raises(ContractValidationError, match="unresolved conflict"):
        validate_opportunity_analysis(context, replace(result, unknowns=replace(
            result.unknowns, unresolved_conflict_ids=())))
    recommendation = AnalystRecommendation(
        "recommendation-1", "pursuit", "Bid", (result.computed_facts[0].statement_id,),
        Confidence.MODERATE, SupportStatus.PARTIALLY_SUPPORTED,
    )
    with pytest.raises(ContractValidationError, match="cannot emit recommendations"):
        validate_opportunity_analysis(context, replace(result, recommendations=(recommendation,)))


def test_validator_rejects_evidence_absent_from_authoritative_context():
    context = OpportunityAnalysisContext(
        AnalystContext("opportunity-1", ("opportunity-1",)), facts())
    result = OpportunityIntelligenceAnalyst().analyze(context)
    invented = EvidenceSupport(SupportedEntityType.REQUIREMENT, "invented-requirement")
    with pytest.raises(ContractValidationError, match="absent from authoritative context"):
        validate_opportunity_analysis(context, replace(
            result, evidence_used=(*result.evidence_used, invented)))


def test_optional_integration_does_not_import_into_existing_pipeline():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    protected = [root / name for name in ("extractor.py", "canonical_opportunity.py",
                                           "contract_hygiene.py", "stage_d_projection.py",
                                           "stage_d_checkpoints.py", "database.py")]
    assert all("opportunity_intelligence" not in path.read_text(encoding="utf-8") for path in protected)
