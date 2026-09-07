"""Domain-neutral contracts for future Decision Intelligence analysts.

Analysts advise. They do not decide, mutate facts, call models, or persist data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import re
from typing import Protocol, runtime_checkable

from decision_intelligence import (
    AnalystContext,
    Confidence,
    ContractValidationError,
    DecisionStatement,
    EvidenceSupport,
    StatementType,
    SupportedEntityType,
)


class SupportStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    UNKNOWN = "UNKNOWN"


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{name} must be a non-empty string")
    return value


def _unique(values, name: str):
    result = tuple(values)
    if any(not isinstance(value, str) or not value.strip() for value in result):
        raise ContractValidationError(f"{name} must contain non-empty strings")
    if len(result) != len(set(result)):
        raise ContractValidationError(f"{name} must not contain duplicates")
    return result


_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def _version_tuple(version: str) -> tuple[int, int, int]:
    match = _VERSION.fullmatch(version) if isinstance(version, str) else None
    if not match:
        raise ContractValidationError("analyst_version must use MAJOR.MINOR.PATCH")
    return tuple(int(part) for part in match.groups())


@dataclass(frozen=True, slots=True)
class DecisionAnalystMetadata:
    analyst_id: str
    analyst_name: str
    analyst_version: str
    analyst_domain: str
    supported_statement_types: frozenset[StatementType]
    supported_evidence_types: frozenset[SupportedEntityType]

    def __post_init__(self) -> None:
        for name in ("analyst_id", "analyst_name", "analyst_domain"):
            _required(getattr(self, name), name)
        _version_tuple(self.analyst_version)
        if not isinstance(self.supported_statement_types, frozenset):
            raise ContractValidationError("supported_statement_types must be a frozenset")
        if not isinstance(self.supported_evidence_types, frozenset):
            raise ContractValidationError("supported_evidence_types must be a frozenset")
        if not self.supported_statement_types:
            raise ContractValidationError("supported_statement_types must not be empty")
        if not self.supported_evidence_types:
            raise ContractValidationError("supported_evidence_types must not be empty")
        if any(not isinstance(value, StatementType) for value in self.supported_statement_types):
            raise ContractValidationError("invalid supported statement type")
        if any(not isinstance(value, SupportedEntityType) for value in self.supported_evidence_types):
            raise ContractValidationError("invalid supported evidence type")
        forbidden = {StatementType.SOURCE_FACT, StatementType.HUMAN_DECISION}
        if self.supported_statement_types & forbidden:
            raise ContractValidationError("analysts cannot emit source facts or human decisions")


@dataclass(frozen=True, slots=True)
class AnalystReasoning:
    statement: DecisionStatement
    support_status: SupportStatus

    def __post_init__(self) -> None:
        if not isinstance(self.statement, DecisionStatement):
            raise ContractValidationError("statement must be a DecisionStatement")
        if self.statement.statement_type != StatementType.AI_INFERENCE:
            raise ContractValidationError("analyst reasoning must contain an AI_INFERENCE")
        if not isinstance(self.support_status, SupportStatus):
            raise ContractValidationError("support_status must be a SupportStatus")
        if not self.statement.evidence_support:
            raise ContractValidationError("analyst reasoning must link existing evidence")


@dataclass(frozen=True, slots=True)
class AnalystHypothesis:
    hypothesis_id: str
    description: str
    supporting_evidence: tuple[EvidenceSupport, ...]
    contradicting_evidence: tuple[EvidenceSupport, ...]
    confidence: Confidence
    support_status: SupportStatus
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _required(self.hypothesis_id, "hypothesis_id")
        _required(self.description, "description")
        if not isinstance(self.confidence, Confidence) or not isinstance(self.support_status, SupportStatus):
            raise ContractValidationError("hypothesis confidence and support status are required")
        if not self.supporting_evidence and not self.contradicting_evidence:
            raise ContractValidationError("hypothesis must link existing evidence")
        if any(not isinstance(value, EvidenceSupport)
               for value in self.supporting_evidence + self.contradicting_evidence):
            raise ContractValidationError("hypothesis evidence must use EvidenceSupport")
        object.__setattr__(self, "limitations", _unique(self.limitations, "limitations"))


@dataclass(frozen=True, slots=True)
class AnalystRecommendation:
    recommendation_id: str
    recommendation_type: str
    rationale: str
    supporting_analysis: tuple[str, ...]
    confidence: Confidence
    support_status: SupportStatus

    def __post_init__(self) -> None:
        for name in ("recommendation_id", "recommendation_type", "rationale"):
            _required(getattr(self, name), name)
        object.__setattr__(self, "supporting_analysis",
                           _unique(self.supporting_analysis, "supporting_analysis"))
        if not self.supporting_analysis:
            raise ContractValidationError("recommendations require supporting analysis")
        if not isinstance(self.confidence, Confidence) or not isinstance(self.support_status, SupportStatus):
            raise ContractValidationError("recommendation confidence and support status are required")


@dataclass(frozen=True, slots=True)
class AnalystAssumption:
    assumption_id: str
    description: str

    def __post_init__(self) -> None:
        _required(self.assumption_id, "assumption_id")
        _required(self.description, "description")


@dataclass(frozen=True, slots=True)
class ManagementQuestion:
    question_id: str
    question: str
    related_analysis_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _required(self.question_id, "question_id")
        _required(self.question, "question")
        object.__setattr__(self, "related_analysis_ids",
                           _unique(self.related_analysis_ids, "related_analysis_ids"))


@dataclass(frozen=True, slots=True)
class AnalystUnknowns:
    missing_evidence: tuple[str, ...] = ()
    unavailable_datasets: tuple[str, ...] = ()
    unavailable_history: tuple[str, ...] = ()
    unresolved_conflict_ids: tuple[str, ...] = ()
    ambiguous_observation_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("missing_evidence", "unavailable_datasets", "unavailable_history",
                     "unresolved_conflict_ids", "ambiguous_observation_ids"):
            object.__setattr__(self, name, _unique(getattr(self, name), name))


@dataclass(frozen=True, slots=True)
class DecisionAnalysis:
    analysis_id: str
    analyst_id: str
    execution_timestamp: datetime
    overall_confidence: Confidence
    evidence_used: tuple[EvidenceSupport, ...]
    computed_facts: tuple[DecisionStatement, ...] = ()
    inferences: tuple[AnalystReasoning, ...] = ()
    hypotheses: tuple[AnalystHypothesis, ...] = ()
    recommendations: tuple[AnalystRecommendation, ...] = ()
    limitations: tuple[str, ...] = ()
    assumptions: tuple[AnalystAssumption, ...] = ()
    unanswered_questions: tuple[ManagementQuestion, ...] = ()
    unknowns: AnalystUnknowns = AnalystUnknowns()

    def __post_init__(self) -> None:
        _required(self.analysis_id, "analysis_id")
        _required(self.analyst_id, "analyst_id")
        if self.execution_timestamp.tzinfo is None or self.execution_timestamp.utcoffset() is None:
            raise ContractValidationError("execution_timestamp must be timezone-aware")
        if not isinstance(self.overall_confidence, Confidence):
            raise ContractValidationError("overall_confidence must be a Confidence")
        if any(not isinstance(item, EvidenceSupport) for item in self.evidence_used):
            raise ContractValidationError("evidence_used must contain EvidenceSupport values")
        if any(not isinstance(item, DecisionStatement) for item in self.computed_facts):
            raise ContractValidationError("computed_facts must contain DecisionStatement values")
        if any(item.statement_type != StatementType.COMPUTED_FACT for item in self.computed_facts):
            raise ContractValidationError("computed_facts must contain COMPUTED_FACT statements")
        if any(not item.evidence_support for item in self.computed_facts):
            raise ContractValidationError("computed facts must link existing evidence")
        if any(not isinstance(item, AnalystReasoning) for item in self.inferences):
            raise ContractValidationError("inferences must contain AnalystReasoning values")
        if any(not isinstance(item, AnalystHypothesis) for item in self.hypotheses):
            raise ContractValidationError("hypotheses must contain AnalystHypothesis values")
        if any(not isinstance(item, AnalystRecommendation) for item in self.recommendations):
            raise ContractValidationError("recommendations must contain AnalystRecommendation values")
        if any(not isinstance(item, AnalystAssumption) for item in self.assumptions):
            raise ContractValidationError("assumptions must contain AnalystAssumption values")
        if any(not isinstance(item, ManagementQuestion) for item in self.unanswered_questions):
            raise ContractValidationError("unanswered_questions must contain ManagementQuestion values")
        if not isinstance(self.unknowns, AnalystUnknowns):
            raise ContractValidationError("unknowns must be AnalystUnknowns")
        object.__setattr__(self, "limitations", _unique(self.limitations, "limitations"))

        declared_evidence = set(self.evidence_used)
        used_links = [link for fact in self.computed_facts for link in fact.evidence_support]
        used_links += [link for inference in self.inferences for link in inference.statement.evidence_support]
        used_links += [link for hypothesis in self.hypotheses
                       for link in hypothesis.supporting_evidence + hypothesis.contradicting_evidence]
        if any(link not in declared_evidence for link in used_links):
            raise ContractValidationError("analysis conclusion uses evidence absent from evidence_used")

        analysis_ids = {item.statement.statement_id for item in self.inferences}
        analysis_ids.update(item.statement_id for item in self.computed_facts)
        analysis_ids.update(item.hypothesis_id for item in self.hypotheses)
        for recommendation in self.recommendations:
            if not set(recommendation.supporting_analysis).issubset(analysis_ids):
                raise ContractValidationError("recommendation references unknown supporting analysis")
        if any(not set(question.related_analysis_ids).issubset(analysis_ids)
               for question in self.unanswered_questions):
            raise ContractValidationError("question references unknown related analysis")

        all_ids = [item.statement_id for item in self.computed_facts]
        all_ids += [item.statement.statement_id for item in self.inferences]
        all_ids += [item.hypothesis_id for item in self.hypotheses]
        all_ids += [item.recommendation_id for item in self.recommendations]
        if len(all_ids) != len(set(all_ids)):
            raise ContractValidationError("analysis conclusion IDs must be unique")


@runtime_checkable
class DecisionAnalyst(Protocol):
    @property
    def metadata(self) -> DecisionAnalystMetadata: ...

    def analyze(self, context: AnalystContext) -> DecisionAnalysis: ...


class DecisionAnalystRegistry:
    """Deterministic in-process registry; it performs no loading or injection."""

    def __init__(self) -> None:
        self._analysts: dict[str, DecisionAnalyst] = {}

    def register(self, analyst: DecisionAnalyst) -> None:
        if not isinstance(analyst, DecisionAnalyst):
            raise ContractValidationError("analyst must satisfy DecisionAnalyst")
        metadata = analyst.metadata
        if not isinstance(metadata, DecisionAnalystMetadata):
            raise ContractValidationError("analyst metadata is invalid")
        if metadata.analyst_id in self._analysts:
            raise ContractValidationError(f"duplicate analyst: {metadata.analyst_id}")
        self._analysts[metadata.analyst_id] = analyst

    def discover(self) -> tuple[DecisionAnalystMetadata, ...]:
        return tuple(self._analysts[key].metadata for key in sorted(self._analysts))

    def get(self, analyst_id: str, compatible_with: str | None = None) -> DecisionAnalyst:
        try:
            analyst = self._analysts[analyst_id]
        except KeyError as exc:
            raise ContractValidationError(f"unknown analyst: {analyst_id}") from exc
        if compatible_with is not None and not self.is_compatible(
                analyst.metadata.analyst_version, compatible_with):
            raise ContractValidationError("analyst version is incompatible")
        return analyst

    def validate_output(self, analyst_id: str, output: DecisionAnalysis) -> DecisionAnalysis:
        analyst = self.get(analyst_id)
        if not isinstance(output, DecisionAnalysis) or output.analyst_id != analyst_id:
            raise ContractValidationError("analysis output does not match its registered analyst")
        emitted = set()
        if output.computed_facts:
            emitted.add(StatementType.COMPUTED_FACT)
        if output.inferences:
            emitted.add(StatementType.AI_INFERENCE)
        if output.hypotheses:
            emitted.add(StatementType.HYPOTHESIS)
        if output.recommendations:
            emitted.add(StatementType.RECOMMENDATION)
        if not emitted.issubset(analyst.metadata.supported_statement_types):
            raise ContractValidationError("analysis exceeds declared statement capabilities")
        evidence_types = {item.entity_type for item in output.evidence_used}
        if not evidence_types.issubset(analyst.metadata.supported_evidence_types):
            raise ContractValidationError("analysis exceeds declared evidence capabilities")
        return output

    @staticmethod
    def is_compatible(available: str, required: str) -> bool:
        available_parts = _version_tuple(available)
        required_parts = _version_tuple(required)
        return available_parts[0] == required_parts[0] and available_parts >= required_parts


@dataclass(frozen=True, slots=True)
class AnalysisReference:
    analysis_id: str
    conclusion_id: str

    def __post_init__(self) -> None:
        _required(self.analysis_id, "analysis_id")
        _required(self.conclusion_id, "conclusion_id")


def _reference_group(values: tuple[AnalysisReference, ...], name: str,
                     minimum: int = 1) -> None:
    if len(values) < minimum or any(not isinstance(value, AnalysisReference) for value in values):
        raise ContractValidationError(f"{name} has invalid references")
    pairs = {(value.analysis_id, value.conclusion_id) for value in values}
    if len(pairs) != len(values):
        raise ContractValidationError(f"{name} contains duplicate references")


@dataclass(frozen=True, slots=True)
class AgreementGroup:
    group_id: str
    statement: str
    members: tuple[AnalysisReference, ...]

    def __post_init__(self) -> None:
        _required(self.group_id, "group_id")
        _required(self.statement, "statement")
        _reference_group(self.members, "agreement group", 2)
        if len({member.analysis_id for member in self.members}) < 2:
            raise ContractValidationError("agreement requires multiple analyses")


@dataclass(frozen=True, slots=True)
class DisagreementGroup:
    group_id: str
    subject: str
    members: tuple[AnalysisReference, ...]

    def __post_init__(self) -> None:
        _required(self.group_id, "group_id")
        _required(self.subject, "subject")
        _reference_group(self.members, "disagreement group", 2)
        if len({member.analysis_id for member in self.members}) < 2:
            raise ContractValidationError("disagreement requires multiple analyses")


@dataclass(frozen=True, slots=True)
class OpenQuestionGroup:
    group_id: str
    questions: tuple[ManagementQuestion, ...]

    def __post_init__(self) -> None:
        _required(self.group_id, "group_id")
        if not self.questions or any(not isinstance(item, ManagementQuestion) for item in self.questions):
            raise ContractValidationError("open question group requires questions")


@dataclass(frozen=True, slots=True)
class ManagementConsiderationGroup:
    group_id: str
    considerations: tuple[str, ...]
    related_analysis: tuple[AnalysisReference, ...] = ()

    def __post_init__(self) -> None:
        _required(self.group_id, "group_id")
        object.__setattr__(self, "considerations", _unique(self.considerations, "considerations"))
        if not self.considerations:
            raise ContractValidationError("management consideration group must not be empty")
        if self.related_analysis:
            _reference_group(self.related_analysis, "management consideration group")


@dataclass(frozen=True, slots=True)
class DecisionAnalysisCollection:
    collection_id: str
    analyses: tuple[DecisionAnalysis, ...]
    agreements: tuple[AgreementGroup, ...] = ()
    disagreements: tuple[DisagreementGroup, ...] = ()
    open_questions: tuple[OpenQuestionGroup, ...] = ()
    management_considerations: tuple[ManagementConsiderationGroup, ...] = ()

    def __post_init__(self) -> None:
        _required(self.collection_id, "collection_id")
        if any(not isinstance(item, DecisionAnalysis) for item in self.analyses):
            raise ContractValidationError("analyses must contain DecisionAnalysis values")
        analysis_ids = [item.analysis_id for item in self.analyses]
        if len(analysis_ids) != len(set(analysis_ids)):
            raise ContractValidationError("collection contains duplicate analysis IDs")
        known = {
            analysis.analysis_id: {
                *(item.statement_id for item in analysis.computed_facts),
                *(item.statement.statement_id for item in analysis.inferences),
                *(item.hypothesis_id for item in analysis.hypotheses),
                *(item.recommendation_id for item in analysis.recommendations),
            }
            for analysis in self.analyses
        }
        groups = self.agreements + self.disagreements
        groups += tuple(item for item in self.management_considerations if item.related_analysis)
        for group in groups:
            members = group.members if hasattr(group, "members") else group.related_analysis
            if any(ref.analysis_id not in known or ref.conclusion_id not in known[ref.analysis_id]
                   for ref in members):
                raise ContractValidationError("collection group references an unknown conclusion")
