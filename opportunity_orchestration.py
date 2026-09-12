"""Deterministic assembly of owner publications for one opportunity operation."""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Iterable

from decision_analyst import DecisionAnalysis
from decision_intelligence import EvidenceSupport, SupportedEntityType
from governed_reference_resolution import (
    AuthorityClass, GovernedObject, GovernedObjectReference,
    GovernedResolutionError, GovernedSnapshot, RelationshipKind,
    ResolutionContext, ResolutionRequest, create_resolution_context,
    resolve_governed_reference,
)
from opportunity_intelligence_publication import OpportunitySupportBinding


ORCHESTRATION_CONTRACT_VERSION = "1.0.0"
OPPORTUNITY_INTELLIGENCE_OPERATION = "opportunity-intelligence"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_OWNER_DIGEST = re.compile(r"^(?:[A-Za-z][A-Za-z0-9_.-]*_)?[0-9a-f]{64}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class OrchestrationFailureCode(str, Enum):
    INVALID_OPERATION = "INVALID_OPERATION"
    INVALID_PUBLICATION = "INVALID_PUBLICATION"
    MISSING_PUBLICATION = "MISSING_PUBLICATION"
    DUPLICATE_IDENTITY = "DUPLICATE_IDENTITY"
    OWNER_MISMATCH = "OWNER_MISMATCH"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    INCOMPATIBLE_PUBLICATION = "INCOMPATIBLE_PUBLICATION"
    INCOMPATIBLE_SNAPSHOT = "INCOMPATIBLE_SNAPSHOT"
    MISSING_SUPPORT = "MISSING_SUPPORT"
    AMBIGUOUS_SUPPORT = "AMBIGUOUS_SUPPORT"
    INCOMPLETE_RELATIONSHIP_CLOSURE = "INCOMPLETE_RELATIONSHIP_CLOSURE"
    INVALID_MANIFEST = "INVALID_MANIFEST"


class OpportunityOrchestrationError(ValueError):
    """Controlled fail-closed orchestration failure."""

    def __init__(self, code: OrchestrationFailureCode, message: str) -> None:
        self.code = code
        super().__init__(message)


def _fail(code: OrchestrationFailureCode, message: str):
    raise OpportunityOrchestrationError(code, message)


def _canonical(value):
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {item.name: _canonical(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=str)}
    return value


def _json(value) -> str:
    try:
        return json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        _fail(OrchestrationFailureCode.INVALID_MANIFEST,
              f"orchestration content is not canonically serializable: {exc}")


def _sha(value) -> str:
    return sha256(_json(value).encode("utf-8")).hexdigest()


def _identifier(value: object, name: str) -> str:
    if (not isinstance(value, str) or not value or value != value.strip()
            or any(character.isspace() for character in value)):
        _fail(OrchestrationFailureCode.INVALID_OPERATION,
              f"{name} must be a stable non-whitespace identifier")
    return value


def _version(value: object, name: str) -> str:
    if not isinstance(value, str) or not _VERSION.fullmatch(value):
        _fail(OrchestrationFailureCode.VERSION_MISMATCH,
              f"{name} must be an exact semantic version")
    return value


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        _fail(OrchestrationFailureCode.DIGEST_MISMATCH,
              f"{name} must be a lowercase SHA-256 digest")
    return value


def _owner_digest(value: object, name: str) -> str:
    if not isinstance(value, str) or not _OWNER_DIGEST.fullmatch(value):
        _fail(OrchestrationFailureCode.DIGEST_MISMATCH,
              f"{name} must be an owner-declared SHA-256 digest")
    return value


def _reference_key(value: GovernedObjectReference) -> tuple[str, ...]:
    return (*value.identity_key, value.snapshot_digest, value.object_digest)


def _support_key(value: EvidenceSupport) -> tuple[str, str, tuple[str, ...]]:
    return value.entity_type.value, value.entity_id, value.evidence_ids


@dataclass(frozen=True, slots=True)
class PublicationAdmissionPolicy:
    role: str
    owner_domain: str
    owner_contract: str
    contract_version: str
    object_classes: tuple[str, ...]
    required: bool = True

    def __post_init__(self) -> None:
        for name in ("role", "owner_domain", "owner_contract"):
            _identifier(getattr(self, name), name)
        _version(self.contract_version, "contract_version")
        if (not isinstance(self.object_classes, tuple) or not self.object_classes
                or any(not isinstance(item, str) for item in self.object_classes)):
            _fail(OrchestrationFailureCode.INVALID_OPERATION,
                  "publication policy requires immutable object classes")
        expected = tuple(sorted(self.object_classes))
        if self.object_classes != expected or len(expected) != len(set(expected)):
            _fail(OrchestrationFailureCode.DUPLICATE_IDENTITY,
                  "publication policy object classes must be unique and ordered")
        for item in self.object_classes:
            _identifier(item, "object_class")
        if type(self.required) is not bool:
            _fail(OrchestrationFailureCode.INVALID_OPERATION,
                  "publication policy required flag must be boolean")

    @property
    def order_key(self) -> tuple[str, ...]:
        return self.role, self.owner_domain, self.owner_contract, self.contract_version


@dataclass(frozen=True, slots=True)
class SupportReferencePolicy:
    entity_type: SupportedEntityType
    publication_role: str
    object_classes: tuple[str, ...]
    allowed_authorities: tuple[AuthorityClass, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.entity_type, SupportedEntityType):
            _fail(OrchestrationFailureCode.INVALID_OPERATION,
                  "support policy entity type is invalid")
        _identifier(self.publication_role, "publication_role")
        if (not isinstance(self.object_classes, tuple) or not self.object_classes
                or self.object_classes != tuple(sorted(self.object_classes))
                or len(self.object_classes) != len(set(self.object_classes))):
            _fail(OrchestrationFailureCode.INVALID_OPERATION,
                  "support policy object classes must be unique and ordered")
        if (not isinstance(self.allowed_authorities, tuple)
                or not self.allowed_authorities
                or any(not isinstance(item, AuthorityClass)
                       for item in self.allowed_authorities)
                or self.allowed_authorities != tuple(sorted(
                    self.allowed_authorities, key=lambda item: item.value))
                or len(self.allowed_authorities) != len(set(self.allowed_authorities))):
            _fail(OrchestrationFailureCode.INVALID_OPERATION,
                  "support policy authorities must be unique and ordered")

    @property
    def order_key(self) -> tuple[str, str]:
        return self.entity_type.value, self.publication_role


@dataclass(frozen=True, slots=True)
class PublicationCompatibilityPolicy:
    source_role: str
    dependent_role: str
    rule_id: str
    rule_version: str

    def __post_init__(self) -> None:
        for name in ("source_role", "dependent_role", "rule_id"):
            _identifier(getattr(self, name), name)
        if self.source_role == self.dependent_role:
            _fail(OrchestrationFailureCode.INVALID_OPERATION,
                  "compatibility policy requires distinct publication roles")
        _version(self.rule_version, "compatibility rule_version")

    @property
    def order_key(self) -> tuple[str, ...]:
        return (self.source_role, self.dependent_role,
                self.rule_id, self.rule_version)


@dataclass(frozen=True, slots=True)
class OpportunityOperationContract:
    operation_type: str
    contract_version: str
    publication_policies: tuple[PublicationAdmissionPolicy, ...]
    support_policies: tuple[SupportReferencePolicy, ...]
    compatibility_policies: tuple[PublicationCompatibilityPolicy, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.operation_type, "operation_type")
        _version(self.contract_version, "orchestration contract_version")
        if self.contract_version != ORCHESTRATION_CONTRACT_VERSION:
            _fail(OrchestrationFailureCode.VERSION_MISMATCH,
                  "unsupported orchestration contract version")
        if (not isinstance(self.publication_policies, tuple)
                or any(not isinstance(item, PublicationAdmissionPolicy)
                       for item in self.publication_policies)
                or self.publication_policies != tuple(sorted(
                    self.publication_policies, key=lambda item: item.order_key))):
            _fail(OrchestrationFailureCode.INVALID_OPERATION,
                  "publication policies must be immutable and ordered")
        roles = tuple(item.role for item in self.publication_policies)
        if len(roles) != len(set(roles)):
            _fail(OrchestrationFailureCode.DUPLICATE_IDENTITY,
                  "publication policy roles must be unique")
        if (not isinstance(self.support_policies, tuple)
                or any(not isinstance(item, SupportReferencePolicy)
                       for item in self.support_policies)
                or self.support_policies != tuple(sorted(
                    self.support_policies, key=lambda item: item.order_key))):
            _fail(OrchestrationFailureCode.INVALID_OPERATION,
                  "support policies must be immutable and ordered")
        entity_types = tuple(item.entity_type for item in self.support_policies)
        if len(entity_types) != len(set(entity_types)):
            _fail(OrchestrationFailureCode.DUPLICATE_IDENTITY,
                  "each supported entity type requires one exact policy")
        if any(item.publication_role not in roles for item in self.support_policies):
            _fail(OrchestrationFailureCode.INVALID_OPERATION,
                  "support policy names an undeclared publication role")
        if (not isinstance(self.compatibility_policies, tuple)
                or any(not isinstance(item, PublicationCompatibilityPolicy)
                       for item in self.compatibility_policies)
                or self.compatibility_policies != tuple(sorted(
                    self.compatibility_policies, key=lambda item: item.order_key))
                or len(self.compatibility_policies) != len(set(
                    item.order_key for item in self.compatibility_policies))):
            _fail(OrchestrationFailureCode.INVALID_OPERATION,
                  "compatibility policies must be unique and ordered")
        if any(item.source_role not in roles or item.dependent_role not in roles
               for item in self.compatibility_policies):
            _fail(OrchestrationFailureCode.INVALID_OPERATION,
                  "compatibility policy names an undeclared publication role")
        required_pairs = {tuple(sorted((roles[left], roles[right])))
                          for left in range(len(roles))
                          for right in range(left + 1, len(roles))}
        policy_pairs = {tuple(sorted((item.source_role, item.dependent_role)))
                        for item in self.compatibility_policies}
        if policy_pairs != required_pairs:
            _fail(OrchestrationFailureCode.INVALID_OPERATION,
                  "compatibility policies must cover every publication-role pair")


@dataclass(frozen=True, slots=True)
class AdmittedOwnerPublication:
    role: str
    publication_id: str
    publication_digest: str
    scope_id: str
    authoritative_input_identity: str
    authoritative_input_digest: str
    snapshot: GovernedSnapshot
    references: tuple[GovernedObjectReference, ...]

    def __post_init__(self) -> None:
        for name in ("role", "publication_id", "scope_id",
                     "authoritative_input_identity"):
            _identifier(getattr(self, name), name)
        _digest(self.publication_digest, "publication_digest")
        _owner_digest(self.authoritative_input_digest, "authoritative_input_digest")
        if not isinstance(self.snapshot, GovernedSnapshot):
            _fail(OrchestrationFailureCode.INVALID_PUBLICATION,
                  "admission requires an immutable governed snapshot")
        if (not isinstance(self.references, tuple)
                or any(not isinstance(item, GovernedObjectReference)
                       for item in self.references)):
            _fail(OrchestrationFailureCode.INVALID_PUBLICATION,
                  "admission requires immutable governed references")
        expected = tuple(sorted(self.references, key=_reference_key))
        if self.references != expected or len(expected) != len(set(expected)):
            _fail(OrchestrationFailureCode.DUPLICATE_IDENTITY,
                  "publication references must be unique and ordered")
        object_keys = {(item.object_class, item.object_id): item
                       for item in self.snapshot.objects}
        if len(self.references) != len(object_keys):
            _fail(OrchestrationFailureCode.INVALID_PUBLICATION,
                  "publication references must exactly cover snapshot membership")
        for reference in self.references:
            item = object_keys.get((reference.object_class, reference.object_id))
            if (item is None
                    or (reference.owner_domain, reference.owner_contract,
                        reference.contract_version, reference.snapshot_id,
                        reference.snapshot_digest, reference.object_digest) != (
                        self.snapshot.owner_domain, self.snapshot.owner_contract,
                        self.snapshot.contract_version, self.snapshot.snapshot_id,
                        self.snapshot.snapshot_digest, item.object_digest)):
                _fail(OrchestrationFailureCode.DIGEST_MISMATCH,
                      "publication reference does not match snapshot membership")

    @property
    def order_key(self) -> tuple[str, ...]:
        return (self.role, self.snapshot.owner_domain, self.snapshot.owner_contract,
                self.snapshot.contract_version, self.snapshot.snapshot_id,
                self.snapshot.snapshot_digest)


@dataclass(frozen=True, slots=True)
class CompatibilityDeclaration:
    source_role: str
    dependent_role: str
    source_snapshot_id: str
    source_snapshot_digest: str
    dependent_snapshot_id: str
    dependent_snapshot_digest: str
    rule_id: str
    rule_version: str

    def __post_init__(self) -> None:
        for name in ("source_role", "dependent_role", "source_snapshot_id",
                     "dependent_snapshot_id", "rule_id"):
            _identifier(getattr(self, name), name)
        _digest(self.source_snapshot_digest, "source_snapshot_digest")
        _digest(self.dependent_snapshot_digest, "dependent_snapshot_digest")
        _version(self.rule_version, "compatibility rule_version")

    @property
    def order_key(self) -> tuple[str, ...]:
        return (self.source_role, self.dependent_role, self.rule_id,
                self.rule_version, self.source_snapshot_id,
                self.dependent_snapshot_id)


@dataclass(frozen=True, slots=True)
class OrchestrationAdmissionRecord:
    role: str
    publication_id: str
    publication_digest: str
    owner_domain: str
    owner_contract: str
    contract_version: str
    snapshot_id: str
    snapshot_digest: str
    authoritative_input_identity: str
    authoritative_input_digest: str

    @property
    def order_key(self) -> tuple[str, ...]:
        return (self.role, self.owner_domain, self.owner_contract,
                self.contract_version, self.snapshot_id, self.snapshot_digest)


@dataclass(frozen=True, slots=True)
class OpportunityOrchestrationManifest:
    manifest_id: str
    contract_version: str
    operation_type: str
    operation_id: str
    scope_id: str
    analysis_id: str
    evidence_support_digest: str
    admissions: tuple[OrchestrationAdmissionRecord, ...]
    compatibility_declarations: tuple[CompatibilityDeclaration, ...]
    required_roles: tuple[str, ...]
    satisfied_roles: tuple[str, ...]
    resolution_context_id: str
    resolution_context_digest: str
    support_bindings_digest: str
    manifest_digest: str

    def __post_init__(self) -> None:
        validate_opportunity_orchestration_manifest(self)

    def to_dict(self) -> dict:
        return _canonical(self)

    def to_json(self) -> str:
        return _json(self)


@dataclass(frozen=True, slots=True)
class OpportunityOrchestration:
    operation_id: str
    scope_id: str
    contract: OpportunityOperationContract
    admitted_publications: tuple[AdmittedOwnerPublication, ...]
    resolution_context: ResolutionContext
    evidence_support: tuple[EvidenceSupport, ...]
    support_bindings: tuple[OpportunitySupportBinding, ...]
    manifest: OpportunityOrchestrationManifest

    def __post_init__(self) -> None:
        validate_opportunity_orchestration(self)

    def to_dict(self) -> dict:
        return _canonical(self)

    def to_json(self) -> str:
        return _json(self)


def admit_owner_publication(
        publication, *, role: str, scope_id: str,
        authoritative_input_identity: str | None = None,
        ) -> AdmittedOwnerPublication:
    """Validate and admit an existing owner publication without recreating it."""
    _identifier(role, "role")
    _identifier(scope_id, "scope_id")
    snapshot = getattr(publication, "snapshot", None)
    references = getattr(publication, "references", None)
    publication_id = getattr(publication, "publication_id", None)
    publication_digest = getattr(publication, "digest", None)
    if callable(publication_digest):
        publication_digest = publication_digest()
    if not isinstance(snapshot, GovernedSnapshot) or not isinstance(references, tuple):
        _fail(OrchestrationFailureCode.INVALID_PUBLICATION,
              "owner publication does not expose an immutable snapshot and references")
    if not isinstance(publication_id, str) or not isinstance(publication_digest, str):
        _fail(OrchestrationFailureCode.INVALID_PUBLICATION,
              "owner publication does not expose immutable publication identity")
    if publication_digest != _sha(publication):
        _fail(OrchestrationFailureCode.DIGEST_MISMATCH,
              "owner publication digest does not reproduce")
    input_digest = getattr(publication, "authoritative_input_digest", None)
    if not isinstance(input_digest, str):
        manifest = getattr(publication, "manifest", None)
        input_digest = getattr(manifest, "authoritative_input_digest", None)
    input_identity = authoritative_input_identity or scope_id
    return AdmittedOwnerPublication(
        role, publication_id, publication_digest, scope_id, input_identity,
        input_digest, snapshot, references)


def _admission_records(
        values: tuple[AdmittedOwnerPublication, ...],
        ) -> tuple[OrchestrationAdmissionRecord, ...]:
    return tuple(OrchestrationAdmissionRecord(
        item.role, item.publication_id, item.publication_digest,
        item.snapshot.owner_domain, item.snapshot.owner_contract,
        item.snapshot.contract_version, item.snapshot.snapshot_id,
        item.snapshot.snapshot_digest, item.authoritative_input_identity,
        item.authoritative_input_digest) for item in values)


def _validate_admissions(
        contract: OpportunityOperationContract, scope_id: str,
        publications: tuple[AdmittedOwnerPublication, ...],
        ) -> dict[str, AdmittedOwnerPublication]:
    if (not isinstance(publications, tuple)
            or any(not isinstance(item, AdmittedOwnerPublication)
                   for item in publications)):
        _fail(OrchestrationFailureCode.INVALID_PUBLICATION,
              "admitted publications must be an immutable tuple")
    expected = tuple(sorted(publications, key=lambda item: item.order_key))
    if publications != expected:
        _fail(OrchestrationFailureCode.INVALID_PUBLICATION,
              "admitted publications are not canonically ordered")
    by_role = {item.role: item for item in publications}
    if len(by_role) != len(publications):
        _fail(OrchestrationFailureCode.DUPLICATE_IDENTITY,
              "publication roles must be unique within an operation")
    policies = {item.role: item for item in contract.publication_policies}
    required = {item.role for item in contract.publication_policies if item.required}
    missing = sorted(required - set(by_role))
    if missing:
        _fail(OrchestrationFailureCode.MISSING_PUBLICATION,
              f"required publication roles are absent: {missing}")
    extra = sorted(set(by_role) - set(policies))
    if extra:
        _fail(OrchestrationFailureCode.INVALID_PUBLICATION,
              f"undeclared publication roles were supplied: {extra}")
    snapshot_keys = []
    identity_digests: dict[tuple[str, str], tuple[str, str]] = {}
    for role, publication in by_role.items():
        policy = policies[role]
        snapshot = publication.snapshot
        if publication.scope_id != scope_id:
            _fail(OrchestrationFailureCode.INCOMPATIBLE_PUBLICATION,
                  f"publication {role} belongs to another operation scope")
        if (snapshot.owner_domain, snapshot.owner_contract,
                snapshot.contract_version) != (
                policy.owner_domain, policy.owner_contract,
                policy.contract_version):
            _fail(OrchestrationFailureCode.OWNER_MISMATCH,
                  f"publication {role} owner contract does not match policy")
        classes = {item.object_class for item in snapshot.objects}
        if not classes or not classes <= set(policy.object_classes):
            _fail(OrchestrationFailureCode.INVALID_PUBLICATION,
                  f"publication {role} exposes unsupported object classes")
        snapshot_keys.append((snapshot.owner_domain, snapshot.owner_contract,
                              snapshot.snapshot_id))
        input_key = (publication.authoritative_input_identity,
                     snapshot.owner_domain)
        prior = identity_digests.get(input_key)
        current = (publication.authoritative_input_digest, snapshot.snapshot_id)
        if prior is not None and prior != current:
            _fail(OrchestrationFailureCode.INCOMPATIBLE_SNAPSHOT,
                  f"publication {role} conflicts with an admitted owner snapshot")
        identity_digests[input_key] = current
    if len(snapshot_keys) != len(set(snapshot_keys)):
        _fail(OrchestrationFailureCode.DUPLICATE_IDENTITY,
              "duplicate snapshot identities are not admissible")
    return by_role


def _validate_compatibility(
        contract: OpportunityOperationContract,
        publications: dict[str, AdmittedOwnerPublication],
        declarations: tuple[CompatibilityDeclaration, ...],
        ) -> None:
    if (not isinstance(declarations, tuple)
            or any(not isinstance(item, CompatibilityDeclaration)
                   for item in declarations)
            or declarations != tuple(sorted(
                declarations, key=lambda item: item.order_key))):
        _fail(OrchestrationFailureCode.INCOMPATIBLE_PUBLICATION,
              "compatibility declarations must be immutable and ordered")
    if len(declarations) != len(set(item.order_key for item in declarations)):
        _fail(OrchestrationFailureCode.DUPLICATE_IDENTITY,
              "compatibility declarations contain duplicates")
    expected = {(item.source_role, item.dependent_role,
                 item.rule_id, item.rule_version)
                for item in contract.compatibility_policies}
    actual = {(item.source_role, item.dependent_role,
               item.rule_id, item.rule_version) for item in declarations}
    if actual != expected:
        _fail(OrchestrationFailureCode.INCOMPATIBLE_PUBLICATION,
              "compatibility declarations do not match the operation contract")
    for item in declarations:
        source = publications.get(item.source_role)
        dependent = publications.get(item.dependent_role)
        if source is None or dependent is None:
            _fail(OrchestrationFailureCode.INCOMPATIBLE_PUBLICATION,
                  "compatibility declaration names an unadmitted role")
        if (item.source_snapshot_id, item.source_snapshot_digest) != (
                source.snapshot.snapshot_id, source.snapshot.snapshot_digest):
            _fail(OrchestrationFailureCode.INCOMPATIBLE_SNAPSHOT,
                  "compatibility source snapshot binding is invalid")
        if (item.dependent_snapshot_id, item.dependent_snapshot_digest) != (
                dependent.snapshot.snapshot_id, dependent.snapshot.snapshot_digest):
            _fail(OrchestrationFailureCode.INCOMPATIBLE_SNAPSHOT,
                  "compatibility dependent snapshot binding is invalid")


def _object_index(context: ResolutionContext) -> dict[
        tuple[str, str, str, str, str, str], GovernedObject]:
    result = {}
    for snapshot in context.snapshots:
        for item in snapshot.objects:
            key = (snapshot.owner_domain, snapshot.owner_contract,
                   snapshot.contract_version, snapshot.snapshot_id,
                   item.object_class, item.object_id)
            if key in result:
                _fail(OrchestrationFailureCode.DUPLICATE_IDENTITY,
                      "context contains duplicate governed object identity")
            result[key] = item
    return result


def _reference_object(reference: GovernedObjectReference,
                      index: dict[tuple[str, str, str, str, str, str], GovernedObject]
                      ) -> GovernedObject:
    key = (reference.owner_domain, reference.owner_contract,
           reference.contract_version, reference.snapshot_id,
           reference.object_class, reference.object_id)
    item = index.get(key)
    if (item is None or item.object_digest != reference.object_digest):
        _fail(OrchestrationFailureCode.INCOMPLETE_RELATIONSHIP_CLOSURE,
              f"reference {reference.object_id} is outside the admitted snapshots")
    return item


def _assemble_bindings(
        analysis: DecisionAnalysis, contract: OpportunityOperationContract,
        publications: dict[str, AdmittedOwnerPublication],
        context: ResolutionContext,
        ) -> tuple[OpportunitySupportBinding, ...]:
    if not isinstance(analysis, DecisionAnalysis):
        _fail(OrchestrationFailureCode.INVALID_OPERATION,
              "Opportunity Intelligence DecisionAnalysis is required")
    policies = {item.entity_type: item for item in contract.support_policies}
    index = _object_index(context)
    bindings = []
    for support in sorted(analysis.evidence_used, key=_support_key):
        policy = policies.get(support.entity_type)
        if policy is None:
            _fail(OrchestrationFailureCode.MISSING_SUPPORT,
                  f"no support policy exists for {support.entity_type.value}")
        publication = publications[policy.publication_role]
        matches = []
        for reference in publication.references:
            if (reference.object_id == support.entity_id
                    and reference.object_class in policy.object_classes):
                item = _reference_object(reference, index)
                if item.authority in policy.allowed_authorities:
                    matches.append((reference, item))
        if not matches:
            _fail(OrchestrationFailureCode.MISSING_SUPPORT,
                  f"support {support.entity_type.value}/{support.entity_id} has no exact target")
        if len(matches) != 1:
            _fail(OrchestrationFailureCode.AMBIGUOUS_SUPPORT,
                  f"support {support.entity_type.value}/{support.entity_id} is ambiguous")
        entity_reference, entity = matches[0]
        evidence = tuple(sorted((
            relationship.target for relationship in entity.relationships
            if relationship.kind == RelationshipKind.EVIDENCE_SUPPORT
            and relationship.target.object_id in support.evidence_ids
        ), key=_reference_key))
        if (len(evidence) != len(support.evidence_ids)
                or {item.object_id for item in evidence} != set(support.evidence_ids)):
            _fail(OrchestrationFailureCode.INCOMPLETE_RELATIONSHIP_CLOSURE,
                  f"support {support.entity_id} lacks exact evidence relationships")
        for reference in (entity_reference, *evidence):
            target = _reference_object(reference, index)
            try:
                resolve_governed_reference(ResolutionRequest(
                    reference, context.context_id, context.context_digest,
                    target.authority), context)
            except GovernedResolutionError as exc:
                _fail(OrchestrationFailureCode.INCOMPLETE_RELATIONSHIP_CLOSURE,
                      f"support {support.entity_id} does not close: {exc.code.value}")
        bindings.append(OpportunitySupportBinding(
            support, entity_reference, evidence))
    result = tuple(bindings)
    if len(result) != len(analysis.evidence_used):
        _fail(OrchestrationFailureCode.MISSING_SUPPORT,
              "support bindings do not completely cover analysis evidence_used")
    return result


def _context_seed(operation_id: str, scope_id: str,
                  contract: OpportunityOperationContract,
                  admissions: tuple[OrchestrationAdmissionRecord, ...],
                  compatibility: tuple[CompatibilityDeclaration, ...]) -> dict:
    return {
        "operation_id": operation_id,
        "scope_id": scope_id,
        "operation_type": contract.operation_type,
        "contract_version": contract.contract_version,
        "admissions": admissions,
        "compatibility_declarations": compatibility,
    }


def _manifest_payload(
        *, contract_version: str, operation_type: str, operation_id: str,
        scope_id: str, analysis_id: str, evidence_support_digest: str,
        admissions: tuple[OrchestrationAdmissionRecord, ...],
        compatibility_declarations: tuple[CompatibilityDeclaration, ...],
        required_roles: tuple[str, ...], satisfied_roles: tuple[str, ...],
        resolution_context_id: str, resolution_context_digest: str,
        support_bindings_digest: str) -> dict:
    return {
        "contract_version": contract_version,
        "operation_type": operation_type,
        "operation_id": operation_id,
        "scope_id": scope_id,
        "analysis_id": analysis_id,
        "evidence_support_digest": evidence_support_digest,
        "admissions": admissions,
        "compatibility_declarations": compatibility_declarations,
        "required_roles": required_roles,
        "satisfied_roles": satisfied_roles,
        "resolution_context_id": resolution_context_id,
        "resolution_context_digest": resolution_context_digest,
        "support_bindings_digest": support_bindings_digest,
    }


def orchestrate_opportunity_intelligence(
        analysis: DecisionAnalysis, *, operation_id: str, scope_id: str,
        contract: OpportunityOperationContract,
        admitted_publications: Iterable[AdmittedOwnerPublication],
        compatibility_declarations: Iterable[CompatibilityDeclaration] = (),
        ) -> OpportunityOrchestration:
    """Assemble one bounded immutable context and exact support bindings."""
    _identifier(operation_id, "operation_id")
    _identifier(scope_id, "scope_id")
    if (not isinstance(contract, OpportunityOperationContract)
            or contract.operation_type != OPPORTUNITY_INTELLIGENCE_OPERATION):
        _fail(OrchestrationFailureCode.INVALID_OPERATION,
              "supported Opportunity Intelligence operation contract is required")
    publications = tuple(sorted(tuple(admitted_publications),
                                key=lambda item: item.order_key))
    declarations = tuple(sorted(tuple(compatibility_declarations),
                                key=lambda item: item.order_key))
    publication_map = _validate_admissions(contract, scope_id, publications)
    _validate_compatibility(contract, publication_map, declarations)
    admissions = _admission_records(publications)
    context_id = "opportunity-context-" + _sha(_context_seed(
        operation_id, scope_id, contract, admissions, declarations))
    try:
        context = create_resolution_context(
            context_id=context_id, context_version=contract.contract_version,
            snapshots=tuple(item.snapshot for item in publications))
    except GovernedResolutionError as exc:
        _fail(OrchestrationFailureCode.INCOMPATIBLE_SNAPSHOT,
              f"bounded resolution context is invalid: {exc.code.value}")
    bindings = _assemble_bindings(
        analysis, contract, publication_map, context)
    evidence_support = tuple(sorted(analysis.evidence_used, key=_support_key))
    evidence_support_digest = _sha(evidence_support)
    bindings_digest = _sha(bindings)
    required_roles = tuple(sorted(item.role for item in contract.publication_policies
                                  if item.required))
    satisfied_roles = tuple(sorted(publication_map))
    payload = _manifest_payload(
        contract_version=contract.contract_version,
        operation_type=contract.operation_type, operation_id=operation_id,
        scope_id=scope_id, analysis_id=analysis.analysis_id,
        evidence_support_digest=evidence_support_digest, admissions=admissions,
        compatibility_declarations=declarations,
        required_roles=required_roles, satisfied_roles=satisfied_roles,
        resolution_context_id=context.context_id,
        resolution_context_digest=context.context_digest,
        support_bindings_digest=bindings_digest)
    manifest_digest = _sha(payload)
    manifest = OpportunityOrchestrationManifest(
        "opportunity-orchestration-" + manifest_digest,
        contract.contract_version, contract.operation_type, operation_id,
        scope_id, analysis.analysis_id, evidence_support_digest,
        admissions, declarations, required_roles, satisfied_roles,
        context.context_id, context.context_digest, bindings_digest,
        manifest_digest)
    return OpportunityOrchestration(
        operation_id, scope_id, contract, publications, context,
        evidence_support, bindings,
        manifest)


def validate_opportunity_orchestration_manifest(
        manifest: OpportunityOrchestrationManifest,
        ) -> OpportunityOrchestrationManifest:
    if not isinstance(manifest, OpportunityOrchestrationManifest):
        _fail(OrchestrationFailureCode.INVALID_MANIFEST,
              "OpportunityOrchestrationManifest is required")
    _version(manifest.contract_version, "manifest contract_version")
    if manifest.contract_version != ORCHESTRATION_CONTRACT_VERSION:
        _fail(OrchestrationFailureCode.VERSION_MISMATCH,
              "manifest contract version is unsupported")
    for name in ("operation_type", "operation_id", "scope_id", "analysis_id",
                 "resolution_context_id"):
        _identifier(getattr(manifest, name), name)
    for name in ("evidence_support_digest", "resolution_context_digest",
                 "support_bindings_digest", "manifest_digest"):
        _digest(getattr(manifest, name), name)
    if (not isinstance(manifest.admissions, tuple)
            or any(not isinstance(item, OrchestrationAdmissionRecord)
                   for item in manifest.admissions)
            or manifest.admissions != tuple(sorted(
                manifest.admissions, key=lambda item: item.order_key))):
        _fail(OrchestrationFailureCode.INVALID_MANIFEST,
              "manifest admissions are not immutable and ordered")
    if (not isinstance(manifest.compatibility_declarations, tuple)
            or manifest.compatibility_declarations != tuple(sorted(
                manifest.compatibility_declarations,
                key=lambda item: item.order_key))):
        _fail(OrchestrationFailureCode.INVALID_MANIFEST,
              "manifest compatibility declarations are invalid")
    if (manifest.required_roles != tuple(sorted(manifest.required_roles))
            or manifest.satisfied_roles != tuple(sorted(manifest.satisfied_roles))
            or not set(manifest.required_roles) <= set(manifest.satisfied_roles)):
        _fail(OrchestrationFailureCode.MISSING_PUBLICATION,
              "manifest publication-role coverage is incomplete")
    payload = _manifest_payload(
        contract_version=manifest.contract_version,
        operation_type=manifest.operation_type,
        operation_id=manifest.operation_id, scope_id=manifest.scope_id,
        analysis_id=manifest.analysis_id,
        evidence_support_digest=manifest.evidence_support_digest,
        admissions=manifest.admissions,
        compatibility_declarations=manifest.compatibility_declarations,
        required_roles=manifest.required_roles,
        satisfied_roles=manifest.satisfied_roles,
        resolution_context_id=manifest.resolution_context_id,
        resolution_context_digest=manifest.resolution_context_digest,
        support_bindings_digest=manifest.support_bindings_digest)
    expected = _sha(payload)
    if (manifest.manifest_digest != expected
            or manifest.manifest_id != "opportunity-orchestration-" + expected):
        _fail(OrchestrationFailureCode.DIGEST_MISMATCH,
              "orchestration manifest identity or digest is invalid")
    return manifest


def validate_opportunity_orchestration(
        value: OpportunityOrchestration,
        ) -> OpportunityOrchestration:
    if not isinstance(value, OpportunityOrchestration):
        _fail(OrchestrationFailureCode.INVALID_MANIFEST,
              "OpportunityOrchestration is required")
    validate_opportunity_orchestration_manifest(value.manifest)
    if (value.operation_id != value.manifest.operation_id
            or value.scope_id != value.manifest.scope_id
            or value.contract.contract_version != value.manifest.contract_version
            or value.contract.operation_type != value.manifest.operation_type):
        _fail(OrchestrationFailureCode.INVALID_MANIFEST,
              "orchestration envelope and manifest differ")
    publication_map = _validate_admissions(
        value.contract, value.scope_id, value.admitted_publications)
    _validate_compatibility(
        value.contract, publication_map,
        value.manifest.compatibility_declarations)
    admissions = _admission_records(value.admitted_publications)
    if admissions != value.manifest.admissions:
        _fail(OrchestrationFailureCode.INVALID_MANIFEST,
              "orchestration admissions differ from the manifest")
    expected_context_id = "opportunity-context-" + _sha(_context_seed(
        value.operation_id, value.scope_id, value.contract, admissions,
        value.manifest.compatibility_declarations))
    if value.resolution_context.context_id != expected_context_id:
        _fail(OrchestrationFailureCode.DIGEST_MISMATCH,
              "orchestration context identity is not reproducible")
    if (not isinstance(value.resolution_context, ResolutionContext)
            or (value.resolution_context.context_id,
                value.resolution_context.context_digest) != (
                value.manifest.resolution_context_id,
                value.manifest.resolution_context_digest)
            or value.resolution_context.snapshots != tuple(sorted(
                (item.snapshot for item in value.admitted_publications),
                key=lambda item: (item.owner_domain, item.owner_contract,
                                  item.snapshot_id)))):
        _fail(OrchestrationFailureCode.INCOMPATIBLE_SNAPSHOT,
              "orchestration context differs from admitted snapshots")
    if (not isinstance(value.support_bindings, tuple)
            or value.support_bindings != tuple(sorted(
                value.support_bindings, key=lambda item: _support_key(item.support)))
            or _sha(value.support_bindings) != value.manifest.support_bindings_digest):
        _fail(OrchestrationFailureCode.DIGEST_MISMATCH,
              "orchestration support bindings are invalid")
    if (not isinstance(value.evidence_support, tuple)
            or value.evidence_support != tuple(sorted(
                value.evidence_support, key=_support_key))
            or len(value.evidence_support) != len(set(value.evidence_support))
            or _sha(value.evidence_support) != value.manifest.evidence_support_digest
            or tuple(item.support for item in value.support_bindings)
            != value.evidence_support):
        _fail(OrchestrationFailureCode.MISSING_SUPPORT,
              "orchestration evidence support coverage is invalid")
    return value


__all__ = [
    "ORCHESTRATION_CONTRACT_VERSION", "OPPORTUNITY_INTELLIGENCE_OPERATION",
    "AdmittedOwnerPublication", "CompatibilityDeclaration",
    "OpportunityOperationContract", "OpportunityOrchestration",
    "OpportunityOrchestrationError", "OpportunityOrchestrationManifest",
    "OrchestrationAdmissionRecord", "OrchestrationFailureCode",
    "PublicationAdmissionPolicy", "PublicationCompatibilityPolicy",
    "SupportReferencePolicy",
    "admit_owner_publication", "orchestrate_opportunity_intelligence",
    "validate_opportunity_orchestration",
    "validate_opportunity_orchestration_manifest",
]
