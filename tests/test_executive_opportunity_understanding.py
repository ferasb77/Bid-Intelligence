from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
import json

import pytest

from decision_analyst import (
    AnalystAssumption, AnalystHypothesis, AnalystReasoning, AnalystUnknowns,
    DecisionAnalysis, ManagementQuestion, SupportStatus,
)
from decision_intelligence import (
    AlternativeHypothesis, Confidence, ContractValidationError, DecisionStatement,
    EvidenceSupport, ReasoningStatus, SourceType, StatementSource, StatementType,
    SupportedEntityType,
)
from executive_opportunity_understanding import (
    CONTRACT_VERSION, ORGANIZATION_PROFILE, CoverageDisposition, ExecutiveSection,
    ExecutiveUnderstandingInput, SECTION_ORDER,
    build_executive_opportunity_understanding,
    validate_executive_opportunity_understanding,
)
from governed_reference_resolution import (
    AuthorityClass, ResolutionRequest, SemanticField, SemanticValue, SemanticValueKind,
    create_governed_object, create_governed_snapshot, create_resolution_context,
    reference_to, resolve_governed_reference,
)
from opportunity_intelligence import ANALYST_VERSION
from opportunity_intelligence_publication import (
    OpportunitySupportBinding, publish_opportunity_intelligence,
)


def _source_context():
    fact = create_governed_object(
        owner_domain="canonical-opportunity", owner_contract="canonical-opportunity",
        contract_version="1.0.0", object_class="canonical-fact",
        object_id="canonical-1", authority=AuthorityClass.CANONICAL_FACT,
        semantic_fields=(SemanticField(
            "value", SemanticValue(SemanticValueKind.STRING, "Known fact")),),
    )
    evidence = create_governed_object(
        owner_domain="canonical-opportunity", owner_contract="canonical-opportunity",
        contract_version="1.0.0", object_class="evidence", object_id="evidence-1",
        authority=AuthorityClass.EVIDENCE,
        semantic_fields=(SemanticField(
            "locator", SemanticValue(SemanticValueKind.STRING, "page 1")),),
    )
    snapshot = create_governed_snapshot(
        owner_domain="canonical-opportunity", owner_contract="canonical-opportunity",
        contract_version="1.0.0", snapshot_id="canonical-snapshot-1",
        objects=(fact, evidence),
    )
    context = create_resolution_context(
        context_id="authoritative-context-1", context_version="1.0.0",
        snapshots=(snapshot,),
    )
    support = EvidenceSupport(
        SupportedEntityType.CANONICAL_FACT, "canonical-1", ("evidence-1",))
    binding = OpportunitySupportBinding(
        support, reference_to(snapshot, "canonical-fact", "canonical-1"),
        (reference_to(snapshot, "evidence", "evidence-1"),),
    )
    return context, support, binding


def _analysis(support, timestamp=None):
    computed = DecisionStatement(
        "computed-1", StatementType.COMPUTED_FACT, "requirement_count=4",
        StatementSource(SourceType.DETERMINISTIC_COMPUTATION,
                        "opportunity-intelligence/1.0.0:requirement-count"),
        None, ReasoningStatus.VALIDATED, support.evidence_ids,
        (support.entity_id,), (support,),
    )
    statement = DecisionStatement(
        "inference-1", StatementType.AI_INFERENCE,
        "The documented structure contains an effort consideration.",
        StatementSource(SourceType.SPECIALIST_ANALYST, "opportunity-intelligence"),
        Confidence.MODERATE, ReasoningStatus.PROPOSED, support.evidence_ids,
        (computed.statement_id,), (support,),
        assumptions=("Structural volume is a relevant effort indicator",),
        alternative_hypotheses=(AlternativeHypothesis(
            "alternative-1", "Submission structure may explain the effort.",
            support.evidence_ids, ("No staffing model is available",)),),
        limitations=("No staffing model is available",),
    )
    return DecisionAnalysis(
        "analysis-1", "opportunity-intelligence",
        timestamp or datetime(2030, 1, 1, 12, tzinfo=timezone.utc),
        Confidence.MODERATE, (support,), (computed,),
        (AnalystReasoning(statement, SupportStatus.PARTIALLY_SUPPORTED),),
        (AnalystHypothesis(
            "hypothesis-1", "Requirement volume may contribute to effort.",
            (support,), (), Confidence.MODERATE,
            SupportStatus.PARTIALLY_SUPPORTED, ("The hypothesis is unranked",)),),
        (), ("Analysis is limited to supplied evidence.",),
        (AnalystAssumption(
            "assumption-1", "Structural volume is a relevant effort indicator"),),
        (ManagementQuestion(
            "question-1", "Which uncertainty requires management attention?",
            (statement.statement_id,)),),
        AnalystUnknowns(ambiguous_observation_ids=(support.entity_id,)),
    )


def _publication(timestamp=None):
    context, support, binding = _source_context()
    publication = publish_opportunity_intelligence(
        _analysis(support, timestamp), analyst_version=ANALYST_VERSION,
        authoritative_context=context, support_bindings=(binding,),
    )
    return publication


def _build(publication=None):
    return build_executive_opportunity_understanding(
        ExecutiveUnderstandingInput("opportunity-1", publication or _publication()))


def test_constructs_projection_bound_to_exact_publication():
    publication = _publication()
    value = _build(publication)
    assert value.contract_version == CONTRACT_VERSION
    assert value.organization_profile == ORGANIZATION_PROFILE
    assert value.analysis_id == publication.analysis_id
    assert value.analysis_digest == publication.manifest.analysis_digest
    assert value.publication_id == publication.publication_id
    assert value.publication_snapshot_id == publication.snapshot.snapshot_id
    assert value.publication_snapshot_digest == publication.snapshot.snapshot_digest
    assert value.context_id == publication.resolution_context.context_id
    assert value.context_digest == publication.resolution_context.context_digest


def test_detail_register_preserves_every_published_reference_exactly_once():
    publication = _publication()
    references = _build(publication).detail_register.references()
    assert {item.source_reference for item in references} == set(publication.references)
    assert len(references) == len(publication.references)
    assert len({item.source_reference.identity_key for item in references}) == len(references)
    assert all(item.owner_domain == "opportunity-intelligence" for item in references)
    assert all(not item.object_id.startswith("eou-") for item in references)


def test_every_reference_resolves_through_bound_context():
    value = _build()
    for item in value.detail_register.references():
        result = resolve_governed_reference(
            ResolutionRequest(item.source_reference, value.context_id,
                              value.context_digest, item.authority_class),
            value.resolution_context,
        )
        assert result.root.object_id == item.object_id
        assert result.root.object_digest == item.source_reference.object_digest


def test_relationship_identity_is_preserved():
    publication = _publication()
    value = _build(publication)
    published = {(item.object_class, item.object_id): item
                 for item in publication.snapshot.objects}
    for reference in value.detail_register.references():
        assert reference.relationships == published[
            (reference.object_class, reference.object_id)].relationships


def test_semantic_properties_remain_owner_resolved_not_copied():
    value = _build()
    inference = value.detail_register.validated_interpretations[0]
    result = resolve_governed_reference(
        ResolutionRequest(
            inference.source_reference, value.context_id, value.context_digest,
            AuthorityClass.INFERENCE), value.resolution_context)
    statement = result.root.field("statement")
    fields_by_name = {item.name: item.value for item in statement.fields}
    assert fields_by_name["confidence"].scalar == "MODERATE"
    assert fields_by_name["assumptions"].items[0].scalar == (
        "Structural volume is a relevant effort indicator")
    assert fields_by_name["alternative_hypotheses"].items[0].kind is SemanticValueKind.OBJECT
    serialized_reference = value.to_dict()["detail_register"][
        "validated_interpretations"][0]
    assert "display_value" not in serialized_reference
    assert "confidence" not in serialized_reference
    assert "support_status" not in serialized_reference


def test_assumptions_alternatives_limitations_unknowns_and_questions_are_preserved():
    value = _build()
    expected = {
        "assumptions": ("assumption-1", "description",
                        "Structural volume is a relevant effort indicator"),
        "competing_interpretation_sets": (
            "alternative-1", "statement", "Submission structure may explain the effort."),
        "limitations": ("analysis-1/limitations", "limitations",
                        "Analysis is limited to supplied evidence."),
        "unknowns": ("analysis-1/unknowns", "ambiguous_observation_ids", "canonical-1"),
        "management_questions": (
            "question-1", "question", "Which uncertainty requires management attention?"),
    }
    for collection_name, (object_id, field_name, expected_value) in expected.items():
        reference = next(
            item for item in getattr(value.detail_register, collection_name)
            if item.object_id == object_id)
        result = resolve_governed_reference(
            ResolutionRequest(reference.source_reference, value.context_id,
                              value.context_digest, reference.authority_class),
            value.resolution_context)
        semantic = result.root.field(field_name)
        actual = semantic.items[0].scalar if semantic.kind is SemanticValueKind.ARRAY else semantic.scalar
        assert actual == expected_value


def test_typed_collections_and_sections_are_deterministic():
    value = _build()
    register = value.detail_register
    assert len(register.computed_facts) == 1
    assert len(register.validated_interpretations) == 1
    assert len(register.competing_interpretation_sets) == 2
    assert len(register.assumptions) == 1
    assert len(register.unknowns) == 1
    assert len(register.management_questions) == 1
    assert len(register.limitations) == 1
    assert len(register.analyst_observations) == 1
    assert tuple(item.section for item in value.executive_index) == SECTION_ORDER
    sections = {item.section: item.object_ids for item in value.executive_index}
    assert "computed-1" in sections[ExecutiveSection.MEASURED_CHARACTERISTICS]
    assert "inference-1" in sections[ExecutiveSection.ANALYST_FINDINGS]
    assert "question-1" in sections[ExecutiveSection.MANAGEMENT_DELIBERATION]


def test_coverage_is_complete_and_bijective():
    value = _build()
    detail_ids = {item.object_id for item in value.detail_register.references()}
    coverage_ids = {item.object_id for item in value.coverage_ledger}
    assert detail_ids == coverage_ids
    assert value.validation_record.detail_object_count == len(detail_ids)
    assert value.validation_record.coverage_object_count == len(coverage_ids)
    analysis_record = next(item for item in value.coverage_ledger
                           if item.object_class == "analysis")
    assert analysis_record.disposition is CoverageDisposition.DETAIL_ONLY


def test_identical_publication_produces_byte_equivalent_understanding():
    publication = _publication()
    first = _build(publication)
    second = _build(publication)
    assert first == second
    assert first.to_json() == second.to_json()
    assert first.digest == second.digest


def test_execution_timestamp_does_not_affect_understanding_semantics():
    first_publication = _publication(datetime(2030, 1, 1, tzinfo=timezone.utc))
    second_publication = _publication(datetime(2040, 1, 1, tzinfo=timezone.utc))
    first = _build(first_publication)
    second = _build(second_publication)
    assert first_publication.execution_timestamp != second_publication.execution_timestamp
    assert first_publication == second_publication
    assert first == second
    assert first.understanding_id == second.understanding_id
    assert first.digest == second.digest
    assert first.to_json() == second.to_json()


def test_serialization_excludes_resolution_objects_but_keeps_exact_bindings():
    value = _build()
    payload = json.loads(value.to_json())
    assert payload == value.to_dict()
    assert "resolution_context" not in payload
    assert payload["context_id"] == value.resolution_context.context_id
    assert payload["context_digest"] == value.resolution_context.context_digest
    assert payload["publication_snapshot_digest"] == value.publication_snapshot_digest


def test_projection_is_deeply_immutable():
    value = _build()
    with pytest.raises(FrozenInstanceError):
        value.publication_id = "changed"
    with pytest.raises(FrozenInstanceError):
        value.detail_register.computed_facts = ()
    with pytest.raises(FrozenInstanceError):
        value.detail_register.computed_facts[0].source_reference.object_id = "changed"


def test_rejects_non_publication_input():
    with pytest.raises(ContractValidationError, match="OpportunityIntelligencePublication"):
        ExecutiveUnderstandingInput("opportunity-1", object())
    with pytest.raises(ContractValidationError, match="ExecutiveUnderstandingInput"):
        build_executive_opportunity_understanding({})


def test_rejects_reference_digest_tampering():
    value = _build()
    original = value.detail_register.computed_facts[0]
    stale = replace(original.source_reference, object_digest="f" * 64)
    tampered = replace(original, source_reference=stale)
    register = replace(value.detail_register, computed_facts=(tampered,))
    with pytest.raises(ContractValidationError, match="does not resolve"):
        replace(value, detail_register=register)


def test_rejects_coverage_and_index_tampering():
    value = _build()
    with pytest.raises(ContractValidationError, match="bijective"):
        replace(value, coverage_ledger=value.coverage_ledger[:-1])
    first = value.executive_index[0]
    bad = replace(first, object_ids=("unknown",))
    with pytest.raises(ContractValidationError, match="index"):
        replace(value, executive_index=(bad, *value.executive_index[1:]))


def test_validation_returns_same_immutable_value():
    value = _build()
    assert validate_executive_opportunity_understanding(value) is value


@pytest.mark.parametrize("opportunity_id", ["", " ", "bad id"])
def test_rejects_invalid_opportunity_identity(opportunity_id):
    with pytest.raises(ContractValidationError):
        ExecutiveUnderstandingInput(opportunity_id, _publication())


@pytest.mark.parametrize("field_name", [
    "context_digest", "authoritative_snapshot_digest", "analysis_digest",
    "publication_snapshot_digest",
])
def test_rejects_digest_binding_tampering(field_name):
    value = _build()
    with pytest.raises(ContractValidationError):
        replace(value, **{field_name: "f" * 64})


def test_rejects_understanding_identity_tampering():
    with pytest.raises(ContractValidationError, match="identity"):
        replace(_build(), understanding_id="eou-invalid")


def test_rejects_detail_pointer_tampering():
    value = _build()
    original = value.detail_register.computed_facts[0]
    tampered = replace(original, detail_pointer="/detail_register/computed_facts/99")
    with pytest.raises(ContractValidationError, match="pointer"):
        replace(value.detail_register, computed_facts=(tampered,))


def test_rejects_authority_reclassification():
    value = _build()
    original = value.detail_register.computed_facts[0]
    tampered = replace(original, authority_class=AuthorityClass.INFERENCE)
    with pytest.raises(ContractValidationError, match="authority"):
        replace(value.detail_register, computed_facts=(tampered,))


def test_rejects_relationship_omission():
    value = _build()
    original = value.detail_register.computed_facts[0]
    tampered = replace(original, relationships=())
    register = replace(value.detail_register, computed_facts=(tampered,))
    with pytest.raises(ContractValidationError, match="relationship"):
        replace(value, detail_register=register)


@pytest.mark.parametrize("field_name", ["context_id", "context_digest"])
def test_rejects_resolution_context_binding_tampering(field_name):
    value = _build()
    replacement = "other-context" if field_name == "context_id" else "f" * 64
    with pytest.raises(ContractValidationError, match="context"):
        replace(value, **{field_name: replacement})


@pytest.mark.parametrize("field_name,replacement", [
    ("publication_snapshot_id", "other-snapshot"),
    ("publication_snapshot_digest", "f" * 64),
])
def test_rejects_publication_snapshot_binding_tampering(field_name, replacement):
    value = _build()
    with pytest.raises(ContractValidationError, match="snapshot"):
        replace(value, **{field_name: replacement})


def test_rejects_executive_section_order_tampering():
    value = _build()
    with pytest.raises(ContractValidationError, match="sections"):
        replace(value, executive_index=tuple(reversed(value.executive_index)))


def test_rejects_coverage_order_tampering():
    value = _build()
    with pytest.raises(ContractValidationError, match="ordered"):
        replace(value, coverage_ledger=tuple(reversed(value.coverage_ledger)))


def test_every_reference_preserves_owner_contract_and_snapshot_binding():
    value = _build()
    for item in value.detail_register.references():
        source = item.source_reference
        assert source.owner_domain == "opportunity-intelligence"
        assert source.owner_contract == "opportunity-intelligence-analyst"
        assert source.contract_version == "1.1.1"
        assert source.snapshot_id == value.publication_snapshot_id
        assert source.snapshot_digest == value.publication_snapshot_digest


def test_input_preserves_exact_immutable_publication():
    publication = _publication()
    source = ExecutiveUnderstandingInput("opportunity-1", publication)
    assert source.publication is publication
    with pytest.raises(FrozenInstanceError):
        source.publication = _publication()
