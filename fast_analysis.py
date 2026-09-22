"""
Fast Analysis -- minimum viable intelligence extraction path.

A separate, sibling workflow to the governed Deep Verify pipeline
(extractor.py's extract_document_facts / Stage A-D). This module does NOT
modify, simplify, or replace that pipeline -- it reuses only pure,
side-effect-free, low-level parsing utilities from it (document text
extraction with source markers, marker-aware chunking, tolerant JSON
parsing) because those are safe, generic building blocks, not Deep Verify
behavior.

Design contract: FAST_ANALYSIS_MINIMUM_VIABLE_INTELLIGENCE_AUDIT.md.
Every design choice below cites the audit section it implements.

Architecture (audit S H):
    16-document corpus
        -> deterministic routing (per-document; audit S D)
        -> deterministic extraction where sufficient (page limits; audit S D/S 3)
        -> narrow, mode-specific LLM extraction otherwise (audit S F)
        -> bounded, targeted recovery only (audit S 8, no universal cascade)
        -> deterministic ambiguity detection (audit S 7, only the 3 known classes)
        -> report-content adapter -> same PDF renderer as Deep Verify's output
"""
from __future__ import annotations

import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, fields as _dataclass_fields
from datetime import datetime, timezone

from config import get_anthropic_client, execute_messages_create
from extractor import (
    chunk_document_text as _deep_chunk_document_text,  # reused: pure, generic, marker-aware
    _safe_parse_json_with_status,                       # reused: pure JSON tolerance, no Deep Verify behavior
)

# ---------------------------------------------------------------------------
# Configuration -- deliberately different from Deep Verify's, per audit S F/S 8.
# ---------------------------------------------------------------------------

FAST_MODEL = "claude-haiku-4-5-20251001"          # unchanged model (audit does not propose changing this)
FAST_TEMPERATURE = 0.0
FAST_MAX_OUTPUT_TOKENS = 4000                     # bounded and smaller than Deep Verify's 8000 (audit S 8)
FAST_MAX_CHUNK_CHARS = 24000                      # larger than Deep Verify's 12000: narrower schemas produce
                                                   # much less output per input character, so larger input
                                                   # chunks are safe without approaching the output ceiling --
                                                   # this is the primary lever that keeps master RFP's call
                                                   # count low (audit S G repeatedly identifies fixed-prompt
                                                   # resend and chunk count, not per-chunk depth, as the cost)

# ---------------------------------------------------------------------------
# Document routing (audit S D) -- deterministic, per the audit's own
# empirically-validated matrix. Every classification below cites the audit's
# reasoning for that specific document.
# ---------------------------------------------------------------------------

ROUTE_SKIP = "SKIP"                    # audit S D: redundant with the master RFP or filename-derivable
ROUTE_EVAL_ONLY = "EVAL_ONLY"          # audit S D: only evaluation_criteria is genuinely new content
ROUTE_IDENTITY_EVAL_REQ = "IDENTITY_EVAL_REQ"   # audit S D: master RFP -- the deep, schema-narrowed document
ROUTE_CONTRACT_NARROW = "CONTRACT_NARROW"       # audit S D: Appendix E -- pricing/contract-term narrative only
ROUTE_COMMERCIAL_ONLY = "COMMERCIAL_ONLY"       # audit S D: Appendix G -- commercial_clauses is the payload

# Filenames match the authoritative Bank of Canada RFP 2026-026 corpus this
# audit was built against (corrected_corpus_manifest.json). Fast Analysis v1
# is validated against this corpus; routing a document not in this table
# falls back to ROUTE_IDENTITY_EVAL_REQ (the safest, broadest narrow mode)
# rather than silently skipping unknown content -- see route_document().
DOCUMENT_ROUTING: dict[str, str] = {
    "abstract.pdf": ROUTE_SKIP,
    "OriginalRevision/RFP 2026-026 - Appendix A - Submission Form.docx": ROUTE_SKIP,
    "OriginalRevision/DP 2026-026 - Annexe F - Questionnaire ESG.xlsx": ROUTE_SKIP,
    # Superseded by the Amendment 1 revision -- see SUPERSEDED_BY below.
    "OriginalRevision/RFP 2026-026 - Appendix D2 - Rated Criteria Response Form.docx": ROUTE_SKIP,

    "Amendment1/RFP 2026-026 - Appendix D2 - Rated Criteria Response REVISED.docx": ROUTE_EVAL_ONLY,
    "OriginalRevision/RFP 2026-026 - Appendix B1 - Mandatory criteria.xlsx": ROUTE_EVAL_ONLY,
    "OriginalRevision/RFP 2026-026 - Appendix B2 - Mandatory criteria.xlsx": ROUTE_EVAL_ONLY,
    "OriginalRevision/RFP 2026-026 - Appendix B3 - Mandatory criteria.xlsx": ROUTE_EVAL_ONLY,
    "OriginalRevision/RFP 2026-026 - Appendix C1 - Minimum qualification requirements.xlsx": ROUTE_EVAL_ONLY,
    "OriginalRevision/RFP 2026-026 - Appendix C2 - Minimum qualification requirements.xlsx": ROUTE_EVAL_ONLY,
    "OriginalRevision/RFP 2026-026 - Appendix C3 - Minimum qualification requirement.xlsx": ROUTE_EVAL_ONLY,
    "OriginalRevision/RFP 2026-026 - Appendix D1 - Rated criteria response form.docx": ROUTE_EVAL_ONLY,
    "OriginalRevision/RFP 2026-026 - Appendix D3 - Rated Criteria Response Form.docx": ROUTE_EVAL_ONLY,

    "OriginalRevision/RFP 2026-026 - Appendix E - Pricing Form.xlsx": ROUTE_CONTRACT_NARROW,

    "OriginalRevision/RFP 2026-06 - Appendix G - Form of Agreement.docx": ROUTE_COMMERCIAL_ONLY,

    "RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf": ROUTE_IDENTITY_EVAL_REQ,
}

# Documents whose page-limit fact is extracted deterministically (audit S D/S 3
# -- "do not spend an LLM call on information that can be extracted reliably
# with deterministic parsing"). These are also EVAL_ONLY-routed for their
# weight-table content; the two extractions are independent and merged.
PAGE_LIMIT_DOCUMENTS = {
    "Amendment1/RFP 2026-026 - Appendix D2 - Rated Criteria Response REVISED.docx": "D2",
    "OriginalRevision/RFP 2026-026 - Appendix D1 - Rated criteria response form.docx": "D1",
    "OriginalRevision/RFP 2026-026 - Appendix D3 - Rated Criteria Response Form.docx": "D3",
}

# Batching (audit S F rule 2): these six documents are each well under the
# chunk boundary individually and contribute only evaluation_criteria: batch
# them into one call instead of six.
BATCH_GROUP = [
    "OriginalRevision/RFP 2026-026 - Appendix B1 - Mandatory criteria.xlsx",
    "OriginalRevision/RFP 2026-026 - Appendix B2 - Mandatory criteria.xlsx",
    "OriginalRevision/RFP 2026-026 - Appendix B3 - Mandatory criteria.xlsx",
    "OriginalRevision/RFP 2026-026 - Appendix C1 - Minimum qualification requirements.xlsx",
    "OriginalRevision/RFP 2026-026 - Appendix C2 - Minimum qualification requirements.xlsx",
    "OriginalRevision/RFP 2026-026 - Appendix C3 - Minimum qualification requirement.xlsx",
]


_CONTRACT_INSTRUMENT_FILENAME_RE = re.compile(
    r'\bform[\s_-]+of[\s_-]+(contract|agreement)\b|'
    r'\b(draft|general[\s_-]+service)[\s_-]+(contract|agreement)\b', re.IGNORECASE)


def route_document(filename: str) -> str:
    """Deterministic routing per the audit's matrix (S D). Unknown documents
    (outside the validated corpus) fall back to the broadest narrow mode
    (IDENTITY_EVAL_REQ) rather than being silently skipped or sent the
    universal Deep Verify schema -- EXCEPT for the one narrow, generic
    pattern this fallback already special-cases within the validated
    corpus itself (compare DOCUMENT_ROUTING's own
    "...Appendix G - Form of Agreement.docx" -> ROUTE_COMMERCIAL_ONLY): a
    filename that names itself as the contract/agreement instrument
    (e.g. "Appendix A - Form of Contract.pdf", "Draft Contract.docx") is
    generically a commercial-terms document, not an opportunity-identity
    or evaluation-criteria source -- confirmed live for a corpus outside
    DOCUMENT_ROUTING's validated set, where such a document was still
    falling back to IDENTITY_EVAL_REQ and consequently (a) getting the
    same generic Source Map role label as the master RFP and every other
    document, instead of its own "commercial and contractual terms" role,
    and (b) being asked for its own doc_metadata (title/client), which can
    then compete with the real solicitation's identity in merge precedence
    (a contract instrument's "client" field is often a formal legal party
    name, not the solicitation's stated buyer name). This never changes
    the route for any filename actually present in DOCUMENT_ROUTING --
    that exact-match table is always checked first."""
    if filename in DOCUMENT_ROUTING:
        return DOCUMENT_ROUTING[filename]
    if _CONTRACT_INSTRUMENT_FILENAME_RE.search(filename):
        return ROUTE_COMMERCIAL_ONLY
    return ROUTE_IDENTITY_EVAL_REQ


# ---------------------------------------------------------------------------
# Deterministic page-limit extraction (audit S D/S 3) -- no LLM call.
# Verified directly against all three forms' actual header text (see
# FAST_ANALYSIS_MINIMUM_VIABLE_INTELLIGENCE_AUDIT.md S E footnote).
# ---------------------------------------------------------------------------

_PAGE_LIMIT_RE = re.compile(
    r'(?:not\s+exceed|maximum\s+of|limit\s+of|exceed)\s+'
    r'(?:(\d+)\s*pages?|(\w+)\s*\((\d+)\)\s*pages?)',
    re.IGNORECASE,
)


def extract_page_limit_deterministic(doc_text: str) -> int | None:
    """Return the stated page limit from a rated-criteria response form's
    own header text, or None if the pattern is not found (callers must treat
    None as "deterministic extraction did not apply here", not as zero)."""
    m = _PAGE_LIMIT_RE.search(doc_text)
    if not m:
        return None
    return int(m.group(1)) if m.group(1) else int(m.group(3))


# ---------------------------------------------------------------------------
# Deterministic enumerated-scope and Response-Guideline parsing -- no LLM
# call, pure text/structure parsing over the same deterministically-
# extracted document text every other deterministic function here already
# operates on. Generic to any procurement document using either of these
# two common structuring conventions; never keyed to a specific buyer's
# wording or a specific set of expected service names/criteria.
# ---------------------------------------------------------------------------

# A trigger sentence that introduces an enumerated scope-of-services list.
# Several common phrasings, all generic procurement-document conventions,
# not any one buyer's exact wording.
_SCOPE_ENUM_TRIGGER_RE = re.compile(
    r'(?:services?\s+(?:will|shall)?\s*(?:include|comprise)(?:\s+providing)?\s+the\s+following|'
    r'scope\s+(?:of\s+services?\s+)?includes?|'
    r'the\s+following\s+services?)\s*[:,]?\s*(?:as\s+and\s+when\s+requested[^:]*)?:?\s*$',
    re.IGNORECASE)

# A line consisting of ONLY a lettered or numbered list marker, e.g. "(a)",
# "(b)", "a)", "1)" -- the marker and its item text are on separate lines
# in this deterministic PDF-text extraction's own layout (confirmed live
# against a real RFP: the marker alone on one line, the item text on the
# next). Also matches a marker sharing its line with the item text, for
# documents laid out that way instead.
_LIST_MARKER_ONLY_RE = re.compile(r'^\(?([a-z]|[ivx]+)\)\s*$', re.IGNORECASE)
_LIST_MARKER_LEADING_RE = re.compile(r'^\(?([a-z]|[ivx]+)\)\s*(.+)$', re.IGNORECASE)


def extract_enumerated_service_scope(doc_text: str) -> dict | None:
    """Deterministically locate an explicitly enumerated list of services
    following a generic scope-introduction sentence (e.g. "The Services
    will include providing the following:" then "(a) ... (b) ... (c)
    ..."), and return its items with provenance. Returns None when no
    such trigger sentence is found anywhere in the text -- this is a
    fallback for a specific, common RFP structuring convention, not a
    general-purpose list extractor, and it must never guess a list exists
    when the text doesn't actually introduce one this way.

    Each returned item is trimmed of trailing list punctuation ("; and",
    "; or", ".") and, when a marker's item text runs on into a longer
    descriptive clause the source's own line-wrapping didn't cleanly
    separate (e.g. "Coaching Services for the following roles: Director,
    ..."), is generically shortened to the leading name portion using the
    same technique already used for LLM-extracted scope text (truncate at
    the first colon, then at a leading preposition if still long) --
    never a hardcoded item name.

    Return shape: {"trigger_sentence": str, "items": [str, ...],
    "source_page": int | None} or None."""
    lines = doc_text.splitlines()
    trigger_idx = None
    trigger_sentence = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if _SCOPE_ENUM_TRIGGER_RE.search(stripped):
            trigger_idx = i
            trigger_sentence = stripped
            break
    if trigger_idx is None:
        return None

    # Determine the nearest preceding [[SOURCE: ... | PAGE: N]] marker for
    # provenance.
    source_page = None
    for j in range(trigger_idx, -1, -1):
        m = re.search(r'\[\[SOURCE:[^\]]*PAGE:\s*(\d+)[^\]]*\]\]', lines[j])
        if m:
            source_page = int(m.group(1))
            break

    def _next_letter(letter: str) -> str:
        return chr(ord(letter) + 1)

    def _finalize(raw: str) -> str:
        clean = raw.strip()
        clean = re.sub(r'\s*;?\s*(?:and|or)?\s*\.?\s*$', '', clean, flags=re.IGNORECASE).strip()
        clean = clean.rstrip(';,.').strip()
        if ":" in clean:
            clean = clean.split(":", 1)[0].strip()
        if len(clean) >= 45:
            m2 = re.match(r'^(.{1,44}?)\s+(?:of|for|in|including|covering)\s+', clean, re.IGNORECASE)
            if m2:
                clean = m2.group(1).strip()
        return clean

    # Accumulate each item's RAW text across however many physical lines
    # it spans, and call _finalize exactly once per item at the end --
    # calling it repeatedly while folding continuation lines in would
    # re-truncate an already-salvaged short name (e.g. re-processing a
    # short item name plus a further continuation line could regrow or
    # corrupt it); accumulating first avoids that entirely.
    raw_items: list[str] = []
    pending_marker = None
    expected_next = "a"

    for k in range(trigger_idx + 1, min(trigger_idx + 200, len(lines))):
        raw_line = lines[k]
        stripped = raw_line.strip()
        if _SOURCE_MARKER_RE.match(stripped):
            continue
        if _ANY_HEADING_RE.match(raw_line) and raw_items:
            # A new numbered section starts -- the enumerated list is over.
            break
        if not stripped:
            continue
        only_m = _LIST_MARKER_ONLY_RE.match(stripped)
        leading_m = _LIST_MARKER_LEADING_RE.match(stripped)
        if only_m:
            marker = only_m.group(1).lower()
            if marker != expected_next:
                break
            if pending_marker is not None:
                # A marker-only line following another marker-only line
                # with no content in between -- stop rather than silently
                # drop data.
                break
            pending_marker = marker
            continue
        if leading_m and leading_m.group(1).lower() == expected_next and pending_marker is None:
            raw_items.append(leading_m.group(2))
            expected_next = _next_letter(expected_next)
            continue
        if pending_marker is not None:
            raw_items.append(stripped)
            pending_marker = None
            expected_next = _next_letter(expected_next)
            continue
        if raw_items:
            # A continuation line belonging to the last collected item
            # (the source line-wrapped mid-sentence) -- only fold it in
            # when it doesn't itself look like the start of unrelated
            # prose (heuristic: short lines or lines ending mid-clause).
            if len(stripped) < 120 and not stripped.endswith('.'):
                raw_items[-1] = raw_items[-1] + " " + stripped
                continue
            break
        break

    if not raw_items:
        return None
    items = [_finalize(r) for r in raw_items]
    return {"trigger_sentence": trigger_sentence, "items": items, "source_page": source_page}


_SOURCE_MARKER_FULL_RE = re.compile(r'^\[\[SOURCE:\s*([^|]+?)\s*\|(.*?)\]\]\s*(.*)$')

_RG_HEADER_ROW_RE = re.compile(
    r'^Response Guideline\s+(\d+)\s*\|\s*Points Available\s*\|\s*Minimum Score\s*$', re.IGNORECASE)
_RG_DATA_ROW_RE = re.compile(
    r'^Response Guideline\s+(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*$', re.IGNORECASE)

# Short table-row labels that are response-FORM structure (a field to fill
# in) rather than an evidence prompt -- generic to any proposal-response
# form using this common reference/example-table layout, not tied to any
# specific buyer's field names.
_RG_FORM_FIELD_NOISE_RE = re.compile(
    r'^(?:example\s+\d+|client\s*\(?organization\)?\s*name|reference\s+name(?:\s+and\s+title)?|'
    r'reference\s+email|reference\s+phone\s+number|start\s+date|end\s+date)\s*:?\s*$',
    re.IGNORECASE)

# A genuine evidence-prompt sentence generically contains an instructional
# verb ("Describe...", "Provide...", "Using the tables below...") -- a
# common convention across proposal response forms, not specific wording
# from any one buyer's form.
_RG_PROMPT_VERB_RE = re.compile(
    r'\b(describe|provide|identify|explain|list|using|outline|summarize|detail|indicate)\b',
    re.IGNORECASE)


def extract_response_guideline_sections(doc_text: str) -> list[dict]:
    """Deterministically parse a Response-Guideline-structured proposal
    response form into one section per guideline, using the document's
    own repeating "Response Guideline N | <weight> | <minimum score>"
    table row as the section boundary -- generic to any corpus using this
    common RFP response-form convention (a numbered "Response Guideline"/
    "Rated Criteria" table per criterion), not hardcoded to any specific
    guideline count, criterion name, or prompt wording. Everything after
    a guideline's data row, up to the next guideline's data row (or the
    end of text), is collected as that guideline's evidence_prompts --
    filtered generically to exclude short response-FORM field labels
    ("Client (Organization) Name:", "Example 1", etc.) that are proposal
    form structure, not evidence prompts, and deduplicated against
    identical repeated table-cell content.

    Returns [] when no "Response Guideline N | ... | ..." data row is
    found anywhere -- never fabricates guideline structure for a corpus
    that doesn't have this table layout.

    Each section: {"id": "RG<n>", "weight": str | None,
    "minimum_score": str | None, "evidence_prompts": [str, ...],
    "source_doc": str | None}."""
    lines = doc_text.splitlines()

    # Group lines into "table row" blocks: each starts at a
    # [[SOURCE: ...]] marker of any kind and continues until the next one.
    blocks: list[tuple[str | None, list[str]]] = []
    current_doc: str | None = None
    current_content: list[str] = []
    have_block = False
    for line in lines:
        m = _SOURCE_MARKER_FULL_RE.match(line)
        if m:
            if have_block:
                blocks.append((current_doc, current_content))
            current_doc = m.group(1).strip()
            current_content = [m.group(3)] if m.group(3) else []
            have_block = True
        elif have_block:
            current_content.append(line)
    if have_block:
        blocks.append((current_doc, current_content))

    sections: list[dict] = []
    current: dict | None = None
    for source_doc, content_lines in blocks:
        joined = ' '.join(l.strip() for l in content_lines if l.strip())
        raw_cells = [p.strip() for p in joined.split('|') if p.strip()]
        distinct_cells: list[str] = []
        for c in raw_cells:
            if c not in distinct_cells:
                distinct_cells.append(c)
        text = ' | '.join(distinct_cells)
        if not text:
            continue

        if _RG_HEADER_ROW_RE.match(text):
            continue  # column-header row, no data yet

        data_m = _RG_DATA_ROW_RE.match(text)
        if data_m:
            if current is not None:
                current.pop("past_boundary", None)
                sections.append(current)
            weight = data_m.group(2).strip()
            min_score = data_m.group(3).strip()
            current = {
                "id": f"RG{int(data_m.group(1))}",
                "weight": weight or None,
                "minimum_score": None if not min_score or min_score.upper() == "N/A" else min_score,
                "evidence_prompts": [],
                "source_doc": source_doc,
            }
            continue

        if current is None:
            continue
        # A block that deduplicates down to 3+ genuinely distinct cell
        # values is a raw multi-column table row (e.g. a nested sub-
        # table's own column-header row, "ICF Certification Level | Total
        # Number in roster | ...") rather than a single evidence-prompt
        # sentence -- a real prompt's identical text simply gets repeated
        # across flattened columns and collapses to exactly one value.
        # Generic to any corpus's response-form table layout.
        if len(distinct_cells) >= 3:
            continue
        if _RG_FORM_FIELD_NOISE_RE.match(text) or len(text) < 25:
            continue
        # The last guideline in the document has no following "Response
        # Guideline N+1" row to bound it, so its content can otherwise run
        # on into an unrelated following section (confirmed live: a
        # "Pricing Rules and Requirements | Points Available" table
        # header bled into the final guideline's prompt list). A genuine
        # evidence prompt consistently contains an instructional verb
        # ("Describe...", "Provide...", "Using...") or is the
        # "Instructions for Proponents:" line itself; once a block stops
        # looking like that after at least one real prompt has already
        # been collected, treat it as the start of the next, unrelated
        # section and stop collecting for this guideline.
        looks_like_prompt = (
            current["evidence_prompts"] == [] or
            text.lower().startswith("instructions for proponents") or
            _RG_PROMPT_VERB_RE.search(text) is not None
        )
        if not looks_like_prompt:
            current["past_boundary"] = True
        if current.get("past_boundary"):
            continue
        if text not in current["evidence_prompts"]:
            current["evidence_prompts"].append(text)

    if current is not None:
        current.pop("past_boundary", None)
        sections.append(current)
    return sections


# ---------------------------------------------------------------------------
# Section-targeted extraction (V4) -- deterministic location of small,
# semantically coherent regions of a document by generic procurement-
# document heading structure (numbered sections, "Stage N." labels), never
# by hard-coded page numbers or any instance-specific offset. Investigation
# (FAST_ANALYSIS_V4_IMPLEMENTATION_REPORT.md) established that D1/D2/D3
# contain NO weight values at all (zero tables, zero numeric point/percent
# mentions tied to any criterion) -- the actual, sole, ground-truth rated-
# criteria weight table lives in the master RFP's own "Rated criteria"
# section, and the Stage-4-pricing / Abnormally-Low-Pricing language lives
# in its own "Stage 4. Pricing" section. Both are small (under 2,500 chars),
# non-truncation-risk regions once isolated from the ~23K-char general
# chunk that has caused truncation in every prior package.
# ---------------------------------------------------------------------------

_SOURCE_MARKER_RE = re.compile(r'\[\[SOURCE:[^\]]+\]\]')

# A line is treated as a section boundary if it looks like a numbered
# procurement-document heading ("4.6", "3.1 Evaluation of proposals") or a
# named evaluation stage ("Stage 5. Cumulative score") -- both are generic,
# widely-used RFP structuring conventions, not specific to this corpus.
_ANY_HEADING_RE = re.compile(
    r'^[ \t]*(?:\d+\.\d+(?:\.\d+)?(?:[ \t]|$)|Stage[ \t]*\d+\.)', re.IGNORECASE | re.MULTILINE)

# Section-kind -> the heading pattern that marks its START. The vocabulary
# ("Rated criteria", "Stage 4. Pricing") is generic procurement/evaluation
# terminology (per audit S 3's explicit allowance), not a Bank-of-Canada-
# specific label -- any RFP using this common structure would match.
_SECTION_START_PATTERNS = {
    "rated_criteria": re.compile(r'^[ \t]*Rated criteria[ \t]*$', re.IGNORECASE | re.MULTILINE),
    "pricing_stage": re.compile(r'^[ \t]*Stage[ \t]*4\.[ \t]*Pricing', re.IGNORECASE | re.MULTILINE),
}


def find_section(doc_text: str, section_kind: str, max_section_chars: int = 6000) -> str | None:
    """Locate ONE deterministically-bounded region of doc_text by generic
    heading structure: from the recognized start heading to the next
    recognized heading (of any kind) or max_section_chars, whichever comes
    first. The nearest preceding [[SOURCE: ...]] marker is prepended so the
    section retains valid page/section provenance even though it doesn't
    start at a marker boundary itself. Returns None if the start heading
    isn't found in this document -- callers must treat that as "this
    document has no such section" and fall back to the general route,
    never silently skip the fact."""
    pattern = _SECTION_START_PATTERNS.get(section_kind)
    if pattern is None:
        raise ValueError(f"unknown section_kind: {section_kind}")
    m = pattern.search(doc_text)
    if not m:
        return None
    start = m.start()
    window = doc_text[start:start + max_section_chars]
    newline = window.find("\n")
    search_from = newline + 1 if newline != -1 else 0
    next_heading = _ANY_HEADING_RE.search(window, search_from)
    if next_heading:
        window = window[:next_heading.start()]
    preceding_markers = list(_SOURCE_MARKER_RE.finditer(doc_text[:start]))
    prefix = (preceding_markers[-1].group(0) + "\n") if preceding_markers else ""
    return (prefix + window).strip()


# ---------------------------------------------------------------------------
# Minimal Fast Analysis schema prompts (audit S F) -- one per route, each
# requesting only the families that route's documents actually contribute
# to the client-facing report. Every prompt retains the same source_refs
# shape and physical-provenance rules as Deep Verify's prompt, so
# provenance validation continues to work unchanged (audit S 4 "Provenance").
# ---------------------------------------------------------------------------

_SOURCE_REF_RULES = """CRITICAL SOURCE TRACEABILITY RULES:
1. For every item, include "source_refs" pointing to the actual markers present in the text.
2. DO NOT hallucinate or guess page numbers, sheet names, or sections. Use only markers in the text.
3. "source_refs" schema:
   [{"source_doc": "<filename>", "page": <int or null>, "sheet": "<str or null>",
     "section": "<str or null>", "excerpt": "<1-2 sentence verbatim quote from text>"}]
"""

_EVAL_SCHEMA = """
Extract EVERY stated evaluation-criterion point/weight value, preserving every distinct
occurrence even if the same criterion label repeats with a different value elsewhere in this
text -- do NOT merge, average, or pick one value if the text states more than one for the same
label. This is the single most important instruction in this prompt.

A weight or point value belongs here ONLY when its role is to score, rank, or otherwise ASSESS
a bidder's submission -- their technical response, methodology, experience, team, references,
qualifications, proposal quality, or price treated as one of several factors used to select the
winning bidder (e.g. "Technical 80%, Price 20%" IS a genuine evaluation criterion and belongs
here). A weight or percentage used only to CALCULATE a bidder's own price -- for example a
weighted average or blend of resource rates, cost line-items, usage scenarios, or quantities
combined into a single price figure -- is a pricing-calculation mechanism, not an evaluation
criterion, even when it appears in a table with a column literally named "Weight" or "Weighted
Cost." Do not extract pricing-calculation weights here -- if this same task also asks for this
procurement's requirements or pricing/commercial content, capture the weighting there instead
(with the weight values preserved verbatim), so the fact is not lost, only correctly classified.
When genuinely uncertain whether a weight scores the bidder or only computes their price, prefer
NOT extracting it here.

For an Award Criterion specifically (as opposed to a Qualification / Gate), also capture, when
explicitly stated, the minimum score/points a bidder must achieve on THAT SPECIFIC criterion to
remain under consideration -- distinct from the criterion's own weight/points-available value,
e.g. a table with columns "Weight" and "Minimum Score", or "proponents not meeting the minimum
score requirement in any category will be excluded." Put this in "threshold" verbatim (e.g. "10
points"); use null when no per-criterion minimum is stated for that criterion (most criteria will
have none -- do not infer one from the overall mandatory pass mark or from another criterion's
minimum). "threshold" still also covers a Qualification/Gate's own pass/fail bar (e.g. "5 years
experience") exactly as before -- the two uses don't conflict, since a single criterion is either
one role or the other.

Return ONLY valid JSON:
{
  "evaluation_criteria": [
    {
      "stage": "Criterion or stage name exactly as stated",
      "parent_stage": "Parent heading/table title, or null",
      "weight": "Exact weight/points string as stated, e.g. '35 points' or '25%', or null",
      "weight_unit": "Points|Percent|Other|None",
      "weight_basis": "Overall|Within Parent|Unknown",
      "threshold": "Minimum passing threshold/minimum score as stated (e.g. '5 years experience' or '10 points'), or null",
      "evaluation_role": "Award Criterion|Qualification / Gate|Structural Container|Unknown",
      "source_refs": []
    }
  ]
}
"""

_IDENTITY_EVAL_REQ_SCHEMA = """
Extract ONLY the following -- do not extract commercial clauses, deliverables, or every
requirement in the document; extract only what is listed below.

1. doc_metadata: title, client (buyer), file_number (solicitation number), submission_deadline
   (YYYY-MM-DD, plus a "submission_time" string if a time is stated), clarification_deadline.
2. typed_observations, restricted to exactly these families (omit all others):
   IDENTITY (kinds: BUYER_NAME, OPPORTUNITY_TITLE, SOLICITATION_NUMBER, DOCUMENT_TITLE),
   MILESTONE (kinds: SUBMISSION_DEADLINE, CLARIFICATION_DEADLINE, PRESENTATION_OR_DEMO,
     INTENT_TO_BID_DEADLINE, AMENDMENT_DATE, OTHER, UNKNOWN -- for PRESENTATION_OR_DEMO
     specifically, capture the "scope" field with which service category the date belongs to,
     since more than one category-specific presentation date may exist under this same label),
   CONTRACT_TERM (kinds: INITIAL_DURATION, EXTENSION_OPTION, MAXIMUM_TERM, TERM_STATEMENT),
   PROCUREMENT_MECHANIC (kinds: RFP, MULTIPLE_SUPPLIER_AWARD, SINGLE_SUPPLIER_AWARD, CALL_OFF,
     FRAMEWORK, LOTS),
   QUALIFICATION_MECHANISM (kinds: REFERENCE_CHECK, BACKGROUND_CHECK, OTHER -- a pass/fail
     qualification mechanism applied to a bidder or its proposed resources that is separate from
     both the mandatory submission gates and the weighted/rated criteria, e.g. "references will
     be contacted and evaluated on a pass/fail basis; an unsatisfactory reference may result in
     rejection of the Proposal." Capture the full pass/fail and consequence wording in
     "original_value"; leave "rank" null.),
   TIE_BREAK_RULE (kind: TIE_BREAK_CRITERION -- ONE entry per step of an explicitly stated,
     ordered tie-breaking procedure used when two or more proposals achieve the same score,
     e.g. "if scores are tied, the proposal with the highest score in Criterion X governs; if
     still tied, Criterion Y governs; if still tied, a random-selection method is used." Emit
     one typed_observation per step, each with "rank" set to that step's 1-based order (1 for
     the first tie-breaker applied, 2 for the next, etc.) and "original_value" holding that
     step's exact criterion name or method (e.g. the criterion name, or "Random selection" /
     the named randomizer method for the final step). Only emit this when the source text
     actually states an explicit, ordered procedure -- never infer or guess one.).
   Preserve every distinct occurrence (do not merge repeats into one).
3. evaluation_criteria: """ + _EVAL_SCHEMA.strip() + """
4. requirements, restricted to exactly four topics -- do not extract any other requirement:
   (a) the service-category scope description for each named category/lot (what each category
       includes), (b) the mandatory submission mechanics (how/where/when to submit, what
       forms are required, bilingual/accessibility/security-clearance obligations),
       (c) any stated pricing-evaluation consequence rule (e.g. what happens if a proponent's
       pricing appears abnormally low, including any required explanation or contract-security/
       performance-bond consequence), and (d) any stated pricing-calculation formula or
       weighting used to combine multiple cost/rate line-items into a single price figure (e.g.
       a weighted blend of resource rates, cost scenarios, or quantities) -- preserve the actual
       weight/percentage values verbatim in the requirement text; this is the correct home for a
       weight excluded from evaluation_criteria above because it only calculates price rather
       than scoring the bidder.

Return ONLY valid JSON:
{
  "doc_metadata": {"title": null, "client": null, "file_number": null,
                    "submission_deadline": null, "submission_time": null,
                    "clarification_deadline": null},
  "typed_observations": [
    {"family": "...", "semantic_kind": "...", "original_value": "...", "source_refs": [],
     "scope": {"component": null, "lot": null, "category": null}, "date": null, "duration": null,
     "unit": null, "option_count": null, "rank": null}
  ],
  "evaluation_criteria": [ ... same shape as above ... ],
  "requirements": [
    {"category": "Mandatory|Rated|Supporting", "description": "Full requirement text",
     "source_refs": []}
  ]
}
"""

_CONTRACT_NARROW_SCHEMA = """
Extract ONLY:
1. typed_observations restricted to CONTRACT_TERM and PROCUREMENT_MECHANIC families (same kinds
   as listed for identity extraction: INITIAL_DURATION, EXTENSION_OPTION, MAXIMUM_TERM,
   TERM_STATEMENT, RFP, MULTIPLE_SUPPLIER_AWARD, CALL_OFF, FRAMEWORK).
2. requirements, restricted to pricing-structure rules only (what must be priced, how, whether
   pricing appears elsewhere in the proposal, minimum-volume commitments or their absence).

Return ONLY valid JSON:
{
  "typed_observations": [
    {"family": "...", "semantic_kind": "...", "original_value": "...", "source_refs": [],
     "scope": {"component": null, "lot": null, "category": null}, "duration": null, "unit": null}
  ],
  "requirements": [
    {"category": "Mandatory|Rated|Supporting", "description": "Full requirement text",
     "source_refs": []}
  ]
}
"""

_COMMERCIAL_ONLY_SCHEMA = """
Extract ONLY commercial_clauses -- do not extract requirements, deliverables, or any other
family.

Return ONLY valid JSON:
{
  "commercial_clauses": [
    {
      "clause_kind": "LIABILITY_INDEMNITY|INSURANCE|INTELLECTUAL_PROPERTY|DATA_PROTECTION_PRIVACY|CYBERSECURITY_SECURITY|CONFIDENTIALITY|SUBCONTRACTING|PERSONNEL_KEY_STAFF|BACKGROUND_CHECK_CLEARANCE|TERMINATION|PAYMENT_WITHHOLDING_SETOFF|PRICING_ESCALATION|GUARANTEE_BOND|WARRANTY|CHANGE_CONTROL|ASSIGNMENT|GOVERNING_LAW_DISPUTE|REGULATORY_COMPLIANCE|OTHER",
      "topic": "Human-readable clause title",
      "source_fact": "Concise factual normalization; no inferred consequence",
      "source_refs": []
    }
  ]
}
"""

# ---------------------------------------------------------------------------
# V4 focused, section-targeted schemas (audit S 4/S 7) -- deliberately NOT
# another universal extraction task. Each operates on a small, pre-selected
# section of text (via find_section()), never a whole document, and asks
# for nothing beyond the one narrow fact family named in its own docstring.
# ---------------------------------------------------------------------------

_EVAL_FOCUSED_SCHEMA = """
Extract ONLY raw evaluation/scoring occurrences from this section -- do NOT extract opportunity
identity, dates, requirements, commercial clauses, contract term, or deliverables.

Preserve EVERY distinct occurrence exactly as stated, even if the same criterion label repeats
under a different category/scope with a different value -- do NOT merge, average, or normalize.
Do not include a "Total points" summary row as a criterion occurrence.

An occurrence belongs here ONLY when its role is to score, rank, or otherwise ASSESS a bidder's
submission (price treated as one of several factors used to select the winning bidder -- e.g.
"Technical 80%, Price 20%" -- is a genuine occurrence here). A weight or percentage used only to
CALCULATE a bidder's own price --
a weighted average or blend of resource rates, cost line-items, usage scenarios, or quantities
combined into a single price figure -- is a pricing-calculation mechanism, not an evaluation
occurrence, even when it appears in a table with a column literally named "Weight" or "Weighted
Cost." When genuinely uncertain whether a weight scores the bidder or only computes their
price, prefer NOT extracting it here.

Also capture, when explicitly stated for a criterion, the minimum score/points a bidder must
achieve on THAT SPECIFIC criterion to remain under consideration (distinct from the criterion's
own weight/points-available value) -- e.g. a table with columns "Weight" and "Minimum Score", or
text such as "proponents not meeting the minimum score requirement in any category will be
excluded." Capture it verbatim in "minimum_score"; use null when no per-criterion minimum is
stated for that criterion (most criteria will have none -- do not infer one from the overall
mandatory pass mark or from another criterion's minimum).

Return ONLY valid JSON:
{
  "evaluation_occurrences": [
    {
      "criterion_label": "Exact criterion or line-item name as stated (e.g. 'Corporate Profile', 'Price')",
      "weight": "Exact weight/points value as stated, e.g. '35 points' or '25%', or null",
      "minimum_score": "Exact minimum-score/points value stated for THIS criterion, e.g. '10 points', or null",
      "category_scope": "The named category/appendix this occurrence belongs to (e.g. 'Appendix D1 - Learning & Development Programs and Assessments'), or null if not category-specific",
      "evaluation_stage": "The stage/table heading this occurrence sits under, or null",
      "parent_heading": "The nearest explicit heading directly above this occurrence, if any, or null",
      "source_refs": []
    }
  ]
}
"""

_PRICING_FOCUSED_SCHEMA = """
Extract ONLY pricing-evaluation structural facts from this section -- do not extract anything else.

Identify each of the following, if present, as its own occurrence:
- A separately-defined pricing evaluation stage (e.g. a "Stage N. Pricing" description) -> semantic_kind "PRICING_STAGE".
- A "Price" (or similarly named) line item scored WITHIN a category's rated-criteria table -> semantic_kind "PRICE_CRITERION".
- Any provision about abnormally low pricing (an explanation requirement, contract security/bond
  consequence, or similar) -> semantic_kind "ABNORMALLY_LOW_PRICING".

Return ONLY valid JSON:
{
  "pricing_occurrences": [
    {
      "semantic_kind": "PRICING_STAGE|PRICE_CRITERION|ABNORMALLY_LOW_PRICING",
      "raw_wording": "Verbatim or near-verbatim statement of the fact",
      "stage": "The named stage/table this occurrence belongs to, if stated, or null",
      "category_scope": "The named category this applies to, or null if it applies generally",
      "weight": "Points/weight value if stated, or null",
      "source_refs": []
    }
  ]
}
"""

_ROUTE_SCHEMAS = {
    ROUTE_EVAL_ONLY: _EVAL_SCHEMA,
    ROUTE_IDENTITY_EVAL_REQ: _IDENTITY_EVAL_REQ_SCHEMA,
    ROUTE_CONTRACT_NARROW: _CONTRACT_NARROW_SCHEMA,
    ROUTE_COMMERCIAL_ONLY: _COMMERCIAL_ONLY_SCHEMA,
}

# Fields that, if entirely absent from a chunk's parsed output, justify one
# bounded, targeted retry (audit S 8: "targeted retry only when a required
# Fast Analysis field is missing", never full-schema re-extraction).
_REQUIRED_FIELDS_BY_ROUTE = {
    ROUTE_IDENTITY_EVAL_REQ: ["doc_metadata"],
    ROUTE_EVAL_ONLY: ["evaluation_criteria"],
    ROUTE_CONTRACT_NARROW: ["typed_observations"],
    ROUTE_COMMERCIAL_ONLY: ["commercial_clauses"],
}


def _build_prompt(route: str, filename: str, chunk_text: str) -> str:
    schema = _ROUTE_SCHEMAS[route]
    header = (
        "You are a procurement intelligence analyst performing a FAST, MINIMAL extraction pass.\n"
        "Extract only what is explicitly requested below -- do not extract any other family or\n"
        "field, and do not attempt to be exhaustive beyond what is requested.\n"
        "The text contains deterministic source markers:\n"
        "- [[SOURCE: <filename> | PAGE: <page_no>]]\n"
        "- [[SOURCE: <filename> | SHEET: <sheet_name> | ROWS: <range>]]\n"
        "- [[SOURCE: <filename> | SECTION: <heading>]]\n\n"
        + _SOURCE_REF_RULES + "\n" + schema
    )
    return header + f"\n\nDOCUMENT TO PROCESS ({filename}):\n" + chunk_text


def _empty_result(route: str) -> dict:
    base = {"doc_metadata": {}, "typed_observations": [], "evaluation_criteria": [],
            "requirements": [], "commercial_clauses": []}
    return base


def _merge_chunk_result(into: dict, data: dict) -> None:
    for k in ("typed_observations", "evaluation_criteria", "requirements", "commercial_clauses"):
        if isinstance(data.get(k), list):
            into[k].extend(x for x in data[k] if isinstance(x, dict))
    meta = data.get("doc_metadata")
    if isinstance(meta, dict):
        for k, v in meta.items():
            if v and not into["doc_metadata"].get(k):
                into["doc_metadata"][k] = v


def _has_required_fields(route: str, data: dict) -> bool:
    for field_name in _REQUIRED_FIELDS_BY_ROUTE.get(route, []):
        val = data.get(field_name)
        if not val:
            return False
    return True


def _call_fast_chunk(route: str, filename: str, chunk_text: str, api_key: str, client,
                     call_index: int, telemetry: list, call_kind: str = "initial",
                     parent_call_index: int | None = None,
                     split_trigger_reason: str | None = None,
                     prompt_override: str | None = None) -> dict:
    """One bounded LLM call for one chunk under one narrow route schema.
    Telemetry mirrors the shape Deep Verify's live-telemetry work established
    (call_index/call_kind/timestamps/tokens/stop_reason/parse_status) so the
    same kind of analysis (recovery tax, token distribution) is possible for
    Fast Analysis too, without importing any Deep Verify telemetry code.
    `parent_call_index`/`split_trigger_reason` are additive V3 observability
    fields (audit S 18) letting a split_recovery_a/b call be traced back to
    the truncated call that caused it; both are None for every other kind.
    `prompt_override` (V4) lets a caller supply a fully-built prompt (e.g. a
    focused section-targeted task) instead of the standard per-route prompt,
    reusing this same call/telemetry/error-handling machinery rather than
    duplicating it."""
    request_text = prompt_override if prompt_override is not None else _build_prompt(route, filename, chunk_text)
    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()
    try:
        response = execute_messages_create(
            client,
            model=FAST_MODEL, max_tokens=FAST_MAX_OUTPUT_TOKENS,
            messages=[{"role": "user", "content": [{"type": "text", "text": request_text}]}],
        )
    except Exception as exc:
        telemetry.append({
            "call_index": call_index, "call_kind": call_kind, "filename": filename, "route": route,
            "model": FAST_MODEL, "request_bytes": len(request_text.encode("utf-8")),
            "chunk_chars": len(chunk_text),
            "call_started_at": started_at.isoformat(), "call_ended_at": datetime.now(timezone.utc).isoformat(),
            "latency_seconds": round(time.monotonic() - t0, 6),
            "input_tokens": None, "output_tokens": None, "stop_reason": None,
            "parse_status": None, "error": f"{type(exc).__name__}: {exc}",
            "parent_call_index": parent_call_index, "split_trigger_reason": split_trigger_reason,
            # Phase 5E.1: this row exists BECAUSE execute_messages_create()
            # was actually invoked and raised -- a genuine attempted (and
            # failed) provider call, never bookkeeping, regardless of its
            # null token fields (a failed attempt has no usage to report).
            "provider_call_attempted": True,
        })
        raise
    usage = getattr(response, "usage", None)
    data, parse_status = _safe_parse_json_with_status(response.content[0].text)
    telemetry.append({
        "call_index": call_index, "call_kind": call_kind, "filename": filename, "route": route,
        "model": FAST_MODEL, "request_bytes": len(request_text.encode("utf-8")),
        "chunk_chars": len(chunk_text),
        "call_started_at": started_at.isoformat(), "call_ended_at": datetime.now(timezone.utc).isoformat(),
        "latency_seconds": round(time.monotonic() - t0, 6),
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "stop_reason": getattr(response, "stop_reason", None),
        "parse_status": parse_status, "error": None,
        "parent_call_index": parent_call_index, "split_trigger_reason": split_trigger_reason,
        "provider_call_attempted": True,
    })
    return data if isinstance(data, dict) else {}


def _split_chunk_for_recovery(chunk_text: str) -> list[str]:
    """Bounded, ONE-TIME, marker-aware split of a truncated chunk into at
    most 2 smaller subchunks (audit S 2/S 3/S 19). Reuses Deep Verify's own
    pure marker-aware chunker (`chunk_document_text`) rather than a blind
    character slice, so a `[[SOURCE: ...]]` marker is never severed from its
    own text -- each subchunk keeps enough physical source context for
    source_refs to remain valid. Returns a list of length 1 (could not be
    split further -- e.g. the chunk is already a single, indivisible marker
    block at this size) or exactly 2 -- callers must never split the result
    again; that is what makes this bounded, not recursive."""
    target = max(len(chunk_text) // 2, 1)
    pieces = [p for p in _deep_chunk_document_text(chunk_text, max_chunk_chars=target) if p.strip()]
    if len(pieces) <= 2:
        return pieces
    # The marker-aware chunker can legitimately return more than 2 pieces
    # (e.g. several short marker blocks) -- collapse everything after the
    # first into a single second half so the split stays exactly 2-way.
    return [pieces[0], "".join(pieces[1:])]


def extract_fast_document(filename: str, doc_text: str, api_key: str, *, route: str | None = None,
                          client=None, telemetry: list | None = None) -> dict:
    """Extract one document's narrow Fast Analysis facts. Chunking reuses
    Deep Verify's pure, marker-aware chunker, but at FAST_MAX_CHUNK_CHARS
    (larger -- audit-justified, see module docstring).

    Recovery has two independent, both-bounded mechanisms (V3):

    1. max_tokens truncation -> BOUNDED, ONE-TIME, MARKER-AWARE SPLIT
       recovery (audit S "PRIMARY V3 CHANGE"). V2 resent the identical
       over-budget chunk at temperature 0 and reproduced the identical
       truncation point every time -- root-caused in
       FAST_ANALYSIS_V2_IMPLEMENTATION_REPORT.md S2. V3 instead splits ONLY
       the truncated chunk into 2 smaller subchunks and extracts each
       independently under the same route/schema -- never resplitting a
       subchunk that itself truncates (no silent recursion; recorded as
       BOUNDED_SPLIT_EXHAUSTED instead).
    2. Missing route-required field WITHOUT a max_tokens truncation -> the
       original v1/v2 bounded single same-content retry (unrelated failure
       mode: the model simply didn't populate a required field on an
       otherwise-complete response; resending can plausibly help here in a
       way it structurally cannot for a token-ceiling truncation).

    In both cases every call's result is MERGED into the document's output,
    never substituted for another call's result, so recovery can only add
    content, never silently drop something an earlier call already got right."""
    if telemetry is None:
        telemetry = []
    if client is None:
        client = get_anthropic_client(api_key=api_key)
    route = route or route_document(filename)
    chunks = _deep_chunk_document_text(doc_text, max_chunk_chars=FAST_MAX_CHUNK_CHARS)
    result = _empty_result(route)
    for chunk in chunks:
        call_index = len(telemetry)
        data = _call_fast_chunk(route, filename, chunk, api_key, client, call_index, telemetry)
        stop_reason = telemetry[call_index].get("stop_reason")
        _merge_chunk_result(result, data)

        if stop_reason == "max_tokens":
            subchunks = _split_chunk_for_recovery(chunk)
            if len(subchunks) < 2:
                telemetry.append({
                    "call_index": len(telemetry), "call_kind": "split_exhausted",
                    "filename": filename, "route": route, "model": None,
                    "request_bytes": 0, "chunk_chars": len(chunk),
                    "call_started_at": None, "call_ended_at": None, "latency_seconds": 0.0,
                    "input_tokens": None, "output_tokens": None, "stop_reason": None,
                    "parse_status": "BOUNDED_SPLIT_EXHAUSTED", "error": None,
                    "parent_call_index": call_index, "split_trigger_reason": "max_tokens",
                    # Phase 5E.1: pure bookkeeping -- no provider request was
                    # ever made for this row (recovery gave up before trying).
                    "provider_call_attempted": False,
                })
                continue
            for label, sub in zip(("split_recovery_a", "split_recovery_b"), subchunks):
                sub_index = len(telemetry)
                sub_data = _call_fast_chunk(route, filename, sub, api_key, client, sub_index,
                                            telemetry, call_kind=label,
                                            parent_call_index=call_index,
                                            split_trigger_reason="max_tokens")
                _merge_chunk_result(result, sub_data)
                if telemetry[sub_index].get("stop_reason") == "max_tokens":
                    # No silent recursion: a split subcall that itself
                    # truncates is NOT split again.
                    telemetry.append({
                        "call_index": len(telemetry), "call_kind": "split_exhausted",
                        "filename": filename, "route": route, "model": None,
                        "request_bytes": 0, "chunk_chars": len(sub),
                        "call_started_at": None, "call_ended_at": None, "latency_seconds": 0.0,
                        "input_tokens": None, "output_tokens": None, "stop_reason": None,
                        "parse_status": "BOUNDED_SPLIT_EXHAUSTED", "error": None,
                        "parent_call_index": sub_index, "split_trigger_reason": "max_tokens",
                        "provider_call_attempted": False,
                    })
        elif not _has_required_fields(route, data):
            # v1/v2's original bounded single same-content retry -- unrelated
            # to truncation, unchanged.
            retry_index = len(telemetry)
            retry_data = _call_fast_chunk(route, filename, chunk, api_key, client, retry_index,
                                          telemetry, call_kind="targeted_retry")
            _merge_chunk_result(result, retry_data)
    return result


def extract_fast_batch(filenames: list[str], texts_by_name: dict[str, str], api_key: str,
                       client=None, telemetry: list | None = None) -> dict[str, dict]:
    """Batch several small, EVAL_ONLY-routed documents into a single call
    (audit S F rule 2). Each document's text is still individually source-
    marked, so per-document source_refs remain correct; the model is asked
    to return a per-document breakdown so results can be split back out."""
    if telemetry is None:
        telemetry = []
    if client is None:
        client = get_anthropic_client(api_key=api_key)
    combined = "\n\n".join(
        f"[[SOURCE: {name} | SECTION: Document Start]]\n{texts_by_name[name]}" for name in filenames
    )
    schema = (
        _EVAL_SCHEMA.strip()
        + '\n\nThis request combines several small documents. Add a "source_doc" field to each '
          "evaluation_criteria entry naming which document it came from (must exactly match one of "
          "the filenames in the [[SOURCE: ...]] markers)."
    )
    header = (
        "You are a procurement intelligence analyst performing a FAST, MINIMAL extraction pass "
        "across several short documents in one request.\n"
        "The text contains deterministic source markers:\n"
        "- [[SOURCE: <filename> | SECTION: <heading>]]\n\n" + _SOURCE_REF_RULES + "\n" + schema
    )
    request_text = header + "\n\nDOCUMENTS TO PROCESS:\n" + combined
    call_index = len(telemetry)
    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()
    response = execute_messages_create(
        client,
        model=FAST_MODEL, max_tokens=FAST_MAX_OUTPUT_TOKENS,
        messages=[{"role": "user", "content": [{"type": "text", "text": request_text}]}],
    )
    usage = getattr(response, "usage", None)
    data, parse_status = _safe_parse_json_with_status(response.content[0].text)
    telemetry.append({
        "call_index": call_index, "call_kind": "batch", "filename": "+".join(filenames),
        "route": ROUTE_EVAL_ONLY, "model": FAST_MODEL,
        "request_bytes": len(request_text.encode("utf-8")),
        "chunk_chars": sum(len(texts_by_name[n]) for n in filenames),
        "call_started_at": started_at.isoformat(), "call_ended_at": datetime.now(timezone.utc).isoformat(),
        "latency_seconds": round(time.monotonic() - t0, 6),
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "stop_reason": getattr(response, "stop_reason", None),
        "parse_status": parse_status, "error": None,
    })
    by_doc: dict[str, dict] = {name: _empty_result(ROUTE_EVAL_ONLY) for name in filenames}
    if isinstance(data, dict):
        for ec in data.get("evaluation_criteria", []) or []:
            if not isinstance(ec, dict):
                continue
            src = ec.get("source_doc")
            target = src if src in by_doc else filenames[0]
            by_doc[target]["evaluation_criteria"].append(ec)
    return by_doc


# ---------------------------------------------------------------------------
# Focused, section-targeted task dispatch (V4, audit S 4/S 7) -- runs one of
# the narrow schemas above against a small, pre-located section instead of
# a whole document. Reuses the same bounded split-on-truncation mechanism
# (audit S 2: "Do NOT add recursive splitting" -- depth stays 1) for
# robustness, even though these sections are small enough that truncation
# is expected to be rare.
# ---------------------------------------------------------------------------

_FOCUSED_SCHEMAS = {
    "rated_criteria": (_EVAL_FOCUSED_SCHEMA, "evaluation_occurrences"),
    "pricing_stage": (_PRICING_FOCUSED_SCHEMA, "pricing_occurrences"),
}


def _build_focused_prompt(schema: str, filename: str, section_text: str) -> str:
    header = (
        "You are a procurement intelligence analyst performing a FOCUSED, MINIMAL extraction pass "
        "over ONE small, pre-selected section of a document -- not the whole document.\n"
        "The text contains deterministic source markers:\n"
        "- [[SOURCE: <filename> | PAGE: <page_no>]]\n\n" + _SOURCE_REF_RULES + "\n" + schema
    )
    return header + f"\n\nSECTION TEXT ({filename}):\n" + section_text


def run_focused_task(section_kind: str, filename: str, section_text: str, api_key: str,
                     client=None, telemetry: list | None = None) -> list[dict]:
    """Run one focused, section-targeted task and return its list of
    occurrences. Bounded split-on-truncation applies here too (never a
    same-content retry, never recursion beyond depth 1) -- reused, not
    duplicated, from the general mechanism."""
    if telemetry is None:
        telemetry = []
    if client is None:
        client = get_anthropic_client(api_key=api_key)
    schema, output_key = _FOCUSED_SCHEMAS[section_kind]
    call_kind_prefix = f"focused_{section_kind}"

    def _call(text: str, call_kind: str, parent_call_index=None) -> dict:
        call_index = len(telemetry)
        prompt = _build_focused_prompt(schema, filename, text)
        data = _call_fast_chunk(section_kind, filename, text, api_key, client, call_index,
                                telemetry, call_kind=call_kind, prompt_override=prompt,
                                parent_call_index=parent_call_index,
                                split_trigger_reason="max_tokens" if parent_call_index is not None else None)
        return call_index, data

    occurrences: list[dict] = []
    call_index, data = _call(section_text, f"{call_kind_prefix}_initial")
    occurrences.extend(x for x in (data.get(output_key) or []) if isinstance(x, dict))

    if telemetry[call_index].get("stop_reason") == "max_tokens":
        subchunks = _split_chunk_for_recovery(section_text)
        if len(subchunks) < 2:
            telemetry.append({
                "call_index": len(telemetry), "call_kind": f"{call_kind_prefix}_split_exhausted",
                "filename": filename, "route": section_kind, "model": None,
                "request_bytes": 0, "chunk_chars": len(section_text),
                "call_started_at": None, "call_ended_at": None, "latency_seconds": 0.0,
                "input_tokens": None, "output_tokens": None, "stop_reason": None,
                "parse_status": "BOUNDED_SPLIT_EXHAUSTED", "error": None,
                "parent_call_index": call_index, "split_trigger_reason": "max_tokens",
                "provider_call_attempted": False,
            })
        else:
            for label, sub in zip(("split_recovery_a", "split_recovery_b"), subchunks):
                sub_index, sub_data = _call(sub, f"{call_kind_prefix}_{label}", parent_call_index=call_index)
                occurrences.extend(x for x in (sub_data.get(output_key) or []) if isinstance(x, dict))
                if telemetry[sub_index].get("stop_reason") == "max_tokens":
                    telemetry.append({
                        "call_index": len(telemetry), "call_kind": f"{call_kind_prefix}_split_exhausted",
                        "filename": filename, "route": section_kind, "model": None,
                        "request_bytes": 0, "chunk_chars": len(sub),
                        "call_started_at": None, "call_ended_at": None, "latency_seconds": 0.0,
                        "input_tokens": None, "output_tokens": None, "stop_reason": None,
                        "parse_status": "BOUNDED_SPLIT_EXHAUSTED", "error": None,
                        "parent_call_index": sub_index, "split_trigger_reason": "max_tokens",
                        "provider_call_attempted": False,
                    })
    return occurrences


# ---------------------------------------------------------------------------
# Ambiguity detection (audit S 7) -- only the three known, report-relevant
# classes. Deliberately NOT a generalized conflict engine: each function is
# a narrow, purpose-built check over the already-extracted, occurrence-
# preserving evaluation_criteria / typed_observations data.
# ---------------------------------------------------------------------------

def detect_evaluation_weight_conflicts(all_evaluation_criteria: list[dict]) -> list[dict]:
    """A conflict exists when the same criterion label appears more than once
    with different stated weight values WITHIN THE SAME SCOPE (V4 fix, audit
    S 6: "Avoid false positives from clearly different categories/scopes").
    v1-v3 grouped by label alone; direct investigation of the real corpus
    (FAST_ANALYSIS_V4_IMPLEMENTATION_REPORT.md) found every apparent
    "Corporate Profile"/"Key Personnel" weight variation in the source text
    is legitimately category-scoped (5/5/10 and 15/15/20 across Categories
    1/2/3 respectively) -- correctly-scoped variation, not a genuine
    conflict, exactly like a category-specific date is not a date conflict.
    A label-only grouping would flag every one of these as a false positive.

    Accepts either the V4 focused-task occurrence shape
    (criterion_label/category_scope) or the general route's
    evaluation_criteria shape (stage/parent_stage) for backward
    compatibility; entries with neither scope field are grouped together
    under an empty scope, preserving the original label-only behavior for
    already-unscoped data (this is what every pre-V4 test fixture uses)."""
    by_key: dict[tuple[str, str], set[str]] = {}
    by_key_examples: dict[tuple[str, str], list[dict]] = {}
    for ec in all_evaluation_criteria:
        label = (ec.get("criterion_label") or ec.get("stage") or "").strip().lower()
        weight = (ec.get("weight") or "").strip()
        scope = (ec.get("category_scope") or ec.get("parent_stage") or "").strip().lower()
        if not label or not weight:
            continue
        key = (label, scope)
        by_key.setdefault(key, set()).add(weight)
        by_key_examples.setdefault(key, []).append(ec)
    conflicts = []
    for (label, scope), weights in by_key.items():
        if len(weights) > 1:
            conflicts.append({
                "type": "EVALUATION_WEIGHT_CONFLICT",
                "label": label,
                "scope": scope or None,
                "competing_values": sorted(weights),
                "occurrences": by_key_examples[(label, scope)],
            })
    return conflicts


def detect_pricing_stage_ambiguity(all_evaluation_criteria: list[dict] | None = None,
                                   pricing_occurrences: list[dict] | None = None) -> list[dict]:
    """A structural ambiguity exists when a "Price" line item appears inside
    a category's rated-criteria table AND a separate pricing evaluation
    stage also exists -- the reader cannot tell if price is scored once or
    twice.

    V4 fix (audit S 8): no longer requires the general route's parent_stage
    field to be exactly None for the top-level signal -- that was too
    brittle (a genuine top-level "Stage 4. Pricing" mention can legitimately
    come back with a non-null parent heading depending on how one specific
    LLM call structures its response, as V3's own live run demonstrated).
    Prefers the focused pricing task's semantic_kind-tagged occurrences
    (PRICING_STAGE / PRICE_CRITERION) when supplied, which carry no such
    parent_stage assumption at all; falls back to the v1-v3 heuristic over
    `all_evaluation_criteria` only when no focused occurrences are supplied,
    preserving prior test/production behavior."""
    if pricing_occurrences:
        has_stage = any((p.get("semantic_kind") or "").upper() == "PRICING_STAGE"
                        for p in pricing_occurrences)
        has_price_criterion = any((p.get("semantic_kind") or "").upper() == "PRICE_CRITERION"
                                  for p in pricing_occurrences)
        if has_stage and has_price_criterion:
            return [{
                "type": "PRICING_STAGE_AMBIGUITY",
                "detail": "A 'Price' line item appears inside a category rated-criteria table, and a "
                          "separate pricing evaluation stage also exists.",
                "occurrences": [p for p in pricing_occurrences
                               if (p.get("semantic_kind") or "").upper()
                               in ("PRICING_STAGE", "PRICE_CRITERION")],
            }]
        return []
    all_evaluation_criteria = all_evaluation_criteria or []
    has_price_in_table = any(
        "price" in (ec.get("stage") or ec.get("criterion_label") or "").strip().lower()
        and (ec.get("parent_stage") or ec.get("category_scope"))
        for ec in all_evaluation_criteria
    )
    has_pricing_stage = any(
        "pricing" in (ec.get("stage") or ec.get("criterion_label") or "").strip().lower()
        and not (ec.get("parent_stage") or ec.get("category_scope"))
        for ec in all_evaluation_criteria
    )
    if has_price_in_table and has_pricing_stage:
        return [{
            "type": "PRICING_STAGE_AMBIGUITY",
            "detail": "A 'Price' line item appears inside a category rated-criteria table, and a "
                      "separate top-level pricing stage also exists.",
        }]
    return []


_CONTINUATION_ROW_LABELS = {"price", "presentations", "total points", "total"}


def carry_forward_category_scope(evaluation_occurrences: list[dict]) -> list[dict]:
    """A rated-criteria table's continuation rows (e.g. a 'Price' or
    'Presentations' line that follows a category's other criteria, often
    separated by a page break, with no new category heading restated in
    between) can come back from the focused task without their own
    category_scope. Carry forward the most recently seen non-null scope, in
    list order, but ONLY for a small, named set of known continuation-row
    labels -- never for an arbitrary unscoped occurrence, which could
    legitimately be general/cross-category and must not be guessed at.
    Returns a new list; the input is never mutated, so result.evaluation_
    occurrences stays a faithful record of what was actually extracted."""
    out = []
    last_scope = None
    for occ in evaluation_occurrences:
        occ = dict(occ)
        label = (occ.get("criterion_label") or "").strip().lower()
        if occ.get("category_scope"):
            last_scope = occ["category_scope"]
        elif label in _CONTINUATION_ROW_LABELS and last_scope:
            occ["category_scope"] = last_scope
        out.append(occ)
    return out


def derive_price_criterion_occurrences(evaluation_occurrences: list[dict]) -> list[dict]:
    """A 'Price' line item scored within a category's own rated-criteria
    table (an evaluation_occurrences entry, from the V4 focused rated-
    criteria task) is exactly the PRICE_CRITERION signal
    detect_pricing_stage_ambiguity() needs. The focused pricing task's own
    section window (Stage 4's description) does not include the Rated
    Criteria table, which lives elsewhere in the document -- rather than
    widen that task's input (more tokens, more truncation risk, for a
    single already-available fact), derive the signal deterministically by
    combining the two focused tasks' already-live outputs. No LLM call.
    Callers should pass occurrences through carry_forward_category_scope()
    first -- a 'Price' row is a continuation row and very often has no
    category_scope of its own in the model's raw response."""
    derived = []
    for occ in evaluation_occurrences:
        label = (occ.get("criterion_label") or "").strip().lower()
        if label == "price" and occ.get("category_scope"):
            derived.append({
                "semantic_kind": "PRICE_CRITERION",
                "raw_wording": f"{occ.get('criterion_label')}: {occ.get('weight')}",
                "stage": occ.get("evaluation_stage"),
                "category_scope": occ.get("category_scope"),
                "weight": occ.get("weight"),
                "source_doc": occ.get("source_doc"),
            })
    return derived


_DATE_FORMAT_PATTERNS = [
    re.compile(r'^\d{4}-\d{2}-\d{2}$'),
    re.compile(r'^(week of\s+)?(January|February|March|April|May|June|July|August|September|'
              r'October|November|December)\s+\d{1,2}(st|nd|rd|th)?(,?\s*\d{4})?$', re.I),
    re.compile(r'^\d{1,2}/\d{1,2}/\d{2,4}$'),
]

def _resolve_obs_date(obs: dict) -> str | None:
    d = (obs.get("date") or "").strip()
    if d and any(p.match(d) for p in _DATE_FORMAT_PATTERNS):
        return d
    v = (obs.get("original_value") or "").strip()
    if v and any(p.match(v) for p in _DATE_FORMAT_PATTERNS):
        return v
    return None

def _dates_genuinely_disagree(observations: list[dict]) -> bool:
    """CI-1 Defect F: two ALTERNATE REPRESENTATIONS of the same date
    ("Week of October 26" and "2026-10-26") are not a disagreement, even
    though their literal strings differ. Reuses `procurement_
    normalization._extract_date_window`'s normalization -- the SAME
    primitive `canonicalize_milestones` already uses to merge alternate
    wordings -- and reports a disagreement only when two observations'
    normalized date WINDOWS genuinely fail to overlap.

    Fails conservatively in the direction of honesty: an observation
    whose wording this normalization cannot parse at all still counts as
    a potential disagreement, so a real conflict is never hidden by an
    unparseable wording."""
    import procurement_normalization as _pn

    assumed_year = None
    for obs in observations:
        for field in ("date", "original_value"):
            value = (obs.get(field) or "").strip()
            if len(value) >= 4 and value[:4].isdigit():
                assumed_year = int(value[:4])
                break
        if assumed_year:
            break

    windows = []
    for obs in observations:
        text = f'{obs.get("date") or ""} {obs.get("original_value") or ""}'.strip()
        window = _pn._extract_date_window(text, assumed_year)
        if window is None:
            return True  # unparseable wording -- never silently reconciled
        windows.append(window)

    for i in range(len(windows)):
        for j in range(i + 1, len(windows)):
            a_start, a_end, _ = windows[i]
            b_start, b_end, _ = windows[j]
            if not (a_start <= b_end and b_start <= a_end):
                return True
    return False


def detect_category_date_distinctions(all_typed_observations: list[dict]) -> list[dict]:
    """Not a conflict-detector in the Stage-C sense: this specifically
    distinguishes genuinely different, category-scoped dates sharing the
    same milestone label (Ambiguity 3 in the Deep Verify PDF) from a true
    single-value disagreement, using the same 'scope' signal the narrow
    prompt was explicitly asked to capture.

    CI-1 Defect F: a milestone's canonical identity is
    (event_type, scope), never event_type alone -- grouping by
    semantic_kind only made two DIFFERENT categories' presentation/demo
    dates look like one contradictory milestone. Grouping now uses
    `canonical_procurement.milestone_scope_key`, so an ambiguity is
    raised only when two authoritative sources disagree about the SAME
    scoped event. Distinct scopes sharing an event type are reported
    separately as `scope_distinct_events`, which is information, not a
    conflict."""
    import canonical_procurement as _canon

    by_kind: dict[tuple, list[dict]] = {}
    for obs in all_typed_observations:
        if obs.get("family") != "MILESTONE":
            continue
        kind = obs.get("semantic_kind") or ""
        by_kind.setdefault((kind, _canon.milestone_scope_key(obs)), []).append(obs)
    distinctions = []
    _NON_CLOSING_TERMS = ("selection", "award", "start date", "contract start", "anticipate", "schedule of events")
    for (kind, scope_key), obs_list in by_kind.items():
        filtered_obs = obs_list
        if kind == "SUBMISSION_DEADLINE":
            # Guard against post-closing milestones misclassified as SUBMISSION_DEADLINE
            filtered = []
            for o in obs_list:
                val = (o.get("original_value") or "").lower()
                excerpt = ""
                refs = o.get("source_refs") or []
                if refs and isinstance(refs[0], dict):
                    excerpt = (refs[0].get("excerpt") or "").lower()
                combined = f"{val} {excerpt}"
                if any(t in combined for t in _NON_CLOSING_TERMS):
                    continue
                filtered.append(o)
            filtered_obs = filtered if filtered else obs_list

        dated = [o for o in filtered_obs if _resolve_obs_date(o) is not None]
        values = {_resolve_obs_date(o) for o in dated}
        if len(values) > 1 and _dates_genuinely_disagree(dated):
            distinctions.append({
                "type": "CATEGORY_DATE_DISTINCTION",
                "milestone_kind": kind,
                "scope": list(scope_key),
                "occurrences": dated,
            })
    return distinctions


def derive_scope_distinct_milestones(all_typed_observations: list[dict]) -> list[dict]:
    """CI-1 Defect F's companion to `detect_category_date_distinctions`:
    the same event type occurring on DIFFERENT dates for DIFFERENT
    scopes is not a conflict, but it IS information a bidder needs. This
    returns those scope-distinct event sets so the intelligence is
    preserved rather than simply deleted along with the false ambiguity.

    Emitted only when at least two DIFFERENT scopes are involved and they
    genuinely carry different dates -- never for a single scope, and
    never for unscoped observations (a date disagreement there is a real
    ambiguity, handled by `detect_category_date_distinctions`)."""
    import canonical_procurement as _canon

    by_kind: dict[str, dict[tuple, set]] = {}
    occurrences: dict[str, list[dict]] = {}
    for obs in all_typed_observations:
        if obs.get("family") != "MILESTONE":
            continue
        resolved = _resolve_obs_date(obs)
        if resolved is None:
            continue
        scope_key = _canon.milestone_scope_key(obs)
        if not scope_key:
            continue
        kind = obs.get("semantic_kind") or ""
        by_kind.setdefault(kind, {}).setdefault(scope_key, set()).add(resolved)
        occurrences.setdefault(kind, []).append(obs)

    results = []
    for kind, scopes in by_kind.items():
        if len(scopes) < 2:
            continue
        all_dates = {d for dates in scopes.values() for d in dates}
        if len(all_dates) < 2:
            continue
        results.append({
            "type": "SCOPE_DISTINCT_MILESTONE",
            "milestone_kind": kind,
            "scopes": {"/".join(k): sorted(v) for k, v in scopes.items()},
            "occurrences": occurrences[kind],
        })
    return results


# ---------------------------------------------------------------------------
# Top-level orchestration -- independent of Deep Verify's orchestrator
# (scripts/stage_a_concurrency_orchestrator.py is not imported here). A
# small, self-contained ThreadPoolExecutor is used instead, structurally
# similar by necessity (it is the same safe, standard pattern) but not
# coupled to any Deep Verify module (audit S 9 / user instruction S 9).
# ---------------------------------------------------------------------------

@dataclass
class FastDocumentJob:
    index: int
    name: str
    doc_text: str
    route: str


@dataclass
class FastAnalysisResult:
    doc_metadata_by_doc: dict = field(default_factory=dict)
    typed_observations: list = field(default_factory=list)
    evaluation_criteria: list = field(default_factory=list)
    requirements: list = field(default_factory=list)
    commercial_clauses: list = field(default_factory=list)
    evaluation_occurrences: list = field(default_factory=list)  # V4: focused rated-criteria task
    pricing_occurrences: list = field(default_factory=list)     # V4: focused pricing-structure task
    focused_sections_found: dict = field(default_factory=dict)  # V4: {section_kind: [filenames]}
    page_limits: dict = field(default_factory=dict)         # filename -> int
    skipped_documents: list = field(default_factory=list)
    batched_documents: list = field(default_factory=list)
    documents_by_route: dict = field(default_factory=dict)  # route -> [filenames]
    ambiguities: dict = field(default_factory=dict)
    telemetry: list = field(default_factory=list)
    wall_seconds: float = 0.0
    deterministic_seconds: float = 0.0
    buyer_intelligence: dict | None = None
    # Deterministic (no-LLM) structural parsing results -- see
    # extract_enumerated_service_scope / extract_response_guideline_sections.
    deterministic_service_scope: dict | None = None
    deterministic_response_guidelines: list = field(default_factory=list)
    # Full-Package Analysis Integrity Remediation (2026-09-22). All four
    # deterministic, no-LLM, no-new-model-call -- see procurement_
    # normalization.py / document_provenance.py for the functions that
    # populate these.
    #   Defect A: per-criterion requested-response/evidence text, keyed by
    #   the SAME criterion labels evaluation extraction already produced.
    deterministic_criterion_response_prompts: dict = field(default_factory=dict)
    # CI-1.1 gap 1: the SCOPED form of the field above -- keyed by
    # canonical_procurement.scoped_criterion_map_key(category, criterion),
    # so a criterion label shared by several service categories keeps one
    # independent prompt per category instead of collapsing to whichever
    # document was scanned first. The label-keyed map above is retained
    # unchanged for backward compatibility with already-persisted
    # snapshots and existing consumers.
    scoped_criterion_response_prompts: dict = field(default_factory=dict)
    # CI-1.1 section 2: one canonical, scoped evaluation record per
    # (category, criterion) -- weight, minimum score, response prompt,
    # requested evidence, required examples, personnel/methodology
    # requirements, constraints, authoritative source, provenance. See
    # procurement_normalization.build_scoped_criterion_records.
    scoped_criterion_evaluation: dict = field(default_factory=dict)
    # CI-1.1 gap 2: positive, source-grounded, type-gated scope-of-work
    # items per service category (procurement_normalization.
    # extract_category_scope_items). A RESPONSE_PROMPT can never appear
    # here; a category with no qualifying source material is absent.
    category_scope_items: dict = field(default_factory=dict)
    #   Defect C: canonicalized milestones (see procurement_normalization.
    #   canonicalize_milestones) -- alternate wordings of the SAME event
    #   collapsed to one row; genuinely different dates never merged.
    canonical_milestones: list = field(default_factory=list)
    #   Defect E: filename-pattern-based document relationship
    #   classification (see document_provenance.classify_document_
    #   relationships) -- CANONICAL/AMENDS/AMENDED_BY/DUPLICATE_
    #   REPRESENTATION/REDUNDANT_DERIVATIVE/INDEPENDENT_SOURCE.
    document_relationships: dict = field(default_factory=dict)
    #   Section 8: bounded package-completeness assessment (see
    #   document_provenance.assess_package_completeness).
    package_completeness: dict | None = None


# ---------------------------------------------------------------------------
# Raw-result durability: FastAnalysisResult <-> a JSON-safe, schema-versioned
# snapshot that can be persisted and later reconstructed for report
# regeneration or audit WITHOUT re-invoking the LLM.
#
# This closes a gap discovered during the Phoenix offline closure task: a
# completed run's FastAnalysisResult was used to build structured_intelligence
# and a rendered report_content_snapshot, then discarded -- with no durable
# way to reconstruct it once a newer report adapter needed fields (minimum
# scores, tie-break ranks, deterministic service scope/Response Guidelines)
# that a run's downstream, lossy structured_intelligence/report_content
# never captured in the first place. This boundary is the ONLY supported way
# to produce or consume that snapshot -- callers must not scatter
# dataclasses.asdict(result) / FastAnalysisResult(**payload) elsewhere.
# ---------------------------------------------------------------------------

# Bump the MAJOR component whenever a change could make an older
# deserializer reconstruct an incorrect/incomplete FastAnalysisResult (e.g.
# a field is removed, renamed, or its meaning changes). Bump MINOR for a
# purely additive change (a new optional field) -- deserialize_fast_analysis_result
# tolerates a payload from any MINOR version within the same MAJOR.
# 1.1 -> 1.2 (CI-1.1): purely additive -- scoped_criterion_response_prompts,
# scoped_criterion_evaluation, category_scope_items. No existing field
# changed shape or meaning, so an older 1.x payload still deserializes
# correctly (the new fields fall back to their dataclass defaults).
FAST_ANALYSIS_RAW_SNAPSHOT_SCHEMA_VERSION = "1.2"

# Every FastAnalysisResult field EXCEPT `telemetry`, which is deliberately
# reduced to a compact audit summary rather than stored verbatim -- see
# serialize_fast_analysis_result's docstring.
_RAW_SNAPSHOT_RESULT_FIELDS = tuple(
    f.name for f in _dataclass_fields(FastAnalysisResult) if f.name != "telemetry"
)


class RawSnapshotSchemaError(ValueError):
    """Raised by deserialize_fast_analysis_result when a payload is not a
    genuine raw Fast Analysis snapshot produced by
    serialize_fast_analysis_result -- missing envelope, unsupported major
    schema version, or a malformed 'result' body. This includes the case of
    a structured_intelligence or report_content_snapshot dict passed by
    mistake: those use an entirely different, downstream schema and must
    never be silently accepted as if they were a raw snapshot (fail closed,
    per this module's durability contract -- never guess, never partially
    reconstruct)."""


# BI Token Optimization Phase 5E: the complete call_kind vocabulary this
# module ever writes into telemetry, classified precisely. A prior
# metric (`recovery_or_retry_calls`, still emitted below for backward
# compatibility) classified anything not literally "initial"/"batch" as
# recovery -- which silently counted planned focused-task calls
# (focused_{kind}_initial) and zero-cost split_exhausted bookkeeping rows
# (no provider call was ever made for them) as if they were genuine paid
# retries. This taxonomy distinguishes all of them explicitly.
_PLANNED_PRIMARY_KINDS = {"initial", "batch"}
_TARGETED_RETRY_KINDS = {"targeted_retry"}


def classify_telemetry_entry(entry: dict) -> str:
    """One of PLANNED_PRIMARY / PLANNED_FOCUSED / TRUNCATION_RECOVERY /
    TARGETED_RETRY / BOOKKEEPING / UNKNOWN, from a telemetry row's
    call_kind alone. UNKNOWN is a safety net for any future call_kind
    this function doesn't yet recognize -- it is never silently folded
    into an existing bucket (see _telemetry_audit_summary's
    "other_provider_calls" for how an UNKNOWN provider call still gets
    counted rather than disappearing from the totals)."""
    kind = (entry.get("call_kind") if isinstance(entry, dict) else None) or "unknown"
    if kind in _PLANNED_PRIMARY_KINDS:
        return "PLANNED_PRIMARY"
    if kind.endswith("_initial"):
        return "PLANNED_FOCUSED"
    if kind == "split_exhausted" or kind.endswith("_split_exhausted"):
        return "BOOKKEEPING"
    if kind in ("split_recovery_a", "split_recovery_b") or "_split_recovery_" in kind:
        return "TRUNCATION_RECOVERY"
    if kind in _TARGETED_RETRY_KINDS:
        return "TARGETED_RETRY"
    return "UNKNOWN"


# BI Token Optimization Phase 5E.1: Phase 5E's _is_provider_call() inferred
# "attempted a provider call" from token presence -- but _call_fast_chunk's
# own exception handler (a GENUINE attempted, failed provider call: it only
# exists because execute_messages_create() was actually invoked and raised)
# writes input_tokens=None, output_tokens=None, exactly like a
# split_exhausted bookkeeping row that never attempted anything. Token
# presence cannot distinguish "attempted and failed" from "never attempted"
# -- only the call site itself knows which happened, so every telemetry
# row constructed by _call_fast_chunk (success AND exception paths) and
# every split_exhausted bookkeeping row now carries an explicit
# "provider_call_attempted" boolean written at construction time.
_KNOWN_BOOKKEEPING_CLASSIFICATION = "BOOKKEEPING"


def _is_provider_call(entry: dict) -> bool | None:
    """True/False when determinable; None when a HISTORICAL row (written
    before Phase 5E.1, so it has no "provider_call_attempted" field) has a
    call_kind this function does not recognize -- surfaced separately via
    _telemetry_audit_summary's "unknown_provider_status_rows", never
    silently guessed either way (instruction 4's "fail conservatively /
    surface separately").

    Resolution order:
      1. Explicit "provider_call_attempted" field, when present (every row
         written by this module's current code always has it).
      2. For historical rows without that field: call_kind-based inference
         -- BOOKKEEPING classification -> False, any other RECOGNIZED
         classification -> True. Never token presence alone (that was
         Phase 5E.1's discovered defect)."""
    if not isinstance(entry, dict):
        return False
    if "provider_call_attempted" in entry:
        return bool(entry["provider_call_attempted"])
    classification = classify_telemetry_entry(entry)
    if classification == _KNOWN_BOOKKEEPING_CLASSIFICATION:
        return False
    if classification != "UNKNOWN":
        return True
    # Unrecognized call_kind, no explicit field: reported token usage is
    # unambiguous evidence of a genuine provider call (a bookkeeping row
    # never has real usage, by construction -- see extract_fast_document/
    # run_focused_task, where split_exhausted rows are always written with
    # null tokens). Only when usage is ALSO absent is this genuinely
    # indeterminate -- surfaced separately, never guessed either way.
    if entry.get("input_tokens") is not None or entry.get("output_tokens") is not None:
        return True
    return None


def _telemetry_audit_summary(telemetry: list, wall_seconds: float) -> dict:
    """A compact, JSON-safe summary of per-call telemetry for audit
    purposes -- never the raw per-call list (which is operational detail,
    not analytical output, and is not consumed by any report adapter).

    Corrected in Phase 5E (call-kind taxonomy) and Phase 5E.1 (provider-
    attempt vs. bookkeeping, independent of token presence). Field
    semantics, made explicit per Phase 5E.1 instruction 5:

      provider_call_attempts        -- every row where a provider request
                                        was genuinely made, success or
                                        failure (this is what Phase 5E's
                                        "provider_calls" meant and still
                                        means -- kept under both names).
      successful_provider_calls     -- attempted AND no error recorded
                                        (a response came back).
      failed_provider_calls         -- attempted AND an error was recorded
                                        (the request itself raised).
      usage_reported_provider_calls -- attempted AND the provider actually
                                        reported token usage. Always a
                                        subset of successful_provider_calls
                                        (a failed attempt reports no usage).
      non_provider_bookkeeping_rows -- provider_call_attempted is False.
      unknown_provider_status_rows  -- a historical row with neither the
                                        explicit field nor a recognized
                                        call_kind; not counted as either
                                        attempted or bookkeeping.

    The original `recovery_or_retry_calls`/`total_calls` fields are kept,
    computed exactly as they always were (never redefined), for any
    existing consumer/dashboard that already keys off those exact names."""
    entries = [c for c in telemetry if isinstance(c, dict)]
    classified = [(c, classify_telemetry_entry(c), _is_provider_call(c)) for c in entries]

    provider_entries = [c for c, cls, attempted in classified if attempted is True]
    bookkeeping_entries = [c for c, cls, attempted in classified if attempted is False]
    unknown_status_entries = [c for c, cls, attempted in classified if attempted is None]

    def _provider_count(label: str) -> int:
        return sum(1 for c, cls, attempted in classified if cls == label and attempted is True)

    planned_primary = _provider_count("PLANNED_PRIMARY")
    planned_focused = _provider_count("PLANNED_FOCUSED")
    truncation_recovery = _provider_count("TRUNCATION_RECOVERY")
    targeted_retry = _provider_count("TARGETED_RETRY")
    other_provider = _provider_count("UNKNOWN")
    split_exhausted_rows = sum(1 for c, cls, attempted in classified if cls == "BOOKKEEPING")

    successful = [c for c in provider_entries if c.get("error") is None]
    failed = [c for c in provider_entries if c.get("error") is not None]
    usage_reported = [c for c in provider_entries
                      if c.get("input_tokens") is not None or c.get("output_tokens") is not None]

    # Legacy metric, computed exactly as it always was -- never redefined.
    legacy_recovery_or_retry_calls = sum(
        1 for c in entries if c.get("call_kind") not in ("initial", "batch"))

    return {
        # -- precise taxonomy (Phase 5E + 5E.1) --
        "telemetry_rows": len(entries),
        "provider_call_attempts": len(provider_entries),
        "provider_calls": len(provider_entries),  # Phase 5E name, same meaning, kept for compatibility
        "successful_provider_calls": len(successful),
        "failed_provider_calls": len(failed),
        "usage_reported_provider_calls": len(usage_reported),
        "planned_primary_provider_calls": planned_primary,
        "planned_focused_provider_calls": planned_focused,
        "recovery_provider_calls": truncation_recovery + targeted_retry,
        "truncation_recovery_provider_calls": truncation_recovery,
        "targeted_retry_provider_calls": targeted_retry,
        "other_provider_calls": other_provider,
        "non_provider_bookkeeping_rows": len(bookkeeping_entries),
        "split_exhausted_rows": split_exhausted_rows,
        "unknown_provider_status_rows": len(unknown_status_entries),
        # -- token totals: actual reported usage only (instruction 6) --
        # a failed attempt contributes zero tokens but was still counted
        # above as a provider_call_attempt / failed_provider_call.
        "input_tokens": sum((c.get("input_tokens") or 0) for c in usage_reported),
        "output_tokens": sum((c.get("output_tokens") or 0) for c in usage_reported),
        "wall_seconds": wall_seconds,
        # -- legacy fields, preserved verbatim for backward compatibility --
        "total_calls": len(entries),
        "recovery_or_retry_calls": legacy_recovery_or_retry_calls,
    }


def serialize_fast_analysis_result(result: FastAnalysisResult, *, engine_version: str) -> dict:
    """The one supported way to turn a completed FastAnalysisResult into a
    durable, JSON-safe payload. Every dataclass field already holds only
    plain str/int/float/bool/list/dict/None values, so this is a direct,
    lossless field-by-field copy for everything except `telemetry` (reduced
    to a compact summary -- see _telemetry_audit_summary). Deliberately not
    dataclasses.asdict(result): an explicit field list means a future new
    field is a conscious decision (add it to _RAW_SNAPSHOT_RESULT_FIELDS and
    bump the schema version if needed), not a silent, unreviewed inclusion.

    Returns the full envelope: {schema_version, created_at,
    analysis_engine_version, telemetry_summary, result}."""
    return {
        "schema_version": FAST_ANALYSIS_RAW_SNAPSHOT_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "analysis_engine_version": engine_version,
        "telemetry_summary": _telemetry_audit_summary(result.telemetry, result.wall_seconds),
        "result": {name: getattr(result, name) for name in _RAW_SNAPSHOT_RESULT_FIELDS},
    }


def deserialize_fast_analysis_result(payload: dict) -> FastAnalysisResult:
    """Inverse of serialize_fast_analysis_result. Reconstructs a
    FastAnalysisResult from a persisted snapshot envelope.

    Fails closed (raises RawSnapshotSchemaError) rather than guessing when:
      - `payload` isn't a dict, or is missing the 'schema_version'/'result'
        envelope keys entirely (this is exactly the shape a
        structured_intelligence or report_content_snapshot dict would have
        -- neither carries either key -- so this also rejects those).
      - `schema_version`'s MAJOR component doesn't match this code's
        supported major version.
      - `payload['result']` isn't a dict.

    Tolerant, by design, of:
      - Extra/unknown keys in `payload['result']` (a newer MINOR-version
        payload) -- silently ignored, never raises.
      - Missing optional keys in `payload['result']` (an older MINOR-version
        payload) -- the dataclass's own defaults apply.

    `telemetry` is intentionally NOT reconstructed (it was never stored
    verbatim); the returned result's `telemetry` is always the dataclass
    default (empty list)."""
    if not isinstance(payload, dict) or "schema_version" not in payload or "result" not in payload:
        raise RawSnapshotSchemaError(
            "payload is not a raw Fast Analysis snapshot: missing the "
            "'schema_version'/'result' envelope. A structured_intelligence "
            "or report_content_snapshot dict cannot be used here -- those "
            "use a different, downstream schema.")

    version = payload.get("schema_version")
    supported_major = FAST_ANALYSIS_RAW_SNAPSHOT_SCHEMA_VERSION.split(".")[0]
    version_major = str(version).split(".")[0] if version else None
    if version_major != supported_major:
        raise RawSnapshotSchemaError(
            f"unsupported raw snapshot schema_version {version!r}; this code "
            f"only supports major version {supported_major}.x")

    raw_result = payload.get("result")
    if not isinstance(raw_result, dict):
        raise RawSnapshotSchemaError("payload['result'] is missing or not an object")

    known_fields = set(_RAW_SNAPSHOT_RESULT_FIELDS)
    filtered = {k: v for k, v in raw_result.items() if k in known_fields}
    return FastAnalysisResult(**filtered)


def run_fast_analysis_corpus(documents: list[tuple[str, str]], api_key: str,
                             max_document_concurrency: int = 2,
                             on_task_done=None) -> FastAnalysisResult:
    """documents: list of (filename, parsed_doc_text) for the full corpus.
    Routes, deterministically extracts, batches, and dispatches narrow LLM
    calls with at most `max_document_concurrency` documents/tasks in flight
    at once -- reusing the same bounded-concurrency pattern already
    validated for Deep Verify (Package 4), but implemented independently.

    `on_task_done` (Product Integration Phase 2 hook; optional, default
    None): if provided, called as `on_task_done(kind, payload, task_result)`
    exactly once per completed task, AFTER that task's data has already been
    merged into `result` below -- the same (kind, payload, task_result) the
    dispatch loop itself just used, handed to the caller as-is. This is
    purely observational: it does not change what is extracted, how
    documents are routed/chunked/batched, the concurrency level, or the
    model/token configuration above -- it only exposes an event that already
    happens internally, so a caller (analysis_service.py) can report
    truthful, real-execution-event progress instead of a fake elapsed-time
    estimate. Default None preserves byte-identical behavior for every
    existing caller -- this parameter changes nothing about Fast Analysis
    V4's accepted intelligence behavior."""
    result = FastAnalysisResult()
    texts_by_name = dict(documents)
    wall_start = time.monotonic()

    # 1. Deterministic page-limit extraction -- no LLM, negligible time.
    det_start = time.monotonic()
    for name, doc_text in documents:
        if name in PAGE_LIMIT_DOCUMENTS:
            limit = extract_page_limit_deterministic(doc_text)
            if limit is not None:
                result.page_limits[name] = limit

    # 1b. Deterministic enumerated-scope and Response-Guideline structural
    # parsing -- no LLM, runs generically across every document in the
    # corpus (not restricted to a validated filename list like
    # PAGE_LIMIT_DOCUMENTS above, since both parsers already return
    # None/[] honestly whenever their trigger pattern isn't present, so
    # there is nothing unsafe about checking every document). Keeps the
    # first genuinely non-empty result found, in corpus order.
    for name, doc_text in documents:
        if result.deterministic_service_scope is None:
            scope = extract_enumerated_service_scope(doc_text)
            if scope:
                result.deterministic_service_scope = scope
        if not result.deterministic_response_guidelines:
            rgs = extract_response_guideline_sections(doc_text)
            if rgs:
                result.deterministic_response_guidelines = rgs
    result.deterministic_seconds = round(time.monotonic() - det_start, 6)

    # 2. Route every document.
    tasks: list[tuple[str, list[str]]] = []  # (kind, [filenames]) -- kind: "batch" | "single"
    for name, _ in documents:
        route = route_document(name)
        result.documents_by_route.setdefault(route, []).append(name)
        if route == ROUTE_SKIP:
            result.skipped_documents.append(name)

    batch_members = [n for n in BATCH_GROUP if n in texts_by_name]
    if batch_members:
        tasks.append(("batch", batch_members))
        result.batched_documents = batch_members
    for name, _ in documents:
        route = route_document(name)
        if route == ROUTE_SKIP or name in batch_members:
            continue
        tasks.append(("single", [name]))

    # 2b. V4 section-targeted focused tasks (audit S 3/S 4/S 7): deterministic
    # heading-based location, not tied to any particular document's route --
    # any document whose text contains a recognized "Rated criteria" or
    # "Stage 4. Pricing" heading gets a small, targeted extra call.
    focused_jobs: list[tuple[str, str, str]] = []  # (filename, section_kind, section_text)
    for name, doc_text in documents:
        if route_document(name) == ROUTE_SKIP:
            continue
        for section_kind in ("rated_criteria", "pricing_stage"):
            section_text = find_section(doc_text, section_kind)
            if section_text:
                focused_jobs.append((name, section_kind, section_text))
                result.focused_sections_found.setdefault(section_kind, []).append(name)
    for job in focused_jobs:
        tasks.append(("focused", job))

    # 2c. Phase 5 generalization correction (audit-neutral, additive-only):
    # a document routed to ROUTE_IDENTITY_EVAL_REQ is explicitly instructed
    # NOT to extract commercial_clauses (_IDENTITY_EVAL_REQ_SCHEMA's own
    # "do not extract commercial clauses" line) -- correct and deliberate
    # when that route's document is Bank of Canada's own master RFP, whose
    # commercial clauses live entirely in a separate ROUTE_COMMERCIAL_ONLY
    # document (Appendix G). For a corpus with no DOCUMENT_ROUTING match at
    # all, EVERY document -- including whichever one happens to bundle its
    # own commercial/contractual terms alongside its identity and
    # evaluation content -- is routed to ROUTE_IDENTITY_EVAL_REQ, so those
    # commercial facts were never requested by any schema and never
    # extracted (confirmed live, Product Integration Phase 4). This adds
    # exactly one additional, UNMODIFIED ROUTE_COMMERCIAL_ONLY pass
    # (same schema, same extract_fast_document machinery, same chunking/
    # recovery) per ROUTE_IDENTITY_EVAL_REQ-routed document, purely
    # additive: it does not change that document's existing
    # ROUTE_IDENTITY_EVAL_REQ call in any way (same prompt, same schema,
    # same output), so a corpus with a real, dedicated ROUTE_COMMERCIAL_ONLY
    # document (Bank of Canada's own) is unaffected in everything this
    # extra pass does not itself add. Procurement-agnostic: applies to any
    # corpus with an ROUTE_IDENTITY_EVAL_REQ-routed document, not a
    # buyer-specific branch.
    for name, _ in documents:
        if route_document(name) == ROUTE_IDENTITY_EVAL_REQ:
            tasks.append(("commercial_supplement", [name]))

    # 3. Dispatch, bounded concurrency.
    telemetry_lock = threading.Lock()

    def run_task(kind: str, payload):
        local_telemetry: list = []
        client = get_anthropic_client(api_key=api_key)
        if kind == "batch":
            by_doc = extract_fast_batch(payload, texts_by_name, api_key, client=client,
                                        telemetry=local_telemetry)
            return kind, payload, by_doc, local_telemetry
        if kind == "focused":
            name, section_kind, section_text = payload
            occurrences = run_focused_task(section_kind, name, section_text, api_key,
                                           client=client, telemetry=local_telemetry)
            return kind, payload, occurrences, local_telemetry
        if kind == "commercial_supplement":
            name = payload[0]
            data = extract_fast_document(name, texts_by_name[name], api_key,
                                         route=ROUTE_COMMERCIAL_ONLY,
                                         client=client, telemetry=local_telemetry)
            return kind, payload, {name: data}, local_telemetry
        name = payload[0]
        route = route_document(name)
        data = extract_fast_document(name, texts_by_name[name], api_key, route=route,
                                     client=client, telemetry=local_telemetry)
        return kind, payload, {name: data}, local_telemetry

    with ThreadPoolExecutor(max_workers=max_document_concurrency) as pool:
        futures = {pool.submit(run_task, kind, payload): (kind, payload) for kind, payload in tasks}
        for fut in as_completed(futures):
            kind, payload, task_result, local_telemetry = fut.result()
            with telemetry_lock:
                result.telemetry.extend(local_telemetry)

            if kind == "focused":
                name, section_kind, _ = payload
                target_list = (result.evaluation_occurrences if section_kind == "rated_criteria"
                              else result.pricing_occurrences)
                for occ in task_result:
                    occ = dict(occ)
                    occ.setdefault("source_doc", name)
                    target_list.append(occ)
                if on_task_done is not None:
                    on_task_done(kind, payload, task_result)
                continue

            if kind == "commercial_supplement":
                # Additive only: merges into result.commercial_clauses,
                # exactly like a ROUTE_COMMERCIAL_ONLY document's own single
                # task already does below -- never touches doc_metadata,
                # typed_observations, evaluation_criteria, or requirements,
                # so it cannot alter or duplicate anything this document's
                # own (unmodified) ROUTE_IDENTITY_EVAL_REQ task already
                # contributed.
                name = payload[0]
                data = task_result.get(name, {})
                for c in data.get("commercial_clauses", []):
                    c = dict(c)
                    c.setdefault("source_doc", name)
                    result.commercial_clauses.append(c)
                if on_task_done is not None:
                    on_task_done(kind, payload, task_result)
                continue

            for name, data in task_result.items():
                result.doc_metadata_by_doc[name] = data.get("doc_metadata", {})
                for obs in data.get("typed_observations", []):
                    obs = dict(obs)
                    obs.setdefault("source_doc", name)
                    result.typed_observations.append(obs)
                for ec in data.get("evaluation_criteria", []):
                    ec = dict(ec)
                    ec.setdefault("source_doc", name)
                    result.evaluation_criteria.append(ec)
                for r in data.get("requirements", []):
                    r = dict(r)
                    r.setdefault("source_doc", name)
                    result.requirements.append(r)
                for c in data.get("commercial_clauses", []):
                    c = dict(c)
                    c.setdefault("source_doc", name)
                    result.commercial_clauses.append(c)

            if on_task_done is not None:
                on_task_done(kind, payload, task_result)

    # 4. Deterministic ambiguity detection over the aggregated, occurrence-
    # preserving data (audit S 7). Evaluation-weight conflicts and pricing-
    # stage ambiguity prefer the V4 focused-task occurrences when available;
    # category-date distinctions are unaffected, unchanged since v1. The
    # PRICE_CRITERION signal is derived from the rated-criteria task's own
    # occurrences (see derive_price_criterion_occurrences) and merged in
    # before detection -- the pricing task's own section doesn't include
    # the rated-criteria table, so this is where that signal has to join.
    combined_pricing_occurrences = (
        result.pricing_occurrences
        + derive_price_criterion_occurrences(carry_forward_category_scope(result.evaluation_occurrences)))
    result.ambiguities = {
        "evaluation_weight_conflicts": detect_evaluation_weight_conflicts(
            result.evaluation_occurrences or result.evaluation_criteria),
        "pricing_stage_ambiguity": detect_pricing_stage_ambiguity(
            result.evaluation_criteria, combined_pricing_occurrences),
        "category_date_distinctions": detect_category_date_distinctions(result.typed_observations),
        # CI-1 Defect F: genuinely distinct, differently-scoped events of
        # the same type -- preserved as information, deliberately NOT in
        # the ambiguity list the report renders as "needs clarification".
        "scope_distinct_milestones": derive_scope_distinct_milestones(result.typed_observations),
    }

    # 5. Full-Package Analysis Integrity Remediation (2026-09-22) -- all
    # deterministic, no new model call, run AFTER extraction/aggregation
    # above since each needs already-aggregated data (known criterion
    # labels, the full requirements list, typed_observations) as input.
    import document_provenance as _doc_provenance
    import procurement_normalization as _proc_norm

    # Defect A: per-criterion requested-response/evidence prompts, keyed
    # to the SAME criterion labels evaluation extraction already produced
    # (never invents a new criterion). Runs over every document's own
    # text -- cheap, pure string search, no LLM call.
    known_criterion_labels = sorted({
        (occ.get("criterion_label") or "").strip()
        for occ in result.evaluation_occurrences
        if isinstance(occ, dict) and (occ.get("criterion_label") or "").strip()
    } | {
        (ec.get("stage") or "").strip()
        for ec in result.evaluation_criteria
        if isinstance(ec, dict) and (ec.get("stage") or "").strip()
    })
    scoped_occurrences = carry_forward_category_scope(result.evaluation_occurrences)
    known_category_labels = sorted({
        (occ.get("category_scope") or "").strip()
        for occ in scoped_occurrences
        if isinstance(occ, dict) and (occ.get("category_scope") or "").strip()
    })
    if known_criterion_labels:
        scoped_candidates: dict = {}
        for name, doc_text in documents:
            prompts = _proc_norm.extract_criterion_response_prompts(doc_text, known_criterion_labels)
            for label, entry in prompts.items():
                result.deterministic_criterion_response_prompts.setdefault(label, entry)
            # CI-1.1 gap 1: the same deterministic pass, scoped by the
            # service category each criterion heading sits under (and, for
            # a document that IS one category's own response form, by its
            # filename), so D1's "Corporate Profile" no longer blocks D2's
            # and D3's from being captured at all.
            scoped = _proc_norm.extract_scoped_criterion_response_prompts(
                doc_text, known_criterion_labels, known_category_labels,
                default_category=_proc_norm.category_for_document_name(
                    name, known_category_labels))
            for key, entry in scoped.items():
                entry = dict(entry)
                entry.setdefault("source_doc", name)
                scoped_candidates.setdefault(key, []).append(entry)
        # Which document wins a scoped criterion's prompt is decided by
        # CI-1's response-form source authority, never by scan order.
        result.scoped_criterion_response_prompts = _proc_norm.select_authoritative_prompts(
            scoped_candidates)

    # CI-1.1 section 2: the canonical scoped evaluation records every
    # future specialist agent reads -- built from the SAME occurrences and
    # the SAME scoped prompts above, never a parallel evaluation model.
    result.scoped_criterion_evaluation = _proc_norm.build_scoped_criterion_records(
        scoped_occurrences, result.scoped_criterion_response_prompts,
        provenance_version=FAST_ANALYSIS_RAW_SNAPSHOT_SCHEMA_VERSION)

    # CI-1.1 gap 2: positive, source-grounded, type-gated category scope.
    if known_category_labels:
        result.category_scope_items = _proc_norm.extract_category_scope_items(
            documents, known_category_labels)

    # Defect B: cross-document duplicate requirement canonicalization --
    # replaces result.requirements IN PLACE (same field, same shape plus
    # new source_variants/source_docs/source_refs_all/duplicate_count
    # keys) so every downstream consumer (report adapter, structured_
    # intelligence, BUILD/proposal_outline) sees de-duplicated
    # requirements without a separate opt-in field.
    result.requirements = _proc_norm.canonicalize_requirements(result.requirements)

    # Defect C: milestone canonicalization over MILESTONE-family typed
    # observations -- a SEPARATE field (canonical_milestones), never
    # mutating typed_observations itself, so ambiguity detection and any
    # other typed_observations consumer above is completely unaffected.
    milestone_observations = [
        o for o in result.typed_observations
        if isinstance(o, dict) and o.get("family") == "MILESTONE"
    ]
    if milestone_observations:
        assumed_year = None
        for doc_meta in result.doc_metadata_by_doc.values():
            deadline = (doc_meta or {}).get("submission_deadline")
            if isinstance(deadline, str) and len(deadline) >= 4 and deadline[:4].isdigit():
                assumed_year = int(deadline[:4])
                break
        result.canonical_milestones = _proc_norm.canonicalize_milestones(
            milestone_observations, assumed_year=assumed_year)

    # Defect E + section 8: document relationships and package
    # completeness -- filename/typed-observation-only, no file re-read.
    result.document_relationships = _doc_provenance.classify_document_relationships(list(texts_by_name.keys()))
    result.package_completeness = _doc_provenance.assess_package_completeness(
        result.typed_observations, result.requirements,
        bool(result.evaluation_occurrences or result.evaluation_criteria),
        list(texts_by_name.keys()))

    result.wall_seconds = round(time.monotonic() - wall_start, 6)
    return result
