"""Immutable, domain-neutral Evidence owner contracts.

This module owns attributable source representations and provenance only.  It
does not publish governed references, resolve them, or create canonical or
analytical meaning.
"""

from __future__ import annotations

import base64
import json
import re
import unicodedata
from dataclasses import dataclass, fields, is_dataclass
from datetime import date
from enum import Enum
from hashlib import sha256
from typing import Iterable
from urllib.parse import urlparse


EVIDENCE_CONTRACT_VERSION = "1.0.0"
EVIDENCE_SNAPSHOT_VERSION = "1.0.0"
EVIDENCE_OWNER = "evidence"

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_LANGUAGE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")


class EvidenceFailureCode(str, Enum):
    INVALID_VALUE = "INVALID_VALUE"
    INVALID_IDENTITY = "INVALID_IDENTITY"
    INVALID_CONTENT = "INVALID_CONTENT"
    INVALID_RELATIONSHIP = "INVALID_RELATIONSHIP"
    DUPLICATE_IDENTITY = "DUPLICATE_IDENTITY"
    INCOMPLETE_PROVENANCE = "INCOMPLETE_PROVENANCE"
    INCOMPLETE_SNAPSHOT = "INCOMPLETE_SNAPSHOT"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"
    SUPERSESSION_CYCLE = "SUPERSESSION_CYCLE"


class EvidenceValidationError(ValueError):
    def __init__(self, code: EvidenceFailureCode, message: str):
        self.code = code
        super().__init__(f"{code.value}: {message}")


class EvidenceObjectClass(str, Enum):
    SOURCE = "EVIDENCE_SOURCE"
    ARTIFACT = "EVIDENCE_ARTIFACT"
    OCCURRENCE = "EVIDENCE_OCCURRENCE"
    EXTRACT = "EVIDENCE_EXTRACT"


class SourceKind(str, Enum):
    ORGANIZATION = "ORGANIZATION"
    PERSON = "PERSON"
    GOVERNED_SYSTEM = "GOVERNED_SYSTEM"
    OTHER_ATTRIBUTABLE = "OTHER_ATTRIBUTABLE"


class ArtifactKind(str, Enum):
    DOCUMENT = "DOCUMENT"
    NOTICE = "NOTICE"
    AMENDMENT = "AMENDMENT"
    RECORD = "RECORD"
    MESSAGE = "MESSAGE"
    DATASET = "DATASET"
    WEB_CAPTURE = "WEB_CAPTURE"
    OTHER_SOURCE_MATERIAL = "OTHER_SOURCE_MATERIAL"


class LocatorKind(str, Enum):
    WHOLE_ARTIFACT = "WHOLE_ARTIFACT"
    PAGE = "PAGE"
    SECTION = "SECTION"
    PARAGRAPH = "PARAGRAPH"
    CELL = "CELL"
    RECORD = "RECORD"
    URL_CAPTURE = "URL_CAPTURE"
    MESSAGE_PART = "MESSAGE_PART"
    OTHER_EXACT = "OTHER_EXACT"


class AuthenticityState(str, Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"


class EvidenceRelationshipKind(str, Enum):
    ATTRIBUTABLE_SOURCE = "ATTRIBUTABLE_SOURCE"
    ARTIFACT_OCCURRENCE = "ARTIFACT_OCCURRENCE"
    EXTRACT_OCCURRENCE = "EXTRACT_OCCURRENCE"
    EXTRACT_ARTIFACT = "EXTRACT_ARTIFACT"
    TRANSLATION = "TRANSLATION"
    EQUIVALENT = "EQUIVALENT"
    SUPERSEDES = "SUPERSEDES"
    LINEAGE = "LINEAGE"


_CLASS_ORDER = {
    EvidenceObjectClass.SOURCE: 0,
    EvidenceObjectClass.ARTIFACT: 1,
    EvidenceObjectClass.OCCURRENCE: 2,
    EvidenceObjectClass.EXTRACT: 3,
}


def _fail(code: EvidenceFailureCode, message: str):
    raise EvidenceValidationError(code, message)


def _required(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        _fail(EvidenceFailureCode.INVALID_VALUE, f"{name} must be a non-empty trimmed string")
    return value


def _identifier(value: object, name: str) -> str:
    value = _required(value, name)
    if not _IDENTIFIER.fullmatch(value):
        _fail(EvidenceFailureCode.INVALID_IDENTITY, f"{name} has invalid syntax")
    return value


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        _fail(EvidenceFailureCode.DIGEST_MISMATCH, f"{name} must be a lowercase SHA-256 digest")
    return value


def _language(value: object) -> str:
    value = _required(value, "language")
    if not _LANGUAGE.fullmatch(value):
        _fail(EvidenceFailureCode.INVALID_VALUE, "language must be a BCP-47-style tag")
    parts = value.split("-")
    return "-".join((parts[0].lower(), *(part.upper() if len(part) == 2 else part for part in parts[1:])))


def _uri(value: object, name: str) -> str:
    value = _required(value, name)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        _fail(EvidenceFailureCode.INVALID_VALUE, f"{name} must be an absolute HTTP(S) URL without credentials")
    return value


def _locator(kind: LocatorKind, value: object) -> str:
    value = _required(value, "locator")
    patterns = {
        LocatorKind.WHOLE_ARTIFACT: r"whole-(?:artifact|document)",
        LocatorKind.PAGE: r"page:\d+|pages:\d+-\d+",
        LocatorKind.SECTION: r"section:.+",
        LocatorKind.PARAGRAPH: r"paragraph:\d+(?:-\d+)?",
        LocatorKind.CELL: r"sheet:[^!]+![A-Z]+\d+(?::[A-Z]+\d+)?",
        LocatorKind.RECORD: r"record:.+",
        LocatorKind.URL_CAPTURE: r"url-capture:https?://.+",
        LocatorKind.MESSAGE_PART: r"message-part:.+",
        LocatorKind.OTHER_EXACT: r"exact:.+",
    }
    if not re.fullmatch(patterns[kind], value):
        _fail(EvidenceFailureCode.INVALID_VALUE,
              f"locator is not exact for {kind.value}")
    if kind is LocatorKind.PAGE and value.startswith("pages:"):
        start, end = (int(item) for item in value[6:].split("-"))
        if start < 1 or end < start:
            _fail(EvidenceFailureCode.INVALID_VALUE, "page range is invalid")
    elif kind is LocatorKind.PAGE and int(value[5:]) < 1:
        _fail(EvidenceFailureCode.INVALID_VALUE, "page must be positive")
    return value


def _normalize_text(value: str) -> str:
    return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))


def _canonical(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        return {"encoding": "base64", "value": base64.b64encode(value).decode("ascii")}
    if is_dataclass(value):
        return {item.name: _canonical(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, str):
        return _normalize_text(value)
    if value is None or isinstance(value, (bool, int)):
        return value
    _fail(EvidenceFailureCode.INVALID_VALUE, f"unsupported canonical value: {type(value).__name__}")


def canonical_evidence_json(value) -> str:
    return json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _sha(value) -> str:
    return sha256(canonical_evidence_json(value).encode("utf-8")).hexdigest()


def _content_bytes(value: str | bytes) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return _normalize_text(value).encode("utf-8")
    _fail(EvidenceFailureCode.INVALID_CONTENT, "content must be immutable text or bytes")


@dataclass(frozen=True, slots=True, order=True)
class RelationshipTarget:
    kind: EvidenceRelationshipKind
    role: str
    target_class: EvidenceObjectClass
    target_id: str
    ordinal: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EvidenceRelationshipKind):
            _fail(EvidenceFailureCode.INVALID_RELATIONSHIP, "relationship kind is unsupported")
        _identifier(self.role, "relationship role")
        if not isinstance(self.target_class, EvidenceObjectClass):
            _fail(EvidenceFailureCode.INVALID_RELATIONSHIP, "target class is unsupported")
        _identifier(self.target_id, "relationship target_id")
        if not isinstance(self.ordinal, int) or isinstance(self.ordinal, bool) or self.ordinal < 0:
            _fail(EvidenceFailureCode.INVALID_RELATIONSHIP, "relationship ordinal must be a non-negative integer")


def _relationships(values: tuple[RelationshipTarget, ...]) -> tuple[RelationshipTarget, ...]:
    if not isinstance(values, tuple) or any(not isinstance(item, RelationshipTarget) for item in values):
        _fail(EvidenceFailureCode.INVALID_RELATIONSHIP, "relationships must be an immutable tuple")
    ordered = tuple(sorted(values, key=lambda item: (
        item.kind.value, item.role, item.ordinal,
        _CLASS_ORDER[item.target_class], item.target_id)))
    if values != ordered or len(values) != len(set(values)):
        _fail(EvidenceFailureCode.INVALID_RELATIONSHIP,
              "relationships must be unique and canonically ordered")
    return values


class _EvidenceObject:
    @property
    def object_digest(self) -> str:
        return _sha({
            "contract_version": EVIDENCE_CONTRACT_VERSION,
            "object_class": self.object_class,
            "object_id": self.object_id,
            "semantics": self._semantic_payload(),
            "relationships": _all_targets(self),
        })

    def _semantic_payload(self) -> dict:
        raise NotImplementedError

    def to_dict(self) -> dict:
        return _canonical({
            "contract_version": EVIDENCE_CONTRACT_VERSION,
            "object_class": self.object_class,
            "object_id": self.object_id,
            "object_digest": self.object_digest,
            "semantics": self._semantic_payload(),
            "relationships": _all_targets(self),
        })

    def to_json(self) -> str:
        return canonical_evidence_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class EvidenceSource(_EvidenceObject):
    source_key: str
    name: str
    kind: SourceKind
    authoritative_uri: str | None = None
    relationships: tuple[RelationshipTarget, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.source_key, "source_key")
        _required(self.name, "source name")
        if not isinstance(self.kind, SourceKind):
            _fail(EvidenceFailureCode.INVALID_VALUE, "source kind is unsupported")
        if self.authoritative_uri is not None:
            _uri(self.authoritative_uri, "authoritative_uri")
        _relationships(self.relationships)

    @property
    def object_class(self) -> EvidenceObjectClass:
        return EvidenceObjectClass.SOURCE

    @property
    def object_id(self) -> str:
        return "esrc-" + _sha(self._identity_payload())

    def _identity_payload(self) -> dict:
        return {"owner": EVIDENCE_OWNER, "class": self.object_class,
                "source_key": self.source_key}

    def _semantic_payload(self) -> dict:
        return {"source_key": self.source_key, "name": self.name,
                "kind": self.kind, "authoritative_uri": self.authoritative_uri}


@dataclass(frozen=True, slots=True)
class EvidenceArtifact(_EvidenceObject):
    source_id: str
    artifact_kind: ArtifactKind
    title: str
    version_label: str
    media_type: str
    language: str
    content_sha256: str
    content: str | bytes | None = None
    governed_location: str | None = None
    publication_date: date | None = None
    effective_date: date | None = None
    relationships: tuple[RelationshipTarget, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.source_id, "source_id")
        if not isinstance(self.artifact_kind, ArtifactKind):
            _fail(EvidenceFailureCode.INVALID_VALUE, "artifact kind is unsupported")
        _required(self.title, "artifact title")
        _required(self.version_label, "version_label")
        media = _required(self.media_type, "media_type")
        if "/" not in media or any(char.isspace() for char in media):
            _fail(EvidenceFailureCode.INVALID_VALUE, "media_type must be a MIME type")
        normalized_language = _language(self.language)
        if normalized_language != self.language:
            object.__setattr__(self, "language", normalized_language)
        _digest(self.content_sha256, "content_sha256")
        if self.content is None and self.governed_location is None:
            _fail(EvidenceFailureCode.INVALID_CONTENT,
                  "artifact requires immutable content or a governed location")
        if self.content is not None:
            actual = sha256(_content_bytes(self.content)).hexdigest()
            if actual != self.content_sha256:
                _fail(EvidenceFailureCode.DIGEST_MISMATCH,
                      "artifact content does not match content_sha256")
        if self.governed_location is not None:
            _uri(self.governed_location, "governed_location")
        for name in ("publication_date", "effective_date"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, date) or hasattr(value, "hour")):
                _fail(EvidenceFailureCode.INVALID_VALUE, f"{name} must be a calendar date")
        _relationships(self.relationships)

    @property
    def object_class(self) -> EvidenceObjectClass:
        return EvidenceObjectClass.ARTIFACT

    @property
    def object_id(self) -> str:
        return "eart-" + _sha({
            "owner": EVIDENCE_OWNER, "class": self.object_class,
            "source_id": self.source_id, "kind": self.artifact_kind,
            "version_label": self.version_label,
            "content_sha256": self.content_sha256,
        })

    def _semantic_payload(self) -> dict:
        return {
            "source_id": self.source_id, "artifact_kind": self.artifact_kind,
            "title": self.title, "version_label": self.version_label,
            "media_type": self.media_type, "language": self.language,
            "content_sha256": self.content_sha256, "content": self.content,
            "governed_location": self.governed_location,
            "publication_date": self.publication_date,
            "effective_date": self.effective_date,
        }


@dataclass(frozen=True, slots=True)
class EvidenceOccurrence(_EvidenceObject):
    source_id: str
    artifact_id: str
    occurrence_key: str
    locator_kind: LocatorKind
    locator: str
    language: str
    acquisition_date: date
    authenticity: AuthenticityState
    integrity_sha256: str
    relationships: tuple[RelationshipTarget, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.source_id, "source_id")
        _identifier(self.artifact_id, "artifact_id")
        _identifier(self.occurrence_key, "occurrence_key")
        if not isinstance(self.locator_kind, LocatorKind):
            _fail(EvidenceFailureCode.INVALID_VALUE, "locator kind is unsupported")
        _locator(self.locator_kind, self.locator)
        normalized_language = _language(self.language)
        if normalized_language != self.language:
            object.__setattr__(self, "language", normalized_language)
        if not isinstance(self.acquisition_date, date) or hasattr(self.acquisition_date, "hour"):
            _fail(EvidenceFailureCode.INVALID_VALUE, "acquisition_date must be a calendar date")
        if not isinstance(self.authenticity, AuthenticityState):
            _fail(EvidenceFailureCode.INVALID_VALUE, "authenticity state is unsupported")
        _digest(self.integrity_sha256, "integrity_sha256")
        _relationships(self.relationships)

    @property
    def object_class(self) -> EvidenceObjectClass:
        return EvidenceObjectClass.OCCURRENCE

    @property
    def object_id(self) -> str:
        return "eocc-" + _sha({
            "owner": EVIDENCE_OWNER, "class": self.object_class,
            "source_id": self.source_id, "artifact_id": self.artifact_id,
            "occurrence_key": self.occurrence_key,
            "locator_kind": self.locator_kind, "locator": self.locator,
            "acquisition_date": self.acquisition_date,
        })

    def _semantic_payload(self) -> dict:
        return {
            "source_id": self.source_id, "artifact_id": self.artifact_id,
            "occurrence_key": self.occurrence_key,
            "locator_kind": self.locator_kind, "locator": self.locator,
            "language": self.language, "acquisition_date": self.acquisition_date,
            "authenticity": self.authenticity,
            "integrity_sha256": self.integrity_sha256,
        }


@dataclass(frozen=True, slots=True)
class EvidenceExtract(_EvidenceObject):
    artifact_id: str
    occurrence_id: str
    locator_kind: LocatorKind
    locator: str
    language: str
    content: str | bytes
    content_sha256: str
    relationships: tuple[RelationshipTarget, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.artifact_id, "artifact_id")
        _identifier(self.occurrence_id, "occurrence_id")
        if not isinstance(self.locator_kind, LocatorKind):
            _fail(EvidenceFailureCode.INVALID_VALUE, "locator kind is unsupported")
        if self.locator_kind is LocatorKind.WHOLE_ARTIFACT:
            _fail(EvidenceFailureCode.INVALID_VALUE,
                  "an extract requires a bounded locator")
        _locator(self.locator_kind, self.locator)
        normalized_language = _language(self.language)
        if normalized_language != self.language:
            object.__setattr__(self, "language", normalized_language)
        payload = _content_bytes(self.content)
        if not payload:
            _fail(EvidenceFailureCode.INVALID_CONTENT, "extract content must not be empty")
        _digest(self.content_sha256, "content_sha256")
        if sha256(payload).hexdigest() != self.content_sha256:
            _fail(EvidenceFailureCode.DIGEST_MISMATCH,
                  "extract content does not match content_sha256")
        _relationships(self.relationships)

    @property
    def object_class(self) -> EvidenceObjectClass:
        return EvidenceObjectClass.EXTRACT

    @property
    def object_id(self) -> str:
        return "eext-" + _sha({
            "owner": EVIDENCE_OWNER, "class": self.object_class,
            "artifact_id": self.artifact_id, "occurrence_id": self.occurrence_id,
            "locator_kind": self.locator_kind, "locator": self.locator,
            "content_sha256": self.content_sha256,
        })

    def _semantic_payload(self) -> dict:
        return {
            "artifact_id": self.artifact_id,
            "occurrence_id": self.occurrence_id,
            "locator_kind": self.locator_kind, "locator": self.locator,
            "language": self.language, "content": self.content,
            "content_sha256": self.content_sha256,
        }


EvidenceObject = EvidenceSource | EvidenceArtifact | EvidenceOccurrence | EvidenceExtract


@dataclass(frozen=True, slots=True, order=True)
class EvidenceRelationship:
    source_class: EvidenceObjectClass
    source_id: str
    kind: EvidenceRelationshipKind
    role: str
    ordinal: int
    target_class: EvidenceObjectClass
    target_id: str


@dataclass(frozen=True, slots=True, order=True)
class EvidenceSnapshotMember:
    object_class: EvidenceObjectClass
    object_id: str
    object_digest: str


@dataclass(frozen=True, slots=True)
class EvidenceSnapshotManifest:
    owner: str
    contract_version: str
    snapshot_version: str
    snapshot_id: str
    snapshot_digest: str
    acquisition_corpus_id: str | None
    acquisition_corpus_digest: str | None
    members: tuple[EvidenceSnapshotMember, ...]
    relationships: tuple[EvidenceRelationship, ...]

    def to_dict(self) -> dict:
        return _canonical(self)

    def to_json(self) -> str:
        return canonical_evidence_json(self)


@dataclass(frozen=True, slots=True)
class EvidenceSnapshot:
    contract_version: str
    snapshot_version: str
    snapshot_id: str
    snapshot_digest: str
    acquisition_corpus_id: str | None
    acquisition_corpus_digest: str | None
    objects: tuple[EvidenceObject, ...]
    manifest: EvidenceSnapshotManifest

    def __post_init__(self) -> None:
        validate_evidence_snapshot(self)

    def to_dict(self) -> dict:
        return _canonical(self)

    def to_json(self) -> str:
        return canonical_evidence_json(self)


def _object_key(value: EvidenceObject):
    return (_CLASS_ORDER[value.object_class], value.object_id)


def _intrinsic_relationships(value: EvidenceObject) -> tuple[RelationshipTarget, ...]:
    if isinstance(value, EvidenceArtifact):
        return (RelationshipTarget(
            EvidenceRelationshipKind.ATTRIBUTABLE_SOURCE, "source", EvidenceObjectClass.SOURCE,
            value.source_id),)
    if isinstance(value, EvidenceOccurrence):
        return tuple(sorted((
            RelationshipTarget(EvidenceRelationshipKind.ATTRIBUTABLE_SOURCE, "source",
                               EvidenceObjectClass.SOURCE, value.source_id),
            RelationshipTarget(EvidenceRelationshipKind.ARTIFACT_OCCURRENCE, "artifact",
                               EvidenceObjectClass.ARTIFACT, value.artifact_id),
        ), key=lambda item: (item.kind.value, item.role, item.ordinal,
                             _CLASS_ORDER[item.target_class], item.target_id)))
    if isinstance(value, EvidenceExtract):
        return tuple(sorted((
            RelationshipTarget(EvidenceRelationshipKind.EXTRACT_ARTIFACT, "artifact",
                               EvidenceObjectClass.ARTIFACT, value.artifact_id),
            RelationshipTarget(EvidenceRelationshipKind.EXTRACT_OCCURRENCE, "occurrence",
                               EvidenceObjectClass.OCCURRENCE, value.occurrence_id),
        ), key=lambda item: (item.kind.value, item.role, item.ordinal,
                             _CLASS_ORDER[item.target_class], item.target_id)))
    return ()


def _all_targets(value: EvidenceObject) -> tuple[RelationshipTarget, ...]:
    combined = _intrinsic_relationships(value) + value.relationships
    ordered = tuple(sorted(combined, key=lambda item: (
        item.kind.value, item.role, item.ordinal,
        _CLASS_ORDER[item.target_class], item.target_id)))
    if len(ordered) != len(set(ordered)):
        _fail(EvidenceFailureCode.INVALID_RELATIONSHIP,
              f"duplicate relationship on {value.object_id}")
    return ordered


def _materialize_relationships(objects: tuple[EvidenceObject, ...]) -> tuple[EvidenceRelationship, ...]:
    result = []
    for value in objects:
        for target in _all_targets(value):
            result.append(EvidenceRelationship(
                value.object_class, value.object_id, target.kind, target.role,
                target.ordinal, target.target_class, target.target_id))
    return tuple(sorted(result, key=lambda item: (
        _CLASS_ORDER[item.source_class], item.source_id, item.kind.value,
        item.role, item.ordinal, _CLASS_ORDER[item.target_class], item.target_id)))


def _snapshot_payload(*, acquisition_corpus_id: str | None,
                      acquisition_corpus_digest: str | None,
                      members: tuple[EvidenceSnapshotMember, ...],
                      relationships: tuple[EvidenceRelationship, ...]) -> dict:
    return {
        "owner": EVIDENCE_OWNER,
        "contract_version": EVIDENCE_CONTRACT_VERSION,
        "snapshot_version": EVIDENCE_SNAPSHOT_VERSION,
        "acquisition_corpus_id": acquisition_corpus_id,
        "acquisition_corpus_digest": acquisition_corpus_digest,
        "members": members,
        "relationships": relationships,
    }


def create_evidence_snapshot(
        objects: Iterable[EvidenceObject], *,
        acquisition_corpus_id: str | None = None,
        acquisition_corpus_digest: str | None = None) -> EvidenceSnapshot:
    values = tuple(objects)
    if not values or any(not isinstance(item, _EvidenceObject) for item in values):
        _fail(EvidenceFailureCode.INCOMPLETE_SNAPSHOT,
              "snapshot requires Evidence owner objects")
    values = tuple(sorted(values, key=_object_key))
    identities = tuple((item.object_class, item.object_id) for item in values)
    if len(identities) != len(set(identities)):
        _fail(EvidenceFailureCode.DUPLICATE_IDENTITY,
              "snapshot object identities must be unique")
    if (acquisition_corpus_id is None) != (acquisition_corpus_digest is None):
        _fail(EvidenceFailureCode.INCOMPLETE_SNAPSHOT,
              "acquisition corpus identity and digest must be supplied together")
    if acquisition_corpus_id is not None:
        _identifier(acquisition_corpus_id, "acquisition_corpus_id")
        _digest(acquisition_corpus_digest, "acquisition_corpus_digest")

    index = {identity: item for identity, item in zip(identities, values)}
    source_ids = {item.object_id for item in values if isinstance(item, EvidenceSource)}
    artifact_ids = {item.object_id for item in values if isinstance(item, EvidenceArtifact)}
    occurrence_ids = {item.object_id for item in values if isinstance(item, EvidenceOccurrence)}
    for item in values:
        for target in _all_targets(item):
            if (target.target_class, target.target_id) not in index:
                _fail(EvidenceFailureCode.INCOMPLETE_PROVENANCE,
                      f"relationship target is outside snapshot: {target.target_id}")
            if target.kind in {EvidenceRelationshipKind.TRANSLATION,
                               EvidenceRelationshipKind.EQUIVALENT,
                               EvidenceRelationshipKind.SUPERSEDES} and target.target_class is not item.object_class:
                _fail(EvidenceFailureCode.INVALID_RELATIONSHIP,
                      f"{target.kind.value} must target the same object class")
            if target.target_id == item.object_id:
                _fail(EvidenceFailureCode.INVALID_RELATIONSHIP,
                      "an Evidence relationship cannot target itself")
        if isinstance(item, EvidenceArtifact) and item.source_id not in source_ids:
            _fail(EvidenceFailureCode.INCOMPLETE_PROVENANCE,
                  f"artifact source is missing: {item.source_id}")
        if isinstance(item, EvidenceOccurrence):
            if item.source_id not in source_ids or item.artifact_id not in artifact_ids:
                _fail(EvidenceFailureCode.INCOMPLETE_PROVENANCE,
                      f"occurrence provenance is incomplete: {item.object_id}")
            artifact = index[(EvidenceObjectClass.ARTIFACT, item.artifact_id)]
            if artifact.source_id != item.source_id or artifact.language != item.language:
                _fail(EvidenceFailureCode.INCOMPLETE_PROVENANCE,
                      f"occurrence provenance conflicts with artifact: {item.object_id}")
        if isinstance(item, EvidenceExtract):
            if item.artifact_id not in artifact_ids or item.occurrence_id not in occurrence_ids:
                _fail(EvidenceFailureCode.INCOMPLETE_PROVENANCE,
                      f"extract provenance is incomplete: {item.object_id}")
            occurrence = index[(EvidenceObjectClass.OCCURRENCE, item.occurrence_id)]
            if occurrence.artifact_id != item.artifact_id or occurrence.language != item.language:
                _fail(EvidenceFailureCode.INCOMPLETE_PROVENANCE,
                      f"extract provenance conflicts with occurrence: {item.object_id}")

    supersession = {
        item.object_id: tuple(target.target_id for target in _all_targets(item)
                              if target.kind is EvidenceRelationshipKind.SUPERSEDES)
        for item in values
    }
    visiting, visited = set(), set()
    def visit(node: str):
        if node in visiting:
            _fail(EvidenceFailureCode.SUPERSESSION_CYCLE,
                  "Evidence supersession relationships contain a cycle")
        if node in visited:
            return
        visiting.add(node)
        for target in supersession.get(node, ()):
            visit(target)
        visiting.remove(node)
        visited.add(node)
    for node in sorted(supersession):
        visit(node)

    members = tuple(EvidenceSnapshotMember(
        item.object_class, item.object_id, item.object_digest) for item in values)
    relationships = _materialize_relationships(values)
    payload = _snapshot_payload(
        acquisition_corpus_id=acquisition_corpus_id,
        acquisition_corpus_digest=acquisition_corpus_digest,
        members=members, relationships=relationships)
    snapshot_digest = _sha(payload)
    snapshot_id = "esnap-" + snapshot_digest
    manifest = EvidenceSnapshotManifest(
        EVIDENCE_OWNER, EVIDENCE_CONTRACT_VERSION, EVIDENCE_SNAPSHOT_VERSION,
        snapshot_id, snapshot_digest, acquisition_corpus_id,
        acquisition_corpus_digest, members, relationships)
    return EvidenceSnapshot(
        EVIDENCE_CONTRACT_VERSION, EVIDENCE_SNAPSHOT_VERSION,
        snapshot_id, snapshot_digest, acquisition_corpus_id,
        acquisition_corpus_digest, values, manifest)


def validate_evidence_snapshot(snapshot: EvidenceSnapshot) -> None:
    if not isinstance(snapshot, EvidenceSnapshot):
        _fail(EvidenceFailureCode.INVALID_VALUE, "value is not an EvidenceSnapshot")
    if snapshot.contract_version != EVIDENCE_CONTRACT_VERSION or snapshot.snapshot_version != EVIDENCE_SNAPSHOT_VERSION:
        _fail(EvidenceFailureCode.UNSUPPORTED_VERSION, "Evidence snapshot version is unsupported")
    if (not isinstance(snapshot.objects, tuple)
            or not snapshot.objects
            or any(not isinstance(item, _EvidenceObject) for item in snapshot.objects)):
        _fail(EvidenceFailureCode.INCOMPLETE_SNAPSHOT,
              "snapshot requires an immutable tuple of Evidence objects")
    identities = tuple((item.object_class, item.object_id) for item in snapshot.objects)
    if len(identities) != len(set(identities)):
        _fail(EvidenceFailureCode.DUPLICATE_IDENTITY,
              "snapshot object identities must be unique")
    if (snapshot.acquisition_corpus_id is None) != (snapshot.acquisition_corpus_digest is None):
        _fail(EvidenceFailureCode.INCOMPLETE_SNAPSHOT,
              "acquisition corpus identity and digest must be supplied together")
    if snapshot.acquisition_corpus_id is not None:
        _identifier(snapshot.acquisition_corpus_id, "acquisition_corpus_id")
        _digest(snapshot.acquisition_corpus_digest, "acquisition_corpus_digest")
    index = {(item.object_class, item.object_id): item for item in snapshot.objects}
    for item in snapshot.objects:
        for target in _all_targets(item):
            target_value = index.get((target.target_class, target.target_id))
            if target_value is None:
                _fail(EvidenceFailureCode.INCOMPLETE_PROVENANCE,
                      f"relationship target is outside snapshot: {target.target_id}")
            if target.kind in {EvidenceRelationshipKind.TRANSLATION,
                               EvidenceRelationshipKind.EQUIVALENT,
                               EvidenceRelationshipKind.SUPERSEDES} and target.target_class is not item.object_class:
                _fail(EvidenceFailureCode.INVALID_RELATIONSHIP,
                      f"{target.kind.value} must target the same object class")
            if target.target_id == item.object_id:
                _fail(EvidenceFailureCode.INVALID_RELATIONSHIP,
                      "an Evidence relationship cannot target itself")
        if isinstance(item, EvidenceArtifact):
            source = index.get((EvidenceObjectClass.SOURCE, item.source_id))
            if source is None:
                _fail(EvidenceFailureCode.INCOMPLETE_PROVENANCE,
                      f"artifact source is missing: {item.source_id}")
        elif isinstance(item, EvidenceOccurrence):
            source = index.get((EvidenceObjectClass.SOURCE, item.source_id))
            artifact = index.get((EvidenceObjectClass.ARTIFACT, item.artifact_id))
            if source is None or artifact is None or artifact.source_id != item.source_id or artifact.language != item.language:
                _fail(EvidenceFailureCode.INCOMPLETE_PROVENANCE,
                      f"occurrence provenance is incomplete or inconsistent: {item.object_id}")
        elif isinstance(item, EvidenceExtract):
            artifact = index.get((EvidenceObjectClass.ARTIFACT, item.artifact_id))
            occurrence = index.get((EvidenceObjectClass.OCCURRENCE, item.occurrence_id))
            if (artifact is None or occurrence is None
                    or occurrence.artifact_id != item.artifact_id
                    or occurrence.language != item.language):
                _fail(EvidenceFailureCode.INCOMPLETE_PROVENANCE,
                      f"extract provenance is incomplete or inconsistent: {item.object_id}")
    supersession = {
        item.object_id: tuple(target.target_id for target in _all_targets(item)
                              if target.kind is EvidenceRelationshipKind.SUPERSEDES)
        for item in snapshot.objects
    }
    visiting, visited = set(), set()
    def visit(node: str):
        if node in visiting:
            _fail(EvidenceFailureCode.SUPERSESSION_CYCLE,
                  "Evidence supersession relationships contain a cycle")
        if node in visited:
            return
        visiting.add(node)
        for target in supersession.get(node, ()):
            visit(target)
        visiting.remove(node)
        visited.add(node)
    for node in sorted(supersession):
        visit(node)
    members = tuple(EvidenceSnapshotMember(
        item.object_class, item.object_id, item.object_digest) for item in snapshot.objects)
    relationships = _materialize_relationships(snapshot.objects)
    payload = _snapshot_payload(
        acquisition_corpus_id=snapshot.acquisition_corpus_id,
        acquisition_corpus_digest=snapshot.acquisition_corpus_digest,
        members=members, relationships=relationships)
    digest = _sha(payload)
    manifest = EvidenceSnapshotManifest(
        EVIDENCE_OWNER, EVIDENCE_CONTRACT_VERSION, EVIDENCE_SNAPSHOT_VERSION,
        "esnap-" + digest, digest, snapshot.acquisition_corpus_id,
        snapshot.acquisition_corpus_digest, members, relationships)
    if tuple(sorted(snapshot.objects, key=_object_key)) != snapshot.objects:
        _fail(EvidenceFailureCode.INCOMPLETE_SNAPSHOT,
              "snapshot membership is not canonically ordered")
    if (snapshot.snapshot_id != "esnap-" + digest
            or snapshot.snapshot_digest != digest
            or snapshot.manifest != manifest):
        _fail(EvidenceFailureCode.DIGEST_MISMATCH,
              "Evidence snapshot identity, digest, membership, or manifest is invalid")


__all__ = [
    "ArtifactKind", "AuthenticityState", "EVIDENCE_CONTRACT_VERSION",
    "EVIDENCE_OWNER", "EVIDENCE_SNAPSHOT_VERSION", "EvidenceArtifact",
    "EvidenceExtract", "EvidenceFailureCode", "EvidenceObjectClass",
    "EvidenceOccurrence", "EvidenceRelationship", "EvidenceRelationshipKind",
    "EvidenceSnapshot", "EvidenceSnapshotManifest", "EvidenceSnapshotMember",
    "EvidenceSource", "EvidenceValidationError", "LocatorKind",
    "RelationshipTarget", "SourceKind", "canonical_evidence_json",
    "create_evidence_snapshot", "validate_evidence_snapshot",
]
