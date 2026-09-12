"""Immutable owner publication for validated Opportunity Structure content.

Mirrors ``canonical_opportunity_publication.py`` exactly wherever the
architecture requires identical behavior (identity binding, evidence and
provenance closure with the same VERIFIED / PARTIAL / UNVERIFIED
accommodation, deterministic snapshot and manifest construction, governed
reference resolution). It publishes exactly the five Opportunity Structure
object families -- REQUIREMENT, EVALUATION_CRITERION, COMMERCIAL_CLAUSE,
DELIVERABLE, SUBMISSION_RULE -- plus the structural conflicts Stage B/C
already detected among them. It performs no reconciliation, interpretation,
or decision of its own.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
import math
import re
from typing import Iterable, Mapping

from canonical_opportunity import canonical_json
from governed_reference_resolution import (
    AuthorityClass, GovernedObject, GovernedObjectReference,
    GovernedRelationship, GovernedResolutionError, GovernedSnapshot,
    RelationshipKind, SemanticField, SemanticValue, SemanticValueKind,
    create_governed_object, create_governed_snapshot, reference_to,
)
from opportunity_structure import FAMILIES, SCHEMA_VERSION

OWNER_DOMAIN = "opportunity-structure"
OWNER_CONTRACT = "opportunity-structure"
PUBLICATION_CONTRACT_VERSION = "1.0.0"
CONFLICT_CLASS = "STRUCTURE_CONFLICT"
_ZERO_DIGEST = "0" * 64
_SOURCE_INPUT_DIGEST_PREFIX = "input_"
_RECORD_KEYS = {
    "record_id", "family", "section", "fields",
    "source_refs", "provenance_status", "occurrence_count", "conflict_ids",
}
_CONFLICT_KEYS = {
    "conflict_id", "state", "family", "field", "affected_record_ids",
    "incompatible_values",
}


class StructurePublicationFailureCode(str, Enum):
    INVALID_STRUCTURE_STATE = "INVALID_STRUCTURE_STATE"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    DUPLICATE_IDENTITY = "DUPLICATE_IDENTITY"
    MISSING_SEMANTIC_CONTENT = "MISSING_SEMANTIC_CONTENT"
    MISSING_RELATIONSHIP_BINDING = "MISSING_RELATIONSHIP_BINDING"
    BROKEN_RELATIONSHIP = "BROKEN_RELATIONSHIP"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    INVALID_PUBLICATION = "INVALID_PUBLICATION"


class OpportunityStructurePublicationError(ValueError):
    """Controlled fail-closed Opportunity Structure publication failure."""

    def __init__(self, code: StructurePublicationFailureCode, message: str) -> None:
        self.code = code
        super().__init__(message)


def _fail(code: StructurePublicationFailureCode, message: str):
    raise OpportunityStructurePublicationError(code, message)


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
        _fail(StructurePublicationFailureCode.MISSING_SEMANTIC_CONTENT,
              f"structure semantic content is not serializable: {exc}")


def _sha(value) -> str:
    return sha256(_json(value).encode("utf-8")).hexdigest()


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or any(
            character.isspace() for character in value):
        _fail(StructurePublicationFailureCode.INVALID_STRUCTURE_STATE,
              f"{name} must be a stable non-whitespace identifier")
    return value


_SEMANTIC_FIELD_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")


def _semantic_value(value) -> SemanticValue:
    if value is None:
        return SemanticValue(SemanticValueKind.NULL)
    if type(value) is bool:
        return SemanticValue(SemanticValueKind.BOOLEAN, value)
    if type(value) is int:
        return SemanticValue(SemanticValueKind.INTEGER, value)
    if type(value) is float:
        # Stage A can extract a genuinely fractional field (e.g. an
        # EVALUATION_CRITERION weight) as a raw JSON number. A Python float's
        # own repr is not a stable, cross-platform canonical form; render it
        # through Decimal(str(value)) instead, matching how
        # canonical_opportunity.py's own _normalized_value already renders
        # MONETARY amounts, so the same source value always serializes to
        # the same DECIMAL string.
        if not math.isfinite(value):
            _fail(StructurePublicationFailureCode.MISSING_SEMANTIC_CONTENT,
                  f"non-finite decimal value cannot be published: {value!r}")
        return SemanticValue(SemanticValueKind.DECIMAL, format(Decimal(str(value)), "f"))
    if isinstance(value, str):
        if not value:
            return SemanticValue(SemanticValueKind.NULL)
        return SemanticValue(SemanticValueKind.STRING, value)
    if isinstance(value, Mapping):
        keys = tuple(str(key) for key in value)
        if len(keys) == len(set(keys)) and all(_SEMANTIC_FIELD_NAME.fullmatch(key) for key in keys):
            return SemanticValue(SemanticValueKind.OBJECT, fields=tuple(sorted((
                SemanticField(str(key), _semantic_value(item))
                for key, item in value.items()), key=lambda item: item.name)))
        entries = tuple(SemanticValue(SemanticValueKind.OBJECT, fields=(
            SemanticField("key", SemanticValue(SemanticValueKind.STRING, str(key))),
            SemanticField("value", _semantic_value(value[key])),
        )) for key in sorted(value, key=str))
        return SemanticValue(SemanticValueKind.ARRAY, items=entries)
    if isinstance(value, (list, tuple)):
        return SemanticValue(SemanticValueKind.ARRAY,
                             items=tuple(_semantic_value(item) for item in value))
    _fail(StructurePublicationFailureCode.MISSING_SEMANTIC_CONTENT,
          f"unsupported structure semantic value type: {type(value).__name__}")


def _semantic_fields(values: Mapping[str, object]) -> tuple[SemanticField, ...]:
    if not values:
        _fail(StructurePublicationFailureCode.MISSING_SEMANTIC_CONTENT,
              "published structure objects require semantic fields")
    try:
        return tuple(sorted((SemanticField(name, _semantic_value(value))
                             for name, value in values.items()),
                            key=lambda item: item.name))
    except GovernedResolutionError as exc:
        _fail(StructurePublicationFailureCode.MISSING_SEMANTIC_CONTENT,
              f"structure semantic field is invalid: {exc.code.value}")


@dataclass(frozen=True, slots=True)
class OpportunityStructureRecordBinding:
    """Exact upstream evidence and provenance targets for one structure record."""
    record_id: str
    evidence_references: tuple[GovernedObjectReference, ...]
    provenance_references: tuple[GovernedObjectReference, ...]

    def __post_init__(self) -> None:
        _identifier(self.record_id, "record_id")
        for name in ("evidence_references", "provenance_references"):
            values = getattr(self, name)
            if (not isinstance(values, tuple)
                    or any(not isinstance(item, GovernedObjectReference)
                           for item in values)):
                _fail(StructurePublicationFailureCode.BROKEN_RELATIONSHIP,
                      f"{name} must contain immutable governed references")
            expected = tuple(sorted(values, key=lambda item: item.identity_key))
            if values != expected or len(values) != len(set(values)):
                _fail(StructurePublicationFailureCode.DUPLICATE_IDENTITY,
                      f"{name} must be unique and canonically ordered")
            if any(item.owner_domain == OWNER_DOMAIN for item in values):
                _fail(StructurePublicationFailureCode.BROKEN_RELATIONSHIP,
                      f"{name} must remain owned outside Opportunity Structure")


@dataclass(frozen=True, slots=True)
class StructurePublicationManifestObject:
    object_class: str
    object_id: str
    object_digest: str


@dataclass(frozen=True, slots=True)
class StructurePublicationManifestRelationship:
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
class OpportunityStructurePublicationManifest:
    owner_domain: str
    owner_contract: str
    contract_version: str
    source_schema_version: str
    opportunity_id: str
    authoritative_input_digest: str
    object_manifest_digest: str
    snapshot_id: str
    snapshot_digest: str
    objects: tuple[StructurePublicationManifestObject, ...]
    relationships: tuple[StructurePublicationManifestRelationship, ...]


@dataclass(frozen=True, slots=True)
class OpportunityStructurePublication:
    publication_id: str
    opportunity_id: str
    source_schema_version: str
    authoritative_input_digest: str
    snapshot: GovernedSnapshot
    manifest: OpportunityStructurePublicationManifest
    references: tuple[GovernedObjectReference, ...]

    def __post_init__(self) -> None:
        validate_opportunity_structure_publication(self)

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
    semantics: Mapping[str, object]
    relationships: tuple[GovernedRelationship, ...] = ()


def _source_input_digest(structure: Mapping) -> str:
    material = {"documents": structure["documents"], "records": structure["records"]}
    return _SOURCE_INPUT_DIGEST_PREFIX + sha256(canonical_json(material).encode("utf-8")).hexdigest()


def _validate_source(structure: Mapping, opportunity_id: str) -> tuple[dict, ...]:
    _identifier(opportunity_id, "opportunity_id")
    if not isinstance(structure, Mapping):
        _fail(StructurePublicationFailureCode.INVALID_STRUCTURE_STATE,
              "publication requires an opportunity structure mapping")
    required = {"schema_version", "documents", "records", "conflicts",
                "coverage", "integrity_diagnostics", "input_digest"}
    if set(structure) != required:
        _fail(StructurePublicationFailureCode.INVALID_STRUCTURE_STATE,
              "opportunity structure envelope is incomplete or unsupported")
    if structure["schema_version"] != SCHEMA_VERSION:
        _fail(StructurePublicationFailureCode.VERSION_MISMATCH,
              "unsupported Opportunity Structure schema version")
    if (not isinstance(structure["input_digest"], str)
            or not structure["input_digest"].startswith(_SOURCE_INPUT_DIGEST_PREFIX)
            or structure["input_digest"] != _source_input_digest(structure)):
        _fail(StructurePublicationFailureCode.DIGEST_MISMATCH,
              "opportunity structure authoritative input digest is invalid")
    diagnostics = structure["integrity_diagnostics"]
    if not isinstance(diagnostics, Mapping) or diagnostics.get("collision_free") is not True:
        _fail(StructurePublicationFailureCode.INVALID_STRUCTURE_STATE,
              "opportunity structure has not completed collision-free identity assignment")
    if not isinstance(structure["documents"], list):
        _fail(StructurePublicationFailureCode.INVALID_STRUCTURE_STATE,
              "opportunity structure documents are invalid")
    for name in ("records", "conflicts"):
        if (not isinstance(structure[name], list)
                or any(not isinstance(item, Mapping) for item in structure[name])):
            _fail(StructurePublicationFailureCode.INVALID_STRUCTURE_STATE,
                  f"opportunity structure {name} are invalid")
    if not isinstance(structure["coverage"], Mapping):
        _fail(StructurePublicationFailureCode.INVALID_STRUCTURE_STATE,
              "opportunity structure coverage is invalid")
    records = tuple(structure["records"])
    conflicts = tuple(structure["conflicts"])
    record_ids = tuple(item.get("record_id") for item in records)
    conflict_ids = tuple(item.get("conflict_id") for item in conflicts)
    if (any(not isinstance(item, str) or not item for item in record_ids)
            or len(record_ids) != len(set(record_ids))):
        _fail(StructurePublicationFailureCode.DUPLICATE_IDENTITY,
              "opportunity structure record identities are invalid")
    if (any(not isinstance(item, str) or not item for item in conflict_ids)
            or len(conflict_ids) != len(set(conflict_ids))):
        _fail(StructurePublicationFailureCode.DUPLICATE_IDENTITY,
              "opportunity structure conflict identities are invalid")
    record_set, conflict_set = set(record_ids), set(conflict_ids)
    for record in records:
        if set(record) != _RECORD_KEYS:
            _fail(StructurePublicationFailureCode.MISSING_SEMANTIC_CONTENT,
                  f"unsupported opportunity structure record fields: {sorted(set(record) - _RECORD_KEYS)}")
        if record.get("family") not in FAMILIES:
            _fail(StructurePublicationFailureCode.INVALID_STRUCTURE_STATE,
                  f"unsupported opportunity structure family: {record.get('family')!r}")
        if any(item not in conflict_set for item in record.get("conflict_ids", [])):
            _fail(StructurePublicationFailureCode.BROKEN_RELATIONSHIP,
                  "opportunity structure record references an unknown conflict")
    for conflict in conflicts:
        if set(conflict) != _CONFLICT_KEYS:
            _fail(StructurePublicationFailureCode.MISSING_SEMANTIC_CONTENT,
                  f"unsupported opportunity structure conflict fields: {sorted(set(conflict) - _CONFLICT_KEYS)}")
        if any(item not in record_set for item in conflict.get("affected_record_ids", [])):
            _fail(StructurePublicationFailureCode.BROKEN_RELATIONSHIP,
                  "opportunity structure conflict references an unknown record")
    return records


def _record_semantics(record: Mapping) -> dict[str, object]:
    return {
        "record_id": record["record_id"], "family": record["family"],
        "section": record["section"], "occurrence_count": record["occurrence_count"],
        "provenance_status": record["provenance_status"],
        "conflict_ids": list(record["conflict_ids"]), "fields": dict(record["fields"]),
    }


def _conflict_semantics(conflict: Mapping) -> dict[str, object]:
    return {key: conflict.get(key) for key in sorted(_CONFLICT_KEYS)}


def _placeholder(snapshot_id: str, object_class: str, object_id: str) -> GovernedObjectReference:
    return GovernedObjectReference(
        OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION,
        snapshot_id, _ZERO_DIGEST, object_class, object_id, _ZERO_DIGEST)


def _relationship(kind: RelationshipKind, role: str, ordinal: int,
                  snapshot_id: str, object_class: str, object_id: str) -> GovernedRelationship:
    return GovernedRelationship(kind, role, _placeholder(snapshot_id, object_class, object_id), ordinal)


def _binding_map(records: tuple[Mapping, ...],
                 bindings: Iterable[OpportunityStructureRecordBinding],
                 ) -> dict[str, OpportunityStructureRecordBinding]:
    values = tuple(bindings)
    if any(not isinstance(item, OpportunityStructureRecordBinding) for item in values):
        _fail(StructurePublicationFailureCode.BROKEN_RELATIONSHIP,
              "structure record bindings are invalid")
    if values != tuple(sorted(values, key=lambda item: item.record_id)):
        _fail(StructurePublicationFailureCode.INVALID_PUBLICATION,
              "structure record bindings are not canonically ordered")
    result = {item.record_id: item for item in values}
    if len(result) != len(values):
        _fail(StructurePublicationFailureCode.DUPLICATE_IDENTITY,
              "structure record bindings contain duplicate identities")
    expected = {item["record_id"] for item in records}
    if set(result) != expected:
        _fail(StructurePublicationFailureCode.MISSING_RELATIONSHIP_BINDING,
              "structure record bindings must exactly cover opportunity structure records")
    for record in records:
        binding = result[record["record_id"]]
        has_source = bool(record.get("source_refs"))
        # Mirrors canonical_opportunity_publication.py's identical
        # accommodation: full evidence/provenance closure is required
        # unless Opportunity Structure's own independent provenance check
        # has already, explicitly declared this record's grounding PARTIAL
        # or UNVERIFIED. Silence (a missing or unrecognized
        # provenance_status) is never treated as a governed absence.
        closure_required = record.get("provenance_status") not in ("PARTIAL", "UNVERIFIED")
        if has_source and closure_required and (not binding.evidence_references
                           or not binding.provenance_references):
            _fail(StructurePublicationFailureCode.MISSING_RELATIONSHIP_BINDING,
                  f"record {binding.record_id} lacks evidence or provenance")
        if not has_source and (binding.evidence_references or binding.provenance_references):
            _fail(StructurePublicationFailureCode.BROKEN_RELATIONSHIP,
                  f"record {binding.record_id} has undeclared source relationships")
    return result


def _logical_manifest(specs: tuple[_ObjectSpec, ...]) -> tuple[dict, ...]:
    def target(value: GovernedObjectReference) -> dict:
        if (value.owner_domain, value.owner_contract, value.contract_version) == (
                OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION):
            return {"scope": "SELF", "object_class": value.object_class, "object_id": value.object_id}
        return {
            "scope": "EXTERNAL", "owner_domain": value.owner_domain,
            "owner_contract": value.owner_contract, "contract_version": value.contract_version,
            "snapshot_id": value.snapshot_id, "snapshot_digest": value.snapshot_digest,
            "object_class": value.object_class, "object_id": value.object_id,
            "object_digest": value.object_digest,
        }

    return tuple({
        "object_class": spec.object_class, "object_id": spec.object_id,
        "semantic_fields": _semantic_fields(spec.semantics),
        "relationships": tuple({
            "kind": item.kind, "role": item.role, "ordinal": item.ordinal,
            "target": target(item.target),
        } for item in spec.relationships),
    } for spec in specs)


def _logical_manifest_from_objects(objects: tuple[GovernedObject, ...]) -> tuple[dict, ...]:
    def target(value: GovernedObjectReference) -> dict:
        if (value.owner_domain, value.owner_contract, value.contract_version) == (
                OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION):
            return {"scope": "SELF", "object_class": value.object_class, "object_id": value.object_id}
        return {
            "scope": "EXTERNAL", "owner_domain": value.owner_domain,
            "owner_contract": value.owner_contract, "contract_version": value.contract_version,
            "snapshot_id": value.snapshot_id, "snapshot_digest": value.snapshot_digest,
            "object_class": value.object_class, "object_id": value.object_id,
            "object_digest": value.object_digest,
        }

    return tuple({
        "object_class": item.object_class, "object_id": item.object_id,
        "semantic_fields": item.semantic_fields,
        "relationships": tuple({
            "kind": relationship.kind, "role": relationship.role, "ordinal": relationship.ordinal,
            "target": target(relationship.target),
        } for relationship in item.relationships),
    } for item in objects)


def _build_specs(structure: Mapping, records: tuple[Mapping, ...],
                 bindings: Mapping[str, OpportunityStructureRecordBinding],
                 snapshot_id: str) -> tuple[_ObjectSpec, ...]:
    specs = []
    for record in records:
        relationships = []
        binding = bindings[record["record_id"]]
        for ordinal, target in enumerate(binding.evidence_references):
            relationships.append(GovernedRelationship(
                RelationshipKind.EVIDENCE_SUPPORT, "source-evidence", target, ordinal))
        for ordinal, target in enumerate(binding.provenance_references):
            relationships.append(GovernedRelationship(
                RelationshipKind.PROVENANCE, "source-provenance", target, ordinal))
        offset = len(relationships)
        for ordinal, conflict_id in enumerate(record.get("conflict_ids", []), offset):
            relationships.append(_relationship(
                RelationshipKind.RELATED, "affected-by-conflict", ordinal,
                snapshot_id, CONFLICT_CLASS, conflict_id))
        specs.append(_ObjectSpec(
            record["family"], record["record_id"], _record_semantics(record),
            tuple(sorted(relationships, key=lambda item: item.order_key))))
    for conflict in structure["conflicts"]:
        relationships = tuple(_relationship(
            RelationshipKind.CONFLICT_MEMBER, "affected-record", ordinal,
            snapshot_id, conflict["family"], record_id)
            for ordinal, record_id in enumerate(conflict.get("affected_record_ids", [])))
        specs.append(_ObjectSpec(
            CONFLICT_CLASS, conflict["conflict_id"], _conflict_semantics(conflict),
            tuple(sorted(relationships, key=lambda item: item.order_key))))
    return tuple(sorted(specs, key=lambda item: (item.object_class, item.object_id)))


def publish_opportunity_structure(
        structure: Mapping, *, opportunity_id: str,
        record_bindings: Iterable[OpportunityStructureRecordBinding],
        ) -> OpportunityStructurePublication:
    """Publish one validated opportunity structure state without assembling a context."""
    before = canonical_json(structure) if isinstance(structure, Mapping) else None
    records = _validate_source(structure, opportunity_id)
    bindings = _binding_map(records, record_bindings)

    provisional_specs = _build_specs(structure, records, bindings, "structure-publication-pending")
    object_manifest_digest = _sha(_logical_manifest(provisional_specs))
    snapshot_id = "structure-publication-" + _sha({
        "owner_domain": OWNER_DOMAIN, "owner_contract": OWNER_CONTRACT,
        "contract_version": PUBLICATION_CONTRACT_VERSION, "opportunity_id": opportunity_id,
        "authoritative_input_digest": structure["input_digest"],
        "object_manifest_digest": object_manifest_digest,
    })
    specs = _build_specs(structure, records, bindings, snapshot_id)
    if _sha(_logical_manifest(specs)) != object_manifest_digest:
        _fail(StructurePublicationFailureCode.DIGEST_MISMATCH,
              "structure object manifest changed during snapshot binding")
    try:
        objects = tuple(create_governed_object(
            owner_domain=OWNER_DOMAIN, owner_contract=OWNER_CONTRACT,
            contract_version=PUBLICATION_CONTRACT_VERSION,
            object_class=spec.object_class, object_id=spec.object_id,
            authority=(AuthorityClass.CONFLICT if spec.object_class == CONFLICT_CLASS
                       else AuthorityClass.CANONICAL_FACT),
            semantic_fields=_semantic_fields(spec.semantics),
            relationships=spec.relationships,
        ) for spec in specs)
        snapshot = create_governed_snapshot(
            owner_domain=OWNER_DOMAIN, owner_contract=OWNER_CONTRACT,
            contract_version=PUBLICATION_CONTRACT_VERSION,
            snapshot_id=snapshot_id, objects=objects)
    except GovernedResolutionError as exc:
        _fail(StructurePublicationFailureCode.INVALID_PUBLICATION,
              f"structure publication snapshot is invalid: {exc.code.value}")

    references = tuple(reference_to(snapshot, item.object_class, item.object_id) for item in snapshot.objects)
    manifest_objects = tuple(StructurePublicationManifestObject(
        item.object_class, item.object_id, item.object_digest) for item in snapshot.objects)
    manifest_relationships = tuple(sorted((
        StructurePublicationManifestRelationship(
            item.object_class, item.object_id, relationship.kind,
            relationship.role, relationship.ordinal, relationship.target)
        for item in snapshot.objects for relationship in item.relationships
    ), key=lambda item: item.order_key))
    manifest = OpportunityStructurePublicationManifest(
        OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION,
        SCHEMA_VERSION, opportunity_id, structure["input_digest"],
        object_manifest_digest, snapshot.snapshot_id, snapshot.snapshot_digest,
        manifest_objects, manifest_relationships)
    publication_id = "structure-publication-record-" + _sha({
        "opportunity_id": opportunity_id, "authoritative_input_digest": structure["input_digest"],
        "snapshot_id": snapshot.snapshot_id, "snapshot_digest": snapshot.snapshot_digest,
    })
    publication = OpportunityStructurePublication(
        publication_id, opportunity_id, SCHEMA_VERSION,
        structure["input_digest"], snapshot, manifest, references)
    if canonical_json(structure) != before:
        _fail(StructurePublicationFailureCode.INVALID_STRUCTURE_STATE,
              "structure publication mutated its source")
    return publication


def validate_opportunity_structure_publication(
        publication: OpportunityStructurePublication) -> OpportunityStructurePublication:
    if not isinstance(publication, OpportunityStructurePublication):
        _fail(StructurePublicationFailureCode.INVALID_PUBLICATION,
              "OpportunityStructurePublication is required")
    manifest, snapshot = publication.manifest, publication.snapshot
    if not isinstance(manifest, OpportunityStructurePublicationManifest):
        _fail(StructurePublicationFailureCode.INVALID_PUBLICATION,
              "structure publication manifest is invalid")
    if not isinstance(snapshot, GovernedSnapshot):
        _fail(StructurePublicationFailureCode.INVALID_PUBLICATION,
              "structure publication snapshot is invalid")
    expected_owner = (OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION)
    if ((snapshot.owner_domain, snapshot.owner_contract, snapshot.contract_version) != expected_owner
            or (manifest.owner_domain, manifest.owner_contract, manifest.contract_version) != expected_owner):
        _fail(StructurePublicationFailureCode.VERSION_MISMATCH,
              "structure publication owner binding is invalid")
    if (publication.source_schema_version != SCHEMA_VERSION
            or manifest.source_schema_version != SCHEMA_VERSION):
        _fail(StructurePublicationFailureCode.VERSION_MISMATCH,
              "structure source schema binding is invalid")
    if (publication.opportunity_id != manifest.opportunity_id
            or publication.authoritative_input_digest != manifest.authoritative_input_digest):
        _fail(StructurePublicationFailureCode.INVALID_PUBLICATION,
              "structure publication envelope and manifest differ")
    if not publication.authoritative_input_digest.startswith(_SOURCE_INPUT_DIGEST_PREFIX):
        _fail(StructurePublicationFailureCode.DIGEST_MISMATCH,
              "structure authoritative input digest is invalid")
    if (snapshot.snapshot_id, snapshot.snapshot_digest) != (manifest.snapshot_id, manifest.snapshot_digest):
        _fail(StructurePublicationFailureCode.DIGEST_MISMATCH,
              "structure snapshot and manifest differ")
    if _sha(_logical_manifest_from_objects(snapshot.objects)) != manifest.object_manifest_digest:
        _fail(StructurePublicationFailureCode.DIGEST_MISMATCH,
              "structure object manifest digest differs from its snapshot")
    expected_snapshot_id = "structure-publication-" + _sha({
        "owner_domain": OWNER_DOMAIN, "owner_contract": OWNER_CONTRACT,
        "contract_version": PUBLICATION_CONTRACT_VERSION, "opportunity_id": publication.opportunity_id,
        "authoritative_input_digest": publication.authoritative_input_digest,
        "object_manifest_digest": manifest.object_manifest_digest,
    })
    if snapshot.snapshot_id != expected_snapshot_id:
        _fail(StructurePublicationFailureCode.DIGEST_MISMATCH,
              "structure publication snapshot identity is invalid")
    expected_objects = tuple(StructurePublicationManifestObject(
        item.object_class, item.object_id, item.object_digest) for item in snapshot.objects)
    if manifest.objects != expected_objects:
        _fail(StructurePublicationFailureCode.DIGEST_MISMATCH,
              "structure object manifest differs from its snapshot")
    allowed = FAMILIES | {CONFLICT_CLASS}
    if any(item.object_class not in allowed for item in snapshot.objects):
        _fail(StructurePublicationFailureCode.INVALID_PUBLICATION,
              "structure snapshot contains a foreign object class")
    expected_relationships = tuple(sorted((
        StructurePublicationManifestRelationship(
            item.object_class, item.object_id, relationship.kind,
            relationship.role, relationship.ordinal, relationship.target)
        for item in snapshot.objects for relationship in item.relationships
    ), key=lambda item: item.order_key))
    if manifest.relationships != expected_relationships:
        _fail(StructurePublicationFailureCode.BROKEN_RELATIONSHIP,
              "structure relationship manifest differs from its snapshot")
    expected_references = tuple(reference_to(snapshot, item.object_class, item.object_id) for item in snapshot.objects)
    if not isinstance(publication.references, tuple) or publication.references != expected_references:
        _fail(StructurePublicationFailureCode.DIGEST_MISMATCH,
              "structure references differ from the immutable snapshot")
    expected_publication_id = "structure-publication-record-" + _sha({
        "opportunity_id": publication.opportunity_id,
        "authoritative_input_digest": publication.authoritative_input_digest,
        "snapshot_id": snapshot.snapshot_id, "snapshot_digest": snapshot.snapshot_digest,
    })
    if publication.publication_id != expected_publication_id:
        _fail(StructurePublicationFailureCode.DIGEST_MISMATCH,
              "structure publication identity is invalid")
    object_keys = {(item.object_class, item.object_id) for item in snapshot.objects}
    for item in snapshot.objects:
        if not item.semantic_fields:
            _fail(StructurePublicationFailureCode.MISSING_SEMANTIC_CONTENT,
                  f"structure object {item.object_id} has no semantic content")
        for relationship in item.relationships:
            target = relationship.target
            if target.owner_domain == OWNER_DOMAIN and (
                    target.owner_contract != OWNER_CONTRACT
                    or target.contract_version != PUBLICATION_CONTRACT_VERSION
                    or (target.object_class, target.object_id) not in object_keys):
                _fail(StructurePublicationFailureCode.BROKEN_RELATIONSHIP,
                      f"structure relationship from {item.object_id} does not close")
    return publication


__all__ = [
    "CONFLICT_CLASS", "OWNER_CONTRACT", "OWNER_DOMAIN", "PUBLICATION_CONTRACT_VERSION",
    "OpportunityStructurePublication", "OpportunityStructurePublicationError",
    "OpportunityStructurePublicationManifest", "OpportunityStructureRecordBinding",
    "StructurePublicationFailureCode", "StructurePublicationManifestObject",
    "StructurePublicationManifestRelationship", "publish_opportunity_structure",
    "validate_opportunity_structure_publication",
]
