from datetime import date

import pytest

from buyer_evidence import (
    AuthenticityStatus, BuyerEvidenceSet, EvidenceAuthority, EvidenceCitation,
    EvidenceDocument, EvidenceExtract, EvidenceFreshness, EvidenceScope,
    EvidenceSource, FreshnessStatus, LocatorType, ScopeType, SourceCategory,
)
from buyer_evidence_publication import (
    CITATION_CLASS, DOCUMENT_CLASS, EXTRACT_CLASS, SOURCE_CLASS,
    BuyerEvidencePublicationError, publish_buyer_evidence,
    validate_buyer_evidence_publication,
)
from governed_reference_resolution import RelationshipKind

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


def test_publishes_one_object_per_evidence_item():
    publication = publish_buyer_evidence(_evidence())
    classes = {item.object_class for item in publication.snapshot.objects}
    assert classes == {SOURCE_CLASS, DOCUMENT_CLASS, CITATION_CLASS, EXTRACT_CLASS}
    assert len(publication.snapshot.objects) == 4
    assert len(publication.references) == 4


def test_relationships_are_derived_from_the_real_foreign_keys():
    publication = publish_buyer_evidence(_evidence())
    extract_object = next(item for item in publication.snapshot.objects if item.object_class == EXTRACT_CLASS)
    kinds = {relationship.kind for relationship in extract_object.relationships}
    assert RelationshipKind.EVIDENCE_SUPPORT in kinds
    assert RelationshipKind.PROVENANCE in kinds
    document_object = next(item for item in publication.snapshot.objects if item.object_class == DOCUMENT_CLASS)
    assert document_object.relationships[0].kind == RelationshipKind.PROVENANCE


def test_publication_is_deterministic():
    evidence = _evidence()
    first = publish_buyer_evidence(evidence)
    second = publish_buyer_evidence(evidence)
    assert first.digest == second.digest
    assert first.publication_id == second.publication_id
    validate_buyer_evidence_publication(first)


def test_publication_does_not_mutate_its_source():
    evidence = _evidence()
    before = evidence.to_json()
    publish_buyer_evidence(evidence)
    assert evidence.to_json() == before


def test_rejects_an_unsupported_source_type():
    with pytest.raises(BuyerEvidencePublicationError):
        publish_buyer_evidence(object())
