from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from decision_intelligence import (
    AnalystContext, Confidence, ContractValidationError, DecisionStatement,
    EvidenceSupport, ReasoningStatus, SourceType, StatementSource,
    StatementType, SupportedEntityType,
)
from decision_analyst import (
    AgreementGroup, AnalysisReference, AnalystAssumption, AnalystHypothesis,
    AnalystReasoning, AnalystRecommendation, AnalystUnknowns, DecisionAnalysis,
    DecisionAnalysisCollection, DecisionAnalystMetadata, DecisionAnalystRegistry,
    DisagreementGroup, ManagementConsiderationGroup, ManagementQuestion,
    OpenQuestionGroup, SupportStatus,
)


EVIDENCE = EvidenceSupport(SupportedEntityType.OBSERVATION, "observation-1", ("evidence-1",))


def computed(statement_id="computed-1"):
    return DecisionStatement(statement_id, StatementType.COMPUTED_FACT, "Computed pattern",
                             StatementSource(SourceType.DETERMINISTIC_COMPUTATION, "method-1"),
                             None, ReasoningStatus.VALIDATED, ("evidence-1",),
                             ("observation-1",), (EVIDENCE,))


def inference(statement_id="inference-1"):
    item = DecisionStatement(statement_id, StatementType.AI_INFERENCE, "Possible explanation",
                             StatementSource(SourceType.SPECIALIST_ANALYST, "analyst-a"),
                             Confidence.MODERATE, ReasoningStatus.PROPOSED, ("evidence-1",),
                             ("observation-1",), (EVIDENCE,), assumptions=("Input is comparable",))
    return AnalystReasoning(item, SupportStatus.PARTIALLY_SUPPORTED)


def analysis(analysis_id="analysis-a", analyst_id="analyst-a"):
    return DecisionAnalysis(
        analysis_id, analyst_id, datetime(2030, 1, 1, tzinfo=timezone.utc), Confidence.MODERATE,
        (EVIDENCE,), computed_facts=(computed(f"{analysis_id}-computed"),),
        inferences=(inference(f"{analysis_id}-inference"),),
        hypotheses=(AnalystHypothesis(f"{analysis_id}-hypothesis", "Alternative explanation",
                                      (EVIDENCE,), (), Confidence.LOW, SupportStatus.UNKNOWN,
                                      ("History is unavailable",)),),
        recommendations=(AnalystRecommendation(
            f"{analysis_id}-recommendation", "REVIEW", "Management review is warranted",
            (f"{analysis_id}-inference",), Confidence.MODERATE, SupportStatus.PARTIALLY_SUPPORTED),),
        limitations=("One source period",),
        assumptions=(AnalystAssumption("assumption-1", "Comparable records exist"),),
        unanswered_questions=(ManagementQuestion("question-1", "Which trade-off is preferred?",
                                                  (f"{analysis_id}-inference",)),),
        unknowns=AnalystUnknowns(missing_evidence=("Independent confirmation",),
                                 unavailable_datasets=("Historical dataset",),
                                 unresolved_conflict_ids=("conflict-1",)),
    )


class FakeAnalyst:
    def __init__(self, analyst_id, version="1.0.0"):
        self._metadata = DecisionAnalystMetadata(
            analyst_id, analyst_id.title(), version, "test-domain",
            frozenset({StatementType.COMPUTED_FACT, StatementType.AI_INFERENCE,
                       StatementType.HYPOTHESIS, StatementType.RECOMMENDATION}),
            frozenset({SupportedEntityType.OBSERVATION}),
        )

    @property
    def metadata(self):
        return self._metadata

    def analyze(self, context):
        return analysis(analyst_id=self.metadata.analyst_id)


def test_contracts_are_immutable():
    item = analysis()
    with pytest.raises(FrozenInstanceError):
        item.analysis_id = "changed"
    with pytest.raises(FrozenInstanceError):
        item.evidence_used[0].entity_id = "changed"


def test_registry_discovery_is_deterministic():
    registry = DecisionAnalystRegistry()
    registry.register(FakeAnalyst("zeta"))
    registry.register(FakeAnalyst("alpha"))
    assert [item.analyst_id for item in registry.discover()] == ["alpha", "zeta"]


def test_registry_rejects_duplicate_analyst():
    registry = DecisionAnalystRegistry()
    registry.register(FakeAnalyst("alpha"))
    with pytest.raises(ContractValidationError, match="duplicate analyst"):
        registry.register(FakeAnalyst("alpha", "2.0.0"))


@pytest.mark.parametrize(("available", "required", "expected"), [
    ("1.0.0", "1.0.0", True), ("1.2.0", "1.1.9", True),
    ("1.0.0", "1.1.0", False), ("2.0.0", "1.9.9", False),
])
def test_version_compatibility(available, required, expected):
    assert DecisionAnalystRegistry.is_compatible(available, required) is expected


def test_registry_get_enforces_version_compatibility():
    registry = DecisionAnalystRegistry()
    analyst = FakeAnalyst("alpha", "1.2.0")
    registry.register(analyst)
    assert registry.get("alpha", "1.1.0") is analyst
    with pytest.raises(ContractValidationError, match="incompatible"):
        registry.get("alpha", "2.0.0")


def test_registry_validates_output_identity_and_declared_capabilities():
    registry = DecisionAnalystRegistry()
    analyst = FakeAnalyst("alpha")
    registry.register(analyst)
    output = analysis(analyst_id="alpha")
    assert registry.validate_output("alpha", output) is output
    with pytest.raises(ContractValidationError, match="registered analyst"):
        registry.validate_output("alpha", analysis(analyst_id="other"))
    limited = FakeAnalyst("limited")
    object.__setattr__(limited, "_metadata", DecisionAnalystMetadata(
        "limited", "Limited", "1.0.0", "test-domain",
        frozenset({StatementType.COMPUTED_FACT}),
        frozenset({SupportedEntityType.OBSERVATION}),
    ))
    registry.register(limited)
    with pytest.raises(ContractValidationError, match="statement capabilities"):
        registry.validate_output("limited", analysis(analyst_id="limited"))


def test_analysis_reuses_evidence_links_and_does_not_copy_provenance():
    item = analysis()
    assert item.evidence_used == (EVIDENCE,)
    assert item.inferences[0].statement.evidence_support == (EVIDENCE,)
    assert not hasattr(item.evidence_used[0], "provenance")


def test_multiple_hypotheses_are_preserved_without_ranking():
    first = AnalystHypothesis("h1", "First", (EVIDENCE,), (), Confidence.LOW, SupportStatus.UNKNOWN)
    second = AnalystHypothesis("h2", "Second", (), (EVIDENCE,), Confidence.HIGH,
                               SupportStatus.NOT_SUPPORTED)
    value = analysis()
    value = DecisionAnalysis(value.analysis_id, value.analyst_id, value.execution_timestamp,
                             value.overall_confidence, value.evidence_used,
                             hypotheses=(first, second))
    assert [item.hypothesis_id for item in value.hypotheses] == ["h1", "h2"]
    assert not hasattr(first, "rank")


def test_assumptions_unknowns_recommendations_and_questions_are_explicit():
    item = analysis()
    assert item.assumptions[0].description == "Comparable records exist"
    assert item.unknowns.unavailable_datasets == ("Historical dataset",)
    assert item.recommendations[0].supporting_analysis == ("analysis-a-inference",)
    assert item.unanswered_questions[0].question == "Which trade-off is preferred?"
    assert not hasattr(item.recommendations[0], "decision")


@pytest.mark.parametrize("factory", [
    lambda: DecisionAnalystMetadata("a", "A", "invalid", "domain",
                                    frozenset({StatementType.AI_INFERENCE}),
                                    frozenset({SupportedEntityType.OBSERVATION})),
    lambda: DecisionAnalystMetadata("a", "A", "1.0.0", "domain",
                                    frozenset({StatementType.HUMAN_DECISION}),
                                    frozenset({SupportedEntityType.OBSERVATION})),
    lambda: AnalystHypothesis("h", "H", (), (), Confidence.UNKNOWN, SupportStatus.UNKNOWN),
    lambda: AnalystRecommendation("r", "REVIEW", "R", (), Confidence.LOW, SupportStatus.UNKNOWN),
    lambda: DecisionAnalysis("a", "x", datetime(2030, 1, 1), Confidence.UNKNOWN, (EVIDENCE,)),
])
def test_invalid_contract_states_are_rejected(factory):
    with pytest.raises(ContractValidationError):
        factory()


def test_analysis_rejects_evidence_outside_declared_evidence_used():
    with pytest.raises(ContractValidationError, match="absent from evidence_used"):
        DecisionAnalysis("a", "analyst", datetime.now(timezone.utc), Confidence.LOW, (),
                         computed_facts=(computed(),))


def test_analysis_rejects_unknown_recommendation_support():
    with pytest.raises(ContractValidationError, match="unknown supporting analysis"):
        DecisionAnalysis("a", "analyst", datetime.now(timezone.utc), Confidence.LOW, (EVIDENCE,),
                         recommendations=(AnalystRecommendation(
                             "r", "REVIEW", "Review", ("missing",), Confidence.LOW,
                             SupportStatus.UNKNOWN),))


def test_collection_integrity_and_moderator_ready_groups():
    first, second = analysis("analysis-a", "analyst-a"), analysis("analysis-b", "analyst-b")
    left = AnalysisReference("analysis-a", "analysis-a-inference")
    right = AnalysisReference("analysis-b", "analysis-b-inference")
    collection = DecisionAnalysisCollection(
        "collection-1", (first, second),
        agreements=(AgreementGroup("agreement-1", "Shared interpretation", (left, right)),),
        disagreements=(DisagreementGroup("disagreement-1", "Confidence differs", (left, right)),),
        open_questions=(OpenQuestionGroup("questions-1", (
            ManagementQuestion("q1", "Which uncertainty is acceptable?"),)),),
        management_considerations=(ManagementConsiderationGroup(
            "considerations-1", ("Human judgment is required",), (left, right)),),
    )
    assert len(collection.analyses) == 2
    assert collection.agreements[0].members == (left, right)


def test_collection_rejects_unknown_or_duplicate_analyses():
    item = analysis()
    with pytest.raises(ContractValidationError, match="duplicate analysis"):
        DecisionAnalysisCollection("c", (item, item))
    with pytest.raises(ContractValidationError, match="unknown conclusion"):
        DecisionAnalysisCollection(
            "c", (item,), management_considerations=(ManagementConsiderationGroup(
                "g", ("Review",), (AnalysisReference("analysis-a", "missing"),)),))


def test_existing_production_modules_do_not_import_phase2():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    production = [path for path in root.glob("*.py")
                  if path.name not in {
                      "decision_analyst.py",
                      "decision_intelligence.py",
                      "opportunity_intelligence.py",
                      "decision_workspace.py",
                      "executive_opportunity_brief.py",
                  }]
    production += list((root / "pages").glob("*.py"))
    assert all("decision_analyst" not in path.read_text(encoding="utf-8") for path in production)


def test_fake_analyst_contract_is_domain_neutral():
    analyst = FakeAnalyst("future-analyst")
    output = analyst.analyze(AnalystContext("context-1", ("entity-1",)))
    assert output.analyst_id == "future-analyst"
    assert analyst.metadata.analyst_domain == "test-domain"
