from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import date, datetime
import json

import pytest

from buyer_evidence import (
    BUYER_EVIDENCE_VERSION,
    AuthenticityStatus,
    BuyerEvidenceSet,
    EvidenceAuthority,
    EvidenceCitation,
    EvidenceDocument,
    EvidenceExtract,
    EvidenceFreshness,
    EvidenceScope,
    EvidenceSource,
    EvidenceValidationError,
    FreshnessStatus,
    LocatorType,
    ScopeType,
    SourceCategory,
    normalize_evidence_url,
)


BUYER_ID = "buyer:bank-of-canada"


def source(source_id="source:bank-of-canada"):
    return EvidenceSource(source_id, "Bank of Canada", EvidenceAuthority.OFFICIAL_BUYER,
                          "HTTPS://WWW.BANKOFCANADA.CA:443/")


def scope(scope_id=BUYER_ID):
    return EvidenceScope(ScopeType.ORGANIZATION, scope_id, "Bank of Canada")


def document(document_id="document:annual-report-2029", source_id="source:bank-of-canada", **changes):
    values = {
        "document_id": document_id,
        "source_id": source_id,
        "category": SourceCategory.ANNUAL_REPORT,
        "title": "Annual Report 2029",
        "canonical_url": "https://www.bankofcanada.ca/2029/annual-report.pdf",
        "language": "en-ca",
        "authenticity": AuthenticityStatus.VERIFIED,
        "publication_date": date(2030, 2, 1),
        "retrieval_date": date(2030, 2, 2),
        "freshness": EvidenceFreshness(FreshnessStatus.CURRENT, date(2030, 2, 2), date(2031, 2, 2)),
        "scopes": (scope(),),
        "content_sha256": "a" * 64,
    }
    values.update(changes)
    return EvidenceDocument(**values)


def citation(citation_id="citation:annual-report-p7", document_id="document:annual-report-2029"):
    return EvidenceCitation(citation_id, document_id, LocatorType.PAGE, "7")


def extract(extract_id="extract:mandate", document_id="document:annual-report-2029",
            citation_ids=("citation:annual-report-p7",)):
    return EvidenceExtract(extract_id, document_id, "The Bank has a statutory mandate.", citation_ids, "en-CA")


def evidence_set(**changes):
    values = {
        "evidence_set_id": "evidence-set:bank-of-canada",
        "buyer_id": BUYER_ID,
        "sources": (source(),),
        "documents": (document(),),
        "citations": (citation(),),
        "extracts": (extract(),),
    }
    values.update(changes)
    return BuyerEvidenceSet(**values)


def test_constructs_source_document_citation_and_extract_contracts():
    result = evidence_set()
    assert result.contract_version == BUYER_EVIDENCE_VERSION
    assert result.sources[0].base_url == "https://www.bankofcanada.ca/"
    assert result.documents[0].language == "en-CA"
    assert result.extracts[0].exact_text == "The Bank has a statutory mandate."


@pytest.mark.parametrize("category", list(SourceCategory))
def test_all_supported_source_categories_construct(category):
    assert document(category=category).category is category


def test_invalid_authority_category_and_authenticity_types_fail_closed():
    with pytest.raises(EvidenceValidationError, match="authority"):
        EvidenceSource("source:test", "Publisher", "OFFICIAL_BUYER", "https://example.gov/")
    with pytest.raises(EvidenceValidationError, match="category"):
        document(category="BLOG")
    with pytest.raises(EvidenceValidationError, match="authenticity"):
        document(authenticity="VERIFIED")


def test_dates_are_strict_and_consistent():
    with pytest.raises(EvidenceValidationError, match="retrieval_date"):
        document(retrieval_date="2030-02-02")
    with pytest.raises(EvidenceValidationError, match="retrieval_date"):
        document(retrieval_date=datetime(2030, 2, 2))
    with pytest.raises(EvidenceValidationError, match="cannot follow"):
        document(publication_date=date(2030, 3, 1), retrieval_date=date(2030, 2, 2))


def test_freshness_is_explicit_and_never_uses_current_time():
    with pytest.raises(EvidenceValidationError, match="requires assessed_on"):
        EvidenceFreshness(FreshnessStatus.CURRENT)
    with pytest.raises(EvidenceValidationError, match="cannot carry"):
        EvidenceFreshness(FreshnessStatus.NOT_ASSESSED, date(2030, 1, 1))
    with pytest.raises(EvidenceValidationError, match="cannot precede"):
        EvidenceFreshness(FreshnessStatus.STALE, date(2030, 2, 2), date(2030, 1, 1))


def test_language_and_url_validation():
    assert normalize_evidence_url("HTTPS://Example.GOV:443/report?q=official") == "https://example.gov/report?q=official"
    for language in ("", "english", "en_CA", "e"):
        with pytest.raises(EvidenceValidationError, match="BCP 47"):
            document(language=language)
    for url in ("example.gov", "ftp://example.gov/a", "https://user@example.gov/a", "https://example.gov/a#section"):
        with pytest.raises(EvidenceValidationError):
            document(canonical_url=url)


@pytest.mark.parametrize("locator_type, locator", [
    (LocatorType.DOCUMENT, "whole-document"),
    (LocatorType.PAGE, "2-7"),
    (LocatorType.SECTION, "Mandate / Functions"),
    (LocatorType.PARAGRAPH, "paragraph-12"),
    (LocatorType.TABLE_CELL, "Mandate!AA27:AB29"),
    (LocatorType.WEB_ANCHOR, "main-content"),
])
def test_supported_exact_citations(locator_type, locator):
    assert EvidenceCitation("citation:test", "document:test", locator_type, locator).locator == locator


@pytest.mark.parametrize("locator_type, locator", [
    (LocatorType.DOCUMENT, "all"),
    (LocatorType.PAGE, "0"),
    (LocatorType.PAGE, "7-2"),
    (LocatorType.TABLE_CELL, "AA27"),
    (LocatorType.TABLE_CELL, "Sheet!A0"),
])
def test_malformed_citations_are_rejected(locator_type, locator):
    with pytest.raises(EvidenceValidationError):
        EvidenceCitation("citation:test", "document:test", locator_type, locator)


def test_reference_closure_and_document_identity_are_enforced():
    with pytest.raises(EvidenceValidationError, match="unknown source_id"):
        evidence_set(documents=(document(source_id="source:missing"),))
    with pytest.raises(EvidenceValidationError, match="unknown document_id"):
        evidence_set(citations=(citation(document_id="document:missing"),))
    with pytest.raises(EvidenceValidationError, match="unknown citation_id"):
        evidence_set(extracts=(extract(citation_ids=("citation:missing",)),))
    with pytest.raises(EvidenceValidationError, match="different document"):
        evidence_set(
            documents=(document(), document("document:other")),
            citations=(citation(document_id="document:other"),),
        )
    with pytest.raises(EvidenceValidationError, match="inconsistent Buyer scope"):
        evidence_set(documents=(document(scopes=(scope("buyer:other"),)),))


def test_extract_language_must_match_document_language():
    with pytest.raises(EvidenceValidationError, match="language differs"):
        evidence_set(extracts=(EvidenceExtract("extract:test", "document:annual-report-2029",
                                              "Texte exact.", ("citation:annual-report-p7",), "fr-CA"),))


def test_duplicate_references_fail_closed():
    with pytest.raises(EvidenceValidationError, match="sources.*duplicates"):
        evidence_set(sources=(source(), source()))
    with pytest.raises(EvidenceValidationError, match="documents.*duplicates"):
        evidence_set(documents=(document(), document()))
    with pytest.raises(EvidenceValidationError, match="extract.citation_ids.*duplicates"):
        extract(citation_ids=("citation:annual-report-p7", "citation:annual-report-p7"))


def test_ordering_equality_and_serialization_are_deterministic():
    source_two = source("source:government")
    document_two = document("document:policy", "source:government", title="Procurement Policy",
                            category=SourceCategory.PROCUREMENT_POLICY)
    citation_two = citation("citation:policy-p2", "document:policy")
    extract_two = extract("extract:policy", "document:policy", ("citation:policy-p2",))
    values = {
        "sources": (source_two, source()),
        "documents": (document_two, document()),
        "citations": (citation_two, citation()),
        "extracts": (extract_two, extract()),
    }
    first = evidence_set(**values)
    second = evidence_set(**{key: tuple(reversed(value)) for key, value in values.items()})
    assert first == second
    assert first.to_json() == second.to_json()
    decoded = json.loads(first.to_json())
    assert decoded["documents"][0]["publication_date"] == "2030-02-01"


def test_contracts_are_deeply_immutable_and_safe_to_copy():
    original = evidence_set()
    copied = deepcopy(original)
    assert copied == original
    with pytest.raises(FrozenInstanceError):
        original.buyer_id = "buyer:other"
    with pytest.raises(TypeError):
        original.documents[0] = document("document:other")
    with pytest.raises(FrozenInstanceError):
        original.documents[0].title = "Changed"


def test_stable_identity_and_version_validation():
    with pytest.raises(EvidenceValidationError, match="stable identifier"):
        evidence_set(evidence_set_id="bad id")
    with pytest.raises(EvidenceValidationError, match="unsupported"):
        evidence_set(contract_version="buyer-evidence/2")


def test_boundary_has_no_intelligence_fields():
    item = evidence_set()
    prohibited = ("interpretation", "reasoning", "summary", "management_questions", "recommendations",
                  "procurement_strategy", "buyer_intelligence", "unknowns", "assumptions", "predictions",
                  "score", "ranking", "executive_conclusion")
    for value in (item, *item.sources, *item.documents, *item.citations, *item.extracts):
        assert all(not hasattr(value, field) for field in prohibited)
    with pytest.raises(TypeError):
        BuyerEvidenceSet(**{**item.to_dict(), "recommendations": ("Pursue",)})


def test_module_has_no_retrieval_ai_or_pipeline_dependency():
    import pathlib

    text = (pathlib.Path(__file__).resolve().parents[1] / "buyer_evidence.py").read_text(encoding="utf-8").casefold()
    for forbidden in ("requests", "urllib.request", "anthropic", "openai", "extractor", "stage_d"):
        assert forbidden not in text
