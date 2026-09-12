"""Fail-closed translation from an ingested procurement corpus to Evidence.

The adapter consumes the existing ``(path, bytes)`` package representation and
the extractor's package metadata.  It adds no procurement meaning; all source
and acquisition attributes must already be present in supplied manifests.
"""

from __future__ import annotations

import mimetypes
import re
from datetime import date
from hashlib import sha256
from typing import Mapping, Sequence

from evidence import (
    ArtifactKind,
    AuthenticityState,
    EvidenceArtifact,
    EvidenceExtract,
    EvidenceOccurrence,
    EvidenceSnapshot,
    EvidenceSource,
    LocatorKind,
    SourceKind,
    create_evidence_snapshot,
)


class ProcurementEvidenceAdapterError(ValueError):
    """The ingested corpus cannot be translated without invention or repair."""


_MARKER = re.compile(r"(?m)^\[\[SOURCE:\s*(.*?)\]\](?:[ \t]*)")
_ROLE_KIND = {
    "MASTER_RFP": ArtifactKind.DOCUMENT,
    "PROCUREMENT_ATTACHMENT": ArtifactKind.DOCUMENT,
    "NOTICE_AND_DOCUMENT_INVENTORY": ArtifactKind.NOTICE,
    "AMENDMENT": ArtifactKind.AMENDMENT,
}


def _required(mapping: Mapping, key: str):
    value = mapping.get(key)
    if value is None or value == "":
        raise ProcurementEvidenceAdapterError(f"missing required corpus metadata: {key}")
    return value


def _parse_date(value: object, field: str) -> date:
    if not isinstance(value, str):
        raise ProcurementEvidenceAdapterError(f"{field} must be an ISO calendar date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ProcurementEvidenceAdapterError(f"{field} must be an ISO calendar date") from exc
    return parsed


def _language(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProcurementEvidenceAdapterError("corpus language is required")
    aliases = {"English": "en", "French": "fr"}
    return aliases.get(value, value)


def _mime(path: str) -> str:
    value = mimetypes.guess_type(path)[0]
    if value is None:
        raise ProcurementEvidenceAdapterError(f"media type is unavailable for {path}")
    return value


def _marker_parts(body: str) -> tuple[str, dict[str, str], tuple[str, ...]]:
    parts = tuple(part.strip() for part in body.split("|"))
    filename = parts[0]
    attributes: dict[str, str] = {}
    flags: list[str] = []
    for part in parts[1:]:
        if ":" in part:
            key, value = part.split(":", 1)
            attributes[key.strip().upper()] = value.strip()
        elif part:
            flags.append(part.upper())
    return filename, attributes, tuple(flags)


def _locator(body: str) -> tuple[LocatorKind, str]:
    _, attributes, flags = _marker_parts(body)
    if "PAGE" in attributes and attributes["PAGE"].isdigit():
        return LocatorKind.PAGE, f"page:{attributes['PAGE']}"
    if "SECTION" in attributes:
        return LocatorKind.SECTION, f"section:{attributes['SECTION']}"
    if "SHEET" in attributes and "ROWS" in attributes:
        return LocatorKind.RECORD, f"record:sheet={attributes['SHEET']};rows={attributes['ROWS']}"
    if "ROWS" in attributes:
        return LocatorKind.RECORD, f"record:rows={attributes['ROWS']}"
    if flags:
        return LocatorKind.OTHER_EXACT, "exact:" + "|".join(flags)
    return LocatorKind.OTHER_EXACT, "exact:source-marker"


def _fragments(text: str, expected_path: str):
    matches = tuple(_MARKER.finditer(text))
    if not matches:
        raise ProcurementEvidenceAdapterError(f"no attributable source marker in {expected_path}")
    for index, match in enumerate(matches):
        body = match.group(1)
        filename, _, _ = _marker_parts(body)
        if filename != expected_path:
            raise ProcurementEvidenceAdapterError(
                f"source marker mismatch for {expected_path}: {filename}")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        content = text[match.end():end]
        if content.startswith("\n"):
            content = content[1:]
        content = content.rstrip("\n")
        yield match.start(), *_locator(body), content or None


def adapt_procurement_corpus(
    package_files: Sequence[tuple[str, bytes]],
    package_metadata: Mapping,
    corpus_manifest: Mapping,
    acquisition_manifest: Mapping,
    source_manifest: Mapping,
) -> EvidenceSnapshot:
    """Translate one already-ingested package into an immutable Evidence snapshot."""
    corpus_id = _required(corpus_manifest, "corpus_id")
    acquisition_date = _parse_date(
        _required(acquisition_manifest, "retrieved_on"), "retrieved_on")
    language = _language(_required(corpus_manifest, "language"))
    source_key = _required(source_manifest, "source_id")
    source_name = _required(source_manifest, "publisher_name")
    source_uri = _required(source_manifest, "base_url")
    source = EvidenceSource(source_key, source_name, SourceKind.ORGANIZATION, source_uri)

    declared_entries = _required(corpus_manifest, "files")
    declared = {_required(item, "path"): item for item in declared_entries}
    if len(declared) != len(declared_entries):
        raise ProcurementEvidenceAdapterError("duplicate manifest paths are not permitted")
    raw = dict(package_files)
    names = tuple(package_metadata.get("files", ()))
    texts = package_metadata.get("doc_texts")
    if not isinstance(texts, Mapping) or set(raw) != set(declared) or set(raw) != set(names) or set(raw) != set(texts):
        raise ProcurementEvidenceAdapterError("corpus files, manifest, and extracted metadata must match exactly")
    if len(raw) != len(package_files):
        raise ProcurementEvidenceAdapterError("duplicate corpus paths are not permitted")

    objects = [source]
    aggregate = sha256()
    for entry in declared_entries:
        aggregate.update(_required(entry, "sha256").encode("ascii"))
    for path in sorted(raw):
        payload = raw[path]
        if not isinstance(payload, bytes):
            raise ProcurementEvidenceAdapterError(f"corpus payload must be bytes: {path}")
        entry = declared[path]
        digest = sha256(payload).hexdigest()
        if digest != _required(entry, "sha256") or len(payload) != _required(entry, "bytes"):
            raise ProcurementEvidenceAdapterError(f"manifest integrity mismatch: {path}")
        role = _required(entry, "role")
        if role not in _ROLE_KIND:
            raise ProcurementEvidenceAdapterError(f"unsupported declared artifact role: {role}")
        artifact = EvidenceArtifact(
            source.object_id, _ROLE_KIND[role], path, digest, _mime(path), language,
            digest, payload)
        objects.append(artifact)
        for offset, locator_kind, locator, content in _fragments(texts[path], path):
            occurrence = EvidenceOccurrence(
                source.object_id, artifact.object_id, f"{digest}:{offset}",
                locator_kind, locator, language, acquisition_date,
                AuthenticityState.VERIFIED, digest)
            objects.append(occurrence)
            if content is not None:
                extract_digest = sha256(content.encode("utf-8")).hexdigest()
                objects.append(EvidenceExtract(
                    artifact.object_id, occurrence.object_id, locator_kind, locator,
                    language, content, extract_digest))

    corpus_digest = aggregate.hexdigest()
    declared_digest = acquisition_manifest.get("procurement_package", {}).get("aggregate_sha256")
    if declared_digest is not None and corpus_digest != declared_digest:
        raise ProcurementEvidenceAdapterError("procurement corpus aggregate digest mismatch")
    return create_evidence_snapshot(
        objects, acquisition_corpus_id=corpus_id,
        acquisition_corpus_digest=corpus_digest)
