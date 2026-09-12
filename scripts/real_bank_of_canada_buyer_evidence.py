"""Real, live-fetched Bank of Canada Buyer Evidence source material.

Retrieved 2026-09-12 via a real browser navigation to
https://www.bankofcanada.ca/about/ and a real page-text extraction. No
fixtures, no fabricated content -- every quote used downstream is copied
verbatim from REAL_PAGE_TEXT below, and buyer_evidence_acquisition.py
independently re-verifies each one against it before accepting it.

Importable by both commission_buyer_evidence.py (the CLI entry point) and
continue_buyer_intelligence.py (which needs the same real objects without
re-running a CLI), so the real source text and quotes exist in exactly one
place.
"""
from datetime import date

from buyer_domain import GovernmentLevel, Jurisdiction, OrganizationType
from buyer_evidence import EvidenceAuthority, EvidenceSource, LocatorType, SourceCategory
from buyer_evidence_acquisition import (
    FetchedExtract, FetchedPage, adapt_buyer_evidence, build_canonical_buyer_identity,
)

REAL_PAGE_TEXT = """About us

Supporting Canada's economy every day by keeping inflation low and stable.

The Bank of Canada is Canada's central bank. In operation since 1935, we play a vital role in promoting our country's economic and financial welfare.

Our history

Initially privately owned to ensure political independence, the Bank became a special federal Crown corporation in 1938.

The Bank of Canada Act has been amended many times since our creation, but the preamble has not changed. We still exist "to regulate credit and currency in the best interests of the economic life of the nation."

What is a central bank?

A central bank promotes economic stability and supports the financial well-being of a country and its citizens. Canada's central bank is the Bank of Canada.

We don't handle personal banking services-you can't open an account with us. We act as "the bank for banks," and we have several areas of responsibility.

What we do

To keep Canada's economy strong and resilient, our work focuses on five key areas:

Monetary policy: We use our monetary policy framework to try and keep inflation low, stable and predictable-and close to the targeted rate.
Financial system: We monitor risks and work to ensure Canada's financial system remains stable and efficient.
Currency: We design, issue and distribute the country's secure, innovative and uniquely Canadian bank notes.
Funds management: We manage the government accounts that hold public debt and foreign reserves.
Regulatory oversight: We oversee Canada's payments and financial market infrastructures to ensure they are safe, resilient and stable. We also support the evolution of the payments ecosystem, including new mandates for stablecoins and consumer-driven banking.

How we're separate from the political process

Although we are a Crown corporation, we are independent from government. This allows us to take a long-term view of Canada's economy.

Independent leadership: Our Governor and Senior Deputy Governor are appointed by an independent Board of Directors. The Bank sets policy independently within an agreed-upon monetary policy framework.
Non-voting government role: The Deputy Minister of Finance participates in Board discussions but cannot vote on any Board decisions.
Financial autonomy: We manage our own budget, approved by our Board of Directors.
"""

BUYER_ID = "buyer:bank-of-canada"
RETRIEVED_ON = date(2026, 9, 12)

_source = EvidenceSource(
    "source:bank-of-canada-official", "Bank of Canada",
    EvidenceAuthority.OFFICIAL_BUYER, "https://www.bankofcanada.ca")

_extracts = (
    FetchedExtract(
        "extract:boc-identity", "citation:boc-identity", LocatorType.SECTION, "About us",
        "The Bank of Canada is Canada's central bank."),
    FetchedExtract(
        "extract:boc-crown-corporation", "citation:boc-crown-corporation", LocatorType.SECTION, "Our history",
        "the Bank became a special federal Crown corporation in 1938."),
    FetchedExtract(
        "extract:boc-mandate", "citation:boc-mandate", LocatorType.SECTION, "Our history",
        "We still exist \"to regulate credit and currency in the best interests of the economic life of the nation.\""),
    FetchedExtract(
        "extract:boc-independence", "citation:boc-independence", LocatorType.SECTION,
        "How we're separate from the political process",
        "Although we are a Crown corporation, we are independent from government."),
)

_page = FetchedPage(
    document_id="document:bank-of-canada-about-us",
    category=SourceCategory.OFFICIAL_ORGANIZATIONAL_WEBSITE,
    title="About us - Bank of Canada",
    url="https://www.bankofcanada.ca/about/",
    language="en",
    retrieval_date=RETRIEVED_ON,
    full_text=REAL_PAGE_TEXT,
    extracts=_extracts,
)


def build_real_buyer_evidence():
    """Return the real, verbatim-verified BuyerEvidenceSet for the Bank of Canada."""
    return adapt_buyer_evidence(
        evidence_set_id="evidence-set:bank-of-canada-2026-09-12",
        buyer_id=BUYER_ID, source=_source, pages=(_page,))


def build_real_canonical_buyer(evidence):
    """Return the real CanonicalBuyer, grounded only in `evidence`'s real entries."""
    return build_canonical_buyer_identity(
        buyer_id=BUYER_ID, legal_name="Bank of Canada", country_code="CA",
        jurisdiction=Jurisdiction("CA", "Canada"), government_level=GovernmentLevel.FEDERAL,
        organization_type=OrganizationType.CENTRAL_BANK, evidence=evidence,
        evidence_ids=("extract:boc-identity", "extract:boc-crown-corporation",
                      "extract:boc-mandate", "extract:boc-independence"),
        public_mandate=("to regulate credit and currency in the best interests of "
                        "the economic life of the nation"),
        official_website="https://www.bankofcanada.ca")
