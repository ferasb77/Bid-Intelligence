"""Deterministic, immutable cross-domain governed reference resolution.

This module verifies identity, ownership, versions, digests, semantic fields,
and relationship closure. It contains no domain logic, persistence, retrieval,
presentation, prompts, model calls, or authority to create semantic content.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, replace
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Iterable


REFERENCE_RESOLUTION_VERSION = "governed-reference-resolution/1.0.0"

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_FIELD = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
_DECIMAL = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$")


class ResolutionFailureCode(str, Enum):
    INVALID_CONTRACT = "INVALID_CONTRACT"
    MISSING_REFERENCE = "MISSING_REFERENCE"
    DUPLICATE_IDENTITY = "DUPLICATE_IDENTITY"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    OWNER_MISMATCH = "OWNER_MISMATCH"
    TYPE_MISMATCH = "TYPE_MISMATCH"
    AUTHORITY_MISMATCH = "AUTHORITY_MISMATCH"
    INCOMPATIBLE_CONTEXT = "INCOMPATIBLE_CONTEXT"
    STALE_CONTEXT = "STALE_CONTEXT"
    MISSING_SEMANTIC_VALUE = "MISSING_SEMANTIC_VALUE"
    INCOMPLETE_PROVENANCE = "INCOMPLETE_PROVENANCE"
    INCOMPLETE_RELATIONSHIP_CLOSURE = "INCOMPLETE_RELATIONSHIP_CLOSURE"


class GovernedResolutionError(ValueError):
    """A controlled fail-closed contract or resolution failure."""

    def __init__(self, code: ResolutionFailureCode, message: str) -> None:
        self.code = code
        super().__init__(message)


class AuthorityClass(str, Enum):
    EVIDENCE = "EVIDENCE"
    CANONICAL_FACT = "CANONICAL_FACT"
    COMPUTED_FACT = "COMPUTED_FACT"
    OBSERVATION = "OBSERVATION"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"
    ASSUMPTION = "ASSUMPTION"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"
    LIMITATION = "LIMITATION"
    MANAGEMENT_QUESTION = "MANAGEMENT_QUESTION"
    COMPLIANCE_FINDING = "COMPLIANCE_FINDING"
    COORDINATION_RECORD = "COORDINATION_RECORD"
    HUMAN_DECISION = "HUMAN_DECISION"


class SemanticValueKind(str, Enum):
    NULL = "NULL"
    STRING = "STRING"
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    DATETIME = "DATETIME"
    IDENTIFIER = "IDENTIFIER"
    ENUM = "ENUM"
    OBJECT = "OBJECT"
    ARRAY = "ARRAY"


class RelationshipKind(str, Enum):
    EVIDENCE_SUPPORT = "EVIDENCE_SUPPORT"
    PROVENANCE = "PROVENANCE"
    SUPPORT = "SUPPORT"
    CONTRADICTION = "CONTRADICTION"
    DEPENDENCY = "DEPENDENCY"
    SUPERSESSION = "SUPERSESSION"
    CONFLICT_MEMBER = "CONFLICT_MEMBER"
    RELATED = "RELATED"


def _fail(code: ResolutionFailureCode, message: str):
    raise GovernedResolutionError(code, message)


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        _fail(ResolutionFailureCode.INVALID_CONTRACT,
              f"{name} must be a non-empty string without surrounding whitespace")
    return value


def _identifier(value: str, name: str) -> str:
    _required(value, name)
    if not _ID.fullmatch(value):
        _fail(ResolutionFailureCode.INVALID_CONTRACT, f"{name} is not a stable identifier")
    return value


def _version(value: str, name: str) -> str:
    if not isinstance(value, str) or not _SEMVER.fullmatch(value):
        _fail(ResolutionFailureCode.INVALID_CONTRACT, f"{name} must use MAJOR.MINOR.PATCH")
    return value


def _digest(value: str, name: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        _fail(ResolutionFailureCode.INVALID_CONTRACT,
              f"{name} must be a lowercase SHA-256 digest")
    return value


def _field_name(value: str, name: str) -> str:
    if not isinstance(value, str) or not _FIELD.fullmatch(value):
        _fail(ResolutionFailureCode.INVALID_CONTRACT, f"{name} is not a semantic field name")
    return value


def _canonical(value):
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {item.name: _canonical(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value)}
    return value


def _json(value) -> str:
    return json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _sha(value) -> str:
    return sha256(_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SemanticValue:
    kind: SemanticValueKind
    scalar: str | int | bool | None = None
    fields: tuple[SemanticField, ...] = ()
    items: tuple[SemanticValue, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SemanticValueKind):
            _fail(ResolutionFailureCode.INVALID_CONTRACT, "semantic value kind is invalid")
        if not isinstance(self.fields, tuple) or any(
                not isinstance(item, SemanticField) for item in self.fields):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "semantic object fields must be an immutable tuple")
        if not isinstance(self.items, tuple) or any(
                not isinstance(item, SemanticValue) for item in self.items):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "semantic array items must be an immutable tuple")

        textual = {SemanticValueKind.STRING, SemanticValueKind.DATE,
                   SemanticValueKind.DATETIME, SemanticValueKind.IDENTIFIER,
                   SemanticValueKind.ENUM, SemanticValueKind.DECIMAL}
        if self.kind in textual:
            if not isinstance(self.scalar, str) or not self.scalar:
                _fail(ResolutionFailureCode.INVALID_CONTRACT,
                      f"{self.kind.value} semantic values require a non-empty string")
            if self.kind == SemanticValueKind.DECIMAL and not _DECIMAL.fullmatch(self.scalar):
                _fail(ResolutionFailureCode.INVALID_CONTRACT,
                      "DECIMAL values require canonical decimal text")
            if self.fields or self.items:
                _fail(ResolutionFailureCode.INVALID_CONTRACT,
                      "scalar semantic values cannot contain fields or items")
        elif self.kind == SemanticValueKind.INTEGER:
            if type(self.scalar) is not int or self.fields or self.items:
                _fail(ResolutionFailureCode.INVALID_CONTRACT,
                      "INTEGER semantic values require one integer scalar")
        elif self.kind == SemanticValueKind.BOOLEAN:
            if type(self.scalar) is not bool or self.fields or self.items:
                _fail(ResolutionFailureCode.INVALID_CONTRACT,
                      "BOOLEAN semantic values require one boolean scalar")
        elif self.kind == SemanticValueKind.NULL:
            if self.scalar is not None or self.fields or self.items:
                _fail(ResolutionFailureCode.INVALID_CONTRACT,
                      "NULL semantic values cannot carry content")
        elif self.kind == SemanticValueKind.OBJECT:
            if self.scalar is not None or self.items:
                _fail(ResolutionFailureCode.INVALID_CONTRACT,
                      "OBJECT semantic values contain fields only")
            names = tuple(item.name for item in self.fields)
            if len(names) != len(set(names)):
                _fail(ResolutionFailureCode.DUPLICATE_IDENTITY,
                      "semantic object contains duplicate field names")
            if self.fields != tuple(sorted(self.fields, key=lambda item: item.name)):
                _fail(ResolutionFailureCode.INVALID_CONTRACT,
                      "semantic object fields are not deterministically ordered")
        elif self.kind == SemanticValueKind.ARRAY:
            if self.scalar is not None or self.fields:
                _fail(ResolutionFailureCode.INVALID_CONTRACT,
                      "ARRAY semantic values contain items only")

    def to_dict(self) -> dict:
        return _canonical(self)


@dataclass(frozen=True, slots=True)
class SemanticField:
    name: str
    value: SemanticValue

    def __post_init__(self) -> None:
        _field_name(self.name, "semantic field name")
        if not isinstance(self.value, SemanticValue):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "semantic field value must be a SemanticValue")


@dataclass(frozen=True, slots=True)
class GovernedObjectReference:
    owner_domain: str
    owner_contract: str
    contract_version: str
    snapshot_id: str
    snapshot_digest: str
    object_class: str
    object_id: str
    object_digest: str

    def __post_init__(self) -> None:
        _identifier(self.owner_domain, "owner_domain")
        _identifier(self.owner_contract, "owner_contract")
        _version(self.contract_version, "contract_version")
        _identifier(self.snapshot_id, "snapshot_id")
        _digest(self.snapshot_digest, "snapshot_digest")
        _identifier(self.object_class, "object_class")
        _identifier(self.object_id, "object_id")
        _digest(self.object_digest, "object_digest")

    @property
    def identity_key(self) -> tuple[str, ...]:
        return (self.owner_domain, self.owner_contract, self.contract_version,
                self.snapshot_id, self.object_class, self.object_id)


@dataclass(frozen=True, slots=True)
class GovernedRelationship:
    kind: RelationshipKind
    role: str
    target: GovernedObjectReference
    ordinal: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.kind, RelationshipKind):
            _fail(ResolutionFailureCode.INVALID_CONTRACT, "relationship kind is invalid")
        _identifier(self.role, "relationship role")
        if not isinstance(self.target, GovernedObjectReference):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "relationship target must be a GovernedObjectReference")
        if type(self.ordinal) is not int or self.ordinal < 0:
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "relationship ordinal must be a non-negative integer")

    @property
    def order_key(self):
        return (self.kind.value, self.role, self.ordinal, self.target.identity_key)


def _object_payload(owner_domain: str, owner_contract: str, contract_version: str,
                    object_class: str, object_id: str, authority: AuthorityClass,
                    semantic_fields: tuple[SemanticField, ...],
                    relationships: tuple[GovernedRelationship, ...]):
    return {
        "owner_domain": owner_domain,
        "owner_contract": owner_contract,
        "contract_version": contract_version,
        "object_class": object_class,
        "object_id": object_id,
        "authority": authority,
        "semantic_fields": semantic_fields,
        "relationships": tuple({
            "kind": item.kind,
            "role": item.role,
            "ordinal": item.ordinal,
            "target": {
                "owner_domain": item.target.owner_domain,
                "owner_contract": item.target.owner_contract,
                "contract_version": item.target.contract_version,
                "snapshot_id": item.target.snapshot_id,
                "object_class": item.target.object_class,
                "object_id": item.target.object_id,
            },
        } for item in relationships),
    }


@dataclass(frozen=True, slots=True)
class GovernedObject:
    owner_domain: str
    owner_contract: str
    contract_version: str
    object_class: str
    object_id: str
    authority: AuthorityClass
    semantic_fields: tuple[SemanticField, ...]
    relationships: tuple[GovernedRelationship, ...]
    object_digest: str

    def __post_init__(self) -> None:
        _identifier(self.owner_domain, "owner_domain")
        _identifier(self.owner_contract, "owner_contract")
        _version(self.contract_version, "contract_version")
        _identifier(self.object_class, "object_class")
        _identifier(self.object_id, "object_id")
        if not isinstance(self.authority, AuthorityClass):
            _fail(ResolutionFailureCode.INVALID_CONTRACT, "authority is invalid")
        if not isinstance(self.semantic_fields, tuple) or any(
                not isinstance(item, SemanticField) for item in self.semantic_fields):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "semantic_fields must be an immutable tuple")
        names = tuple(item.name for item in self.semantic_fields)
        if len(names) != len(set(names)):
            _fail(ResolutionFailureCode.DUPLICATE_IDENTITY,
                  "governed object contains duplicate semantic fields")
        if self.semantic_fields != tuple(sorted(self.semantic_fields, key=lambda item: item.name)):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "semantic fields are not deterministically ordered")
        if not self.semantic_fields:
            _fail(ResolutionFailureCode.MISSING_SEMANTIC_VALUE,
                  "governed object must expose semantic content")
        if not isinstance(self.relationships, tuple) or any(
                not isinstance(item, GovernedRelationship) for item in self.relationships):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "relationships must be an immutable tuple")
        keys = tuple(item.order_key for item in self.relationships)
        if len(keys) != len(set(keys)):
            _fail(ResolutionFailureCode.DUPLICATE_IDENTITY,
                  "governed object contains duplicate relationships")
        if self.relationships != tuple(sorted(self.relationships,
                                               key=lambda item: item.order_key)):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "relationships are not deterministically ordered")
        _digest(self.object_digest, "object_digest")
        expected = _sha(_object_payload(
            self.owner_domain, self.owner_contract, self.contract_version,
            self.object_class, self.object_id, self.authority,
            self.semantic_fields, self.relationships))
        if self.object_digest != expected:
            _fail(ResolutionFailureCode.DIGEST_MISMATCH,
                  f"object digest mismatch for {self.object_id}")

    def field(self, name: str) -> SemanticValue:
        _field_name(name, "semantic field name")
        for item in self.semantic_fields:
            if item.name == name:
                return item.value
        _fail(ResolutionFailureCode.MISSING_SEMANTIC_VALUE,
              f"semantic field {name} is absent from {self.object_id}")

    def to_dict(self) -> dict:
        return _canonical(self)


def create_governed_object(*, owner_domain: str, owner_contract: str,
                           contract_version: str, object_class: str,
                           object_id: str, authority: AuthorityClass,
                           semantic_fields: Iterable[SemanticField],
                           relationships: Iterable[GovernedRelationship] = ()) -> GovernedObject:
    """Create a canonically ordered object and calculate its semantic digest."""
    semantic_input = tuple(semantic_fields)
    relationship_input = tuple(relationships)
    if any(not isinstance(item, SemanticField) for item in semantic_input):
        _fail(ResolutionFailureCode.INVALID_CONTRACT,
              "semantic_fields must contain SemanticField values")
    if any(not isinstance(item, GovernedRelationship) for item in relationship_input):
        _fail(ResolutionFailureCode.INVALID_CONTRACT,
              "relationships must contain GovernedRelationship values")
    semantic = tuple(sorted(semantic_input, key=lambda item: item.name))
    links = tuple(sorted(relationship_input, key=lambda item: item.order_key))
    digest = _sha(_object_payload(owner_domain, owner_contract, contract_version,
                                  object_class, object_id, authority, semantic, links))
    return GovernedObject(owner_domain, owner_contract, contract_version,
                          object_class, object_id, authority, semantic, links, digest)


def _snapshot_payload(owner_domain: str, owner_contract: str, contract_version: str,
                      snapshot_id: str, objects: tuple[GovernedObject, ...]):
    return {
        "owner_domain": owner_domain,
        "owner_contract": owner_contract,
        "contract_version": contract_version,
        "snapshot_id": snapshot_id,
        "objects": tuple({
            "object_class": item.object_class,
            "object_id": item.object_id,
            "object_digest": item.object_digest,
        } for item in objects),
    }


@dataclass(frozen=True, slots=True)
class GovernedSnapshot:
    owner_domain: str
    owner_contract: str
    contract_version: str
    snapshot_id: str
    objects: tuple[GovernedObject, ...]
    snapshot_digest: str

    def __post_init__(self) -> None:
        _identifier(self.owner_domain, "snapshot owner_domain")
        _identifier(self.owner_contract, "snapshot owner_contract")
        _version(self.contract_version, "snapshot contract_version")
        _identifier(self.snapshot_id, "snapshot_id")
        if not isinstance(self.objects, tuple) or any(
                not isinstance(item, GovernedObject) for item in self.objects):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "snapshot objects must be an immutable tuple")
        if any((item.owner_domain, item.owner_contract, item.contract_version) !=
               (self.owner_domain, self.owner_contract, self.contract_version)
               for item in self.objects):
            _fail(ResolutionFailureCode.OWNER_MISMATCH,
                  "snapshot contains an object owned by another contract")
        keys = tuple((item.object_class, item.object_id) for item in self.objects)
        if len(keys) != len(set(keys)):
            _fail(ResolutionFailureCode.DUPLICATE_IDENTITY,
                  "snapshot contains duplicate object identities")
        if self.objects != tuple(sorted(self.objects,
                                        key=lambda item: (item.object_class, item.object_id))):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "snapshot objects are not deterministically ordered")
        _digest(self.snapshot_digest, "snapshot_digest")
        expected = _sha(_snapshot_payload(
            self.owner_domain, self.owner_contract, self.contract_version,
            self.snapshot_id, self.objects))
        if self.snapshot_digest != expected:
            _fail(ResolutionFailureCode.DIGEST_MISMATCH,
                  f"snapshot digest mismatch for {self.snapshot_id}")
        object_by_key = {(item.object_class, item.object_id): item for item in self.objects}
        for item in self.objects:
            for relationship in item.relationships:
                target = relationship.target
                is_internal = (
                    target.owner_domain == self.owner_domain
                    and target.owner_contract == self.owner_contract
                    and target.contract_version == self.contract_version
                    and target.snapshot_id == self.snapshot_id)
                if not is_internal:
                    continue
                resolved = object_by_key.get((target.object_class, target.object_id))
                if resolved is None:
                    code = (ResolutionFailureCode.INCOMPLETE_PROVENANCE
                            if relationship.kind == RelationshipKind.PROVENANCE
                            else ResolutionFailureCode.INCOMPLETE_RELATIONSHIP_CLOSURE)
                    _fail(code, f"internal relationship from {item.object_id} does not close")
                if (target.snapshot_digest != self.snapshot_digest
                        or target.object_digest != resolved.object_digest):
                    _fail(ResolutionFailureCode.DIGEST_MISMATCH,
                          f"internal relationship binding mismatch for {target.object_id}")

    def to_dict(self) -> dict:
        return _canonical(self)


def create_governed_snapshot(*, owner_domain: str, owner_contract: str,
                             contract_version: str, snapshot_id: str,
                             objects: Iterable[GovernedObject]) -> GovernedSnapshot:
    """Create a canonically ordered immutable owner snapshot."""
    object_input = tuple(objects)
    if any(not isinstance(item, GovernedObject) for item in object_input):
        _fail(ResolutionFailureCode.INVALID_CONTRACT,
              "objects must contain GovernedObject values")
    ordered = tuple(sorted(object_input,
                           key=lambda item: (item.object_class, item.object_id)))
    digest = _sha(_snapshot_payload(owner_domain, owner_contract, contract_version,
                                    snapshot_id, ordered))
    object_by_key = {(item.object_class, item.object_id): item for item in ordered}
    normalized = []
    for item in ordered:
        relationships = []
        for relationship in item.relationships:
            target = relationship.target
            is_internal = (
                target.owner_domain == owner_domain
                and target.owner_contract == owner_contract
                and target.contract_version == contract_version
                and target.snapshot_id == snapshot_id)
            if is_internal:
                resolved = object_by_key.get((target.object_class, target.object_id))
                if resolved is None:
                    code = (ResolutionFailureCode.INCOMPLETE_PROVENANCE
                            if relationship.kind == RelationshipKind.PROVENANCE
                            else ResolutionFailureCode.INCOMPLETE_RELATIONSHIP_CLOSURE)
                    _fail(code, f"internal relationship from {item.object_id} does not close")
                target = replace(target, snapshot_digest=digest,
                                 object_digest=resolved.object_digest)
                relationship = replace(relationship, target=target)
            relationships.append(relationship)
        normalized.append(create_governed_object(
            owner_domain=item.owner_domain, owner_contract=item.owner_contract,
            contract_version=item.contract_version, object_class=item.object_class,
            object_id=item.object_id, authority=item.authority,
            semantic_fields=item.semantic_fields, relationships=tuple(relationships)))
    normalized_objects = tuple(sorted(normalized,
                                      key=lambda item: (item.object_class, item.object_id)))
    normalized_digest = _sha(_snapshot_payload(
        owner_domain, owner_contract, contract_version, snapshot_id, normalized_objects))
    if normalized_digest != digest:
        _fail(ResolutionFailureCode.DIGEST_MISMATCH,
              "internal reference normalization changed snapshot identity")
    return GovernedSnapshot(owner_domain, owner_contract, contract_version,
                            snapshot_id, normalized_objects, digest)


def reference_to(snapshot: GovernedSnapshot, object_class: str,
                 object_id: str) -> GovernedObjectReference:
    """Create an exact reference to an object already registered in a snapshot."""
    if not isinstance(snapshot, GovernedSnapshot):
        _fail(ResolutionFailureCode.INVALID_CONTRACT, "snapshot is invalid")
    matches = tuple(item for item in snapshot.objects
                    if item.object_class == object_class and item.object_id == object_id)
    if not matches:
        _fail(ResolutionFailureCode.MISSING_REFERENCE,
              f"object {object_id} is absent from snapshot {snapshot.snapshot_id}")
    if len(matches) != 1:
        _fail(ResolutionFailureCode.DUPLICATE_IDENTITY,
              f"object {object_id} is ambiguous")
    item = matches[0]
    return GovernedObjectReference(
        snapshot.owner_domain, snapshot.owner_contract, snapshot.contract_version,
        snapshot.snapshot_id, snapshot.snapshot_digest, object_class, object_id,
        item.object_digest)


def _context_payload(context_id: str, context_version: str,
                     snapshots: tuple[GovernedSnapshot, ...]):
    return {"context_id": context_id, "context_version": context_version,
            "snapshots": snapshots}


@dataclass(frozen=True, slots=True)
class ResolutionContext:
    context_id: str
    context_version: str
    snapshots: tuple[GovernedSnapshot, ...]
    context_digest: str

    def __post_init__(self) -> None:
        _identifier(self.context_id, "context_id")
        _version(self.context_version, "context_version")
        if not isinstance(self.snapshots, tuple) or any(
                not isinstance(item, GovernedSnapshot) for item in self.snapshots):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "context snapshots must be an immutable tuple")
        keys = tuple((item.owner_domain, item.owner_contract, item.snapshot_id)
                     for item in self.snapshots)
        if len(keys) != len(set(keys)):
            _fail(ResolutionFailureCode.DUPLICATE_IDENTITY,
                  "resolution context contains duplicate snapshot identities")
        if self.snapshots != tuple(sorted(
                self.snapshots,
                key=lambda item: (item.owner_domain, item.owner_contract,
                                  item.snapshot_id))):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "context snapshots are not deterministically ordered")
        _digest(self.context_digest, "context_digest")
        expected = _sha(_context_payload(self.context_id, self.context_version,
                                         self.snapshots))
        if self.context_digest != expected:
            _fail(ResolutionFailureCode.DIGEST_MISMATCH,
                  f"context digest mismatch for {self.context_id}")

    def to_dict(self) -> dict:
        return _canonical(self)

    def to_json(self) -> str:
        return _json(self)


def create_resolution_context(*, context_id: str, context_version: str,
                              snapshots: Iterable[GovernedSnapshot]) -> ResolutionContext:
    """Create a canonically ordered bounded immutable resolution context."""
    snapshot_input = tuple(snapshots)
    if any(not isinstance(item, GovernedSnapshot) for item in snapshot_input):
        _fail(ResolutionFailureCode.INVALID_CONTRACT,
              "snapshots must contain GovernedSnapshot values")
    ordered = tuple(sorted(snapshot_input,
                           key=lambda item: (item.owner_domain, item.owner_contract,
                                             item.snapshot_id)))
    digest = _sha(_context_payload(context_id, context_version, ordered))
    return ResolutionContext(context_id, context_version, ordered, digest)


@dataclass(frozen=True, slots=True)
class ResolutionRequest:
    reference: GovernedObjectReference
    context_id: str
    context_digest: str
    expected_authority: AuthorityClass
    required_semantic_fields: tuple[str, ...] = ()
    required_relationship_kinds: tuple[RelationshipKind, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.reference, GovernedObjectReference):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "reference must be a GovernedObjectReference")
        _identifier(self.context_id, "request context_id")
        _digest(self.context_digest, "request context_digest")
        if not isinstance(self.expected_authority, AuthorityClass):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "expected_authority is invalid")
        if not isinstance(self.required_semantic_fields, tuple) or any(
                not isinstance(item, str) for item in self.required_semantic_fields):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "required_semantic_fields must be an immutable tuple")
        normalized_fields = tuple(sorted(self.required_semantic_fields))
        if len(normalized_fields) != len(set(normalized_fields)):
            _fail(ResolutionFailureCode.DUPLICATE_IDENTITY,
                  "required semantic fields contain duplicates")
        for item in normalized_fields:
            _field_name(item, "required semantic field")
        if self.required_semantic_fields != normalized_fields:
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "required semantic fields are not deterministically ordered")
        if not isinstance(self.required_relationship_kinds, tuple) or any(
                not isinstance(item, RelationshipKind)
                for item in self.required_relationship_kinds):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "required relationship kinds must be an immutable tuple")
        ordered_kinds = tuple(sorted(self.required_relationship_kinds,
                                     key=lambda item: item.value))
        if len(ordered_kinds) != len(set(ordered_kinds)):
            _fail(ResolutionFailureCode.DUPLICATE_IDENTITY,
                  "required relationship kinds contain duplicates")
        if self.required_relationship_kinds != ordered_kinds:
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "required relationship kinds are not deterministically ordered")


@dataclass(frozen=True, slots=True)
class ResolvedRelationship:
    source: GovernedObjectReference
    kind: RelationshipKind
    role: str
    ordinal: int
    target: GovernedObjectReference

    def __post_init__(self) -> None:
        if not isinstance(self.source, GovernedObjectReference):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "resolved relationship source is invalid")
        if not isinstance(self.kind, RelationshipKind):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "resolved relationship kind is invalid")
        _identifier(self.role, "resolved relationship role")
        if type(self.ordinal) is not int or self.ordinal < 0:
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "resolved relationship ordinal is invalid")
        if not isinstance(self.target, GovernedObjectReference):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "resolved relationship target is invalid")

    @property
    def order_key(self):
        return (self.source.identity_key, self.kind.value, self.role,
                self.ordinal, self.target.identity_key)


@dataclass(frozen=True, slots=True)
class ResolvedObject:
    reference: GovernedObjectReference
    value: GovernedObject

    def __post_init__(self) -> None:
        if not isinstance(self.reference, GovernedObjectReference):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "resolved object reference is invalid")
        if not isinstance(self.value, GovernedObject):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "resolved object value is invalid")
        if not _object_matches_reference(self.value, self.reference):
            _fail(ResolutionFailureCode.OWNER_MISMATCH,
                  "resolved object does not match its reference")
        if self.value.object_digest != self.reference.object_digest:
            _fail(ResolutionFailureCode.DIGEST_MISMATCH,
                  "resolved object digest does not match its reference")

    @property
    def order_key(self):
        return self.reference.identity_key


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    protocol_version: str
    context_id: str
    context_digest: str
    root_reference: GovernedObjectReference
    objects: tuple[ResolvedObject, ...]
    relationships: tuple[ResolvedRelationship, ...]

    def __post_init__(self) -> None:
        if self.protocol_version != REFERENCE_RESOLUTION_VERSION:
            _fail(ResolutionFailureCode.VERSION_MISMATCH,
                  "unsupported resolution protocol version")
        _identifier(self.context_id, "result context_id")
        _digest(self.context_digest, "result context_digest")
        if not isinstance(self.root_reference, GovernedObjectReference):
            _fail(ResolutionFailureCode.INVALID_CONTRACT, "root reference is invalid")
        if not isinstance(self.objects, tuple) or any(
                not isinstance(item, ResolvedObject) for item in self.objects):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "resolved objects must be an immutable tuple")
        if self.objects != tuple(sorted(self.objects, key=lambda item: item.order_key)):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "resolved objects are not deterministically ordered")
        object_keys = tuple(item.reference.identity_key for item in self.objects)
        if len(object_keys) != len(set(object_keys)):
            _fail(ResolutionFailureCode.DUPLICATE_IDENTITY,
                  "resolved result contains duplicate objects")
        if not isinstance(self.relationships, tuple) or any(
                not isinstance(item, ResolvedRelationship) for item in self.relationships):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "resolved relationships must be an immutable tuple")
        if self.relationships != tuple(sorted(self.relationships,
                                              key=lambda item: item.order_key)):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "resolved relationships are not deterministically ordered")
        edge_keys = tuple(item.order_key for item in self.relationships)
        if len(edge_keys) != len(set(edge_keys)):
            _fail(ResolutionFailureCode.DUPLICATE_IDENTITY,
                  "resolved result contains duplicate relationships")
        if any(item.source.identity_key not in set(object_keys)
               or item.target.identity_key not in set(object_keys)
               for item in self.relationships):
            _fail(ResolutionFailureCode.INCOMPLETE_RELATIONSHIP_CLOSURE,
                  "resolved result contains a relationship outside its object closure")
        if self.root_reference.identity_key not in set(object_keys):
            _fail(ResolutionFailureCode.MISSING_REFERENCE,
                  "resolved result does not contain its root reference")

    @property
    def root(self) -> GovernedObject:
        for item in self.objects:
            if item.reference.identity_key == self.root_reference.identity_key:
                return item.value
        _fail(ResolutionFailureCode.MISSING_REFERENCE,
              "resolved result does not contain its root object")

    @property
    def digest(self) -> str:
        return _sha(self)

    def to_dict(self) -> dict:
        return _canonical(self)

    def to_json(self) -> str:
        return _json(self)

    def relationship_targets(self, source: GovernedObjectReference,
                             kind: RelationshipKind) -> tuple[GovernedObject, ...]:
        if not isinstance(source, GovernedObjectReference) or not isinstance(kind, RelationshipKind):
            _fail(ResolutionFailureCode.INVALID_CONTRACT,
                  "relationship navigation requires a governed reference and kind")
        targets = {item.target.identity_key for item in self.relationships
                   if item.source == source and item.kind == kind}
        return tuple(item.value for item in self.objects
                     if item.reference.identity_key in targets)


def _resolved_object_key(item: GovernedObject):
    return (item.owner_domain, item.owner_contract, item.contract_version,
            item.object_class, item.object_id)


def _object_matches_reference(item: GovernedObject,
                              reference: GovernedObjectReference) -> bool:
    return (_resolved_object_key(item) ==
            (reference.owner_domain, reference.owner_contract,
             reference.contract_version, reference.object_class, reference.object_id))


def _find_snapshot(reference: GovernedObjectReference,
                   context: ResolutionContext) -> GovernedSnapshot:
    exact_owner = tuple(item for item in context.snapshots
                        if item.snapshot_id == reference.snapshot_id
                        and item.owner_domain == reference.owner_domain
                        and item.owner_contract == reference.owner_contract)
    if not exact_owner:
        same_snapshot = tuple(item for item in context.snapshots
                              if item.snapshot_id == reference.snapshot_id)
        if same_snapshot:
            _fail(ResolutionFailureCode.OWNER_MISMATCH,
                  f"snapshot {reference.snapshot_id} belongs to another owner")
        _fail(ResolutionFailureCode.MISSING_REFERENCE,
              f"snapshot {reference.snapshot_id} is absent from the resolution context")
    snapshot = exact_owner[0]
    if snapshot.contract_version != reference.contract_version:
        _fail(ResolutionFailureCode.VERSION_MISMATCH,
              f"contract version mismatch for snapshot {reference.snapshot_id}")
    if snapshot.snapshot_digest != reference.snapshot_digest:
        _fail(ResolutionFailureCode.DIGEST_MISMATCH,
              f"snapshot digest mismatch for {reference.snapshot_id}")
    return snapshot


def _resolve_one(reference: GovernedObjectReference,
                 context: ResolutionContext) -> GovernedObject:
    snapshot = _find_snapshot(reference, context)
    same_id = tuple(item for item in snapshot.objects if item.object_id == reference.object_id)
    exact = tuple(item for item in same_id if item.object_class == reference.object_class)
    if not exact:
        if same_id:
            _fail(ResolutionFailureCode.TYPE_MISMATCH,
                  f"object class mismatch for {reference.object_id}")
        _fail(ResolutionFailureCode.MISSING_REFERENCE,
              f"object {reference.object_id} is absent from snapshot {reference.snapshot_id}")
    if len(exact) != 1:
        _fail(ResolutionFailureCode.DUPLICATE_IDENTITY,
              f"object {reference.object_id} is ambiguous")
    item = exact[0]
    if item.object_digest != reference.object_digest:
        _fail(ResolutionFailureCode.DIGEST_MISMATCH,
              f"object digest mismatch for {reference.object_id}")
    return item


def resolve_governed_reference(request: ResolutionRequest,
                               context: ResolutionContext) -> ResolutionResult:
    """Resolve one root and its complete declared relationship closure."""
    if not isinstance(request, ResolutionRequest) or not isinstance(context, ResolutionContext):
        _fail(ResolutionFailureCode.INVALID_CONTRACT,
              "resolution requires a ResolutionRequest and ResolutionContext")
    if request.context_id != context.context_id:
        _fail(ResolutionFailureCode.INCOMPATIBLE_CONTEXT,
              "request and resolution context identities differ")
    if request.context_digest != context.context_digest:
        _fail(ResolutionFailureCode.STALE_CONTEXT,
              "request is bound to a different resolution context digest")

    root = _resolve_one(request.reference, context)
    if root.authority != request.expected_authority:
        _fail(ResolutionFailureCode.AUTHORITY_MISMATCH,
              f"authority mismatch for {root.object_id}")
    available_fields = {item.name for item in root.semantic_fields}
    missing_fields = set(request.required_semantic_fields) - available_fields
    if missing_fields:
        _fail(ResolutionFailureCode.MISSING_SEMANTIC_VALUE,
              "required semantic fields are absent: " + ", ".join(sorted(missing_fields)))
    available_kinds = {item.kind for item in root.relationships}
    missing_kinds = set(request.required_relationship_kinds) - available_kinds
    if missing_kinds:
        code = (ResolutionFailureCode.INCOMPLETE_PROVENANCE
                if RelationshipKind.PROVENANCE in missing_kinds
                else ResolutionFailureCode.INCOMPLETE_RELATIONSHIP_CLOSURE)
        _fail(code, "required relationship kinds are absent: " +
              ", ".join(sorted(item.value for item in missing_kinds)))

    pending = [request.reference]
    visited: set[tuple[str, ...]] = set()
    resolved_objects: dict[tuple[str, ...], ResolvedObject] = {}
    resolved_edges: list[ResolvedRelationship] = []
    while pending:
        reference = pending.pop()
        item = _resolve_one(reference, context)
        if reference.identity_key in visited:
            continue
        visited.add(reference.identity_key)
        resolved_objects[reference.identity_key] = ResolvedObject(reference, item)
        for relationship in item.relationships:
            try:
                target_object = _resolve_one(relationship.target, context)
            except GovernedResolutionError as exc:
                code = (ResolutionFailureCode.INCOMPLETE_PROVENANCE
                        if relationship.kind == RelationshipKind.PROVENANCE
                        else ResolutionFailureCode.INCOMPLETE_RELATIONSHIP_CLOSURE)
                _fail(code, f"{relationship.kind.value} relationship from "
                      f"{item.object_id} does not close: {exc.code.value}")
            if (relationship.kind in {RelationshipKind.EVIDENCE_SUPPORT,
                                      RelationshipKind.PROVENANCE}
                    and target_object.authority != AuthorityClass.EVIDENCE):
                _fail(ResolutionFailureCode.AUTHORITY_MISMATCH,
                      f"{relationship.kind.value} target {target_object.object_id} "
                      "does not have evidence authority")
            source_reference = GovernedObjectReference(
                item.owner_domain, item.owner_contract, item.contract_version,
                reference.snapshot_id, reference.snapshot_digest,
                item.object_class, item.object_id, item.object_digest)
            resolved_edges.append(ResolvedRelationship(
                source_reference, relationship.kind, relationship.role,
                relationship.ordinal, relationship.target))
            pending.append(relationship.target)

    objects = tuple(sorted(resolved_objects.values(), key=lambda item: item.order_key))
    edges = tuple(sorted(resolved_edges, key=lambda item: item.order_key))
    return ResolutionResult(REFERENCE_RESOLUTION_VERSION, context.context_id,
                            context.context_digest, request.reference, objects, edges)


__all__ = [
    "AuthorityClass", "GovernedObject", "GovernedObjectReference",
    "GovernedRelationship", "GovernedResolutionError", "GovernedSnapshot",
    "REFERENCE_RESOLUTION_VERSION", "RelationshipKind", "ResolutionContext",
    "ResolutionFailureCode", "ResolutionRequest", "ResolutionResult",
    "ResolvedObject", "ResolvedRelationship", "SemanticField", "SemanticValue",
    "SemanticValueKind", "create_governed_object", "create_governed_snapshot",
    "create_resolution_context", "reference_to", "resolve_governed_reference",
]
