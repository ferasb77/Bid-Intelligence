"""Immutable contracts for attributable public Buyer evidence.

The contracts describe sources and source material.  They do not retrieve,
interpret, summarize, score, or otherwise reason about that material.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from enum import Enum
import json
import re
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit, urlunsplit


BUYER_EVIDENCE_VERSION = "buyer-evidence/1"


class EvidenceValidationError(ValueError):
    """Raised when Buyer evidence violates a contract invariant."""


class SourceCategory(str, Enum):
    OFFICIAL_ORGANIZATIONAL_WEBSITE = "OFFICIAL_ORGANIZATIONAL_WEBSITE"
    ANNUAL_REPORT = "ANNUAL_REPORT"
    STRATEGIC_PLAN = "STRATEGIC_PLAN"
    LEGISLATION = "LEGISLATION"
    POLICY_DOCUMENT = "POLICY_DOCUMENT"
    ORGANIZATIONAL_CHART = "ORGANIZATIONAL_CHART"
    PROCUREMENT_POLICY = "PROCUREMENT_POLICY"
    ACCESSIBILITY_STATEMENT = "ACCESSIBILITY_STATEMENT"
    OFFICIAL_PRESS_RELEASE = "OFFICIAL_PRESS_RELEASE"
    PROCUREMENT_NOTICE = "PROCUREMENT_NOTICE"
    GOVERNMENT_PUBLICATION = "GOVERNMENT_PUBLICATION"
    OTHER_OFFICIAL_PUBLICATION = "OTHER_OFFICIAL_PUBLICATION"


class EvidenceAuthority(str, Enum):
    OFFICIAL_BUYER = "OFFICIAL_BUYER"
    LEGISLATIVE_AUTHORITY = "LEGISLATIVE_AUTHORITY"
    GOVERNMENT_AUTHORITY = "GOVERNMENT_AUTHORITY"
    OFFICIAL_PROCUREMENT_AUTHORITY = "OFFICIAL_PROCUREMENT_AUTHORITY"
    OTHER_OFFICIAL_PUBLISHER = "OTHER_OFFICIAL_PUBLISHER"
    ATTRIBUTABLE_PUBLIC_SOURCE = "ATTRIBUTABLE_PUBLIC_SOURCE"


class AuthenticityStatus(str, Enum):
    VERIFIED = "VERIFIED"
    PROVISIONAL = "PROVISIONAL"
    UNVERIFIED = "UNVERIFIED"


class FreshnessStatus(str, Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    NOT_ASSESSED = "NOT_ASSESSED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ScopeType(str, Enum):
    ORGANIZATION = "ORGANIZATION"
    ORGANIZATIONAL_UNIT = "ORGANIZATIONAL_UNIT"
    JURISDICTION = "JURISDICTION"
    PROGRAM = "PROGRAM"
    OPPORTUNITY = "OPPORTUNITY"


class LocatorType(str, Enum):
    DOCUMENT = "DOCUMENT"
    PAGE = "PAGE"
    SECTION = "SECTION"
    PARAGRAPH = "PARAGRAPH"
    TABLE_CELL = "TABLE_CELL"
    WEB_ANCHOR = "WEB_ANCHOR"


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{2,127}$")
_LANGUAGE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z]{4})?(?:-(?:[A-Za-z]{2}|[0-9]{3}))?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PAGE = re.compile(r"^[1-9][0-9]*(?:-[1-9][0-9]*)?$")
_CELL = re.compile(r"^(?:'[^']+'|[A-Za-z0-9_. -]+)![A-Z]+[1-9][0-9]*(?::[A-Z]+[1-9][0-9]*)?$")


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceValidationError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise EvidenceValidationError(f"{field_name} must not have surrounding whitespace")
    return value


def _optional(value: str | None, field_name: str) -> str | None:
    return None if value is None else _required(value, field_name)


def _stable_id(value: str, field_name: str) -> str:
    value = _required(value, field_name)
    if not _ID.fullmatch(value):
        raise EvidenceValidationError(f"{field_name} must be a stable identifier")
    return value


def _language(value: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not _LANGUAGE.fullmatch(value):
        raise EvidenceValidationError("language must be a simple BCP 47 language code")
    parts = value.split("-")
    return "-".join([parts[0].lower(), *(part.title() if len(part) == 4 else part.upper() for part in parts[1:])])


def normalize_evidence_url(value: str) -> str:
    """Normalize an HTTP(S) source URL without changing its resource identity."""
    value = _required(value, "url")
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise EvidenceValidationError("url must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.fragment:
        raise EvidenceValidationError("url must not contain credentials or a fragment")
    try:
        port = parsed.port
        host = parsed.hostname.encode("idna").decode("ascii").lower()
    except (ValueError, UnicodeError) as exc:
        raise EvidenceValidationError("url contains an invalid host or port") from exc
    scheme = parsed.scheme.lower()
    if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    path = parsed.path or "/"
    return urlunsplit((scheme, host, path, parsed.query, ""))


def _typed_date(value: date | None, field_name: str) -> date | None:
    if value is not None and (not isinstance(value, date) or type(value) is not date):
        raise EvidenceValidationError(f"{field_name} must be a date or None")
    return value


def _ordered_unique(values: Iterable[Any], field_name: str, key: Callable[[Any], Any]) -> tuple[Any, ...]:
    items = tuple(values)
    keys = [key(item) for item in items]
    if len(keys) != len(set(keys)):
        raise EvidenceValidationError(f"{field_name} must not contain duplicates")
    return tuple(sorted(items, key=key))


@dataclass(frozen=True, slots=True, order=True)
class EvidenceFreshness:
    status: FreshnessStatus
    assessed_on: date | None = None
    valid_through: date | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, FreshnessStatus):
            raise EvidenceValidationError("freshness.status must be a FreshnessStatus")
        _typed_date(self.assessed_on, "freshness.assessed_on")
        _typed_date(self.valid_through, "freshness.valid_through")
        if self.status in {FreshnessStatus.CURRENT, FreshnessStatus.STALE} and self.assessed_on is None:
            raise EvidenceValidationError("assessed freshness requires assessed_on")
        if self.status in {FreshnessStatus.NOT_ASSESSED, FreshnessStatus.NOT_APPLICABLE} and (
            self.assessed_on is not None or self.valid_through is not None
        ):
            raise EvidenceValidationError("unassessed or inapplicable freshness cannot carry assessment dates")
        if self.valid_through is not None and self.assessed_on is not None and self.valid_through < self.assessed_on:
            raise EvidenceValidationError("freshness.valid_through cannot precede assessed_on")


@dataclass(frozen=True, slots=True, order=True)
class EvidenceScope:
    scope_type: ScopeType
    scope_id: str
    label: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.scope_type, ScopeType):
            raise EvidenceValidationError("scope_type must be a ScopeType")
        _stable_id(self.scope_id, "scope_id")
        _optional(self.label, "scope.label")


@dataclass(frozen=True, slots=True, order=True)
class EvidenceSource:
    source_id: str
    publisher_name: str
    authority: EvidenceAuthority
    base_url: str
    jurisdiction: str | None = None

    def __post_init__(self) -> None:
        _stable_id(self.source_id, "source_id")
        _required(self.publisher_name, "publisher_name")
        if not isinstance(self.authority, EvidenceAuthority):
            raise EvidenceValidationError("authority must be an EvidenceAuthority")
        object.__setattr__(self, "base_url", normalize_evidence_url(self.base_url))
        _optional(self.jurisdiction, "source.jurisdiction")


@dataclass(frozen=True, slots=True, order=True)
class EvidenceDocument:
    document_id: str
    source_id: str
    category: SourceCategory
    title: str
    canonical_url: str
    language: str
    authenticity: AuthenticityStatus
    retrieval_date: date
    freshness: EvidenceFreshness
    scopes: tuple[EvidenceScope, ...]
    publication_date: date | None = None
    publisher_document_id: str | None = None
    version_label: str | None = None
    content_sha256: str | None = None

    def __post_init__(self) -> None:
        _stable_id(self.document_id, "document_id")
        _stable_id(self.source_id, "document.source_id")
        if not isinstance(self.category, SourceCategory):
            raise EvidenceValidationError("category must be a SourceCategory")
        _required(self.title, "document.title")
        object.__setattr__(self, "canonical_url", normalize_evidence_url(self.canonical_url))
        object.__setattr__(self, "language", _language(self.language))
        if not isinstance(self.authenticity, AuthenticityStatus):
            raise EvidenceValidationError("authenticity must be an AuthenticityStatus")
        _typed_date(self.retrieval_date, "retrieval_date")
        _typed_date(self.publication_date, "publication_date")
        if self.publication_date is not None and self.publication_date > self.retrieval_date:
            raise EvidenceValidationError("publication_date cannot follow retrieval_date")
        if not isinstance(self.freshness, EvidenceFreshness):
            raise EvidenceValidationError("freshness must be EvidenceFreshness")
        if any(not isinstance(item, EvidenceScope) for item in self.scopes):
            raise EvidenceValidationError("scopes must contain EvidenceScope values")
        if not self.scopes:
            raise EvidenceValidationError("scopes must not be empty")
        object.__setattr__(self, "scopes", _ordered_unique(self.scopes, "scopes", lambda item: (item.scope_type.value, item.scope_id)))
        _optional(self.publisher_document_id, "publisher_document_id")
        _optional(self.version_label, "version_label")
        if self.content_sha256 is not None:
            digest = _required(self.content_sha256, "content_sha256").lower()
            if not _SHA256.fullmatch(digest):
                raise EvidenceValidationError("content_sha256 must contain 64 hexadecimal characters")
            object.__setattr__(self, "content_sha256", digest)


@dataclass(frozen=True, slots=True, order=True)
class EvidenceCitation:
    citation_id: str
    document_id: str
    locator_type: LocatorType
    locator: str

    def __post_init__(self) -> None:
        _stable_id(self.citation_id, "citation_id")
        _stable_id(self.document_id, "citation.document_id")
        if not isinstance(self.locator_type, LocatorType):
            raise EvidenceValidationError("locator_type must be a LocatorType")
        _required(self.locator, "citation.locator")
        if self.locator_type == LocatorType.DOCUMENT and self.locator != "whole-document":
            raise EvidenceValidationError("document citations must use the whole-document locator")
        if self.locator_type == LocatorType.PAGE:
            match = _PAGE.fullmatch(self.locator)
            if not match:
                raise EvidenceValidationError("page locator must be a positive page or page range")
            if "-" in self.locator:
                start, end = map(int, self.locator.split("-"))
                if end < start:
                    raise EvidenceValidationError("page range end cannot precede its start")
        if self.locator_type == LocatorType.TABLE_CELL and not _CELL.fullmatch(self.locator):
            raise EvidenceValidationError("table-cell locator must contain an exact sheet and cell or range")


@dataclass(frozen=True, slots=True, order=True)
class EvidenceExtract:
    extract_id: str
    document_id: str
    exact_text: str
    citation_ids: tuple[str, ...]
    language: str

    def __post_init__(self) -> None:
        _stable_id(self.extract_id, "extract_id")
        _stable_id(self.document_id, "extract.document_id")
        _required(self.exact_text, "exact_text")
        citations = tuple(_stable_id(item, "extract.citation_ids") for item in self.citation_ids)
        if not citations:
            raise EvidenceValidationError("extract.citation_ids must not be empty")
        object.__setattr__(self, "citation_ids", _ordered_unique(citations, "extract.citation_ids", str))
        object.__setattr__(self, "language", _language(self.language))


@dataclass(frozen=True, slots=True)
class BuyerEvidenceSet:
    evidence_set_id: str
    buyer_id: str
    sources: tuple[EvidenceSource, ...]
    documents: tuple[EvidenceDocument, ...]
    citations: tuple[EvidenceCitation, ...]
    extracts: tuple[EvidenceExtract, ...]
    contract_version: str = BUYER_EVIDENCE_VERSION

    def __post_init__(self) -> None:
        _stable_id(self.evidence_set_id, "evidence_set_id")
        _stable_id(self.buyer_id, "buyer_id")
        if self.contract_version != BUYER_EVIDENCE_VERSION:
            raise EvidenceValidationError(f"unsupported Buyer evidence contract version: {self.contract_version}")
        collections = (
            ("sources", self.sources, EvidenceSource, lambda item: item.source_id),
            ("documents", self.documents, EvidenceDocument, lambda item: item.document_id),
            ("citations", self.citations, EvidenceCitation, lambda item: item.citation_id),
            ("extracts", self.extracts, EvidenceExtract, lambda item: item.extract_id),
        )
        for name, values, expected, key in collections:
            if any(not isinstance(item, expected) for item in values):
                raise EvidenceValidationError(f"{name} must contain {expected.__name__} values")
            object.__setattr__(self, name, _ordered_unique(values, name, key))
        if not self.sources or not self.documents:
            raise EvidenceValidationError("an evidence set requires at least one source and document")

        source_ids = {item.source_id for item in self.sources}
        documents = {item.document_id: item for item in self.documents}
        citations = {item.citation_id: item for item in self.citations}
        for document in self.documents:
            if document.source_id not in source_ids:
                raise EvidenceValidationError(f"document references unknown source_id: {document.source_id}")
            buyer_scopes = {scope.scope_id for scope in document.scopes if scope.scope_type == ScopeType.ORGANIZATION}
            if buyer_scopes and self.buyer_id not in buyer_scopes:
                raise EvidenceValidationError(f"document {document.document_id} has an inconsistent Buyer scope")
        for citation in self.citations:
            if citation.document_id not in documents:
                raise EvidenceValidationError(f"citation references unknown document_id: {citation.document_id}")
        for extract in self.extracts:
            document = documents.get(extract.document_id)
            if document is None:
                raise EvidenceValidationError(f"extract references unknown document_id: {extract.document_id}")
            if extract.language != document.language:
                raise EvidenceValidationError(f"extract {extract.extract_id} language differs from its document")
            for citation_id in extract.citation_ids:
                citation = citations.get(citation_id)
                if citation is None:
                    raise EvidenceValidationError(f"extract references unknown citation_id: {citation_id}")
                if citation.document_id != extract.document_id:
                    raise EvidenceValidationError(f"extract {extract.extract_id} cites a different document")

    def to_dict(self) -> dict[str, Any]:
        return _primitives(asdict(self))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _primitives(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _primitives(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_primitives(item) for item in value]
    return value
