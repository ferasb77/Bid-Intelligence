"""Immutable, evidence-closed contracts for Buyer Intelligence v1.

This module validates governed analysis supplied to it. It performs no source
retrieval, model call, persistence, presentation, or autonomous reasoning.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Any, Callable, Iterable

from buyer_domain import BUYER_DOMAIN_VERSION, CanonicalBuyer
from buyer_evidence import (
    BUYER_EVIDENCE_VERSION, AuthenticityStatus, BuyerEvidenceSet,
    EvidenceAuthority, FreshnessStatus, SourceCategory,
)


BUYER_INTELLIGENCE_VERSION = "buyer-intelligence/1"


class BuyerIntelligenceValidationError(ValueError):
    """Raised when a Buyer Intelligence contract violates its authority boundary."""


class FactClass(str, Enum):
    AUTHORITATIVE_BUYER_FACT = "AUTHORITATIVE_BUYER_FACT"
    PUBLIC_ORGANIZATIONAL_INFORMATION = "PUBLIC_ORGANIZATIONAL_INFORMATION"
    VERIFIED_PROCUREMENT_CONTEXT = "VERIFIED_PROCUREMENT_CONTEXT"


class FactKind(str, Enum):
    IDENTITY = "IDENTITY"
    MANDATE = "MANDATE"
    RESPONSIBILITY = "RESPONSIBILITY"
    ORGANIZATIONAL_FUNCTION = "ORGANIZATIONAL_FUNCTION"
    PUBLISHED_PRIORITY = "PUBLISHED_PRIORITY"
    ORGANIZATIONAL_CAPABILITY = "ORGANIZATIONAL_CAPABILITY"
    GOVERNANCE = "GOVERNANCE"
    ACCESSIBILITY_COMMITMENT = "ACCESSIBILITY_COMMITMENT"
    PUBLIC_INITIATIVE = "PUBLIC_INITIATIVE"
    ORGANIZATIONAL_RELATIONSHIP = "ORGANIZATIONAL_RELATIONSHIP"
    CURRENT_PROCUREMENT_ROLE = "CURRENT_PROCUREMENT_ROLE"


class InterpretationKind(str, Enum):
    OPPORTUNITY_MANDATE_RELATIONSHIP = "OPPORTUNITY_MANDATE_RELATIONSHIP"
    RELEVANT_ORGANIZATIONAL_FUNCTION = "RELEVANT_ORGANIZATIONAL_FUNCTION"
    PUBLISHED_PRIORITY_CONTEXT = "PUBLISHED_PRIORITY_CONTEXT"
    ORGANIZATIONAL_CONTEXT = "ORGANIZATIONAL_CONTEXT"
    GOVERNANCE_CONTEXT = "GOVERNANCE_CONTEXT"
    PROCUREMENT_CONTEXT = "PROCUREMENT_CONTEXT"


class Confidence(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class SupportStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    CONFLICTING = "CONFLICTING"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"


class UnknownKind(str, Enum):
    MISSING_BUYER_EVIDENCE = "MISSING_BUYER_EVIDENCE"
    UNAVAILABLE_PUBLIC_INFORMATION = "UNAVAILABLE_PUBLIC_INFORMATION"
    AMBIGUOUS_ORGANIZATIONAL_OWNERSHIP = "AMBIGUOUS_ORGANIZATIONAL_OWNERSHIP"
    CONFLICTING_PUBLIC_STATEMENTS = "CONFLICTING_PUBLIC_STATEMENTS"
    STALE_INFORMATION = "STALE_INFORMATION"
    UNKNOWN_OPPORTUNITY_RELATIONSHIP = "UNKNOWN_OPPORTUNITY_RELATIONSHIP"
    UNSUPPORTED_BUYER_INTENT = "UNSUPPORTED_BUYER_INTENT"


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{2,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_PROHIBITED = re.compile(
    r"\b(?:recommend(?:s|ed|ation)?|should\s+(?:bid|price|propose|pursue)|"
    r"bid\s*/?\s*no\s*bid|win\s+probability|likely\s+winner|evaluator\s+(?:wants|prefers)|"
    r"hidden\s+motivation|political\s+influence|pricing\s+strategy|proposal\s+strategy)\b",
    re.IGNORECASE,
)


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BuyerIntelligenceValidationError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise BuyerIntelligenceValidationError(f"{name} must not have surrounding whitespace")
    return value


def _stable_id(value: str, name: str) -> str:
    value = _required(value, name)
    if not _ID.fullmatch(value):
        raise BuyerIntelligenceValidationError(f"{name} must be a stable identifier")
    return value


def _safe_statement(value: str, name: str) -> str:
    value = _required(value, name)
    if _PROHIBITED.search(value):
        raise BuyerIntelligenceValidationError(f"{name} contains prohibited advice or prediction language")
    return value


def _ids(values: Iterable[str], name: str, *, required: bool = False) -> tuple[str, ...]:
    result = tuple(_stable_id(value, name) for value in values)
    if required and not result:
        raise BuyerIntelligenceValidationError(f"{name} must not be empty")
    if len(result) != len(set(result)):
        raise BuyerIntelligenceValidationError(f"{name} must not contain duplicates")
    return tuple(sorted(result))


def _objects(values: Iterable[Any], name: str, expected: type, key: Callable[[Any], str]) -> tuple[Any, ...]:
    result = tuple(values)
    if any(not isinstance(item, expected) for item in result):
        raise BuyerIntelligenceValidationError(f"{name} must contain {expected.__name__} values")
    keys = [key(item) for item in result]
    if len(keys) != len(set(keys)):
        raise BuyerIntelligenceValidationError(f"{name} contains duplicate identities")
    return tuple(sorted(result, key=key))


def _id(prefix: str, value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return prefix + sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class GovernedBuyerInputs:
    buyer: CanonicalBuyer
    evidence: BuyerEvidenceSet
    opportunity_id: str
    canonical_opportunity_version: str
    canonical_opportunity_digest: str
    opportunity_entity_ids: tuple[str, ...]
    procurement_evidence_ids: tuple[str, ...]
    procurement_package_digest: str
    evaluation_context_id: str
    source_date: date
    opportunity_analysis_id: str | None = None
    opportunity_analysis_version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.buyer, CanonicalBuyer) or self.buyer.contract_version != BUYER_DOMAIN_VERSION:
            raise BuyerIntelligenceValidationError("buyer must be a supported CanonicalBuyer")
        if not isinstance(self.evidence, BuyerEvidenceSet) or self.evidence.contract_version != BUYER_EVIDENCE_VERSION:
            raise BuyerIntelligenceValidationError("evidence must be a supported BuyerEvidenceSet")
        if self.evidence.buyer_id != self.buyer.buyer_id:
            raise BuyerIntelligenceValidationError("Canonical Buyer and Buyer Evidence identities differ")
        for name in ("opportunity_id", "evaluation_context_id"):
            _stable_id(getattr(self, name), name)
        _required(self.canonical_opportunity_version, "canonical_opportunity_version")
        if self.canonical_opportunity_version != "canonical-opportunity/1":
            raise BuyerIntelligenceValidationError("unsupported Canonical Opportunity version")
        for name in ("canonical_opportunity_digest", "procurement_package_digest"):
            digest = _required(getattr(self, name), name).lower()
            if not _DIGEST.fullmatch(digest):
                raise BuyerIntelligenceValidationError(f"{name} must be a SHA-256 digest")
            object.__setattr__(self, name, digest)
        object.__setattr__(self, "opportunity_entity_ids",
                           _ids(self.opportunity_entity_ids, "opportunity_entity_ids", required=True))
        object.__setattr__(self, "procurement_evidence_ids",
                           _ids(self.procurement_evidence_ids, "procurement_evidence_ids", required=True))
        if type(self.source_date) is not date:
            raise BuyerIntelligenceValidationError("source_date must be a date")
        if (self.opportunity_analysis_id is None) != (self.opportunity_analysis_version is None):
            raise BuyerIntelligenceValidationError("Opportunity Intelligence identity and version must appear together")
        if self.opportunity_analysis_id is not None:
            _stable_id(self.opportunity_analysis_id, "opportunity_analysis_id")
            if not re.fullmatch(r"1\.\d+\.\d+", self.opportunity_analysis_version or ""):
                raise BuyerIntelligenceValidationError("unsupported Opportunity Intelligence version")

    @property
    def evidence_ids(self) -> frozenset[str]:
        public = {
            *(item.source_id for item in self.evidence.sources),
            *(item.document_id for item in self.evidence.documents),
            *(item.citation_id for item in self.evidence.citations),
            *(item.extract_id for item in self.evidence.extracts),
        }
        return frozenset(public | set(self.procurement_evidence_ids))


@dataclass(frozen=True, slots=True, order=True)
class BuyerFact:
    fact_id: str
    fact_class: FactClass
    fact_kind: FactKind
    statement: str
    evidence_status: SupportStatus
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _stable_id(self.fact_id, "fact_id")
        if not isinstance(self.fact_class, FactClass) or not isinstance(self.fact_kind, FactKind):
            raise BuyerIntelligenceValidationError("fact class and kind must use supported values")
        permitted_kinds = {
            FactClass.AUTHORITATIVE_BUYER_FACT: {
                FactKind.IDENTITY, FactKind.MANDATE, FactKind.RESPONSIBILITY,
                FactKind.ORGANIZATIONAL_FUNCTION, FactKind.GOVERNANCE,
                FactKind.ORGANIZATIONAL_RELATIONSHIP,
            },
            FactClass.PUBLIC_ORGANIZATIONAL_INFORMATION: {
                FactKind.RESPONSIBILITY, FactKind.ORGANIZATIONAL_FUNCTION,
                FactKind.PUBLISHED_PRIORITY, FactKind.ORGANIZATIONAL_CAPABILITY,
                FactKind.GOVERNANCE, FactKind.ACCESSIBILITY_COMMITMENT,
                FactKind.PUBLIC_INITIATIVE, FactKind.ORGANIZATIONAL_RELATIONSHIP,
            },
            FactClass.VERIFIED_PROCUREMENT_CONTEXT: {FactKind.CURRENT_PROCUREMENT_ROLE},
        }
        if self.fact_kind not in permitted_kinds[self.fact_class]:
            raise BuyerIntelligenceValidationError("fact kind exceeds its information class")
        if self.evidence_status not in {SupportStatus.SUPPORTED, SupportStatus.PARTIALLY_SUPPORTED}:
            raise BuyerIntelligenceValidationError("facts must be supported or partially supported")
        _safe_statement(self.statement, "fact.statement")
        object.__setattr__(self, "evidence_ids", _ids(self.evidence_ids, "fact.evidence_ids", required=True))


@dataclass(frozen=True, slots=True, order=True)
class ComputedFact:
    fact_id: str
    computation: str
    value: str
    input_fact_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _stable_id(self.fact_id, "computed_fact.fact_id")
        _required(self.computation, "computed_fact.computation")
        _required(self.value, "computed_fact.value")
        object.__setattr__(self, "input_fact_ids",
                           _ids(self.input_fact_ids, "computed_fact.input_fact_ids", required=True))


@dataclass(frozen=True, slots=True, order=True)
class BuyerInterpretation:
    interpretation_id: str
    kind: InterpretationKind
    statement: str
    confidence: Confidence
    support_status: SupportStatus
    supporting_evidence_ids: tuple[str, ...]
    contradicting_evidence_ids: tuple[str, ...]
    opportunity_entity_ids: tuple[str, ...]
    assumption_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _stable_id(self.interpretation_id, "interpretation_id")
        if not isinstance(self.kind, InterpretationKind):
            raise BuyerIntelligenceValidationError("interpretation kind is unsupported")
        _safe_statement(self.statement, "interpretation.statement")
        if not isinstance(self.confidence, Confidence) or not isinstance(self.support_status, SupportStatus):
            raise BuyerIntelligenceValidationError("interpretation confidence and support status are required")
        if self.support_status in {SupportStatus.INSUFFICIENT_EVIDENCE, SupportStatus.MISSING_EVIDENCE}:
            raise BuyerIntelligenceValidationError("unsupported interpretation must be represented as an unknown")
        if self.support_status == SupportStatus.SUPPORTED and self.confidence == Confidence.UNKNOWN:
            raise BuyerIntelligenceValidationError("supported interpretation cannot have unknown confidence")
        object.__setattr__(self, "supporting_evidence_ids",
                           _ids(self.supporting_evidence_ids, "interpretation.supporting_evidence_ids", required=True))
        object.__setattr__(self, "contradicting_evidence_ids",
                           _ids(self.contradicting_evidence_ids, "interpretation.contradicting_evidence_ids"))
        object.__setattr__(self, "opportunity_entity_ids",
                           _ids(self.opportunity_entity_ids, "interpretation.opportunity_entity_ids", required=True))
        object.__setattr__(self, "assumption_ids", _ids(self.assumption_ids, "interpretation.assumption_ids"))
        if self.support_status == SupportStatus.CONFLICTING and not self.contradicting_evidence_ids:
            raise BuyerIntelligenceValidationError("conflicting interpretation requires contradicting evidence")
        if self.assumption_ids and self.support_status == SupportStatus.SUPPORTED:
            raise BuyerIntelligenceValidationError("an assumption-dependent interpretation cannot be fully supported")


@dataclass(frozen=True, slots=True, order=True)
class BuyerHypothesis:
    hypothesis_id: str
    statement: str
    confidence: Confidence
    support_status: SupportStatus
    supporting_evidence_ids: tuple[str, ...]
    contradicting_evidence_ids: tuple[str, ...]
    opportunity_entity_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _stable_id(self.hypothesis_id, "hypothesis_id")
        _safe_statement(self.statement, "hypothesis.statement")
        if not isinstance(self.confidence, Confidence) or not isinstance(self.support_status, SupportStatus):
            raise BuyerIntelligenceValidationError("hypothesis confidence and support status are required")
        if self.support_status in {SupportStatus.INSUFFICIENT_EVIDENCE, SupportStatus.MISSING_EVIDENCE}:
            raise BuyerIntelligenceValidationError("unsupported hypothesis must be represented as an unknown")
        if self.support_status == SupportStatus.SUPPORTED and self.confidence == Confidence.UNKNOWN:
            raise BuyerIntelligenceValidationError("supported hypothesis cannot have unknown confidence")
        object.__setattr__(self, "supporting_evidence_ids",
                           _ids(self.supporting_evidence_ids, "hypothesis.supporting_evidence_ids", required=True))
        object.__setattr__(self, "contradicting_evidence_ids",
                           _ids(self.contradicting_evidence_ids, "hypothesis.contradicting_evidence_ids"))
        object.__setattr__(self, "opportunity_entity_ids",
                           _ids(self.opportunity_entity_ids, "hypothesis.opportunity_entity_ids", required=True))
        if self.support_status == SupportStatus.CONFLICTING and not self.contradicting_evidence_ids:
            raise BuyerIntelligenceValidationError("conflicting hypothesis requires contradicting evidence")


@dataclass(frozen=True, slots=True, order=True)
class BuyerAssumption:
    assumption_id: str
    statement: str
    evidence_gap: str
    interpretation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _stable_id(self.assumption_id, "assumption_id")
        _safe_statement(self.statement, "assumption.statement")
        _required(self.evidence_gap, "assumption.evidence_gap")
        object.__setattr__(self, "interpretation_ids",
                           _ids(self.interpretation_ids, "assumption.interpretation_ids", required=True))


@dataclass(frozen=True, slots=True, order=True)
class BuyerUnknown:
    unknown_id: str
    kind: UnknownKind
    statement: str
    unresolved_reason: str
    related_evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _stable_id(self.unknown_id, "unknown_id")
        if not isinstance(self.kind, UnknownKind):
            raise BuyerIntelligenceValidationError("unknown kind is unsupported")
        _safe_statement(self.statement, "unknown.statement")
        _required(self.unresolved_reason, "unknown.unresolved_reason")
        object.__setattr__(self, "related_evidence_ids",
                           _ids(self.related_evidence_ids, "unknown.related_evidence_ids"))


@dataclass(frozen=True, slots=True, order=True)
class BuyerConflict:
    conflict_id: str
    subject: str
    opposing_evidence: tuple[tuple[str, ...], ...]

    def __post_init__(self) -> None:
        _stable_id(self.conflict_id, "conflict_id")
        _required(self.subject, "conflict.subject")
        groups = tuple(_ids(group, "conflict.opposing_evidence", required=True)
                       for group in self.opposing_evidence)
        if len(groups) < 2 or len(set(groups)) != len(groups):
            raise BuyerIntelligenceValidationError("conflict requires at least two distinct evidence positions")
        object.__setattr__(self, "opposing_evidence", tuple(sorted(groups)))


@dataclass(frozen=True, slots=True, order=True)
class BuyerManagementQuestion:
    question_id: str
    question: str
    evidence_ids: tuple[str, ...] = ()
    unknown_ids: tuple[str, ...] = ()
    conflict_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _stable_id(self.question_id, "question_id")
        _safe_statement(self.question, "question")
        if not self.question.endswith("?"):
            raise BuyerIntelligenceValidationError("management question must be unanswered and end with '?'")
        for name in ("evidence_ids", "unknown_ids", "conflict_ids"):
            object.__setattr__(self, name, _ids(getattr(self, name), f"question.{name}"))
        if not (self.evidence_ids or self.unknown_ids or self.conflict_ids):
            raise BuyerIntelligenceValidationError("management question must reference evidence or uncertainty")


@dataclass(frozen=True, slots=True, order=True)
class BuyerLimitation:
    limitation_id: str
    statement: str

    def __post_init__(self) -> None:
        _stable_id(self.limitation_id, "limitation_id")
        _required(self.statement, "limitation.statement")


@dataclass(frozen=True, slots=True)
class BuyerIntelligenceAnalysis:
    analysis_id: str
    buyer_id: str
    opportunity_id: str
    evaluation_context_id: str
    input_digest: str
    evidence_used: tuple[str, ...]
    buyer_facts: tuple[BuyerFact, ...]
    public_organizational_information: tuple[BuyerFact, ...]
    verified_procurement_context: tuple[BuyerFact, ...]
    computed_facts: tuple[ComputedFact, ...]
    interpretations: tuple[BuyerInterpretation, ...]
    competing_hypotheses: tuple[BuyerHypothesis, ...]
    assumptions: tuple[BuyerAssumption, ...]
    unknowns: tuple[BuyerUnknown, ...]
    conflicts: tuple[BuyerConflict, ...]
    management_questions: tuple[BuyerManagementQuestion, ...]
    limitations: tuple[BuyerLimitation, ...]
    analyst_version: str = BUYER_INTELLIGENCE_VERSION

    def __post_init__(self) -> None:
        for name in ("analysis_id", "buyer_id", "opportunity_id", "evaluation_context_id"):
            _stable_id(getattr(self, name), name)
        digest = _required(self.input_digest, "input_digest").lower()
        if not _DIGEST.fullmatch(digest):
            raise BuyerIntelligenceValidationError("input_digest must be a SHA-256 digest")
        object.__setattr__(self, "input_digest", digest)
        if self.analyst_version != BUYER_INTELLIGENCE_VERSION:
            raise BuyerIntelligenceValidationError("unsupported Buyer Intelligence version")
        object.__setattr__(self, "evidence_used", _ids(self.evidence_used, "evidence_used", required=True))
        sections = (
            ("buyer_facts", BuyerFact, lambda item: item.fact_id),
            ("public_organizational_information", BuyerFact, lambda item: item.fact_id),
            ("verified_procurement_context", BuyerFact, lambda item: item.fact_id),
            ("computed_facts", ComputedFact, lambda item: item.fact_id),
            ("interpretations", BuyerInterpretation, lambda item: item.interpretation_id),
            ("competing_hypotheses", BuyerHypothesis, lambda item: item.hypothesis_id),
            ("assumptions", BuyerAssumption, lambda item: item.assumption_id),
            ("unknowns", BuyerUnknown, lambda item: item.unknown_id),
            ("conflicts", BuyerConflict, lambda item: item.conflict_id),
            ("management_questions", BuyerManagementQuestion, lambda item: item.question_id),
            ("limitations", BuyerLimitation, lambda item: item.limitation_id),
        )
        for name, expected, key in sections:
            object.__setattr__(self, name, _objects(getattr(self, name), name, expected, key))
        expected_classes = {
            "buyer_facts": FactClass.AUTHORITATIVE_BUYER_FACT,
            "public_organizational_information": FactClass.PUBLIC_ORGANIZATIONAL_INFORMATION,
            "verified_procurement_context": FactClass.VERIFIED_PROCUREMENT_CONTEXT,
        }
        for name, expected in expected_classes.items():
            if any(item.fact_class != expected for item in getattr(self, name)):
                raise BuyerIntelligenceValidationError(f"{name} contains the wrong fact class")
        all_ids = [key(item) for name, _, key in sections for item in getattr(self, name)]
        if len(all_ids) != len(set(all_ids)):
            raise BuyerIntelligenceValidationError("analysis identities must be unique across sections")

    def to_dict(self) -> dict[str, Any]:
        return _primitives(asdict(self))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate_buyer_intelligence(inputs: GovernedBuyerInputs,
                                analysis: BuyerIntelligenceAnalysis) -> BuyerIntelligenceAnalysis:
    """Validate an analysis against immutable governed inputs without modifying either."""
    if not isinstance(inputs, GovernedBuyerInputs) or not isinstance(analysis, BuyerIntelligenceAnalysis):
        raise BuyerIntelligenceValidationError("governed inputs and Buyer Intelligence analysis are required")
    if (analysis.buyer_id, analysis.opportunity_id, analysis.evaluation_context_id) != (
        inputs.buyer.buyer_id, inputs.opportunity_id, inputs.evaluation_context_id
    ):
        raise BuyerIntelligenceValidationError("analysis identity is inconsistent with governed inputs")
    if analysis.input_digest != governed_input_digest(inputs):
        raise BuyerIntelligenceValidationError("analysis input digest does not match governed inputs")
    known_evidence = inputs.evidence_ids
    if not set(inputs.buyer.evidence_ids).issubset(known_evidence):
        raise BuyerIntelligenceValidationError("Canonical Buyer contains evidence outside Buyer Evidence")
    declared = set(analysis.evidence_used)
    if not declared.issubset(known_evidence):
        raise BuyerIntelligenceValidationError("evidence_used contains an unresolved evidence reference")

    source_by_id = {item.source_id: item for item in inputs.evidence.sources}
    document_by_id = {item.document_id: item for item in inputs.evidence.documents}
    citation_by_id = {item.citation_id: item for item in inputs.evidence.citations}
    extract_by_id = {item.extract_id: item for item in inputs.evidence.extracts}
    def document_for(evidence_id: str):
        if evidence_id in document_by_id:
            return document_by_id[evidence_id]
        if evidence_id in citation_by_id:
            return document_by_id[citation_by_id[evidence_id].document_id]
        if evidence_id in extract_by_id:
            return document_by_id[extract_by_id[evidence_id].document_id]
        return None
    for evidence_id in declared:
        document = document_for(evidence_id)
        source = source_by_id.get(evidence_id) if document is None else source_by_id[document.source_id]
        if source is not None and source.authority == EvidenceAuthority.ATTRIBUTABLE_PUBLIC_SOURCE:
            raise BuyerIntelligenceValidationError("Buyer Intelligence v1 does not permit secondary public sources")

    facts = analysis.buyer_facts + analysis.public_organizational_information + analysis.verified_procurement_context
    referenced = {eid for fact in facts for eid in fact.evidence_ids}
    referenced |= {eid for item in analysis.interpretations
                   for eid in item.supporting_evidence_ids + item.contradicting_evidence_ids}
    referenced |= {eid for item in analysis.competing_hypotheses
                   for eid in item.supporting_evidence_ids + item.contradicting_evidence_ids}
    referenced |= {eid for item in analysis.unknowns for eid in item.related_evidence_ids}
    referenced |= {eid for item in analysis.conflicts for group in item.opposing_evidence for eid in group}
    referenced |= {eid for item in analysis.management_questions for eid in item.evidence_ids}
    if not referenced.issubset(declared):
        raise BuyerIntelligenceValidationError("analysis conclusion uses evidence absent from evidence_used")
    citable = {*(item.citation_id for item in inputs.evidence.citations),
               *(item.extract_id for item in inputs.evidence.extracts),
               *inputs.procurement_evidence_ids}
    if not referenced.issubset(citable):
        raise BuyerIntelligenceValidationError("analysis conclusions require exact citable evidence")
    for fact in facts:
        documents = [document_for(eid) for eid in fact.evidence_ids
                     if eid not in inputs.procurement_evidence_ids]
        if any(document is None for document in documents):
            raise BuyerIntelligenceValidationError("fact evidence cannot establish its information class")
        if any(document.authenticity != AuthenticityStatus.VERIFIED for document in documents):
            raise BuyerIntelligenceValidationError("facts require verified document authenticity")
        if fact.fact_class == FactClass.PUBLIC_ORGANIZATIONAL_INFORMATION:
            if any(eid in inputs.procurement_evidence_ids for eid in fact.evidence_ids):
                raise BuyerIntelligenceValidationError("public organizational facts require organizational evidence")
        elif fact.fact_class == FactClass.AUTHORITATIVE_BUYER_FACT and fact.fact_kind != FactKind.IDENTITY:
            if any(eid in inputs.procurement_evidence_ids for eid in fact.evidence_ids):
                raise BuyerIntelligenceValidationError("buyer facts exceed procurement-source authority")
        elif fact.fact_class == FactClass.VERIFIED_PROCUREMENT_CONTEXT:
            if any(document is not None and document.category != SourceCategory.PROCUREMENT_NOTICE
                   for document in documents):
                raise BuyerIntelligenceValidationError("procurement context requires procurement evidence")
        stale = any((document_for(eid) is not None and
                     document_for(eid).freshness.status == FreshnessStatus.STALE)
                    for eid in fact.evidence_ids)
        if stale and fact.evidence_status == SupportStatus.SUPPORTED:
            raise BuyerIntelligenceValidationError("stale information cannot be presented as fully supported")

    fact_ids = {item.fact_id for item in facts}
    if any(not set(item.input_fact_ids).issubset(fact_ids) for item in analysis.computed_facts):
        raise BuyerIntelligenceValidationError("computed fact references an unknown fact")
    opportunity_ids = set(inputs.opportunity_entity_ids)
    reasoned = analysis.interpretations + analysis.competing_hypotheses
    if any(not set(item.opportunity_entity_ids).issubset(opportunity_ids) for item in reasoned):
        raise BuyerIntelligenceValidationError("reasoning references an unknown Canonical Opportunity entity")
    interpretation_ids = {item.interpretation_id for item in analysis.interpretations}
    assumptions = {item.assumption_id: item for item in analysis.assumptions}
    by_interpretation = {item.interpretation_id: item for item in analysis.interpretations}
    for item in analysis.interpretations:
        if any(aid not in assumptions for aid in item.assumption_ids):
            raise BuyerIntelligenceValidationError("interpretation references an unknown assumption")
    for item in analysis.assumptions:
        if not set(item.interpretation_ids).issubset(interpretation_ids):
            raise BuyerIntelligenceValidationError("assumption references an unknown interpretation")
        if any(item.assumption_id not in by_interpretation[iid].assumption_ids
               for iid in item.interpretation_ids):
            raise BuyerIntelligenceValidationError("assumption and interpretation links must be reciprocal")

    unknown_ids = {item.unknown_id for item in analysis.unknowns}
    conflict_ids = {item.conflict_id for item in analysis.conflicts}
    for question in analysis.management_questions:
        if not set(question.unknown_ids).issubset(unknown_ids) or not set(question.conflict_ids).issubset(conflict_ids):
            raise BuyerIntelligenceValidationError("management question references unknown uncertainty")
    conflict_evidence = [set(eid for group in item.opposing_evidence for eid in group)
                         for item in analysis.conflicts]
    for item in reasoned:
        if item.support_status == SupportStatus.CONFLICTING:
            required = set(item.supporting_evidence_ids + item.contradicting_evidence_ids)
            if not any(required.issubset(covered) for covered in conflict_evidence):
                raise BuyerIntelligenceValidationError("conflicting reasoning requires a matching explicit conflict")
    return analysis


_AUTHORITY_TO_FACT_CLASS = {
    EvidenceAuthority.OFFICIAL_BUYER: FactClass.AUTHORITATIVE_BUYER_FACT,
    EvidenceAuthority.LEGISLATIVE_AUTHORITY: FactClass.AUTHORITATIVE_BUYER_FACT,
    EvidenceAuthority.GOVERNMENT_AUTHORITY: FactClass.PUBLIC_ORGANIZATIONAL_INFORMATION,
    EvidenceAuthority.OFFICIAL_PROCUREMENT_AUTHORITY: FactClass.PUBLIC_ORGANIZATIONAL_INFORMATION,
    EvidenceAuthority.OTHER_OFFICIAL_PUBLISHER: FactClass.PUBLIC_ORGANIZATIONAL_INFORMATION,
    # ATTRIBUTABLE_PUBLIC_SOURCE is absent deliberately: validate_buyer_intelligence
    # already refuses it (Buyer Intelligence v1 does not permit secondary public
    # sources), so no fact class mapping for it should ever be reachable.
}


def _evidence_lookup(evidence: BuyerEvidenceSet):
    """Return a document_for(evidence_id) resolver and a source_by_id map,
    mirroring validate_buyer_intelligence's own resolution exactly so the
    analyst never builds a fact that resolution would treat differently.
    """
    document_by_id = {item.document_id: item for item in evidence.documents}
    citation_by_id = {item.citation_id: item for item in evidence.citations}
    extract_by_id = {item.extract_id: item for item in evidence.extracts}
    source_by_id = {item.source_id: item for item in evidence.sources}

    def document_for(evidence_id: str):
        if evidence_id in document_by_id:
            return document_by_id[evidence_id]
        if evidence_id in citation_by_id:
            return document_by_id[citation_by_id[evidence_id].document_id]
        if evidence_id in extract_by_id:
            return document_by_id[extract_by_id[evidence_id].document_id]
        return None

    return document_for, source_by_id


def _admissible_evidence(evidence_ids, document_for, source_by_id):
    """Return (kept_ids, evidence_status) for the subset of evidence_ids
    backed by a VERIFIED document from a permitted (non-secondary) source
    authority -- or ((), None) if none qualify. A fact must never cite
    evidence this would exclude: doing so would either fabricate support
    validate_buyer_intelligence cannot find, or smuggle in a forbidden
    secondary source. Any qualifying evidence resting on a STALE document
    downgrades the whole fact to PARTIALLY_SUPPORTED, never SUPPORTED.
    """
    kept = []
    any_stale = False
    for evidence_id in evidence_ids:
        document = document_for(evidence_id)
        if document is None or document.authenticity != AuthenticityStatus.VERIFIED:
            continue
        source = source_by_id.get(document.source_id)
        if source is None or source.authority == EvidenceAuthority.ATTRIBUTABLE_PUBLIC_SOURCE:
            continue
        kept.append(evidence_id)
        if document.freshness.status == FreshnessStatus.STALE:
            any_stale = True
    if not kept:
        return (), None
    status = SupportStatus.PARTIALLY_SUPPORTED if any_stale else SupportStatus.SUPPORTED
    return tuple(sorted(kept)), status


def analyze_buyer(inputs: GovernedBuyerInputs) -> BuyerIntelligenceAnalysis:
    """Produce one validated Buyer Intelligence analysis from governed inputs.

    This is a deterministic, non-interpretive analyst. It transcribes
    verbatim, VERIFIED Buyer Evidence extracts into typed facts, declares
    which fact kinds have no supporting evidence, and stops there -- it
    never infers a fact, summarizes a verbatim statement, interprets
    relevance to the opportunity, proposes a competing hypothesis, or
    assumes a fact evidence does not establish. Evidence-sourced facts are
    classified by source authority, not by reading and judging what a
    statement is about (see the "coarse-classification" limitation below)
    -- doing otherwise would require exactly the interpretive judgment this
    analyst is built to avoid.

    It never restates CanonicalBuyer's own identity fields (legal name,
    organization type, government level, jurisdiction) as BuyerFacts.
    Canonical Buyer is their sole governed owner
    (BUYER_INTELLIGENCE_FACT_OWNERSHIP_ARCHITECTURE.md): Opportunity
    Intelligence never re-asserts Canonical Opportunity's resolved fields as
    its own, and Buyer Intelligence holds the identical relationship to
    Canonical Buyer. Anything needing to cite the buyer's identity
    references Canonical Buyer Publication directly instead of duplicating
    it (see buyer_intelligence_publication.py).
    """
    if not isinstance(inputs, GovernedBuyerInputs):
        raise BuyerIntelligenceValidationError("GovernedBuyerInputs is required")
    digest = governed_input_digest(inputs)
    buyer, evidence = inputs.buyer, inputs.evidence
    document_for, source_by_id = _evidence_lookup(evidence)

    buyer_facts: list[BuyerFact] = []
    public_information: list[BuyerFact] = []

    for extract in evidence.extracts:
        kept_ids, status = _admissible_evidence((extract.extract_id,), document_for, source_by_id)
        if not kept_ids:
            continue  # not VERIFIED, or a forbidden secondary source -- never guess
        source = source_by_id[document_for(extract.extract_id).source_id]
        fact_class = _AUTHORITY_TO_FACT_CLASS[source.authority]
        fact = BuyerFact(
            fact_id=f"fact:{extract.extract_id.split(':', 1)[-1]}", fact_class=fact_class,
            fact_kind=FactKind.ORGANIZATIONAL_FUNCTION, statement=extract.exact_text,
            evidence_status=status, evidence_ids=kept_ids,
        )
        (buyer_facts if fact_class == FactClass.AUTHORITATIVE_BUYER_FACT else public_information).append(fact)

    buyer_facts = tuple(buyer_facts)
    public_information = tuple(public_information)
    # No specific Canonical Opportunity observation content is available to
    # GovernedBuyerInputs (only opaque entity IDs) -- citing one without a
    # real, inspectable basis for the claim would not be evidence-owned.
    verified_procurement_context: tuple[BuyerFact, ...] = ()

    all_facts = buyer_facts + public_information + verified_procurement_context
    computed_facts: tuple[ComputedFact, ...] = ()
    if all_facts:
        computed_facts = (ComputedFact(
            fact_id="computed:total-established-facts",
            computation="count(buyer_facts + public_organizational_information + verified_procurement_context)",
            value=str(len(all_facts)),
            input_fact_ids=tuple(sorted(item.fact_id for item in all_facts)),
        ),)

    established_kinds = {item.fact_kind for item in all_facts}
    # IDENTITY is deliberately excluded from this scan: it is never
    # established by this analyst by design (Canonical Buyer's exclusive
    # ownership -- see the module-level note on analyze_buyer above), so its
    # permanent absence from `all_facts` is not a genuine evidence gap and
    # must not be reported as one ("Unknowns must represent absence of
    # evidence, never negative inference").
    scoped_kinds = tuple(kind for kind in FactKind if kind != FactKind.IDENTITY)
    unknowns = tuple(sorted((
        BuyerUnknown(
            unknown_id=f"unknown:missing-{kind.value.lower().replace('_', '-')}",
            kind=UnknownKind.MISSING_BUYER_EVIDENCE,
            statement=f"No established fact of kind {kind.value} exists for this buyer.",
            unresolved_reason="No acquired, verified Buyer Evidence supports this fact kind.",
        )
        for kind in scoped_kinds if kind not in established_kinds
    ), key=lambda item: item.unknown_id))

    management_questions: tuple[BuyerManagementQuestion, ...] = ()
    if unknowns:
        management_questions = (BuyerManagementQuestion(
            question_id="question:buyer-evidence-gaps",
            question=("Which identified Buyer Intelligence evidence gaps require additional "
                      "research before proposal kickoff?"),
            unknown_ids=tuple(sorted(item.unknown_id for item in unknowns)),
        ),)

    limitations = (
        BuyerLimitation("limitation:scope",
            "Analysis uses only the supplied Canonical Buyer and Buyer Evidence; no Canonical "
            "Opportunity content is cited by any established fact in this version."),
        BuyerLimitation("limitation:no-sales-intelligence",
            "No private CRM data, relationship notes, personal data enrichment, competitor "
            "data, or unverified sales intelligence is available."),
        BuyerLimitation("limitation:no-prediction",
            "This analysis does not predict award outcome, recommend Bid/No-Bid, or infer "
            "buyer preference."),
        BuyerLimitation("limitation:coarse-classification",
            "Evidence-sourced facts are classified by source authority, not by individual "
            "statement content; a verbatim statement may describe a more specific fact kind "
            "than the one recorded."),
    )

    evidence_used = tuple(sorted({eid for fact in all_facts for eid in fact.evidence_ids}))
    analysis_id = _id("bi-analysis-", {
        "input_digest": digest, "evaluation_context_id": inputs.evaluation_context_id,
        "version": BUYER_INTELLIGENCE_VERSION,
    })

    analysis = BuyerIntelligenceAnalysis(
        analysis_id=analysis_id, buyer_id=buyer.buyer_id, opportunity_id=inputs.opportunity_id,
        evaluation_context_id=inputs.evaluation_context_id, input_digest=digest,
        evidence_used=evidence_used, buyer_facts=buyer_facts,
        public_organizational_information=public_information,
        verified_procurement_context=verified_procurement_context,
        computed_facts=computed_facts, interpretations=(), competing_hypotheses=(),
        assumptions=(), unknowns=unknowns, conflicts=(),
        management_questions=management_questions, limitations=limitations,
    )
    if governed_input_digest(inputs) != digest:
        raise BuyerIntelligenceValidationError("authoritative input mutation")
    return validate_buyer_intelligence(inputs, analysis)


def governed_input_digest(inputs: GovernedBuyerInputs) -> str:
    payload = {
        "buyer": inputs.buyer.to_dict(),
        "evidence": inputs.evidence.to_dict(),
        "opportunity_id": inputs.opportunity_id,
        "canonical_opportunity_version": inputs.canonical_opportunity_version,
        "canonical_opportunity_digest": inputs.canonical_opportunity_digest,
        "opportunity_entity_ids": inputs.opportunity_entity_ids,
        "procurement_evidence_ids": inputs.procurement_evidence_ids,
        "procurement_package_digest": inputs.procurement_package_digest,
        "evaluation_context_id": inputs.evaluation_context_id,
        "source_date": inputs.source_date.isoformat(),
        "opportunity_analysis_id": inputs.opportunity_analysis_id,
        "opportunity_analysis_version": inputs.opportunity_analysis_version,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _primitives(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _primitives(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_primitives(item) for item in value]
    return value
