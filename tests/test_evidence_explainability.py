import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from evidence_explainability import (EvidenceCitation, EvidencePath,
    ExplainabilityEngine, ExplanationStatus)
from evidence_graph import (EdgeConfidence, EvidenceEdge, EvidenceGraphError,
    EvidenceNode, EvidenceReference, GraphBuilder, NodeType, RelationshipType)
from evidence_query import EvidenceQueryEngine


SNAP = "explain-snapshot"


def _node(stable_id, kind, attributes=None, refs=()):
    return EvidenceNode(stable_id, kind, attributes or {}, refs, SNAP)


def _ref(node):
    return EvidenceReference(node.stable_id, node.type, SNAP)


def _edge(source, target, kind, confidence=EdgeConfidence.VERIFIED):
    return EvidenceEdge(source.stable_id, target.stable_id, kind, confidence, (_ref(source),))


def _engine(complete=True):
    artifact = _node("artifact", NodeType.ARTIFACT, {"file": "rfp.pdf"})
    occurrence = _node("occurrence", NodeType.OCCURRENCE, {"source_doc": "rfp.pdf", "page": 1})
    extract = _node("extract", NodeType.EXTRACT, {"source_doc": "rfp.pdf", "page": 1})
    requirement = _node("requirement", NodeType.REQUIREMENT, {"description": "Submit response"},
                        (_ref(extract),) if complete else ())
    conflict = _node("conflict", NodeType.CONFLICT)
    section = _node("section", NodeType.BID_BRIEF_SECTION)
    evidence_refs = (_ref(extract),) if complete else ()
    clause = _node("clause", NodeType.COMMERCIAL_CLAUSE, {"source_fact": "Term"}, evidence_refs)
    submission = _node("submission", NodeType.SUBMISSION_RULE, {}, evidence_refs)
    deliverable = _node("deliverable", NodeType.DELIVERABLE, {}, evidence_refs)
    criterion = _node("criterion", NodeType.EVALUATION_CRITERION, {}, evidence_refs)
    nodes = [requirement, conflict, section, clause, submission, deliverable, criterion]
    edges = [_edge(requirement, conflict, RelationshipType.HAS_CONFLICT, EdgeConfidence.MEDIUM),
             _edge(conflict, section, RelationshipType.SUPPORTS_BID_BRIEF_SECTION)]
    if complete:
        nodes += [artifact, occurrence, extract]
        edges += [_edge(artifact, occurrence, RelationshipType.HAS_OCCURRENCE),
                  _edge(occurrence, extract, RelationshipType.HAS_EXTRACT),
                  _edge(extract, requirement, RelationshipType.SUPPORTS_REQUIREMENT)]
    builder = GraphBuilder(SNAP)
    for node in nodes:
        builder.add_node(node)
    for edge in edges:
        builder.add_edge(edge)
    return ExplainabilityEngine(EvidenceQueryEngine(builder.build()))


def _bank():
    root = Path(__file__).resolve().parents[1] / "evaluation/bank_of_canada_briefing_pack/corrected_pipeline"
    normalized = json.loads((root / "stage_b_normalized_facts.json").read_text(encoding="utf-8"))
    conflicts = json.loads((root / "stage_c_conflicts.json").read_text(encoding="utf-8"))
    graph = GraphBuilder.from_normalized_replay("bank-of-canada-frozen", normalized, conflicts)
    return ExplainabilityEngine(EvidenceQueryEngine(graph))


def test_complete_explanations_preserve_path_citations_and_confidence():
    engine = _engine()
    requirement = engine.explain_requirement("requirement")
    assert requirement.status is ExplanationStatus.COMPLETE
    assert requirement.narrative.supporting_artifacts == ("artifact",)
    assert requirement.narrative.supporting_occurrences == ("occurrence",)
    assert requirement.narrative.supporting_extracts == ("extract",)
    assert requirement.narrative.confidence is EdgeConfidence.MEDIUM
    assert requirement.narrative.validation == ("COMPLETE",)
    assert engine.explain_conflict("conflict").status is ExplanationStatus.COMPLETE
    assert engine.explain_bid_brief_dependency("section").status is ExplanationStatus.COMPLETE


def test_all_supported_evidence_and_domain_explainers_are_deterministic():
    engine = _engine()
    calls = ((engine.explain_commercial_clause, "clause"),
             (engine.explain_submission_requirement, "submission"),
             (engine.explain_deliverable, "deliverable"),
             (engine.explain_evaluation_criterion, "criterion"),
             (engine.explain_extract, "extract"),
             (engine.explain_artifact, "artifact"))
    for call, stable_id in calls:
        assert call(stable_id) == call(stable_id)
        assert call(stable_id).status is ExplanationStatus.COMPLETE
    assert engine.explain_snapshot().status is ExplanationStatus.COMPLETE
    assert engine.explain_graph_statistics().status is ExplanationStatus.COMPLETE


def test_missing_nodes_and_broken_chains_are_structured_incomplete_results():
    engine = _engine(False)
    missing = engine.explain_requirement("absent")
    assert missing.status is ExplanationStatus.EXPLANATION_INCOMPLETE
    assert missing.failures[0].code == "MISSING_NODE"
    broken = engine.explain_requirement("requirement")
    assert broken.status is ExplanationStatus.EXPLANATION_INCOMPLETE
    assert {failure.code for failure in broken.failures} == {
        "MISSING_ARTIFACT", "MISSING_OCCURRENCE", "MISSING_EXTRACT"}


def test_duplicate_citations_and_snapshot_mismatch_fail_validation():
    engine = _engine()
    explanation = engine.explain_requirement("requirement")
    duplicate = replace(explanation, citations=explanation.citations + (explanation.citations[0],))
    assert {item.code for item in engine.validate_citations(duplicate)} == {"DUPLICATE_CITATION"}
    mismatch = replace(explanation, snapshot_id="other-snapshot")
    assert "SNAPSHOT_MISMATCH" in {item.code for item in engine.validate_snapshot(mismatch)}


def test_cycle_detection_is_structured_and_graph_still_rejects_cycles():
    engine = _engine()
    first = _node("cycle-a", NodeType.REQUIREMENT)
    second = _node("cycle-b", NodeType.CONFLICT)
    forward = _edge(first, second, RelationshipType.HAS_CONFLICT)
    backward = _edge(second, first, RelationshipType.HAS_CONFLICT)
    path = EvidencePath(SNAP, (first, second), (forward, backward))
    assert "CYCLIC_PATH" in {item.code for item in engine.validator.validate_trace(
        path, "cycle-a", NodeType.REQUIREMENT.value)}
    with pytest.raises(EvidenceGraphError, match="cycle"):
        GraphBuilder(SNAP).add_node(first).add_node(second).add_edge(forward).add_edge(backward).build()


def test_engine_and_explanation_are_immutable():
    engine = _engine()
    explanation = engine.explain_requirement("requirement")
    with pytest.raises(AttributeError):
        engine.query = None
    with pytest.raises(FrozenInstanceError):
        explanation.status = ExplanationStatus.EXPLANATION_INCOMPLETE


def test_bank_of_canada_frozen_replay_explains_every_supported_type():
    engine = _bank()
    graph = engine.query.graph
    type_calls = {
        NodeType.REQUIREMENT: engine.explain_requirement,
        NodeType.CONFLICT: engine.explain_conflict,
        NodeType.COMMERCIAL_CLAUSE: engine.explain_commercial_clause,
        NodeType.SUBMISSION_RULE: engine.explain_submission_requirement,
        NodeType.DELIVERABLE: engine.explain_deliverable,
        NodeType.EVALUATION_CRITERION: engine.explain_evaluation_criterion,
        NodeType.EXTRACT: engine.explain_extract,
        NodeType.ARTIFACT: engine.explain_artifact,
    }
    outcomes = {}
    for node_type, call in type_calls.items():
        node = next(node for node in graph.nodes if node.type is node_type)
        outcomes[node_type] = call(node.stable_id)
        assert outcomes[node_type] == call(node.stable_id)
    assert outcomes[NodeType.REQUIREMENT].status is ExplanationStatus.COMPLETE
    assert outcomes[NodeType.COMMERCIAL_CLAUSE].status is ExplanationStatus.COMPLETE
    assert outcomes[NodeType.SUBMISSION_RULE].status is ExplanationStatus.COMPLETE
    assert outcomes[NodeType.DELIVERABLE].status is ExplanationStatus.COMPLETE
    assert outcomes[NodeType.EVALUATION_CRITERION].status is ExplanationStatus.COMPLETE
    assert outcomes[NodeType.EXTRACT].status is ExplanationStatus.COMPLETE
    assert outcomes[NodeType.ARTIFACT].status is ExplanationStatus.COMPLETE
    assert outcomes[NodeType.CONFLICT].status is ExplanationStatus.EXPLANATION_INCOMPLETE
    assert engine.explain_bid_brief_dependency("not-published").status is ExplanationStatus.EXPLANATION_INCOMPLETE
    assert engine.explain_snapshot().status is ExplanationStatus.COMPLETE
    assert engine.explain_graph_statistics().status is ExplanationStatus.COMPLETE
    all_results = {node_type: [call(node.stable_id) for node in graph.nodes
                               if node.type is node_type]
                   for node_type, call in type_calls.items()}
    assert sum(item.status is ExplanationStatus.COMPLETE
               for item in all_results[NodeType.REQUIREMENT]) == 413
    assert sum(item.status is ExplanationStatus.COMPLETE
               for item in all_results[NodeType.DELIVERABLE]) == 28
    assert sum(item.status is ExplanationStatus.EXPLANATION_INCOMPLETE
               for item in all_results[NodeType.DELIVERABLE]) == 2
    assert all(item.status is ExplanationStatus.EXPLANATION_INCOMPLETE
               for item in all_results[NodeType.CONFLICT])
