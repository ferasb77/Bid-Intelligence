"""
CHECK-2A -- one-off live acceptance of Requirement & Evaluation Coverage
Adjudication on the canonical Calgary benchmark (bid 1360, RFP 26-1603).

    python scripts/commission_check2a_calgary.py plan <out_dir>
        READ-ONLY, ZERO provider calls (every Anthropic entry point poisoned):
        loads the live canonical buyer package + persisted bidder package and
        prints/writes the scope gate, deterministic results and the bounded
        batch plan (planned call count).

    python scripts/commission_check2a_calgary.py run <out_dir> [--write-fixture]
        The real acceptance run: the SAME read-only loads, then ONE bounded
        Anthropic call per planned batch (refuses to start if the plan exceeds
        check_coverage.MODEL_CALL_TARGET). Provider calls are counted by a
        wrapper around the shared invocation helper, independently of the
        module's own counter. Writes the full result + raw parsed responses to
        <out_dir> (outside the repo) and, with --write-fixture, the
        CONTENT-FREE replay record tests/fixtures/calgary_26_1603_check2a_
        replay.json (statuses, evidence ids, buyer-verbatim element text only
        -- no bidder prose, no model free text).

Database: SELECT-style reads only (analysis run 34 + its raw snapshot, buyer
'RFP / Source' documents 199-211 from Storage, migration-021 package snapshot
9). Every database write function is poisoned for the whole process; no
telemetry_context is passed, so model_usage_events is not written either.
Run 34's raw snapshot is hashed before and after.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings("ignore")

BID_ID, RUN_ID, SNAPSHOT_ID = 1360, 34, 9
ORG_ID = "4326b564-8cc5-4463-9304-9a589f08cc91"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(REPO, "tests", "fixtures", "calgary_26_1603_check2a_replay.json")
COUNTS = {"provider_attempts": 0, "db_write_attempts": 0}


def _env():
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(REPO, ".env"))
    except Exception:
        pass


def _poison_db_writes():
    import database as db

    def _refuse(*_a, **_k):
        COUNTS["db_write_attempts"] += 1
        raise RuntimeError("CHECK-2A acceptance: database writes are forbidden")
    for name in dir(db):
        if name.startswith(("create_", "get_or_create_", "insert_", "update_", "upsert_", "delete_", "record_",
                            "finalize_", "start_", "persist_", "save_", "mark_", "approve_")):
            fn = getattr(db, name)
            if callable(fn) and getattr(fn, "__module__", None) == "database":
                setattr(db, name, _refuse)
    try:
        import model_telemetry
        for name in ("record_failure", "record_from_anthropic_response"):
            if hasattr(model_telemetry, name):
                setattr(model_telemetry, name, _refuse)
    except Exception:
        pass


def _poison_provider():
    def _refuse(*_a, **_k):
        COUNTS["provider_attempts"] += 1
        raise RuntimeError("CHECK-2A plan: provider calls are forbidden")
    import importlib
    for mod_name in ("config", "full_analysis", "fast_analysis", "analyst", "evidence_strengthening"):
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        for attr in ("get_anthropic_client", "execute_messages_create"):
            if hasattr(mod, attr):
                setattr(mod, attr, _refuse)


def _count_provider():
    """Counting (not blocking) wrapper around the ONE provider helper
    full_analysis._call_model uses."""
    import full_analysis
    original = full_analysis.execute_messages_create

    def _counted(*a, **k):
        COUNTS["provider_attempts"] += 1
        return original(*a, **k)
    full_analysis.execute_messages_create = _counted


def _snapshot_digest() -> str:
    import database as db
    snap = (db.get_analysis_result(RUN_ID) or {}).get("fast_analysis_result_snapshot")
    return hashlib.sha256(json.dumps(snap, sort_keys=True, default=str).encode()).hexdigest()


def load_inputs():
    """Read-only: the live canonical buyer package (the existing
    build_full_analysis_package recomputation, documents retained so the scope
    gate can read the buyer's own deeming statements) + the persisted bidder
    package (migration-021 rows)."""
    import analysis_service
    import database as db
    import full_analysis
    import tenancy
    from extractor import extract_document_with_metadata

    run = db.get_analysis_run(RUN_ID)
    assert run and run.get("status") == "COMPLETE" and int(run.get("bid_id")) == BID_ID, run
    result = analysis_service.load_raw_fast_analysis_result(RUN_ID)
    documents = []
    for d in db.get_documents(BID_ID):
        if d.get("doc_type") != "RFP / Source" or not d.get("storage_path"):
            continue
        data = db.download_file(d["storage_path"])
        if data:
            documents.append((d["name"], extract_document_with_metadata(data, d["name"])[0]))
    cpkg = full_analysis.build_canonical_package(result, bid_id=BID_ID, analysis_run_id=RUN_ID, documents=documents)
    bidder = tenancy.load_submission_evidence_package_for_organization(BID_ID, ORG_ID, SNAPSHOT_ID)
    return run, result, documents, cpkg, bidder


def _inputs_view(result, documents, cpkg, bidder) -> dict:
    return {"buyer_documents": len(documents), "canonical_requirements": len(cpkg.requirements),
            "raw_snapshot_requirements": len(result.requirements), "scoped_criteria": len(cpkg.scoped_criteria),
            "canonical_deadline": dict(cpkg.submission_mechanics).get("submission_deadline"),
            "bidder_files": len(bidder.documents), "logical_artifacts": len(bidder.member_documents()),
            "evidence_items": len(bidder.registry),
            "roles": {d.document_role: d.filename for d in bidder.member_documents()},
            "buyer_package_digest": cpkg.package_digest, "submission_package_digest": bidder.package_digest}


def cmd_plan(out_dir):
    _env()
    _poison_provider()
    _poison_db_writes()
    import check_coverage as cc
    run, result, documents, cpkg, bidder = load_inputs()
    plan = cc.plan_check_coverage(cpkg, bidder, raw_requirements=result.requirements, buyer_documents=documents)
    out = {"inputs": _inputs_view(result, documents, cpkg, bidder), "plan": plan.summary(),
           "scopes": {k: v.to_dict() for k, v in plan.scopes.items()},
           "deterministic": {k: v.to_dict() for k, v in plan.deterministic.items()},
           "provider_attempts": COUNTS["provider_attempts"], "db_write_attempts": COUNTS["db_write_attempts"]}
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "check2a_plan.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False, default=str)
    print(json.dumps({"inputs": out["inputs"], "planned_model_calls": plan.summary()["planned_model_calls"],
                      "batches": plan.summary()["batches"], "provider_attempts": COUNTS["provider_attempts"]},
                     indent=1, default=str))


def _replay_record(res, raw_responses, cc) -> dict:
    by = res.by_id()
    batches = {}
    for bid, rec in raw_responses.items():
        alias = rec["alias_to_eid"]
        objs = next(b["objects"] for b in res.batches if b["batch_id"] == bid)
        rows = []
        for r in (rec["parsed"] or {}).get("adjudications") or []:
            if not isinstance(r, dict) or r.get("object_id") not in objs:
                continue
            wording = by[r["object_id"]].buyer_expectation
            els = []
            for e in r.get("requested_elements") or []:
                if isinstance(e, dict) and cc._buyer_fragment_ok(str(e.get("element") or ""), wording):
                    els.append({"element": e["element"], "coverage": e.get("coverage"),
                                "evidence_ids": [alias.get(x, x) for x in (e.get("evidence_ids") or [])
                                                 if isinstance(x, str)]})
            rows.append({"object_id": r["object_id"], "status": r.get("status"),
                         "evidence_ids": [alias.get(x, x) for x in (r.get("evidence_ids") or [])
                                          if isinstance(x, str)],
                         "requested_elements": els})
        batches[bid] = {"objects": objs, "adjudications": rows}
    return {
        "_provenance": ("CONTENT-FREE record of the live CHECK-2A acceptance run on City of Calgary RFP 26-1603 "
                        "(bid 1360, Fast Analysis run 34, package snapshot 9), written by scripts/"
                        "commission_check2a_calgary.py run --write-fixture. Per batch: the model's status, "
                        "evidence ids (CHECK-1 EV ids) and requested elements whose text is VERBATIM buyer wording. "
                        "No bidder prose and no model free text (summaries / reasons / notes omitted)."),
        "contract_version": res.contract_version, "provider_calls": res.provider_calls,
        "buyer_package_digest": res.buyer_package_digest, "submission_package_digest": res.submission_package_digest,
        "batches": batches,
        "final": {a.buyer_object_id: {"status": a.status, "evidence_ids": list(a.evidence_ids),
                                      "method": a.deterministic_or_model, "scope": a.assurance_scope}
                  for a in res.adjudications},
    }


def cmd_run(out_dir, *flags):
    _env()
    _poison_db_writes()
    import check_coverage as cc
    import config
    run, result, documents, cpkg, bidder = load_inputs()
    digest_before = _snapshot_digest()
    plan = cc.plan_check_coverage(cpkg, bidder, raw_requirements=result.requirements, buyer_documents=documents)
    planned = len(plan.batches)
    if planned > cc.MODEL_CALL_TARGET:
        raise SystemExit(f"STOP: plan needs {planned} calls (> target {cc.MODEL_CALL_TARGET}); redesign batching")
    _count_provider()
    client = config.get_anthropic_client()
    telemetry, raw = [], {}
    t0 = time.monotonic()
    res = cc.run_check_coverage(cpkg, bidder, raw_requirements=result.requirements, buyer_documents=documents,
                                client=client, telemetry=telemetry, raw_responses=raw)
    wall = round(time.monotonic() - t0, 2)
    digest_after = _snapshot_digest()
    screen = cc.artifact_blind_regression_screen(res, bidder)
    summary = {
        "inputs": _inputs_view(result, documents, cpkg, bidder),
        "planned_model_calls": planned, "module_provider_calls": res.provider_calls,
        "independently_counted_provider_calls": COUNTS["provider_attempts"],
        "db_write_attempts": COUNTS["db_write_attempts"],
        "status_counts": res.status_counts(), "scope_counts": res.scope_counts(), "method_counts": res.method_counts(),
        "batches": res.batches,
        "tokens": {"input": sum(r.get("input_tokens") or 0 for r in telemetry),
                   "output": sum(r.get("output_tokens") or 0 for r in telemetry),
                   "per_call": [{k: r.get(k) for k in ("call_kind", "model", "input_tokens", "output_tokens",
                                                       "stop_reason", "parse_status", "latency_seconds")}
                                for r in telemetry]},
        "wall_seconds": wall, "artifact_blind_regression_hits": screen,
        "run34_snapshot_unchanged": digest_before == digest_after, "run34_snapshot_sha256": digest_after,
        "result_digest": cc.result_digest(res),
    }
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "check2a_calgary_result.json"), "w", encoding="utf-8") as fh:
        json.dump({"summary": summary, "result": res.to_dict()}, fh, indent=1, ensure_ascii=False, default=str)
    with open(os.path.join(out_dir, "check2a_raw_responses.json"), "w", encoding="utf-8") as fh:
        json.dump(raw, fh, indent=1, ensure_ascii=False, default=str)
    if "--write-fixture" in flags:
        with open(FIXTURE, "w", encoding="utf-8") as fh:
            json.dump(_replay_record(res, raw, cc), fh, indent=1, ensure_ascii=False)
    print(json.dumps(summary, indent=1, ensure_ascii=False, default=str))


def replay_adjudicator(record: dict):
    """An adjudicate_fn that answers each batch from the recorded live model
    output (content-free record), mapping recorded EV ids to this batch's PE
    aliases. Batch composition must be identical to the recorded run."""
    def fn(prompt, batch):
        rec = record["batches"][batch["batch_id"]]
        assert sorted(t.obj.object_id for t in batch["tasks"]) == sorted(rec["objects"]), batch["batch_id"]
        e2a = {v: k for k, v in batch["alias_to_eid"].items()}
        return {"adjudications": [
            {"object_id": r["object_id"], "status": r["status"],
             "evidence_ids": [e2a.get(x, x) for x in r["evidence_ids"]],
             "requested_elements": [{"element": e["element"], "coverage": e["coverage"],
                                     "evidence_ids": [e2a.get(x, x) for x in e["evidence_ids"]]}
                                    for e in r["requested_elements"]],
             "reason": "recorded live adjudication (reason text omitted from content-free fixture)"}
            for r in rec["adjudications"]]}
    return fn


def cmd_replay(out_dir):
    """ZERO provider calls: re-apply the CURRENT deterministic logic and
    fail-closed validation to the recorded live model output, and refresh the
    record's `final` section (the recorded model output itself is never
    changed)."""
    _env()
    _poison_provider()
    _poison_db_writes()
    import check_coverage as cc
    with open(FIXTURE, encoding="utf-8") as fh:
        record = json.load(fh)
    run, result, documents, cpkg, bidder = load_inputs()
    res = cc.run_check_coverage(cpkg, bidder, raw_requirements=result.requirements, buyer_documents=documents,
                                adjudicate_fn=replay_adjudicator(record))
    before = {k: v["status"] for k, v in record["final"].items()}
    record["final"] = {a.buyer_object_id: {"status": a.status, "evidence_ids": list(a.evidence_ids),
                                           "method": a.deterministic_or_model, "scope": a.assurance_scope}
                       for a in res.adjudications}
    record["final_recomputed_by_replay"] = True
    changed = {k: [before.get(k), v["status"]] for k, v in record["final"].items() if before.get(k) != v["status"]}
    with open(FIXTURE, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=1, ensure_ascii=False)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "check2a_calgary_result_replayed.json"), "w", encoding="utf-8") as fh:
        json.dump({"result": res.to_dict(), "changed_vs_recorded_final": changed}, fh, indent=1,
                  ensure_ascii=False, default=str)
    print(json.dumps({"provider_attempts": COUNTS["provider_attempts"], "db_write_attempts": COUNTS["db_write_attempts"],
                      "replayed_batches": len(res.batches), "status_counts": res.status_counts(),
                      "method_counts": res.method_counts(), "changed_vs_recorded_final": changed,
                      "artifact_blind_regression_hits": cc.artifact_blind_regression_screen(res, bidder),
                      "result_digest": cc.result_digest(res)}, indent=1, default=str))


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    {"plan": cmd_plan, "run": cmd_run, "replay": cmd_replay}[cmd](*args)
