from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest

from decision_analyst import (
    AnalystAssumption,
    AnalystHypothesis,
    AnalystReasoning,
    AnalystRecommendation,
    AnalystUnknowns,
    DecisionAnalysis,
    ManagementQuestion,
    SupportStatus,
)
from decision_intelligence import (
    AlternativeHypothesis,
    Confidence,
    DecisionStatement,
    EvidenceSupport,
    ReasoningStatus,
    SourceType,
    StatementSource,
    StatementType,
    SupportedEntityType,
)
from governed_reference_resolution import (
    AuthorityClass,
    GovernedObjectReference,
    RelationshipKind,
    SemanticField,
    SemanticValue,
    SemanticValueKind,
    create_governed_object,
    create_governed_snapshot,
    create_resolution_context,
    reference_to,
    resolve_governed_reference,
)
from opportunity_intelligence import ANALYST_VERSION
from opportunity_intelligence_publication import (
    OWNER_CONTRACT,
    OWNER_DOMAIN,
    PUBLICATION_CONTRACT_VERSION,
    OpportunityPublicationError,
    OpportunitySupportBinding,
    PublicationFailureCode,
    publish_opportunity_intelligence,
)


def _source_context():
    canonical = create_governed_object(
        owner_domain="canonical-opportunity",
        owner_contract="canonical-opportunity",
        contract_version="1.0.0",
        object_class="canonical-fact",
        object_id="canonical-1",
        authority=AuthorityClass.CANONICAL_FACT,
        semantic_fields=(SemanticField(
            "value", SemanticValue(SemanticValueKind.STRING, "Known fact")),),
    )
    evidence = create_governed_object(
        owner_domain="canonical-opportunity",
        owner_contract="canonical-opportunity",
        contract_version="1.0.0",
        object_class="evidence",
        object_id="evidence-1",
        authority=AuthorityClass.EVIDENCE,
        semantic_fields=(SemanticField(
            "locator", SemanticValue(SemanticValueKind.STRING, "page 1")),),
    )
    snapshot = create_governed_snapshot(
        owner_domain="canonical-opportunity",
        owner_contract="canonical-opportunity",
        contract_version="1.0.0",
        snapshot_id="canonical-snapshot-1",
        objects=(canonical, evidence),
    )
    context = create_resolution_context(
        context_id="authoritative-context-1",
        context_version="1.0.0",
        snapshots=(snapshot,),
    )
    support = EvidenceSupport(
        SupportedEntityType.CANONICAL_FACT,
        "canonical-1",
        ("evidence-1",),
    )
    binding = OpportunitySupportBinding(
        support,
        reference_to(snapshot, "canonical-fact", "canonical-1"),
        (reference_to(snapshot, "evidence", "evidence-1"),),
    )
    return context, support, binding


def _analysis(support):
    computed = DecisionStatement(
        "computed-1",
        StatementType.COMPUTED_FACT,
        "requirement_count=4",
        StatementSource(SourceType.DETERMINISTIC_COMPUTATION,
                        "opportunity-intelligence/1.0.0:requirement-count"),
        None,
        ReasoningStatus.VALIDATED,
        support.evidence_ids,
        (support.entity_id,),
        (support,),
    )
    inference_statement = DecisionStatement(
        "inference-1",
        StatementType.AI_INFERENCE,
        "The documented structure contains a proposal-effort consideration.",
        StatementSource(SourceType.SPECIALIST_ANALYST, "opportunity-intelligence"),
        Confidence.MODERATE,
        ReasoningStatus.PROPOSED,
        support.evidence_ids,
        (computed.statement_id,),
        (support,),
        assumptions=("Structural volume is a relevant effort indicator",),
        alternative_hypotheses=(AlternativeHypothesis(
            "alternative-1",
            "The apparent effort may instead arise from submission structure.",
            support.evidence_ids,
            ("No staffing model is available",),
        ),),
        limitations=("No staffing model is available",),
    )
    inference = AnalystReasoning(inference_statement, SupportStatus.PARTIALLY_SUPPORTED)
    hypothesis = AnalystHypothesis(
        "hypothesis-1",
        "The measured volume may contribute to proposal effort.",
        (support,),
        (support,),
        Confidence.MODERATE,
        SupportStatus.PARTIALLY_SUPPORTED,
        ("The hypothesis is unranked",),
    )
    return DecisionAnalysis(
        "analysis-1",
        "opportunity-intelligence",
        datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc),
        Confidence.MODERATE,
        (support,),
        (computed,),
        (inference,),
        (hypothesis,),
        (),
        ("Analysis is limited to supplied evidence.",),
        (AnalystAssumption(
            "assumption-1", "Structural volume is a relevant effort indicator"),),
        (ManagementQuestion(
            "question-1", "Which uncertainty requires management attention?",
            (inference_statement.statement_id,)),),
        AnalystUnknowns(ambiguous_observation_ids=(support.entity_id,)),
    )


def _publication():
    context, support, binding = _source_context()
    analysis = _analysis(support)
    publication = publish_opportunity_intelligence(
        analysis,
        analyst_version=ANALYST_VERSION,
        authoritative_context=context,
        support_bindings=(binding,),
    )
    return publication, analysis, context, binding


def test_successful_publication_is_resolver_compatible():
    publication, _, _, _ = _publication()
    request = publication.request_for(
        "inference",
        "inference-1",
        expected_authority=AuthorityClass.INFERENCE,
        required_semantic_fields=("statement", "support_status"),
        required_relationship_kinds=(RelationshipKind.EVIDENCE_SUPPORT,
                                     RelationshipKind.SUPPORT),
    )
    result = resolve_governed_reference(request, publication.resolution_context)
    assert result.root.field("support_status").scalar == "PARTIALLY_SUPPORTED"
    assert result.root.field("statement").kind is SemanticValueKind.OBJECT
    assert publication.snapshot.owner_domain == OWNER_DOMAIN
    assert publication.snapshot.owner_contract == OWNER_CONTRACT
    assert publication.snapshot.contract_version == PUBLICATION_CONTRACT_VERSION


def test_publication_is_deterministic_with_stable_identity_and_digests():
    first, analysis, context, binding = _publication()
    second = publish_opportunity_intelligence(
        analysis,
        analyst_version=ANALYST_VERSION,
        authoritative_context=context,
        support_bindings=(binding,),
    )
    assert first == second
    assert first.to_json() == second.to_json()
    assert first.publication_id == second.publication_id
    assert first.snapshot.snapshot_id == second.snapshot.snapshot_id
    assert first.snapshot.snapshot_digest == second.snapshot.snapshot_digest
    assert [item.object_digest for item in first.snapshot.objects] == [
        item.object_digest for item in second.snapshot.objects]


def test_execution_timestamp_is_auditable_but_excluded_from_semantic_identity():
    first, analysis, context, binding = _publication()
    later_timestamp = datetime(2040, 2, 3, 4, 5, tzinfo=timezone.utc)
    second = publish_opportunity_intelligence(
        replace(analysis, execution_timestamp=later_timestamp),
        analyst_version=ANALYST_VERSION,
        authoritative_context=context,
        support_bindings=(binding,),
    )

    assert first.execution_timestamp == analysis.execution_timestamp
    assert second.execution_timestamp == later_timestamp
    assert first.execution_timestamp != second.execution_timestamp
    assert first == second
    assert first.manifest.analysis_digest == second.manifest.analysis_digest
    assert first.publication_id == second.publication_id
    assert first.snapshot.snapshot_id == second.snapshot.snapshot_id
    assert first.snapshot.snapshot_digest == second.snapshot.snapshot_digest
    assert first.references == second.references
    assert first.resolution_context == second.resolution_context
    assert [item.object_digest for item in first.snapshot.objects] == [
        item.object_digest for item in second.snapshot.objects]
    assert first.to_json() != second.to_json()

    analysis_object = next(
        item for item in first.snapshot.objects if item.object_class == "analysis")
    assert {item.name for item in analysis_object.semantic_fields} == {
        "analysis_id", "analyst_id", "analyst_version", "overall_confidence",
    }


def test_manifest_preserves_objects_relationships_and_canonical_order():
    publication, _, context, _ = _publication()
    assert publication.authoritative_context_id == context.context_id
    assert publication.authoritative_context_digest == context.context_digest
    assert publication.manifest.publication_snapshot_id == publication.snapshot.snapshot_id
    assert publication.manifest.publication_snapshot_digest == publication.snapshot.snapshot_digest
    assert publication.manifest.objects == tuple(sorted(
        publication.manifest.objects, key=lambda item: (item.object_class, item.object_id)))
    assert publication.manifest.relationships == tuple(sorted(
        publication.manifest.relationships, key=lambda item: item.order_key))
    assert {item.object_class for item in publication.snapshot.objects} == {
        "analysis", "alternative-hypothesis", "assumption", "computed-fact",
        "hypothesis", "inference", "limitations", "management-question", "unknowns",
    }
    assert any(item.kind is RelationshipKind.CONTRADICTION
               for item in publication.manifest.relationships)
    assert any(item.kind is RelationshipKind.DEPENDENCY
               for item in publication.manifest.relationships)


def test_publication_preserves_semantics_confidence_uncertainty_and_limitations():
    publication, _, _, _ = _publication()
    inference = next(item for item in publication.snapshot.objects
                     if item.object_class == "inference")
    statement = inference.field("statement")
    statement_fields = {item.name: item.value for item in statement.fields}
    assert statement_fields["confidence"].scalar == "MODERATE"
    assert statement_fields["assumptions"].items[0].scalar == (
        "Structural volume is a relevant effort indicator")
    assert statement_fields["alternative_hypotheses"].items[0].kind is SemanticValueKind.OBJECT
    limitations = next(item for item in publication.snapshot.objects
                       if item.object_class == "limitations")
    assert limitations.field("limitations").items[0].scalar == (
        "Analysis is limited to supplied evidence.")
    unknowns = next(item for item in publication.snapshot.objects
                    if item.object_class == "unknowns")
    assert unknowns.field("ambiguous_observation_ids").items[0].scalar == "canonical-1"


def test_publication_is_deeply_immutable():
    publication, _, _, _ = _publication()
    with pytest.raises(FrozenInstanceError):
        publication.publication_id = "changed"
    with pytest.raises(FrozenInstanceError):
        publication.manifest.objects[0].object_id = "changed"
    with pytest.raises(FrozenInstanceError):
        publication.execution_timestamp = datetime.now(timezone.utc)
    assert isinstance(publication.references, tuple)
    assert isinstance(publication.snapshot.objects, tuple)
    assert isinstance(publication.manifest.relationships, tuple)


def test_unsupported_analyst_version_fails_closed():
    _, analysis, context, binding = _publication()
    with pytest.raises(OpportunityPublicationError) as raised:
        publish_opportunity_intelligence(
            analysis,
            analyst_version="2.0.0",
            authoritative_context=context,
            support_bindings=(binding,),
        )
    assert raised.value.code is PublicationFailureCode.VERSION_MISMATCH


def test_duplicate_owned_identity_fails_closed():
    _, analysis, context, binding = _publication()
    duplicate = replace(
        analysis,
        assumptions=(AnalystAssumption("duplicate", "First"),
                     AnalystAssumption("duplicate", "Second")),
    )
    with pytest.raises(OpportunityPublicationError) as raised:
        publish_opportunity_intelligence(
            duplicate,
            analyst_version=ANALYST_VERSION,
            authoritative_context=context,
            support_bindings=(binding,),
        )
    assert raised.value.code is PublicationFailureCode.DUPLICATE_IDENTITY


def test_missing_semantic_content_fails_closed():
    _, analysis, context, binding = _publication()
    invalid_statement = object.__new__(DecisionStatement)
    for field_name, value in {
        "statement_id": "computed-invalid",
        "statement_type": StatementType.COMPUTED_FACT,
        "statement": None,
        "source": StatementSource(
            SourceType.DETERMINISTIC_COMPUTATION, "opportunity-intelligence/1.0.0:test"),
        "confidence": None,
        "reasoning_status": ReasoningStatus.VALIDATED,
        "evidence_ids": binding.support.evidence_ids,
        "supporting_fact_ids": (binding.support.entity_id,),
        "evidence_support": (binding.support,),
        "assumptions": (),
        "alternative_hypotheses": (),
        "limitations": (),
        "recommendation_scope": None,
        "reasoning_gaps": analysis.computed_facts[0].reasoning_gaps,
    }.items():
        object.__setattr__(invalid_statement, field_name, value)
    invalid = replace(analysis, computed_facts=(invalid_statement,))
    with pytest.raises(OpportunityPublicationError) as raised:
        publish_opportunity_intelligence(
            invalid,
            analyst_version=ANALYST_VERSION,
            authoritative_context=context,
            support_bindings=(binding,),
        )
    assert raised.value.code is PublicationFailureCode.MISSING_SEMANTIC_CONTENT


def test_missing_or_broken_relationship_binding_fails_closed():
    _, analysis, context, binding = _publication()
    with pytest.raises(OpportunityPublicationError) as raised:
        publish_opportunity_intelligence(
            analysis,
            analyst_version=ANALYST_VERSION,
            authoritative_context=context,
            support_bindings=(),
        )
    assert raised.value.code is PublicationFailureCode.BROKEN_RELATIONSHIP

    stale = replace(binding.entity_reference, object_digest="f" * 64)
    stale_binding = OpportunitySupportBinding(
        binding.support, stale, binding.evidence_references)
    with pytest.raises(OpportunityPublicationError) as raised:
        publish_opportunity_intelligence(
            analysis,
            analyst_version=ANALYST_VERSION,
            authoritative_context=context,
            support_bindings=(stale_binding,),
        )
    assert raised.value.code is PublicationFailureCode.BROKEN_RELATIONSHIP


def test_incompatible_authoritative_snapshot_fails_closed():
    _, analysis, _, binding = _publication()
    empty_context = create_resolution_context(
        context_id="different-authoritative-context",
        context_version="1.0.0",
        snapshots=(),
    )
    with pytest.raises(OpportunityPublicationError) as raised:
        publish_opportunity_intelligence(
            analysis,
            analyst_version=ANALYST_VERSION,
            authoritative_context=empty_context,
            support_bindings=(binding,),
        )
    assert raised.value.code is PublicationFailureCode.INCOMPATIBLE_SNAPSHOT


def test_recommendations_are_never_published():
    _, analysis, context, binding = _publication()
    recommendation = AnalystRecommendation(
        "recommendation-1",
        "pursuit",
        "Proceed",
        ("computed-1",),
        Confidence.MODERATE,
        SupportStatus.PARTIALLY_SUPPORTED,
    )
    invalid = replace(analysis, recommendations=(recommendation,))
    with pytest.raises(OpportunityPublicationError) as raised:
        publish_opportunity_intelligence(
            invalid,
            analyst_version=ANALYST_VERSION,
            authoritative_context=context,
            support_bindings=(binding,),
        )
    assert raised.value.code is PublicationFailureCode.INVALID_ANALYSIS


def test_support_binding_rejects_evidence_that_is_not_evidence_authority():
    _, support, _ = _source_context()
    canonical = create_governed_object(
        owner_domain="canonical-opportunity",
        owner_contract="canonical-opportunity",
        contract_version="1.0.0",
        object_class="canonical-fact",
        object_id="canonical-1",
        authority=AuthorityClass.CANONICAL_FACT,
        semantic_fields=(SemanticField(
            "value", SemanticValue(SemanticValueKind.STRING, "Known fact")),),
    )
    wrong_evidence = create_governed_object(
        owner_domain="canonical-opportunity",
        owner_contract="canonical-opportunity",
        contract_version="1.0.0",
        object_class="canonical-fact",
        object_id="evidence-1",
        authority=AuthorityClass.CANONICAL_FACT,
        semantic_fields=(SemanticField(
            "value", SemanticValue(SemanticValueKind.STRING, "Not evidence")),),
    )
    snapshot = create_governed_snapshot(
        owner_domain="canonical-opportunity",
        owner_contract="canonical-opportunity",
        contract_version="1.0.0",
        snapshot_id="wrong-authority-snapshot",
        objects=(canonical, wrong_evidence),
    )
    context = create_resolution_context(
        context_id="wrong-authority-context",
        context_version="1.0.0",
        snapshots=(snapshot,),
    )
    wrong = OpportunitySupportBinding(
        support,
        reference_to(snapshot, "canonical-fact", "canonical-1"),
        (reference_to(snapshot, "canonical-fact", "evidence-1"),),
    )
    analysis = _analysis(support)
    with pytest.raises(OpportunityPublicationError) as raised:
        publish_opportunity_intelligence(
            analysis,
            analyst_version=ANALYST_VERSION,
            authoritative_context=context,
            support_bindings=(wrong,),
        )
    assert raised.value.code is PublicationFailureCode.BROKEN_RELATIONSHIP


def test_changed_analysis_content_creates_a_distinct_publication():
    first, analysis, context, binding = _publication()
    changed_statement = replace(
        analysis.computed_facts[0], statement="requirement_count=5")
    changed = replace(analysis, computed_facts=(changed_statement,))
    second = publish_opportunity_intelligence(
        changed,
        analyst_version=ANALYST_VERSION,
        authoritative_context=context,
        support_bindings=(binding,),
    )
    assert first.publication_id != second.publication_id
    assert first.snapshot.snapshot_id != second.snapshot.snapshot_id
    assert first.snapshot.snapshot_digest != second.snapshot.snapshot_digest


def test_reference_binding_cannot_be_replaced_with_current_state():
    publication, _, _, _ = _publication()
    reference = publication.reference_for("computed-fact", "computed-1")
    stale_reference = GovernedObjectReference(
        reference.owner_domain,
        reference.owner_contract,
        reference.contract_version,
        reference.snapshot_id,
        "a" * 64,
        reference.object_class,
        reference.object_id,
        reference.object_digest,
    )
    assert stale_reference != reference
    assert all(item != stale_reference for item in publication.references)
