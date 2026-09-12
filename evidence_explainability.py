"""Deterministic human-readable explanations of immutable Evidence Graph paths."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from evidence_graph import EdgeConfidence, EvidenceEdge, EvidenceNode, NodeType
from evidence_query import EvidenceQueryEngine, ValidationFailure


class ExplanationStatus(str, Enum):
    COMPLETE = "COMPLETE"
    EXPLANATION_INCOMPLETE = "EXPLANATION_INCOMPLETE"


@dataclass(frozen=True, slots=True, order=True)
class EvidenceCitation:
    stable_id: str
    node_type: NodeType
    snapshot_id: str
    source: str | None = None
    locator: str | None = None


@dataclass(frozen=True, slots=True)
class EvidencePath:
    snapshot_id: str
    nodes: tuple[EvidenceNode, ...]
    edges: tuple[EvidenceEdge, ...]


@dataclass(frozen=True, slots=True)
class EvidenceNarrative:
    summary: str
    evidence_path: tuple[str, ...]
    supporting_artifacts: tuple[str, ...]
    supporting_occurrences: tuple[str, ...]
    supporting_extracts: tuple[str, ...]
    supporting_requirements: tuple[str, ...]
    confidence: EdgeConfidence
    validation: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Explanation:
    subject_id: str
    subject_type: str
    snapshot_id: str
    status: ExplanationStatus
    narrative: EvidenceNarrative
    path: EvidencePath
    citations: tuple[EvidenceCitation, ...]
    failures: tuple[ValidationFailure, ...]


_CONFIDENCE_ORDER = {
    EdgeConfidence.UNKNOWN: 0,
    EdgeConfidence.LOW: 1,
    EdgeConfidence.MEDIUM: 2,
    EdgeConfidence.HIGH: 3,
    EdgeConfidence.VERIFIED: 4,
}


class ExplanationValidator:
    """Returns structured failures; validation does not repair explanations."""

    def __init__(self, query: EvidenceQueryEngine):
        self.query = query

    def validate_explanation(self, explanation: Explanation) -> tuple[ValidationFailure, ...]:
        failures = list(self.validate_snapshot(explanation))
        failures.extend(self.validate_citations(explanation))
        failures.extend(self.validate_trace(explanation.path, explanation.subject_id,
                                            explanation.subject_type))
        return tuple(sorted(set(failures)))

    def validate_citations(self, explanation: Explanation) -> tuple[ValidationFailure, ...]:
        failures = []
        keys = [(item.stable_id, item.node_type, item.snapshot_id) for item in explanation.citations]
        if len(keys) != len(set(keys)):
            failures.append(ValidationFailure("DUPLICATE_CITATION", "explanation contains duplicate citations",
                                              explanation.subject_id))
        for citation in explanation.citations:
            node = self.query.traversal.nodes.get(citation.stable_id)
            if node is None:
                failures.append(ValidationFailure("MISSING_CITATION", "citation target is absent",
                                                  citation.stable_id))
            elif node.type is not citation.node_type:
                failures.append(ValidationFailure("CITATION_TYPE_MISMATCH", "citation type differs from target",
                                                  citation.stable_id))
        return tuple(failures)

    def validate_snapshot(self, explanation: Explanation) -> tuple[ValidationFailure, ...]:
        failures = list(self.query.validate_snapshot().failures)
        if explanation.snapshot_id != self.query.graph.snapshot_id:
            failures.append(ValidationFailure("SNAPSHOT_MISMATCH", "explanation snapshot differs from graph",
                                              explanation.subject_id))
        if any(node.snapshot_id != explanation.snapshot_id for node in explanation.path.nodes):
            failures.append(ValidationFailure("PATH_SNAPSHOT_MISMATCH", "path crosses snapshot boundary",
                                              explanation.subject_id))
        return tuple(failures)

    def validate_trace(self, path: EvidencePath, subject_id: str,
                       subject_type: str) -> tuple[ValidationFailure, ...]:
        node_ids = {node.stable_id for node in path.nodes}
        failures = []
        if subject_id not in node_ids and subject_type not in {"EVIDENCE_SNAPSHOT", "GRAPH_STATISTICS"}:
            failures.append(ValidationFailure("MISSING_SUBJECT", "subject is absent from evidence path", subject_id))
        if any(edge.source_id not in node_ids or edge.target_id not in node_ids for edge in path.edges):
            failures.append(ValidationFailure("BROKEN_PATH", "path edge has a missing endpoint", subject_id))
        if _has_cycle(path):
            failures.append(ValidationFailure("CYCLIC_PATH", "explanation path contains a cycle", subject_id))
        types = {node.type for node in path.nodes}
        needs_evidence = subject_type in {
            NodeType.REQUIREMENT.value, NodeType.CONFLICT.value,
            NodeType.COMMERCIAL_CLAUSE.value, NodeType.SUBMISSION_RULE.value,
            NodeType.DELIVERABLE.value, NodeType.EVALUATION_CRITERION.value,
            NodeType.EXTRACT.value, NodeType.BID_BRIEF_SECTION.value,
        }
        if needs_evidence:
            for required, code in ((NodeType.ARTIFACT, "MISSING_ARTIFACT"),
                                   (NodeType.OCCURRENCE, "MISSING_OCCURRENCE"),
                                   (NodeType.EXTRACT, "MISSING_EXTRACT")):
                if required not in types:
                    failures.append(ValidationFailure(code, f"explanation lacks {required.value}", subject_id))
        if subject_type in {NodeType.CONFLICT.value, NodeType.BID_BRIEF_SECTION.value} and NodeType.REQUIREMENT not in types:
            failures.append(ValidationFailure("MISSING_REQUIREMENT", "explanation lacks REQUIREMENT", subject_id))
        return tuple(failures)


class ExplainabilityEngine:
    """Formats only values and relationships already present in a query graph."""

    __slots__ = ("query", "validator", "_cache", "_sealed")

    def __init__(self, query: EvidenceQueryEngine):
        if not isinstance(query, EvidenceQueryEngine):
            raise TypeError("query must be an EvidenceQueryEngine")
        object.__setattr__(self, "query", query)
        object.__setattr__(self, "validator", ExplanationValidator(query))
        object.__setattr__(self, "_cache", MappingProxyType({}))
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name, value):
        if getattr(self, "_sealed", False):
            raise AttributeError("ExplainabilityEngine is immutable")
        object.__setattr__(self, name, value)

    def explain_requirement(self, stable_id: str) -> Explanation:
        return self._explain_node(stable_id, NodeType.REQUIREMENT)

    def explain_conflict(self, stable_id: str) -> Explanation:
        return self._explain_node(stable_id, NodeType.CONFLICT)

    def explain_commercial_clause(self, stable_id: str) -> Explanation:
        return self._explain_node(stable_id, NodeType.COMMERCIAL_CLAUSE)

    def explain_submission_requirement(self, stable_id: str) -> Explanation:
        return self._explain_node(stable_id, NodeType.SUBMISSION_RULE)

    def explain_deliverable(self, stable_id: str) -> Explanation:
        return self._explain_node(stable_id, NodeType.DELIVERABLE)

    def explain_evaluation_criterion(self, stable_id: str) -> Explanation:
        return self._explain_node(stable_id, NodeType.EVALUATION_CRITERION)

    def explain_extract(self, stable_id: str) -> Explanation:
        return self._explain_node(stable_id, NodeType.EXTRACT)

    def explain_artifact(self, stable_id: str) -> Explanation:
        return self._explain_node(stable_id, NodeType.ARTIFACT)

    def explain_bid_brief_dependency(self, stable_id: str) -> Explanation:
        return self._explain_node(stable_id, NodeType.BID_BRIEF_SECTION)

    def explain_snapshot(self) -> Explanation:
        metadata = {"node_count": len(self.query.graph.nodes), "edge_count": len(self.query.graph.edges)}
        return self._special("EVIDENCE_SNAPSHOT", self.query.graph.snapshot_id, metadata)

    def explain_graph_statistics(self) -> Explanation:
        return self._special("GRAPH_STATISTICS", self.query.graph.graph_id,
                             self.query.graph_statistics().metadata)

    def _special(self, subject_type: str, subject_id: str, values: Mapping[str, Any]) -> Explanation:
        lines = tuple(f"{key}: {values[key]}" for key in sorted(values)
                      if isinstance(values[key], (str, int, float, bool)))
        path = EvidencePath(self.query.graph.snapshot_id, (), ())
        narrative = EvidenceNarrative(f"{subject_type} {subject_id}", lines, (), (), (), (),
                                      EdgeConfidence.UNKNOWN, ("COMPLETE",))
        explanation = Explanation(subject_id, subject_type, self.query.graph.snapshot_id,
                                  ExplanationStatus.COMPLETE, narrative, path, (), ())
        failures = self.validator.validate_explanation(explanation)
        if failures:
            return self._with_failures(explanation, failures)
        return explanation

    def _explain_node(self, stable_id: str, expected: NodeType) -> Explanation:
        subject = self.query.traversal.nodes.get(stable_id)
        if subject is None or subject.type is not expected:
            code = "MISSING_NODE" if subject is None else "TYPE_MISMATCH"
            failure = ValidationFailure(code, f"cannot explain {expected.value}", stable_id)
            empty = EvidencePath(self.query.graph.snapshot_id, (), ())
            narrative = EvidenceNarrative(f"{expected.value} {stable_id}", (), (), (), (), (),
                                          EdgeConfidence.UNKNOWN, (code,))
            return Explanation(stable_id, expected.value, self.query.graph.snapshot_id,
                               ExplanationStatus.EXPLANATION_INCOMPLETE, narrative, empty, (), (failure,))

        ids = {stable_id}
        ids.update(self.query.traversal.ancestors(stable_id))
        if expected in {NodeType.REQUIREMENT, NodeType.CONFLICT, NodeType.ARTIFACT}:
            ids.update(self.query.traversal.descendants(stable_id))
        for reference in subject.source_references:
            ids.add(reference.stable_id)
            ids.update(self.query.traversal.ancestors(reference.stable_id))
        nodes = tuple(node for node in self.query.graph.nodes if node.stable_id in ids)
        edges = tuple(edge for edge in self.query.graph.edges
                      if edge.source_id in ids and edge.target_id in ids)
        path = EvidencePath(self.query.graph.snapshot_id, nodes, edges)
        citations = tuple(_citation(node) for node in nodes
                          if node.type in {NodeType.ARTIFACT, NodeType.OCCURRENCE, NodeType.EXTRACT})
        confidence = min((edge.confidence for edge in edges),
                         key=lambda item: _CONFIDENCE_ORDER[item], default=EdgeConfidence.UNKNOWN)
        narrative = EvidenceNarrative(
            f"{expected.value} {stable_id}",
            tuple(f"{edge.source_id} {edge.relationship_type.value} {edge.target_id}" for edge in edges),
            _ids(nodes, NodeType.ARTIFACT), _ids(nodes, NodeType.OCCURRENCE),
            _ids(nodes, NodeType.EXTRACT), _ids(nodes, NodeType.REQUIREMENT),
            confidence, ("PENDING_VALIDATION",))
        draft = Explanation(stable_id, expected.value, self.query.graph.snapshot_id,
                            ExplanationStatus.COMPLETE, narrative, path, citations, ())
        failures = self.validator.validate_explanation(draft)
        if failures:
            return self._with_failures(draft, failures)
        return Explanation(stable_id, expected.value, self.query.graph.snapshot_id,
                           ExplanationStatus.COMPLETE,
                           EvidenceNarrative(narrative.summary, narrative.evidence_path,
                               narrative.supporting_artifacts, narrative.supporting_occurrences,
                               narrative.supporting_extracts, narrative.supporting_requirements,
                               narrative.confidence, ("COMPLETE",)), path, citations, ())

    @staticmethod
    def _with_failures(value: Explanation, failures: tuple[ValidationFailure, ...]) -> Explanation:
        narrative = value.narrative
        return Explanation(value.subject_id, value.subject_type, value.snapshot_id,
            ExplanationStatus.EXPLANATION_INCOMPLETE,
            EvidenceNarrative(narrative.summary, narrative.evidence_path,
                narrative.supporting_artifacts, narrative.supporting_occurrences,
                narrative.supporting_extracts, narrative.supporting_requirements,
                narrative.confidence, tuple(failure.code for failure in failures)),
            value.path, value.citations, failures)

    def validate_explanation(self, value: Explanation):
        return self.validator.validate_explanation(value)

    def validate_citations(self, value: Explanation):
        return self.validator.validate_citations(value)

    def validate_trace(self, value: Explanation):
        return self.validator.validate_trace(value.path, value.subject_id, value.subject_type)

    def validate_snapshot(self, value: Explanation):
        return self.validator.validate_snapshot(value)


def _ids(nodes: tuple[EvidenceNode, ...], node_type: NodeType) -> tuple[str, ...]:
    return tuple(node.stable_id for node in nodes if node.type is node_type)


def _citation(node: EvidenceNode) -> EvidenceCitation:
    attributes = node.attributes
    source = attributes.get("file") or attributes.get("source_doc")
    locator = attributes.get("locator")
    if locator is None:
        if attributes.get("page") is not None:
            locator = f"page:{attributes['page']}"
        elif attributes.get("section"):
            locator = f"section:{attributes['section']}"
        elif attributes.get("sheet"):
            locator = f"sheet:{attributes['sheet']}"
    return EvidenceCitation(node.stable_id, node.type, node.snapshot_id,
                            str(source) if source else None,
                            str(locator) if locator else None)


def _has_cycle(path: EvidencePath) -> bool:
    outgoing = {node.stable_id: [] for node in path.nodes}
    for edge in path.edges:
        if edge.source_id in outgoing:
            outgoing[edge.source_id].append(edge.target_id)
    visiting, visited = set(), set()
    def visit(node_id: str) -> bool:
        if node_id in visiting:
            return True
        if node_id in visited:
            return False
        visiting.add(node_id)
        if any(visit(child) for child in outgoing.get(node_id, ())):
            return True
        visiting.remove(node_id); visited.add(node_id)
        return False
    return any(visit(node_id) for node_id in outgoing)
