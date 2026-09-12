from copy import deepcopy
from dataclasses import FrozenInstanceError, fields
from datetime import date
import json

import pytest

from buyer_brief import (
    BUYER_BRIEF_VERSION, SECTION_ORDER, BuyerBrief, build_buyer_brief,
    render_buyer_brief,
)
from buyer_domain import CanonicalBuyer, GovernmentLevel, Jurisdiction, OrganizationType
from buyer_evidence import (
    AuthenticityStatus, BuyerEvidenceSet, EvidenceAuthority, EvidenceCitation,
    EvidenceDocument, EvidenceExtract, EvidenceFreshness, EvidenceScope,
    EvidenceSource, FreshnessStatus, LocatorType, ScopeType, SourceCategory,
)
from buyer_intelligence import (
    BuyerAssumption, BuyerConflict, BuyerFact, BuyerHypothesis,
    BuyerIntelligenceAnalysis, BuyerIntelligenceValidationError,
    BuyerInterpretation, BuyerLimitation, BuyerManagementQuestion, BuyerUnknown,
    Confidence, FactClass, FactKind, GovernedBuyerInputs, InterpretationKind,
    SupportStatus, UnknownKind, governed_input_digest,
)


BUYER_ID = "buyer:bank-of-canada"
OPPORTUNITY_ID = "opportunity:rfp-2030"


def governed_inputs():
    source = EvidenceSource("source:buyer", "Bank of Canada",
                            EvidenceAuthority.OFFICIAL_BUYER,
                            "https://www.bankofcanada.ca/")
    document = EvidenceDocument(
        "document:plan", source.source_id, SourceCategory.STRATEGIC_PLAN,
        "Strategic Plan", "https://www.bankofcanada.ca/plan", "en-CA",
        AuthenticityStatus.VERIFIED, date(2030, 2, 2),
        EvidenceFreshness(FreshnessStatus.CURRENT, date(2030, 2, 2)),
        (EvidenceScope(ScopeType.ORGANIZATION, BUYER_ID),), date(2030, 1, 1),
    )
    citations = (
        EvidenceCitation("citation:mandate", document.document_id,
                         LocatorType.SECTION, "Mandate"),
        EvidenceCitation("citation:priority", document.document_id,
                         LocatorType.SECTION, "Priorities"),
    )
    extracts = (
        EvidenceExtract("extract:mandate", document.document_id,
                        "The Bank has a statutory mandate.",
                        ("citation:mandate",), "en-CA"),
        EvidenceExtract("extract:priority", document.document_id,
                        "The plan identifies modernization.",
                        ("citation:priority",), "en-CA"),
    )
    evidence = BuyerEvidenceSet("evidence-set:buyer", BUYER_ID, (source,),
                                (document,), citations, extracts)
    buyer = CanonicalBuyer(
        BUYER_ID, "Bank of Canada", "CA", Jurisdiction("CA", "Canada"),
        GovernmentLevel.FEDERAL, OrganizationType.CENTRAL_BANK,
        ("extract:mandate",), common_name="Canada's central bank",
        public_mandate="Promote Canada's economic and financial welfare.",
    )
    return GovernedBuyerInputs(
        buyer, evidence, OPPORTUNITY_ID, "canonical-opportunity/1", "a" * 64,
        (OPPORTUNITY_ID, "requirement:services"), ("procurement:notice",),
        "b" * 64, "context:buyer", date(2030, 2, 2),
        "analysis:opportunity", "1.0.0",
    )


def validated_analysis(inputs=None, **changes):
    inputs = inputs or governed_inputs()
    mandate = BuyerFact("fact:mandate", FactClass.AUTHORITATIVE_BUYER_FACT,
                        FactKind.MANDATE, "The Bank has a statutory mandate.",
                        SupportStatus.SUPPORTED, ("extract:mandate",))
    function = BuyerFact("fact:function", FactClass.PUBLIC_ORGANIZATIONAL_INFORMATION,
                         FactKind.ORGANIZATIONAL_FUNCTION,
                         "The plan describes an organizational function.",
                         SupportStatus.SUPPORTED, ("citation:mandate",))
    priority = BuyerFact("fact:priority", FactClass.PUBLIC_ORGANIZATIONAL_INFORMATION,
                         FactKind.PUBLISHED_PRIORITY,
                         "The plan identifies modernization.",
                         SupportStatus.SUPPORTED, ("extract:priority",))
    procurement = BuyerFact("fact:procurement", FactClass.VERIFIED_PROCUREMENT_CONTEXT,
                            FactKind.CURRENT_PROCUREMENT_ROLE,
                            "The notice identifies the Bank as issuer.",
                            SupportStatus.SUPPORTED, ("procurement:notice",))
    function_view = BuyerInterpretation(
        "interpretation:function", InterpretationKind.RELEVANT_ORGANIZATIONAL_FUNCTION,
        "The documented function appears related to the requested services.",
        Confidence.MODERATE, SupportStatus.SUPPORTED, ("citation:mandate",), (),
        ("requirement:services",), (),
    )
    priority_view = BuyerInterpretation(
        "interpretation:priority", InterpretationKind.PUBLISHED_PRIORITY_CONTEXT,
        "The published priority appears related to the opportunity.",
        Confidence.MODERATE, SupportStatus.PARTIALLY_SUPPORTED,
        ("extract:priority",), (), ("requirement:services",),
        ("assumption:applicability",),
    )
    assumption = BuyerAssumption(
        "assumption:applicability", "The published priority remains applicable.",
        "No later plan is present in the supplied evidence.",
        (priority_view.interpretation_id,),
    )
    unknown = BuyerUnknown(
        "unknown:ownership", UnknownKind.AMBIGUOUS_ORGANIZATIONAL_OWNERSHIP,
        "The accountable organizational unit is unknown.",
        "The supplied sources do not name it.", ("citation:mandate",),
    )
    conflict = BuyerConflict("conflict:wording", "Published mandate wording",
                             (("extract:mandate",), ("citation:priority",)))
    hypothesis = BuyerHypothesis(
        "hypothesis:context", "More than one organizational context may apply.",
        Confidence.LOW, SupportStatus.PARTIALLY_SUPPORTED,
        ("citation:mandate",), ("citation:priority",),
        ("requirement:services",),
    )
    values = {
        "analysis_id": "analysis:buyer",
        "buyer_id": BUYER_ID,
        "opportunity_id": OPPORTUNITY_ID,
        "evaluation_context_id": "context:buyer",
        "input_digest": governed_input_digest(inputs),
        "evidence_used": ("extract:mandate", "citation:mandate",
                          "extract:priority", "citation:priority",
                          "procurement:notice"),
        "buyer_facts": (mandate,),
        "public_organizational_information": (function, priority),
        "verified_procurement_context": (procurement,),
        "computed_facts": (),
        "interpretations": (priority_view, function_view),
        "competing_hypotheses": (hypothesis,),
        "assumptions": (assumption,),
        "unknowns": (unknown,),
        "conflicts": (conflict,),
        "management_questions": (BuyerManagementQuestion(
            "question:owner", "Which function owns the work?", (),
            (unknown.unknown_id,), ()),),
        "limitations": (BuyerLimitation(
            "limitation:coverage", "Only the supplied evidence was considered."),),
    }
    values.update(changes)
    return BuyerIntelligenceAnalysis(**values)


def test_section_order_matches_governed_design_and_specification():
    brief = build_buyer_brief(governed_inputs(), validated_analysis())
    assert brief.section_order == SECTION_ORDER
    rendered = render_buyer_brief(brief)
    headings = [f"## {title}" for title in SECTION_ORDER]
    assert [rendered.index(item) for item in headings] == sorted(rendered.index(item) for item in headings)


def test_analysis_objects_are_reused_without_new_reasoning():
    analysis = validated_analysis()
    brief = build_buyer_brief(governed_inputs(), analysis)
    projected = (
        *brief.mandate_and_operating_context.facts,
        *brief.relevant_organizational_context.facts,
        *brief.published_priorities_in_context.facts,
        *brief.current_procurement_context.facts,
    )
    assert set(projected) == set((*analysis.buyer_facts,
                                  *analysis.public_organizational_information,
                                  *analysis.verified_procurement_context))
    assert all(any(item is original for original in analysis.interpretations)
               for item in (*brief.relevant_organizational_context.interpretations,
                            *brief.published_priorities_in_context.interpretations,
                            *brief.opportunity_to_organization_context.interpretations))


def test_facts_interpretations_hypotheses_and_uncertainty_remain_separate():
    analysis = validated_analysis()
    brief = build_buyer_brief(governed_inputs(), analysis)
    assert brief.published_priorities_in_context.facts[0].fact_id == "fact:priority"
    assert brief.published_priorities_in_context.interpretations[0].interpretation_id == "interpretation:priority"
    assert brief.opportunity_to_organization_context.hypotheses == analysis.competing_hypotheses
    assert brief.known_unknowns_and_assumptions.unknowns == analysis.unknowns
    assert brief.known_unknowns_and_assumptions.conflicts == analysis.conflicts
    assert brief.known_unknowns_and_assumptions.assumptions == analysis.assumptions


def test_confidence_is_rendered_only_with_reasoning():
    rendered = render_buyer_brief(build_buyer_brief(governed_inputs(), validated_analysis()))
    fact_line = next(line for line in rendered.splitlines() if "statutory mandate" in line)
    interpretation_line = next(line for line in rendered.splitlines() if "Interpretation (" in line)
    assert "confidence" not in fact_line.casefold()
    assert "Moderate confidence" in interpretation_line
    assert "assumption:applicability" not in rendered
    assert "The published priority remains applicable." in rendered


def test_evidence_register_preserves_metadata_and_stable_markers():
    brief = build_buyer_brief(governed_inputs(), validated_analysis())
    assert tuple(item.marker for item in brief.evidence_register) == ("E1", "E2", "E3", "E4", "E5")
    public = next(item for item in brief.evidence_register if item.evidence_id == "extract:mandate")
    assert public.document.title == "Strategic Plan"
    assert public.source.publisher_name == "Bank of Canada"
    assert public.citation.locator == "Mandate"
    procurement = next(item for item in brief.evidence_register if item.evidence_id == "procurement:notice")
    assert procurement.source_class == "CURRENT_PROCUREMENT_SOURCE"


def test_all_analysis_evidence_appears_in_rendered_register():
    analysis = validated_analysis()
    rendered = render_buyer_brief(build_buyer_brief(governed_inputs(), analysis))
    assert all(evidence_id in rendered for evidence_id in analysis.evidence_used)


def test_empty_sections_remain_visible_without_inventing_content():
    inputs = governed_inputs()
    item = validated_analysis(inputs,
        public_organizational_information=(), interpretations=(),
        competing_hypotheses=(), assumptions=(),
        management_questions=(), conflicts=())
    brief = build_buyer_brief(inputs, item)
    rendered = render_buyer_brief(brief)
    assert "## Published Priorities in Context" in rendered
    assert "No validated published-priority context available." in rendered
    assert "## Questions for the Proposal Kickoff" in rendered


def test_deterministic_identity_rendering_serialization_and_copying():
    inputs = governed_inputs()
    analysis = validated_analysis(inputs)
    first = build_buyer_brief(inputs, analysis)
    second = build_buyer_brief(deepcopy(inputs), deepcopy(analysis))
    assert first == second
    assert first.brief_id == second.brief_id
    assert first.to_json() == second.to_json()
    assert render_buyer_brief(first) == render_buyer_brief(second)
    assert json.loads(first.to_json())["brief_version"] == BUYER_BRIEF_VERSION


def test_brief_is_deeply_immutable():
    brief = build_buyer_brief(governed_inputs(), validated_analysis())
    with pytest.raises(FrozenInstanceError):
        brief.analysis_id = "analysis:other"
    with pytest.raises(TypeError):
        brief.limitations[0] = brief.limitations[0]
    with pytest.raises(FrozenInstanceError):
        brief.limitations[0].statement = "Changed"


def test_invalid_analysis_and_missing_identity_evidence_fail_closed():
    inputs = governed_inputs()
    with pytest.raises(BuyerIntelligenceValidationError, match="digest"):
        build_buyer_brief(inputs, validated_analysis(inputs, input_digest="0" * 64))
    with pytest.raises(BuyerIntelligenceValidationError, match="identity evidence"):
        build_buyer_brief(inputs, validated_analysis(inputs,
            evidence_used=("citation:mandate", "extract:priority", "citation:priority", "procurement:notice"),
            buyer_facts=(), conflicts=()))


def test_required_sections_and_order_fail_closed():
    brief = build_buyer_brief(governed_inputs(), validated_analysis())
    values = {field.name: getattr(brief, field.name) for field in fields(brief)}
    values["section_order"] = tuple(reversed(SECTION_ORDER))
    with pytest.raises(BuyerIntelligenceValidationError, match="section order"):
        BuyerBrief(**values)
    values = brief.to_dict()
    values.pop("limitations")
    with pytest.raises(TypeError):
        BuyerBrief(**values)


def test_buyer_at_a_glance_is_limited_to_six_items():
    inputs = governed_inputs()
    identity = BuyerFact("fact:identity", FactClass.AUTHORITATIVE_BUYER_FACT,
                         FactKind.IDENTITY, "The legal identity is verified.",
                         SupportStatus.SUPPORTED, ("extract:mandate",))
    # The canonical fixture already supplies six populated identity fields.
    with pytest.raises(BuyerIntelligenceValidationError, match="six items"):
        build_buyer_brief(inputs, validated_analysis(inputs, buyer_facts=(identity,)))


def test_inputs_and_analysis_are_not_mutated():
    inputs = governed_inputs()
    analysis = validated_analysis(inputs)
    before = deepcopy((inputs, analysis))
    build_buyer_brief(inputs, analysis)
    assert (inputs, analysis) == before


def test_brief_contract_has_no_decision_recommendation_score_or_ranking():
    names = {item.name for item in fields(BuyerBrief)}
    assert not names & {"decision", "recommendation", "recommendations", "score",
                        "ranking", "bid_no_bid", "win_probability"}
    rendered = render_buyer_brief(build_buyer_brief(governed_inputs(), validated_analysis())).casefold()
    assert "win probability" not in rendered
    assert "bid / no bid" not in rendered


def test_generator_has_no_retrieval_ai_persistence_or_pipeline_dependency():
    import pathlib

    text = (pathlib.Path(__file__).resolve().parents[1] / "buyer_brief.py").read_text(encoding="utf-8").casefold()
    for forbidden in ("requests", "urllib.request", "anthropic", "openai", "supabase", "extractor", "stage_d"):
        assert forbidden not in text
