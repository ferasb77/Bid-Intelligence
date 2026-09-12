"""Immutable canonical Buyer identity contracts.

This module represents attributable organizational identity only.  It performs
no retrieval, reconciliation, analysis, persistence, or brief generation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import json
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit


BUYER_DOMAIN_VERSION = "canonical-buyer/1"


class BuyerValidationError(ValueError):
    """Raised when a canonical Buyer contract is invalid."""


class GovernmentLevel(str, Enum):
    INTERNATIONAL = "INTERNATIONAL"
    FEDERAL = "FEDERAL"
    PROVINCIAL_STATE = "PROVINCIAL_STATE"
    REGIONAL = "REGIONAL"
    MUNICIPAL = "MUNICIPAL"
    INDIGENOUS = "INDIGENOUS"
    OTHER = "OTHER"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


class OrganizationType(str, Enum):
    GOVERNMENT_DEPARTMENT = "GOVERNMENT_DEPARTMENT"
    CROWN_PUBLIC_CORPORATION = "CROWN_PUBLIC_CORPORATION"
    CENTRAL_BANK = "CENTRAL_BANK"
    PUBLIC_AGENCY = "PUBLIC_AGENCY"
    MUNICIPALITY = "MUNICIPALITY"
    EDUCATIONAL_INSTITUTION = "EDUCATIONAL_INSTITUTION"
    HEALTHCARE_INSTITUTION = "HEALTHCARE_INSTITUTION"
    NONPROFIT = "NONPROFIT"
    PRIVATE_ORGANIZATION = "PRIVATE_ORGANIZATION"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class ContactKind(str, Enum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    WEB = "WEB"
    POSTAL = "POSTAL"
    OTHER = "OTHER"


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{2,127}$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_LANGUAGE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z]{4})?(?:-(?:[A-Za-z]{2}|[0-9]{3}))?$")


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BuyerValidationError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise BuyerValidationError(f"{field_name} must not have surrounding whitespace")
    return value


def _optional(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _required(value, field_name)


def _stable_id(value: str, field_name: str) -> str:
    value = _required(value, field_name)
    if not _ID.fullmatch(value):
        raise BuyerValidationError(f"{field_name} must be a stable identifier")
    return value


def _country(value: str, field_name: str = "country_code") -> str:
    value = _required(value, field_name).upper()
    if not _COUNTRY.fullmatch(value):
        raise BuyerValidationError(f"{field_name} must be an ISO 3166-1 alpha-2 code")
    return value


def _language(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip() or not _LANGUAGE.fullmatch(value):
        raise BuyerValidationError("languages must contain simple BCP 47 language codes")
    parts = value.split("-")
    normalized = [parts[0].lower()]
    for part in parts[1:]:
        normalized.append(part.title() if len(part) == 4 else part.upper())
    return "-".join(normalized)


def normalize_website(value: str) -> str:
    """Return a narrow canonical HTTPS/HTTP organizational URL."""
    value = _required(value, "official_website")
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise BuyerValidationError("official_website must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise BuyerValidationError("official_website must not contain credentials, query, or fragment")
    try:
        port = parsed.port
    except ValueError as exc:
        raise BuyerValidationError("official_website contains an invalid port") from exc
    scheme = parsed.scheme.lower()
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    path = parsed.path.rstrip("/") or ""
    return urlunsplit((scheme, host, path, "", ""))


@dataclass(frozen=True, slots=True, order=True)
class Jurisdiction:
    country_code: str
    name: str
    subdivision_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "country_code", _country(self.country_code, "jurisdiction.country_code"))
        _required(self.name, "jurisdiction.name")
        subdivision = _optional(self.subdivision_code, "jurisdiction.subdivision_code")
        if subdivision is not None:
            subdivision = subdivision.upper()
            if not re.fullmatch(r"[A-Z]{2}-[A-Z0-9]{1,3}", subdivision):
                raise BuyerValidationError("jurisdiction.subdivision_code must be an ISO 3166-2 style code")
            if not subdivision.startswith(self.country_code + "-"):
                raise BuyerValidationError("jurisdiction subdivision must belong to its country")
            object.__setattr__(self, "subdivision_code", subdivision)


@dataclass(frozen=True, slots=True, order=True)
class OrganizationIdentifier:
    scheme: str
    value: str
    issuing_authority: str | None = None

    def __post_init__(self) -> None:
        _required(self.scheme, "identifier.scheme")
        _required(self.value, "identifier.value")
        _optional(self.issuing_authority, "identifier.issuing_authority")


@dataclass(frozen=True, slots=True, order=True)
class BuyerAlias:
    name: str
    language_code: str | None = None

    def __post_init__(self) -> None:
        _required(self.name, "alias.name")
        if self.language_code is not None:
            object.__setattr__(self, "language_code", _language(self.language_code))


@dataclass(frozen=True, slots=True, order=True)
class PublicContactReference:
    kind: ContactKind
    value: str
    label: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ContactKind):
            raise BuyerValidationError("contact.kind must be a ContactKind")
        _required(self.value, "contact.value")
        _optional(self.label, "contact.label")
        if self.kind == ContactKind.WEB:
            object.__setattr__(self, "value", normalize_website(self.value))


@dataclass(frozen=True, slots=True, order=True)
class OrganizationalNote:
    note_id: str
    text: str
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _stable_id(self.note_id, "note.note_id")
        _required(self.text, "note.text")
        evidence = tuple(_stable_id(item, "note.evidence_ids") for item in self.evidence_ids)
        if not evidence:
            raise BuyerValidationError("note.evidence_ids must not be empty")
        if len(evidence) != len(set(evidence)):
            raise BuyerValidationError("note.evidence_ids must not contain duplicates")
        object.__setattr__(self, "evidence_ids", tuple(sorted(evidence)))


def _ordered_unique(values: tuple[Any, ...], field_name: str, key) -> tuple[Any, ...]:
    items = tuple(values)
    normalized_keys = [key(item) for item in items]
    if len(normalized_keys) != len(set(normalized_keys)):
        raise BuyerValidationError(f"{field_name} must not contain duplicates")
    return tuple(sorted(items, key=key))


@dataclass(frozen=True, slots=True)
class CanonicalBuyer:
    buyer_id: str
    legal_name: str
    country_code: str
    jurisdiction: Jurisdiction
    government_level: GovernmentLevel
    organization_type: OrganizationType
    evidence_ids: tuple[str, ...]
    common_name: str | None = None
    sector: str | None = None
    parent_organization_id: str | None = None
    public_mandate: str | None = None
    official_website: str | None = None
    primary_procurement_authority: str | None = None
    identifiers: tuple[OrganizationIdentifier, ...] = ()
    aliases: tuple[BuyerAlias, ...] = ()
    languages: tuple[str, ...] = ()
    public_contacts: tuple[PublicContactReference, ...] = ()
    organizational_notes: tuple[OrganizationalNote, ...] = ()
    contract_version: str = BUYER_DOMAIN_VERSION

    def __post_init__(self) -> None:
        _stable_id(self.buyer_id, "buyer_id")
        _required(self.legal_name, "legal_name")
        object.__setattr__(self, "country_code", _country(self.country_code))
        if not isinstance(self.jurisdiction, Jurisdiction):
            raise BuyerValidationError("jurisdiction must be a Jurisdiction")
        if self.jurisdiction.country_code != self.country_code:
            raise BuyerValidationError("jurisdiction and buyer country_code must agree")
        if not isinstance(self.government_level, GovernmentLevel):
            raise BuyerValidationError("government_level must be a GovernmentLevel")
        if not isinstance(self.organization_type, OrganizationType):
            raise BuyerValidationError("organization_type must be an OrganizationType")
        if self.contract_version != BUYER_DOMAIN_VERSION:
            raise BuyerValidationError(f"unsupported Buyer contract version: {self.contract_version}")
        for name in ("common_name", "sector", "public_mandate", "primary_procurement_authority"):
            _optional(getattr(self, name), name)
        if self.parent_organization_id is not None:
            _stable_id(self.parent_organization_id, "parent_organization_id")
            if self.parent_organization_id == self.buyer_id:
                raise BuyerValidationError("a Buyer cannot be its own parent")
        if self.official_website is not None:
            object.__setattr__(self, "official_website", normalize_website(self.official_website))

        evidence = tuple(_stable_id(item, "evidence_ids") for item in self.evidence_ids)
        if not evidence:
            raise BuyerValidationError("evidence_ids must not be empty")
        object.__setattr__(self, "evidence_ids", _ordered_unique(evidence, "evidence_ids", str))

        identifiers = self.identifiers
        aliases = self.aliases
        contacts = self.public_contacts
        notes = self.organizational_notes
        if any(not isinstance(item, OrganizationIdentifier) for item in identifiers):
            raise BuyerValidationError("identifiers must contain OrganizationIdentifier values")
        if any(not isinstance(item, BuyerAlias) for item in aliases):
            raise BuyerValidationError("aliases must contain BuyerAlias values")
        if any(not isinstance(item, PublicContactReference) for item in contacts):
            raise BuyerValidationError("public_contacts must contain PublicContactReference values")
        if any(not isinstance(item, OrganizationalNote) for item in notes):
            raise BuyerValidationError("organizational_notes must contain OrganizationalNote values")
        object.__setattr__(self, "identifiers", _ordered_unique(identifiers, "identifiers", lambda x: (x.scheme.casefold(), x.value.casefold())))
        alias_keys = [item.name.casefold() for item in aliases]
        reserved_names = {self.legal_name.casefold(), *((self.common_name.casefold(),) if self.common_name else ())}
        if any(key in reserved_names for key in alias_keys):
            raise BuyerValidationError("aliases must not duplicate the legal or common name")
        object.__setattr__(self, "aliases", _ordered_unique(aliases, "aliases", lambda x: x.name.casefold()))
        object.__setattr__(self, "public_contacts", _ordered_unique(contacts, "public_contacts", lambda x: (x.kind.value, x.value.casefold())))
        object.__setattr__(self, "organizational_notes", _ordered_unique(notes, "organizational_notes", lambda x: x.note_id))
        language_values = tuple(_language(item) for item in self.languages)
        object.__setattr__(self, "languages", _ordered_unique(language_values, "languages", str))

    def to_dict(self) -> dict[str, Any]:
        """Return a deterministic JSON-compatible representation."""
        return _enum_values(asdict(self))

    def to_json(self) -> str:
        """Serialize with stable key and collection ordering."""
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _enum_values(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _enum_values(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_enum_values(item) for item in value]
    return value
