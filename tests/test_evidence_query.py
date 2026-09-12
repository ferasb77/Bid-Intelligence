import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from evidence_graph import (EdgeConfidence, EvidenceEdge, EvidenceGraph,
    EvidenceGraphError, EvidenceNode, EvidenceReference, GraphBuilder,
    NodeType, RelationshipType)
from evidence_query import EvidenceQueryEngine, EvidenceTrace, QueryResult


SNAP = "query-snapshot"


def _node(stable_id, kind, attributes=None):
    return EvidenceNode(stable_id, kind, attributes or {}, (), SNAP)


def _edge(source, target, kind):
    return EvidenceEdge(source.stable_id, target.stable_id, kind,
        EdgeConfidence.VERIFIED,
        (EvidenceReference(source.stable_id, source.type, SNAP),))


def _graph(include_evidence=True):
    artifact = _node("artifact", NodeType.ARTIFACT, {"file": "rfp.pdf"})
    occurrence = _node("occurrence", NodeType.OCCURRENCE)
    extract = _node("extract", NodeType.EXTRACT)
    requirement = _node("requirement", NodeType.REQUIREMENT,
                        {"category": "Mandatory", "requirement_type": "Financial"})
    conflict = _node("conflict", NodeType.CONFLICT)
    section = _node("section", NodeType.BID_BRIEF_SECTION)
    nodes = [requirement, conflict, section]
    edges = [_edge(requirement, conflict, RelationshipType.HAS_CONFLICT),
             _edge(conflict, section, RelationshipType.SUPPORTS_BID_BRIEF_SECTION)]
    if include_evidence:
        nodes += [artifact, occurrence, extract]
        edges += [_edge(artifact, occurrence, RelationshipType.HAS_OCCURRENCE),
                  _edge(occurrence, extract, RelationshipType.HAS_EXTRACT),
                  _edge(extract, requirement, RelationshipType.SUPPORTS_REQUIREMENT)]
    return GraphBuilder(SNAP)._chain(nodes, edges) if False else _build(nodes, edges)


def _build(nodes, edges):
    builder = GraphBuilder(SNAP)
    for value in nodes:
        builder.add_node(value)
    for value in edges:
        builder.add_edge(value)
    return builder.build()


def _bank_engine():
    root = Path(__file__).resolve().parents[1] / "evaluation/bank_of_canada_briefing_pack/corrected_pipeline"
    normalized = json.loads((root / "stage_b_normalized_facts.json").read_text(encoding="utf-8"))
    conflicts = json.loads((root / "stage_c_conflicts.json").read_text(encoding="utf-8"))
    return EvidenceQueryEngine(GraphBuilder.from_normalized_replay(
        "bank-of-canada-frozen", normalized, conflicts))


def test_traces_preserve_complete_chain_and_are_deterministic():
    engine = EvidenceQueryEngine(_graph())
    first = engine.trace_requirement("requirement")
    second = engine.trace_requirement("requirement")
    assert first == second and first.valid
    trace = first.items[0]
    assert isinstance(trace, EvidenceTrace)
    assert {node.type for node in trace.nodes} == {
        NodeType.ARTIFACT, NodeType.OCCURRENCE, NodeType.EXTRACT,
        NodeType.REQUIREMENT, NodeType.CONFLICT, NodeType.BID_BRIEF_SECTION}
    assert engine.trace_conflict("conflict").valid
    assert engine.trace_bid_brief_section("section").valid


def test_queries_cover_dependencies_categories_and_gaps():
    engine = EvidenceQueryEngine(_graph())
    assert len(engine.requirements_from_artifact("artifact").items) == 1
    assert len(engine.artifacts_for_requirement("requirement").items) == 1
    assert len(engine.occurrences_for_requirement("requirement").items) == 1
    assert len(engine.extracts_for_requirement("requirement").items) == 1
    assert len(engine.mandatory_requirements().items) == 1
    assert len(engine.financial_requirements().items) == 1
    assert not engine.rated_requirements().items
    assert not engine.supporting_requirements().items
    assert not engine.requirements_without_extracts().items
    assert not engine.requirements_without_occurrences().items
    assert not engine.unused_extracts().items
    assert not engine.unused_occurrences().items
    assert engine.requirements_by_source().metadata["rfp.pdf"][0].stable_id == "requirement"
    assert engine.requirements_by_category().metadata["Mandatory"][0].stable_id == "requirement"
    assert engine.impact("artifact").items[0].conflicts[0].stable_id == "conflict"


def test_expected_missing_and_broken_chain_failures_are_structured():
    engine = EvidenceQueryEngine(_graph(include_evidence=False))
    missing = engine.trace_requirement("absent")
    assert not missing.valid and missing.failures[0].code == "MISSING_NODE"
    broken = engine.trace_requirement("requirement")
    assert not broken.valid
    assert {failure.code for failure in broken.failures} == {
        "MISSING_ARTIFACT", "MISSING_OCCURRENCE", "MISSING_EXTRACT"}
    assert isinstance(engine.validate_relationship_chain("absent"), QueryResult)


def test_empty_graph_and_cached_indexes_are_read_only():
    engine = EvidenceQueryEngine(EvidenceGraph(SNAP, (), ()))
    assert engine.graph_statistics().metadata["node_count"] == 0
    assert engine.conflicts().items == ()
    assert engine.requirements_without_extracts().items == ()
    with pytest.raises(TypeError):
        engine.traversal.nodes["x"] = None
    with pytest.raises(FrozenInstanceError):
        engine.graph = _graph()


def test_large_graph_queries_use_stable_cached_ordering():
    nodes = [_node(f"R{i:04d}", NodeType.REQUIREMENT,
                   {"category": "Rated" if i % 2 else "Supporting"})
             for i in range(1000)]
    engine = EvidenceQueryEngine(_build(reversed(nodes), ()))
    assert len(engine.rated_requirements().items) == 500
    assert len(engine.supporting_requirements().items) == 500
    assert engine.graph_statistics().metadata["node_count"] == 1000
    assert engine.rated_requirements().items == engine.rated_requirements().items


def test_duplicate_identity_is_rejected_before_querying():
    duplicate = _node("same", NodeType.REQUIREMENT)
    with pytest.raises(EvidenceGraphError, match="duplicate node"):
        EvidenceGraph(SNAP, (duplicate, duplicate), ())


def test_bank_of_canada_frozen_graph_supports_every_query_deterministically():
    engine = _bank_engine()
    stats = engine.graph_statistics()
    assert stats.metadata["node_count"] == 2138
    assert stats.metadata["edge_count"] == 1837
    assert len(engine.commercial_clauses().items) == 91
    assert len(engine.submission_requirements().items) == 66
    assert len(engine.conflicts().items) == 9
    assert engine.mandatory_requirements().items
    assert engine.financial_requirements().items
    assert engine.rated_requirements().items
    engine.supporting_requirements()
    engine.requirements_without_extracts()
    engine.requirements_without_occurrences()
    engine.unused_extracts()
    engine.unused_occurrences()
    assert engine.requirements_by_source().metadata
    assert engine.requirements_by_category().metadata
    requirement = engine.graph.requirements()[0]
    artifact = engine.artifacts_for_requirement(requirement.stable_id).items[0]
    assert engine.trace_requirement(requirement.stable_id).valid
    assert engine.requirements_from_artifact(artifact.stable_id).items
    assert engine.occurrences_for_requirement(requirement.stable_id).items
    assert engine.extracts_for_requirement(requirement.stable_id).items
    conflict = engine.conflicts().items[0]
    assert engine.trace_conflict(conflict.stable_id).failures  # no invented requirement edge
    assert engine.trace_bid_brief_section("not-published").failures
    assert engine.validate_snapshot().valid
    assert engine.validate_provenance().valid
    assert engine.graph_statistics().metadata == engine.graph_statistics().metadata
