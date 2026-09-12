"""Immutable owner publication for validated Buyer Intelligence analysis.

Publishes exactly what buyer_intelligence.py's analyze_buyer already
established -- facts, computed facts, interpretations, hypotheses,
assumptions, unknowns, conflicts, management questions, and limitations --
as immutable governed objects. Every fact's evidence_ids are bound to real
references from Buyer Evidence Publication or Canonical Buyer Publication;
an id neither can resolve is refused, never guessed. It performs no new
reasoning, confidence, or fact.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from hashlib import sha256
import json
from typing import Mapping

from buyer_domain import BUYER_DOMAIN_VERSION
from buyer_evidence import BUYER_EVIDENCE_VERSION
from buyer_evidence_publication import BuyerEvidencePublication
from canonical_buyer_publication import CanonicalBuyerPublication
from buyer_intelligence import BUYER_INTELLIGENCE_VERSION, BuyerIntelligenceAnalysis
from governed_reference_resolution import (
    AuthorityClass, GovernedObjectReference, GovernedRelationship,
    GovernedResolutionError, GovernedSnapshot, RelationshipKind, SemanticField,
    SemanticValue, SemanticValueKind, create_governed_object,
    create_governed_snapshot, reference_to,
)

OWNER_DOMAIN = "buyer-intelligence"
OWNER_CONTRACT = "buyer-intelligence-analyst"
PUBLICATION_CONTRACT_VERSION = "1.0.0"

BUYER_FACT_CLASS = "BUYER_FACT"
COMPUTED_FACT_CLASS = "COMPUTED_FACT"
INTERPRETATION_CLASS = "INTERPRETATION"
HYPOTHESIS_CLASS = "HYPOTHESIS"
ASSUMPTION_CLASS = "ASSUMPTION"
UNKNOWN_CLASS = "UNKNOWN"
CONFLICT_CLASS = "CONFLICT"
MANAGEMENT_QUESTION_CLASS = "MANAGEMENT_QUESTION"
LIMITATION_CLASS = "LIMITATION"
ANALYSIS_CLASS = "ANALYSIS"
_ZERO_DIGEST = "0" * 64
_ALLOWED_CLASSES = {
    BUYER_FACT_CLASS, COMPUTED_FACT_CLASS, INTERPRETATION_CLASS, HYPOTHESIS_CLASS,
    ASSUMPTION_CLASS, UNKNOWN_CLASS, CONFLICT_CLASS, MANAGEMENT_QUESTION_CLASS,
    LIMITATION_CLASS, ANALYSIS_CLASS,
}


class BuyerIntelligencePublicationFailureCode(str, Enum):
    INVALID_SOURCE = "INVALID_SOURCE"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    DUPLICATE_IDENTITY = "DUPLICATE_IDENTITY"
    MISSING_SEMANTIC_CONTENT = "MISSING_SEMANTIC_CONTENT"
    MISSING_RELATIONSHIP_BINDING = "MISSING_RELATIONSHIP_BINDING"
    BROKEN_RELATIONSHIP = "BROKEN_RELATIONSHIP"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    INVALID_PUBLICATION = "INVALID_PUBLICATION"


class BuyerIntelligencePublicationError(ValueError):
    """Controlled fail-closed Buyer Intelligence publication failure."""

    def __init__(self, code: BuyerIntelligencePublicationFailureCode, message: str) -> None:
        self.code = code
        super().__init__(message)


def _fail(code: BuyerIntelligencePublicationFailureCode, message: str):
    raise BuyerIntelligencePublicationError(code, message)


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
        _fail(BuyerIntelligencePublicationFailureCode.MISSING_SEMANTIC_CONTENT,
              f"buyer intelligence semantic content is not serializable: {exc}")


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
    _fail(BuyerIntelligencePublicationFailureCode.MISSING_SEMANTIC_CONTENT,
          f"unsupported buyer intelligence semantic value type: {type(value).__name__}")


def _semantic_fields(values: Mapping[str, object]) -> tuple[SemanticField, ...]:
    if not values:
        _fail(BuyerIntelligencePublicationFailureCode.MISSING_SEMANTIC_CONTENT,
              "published buyer intelligence objects require semantic fields")
    return tuple(sorted((SemanticField(name, _semantic_value(value))
                         for name, value in values.items()), key=lambda item: item.name))


def _statement_semantics(item) -> dict:
    return {field.name: getattr(item, field.name) for field in fields(item)}


@dataclass(frozen=True, slots=True)
class BuyerIntelligencePublicationManifestObject:
    object_class: str
    object_id: str
    object_digest: str


@dataclass(frozen=True, slots=True)
class BuyerIntelligencePublicationManifestRelationship:
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
class BuyerIntelligencePublicationManifest:
    owner_domain: str
    owner_contract: str
    contract_version: str
    source_contract_version: str
    analysis_id: str
    buyer_id: str
    input_digest: str
    object_manifest_digest: str
    snapshot_id: str
    snapshot_digest: str
    objects: tuple[BuyerIntelligencePublicationManifestObject, ...]
    relationships: tuple[BuyerIntelligencePublicationManifestRelationship, ...]


@dataclass(frozen=True, slots=True)
class BuyerIntelligencePublication:
    publication_id: str
    analysis_id: str
    buyer_id: str
    source_contract_version: str
    input_digest: str
    snapshot: GovernedSnapshot
    manifest: BuyerIntelligencePublicationManifest
    references: tuple[GovernedObjectReference, ...]

    def __post_init__(self) -> None:
        validate_buyer_intelligence_publication(self)

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


def _placeholder(snapshot_id: str, object_class: str, object_id: str) -> GovernedObjectReference:
    return GovernedObjectReference(
        OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION,
        snapshot_id, _ZERO_DIGEST, object_class, object_id, _ZERO_DIGEST)


def _internal(kind: RelationshipKind, role: str, ordinal: int,
             snapshot_id: str, object_class: str, object_id: str) -> GovernedRelationship:
    return GovernedRelationship(kind, role, _placeholder(snapshot_id, object_class, object_id), ordinal)


def _resolve_evidence(evidence_id: str, evidence_by_id: Mapping[str, GovernedObjectReference],
                      *, fact_id: str) -> GovernedObjectReference:
    reference = evidence_by_id.get(evidence_id)
    if reference is None:
        _fail(BuyerIntelligencePublicationFailureCode.MISSING_RELATIONSHIP_BINDING,
              f"{fact_id}: evidence id {evidence_id!r} does not resolve in the supplied "
              "Buyer Evidence Publication or Canonical Buyer Publication; refusing to guess")
    return reference


def _build_specs(analysis: BuyerIntelligenceAnalysis,
                 evidence_by_id: Mapping[str, GovernedObjectReference],
                 identity_reference: GovernedObjectReference,
                 snapshot_id: str) -> tuple[_ObjectSpec, ...]:
    specs: list[_ObjectSpec] = []
    fact_ids: set[str] = set()
    all_facts = (analysis.buyer_facts + analysis.public_organizational_information
                +analysis.verified_procurement_context)
    for fact in all_facts:
        relationships = tuple(
            GovernedRelationship(RelationshipKind.EVIDENCE_SUPPORT, "source-evidence",
                                 _resolve_evidence(eid, evidence_by_id, fact_id=fact.fact_id), ordinal)
            for ordinal, eid in enumerate(fact.evidence_ids))
        specs.append(_ObjectSpec(BUYER_FACT_CLASS, fact.fact_id, _statement_semantics(fact), relationships))
        fact_ids.add(fact.fact_id)

    for item in analysis.computed_facts:
        relationships = tuple(_internal(RelationshipKind.SUPPORT, "input-fact", ordinal,
                                        snapshot_id, BUYER_FACT_CLASS, input_id)
                              for ordinal, input_id in enumerate(item.input_fact_ids))
        specs.append(_ObjectSpec(COMPUTED_FACT_CLASS, item.fact_id, _statement_semantics(item), relationships))

    for item in analysis.interpretations:
        relationships = []
        for ordinal, eid in enumerate(item.supporting_evidence_ids):
            relationships.append(GovernedRelationship(
                RelationshipKind.SUPPORT, "supporting-evidence",
                _resolve_evidence(eid, evidence_by_id, fact_id=item.interpretation_id), ordinal))
        offset = len(relationships)
        for ordinal, eid in enumerate(item.contradicting_evidence_ids, offset):
            relationships.append(GovernedRelationship(
                RelationshipKind.CONTRADICTION, "contradicting-evidence",
                _resolve_evidence(eid, evidence_by_id, fact_id=item.interpretation_id), ordinal))
        offset = len(relationships)
        for ordinal, aid in enumerate(item.assumption_ids, offset):
            relationships.append(_internal(RelationshipKind.RELATED, "assumption", ordinal,
                                           snapshot_id, ASSUMPTION_CLASS, aid))
        specs.append(_ObjectSpec(INTERPRETATION_CLASS, item.interpretation_id,
                                 _statement_semantics(item), tuple(relationships)))

    for item in analysis.competing_hypotheses:
        relationships = []
        for ordinal, eid in enumerate(item.supporting_evidence_ids):
            relationships.append(GovernedRelationship(
                RelationshipKind.SUPPORT, "supporting-evidence",
                _resolve_evidence(eid, evidence_by_id, fact_id=item.hypothesis_id), ordinal))
        offset = len(relationships)
        for ordinal, eid in enumerate(item.contradicting_evidence_ids, offset):
            relationships.append(GovernedRelationship(
                RelationshipKind.CONTRADICTION, "contradicting-evidence",
                _resolve_evidence(eid, evidence_by_id, fact_id=item.hypothesis_id), ordinal))
        specs.append(_ObjectSpec(HYPOTHESIS_CLASS, item.hypothesis_id,
                                 _statement_semantics(item), tuple(relationships)))

    for item in analysis.assumptions:
        relationships = tuple(_internal(RelationshipKind.RELATED, "interpretation", ordinal,
                                        snapshot_id, INTERPRETATION_CLASS, iid)
                              for ordinal, iid in enumerate(item.interpretation_ids))
        specs.append(_ObjectSpec(ASSUMPTION_CLASS, item.assumption_id, _statement_semantics(item), relationships))

    for item in analysis.unknowns:
        relationships = tuple(
            GovernedRelationship(RelationshipKind.RELATED, "related-evidence",
                                 _resolve_evidence(eid, evidence_by_id, fact_id=item.unknown_id), ordinal)
            for ordinal, eid in enumerate(item.related_evidence_ids))
        specs.append(_ObjectSpec(UNKNOWN_CLASS, item.unknown_id, _statement_semantics(item), relationships))

    for item in analysis.conflicts:
        relationships = []
        ordinal = 0
        for group_index, group in enumerate(item.opposing_evidence):
            for eid in group:
                relationships.append(GovernedRelationship(
                    RelationshipKind.CONFLICT_MEMBER, f"opposing-group-{group_index}",
                    _resolve_evidence(eid, evidence_by_id, fact_id=item.conflict_id), ordinal))
                ordinal += 1
        specs.append(_ObjectSpec(CONFLICT_CLASS, item.conflict_id, _statement_semantics(item), tuple(relationships)))

    for item in analysis.management_questions:
        relationships = []
        for ordinal, eid in enumerate(item.evidence_ids):
            relationships.append(GovernedRelationship(
                RelationshipKind.RELATED, "related-evidence",
                _resolve_evidence(eid, evidence_by_id, fact_id=item.question_id), ordinal))
        offset = len(relationships)
        for ordinal, uid in enumerate(item.unknown_ids, offset):
            relationships.append(_internal(RelationshipKind.RELATED, "unknown", ordinal,
                                           snapshot_id, UNKNOWN_CLASS, uid))
        offset = len(relationships)
        for ordinal, cid in enumerate(item.conflict_ids, offset):
            relationships.append(_internal(RelationshipKind.RELATED, "conflict", ordinal,
                                           snapshot_id, CONFLICT_CLASS, cid))
        specs.append(_ObjectSpec(MANAGEMENT_QUESTION_CLASS, item.question_id,
                                 _statement_semantics(item), tuple(relationships)))

    for item in analysis.limitations:
        specs.append(_ObjectSpec(LIMITATION_CLASS, item.limitation_id, _statement_semantics(item)))

    contained = tuple(sorted((spec.object_class, spec.object_id) for spec in specs))
    analysis_relationships = [
        _internal(RelationshipKind.DEPENDENCY, "contains", ordinal, snapshot_id, object_class, object_id)
        for ordinal, (object_class, object_id) in enumerate(contained)
    ]
    # Canonical Buyer remains the sole owner of buyer identity
    # (BUYER_INTELLIGENCE_FACT_OWNERSHIP_ARCHITECTURE.md) -- this analysis
    # never republishes it as a BuyerFact. Where identity is required, the
    # analysis root references Canonical Buyer Publication's own identity
    # object directly instead.
    analysis_relationships.append(GovernedRelationship(
        RelationshipKind.RELATED, "buyer-identity", identity_reference, len(analysis_relationships)))
    analysis_relationships = tuple(analysis_relationships)
    specs.append(_ObjectSpec(ANALYSIS_CLASS, analysis.analysis_id, {
        "analysis_id": analysis.analysis_id, "buyer_id": analysis.buyer_id,
        "opportunity_id": analysis.opportunity_id,
        "evaluation_context_id": analysis.evaluation_context_id,
        "analyst_version": analysis.analyst_version,
    }, analysis_relationships))

    return tuple(sorted(specs, key=lambda item: (item.object_class, item.object_id)))


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
        "relationships": tuple({"kind": item.kind, "role": item.role, "ordinal": item.ordinal,
                                "target": target(item.target)} for item in spec.relationships),
    } for spec in specs)


_AUTHORITY_BY_CLASS = {
    BUYER_FACT_CLASS: AuthorityClass.CANONICAL_FACT,
    COMPUTED_FACT_CLASS: AuthorityClass.COMPUTED_FACT,
    INTERPRETATION_CLASS: AuthorityClass.INFERENCE,
    HYPOTHESIS_CLASS: AuthorityClass.HYPOTHESIS,
    ASSUMPTION_CLASS: AuthorityClass.ASSUMPTION,
    UNKNOWN_CLASS: AuthorityClass.UNKNOWN,
    CONFLICT_CLASS: AuthorityClass.CONFLICT,
    MANAGEMENT_QUESTION_CLASS: AuthorityClass.MANAGEMENT_QUESTION,
    LIMITATION_CLASS: AuthorityClass.LIMITATION,
    ANALYSIS_CLASS: AuthorityClass.INFERENCE,
}


def publish_buyer_intelligence(
        analysis: BuyerIntelligenceAnalysis, *,
        buyer_evidence_publication: BuyerEvidencePublication,
        canonical_buyer_publication: CanonicalBuyerPublication,
        ) -> BuyerIntelligencePublication:
    """Publish one validated Buyer Intelligence analysis without changing it."""
    if not isinstance(analysis, BuyerIntelligenceAnalysis) or analysis.analyst_version != BUYER_INTELLIGENCE_VERSION:
        _fail(BuyerIntelligencePublicationFailureCode.INVALID_SOURCE,
              "publication requires a supported BuyerIntelligenceAnalysis")
    if not isinstance(buyer_evidence_publication, BuyerEvidencePublication):
        _fail(BuyerIntelligencePublicationFailureCode.INVALID_SOURCE,
              "publication requires a validated BuyerEvidencePublication")
    if not isinstance(canonical_buyer_publication, CanonicalBuyerPublication):
        _fail(BuyerIntelligencePublicationFailureCode.INVALID_SOURCE,
              "publication requires a validated CanonicalBuyerPublication")
    if buyer_evidence_publication.buyer_id != analysis.buyer_id:
        _fail(BuyerIntelligencePublicationFailureCode.INVALID_SOURCE,
              "Buyer Evidence Publication does not belong to this analysis's buyer")
    if canonical_buyer_publication.buyer_id != analysis.buyer_id:
        _fail(BuyerIntelligencePublicationFailureCode.INVALID_SOURCE,
              "Canonical Buyer Publication does not belong to this analysis's buyer")
    before = analysis.to_json()

    evidence_by_id: dict[str, GovernedObjectReference] = {}
    for reference in buyer_evidence_publication.references + canonical_buyer_publication.references:
        if reference.object_id in evidence_by_id:
            _fail(BuyerIntelligencePublicationFailureCode.DUPLICATE_IDENTITY,
                  f"evidence id {reference.object_id!r} is ambiguous across admitted publications")
        evidence_by_id[reference.object_id] = reference

    identity_reference = canonical_buyer_publication.reference_for_identity()
    provisional_specs = _build_specs(analysis, evidence_by_id, identity_reference,
                                     "buyer-intelligence-publication-pending")
    object_manifest_digest = _sha(_logical_manifest(provisional_specs))
    snapshot_id = "buyer-intelligence-publication-" + _sha({
        "owner_domain": OWNER_DOMAIN, "owner_contract": OWNER_CONTRACT,
        "contract_version": PUBLICATION_CONTRACT_VERSION, "analysis_id": analysis.analysis_id,
        "input_digest": analysis.input_digest, "object_manifest_digest": object_manifest_digest,
    })
    specs = _build_specs(analysis, evidence_by_id, identity_reference, snapshot_id)
    if _sha(_logical_manifest(specs)) != object_manifest_digest:
        _fail(BuyerIntelligencePublicationFailureCode.DIGEST_MISMATCH,
              "buyer intelligence object manifest changed during snapshot binding")
    try:
        objects = tuple(create_governed_object(
            owner_domain=OWNER_DOMAIN, owner_contract=OWNER_CONTRACT,
            contract_version=PUBLICATION_CONTRACT_VERSION, object_class=spec.object_class,
            object_id=spec.object_id, authority=_AUTHORITY_BY_CLASS[spec.object_class],
            semantic_fields=_semantic_fields(spec.semantics), relationships=spec.relationships,
        ) for spec in specs)
        snapshot = create_governed_snapshot(
            owner_domain=OWNER_DOMAIN, owner_contract=OWNER_CONTRACT,
            contract_version=PUBLICATION_CONTRACT_VERSION, snapshot_id=snapshot_id, objects=objects)
    except GovernedResolutionError as exc:
        _fail(BuyerIntelligencePublicationFailureCode.INVALID_PUBLICATION,
              f"buyer intelligence publication snapshot is invalid: {exc.code.value}")

    references = tuple(reference_to(snapshot, item.object_class, item.object_id) for item in snapshot.objects)
    manifest_objects = tuple(BuyerIntelligencePublicationManifestObject(
        item.object_class, item.object_id, item.object_digest) for item in snapshot.objects)
    manifest_relationships = tuple(sorted((
        BuyerIntelligencePublicationManifestRelationship(
            item.object_class, item.object_id, relationship.kind, relationship.role,
            relationship.ordinal, relationship.target)
        for item in snapshot.objects for relationship in item.relationships
    ), key=lambda item: item.order_key))
    manifest = BuyerIntelligencePublicationManifest(
        OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION, BUYER_INTELLIGENCE_VERSION,
        analysis.analysis_id, analysis.buyer_id, analysis.input_digest, object_manifest_digest,
        snapshot.snapshot_id, snapshot.snapshot_digest, manifest_objects, manifest_relationships)
    publication_id = "buyer-intelligence-publication-record-" + _sha({
        "analysis_id": analysis.analysis_id, "input_digest": analysis.input_digest,
        "snapshot_id": snapshot.snapshot_id, "snapshot_digest": snapshot.snapshot_digest,
    })
    publication = BuyerIntelligencePublication(
        publication_id, analysis.analysis_id, analysis.buyer_id, BUYER_INTELLIGENCE_VERSION,
        analysis.input_digest, snapshot, manifest, references)
    if analysis.to_json() != before:
        _fail(BuyerIntelligencePublicationFailureCode.INVALID_SOURCE,
              "buyer intelligence publication mutated its source")
    return publication


def validate_buyer_intelligence_publication(
        publication: BuyerIntelligencePublication) -> BuyerIntelligencePublication:
    if not isinstance(publication, BuyerIntelligencePublication):
        _fail(BuyerIntelligencePublicationFailureCode.INVALID_PUBLICATION,
              "BuyerIntelligencePublication is required")
    manifest, snapshot = publication.manifest, publication.snapshot
    if not isinstance(manifest, BuyerIntelligencePublicationManifest) or not isinstance(snapshot, GovernedSnapshot):
        _fail(BuyerIntelligencePublicationFailureCode.INVALID_PUBLICATION,
              "buyer intelligence publication manifest or snapshot is invalid")
    expected_owner = (OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION)
    if ((snapshot.owner_domain, snapshot.owner_contract, snapshot.contract_version) != expected_owner
            or (manifest.owner_domain, manifest.owner_contract, manifest.contract_version) != expected_owner):
        _fail(BuyerIntelligencePublicationFailureCode.VERSION_MISMATCH,
              "buyer intelligence publication owner binding is invalid")
    if (publication.source_contract_version != BUYER_INTELLIGENCE_VERSION
            or manifest.source_contract_version != BUYER_INTELLIGENCE_VERSION):
        _fail(BuyerIntelligencePublicationFailureCode.VERSION_MISMATCH,
              "buyer intelligence source contract binding is invalid")
    if ((publication.analysis_id, publication.buyer_id, publication.input_digest)
            != (manifest.analysis_id, manifest.buyer_id, manifest.input_digest)):
        _fail(BuyerIntelligencePublicationFailureCode.INVALID_PUBLICATION,
              "buyer intelligence publication envelope and manifest differ")
    if (snapshot.snapshot_id, snapshot.snapshot_digest) != (manifest.snapshot_id, manifest.snapshot_digest):
        _fail(BuyerIntelligencePublicationFailureCode.DIGEST_MISMATCH,
              "buyer intelligence snapshot and manifest differ")
    expected_objects = tuple(BuyerIntelligencePublicationManifestObject(
        item.object_class, item.object_id, item.object_digest) for item in snapshot.objects)
    if manifest.objects != expected_objects:
        _fail(BuyerIntelligencePublicationFailureCode.DIGEST_MISMATCH,
              "buyer intelligence object manifest differs from its snapshot")
    if any(item.object_class not in _ALLOWED_CLASSES for item in snapshot.objects):
        _fail(BuyerIntelligencePublicationFailureCode.INVALID_PUBLICATION,
              "buyer intelligence snapshot contains a foreign object class")
    analysis_objects = tuple(item for item in snapshot.objects if item.object_class == ANALYSIS_CLASS)
    if len(analysis_objects) != 1 or analysis_objects[0].object_id != publication.analysis_id:
        _fail(BuyerIntelligencePublicationFailureCode.INVALID_PUBLICATION,
              "buyer intelligence publication must contain exactly one analysis root")
    expected_relationships = tuple(sorted((
        BuyerIntelligencePublicationManifestRelationship(
            item.object_class, item.object_id, relationship.kind, relationship.role,
            relationship.ordinal, relationship.target)
        for item in snapshot.objects for relationship in item.relationships
    ), key=lambda item: item.order_key))
    if manifest.relationships != expected_relationships:
        _fail(BuyerIntelligencePublicationFailureCode.BROKEN_RELATIONSHIP,
              "buyer intelligence relationship manifest differs from its snapshot")
    expected_references = tuple(reference_to(snapshot, item.object_class, item.object_id) for item in snapshot.objects)
    if not isinstance(publication.references, tuple) or publication.references != expected_references:
        _fail(BuyerIntelligencePublicationFailureCode.DIGEST_MISMATCH,
              "buyer intelligence references differ from the immutable snapshot")
    expected_publication_id = "buyer-intelligence-publication-record-" + _sha({
        "analysis_id": publication.analysis_id, "input_digest": publication.input_digest,
        "snapshot_id": snapshot.snapshot_id, "snapshot_digest": snapshot.snapshot_digest,
    })
    if publication.publication_id != expected_publication_id:
        _fail(BuyerIntelligencePublicationFailureCode.DIGEST_MISMATCH,
              "buyer intelligence publication identity is invalid")
    object_keys = {(item.object_class, item.object_id) for item in snapshot.objects}
    for item in snapshot.objects:
        if not item.semantic_fields:
            _fail(BuyerIntelligencePublicationFailureCode.MISSING_SEMANTIC_CONTENT,
                  f"buyer intelligence object {item.object_id} has no semantic content")
        for relationship in item.relationships:
            target = relationship.target
            if target.owner_domain == OWNER_DOMAIN and (
                    target.owner_contract != OWNER_CONTRACT
                    or target.contract_version != PUBLICATION_CONTRACT_VERSION
                    or (target.object_class, target.object_id) not in object_keys):
                _fail(BuyerIntelligencePublicationFailureCode.BROKEN_RELATIONSHIP,
                      f"buyer intelligence relationship from {item.object_id} does not close")
    return publication


__all__ = [
    "ANALYSIS_CLASS", "ASSUMPTION_CLASS", "BUYER_FACT_CLASS", "COMPUTED_FACT_CLASS",
    "CONFLICT_CLASS", "HYPOTHESIS_CLASS", "INTERPRETATION_CLASS",
    "LIMITATION_CLASS", "MANAGEMENT_QUESTION_CLASS", "OWNER_CONTRACT",
    "OWNER_DOMAIN", "PUBLICATION_CONTRACT_VERSION", "UNKNOWN_CLASS",
    "BuyerIntelligencePublication", "BuyerIntelligencePublicationError",
    "BuyerIntelligencePublicationFailureCode", "BuyerIntelligencePublicationManifest",
    "publish_buyer_intelligence", "validate_buyer_intelligence_publication",
]
