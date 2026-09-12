"""Shared physical-evidence grounding logic for the independent Evidence
Publication binding adapters (canonical_observation_binding.py,
opportunity_structure_binding.py).

Both modules previously carried their own, near-identical copies of this
matching logic. That duplication was a demonstrated defect source: a fix
applied to one module's excerpt-comparison tolerance silently left the other
module's copy stale (see BANK_OF_CANADA_PROVENANCE_GRANULARITY_REMEDIATION_
REPORT.md). This module is now the single implementation both binding
adapters call into; each still raises its own domain-specific error type via
the `fail` callback it supplies, so their public exception contracts are
unchanged.

This module adds no procurement meaning and invents no evidence or
provenance. It answers exactly two independently-provable questions for
each source_ref:

1. Does the ref's claimed locator (page / section / sheet+rows / rows)
   exist as a real, already-published EvidenceOccurrence for the correct
   document? (exact physical locator match)
2. Failing that -- and ONLY when the ref carries an excerpt -- does the
   ref's excerpt appear, verbatim (whitespace-insensitively), inside
   exactly one real, already-published EvidenceExtract for the correct
   document, regardless of which occurrence published it? (coarser-locator
   fallback, "Model 2 / hierarchical": a finer semantic label Stage A cited
   may bind to a coarser real physical extract when the excerpt itself
   independently, unambiguously proves the association -- the locator
   STRING never substitutes for or coerces a different locator's identity;
   only the excerpt's own verbatim presence can do that, and only when it
   is unambiguous.)

A ref that fails both never receives a fabricated binding. This module never
decides whether that failure is fatal for the caller (a genuine anomaly, or
a record already honestly declared PARTIAL/UNVERIFIED upstream) -- that
policy remains in each caller's own build_*_bindings() function, unchanged.
"""
from __future__ import annotations

from typing import Callable, Mapping

from evidence import EvidenceExtract, EvidenceOccurrence

NoReturn = None  # fail() is documented to never return; callers raise inside it.


def normalize_locator_text(value: str) -> str:
    """Whitespace-collapsing, case-insensitive comparison for locator free
    text (section/sheet names). Preserves word boundaries -- appropriate for
    matching a locator's own identity, never for excerpt content."""
    return " ".join(str(value).split()).casefold()


def normalize_excerpt_text(value: str) -> str:
    """Whitespace-insensitive comparison for excerpt verbatim-matching only.

    PDF/DOCX text extraction routinely reflows incidental whitespace around
    a hyphenated line-wrap ("one-\\nyear" -> "one- year") or drops a space a
    human would read after label punctuation ("Duration:3 years"). Neither
    changes the words present. Locator text keeps using
    normalize_locator_text (word-boundary-preserving); only excerpt content
    uses this stricter-looking but semantically-equivalent, whitespace-blind
    comparison.
    """
    return "".join(str(value).split()).casefold()


def normalized_locator(locator_kind: str, locator: str) -> str:
    """Normalize the free-text component (section or sheet name) of an
    already-formatted locator string the same way canonical_opportunity.py's
    own _locator_matches normalizes the same text before comparing it.
    Page numbers and row ranges are not free text and are left unchanged.
    """
    if locator_kind == "SECTION" and locator.startswith("section:"):
        return "section:" + normalize_locator_text(locator[len("section:"):])
    if locator_kind == "RECORD" and locator.startswith("record:sheet="):
        body = locator[len("record:sheet="):]
        sheet_part, sep, rest = body.partition(";rows=")
        if sep:
            return f"record:sheet={normalize_locator_text(sheet_part)};rows={rest}"
    return locator


def locator_for_ref(ref: Mapping):
    """Reproduce procurement_evidence_adapter._locator's exact priority
    order (page, then section, then sheet+rows, then rows) from an
    already-cleaned source_ref. Returns None when the ref does not carry
    enough coordinate information to derive an adapter-equivalent exact
    locator (e.g. a bare sheet name with no row range) -- the caller must
    either resolve it by an unambiguous, within-artifact fallback or fail
    closed, never guess a locator.
    """
    page = ref.get("page")
    if page is not None:
        page_text = str(page).strip()
        if page_text.isdigit():
            return ("PAGE", f"page:{int(page_text)}")
    section = ref.get("section")
    if isinstance(section, str) and section.strip():
        return ("SECTION", f"section:{normalize_locator_text(section)}")
    sheet = ref.get("sheet")
    rows = ref.get("rows") or ref.get("row_range") or ref.get("range")
    if isinstance(sheet, str) and sheet.strip() and rows not in (None, ""):
        return ("RECORD", f"record:sheet={normalize_locator_text(sheet)};rows={rows}")
    if rows not in (None, ""):
        return ("RECORD", f"record:rows={rows}")
    return None


def sheet_only_candidates(ref: Mapping, artifact_id: str,
                          occurrences_by_artifact: Mapping[str, list]):
    """Fallback for a ref that names a sheet but not a row range (Stage A's
    typed-observation source_refs schema has no "rows" field, so this is the
    normal shape for a spreadsheet-sourced observation, not malformed
    input). Never guesses across ambiguity: returns every RECORD occurrence
    in the SAME artifact whose locator's sheet component, once normalized,
    exactly equals the ref's normalized sheet name, regardless of row
    range. The caller still fails closed unless that search yields exactly
    one occurrence.
    """
    sheet = ref.get("sheet")
    if not isinstance(sheet, str) or not sheet.strip():
        return None
    if ref.get("page") is not None or (isinstance(ref.get("section"), str) and ref["section"].strip()):
        return None
    prefix = f"record:sheet={normalize_locator_text(sheet)};rows="
    return [
        occurrence for occurrence in occurrences_by_artifact.get(artifact_id, ())
        if occurrence.locator_kind.value == "RECORD"
        and normalized_locator("RECORD", occurrence.locator).startswith(prefix)
    ]


def build_locator_index(evidence_snapshot):
    """Return the four lookup structures every match_refs() call needs,
    built once per Evidence snapshot."""
    from evidence import EvidenceArtifact

    artifact_id_by_filename: dict[str, str] = {}
    for item in evidence_snapshot.objects:
        if isinstance(item, EvidenceArtifact):
            if item.title in artifact_id_by_filename and artifact_id_by_filename[item.title] != item.object_id:
                raise ValueError(f"multiple Evidence artifacts declare the same filename {item.title!r}; ambiguous")
            artifact_id_by_filename[item.title] = item.object_id

    occurrences_by_locator: dict[tuple[str, str, str], list[EvidenceOccurrence]] = {}
    occurrences_by_artifact: dict[str, list[EvidenceOccurrence]] = {}
    for item in evidence_snapshot.objects:
        if isinstance(item, EvidenceOccurrence):
            occurrences_by_locator.setdefault(
                (item.artifact_id, item.locator_kind.value,
                 normalized_locator(item.locator_kind.value, item.locator)), []).append(item)
            occurrences_by_artifact.setdefault(item.artifact_id, []).append(item)

    extracts_by_occurrence: dict[str, list[EvidenceExtract]] = {}
    for item in evidence_snapshot.objects:
        if isinstance(item, EvidenceExtract):
            extracts_by_occurrence.setdefault(item.occurrence_id, []).append(item)

    return artifact_id_by_filename, occurrences_by_locator, occurrences_by_artifact, extracts_by_occurrence


def match_refs(entity_id: str, refs: list, index: tuple,
               fail: Callable[[str, str], None]) -> tuple[set, set]:
    """Match every ref in `refs` to real, already-published Evidence
    occurrences/extracts. Returns (matched_extract_ids, matched_occurrence_ids).

    `fail(entity_id, reason)` must raise -- the caller's own domain error
    type -- and never return; this function does not catch it.
    """
    artifact_id_by_filename, occurrences_by_locator, occurrences_by_artifact, extracts_by_occurrence = index
    matched_occurrence_ids: set[str] = set()
    matched_extract_ids: set[str] = set()

    for ref in refs:
        source_doc = ref.get("source_doc")
        if not isinstance(source_doc, str) or source_doc not in artifact_id_by_filename:
            fail(entity_id, f"source document not found among Evidence artifacts: {source_doc!r}")
        artifact_id = artifact_id_by_filename[source_doc]

        excerpt = ref.get("excerpt")
        has_excerpt = isinstance(excerpt, str) and bool(excerpt.strip())

        locator = locator_for_ref(ref)
        if locator is not None:
            locator_kind, locator_str = locator
            candidates = occurrences_by_locator.get((artifact_id, locator_kind, locator_str), [])
            describe = f"{locator_kind}:{locator_str}"
        else:
            candidates = sheet_only_candidates(ref, artifact_id, occurrences_by_artifact)
            if candidates is None:
                fail(entity_id, f"ref does not carry a locator this adapter can resolve without guessing: {ref!r}")
            describe = f"sheet={ref.get('sheet')!r} (no row range stated)"

        if len(candidates) > 1:
            fail(entity_id, f"{len(candidates)} Evidence occurrences match {describe} "
                            f"in {source_doc!r}; ambiguous, refusing to choose")

        # The coarser-locator fallback applies only to SECTION: a free-text,
        # structurally un-enumerable dimension where a real, correctly-cited
        # heading may simply never have been emitted as its own marker (the
        # actual, confirmed shape of this defect -- see
        # BANK_OF_CANADA_PROVENANCE_GRANULARITY_REMEDIATION_REPORT.md). PAGE
        # and RECORD (sheet+rows) are bounded, enumerable coordinates already
        # validated elsewhere (Stage B's validate_source_refs checks page
        # bounds and sheet existence); a page/row citation that does not
        # match any real occurrence is a genuine citation error, not coarser
        # precision, and must keep failing closed exactly as before -- an
        # excerpt happening to also appear in some unrelated real occurrence
        # must never rescue a wrong page number.
        if len(candidates) == 1:
            occurrence = candidates[0]
        elif has_excerpt and locator is not None and locator[0] == "SECTION":
            # Coarser-locator fallback (Model 2): the exact requested
            # locator does not exist as a real published occurrence, but a
            # coarser real occurrence for this SAME artifact may still,
            # independently, uniquely prove the citation via its own
            # extract text. The locator label itself never substitutes for
            # this -- only the excerpt's own unambiguous verbatim presence
            # can establish the relationship.
            normalized_excerpt = normalize_excerpt_text(excerpt)
            owners = [
                occ for occ in occurrences_by_artifact.get(artifact_id, [])
                if any(isinstance(extract.content, str)
                       and normalized_excerpt in normalize_excerpt_text(extract.content)
                       for extract in extracts_by_occurrence.get(occ.object_id, []))
            ]
            if len(owners) > 1:
                fail(entity_id, f"{len(owners)} distinct real Evidence occurrences in {source_doc!r} "
                                f"each independently ground the excerpt claimed for {describe}; "
                                f"ambiguous, refusing to choose a coarser owner")
            if not owners:
                fail(entity_id, f"no Evidence occurrence matches {describe} in {source_doc!r}, and "
                                f"the excerpt is not verbatim in any real occurrence for this document either")
            occurrence = owners[0]
            describe = f"{describe} (coarser real occurrence {occurrence.locator_kind.value}:{occurrence.locator})"
        else:
            fail(entity_id, f"no Evidence occurrence matches {describe} in {source_doc!r}")

        matched_occurrence_ids.add(occurrence.object_id)

        if has_excerpt:
            normalized_excerpt = normalize_excerpt_text(excerpt)
            confirmed = [
                extract for extract in extracts_by_occurrence.get(occurrence.object_id, [])
                if isinstance(extract.content, str) and normalized_excerpt in normalize_excerpt_text(extract.content)
            ]
            if not confirmed:
                fail(entity_id, f"excerpt not found verbatim in the Evidence extract for "
                                f"{describe} in {source_doc!r}")
            if len(confirmed) > 1:
                fail(entity_id, f"{len(confirmed)} Evidence extracts confirm the excerpt for "
                                f"{describe} in {source_doc!r}; ambiguous")
            matched_extract_ids.add(confirmed[0].object_id)

    if not matched_occurrence_ids:
        fail(entity_id, "no provenance could be established for any ref")
    if not matched_extract_ids:
        fail(entity_id, "no quoted evidence extract could be established for any ref "
                        "(every ref lacked a verifiable excerpt)")

    return matched_extract_ids, matched_occurrence_ids


__all__ = [
    "build_locator_index", "locator_for_ref", "match_refs", "normalize_excerpt_text",
    "normalize_locator_text", "normalized_locator", "sheet_only_candidates",
]
