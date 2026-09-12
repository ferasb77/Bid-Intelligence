from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timezone

import pytest

from decision_analyst import (
    AnalystReasoning, AnalystUnknowns, DecisionAnalysis, ManagementQuestion,
    SupportStatus,
)
from decision_intelligence import (
    Confidence, ContractValidationError, DecisionStatement, EvidenceSupport,
    ReasoningStatus, SourceType, StatementSource, StatementType,
    SupportedEntityType,
)
from executive_opportunity_brief import (
    BRIEF_VERSION, ExecutiveOpportunityBrief, build_executive_opportunity_brief,
    render_executive_opportunity_brief,
)
from executive_opportunity_understanding import (
    ExecutiveUnderstandingInput, SECTION_ORDER,
    build_executive_opportunity_understanding,
)
from governed_reference_resolution import (
    AuthorityClass, SemanticField, SemanticValue, SemanticValueKind,
    create_governed_object, create_governed_snapshot, create_resolution_context,
    reference_to,
)
from opportunity_intelligence import ANALYST_VERSION
from opportunity_intelligence_publication import (
    OpportunitySupportBinding, publish_opportunity_intelligence,
)


def _understanding():
    fact = create_governed_object(
        owner_domain="canonical-opportunity", owner_contract="canonical-opportunity",
        contract_version="1.0.0", object_class="canonical-fact",
        object_id="canonical-1", authority=AuthorityClass.CANONICAL_FACT,
        semantic_fields=(SemanticField(
            "value", SemanticValue(SemanticValueKind.STRING, "Known fact")),),
    )
    evidence = create_governed_object(
        owner_domain="canonical-opportunity", owner_contract="canonical-opportunity",
        contract_version="1.0.0", object_class="evidence", object_id="evidence-1",
        authority=AuthorityClass.EVIDENCE,
        semantic_fields=(SemanticField(
            "locator", SemanticValue(SemanticValueKind.STRING, "page 1")),),
    )
    snapshot = create_governed_snapshot(
        owner_domain="canonical-opportunity", owner_contract="canonical-opportunity",
        contract_version="1.0.0", snapshot_id="canonical-snapshot-1",
        objects=(fact, evidence),
    )
    context = create_resolution_context(
        context_id="authoritative-context-1", context_version="1.0.0",
        snapshots=(snapshot,),
    )
    support = EvidenceSupport(
        SupportedEntityType.CANONICAL_FACT, "canonical-1", ("evidence-1",))
    binding = OpportunitySupportBinding(
        support, reference_to(snapshot, "canonical-fact", "canonical-1"),
        (reference_to(snapshot, "evidence", "evidence-1"),),
    )
    computed = DecisionStatement(
        "computed-1", StatementType.COMPUTED_FACT, "requirement_count=4",
        StatementSource(SourceType.DETERMINISTIC_COMPUTATION, "test/count"),
        None, ReasoningStatus.VALIDATED, support.evidence_ids,
        (support.entity_id,), (support,),
    )
    inference = DecisionStatement(
        "inference-1", StatementType.AI_INFERENCE,
        "The documented structure contains an effort consideration.",
        StatementSource(SourceType.SPECIALIST_ANALYST, "opportunity-intelligence"),
        Confidence.MODERATE, ReasoningStatus.PROPOSED, support.evidence_ids,
        (computed.statement_id,), (support,),
    )
    analysis = DecisionAnalysis(
        "analysis-1", "opportunity-intelligence",
        datetime(2030, 1, 1, 12, tzinfo=timezone.utc), Confidence.MODERATE,
        (support,), (computed,),
        (AnalystReasoning(inference, SupportStatus.PARTIALLY_SUPPORTED),),
        (), (), ("Analysis is limited to supplied evidence.",), (),
        (ManagementQuestion("question-1", "What requires human judgment?",
                            (inference.statement_id,)),),
        AnalystUnknowns(ambiguous_observation_ids=(support.entity_id,)),
    )
    publication = publish_opportunity_intelligence(
        analysis, analyst_version=ANALYST_VERSION,
        authoritative_context=context, support_bindings=(binding,),
    )
    return build_executive_opportunity_understanding(
        ExecutiveUnderstandingInput("opportunity-1", publication))


def test_accepts_only_validated_executive_opportunity_understanding():
    understanding = _understanding()
    brief = build_executive_opportunity_brief(understanding)
    assert isinstance(brief, ExecutiveOpportunityBrief)
    assert brief.brief_version == BRIEF_VERSION
    with pytest.raises(ContractValidationError, match="ExecutiveOpportunityUnderstanding"):
        build_executive_opportunity_brief({})


def test_preserves_index_detail_coverage_and_identity_bindings():
    understanding = _understanding()
    brief = build_executive_opportunity_brief(understanding)
    assert tuple(item.section for item in brief.sections) == SECTION_ORDER
    assert tuple(item.object_ids for item in brief.sections) == tuple(
        item.object_ids for item in understanding.executive_index)
    assert brief.detail_register == understanding.detail_register.references()
    assert brief.coverage_ledger == understanding.coverage_ledger
    assert brief.publication_id == understanding.publication_id
    assert brief.publication_snapshot_id == understanding.publication_snapshot_id
    assert brief.publication_snapshot_digest == understanding.publication_snapshot_digest


def test_rendering_uses_resolved_owner_values_and_preserves_provenance():
    brief = build_executive_opportunity_brief(_understanding())
    rendered = render_executive_opportunity_brief(brief)
    assert "requirement_count=4" in rendered
    assert "The documented structure contains an effort consideration." in rendered
    assert "canonical-opportunity/canonical-opportunity/1.0.0/evidence/evidence-1" in rendered
    assert "EVIDENCE_SUPPORT" in rendered
    assert brief.publication_snapshot_id in rendered


def test_rendering_fails_closed_for_a_stale_bound_context():
    brief = build_executive_opportunity_brief(_understanding())
    with pytest.raises(ContractValidationError):
        replace(brief.understanding, context_digest="0" * 64)


def test_identical_understanding_produces_identical_brief_and_bytes():
    understanding = _understanding()
    first = build_executive_opportunity_brief(understanding)
    second = build_executive_opportunity_brief(understanding)
    assert first == second
    assert first.to_json() == second.to_json()
    assert render_executive_opportunity_brief(first) == render_executive_opportunity_brief(second)


def test_brief_is_immutable_and_contains_no_semantic_value_or_upstream_fields():
    brief = build_executive_opportunity_brief(_understanding())
    with pytest.raises(FrozenInstanceError):
        brief.brief_id = "changed"
    names = {item.name for item in fields(brief)}
    assert not names & {
        "analysis", "decision_analysis", "normalized_facts", "stage_d",
        "synthesis", "semantic_values", "recommendations", "score", "decision",
    }
    assert "understanding" not in brief.to_dict()
    assert "semantic_fields" not in brief.to_json()


def test_section_order_is_executive_index_order_and_repeated_values_render_once():
    brief = build_executive_opportunity_brief(_understanding())
    rendered = render_executive_opportunity_brief(brief)
    headings = [f"## {item.heading}" for item in brief.sections]
    assert [rendered.index(value) for value in headings] == sorted(
        rendered.index(value) for value in headings)
    assert rendered.count("The documented structure contains an effort consideration.") == 1


def test_every_detail_object_has_exactly_one_coverage_record_and_is_presented():
    brief = build_executive_opportunity_brief(_understanding())
    detail_ids = tuple(item.object_id for item in brief.detail_register)
    coverage_ids = tuple(item.object_id for item in brief.coverage_ledger)
    assert set(detail_ids) == set(coverage_ids)
    assert len(coverage_ids) == len(set(coverage_ids))
    rendered = render_executive_opportunity_brief(brief)
    assert all(object_id in rendered for object_id in detail_ids)


def test_legacy_multi_input_construction_path_is_removed():
    with pytest.raises(TypeError):
        build_executive_opportunity_brief({}, {}, object())
