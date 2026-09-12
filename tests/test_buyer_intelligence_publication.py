from datetime import date

import pytest

from buyer_domain import CanonicalBuyer, GovernmentLevel, Jurisdiction, OrganizationType
from buyer_evidence import (
    AuthenticityStatus, BuyerEvidenceSet, EvidenceAuthority, EvidenceCitation,
    EvidenceDocument, EvidenceExtract, EvidenceFreshness, EvidenceScope,
    EvidenceSource, FreshnessStatus, LocatorType, ScopeType, SourceCategory,
)
from buyer_evidence_publication import publish_buyer_evidence
from canonical_buyer_publication import IDENTITY_CLASS, publish_canonical_buyer
from buyer_intelligence import (
    BuyerFact, BuyerIntelligenceAnalysis, BuyerUnknown, Confidence, FactClass,
    FactKind, GovernedBuyerInputs, SupportStatus, UnknownKind, analyze_buyer,
    governed_input_digest,
)
from buyer_intelligence_publication import (
    ANALYSIS_CLASS, BUYER_FACT_CLASS, BuyerIntelligencePublicationError,
    BuyerIntelligencePublicationFailureCode, publish_buyer_intelligence,
    validate_buyer_intelligence_publication,
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


def _buyer():
    return CanonicalBuyer(
        BUYER_ID, "Bank of Canada", "CA", Jurisdiction("CA", "Canada"),
        GovernmentLevel.FEDERAL, OrganizationType.CENTRAL_BANK, ("extract:identity",),
    )


def _inputs():
    return GovernedBuyerInputs(
        buyer=_buyer(), evidence=_evidence(),
        opportunity_id="opportunity:bank-of-canada-rfp-2026-026-original",
        canonical_opportunity_version="canonical-opportunity/1",
        canonical_opportunity_digest="a" * 64, opportunity_entity_ids=("obs:1",),
        procurement_evidence_ids=("procurement:notice",), procurement_package_digest="b" * 64,
        evaluation_context_id="evaluation:bank-of-canada-buyer-intelligence",
        source_date=date(2026, 9, 12),
    )


def _publications():
    evidence = _evidence()
    evidence_pub = publish_buyer_evidence(evidence)
    buyer_pub = publish_canonical_buyer(_buyer(), evidence_publication=evidence_pub)
    return evidence_pub, buyer_pub


def test_publishes_every_analysis_section_with_one_analysis_root():
    inputs = _inputs()
    analysis = analyze_buyer(inputs)
    evidence_pub, buyer_pub = _publications()
    publication = publish_buyer_intelligence(
        analysis, buyer_evidence_publication=evidence_pub, canonical_buyer_publication=buyer_pub)
    classes = {item.object_class for item in publication.snapshot.objects}
    assert ANALYSIS_CLASS in classes
    assert BUYER_FACT_CLASS in classes
    roots = [item for item in publication.snapshot.objects if item.object_class == ANALYSIS_CLASS]
    assert len(roots) == 1
    assert roots[0].object_id == analysis.analysis_id
    expected_count = (len(analysis.buyer_facts) + len(analysis.public_organizational_information)
                      + len(analysis.verified_procurement_context) + len(analysis.computed_facts)
                      + len(analysis.interpretations) + len(analysis.competing_hypotheses)
                      + len(analysis.assumptions) + len(analysis.unknowns) + len(analysis.conflicts)
                      + len(analysis.management_questions) + len(analysis.limitations) + 1)
    assert len(publication.snapshot.objects) == expected_count


def test_analysis_root_contains_every_other_object():
    analysis = analyze_buyer(_inputs())
    evidence_pub, buyer_pub = _publications()
    publication = publish_buyer_intelligence(
        analysis, buyer_evidence_publication=evidence_pub, canonical_buyer_publication=buyer_pub)
    root = next(item for item in publication.snapshot.objects if item.object_class == ANALYSIS_CLASS)
    contains_relationships = [rel for rel in root.relationships if rel.kind == RelationshipKind.DEPENDENCY]
    contained = {(rel.target.object_class, rel.target.object_id) for rel in contains_relationships}
    all_other = {(item.object_class, item.object_id) for item in publication.snapshot.objects
                if item.object_class != ANALYSIS_CLASS}
    assert contained == all_other


def test_analysis_root_references_canonical_buyer_identity_instead_of_restating_it():
    # BUYER_INTELLIGENCE_FACT_OWNERSHIP_ARCHITECTURE.md: Canonical Buyer
    # remains the sole owner of identity. No BUYER_FACT object may restate
    # it; instead, the analysis root holds a direct governed reference to
    # Canonical Buyer Publication's own identity object.
    analysis = analyze_buyer(_inputs())
    evidence_pub, buyer_pub = _publications()
    publication = publish_buyer_intelligence(
        analysis, buyer_evidence_publication=evidence_pub, canonical_buyer_publication=buyer_pub)
    root = next(item for item in publication.snapshot.objects if item.object_class == ANALYSIS_CLASS)
    identity_relationships = [rel for rel in root.relationships if rel.role == "buyer-identity"]
    assert len(identity_relationships) == 1
    identity_relationship = identity_relationships[0]
    assert identity_relationship.kind == RelationshipKind.RELATED
    expected = buyer_pub.reference_for_identity()
    assert identity_relationship.target.object_id == expected.object_id
    assert identity_relationship.target.object_class == IDENTITY_CLASS
    assert identity_relationship.target.owner_domain == "canonical-buyer"
    # No published object anywhere in this snapshot restates identity content.
    assert not any(item.object_class == BUYER_FACT_CLASS
                  for item in publication.snapshot.objects
                  if any(field.name == "fact_kind" and field.value.scalar == "IDENTITY"
                        for field in item.semantic_fields))


def test_publication_is_deterministic():
    analysis = analyze_buyer(_inputs())
    evidence_pub, buyer_pub = _publications()
    first = publish_buyer_intelligence(analysis, buyer_evidence_publication=evidence_pub,
                                       canonical_buyer_publication=buyer_pub)
    second = publish_buyer_intelligence(analysis, buyer_evidence_publication=evidence_pub,
                                        canonical_buyer_publication=buyer_pub)
    assert first.digest == second.digest
    validate_buyer_intelligence_publication(first)


def test_refuses_evidence_id_neither_publication_can_resolve():
    fact = BuyerFact("fact:invented", FactClass.AUTHORITATIVE_BUYER_FACT, FactKind.IDENTITY,
                     "A fact citing evidence that was never acquired.", SupportStatus.SUPPORTED,
                     ("extract:never-acquired",))
    analysis = BuyerIntelligenceAnalysis(
        "bi-analysis-" + "0" * 64, BUYER_ID, "opportunity:bank-of-canada-rfp-2026-026-original",
        "evaluation:bank-of-canada-buyer-intelligence", "0" * 64, ("extract:never-acquired",),
        (fact,), (), (), (), (), (), (), (), (), (), (),
    )
    evidence_pub, buyer_pub = _publications()
    with pytest.raises(BuyerIntelligencePublicationError) as excinfo:
        publish_buyer_intelligence(analysis, buyer_evidence_publication=evidence_pub,
                                   canonical_buyer_publication=buyer_pub)
    assert excinfo.value.code == BuyerIntelligencePublicationFailureCode.MISSING_RELATIONSHIP_BINDING


def test_refuses_a_buyer_evidence_publication_for_a_different_buyer():
    other_evidence = BuyerEvidenceSet(
        "evidence-set:other", "buyer:someone-else",
        (EvidenceSource("source:other", "Someone Else", EvidenceAuthority.OFFICIAL_BUYER, "https://example.org"),),
        (EvidenceDocument("document:other", "source:other", SourceCategory.OFFICIAL_ORGANIZATIONAL_WEBSITE,
                          "Other", "https://example.org/about", "en", AuthenticityStatus.VERIFIED,
                          date(2026, 9, 12), EvidenceFreshness(FreshnessStatus.CURRENT, assessed_on=date(2026, 9, 12)),
                          (EvidenceScope(ScopeType.ORGANIZATION, "buyer:someone-else"),)),),
        (), ())
    other_pub = publish_buyer_evidence(other_evidence)
    analysis = analyze_buyer(_inputs())
    _, buyer_pub = _publications()
    with pytest.raises(BuyerIntelligencePublicationError):
        publish_buyer_intelligence(analysis, buyer_evidence_publication=other_pub,
                                   canonical_buyer_publication=buyer_pub)


def test_unknown_with_related_evidence_resolves_against_admitted_publications():
    unknown = BuyerUnknown("unknown:stale-mandate", UnknownKind.STALE_INFORMATION,
                           "The mandate statement may be stale.", "No refreshed source has been acquired.",
                           ("extract:identity",))
    digest_inputs = _inputs()
    analysis = BuyerIntelligenceAnalysis(
        "bi-analysis-" + "1" * 64, BUYER_ID, digest_inputs.opportunity_id,
        digest_inputs.evaluation_context_id, governed_input_digest(digest_inputs), ("extract:identity",),
        (), (), (), (), (), (), (), (unknown,), (), (), (),
    )
    evidence_pub, buyer_pub = _publications()
    publication = publish_buyer_intelligence(
        analysis, buyer_evidence_publication=evidence_pub, canonical_buyer_publication=buyer_pub)
    unknown_object = next(item for item in publication.snapshot.objects if item.object_id == "unknown:stale-mandate")
    assert len(unknown_object.relationships) == 1
