from datetime import date

import pytest

from buyer_domain import CanonicalBuyer, GovernmentLevel, Jurisdiction, OrganizationType
from buyer_evidence import (
    AuthenticityStatus, BuyerEvidenceSet, EvidenceAuthority, EvidenceCitation,
    EvidenceDocument, EvidenceExtract, EvidenceFreshness, EvidenceScope,
    EvidenceSource, FreshnessStatus, LocatorType, ScopeType, SourceCategory,
)
from buyer_intelligence import (
    BuyerIntelligenceValidationError, FactClass, FactKind, GovernedBuyerInputs,
    SupportStatus, UnknownKind, analyze_buyer, governed_input_digest,
    validate_buyer_intelligence,
)

BUYER_ID = "buyer:bank-of-canada"
IDENTITY_QUOTE = "The Bank of Canada is Canada's central bank."
UNDER_TEST_QUOTE = "Although we are a Crown corporation, we are independent from government."

# Two independent sources so tests can vary the evidence "under test"
# (authenticity / freshness / authority) without disturbing the separate,
# always-healthy evidence CanonicalBuyer's own identity_ids rely on --
# exactly like two different real documents about the same real buyer.
ANCHOR_SOURCE_ID = "source:bank-of-canada-anchor"
TEST_SOURCE_ID = "source:bank-of-canada-under-test"


def _anchor_source():
    return EvidenceSource(ANCHOR_SOURCE_ID, "Bank of Canada", EvidenceAuthority.OFFICIAL_BUYER,
                          "https://www.bankofcanada.ca")


def _anchor_document():
    freshness = EvidenceFreshness(FreshnessStatus.CURRENT, assessed_on=date(2026, 9, 12))
    return EvidenceDocument(
        document_id="document:anchor", source_id=ANCHOR_SOURCE_ID,
        category=SourceCategory.OFFICIAL_ORGANIZATIONAL_WEBSITE, title="About us - Bank of Canada",
        canonical_url="https://www.bankofcanada.ca/about/", language="en",
        authenticity=AuthenticityStatus.VERIFIED, retrieval_date=date(2026, 9, 12), freshness=freshness,
        scopes=(EvidenceScope(ScopeType.ORGANIZATION, BUYER_ID),),
    )


def _test_document(*, authenticity=AuthenticityStatus.VERIFIED, stale=False):
    freshness = EvidenceFreshness(FreshnessStatus.STALE if stale else FreshnessStatus.CURRENT,
                                  assessed_on=date(2026, 9, 12))
    return EvidenceDocument(
        document_id="document:under-test", source_id=TEST_SOURCE_ID,
        category=SourceCategory.OFFICIAL_ORGANIZATIONAL_WEBSITE, title="About us - Bank of Canada",
        canonical_url="https://www.bankofcanada.ca/about/", language="en",
        authenticity=authenticity, retrieval_date=date(2026, 9, 12), freshness=freshness,
        scopes=(EvidenceScope(ScopeType.ORGANIZATION, BUYER_ID),),
    )


def _evidence(*, authenticity=AuthenticityStatus.VERIFIED, stale=False, authority=EvidenceAuthority.OFFICIAL_BUYER):
    anchor_source, anchor_document = _anchor_source(), _anchor_document()
    test_source = EvidenceSource(TEST_SOURCE_ID, "Bank of Canada", authority, "https://www.bankofcanada.ca")
    test_document = _test_document(authenticity=authenticity, stale=stale)

    anchor_citation = EvidenceCitation("citation:identity", anchor_document.document_id,
                                       LocatorType.SECTION, "About us")
    anchor_extract = EvidenceExtract("extract:identity", anchor_document.document_id,
                                     IDENTITY_QUOTE, (anchor_citation.citation_id,), "en")
    test_citation = EvidenceCitation("citation:under-test", test_document.document_id,
                                     LocatorType.SECTION, "How we're separate from the political process")
    test_extract = EvidenceExtract("extract:under-test", test_document.document_id,
                                   UNDER_TEST_QUOTE, (test_citation.citation_id,), "en")
    return BuyerEvidenceSet(
        "evidence-set:bank-of-canada", BUYER_ID, (anchor_source, test_source),
        (anchor_document, test_document), (anchor_citation, test_citation), (anchor_extract, test_extract))


def _buyer():
    return CanonicalBuyer(
        BUYER_ID, "Bank of Canada", "CA", Jurisdiction("CA", "Canada"),
        GovernmentLevel.FEDERAL, OrganizationType.CENTRAL_BANK, ("extract:identity",),
    )


def _inputs(*, authenticity=AuthenticityStatus.VERIFIED, stale=False,
           authority=EvidenceAuthority.OFFICIAL_BUYER):
    return GovernedBuyerInputs(
        buyer=_buyer(), evidence=_evidence(authenticity=authenticity, stale=stale, authority=authority),
        opportunity_id="opportunity:bank-of-canada-rfp-2026-026-original",
        canonical_opportunity_version="canonical-opportunity/1",
        canonical_opportunity_digest="a" * 64, opportunity_entity_ids=("obs:1",),
        procurement_evidence_ids=("procurement:notice",), procurement_package_digest="b" * 64,
        evaluation_context_id="evaluation:bank-of-canada-buyer-intelligence",
        source_date=date(2026, 9, 12),
    )


def _fact_under_test(result):
    return next(item for item in result.buyer_facts + result.public_organizational_information
               if item.fact_id == "fact:under-test")


def test_analyze_buyer_produces_a_valid_analysis():
    result = analyze_buyer(_inputs())
    assert result.buyer_id == BUYER_ID
    assert result.opportunity_id == "opportunity:bank-of-canada-rfp-2026-026-original"
    # analyze_buyer already calls validate_buyer_intelligence; calling it again
    # independently must also succeed, proving no hidden inconsistency.
    validate_buyer_intelligence(_inputs(), result)


def test_identity_is_never_restated_as_a_buyer_fact():
    # Regression for BUYER_INTELLIGENCE_FACT_OWNERSHIP_ARCHITECTURE.md:
    # Canonical Buyer is the sole owner of legal name, organization type,
    # government level, and jurisdiction. analyze_buyer must never construct
    # a FactKind.IDENTITY BuyerFact restating them, under any evidence
    # condition -- exactly as Opportunity Intelligence never restates
    # Canonical Opportunity's resolved fields.
    for kwargs in ({}, {"stale": True}, {"authenticity": AuthenticityStatus.UNVERIFIED},
                   {"authority": EvidenceAuthority.ATTRIBUTABLE_PUBLIC_SOURCE}):
        result = analyze_buyer(_inputs(**kwargs))
        all_facts = (result.buyer_facts + result.public_organizational_information
                    +result.verified_procurement_context)
        assert not any(item.fact_kind == FactKind.IDENTITY for item in all_facts)
        assert not any("legal name" in item.statement or "organization type" in item.statement
                      for item in all_facts)


def test_identity_fact_kind_is_excluded_from_the_unknowns_scan():
    # Unknowns must represent absence of evidence, never negative inference:
    # IDENTITY is permanently, deliberately never established by this
    # analyst, so its absence is not a real evidence gap and must never be
    # reported as an unknown.
    result = analyze_buyer(_inputs())
    unknown_kinds = {item.unknown_id for item in result.unknowns}
    assert "unknown:missing-identity" not in unknown_kinds


def test_evidence_sourced_fact_statement_is_exactly_verbatim():
    result = analyze_buyer(_inputs())
    fact = _fact_under_test(result)
    assert fact.statement == UNDER_TEST_QUOTE
    assert fact.evidence_ids == ("extract:under-test",)
    assert fact.fact_kind == FactKind.ORGANIZATIONAL_FUNCTION


def test_unverified_document_never_produces_a_fact():
    result = analyze_buyer(_inputs(authenticity=AuthenticityStatus.UNVERIFIED))
    assert not any(item.fact_id == "fact:under-test"
                  for item in result.buyer_facts + result.public_organizational_information)


def test_attributable_public_source_extract_is_skipped_not_forbidden():
    result = analyze_buyer(_inputs(authority=EvidenceAuthority.ATTRIBUTABLE_PUBLIC_SOURCE))
    assert "extract:under-test" not in result.evidence_used
    assert not any(item.fact_id == "fact:under-test"
                  for item in result.buyer_facts + result.public_organizational_information)


def test_stale_evidence_produces_partially_supported_fact():
    result = analyze_buyer(_inputs(stale=True))
    fact = _fact_under_test(result)
    assert fact.evidence_status == SupportStatus.PARTIALLY_SUPPORTED


def test_no_interpretive_content_is_ever_generated():
    result = analyze_buyer(_inputs())
    assert result.interpretations == ()
    assert result.competing_hypotheses == ()
    assert result.assumptions == ()
    assert result.conflicts == ()


def test_verified_procurement_context_is_empty_without_content_specific_link():
    result = analyze_buyer(_inputs())
    assert result.verified_procurement_context == ()


def test_unknowns_cover_every_uncovered_fact_kind_except_identity():
    result = analyze_buyer(_inputs())
    established = {item.fact_kind for item in result.buyer_facts + result.public_organizational_information}
    assert established == {FactKind.ORGANIZATIONAL_FUNCTION}
    unknown_kinds = {FactKind(item.unknown_id.removeprefix("unknown:missing-").upper().replace("-", "_"))
                     for item in result.unknowns}
    assert unknown_kinds == set(FactKind) - established - {FactKind.IDENTITY}
    assert FactKind.IDENTITY not in unknown_kinds
    assert all(item.kind == UnknownKind.MISSING_BUYER_EVIDENCE for item in result.unknowns)


def test_management_question_references_every_unknown():
    result = analyze_buyer(_inputs())
    assert len(result.management_questions) == 1
    question = result.management_questions[0]
    assert question.question.endswith("?")
    assert set(question.unknown_ids) == {item.unknown_id for item in result.unknowns}


def test_evidence_used_is_a_subset_of_governed_evidence_ids():
    inputs = _inputs()
    result = analyze_buyer(inputs)
    assert set(result.evidence_used).issubset(inputs.evidence_ids)
    # Both real, VERIFIED extracts are cited as evidence-sourced facts --
    # extract:identity's own verbatim quote is a legitimate
    # ORGANIZATIONAL_FUNCTION fact in its own right; it is simply never
    # *also* restated as a separate FactKind.IDENTITY fact from
    # CanonicalBuyer's structured fields.
    assert set(result.evidence_used) == {"extract:identity", "extract:under-test"}


def test_input_digest_matches_governed_input_digest():
    inputs = _inputs()
    result = analyze_buyer(inputs)
    assert result.input_digest == governed_input_digest(inputs)


def test_analyze_buyer_is_deterministic():
    first = analyze_buyer(_inputs())
    second = analyze_buyer(_inputs())
    assert first.analysis_id == second.analysis_id
    assert first.to_json() == second.to_json()


def test_analyze_buyer_rejects_non_governed_inputs():
    with pytest.raises(BuyerIntelligenceValidationError):
        analyze_buyer(object())
