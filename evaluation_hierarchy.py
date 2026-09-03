"""
evaluation_hierarchy.py

Focused, pure evaluation hierarchy model and deterministic calculations.
Handles:
- Controlled weight units (Percent, Points, Other, None)
- Controlled weight basis (Overall, Within Parent, Unknown)
- Deterministic weight parsing (parse_evaluation_weight)
- Deterministic criterion identity and deduplication
- Hierarchy tree construction and validation
- Overall total calculation without parent-child double-counting
- Aggregation statuses (VALID, SOURCE_DISCREPANCY, UNRESOLVED_HIERARCHY, MIXED_UNITS, INSUFFICIENT_DATA)
- Child / parent consistency checking
"""
import re
from typing import Any

# Weight units
UNIT_PERCENT = "Percent"
UNIT_POINTS = "Points"
UNIT_OTHER = "Other"
UNIT_NONE = "None"

# Weight basis
BASIS_OVERALL = "Overall"
BASIS_WITHIN_PARENT = "Within Parent"
BASIS_UNKNOWN = "Unknown"

# Aggregation status
STATUS_VALID = "VALID"
STATUS_SOURCE_DISCREPANCY = "SOURCE_DISCREPANCY"
STATUS_UNRESOLVED_HIERARCHY = "UNRESOLVED_HIERARCHY"
STATUS_MIXED_UNITS = "MIXED_UNITS"
STATUS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


def parse_evaluation_weight(raw_weight: Any) -> tuple[float | None, str, str]:
    """
    Deterministically parses a raw weight into (weight_value, weight_unit, weight_basis).
    
    Rules:
    - "40%" -> (40.0, "Percent", "Overall")
    - "40 percent" -> (40.0, "Percent", "Overall")
    - "25 points" / "25 pts" -> (25.0, "Points", "Overall")
    - "50% within Technical" -> (50.0, "Percent", "Within Parent")
    - "Pass/Fail" -> (None, "None", "Unknown")
    - "minimum 70% required" / threshold phrases -> (None, "None", "Unknown") (thresholds are not weights)
    - Empty/None -> (None, "None", "Unknown")
    
    Does NOT parse arbitrary numbers from descriptive sentences.
    """
    if raw_weight is None:
        return None, UNIT_NONE, BASIS_UNKNOWN

    raw_str = str(raw_weight).strip()
    if not raw_str:
        return None, UNIT_NONE, BASIS_UNKNOWN

    lower = raw_str.lower()

    # Pass/fail or qualitative
    if any(k in lower for k in ["pass/fail", "pass / fail", "mandatory", "non-weighted", "qualitative"]):
        return None, UNIT_NONE, BASIS_UNKNOWN

    # Threshold phrases are not weights
    if re.search(r"\b(?:minimum|min|threshold|cutoff|passing)\b", lower):
        return None, UNIT_NONE, BASIS_UNKNOWN

    # Detect basis hints
    basis = BASIS_OVERALL
    if re.search(r"\b(?:within|of\s+(?:the\s+)?(?:parent|stage|technical|category|section))\b", lower):
        basis = BASIS_WITHIN_PARENT
    elif "within parent" in lower:
        basis = BASIS_WITHIN_PARENT

    # Match numeric patterns
    # 1. Percentage
    # e.g. "40%", "40.5%", "40 %", "40 percent", "40 percentage"
    pct_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|percent(?:age)?\b)", raw_str, re.IGNORECASE)
    if pct_match:
        try:
            val = float(pct_match.group(1))
            return val, UNIT_PERCENT, basis
        except (ValueError, TypeError):
            pass

    # 2. Points
    # e.g. "25 points", "25.5 points", "25 pts", "25 pt", "25 marks"
    pts_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:points?|pts?|marks?)\b", raw_str, re.IGNORECASE)
    if pts_match:
        try:
            val = float(pts_match.group(1))
            return val, UNIT_POINTS, basis
        except (ValueError, TypeError):
            pass

    # 3. Clean numeric alone (e.g. 40, "40", "40.0")
    num_alone_match = re.match(r"^(\d+(?:\.\d+)?)$", raw_str.strip())
    if num_alone_match:
        try:
            val = float(num_alone_match.group(1))
            return val, UNIT_PERCENT, basis
        except (ValueError, TypeError):
            pass

    return None, UNIT_NONE, BASIS_UNKNOWN


def normalize_criterion_title(title: str) -> str:
    """Normalize criterion title for robust canonical identity."""
    if not title:
        return ""
    # Strip leading markers like "Stage 1 -", "1.1", bullet points
    t = re.sub(r"^(?:stage\s*\d+\s*[-:–—]?|\d+(?:\.\d+)*\s*[-:–—]?|[•\-*]\s*)", "", title.strip(), flags=re.IGNORECASE)
    # Normalize whitespace and lowercase
    t = re.sub(r"\s+", " ", t).strip()
    return t.lower()


def make_criterion_key(ec: dict) -> tuple:
    """
    Deterministic material identity for evaluation criteria.
    Uses: normalized title + normalized parent title + hierarchy level + normalized weight.
    Two criteria with the same title and parent but differing weights or threshold values
    are preserved rather than silently collapsed.
    """
    title = ec.get("title") or ec.get("stage") or ec.get("criterion") or ""
    norm_title = normalize_criterion_title(str(title))
    
    parent_title = ec.get("parent_title") or ec.get("parent_stage") or ""
    norm_parent = normalize_criterion_title(str(parent_title))
    
    level = ec.get("hierarchy_level", 1 if not norm_parent else 2)
    raw_wt = str(ec.get("weight") or "").strip().lower()
    return (norm_title, norm_parent, level, raw_wt)


def normalize_evaluation_criterion(ec: dict) -> dict:
    """
    Normalizes a single evaluation criterion into the canonical structured model.
    Preserves existing backward-compatible fields (stage, weight, threshold, notes)
    while populating explicit hierarchy fields.
    """
    if not isinstance(ec, dict):
        return {}

    stage = str(ec.get("stage") or ec.get("criterion") or ec.get("title") or "").strip()
    notes = str(ec.get("notes") or "").strip()
    threshold = ec.get("threshold")
    raw_weight = ec.get("weight") or ec.get("points")
    
    # Hierarchy fields
    parent_stage = ec.get("parent_stage") or ec.get("parent_title") or ec.get("parent_criterion_id")
    if parent_stage:
        parent_stage = str(parent_stage).strip()
    else:
        parent_stage = None

    hierarchy_level = ec.get("hierarchy_level")
    if hierarchy_level is None:
        hierarchy_level = 2 if parent_stage else 1
    else:
        try:
            hierarchy_level = int(hierarchy_level)
        except (ValueError, TypeError):
            hierarchy_level = 2 if parent_stage else 1

    criterion_id = ec.get("criterion_id") or ec.get("id")
    if criterion_id:
        criterion_id = str(criterion_id).strip()
    else:
        criterion_id = None

    # Weight parsing
    val, unit, basis = parse_evaluation_weight(raw_weight)
    
    # Override weight_basis if explicitly provided
    explicit_basis = ec.get("weight_basis")
    if explicit_basis in (BASIS_OVERALL, BASIS_WITHIN_PARENT, BASIS_UNKNOWN):
        basis = explicit_basis
    elif explicit_basis and "within" in str(explicit_basis).lower():
        basis = BASIS_WITHIN_PARENT
    elif explicit_basis and "overall" in str(explicit_basis).lower():
        basis = BASIS_OVERALL

    # Override weight_unit if explicitly provided
    explicit_unit = ec.get("weight_unit")
    if explicit_unit in (UNIT_PERCENT, UNIT_POINTS, UNIT_OTHER, UNIT_NONE):
        unit = explicit_unit

    # Source refs
    source_refs = []
    for sref in (ec.get("source_refs") or []):
        if isinstance(sref, dict):
            source_refs.append(dict(sref))
    if not source_refs and ec.get("source_doc"):
        source_refs.append({"source_doc": ec.get("source_doc")})

    return {
        "criterion_id": criterion_id,
        "stage": stage,
        "title": stage,
        "parent_stage": parent_stage,
        "parent_title": parent_stage,
        "hierarchy_level": hierarchy_level,
        "weight": raw_weight,
        "weight_value": val,
        "weight_unit": unit,
        "weight_basis": basis,
        "threshold": threshold,
        "notes": notes,
        "source_refs": source_refs,
    }


def deduplicate_evaluation_criteria(criteria_list: list[dict]) -> list[dict]:
    """
    Deterministically deduplicate criteria list while merging source_refs.
    - Full canonical key (normalized title + normalized parent + level).
    - Preserves first non-empty weights and notes.
    - Merges source references across occurrences.
    """
    seen = {}
    result = []
    
    for ec in criteria_list:
        if not isinstance(ec, dict):
            continue
        norm_ec = normalize_evaluation_criterion(ec)
        if not norm_ec.get("stage"):
            continue

        key = make_criterion_key(norm_ec)
        if key in seen:
            existing = seen[key]
            # Merge source refs
            existing_refs = existing.get("source_refs", [])
            existing_keys = {(r.get("source_doc"), r.get("page"), r.get("section")) for r in existing_refs if isinstance(r, dict)}
            for r in norm_ec.get("source_refs", []):
                if isinstance(r, dict):
                    rk = (r.get("source_doc"), r.get("page"), r.get("section"))
                    if rk not in existing_keys:
                        existing_refs.append(r)
                        existing_keys.add(rk)
            
            # Fill missing weight_value or notes if current has it
            if existing.get("weight_value") is None and norm_ec.get("weight_value") is not None:
                existing["weight_value"] = norm_ec["weight_value"]
                existing["weight_unit"] = norm_ec["weight_unit"]
                existing["weight_basis"] = norm_ec["weight_basis"]
                existing["weight"] = norm_ec["weight"]
            if not existing.get("notes") and norm_ec.get("notes"):
                existing["notes"] = norm_ec["notes"]
            if not existing.get("threshold") and norm_ec.get("threshold"):
                existing["threshold"] = norm_ec["threshold"]
        else:
            seen[key] = norm_ec
            result.append(norm_ec)
            
    return result


def build_evaluation_hierarchy(criteria_list: list[dict]) -> dict:
    """
    Builds a structured hierarchy tree from normalized/deduplicated criteria.
    Returns:
    {
      "roots": [
         {
            ...criterion fields...,
            "children": [
               { ...child fields... }
            ]
         }
      ],
      "unresolved": [ ...items whose parent could not be resolved or ambiguous... ]
    }
    """
    deduped = deduplicate_evaluation_criteria(criteria_list)
    
    # Index potential parents by normalized title
    by_norm_title = {}
    for item in deduped:
        norm_t = normalize_criterion_title(item["stage"])
        if norm_t:
            by_norm_title[norm_t] = item

    roots = []
    children_by_parent = {}
    unresolved = []

    for item in deduped:
        parent_name = item.get("parent_stage")
        if not parent_name or item.get("hierarchy_level") == 1:
            roots.append(item)
        else:
            norm_p = normalize_criterion_title(parent_name)
            if norm_p in by_norm_title:
                children_by_parent.setdefault(norm_p, []).append(item)
            else:
                # Parent specified but not found in criteria list
                # If ambiguous, place in unresolved
                item_copy = dict(item)
                item_copy["unresolved_reason"] = f"Parent '{parent_name}' not found"
                unresolved.append(item_copy)

    # Attach children to roots
    built_roots = []
    for r in roots:
        r_copy = dict(r)
        norm_r = normalize_criterion_title(r["stage"])
        r_children = children_by_parent.get(norm_r, [])
        r_copy["children"] = r_children
        built_roots.append(r_copy)

    return {
        "roots": built_roots,
        "unresolved": unresolved,
        "all_criteria": deduped,
    }


def calculate_evaluation_totals(hierarchy: dict) -> dict:
    """
    Calculates overall evaluation weight and checks consistency.
    CORE RULES:
    1. Overall total is computed ONLY from top-level (root) criteria that have an Overall weight basis.
    2. Child weights are NEVER added directly to root total.
    3. Duplicate/summary presentation (e.g. parent 40% with child 40%) counts 40% once.
    4. Mixed units (Percent vs Points) -> STATUS_MIXED_UNITS.
    5. Missing weights on essential roots -> STATUS_INSUFFICIENT_DATA.
    6. Unresolved parentage -> STATUS_UNRESOLVED_HIERARCHY.
    7. Overall != 100% (e.g. 110%) -> STATUS_SOURCE_DISCREPANCY (never silently normalized).
    8. Valid 100% -> STATUS_VALID.
    """
    roots = hierarchy.get("roots", [])
    unresolved = hierarchy.get("unresolved", [])
    all_criteria = hierarchy.get("all_criteria", [])

    if not all_criteria:
        return {
            "status": STATUS_INSUFFICIENT_DATA,
            "overall_total": 0.0,
            "overall_unit": UNIT_NONE,
            "root_details": [],
            "child_details": {},
            "warnings": ["No evaluation criteria present."],
        }

    warnings = []

    if unresolved:
        warnings.append(f"{len(unresolved)} criteria have unresolved hierarchy.")
        return {
            "status": STATUS_UNRESOLVED_HIERARCHY,
            "overall_total": None,
            "overall_unit": UNIT_NONE,
            "root_details": [],
            "child_details": {},
            "warnings": warnings,
        }

    # Analyze root weights
    root_units = set()
    root_total = 0.0
    has_missing_weight = False
    root_details = []
    child_details = {}

    for r in roots:
        val = r.get("weight_value")
        unit = r.get("weight_unit") or UNIT_NONE
        basis = r.get("weight_basis") or BASIS_OVERALL
        title = r.get("stage")
        children = r.get("children", [])

        # Check children consistency
        if children:
            c_vals = []
            c_units = set()
            c_bases = set()
            for c in children:
                cv = c.get("weight_value")
                cu = c.get("weight_unit") or UNIT_NONE
                cb = c.get("weight_basis") or BASIS_OVERALL
                if cv is not None:
                    c_vals.append(cv)
                c_units.add(cu)
                c_bases.add(cb)

            child_subtotal = sum(c_vals) if c_vals else None
            child_details[title] = {
                "count": len(children),
                "subtotal": child_subtotal,
                "units": list(c_units),
                "bases": list(c_bases),
            }

            # If parent has no weight, but children have overall weights, parent weight can be represented by children
            if val is None and child_subtotal is not None and all(b == BASIS_OVERALL for b in c_bases) and len(c_units) == 1:
                pass
            elif val is not None and child_subtotal is not None:
                # Consistency check between parent and children
                if BASIS_WITHIN_PARENT in c_bases:
                    if child_subtotal != 100.0:
                        warnings.append(f"Subcriteria for '{title}' total {child_subtotal}% within parent (expected 100%).")
                elif all(b == BASIS_OVERALL for b in c_bases):
                    if round(child_subtotal, 2) != round(val, 2):
                        warnings.append(f"Subcriteria for '{title}' sum to {child_subtotal}% overall, but parent states {val}%.")

        if val is None:
            # If parent has children whose sum provides the overall weight, treat that as the contribution
            c_info = child_details.get(title)
            if c_info and c_info["subtotal"] is not None and all(b == BASIS_OVERALL for b in c_info["bases"]):
                root_total += c_info["subtotal"]
                if c_info["units"]:
                    root_units.add(c_info["units"][0])
                root_details.append({
                    "stage": title,
                    "weight_value": c_info["subtotal"],
                    "weight_unit": c_info["units"][0] if c_info["units"] else UNIT_PERCENT,
                    "derived_from_children": True
                })
            else:
                has_missing_weight = True
                root_details.append({
                    "stage": title,
                    "weight_value": None,
                    "weight_unit": UNIT_NONE,
                    "derived_from_children": False
                })
        else:
            root_units.add(unit)
            root_total += val
            root_details.append({
                "stage": title,
                "weight_value": val,
                "weight_unit": unit,
                "derived_from_children": False
            })

    # Filter out UNIT_NONE from units if other units exist
    active_units = {u for u in root_units if u != UNIT_NONE}

    if len(active_units) > 1:
        warnings.append(f"Mixed weight units detected at root level: {sorted(active_units)}.")
        return {
            "status": STATUS_MIXED_UNITS,
            "overall_total": None,
            "overall_unit": "Mixed",
            "root_details": root_details,
            "child_details": child_details,
            "warnings": warnings,
        }

    overall_unit = list(active_units)[0] if active_units else UNIT_NONE

    if has_missing_weight and (not active_units or root_total < 100.0):
        warnings.append("One or more root criteria have unstated weights.")
        return {
            "status": STATUS_INSUFFICIENT_DATA,
            "overall_total": root_total if active_units else None,
            "overall_unit": overall_unit,
            "root_details": root_details,
            "child_details": child_details,
            "warnings": warnings,
        }

    # Check for source discrepancy (e.g. 110%)
    if overall_unit == UNIT_PERCENT and round(root_total, 2) != 100.0:
        warnings.append(f"Overall evaluation weighting totals {root_total:.1f}% (source discrepancy).")
        return {
            "status": STATUS_SOURCE_DISCREPANCY,
            "overall_total": root_total,
            "overall_unit": overall_unit,
            "root_details": root_details,
            "child_details": child_details,
            "warnings": warnings,
        }

    return {
        "status": STATUS_VALID,
        "overall_total": root_total,
        "overall_unit": overall_unit,
        "root_details": root_details,
        "child_details": child_details,
        "warnings": warnings,
    }


def format_evaluation_for_display(breakdown: list[dict]) -> tuple[list[dict], dict]:
    """
    Prepares an evaluation breakdown list for UI display.
    Builds hierarchy tree, calculates totals, and assigns indentation levels.
    Returns: (display_rows, totals_summary)
    """
    hierarchy = build_evaluation_hierarchy(breakdown)
    totals = calculate_evaluation_totals(hierarchy)
    
    display_rows = []
    
    for r in hierarchy.get("roots", []):
        r_copy = dict(r)
        r_copy["indent"] = 0
        r_copy["is_parent"] = bool(r.get("children"))
        display_rows.append(r_copy)
        
        for c in r.get("children", []):
            c_copy = dict(c)
            c_copy["indent"] = 1
            c_copy["is_parent"] = False
            display_rows.append(c_copy)
            
    for u in hierarchy.get("unresolved", []):
        u_copy = dict(u)
        u_copy["indent"] = 0
        u_copy["is_parent"] = False
        display_rows.append(u_copy)

    return display_rows, totals
