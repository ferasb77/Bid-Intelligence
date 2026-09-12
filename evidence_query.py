"""Deterministic read-only queries over an immutable :mod:`evidence_graph`.

This module indexes relationships already declared by the graph.  It never
creates, repairs, or infers an evidence relationship.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from evidence_graph import EvidenceEdge, EvidenceGraph, EvidenceNode, NodeType, RelationshipType


@dataclass(frozen=True, slots=True, order=True)
class ValidationFailure:
    code: str
    message: str
    stable_id: str | None = None


@dataclass(frozen=True, slots=True)
class QueryResult:
    items: tuple[Any, ...] = ()
    failures: tuple[ValidationFailure, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        object.__setattr__(self, "failures", tuple(sorted(self.failures)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(sorted(self.metadata.items()))))

    @property
    def valid(self) -> bool:
        return not self.failures


@dataclass(frozen=True, slots=True)
class EvidenceTrace:
    subject_id: str
    snapshot_id: str
    nodes: tuple[EvidenceNode, ...]
    edges: tuple[EvidenceEdge, ...]
    failures: tuple[ValidationFailure, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.failures


@dataclass(frozen=True, slots=True)
class EvidenceImpact:
    subject_id: str
    requirements: tuple[EvidenceNode, ...]
    conflicts: tuple[EvidenceNode, ...]
    bid_brief_sections: tuple[EvidenceNode, ...]


@dataclass(frozen=True, slots=True)
class GraphTraversal:
    """Immutable adjacency indexes shared by all engine queries."""

    graph: EvidenceGraph
    nodes: Mapping[str, EvidenceNode] = field(init=False, repr=False)
    outgoing: Mapping[str, tuple[EvidenceEdge, ...]] = field(init=False, repr=False)
    incoming: Mapping[str, tuple[EvidenceEdge, ...]] = field(init=False, repr=False)
    by_type: Mapping[NodeType, tuple[EvidenceNode, ...]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        nodes = MappingProxyType({node.stable_id: node for node in self.graph.nodes})
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "outgoing", MappingProxyType({node_id: tuple(
            edge for edge in self.graph.edges if edge.source_id == node_id)
            for node_id in nodes}))
        object.__setattr__(self, "incoming", MappingProxyType({node_id: tuple(
            edge for edge in self.graph.edges if edge.target_id == node_id)
            for node_id in nodes}))
        object.__setattr__(self, "by_type", MappingProxyType({kind: tuple(
            node for node in self.graph.nodes if node.type is kind) for kind in NodeType}))

    def ancestors(self, stable_id: str) -> tuple[str, ...]:
        return self._walk(stable_id, self.incoming, "source_id")

    def descendants(self, stable_id: str) -> tuple[str, ...]:
        return self._walk(stable_id, self.outgoing, "target_id")

    @staticmethod
    def _walk(stable_id: str, index: Mapping[str, tuple[EvidenceEdge, ...]], field: str) -> tuple[str, ...]:
        if stable_id not in index:
            return ()
        seen, pending = {stable_id}, [stable_id]
        while pending:
            current = pending.pop()
            for edge in index[current]:
                candidate = getattr(edge, field)
                if candidate not in seen:
                    seen.add(candidate)
                    pending.append(candidate)
        return tuple(sorted(seen))


@dataclass(frozen=True, slots=True)
class EvidenceQueryEngine:
    """Cached deterministic queries over one immutable graph snapshot."""

    graph: EvidenceGraph
    traversal: GraphTraversal = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.graph, EvidenceGraph):
            raise TypeError("graph must be an EvidenceGraph")
        object.__setattr__(self, "traversal", GraphTraversal(self.graph))

    def trace_requirement(self, requirement_id: str) -> QueryResult:
        return self._trace(requirement_id, NodeType.REQUIREMENT)

    def trace_bid_brief_section(self, section_id: str) -> QueryResult:
        return self._trace(section_id, NodeType.BID_BRIEF_SECTION)

    def trace_conflict(self, conflict_id: str) -> QueryResult:
        return self._trace(conflict_id, NodeType.CONFLICT)

    def _trace(self, stable_id: str, expected: NodeType) -> QueryResult:
        node = self.traversal.nodes.get(stable_id)
        if node is None:
            return QueryResult(failures=(ValidationFailure("MISSING_NODE", "query subject does not exist", stable_id),))
        if node.type is not expected:
            return QueryResult(failures=(ValidationFailure("TYPE_MISMATCH", f"expected {expected.value}", stable_id),))
        ids = set(self.traversal.ancestors(stable_id))
        if expected in {NodeType.REQUIREMENT, NodeType.CONFLICT}:
            ids.update(self.traversal.descendants(stable_id))
        nodes = tuple(node for node in self.graph.nodes if node.stable_id in ids)
        edges = tuple(edge for edge in self.graph.edges
                      if edge.source_id in ids and edge.target_id in ids)
        trace = EvidenceTrace(stable_id, self.graph.snapshot_id, nodes, edges)
        failures = self.validate_trace(trace).failures
        if failures:
            trace = EvidenceTrace(stable_id, self.graph.snapshot_id, nodes, edges, failures)
        return QueryResult((trace,), failures)

    def requirements_from_artifact(self, artifact_id: str) -> QueryResult:
        node = self._node(artifact_id, NodeType.ARTIFACT)
        if isinstance(node, QueryResult):
            return node
        reached = set(self.traversal.descendants(artifact_id))
        return self._nodes(NodeType.REQUIREMENT, reached)

    def artifacts_for_requirement(self, requirement_id: str) -> QueryResult:
        node = self._node(requirement_id, NodeType.REQUIREMENT)
        if isinstance(node, QueryResult):
            return node
        return self._nodes(NodeType.ARTIFACT, set(self.traversal.ancestors(requirement_id)))

    def occurrences_for_requirement(self, requirement_id: str) -> QueryResult:
        return self._ancestors_of_type(requirement_id, NodeType.OCCURRENCE)

    def extracts_for_requirement(self, requirement_id: str) -> QueryResult:
        return self._ancestors_of_type(requirement_id, NodeType.EXTRACT)

    def commercial_clauses(self) -> QueryResult:
        return QueryResult(self.traversal.by_type[NodeType.COMMERCIAL_CLAUSE])

    def submission_requirements(self) -> QueryResult:
        return QueryResult(self.traversal.by_type[NodeType.SUBMISSION_RULE])

    def mandatory_requirements(self) -> QueryResult:
        return self._requirements_matching("mandatory")

    def financial_requirements(self) -> QueryResult:
        return self._requirements_matching("financial", "finance", "pricing", "commercial")

    def rated_requirements(self) -> QueryResult:
        return self._requirements_matching("rated", "evaluation")

    def supporting_requirements(self) -> QueryResult:
        return self._requirements_matching("supporting", "support")

    def conflicts(self) -> QueryResult:
        return QueryResult(self.traversal.by_type[NodeType.CONFLICT])

    def requirements_without_extracts(self) -> QueryResult:
        return QueryResult(tuple(req for req in self.traversal.by_type[NodeType.REQUIREMENT]
                                 if not self.extracts_for_requirement(req.stable_id).items))

    def requirements_without_occurrences(self) -> QueryResult:
        return QueryResult(tuple(req for req in self.traversal.by_type[NodeType.REQUIREMENT]
                                 if not self.occurrences_for_requirement(req.stable_id).items))

    def unused_extracts(self) -> QueryResult:
        used = {edge.source_id for edge in self.graph.edges
                if edge.relationship_type is RelationshipType.SUPPORTS_REQUIREMENT}
        return QueryResult(tuple(node for node in self.traversal.by_type[NodeType.EXTRACT]
                                 if node.stable_id not in used))

    def unused_occurrences(self) -> QueryResult:
        used_extracts = {edge.source_id for edge in self.graph.edges
                         if edge.relationship_type is RelationshipType.SUPPORTS_REQUIREMENT}
        used = {edge.source_id for edge in self.graph.edges
                if edge.relationship_type is RelationshipType.HAS_EXTRACT
                and edge.target_id in used_extracts}
        return QueryResult(tuple(node for node in self.traversal.by_type[NodeType.OCCURRENCE]
                                 if node.stable_id not in used))

    def requirements_by_source(self) -> QueryResult:
        groups = {}
        for artifact in self.traversal.by_type[NodeType.ARTIFACT]:
            key = artifact.attributes.get("file", artifact.stable_id)
            groups[str(key)] = self.requirements_from_artifact(artifact.stable_id).items
        return QueryResult(metadata=groups)

    def requirements_by_category(self) -> QueryResult:
        groups: dict[str, list[EvidenceNode]] = {}
        for req in self.traversal.by_type[NodeType.REQUIREMENT]:
            category = str(req.attributes.get("category") or "UNKNOWN")
            groups.setdefault(category, []).append(req)
        return QueryResult(metadata={key: tuple(value) for key, value in sorted(groups.items())})

    def graph_statistics(self) -> QueryResult:
        node_counts = {kind.value: len(self.traversal.by_type[kind]) for kind in NodeType}
        edge_counts = {kind.value: sum(edge.relationship_type is kind for edge in self.graph.edges)
                       for kind in RelationshipType}
        return QueryResult(metadata={"graph_id": self.graph.graph_id,
            "snapshot_id": self.graph.snapshot_id, "node_count": len(self.graph.nodes),
            "edge_count": len(self.graph.edges), "node_counts": MappingProxyType(node_counts),
            "edge_counts": MappingProxyType(edge_counts)})

    def impact(self, stable_id: str) -> QueryResult:
        if stable_id not in self.traversal.nodes:
            return QueryResult(failures=(ValidationFailure("MISSING_NODE", "impact subject does not exist", stable_id),))
        reached = set(self.traversal.descendants(stable_id))
        return QueryResult((EvidenceImpact(stable_id,
            self._nodes(NodeType.REQUIREMENT, reached).items,
            self._nodes(NodeType.CONFLICT, reached).items,
            self._nodes(NodeType.BID_BRIEF_SECTION, reached).items),))

    def validate_snapshot(self) -> QueryResult:
        failures = []
        for node in self.graph.nodes:
            if node.snapshot_id != self.graph.snapshot_id:
                failures.append(ValidationFailure("SNAPSHOT_MISMATCH", "node is bound to another snapshot", node.stable_id))
        return QueryResult(failures=tuple(failures))

    def validate_provenance(self) -> QueryResult:
        failures = []
        for edge in self.graph.edges:
            if not edge.provenance:
                failures.append(ValidationFailure("MISSING_PROVENANCE", "edge has no provenance", edge.stable_id))
            for reference in edge.provenance:
                if reference.stable_id not in self.traversal.nodes:
                    failures.append(ValidationFailure("BROKEN_PROVENANCE", "provenance target is missing", edge.stable_id))
        return QueryResult(failures=tuple(failures))

    def validate_relationship_chain(self, subject_id: str) -> QueryResult:
        node = self.traversal.nodes.get(subject_id)
        if node is None:
            return QueryResult(failures=(ValidationFailure("MISSING_NODE", "chain subject does not exist", subject_id),))
        if node.type not in {NodeType.REQUIREMENT, NodeType.CONFLICT, NodeType.BID_BRIEF_SECTION}:
            return QueryResult(failures=(ValidationFailure("UNSUPPORTED_TRACE_TYPE", "node is not traceable", subject_id),))
        ancestors = set(self.traversal.ancestors(subject_id))
        failures = []
        for required_type, code in ((NodeType.ARTIFACT, "MISSING_ARTIFACT"),
                                    (NodeType.OCCURRENCE, "MISSING_OCCURRENCE"),
                                    (NodeType.EXTRACT, "MISSING_EXTRACT")):
            if not any(self.traversal.nodes[item].type is required_type for item in ancestors):
                failures.append(ValidationFailure(code, f"trace lacks {required_type.value}", subject_id))
        if node.type in {NodeType.CONFLICT, NodeType.BID_BRIEF_SECTION} and not any(
                self.traversal.nodes[item].type is NodeType.REQUIREMENT for item in ancestors):
            failures.append(ValidationFailure("MISSING_REQUIREMENT", "trace lacks REQUIREMENT", subject_id))
        return QueryResult(failures=tuple(failures))

    def validate_trace(self, trace: EvidenceTrace) -> QueryResult:
        failures = list(self.validate_snapshot().failures)
        failures.extend(self.validate_provenance().failures)
        failures.extend(self.validate_relationship_chain(trace.subject_id).failures)
        trace_ids = {node.stable_id for node in trace.nodes}
        if any(edge.source_id not in trace_ids or edge.target_id not in trace_ids for edge in trace.edges):
            failures.append(ValidationFailure("BROKEN_TRACE_EDGE", "trace edge endpoint is absent", trace.subject_id))
        return QueryResult(failures=tuple(failures))

    def _node(self, stable_id: str, expected: NodeType):
        node = self.traversal.nodes.get(stable_id)
        if node is None:
            return QueryResult(failures=(ValidationFailure("MISSING_NODE", "query subject does not exist", stable_id),))
        if node.type is not expected:
            return QueryResult(failures=(ValidationFailure("TYPE_MISMATCH", f"expected {expected.value}", stable_id),))
        return node

    def _nodes(self, node_type: NodeType, ids: set[str]) -> QueryResult:
        return QueryResult(tuple(node for node in self.traversal.by_type[node_type]
                                 if node.stable_id in ids))

    def _ancestors_of_type(self, requirement_id: str, node_type: NodeType) -> QueryResult:
        node = self._node(requirement_id, NodeType.REQUIREMENT)
        if isinstance(node, QueryResult):
            return node
        return self._nodes(node_type, set(self.traversal.ancestors(requirement_id)))

    def _requirements_matching(self, *terms: str) -> QueryResult:
        def matches(node: EvidenceNode) -> bool:
            fields = (node.attributes.get("category"), node.attributes.get("requirement_type"))
            tokens = " ".join(str(value).lower() for value in fields if value is not None)
            return any(term in tokens for term in terms)
        return QueryResult(tuple(node for node in self.traversal.by_type[NodeType.REQUIREMENT] if matches(node)))
