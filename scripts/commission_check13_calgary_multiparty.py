"""
CHECK-1.3 -- one-off, READ-ONLY live acceptance of the final multi-party
requirement gap on the canonical Calgary benchmark (bid 1360).

    python scripts/commission_check13_calgary_multiparty.py <out_json>

Chain proven entirely from REAL persisted data, zero model calls, zero
database writes:

  authoritative City RFP passage (persisted buyer documents 199-211,
    extracted with the CHECK-1.2 DOCX extractor)
  -> canonical buyer requirement (analysis_service.build_full_analysis_
    package(34): the existing recomputation path over the IMMUTABLE Fast
    Analysis run 34 raw snapshot + the same buyer corpus)
  -> expected role MULTI_PARTY_FORM (submission_package.derive_expected_evidence)
  -> real Phoenix / Inquisitive Talent B2 evidence candidates (migration-021
    package snapshot 9, reloaded via tenancy.load_submission_evidence_
    package_for_organization).

Every Anthropic entry point is replaced by a function that raises and
counts, so the script cannot make a provider call and reports how many
were attempted (must be 0). Run 34's raw snapshot is hashed before and
after to prove it was not mutated.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings("ignore")

BID_ID, RUN_ID, SNAPSHOT_ID = 1360, 34, 9
ORG_ID = "4326b564-8cc5-4463-9304-9a589f08cc91"
PROVIDER_ATTEMPTS = {"count": 0}


def _env():
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
    except Exception:
        pass


def _poison_provider():
    def _refuse(*_a, **_k):
        PROVIDER_ATTEMPTS["count"] += 1
        raise RuntimeError("CHECK-1.3 acceptance: provider calls are forbidden")

    import importlib
    for mod_name in ("config", "fast_analysis", "full_analysis", "analyst", "section_drafting",
                     "evidence_strengthening", "analysis_service"):
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        for attr in ("get_anthropic_client", "execute_messages_create"):
            if hasattr(mod, attr):
                setattr(mod, attr, _refuse)


def _snapshot_digest() -> str:
    import database as db
    snap = (db.get_analysis_result(RUN_ID) or {}).get("fast_analysis_result_snapshot")
    return hashlib.sha256(json.dumps(snap, sort_keys=True, default=str).encode()).hexdigest()


def main(out_json: str):
    _env()
    _poison_provider()
    import analysis_service
    import database as db
    import submission_package as sp
    import tenancy

    run_before = db.get_analysis_run(RUN_ID)
    digest_before = _snapshot_digest()

    # ---- buyer side: canonical package via the existing recompute path ----
    package = analysis_service.build_full_analysis_package(RUN_ID, include_documents=True)
    raw = analysis_service.load_raw_fast_analysis_result(RUN_ID)
    recovered = [r for r in package.requirements if r.get("requirement_origin")]
    assert len(recovered) == 1, recovered
    req = dict(recovered[0])
    expected = sp.derive_expected_evidence(req)

    # ---- bidder side: persisted migration-021 package, fresh reload ----
    bidder = tenancy.load_submission_evidence_package_for_organization(BID_ID, ORG_ID, SNAPSHOT_ID)
    mapping = sp.map_requirement_to_submission(req, bidder)
    b2_docs = bidder.documents_with_roles([sp.ROLE_MULTI_PARTY_FORM], include_secondary=False)
    b2 = b2_docs[0]
    b2_items = bidder.registry.for_document(b2.submission_document_id)
    b2_text = " ".join(i.content for i in b2_items)
    candidates = [c.to_dict() for c in mapping.candidates]
    for c in mapping.candidates:
        bidder.registry.get(c.evidence_id, bid_id=BID_ID)  # resolves under the right bid
    try:
        bidder.registry.get(mapping.candidates[0].evidence_id, bid_id=BID_ID + 1)
        cross_bid_rejected = False
    except sp.CrossBidEvidenceError:
        cross_bid_rejected = True

    members = bidder.member_documents()
    roles = {d.document_role: d.filename for d in members}
    submission = dict(package.submission_mechanics)
    deadline_milestones = sorted({m.get("normalized_date_start") for m in package.milestones
                                  if "DEADLINE" in (m.get("label") or "").upper() and m.get("normalized_date_start")})

    run_after = db.get_analysis_run(RUN_ID)
    digest_after = _snapshot_digest()

    out = {
        "provider_call_attempts": PROVIDER_ATTEMPTS["count"],
        "run34": {"status": run_after.get("status"), "completed_at": run_after.get("completed_at"),
                  "snapshot_sha256_before": digest_before, "snapshot_sha256_after": digest_after,
                  "unchanged": digest_before == digest_after and run_before == run_after,
                  "raw_snapshot_requirement_count": len(raw.requirements)},
        "buyer_source": {"source_doc": req["source_docs"], "source_locator": req.get("source_locator"),
                         "verbatim": req["description"], "source_context": req.get("source_context"),
                         "source_refs": req["source_refs"]},
        "canonical_requirement": {k: req.get(k) for k in (
            "canonical_id", "object_type", "description", "category", "requirement_type", "semantic_type",
            "applicability", "applicable_category_ids", "applicability_condition", "required_form",
            "requirement_origin")},
        "canonical_requirement_count": len(package.requirements),
        "expected_evidence": expected.to_dict(),
        "bidder": {"b2_submission_document_id": b2.submission_document_id, "b2_filename": b2.filename,
                   "b2_package_path": b2.package_path, "b2_role": b2.document_role,
                   "b2_logical_artifact_id": b2.logical_artifact_id,
                   "b2_evidence_count": len(b2_items),
                   "phoenix_recoverable": "Phoenix Consulting Canada" in b2_text,
                   "inquisitive_talent_recoverable": "Inquisitive Talent" in b2_text,
                   "mapping_req_id": mapping.req_id, "artifact_status": mapping.artifact_status,
                   "primary_role_present": mapping.primary_role_present,
                   "candidates": candidates,
                   "candidate_provenance": [bidder.registry.get(c.evidence_id, bid_id=BID_ID).provenance
                                            for c in mapping.candidates],
                   "cross_bid_rejected": cross_bid_rejected},
        "regression": {"bidder_documents": len(bidder.documents), "logical_artifacts": len(members),
                       "evidence_items": len(bidder.registry), "roles": roles,
                       "scoped_criteria": len(package.scoped_criteria),
                       "canonical_deadline": submission.get("submission_deadline"),
                       "deadline_milestones": deadline_milestones},
    }
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False, default=str)
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main(sys.argv[1])
