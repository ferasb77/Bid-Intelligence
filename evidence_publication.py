"""Immutable owner publication for the domain-neutral Evidence contract."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from hashlib import sha256
from typing import Iterable, Mapping

from evidence import (
    EVIDENCE_CONTRACT_VERSION,
    EVIDENCE_OWNER,
    EVIDENCE_SNAPSHOT_VERSION,
    EvidenceObject,
    EvidenceObjectClass,
    EvidenceRelationship,
    EvidenceRelationshipKind,
    EvidenceSnapshot,
    EvidenceValidationError,
    canonical_evidence_json,
    validate_evidence_snapshot,
)
from governed_reference_resolution import (
    AuthorityClass,
    GovernedObject,
    GovernedObjectReference,
    GovernedRelationship,
    GovernedResolutionError,
    GovernedSnapshot,
    RelationshipKind,
    SemanticField,
    SemanticValue,
    SemanticValueKind,
    create_governed_object,
    create_governed_snapshot,
    reference_to,
)


OWNER_DOMAIN = EVIDENCE_OWNER
OWNER_CONTRACT = "evidence"
PUBLICATION_CONTRACT_VERSION = "1.0.0"

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_ZERO_DIGEST = "0" * 64
_CLASS_ORDER = {
    EvidenceObjectClass.SOURCE: 0,
    EvidenceObjectClass.ARTIFACT: 1,
    EvidenceObjectClass.OCCURRENCE: 2,
    EvidenceObjectClass.EXTRACT: 3,
}


class EvidencePublicationFailureCode(str, Enum):
    INVALID_SOURCE = "INVALID_SOURCE"
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"
    DUPLICATE_IDENTITY = "DUPLICATE_IDENTITY"
    MISSING_SEMANTIC_CONTENT = "MISSING_SEMANTIC_CONTENT"
    BROKEN_RELATIONSHIP = "BROKEN_RELATIONSHIP"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    INVALID_PUBLICATION = "INVALID_PUBLICATION"


class EvidencePublicationError(ValueError):
    def __init__(self, code: EvidencePublicationFailureCode, message: str):
        self.code = code
        super().__init__(f"{code.value}: {message}")


def _fail(code: EvidencePublicationFailureCode, message: str):
    raise EvidencePublicationError(code, message)


def _canonical(value):
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {item.name: _canonical(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _canonical(value[key]) for key in sorted(value)}
    return value


def canonical_publication_json(value) -> str:
    return json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _sha(value) -> str:
    return sha256(canonical_publication_json(value).encode("utf-8")).hexdigest()


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        _fail(EvidencePublicationFailureCode.INVALID_PUBLICATION,
              f"{name} is not a stable identifier")
    return value


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        _fail(EvidencePublicationFailureCode.DIGEST_MISMATCH,
              f"{name} must be a lowercase SHA-256 digest")
    return value


def _semantic_value(value) -> SemanticValue:
    if value is None:
        return SemanticValue(SemanticValueKind.NULL)
    if type(value) is bool:
        return SemanticValue(SemanticValueKind.BOOLEAN, value)
    if type(value) is int:
        return SemanticValue(SemanticValueKind.INTEGER, value)
    if isinstance(value, str):
        if not value:
            _fail(EvidencePublicationFailureCode.MISSING_SEMANTIC_CONTENT,
                  "empty strings cannot be published as semantic values")
        return SemanticValue(SemanticValueKind.STRING, value)
    if isinstance(value, list):
        return SemanticValue(SemanticValueKind.ARRAY,
                             items=tuple(_semantic_value(item) for item in value))
    if isinstance(value, Mapping):
        return SemanticValue(
            SemanticValueKind.OBJECT,
            fields=tuple(sorted((SemanticField(str(key), _semantic_value(child))
                                 for key, child in value.items()),
                                key=lambda item: item.name)))
    _fail(EvidencePublicationFailureCode.MISSING_SEMANTIC_CONTENT,
          f"unsupported Evidence semantic value: {type(value).__name__}")


def _semantic_fields(value: EvidenceObject) -> tuple[SemanticField, ...]:
    semantics = value.to_dict().get("semantics")
    if not isinstance(semantics, Mapping) or not semantics:
        _fail(EvidencePublicationFailureCode.MISSING_SEMANTIC_CONTENT,
              f"Evidence object {value.object_id} has no semantic content")
    return tuple(sorted((SemanticField(str(name), _semantic_value(child))
                         for name, child in semantics.items()),
                        key=lambda item: item.name))


_RELATIONSHIP_KIND = {
    EvidenceRelationshipKind.ATTRIBUTABLE_SOURCE: RelationshipKind.PROVENANCE,
    EvidenceRelationshipKind.ARTIFACT_OCCURRENCE: RelationshipKind.PROVENANCE,
    EvidenceRelationshipKind.EXTRACT_OCCURRENCE: RelationshipKind.PROVENANCE,
    EvidenceRelationshipKind.EXTRACT_ARTIFACT: RelationshipKind.EVIDENCE_SUPPORT,
    EvidenceRelationshipKind.TRANSLATION: RelationshipKind.RELATED,
    EvidenceRelationshipKind.EQUIVALENT: RelationshipKind.RELATED,
    EvidenceRelationshipKind.SUPERSEDES: RelationshipKind.SUPERSESSION,
    EvidenceRelationshipKind.LINEAGE: RelationshipKind.RELATED,
}


def _published_role(value: EvidenceRelationship) -> str:
    return f"{value.kind.value.lower()}:{value.role}"


def _relationship_logical(values: Iterable[EvidenceRelationship]) -> tuple[dict, ...]:
    return tuple({
        "source_class": item.source_class,
        "source_id": item.source_id,
        "evidence_kind": item.kind,
        "evidence_role": item.role,
        "ordinal": item.ordinal,
        "target_class": item.target_class,
        "target_id": item.target_id,
        "governed_kind": _RELATIONSHIP_KIND[item.kind],
        "governed_role": _published_role(item),
    } for item in values)


def _placeholder(snapshot_id: str, object_class: EvidenceObjectClass,
                 object_id: str) -> GovernedObjectReference:
    return GovernedObjectReference(
        OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION,
        snapshot_id, _ZERO_DIGEST, object_class.value, object_id, _ZERO_DIGEST)


@dataclass(frozen=True, slots=True, order=True)
class EvidencePublicationManifestObject:
    object_class: str
    object_id: str
    source_object_digest: str
    published_object_digest: str


@dataclass(frozen=True, slots=True)
class EvidencePublicationRelationshipManifest:
    source_class: EvidenceObjectClass
    source_id: str
    evidence_kind: EvidenceRelationshipKind
    evidence_role: str
    ordinal: int
    target_class: EvidenceObjectClass
    target_id: str
    governed_kind: RelationshipKind
    governed_role: str
    target_reference: GovernedObjectReference

    @property
    def order_key(self):
        return (_CLASS_ORDER[self.source_class], self.source_id,
                self.evidence_kind.value, self.evidence_role, self.ordinal,
                _CLASS_ORDER[self.target_class], self.target_id)


@dataclass(frozen=True, slots=True)
class EvidencePublicationManifest:
    owner_domain: str
    owner_contract: str
    contract_version: str
    source_contract_version: str
    source_snapshot_version: str
    source_snapshot_id: str
    source_snapshot_digest: str
    object_manifest_digest: str
    relationship_manifest_digest: str
    snapshot_id: str
    snapshot_digest: str
    objects: tuple[EvidencePublicationManifestObject, ...]
    relationships: tuple[EvidencePublicationRelationshipManifest, ...]
    manifest_digest: str

    def to_dict(self) -> dict:
        return _canonical(self)

    def to_json(self) -> str:
        return canonical_publication_json(self)


@dataclass(frozen=True, slots=True)
class EvidencePublication:
    publication_id: str
    publication_digest: str
    source_snapshot_id: str
    source_snapshot_digest: str
    snapshot: GovernedSnapshot
    manifest: EvidencePublicationManifest
    references: tuple[GovernedObjectReference, ...]

    def __post_init__(self) -> None:
        validate_evidence_publication(self)

    def to_dict(self) -> dict:
        return _canonical(self)

    def to_json(self) -> str:
        return canonical_publication_json(self)


def _source_relationships(snapshot: EvidenceSnapshot) -> tuple[EvidenceRelationship, ...]:
    return snapshot.manifest.relationships


def _logical_manifest(snapshot: EvidenceSnapshot) -> tuple[dict, ...]:
    by_source: dict[tuple[EvidenceObjectClass, str], list[EvidenceRelationship]] = {}
    for relationship in _source_relationships(snapshot):
        by_source.setdefault((relationship.source_class, relationship.source_id), []).append(relationship)
    return tuple({
        "object_class": item.object_class.value,
        "object_id": item.object_id,
        "source_object_digest": item.object_digest,
        "semantic_fields": _semantic_fields(item),
        "relationships": tuple({
            "evidence_kind": relationship.kind,
            "evidence_role": relationship.role,
            "ordinal": relationship.ordinal,
            "target_class": relationship.target_class,
            "target_id": relationship.target_id,
            "governed_kind": _RELATIONSHIP_KIND[relationship.kind],
            "governed_role": _published_role(relationship),
        } for relationship in by_source.get((item.object_class, item.object_id), ())),
    } for item in snapshot.objects)


def _build_governed_objects(snapshot: EvidenceSnapshot,
                            snapshot_id: str) -> tuple[GovernedObject, ...]:
    relationships: dict[tuple[EvidenceObjectClass, str], list[GovernedRelationship]] = {}
    for item in _source_relationships(snapshot):
        relationships.setdefault((item.source_class, item.source_id), []).append(
            GovernedRelationship(
                _RELATIONSHIP_KIND[item.kind], _published_role(item),
                _placeholder(snapshot_id, item.target_class, item.target_id),
                item.ordinal))
    return tuple(create_governed_object(
        owner_domain=OWNER_DOMAIN,
        owner_contract=OWNER_CONTRACT,
        contract_version=PUBLICATION_CONTRACT_VERSION,
        object_class=item.object_class.value,
        object_id=item.object_id,
        authority=AuthorityClass.EVIDENCE,
        semantic_fields=_semantic_fields(item),
        relationships=relationships.get((item.object_class, item.object_id), ()),
    ) for item in snapshot.objects)


def _manifest_payload(*, source: EvidenceSnapshot,
                      object_manifest_digest: str,
                      relationship_manifest_digest: str,
                      snapshot: GovernedSnapshot,
                      objects: tuple[EvidencePublicationManifestObject, ...],
                      relationships: tuple[EvidencePublicationRelationshipManifest, ...]):
    return {
        "owner_domain": OWNER_DOMAIN,
        "owner_contract": OWNER_CONTRACT,
        "contract_version": PUBLICATION_CONTRACT_VERSION,
        "source_contract_version": EVIDENCE_CONTRACT_VERSION,
        "source_snapshot_version": EVIDENCE_SNAPSHOT_VERSION,
        "source_snapshot_id": source.snapshot_id,
        "source_snapshot_digest": source.snapshot_digest,
        "object_manifest_digest": object_manifest_digest,
        "relationship_manifest_digest": relationship_manifest_digest,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_digest": snapshot.snapshot_digest,
        "objects": objects,
        "relationships": relationships,
    }


def _publication_payload(*, publication_id: str, source_snapshot_id: str,
                         source_snapshot_digest: str, snapshot: GovernedSnapshot,
                         manifest: EvidencePublicationManifest,
                         references: tuple[GovernedObjectReference, ...]):
    return {
        "publication_id": publication_id,
        "source_snapshot_id": source_snapshot_id,
        "source_snapshot_digest": source_snapshot_digest,
        "snapshot": snapshot,
        "manifest": manifest,
        "references": references,
    }


def publish_evidence(source: EvidenceSnapshot) -> EvidencePublication:
    """Faithfully publish one validated immutable Evidence owner snapshot."""
    if not isinstance(source, EvidenceSnapshot):
        _fail(EvidencePublicationFailureCode.INVALID_SOURCE,
              "publication requires an EvidenceSnapshot")
    try:
        validate_evidence_snapshot(source)
    except EvidenceValidationError as exc:
        _fail(EvidencePublicationFailureCode.INVALID_SOURCE,
              f"Evidence snapshot is invalid: {exc.code.value}")
    if (source.contract_version != EVIDENCE_CONTRACT_VERSION
            or source.snapshot_version != EVIDENCE_SNAPSHOT_VERSION):
        _fail(EvidencePublicationFailureCode.UNSUPPORTED_VERSION,
              "Evidence source snapshot version is unsupported")

    before = canonical_evidence_json(source)
    logical = _logical_manifest(source)
    object_manifest_digest = _sha(logical)
    relationship_logical = _relationship_logical(_source_relationships(source))
    relationship_manifest_digest = _sha(relationship_logical)
    snapshot_id = "evidence-publication-" + _sha({
        "owner_domain": OWNER_DOMAIN,
        "owner_contract": OWNER_CONTRACT,
        "contract_version": PUBLICATION_CONTRACT_VERSION,
        "source_snapshot_id": source.snapshot_id,
        "source_snapshot_digest": source.snapshot_digest,
        "object_manifest_digest": object_manifest_digest,
        "relationship_manifest_digest": relationship_manifest_digest,
    })
    try:
        objects = _build_governed_objects(source, snapshot_id)
        snapshot = create_governed_snapshot(
            owner_domain=OWNER_DOMAIN,
            owner_contract=OWNER_CONTRACT,
            contract_version=PUBLICATION_CONTRACT_VERSION,
            snapshot_id=snapshot_id,
            objects=objects)
        references = tuple(reference_to(snapshot, item.object_class, item.object_id)
                           for item in snapshot.objects)
    except GovernedResolutionError as exc:
        _fail(EvidencePublicationFailureCode.INVALID_PUBLICATION,
              f"governed Evidence projection is invalid: {exc.code.value}")

    source_digests = {(item.object_class.value, item.object_id): item.object_digest
                      for item in source.objects}
    manifest_objects = tuple(EvidencePublicationManifestObject(
        item.object_class, item.object_id,
        source_digests[(item.object_class, item.object_id)], item.object_digest)
        for item in snapshot.objects)
    source_relationships = _source_relationships(source)
    governed_relationships = {
        (item.object_class, item.object_id, relationship.kind,
         relationship.role, relationship.ordinal,
         relationship.target.object_class, relationship.target.object_id): relationship.target
        for item in snapshot.objects for relationship in item.relationships
    }
    manifest_relationships = tuple(sorted((
        EvidencePublicationRelationshipManifest(
            item.source_class, item.source_id, item.kind, item.role, item.ordinal,
            item.target_class, item.target_id, _RELATIONSHIP_KIND[item.kind],
            _published_role(item),
            governed_relationships[(
                item.source_class.value, item.source_id,
                _RELATIONSHIP_KIND[item.kind], _published_role(item), item.ordinal,
                item.target_class.value, item.target_id)])
        for item in source_relationships), key=lambda item: item.order_key))
    manifest_without_digest = _manifest_payload(
        source=source, object_manifest_digest=object_manifest_digest,
        relationship_manifest_digest=relationship_manifest_digest,
        snapshot=snapshot, objects=manifest_objects,
        relationships=manifest_relationships)
    manifest_digest = _sha(manifest_without_digest)
    manifest = EvidencePublicationManifest(
        OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION,
        EVIDENCE_CONTRACT_VERSION, EVIDENCE_SNAPSHOT_VERSION,
        source.snapshot_id, source.snapshot_digest,
        object_manifest_digest, relationship_manifest_digest,
        snapshot.snapshot_id, snapshot.snapshot_digest,
        manifest_objects, manifest_relationships, manifest_digest)
    publication_id = "evidence-publication-record-" + _sha({
        "source_snapshot_id": source.snapshot_id,
        "source_snapshot_digest": source.snapshot_digest,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_digest": snapshot.snapshot_digest,
        "manifest_digest": manifest.manifest_digest,
    })
    publication_digest = _sha(_publication_payload(
        publication_id=publication_id,
        source_snapshot_id=source.snapshot_id,
        source_snapshot_digest=source.snapshot_digest,
        snapshot=snapshot, manifest=manifest, references=references))
    publication = EvidencePublication(
        publication_id, publication_digest, source.snapshot_id,
        source.snapshot_digest, snapshot, manifest, references)
    if canonical_evidence_json(source) != before:
        _fail(EvidencePublicationFailureCode.INVALID_SOURCE,
              "Evidence publication mutated its source snapshot")
    return publication


def validate_evidence_publication(publication: EvidencePublication) -> EvidencePublication:
    if not isinstance(publication, EvidencePublication):
        _fail(EvidencePublicationFailureCode.INVALID_PUBLICATION,
              "EvidencePublication is required")
    snapshot, manifest = publication.snapshot, publication.manifest
    if not isinstance(snapshot, GovernedSnapshot) or not isinstance(manifest, EvidencePublicationManifest):
        _fail(EvidencePublicationFailureCode.INVALID_PUBLICATION,
              "publication snapshot or manifest is invalid")
    expected_owner = (OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION)
    if ((snapshot.owner_domain, snapshot.owner_contract, snapshot.contract_version) != expected_owner
            or (manifest.owner_domain, manifest.owner_contract, manifest.contract_version) != expected_owner):
        _fail(EvidencePublicationFailureCode.UNSUPPORTED_VERSION,
              "Evidence publication owner or version binding is invalid")
    if (manifest.source_contract_version != EVIDENCE_CONTRACT_VERSION
            or manifest.source_snapshot_version != EVIDENCE_SNAPSHOT_VERSION):
        _fail(EvidencePublicationFailureCode.UNSUPPORTED_VERSION,
              "Evidence source contract binding is unsupported")
    for value, name in ((publication.source_snapshot_digest, "source_snapshot_digest"),
                        (publication.publication_digest, "publication_digest"),
                        (manifest.source_snapshot_digest, "manifest source_snapshot_digest"),
                        (manifest.object_manifest_digest, "object_manifest_digest"),
                        (manifest.relationship_manifest_digest, "relationship_manifest_digest"),
                        (manifest.snapshot_digest, "manifest snapshot_digest"),
                        (manifest.manifest_digest, "manifest_digest")):
        _digest(value, name)
    for value, name in ((publication.publication_id, "publication_id"),
                        (publication.source_snapshot_id, "source_snapshot_id"),
                        (manifest.source_snapshot_id, "manifest source_snapshot_id"),
                        (manifest.snapshot_id, "manifest snapshot_id")):
        _identifier(value, name)
    if ((publication.source_snapshot_id, publication.source_snapshot_digest)
            != (manifest.source_snapshot_id, manifest.source_snapshot_digest)):
        _fail(EvidencePublicationFailureCode.DIGEST_MISMATCH,
              "publication and manifest source bindings differ")
    if (snapshot.snapshot_id, snapshot.snapshot_digest) != (manifest.snapshot_id, manifest.snapshot_digest):
        _fail(EvidencePublicationFailureCode.DIGEST_MISMATCH,
              "publication snapshot and manifest differ")
    expected_objects = tuple(EvidencePublicationManifestObject(
        item.object_class, item.object_id, source.source_object_digest,
        item.object_digest)
        for item, source in zip(snapshot.objects, manifest.objects))
    if len(snapshot.objects) != len(manifest.objects) or expected_objects != manifest.objects:
        _fail(EvidencePublicationFailureCode.INVALID_PUBLICATION,
              "object manifest does not exactly cover the publication snapshot")
    expected_references = tuple(reference_to(snapshot, item.object_class, item.object_id)
                                for item in snapshot.objects)
    if publication.references != expected_references or len(set(publication.references)) != len(publication.references):
        _fail(EvidencePublicationFailureCode.DUPLICATE_IDENTITY,
              "governed references are incomplete, duplicated, or unordered")
    relationship_edges = tuple(sorted((
        (item.object_class, item.object_id, rel.kind, rel.role, rel.ordinal,
         rel.target.object_class, rel.target.object_id, rel.target)
        for item in snapshot.objects for rel in item.relationships),
        key=lambda value: tuple(str(item) for item in value[:-1])))
    declared_edges = tuple(sorted((
        (item.source_class.value, item.source_id, item.governed_kind,
         item.governed_role, item.ordinal, item.target_class.value,
         item.target_id, item.target_reference)
        for item in manifest.relationships),
        key=lambda value: tuple(str(item) for item in value[:-1])))
    if relationship_edges != declared_edges:
        _fail(EvidencePublicationFailureCode.BROKEN_RELATIONSHIP,
              "relationship manifest does not exactly cover governed relationships")
    expected_relationship_digest = _sha(tuple({
        "source_class": item.source_class,
        "source_id": item.source_id,
        "evidence_kind": item.evidence_kind,
        "evidence_role": item.evidence_role,
        "ordinal": item.ordinal,
        "target_class": item.target_class,
        "target_id": item.target_id,
        "governed_kind": item.governed_kind,
        "governed_role": item.governed_role,
    } for item in manifest.relationships))
    if manifest.relationship_manifest_digest != expected_relationship_digest:
        _fail(EvidencePublicationFailureCode.DIGEST_MISMATCH,
              "relationship manifest digest is invalid")
    manifest_payload = _manifest_payload(
        source=type("SourceBinding", (), {
            "snapshot_id": manifest.source_snapshot_id,
            "snapshot_digest": manifest.source_snapshot_digest})(),
        object_manifest_digest=manifest.object_manifest_digest,
        relationship_manifest_digest=manifest.relationship_manifest_digest,
        snapshot=snapshot, objects=manifest.objects,
        relationships=manifest.relationships)
    if manifest.manifest_digest != _sha(manifest_payload):
        _fail(EvidencePublicationFailureCode.DIGEST_MISMATCH,
              "publication manifest digest is invalid")
    expected_id = "evidence-publication-record-" + _sha({
        "source_snapshot_id": publication.source_snapshot_id,
        "source_snapshot_digest": publication.source_snapshot_digest,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_digest": snapshot.snapshot_digest,
        "manifest_digest": manifest.manifest_digest,
    })
    if publication.publication_id != expected_id:
        _fail(EvidencePublicationFailureCode.DIGEST_MISMATCH,
              "publication identity is invalid")
    expected_digest = _sha(_publication_payload(
        publication_id=publication.publication_id,
        source_snapshot_id=publication.source_snapshot_id,
        source_snapshot_digest=publication.source_snapshot_digest,
        snapshot=snapshot, manifest=manifest, references=publication.references))
    if publication.publication_digest != expected_digest:
        _fail(EvidencePublicationFailureCode.DIGEST_MISMATCH,
              "publication digest is invalid")
    return publication


__all__ = [
    "EvidencePublication", "EvidencePublicationError",
    "EvidencePublicationFailureCode", "EvidencePublicationManifest",
    "EvidencePublicationManifestObject",
    "EvidencePublicationRelationshipManifest", "OWNER_CONTRACT",
    "OWNER_DOMAIN", "PUBLICATION_CONTRACT_VERSION",
    "canonical_publication_json", "publish_evidence",
    "validate_evidence_publication",
]
