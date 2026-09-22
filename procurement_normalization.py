"""
procurement_normalization.py -- Full-Package Analysis Integrity
Remediation (Defects A/B/C/D).

CANONICAL PROCUREMENT INTELLIGENCE: normalized requirements, criterion
response/evidence prompts, milestones, and service-category scope. Pure,
deterministic, no I/O, no model call -- operates ONLY on already-extracted
Fast Analysis output (FastAnalysisResult fields / typed_observations /
evaluation occurrences), never re-reads a source document itself.

This is a genuinely separate conceptual layer from document_provenance.py's
CANONICAL SOURCE LAYER (document identity/version/completeness) -- a
future specialist "requirements/compliance" analyzer would consume this
module's `canonicalize_requirements` output directly; a future "evaluation
criteria and requested evidence" specialist would own `extract_criterion_
response_prompts`; a future "SOW/scope/deliverables" specialist would own
`derive_category_scope_summaries`; a future "schedule/submission
mechanics" specialist would own `canonicalize_milestones`. All four
already share ONE deterministic dedup primitive
(`scripts.fast_analysis_report_adapter._fuzzy_word_set`/
`_is_near_duplicate`, reused not reimplemented) rather than four separate
matching philosophies, so parallelizing these into independent specialist
passes later requires no shared-state coordination beyond each one reading
the same already-persisted FastAnalysisResult/structured_intelligence.
"""
from __future__ import annotations

import re

import scripts.fast_analysis_report_adapter as _fast_report_adapter

_fuzzy_word_set = _fast_report_adapter._fuzzy_word_set
_is_near_duplicate = _fast_report_adapter._is_near_duplicate


# ═══════════════════════════════════════════════════════════════════════════
# Defect A -- criterion requested-evidence/response-prompt extraction
# ═══════════════════════════════════════════════════════════════════════════

_SOURCE_MARKER_LINE_RE = re.compile(r'^\[\[SOURCE:.*\]\]\s*$')
MAX_RESPONSE_PROMPT_CHARS = 1500


def _normalize_heading(text: str) -> str:
    return re.sub(r'\s+', ' ', text.strip().rstrip(':')).strip().lower()


def extract_criterion_response_prompts(doc_text: str, known_criterion_labels: list[str]) -> dict[str, dict]:
    """Deterministic, no-LLM extraction of the requested-response/evidence
    text for each ALREADY-KNOWN evaluation criterion label (the SAME
    labels evaluation extraction already produced -- this function never
    invents a criterion, only looks for where the buyer's own response
    form restates one of them as a heading). Generic to any procurement
    document using the common convention of "criterion name as its own
    heading line, followed by prose describing what to include" (e.g.
    Appendix D-style rated-criteria response forms) -- the same class of
    "known boundary marker" technique extract_response_guideline_
    sections already uses for the DIFFERENT "Response Guideline N | ..."
    table convention; this is a second, independent deterministic
    convention, not a replacement.

    A line is treated as a criterion heading when its normalized text
    (whitespace-collapsed, trailing colon stripped, case-insensitive)
    exactly equals one of `known_criterion_labels` -- never a fuzzy or
    partial match, since a heading match must be unambiguous to trust as
    a structural boundary. Everything between one matched heading and the
    next (or end of text) becomes that criterion's response_prompt,
    [[SOURCE: ...]] marker lines stripped out, capped at
    MAX_RESPONSE_PROMPT_CHARS (never silently truncated without saying
    so -- `truncated` is set True when the cap was hit).

    Returns {criterion_label: {"response_prompt": str, "truncated": bool}}
    -- only for labels actually found as headings; a label the text never
    restates is simply absent (never fabricated as "not stated" text --
    the caller distinguishes "found" from "absent" by dict membership)."""
    if not known_criterion_labels or not doc_text:
        return {}
    label_by_normalized = {_normalize_heading(lbl): lbl for lbl in known_criterion_labels if lbl and lbl.strip()}
    if not label_by_normalized:
        return {}

    lines = doc_text.splitlines()
    found: dict[str, list[str]] = {}
    current_label = None
    for line in lines:
        stripped = line.strip()
        if _SOURCE_MARKER_LINE_RE.match(stripped):
            continue
        normalized = _normalize_heading(stripped)
        if normalized in label_by_normalized:
            current_label = label_by_normalized[normalized]
            found.setdefault(current_label, [])
            continue
        if current_label is not None and stripped:
            found[current_label].append(stripped)

    result = {}
    for label, body_lines in found.items():
        text = " ".join(body_lines).strip()
        if not text:
            continue
        truncated = len(text) > MAX_RESPONSE_PROMPT_CHARS
        result[label] = {
            "response_prompt": text[:MAX_RESPONSE_PROMPT_CHARS].strip(),
            "truncated": truncated,
        }
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Defect B -- cross-document duplicate requirement canonicalization
# ═══════════════════════════════════════════════════════════════════════════

# A normative standard/statute identity: an acronym plus its version
# number ("WCAG 2.1", "ISO 27001", "EN 301 549"), or a bare statutory
# acronym ("AODA", "PIPEDA"). Deliberately EXCLUDES conformance-level
# suffixes ("Level AA" vs plain "AA"), which are wording variants of the
# SAME standard citation -- including them would make two restatements of
# one obligation look like two different standards, which is exactly the
# semantic-duplicate failure Defect I is about.
_STANDARD_VERSIONED_RE = re.compile(r'\b([A-Z]{2,6})\s?(\d{1,4}(?:[.\-]\d{1,3})*)\b')
_STANDARD_BARE_RE = re.compile(r'\b(AODA|ADA|WCAG|PIPEDA|FIPPA|GDPR)\b')

_OBLIGATION_TARGET_RE = re.compile(
    r'\b(accessib\w+|privacy|security|confidentialit\w+|insurance|'
    r'bilingual\w+|indemnit\w+|environment\w+)\b', re.IGNORECASE)


def _cited_standards(text: str) -> frozenset:
    """Normative standards/statutes a requirement explicitly cites (e.g.
    "WCAG 2.1 AA", "AODA", "EN 301 549"). Used ONLY as an additional
    same-obligation identity signal inside an already-narrowed candidate
    bucket -- never on its own."""
    body = text or ""
    versioned = {f"{m.group(1).upper()} {m.group(2)}" for m in _STANDARD_VERSIONED_RE.finditer(body)}
    if versioned:
        return frozenset(versioned)
    return frozenset(m.group(1).upper() for m in _STANDARD_BARE_RE.finditer(body))


def _obligation_target(text: str) -> frozenset:
    """The subject-matter target(s) an obligation is about (accessibility,
    privacy, security ...). Two passages citing the same standard AND
    about the same target are the same obligation restated."""
    return frozenset(m.group(1).lower()[:6] for m in _OBLIGATION_TARGET_RE.finditer(text or ""))


def canonicalize_requirements(requirements: list[dict]) -> list[dict]:
    """Collapses semantically-equivalent requirement rows (the SAME
    obligation restated across the main RFP, an appendix, a mandatory-
    criteria form, and/or an amended document) into ONE canonical
    requirement carrying EVERY source variant/reference -- never discards
    a source wording, never merges across `category` (bounded candidate
    narrowing: only requirements sharing the SAME category are ever
    compared, so this is never an all-vs-all pass across the whole
    corpus, and a genuinely different obligation that happens to share a
    category is still protected by the fuzzy-match threshold below).

    Tier 1 (exact): requirement_semantics.normalize_requirement_identity_
    text equality (strict punctuation/whitespace-insensitive exact match).
    Tier 2 (near-duplicate): _is_near_duplicate on the full description
    text (reused, not reimplemented -- the SAME >=70%-smaller-in-larger
    word-overlap heuristic already used for qualification-mechanism/tie-
    break-rule collapsing elsewhere in this codebase). Two requirements
    with fewer than 3 significant words each fail closed to exact-string
    comparison only (never a false collapse of two short, genuinely
    distinct one-line obligations).

    No model call -- entirely deterministic. Fails conservatively: absent
    a Tier 1/2 match, requirements remain separate, even if a human reader
    might recognize a deeper paraphrase as the same obligation.

    Each returned requirement gains `source_variants` (every distinct
    description text merged into it, canonical one first) and
    `source_docs`/`source_refs_all` (every contributing document/
    reference, deduplicated, order preserved) -- the canonical
    `description`/`source_doc`/`source_refs` fields are UNCHANGED for a
    requirement that had no duplicate (still gains the new fields, for a
    uniform output shape)."""
    import canonical_procurement as _canon
    import requirement_semantics as rs

    # CI-1 Defects C + I: every canonical requirement now RETAINS its
    # category applicability, and applicability is part of the dedup
    # candidate key -- two identically-worded obligations scoped to
    # different service categories are two obligations, never one.
    applicability = [_canon.derive_requirement_applicability(r) for r in requirements]

    by_category: dict[str, list[int]] = {}
    for i, r in enumerate(requirements):
        by_category.setdefault((r.get("category") or "").strip(), []).append(i)

    parent = list(range(len(requirements)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    cache_norm = [rs.normalize_requirement_identity_text(r.get("description") or "") for r in requirements]
    cache_words = [_fuzzy_word_set(r.get("description") or "") for r in requirements]
    cache_standards = [_cited_standards(r.get("description") or "") for r in requirements]
    cache_targets = [_obligation_target(r.get("description") or "") for r in requirements]

    for category, indices in by_category.items():
        for a_pos in range(len(indices)):
            i = indices[a_pos]
            for b_pos in range(a_pos + 1, len(indices)):
                j = indices[b_pos]
                # CI-1 Defects C + I: conflicting STATED category
                # applicability is an absolute merge barrier -- the same
                # sentence scoped to Category 1 and to Category 2 is two
                # obligations. Silence is not a conflict (see
                # canonical_procurement.applicability_compatible).
                if not _canon.applicability_compatible(applicability[i], applicability[j]):
                    continue
                if cache_norm[i] and cache_norm[i] == cache_norm[j]:
                    union(i, j)
                    continue
                desc_i, desc_j = requirements[i].get("description") or "", requirements[j].get("description") or ""
                if _is_near_duplicate(desc_i, cache_words[i], desc_j, cache_words[j]):
                    union(i, j)
                    continue
                # Tier 3 (CI-1 Defect I): semantic duplicates whose WORDING
                # differs too much for Tier 2's word-overlap heuristic, but
                # which cite the SAME normative standard/statute AND impose
                # the same obligation target. Bounded by the same
                # same-category+same-applicability candidate narrowing as
                # Tier 1/2 -- never an all-vs-all corpus comparison, and
                # never a model call. Requires a shared standard token,
                # which is a much stronger identity signal than shared
                # prose, so a genuinely different obligation citing a
                # different standard is still kept separate.
                std_i, std_j = cache_standards[i], cache_standards[j]
                if std_i and std_i == std_j and cache_targets[i] == cache_targets[j]:
                    union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(len(requirements)):
        groups.setdefault(find(i), []).append(i)

    canonical_list = []
    for root in sorted(groups.keys()):
        member_indices = groups[root]
        members = [requirements[i] for i in member_indices]
        canonical = dict(members[0])

        seen_desc, source_variants = set(), []
        seen_docs, source_docs = set(), []
        source_refs_all = []
        for m in members:
            desc = (m.get("description") or "").strip()
            if desc and desc not in seen_desc:
                seen_desc.add(desc)
                source_variants.append(desc)
            doc = m.get("source_doc")
            if doc and doc not in seen_docs:
                seen_docs.add(doc)
                source_docs.append(doc)
            for ref in (m.get("source_refs") or []):
                if ref not in source_refs_all:
                    source_refs_all.append(ref)

        canonical["source_variants"] = source_variants
        canonical["source_docs"] = source_docs
        canonical["source_refs_all"] = source_refs_all
        canonical["duplicate_count"] = len(members)

        # CI-1 Defect C: applicability survives canonicalization. The
        # group's applicability is the single stated one its members
        # agree on (never widened, never invented).
        group_applicability = _canon.most_specific_applicability(
            [applicability[i] for i in member_indices])
        canonical["applicability"] = group_applicability["applicability"]
        canonical["applicable_category_ids"] = list(group_applicability["category_ids"])
        canonical["applicability_basis"] = group_applicability["basis"]
        canonical["semantic_type"] = group_applicability["semantic_type"]
        canonical_list.append(canonical)

    return canonical_list


# ═══════════════════════════════════════════════════════════════════════════
# Defect C -- milestone/date canonicalization
# ═══════════════════════════════════════════════════════════════════════════

_WEEK_OF_RE = re.compile(r'week\s+of\s+([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?', re.IGNORECASE)
_ISO_DATE_RE = re.compile(r'(\d{4})-(\d{2})-(\d{2})')
_MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def _extract_date_window(text: str, assumed_year: int | None = None):
    """Returns (start_ordinal, end_ordinal, precision) for the FIRST
    date-like expression found in `text` -- an exact ISO date is a
    zero-width window (start == end); a "Week of <Month> <Day>" mention
    is treated as a 7-day window starting that day (inclusive), never
    guessing which day of that week is meant beyond that stated anchor.
    Returns None when no recognizable date expression is present."""
    import datetime

    m = _ISO_DATE_RE.search(text)
    if m:
        try:
            d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
        return (d.toordinal(), d.toordinal(), "exact")

    m = _WEEK_OF_RE.search(text)
    if m:
        month = _MONTH_NAMES.get(m.group(1).lower())
        if month is None or assumed_year is None:
            return None
        try:
            d = datetime.date(assumed_year, month, int(m.group(2)))
        except ValueError:
            return None
        return (d.toordinal(), d.toordinal() + 6, "week")

    return None


def canonicalize_milestones(raw_date_observations: list[dict], assumed_year: int | None = None) -> list[dict]:
    """Collapses alternate representations of the SAME milestone (e.g. a
    "Week of October 26" mention and a "2026-10-26" mention for the same
    category-scoped event) into one canonical milestone, WITHOUT ever
    collapsing genuinely different dates.

    Two observations are candidates for the SAME milestone only when:
      (1) their `scope` (component/lot/category, whichever is set)
          matches, or both are unscoped, AND
      (2) their `semantic_kind`/label text is a near-duplicate (reuses
          `_is_near_duplicate`, the SAME primitive Defect B's requirement
          dedup reuses), AND
      (3) their date windows (see `_extract_date_window`) OVERLAP.

    A genuine ambiguity (same scope/label, but dates that do NOT overlap,
    or a date expression this function cannot parse) is never silently
    merged -- it is kept as a distinct row, with `ambiguity_state` set so
    a caller can surface it rather than pretend certainty either way.

    Returns a list of canonical milestone dicts: {"label", "scope",
    "normalized_date_start"/"normalized_date_end" (ISO strings, or None
    if unparsed), "original_wording": [...], "source_refs": [...],
    "confidence": "high"|"low", "ambiguity_state": "resolved"|
    "unresolved"}."""
    import datetime

    def _scope_key(obs):
        scope = obs.get("scope") or {}
        if isinstance(scope, dict):
            return tuple(sorted((k, v) for k, v in scope.items() if v))
        return ()

    entries = []
    for obs in raw_date_observations:
        label = (obs.get("semantic_kind") or obs.get("original_value") or "").strip()
        if not label:
            continue
        text_for_date = f'{obs.get("date") or ""} {obs.get("original_value") or ""}'.strip()
        window = _extract_date_window(text_for_date, assumed_year)
        entries.append({
            "label": label, "words": _fuzzy_word_set(label), "scope": _scope_key(obs),
            "window": window, "original_value": obs.get("original_value") or label,
            "source_refs": obs.get("source_refs") or [],
        })

    parent = list(range(len(entries)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            a, b = entries[i], entries[j]
            if a["scope"] != b["scope"]:
                continue
            if not _is_near_duplicate(a["label"], a["words"], b["label"], b["words"]):
                continue
            if a["window"] is None or b["window"] is None:
                continue  # can't confirm overlap -- never merge on label alone
            a_start, a_end, _ = a["window"]
            b_start, b_end, _ = b["window"]
            if a_start <= b_end and b_start <= a_end:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(len(entries)):
        groups.setdefault(find(i), []).append(i)

    canonical = []
    for root in sorted(groups.keys()):
        members = [entries[i] for i in groups[root]]
        windows = [m["window"] for m in members if m["window"] is not None]
        start = min(w[0] for w in windows) if windows else None
        end = max(w[1] for w in windows) if windows else None
        wordings, seen_wording = [], set()
        refs = []
        for m in members:
            if m["original_value"] not in seen_wording:
                seen_wording.add(m["original_value"])
                wordings.append(m["original_value"])
            for r in m["source_refs"]:
                if r not in refs:
                    refs.append(r)
        ambiguous = len(members) > 1 and any(m["window"] is None for m in members)
        canonical.append({
            "label": members[0]["label"],
            "scope": dict(members[0]["scope"]) if members[0]["scope"] else {},
            "normalized_date_start": datetime.date.fromordinal(start).isoformat() if start else None,
            "normalized_date_end": datetime.date.fromordinal(end).isoformat() if end else None,
            "original_wording": wordings,
            "source_refs": refs,
            "confidence": "high" if len(members) == 1 or not ambiguous else "low",
            "ambiguity_state": "unresolved" if ambiguous else "resolved",
        })
    return canonical


# ═══════════════════════════════════════════════════════════════════════════
# Defect D -- service-category scope derivation
# ═══════════════════════════════════════════════════════════════════════════

def derive_category_scope_summaries(
    weights_by_category: dict, criterion_response_prompts: dict[str, dict],
    deterministic_service_scope: dict | None = None,
) -> dict[str, dict]:
    """For each buyer-defined response category, derives a genuine
    scope-of-work summary from material the RFP/appendices actually
    state -- NEVER from the category title alone. Two source-grounded
    signals, both already extracted elsewhere in this remediation, never
    a new extraction pass:

      1. Each of the category's OWN criteria (from `weights_by_category`)
         that has a captured response_prompt (Defect A) AND whose prompt
         text is semantically typed as scope material -- a criterion like
         "Curriculum & Program Design Capability" whose response form
         explicitly describes "designing, developing, delivering and
         updating learning solutions" IS a real, source-grounded scope
         signal for that category. CI-1 Defect B added the type gate:
         a prompt that merely instructs the proponent ("Proponents are to
         describe their organisation...") is a RESPONSE_PROMPT and is
         NEVER offered as scope, no matter how many service words it
         contains. Such prompts are returned separately under
         `response_prompts_not_scope`, not discarded.
      2. `deterministic_service_scope`'s own enumerated services list
         (extract_enumerated_service_scope), when the category name
         shares significant words with the scope's own trigger sentence
         or items -- included only when that overlap exists, never
         attached to every category regardless of relevance.

    A category with neither signal available returns
    `"summary_available": False` -- the caller renders "not stated" for
    that category honestly, never fabricating a generic summary from the
    title."""
    import canonical_procurement as _canon

    result = {}
    scope_items = (deterministic_service_scope or {}).get("items") or []
    scope_words = _fuzzy_word_set(" ".join(scope_items)) if scope_items else frozenset()

    for category, rows in (weights_by_category or {}).items():
        criteria_labels = [r.get("criterion") for r in (rows or []) if isinstance(r, dict) and r.get("criterion")]
        # CI-1 Defect B: a criterion's response prompt is an EVALUATION/
        # RESPONSE instruction ("Proponents are to describe their
        # organisation..."), not a statement of the scope of work. Each
        # prompt is semantically typed and only the ones that genuinely
        # describe the work itself may be offered as scope; the rest are
        # preserved separately, correctly labelled, so the evaluation
        # layer keeps them without the scope layer ever adopting them.
        criteria_prompts = []
        response_prompts_only = []
        for label in criteria_labels:
            if label not in criterion_response_prompts:
                continue
            prompt_text = criterion_response_prompts[label]["response_prompt"]
            entry = {
                "criterion": label,
                "response_prompt": prompt_text,
                "semantic_type": _canon.classify_semantic_type(prompt_text),
            }
            if _canon.is_usable_as_scope(prompt_text):
                criteria_prompts.append(entry)
            else:
                response_prompts_only.append(entry)

        category_words = _fuzzy_word_set(category)
        related_scope_items = []
        if scope_items and category_words and scope_words and (category_words & scope_words):
            related_scope_items = list(scope_items)

        result[category] = {
            "criteria_prompts": criteria_prompts,
            "response_prompts_not_scope": response_prompts_only,
            "enumerated_scope_items": related_scope_items,
            "summary_available": bool(criteria_prompts or related_scope_items),
        }
    return result
