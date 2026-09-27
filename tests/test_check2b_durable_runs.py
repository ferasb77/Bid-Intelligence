"""
CHECK-2B: Durable Proposal Assurance (CHECK) runs.

Fully deterministic: ZERO live provider calls (semantic batches are answered
by injected adjudicators or by a local mock Anthropic client driven through
the REAL full_analysis._call_model / config.execute_messages_create path),
no live database -- migration 022's three RPCs and four tables are simulated
by tests/check2b_fake_db.FakeCheckDB, which implements the SAME contract the
SQL enforces. Static checks assert the migration SQL actually states those
rules. Section R replays the real, already-validated CHECK-2A Calgary
adjudication (tests/fixtures/calgary_26_1603_check2a_replay.json) through
the durable path against the real Calgary files (skipped when absent).
"""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
import threading
import time
import zipfile
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import check_coverage as cc  # noqa: E402
import check_run_service as csr  # noqa: E402
import database  # noqa: E402
import fast_analysis  # noqa: E402
import full_analysis  # noqa: E402
import submission_package as sp  # noqa: E402
import tenancy  # noqa: E402
from check2b_fake_db import FakeCheckDB  # noqa: E402
from test_check2a_coverage_adjudication import (  # noqa: E402
    BUYER_DOCS, EVAL, ORDER, REQS, build_package, canonical, req_id,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATION_022 = (ROOT / "migrations" / "022_check_runs.sql").read_text(encoding="utf-8")
BID, ORG, OTHER_BID = 7001, "org-test", 7002
FAST_RUN, SNAPSHOT = 1, 11


@pytest.fixture(autouse=True)
def _no_live_provider(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("CHECK-2B tests must never reach a live model provider")
    import config
    monkeypatch.setattr(config, "get_anthropic_client", refuse)


# ═══════════════════════════════════════════════════════════════════════
# Builders
# ═══════════════════════════════════════════════════════════════════════

def canonical_from(raw, evals=None, bid=BID, run_id=1):
    result = fast_analysis.FastAnalysisResult(requirements=[dict(r) for r in raw],
                                              evaluation_criteria=list(EVAL if evals is None else evals))
    return full_analysis.build_canonical_package(result, bid_id=bid, analysis_run_id=run_id)


def make_inputs(*, pkg=None, raw=None, evals=None, docs=BUYER_DOCS, bid=BID, snapshot=SNAPSHOT, run_id=FAST_RUN):
    raw = raw if raw is not None else [dict(REQS[k]) for k in ORDER]
    pkg = pkg or build_package(bid=bid)
    return csr.CheckInputs(bid_id=bid, source_analysis_run_id=run_id, package_snapshot_id=snapshot,
                           canonical_package=canonical_from(raw, evals, bid=bid, run_id=run_id),
                           raw_requirements=raw, buyer_documents=list(docs), submission_package=pkg)


def loader_for(inputs, delay=None, barrier=None):
    calls = []

    def load(bid_id, organization_id, *, package_snapshot_id=None, source_run_id=None):
        calls.append(bid_id)
        if barrier is not None:
            barrier.wait()
        if delay:
            time.sleep(delay)
        return inputs
    load.calls = calls
    return load


class EchoModel:
    """Injected adjudicator: one call per batch; per object ADDRESSED on the
    first two issued aliases (or a scripted override)."""

    def __init__(self, override=None, raise_for=(), omit=(), delay=0.0):
        self.calls, self.override, self.raise_for, self.omit, self.delay = [], override or {}, raise_for, omit, delay

    def __call__(self, prompt, batch):
        self.calls.append(batch["batch_id"])
        if self.delay:
            time.sleep(self.delay)
        if batch["batch_id"] in self.raise_for:
            raise RuntimeError("simulated adjudicator failure")
        e2a = {v: k for k, v in batch["alias_to_eid"].items()}
        rows = []
        for t in batch["tasks"]:
            oid = t.obj.object_id
            if oid in self.omit:
                continue
            aliases = [e2a[e] for e in t.evidence_ids if e in e2a][:2]
            row = {"object_id": oid, "status": "ADDRESSED", "evidence_ids": aliases,
                   "requested_elements": [{"element": t.obj.wording[:40], "coverage": "ADDRESSED",
                                           "evidence_ids": aliases, "note": "present"}],
                   "evidence_summary": "evidence present", "reason": ""}
            if oid in self.override:
                row = self.override[oid](t, aliases, row)
            rows.append(row)
        return {"adjudications": rows}


def _objects_in_prompt(prompt):
    seg = prompt.split("BUYER OBJECTS TO ADJUDICATE:\n", 1)[1].split("\n\nEVIDENCE (bidder files only", 1)[0]
    return json.loads(seg)


class MockAnthropic:
    """Local stand-in for anthropic.Anthropic driven through the REAL
    full_analysis._call_model -> config.execute_messages_create path.
    `stop_for` maps a batch marker (an object id in the prompt) to a
    provider stop_reason; `cut_for` truncates the JSON body."""

    def __init__(self, stop_for=None, cut_for=(), explode=False, cut_len=25):
        self.prompts, self.cut_len = [], cut_len
        self.stop_for, self.cut_for, self.explode = stop_for or {}, cut_for, explode
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        if self.explode:
            raise AssertionError("this client must never be called")
        prompt = kwargs["messages"][0]["content"][0]["text"]
        self.prompts.append(prompt)
        objs = _objects_in_prompt(prompt)
        rows = []
        for o in objs:
            aliases = o["evidence_retrieved_for_this_object"][:2]
            rows.append({"object_id": o["object_id"], "status": "ADDRESSED", "evidence_ids": aliases,
                         "requested_elements": [{"element": o["buyer_wording"][:40], "coverage": "ADDRESSED",
                                                 "evidence_ids": aliases}]})
        text = json.dumps({"adjudications": rows})
        ids = [o["object_id"] for o in objs]
        stop = next((s for k, s in self.stop_for.items() if k in ids), "end_turn")
        if any(k in ids for k in self.cut_for):
            text = text[:self.cut_len]   # default: '{"adjudications": [{"obj' -- nothing recoverable
        return SimpleNamespace(content=[SimpleNamespace(text=text)], stop_reason=stop, model=kwargs.get("model"),
                               usage=SimpleNamespace(input_tokens=1200, output_tokens=300,
                                                     cache_creation_input_tokens=0, cache_read_input_tokens=0))


@pytest.fixture
def fake(monkeypatch):
    f = FakeCheckDB()
    f.add_fast_run(BID, FAST_RUN)
    f.add_fast_run(OTHER_BID, 2)
    f.add_snapshot(BID, SNAPSHOT, [i.evidence_id for i in build_package(bid=BID).registry])
    f.add_snapshot(OTHER_BID, 12, [i.evidence_id for i in build_package(bid=OTHER_BID).registry])
    f.install(monkeypatch.setattr)
    return f


def start(inputs=None, *, model=None, client=None, bid=BID, **kw):
    kw.setdefault("execution", csr.EXECUTION_INLINE)
    inputs = inputs or make_inputs()
    if client is None and model is None:
        model = EchoModel()
    return csr.start_check_run(bid, ORG, inputs_loader=loader_for(inputs), adjudicate_fn=model, client=client, **kw)


def pure_result(inputs, model):
    return cc.run_check_coverage(inputs.canonical_package, inputs.submission_package,
                                 raw_requirements=inputs.raw_requirements, buyer_documents=inputs.buyer_documents,
                                 adjudicate_fn=model)


def _norm(x):
    return json.loads(json.dumps(x, sort_keys=True, default=str))


def _adj_dicts(result):
    return _norm([a.to_dict() for a in result.adjudications])


# ═══════════════════════════════════════════════════════════════════════
# A. Fingerprint (sections 4 / 17)
# ═══════════════════════════════════════════════════════════════════════

class TestFingerprint:
    def test_stable_for_identical_inputs_built_independently(self):
        assert csr.compute_check_fingerprint(make_inputs()) == csr.compute_check_fingerprint(make_inputs())

    def test_canonical_buyer_requirement_change_invalidates(self):
        raw = [dict(REQS[k]) for k in ORDER]
        raw[ORDER.index("firm_experience")]["description"] += " Include client references."
        assert csr.compute_check_fingerprint(make_inputs(raw=raw)) != csr.compute_check_fingerprint(make_inputs())

    def test_scoped_criterion_change_invalidates(self):
        evals = copy.deepcopy(EVAL)
        evals[0]["weight"] = "35%"
        assert csr.compute_check_fingerprint(make_inputs(evals=evals)) != \
            csr.compute_check_fingerprint(make_inputs())
        evals = copy.deepcopy(EVAL)
        evals[0]["threshold"] = "70%"
        assert csr.compute_check_fingerprint(make_inputs(evals=evals)) != \
            csr.compute_check_fingerprint(make_inputs())

    def test_submission_evidence_change_invalidates(self):
        pkg = build_package()
        items = list(pkg.registry)
        items[0] = sp.EvidenceItem(**{**items[0].__dict__, "content": items[0].content + " (revised)"})
        changed = sp.SubmissionPackage(bid_id=BID, organization_id=ORG, package_digest=pkg.package_digest,
                                       documents=pkg.documents, registry=sp.SubmissionEvidenceRegistry(BID, items),
                                       manifest=())
        assert csr.compute_check_fingerprint(make_inputs(pkg=changed)) != csr.compute_check_fingerprint(make_inputs())
        # a missing artifact (no multi-party form) also invalidates
        assert csr.compute_check_fingerprint(make_inputs(pkg=build_package(with_multiparty=False))) != \
            csr.compute_check_fingerprint(make_inputs())

    def test_buyer_document_deeming_text_change_invalidates(self):
        docs = [(BUYER_DOCS[0][0], BUYER_DOCS[0][1] + " Extra buyer sentence."), BUYER_DOCS[1]]
        assert csr.compute_check_fingerprint(make_inputs(docs=docs)) != csr.compute_check_fingerprint(make_inputs())

    @pytest.mark.parametrize("attr", ["ADJUDICATION_VERSION", "SCOPE_GATE_VERSION", "RETRIEVAL_VERSION",
                                      "DETERMINISTIC_RULE_VERSION", "PROMPT_SCHEMA_VERSION"])
    def test_check_architecture_version_change_invalidates(self, monkeypatch, attr):
        before = csr.compute_check_fingerprint(make_inputs())
        monkeypatch.setattr(cc, attr, getattr(cc, attr) + "-bumped")
        assert csr.compute_check_fingerprint(make_inputs()) != before

    def test_prompt_model_and_bound_changes_invalidate_without_a_version_bump(self, monkeypatch):
        before = csr.compute_check_fingerprint(make_inputs())
        for mod, attr, value in ((cc, "_ADJUDICATION_RULES", cc._ADJUDICATION_RULES + "\n- extra rule"),
                                 (full_analysis, "FULL_ANALYSIS_MODEL", "claude-other-model"),
                                 (cc, "MODEL_MAX_OUTPUT_TOKENS", 4000)):
            original = getattr(mod, attr)
            monkeypatch.setattr(mod, attr, value)
            assert csr.compute_check_fingerprint(make_inputs()) != before, attr
            monkeypatch.setattr(mod, attr, original)
        assert csr.compute_check_fingerprint(make_inputs()) == before

    def test_timestamps_run_ids_snapshot_ids_and_ordering_are_ignored(self):
        base = csr.compute_check_fingerprint(make_inputs())
        # other source-run id / snapshot id / canonical analysis_run_id: identity rows, not semantics
        assert csr.compute_check_fingerprint(make_inputs(run_id=99, snapshot=77)) == base
        # evidence registry in a different order (e.g. persisted rows reloaded)
        pkg = build_package()
        rev = sp.SubmissionPackage(bid_id=BID, organization_id="another-ui-session", package_digest=pkg.package_digest,
                                   documents=tuple(reversed(pkg.documents)),
                                   registry=sp.SubmissionEvidenceRegistry(BID, list(reversed(list(pkg.registry)))),
                                   manifest=())
        assert csr.compute_check_fingerprint(make_inputs(pkg=rev)) == base
        blob = json.dumps(csr.check_fingerprint_inputs(make_inputs()))
        for forbidden in ("created_at", "occurred_at", "started_at", "last_progress_at", "run_id", "sequence",
                          "package_snapshot_id", "session"):
            assert f'"{forbidden}"' not in blob, forbidden

    def test_fingerprint_inputs_cover_every_required_dimension(self):
        fi = csr.check_fingerprint_inputs(make_inputs())
        assert set(fi) == {"fingerprint_version", "architecture", "model", "buyer", "bidder"}
        assert {"scope_gate_version", "retrieval_version", "adjudication_version", "deterministic_rule_version",
                "prompt_schema_version", "check2a_contract_version"} <= set(fi["architecture"])
        assert {"model", "provider", "max_output_tokens", "prompt_rules_sha256"} <= set(fi["model"])
        assert {"canonical_snapshot_digest", "canonical_content_digest", "requirement_ids", "criterion_ids",
                "buyer_objects_digest", "expected_evidence_digest", "buyer_documents"} <= set(fi["buyer"])
        assert {"submission_package_digest", "documents_digest", "evidence_registry_digest",
                "authoritative_artifacts"} <= set(fi["bidder"])


# ═══════════════════════════════════════════════════════════════════════
# B. Start semantics / duplicate-run protection (section 5)
# ═══════════════════════════════════════════════════════════════════════

class TestStartSemantics:
    def test_created_executes_to_complete(self, fake):
        model = EchoModel()
        out = start(model=model)
        run = fake.runs[out["run"]["id"]]
        assert out["outcome"] == csr.OUTCOME_CREATED
        assert run["analysis_mode"] == "CHECK" and run["status"] == "COMPLETE"
        assert run["source_analysis_run_id"] == FAST_RUN and run["source_package_snapshot_id"] == SNAPSHOT
        assert model.calls == ["B1", "B2"]

    def test_identical_inputs_reuse_complete_with_zero_calls(self, fake):
        first = start()
        model = EchoModel()
        second = start(model=model)
        assert second["outcome"] == csr.OUTCOME_REUSED_COMPLETE
        assert second["run"]["id"] == first["run"]["id"] and model.calls == []
        assert second["result"]["result_digest_verified"] is True
        assert len([r for r in fake.runs.values() if r["analysis_mode"] == "CHECK"]) == 1

    def test_active_run_is_returned_not_duplicated(self, fake):
        inflight = fake.start_check_run(BID, FAST_RUN, SNAPSHOT, "fp-inflight", "e")["run"]
        model = EchoModel()
        out = start(model=model)
        assert out["outcome"] == csr.OUTCOME_ACTIVE_RUN_EXISTS and out["run"]["id"] == inflight["id"]
        assert model.calls == [] and not out["executing"]

    def test_existing_failed_is_not_silently_retried(self, fake, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("canonical input exploded")
        real = cc.run_check_coverage
        monkeypatch.setattr(cc, "run_check_coverage", boom)
        first = start()
        assert fake.runs[first["run"]["id"]]["status"] == "FAILED"
        assert "canonical input exploded" in fake.runs[first["run"]["id"]]["failure_reason"]
        monkeypatch.setattr(cc, "run_check_coverage", real)
        model = EchoModel()
        again = start(model=model)
        assert again["outcome"] == csr.OUTCOME_EXISTING_FAILED and model.calls == []
        retried = start(model=model, retry=True)
        assert retried["outcome"] == csr.OUTCOME_CREATED and fake.runs[retried["run"]["id"]]["status"] == "COMPLETE"
        assert fake.runs[first["run"]["id"]]["status"] == "FAILED"          # history preserved

    def test_existing_partial_requires_explicit_retry(self, fake):
        first = start(model=EchoModel(raise_for=("B1",)))
        assert fake.runs[first["run"]["id"]]["status"] == "PARTIAL"
        model = EchoModel()
        again = start(model=model)
        assert again["outcome"] == csr.OUTCOME_EXISTING_PARTIAL and model.calls == []
        retried = start(model=model, retry=True)
        assert retried["outcome"] == csr.OUTCOME_CREATED and model.calls == ["B1", "B2"]

    def test_concurrent_duplicate_starts_create_exactly_one_run(self, fake):
        inputs = make_inputs()
        barrier = threading.Barrier(5)
        model = EchoModel(delay=0.2)
        outcomes = []

        def click():
            outcomes.append(csr.start_check_run(BID, ORG, inputs_loader=loader_for(inputs, barrier=barrier),
                                                adjudicate_fn=model, execution=csr.EXECUTION_INLINE)["outcome"])
        threads = [threading.Thread(target=click) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert outcomes.count(csr.OUTCOME_CREATED) == 1
        assert set(outcomes) <= {csr.OUTCOME_CREATED, csr.OUTCOME_ACTIVE_RUN_EXISTS, csr.OUTCOME_REUSED_COMPLETE}
        assert len([r for r in fake.runs.values() if r["analysis_mode"] == "CHECK"]) == 1
        assert model.calls == ["B1", "B2"]                      # paid once

    def test_background_execution_persists_independently(self, fake):
        out = start(execution=csr.EXECUTION_BACKGROUND)
        assert out["executing"] is True
        for _ in range(100):
            if fake.runs[out["run"]["id"]]["status"] in ("COMPLETE", "PARTIAL", "FAILED"):
                break
            time.sleep(0.02)
        assert fake.runs[out["run"]["id"]]["status"] == "COMPLETE"

    def test_changed_input_creates_a_new_run_and_keeps_history(self, fake):
        first = start()
        raw = [dict(REQS[k]) for k in ORDER]
        raw[ORDER.index("service")]["description"] += " Describe escalation paths."
        second = start(make_inputs(raw=raw))
        assert second["outcome"] == csr.OUTCOME_CREATED and second["run"]["id"] != first["run"]["id"]
        assert fake.runs[first["run"]["id"]]["status"] == "COMPLETE"


# ═══════════════════════════════════════════════════════════════════════
# C. Immutable persistence / reconstruction (sections 6 / 7 / 15)
# ═══════════════════════════════════════════════════════════════════════

def _partial_firm(t, aliases, row):
    row["status"] = "PARTIALLY_ADDRESSED"
    row["requested_elements"] = [
        {"element": "An overview of the services provided", "coverage": "ADDRESSED", "evidence_ids": aliases},
        {"element": "Key outcomes or results achieved", "coverage": "ABSENT", "evidence_ids": []}]
    row["reason"] = "outcomes absent"
    return row


class TestPersistence:
    def test_every_adjudication_field_round_trips(self, fake):
        inputs = make_inputs()
        model = EchoModel(override={req_id("firm_experience"): _partial_firm})
        out = start(inputs, model=model)
        original = pure_result(make_inputs(), EchoModel(override={req_id("firm_experience"): _partial_firm}))
        reopened = csr.get_check_run_result(BID, out["run"]["id"])
        assert _adj_dicts(reopened["result"]) == _adj_dicts(original)
        assert cc.result_digest(reopened["result"]) == cc.result_digest(original)
        assert reopened["result"].status_counts() == original.status_counts()
        assert reopened["result"].provider_calls == original.provider_calls
        row = fake.adjudications[0]
        for col in ("buyer_object_id", "buyer_object_type", "assurance_scope", "status", "buyer_expectation",
                    "expected_evidence_roles", "evidence_ids", "evidence_refs", "evidence_summary",
                    "addressed_elements", "missing_elements", "unverifiable_elements", "ambiguity_or_review_reason",
                    "buyer_weight", "buyer_threshold", "adjudication_method", "validation", "source_provenance"):
            assert col in row, col

    def test_structured_elements_weights_thresholds_and_provenance_preserved(self, fake):
        out = start(model=EchoModel(override={req_id("firm_experience"): _partial_firm}))
        by = csr.get_check_run_result(BID, out["run"]["id"])["result"].by_id()
        firm = by[req_id("firm_experience")]
        assert firm.status == cc.STATUS_PARTIALLY_ADDRESSED
        assert [e["element"] for e in firm.missing_elements] == ["Key outcomes or results achieved"]
        assert firm.missing_elements[0]["coverage"] == cc.ELEMENT_ABSENT
        assert firm.addressed_elements and firm.addressed_elements[0]["evidence_ids"]
        crit = by["CRIT-firm-experience"]
        assert crit.buyer_weight == "30%" and crit.buyer_threshold == "60%"
        assert set(crit.buyer_weight_variants) == {"30%", "20%"} and isinstance(crit.buyer_weight_variants, tuple)
        assert crit.source_provenance["authoritative_source"]
        assert crit.linked_requirement_ids and isinstance(crit.linked_requirement_ids, tuple)
        row = next(r for r in fake.adjudications if r["buyer_object_id"] == req_id("firm_experience"))
        pkg = build_package()
        for ref in row["evidence_refs"]:
            it = pkg.registry.get(ref["evidence_id"], bid_id=BID)
            assert ref["submission_document_id"] == it.submission_document_id
            assert ref["logical_artifact_id"] == pkg.document(it.submission_document_id).logical_artifact_id

    def test_evidence_ids_round_trip_and_are_db_linked(self, fake):
        out = start()
        run_id = out["run"]["id"]
        result = csr.get_check_run_result(BID, run_id)["result"]
        links = {(l["buyer_object_id"], l["evidence_id"]): l["reference_kind"] for l in fake.evidence_links
                 if l["run_id"] == run_id}
        for a in result.adjudications:
            for e in a.evidence_ids:
                assert links[(a.buyer_object_id, e)] == "VERDICT"
            for grp in (a.addressed_elements, a.missing_elements, a.unverifiable_elements):
                for el in grp:
                    for e in el.get("evidence_ids") or []:
                        assert (a.buyer_object_id, e) in links
        assert all(l["package_snapshot_id"] == SNAPSHOT and l["bid_id"] == BID for l in fake.evidence_links)

    def test_reopen_in_a_fresh_store_is_semantically_identical(self, fake, monkeypatch):
        out = start()
        original = csr.get_check_run_result(BID, out["run"]["id"])
        blob = json.dumps(fake.dump(), default=str)
        fresh = FakeCheckDB.load(json.loads(blob))
        fresh.install(monkeypatch.setattr)
        reopened = csr.get_check_run_result(BID, out["run"]["id"])
        assert _adj_dicts(reopened["result"]) == _adj_dicts(original["result"])
        assert reopened["result_digest_verified"] is True

    def test_default_result_prefers_complete_then_partial_never_failed(self, fake, monkeypatch):
        assert csr.get_check_run_result(BID) is None
        partial = start(model=EchoModel(raise_for=("B2",)))
        assert csr.get_check_run_result(BID)["run"]["id"] == partial["run"]["id"]
        complete = start(model=EchoModel(), retry=True)
        assert csr.get_check_run_result(BID)["run"]["id"] == complete["run"]["id"]


# ═══════════════════════════════════════════════════════════════════════
# D. Evidence integrity on persistence (section 7)
# ═══════════════════════════════════════════════════════════════════════

class TestEvidenceIntegrity:
    def _poisoned(self, monkeypatch, mutate):
        real = cc.run_check_coverage

        def wrapped(*a, **k):
            res = real(*a, **k)
            mutate(res)
            return res
        monkeypatch.setattr(cc, "run_check_coverage", wrapped)

    @pytest.mark.parametrize("bad_id", ["REQ-3", "CE1", "EV-00000000000000000000",
                                        sp.derive_evidence_id(OTHER_BID, "doc-tech", "SECTION_TEXT", "p1b1")])
    def test_invalid_in_memory_evidence_never_becomes_durable(self, fake, monkeypatch, bad_id):
        def mutate(res):
            a = next(x for x in res.adjudications if x.status == cc.STATUS_ADDRESSED)
            a.evidence_ids = tuple(a.evidence_ids) + (bad_id,)
        self._poisoned(monkeypatch, mutate)
        out = start()
        run = fake.runs[out["run"]["id"]]
        assert run["status"] == "FAILED" and "integrity validation failed" in run["failure_reason"]
        assert not [a for a in fake.adjudications if a["run_id"] == run["id"]]
        assert out["run"]["id"] not in fake.results
        assert any(bad_id in v for v in run["failure_detail"]["integrity_violations"])

    def test_positive_verdict_without_evidence_is_rejected(self, fake, monkeypatch):
        def mutate(res):
            a = next(x for x in res.adjudications if x.status == cc.STATUS_ADDRESSED)
            a.evidence_ids = ()
        self._poisoned(monkeypatch, mutate)
        out = start()
        assert fake.runs[out["run"]["id"]]["status"] == "FAILED"

    def test_database_fk_refuses_cross_bid_evidence_atomically(self, fake):
        run = fake.start_check_run(BID, FAST_RUN, SNAPSHOT, "fp", "e")["run"]
        good = pure_result(make_inputs(), EchoModel())
        rows = [csr.adjudication_row(a, build_package()) for a in good.adjudications]
        rows[0] = dict(rows[0], status="ADDRESSED", assurance_scope="SUBMISSION_RESPONSE_REQUIRED",
                       evidence_ids=[sp.derive_evidence_id(OTHER_BID, "doc-tech", "SECTION_TEXT", "p1b1")])
        result = {"run_integrity": "PARTIAL", "object_counts": {"total": len(rows)}}
        with pytest.raises(RuntimeError, match="foreign key"):
            fake.finalize_check_run(run["id"], BID, "PARTIAL", result=result, adjudications=rows)
        assert not fake.adjudications and not fake.evidence_links and fake.runs[run["id"]]["status"] == "QUEUED"

    def test_cross_bid_inputs_and_snapshots_are_refused(self, fake):
        with pytest.raises(sp.CrossBidEvidenceError):
            start(make_inputs(bid=OTHER_BID, snapshot=12, run_id=2), bid=BID)
        with pytest.raises(RuntimeError, match="does not belong"):
            fake.start_check_run(BID, FAST_RUN, 12, "fp", "e")          # bid 7002's snapshot
        with pytest.raises(RuntimeError, match="not a COMPLETE FAST run"):
            fake.start_check_run(BID, 2, SNAPSHOT, "fp", "e")            # bid 7002's source run

    def test_validation_flags_non_authoritative_representation_evidence(self):
        pkg = build_package()
        res = pure_result(make_inputs(pkg=pkg), EchoModel())
        docs = tuple(d if d.submission_document_id != "doc-subform" else
                     sp.SubmissionDocument(**{**d.__dict__, "representation_relationship": sp.REP_ALTERNATE,
                                              "representation_of": "doc-tech"}) for d in pkg.documents)
        alt = sp.SubmissionPackage(bid_id=BID, organization_id=ORG, package_digest=pkg.package_digest,
                                   documents=docs, registry=pkg.registry, manifest=())
        v = csr.validate_result_for_persistence(res, alt, bid_id=BID,
                                                expected_object_ids=[a.buyer_object_id for a in res.adjudications])
        assert any("non-authoritative" in x for x in v)
        assert csr.validate_result_for_persistence(
            res, pkg, bid_id=BID, expected_object_ids=[a.buyer_object_id for a in res.adjudications]) == []

    def test_batch_rows_cannot_reference_foreign_evidence(self, fake):
        run = fake.start_check_run(BID, FAST_RUN, SNAPSHOT, "fp", "e")["run"]
        with pytest.raises(RuntimeError, match="outside bid snapshot"):
            fake.record_check_run_event(run["id"], BID, "SEMANTIC_BATCH_COMPLETED", batch_id="B1",
                                        batch_result={"effective_status": "COMPLETE", "buyer_object_ids": [],
                                                      "candidate_evidence_ids": ["REQ-1"]})


# ═══════════════════════════════════════════════════════════════════════
# E. Run status (section 8) and events (section 9)
# ═══════════════════════════════════════════════════════════════════════

def _review(t, aliases, row):
    return dict(row, status="HUMAN_REVIEW_REQUIRED", requested_elements=[], evidence_ids=[],
                reason="evidence conflicts")


def _unverifiable(t, aliases, row):
    return dict(row, status="NOT_VERIFIABLE_FROM_FILES", requested_elements=[], evidence_ids=[],
                reason="internal calculation basis")


class TestRunStatus:
    def test_complete_run(self, fake):
        out = start()
        rid = out["run"]["id"]
        assert fake.runs[rid]["status"] == "COMPLETE"
        assert all(b["effective_status"] == "COMPLETE" for b in fake.get_check_semantic_batches(rid))
        assert fake.results[rid]["check_coverage_result"]["run_integrity"] == "COMPLETE"

    def test_failed_semantic_batch_makes_run_partial_and_keeps_usable_results(self, fake):
        out = start(model=EchoModel(raise_for=("B1",)))
        rid = out["run"]["id"]
        run = fake.runs[rid]
        assert run["status"] == "PARTIAL" and "B1 FAILED" in run["failure_reason"]
        batches = {b["batch_id"]: b for b in fake.get_check_semantic_batches(rid)}
        assert batches["B1"]["effective_status"] == "FAILED" and batches["B2"]["effective_status"] == "COMPLETE"
        by = csr.get_check_run_result(BID, rid)["result"].by_id()
        assert by[req_id("firm_experience")].status == cc.STATUS_HUMAN_REVIEW       # no verdict inferred
        assert by[req_id("pricing_form")].status == cc.STATUS_ADDRESSED              # deterministic survives
        events = [e["event_type"] for e in fake.get_check_run_events(rid)]
        assert "SEMANTIC_BATCH_FAILED" in events and events[-1] == "RUN_PARTIAL"

    def test_model_omitting_an_object_is_partial_not_complete(self, fake):
        out = start(model=EchoModel(omit=(req_id("service"),)))
        assert fake.runs[out["run"]["id"]]["status"] == "PARTIAL"

    def test_human_review_object_does_not_make_run_partial(self, fake):
        out = start(model=EchoModel(override={req_id("firm_experience"): _review}))
        res = csr.get_check_run_result(BID, out["run"]["id"])["result"]
        assert fake.runs[out["run"]["id"]]["status"] == "COMPLETE"
        assert res.by_id()[req_id("firm_experience")].status == cc.STATUS_HUMAN_REVIEW

    def test_unverifiable_object_does_not_make_run_partial(self, fake):
        out = start(model=EchoModel(override={req_id("service"): _unverifiable}))
        res = csr.get_check_run_result(BID, out["run"]["id"])["result"]
        assert fake.runs[out["run"]["id"]]["status"] == "COMPLETE"
        assert res.by_id()[req_id("service")].status == cc.STATUS_NOT_VERIFIABLE
        assert res.by_id()[req_id("portal")].status == cc.STATUS_NOT_VERIFIABLE      # portal-native, scope gate

    def test_events_reconstruct_progress_after_refresh(self, fake):
        out = start()
        rid = out["run"]["id"]
        events = [e["event_type"] for e in fake.get_check_run_events(rid)]
        assert events == ["RUN_CREATED", "RUN_STARTED", "BUYER_SCOPE_CLASSIFIED", "CANDIDATE_RETRIEVAL_COMPLETE",
                          "DETERMINISTIC_ADJUDICATION_COMPLETE", "SEMANTIC_BATCH_STARTED", "SEMANTIC_BATCH_COMPLETED",
                          "SEMANTIC_BATCH_STARTED", "SEMANTIC_BATCH_COMPLETED", "EVIDENCE_ASSURANCE_COMPLETE",
                          "RUN_COMPLETED"]
        seqs = [e["sequence"] for e in fake.get_check_run_events(rid)]
        assert seqs == list(range(1, len(seqs) + 1))
        status = csr.get_check_run_status(BID, rid)
        p = status["progress"]
        assert p["total_buyer_objects"] == 16 and p["semantic_batches_total"] == 2
        assert p["semantic_batches_complete"] == 2 and p["final_adjudications"] == 16
        assert p["excluded_non_submission"] >= 1 and p["deterministic_complete"] >= 1
        incremental = csr.get_check_run_status(BID, rid, after_sequence=9)["events"]
        assert [e["sequence"] for e in incremental] == [10, 11]

    def test_events_hold_counts_only_never_percentages_or_text(self, fake):
        out = start()
        for e in fake.get_check_run_events(out["run"]["id"]):
            blob = json.dumps(e["detail"]).lower()
            assert "percent" not in blob and "%" not in blob
            assert "acme" not in blob and "provide two" not in blob          # no bidder / buyer prose
            assert len(json.dumps(e["detail"]).encode()) <= 4000

    def test_live_state_is_truthful_mid_run(self, fake):
        seen = {}

        class Peek(EchoModel):
            def __call__(self, prompt, batch):
                if batch["batch_id"] == "B2":
                    st = csr.get_check_run_status(BID)
                    seen.update(status=st["status"], progress=st["progress"])
                return super().__call__(prompt, batch)
        start(model=Peek())
        assert seen["status"] == "RUNNING"
        assert seen["progress"]["semantic_batches_complete"] == 1 and seen["progress"]["running_batch"] == "B2"
        assert seen["progress"]["final_adjudications"] is None


# ═══════════════════════════════════════════════════════════════════════
# F. Provider accounting / truncation integrity (sections 10 / 11 / 12)
# ═══════════════════════════════════════════════════════════════════════

class TestProviderIntegrity:
    def test_provider_path_links_usage_to_the_check_run_and_keeps_stop_reason(self, fake):
        client = MockAnthropic()
        out = start(client=client)
        rid = out["run"]["id"]
        assert len(client.prompts) == 2 and fake.runs[rid]["status"] == "COMPLETE"
        batches = fake.get_check_semantic_batches(rid)
        assert {b["stop_reason"] for b in batches} == {"end_turn"}
        assert all(b["provider"] == "anthropic" and b["model"] == full_analysis.FULL_ANALYSIS_MODEL
                   and b["input_tokens"] == 1200 and b["output_tokens"] == 300 and b["parse_status"] == "COMPLETE"
                   and b["structured_output"]["adjudications"] and b["prompt_sha256"] for b in batches)
        usage = [u for u in fake.usage_events if u.get("analysis_run_id") == rid]
        assert len(usage) == 2 and {u["workflow"] for u in usage} == {"check_coverage"}
        assert {u["operation"] for u in usage} == {"check2a_b1", "check2a_b2"}
        tel = fake.runs[rid]["telemetry"]
        assert tel["live_provider_calls"] == 2 and tel["input_tokens"] == 2400
        assert tel["adjudication_source"] == csr.SOURCE_PROVIDER

    def test_reused_complete_makes_zero_provider_calls(self, fake):
        start(client=MockAnthropic())
        exploding = MockAnthropic(explode=True)
        out = start(client=exploding)
        assert out["outcome"] == csr.OUTCOME_REUSED_COMPLETE and exploding.prompts == []
        assert len([u for u in fake.usage_events]) == 2                       # still only the first run's calls

    def test_max_tokens_with_parsed_json_cannot_masquerade_as_complete(self, fake):
        client = MockAnthropic(stop_for={req_id("firm_experience"): "max_tokens"})
        out = start(client=client)
        rid = out["run"]["id"]
        b = {x["batch_id"]: x for x in fake.get_check_semantic_batches(rid)}
        assert b["B1"]["stop_reason"] == "max_tokens" and b["B1"]["parse_status"] == "COMPLETE"
        assert b["B1"]["effective_status"] == "PARTIAL" and "OUTPUT_TRUNCATED" in b["B1"]["failure_reason"]
        assert fake.runs[rid]["status"] == "PARTIAL"
        assert fake.results[rid]["check_coverage_result"]["run_integrity"] == "PARTIAL"

    def test_truncated_unrecoverable_output_fails_the_batch(self, fake):
        client = MockAnthropic(stop_for={req_id("firm_experience"): "max_tokens"},
                               cut_for=(req_id("firm_experience"),))
        out = start(client=client)
        b = {x["batch_id"]: x for x in fake.get_check_semantic_batches(out["run"]["id"])}
        assert b["B1"]["effective_status"] == "FAILED" and fake.runs[out["run"]["id"]]["status"] == "PARTIAL"
        events = [e["event_type"] for e in fake.get_check_run_events(out["run"]["id"])]
        assert "SEMANTIC_BATCH_FAILED" in events

    def test_truncated_but_partly_recovered_output_is_partial(self, fake):
        client = MockAnthropic(stop_for={req_id("firm_experience"): "max_tokens"},
                               cut_for=(req_id("firm_experience"),), cut_len=60)
        out = start(client=client)
        b = {x["batch_id"]: x for x in fake.get_check_semantic_batches(out["run"]["id"])}
        assert b["B1"]["parse_status"] == "RECOVERED_TRUNCATED" and b["B1"]["effective_status"] == "PARTIAL"
        assert fake.runs[out["run"]["id"]]["status"] == "PARTIAL"
        # the recovered verdict had no surviving evidence: CHECK-2A fail-closed made it human review
        res = csr.get_check_run_result(BID, out["run"]["id"])["result"]
        assert res.by_id()[req_id("firm_experience")].status == cc.STATUS_HUMAN_REVIEW

    def test_rpc_refuses_complete_over_a_partial_batch(self, fake):
        run = fake.start_check_run(BID, FAST_RUN, SNAPSHOT, "fp", "e")["run"]
        fake.record_check_run_event(run["id"], BID, "SEMANTIC_BATCH_COMPLETED", batch_id="B1",
                                    batch_result={"effective_status": "PARTIAL", "buyer_object_ids": [],
                                                  "candidate_evidence_ids": []})
        rows = [csr.adjudication_row(a, build_package()) for a in pure_result(make_inputs(), EchoModel()).adjudications]
        with pytest.raises(RuntimeError, match="not COMPLETE"):
            fake.finalize_check_run(run["id"], BID, "COMPLETE", adjudications=rows,
                                    result={"run_integrity": "COMPLETE", "planned_semantic_batches": 1,
                                            "object_counts": {"total": len(rows)}})
        with pytest.raises(RuntimeError, match="not COMPLETE"):
            fake.finalize_check_run(run["id"], BID, "COMPLETE", adjudications=rows,
                                    result={"run_integrity": "PARTIAL", "planned_semantic_batches": 1,
                                            "object_counts": {"total": len(rows)}})
        assert fake.runs[run["id"]]["status"] == "RUNNING" and not fake.adjudications

    @pytest.mark.parametrize("stop,parse,error,omit,expected", [
        ("end_turn", "COMPLETE", None, False, "COMPLETE"),
        (None, None, None, False, "COMPLETE"),                       # injected adjudicator: no provider metadata
        ("max_tokens", "COMPLETE", None, False, "PARTIAL"),
        ("end_turn", "RECOVERED_TRUNCATED", None, False, "PARTIAL"),
        ("max_tokens", "FAILED", None, False, "FAILED"),
        ("end_turn", "COMPLETE", "RuntimeError: boom", False, "FAILED"),
        ("end_turn", "COMPLETE", None, True, "PARTIAL"),
        ("refusal", "COMPLETE", None, False, "PARTIAL"),
    ])
    def test_effective_batch_status_table(self, stop, parse, error, omit, expected):
        ok = cc.CheckAdjudication("REQ-1", cc.OBJECT_REQUIREMENT, cc.SCOPE_SUBMISSION_RESPONSE, "", "ADDRESSED", "w",
                                  validation={"downgrades": []})
        miss = cc.CheckAdjudication("REQ-2", cc.OBJECT_REQUIREMENT, cc.SCOPE_SUBMISSION_RESPONSE, "",
                                    "HUMAN_REVIEW_REQUIRED", "w", validation={"downgrades": ["MISSING_FROM_RESPONSE"]})
        results = {"REQ-1": ok, "REQ-2": miss if omit else ok}
        status, _ = csr.effective_batch_status(objects=["REQ-1", "REQ-2"], results=results, stop_reason=stop,
                                               parse_status=parse, error=error)
        assert status == expected


# ═══════════════════════════════════════════════════════════════════════
# G. Stale runs (section 13)
# ═══════════════════════════════════════════════════════════════════════

class TestStaleRuns:
    def test_stale_run_detected_and_only_explicitly_failed(self, fake):
        run = fake.start_check_run(BID, FAST_RUN, SNAPSHOT, "fp", "e")["run"]
        fake.record_check_run_event(run["id"], BID, "RUN_STARTED", status="RUNNING")
        assert csr.get_check_run_status(BID, run["id"], now=fake.clock + timedelta(seconds=60))["stuck"]["stuck"] \
            is False
        later = fake.clock + timedelta(seconds=csr.STALE_RUN_POLICY["no_progress_seconds"] + 1)
        st = csr.get_check_run_status(BID, run["id"], now=later)
        assert st["stuck"] == {**st["stuck"], "stuck": True, "reason": "NO_PROGRESS"}
        assert fake.runs[run["id"]]["status"] == "RUNNING" and fake.start_calls == 1   # nothing automatic
        with pytest.raises(csr.RunNotStuckError):
            csr.mark_check_run_stuck(BID, run["id"], now=fake.clock)
        csr.mark_check_run_stuck(BID, run["id"], now=later)
        assert fake.runs[run["id"]]["status"] == "FAILED"
        assert fake.runs[run["id"]]["failure_detail"]["marked_stuck_by_user"] is True
        assert fake.start_calls == 1                                                  # no relaunch

    def test_max_run_age_rule_and_single_policy(self):
        from datetime import datetime, timezone
        now = datetime(2026, 9, 27, 13, 0, tzinfo=timezone.utc)
        run = {"status": "RUNNING", "created_at": (now - timedelta(hours=2)).isoformat(),
               "last_progress_at": (now - timedelta(seconds=5)).isoformat()}
        assert csr.is_check_run_stuck(run, now=now)["reason"] == "MAX_RUN_AGE_EXCEEDED"
        assert csr.is_check_run_stuck(dict(run, status="COMPLETE"), now=now)["stuck"] is False
        assert csr.STALE_RUN_POLICY["policy_version"]
        src = Path(csr.__file__).read_text(encoding="utf-8")
        assert src.count("10 * 60") == 1 and src.count("45 * 60") == 1

    def test_late_writer_cannot_resurrect_a_terminal_run(self, fake):
        run = fake.start_check_run(BID, FAST_RUN, SNAPSHOT, "fp", "e")["run"]
        fake.finalize_check_run(run["id"], BID, "FAILED", failure_reason="stuck")
        rec = csr._CheckEventRecorder(run["id"], BID)
        rec.record("SEMANTIC_BATCH_STARTED", batch_id="B1")
        assert rec.aborted is True
        with pytest.raises(RuntimeError, match="already terminal"):
            fake.finalize_check_run(run["id"], BID, "FAILED")


# ═══════════════════════════════════════════════════════════════════════
# H. Security / tenancy (section 18)
# ═══════════════════════════════════════════════════════════════════════

class TestSecurity:
    def test_cross_org_is_denied_before_any_work(self, fake, monkeypatch):
        monkeypatch.setattr(tenancy, "get_bid_for_organization",
                            lambda bid_id, org: {"id": bid_id} if org == ORG else None)
        for fn, args in ((tenancy.start_check_run_for_organization, (BID, "org-evil")),
                         (tenancy.get_check_run_status_for_organization, (BID, "org-evil")),
                         (tenancy.get_check_run_result_for_organization, (BID, "org-evil")),
                         (tenancy.mark_check_run_stuck_for_organization, (BID, "org-evil", 500))):
            with pytest.raises(tenancy.AccessDeniedError):
                fn(*args)
        assert fake.start_calls == 0 and not fake.events

    def test_cross_bid_run_ids_are_inaccessible(self, fake, monkeypatch):
        out = start()
        with pytest.raises(csr.RunNotFoundError):
            csr.get_check_run_status(OTHER_BID, out["run"]["id"])
        with pytest.raises(csr.RunNotFoundError):
            csr.get_check_run_result(OTHER_BID, out["run"]["id"])
        monkeypatch.setattr(tenancy, "get_bid_for_organization", lambda bid_id, org: {"id": bid_id})
        with pytest.raises(tenancy.AccessDeniedError):
            tenancy.get_check_run_result_for_organization(OTHER_BID, ORG, out["run"]["id"])
        with pytest.raises(RuntimeError, match="not a CHECK run of bid"):
            fake.record_check_run_event(out["run"]["id"], OTHER_BID, "RUN_STARTED")
        assert csr.get_check_run_result(OTHER_BID) is None                  # nothing leaks by default

    def test_rpcs_refuse_forged_terminal_events(self, fake):
        run = fake.start_check_run(BID, FAST_RUN, SNAPSHOT, "fp", "e")["run"]
        for et in ("RUN_COMPLETED", "RUN_CREATED"):
            with pytest.raises(RuntimeError):
                fake.record_check_run_event(run["id"], BID, et)

    def test_migration_writes_are_service_role_only(self):
        sql = MIGRATION_022
        for fn in ("start_check_run", "record_check_run_event", "finalize_check_run"):
            assert re.search(rf"revoke all on function public\.{fn}\([^)]*\) from public;", sql), fn
            assert re.search(rf"revoke all on function public\.{fn}\([^)]*\) from anon, authenticated", sql), fn
            assert re.search(rf"grant execute on function public\.{fn}\([^)]*\) to service_role", sql), fn
            assert re.search(rf"function public\.{fn}\([^;]*?security definer\s+set search_path = public", sql, re.S)

    def test_migration_rls_members_read_only_anon_nothing(self):
        sql = MIGRATION_022
        for table in ("check_semantic_batches", "check_run_events", "check_adjudications",
                      "check_adjudication_evidence"):
            assert f"alter table public.{table} enable row level security" in sql
            assert re.search(rf"on public\.{table} for select to authenticated\s+using "
                             rf"\(public\.can_access_bid\(bid_id\)\)", sql), table
            assert not re.search(rf"on public\.{table} for (insert|update|delete|all)", sql), table
        assert "to anon" not in sql.replace("from anon", "")
        assert not re.search(r"grant\s+(select|insert|update|delete|all)", sql, re.I)

    def test_migration_enforces_same_bid_same_snapshot_evidence(self):
        sql = MIGRATION_022
        assert ("foreign key (bid_id, package_snapshot_id, evidence_id)\n"
                "        references public.submission_evidence_items (bid_id, package_snapshot_id, evidence_id)") in sql
        assert sql.count("references public.analysis_runs (id, bid_id, source_package_snapshot_id)") == 3
        assert "references public.proposal_package_snapshots (id, bid_id)" in sql
        assert "unique (id, bid_id, source_package_snapshot_id)" in sql
        # COMPLETE cannot be claimed over a partial / truncated batch
        assert "effective_status <> 'COMPLETE'" in sql and "run_integrity" in sql
        assert "idx_analysis_runs_check_complete_fingerprint" in sql
        assert "pg_advisory_xact_lock(hashtext('check_run:'" in sql
        assert "before update or delete on public.check_run_events" in sql
        assert "trg_analysis_runs_guard_check_run" in sql


# ═══════════════════════════════════════════════════════════════════════
# I. Migration discipline / regressions (sections 21 / 22)
# ═══════════════════════════════════════════════════════════════════════

def _git_diff(*paths, base="b488749"):
    out = subprocess.run(["git", "diff", "--name-only", base, "--", *paths], cwd=ROOT, capture_output=True,
                         text=True)
    if out.returncode != 0:
        pytest.skip("git history unavailable")
    return out.stdout.strip()


class TestMigrationAndRegression:
    def test_022_follows_021_and_is_marked_commissioned(self):
        # CHECK-2B.1 applied 022 live; its only pre-application edit was the
        # STATUS header (see tests/test_check2b1_live_commissioning.py).
        names = sorted(p.name for p in (ROOT / "migrations").glob("*.sql"))
        assert names[-2:] == ["021_submission_evidence_registry.sql", "022_check_runs.sql"]
        assert "STATUS: APPLIED_AND_COMMISSIONED" in MIGRATION_022

    def test_migrations_001_to_021_unmodified(self):
        files = [f"migrations/{p.name}" for p in sorted((ROOT / "migrations").glob("0[0-2][0-9]_*.sql"))
                 if not p.name.startswith("022")]
        assert _git_diff(*files) == ""

    def test_migration_widens_modes_without_touching_canonical_tables(self):
        sql = MIGRATION_022
        assert "check (analysis_mode in ('FAST', 'DEEP_VERIFY', 'FULL', 'CHECK'))" in sql
        for forbidden in ("alter table public.requirements", "alter table public.bids",
                          "alter table public.submission_evidence_items", "alter table public.submission_documents",
                          "update public.requirements", "insert into public.requirements",
                          "drop index if exists public.idx_analysis_runs_one_active"):
            assert forbidden not in sql

    def test_check1_frozen_and_full_analysis_untouched(self):
        assert _git_diff("submission_package.py", "full_analysis.py", "full_analysis_service.py",
                         "canonical_procurement.py", "procurement_normalization.py", "fast_analysis.py",
                         "extractor.py") == ""

    def test_check2a_result_identical_with_and_without_the_durability_hook(self):
        inputs = make_inputs()
        plain = pure_result(inputs, EchoModel(override={req_id("firm_experience"): _partial_firm}))
        seen = []
        hooked = cc.run_check_coverage(inputs.canonical_package, inputs.submission_package,
                                       raw_requirements=inputs.raw_requirements,
                                       buyer_documents=inputs.buyer_documents,
                                       adjudicate_fn=EchoModel(override={req_id("firm_experience"): _partial_firm}),
                                       on_event=lambda et, p: seen.append(et))
        assert _norm(plain.to_dict()) == _norm(hooked.to_dict())
        assert seen == [cc.EVENT_PLAN_READY, cc.EVENT_BATCH_STARTED, cc.EVENT_BATCH_COMPLETED,
                        cc.EVENT_BATCH_STARTED, cc.EVENT_BATCH_COMPLETED]

    def test_durable_path_never_writes_canonical_layers(self, fake, monkeypatch):
        for name in ("upsert_requirement", "update_bid", "create_analysis_result", "update_analysis_run",
                     "create_submission_evidence_bundle", "get_or_create_proposal_package_snapshot",
                     "start_full_analysis_run", "finalize_full_analysis_run"):
            monkeypatch.setattr(database, name, lambda *a, _n=name, **k: pytest.fail(f"{_n} called"))
        start()


# ═══════════════════════════════════════════════════════════════════════
# R. REAL Calgary 26-1603 (bid 1360) durable replay -- zero provider calls
# ═══════════════════════════════════════════════════════════════════════

RUN34 = os.path.join(os.path.dirname(__file__), "fixtures", "calgary_26_1603_run34_raw_snapshot.json")
REPLAY = os.path.join(os.path.dirname(__file__), "fixtures", "calgary_26_1603_check2a_replay.json")
BIDDER_ZIP = os.getenv("CHECK11_BIDDER_ZIP", r"C:\Users\feras\Downloads\OneDrive_2_9-27-2026.zip")
BUYER_ZIP = os.getenv("CHECK11_BUYER_ZIP", r"C:\Users\feras\Downloads\Calgary RFP.zip")
needs_real = pytest.mark.skipif(not (os.path.exists(BUYER_ZIP) and os.path.exists(BIDDER_ZIP)
                                     and os.path.exists(REPLAY)),
                                reason="real Calgary ZIPs / live CHECK-2A replay record not on this machine")


def replay_adjudicator(record):
    """Answers each batch from the recorded, already-validated live CHECK-2A
    model output (same mapping as scripts/commission_check2a_calgary.py)."""
    calls = []

    def fn(prompt, batch):
        calls.append(batch["batch_id"])
        rec = record["batches"][batch["batch_id"]]
        assert sorted(t.obj.object_id for t in batch["tasks"]) == sorted(rec["objects"])
        e2a = {v: k for k, v in batch["alias_to_eid"].items()}
        return {"adjudications": [
            {"object_id": r["object_id"], "status": r["status"],
             "evidence_ids": [e2a.get(x, x) for x in r["evidence_ids"]],
             "requested_elements": [{"element": e["element"], "coverage": e["coverage"],
                                     "evidence_ids": [e2a.get(x, x) for x in e["evidence_ids"]]}
                                    for e in r["requested_elements"]],
             "reason": "recorded live adjudication (reason text omitted from content-free fixture)"}
            for r in rec["adjudications"]]}
    fn.calls = calls
    return fn


@pytest.fixture(scope="module")
def calgary_inputs():
    import extractor
    with open(RUN34, encoding="utf-8") as fh:
        result = fast_analysis.deserialize_fast_analysis_result(json.load(fh))
    documents = []
    with zipfile.ZipFile(BUYER_ZIP) as z:
        for n in z.namelist():
            if not n.endswith("/"):
                base = n.rsplit("/", 1)[-1]
                documents.append((base, extractor.extract_document_with_metadata(z.read(n), base)[0]))
    cpkg = full_analysis.build_canonical_package(result, bid_id=1360, analysis_run_id=34, documents=documents)
    with open(BIDDER_ZIP, "rb") as fh:
        bidder = sp.build_submission_package([(os.path.basename(BIDDER_ZIP), fh.read())], bid_id=1360,
                                             organization_id="org-calgary")
    with open(REPLAY, encoding="utf-8") as fh:
        record = json.load(fh)
    inputs = csr.CheckInputs(bid_id=1360, source_analysis_run_id=34, package_snapshot_id=9, canonical_package=cpkg,
                             raw_requirements=list(result.requirements), buyer_documents=documents,
                             submission_package=bidder)
    return inputs, record


@pytest.fixture
def calgary(calgary_inputs, monkeypatch):
    inputs, record = calgary_inputs
    f = FakeCheckDB()
    f.add_fast_run(1360, 34)
    f.add_snapshot(1360, 9, [i.evidence_id for i in inputs.submission_package.registry])
    f.install(monkeypatch.setattr)
    fn = replay_adjudicator(record)
    out = csr.start_check_run(1360, "org-calgary", inputs_loader=loader_for(inputs), adjudicate_fn=fn,
                              adjudication_source=csr.SOURCE_REPLAY, execution=csr.EXECUTION_INLINE)
    return {"fake": f, "out": out, "inputs": inputs, "record": record, "fn": fn,
            "reopened": csr.get_check_run_result(1360, out["run"]["id"])}


@needs_real
class TestRealCalgaryDurableReplay:
    def test_persisted_run_is_complete_and_counts_reconstruct_exactly(self, calgary):
        f, out, res = calgary["fake"], calgary["out"], calgary["reopened"]["result"]
        assert f.runs[out["run"]["id"]]["status"] == "COMPLETE"
        assert len(res.adjudications) == 60 and sum(a.buyer_object_type == cc.OBJECT_CRITERION
                                                     for a in res.adjudications) == 13
        counts = {k: v for k, v in res.status_counts().items() if v}
        assert counts == {"ADDRESSED": 18, "PARTIALLY_ADDRESSED": 11, "NOT_APPLICABLE": 23,
                          "NOT_VERIFIABLE_FROM_FILES": 6, "HUMAN_REVIEW_REQUIRED": 2}
        assert res.scope_counts()[cc.SCOPE_PORTAL_NATIVE] == 3
        assert calgary["fn"].calls == ["B1", "B2", "B3", "B4"]
        assert f.runs[out["run"]["id"]]["telemetry"]["live_provider_calls"] == 0

    def test_reconstruction_matches_the_validated_check2a_record(self, calgary):
        live = calgary["record"]["final"]
        for a in calgary["reopened"]["result"].adjudications:
            assert a.status == live[a.buyer_object_id]["status"], a.buyer_object_id
            assert sorted(a.evidence_ids) == sorted(live[a.buyer_object_id]["evidence_ids"]), a.buyer_object_id
            assert a.deterministic_or_model == live[a.buyer_object_id]["method"]
        assert calgary["reopened"]["result_digest_verified"] is True

    def test_reconstruction_is_semantically_identical_to_pure_check2a(self, calgary):
        inputs = calgary["inputs"]
        pure = pure_result(inputs, replay_adjudicator(calgary["record"]))
        assert _adj_dicts(calgary["reopened"]["result"]) == _adj_dicts(pure)

    def test_req46_pricing_and_appendix_e_evidence_survive(self, calgary):
        by, bidder = calgary["reopened"]["result"].by_id(), calgary["inputs"].submission_package
        role_ids = {role: {i.evidence_id for d in bidder.documents_with_roles([role], include_secondary=False)
                           for i in bidder.registry.for_document(d.submission_document_id)}
                    for role in (sp.ROLE_MULTI_PARTY_FORM, sp.ROLE_PRICING_FORM, sp.ROLE_SUBMISSION_FORM)}
        assert by["REQ-46"].status == cc.STATUS_ADDRESSED and set(by["REQ-46"].evidence_ids) & \
            role_ids[sp.ROLE_MULTI_PARTY_FORM]
        for cid in ("CRIT-price", "CRIT-pricing"):
            assert by[cid].status == cc.STATUS_ADDRESSED and set(by[cid].evidence_ids) <= role_ids[sp.ROLE_PRICING_FORM]
        for rid in ("REQ-33", "REQ-37"):
            assert by[rid].status == cc.STATUS_ADDRESSED and \
                set(by[rid].evidence_ids) <= role_ids[sp.ROLE_SUBMISSION_FORM]

    def test_scope_outcomes_preserved(self, calgary):
        res = calgary["reopened"]["result"]
        for a in res.adjudications:
            if a.assurance_scope == cc.SCOPE_PORTAL_NATIVE:
                assert a.status == cc.STATUS_NOT_VERIFIABLE
            if a.assurance_scope in cc.EXCLUDED_SCOPES:
                assert a.status == cc.STATUS_NOT_APPLICABLE and not a.missing_elements
        assert sum(a.status == cc.STATUS_HUMAN_REVIEW for a in res.adjudications) == 2
        assert all(a.status != cc.STATUS_NOT_ADDRESSED for a in res.adjudications)

    def test_every_cited_evidence_id_is_db_linked_to_snapshot_9(self, calgary):
        f = calgary["fake"]
        registry = {i.evidence_id for i in calgary["inputs"].submission_package.registry}
        links = [l for l in f.evidence_links if l["run_id"] == calgary["out"]["run"]["id"]]
        assert links and all(l["evidence_id"] in registry and l["package_snapshot_id"] == 9 for l in links)

    def test_identical_inputs_reuse_with_zero_calls(self, calgary):
        inputs, record = calgary["inputs"], calgary["record"]
        fn = replay_adjudicator(record)
        again = csr.start_check_run(1360, "org-calgary", inputs_loader=loader_for(inputs), adjudicate_fn=fn,
                                    execution=csr.EXECUTION_INLINE)
        assert again["outcome"] == csr.OUTCOME_REUSED_COMPLETE and fn.calls == []
        assert again["run"]["id"] == calgary["out"]["run"]["id"]
        assert _adj_dicts(again["result"]["result"]) == _adj_dicts(calgary["reopened"]["result"])

    def test_req41_known_model_imperfection_is_preserved_not_overridden(self, calgary):
        """Regression fixture for the disclosed CHECK-2A residual: the model
        marked REQ-41's 'three (3) examples from the past five (5) years'
        element PARTIAL although the examples are recent. CHECK-2B persists
        the adjudication exactly as validated -- no special-case override."""
        a = calgary["reopened"]["result"].by_id()["REQ-41"]
        assert a.status == cc.STATUS_PARTIALLY_ADDRESSED and a.deterministic_or_model == cc.METHOD_MODEL
        el = next(e for e in a.missing_elements if e["element"].startswith("three (3) examples from the past five"))
        assert el["coverage"] == cc.ELEMENT_PARTIAL and el["evidence_ids"]
        src = Path(csr.__file__).read_text(encoding="utf-8") + Path(cc.__file__).read_text(encoding="utf-8")
        assert "REQ-41" not in src and "past five" not in src
