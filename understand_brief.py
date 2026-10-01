"""Deterministic, customer-safe UNDERSTAND Brief selection model.

This module deliberately sits after Fast Analysis.  It consumes a completed
``FastAnalysisResult`` only; it neither reads a database nor invokes a model.
The PDF renderer is consequently an interchangeable presentation concern, and
re-exporting a durable run is zero-call.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
from collections import Counter
from typing import Iterable

from fast_analysis import FastAnalysisResult, carry_forward_category_scope
from scripts.fast_analysis_report_adapter import (
    _clarification_deadline_text, _contract_term, _merged_doc_metadata,
    _presentation_dates, _submission_channel, _submission_deadline_text,
    _shorten_to_sentence, build_fast_report_content,
)

BRIEF_CONTRACT_VERSION = "1.0"
MAX_ATTENTION_ITEMS = 7
_NOISE = ("not stated in extracted data", "crit-", "obl-", "ident-", "doc-",
          "max_tokens", "migration", "product-feedback", "provider", "benchmark")
_FORM_TITLES = ("appendix", "acknowledgement", "acknowledgment", "submission form",
                "price form", "proponent", "general conditions", "terms and conditions",
                "form of agreement", "addendum", "question and answer", "qa log")
_SUBMISSION_WORDS = ("submit", "submission", "proposal", "appendix", "form", "portal",
                     "ariba", "page limit", "font", "language", "rectif", "deadline")
_POST_AWARD_WORDS = ("invoice", "payment", "payable", "billing")
_COMMERCIAL_WORDS = ("insurance", "liability", "indemn", "intellectual property", "ip ",
                     "subcontract", "assignment", "term", "renew", "price", "rate", "volume",
                     "exclusiv", "privacy", "security", "termination", "registration")


@dataclass(frozen=True)
class BriefCriterion:
    name: str
    weight: str
    minimum: str | None
    response_expectation: str | None


@dataclass(frozen=True)
class BriefPriority:
    title: str
    action: str


@dataclass(frozen=True)
class BidIntelligenceBrief:
    contract_version: str
    buyer: str
    solicitation: str
    opportunity: str
    source_documents: tuple[str, ...]
    partial_sections: tuple[str, ...]
    snapshot: tuple[tuple[str, str], ...]
    immediate_matter: str | None
    buyer_intent: tuple[str, ...]
    scope_intro: str | None
    service_scope: tuple[str, ...]
    success_profile: str | None
    criteria: tuple[BriefCriterion, ...]
    evaluation_implication: str | None
    submission: tuple[tuple[str, str, str | None], ...]
    key_dates: tuple[str, ...]
    submission_distinction: str | None
    commercial: tuple[tuple[str, str], ...]
    commercial_implication: str | None
    priorities: tuple[BriefPriority, ...]
    clarifications: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


class BriefModelError(ValueError):
    """Raised before rendering when customer-facing identity is unsafe."""


def _clean(value: object, limit: int = 420) -> str | None:
    if not isinstance(value, str):
        return None
    value = re.sub(r"\s+", " ", value).strip()
    if not value or any(n in value.lower() for n in _NOISE):
        return None
    return _shorten_to_sentence(value, limit=limit)


def _title(result: FastAnalysisResult, meta: dict) -> str:
    # A merged metadata record is useful for dates but can be last-document
    # wins.  Identity must be selected from all source-document candidates so
    # a general-conditions file can never displace the actual opportunity.
    candidates = []
    for filename, metadata in result.doc_metadata_by_doc.items():
        if not isinstance(metadata, dict):
            continue
        cleaned = _clean(metadata.get("title"), 260)
        context = f"{filename or ''} {cleaned or ''}".lower()
        if cleaned and not any(x in context for x in _FORM_TITLES):
            candidates.append(cleaned)
    if not candidates:
        cleaned = _clean(meta.get("title"), 260)
        if cleaned and not any(x in cleaned.lower() for x in _FORM_TITLES):
            candidates.append(cleaned)
    if candidates:
        # Repetition across main RFP, amendments and Q&A is stronger evidence
        # than a title appearing in one supporting document; ties preserve the
        # source package's deterministic metadata order.
        counts = Counter(x.lower() for x in candidates)
        return max(candidates, key=lambda x: counts[x.lower()])
    raise BriefModelError("A customer-safe procurement opportunity title is unavailable.")


def _source_documents(result: FastAnalysisResult) -> tuple[str, ...]:
    names = []
    for group in (result.documents_by_route or {}).values():
        names.extend(n for n in group if isinstance(n, str))
    names.extend(n for n in result.doc_metadata_by_doc if isinstance(n, str))
    return tuple(dict.fromkeys(names))


def _expectation(result: FastAnalysisResult, occ: dict) -> str | None:
    label = occ.get("criterion_label") or ""
    scoped = getattr(result, "scoped_criterion_response_prompts", {}) or {}
    # Scoped lookup is preferred, but raw snapshots predating it remain usable.
    for key, entry in scoped.items():
        if key.endswith("|" + label.lower()) and isinstance(entry, dict):
            text = _clean(entry.get("response_prompt"), 320)
            if text and not _looks_like_table_residue(text):
                return text
    entry = (getattr(result, "deterministic_criterion_response_prompts", {}) or {}).get(label) or {}
    text = _clean(entry.get("response_prompt"), 320)
    if text and not _looks_like_table_residue(text):
        return text
    matches = [r.get("description") for r in result.requirements
               if isinstance(r, dict) and label.lower() in (r.get("description") or "").lower()]
    return _clean(" ".join(matches[:2]), 320)


def _looks_like_table_residue(text: str) -> bool:
    """Reject a response prompt that starts with flattened scoring-table cells."""
    return bool(re.match(r"^(?:\d+%\s|\d+\s+(?:N/A|\d+%|Grand Total)\b)", text, re.I))


def _minimums(result: FastAnalysisResult) -> dict[str, str]:
    values: dict[str, str] = {}
    for guide in getattr(result, "deterministic_response_guidelines", []) or []:
        if not isinstance(guide, dict):
            continue
        label, minimum = guide.get("criterion_label") or guide.get("label"), guide.get("minimum_score")
        if label and minimum not in (None, ""):
            values[str(label).lower()] = str(minimum)
    for occ in result.evaluation_occurrences:
        if isinstance(occ, dict) and occ.get("criterion_label") and occ.get("minimum_score") not in (None, ""):
            values[str(occ["criterion_label"]).lower()] = str(occ["minimum_score"])
    return values


def _criteria(result: FastAnalysisResult) -> tuple[BriefCriterion, ...]:
    seen, rows, minimums = set(), [], _minimums(result)
    for occ in carry_forward_category_scope(result.evaluation_occurrences):
        if not isinstance(occ, dict):
            continue
        name, weight = _clean(occ.get("criterion_label"), 120), _clean(occ.get("weight"), 40)
        if not name or not weight or name.lower() in seen or name.lower() in ("total", "total points"):
            continue
        seen.add(name.lower())
        rows.append(BriefCriterion(name, weight, minimums.get(name.lower()), _expectation(result, occ)))
    return tuple(rows)


def _scope(result: FastAnalysisResult) -> tuple[str, ...]:
    # Only positive, source-extracted scope is eligible.  A response instruction
    # and an ordinary verb can never become a made-up service category.
    items: list[str] = []
    for values in (getattr(result, "category_scope_items", {}) or {}).values():
        for value in values or []:
            if isinstance(value, dict):
                value = value.get("text") or value.get("description")
            cleaned = _clean(value, 250)
            if cleaned and not re.match(r"^(provide|proponents? (must|are|shall)|describe|submit|complete|respond|[0-9]+\.)\b", cleaned, re.I) and cleaned not in items:
                items.append(cleaned)
    det = getattr(result, "deterministic_service_scope", None) or {}
    for value in det.get("items", []) if isinstance(det, dict) else []:
        cleaned = _clean(value if isinstance(value, str) else value.get("text"), 250)
        if cleaned and not re.match(r"^(provide|proponents? (must|are|shall)|describe|submit|complete|respond|[0-9]+\.)\b", cleaned, re.I) and cleaned not in items:
            items.append(cleaned)
    # Some durable snapshots predate the dedicated scope projection but retain
    # an explicit, source-derived service-scope requirement.  It is safe to
    # surface only that labelled fact; generic requirements and response
    # prompts remain ineligible, so an instruction can never be relabelled as
    # buyer scope.
    for requirement in result.requirements:
        if not isinstance(requirement, dict):
            continue
        raw_description = re.sub(r"\s+", " ", str(requirement.get("description") or "")).strip()
        description = _clean(raw_description, 250)
        if (description and re.match(r"^service scope includes\b", description, re.I)
                and description not in items):
            items.append(description)
        refs = requirement.get("source_refs") or []
        section_text = " ".join(str(ref.get("section") or "") for ref in refs if isinstance(ref, dict)).lower()
        if (raw_description and ("deliverables" in section_text or "scope" in section_text)
                and not re.search(r"\b(?:credential|certif|ethical|confidentiality practices|professional boundaries)\b", raw_description, re.I)):
            # Preserve the source's own sentence/list boundaries; do not
            # manufacture categories from arbitrary response verbs.
            for part in re.split(r"(?<=[.!?])\s+", raw_description):
                clean = _clean(part, 250)
                if (clean and len(clean.split()) >= 5
                        and not re.match(r"^(proponents?|submit|complete|provide the form)\b", clean, re.I)
                        and clean not in items):
                    items.append(clean)
    # Do not fall back to generic requirements.  Historical snapshots can
    # label a response prompt ``SCOPE_ITEM``; without the dedicated positive
    # scope field, omitting this section is more truthful than converting a
    # bidder instruction into a buyer service category.
    items = [item for item in items if not re.search(
        r"\b(?:credential\w*|certif\w*|ethical|confidentiality practices|professional boundaries|anticipates a total volume|session duration)\b",
        item, re.I)]
    return tuple(items[:8])


def _buyer_intent(deterministic: Iterable[object]) -> tuple[str, ...]:
    """Restore sentence-level objectives from line-wrapped fact fragments."""
    complete, pending = [], []
    for fact in deterministic:
        if not isinstance(fact, dict) or fact.get("family") != "OBJECTIVE":
            continue
        fragment = _clean(fact.get("value"), 220)
        if not fragment:
            continue
        pending.append(fragment)
        if re.search(r"[.!?]$", fragment):
            complete.append(" ".join(pending))
            pending = []
    if pending:
        complete.append(" ".join(pending))
    return tuple(dict.fromkeys(complete))[:6]


def _fact_dates(deterministic: Iterable[object]) -> tuple[str, ...]:
    labels = {
        "RFP_ISSUE_DATE": "RFP issue date",
        "QUESTION_DEADLINE": "Questions deadline",
        "ADDENDA_DEADLINE": "Addenda deadline",
        "SUBMISSION_DEADLINE": "Submission deadline",
        "RECTIFICATION_PERIOD": "Rectification period",
    }
    found = {}
    for fact in deterministic:
        if isinstance(fact, dict) and fact.get("semantic_kind") in labels:
            value = _clean(fact.get("value"), 180)
            if value:
                found[fact["semantic_kind"]] = value
    return tuple(f"{label}: {found[kind]}" for kind, label in labels.items() if kind in found)


def _submission_distinction(result: FastAnalysisResult, deterministic: Iterable[object]) -> str | None:
    rectification = next((
        _clean(fact.get("value"), 160)
        for fact in deterministic
        if isinstance(fact, dict) and fact.get("semantic_kind") == "RECTIFICATION_PERIOD"
    ), None)
    if rectification:
        return (f"The stated rectification period is {rectification}. It is a limited procurement mechanic; "
                "the proposal must still address the rated response requirements at submission.")
    return None


def _submission(result: FastAnalysisResult) -> tuple[tuple[str, str, str | None], ...]:
    content = build_fast_report_content(result)
    rows = []
    seen_labels = set()
    categories = (
        ("Submission Form", ("submission form", "appendix e")),
        ("Technical Response", ("rated criteria", "appendix c", "technical")),
        ("Pricing Form", ("price form", "pricing form", "appendix d", "pricing")),
        ("ICF Evidence", ("international coaching federation", "icf")),
        ("Portal", ("sap ariba", "portal", "registered supplier")),
        ("Language", ("in english", "english")),
        ("Formatting", ("single-spaced", "point font", "sequentially numbered")),
        ("Page Limit", ("maximum of twenty", "page limit", "20 pages")),
        ("Rectification", ("rectification",)),
    )
    source_rows = list(content.RESPONSE_CHECKLIST)
    source_rows.extend(
        ("Source requirement", r.get("description") or "", r.get("source_doc"))
        for r in result.requirements if isinstance(r, dict)
    )
    for item, requirement, note in source_rows:
        text = " ".join(str(x or "") for x in (item, requirement, note)).lower()
        if any(x in text for x in _POST_AWARD_WORDS) or not any(x in text for x in _SUBMISSION_WORDS):
            continue
        labels = [name for name, words in categories if any(word in text for word in words)]
        if not labels:
            # Do not expose opaque adapter numbering in the customer Brief.
            continue
        for label in labels:
            if label in seen_labels:
                continue
            seen_labels.add(label)
            rows.append((label, _clean(requirement, 280) or "", _clean(note, 180) or ""))
    return tuple(rows[:10])


def _commercial(result: FastAnalysisResult) -> tuple[tuple[str, str], ...]:
    raw = []
    for clause in result.commercial_clauses:
        if not isinstance(clause, dict):
            continue
        topic = _clean(clause.get("topic") or clause.get("clause_kind"), 70)
        detail = _clean(clause.get("source_fact"), 300)
        combined = f"{topic or ''} {detail or ''}".lower()
        if topic and detail and any(word in combined for word in _COMMERCIAL_WORDS):
            raw.append((topic, detail, combined))
    # Concise, generic commercial curation.  Category selection makes the
    # brief usable while retaining every raw clause in the immutable snapshot.
    categories = (
        ("Business registration", ("business registration", "registration")),
        ("Performance management", ("performance evaluation", "performance improvement", "kpi")),
        ("Assignment and subcontracting", ("assign", "subcontract", "geographic restriction")),
        ("Pricing and rate commitments", ("price", "rate", "escalat")),
        ("Insurance", ("insurance", "liability", "indemn")),
        ("Intellectual property", ("intellectual property",)),
        ("Privacy and security", ("privacy", "security")),
        ("Governing law", ("governing law", "jurisdiction")),
    )
    rows = []
    used = set()
    for label, terms in categories:
        # Headings (rather than incidental clause prose) determine the brief
        # category: e.g. a governing-law clause's "exclusive jurisdiction"
        # is not a volume/exclusivity commitment.
        match = next((detail for topic, detail, _ in raw
                      if any(term in topic.lower() for term in terms) and detail not in used), None)
        if match:
            rows.append((label, match)); used.add(match)
    return tuple(rows[:9])


def _priorities(criteria: tuple[BriefCriterion, ...], submission, commercial) -> tuple[BriefPriority, ...]:
    priorities: list[BriefPriority] = []
    gates = [c for c in criteria if c.minimum]
    if gates:
        c = gates[0]
        priorities.append(BriefPriority(f"Protect the {c.minimum} gate", f"Make the evidence for {c.name} explicit before submission."))
    for c in criteria[:3]:
        if len(priorities) >= 5:
            break
        priorities.append(BriefPriority(f"Answer {c.name}", c.response_expectation or "Use the buyer's stated criterion as the response structure."))
    if submission and len(priorities) < MAX_ATTENTION_ITEMS:
        priorities.append(BriefPriority("Control submission mechanics", "Assign ownership for mandatory forms, format checks and portal submission before the deadline."))
    if commercial and len(priorities) < MAX_ATTENTION_ITEMS:
        priorities.append(BriefPriority("Model material commercial exposure", "Confirm pricing, delivery and contractual commitments before making them in the proposal."))
    return tuple(priorities[:MAX_ATTENTION_ITEMS])


def _safe_submission_channel(result: FastAnalysisResult) -> str | None:
    value = _clean(_submission_channel(result), 160)
    if value and any(token in value.lower() for token in ("ariba", "portal", "electronic", "online", "website")):
        return value
    return None


def build_bid_intelligence_brief(result: FastAnalysisResult, *, analysis_partial: bool = False) -> BidIntelligenceBrief:
    """Build a deterministic concise Brief or fail before any misleading PDF.

    The same raw snapshot always produces the same model.  The function does
    not mutate ``result`` and has no provider, database, filesystem or UI I/O.
    """
    meta = _merged_doc_metadata(result)
    buyer = _clean(meta.get("client"), 120) or "Buyer not identified"
    solicitation = _clean(meta.get("file_number"), 80) or "Solicitation reference not identified"
    opportunity = _title(result, meta)
    content = build_fast_report_content(result)
    criteria = _criteria(result)
    snapshot = [("Buyer", buyer), ("Opportunity", opportunity), ("Solicitation", solicitation)]
    deterministic = getattr(result, "deterministic_procurement_facts", []) or []
    fact_by_kind = {f.get("semantic_kind"): f.get("value") for f in deterministic if isinstance(f, dict)}
    budget = fact_by_kind.get("ESTIMATED_BUDGET")
    budget_text = None
    if isinstance(budget, dict) and budget.get("minimum") is not None and budget.get("maximum") is not None:
        budget_text = f"CAD {budget['minimum']:,}–{budget['maximum']:,} per {budget.get('period', 'year')}"
    annual_volume = fact_by_kind.get("ANNUAL_SESSION_VOLUME")
    volume_text = None
    if isinstance(annual_volume, dict):
        volume_text = f"Approximately {annual_volume.get('minimum')}–{annual_volume.get('maximum')} {annual_volume.get('unit', 'sessions')} per year"
    session_range = fact_by_kind.get("SESSION_VOLUME_RANGE")
    if isinstance(session_range, dict):
        volume_text = (volume_text + "; separate engagement wording: " if volume_text else "") + f"{session_range.get('minimum')}–{session_range.get('maximum')} {session_range.get('unit', 'sessions')}"
    for label, value in (("Budget", budget_text or meta.get("budget") or meta.get("value_cad")),
                         ("Volume", volume_text),
                         ("Term", _contract_term(result.typed_observations)),
                         ("Submission deadline", _submission_deadline_text(meta)),
                         ("Questions deadline", _clarification_deadline_text(meta, result.typed_observations)),
                         ("Submission channel", _safe_submission_channel(result))):
        value = _clean(value, 240)
        if value and "not confidently extracted" not in value.lower():
            snapshot.append((label, value))
    immediate = None
    for c in criteria:
        if c.minimum:
            immediate = f"{c.name} has a stated minimum threshold of {c.minimum}."
            break
    scope = _scope(result)
    buyer_intent = _buyer_intent(deterministic)
    dates = _fact_dates(deterministic) or tuple(
        f"{label}: {value}" for value, label in _presentation_dates(result.typed_observations)[:6]
    )
    clarification_list = []
    for ambiguity in content.AMBIGUITIES or []:
        question = _clean(ambiguity.get("question"), 380) if isinstance(ambiguity, dict) else None
        if question and question not in clarification_list:
            clarification_list.append(question)
    if fact_by_kind.get("ANNUAL_SESSION_VOLUME") and fact_by_kind.get("SESSION_VOLUME_RANGE"):
        clarification_list.append("Confirm how the stated annual session volume relates to the separate per-engagement session range.")
    service_prompt = next((c.response_expectation or "" for c in criteria
                           if c.name.lower() == "service delivery"), "")
    if service_prompt and not re.search(r"response time|sla|service level", service_prompt, re.I):
        clarification_list.append("Confirm whether any explicit response-time or service-level targets apply beyond the stated delivery requirements.")
    clarifications = tuple(clarification_list[:4])
    partial = ("Interpretive priority sections",) if analysis_partial else ()
    return BidIntelligenceBrief(
        BRIEF_CONTRACT_VERSION, buyer, solicitation, opportunity, _source_documents(result), partial,
        tuple(snapshot), immediate, buyer_intent, None, scope, None, criteria,
        ("Prioritize the highest-weighted criteria and any stated threshold." if criteria else None),
        _submission(result), dates, _submission_distinction(result, deterministic), _commercial(result), None,
        _priorities(criteria, _submission(result), _commercial(result)), clarifications,
    )


def model_digest(model: BidIntelligenceBrief) -> str:
    return hashlib.sha256(json.dumps(model.to_dict(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
