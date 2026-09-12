"""Immutable owner publication for the validated Canonical Buyer identity.

CanonicalBuyer is already a single, reconciled identity record -- unlike
Canonical Opportunity's six-family observation ledger, there is exactly one
object to publish, not several. Its evidence_ids are bound to real Buyer
Evidence Publication references; an id Buyer Evidence Publication cannot
resolve is refused, never guessed.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from hashlib import sha256
import json
from typing import Mapping

from buyer_domain import BUYER_DOMAIN_VERSION, CanonicalBuyer
from buyer_evidence_publication import BuyerEvidencePublication
from governed_reference_resolution import (
    AuthorityClass, GovernedObjectReference, GovernedRelationship,
    GovernedResolutionError, GovernedSnapshot, RelationshipKind, SemanticField,
    SemanticValue, SemanticValueKind, create_governed_object,
    create_governed_snapshot, reference_to,
)

OWNER_DOMAIN = "canonical-buyer"
OWNER_CONTRACT = "canonical-buyer"
PUBLICATION_CONTRACT_VERSION = "1.0.0"
IDENTITY_CLASS = "CANONICAL_BUYER_IDENTITY"
_ZERO_DIGEST = "0" * 64


class CanonicalBuyerPublicationFailureCode(str, Enum):
    INVALID_SOURCE = "INVALID_SOURCE"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    MISSING_SEMANTIC_CONTENT = "MISSING_SEMANTIC_CONTENT"
    MISSING_RELATIONSHIP_BINDING = "MISSING_RELATIONSHIP_BINDING"
    BROKEN_RELATIONSHIP = "BROKEN_RELATIONSHIP"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    INVALID_PUBLICATION = "INVALID_PUBLICATION"


class CanonicalBuyerPublicationError(ValueError):
    """Controlled fail-closed Canonical Buyer publication failure."""

    def __init__(self, code: CanonicalBuyerPublicationFailureCode, message: str) -> None:
        self.code = code
        super().__init__(message)


def _fail(code: CanonicalBuyerPublicationFailureCode, message: str):
    raise CanonicalBuyerPublicationError(code, message)


def _canonical(value):
    if isinstance(value, Enum):
        return value.value
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
        _fail(CanonicalBuyerPublicationFailureCode.MISSING_SEMANTIC_CONTENT,
              f"canonical buyer semantic content is not serializable: {exc}")


def _sha(value) -> str:
    return sha256(_json(value).encode("utf-8")).hexdigest()


def _semantic_value(value) -> SemanticValue:
    if isinstance(value, Enum):
        return SemanticValue(SemanticValueKind.ENUM, value.value)
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
    _fail(CanonicalBuyerPublicationFailureCode.MISSING_SEMANTIC_CONTENT,
          f"unsupported canonical buyer semantic value type: {type(value).__name__}")


def _semantic_fields(buyer: CanonicalBuyer) -> tuple[SemanticField, ...]:
    values = {field.name: getattr(buyer, field.name) for field in fields(buyer)}
    return tuple(sorted((SemanticField(name, _semantic_value(value))
                         for name, value in values.items()), key=lambda item: item.name))


@dataclass(frozen=True, slots=True)
class CanonicalBuyerPublicationManifest:
    owner_domain: str
    owner_contract: str
    contract_version: str
    source_contract_version: str
    buyer_id: str
    object_digest: str
    snapshot_id: str
    snapshot_digest: str


@dataclass(frozen=True, slots=True)
class CanonicalBuyerPublication:
    publication_id: str
    buyer_id: str
    source_contract_version: str
    snapshot: GovernedSnapshot
    manifest: CanonicalBuyerPublicationManifest
    references: tuple[GovernedObjectReference, ...]

    def __post_init__(self) -> None:
        validate_canonical_buyer_publication(self)

    def to_dict(self) -> dict:
        return _canonical(self)

    def to_json(self) -> str:
        return _json(self)

    @property
    def digest(self) -> str:
        return _sha(self)

    def reference_for_identity(self) -> GovernedObjectReference:
        matches = tuple(item for item in self.references if item.object_id == self.buyer_id)
        if len(matches) != 1:
            _fail(CanonicalBuyerPublicationFailureCode.BROKEN_RELATIONSHIP,
                  "canonical buyer identity reference is not uniquely available")
        return matches[0]


def _bind_evidence(buyer: CanonicalBuyer, evidence_publication: BuyerEvidencePublication,
                   snapshot_id: str) -> tuple[GovernedRelationship, ...]:
    reference_by_id = {item.object_id: item for item in evidence_publication.references}
    relationships = []
    for ordinal, evidence_id in enumerate(buyer.evidence_ids):
        reference = reference_by_id.get(evidence_id)
        if reference is None:
            _fail(CanonicalBuyerPublicationFailureCode.MISSING_RELATIONSHIP_BINDING,
                  f"buyer evidence id {evidence_id!r} does not resolve in the supplied "
                  "Buyer Evidence Publication; refusing to invent the reference")
        relationships.append(GovernedRelationship(
            RelationshipKind.EVIDENCE_SUPPORT, "source-evidence", reference, ordinal))
    return tuple(relationships)


def publish_canonical_buyer(
        buyer: CanonicalBuyer, *, evidence_publication: BuyerEvidencePublication,
        ) -> CanonicalBuyerPublication:
    """Publish one validated Canonical Buyer identity, bound to real Buyer Evidence."""
    if not isinstance(buyer, CanonicalBuyer) or buyer.contract_version != BUYER_DOMAIN_VERSION:
        _fail(CanonicalBuyerPublicationFailureCode.INVALID_SOURCE,
              "publication requires a supported CanonicalBuyer")
    if not isinstance(evidence_publication, BuyerEvidencePublication):
        _fail(CanonicalBuyerPublicationFailureCode.INVALID_SOURCE,
              "publication requires a validated BuyerEvidencePublication")
    if evidence_publication.buyer_id != buyer.buyer_id:
        _fail(CanonicalBuyerPublicationFailureCode.INVALID_SOURCE,
              "Buyer Evidence Publication does not belong to this buyer")
    before = buyer.to_json()

    provisional = _bind_evidence(buyer, evidence_publication, "canonical-buyer-publication-pending")
    provisional_object = create_governed_object(
        owner_domain=OWNER_DOMAIN, owner_contract=OWNER_CONTRACT,
        contract_version=PUBLICATION_CONTRACT_VERSION, object_class=IDENTITY_CLASS,
        object_id=buyer.buyer_id, authority=AuthorityClass.CANONICAL_FACT,
        semantic_fields=_semantic_fields(buyer), relationships=provisional)
    object_digest = provisional_object.object_digest
    snapshot_id = "canonical-buyer-publication-" + _sha({
        "owner_domain": OWNER_DOMAIN, "owner_contract": OWNER_CONTRACT,
        "contract_version": PUBLICATION_CONTRACT_VERSION, "buyer_id": buyer.buyer_id,
        "object_digest": object_digest,
    })
    relationships = _bind_evidence(buyer, evidence_publication, snapshot_id)
    try:
        identity_object = create_governed_object(
            owner_domain=OWNER_DOMAIN, owner_contract=OWNER_CONTRACT,
            contract_version=PUBLICATION_CONTRACT_VERSION, object_class=IDENTITY_CLASS,
            object_id=buyer.buyer_id, authority=AuthorityClass.CANONICAL_FACT,
            semantic_fields=_semantic_fields(buyer), relationships=relationships)
        if identity_object.object_digest != object_digest:
            _fail(CanonicalBuyerPublicationFailureCode.DIGEST_MISMATCH,
                  "canonical buyer object digest changed during snapshot binding")
        snapshot = create_governed_snapshot(
            owner_domain=OWNER_DOMAIN, owner_contract=OWNER_CONTRACT,
            contract_version=PUBLICATION_CONTRACT_VERSION, snapshot_id=snapshot_id,
            objects=(identity_object,))
    except GovernedResolutionError as exc:
        _fail(CanonicalBuyerPublicationFailureCode.INVALID_PUBLICATION,
              f"canonical buyer publication snapshot is invalid: {exc.code.value}")

    references = tuple(reference_to(snapshot, item.object_class, item.object_id) for item in snapshot.objects)
    manifest = CanonicalBuyerPublicationManifest(
        OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION, BUYER_DOMAIN_VERSION,
        buyer.buyer_id, object_digest, snapshot.snapshot_id, snapshot.snapshot_digest)
    publication_id = "canonical-buyer-publication-record-" + _sha({
        "buyer_id": buyer.buyer_id, "snapshot_id": snapshot.snapshot_id,
        "snapshot_digest": snapshot.snapshot_digest,
    })
    publication = CanonicalBuyerPublication(
        publication_id, buyer.buyer_id, BUYER_DOMAIN_VERSION, snapshot, manifest, references)
    if buyer.to_json() != before:
        _fail(CanonicalBuyerPublicationFailureCode.INVALID_SOURCE,
              "canonical buyer publication mutated its source")
    return publication


def validate_canonical_buyer_publication(
        publication: CanonicalBuyerPublication) -> CanonicalBuyerPublication:
    if not isinstance(publication, CanonicalBuyerPublication):
        _fail(CanonicalBuyerPublicationFailureCode.INVALID_PUBLICATION,
              "CanonicalBuyerPublication is required")
    manifest, snapshot = publication.manifest, publication.snapshot
    if not isinstance(manifest, CanonicalBuyerPublicationManifest) or not isinstance(snapshot, GovernedSnapshot):
        _fail(CanonicalBuyerPublicationFailureCode.INVALID_PUBLICATION,
              "canonical buyer publication manifest or snapshot is invalid")
    expected_owner = (OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION)
    if ((snapshot.owner_domain, snapshot.owner_contract, snapshot.contract_version) != expected_owner
            or (manifest.owner_domain, manifest.owner_contract, manifest.contract_version) != expected_owner):
        _fail(CanonicalBuyerPublicationFailureCode.VERSION_MISMATCH,
              "canonical buyer publication owner binding is invalid")
    if (publication.source_contract_version != BUYER_DOMAIN_VERSION
            or manifest.source_contract_version != BUYER_DOMAIN_VERSION):
        _fail(CanonicalBuyerPublicationFailureCode.VERSION_MISMATCH,
              "canonical buyer source contract binding is invalid")
    if publication.buyer_id != manifest.buyer_id:
        _fail(CanonicalBuyerPublicationFailureCode.INVALID_PUBLICATION,
              "canonical buyer publication envelope and manifest differ")
    if (snapshot.snapshot_id, snapshot.snapshot_digest) != (manifest.snapshot_id, manifest.snapshot_digest):
        _fail(CanonicalBuyerPublicationFailureCode.DIGEST_MISMATCH,
              "canonical buyer snapshot and manifest differ")
    if len(snapshot.objects) != 1 or snapshot.objects[0].object_class != IDENTITY_CLASS:
        _fail(CanonicalBuyerPublicationFailureCode.INVALID_PUBLICATION,
              "canonical buyer publication must contain exactly one identity object")
    if snapshot.objects[0].object_id != publication.buyer_id:
        _fail(CanonicalBuyerPublicationFailureCode.INVALID_PUBLICATION,
              "canonical buyer identity object id does not match the publication")
    if snapshot.objects[0].object_digest != manifest.object_digest:
        _fail(CanonicalBuyerPublicationFailureCode.DIGEST_MISMATCH,
              "canonical buyer object digest differs from its snapshot")
    expected_references = tuple(reference_to(snapshot, item.object_class, item.object_id) for item in snapshot.objects)
    if not isinstance(publication.references, tuple) or publication.references != expected_references:
        _fail(CanonicalBuyerPublicationFailureCode.DIGEST_MISMATCH,
              "canonical buyer references differ from the immutable snapshot")
    expected_publication_id = "canonical-buyer-publication-record-" + _sha({
        "buyer_id": publication.buyer_id, "snapshot_id": snapshot.snapshot_id,
        "snapshot_digest": snapshot.snapshot_digest,
    })
    if publication.publication_id != expected_publication_id:
        _fail(CanonicalBuyerPublicationFailureCode.DIGEST_MISMATCH,
              "canonical buyer publication identity is invalid")
    if not snapshot.objects[0].semantic_fields:
        _fail(CanonicalBuyerPublicationFailureCode.MISSING_SEMANTIC_CONTENT,
              "canonical buyer identity object has no semantic content")
    return publication


__all__ = [
    "IDENTITY_CLASS", "OWNER_CONTRACT", "OWNER_DOMAIN", "PUBLICATION_CONTRACT_VERSION",
    "CanonicalBuyerPublication", "CanonicalBuyerPublicationError",
    "CanonicalBuyerPublicationFailureCode", "CanonicalBuyerPublicationManifest",
    "publish_canonical_buyer", "validate_canonical_buyer_publication",
]
