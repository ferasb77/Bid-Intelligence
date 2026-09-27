"""
check_coverage.py -- CHECK-2A: Requirement & Evaluation Coverage Adjudication.

The first ADJUDICATION layer of CHECK. For every canonical BUYER object
(canonical requirement or scoped evaluation criterion) it answers:

    What did the buyer ask for, where should the response/evidence exist,
    what did the bidder actually provide, and is that response sufficiently
    addressed?

and every answer is traceable to the buyer-side canonical source (canonical
id + verbatim wording + source refs) AND to bidder-side CHECK-1 evidence ids.

    canonical buyer package      (full_analysis.CanonicalPackage, frozen)
  + submission evidence registry (submission_package.SubmissionPackage, CHECK-1)
  + scope gate                   (classify_assurance_scope -- deterministic)
  + candidate retrieval          (CHECK-1 map_requirement_to_submission + section/role expansion)
  + deterministic adjudication   (forms, pricing workbook, declaration tables, page limits)
  + bounded model adjudication   (semantic items only, batched by domain, <= target calls)
  + evidence assurance           (fail-closed evidence-id / role / consistency validation)
  = CheckCoverageResult          (compute-and-return; nothing is persisted here)

Hard boundaries (constitutional, not stylistic):

  * Pure core: no Streamlit, no database, no Storage I/O. The only side
    effect is the optional bounded model call, which is injected
    (`adjudicate_fn`) or made through the SAME provider helper MA-1 uses
    (`full_analysis._call_model` -> config.execute_messages_create).
  * Buyer truth is INPUT ONLY -- never mutated, never paraphrased away
    (buyer wording is carried verbatim; a model-quoted "requested element"
    that is not literally present in the buyer wording is dropped).
  * No numeric proposal score, no percentage completeness, no predicted
    evaluator mark, no strengths/weaknesses, no recommendations, no rewrite
    suggestions. A buyer-stated weight / threshold is preserved verbatim as
    buyer metadata and never converted into a judgement.
  * Model output may cite ONLY the short evidence ids issued to THAT call
    (section_drafting.evidence_id_registry's PE# ids over CHECK-1 evidence);
    invented ids, buyer-source ids (CE#/REQ-*/CRIT-*), cross-bid ids and
    wrong-artifact ids (where the artifact role is material) are rejected
    and recorded -- fail closed.
  * A NOT_ADDRESSED verdict requires (a) a response-bearing scope, (b) a
    recorded search basis over the WHOLE package, and (c) survival of
    CHECK-1's `screen_absence_claim` artifact-presence guard -- so the
    historical "Price Form / Submission Form / multi-party form missing
    because only the narrative was read" error class cannot recur.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

import canonical_procurement as cp
import section_drafting as sd
import submission_package as sp

CHECK2A_CONTRACT_VERSION = "check-2a.1.0"

# ═══════════════════════════════════════════════════════════════════════
# 1. Closed vocabularies
# ═══════════════════════════════════════════════════════════════════════

STATUS_ADDRESSED = "ADDRESSED"
STATUS_PARTIALLY_ADDRESSED = "PARTIALLY_ADDRESSED"
STATUS_NOT_ADDRESSED = "NOT_ADDRESSED"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"
STATUS_NOT_VERIFIABLE = "NOT_VERIFIABLE_FROM_FILES"
STATUS_HUMAN_REVIEW = "HUMAN_REVIEW_REQUIRED"
STATUSES = (STATUS_ADDRESSED, STATUS_PARTIALLY_ADDRESSED, STATUS_NOT_ADDRESSED,
            STATUS_NOT_APPLICABLE, STATUS_NOT_VERIFIABLE, STATUS_HUMAN_REVIEW)
#: Statuses a MODEL may return. NOT_APPLICABLE is a scope decision, made
#: deterministically by the scope gate -- never by the model.
MODEL_STATUSES = (STATUS_ADDRESSED, STATUS_PARTIALLY_ADDRESSED, STATUS_NOT_ADDRESSED,
                  STATUS_NOT_VERIFIABLE, STATUS_HUMAN_REVIEW)

SCOPE_SUBMISSION_RESPONSE = "SUBMISSION_RESPONSE_REQUIRED"
SCOPE_SUBMISSION_EVIDENCE = "SUBMISSION_EVIDENCE_REQUIRED"
SCOPE_EVALUATION_RESPONSE = "EVALUATION_RESPONSE"
SCOPE_PORTAL_NATIVE = "PORTAL_NATIVE"
SCOPE_POST_AWARD = "POST_AWARD_OBLIGATION"
SCOPE_BUYER_PROCESS = "BUYER_PROCESS"
SCOPE_INFORMATIONAL = "INFORMATIONAL"
#: The buyer's own document states that the acknowledgement / declaration
#: is made BY THE ACT OF SUBMITTING ("By submitting a proposal ..., the
#: proponent acknowledges ..."): no separate written response is required,
#: so the files cannot be deficient for lacking one.
SCOPE_DEEMED_BY_SUBMISSION = "DEEMED_BY_SUBMISSION"
SCOPE_NOT_APPLICABLE = "NOT_APPLICABLE"
SCOPE_HUMAN_REVIEW = "HUMAN_REVIEW_REQUIRED"
ASSURANCE_SCOPES = (SCOPE_SUBMISSION_RESPONSE, SCOPE_SUBMISSION_EVIDENCE, SCOPE_EVALUATION_RESPONSE,
                    SCOPE_PORTAL_NATIVE, SCOPE_POST_AWARD, SCOPE_BUYER_PROCESS, SCOPE_INFORMATIONAL,
                    SCOPE_DEEMED_BY_SUBMISSION, SCOPE_NOT_APPLICABLE, SCOPE_HUMAN_REVIEW)
#: Only these scopes are ever judged ADDRESSED / PARTIAL / NOT_ADDRESSED.
CHECKABLE_SCOPES = frozenset({SCOPE_SUBMISSION_RESPONSE, SCOPE_SUBMISSION_EVIDENCE, SCOPE_EVALUATION_RESPONSE})
#: Scopes that are not proposal obligations at all (never a proposal gap).
EXCLUDED_SCOPES = frozenset({SCOPE_POST_AWARD, SCOPE_BUYER_PROCESS, SCOPE_INFORMATIONAL,
                             SCOPE_DEEMED_BY_SUBMISSION, SCOPE_NOT_APPLICABLE})

METHOD_SCOPE_GATE = "SCOPE_GATE"
METHOD_DETERMINISTIC = "DETERMINISTIC"
METHOD_MODEL = "MODEL"
METHOD_DERIVED = "DERIVED_FROM_LINKED_REQUIREMENTS"

OBJECT_REQUIREMENT = "CANONICAL_REQUIREMENT"
OBJECT_CRITERION = "SCOPED_EVALUATION_CRITERION"

ELEMENT_ADDRESSED = "ADDRESSED"
ELEMENT_PARTIAL = "PARTIAL"
ELEMENT_ABSENT = "ABSENT"
ELEMENT_NOT_VERIFIABLE = "NOT_VERIFIABLE"
ELEMENT_HUMAN_REVIEW = "HUMAN_REVIEW"
ELEMENT_NON_OBLIGATION = "NON_OBLIGATION"
MODEL_ELEMENT_COVERAGES = (ELEMENT_ADDRESSED, ELEMENT_PARTIAL, ELEMENT_ABSENT, ELEMENT_NOT_VERIFIABLE)

# Evidence-id rejection reasons (validation metadata, never silently dropped).
REJECT_NOT_ISSUED = "NOT_ISSUED_TO_THIS_CALL"
REJECT_BUYER_SOURCE = "BUYER_SOURCE_ID_NOT_BIDDER_EVIDENCE"
REJECT_CROSS_BID = "CROSS_BID_OR_UNKNOWN_EVIDENCE"
REJECT_WRONG_ARTIFACT = "WRONG_ARTIFACT_ROLE"

# ═══════════════════════════════════════════════════════════════════════
# 2. Call / size discipline
# ═══════════════════════════════════════════════════════════════════════

#: Preferred ceiling for a full-package run; batches are merged to fit it.
MODEL_CALL_TARGET = 10
#: Absolute ceiling. A plan needing more raises BEFORE any call is made.
MODEL_CALL_HARD_CEILING = 12
MAX_OBJECTS_PER_BATCH = 6
MAX_EVIDENCE_PER_OBJECT = 70
MAX_EVIDENCE_PER_BATCH = 110
MAX_SECTION_TEXT_CHARS = 900
MAX_OTHER_ITEM_CHARS = 400
MAX_ELEMENTS_PER_OBJECT = 10
MODEL_MAX_OUTPUT_TOKENS = 8000
MODEL_RETRY_ATTEMPTS = 0          # explicit: no automatic retries (MA-1 precedent)


#: CHECK-2B observation events emitted by run_check_coverage(on_event=...).
EVENT_PLAN_READY = "PLAN_READY"
EVENT_BATCH_STARTED = "SEMANTIC_BATCH_STARTED"
EVENT_BATCH_COMPLETED = "SEMANTIC_BATCH_COMPLETED"

# ── CHECK-2B: component versions (inputs to the durable-run fingerprint) ──
# Bump the one whose logic changes; every persisted CHECK run fingerprint
# covering it is then invalidated (a changed prompt / model / call bound is
# ALSO covered automatically by check_run_service's contract digest).
SCOPE_GATE_VERSION = "check-2a-scope-1"
RETRIEVAL_VERSION = "check-2a-retrieval-1"
DETERMINISTIC_RULE_VERSION = "check-2a-deterministic-1"
ADJUDICATION_VERSION = "check-2a-adjudication-1"
PROMPT_SCHEMA_VERSION = "check-2a-prompt-1"


class BatchPlanningError(RuntimeError):
    """The model-adjudication plan would exceed the hard call ceiling. Raised
    before any provider call is made -- redesign the batching instead."""


class ModelCallBudgetExceeded(RuntimeError):
    """Defensive: a run tried to exceed its own call ceiling."""


# ═══════════════════════════════════════════════════════════════════════
# 3. Buyer objects (buyer truth, section 4)
# ═══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class BuyerObject:
    """One canonical buyer object, carried VERBATIM. Requirements take their
    full (unclipped) Fast Analysis description when the canonical package's
    clipped text provably came from it; criteria keep label, weight(s),
    threshold and their own source refs exactly as the buyer stated them."""

    object_id: str
    object_type: str
    wording: str
    label: Optional[str] = None
    category: Optional[str] = None
    semantic_type: Optional[str] = None
    applicability: Optional[str] = None
    applicability_condition: Optional[str] = None
    weight: Optional[str] = None
    weight_variants: tuple = ()
    threshold: Optional[str] = None
    source_docs: tuple = ()
    source_refs: tuple = ()
    authoritative_source: Optional[str] = None
    requirement_origin: Optional[str] = None
    required_form: Optional[str] = None
    response_prompt: Optional[str] = None

    def requirement_dict(self) -> dict:
        """The CHECK-1 requirement shape (derive_expected_evidence /
        map_requirement_to_submission read description/category/req_id)."""
        return {"req_id": self.object_id, "canonical_id": self.object_id, "description": self.wording,
                "category": self.category or "", "source_doc": (self.source_docs or (None,))[0],
                "required_form": self.required_form}

    def to_dict(self) -> dict:
        return {"object_id": self.object_id, "object_type": self.object_type, "wording": self.wording,
                "label": self.label, "category": self.category, "semantic_type": self.semantic_type,
                "applicability": self.applicability, "applicability_condition": self.applicability_condition,
                "weight": self.weight, "weight_variants": list(self.weight_variants),
                "threshold": self.threshold, "source_docs": list(self.source_docs),
                "source_refs": list(self.source_refs), "authoritative_source": self.authoritative_source,
                "requirement_origin": self.requirement_origin, "required_form": self.required_form,
                "response_prompt": self.response_prompt}


def _clip_like_canonical(text) -> str:
    body = re.sub(r"\s+", " ", str(text or "")).strip()
    return body if len(body) <= 600 else body[:600].rstrip() + " ..."


def buyer_objects_from_canonical_package(package, raw_requirements: Optional[list] = None) -> list[BuyerObject]:
    """Every canonical requirement (REQ-*) and scoped evaluation criterion
    (CRIT-*) of a full_analysis.CanonicalPackage, in canonical order.

    `raw_requirements` (the SAME FastAnalysisResult.requirements the package
    was built from) is used only to recover the full, unclipped buyer wording
    and the raw `category` the canonical projection does not carry
    (CHECK-1.1 finding). It is used for REQ-<i> only when the canonical
    clipped description is provably the clip of raw[i]'s description --
    otherwise the canonical text is kept (never guessed)."""
    raws = list(raw_requirements or [])
    out: list[BuyerObject] = []
    for i, req in enumerate(package.requirements):
        cid = req["canonical_id"]
        idx = int(cid.split("-", 1)[1]) if cid.startswith("REQ-") and cid[4:].isdigit() else i
        raw = raws[idx] if idx < len(raws) and isinstance(raws[idx], dict) else {}
        wording = req.get("description") or ""
        category = req.get("category")
        if raw and _clip_like_canonical(raw.get("description")) == wording:
            wording = raw.get("description") or wording
            category = category or raw.get("category")
        out.append(BuyerObject(
            object_id=cid, object_type=OBJECT_REQUIREMENT, wording=(wording or "").strip(),
            category=category, semantic_type=req.get("semantic_type"),
            applicability=req.get("applicability"), applicability_condition=req.get("applicability_condition"),
            source_docs=tuple(req.get("source_docs") or ()), source_refs=tuple(req.get("source_refs") or ()),
            requirement_origin=req.get("requirement_origin"), required_form=req.get("required_form")))
    for crit in package.scoped_criteria:
        label = crit.get("criterion") or ""
        prompt = crit.get("response_prompt") or None
        out.append(BuyerObject(
            object_id=crit["canonical_id"], object_type=OBJECT_CRITERION,
            wording=label if not prompt else f"{label}: {prompt}", label=label,
            category=crit.get("category_scope") or None, weight=crit.get("weight"),
            weight_variants=tuple(crit.get("weight_variants") or ()), threshold=crit.get("minimum_score"),
            source_docs=tuple(d for d in [crit.get("authoritative_source")] if d),
            source_refs=tuple(crit.get("source_refs") or ()), authoritative_source=crit.get("authoritative_source"),
            response_prompt=prompt))
    return out


# ═══════════════════════════════════════════════════════════════════════
# 4. Submission-assurance scope gate (section 3)
# ═══════════════════════════════════════════════════════════════════════
#
# Buyer-agnostic procurement phrasing only. Nothing here names a buyer, a
# solicitation, an appendix letter or a form title.

_PROPONENT_NOUN = (r"(?:proponents?|bidders?|respondents?|tenderers?|applicants?|you|your\s+(?:firm|organi[sz]ation|"
                   r"proposal|company)|the\s+proponent|each\s+proposal|proposals?|submissions?)")
_OBLIGATION_MODAL = (r"(?:must|shall|should|(?:is|are)\s+required\s+to|(?:is|are)\s+to|will\s+be\s+required\s+to|"
                     r"needs?\s+to|requires?\s+(?:the\s+)?complet\w+)")
_PROPONENT_OBLIGATION_RE = re.compile(rf"\b{_PROPONENT_NOUN}\b[^.;:]{{0,160}}?\b{_OBLIGATION_MODAL}\b", re.IGNORECASE)
_IMPERATIVE_RE = re.compile(
    r"(?:^|[.:;]\s*|\)\s+)(?:provide|describe|identify|outline|complete|submit|include|attach|confirm|demonstrate|"
    r"list|explain|detail|indicate|state|acknowledge|sign|delete|replace|insert|enter|fill\s+in)\b", re.IGNORECASE)
_PASSIVE_INSTRUCTION_RE = re.compile(
    r"\b(?:is|are|shall|must|should)\s+(?:to\s+)?be\s+(?:provided|submitted|completed|included|based|captured|made|"
    r"entered|itemi[sz]ed|attached|signed)\b|\brequires?\s+(?:the\s+)?complet\w+\s+of\b", re.IGNORECASE)
_NAMED_FORM_RE = re.compile(r"\b(?:[A-Z][\w'’&-]*\s+){1,5}Form\b")
_ARTIFACT_WORD_RE = re.compile(
    r"\b(?:pric(?:e|ing)\s+(?:form|table|schedule|sheet|workbook)|spreadsheet|workbook|excel|"
    r"appendix\s+[A-Z0-9]{1,3}\b|submission\s+form|zip\s+(?:folder|file)|yellow\s+cells?|input\s+cells?)",
    re.IGNORECASE)
_CONTRACT_PARTY_RE = re.compile(
    r"\b(?:the\s+)?(?:consultant|contractor|supplier|vendor|service\s+provider|successful\s+(?:proponent|bidder|"
    r"respondent)|selected\s+proponent)(?:'s|’s)?\b", re.IGNORECASE)
_PERFORMANCE_RE = re.compile(
    r"\b(?:is|are)\s+(?:expected\s+|required\s+)?to\s+be\s+(?:delivered|performed|conducted|carried\s+out)\b"
    r"|\bduring\s+the\s+(?:term|contract)\b|\bpursuant\s+to\s+the\s+agreement\b|\bupon\s+request\b"
    r"|\bafter\s+(?:contract\s+)?award\b|\bresponse\s+time(?:frame)?s?\b", re.IGNORECASE)
_BUYER_SUBJECT_RE = re.compile(
    r"\b(?:the\s+)?(?:city|buyer|owner|purchaser|client|crown|province|agency|authority|department|ministry|"
    r"municipality|region|county|town|district|bank|commission|university|board|government)(?:'s|’s)?\s+"
    r"(?:will|may|shall|is|does|reserves|intends|has|preferred|requires?|expects?|would|anticipates?)\b",
    re.IGNORECASE)
_EVALUATION_PROCESS_RE = re.compile(
    r"\b(?:total\s+weighted\s+(?:cost|score)|(?:pricing|price|scoring)[\s-]+(?:calculation\s+)?formula|"
    r"weighted\s+at\s+\d|will\s+be\s+(?:evaluated|scored|assessed|considered)|scoring\s+will\s+be|"
    r"highest[\s-]rated|negotiations?\b)", re.IGNORECASE)
_DEFINITION_RE = re.compile(
    r"\b(?:refers?\s+to|means|is\s+defined\s+as|(?:is|are)\s+considered|target\s+audience|"
    r"expected\s+(?:time\s+)?duration)\b", re.IGNORECASE)
_PAGE_LIMIT_RE = re.compile(
    r"\b(?:maximum|max\.?|not\s+exceed|limit(?:ed)?\s+(?:of|to)|no\s+more\s+than)\b[^.;]{0,60}?\(?(\d{1,3})\)?\s*"
    r"(?:single[\s-]sided\s+)?pages?\b|\(?(\d{1,3})\)?\s*[-\s]?page\s+limit\b", re.IGNORECASE)
_DEEMING_RE = re.compile(
    r"\bby\s+submitting\s+(?:a|an|its|their|our|this|the)?\s*(?:proposal|bid|tender|response|submission|offer|"
    r"quotation)\b[^.]{0,200}?\b(?:acknowledg|confirm|declar|agree|represent|warrant|certif)\w*", re.IGNORECASE)


def _norm_text(text) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[‘’“”\"'`]", "", str(text or "")).lower()).strip()


def _deeming_positions(buyer_documents) -> dict:
    """{document name: normalized text, first deeming-statement offset}
    for every buyer document containing a "By submitting ..., the proponent
    acknowledges/confirms/declares" statement."""
    out = {}
    for entry in (buyer_documents or []):
        if not (isinstance(entry, (tuple, list)) and len(entry) == 2):
            continue
        name, text = entry
        body = _norm_text(text)
        m = _DEEMING_RE.search(body)
        if m:
            out[name] = (body, m.start())
    return out


def _is_deemed_by_submission(obj: BuyerObject, deeming: dict) -> Optional[str]:
    """The buyer deeming sentence that covers this requirement, when the
    requirement's own source excerpt sits AFTER a deeming statement in one
    of its own source documents; else None."""
    for doc in obj.source_docs:
        entry = deeming.get(doc)
        if not entry:
            continue
        body, first = entry
        for ref in obj.source_refs:
            excerpt = _norm_text((ref or {}).get("excerpt") if isinstance(ref, dict) else "")
            if len(excerpt) < 20:
                continue
            pos = body.find(excerpt[:120])
            if pos > first:
                m = _DEEMING_RE.search(body)
                return body[m.start():m.end()] if m else "by submitting a proposal"
    return None


def _has_instruction(text: str) -> bool:
    return bool(_PROPONENT_OBLIGATION_RE.search(text) or _IMPERATIVE_RE.search(text)
                or _PASSIVE_INSTRUCTION_RE.search(text))


def _artifact_anchored(text: str) -> bool:
    return bool((_NAMED_FORM_RE.search(text) or _ARTIFACT_WORD_RE.search(text)) and _has_instruction(text))


@dataclass(frozen=True)
class ScopeDecision:
    scope: str
    basis: str

    def to_dict(self) -> dict:
        return {"scope": self.scope, "basis": self.basis}


def classify_assurance_scope(obj: BuyerObject, *, expected: Optional[sp.ExpectedEvidence] = None,
                             deeming: Optional[dict] = None) -> ScopeDecision:
    """Deterministic: is this canonical buyer object something the SUBMITTED
    FILES are expected to answer? Only SUBMISSION_RESPONSE_REQUIRED /
    SUBMISSION_EVIDENCE_REQUIRED / EVALUATION_RESPONSE are ever judged
    ADDRESSED / PARTIAL / NOT_ADDRESSED; a post-award obligation, buyer
    process, informational item or deemed acknowledgement can never become a
    proposal gap. Precedence is fixed and documented inline."""
    text = (obj.wording or "").strip()
    if obj.object_type == OBJECT_CRITERION:
        return ScopeDecision(SCOPE_EVALUATION_RESPONSE, "scoped evaluation criterion")
    if not text:
        return ScopeDecision(SCOPE_HUMAN_REVIEW, "canonical requirement carries no buyer wording; nothing to check")
    expected = expected or sp.derive_expected_evidence(obj.requirement_dict())
    if expected.portal_native and not expected.roles:
        return ScopeDecision(SCOPE_PORTAL_NATIVE, expected.rationale)
    anchored = _artifact_anchored(text)
    if not anchored:
        deemed = _is_deemed_by_submission(obj, deeming or {})
        if deemed:
            return ScopeDecision(SCOPE_DEEMED_BY_SUBMISSION,
                                 f"buyer source states the proponent's acknowledgement is made by submission: "
                                 f"'{deemed}'")
    if anchored:
        return ScopeDecision(SCOPE_SUBMISSION_EVIDENCE,
                             "instruction to the proponent about a named submission artifact / form")
    if (obj.category or "").strip().lower() == "rated":
        return ScopeDecision(SCOPE_EVALUATION_RESPONSE, "rated requirement (evaluated proposal content)")
    if _PAGE_LIMIT_RE.search(text):
        return ScopeDecision(SCOPE_SUBMISSION_RESPONSE, "submission format constraint (page limit)")
    proponent_obligation = bool(_PROPONENT_OBLIGATION_RE.search(text) or _IMPERATIVE_RE.search(text))
    if _PERFORMANCE_RE.search(text) or sp._POST_AWARD_RE.search(text):
        return ScopeDecision(SCOPE_POST_AWARD, "contract-performance obligation (post-award delivery / service terms)")
    if proponent_obligation:
        return ScopeDecision(SCOPE_SUBMISSION_RESPONSE, "obligation addressed to the proponent")
    if _EVALUATION_PROCESS_RE.search(text) or _BUYER_SUBJECT_RE.search(text):
        return ScopeDecision(SCOPE_BUYER_PROCESS, "describes the buyer's own process / evaluation / intentions")
    if _CONTRACT_PARTY_RE.search(text):
        return ScopeDecision(SCOPE_POST_AWARD, "obligation of the contracted supplier (post-award), not of the proposal")
    if _DEFINITION_RE.search(text):
        return ScopeDecision(SCOPE_INFORMATIONAL, "definition / background information")
    if (obj.category or "").strip().lower() in ("mandatory", "rated"):
        return ScopeDecision(SCOPE_HUMAN_REVIEW, "mandatory buyer object whose obligation form is not recognizable")
    return ScopeDecision(SCOPE_INFORMATIONAL, "no obligation addressed to the proponent")


# ═══════════════════════════════════════════════════════════════════════
# 5. Result contract (section 9)
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class CheckAdjudication:
    buyer_object_id: str
    buyer_object_type: str
    assurance_scope: str
    scope_basis: str
    status: str
    buyer_expectation: str
    buyer_label: Optional[str] = None
    buyer_category: Optional[str] = None
    expected_evidence_roles: tuple = ()
    evidence_ids: tuple = ()
    evidence_summary: str = ""
    addressed_elements: list = field(default_factory=list)
    missing_elements: list = field(default_factory=list)
    unverifiable_elements: list = field(default_factory=list)
    ambiguity_or_review_reason: Optional[str] = None
    buyer_weight: Optional[str] = None
    buyer_weight_variants: tuple = ()
    buyer_threshold: Optional[str] = None
    deterministic_or_model: str = METHOD_SCOPE_GATE
    batch_id: Optional[str] = None
    linked_requirement_ids: tuple = ()
    search_basis: dict = field(default_factory=dict)
    validation: dict = field(default_factory=dict)
    source_provenance: dict = field(default_factory=dict)
    applicability: Optional[str] = None
    applicability_condition: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "buyer_object_id": self.buyer_object_id, "buyer_object_type": self.buyer_object_type,
            "assurance_scope": self.assurance_scope, "scope_basis": self.scope_basis, "status": self.status,
            "buyer_expectation": self.buyer_expectation, "buyer_label": self.buyer_label,
            "buyer_category": self.buyer_category,
            "expected_evidence_roles": list(self.expected_evidence_roles), "evidence_ids": list(self.evidence_ids),
            "evidence_summary": self.evidence_summary, "addressed_elements": list(self.addressed_elements),
            "missing_elements": list(self.missing_elements), "unverifiable_elements": list(self.unverifiable_elements),
            "ambiguity_or_review_reason": self.ambiguity_or_review_reason, "buyer_weight": self.buyer_weight,
            "buyer_weight_variants": list(self.buyer_weight_variants), "buyer_threshold": self.buyer_threshold,
            "deterministic_or_model": self.deterministic_or_model, "batch_id": self.batch_id,
            "linked_requirement_ids": list(self.linked_requirement_ids), "search_basis": self.search_basis,
            "validation": self.validation, "source_provenance": self.source_provenance,
            "applicability": self.applicability, "applicability_condition": self.applicability_condition,
        }


@dataclass
class CheckCoverageResult:
    bid_id: Optional[int]
    contract_version: str
    buyer_package_digest: Optional[str]
    submission_package_digest: Optional[str]
    adjudications: list
    provider_calls: int
    batches: list
    telemetry: list = field(default_factory=list)

    def by_id(self) -> dict:
        return {a.buyer_object_id: a for a in self.adjudications}

    def status_counts(self) -> dict:
        counts = {s: 0 for s in STATUSES}
        for a in self.adjudications:
            counts[a.status] += 1
        return counts

    def scope_counts(self) -> dict:
        counts = {s: 0 for s in ASSURANCE_SCOPES}
        for a in self.adjudications:
            counts[a.assurance_scope] += 1
        return counts

    def method_counts(self) -> dict:
        counts: dict = {}
        for a in self.adjudications:
            counts[a.deterministic_or_model] = counts.get(a.deterministic_or_model, 0) + 1
        return counts

    def to_dict(self) -> dict:
        return {"bid_id": self.bid_id, "contract_version": self.contract_version,
                "buyer_package_digest": self.buyer_package_digest,
                "submission_package_digest": self.submission_package_digest,
                "object_counts": {"total": len(self.adjudications),
                                  "requirements": sum(1 for a in self.adjudications
                                                      if a.buyer_object_type == OBJECT_REQUIREMENT),
                                  "criteria": sum(1 for a in self.adjudications
                                                  if a.buyer_object_type == OBJECT_CRITERION)},
                "status_counts": self.status_counts(), "scope_counts": self.scope_counts(),
                "method_counts": self.method_counts(), "provider_calls": self.provider_calls,
                "batches": self.batches, "adjudications": [a.to_dict() for a in self.adjudications]}


# ═══════════════════════════════════════════════════════════════════════
# 6. Evidence helpers
# ═══════════════════════════════════════════════════════════════════════

_FURNITURE_RE = re.compile(r"^\s*p\s*a\s*g\s*e\s+\d+(?:\s*\|\s*\d+)?\s*$|\.{5,}\s*\d+\s*$|^\s*\d{1,3}\s*$", re.IGNORECASE)


def _is_furniture(item: sp.EvidenceItem) -> bool:
    return bool(_FURNITURE_RE.search(item.content or "")) or len((item.content or "").strip()) < 3


def _ordered_items(package: sp.SubmissionPackage, doc_id: str) -> list:
    """Registry insertion order == CHECK-1 reading order (persisted rows are
    reloaded ordered by id, i.e. insertion order)."""
    return package.registry.for_document(doc_id)


def _section_root(item: sp.EvidenceItem) -> str:
    loc = item.location or {}
    path = loc.get("section_path") or []
    return str(path[0] if path else (loc.get("section_title") or loc.get("sheet") or ""))


def _primary_docs(package: sp.SubmissionPackage, role: str) -> list:
    return [d for d in package.documents_with_roles([role], include_secondary=False) if d.readable]


def _item_serves_role(item: sp.EvidenceItem, doc: sp.SubmissionDocument, role: str) -> bool:
    """Evidence counts for a MATERIAL artifact role only when it comes from a
    document whose PRIMARY role is that role, or from an EMBEDDED section of
    that role (e.g. a 'PART 6 -- PRICING' section of a technical proposal)."""
    if doc.document_role == role:
        return True
    if role not in doc.all_roles:
        return False
    heading = " ".join((item.location or {}).get("section_path") or [])
    return any(r == role and rx.search(heading) for r, rx in sp._EMBEDDED_ROLE_HEADING_RULES)


_MATERIAL_ROLE_CATEGORIES = {
    sp.EVIDENCE_CATEGORY_PRICING: sp.ROLE_PRICING_FORM,
    sp.EVIDENCE_CATEGORY_DECLARATION: sp.ROLE_SUBMISSION_FORM,
    sp.EVIDENCE_CATEGORY_MULTI_PARTY: sp.ROLE_MULTI_PARTY_FORM,
}


def material_role(expected: Optional[sp.ExpectedEvidence]) -> Optional[str]:
    """The artifact role that is MATERIAL to an object (its evidence must come
    from that artifact), or None when the evidence location is flexible."""
    if expected is None or expected.flexible or not expected.roles:
        return None
    role = _MATERIAL_ROLE_CATEGORIES.get(expected.evidence_category)
    return role if role and role in expected.roles else None


def _content_key(item: sp.EvidenceItem) -> str:
    return _norm_text(item.content)[:400]


def distinct_evidence(ids: Iterable[str], package: sp.SubmissionPackage) -> list[str]:
    """Order-preserving de-duplication: a repeated id, or a second item whose
    normalized content is identical to one already kept (a FORM_FIELD
    restating its own SECTION_TEXT line, a repeated heading), never counts
    twice -- duplicate evidence can never inflate coverage."""
    seen_ids, seen_content, out = set(), set(), []
    for eid in ids:
        if eid in seen_ids or eid not in package.registry:
            continue
        seen_ids.add(eid)
        key = _content_key(package.registry.get(eid, bid_id=package.bid_id))
        if key and key in seen_content:
            continue
        seen_content.add(key)
        out.append(eid)
    return out


def _search_basis(expected: Optional[sp.ExpectedEvidence], mapping: Optional[sp.RequirementEvidenceMapping],
                  package: sp.SubmissionPackage, considered: Iterable[str] = ()) -> dict:
    return {
        "expected_roles": list(expected.roles) if expected else [],
        "evidence_category": expected.evidence_category if expected else None,
        "location_basis": expected.location_basis if expected else None,
        "artifact_status": mapping.artifact_status if mapping else None,
        "expected_role_documents": list(mapping.expected_role_documents) if mapping else [],
        "documents_searched": [{"submission_document_id": d.submission_document_id, "filename": d.filename,
                                "document_role": d.document_role, "secondary_roles": list(d.role.secondary_roles)}
                               for d in package.member_documents()],
        "evidence_items_in_registry": len(package.registry),
        "candidates_considered": list(dict.fromkeys(considered))[:MAX_EVIDENCE_PER_OBJECT],
        "retrieval": "CHECK-1 lexical/role candidates + mapped proposal section + expected-role artifact",
    }


def _provenance(obj: BuyerObject) -> dict:
    return {"source_docs": list(obj.source_docs), "source_refs": list(obj.source_refs)[:4],
            "authoritative_source": obj.authoritative_source, "requirement_origin": obj.requirement_origin,
            "required_form": obj.required_form}


def _base_adjudication(obj: BuyerObject, scope: ScopeDecision, status: str, method: str, *,
                       expected=None, mapping=None, package=None, considered=()) -> CheckAdjudication:
    return CheckAdjudication(
        buyer_object_id=obj.object_id, buyer_object_type=obj.object_type, assurance_scope=scope.scope,
        scope_basis=scope.basis, status=status, buyer_expectation=obj.wording, buyer_label=obj.label,
        buyer_category=obj.category, expected_evidence_roles=tuple(expected.roles) if expected else (),
        buyer_weight=obj.weight, buyer_weight_variants=tuple(obj.weight_variants), buyer_threshold=obj.threshold,
        deterministic_or_model=method,
        search_basis=_search_basis(expected, mapping, package, considered) if package is not None else {},
        source_provenance=_provenance(obj), applicability=obj.applicability,
        applicability_condition=obj.applicability_condition)


# ═══════════════════════════════════════════════════════════════════════
# 7. Deterministic element checkers (section 6)
# ═══════════════════════════════════════════════════════════════════════
#
# A requirement is adjudicated deterministically only when EVERY sentence is
# handled by an unambiguous checker below (or is a non-obligation sentence).
# Anything else goes to the bounded model. Presence already established by
# CHECK-1 is never re-proved with a model call.

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;!?])\s+(?=\S)")
_PERMISSION_RE = re.compile(r"\b(?:acceptable|is\s+permitted|may\s+be|optional|does\s+not\s+count|"
                            r"is\s+considered|are\s+considered|at\s+(?:its|their)\s+discretion|may\s+include|"
                            r"not\s+limited\s+to)\b", re.IGNORECASE)
#: A pricing ASSUMPTION the buyer prescribes for building a price ("For the
#: purposes of the Pricing Form, pricing shall be based on ..."). A completed
#: lump-sum price never discloses its own calculation basis.
_PRICING_BASIS_RE = re.compile(
    r"\bfor\s+the\s+purposes?\s+of\s+the\s+pric\w*\s+form\b|\bpric\w*\s+(?:shall|must|is\s+to|are\s+to|will|should)\s+"
    r"be\s+based\s+on\b", re.IGNORECASE)
#: A legal / registration STATUS the proponent must hold, with no
#: instruction to put proof of it in the submission.
_STATUS_ELIGIBILITY_RE = re.compile(
    r"\b(?:must|shall)\s+be\s+(?:a\s+)?(?:registered|licen[cs]ed|incorporated|in\s+good\s+standing|"
    r"authori[sz]ed\s+to\s+(?:carry\s+on|do)\s+business)\b", re.IGNORECASE)
_PROOF_REQUEST_RE = re.compile(r"\b(?:provide|submit|attach|include|enclose)\b[^.;]{0,40}\b(?:proof|evidence|copy|"
                               r"copies|certificate|documentation)\b", re.IGNORECASE)
_PRICING_ARTIFACT_RE = re.compile(r"\bpric(?:e|es|ing)\b|\blump\s+sum\b|\bcosts?\b|\bexcel\b|\bspreadsheet\b|"
                                  r"\bworkbook\b|\byellow\s+cells?\b", re.IGNORECASE)
_PRICING_COMPLETION_RE = re.compile(r"\b(?:complet\w*|provided?|captured|enter(?:ed)?|fill(?:ed)?|include[ds]?|"
                                    r"submit(?:ted)?)\b", re.IGNORECASE)
#: Anything asking HOW a price was built (basis, inclusions, firmness, rate
#: form, exclusions) is semantic -- the workbook's presence cannot prove it.
_PRICING_RESIDUE_RE = re.compile(
    r"\b(?:based\s+(?:only\s+)?on|only|inclusive|include\s+all|all\s+applicable|firm\s+(?:for|price)|flat\s+rate|"
    r"ranges?|hours?|hourly|not\s+(?:include|asked|be\s+considered)|exclud\w*|delete|replace|per\s+participant|"
    r"annual|multiple|breakdown|duties|taxes)\b", re.IGNORECASE)
_DECLARATION_TABLE_RE = re.compile(r"\btable\s+in\s+(?:the\s+|our\s+|your\s+)?(?:[A-Z][\w-]*\s+){0,3}Submission\s+Form\b"
                                   r"|\b(?:field|section)\s+(?:of|in)\s+(?:the\s+)?Submission\s+Form\b", re.IGNORECASE)
_EXPLICIT_NIL_RE = re.compile(r"\b(?:not\s+applicable|n/?a|none|nil|no\s+conflicts?|not\s+any)\b", re.IGNORECASE)
_SIGNATORY_LABEL_RE = re.compile(r"^(?:per|signature|signed(?:\s+by)?|authori[sz]ed\s+(?:signatory|signature)|"
                                 r"name\s+of\s+signatory|signing\s+officer)$", re.IGNORECASE)
_LEGAL_NAME_LABEL_RE = re.compile(r"\blegal\s+name\b", re.IGNORECASE)
_TEAM_SECTION_RE = re.compile(r"\bidentity\s+of\s+(?:the\s+)?(?:team\s+)?members\b|\bmembers\s+of\s+the\s+"
                              r"(?:multi[\s-]*party\s+)?team\b|\b(?:consortium|joint\s+venture)\s+members\b",
                              re.IGNORECASE)
_NAME_LINE_RE = re.compile(r"^[A-Z][A-Za-z0-9&.,'’\- ]{1,70}$")
_NON_NAME_RE = re.compile(r"\b(?:repeat|legal\s+name|date|title|name|each|above|below|form|confirm|team\s+member)\b",
                          re.IGNORECASE)
_GENERIC_TERMS = sp._terms("table submission form appendix proponent proponents must provide complete confirm "
                           "including include set out our your any all such there that except those")


@dataclass
class Element:
    element: str
    coverage: str
    evidence_ids: list = field(default_factory=list)
    note: str = ""
    source_object_id: Optional[str] = None

    def to_dict(self) -> dict:
        out = {"element": self.element, "coverage": self.coverage, "evidence_ids": list(self.evidence_ids),
               "note": self.note}
        if self.source_object_id:
            out["source_object_id"] = self.source_object_id
        return out


def _sheet_rows(items: list) -> list:
    return [i for i in items if i.kind == sp.EVIDENCE_KIND_SHEET_ROW]


def _row_input_cells(items: list, sheet, row) -> list:
    return [i for i in items if i.kind == sp.EVIDENCE_KIND_SHEET_CELL and (i.location or {}).get("sheet") == sheet
            and (i.location or {}).get("row") == row and (i.structured_value or {}).get("is_input_cell")]


def _pricing_completion_element(package: sp.SubmissionPackage, sentence: str,
                                absence_permitted: bool) -> list:
    """Pricing workbook presence + input-cell completion + stated sub-elements
    (lump-sum rows, travel row, every scenario/item row). Never judges price
    level or competitiveness."""
    docs = _primary_docs(package, sp.ROLE_PRICING_FORM)
    if not docs:
        embedded = [d for d in package.documents_with_roles([sp.ROLE_PRICING_FORM]) if d.readable]
        if embedded:
            return [Element(sentence, ELEMENT_HUMAN_REVIEW, note="pricing appears only as an embedded section of "
                            + ", ".join(d.filename for d in embedded) + "; no standalone pricing form")]
        return [Element(sentence, ELEMENT_ABSENT if absence_permitted else ELEMENT_NOT_VERIFIABLE,
                        note="no pricing form artifact in the submitted package")]
    out = []
    for doc in docs:
        items = _ordered_items(package, doc.submission_document_id)
        inputs = [i for i in items if i.kind == sp.EVIDENCE_KIND_SHEET_CELL
                  and (i.structured_value or {}).get("is_input_cell")]
        if not inputs:
            inputs = [i for i in items if i.kind == sp.EVIDENCE_KIND_SHEET_CELL
                      and isinstance((i.structured_value or {}).get("value"), (int, float))
                      and re.search(r"pric|cost|rate|fee|amount", str((i.structured_value or {}).get("column_header")
                                                                         or ""), re.IGNORECASE)]
        completed = [i for i in inputs if (i.structured_value or {}).get("completed") is True]
        blank = [i for i in inputs if (i.structured_value or {}).get("completed") is False]
        cells = ", ".join(str((i.location or {}).get("cell")) for i in completed)
        if not inputs:
            out.append(Element(sentence, ELEMENT_HUMAN_REVIEW, note=f"{doc.filename}: no pricing input/value cells "
                               f"could be identified"))
            continue
        if completed and not blank:
            out.append(Element(f"pricing form completed ({doc.filename})", ELEMENT_ADDRESSED,
                               [i.evidence_id for i in completed],
                               f"all {len(completed)} pricing input cell(s) completed: {cells}"))
        elif completed:
            out.append(Element(f"pricing form completed ({doc.filename})", ELEMENT_PARTIAL,
                               [i.evidence_id for i in completed],
                               "blank input cell(s): " + ", ".join(str((i.location or {}).get("cell")) for i in blank)))
        else:
            out.append(Element(f"pricing form completed ({doc.filename})", ELEMENT_ABSENT, [],
                               "the pricing form's input cells are blank"))
        rows = _sheet_rows(items)
        low = sentence.lower()
        if re.search(r"\blump\s+sum\b|\bLS\b", sentence):
            ls_rows = [r for r in rows if re.search(r"\bLS\b|lump\s*sum", r.content, re.IGNORECASE)]
            ls_cells = [c for r in ls_rows for c in _row_input_cells(items, (r.location or {}).get("sheet"),
                                                                     (r.location or {}).get("row"))]
            ok = ls_rows and all((c.structured_value or {}).get("completed") for c in ls_cells) and ls_cells
            out.append(Element("pricing in lump-sum format", ELEMENT_ADDRESSED if ok else ELEMENT_HUMAN_REVIEW,
                               [r.evidence_id for r in ls_rows] + [c.evidence_id for c in ls_cells],
                               f"{len(ls_rows)} lump-sum row(s) with completed price cell(s)" if ok else
                               "lump-sum rows could not be confirmed from the workbook structure"))
        if "travel" in low:
            tr_rows = [r for r in rows if "travel" in r.content.lower()]
            tr_cells = [c for r in tr_rows for c in _row_input_cells(items, (r.location or {}).get("sheet"),
                                                                     (r.location or {}).get("row"))]
            ok = tr_rows and tr_cells and all((c.structured_value or {}).get("completed") for c in tr_cells)
            out.append(Element("travel costs captured in the pricing form",
                               ELEMENT_ADDRESSED if ok else ELEMENT_HUMAN_REVIEW,
                               [r.evidence_id for r in tr_rows] + [c.evidence_id for c in tr_cells],
                               "travel row has a completed price cell" if ok else
                               "travel row / price cell not confirmable from the workbook structure"))
        if re.search(r"\beach\s+(?:cohort|scenario|item)\b|\bsample\s+scenarios?\b|\bscenarios?\b", low):
            item_rows = [r for r in rows if ((r.structured_value or {}).get("cells") or [{}])[0].get("value")
                         not in (None, "") and isinstance(((r.structured_value or {}).get("cells") or [{}])[0]
                                                          .get("value"), (int, float))]
            row_cells = {r.evidence_id: _row_input_cells(items, (r.location or {}).get("sheet"),
                                                         (r.location or {}).get("row")) for r in item_rows}
            ok = item_rows and all(cs and all((c.structured_value or {}).get("completed") for c in cs)
                                   for cs in row_cells.values())
            out.append(Element("every priced scenario / item row completed",
                               ELEMENT_ADDRESSED if ok else ELEMENT_HUMAN_REVIEW,
                               [r.evidence_id for r in item_rows] + [c.evidence_id for cs in row_cells.values()
                                                                     for c in cs],
                               f"{len(item_rows)} item row(s), each with a completed price cell" if ok else
                               "scenario/item rows not confirmable from the workbook structure"))
    return out


def _pricing_basis_element(package: sp.SubmissionPackage, sentence: str, absence_permitted: bool) -> list:
    """A buyer-prescribed pricing ASSUMPTION: whether the completed price was
    built on it cannot be read from the price itself."""
    done = [e for e in _pricing_completion_element(package, "complete the pricing form", absence_permitted)
            if e.coverage == ELEMENT_ADDRESSED]
    if not done:
        return [Element(sentence, ELEMENT_HUMAN_REVIEW,
                        note="pricing assumption prescribed, and no completed pricing form was identified")]
    return [Element(sentence, ELEMENT_NOT_VERIFIABLE, done[0].evidence_ids,
                    "a completed price is present, but a lump-sum price does not disclose whether it was built on "
                    "the prescribed pricing assumption")]


def _page_limit_element(package: sp.SubmissionPackage, sentence: str, limit: int) -> Element:
    docs = _primary_docs(package, sp.ROLE_TECHNICAL_PROPOSAL)
    if not docs:
        return Element(sentence, ELEMENT_HUMAN_REVIEW, note="no technical proposal artifact to measure")
    counts = [(d, d.page_count) for d in docs]
    if any(pc is None for _, pc in counts):
        return Element(sentence, ELEMENT_NOT_VERIFIABLE,
                       note="page count not determinable from the submitted format (no page geometry)")
    ev = []
    for d, pc in counts:
        last = [i for i in _ordered_items(package, d.submission_document_id) if (i.location or {}).get("page") == pc]
        if last:
            ev.append(last[-1].evidence_id)
    total = sum(pc for _, pc in counts)
    if total <= limit:
        return Element(f"page limit of {limit} pages", ELEMENT_ADDRESSED, ev,
                       f"technical proposal is {total} page(s) in total (<= {limit}), before any permitted exclusions")
    return Element(f"page limit of {limit} pages", ELEMENT_HUMAN_REVIEW, ev,
                   f"technical proposal is {total} pages; whether permitted exclusions bring it within {limit} "
                   f"cannot be determined deterministically")


def _declaration_table_element(package: sp.SubmissionPackage, sentence: str) -> Optional[Element]:
    """A named table/field of the submission form carries an EXPLICIT value
    (a completed row, or an explicit 'Not Applicable' / 'None')."""
    docs = _primary_docs(package, sp.ROLE_SUBMISSION_FORM)
    if not docs:
        return None
    subject = sp._terms(sentence) - _GENERIC_TERMS
    for doc in docs:
        items = _ordered_items(package, doc.submission_document_id)
        best, best_i, best_score = None, None, 0
        for idx, it in enumerate(items):
            if it.kind != sp.EVIDENCE_KIND_SECTION_TEXT or len(it.content or "") > 160:
                continue
            score = len(subject & sp._terms(it.content))
            if score > best_score:
                best, best_i, best_score = it, idx, score
        if best is None or best_score < (2 if len(subject) > 2 else 1):
            continue
        rows = []
        for it in items[best_i + 1:]:
            if it.kind == sp.EVIDENCE_KIND_TABLE_ROW:
                rows.append(it)
            elif rows:
                break
        if not rows:
            continue
        explicit = [r for r in rows if (r.structured_value or {}).get("completed") or _EXPLICIT_NIL_RE.search(r.content)]
        nil = all(_EXPLICIT_NIL_RE.search(r.content) for r in explicit) if explicit else False
        if explicit:
            return Element(f"'{best.content.strip()}' table completed in {doc.filename}", ELEMENT_ADDRESSED,
                           [best.evidence_id] + [r.evidence_id for r in explicit],
                           "table carries an explicit 'not applicable' / nil entry" if nil
                           else f"{len(explicit)} completed table row(s)")
        return Element(f"'{best.content.strip()}' table in {doc.filename}", ELEMENT_HUMAN_REVIEW,
                       [best.evidence_id], "table present but blank; the files cannot distinguish a nil declaration "
                                           "from an omission")
    return None


def _form_role(form_name: str) -> Optional[str]:
    for role in sp._filename_roles(form_name):
        if role in (sp.ROLE_MULTI_PARTY_FORM, sp.ROLE_SUBMISSION_FORM, sp.ROLE_PRICING_FORM):
            return role
    return None


def _required_form_elements(package: sp.SubmissionPackage, obj: BuyerObject, sentence: str, form: str,
                            role: str, absence_permitted: bool) -> list:
    docs = _primary_docs(package, role)
    if not docs:
        other = [d for d in package.documents_with_roles([role])]
        if other:
            return [Element(f"{form} included", ELEMENT_HUMAN_REVIEW,
                            note=f"no standalone {role}; the role appears only embedded in "
                                 + ", ".join(d.filename for d in other))]
        if obj.applicability_condition:
            return [Element(f"{form} included", ELEMENT_HUMAN_REVIEW,
                            note="obligation is conditional ('" + obj.applicability_condition + "') and the package "
                                 "shows no artifact of this role; whether the condition applies needs human review")]
        return [Element(f"{form} included", ELEMENT_ABSENT if absence_permitted else ELEMENT_NOT_VERIFIABLE,
                        note=f"no {role} artifact in the submitted package")]
    out = []
    doc = docs[0]
    items = _ordered_items(package, doc.submission_document_id)
    title = next((i for i in items if i.kind == sp.EVIDENCE_KIND_SECTION_TEXT and not _is_furniture(i)), None)
    out.append(Element(f"{form} included", ELEMENT_ADDRESSED, [title.evidence_id] if title else [],
                       f"submitted as '{doc.filename}' (primary role {role})"))
    completed = [i for i in items if i.kind in (sp.EVIDENCE_KIND_FORM_FIELD, sp.EVIDENCE_KIND_CHECKBOX)
                 and (i.structured_value or {}).get("completed")]
    out.append(Element(f"{form} completed", ELEMENT_ADDRESSED if completed else ELEMENT_ABSENT,
                       [i.evidence_id for i in completed][:12],
                       f"{len(completed)} completed field(s)" if completed else "no completed field found"))
    if obj.applicability_condition and role == sp.ROLE_MULTI_PARTY_FORM:
        out.append(Element("applicability condition", ELEMENT_NON_OBLIGATION, [],
                           "condition treated as met: the bidder itself submitted a multi-party form"))
    if role == sp.ROLE_MULTI_PARTY_FORM:
        parties, party_ev = [], []
        lead = None
        for sub in _primary_docs(package, sp.ROLE_SUBMISSION_FORM):
            for it in _ordered_items(package, sub.submission_document_id):
                sv = it.structured_value or {}
                if it.kind == sp.EVIDENCE_KIND_FORM_FIELD and _LEGAL_NAME_LABEL_RE.search(str(sv.get("label") or "")) \
                        and sv.get("value"):
                    lead = str(sv["value"]).strip()
                    party_ev.append(it.evidence_id)
                    break
            if lead:
                break
        if lead:
            hit = next((i for i in items if lead.lower() in (i.content or "").lower()), None)
            if hit:
                parties.append(lead)
                party_ev.append(hit.evidence_id)
        for it in items:
            if it.kind != sp.EVIDENCE_KIND_SECTION_TEXT:
                continue
            sec = str((it.location or {}).get("section_title") or "")
            text = (it.content or "").strip()
            if _TEAM_SECTION_RE.search(sec) and _NAME_LINE_RE.match(text) and not _NON_NAME_RE.search(text) \
                    and not text.endswith((".", ":")) and text not in parties:
                parties.append(text)
                party_ev.append(it.evidence_id)
        out.append(Element("all team members identified", ELEMENT_ADDRESSED if len(parties) >= 2 else
                           ELEMENT_HUMAN_REVIEW, party_ev,
                           ("parties identified: " + "; ".join(parties)) if parties else
                           "party names could not be read deterministically"))
        if re.search(r"\bsign", sentence, re.IGNORECASE):
            signers = [i for i in items if i.kind == sp.EVIDENCE_KIND_FORM_FIELD
                       and _SIGNATORY_LABEL_RE.match(str((i.structured_value or {}).get("label") or "").strip())
                       and (i.structured_value or {}).get("completed")]
            sections = {(i.location or {}).get("section_id") for i in signers}
            ok = len(parties) >= 2 and len(sections) >= len(parties)
            out.append(Element("executed (signed) by all team members", ELEMENT_ADDRESSED if ok else ELEMENT_HUMAN_REVIEW,
                               [i.evidence_id for i in signers],
                               (f"{len(signers)} named signatory block(s) completed across {len(sections)} party "
                                f"execution section(s); signature images themselves are not verifiable from "
                                f"extracted text") if signers else "no completed signatory block found"))
    elif re.search(r"\bsign", sentence, re.IGNORECASE):
        signers = [i for i in items if i.kind == sp.EVIDENCE_KIND_FORM_FIELD
                   and _SIGNATORY_LABEL_RE.match(str((i.structured_value or {}).get("label") or "").strip())
                   and (i.structured_value or {}).get("completed")]
        out.append(Element(f"{form} signed", ELEMENT_ADDRESSED if signers else ELEMENT_HUMAN_REVIEW,
                           [i.evidence_id for i in signers],
                           "named signatory block completed" if signers else
                           "no completed signatory block found in extracted text"))
    return out


def _sentence_elements(obj: BuyerObject, sentence: str, package: sp.SubmissionPackage,
                       absence_permitted: bool) -> Optional[list]:
    """Elements for ONE sentence, or None when no deterministic checker can
    handle it unambiguously (-> the whole object goes to the model)."""
    s = sentence.strip()
    if not s:
        return []
    m = _PAGE_LIMIT_RE.search(s)
    if m and _has_instruction(s) or (m and re.search(r"\blength\b|\bpage\s+limit\b", s, re.IGNORECASE)):
        return [_page_limit_element(package, s, int(m.group(1) or m.group(2)))]
    if _DECLARATION_TABLE_RE.search(s):
        el = _declaration_table_element(package, s)
        return [el] if el is not None else None
    fm = _NAMED_FORM_RE.search(s)
    if fm and _has_instruction(s) and re.search(r"\b(?:include|submit|complete|attach|provide)\b", s, re.IGNORECASE):
        form = re.sub(r"\s+", " ", fm.group(0)).strip()
        role = _form_role(form)
        if role in (sp.ROLE_MULTI_PARTY_FORM, sp.ROLE_SUBMISSION_FORM):
            return _required_form_elements(package, obj, s, form, role, absence_permitted)
    if _PRICING_ARTIFACT_RE.search(s) and _PRICING_COMPLETION_RE.search(s) and not _PRICING_RESIDUE_RE.search(s) \
            and (_ARTIFACT_WORD_RE.search(s) or _NAMED_FORM_RE.search(s) or re.search(r"\blump\s+sum\b", s, re.I)):
        return _pricing_completion_element(package, s, absence_permitted)
    if _PRICING_BASIS_RE.search(s):
        return _pricing_basis_element(package, s, absence_permitted)
    if _STATUS_ELIGIBILITY_RE.search(s) and not _PROOF_REQUEST_RE.search(s):
        return [Element(s, ELEMENT_NOT_VERIFIABLE,
                        note="a legal / registration status of the proponent; the requirement does not ask for "
                             "proof in the submission, so the submitted files cannot establish it")]
    # "... that may be required" is not an obligation; "must" / "shall" /
    # "is|are required" are
    has_obligation = bool(_PROPONENT_OBLIGATION_RE.search(s) or _IMPERATIVE_RE.search(s) or
                          re.search(r"\b(?:must|shall)\b|\b(?:is|are)\s+required\b", s, re.IGNORECASE))
    if has_obligation and _CONTRACT_PARTY_RE.match(s) and not _PROPONENT_OBLIGATION_RE.search(s):
        return [Element(s, ELEMENT_NON_OBLIGATION,
                        note="obligation of the contracted supplier after award (post-award), not of the proposal")]
    if not has_obligation and (_PERMISSION_RE.search(s) or "=" in s or not _PRICING_RESIDUE_RE.search(s)):
        return [Element(s, ELEMENT_NON_OBLIGATION, note="no obligation stated in this sentence")]
    if sp._PORTAL_NATIVE_RE.search(s) and not _PRICING_ARTIFACT_RE.search(s):
        return [Element(s, ELEMENT_NOT_VERIFIABLE,
                        note="completed through the buyer's e-procurement portal; uploaded files cannot show it")]
    return None


def _aggregate_elements(elements: list) -> str:
    live = [e for e in elements if e.coverage != ELEMENT_NON_OBLIGATION]
    if not live:
        return STATUS_HUMAN_REVIEW
    kinds = [e.coverage for e in live]
    if ELEMENT_HUMAN_REVIEW in kinds:
        return STATUS_HUMAN_REVIEW
    addressed = kinds.count(ELEMENT_ADDRESSED)
    partial = kinds.count(ELEMENT_PARTIAL)
    absent = kinds.count(ELEMENT_ABSENT)
    unverifiable = kinds.count(ELEMENT_NOT_VERIFIABLE)
    if addressed and not partial and not absent:
        return STATUS_ADDRESSED
    if not addressed and not partial and not absent and unverifiable:
        return STATUS_NOT_VERIFIABLE
    if not addressed and not partial and absent:
        return STATUS_NOT_ADDRESSED
    return STATUS_PARTIALLY_ADDRESSED


def _apply_elements(adj: CheckAdjudication, elements: list, package: sp.SubmissionPackage) -> None:
    adj.addressed_elements = [e.to_dict() for e in elements if e.coverage == ELEMENT_ADDRESSED]
    adj.missing_elements = [e.to_dict() for e in elements if e.coverage in (ELEMENT_PARTIAL, ELEMENT_ABSENT)]
    adj.unverifiable_elements = [e.to_dict() for e in elements if e.coverage == ELEMENT_NOT_VERIFIABLE]
    review = [e for e in elements if e.coverage == ELEMENT_HUMAN_REVIEW]
    ids = [eid for e in elements if e.coverage in (ELEMENT_ADDRESSED, ELEMENT_PARTIAL, ELEMENT_HUMAN_REVIEW,
                                                   ELEMENT_NOT_VERIFIABLE)
           for eid in e.evidence_ids]
    adj.evidence_ids = tuple(distinct_evidence(ids, package))
    notes = []
    if review:
        notes.append("; ".join(f"{e.element}: {e.note}" for e in review))
    if adj.unverifiable_elements and adj.status == STATUS_ADDRESSED:
        notes.append("file-verifiable elements addressed; not verifiable from files: "
                     + "; ".join(e["element"] for e in adj.unverifiable_elements))
    elif adj.unverifiable_elements:
        notes.append("; ".join(f"{e['element']}: {e['note']}" for e in adj.unverifiable_elements))
    adj.ambiguity_or_review_reason = " | ".join(notes) or None


def deterministic_adjudication(obj: BuyerObject, scope: ScopeDecision, expected: sp.ExpectedEvidence,
                               mapping: sp.RequirementEvidenceMapping,
                               package: sp.SubmissionPackage) -> Optional[CheckAdjudication]:
    """A complete deterministic adjudication, or None when any sentence needs
    semantic comparison. Every element carries its own evidence ids."""
    sentences: list = []
    carry = ""
    for s in (x for x in _SENTENCE_SPLIT_RE.split(obj.wording or "") if x.strip()):
        s = (carry + " " + s).strip() if carry else s
        # a short lead-in fragment ("For the purposes of the Pricing Form;")
        # belongs to the clause it introduces
        if len(s.split()) < 9 and s.rstrip().endswith((";", ":")):
            carry = s
            continue
        carry = ""
        sentences.append(s)
    if carry:
        sentences.append(carry)
    absence_permitted = mapping.absence_claim_permitted
    elements: list = []
    for s in sentences:
        got = _sentence_elements(obj, s, package, absence_permitted)
        if got is None:
            return None
        elements.extend(got)
    if not any(e.coverage != ELEMENT_NON_OBLIGATION for e in elements):
        return None
    status = _aggregate_elements(elements)
    adj = _base_adjudication(obj, scope, status, METHOD_DETERMINISTIC, expected=expected, mapping=mapping,
                             package=package, considered=[c.evidence_id for c in mapping.candidates])
    _apply_elements(adj, elements, package)
    adj.evidence_summary = "; ".join(e.note for e in elements if e.coverage == ELEMENT_ADDRESSED and e.note)[:600]
    if status == STATUS_NOT_ADDRESSED and not absence_permitted:
        adj.status = STATUS_HUMAN_REVIEW
        adj.validation["downgrades"] = ["NOT_ADDRESSED -> HUMAN_REVIEW_REQUIRED: CHECK-1 does not permit an absence "
                                        "claim for this object (artifact_status=" + mapping.artifact_status + ")"]
    return adj


# ── Deterministic evaluation-criterion handling ────────────────────────

_PRICING_LABEL_RE = re.compile(r"\bpric(?:e|es|ing)\b|\bcost\b|\bfees?\b|\brates?\b", re.IGNORECASE)
_CURRENCY_RE = re.compile(r"[$€£]\s?\d|\b(?:CAD|USD)\s?\d", re.IGNORECASE)
_ITEM_LABEL_RE = re.compile(r"^\s*item\s+(\d{1,3})\b", re.IGNORECASE)


def is_pricing_criterion(obj: BuyerObject) -> bool:
    if _PRICING_LABEL_RE.search(obj.label or ""):
        return True
    excerpts = " ".join(str((r or {}).get("excerpt") or "") for r in obj.source_refs if isinstance(r, dict))
    # A numbered line item whose own buyer source row carries a currency
    # amount is a row of the buyer's pricing schedule.
    return bool(_ITEM_LABEL_RE.match(obj.label or "") and _CURRENCY_RE.search(excerpts))


def pricing_criterion_adjudication(obj: BuyerObject, scope: ScopeDecision,
                                   package: sp.SubmissionPackage) -> CheckAdjudication:
    """Pricing evaluation criteria: is the required PRICING RESPONSE content
    present in the real pricing workbook? Price level / competitiveness is
    deliberately never judged (CHECK-2A scope)."""
    expected = sp.ExpectedEvidence((sp.ROLE_PRICING_FORM,), sp.EVIDENCE_CATEGORY_PRICING, sp.LOCATION_BASIS_INFERRED,
                                   False, False, "pricing evaluation criterion -- evidenced by the pricing form")
    mapping_like = sp.map_requirement_to_submission({"req_id": obj.object_id, "description": obj.wording,
                                                    "category": "Financial"}, package)
    docs = _primary_docs(package, sp.ROLE_PRICING_FORM)
    m = _ITEM_LABEL_RE.match(obj.label or "")
    elements: list = []
    if not docs:
        elements = _pricing_completion_element(package, obj.wording, mapping_like.absence_claim_permitted)
    elif m:
        n = int(m.group(1))
        for doc in docs:
            items = _ordered_items(package, doc.submission_document_id)
            row = next((r for r in _sheet_rows(items)
                        if ((r.structured_value or {}).get("cells") or [{}])[0].get("value") == n), None)
            if row is None:
                elements.append(Element(obj.label or obj.wording, ELEMENT_HUMAN_REVIEW,
                                        note=f"no row for item {n} identified in {doc.filename}"))
                continue
            cells = _row_input_cells(items, (row.location or {}).get("sheet"), (row.location or {}).get("row"))
            done = [c for c in cells if (c.structured_value or {}).get("completed")]
            cov = ELEMENT_ADDRESSED if cells and len(done) == len(cells) else (
                ELEMENT_PARTIAL if done else ELEMENT_ABSENT if cells else ELEMENT_HUMAN_REVIEW)
            elements.append(Element(f"price entered for item {n}", cov, [row.evidence_id] + [c.evidence_id for c in done],
                                    f"{doc.filename}: row {(row.location or {}).get('row')} price cell(s) "
                                    + ", ".join(str((c.location or {}).get("cell")) for c in done)
                                    if done else "price cell blank or not identified"))
    else:
        elements = _pricing_completion_element(package, "complete the pricing form", mapping_like.absence_claim_permitted)
    status = _aggregate_elements(elements)
    adj = _base_adjudication(obj, scope, status, METHOD_DETERMINISTIC, expected=expected, mapping=mapping_like,
                             package=package, considered=[c.evidence_id for c in mapping_like.candidates])
    _apply_elements(adj, elements, package)
    adj.evidence_summary = ("; ".join(e.note for e in elements if e.note) +
                            " (coverage of required pricing content only; price level is not assessed)")[:600]
    return adj


# ═══════════════════════════════════════════════════════════════════════
# 8. Criterion -> canonical rated requirement linking (sections 11 / 12)
# ═══════════════════════════════════════════════════════════════════════

_REQ_NUMBER_RE = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){0,3})\s")
_LOCATION_WORDS = sp._terms("appendix evaluation section page asks rfp criteria criterion subsection weighting "
                            "weight carries")


def _criterion_numbers(obj: BuyerObject) -> set:
    label = obj.label or ""
    nums = set()
    sub = re.search(r"\bsubsection\s+(\d{1,2}(?:\.\d{1,2})+)", label, re.IGNORECASE)
    if sub:
        return {sub.group(1)}
    m = re.match(r"^\s*(?:evaluation\s+criteri(?:on|a)\s+)?(\d{1,2}(?:\.\d{1,2}){0,3})\b", label, re.IGNORECASE)
    if m:
        nums.add(m.group(1))
    core = re.escape(re.split(r"\s*[,–—-]\s*", label.strip())[-1].strip()) if label.strip() else None
    if core:
        # "Item 3 Travel Expenses": an ITEM number is a pricing-row number,
        # never an evaluation-criterion section number.
        rx = re.compile(r"(?<!item\s)(?<![\d.])(\d{1,2}(?:\.\d{1,2}){0,3})\s*[.)|–—-]?\s*\|?\s*" + core,
                        re.IGNORECASE)
        for ref in obj.source_refs:
            for mm in rx.finditer(str((ref or {}).get("excerpt") or "") if isinstance(ref, dict) else ""):
                nums.add(mm.group(1))
    return nums


def _label_segments(label: str) -> list:
    segs = [s.strip(" .:") for s in re.split(r"\s*[,–—:]\s*|\s+-\s+", label or "") if s.strip()]
    out = [label.strip()] if label and label.strip() else []
    for s in segs:
        s2 = re.sub(r"^(?:evaluation\s+criteri(?:on|a)\s+\d+|subsection\s+[\d.]+)\s*", "", s, flags=re.I).strip()
        if len(s2.split()) >= 2 and s2 not in out:
            out.append(s2)
    return out


def link_criterion_to_requirements(obj: BuyerObject, candidates: list) -> list:
    """Canonical requirements that carry THIS criterion's buyer ask (its
    response prompt), by three deterministic, buyer-agnostic signals:
    the criterion label (or a >=2-word segment of it) literally present in
    the requirement wording; the criterion's own number heading the
    requirement's numbering ("2" -> "2.1 ...", "2.2 ..."); or a buyer source
    excerpt of the criterion (minus location words) contained >= 60% in the
    requirement wording. `candidates` are (BuyerObject, ScopeDecision)."""
    nums = _criterion_numbers(obj)
    segments = [s.lower() for s in _label_segments(obj.label or "")]
    excerpts = []
    label_terms = sp._terms(obj.label or "")
    for ref in obj.source_refs:
        t = sp._terms(str((ref or {}).get("excerpt") or "") if isinstance(ref, dict) else "")
        t = t - _LOCATION_WORDS - label_terms
        if len(t) >= 6:
            excerpts.append(t)
    linked = []
    for req, scope in candidates:
        text = (req.wording or "")
        low = text.lower()
        hit = any(seg and seg in low for seg in segments)
        if not hit and nums:
            m = _REQ_NUMBER_RE.match(text)
            hit = bool(m and any(m.group(1) == n or m.group(1).startswith(n + ".") for n in nums))
        if not hit and excerpts:
            rt = sp._terms(text)
            hit = any(len(e & rt) / len(e) >= 0.6 for e in excerpts)
        if hit:
            linked.append(req.object_id)
    return linked


def derived_criterion_adjudication(obj: BuyerObject, linked: list, by_id: dict,
                                   package: sp.SubmissionPackage) -> CheckAdjudication:
    """A criterion whose buyer ask IS its linked requirement prompt(s): an
    INDEPENDENT adjudication record (own weight / threshold / label) derived
    deterministically from the linked requirements' element-level results,
    sharing -- not duplicating -- their evidence ids."""
    subs = [by_id[i] for i in linked if i in by_id]
    live = [a for a in subs if a.assurance_scope not in EXCLUDED_SCOPES]
    statuses = [a.status for a in live]
    all_portal = bool(live) and all(a.assurance_scope == SCOPE_PORTAL_NATIVE for a in live)
    scope = ScopeDecision(SCOPE_PORTAL_NATIVE if all_portal else SCOPE_EVALUATION_RESPONSE,
                          "scoped evaluation criterion; buyer ask carried by " + ", ".join(linked))
    if not live:
        status = STATUS_HUMAN_REVIEW
    elif STATUS_HUMAN_REVIEW in statuses:
        status = STATUS_HUMAN_REVIEW
    elif all(s == STATUS_NOT_VERIFIABLE for s in statuses):
        status = STATUS_NOT_VERIFIABLE
    elif all(s == STATUS_ADDRESSED for s in statuses):
        status = STATUS_ADDRESSED
    elif all(s == STATUS_NOT_ADDRESSED for s in statuses):
        status = STATUS_NOT_ADDRESSED
    else:
        status = STATUS_PARTIALLY_ADDRESSED
    adj = _base_adjudication(obj, scope, status, METHOD_DERIVED, package=package)
    adj.linked_requirement_ids = tuple(linked)
    adj.buyer_expectation = obj.wording + "\n" + "\n".join(f"[{a.buyer_object_id}] {a.buyer_expectation}" for a in subs)
    roles = []
    for a in subs:
        roles.extend(r for r in a.expected_evidence_roles if r not in roles)
    adj.expected_evidence_roles = tuple(roles)
    for a in subs:
        for e in a.addressed_elements:
            adj.addressed_elements.append(dict(e, source_object_id=a.buyer_object_id))
        for e in a.missing_elements:
            adj.missing_elements.append(dict(e, source_object_id=a.buyer_object_id))
        for e in a.unverifiable_elements:
            adj.unverifiable_elements.append(dict(e, source_object_id=a.buyer_object_id))
    adj.evidence_ids = tuple(distinct_evidence([e for a in subs for e in a.evidence_ids], package))
    adj.evidence_summary = " | ".join(f"[{a.buyer_object_id}] {a.evidence_summary}" for a in subs
                                      if a.evidence_summary)[:900]
    reasons = [f"[{a.buyer_object_id}] {a.ambiguity_or_review_reason}" for a in subs if a.ambiguity_or_review_reason]
    if not live:
        reasons.insert(0, "every linked buyer requirement is out of submission scope; nothing to adjudicate")
    notes = []
    if len(set(obj.weight_variants)) > 1:
        notes.append("buyer sources state differing weights for this criterion: " + ", ".join(obj.weight_variants)
                     + " (buyer metadata, not resolved by CHECK)")
    adj.ambiguity_or_review_reason = " | ".join(notes + reasons) or None
    sub_basis = {a.buyer_object_id: a.search_basis.get("candidates_considered", []) for a in subs}
    adj.search_basis["linked_requirement_candidates"] = sub_basis
    adj.validation = {"derived_from": {a.buyer_object_id: a.status for a in subs}}
    return adj


# ═══════════════════════════════════════════════════════════════════════
# 9. Candidate retrieval for model adjudication (section 5)
# ═══════════════════════════════════════════════════════════════════════

_HEADING_HINT_RE = re.compile(r"^\s*((?:\d{1,2}(?:\.\d{1,2}){0,3}\s+)?[^:.;]{3,80}?)\s*(?:\(\d{1,3}\s*%\)\s*)?[:–—-]\s")


def heading_hints(obj: BuyerObject, criterion_labels: Iterable[str] = ()) -> list[str]:
    """Buyer-side heading phrases a proposal typically mirrors: the labels of
    every evaluation criterion that links to this object (the buyer's own
    headings for this ask) plus the object's own leading heading
    ("3.1 Understanding of the Services: ...")."""
    hints = [str(x) for x in criterion_labels if x]
    m = _HEADING_HINT_RE.match(obj.wording or "")
    if m:
        hints.append(m.group(1).strip())
    if obj.label:
        hints.append(obj.label)
    return list(dict.fromkeys(h for h in hints if h))


def anchor_section(package: sp.SubmissionPackage, hints: list[str]) -> Optional[tuple]:
    """(submission_document_id, root section label) of the technical-proposal
    section whose headings (root or any sub-heading) best match the buyer's
    heading hints -- heading match, the SAME priority CHECK-1's
    map_evaluation_criteria_to_sections gives headings over body text.
    None when no heading matches at least half of some hint's terms."""
    hint_terms = [t for t in (sp._terms(h) - _LOCATION_WORDS for h in hints) if t]
    if not hint_terms:
        return None
    best, best_score = None, 0.0
    for d in package.documents_with_roles([sp.ROLE_TECHNICAL_PROPOSAL], include_secondary=False):
        by_id = {s.section_id: s for s in d.sections}
        roots: dict = {}
        for s in d.sections:
            top = s
            while top.parent_id and top.parent_id in by_id:
                top = by_id[top.parent_id]
            title_terms = sp._terms(s.title)
            per_hint = [len(h & title_terms) / len(h) for h in hint_terms]
            cur = roots.setdefault(top.label, [0.0] * len(hint_terms))
            roots[top.label] = [max(a, b) for a, b in zip(cur, per_hint)]
        for root, scores in roots.items():
            score = sum(x for x in scores if x >= 0.5)
            if score > best_score:
                best, best_score = (d.submission_document_id, root), score
    return best


def _derived_duplicate(item: sp.EvidenceItem, page_texts: dict) -> bool:
    """A FORM_FIELD line that merely restates part of a SECTION_TEXT block on
    the same page (the 'Name: X' line inside a bio paragraph)."""
    if item.kind != sp.EVIDENCE_KIND_FORM_FIELD or (item.structured_value or {}).get("source") == "pdf_form_table":
        return False
    key = (item.submission_document_id, (item.location or {}).get("page"))
    body = _norm_text(item.content)
    return any(body and body in t and body != t for t in page_texts.get(key, ()))


def object_evidence(obj: BuyerObject, expected: sp.ExpectedEvidence, mapping: sp.RequirementEvidenceMapping,
                    package: sp.SubmissionPackage, *, anchor: Optional[tuple] = None,
                    limit: int = MAX_EVIDENCE_PER_OBJECT) -> list[str]:
    """Deterministically ranked, bounded bidder evidence for ONE object:
      1. the whole expected-role artifact when the role is material (a
         pricing workbook / submission form / multi-party form is read in
         full, never sampled);
      2. the mapped proposal section: the heading-matched `anchor` section,
         else the section the CHECK-1 candidates concentrate in -- in reading
         order;
      3. the remaining CHECK-1 in-role candidates, then other-artifact
         candidates (a relevant passage in an unexpected artifact is kept).
    Page furniture, derived restatements and content-duplicates are dropped.
    Never the whole registry."""
    page_texts: dict = {}
    for it in package.registry:
        if it.kind == sp.EVIDENCE_KIND_SECTION_TEXT:
            page_texts.setdefault((it.submission_document_id, (it.location or {}).get("page")), []).append(
                _norm_text(it.content))

    def _keep(i) -> bool:
        return not _is_furniture(i) and not _derived_duplicate(i, page_texts)

    def _substantive(i) -> bool:
        # a mapped section's line fragments (a wrapped table cell such as
        # "influence, personal") add tokens, not evidence; structured items
        # (form fields, table rows, sheet cells) are always kept
        return _keep(i) and (i.kind != sp.EVIDENCE_KIND_SECTION_TEXT or len((i.content or "").strip()) >= 40)

    out: list = []
    role = material_role(expected)
    if role:
        for d in _primary_docs(package, role):
            out.extend(i.evidence_id for i in _ordered_items(package, d.submission_document_id) if _keep(i))
    if anchor is None and not role:
        weights: dict = {}
        for rank, c in enumerate(mapping.candidates):
            it = package.registry.get(c.evidence_id, bid_id=package.bid_id)
            key = (it.submission_document_id, _section_root(it))
            weights[key] = weights.get(key, 0.0) + c.score + 1.0 / (rank + 1)
        if weights:
            anchor = sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    if anchor and anchor[1] and not role:
        out.extend(i.evidence_id for i in _ordered_items(package, anchor[0])
                   if _section_root(i) == anchor[1] and _substantive(i))
    out.extend(phrase_matches(obj.wording, package, keep=lambda i: _keep(i) and (
        not role or _item_serves_role(i, package.document(i.submission_document_id), role))))
    out.extend(c.evidence_id for c in mapping.candidates
               if _keep(package.registry.get(c.evidence_id, bid_id=package.bid_id)))
    out.extend(c.evidence_id for c in mapping.other_artifact_candidates
               if _keep(package.registry.get(c.evidence_id, bid_id=package.bid_id)))
    return distinct_evidence(out, package)[:limit]


_PHRASE_WORD_RE = re.compile(r"[a-z][a-z0-9'’-]+")
MAX_PHRASE_MATCHES = 8


def _content_bigrams(text: str) -> set:
    words = [w for w in _PHRASE_WORD_RE.findall((text or "").lower()) if w not in sp._STOPWORDS]
    return {f"{a} {b}" for a, b in zip(words, words[1:]) if len(a) >= 4 and len(b) >= 4}


def phrase_matches(wording: str, package: sp.SubmissionPackage, *, keep=None,
                   limit: int = MAX_PHRASE_MATCHES) -> list[str]:
    """Exact buyer TERMINOLOGY retrieval (section 5): bidder items that repeat
    a two-content-word phrase of the buyer's wording ("point of contact",
    "quality assurance", "response times"), ranked by how many distinct buyer
    phrases they repeat, then reading order. Complements CHECK-1's unigram
    ranking, which lets long passages sharing many common words outrank the
    one short passage that uses the buyer's exact phrase."""
    grams = _content_bigrams(wording)
    if not grams:
        return []
    item_grams = [(n, it, _content_bigrams(it.content)) for n, it in enumerate(package.registry)]
    df: dict = {}
    for _, _, g in item_grams:
        for x in g & grams:
            df[x] = df.get(x, 0) + 1
    scored = []
    for n, it, g in item_grams:
        if keep is not None and not keep(it):
            continue
        hits = grams & g
        if hits:
            # a buyer phrase repeated across many items (e.g. a form's
            # boilerplate "team member") is weak evidence of relevance; a
            # rare exact phrase ("point of contact") is strong (IDF weight)
            scored.append((-round(sum(1.0 / df[x] for x in hits), 6), n, it.evidence_id))
    return [eid for _, _, eid in sorted(scored)[:limit]]


def refine_expected(obj: BuyerObject, expected: sp.ExpectedEvidence, scope: ScopeDecision) -> sp.ExpectedEvidence:
    """CHECK-2A refinement (CHECK-1's derive_expected_evidence is unchanged):
    a submission instruction whose SUBJECT is pricing ("Pricing is to be
    provided ...", "Lump Sum price for ...") but which CHECK-1 fell back to a
    flexible contract-obligation location is evidenced in the pricing form."""
    if expected.evidence_category == sp.EVIDENCE_CATEGORY_PRICING or scope.scope != SCOPE_SUBMISSION_EVIDENCE:
        return expected
    if len(re.findall(r"\bpric\w*|\blump\s+sum\b", obj.wording or "", re.IGNORECASE)) < 2:
        return expected
    return sp.ExpectedEvidence((sp.ROLE_PRICING_FORM, sp.ROLE_TECHNICAL_PROPOSAL), sp.EVIDENCE_CATEGORY_PRICING,
                               sp.LOCATION_BASIS_INFERRED, False, expected.portal_native,
                               "CHECK-2A: pricing-subject submission instruction is evidenced in the pricing form "
                               f"(CHECK-1 location: {expected.evidence_category})")


# ═══════════════════════════════════════════════════════════════════════
# 10. Batching (section 8)
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class ModelTask:
    obj: BuyerObject
    scope: ScopeDecision
    expected: sp.ExpectedEvidence
    mapping: sp.RequirementEvidenceMapping
    evidence_ids: list
    domain: str
    supersessions: list = field(default_factory=list)


_DELETE_REPLACE_RE = re.compile(
    r"\bdelete\s+(?:the\s+)?(?P<old>[A-Za-z][\w /-]{2,40}?)\s+and\s+replace\s+(?:it\s+|them\s+)?with\s+"
    r"(?P<new>[A-Za-z][\w /-]{1,40}?)\s*(?:[.;]|$)", re.IGNORECASE)


def amendment_supersessions(objects: Iterable[BuyerObject]) -> list[dict]:
    """Deterministic, buyer-side: wording an AMENDMENT-role buyer document
    (canonical_procurement.classify_identity_role) explicitly deletes and
    replaces ("Delete hourly rate and replace it with price"). An earlier
    buyer instruction still carrying the deleted wording is judged against
    the amendment, never against the superseded text."""
    out = []
    for o in objects:
        if o.object_type != OBJECT_REQUIREMENT:
            continue
        if not any(cp.classify_identity_role(d) == cp.IDENTITY_ROLE_AMENDMENT for d in o.source_docs):
            continue
        for m in _DELETE_REPLACE_RE.finditer(o.wording or ""):
            out.append({"deleted": _norm_text(m.group("old")), "replacement": m.group("new").strip(),
                        "amendment_object_id": o.object_id, "amendment_source": o.source_docs[0]})
    return out


def supersessions_for(obj: BuyerObject, supersessions: list) -> list:
    if any(cp.classify_identity_role(d) == cp.IDENTITY_ROLE_AMENDMENT for d in obj.source_docs):
        return []
    body = _norm_text(obj.wording)
    return [s for s in supersessions if s["amendment_object_id"] != obj.object_id and s["deleted"] in body]


def _domain(obj: BuyerObject, expected: sp.ExpectedEvidence, evidence_ids: list, package: sp.SubmissionPackage,
            anchor: Optional[tuple] = None) -> str:
    """Coherent adjudication domain: the artifact domain for role-bound
    categories, else the mapped proposal section (so e.g. every firm-
    experience object shares one call and one evidence set)."""
    if expected.evidence_category in (sp.EVIDENCE_CATEGORY_PRICING, sp.EVIDENCE_CATEGORY_DECLARATION,
                                      sp.EVIDENCE_CATEGORY_MULTI_PARTY, sp.EVIDENCE_CATEGORY_CERTIFICATION,
                                      sp.EVIDENCE_CATEGORY_SOCIAL):
        return expected.evidence_category
    if anchor and anchor[1]:
        return f"SECTION:{anchor[1]}"
    roots: dict = {}
    for eid in evidence_ids[:12]:
        it = package.registry.get(eid, bid_id=package.bid_id)
        r = _section_root(it)
        if r:
            roots[r] = roots.get(r, 0) + 1
    anchor = sorted(roots.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if roots else "general"
    return f"{expected.evidence_category}:{anchor}"


def plan_model_batches(tasks: list, *, target: int = MODEL_CALL_TARGET,
                       hard_ceiling: int = MODEL_CALL_HARD_CEILING) -> list[dict]:
    """Coherent-domain batches (never one call per requirement). Domains are
    split at MAX_OBJECTS_PER_BATCH / MAX_EVIDENCE_PER_BATCH; if the plan
    exceeds `target`, the smallest batches are merged (largest evidence
    overlap first); if it still exceeds `hard_ceiling`, BatchPlanningError
    is raised before any provider call."""
    groups: dict = {}
    for t in tasks:
        groups.setdefault(t.domain, []).append(t)
    batches: list = []
    for dom in sorted(groups):
        cur: list = []
        cur_ev: list = []
        for t in groups[dom]:
            new_ev = [e for e in t.evidence_ids if e not in cur_ev]
            if cur and (len(cur) >= MAX_OBJECTS_PER_BATCH or len(cur_ev) + len(new_ev) > MAX_EVIDENCE_PER_BATCH):
                batches.append({"domain": dom, "tasks": cur, "evidence_ids": cur_ev})
                cur, cur_ev, new_ev = [], [], list(t.evidence_ids)
            cur.append(t)
            cur_ev.extend(new_ev)
        if cur:
            batches.append({"domain": dom, "tasks": cur, "evidence_ids": cur_ev})

    def _merge_once() -> bool:
        best = None
        for i in range(len(batches)):
            for j in range(i + 1, len(batches)):
                a, b = batches[i], batches[j]
                union = list(dict.fromkeys(a["evidence_ids"] + b["evidence_ids"]))
                if len(a["tasks"]) + len(b["tasks"]) > MAX_OBJECTS_PER_BATCH or len(union) > MAX_EVIDENCE_PER_BATCH:
                    continue
                key = (len(a["tasks"]) + len(b["tasks"]), -len(set(a["evidence_ids"]) & set(b["evidence_ids"])), i, j)
                if best is None or key < best[0]:
                    best = (key, i, j, union)
        if best is None:
            return False
        _, i, j, union = best
        a, b = batches[i], batches[j]
        batches[i] = {"domain": a["domain"] + "+" + b["domain"], "tasks": a["tasks"] + b["tasks"],
                      "evidence_ids": union}
        del batches[j]
        return True

    while len(batches) > target and _merge_once():
        pass
    if len(batches) > hard_ceiling:
        raise BatchPlanningError(f"model adjudication plan needs {len(batches)} calls (> hard ceiling "
                                 f"{hard_ceiling}); redesign batching before spending")
    for n, b in enumerate(batches, 1):
        b["batch_id"] = f"B{n}"
    return batches


# ═══════════════════════════════════════════════════════════════════════
# 11. Model prompt + fail-closed reconciliation (sections 7 / 10)
# ═══════════════════════════════════════════════════════════════════════

_ADJUDICATION_RULES = """You are CHECK-2A, a bounded SUBMISSION COVERAGE adjudicator for a public-sector procurement.
You compare what the BUYER asked for (canonical buyer objects, verbatim) with what the BIDDER actually
submitted (evidence items extracted from the bidder's submitted files). You do NOT write or improve the
proposal, you do NOT score it, you do NOT predict evaluator points, and you do NOT give recommendations.

HARD RULES
- Judge COVERAGE only: is each thing the buyer explicitly requested actually present in the bidder's evidence?
  Do not judge persuasiveness, quality or price level.
- Break each buyer object into the separate things it explicitly requests ("requested_elements"). Each
  "element" MUST be copied VERBATIM (a contiguous fragment) from that object's buyer_wording. Never invent a
  requirement the buyer did not state. At most 10 elements per object.
- A name, a heading or a reference list alone does NOT cover an element that asks for descriptions, outcomes,
  challenges, time commitment, availability, response times, etc. Check each requested element separately.
- Cite ONLY evidence ids of the form PE<n> listed in the EVIDENCE section below. Never cite anything else.
- The bidder submitted a PACKAGE of several files (listed below). Evidence may legitimately sit in any of them;
  never conclude something is missing just because one document lacks it.
- status meanings:
  ADDRESSED: every requested element is present in the evidence.
  PARTIALLY_ADDRESSED: some requested elements are present, at least one is absent or only partly covered.
  NOT_ADDRESSED: no material response exists anywhere in the supplied evidence.
  NOT_VERIFIABLE_FROM_FILES: the submitted files cannot establish the answer (e.g. completed in a buyer portal,
    a future contractual performance, an internal calculation basis the files do not disclose).
  HUMAN_REVIEW_REQUIRED: the evidence is ambiguous or conflicting.
- element coverage: ADDRESSED | PARTIAL | ABSENT | NOT_VERIFIABLE. ADDRESSED/PARTIAL elements must cite PE ids.
- "evidence_summary": at most 40 words, factual, describing what the bidder evidence contains. No advice.
- "reason": at most 40 words; REQUIRED unless status is ADDRESSED. For PARTIALLY_ADDRESSED name what is absent.
- If a later addendum in this batch amends an earlier instruction, judge against the amended instruction and
  say so in "reason".
- Adjudicate EVERY object listed. Return ONLY JSON, no prose outside it:
{"adjudications": [{"object_id": "<id>", "status": "<status>",
  "requested_elements": [{"element": "<verbatim buyer fragment>", "coverage": "<coverage>",
                          "evidence_ids": ["PE1"], "note": "<=20 words"}],
  "evidence_ids": ["PE1", "PE2"], "evidence_summary": "<=40 words", "reason": "<=40 words"}]}
"""


def _clip_item(item: sp.EvidenceItem) -> str:
    limit = (MAX_OTHER_ITEM_CHARS if item.kind in (sp.EVIDENCE_KIND_SHEET_CELL, sp.EVIDENCE_KIND_SHEET_ROW)
             else MAX_SECTION_TEXT_CHARS)
    body = re.sub(r"\s+", " ", item.content or "").strip()
    return body if len(body) <= limit else body[:limit].rstrip() + " ..."


def _batch_brief(batch: dict, package: sp.SubmissionPackage, organization_id: str) -> sd.SectionResponseBrief:
    """Reuse section_drafting's brief + evidence_id_registry as the bounded
    short-id ledger: bidder evidence becomes PE# (tier-2 proposal evidence,
    CHECK-1 to_proposal_source_ref shape), buyer source refs become CE#
    (procurement evidence) -- so a buyer-source id can never be accepted as
    bidder evidence."""
    refs = [sp.to_proposal_source_ref(package.registry.get(e, bid_id=package.bid_id)) for e in batch["evidence_ids"]]
    buyer_refs = [dict(r) for t in batch["tasks"] for r in t.obj.source_refs if isinstance(r, dict)]
    return sd.build_brief(
        organization_id=organization_id or "", bid_id=package.bid_id,
        requirement={"req_id": batch.get("batch_id") or "", "description": batch.get("domain") or "",
                     "source_refs": buyer_refs},
        assessment={"proposal_source_refs": refs})


def build_batch_ledger(batch: dict, package: sp.SubmissionPackage, organization_id: str = "") -> dict:
    """alias -> evidence id (PE#) plus the full sd registry (PE#/CE#)."""
    brief = _batch_brief(batch, package, organization_id)
    registry = sd.evidence_id_registry(brief)
    alias_to_eid = {k: v["detail"]["evidence_id"] for k, v in registry.items()
                    if v["source_kind"] == sd.SOURCE_KIND_PROPOSAL}
    return {"brief": brief, "registry": registry, "alias_to_eid": alias_to_eid,
            "eid_to_alias": {v: k for k, v in alias_to_eid.items()}}


def build_batch_prompt(batch: dict, package: sp.SubmissionPackage, ledger: dict) -> str:
    objects = []
    for t in batch["tasks"]:
        o = t.obj
        entry = {"object_id": o.object_id, "object_type": o.object_type, "buyer_category": o.category,
                 "buyer_wording": o.wording, "expected_evidence_roles": list(t.expected.roles),
                 "evidence_retrieved_for_this_object": [ledger["eid_to_alias"][e] for e in t.evidence_ids
                                                        if e in ledger["eid_to_alias"]]}
        if o.applicability_condition:
            entry["applicability_condition"] = o.applicability_condition
        if o.weight or o.threshold:
            entry["buyer_weight"] = o.weight
            entry["buyer_threshold"] = o.threshold
        if o.source_docs:
            entry["buyer_source"] = list(o.source_docs)[:2]
        if t.supersessions:
            entry["amendments_in_force"] = [
                f"{x['amendment_object_id']} ({x['amendment_source']}) deletes '{x['deleted']}' and replaces it "
                f"with '{x['replacement']}' -- do not require the deleted wording" for x in t.supersessions]
        objects.append(entry)
    docs = [f"- {d.filename} (role {d.document_role}"
            + (f"; embedded: {', '.join(d.role.secondary_roles)}" if d.role.secondary_roles else "") + ")"
            for d in package.member_documents()]
    ev_lines = []
    for alias, eid in ledger["alias_to_eid"].items():
        it = package.registry.get(eid, bid_id=package.bid_id)
        doc = package.document(it.submission_document_id)
        ev_lines.append(f"{alias} | {it.document_role} | {sp.format_citation(doc.filename, it.location)} | "
                        f"{it.kind}\n{_clip_item(it)}")
    return (_ADJUDICATION_RULES
            + "\nSUBMITTED PACKAGE (all authoritative bidder files):\n" + "\n".join(docs)
            + "\n\nBUYER OBJECTS TO ADJUDICATE:\n" + json.dumps(objects, indent=1, ensure_ascii=False)
            + "\n\nEVIDENCE (bidder files only; cite by PE id):\n" + "\n\n".join(ev_lines))


#: Properties a buyer requires OF a price (its basis, composition, currency,
#: tax treatment, firmness). A completed pricing form shows the price, never
#: these properties -- a model "absent" on one is reclassified NOT_VERIFIABLE
#: (unless the buyer asks the bidder to STATE / itemize it).
_PRICE_PROPERTY_RE = re.compile(
    r"\b(?:inclusive\s+of|include\s+all|exclusive\s+of|(?:canadian|us|local)\s+currency|gst|hst|vat|taxes|"
    r"duties|based\s+(?:only\s+)?on|(?:remain|keep\s+\w+(?:\s+\w+)?\s+)firm|firm\s+for)\b", re.IGNORECASE)
_PRICE_STATEMENT_RE = re.compile(r"\b(?:itemi[sz]e\w*|state|indicate|show|list|break\s*down|separately)\b",
                                 re.IGNORECASE)

#: Buyer-side canonical / procurement-source id shapes (never bidder evidence).
_BUYER_ID_RE = re.compile(r"^(?:REQ|CRIT|SCOPE|OBL|MS|DOC|REL|CAT|CE)-?\d|^(?:REQ|CRIT|SCOPE|OBL|MS|DOC|REL|CAT)-|"
                          r"^(?:IDENT|SUBMISSION|PKG)$")


def _clip_words(text, n: int) -> str:
    words = str(text or "").split()
    return " ".join(words[:n])


def _buyer_fragment_ok(fragment: str, wording: str) -> bool:
    frag = _norm_text(fragment).strip(" .;:,")
    return len(frag) >= 3 and frag in _norm_text(wording)


def reconcile_batch_response(parsed: dict, batch: dict, ledger: dict, package: sp.SubmissionPackage, *,
                             stop_reason: Optional[str] = None) -> dict:
    """Fail-closed validation of ONE model response -> {object_id:
    CheckAdjudication}. Every evidence id is checked against the ids issued
    to THIS call (reusing section_drafting.reconcile_structured_result /
    reconcile_material_claims over the batch's evidence_id_registry), then
    against the bid-bound registry, then against the object's material
    artifact role. Status consistency rules are then enforced structurally;
    an object the model skipped, or returned malformed, becomes
    HUMAN_REVIEW_REQUIRED -- never silently ADDRESSED or NOT_ADDRESSED."""
    registry = ledger["registry"]
    brief = ledger["brief"]
    tasks = {t.obj.object_id: t for t in batch["tasks"]}
    rows = parsed.get("adjudications") if isinstance(parsed, dict) else None
    seen: dict = {}
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and row.get("object_id") in tasks and row["object_id"] not in seen:
            seen[row["object_id"]] = row
    out = {}
    for oid, task in tasks.items():
        row = seen.get(oid)
        adj = _base_adjudication(task.obj, task.scope, STATUS_HUMAN_REVIEW, METHOD_MODEL, expected=task.expected,
                                 mapping=task.mapping, package=package, considered=task.evidence_ids)
        adj.batch_id = batch.get("batch_id")
        rejected: list = []
        downgrades: list = []

        def _validate_ids(raw_ids) -> list:
            ids = []
            for rid in (raw_ids or []):
                if not isinstance(rid, str):
                    continue
                rid = rid.strip()
                alias = rid if rid in registry else ledger["eid_to_alias"].get(rid)
                if alias is None:
                    reason = (REJECT_CROSS_BID if rid.startswith("EV-") else
                              REJECT_BUYER_SOURCE if _BUYER_ID_RE.match(rid) else REJECT_NOT_ISSUED)
                    rejected.append({"id": rid, "reason": reason})
                    continue
                if registry[alias]["source_kind"] != sd.SOURCE_KIND_PROPOSAL:
                    rejected.append({"id": rid, "reason": REJECT_BUYER_SOURCE})
                    continue
                recon = sd.reconcile_structured_result(
                    {"evidence_items_used": [{"evidence_id": alias, "claim_type": sd.CLAIM_TYPE_VERIFIED_FACT}]}, brief)
                if not recon.evidence_items_used:
                    rejected.append({"id": rid, "reason": REJECT_NOT_ISSUED})
                    continue
                eid = ledger["alias_to_eid"][alias]
                if not package.registry.filter_valid([eid], bid_id=package.bid_id):
                    rejected.append({"id": rid, "reason": REJECT_CROSS_BID})
                    continue
                role = material_role(task.expected)
                if role:
                    it = package.registry.get(eid, bid_id=package.bid_id)
                    if not _item_serves_role(it, package.document(it.submission_document_id), role):
                        rejected.append({"id": rid, "evidence_id": eid, "reason": REJECT_WRONG_ARTIFACT})
                        continue
                ids.append(eid)
            return distinct_evidence(ids, package)

        if row is None:
            adj.ambiguity_or_review_reason = ("model returned no adjudication for this object"
                                              + (" (output truncated at the provider limit)"
                                                 if stop_reason == "max_tokens" else ""))
            adj.validation = {"model_status": None, "rejected_evidence_ids": [], "downgrades": ["MISSING_FROM_RESPONSE"]}
            out[oid] = adj
            continue

        model_status = str(row.get("status") or "").strip().upper()
        elements: list = []
        raw_elements = row.get("requested_elements") if isinstance(row.get("requested_elements"), list) else []
        claims = []
        for n, el in enumerate(raw_elements[:MAX_ELEMENTS_PER_OBJECT]):
            if not isinstance(el, dict):
                continue
            frag = str(el.get("element") or "").strip()
            cov = str(el.get("coverage") or "").strip().upper()
            if cov not in MODEL_ELEMENT_COVERAGES:
                downgrades.append(f"element dropped (unknown coverage {cov!r})")
                continue
            if not _buyer_fragment_ok(frag, task.obj.wording):
                downgrades.append(f"element dropped (not verbatim buyer wording): {frag[:80]!r}")
                continue
            ids = _validate_ids(el.get("evidence_ids"))
            claims.append({"claim_id": f"E{n}", "claim_text": frag,
                           "claim_type": sd.CLAIM_TYPE_VERIFIED_FACT if cov in (ELEMENT_ADDRESSED, ELEMENT_PARTIAL)
                           else sd.CLAIM_TYPE_UNSUPPORTED_GAP,
                           "evidence_ids": [ledger["eid_to_alias"][e] for e in ids]})
            elements.append([frag, cov, ids, _clip_words(el.get("note"), 25)])
        # section_drafting's fail-closed claim reconciliation: a "supported"
        # element with no surviving evidence is downgraded (never trusted).
        recon_claims = {c.claim_id: c for c in sd.reconcile_material_claims(claims, registry)}
        final_elements = []
        superseded: list = []
        reclassified: list = []
        for n, (frag, cov, ids, note) in enumerate(elements):
            c = recon_claims.get(f"E{n}")
            hit = next((x for x in task.supersessions if x["deleted"] in _norm_text(frag)), None)
            if hit is not None and cov in (ELEMENT_ABSENT, ELEMENT_PARTIAL):
                superseded.append({"element": frag, "superseded_by": hit["amendment_object_id"],
                                   "amendment_source": hit["amendment_source"], "deleted": hit["deleted"],
                                   "replacement": hit["replacement"], "model_coverage": cov})
                final_elements.append(Element(frag, ELEMENT_NON_OBLIGATION, [],
                                              f"superseded by {hit['amendment_object_id']}"))
                continue
            if (cov in (ELEMENT_ABSENT, ELEMENT_PARTIAL) and material_role(task.expected) == sp.ROLE_PRICING_FORM
                    and _PRICE_PROPERTY_RE.search(frag) and not _PRICE_STATEMENT_RE.search(frag)):
                reclassified.append({"element": frag, "model_coverage": cov, "to": ELEMENT_NOT_VERIFIABLE,
                                     "rule": "PRICE_PROPERTY_NOT_OBSERVABLE"})
                final_elements.append(Element(frag, ELEMENT_NOT_VERIFIABLE, [],
                                              "a property of the submitted price (basis / composition / currency / "
                                              "tax treatment / firmness) that a completed price does not disclose"))
                continue
            if cov in (ELEMENT_ADDRESSED, ELEMENT_PARTIAL) and (c is None or not c.evidence_ids):
                downgrades.append(f"element {cov} without valid evidence -> HUMAN_REVIEW: {frag[:80]!r}")
                cov, ids = ELEMENT_HUMAN_REVIEW, []
            final_elements.append(Element(frag, cov, ids, note))

        top_ids = _validate_ids(row.get("evidence_ids"))
        all_ids = distinct_evidence(top_ids + [e for el in final_elements for e in el.evidence_ids], package)
        reason = _clip_words(row.get("reason"), 45) or None
        summary = _clip_words(row.get("evidence_summary"), 45)

        status = model_status if model_status in MODEL_STATUSES else None
        if status is None:
            downgrades.append(f"unknown status {model_status!r} -> HUMAN_REVIEW_REQUIRED")
            status = STATUS_HUMAN_REVIEW
        kinds = [e.coverage for e in final_elements]
        if status == STATUS_ADDRESSED:
            if not all_ids:
                downgrades.append("ADDRESSED without valid bidder evidence -> HUMAN_REVIEW_REQUIRED")
                status = STATUS_HUMAN_REVIEW
            elif ELEMENT_ABSENT in kinds or ELEMENT_PARTIAL in kinds:
                downgrades.append("ADDRESSED but an element is absent/partial -> PARTIALLY_ADDRESSED")
                status = STATUS_PARTIALLY_ADDRESSED
            elif ELEMENT_HUMAN_REVIEW in kinds:
                downgrades.append("ADDRESSED but an element lost its evidence -> HUMAN_REVIEW_REQUIRED")
                status = STATUS_HUMAN_REVIEW
        if (status == STATUS_PARTIALLY_ADDRESSED and (superseded or reclassified) and all_ids
                and not any(k in (ELEMENT_ABSENT, ELEMENT_PARTIAL, ELEMENT_HUMAN_REVIEW) for k in kinds)):
            why = []
            if superseded:
                why.append("wording a buyer amendment deleted ("
                           + ", ".join(sorted({x["superseded_by"] for x in superseded})) + ")")
            if reclassified:
                why.append("price properties the files cannot show (now NOT_VERIFIABLE elements)")
            downgrades.append("PARTIALLY_ADDRESSED -> ADDRESSED: the only missing element(s) were " + " and ".join(why)
                              + "; every file-verifiable element is addressed")
            status = STATUS_ADDRESSED
        if status == STATUS_PARTIALLY_ADDRESSED:
            if not all_ids:
                downgrades.append("PARTIALLY_ADDRESSED without valid bidder evidence -> HUMAN_REVIEW_REQUIRED")
                status = STATUS_HUMAN_REVIEW
            elif not any(k in (ELEMENT_ABSENT, ELEMENT_PARTIAL) for k in kinds):
                downgrades.append("PARTIALLY_ADDRESSED without an identified absent/partial buyer element "
                                  "-> HUMAN_REVIEW_REQUIRED")
                status = STATUS_HUMAN_REVIEW
        if status == STATUS_NOT_ADDRESSED:
            if task.scope.scope not in CHECKABLE_SCOPES:
                downgrades.append("NOT_ADDRESSED on a non-response scope -> NOT_VERIFIABLE_FROM_FILES")
                status = STATUS_NOT_VERIFIABLE
            elif task.mapping.artifact_status in (sp.POSSIBLY_PORTAL_NATIVE, sp.NOT_VERIFIABLE_FROM_FILES):
                downgrades.append("NOT_ADDRESSED where CHECK-1 artifact status is "
                                  f"{task.mapping.artifact_status} -> NOT_VERIFIABLE_FROM_FILES")
                status = STATUS_NOT_VERIFIABLE
            elif top_ids or any(e.coverage in (ELEMENT_ADDRESSED, ELEMENT_PARTIAL) for e in final_elements):
                downgrades.append("NOT_ADDRESSED while citing supporting evidence -> HUMAN_REVIEW_REQUIRED")
                status = STATUS_HUMAN_REVIEW
            else:
                claim = " ".join([reason or ""] + [e.element for e in final_elements]) + " not provided"
                screen = sp.screen_absence_claim(claim, package)
                if screen["verdict"] == sp.ABSENCE_CONTRADICTED_BY_PACKAGE:
                    downgrades.append("NOT_ADDRESSED contradicted by package artifacts ("
                                      + ", ".join(d["filename"] for d in screen["present_documents"])
                                      + ") -> HUMAN_REVIEW_REQUIRED")
                    status = STATUS_HUMAN_REVIEW
        if status in (STATUS_NOT_VERIFIABLE, STATUS_HUMAN_REVIEW) and not reason:
            reason = "model gave no reason" if model_status == status else None

        adj.status = status
        adj.addressed_elements = [e.to_dict() for e in final_elements if e.coverage == ELEMENT_ADDRESSED]
        adj.missing_elements = [e.to_dict() for e in final_elements if e.coverage in (ELEMENT_ABSENT, ELEMENT_PARTIAL)]
        adj.unverifiable_elements = [e.to_dict() for e in final_elements if e.coverage == ELEMENT_NOT_VERIFIABLE]
        review = [e for e in final_elements if e.coverage == ELEMENT_HUMAN_REVIEW]
        adj.evidence_ids = tuple(all_ids)
        adj.evidence_summary = summary
        extra = [f"element needs review: {e.element}" for e in review]
        adj.ambiguity_or_review_reason = " | ".join([r for r in [reason] if r] + extra
                                                    + (downgrades if status != model_status else [])) or None
        adj.validation = {"model_status": model_status or None, "rejected_evidence_ids": rejected,
                          "downgrades": downgrades, "superseded_elements": superseded,
                          "reclassified_elements": reclassified}
        out[oid] = adj
    return out


def _default_model_call(prompt: str, batch: dict, *, client, telemetry: list,
                        telemetry_context: Optional[dict]) -> dict:
    """ONE bounded structured call through MA-1's shared invocation path
    (config.execute_messages_create + extractor._safe_parse_json_with_status,
    same telemetry row vocabulary incl. provider stop_reason)."""
    import full_analysis as fa
    return fa._call_model(prompt, client=client, call_label=f"check2a_{batch['batch_id'].lower()}",
                          max_tokens=MODEL_MAX_OUTPUT_TOKENS, telemetry=telemetry,
                          telemetry_context=telemetry_context)


# ═══════════════════════════════════════════════════════════════════════
# 12. Orchestration (section 16)
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class CoveragePlan:
    objects: list
    scopes: dict
    expected: dict
    mappings: dict
    deterministic: dict
    model_tasks: list
    batches: list
    criterion_links: dict
    pricing_criteria: list

    def summary(self) -> dict:
        return {"objects": len(self.objects),
                "scope_counts": {s: sum(1 for d in self.scopes.values() if d.scope == s) for s in ASSURANCE_SCOPES},
                "deterministic": len(self.deterministic), "model_objects": len(self.model_tasks),
                "planned_model_calls": len(self.batches),
                "batches": [{"batch_id": b["batch_id"], "domain": b["domain"],
                             "objects": [t.obj.object_id for t in b["tasks"]],
                             "evidence_items": len(b["evidence_ids"])} for b in self.batches],
                "criterion_links": self.criterion_links}


def plan_check_coverage(canonical_package, submission_package: sp.SubmissionPackage, *,
                        raw_requirements: Optional[list] = None, buyer_documents: Optional[list] = None,
                        target: int = MODEL_CALL_TARGET, hard_ceiling: int = MODEL_CALL_HARD_CEILING) -> CoveragePlan:
    """Everything up to (not including) the model calls: buyer objects, scope
    gate, CHECK-1 candidate mapping, deterministic adjudication, criterion
    links and the bounded batch plan. Pure; zero provider calls."""
    cb = getattr(canonical_package, "bid_id", None)
    if cb is not None and submission_package.bid_id is not None and int(cb) != int(submission_package.bid_id):
        raise sp.CrossBidEvidenceError(f"canonical buyer package is bid {cb}, submission package is bid "
                                       f"{submission_package.bid_id}")
    objects = buyer_objects_from_canonical_package(canonical_package, raw_requirements)
    deeming = _deeming_positions(buyer_documents)
    supersessions = amendment_supersessions(objects)
    scopes, expected, mappings, deterministic = {}, {}, {}, {}
    model_tasks: list = []
    requirements = [o for o in objects if o.object_type == OBJECT_REQUIREMENT]
    criteria = [o for o in objects if o.object_type == OBJECT_CRITERION]

    # (1) scope gate for every requirement (buyer semantics only)
    for obj in requirements:
        rd = obj.requirement_dict()
        ee = sp.derive_expected_evidence(rd)
        scope = classify_assurance_scope(obj, expected=ee, deeming=deeming)
        scopes[obj.object_id] = scope
        expected[obj.object_id] = refine_expected(obj, ee, scope)
        mappings[obj.object_id] = sp.map_requirement_to_submission(rd, submission_package, top_k=12, other_k=4)

    # (2) criterion -> rated requirement links (the buyer's ask per criterion)
    link_pool = [(o, scopes[o.object_id]) for o in requirements
                 if scopes[o.object_id].scope in CHECKABLE_SCOPES | {SCOPE_PORTAL_NATIVE}]
    criterion_links, pricing_criteria = {}, []
    criterion_for_req: dict = {}
    direct_criteria: list = []
    for crit in criteria:
        scopes[crit.object_id] = classify_assurance_scope(crit)
        if is_pricing_criterion(crit):
            pricing_criteria.append(crit.object_id)
            continue
        linked = link_criterion_to_requirements(crit, link_pool)
        criterion_links[crit.object_id] = linked
        for rid in linked:
            criterion_for_req.setdefault(rid, []).append(crit.label or "")
        if crit.response_prompt:
            direct_criteria.append(crit)

    # (3) deterministic adjudication, else bounded retrieval for the model
    for obj in requirements:
        scope = scopes[obj.object_id]
        if scope.scope not in CHECKABLE_SCOPES:
            continue
        ee, mapping = expected[obj.object_id], mappings[obj.object_id]
        det = deterministic_adjudication(obj, scope, ee, mapping, submission_package)
        if det is not None:
            deterministic[obj.object_id] = det
            continue
        anchor = None
        if material_role(ee) is None:
            anchor = anchor_section(submission_package, heading_hints(obj, criterion_for_req.get(obj.object_id, ())))
        ev = object_evidence(obj, ee, mapping, submission_package, anchor=anchor)
        model_tasks.append(ModelTask(obj, scope, ee, mapping, ev, _domain(obj, ee, ev, submission_package, anchor),
                                     supersessions_for(obj, supersessions)))

    # (4) a criterion carrying its OWN response prompt is adjudicated directly
    for crit in direct_criteria:
        rd = {"req_id": crit.object_id, "description": crit.wording, "category": "Rated"}
        ee = sp.derive_expected_evidence(rd)
        expected[crit.object_id] = ee
        mapping = sp.map_requirement_to_submission(rd, submission_package, top_k=12, other_k=4)
        mappings[crit.object_id] = mapping
        anchor = anchor_section(submission_package, heading_hints(crit))
        ev = object_evidence(crit, ee, mapping, submission_package, anchor=anchor)
        model_tasks.append(ModelTask(crit, scopes[crit.object_id], ee, mapping, ev,
                                     _domain(crit, ee, ev, submission_package, anchor)))
        criterion_links.pop(crit.object_id, None)
    batches = plan_model_batches(model_tasks, target=target, hard_ceiling=hard_ceiling)
    return CoveragePlan(objects, scopes, expected, mappings, deterministic, model_tasks, batches,
                        criterion_links, pricing_criteria)


def run_check_coverage(canonical_package, submission_package: sp.SubmissionPackage, *,
                       raw_requirements: Optional[list] = None, buyer_documents: Optional[list] = None,
                       adjudicate_fn: Optional[Callable] = None, client=None, organization_id: str = "",
                       telemetry: Optional[list] = None, telemetry_context: Optional[dict] = None,
                       target: int = MODEL_CALL_TARGET, hard_ceiling: int = MODEL_CALL_HARD_CEILING,
                       raw_responses: Optional[dict] = None,
                       on_event: Optional[Callable] = None) -> CheckCoverageResult:
    """THE CHECK-2A entry point. Compute-and-return: nothing is persisted.

    `adjudicate_fn(prompt, batch) -> dict` performs ONE bounded model call
    per batch (tests inject a fake; the default goes through MA-1's shared
    provider helper with `client`). The call count is bounded by the plan
    (<= target, never > hard_ceiling) and counted here independently of
    the provider. `raw_responses`, when given, receives the parsed response
    of every batch (for acceptance evidence / replay).

    `on_event(event_type, payload)` (CHECK-2B, observation only -- same
    pattern as full_analysis.run_full_analysis(on_event=...)) fires at the
    real execution boundaries: EVENT_PLAN_READY after the scope gate /
    retrieval / deterministic stage, EVENT_BATCH_STARTED immediately before
    a semantic batch's adjudicator call and EVENT_BATCH_COMPLETED after its
    fail-closed reconciliation. It never alters a result: with or without a
    hook the adjudications are identical."""
    plan = plan_check_coverage(canonical_package, submission_package, raw_requirements=raw_requirements,
                               buyer_documents=buyer_documents, target=target, hard_ceiling=hard_ceiling)
    if on_event is not None:
        on_event(EVENT_PLAN_READY, {"plan": plan})
    telemetry = telemetry if telemetry is not None else []
    by_id: dict = {}
    for obj in plan.objects:
        if obj.object_type != OBJECT_REQUIREMENT:
            continue
        scope = plan.scopes[obj.object_id]
        if obj.object_id in plan.deterministic:
            by_id[obj.object_id] = plan.deterministic[obj.object_id]
        elif scope.scope not in CHECKABLE_SCOPES:
            ee, mapping = plan.expected[obj.object_id], plan.mappings[obj.object_id]
            status = {SCOPE_PORTAL_NATIVE: STATUS_NOT_VERIFIABLE, SCOPE_HUMAN_REVIEW: STATUS_HUMAN_REVIEW}.get(
                scope.scope, STATUS_NOT_APPLICABLE)
            adj = _base_adjudication(obj, scope, status, METHOD_SCOPE_GATE, expected=ee, mapping=mapping,
                                     package=submission_package,
                                     considered=[c.evidence_id for c in mapping.candidates])
            if status == STATUS_NOT_VERIFIABLE:
                adj.ambiguity_or_review_reason = ("response is completed in the buyer's e-procurement portal; the "
                                                  "uploaded files cannot prove whether it was completed (" +
                                                  scope.basis + ")")
            elif status == STATUS_HUMAN_REVIEW:
                adj.ambiguity_or_review_reason = scope.basis
            else:
                adj.ambiguity_or_review_reason = f"not a submission obligation: {scope.basis}"
            by_id[obj.object_id] = adj

    calls = 0
    batch_log = []
    for batch in plan.batches:
        if calls >= hard_ceiling:
            raise ModelCallBudgetExceeded(f"refusing call {calls + 1}: hard ceiling {hard_ceiling}")
        ledger = build_batch_ledger(batch, submission_package, organization_id)
        prompt = build_batch_prompt(batch, submission_package, ledger)
        batch["alias_to_eid"] = dict(ledger["alias_to_eid"])
        if on_event is not None:
            on_event(EVENT_BATCH_STARTED, {
                "batch_id": batch["batch_id"], "domain": batch["domain"],
                "objects": [t.obj.object_id for t in batch["tasks"]],
                "candidate_evidence_ids": list(batch["evidence_ids"]),
                "alias_to_eid": dict(ledger["alias_to_eid"]), "prompt_chars": len(prompt),
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()})
        calls += 1
        before = len(telemetry)
        stop_reason, error = None, None
        try:
            if adjudicate_fn is not None:
                parsed = adjudicate_fn(prompt, batch)
            else:
                parsed = _default_model_call(prompt, batch, client=client, telemetry=telemetry,
                                             telemetry_context=telemetry_context)
        except Exception as exc:          # fail closed: the batch becomes human review
            parsed, error = {}, f"{type(exc).__name__}: {exc}"[:300]
        if len(telemetry) > before:
            stop_reason = telemetry[-1].get("stop_reason")
        if raw_responses is not None:
            raw_responses[batch["batch_id"]] = {"parsed": parsed, "alias_to_eid": dict(ledger["alias_to_eid"]),
                                                "stop_reason": stop_reason, "error": error}
        results = reconcile_batch_response(parsed if isinstance(parsed, dict) else {}, batch, ledger,
                                           submission_package, stop_reason=stop_reason)
        if error:
            for a in results.values():
                a.ambiguity_or_review_reason = f"model adjudication failed ({error}); no verdict inferred"
        by_id.update(results)
        batch_log.append({"batch_id": batch["batch_id"], "domain": batch["domain"],
                          "objects": [t.obj.object_id for t in batch["tasks"]],
                          "evidence_items_sent": len(ledger["alias_to_eid"]), "prompt_chars": len(prompt),
                          "stop_reason": stop_reason, "error": error})
        if on_event is not None:
            on_event(EVENT_BATCH_COMPLETED, {
                "batch_id": batch["batch_id"], "domain": batch["domain"],
                "objects": [t.obj.object_id for t in batch["tasks"]],
                "candidate_evidence_ids": list(batch["evidence_ids"]),
                "alias_to_eid": dict(ledger["alias_to_eid"]), "parsed": parsed,
                "stop_reason": stop_reason, "error": error,
                "telemetry_rows": [dict(r) for r in telemetry[before:]],
                "results": results, "prompt_chars": len(prompt),
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()})

    for obj in plan.objects:
        if obj.object_type != OBJECT_CRITERION:
            continue
        cid = obj.object_id
        if cid in by_id:
            continue
        if cid in plan.pricing_criteria:
            by_id[cid] = pricing_criterion_adjudication(obj, plan.scopes[cid], submission_package)
        elif plan.criterion_links.get(cid):
            by_id[cid] = derived_criterion_adjudication(obj, plan.criterion_links[cid], by_id, submission_package)
        else:
            adj = _base_adjudication(obj, plan.scopes[cid], STATUS_HUMAN_REVIEW, METHOD_SCOPE_GATE,
                                     package=submission_package)
            adj.ambiguity_or_review_reason = ("criterion carries no buyer response prompt and could not be linked "
                                              "to a canonical rated requirement; requested content unknown")
            by_id[cid] = adj

    ordered = [by_id[o.object_id] for o in plan.objects if o.object_id in by_id]
    for a in ordered:
        if a.buyer_object_type == OBJECT_CRITERION:
            a.buyer_weight_variants = tuple(a.buyer_weight_variants)
    return CheckCoverageResult(
        bid_id=submission_package.bid_id, contract_version=CHECK2A_CONTRACT_VERSION,
        buyer_package_digest=getattr(canonical_package, "package_digest", None),
        submission_package_digest=submission_package.package_digest, adjudications=ordered,
        provider_calls=calls, batches=batch_log, telemetry=list(telemetry))


def artifact_blind_regression_screen(result: CheckCoverageResult, package: sp.SubmissionPackage) -> list:
    """Section 14 guard, applied to the FINAL output: any NOT_ADDRESSED
    verdict whose wording claims a submitted artifact (pricing form,
    submission declarations, multi-party form, ...) is missing while that
    artifact is in the package. Must be empty."""
    hits = []
    for a in result.adjudications:
        if a.status != STATUS_NOT_ADDRESSED:
            continue
        claim = " ".join([a.ambiguity_or_review_reason or ""] + [str(e.get("element")) for e in a.missing_elements]
                         + [a.buyer_expectation]) + " not provided"
        screen = sp.screen_absence_claim(claim, package)
        if screen["verdict"] == sp.ABSENCE_CONTRADICTED_BY_PACKAGE:
            hits.append({"buyer_object_id": a.buyer_object_id, "screen": screen})
    return hits


def result_digest(result: CheckCoverageResult) -> str:
    """Deterministic digest of the adjudication content (not of telemetry)."""
    payload = [{k: v for k, v in a.to_dict().items() if k not in ("search_basis",)} for a in result.adjudications]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


__all__ = [n for n in dir() if n.isupper() or n in {
    "BuyerObject", "buyer_objects_from_canonical_package", "ScopeDecision", "classify_assurance_scope",
    "CheckAdjudication", "CheckCoverageResult", "distinct_evidence", "material_role", "Element",
    "deterministic_adjudication", "is_pricing_criterion", "pricing_criterion_adjudication",
    "link_criterion_to_requirements", "derived_criterion_adjudication", "object_evidence", "ModelTask",
    "plan_model_batches", "build_batch_ledger", "build_batch_prompt", "reconcile_batch_response",
    "CoveragePlan", "plan_check_coverage", "run_check_coverage", "artifact_blind_regression_screen",
    "result_digest", "BatchPlanningError", "ModelCallBudgetExceeded"}]
