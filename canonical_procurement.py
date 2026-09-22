"""
canonical_procurement.py -- CI-1: Typed & Scoped Canonical Procurement
Intelligence.

THE shared canonical contract every current and future specialist
analyzer consumes. Pure, deterministic, no I/O, no model call. It does
NOT re-extract anything: it types, scopes and validates material that
`fast_analysis.py` already extracted and that `document_provenance.py`
(Layer 1 -- source/provenance) and `procurement_normalization.py`
(Layer 2 -- canonical procurement intelligence) already normalized.

CI-1's central finding was that extraction is usually correct but
canonicalization was losing four things:

  1. SEMANTIC TYPE   -- an evaluation RESPONSE_PROMPT was allowed to
                        populate a SCOPE_ITEM field (Defect B).
  2. SCOPE           -- category applicability was dropped from
                        requirements (C), evaluation criteria (D/E) and
                        milestones (F).
  3. SOURCE AUTHORITY-- one universal "latest document wins" ranking let
                        an addendum redefine procurement IDENTITY (A/J).
  4. TOPIC SEMANTICS -- shallow keyword matching bound clauses to the
                        wrong commercial topic (G) and attention points
                        to unrelated evidence (H).

Every helper here is deliberately conservative: when a classification is
not supportable from the material itself it returns the explicit
UNKNOWN/None member of its own closed vocabulary rather than guessing.
Nothing in this module is keyed to any particular buyer, solicitation or
document name.
"""
from __future__ import annotations

import re

import scripts.fast_analysis_report_adapter as _fast_report_adapter

_fuzzy_word_set = _fast_report_adapter._fuzzy_word_set
_is_near_duplicate = _fast_report_adapter._is_near_duplicate


# ═══════════════════════════════════════════════════════════════════════
# 1. Semantic type vocabulary (task section 4 / 13)
# ═══════════════════════════════════════════════════════════════════════

SEMANTIC_PROCUREMENT_IDENTITY = "PROCUREMENT_IDENTITY"
SEMANTIC_SCOPE_ITEM = "SCOPE_ITEM"
SEMANTIC_SERVICE = "SERVICE"
SEMANTIC_DELIVERABLE = "DELIVERABLE"
SEMANTIC_RESOURCE_EXPECTATION = "RESOURCE_EXPECTATION"
SEMANTIC_QUALIFICATION_REQUIREMENT = "QUALIFICATION_REQUIREMENT"
SEMANTIC_SUBMISSION_REQUIREMENT = "SUBMISSION_REQUIREMENT"
SEMANTIC_EVALUATION_CRITERION = "EVALUATION_CRITERION"
SEMANTIC_RESPONSE_PROMPT = "RESPONSE_PROMPT"
SEMANTIC_REQUESTED_EVIDENCE = "REQUESTED_EVIDENCE"
SEMANTIC_COMMERCIAL_OBLIGATION = "COMMERCIAL_OBLIGATION"
SEMANTIC_CONTRACTUAL_OBLIGATION = "CONTRACTUAL_OBLIGATION"
SEMANTIC_MILESTONE = "MILESTONE"
SEMANTIC_INFORMATIONAL_ITEM = "INFORMATIONAL_ITEM"
SEMANTIC_UNKNOWN = "UNKNOWN"

SEMANTIC_TYPES = (
    SEMANTIC_PROCUREMENT_IDENTITY, SEMANTIC_SCOPE_ITEM, SEMANTIC_SERVICE,
    SEMANTIC_DELIVERABLE, SEMANTIC_RESOURCE_EXPECTATION,
    SEMANTIC_QUALIFICATION_REQUIREMENT, SEMANTIC_SUBMISSION_REQUIREMENT,
    SEMANTIC_EVALUATION_CRITERION, SEMANTIC_RESPONSE_PROMPT,
    SEMANTIC_REQUESTED_EVIDENCE, SEMANTIC_COMMERCIAL_OBLIGATION,
    SEMANTIC_CONTRACTUAL_OBLIGATION, SEMANTIC_MILESTONE,
    SEMANTIC_INFORMATIONAL_ITEM, SEMANTIC_UNKNOWN,
)

#: Types that may NEVER be used to populate a scope-of-work field. A
#: response prompt telling the proponent what to write about a service is
#: not a statement of what the buyer is procuring (Defect B).
NON_SCOPE_SEMANTIC_TYPES = frozenset({
    SEMANTIC_RESPONSE_PROMPT, SEMANTIC_REQUESTED_EVIDENCE,
    SEMANTIC_EVALUATION_CRITERION, SEMANTIC_SUBMISSION_REQUIREMENT,
})

#: Types that legitimately describe the scope of work itself.
SCOPE_SEMANTIC_TYPES = frozenset({
    SEMANTIC_SCOPE_ITEM, SEMANTIC_SERVICE, SEMANTIC_DELIVERABLE,
    SEMANTIC_RESOURCE_EXPECTATION,
})

# A response prompt addresses the PROPONENT and asks them to write/
# provide/demonstrate something. These are the buyer-agnostic, standard
# procurement phrasings of that instruction -- not any one buyer's words.
_RESPONSE_PROMPT_RE = re.compile(
    r'\b(?:proponents?|bidders?|respondents?|suppliers?|tenderers?|vendors?|'
    r'proposals?|submissions?)\b[^.]{0,80}?\b(?:are\s+to|should|must|shall|may|will)\b'
    r'[^.]{0,40}?\b(?:describe|demonstrate|outline|explain|provide|detail|submit|'
    r'include|identify|address|set\s+out|confirm|indicate|state)\b'
    r'|\b(?:describe|demonstrate|outline|explain|detail)\s+(?:your|their|the\s+proponent)',
    re.IGNORECASE)

_REQUESTED_EVIDENCE_RE = re.compile(
    r'\b(?:attach|append|enclose|provide\s+(?:copies|evidence|proof|documentation)|'
    r'supporting\s+(?:documentation|evidence)|curricul(?:um|a)\s+vitae|\bCVs?\b|'
    r'r[ée]sum[ée]s?|references?\s+(?:must|are\s+to)\s+be\s+provided)\b',
    re.IGNORECASE)

_SUBMISSION_REQUIREMENT_RE = re.compile(
    r'\b(?:closing\s+(?:date|time)|submission\s+(?:deadline|method|portal)|'
    r'page\s+limit|not\s+exceed\s+\d+\s+pages?|font\s+size|'
    r'signed\s+by\s+a\s+person\s+authorized|submission\s+declaration|'
    r'must\s+be\s+(?:submitted|received)\b)',
    re.IGNORECASE)

_MILESTONE_RE = re.compile(
    r'\b(?:week\s+of|\d{4}-\d{2}-\d{2}|on\s+or\s+(?:before|about)\s+\w+\s+\d{1,2})\b',
    re.IGNORECASE)

_SCOPE_RE = re.compile(
    r'\b(?:the\s+services?\s+(?:will|shall)\s+(?:include|comprise|consist)|'
    r'scope\s+of\s+(?:work|services?)|statement\s+of\s+work|'
    r'the\s+(?:contractor|supplier|successful\s+proponent)\s+(?:will|shall|must)\s+'
    r'(?:provide|deliver|perform|supply)|'
    r'services?\s+(?:to\s+be\s+)?(?:provided|delivered|performed)|'
    r'call[\s-]?off\s+(?:activities|services)|deliverables?\s+(?:include|comprise))\b',
    re.IGNORECASE)

_RESOURCE_RE = re.compile(
    r'\b(?:roster\s+of|minimum\s+of\s+\d+\s+(?:consultants?|facilitators?|resources?|'
    r'practitioners?|staff)|key\s+personnel|named\s+resources?|'
    r'availability\s+of\s+resources?)\b', re.IGNORECASE)

_COMMERCIAL_RE = re.compile(
    r'\b(?:price|pricing|rate|invoice|payment|fee|escalation|remuneration|'
    r'hourly\s+rate|per\s+diem)\b', re.IGNORECASE)

_CONTRACTUAL_RE = re.compile(
    r'\b(?:indemnif\w*|liabilit\w*|governing\s+law|terminat\w*|assign(?:ment|ed)?\s+'
    r'(?:of\s+)?(?:this\s+)?(?:agreement|contract)|confidential|insurance|warrant)\b',
    re.IGNORECASE)

_QUALIFICATION_RE = re.compile(
    r'\b(?:years?\s+of\s+experience|minimum\s+(?:qualification|experience)|'
    r'must\s+have\s+(?:at\s+least|a\s+minimum)|certified|accredit|'
    r'demonstrated\s+experience\s+(?:in|with))\b', re.IGNORECASE)


def classify_semantic_type(text: str, hint: str | None = None) -> str:
    """Deterministically classify one piece of already-extracted
    procurement text into the closed SEMANTIC_TYPES vocabulary.

    `hint` is an optional structural signal the caller already knows for
    certain (e.g. "EVALUATION_CRITERION" because the text came out of a
    rated-criteria weight table, or "MILESTONE" because it came from a
    MILESTONE-family typed observation). A hint that is itself a member
    of SEMANTIC_TYPES is only ever OVERRIDDEN by the one distinction CI-1
    exists to protect: text that is unmistakably an instruction to the
    proponent is RESPONSE_PROMPT / REQUESTED_EVIDENCE regardless of which
    structural slot it was found in.

    Returns SEMANTIC_UNKNOWN when nothing in the text supports a
    classification -- callers must treat that as "do not use this text
    for a typed field", never as a default bucket.
    """
    body = (text or "").strip()
    if not body:
        return SEMANTIC_UNKNOWN

    if _REQUESTED_EVIDENCE_RE.search(body) and not _SCOPE_RE.search(body):
        return SEMANTIC_REQUESTED_EVIDENCE
    if _RESPONSE_PROMPT_RE.search(body):
        return SEMANTIC_RESPONSE_PROMPT

    if hint in SEMANTIC_TYPES and hint != SEMANTIC_UNKNOWN:
        return hint

    if _SUBMISSION_REQUIREMENT_RE.search(body):
        return SEMANTIC_SUBMISSION_REQUIREMENT
    if _MILESTONE_RE.search(body):
        return SEMANTIC_MILESTONE
    if _SCOPE_RE.search(body):
        return SEMANTIC_SCOPE_ITEM
    if _RESOURCE_RE.search(body):
        return SEMANTIC_RESOURCE_EXPECTATION
    if _QUALIFICATION_RE.search(body):
        return SEMANTIC_QUALIFICATION_REQUIREMENT
    if _CONTRACTUAL_RE.search(body):
        return SEMANTIC_CONTRACTUAL_OBLIGATION
    if _COMMERCIAL_RE.search(body):
        return SEMANTIC_COMMERCIAL_OBLIGATION
    return SEMANTIC_UNKNOWN


def is_usable_as_scope(text: str, hint: str | None = None) -> bool:
    """True only when `text` may legitimately populate a scope-of-work /
    "what is being procured" field (Defect B's fail-closed gate). An
    UNKNOWN classification is NOT usable -- absent positive evidence that
    a passage describes the work itself, the honest answer is "scope not
    stated", never a repurposed evaluation instruction."""
    return classify_semantic_type(text, hint) in SCOPE_SEMANTIC_TYPES


# ═══════════════════════════════════════════════════════════════════════
# 2. Source authority roles (task sections 3 / 15 / 12)
# ═══════════════════════════════════════════════════════════════════════

IDENTITY_ROLE_PRIMARY_SOLICITATION = "PRIMARY_SOLICITATION"
IDENTITY_ROLE_AMENDMENT = "AMENDMENT"
IDENTITY_ROLE_RESPONSE_FORM = "RESPONSE_FORM"
IDENTITY_ROLE_CONTRACT_INSTRUMENT = "CONTRACT_INSTRUMENT"
IDENTITY_ROLE_SUPPORTING = "SUPPORTING"

IDENTITY_ROLES = (
    IDENTITY_ROLE_PRIMARY_SOLICITATION, IDENTITY_ROLE_AMENDMENT,
    IDENTITY_ROLE_RESPONSE_FORM, IDENTITY_ROLE_CONTRACT_INSTRUMENT,
    IDENTITY_ROLE_SUPPORTING,
)

#: Per-field authority, NOT one universal ranking (task section 15). Each
#: entry lists identity roles in descending precedence for that field
#: family. A role absent from a list has NO authority over that field at
#: all -- e.g. an AMENDMENT never supplies procurement identity, it only
#: overrides clauses it explicitly changes.
AUTHORITY_BY_FIELD_FAMILY = {
    "identity": (
        IDENTITY_ROLE_PRIMARY_SOLICITATION,
        IDENTITY_ROLE_SUPPORTING,
        IDENTITY_ROLE_RESPONSE_FORM,
    ),
    "clause": (
        IDENTITY_ROLE_AMENDMENT,
        IDENTITY_ROLE_PRIMARY_SOLICITATION,
        IDENTITY_ROLE_SUPPORTING,
    ),
    "contract": (
        IDENTITY_ROLE_CONTRACT_INSTRUMENT,
        IDENTITY_ROLE_AMENDMENT,
        IDENTITY_ROLE_PRIMARY_SOLICITATION,
    ),
    "response_form": (
        IDENTITY_ROLE_RESPONSE_FORM,
        IDENTITY_ROLE_AMENDMENT,
        IDENTITY_ROLE_PRIMARY_SOLICITATION,
    ),
}

_AMENDMENT_NAME_RE = re.compile(
    r'\b(?:addend(?:um|a)|amendment|revision\s+notice)\b', re.IGNORECASE)
_AMENDMENT_PATH_RE = re.compile(r'(?:^|/)amendment\s*0*\d+\b', re.IGNORECASE)
_RESPONSE_FORM_NAME_RE = re.compile(
    r'\b(?:response\s+form|proposal\s+response|submission\s+form|'
    r'rated\s+criteria|mandatory\s+criteria|qualification\s+requirements?)\b',
    re.IGNORECASE)
_CONTRACT_NAME_RE = re.compile(
    r'\b(?:form\s+of\s+(?:contract|agreement)|draft\s+(?:contract|agreement)|'
    r'general\s+service\s+agreement|terms\s+and\s+conditions)\b', re.IGNORECASE)
_SUPPORTING_NAME_RE = re.compile(
    r'\b(?:appendix|annex(?:e)?|schedule|attachment|exhibit)\b', re.IGNORECASE)


def classify_identity_role(document_name: str) -> str:
    """Classify ONE document's procurement-identity role from its own
    name/path convention only -- never from recency, never from upload
    order, never from how much text it contains.

    The ordering below is the whole point of Defect A: an addendum is
    recognized BEFORE the "looks like a main solicitation" fallback, so
    "RFP 2026-026 Addendum #2.pdf" can never be mistaken for the
    procurement-identity document merely because it also carries the
    solicitation number in its filename."""
    name = (document_name or "")
    base = name.rsplit("/", 1)[-1]
    if _AMENDMENT_PATH_RE.search(name) or _AMENDMENT_NAME_RE.search(base):
        return IDENTITY_ROLE_AMENDMENT
    if _CONTRACT_NAME_RE.search(base):
        return IDENTITY_ROLE_CONTRACT_INSTRUMENT
    if _RESPONSE_FORM_NAME_RE.search(base):
        return IDENTITY_ROLE_RESPONSE_FORM
    if _SUPPORTING_NAME_RE.search(base):
        return IDENTITY_ROLE_SUPPORTING
    return IDENTITY_ROLE_PRIMARY_SOLICITATION


def classify_identity_roles(document_names: list[str]) -> dict[str, str]:
    """`classify_identity_role` over a whole corpus. Every name gets
    exactly one role."""
    return {name: classify_identity_role(name) for name in document_names}


def merge_identity_fields(
    metadata_by_doc: dict[str, dict],
    field_family: str = "identity",
) -> dict:
    """Merge per-document metadata into one canonical record using the
    PER-FIELD-FAMILY authority ranking above, not a single global one.

    For `field_family="identity"`, an AMENDMENT-role document contributes
    NOTHING unless no document of any identity-bearing role supplied a
    value at all -- and even then only as an explicit last resort, so a
    package consisting solely of addenda still yields the best available
    answer instead of nothing. Within one role, insertion order decides,
    which keeps the result deterministic for a given corpus.

    Returns {field: value}. Callers wanting to know WHICH document won a
    field use `merge_identity_fields_with_provenance`."""
    return {k: v for k, (v, _doc) in
            merge_identity_fields_with_provenance(metadata_by_doc, field_family).items()}


def merge_identity_fields_with_provenance(
    metadata_by_doc: dict[str, dict],
    field_family: str = "identity",
) -> dict[str, tuple]:
    """As `merge_identity_fields`, but each value is a
    (value, source_document_name) pair so the canonical record stays
    traceable to the exact document whose authority produced it."""
    ranking = AUTHORITY_BY_FIELD_FAMILY.get(field_family) or AUTHORITY_BY_FIELD_FAMILY["identity"]
    roles = classify_identity_roles(list(metadata_by_doc.keys()))

    merged: dict[str, tuple] = {}
    for role in ranking:
        for doc_name, meta in metadata_by_doc.items():
            if roles.get(doc_name) != role or not isinstance(meta, dict):
                continue
            for key, value in meta.items():
                if value and key not in merged:
                    merged[key] = (value, doc_name)

    # Last resort only: a corpus with no identity-bearing document at all
    # still gets an honest best-available answer rather than silence.
    for doc_name, meta in metadata_by_doc.items():
        if roles.get(doc_name) in ranking or not isinstance(meta, dict):
            continue
        for key, value in meta.items():
            if value and key not in merged:
                merged[key] = (value, doc_name)
    return merged


# ═══════════════════════════════════════════════════════════════════════
# 3. Category applicability / scope (task sections 5 / 11)
# ═══════════════════════════════════════════════════════════════════════

APPLICABILITY_CATEGORY_SPECIFIC = "CATEGORY_SPECIFIC"
APPLICABILITY_ALL_CATEGORIES = "ALL_CATEGORIES"
APPLICABILITY_SUBMISSION_WIDE = "SUBMISSION_WIDE"
APPLICABILITY_CONTRACT_WIDE = "CONTRACT_WIDE"
APPLICABILITY_INFORMATIONAL = "INFORMATIONAL"
APPLICABILITY_UNKNOWN = "UNKNOWN"

APPLICABILITY_VALUES = (
    APPLICABILITY_CATEGORY_SPECIFIC, APPLICABILITY_ALL_CATEGORIES,
    APPLICABILITY_SUBMISSION_WIDE, APPLICABILITY_CONTRACT_WIDE,
    APPLICABILITY_INFORMATIONAL, APPLICABILITY_UNKNOWN,
)

# A short letter+digit form/category identifier (C1/D2/B3 ...) -- exactly
# the convention document_provenance already relies on to keep one
# category's form distinct from another's.
_CATEGORY_ID_RE = re.compile(r'\b([A-Z]\d{1,2})\b')
_CATEGORY_NUMBER_RE = re.compile(r'\bcategory\s*(\d{1,2})\b', re.IGNORECASE)

_ALL_CATEGORIES_RE = re.compile(
    r'\b(?:all\s+(?:three\s+)?(?:categories|service\s+categories|lots)|'
    r'each\s+(?:category|service\s+category)|every\s+category|'
    r'regardless\s+of\s+category|applies\s+to\s+all)\b', re.IGNORECASE)


def _category_tokens(text: str) -> set[str]:
    """Every category/scope identifier a piece of text or a document name
    explicitly names: "D2" -> {"D2"}, "Category 1" -> {"CATEGORY 1"}."""
    tokens = {m.group(1).upper() for m in _CATEGORY_ID_RE.finditer(text or "")}
    tokens |= {f"CATEGORY {m.group(1)}" for m in _CATEGORY_NUMBER_RE.finditer(text or "")}
    return tokens


def derive_requirement_applicability(requirement: dict) -> dict:
    """Derive a requirement's canonical applicability WITHOUT ever
    inferring "global" merely because a requirement happens to sit in a
    shared summary document (task section 5's explicit prohibition).

    Signals, in precedence order, all source-grounded:
      1. An explicit `category_scope`/`applies_to` field the extraction
         already captured.
      2. An "applies to all categories" statement in the requirement's
         own text -> ALL_CATEGORIES.
      3. A category identifier (C1/D2/"Category 3") named in the
         requirement's own text.
      4. A category identifier in the requirement's own SOURCE DOCUMENT
         name -- a requirement extracted from "Appendix C2 - Minimum
         qualification requirements.xlsx" is a Category 2 qualification
         requirement, full stop.
      5. Semantic type: a SUBMISSION_REQUIREMENT is SUBMISSION_WIDE, a
         COMMERCIAL/CONTRACTUAL obligation is CONTRACT_WIDE, an
         INFORMATIONAL item is INFORMATIONAL.
      6. Otherwise UNKNOWN -- explicitly NOT "all categories". A
         consumer must render that as "applicability not stated".

    Returns {"applicability", "category_ids" (sorted list),
    "semantic_type", "basis"}.
    """
    description = (requirement.get("description") or "")
    source_doc = (requirement.get("source_doc") or "")
    semantic_type = classify_semantic_type(
        description, requirement.get("semantic_type"))

    explicit = requirement.get("category_scope") or requirement.get("applies_to")
    if isinstance(explicit, str) and explicit.strip():
        if _ALL_CATEGORIES_RE.search(explicit):
            return {"applicability": APPLICABILITY_ALL_CATEGORIES, "category_ids": [],
                    "semantic_type": semantic_type, "basis": "explicit_field"}
        ids = sorted(_category_tokens(explicit))
        if ids:
            return {"applicability": APPLICABILITY_CATEGORY_SPECIFIC, "category_ids": ids,
                    "semantic_type": semantic_type, "basis": "explicit_field"}
        return {"applicability": APPLICABILITY_CATEGORY_SPECIFIC,
                "category_ids": [explicit.strip().upper()],
                "semantic_type": semantic_type, "basis": "explicit_field"}

    if _ALL_CATEGORIES_RE.search(description):
        return {"applicability": APPLICABILITY_ALL_CATEGORIES, "category_ids": [],
                "semantic_type": semantic_type, "basis": "stated_in_text"}

    ids = sorted(_category_tokens(description))
    if ids:
        return {"applicability": APPLICABILITY_CATEGORY_SPECIFIC, "category_ids": ids,
                "semantic_type": semantic_type, "basis": "stated_in_text"}

    doc_ids = sorted(_category_tokens(source_doc.rsplit("/", 1)[-1]))
    if doc_ids:
        return {"applicability": APPLICABILITY_CATEGORY_SPECIFIC, "category_ids": doc_ids,
                "semantic_type": semantic_type, "basis": "source_document"}

    if semantic_type == SEMANTIC_SUBMISSION_REQUIREMENT:
        return {"applicability": APPLICABILITY_SUBMISSION_WIDE, "category_ids": [],
                "semantic_type": semantic_type, "basis": "semantic_type"}
    if semantic_type in (SEMANTIC_COMMERCIAL_OBLIGATION, SEMANTIC_CONTRACTUAL_OBLIGATION):
        return {"applicability": APPLICABILITY_CONTRACT_WIDE, "category_ids": [],
                "semantic_type": semantic_type, "basis": "semantic_type"}
    if semantic_type == SEMANTIC_INFORMATIONAL_ITEM:
        return {"applicability": APPLICABILITY_INFORMATIONAL, "category_ids": [],
                "semantic_type": semantic_type, "basis": "semantic_type"}

    return {"applicability": APPLICABILITY_UNKNOWN, "category_ids": [],
            "semantic_type": semantic_type, "basis": "not_stated"}


def applicability_compatible(a: dict, b: dict) -> bool:
    """Whether two canonical objects may EVER be merged as the same
    obligation (Defect I's hard rule: "Never merge obligations with
    different applicability").

    The rule is about CONFLICTING STATED scope, not about silence. Two
    requirements are incompatible only when BOTH state an applicability
    and those statements disagree -- a Category 1 obligation and a
    Category 2 obligation are two obligations even when worded
    identically. A requirement whose source never states a scope
    (APPLICABILITY_UNKNOWN) is compatible with anything: the main RFP's
    unscoped restatement of a Category 2 form's obligation is the same
    obligation, and refusing that merge would resurrect the duplicate
    requirements CI-1's predecessor task removed."""
    app_a, app_b = a.get("applicability"), b.get("applicability")
    if APPLICABILITY_UNKNOWN in (app_a, app_b):
        return True
    if app_a != app_b:
        return False
    ids_a = sorted(a.get("category_ids") or [])
    ids_b = sorted(b.get("category_ids") or [])
    if not ids_a or not ids_b:
        return True
    return ids_a == ids_b


def most_specific_applicability(entries: list[dict]) -> dict:
    """The canonical applicability of a merged group: the single stated
    applicability its members agree on, or UNKNOWN when none of them
    state one. Never invents a scope no member stated, and never widens
    a stated category-specific scope into "all categories"."""
    stated = [e for e in entries if e.get("applicability") != APPLICABILITY_UNKNOWN]
    if not stated:
        return dict(entries[0]) if entries else {
            "applicability": APPLICABILITY_UNKNOWN, "category_ids": [],
            "semantic_type": SEMANTIC_UNKNOWN, "basis": "not_stated"}
    specific = [e for e in stated if e.get("category_ids")]
    return dict((specific or stated)[0])


# ═══════════════════════════════════════════════════════════════════════
# 4. Scoped evaluation-criterion identity (task sections 6 / 7)
# ═══════════════════════════════════════════════════════════════════════

def scoped_criterion_key(category: str | None, criterion: str) -> tuple:
    """A canonical evaluation criterion's identity is (category, criterion
    label) -- NOT the label alone. Two categories that both score
    "Relevant Experience" have two separately-scored criteria, and
    collapsing them into one loses the scoring identity the buyer
    actually defined (Defects D and E)."""
    cat = re.sub(r'\s+', ' ', (category or "").strip()).lower()
    crit = re.sub(r'\s+', ' ', (criterion or "").strip()).lower()
    return (cat, crit)


def is_genuinely_global_criterion(
    criterion: str,
    scoped_criteria: list[tuple],
) -> bool:
    """A criterion label is only "procurement-wide" when it appears with
    NO category scope at all. A label that occurs inside one or more
    category-scoped criterion sets is, by definition, a scoped instance
    (or several) -- never one global criterion (Defect E).

    `scoped_criteria` is the already-known list of (category, label)
    pairs from every category's own evaluation table."""
    label = re.sub(r'\s+', ' ', (criterion or "").strip()).lower()
    if not label:
        return False
    label_words = _fuzzy_word_set(label)
    for cat, crit in scoped_criteria:
        if not cat:
            continue
        if crit == label:
            return False
        if _is_near_duplicate(label, label_words, crit, _fuzzy_word_set(crit)):
            return False
    return True


# ═══════════════════════════════════════════════════════════════════════
# 5. Scoped milestone identity (task section 8 / Defect F)
# ═══════════════════════════════════════════════════════════════════════

def milestone_scope_key(observation: dict) -> tuple:
    """A milestone's canonical identity is (event_type, scope), not
    event_type alone. Two categories' presentation dates are two distinct
    scoped events, not a conflict (Defect F).

    Reads every scope-bearing field the extraction schema can produce
    (`scope` dict, `category_scope`, `component`, `lot`) and normalizes
    them into one comparable key. An observation with no scope signal at
    all yields an empty key -- and two empty-keyed observations of the
    same event type ARE genuinely comparable, which is exactly when a
    date disagreement is a real ambiguity."""
    scope = observation.get("scope")
    parts: set[str] = set()
    if isinstance(scope, dict):
        parts |= {str(v).strip().lower() for v in scope.values() if v}
    elif isinstance(scope, str) and scope.strip():
        parts.add(scope.strip().lower())
    for key in ("category_scope", "component", "lot", "applies_to"):
        value = observation.get(key)
        if isinstance(value, str) and value.strip():
            parts.add(value.strip().lower())
    # A scope naming an explicit category identifier normalizes to that
    # identifier, so "Category 1" and "category 1 - learning" agree.
    ids: set[str] = set()
    for part in parts:
        ids |= _category_tokens(part.upper())
    return tuple(sorted(ids)) if ids else tuple(sorted(parts))


# ═══════════════════════════════════════════════════════════════════════
# 6. Commercial / contractual semantic topics (task section 9 / Defect G)
# ═══════════════════════════════════════════════════════════════════════

TOPIC_PRICING_ESCALATION = "PRICING_ESCALATION"
TOPIC_CALL_OFF_ACCEPTANCE = "CALL_OFF_ACCEPTANCE"
TOPIC_TERMINATION = "TERMINATION"
TOPIC_INDEMNITY = "INDEMNITY"
TOPIC_TAX_STATUTORY = "TAX_STATUTORY_REMITTANCES"
TOPIC_INSURANCE = "INSURANCE"
TOPIC_GOVERNING_LAW = "GOVERNING_LAW"
TOPIC_IP = "INTELLECTUAL_PROPERTY"
TOPIC_CONFIDENTIALITY = "CONFIDENTIALITY"
TOPIC_PRIVACY = "PRIVACY"
TOPIC_CYBERSECURITY = "CYBERSECURITY"
TOPIC_WARRANTY = "WARRANTY"
TOPIC_CONFLICT_OF_INTEREST = "CONFLICT_OF_INTEREST"
TOPIC_ASSIGNMENT = "ASSIGNMENT"
TOPIC_UNCLASSIFIED = "UNCLASSIFIED"

COMMERCIAL_TOPICS = (
    TOPIC_PRICING_ESCALATION, TOPIC_CALL_OFF_ACCEPTANCE, TOPIC_TERMINATION,
    TOPIC_INDEMNITY, TOPIC_TAX_STATUTORY, TOPIC_INSURANCE,
    TOPIC_GOVERNING_LAW, TOPIC_IP, TOPIC_CONFIDENTIALITY, TOPIC_PRIVACY,
    TOPIC_CYBERSECURITY, TOPIC_WARRANTY, TOPIC_CONFLICT_OF_INTEREST,
    TOPIC_ASSIGNMENT, TOPIC_UNCLASSIFIED,
)

# Ordered most-specific-first. Each rule is a (topic, positive regex,
# disqualifying regex | None). The FIRST rule whose positive pattern
# matches and whose disqualifier does not wins -- so a clause about
# statutory remittances that merely mentions "indemnify the Bank" is
# classified TAX_STATUTORY (its actual subject), not INDEMNITY.
_TOPIC_RULES: tuple = (
    (TOPIC_TAX_STATUTORY, re.compile(
        r'\b(?:income\s+tax|withholding\s+tax|GST|HST|QST|VAT|'
        r'Canada\s+Pension\s+Plan|\bCPP\b|employment\s+insurance|\bEI\b\s+premiums?|'
        r'workers[\'’]?\s+compensation|workplace\s+(?:safety\s+and\s+)?insurance|'
        r'\bWSIB\b|payroll\s+(?:deduction|remittance)|statutory\s+(?:deduction|remittance)|'
        r'source\s+deductions?)\b', re.IGNORECASE), None),
    (TOPIC_CALL_OFF_ACCEPTANCE, re.compile(
        r'\b(?:decline|refuse|turn\s+down|not\s+obliged\s+to\s+accept|'
        r'no\s+obligation\s+to\s+(?:accept|purchase|order))\b[^.]{0,80}?'
        r'\b(?:engagement|assignment|work\s+request|service\s+request|call[\s-]?off|'
        r'task\s+authorization|statement\s+of\s+work)\b'
        r'|\b(?:no\s+guarantee|not\s+guarantee)\b[^.]{0,60}?\b(?:volume|quantity|work)\b',
        re.IGNORECASE), None),
    (TOPIC_ASSIGNMENT, re.compile(
        r'\b(?:assign\w*|transfer\w*|subcontract\w*)\b[^.]{0,80}?'
        r'\b(?:this\s+)?(?:agreement|contract|rights?\s+(?:and|or)\s+obligations?)\b'
        r'|\bchange\s+of\s+control\b', re.IGNORECASE), None),
    (TOPIC_INDEMNITY, re.compile(
        r'\b(?:indemnif\w*|save\s+harmless|hold\s+harmless|limitation\s+of\s+liability|'
        r'liable\s+for\s+(?:any|all)\s+(?:loss|damage))\b', re.IGNORECASE), None),
    (TOPIC_INSURANCE, re.compile(
        r'\b(?:commercial\s+general\s+liability|certificate\s+of\s+insurance|'
        r'insurance\s+(?:policy|coverage|policies)|professional\s+liability\s+insurance|'
        r'maintain\s+insurance)\b', re.IGNORECASE), None),
    (TOPIC_TERMINATION, re.compile(
        r'\b(?:terminat\w+|event\s+of\s+default|cancel\s+this\s+(?:agreement|contract))\b',
        re.IGNORECASE), None),
    (TOPIC_GOVERNING_LAW, re.compile(
        r'\b(?:governed\s+by\s+the\s+laws|governing\s+law|courts?\s+of\s+the\s+'
        r'(?:province|state)|exclusive\s+jurisdiction)\b', re.IGNORECASE), None),
    (TOPIC_IP, re.compile(
        r'\b(?:intellectual\s+property|copyright|moral\s+rights|'
        r'work\s+product\s+(?:will|shall)\s+(?:vest|belong)|licen[cs]e\s+to\s+use)\b',
        re.IGNORECASE), None),
    (TOPIC_PRIVACY, re.compile(
        r'\b(?:personal\s+information|privacy\s+(?:act|schedule|protection)|'
        r'\bPIPEDA\b|\bFIPPA\b|\bGDPR\b|data\s+subject)\b', re.IGNORECASE), None),
    (TOPIC_CYBERSECURITY, re.compile(
        r'\b(?:cyber\s*security|information\s+security|encrypt\w*|'
        r'threat\s+and\s+risk\s+assessment|security\s+controls?|penetration\s+test)\b',
        re.IGNORECASE), None),
    (TOPIC_CONFIDENTIALITY, re.compile(
        r'\b(?:confidential\s+information|non[\s-]?disclosure|keep\s+confidential)\b',
        re.IGNORECASE), None),
    (TOPIC_CONFLICT_OF_INTEREST, re.compile(
        r'\bconflict\s+of\s+interest\b', re.IGNORECASE), None),
    (TOPIC_WARRANTY, re.compile(
        r'\b(?:warrant\w+|represents?\s+and\s+warrants?)\b', re.IGNORECASE), None),
    # "pricing / escalation" in the task's own bounded taxonomy covers
    # the priced STRUCTURE as well as escalation: a blended-rate formula
    # or an hourly/per-diem rate basis is genuine pricing content and
    # belongs here. Deliberately specific phrasings, so incidental
    # mentions of the word "pricing" (e.g. "the Bank may seek
    # clarification of pricing") do NOT capture this slot.
    (TOPIC_PRICING_ESCALATION, re.compile(
        r'\b(?:firm\s+(?:for|price)|price\s+(?:increase|escalation|adjustment)|'
        r'rates?\s+(?:will|shall)\s+(?:remain|be)\s+firm|consumer\s+price\s+index|\bCPI\b|'
        r'blended\s+rate|rates?\s+calculated\s+as|hourly\s+rate|per\s+diem|'
        r'maximum\s+annual\s+increase|rate\s+card|pricing\s+(?:structure|basis|schedule))\b',
        re.IGNORECASE), None),
)


def classify_commercial_topic(clause_text: str, heading: str | None = None) -> str:
    """Classify a commercial/contractual clause into the bounded topic
    taxonomy (task section 9), preferring, in order:

      1. The clause's own EXPLICIT source heading / clause title, when
         the heading itself classifies unambiguously. The buyer's own
         heading is the strongest available signal and outranks anything
         inferred from body prose.
      2. Deterministic contextual classification of the clause body,
         using ordered most-specific-first rules so a clause whose
         SUBJECT is statutory remittances is never captured by an
         INDEMNITY keyword it merely mentions in passing.
      3. TOPIC_UNCLASSIFIED -- explicitly not a bucket to fill a report
         slot with. A bounded model classification could be added here
         later for genuinely ambiguous clauses; CI-1 deliberately does
         not add one, because no live clause in the reference corpus
         needed it.
    """
    if heading:
        for topic, positive, disqualifier in _TOPIC_RULES:
            if positive.search(heading) and not (disqualifier and disqualifier.search(heading)):
                return topic
    body = clause_text or ""
    for topic, positive, disqualifier in _TOPIC_RULES:
        if positive.search(body) and not (disqualifier and disqualifier.search(body)):
            return topic
    return TOPIC_UNCLASSIFIED


def clause_supports_topic(clause_text: str, topic: str, heading: str | None = None) -> bool:
    """Fail-closed gate used before a clause is rendered under a named
    commercial topic: a clause whose own deterministic classification
    contradicts `topic` must NOT be bound to it (Defect G). An
    UNCLASSIFIED clause is permitted to stay where the upstream
    extraction put it -- CI-1 removes wrong bindings, it does not discard
    clauses it simply cannot classify."""
    classified = classify_commercial_topic(clause_text, heading)
    return classified in (topic, TOPIC_UNCLASSIFIED)


# ═══════════════════════════════════════════════════════════════════════
# 7. Attention-point evidence binding (task section 10 / Defect H)
# ═══════════════════════════════════════════════════════════════════════

#: Each synthesizable attention-point topic and the pattern a supporting
#: fact must itself match to be allowed to support it. Fail-closed: a
#: topic absent from this map has no validated evidence contract and is
#: never auto-bound.
_ATTENTION_TOPIC_EVIDENCE = {
    "REFERENCE_CHECK": re.compile(
        r'\b(?:referees?|references?|reference\s+check|past\s+performance\s+check)\b',
        re.IGNORECASE),
    "BILINGUALISM": re.compile(
        r'\b(?:bilingual\w*|both\s+official\s+languages|français|french\s+and\s+english)\b',
        re.IGNORECASE),
    "SECURITY_SCREENING": re.compile(
        r'\b(?:security\s+(?:clearance|screening)|criminal\s+record\s+check|'
        r'background\s+check)\b', re.IGNORECASE),
    "CYBERSECURITY": _TOPIC_RULES[10][1],
    "PRICING_COMPLETENESS": re.compile(
        r'\b(?:unconditional|all[\s-]inclusive|complete\s+pricing|no\s+additional\s+charges)\b',
        re.IGNORECASE),
}

ATTENTION_TOPICS = tuple(sorted(_ATTENTION_TOPIC_EVIDENCE))


def attention_evidence_supports_topic(topic: str, fact_text: str) -> bool:
    """Fail-closed validation that a synthesized attention point's
    supporting fact actually concerns that point's topic (Defect H: a
    reference-check attention point citing a bilingualism requirement is
    semantically incoherent and must never be emitted).

    An unknown topic returns False -- the caller must then either find
    genuinely matching evidence or not emit the point at all."""
    pattern = _ATTENTION_TOPIC_EVIDENCE.get(topic)
    if pattern is None:
        return False
    return bool(pattern.search(fact_text or ""))


def select_supporting_facts(topic: str, candidate_facts: list[str]) -> list[str]:
    """Every candidate fact that genuinely supports `topic`, order
    preserved. Returns [] when none do -- the caller must then omit the
    attention point rather than bind the nearest available fact, which is
    exactly the failure Defect H describes."""
    return [f for f in candidate_facts if attention_evidence_supports_topic(topic, f)]
