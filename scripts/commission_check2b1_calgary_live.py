"""
CHECK-2B.1 -- LIVE durable-run commissioning on the canonical Calgary benchmark
(bid 1360, RFP 26-1603, Fast Analysis run 34, package snapshot 9) against the
REAL migration-022 schema, with ZERO provider calls.

    python scripts/commission_check2b1_calgary_live.py persist <out_dir>
        Loads the live inputs read-only (check_run_service.load_check_inputs),
        then runs the PRODUCTION durable path (check_run_service.start_check_run
        -> database.start_check_run / record_check_run_event / finalize_check_run
        RPCs, inline) with the semantic batches answered by a deterministic
        REPLAY of the already-validated CHECK-2A live output
        (tests/fixtures/calgary_26_1603_check2a_replay.json). Creates ONE real,
        permanent CHECK run. The in-memory result is written to
        <out_dir>/check2b1_inmemory_result.json for the fresh-process comparison.

    python scripts/commission_check2b1_calgary_live.py reopen <out_dir>
        In a FRESH process, with no replay fixture consulted for reconstruction:
        reconstructs the run purely from the database through tenancy's
        read wrappers, compares it field-by-field with the persisted in-memory
        result and the accepted CHECK-2A record, then calls
        tenancy.start_check_run_for_organization again with identical inputs
        (production wrapper, no adjudicator injected, provider poisoned) --
        expected REUSED_COMPLETE, zero new rows, zero provider calls.

Provider safety: every Anthropic entry point and model_usage_events recorder is
poisoned for the whole process. DB safety: every database write function EXCEPT
the three migration-022 CHECK RPCs is poisoned.
"""
from __future__ import annotations

import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [REPO, os.path.join(REPO, "scripts"), os.path.join(REPO, "tests")]

BID_ID, RUN_ID, SNAPSHOT_ID = 1360, 34, 9
ORG_ID = "4326b564-8cc5-4463-9304-9a589f08cc91"
REPLAY = os.path.join(REPO, "tests", "fixtures", "calgary_26_1603_check2a_replay.json")
INMEM = "check2b1_inmemory_result.json"
ALLOWED_WRITES = ("start_check_run", "record_check_run_event", "finalize_check_run")
COUNTS = {"adjudicator_invocations": 0, "provider_attempts": 0, "forbidden_db_writes": 0}


def _setup():
    import commission_check2a_calgary as c2a
    import database as db
    c2a._env()
    c2a._poison_provider()
    saved = {n: getattr(db, n) for n in ALLOWED_WRITES}
    c2a._poison_db_writes()
    for n, fn in saved.items():
        setattr(db, n, fn)
    return c2a


def _replay_fn(record):
    import commission_check2a_calgary as c2a
    inner = c2a.replay_adjudicator(record)

    def fn(prompt, batch):
        COUNTS["adjudicator_invocations"] += 1
        return inner(prompt, batch)
    return fn


def _inputs():
    import check_run_service as csr
    t0 = time.monotonic()
    inputs = csr.load_check_inputs(BID_ID, ORG_ID, package_snapshot_id=SNAPSHOT_ID, source_run_id=RUN_ID)
    return inputs, round(time.monotonic() - t0, 2)


def _norm(x):
    return json.loads(json.dumps(x, sort_keys=True, default=str))


def _row_counts(db, run_id):
    return {"events": len(db.get_check_run_events(run_id)),
            "batches": len(db.get_check_semantic_batches(run_id)),
            "adjudications": len(db.get_check_adjudications(run_id)),
            "check_runs_for_bid": len(db.get_check_runs(BID_ID))}


def cmd_persist(out_dir):
    c2a = _setup()
    import check_coverage as cc
    import check_run_service as csr
    import database as db
    with open(REPLAY, encoding="utf-8") as fh:
        record = json.load(fh)
    inputs, load_s = _inputs()
    existing = db.get_check_runs(BID_ID)
    if existing:
        raise SystemExit(f"bid {BID_ID} already has CHECK runs {[r['id'] for r in existing]}; persist is one-shot")
    provenance = {"source_adjudication": "CHECK-2A live acceptance (commit b488749)",
                  "recorded_output": "tests/fixtures/calgary_26_1603_check2a_replay.json",
                  "source_contract_version": record["contract_version"],
                  "source_recorded_provider_calls": record["provider_calls"],
                  "source_buyer_package_digest": record["buyer_package_digest"],
                  "source_submission_package_digest": record["submission_package_digest"]}
    out = csr.start_check_run(BID_ID, ORG_ID, package_snapshot_id=SNAPSHOT_ID, source_run_id=RUN_ID,
                              inputs_loader=lambda *a, **k: inputs, adjudicate_fn=_replay_fn(record),
                              adjudication_source=csr.SOURCE_REPLAY, execution=csr.EXECUTION_INLINE,
                              adjudication_provenance=provenance)
    run_id = int(out["run"]["id"])
    run = db.get_analysis_run(run_id)
    # The in-memory reference the durable result must reproduce (same replay, pure CHECK-2A).
    pure = cc.run_check_coverage(inputs.canonical_package, inputs.submission_package,
                                 raw_requirements=inputs.raw_requirements, buyer_documents=inputs.buyer_documents,
                                 adjudicate_fn=c2a.replay_adjudicator(record))
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, INMEM), "w", encoding="utf-8") as fh:
        json.dump({"run_id": run_id, "input_fingerprint": out["input_fingerprint"],
                   "adjudications": [a.to_dict() for a in pure.adjudications],
                   "evidence_refs": {a.buyer_object_id: csr.evidence_refs(a, inputs.submission_package)
                                     for a in pure.adjudications},
                   "result_digest": cc.result_digest(pure)}, fh, default=str)
    print(json.dumps({
        "live_input_load_seconds": load_s, "outcome": out["outcome"], "run_id": run_id,
        "run_status": run["status"], "input_fingerprint": out["input_fingerprint"],
        "fingerprint_matches": out["fingerprint_matches"],
        "source_analysis_run_id": run["source_analysis_run_id"],
        "source_package_snapshot_id": run["source_package_snapshot_id"],
        "engine_version": run["engine_version"],
        "buyer_package_digest": inputs.canonical_package.package_digest,
        "submission_package_digest": inputs.submission_package.package_digest,
        "evidence_items": len(inputs.submission_package.registry),
        "telemetry": {k: run["telemetry"].get(k) for k in ("adjudication_source", "adjudicator_invocations",
                                                           "live_provider_calls", "input_tokens", "output_tokens",
                                                           "source_adjudication_provenance")},
        "row_counts": _row_counts(db, run_id),
        "counts": COUNTS, "check2a_poison_counts": c2a.COUNTS,
    }, indent=1, default=str))


def cmd_reopen(out_dir):
    c2a = _setup()
    import check_coverage as cc
    import check_run_service as csr
    import database as db
    import submission_package as sp
    import tenancy
    with open(os.path.join(out_dir, INMEM), encoding="utf-8") as fh:
        mem = json.load(fh)
    run_id = int(mem["run_id"])

    # 1. Reconstruction from the DATABASE ONLY (no fixture, no inputs).
    bundle = tenancy.get_check_run_result_for_organization(BID_ID, ORG_ID, run_id)
    status = tenancy.get_check_run_status_for_organization(BID_ID, ORG_ID, run_id)
    res = bundle["result"]
    rows = db.get_check_adjudications(run_id)
    db_adj = _norm([a.to_dict() for a in res.adjudications])
    mem_adj = _norm(mem["adjudications"])
    field_diffs = []
    for got, want in zip(db_adj, mem_adj):
        for k in want:
            if got.get(k) != want[k]:
                field_diffs.append((want["buyer_object_id"], k))
    refs_equal = all(_norm(r["evidence_refs"]) == _norm(mem["evidence_refs"][r["buyer_object_id"]]) for r in rows)
    links = db.get_client().table("check_adjudication_evidence").select("*").eq("run_id", run_id) \
        .range(0, 4999).execute().data

    # 2. Only now load the accepted record + live inputs for semantic comparison.
    with open(REPLAY, encoding="utf-8") as fh:
        record = json.load(fh)
    inputs, load_s = _inputs()
    bidder = inputs.submission_package
    registry = {i.evidence_id for i in bidder.registry}
    live = record["final"]
    by = res.by_id()
    role_ids = {role: {i.evidence_id for d in bidder.documents_with_roles([role], include_secondary=False)
                       for i in bidder.registry.for_document(d.submission_document_id)}
                for role in (sp.ROLE_MULTI_PARTY_FORM, sp.ROLE_PRICING_FORM, sp.ROLE_SUBMISSION_FORM)}
    cited = sorted({e for a in res.adjudications for e in list(a.evidence_ids)
                    + [x for g in (a.addressed_elements, a.missing_elements, a.unverifiable_elements)
                       for el in g for x in (el.get("evidence_ids") or [])]})
    req41 = by["REQ-41"]
    fp_inputs = csr.check_fingerprint_inputs(inputs)
    checks = {
        "objects": len(res.adjudications),
        "requirements": sum(a.buyer_object_type == cc.OBJECT_REQUIREMENT for a in res.adjudications),
        "criteria": sum(a.buyer_object_type == cc.OBJECT_CRITERION for a in res.adjudications),
        "status_counts": {k: v for k, v in res.status_counts().items() if v},
        "scope_counts": {k: v for k, v in res.scope_counts().items() if v},
        "method_counts": res.method_counts(),
        "statuses_identical_to_accepted_check2a": len(live) == len(res.adjudications) and all(
            a.status == live[a.buyer_object_id]["status"] for a in res.adjudications),
        "methods_identical_to_accepted_check2a": all(a.deterministic_or_model == live[a.buyer_object_id]["method"]
                                                     for a in res.adjudications),
        "evidence_ids_identical_to_accepted_check2a": all(
            sorted(a.evidence_ids) == sorted(live[a.buyer_object_id]["evidence_ids"]) for a in res.adjudications),
        "all_fields_identical_to_inmemory": not field_diffs and len(db_adj) == len(mem_adj),
        "field_diffs": field_diffs[:20],
        "evidence_refs_identical": refs_equal,
        "result_digest_verified": bundle["result_digest_verified"],
        "result_digest_equals_inmemory": cc.result_digest(res) == mem["result_digest"],
        "distinct_cited_ids": len(cited), "all_cited_ids_in_live_registry": all(e in registry for e in cited),
        "evidence_link_rows": len(links),
        "evidence_links_all_snapshot9_bid1360": all(l["bid_id"] == BID_ID and l["package_snapshot_id"] == SNAPSHOT_ID
                                                     for l in links),
        "evidence_links_cover_every_cited_id": sorted({l["evidence_id"] for l in links}) == cited,
        "criteria_ids": sorted(a.buyer_object_id for a in res.adjudications
                               if a.buyer_object_type == cc.OBJECT_CRITERION),
        "REQ-46": {"status": by["REQ-46"].status, "method": by["REQ-46"].deterministic_or_model,
                   "b2_evidence": len(set(by["REQ-46"].evidence_ids) & role_ids[sp.ROLE_MULTI_PARTY_FORM]),
                   "evidence": len(by["REQ-46"].evidence_ids)},
        "pricing": {cid: {"status": by[cid].status, "evidence": len(by[cid].evidence_ids),
                          "all_from_appendix_d": set(by[cid].evidence_ids) <= role_ids[sp.ROLE_PRICING_FORM]}
                    for cid in sorted(by) if cid.startswith("CRIT-") and
                    (set(by[cid].evidence_ids) & role_ids[sp.ROLE_PRICING_FORM])},
        "appendix_e": {rid: {"status": by[rid].status, "evidence": len(by[rid].evidence_ids),
                             "all_from_appendix_e": set(by[rid].evidence_ids) <= role_ids[sp.ROLE_SUBMISSION_FORM]}
                       for rid in ("REQ-33", "REQ-37")},
        "portal_native": {a.buyer_object_id: a.status for a in res.adjudications
                          if a.assurance_scope == cc.SCOPE_PORTAL_NATIVE},
        "human_review": sorted(a.buyer_object_id for a in res.adjudications if a.status == cc.STATUS_HUMAN_REVIEW),
        "excluded_all_not_applicable_no_missing": all(a.status == cc.STATUS_NOT_APPLICABLE and not a.missing_elements
                                                      for a in res.adjudications
                                                      if a.assurance_scope in cc.EXCLUDED_SCOPES),
        "excluded_count": sum(a.assurance_scope in cc.EXCLUDED_SCOPES for a in res.adjudications),
        "partial_missing_elements_identical": all(
            _norm(a.missing_elements) == _norm(next(m for m in mem_adj if m["buyer_object_id"] == a.buyer_object_id)
                                               ["missing_elements"])
            for a in res.adjudications if a.status == cc.STATUS_PARTIALLY_ADDRESSED),
        "REQ-41": {"status": req41.status, "method": req41.deterministic_or_model,
                   "past_five_years_element": next((e["coverage"] for e in req41.missing_elements
                                                    if e["element"].startswith("three (3) examples from the past")),
                                                   None)},
    }
    fingerprint = {
        "persisted": bundle["run"]["input_fingerprint"],
        "recomputed_from_live_inputs": csr.compute_check_fingerprint(inputs),
        "requirement_ids": len(fp_inputs["buyer"]["requirement_ids"]),
        "criterion_ids": len(fp_inputs["buyer"]["criterion_ids"]),
        "buyer_documents": len(fp_inputs["buyer"]["buyer_documents"]),
        "authoritative_artifacts": fp_inputs["bidder"]["authoritative_artifacts"],
        "evidence_item_count": fp_inputs["bidder"]["evidence_item_count"],
        "architecture": fp_inputs["architecture"],
        "model": {k: fp_inputs["model"][k] for k in ("provider", "model", "max_output_tokens")},
        "top_level_keys": sorted(fp_inputs),
    }
    before = _row_counts(db, run_id)
    if fingerprint["persisted"] != fingerprint["recomputed_from_live_inputs"]:
        # Never let a mismatching start create an orphan QUEUED run on the live DB.
        print(json.dumps({"ABORT": "fingerprint mismatch; reuse start not attempted", "checks": checks,
                          "fingerprint": fingerprint}, indent=1, default=str))
        raise SystemExit(2)

    # 3. REUSED_COMPLETE through the production tenancy wrapper (no adjudicator
    #    injected; provider poisoned -- a CREATED outcome would raise).
    again = tenancy.start_check_run_for_organization(BID_ID, ORG_ID, package_snapshot_id=SNAPSHOT_ID,
                                                     source_run_id=RUN_ID, execution="inline")
    after = _row_counts(db, run_id)
    reuse = {"outcome": again["outcome"], "run_id": again["run"]["id"],
             "same_run": int(again["run"]["id"]) == run_id,
             "fingerprint_matches": again["fingerprint_matches"],
             "result_identical": _norm([a.to_dict() for a in again["result"]["result"].adjudications]) == db_adj,
             "rows_before": before, "rows_after": after, "no_new_rows": before == after}
    events = status["events"]
    print(json.dumps({
        "fresh_process": True, "run_id": run_id, "run_status": bundle["run"]["status"],
        "is_complete": bundle["is_complete"], "live_input_load_seconds": load_s,
        "checks": checks, "fingerprint": fingerprint, "reuse": reuse,
        "events": [{"seq": e["sequence"], "type": e["event_type"], "batch": e["batch_id"], "status": e["status"]}
                   for e in events],
        "progress": status["progress"], "semantic_batches": [
            {k: b[k] for k in ("batch_id", "effective_status", "provider", "model", "stop_reason", "parse_status",
                               "input_tokens", "output_tokens")} for b in bundle["semantic_batches"]],
        "counts": COUNTS, "check2a_poison_counts": c2a.COUNTS,
    }, indent=1, default=str))


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    {"persist": cmd_persist, "reopen": cmd_reopen}[cmd](*args)
