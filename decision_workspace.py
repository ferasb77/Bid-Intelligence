"""Deterministic presentation of validated Decision Analysis outputs.

The workspace performs no analysis. It preserves analyst boundaries and exposes
facts, findings, assumptions, unknowns, hypotheses, questions, and limitations
without ranking, scoring, recommendation, or decision logic.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Iterable, Mapping

from decision_analyst import (
    AnalystAssumption,
    AnalystHypothesis,
    AnalystReasoning,
    AnalystUnknowns,
    DecisionAnalysis,
    DecisionAnalystMetadata,
    ManagementQuestion,
)
from decision_intelligence import (
    ContractValidationError,
    DecisionStatement,
    EvidenceSupport,
)


WORKSPACE_VERSION = "decision-workspace/1"


def _required(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{name} must be a non-empty string")


def _unique(values: tuple, name: str) -> None:
    if len(values) != len(set(values)):
        raise ContractValidationError(f"{name} must not contain duplicates")


def _evidence_key(value: EvidenceSupport) -> tuple[str, str, tuple[str, ...]]:
    return value.entity_type.value, value.entity_id, value.evidence_ids


@dataclass(frozen=True, slots=True)
class AnalystEvidenceCoverage:
    analyst_id: str
    analysis_id: str
    referenced_evidence: int
    evidence_with_source_ids: int
    unresolved_evidence_gaps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenceCategory:
    category: str
    count: int


@dataclass(frozen=True, slots=True)
class EvidenceOverview:
    authoritative_evidence: tuple[EvidenceSupport, ...]
    coverage: tuple[AnalystEvidenceCoverage, ...]
    categories: tuple[EvidenceCategory, ...]
    unresolved_evidence_gaps: tuple[tuple[str, str, tuple[str, ...]], ...]


@dataclass(frozen=True, slots=True)
class AnalystFacts:
    analyst_id: str
    analysis_id: str
    facts: tuple[DecisionStatement, ...]


@dataclass(frozen=True, slots=True)
class AnalystFindings:
    analyst_id: str
    analysis_id: str
    findings: tuple[AnalystReasoning, ...]


@dataclass(frozen=True, slots=True)
class AnalystAssumptions:
    analyst_id: str
    analysis_id: str
    assumptions: tuple[AnalystAssumption, ...]


@dataclass(frozen=True, slots=True)
class AnalystUnknownGroup:
    analyst_id: str
    analysis_id: str
    missing_evidence: tuple[str, ...]
    unresolved_conflicts: tuple[str, ...]
    unavailable_information: tuple[str, ...]
    ambiguity: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnalystAlternatives:
    analyst_id: str
    analysis_id: str
    hypotheses: tuple[AnalystHypothesis, ...]


@dataclass(frozen=True, slots=True)
class AnalystConsiderations:
    """Existing analyst findings displayed for deliberation, without selection."""

    analyst_id: str
    analysis_id: str
    considerations: tuple[AnalystReasoning, ...]


@dataclass(frozen=True, slots=True)
class AnalystQuestions:
    analyst_id: str
    analysis_id: str
    questions: tuple[ManagementQuestion, ...]


@dataclass(frozen=True, slots=True)
class AnalystLimitations:
    analyst_id: str
    analysis_id: str
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WorkspaceAnalyst:
    analyst_id: str
    analyst_version: str
    analysis_id: str


@dataclass(frozen=True, slots=True)
class DecisionWorkspace:
    workspace_id: str
    workspace_version: str
    analysts: tuple[WorkspaceAnalyst, ...]
    evidence_overview: EvidenceOverview
    computed_facts: tuple[AnalystFacts, ...]
    analyst_findings: tuple[AnalystFindings, ...]
    assumptions: tuple[AnalystAssumptions, ...]
    unknowns: tuple[AnalystUnknownGroup, ...]
    alternative_interpretations: tuple[AnalystAlternatives, ...]
    decision_considerations: tuple[AnalystConsiderations, ...]
    management_questions: tuple[AnalystQuestions, ...]
    limitations: tuple[AnalystLimitations, ...]

    def __post_init__(self) -> None:
        _required(self.workspace_id, "workspace_id")
        if self.workspace_version != WORKSPACE_VERSION:
            raise ContractValidationError("unsupported workspace version")
        _unique(tuple(item.analysis_id for item in self.analysts), "analysis IDs")


def _validate_analysis(analysis: DecisionAnalysis) -> None:
    if not isinstance(analysis, DecisionAnalysis):
        raise ContractValidationError("workspace inputs must be DecisionAnalysis objects")
    analysis.__post_init__()
    if analysis.recommendations:
        raise ContractValidationError("Decision Workspace cannot contain recommendations")
    declared = set(analysis.evidence_used)
    used = [link for fact in analysis.computed_facts for link in fact.evidence_support]
    used += [link for finding in analysis.inferences for link in finding.statement.evidence_support]
    used += [link for hypothesis in analysis.hypotheses
             for link in hypothesis.supporting_evidence + hypothesis.contradicting_evidence]
    if any(link not in declared for link in used):
        raise ContractValidationError("analysis contains a missing evidence reference")
    if any(not isinstance(item, EvidenceSupport) for item in analysis.evidence_used):
        raise ContractValidationError("analysis evidence is invalid")


def _metadata_catalog(metadata: Iterable[DecisionAnalystMetadata]) -> Mapping[str, DecisionAnalystMetadata]:
    result = {}
    for item in metadata:
        if not isinstance(item, DecisionAnalystMetadata):
            raise ContractValidationError("analyst metadata is invalid")
        if item.analyst_id in result:
            raise ContractValidationError("duplicate analyst metadata")
        result[item.analyst_id] = item
    return result


def _default_metadata() -> tuple[DecisionAnalystMetadata, ...]:
    from opportunity_intelligence import METADATA
    return (METADATA,)


def build_decision_workspace(
    analyses: Iterable[DecisionAnalysis],
    *,
    analyst_metadata: Iterable[DecisionAnalystMetadata] | None = None,
    supported_versions: Mapping[str, str] | None = None,
) -> DecisionWorkspace:
    """Arrange analyses into immutable views without interpreting their content."""
    values = tuple(analyses)
    if not values:
        raise ContractValidationError("workspace requires at least one analysis")
    for analysis in values:
        _validate_analysis(analysis)
    analysis_ids = tuple(item.analysis_id for item in values)
    _unique(analysis_ids, "analysis IDs")

    catalog = _metadata_catalog(_default_metadata() if analyst_metadata is None else analyst_metadata)
    supported = ({item.analyst_id: item.analyst_version for item in catalog.values()}
                 if supported_versions is None else dict(supported_versions))
    for analysis in values:
        metadata = catalog.get(analysis.analyst_id)
        if metadata is None:
            raise ContractValidationError(f"unsupported analyst: {analysis.analyst_id}")
        if supported.get(analysis.analyst_id) != metadata.analyst_version:
            raise ContractValidationError(
                f"unsupported analyst version: {analysis.analyst_id}/{metadata.analyst_version}")

    ordered = tuple(sorted(values, key=lambda item: (item.analyst_id, item.analysis_id)))
    evidence = tuple(sorted(
        {link for item in ordered for link in item.evidence_used}, key=_evidence_key))
    categories = Counter(link.entity_type.value for link in evidence)

    coverage = tuple(AnalystEvidenceCoverage(
        item.analyst_id, item.analysis_id, len(item.evidence_used),
        sum(bool(link.evidence_ids) for link in item.evidence_used),
        tuple(sorted(item.unknowns.missing_evidence)),
    ) for item in ordered)
    evidence_overview = EvidenceOverview(
        evidence,
        coverage,
        tuple(EvidenceCategory(name, count) for name, count in sorted(categories.items())),
        tuple((item.analyst_id, item.analysis_id,
               tuple(sorted(item.unknowns.missing_evidence)))
              for item in ordered if item.unknowns.missing_evidence),
    )

    def identity(item: DecisionAnalysis) -> tuple[str, str]:
        return item.analyst_id, item.analysis_id

    analysts = tuple(WorkspaceAnalyst(
        item.analyst_id, catalog[item.analyst_id].analyst_version, item.analysis_id)
        for item in ordered)
    facts = tuple(AnalystFacts(*identity(item), tuple(item.computed_facts)) for item in ordered)
    findings = tuple(AnalystFindings(*identity(item), tuple(item.inferences)) for item in ordered)
    assumptions = tuple(AnalystAssumptions(*identity(item), tuple(item.assumptions)) for item in ordered)
    unknowns = tuple(AnalystUnknownGroup(
        *identity(item),
        tuple(sorted(item.unknowns.missing_evidence)),
        tuple(sorted(item.unknowns.unresolved_conflict_ids)),
        tuple(sorted((*item.unknowns.unavailable_datasets, *item.unknowns.unavailable_history))),
        tuple(sorted(item.unknowns.ambiguous_observation_ids)),
    ) for item in ordered)
    alternatives = tuple(AnalystAlternatives(
        *identity(item), tuple(item.hypotheses)) for item in ordered)
    considerations = tuple(AnalystConsiderations(
        *identity(item), tuple(item.inferences)) for item in ordered)
    questions = tuple(AnalystQuestions(
        *identity(item), tuple(item.unanswered_questions)) for item in ordered)
    limitations = tuple(AnalystLimitations(
        *identity(item), tuple(item.limitations)) for item in ordered)

    identity_payload = {
        "version": WORKSPACE_VERSION,
        "analysts": [(item.analyst_id, catalog[item.analyst_id].analyst_version,
                       item.analysis_id) for item in ordered],
    }
    workspace_id = "workspace-" + sha256(json.dumps(
        identity_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return DecisionWorkspace(
        workspace_id, WORKSPACE_VERSION, analysts, evidence_overview, facts,
        findings, assumptions, unknowns, alternatives, considerations,
        questions, limitations,
    )


def render_decision_workspace(workspace: DecisionWorkspace) -> str:
    """Return a deterministic lossless JSON rendering of the presentation model."""
    if not isinstance(workspace, DecisionWorkspace):
        raise ContractValidationError("workspace must be a DecisionWorkspace")
    return json.dumps(asdict(workspace), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=lambda value: value.value)
