"""Deterministic canonical opportunity ledger and executive-field resolution.

The ledger is immutable input evidence.  Resolution creates a separate view and
never removes observations, occurrences, weak provenance, or superseded history.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation

SCHEMA_VERSION = "canonical-opportunity/1"

FAMILIES = {"IDENTITY", "MILESTONE", "CONTRACT_TERM", "MONETARY", "PROCUREMENT_MECHANIC", "DOCUMENT_ROLE"}
ROLES = {"MAIN_SOLICITATION", "AMENDMENT", "ADDENDUM", "FAQ_QA", "CONTRACT_TERMS", "PRICING_SCHEDULE", "RESPONSE_TEMPLATE", "TECHNICAL_SPECIFICATION", "EVALUATION_SCHEDULE", "ANNEX", "OTHER", "UNKNOWN"}
MILESTONES = {"SUBMISSION_DEADLINE", "CLARIFICATION_DEADLINE", "INTENT_TO_BID_DEADLINE", "SITE_VISIT", "BRIEFING", "PRESENTATION_OR_DEMO", "AWARD_DATE", "CONTRACT_START", "CONTRACT_END", "IMPLEMENTATION_DEADLINE", "DELIVERY_DEADLINE", "BID_VALIDITY_END", "PUBLICATION_DATE", "AMENDMENT_DATE", "PAYMENT_MILESTONE", "OTHER", "UNKNOWN"}
TERM_KINDS = {"INITIAL_DURATION", "COMMENCEMENT_DATE", "END_DATE", "EXTENSION_OPTION", "RENEWAL_OPTION", "MAXIMUM_TERM", "TERMINATION_CONDITION", "TERM_STATEMENT"}
MONEY_KINDS = {"ESTIMATED_CONTRACT_VALUE", "MAXIMUM_CONTRACT_VALUE", "FRAMEWORK_CEILING", "BUDGET", "ANNUAL_VALUE", "LOT_VALUE", "MINIMUM_SPEND", "GUARANTEED_SPEND", "FORECAST_VALUE", "EVALUATION_SCENARIO_VALUE", "RATE_CAP", "UNIT_RATE", "MILESTONE_PAYMENT", "OTHER", "UNKNOWN"}
MECHANICS = {"RFP", "ITT", "RFQ", "SINGLE_SUPPLIER_AWARD", "MULTIPLE_SUPPLIER_AWARD", "STANDING_OFFER", "FRAMEWORK", "PANEL", "CALL_OFF", "LOTS", "FIXED_PRICE", "RATE_CARD", "HOURLY_RATE", "DAILY_RATE", "MILESTONE_PAYMENT", "SUBSCRIPTION", "RETAINER", "RATE_CAP", "ESCALATION_CAP", "NO_GUARANTEED_VOLUME", "EXTENSION_PRICING", "EVALUATED_SCENARIO"}
IDENTITY_KINDS = {"OPPORTUNITY_TITLE", "DOCUMENT_TITLE", "BUYER_NAME", "ISSUING_AUTHORITY", "SOLICITATION_NUMBER", "DOCUMENT_REFERENCE_NUMBER"}
SUPERSESSION_BASES = {"EXPLICIT_REVISED_VALUE", "EXPLICIT_EXTENSION", "EXPLICIT_REPLACEMENT", "EXPLICIT_SUPERSEDES_STATEMENT", "EXPLICIT_OLD_TO_NEW_RELATIONSHIP"}

FIELD_KINDS = {
    "title": ("IDENTITY", {"OPPORTUNITY_TITLE"}),
    "client": ("IDENTITY", {"BUYER_NAME"}),
    "file_number": ("IDENTITY", {"SOLICITATION_NUMBER"}),
    "submission_deadline": ("MILESTONE", {"SUBMISSION_DEADLINE"}),
    "clarification_deadline": ("MILESTONE", {"CLARIFICATION_DEADLINE"}),
}
KINDS_BY_FAMILY = {"IDENTITY": IDENTITY_KINDS, "MILESTONE": MILESTONES,
                   "CONTRACT_TERM": TERM_KINDS, "MONETARY": MONEY_KINDS,
                   "PROCUREMENT_MECHANIC": MECHANICS, "DOCUMENT_ROLE": ROLES}


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _id(prefix, value):
    return prefix + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm(value):
    return _text(value).casefold()


def _valid_iso_date(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value or "")):
        return False
    try:
        date.fromisoformat(str(value))
        return True
    except ValueError:
        return False


def _scope(raw):
    scope = raw.get("scope") if isinstance(raw.get("scope"), dict) else {}
    for key in ("component", "lot", "category", "period_basis", "option_sequence", "option_id"):
        if raw.get(key) not in (None, ""):
            scope[key] = raw[key]
    return {str(k): _text(v) for k, v in sorted(scope.items()) if v not in (None, "")}


def _coordinates(ref):
    keys = ("page", "sheet", "section", "row", "rows", "row_start", "row_end", "cell", "cells", "range", "row_range", "cell_range")
    return {k: ref[k] for k in keys if ref.get(k) not in (None, "")}


def _parse_marker(marker):
    body = marker[2:-2]
    parts = [p.strip() for p in body.split("|")]
    if not parts or not parts[0].upper().startswith("SOURCE:"):
        return None
    parsed = {"source_doc": parts[0].split(":", 1)[1].strip()}
    for part in parts[1:]:
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        parsed[key.strip().lower()] = value.strip()
    return parsed


def _row_interval(value):
    if isinstance(value, int): return (value, value)
    match = re.fullmatch(r"\s*(\d+)\s*(?:[-:]\s*(\d+)\s*)?", str(value))
    return (int(match.group(1)), int(match.group(2) or match.group(1))) if match else None


def _cell(value):
    match = re.fullmatch(r"\s*([A-Za-z]+)(\d+)\s*", str(value))
    return (match.group(1).upper(), int(match.group(2))) if match else None


def _locator_matches(parsed, ref):
    if ref.get("page") is not None:
        try:
            if int(parsed.get("page", "")) != int(ref["page"]): return False
        except (TypeError, ValueError): return False
    for key in ("sheet", "section"):
        if ref.get(key) is not None and _norm(parsed.get(key)) != _norm(ref[key]): return False
    marker_rows = _row_interval(parsed.get("rows"))
    requested = ref.get("rows", ref.get("row_range", ref.get("row")))
    if requested is None and (ref.get("row_start") is not None or ref.get("row_end") is not None):
        requested = f"{ref.get('row_start', ref.get('row_end'))}-{ref.get('row_end', ref.get('row_start'))}"
    if requested is not None:
        wanted = _row_interval(requested)
        if not marker_rows or not wanted or wanted[0] < marker_rows[0] or wanted[1] > marker_rows[1]: return False
    marker_cells = parsed.get("cells") or parsed.get("range")
    requested_cells = ref.get("cells", ref.get("cell_range", ref.get("cell")))
    if requested_cells is not None:
        if not marker_cells: return False
        marker_parts = [p.strip() for p in re.split(r"[:-]", marker_cells)]
        wanted_parts = [p.strip() for p in re.split(r"[:-]", str(requested_cells))]
        m = [_cell(p) for p in marker_parts]; w = [_cell(p) for p in wanted_parts]
        if any(x is None for x in m + w): return False
        if len(m) == 1: m *= 2
        if len(w) == 1: w *= 2
        if not (m[0][0] <= w[0][0] <= w[1][0] <= m[1][0] and m[0][1] <= w[0][1] <= w[1][1] <= m[1][1]): return False
    return True


def _source_segment(text, source_doc, ref):
    if not text:
        return ""
    marker = re.compile(r"\[\[SOURCE:\s*([^|\]]+)(.*?)\]\]", re.I)
    matches = list(marker.finditer(text))
    wanted = _coordinates(ref)
    for i, match in enumerate(matches):
        parsed = _parse_marker(match.group(0))
        if not parsed or _norm(parsed["source_doc"]) != _norm(source_doc):
            continue
        if _locator_matches(parsed, ref):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            return text[match.end():end]
    return ""


def _validate_ref(ref, package_metadata):
    ref = copy.deepcopy(ref) if isinstance(ref, dict) else {}
    files = {str(x).casefold(): x for x in package_metadata.get("files", [])}
    source_doc = files.get(_norm(ref.get("source_doc")))
    excerpt = _text(ref.get("excerpt"))
    if not source_doc:
        return ref, "UNVERIFIED"
    ref["source_doc"] = source_doc
    text = package_metadata.get("doc_texts", {}).get(source_doc, "")
    segment = _source_segment(text, source_doc, ref)
    grounded = bool(excerpt and segment and _norm(excerpt) in _norm(segment))
    locator = bool(_coordinates(ref))
    if grounded and locator:
        return ref, "VERIFIED"
    if source_doc and (locator or grounded):
        return ref, "PARTIAL"
    return ref, "UNVERIFIED"


def _normalized_value(family, kind, raw):
    value = raw.get("normalized_value", raw.get("original_value", raw.get("value")))
    if family == "MONETARY":
        amount = raw.get("amount", value)
        try:
            amount = format(Decimal(str(amount).replace(",", "").strip()), "f")
        except (InvalidOperation, ValueError, AttributeError):
            return {"amount": None, "currency": _text(raw.get("currency")).upper() or None}, "UNPARSED"
        return {"amount": amount, "currency": _text(raw.get("currency")).upper() or None,
                "tax_basis": _text(raw.get("tax_basis")).upper() or "UNSPECIFIED",
                "guarantee_status": _text(raw.get("guarantee_status")).upper() or "UNSPECIFIED",
                "period_basis": _text(raw.get("period_basis")) or None}, "NORMALIZED"
    if family == "MILESTONE":
        date_value, precision, time_value = raw.get("date") or value, _text(raw.get("precision") or "DATE").upper(), raw.get("time")
        if precision == "DAY": precision = "DATE"
        try:
            if precision not in {"DATE", "DATETIME", "MONTH", "YEAR", "UNKNOWN"}: raise ValueError
            if precision in {"DATE", "DATETIME"} and not _valid_iso_date(date_value): raise ValueError
            if precision == "DATETIME" and time_value is None: raise ValueError
            if time_value is not None and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?", str(time_value)): raise ValueError
        except (TypeError, ValueError):
            return {"date": date_value, "time": time_value, "timezone": raw.get("timezone"), "precision": precision}, "UNPARSED"
        return {"date": date_value, "time": time_value, "timezone": raw.get("timezone"), "precision": precision}, "NORMALIZED"
    if family == "CONTRACT_TERM":
        if kind in {"COMMENCEMENT_DATE", "END_DATE"}:
            date_value, precision = raw.get("date") or value, _text(raw.get("precision") or "DATE").upper()
            if precision == "DAY": precision = "DATE"
            try:
                if precision not in {"DATE", "MONTH", "YEAR", "UNKNOWN"}: raise ValueError
                if precision == "DATE": date.fromisoformat(str(date_value))
            except (TypeError, ValueError):
                return {"date": date_value, "precision": precision}, "UNPARSED"
            return {"date": date_value, "precision": precision}, "NORMALIZED"
        return {k: raw.get(k) for k in ("duration", "unit", "start_date", "end_date", "option_count", "optional", "conditions") if raw.get(k) is not None} or _text(value), "NORMALIZED"
    return _norm(value), "NORMALIZED" if _text(value) else "EMPTY"


def _physical_key(source_doc, refs, pointer):
    coords = [_coordinates(r) for r in refs]
    return {"source_document": source_doc, "coordinates": sorted(coords, key=canonical_json), "source_pointer": pointer}


def build_canonical_opportunity(doc_facts_list, package_metadata):
    """Build a complete, order-independent observation ledger from Stage A facts."""
    docs = []
    for name in sorted(package_metadata.get("files", []), key=str.casefold):
        docs.append({"source_document_id": _id("doc_", {"version": SCHEMA_VERSION, "name": name.casefold()}), "source_doc": name})
    doc_ids = {d["source_doc"].casefold(): d["source_document_id"] for d in docs}
    logical = {}
    collisions, invalid = [], []
    for df in doc_facts_list:
        for index, raw in enumerate(df.get("typed_observations") or []):
            if not isinstance(raw, dict):
                continue
            family, kind = _text(raw.get("family")).upper(), _text(raw.get("semantic_kind")).upper()
            if family not in FAMILIES or kind not in KINDS_BY_FAMILY.get(family, set()):
                invalid.append({"digest": _id("invalid_", raw), "family": family, "semantic_kind": kind,
                                "validation_state": "INVALID_FAMILY_KIND"})
                continue
            refs, statuses = [], []
            for ref in raw.get("source_refs") or []:
                clean, status = _validate_ref(ref, package_metadata)
                refs.append(clean); statuses.append(status)
            source_doc = _text(raw.get("source_doc") or (refs[0].get("source_doc") if refs else ""))
            source_id = doc_ids.get(source_doc.casefold(), _id("doc_", {"version": SCHEMA_VERSION, "name": source_doc.casefold()}))
            normalized, norm_state = _normalized_value(family, kind, raw)
            scope = _scope(raw)
            pointer = _text(raw.get("source_pointer"))
            ident = {"version": SCHEMA_VERSION, "family": family, "semantic_kind": kind,
                     "original_value": _text(raw.get("original_value", raw.get("value"))),
                     "source_document_id": source_id, "source_coordinates": sorted((_coordinates(r) for r in refs), key=canonical_json),
                     "scope": scope, "source_pointer": pointer}
            oid = _id("obs_", ident)
            nid = _id("norm_", {"version": SCHEMA_VERSION, "family": family, "semantic_kind": kind,
                                "normalized_value": normalized, "scope": scope})
            occurrence = {"source_pointer": pointer, "digest": _id("occ_", {"observation": oid, "raw": raw}), "count": 1}
            if oid in logical:
                if logical[oid]["identity_material"] != ident:
                    collisions.append(oid)
                else:
                    existing = next((x for x in logical[oid]["extraction_occurrences"] if x["digest"] == occurrence["digest"]), None)
                    if existing: existing["count"] += 1
                    else: logical[oid]["extraction_occurrences"].append(occurrence)
                continue
            provenance = "VERIFIED" if statuses and all(s == "VERIFIED" for s in statuses) else "PARTIAL" if any(s in {"VERIFIED", "PARTIAL"} for s in statuses) else "UNVERIFIED"
            supersession = raw.get("supersession") if isinstance(raw.get("supersession"), dict) else {}
            logical[oid] = {"observation_id": oid, "normalized_identity_id": nid, "family": family,
                "semantic_kind": kind, "original_value": raw.get("original_value", raw.get("value")),
                "normalized_value": normalized, "normalization_state": norm_state,
                "source_document_id": source_id, "source_doc": source_doc, "source_refs": refs,
                "provenance_status": provenance, "document_role": raw.get("document_role") if raw.get("document_role") in ROLES else "UNKNOWN",
                "document_role_basis": raw.get("document_role_basis"), "source_state": raw.get("source_state") or "ACTIVE",
                "source_pointer": pointer, "scope": scope, "supersession": supersession,
                "supersession_state": "ACTIVE", "conflict_ids": [], "extraction_occurrences": [occurrence],
                "identity_material": ident}
    ledger = sorted(logical.values(), key=lambda x: x["observation_id"])
    for observation in ledger:
        observation["extraction_occurrences"].sort(key=lambda x: x["digest"])
        sup = observation.get("supersession") or {}
        if sup.get("basis") not in SUPERSESSION_BASES:
            continue
        sup_refs, sup_states = [], []
        for ref in sup.get("source_refs") or []:
            clean, state = _validate_ref(ref, package_metadata); sup_refs.append(clean); sup_states.append(state)
        sup["source_refs"] = sup_refs
        sup["provenance_status"] = "VERIFIED" if sup_states and all(x == "VERIFIED" for x in sup_states) else "UNVERIFIED"
        target_family = _text(sup.get("target_family")).upper()
        target_kind = _text(sup.get("target_semantic_kind")).upper()
        target_scope = {str(k): _text(v) for k, v in sorted((sup.get("scope") or {}).items()) if v not in (None, "")}
        targets = [o for o in ledger if o["observation_id"] != observation["observation_id"] and o["family"] == target_family
                   and o["semantic_kind"] == target_kind and o["scope"] == target_scope and _norm(o["original_value"]) == _norm(sup.get("old_value"))]
        new_matches = _norm(observation["original_value"]) == _norm(sup.get("new_value"))
        identities = {o["normalized_identity_id"] for o in targets}
        if sup["provenance_status"] == "VERIFIED" and new_matches and len(identities) == 1:
            sup["supersedes_observation_ids"] = sorted(o["observation_id"] for o in targets)
            sup["resolution_state"] = "RESOLVED"
        else:
            sup["resolution_state"] = "UNRESOLVED"
    canonical = {"schema_version": SCHEMA_VERSION, "documents": docs, "observations": ledger,
                 "resolved": {}, "conflicts": [], "coverage": {}, "integrity_diagnostics": {"collision_ids": sorted(collisions), "collision_free": not collisions, "invalid_observations": sorted(invalid, key=canonical_json)},
                 "input_digest": _id("input_", {"documents": docs, "observations": ledger})}
    return canonical


def _empty(status="MISSING", conflicts=None):
    return {"status": status, "value": None, "observation_ids": [], "conflict_ids": conflicts or [],
            "resolution_basis": None, "provenance_status": "UNVERIFIED"}


def _conflict(field, observations, values):
    affected = "/resolved/" + field
    cid = _id("conf_", {"version": SCHEMA_VERSION, "field": affected, "observations": sorted(o["observation_id"] for o in observations), "values": values})
    return {"conflict_id": cid, "state": "ACTIVE", "semantic_kind": observations[0]["semantic_kind"],
            "scope": observations[0].get("scope", {}), "affected_fields": [affected], "link_status": "LINKED",
            "affected_observation_ids": sorted(o["observation_id"] for o in observations), "incompatible_values": values,
            "source_refs": [r for o in observations for r in o.get("source_refs", [])], "resolution_basis": None, "resolved_by": None}


def _apply_supersession(observations, diagnostics):
    by_id = {o["observation_id"]: o for o in observations}
    graph = {}
    for obs in observations:
        sup = obs.get("supersession") or {}
        targets = sup.get("supersedes_observation_ids") or []
        if sup.get("basis") not in SUPERSESSION_BASES or not targets or sup.get("provenance_status") != "VERIFIED":
            continue
        graph[obs["observation_id"]] = [x for x in targets if x in by_id]
    visiting, visited, cycles = set(), set(), set()
    def visit(node):
        if node in visiting: cycles.add(node); return
        if node in visited: return
        visiting.add(node)
        for child in graph.get(node, []): visit(child)
        visiting.remove(node); visited.add(node)
    for node in graph: visit(node)
    diagnostics["supersession_cycles"] = sorted(cycles)
    if cycles: return
    for newer, targets in graph.items():
        for target in targets:
            by_id[target]["supersession_state"] = "SUPERSEDED"
            by_id[target]["superseded_by"] = newer


def _resolve_simple(field, observations, conflicts):
    family, kinds = FIELD_KINDS[field]
    candidates = [o for o in observations if o["family"] == family and o["semantic_kind"] in kinds and
                  o["supersession_state"] == "ACTIVE" and o["normalization_state"] not in {"EMPTY", "UNPARSED"}]
    if family == "MILESTONE":
        # Component/lot events remain in the ledger and never compete for an
        # opportunity-level executive deadline.
        candidates = [o for o in candidates if not o.get("scope")]
        if field in {"submission_deadline", "clarification_deadline"}:
            candidates = [o for o in candidates if o.get("normalized_value", {}).get("precision") in {"DATE", "DATETIME"}]
    eligible = [o for o in candidates if o["provenance_status"] == "VERIFIED"]
    if not candidates:
        return _empty("UNVERIFIED" if any(o["family"] == family and o["semantic_kind"] in kinds for o in observations) else "MISSING")
    if not eligible: return _empty("UNVERIFIED")
    groups = {}
    for o in eligible: groups.setdefault(canonical_json(o["normalized_value"]), []).append(o)
    if len(groups) != 1:
        c = _conflict(field, eligible, sorted((json.loads(v) for v in groups), key=canonical_json))
        conflicts.append(c)
        for o in eligible: o["conflict_ids"].append(c["conflict_id"])
        return _empty("CONFLICTED", [c["conflict_id"]])
    support = next(iter(groups.values()))
    value = support[0]["original_value"]
    if family == "MILESTONE": value = support[0]["normalized_value"]
    superseded = any((o.get("supersession") or {}).get("resolution_state") == "RESOLVED" for o in support)
    return {"status": "RESOLVED", "value": value, "observation_ids": sorted(o["observation_id"] for o in support),
            "conflict_ids": [], "resolution_basis": "RESOLVED_BY_SUPERSESSION" if superseded else "EXACT_AGREEMENT", "provenance_status": "VERIFIED"}


def _resolve_client(observations, conflicts):
    buyers = [o for o in observations if o["family"] == "IDENTITY" and o["semantic_kind"] == "BUYER_NAME"]
    if buyers:
        return _resolve_simple("client", observations, conflicts)
    issuers = copy.deepcopy(observations)
    for o in issuers:
        if o["family"] == "IDENTITY" and o["semantic_kind"] == "ISSUING_AUTHORITY": o["semantic_kind"] = "BUYER_NAME"
    result = _resolve_simple("client", issuers, conflicts)
    if result["status"] == "RESOLVED": result["resolution_basis"] = "ISSUING_AUTHORITY_FALLBACK"
    return result


def _resolve_term(observations, conflicts):
    terms = [o for o in observations if o["family"] == "CONTRACT_TERM" and o["supersession_state"] == "ACTIVE" and o["provenance_status"] == "VERIFIED"]
    if not terms: return _empty("UNVERIFIED" if any(o["family"] == "CONTRACT_TERM" for o in observations) else "MISSING")
    groups = {}
    for o in terms: groups.setdefault((o["semantic_kind"], canonical_json(o["normalized_value"]), canonical_json(o["scope"])), []).append(o)
    by_kind = {}
    for (kind, value, scope), items in groups.items(): by_kind.setdefault((kind, scope), []).append((value, items))
    repeatable = {"EXTENSION_OPTION", "RENEWAL_OPTION"}
    bad = []
    for (kind, scope), items in by_kind.items():
        if kind not in repeatable:
            if len(items) > 1: bad.append(items)
        elif json.loads(scope).get("option_sequence") or json.loads(scope).get("option_id"):
            if len(items) > 1: bad.append(items)
    if bad:
        impacted = [o for group in bad for _, items in group for o in items]
        c = _conflict("contract_term", impacted, sorted({canonical_json(o["normalized_value"]) for o in impacted}))
        conflicts.append(c)
        return _empty("CONFLICTED", [c["conflict_id"]])
    # A source-stated month duration must agree with exact start/end calendar
    # coordinates when all three are available. Approximate conversions are forbidden.
    initial = [o for o in terms if o["semantic_kind"] == "INITIAL_DURATION" and isinstance(o["normalized_value"], dict)]
    starts = [o for o in terms if o["semantic_kind"] == "COMMENCEMENT_DATE"]
    ends = [o for o in terms if o["semantic_kind"] == "END_DATE"]
    if len(initial) == len(starts) == len(ends) == 1:
        duration = initial[0]["normalized_value"]
        try:
            count = int(duration.get("duration"))
            unit = _norm(duration.get("unit"))
            start = date.fromisoformat(starts[0]["normalized_value"]["date"])
            end = date.fromisoformat(ends[0]["normalized_value"]["date"])
            months = count * (12 if unit in {"year", "years"} else 1) if unit in {"month", "months", "year", "years"} else None
            if months is not None:
                target_month = start.month - 1 + months
                target_year, target_month = start.year + target_month // 12, target_month % 12 + 1
                consistent = (end.year, end.month, end.day) == (target_year, target_month, start.day)
                if not consistent:
                    impacted = initial + starts + ends
                    c = _conflict("contract_term", impacted, [duration, starts[0]["normalized_value"], ends[0]["normalized_value"]])
                    c["semantic_kind"] = "TERM_DURATION_DATE_INCONSISTENCY"
                    conflicts.append(c)
                    return _empty("CONFLICTED", [c["conflict_id"]])
        except (TypeError, ValueError):
            pass
    values = [{"kind": o["semantic_kind"], "value": o["normalized_value"], "scope": o["scope"]} for o in terms]
    return {"status": "RESOLVED", "value": sorted(values, key=canonical_json), "observation_ids": sorted(o["observation_id"] for o in terms),
            "conflict_ids": [], "resolution_basis": "STRUCTURED_COMPONENTS", "provenance_status": "VERIFIED"}


def _resolve_money(observations, conflicts):
    candidates = [o for o in observations if o["family"] == "MONETARY" and o["semantic_kind"] == "ESTIMATED_CONTRACT_VALUE" and
                  o["supersession_state"] == "ACTIVE" and o["provenance_status"] == "VERIFIED" and not o["scope"] and
                  isinstance(o["normalized_value"], dict) and o["normalized_value"].get("currency")]
    if not candidates: return _empty("UNVERIFIED" if any(o["family"] == "MONETARY" and o["semantic_kind"] == "ESTIMATED_CONTRACT_VALUE" for o in observations) else "MISSING")
    groups = {}
    for o in candidates: groups.setdefault(canonical_json(o["normalized_value"]), []).append(o)
    if len(groups) != 1:
        c = _conflict("headline_value", candidates, sorted(json.loads(v) for v in groups)); conflicts.append(c)
        return _empty("CONFLICTED", [c["conflict_id"]])
    support = next(iter(groups.values()))
    return {"status": "RESOLVED", "value": support[0]["normalized_value"], "observation_ids": sorted(o["observation_id"] for o in support),
            "conflict_ids": [], "resolution_basis": "EXACT_ESTIMATED_VALUE_AGREEMENT", "provenance_status": "VERIFIED"}


def _resolve_classifications(observations):
    mechanics = {o["semantic_kind"] for o in observations if o["family"] == "PROCUREMENT_MECHANIC" and o["provenance_status"] == "VERIFIED" and o["supersession_state"] == "ACTIVE"}
    ids = sorted(o["observation_id"] for o in observations if o["semantic_kind"] in mechanics)
    opportunity = "Panel Agreement" if "PANEL" in mechanics else "Standing Offer" if "STANDING_OFFER" in mechanics else None
    model = ("Standing Offer Panel" if "STANDING_OFFER" in mechanics and ({"MULTIPLE_SUPPLIER_AWARD", "PANEL"} & mechanics)
             else "Multi-vendor Call-off" if {"MULTIPLE_SUPPLIER_AWARD", "CALL_OFF"} <= mechanics
             else "Single Contract" if "SINGLE_SUPPLIER_AWARD" in mechanics else None)
    def result(value):
        return {"status": "RESOLVED" if value else "NOT_CLASSIFIED", "value": value, "observation_ids": ids if value else [],
                "conflict_ids": [], "resolution_basis": "EXPLICIT_MECHANICS" if value else None,
                "provenance_status": "VERIFIED" if value else "UNVERIFIED", "stage_d_tier2_permitted": not bool(value)}
    return result(opportunity), result(model)


def resolve_canonical_opportunity(canonical):
    result = copy.deepcopy(canonical)
    observations, conflicts = result["observations"], []
    _apply_supersession(observations, result["integrity_diagnostics"])
    for field in FIELD_KINDS:
        result["resolved"][field] = _resolve_client(observations, conflicts) if field == "client" else _resolve_simple(field, observations, conflicts)
    result["resolved"]["contract_term"] = _resolve_term(observations, conflicts)
    result["resolved"]["headline_value"] = _resolve_money(observations, conflicts)
    opportunity, model = _resolve_classifications(observations)
    result["resolved"]["opportunity_type"], result["resolved"]["procurement_model"] = opportunity, model
    for field, (family, kinds) in FIELD_KINDS.items():
        present = any(o["family"] == family and o["semantic_kind"] in kinds for o in observations)
        if field == "client": present = present or any(o["family"] == "IDENTITY" and o["semantic_kind"] == "ISSUING_AUTHORITY" for o in observations)
        state = result["resolved"][field]
        result["coverage"][field] = {"typed_observations_present": present,
            "canonical_conflict_authoritative": state["status"] == "CONFLICTED" or state.get("resolution_basis") == "RESOLVED_BY_SUPERSESSION"}
    result["coverage"]["contract_term"] = {"typed_observations_present": any(o["family"] == "CONTRACT_TERM" for o in observations), "canonical_conflict_authoritative": any(o["family"] == "CONTRACT_TERM" for o in observations)}
    result["conflicts"] = sorted(conflicts, key=lambda c: c["conflict_id"])
    result["integrity_diagnostics"].update({"observation_count": len(observations), "conflict_count": len(conflicts),
                                             "resolution_complete": True})
    result["input_digest"] = _id("input_", {"documents": result["documents"], "observations": result["observations"]})
    return result


def apply_legacy_conflict_fallback(canonical, legacy_conflicts):
    """Suppress only uncovered fields deterministically identified by legacy conflicts."""
    result = copy.deepcopy(canonical)
    for conflict in legacy_conflicts:
        text = " ".join(str(conflict.get(k) or "") for k in ("conflict_type", "topic", "reason")).casefold()
        field = ("clarification_deadline" if any(x in text for x in ("clarification deadline", "question deadline", "questions deadline"))
                 else "submission_deadline" if any(x in text for x in ("submission deadline", "closing date", "response deadline"))
                 else "contract_term" if any(x in text for x in ("contract term", "contract duration", "initial term")) else None)
        if not field:
            continue
        resolved = result.get("resolved", {}).get(field, {})
        if resolved.get("status") == "CONFLICTED":
            continue
        safely_superseded = False
        if resolved.get("resolution_basis") == "RESOLVED_BY_SUPERSESSION":
            legacy_text = _norm(canonical_json(conflict))
            for observation in result.get("observations", []):
                sup = observation.get("supersession") or {}
                if (observation["observation_id"] in resolved.get("observation_ids", [])
                        and sup.get("resolution_state") == "RESOLVED"
                        and _norm(sup.get("old_value")) in legacy_text
                        and _norm(sup.get("new_value")) in legacy_text):
                    safely_superseded = True
                    break
        if safely_superseded:
            result["coverage"].setdefault(field, {})["legacy_conflict_accounted_by_supersession"] = True
            continue
        cid = str(conflict.get("conflict_id") or _id("legacy_conf_", conflict))
        result["resolved"][field] = _empty("CONFLICTED", [cid])
        result["coverage"].setdefault(field, {})["legacy_conflict_fallback"] = True
    return result


def compact_stage_d_summary(canonical):
    """Prompt-safe canonical view; full ledger remains in the sidecar."""
    mechanics = sorted({o["semantic_kind"] for o in canonical.get("observations", []) if o["family"] == "PROCUREMENT_MECHANIC" and o["provenance_status"] == "VERIFIED"})
    return {"schema_version": SCHEMA_VERSION,
            "resolved": {k: {x: v.get(x) for x in ("status", "value", "conflict_ids", "resolution_basis", "stage_d_tier2_permitted") if x in v}
                         for k, v in sorted(canonical.get("resolved", {}).items())},
            "conflicts": [{k: c.get(k) for k in ("conflict_id", "state", "semantic_kind", "affected_fields", "link_status", "incompatible_values")} for c in canonical.get("conflicts", [])],
            "observations": [{"observation_id": o["observation_id"], "family": o["family"], "semantic_kind": o["semantic_kind"],
                              "original_value": o["original_value"], "normalized_value": o["normalized_value"], "scope": o["scope"],
                              "source_doc": o["source_doc"]} for o in canonical.get("observations", [])
                             if o["family"] == "PROCUREMENT_MECHANIC" and o["provenance_status"] == "VERIFIED"],
            "verified_mechanics": mechanics, "coverage": canonical.get("coverage", {}), "input_digest": canonical.get("input_digest")}


def format_contract_term(resolved):
    if resolved.get("status") != "RESOLVED": return "Not stated"
    parts = []
    for item in resolved.get("value") or []:
        value = item.get("value")
        def duration_text(v):
            if not isinstance(v, dict): return _text(v)
            amount, unit = _text(v.get("duration")), _text(v.get("unit"))
            return (amount + (" " + unit if unit else "")).strip()
        if item.get("kind") == "INITIAL_DURATION": parts.append("Initial term: " + duration_text(value))
        elif item.get("kind") in {"EXTENSION_OPTION", "RENEWAL_OPTION"}:
            count = value.get("option_count") if isinstance(value, dict) else None
            conditions = value.get("conditions") if isinstance(value, dict) else None
            label = (f"Up to {count} optional {duration_text(value)} extensions" if count else "Optional extension: " + duration_text(value))
            parts.append(label + ((" subject to " + _text(conditions)) if conditions else ""))
        elif item.get("kind") == "MAXIMUM_TERM": parts.append("Maximum potential term: " + duration_text(value))
        else: parts.append(item.get("kind", "Term").replace("_", " ").title() + ": " + _text(value))
    return "; ".join(p for p in parts if p) or "Not stated"


def apply_authoritative_values(synthesis, canonical):
    out = copy.deepcopy(synthesis) if isinstance(synthesis, dict) else {}
    bid = out.setdefault("bid", {}); brief = out.setdefault("brief", {})
    mapping = {"title": "title", "client": "client", "file_number": "file_number", "submission_deadline": "submission_deadline", "clarification_deadline": "clarification_deadline"}
    for field, key in mapping.items():
        resolved = canonical.get("resolved", {}).get(field, {})
        value = resolved.get("value") if resolved.get("status") == "RESOLVED" else None
        if isinstance(value, dict) and field.endswith("deadline"): value = value.get("date")
        bid[key] = value
    bid["value_cad"] = None
    term = canonical.get("resolved", {}).get("contract_term", {})
    brief["contract_term"] = format_contract_term(term)
    for field in ("opportunity_type", "procurement_model"):
        resolved = canonical.get("resolved", {}).get(field, {})
        if resolved.get("status") == "RESOLVED": brief[field] = resolved.get("value")
        elif not resolved.get("stage_d_tier2_permitted"): brief[field] = None
    return out


def remove_authoritative_values_for_validation(response, canonical):
    """Remove model copies of deterministic fields before legacy citation checks.

    The validated synthesis receives the authoritative values afterward. Tier-2
    classifications remain untouched only where deterministic resolution permits them.
    """
    out = copy.deepcopy(response)
    synthesis = out.get("synthesis", {})
    bid, brief = synthesis.get("bid", {}), synthesis.get("brief", {})
    for field in ("title", "client", "file_number", "submission_deadline", "clarification_deadline"):
        if canonical.get("resolved", {}).get(field, {}).get("status") == "RESOLVED":
            bid[field] = None
    if canonical.get("resolved", {}).get("contract_term", {}).get("status") == "RESOLVED":
        brief["contract_term"] = "Not stated"
    for field in ("opportunity_type", "procurement_model"):
        if canonical.get("resolved", {}).get(field, {}).get("status") == "RESOLVED":
            brief[field] = None
    return out
