"""
CHECK-2B.1: live durable-run commissioning -- the deterministic contract tests
that accompany it (ZERO provider calls, no live database).

Covers what the live commissioning added or proved:
  * migration 022's SQL is byte-identical to the CHECK-2B contract the tests
    were written against; only its STATUS header comment changed before first
    application (it is immutable from then on);
  * the REAL schema writes several adjudication fields through `->>` into TEXT
    columns -- every such payload field must be str/None so a real round trip
    is lossless (fake_db keeps JSON types, so it could not catch this);
  * replay provenance is recorded as SOURCE adjudication provenance, never as
    calls executed by the durable run (section 7);
  * the offline Calgary durable replay reproduces EXACTLY the fingerprint and
    result digest persisted live as CHECK run 37.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import check_coverage as cc  # noqa: E402
import check_run_service as csr  # noqa: E402
from test_check2b_durable_runs import (  # noqa: E402,F401  (fixtures re-registered here)
    BID, EchoModel, _no_live_provider, calgary, calgary_inputs, fake, make_inputs, needs_real, start,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "migrations" / "022_check_runs.sql"
LIVE = json.loads((ROOT / "tests" / "fixtures" / "calgary_26_1603_check2b1_live_run.json").read_text(encoding="utf-8"))

#: check_adjudications columns migration 022's finalize_check_run fills with
#: `v_adj->>'<key>'` (TEXT). A non-string JSON value would come back as its
#: text rendering -- a silent type change on reconstruction.
TEXT_VIA_ARROW = ("buyer_object_id", "buyer_object_type", "assurance_scope", "scope_basis", "status",
                  "buyer_expectation", "buyer_label", "buyer_category", "evidence_summary",
                  "ambiguity_or_review_reason", "buyer_weight", "buyer_threshold", "deterministic_or_model",
                  "batch_id", "applicability", "applicability_condition")


def _pg_text(value):
    """Postgres `jsonb ->> key` semantics: JSON null -> SQL NULL, a string ->
    itself, anything else -> its JSON text."""
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value)


def emulate_real_schema_row(row: dict) -> dict:
    """What check_adjudications returns for one finalize payload element."""
    out = json.loads(json.dumps(row, default=str))          # jsonb columns
    for k in TEXT_VIA_ARROW:
        out[k] = _pg_text(row.get(k))
    out["adjudication_method"] = out.pop("deterministic_or_model")
    for k, default in (("scope_basis", ""), ("evidence_summary", "")):
        out[k] = out[k] if out[k] is not None else default
    return out


def _sql_body(text: str) -> str:
    """Migration SQL without `--` comment lines (the executable content)."""
    return "\n".join(line for line in text.replace("\r\n", "\n").split("\n") if not line.lstrip().startswith("--"))


class TestMigration022Commissioned:
    def test_status_header_records_commissioning(self):
        sql = MIGRATION.read_text(encoding="utf-8")
        assert "STATUS: APPLIED_AND_COMMISSIONED by CHECK-2B.1" in sql
        assert "CREATED_NOT_APPLIED" not in sql

    def test_executable_sql_identical_to_check2b_contract(self):
        out = subprocess.run(["git", "show", "90945fd:migrations/022_check_runs.sql"], cwd=ROOT,
                             capture_output=True, text=True, encoding="utf-8")
        if out.returncode != 0:
            pytest.skip("git history unavailable")
        assert _sql_body(out.stdout) == _sql_body(MIGRATION.read_text(encoding="utf-8"))

    def test_live_ledger_record_is_022(self):
        assert LIVE["migration_ledger"] == {"version": "20260927153417", "name": "check_runs"}


class TestRealSchemaRoundTrip:
    def test_every_arrow_text_field_is_str_or_none(self, fake):
        inputs = make_inputs()
        start(inputs)
        for a in csr.get_check_run_result(BID)["result"].adjudications:
            row = csr.adjudication_row(a, inputs.submission_package)
            bad = {k: row[k] for k in TEXT_VIA_ARROW if row[k] is not None and not isinstance(row[k], str)}
            assert not bad, (a.buyer_object_id, bad)

    def test_reconstruction_through_real_schema_semantics_is_lossless(self, fake):
        inputs = make_inputs()
        out = start(inputs)
        stored = csr.get_check_run_result(BID, out["run"]["id"])
        rows = [emulate_real_schema_row(csr.adjudication_row(a, inputs.submission_package))
                for a in stored["result"].adjudications]
        rebuilt = csr.reconstruct_result(stored["result_payload"], rows)
        assert cc.result_digest(rebuilt) == stored["result_payload"]["result_digest"]

    def test_emulation_would_catch_a_non_string_weight(self):
        a = cc.CheckAdjudication(buyer_object_id="CRIT-x", buyer_object_type=cc.OBJECT_CRITERION,
                                 assurance_scope=cc.SCOPE_EVALUATION_RESPONSE, scope_basis="", status=cc.STATUS_HUMAN_REVIEW,
                                 buyer_expectation="x", buyer_weight=25)
        row = emulate_real_schema_row(a.to_dict())
        assert csr.adjudication_from_row(row).buyer_weight == "25" != a.buyer_weight


class TestReplayProvenance:
    PROV = {"source_adjudication": "CHECK-2A live acceptance", "source_recorded_provider_calls": 4}

    def test_replay_records_source_provenance_not_new_calls(self, fake):
        out = start(adjudication_source=csr.SOURCE_REPLAY, adjudication_provenance=self.PROV)
        run = fake.runs[out["run"]["id"]]
        payload = fake.results[out["run"]["id"]]["check_coverage_result"]
        for block in (payload, run["telemetry"]):
            p = block["source_adjudication_provenance"]
            assert p["applies_to"] == "SOURCE_ADJUDICATION_NOT_THIS_RUN"
            assert p["source_recorded_provider_calls"] == 4
            assert p["adjudication_source"] == csr.SOURCE_REPLAY
            assert block["live_provider_calls"] == 0
        assert run["status"] == "COMPLETE" and not fake.usage_events
        assert all(b["provider"] is None and b["input_tokens"] is None for b in fake.batches)

    def test_no_provenance_block_without_provenance(self, fake):
        out = start()
        assert "source_adjudication_provenance" not in fake.results[out["run"]["id"]]["check_coverage_result"]
        assert "source_adjudication_provenance" not in fake.runs[out["run"]["id"]]["telemetry"]

    def test_provenance_never_changes_fingerprint_or_result(self, fake):
        a = start(make_inputs(), adjudication_provenance=self.PROV)
        digest_a = fake.results[a["run"]["id"]]["check_coverage_result"]["result_digest"]
        assert a["input_fingerprint"] == csr.compute_check_fingerprint(make_inputs())
        again = start(make_inputs(), adjudication_provenance=None)
        assert again["outcome"] == csr.OUTCOME_REUSED_COMPLETE
        assert csr.get_check_run_result(BID, a["run"]["id"])["result_payload"]["result_digest"] == digest_a


@needs_real
class TestOfflineReplayMatchesLiveRun37:
    def test_fingerprint_and_result_digest_equal_the_live_durable_run(self, calgary):
        out, bundle = calgary["out"], calgary["reopened"]
        assert out["input_fingerprint"] == LIVE["input_fingerprint"]
        assert bundle["result_payload"]["result_digest"] == LIVE["result_digest"]
        assert cc.result_digest(bundle["result"]) == LIVE["result_digest"]
        counts = {k: v for k, v in bundle["result"].status_counts().items() if v}
        assert counts == LIVE["status_counts"]

    def test_persisted_shape_matches_live_row_counts(self, calgary):
        f, run_id = calgary["fake"], calgary["out"]["run"]["id"]
        assert [e["event_type"] for e in f.get_check_run_events(run_id)] == LIVE["event_types"]
        links = [l for l in f.evidence_links if l["run_id"] == run_id]
        assert len(links) == LIVE["persisted_rows"]["evidence_links"]
        kinds = {k: sum(l["reference_kind"] == k for l in links) for k in ("VERDICT", "ELEMENT")}
        assert kinds == LIVE["persisted_rows"]["evidence_links_by_kind"]
        assert len({l["evidence_id"] for l in links}) == LIVE["distinct_cited_evidence_ids"]
        assert len(f.get_check_semantic_batches(run_id)) == LIVE["persisted_rows"]["semantic_batches"]

    def test_real_calgary_text_fields_are_str_or_none(self, calgary):
        pkg = calgary["inputs"].submission_package
        for a in calgary["reopened"]["result"].adjudications:
            row = csr.adjudication_row(a, pkg)
            assert all(row[k] is None or isinstance(row[k], str) for k in TEXT_VIA_ARROW), a.buyer_object_id


def test_commissioning_script_poisons_everything_but_the_three_check_rpcs():
    src = (ROOT / "scripts" / "commission_check2b1_calgary_live.py").read_text(encoding="utf-8")
    assert re.search(r'ALLOWED_WRITES = \("start_check_run", "record_check_run_event", "finalize_check_run"\)', src)
    assert "_poison_provider()" in src and "_poison_db_writes()" in src
    assert "fingerprint mismatch; reuse start not attempted" in src
