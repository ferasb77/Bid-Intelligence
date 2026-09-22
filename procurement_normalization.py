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
# CI-1.1 gap 1 -- SCOPED criterion response-prompt / requested-evidence
# extraction and retention
# ═══════════════════════════════════════════════════════════════════════════

#: A category heading is a short line. A long paragraph that merely
#: mentions a category name is prose, not a structural boundary.
MAX_CATEGORY_HEADING_CHARS = 160

_DASH_RE = re.compile(r'[‐-―−]')

#: A captured "prompt" body consisting only of a score/points/pass-fail
#: cell -- i.e. the criterion's own row in a weights table, not the
#: buyer's instruction about how to respond to it.
_SCORE_CELL_ONLY_RE = re.compile(
    r'(?:n/?a|pass|fail|pass\s*/\s*fail|\d+\s*(?:points?|pts|%))'
    r'(?:\s*(?:/|,|and)?\s*(?:n/?a|pass|fail|\d+\s*(?:points?|pts|%)))*',
    re.IGNORECASE)


def _normalize_category(text: str) -> str:
    """Category-label normalization: every dash variant folded to '-',
    whitespace collapsed, case-insensitive. A buyer writes the SAME
    category as "Appendix D1 – Learning & Development" in one place and
    "Appendix D1 - Learning & Development" in another; those are one
    category, and a naive string compare would treat them as two."""
    folded = _DASH_RE.sub("-", text or "")
    return re.sub(r'\s+', ' ', folded).strip().rstrip(':').lower()


def _category_heading_match(line: str, category_by_normalized: dict,
                            category_by_token: dict) -> str | None:
    """The buyer-defined service category a heading line announces, or
    None. Three deterministic signals, most explicit first: an exact
    normalized match of the category's own label, a short heading line
    CONTAINING that label, and a short heading line naming the category's
    own unambiguous identifier token (D1/D2/"Category 3"). A token shared
    by more than one known category is never used -- an ambiguous signal
    must not silently pick one."""
    import canonical_procurement as _canon

    stripped = (line or "").strip()
    if not stripped or len(stripped) > MAX_CATEGORY_HEADING_CHARS:
        return None
    normalized = _normalize_category(stripped)
    if normalized in category_by_normalized:
        return category_by_normalized[normalized]
    for norm_label, label in category_by_normalized.items():
        if norm_label and norm_label in normalized:
            return label
    for token in _canon._category_tokens(stripped.upper()):
        owner = category_by_token.get(token)
        if owner:
            return owner
    return None


def _category_indexes(known_category_labels: list[str]) -> tuple[dict, dict]:
    """(normalized label -> label, unambiguous identifier token -> label)."""
    import canonical_procurement as _canon

    by_normalized: dict[str, str] = {}
    token_owners: dict[str, set] = {}
    for label in (known_category_labels or []):
        if not label or not label.strip():
            continue
        by_normalized.setdefault(_normalize_category(label), label)
        for token in _canon._category_tokens(label.upper()):
            token_owners.setdefault(token, set()).add(label)
            # A buyer routinely names the SAME service category by its
            # form identifier in the evaluation tables ("Appendix D2 - HR
            # Advisory") and by its ordinal in the statement of work
            # ("CATEGORY 2: HR ADVISORY"). The shared digit is the link,
            # and it is registered as an ordinary ambiguity-checked token
            # -- if two known categories ever claimed the same ordinal it
            # would be dropped as ambiguous, not guessed at.
            ordinal = re.fullmatch(r'[A-Z](\d{1,2})', token)
            if ordinal:
                token_owners.setdefault(f"CATEGORY {ordinal.group(1)}", set()).add(label)
    by_token = {t: next(iter(owners)) for t, owners in token_owners.items() if len(owners) == 1}
    return by_normalized, by_token


def category_for_document_name(document_name: str,
                               known_category_labels: list[str] | None = None) -> str:
    """The service category a document BELONGS to, from its own filename
    convention ("...Appendix D2 - Rated Criteria Response Form.docx" ->
    the D2 category). The same source-document signal CI-1's
    `derive_requirement_applicability` already trusts for requirements,
    applied to evaluation material: a per-category response form states
    its criteria without repeating the category heading inside, so without
    this its prompts would be honestly-but-uselessly unscoped.

    Returns "" when the filename names no category, or names one
    ambiguously."""
    import canonical_procurement as _canon

    _, by_token = _category_indexes(known_category_labels or [])
    base = (document_name or "").rsplit("/", 1)[-1].upper()
    owners = {by_token[t] for t in _canon._category_tokens(base) if t in by_token}
    return next(iter(owners)) if len(owners) == 1 else ""


def select_authoritative_prompts(candidates_by_key: dict) -> dict[str, dict]:
    """Given every document's candidate entry for each scoped criterion,
    keep the one whose SOURCE DOCUMENT has the most authority over
    response-form material -- CI-1's `AUTHORITY_BY_FIELD_FAMILY
    ["response_form"]` ranking (a rated-criteria response form outranks an
    amendment, which outranks the primary solicitation), never "whichever
    document happened to be scanned first". Ties keep corpus order, so the
    result is deterministic for a given corpus."""
    import canonical_procurement as _canon

    ranking = _canon.AUTHORITY_BY_FIELD_FAMILY["response_form"]
    chosen: dict[str, dict] = {}
    for key, entries in (candidates_by_key or {}).items():
        best, best_rank = None, len(ranking) + 1
        for entry in entries:
            role = _canon.classify_identity_role(entry.get("source_doc") or "")
            rank = ranking.index(role) if role in ranking else len(ranking)
            if rank < best_rank:
                best, best_rank = entry, rank
        if best is not None:
            chosen[key] = best
    return chosen


def extract_scoped_criterion_response_prompts(
    doc_text: str,
    known_criterion_labels: list[str],
    known_category_labels: list[str] | None = None,
    default_category: str = "",
) -> dict[str, dict]:
    """CI-1.1 gap 1. The SCOPED form of `extract_criterion_response_prompts`:
    the same deterministic, no-LLM "criterion label as its own heading
    line" convention, but tracking the service category each heading sits
    under, so the result is keyed by `canonical_procurement.
    scoped_criterion_map_key(category, criterion)` rather than by the
    criterion label alone.

    This is the whole of CI-1.1's first fix. A buyer that scores
    "Corporate Profile" separately in Category 1, Category 2 and Category
    3 states three genuinely different response prompts under three
    category headings in the SAME document; keyed by label alone, the
    first one scanned wins and the other two are lost forever. Keyed by
    (category, criterion), all three survive independently.

    A criterion heading encountered before any category heading is
    retained with an EMPTY category component -- honestly unscoped, never
    assigned to whichever category happens to appear next.

    Returns {scoped_key: {"category", "criterion", "response_prompt",
    "truncated"}} -- only for criterion labels actually found as headings.
    """
    import canonical_procurement as _canon

    if not known_criterion_labels or not doc_text:
        return {}
    label_by_normalized = {_normalize_heading(lbl): lbl
                           for lbl in known_criterion_labels if lbl and lbl.strip()}
    if not label_by_normalized:
        return {}
    category_by_normalized, category_by_token = _category_indexes(known_category_labels or [])

    found: dict[tuple, list[str]] = {}
    order: list[tuple] = []
    # A document that IS one category's own form carries that category
    # even though it never restates the heading inside (see
    # category_for_document_name).
    current_category = default_category or ""
    current_key: tuple | None = None
    for line in doc_text.splitlines():
        stripped = line.strip()
        if _SOURCE_MARKER_LINE_RE.match(stripped):
            continue
        category = _category_heading_match(stripped, category_by_normalized, category_by_token)
        if category is not None:
            # A new category section begins: the previous category's
            # criterion body must never bleed across the boundary.
            current_category = category
            current_key = None
            continue
        normalized = _normalize_heading(stripped)
        if normalized in label_by_normalized:
            current_key = (current_category, label_by_normalized[normalized])
            if current_key not in found:
                found[current_key] = []
                order.append(current_key)
            continue
        if current_key is not None and stripped:
            found[current_key].append(stripped)

    result: dict[str, dict] = {}
    for key in order:
        category, label = key
        text = " ".join(found[key]).strip()
        if not text or _SCORE_CELL_ONLY_RE.fullmatch(text):
            # The criterion label also appears as a row in the weights
            # table, where the only thing following it is that row's own
            # score cell. A score is not a response prompt.
            continue
        result[_canon.scoped_criterion_map_key(category, label)] = {
            "category": category,
            "criterion": label,
            "response_prompt": text[:MAX_RESPONSE_PROMPT_CHARS].strip(),
            "truncated": len(text) > MAX_RESPONSE_PROMPT_CHARS,
        }
    return result


def build_scoped_criterion_records(
    evaluation_occurrences: list[dict],
    scoped_response_prompts: dict[str, dict] | None = None,
    identity_role_by_doc: dict[str, str] | None = None,
    provenance_version: str | None = None,
) -> dict[str, dict]:
    """CI-1.1 section 2. ONE canonical, scoped evaluation record per
    (category, criterion) pair, carrying everything the future Evaluation
    Agent needs to answer "give me all criteria and response prompts for
    Category 2" without ever seeing Category 1's or Category 3's.

    Reuses CI-1's existing canonical structures throughout -- there is
    deliberately NO parallel evaluation model here: identity is
    `canonical_procurement.scoped_criterion_key`, source authority is
    `classify_identity_role`, and the typed evidence facets are
    `extract_requested_evidence_elements`. The record is a projection of
    already-extracted occurrences plus already-extracted prompts, never a
    new extraction or a model call.

    Per record: category/scope, criterion label, weight, minimum score,
    response prompt, requested evidence, required examples, personnel/
    resource requirements, methodology requirements, constraints/limits,
    authoritative source, and provenance. `weight`/`minimum_score` take
    the FIRST non-null value stated for that scoped criterion, and every
    distinct stated variant is preserved in `weight_variants`/
    `minimum_score_variants` so a genuine cross-document disagreement is
    visible rather than silently resolved.

    The authoritative source for an evaluation criterion is chosen with
    the "response_form" field-family authority (a rated-criteria response
    form outranks an amendment, which outranks the primary solicitation)
    -- CI-1's ranking, applied here, not a new one.
    """
    import canonical_procurement as _canon

    prompts = scoped_response_prompts or {}
    roles = identity_role_by_doc or {}
    authority = _canon.AUTHORITY_BY_FIELD_FAMILY["response_form"]

    records: dict[str, dict] = {}
    for occ in (evaluation_occurrences or []):
        if not isinstance(occ, dict):
            continue
        criterion = (occ.get("criterion_label") or "").strip()
        if not criterion:
            continue
        category = (occ.get("category_scope") or "").strip()
        key = _canon.scoped_criterion_map_key(category, criterion)
        record = records.get(key)
        if record is None:
            record = {
                "scoped_key": key,
                "category_scope": category,
                "criterion": criterion,
                # The SAME field name Fast Analysis's own evaluation
                # occurrences and section_analyzer/_match_evaluation_
                # criterion already use, so a scoped record drops straight
                # into every existing downstream consumer (PI-3A's
                # EvaluationContext included) without a parallel model.
                "criterion_label": criterion,
                "weight": None,
                "weight_variants": [],
                "minimum_score": None,
                "minimum_score_variants": [],
                "evaluation_stage": occ.get("evaluation_stage"),
                "parent_heading": occ.get("parent_heading"),
                "response_prompt": None,
                "response_prompt_truncated": False,
                "requested_evidence": [],
                "required_examples": [],
                "personnel_requirements": [],
                "methodology_requirements": [],
                "constraints": [],
                "authoritative_source": None,
                "authoritative_source_role": None,
                "source_docs": [],
                "source_refs": [],
                "occurrence_count": 0,
                "provenance_version": provenance_version,
            }
            records[key] = record

        record["occurrence_count"] += 1
        for field_name, variants_name in (("weight", "weight_variants"),
                                          ("minimum_score", "minimum_score_variants")):
            value = occ.get(field_name)
            if isinstance(value, str) and value.strip():
                value = value.strip()
                if value not in record[variants_name]:
                    record[variants_name].append(value)
                if record[field_name] is None:
                    record[field_name] = value
        doc = occ.get("source_doc")
        if doc and doc not in record["source_docs"]:
            record["source_docs"].append(doc)
        for ref in (occ.get("source_refs") or []):
            if ref not in record["source_refs"]:
                record["source_refs"].append(ref)
        if not record["evaluation_stage"] and occ.get("evaluation_stage"):
            record["evaluation_stage"] = occ["evaluation_stage"]
        if not record["parent_heading"] and occ.get("parent_heading"):
            record["parent_heading"] = occ["parent_heading"]

    for key, record in records.items():
        # Authoritative source: CI-1's per-field-family ranking, never
        # "most recent document wins".
        best_doc, best_rank = None, len(authority) + 1
        for doc in record["source_docs"]:
            role = roles.get(doc) or _canon.classify_identity_role(doc)
            rank = authority.index(role) if role in authority else len(authority)
            if rank < best_rank:
                best_doc, best_rank = doc, rank
        if best_doc:
            record["authoritative_source"] = best_doc
            record["authoritative_source_role"] = (
                roles.get(best_doc) or _canon.classify_identity_role(best_doc))

        entry = prompts.get(key)
        if not entry:
            continue
        prompt_text = entry.get("response_prompt") or ""
        record["response_prompt"] = prompt_text or None
        record["response_prompt_truncated"] = bool(entry.get("truncated"))
        record["semantic_type"] = _canon.classify_semantic_type(prompt_text)
        record.update(_canon.extract_requested_evidence_elements(prompt_text))
    return records


def criteria_for_category(scoped_records: dict[str, dict], category: str) -> list[dict]:
    """The future Evaluation Agent's read contract: every scoped criterion
    record belonging to EXACTLY `category` and nothing else. Category
    matching is normalized (dash/whitespace/case), never fuzzy -- a
    request for Category 2 can never return a Category 3 record."""
    wanted = _normalize_category(category)
    return [dict(rec) for key, rec in sorted((scoped_records or {}).items())
            if _normalize_category(rec.get("category_scope") or "") == wanted]


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

#: A scope passage shorter than this is a fragment/heading, not a usable
#: statement of what is being procured; longer than this is a whole
#: section, which a report cannot render as one item.
MIN_SCOPE_ITEM_CHARS = 40
MAX_SCOPE_ITEM_CHARS = 700
MAX_SCOPE_ITEMS_PER_CATEGORY = 12
#: An enumerated service/workstream line is a deliberately terse phrase
#: ("Competency framework development and validation"), so it has its own,
#: lower floor and its own ceiling.
MIN_SCOPE_BULLET_CHARS = 20
MAX_SCOPE_BULLET_CHARS = 220
MAX_BULLET_CONTINUATION_LINES = 3

#: A scope-of-work section begins. Buyer-agnostic: these are the standard
#: headings/lead-ins under which a solicitation states what it is buying.
_SOW_SECTION_RE = re.compile(
    r'\b(?:statement\s+of\s+work|scope\s+of\s+(?:work|services?)|'
    r'description\s+of\s+(?:the\s+)?(?:services?|work)|services?\s+required|'
    r'required\s+services?|requirements?\s+and\s+deliverables?|'
    r'may\s+require\s+services?|services?\s+to\s+be\s+(?:provided|delivered))\b',
    re.IGNORECASE)

#: A scope-of-work section ends because an evaluation, submission,
#: pricing or contract-terms section has begun. Everything after one of
#: these headings describes how a bid is written, scored or contracted --
#: never what the buyer is procuring.
_NON_SCOPE_SECTION_RE = re.compile(
    r'\b(?:rated\s+criteria|evaluation\s+(?:criteria|process|method\w*|stages?)|'
    r'mandatory\s+criteria|minimum\s+qualification|response\s+(?:form|guideline)|'
    r'proposal\s+response|pricing\s+(?:form|schedule|evaluation)|'
    r'submission\s+(?:instructions?|form|requirements?)|general\s+conditions|'
    r'terms\s+and\s+conditions|contract\s+term|form\s+of\s+(?:agreement|contract)|'
    r'certification|conflict\s+of\s+interest)\b', re.IGNORECASE)

#: Procurement boilerplate that can mention scope vocabulary without ever
#: describing the work: a bidder certification/representation, a buyer's
#: reserved right, or a scoring table. None of these may become a scope
#: item, whatever their keyword classification would otherwise be.
_SCOPE_BOILERPLATE_RE = re.compile(
    r'\b(?:certif(?:ies|ication|y)|represents?\s+and\s+warrants?|'
    r'acknowledges?\s+and\s+agrees?|under\s+no\s+obligation|'
    r'reserves?\s+the\s+right|no\s+obligation\s+to\s+award|'
    r'pass\s*/\s*fail|points\s+available|total\s+points)\b', re.IGNORECASE)
_SCORING_TABLE_RE = re.compile(r'\b\d+\s+points\b', re.IGNORECASE)

_BULLET_RE = re.compile(r'^\s*(?:[•▪■●·⁃∙◦‣]|[-–—*])\s*(.*)$')
#: A line that restarts prose rather than continuing a wrapped bullet.
_PROSE_RESTART_RE = re.compile(
    r'^(?:The|This|These|Those|Proponents?|Bidders?|Respondents?|Suppliers?|'
    r'For\s|Note|Please|All\s|Each\s)\b')
_PAGE_FURNITURE_RE = re.compile(r'^(?:page\s+\d+|\d{1,4})$', re.IGNORECASE)
_OPEN_CLAUSE_RE = re.compile(r'(?:,|\band|\bor|\bof|\bthe|\bfor|\bwith|\bto)$', re.IGNORECASE)


def _continues_wrapped_line(accumulated: str, candidate: str) -> bool:
    """Whether `candidate` is plausibly the wrapped remainder of the
    enumerated item `accumulated`, rather than the start of a new,
    unrelated phrase (in a PDF-extracted table, the adjacent column's
    text can follow a list item on the very next line). A newly
    capitalized phrase only continues an item whose own text visibly ends
    mid-clause."""
    if not accumulated.strip():
        # A bullet marker alone on its own line (common in PDF-extracted
        # tables): the item's text IS the next line.
        return True
    if not candidate[:1].isupper():
        return True
    return bool(_OPEN_CLAUSE_RE.search(accumulated.rstrip()))


def extract_category_scope_items(
    documents: list[tuple],
    known_category_labels: list[str] | None = None,
) -> dict[str, list[dict]]:
    """CI-1.1 gap 2: POSITIVE, source-grounded scope-of-work extraction.

    CI-1 correctly STOPPED evaluation response prompts from masquerading
    as scope, which left the Bank of Canada's three service categories
    honestly empty rather than wrongly populated. This function is the
    positive half: it looks in the source documents themselves for
    passages that genuinely describe services, workstreams, activities,
    deliverables, resource expectations or delivery modalities, and
    attributes each to the service category whose heading it sits under.

    Entirely deterministic -- paragraph segmentation plus the SAME
    category-heading tracker `extract_scoped_criterion_response_prompts`
    uses, plus CI-1's own `canonical_procurement.is_usable_as_scope` type
    gate. No model call, no re-reading of anything the corpus did not
    already provide.

    The type gate is the hard guarantee task section 3 demands: a passage
    classified RESPONSE_PROMPT or REQUESTED_EVIDENCE can NEVER become a
    scope item, however many service words it contains, because
    `classify_semantic_type` tests those two first. A passage that
    supports no positive scope classification is likewise excluded
    (UNKNOWN is not usable as scope) -- a category with no qualifying
    source material stays empty, honestly, rather than being filled.

    `documents` is the same list of (filename, text) pairs Fast Analysis
    already holds. Returns {category_label: [scope_item, ...]}; passages
    found before any category heading are returned under the empty-string
    key, explicitly unscoped, never assigned to a category."""
    import canonical_procurement as _canon

    category_by_normalized, category_by_token = _category_indexes(known_category_labels or [])
    by_category: dict[str, list[dict]] = {}
    seen: set[str] = set()

    def emit(category: str, text: str, hint: str | None, source_doc: str,
             minimum: int, maximum: int):
        text = re.sub(r'\s+', ' ', text).strip(" \t-–—;")
        if len(text) < minimum or len(text) > maximum:
            return
        # Fail-closed boilerplate rejection, BEFORE typing: a
        # certification, a reserved right or a scoring table states no
        # scope however much scope vocabulary it borrows.
        if _SCOPE_BOILERPLATE_RE.search(text):
            return
        if len(_SCORING_TABLE_RE.findall(text)) >= 2:
            return
        semantic_type = _canon.classify_semantic_type(text, hint)
        # THE guarantee of task section 3: classify_semantic_type tests
        # RESPONSE_PROMPT/REQUESTED_EVIDENCE first and they are not in
        # SCOPE_SEMANTIC_TYPES, so an evaluation instruction can never
        # arrive here -- not even with an explicit structural hint.
        if semantic_type not in _canon.SCOPE_SEMANTIC_TYPES:
            return
        fingerprint = re.sub(r'\W+', ' ', text).strip().lower()
        if fingerprint in seen:
            return
        seen.add(fingerprint)
        bucket = by_category.setdefault(category, [])
        if len(bucket) >= MAX_SCOPE_ITEMS_PER_CATEGORY:
            return
        bucket.append({
            "text": text,
            "semantic_type": semantic_type,
            "category_scope": category,
            "source_doc": source_doc,
        })

    for name, doc_text in (documents or []):
        if not doc_text:
            continue
        current_category = ""
        in_scope_section = False
        block: list[str] = []
        bullet: list[str] = []
        bullet_continuations = 0

        def flush_bullet(category: str):
            nonlocal bullet_continuations
            if bullet:
                emit(category, " ".join(bullet), _canon.SEMANTIC_SERVICE, name,
                     MIN_SCOPE_BULLET_CHARS, MAX_SCOPE_BULLET_CHARS)
            bullet.clear()
            bullet_continuations = 0

        def flush_block(category: str):
            if block:
                emit(category, " ".join(block), None, name,
                     MIN_SCOPE_ITEM_CHARS, MAX_SCOPE_ITEM_CHARS)
            block.clear()

        for line in doc_text.splitlines():
            stripped = line.strip()
            if _SOURCE_MARKER_LINE_RE.match(stripped) or _PAGE_FURNITURE_RE.match(stripped):
                continue

            category = _category_heading_match(stripped, category_by_normalized, category_by_token)
            if category is not None:
                flush_bullet(current_category)
                flush_block(current_category)
                current_category = category
                continue

            if not stripped:
                flush_bullet(current_category)
                flush_block(current_category)
                continue

            # Section tracking. A non-scope heading closes the scope
            # section BEFORE a scope heading could reopen it, so a line
            # like "Evaluation of the statement of work" never reopens it.
            is_heading = len(stripped) <= MAX_CATEGORY_HEADING_CHARS
            if is_heading and _NON_SCOPE_SECTION_RE.search(stripped):
                flush_bullet(current_category)
                flush_block(current_category)
                in_scope_section = False
                continue
            if _SOW_SECTION_RE.search(stripped):
                flush_bullet(current_category)
                flush_block(current_category)
                in_scope_section = True
                if is_heading:
                    continue

            marker = _BULLET_RE.match(stripped)
            if marker:
                flush_bullet(current_category)
                flush_block(current_category)
                # An enumerated item is only read as scope inside a
                # declared scope-of-work section. Outside one, a bullet is
                # just as likely to be a response-form instruction's own
                # sub-list, so it is dropped rather than guessed at. A
                # PARAGRAPH, by contrast, is always considered, because it
                # must pass the semantic-type gate on its own words.
                if in_scope_section:
                    bullet.append(marker.group(1).strip())
                continue

            if bullet:
                # A wrapped continuation of the current enumerated item --
                # bounded, and never allowed to swallow the paragraph or
                # adjacent table column that follows the list.
                joined = " ".join(bullet)
                if (bullet_continuations < MAX_BULLET_CONTINUATION_LINES
                        and not _PROSE_RESTART_RE.match(stripped)
                        and _continues_wrapped_line(joined, stripped)
                        and len(joined) < MAX_SCOPE_BULLET_CHARS):
                    bullet.append(stripped)
                    bullet_continuations += 1
                    continue
                flush_bullet(current_category)

            block.append(stripped)

        flush_bullet(current_category)
        flush_block(current_category)

    return by_category


def scope_items_for_category(category_scope_items: dict, category: str) -> list[dict]:
    """The future Scope Agent's read contract: every source-grounded scope
    item for EXACTLY `category`, and never an evaluation prompt. Returns
    [] when the source package genuinely states no scope for it."""
    wanted = _normalize_category(category)
    for label, items in (category_scope_items or {}).items():
        if _normalize_category(label) == wanted:
            return [dict(i) for i in items]
    return []


def derive_category_scope_summaries(
    weights_by_category: dict, criterion_response_prompts: dict[str, dict],
    deterministic_service_scope: dict | None = None,
    category_scope_items: dict | None = None,
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
            # CI-1.1 gap 1: prefer this category's OWN scoped prompt. The
            # label-keyed lookup remains as a fallback for an older
            # persisted snapshot that only has the collapsed map.
            entry = (criterion_response_prompts or {}).get(
                _canon.scoped_criterion_map_key(category, label))
            if entry is None:
                entry = (criterion_response_prompts or {}).get(label)
            if entry is None:
                continue
            prompt_text = entry["response_prompt"]
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

        # CI-1.1 gap 2: genuine, source-grounded SOW/service-scope material
        # extracted from the category's own section of the source package
        # (see extract_category_scope_items) -- the strongest signal when
        # present, and still type-gated, so a response prompt can never
        # arrive here.
        sourced_items = scope_items_for_category(category_scope_items, category)

        result[category] = {
            "criteria_prompts": criteria_prompts,
            "response_prompts_not_scope": response_prompts_only,
            "enumerated_scope_items": related_scope_items,
            "source_scope_items": sourced_items,
            "summary_available": bool(criteria_prompts or related_scope_items or sourced_items),
        }
    return result
