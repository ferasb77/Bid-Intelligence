from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timezone
from hashlib import sha256

import pytest

from evidence import (
    ArtifactKind,
    AuthenticityState,
    EVIDENCE_CONTRACT_VERSION,
    EvidenceArtifact,
    EvidenceExtract,
    EvidenceFailureCode,
    EvidenceObjectClass,
    EvidenceOccurrence,
    EvidenceRelationshipKind,
    EvidenceSource,
    EvidenceValidationError,
    LocatorKind,
    RelationshipTarget,
    SourceKind,
    canonical_evidence_json,
    create_evidence_snapshot,
    validate_evidence_snapshot,
)


def _hash(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return sha256(value).hexdigest()


def _corpus(*, text="Issued requirement", version="1", occurrence_key="download-1"):
    content = text.encode("utf-8")
    digest = _hash(content)
    source = EvidenceSource(
        "bank-of-canada", "Bank of Canada", SourceKind.ORGANIZATION,
        "https://www.bankofcanada.ca/")
    artifact = EvidenceArtifact(
        source.object_id, ArtifactKind.DOCUMENT, "Request for Proposals",
        version, "application/pdf", "en", digest, content,
        publication_date=date(2030, 1, 2))
    occurrence = EvidenceOccurrence(
        source.object_id, artifact.object_id, occurrence_key,
        LocatorKind.WHOLE_ARTIFACT, "whole-document", "en",
        date(2030, 1, 3), AuthenticityState.VERIFIED, digest)
    extract = EvidenceExtract(
        artifact.object_id, occurrence.object_id, LocatorKind.PAGE, "page:1",
        "en", text, digest)
    return source, artifact, occurrence, extract


def test_four_immutable_evidence_objects_have_stable_identity_and_digest():
    values = _corpus()
    assert tuple(item.object_class for item in values) == (
        EvidenceObjectClass.SOURCE,
        EvidenceObjectClass.ARTIFACT,
        EvidenceObjectClass.OCCURRENCE,
        EvidenceObjectClass.EXTRACT,
    )
    assert all(len(item.object_digest) == 64 for item in values)
    assert values == _corpus()
    assert tuple(item.object_id for item in values) == tuple(
        item.object_id for item in _corpus())
    with pytest.raises(FrozenInstanceError):
        values[0].name = "Changed"


def test_semantic_change_changes_identity_or_digest():
    source, artifact, occurrence, extract = _corpus()
    changed_source = replace(source, name="Banque du Canada")
    assert changed_source.object_id == source.object_id
    assert changed_source.object_digest != source.object_digest

    changed = _corpus(text="Different issued requirement")
    assert changed[1].object_id != artifact.object_id
    assert changed[2].object_id != occurrence.object_id
    assert changed[3].object_id != extract.object_id


def test_canonical_serialization_normalizes_unicode_and_line_endings():
    left = canonical_evidence_json({"text": "Cafe\u0301\r\nLine"})
    right = canonical_evidence_json({"text": "Café\nLine"})
    assert left == right
    assert canonical_evidence_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'


def test_artifact_requires_verified_content_digest_or_governed_location():
    source = _corpus()[0]
    with pytest.raises(EvidenceValidationError) as captured:
        EvidenceArtifact(
            source.object_id, ArtifactKind.DOCUMENT, "RFP", "1",
            "application/pdf", "en", "0" * 64, b"content")
    assert captured.value.code is EvidenceFailureCode.DIGEST_MISMATCH

    remote = EvidenceArtifact(
        source.object_id, ArtifactKind.WEB_CAPTURE, "Notice", "2029-01-01",
        "text/html", "en", "1" * 64, governed_location="https://example.gov/notice")
    assert remote.content is None

    with pytest.raises(EvidenceValidationError) as captured:
        EvidenceArtifact(
            source.object_id, ArtifactKind.DOCUMENT, "RFP", "1",
            "application/pdf", "en", "1" * 64)
    assert captured.value.code is EvidenceFailureCode.INVALID_CONTENT


@pytest.mark.parametrize("url", ["relative/file.pdf", "ftp://example.gov/a", "https://u:p@example.gov/a"])
def test_invalid_or_credential_bearing_urls_fail_closed(url):
    with pytest.raises(EvidenceValidationError) as captured:
        EvidenceSource("source", "Source", SourceKind.ORGANIZATION, url)
    assert captured.value.code is EvidenceFailureCode.INVALID_VALUE


def test_extract_requires_bounded_exact_locator_and_matching_content():
    source, artifact, occurrence, _ = _corpus()
    with pytest.raises(EvidenceValidationError):
        EvidenceExtract(
            artifact.object_id, occurrence.object_id,
            LocatorKind.WHOLE_ARTIFACT, "whole-document", "en",
            "text", _hash("text"))
    with pytest.raises(EvidenceValidationError) as captured:
        EvidenceExtract(
            artifact.object_id, occurrence.object_id,
            LocatorKind.PAGE, "page 1 or nearby", "en", "text", "0" * 64)
    assert captured.value.code is EvidenceFailureCode.INVALID_VALUE
    with pytest.raises(EvidenceValidationError) as captured:
        EvidenceExtract(
            artifact.object_id, occurrence.object_id,
            LocatorKind.PAGE, "page:1", "en", "text", "0" * 64)
    assert captured.value.code is EvidenceFailureCode.DIGEST_MISMATCH


def test_dates_are_calendar_dates_and_language_is_canonicalized():
    source, artifact, _, _ = _corpus()
    occurrence = EvidenceOccurrence(
        source.object_id, artifact.object_id, "occurrence", LocatorKind.PAGE,
        "page:1", "EN-us", date(2030, 1, 3),
        AuthenticityState.UNVERIFIED, artifact.content_sha256)
    assert occurrence.language == "en-US"
    with pytest.raises(EvidenceValidationError):
        replace(occurrence, acquisition_date=datetime.now(timezone.utc))
    with pytest.raises(EvidenceValidationError):
        replace(occurrence, language="not_a_language")


def test_snapshot_canonically_orders_members_and_preserves_provenance():
    source, artifact, occurrence, extract = _corpus()
    snapshot = create_evidence_snapshot((extract, occurrence, artifact, source))
    assert snapshot.objects == (source, artifact, occurrence, extract)
    assert tuple(member.object_class for member in snapshot.manifest.members) == (
        EvidenceObjectClass.SOURCE,
        EvidenceObjectClass.ARTIFACT,
        EvidenceObjectClass.OCCURRENCE,
        EvidenceObjectClass.EXTRACT,
    )
    relationships = snapshot.manifest.relationships
    assert len(relationships) == 5
    assert any(item.kind is EvidenceRelationshipKind.ATTRIBUTABLE_SOURCE
               and item.source_id == occurrence.object_id for item in relationships)
    assert any(item.kind is EvidenceRelationshipKind.EXTRACT_OCCURRENCE
               and item.target_id == occurrence.object_id for item in relationships)
    validate_evidence_snapshot(snapshot)


def test_snapshot_identity_serialization_and_digest_are_deterministic():
    values = _corpus()
    first = create_evidence_snapshot(
        values, acquisition_corpus_id="corpus-1",
        acquisition_corpus_digest="a" * 64)
    second = create_evidence_snapshot(
        reversed(values), acquisition_corpus_id="corpus-1",
        acquisition_corpus_digest="a" * 64)
    assert first == second
    assert first.snapshot_id == second.snapshot_id
    assert first.snapshot_digest == second.snapshot_digest
    assert first.to_json() == second.to_json()


def test_snapshot_and_nested_members_are_deeply_immutable():
    snapshot = create_evidence_snapshot(_corpus())
    with pytest.raises(FrozenInstanceError):
        snapshot.snapshot_id = "changed"
    with pytest.raises(TypeError):
        snapshot.objects[0] = None
    with pytest.raises(FrozenInstanceError):
        snapshot.manifest.members[0].object_id = "changed"


def test_snapshot_rejects_duplicate_and_missing_provenance_members():
    source, artifact, occurrence, extract = _corpus()
    with pytest.raises(EvidenceValidationError) as captured:
        create_evidence_snapshot((source, source, artifact, occurrence, extract))
    assert captured.value.code is EvidenceFailureCode.DUPLICATE_IDENTITY

    with pytest.raises(EvidenceValidationError) as captured:
        create_evidence_snapshot((artifact, occurrence, extract))
    assert captured.value.code is EvidenceFailureCode.INCOMPLETE_PROVENANCE

    with pytest.raises(EvidenceValidationError) as captured:
        create_evidence_snapshot((source, artifact, extract))
    assert captured.value.code is EvidenceFailureCode.INCOMPLETE_PROVENANCE


def test_snapshot_rejects_language_and_artifact_lineage_mismatch():
    source, artifact, occurrence, extract = _corpus()
    mismatched = replace(occurrence, language="fr")
    with pytest.raises(EvidenceValidationError) as captured:
        create_evidence_snapshot((source, artifact, mismatched))
    assert captured.value.code is EvidenceFailureCode.INCOMPLETE_PROVENANCE

    other = _corpus(text="other", version="2", occurrence_key="download-2")[1]
    broken_extract = replace(extract, artifact_id=other.object_id)
    with pytest.raises(EvidenceValidationError) as captured:
        create_evidence_snapshot((source, artifact, occurrence, other, broken_extract))
    assert captured.value.code is EvidenceFailureCode.INCOMPLETE_PROVENANCE


def test_snapshot_rejects_tampered_digest_manifest_and_version():
    snapshot = create_evidence_snapshot(_corpus())
    with pytest.raises(EvidenceValidationError) as captured:
        replace(snapshot, snapshot_digest="0" * 64)
    assert captured.value.code is EvidenceFailureCode.DIGEST_MISMATCH
    with pytest.raises(EvidenceValidationError) as captured:
        replace(snapshot, contract_version="2.0.0")
    assert captured.value.code is EvidenceFailureCode.UNSUPPORTED_VERSION


def test_acquisition_corpus_binding_is_all_or_nothing():
    with pytest.raises(EvidenceValidationError) as captured:
        create_evidence_snapshot(_corpus(), acquisition_corpus_id="corpus-1")
    assert captured.value.code is EvidenceFailureCode.INCOMPLETE_SNAPSHOT


def test_historical_versions_remain_distinct_with_explicit_supersession():
    source, old, old_occurrence, _ = _corpus(text="old", version="1")
    _, new_base, new_occurrence_base, _ = _corpus(
        text="new", version="2", occurrence_key="download-2")
    relation = RelationshipTarget(
        EvidenceRelationshipKind.SUPERSEDES, "previous-version",
        EvidenceObjectClass.ARTIFACT, old.object_id)
    new = replace(new_base, relationships=(relation,))
    new_occurrence = replace(new_occurrence_base, artifact_id=new.object_id)
    snapshot = create_evidence_snapshot((source, old, old_occurrence, new, new_occurrence))
    assert old.object_id != new.object_id
    assert any(item.kind is EvidenceRelationshipKind.SUPERSEDES
               and item.source_id == new.object_id
               and item.target_id == old.object_id
               for item in snapshot.manifest.relationships)


def test_supersession_cycle_fails_closed():
    source, first_base, _, _ = _corpus(text="first", version="1")
    _, second_base, _, _ = _corpus(text="second", version="2")
    first = replace(first_base, relationships=(RelationshipTarget(
        EvidenceRelationshipKind.SUPERSEDES, "previous-version",
        EvidenceObjectClass.ARTIFACT, second_base.object_id),))
    second = replace(second_base, relationships=(RelationshipTarget(
        EvidenceRelationshipKind.SUPERSEDES, "previous-version",
        EvidenceObjectClass.ARTIFACT, first_base.object_id),))
    with pytest.raises(EvidenceValidationError) as captured:
        create_evidence_snapshot((source, first, second))
    assert captured.value.code is EvidenceFailureCode.SUPERSESSION_CYCLE


def test_relationships_must_be_canonical_and_same_class_where_required():
    source, artifact, occurrence, extract = _corpus()
    high = RelationshipTarget(
        EvidenceRelationshipKind.LINEAGE, "z", EvidenceObjectClass.SOURCE,
        source.object_id, 1)
    low = RelationshipTarget(
        EvidenceRelationshipKind.LINEAGE, "a", EvidenceObjectClass.SOURCE,
        source.object_id, 0)
    with pytest.raises(EvidenceValidationError) as captured:
        replace(extract, relationships=(high, low))
    assert captured.value.code is EvidenceFailureCode.INVALID_RELATIONSHIP

    invalid = replace(artifact, relationships=(RelationshipTarget(
        EvidenceRelationshipKind.SUPERSEDES, "invalid",
        EvidenceObjectClass.SOURCE, source.object_id),))
    with pytest.raises(EvidenceValidationError) as captured:
        create_evidence_snapshot((source, invalid, occurrence))
    assert captured.value.code is EvidenceFailureCode.INVALID_RELATIONSHIP


def test_contract_contains_no_publication_resolution_or_analysis_behavior():
    import evidence

    assert EVIDENCE_CONTRACT_VERSION == "1.0.0"
    assert not hasattr(evidence, "publish_evidence")
    assert not hasattr(evidence, "resolve_evidence")
    assert not hasattr(evidence, "analyze_evidence")
