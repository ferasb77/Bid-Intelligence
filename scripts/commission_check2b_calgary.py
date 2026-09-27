"""
CHECK-2B -- durable-run persistence acceptance on the canonical Calgary
benchmark (bid 1360, RFP 26-1603, Fast Analysis run 34, package snapshot 9),
with ZERO provider calls.

    python scripts/commission_check2b_calgary.py persist <out_dir>
        1. Loads the REAL inputs read-only through the production loader
           check_run_service.load_check_inputs (live run 34 raw snapshot, the
           13 buyer 'RFP / Source' documents from Storage, migration-021 rows of
           snapshot 9 via tenancy.load_submission_evidence_package_for_
           organization).
        2. Runs the durable CHECK path (check_run_service.start_check_run,
           inline) with the semantic batches answered by a deterministic REPLAY
           of the already-captured, already-validated live CHECK-2A model output
           (tests/fixtures/calgary_26_1603_check2a_replay.json) -- no new paid
           adjudication.
        3. Persists into tests/check2b_fake_db.FakeCheckDB, the in-memory
           implementation of migration 022's RPC contract, because migration 022
           was not yet applied at CHECK-2B time (CHECK-2B.1 later commissioned it
           live -- see scripts/commission_check2b1_calgary_live.py). The
           store is seeded with the LIVE snapshot-9 evidence ids, so the
           evidence-link FK check runs against the real registry. The store is
           dumped to <out_dir>/check2b_calgary_store.json.

    python scripts/commission_check2b_calgary.py reopen <out_dir>
        In a FRESH process: reloads the dumped store, reconstructs the persisted
        run (zero provider calls), re-runs the section-15 checks, reloads the
        live inputs, recomputes the fingerprint and calls start_check_run again
        with identical inputs -- expected REUSED_COMPLETE with an adjudicator
        that fails if it is ever invoked.

Every database write function and every provider entry point is poisoned for
the whole process (the only "writes" go to the in-memory store).
"""
from __future__ import annotations

import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))
sys.path.insert(0, os.path.join(REPO, "scripts"))

BID_ID, RUN_ID, SNAPSHOT_ID = 1360, 34, 9
ORG_ID = "4326b564-8cc5-4463-9304-9a589f08cc91"
REPLAY = os.path.join(REPO, "tests", "fixtures", "calgary_26_1603_check2a_replay.json")
STORE = "check2b_calgary_store.json"
COUNTS = {"adjudicator_invocations": 0}


def _setup():
    import commission_check2a_calgary as c2a
    c2a._env()
    c2a._poison_provider()
    c2a._poison_db_writes()
    return c2a


def _replay_fn(record):
    import commission_check2a_calgary as c2a
    inner = c2a.replay_adjudicator(record)

    def fn(prompt, batch):
        COUNTS["adjudicator_invocations"] += 1
        return inner(prompt, batch)
    return fn


def _live_inputs():
    import check_run_service as csr
    t0 = time.monotonic()
    inputs = csr.load_check_inputs(BID_ID, ORG_ID, package_snapshot_id=SNAPSHOT_ID, source_run_id=RUN_ID)
    return inputs, round(time.monotonic() - t0, 2)


def _checks(bundle, inputs, record) -> dict:
    import check_coverage as cc
    import submission_package as sp
    res = bundle["result"]
    by = res.by_id()
    bidder = inputs.submission_package
    role_ids = {role: {i.evidence_id for d in bidder.documents_with_roles([role], include_secondary=False)
                       for i in bidder.registry.for_document(d.submission_document_id)}
                for role in (sp.ROLE_MULTI_PARTY_FORM, sp.ROLE_PRICING_FORM, sp.ROLE_SUBMISSION_FORM)}
    live = record["final"]
    registry = {i.evidence_id for i in bidder.registry}
    req41 = by["REQ-41"]
    return {
        "run_status": bundle["run"]["status"],
        "objects": len(res.adjudications),
        "requirements": sum(a.buyer_object_type == cc.OBJECT_REQUIREMENT for a in res.adjudications),
        "criteria": sum(a.buyer_object_type == cc.OBJECT_CRITERION for a in res.adjudications),
        "status_counts": {k: v for k, v in res.status_counts().items() if v},
        "scope_counts": {k: v for k, v in res.scope_counts().items() if v},
        "method_counts": res.method_counts(),
        "statuses_match_validated_check2a": all(a.status == live[a.buyer_object_id]["status"]
                                               for a in res.adjudications) and len(live) == len(res.adjudications),
        "evidence_ids_round_trip": all(sorted(a.evidence_ids) == sorted(live[a.buyer_object_id]["evidence_ids"])
                                       for a in res.adjudications),
        "all_cited_ids_in_live_snapshot9_registry": all(
            e in registry for a in res.adjudications for e in list(a.evidence_ids)
            + [x for g in (a.addressed_elements, a.missing_elements, a.unverifiable_elements) for el in g
               for x in (el.get("evidence_ids") or [])]),
        "criteria_reconstructed": sorted(a.buyer_object_id for a in res.adjudications
                                         if a.buyer_object_type == cc.OBJECT_CRITERION),
        "REQ-46": {"status": by["REQ-46"].status, "method": by["REQ-46"].deterministic_or_model,
                   "b2_evidence": len(set(by["REQ-46"].evidence_ids) & role_ids[sp.ROLE_MULTI_PARTY_FORM])},
        "pricing": {cid: {"status": by[cid].status,
                          "all_from_appendix_d": set(by[cid].evidence_ids) <= role_ids[sp.ROLE_PRICING_FORM],
                          "evidence": len(by[cid].evidence_ids)} for cid in ("CRIT-price", "CRIT-pricing")},
        "appendix_e": {rid: {"status": by[rid].status,
                             "all_from_appendix_e": set(by[rid].evidence_ids) <= role_ids[sp.ROLE_SUBMISSION_FORM],
                             "evidence": len(by[rid].evidence_ids)} for rid in ("REQ-33", "REQ-37")},
        "portal_native_all_not_verifiable": all(a.status == cc.STATUS_NOT_VERIFIABLE for a in res.adjudications
                                                if a.assurance_scope == cc.SCOPE_PORTAL_NATIVE),
        "human_review": sorted(a.buyer_object_id for a in res.adjudications if a.status == cc.STATUS_HUMAN_REVIEW),
        "excluded_never_gaps": all(a.status == cc.STATUS_NOT_APPLICABLE and not a.missing_elements
                                   for a in res.adjudications if a.assurance_scope in cc.EXCLUDED_SCOPES),
        "not_addressed": sum(a.status == cc.STATUS_NOT_ADDRESSED for a in res.adjudications),
        "REQ-41": {"status": req41.status, "past_five_years_element": next(
            (e["coverage"] for e in req41.missing_elements if e["element"].startswith("three (3) examples from the past")),
            None)},
        "result_digest": cc.result_digest(res),
        "result_digest_verified": bundle["result_digest_verified"],
    }


def cmd_persist(out_dir):
    _setup()
    import check_run_service as csr
    from check2b_fake_db import FakeCheckDB
    with open(REPLAY, encoding="utf-8") as fh:
        record = json.load(fh)
    inputs, load_s = _live_inputs()                 # live, read-only (before the store is installed)
    store = FakeCheckDB()
    store.add_fast_run(BID_ID, RUN_ID)
    store.add_snapshot(BID_ID, SNAPSHOT_ID, [i.evidence_id for i in inputs.submission_package.registry])
    store.install(lambda mod, name, value: setattr(mod, name, value))
    fn = _replay_fn(record)
    out = csr.start_check_run(BID_ID, ORG_ID, package_snapshot_id=SNAPSHOT_ID, source_run_id=RUN_ID,
                              inputs_loader=lambda *a, **k: inputs, adjudicate_fn=fn,
                              adjudication_source=csr.SOURCE_REPLAY, execution=csr.EXECUTION_INLINE)
    run_id = out["run"]["id"]
    bundle = csr.get_check_run_result(BID_ID, run_id)
    status = csr.get_check_run_status(BID_ID, run_id)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, STORE), "w", encoding="utf-8") as fh:
        json.dump(store.dump(), fh, default=str)
    summary = {
        "live_input_load_seconds": load_s, "outcome": out["outcome"], "run_id": run_id,
        "input_fingerprint": out["input_fingerprint"],
        "buyer_package_digest": inputs.canonical_package.package_digest,
        "submission_package_digest": inputs.submission_package.package_digest,
        "live_snapshot9_evidence_items": len(inputs.submission_package.registry),
        "adjudicator_invocations": COUNTS["adjudicator_invocations"],
        "live_provider_calls": store.runs[run_id]["telemetry"]["live_provider_calls"],
        "semantic_batches": [{k: b[k] for k in ("batch_id", "effective_status", "stop_reason", "parse_status")}
                             for b in store.get_check_semantic_batches(run_id)],
        "events": [e["event_type"] for e in store.get_check_run_events(run_id)],
        "progress": status["progress"],
        "persisted_rows": {"adjudications": len(store.adjudications), "evidence_links": len(store.evidence_links),
                           "batches": len(store.batches), "events": len(store.events)},
        "checks": _checks(bundle, inputs, record),
    }
    print(json.dumps(summary, indent=1, default=str))


def cmd_reopen(out_dir):
    _setup()
    import check_coverage as cc
    import check_run_service as csr
    from check2b_fake_db import FakeCheckDB
    with open(REPLAY, encoding="utf-8") as fh:
        record = json.load(fh)
    with open(os.path.join(out_dir, STORE), encoding="utf-8") as fh:
        dumped = json.load(fh)
    inputs, load_s = _live_inputs()
    store = FakeCheckDB.load(dumped)
    store.install(lambda mod, name, value: setattr(mod, name, value))
    run_id = max(r["id"] for r in store.runs.values() if r["analysis_mode"] == "CHECK")
    bundle = csr.get_check_run_result(BID_ID, run_id)

    def must_not_run(prompt, batch):
        COUNTS["adjudicator_invocations"] += 1
        raise AssertionError("REUSED_COMPLETE must not adjudicate")
    again = csr.start_check_run(BID_ID, ORG_ID, package_snapshot_id=SNAPSHOT_ID, source_run_id=RUN_ID,
                                inputs_loader=lambda *a, **k: inputs, adjudicate_fn=must_not_run,
                                execution=csr.EXECUTION_INLINE)
    fresh_pure = cc.run_check_coverage(inputs.canonical_package, inputs.submission_package,
                                       raw_requirements=inputs.raw_requirements, buyer_documents=inputs.buyer_documents,
                                       adjudicate_fn=_replay_fn(record))
    norm = lambda r: json.dumps([a.to_dict() for a in r.adjudications], sort_keys=True, default=str)  # noqa: E731
    print(json.dumps({
        "fresh_process": True, "live_input_load_seconds": load_s, "reopened_run_id": run_id,
        "fingerprint_recomputed": csr.compute_check_fingerprint(inputs),
        "fingerprint_persisted": store.runs[run_id]["input_fingerprint"],
        "reuse_outcome": again["outcome"], "reuse_run_id": again["run"]["id"],
        "adjudicator_invocations_on_reuse_and_reopen": COUNTS["adjudicator_invocations"] - len(record["batches"]),
        "reused_result_identical_to_reopened": norm(again["result"]["result"]) == norm(bundle["result"]),
        "reopened_identical_to_fresh_pure_check2a": norm(bundle["result"]) == norm(fresh_pure),
        "checks": _checks(bundle, inputs, record),
    }, indent=1, default=str))


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    {"persist": cmd_persist, "reopen": cmd_reopen}[cmd](*args)
