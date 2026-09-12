from dataclasses import FrozenInstanceError, dataclass, replace
from datetime import datetime, timezone

import pytest

from decision_analyst import AnalystUnknowns, DecisionAnalysis
from decision_intelligence import (
    Confidence, DecisionStatement, EvidenceSupport, ReasoningStatus,
    SourceType, StatementSource, StatementType, SupportedEntityType,
)
from governed_reference_resolution import (
    AuthorityClass, GovernedObjectReference, GovernedRelationship,
    RelationshipKind, SemanticField, SemanticValue, SemanticValueKind,
    create_governed_object, create_governed_snapshot, reference_to,
)
from opportunity_intelligence import ANALYST_VERSION
from opportunity_intelligence_publication import publish_opportunity_intelligence
from opportunity_orchestration import (
    OPPORTUNITY_INTELLIGENCE_OPERATION, AdmittedOwnerPublication,
    CompatibilityDeclaration,
    OpportunityOperationContract, OpportunityOrchestrationError,
    OrchestrationFailureCode, PublicationAdmissionPolicy,
    PublicationCompatibilityPolicy, SupportReferencePolicy, _sha,
    admit_owner_publication,
    orchestrate_opportunity_intelligence,
)


@dataclass(frozen=True, slots=True)
class _OwnerPublication:
    publication_id: str
    authoritative_input_digest: str
    snapshot: object
    references: tuple

    @property
    def digest(self):
        return _sha(self)


def _publication(*, entity_id="canonical-1", owner="canonical-opportunity",
                 role="canonical", second_entity_class=None):
    snapshot_id = f"{role}-snapshot-1"
    evidence = create_governed_object(
        owner_domain=owner, owner_contract=owner, contract_version="1.0.0",
        object_class="evidence", object_id="evidence-1",
        authority=AuthorityClass.EVIDENCE,
        semantic_fields=(SemanticField(
            "locator", SemanticValue(SemanticValueKind.STRING, "page 1")),),
    )
    placeholder = GovernedObjectReference(
        owner, owner, "1.0.0", snapshot_id, "0" * 64,
        "evidence", "evidence-1", "0" * 64)
    entity = create_governed_object(
        owner_domain=owner, owner_contract=owner, contract_version="1.0.0",
        object_class="canonical-fact", object_id=entity_id,
        authority=AuthorityClass.CANONICAL_FACT,
        semantic_fields=(SemanticField(
            "value", SemanticValue(SemanticValueKind.STRING, "Known fact")),),
        relationships=(GovernedRelationship(
            RelationshipKind.EVIDENCE_SUPPORT, "source-evidence", placeholder),),
    )
    objects = [entity, evidence]
    if second_entity_class:
        objects.append(create_governed_object(
            owner_domain=owner, owner_contract=owner, contract_version="1.0.0",
            object_class=second_entity_class, object_id=entity_id,
            authority=AuthorityClass.CANONICAL_FACT,
            semantic_fields=(SemanticField(
                "value", SemanticValue(SemanticValueKind.STRING, "Other fact")),),
            relationships=(GovernedRelationship(
                RelationshipKind.EVIDENCE_SUPPORT, "source-evidence", placeholder),),
        ))
    snapshot = create_governed_snapshot(
        owner_domain=owner, owner_contract=owner, contract_version="1.0.0",
        snapshot_id=snapshot_id, objects=objects)
    publication = _OwnerPublication(
        f"{role}-publication-1", "input_" + "1" * 64, snapshot,
        tuple(reference_to(snapshot, item.object_class, item.object_id)
              for item in snapshot.objects))
    admission = admit_owner_publication(
        publication, role=role, scope_id="opportunity-1")
    return publication, admission


def _analysis(entity_id="canonical-1"):
    support = EvidenceSupport(
        SupportedEntityType.CANONICAL_FACT, entity_id, ("evidence-1",))
    statement = DecisionStatement(
        "computed-1", StatementType.COMPUTED_FACT, "known_count=1",
        StatementSource(SourceType.DETERMINISTIC_COMPUTATION,
                        "opportunity-intelligence/1.0.0:known-count"),
        None, ReasoningStatus.VALIDATED, support.evidence_ids,
        (support.entity_id,), (support,))
    return DecisionAnalysis(
        "analysis-1", "opportunity-intelligence",
        datetime(2030, 1, 1, tzinfo=timezone.utc), Confidence.UNKNOWN,
        (support,), (statement,), (), (), (),
        ("Analysis is limited to supplied evidence.",), (), (),
        AnalystUnknowns())


def _contract(*, owner="canonical-opportunity", required=True,
              object_classes=("canonical-fact", "evidence")):
    publication_policy = PublicationAdmissionPolicy(
        "canonical", owner, owner, "1.0.0", tuple(sorted(object_classes)), required)
    support_policy = SupportReferencePolicy(
        SupportedEntityType.CANONICAL_FACT, "canonical", ("canonical-fact",),
        (AuthorityClass.CANONICAL_FACT,))
    return OpportunityOperationContract(
        OPPORTUNITY_INTELLIGENCE_OPERATION, "1.0.0",
        (publication_policy,), (support_policy,))


def _orchestration(**kwargs):
    _, admission = _publication(**kwargs)
    return orchestrate_opportunity_intelligence(
        _analysis(), operation_id="operation-1", scope_id="opportunity-1",
        contract=_contract(), admitted_publications=(admission,))


def test_assembles_context_bindings_and_manifest_without_republishing():
    _, admission = _publication()
    result = orchestrate_opportunity_intelligence(
        _analysis(), operation_id="operation-1", scope_id="opportunity-1",
        contract=_contract(), admitted_publications=(admission,))
    assert result.resolution_context.snapshots == (admission.snapshot,)
    assert result.admitted_publications == (admission,)
    assert len(result.support_bindings) == 1
    binding = result.support_bindings[0]
    assert binding.entity_reference in admission.references
    assert binding.evidence_references[0] in admission.references
    assert result.manifest.required_roles == ("canonical",)
    assert result.manifest.satisfied_roles == ("canonical",)


def test_identical_inputs_produce_identical_context_bindings_and_manifest():
    _, admission = _publication()
    values = [orchestrate_opportunity_intelligence(
        _analysis(), operation_id="operation-1", scope_id="opportunity-1",
        contract=_contract(), admitted_publications=(admission,)) for _ in range(2)]
    assert values[0] == values[1]
    assert values[0].to_json() == values[1].to_json()
    assert values[0].resolution_context.context_id == values[1].resolution_context.context_id
    assert values[0].resolution_context.context_digest == values[1].resolution_context.context_digest
    assert values[0].manifest.support_bindings_digest == values[1].manifest.support_bindings_digest
    assert values[0].manifest.manifest_id == values[1].manifest.manifest_id
    assert values[0].manifest.manifest_digest == values[1].manifest.manifest_digest


def test_multiple_publications_are_ordered_and_require_declared_compatibility():
    _, canonical = _publication()
    _, provenance = _publication(owner="provenance-owner", role="provenance")
    policies = tuple(sorted((
        PublicationAdmissionPolicy(
            "canonical", "canonical-opportunity", "canonical-opportunity",
            "1.0.0", ("canonical-fact", "evidence")),
        PublicationAdmissionPolicy(
            "provenance", "provenance-owner", "provenance-owner",
            "1.0.0", ("canonical-fact", "evidence")),
    ), key=lambda item: item.order_key))
    compatibility_policy = PublicationCompatibilityPolicy(
        "canonical", "provenance", "same-opportunity-scope", "1.0.0")
    contract = OpportunityOperationContract(
        OPPORTUNITY_INTELLIGENCE_OPERATION, "1.0.0", policies,
        (_contract().support_policies[0],), (compatibility_policy,))
    declaration = CompatibilityDeclaration(
        "canonical", "provenance",
        canonical.snapshot.snapshot_id, canonical.snapshot.snapshot_digest,
        provenance.snapshot.snapshot_id, provenance.snapshot.snapshot_digest,
        "same-opportunity-scope", "1.0.0")
    result = orchestrate_opportunity_intelligence(
        _analysis(), operation_id="operation-1", scope_id="opportunity-1",
        contract=contract, admitted_publications=(provenance, canonical),
        compatibility_declarations=(declaration,))
    assert tuple(item.role for item in result.admitted_publications) == (
        "canonical", "provenance")
    assert result.resolution_context.snapshots == tuple(sorted(
        (canonical.snapshot, provenance.snapshot),
        key=lambda item: (item.owner_domain, item.owner_contract, item.snapshot_id)))
    with pytest.raises(OpportunityOrchestrationError) as captured:
        orchestrate_opportunity_intelligence(
            _analysis(), operation_id="operation-1", scope_id="opportunity-1",
            contract=contract, admitted_publications=(canonical, provenance))
    assert captured.value.code is OrchestrationFailureCode.INCOMPATIBLE_PUBLICATION


def test_orchestration_outputs_are_deeply_immutable():
    result = _orchestration()
    with pytest.raises(FrozenInstanceError):
        result.operation_id = "changed"
    with pytest.raises(FrozenInstanceError):
        result.manifest.manifest_id = "changed"
    with pytest.raises(TypeError):
        result.resolution_context.snapshots[0] = None


def test_opportunity_intelligence_publication_accepts_orchestration_outputs():
    result = _orchestration()
    publication = publish_opportunity_intelligence(
        _analysis(), analyst_version=ANALYST_VERSION,
        authoritative_context=result.resolution_context,
        support_bindings=result.support_bindings)
    assert publication.authoritative_context == result.resolution_context
    assert publication.manifest.support_bindings_digest == result.manifest.support_bindings_digest


def test_missing_required_publication_fails_closed():
    with pytest.raises(OpportunityOrchestrationError) as captured:
        orchestrate_opportunity_intelligence(
            _analysis(), operation_id="operation-1", scope_id="opportunity-1",
            contract=_contract(), admitted_publications=())
    assert captured.value.code is OrchestrationFailureCode.MISSING_PUBLICATION


def test_owner_contract_mismatch_fails_closed():
    _, admission = _publication(owner="foreign-owner")
    with pytest.raises(OpportunityOrchestrationError) as captured:
        orchestrate_opportunity_intelligence(
            _analysis(), operation_id="operation-1", scope_id="opportunity-1",
            contract=_contract(), admitted_publications=(admission,))
    assert captured.value.code is OrchestrationFailureCode.OWNER_MISMATCH


def test_missing_and_ambiguous_support_targets_fail_closed():
    _, admission = _publication(entity_id="other-id")
    with pytest.raises(OpportunityOrchestrationError) as captured:
        orchestrate_opportunity_intelligence(
            _analysis(), operation_id="operation-1", scope_id="opportunity-1",
            contract=_contract(), admitted_publications=(admission,))
    assert captured.value.code is OrchestrationFailureCode.MISSING_SUPPORT

    _, ambiguous = _publication(second_entity_class="canonical-fact-alternate")
    contract = _contract(object_classes=(
        "canonical-fact", "canonical-fact-alternate", "evidence"))
    support = SupportReferencePolicy(
        SupportedEntityType.CANONICAL_FACT, "canonical",
        ("canonical-fact", "canonical-fact-alternate"),
        (AuthorityClass.CANONICAL_FACT,))
    contract = replace(contract, support_policies=(support,))
    with pytest.raises(OpportunityOrchestrationError) as captured:
        orchestrate_opportunity_intelligence(
            _analysis(), operation_id="operation-1", scope_id="opportunity-1",
            contract=contract, admitted_publications=(ambiguous,))
    assert captured.value.code is OrchestrationFailureCode.AMBIGUOUS_SUPPORT


def test_missing_evidence_relationship_fails_closed():
    _, admission = _publication()
    analysis = _analysis()
    support = replace(analysis.evidence_used[0], evidence_ids=("missing-evidence",))
    statement = replace(analysis.computed_facts[0], evidence_ids=support.evidence_ids,
                        evidence_support=(support,))
    analysis = replace(analysis, evidence_used=(support,), computed_facts=(statement,))
    with pytest.raises(OpportunityOrchestrationError) as captured:
        orchestrate_opportunity_intelligence(
            analysis, operation_id="operation-1", scope_id="opportunity-1",
            contract=_contract(), admitted_publications=(admission,))
    assert captured.value.code is OrchestrationFailureCode.INCOMPLETE_RELATIONSHIP_CLOSURE


def test_scope_version_and_object_class_mismatches_fail_closed():
    _, admission = _publication()
    with pytest.raises(OpportunityOrchestrationError) as captured:
        orchestrate_opportunity_intelligence(
            _analysis(), operation_id="operation-1", scope_id="opportunity-1",
            contract=_contract(),
            admitted_publications=(replace(admission, scope_id="opportunity-2"),))
    assert captured.value.code is OrchestrationFailureCode.INCOMPATIBLE_PUBLICATION
    with pytest.raises(OpportunityOrchestrationError) as captured:
        replace(_contract(), contract_version="2.0.0")
    assert captured.value.code is OrchestrationFailureCode.VERSION_MISMATCH


def test_manifest_and_binding_tampering_fail_closed():
    result = _orchestration()
    with pytest.raises(OpportunityOrchestrationError) as captured:
        replace(result.manifest, manifest_digest="0" * 64)
    assert captured.value.code is OrchestrationFailureCode.DIGEST_MISMATCH
    with pytest.raises(OpportunityOrchestrationError) as captured:
        replace(result, support_bindings=())
    assert captured.value.code is OrchestrationFailureCode.DIGEST_MISMATCH


def test_admission_rejects_non_publication_and_nonreproducible_digest():
    with pytest.raises(OpportunityOrchestrationError) as captured:
        admit_owner_publication(object(), role="canonical", scope_id="opportunity-1")
    assert captured.value.code is OrchestrationFailureCode.INVALID_PUBLICATION
    publication, _ = _publication()
    @dataclass(frozen=True, slots=True)
    class BrokenPublication:
        publication_id: str
        authoritative_input_digest: str
        snapshot: object
        references: tuple
        digest: str
    broken = BrokenPublication(
        publication.publication_id, publication.authoritative_input_digest,
        publication.snapshot, publication.references, "0" * 64)
    with pytest.raises(OpportunityOrchestrationError) as captured:
        admit_owner_publication(broken, role="canonical", scope_id="opportunity-1")
    assert captured.value.code is OrchestrationFailureCode.DIGEST_MISMATCH
