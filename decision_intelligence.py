"""Typed contracts for evidence-driven decision intelligence.

This module contains no procurement logic, persistence, prompts, or model calls.
It defines the boundary future analysts must satisfy: AI can organize reasoning
and recommendations, while accountable human decisions remain separate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol, Sequence, runtime_checkable


class ContractValidationError(ValueError):
    """Raised when a decision-intelligence contract violates an invariant."""


class StatementType(str, Enum):
    SOURCE_FACT = "SOURCE_FACT"
    COMPUTED_FACT = "COMPUTED_FACT"
    AI_INFERENCE = "AI_INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"
    RECOMMENDATION = "RECOMMENDATION"
    HUMAN_DECISION = "HUMAN_DECISION"
    UNKNOWN = "UNKNOWN"


class Confidence(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class ReasoningStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PROPOSED = "PROPOSED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    UNRESOLVED = "UNRESOLVED"


class SourceType(str, Enum):
    AUTHORITATIVE_SOURCE = "AUTHORITATIVE_SOURCE"
    DETERMINISTIC_COMPUTATION = "DETERMINISTIC_COMPUTATION"
    SPECIALIST_ANALYST = "SPECIALIST_ANALYST"
    HUMAN = "HUMAN"
    SYSTEM = "SYSTEM"


class SupportedEntityType(str, Enum):
    CANONICAL_FACT = "CANONICAL_FACT"
    REQUIREMENT = "REQUIREMENT"
    COMMERCIAL_CLAUSE = "COMMERCIAL_CLAUSE"
    DELIVERABLE = "DELIVERABLE"
    OBSERVATION = "OBSERVATION"
    FUTURE_ENTITY = "FUTURE_ENTITY"


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return value


def _unique(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    result = tuple(values)
    if any(not isinstance(value, str) or not value.strip() for value in result):
        raise ContractValidationError(f"{field_name} must contain non-empty strings")
    if len(set(result)) != len(result):
        raise ContractValidationError(f"{field_name} must not contain duplicates")
    return result


@dataclass(frozen=True, slots=True)
class StatementSource:
    source_type: SourceType
    source_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_type, SourceType):
            raise ContractValidationError("source_type must be a SourceType")
        _required(self.source_id, "source_id")


@dataclass(frozen=True, slots=True)
class EvidenceSupport:
    """A reference to an existing entity and its existing evidence IDs."""

    entity_type: SupportedEntityType
    entity_id: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.entity_type, SupportedEntityType):
            raise ContractValidationError("entity_type must be a SupportedEntityType")
        _required(self.entity_id, "entity_id")
        object.__setattr__(self, "evidence_ids", _unique(self.evidence_ids, "evidence_ids"))


@dataclass(frozen=True, slots=True)
class AlternativeHypothesis:
    hypothesis_id: str
    statement: str
    evidence_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _required(self.hypothesis_id, "hypothesis_id")
        _required(self.statement, "statement")
        object.__setattr__(self, "evidence_ids", _unique(self.evidence_ids, "evidence_ids"))
        object.__setattr__(self, "limitations", _unique(self.limitations, "limitations"))


@dataclass(frozen=True, slots=True)
class ReasoningGaps:
    missing_evidence: tuple[str, ...] = ()
    missing_documents: tuple[str, ...] = ()
    missing_history: tuple[str, ...] = ()
    known_uncertainty: tuple[str, ...] = ()
    validation_limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("missing_evidence", "missing_documents", "missing_history",
                     "known_uncertainty", "validation_limitations"):
            object.__setattr__(self, name, _unique(getattr(self, name), name))


_REASONING_TYPES = frozenset({
    StatementType.AI_INFERENCE,
    StatementType.HYPOTHESIS,
    StatementType.RECOMMENDATION,
})


@dataclass(frozen=True, slots=True)
class DecisionStatement:
    statement_id: str
    statement_type: StatementType
    statement: str
    source: StatementSource
    confidence: Confidence | None
    reasoning_status: ReasoningStatus
    evidence_ids: tuple[str, ...] = ()
    supporting_fact_ids: tuple[str, ...] = ()
    evidence_support: tuple[EvidenceSupport, ...] = ()
    assumptions: tuple[str, ...] = ()
    alternative_hypotheses: tuple[AlternativeHypothesis, ...] = ()
    limitations: tuple[str, ...] = ()
    recommendation_scope: str | None = None
    reasoning_gaps: ReasoningGaps = field(default_factory=ReasoningGaps)

    def __post_init__(self) -> None:
        if not isinstance(self.statement_type, StatementType):
            raise ContractValidationError("statement_type must be a StatementType")
        if self.confidence is not None and not isinstance(self.confidence, Confidence):
            raise ContractValidationError("confidence must be a Confidence or None")
        if not isinstance(self.reasoning_status, ReasoningStatus):
            raise ContractValidationError("reasoning_status must be a ReasoningStatus")
        if not isinstance(self.source, StatementSource):
            raise ContractValidationError("source must be a StatementSource")
        if any(not isinstance(link, EvidenceSupport) for link in self.evidence_support):
            raise ContractValidationError("evidence_support must contain EvidenceSupport values")
        if any(not isinstance(item, AlternativeHypothesis) for item in self.alternative_hypotheses):
            raise ContractValidationError("alternative_hypotheses must contain AlternativeHypothesis values")
        if not isinstance(self.reasoning_gaps, ReasoningGaps):
            raise ContractValidationError("reasoning_gaps must be ReasoningGaps")
        _required(self.statement_id, "statement_id")
        _required(self.statement, "statement")
        for name in ("evidence_ids", "supporting_fact_ids", "assumptions", "limitations"):
            object.__setattr__(self, name, _unique(getattr(self, name), name))

        if self.statement_type in _REASONING_TYPES:
            if self.confidence is None or self.reasoning_status == ReasoningStatus.NOT_APPLICABLE:
                raise ContractValidationError("reasoning statements require confidence and reasoning status")
        elif self.statement_type == StatementType.UNKNOWN:
            if self.confidence not in (None, Confidence.UNKNOWN):
                raise ContractValidationError("UNKNOWN statements cannot claim confidence")
            if self.reasoning_status not in (ReasoningStatus.UNRESOLVED, ReasoningStatus.NOT_APPLICABLE):
                raise ContractValidationError("UNKNOWN statements must remain unresolved")
        elif self.confidence is not None:
            raise ContractValidationError("confidence applies only to reasoning statements")

        expected_source = {
            StatementType.SOURCE_FACT: SourceType.AUTHORITATIVE_SOURCE,
            StatementType.COMPUTED_FACT: SourceType.DETERMINISTIC_COMPUTATION,
            StatementType.AI_INFERENCE: SourceType.SPECIALIST_ANALYST,
            StatementType.HYPOTHESIS: SourceType.SPECIALIST_ANALYST,
            StatementType.RECOMMENDATION: SourceType.SPECIALIST_ANALYST,
            StatementType.HUMAN_DECISION: SourceType.HUMAN,
        }.get(self.statement_type)
        if expected_source is not None and self.source.source_type != expected_source:
            raise ContractValidationError("statement type and source type do not match")

        if self.statement_type == StatementType.RECOMMENDATION:
            _required(self.recommendation_scope or "", "recommendation_scope")
        elif self.recommendation_scope is not None:
            raise ContractValidationError("recommendation_scope is valid only for recommendations")

        linked_evidence = {eid for link in self.evidence_support for eid in link.evidence_ids}
        if not linked_evidence.issubset(set(self.evidence_ids)):
            raise ContractValidationError("evidence support references undeclared evidence IDs")


@dataclass(frozen=True, slots=True)
class AnalystContext:
    context_id: str
    entity_ids: tuple[str, ...]
    statements: tuple[DecisionStatement, ...] = ()

    def __post_init__(self) -> None:
        _required(self.context_id, "context_id")
        object.__setattr__(self, "entity_ids", _unique(self.entity_ids, "entity_ids"))


@dataclass(frozen=True, slots=True)
class AnalystOutput:
    analyst_id: str
    statements: tuple[DecisionStatement, ...]

    def __post_init__(self) -> None:
        _required(self.analyst_id, "analyst_id")
        if any(not isinstance(item, DecisionStatement) for item in self.statements):
            raise ContractValidationError("statements must contain DecisionStatement values")
        ids = tuple(item.statement_id for item in self.statements)
        if len(ids) != len(set(ids)):
            raise ContractValidationError("analyst output contains duplicate statement IDs")


@runtime_checkable
class SpecialistAnalyst(Protocol):
    """Contract for future evidence-producing specialist analysts."""

    @property
    def analyst_id(self) -> str: ...

    def analyze(self, context: AnalystContext) -> AnalystOutput: ...


@dataclass(frozen=True, slots=True)
class ModeratorInput:
    context_id: str
    analyst_outputs: tuple[AnalystOutput, ...]

    def __post_init__(self) -> None:
        _required(self.context_id, "context_id")
        if any(not isinstance(output, AnalystOutput) for output in self.analyst_outputs):
            raise ContractValidationError("analyst_outputs must contain AnalystOutput values")
        analysts = tuple(output.analyst_id for output in self.analyst_outputs)
        if len(analysts) != len(set(analysts)):
            raise ContractValidationError("moderator input contains duplicate analysts")


@dataclass(frozen=True, slots=True)
class ModeratorOutput:
    agreement_statement_ids: tuple[tuple[str, ...], ...] = ()
    disagreement_statement_ids: tuple[tuple[str, ...], ...] = ()
    unresolved_questions: tuple[str, ...] = ()
    decision_considerations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for groups_name in ("agreement_statement_ids", "disagreement_statement_ids"):
            for group in getattr(self, groups_name):
                if len(_unique(group, groups_name)) < 2:
                    raise ContractValidationError(f"{groups_name} groups require at least two statements")
        object.__setattr__(self, "unresolved_questions", _unique(self.unresolved_questions, "unresolved_questions"))
        object.__setattr__(self, "decision_considerations", _unique(self.decision_considerations, "decision_considerations"))


@dataclass(frozen=True, slots=True)
class HumanDecisionRecord:
    decision_id: str
    decision: str
    rationale: str
    decision_maker: str
    timestamp: datetime
    accepted_recommendation_ids: tuple[str, ...] = ()
    rejected_recommendation_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("decision_id", "decision", "rationale", "decision_maker"):
            _required(getattr(self, name), name)
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ContractValidationError("timestamp must be timezone-aware")
        accepted = _unique(self.accepted_recommendation_ids, "accepted_recommendation_ids")
        rejected = _unique(self.rejected_recommendation_ids, "rejected_recommendation_ids")
        object.__setattr__(self, "accepted_recommendation_ids", accepted)
        object.__setattr__(self, "rejected_recommendation_ids", rejected)
        if set(accepted) & set(rejected):
            raise ContractValidationError("a recommendation cannot be both accepted and rejected")


@runtime_checkable
class AnalystModerator(Protocol):
    """Contract for a future moderator; no moderation logic is implemented."""

    def moderate(self, inputs: ModeratorInput) -> ModeratorOutput: ...
