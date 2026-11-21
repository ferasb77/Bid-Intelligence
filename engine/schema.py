"""General-purpose procurement vocabulary and the JSON schemas both analysts
answer in. Nothing here is specific to any buyer, document or test case."""
from __future__ import annotations

CATEGORIES: dict[str, str] = {
    "IDENTITY": "who issues the opportunity, its title, reference number, buyer, programme",
    "SCOPE": "what is being procured; services, goods, objectives, beneficiaries, location of delivery",
    "DELIVERABLE": "outputs, activities, reports, milestones the supplier must produce or perform",
    "ELIGIBILITY": "who may bid at all: legal status, registration, nationality, licences, "
                   "pass/fail participation conditions",
    "QUALIFICATION": "technical or professional experience, personnel, certifications, past "
                     "performance the bidder or its team must have",
    "SUBMISSION_REQUIREMENT": "what the proposal must contain or how it must be prepared "
                              "(format, language, copies, signatures, structure, page limits)",
    "SUBMISSION_METHOD": "how and where bids are delivered (e-mail, portal, physical address, envelopes)",
    "DEADLINE": "dates and times: submission deadline, questions deadline, validity, schedule, milestones",
    "REQUIRED_DOCUMENT": "specific documents, forms, certificates or annexes that must be submitted",
    "DISQUALIFICATION": "conditions that cause rejection, disqualification or non-consideration of a bid",
    "FINANCIAL_THRESHOLD": "turnover, budget ceilings, minimum financial capacity, estimated value",
    "GUARANTEE": "bid bonds, performance guarantees, securities, insurance, retention",
    "EVALUATION": "evaluation and award criteria, weights, scoring, thresholds, evaluation method",
    "PRICING": "how prices must be stated: currency, taxes, inclusions, price forms, price validity",
    "PAYMENT": "payment terms, schedule, invoicing, advance payments",
    "CONTRACT_TERM": "contractual obligations, restrictions, penalties, IP, confidentiality, termination",
    "DURATION": "contract or project duration, implementation period, phases",
    "RISK_DEPENDENCY": "material risks, dependencies, buyer responsibilities, assumptions stated by the buyer",
    "DOCUMENT_AUTHORITY": "which document prevails over another, order of precedence, how addenda apply",
    "AMENDMENT": "a statement that changes, clarifies, adds to, replaces or cancels an earlier provision",
    "OTHER": "any other provision material to deciding whether and how to bid",
}

#: Categories whose omission from FAST is a material defect.
FAST_MANDATORY = {"ELIGIBILITY", "QUALIFICATION", "SUBMISSION_REQUIREMENT", "SUBMISSION_METHOD", "DEADLINE",
                  "REQUIRED_DOCUMENT", "DISQUALIFICATION", "FINANCIAL_THRESHOLD", "GUARANTEE", "EVALUATION"}

MODALITIES = {
    "MUST": "an obligation (must, shall, is required to, is to)",
    "MUST_NOT": "a prohibition (must not, shall not, may not, is not permitted)",
    "SHOULD": "a recommendation or expectation (should, is expected to, is encouraged)",
    "MAY": "a permission or option (may, can, reserves the right to)",
    "WILL": "a statement of what will happen or a commitment (will) -- not the same as MUST",
    "IS": "a statement of fact or information with no modal force",
}

MATERIALITY = {
    "CRITICAL": "failing it can exclude the bid or makes the bid non-compliant (eligibility, mandatory "
                "documents, deadlines, submission method, guarantees, disqualification conditions)",
    "MATERIAL": "affects the decision to bid, the price, the commitments or the evaluation",
    "INFORMATIONAL": "useful context with no direct consequence for the bid",
}

VALUE_KINDS = ["DATE", "TIME", "AMOUNT", "PERCENT", "DURATION", "QUANTITY", "EMAIL", "URL", "REFERENCE", "OTHER"]

RELATION_TYPES = ["CROSS_REFERENCE", "AMENDS", "CLARIFIES", "CONDITIONAL_EXCEPTION", "CONFLICTS_WITH",
                  "RESTATES", "DEPENDS_ON"]


def _str(desc: str = "") -> dict:
    return {"type": "string", "description": desc} if desc else {"type": "string"}


def _strs(desc: str) -> dict:
    return {"type": "array", "items": {"type": "string"}, "description": desc}


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


VALUE = _obj({"kind": {"type": "string", "enum": VALUE_KINDS},
              "text": _str("the value exactly as written in the quote"),
              "normalized": _str("ISO date (YYYY-MM-DD), number, currency code + amount, or '' if unsure")})

FINDING = _obj({
    "category": {"type": "string", "enum": list(CATEGORIES)},
    "statement": _str("faithful one-sentence restatement; keeps who, the modal force, every condition, "
                      "exception, number and date; adds nothing"),
    "quote": _str("verbatim text copied from the page that states this, without paraphrase; use ' ... ' "
                  "only to join non-adjacent parts of the same page"),
    "document": _str("the document name from the SOURCE marker"),
    "page": _str("page number or sheet name from the nearest marker"),
    "section": _str("heading path of the section, e.g. '3. Instructions > 3.4 Submission'"),
    "party": _str("who the provision binds or concerns (bidder, supplier, buyer, evaluation committee...)"),
    "action": _str("what the party must / may / will do, or what is stated"),
    "modality": {"type": "string", "enum": list(MODALITIES)},
    "conditions": _strs("conditions under which it applies (if, when, provided that ...), verbatim or close"),
    "exceptions": _strs("exceptions and alternatives (unless, except, or ...)"),
    "values": {"type": "array", "items": VALUE},
    "consequence": _str("the consequence the text states for non-compliance, or ''"),
    "materiality": {"type": "string", "enum": list(MATERIALITY)},
    "relations": {"type": "array", "items": _obj({
        "type": {"type": "string", "enum": RELATION_TYPES},
        "target": _str("the section, clause, annex or document referred to, as written")})},
    "uncertainty": _str("anything ambiguous or unclear about this provision, or ''"),
})

SECTION_ACCOUNT = _obj({
    "section_id": _str("the SECTION id given in the input"),
    "status": {"type": "string", "enum": ["HAS_FINDINGS", "NO_MATERIAL_PROVISIONS", "UNREADABLE"]},
    "note": _str("for NO_MATERIAL_PROVISIONS or UNREADABLE: why, in a few words"),
})

EXTRACTION_OUTPUT = _obj({
    "findings": {"type": "array", "items": FINDING},
    "sections": {"type": "array", "items": SECTION_ACCOUNT},
})

PACKAGE_REVIEW_OUTPUT = _obj({
    "documents": {"type": "array", "items": _obj({
        "document": _str(),
        "role": {"type": "string", "enum": ["MAIN_SOLICITATION", "TERMS_OF_REFERENCE", "TECHNICAL_SPECIFICATION",
                                            "ANNEX", "FORM", "PRICE_SCHEDULE", "CLARIFICATION", "ADDENDUM",
                                            "CONTRACT", "OTHER"]},
        "version": _str("version, issue number or date the document states for itself, or ''"),
        "summary": _str("one sentence")})},
    "relationships": {"type": "array", "items": _obj({
        "type": {"type": "string", "enum": ["RESTATEMENT", "CLARIFICATION", "CONDITIONAL_EXCEPTION",
                                            "EXPRESS_AMENDMENT", "SUPERSEDED", "UNRESOLVED_CONTRADICTION",
                                            "CONSISTENT"]},
        "finding_ids": _strs("ids of the findings involved, earliest provision first"),
        "explanation": _str("why, citing the text"),
        "authority_quote": _str("verbatim text that establishes which provision applies (an express amendment "
                                "or an order-of-precedence rule), or '' if none exists"),
        "authority_document": _str("document containing authority_quote, or ''"),
        "clarification_question": _str("a neutral question to ask the buyer if unresolved, else ''"),
        "implication": _str("what it means for a bidder if unresolved, or ''")})},
    "missed": {"type": "array", "items": FINDING,
               "description": "material provisions you notice in the listed findings' sections that no "
                              "finding states (only if certain)"},
})

ADJUDICATION_OUTPUT = _obj({
    "decisions": {"type": "array", "items": _obj({
        "entry_id": _str(),
        "decision": {"type": "string", "enum": ["CONFIRMED", "BOTH_VALID_DIFFERENT_CONDITIONS", "CORRECTED",
                                                "SUPERSEDED", "AMBIGUOUS_SOURCE", "UNSUPPORTED",
                                                "DUPLICATE"]},
        "preferred": {"type": "string", "enum": ["A", "B", "BOTH", "NEITHER"]},
        "statement": _str("the faithful statement the evidence supports (required unless UNSUPPORTED/DUPLICATE)"),
        "modality": {"type": "string", "enum": list(MODALITIES)},
        "quote": _str("verbatim supporting quote from the excerpt"),
        "duplicate_of": _str("for DUPLICATE: the entry id it duplicates, else ''"),
        "reason": _str("the evidence-based reason, one or two sentences")})},
})

REVIEW_OUTPUT = _obj({
    "issues": {"type": "array", "items": _obj({
        "type": {"type": "string", "enum": ["MISSING_MANDATORY", "WRONG_MODALITY", "CHANGED_CONDITION",
                                            "UNSUPPORTED_CONSEQUENCE", "CONTRADICTORY", "WRONG_FIGURE",
                                            "MISCLASSIFIED", "MISLEADING_ANALYSIS", "DUPLICATION", "VERBOSITY",
                                            "OTHER"]},
        "report": {"type": "string", "enum": ["FAST", "FULL", "BOTH"]},
        "entry_ids": _strs("register entry ids involved"),
        "category": {"type": "string", "enum": list(CATEGORIES),
                     "description": "for MISSING_MANDATORY: the category of the missing provision"},
        "description": _str(),
        "corrected_statement": _str("evidence-backed replacement wording, or '' if none"),
        "modality": {"type": "string", "enum": list(MODALITIES),
                     "description": "modal force of the corrected or missing provision"},
        "quote": _str("verbatim source text supporting the correction, or ''")})},
})

_CITED = _obj({"text": _str(), "entry_ids": _strs("register entry ids that state this (at least one)")})

ANALYSIS_OUTPUT = _obj({
    "title": _CITED,
    "buyer": _CITED,
    "reference": _CITED,
    "summary": {"type": "array", "items": _CITED,
                "description": "two to four sentences: what is procured, from whom, the decisive conditions"},
    "points": {"type": "array", "items": _obj({
        "heading": _str("short heading"),
        "analysis": _str("the analytical point: a consequence, dependency, risk or interaction between "
                         "provisions, no stronger than the cited entries"),
        "entry_ids": _strs("register entry ids the point rests on (at least one)"),
        "kind": {"type": "string", "enum": ["INFERENCE", "RISK", "DEPENDENCY", "OPEN_QUESTION"]}})},
})
