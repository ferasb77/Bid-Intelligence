from dataclasses import FrozenInstanceError, replace

import pytest

from evidence import (
    EvidenceObjectClass,
    EvidenceRelationshipKind,
    create_evidence_snapshot,
)
from evidence_publication import (
    OWNER_CONTRACT,
    OWNER_DOMAIN,
    PUBLICATION_CONTRACT_VERSION,
    EvidencePublicationError,
    EvidencePublicationFailureCode,
    publish_evidence,
    validate_evidence_publication,
)
from governed_reference_resolution import (
    AuthorityClass,
    RelationshipKind,
    ResolutionRequest,
    create_resolution_context,
    resolve_governed_reference,
)
from tests.test_evidence import _corpus


def _publication(**kwargs):
    return publish_evidence(create_evidence_snapshot(_corpus(**kwargs)))


def test_publishes_only_the_four_evidence_owned_semantic_classes():
    publication = _publication()
    assert {item.object_class for item in publication.snapshot.objects} == {
        item.value for item in EvidenceObjectClass
    }
    assert all(item.authority is AuthorityClass.EVIDENCE
               for item in publication.snapshot.objects)


def test_publication_is_deterministic_for_identical_evidence():
    first = _publication()
    second = _publication()
    assert first == second
    assert first.publication_id == second.publication_id
    assert first.publication_digest == second.publication_digest
    assert first.snapshot.snapshot_id == second.snapshot.snapshot_id
    assert first.snapshot.snapshot_digest == second.snapshot.snapshot_digest
    assert first.references == second.references
    assert first.to_json() == second.to_json()


def test_governed_references_are_exact_complete_and_ordered():
    publication = _publication()
    assert len(publication.references) == len(publication.snapshot.objects)
    assert tuple((item.object_class, item.object_id) for item in publication.references) == tuple(
        (item.object_class, item.object_id) for item in publication.snapshot.objects)
    assert all((item.owner_domain, item.owner_contract, item.contract_version) ==
               (OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION)
               for item in publication.references)
    assert all(item.snapshot_id == publication.snapshot.snapshot_id
               and item.snapshot_digest == publication.snapshot.snapshot_digest
               for item in publication.references)


def test_every_reference_resolves_with_evidence_authority_and_closure():
    publication = _publication()
    context = create_resolution_context(
        context_id="evidence-context-1", context_version="1.0.0",
        snapshots=(publication.snapshot,))
    for reference in publication.references:
        result = resolve_governed_reference(
            ResolutionRequest(reference, context.context_id,
                              context.context_digest, AuthorityClass.EVIDENCE),
            context)
        assert result.root.object_id == reference.object_id
        assert result.root.object_digest == reference.object_digest


def test_semantic_content_is_a_faithful_projection():
    source = create_evidence_snapshot(_corpus())
    publication = publish_evidence(source)
    published = {(item.object_class, item.object_id): item
                 for item in publication.snapshot.objects}
    manifest = {(item.object_class, item.object_id): item
                for item in publication.manifest.objects}
    for item in source.objects:
        target = published[(item.object_class.value, item.object_id)]
        actual = {field.name for field in target.semantic_fields}
        assert actual == set(item.to_dict()["semantics"])
        assert manifest[(item.object_class.value, item.object_id)].source_object_digest == item.object_digest


def test_relationship_manifest_preserves_exact_evidence_relationships():
    source = create_evidence_snapshot(_corpus())
    publication = publish_evidence(source)
    assert len(publication.manifest.relationships) == len(source.manifest.relationships)
    source_edges = tuple((
        item.source_class, item.source_id, item.kind, item.role, item.ordinal,
        item.target_class, item.target_id) for item in source.manifest.relationships)
    published_edges = tuple((
        item.source_class, item.source_id, item.evidence_kind,
        item.evidence_role, item.ordinal, item.target_class, item.target_id)
        for item in publication.manifest.relationships)
    assert published_edges == source_edges
    assert all(item.target_reference.owner_domain == OWNER_DOMAIN
               for item in publication.manifest.relationships)


def test_occurrence_provenance_is_resolver_navigable():
    publication = _publication()
    occurrence = next(item for item in publication.snapshot.objects
                      if item.object_class == EvidenceObjectClass.OCCURRENCE.value)
    assert {item.kind for item in occurrence.relationships} == {RelationshipKind.PROVENANCE}
    assert {item.target.object_class for item in occurrence.relationships} == {
        EvidenceObjectClass.SOURCE.value,
        EvidenceObjectClass.ARTIFACT.value,
    }
    entries = [item for item in publication.manifest.relationships
               if item.source_id == occurrence.object_id]
    assert {item.evidence_kind for item in entries} == {
        EvidenceRelationshipKind.ATTRIBUTABLE_SOURCE,
        EvidenceRelationshipKind.ARTIFACT_OCCURRENCE,
    }


def test_publication_and_all_members_are_deeply_immutable():
    publication = _publication()
    with pytest.raises(FrozenInstanceError):
        publication.publication_id = "changed"
    with pytest.raises(FrozenInstanceError):
        publication.manifest.manifest_digest = "0" * 64
    with pytest.raises(FrozenInstanceError):
        publication.manifest.relationships[0].target_id = "changed"
    with pytest.raises(TypeError):
        publication.references[0] = publication.references[-1]


def test_invalid_source_type_fails_closed():
    with pytest.raises(EvidencePublicationError) as captured:
        publish_evidence(object())
    assert captured.value.code is EvidencePublicationFailureCode.INVALID_SOURCE


def test_tampered_publication_identity_digest_and_manifest_fail_closed():
    publication = _publication()
    with pytest.raises(EvidencePublicationError) as captured:
        replace(publication, publication_id="evidence-publication-record-" + "0" * 64)
    assert captured.value.code is EvidencePublicationFailureCode.DIGEST_MISMATCH
    with pytest.raises(EvidencePublicationError) as captured:
        replace(publication, publication_digest="0" * 64)
    assert captured.value.code is EvidencePublicationFailureCode.DIGEST_MISMATCH
    with pytest.raises(EvidencePublicationError) as captured:
        replace(publication, manifest=replace(
            publication.manifest, manifest_digest="0" * 64))
    assert captured.value.code is EvidencePublicationFailureCode.DIGEST_MISMATCH


def test_missing_duplicate_or_reordered_references_fail_closed():
    publication = _publication()
    for references in (
        publication.references[:-1],
        publication.references + (publication.references[-1],),
        tuple(reversed(publication.references)),
    ):
        with pytest.raises(EvidencePublicationError):
            replace(publication, references=references)


def test_broken_relationship_manifest_fails_closed():
    publication = _publication()
    relationships = publication.manifest.relationships[:-1]
    with pytest.raises(EvidencePublicationError) as captured:
        replace(publication, manifest=replace(
            publication.manifest, relationships=relationships))
    assert captured.value.code is EvidencePublicationFailureCode.BROKEN_RELATIONSHIP


def test_historical_source_snapshots_produce_distinct_immutable_publications():
    old = _publication(text="old source text", version="1")
    new = _publication(text="new source text", version="2")
    assert old.source_snapshot_id != new.source_snapshot_id
    assert old.publication_id != new.publication_id
    assert old.snapshot.snapshot_id != new.snapshot.snapshot_id
    validate_evidence_publication(old)
    validate_evidence_publication(new)


def test_publication_does_not_create_context_bindings_or_downstream_content():
    publication = _publication()
    assert not hasattr(publication, "resolution_context")
    assert not hasattr(publication, "support_bindings")
    assert not hasattr(publication, "canonical_opportunity")
    assert not hasattr(publication, "analysis")
    assert not hasattr(publication, "presentation")


def test_source_snapshot_is_not_mutated():
    source = create_evidence_snapshot(_corpus())
    before = source.to_json()
    publish_evidence(source)
    assert source.to_json() == before
