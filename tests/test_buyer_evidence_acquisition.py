from datetime import date

import pytest

from buyer_domain import GovernmentLevel, Jurisdiction, OrganizationType
from buyer_evidence import EvidenceAuthority, EvidenceSource, LocatorType, SourceCategory
from buyer_evidence_acquisition import (
    BuyerEvidenceAcquisitionError, FetchedExtract, FetchedPage,
    adapt_buyer_evidence, build_canonical_buyer_identity,
)

BUYER_ID = "buyer:bank-of-canada"
REAL_PAGE_TEXT = (
    "About us\n\nThe Bank of Canada is Canada's central bank. In operation since 1935, "
    "we play a vital role in promoting our country's economic and financial welfare.\n\n"
    "Our history\n\nThe Bank became a special federal Crown corporation in 1938.\n\n"
    "Although we are a Crown corporation, we are independent from government."
)


def _source():
    return EvidenceSource("source:bank-of-canada-official", "Bank of Canada",
                          EvidenceAuthority.OFFICIAL_BUYER, "https://www.bankofcanada.ca")


def _page(**extracts_override):
    extracts = extracts_override.get("extracts") or (
        FetchedExtract("extract:identity", "citation:identity", LocatorType.SECTION,
                       "About us", "The Bank of Canada is Canada's central bank."),
    )
    return FetchedPage(
        document_id="document:bank-of-canada-about-us", category=SourceCategory.OFFICIAL_ORGANIZATIONAL_WEBSITE,
        title="About us - Bank of Canada", url="https://www.bankofcanada.ca/about/", language="en",
        retrieval_date=date(2026, 9, 12), full_text=REAL_PAGE_TEXT, extracts=extracts,
    )


def test_adapts_a_real_page_with_a_verbatim_quote_into_governed_evidence():
    evidence = adapt_buyer_evidence(
        evidence_set_id="evidence-set:bank-of-canada-2026-09-12", buyer_id=BUYER_ID,
        source=_source(), pages=(_page(),))
    assert len(evidence.documents) == 1
    assert len(evidence.extracts) == 1
    assert evidence.extracts[0].exact_text == "The Bank of Canada is Canada's central bank."


def test_multiple_extracts_from_the_same_real_page_are_each_independently_verified():
    extracts = (
        FetchedExtract("extract:identity", "citation:identity", LocatorType.SECTION,
                       "About us", "The Bank of Canada is Canada's central bank."),
        FetchedExtract("extract:history", "citation:history", LocatorType.SECTION,
                       "Our history", "The Bank became a special federal Crown corporation in 1938."),
        FetchedExtract("extract:governance", "citation:governance", LocatorType.SECTION,
                       "How we're separate from the political process",
                       "Although we are a Crown corporation, we are independent from government."),
    )
    evidence = adapt_buyer_evidence(
        evidence_set_id="evidence-set:bank-of-canada-2026-09-12", buyer_id=BUYER_ID,
        source=_source(), pages=(_page(extracts=extracts),))
    assert len(evidence.extracts) == 3
    assert len(evidence.citations) == 3


def test_refuses_a_quote_not_present_in_the_real_fetched_text():
    fabricated = (FetchedExtract("extract:fabricated", "citation:fabricated", LocatorType.SECTION,
                                 "About us", "The Bank of Canada was founded by aliens."),)
    with pytest.raises(BuyerEvidenceAcquisitionError, match="not verbatim"):
        adapt_buyer_evidence(evidence_set_id="evidence-set:bank-of-canada-2026-09-12", buyer_id=BUYER_ID,
                             source=_source(), pages=(_page(extracts=fabricated),))


def test_refuses_a_page_with_no_full_text_to_verify_against():
    page = FetchedPage(
        document_id="document:bank-of-canada-about-us", category=SourceCategory.OFFICIAL_ORGANIZATIONAL_WEBSITE,
        title="About us - Bank of Canada", url="https://www.bankofcanada.ca/about/", language="en",
        retrieval_date=date(2026, 9, 12), full_text="",
        extracts=(FetchedExtract("extract:identity", "citation:identity", LocatorType.SECTION,
                                 "About us", "anything"),),
    )
    with pytest.raises(BuyerEvidenceAcquisitionError, match="no real fetched page text"):
        adapt_buyer_evidence(evidence_set_id="evidence-set:x", buyer_id=BUYER_ID, source=_source(), pages=(page,))


def test_refuses_a_page_with_no_extracts():
    page = FetchedPage(
        document_id="document:bank-of-canada-about-us", category=SourceCategory.OFFICIAL_ORGANIZATIONAL_WEBSITE,
        title="About us - Bank of Canada", url="https://www.bankofcanada.ca/about/", language="en",
        retrieval_date=date(2026, 9, 12), full_text=REAL_PAGE_TEXT, extracts=(),
    )
    with pytest.raises(BuyerEvidenceAcquisitionError, match="at least one extract"):
        adapt_buyer_evidence(evidence_set_id="evidence-set:x", buyer_id=BUYER_ID, source=_source(), pages=(page,))


def test_build_canonical_buyer_identity_succeeds_when_evidence_ids_exist():
    evidence = adapt_buyer_evidence(
        evidence_set_id="evidence-set:bank-of-canada-2026-09-12", buyer_id=BUYER_ID,
        source=_source(), pages=(_page(),))
    buyer = build_canonical_buyer_identity(
        buyer_id=BUYER_ID, legal_name="Bank of Canada", country_code="CA",
        jurisdiction=Jurisdiction("CA", "Canada"), government_level=GovernmentLevel.FEDERAL,
        organization_type=OrganizationType.CENTRAL_BANK, evidence=evidence,
        evidence_ids=("extract:identity",), official_website="https://www.bankofcanada.ca")
    assert buyer.buyer_id == BUYER_ID
    assert buyer.evidence_ids == ("extract:identity",)


def test_build_canonical_buyer_identity_refuses_unknown_evidence_ids():
    evidence = adapt_buyer_evidence(
        evidence_set_id="evidence-set:bank-of-canada-2026-09-12", buyer_id=BUYER_ID,
        source=_source(), pages=(_page(),))
    with pytest.raises(BuyerEvidenceAcquisitionError, match="absent from the real evidence set"):
        build_canonical_buyer_identity(
            buyer_id=BUYER_ID, legal_name="Bank of Canada", country_code="CA",
            jurisdiction=Jurisdiction("CA", "Canada"), government_level=GovernmentLevel.FEDERAL,
            organization_type=OrganizationType.CENTRAL_BANK, evidence=evidence,
            evidence_ids=("extract:never-acquired",))


def test_build_canonical_buyer_identity_refuses_mismatched_buyer_id():
    evidence = adapt_buyer_evidence(
        evidence_set_id="evidence-set:bank-of-canada-2026-09-12", buyer_id=BUYER_ID,
        source=_source(), pages=(_page(),))
    with pytest.raises(BuyerEvidenceAcquisitionError, match="does not belong to this buyer_id"):
        build_canonical_buyer_identity(
            buyer_id="buyer:someone-else", legal_name="Someone Else", country_code="CA",
            jurisdiction=Jurisdiction("CA", "Canada"), government_level=GovernmentLevel.FEDERAL,
            organization_type=OrganizationType.CENTRAL_BANK, evidence=evidence,
            evidence_ids=("extract:identity",))
