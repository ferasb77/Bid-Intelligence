import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from evidence_graph import (
    EdgeConfidence, EvidenceEdge, EvidenceGraphError, EvidenceNode,
    EvidenceReference, GraphBuilder, NodeType, RelationshipType,
)


SNAP = "snapshot-1"


def node(stable_id, node_type, attributes=None):
    return EvidenceNode(stable_id, node_type, attributes or {}, (), SNAP)


def ref(value):
    return EvidenceReference(value.stable_id, value.type, SNAP)


def edge(source, target, kind):
    return EvidenceEdge(source.stable_id, target.stable_id, kind,
                        EdgeConfidence.VERIFIED, (ref(source),))


def graph_fixture():
    artifact = node("artifact-1", NodeType.ARTIFACT, {"file": "rfp.pdf"})
    occurrence = node("occurrence-1", NodeType.OCCURRENCE)
    extract = node("extract-1", NodeType.EXTRACT)
    requirement = node("REQ-1", NodeType.REQUIREMENT)
    conflict = node("CONF-1", NodeType.CONFLICT)
    section = node("section-1", NodeType.BID_BRIEF_SECTION)
    builder = GraphBuilder(SNAP)
    for value in (section, conflict, requirement, extract, occurrence, artifact):
        builder.add_node(value)
    for value in (
        edge(artifact, occurrence, RelationshipType.HAS_OCCURRENCE),
        edge(occurrence, extract, RelationshipType.HAS_EXTRACT),
        edge(extract, requirement, RelationshipType.SUPPORTS_REQUIREMENT),
        edge(requirement, conflict, RelationshipType.HAS_CONFLICT),
        edge(requirement, section, RelationshipType.SUPPORTS_BID_BRIEF_SECTION),
    ):
        builder.add_edge(value)
    return builder, builder.build()


def test_graph_construction_queries_and_snapshot_preservation():
    _, graph = graph_fixture()
    assert [n.stable_id for n in graph.requirements()] == ["REQ-1"]
    assert [n.stable_id for n in graph.conflicts()] == ["CONF-1"]
    assert len(graph.bid_brief_dependencies()) == 1
    assert [n.stable_id for n in graph.requirements_for_artifact("rfp.pdf")] == ["REQ-1"]
    assert [n.stable_id for n in graph.artifacts_for_requirement("REQ-1")] == ["artifact-1"]
    assert all(n.snapshot_id == SNAP for n in graph.trace_requirement("REQ-1"))
    assert {n.stable_id for n in graph.trace_conflict("CONF-1")} == {
        "artifact-1", "occurrence-1", "extract-1", "REQ-1", "CONF-1", "section-1"}


def test_graph_and_nested_attributes_are_immutable_and_builder_seals():
    builder, graph = graph_fixture()
    with pytest.raises(FrozenInstanceError):
        graph.snapshot_id = "other"
    with pytest.raises(TypeError):
        graph.nodes[-1].attributes["x"] = 1
    with pytest.raises(EvidenceGraphError):
        builder.add_node(node("late", NodeType.REQUIREMENT))


def test_duplicate_nodes_edges_and_dangling_relationships_fail_closed():
    value = node("same", NodeType.REQUIREMENT)
    with pytest.raises(EvidenceGraphError, match="duplicate node"):
        GraphBuilder(SNAP).add_node(value).add_node(value).build()
    other = node("other", NodeType.CONFLICT)
    duplicate = edge(value, other, RelationshipType.HAS_CONFLICT)
    with pytest.raises(EvidenceGraphError, match="duplicate edge"):
        GraphBuilder(SNAP).add_node(value).add_node(other).add_edge(duplicate).add_edge(duplicate).build()
    with pytest.raises(EvidenceGraphError, match="endpoint"):
        GraphBuilder(SNAP).add_node(value).add_edge(duplicate).build()


def test_cycle_and_snapshot_mismatch_are_rejected():
    first = node("first", NodeType.REQUIREMENT)
    second = node("second", NodeType.CONFLICT)
    with pytest.raises(EvidenceGraphError, match="cycle"):
        (GraphBuilder(SNAP).add_node(first).add_node(second)
         .add_edge(edge(first, second, RelationshipType.HAS_CONFLICT))
         .add_edge(edge(second, first, RelationshipType.HAS_CONFLICT)).build())
    wrong = EvidenceNode("wrong", NodeType.REQUIREMENT, {}, (), "snapshot-2")
    with pytest.raises(EvidenceGraphError, match="snapshot mismatch"):
        GraphBuilder(SNAP).add_node(wrong).build()


def test_stable_ids_serialization_and_order_are_deterministic():
    _, first = graph_fixture(); _, second = graph_fixture()
    assert first.graph_id == second.graph_id
    assert first.to_json() == second.to_json()
    assert GraphBuilder.stable_id(NodeType.REQUIREMENT, {"b": 2, "a": 1}) == \
           GraphBuilder.stable_id(NodeType.REQUIREMENT, {"a": 1, "b": 2})


def test_replay_preserves_conflicting_duplicate_owner_labels_without_merging():
    normalized = {"requirements": [
        {"req_id": "M1", "description": "First", "source_refs": [{
            "source_doc": "a.pdf", "page": 1, "excerpt": "First"}]},
        {"req_id": "M1", "description": "Second", "source_refs": [{
            "source_doc": "a.pdf", "page": 2, "excerpt": "Second"}]},
    ]}
    graph = GraphBuilder.from_normalized_replay(SNAP, normalized)
    assert len(graph.requirements()) == 2
    assert len({n.stable_id for n in graph.requirements()}) == 2
    assert {n.attributes["req_id"] for n in graph.requirements()} == {"M1"}


def test_bank_of_canada_frozen_replay_builds_deterministically():
    root = Path(__file__).resolve().parents[1]
    normalized = json.loads((root / "evaluation/bank_of_canada_briefing_pack/corrected_pipeline/stage_b_normalized_facts.json").read_text(encoding="utf-8"))
    conflicts = json.loads((root / "evaluation/bank_of_canada_briefing_pack/corrected_pipeline/stage_c_conflicts.json").read_text(encoding="utf-8"))
    first = GraphBuilder.from_normalized_replay("bank-of-canada-frozen", normalized, conflicts)
    second = GraphBuilder.from_normalized_replay("bank-of-canada-frozen", normalized, conflicts)
    assert len(first.requirements()) == 413
    assert len(first.conflicts()) == len(conflicts)
    assert all(node.source_references for node in first.requirements())
    assert any(node.source_references for node in first.conflicts())
    assert first.graph_id == second.graph_id
    assert first.to_json() == second.to_json()
    assert first.requirements_for_artifact("abstract.pdf")
