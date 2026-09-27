"""
check_run_service.py -- CHECK-2B: Durable Proposal Assurance (CHECK) runs.

The ONE orchestration boundary that makes CHECK-2A's pure, compute-and-return
adjudication (check_coverage.run_check_coverage) durable, reproducible,
reopenable and safe against duplicate model spending. It mirrors MA-2A's
full_analysis_service.py architecture exactly:

    start_check_run(...)        inputs -> deterministic input fingerprint ->
                                ONE idempotent, advisory-locked start RPC
                                (CREATED / ACTIVE_RUN_EXISTS / REUSED_COMPLETE /
                                EXISTING_FAILED / EXISTING_PARTIAL) -> only for
                                CREATED: execution (background thread or inline)
    get_check_run_status(...)   durable run + ordered event log + derived
                                counts + stale-run detection (reads only)
    get_check_run_result(...)   the persisted adjudication, reconstructed into
                                the CHECK-2A CheckCoverageResult contract with
                                ZERO provider calls
    mark_check_run_stuck(...)   explicit, user-initiated FAILED marking of a
                                genuinely stale run (never an automatic rerun)

It does NOT duplicate any CHECK-2A logic: the adjudication itself is
check_coverage.run_check_coverage, observed through its `on_event` hook, which
fires only at real execution boundaries. Nothing here re-judges a buyer
object; persistence only validates (fail closed) and stores.

Persistence reuses analysis_runs / analysis_results (analysis_mode='CHECK')
plus migration 022's check_run_events / check_semantic_batches /
check_adjudications / check_adjudication_evidence. Every write is one of
migration 022's three service_role-only RPCs (database.start_check_run /
record_check_run_event / finalize_check_run). MIGRATION 022 IS
CREATED_NOT_APPLIED: until a commissioning task applies it, these RPCs do not
exist live.

Provider accounting: the default adjudicator is full_analysis._call_model
(through check_coverage), which records every call through the EXISTING
model_usage_events path; this service passes telemetry_context
{workflow='check_coverage', analysis_run_id=<CHECK run>} so each call links to
the durable run -- no second usage-accounting system.

Background execution has the same honest limits as MA-2A: an in-process
daemon thread (durable state, not durable execution). A process death leaves
a visibly non-terminal run that `is_check_run_stuck` surfaces; nothing here
ever auto-reruns or spends provider calls on its own.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone

import check_coverage as cc
import database as db
import submission_package as sp

# ═══════════════════════════════════════════════════════════════════════
# Versions / vocabularies
# ═══════════════════════════════════════════════════════════════════════

#: Durable-run architecture version (this module + migration 022).
CHECK2B_ARCHITECTURE_VERSION = "check-2b.1.0"
#: Version of the fingerprint recipe itself; bumping it invalidates every
#: persisted CHECK fingerprint.
CHECK_FINGERPRINT_VERSION = "check-2b-fp-1"

CHECK_ENGINE_VERSION = f"check-coverage-{cc.CHECK2A_CONTRACT_VERSION}/durable-{CHECK2B_ARCHITECTURE_VERSION}"

MODE_CHECK = "CHECK"
TELEMETRY_WORKFLOW = "check_coverage"
PROVIDER_ANTHROPIC = "anthropic"

RUN_QUEUED = "QUEUED"
RUN_RUNNING = "RUNNING"
RUN_COMPLETE = "COMPLETE"
RUN_PARTIAL = "PARTIAL"
RUN_FAILED = "FAILED"
TERMINAL_RUN_STATUSES = (RUN_COMPLETE, RUN_PARTIAL, RUN_FAILED)

BATCH_COMPLETE = "COMPLETE"
BATCH_PARTIAL = "PARTIAL"
BATCH_FAILED = "FAILED"

OUTCOME_CREATED = "CREATED"
OUTCOME_ACTIVE_RUN_EXISTS = "ACTIVE_RUN_EXISTS"
OUTCOME_REUSED_COMPLETE = "REUSED_COMPLETE"
OUTCOME_EXISTING_FAILED = "EXISTING_FAILED"
OUTCOME_EXISTING_PARTIAL = "EXISTING_PARTIAL"

# Event vocabulary (mirrors migration 022's CHECK constraint exactly).
EVENT_RUN_CREATED = "RUN_CREATED"
EVENT_RUN_STARTED = "RUN_STARTED"
EVENT_BUYER_SCOPE_CLASSIFIED = "BUYER_SCOPE_CLASSIFIED"
EVENT_CANDIDATE_RETRIEVAL_COMPLETE = "CANDIDATE_RETRIEVAL_COMPLETE"
EVENT_DETERMINISTIC_ADJUDICATION_COMPLETE = "DETERMINISTIC_ADJUDICATION_COMPLETE"
EVENT_SEMANTIC_BATCH_STARTED = "SEMANTIC_BATCH_STARTED"
EVENT_SEMANTIC_BATCH_COMPLETED = "SEMANTIC_BATCH_COMPLETED"
EVENT_SEMANTIC_BATCH_FAILED = "SEMANTIC_BATCH_FAILED"
EVENT_EVIDENCE_ASSURANCE_COMPLETE = "EVIDENCE_ASSURANCE_COMPLETE"
EVENT_RUN_COMPLETED = "RUN_COMPLETED"
EVENT_RUN_PARTIAL = "RUN_PARTIAL"
EVENT_RUN_FAILED = "RUN_FAILED"
EVENT_TYPES = (EVENT_RUN_CREATED, EVENT_RUN_STARTED, EVENT_BUYER_SCOPE_CLASSIFIED,
               EVENT_CANDIDATE_RETRIEVAL_COMPLETE, EVENT_DETERMINISTIC_ADJUDICATION_COMPLETE,
               EVENT_SEMANTIC_BATCH_STARTED, EVENT_SEMANTIC_BATCH_COMPLETED, EVENT_SEMANTIC_BATCH_FAILED,
               EVENT_EVIDENCE_ASSURANCE_COMPLETE, EVENT_RUN_COMPLETED, EVENT_RUN_PARTIAL, EVENT_RUN_FAILED)

#: Provider termination values that mean "finished normally".
NORMAL_STOP_REASONS = frozenset({None, "end_turn", "stop_sequence"})
STOP_REASON_MAX_TOKENS = "max_tokens"
PARSE_COMPLETE = "COMPLETE"
PARSE_RECOVERED_TRUNCATED = "RECOVERED_TRUNCATED"
PARSE_FAILED = "FAILED"

#: How the semantic adjudications were produced (recorded on the run, never
#: part of the fingerprint): live provider calls, or an injected adjudicator
#: (tests), or a deterministic replay of a recorded, already-validated live
#: model output (CHECK-2B Calgary persistence commissioning -- zero spend).
SOURCE_PROVIDER = "PROVIDER"
SOURCE_INJECTED = "INJECTED_ADJUDICATOR"
SOURCE_REPLAY = "REPLAY_OF_RECORDED_LIVE_OUTPUT"

#: Stale-run policy -- ONE place, versioned. A CHECK run is a bounded plan
#: (seconds) plus <= check_coverage.MODEL_CALL_HARD_CEILING sequential
#: semantic calls, each durably evented; 10 minutes without any durable
#: progress, or 45 minutes alive, is not merely slow. Detection only:
#: nothing ever auto-fails, auto-reruns or spends on a stale run.
STALE_RUN_POLICY = {"policy_version": "check-2b-stale-1",
                    "no_progress_seconds": 10 * 60,
                    "max_run_age_seconds": 45 * 60}

EXECUTION_BACKGROUND = "background"
EXECUTION_INLINE = "inline"


class CheckRunError(RuntimeError):
    """Base error for this service."""


class NoCheckInputsError(CheckRunError):
    """The buyer canonical source run or the bidder package snapshot is missing."""


class RunNotFoundError(CheckRunError):
    """The requested CHECK run does not exist for this bid."""


class RunNotStuckError(CheckRunError):
    """mark_check_run_stuck was called on a run that is not stale."""


# ═══════════════════════════════════════════════════════════════════════
# Inputs
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class CheckInputs:
    """Everything CHECK-2A reads. Buyer side: the canonical package (built
    from the source Fast Analysis run's raw snapshot), the SAME raw
    requirements (verbatim wording recovery) and the buyer source documents
    (the scope gate reads their deeming statements). Bidder side: the
    migration-021-persisted submission package of `package_snapshot_id`."""
    bid_id: int
    source_analysis_run_id: int
    package_snapshot_id: int
    canonical_package: object
    raw_requirements: list
    buyer_documents: list
    submission_package: sp.SubmissionPackage


def load_check_inputs(bid_id: int, organization_id: str, *, package_snapshot_id: int | None = None,
                      source_run_id: int | None = None) -> CheckInputs:
    """Read-only, zero model calls. The buyer path mirrors
    analysis_service.build_full_analysis_package (documents always retained:
    the CHECK scope gate needs them); the bidder path is CHECK-1.1's
    tenancy.load_submission_evidence_package_for_organization (a fresh read
    of migration-021 rows, bid-checked). Default snapshot: the most recent
    package snapshot of this bid that has a persisted evidence registry."""
    import analysis_service
    import full_analysis as fa
    import full_analysis_service as fas
    import tenancy
    from extractor import extract_document_with_metadata

    try:
        source = fas._resolve_source_run(bid_id, source_run_id)
    except fas.NoCompleteFastAnalysisError as exc:
        raise NoCheckInputsError(str(exc))
    result = analysis_service.load_raw_fast_analysis_result(int(source["id"]))
    if isinstance(result, str):
        raise NoCheckInputsError(f"analysis run {source['id']} has no raw Fast Analysis snapshot ({result})")
    documents = []
    for d in db.get_documents(bid_id):
        if d.get("doc_type") != "RFP / Source" or not d.get("storage_path"):
            continue
        data = db.download_file(d["storage_path"])
        if data:
            documents.append((d["name"], extract_document_with_metadata(data, d["name"])[0]))
    cpkg = fa.build_canonical_package(result, bid_id=bid_id, analysis_run_id=int(source["id"]),
                                      documents=documents)
    if package_snapshot_id is None:
        for snap in db.get_proposal_package_snapshots(bid_id):
            if db.get_submission_documents(bid_id, int(snap["id"])):
                package_snapshot_id = int(snap["id"])
                break
    if package_snapshot_id is None:
        raise NoCheckInputsError(f"bid {bid_id} has no persisted submission evidence package")
    bidder = tenancy.load_submission_evidence_package_for_organization(bid_id, organization_id,
                                                                       int(package_snapshot_id))
    return CheckInputs(bid_id=int(bid_id), source_analysis_run_id=int(source["id"]),
                       package_snapshot_id=int(package_snapshot_id), canonical_package=cpkg,
                       raw_requirements=list(result.requirements or []), buyer_documents=documents,
                       submission_package=bidder)


# ═══════════════════════════════════════════════════════════════════════
# Fingerprint (section 4) -- pure
# ═══════════════════════════════════════════════════════════════════════

def _digest(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _sha(text) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def architecture_versions() -> dict:
    return {"check2a_contract_version": cc.CHECK2A_CONTRACT_VERSION,
            "check2b_architecture_version": CHECK2B_ARCHITECTURE_VERSION,
            "scope_gate_version": cc.SCOPE_GATE_VERSION,
            "retrieval_version": cc.RETRIEVAL_VERSION,
            "deterministic_rule_version": cc.DETERMINISTIC_RULE_VERSION,
            "adjudication_version": cc.ADJUDICATION_VERSION,
            "prompt_schema_version": cc.PROMPT_SCHEMA_VERSION,
            "check1_contract_version": sp.CHECK1_CONTRACT_VERSION}


def model_contract() -> dict:
    """Model identity/configuration for the semantic batches, plus a digest of
    the prompt rules, so a prompt / model / bound edit invalidates prior runs
    even if nobody bumps a version (MA-2A precedent)."""
    import full_analysis as fa
    return {"provider": PROVIDER_ANTHROPIC, "model": fa.FULL_ANALYSIS_MODEL,
            "max_output_tokens": cc.MODEL_MAX_OUTPUT_TOKENS, "retry_attempts": cc.MODEL_RETRY_ATTEMPTS,
            "call_target": cc.MODEL_CALL_TARGET, "call_hard_ceiling": cc.MODEL_CALL_HARD_CEILING,
            "max_objects_per_batch": cc.MAX_OBJECTS_PER_BATCH,
            "max_evidence_per_object": cc.MAX_EVIDENCE_PER_OBJECT,
            "max_evidence_per_batch": cc.MAX_EVIDENCE_PER_BATCH,
            "max_section_text_chars": cc.MAX_SECTION_TEXT_CHARS,
            "max_other_item_chars": cc.MAX_OTHER_ITEM_CHARS,
            "max_elements_per_object": cc.MAX_ELEMENTS_PER_OBJECT,
            "prompt_rules_sha256": _sha(cc._ADJUDICATION_RULES)}


def buyer_fingerprint_inputs(canonical_package, raw_requirements, buyer_documents) -> dict:
    """Buyer side: the canonical digests, the exact buyer objects CHECK-2A
    reads (verbatim wording, category, applicability, weights / variants,
    thresholds, response prompts, source refs, required forms), their
    expected evidence roles, and every buyer source document's normalized
    text (the scope gate's deeming statements)."""
    import full_analysis as fa
    objects = cc.buyer_objects_from_canonical_package(canonical_package, raw_requirements)
    expected = {o.object_id: sp.derive_expected_evidence(o.requirement_dict()).to_dict()
                for o in objects if o.object_type == cc.OBJECT_REQUIREMENT}
    docs = sorted(({"name": str(name), "normalized_text_sha256": _sha(cc._norm_text(text))}
                   for name, text in _document_pairs(buyer_documents)),
                  key=lambda x: (x["name"], x["normalized_text_sha256"]))
    return {"canonical_snapshot_digest": canonical_package.package_digest,
            "canonical_content_digest": fa.canonical_content_digest(canonical_package),
            "requirement_ids": [o.object_id for o in objects if o.object_type == cc.OBJECT_REQUIREMENT],
            "criterion_ids": [o.object_id for o in objects if o.object_type == cc.OBJECT_CRITERION],
            "buyer_objects_digest": _digest([o.to_dict() for o in objects]),
            "expected_evidence_digest": _digest(expected),
            "buyer_documents": docs}


def _document_pairs(buyer_documents):
    for entry in buyer_documents or []:
        if isinstance(entry, (tuple, list)) and len(entry) == 2:
            yield entry


def bidder_fingerprint_inputs(package: sp.SubmissionPackage) -> dict:
    """Bidder side: package identity, every document's role / logical-
    artifact / representation relationship, and the FULL evidence registry
    content (content, kind, location, structured value, provenance) --
    order-independent (sorted by id), never timestamps or row ids."""
    docs = sorted(({"submission_document_id": d.submission_document_id, "content_hash": d.content_hash,
                    "filename": d.filename, "package_path": d.package_path, "file_type": d.file_type,
                    "lifecycle_status": d.lifecycle_status, "included": d.included,
                    "document_role": d.document_role, "secondary_roles": list(d.role.secondary_roles),
                    "parse_status": d.parse_status, "page_count": d.page_count, "sheets": list(d.sheets),
                    "sections": [s.to_dict() for s in d.sections],
                    "logical_artifact_id": d.logical_artifact_id or d.submission_document_id,
                    "representation_relationship": d.representation_relationship,
                    "representation_of": d.representation_of, "duplicate_of": d.duplicate_of}
                   for d in package.documents), key=lambda x: x["submission_document_id"])
    items = sorted(({"evidence_id": i.evidence_id, "submission_document_id": i.submission_document_id,
                     "document_role": i.document_role, "kind": i.kind, "location": i.location,
                     "content": i.content, "structured_value": i.structured_value, "provenance": i.provenance}
                    for i in package.registry), key=lambda x: x["evidence_id"])
    return {"submission_package_digest": package.package_digest,
            "check1_contract_version": package.contract_version,
            "documents_digest": _digest(docs), "evidence_registry_digest": _digest(items),
            "evidence_item_count": len(items),
            "authoritative_artifacts": sorted(f"{d.logical_artifact_id or d.submission_document_id}:"
                                              f"{d.document_role}" for d in package.member_documents())}


def check_fingerprint_inputs(inputs: CheckInputs) -> dict:
    """Exactly what a CHECK result depends on -- and nothing else: no bid /
    run / event / snapshot row ids, no timestamps, no UI state."""
    return {"fingerprint_version": CHECK_FINGERPRINT_VERSION,
            "architecture": architecture_versions(),
            "model": model_contract(),
            "buyer": buyer_fingerprint_inputs(inputs.canonical_package, inputs.raw_requirements,
                                              inputs.buyer_documents),
            "bidder": bidder_fingerprint_inputs(inputs.submission_package)}


def compute_check_fingerprint(inputs: CheckInputs) -> str:
    """Deterministic sha256 (sorted-key JSON, the repository convention). A
    persisted CHECK result is reusable only when this matches exactly."""
    return _digest(check_fingerprint_inputs(inputs))


# ═══════════════════════════════════════════════════════════════════════
# Integrity validation before persistence (section 7) -- pure
# ═══════════════════════════════════════════════════════════════════════

def _element_ids(a: cc.CheckAdjudication) -> list:
    out = []
    for group in (a.addressed_elements, a.missing_elements, a.unverifiable_elements):
        for el in group or []:
            out.extend((el or {}).get("evidence_ids") or [])
    return out


def validate_result_for_persistence(result: cc.CheckCoverageResult, package: sp.SubmissionPackage, *,
                                    bid_id: int, expected_object_ids: list) -> list[str]:
    """Fail-closed re-validation of the in-memory adjudication BEFORE it may
    become durable truth (the database re-enforces the evidence part through
    migration 022's FK into submission_evidence_items). Returns violations;
    empty means persistable. Never repairs anything."""
    v: list[str] = []
    if int(package.bid_id) != int(bid_id):
        v.append(f"submission package belongs to bid {package.bid_id}, not {bid_id}")
    if result.bid_id is not None and int(result.bid_id) != int(bid_id):
        v.append(f"result belongs to bid {result.bid_id}, not {bid_id}")
    members = {d.submission_document_id for d in package.member_documents()}
    ids = [a.buyer_object_id for a in result.adjudications]
    if len(ids) != len(set(ids)):
        v.append("duplicate buyer object adjudication")
    if list(ids) != list(expected_object_ids):
        v.append("adjudicated buyer objects differ from the canonical buyer objects")
    methods = (cc.METHOD_SCOPE_GATE, cc.METHOD_DETERMINISTIC, cc.METHOD_MODEL, cc.METHOD_DERIVED)

    def _check_id(oid, eid, where):
        if not isinstance(eid, str) or not eid:
            v.append(f"{oid}: malformed evidence id in {where}")
        elif cc._BUYER_ID_RE.match(eid):
            v.append(f"{oid}: buyer-source id {eid!r} cited as bidder evidence ({where})")
        elif not package.registry.filter_valid([eid], bid_id=int(bid_id)):
            v.append(f"{oid}: evidence id {eid!r} is unknown or not evidence of bid {bid_id} ({where})")
        else:
            item = package.registry.get(eid, bid_id=int(bid_id))
            if int(item.bid_id) != int(bid_id):
                v.append(f"{oid}: evidence {eid} belongs to bid {item.bid_id}")
            if item.submission_document_id not in members:
                v.append(f"{oid}: evidence {eid} comes from a non-authoritative representation")

    for a in result.adjudications:
        oid = a.buyer_object_id
        if a.status not in cc.STATUSES:
            v.append(f"{oid}: unknown status {a.status!r}")
        if a.assurance_scope not in cc.ASSURANCE_SCOPES:
            v.append(f"{oid}: unknown scope {a.assurance_scope!r}")
        if a.buyer_object_type not in (cc.OBJECT_REQUIREMENT, cc.OBJECT_CRITERION):
            v.append(f"{oid}: unknown object type {a.buyer_object_type!r}")
        if a.deterministic_or_model not in methods:
            v.append(f"{oid}: unknown adjudication method {a.deterministic_or_model!r}")
        if a.deterministic_or_model == cc.METHOD_MODEL and not a.batch_id:
            v.append(f"{oid}: model verdict without a batch id")
        if not (a.buyer_expectation or "").strip() and a.buyer_object_type == cc.OBJECT_CRITERION:
            v.append(f"{oid}: criterion without buyer expectation")
        for eid in a.evidence_ids:
            _check_id(oid, eid, "verdict")
        for eid in _element_ids(a):
            _check_id(oid, eid, "element")
        if a.status in (cc.STATUS_ADDRESSED, cc.STATUS_PARTIALLY_ADDRESSED) and not a.evidence_ids:
            v.append(f"{oid}: {a.status} without bidder evidence")
        if a.assurance_scope in cc.EXCLUDED_SCOPES and a.status != cc.STATUS_NOT_APPLICABLE:
            v.append(f"{oid}: non-submission scope {a.assurance_scope} carries status {a.status}")
        if a.status == cc.STATUS_NOT_ADDRESSED and a.assurance_scope not in cc.CHECKABLE_SCOPES:
            v.append(f"{oid}: NOT_ADDRESSED on non-response scope {a.assurance_scope}")
    return v


def evidence_refs(a: cc.CheckAdjudication, package: sp.SubmissionPackage) -> list[dict]:
    """The exact logical-artifact / provenance relation of every verdict-level
    evidence id (persisted beside the id; the id itself stays authoritative)."""
    out = []
    for eid in a.evidence_ids:
        it = package.registry.get(eid, bid_id=package.bid_id)
        doc = package.document(it.submission_document_id)
        out.append({"evidence_id": eid, "submission_document_id": it.submission_document_id,
                    "logical_artifact_id": doc.logical_artifact_id or doc.submission_document_id,
                    "document_role": it.document_role, "kind": it.kind, "filename": doc.filename,
                    "locator": (it.provenance or {}).get("locator"), "citation": it.citation()})
    return out


def adjudication_row(a: cc.CheckAdjudication, package: sp.SubmissionPackage) -> dict:
    row = a.to_dict()
    row["evidence_refs"] = evidence_refs(a, package)
    return row


# ═══════════════════════════════════════════════════════════════════════
# Semantic batch integrity (sections 11 / 12) -- pure
# ═══════════════════════════════════════════════════════════════════════

def effective_batch_status(*, objects: list, results: dict, stop_reason, parse_status, error) -> tuple:
    """(effective_status, reason). A batch is COMPLETE only when the
    adjudicator returned without error, the provider stopped normally, the
    output parsed completely and EVERY object of the batch was adjudicated.
    JSON that parsed is never enough (MA-2A.2 lesson): stop_reason=max_tokens
    or a truncation-recovered parse is PARTIAL when usable adjudications
    survived, FAILED when none did."""
    if error:
        return BATCH_FAILED, f"adjudicator error: {error}"[:300]
    missing = [oid for oid in objects
               if "MISSING_FROM_RESPONSE" in ((results.get(oid).validation or {}).get("downgrades") or [])
               or oid not in results]
    returned = len(objects) - len(missing)
    truncated = stop_reason == STOP_REASON_MAX_TOKENS or parse_status == PARSE_RECOVERED_TRUNCATED
    abnormal = stop_reason not in NORMAL_STOP_REASONS
    if parse_status == PARSE_FAILED or returned == 0:
        why = ("OUTPUT_TRUNCATED: provider stop_reason=max_tokens" if truncated else
               f"provider stop_reason={stop_reason}" if abnormal else "no parsable adjudication returned")
        return BATCH_FAILED, f"{why}; 0 of {len(objects)} object(s) adjudicated"
    if truncated:
        return BATCH_PARTIAL, (f"OUTPUT_TRUNCATED: provider stop_reason={stop_reason}, parse_status={parse_status}; "
                               f"{returned} of {len(objects)} object(s) adjudicated")
    if abnormal:
        return BATCH_PARTIAL, f"provider stop_reason={stop_reason}; {returned} of {len(objects)} object(s) adjudicated"
    if missing:
        return BATCH_PARTIAL, f"model omitted {len(missing)} object(s): {', '.join(missing)}"
    return BATCH_COMPLETE, None


def batch_record(payload: dict) -> dict:
    """The check_semantic_batches row for one SEMANTIC_BATCH_COMPLETED hook
    payload: objects, candidate evidence, alias map, structured model output,
    reconciled per-object outcome, provider termination metadata, usage and
    the effective status. Never the prompt text."""
    rows = payload.get("telemetry_rows") or []
    row = rows[-1] if rows else {}
    results = payload.get("results") or {}
    status, reason = effective_batch_status(objects=payload["objects"], results=results,
                                            stop_reason=payload.get("stop_reason"),
                                            parse_status=row.get("parse_status"), error=payload.get("error"))
    reconciled = {oid: {"status": a.status, "evidence_ids": list(a.evidence_ids),
                        "model_status": (a.validation or {}).get("model_status"),
                        "downgrades": list((a.validation or {}).get("downgrades") or []),
                        "rejected_evidence_ids": list((a.validation or {}).get("rejected_evidence_ids") or [])}
                  for oid, a in results.items()}
    parsed = payload.get("parsed")
    return {"batch_id": payload["batch_id"], "domain": payload.get("domain"),
            "buyer_object_ids": list(payload["objects"]),
            "candidate_evidence_ids": list(payload.get("candidate_evidence_ids") or []),
            "alias_to_evidence": dict(payload.get("alias_to_eid") or {}),
            "structured_output": parsed if isinstance(parsed, dict) else None,
            "reconciled_output": reconciled,
            "provider": PROVIDER_ANTHROPIC if row.get("provider_call_attempted") else None,
            "model": row.get("model"), "stop_reason": payload.get("stop_reason"),
            "parse_status": row.get("parse_status"), "effective_status": status, "failure_reason": reason,
            "input_tokens": row.get("input_tokens"), "output_tokens": row.get("output_tokens"),
            "latency_seconds": row.get("latency_seconds"), "prompt_chars": payload.get("prompt_chars"),
            "prompt_sha256": payload.get("prompt_sha256"),
            "provider_calls": sum(1 for r in rows if r.get("provider_call_attempted"))}


def run_integrity(batch_records: list) -> tuple:
    """(run status, reason) from the semantic batch records. Object statuses
    (HUMAN_REVIEW_REQUIRED / NOT_VERIFIABLE_FROM_FILES) never make a run
    partial -- they are legitimate completed CHECK outcomes."""
    bad = [b for b in batch_records if b["effective_status"] != BATCH_COMPLETE]
    if not bad:
        return RUN_COMPLETE, None
    return RUN_PARTIAL, "incomplete semantic batches: " + "; ".join(
        f"{b['batch_id']} {b['effective_status']} ({b.get('failure_reason')})" for b in bad)


# ═══════════════════════════════════════════════════════════════════════
# Payload builders
# ═══════════════════════════════════════════════════════════════════════

def _plan_counts(plan) -> dict:
    scope_counts = plan.summary()["scope_counts"]
    excluded = sum(n for s, n in scope_counts.items() if s in cc.EXCLUDED_SCOPES)
    reqs = sum(1 for o in plan.objects if o.object_type == cc.OBJECT_REQUIREMENT)
    return {"total_buyer_objects": len(plan.objects), "requirements": reqs,
            "criteria": len(plan.objects) - reqs, "excluded_non_submission": excluded,
            "portal_native": scope_counts.get(cc.SCOPE_PORTAL_NATIVE, 0),
            "checkable": sum(n for s, n in scope_counts.items() if s in cc.CHECKABLE_SCOPES),
            "scope_counts": {k: n for k, n in scope_counts.items() if n}}


def _result_payload(result: cc.CheckCoverageResult, *, run: dict, inputs: CheckInputs, fingerprint: str,
                    fingerprint_inputs: dict, plan, batch_records: list, integrity: str,
                    adjudication_source: str) -> dict:
    d = result.to_dict()
    d.pop("adjudications", None)
    d.update({
        "check_run_id": int(run["id"]), "source_analysis_run_id": inputs.source_analysis_run_id,
        "source_package_snapshot_id": inputs.package_snapshot_id, "input_fingerprint": fingerprint,
        "fingerprint_inputs": fingerprint_inputs, "architecture": architecture_versions(),
        "model_contract": model_contract(), "run_integrity": integrity,
        "planned_semantic_batches": len(plan.batches) if plan is not None else 0,
        "semantic_batches": [{k: b[k] for k in ("batch_id", "domain", "buyer_object_ids", "effective_status",
                                                "stop_reason", "parse_status", "failure_reason")}
                             for b in batch_records],
        "adjudicator_invocations": result.provider_calls,
        "live_provider_calls": sum(b.get("provider_calls", 0) for b in batch_records),
        "adjudication_source": adjudication_source,
        "result_digest": cc.result_digest(result),
    })
    return d


def _summary(result: cc.CheckCoverageResult, integrity: str, batch_records: list) -> dict:
    """Bounded (<= 4000 bytes: it is also the terminal event's detail)."""
    return {"analysis_mode": MODE_CHECK, "run_integrity": integrity,
            "object_counts": result.to_dict()["object_counts"],
            "status_counts": {k: n for k, n in result.status_counts().items() if n},
            "method_counts": result.method_counts(),
            "semantic_batches_total": len(batch_records),
            "semantic_batches_complete": sum(1 for b in batch_records if b["effective_status"] == BATCH_COMPLETE),
            "final_adjudications": len(result.adjudications)}


def _telemetry_summary(batch_records: list, result: cc.CheckCoverageResult, adjudication_source: str,
                       wall_seconds: float) -> dict:
    import full_analysis as fa
    return {"engine_version": CHECK_ENGINE_VERSION, "provider": PROVIDER_ANTHROPIC,
            "model": fa.FULL_ANALYSIS_MODEL, "adjudication_source": adjudication_source,
            "adjudicator_invocations": result.provider_calls,
            "live_provider_calls": sum(b.get("provider_calls", 0) for b in batch_records),
            "input_tokens": sum(b.get("input_tokens") or 0 for b in batch_records),
            "output_tokens": sum(b.get("output_tokens") or 0 for b in batch_records),
            "per_batch": [{k: b.get(k) for k in ("batch_id", "provider", "model", "stop_reason", "parse_status",
                                                 "effective_status", "input_tokens", "output_tokens",
                                                 "latency_seconds", "provider_calls")} for b in batch_records],
            "wall_seconds": round(wall_seconds, 3),
            "per_call_rows": f"model_usage_events (workflow='{TELEMETRY_WORKFLOW}', analysis_run_id=<this run>)"}


# ═══════════════════════════════════════════════════════════════════════
# Execution
# ═══════════════════════════════════════════════════════════════════════

class _CheckEventRecorder:
    """Writes durable, sequenced check_run_events rows. A refused write
    because the run became terminal underneath (e.g. marked stuck) sets
    `aborted`; nothing further is written and the run is never resurrected."""

    def __init__(self, run_id: int, bid_id: int):
        self.run_id = run_id
        self.bid_id = bid_id
        self.aborted = False
        self.write_errors: list[str] = []
        self._lock = threading.Lock()

    def record(self, event_type: str, **kwargs) -> None:
        with self._lock:
            if self.aborted:
                return
            try:
                db.record_check_run_event(self.run_id, self.bid_id, event_type, **kwargs)
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                self.write_errors.append(message[:300])
                if "terminal" in message.lower() or "not a check run" in message.lower():
                    self.aborted = True


def _execute_check_run(run: dict, inputs: CheckInputs, *, fingerprint: str, fingerprint_inputs: dict,
                       client=None, adjudicate_fn=None, adjudication_source: str = SOURCE_PROVIDER) -> None:
    """Execute one already-created CHECK run to a terminal state. Never
    raises: every failure is persisted as a FAILED run."""
    run_id, bid_id = int(run["id"]), int(run["bid_id"])
    recorder = _CheckEventRecorder(run_id, bid_id)
    t0 = time.monotonic()
    state = {"plan": None, "batches": [], "started": {}}
    try:
        recorder.record(EVENT_RUN_STARTED, status=RUN_RUNNING, detail={
            "engine_version": CHECK_ENGINE_VERSION, "input_fingerprint": fingerprint,
            "buyer_package_digest": inputs.canonical_package.package_digest,
            "submission_package_digest": inputs.submission_package.package_digest,
            "adjudication_source": adjudication_source})
        if recorder.aborted:
            return

        def on_event(event_type, payload):
            if event_type == cc.EVENT_PLAN_READY:
                plan = payload["plan"]
                state["plan"] = plan
                counts = _plan_counts(plan)
                recorder.record(EVENT_BUYER_SCOPE_CLASSIFIED, status=RUN_RUNNING, detail=counts)
                recorder.record(EVENT_CANDIDATE_RETRIEVAL_COMPLETE, status=RUN_RUNNING, detail={
                    "semantic_objects": len(plan.model_tasks),
                    "semantic_batches_total": len(plan.batches),
                    "candidate_evidence_per_batch": {b["batch_id"]: len(b["evidence_ids"]) for b in plan.batches}})
                recorder.record(EVENT_DETERMINISTIC_ADJUDICATION_COMPLETE, status=RUN_RUNNING, detail={
                    "deterministic_complete": len(plan.deterministic),
                    "pricing_criteria": len(plan.pricing_criteria),
                    "linked_criteria": sum(1 for v in plan.criterion_links.values() if v)})
            elif event_type == cc.EVENT_BATCH_STARTED:
                state["started"][payload["batch_id"]] = time.monotonic()
                recorder.record(EVENT_SEMANTIC_BATCH_STARTED, batch_id=payload["batch_id"], status=RUN_RUNNING,
                                detail={"objects": len(payload["objects"]),
                                        "candidate_evidence": len(payload["candidate_evidence_ids"]),
                                        "batches_total": len(state["plan"].batches) if state["plan"] else None,
                                        "batches_complete": len(state["batches"])})
            elif event_type == cc.EVENT_BATCH_COMPLETED:
                rec = batch_record(payload)
                state["batches"].append(rec)
                started = state["started"].get(rec["batch_id"])
                ev = EVENT_SEMANTIC_BATCH_FAILED if rec["effective_status"] == BATCH_FAILED \
                    else EVENT_SEMANTIC_BATCH_COMPLETED
                recorder.record(ev, batch_id=rec["batch_id"], status=rec["effective_status"],
                                duration_seconds=round(time.monotonic() - started, 6) if started else None,
                                failure_summary=rec["failure_reason"],
                                detail={"objects": len(rec["buyer_object_ids"]),
                                        "stop_reason": rec["stop_reason"], "parse_status": rec["parse_status"],
                                        "batches_complete": len(state["batches"]),
                                        "batches_total": len(state["plan"].batches) if state["plan"] else None,
                                        "input_tokens": rec["input_tokens"], "output_tokens": rec["output_tokens"]},
                                batch_result={k: v for k, v in rec.items() if k != "provider_calls"})

        telemetry: list = []
        telemetry_context = {"workflow": TELEMETRY_WORKFLOW, "bid_id": bid_id, "analysis_run_id": run_id,
                             "metadata": {"input_fingerprint": fingerprint[:16]}}
        result = cc.run_check_coverage(
            inputs.canonical_package, inputs.submission_package, raw_requirements=inputs.raw_requirements,
            buyer_documents=inputs.buyer_documents, adjudicate_fn=adjudicate_fn, client=client,
            organization_id=inputs.submission_package.organization_id or "", telemetry=telemetry,
            telemetry_context=telemetry_context, on_event=on_event)
        if recorder.aborted:
            return
        plan = state["plan"]
        expected_ids = [o.object_id for o in plan.objects] if plan is not None else []
        violations = validate_result_for_persistence(result, inputs.submission_package, bid_id=bid_id,
                                                     expected_object_ids=expected_ids)
        rejected = sum(len((a.validation or {}).get("rejected_evidence_ids") or []) for a in result.adjudications)
        recorder.record(EVENT_EVIDENCE_ASSURANCE_COMPLETE,
                        status=RUN_FAILED if violations else RUN_RUNNING,
                        failure_summary=("; ".join(violations)[:500] if violations else None),
                        detail={"final_adjudications": len(result.adjudications),
                                "cited_evidence_ids": len({e for a in result.adjudications for e in a.evidence_ids}),
                                "model_evidence_ids_rejected_fail_closed": rejected,
                                "integrity_violations": len(violations)})
        if recorder.aborted:
            return
        if violations:
            db.finalize_check_run(run_id, bid_id, RUN_FAILED,
                                  failure_reason=f"integrity validation failed ({len(violations)} violation(s)); "
                                                 f"nothing persisted as adjudication",
                                  failure_detail={"integrity_violations": violations[:50]},
                                  telemetry=_telemetry_summary(state["batches"], result, adjudication_source,
                                                               time.monotonic() - t0))
            return
        status, reason = run_integrity(state["batches"])
        db.finalize_check_run(
            run_id, bid_id, status,
            result=_result_payload(result, run=run, inputs=inputs, fingerprint=fingerprint,
                                   fingerprint_inputs=fingerprint_inputs, plan=plan,
                                   batch_records=state["batches"], integrity=status,
                                   adjudication_source=adjudication_source),
            adjudications=[adjudication_row(a, inputs.submission_package) for a in result.adjudications],
            summary=_summary(result, status, state["batches"]), failure_reason=reason,
            telemetry=_telemetry_summary(state["batches"], result, adjudication_source, time.monotonic() - t0))
    except Exception as exc:
        if recorder.aborted:
            return
        try:
            db.finalize_check_run(
                run_id, bid_id, RUN_FAILED, failure_reason=f"{type(exc).__name__}: {exc}"[:500],
                failure_detail={"traceback": traceback.format_exc()[-4000:],
                                "event_write_errors": recorder.write_errors[-5:],
                                "semantic_batches_finished": [b["batch_id"] for b in state["batches"]]})
        except Exception:
            pass  # already terminal / DB unreachable: is_check_run_stuck surfaces it


# ═══════════════════════════════════════════════════════════════════════
# Public service API
# ═══════════════════════════════════════════════════════════════════════

def start_check_run(bid_id: int, organization_id: str, *, package_snapshot_id: int | None = None,
                    source_run_id: int | None = None, created_by_user_id: str | None = None,
                    retry: bool = False, execution: str = EXECUTION_BACKGROUND, api_key: str | None = None,
                    client=None, adjudicate_fn=None, adjudication_source: str | None = None,
                    inputs_loader=None) -> dict:
    """Start (or reuse) the canonical CHECK adjudication for a bid's current
    buyer canonical state and bidder package snapshot.

    Authorization is NOT performed here -- call only through
    tenancy.start_check_run_for_organization (require_bid_access first).

    1. Load inputs (read-only, zero model calls) and compute the fingerprint.
    2. ONE advisory-locked RPC decides the outcome.
    3. Only CREATED executes. REUSED_COMPLETE returns the persisted,
       reconstructed adjudication with ZERO provider calls; ACTIVE / FAILED /
       PARTIAL runs are returned, never silently re-run (retry=True is the
       explicit way to spend again on a FAILED/PARTIAL fingerprint)."""
    if execution not in (EXECUTION_BACKGROUND, EXECUTION_INLINE):
        raise ValueError(f"unknown execution mode {execution!r}")
    loader = inputs_loader or load_check_inputs
    inputs = loader(bid_id, organization_id, package_snapshot_id=package_snapshot_id, source_run_id=source_run_id)
    if int(inputs.bid_id) != int(bid_id) or int(inputs.submission_package.bid_id) != int(bid_id):
        raise sp.CrossBidEvidenceError("CHECK inputs do not belong to this bid")
    fingerprint_inputs = check_fingerprint_inputs(inputs)
    fingerprint = _digest(fingerprint_inputs)
    response = db.start_check_run(
        bid_id, inputs.source_analysis_run_id, inputs.package_snapshot_id, fingerprint, CHECK_ENGINE_VERSION,
        created_by_user_id=created_by_user_id, retry=retry,
        detail={"source_analysis_run_id": inputs.source_analysis_run_id,
                "source_package_snapshot_id": inputs.package_snapshot_id,
                "buyer_package_digest": inputs.canonical_package.package_digest,
                "submission_package_digest": inputs.submission_package.package_digest,
                "engine_version": CHECK_ENGINE_VERSION})
    if not response or "outcome" not in response:
        raise CheckRunError("start_check_run returned no outcome")
    outcome, run = response["outcome"], response["run"]
    out = {"outcome": outcome, "run": run, "input_fingerprint": fingerprint,
           "fingerprint_matches": run.get("input_fingerprint") == fingerprint,
           "source_analysis_run_id": inputs.source_analysis_run_id,
           "package_snapshot_id": inputs.package_snapshot_id, "executing": False, "result": None}
    if outcome == OUTCOME_REUSED_COMPLETE:
        out["result"] = get_check_run_result(bid_id, int(run["id"]))
        return out
    if outcome != OUTCOME_CREATED:
        return out
    source = adjudication_source or (SOURCE_INJECTED if adjudicate_fn is not None else SOURCE_PROVIDER)
    if adjudicate_fn is None and client is None:
        import config
        client = config.get_anthropic_client(api_key)
    kwargs = dict(fingerprint=fingerprint, fingerprint_inputs=fingerprint_inputs, client=client,
                  adjudicate_fn=adjudicate_fn, adjudication_source=source)
    if execution == EXECUTION_INLINE:
        _execute_check_run(run, inputs, **kwargs)
    else:
        thread = threading.Thread(target=_execute_check_run, args=(run, inputs), kwargs=kwargs, daemon=True,
                                  name=f"check-run-{run['id']}")
        thread.start()
        out["executing"] = True
    return out


def _parse_ts(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def is_check_run_stuck(run: dict, *, now: datetime | None = None) -> dict:
    """Pure stale-run detection under STALE_RUN_POLICY. Only a non-terminal
    run can be stuck; detection never triggers any action."""
    now = now or datetime.now(timezone.utc)
    created = _parse_ts(run.get("created_at"))
    progress = _parse_ts(run.get("last_progress_at")) or _parse_ts(run.get("started_at")) or created
    age = (now - created).total_seconds() if created else None
    idle = (now - progress).total_seconds() if progress else None
    info = {"stuck": False, "reason": None, "seconds_since_progress": idle, "run_age_seconds": age,
            "policy": dict(STALE_RUN_POLICY)}
    if run.get("status") in TERMINAL_RUN_STATUSES:
        return info
    if idle is not None and idle > STALE_RUN_POLICY["no_progress_seconds"]:
        info.update(stuck=True, reason="NO_PROGRESS")
    elif age is not None and age > STALE_RUN_POLICY["max_run_age_seconds"]:
        info.update(stuck=True, reason="MAX_RUN_AGE_EXCEEDED")
    return info


def derive_check_progress(run: dict, events: list[dict]) -> dict:
    """Pure: refresh-safe progress counts reconstructed from the durable event
    log (latest event wins; no percentages, no timers)."""
    p = {"stage": None, "total_buyer_objects": None, "excluded_non_submission": None, "portal_native": None,
         "checkable": None, "deterministic_complete": None, "semantic_batches_total": None,
         "semantic_batches_complete": 0, "semantic_batches_failed": 0, "semantic_batches_partial": 0,
         "running_batch": None, "final_adjudications": None, "batches": {}}
    for ev in sorted(events, key=lambda e: e.get("sequence") or 0):
        et, d = ev.get("event_type"), ev.get("detail") or {}
        p["stage"] = et
        if et == EVENT_BUYER_SCOPE_CLASSIFIED:
            for k in ("total_buyer_objects", "excluded_non_submission", "portal_native", "checkable"):
                p[k] = d.get(k)
        elif et == EVENT_CANDIDATE_RETRIEVAL_COMPLETE:
            p["semantic_batches_total"] = d.get("semantic_batches_total")
        elif et == EVENT_DETERMINISTIC_ADJUDICATION_COMPLETE:
            p["deterministic_complete"] = d.get("deterministic_complete")
        elif et == EVENT_SEMANTIC_BATCH_STARTED:
            p["running_batch"] = ev.get("batch_id")
            p["batches"][ev.get("batch_id")] = RUN_RUNNING
        elif et in (EVENT_SEMANTIC_BATCH_COMPLETED, EVENT_SEMANTIC_BATCH_FAILED):
            p["running_batch"] = None
            p["batches"][ev.get("batch_id")] = ev.get("status")
        elif et in (EVENT_RUN_COMPLETED, EVENT_RUN_PARTIAL):
            p["final_adjudications"] = d.get("final_adjudications")
    statuses = list(p["batches"].values())
    p["semantic_batches_complete"] = statuses.count(BATCH_COMPLETE)
    p["semantic_batches_partial"] = statuses.count(BATCH_PARTIAL)
    p["semantic_batches_failed"] = statuses.count(BATCH_FAILED)
    return p


def _get_check_run(bid_id: int, run_id: int | None) -> dict | None:
    if run_id is None:
        runs = db.get_check_runs(bid_id, limit=1)
        return runs[0] if runs else None
    run = db.get_analysis_run(run_id)
    if not run or int(run.get("bid_id")) != int(bid_id) or run.get("analysis_mode") != MODE_CHECK:
        raise RunNotFoundError(f"CHECK run {run_id} does not exist for bid {bid_id}")
    return run


def get_check_run_status(bid_id: int, run_id: int | None = None, *, after_sequence: int = 0,
                         now: datetime | None = None) -> dict | None:
    """Durable, refresh-safe state for one CHECK run (default: the bid's
    latest). Reads only persisted rows -- never calls a model, never starts
    work."""
    run = _get_check_run(bid_id, run_id)
    if run is None:
        return None
    events = db.get_check_run_events(int(run["id"]))
    return {"run_id": run["id"], "bid_id": run["bid_id"], "analysis_mode": MODE_CHECK,
            "status": run.get("status"), "is_terminal": run.get("status") in TERMINAL_RUN_STATUSES,
            "input_fingerprint": run.get("input_fingerprint"),
            "source_analysis_run_id": run.get("source_analysis_run_id"),
            "source_package_snapshot_id": run.get("source_package_snapshot_id"),
            "engine_version": run.get("engine_version"), "created_at": run.get("created_at"),
            "started_at": run.get("started_at"), "completed_at": run.get("completed_at"),
            "failed_at": run.get("failed_at"), "last_progress_at": run.get("last_progress_at"),
            "failure_reason": run.get("failure_reason"), "stuck": is_check_run_stuck(run, now=now),
            "progress": derive_check_progress(run, events),
            "last_sequence": max((e.get("sequence") or 0 for e in events), default=0),
            "events": [e for e in events if (e.get("sequence") or 0) > after_sequence],
            "telemetry": run.get("telemetry")}


def adjudication_from_row(row: dict) -> cc.CheckAdjudication:
    """Inverse of adjudication_row: the persisted row back into the CHECK-2A
    CheckAdjudication contract (tuples where CHECK-2A uses tuples)."""
    return cc.CheckAdjudication(
        buyer_object_id=row["buyer_object_id"], buyer_object_type=row["buyer_object_type"],
        assurance_scope=row["assurance_scope"], scope_basis=row.get("scope_basis") or "", status=row["status"],
        buyer_expectation=row["buyer_expectation"], buyer_label=row.get("buyer_label"),
        buyer_category=row.get("buyer_category"),
        expected_evidence_roles=tuple(row.get("expected_evidence_roles") or ()),
        evidence_ids=tuple(row.get("evidence_ids") or ()), evidence_summary=row.get("evidence_summary") or "",
        addressed_elements=list(row.get("addressed_elements") or []),
        missing_elements=list(row.get("missing_elements") or []),
        unverifiable_elements=list(row.get("unverifiable_elements") or []),
        ambiguity_or_review_reason=row.get("ambiguity_or_review_reason"), buyer_weight=row.get("buyer_weight"),
        buyer_weight_variants=tuple(row.get("buyer_weight_variants") or ()),
        buyer_threshold=row.get("buyer_threshold"),
        deterministic_or_model=row.get("adjudication_method") or row.get("deterministic_or_model"),
        batch_id=row.get("batch_id"), linked_requirement_ids=tuple(row.get("linked_requirement_ids") or ()),
        search_basis=dict(row.get("search_basis") or {}), validation=dict(row.get("validation") or {}),
        source_provenance=dict(row.get("source_provenance") or {}), applicability=row.get("applicability"),
        applicability_condition=row.get("applicability_condition"))


def reconstruct_result(stored: dict, rows: list[dict]) -> cc.CheckCoverageResult:
    """The CHECK-2A CheckCoverageResult rebuilt purely from persisted rows."""
    ordered = sorted(rows, key=lambda r: r.get("ordinal") or 0)
    return cc.CheckCoverageResult(
        bid_id=stored.get("bid_id"), contract_version=stored.get("contract_version"),
        buyer_package_digest=stored.get("buyer_package_digest"),
        submission_package_digest=stored.get("submission_package_digest"),
        adjudications=[adjudication_from_row(r) for r in ordered],
        provider_calls=int(stored.get("provider_calls") or 0), batches=list(stored.get("batches") or []),
        telemetry=[])


def get_check_run_result(bid_id: int, run_id: int | None = None) -> dict | None:
    """The persisted CHECK adjudication, reconstructed with ZERO provider
    calls. Default: the most recent COMPLETE run, else the most recent
    PARTIAL (a FAILED run is never returned by default). Returns {"run",
    "result" (CheckCoverageResult), "result_payload", "semantic_batches",
    "is_complete", "result_digest_verified"} or None."""
    if run_id is None:
        runs = db.get_check_runs(bid_id)
        run = (next((r for r in runs if r.get("status") == RUN_COMPLETE), None)
               or next((r for r in runs if r.get("status") == RUN_PARTIAL), None))
        if run is None:
            return None
    else:
        run = _get_check_run(bid_id, run_id)
    stored = (db.get_analysis_result(int(run["id"])) or {}).get("check_coverage_result")
    rows = db.get_check_adjudications(int(run["id"])) or []
    for r in rows:
        if int(r.get("bid_id")) != int(bid_id):
            raise sp.CrossBidEvidenceError(f"adjudication row of bid {r.get('bid_id')} under bid {bid_id}")
    result = reconstruct_result(stored, rows) if stored else None
    return {"run": run, "result": result, "result_payload": stored,
            "semantic_batches": db.get_check_semantic_batches(int(run["id"])) or [],
            "is_complete": run.get("status") == RUN_COMPLETE,
            "result_digest_verified": bool(result is not None and stored
                                           and cc.result_digest(result) == stored.get("result_digest"))}


def mark_check_run_stuck(bid_id: int, run_id: int, *, now: datetime | None = None) -> dict:
    """Explicit, user-initiated action (never automatic): marks a stale run
    FAILED, preserving every already-durable batch row. Never starts a new
    run -- the caller must explicitly start again (retry=True)."""
    run = _get_check_run(bid_id, run_id)
    stuck = is_check_run_stuck(run, now=now)
    if not stuck["stuck"]:
        raise RunNotStuckError(f"CHECK run {run_id} is not stuck (status {run.get('status')})")
    return db.finalize_check_run(
        int(run["id"]), int(bid_id), RUN_FAILED,
        failure_reason=(f"Marked failed by user action: run appears stuck ({stuck['reason']}; "
                        f"no durable progress for {int(stuck['seconds_since_progress'] or 0)}s)."),
        failure_detail={"marked_stuck_by_user": True, "prior_status": run.get("status"),
                        "stuck": {k: stuck[k] for k in ("reason", "seconds_since_progress", "run_age_seconds")},
                        "policy": dict(STALE_RUN_POLICY)})
