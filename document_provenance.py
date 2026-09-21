"""
document_provenance.py -- Full-Package Analysis Integrity Remediation
(Defect E + package completeness, task section 8).

CANONICAL SOURCE LAYER: document identity, version/amendment relationships,
duplicate-representation detection, and package-completeness assessment.
Pure, deterministic, no I/O, no model call -- operates ONLY on already-
available document names/typed_observations/doc_metadata, never fetches or
re-parses file content itself.

This is a genuinely separate conceptual layer from procurement_
normalization.py's CANONICAL PROCUREMENT INTELLIGENCE (requirements/
evaluation/milestones/scope) -- a future specialist "procurement/document
structure" analyzer would own exactly this module's surface and nothing
else, while a future "requirements/compliance" or "evaluation criteria"
specialist would consume this module's OUTPUT (document relationships,
completeness) as already-resolved context, never re-deriving it.

Does not reuse or duplicate migrations/010_procurement_revision_
governance.sql's heavier, human-reviewed document-relationship model
(`procurement_update_review_documents.role`, `procurement_changes`) --
that system governs how an APPROVED procurement update is applied to
canonical requirements after human review; this module classifies raw
uploaded documents' likely relationships BEFORE any such review, purely
to make Fast Analysis's own report/structured_intelligence honest about
what it is looking at. No schema change -- results are computed at
analysis time and stored inside the existing `structured_intelligence`
jsonb column, never a new table.
"""
from __future__ import annotations

import re

import scripts.fast_analysis_report_adapter as _fast_report_adapter

RELATIONSHIP_CANONICAL = "CANONICAL"
RELATIONSHIP_AMENDS = "AMENDS"
RELATIONSHIP_AMENDED_BY = "AMENDED_BY"
RELATIONSHIP_SUPERSEDES = "SUPERSEDES"
RELATIONSHIP_SUPERSEDED_BY = "SUPERSEDED_BY"
RELATIONSHIP_DUPLICATE_REPRESENTATION = "DUPLICATE_REPRESENTATION"
RELATIONSHIP_REDUNDANT_DERIVATIVE = "REDUNDANT_DERIVATIVE"
RELATIONSHIP_TRANSLATION_EQUIVALENT = "TRANSLATION_EQUIVALENT"
RELATIONSHIP_INDEPENDENT_SOURCE = "INDEPENDENT_SOURCE"

RELATIONSHIP_VALUES = (
    RELATIONSHIP_CANONICAL, RELATIONSHIP_AMENDS, RELATIONSHIP_AMENDED_BY,
    RELATIONSHIP_SUPERSEDES, RELATIONSHIP_SUPERSEDED_BY,
    RELATIONSHIP_DUPLICATE_REPRESENTATION, RELATIONSHIP_REDUNDANT_DERIVATIVE,
    RELATIONSHIP_TRANSLATION_EQUIVALENT, RELATIONSHIP_INDEPENDENT_SOURCE,
)

_AMENDMENT_DIR_RE = re.compile(r'(?:^|/)amendment\s*0*(\d+)\b', re.IGNORECASE)
_ORIGINAL_DIR_RE = re.compile(r'(?:^|/)originalrevision\b', re.IGNORECASE)
_REVISED_WORD_RE = re.compile(r'\brevised\b', re.IGNORECASE)
_DERIVATIVE_NAME_RE = re.compile(r'^(abstract|summary|overview)\b', re.IGNORECASE)

_BASENAME_STOPWORDS = {
    "rfp", "dp", "form", "docx", "pdf", "xlsx", "appendix", "annexe",
    "revised", "response", "criteria", "rated",
}


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


_SHORT_IDENTIFIER_RE = re.compile(r'\b([a-z]\d{1,2})\b', re.IGNORECASE)


def _basename_words(name: str) -> frozenset:
    """Reuses fast_analysis_report_adapter's own significant-word
    tokenizer (the same primitive Defect B's requirement dedup reuses)
    for consistency, then additionally strips filename-specific noise
    words (file extensions, generic "form"/"appendix" boilerplate) that
    would otherwise dominate every filename's overlap score.

    ALSO separately captures short letter+digit identifiers (D1/D2/D3,
    B1/B2/B3, C1/C2/C3 ...) that the shared tokenizer's own >=4-character
    filter would otherwise silently drop -- these are exactly the tokens
    that distinguish "Appendix D1" from "Appendix D2", so losing them
    would make every category's response form look equally similar to
    every other category's, which is the one distinction this function
    must never blur."""
    base = _basename(name)
    words = _fast_report_adapter._fuzzy_word_set(base) - _BASENAME_STOPWORDS
    short_ids = {m.group(1).lower() for m in _SHORT_IDENTIFIER_RE.finditer(base)}
    return words | short_ids


def _short_identifiers(name: str) -> frozenset:
    return frozenset(m.group(1).lower() for m in _SHORT_IDENTIFIER_RE.finditer(_basename(name)))


def _basename_similarity(name_a: str, name_b: str) -> float:
    """Jaccard overlap of each name's own significant words -- used for
    ranking the BEST candidate match among several (unlike _is_near_
    duplicate's containment-based yes/no, filename matching needs a
    ranked score to pick the single most-similar counterpart).

    Guarded against the specific failure mode this caught live on the
    Bank of Canada corpus: "Appendix C1 - Minimum Qualification
    Requirements" and "Appendix C2 - Minimum Qualification Requirements"
    share 3 generic words ("minimum"/"qualification"/"requirements")
    against only 1 distinguishing token each ("c1"/"c2"), scoring 0.6
    Jaccard overall -- enough to falsely call them duplicates of EACH
    OTHER despite being genuinely different categories' forms. When BOTH
    names carry at least one short letter+digit identifier and those
    identifier SETS are completely disjoint (no shared identifier at
    all), the two are never considered similar, regardless of how much
    other generic text they share -- the identifier is exactly the
    signal a buyer's own naming convention uses to distinguish otherwise
    near-identical form names."""
    wa, wb = _basename_words(name_a), _basename_words(name_b)
    if not wa or not wb:
        return 0.0
    ids_a, ids_b = _short_identifiers(name_a), _short_identifiers(name_b)
    if ids_a and ids_b and not (ids_a & ids_b):
        return 0.0
    return len(wa & wb) / len(wa | wb)


def classify_document_relationships(document_names: list[str]) -> dict[str, dict]:
    """Deterministic, filename-pattern-based classification of how each
    document in the corpus likely relates to the others -- NEVER infers
    legal precedence beyond what the directory/filename convention itself
    states (e.g. an `Amendment1/` path explicitly amending an
    `OriginalRevision/` counterpart), and defaults every document that
    doesn't match a confident pattern to INDEPENDENT_SOURCE rather than
    guessing a relationship (instruction: "fail conservatively").

    Patterns recognized:
      - `AmendmentN/<file>` whose basename fuzzy-matches an
        `OriginalRevision/<file>` (or a bare, unprefixed) counterpart ->
        AMENDS that counterpart; the counterpart becomes AMENDED_BY.
      - A filename containing "REVISED" that fuzzy-matches a non-REVISED
        counterpart -> same AMENDS/AMENDED_BY pairing.
      - Two documents whose basenames are near-identical (>=0.6 Jaccard
        overlap of significant words) but neither is in an Amendment*/
        directory -> DUPLICATE_REPRESENTATION of each other (e.g. the
        same RFP uploaded as both a native PDF and a DOCX-converted PDF,
        or the same appendix uploaded once as a raw source file and once
        as an unprefixed "Submission" checklist placeholder).
      - A short, generic filename (abstract/summary/overview) that also
        has >=0.5 basename-word overlap with a longer, fuller document ->
        REDUNDANT_DERIVATIVE of that document.
      - Everything else -> INDEPENDENT_SOURCE.

    Returns {document_name: {"relationship": ..., "related_to": name|None,
    "confidence": "high"|"medium"}}. Every input name gets exactly one
    entry. Multiple relationships to the SAME name are never invented --
    each document gets its single best-supported classification."""
    result: dict[str, dict] = {
        name: {"relationship": RELATIONSHIP_INDEPENDENT_SOURCE, "related_to": None, "confidence": "low"}
        for name in document_names
    }
    claimed: set[str] = set()

    # Pass 1: explicit amendment/revision directory or filename markers.
    for name in document_names:
        if name in claimed:
            continue
        is_amendment_path = bool(_AMENDMENT_DIR_RE.search(name))
        is_revised_name = bool(_REVISED_WORD_RE.search(_basename(name)))
        if not (is_amendment_path or is_revised_name):
            continue
        best_match, best_score = None, 0.0
        for other in document_names:
            if other == name or other in claimed:
                continue
            if _AMENDMENT_DIR_RE.search(other) or _REVISED_WORD_RE.search(_basename(other)):
                continue  # never pair two amendment-looking files together
            score = _basename_similarity(name, other)
            if score > best_score:
                best_match, best_score = other, score
        if best_match and best_score >= 0.5:
            result[name] = {"relationship": RELATIONSHIP_AMENDS, "related_to": best_match, "confidence": "high"}
            result[best_match] = {"relationship": RELATIONSHIP_AMENDED_BY, "related_to": name, "confidence": "high"}
            claimed.add(name)
            claimed.add(best_match)

    # Pass 2: redundant derivative (short generic name deriving from a fuller document).
    for name in document_names:
        if name in claimed:
            continue
        if not _DERIVATIVE_NAME_RE.match(_basename(name)):
            continue
        best_match, best_score = None, 0.0
        for other in document_names:
            if other == name or other in claimed:
                continue
            score = _basename_similarity(name, other)
            if score > best_score:
                best_match, best_score = other, score
        if best_match and best_score >= 0.5:
            result[name] = {"relationship": RELATIONSHIP_REDUNDANT_DERIVATIVE, "related_to": best_match, "confidence": "medium"}
            claimed.add(name)

    # Pass 3: duplicate representation (near-identical basenames, neither already classified).
    for i, name in enumerate(document_names):
        if name in claimed:
            continue
        for other in document_names[i + 1:]:
            if other in claimed:
                continue
            score = _basename_similarity(name, other)
            if score >= 0.6:
                result[name] = {"relationship": RELATIONSHIP_DUPLICATE_REPRESENTATION, "related_to": other, "confidence": "medium"}
                result[other] = {"relationship": RELATIONSHIP_DUPLICATE_REPRESENTATION, "related_to": name, "confidence": "medium"}
                claimed.add(name)
                claimed.add(other)
                break

    return result


# ── Package completeness (task section 8) ────────────────────────────────

_MAIN_RFP_IDENTITY_KINDS = {"OPPORTUNITY_TITLE", "SOLICITATION_NUMBER", "BUYER_NAME", "DOCUMENT_TITLE"}
_SUPPORTING_DOC_HINTS = ("appendix", "addendum", "amendment", "schedule", "form", "annexe")


def assess_package_completeness(
    typed_observations: list[dict], requirements: list[dict], evaluation_present: bool,
    document_names: list[str],
) -> dict:
    """Bounded, deterministic package-completeness check (instruction 8)
    -- never blocks analysis, only surfaces a warning. "Confident primary
    solicitation identified" means: at least one IDENTITY-family
    observation naming the opportunity/solicitation/buyer exists AND at
    least one of (requirements present, evaluation criteria present) --
    a real RFP body, not just a title fragment. A corpus with only
    appendix/addendum/amendment-shaped filenames and no such signal is
    flagged, without attempting real document classification."""
    has_identity_signal = any(
        isinstance(o, dict) and o.get("family") == "IDENTITY"
        and (o.get("semantic_kind") in _MAIN_RFP_IDENTITY_KINDS)
        for o in typed_observations
    )
    has_substantive_body = bool(requirements) or evaluation_present
    looks_primary_identified = has_identity_signal and has_substantive_body

    only_supporting_docs = bool(document_names) and all(
        any(hint in name.lower() for hint in _SUPPORTING_DOC_HINTS) for name in document_names
    )

    is_complete = looks_primary_identified or not only_supporting_docs
    warning = None
    if not is_complete:
        warning = (
            "Possible incomplete procurement package: supporting documents/addenda were found, "
            "but no primary solicitation document was confidently identified."
        )
    return {
        "is_complete": is_complete,
        "warning": warning,
        "has_identity_signal": has_identity_signal,
        "has_substantive_body": has_substantive_body,
        "only_supporting_docs_present": only_supporting_docs,
    }
