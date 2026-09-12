"""Immutable owner publication for validated Opportunity Intelligence analysis.

Publication exposes exact Opportunity Intelligence semantics and relationships
to Governed Reference Resolution. It performs no analysis, inference, repair,
persistence, presentation, or transfer of upstream authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Iterable, Mapping

from decision_analyst import (
    AnalystAssumption,
    AnalystHypothesis,
    AnalystReasoning,
    AnalystUnknowns,
    DecisionAnalysis,
    ManagementQuestion,
)
from decision_intelligence import (
    AlternativeHypothesis,
    DecisionStatement,
    EvidenceSupport,
    ReasoningGaps,
    StatementSource,
    StatementType,
)
from governed_reference_resolution import (
    AuthorityClass,
    GovernedObject,
    GovernedObjectReference,
    GovernedRelationship,
    GovernedResolutionError,
    GovernedSnapshot,
    RelationshipKind,
    ResolutionContext,
    ResolutionRequest,
    SemanticField,
    SemanticValue,
    SemanticValueKind,
    create_governed_object,
    create_governed_snapshot,
    create_resolution_context,
    reference_to,
    resolve_governed_reference,
)
from opportunity_intelligence import ANALYST_ID, ANALYST_VERSION


OWNER_DOMAIN = "opportunity-intelligence"
OWNER_CONTRACT = "opportunity-intelligence-analyst"
PUBLICATION_CONTRACT_VERSION = "1.1.1"
PUBLICATION_CONTEXT_VERSION = "1.0.0"
_ZERO_DIGEST = "0" * 64
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class PublicationFailureCode(str, Enum):
    INVALID_ANALYSIS = "INVALID_ANALYSIS"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    DUPLICATE_IDENTITY = "DUPLICATE_IDENTITY"
    MISSING_SEMANTIC_CONTENT = "MISSING_SEMANTIC_CONTENT"
    BROKEN_RELATIONSHIP = "BROKEN_RELATIONSHIP"
    INCOMPATIBLE_SNAPSHOT = "INCOMPATIBLE_SNAPSHOT"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    INVALID_PUBLICATION = "INVALID_PUBLICATION"


class OpportunityPublicationError(ValueError):
    """Controlled fail-closed Opportunity Intelligence publication failure."""

    def __init__(self, code: PublicationFailureCode, message: str) -> None:
        self.code = code
        super().__init__(message)


def _fail(code: PublicationFailureCode, message: str):
    raise OpportunityPublicationError(code, message)


def _canonical(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {item.name: _canonical(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    if isinstance(value, frozenset):
        return sorted(_canonical(item) for item in value)
    if isinstance(value, Mapping):
        return {str(key): _canonical(value[key]) for key in sorted(value)}
    return value


def _json(value) -> str:
    try:
        return json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        _fail(PublicationFailureCode.MISSING_SEMANTIC_CONTENT,
              f"semantic content is not canonically serializable: {exc}")


def _sha(value) -> str:
    return sha256(_json(value).encode("utf-8")).hexdigest()


def _semantic_value(value) -> SemanticValue:
    if isinstance(value, Enum):
        return SemanticValue(SemanticValueKind.ENUM, value.value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            _fail(PublicationFailureCode.MISSING_SEMANTIC_CONTENT,
                  "published datetime values must be timezone-aware")
        return SemanticValue(SemanticValueKind.DATETIME, value.isoformat())
    if value is None:
        return SemanticValue(SemanticValueKind.NULL)
    if type(value) is bool:
        return SemanticValue(SemanticValueKind.BOOLEAN, value)
    if type(value) is int:
        return SemanticValue(SemanticValueKind.INTEGER, value)
    if isinstance(value, str):
        return SemanticValue(SemanticValueKind.STRING, value)
    if is_dataclass(value):
        semantic_fields = tuple(sorted(
            (SemanticField(item.name, _semantic_value(getattr(value, item.name)))
             for item in fields(value)),
            key=lambda item: item.name,
        ))
        return SemanticValue(SemanticValueKind.OBJECT, fields=semantic_fields)
    if isinstance(value, tuple):
        return SemanticValue(SemanticValueKind.ARRAY,
                             items=tuple(_semantic_value(item) for item in value))
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            _fail(PublicationFailureCode.MISSING_SEMANTIC_CONTENT,
                  "published semantic mappings require string field names")
        semantic_fields = tuple(sorted(
            (SemanticField(key, _semantic_value(item)) for key, item in value.items()),
            key=lambda item: item.name,
        ))
        return SemanticValue(SemanticValueKind.OBJECT, fields=semantic_fields)
    _fail(PublicationFailureCode.MISSING_SEMANTIC_CONTENT,
          f"unsupported semantic value type: {type(value).__name__}")


def _semantic_fields(values: Mapping[str, object]) -> tuple[SemanticField, ...]:
    if not values:
        _fail(PublicationFailureCode.MISSING_SEMANTIC_CONTENT,
              "published objects require semantic fields")
    return tuple(sorted(
        (SemanticField(name, _semantic_value(value)) for name, value in values.items()),
        key=lambda item: item.name,
    ))


def _dataclass_semantics(value) -> dict[str, object]:
    if not is_dataclass(value):
        _fail(PublicationFailureCode.MISSING_SEMANTIC_CONTENT,
              "published analytical objects must be typed dataclass values")
    return {item.name: getattr(value, item.name) for item in fields(value)}


def _analysis_semantics(analysis: DecisionAnalysis) -> dict[str, object]:
    """Return owner-declared meaning without operational execution metadata."""
    values = _dataclass_semantics(analysis)
    values.pop("execution_timestamp", None)
    return values


def _revalidate_analysis(analysis: DecisionAnalysis) -> None:
    """Re-run nested owner contracts for replayed or imported object graphs."""
    def support(value: EvidenceSupport) -> EvidenceSupport:
        return EvidenceSupport(**_dataclass_semantics(value))

    def statement(value: DecisionStatement) -> DecisionStatement:
        values = _dataclass_semantics(value)
        values["source"] = StatementSource(**_dataclass_semantics(value.source))
        values["evidence_support"] = tuple(support(item)
                                             for item in value.evidence_support)
        values["alternative_hypotheses"] = tuple(
            AlternativeHypothesis(**_dataclass_semantics(item))
            for item in value.alternative_hypotheses)
        values["reasoning_gaps"] = ReasoningGaps(
            **_dataclass_semantics(value.reasoning_gaps))
        return DecisionStatement(**values)

    try:
        computed = tuple(statement(item) for item in analysis.computed_facts)
        inferences = tuple(AnalystReasoning(
            statement(item.statement),
            item.support_status,
        ) for item in analysis.inferences)
        hypotheses = tuple(AnalystHypothesis(
            item.hypothesis_id,
            item.description,
            tuple(support(value) for value in item.supporting_evidence),
            tuple(support(value) for value in item.contradicting_evidence),
            item.confidence,
            item.support_status,
            item.limitations,
        ) for item in analysis.hypotheses)
        assumptions = tuple(AnalystAssumption(**_dataclass_semantics(item))
                            for item in analysis.assumptions)
        questions = tuple(ManagementQuestion(**_dataclass_semantics(item))
                          for item in analysis.unanswered_questions)
        unknowns = AnalystUnknowns(**_dataclass_semantics(analysis.unknowns))
        rebuilt = DecisionAnalysis(
            analysis.analysis_id,
            analysis.analyst_id,
            analysis.execution_timestamp,
            analysis.overall_confidence,
            tuple(support(item) for item in analysis.evidence_used),
            computed,
            inferences,
            hypotheses,
            analysis.recommendations,
            analysis.limitations,
            assumptions,
            questions,
            unknowns,
        )
    except (TypeError, ValueError, AttributeError) as exc:
        _fail(PublicationFailureCode.MISSING_SEMANTIC_CONTENT,
              f"analysis contains invalid or incomplete semantic content: {exc}")
    if rebuilt != analysis:
        _fail(PublicationFailureCode.INVALID_ANALYSIS,
              "analysis semantics changed during owner-contract validation")


def _support_key(value: EvidenceSupport) -> tuple[str, str, tuple[str, ...]]:
    return value.entity_type.value, value.entity_id, value.evidence_ids


@dataclass(frozen=True, slots=True)
class OpportunitySupportBinding:
    """Explicit owner references for one existing DecisionAnalysis support value."""

    support: EvidenceSupport
    entity_reference: GovernedObjectReference
    evidence_references: tuple[GovernedObjectReference, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.support, EvidenceSupport):
            _fail(PublicationFailureCode.BROKEN_RELATIONSHIP,
                  "support binding requires EvidenceSupport")
        if not isinstance(self.entity_reference, GovernedObjectReference):
            _fail(PublicationFailureCode.BROKEN_RELATIONSHIP,
                  "support binding requires an entity reference")
        if self.entity_reference.object_id != self.support.entity_id:
            _fail(PublicationFailureCode.BROKEN_RELATIONSHIP,
                  "support entity identity does not match its governed reference")
        if not isinstance(self.evidence_references, tuple) or any(
                not isinstance(item, GovernedObjectReference)
                for item in self.evidence_references):
            _fail(PublicationFailureCode.BROKEN_RELATIONSHIP,
                  "evidence references must be an immutable tuple")
        expected = tuple(sorted(self.evidence_references,
                                key=lambda item: item.identity_key))
        if self.evidence_references != expected:
            _fail(PublicationFailureCode.INVALID_PUBLICATION,
                  "evidence references are not canonically ordered")
        identities = tuple(item.identity_key for item in self.evidence_references)
        if len(identities) != len(set(identities)):
            _fail(PublicationFailureCode.DUPLICATE_IDENTITY,
                  "support binding contains duplicate evidence references")
        if (len(self.evidence_references) != len(self.support.evidence_ids)
                or {item.object_id for item in self.evidence_references}
                != set(self.support.evidence_ids)):
            _fail(PublicationFailureCode.BROKEN_RELATIONSHIP,
                  "support evidence IDs do not match their governed references")


@dataclass(frozen=True, slots=True)
class PublicationManifestObject:
    object_class: str
    object_id: str
    object_digest: str


@dataclass(frozen=True, slots=True)
class PublicationManifestRelationship:
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
class OpportunityPublicationManifest:
    owner_domain: str
    owner_contract: str
    contract_version: str
    analysis_id: str
    analyst_version: str
    analysis_digest: str
    support_bindings_digest: str
    authoritative_context_id: str
    authoritative_context_digest: str
    publication_snapshot_id: str
    publication_snapshot_digest: str
    objects: tuple[PublicationManifestObject, ...]
    relationships: tuple[PublicationManifestRelationship, ...]

    def __post_init__(self) -> None:
        digests = (self.analysis_digest, self.support_bindings_digest,
                   self.authoritative_context_digest, self.publication_snapshot_digest)
        if any(not isinstance(item, str) or not _DIGEST.fullmatch(item)
               for item in digests):
            _fail(PublicationFailureCode.DIGEST_MISMATCH,
                  "publication manifest contains an invalid digest")
        if (not isinstance(self.objects, tuple) or not self.objects
                or any(not isinstance(item, PublicationManifestObject)
                       for item in self.objects)):
            _fail(PublicationFailureCode.INVALID_PUBLICATION,
                  "publication manifest requires immutable object entries")
        if self.objects != tuple(sorted(
                self.objects, key=lambda item: (item.object_class, item.object_id))):
            _fail(PublicationFailureCode.INVALID_PUBLICATION,
                  "publication manifest objects are not canonically ordered")
        object_keys = tuple((item.object_class, item.object_id) for item in self.objects)
        if len(object_keys) != len(set(object_keys)):
            _fail(PublicationFailureCode.DUPLICATE_IDENTITY,
                  "publication manifest contains duplicate object identities")
        if (not isinstance(self.relationships, tuple)
                or any(not isinstance(item, PublicationManifestRelationship)
                       for item in self.relationships)):
            _fail(PublicationFailureCode.INVALID_PUBLICATION,
                  "publication relationships must be an immutable tuple")
        if self.relationships != tuple(sorted(
                self.relationships, key=lambda item: item.order_key)):
            _fail(PublicationFailureCode.INVALID_PUBLICATION,
                  "publication relationships are not canonically ordered")
        relationship_keys = tuple(item.order_key for item in self.relationships)
        if len(relationship_keys) != len(set(relationship_keys)):
            _fail(PublicationFailureCode.DUPLICATE_IDENTITY,
                  "publication manifest contains duplicate relationships")

    def to_dict(self) -> dict:
        return _canonical(self)

    def to_json(self) -> str:
        return _json(self)


@dataclass(frozen=True, slots=True)
class OpportunityIntelligencePublication:
    publication_id: str
    analysis_id: str
    analyst_version: str
    authoritative_context: ResolutionContext
    authoritative_context_id: str
    authoritative_context_digest: str
    snapshot: GovernedSnapshot
    manifest: OpportunityPublicationManifest
    references: tuple[GovernedObjectReference, ...]
    resolution_context: ResolutionContext
    execution_timestamp: datetime = field(compare=False)

    def __post_init__(self) -> None:
        validate_opportunity_intelligence_publication(self)

    def reference_for(self, object_class: str,
                      object_id: str) -> GovernedObjectReference:
        matches = tuple(item for item in self.references
                        if item.object_class == object_class and item.object_id == object_id)
        if len(matches) != 1:
            _fail(PublicationFailureCode.BROKEN_RELATIONSHIP,
                  f"published object {object_class}/{object_id} is not uniquely available")
        return matches[0]

    def request_for(self, object_class: str, object_id: str,
                    *, expected_authority: AuthorityClass,
                    required_semantic_fields: Iterable[str] = (),
                    required_relationship_kinds: Iterable[RelationshipKind] = ()) -> ResolutionRequest:
        return ResolutionRequest(
            self.reference_for(object_class, object_id),
            self.resolution_context.context_id,
            self.resolution_context.context_digest,
            expected_authority,
            tuple(sorted(required_semantic_fields)),
            tuple(sorted(required_relationship_kinds, key=lambda item: item.value)),
        )

    def to_dict(self) -> dict:
        return _canonical(self)

    def to_json(self) -> str:
        return _json(self)


@dataclass(frozen=True, slots=True)
class _ObjectSpec:
    object_class: str
    object_id: str
    authority: AuthorityClass
    semantics: Mapping[str, object]
    relationships: tuple[GovernedRelationship, ...] = ()


def _find_context_object(reference: GovernedObjectReference,
                         context: ResolutionContext) -> GovernedObject:
    snapshots = tuple(item for item in context.snapshots
                      if item.owner_domain == reference.owner_domain
                      and item.owner_contract == reference.owner_contract
                      and item.contract_version == reference.contract_version
                      and item.snapshot_id == reference.snapshot_id
                      and item.snapshot_digest == reference.snapshot_digest)
    if len(snapshots) != 1:
        _fail(PublicationFailureCode.INCOMPATIBLE_SNAPSHOT,
              f"reference {reference.object_id} is outside the authoritative context")
    objects = tuple(item for item in snapshots[0].objects
                    if item.object_class == reference.object_class
                    and item.object_id == reference.object_id
                    and item.object_digest == reference.object_digest)
    if len(objects) != 1:
        _fail(PublicationFailureCode.BROKEN_RELATIONSHIP,
              f"reference {reference.object_id} does not resolve exactly")
    try:
        resolve_governed_reference(
            ResolutionRequest(reference, context.context_id, context.context_digest,
                              objects[0].authority),
            context,
        )
    except GovernedResolutionError as exc:
        _fail(PublicationFailureCode.BROKEN_RELATIONSHIP,
              f"reference {reference.object_id} does not close: {exc.code.value}")
    return objects[0]


def _validate_bindings(analysis: DecisionAnalysis,
                       bindings: tuple[OpportunitySupportBinding, ...],
                       context: ResolutionContext) -> dict[EvidenceSupport, OpportunitySupportBinding]:
    if not isinstance(bindings, tuple) or any(
            not isinstance(item, OpportunitySupportBinding) for item in bindings):
        _fail(PublicationFailureCode.BROKEN_RELATIONSHIP,
              "support bindings must be an immutable tuple")
    if bindings != tuple(sorted(bindings, key=lambda item: _support_key(item.support))):
        _fail(PublicationFailureCode.INVALID_PUBLICATION,
              "support bindings are not canonically ordered")
    if len(analysis.evidence_used) != len(set(analysis.evidence_used)):
        _fail(PublicationFailureCode.DUPLICATE_IDENTITY,
              "analysis contains duplicate evidence support identities")
    binding_map = {item.support: item for item in bindings}
    if len(binding_map) != len(bindings):
        _fail(PublicationFailureCode.DUPLICATE_IDENTITY,
              "duplicate support bindings are not permitted")
    if set(binding_map) != set(analysis.evidence_used):
        _fail(PublicationFailureCode.BROKEN_RELATIONSHIP,
              "support bindings must exactly cover analysis evidence_used")
    for binding in bindings:
        _find_context_object(binding.entity_reference, context)
        for reference in binding.evidence_references:
            target = _find_context_object(reference, context)
            if target.authority != AuthorityClass.EVIDENCE:
                _fail(PublicationFailureCode.BROKEN_RELATIONSHIP,
                      f"evidence reference {reference.object_id} lacks evidence authority")
    return binding_map


def _support_relationships(supports: Iterable[EvidenceSupport], *, role: str,
                           binding_map: Mapping[EvidenceSupport, OpportunitySupportBinding]
                           ) -> tuple[GovernedRelationship, ...]:
    relationships = []
    ordinal = 0
    support_values = tuple(supports)
    if len(support_values) != len(set(support_values)):
        _fail(PublicationFailureCode.DUPLICATE_IDENTITY,
              f"{role} contains duplicate support relationships")
    for support in sorted(support_values, key=_support_key):
        binding = binding_map.get(support)
        if binding is None:
            _fail(PublicationFailureCode.BROKEN_RELATIONSHIP,
                  f"missing governed binding for support {support.entity_id}")
        relationships.append(GovernedRelationship(
            RelationshipKind.SUPPORT, f"{role}-entity", binding.entity_reference, ordinal))
        ordinal += 1
        for evidence_reference in binding.evidence_references:
            relationships.append(GovernedRelationship(
                RelationshipKind.EVIDENCE_SUPPORT, f"{role}-evidence",
                evidence_reference, ordinal))
            ordinal += 1
    return tuple(sorted(relationships, key=lambda item: item.order_key))


def _placeholder_reference(snapshot_id: str, object_class: str,
                           object_id: str) -> GovernedObjectReference:
    return GovernedObjectReference(
        OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION,
        snapshot_id, _ZERO_DIGEST, object_class, object_id, _ZERO_DIGEST,
    )


def _internal_relationship(snapshot_id: str, object_class: str, object_id: str,
                           kind: RelationshipKind, role: str,
                           ordinal: int) -> GovernedRelationship:
    return GovernedRelationship(kind, role,
                                _placeholder_reference(snapshot_id, object_class, object_id),
                                ordinal)


def _statement_specs(statement: DecisionStatement, object_class: str,
                     authority: AuthorityClass,
                     binding_map: Mapping[EvidenceSupport, OpportunitySupportBinding],
                     snapshot_id: str,
                     owned_ids: Mapping[str, tuple[str, str]]) -> tuple[_ObjectSpec, ...]:
    relationships = list(_support_relationships(
        statement.evidence_support, role="statement-support", binding_map=binding_map))
    ordinal = len(relationships)
    for supporting_id in statement.supporting_fact_ids:
        target = owned_ids.get(supporting_id)
        if target is not None:
            relationships.append(_internal_relationship(
                snapshot_id, target[0], target[1], RelationshipKind.SUPPORT,
                "supporting-fact", ordinal))
        else:
            candidates = tuple(binding.entity_reference for support, binding in binding_map.items()
                               if support.entity_id == supporting_id)
            if len(candidates) != 1:
                _fail(PublicationFailureCode.BROKEN_RELATIONSHIP,
                      f"supporting fact {supporting_id} has no exact governed target")
            relationships.append(GovernedRelationship(
                RelationshipKind.SUPPORT, "supporting-fact", candidates[0], ordinal))
        ordinal += 1
    for alternative in statement.alternative_hypotheses:
        relationships.append(_internal_relationship(
            snapshot_id, "alternative-hypothesis", alternative.hypothesis_id,
            RelationshipKind.RELATED, "alternative-hypothesis", ordinal))
        ordinal += 1
    main = _ObjectSpec(
        object_class, statement.statement_id, authority,
        _dataclass_semantics(statement),
        tuple(sorted(relationships, key=lambda item: item.order_key)),
    )
    alternatives = []
    for alternative in statement.alternative_hypotheses:
        evidence_references = []
        for evidence_id in alternative.evidence_ids:
            matches = tuple(reference
                            for binding in binding_map.values()
                            for reference in binding.evidence_references
                            if reference.object_id == evidence_id)
            unique = {item.identity_key: item for item in matches}
            if len(unique) != 1:
                _fail(PublicationFailureCode.BROKEN_RELATIONSHIP,
                      f"alternative evidence {evidence_id} has no exact governed target")
            evidence_references.append(next(iter(unique.values())))
        alt_relationships = tuple(sorted((GovernedRelationship(
            RelationshipKind.EVIDENCE_SUPPORT, "alternative-evidence", reference, index)
            for index, reference in enumerate(sorted(
                evidence_references, key=lambda item: item.identity_key))),
            key=lambda item: item.order_key))
        alternatives.append(_ObjectSpec(
            "alternative-hypothesis", alternative.hypothesis_id,
            AuthorityClass.HYPOTHESIS, _dataclass_semantics(alternative), alt_relationships))
    return (main, *alternatives)


def _publication_snapshot_seed(*, analysis_id: str, analysis_digest: str,
                               authoritative_context: ResolutionContext,
                               support_bindings_digest: str) -> dict:
    return {
        "owner_domain": OWNER_DOMAIN,
        "owner_contract": OWNER_CONTRACT,
        "contract_version": PUBLICATION_CONTRACT_VERSION,
        "analysis_id": analysis_id,
        "analysis_digest": analysis_digest,
        "authoritative_context_id": authoritative_context.context_id,
        "authoritative_context_digest": authoritative_context.context_digest,
        "support_bindings_digest": support_bindings_digest,
    }


def publish_opportunity_intelligence(
        analysis: DecisionAnalysis, *, analyst_version: str,
        authoritative_context: ResolutionContext,
        support_bindings: Iterable[OpportunitySupportBinding],
        ) -> OpportunityIntelligencePublication:
    """Publish one validated Opportunity Intelligence analysis without changing it."""
    if not isinstance(analysis, DecisionAnalysis) or analysis.analyst_id != ANALYST_ID:
        _fail(PublicationFailureCode.INVALID_ANALYSIS,
              "publication requires an Opportunity Intelligence DecisionAnalysis")
    if analyst_version != ANALYST_VERSION:
        _fail(PublicationFailureCode.VERSION_MISMATCH,
              "analysis version does not match the supported Opportunity Intelligence analyst")
    if not isinstance(authoritative_context, ResolutionContext):
        _fail(PublicationFailureCode.INCOMPATIBLE_SNAPSHOT,
              "publication requires an immutable authoritative resolution context")
    if analysis.recommendations:
        _fail(PublicationFailureCode.INVALID_ANALYSIS,
              "Opportunity Intelligence publication cannot contain recommendations")
    if any(item.statement_type == StatementType.HUMAN_DECISION
           for item in analysis.computed_facts):
        _fail(PublicationFailureCode.INVALID_ANALYSIS,
              "Opportunity Intelligence publication cannot contain human decisions")
    _revalidate_analysis(analysis)

    bindings = tuple(support_bindings)
    binding_map = _validate_bindings(analysis, bindings, authoritative_context)
    analysis_digest = _sha(_analysis_semantics(analysis))
    support_bindings_digest = _sha(bindings)
    snapshot_id = "oi-publication-" + _sha(_publication_snapshot_seed(
        analysis_id=analysis.analysis_id,
        analysis_digest=analysis_digest,
        authoritative_context=authoritative_context,
        support_bindings_digest=support_bindings_digest,
    ))

    owned_ids: dict[str, tuple[str, str]] = {}
    identities = []
    identities.extend((item.statement_id, "computed-fact", item.statement_id)
                      for item in analysis.computed_facts)
    identities.extend((item.statement.statement_id, "inference", item.statement.statement_id)
                      for item in analysis.inferences)
    identities.extend((item.hypothesis_id, "hypothesis", item.hypothesis_id)
                      for item in analysis.hypotheses)
    identities.extend((item.assumption_id, "assumption", item.assumption_id)
                      for item in analysis.assumptions)
    identities.extend((item.question_id, "management-question", item.question_id)
                      for item in analysis.unanswered_questions)
    for statement in (*analysis.computed_facts,
                      *(item.statement for item in analysis.inferences)):
        identities.extend((item.hypothesis_id, "alternative-hypothesis", item.hypothesis_id)
                          for item in statement.alternative_hypotheses)
    for object_id, object_class, exact_id in identities:
        if object_id in owned_ids:
            _fail(PublicationFailureCode.DUPLICATE_IDENTITY,
                  f"duplicate published analytical identity: {object_id}")
        owned_ids[object_id] = (object_class, exact_id)

    unknowns_id = f"{analysis.analysis_id}/unknowns"
    limitations_id = f"{analysis.analysis_id}/limitations"
    analysis_object_id = analysis.analysis_id
    for reserved_id, object_class in ((unknowns_id, "unknowns"),
                                      (analysis_object_id, "analysis")):
        if reserved_id in owned_ids:
            _fail(PublicationFailureCode.DUPLICATE_IDENTITY,
                  f"duplicate published analytical identity: {reserved_id}")
        owned_ids[reserved_id] = (object_class, reserved_id)
    if analysis.limitations:
        if limitations_id in owned_ids:
            _fail(PublicationFailureCode.DUPLICATE_IDENTITY,
                  f"duplicate published analytical identity: {limitations_id}")
        owned_ids[limitations_id] = ("limitations", limitations_id)

    specs: list[_ObjectSpec] = []
    for statement in analysis.computed_facts:
        specs.extend(_statement_specs(
            statement, "computed-fact", AuthorityClass.COMPUTED_FACT,
            binding_map, snapshot_id, owned_ids))
    for reasoning in analysis.inferences:
        statement_specs = _statement_specs(
            reasoning.statement, "inference", AuthorityClass.INFERENCE,
            binding_map, snapshot_id, owned_ids)
        main = statement_specs[0]
        specs.append(_ObjectSpec(
            main.object_class, main.object_id, main.authority,
            _dataclass_semantics(reasoning), main.relationships))
        specs.extend(statement_specs[1:])
    for hypothesis in analysis.hypotheses:
        relationships = []
        for support_status, support_values in (
                ("hypothesis-supporting", hypothesis.supporting_evidence),
                ("hypothesis-contradicting", hypothesis.contradicting_evidence)):
            kind = (RelationshipKind.SUPPORT if support_status.endswith("supporting")
                    else RelationshipKind.CONTRADICTION)
            for relationship in _support_relationships(
                    support_values, role=support_status, binding_map=binding_map):
                relationships.append(GovernedRelationship(
                    kind if relationship.kind == RelationshipKind.SUPPORT else relationship.kind,
                    relationship.role, relationship.target, relationship.ordinal))
        specs.append(_ObjectSpec(
            "hypothesis", hypothesis.hypothesis_id, AuthorityClass.HYPOTHESIS,
            _dataclass_semantics(hypothesis),
            tuple(sorted(relationships, key=lambda item: item.order_key))))
    specs.extend(_ObjectSpec(
        "assumption", item.assumption_id, AuthorityClass.ASSUMPTION,
        _dataclass_semantics(item)) for item in analysis.assumptions)

    unknown_relationships = []
    unknown_ids = tuple(sorted({
        *analysis.unknowns.missing_evidence,
        *analysis.unknowns.unresolved_conflict_ids,
        *analysis.unknowns.ambiguous_observation_ids,
    }))
    # unresolved_conflict_ids is the one AnalystUnknowns field that can
    # legitimately name an entity with no governed representation anywhere:
    # Stage C's own cross-document reconciliation pass (CONF-DATE-N,
    # CONF-EVAL-N, CONF-SUB-N, CONF-MAND-N, CONF-COMM-N, CONF-SCOPE-N,
    # CONF-HYGIENE-N, CONF-CLAUSE-N -- see extractor.detect_document_conflicts
    # and contract_hygiene.structured_*_conflicts) produces advisory review
    # items that were never designed to become their own governed,
    # individually-publishable objects -- unlike the FIELD_KINDS conflicts
    # canonical_opportunity.py's own resolve_canonical_opportunity() detects
    # and Canonical Opportunity Publication genuinely does publish. Opportunity
    # Intelligence already marks every conflict-sourced support FUTURE_ENTITY
    # (see opportunity_intelligence.py's _entity_type fallback) precisely
    # because some of them are known, by design, to possibly never resolve to
    # a governed object -- not because of an oversight. missing_evidence
    # (requirements, always published by Opportunity Structure Publication)
    # and ambiguous_observation_ids (observations, always published by
    # Canonical Opportunity Publication) carry no such exception and must
    # keep failing closed exactly as before if they cannot resolve.
    conflict_ids = set(analysis.unknowns.unresolved_conflict_ids)
    for unknown_id in unknown_ids:
        candidates = tuple(binding.entity_reference for support, binding in binding_map.items()
                           if support.entity_id == unknown_id)
        unique = {item.identity_key: item for item in candidates}
        if len(unique) > 1:
            _fail(PublicationFailureCode.BROKEN_RELATIONSHIP,
                  f"unknown reference {unknown_id} matches more than one governed target; ambiguous")
        if not unique:
            if unknown_id in conflict_ids:
                # Honest, disclosed absence -- consistent with this conflict
                # never having been offered as citable evidence_used support
                # in the first place (opportunity_intelligence.py only links
                # governed conflicts). No relationship is fabricated.
                continue
            _fail(PublicationFailureCode.BROKEN_RELATIONSHIP,
                  f"unknown reference {unknown_id} has no exact governed target")
        unknown_relationships.append(GovernedRelationship(
            RelationshipKind.RELATED, "affected-entity", next(iter(unique.values())), len(unknown_relationships)))
    specs.append(_ObjectSpec(
        "unknowns", unknowns_id, AuthorityClass.UNKNOWN,
        _dataclass_semantics(analysis.unknowns), tuple(unknown_relationships)))
    if analysis.limitations:
        specs.append(_ObjectSpec(
            "limitations", limitations_id, AuthorityClass.LIMITATION,
            {"limitations": analysis.limitations}))

    for question in analysis.unanswered_questions:
        relationships = []
        for ordinal, related_id in enumerate(question.related_analysis_ids):
            target = owned_ids.get(related_id)
            if target is None:
                _fail(PublicationFailureCode.BROKEN_RELATIONSHIP,
                      f"management question target {related_id} is not published")
            relationships.append(_internal_relationship(
                snapshot_id, target[0], target[1], RelationshipKind.RELATED,
                "question-basis", ordinal))
        specs.append(_ObjectSpec(
            "management-question", question.question_id,
            AuthorityClass.MANAGEMENT_QUESTION,
            _dataclass_semantics(question), tuple(relationships)))

    contained = tuple(sorted(
        ((item.object_class, item.object_id) for item in specs),
        key=lambda item: (item[0], item[1])))
    analysis_relationships = list(_support_relationships(
        analysis.evidence_used, role="analysis-evidence", binding_map=binding_map))
    ordinal = len(analysis_relationships)
    for object_class, object_id in contained:
        analysis_relationships.append(_internal_relationship(
            snapshot_id, object_class, object_id, RelationshipKind.DEPENDENCY,
            "contains", ordinal))
        ordinal += 1
    specs.append(_ObjectSpec(
        "analysis", analysis_object_id, AuthorityClass.INFERENCE,
        {
            "analysis_id": analysis.analysis_id,
            "analyst_id": analysis.analyst_id,
            "analyst_version": analyst_version,
            "overall_confidence": analysis.overall_confidence,
        },
        tuple(sorted(analysis_relationships, key=lambda item: item.order_key)),
    ))

    object_keys = tuple((item.object_class, item.object_id) for item in specs)
    if len(object_keys) != len(set(object_keys)):
        _fail(PublicationFailureCode.DUPLICATE_IDENTITY,
              "publication contains duplicate object identities")
    objects = tuple(create_governed_object(
        owner_domain=OWNER_DOMAIN,
        owner_contract=OWNER_CONTRACT,
        contract_version=PUBLICATION_CONTRACT_VERSION,
        object_class=item.object_class,
        object_id=item.object_id,
        authority=item.authority,
        semantic_fields=_semantic_fields(item.semantics),
        relationships=item.relationships,
    ) for item in specs)
    try:
        snapshot = create_governed_snapshot(
            owner_domain=OWNER_DOMAIN,
            owner_contract=OWNER_CONTRACT,
            contract_version=PUBLICATION_CONTRACT_VERSION,
            snapshot_id=snapshot_id,
            objects=objects,
        )
    except GovernedResolutionError as exc:
        _fail(PublicationFailureCode.INVALID_PUBLICATION,
              f"publication snapshot is invalid: {exc.code.value}")

    references = tuple(reference_to(snapshot, item.object_class, item.object_id)
                       for item in snapshot.objects)
    manifest_objects = tuple(PublicationManifestObject(
        item.object_class, item.object_id, item.object_digest) for item in snapshot.objects)
    manifest_relationships = tuple(sorted((
        PublicationManifestRelationship(
            item.object_class, item.object_id, relationship.kind,
            relationship.role, relationship.ordinal, relationship.target)
        for item in snapshot.objects for relationship in item.relationships
    ), key=lambda item: item.order_key))
    manifest = OpportunityPublicationManifest(
        OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION,
        analysis.analysis_id, analyst_version, analysis_digest, support_bindings_digest,
        authoritative_context.context_id, authoritative_context.context_digest,
        snapshot.snapshot_id, snapshot.snapshot_digest,
        manifest_objects, manifest_relationships,
    )
    publication_id = "oi-publication-record-" + _sha({
        "analysis_id": analysis.analysis_id,
        "authoritative_context_digest": authoritative_context.context_digest,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_digest": snapshot.snapshot_digest,
    })
    resolution_context = create_resolution_context(
        context_id="oi-resolution-" + _sha({
            "authoritative_context": authoritative_context.context_digest,
            "publication_snapshot": snapshot.snapshot_digest,
        }),
        context_version=PUBLICATION_CONTEXT_VERSION,
        snapshots=(*authoritative_context.snapshots, snapshot),
    )
    return OpportunityIntelligencePublication(
        publication_id, analysis.analysis_id, analyst_version,
        authoritative_context,
        authoritative_context.context_id, authoritative_context.context_digest,
        snapshot, manifest, references, resolution_context,
        analysis.execution_timestamp,
    )


def validate_opportunity_intelligence_publication(
        publication: OpportunityIntelligencePublication,
        ) -> OpportunityIntelligencePublication:
    if not isinstance(publication.manifest, OpportunityPublicationManifest):
        _fail(PublicationFailureCode.INVALID_PUBLICATION,
              "publication manifest is invalid")
    if (not isinstance(publication.references, tuple)
            or any(not isinstance(item, GovernedObjectReference)
                   for item in publication.references)):
        _fail(PublicationFailureCode.INVALID_PUBLICATION,
              "publication references must be an immutable tuple")
    if not isinstance(publication.resolution_context, ResolutionContext):
        _fail(PublicationFailureCode.INCOMPATIBLE_SNAPSHOT,
              "publication resolution context is invalid")
    if not isinstance(publication.snapshot, GovernedSnapshot):
        _fail(PublicationFailureCode.INVALID_PUBLICATION,
              "publication snapshot is invalid")
    if (publication.snapshot.owner_domain, publication.snapshot.owner_contract,
            publication.snapshot.contract_version) != (
                OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION):
        _fail(PublicationFailureCode.VERSION_MISMATCH,
              "publication owner contract binding is invalid")
    if (publication.manifest.owner_domain, publication.manifest.owner_contract,
            publication.manifest.contract_version) != (
                OWNER_DOMAIN, OWNER_CONTRACT, PUBLICATION_CONTRACT_VERSION):
        _fail(PublicationFailureCode.VERSION_MISMATCH,
              "publication manifest owner contract binding is invalid")
    if publication.analysis_id != publication.manifest.analysis_id:
        _fail(PublicationFailureCode.INVALID_PUBLICATION,
              "publication analysis identity does not match its manifest")
    if publication.analyst_version != ANALYST_VERSION:
        _fail(PublicationFailureCode.VERSION_MISMATCH,
              "publication analyst version is unsupported")
    if (not isinstance(publication.execution_timestamp, datetime)
            or publication.execution_timestamp.tzinfo is None
            or publication.execution_timestamp.utcoffset() is None):
        _fail(PublicationFailureCode.INVALID_PUBLICATION,
              "publication execution timestamp must be timezone-aware operational metadata")
    if publication.manifest.analyst_version != publication.analyst_version:
        _fail(PublicationFailureCode.VERSION_MISMATCH,
              "publication manifest analyst version is inconsistent")
    if not isinstance(publication.authoritative_context, ResolutionContext):
        _fail(PublicationFailureCode.INCOMPATIBLE_SNAPSHOT,
              "publication authoritative context is invalid")
    if (publication.authoritative_context_id,
            publication.authoritative_context_digest) != (
                publication.authoritative_context.context_id,
                publication.authoritative_context.context_digest):
        _fail(PublicationFailureCode.INCOMPATIBLE_SNAPSHOT,
              "publication authoritative context identity is inconsistent")
    if (publication.authoritative_context_id,
            publication.authoritative_context_digest) != (
                publication.manifest.authoritative_context_id,
                publication.manifest.authoritative_context_digest):
        _fail(PublicationFailureCode.INCOMPATIBLE_SNAPSHOT,
              "publication authoritative context binding is inconsistent")
    if (publication.snapshot.snapshot_id, publication.snapshot.snapshot_digest) != (
            publication.manifest.publication_snapshot_id,
            publication.manifest.publication_snapshot_digest):
        _fail(PublicationFailureCode.DIGEST_MISMATCH,
              "publication snapshot does not match its manifest")
    expected_snapshot_id = "oi-publication-" + _sha(_publication_snapshot_seed(
        analysis_id=publication.analysis_id,
        analysis_digest=publication.manifest.analysis_digest,
        authoritative_context=publication.authoritative_context,
        support_bindings_digest=publication.manifest.support_bindings_digest,
    ))
    if publication.snapshot.snapshot_id != expected_snapshot_id:
        _fail(PublicationFailureCode.DIGEST_MISMATCH,
              "publication snapshot identity is inconsistent with its owner bindings")
    expected_objects = tuple(PublicationManifestObject(
        item.object_class, item.object_id, item.object_digest)
        for item in publication.snapshot.objects)
    if publication.manifest.objects != expected_objects:
        _fail(PublicationFailureCode.DIGEST_MISMATCH,
              "publication object manifest does not match its snapshot")
    expected_relationships = tuple(sorted((
        PublicationManifestRelationship(
            item.object_class, item.object_id, relationship.kind,
            relationship.role, relationship.ordinal, relationship.target)
        for item in publication.snapshot.objects for relationship in item.relationships
    ), key=lambda item: item.order_key))
    if publication.manifest.relationships != expected_relationships:
        _fail(PublicationFailureCode.BROKEN_RELATIONSHIP,
              "publication relationship manifest does not match its snapshot")
    expected_references = tuple(reference_to(
        publication.snapshot, item.object_class, item.object_id)
        for item in publication.snapshot.objects)
    if publication.references != expected_references:
        _fail(PublicationFailureCode.DIGEST_MISMATCH,
              "publication references do not match the immutable snapshot")
    expected_context = create_resolution_context(
        context_id="oi-resolution-" + _sha({
            "authoritative_context": publication.authoritative_context_digest,
            "publication_snapshot": publication.snapshot.snapshot_digest,
        }),
        context_version=PUBLICATION_CONTEXT_VERSION,
        snapshots=(*publication.authoritative_context.snapshots, publication.snapshot),
    )
    if publication.resolution_context != expected_context:
        _fail(PublicationFailureCode.INCOMPATIBLE_SNAPSHOT,
              "publication resolution context does not match its bound snapshots")
    expected_publication_id = "oi-publication-record-" + _sha({
        "analysis_id": publication.analysis_id,
        "authoritative_context_digest": publication.authoritative_context_digest,
        "snapshot_id": publication.snapshot.snapshot_id,
        "snapshot_digest": publication.snapshot.snapshot_digest,
    })
    if publication.publication_id != expected_publication_id:
        _fail(PublicationFailureCode.DIGEST_MISMATCH,
              "publication identity is inconsistent with its immutable bindings")
    for item, reference in zip(publication.snapshot.objects, publication.references):
        try:
            resolve_governed_reference(
                ResolutionRequest(reference,
                                  publication.resolution_context.context_id,
                                  publication.resolution_context.context_digest,
                                  item.authority,
                                  tuple(field.name for field in item.semantic_fields),
                                  tuple(sorted({relationship.kind for relationship in item.relationships},
                                               key=lambda kind: kind.value))),
                publication.resolution_context,
            )
        except GovernedResolutionError as exc:
            _fail(PublicationFailureCode.BROKEN_RELATIONSHIP,
                  f"published object {item.object_id} does not resolve: {exc.code.value}")
    return publication


__all__ = [
    "ANALYST_VERSION",
    "OWNER_CONTRACT",
    "OWNER_DOMAIN",
    "PUBLICATION_CONTRACT_VERSION",
    "OpportunityIntelligencePublication",
    "OpportunityPublicationError",
    "OpportunityPublicationManifest",
    "OpportunitySupportBinding",
    "PublicationFailureCode",
    "PublicationManifestObject",
    "PublicationManifestRelationship",
    "publish_opportunity_intelligence",
    "validate_opportunity_intelligence_publication",
]
