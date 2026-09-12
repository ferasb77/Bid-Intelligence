from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json

import pytest

from governed_reference_resolution import (
    AuthorityClass,
    GovernedObjectReference,
    GovernedRelationship,
    GovernedResolutionError,
    RelationshipKind,
    ResolutionFailureCode,
    ResolutionRequest,
    SemanticField,
    SemanticValue,
    SemanticValueKind,
    create_governed_object,
    create_governed_snapshot,
    create_resolution_context,
    reference_to,
    resolve_governed_reference,
)


def text(value: str) -> SemanticValue:
    return SemanticValue(SemanticValueKind.STRING, value)


def field(name: str, value: str) -> SemanticField:
    return SemanticField(name, text(value))


def graph(*, reverse_context=False):
    provenance = create_governed_object(
        owner_domain="source-registry", owner_contract="source-record",
        contract_version="1.0.0", object_class="SOURCE", object_id="source-1",
        authority=AuthorityClass.EVIDENCE,
        semantic_fields=(field("locator", "page 4"), field("title", "Issued RFP")),
    )
    provenance_snapshot = create_governed_snapshot(
        owner_domain="source-registry", owner_contract="source-record",
        contract_version="1.0.0", snapshot_id="source-snapshot-1",
        objects=(provenance,),
    )
    provenance_ref = reference_to(provenance_snapshot, "SOURCE", "source-1")

    evidence = create_governed_object(
        owner_domain="opportunity-evidence", owner_contract="evidence-record",
        contract_version="1.0.0", object_class="EVIDENCE", object_id="evidence-1",
        authority=AuthorityClass.EVIDENCE,
        semantic_fields=(field("exact_text", "Submission closes on 2030-01-15."),),
        relationships=(GovernedRelationship(
            RelationshipKind.PROVENANCE, "source", provenance_ref),),
    )
    evidence_snapshot = create_governed_snapshot(
        owner_domain="opportunity-evidence", owner_contract="evidence-record",
        contract_version="1.0.0", snapshot_id="evidence-snapshot-1",
        objects=(evidence,),
    )
    evidence_ref = reference_to(evidence_snapshot, "EVIDENCE", "evidence-1")

    fact = create_governed_object(
        owner_domain="canonical-opportunity", owner_contract="canonical-fact",
        contract_version="1.0.0", object_class="DEADLINE", object_id="deadline-1",
        authority=AuthorityClass.CANONICAL_FACT,
        semantic_fields=(
            SemanticField("precision", SemanticValue(SemanticValueKind.ENUM, "DATE")),
            SemanticField("value", SemanticValue(SemanticValueKind.DATE, "2030-01-15")),
        ),
        relationships=(GovernedRelationship(
            RelationshipKind.EVIDENCE_SUPPORT, "supporting-evidence", evidence_ref),),
    )
    fact_snapshot = create_governed_snapshot(
        owner_domain="canonical-opportunity", owner_contract="canonical-fact",
        contract_version="1.0.0", snapshot_id="fact-snapshot-1", objects=(fact,),
    )
    fact_ref = reference_to(fact_snapshot, "DEADLINE", "deadline-1")
    snapshots = (fact_snapshot, evidence_snapshot, provenance_snapshot)
    if reverse_context:
        snapshots = tuple(reversed(snapshots))
    context = create_resolution_context(
        context_id="opportunity-context-1", context_version="1.0.0",
        snapshots=snapshots,
    )
    request = ResolutionRequest(
        fact_ref, context.context_id, context.context_digest,
        AuthorityClass.CANONICAL_FACT,
        required_semantic_fields=("precision", "value"),
        required_relationship_kinds=(RelationshipKind.EVIDENCE_SUPPORT,),
    )
    return context, request, fact_snapshot, evidence_snapshot, provenance_snapshot


def assert_code(code: ResolutionFailureCode, operation):
    with pytest.raises(GovernedResolutionError) as captured:
        operation()
    assert captured.value.code == code


def test_successfully_resolves_semantics_evidence_and_provenance():
    context, request, *_ = graph()
    result = resolve_governed_reference(request, context)
    assert result.root.field("value") == SemanticValue(SemanticValueKind.DATE, "2030-01-15")
    assert result.root.authority == AuthorityClass.CANONICAL_FACT
    assert [item.value.object_id for item in result.objects] == [
        "deadline-1", "evidence-1", "source-1"]
    evidence = result.relationship_targets(
        request.reference, RelationshipKind.EVIDENCE_SUPPORT)
    assert tuple(item.object_id for item in evidence) == ("evidence-1",)
    evidence_resolved = next(item for item in result.objects
                             if item.value.object_id == "evidence-1")
    provenance = result.relationship_targets(
        evidence_resolved.reference, RelationshipKind.PROVENANCE)
    assert tuple(item.field("locator").scalar for item in provenance) == ("page 4",)


def test_resolution_preserves_every_owner_and_snapshot_binding():
    context, request, *_ = graph()
    result = resolve_governed_reference(request, context)
    bindings = {(item.reference.owner_domain, item.reference.snapshot_id,
                 item.value.owner_domain) for item in result.objects}
    assert bindings == {
        ("canonical-opportunity", "fact-snapshot-1", "canonical-opportunity"),
        ("opportunity-evidence", "evidence-snapshot-1", "opportunity-evidence"),
        ("source-registry", "source-snapshot-1", "source-registry"),
    }


def test_input_order_does_not_change_context_or_result():
    first_context, first_request, *_ = graph()
    second_context, second_request, *_ = graph(reverse_context=True)
    first = resolve_governed_reference(first_request, first_context)
    second = resolve_governed_reference(second_request, second_context)
    assert first_context == second_context
    assert first_context.to_json() == second_context.to_json()
    assert first == second
    assert first.to_json() == second.to_json()
    assert first.digest == second.digest


def test_serialization_is_canonical_and_round_trippable():
    context, request, *_ = graph()
    result = resolve_governed_reference(request, context)
    assert json.loads(context.to_json()) == context.to_dict()
    assert json.loads(result.to_json()) == result.to_dict()
    assert result.to_json() == result.to_json()


def test_contracts_are_deeply_immutable():
    context, request, *_ = graph()
    result = resolve_governed_reference(request, context)
    with pytest.raises(FrozenInstanceError):
        context.context_id = "changed"
    with pytest.raises(FrozenInstanceError):
        result.root.object_id = "changed"
    with pytest.raises(TypeError):
        result.objects[0] = result.objects[1]


def test_semantic_values_preserve_nested_typed_properties():
    nested = SemanticValue(SemanticValueKind.OBJECT, fields=(
        SemanticField("active", SemanticValue(SemanticValueKind.BOOLEAN, True)),
        SemanticField("count", SemanticValue(SemanticValueKind.INTEGER, 2)),
    ))
    array = SemanticValue(SemanticValueKind.ARRAY, items=(nested,))
    assert array.items[0].fields[0].value.scalar is True
    assert array.items[0].fields[1].value.scalar == 2


@pytest.mark.parametrize("version", ["", "1", "1.0", "v1.0.0", "01.0.0"])
def test_version_validation_fails_closed(version):
    assert_code(ResolutionFailureCode.INVALID_CONTRACT, lambda: create_governed_object(
        owner_domain="owner", owner_contract="contract", contract_version=version,
        object_class="FACT", object_id="fact-1", authority=AuthorityClass.CANONICAL_FACT,
        semantic_fields=(field("value", "x"),),
    ))


def test_object_digest_validation_fails_closed():
    context, _, fact_snapshot, *_ = graph()
    fact = fact_snapshot.objects[0]
    assert_code(ResolutionFailureCode.DIGEST_MISMATCH,
                lambda: replace(fact, object_digest="b" * 64))
    assert context.context_digest


def test_snapshot_digest_validation_fails_closed():
    _, _, fact_snapshot, *_ = graph()
    assert_code(ResolutionFailureCode.DIGEST_MISMATCH,
                lambda: replace(fact_snapshot, snapshot_digest="b" * 64))


def test_context_digest_validation_fails_closed():
    context, *_ = graph()
    assert_code(ResolutionFailureCode.DIGEST_MISMATCH,
                lambda: replace(context, context_digest="b" * 64))


def test_missing_reference_fails_closed_without_fallback():
    context, request, *_ = graph()
    missing = replace(request.reference, object_id="deadline-missing")
    assert_code(ResolutionFailureCode.MISSING_REFERENCE,
                lambda: resolve_governed_reference(replace(request, reference=missing), context))


def test_duplicate_object_identity_is_rejected():
    _, _, fact_snapshot, *_ = graph()
    fact = fact_snapshot.objects[0]
    assert_code(ResolutionFailureCode.DUPLICATE_IDENTITY,
                lambda: create_governed_snapshot(
                    owner_domain=fact_snapshot.owner_domain,
                    owner_contract=fact_snapshot.owner_contract,
                    contract_version=fact_snapshot.contract_version,
                    snapshot_id="duplicate-snapshot", objects=(fact, fact)))


def test_duplicate_snapshot_identity_is_rejected():
    _, _, fact_snapshot, *_ = graph()
    assert_code(ResolutionFailureCode.DUPLICATE_IDENTITY,
                lambda: create_resolution_context(
                    context_id="context", context_version="1.0.0",
                    snapshots=(fact_snapshot, fact_snapshot)))


def test_version_mismatch_fails_closed():
    context, request, *_ = graph()
    reference = replace(request.reference, contract_version="2.0.0")
    assert_code(ResolutionFailureCode.VERSION_MISMATCH,
                lambda: resolve_governed_reference(replace(request, reference=reference), context))


def test_snapshot_reference_digest_mismatch_fails_closed():
    context, request, *_ = graph()
    reference = replace(request.reference, snapshot_digest="b" * 64)
    assert_code(ResolutionFailureCode.DIGEST_MISMATCH,
                lambda: resolve_governed_reference(replace(request, reference=reference), context))


def test_object_reference_digest_mismatch_fails_closed():
    context, request, *_ = graph()
    reference = replace(request.reference, object_digest="b" * 64)
    assert_code(ResolutionFailureCode.DIGEST_MISMATCH,
                lambda: resolve_governed_reference(replace(request, reference=reference), context))


def test_owner_mismatch_fails_closed():
    context, request, *_ = graph()
    reference = replace(request.reference, owner_domain="another-owner")
    assert_code(ResolutionFailureCode.OWNER_MISMATCH,
                lambda: resolve_governed_reference(replace(request, reference=reference), context))


def test_object_type_mismatch_fails_closed():
    context, request, *_ = graph()
    reference = replace(request.reference, object_class="OTHER")
    assert_code(ResolutionFailureCode.TYPE_MISMATCH,
                lambda: resolve_governed_reference(replace(request, reference=reference), context))


def test_authority_mismatch_fails_closed():
    context, request, *_ = graph()
    wrong = replace(request, expected_authority=AuthorityClass.INFERENCE)
    assert_code(ResolutionFailureCode.AUTHORITY_MISMATCH,
                lambda: resolve_governed_reference(wrong, context))


def test_incompatible_context_identity_fails_closed():
    context, request, *_ = graph()
    wrong = replace(request, context_id="another-context")
    assert_code(ResolutionFailureCode.INCOMPATIBLE_CONTEXT,
                lambda: resolve_governed_reference(wrong, context))


def test_stale_context_digest_fails_closed():
    context, request, *_ = graph()
    wrong = replace(request, context_digest="b" * 64)
    assert_code(ResolutionFailureCode.STALE_CONTEXT,
                lambda: resolve_governed_reference(wrong, context))


def test_missing_required_semantic_value_fails_closed():
    context, request, *_ = graph()
    wrong = replace(request, required_semantic_fields=("missing", "value"))
    assert_code(ResolutionFailureCode.MISSING_SEMANTIC_VALUE,
                lambda: resolve_governed_reference(wrong, context))


def test_missing_required_provenance_role_fails_closed():
    context, request, *_ = graph()
    wrong = replace(request, required_relationship_kinds=(
        RelationshipKind.EVIDENCE_SUPPORT, RelationshipKind.PROVENANCE))
    assert_code(ResolutionFailureCode.INCOMPLETE_PROVENANCE,
                lambda: resolve_governed_reference(wrong, context))


def test_missing_required_relationship_role_fails_closed():
    context, request, *_ = graph()
    wrong = replace(request, required_relationship_kinds=(RelationshipKind.DEPENDENCY,))
    assert_code(ResolutionFailureCode.INCOMPLETE_RELATIONSHIP_CLOSURE,
                lambda: resolve_governed_reference(wrong, context))


def test_broken_nested_provenance_fails_closed():
    context, request, fact_snapshot, evidence_snapshot, provenance_snapshot = graph()
    evidence = evidence_snapshot.objects[0]
    broken_target = replace(evidence.relationships[0].target, object_id="source-missing")
    broken_evidence = create_governed_object(
        owner_domain=evidence.owner_domain, owner_contract=evidence.owner_contract,
        contract_version=evidence.contract_version, object_class=evidence.object_class,
        object_id=evidence.object_id, authority=evidence.authority,
        semantic_fields=evidence.semantic_fields,
        relationships=(replace(evidence.relationships[0], target=broken_target),))
    broken_evidence_snapshot = create_governed_snapshot(
        owner_domain=evidence_snapshot.owner_domain,
        owner_contract=evidence_snapshot.owner_contract,
        contract_version=evidence_snapshot.contract_version,
        snapshot_id=evidence_snapshot.snapshot_id, objects=(broken_evidence,))
    old_evidence_ref = request.reference
    root = fact_snapshot.objects[0]
    new_evidence_ref = reference_to(broken_evidence_snapshot, "EVIDENCE", "evidence-1")
    broken_root = create_governed_object(
        owner_domain=root.owner_domain, owner_contract=root.owner_contract,
        contract_version=root.contract_version, object_class=root.object_class,
        object_id=root.object_id, authority=root.authority,
        semantic_fields=root.semantic_fields,
        relationships=(replace(root.relationships[0], target=new_evidence_ref),))
    broken_fact_snapshot = create_governed_snapshot(
        owner_domain=fact_snapshot.owner_domain, owner_contract=fact_snapshot.owner_contract,
        contract_version=fact_snapshot.contract_version,
        snapshot_id=fact_snapshot.snapshot_id, objects=(broken_root,))
    broken_context = create_resolution_context(
        context_id=context.context_id, context_version=context.context_version,
        snapshots=(broken_fact_snapshot, broken_evidence_snapshot, provenance_snapshot))
    broken_request = replace(
        request, reference=reference_to(broken_fact_snapshot, "DEADLINE", "deadline-1"),
        context_digest=broken_context.context_digest)
    assert old_evidence_ref.object_id == "deadline-1"
    assert_code(ResolutionFailureCode.INCOMPLETE_PROVENANCE,
                lambda: resolve_governed_reference(broken_request, broken_context))


def test_broken_evidence_relationship_closure_fails_closed():
    context, request, fact_snapshot, evidence_snapshot, provenance_snapshot = graph()
    root = fact_snapshot.objects[0]
    broken_target = replace(root.relationships[0].target, object_id="evidence-missing")
    broken_root = create_governed_object(
        owner_domain=root.owner_domain, owner_contract=root.owner_contract,
        contract_version=root.contract_version, object_class=root.object_class,
        object_id=root.object_id, authority=root.authority,
        semantic_fields=root.semantic_fields,
        relationships=(replace(root.relationships[0], target=broken_target),))
    broken_snapshot = create_governed_snapshot(
        owner_domain=fact_snapshot.owner_domain, owner_contract=fact_snapshot.owner_contract,
        contract_version=fact_snapshot.contract_version,
        snapshot_id=fact_snapshot.snapshot_id, objects=(broken_root,))
    broken_context = create_resolution_context(
        context_id=context.context_id, context_version=context.context_version,
        snapshots=(broken_snapshot, evidence_snapshot, provenance_snapshot))
    broken_request = replace(
        request, reference=reference_to(broken_snapshot, "DEADLINE", "deadline-1"),
        context_digest=broken_context.context_digest)
    assert_code(ResolutionFailureCode.INCOMPLETE_RELATIONSHIP_CLOSURE,
                lambda: resolve_governed_reference(broken_request, broken_context))


def test_repeated_identity_with_stale_binding_cannot_hide_behind_visited_object():
    context, request, fact_snapshot, evidence_snapshot, provenance_snapshot = graph()
    root = fact_snapshot.objects[0]
    valid = root.relationships[0]
    stale = GovernedRelationship(
        RelationshipKind.EVIDENCE_SUPPORT, "a-stale-binding",
        replace(valid.target, object_digest="b" * 64))
    changed_root = create_governed_object(
        owner_domain=root.owner_domain, owner_contract=root.owner_contract,
        contract_version=root.contract_version, object_class=root.object_class,
        object_id=root.object_id, authority=root.authority,
        semantic_fields=root.semantic_fields, relationships=(stale, valid))
    changed_snapshot = create_governed_snapshot(
        owner_domain=fact_snapshot.owner_domain, owner_contract=fact_snapshot.owner_contract,
        contract_version=fact_snapshot.contract_version,
        snapshot_id=fact_snapshot.snapshot_id, objects=(changed_root,))
    changed_context = create_resolution_context(
        context_id=context.context_id, context_version=context.context_version,
        snapshots=(changed_snapshot, evidence_snapshot, provenance_snapshot))
    changed_request = replace(
        request, reference=reference_to(changed_snapshot, "DEADLINE", "deadline-1"),
        context_digest=changed_context.context_digest)
    assert_code(ResolutionFailureCode.INCOMPLETE_RELATIONSHIP_CLOSURE,
                lambda: resolve_governed_reference(changed_request, changed_context))


def test_snapshot_rejects_object_from_another_owner():
    _, _, fact_snapshot, _, provenance_snapshot = graph()
    foreign = provenance_snapshot.objects[0]
    assert_code(ResolutionFailureCode.OWNER_MISMATCH,
                lambda: create_governed_snapshot(
                    owner_domain=fact_snapshot.owner_domain,
                    owner_contract=fact_snapshot.owner_contract,
                    contract_version=fact_snapshot.contract_version,
                    snapshot_id="mixed", objects=(foreign,)))


def test_governed_object_rejects_missing_semantic_content():
    assert_code(ResolutionFailureCode.MISSING_SEMANTIC_VALUE,
                lambda: create_governed_object(
                    owner_domain="owner", owner_contract="contract",
                    contract_version="1.0.0", object_class="FACT",
                    object_id="fact-1", authority=AuthorityClass.CANONICAL_FACT,
                    semantic_fields=()))


def test_no_current_state_or_other_snapshot_substitution():
    context, request, fact_snapshot, evidence_snapshot, provenance_snapshot = graph()
    current_snapshot = create_governed_snapshot(
        owner_domain=fact_snapshot.owner_domain,
        owner_contract=fact_snapshot.owner_contract,
        contract_version=fact_snapshot.contract_version,
        snapshot_id="fact-snapshot-current", objects=fact_snapshot.objects)
    context_without_requested_snapshot = create_resolution_context(
        context_id=context.context_id, context_version=context.context_version,
        snapshots=(current_snapshot, evidence_snapshot, provenance_snapshot))
    rebound = replace(request, context_digest=context_without_requested_snapshot.context_digest)
    assert_code(ResolutionFailureCode.MISSING_REFERENCE,
                lambda: resolve_governed_reference(rebound, context_without_requested_snapshot))


def test_reference_factory_requires_exact_registered_identity():
    _, _, fact_snapshot, *_ = graph()
    assert_code(ResolutionFailureCode.MISSING_REFERENCE,
                lambda: reference_to(fact_snapshot, "DEADLINE", "missing"))


def test_invalid_scalar_shapes_fail_closed():
    assert_code(ResolutionFailureCode.INVALID_CONTRACT,
                lambda: SemanticValue(SemanticValueKind.INTEGER, True))
    assert_code(ResolutionFailureCode.INVALID_CONTRACT,
                lambda: SemanticValue(SemanticValueKind.DECIMAL, "01.50"))
    assert_code(ResolutionFailureCode.INVALID_CONTRACT,
                lambda: SemanticValue(SemanticValueKind.STRING, "x", items=(text("y"),)))


def test_required_inputs_must_already_be_canonically_ordered():
    context, request, *_ = graph()
    assert context.context_digest
    assert_code(ResolutionFailureCode.INVALID_CONTRACT,
                lambda: replace(request, required_semantic_fields=("value", "precision")))


def test_fact_cannot_satisfy_an_evidence_relationship():
    draft_self = GovernedObjectReference(
        "owner", "contract", "1.0.0", "snapshot", "0" * 64,
        "FACT", "fact-1", "0" * 64)
    fact = create_governed_object(
        owner_domain="owner", owner_contract="contract", contract_version="1.0.0",
        object_class="FACT", object_id="fact-1", authority=AuthorityClass.CANONICAL_FACT,
        semantic_fields=(field("value", "x"),),
        relationships=(GovernedRelationship(
            RelationshipKind.EVIDENCE_SUPPORT, "evidence", draft_self),))
    snapshot = create_governed_snapshot(
        owner_domain="owner", owner_contract="contract", contract_version="1.0.0",
        snapshot_id="snapshot", objects=(fact,))
    context = create_resolution_context(
        context_id="context", context_version="1.0.0", snapshots=(snapshot,))
    reference = reference_to(snapshot, "FACT", "fact-1")
    request = ResolutionRequest(
        reference, context.context_id, context.context_digest,
        AuthorityClass.CANONICAL_FACT)
    assert_code(ResolutionFailureCode.AUTHORITY_MISMATCH,
                lambda: resolve_governed_reference(request, context))


def test_factories_reject_unsupported_nested_inputs_fail_closed():
    assert_code(ResolutionFailureCode.INVALID_CONTRACT,
                lambda: create_governed_object(
                    owner_domain="owner", owner_contract="contract",
                    contract_version="1.0.0", object_class="FACT",
                    object_id="fact-1", authority=AuthorityClass.CANONICAL_FACT,
                    semantic_fields=("invalid",)))
    assert_code(ResolutionFailureCode.INVALID_CONTRACT,
                lambda: create_resolution_context(
                    context_id="context", context_version="1.0.0",
                    snapshots=("invalid",)))


def test_same_snapshot_relationships_receive_exact_digest_bindings():
    target = create_governed_object(
        owner_domain="owner", owner_contract="contract", contract_version="1.0.0",
        object_class="EVIDENCE", object_id="evidence-1", authority=AuthorityClass.EVIDENCE,
        semantic_fields=(field("text", "Exact evidence"),))
    draft_target = GovernedObjectReference(
        "owner", "contract", "1.0.0", "snapshot-1", "0" * 64,
        "EVIDENCE", "evidence-1", "0" * 64)
    source = create_governed_object(
        owner_domain="owner", owner_contract="contract", contract_version="1.0.0",
        object_class="FACT", object_id="fact-1", authority=AuthorityClass.CANONICAL_FACT,
        semantic_fields=(field("value", "Exact fact"),),
        relationships=(GovernedRelationship(
            RelationshipKind.EVIDENCE_SUPPORT, "evidence", draft_target),))
    snapshot = create_governed_snapshot(
        owner_domain="owner", owner_contract="contract", contract_version="1.0.0",
        snapshot_id="snapshot-1", objects=(source, target))
    source_ref = reference_to(snapshot, "FACT", "fact-1")
    relationship = next(item for item in snapshot.objects
                        if item.object_id == "fact-1").relationships[0]
    assert relationship.target.snapshot_digest == snapshot.snapshot_digest
    assert relationship.target.object_digest == target.object_digest
    context = create_resolution_context(
        context_id="context", context_version="1.0.0", snapshots=(snapshot,))
    result = resolve_governed_reference(ResolutionRequest(
        source_ref, context.context_id, context.context_digest,
        AuthorityClass.CANONICAL_FACT,
        required_relationship_kinds=(RelationshipKind.EVIDENCE_SUPPORT,)), context)
    assert tuple(item.value.object_id for item in result.objects) == ("evidence-1", "fact-1")


def test_same_snapshot_cycles_are_bounded_and_deterministic():
    a_to_b = GovernedObjectReference(
        "owner", "contract", "1.0.0", "snapshot-cycle", "0" * 64,
        "NODE", "node-b", "0" * 64)
    b_to_a = replace(a_to_b, object_id="node-a")
    node_a = create_governed_object(
        owner_domain="owner", owner_contract="contract", contract_version="1.0.0",
        object_class="NODE", object_id="node-a", authority=AuthorityClass.COORDINATION_RECORD,
        semantic_fields=(field("label", "A"),),
        relationships=(GovernedRelationship(RelationshipKind.RELATED, "peer", a_to_b),))
    node_b = create_governed_object(
        owner_domain="owner", owner_contract="contract", contract_version="1.0.0",
        object_class="NODE", object_id="node-b", authority=AuthorityClass.COORDINATION_RECORD,
        semantic_fields=(field("label", "B"),),
        relationships=(GovernedRelationship(RelationshipKind.RELATED, "peer", b_to_a),))
    snapshot = create_governed_snapshot(
        owner_domain="owner", owner_contract="contract", contract_version="1.0.0",
        snapshot_id="snapshot-cycle", objects=(node_b, node_a))
    context = create_resolution_context(
        context_id="cycle-context", context_version="1.0.0", snapshots=(snapshot,))
    root = reference_to(snapshot, "NODE", "node-a")
    result = resolve_governed_reference(ResolutionRequest(
        root, context.context_id, context.context_digest,
        AuthorityClass.COORDINATION_RECORD), context)
    assert tuple(item.value.object_id for item in result.objects) == ("node-a", "node-b")
    assert len(result.relationships) == 2
