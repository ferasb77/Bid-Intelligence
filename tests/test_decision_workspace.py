import copy
import json
from dataclasses import replace

import pytest

from decision_analyst import DecisionAnalystMetadata
from decision_intelligence import ContractValidationError
from decision_workspace import (
    DecisionWorkspace,
    build_decision_workspace,
    render_decision_workspace,
)
from opportunity_intelligence import METADATA, _record_id, analyze_opportunity


def _facts():
    return {
        "requirements": [
            {"req_id": f"r-{index}", "category": "Mandatory",
             "evidence_status": "MISSING" if index == 0 else "READY",
             "evidence_id": f"e-{index}"}
            for index in range(20)
        ],
        "evaluation_criteria": [
            {"criterion_id": "criterion-1", "hierarchy_level": 2, "weight": "100%"}
        ],
        "submission_rules": [
            {"artifact_id": "artifact-1", "mandatory": None,
             "submission_channel": "Portal"}
        ],
        "dates": [],
        "deliverables": [],
        "commercial_clauses": [],
        "_canonical_opportunity": {"observations": [], "resolved": {}, "conflicts": []},
    }


def _analysis(context_id="opportunity-1", conflicts=()):
    return analyze_opportunity(_facts(), conflicts, context_id=context_id)


def _missing_evidence_requirement_id():
    # req_id is a document-local Stage A label, not a trusted identity, so
    # opportunity_intelligence._record_id falls through to its deterministic
    # content-and-position hash for "requirements" -- compute the same way
    # production code does rather than hardcoding a stale literal.
    return _record_id("requirements", _facts()["requirements"][0], 0)


def _metadata(analyst_id):
    return DecisionAnalystMetadata(
        analyst_id, analyst_id, "1.0.0", "test",
        METADATA.supported_statement_types, METADATA.supported_evidence_types,
    )


def test_single_analyst_views_preserve_content_exactly():
    analysis = _analysis()
    workspace = build_decision_workspace((analysis,))
    assert isinstance(workspace, DecisionWorkspace)
    assert workspace.computed_facts[0].facts == analysis.computed_facts
    assert workspace.analyst_findings[0].findings == analysis.inferences
    assert workspace.assumptions[0].assumptions == analysis.assumptions
    assert workspace.alternative_interpretations[0].hypotheses == analysis.hypotheses
    assert workspace.management_questions[0].questions == analysis.unanswered_questions
    assert workspace.limitations[0].limitations == analysis.limitations


def test_evidence_overview_organizes_without_evaluating():
    analysis = _analysis()
    overview = build_decision_workspace((analysis,)).evidence_overview
    assert overview.authoritative_evidence == tuple(sorted(
        analysis.evidence_used,
        key=lambda item: (item.entity_type.value, item.entity_id, item.evidence_ids)))
    assert overview.coverage[0].referenced_evidence == len(analysis.evidence_used)
    assert overview.coverage[0].evidence_with_source_ids == 20
    assert overview.coverage[0].unresolved_evidence_gaps == (_missing_evidence_requirement_id(),)
    assert sum(item.count for item in overview.categories) == len(overview.authoritative_evidence)


def test_unknowns_are_grouped_without_loss():
    analysis = _analysis(conflicts=(
        {"conflict_id": "conflict-1", "conflict_type": "DATE_CONFLICT"},))
    group = build_decision_workspace((analysis,)).unknowns[0]
    assert group.missing_evidence == (_missing_evidence_requirement_id(),)
    assert group.unresolved_conflicts == ("conflict-1",)
    assert group.unavailable_information == ()
    assert group.ambiguity == ()


def test_hypotheses_are_all_preserved_and_never_ranked():
    analysis = _analysis()
    hypotheses = build_decision_workspace((analysis,)).alternative_interpretations[0].hypotheses
    assert hypotheses == analysis.hypotheses
    assert len(hypotheses) >= 2
    assert all(not hasattr(item, "rank") for item in hypotheses)


def test_multiple_analysts_are_isolated_and_deterministically_ordered():
    first = _analysis("context-b")
    second = replace(_analysis("context-a"), analyst_id="analyst-z")
    metadata = (METADATA, _metadata("analyst-z"))
    workspace = build_decision_workspace((second, first), analyst_metadata=metadata)
    assert [(item.analyst_id, item.analysis_id) for item in workspace.analysts] == sorted(
        [(first.analyst_id, first.analysis_id), (second.analyst_id, second.analysis_id)])
    grouped = {item.analyst_id: item.findings for item in workspace.analyst_findings}
    assert grouped[first.analyst_id] == first.inferences
    assert grouped[second.analyst_id] == second.inferences


def test_identical_inputs_render_identically():
    analysis = _analysis()
    first = build_decision_workspace((analysis,))
    second = build_decision_workspace((copy.deepcopy(analysis),))
    assert first == second
    assert render_decision_workspace(first) == render_decision_workspace(second)
    assert json.loads(render_decision_workspace(first))["workspace_id"] == first.workspace_id


def test_duplicate_analysis_ids_fail_closed():
    analysis = _analysis()
    with pytest.raises(ContractValidationError, match="duplicate"):
        build_decision_workspace((analysis, analysis))


def test_invalid_analysis_and_missing_evidence_reference_fail_closed():
    with pytest.raises(ContractValidationError, match="DecisionAnalysis"):
        build_decision_workspace((object(),))
    invalid = copy.deepcopy(_analysis())
    object.__setattr__(invalid, "evidence_used", ())
    with pytest.raises(ContractValidationError, match="evidence"):
        build_decision_workspace((invalid,))


def test_unknown_analyst_and_unsupported_version_fail_closed():
    unknown = replace(_analysis(), analyst_id="unknown-analyst")
    with pytest.raises(ContractValidationError, match="unsupported analyst"):
        build_decision_workspace((unknown,))
    with pytest.raises(ContractValidationError, match="unsupported analyst version"):
        build_decision_workspace((_analysis(),), supported_versions={
            METADATA.analyst_id: "2.0.0"})


def test_workspace_rejects_recommendations_and_has_no_decision_or_score_fields():
    analysis = _analysis()
    assert not analysis.recommendations
    workspace = build_decision_workspace((analysis,))
    field_names = set(workspace.__dataclass_fields__)
    assert not field_names & {"recommendations", "decisions", "scores", "rankings"}


def test_workspace_is_not_imported_by_existing_production_pipeline():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    protected = [root / name for name in (
        "extractor.py", "canonical_opportunity.py", "contract_hygiene.py",
        "stage_d_projection.py", "stage_d_checkpoints.py", "database.py",
        "opportunity_intelligence.py",
    )]
    assert all("decision_workspace" not in path.read_text(encoding="utf-8")
               for path in protected)
