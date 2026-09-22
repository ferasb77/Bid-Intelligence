"""
full_analysis.py -- MA-1: Bounded Specialist Full Analysis.

The first genuine multi-agent Full Analysis backend. Six bounded
specialist analyzers independently interpret different domains of the
SAME frozen canonical procurement package (CI-1 / CI-1.1 Layers 1-2),
then one reconciliation stage cross-validates their outputs into a
coherent Full Bid Intelligence result.

    canonical procurement package  (frozen Layers 1-2, no re-extraction)
        -> six bounded specialist analyses  (parallel, isolated)
        -> one bounded reconciliation stage
        -> one structured FullAnalysisResult

This is NOT six independent RAG systems. Every specialist consumes a
BOUNDED SLICE of one shared canonical contract:

  * no specialist rereads the raw RFP text,
  * no specialist queries Organizational Memory or historical proposals,
  * no specialist re-runs ingestion, re-normalizes requirements, or
    creates a second requirement model,
  * no specialist invokes another specialist or the drafting system,
  * every source id a specialist cites must already exist in the
    canonical package -- an unknown id FAILS CLOSED (the finding is
    rejected, never silently kept).

Relationship to Fast Analysis (deliberately preserved, task section 17):
Fast Analysis (fast_analysis.py) remains the preliminary, lower-cost,
faster orientation path and is NOT modified or replaced by this module.
Full Analysis is an EXPLICIT execution mode -- nothing here runs
automatically as part of ingestion. This module makes no extraction
calls at all: it consumes a completed Fast Analysis canonical result.

Layers 1-2 (document_provenance.py, procurement_normalization.py,
canonical_procurement.py) are FROZEN for MA-1 and are imported, never
modified, here.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from types import MappingProxyType

import canonical_procurement as canon
import document_provenance as doc_prov
import procurement_normalization as pn
from config import get_anthropic_client, execute_messages_create
from extractor import _safe_parse_json_with_status

# ═══════════════════════════════════════════════════════════════════════
# 0. Versions and bounded execution configuration
# ═══════════════════════════════════════════════════════════════════════

FULL_ANALYSIS_VERSION = "ma-1"
#: MA-2A: bumped from "ma-1.0" -- the specialist contract gained explicit
#: allowed-category / exact-id instructions and bounded category-label and
#: canonical-id normalization (see `normalize_category_scope` /
#: `normalize_canonical_id`). Bumping it invalidates every prior Full
#: Analysis fingerprint (`compute_full_analysis_fingerprint`).
SPECIALIST_VERSION = "ma-1.1"
RECONCILIATION_VERSION = "ma-1.0"

#: Model used for every specialist and the reconciliation stage. Same
#: provider client/invocation helper Fast Analysis already uses
#: (config.execute_messages_create) -- no second model-call stack.
FULL_ANALYSIS_MODEL = "claude-haiku-4-5-20251001"
SPECIALIST_MAX_OUTPUT_TOKENS = 3000
RECONCILIATION_MAX_OUTPUT_TOKENS = 3000

#: Bounded concurrency (task section 11). Never unbounded, never one
#: thread per finding, never nested pools.
MAX_SPECIALIST_CONCURRENCY = 3

#: Task section 11: "no uncontrolled retries". MA-1 performs ZERO
#: automatic retries -- a failed specialist is reported failed, and the
#: Full Analysis is reported incomplete for that domain. This constant
#: exists so the rule is explicit and testable rather than implicit.
SPECIALIST_RETRY_ATTEMPTS = 0

#: Hard ceilings on how much canonical material one specialist slice may
#: carry. Token discipline (task section 12): each specialist receives
#: only its own bounded slice -- never the whole package, never raw
#: document text.
MAX_ITEMS_PER_SLICE_SECTION = 40
MAX_TEXT_CHARS_PER_ITEM = 600


# ═══════════════════════════════════════════════════════════════════════
# 1. Specialist identities and the bounded canonical-object vocabulary
# ═══════════════════════════════════════════════════════════════════════

SPECIALIST_PROCUREMENT_STRUCTURE = "PROCUREMENT_STRUCTURE"
SPECIALIST_REQUIREMENTS_COMPLIANCE = "REQUIREMENTS_COMPLIANCE"
SPECIALIST_EVALUATION_INTELLIGENCE = "EVALUATION_INTELLIGENCE"
SPECIALIST_SCOPE_DELIVERABLES = "SCOPE_DELIVERABLES"
SPECIALIST_COMMERCIAL_CONTRACTUAL = "COMMERCIAL_CONTRACTUAL"
SPECIALIST_SCHEDULE_SUBMISSION = "SCHEDULE_SUBMISSION"

SPECIALIST_IDS = (
    SPECIALIST_PROCUREMENT_STRUCTURE,
    SPECIALIST_REQUIREMENTS_COMPLIANCE,
    SPECIALIST_EVALUATION_INTELLIGENCE,
    SPECIALIST_SCOPE_DELIVERABLES,
    SPECIALIST_COMMERCIAL_CONTRACTUAL,
    SPECIALIST_SCHEDULE_SUBMISSION,
)

#: The closed vocabulary of canonical object types a specialist slice may
#: contain. Every one of these is produced by the FROZEN Layer 1/2
#: canonical contract -- this module creates no new procurement object
#: type and re-extracts nothing.
OBJ_PROCUREMENT_IDENTITY = "PROCUREMENT_IDENTITY"
OBJ_DOCUMENT_ROLE = "DOCUMENT_ROLE"
OBJ_DOCUMENT_RELATIONSHIP = "DOCUMENT_RELATIONSHIP"
OBJ_PACKAGE_COMPLETENESS = "PACKAGE_COMPLETENESS"
OBJ_SERVICE_CATEGORY = "SERVICE_CATEGORY"
OBJ_CANONICAL_REQUIREMENT = "CANONICAL_REQUIREMENT"
OBJ_SCOPED_EVALUATION_CRITERION = "SCOPED_EVALUATION_CRITERION"
OBJ_CATEGORY_SCOPE_ITEM = "CATEGORY_SCOPE_ITEM"
OBJ_COMMERCIAL_OBLIGATION = "COMMERCIAL_OBLIGATION"
OBJ_SCOPED_MILESTONE = "SCOPED_MILESTONE"
OBJ_SUBMISSION_MECHANICS = "SUBMISSION_MECHANICS"

CANONICAL_OBJECT_TYPES = (
    OBJ_PROCUREMENT_IDENTITY, OBJ_DOCUMENT_ROLE, OBJ_DOCUMENT_RELATIONSHIP,
    OBJ_PACKAGE_COMPLETENESS, OBJ_SERVICE_CATEGORY, OBJ_CANONICAL_REQUIREMENT,
    OBJ_SCOPED_EVALUATION_CRITERION, OBJ_CATEGORY_SCOPE_ITEM,
    OBJ_COMMERCIAL_OBLIGATION, OBJ_SCOPED_MILESTONE, OBJ_SUBMISSION_MECHANICS,
)

#: THE strict input boundary (task section 3). A specialist receives ONLY
#: the canonical object types listed for it -- assembled deterministically
#: by `build_specialist_input`, which drops anything else rather than
#: trusting a caller to pass the right slice.
#:
#: Note what is deliberately ABSENT: SCOPE_DELIVERABLES has no
#: SCOPED_EVALUATION_CRITERION entry, so an evaluation RESPONSE_PROMPT can
#: never reach the Scope specialist as if it described the work
#: (CI-1 Defect B, enforced here a second time at the agent boundary).
SPECIALIST_INPUT_TYPES: dict[str, frozenset] = {
    SPECIALIST_PROCUREMENT_STRUCTURE: frozenset({
        OBJ_PROCUREMENT_IDENTITY, OBJ_DOCUMENT_ROLE, OBJ_DOCUMENT_RELATIONSHIP,
        OBJ_PACKAGE_COMPLETENESS, OBJ_SERVICE_CATEGORY, OBJ_SUBMISSION_MECHANICS,
    }),
    SPECIALIST_REQUIREMENTS_COMPLIANCE: frozenset({
        OBJ_PROCUREMENT_IDENTITY, OBJ_SERVICE_CATEGORY, OBJ_CANONICAL_REQUIREMENT,
        OBJ_SUBMISSION_MECHANICS,
    }),
    SPECIALIST_EVALUATION_INTELLIGENCE: frozenset({
        OBJ_PROCUREMENT_IDENTITY, OBJ_SERVICE_CATEGORY,
        OBJ_SCOPED_EVALUATION_CRITERION,
    }),
    SPECIALIST_SCOPE_DELIVERABLES: frozenset({
        OBJ_PROCUREMENT_IDENTITY, OBJ_SERVICE_CATEGORY, OBJ_CATEGORY_SCOPE_ITEM,
    }),
    SPECIALIST_COMMERCIAL_CONTRACTUAL: frozenset({
        OBJ_PROCUREMENT_IDENTITY, OBJ_COMMERCIAL_OBLIGATION,
    }),
    SPECIALIST_SCHEDULE_SUBMISSION: frozenset({
        OBJ_PROCUREMENT_IDENTITY, OBJ_SERVICE_CATEGORY, OBJ_SCOPED_MILESTONE,
        OBJ_SUBMISSION_MECHANICS,
    }),
}

#: Capabilities NO specialist has (task section 3 / 21). Asserted by the
#: automated suite against the module's own imports, so a future edit that
#: imports one of these into this module fails the test rather than
#: silently widening an agent's reach.
FORBIDDEN_SPECIALIST_CAPABILITIES = (
    "raw_document_text", "organizational_memory", "historical_proposals",
    "ingestion", "requirement_renormalization", "proposal_drafting",
    "specialist_to_specialist_invocation",
)


# ═══════════════════════════════════════════════════════════════════════
# 2. Typed finding taxonomy (task section 10)
# ═══════════════════════════════════════════════════════════════════════

FINDING_FACT = "FACT"
FINDING_RISK = "RISK"
FINDING_GAP = "GAP"
FINDING_AMBIGUITY = "AMBIGUITY"
FINDING_ATTENTION_ITEM = "ATTENTION_ITEM"
FINDING_INTERPRETATION = "INTERPRETATION"

FINDING_TYPES = (
    FINDING_FACT, FINDING_RISK, FINDING_GAP, FINDING_AMBIGUITY,
    FINDING_ATTENTION_ITEM, FINDING_INTERPRETATION,
)

#: Finding types that make a source-grounded CLAIM and therefore must cite
#: at least one canonical object id. An INTERPRETATION is explicitly
#: analytical: it may stand without a canonical citation, but is then
#: marked unsupported and requires human confirmation -- it is NEVER
#: presented as source fact (task section 10).
CITATION_REQUIRED_FINDING_TYPES = frozenset({
    FINDING_FACT, FINDING_RISK, FINDING_GAP, FINDING_AMBIGUITY,
    FINDING_ATTENTION_ITEM,
})

SUPPORT_CANONICAL = "CANONICAL_SUPPORTED"
SUPPORT_UNSUPPORTED = "UNSUPPORTED_INTERPRETATION"

#: Authority labels (task section 13/21): canonical source authority is
#: always higher than specialist interpretation, and reconciliation must
#: never promote interpretation to fact by consensus.
AUTHORITY_CANONICAL = "CANONICAL"
AUTHORITY_SPECIALIST = "SPECIALIST_INTERPRETATION"

STATUS_COMPLETE = "COMPLETE"
STATUS_FAILED = "FAILED"
STATUS_NOT_RUN = "NOT_RUN"

COMPLETENESS_COMPLETE = "COMPLETE"
COMPLETENESS_PARTIAL = "PARTIAL"
COMPLETENESS_FAILED = "FAILED"

#: MA-2A execution events emitted by `run_full_analysis(on_event=...)`.
#: The durable run service (full_analysis_service.py) owns the run-level
#: events (RUN_CREATED, CANONICAL_PACKAGE_READY, RUN_COMPLETED/PARTIAL/
#: FAILED); these are the ones only the orchestrator itself can observe.
EVENT_SPECIALIST_QUEUED = "SPECIALIST_QUEUED"
EVENT_SPECIALIST_STARTED = "SPECIALIST_STARTED"
EVENT_SPECIALIST_COMPLETED = "SPECIALIST_COMPLETED"
EVENT_SPECIALIST_FAILED = "SPECIALIST_FAILED"
EVENT_RECONCILIATION_STARTED = "RECONCILIATION_STARTED"
EVENT_RECONCILIATION_COMPLETED = "RECONCILIATION_COMPLETED"
EVENT_RECONCILIATION_FAILED = "RECONCILIATION_FAILED"


class CanonicalBoundaryError(ValueError):
    """Raised when a caller tries to hand a specialist material that is
    not part of the canonical package (an object type outside its
    permitted set, or raw document text). Fail closed -- never silently
    narrowed, never silently widened."""


# ═══════════════════════════════════════════════════════════════════════
# 3. The canonical package -- one shared, immutable truth
# ═══════════════════════════════════════════════════════════════════════

def _digest(payload) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _clip(text, limit: int = MAX_TEXT_CHARS_PER_ITEM) -> str:
    body = re.sub(r'\s+', ' ', str(text or "")).strip()
    return body if len(body) <= limit else body[:limit].rstrip() + " ..."


@dataclass(frozen=True)
class CanonicalPackage:
    """The ONE shared canonical truth every specialist reads (task section
    21). Frozen dataclass whose collections are tuples / read-only
    mappings: a specialist physically cannot mutate what another
    specialist will read.

    Every object carries a deterministic canonical id (REQ-*, CRIT-*,
    SCOPE-*, OBL-*, MS-*, DOC-*, CAT-*, IDENT, SUBMISSION, PKG). Those
    ids ARE the citation vocabulary -- a finding citing anything else
    fails closed."""
    bid_id: int | None
    analysis_run_id: int | None
    package_digest: str
    identity: MappingProxyType
    document_roles: tuple
    document_relationships: tuple
    package_completeness: MappingProxyType
    service_categories: tuple
    requirements: tuple
    scoped_criteria: tuple
    category_scope_items: tuple
    commercial_obligations: tuple
    milestones: tuple
    submission_mechanics: MappingProxyType
    canonical_ids: frozenset

    def objects_of_type(self, object_type: str) -> tuple:
        return _PACKAGE_ACCESSORS[object_type](self)


def _identity_objects(pkg: CanonicalPackage) -> tuple:
    return (dict(pkg.identity),)


_PACKAGE_ACCESSORS = {
    OBJ_PROCUREMENT_IDENTITY: _identity_objects,
    OBJ_DOCUMENT_ROLE: lambda p: p.document_roles,
    OBJ_DOCUMENT_RELATIONSHIP: lambda p: p.document_relationships,
    OBJ_PACKAGE_COMPLETENESS: lambda p: (dict(p.package_completeness),),
    OBJ_SERVICE_CATEGORY: lambda p: p.service_categories,
    OBJ_CANONICAL_REQUIREMENT: lambda p: p.requirements,
    OBJ_SCOPED_EVALUATION_CRITERION: lambda p: p.scoped_criteria,
    OBJ_CATEGORY_SCOPE_ITEM: lambda p: p.category_scope_items,
    OBJ_COMMERCIAL_OBLIGATION: lambda p: p.commercial_obligations,
    OBJ_SCOPED_MILESTONE: lambda p: p.milestones,
    OBJ_SUBMISSION_MECHANICS: lambda p: (dict(p.submission_mechanics),),
}


def _slug(text: str, limit: int = 48) -> str:
    return re.sub(r'[^a-z0-9]+', '-', str(text or "").strip().lower()).strip('-')[:limit] or "x"


def build_canonical_package(
    result,
    *,
    bid_id: int | None = None,
    analysis_run_id: int | None = None,
    documents: list | None = None,
) -> CanonicalPackage:
    """Assemble the ONE canonical package from a completed Fast Analysis
    canonical result (a `fast_analysis.FastAnalysisResult`, live or
    reconstructed from a persisted raw snapshot).

    Deterministic and free of model calls. Where a snapshot predates a
    CI-1/CI-1.1 canonical field (an older raw-snapshot schema version),
    the FROZEN Layer 1/2 functions that produce that field are re-run here
    over the snapshot's own base material -- this re-derives, it never
    re-extracts and never invents. `documents` (the same [(name, text)]
    pairs Fast Analysis itself was given) is only ever used to re-derive
    the two text-dependent CI-1.1 fields for such an older snapshot; the
    specialists themselves never see document text.

    Assembly order is fixed, so the same result always yields the same
    package digest."""
    identity_by_doc = dict(getattr(result, "doc_metadata_by_doc", {}) or {})
    merged = canon.merge_identity_fields_with_provenance(identity_by_doc, "identity")
    # Canonical procurement-mechanic statements (the buyer's OWN words about
    # how it intends to contract -- multi-vendor call-off, standing offer,
    # single award). Already extracted as a typed PROCUREMENT_MECHANIC
    # observation by the frozen Layer-2 contract; carried here verbatim so
    # the Procurement Structure specialist can interpret the contracting
    # model from source instead of honestly reporting it as undeterminable.
    mechanics, seen_mechanics = [], set()
    for obs in (getattr(result, "typed_observations", []) or []):
        if not isinstance(obs, dict) or obs.get("family") != "PROCUREMENT_MECHANIC":
            continue
        value = _clip(obs.get("original_value") or obs.get("normalized_value"), 300)
        if not value or value.lower() in seen_mechanics:
            continue
        seen_mechanics.add(value.lower())
        mechanics.append({"statement": value, "source_doc": obs.get("source_doc"),
                          "source_refs": list(obs.get("source_refs") or [])})
        if len(mechanics) >= 8:
            break

    identity = {
        "canonical_id": "IDENT",
        "object_type": OBJ_PROCUREMENT_IDENTITY,
        "fields": {k: {"value": _clip(v, 300), "source_doc": doc}
                   for k, (v, doc) in sorted(merged.items())},
        "procurement_mechanics": mechanics,
    }

    roles = canon.classify_identity_roles(sorted(identity_by_doc.keys()))
    document_roles = tuple(
        {"canonical_id": f"DOC-{_slug(name)}", "object_type": OBJ_DOCUMENT_ROLE,
         "document": name, "identity_role": role}
        for name, role in sorted(roles.items())
    )

    relationships = getattr(result, "document_relationships", None) or {}
    if not relationships and identity_by_doc:
        relationships = doc_prov.classify_document_relationships(sorted(identity_by_doc.keys()))
    document_relationships = tuple(
        {"canonical_id": f"REL-{_slug(name)}", "object_type": OBJ_DOCUMENT_RELATIONSHIP,
         "document": name,
         # document_provenance returns a {relationship, related_to, confidence}
         # record per document; older callers stored a bare string. Both are
         # read here, neither is re-decided (Layer 1 stays authoritative).
         "relationship": (rel.get("relationship") if isinstance(rel, dict) else rel),
         "related_to": (rel.get("related_to") if isinstance(rel, dict) else None),
         "confidence": (rel.get("confidence") if isinstance(rel, dict) else None)}
        for name, rel in sorted((relationships or {}).items())
    )

    completeness = dict(getattr(result, "package_completeness", None) or {})
    completeness.update({"canonical_id": "PKG", "object_type": OBJ_PACKAGE_COMPLETENESS})

    # ---- scoped evaluation criteria (CI-1.1 canonical records) --------
    scoped_records = dict(getattr(result, "scoped_criterion_evaluation", {}) or {})
    if not scoped_records:
        from fast_analysis import carry_forward_category_scope
        occurrences = carry_forward_category_scope(
            list(getattr(result, "evaluation_occurrences", []) or []))
        scoped_records = pn.build_scoped_criterion_records(
            occurrences, dict(getattr(result, "scoped_criterion_response_prompts", {}) or {}),
            identity_role_by_doc=roles)

    scoped_criteria = []
    for key, rec in sorted(scoped_records.items()):
        scoped_criteria.append({
            "canonical_id": f"CRIT-{_slug(key, 72)}",
            "object_type": OBJ_SCOPED_EVALUATION_CRITERION,
            "scoped_key": rec.get("scoped_key") or key,
            "category_scope": rec.get("category_scope") or "",
            "criterion": rec.get("criterion") or rec.get("criterion_label") or "",
            "weight": rec.get("weight"),
            "weight_variants": list(rec.get("weight_variants") or []),
            "minimum_score": rec.get("minimum_score"),
            "evaluation_stage": rec.get("evaluation_stage"),
            "response_prompt": _clip(rec.get("response_prompt")),
            "requested_evidence": [_clip(x, 240) for x in (rec.get("requested_evidence") or [])],
            "required_examples": [_clip(x, 240) for x in (rec.get("required_examples") or [])],
            "personnel_requirements": [_clip(x, 240) for x in (rec.get("personnel_requirements") or [])],
            "methodology_requirements": [_clip(x, 240) for x in (rec.get("methodology_requirements") or [])],
            "constraints": [_clip(x, 240) for x in (rec.get("constraints") or [])],
            "authoritative_source": rec.get("authoritative_source"),
            "source_refs": list(rec.get("source_refs") or []),
        })
    scoped_criteria = tuple(scoped_criteria)

    # ---- service categories -------------------------------------------
    category_labels = sorted({c["category_scope"] for c in scoped_criteria if c["category_scope"]})
    raw_scope_items = dict(getattr(result, "category_scope_items", {}) or {})
    if not raw_scope_items and documents and category_labels:
        raw_scope_items = pn.extract_category_scope_items(documents, category_labels)
    category_labels = sorted(set(category_labels) | {c for c in raw_scope_items if c})
    service_categories = tuple(
        {"canonical_id": f"CAT-{_slug(label)}", "object_type": OBJ_SERVICE_CATEGORY,
         "label": label,
         "criterion_count": sum(1 for c in scoped_criteria if c["category_scope"] == label),
         "scope_item_count": len(raw_scope_items.get(label) or [])}
        for label in category_labels
    )

    # ---- category scope items (type-gated a SECOND time here) ----------
    scope_items = []
    for label in sorted(raw_scope_items):
        for i, item in enumerate(raw_scope_items[label] or []):
            text = item.get("text") if isinstance(item, dict) else str(item)
            hint = item.get("semantic_type") if isinstance(item, dict) else None
            # Defect B enforced at the AGENT boundary as well as at
            # extraction: only positively-typed scope material may reach
            # the Scope specialist. A response prompt can never pass.
            semantic_type = canon.classify_semantic_type(text, hint)
            if semantic_type not in canon.SCOPE_SEMANTIC_TYPES:
                continue
            scope_items.append({
                "canonical_id": f"SCOPE-{_slug(label, 32)}-{i}",
                "object_type": OBJ_CATEGORY_SCOPE_ITEM,
                "category_scope": label,
                "semantic_type": semantic_type,
                "text": _clip(text),
                "source_doc": item.get("source_doc") if isinstance(item, dict) else None,
            })
    category_scope_items = tuple(scope_items)

    # ---- canonical requirements ---------------------------------------
    requirements = []
    for i, req in enumerate(getattr(result, "requirements", []) or []):
        if not isinstance(req, dict):
            continue
        applicability = req.get("applicability")
        if not applicability:
            derived = canon.derive_requirement_applicability(req)
            applicability = derived["applicability"]
            category_ids = derived["category_ids"]
            semantic_type = derived["semantic_type"]
        else:
            category_ids = list(req.get("applicable_category_ids") or [])
            semantic_type = req.get("semantic_type") or canon.classify_semantic_type(
                req.get("description"))
        requirements.append({
            "canonical_id": f"REQ-{i}",
            "object_type": OBJ_CANONICAL_REQUIREMENT,
            "description": _clip(req.get("description")),
            "requirement_type": req.get("requirement_type") or req.get("type"),
            "semantic_type": semantic_type,
            "applicability": applicability,
            "applicable_category_ids": list(category_ids),
            "source_docs": list(req.get("source_docs") or
                                ([req["source_doc"]] if req.get("source_doc") else [])),
            "source_refs": list(req.get("source_refs_all") or req.get("source_refs") or []),
        })
    requirements = tuple(requirements)

    # ---- typed commercial / contractual obligations --------------------
    obligations = []
    for i, clause in enumerate(getattr(result, "commercial_clauses", []) or []):
        if not isinstance(clause, dict):
            continue
        text = clause.get("clause_text") or clause.get("text") or clause.get("description")
        heading = clause.get("heading") or clause.get("clause_heading") or clause.get("topic")
        topic = canon.classify_commercial_topic(text or "", heading)
        obligations.append({
            "canonical_id": f"OBL-{i}",
            "object_type": OBJ_COMMERCIAL_OBLIGATION,
            "topic": topic,
            "heading": _clip(heading, 160),
            "clause_text": _clip(text),
            "semantic_type": canon.classify_semantic_type(text or ""),
            "source_doc": clause.get("source_doc"),
            "source_refs": list(clause.get("source_refs") or []),
        })
    commercial_obligations = tuple(obligations)

    # ---- scoped milestones ---------------------------------------------
    raw_milestones = list(getattr(result, "canonical_milestones", []) or [])
    if not raw_milestones:
        observations = [o for o in (getattr(result, "typed_observations", []) or [])
                        if isinstance(o, dict) and o.get("family") == "MILESTONE"]
        if observations:
            raw_milestones = pn.canonicalize_milestones(observations)
    milestones = []
    for i, ms in enumerate(raw_milestones):
        if not isinstance(ms, dict):
            continue
        scope = ms.get("scope") or {}
        milestones.append({
            "canonical_id": f"MS-{i}",
            "object_type": OBJ_SCOPED_MILESTONE,
            "label": _clip(ms.get("label"), 200),
            "scope": scope if isinstance(scope, dict) else {"scope": scope},
            "scope_key": list(canon.milestone_scope_key(ms)),
            "normalized_date_start": ms.get("normalized_date_start"),
            "normalized_date_end": ms.get("normalized_date_end"),
            "original_wording": [_clip(w, 200) for w in (ms.get("original_wording") or [])],
            "ambiguity_state": ms.get("ambiguity_state"),
            "confidence": ms.get("confidence"),
            "source_refs": list(ms.get("source_refs") or []),
        })
    milestones = tuple(milestones)

    # ---- submission mechanics ------------------------------------------
    identity_fields = identity["fields"]
    submission = {
        "canonical_id": "SUBMISSION",
        "object_type": OBJ_SUBMISSION_MECHANICS,
        "submission_deadline": (identity_fields.get("submission_deadline") or {}).get("value"),
        "clarification_deadline": (identity_fields.get("clarification_deadline") or {}).get("value"),
        "submission_method": (identity_fields.get("submission_method") or {}).get("value"),
        "page_limits": dict(getattr(result, "page_limits", {}) or {}),
        "required_response_forms": [
            d["document"] for d in document_roles
            if d["identity_role"] == canon.IDENTITY_ROLE_RESPONSE_FORM],
    }

    canonical_ids = {"IDENT", "SUBMISSION", "PKG"}
    for group in (document_roles, document_relationships, service_categories, requirements,
                  scoped_criteria, category_scope_items, commercial_obligations, milestones):
        canonical_ids |= {o["canonical_id"] for o in group}

    digest_payload = {
        "identity": identity, "document_roles": list(document_roles),
        "requirements": list(requirements), "scoped_criteria": list(scoped_criteria),
        "category_scope_items": list(category_scope_items),
        "commercial_obligations": list(commercial_obligations),
        "milestones": list(milestones), "submission": submission,
    }

    return CanonicalPackage(
        bid_id=bid_id,
        analysis_run_id=analysis_run_id,
        package_digest=_digest(digest_payload),
        identity=MappingProxyType(identity),
        document_roles=document_roles,
        document_relationships=document_relationships,
        package_completeness=MappingProxyType(completeness),
        service_categories=service_categories,
        requirements=requirements,
        scoped_criteria=scoped_criteria,
        category_scope_items=category_scope_items,
        commercial_obligations=commercial_obligations,
        milestones=milestones,
        submission_mechanics=MappingProxyType(submission),
        canonical_ids=frozenset(canonical_ids),
    )


# ═══════════════════════════════════════════════════════════════════════
# 4. Bounded specialist input assembly (task sections 3 / 12)
# ═══════════════════════════════════════════════════════════════════════

def _freeze(value):
    """A deep, read-only copy. A specialist receiving this cannot mutate
    canonical state -- neither its own slice nor, therefore, any other
    specialist's view of the same package (task section 11: no shared
    mutable specialist state)."""
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


def build_specialist_input(package: CanonicalPackage, specialist_id: str) -> MappingProxyType:
    """The deterministic, bounded canonical slice for ONE specialist.

    Only the object types in SPECIALIST_INPUT_TYPES[specialist_id] are
    included; everything else in the package is simply not assembled, so
    the specialist never holds it. The result is deeply read-only, so a
    specialist cannot mutate canonical input, and the same package always
    produces the same slice (deterministic input assembly)."""
    if specialist_id not in SPECIALIST_INPUT_TYPES:
        raise CanonicalBoundaryError(f"unknown specialist id: {specialist_id!r}")
    permitted = SPECIALIST_INPUT_TYPES[specialist_id]
    slice_payload: dict = {}
    for object_type in CANONICAL_OBJECT_TYPES:
        if object_type not in permitted:
            continue
        objects = list(package.objects_of_type(object_type))[:MAX_ITEMS_PER_SLICE_SECTION]
        slice_payload[object_type] = objects
    return _freeze({
        "specialist_id": specialist_id,
        "package_digest": package.package_digest,
        "permitted_object_types": sorted(permitted),
        "objects": slice_payload,
    })


def specialist_input_digest(slice_payload) -> str:
    return _digest(_thaw(slice_payload))


def _thaw(value):
    if isinstance(value, (MappingProxyType, dict)):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(v) for v in value]
    return value


def slice_canonical_ids(slice_payload) -> set:
    """Every canonical id this specialist was actually given. A finding
    citing an id outside this set fails closed -- a specialist may only
    cite what it was shown, not the whole package."""
    ids = set()
    for objects in _thaw(slice_payload).get("objects", {}).values():
        for obj in objects:
            if isinstance(obj, dict) and obj.get("canonical_id"):
                ids.add(obj["canonical_id"])
    return ids


# ═══════════════════════════════════════════════════════════════════════
# 5. Per-specialist analytical briefs (task sections 4-9)
# ═══════════════════════════════════════════════════════════════════════

_SHARED_RULES = """
HARD RULES (these outrank anything else in this prompt):
- You are ONE bounded specialist. Interpret ONLY the canonical objects given below.
- The canonical objects are the ONLY source of truth. Do not invent a procurement
  requirement, date, weight, category, obligation or document that is not present.
- You cannot read the original RFP, search any memory, or call another specialist.
- Every FACT, RISK, GAP, AMBIGUITY and ATTENTION_ITEM finding MUST cite at least one
  canonical_id copied EXACTLY from the objects below. A finding citing an id that is
  not in the objects below will be discarded.
- Never present interpretation as source fact. Analytical judgement that goes beyond
  what the objects state must be typed INTERPRETATION.
- Never infer a hidden weight, price, deadline or obligation that is not stated.
- Different service categories are DIFFERENT scopes. Never merge them, and never
  report a difference between two categories as a conflict.

- "finding_type" MUST be EXACTLY one of these six values and nothing else:
  FACT (stated in the canonical objects), RISK (a bidder exposure you infer),
  GAP (something a bidder needs that the canonical objects do not state),
  AMBIGUITY (the canonical objects support more than one reading),
  ATTENTION_ITEM (easy to miss / must not be overlooked),
  INTERPRETATION (your analytical judgement).
  Do NOT invent a domain-specific type name. A hard compliance gate, a
  submission-critical obligation or a pricing rule is still a FACT (if stated)
  or an ATTENTION_ITEM (if it is easy to miss) -- put the emphasis in "title"
  and "severity", never in "finding_type". A finding whose finding_type is not
  one of the six values above is DISCARDED.

Return ONLY a JSON object, no prose outside it:
{"findings": [{"finding_type": "FACT|RISK|GAP|AMBIGUITY|ATTENTION_ITEM|INTERPRETATION",
  "title": "<short>", "detail": "<2-4 sentences>", "canonical_ids": ["<id>", ...],
  "category_scope": "<category label or empty string>",
  "severity": "HIGH|MEDIUM|LOW",
  "human_confirmation_required": true|false}]}
Return at most 14 findings, highest-value first.
"""

SPECIALIST_BRIEFS = {
    SPECIALIST_PROCUREMENT_STRUCTURE: """You are the PROCUREMENT STRUCTURE specialist.
Interpret how this procurement is ORGANIZED: the procurement/contracting model
(single award, multi-vendor call-off, standing offer), how the service categories
relate to one another, which document governs which question for a bidder
(document precedence), the submission architecture, structural dependencies between
documents and categories, and meaningful procurement-shape risks.
You must NOT re-decide document identity, authorship or amendment lineage -- those
are already canonically decided and given to you; interpret their CONSEQUENCES.""",

    SPECIALIST_REQUIREMENTS_COMPLIANCE: """You are the REQUIREMENTS & COMPLIANCE specialist.
Interpret the canonical requirements you are given: which are hard compliance gates,
which qualification requirements are category-specific, which are submission-critical,
which depend on another requirement, which need explicit human confirmation, where the
highest-risk compliance gaps are, and which obligations are easy to miss.
Do NOT restate or duplicate the canonical requirements as findings -- reference them by
canonical_id and say what they MEAN for a bidder. Preserve each requirement's stated
category applicability exactly; never widen a category-specific requirement to all
categories and never narrow an all-categories requirement.""",

    SPECIALIST_EVALUATION_INTELLIGENCE: """You are the EVALUATION INTELLIGENCE specialist.
Interpret the scoped evaluation criteria you are given: what the evaluator is explicitly
asking bidders to demonstrate, where the points are concentrated, the evidence burden per
criterion, the highest-value response areas, relationships between criteria, and
evaluation-related risks and gaps.
Criteria are SCOPED to a service category. A criterion label that appears under several
categories is several separate criteria -- never merge them, and never treat different
weights across categories as a conflict. Never infer a weight that is not stated; if a
weight is absent say so as a GAP.""",

    SPECIALIST_SCOPE_DELIVERABLES: """You are the SCOPE & DELIVERABLES specialist.
Interpret what work the supplier may actually be asked to perform: major workstreams,
services, deliverables, delivery complexity, resource and capability implications,
deliverable dependencies, and category-specific operating implications.
Everything you are given is source-grounded scope material. You have deliberately NOT
been given evaluation criteria or response prompts, because an instruction telling a
proponent what to write is NOT a statement of the work being procured. Keep each
category's scope separate.""",

    SPECIALIST_COMMERCIAL_CONTRACTUAL: """You are the COMMERCIAL & CONTRACTUAL specialist.
Interpret the typed commercial and contractual obligations you are given: material
commercial exposure, negotiation-sensitive provisions, unusual obligations, pricing
constraints, legal/operational dependencies, and decisions a bidder must take BEFORE
submitting.
Each obligation carries a canonical topic classification -- respect it; do not rebind a
clause to a different topic. Keep factual obligation separate from analytical risk
commentary: state the obligation as FACT (citing the clause) and your commercial concern
as RISK or INTERPRETATION. Do NOT give legal advice and do not invent interpretation
beyond what the clause supports.""",

    SPECIALIST_SCHEDULE_SUBMISSION: """You are the SCHEDULE & SUBMISSION specialist.
Interpret the canonical bid calendar and submission mechanics: the sequence of milestones,
category-specific milestones, dependencies between events, timing risks, and what a bidder
must have ready when.
Milestones are SCOPED. Two different service categories holding their demonstrations or
presentations on different dates is NORMAL and is NOT a conflict or ambiguity -- report it
as a category-specific schedule fact. Only report a timing AMBIGUITY when the SAME scope
has genuinely irreconcilable dates.""",
}


def _allowed_category_rules(slice_payload) -> str:
    """MA-2A residual hardening (task sections 14/15): MA-1's live smoke
    surfaced 9 findings whose `category_scope` paraphrased a canonical
    service-category label (e.g. "Category 1" / "D1" instead of the exact
    canonical label). The fix is to state the closed set explicitly in the
    prompt -- canonical ids preferred over labels -- rather than loosen any
    validation downstream."""
    objects = _thaw(slice_payload).get("objects", {})
    categories = [o for o in objects.get(OBJ_SERVICE_CATEGORY, []) if isinstance(o, dict)]
    if not categories:
        return ('\n- "category_scope" MUST be the empty string "" -- you have not been given '
                'any service category objects, so you may not name one.\n')
    lines = "\n".join(f'    {c["canonical_id"]}  =  {c["label"]}' for c in categories)
    return ('\n- "category_scope" MUST be either the empty string "" (applies to all '
            'categories / not category-specific) or EXACTLY one of the canonical category '
            'ids below (preferred) or its exact label. Never paraphrase, abbreviate or '
            'renumber a category ("Category 1", "D1", "L&D" are NOT valid). A category not '
            'in this list does not exist:\n' + lines + "\n"
            '- "canonical_ids" must contain canonical_id values copied character-for-character '
            'from the objects below -- never a title, label, page reference or document name.\n')


def _build_specialist_prompt(specialist_id: str, slice_payload) -> str:
    body = json.dumps(_thaw(slice_payload)["objects"], indent=1, ensure_ascii=False, default=str)
    return (
        SPECIALIST_BRIEFS[specialist_id].strip() + "\n" + _SHARED_RULES +
        _allowed_category_rules(slice_payload) +
        "\nCANONICAL OBJECTS (the complete and only material available to you):\n" + body
    )


# ═══════════════════════════════════════════════════════════════════════
# 6. Structured model call (reuses the existing invocation helper)
# ═══════════════════════════════════════════════════════════════════════

def _call_model(prompt: str, *, client, call_label: str, max_tokens: int,
                telemetry: list, telemetry_context: dict | None = None) -> dict:
    """ONE bounded, structured model call. Reuses
    config.execute_messages_create (the single provider invocation helper
    this codebase uses everywhere) and extractor._safe_parse_json_with_status
    (the same tolerant JSON parse Fast Analysis uses) -- no second
    model-call stack, no second JSON parser.

    Telemetry rows use the SAME field vocabulary as Fast Analysis's own
    per-call telemetry (call_kind / request_bytes / latency / tokens /
    stop_reason / parse_status / provider_call_attempted), so the existing
    model-usage tooling can read them unchanged."""
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    row = {
        "call_index": len(telemetry), "call_kind": f"{call_label}_initial",
        "filename": None, "route": call_label, "model": FULL_ANALYSIS_MODEL,
        "request_bytes": len(prompt.encode("utf-8")), "chunk_chars": len(prompt),
        "call_started_at": started.isoformat(), "call_ended_at": None,
        "latency_seconds": 0.0, "input_tokens": None, "output_tokens": None,
        "stop_reason": None, "parse_status": None, "error": None,
        "parent_call_index": None, "split_trigger_reason": None,
        "provider_call_attempted": True,
    }
    telemetry.append(row)
    # MA-2A telemetry linkage (task section 13): when the caller supplies a
    # telemetry_context (the durable-run service does, with workflow=
    # "full_analysis" and the Full Analysis run id), each call is recorded
    # through the EXISTING model_usage_events path with an operation naming
    # exactly which specialist / reconciliation made it. No second
    # telemetry system; the in-memory `telemetry` list is unchanged.
    call_context = None
    if telemetry_context:
        call_context = dict(telemetry_context)
        call_context["operation"] = call_label
        call_context["metadata"] = {**(telemetry_context.get("metadata") or {}),
                                    "call_label": call_label}
    try:
        response = execute_messages_create(
            client, model=FULL_ANALYSIS_MODEL, max_tokens=max_tokens,
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
            **({"telemetry_context": call_context} if call_context else {}),
        )
    except Exception as exc:
        row["call_ended_at"] = datetime.now(timezone.utc).isoformat()
        row["latency_seconds"] = round(time.monotonic() - t0, 6)
        row["error"] = f"{type(exc).__name__}: {exc}"
        raise
    usage = getattr(response, "usage", None)
    data, parse_status = _safe_parse_json_with_status(response.content[0].text)
    row.update({
        "call_ended_at": datetime.now(timezone.utc).isoformat(),
        "latency_seconds": round(time.monotonic() - t0, 6),
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "stop_reason": getattr(response, "stop_reason", None),
        "parse_status": parse_status,
    })
    return data if isinstance(data, dict) else {}


# ═══════════════════════════════════════════════════════════════════════
# 7. Finding validation -- unknown ids fail closed (task sections 3 / 10)
# ═══════════════════════════════════════════════════════════════════════

_SEVERITIES = ("HIGH", "MEDIUM", "LOW")


CATEGORY_SCOPE_EXACT = "EXACT"
CATEGORY_SCOPE_EMPTY = "EMPTY"
CATEGORY_SCOPE_NORMALIZED = "NORMALIZED"
CATEGORY_SCOPE_UNRECOGNIZED = "UNRECOGNIZED"


def _label_key(text) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', str(text or "").lower()).strip()


def normalize_category_scope(value, categories) -> tuple:
    """Bounded label -> canonical category normalization (MA-2A section 15).

    `categories` is an iterable of (canonical_id, label) pairs -- the ONLY
    categories that exist. Returns (category_scope, status):

      * ""                          -> ("", EMPTY)
      * exact canonical label       -> (label, EXACT)
      * a canonical CAT-* id        -> (label, NORMALIZED)
      * the same label differing only in case/punctuation/whitespace
                                    -> (label, NORMALIZED)
      * a phrase that is a whole-word sub-phrase of EXACTLY ONE canonical
        label (e.g. "HR Advisory" for "Appendix D2 - HR Advisory")
                                    -> (label, NORMALIZED)
      * anything else, including a phrase matching two or more labels, or a
        renumbering like "Category 1" that appears in no label
                                    -> (original value, UNRECOGNIZED)

    Canonical ids stay authoritative; the model can never create a
    category, and an ambiguous or unrecognized label FAILS CLOSED (it is
    returned unchanged and flagged, so the deterministic
    CATEGORY_NOT_CANONICAL assurance still surfaces it)."""
    raw = str(value or "").strip()
    if not raw:
        return "", CATEGORY_SCOPE_EMPTY
    pairs = [(str(cid), str(label)) for cid, label in (categories or []) if label]
    for _, label in pairs:
        if raw == label:
            return label, CATEGORY_SCOPE_EXACT
    for cid, label in pairs:
        if raw == cid or raw.upper() == cid.upper():
            return label, CATEGORY_SCOPE_NORMALIZED
    key = _label_key(raw)
    if not key:
        return raw, CATEGORY_SCOPE_UNRECOGNIZED
    same = [label for _, label in pairs if _label_key(label) == key]
    if len(same) == 1:
        return same[0], CATEGORY_SCOPE_NORMALIZED
    # Whole-word sub-phrase match; a single short token ("d", "1") is never
    # enough on its own -- require >= 2 words or >= 4 characters.
    if len(key.split()) >= 2 or len(key) >= 4:
        padded = f" {key} "
        contains = [label for _, label in pairs if padded in f" {_label_key(label)} "]
        if len(contains) == 1:
            return contains[0], CATEGORY_SCOPE_NORMALIZED
    return raw, CATEGORY_SCOPE_UNRECOGNIZED


def normalize_canonical_id(value, permitted_ids) -> str | None:
    """Exact id, else a unique case-/whitespace-insensitive match against the
    ids this specialist was actually given. Never maps to an id outside
    `permitted_ids`; an ambiguous or unknown id returns None (fail closed)."""
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw in permitted_ids:
        return raw
    folded = re.sub(r'\s+', '', raw).upper()
    matches = [p for p in permitted_ids if re.sub(r'\s+', '', p).upper() == folded]
    return matches[0] if len(matches) == 1 else None


def validate_findings(raw_findings, permitted_ids: set, *, produced_by: str,
                      categories=None) -> tuple:
    """Type, validate and ground one specialist's raw findings.

    Returns (accepted, rejected). A finding is REJECTED (never silently
    repaired, never downgraded into a different claim) when:
      * its finding_type is outside the closed taxonomy,
      * it has no substantive text,
      * it is a citation-requiring type with no canonical id that this
        specialist was actually given (unknown id -> fail closed).

    An accepted finding carries the canonical ids it is grounded in, its
    support status, and its authority label -- an INTERPRETATION is
    ALWAYS SPECIALIST_INTERPRETATION authority and never becomes fact."""
    accepted, rejected = [], []
    for raw in (raw_findings or []):
        if not isinstance(raw, dict):
            rejected.append({"reason": "MALFORMED", "raw": str(raw)[:200]})
            continue
        finding_type = str(raw.get("finding_type") or "").strip().upper()
        title = _clip(raw.get("title"), 200)
        detail = _clip(raw.get("detail"), 900)
        if finding_type not in FINDING_TYPES:
            rejected.append({"reason": "UNKNOWN_FINDING_TYPE", "finding_type": finding_type,
                             "title": title})
            continue
        if not (title or detail):
            rejected.append({"reason": "EMPTY", "finding_type": finding_type})
            continue
        cited = [str(i).strip() for i in (raw.get("canonical_ids") or []) if str(i).strip()]
        known, unknown, id_normalizations = [], [], []
        for cid in cited:
            resolved = normalize_canonical_id(cid, permitted_ids)
            if resolved is None:
                unknown.append(cid)
            elif resolved not in known:
                known.append(resolved)
                if resolved != cid:
                    id_normalizations.append({"from": cid, "to": resolved})
        if finding_type in CITATION_REQUIRED_FINDING_TYPES and not known:
            rejected.append({
                "reason": "UNCITED_OR_UNKNOWN_CANONICAL_ID", "finding_type": finding_type,
                "title": title, "unknown_ids": unknown})
            continue
        severity = str(raw.get("severity") or "MEDIUM").strip().upper()
        support = SUPPORT_CANONICAL if known else SUPPORT_UNSUPPORTED
        raw_scope = _clip(raw.get("category_scope"), 160)
        if categories is None:
            category_scope, scope_status = raw_scope, None
        else:
            category_scope, scope_status = normalize_category_scope(raw_scope, categories)
        entry = {
            "finding_id": f"{produced_by}:{len(accepted)}",
            "finding_type": finding_type,
            "title": title,
            "detail": detail,
            "canonical_ids": known,
            "rejected_canonical_ids": unknown,
            "category_scope": category_scope,
            "severity": severity if severity in _SEVERITIES else "MEDIUM",
            "support_status": support,
            "authority": AUTHORITY_CANONICAL if finding_type == FINDING_FACT and known
                         else AUTHORITY_SPECIALIST,
            "human_confirmation_required": bool(raw.get("human_confirmation_required"))
                                           or support == SUPPORT_UNSUPPORTED
                                           or scope_status == CATEGORY_SCOPE_UNRECOGNIZED,
            "produced_by": [produced_by],
        }
        if scope_status is not None:
            entry["category_scope_status"] = scope_status
            if scope_status == CATEGORY_SCOPE_NORMALIZED:
                entry["category_scope_normalized_from"] = raw_scope
        if id_normalizations:
            entry["canonical_id_normalizations"] = id_normalizations
        accepted.append(entry)
    return accepted, rejected


# ═══════════════════════════════════════════════════════════════════════
# 8. Specialist result contract (task section 2)
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class SpecialistResult:
    specialist_id: str
    specialist_version: str = SPECIALIST_VERSION
    bid_id: int | None = None
    status: str = STATUS_NOT_RUN
    input_digest: str = ""
    canonical_objects_consumed: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)
    risks: list = field(default_factory=list)
    ambiguities: list = field(default_factory=list)
    gaps: list = field(default_factory=list)
    attention_items: list = field(default_factory=list)
    source_refs: list = field(default_factory=list)
    confidence: str = "NOT_RUN"
    human_confirmation_required: bool = False
    rejected_findings: list = field(default_factory=list)
    failure_reason: str | None = None
    duration_seconds: float = 0.0
    usage: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


_TYPE_BUCKETS = {
    FINDING_RISK: "risks",
    FINDING_GAP: "gaps",
    FINDING_AMBIGUITY: "ambiguities",
    FINDING_ATTENTION_ITEM: "attention_items",
}


def run_specialist(package: CanonicalPackage, specialist_id: str, *, client,
                   telemetry: list, telemetry_context: dict | None = None) -> SpecialistResult:
    """Run ONE specialist end to end: bounded slice -> one structured model
    call -> validated, typed findings. Never raises for an analysis-level
    failure -- a failed specialist returns status=FAILED with its reason,
    so one specialist's failure cannot destroy another's output (task
    section 14). No retries (SPECIALIST_RETRY_ATTEMPTS == 0)."""
    t0 = time.monotonic()
    result = SpecialistResult(specialist_id=specialist_id, bid_id=package.bid_id)
    try:
        slice_payload = build_specialist_input(package, specialist_id)
        result.input_digest = specialist_input_digest(slice_payload)
        objects = _thaw(slice_payload)["objects"]
        result.canonical_objects_consumed = {k: len(v) for k, v in sorted(objects.items())}
        permitted_ids = slice_canonical_ids(slice_payload)

        prompt = _build_specialist_prompt(specialist_id, slice_payload)
        before = len(telemetry)
        data = _call_model(prompt, client=client, call_label=f"specialist_{specialist_id.lower()}",
                           max_tokens=SPECIALIST_MAX_OUTPUT_TOKENS, telemetry=telemetry,
                           telemetry_context=telemetry_context)
        rows = telemetry[before:]
        result.usage = {
            "calls": len(rows),
            "input_tokens": sum(r.get("input_tokens") or 0 for r in rows),
            "output_tokens": sum(r.get("output_tokens") or 0 for r in rows),
            "request_bytes": sum(r.get("request_bytes") or 0 for r in rows),
            "model": FULL_ANALYSIS_MODEL,
        }

        accepted, rejected = validate_findings(
            data.get("findings"), permitted_ids, produced_by=specialist_id,
            categories=[(c["canonical_id"], c["label"]) for c in package.service_categories])
        result.findings = accepted
        result.rejected_findings = rejected
        for finding in accepted:
            bucket = _TYPE_BUCKETS.get(finding["finding_type"])
            if bucket:
                getattr(result, bucket).append(finding)
        refs = []
        by_id = {o["canonical_id"]: o for objs in objects.values() for o in objs
                 if isinstance(o, dict) and o.get("canonical_id")}
        for finding in accepted:
            for cid in finding["canonical_ids"]:
                obj = by_id.get(cid) or {}
                for ref in (obj.get("source_refs") or []):
                    if ref not in refs:
                        refs.append(ref)
        result.source_refs = refs
        result.human_confirmation_required = any(
            f["human_confirmation_required"] for f in accepted)
        supported = sum(1 for f in accepted if f["support_status"] == SUPPORT_CANONICAL)
        result.confidence = ("HIGH" if accepted and supported == len(accepted)
                             else "MEDIUM" if supported else "LOW")
        result.status = STATUS_COMPLETE
    except Exception as exc:
        # Isolated failure handling: recorded, never re-raised into the
        # orchestrator, never substituted with generic model reasoning.
        result.status = STATUS_FAILED
        result.failure_reason = f"{type(exc).__name__}: {exc}"[:400]
        result.confidence = "NONE"
    result.duration_seconds = round(time.monotonic() - t0, 6)
    return result


# ═══════════════════════════════════════════════════════════════════════
# 9. Deterministic cross-domain checks (run BEFORE the model stage)
# ═══════════════════════════════════════════════════════════════════════

def _normalize_title(text: str) -> str:
    return re.sub(r'[^a-z0-9 ]+', ' ', str(text or "").lower()).strip()


def consolidate_findings(specialist_results: list) -> tuple:
    """Merge overlapping findings from different specialists into one
    canonical Full Analysis view while PRESERVING which specialist(s)
    produced each (task section 13).

    Two findings merge only when they are the same finding_type AND their
    titles are near-duplicates by the SAME primitive CI-1 uses for
    requirement de-duplication (never a new fuzzy matcher), AND they do
    not contradict each other's stated category scope. Merging is a VIEW
    operation: nothing about canonical authority changes, and a merged
    finding keeps the union of its canonical ids."""
    merged: list = []
    duplicate_groups: list = []
    for result in specialist_results:
        for finding in result.findings:
            title = _normalize_title(finding["title"] or finding["detail"])
            words = canon._fuzzy_word_set(title)
            target = None
            for candidate in merged:
                if candidate["finding_type"] != finding["finding_type"]:
                    continue
                if (candidate["category_scope"] or "") != (finding["category_scope"] or ""):
                    continue
                if canon._is_near_duplicate(title, words, candidate["_title_norm"],
                                            candidate["_title_words"]):
                    target = candidate
                    break
            if target is None:
                entry = dict(finding)
                entry["_title_norm"] = title
                entry["_title_words"] = words
                entry["produced_by"] = list(finding["produced_by"])
                merged.append(entry)
                continue
            for producer in finding["produced_by"]:
                if producer not in target["produced_by"]:
                    target["produced_by"].append(producer)
            for cid in finding["canonical_ids"]:
                if cid not in target["canonical_ids"]:
                    target["canonical_ids"].append(cid)
            # Canonical authority wins over specialist interpretation: a
            # FACT grounded in canonical ids is never demoted by merging
            # an interpretation-authority duplicate into it.
            if finding["authority"] == AUTHORITY_CANONICAL:
                target["authority"] = AUTHORITY_CANONICAL
            target["human_confirmation_required"] = (
                target["human_confirmation_required"] or finding["human_confirmation_required"])
            duplicate_groups.append({
                "finding_type": finding["finding_type"],
                "title": finding["title"],
                "merged_into": target["finding_id"],
                "produced_by": list(target["produced_by"]),
            })
    for entry in merged:
        entry.pop("_title_norm", None)
        entry.pop("_title_words", None)
    return merged, duplicate_groups


def detect_orphaned_requirements(package: CanonicalPackage, specialist_results: list) -> list:
    """Canonical requirements no specialist discussed at all. This is a
    COMPLETENESS signal computed from canonical truth, not from specialist
    opinion -- an agent forgetting a requirement can never make that
    requirement disappear (task section 13 / 21)."""
    cited = set()
    for result in specialist_results:
        for finding in result.findings:
            cited |= set(finding["canonical_ids"])
    orphans = []
    for req in package.requirements:
        if req["canonical_id"] in cited:
            continue
        orphans.append({
            "canonical_id": req["canonical_id"],
            "description": req["description"],
            "applicability": req["applicability"],
            "applicable_category_ids": req["applicable_category_ids"],
        })
    return orphans


def detect_category_scope_inconsistencies(package: CanonicalPackage,
                                          specialist_results: list) -> list:
    """A specialist claiming a category scope that is not a canonical
    service category, or citing a canonical object belonging to a
    DIFFERENT category than the finding claims. Canonical scope wins."""
    known = {c["label"] for c in package.service_categories}
    by_id = {}
    for group in (package.scoped_criteria, package.category_scope_items):
        for obj in group:
            by_id[obj["canonical_id"]] = obj.get("category_scope") or ""
    issues = []
    for result in specialist_results:
        for finding in result.findings:
            claimed = finding["category_scope"] or ""
            if claimed and claimed not in known:
                issues.append({"specialist_id": result.specialist_id,
                               "finding_id": finding["finding_id"],
                               "issue": "CATEGORY_NOT_CANONICAL",
                               "claimed_category": claimed})
                continue
            if not claimed:
                continue
            for cid in finding["canonical_ids"]:
                owner = by_id.get(cid)
                if owner is not None and owner and owner != claimed:
                    issues.append({"specialist_id": result.specialist_id,
                                   "finding_id": finding["finding_id"],
                                   "issue": "CITED_OBJECT_BELONGS_TO_OTHER_CATEGORY",
                                   "claimed_category": claimed,
                                   "canonical_category": owner,
                                   "canonical_id": cid})
    return issues


def detect_evaluation_scope_mismatches(package: CanonicalPackage) -> list:
    """Categories that are evaluated but have no canonical scope material
    (or vice versa) -- a genuine cross-domain signal a bidder needs, and
    exactly the kind of thing no single specialist can see."""
    mismatches = []
    for cat in package.service_categories:
        if cat["criterion_count"] and not cat["scope_item_count"]:
            mismatches.append({"category": cat["label"], "canonical_id": cat["canonical_id"],
                               "issue": "EVALUATED_CATEGORY_WITH_NO_CANONICAL_SCOPE_ITEMS",
                               "criterion_count": cat["criterion_count"]})
        elif cat["scope_item_count"] and not cat["criterion_count"]:
            mismatches.append({"category": cat["label"], "canonical_id": cat["canonical_id"],
                               "issue": "SCOPED_CATEGORY_WITH_NO_EVALUATION_CRITERIA",
                               "scope_item_count": cat["scope_item_count"]})
    return mismatches


def enforce_canonical_authority(findings: list, package: CanonicalPackage) -> tuple:
    """Canonical source authority beats agent opinion (task sections 13 /
    21). A specialist FACT that cites a canonical object but contradicts
    that object's own canonical CATEGORY SCOPE is demoted to
    SPECIALIST_INTERPRETATION and flagged for human confirmation -- never
    allowed to stand as fact, and never resolved by how many specialists
    agreed with it."""
    by_id = {}
    for group in (package.scoped_criteria, package.category_scope_items):
        for obj in group:
            by_id[obj["canonical_id"]] = obj.get("category_scope") or ""
    overrides = []
    for finding in findings:
        if finding["finding_type"] != FINDING_FACT:
            continue
        claimed = finding.get("category_scope") or ""
        if not claimed:
            continue
        conflicting = [cid for cid in finding["canonical_ids"]
                       if by_id.get(cid) and by_id[cid] != claimed]
        if not conflicting:
            continue
        finding["authority"] = AUTHORITY_SPECIALIST
        finding["support_status"] = SUPPORT_UNSUPPORTED
        finding["human_confirmation_required"] = True
        overrides.append({
            "finding_id": finding["finding_id"],
            "reason": "CANONICAL_CATEGORY_SCOPE_OVERRIDES_SPECIALIST_CLAIM",
            "claimed_category": claimed,
            "canonical_categories": sorted({by_id[cid] for cid in conflicting}),
        })
    return findings, overrides


# ═══════════════════════════════════════════════════════════════════════
# 10. Reconciliation / assurance stage (task section 13)
# ═══════════════════════════════════════════════════════════════════════

_RECONCILIATION_RULES = """
You are the CROSS-DOMAIN RECONCILIATION stage of a multi-agent procurement analysis.
Six bounded specialists have each analysed one domain of the SAME canonical procurement
package. You receive their structured findings plus a MINIMAL canonical index (ids and
labels only). You do NOT have the RFP and must not ask for it.

HARD RULES:
- Canonical source authority is higher than any specialist's interpretation. If a
  specialist finding conflicts with the canonical index, the canonical index wins.
- Do NOT majority-vote facts. Two specialists agreeing does not make something true.
- Do NOT invent a new requirement, obligation, date, weight or category.
- A domain marked incomplete below is INCOMPLETE: say so, do not fill the gap with
  your own reasoning.
- Different service categories are different scopes, never a contradiction.
- Cite canonical_ids (from the index) and/or finding_ids (from the specialists) for
  every item you raise.

Identify: cross-domain contradictions, cross-domain risks and dependencies
(schedule/submission dependencies, commercial obligations affecting proposed delivery,
evaluation-vs-scope mismatches), unresolved ambiguities, and overall completeness.

Return ONLY JSON:
{"cross_domain_risks": [{"title": "...", "detail": "...", "severity": "HIGH|MEDIUM|LOW",
   "domains": ["<specialist_id>", ...], "canonical_ids": [...], "finding_ids": [...]}],
 "contradictions": [{"title": "...", "detail": "...", "domains": [...],
   "canonical_ids": [...], "finding_ids": [...]}],
 "unresolved_ambiguities": [{"title": "...", "detail": "...", "canonical_ids": [...]}],
 "human_confirmation_required": [{"title": "...", "detail": "...", "canonical_ids": [...]}],
 "completeness_note": "<1-3 sentences>"}
"""


def build_reconciliation_input(package: CanonicalPackage, specialist_results: list) -> dict:
    """The MINIMAL payload the reconciliation stage receives: specialist
    structured outputs plus only the canonical identity/index data needed
    to validate them (ids and labels -- never clause text, never response
    prompts, never raw document text). Task section 13's explicit "it must
    NOT reread the full RFP"."""
    index = {
        "identity": {k: v["value"] for k, v in
                     list(dict(package.identity)["fields"].items())[:12]},
        "service_categories": [{"canonical_id": c["canonical_id"], "label": c["label"],
                                "criterion_count": c["criterion_count"],
                                "scope_item_count": c["scope_item_count"]}
                               for c in package.service_categories],
        "requirement_ids": [r["canonical_id"] for r in package.requirements],
        "criterion_index": [{"canonical_id": c["canonical_id"],
                             "category_scope": c["category_scope"],
                             "criterion": c["criterion"], "weight": c["weight"]}
                            for c in package.scoped_criteria],
        "obligation_index": [{"canonical_id": o["canonical_id"], "topic": o["topic"]}
                             for o in package.commercial_obligations],
        "milestone_index": [{"canonical_id": m["canonical_id"], "label": m["label"],
                             "scope_key": m["scope_key"],
                             "date_start": m["normalized_date_start"]}
                            for m in package.milestones],
        "submission": {k: v for k, v in dict(package.submission_mechanics).items()
                       if k in ("submission_deadline", "clarification_deadline")},
    }
    domains = []
    for result in specialist_results:
        domains.append({
            "specialist_id": result.specialist_id,
            "status": result.status,
            "domain_complete": result.status == STATUS_COMPLETE,
            "failure_reason": result.failure_reason,
            "findings": [{"finding_id": f["finding_id"], "finding_type": f["finding_type"],
                          "title": f["title"], "detail": f["detail"],
                          "category_scope": f["category_scope"],
                          "canonical_ids": f["canonical_ids"], "severity": f["severity"]}
                         for f in result.findings],
        })
    return {"canonical_index": index, "domains": domains}


@dataclass
class ReconciliationResult:
    reconciliation_version: str = RECONCILIATION_VERSION
    status: str = STATUS_NOT_RUN
    incomplete_domains: list = field(default_factory=list)
    reconciled_findings: list = field(default_factory=list)
    duplicate_findings: list = field(default_factory=list)
    orphaned_requirements: list = field(default_factory=list)
    category_scope_inconsistencies: list = field(default_factory=list)
    evaluation_scope_mismatches: list = field(default_factory=list)
    canonical_authority_overrides: list = field(default_factory=list)
    cross_domain_risks: list = field(default_factory=list)
    contradictions: list = field(default_factory=list)
    unresolved_ambiguities: list = field(default_factory=list)
    human_confirmation_required: list = field(default_factory=list)
    completeness_note: str = ""
    failure_reason: str | None = None
    duration_seconds: float = 0.0
    usage: dict = field(default_factory=dict)


def _validated_index_items(items, permitted_ids: set, *, keep_finding_ids: set) -> list:
    """Reconciliation output grounding: every id must be a real canonical
    id or a real specialist finding id. Unknown ids are dropped, and an
    item left with no grounding at all is dropped entirely -- the
    reconciliation stage cannot introduce a source the package never had."""
    out = []
    for item in (items or []):
        if not isinstance(item, dict):
            continue
        cids = [str(c) for c in (item.get("canonical_ids") or []) if str(c) in permitted_ids]
        fids = [str(f) for f in (item.get("finding_ids") or []) if str(f) in keep_finding_ids]
        title = _clip(item.get("title"), 200)
        detail = _clip(item.get("detail"), 900)
        if not (title or detail) or not (cids or fids):
            continue
        severity = str(item.get("severity") or "MEDIUM").strip().upper()
        out.append({
            "title": title, "detail": detail,
            "severity": severity if severity in _SEVERITIES else "MEDIUM",
            "domains": [d for d in (item.get("domains") or []) if d in SPECIALIST_IDS],
            "canonical_ids": cids, "finding_ids": fids,
            "authority": AUTHORITY_SPECIALIST,
        })
    return out


def run_reconciliation(package: CanonicalPackage, specialist_results: list, *, client,
                       telemetry: list, telemetry_context: dict | None = None
                       ) -> ReconciliationResult:
    """The single bounded reconciliation stage. Deterministic cross-domain
    checks run FIRST (and stand on their own even if the model call
    fails); the model call then adds cross-domain contradictions, risks
    and dependencies over the specialists' structured outputs plus the
    minimal canonical index."""
    t0 = time.monotonic()
    out = ReconciliationResult()
    out.incomplete_domains = [
        {"specialist_id": r.specialist_id, "status": r.status, "reason": r.failure_reason}
        for r in specialist_results if r.status != STATUS_COMPLETE]

    merged, duplicates = consolidate_findings(specialist_results)
    merged, overrides = enforce_canonical_authority(merged, package)
    out.reconciled_findings = merged
    out.duplicate_findings = duplicates
    out.canonical_authority_overrides = overrides
    out.orphaned_requirements = detect_orphaned_requirements(package, specialist_results)
    out.category_scope_inconsistencies = detect_category_scope_inconsistencies(
        package, specialist_results)
    out.evaluation_scope_mismatches = detect_evaluation_scope_mismatches(package)
    out.unresolved_ambiguities = [
        {"title": f["title"], "detail": f["detail"], "canonical_ids": f["canonical_ids"],
         "produced_by": f["produced_by"]}
        for f in merged if f["finding_type"] == FINDING_AMBIGUITY]

    payload = build_reconciliation_input(package, specialist_results)
    prompt = (_RECONCILIATION_RULES.strip() + "\n\nSPECIALIST OUTPUTS AND CANONICAL INDEX:\n"
              + json.dumps(payload, indent=1, ensure_ascii=False, default=str))
    finding_ids = {f["finding_id"] for r in specialist_results for f in r.findings}
    try:
        before = len(telemetry)
        data = _call_model(prompt, client=client, call_label="reconciliation",
                           max_tokens=RECONCILIATION_MAX_OUTPUT_TOKENS, telemetry=telemetry,
                           telemetry_context=telemetry_context)
        rows = telemetry[before:]
        out.usage = {
            "calls": len(rows),
            "input_tokens": sum(r.get("input_tokens") or 0 for r in rows),
            "output_tokens": sum(r.get("output_tokens") or 0 for r in rows),
            "request_bytes": sum(r.get("request_bytes") or 0 for r in rows),
            "model": FULL_ANALYSIS_MODEL,
        }
        out.cross_domain_risks = _validated_index_items(
            data.get("cross_domain_risks"), set(package.canonical_ids), keep_finding_ids=finding_ids)
        out.contradictions = _validated_index_items(
            data.get("contradictions"), set(package.canonical_ids), keep_finding_ids=finding_ids)
        out.unresolved_ambiguities += _validated_index_items(
            data.get("unresolved_ambiguities"), set(package.canonical_ids),
            keep_finding_ids=finding_ids)
        out.human_confirmation_required = _validated_index_items(
            data.get("human_confirmation_required"), set(package.canonical_ids),
            keep_finding_ids=finding_ids)
        out.completeness_note = _clip(data.get("completeness_note"), 600)
        out.status = STATUS_COMPLETE
    except Exception as exc:
        # The deterministic half above is already populated and stays --
        # a reconciliation model failure degrades the stage, it does not
        # destroy the specialists' work.
        out.status = STATUS_FAILED
        out.failure_reason = f"{type(exc).__name__}: {exc}"[:400]
    out.human_confirmation_required += [
        {"title": f["title"], "detail": f["detail"], "canonical_ids": f["canonical_ids"],
         "finding_ids": [f["finding_id"]], "domains": list(f["produced_by"]),
         "severity": f["severity"], "authority": f["authority"]}
        for f in merged if f["human_confirmation_required"]]
    out.duration_seconds = round(time.monotonic() - t0, 6)
    return out


# ═══════════════════════════════════════════════════════════════════════
# 11. Full Analysis orchestration (task sections 11 / 14 / 15)
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class FullAnalysisResult:
    bid_id: int | None = None
    analysis_run_id: int | None = None
    analysis_version: str = FULL_ANALYSIS_VERSION
    canonical_snapshot_digest: str = ""
    specialist_statuses: dict = field(default_factory=dict)
    specialist_results: list = field(default_factory=list)
    reconciliation: dict = field(default_factory=dict)
    reconciled_findings: list = field(default_factory=list)
    unresolved_gaps: list = field(default_factory=list)
    cross_domain_risks: list = field(default_factory=list)
    ambiguities: list = field(default_factory=list)
    completeness_status: str = COMPLETENESS_FAILED
    human_confirmation_required: list = field(default_factory=list)
    source_refs: list = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""
    wall_seconds: float = 0.0
    usage: dict = field(default_factory=dict)
    telemetry: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def run_full_analysis(package: CanonicalPackage, api_key: str | None = None, *,
                      client=None, max_concurrency: int = MAX_SPECIALIST_CONCURRENCY,
                      specialists: tuple = SPECIALIST_IDS,
                      telemetry_context: dict | None = None,
                      on_specialist_done=None,
                      on_event=None) -> FullAnalysisResult:
    """Run the six bounded specialists (concurrently, bounded) over one
    canonical package, then the single reconciliation stage.

    EXPLICIT execution mode only (task section 17): nothing calls this as
    part of ingestion or of Fast Analysis. Total provider calls are
    exactly one per specialist plus one for reconciliation -- no retries,
    no cascades, and no specialist ever receives the whole package.

    Thread safety: each specialist builds its own read-only slice from the
    frozen package and returns its own SpecialistResult; nothing is shared
    and mutated. Telemetry rows are collected per specialist and merged in
    a fixed specialist order after the pool drains, so the aggregate is
    deterministic in ORDER as well as content.

    `on_event(event_type, payload)` (MA-2A, optional, purely observational)
    is invoked at REAL execution boundaries only -- never on a timer:
    SPECIALIST_QUEUED (before submission), SPECIALIST_STARTED (inside the
    worker, immediately before the specialist's own work begins),
    SPECIALIST_COMPLETED / SPECIALIST_FAILED (inside the worker, the moment
    `run_specialist` returns, carrying the SpecialistResult),
    RECONCILIATION_STARTED, RECONCILIATION_COMPLETED / RECONCILIATION_FAILED.
    It may be called from worker threads concurrently; an exception raised
    by the observer is swallowed and never affects the analysis."""
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    if client is None:
        client = get_anthropic_client(api_key=api_key)

    ordered = [s for s in SPECIALIST_IDS if s in specialists]
    per_specialist_telemetry: dict = {s: [] for s in ordered}

    def _emit(event_type: str, payload: dict) -> None:
        if on_event is None:
            return
        try:
            on_event(event_type, payload)
        except Exception:
            pass

    for sid in ordered:
        _emit(EVENT_SPECIALIST_QUEUED, {"specialist_id": sid})

    def _run(specialist_id: str):
        _emit(EVENT_SPECIALIST_STARTED, {"specialist_id": specialist_id})
        outcome = run_specialist(package, specialist_id, client=client,
                                 telemetry=per_specialist_telemetry[specialist_id],
                                 telemetry_context=telemetry_context)
        _emit(EVENT_SPECIALIST_COMPLETED if outcome.status == STATUS_COMPLETE
              else EVENT_SPECIALIST_FAILED,
              {"specialist_id": specialist_id, "result": outcome})
        return outcome

    results_by_id: dict = {}
    with ThreadPoolExecutor(max_workers=max(1, min(max_concurrency, len(ordered) or 1))) as pool:
        futures = {pool.submit(_run, sid): sid for sid in ordered}
        for future, sid in futures.items():
            try:
                results_by_id[sid] = future.result()
            except Exception as exc:  # pragma: no cover - run_specialist catches its own
                failed = SpecialistResult(specialist_id=sid, bid_id=package.bid_id)
                failed.status = STATUS_FAILED
                failed.failure_reason = f"{type(exc).__name__}: {exc}"[:400]
                results_by_id[sid] = failed
            if on_specialist_done is not None:
                try:
                    on_specialist_done(results_by_id[sid])
                except Exception:
                    pass

    specialist_results = [results_by_id[sid] for sid in ordered]
    telemetry: list = []
    for sid in ordered:
        telemetry.extend(per_specialist_telemetry[sid])

    _emit(EVENT_RECONCILIATION_STARTED, {
        "incomplete_domains": [r.specialist_id for r in specialist_results
                               if r.status != STATUS_COMPLETE]})
    reconciliation = run_reconciliation(package, specialist_results, client=client,
                                        telemetry=telemetry,
                                        telemetry_context=telemetry_context)
    _emit(EVENT_RECONCILIATION_COMPLETED if reconciliation.status == STATUS_COMPLETE
          else EVENT_RECONCILIATION_FAILED, {"reconciliation": reconciliation})

    completed = [r for r in specialist_results if r.status == STATUS_COMPLETE]
    if not completed:
        completeness = COMPLETENESS_FAILED
    elif len(completed) == len(ordered) and reconciliation.status == STATUS_COMPLETE:
        completeness = COMPLETENESS_COMPLETE
    else:
        completeness = COMPLETENESS_PARTIAL

    gaps = [f for f in reconciliation.reconciled_findings if f["finding_type"] == FINDING_GAP]
    gaps += [{"finding_type": FINDING_GAP, "title": "Canonical requirement not analysed",
              "detail": f"{o['description']}", "canonical_ids": [o["canonical_id"]],
              "produced_by": [], "authority": AUTHORITY_CANONICAL,
              "severity": "MEDIUM"}
             for o in reconciliation.orphaned_requirements]
    gaps += [{"finding_type": FINDING_GAP,
              "title": f"Incomplete domain: {d['specialist_id']}",
              "detail": f"Specialist {d['specialist_id']} did not complete "
                        f"({d['reason'] or d['status']}); this domain of the Full Analysis "
                        f"is incomplete.",
              "canonical_ids": [], "produced_by": [d["specialist_id"]],
              "authority": AUTHORITY_CANONICAL, "severity": "HIGH"}
             for d in reconciliation.incomplete_domains]

    source_refs = []
    for result in specialist_results:
        for ref in result.source_refs:
            if ref not in source_refs:
                source_refs.append(ref)

    usage_rows = telemetry
    result = FullAnalysisResult(
        bid_id=package.bid_id,
        analysis_run_id=package.analysis_run_id,
        canonical_snapshot_digest=package.package_digest,
        specialist_statuses={r.specialist_id: r.status for r in specialist_results},
        specialist_results=[r.as_dict() for r in specialist_results],
        reconciliation=asdict(reconciliation),
        reconciled_findings=reconciliation.reconciled_findings,
        unresolved_gaps=gaps,
        cross_domain_risks=(reconciliation.cross_domain_risks
                            + reconciliation.contradictions),
        ambiguities=reconciliation.unresolved_ambiguities,
        completeness_status=completeness,
        human_confirmation_required=reconciliation.human_confirmation_required,
        source_refs=source_refs,
        started_at=started.isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
        wall_seconds=round(time.monotonic() - t0, 6),
        usage={
            "model": FULL_ANALYSIS_MODEL,
            "total_calls": sum(1 for r in usage_rows if r.get("provider_call_attempted")),
            "input_tokens": sum(r.get("input_tokens") or 0 for r in usage_rows),
            "output_tokens": sum(r.get("output_tokens") or 0 for r in usage_rows),
            "request_bytes": sum(r.get("request_bytes") or 0 for r in usage_rows),
            "by_specialist": {r.specialist_id: dict(r.usage) for r in specialist_results},
            "reconciliation": dict(reconciliation.usage),
        },
        telemetry=telemetry,
    )
    return result


# ═══════════════════════════════════════════════════════════════════════
# 12. MA-2A: Full Analysis input fingerprint (freshness / reuse contract)
# ═══════════════════════════════════════════════════════════════════════

#: Version of the fingerprint recipe itself. Bumping it invalidates every
#: persisted Full Analysis fingerprint.
FULL_ANALYSIS_FINGERPRINT_VERSION = "ma-2a-fp-1"


def canonical_content_digest(package: CanonicalPackage) -> str:
    """sha256 over EVERY canonical object type the specialists can be given
    (all of CANONICAL_OBJECT_TYPES, in fixed order). `package.package_digest`
    (MA-1) deliberately stays unchanged, but it omits document
    relationships, package completeness and service categories -- all of
    which reach a specialist -- so the Full Analysis fingerprint covers this
    complete digest as well. Pure; excludes bid_id / analysis_run_id, so the
    same canonical truth produces the same digest regardless of which Fast
    Analysis run it was assembled from."""
    return _digest({t: [_thaw(o) for o in package.objects_of_type(t)]
                    for t in CANONICAL_OBJECT_TYPES})


def specialist_contract_digests() -> dict:
    """Per-specialist contract/prompt identity: the declared version plus a
    digest of everything that shapes that specialist's behaviour -- its
    brief, the shared rules, its permitted input types, the model and its
    output ceiling. A prompt edit therefore invalidates prior results even
    if someone forgets to bump SPECIALIST_VERSION."""
    return {
        sid: {
            "specialist_version": SPECIALIST_VERSION,
            "contract_digest": _digest({
                "brief": SPECIALIST_BRIEFS[sid],
                "shared_rules": _SHARED_RULES,
                "category_rules_fn": "allowed_category_rules_v1",
                "input_types": sorted(SPECIALIST_INPUT_TYPES[sid]),
                "model": FULL_ANALYSIS_MODEL,
                "max_tokens": SPECIALIST_MAX_OUTPUT_TOKENS,
                "max_items": MAX_ITEMS_PER_SLICE_SECTION,
                "max_chars": MAX_TEXT_CHARS_PER_ITEM,
            }),
        }
        for sid in SPECIALIST_IDS
    }


def reconciliation_contract_digest() -> str:
    return _digest({"version": RECONCILIATION_VERSION, "rules": _RECONCILIATION_RULES,
                    "model": FULL_ANALYSIS_MODEL,
                    "max_tokens": RECONCILIATION_MAX_OUTPUT_TOKENS})


def full_analysis_fingerprint_inputs(package: CanonicalPackage) -> dict:
    """Exactly what a Full Analysis result depends on -- and nothing else
    (no bid/run ids, no timestamps, no UI state)."""
    return {
        "fingerprint_version": FULL_ANALYSIS_FINGERPRINT_VERSION,
        "architecture_version": FULL_ANALYSIS_VERSION,
        "canonical_snapshot_digest": package.package_digest,
        "canonical_content_digest": canonical_content_digest(package),
        "specialists": specialist_contract_digests(),
        "reconciliation": {"reconciliation_version": RECONCILIATION_VERSION,
                           "contract_digest": reconciliation_contract_digest()},
    }


def compute_full_analysis_fingerprint(package: CanonicalPackage) -> str:
    """Deterministic sha256 (same sorted-key JSON convention as
    proposal_intelligence.compute_package_digest / evidence_strengthening.
    compute_input_fingerprint). A persisted Full Analysis result is reusable
    only when this matches exactly."""
    return _digest(full_analysis_fingerprint_inputs(package))
