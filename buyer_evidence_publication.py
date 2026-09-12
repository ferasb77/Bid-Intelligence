"""Immutable owner publication for validated Buyer Evidence.

Publishes exactly what buyer_evidence.py already governs -- sources,
documents, citations, and extracts -- as immutable governed objects,
deriving relationships from the same foreign-key fields BuyerEvidenceSet's
own __post_init__ already validated. It performs no acquisition, no
authenticity reassessment, and no interpretation.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import date
from enum import Enum
from hashlib import sha256
import json
from typing import Mapping

from buyer_evidence import BUYER_EVIDENCE_VERSION, BuyerEvidenceSet
from governed_reference_resolution import (
    AuthorityClass, GovernedObjectReference, GovernedRelationship,
    GovernedResolutionError, GovernedSnapshot, RelationshipKind, SemanticField,
    SemanticValue, SemanticValueKind, create_governed_object,
    create_governed_snapshot, reference_to,
)

OWNER_DOMAIN = "buyer-evidence"
OWNER_CONTRACT = "buyer-evidence"
PUBLICATION_CONTRACT_VERSION = "1.0.0"
SOURCE_CLASS = "SOURCE"
DOCUMENT_CLASS = "DOCUMENT"
CITATION_CLASS = "CITATION"
EXTRACT_CLASS = "EXTRACT"
_ZERO_DIGEST = "0" * 64


class BuyerEvidencePublicationFailureCode(str, Enum):
    INVALID_SOURCE = "INVALID_SOURCE"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    DUPLICATE_IDENTITY = "DUPLICATE_IDENTITY"
    MISSING_SEMANTIC_CONTENT = "MISSING_SEMANTIC_CONTENT"
    BROKEN_RELATIONSHIP = "BROKEN_RELATIONSHIP"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    INVALID_PUBLICATION = "INVALID_PUBLICATION"


class BuyerEvidencePublicationError(ValueError):
    """Controlled fail-closed Buyer Evidence publication failure."""

    def __init__(self, code: BuyerEvidencePublicationFailureCode, message: str) -> None:
        self.code = code
        super().__init__(message)


def _fail(code: BuyerEvidencePublicationFailureCode, message: str):
    raise BuyerEvidencePublicationError(code, message)


def _canonical(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value):
        return {item.name: _canonical(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _canonical(value[key]) for key in sorted(value)}
    return value


def _json(value) -> str:
    try:
        return json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        _fail(BuyerEvidencePublicationFailureCode.MISSING_SEMANTIC_CONTENT,
              f"buyer evidence semantic content is not serializable: {exc}")


def _sha(value) -> str:
    return sha256(_json(value).encode("utf-8")).hexdigest()


def _semantic_value(value) -> SemanticValue:
    if isinstance(value, Enum):
        return SemanticValue(SemanticValueKind.ENUM, value.value)
    if isinstance(value, date):
        return SemanticValue(SemanticValueKind.DATE, value.isoformat())
    if value is None:
        return SemanticValue(SemanticValueKind.NULL)
    if type(value) is bool:
        return SemanticValue(SemanticValueKind.BOOLEAN, value)
    if type(value) is int:
        return SemanticValue(SemanticValueKind.INTEGER, value)
    if isinstance(value, str):
        if not value:
            return SemanticValue(SemanticValueKind.NULL)
        return SemanticValue(SemanticValueKind.STRING, value)
    if is_dataclass(value):
        semantic_fields = tuple(sorted((
            SemanticField(item.name, _semantic_value(getattr(value, item.name)))
            for item in fields(value)), key=lambda item: item.name))
        return SemanticValue(SemanticValueKind.OBJECT, fields=semantic_fields)
    if isinstance(value, (tuple, list)):
        return SemanticValue(SemanticValueKind.ARRAY,
                             items=tuple(_semantic_value(item) for item in value))
    _fail(BuyerEvidencePublicationFailureCode.MISSING_SEMANTIC_CONTENT,
          f"unsupported buyer evidence semantic value type: {type(value).__name__}")


def _semantic_fields(item) -> tuple[SemanticField, ...]:
    values = {field.name: getattr(item, field.name) for field in fields(item)}
    if not values:
        _fail(BuyerEvidencePublicationFailureCode.MISSING_SEMANTIC_CONTENT,
              "published buyer evidence objects require semantic fields")
    return tuple(sorted((SemanticField(name, _semantic_value(value))
                         for name, value in values.items()), key=lambda item: item.name))


@dataclass(frozen=True, slots=True)
class BuyerEvidencePublicationManifestObject:
    object_class: str
    object_id: str
    object_digest: str


@dataclass(frozen=True, slots=True)
class BuyerEvidencePublicationManifestRelationship:
    source_class: str
    source_id: str
    kind: RelationshipKind
    role: str
    ordinal: int
    target: GovernedObjectReference

    @property
    def order_key(self):
        return (self.source_class, self.source_id, self.kind.value, self.role,
                self.ordinal, self.target.identity_key)


@dataclass(frozen=True, slots=True)
class BuyerEvidencePublicationManifest:
    owner_domain: str
    owner_contract: str
    contract_version: str
    source_contract_version: str
    evidence_set_id: str
    buyer_id: str
    object_manifest_digest: str
    snapshot_id: str
    snapshot_digest: str
    objects: tuple[BuyerEvidencePublicationManifestObject, ...]
    relationships: tuple[BuyerEvidencePublicationManifestRelationship, ...]


@dataclass(frozen=True, slots=True)
class BuyerEvidencePublication:
    publication_id: str
    evidence_set_id: str
    buyer_id: str
    source_contract_version: str
    snapshot: GovernedSnapshot
    manifest: BuyerEvidencePublicationManifest
    references: tuple[GovernedObjectReference, ...]

    def __post_init__(self) -> None:
        validate_buyer_evidence_publication(self)

    def to_dict(self) -> dict:
        return _canonical(self)

    def to_json(self) -> str:
        return _json(self)

    @property
    def digest(self) -> str:
        return _sha(self)


@dataclass(frozen=True, slots=True)
class _ObjectSpec:
    object_class: str
    object_id: str
    item: object
    relationships: tuple[GovernedRelationship, ...] = ()


def _placeholder(snapshot_id: str, object_class: str, object_id: str) -> GovernedObjectReference:
    return GovernedObjectReference(
        OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION,
        snapshot_id, _ZERO_DIGEST, object_class, object_id, _ZERO_DIGEST)


def _relationship(kind: RelationshipKind, role: str, ordinal: int,
                  snapshot_id: str, object_class: str, object_id: str) -> GovernedRelationship:
    return GovernedRelationship(kind, role, _placeholder(snapshot_id, object_class, object_id), ordinal)


def _build_specs(evidence: BuyerEvidenceSet, snapshot_id: str) -> tuple[_ObjectSpec, ...]:
    specs = []
    for source in evidence.sources:
        specs.append(_ObjectSpec(SOURCE_CLASS, source.source_id, source))
    for document in evidence.documents:
        relationships = (_relationship(RelationshipKind.PROVENANCE, "source", 0,
                                       snapshot_id, SOURCE_CLASS, document.source_id),)
        specs.append(_ObjectSpec(DOCUMENT_CLASS, document.document_id, document, relationships))
    for citation in evidence.citations:
        relationships = (_relationship(RelationshipKind.PROVENANCE, "document", 0,
                                       snapshot_id, DOCUMENT_CLASS, citation.document_id),)
        specs.append(_ObjectSpec(CITATION_CLASS, citation.citation_id, citation, relationships))
    for extract in evidence.extracts:
        relationships = [_relationship(RelationshipKind.EVIDENCE_SUPPORT, "document", 0,
                                       snapshot_id, DOCUMENT_CLASS, extract.document_id)]
        for ordinal, citation_id in enumerate(extract.citation_ids):
            relationships.append(_relationship(RelationshipKind.PROVENANCE, "citation", ordinal,
                                               snapshot_id, CITATION_CLASS, citation_id))
        specs.append(_ObjectSpec(EXTRACT_CLASS, extract.extract_id, extract, tuple(relationships)))
    return tuple(sorted(specs, key=lambda item: (item.object_class, item.object_id)))


def _logical_manifest(specs: tuple[_ObjectSpec, ...]) -> tuple[dict, ...]:
    def target(value: GovernedObjectReference) -> dict:
        return {"object_class": value.object_class, "object_id": value.object_id}

    return tuple({
        "object_class": spec.object_class, "object_id": spec.object_id,
        "semantic_fields": _semantic_fields(spec.item),
        "relationships": tuple({"kind": item.kind, "role": item.role, "ordinal": item.ordinal,
                                "target": target(item.target)} for item in spec.relationships),
    } for spec in specs)


def publish_buyer_evidence(evidence: BuyerEvidenceSet) -> BuyerEvidencePublication:
    """Publish one validated Buyer Evidence set without assembling a context."""
    if not isinstance(evidence, BuyerEvidenceSet) or evidence.contract_version != BUYER_EVIDENCE_VERSION:
        _fail(BuyerEvidencePublicationFailureCode.INVALID_SOURCE,
              "publication requires a supported BuyerEvidenceSet")
    before = evidence.to_json()

    provisional_specs = _build_specs(evidence, "buyer-evidence-publication-pending")
    object_manifest_digest = _sha(_logical_manifest(provisional_specs))
    snapshot_id = "buyer-evidence-publication-" + _sha({
        "owner_domain": OWNER_DOMAIN, "owner_contract": OWNER_CONTRACT,
        "contract_version": PUBLICATION_CONTRACT_VERSION,
        "evidence_set_id": evidence.evidence_set_id, "buyer_id": evidence.buyer_id,
        "object_manifest_digest": object_manifest_digest,
    })
    specs = _build_specs(evidence, snapshot_id)
    if _sha(_logical_manifest(specs)) != object_manifest_digest:
        _fail(BuyerEvidencePublicationFailureCode.DIGEST_MISMATCH,
              "buyer evidence object manifest changed during snapshot binding")
    try:
        objects = tuple(create_governed_object(
            owner_domain=OWNER_DOMAIN, owner_contract=OWNER_CONTRACT,
            contract_version=PUBLICATION_CONTRACT_VERSION,
            object_class=spec.object_class, object_id=spec.object_id,
            authority=AuthorityClass.EVIDENCE,
            semantic_fields=_semantic_fields(spec.item), relationships=spec.relationships,
        ) for spec in specs)
        snapshot = create_governed_snapshot(
            owner_domain=OWNER_DOMAIN, owner_contract=OWNER_CONTRACT,
            contract_version=PUBLICATION_CONTRACT_VERSION, snapshot_id=snapshot_id, objects=objects)
    except GovernedResolutionError as exc:
        _fail(BuyerEvidencePublicationFailureCode.INVALID_PUBLICATION,
              f"buyer evidence publication snapshot is invalid: {exc.code.value}")

    references = tuple(reference_to(snapshot, item.object_class, item.object_id) for item in snapshot.objects)
    manifest_objects = tuple(BuyerEvidencePublicationManifestObject(
        item.object_class, item.object_id, item.object_digest) for item in snapshot.objects)
    manifest_relationships = tuple(sorted((
        BuyerEvidencePublicationManifestRelationship(
            item.object_class, item.object_id, relationship.kind, relationship.role,
            relationship.ordinal, relationship.target)
        for item in snapshot.objects for relationship in item.relationships
    ), key=lambda item: item.order_key))
    manifest = BuyerEvidencePublicationManifest(
        OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION, BUYER_EVIDENCE_VERSION,
        evidence.evidence_set_id, evidence.buyer_id, object_manifest_digest,
        snapshot.snapshot_id, snapshot.snapshot_digest, manifest_objects, manifest_relationships)
    publication_id = "buyer-evidence-publication-record-" + _sha({
        "evidence_set_id": evidence.evidence_set_id, "buyer_id": evidence.buyer_id,
        "snapshot_id": snapshot.snapshot_id, "snapshot_digest": snapshot.snapshot_digest,
    })
    publication = BuyerEvidencePublication(
        publication_id, evidence.evidence_set_id, evidence.buyer_id, BUYER_EVIDENCE_VERSION,
        snapshot, manifest, references)
    if evidence.to_json() != before:
        _fail(BuyerEvidencePublicationFailureCode.INVALID_SOURCE,
              "buyer evidence publication mutated its source")
    return publication


def validate_buyer_evidence_publication(
        publication: BuyerEvidencePublication) -> BuyerEvidencePublication:
    if not isinstance(publication, BuyerEvidencePublication):
        _fail(BuyerEvidencePublicationFailureCode.INVALID_PUBLICATION,
              "BuyerEvidencePublication is required")
    manifest, snapshot = publication.manifest, publication.snapshot
    if not isinstance(manifest, BuyerEvidencePublicationManifest) or not isinstance(snapshot, GovernedSnapshot):
        _fail(BuyerEvidencePublicationFailureCode.INVALID_PUBLICATION,
              "buyer evidence publication manifest or snapshot is invalid")
    expected_owner = (OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION)
    if ((snapshot.owner_domain, snapshot.owner_contract, snapshot.contract_version) != expected_owner
            or (manifest.owner_domain, manifest.owner_contract, manifest.contract_version) != expected_owner):
        _fail(BuyerEvidencePublicationFailureCode.VERSION_MISMATCH,
              "buyer evidence publication owner binding is invalid")
    if (publication.source_contract_version != BUYER_EVIDENCE_VERSION
            or manifest.source_contract_version != BUYER_EVIDENCE_VERSION):
        _fail(BuyerEvidencePublicationFailureCode.VERSION_MISMATCH,
              "buyer evidence source contract binding is invalid")
    if (publication.evidence_set_id, publication.buyer_id) != (manifest.evidence_set_id, manifest.buyer_id):
        _fail(BuyerEvidencePublicationFailureCode.INVALID_PUBLICATION,
              "buyer evidence publication envelope and manifest differ")
    if (snapshot.snapshot_id, snapshot.snapshot_digest) != (manifest.snapshot_id, manifest.snapshot_digest):
        _fail(BuyerEvidencePublicationFailureCode.DIGEST_MISMATCH,
              "buyer evidence snapshot and manifest differ")
    expected_objects = tuple(BuyerEvidencePublicationManifestObject(
        item.object_class, item.object_id, item.object_digest) for item in snapshot.objects)
    if manifest.objects != expected_objects:
        _fail(BuyerEvidencePublicationFailureCode.DIGEST_MISMATCH,
              "buyer evidence object manifest differs from its snapshot")
    allowed = {SOURCE_CLASS, DOCUMENT_CLASS, CITATION_CLASS, EXTRACT_CLASS}
    if any(item.object_class not in allowed for item in snapshot.objects):
        _fail(BuyerEvidencePublicationFailureCode.INVALID_PUBLICATION,
              "buyer evidence snapshot contains a foreign object class")
    expected_relationships = tuple(sorted((
        BuyerEvidencePublicationManifestRelationship(
            item.object_class, item.object_id, relationship.kind, relationship.role,
            relationship.ordinal, relationship.target)
        for item in snapshot.objects for relationship in item.relationships
    ), key=lambda item: item.order_key))
    if manifest.relationships != expected_relationships:
        _fail(BuyerEvidencePublicationFailureCode.BROKEN_RELATIONSHIP,
              "buyer evidence relationship manifest differs from its snapshot")
    expected_references = tuple(reference_to(snapshot, item.object_class, item.object_id) for item in snapshot.objects)
    if not isinstance(publication.references, tuple) or publication.references != expected_references:
        _fail(BuyerEvidencePublicationFailureCode.DIGEST_MISMATCH,
              "buyer evidence references differ from the immutable snapshot")
    expected_publication_id = "buyer-evidence-publication-record-" + _sha({
        "evidence_set_id": publication.evidence_set_id, "buyer_id": publication.buyer_id,
        "snapshot_id": snapshot.snapshot_id, "snapshot_digest": snapshot.snapshot_digest,
    })
    if publication.publication_id != expected_publication_id:
        _fail(BuyerEvidencePublicationFailureCode.DIGEST_MISMATCH,
              "buyer evidence publication identity is invalid")
    object_keys = {(item.object_class, item.object_id) for item in snapshot.objects}
    for item in snapshot.objects:
        if not item.semantic_fields:
            _fail(BuyerEvidencePublicationFailureCode.MISSING_SEMANTIC_CONTENT,
                  f"buyer evidence object {item.object_id} has no semantic content")
        for relationship in item.relationships:
            target = relationship.target
            if target.owner_domain == OWNER_DOMAIN and (
                    target.owner_contract != OWNER_CONTRACT
                    or target.contract_version != PUBLICATION_CONTRACT_VERSION
                    or (target.object_class, target.object_id) not in object_keys):
                _fail(BuyerEvidencePublicationFailureCode.BROKEN_RELATIONSHIP,
                      f"buyer evidence relationship from {item.object_id} does not close")
    return publication


__all__ = [
    "CITATION_CLASS", "DOCUMENT_CLASS", "EXTRACT_CLASS", "OWNER_CONTRACT",
    "OWNER_DOMAIN", "PUBLICATION_CONTRACT_VERSION", "SOURCE_CLASS",
    "BuyerEvidencePublication", "BuyerEvidencePublicationError",
    "BuyerEvidencePublicationFailureCode", "BuyerEvidencePublicationManifest",
    "BuyerEvidencePublicationManifestObject",
    "BuyerEvidencePublicationManifestRelationship", "publish_buyer_evidence",
    "validate_buyer_evidence_publication",
]
