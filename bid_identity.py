"""Phoenix Beta: bid identity (opportunity title / issuing organization)
taken from a completed FAST analysis, for bids created by the upload-only
New Bid Ingestion flow.

A bid created from an upload starts with the clear temporary values below.
When its FAST run completes, the identity FAST already extracted
(``doc_metadata`` per document, resolved through the canonical identity
merge used by the FAST report) replaces a temporary value -- and only a
temporary value, so a title or client the user has already typed is never
overwritten. No additional model call is made.

Fail-safe rule: a value is used only if it is grounded in the uploaded
documents' own text. The issuing organization must appear verbatim
(case/whitespace-insensitive); the title must have nearly all of its words
present. Anything else is treated as uncertain and the temporary value is
kept -- a client name is never invented.
"""
from __future__ import annotations

import re

PLACEHOLDER_TITLE = "Untitled Opportunity"
PLACEHOLDER_CLIENT = "Organization not identified"

_MAX_TITLE = 250
_MAX_CLIENT = 150
_TITLE_MIN_WORD_COVERAGE = 0.8


def _norm(text: str) -> str:
    text = (text or "").lower().replace("’", "'").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip()


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", _norm(text)) if len(w) > 2]


def _clean(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = re.sub(r"\s+", " ", value).strip().strip("\"'").strip()
    return value or None


def grounded_identity(merged_identity: dict, corpus_texts: list[str]) -> dict:
    """Return {"title": str|None, "client": str|None}: each value only if it
    is grounded in the corpus text, else None (uncertain)."""
    corpus = _norm(" ".join(t for t in corpus_texts if isinstance(t, str)))
    corpus_words = set(_words(corpus))
    out = {"title": None, "client": None}

    title = _clean((merged_identity or {}).get("title"))
    if title and len(title) <= _MAX_TITLE and _norm(title) not in (_norm(PLACEHOLDER_TITLE),):
        words = _words(title)
        if words and sum(1 for w in words if w in corpus_words) / len(words) >= _TITLE_MIN_WORD_COVERAGE:
            out["title"] = title

    client = _clean((merged_identity or {}).get("client"))
    if client and len(client) <= _MAX_CLIENT and _norm(client) != _norm(PLACEHOLDER_CLIENT):
        if _norm(client) in corpus:
            out["client"] = client
    return out


def resolve_from_fast_result(result, corpus_texts: list[str]) -> dict:
    """Grounded identity from a FastAnalysisResult, using the same canonical
    identity merge the FAST report uses (no model call)."""
    from scripts.fast_analysis_report_adapter import _merged_doc_metadata
    return grounded_identity(_merged_doc_metadata(result), corpus_texts)
