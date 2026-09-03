"""
evaluation_hierarchy.py

Focused, pure evaluation hierarchy model and deterministic calculations.
Handles:
- Controlled weight units (Percent, Points, Other, None)
- Controlled weight basis (Overall, Within Parent, Unknown)
- Controlled evaluation roles (Award Criterion, Subcriterion, Qualification / Gate,
  Scoring Scale, Process / Methodology, Structural Container, Unknown)
- Deterministic weight parsing (parse_evaluation_weight)
- Deterministic criterion identity and deduplication (material identity independent of weight observations)
- Weight observation and conflict tracking
- Structural parent containers
- Recursive hierarchy tree construction and validation
- Overall total calculation without parent-child double-counting
- Aggregation statuses (VALID, SOURCE_DISCREPANCY, UNRESOLVED_HIERARCHY, MIXED_UNITS, INSUFFICIENT_DATA)
- Status precedence: UNRESOLVED_HIERARCHY -> MIXED_UNITS -> SOURCE_DISCREPANCY -> INSUFFICIENT_DATA -> VALID
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

# Evaluation roles
ROLE_AWARD_CRITERION = "Award Criterion"
ROLE_SUBCRITERION = "Subcriterion"
ROLE_QUALIFICATION_GATE = "Qualification / Gate"
ROLE_SCORING_SCALE = "Scoring Scale"
ROLE_PROCESS_STAGE = "Process / Methodology"
ROLE_STRUCTURAL_CONTAINER = "Structural Container"
ROLE_UNKNOWN = "Unknown"

# Aggregation status (precedence: UNRESOLVED_HIERARCHY -> MIXED_UNITS -> SOURCE_DISCREPANCY -> INSUFFICIENT_DATA -> VALID)
STATUS_UNRESOLVED_HIERARCHY = "UNRESOLVED_HIERARCHY"
STATUS_MIXED_UNITS = "MIXED_UNITS"
STATUS_SOURCE_DISCREPANCY = "SOURCE_DISCREPANCY"
STATUS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
STATUS_VALID = "VALID"


def parse_evaluation_weight(raw_weight: Any) -> tuple[float | None, str, str]:
    """
    Deterministically parses a raw weight into (weight_value, weight_unit, weight_basis).
    
    Rules:
    - "40%" -> (40.0, "Percent", "Unknown")
    - "40 percent" -> (40.0, "Percent", "Unknown")
    - "25 points" / "25 pts" -> (25.0, "Points", "Unknown")
    - "50% within Technical" -> (50.0, "Percent", "Within Parent")
    - "40% of overall tender score" -> (40.0, "Percent", "Overall")
    - "40" / 40 / 10.0 -> (40.0, "Other", "Unknown") (bare numbers are NOT Percent)
    - "Pass/Fail" -> (None, "None", "Unknown")
    - "minimum 70% required" / threshold phrases -> (None, "None", "Unknown") (thresholds are not weights)
    - Empty/None -> (None, "None", "Unknown")
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

    # Detect explicit basis in raw string
    basis = BASIS_UNKNOWN
    if re.search(r"\b(?:within|of\s+(?:the\s+)?(?:parent|stage|technical|category|section))\b", lower) or "within parent" in lower:
        basis = BASIS_WITHIN_PARENT
    elif re.search(r"\b(?:overall|of\s+(?:the\s+)?(?:overall\s+)?tender\s+score|of\s+(?:the\s+)?total)\b", lower):
        basis = BASIS_OVERALL

    # Match numeric patterns
    # 1. Percentage (explicit % or percent)
    pct_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|percent(?:age)?\b)", raw_str, re.IGNORECASE)
    if pct_match:
        try:
            val = float(pct_match.group(1))
            return val, UNIT_PERCENT, basis
        except (ValueError, TypeError):
            pass

    # 2. Points (explicit points/pts/marks)
    pts_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:points?|pts?|marks?)\b", raw_str, re.IGNORECASE)
    if pts_match:
        try:
            val = float(pts_match.group(1))
            return val, UNIT_POINTS, basis
        except (ValueError, TypeError):
            pass

    # 3. Clean numeric alone (bare number without unit -> UNIT_OTHER, BASIS_UNKNOWN)
    num_alone_match = re.match(r"^(\d+(?:\.\d+)?)$", raw_str.strip())
    if num_alone_match:
        try:
            val = float(num_alone_match.group(1))
            return val, UNIT_OTHER, BASIS_UNKNOWN
        except (ValueError, TypeError):
            pass

    return None, UNIT_NONE, BASIS_UNKNOWN


def normalize_criterion_title(title: str) -> str:
    """Normalize criterion title for robust canonical identity."""
    if not title:
        return ""
    # Strip leading markers like "Stage 1 -", "1.1", bullet points
    t = re.sub(r"^(?:stage\s*\d+\s*[-:—]?|\d+(?:\.\d+)*\s*[-:—]?|[•\-*]\s*)", "", str(title).strip(), flags=re.IGNORECASE)
    # Normalize whitespace and lowercase
    t = re.sub(r"\s+", " ", t).strip()
    return t.lower()


def infer_evaluation_role(stage: str, parent_stage: str = None, level: int = 1, weight: Any = None) -> str:
    """Infers evaluation role conservatively from stage name, parent name, and weight."""
    s_lower = str(stage).lower() if stage else ""
    p_lower = str(parent_stage).lower() if parent_stage else ""

    if any(k in s_lower for k in ["scoring scale", "points scale", "marks scale"]) or "scoring" in p_lower:
        return ROLE_SCORING_SCALE
    if any(k in s_lower for k in ["conditions of participation", "mandatory requirements check", "qualification review", "selection questionnaire", "exclusion grounds", "eligibility"]):
        return ROLE_QUALIFICATION_GATE
    if any(k in s_lower for k in ["moderation", "winning tender selection", "process", "procedure", "submission check"]) or re.search(r"\bstage\s*\d+\b", s_lower):
        if not weight or str(weight).strip().lower() in ("none", "null", ""):
            return ROLE_PROCESS_STAGE
    if level > 1 or parent_stage:
        return ROLE_SUBCRITERION
    # Standard procurement award criteria topics even without weight stated
    if any(k in s_lower for k in ["technical", "commercial", "financial", "price", "pricing", "quality", "social value", "experience", "methodology", "scope"]):
        return ROLE_AWARD_CRITERION
    if weight and any(c in str(weight).lower() for c in ["%", "point", "pt", "mark"]):
        return ROLE_AWARD_CRITERION
    return ROLE_UNKNOWN


def make_criterion_key(ec: dict) -> tuple:
    """
    Material logical identity for evaluation criteria.
    INDEPENDENT of observed weight so differing weights for the same logical criterion
    are treated as observations/conflicts rather than duplicate criteria.
    Identity components:
    - explicit criterion_id (if distinct) or normalized title
    - normalized parent title
    - hierarchy level
    - evaluation role (if known)
    """
    cid = str(ec.get("criterion_id") or "").strip()
    title = ec.get("title") or ec.get("stage") or ec.get("criterion") or ""
    norm_title = normalize_criterion_title(str(title))

    parent_title = ec.get("parent_title") or ec.get("parent_stage") or ""
    norm_parent = normalize_criterion_title(str(parent_title))

    level = ec.get("hierarchy_level", 1 if not norm_parent else 2)
    role = ec.get("evaluation_role") or ROLE_UNKNOWN

    # If explicit unique criterion_id is provided, include it to preserve distinct candidate nodes
    return (cid if cid else norm_title, norm_parent, level, role)


def normalize_evaluation_criterion(ec: dict) -> dict:
    """
    Normalizes a single evaluation criterion into the canonical structured model.
    Preserves backward-compatible fields (stage, weight, threshold, notes).
    """
    if not isinstance(ec, dict):
        return {}

    stage = str(ec.get("stage") or ec.get("criterion") or ec.get("title") or "").strip()
    notes = str(ec.get("notes") or "").strip()
    threshold = ec.get("threshold")
    raw_weight = ec.get("weight") or ec.get("points")

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
    criterion_id = str(criterion_id).strip() if criterion_id else None

    parent_criterion_id = ec.get("parent_criterion_id")
    parent_criterion_id = str(parent_criterion_id).strip() if parent_criterion_id else None

    # Evaluation role
    role = ec.get("evaluation_role")
    if not role or role == ROLE_UNKNOWN:
        role = infer_evaluation_role(stage, parent_stage, hierarchy_level, raw_weight)

    # Weight parsing
    val, unit, basis = parse_evaluation_weight(raw_weight)

    # Allow explicit Stage A overrides for weight_basis
    explicit_basis = ec.get("weight_basis")
    if explicit_basis in (BASIS_OVERALL, BASIS_WITHIN_PARENT, BASIS_UNKNOWN):
        basis = explicit_basis
    elif explicit_basis and "within" in str(explicit_basis).lower():
        basis = BASIS_WITHIN_PARENT
    elif explicit_basis and "overall" in str(explicit_basis).lower():
        basis = BASIS_OVERALL
    elif basis == BASIS_UNKNOWN and hierarchy_level == 1 and not parent_stage and unit in (UNIT_PERCENT, UNIT_POINTS):
        # Top-level criterion with no parent naturally defaults to Overall evaluation allocation unless specified
        basis = BASIS_OVERALL

    # Allow explicit Stage A overrides for weight_unit
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

    # Weight observations
    weight_obs = []
    if raw_weight is not None or val is not None:
        weight_obs.append({
            "raw_weight": raw_weight,
            "value": val,
            "unit": unit,
            "basis": basis,
            "source_refs": list(source_refs),
        })

    is_structural = bool(ec.get("is_structural_container", False))

    return {
        "criterion_id": criterion_id,
        "parent_criterion_id": parent_criterion_id,
        "stage": stage,
        "title": stage,
        "parent_stage": parent_stage,
        "parent_title": parent_stage,
        "hierarchy_level": hierarchy_level,
        "evaluation_role": role,
        "is_structural_container": is_structural,
        "weight": raw_weight,
        "weight_value": val,
        "weight_unit": unit,
        "weight_basis": basis,
        "threshold": threshold,
        "notes": notes,
        "source_refs": source_refs,
        "weight_observations": weight_obs,
        "weight_conflict": False,
    }


def deduplicate_evaluation_criteria(criteria_list: list[dict]) -> list[dict]:
    """
    Deterministically deduplicate criteria list while merging source_refs and tracking weight observations.
    - Full canonical key (normalized title + normalized parent + level + role).
    - If same criterion has differing weights across documents/chunks:
      retains BOTH weight observations, marks weight_conflict = True,
      does not collapse to two criteria, does not choose silently.
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

            # Check weight observations
            new_obs = norm_ec.get("weight_observations", [])
            existing_obs = existing.setdefault("weight_observations", [])
            for nobs in new_obs:
                match_found = False
                for eobs in existing_obs:
                    if eobs.get("value") == nobs.get("value") and eobs.get("unit") == nobs.get("unit"):
                        match_found = True
                        break
                if not match_found:
                    existing_obs.append(nobs)
                    existing["weight_conflict"] = True

            # If existing had no weight and new has it, adopt primary representation
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
    Builds a recursive structured hierarchy tree from normalized/deduplicated criteria.
    Supports arbitrary nesting (Level 1 -> Level 2 -> Level 3...).
    Handles structural containers:
    When multiple criteria (>= 2) or a recognized container section declare the same non-empty
    parent_stage and no physical criterion row exists for that parent:
    creates a derived STRUCTURAL CONTAINER node.
    Isolated child criteria referencing an unknown parent remain unresolved (Test K).
    Returns:
    {
      "roots": [
         {
            ...criterion fields...,
            "children": [
               { ...child fields..., "children": [...] }
            ]
         }
      ],
      "unresolved": [ ...items whose parent could not be resolved or ambiguous... ],
      "all_criteria": [ ...all deduped items including structural containers... ]
    }
    """
    deduped = deduplicate_evaluation_criteria(criteria_list)

    # Index criteria by explicit ID and by normalized title
    by_id = {}
    by_norm_title = {}
    for item in deduped:
        cid = item.get("criterion_id")
        if cid:
            by_id[cid] = item
        nt = normalize_criterion_title(item.get("stage") or item.get("title") or "")
        if nt:
            by_norm_title.setdefault(nt, []).append(item)

    # Identify declared parent_stage references that do not exist as physical rows
    missing_parents = {}
    for item in deduped:
        pid = item.get("parent_criterion_id")
        pname = item.get("parent_stage") or item.get("parent_title")
        if pid and pid in by_id:
            continue
        if pname:
            norm_p = normalize_criterion_title(pname)
            if norm_p and norm_p not in by_norm_title:
                missing_parents.setdefault(norm_p, {"orig_name": pname, "children": []})["children"].append(item)

    # Create structural containers for missing parents only when established by multiple children (>=2)
    # or explicit structural container intent, avoiding false synthesis for orphan single criteria (Test K)
    structural_nodes = []
    for norm_p, info in missing_parents.items():
        orig_name = info["orig_name"]
        children = info["children"]
        if len(children) < 2 and not any(k in orig_name.lower() for k in ["award", "criteria", "model", "participation"]):
            # Isolated child with unverified single parent remains unresolved
            continue

        # Aggregate source refs from children
        container_refs = []
        seen_refs = set()
        for ch in children:
            for ref in ch.get("source_refs", []):
                if isinstance(ref, dict):
                    rk = (ref.get("source_doc"), ref.get("page"), ref.get("section"))
                    if rk not in seen_refs:
                        container_refs.append(dict(ref))
                        seen_refs.add(rk)

        # Infer container role
        c_lower = orig_name.lower()
        if "award" in c_lower:
            c_role = ROLE_STRUCTURAL_CONTAINER
        elif "scoring" in c_lower:
            c_role = ROLE_SCORING_SCALE
        elif "participation" in c_lower or "qualification" in c_lower or "eligibility" in c_lower:
            c_role = ROLE_QUALIFICATION_GATE
        else:
            c_role = ROLE_STRUCTURAL_CONTAINER

        synth_container = {
            "criterion_id": f"struct_{norm_p.replace(' ', '_')}",
            "parent_criterion_id": None,
            "stage": orig_name,
            "title": orig_name,
            "parent_stage": None,
            "parent_title": None,
            "hierarchy_level": 1,
            "evaluation_role": c_role,
            "is_structural_container": True,
            "weight": None,
            "weight_value": None,
            "weight_unit": UNIT_NONE,
            "weight_basis": BASIS_UNKNOWN,
            "threshold": None,
            "notes": "Structural evaluation container",
            "source_refs": container_refs,
            "weight_observations": [],
            "weight_conflict": False,
        }
        structural_nodes.append(synth_container)
        by_norm_title[norm_p] = [synth_container]
        if synth_container["criterion_id"]:
            by_id[synth_container["criterion_id"]] = synth_container

    all_items = deduped + structural_nodes

    # Attach children to parents recursively
    parent_map = {}  # id(parent) -> list of child dicts
    unresolved = []
    root_items = []

    for item in all_items:
        # Check if item is a root
        pid = item.get("parent_criterion_id")
        pname = item.get("parent_stage") or item.get("parent_title")

        if not pid and not pname:
            root_items.append(item)
            continue

        if item.get("hierarchy_level", 1) == 1 and not pid and not pname:
            root_items.append(item)
            continue

        # Resolve parent
        parent = None
        if pid and pid in by_id:
            parent = by_id[pid]
        elif pname:
            norm_p = normalize_criterion_title(pname)
            candidates = by_norm_title.get(norm_p, [])
            if len(candidates) == 1:
                parent = candidates[0]
            elif len(candidates) > 1:
                # Ambiguous between multiple candidates
                item_copy = dict(item)
                item_copy["unresolved_reason"] = f"Ambiguous parent '{pname}': multiple candidate parents match."
                unresolved.append(item_copy)
                continue
            else:
                item_copy = dict(item)
                item_copy["unresolved_reason"] = f"Parent '{pname}' not found."
                unresolved.append(item_copy)
                continue

        if parent:
            parent_map.setdefault(id(parent), []).append(item)
        else:
            item_copy = dict(item)
            item_copy["unresolved_reason"] = f"Parent not resolved."
            unresolved.append(item_copy)

    # Recursive function to build tree
    def build_node(item_dict: dict) -> dict:
        node = dict(item_dict)
        ch_list = parent_map.get(id(item_dict), [])
        node["children"] = [build_node(ch) for ch in ch_list]
        return node

    built_roots = [build_node(r) for r in root_items]

    return {
        "roots": built_roots,
        "unresolved": unresolved,
        "all_criteria": all_items,
    }


def calculate_evaluation_totals(hierarchy: dict) -> dict:
    """
    Calculates overall evaluation weight and checks consistency with strict status precedence:
    UNRESOLVED_HIERARCHY -> MIXED_UNITS -> SOURCE_DISCREPANCY -> INSUFFICIENT_DATA -> VALID.
    
    CORE RULES:
    1. Overall total is computed ONLY from criteria that have weight_basis == Overall.
    2. Unknown basis, Within Parent basis, Structural Containers, Scoring Scales,
       and Process/Eligibility stages are NEVER additive directly to overall total.
    3. Structural container with child subtotal: if container has no direct weight, but
       all its children have basis == Overall and unit == Percent, the children's subtotal
       provides the container's authoritative overall contribution.
    4. Duplicate/summary presentation (e.g. parent 40% with child 40%) counts 40% once.
    5. Confirmed child/parent mismatch (e.g. parent 60% with children 70% overall, or
       within-parent children totaling 110%) is a SOURCE_DISCREPANCY.
    6. Weight conflicts on the same logical criterion (e.g. 70 pts vs 60 pts) -> SOURCE_DISCREPANCY.
    7. Overall != 100.0% (e.g. 110.0%) -> SOURCE_DISCREPANCY.
    8. Missing weight on an actual Award Criterion -> INSUFFICIENT_DATA.
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

    # Priority 1: UNRESOLVED_HIERARCHY
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

    # Priority 2 & 3: Check for weight conflicts and calculate contributions
    has_weight_conflict = False
    for c in all_criteria:
        if c.get("weight_conflict"):
            has_weight_conflict = True
            obs = c.get("weight_observations", [])
            obs_str = ", ".join(str(o.get('raw_weight')) for o in obs)
            warnings.append(f"Weight conflict on criterion '{c.get('stage')}': observed conflicting weights [{obs_str}].")

    root_units = set()
    root_total = 0.0
    has_missing_award_weight = False
    has_source_discrepancy = False
    root_details = []
    child_details = {}

    for r in roots:
        val = r.get("weight_value")
        unit = r.get("weight_unit") or UNIT_NONE
        basis = r.get("weight_basis") or BASIS_UNKNOWN
        role = r.get("evaluation_role") or ROLE_UNKNOWN
        is_container = bool(r.get("is_structural_container"))
        title = r.get("stage")
        children = r.get("children", [])

        # Process children recursively/shallowly for consistency
        child_subtotal = None
        c_units = set()
        c_bases = set()
        if children:
            c_vals = []
            for c in children:
                cv = c.get("weight_value")
                cu = c.get("weight_unit") or UNIT_NONE
                cb = c.get("weight_basis") or BASIS_UNKNOWN
                crole = c.get("evaluation_role")
                if cv is not None:
                    c_vals.append(cv)
                if cu != UNIT_NONE:
                    c_units.add(cu)
                c_bases.add(cb)
                # Check missing weight on child award criteria
                if cv is None and crole == ROLE_AWARD_CRITERION:
                    has_missing_award_weight = True

            child_subtotal = sum(c_vals) if c_vals else None
            child_details[title] = {
                "count": len(children),
                "subtotal": child_subtotal,
                "units": list(c_units),
                "bases": list(c_bases),
            }

            # Child/Parent consistency check
            if val is not None and child_subtotal is not None:
                if BASIS_WITHIN_PARENT in c_bases:
                    if round(child_subtotal, 2) != 100.0:
                        has_source_discrepancy = True
                        warnings.append(f"Subcriteria for '{title}' total {child_subtotal}% within parent (expected 100%).")
                elif all(b == BASIS_OVERALL for b in c_bases):
                    if round(child_subtotal, 2) != round(val, 2):
                        has_source_discrepancy = True
                        warnings.append(f"Subcriteria for '{title}' sum to {child_subtotal}% overall, but parent states {val}%. correlation discrepancy.")

        # Determine if root contributes to overall total
        contributing_value = None
        contributing_unit = None

        if is_container:
            # Container itself has no direct weight. If children have overall percentages, container contributes their sum.
            if child_subtotal is not None and all(b == BASIS_OVERALL for b in c_bases) and len(c_units) == 1:
                contributing_value = child_subtotal
                contributing_unit = list(c_units)[0]
                root_details.append({
                    "stage": title,
                    "weight_value": contributing_value,
                    "weight_unit": contributing_unit,
                    "derived_from_children": True,
                    "evaluation_role": role,
                })
            else:
                root_details.append({
                    "stage": title,
                    "weight_value": None,
                    "weight_unit": UNIT_NONE,
                    "derived_from_children": False,
                    "evaluation_role": role,
                })
        elif basis == BASIS_OVERALL and val is not None:
            contributing_value = val
            contributing_unit = unit
            root_details.append({
                "stage": title,
                "weight_value": val,
                "weight_unit": unit,
                "derived_from_children": False,
                "evaluation_role": role,
            })
        elif val is None and child_subtotal is not None and all(b == BASIS_OVERALL for b in c_bases) and len(c_units) == 1:
            contributing_value = child_subtotal
            contributing_unit = list(c_units)[0]
            root_details.append({
                "stage": title,
                "weight_value": contributing_value,
                "weight_unit": contributing_unit,
                "derived_from_children": True,
                "evaluation_role": role,
            })
        else:
            # Root without Overall basis (e.g. Unknown, Within Parent, Process Stage, Qualification Gate)
            if val is None and role in (ROLE_AWARD_CRITERION, ROLE_UNKNOWN):
                has_missing_award_weight = True
            root_details.append({
                "stage": title,
                "weight_value": val,
                "weight_unit": unit,
                "derived_from_children": False,
                "evaluation_role": role,
            })

        if contributing_value is not None and contributing_unit is not None:
            root_units.add(contributing_unit)
            root_total += contributing_value

    # Filter out UNIT_NONE from units if other units exist
    active_units = {u for u in root_units if u != UNIT_NONE}

    # Priority 2: MIXED_UNITS
    if len(active_units) > 1:
        warnings.append(f"Mixed weight units detected at overall contribution level: {sorted(active_units)}.")
        return {
            "status": STATUS_MIXED_UNITS,
            "overall_total": None,
            "overall_unit": "Mixed",
            "root_details": root_details,
            "child_details": child_details,
            "warnings": warnings,
        }

    overall_unit = list(active_units)[0] if active_units else UNIT_NONE

    # Priority 3: SOURCE_DISCREPANCY (from weight conflict, child/parent mismatch, or total != 100%)
    if has_weight_conflict:
        return {
            "status": STATUS_SOURCE_DISCREPANCY,
            "overall_total": root_total if active_units else None,
            "overall_unit": overall_unit,
            "root_details": root_details,
            "child_details": child_details,
            "warnings": warnings,
        }

    if has_source_discrepancy:
        return {
            "status": STATUS_SOURCE_DISCREPANCY,
            "overall_total": root_total if active_units else None,
            "overall_unit": overall_unit,
            "root_details": root_details,
            "child_details": child_details,
            "warnings": warnings,
        }

    # Priority 3: INSUFFICIENT_DATA (missing weight on actual Award Criterion or unstated essential weights)
    if has_missing_award_weight:
        warnings.append("One or more award criteria have unstated weights.")
        return {
            "status": STATUS_INSUFFICIENT_DATA,
            "overall_total": root_total if active_units else None,
            "overall_unit": overall_unit,
            "root_details": root_details,
            "child_details": child_details,
            "warnings": warnings,
        }

    if not active_units:
        warnings.append("No overall quantitative evaluation weights found.")
        return {
            "status": STATUS_INSUFFICIENT_DATA,
            "overall_total": None,
            "overall_unit": UNIT_NONE,
            "root_details": root_details,
            "child_details": child_details,
            "warnings": warnings,
        }

    # Priority 4: SOURCE_DISCREPANCY (overall total != 100% when active units present)
    if overall_unit == UNIT_PERCENT and round(root_total, 2) != 100.0 and active_units:
        warnings.append(f"Overall evaluation weighting totals {root_total:.1f}% (source discrepancy).")
        return {
            "status": STATUS_SOURCE_DISCREPANCY,
            "overall_total": root_total,
            "overall_unit": overall_unit,
            "root_details": root_details,
            "child_details": child_details,
            "warnings": warnings,
        }

    # Priority 5: VALID
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
    Prepares an evaluation breakdown list for UI display recursively.
    Returns: (display_rows, totals_summary)
    """
    hierarchy = build_evaluation_hierarchy(breakdown)
    totals = calculate_evaluation_totals(hierarchy)

    display_rows = []

    def flatten_node(node: dict, indent: int):
        n_copy = dict(node)
        ch_list = n_copy.get("children", [])
        n_copy["indent"] = indent
        n_copy["is_parent"] = bool(ch_list)
        display_rows.append(n_copy)
        for ch in ch_list:
            flatten_node(ch, indent + 1)

    for r in hierarchy.get("roots", []):
        flatten_node(r, 0)

    for u in hierarchy.get("unresolved", []):
        u_copy = dict(u)
        u_copy["indent"] = 0
        u_copy["is_parent"] = False
        display_rows.append(u_copy)

    return display_rows, totals
