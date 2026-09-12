from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import date
import json

import pytest

from buyer_domain import CanonicalBuyer, GovernmentLevel, Jurisdiction, OrganizationType
from buyer_evidence import (
    AuthenticityStatus, BuyerEvidenceSet, EvidenceAuthority, EvidenceCitation,
    EvidenceDocument, EvidenceExtract, EvidenceFreshness, EvidenceScope,
    EvidenceSource, FreshnessStatus, LocatorType, ScopeType, SourceCategory,
)
from buyer_intelligence import (
    BUYER_INTELLIGENCE_VERSION, BuyerAssumption, BuyerConflict, BuyerFact,
    BuyerHypothesis, BuyerIntelligenceAnalysis, BuyerIntelligenceValidationError,
    BuyerInterpretation, BuyerLimitation, BuyerManagementQuestion, BuyerUnknown,
    ComputedFact, Confidence, FactClass, FactKind, GovernedBuyerInputs,
    InterpretationKind, SupportStatus, UnknownKind, governed_input_digest,
    validate_buyer_intelligence,
)


BUYER_ID = "buyer:bank-of-canada"
OPPORTUNITY_ID = "opportunity:rfp-2030"


def evidence(*, stale=False, authority=EvidenceAuthority.OFFICIAL_BUYER):
    source = EvidenceSource("source:buyer", "Bank of Canada", authority,
                            "https://www.bankofcanada.ca/")
    freshness = EvidenceFreshness(FreshnessStatus.STALE if stale else FreshnessStatus.CURRENT,
                                  date(2030, 2, 2))
    document = EvidenceDocument(
        "document:plan", source.source_id, SourceCategory.STRATEGIC_PLAN,
        "Strategic Plan", "https://www.bankofcanada.ca/plan", "en-CA",
        AuthenticityStatus.VERIFIED, date(2030, 2, 2), freshness,
        (EvidenceScope(ScopeType.ORGANIZATION, BUYER_ID),), date(2030, 1, 1),
    )
    citation = EvidenceCitation("citation:plan-mandate", document.document_id,
                                LocatorType.SECTION, "Mandate")
    extract = EvidenceExtract("extract:plan-mandate", document.document_id,
                              "The plan identifies a modernization mandate.",
                              (citation.citation_id,), "en-CA")
    return BuyerEvidenceSet("evidence-set:buyer", BUYER_ID, (source,), (document,),
                            (citation,), (extract,))


def inputs(*, stale=False, authority=EvidenceAuthority.OFFICIAL_BUYER, **changes):
    item_evidence = evidence(stale=stale, authority=authority)
    buyer = CanonicalBuyer(
        BUYER_ID, "Bank of Canada", "CA", Jurisdiction("CA", "Canada"),
        GovernmentLevel.FEDERAL, OrganizationType.CENTRAL_BANK,
        ("extract:plan-mandate",),
    )
    values = {
        "buyer": buyer,
        "evidence": item_evidence,
        "opportunity_id": OPPORTUNITY_ID,
        "canonical_opportunity_version": "canonical-opportunity/1",
        "canonical_opportunity_digest": "a" * 64,
        "opportunity_entity_ids": (OPPORTUNITY_ID, "requirement:services"),
        "procurement_evidence_ids": ("procurement:notice",),
        "procurement_package_digest": "b" * 64,
        "evaluation_context_id": "context:buyer-review",
        "source_date": date(2030, 2, 2),
        "opportunity_analysis_id": "analysis:opportunity",
        "opportunity_analysis_version": "1.0.0",
    }
    values.update(changes)
    return GovernedBuyerInputs(**values)


def facts(status=SupportStatus.SUPPORTED):
    buyer_fact = BuyerFact("fact:mandate", FactClass.AUTHORITATIVE_BUYER_FACT,
                           FactKind.MANDATE, "The organization has a published mandate.",
                           status, ("extract:plan-mandate",))
    public_fact = BuyerFact("fact:priority", FactClass.PUBLIC_ORGANIZATIONAL_INFORMATION,
                            FactKind.PUBLISHED_PRIORITY, "The plan identifies modernization.",
                            status, ("citation:plan-mandate",))
    procurement_fact = BuyerFact("fact:procurement-role", FactClass.VERIFIED_PROCUREMENT_CONTEXT,
                                 FactKind.CURRENT_PROCUREMENT_ROLE,
                                 "The notice identifies the issuing organization.", status,
                                 ("procurement:notice",))
    return buyer_fact, public_fact, procurement_fact


def analysis(governed=None, **changes):
    governed = governed or inputs()
    buyer_fact, public_fact, procurement_fact = facts(
        SupportStatus.PARTIALLY_SUPPORTED if governed.evidence.documents[0].freshness.status == FreshnessStatus.STALE
        else SupportStatus.SUPPORTED
    )
    interpretation = BuyerInterpretation(
        "interpretation:mandate", InterpretationKind.OPPORTUNITY_MANDATE_RELATIONSHIP,
        "The opportunity appears related to the published mandate.", Confidence.MODERATE,
        SupportStatus.PARTIALLY_SUPPORTED, ("extract:plan-mandate",), (),
        ("requirement:services",), ("assumption:scope",),
    )
    assumption = BuyerAssumption("assumption:scope", "The stated scope remains applicable.",
                                 "The evidence does not establish current operational ownership.",
                                 (interpretation.interpretation_id,))
    unknown = BuyerUnknown("unknown:ownership", UnknownKind.AMBIGUOUS_ORGANIZATIONAL_OWNERSHIP,
                           "Operational ownership is not established.",
                           "No supplied source names the accountable unit.",
                           ("citation:plan-mandate",))
    values = {
        "analysis_id": "analysis:buyer",
        "buyer_id": BUYER_ID,
        "opportunity_id": OPPORTUNITY_ID,
        "evaluation_context_id": "context:buyer-review",
        "input_digest": governed_input_digest(governed),
        "evidence_used": ("procurement:notice", "citation:plan-mandate", "extract:plan-mandate"),
        "buyer_facts": (buyer_fact,),
        "public_organizational_information": (public_fact,),
        "verified_procurement_context": (procurement_fact,),
        "computed_facts": (ComputedFact("computed:fact-count", "count-source-facts", "3",
                                        (buyer_fact.fact_id, public_fact.fact_id, procurement_fact.fact_id)),),
        "interpretations": (interpretation,),
        "competing_hypotheses": (BuyerHypothesis(
            "hypothesis:organizational-home", "More than one function may be implicated.",
            Confidence.LOW, SupportStatus.PARTIALLY_SUPPORTED,
            ("citation:plan-mandate",), (), ("requirement:services",)),),
        "assumptions": (assumption,),
        "unknowns": (unknown,),
        "conflicts": (),
        "management_questions": (BuyerManagementQuestion(
            "question:ownership", "Which function owns the work?", (), (unknown.unknown_id,), ()),),
        "limitations": (BuyerLimitation("limitation:coverage", "Only supplied official evidence was considered."),),
    }
    values.update(changes)
    return BuyerIntelligenceAnalysis(**values)


def test_complete_analysis_validates_against_governed_inputs():
    governed = inputs()
    result = validate_buyer_intelligence(governed, analysis(governed))
    assert result.analyst_version == BUYER_INTELLIGENCE_VERSION
    assert not hasattr(result, "recommendations")


def test_all_information_classes_remain_separate():
    item = analysis()
    assert item.buyer_facts[0].fact_class == FactClass.AUTHORITATIVE_BUYER_FACT
    assert item.public_organizational_information[0].fact_class == FactClass.PUBLIC_ORGANIZATIONAL_INFORMATION
    assert item.verified_procurement_context[0].fact_class == FactClass.VERIFIED_PROCUREMENT_CONTEXT
    assert not hasattr(item.buyer_facts[0], "confidence")
    assert item.interpretations[0].confidence == Confidence.MODERATE


def test_wrong_fact_class_is_rejected():
    wrong = BuyerFact("fact:wrong", FactClass.PUBLIC_ORGANIZATIONAL_INFORMATION,
                      FactKind.PUBLISHED_PRIORITY, "A public statement.", SupportStatus.SUPPORTED,
                      ("citation:plan-mandate",))
    with pytest.raises(BuyerIntelligenceValidationError, match="wrong fact class"):
        analysis(buyer_facts=(wrong,))


def test_fact_kind_cannot_exceed_its_information_class():
    with pytest.raises(BuyerIntelligenceValidationError, match="exceeds"):
        BuyerFact("fact:wrong", FactClass.VERIFIED_PROCUREMENT_CONTEXT,
                  FactKind.PUBLISHED_PRIORITY, "A priority is published.",
                  SupportStatus.SUPPORTED, ("procurement:notice",))


@pytest.mark.parametrize("status", [SupportStatus.CONFLICTING,
                                     SupportStatus.INSUFFICIENT_EVIDENCE,
                                     SupportStatus.MISSING_EVIDENCE])
def test_facts_cannot_carry_reasoning_or_missing_evidence_states(status):
    with pytest.raises(BuyerIntelligenceValidationError, match="facts must be"):
        BuyerFact("fact:test", FactClass.AUTHORITATIVE_BUYER_FACT, FactKind.IDENTITY,
                  "A fact.", status, ("extract:plan-mandate",))


def test_evidence_traceability_fails_for_unknown_and_undeclared_ids():
    governed = inputs()
    with pytest.raises(BuyerIntelligenceValidationError, match="unresolved evidence"):
        validate_buyer_intelligence(governed,
            analysis(governed, evidence_used=("evidence:missing",)))
    changed = BuyerFact("fact:mandate", FactClass.AUTHORITATIVE_BUYER_FACT, FactKind.MANDATE,
                        "A mandate is stated.", SupportStatus.SUPPORTED,
                        ("citation:plan-mandate",))
    with pytest.raises(BuyerIntelligenceValidationError, match="absent from evidence_used"):
        validate_buyer_intelligence(governed,
            analysis(governed, buyer_facts=(changed,), evidence_used=("extract:plan-mandate", "procurement:notice")))


def test_conclusions_require_exact_citable_evidence():
    governed = inputs()
    source_fact = BuyerFact("fact:mandate", FactClass.AUTHORITATIVE_BUYER_FACT, FactKind.MANDATE,
                            "A mandate is stated.", SupportStatus.SUPPORTED, ("source:buyer",))
    with pytest.raises(BuyerIntelligenceValidationError, match="exact citable"):
        validate_buyer_intelligence(governed,
            analysis(governed, buyer_facts=(source_fact,),
                     evidence_used=("source:buyer", "citation:plan-mandate", "extract:plan-mandate", "procurement:notice")))


def test_identity_and_input_digest_must_match():
    governed = inputs()
    with pytest.raises(BuyerIntelligenceValidationError, match="identity"):
        validate_buyer_intelligence(governed, analysis(governed, buyer_id="buyer:other"))
    with pytest.raises(BuyerIntelligenceValidationError, match="digest"):
        validate_buyer_intelligence(governed, analysis(governed, input_digest="0" * 64))


def test_canonical_buyer_evidence_must_close():
    governed = inputs()
    bad_buyer = CanonicalBuyer(BUYER_ID, "Bank of Canada", "CA", Jurisdiction("CA", "Canada"),
                               GovernmentLevel.FEDERAL, OrganizationType.CENTRAL_BANK,
                               ("evidence:outside",))
    governed = inputs(buyer=bad_buyer)
    with pytest.raises(BuyerIntelligenceValidationError, match="outside Buyer Evidence"):
        validate_buyer_intelligence(governed, analysis(governed))


def test_secondary_sources_are_not_permitted_in_version_one():
    governed = inputs(authority=EvidenceAuthority.ATTRIBUTABLE_PUBLIC_SOURCE)
    with pytest.raises(BuyerIntelligenceValidationError, match="secondary"):
        validate_buyer_intelligence(governed, analysis(governed))


def test_fact_source_authority_is_proposition_specific():
    governed = inputs()
    mandate_from_notice = BuyerFact("fact:mandate", FactClass.AUTHORITATIVE_BUYER_FACT,
                                    FactKind.MANDATE, "A mandate is stated.",
                                    SupportStatus.SUPPORTED, ("procurement:notice",))
    with pytest.raises(BuyerIntelligenceValidationError, match="exceed"):
        validate_buyer_intelligence(governed, analysis(governed, buyer_facts=(mandate_from_notice,)))
    priority_from_notice = BuyerFact("fact:priority", FactClass.PUBLIC_ORGANIZATIONAL_INFORMATION,
                                    FactKind.PUBLISHED_PRIORITY, "A priority is stated.",
                                    SupportStatus.SUPPORTED, ("procurement:notice",))
    with pytest.raises(BuyerIntelligenceValidationError, match="organizational evidence"):
        validate_buyer_intelligence(governed,
            analysis(governed, public_organizational_information=(priority_from_notice,)))
    role_from_plan = BuyerFact("fact:procurement-role", FactClass.VERIFIED_PROCUREMENT_CONTEXT,
                               FactKind.CURRENT_PROCUREMENT_ROLE, "A procurement role is stated.",
                               SupportStatus.SUPPORTED, ("extract:plan-mandate",))
    with pytest.raises(BuyerIntelligenceValidationError, match="procurement evidence"):
        validate_buyer_intelligence(governed,
            analysis(governed, verified_procurement_context=(role_from_plan,)))


def test_stale_fact_must_be_qualified():
    governed = inputs(stale=True)
    unqualified = BuyerFact("fact:mandate", FactClass.AUTHORITATIVE_BUYER_FACT, FactKind.MANDATE,
                            "A mandate is stated.", SupportStatus.SUPPORTED,
                            ("extract:plan-mandate",))
    with pytest.raises(BuyerIntelligenceValidationError, match="stale"):
        validate_buyer_intelligence(governed, analysis(governed, buyer_facts=(unqualified,)))
    assert validate_buyer_intelligence(governed, analysis(governed)).buyer_facts[0].evidence_status == SupportStatus.PARTIALLY_SUPPORTED


def test_assumption_links_are_visible_and_reciprocal():
    governed = inputs()
    hidden = BuyerInterpretation(
        "interpretation:mandate", InterpretationKind.OPPORTUNITY_MANDATE_RELATIONSHIP,
        "The opportunity appears related to the mandate.", Confidence.LOW,
        SupportStatus.PARTIALLY_SUPPORTED, ("extract:plan-mandate",), (),
        ("requirement:services",), (),
    )
    with pytest.raises(BuyerIntelligenceValidationError, match="reciprocal"):
        validate_buyer_intelligence(governed, analysis(governed, interpretations=(hidden,)))
    with pytest.raises(BuyerIntelligenceValidationError, match="cannot be fully supported"):
        BuyerInterpretation("interpretation:test", InterpretationKind.ORGANIZATIONAL_CONTEXT,
                            "The context appears relevant.", Confidence.HIGH, SupportStatus.SUPPORTED,
                            ("extract:plan-mandate",), (), (OPPORTUNITY_ID,), ("assumption:test",))


def test_unknowns_explain_why_they_remain_unknown():
    with pytest.raises(BuyerIntelligenceValidationError, match="unresolved_reason"):
        BuyerUnknown("unknown:test", UnknownKind.MISSING_BUYER_EVIDENCE,
                     "Ownership is unknown.", "")


def test_management_questions_are_unanswered_and_traceable():
    with pytest.raises(BuyerIntelligenceValidationError, match="end with"):
        BuyerManagementQuestion("question:test", "Confirm the owner.", ("citation:plan-mandate",))
    with pytest.raises(BuyerIntelligenceValidationError, match="reference evidence"):
        BuyerManagementQuestion("question:test", "Who owns the work?")
    governed = inputs()
    bad = BuyerManagementQuestion("question:test", "Who owns the work?", (), ("unknown:missing",))
    with pytest.raises(BuyerIntelligenceValidationError, match="unknown uncertainty"):
        validate_buyer_intelligence(governed, analysis(governed, management_questions=(bad,)))


@pytest.mark.parametrize("text", [
    "We recommend a proposal strategy?",
    "Should bid on this opportunity?",
    "What pricing strategy should we use?",
    "Is this bidder the likely winner?",
])
def test_recommendations_predictions_and_strategy_are_rejected(text):
    with pytest.raises(BuyerIntelligenceValidationError, match="prohibited"):
        BuyerManagementQuestion("question:unsafe", text, ("citation:plan-mandate",))


def test_conflicting_reasoning_preserves_opposing_evidence():
    with pytest.raises(BuyerIntelligenceValidationError, match="contradicting"):
        BuyerInterpretation("interpretation:conflict", InterpretationKind.ORGANIZATIONAL_CONTEXT,
                            "The sources present conflicting context.", Confidence.LOW,
                            SupportStatus.CONFLICTING, ("extract:plan-mandate",), (),
                            (OPPORTUNITY_ID,))
    with pytest.raises(BuyerIntelligenceValidationError, match="two distinct"):
        BuyerConflict("conflict:test", "Mandate wording", (("citation:plan-mandate",),))


def test_conflicts_and_missing_evidence_cannot_be_hidden():
    governed = inputs()
    conflicting = BuyerHypothesis("hypothesis:conflict", "Two contexts may apply.", Confidence.LOW,
                                  SupportStatus.CONFLICTING, ("extract:plan-mandate",),
                                  ("citation:plan-mandate",), (OPPORTUNITY_ID,))
    with pytest.raises(BuyerIntelligenceValidationError, match="matching explicit conflict"):
        validate_buyer_intelligence(governed, analysis(governed, competing_hypotheses=(conflicting,), conflicts=()))
    with pytest.raises(BuyerIntelligenceValidationError, match="represented as an unknown"):
        BuyerHypothesis("hypothesis:unsupported", "Ownership might exist.", Confidence.UNKNOWN,
                        SupportStatus.MISSING_EVIDENCE, ("extract:plan-mandate",), (),
                        (OPPORTUNITY_ID,))


def test_unknown_opportunity_and_computed_fact_references_fail_closed():
    governed = inputs()
    bad_interpretation = BuyerInterpretation(
        "interpretation:bad", InterpretationKind.ORGANIZATIONAL_CONTEXT,
        "The context appears related.", Confidence.LOW, SupportStatus.PARTIALLY_SUPPORTED,
        ("extract:plan-mandate",), (), ("requirement:missing",), (),
    )
    with pytest.raises(BuyerIntelligenceValidationError, match="Canonical Opportunity"):
        validate_buyer_intelligence(governed,
            analysis(governed, interpretations=(bad_interpretation,), assumptions=()))
    with pytest.raises(BuyerIntelligenceValidationError, match="unknown fact"):
        validate_buyer_intelligence(governed,
            analysis(governed, computed_facts=(ComputedFact("computed:test", "count", "1", ("fact:missing",)),)))


def test_required_sections_and_supported_versions_fail_closed():
    item = analysis()
    data = item.to_dict()
    data.pop("limitations")
    with pytest.raises(TypeError):
        BuyerIntelligenceAnalysis(**data)
    with pytest.raises(BuyerIntelligenceValidationError, match="unsupported Buyer Intelligence"):
        analysis(analyst_version="buyer-intelligence/2")
    with pytest.raises(BuyerIntelligenceValidationError, match="Opportunity Intelligence version"):
        inputs(opportunity_analysis_version="2.0.0")


def test_ordering_equality_serialization_and_copying_are_deterministic():
    governed = inputs()
    first = analysis(governed, limitations=(BuyerLimitation("limitation:z", "Z."),
                                            BuyerLimitation("limitation:a", "A.")))
    second = analysis(governed, limitations=tuple(reversed(first.limitations)),
                      evidence_used=tuple(reversed(first.evidence_used)))
    assert first == second
    assert first.to_json() == second.to_json()
    assert json.loads(first.to_json())["analyst_version"] == BUYER_INTELLIGENCE_VERSION
    assert deepcopy(first) == first


def test_contracts_are_deeply_immutable():
    item = analysis()
    with pytest.raises(FrozenInstanceError):
        item.buyer_id = "buyer:other"
    with pytest.raises(TypeError):
        item.buyer_facts[0] = item.buyer_facts[0]
    with pytest.raises(FrozenInstanceError):
        item.interpretations[0].statement = "Changed"


def test_governed_inputs_are_not_mutated_by_validation():
    governed = inputs()
    before = governed_input_digest(governed)
    validate_buyer_intelligence(governed, analysis(governed))
    assert governed_input_digest(governed) == before


def test_module_has_no_retrieval_presentation_model_or_pipeline_dependency():
    import pathlib

    text = (pathlib.Path(__file__).resolve().parents[1] / "buyer_intelligence.py").read_text(encoding="utf-8").casefold()
    for forbidden in ("requests", "urllib.request", "anthropic", "openai", "buyer_brief", "extractor", "stage_d"):
        assert forbidden not in text
