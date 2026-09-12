"""Immutable owner publication for validated Canonical Opportunity semantics."""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Iterable, Mapping

from canonical_opportunity import SCHEMA_VERSION, canonical_json
from governed_reference_resolution import (
    AuthorityClass, GovernedObject, GovernedObjectReference,
    GovernedRelationship, GovernedResolutionError, GovernedSnapshot,
    RelationshipKind, SemanticField, SemanticValue, SemanticValueKind,
    create_governed_object, create_governed_snapshot, reference_to,
)

OWNER_DOMAIN = "canonical-opportunity"
OWNER_CONTRACT = "canonical-opportunity"
PUBLICATION_CONTRACT_VERSION = "1.2.0"
FIELD_STATE_CLASS = "CANONICAL_FIELD_STATE"
OBSERVATION_CLASS = "CANONICAL_OBSERVATION"
CONFLICT_CLASS = "CANONICAL_CONFLICT"
# The single additive object representing the Opportunity itself -- the
# governed anchor every other publication's "this analysis/record concerns
# THIS opportunity" relationship can resolve against. It never restates or
# reinterprets a resolved field; it exists only to be the referenceable
# whole that the already-published per-field CANONICAL_FIELD_STATE objects
# are part of (see OPPORTUNITY_IDENTITY_AND_LEGACY_DATES_ARCHITECTURE.md).
IDENTITY_CLASS = "CANONICAL_OPPORTUNITY_IDENTITY"
_ZERO_DIGEST = "0" * 64
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_INPUT_DIGEST = re.compile(r"^input_[0-9a-f]{64}$")
_SEMANTIC_FIELD = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")


class CanonicalPublicationFailureCode(str, Enum):
    INVALID_CANONICAL_STATE = "INVALID_CANONICAL_STATE"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    DUPLICATE_IDENTITY = "DUPLICATE_IDENTITY"
    MISSING_SEMANTIC_CONTENT = "MISSING_SEMANTIC_CONTENT"
    MISSING_RELATIONSHIP_BINDING = "MISSING_RELATIONSHIP_BINDING"
    BROKEN_RELATIONSHIP = "BROKEN_RELATIONSHIP"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    INVALID_PUBLICATION = "INVALID_PUBLICATION"


class CanonicalOpportunityPublicationError(ValueError):
    """Controlled fail-closed Canonical Opportunity publication failure."""

    def __init__(self, code: CanonicalPublicationFailureCode, message: str) -> None:
        self.code = code
        super().__init__(message)


def _fail(code: CanonicalPublicationFailureCode, message: str):
    raise CanonicalOpportunityPublicationError(code, message)


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
        _fail(CanonicalPublicationFailureCode.MISSING_SEMANTIC_CONTENT,
              f"canonical semantic content is not serializable: {exc}")


def _sha(value) -> str:
    return sha256(_json(value).encode("utf-8")).hexdigest()


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or any(
            character.isspace() for character in value):
        _fail(CanonicalPublicationFailureCode.INVALID_CANONICAL_STATE,
              f"{name} must be a stable non-whitespace identifier")
    return value


def _semantic_value(value) -> SemanticValue:
    if value is None:
        return SemanticValue(SemanticValueKind.NULL)
    if type(value) is bool:
        return SemanticValue(SemanticValueKind.BOOLEAN, value)
    if type(value) is int:
        return SemanticValue(SemanticValueKind.INTEGER, value)
    if isinstance(value, str):
        # An empty string and an absent value are the same "nothing" for
        # publication purposes -- e.g. Canonical Opportunity's own
        # normalization_state "EMPTY" legitimately produces
        # normalized_value == "" for a typed observation with no real
        # textual value. Governed Reference Resolution's STRING kind
        # requires non-empty content by design (a real, general invariant
        # this does not weaken); representing emptiness as NULL, exactly as
        # None already is, is the correct mapping rather than treating an
        # already-defined upstream state as invalid.
        if not value:
            return SemanticValue(SemanticValueKind.NULL)
        return SemanticValue(SemanticValueKind.STRING, value)
    if isinstance(value, Mapping):
        keys = tuple(str(key) for key in value)
        if len(keys) == len(set(keys)) and all(_SEMANTIC_FIELD.fullmatch(key) for key in keys):
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
    _fail(CanonicalPublicationFailureCode.MISSING_SEMANTIC_CONTENT,
          f"unsupported canonical semantic value type: {type(value).__name__}")


def _semantic_fields(values: Mapping[str, object]) -> tuple[SemanticField, ...]:
    if not values:
        _fail(CanonicalPublicationFailureCode.MISSING_SEMANTIC_CONTENT,
              "published canonical objects require semantic fields")
    try:
        return tuple(sorted((SemanticField(name, _semantic_value(value))
                             for name, value in values.items()),
                            key=lambda item: item.name))
    except GovernedResolutionError as exc:
        _fail(CanonicalPublicationFailureCode.MISSING_SEMANTIC_CONTENT,
              f"canonical semantic field is invalid: {exc.code.value}")


@dataclass(frozen=True, slots=True)
class CanonicalObservationBinding:
    """Exact upstream evidence and provenance targets for one observation."""
    observation_id: str
    evidence_references: tuple[GovernedObjectReference, ...]
    provenance_references: tuple[GovernedObjectReference, ...]

    def __post_init__(self) -> None:
        _identifier(self.observation_id, "observation_id")
        for name in ("evidence_references", "provenance_references"):
            values = getattr(self, name)
            if (not isinstance(values, tuple)
                    or any(not isinstance(item, GovernedObjectReference)
                           for item in values)):
                _fail(CanonicalPublicationFailureCode.BROKEN_RELATIONSHIP,
                      f"{name} must contain immutable governed references")
            expected = tuple(sorted(values, key=lambda item: item.identity_key))
            if values != expected or len(values) != len(set(values)):
                _fail(CanonicalPublicationFailureCode.DUPLICATE_IDENTITY,
                      f"{name} must be unique and canonically ordered")
            if any(item.owner_domain == OWNER_DOMAIN for item in values):
                _fail(CanonicalPublicationFailureCode.BROKEN_RELATIONSHIP,
                      f"{name} must remain owned outside Canonical Opportunity")


@dataclass(frozen=True, slots=True)
class CanonicalPublicationManifestObject:
    object_class: str
    object_id: str
    object_digest: str


@dataclass(frozen=True, slots=True)
class CanonicalPublicationManifestRelationship:
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
class CanonicalOpportunityPublicationManifest:
    owner_domain: str
    owner_contract: str
    contract_version: str
    source_schema_version: str
    opportunity_id: str
    authoritative_input_digest: str
    object_manifest_digest: str
    snapshot_id: str
    snapshot_digest: str
    objects: tuple[CanonicalPublicationManifestObject, ...]
    relationships: tuple[CanonicalPublicationManifestRelationship, ...]


@dataclass(frozen=True, slots=True)
class CanonicalOpportunityPublication:
    publication_id: str
    opportunity_id: str
    source_schema_version: str
    authoritative_input_digest: str
    snapshot: GovernedSnapshot
    manifest: CanonicalOpportunityPublicationManifest
    references: tuple[GovernedObjectReference, ...]

    def __post_init__(self) -> None:
        validate_canonical_opportunity_publication(self)

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


_OBSERVATION_SEMANTIC_FIELDS = {
    "observation_id", "normalized_identity_id", "family", "semantic_kind",
    "original_value", "normalized_value", "normalization_state",
    "provenance_status", "document_role", "document_role_basis", "source_state",
    "scope", "supersession", "supersession_state", "superseded_by",
    "conflict_ids",
}
_OBSERVATION_NON_SEMANTIC_FIELDS = {
    "source_document_id", "source_doc", "source_refs", "source_pointer",
    "extraction_occurrences", "identity_material",
}
_CONFLICT_SEMANTIC_FIELDS = {
    "conflict_id", "state", "semantic_kind", "scope", "affected_fields",
    "link_status", "affected_observation_ids", "incompatible_values",
    "resolution_basis", "resolved_by",
}
_CONFLICT_NON_SEMANTIC_FIELDS = {"source_refs"}


def _source_input_digest(canonical: Mapping) -> str:
    material = {"documents": canonical["documents"],
                "observations": canonical["observations"]}
    return "input_" + sha256(canonical_json(material).encode("utf-8")).hexdigest()


def _validate_source(canonical: Mapping, opportunity_id: str) -> tuple[dict, ...]:
    _identifier(opportunity_id, "opportunity_id")
    if not isinstance(canonical, Mapping):
        _fail(CanonicalPublicationFailureCode.INVALID_CANONICAL_STATE,
              "publication requires a canonical opportunity mapping")
    required = {"schema_version", "documents", "observations", "resolved",
                "conflicts", "coverage", "integrity_diagnostics", "input_digest"}
    if set(canonical) != required:
        _fail(CanonicalPublicationFailureCode.INVALID_CANONICAL_STATE,
              "canonical opportunity envelope is incomplete or unsupported")
    if canonical["schema_version"] != SCHEMA_VERSION:
        _fail(CanonicalPublicationFailureCode.VERSION_MISMATCH,
              "unsupported Canonical Opportunity schema version")
    if (not isinstance(canonical["input_digest"], str)
            or not _SOURCE_INPUT_DIGEST.fullmatch(canonical["input_digest"])
            or canonical["input_digest"] != _source_input_digest(canonical)):
        _fail(CanonicalPublicationFailureCode.DIGEST_MISMATCH,
              "canonical authoritative input digest is invalid")
    diagnostics = canonical["integrity_diagnostics"]
    if (not isinstance(diagnostics, Mapping)
            or diagnostics.get("collision_free") is not True
            or diagnostics.get("resolution_complete") is not True
            or diagnostics.get("supersession_cycles")):
        _fail(CanonicalPublicationFailureCode.INVALID_CANONICAL_STATE,
              "canonical opportunity has not completed safe resolution")
    if not isinstance(canonical["documents"], list):
        _fail(CanonicalPublicationFailureCode.INVALID_CANONICAL_STATE,
              "canonical documents are invalid")
    for name in ("observations", "conflicts"):
        if (not isinstance(canonical[name], list)
                or any(not isinstance(item, Mapping) for item in canonical[name])):
            _fail(CanonicalPublicationFailureCode.INVALID_CANONICAL_STATE,
                  f"canonical {name} are invalid")
    if (not isinstance(canonical["resolved"], Mapping)
            or not canonical["resolved"]
            or any(not isinstance(value, Mapping)
                   for value in canonical["resolved"].values())):
        _fail(CanonicalPublicationFailureCode.INVALID_CANONICAL_STATE,
              "canonical resolved field states are unavailable")
    if not isinstance(canonical["coverage"], Mapping):
        _fail(CanonicalPublicationFailureCode.INVALID_CANONICAL_STATE,
              "canonical coverage is invalid")
    observations = tuple(canonical["observations"])
    conflicts = tuple(canonical["conflicts"])
    observation_ids = tuple(item.get("observation_id") for item in observations)
    conflict_ids = tuple(item.get("conflict_id") for item in conflicts)
    if (any(not isinstance(item, str) or not item for item in observation_ids)
            or len(observation_ids) != len(set(observation_ids))):
        _fail(CanonicalPublicationFailureCode.DUPLICATE_IDENTITY,
              "canonical observation identities are invalid")
    if (any(not isinstance(item, str) or not item for item in conflict_ids)
            or len(conflict_ids) != len(set(conflict_ids))):
        _fail(CanonicalPublicationFailureCode.DUPLICATE_IDENTITY,
              "canonical conflict identities are invalid")
    observation_set, conflict_set = set(observation_ids), set(conflict_ids)
    for observation in observations:
        keys = set(observation)
        if not keys <= _OBSERVATION_SEMANTIC_FIELDS | _OBSERVATION_NON_SEMANTIC_FIELDS:
            _fail(CanonicalPublicationFailureCode.MISSING_SEMANTIC_CONTENT,
                  f"unsupported canonical observation fields: {sorted(keys - _OBSERVATION_SEMANTIC_FIELDS - _OBSERVATION_NON_SEMANTIC_FIELDS)}")
        if any(item not in conflict_set for item in observation.get("conflict_ids", [])):
            _fail(CanonicalPublicationFailureCode.BROKEN_RELATIONSHIP,
                  "canonical observation references an unknown conflict")
        supersession = observation.get("supersession") or {}
        if not isinstance(supersession, Mapping):
            _fail(CanonicalPublicationFailureCode.INVALID_CANONICAL_STATE,
                  "canonical supersession state is invalid")
        targets = supersession.get("supersedes_observation_ids", []) or []
        if any(item not in observation_set for item in targets):
            _fail(CanonicalPublicationFailureCode.BROKEN_RELATIONSHIP,
                  "canonical supersession references an unknown observation")
    for conflict in conflicts:
        keys = set(conflict)
        if not keys <= _CONFLICT_SEMANTIC_FIELDS | _CONFLICT_NON_SEMANTIC_FIELDS:
            _fail(CanonicalPublicationFailureCode.MISSING_SEMANTIC_CONTENT,
                  f"unsupported canonical conflict fields: {sorted(keys - _CONFLICT_SEMANTIC_FIELDS - _CONFLICT_NON_SEMANTIC_FIELDS)}")
        if any(item not in observation_set
               for item in conflict.get("affected_observation_ids", [])):
            _fail(CanonicalPublicationFailureCode.BROKEN_RELATIONSHIP,
                  "canonical conflict references an unknown observation")
    for field_name, state in canonical["resolved"].items():
        _identifier(field_name, "canonical field key")
        if any(item not in observation_set for item in state.get("observation_ids", [])):
            _fail(CanonicalPublicationFailureCode.BROKEN_RELATIONSHIP,
                  "canonical field references an unknown observation")
        if any(item not in conflict_set for item in state.get("conflict_ids", [])):
            _fail(CanonicalPublicationFailureCode.BROKEN_RELATIONSHIP,
                  "canonical field references an unknown conflict")
    return observations


def _observation_semantics(observation: Mapping) -> dict[str, object]:
    values = {key: observation.get(key) for key in sorted(_OBSERVATION_SEMANTIC_FIELDS)
              if key in observation}
    supersession = values.get("supersession")
    if isinstance(supersession, Mapping):
        values["supersession"] = {
            key: supersession[key] for key in sorted(supersession)
            if key != "source_refs"}
    return values


def _conflict_semantics(conflict: Mapping) -> dict[str, object]:
    return {key: conflict.get(key) for key in sorted(_CONFLICT_SEMANTIC_FIELDS)
            if key in conflict}


def _placeholder(snapshot_id: str, object_class: str,
                 object_id: str) -> GovernedObjectReference:
    return GovernedObjectReference(
        OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION,
        snapshot_id, _ZERO_DIGEST, object_class, object_id, _ZERO_DIGEST)


def _relationship(kind: RelationshipKind, role: str, ordinal: int,
                  snapshot_id: str, object_class: str,
                  object_id: str) -> GovernedRelationship:
    return GovernedRelationship(
        kind, role, _placeholder(snapshot_id, object_class, object_id), ordinal)


def _field_object_id(opportunity_id: str, field_name: str) -> str:
    return "canonical-field-" + _sha({
        "owner_contract": OWNER_CONTRACT,
        "contract_version": PUBLICATION_CONTRACT_VERSION,
        "opportunity_id": opportunity_id,
        "field_key": field_name,
    })


def identity_object_id(opportunity_id: str, authoritative_input_digest: str) -> str:
    """The deterministic identity of the Opportunity itself for one exact
    (opportunity_id, authoritative_input_digest) pair -- the same pair
    publish_canonical_opportunity already requires. Exposed as a public
    function so a caller can compute the Opportunity's governed identity
    (for example, to use as an OpportunityAnalysisContext context_id)
    before or independently of building a full publication.
    """
    _identifier(opportunity_id, "opportunity_id")
    if not _SOURCE_INPUT_DIGEST.fullmatch(authoritative_input_digest or ""):
        _fail(CanonicalPublicationFailureCode.DIGEST_MISMATCH,
              "authoritative_input_digest is invalid")
    return "canonical-opportunity-identity-" + _sha({
        "owner_contract": OWNER_CONTRACT,
        "contract_version": PUBLICATION_CONTRACT_VERSION,
        "class": IDENTITY_CLASS,
        "opportunity_id": opportunity_id,
        "authoritative_input_digest": authoritative_input_digest,
    })


def _binding_map(observations: tuple[Mapping, ...],
                 bindings: Iterable[CanonicalObservationBinding]
                 ) -> dict[str, CanonicalObservationBinding]:
    values = tuple(bindings)
    if any(not isinstance(item, CanonicalObservationBinding) for item in values):
        _fail(CanonicalPublicationFailureCode.BROKEN_RELATIONSHIP,
              "observation bindings are invalid")
    if values != tuple(sorted(values, key=lambda item: item.observation_id)):
        _fail(CanonicalPublicationFailureCode.INVALID_PUBLICATION,
              "observation bindings are not canonically ordered")
    result = {item.observation_id: item for item in values}
    if len(result) != len(values):
        _fail(CanonicalPublicationFailureCode.DUPLICATE_IDENTITY,
              "observation bindings contain duplicate identities")
    expected = {item["observation_id"] for item in observations}
    if set(result) != expected:
        _fail(CanonicalPublicationFailureCode.MISSING_RELATIONSHIP_BINDING,
              "observation bindings must exactly cover canonical observations")
    for observation in observations:
        binding = result[observation["observation_id"]]
        has_source = bool(observation.get("source_refs")
                          or observation.get("extraction_occurrences"))
        # Full evidence/provenance closure is required whenever Canonical
        # Opportunity's own tri-state provenance check has not already,
        # explicitly declared this observation's grounding PARTIAL or
        # UNVERIFIED. An observation with a missing or unrecognized
        # provenance_status is held to the strict requirement, matching
        # VERIFIED -- silence is never treated as a governed absence.
        closure_required = observation.get("provenance_status") not in ("PARTIAL", "UNVERIFIED")
        if has_source and closure_required and (not binding.evidence_references
                           or not binding.provenance_references):
            _fail(CanonicalPublicationFailureCode.MISSING_RELATIONSHIP_BINDING,
                  f"observation {binding.observation_id} lacks evidence or provenance")
        if not has_source and (binding.evidence_references
                               or binding.provenance_references):
            _fail(CanonicalPublicationFailureCode.BROKEN_RELATIONSHIP,
                  f"observation {binding.observation_id} has undeclared source relationships")
    return result


def _logical_manifest(specs: tuple[_ObjectSpec, ...]) -> tuple[dict, ...]:
    def target(value: GovernedObjectReference) -> dict:
        if (value.owner_domain, value.owner_contract, value.contract_version) == (
                OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION):
            return {"scope": "SELF", "object_class": value.object_class,
                    "object_id": value.object_id}
        return {
            "scope": "EXTERNAL", "owner_domain": value.owner_domain,
            "owner_contract": value.owner_contract,
            "contract_version": value.contract_version,
            "snapshot_id": value.snapshot_id,
            "snapshot_digest": value.snapshot_digest,
            "object_class": value.object_class, "object_id": value.object_id,
            "object_digest": value.object_digest,
        }

    return tuple({
        "object_class": spec.object_class,
        "object_id": spec.object_id,
        "semantic_fields": _semantic_fields(spec.semantics),
        "relationships": tuple({
            "kind": item.kind,
            "role": item.role,
            "ordinal": item.ordinal,
            "target": target(item.target),
        } for item in spec.relationships),
    } for spec in specs)


def _logical_manifest_from_objects(
        objects: tuple[GovernedObject, ...],
        ) -> tuple[dict, ...]:
    def target(value: GovernedObjectReference) -> dict:
        if (value.owner_domain, value.owner_contract, value.contract_version) == (
                OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION):
            return {"scope": "SELF", "object_class": value.object_class,
                    "object_id": value.object_id}
        return {
            "scope": "EXTERNAL", "owner_domain": value.owner_domain,
            "owner_contract": value.owner_contract,
            "contract_version": value.contract_version,
            "snapshot_id": value.snapshot_id,
            "snapshot_digest": value.snapshot_digest,
            "object_class": value.object_class, "object_id": value.object_id,
            "object_digest": value.object_digest,
        }

    return tuple({
        "object_class": item.object_class,
        "object_id": item.object_id,
        "semantic_fields": item.semantic_fields,
        "relationships": tuple({
            "kind": relationship.kind,
            "role": relationship.role,
            "ordinal": relationship.ordinal,
            "target": target(relationship.target),
        } for relationship in item.relationships),
    } for item in objects)


def _build_specs(canonical: Mapping, observations: tuple[Mapping, ...],
                 bindings: Mapping[str, CanonicalObservationBinding],
                 field_ids: Mapping[str, str], identity_id: str,
                 opportunity_id: str, snapshot_id: str) -> tuple[_ObjectSpec, ...]:
    specs = []
    identity_relationships = tuple(_relationship(
        RelationshipKind.DEPENDENCY, "contains-field-state", ordinal,
        snapshot_id, FIELD_STATE_CLASS, field_ids[field_name])
        for ordinal, field_name in enumerate(sorted(field_ids)))
    specs.append(_ObjectSpec(
        IDENTITY_CLASS, identity_id,
        {"opportunity_id": opportunity_id, "source_schema_version": SCHEMA_VERSION,
         "authoritative_input_digest": canonical["input_digest"],
         "document_count": len(canonical["documents"])},
        identity_relationships))
    for field_name, state in sorted(canonical["resolved"].items()):
        relationships = []
        for ordinal, observation_id in enumerate(state.get("observation_ids", [])):
            relationships.append(_relationship(
                RelationshipKind.SUPPORT, "contributing-observation", ordinal,
                snapshot_id, OBSERVATION_CLASS, observation_id))
        offset = len(relationships)
        for ordinal, conflict_id in enumerate(state.get("conflict_ids", []), offset):
            relationships.append(_relationship(
                RelationshipKind.RELATED, "affected-by-conflict", ordinal,
                snapshot_id, CONFLICT_CLASS, conflict_id))
        specs.append(_ObjectSpec(
            FIELD_STATE_CLASS, field_ids[field_name],
            {"field_key": field_name, "state": dict(state),
             "coverage": canonical["coverage"].get(field_name)},
            tuple(sorted(relationships, key=lambda item: item.order_key))))
    for observation in observations:
        relationships = []
        binding = bindings[observation["observation_id"]]
        for ordinal, target in enumerate(binding.evidence_references):
            relationships.append(GovernedRelationship(
                RelationshipKind.EVIDENCE_SUPPORT, "source-evidence", target, ordinal))
        for ordinal, target in enumerate(binding.provenance_references):
            relationships.append(GovernedRelationship(
                RelationshipKind.PROVENANCE, "source-provenance", target, ordinal))
        supersession = observation.get("supersession") or {}
        if (supersession.get("resolution_state") == "RESOLVED"
                and supersession.get("provenance_status") == "VERIFIED"):
            for ordinal, target_id in enumerate(
                    supersession.get("supersedes_observation_ids", [])):
                relationships.append(_relationship(
                    RelationshipKind.SUPERSESSION, "supersedes", ordinal,
                    snapshot_id, OBSERVATION_CLASS, target_id))
        specs.append(_ObjectSpec(
            OBSERVATION_CLASS, observation["observation_id"],
            _observation_semantics(observation),
            tuple(sorted(relationships, key=lambda item: item.order_key))))
    for conflict in canonical["conflicts"]:
        relationships = tuple(_relationship(
            RelationshipKind.CONFLICT_MEMBER, "affected-observation", ordinal,
            snapshot_id, OBSERVATION_CLASS, observation_id)
            for ordinal, observation_id in enumerate(
                conflict.get("affected_observation_ids", [])))
        specs.append(_ObjectSpec(
            CONFLICT_CLASS, conflict["conflict_id"], _conflict_semantics(conflict),
            tuple(sorted(relationships, key=lambda item: item.order_key))))
    return tuple(sorted(specs, key=lambda item: (item.object_class, item.object_id)))


def publish_canonical_opportunity(
        canonical: Mapping, *, opportunity_id: str,
        observation_bindings: Iterable[CanonicalObservationBinding],
        ) -> CanonicalOpportunityPublication:
    """Publish one validated canonical state without assembling a context."""
    before = canonical_json(canonical) if isinstance(canonical, Mapping) else None
    observations = _validate_source(canonical, opportunity_id)
    bindings = _binding_map(observations, observation_bindings)
    field_ids = {name: _field_object_id(opportunity_id, name)
                 for name in canonical["resolved"]}
    identity_id = identity_object_id(opportunity_id, canonical["input_digest"])

    # A logical SELF binding avoids a circular dependency between internal
    # reference snapshot IDs and the manifest-derived snapshot identity.
    provisional_specs = _build_specs(
        canonical, observations, bindings, field_ids, identity_id, opportunity_id,
        "canonical-publication-pending")
    object_manifest_digest = _sha(_logical_manifest(provisional_specs))
    snapshot_id = "canonical-publication-" + _sha({
        "owner_domain": OWNER_DOMAIN,
        "owner_contract": OWNER_CONTRACT,
        "contract_version": PUBLICATION_CONTRACT_VERSION,
        "opportunity_id": opportunity_id,
        "authoritative_input_digest": canonical["input_digest"],
        "object_manifest_digest": object_manifest_digest,
    })
    specs = _build_specs(canonical, observations, bindings, field_ids, identity_id,
                         opportunity_id, snapshot_id)
    if _sha(_logical_manifest(specs)) != object_manifest_digest:
        _fail(CanonicalPublicationFailureCode.DIGEST_MISMATCH,
              "canonical object manifest changed during snapshot binding")
    try:
        objects = tuple(create_governed_object(
            owner_domain=OWNER_DOMAIN, owner_contract=OWNER_CONTRACT,
            contract_version=PUBLICATION_CONTRACT_VERSION,
            object_class=spec.object_class, object_id=spec.object_id,
            authority=(AuthorityClass.CONFLICT
                       if spec.object_class == CONFLICT_CLASS
                       else AuthorityClass.OBSERVATION
                       if spec.object_class == OBSERVATION_CLASS
                       else AuthorityClass.CANONICAL_FACT),
            semantic_fields=_semantic_fields(spec.semantics),
            relationships=spec.relationships,
        ) for spec in specs)
        snapshot = create_governed_snapshot(
            owner_domain=OWNER_DOMAIN, owner_contract=OWNER_CONTRACT,
            contract_version=PUBLICATION_CONTRACT_VERSION,
            snapshot_id=snapshot_id, objects=objects)
    except GovernedResolutionError as exc:
        _fail(CanonicalPublicationFailureCode.INVALID_PUBLICATION,
              f"canonical publication snapshot is invalid: {exc.code.value}")

    references = tuple(reference_to(snapshot, item.object_class, item.object_id)
                       for item in snapshot.objects)
    manifest_objects = tuple(CanonicalPublicationManifestObject(
        item.object_class, item.object_id, item.object_digest)
        for item in snapshot.objects)
    manifest_relationships = tuple(sorted((
        CanonicalPublicationManifestRelationship(
            item.object_class, item.object_id, relationship.kind,
            relationship.role, relationship.ordinal, relationship.target)
        for item in snapshot.objects for relationship in item.relationships
    ), key=lambda item: item.order_key))
    manifest = CanonicalOpportunityPublicationManifest(
        OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION,
        SCHEMA_VERSION, opportunity_id, canonical["input_digest"],
        object_manifest_digest, snapshot.snapshot_id, snapshot.snapshot_digest,
        manifest_objects, manifest_relationships)
    publication_id = "canonical-publication-record-" + _sha({
        "opportunity_id": opportunity_id,
        "authoritative_input_digest": canonical["input_digest"],
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_digest": snapshot.snapshot_digest,
    })
    publication = CanonicalOpportunityPublication(
        publication_id, opportunity_id, SCHEMA_VERSION,
        canonical["input_digest"], snapshot, manifest, references)
    if canonical_json(canonical) != before:
        _fail(CanonicalPublicationFailureCode.INVALID_CANONICAL_STATE,
              "canonical publication mutated its source")
    return publication


def validate_canonical_opportunity_publication(
        publication: CanonicalOpportunityPublication,
        ) -> CanonicalOpportunityPublication:
    if not isinstance(publication, CanonicalOpportunityPublication):
        _fail(CanonicalPublicationFailureCode.INVALID_PUBLICATION,
              "CanonicalOpportunityPublication is required")
    manifest, snapshot = publication.manifest, publication.snapshot
    if not isinstance(manifest, CanonicalOpportunityPublicationManifest):
        _fail(CanonicalPublicationFailureCode.INVALID_PUBLICATION,
              "canonical publication manifest is invalid")
    if not isinstance(snapshot, GovernedSnapshot):
        _fail(CanonicalPublicationFailureCode.INVALID_PUBLICATION,
              "canonical publication snapshot is invalid")
    expected_owner = (OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION)
    if ((snapshot.owner_domain, snapshot.owner_contract, snapshot.contract_version)
            != expected_owner
            or (manifest.owner_domain, manifest.owner_contract,
                manifest.contract_version) != expected_owner):
        _fail(CanonicalPublicationFailureCode.VERSION_MISMATCH,
              "canonical publication owner binding is invalid")
    if (publication.source_schema_version != SCHEMA_VERSION
            or manifest.source_schema_version != SCHEMA_VERSION):
        _fail(CanonicalPublicationFailureCode.VERSION_MISMATCH,
              "canonical source schema binding is invalid")
    if (publication.opportunity_id != manifest.opportunity_id
            or publication.authoritative_input_digest
            != manifest.authoritative_input_digest):
        _fail(CanonicalPublicationFailureCode.INVALID_PUBLICATION,
              "canonical publication envelope and manifest differ")
    if not _SOURCE_INPUT_DIGEST.fullmatch(publication.authoritative_input_digest):
        _fail(CanonicalPublicationFailureCode.DIGEST_MISMATCH,
              "canonical authoritative input digest is invalid")
    if (snapshot.snapshot_id, snapshot.snapshot_digest) != (
            manifest.snapshot_id, manifest.snapshot_digest):
        _fail(CanonicalPublicationFailureCode.DIGEST_MISMATCH,
              "canonical snapshot and manifest differ")
    if not _DIGEST.fullmatch(manifest.object_manifest_digest):
        _fail(CanonicalPublicationFailureCode.DIGEST_MISMATCH,
              "canonical object manifest digest is invalid")
    if _sha(_logical_manifest_from_objects(snapshot.objects)) != manifest.object_manifest_digest:
        _fail(CanonicalPublicationFailureCode.DIGEST_MISMATCH,
              "canonical object manifest digest differs from its snapshot")
    expected_snapshot_id = "canonical-publication-" + _sha({
        "owner_domain": OWNER_DOMAIN,
        "owner_contract": OWNER_CONTRACT,
        "contract_version": PUBLICATION_CONTRACT_VERSION,
        "opportunity_id": publication.opportunity_id,
        "authoritative_input_digest": publication.authoritative_input_digest,
        "object_manifest_digest": manifest.object_manifest_digest,
    })
    if snapshot.snapshot_id != expected_snapshot_id:
        _fail(CanonicalPublicationFailureCode.DIGEST_MISMATCH,
              "canonical publication snapshot identity is invalid")
    expected_objects = tuple(CanonicalPublicationManifestObject(
        item.object_class, item.object_id, item.object_digest)
        for item in snapshot.objects)
    if manifest.objects != expected_objects:
        _fail(CanonicalPublicationFailureCode.DIGEST_MISMATCH,
              "canonical object manifest differs from its snapshot")
    allowed = {FIELD_STATE_CLASS, OBSERVATION_CLASS, CONFLICT_CLASS, IDENTITY_CLASS}
    if any(item.object_class not in allowed for item in snapshot.objects):
        _fail(CanonicalPublicationFailureCode.INVALID_PUBLICATION,
              "canonical snapshot contains a foreign object class")
    identity_objects = tuple(item for item in snapshot.objects if item.object_class == IDENTITY_CLASS)
    if len(identity_objects) != 1:
        _fail(CanonicalPublicationFailureCode.INVALID_PUBLICATION,
              "canonical publication must contain exactly one Opportunity identity object")
    if identity_objects[0].object_id != identity_object_id(
            publication.opportunity_id, publication.authoritative_input_digest):
        _fail(CanonicalPublicationFailureCode.DIGEST_MISMATCH,
              "canonical Opportunity identity object identity is invalid")
    expected_relationships = tuple(sorted((
        CanonicalPublicationManifestRelationship(
            item.object_class, item.object_id, relationship.kind,
            relationship.role, relationship.ordinal, relationship.target)
        for item in snapshot.objects for relationship in item.relationships
    ), key=lambda item: item.order_key))
    if manifest.relationships != expected_relationships:
        _fail(CanonicalPublicationFailureCode.BROKEN_RELATIONSHIP,
              "canonical relationship manifest differs from its snapshot")
    expected_references = tuple(reference_to(
        snapshot, item.object_class, item.object_id) for item in snapshot.objects)
    if (not isinstance(publication.references, tuple)
            or publication.references != expected_references):
        _fail(CanonicalPublicationFailureCode.DIGEST_MISMATCH,
              "canonical references differ from the immutable snapshot")
    expected_publication_id = "canonical-publication-record-" + _sha({
        "opportunity_id": publication.opportunity_id,
        "authoritative_input_digest": publication.authoritative_input_digest,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_digest": snapshot.snapshot_digest,
    })
    if publication.publication_id != expected_publication_id:
        _fail(CanonicalPublicationFailureCode.DIGEST_MISMATCH,
              "canonical publication identity is invalid")
    object_keys = {(item.object_class, item.object_id) for item in snapshot.objects}
    for item in snapshot.objects:
        if not item.semantic_fields:
            _fail(CanonicalPublicationFailureCode.MISSING_SEMANTIC_CONTENT,
                  f"canonical object {item.object_id} has no semantic content")
        for relationship in item.relationships:
            target = relationship.target
            if target.owner_domain == OWNER_DOMAIN and (
                    target.owner_contract != OWNER_CONTRACT
                    or target.contract_version != PUBLICATION_CONTRACT_VERSION
                    or (target.object_class, target.object_id) not in object_keys):
                _fail(CanonicalPublicationFailureCode.BROKEN_RELATIONSHIP,
                      f"canonical relationship from {item.object_id} does not close")
    return publication


__all__ = [
    "CONFLICT_CLASS", "FIELD_STATE_CLASS", "IDENTITY_CLASS", "OBSERVATION_CLASS",
    "OWNER_CONTRACT", "OWNER_DOMAIN", "PUBLICATION_CONTRACT_VERSION",
    "CanonicalObservationBinding", "CanonicalOpportunityPublication",
    "CanonicalOpportunityPublicationError",
    "CanonicalOpportunityPublicationManifest",
    "CanonicalPublicationFailureCode", "CanonicalPublicationManifestObject",
    "CanonicalPublicationManifestRelationship", "identity_object_id",
    "publish_canonical_opportunity", "validate_canonical_opportunity_publication",
]
