"""Immutable internal relationship graph for governed evidence and bid entities.

The graph is an additive index.  It does not own, normalize, reconcile, or
interpret the semantic objects represented by its nodes.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Iterable, Mapping


GRAPH_VERSION = "1.0.0"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


class EvidenceGraphError(ValueError):
    pass


class NodeType(str, Enum):
    ARTIFACT = "ARTIFACT"
    OCCURRENCE = "OCCURRENCE"
    EXTRACT = "EXTRACT"
    REQUIREMENT = "REQUIREMENT"
    EVALUATION_CRITERION = "EVALUATION_CRITERION"
    SUBMISSION_RULE = "SUBMISSION_RULE"
    COMMERCIAL_CLAUSE = "COMMERCIAL_CLAUSE"
    DELIVERABLE = "DELIVERABLE"
    CONFLICT = "CONFLICT"
    BID_BRIEF_SECTION = "BID_BRIEF_SECTION"


class RelationshipType(str, Enum):
    HAS_OCCURRENCE = "HAS_OCCURRENCE"
    HAS_EXTRACT = "HAS_EXTRACT"
    SUPPORTS_REQUIREMENT = "SUPPORTS_REQUIREMENT"
    HAS_EVALUATION_CRITERION = "HAS_EVALUATION_CRITERION"
    HAS_SUBMISSION_RULE = "HAS_SUBMISSION_RULE"
    HAS_COMMERCIAL_CLAUSE = "HAS_COMMERCIAL_CLAUSE"
    HAS_DELIVERABLE = "HAS_DELIVERABLE"
    HAS_CONFLICT = "HAS_CONFLICT"
    SUPPORTS_BID_BRIEF_SECTION = "SUPPORTS_BID_BRIEF_SECTION"


class EdgeConfidence(str, Enum):
    VERIFIED = "VERIFIED"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(value[k]) for k in sorted(value, key=str)})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (str, int, float, bool, type(None))):
        return unicodedata.normalize("NFC", value) if isinstance(value, str) else value
    if isinstance(value, Enum):
        return value.value
    raise EvidenceGraphError(f"unsupported graph value: {type(value).__name__}")


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _canonical(value: Any) -> str:
    return json.dumps(_plain(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _stable(prefix: str, value: Any) -> str:
    return f"{prefix}-{sha256(_canonical(value).encode('utf-8')).hexdigest()}"


def _valid_id(value: str, name: str) -> None:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise EvidenceGraphError(f"invalid {name}")


@dataclass(frozen=True, slots=True, order=True)
class EvidenceReference:
    stable_id: str
    node_type: NodeType
    snapshot_id: str

    def __post_init__(self) -> None:
        _valid_id(self.stable_id, "reference stable_id")
        _valid_id(self.snapshot_id, "reference snapshot_id")
        if not isinstance(self.node_type, NodeType):
            raise EvidenceGraphError("invalid reference node type")


@dataclass(frozen=True, slots=True)
class EvidenceNode:
    stable_id: str
    type: NodeType
    attributes: Mapping[str, Any]
    source_references: tuple[EvidenceReference, ...]
    snapshot_id: str

    def __post_init__(self) -> None:
        _valid_id(self.stable_id, "node stable_id")
        _valid_id(self.snapshot_id, "node snapshot_id")
        if not isinstance(self.type, NodeType):
            raise EvidenceGraphError("invalid node type")
        object.__setattr__(self, "attributes", _freeze(self.attributes))
        refs = tuple(sorted(self.source_references))
        if len(refs) != len(set(refs)):
            raise EvidenceGraphError("duplicate source reference")
        object.__setattr__(self, "source_references", refs)

    def to_dict(self) -> dict[str, Any]:
        return {"stable_id": self.stable_id, "type": self.type.value,
                "attributes": _plain(self.attributes),
                "source_references": [_plain_reference(r) for r in self.source_references],
                "snapshot_id": self.snapshot_id}


@dataclass(frozen=True, slots=True)
class EvidenceEdge:
    source_id: str
    target_id: str
    relationship_type: RelationshipType
    confidence: EdgeConfidence
    provenance: tuple[EvidenceReference, ...]

    def __post_init__(self) -> None:
        _valid_id(self.source_id, "edge source_id")
        _valid_id(self.target_id, "edge target_id")
        if self.source_id == self.target_id:
            raise EvidenceGraphError("self edges are prohibited")
        if not isinstance(self.relationship_type, RelationshipType):
            raise EvidenceGraphError("invalid relationship type")
        if not isinstance(self.confidence, EdgeConfidence):
            raise EvidenceGraphError("invalid edge confidence")
        refs = tuple(sorted(self.provenance))
        if not refs or len(refs) != len(set(refs)):
            raise EvidenceGraphError("edge provenance must be non-empty and unique")
        object.__setattr__(self, "provenance", refs)

    @property
    def stable_id(self) -> str:
        return _stable("edge", self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {"source_id": self.source_id, "target_id": self.target_id,
                "relationship_type": self.relationship_type.value,
                "confidence": self.confidence.value,
                "provenance": [_plain_reference(r) for r in self.provenance]}


def _plain_reference(value: EvidenceReference) -> dict[str, str]:
    return {"stable_id": value.stable_id, "node_type": value.node_type.value,
            "snapshot_id": value.snapshot_id}


@dataclass(frozen=True, slots=True)
class EvidenceGraph:
    snapshot_id: str
    nodes: tuple[EvidenceNode, ...]
    edges: tuple[EvidenceEdge, ...]
    version: str = GRAPH_VERSION
    _node_index: Mapping[str, EvidenceNode] = field(init=False, repr=False, compare=False)
    _outgoing: Mapping[str, tuple[EvidenceEdge, ...]] = field(init=False, repr=False, compare=False)
    _incoming: Mapping[str, tuple[EvidenceEdge, ...]] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        _valid_id(self.snapshot_id, "graph snapshot_id")
        if self.version != GRAPH_VERSION:
            raise EvidenceGraphError("unsupported graph version")
        ordered_nodes = tuple(sorted(self.nodes, key=lambda n: (n.type.value, n.stable_id)))
        ordered_edges = tuple(sorted(self.edges, key=lambda e: e.stable_id))
        if len({n.stable_id for n in ordered_nodes}) != len(ordered_nodes):
            raise EvidenceGraphError("duplicate node identity")
        if len({e.stable_id for e in ordered_edges}) != len(ordered_edges):
            raise EvidenceGraphError("duplicate edge identity")
        index = {n.stable_id: n for n in ordered_nodes}
        if any(n.snapshot_id != self.snapshot_id for n in ordered_nodes):
            raise EvidenceGraphError("node snapshot mismatch")
        for edge in ordered_edges:
            if edge.source_id not in index or edge.target_id not in index:
                raise EvidenceGraphError("edge endpoint is missing")
            if any(r.stable_id not in index or index[r.stable_id].type is not r.node_type
                   or r.snapshot_id != self.snapshot_id for r in edge.provenance):
                raise EvidenceGraphError("edge provenance is outside the graph snapshot")
        for node in ordered_nodes:
            if any(r.stable_id not in index or index[r.stable_id].type is not r.node_type
                   or r.snapshot_id != self.snapshot_id for r in node.source_references):
                raise EvidenceGraphError("node source reference is outside the graph snapshot")
        outgoing = {node_id: tuple(e for e in ordered_edges if e.source_id == node_id)
                    for node_id in index}
        incoming = {node_id: tuple(e for e in ordered_edges if e.target_id == node_id)
                    for node_id in index}
        _assert_acyclic(index, outgoing)
        object.__setattr__(self, "nodes", ordered_nodes)
        object.__setattr__(self, "edges", ordered_edges)
        object.__setattr__(self, "_node_index", MappingProxyType(index))
        object.__setattr__(self, "_outgoing", MappingProxyType(outgoing))
        object.__setattr__(self, "_incoming", MappingProxyType(incoming))

    @property
    def graph_id(self) -> str:
        return _stable("egraph", self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "snapshot_id": self.snapshot_id,
                "nodes": [n.to_dict() for n in self.nodes],
                "edges": [e.to_dict() for e in self.edges]}

    def to_json(self) -> str:
        return _canonical(self.to_dict())

    def _typed(self, node_type: NodeType) -> tuple[EvidenceNode, ...]:
        return tuple(node for node in self.nodes if node.type is node_type)

    def requirements(self) -> tuple[EvidenceNode, ...]:
        return self._typed(NodeType.REQUIREMENT)

    def conflicts(self) -> tuple[EvidenceNode, ...]:
        return self._typed(NodeType.CONFLICT)

    def bid_brief_dependencies(self) -> tuple[EvidenceEdge, ...]:
        return tuple(e for e in self.edges
                     if e.relationship_type is RelationshipType.SUPPORTS_BID_BRIEF_SECTION)

    def trace_requirement(self, req_id: str) -> tuple[EvidenceNode, ...]:
        return self._trace(req_id)

    def trace_conflict(self, conflict_id: str) -> tuple[EvidenceNode, ...]:
        return self._trace(conflict_id)

    def _trace(self, stable_id: str) -> tuple[EvidenceNode, ...]:
        if stable_id not in self._node_index:
            raise EvidenceGraphError(f"unknown node: {stable_id}")
        seen, pending = set(), [stable_id]
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            pending.extend(e.source_id for e in self._incoming[current])
            pending.extend(e.target_id for e in self._outgoing[current])
        return tuple(node for node in self.nodes if node.stable_id in seen)

    def requirements_for_artifact(self, artifact: str) -> tuple[EvidenceNode, ...]:
        starts = {n.stable_id for n in self.nodes if n.type is NodeType.ARTIFACT and
                  (n.stable_id == artifact or n.attributes.get("file") == artifact)}
        reached = self._forward(starts)
        return tuple(n for n in self.requirements() if n.stable_id in reached)

    def artifacts_for_requirement(self, requirement: str) -> tuple[EvidenceNode, ...]:
        if requirement not in self._node_index:
            raise EvidenceGraphError(f"unknown requirement: {requirement}")
        reached = self._backward({requirement})
        return tuple(n for n in self._typed(NodeType.ARTIFACT) if n.stable_id in reached)

    def _forward(self, starts: set[str]) -> set[str]:
        seen, pending = set(starts), list(starts)
        while pending:
            for edge in self._outgoing[pending.pop()]:
                if edge.target_id not in seen:
                    seen.add(edge.target_id); pending.append(edge.target_id)
        return seen

    def _backward(self, starts: set[str]) -> set[str]:
        seen, pending = set(starts), list(starts)
        while pending:
            for edge in self._incoming[pending.pop()]:
                if edge.source_id not in seen:
                    seen.add(edge.source_id); pending.append(edge.source_id)
        return seen


def _assert_acyclic(nodes: Mapping[str, EvidenceNode], outgoing: Mapping[str, tuple[EvidenceEdge, ...]]) -> None:
    visiting, visited = set(), set()
    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise EvidenceGraphError("graph cycle detected")
        if node_id in visited:
            return
        visiting.add(node_id)
        for edge in outgoing[node_id]:
            visit(edge.target_id)
        visiting.remove(node_id); visited.add(node_id)
    for node_id in nodes:
        visit(node_id)


class GraphBuilder:
    """Mutable construction boundary that seals into an immutable graph."""

    def __init__(self, snapshot_id: str):
        _valid_id(snapshot_id, "builder snapshot_id")
        self._snapshot_id = snapshot_id
        self._nodes: list[EvidenceNode] = []
        self._edges: list[EvidenceEdge] = []
        self._built = False

    def add_node(self, node: EvidenceNode) -> "GraphBuilder":
        self._open(); self._nodes.append(node); return self

    def add_edge(self, edge: EvidenceEdge) -> "GraphBuilder":
        self._open(); self._edges.append(edge); return self

    def build(self) -> EvidenceGraph:
        self._open(); self._built = True
        return EvidenceGraph(self._snapshot_id, tuple(self._nodes), tuple(self._edges))

    def _open(self) -> None:
        if self._built:
            raise EvidenceGraphError("builder is sealed")

    @staticmethod
    def stable_id(node_type: NodeType, attributes: Mapping[str, Any]) -> str:
        return _stable("eg" + node_type.value.lower().replace("_", "-"), _freeze(attributes))

    @classmethod
    def from_normalized_replay(cls, snapshot_id: str, normalized: Mapping[str, Any],
                               conflicts: Iterable[Mapping[str, Any]] = ()) -> EvidenceGraph:
        """Index frozen normalized artifacts without changing their contents."""
        builder = cls(snapshot_id)
        node_by_id: dict[str, EvidenceNode] = {}
        ref_nodes: dict[str, tuple[EvidenceNode, EvidenceNode, EvidenceNode]] = {}

        def add(node_type: NodeType, value: Mapping[str, Any], id_key: str | None = None,
                force_generated: bool = False,
                source_references: tuple[EvidenceReference, ...] = ()) -> EvidenceNode:
            existing = value.get(id_key) if id_key else None
            stable_id = (existing if not force_generated and isinstance(existing, str)
                         and _ID.fullmatch(existing) else cls.stable_id(node_type, value))
            node = EvidenceNode(stable_id, node_type, value, source_references, snapshot_id)
            if stable_id in node_by_id:
                if node_by_id[stable_id].attributes != node.attributes:
                    raise EvidenceGraphError(f"conflicting duplicate node: {stable_id}")
                return node_by_id[stable_id]
            node_by_id[stable_id] = node; builder.add_node(node); return node

        def source_chain(ref: Mapping[str, Any]) -> EvidenceNode:
            key = _canonical(_freeze(ref))
            if key in ref_nodes:
                return ref_nodes[key][2]
            file = ref.get("source_doc")
            if not isinstance(file, str) or not file:
                raise EvidenceGraphError("source reference lacks source_doc")
            artifact = add(NodeType.ARTIFACT, {"file": file})
            occurrence = add(NodeType.OCCURRENCE, dict(ref))
            extract = add(NodeType.EXTRACT, dict(ref))
            ar = EvidenceReference(artifact.stable_id, artifact.type, snapshot_id)
            oc = EvidenceReference(occurrence.stable_id, occurrence.type, snapshot_id)
            builder.add_edge(EvidenceEdge(artifact.stable_id, occurrence.stable_id,
                RelationshipType.HAS_OCCURRENCE, EdgeConfidence.VERIFIED, (ar,)))
            builder.add_edge(EvidenceEdge(occurrence.stable_id, extract.stable_id,
                RelationshipType.HAS_EXTRACT, EdgeConfidence.VERIFIED, (oc,)))
            ref_nodes[key] = (artifact, occurrence, extract)
            return extract

        requirement_values = tuple(normalized.get("requirements", ()))
        requirement_id_counts: dict[str, int] = {}
        for value in requirement_values:
            req_id = value.get("req_id")
            if isinstance(req_id, str):
                requirement_id_counts[req_id] = requirement_id_counts.get(req_id, 0) + 1
        requirements = []
        for value in requirement_values:
            extracts = tuple(source_chain(ref) for ref in value.get("source_refs", ()))
            source_references = tuple(EvidenceReference(item.stable_id, item.type, snapshot_id)
                                      for item in extracts)
            req = add(NodeType.REQUIREMENT, value, "req_id",
                      requirement_id_counts.get(value.get("req_id"), 0) > 1,
                      source_references)
            requirements.append(req)
            for extract in extracts:
                provenance = (EvidenceReference(extract.stable_id, extract.type, snapshot_id),)
                builder.add_edge(EvidenceEdge(extract.stable_id, req.stable_id,
                    RelationshipType.SUPPORTS_REQUIREMENT, EdgeConfidence.VERIFIED, provenance))

        groups = (
            ("evaluation_criteria", NodeType.EVALUATION_CRITERION, "criterion_id", RelationshipType.HAS_EVALUATION_CRITERION),
            ("submission_rules", NodeType.SUBMISSION_RULE, "rule_id", RelationshipType.HAS_SUBMISSION_RULE),
            ("commercial_clauses", NodeType.COMMERCIAL_CLAUSE, "clause_id", RelationshipType.HAS_COMMERCIAL_CLAUSE),
            ("deliverables", NodeType.DELIVERABLE, "deliverable_id", RelationshipType.HAS_DELIVERABLE),
        )
        for key, node_type, id_key, relationship in groups:
            for value in normalized.get(key, ()):
                extracts = tuple(source_chain(ref) for ref in value.get("source_refs", ()))
                target = add(node_type, value, id_key, source_references=tuple(
                    EvidenceReference(item.stable_id, item.type, snapshot_id)
                    for item in extracts))
                # Only explicit requirement links create requirement relationships.
                linked = value.get("requirement_ids", ())
                for req in requirements:
                    if req.stable_id in linked:
                        builder.add_edge(EvidenceEdge(req.stable_id, target.stable_id,
                            relationship, EdgeConfidence.VERIFIED,
                            (EvidenceReference(req.stable_id, req.type, snapshot_id),)))
        for value in conflicts:
            extracts = tuple(source_chain(ref) for ref in value.get("source_refs", ()))
            target = add(NodeType.CONFLICT, value, "conflict_id", source_references=tuple(
                EvidenceReference(item.stable_id, item.type, snapshot_id)
                for item in extracts))
            for req_id in value.get("requirement_ids", ()):
                if req_id in node_by_id:
                    req = node_by_id[req_id]
                    builder.add_edge(EvidenceEdge(req.stable_id, target.stable_id,
                        RelationshipType.HAS_CONFLICT, EdgeConfidence.VERIFIED,
                        (EvidenceReference(req.stable_id, req.type, snapshot_id),)))
        return builder.build()
