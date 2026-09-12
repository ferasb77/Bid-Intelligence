"""Deterministic contract fact hygiene (contract-hygiene/1).

Fresh Stage A records are source occurrences.  This module validates their
shape, assigns content-derived identifiers, and groups only exact structured
matches into logical records while retaining every physical occurrence.
Legacy extraction records remain visible but can never be promoted to verified
source facts.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation


VERSION = "contract-hygiene/1"

CLAUSE_KINDS = frozenset({
    "LIABILITY_INDEMNITY", "INSURANCE", "INTELLECTUAL_PROPERTY",
    "AI_AUTOMATED_TOOLS", "DATA_PROTECTION_PRIVACY",
    "CYBERSECURITY_SECURITY", "CONFIDENTIALITY", "SUBCONTRACTING",
    "PERSONNEL_KEY_STAFF", "BACKGROUND_CHECK_CLEARANCE", "TERMINATION",
    "SUSPENSION", "PAYMENT_WITHHOLDING_SETOFF", "PRICING_ESCALATION",
    "GUARANTEE_BOND", "SERVICE_CREDIT_PENALTY_LD", "WARRANTY",
    "ACCEPTANCE", "AUDIT_RECORDS", "CHANGE_CONTROL", "ASSIGNMENT",
    "GOVERNING_LAW_DISPUTE", "EXCLUSIVITY_NONCOMPETE",
    "BUSINESS_CONTINUITY_DR", "REGULATORY_COMPLIANCE", "OTHER",
})
OBLIGATION_STATES = frozenset({"MANDATORY", "OPTIONAL", "CONDITIONAL", "NOT_STATED"})
RESPONSIBLE_ACTORS = frozenset({"SUPPLIER", "BUYER", "SHARED", "THIRD_PARTY", "NOT_STATED"})
FREQUENCIES = frozenset({
    "ONE_TIME", "DAILY", "WEEKLY", "MONTHLY", "QUARTERLY", "ANNUAL",
    "PER_EVENT", "PER_CALL_OFF", "AS_REQUESTED", "OTHER", "NOT_STATED",
})
ASSESSMENT_STATES = frozenset({"REVIEW", "UNKNOWN"})
INTERPRETATION_CODES = frozenset({"REVIEW_CLAUSE_TERMS", "INSUFFICIENT_CONTEXT"})
INTERPRETATION_TEXT = {
    "REVIEW_CLAUSE_TERMS": "Review this clause against the bidder's approved contracting policy.",
    "INSUFFICIENT_CONTEXT": "The verified clause is retained, but the available context is insufficient for further interpretation.",
}
SCOPE_KEYS = ("lot", "phase", "component", "location")


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _id(prefix: str, value) -> str:
    return prefix + hashlib.sha256(_json(value).encode("utf-8")).hexdigest()[:24]


def _text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _identity(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _text(value).lower()).strip()


def _scope(value) -> dict:
    value = value if isinstance(value, dict) else {}
    return {key: _text(value.get(key)) or None for key in SCOPE_KEYS}


def _strings(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value if _text(item)]


def _quantity(value):
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    return format(number.normalize(), "f")


def _physical_ref_key(ref: dict) -> tuple:
    rows = ref.get("rows")
    if isinstance(rows, list):
        rows = tuple(rows)
    return (ref.get("source_doc"), ref.get("page"), ref.get("sheet"),
            ref.get("section"), rows, _text(ref.get("excerpt")))


def _verified_refs(refs, validate_refs, package_metadata) -> list[dict]:
    if not isinstance(refs, list) or not refs:
        return []
    explicitly_unverified = {_physical_ref_key(ref) for ref in refs
                             if isinstance(ref, dict) and ref.get("verified") is False}
    checked = validate_refs(copy.deepcopy(refs), package_metadata)
    unique = {}
    for ref in checked:
        # A ref counts as a valid physical reference on the same terms
        # validate_refs() itself uses (document + locator resolve) -- no
        # additional excerpt requirement is imposed here. Requiring a
        # non-empty excerpt on top of an already-verified ref discarded
        # genuine document+section/sheet/page citations that validate_refs()
        # itself considered valid (e.g. a DOCX Header-section citation with
        # no quotable excerpt), which silently dropped real provenance.
        if (isinstance(ref, dict) and ref.get("verified") is True
                and _physical_ref_key(ref) not in explicitly_unverified):
            unique[_physical_ref_key(ref)] = ref
    return [unique[key] for key in sorted(unique, key=lambda k: _json(k))]


def _occurrence_id(prefix, factual, refs):
    physical = [_physical_ref_key(ref) for ref in refs]
    return _id(prefix, {"fact": factual, "physical": physical})


def normalize_deliverable_occurrence(raw, validate_refs, package_metadata):
    if not isinstance(raw, dict) or "obligation_state" not in raw:
        return None
    title, description = _text(raw.get("title")), _text(raw.get("description"))
    state = _text(raw.get("obligation_state")).upper()
    actor = _text(raw.get("responsible_actor")).upper()
    frequency = _text(raw.get("frequency")).upper()
    if not title or not description or state not in OBLIGATION_STATES:
        return None
    if actor not in RESPONSIBLE_ACTORS:
        actor = "NOT_STATED"
    if frequency not in FREQUENCIES:
        frequency = "NOT_STATED"
    refs = _verified_refs(raw.get("source_refs"), validate_refs, package_metadata)
    factual = {
        "title": title, "description": description, "obligation_state": state,
        "quantity": _quantity(raw.get("quantity")), "unit": _text(raw.get("unit")) or None,
        "frequency": frequency, "frequency_raw": _text(raw.get("frequency_raw")) or None,
        "scope": _scope(raw.get("scope")),
        "due_milestone": _text(raw.get("due_milestone")) or None,
        "acceptance_criteria": _text(raw.get("acceptance_criteria")) or None,
        "responsible_actor": actor, "conditions": _strings(raw.get("conditions")),
    }
    return {"occurrence_id": _occurrence_id("dlo_", factual, refs), **factual,
            "source_refs": refs, "evidence_state": "VERIFIED" if refs else "UNVERIFIED",
            "contract_hygiene_version": VERSION}


def normalize_clause_occurrence(raw, validate_refs, package_metadata):
    if not isinstance(raw, dict) or "clause_kind" not in raw or "source_fact" not in raw:
        return None
    kind = _text(raw.get("clause_kind")).upper()
    if kind not in CLAUSE_KINDS:
        kind = "OTHER"
    topic, fact = _text(raw.get("topic")), _text(raw.get("source_fact"))
    if not topic or not fact:
        return None
    refs = _verified_refs(raw.get("source_refs"), validate_refs, package_metadata)
    factual = {"clause_kind": kind, "topic": topic, "source_fact": fact,
               "conditions": _strings(raw.get("conditions")), "scope": _scope(raw.get("scope")),
               "linked_observation_ids": sorted(set(_strings(raw.get("linked_observation_ids"))))}
    return {"occurrence_id": _occurrence_id("clo_", factual, refs), **factual,
            "source_refs": refs, "evidence_state": "VERIFIED" if refs else "UNVERIFIED",
            "contract_hygiene_version": VERSION}


def _deliverable_key(item):
    return (_identity(item["title"]), item["obligation_state"], item["quantity"],
            _identity(item["unit"]), item["frequency"], tuple(item["conditions"]),
            tuple(item["scope"].items()), _identity(item["due_milestone"]),
            _identity(item["acceptance_criteria"]), item["responsible_actor"])


def _clause_key(item):
    return (item["clause_kind"], _identity(item["source_fact"]), tuple(item["conditions"]),
            tuple(item["scope"].items()), tuple(item["linked_observation_ids"]))


def _logical_records(occurrences, key_fn, prefix):
    groups = {}
    for occurrence in occurrences:
        # Overlapping chunks that describe the same physical occurrence collapse here.
        group = groups.setdefault(key_fn(occurrence), {})
        group[occurrence["occurrence_id"]] = occurrence
    output = []
    for key in sorted(groups, key=_json):
        members = [groups[key][oid] for oid in sorted(groups[key])]
        first = copy.deepcopy(members[0])
        first.pop("occurrence_id", None)
        first["occurrences"] = members
        first["source_refs"] = [copy.deepcopy(ref) for member in members for ref in member["source_refs"]]
        first["evidence_state"] = "VERIFIED" if members and all(m["evidence_state"] == "VERIFIED" for m in members) else "UNVERIFIED"
        first[("deliverable_id" if prefix == "dlv_" else "clause_id")] = _id(prefix, key)
        output.append(first)
    return output


def build_contract_hygiene(deliverables, clauses, legacy_risks, validate_refs, package_metadata):
    deliverable_occurrences, legacy_deliverables = [], []
    for raw in deliverables or []:
        occurrence = normalize_deliverable_occurrence(raw, validate_refs, package_metadata)
        if occurrence is None:
            item = copy.deepcopy(raw) if isinstance(raw, dict) else {"description": str(raw)}
            item.update({"evidence_state": "UNVERIFIED", "assessment_basis": "LEGACY_EXTRACTION"})
            legacy_deliverables.append(item)
        else:
            deliverable_occurrences.append(occurrence)
    clause_occurrences, legacy_clauses = [], []
    for raw in clauses or []:
        occurrence = normalize_clause_occurrence(raw, validate_refs, package_metadata)
        if occurrence is None:
            item = copy.deepcopy(raw) if isinstance(raw, dict) else {"details": str(raw)}
            item.update({"evidence_state": "UNVERIFIED", "assessment_basis": "LEGACY_EXTRACTION"})
            legacy_clauses.append(item)
        else:
            clause_occurrences.append(occurrence)
    legacy_risk_records = []
    for raw in legacy_risks or []:
        item = copy.deepcopy(raw) if isinstance(raw, dict) else {"details": str(raw)}
        item.update({"evidence_state": "UNVERIFIED", "assessment_basis": "LEGACY_EXTRACTION"})
        legacy_risk_records.append(item)
    return {
        "version": VERSION,
        "deliverable_occurrences": deliverable_occurrences,
        "deliverables": _logical_records(deliverable_occurrences, _deliverable_key, "dlv_"),
        "clause_occurrences": clause_occurrences,
        "clauses": _logical_records(clause_occurrences, _clause_key, "clause_"),
        "legacy_deliverables": legacy_deliverables,
        "legacy_clauses": legacy_clauses,
        "legacy_risks": legacy_risk_records,
    }


def validate_assessments(assessments, verified_clauses):
    clauses = {item["clause_id"]: item for item in verified_clauses if item.get("evidence_state") == "VERIFIED"}
    output = []
    for raw in assessments or []:
        if not isinstance(raw, dict):
            raise ValueError("INVALID_RISK_ASSESSMENT")
        allowed = {"clause_ids", "clause_kind", "assessment_state", "interpretation_code",
                   "assessment_basis", "user_decision"}
        if set(raw) - allowed:
            raise ValueError("UNSUPPORTED_INTERPRETATION")
        state = raw.get("assessment_state")
        ids = raw.get("clause_ids")
        if state not in ASSESSMENT_STATES or not isinstance(ids, list) or not ids:
            raise ValueError("INVALID_RISK_ASSESSMENT")
        if any(cid not in clauses for cid in ids):
            raise ValueError("UNKNOWN_CLAUSE_ID")
        if raw.get("user_decision") is not None or raw.get("assessment_basis") != "AI_ASSISTED" or "severity" in raw:
            raise ValueError("INVENTED_RISK_AUTHORITY")
        code = raw.get("interpretation_code")
        expected_code = "REVIEW_CLAUSE_TERMS" if state == "REVIEW" else "INSUFFICIENT_CONTEXT"
        if code not in INTERPRETATION_CODES or code != expected_code:
            raise ValueError("INVALID_RISK_ASSESSMENT")
        factual = {"clause_ids": sorted(set(ids)), "assessment_state": state,
                   "interpretation_code": code, "why_it_matters": INTERPRETATION_TEXT[code],
                   "assessment_basis": "AI_ASSISTED", "user_decision": None}
        output.append({"assessment_id": _id("ra_", factual), **factual})
    return output


def authoritative_sections(hygiene, assessments=None):
    verified_deliverables = [copy.deepcopy(item) for item in hygiene.get("deliverables", [])
                             if item.get("evidence_state") == "VERIFIED"
                             and item.get("responsible_actor") == "SUPPLIER"]
    verified_clauses = [copy.deepcopy(item) for item in hygiene.get("clauses", [])
                        if item.get("evidence_state") == "VERIFIED"]
    checked = validate_assessments(assessments or [], verified_clauses)
    by_clause = {}
    for assessment in checked:
        for cid in assessment["clause_ids"]:
            by_clause.setdefault(cid, []).append(assessment)
    risks = []
    for clause in verified_clauses:
        item = copy.deepcopy(clause)
        item["assessment"] = copy.deepcopy(by_clause.get(clause["clause_id"], []))
        risks.append(item)
    # Historical records stay visible but remain explicitly unverified.
    legacy_deliverables = copy.deepcopy(hygiene.get("legacy_deliverables", []))
    legacy_clauses = copy.deepcopy(hygiene.get("legacy_clauses", []))
    legacy_risks = copy.deepcopy(hygiene.get("legacy_risks", []))
    return verified_deliverables + legacy_deliverables, verified_clauses + legacy_clauses, risks + legacy_risks


def structured_deliverable_conflicts(records, start_index=1):
    """Compare only commensurable verified structured deliverables."""
    groups = {}
    for item in records or []:
        if not isinstance(item, dict) or not item.get("deliverable_id") or item.get("evidence_state") != "VERIFIED":
            continue
        base = (_identity(item.get("title")), tuple(_scope(item.get("scope")).items()),
                tuple(_strings(item.get("conditions"))), item.get("frequency"))
        groups.setdefault(base, []).append(item)
    conflicts = []
    index = start_index
    for base, items in sorted(groups.items(), key=lambda pair: _json(pair[0])):
        quantities = {item.get("quantity") for item in items if item.get("quantity") is not None}
        states = {item.get("obligation_state") for item in items}
        contradiction = None
        if len(quantities) > 1:
            contradiction = "different explicit quantities"
        elif "MANDATORY" in states and "OPTIONAL" in states:
            contradiction = "mandatory and explicitly optional obligations"
        if not contradiction:
            continue
        a = items[0]
        b = next(item for item in items[1:]
                 if item.get("quantity") != a.get("quantity") or item.get("obligation_state") != a.get("obligation_state"))
        def source(item):
            ref = (item.get("source_refs") or [{}])[0]
            return {"doc": ref.get("source_doc", "Source"), "ref": ref.get("section", ""),
                    "text": item.get("description", "")}
        conflicts.append({
            "conflict_id": f"CONF-HYGIENE-{index}", "conflict_type": "SCOPE_CONFLICT",
            "classification": "TRUE_CONFLICT", "confidence": "HIGH",
            "reason": f"Structured contract deliverable has {contradiction} in the same explicit scope.",
            "source_validity": "PHYSICAL_BOTH", "topic": a.get("title"),
            "source_a": source(a), "source_b": source(b),
            "assessment": "The source-grounded structured facts disagree.",
            "recommended_action": "Confirm the authoritative obligation with the contracting authority.",
        })
        index += 1
    return conflicts


_CLAUSE_VALUE_TOKEN_RE = re.compile(
    r"\$\s*[\d,]+(?:\.\d+)?(?:\s*(?:million|m\b|thousand|k\b))?"
    r"|\b\d+(?:\.\d+)?\s*%"
    r"|\b\d+\s*(?:calendar\s+|business\s+)?days?\b"
    r"|\b\d+\s*(?:weeks?|months?|years?)\b",
    re.IGNORECASE,
)


def _clause_value_tokens(text) -> frozenset[str]:
    """Extract a conservative, generic set of quantified value tokens
    (dollar amounts, percentages, day/week/month/year counts) from a
    clause's source_fact. Deliberately topic-agnostic (no clause_kind-
    specific parsing, no unit conversion, no semantic interpretation) --
    it only asks "does this clause state a number", not what the number
    means. Two clauses with no extractable value are never compared by
    number; two clauses whose extracted values agree are never flagged.
    """
    return frozenset(re.sub(r"\s+", " ", token.strip().lower())
                     for token in _CLAUSE_VALUE_TOKEN_RE.findall(_text(text)))


def structured_commercial_clause_conflicts(records, start_index=1):
    """Compare only commensurable verified structured commercial clauses:
    same controlled clause_kind, same normalized topic, and same explicit
    scope -- the narrowest identity a human would need to agree on before
    even asking whether two clauses disagree. Within that bucket, flag a
    contradiction only when at least two clauses each state an extractable
    quantified value (see _clause_value_tokens) and those value-sets
    differ. Clauses with no extractable value, or whose values already
    agree, are never flagged merely because their prose wording differs --
    e.g. two per-service-category restatements of the same compliance
    requirement, or two different sub-topics that happen to share a
    clause_kind, are not compared at all (different topic or no number).
    """
    groups = {}
    for item in records or []:
        if not isinstance(item, dict) or not item.get("clause_id") or item.get("evidence_state") != "VERIFIED":
            continue
        key = (item.get("clause_kind"), _identity(item.get("topic")),
               tuple(_scope(item.get("scope")).items()))
        groups.setdefault(key, []).append(item)
    conflicts = []
    index = start_index
    for key, items in sorted(groups.items(), key=lambda pair: _json(pair[0])):
        if len(items) < 2:
            continue
        tagged = [(item, _clause_value_tokens(item.get("source_fact"))) for item in items]
        tagged = [(item, values) for item, values in tagged if values]
        distinct_value_sets = {values for _, values in tagged}
        if len(distinct_value_sets) < 2:
            continue
        a, a_values = tagged[0]
        b, b_values = next((pair for pair in tagged[1:] if pair[1] != a_values), (None, None))
        if b is None:
            continue

        def source(item):
            ref = (item.get("source_refs") or [{}])[0]
            return {"doc": ref.get("source_doc", "Source"), "ref": ref.get("section", ""),
                    "text": item.get("source_fact", "")}

        conflicts.append({
            "conflict_id": f"CONF-CLAUSE-{index}", "conflict_type": "COMMERCIAL_TERM_CONFLICT",
            "classification": "TRUE_CONFLICT", "confidence": "HIGH",
            "reason": f"Structured commercial clauses of the same kind and topic ({key[0]}: {a.get('topic')}) "
                      f"state different quantified values in the same explicit scope.",
            "source_validity": "PHYSICAL_BOTH", "topic": a.get("topic"),
            "source_a": source(a), "source_b": source(b),
            "assessment": f"Extracted values disagree: {sorted(a_values)} vs. {sorted(b_values)}.",
            "recommended_action": "Confirm the authoritative term with the contracting authority.",
            "candidates": [
                {"clause_id": candidate.get("clause_id"), "topic": candidate.get("topic"),
                 "extracted_values": sorted(values), "source_refs": candidate.get("source_refs", [])}
                for candidate, values in tagged
            ],
        })
        index += 1
    return conflicts
