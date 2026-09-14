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
from dataclasses import dataclass, field
from datetime import datetime, timezone

from config import get_anthropic_client
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


def route_document(filename: str) -> str:
    """Deterministic routing per the audit's matrix (S D). Unknown documents
    (outside the validated corpus) fall back to the broadest narrow mode
    rather than being silently skipped or sent the universal Deep Verify
    schema."""
    return DOCUMENT_ROUTING.get(filename, ROUTE_IDENTITY_EVAL_REQ)


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

Return ONLY valid JSON:
{
  "evaluation_criteria": [
    {
      "stage": "Criterion or stage name exactly as stated",
      "parent_stage": "Parent heading/table title, or null",
      "weight": "Exact weight/points string as stated, e.g. '35 points' or '25%', or null",
      "weight_unit": "Points|Percent|Other|None",
      "weight_basis": "Overall|Within Parent|Unknown",
      "threshold": "Minimum passing threshold as stated (e.g. '5 years experience'), or null",
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
     FRAMEWORK, LOTS).
   Preserve every distinct occurrence (do not merge repeats into one).
3. evaluation_criteria: """ + _EVAL_SCHEMA.strip() + """
4. requirements, restricted to exactly three topics -- do not extract any other requirement:
   (a) the service-category scope description for each named category/lot (what each category
       includes), (b) the mandatory submission mechanics (how/where/when to submit, what
       forms are required, bilingual/accessibility/security-clearance obligations), and
       (c) any stated pricing-evaluation consequence rule (e.g. what happens if a proponent's
       pricing appears abnormally low, including any required explanation or contract-security/
       performance-bond consequence).

Return ONLY valid JSON:
{
  "doc_metadata": {"title": null, "client": null, "file_number": null,
                    "submission_deadline": null, "submission_time": null,
                    "clarification_deadline": null},
  "typed_observations": [
    {"family": "...", "semantic_kind": "...", "original_value": "...", "source_refs": [],
     "scope": {"component": null, "lot": null, "category": null}, "date": null, "duration": null,
     "unit": null, "option_count": null}
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

Return ONLY valid JSON:
{
  "evaluation_occurrences": [
    {
      "criterion_label": "Exact criterion or line-item name as stated (e.g. 'Corporate Profile', 'Price')",
      "weight": "Exact weight/points value as stated, e.g. '35 points' or '25%', or null",
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
        response = client.messages.create(
            model=FAST_MODEL, max_tokens=FAST_MAX_OUTPUT_TOKENS, temperature=FAST_TEMPERATURE,
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
    response = client.messages.create(
        model=FAST_MODEL, max_tokens=FAST_MAX_OUTPUT_TOKENS, temperature=FAST_TEMPERATURE,
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


def detect_category_date_distinctions(all_typed_observations: list[dict]) -> list[dict]:
    """Not a conflict-detector in the Stage-C sense: this specifically
    distinguishes genuinely different, category-scoped dates sharing the
    same milestone label (Ambiguity 3 in the Deep Verify PDF) from a true
    single-value disagreement, using the same 'scope' signal the narrow
    prompt was explicitly asked to capture."""
    by_kind: dict[str, list[dict]] = {}
    for obs in all_typed_observations:
        if obs.get("family") != "MILESTONE":
            continue
        kind = obs.get("semantic_kind") or ""
        by_kind.setdefault(kind, []).append(obs)
    distinctions = []
    for kind, obs_list in by_kind.items():
        dated = [o for o in obs_list if o.get("date") or o.get("original_value")]
        values = {(o.get("date") or o.get("original_value")) for o in dated}
        if len(values) > 1:
            distinctions.append({
                "type": "CATEGORY_DATE_DISTINCTION",
                "milestone_kind": kind,
                "occurrences": dated,
            })
    return distinctions


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
    }

    result.wall_seconds = round(time.monotonic() - wall_start, 6)
    return result
