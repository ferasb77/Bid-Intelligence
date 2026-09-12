from dataclasses import FrozenInstanceError
import json

import pytest

from buyer_domain import (
    BUYER_DOMAIN_VERSION,
    BuyerAlias,
    BuyerValidationError,
    CanonicalBuyer,
    ContactKind,
    GovernmentLevel,
    Jurisdiction,
    OrganizationIdentifier,
    OrganizationalNote,
    OrganizationType,
    PublicContactReference,
    normalize_website,
)


def buyer(**changes):
    values = {
        "buyer_id": "buyer:bank-of-canada",
        "legal_name": "Bank of Canada",
        "common_name": "Canada's central bank",
        "country_code": "ca",
        "jurisdiction": Jurisdiction("ca", "Canada"),
        "government_level": GovernmentLevel.FEDERAL,
        "organization_type": OrganizationType.CENTRAL_BANK,
        "sector": "Central banking",
        "official_website": "HTTPS://WWW.BANKOFCANADA.CA/",
        "public_mandate": "Promote the economic and financial welfare of Canada.",
        "evidence_ids": ("evidence:mandate", "evidence:identity"),
        "identifiers": (
            OrganizationIdentifier("internal", "BOC"),
            OrganizationIdentifier("registry", "123"),
        ),
        "aliases": (BuyerAlias("Banque du Canada", "fr"),),
        "languages": ("fr-CA", "en-ca"),
        "public_contacts": (PublicContactReference(ContactKind.WEB, "https://bankofcanada.ca/contact/"),),
        "organizational_notes": (OrganizationalNote("note:legal-status", "Established by statute.", ("evidence:identity",)),),
    }
    values.update(changes)
    return CanonicalBuyer(**values)


def test_constructs_identity_only_canonical_buyer():
    item = buyer()
    assert item.contract_version == BUYER_DOMAIN_VERSION
    assert item.country_code == "CA"
    assert item.official_website == "https://www.bankofcanada.ca"
    assert item.languages == ("en-CA", "fr-CA")
    for prohibited in ("strategic_priorities", "procurement_behaviour", "risk", "findings",
                       "management_questions", "unknowns", "assumptions", "recommendations"):
        assert not hasattr(item, prohibited)


def test_required_identity_and_typed_fields_fail_closed():
    for change in ({"buyer_id": ""}, {"buyer_id": "?"}, {"legal_name": " "},
                   {"government_level": "FEDERAL"}, {"organization_type": "CENTRAL_BANK"},
                   {"evidence_ids": ()}):
        with pytest.raises(BuyerValidationError):
            buyer(**change)


def test_stable_identifier_and_parent_validation():
    with pytest.raises(BuyerValidationError, match="stable identifier"):
        buyer(parent_organization_id="bad id")
    with pytest.raises(BuyerValidationError, match="own parent"):
        buyer(parent_organization_id="buyer:bank-of-canada")
    with pytest.raises(BuyerValidationError, match="duplicates"):
        buyer(evidence_ids=("evidence:identity", "evidence:identity"))


def test_duplicate_aliases_are_case_insensitive_and_names_cannot_repeat():
    with pytest.raises(BuyerValidationError, match="aliases"):
        buyer(aliases=(BuyerAlias("BoC"), BuyerAlias("boc")))
    with pytest.raises(BuyerValidationError, match="legal or common"):
        buyer(aliases=(BuyerAlias("BANK OF CANADA"),))


@pytest.mark.parametrize("value, expected", [
    ("en", "en"), ("FR-ca", "fr-CA"), ("zh-Hant-TW", "zh-Hant-TW"),
])
def test_language_codes_are_normalized(value, expected):
    assert buyer(languages=(value,)).languages == (expected,)


@pytest.mark.parametrize("value", ["", "english", "e", "en_CA", "en-ca-extra"])
def test_invalid_language_codes_are_rejected(value):
    with pytest.raises(BuyerValidationError, match="BCP 47"):
        buyer(languages=(value,))


def test_website_normalization_is_narrow_and_deterministic():
    assert normalize_website("HTTPS://Example.COM:443/path/") == "https://example.com/path"
    assert normalize_website("http://example.com:8080/") == "http://example.com:8080"
    for value in ("example.com", "ftp://example.com", "https://user:pass@example.com", "https://example.com?q=1", "https://example.com/#x"):
        with pytest.raises(BuyerValidationError):
            normalize_website(value)


def test_jurisdiction_must_be_consistent():
    with pytest.raises(BuyerValidationError, match="must agree"):
        buyer(jurisdiction=Jurisdiction("US", "United States"))
    with pytest.raises(BuyerValidationError, match="belong"):
        Jurisdiction("CA", "Ontario", "US-NY")


def test_collections_are_ordered_deterministically():
    first = buyer(
        aliases=(BuyerAlias("Zed"), BuyerAlias("Alpha")),
        identifiers=(OrganizationIdentifier("z", "2"), OrganizationIdentifier("a", "1")),
        evidence_ids=("evidence:z", "evidence:a"),
    )
    second = buyer(
        aliases=tuple(reversed((BuyerAlias("Zed"), BuyerAlias("Alpha")))),
        identifiers=tuple(reversed((OrganizationIdentifier("z", "2"), OrganizationIdentifier("a", "1")))),
        evidence_ids=("evidence:a", "evidence:z"),
    )
    assert first == second
    assert first.to_json() == second.to_json()


def test_serialization_is_json_compatible_and_stable():
    item = buyer()
    encoded = item.to_json()
    decoded = json.loads(encoded)
    assert decoded["government_level"] == "FEDERAL"
    assert decoded["organization_type"] == "CENTRAL_BANK"
    assert encoded == item.to_json()


def test_contract_is_deeply_immutable():
    item = buyer()
    with pytest.raises((FrozenInstanceError, AttributeError)):
        item.legal_name = "Changed"
    with pytest.raises(TypeError):
        item.aliases[0] = BuyerAlias("Changed")
    with pytest.raises(FrozenInstanceError):
        item.aliases[0].name = "Changed"


def test_wrong_nested_types_and_duplicates_are_rejected():
    with pytest.raises(BuyerValidationError, match="identifiers"):
        buyer(identifiers=("identifier",))
    with pytest.raises(BuyerValidationError, match="identifiers.*duplicates"):
        buyer(identifiers=(OrganizationIdentifier("Registry", "ABC"), OrganizationIdentifier("registry", "abc")))
    with pytest.raises(BuyerValidationError, match="public_contacts.*duplicates"):
        buyer(public_contacts=(PublicContactReference(ContactKind.EMAIL, "buy@example.com"), PublicContactReference(ContactKind.EMAIL, "BUY@example.com")))


def test_notes_require_evidence_and_unsupported_version_is_rejected():
    with pytest.raises(BuyerValidationError, match="must not be empty"):
        OrganizationalNote("note:test", "A source fact.", ())
    with pytest.raises(BuyerValidationError, match="unsupported"):
        buyer(contract_version="canonical-buyer/2")


def test_unknown_boundary_fields_are_not_accepted():
    with pytest.raises(TypeError):
        CanonicalBuyer(**{**buyer().to_dict(), "recommendations": ("Bid",)})


def test_module_has_no_pipeline_or_network_dependencies():
    import pathlib

    source = (pathlib.Path(__file__).resolve().parents[1] / "buyer_domain.py").read_text(encoding="utf-8")
    for forbidden in ("extractor", "anthropic", "requests", "urllib.request", "stage_d"):
        assert forbidden not in source.casefold()

