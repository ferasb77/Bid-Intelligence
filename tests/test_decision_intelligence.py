from datetime import datetime, timezone

import pytest

from decision_intelligence import (
    AlternativeHypothesis,
    AnalystContext,
    AnalystOutput,
    Confidence,
    ContractValidationError,
    DecisionStatement,
    EvidenceSupport,
    HumanDecisionRecord,
    ModeratorInput,
    ModeratorOutput,
    ReasoningGaps,
    ReasoningStatus,
    SourceType,
    SpecialistAnalyst,
    StatementSource,
    StatementType,
    SupportedEntityType,
)


def source(kind=SourceType.AUTHORITATIVE_SOURCE, source_id="document-1"):
    return StatementSource(kind, source_id)


def statement(kind=StatementType.SOURCE_FACT, **changes):
    values = {
        "statement_id": "statement-1",
        "statement_type": kind,
        "statement": "The source states a calendar date.",
        "source": source(),
        "confidence": None,
        "reasoning_status": ReasoningStatus.NOT_APPLICABLE,
        "evidence_ids": ("evidence-1",),
        "supporting_fact_ids": ("observation-1",),
        "evidence_support": (
            EvidenceSupport(SupportedEntityType.OBSERVATION, "observation-1", ("evidence-1",)),
        ),
    }
    values.update(changes)
    return DecisionStatement(**values)


@pytest.mark.parametrize("kind", list(StatementType))
def test_every_statement_has_exactly_one_classification(kind):
    changes = {}
    if kind in {StatementType.AI_INFERENCE, StatementType.HYPOTHESIS, StatementType.RECOMMENDATION}:
        changes.update(source=source(SourceType.SPECIALIST_ANALYST, "analyst-1"),
                       confidence=Confidence.MODERATE, reasoning_status=ReasoningStatus.PROPOSED)
    elif kind == StatementType.COMPUTED_FACT:
        changes["source"] = source(SourceType.DETERMINISTIC_COMPUTATION, "calculation-1")
    elif kind == StatementType.HUMAN_DECISION:
        changes["source"] = source(SourceType.HUMAN, "user-1")
    elif kind == StatementType.UNKNOWN:
        changes.update(source=source(SourceType.SYSTEM, "system-1"),
                       confidence=Confidence.UNKNOWN, reasoning_status=ReasoningStatus.UNRESOLVED)
    if kind == StatementType.RECOMMENDATION:
        changes["recommendation_scope"] = "Decision maker consideration"
    assert statement(kind, **changes).statement_type is kind


def test_evidence_links_reuse_existing_ids_without_provenance_copy():
    item = statement()
    assert item.evidence_ids == ("evidence-1",)
    assert item.evidence_support[0].entity_id == "observation-1"
    assert not hasattr(item.evidence_support[0], "provenance")


def test_source_and_computed_facts_cannot_claim_confidence():
    with pytest.raises(ContractValidationError, match="confidence applies only"):
        statement(confidence=Confidence.HIGH)
    with pytest.raises(ContractValidationError, match="confidence applies only"):
        statement(StatementType.COMPUTED_FACT,
                  source=source(SourceType.DETERMINISTIC_COMPUTATION), confidence=Confidence.LOW)


def test_ai_inference_carries_uncertainty_and_alternatives():
    item = statement(
        StatementType.AI_INFERENCE,
        source=source(SourceType.SPECIALIST_ANALYST, "buyer-analyst"),
        confidence=Confidence.MODERATE,
        reasoning_status=ReasoningStatus.PROPOSED,
        alternative_hypotheses=(AlternativeHypothesis("hypothesis-2", "A different explanation."),),
        assumptions=("History is representative.",),
        limitations=("Only one period is available.",),
        reasoning_gaps=ReasoningGaps(missing_history=("Prior award data",),
                                    known_uncertainty=("Buyer preference is unknown",)),
    )
    assert item.alternative_hypotheses[0].hypothesis_id == "hypothesis-2"
    assert item.reasoning_gaps.missing_history == ("Prior award data",)


@pytest.mark.parametrize("changes", [
    {"statement_id": ""},
    {"statement_type": "SOURCE_FACT"},
    {"confidence": "HIGH"},
    {"reasoning_status": "NOT_APPLICABLE"},
    {"evidence_ids": ("evidence-1", "evidence-1")},
    {"source": source(SourceType.HUMAN)},
    {"recommendation_scope": "Not permitted"},
    {"evidence_ids": (), "evidence_support": (
        EvidenceSupport(SupportedEntityType.REQUIREMENT, "requirement-1", ("missing-evidence",)),)},
])
def test_invalid_states_are_rejected(changes):
    with pytest.raises(ContractValidationError):
        statement(**changes)


def test_recommendation_and_human_decision_are_separate_contracts():
    recommendation = statement(
        StatementType.RECOMMENDATION,
        source=source(SourceType.SPECIALIST_ANALYST, "commercial-analyst"),
        confidence=Confidence.HIGH,
        reasoning_status=ReasoningStatus.VALIDATED,
        recommendation_scope="Commercial review",
    )
    decision = HumanDecisionRecord(
        "decision-1", "Proceed", "Approved after review", "user-1",
        datetime(2030, 1, 1, tzinfo=timezone.utc),
        accepted_recommendation_ids=(recommendation.statement_id,),
    )
    assert recommendation.statement_type is StatementType.RECOMMENDATION
    assert decision.accepted_recommendation_ids == (recommendation.statement_id,)
    with pytest.raises(ContractValidationError, match="both accepted and rejected"):
        HumanDecisionRecord("decision-2", "Pause", "More evidence", "user-1",
                            datetime.now(timezone.utc), ("recommendation-1",), ("recommendation-1",))


def test_naive_decision_timestamp_is_rejected():
    with pytest.raises(ContractValidationError, match="timezone-aware"):
        HumanDecisionRecord("decision-1", "Proceed", "Reviewed", "user-1", datetime(2030, 1, 1))


def test_analyst_and_moderator_contracts_do_not_execute_reasoning():
    inference = statement(StatementType.AI_INFERENCE,
                          source=source(SourceType.SPECIALIST_ANALYST, "buyer-analyst"),
                          confidence=Confidence.LOW, reasoning_status=ReasoningStatus.PROPOSED)
    output = AnalystOutput("buyer-analyst", (inference,))
    inputs = ModeratorInput("context-1", (output,))
    moderated = ModeratorOutput(unresolved_questions=("What changed?",),
                                decision_considerations=("Confirm the evidence.",))
    assert inputs.analyst_outputs == (output,)
    assert moderated.unresolved_questions == ("What changed?",)
    assert SpecialistAnalyst.__dict__.get("analyze") is not None


def test_framework_is_not_imported_by_existing_production_pipeline():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    framework_modules = {
        "decision_intelligence.py",
        "decision_analyst.py",
        "opportunity_intelligence.py",
    }
    production = [path for path in root.glob("*.py") if path.name not in framework_modules]
    production += list((root / "pages").glob("*.py"))
    assert all("decision_intelligence" not in path.read_text(encoding="utf-8") for path in production)


def test_context_and_output_reject_duplicate_identity():
    context = AnalystContext("context-1", ("bid-1", "requirement-1"))
    assert context.entity_ids == ("bid-1", "requirement-1")
    with pytest.raises(ContractValidationError, match="duplicate statement IDs"):
        AnalystOutput("analyst-1", (statement(), statement()))
    with pytest.raises(ContractValidationError, match="duplicate analysts"):
        ModeratorInput("context-1", (AnalystOutput("analyst-1", ()), AnalystOutput("analyst-1", ())))
