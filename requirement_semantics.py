"""
requirement_semantics.py

Orthogonal requirement semantics and supplier-qualification helper module.
Defines:
- Controlled requirement_type taxonomy (orthogonal to category).
- Normalization and fallback classification.
- Conflict-safe, order-independent semantic type merging.
- Supplier qualification gate filtering and matching logic.
"""
import re
from typing import Any
from collections.abc import Iterable

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

# Specific (non-general) types for conflict-safe merging
SPECIFIC_REQUIREMENT_TYPES = {
    TYPE_SUPPLIER_QUALIFICATION,
    TYPE_TECHNICAL_SPECIFICATION,
    TYPE_SUBMISSION_COMPLIANCE,
    TYPE_DELIVERY_SLA,
    TYPE_COMMERCIAL_CONTRACTUAL,
    TYPE_EVALUATION_SCORED,
}

# Explicit exact aliases mapping to canonical enum values after safe whitespace/separator normalization.
# NOTE: Arbitrary substring matching is strictly prohibited.
# Ambiguous compounds (e.g. "Technical Qualification", "Commercial Qualification",
# "Submission Qualification", "Qualification / Technical") are strictly omitted and return None.
_EXACT_ALIAS_MAP = {
    # Supplier Qualification
    "supplier qualification": TYPE_SUPPLIER_QUALIFICATION,
    "supplier_qualification": TYPE_SUPPLIER_QUALIFICATION,
    "supplierqualification": TYPE_SUPPLIER_QUALIFICATION,
    "bidder qualification": TYPE_SUPPLIER_QUALIFICATION,
    "bidder_qualification": TYPE_SUPPLIER_QUALIFICATION,
    "bidderqualification": TYPE_SUPPLIER_QUALIFICATION,
    "proponent qualification": TYPE_SUPPLIER_QUALIFICATION,
    "proponent_qualification": TYPE_SUPPLIER_QUALIFICATION,
    "qualification gate": TYPE_SUPPLIER_QUALIFICATION,
    "qualification_gate": TYPE_SUPPLIER_QUALIFICATION,
    "eligibility gate": TYPE_SUPPLIER_QUALIFICATION,
    "eligibility_gate": TYPE_SUPPLIER_QUALIFICATION,
    "supplier eligibility": TYPE_SUPPLIER_QUALIFICATION,
    "supplier_eligibility": TYPE_SUPPLIER_QUALIFICATION,
    "bidder eligibility": TYPE_SUPPLIER_QUALIFICATION,
    "bidder_eligibility": TYPE_SUPPLIER_QUALIFICATION,

    # Technical Specification
    "technical specification": TYPE_TECHNICAL_SPECIFICATION,
    "technical_specification": TYPE_TECHNICAL_SPECIFICATION,
    "technicalspecification": TYPE_TECHNICAL_SPECIFICATION,
    "technical specifications": TYPE_TECHNICAL_SPECIFICATION,
    "technical_specifications": TYPE_TECHNICAL_SPECIFICATION,
    "technical requirement": TYPE_TECHNICAL_SPECIFICATION,
    "technical_requirement": TYPE_TECHNICAL_SPECIFICATION,
    "technical requirements": TYPE_TECHNICAL_SPECIFICATION,
    "technical_requirements": TYPE_TECHNICAL_SPECIFICATION,
    "technical spec": TYPE_TECHNICAL_SPECIFICATION,
    "technical_spec": TYPE_TECHNICAL_SPECIFICATION,

    # Submission Compliance
    "submission compliance": TYPE_SUBMISSION_COMPLIANCE,
    "submission_compliance": TYPE_SUBMISSION_COMPLIANCE,
    "submissioncompliance": TYPE_SUBMISSION_COMPLIANCE,
    "submission requirement": TYPE_SUBMISSION_COMPLIANCE,
    "submission_requirement": TYPE_SUBMISSION_COMPLIANCE,
    "submission requirements": TYPE_SUBMISSION_COMPLIANCE,
    "submission_requirements": TYPE_SUBMISSION_COMPLIANCE,
    "submission instruction": TYPE_SUBMISSION_COMPLIANCE,
    "submission_instruction": TYPE_SUBMISSION_COMPLIANCE,
    "submission instructions": TYPE_SUBMISSION_COMPLIANCE,
    "submission_instructions": TYPE_SUBMISSION_COMPLIANCE,
    "bidding instruction": TYPE_SUBMISSION_COMPLIANCE,
    "bidding instructions": TYPE_SUBMISSION_COMPLIANCE,

    # Delivery / SLA
    "delivery / sla": TYPE_DELIVERY_SLA,
    "delivery/sla": TYPE_DELIVERY_SLA,
    "delivery _ sla": TYPE_DELIVERY_SLA,
    "delivery_sla": TYPE_DELIVERY_SLA,
    "delivery and sla": TYPE_DELIVERY_SLA,
    "service level agreement": TYPE_DELIVERY_SLA,
    "service_level_agreement": TYPE_DELIVERY_SLA,
    "service level": TYPE_DELIVERY_SLA,
    "service_level": TYPE_DELIVERY_SLA,
    "delivery obligation": TYPE_DELIVERY_SLA,
    "delivery_obligation": TYPE_DELIVERY_SLA,
    "delivery obligations": TYPE_DELIVERY_SLA,
    "delivery_obligations": TYPE_DELIVERY_SLA,
    "sla requirement": TYPE_DELIVERY_SLA,
    "sla_requirement": TYPE_DELIVERY_SLA,
    "sla requirements": TYPE_DELIVERY_SLA,
    "sla_requirements": TYPE_DELIVERY_SLA,

    # Commercial / Contractual
    "commercial / contractual": TYPE_COMMERCIAL_CONTRACTUAL,
    "commercial/contractual": TYPE_COMMERCIAL_CONTRACTUAL,
    "commercial _ contractual": TYPE_COMMERCIAL_CONTRACTUAL,
    "commercial_contractual": TYPE_COMMERCIAL_CONTRACTUAL,
    "commercial and contractual": TYPE_COMMERCIAL_CONTRACTUAL,
    "commercial requirement": TYPE_COMMERCIAL_CONTRACTUAL,
    "commercial_requirement": TYPE_COMMERCIAL_CONTRACTUAL,
    "commercial requirements": TYPE_COMMERCIAL_CONTRACTUAL,
    "commercial_requirements": TYPE_COMMERCIAL_CONTRACTUAL,
    "contractual requirement": TYPE_COMMERCIAL_CONTRACTUAL,
    "contractual_requirement": TYPE_COMMERCIAL_CONTRACTUAL,
    "contractual requirements": TYPE_COMMERCIAL_CONTRACTUAL,
    "contractual_requirements": TYPE_COMMERCIAL_CONTRACTUAL,
    "commercial term": TYPE_COMMERCIAL_CONTRACTUAL,
    "commercial terms": TYPE_COMMERCIAL_CONTRACTUAL,
    "contract term": TYPE_COMMERCIAL_CONTRACTUAL,
    "contract terms": TYPE_COMMERCIAL_CONTRACTUAL,

    # Evaluation / Scored
    "evaluation / scored": TYPE_EVALUATION_SCORED,
    "evaluation/scored": TYPE_EVALUATION_SCORED,
    "evaluation _ scored": TYPE_EVALUATION_SCORED,
    "evaluation_scored": TYPE_EVALUATION_SCORED,
    "evaluation and scored": TYPE_EVALUATION_SCORED,
    "scored evaluation": TYPE_EVALUATION_SCORED,
    "scored_evaluation": TYPE_EVALUATION_SCORED,
    "evaluation criteria": TYPE_EVALUATION_SCORED,
    "evaluation_criteria": TYPE_EVALUATION_SCORED,
    "evaluation criterion": TYPE_EVALUATION_SCORED,
    "evaluation_criterion": TYPE_EVALUATION_SCORED,
    "rated criterion": TYPE_EVALUATION_SCORED,
    "rated_criterion": TYPE_EVALUATION_SCORED,
    "rated criteria": TYPE_EVALUATION_SCORED,
    "rated_criteria": TYPE_EVALUATION_SCORED,
    "scored criterion": TYPE_EVALUATION_SCORED,
    "scored criteria": TYPE_EVALUATION_SCORED,

    # General Compliance
    "general compliance": TYPE_GENERAL_COMPLIANCE,
    "general_compliance": TYPE_GENERAL_COMPLIANCE,
    "generalcompliance": TYPE_GENERAL_COMPLIANCE,
    "general requirement": TYPE_GENERAL_COMPLIANCE,
    "general requirements": TYPE_GENERAL_COMPLIANCE,
    "mandatory compliance": TYPE_GENERAL_COMPLIANCE,
    "compliance requirement": TYPE_GENERAL_COMPLIANCE,
    "compliance requirements": TYPE_GENERAL_COMPLIANCE,
}

# Canonical lowercase map for exact canonical matching
_CANONICAL_LOWER_MAP = {t.lower(): t for t in ALLOWED_REQUIREMENT_TYPES}

# Strong supplier qualification / bidder eligibility cues for fallback detection and hard-gate safety barrier.
# NOTE: Generic modal words ("must", "shall", "mandatory", "required"), standalone disclosure words
# (bidding model, consortium, guarantor, demonstrable experience) and solution/product specs are strictly EXCLUDED.
_STRONG_QUALIFICATION_CUES = [
    r"\bcondition[s]?\s+of\s+participation\b",
    r"\b(?:minimum\s+)?qualification[s]?\s+(?:criteria|requirements?|standards?)\b",
    r"\bminimum\s+qualification[s]?\b",
    r"\b(?:bidder|supplier|vendor|participant|proponent|tenderer)s?\s+(?:eligibility|qualification[s]?)\b",
    r"\b(?:bidder|supplier|vendor|participant|proponent|tenderer)s?\s+must\s+be\s+eligible\b",
    r"\b(?:bidder|supplier|vendor|participant|proponent|tenderer)s?\s+must\s+be\s+certified\b",
    r"\b(?:economic\s+(?:and|&)\s+)?financial\s+standing\b",
    r"\b(?:selection\s+questionnaire|supplier\s+questionnaire|procurement\s+specific\s+questionnaire)\s+qualification\b",
    r"\bqualification\s+requirements\b",
    r"\blegal\s+(?:capacity|standing|status|eligibility)\b",
    r"\b(?:oem|manufacturer['’]?s?)\s+authorization\b",
    r"\boriginal\s+equipment\s+manufacturer\s*\(\s*oem\s*\)\s+authorization\b",
    r"\bauthorized\s+(?:(?:oem\s+)?(?:[a-z0-9\-]+\s+)*)?(?:partner|reseller|distributor)\b",
    r"\bauthorized\s+by\s+(?:the\s+)?(?:respective\s+)?oem\b",
    r"\bsecurity\s+clearance\s+threshold\b",
    r"\b(?:debarment|debarred|exclusion\s+grounds|excludable|excluded\s+supplier)\b",
    r"\b(?:right\s+to\s+exclude|results?\s+in\s+exclusion|subject\s+to\s+exclusion)\b",
    r"\b(?:tax\s+registration|trade\s+license)\b",
    # Context-bound experience, capability, and bidding structure
    r"\b(?:bidder|supplier|vendor|participant|proponent|tenderer)s?\s+must\s+have\s+demonstrable\s+experience\b",
    r"\b(?:previous|demonstrable)\s+experience\s+(?:as\s+a\s+condition\s+of\s+participation|required\s+for\s+qualification)\b",
    r"\b(?:demonstrating\s+technical\s+ability|organizational\s+qualifications).*?(?:exclude|exclusion|condition[s]?\s+of\s+participation)\b",
    r"\b(?:organizational|technical)\s+capability\s+to\s+(?:supply|install|perform|provide)\b",
    r"\b(?:consortium|associated\s+person[s]?|guarantor).*?(?:condition[s]?\s+of\s+participation|financial\s+(?:capacity|standing)|exclusion|debarment)\b",
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

    Rules:
    - Accepts exact canonical values (case-insensitive, normalized whitespace/separators).
    - Accepts explicit exact aliases from _EXACT_ALIAS_MAP.
    - DOES NOT perform substring matching.
    - Ambiguous compounds (e.g. 'Technical Qualification', 'Qualification / Technical')
      strictly return None rather than guessing a category.
    """
    if not isinstance(raw_type, str):
        return None
    cleaned = raw_type.strip()
    if not cleaned:
        return None

    # Exact canonical check (case-insensitive)
    lower_cleaned = cleaned.lower()
    if lower_cleaned in _CANONICAL_LOWER_MAP:
        return _CANONICAL_LOWER_MAP[lower_cleaned]

    # Normalize inner multiple whitespace
    normalized_spacing = " ".join(lower_cleaned.split())
    if normalized_spacing in _EXACT_ALIAS_MAP:
        return _EXACT_ALIAS_MAP[normalized_spacing]

    # No substring matching: anything not exactly matched returns None
    return None


def resolve_candidate_requirement_types(candidate_types: Iterable[Any]) -> str:
    """
    True N-way order-independent and associative semantic resolution.

    Rules:
    - Retain/accumulate the set of normalized observed SPECIFIC semantic types.
    - Ignore General Compliance and None as specific evidence.
    - If zero specific types exist: General Compliance.
    - If exactly one distinct specific type exists: that specific type.
    - If two or more distinct specific types exist: General Compliance.
    """
    specifics = set()
    for t in candidate_types:
        norm = normalize_requirement_type(t)
        if norm in SPECIFIC_REQUIREMENT_TYPES:
            specifics.add(norm)

    if len(specifics) == 1:
        return next(iter(specifics))
    return TYPE_GENERAL_COMPLIANCE


def merge_requirement_types(current_type: Any, incoming_type: Any) -> str:
    """
    Conflict-safe, commutative (order-independent) merge of two requirement semantic types.
    Delegates to resolve_candidate_requirement_types for uniform resolution.
    """
    return resolve_candidate_requirement_types([current_type, incoming_type])


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


def has_supplier_qualification_evidence(requirement: dict | str) -> bool:
    """
    Check if a requirement contains deterministic evidence that the condition
    concerns bidder/supplier participation, eligibility, standing, authorization,
    capability or exclusion.

    Product or solution properties (e.g. 'all items must be brand new', 'hardware must...',
    'display must support 4K') return False even if labelled Supplier Qualification.
    """
    if isinstance(requirement, dict):
        desc = requirement.get("description") or ""
        rfso = requirement.get("rfso_ref") or ""
        text = f"{desc} {rfso}".strip()
    elif isinstance(requirement, str):
        text = requirement.strip()
    else:
        return False
    return bool(_QUAL_CUES_RE.search(text))


def is_supplier_qualification(requirement: dict) -> bool:
    """
    Returns True ONLY if:
    1. Requirement category is pass/fail Mandatory.
    2. Resolved requirement_type is Supplier Qualification.
    3. AND material requirement text satisfies has_supplier_qualification_evidence.

    Rated criteria or technical product specs cannot be qualification gates even if type is Supplier Qualification.
    """
    if not isinstance(requirement, dict):
        return False
    cat = (requirement.get("category") or "").strip().lower()
    if cat != "mandatory":
        return False
    if resolve_requirement_type(requirement) != TYPE_SUPPLIER_QUALIFICATION:
        return False
    return has_supplier_qualification_evidence(requirement)


def select_qualification_requirements(requirements: list[dict], qualification_gates: list[dict]) -> list[dict]:
    """
    Match authoritative qualification_gates from the Bid Brief back to persisted requirements.
    - Uses full normalized description identity as the primary anchor.
    - Case and punctuation differences remain supported by normalization.
    - NO fuzzy substring matching: if exact normalized description identity fails,
      it does NOT guess a match from substring containment.
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
    seen_pks: set = set()

    for g in qualification_gates:
        if not isinstance(g, dict):
            continue
        gate_text = g.get("requirement") or g.get("description") or ""
        norm_gate = normalize_requirement_identity_text(gate_text)
        if not norm_gate:
            continue

        # EXACT description match only
        target_req = desc_lookup.get(norm_gate)

        if target_req:
            # Anchor uniqueness by database id if present, else by full normalized description
            req_pk = target_req.get("id") or normalize_requirement_identity_text(target_req.get("description")) or id(target_req)
            if req_pk not in seen_pks:
                seen_pks.add(req_pk)
                matched.append(target_req)

    return matched


def get_qualification_gate_ui_alert(q_total: int, q_fail: int, q_unknown: int) -> dict[str, str]:
    """
    Produce the appropriate UI warning/info/success block for qualification gates in DECIDE.
    Returns dict with keys:
      'state': 'FAIL' | 'UNKNOWN' | 'ALL_VERIFIED' | 'ZERO_GATES'
      'alert_class': 'warn-box' | 'info-box' | 'success-box'
      'html': formatted alert html
    """
    if q_total == 0:
        return {
            "state": "ZERO_GATES",
            "alert_class": "info-box",
            "html": (
                '<div class="info-box">'
                'ℹ️ <strong>NO QUALIFICATION GATES IDENTIFIED:</strong> '
                'No explicit pass/fail supplier qualification gates were identified. '
                'Mandatory compliance requirements remain tracked separately.'
                '</div>'
            ),
        }

    if q_fail > 0:
        return {
            "state": "FAIL",
            "alert_class": "warn-box",
            "html": (
                f'<div class="warn-box">'
                f'⛔ <strong>DISQUALIFICATION RISK:</strong> {q_fail} qualification gate(s) are currently marked as <strong>FAIL</strong>. '
                f'Submitting without resolving these hard gates will result in formal rejection.'
                f'</div>'
            ),
        }

    if q_unknown > 0:
        return {
            "state": "UNKNOWN",
            "alert_class": "info-box",
            "html": (
                f'<div class="info-box">'
                f'⚠️ <strong>UNVERIFIED QUALIFICATION GATES:</strong> {q_unknown} qualification gate(s) have status <strong>UNKNOWN</strong>. '
                f'The system does not assume compliance without evidence. Verify qualifying credentials before committing to bid.'
                f'</div>'
            ),
        }

    return {
        "state": "ALL_VERIFIED",
        "alert_class": "success-box",
        "html": (
            '<div class="success-box">'
            '✅ <strong>ALL QUALIFICATION GATES VERIFIED:</strong> All supplier qualification criteria are confirmed with PASS status.'
            '</div>'
        ),
    }
