"""Deterministic adapter turning already-fetched, real public organizational
source material into governed Buyer Evidence and Canonical Buyer identity
objects.

This module performs no retrieval itself -- fetching real content from real
public sources is the caller's responsibility (an interactive research
session today; a future automated Buyer Retrieval implementation per
BUYER_RETRIEVAL_ARCHITECTURE.md eventually) -- and it invents no fact or
quote: every extract is independently verified to appear verbatim in the
exact page text the caller supplies for that same page, mirroring
canonical_opportunity.py's own excerpt-verification discipline for
procurement evidence. A quote that cannot be found in the real fetched text
is refused, not softened or approximated.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from buyer_domain import (
    BuyerValidationError, CanonicalBuyer, GovernmentLevel, Jurisdiction,
    OrganizationType,
)
from buyer_evidence import (
    AuthenticityStatus, BuyerEvidenceSet, EvidenceCitation, EvidenceDocument,
    EvidenceExtract, EvidenceFreshness, EvidenceScope, EvidenceSource,
    EvidenceValidationError, FreshnessStatus, LocatorType, ScopeType,
    SourceCategory,
)


class BuyerEvidenceAcquisitionError(ValueError):
    """A real fetched page could not be turned into governed Buyer Evidence without inventing content."""


def _normalize_text(value: str) -> str:
    return " ".join(str(value).split())


@dataclass(frozen=True, slots=True)
class FetchedExtract:
    """One verbatim quote taken from a single real fetched page."""
    extract_id: str
    citation_id: str
    locator_type: LocatorType
    locator: str
    quote: str


@dataclass(frozen=True, slots=True)
class FetchedPage:
    """One real page as actually retrieved, including its full extracted
    text -- required so every claimed quote can be verified against it.
    """
    document_id: str
    category: SourceCategory
    title: str
    url: str
    language: str
    retrieval_date: date
    full_text: str
    extracts: tuple[FetchedExtract, ...]


def adapt_buyer_evidence(
        *, evidence_set_id: str, buyer_id: str, source: EvidenceSource,
        pages: Sequence[FetchedPage],
        ) -> BuyerEvidenceSet:
    """Build one BuyerEvidenceSet from real, already-fetched pages.

    Every extract's quote is checked against the same page's real fetched
    full_text before being accepted. Nothing here reaches the network or
    reads a file; pages must already carry real, retrieved content.
    """
    if not pages:
        raise BuyerEvidenceAcquisitionError("at least one real fetched page is required")
    documents = []
    citations = []
    extracts = []
    for page in pages:
        if not page.full_text or not page.full_text.strip():
            raise BuyerEvidenceAcquisitionError(
                f"{page.document_id}: no real fetched page text was supplied to verify extracts against")
        if not page.extracts:
            raise BuyerEvidenceAcquisitionError(
                f"{page.document_id}: a fetched page requires at least one extract")
        normalized_page = _normalize_text(page.full_text)
        try:
            documents.append(EvidenceDocument(
                document_id=page.document_id, source_id=source.source_id, category=page.category,
                title=page.title, canonical_url=page.url, language=page.language,
                authenticity=AuthenticityStatus.VERIFIED, retrieval_date=page.retrieval_date,
                freshness=EvidenceFreshness(FreshnessStatus.CURRENT, assessed_on=page.retrieval_date),
                scopes=(EvidenceScope(ScopeType.ORGANIZATION, buyer_id),),
            ))
        except EvidenceValidationError as exc:
            raise BuyerEvidenceAcquisitionError(f"{page.document_id}: {exc}") from exc
        for item in page.extracts:
            normalized_quote = _normalize_text(item.quote)
            if not normalized_quote or normalized_quote not in normalized_page:
                raise BuyerEvidenceAcquisitionError(
                    f"{item.extract_id}: quote is not verbatim in the real fetched text of "
                    f"{page.document_id}; refusing to fabricate buyer evidence")
            try:
                citations.append(EvidenceCitation(
                    item.citation_id, page.document_id, item.locator_type, item.locator))
                extracts.append(EvidenceExtract(
                    item.extract_id, page.document_id, item.quote, (item.citation_id,), page.language))
            except EvidenceValidationError as exc:
                raise BuyerEvidenceAcquisitionError(f"{item.extract_id}: {exc}") from exc
    try:
        return BuyerEvidenceSet(
            evidence_set_id, buyer_id, (source,), tuple(documents), tuple(citations), tuple(extracts))
    except EvidenceValidationError as exc:
        raise BuyerEvidenceAcquisitionError(str(exc)) from exc


def build_canonical_buyer_identity(
        *, buyer_id: str, legal_name: str, country_code: str, jurisdiction: Jurisdiction,
        government_level: GovernmentLevel, organization_type: OrganizationType,
        evidence: BuyerEvidenceSet, evidence_ids: Sequence[str],
        public_mandate: str | None = None, official_website: str | None = None,
        ) -> CanonicalBuyer:
    """Build one CanonicalBuyer whose evidence_ids are verified to already
    exist in `evidence` -- an identity claim may not point at evidence that
    was never actually acquired.
    """
    if evidence.buyer_id != buyer_id:
        raise BuyerEvidenceAcquisitionError("evidence set does not belong to this buyer_id")
    known_ids = ({item.extract_id for item in evidence.extracts}
                 | {item.citation_id for item in evidence.citations}
                 | {item.document_id for item in evidence.documents}
                 | {item.source_id for item in evidence.sources})
    unknown = sorted(set(evidence_ids) - known_ids)
    if unknown:
        raise BuyerEvidenceAcquisitionError(
            f"evidence_ids reference entries absent from the real evidence set: {unknown}")
    try:
        return CanonicalBuyer(
            buyer_id=buyer_id, legal_name=legal_name, country_code=country_code,
            jurisdiction=jurisdiction, government_level=government_level,
            organization_type=organization_type, evidence_ids=tuple(evidence_ids),
            public_mandate=public_mandate, official_website=official_website,
        )
    except BuyerValidationError as exc:
        raise BuyerEvidenceAcquisitionError(str(exc)) from exc


__all__ = [
    "BuyerEvidenceAcquisitionError", "FetchedExtract", "FetchedPage",
    "adapt_buyer_evidence", "build_canonical_buyer_identity",
]
