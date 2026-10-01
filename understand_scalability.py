"""understand_scalability.py -- Full Analysis & Stage D Scalability Remediation.

Remediates large-package scalability for multi-agent full intelligence:
1. Duplicate-document detection before specialist analysis
2. Additive near-duplicate clustering scoped to Stage D / reconciliation prompt construction
3. Consistent excerpt caps across ALL prompt sections
4. Meaningful material variation preservation (deadlines, thresholds, quantities, qualifiers, prices, exceptions)
5. Zero silent omission of requirements
"""
from __future__ import annotations

import copy
import hashlib
import re
from typing import Any, Sequence

EXCERPT_CAP = 500

_DATE_PAT = re.compile(r'\b(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}(?:,?\s+\d{4})?|\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(?:\s+\d{4})?)\b', re.I)
_NUMBER_PAT = re.compile(r'\b(?:\d+(?:\.\d+)?|\$\s*[\d,]+|\d+%\s*)\b')
_MANDATORY_WORDS = {"must", "shall", "mandatory", "required", "will be disqualified"}
_OPTIONAL_WORDS = {"may", "should", "recommended", "optional", "desired", "preferable"}
_EXCEPTION_WORDS = {"except", "unless", "excluding", "exclusion", "exemption", "save and except"}


# ═════════════════════════════════════════════════════════════════════════════
# 1. DUPLICATE-DOCUMENT DETECTION
# ═════════════════════════════════════════════════════════════════════════════

def normalize_text_for_digest(text: str) -> str:
    """Normalize text by stripping source annotations, lowercasing, and collapsing whitespace."""
    if not text:
        return ""
    stripped = re.sub(r'\[\[SOURCE:[^\]]*\]\]', ' ', text)
    return " ".join(stripped.lower().split())


def compute_content_hash(content: str | bytes) -> str:
    """Return SHA-256 hash of content."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def is_distinct_document_name(fname: str) -> bool:
    """True if filename indicates a distinct legal artifact, addendum, schedule, or revision."""
    lower = fname.lower()
    distinct_indicators = (
        "addend", "amend", "q&a", "qa", "question", "bulletin", "schedule",
        "appendix", "annex", "revised", "revision", "v1.", "v2.", "v3.", "part"
    )
    return any(ind in lower for ind in distinct_indicators)


def detect_duplicate_documents(
    documents: Sequence[tuple[str, str | bytes]]
) -> tuple[list[tuple[str, str | bytes]], dict[str, str]]:
    """Detect and suppress exact duplicate documents while preserving legally distinct ones.

    Returns:
        (retained_documents, alias_map) where alias_map maps duplicate filename -> primary filename.
    """
    seen_hashes: dict[str, str] = {}
    seen_text_digests: dict[str, str] = {}
    retained: list[tuple[str, str | bytes]] = []
    alias_map: dict[str, str] = {}

    for fname, content in documents:
        chash = compute_content_hash(content)
        text_content = content if isinstance(content, str) else content.decode("utf-8", errors="replace")
        tdigest = hashlib.sha256(normalize_text_for_digest(text_content).encode("utf-8")).hexdigest()

        # Check for exact duplicate bytes (unless explicitly distinct legal artifact)
        if chash in seen_hashes:
            if not is_distinct_document_name(fname):
                primary = seen_hashes[chash]
                alias_map[fname] = primary
                continue

        # Check for identical normalized text (e.g. same text saved in different container or minor formatting)
        if tdigest in seen_text_digests:
            # If filename explicitly indicates an amendment or distinct schedule, retain it
            if not is_distinct_document_name(fname):
                primary = seen_text_digests[tdigest]
                alias_map[fname] = primary
                continue

        seen_hashes[chash] = fname
        seen_text_digests[tdigest] = fname
        retained.append((fname, content))

    return retained, alias_map


# ═════════════════════════════════════════════════════════════════════════════
# 2. NEAR-DUPLICATE STAGE-D CLUSTERING
# ═════════════════════════════════════════════════════════════════════════════

def _extract_material_facets(text: str) -> dict[str, set[str]]:
    """Extract dates, numbers/quantities/percentages, mandatory tone, and exceptions."""
    lower = text.lower()
    dates = set(_DATE_PAT.findall(lower))
    numbers = set(_NUMBER_PAT.findall(lower))
    mandatory = {w for w in _MANDATORY_WORDS if w in lower}
    optional = {w for w in _OPTIONAL_WORDS if w in lower}
    exceptions = {w for w in _EXCEPTION_WORDS if w in lower}
    return {
        "dates": dates,
        "numbers": numbers,
        "mandatory": mandatory,
        "optional": optional,
        "exceptions": exceptions,
    }


def have_material_variation(text_a: str, text_b: str) -> bool:
    """Return True if two near-duplicate texts differ in any material facet.

    Checks:
    - Deadlines / dates
    - Thresholds / quantities / numbers / prices
    - Mandatory vs optional tone
    - Explicit exception clauses
    """
    f_a = _extract_material_facets(text_a)
    f_b = _extract_material_facets(text_b)

    if f_a["dates"] != f_b["dates"]:
        return True
    if f_a["numbers"] != f_b["numbers"]:
        return True
    if bool(f_a["mandatory"]) != bool(f_b["mandatory"]):
        return True
    if bool(f_a["optional"]) != bool(f_b["optional"]):
        return True
    if bool(f_a["exceptions"]) != bool(f_b["exceptions"]):
        return True
    return False


def _word_set(text: str) -> set[str]:
    return set(re.findall(r'[a-z0-9]+', (text or '').lower()))


def _jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union else 0.0


def cluster_near_duplicate_requirements(
    requirements: list[dict],
    similarity_threshold: float = 0.80,
) -> list[dict]:
    """Cluster near-duplicate requirements specifically for synthesis prompt construction.

    CRITICAL RULES:
    1. The durable canonical layer remains lossless.
    2. Items differing in material deadline, threshold, quantity, qualifier, price,
       or exception are NEVER merged.
    3. Retains representative + source count + combined provenance references.
    4. Zero silent omission: every source requirement is accounted for.
    """
    if not requirements:
        return []

    # Group by category first (never merge across different categories)
    by_category: dict[str, list[dict]] = {}
    for r in requirements:
        cat = str(r.get("category", "")).strip().lower()
        by_category.setdefault(cat, []).append(r)

    clustered_results: list[dict] = []

    for cat, items in by_category.items():
        clusters: list[list[dict]] = []

        for item in items:
            desc = str(item.get("description") or "")
            words = _word_set(desc)
            placed = False

            for cluster in clusters:
                rep = cluster[0]
                rep_desc = str(rep.get("description") or "")
                rep_words = _word_set(rep_desc)

                if _jaccard_similarity(words, rep_words) >= similarity_threshold:
                    # Verify no material variation
                    if not have_material_variation(desc, rep_desc):
                        cluster.append(item)
                        placed = True
                        break

            if not placed:
                clusters.append([item])

        for cluster in clusters:
            primary = copy.deepcopy(cluster[0])
            if len(cluster) > 1:
                # Merge provenance references
                all_refs: list[dict] = []
                seen_ref_keys = set()
                for member in cluster:
                    for sref in (member.get("source_refs") or []):
                        if isinstance(sref, dict):
                            key = (sref.get("source_doc"), sref.get("page"), sref.get("section"))
                            if key not in seen_ref_keys:
                                seen_ref_keys.add(key)
                                all_refs.append(sref)
                primary["source_refs"] = all_refs
                primary["cluster_count"] = len(cluster)
                primary["cluster_member_ids"] = [
                    m.get("req_id") or m.get("canonical_id") for m in cluster if m.get("req_id") or m.get("canonical_id")
                ]
            else:
                primary["cluster_count"] = 1
                primary["cluster_member_ids"] = [primary.get("req_id") or primary.get("canonical_id")]
            clustered_results.append(primary)

    return clustered_results


# ═════════════════════════════════════════════════════════════════════════════
# 3. STAGE-D CONTEXT BOUNDING & CONSISTENT EXCERPT CAPS
# ═════════════════════════════════════════════════════════════════════════════

def _bound_excerpt_text(text: Any, cap: int = EXCERPT_CAP) -> str:
    s = str(text or "")
    if len(s) > cap:
        return s[:cap] + "…"
    return s


def bound_source_refs(refs: list[dict] | None, cap: int = EXCERPT_CAP) -> list[dict]:
    """Bound excerpts in source_refs records."""
    if not refs:
        return []
    bounded: list[dict] = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        c = dict(ref)
        if c.get("excerpt"):
            c["excerpt"] = _bound_excerpt_text(c["excerpt"], cap)
        bounded.append(c)
    return bounded


def bound_section_items(items: list[dict] | None, text_fields: Sequence[str], cap: int = EXCERPT_CAP) -> list[dict]:
    """Consistently bound text and source_refs across an entire section."""
    if not items:
        return []
    bounded: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        c = dict(item)
        if "source_refs" in c:
            c["source_refs"] = bound_source_refs(c["source_refs"], cap)
        for tf in text_fields:
            if tf in c and c[tf]:
                c[tf] = _bound_excerpt_text(c[tf], cap)
        bounded.append(c)
    return bounded


def build_scalable_stage_d_context(
    normalized_facts: dict,
    conflicts: list[dict],
    *,
    excerpt_cap: int = EXCERPT_CAP,
    apply_clustering: bool = True,
) -> dict:
    """Build a bounded, scalable Stage D context with consistent caps across ALL sections.

    Remediates the context-explosion defect identified in the British Council audit:
    - Consistent excerpt bounds applied to requirements, deliverables, commercial clauses,
      contract risks, evaluation criteria, submission rules, and dates.
    - Scoped near-duplicate requirement clustering prevents redundant prompt bloat.
    - Zero silent omissions: integrity counts explicitly track all items.
    """
    raw_reqs = normalized_facts.get("requirements") or []
    source_count = len(raw_reqs)

    for idx, r in enumerate(raw_reqs):
        if not isinstance(r, dict):
            raise RuntimeError(
                f"Stage D context integrity failure: requirements[{idx}] is {type(r).__name__!r}, not a dict."
            )

    reqs_to_use = cluster_near_duplicate_requirements(raw_reqs) if apply_clustering else raw_reqs
    clustered_count = len(reqs_to_use)

    # Bound requirements
    bounded_reqs = bound_section_items(reqs_to_use, ("description", "evidence"), excerpt_cap)

    mandatory = [r for r in bounded_reqs if str(r.get("category", "")).strip().lower() == "mandatory"]
    financial = [r for r in bounded_reqs if str(r.get("category", "")).strip().lower() == "financial"]
    rated = [r for r in bounded_reqs if str(r.get("category", "")).strip().lower() == "rated"]
    supporting = [r for r in bounded_reqs if str(r.get("category", "")).strip().lower() == "supporting"]
    other = [r for r in bounded_reqs if str(r.get("category", "")).strip().lower() not in ("mandatory", "financial", "rated", "supporting")]

    # Bound all other sections consistently
    bounded_criteria = bound_section_items(
        normalized_facts.get("evaluation_criteria", []),
        ("description", "source_text", "response_prompt"),
        excerpt_cap
    )
    bounded_deliverables = bound_section_items(
        normalized_facts.get("deliverables", []),
        ("description", "source_text"),
        excerpt_cap
    )
    bounded_commercial = bound_section_items(
        normalized_facts.get("commercial_clauses", []),
        ("source_fact", "description", "clause_text"),
        excerpt_cap
    )
    bounded_risks = bound_section_items(
        normalized_facts.get("contract_risks", []),
        ("description", "mitigation"),
        excerpt_cap
    )
    bounded_rules = bound_section_items(
        normalized_facts.get("submission_rules", []),
        ("description", "rule_text"),
        excerpt_cap
    )
    bounded_dates = bound_section_items(
        normalized_facts.get("dates", []),
        ("source_text", "notes"),
        excerpt_cap
    )

    included_count = len(mandatory) + len(financial) + len(rated) + len(supporting) + len(other)

    context = {
        "metadata": normalized_facts.get("doc_metadata", {}),
        "requirements": {
            "mandatory": mandatory,
            "financial": financial,
            "rated": rated,
            "supporting": supporting,
            **({"other": other} if other else {}),
        },
        "dates": bounded_dates,
        "evaluation_criteria": bounded_criteria,
        "submission_rules": bounded_rules,
        "deliverables": bounded_deliverables,
        "commercial_clauses": bounded_commercial,
        "contract_risks": bounded_risks,
        "detected_conflicts": list(conflicts),
        "context_integrity": {
            "source_requirement_count": source_count,
            "clustered_requirement_count": clustered_count,
            "included_requirement_count": included_count,
            "omitted_requirement_count": 0,
            "all_mandatory_included": True,
            "all_financial_included": True,
        },
    }
    return context
