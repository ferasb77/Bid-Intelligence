from datetime import date

import pytest

from buyer_domain import CanonicalBuyer, GovernmentLevel, Jurisdiction, OrganizationType
from buyer_evidence import (
    AuthenticityStatus, BuyerEvidenceSet, EvidenceAuthority, EvidenceCitation,
    EvidenceDocument, EvidenceExtract, EvidenceFreshness, EvidenceScope,
    EvidenceSource, FreshnessStatus, LocatorType, ScopeType, SourceCategory,
)
from buyer_evidence_publication import publish_buyer_evidence
from canonical_buyer_publication import (
    IDENTITY_CLASS, CanonicalBuyerPublicationError, CanonicalBuyerPublicationFailureCode,
    publish_canonical_buyer, validate_canonical_buyer_publication,
)

BUYER_ID = "buyer:bank-of-canada"


def _evidence():
    source = EvidenceSource("source:bank-of-canada", "Bank of Canada",
                            EvidenceAuthority.OFFICIAL_BUYER, "https://www.bankofcanada.ca")
    freshness = EvidenceFreshness(FreshnessStatus.CURRENT, assessed_on=date(2026, 9, 12))
    document = EvidenceDocument(
        "document:about-us", source.source_id, SourceCategory.OFFICIAL_ORGANIZATIONAL_WEBSITE,
        "About us", "https://www.bankofcanada.ca/about/", "en", AuthenticityStatus.VERIFIED,
        date(2026, 9, 12), freshness, (EvidenceScope(ScopeType.ORGANIZATION, BUYER_ID),))
    citation = EvidenceCitation("citation:identity", document.document_id, LocatorType.SECTION, "About us")
    extract = EvidenceExtract("extract:identity", document.document_id,
                              "The Bank of Canada is Canada's central bank.", (citation.citation_id,), "en")
    return BuyerEvidenceSet("evidence-set:bank-of-canada", BUYER_ID, (source,), (document,),
                            (citation,), (extract,))


def _buyer(evidence_ids=("extract:identity",)):
    return CanonicalBuyer(
        BUYER_ID, "Bank of Canada", "CA", Jurisdiction("CA", "Canada"),
        GovernmentLevel.FEDERAL, OrganizationType.CENTRAL_BANK, evidence_ids,
    )


def test_publishes_exactly_one_identity_object_bound_to_real_evidence():
    evidence_pub = publish_buyer_evidence(_evidence())
    publication = publish_canonical_buyer(_buyer(), evidence_publication=evidence_pub)
    assert len(publication.snapshot.objects) == 1
    identity = publication.snapshot.objects[0]
    assert identity.object_class == IDENTITY_CLASS
    assert identity.object_id == BUYER_ID
    assert len(identity.relationships) == 1


def test_publication_is_deterministic():
    evidence_pub = publish_buyer_evidence(_evidence())
    buyer = _buyer()
    first = publish_canonical_buyer(buyer, evidence_publication=evidence_pub)
    second = publish_canonical_buyer(buyer, evidence_publication=evidence_pub)
    assert first.digest == second.digest
    validate_canonical_buyer_publication(first)


def test_refuses_an_evidence_id_buyer_evidence_publication_cannot_resolve():
    evidence_pub = publish_buyer_evidence(_evidence())
    buyer = _buyer(evidence_ids=("extract:never-acquired",))
    with pytest.raises(CanonicalBuyerPublicationError) as excinfo:
        publish_canonical_buyer(buyer, evidence_publication=evidence_pub)
    assert excinfo.value.code == CanonicalBuyerPublicationFailureCode.MISSING_RELATIONSHIP_BINDING


def test_refuses_an_evidence_publication_for_a_different_buyer():
    evidence_pub = publish_buyer_evidence(_evidence())
    other_buyer = CanonicalBuyer(
        "buyer:someone-else", "Someone Else", "CA", Jurisdiction("CA", "Canada"),
        GovernmentLevel.FEDERAL, OrganizationType.PUBLIC_AGENCY, ("extract:identity",),
    )
    with pytest.raises(CanonicalBuyerPublicationError):
        publish_canonical_buyer(other_buyer, evidence_publication=evidence_pub)


def test_reference_for_identity_resolves_to_the_published_object():
    evidence_pub = publish_buyer_evidence(_evidence())
    publication = publish_canonical_buyer(_buyer(), evidence_publication=evidence_pub)
    reference = publication.reference_for_identity()
    assert reference.object_id == BUYER_ID
    assert reference.object_class == IDENTITY_CLASS
