"""procurement_intelligence.py -- Deterministic Procurement Intelligence Foundation.

Preserves and isolates deterministic, no-LLM extraction capabilities:
- Document authority and classification
- Explicit budget, volume, timetable, and objective facts
- Criterion response prompt extraction with split-line heading normalization and complete passage retention
- Summary table boundary protection
- Canonical buyer truth assembly

This module is strictly isolated behind the UNDERSTAND boundary to preserve
frozen CHECK semantics in shared canonical modules.
"""
from __future__ import annotations

import re
from typing import Iterable

_PAGE_LIMIT_RE = re.compile(
    r'(?:not\s+exceed|maximum\s+of|limit\s+of|exceed)\s+'
    r'(?:(\d+)\s*pages?|(\w+)\s*\((\d+)\)\s*pages?)',
    re.IGNORECASE,
)

_BUDGET_RE = re.compile(
    r'(?is)(?:estimated\s+budget[\s\S]{0,180}?)(?:\$|CAD\s*)\s*([\d,]+)\s*[-\u2013]\s*(?:\$|CAD\s*)?\s*([\d,]+)\s+per\s+(year|month|quarter)'
)
_RANGE_DASH = r'[-\u2013\u2014\ufffd]'
_SESSION_RANGE_RE = re.compile(r'(?is)(\d+)\s*(?:' + _RANGE_DASH + r'|to)\s*(\d+)\s+(?:[a-z -]{0,30}?)sessions?')
_WORD_SESSION_RANGE_RE = re.compile(
    r'(?is)(one|two|three|four|five|six|seven|eight|nine|ten)\s*\([^)]*\)\s*(?:' + _RANGE_DASH + r'|to)\s*(\d+)\s+(?:[a-z0-9 -]{0,20}?)sessions?'
)
_WORD_WORD_SESSION_RANGE_RE = re.compile(
    r'(?is)(one|two|three|four|five|six|seven|eight|nine|ten)\s*\([^)]*\)\s*(?:' + _RANGE_DASH + r'|to)\s*(one|two|three|four|five|six|seven|eight|nine|ten)\s*\([^)]*\)\s+(?:[a-z0-9 -]{0,20}?)sessions?'
)
_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_SINGLE_SESSION_RE = re.compile(r'(?is)(?:up\s+to\s+)?(\d+)\s+(?:one[- ]?hour\s+)?sessions?')

_SOURCE_MARKER_LINE_RE = re.compile(r'^\[\[SOURCE:.*\]\]\s*$')
MAX_RESPONSE_PROMPT_CHARS = 1500


def _normalize_heading(text: str) -> str:
    return re.sub(r'\s+', ' ', text.strip().rstrip(':')).strip().lower()


def _criterion_heading_label(line: str, label_by_normalized: dict[str, str]) -> str | None:
    """Return a known criterion when line is its structural heading.

    RFP PDFs commonly flatten a table heading into lines such as:
    ``1. Firm Experience & Capabilities (30%)`` or ``2. Team ... – Weight (10 %)``.
    This normalises numbering and score/weight decorations without fuzzy-matching prose.
    """
    raw = re.sub(r'\s+', ' ', (line or '').strip()).strip(':')
    if not raw or len(raw) > 240:
        return None
    candidates = [raw]
    candidates.append(re.sub(r'^\s*\d+[.)]\s*', '', raw))
    for value in list(candidates):
        value = re.sub(r'\s*[\u2010-\u2015-]\s*weight\s*\([^)]*\)\s*$', '', value, flags=re.I)
        value = re.sub(r'\s*\([^)]*%[^)]*\)\s*$', '', value)
        value = re.sub(r'\s+weight\s*[:\-]?\s*\([^)]*\)\s*$', '', value, flags=re.I)
        value = re.sub(r'\s*[\u2010-\u2015-]\s*$', '', value)
        candidates.append(value.strip())
    for candidate in candidates:
        hit = label_by_normalized.get(_normalize_heading(candidate))
        if hit:
            return hit
    return None


def _source_page_for_line(lines: list[str], line_no: int) -> int | None:
    for i in range(min(line_no, len(lines) - 1), -1, -1):
        m = re.search(r'\[\[SOURCE:[^\]]*PAGE:\s*(\d+)', lines[i])
        if m:
            return int(m.group(1))
    return None


def extract_page_limit_deterministic(doc_text: str) -> int | None:
    """Return stated page limit from header text, or None."""
    m = _PAGE_LIMIT_RE.search(doc_text)
    if not m:
        return None
    return int(m.group(1)) if m.group(1) else int(m.group(3))


def extract_deterministic_procurement_facts(doc_text: str, source_doc: str = "") -> list[dict]:
    """Capture explicit budget, volume, objectives, and timetable facts."""
    if not doc_text:
        return []
    lines = doc_text.splitlines()
    facts: list[dict] = []

    def add(family: str, kind: str, value: object, excerpt: str, line_no: int) -> None:
        page = _source_page_for_line(lines, line_no)
        facts.append({
            "family": family,
            "semantic_kind": kind,
            "value": value,
            "text": excerpt.strip(),
            "source_doc": source_doc,
            "source_refs": ([f"page:{page}"] if page else []),
        })

    m = _BUDGET_RE.search(doc_text)
    if m:
        add(
            "MONETARY",
            "ESTIMATED_BUDGET",
            {
                "currency": "CAD",
                "minimum": int(m.group(1).replace(',', '')),
                "maximum": int(m.group(2).replace(',', '')),
                "period": m.group(3).lower(),
            },
            m.group(0),
            doc_text[:m.start()].count('\n'),
        )

    for i, line in enumerate(lines):
        sm = _SESSION_RANGE_RE.search(line)
        if not sm:
            wm = _WORD_SESSION_RANGE_RE.search(line)
            if wm:
                sm = (int(_WORD_NUMBERS[wm.group(1).lower()]), int(wm.group(2)))
        if not sm:
            ww = _WORD_WORD_SESSION_RANGE_RE.search(line)
            if ww:
                sm = (int(_WORD_NUMBERS[ww.group(1).lower()]), int(_WORD_NUMBERS[ww.group(2).lower()]))
        if sm:
            annual = bool(re.search(r'\bper\s+year\b|\bannually\b', line, re.I))
            lo, hi = sm if isinstance(sm, tuple) else (int(sm.group(1)), int(sm.group(2)))
            add(
                "VOLUME",
                "ANNUAL_SESSION_VOLUME" if annual else "SESSION_VOLUME_RANGE",
                {"minimum": lo, "maximum": hi, "unit": "sessions", **({"period": "annual"} if annual else {})},
                line,
                i,
            )
        elif re.search(r'\bsessions?\b', line, re.I):
            sm_single = _SINGLE_SESSION_RE.search(line)
            if sm_single:
                add(
                    "VOLUME",
                    "SESSION_VOLUME",
                    {"quantity": int(sm_single.group(1)), "unit": "sessions"},
                    line,
                    i,
                )

    in_objectives = False
    objective_start_seen = False
    objective_page = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if (not objective_start_seen and re.search(
                r'\b(?:primary\s+)?(?:coaching\s+)?objectives?\b\s*(?:will\s+achieve|include|are\s+as\s+follows|:|$)',
                stripped, re.I)):
            in_objectives = True
            objective_start_seen = True
            continue
        if in_objectives:
            pm = re.search(r'\[\[SOURCE:[^\]]*PAGE:\s*(\d+)', stripped)
            if pm:
                objective_page = int(pm.group(1)) if objective_page is None else objective_page
                continue
            if re.search(r'\b(?:will\s+achieve|include|are\s+as\s+follows|the\s+following:?)\b', stripped, re.I):
                continue
            if re.match(r'^(?:the agreement term|information table|rfp timetable|appendix)\b', stripped, re.I):
                in_objectives = False
                continue
            bullet = re.sub(r'^[•\-]\s*', '', stripped).strip()
            if bullet and len(bullet) > 12:
                if re.match(r'^(?:the agreement term|appendix|section)\b', bullet, re.I):
                    in_objectives = False
                else:
                    add("OBJECTIVE", "PROCUREMENT_OBJECTIVE", bullet, stripped, i)

    timetable = {
        "RFP issue date": "RFP_ISSUE_DATE",
        "Deadline for Proponent Questions": "QUESTION_DEADLINE",
        "Deadline for Issuing Addenda": "ADDENDA_DEADLINE",
        "Submission Deadline": "SUBMISSION_DEADLINE",
        "Rectification Period": "RECTIFICATION_PERIOD",
    }
    for i, line in enumerate(lines):
        for label, kind in timetable.items():
            normalized_line = re.sub(r'\s+', ' ', line.strip()).lower()
            label_lines = [normalized_line]
            if i + 1 < len(lines):
                label_lines.append((normalized_line + ' ' + re.sub(r'\s+', ' ', lines[i + 1].strip())).strip().lower())
            matched = next((offset for offset, candidate in enumerate(label_lines)
                            if candidate == label.lower()), None)
            if matched is not None:
                value_start = i + (2 if matched == 1 else 1)
                values = []
                for candidate in lines[value_start:value_start + 6]:
                    x = candidate.strip()
                    if not x or re.match(r'^\[\[SOURCE:', x):
                        continue
                    if values and re.search(r'\b20\d{2}\b', x) and any(re.search(r'\b20\d{2}\b', prior) for prior in values):
                        break
                    if re.search(r'\b20\d{2}\b', x) or re.search(r'\b(?:business|MST|time)\b', x, re.I):
                        values.append(x)
                    if values and (re.search(r'\b20\d{2}\b', x) or
                                   re.search(r'\b(?:business|MST|time)\b', x, re.I)):
                        continue
                    if values:
                        break
                if values:
                    add("MILESTONE", kind, " ".join(values[:2]), " ".join(values[:2]), i)
                break
    return facts


def extract_criterion_response_prompts(
    doc_text: str, known_criterion_labels: list[str]
) -> dict[str, dict]:
    """Extract requested-response text for already-known evaluation criteria.

    Retains the complete passage (complete=True) rather than truncating.
    """
    if not doc_text or not known_criterion_labels:
        return {}
    label_by_normalized = {_normalize_heading(lbl): lbl for lbl in known_criterion_labels}
    lines = doc_text.splitlines()
    found: dict[str, list[str]] = {}
    current_label = None
    rated_section = False
    explicit_section = False
    for line in lines:
        stripped = line.strip()
        if _SOURCE_MARKER_LINE_RE.match(stripped):
            continue
        if re.match(r'^[A-Z][.)]\s+EVALUATION OF RATED CRITERIA', stripped, re.I):
            rated_section = True
            explicit_section = True
            current_label = None
            continue
        if re.match(r'^[A-Z][.)]\s+EVALUATION OF PRICING', stripped, re.I):
            rated_section = False
            explicit_section = True
            current_label = None
            continue
        if _normalize_heading(stripped) in {"c.", "c"}:
            rated_section = False
            current_label = None
            continue
        label = _criterion_heading_label(stripped, label_by_normalized)
        if label and label.lower() == "price" and not re.match(r'^\s*\d+[.)]\s*', stripped):
            continue
        if label and (rated_section or not explicit_section or re.match(r'^\s*\d+[.)]\s*', stripped)):
            current_label = label
            found[current_label] = []
            continue
        if re.match(r'^\s*weight\s*[:\-]?\s*\([^)]*\)\s*$', stripped, re.I):
            continue
        if current_label is not None and stripped:
            found[current_label].append(stripped)

    result: dict[str, dict] = {}
    for label, body_lines in found.items():
        text = " ".join(body_lines).strip()
        if not text:
            continue
        result[label] = {
            "response_prompt": text,
            "truncated": len(text) > 1500,
            "complete": True,
        }
    return result


def extract_scoped_criterion_response_prompts(
    doc_text: str,
    known_criterion_labels: list[str],
    default_category: str = "",
) -> dict[str, dict]:
    """Scoped extraction keeping category prefix ||criterion."""
    if not doc_text or not known_criterion_labels:
        return {}
    label_by_normalized = {_normalize_heading(lbl): lbl for lbl in known_criterion_labels}
    found: dict[tuple, list[str]] = {}
    order: list[tuple] = []
    current_category = default_category or ""
    current_key: tuple | None = None
    rated_section = False
    explicit_section = False
    for line in doc_text.splitlines():
        stripped = line.strip()
        if _SOURCE_MARKER_LINE_RE.match(stripped):
            continue
        if re.match(r'^[A-Z][.)]\s+EVALUATION OF RATED CRITERIA', stripped, re.I):
            rated_section = True
            explicit_section = True
            current_key = None
            continue
        if re.match(r'^[A-Z][.)]\s+EVALUATION OF PRICING', stripped, re.I):
            rated_section = False
            explicit_section = True
            current_key = None
            continue
        if _normalize_heading(stripped) in {"c.", "c"}:
            rated_section = False
            current_key = None
            continue
        label = _criterion_heading_label(stripped, label_by_normalized)
        if label and label.lower() == "price" and not re.match(r'^\s*\d+[.)]\s*', stripped):
            continue
        if label and (rated_section or not explicit_section or re.match(r'^\s*\d+[.)]\s*', stripped)):
            current_key = (current_category, label)
            if current_key not in found:
                order.append(current_key)
            found[current_key] = []
            continue
        if re.match(r'^\s*weight\s*[:\-]?\s*\([^)]*\)\s*$', stripped, re.I):
            continue
        if current_key is not None and stripped:
            found[current_key].append(stripped)

    result: dict[str, dict] = {}
    for category, label in order:
        body_lines = found.get((category, label)) or []
        text = " ".join(body_lines).strip()
        if not text:
            continue
        key = f"{category.lower()}||{label.lower()}" if category else f"||{label.lower()}"
        result[key] = {
            "category": category,
            "criterion": label,
            "response_prompt": text,
            "truncated": len(text) > 1500,
            "complete": True,
        }
    return result
