"""Immutable organizational projection over published Opportunity Intelligence."""
from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Iterable

from decision_intelligence import ContractValidationError
from governed_reference_resolution import (
    AuthorityClass,
    GovernedObjectReference as PublishedObjectReference,
    GovernedRelationship,
    GovernedResolutionError,
    ResolutionContext,
    ResolutionRequest,
    resolve_governed_reference,
)
from opportunity_intelligence_publication import (
    OWNER_CONTRACT,
    OWNER_DOMAIN,
    PUBLICATION_CONTRACT_VERSION,
    OpportunityIntelligencePublication,
    validate_opportunity_intelligence_publication,
)

CONTRACT_VERSION = "executive-opportunity-understanding/1.0.0"
ORGANIZATION_PROFILE = "executive-opportunity-understanding-profile/1.0.0"
SUPPORTED_ANALYST_ID = "opportunity-intelligence"
SUPPORTED_ANALYST_VERSION = "1.0.0"
SOURCE_CONTRACT_VERSION = PUBLICATION_CONTRACT_VERSION
_ID = re.compile(r"^[^\s]+$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class ExecutiveSection(str, Enum):
    OPPORTUNITY_IDENTITY = "OPPORTUNITY_IDENTITY"
    REQUESTED_WORK = "REQUESTED_WORK"
    EVALUATION_AND_SUCCESS_STRUCTURE = "EVALUATION_AND_SUCCESS_STRUCTURE"
    RESPONSE_AND_SUBMISSION_STRUCTURE = "RESPONSE_AND_SUBMISSION_STRUCTURE"
    TIMELINE = "TIMELINE"
    DELIVERY_STRUCTURE = "DELIVERY_STRUCTURE"
    COMMERCIAL_AND_CONTRACT_STRUCTURE = "COMMERCIAL_AND_CONTRACT_STRUCTURE"
    MEASURED_CHARACTERISTICS = "MEASURED_CHARACTERISTICS"
    ANALYST_FINDINGS = "ANALYST_FINDINGS"
    ASSUMPTIONS_AND_ALTERNATIVES = "ASSUMPTIONS_AND_ALTERNATIVES"
    CONFLICTS_UNKNOWNS_AND_EVIDENCE_GAPS = "CONFLICTS_UNKNOWNS_AND_EVIDENCE_GAPS"
    MANAGEMENT_DELIBERATION = "MANAGEMENT_DELIBERATION"
    LIMITATIONS_AND_COVERAGE = "LIMITATIONS_AND_COVERAGE"


SECTION_ORDER = tuple(ExecutiveSection)
_SECTION_ORDINAL = {section: index for index, section in enumerate(SECTION_ORDER)}


class CoverageDisposition(str, Enum):
    EXECUTIVE_INDEX_AND_DETAIL = "EXECUTIVE_INDEX_AND_DETAIL"
    DETAIL_ONLY = "DETAIL_ONLY"
    INELIGIBLE = "INELIGIBLE"


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{name} must be a non-empty string")
    return value


def _identifier(value: str, name: str) -> str:
    _required(value, name)
    if not _ID.fullmatch(value):
        raise ContractValidationError(f"{name} must not contain whitespace")
    return value


def _digest(value: str, name: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ContractValidationError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _unique_strings(values: Iterable[str], name: str) -> tuple[str, ...]:
    result = tuple(values)
    if any(not isinstance(value, str) or not value.strip() for value in result):
        raise ContractValidationError(f"{name} must contain non-empty strings")
    if len(result) != len(set(result)):
        raise ContractValidationError(f"{name} must not contain duplicates")
    return result


def _strings(values: Iterable[str], name: str) -> tuple[str, ...]:
    result = tuple(values)
    if any(not isinstance(value, str) or not value.strip() for value in result):
        raise ContractValidationError(f"{name} must contain non-empty strings")
    return result


def _canonical(value):
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {item.name: _canonical(getattr(value, item.name)) for item in fields(value)
                if item.metadata.get("semantic", True)}
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value)}
    return value


def _json(value) -> str:
    return json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _hash(value) -> str:
    return sha256(_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ExecutiveUnderstandingInput:
    opportunity_id: str
    publication: OpportunityIntelligencePublication

    def __post_init__(self) -> None:
        _identifier(self.opportunity_id, "opportunity_id")
        if not isinstance(self.publication, OpportunityIntelligencePublication):
            raise ContractValidationError(
                "publication must be an OpportunityIntelligencePublication")
        try:
            validate_opportunity_intelligence_publication(self.publication)
        except (ValueError, TypeError) as exc:
            raise ContractValidationError(
                f"Opportunity Intelligence publication is invalid: {exc}") from exc
        if self.publication.analyst_version != SUPPORTED_ANALYST_VERSION:
            raise ContractValidationError("unsupported analyst version")


@dataclass(frozen=True, slots=True)
class GovernedObjectReference:
    """Organization metadata bound to one exact owner-published reference."""
    source_reference: PublishedObjectReference
    authority_class: AuthorityClass
    relationships: tuple[GovernedRelationship, ...]
    section_assignments: tuple[ExecutiveSection, ...]
    display_order_key: tuple[str, ...]
    detail_pointer: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_reference, PublishedObjectReference):
            raise ContractValidationError("source_reference is invalid")
        if not isinstance(self.authority_class, AuthorityClass):
            raise ContractValidationError("authority_class is invalid")
        if (not isinstance(self.relationships, tuple)
                or any(not isinstance(value, GovernedRelationship)
                       for value in self.relationships)):
            raise ContractValidationError("relationships must be immutable governed relationships")
        if self.relationships != tuple(sorted(
                self.relationships, key=lambda value: value.order_key)):
            raise ContractValidationError("relationships are not canonically ordered")
        if (not self.section_assignments
                or any(not isinstance(section, ExecutiveSection)
                       for section in self.section_assignments)
                or len(self.section_assignments) != len(set(self.section_assignments))):
            raise ContractValidationError("section_assignments are invalid")
        expected = tuple(sorted(self.section_assignments,
                                key=lambda section: _SECTION_ORDINAL[section]))
        if self.section_assignments != expected:
            raise ContractValidationError("section_assignments are not canonically ordered")
        object.__setattr__(self, "display_order_key",
                           _strings(self.display_order_key, "display_order_key"))
        _required(self.detail_pointer, "detail_pointer")

    @property
    def object_id(self) -> str:
        return self.source_reference.object_id

    @property
    def object_class(self) -> str:
        return self.source_reference.object_class

    @property
    def owner_domain(self) -> str:
        return self.source_reference.owner_domain

    @property
    def source_contract_version(self) -> str:
        return self.source_reference.contract_version


@dataclass(frozen=True, slots=True)
class DetailRegister:
    authoritative_facts: tuple[GovernedObjectReference, ...] = ()
    computed_facts: tuple[GovernedObjectReference, ...] = ()
    analyst_observations: tuple[GovernedObjectReference, ...] = ()
    validated_interpretations: tuple[GovernedObjectReference, ...] = ()
    competing_interpretation_sets: tuple[GovernedObjectReference, ...] = ()
    assumptions: tuple[GovernedObjectReference, ...] = ()
    unknowns: tuple[GovernedObjectReference, ...] = ()
    conflicts: tuple[GovernedObjectReference, ...] = ()
    management_considerations: tuple[GovernedObjectReference, ...] = ()
    management_questions: tuple[GovernedObjectReference, ...] = ()
    limitations: tuple[GovernedObjectReference, ...] = ()

    def __post_init__(self) -> None:
        allowed = {
            "authoritative_facts": {AuthorityClass.CANONICAL_FACT},
            "computed_facts": {AuthorityClass.COMPUTED_FACT},
            "analyst_observations": {AuthorityClass.OBSERVATION, AuthorityClass.INFERENCE},
            "validated_interpretations": {AuthorityClass.INFERENCE},
            "competing_interpretation_sets": {AuthorityClass.HYPOTHESIS},
            "assumptions": {AuthorityClass.ASSUMPTION},
            "unknowns": {AuthorityClass.UNKNOWN},
            "conflicts": {AuthorityClass.CONFLICT},
            "management_considerations": {AuthorityClass.INFERENCE},
            "management_questions": {AuthorityClass.MANAGEMENT_QUESTION},
            "limitations": {AuthorityClass.LIMITATION},
        }
        all_refs = []
        for item in fields(self):
            values = getattr(self, item.name)
            if (not isinstance(values, tuple)
                    or any(not isinstance(value, GovernedObjectReference)
                           for value in values)):
                raise ContractValidationError(f"{item.name} must contain governed references")
            if tuple(sorted(values, key=_reference_sort_key)) != values:
                raise ContractValidationError(f"{item.name} is not deterministically ordered")
            if any(value.authority_class not in allowed[item.name] for value in values):
                raise ContractValidationError(f"{item.name} contains the wrong authority class")
            if any(value.detail_pointer != f"/detail_register/{item.name}/{index}"
                   for index, value in enumerate(values)):
                raise ContractValidationError(f"{item.name} contains an invalid detail pointer")
            all_refs.extend(values)
        identities = [value.source_reference.identity_key for value in all_refs]
        if len(identities) != len(set(identities)):
            raise ContractValidationError("detail register references must be globally unique")

    def references(self) -> tuple[GovernedObjectReference, ...]:
        return tuple(value for item in fields(self) for value in getattr(self, item.name))


@dataclass(frozen=True, slots=True)
class ExecutiveIndexSection:
    section: ExecutiveSection
    object_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.section, ExecutiveSection):
            raise ContractValidationError("section is invalid")
        object.__setattr__(self, "object_ids", _unique_strings(self.object_ids, "object_ids"))


@dataclass(frozen=True, slots=True)
class CoverageRecord:
    object_id: str
    object_class: str
    disposition: CoverageDisposition
    rule_id: str
    section_keys: tuple[ExecutiveSection, ...]
    detail_pointer: str
    ineligibility_reason: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.object_id, "object_id")
        _required(self.object_class, "object_class")
        if not isinstance(self.disposition, CoverageDisposition):
            raise ContractValidationError("coverage disposition is invalid")
        _required(self.rule_id, "rule_id")
        if (any(not isinstance(section, ExecutiveSection) for section in self.section_keys)
                or len(self.section_keys) != len(set(self.section_keys))):
            raise ContractValidationError("section_keys are invalid")
        if self.section_keys != tuple(sorted(
                self.section_keys, key=lambda section: _SECTION_ORDINAL[section])):
            raise ContractValidationError("section_keys are not canonically ordered")
        _required(self.detail_pointer, "detail_pointer")
        if self.disposition == CoverageDisposition.INELIGIBLE:
            _required(self.ineligibility_reason or "", "ineligibility_reason")
        elif self.ineligibility_reason is not None:
            raise ContractValidationError("admitted coverage cannot have an ineligibility reason")
        if (self.disposition == CoverageDisposition.EXECUTIVE_INDEX_AND_DETAIL
                and not self.section_keys):
            raise ContractValidationError("indexed coverage requires a section")
        if self.disposition == CoverageDisposition.DETAIL_ONLY and self.section_keys:
            raise ContractValidationError("detail-only coverage cannot claim index sections")


@dataclass(frozen=True, slots=True)
class ValidationRecord:
    status: str
    detail_object_count: int
    coverage_object_count: int
    indexed_object_count: int
    reference_integrity: bool
    coverage_complete: bool
    deterministic_order: bool

    def __post_init__(self) -> None:
        if self.status != "VALIDATED":
            raise ContractValidationError("validation record status must be VALIDATED")
        for name in ("detail_object_count", "coverage_object_count", "indexed_object_count"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ContractValidationError(f"{name} must be a non-negative integer")
        if not all((self.reference_integrity, self.coverage_complete,
                    self.deterministic_order)):
            raise ContractValidationError("validation record cannot assert an incomplete contract")


@dataclass(frozen=True, slots=True)
class ExecutiveOpportunityUnderstanding:
    understanding_id: str
    contract_version: str
    opportunity_id: str
    context_id: str
    context_digest: str
    authoritative_snapshot_digest: str
    analysis_id: str
    analyst_id: str
    analyst_version: str
    analysis_input_digest: str
    analysis_digest: str
    publication_id: str
    publication_snapshot_id: str
    publication_snapshot_digest: str
    organization_profile: str
    executive_index: tuple[ExecutiveIndexSection, ...]
    detail_register: DetailRegister
    coverage_ledger: tuple[CoverageRecord, ...]
    validation_record: ValidationRecord
    resolution_context: ResolutionContext = field(
        compare=False, repr=False, metadata={"semantic": False})

    def __post_init__(self) -> None:
        _identifier(self.understanding_id, "understanding_id")
        if self.contract_version != CONTRACT_VERSION:
            raise ContractValidationError("unsupported Executive Opportunity Understanding version")
        _identifier(self.opportunity_id, "opportunity_id")
        _identifier(self.context_id, "context_id")
        for name in ("context_digest", "authoritative_snapshot_digest",
                     "analysis_input_digest", "analysis_digest",
                     "publication_snapshot_digest"):
            _digest(getattr(self, name), name)
        for name in ("analysis_id", "publication_id", "publication_snapshot_id"):
            _identifier(getattr(self, name), name)
        if self.analyst_id != SUPPORTED_ANALYST_ID:
            raise ContractValidationError("unsupported analyst")
        if self.analyst_version != SUPPORTED_ANALYST_VERSION:
            raise ContractValidationError("unsupported analyst version")
        if self.organization_profile != ORGANIZATION_PROFILE:
            raise ContractValidationError("unsupported organization profile")
        if not isinstance(self.detail_register, DetailRegister):
            raise ContractValidationError("detail_register is invalid")
        if not isinstance(self.validation_record, ValidationRecord):
            raise ContractValidationError("validation_record is invalid")
        if not isinstance(self.resolution_context, ResolutionContext):
            raise ContractValidationError("resolution_context is invalid")
        validate_executive_opportunity_understanding(self)

    def to_dict(self) -> dict:
        return _canonical(self)

    def to_json(self) -> str:
        return _json(self)

    @property
    def digest(self) -> str:
        return sha256(self.to_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class _Candidate:
    source_reference: PublishedObjectReference
    authority_class: AuthorityClass
    relationships: tuple[GovernedRelationship, ...]
    collection_name: str
    sections: tuple[ExecutiveSection, ...]
    indexed: bool


_RULES = {
    "analysis": ("analyst_observations", (ExecutiveSection.ANALYST_FINDINGS,), False),
    "computed-fact": ("computed_facts", (ExecutiveSection.MEASURED_CHARACTERISTICS,), True),
    "inference": ("validated_interpretations", (ExecutiveSection.ANALYST_FINDINGS,), True),
    "hypothesis": ("competing_interpretation_sets",
                   (ExecutiveSection.ASSUMPTIONS_AND_ALTERNATIVES,), True),
    "alternative-hypothesis": ("competing_interpretation_sets",
                               (ExecutiveSection.ASSUMPTIONS_AND_ALTERNATIVES,), True),
    "assumption": ("assumptions", (ExecutiveSection.ASSUMPTIONS_AND_ALTERNATIVES,), True),
    "unknowns": ("unknowns", (ExecutiveSection.CONFLICTS_UNKNOWNS_AND_EVIDENCE_GAPS,), True),
    "limitations": ("limitations", (ExecutiveSection.LIMITATIONS_AND_COVERAGE,), True),
    "management-question": ("management_questions",
                            (ExecutiveSection.MANAGEMENT_DELIBERATION,), True),
}
_ALLOWED = {
    "analyst_observations": {AuthorityClass.OBSERVATION, AuthorityClass.INFERENCE},
    "computed_facts": {AuthorityClass.COMPUTED_FACT},
    "validated_interpretations": {AuthorityClass.INFERENCE},
    "competing_interpretation_sets": {AuthorityClass.HYPOTHESIS},
    "assumptions": {AuthorityClass.ASSUMPTION},
    "unknowns": {AuthorityClass.UNKNOWN},
    "limitations": {AuthorityClass.LIMITATION},
    "management_questions": {AuthorityClass.MANAGEMENT_QUESTION},
}


def _reference_sort_key(reference: GovernedObjectReference):
    return (reference.display_order_key, reference.source_reference.identity_key)


def _make_references(name: str, candidates: Iterable[_Candidate]):
    result = []
    ordered = sorted(candidates, key=lambda value: value.source_reference.identity_key)
    for index, candidate in enumerate(ordered):
        sections = tuple(sorted(set(candidate.sections),
                                key=lambda value: _SECTION_ORDINAL[value]))
        result.append(GovernedObjectReference(
            candidate.source_reference, candidate.authority_class,
            candidate.relationships, sections,
            (f"{_SECTION_ORDINAL[sections[0]]:02d}",
             candidate.source_reference.object_class,
             candidate.source_reference.object_id),
            f"/detail_register/{name}/{index}",
        ))
    return tuple(result)


def _resolve_candidate(publication: OpportunityIntelligencePublication,
                       reference: PublishedObjectReference) -> _Candidate:
    matches = tuple(item for item in publication.snapshot.objects
                    if item.object_class == reference.object_class
                    and item.object_id == reference.object_id)
    if len(matches) != 1:
        raise ContractValidationError("published reference is not unique")
    published = matches[0]
    if reference.object_class not in _RULES:
        raise ContractValidationError(
            f"unsupported published analytical class: {reference.object_class}")
    collection, sections, indexed = _RULES[reference.object_class]
    if published.authority not in _ALLOWED[collection]:
        raise ContractValidationError("published object has incompatible authority")
    request = ResolutionRequest(
        reference, publication.resolution_context.context_id,
        publication.resolution_context.context_digest, published.authority,
        tuple(item.name for item in published.semantic_fields),
        tuple(sorted({item.kind for item in published.relationships},
                     key=lambda value: value.value)),
    )
    try:
        resolved = resolve_governed_reference(request, publication.resolution_context)
    except GovernedResolutionError as exc:
        raise ContractValidationError(
            f"published object {reference.object_id} failed governed resolution: "
            f"{exc.code.value}") from exc
    if resolved.root.object_digest != reference.object_digest:
        raise ContractValidationError("resolved semantic identity changed")
    if resolved.root.relationships != published.relationships:
        raise ContractValidationError("resolved relationship identity changed")
    return _Candidate(reference, resolved.root.authority, resolved.root.relationships,
                      collection, sections, indexed)


def build_executive_opportunity_understanding(
        source: ExecutiveUnderstandingInput) -> ExecutiveOpportunityUnderstanding:
    """Organize one validated immutable Opportunity Intelligence publication."""
    if not isinstance(source, ExecutiveUnderstandingInput):
        raise ContractValidationError("source must be ExecutiveUnderstandingInput")
    publication = source.publication
    candidates = tuple(_resolve_candidate(publication, reference)
                       for reference in publication.references)
    collections = {item.name: [] for item in fields(DetailRegister)}
    for candidate in candidates:
        collections[candidate.collection_name].append(candidate)
    register = DetailRegister(**{
        name: _make_references(name, values) for name, values in collections.items()})
    references = register.references()
    indexed = {candidate.source_reference.identity_key
               for candidate in candidates if candidate.indexed}
    index = tuple(ExecutiveIndexSection(
        section,
        tuple(reference.object_id for reference in sorted(references, key=_reference_sort_key)
              if reference.source_reference.identity_key in indexed
              and section in reference.section_assignments),
    ) for section in SECTION_ORDER)
    ledger = tuple(sorted((CoverageRecord(
        reference.object_id, reference.object_class,
        (CoverageDisposition.EXECUTIVE_INDEX_AND_DETAIL
         if reference.source_reference.identity_key in indexed
         else CoverageDisposition.DETAIL_ONLY),
        ("eou-v1-published-semantic-index"
         if reference.source_reference.identity_key in indexed
         else "eou-v1-published-detail-register"),
        (reference.section_assignments
         if reference.source_reference.identity_key in indexed else ()),
        reference.detail_pointer,
    ) for reference in references), key=lambda value: (value.object_class, value.object_id)))
    validation = ValidationRecord(
        "VALIDATED", len(references), len(ledger), len(indexed), True, True, True)
    manifest = publication.manifest
    identity = {
        "contract_version": CONTRACT_VERSION,
        "organization_profile": ORGANIZATION_PROFILE,
        "opportunity_id": source.opportunity_id,
        "authoritative_snapshot_digest": publication.authoritative_context_digest,
        "analysis_id": publication.analysis_id,
        "analysis_input_digest": publication.authoritative_context_digest,
        "analysis_digest": manifest.analysis_digest,
        "publication_id": publication.publication_id,
        "publication_snapshot_id": publication.snapshot.snapshot_id,
        "publication_snapshot_digest": publication.snapshot.snapshot_digest,
    }
    return ExecutiveOpportunityUnderstanding(
        "eou-" + _hash(identity), CONTRACT_VERSION, source.opportunity_id,
        publication.resolution_context.context_id,
        publication.resolution_context.context_digest,
        publication.authoritative_context_digest, publication.analysis_id,
        SUPPORTED_ANALYST_ID, publication.analyst_version,
        publication.authoritative_context_digest, manifest.analysis_digest,
        publication.publication_id, publication.snapshot.snapshot_id,
        publication.snapshot.snapshot_digest, ORGANIZATION_PROFILE,
        index, register, ledger, validation, publication.resolution_context,
    )


def validate_executive_opportunity_understanding(
        value: ExecutiveOpportunityUnderstanding) -> ExecutiveOpportunityUnderstanding:
    """Validate exact resolution, complete coverage, ordering, and identity."""
    if not isinstance(value, ExecutiveOpportunityUnderstanding):
        raise ContractValidationError("ExecutiveOpportunityUnderstanding is required")
    if (value.context_id, value.context_digest) != (
            value.resolution_context.context_id, value.resolution_context.context_digest):
        raise ContractValidationError("resolution context binding is inconsistent")
    snapshots = tuple(snapshot for snapshot in value.resolution_context.snapshots
                      if snapshot.owner_domain == OWNER_DOMAIN
                      and snapshot.owner_contract == OWNER_CONTRACT
                      and snapshot.contract_version == SOURCE_CONTRACT_VERSION
                      and snapshot.snapshot_id == value.publication_snapshot_id
                      and snapshot.snapshot_digest == value.publication_snapshot_digest)
    if len(snapshots) != 1:
        raise ContractValidationError("publication snapshot is absent from resolution context")
    publication_snapshot = snapshots[0]
    references = value.detail_register.references()
    by_identity = {item.source_reference.identity_key: item for item in references}
    if len(by_identity) != len(references):
        raise ContractValidationError("detail register contains duplicate references")
    expected = {(
        publication_snapshot.owner_domain, publication_snapshot.owner_contract,
        publication_snapshot.contract_version, publication_snapshot.snapshot_id,
        item.object_class, item.object_id) for item in publication_snapshot.objects}
    if set(by_identity) != expected:
        raise ContractValidationError("detail register is incomplete for publication snapshot")
    for reference in references:
        request = ResolutionRequest(
            reference.source_reference, value.context_id, value.context_digest,
            reference.authority_class, (),
            tuple(sorted({item.kind for item in reference.relationships},
                         key=lambda item: item.value)))
        try:
            resolved = resolve_governed_reference(request, value.resolution_context)
        except GovernedResolutionError as exc:
            raise ContractValidationError(
                f"understanding reference {reference.object_id} does not resolve: "
                f"{exc.code.value}") from exc
        if resolved.root.relationships != reference.relationships:
            raise ContractValidationError("understanding relationship identity changed")

    if (not isinstance(value.executive_index, tuple)
            or len(value.executive_index) != len(SECTION_ORDER)
            or tuple(item.section for item in value.executive_index) != SECTION_ORDER):
        raise ContractValidationError("executive index sections are incomplete or unordered")
    reference_by_id = {item.object_id: item for item in references}
    coverage_by_id = {item.object_id: item for item in value.coverage_ledger}
    if len(reference_by_id) != len(references):
        raise ContractValidationError("published object IDs are not globally unique")
    if len(coverage_by_id) != len(value.coverage_ledger):
        raise ContractValidationError("coverage ledger contains duplicate object IDs")
    if set(reference_by_id) != set(coverage_by_id):
        raise ContractValidationError("coverage ledger is not bijective with detail register")
    if value.coverage_ledger != tuple(sorted(
            value.coverage_ledger, key=lambda item: (item.object_class, item.object_id))):
        raise ContractValidationError("coverage ledger is not deterministically ordered")
    if any(record.object_class != reference_by_id[record.object_id].object_class
           or record.detail_pointer != reference_by_id[record.object_id].detail_pointer
           for record in value.coverage_ledger):
        raise ContractValidationError("coverage ledger does not preserve detail identity")
    indexed_ids = {item.object_id for item in value.coverage_ledger
                   if item.disposition == CoverageDisposition.EXECUTIVE_INDEX_AND_DETAIL}
    index_ids = []
    for section in value.executive_index:
        expected_ids = tuple(
            reference.object_id for reference in sorted(references, key=_reference_sort_key)
            if reference.object_id in indexed_ids
            and section.section in reference.section_assignments)
        if section.object_ids != expected_ids:
            raise ContractValidationError("executive index does not match assignments")
        index_ids.extend(section.object_ids)
    if set(index_ids) != indexed_ids:
        raise ContractValidationError("executive index and indexed coverage differ")
    validation = value.validation_record
    if (validation.detail_object_count != len(references)
            or validation.coverage_object_count != len(value.coverage_ledger)
            or validation.indexed_object_count != len(indexed_ids)):
        raise ContractValidationError("validation counts do not match contract content")
    identity = {
        "contract_version": value.contract_version,
        "organization_profile": value.organization_profile,
        "opportunity_id": value.opportunity_id,
        "authoritative_snapshot_digest": value.authoritative_snapshot_digest,
        "analysis_id": value.analysis_id,
        "analysis_input_digest": value.analysis_input_digest,
        "analysis_digest": value.analysis_digest,
        "publication_id": value.publication_id,
        "publication_snapshot_id": value.publication_snapshot_id,
        "publication_snapshot_digest": value.publication_snapshot_digest,
    }
    if value.understanding_id != "eou-" + _hash(identity):
        raise ContractValidationError("understanding identity does not match governed inputs")
    return value


__all__ = [
    "AuthorityClass", "CONTRACT_VERSION", "CoverageDisposition", "CoverageRecord",
    "DetailRegister", "ExecutiveIndexSection", "ExecutiveOpportunityUnderstanding",
    "ExecutiveSection", "ExecutiveUnderstandingInput", "GovernedObjectReference",
    "ORGANIZATION_PROFILE", "SECTION_ORDER", "SOURCE_CONTRACT_VERSION",
    "SUPPORTED_ANALYST_ID", "SUPPORTED_ANALYST_VERSION", "ValidationRecord",
    "build_executive_opportunity_understanding",
    "validate_executive_opportunity_understanding",
]
