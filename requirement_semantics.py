"""
requirement_semantics.py

Orthogonal requirement semantics and supplier-qualification helper module.
Defines:
- Controlled requirement_type taxonomy (orthogonal to category).
- Normalization and fallback classification.
- Supplier qualification gate filtering and matching logic.
"""
import re
from typing import Any

# Controlled taxonomy enum values
TYPE_SUPPLIER_QUALIFICATION = "Supplier Qualification"
TYPE_TECHNICAL_SPECIFICATION = "Technical Specification"
TYPE_SUBMISSION_COMPLIANCE = "Submission Compliance"
TYPE_DELIVERY_SLA = "Delivery / SLA"
TYPE_COMMERCIAL_CONTRACTUAL = "Commercial / Contractual"
TYPE_EVALUATION_SCORED = "Evaluation / Scored"
TYPE_GENERAL_COMPLIANCE = "General Compliance"

ALLOWED_REQUIREMENT_TYPES = (
    TYPE_SUPPLIER_QUALIFICATION,
    TYPE_TECHNICAL_SPECIFICATION,
    TYPE_SUBMISSION_COMPLIANCE,
    TYPE_DELIVERY_SLA,
    TYPE_COMMERCIAL_CONTRACTUAL,
    TYPE_EVALUATION_SCORED,
    TYPE_GENERAL_COMPLIANCE,
)

_NORMALIZED_TYPE_MAP = {
    # Direct and canonical variants
    "supplier qualification": TYPE_SUPPLIER_QUALIFICATION,
    "supplier_qualification": TYPE_SUPPLIER_QUALIFICATION,
    "supplierqualification": TYPE_SUPPLIER_QUALIFICATION,
    "qualification": TYPE_SUPPLIER_QUALIFICATION,
    "eligibility": TYPE_SUPPLIER_QUALIFICATION,
    "bidder qualification": TYPE_SUPPLIER_QUALIFICATION,
    "bidder_qualification": TYPE_SUPPLIER_QUALIFICATION,

    "technical specification": TYPE_TECHNICAL_SPECIFICATION,
    "technical_specification": TYPE_TECHNICAL_SPECIFICATION,
    "technicalspecification": TYPE_TECHNICAL_SPECIFICATION,
    "technical": TYPE_TECHNICAL_SPECIFICATION,
    "specification": TYPE_TECHNICAL_SPECIFICATION,

    "submission compliance": TYPE_SUBMISSION_COMPLIANCE,
    "submission_compliance": TYPE_SUBMISSION_COMPLIANCE,
    "submissioncompliance": TYPE_SUBMISSION_COMPLIANCE,
    "submission": TYPE_SUBMISSION_COMPLIANCE,

    "delivery / sla": TYPE_DELIVERY_SLA,
    "delivery/sla": TYPE_DELIVERY_SLA,
    "delivery": TYPE_DELIVERY_SLA,
    "sla": TYPE_DELIVERY_SLA,
    "service level": TYPE_DELIVERY_SLA,

    "commercial / contractual": TYPE_COMMERCIAL_CONTRACTUAL,
    "commercial/contractual": TYPE_COMMERCIAL_CONTRACTUAL,
    "commercial": TYPE_COMMERCIAL_CONTRACTUAL,
    "contractual": TYPE_COMMERCIAL_CONTRACTUAL,
    "contract": TYPE_COMMERCIAL_CONTRACTUAL,

    "evaluation / scored": TYPE_EVALUATION_SCORED,
    "evaluation/scored": TYPE_EVALUATION_SCORED,
    "evaluation": TYPE_EVALUATION_SCORED,
    "scored": TYPE_EVALUATION_SCORED,
    "rated": TYPE_EVALUATION_SCORED,

    "general compliance": TYPE_GENERAL_COMPLIANCE,
    "general_compliance": TYPE_GENERAL_COMPLIANCE,
    "generalcompliance": TYPE_GENERAL_COMPLIANCE,
    "general": TYPE_GENERAL_COMPLIANCE,
    "compliance": TYPE_GENERAL_COMPLIANCE,
}

# Strong supplier qualification / bidder eligibility cues for fallback detection
# NOTE: Generic modal words ("must", "shall", "mandatory", "required") are strictly EXCLUDED.
_STRONG_QUALIFICATION_CUES = [
    r"\bcondition[s]?\s+of\s+participation\b",
    r"\bminimum\s+qualification[s]?\b",
    r"\bsupplier\s+eligibility\b",
    r"\bbidder\s+eligibility\b",
    r"\bproponent\s+eligibility\b",
    r"\btenderer\s+eligibility\b",
    r"\bfinancial\s+standing\b",
    r"\bsupplier\s+questionnaire\s+qualification\b",
    r"\blegal\s+capacity\s+to\s+participate\b",
    r"\boem\s+authorization\b",
    r"\bmanufacturer['’]?s?\s+authorization\b",
    r"\bauthorized\s+partner\b",
    r"\bauthorized\s+reseller\b",
    r"\bsecurity\s+clearance\s+threshold\b",
]

_QUAL_CUES_RE = re.compile("|".join(_STRONG_QUALIFICATION_CUES), re.IGNORECASE)


def normalize_requirement_identity_text(text: Any) -> str:
    """
    Produce a canonical normalized text key for reliable cross-stage and UI matching.
    Removes all non-alphanumeric characters and lowercases.
    """
    if not isinstance(text, str):
        return ""
    return re.sub(r'\W+', '', text.lower())


def normalize_requirement_type(raw_type: Any) -> str | None:
    """
    Normalize raw requirement_type string to one of the canonical ALLOWED_REQUIREMENT_TYPES,
    or None if unrecognized / empty.
    """
    if not isinstance(raw_type, str):
        return None
    cleaned = raw_type.strip().lower()
    if not cleaned:
        return None
    # Direct map lookup
    if cleaned in _NORMALIZED_TYPE_MAP:
        return _NORMALIZED_TYPE_MAP[cleaned]
    # Check if any canonical name is contained
    for k, v in _NORMALIZED_TYPE_MAP.items():
        if k in cleaned:
            return v
    return None


def resolve_requirement_type(requirement: dict) -> str:
    """
    Deterministically resolve requirement_type for a requirement record.
    - If requirement_type is present and valid, normalizes and returns it.
    - If rated/scored category and unclassified or general, returns Evaluation / Scored.
    - If missing or unclassified: applies conservative deterministic fallback.
      * Only strong, explicit qualification/eligibility cues resolve to Supplier Qualification.
      * Category == 'Mandatory' alone NEVER defaults to Supplier Qualification.
      * Otherwise defaults to General Compliance.
    """
    if not isinstance(requirement, dict):
        return TYPE_GENERAL_COMPLIANCE

    # Check explicit requirement_type
    raw_type = requirement.get("requirement_type")
    norm_type = normalize_requirement_type(raw_type)
    if norm_type:
        return norm_type

    category = (requirement.get("category") or "").strip().lower()
    desc = requirement.get("description") or ""
    rfso = requirement.get("rfso_ref") or ""
    text_to_check = f"{desc} {rfso}".strip()

    # If rated/scored category
    if category in ("rated", "evaluation"):
        return TYPE_EVALUATION_SCORED

    # Conservative deterministic fallback: check for strong qualification cues
    if _QUAL_CUES_RE.search(text_to_check):
        return TYPE_SUPPLIER_QUALIFICATION

    # Check submission compliance cues in text
    if re.search(r"\b(?:signed\s+form|submission\s+form|submission\s+checklist|tender\s+declaration|appendix\s+\d+\s+form)\b", text_to_check, re.IGNORECASE):
        return TYPE_SUBMISSION_COMPLIANCE

    # Check delivery/sla cues in text
    if re.search(r"\b(?:service\s+level\s+agreement|sla|response\s+time|incident\s+resolution|uptime\s+guarantee|hours\s+of\s+operation)\b", text_to_check, re.IGNORECASE):
        return TYPE_DELIVERY_SLA

    # Check commercial/contractual cues in text
    if re.search(r"\b(?:limitation\s+of\s+liability|indemnification|intellectual\s+property\s+rights|payment\s+terms|invoicing\s+schedule)\b", text_to_check, re.IGNORECASE):
        return TYPE_COMMERCIAL_CONTRACTUAL

    # Check technical specification cues
    if re.search(r"\b(?:technical\s+specification|functional\s+requirement|hardware\s+specification|system\s+architecture|api\s+integration)\b", text_to_check, re.IGNORECASE):
        return TYPE_TECHNICAL_SPECIFICATION

    # Safe default: General Compliance (NEVER defaults to Supplier Qualification merely because Mandatory)
    return TYPE_GENERAL_COMPLIANCE


def is_supplier_qualification(requirement: dict) -> bool:
    """
    Returns True ONLY if requirement is pass/fail Mandatory AND resolves to Supplier Qualification.
    Rated criteria cannot be qualification gates even if type is Supplier Qualification.
    """
    if not isinstance(requirement, dict):
        return False
    cat = (requirement.get("category") or "").strip().lower()
    if cat != "mandatory":
        return False
    return resolve_requirement_type(requirement) == TYPE_SUPPLIER_QUALIFICATION


def select_qualification_requirements(requirements: list[dict], qualification_gates: list[dict]) -> list[dict]:
    """
    Match authoritative qualification_gates from the Bid Brief back to persisted requirements.
    - Uses full normalized description identity as the primary anchor.
    - Matches are constrained to requirements where category == 'Mandatory'.
    - If qualification_gates is empty: returns empty list []. (Never falls back to all Mandatory!)
    - If multiple requirements share the same req_id, only the requirement matching the gate description is selected.
    """
    if not requirements or not qualification_gates:
        return []

    # Build lookup table of mandatory requirements by normalized description
    desc_lookup: dict[str, dict] = {}
    for r in requirements:
        if not isinstance(r, dict):
            continue
        if (r.get("category") or "").strip().lower() != "mandatory":
            continue
        norm_desc = normalize_requirement_identity_text(r.get("description"))
        if norm_desc:
            desc_lookup[norm_desc] = r

    matched: list[dict] = []
    seen_ids: set = set()

    for g in qualification_gates:
        if not isinstance(g, dict):
            continue
        gate_text = g.get("requirement") or g.get("description") or ""
        norm_gate = normalize_requirement_identity_text(gate_text)
        if not norm_gate:
            continue

        target_req = desc_lookup.get(norm_gate)
        if not target_req:
            # Try matching gate text against normalized requirement description substring or vice versa
            for nd, r in desc_lookup.items():
                if len(nd) > 20 and len(norm_gate) > 20 and (nd in norm_gate or norm_gate in nd):
                    target_req = r
                    break

        if target_req:
            req_pk = target_req.get("id") or target_req.get("req_id") or id(target_req)
            if req_pk not in seen_ids:
                seen_ids.add(req_pk)
                matched.append(target_req)

    return matched
