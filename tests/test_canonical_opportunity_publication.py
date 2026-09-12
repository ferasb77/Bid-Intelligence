from dataclasses import FrozenInstanceError, replace
import copy
import json

import pytest

from canonical_opportunity import (
    build_canonical_opportunity, resolve_canonical_opportunity,
)
from canonical_opportunity_publication import (
    CONFLICT_CLASS, FIELD_STATE_CLASS, IDENTITY_CLASS, OBSERVATION_CLASS,
    CanonicalObservationBinding, CanonicalOpportunityPublicationError,
    CanonicalPublicationFailureCode, identity_object_id,
    publish_canonical_opportunity, validate_canonical_opportunity_publication,
)
from governed_reference_resolution import (
    AuthorityClass, RelationshipKind, ResolutionRequest, SemanticField,
    SemanticValue, SemanticValueKind, create_governed_object,
    create_governed_snapshot, create_resolution_context, reference_to,
    resolve_governed_reference,
)


def _metadata(*names):
    return {
        "files": list(names),
        "doc_metadata": {name: {"page_count": 1} for name in names},
        "doc_texts": {name: f"[[SOURCE: {name} | PAGE: 1]]\nTender Alpha 2030-01-01 2030-01-02"
                      for name in names},
    }


def _observation(kind, value, doc="a.pdf", family="IDENTITY", **extra):
    return {
        "family": family, "semantic_kind": kind, "original_value": value,
        "source_doc": doc,
        "source_refs": [{"source_doc": doc, "page": 1, "excerpt": str(value)}],
        **extra,
    }


def _canonical(*, conflict=False, supersession=False, empty_value=False):
    items = [_observation("OPPORTUNITY_TITLE", "Tender Alpha")]
    names = ["a.pdf"]
    if conflict:
        items.append(_observation("OPPORTUNITY_TITLE", "Tender Beta"))
    if empty_value:
        # A typed observation with no real textual value (e.g. a bare
        # procurement-mechanic marker) legitimately normalizes to
        # normalization_state "EMPTY" / normalized_value "" -- this must
        # remain publishable, not rejected as invalid content.
        items.append(_observation("RFP", "", family="PROCUREMENT_MECHANIC"))
    if supersession:
        names.append("b.pdf")
        old = _observation("SUBMISSION_DEADLINE", "2030-01-01",
                           family="MILESTONE", date="2030-01-01")
        new = _observation("SUBMISSION_DEADLINE", "2030-01-02", doc="b.pdf",
                           family="MILESTONE", date="2030-01-02")
        new["supersession"] = {
            "basis": "EXPLICIT_EXTENSION", "target_family": "MILESTONE",
            "target_semantic_kind": "SUBMISSION_DEADLINE",
            "old_value": "2030-01-01", "new_value": "2030-01-02", "scope": {},
            "source_refs": [{"source_doc": "b.pdf", "page": 1,
                             "excerpt": "2030-01-01 2030-01-02"}],
        }
        items.extend((old, new))
    metadata = _metadata(*names)
    if conflict:
        metadata["doc_texts"]["a.pdf"] += " Tender Beta"
    return resolve_canonical_opportunity(
        build_canonical_opportunity([{"typed_observations": items}], metadata))


def _external_snapshots():
    provenance = create_governed_object(
        owner_domain="source-registry", owner_contract="source-record",
        contract_version="1.0.0", object_class="PROVENANCE",
        object_id="provenance-1", authority=AuthorityClass.EVIDENCE,
        semantic_fields=(SemanticField(
            "locator", SemanticValue(SemanticValueKind.STRING, "page 1")),),
    )
    provenance_snapshot = create_governed_snapshot(
        owner_domain="source-registry", owner_contract="source-record",
        contract_version="1.0.0", snapshot_id="provenance-snapshot-1",
        objects=(provenance,),
    )
    provenance_reference = reference_to(
        provenance_snapshot, "PROVENANCE", "provenance-1")
    evidence = create_governed_object(
        owner_domain="opportunity-evidence", owner_contract="evidence-record",
        contract_version="1.0.0", object_class="EVIDENCE",
        object_id="evidence-1", authority=AuthorityClass.EVIDENCE,
        semantic_fields=(SemanticField(
            "content_digest", SemanticValue(SemanticValueKind.STRING, "source-digest")),),
        relationships=(),
    )
    evidence_snapshot = create_governed_snapshot(
        owner_domain="opportunity-evidence", owner_contract="evidence-record",
        contract_version="1.0.0", snapshot_id="evidence-snapshot-1",
        objects=(evidence,),
    )
    return (evidence_snapshot, provenance_snapshot,
            reference_to(evidence_snapshot, "EVIDENCE", "evidence-1"),
            provenance_reference)


def _bindings(canonical):
    _, _, evidence, provenance = _external_snapshots()
    return tuple(CanonicalObservationBinding(
        item["observation_id"], (evidence,), (provenance,))
        for item in canonical["observations"])


def _publication(canonical=None):
    canonical = canonical or _canonical()
    return publish_canonical_opportunity(
        canonical, opportunity_id="opportunity-1",
        observation_bindings=_bindings(canonical))


def test_publishes_only_owned_canonical_object_classes():
    canonical = _canonical(conflict=True)
    publication = _publication(canonical)
    classes = {item.object_class for item in publication.snapshot.objects}
    assert classes == {FIELD_STATE_CLASS, OBSERVATION_CLASS, CONFLICT_CLASS, IDENTITY_CLASS}
    assert sum(item.object_class == FIELD_STATE_CLASS
               for item in publication.snapshot.objects) == len(canonical["resolved"])
    assert sum(item.object_class == OBSERVATION_CLASS
               for item in publication.snapshot.objects) == len(canonical["observations"])
    assert sum(item.object_class == CONFLICT_CLASS
               for item in publication.snapshot.objects) == len(canonical["conflicts"])
    assert sum(item.object_class == IDENTITY_CLASS for item in publication.snapshot.objects) == 1


def test_opportunity_identity_is_additive_deterministic_and_references_every_field_state():
    canonical = _canonical(conflict=True)
    publication = _publication(canonical)
    identity_id = identity_object_id("opportunity-1", canonical["input_digest"])
    identity = next(item for item in publication.snapshot.objects if item.object_class == IDENTITY_CLASS)
    assert identity.object_id == identity_id
    field_names = {field.name for field in identity.semantic_fields}
    assert field_names == {"opportunity_id", "source_schema_version",
                           "authoritative_input_digest", "document_count"}
    contained_field_states = {
        relationship.target.object_id for relationship in identity.relationships
        if relationship.kind == RelationshipKind.DEPENDENCY}
    expected_field_ids = {
        item.object_id for item in publication.snapshot.objects
        if item.object_class == FIELD_STATE_CLASS}
    assert contained_field_states == expected_field_ids
    # Republishing the identical real input produces the identical identity.
    second = _publication(canonical)
    second_identity = next(item for item in second.snapshot.objects if item.object_class == IDENTITY_CLASS)
    assert second_identity.object_id == identity.object_id
    assert second_identity.object_digest == identity.object_digest


def test_publishes_an_observation_with_an_empty_normalized_value():
    canonical = _canonical(empty_value=True)
    publication = _publication(canonical)
    classes = {item.object_class for item in publication.snapshot.objects}
    assert OBSERVATION_CLASS in classes
    assert sum(item.object_class == OBSERVATION_CLASS
               for item in publication.snapshot.objects) == len(canonical["observations"])


def test_publication_is_deterministic_and_serialization_is_canonical():
    canonical = _canonical(conflict=True)
    first = _publication(canonical)
    second = _publication(copy.deepcopy(canonical))
    assert first == second
    assert first.publication_id == second.publication_id
    assert first.snapshot.snapshot_id == second.snapshot.snapshot_id
    assert first.snapshot.snapshot_digest == second.snapshot.snapshot_digest
    assert first.references == second.references
    assert first.to_json() == second.to_json()
    assert json.loads(first.to_json()) == first.to_dict()


def test_object_and_snapshot_membership_are_deeply_immutable():
    publication = _publication()
    with pytest.raises(FrozenInstanceError):
        publication.publication_id = "changed"
    with pytest.raises(FrozenInstanceError):
        publication.snapshot.snapshot_id = "changed"
    with pytest.raises(TypeError):
        publication.snapshot.objects[0] = publication.snapshot.objects[1]


def test_exact_canonical_semantics_are_preserved_without_provenance_content():
    canonical = _canonical()
    publication = _publication(canonical)
    observation = next(item for item in publication.snapshot.objects
                       if item.object_class == OBSERVATION_CLASS)
    fields = {item.name: item.value for item in observation.semantic_fields}
    assert fields["original_value"].scalar == "Tender Alpha"
    assert fields["provenance_status"].scalar == "VERIFIED"
    serialized = json.dumps(observation.to_dict(), sort_keys=True)
    assert "source_refs" not in serialized
    assert "extraction_occurrences" not in serialized
    assert "[[SOURCE" not in serialized


def test_relationship_manifest_preserves_evidence_provenance_and_conflicts():
    publication = _publication(_canonical(conflict=True))
    kinds = {item.kind for item in publication.manifest.relationships}
    assert RelationshipKind.EVIDENCE_SUPPORT in kinds
    assert RelationshipKind.PROVENANCE in kinds
    assert RelationshipKind.CONFLICT_MEMBER in kinds
    assert all(item.target.owner_domain != "canonical-opportunity"
               for item in publication.manifest.relationships
               if item.kind in {RelationshipKind.EVIDENCE_SUPPORT,
                                RelationshipKind.PROVENANCE})


def test_external_relationship_binding_participates_in_publication_identity():
    canonical = _canonical()
    first = _publication(canonical)
    evidence, provenance, _, provenance_reference = _external_snapshots()
    changed = create_governed_object(
        owner_domain="opportunity-evidence", owner_contract="evidence-record",
        contract_version="1.0.0", object_class="EVIDENCE",
        object_id="evidence-2", authority=AuthorityClass.EVIDENCE,
        semantic_fields=(SemanticField(
            "content_digest", SemanticValue(SemanticValueKind.STRING, "other-source")),),
    )
    changed_snapshot = create_governed_snapshot(
        owner_domain="opportunity-evidence", owner_contract="evidence-record",
        contract_version="1.0.0", snapshot_id="evidence-snapshot-2",
        objects=(changed,),
    )
    changed_reference = reference_to(changed_snapshot, "EVIDENCE", "evidence-2")
    bindings = tuple(CanonicalObservationBinding(
        item["observation_id"], (changed_reference,), (provenance_reference,))
        for item in canonical["observations"])
    second = publish_canonical_opportunity(
        canonical, opportunity_id="opportunity-1", observation_bindings=bindings)
    assert first.manifest.object_manifest_digest != second.manifest.object_manifest_digest
    assert first.snapshot.snapshot_id != second.snapshot.snapshot_id
    assert first.snapshot.snapshot_digest != second.snapshot.snapshot_digest


def test_verified_supersession_is_published_as_exact_internal_relationship():
    publication = _publication(_canonical(supersession=True))
    links = [item for item in publication.manifest.relationships
             if item.kind == RelationshipKind.SUPERSESSION]
    assert len(links) == 1
    assert links[0].source_class == OBSERVATION_CLASS
    assert links[0].target.object_class == OBSERVATION_CLASS
    assert links[0].target.owner_domain == "canonical-opportunity"


def test_every_reference_resolves_with_complete_external_context():
    canonical = _canonical(conflict=True)
    publication = _publication(canonical)
    evidence, provenance, _, _ = _external_snapshots()
    context = create_resolution_context(
        context_id="canonical-context-1", context_version="1.0.0",
        snapshots=(publication.snapshot, evidence, provenance))
    authority = {
        FIELD_STATE_CLASS: AuthorityClass.CANONICAL_FACT,
        OBSERVATION_CLASS: AuthorityClass.OBSERVATION,
        CONFLICT_CLASS: AuthorityClass.CONFLICT,
        IDENTITY_CLASS: AuthorityClass.CANONICAL_FACT,
    }
    for reference in publication.references:
        result = resolve_governed_reference(
            ResolutionRequest(reference, context.context_id, context.context_digest,
                              authority[reference.object_class]), context)
        assert result.root.object_id == reference.object_id
        assert result.root.object_digest == reference.object_digest


def test_publication_does_not_assemble_a_resolution_context_or_support_bindings():
    publication = _publication()
    assert not hasattr(publication, "resolution_context")
    assert not hasattr(publication, "support_bindings")
    assert not hasattr(publication, "requirements")
    assert not hasattr(publication, "evaluation_entities")
    assert not hasattr(publication, "submission_entities")


def test_missing_observation_bindings_fail_closed():
    canonical = _canonical()
    with pytest.raises(CanonicalOpportunityPublicationError) as captured:
        publish_canonical_opportunity(
            canonical, opportunity_id="opportunity-1", observation_bindings=())
    assert captured.value.code == CanonicalPublicationFailureCode.MISSING_RELATIONSHIP_BINDING


def test_incomplete_evidence_or_provenance_fails_closed():
    canonical = _canonical()
    _, _, evidence, provenance = _external_snapshots()
    observation_id = canonical["observations"][0]["observation_id"]
    for binding in (
            CanonicalObservationBinding(observation_id, (evidence,), ()),
            CanonicalObservationBinding(observation_id, (), (provenance,))):
        with pytest.raises(CanonicalOpportunityPublicationError) as captured:
            publish_canonical_opportunity(
                canonical, opportunity_id="opportunity-1",
                observation_bindings=(binding,))
        assert captured.value.code == CanonicalPublicationFailureCode.MISSING_RELATIONSHIP_BINDING


def test_unresolved_or_wrong_version_canonical_state_fails_closed():
    canonical = _canonical()
    unresolved = copy.deepcopy(canonical)
    unresolved["integrity_diagnostics"]["resolution_complete"] = False
    with pytest.raises(CanonicalOpportunityPublicationError) as captured:
        publish_canonical_opportunity(
            unresolved, opportunity_id="opportunity-1",
            observation_bindings=_bindings(unresolved))
    assert captured.value.code == CanonicalPublicationFailureCode.INVALID_CANONICAL_STATE
    wrong = copy.deepcopy(canonical)
    wrong["schema_version"] = "canonical-opportunity/2"
    with pytest.raises(CanonicalOpportunityPublicationError) as captured:
        publish_canonical_opportunity(
            wrong, opportunity_id="opportunity-1", observation_bindings=_bindings(wrong))
    assert captured.value.code == CanonicalPublicationFailureCode.VERSION_MISMATCH


def test_digest_tampering_and_unknown_semantics_fail_closed():
    canonical = _canonical()
    tampered = copy.deepcopy(canonical)
    tampered["input_digest"] = "input_" + "0" * 64
    with pytest.raises(CanonicalOpportunityPublicationError) as captured:
        publish_canonical_opportunity(
            tampered, opportunity_id="opportunity-1",
            observation_bindings=_bindings(tampered))
    assert captured.value.code == CanonicalPublicationFailureCode.DIGEST_MISMATCH
    unsupported = copy.deepcopy(canonical)
    unsupported["observations"][0]["new_meaning"] = "not declared"
    with pytest.raises(CanonicalOpportunityPublicationError) as captured:
        publish_canonical_opportunity(
            unsupported, opportunity_id="opportunity-1",
            observation_bindings=_bindings(unsupported))
    assert captured.value.code == CanonicalPublicationFailureCode.DIGEST_MISMATCH


def test_source_is_not_mutated_and_validation_rejects_tampered_publication():
    canonical = _canonical(conflict=True)
    before = copy.deepcopy(canonical)
    publication = _publication(canonical)
    assert canonical == before
    validate_canonical_opportunity_publication(publication)
    with pytest.raises(CanonicalOpportunityPublicationError) as captured:
        replace(publication, publication_id="canonical-publication-record-" + "0" * 64)
    assert captured.value.code == CanonicalPublicationFailureCode.DIGEST_MISMATCH
