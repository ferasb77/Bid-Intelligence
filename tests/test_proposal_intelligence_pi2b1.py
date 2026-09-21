"""
tests/test_proposal_intelligence_pi2b1.py

Proposal Intelligence PI-2B1: whole-package claims, contradictions, and
consistency. ZERO live provider calls anywhere in this file -- every
model-shaped response is a hand-built dict/JSON string, and every real
call site (analyst._call) is mocked or never reached. Mirrors the
existing style of tests/test_proposal_intelligence_pi2a.py.
"""
import json

import analyst
import proposal_intelligence as pi


def _chunk(index=0, total=1, heading="Section", start=0, end=10,
           source_file_id="f1", source_filename="Tech.pdf"):
    return {
        "index": index, "total": total, "heading": heading, "start": start, "end": end,
        "source_file_id": source_file_id, "source_filename": source_filename,
    }


def _claim(claim_type="STAFFING", req_id="R1", subject="coaches", statement="We have 8 coaches",
           value="8", unit="people", confidence="High"):
    return {"claim_type": claim_type, "req_id": req_id, "subject": subject, "statement": statement,
            "value": value, "unit": unit, "confidence": confidence}


# ── LOCAL CLAIM LEDGER (per-chunk schema, provenance, aggregation) ────────

class TestChunkClaimValidation:

    def test_valid_claim_survives_with_source_ref(self):
        parsed = {"requirement_assertions": [], "chunk_findings": [],
                 "proposal_claims": [_claim()]}
        out = analyst._attach_chunk_provenance(parsed, _chunk(), "label")
        assert len(out["proposal_claims"]) == 1
        c = out["proposal_claims"][0]
        assert c["_source_ref"]["file_id"] == "f1"
        assert c["claim_type"] == "STAFFING"

    def test_invalid_claim_type_falls_back_to_other(self):
        parsed = {"requirement_assertions": [], "chunk_findings": [],
                 "proposal_claims": [_claim(claim_type="NOT_A_TYPE")]}
        out = analyst._attach_chunk_provenance(parsed, _chunk(), "label")
        assert out["proposal_claims"][0]["claim_type"] == "OTHER"

    def test_empty_statement_claim_is_discarded_not_whole_chunk(self):
        parsed = {"requirement_assertions": [{"req_id": "R1", "coverage": "Fully Addressed", "evidence": "x"}],
                 "chunk_findings": [], "proposal_claims": [_claim(statement=""), _claim()]}
        out = analyst._attach_chunk_provenance(parsed, _chunk(), "label")
        assert len(out["proposal_claims"]) == 1
        # the rest of the chunk response is untouched
        assert len(out["requirement_assertions"]) == 1

    def test_non_dict_claim_entry_is_dropped(self):
        parsed = {"requirement_assertions": [], "chunk_findings": [],
                 "proposal_claims": ["not-a-dict", _claim()]}
        out = analyst._attach_chunk_provenance(parsed, _chunk(), "label")
        assert len(out["proposal_claims"]) == 1

    def test_model_cannot_supply_its_own_source_ref(self):
        parsed = {"requirement_assertions": [], "chunk_findings": [],
                 "proposal_claims": [dict(_claim(), _source_ref={"file_id": "FAKE"})]}
        out = analyst._attach_chunk_provenance(parsed, _chunk(source_file_id="real-f1"), "label")
        assert out["proposal_claims"][0]["_source_ref"]["file_id"] == "real-f1"


class TestClaimAggregation:

    def test_deterministic_dedup_preserves_all_provenance(self):
        cr1 = {"proposal_claims": [dict(_claim(), _source_ref={"file_id": "f1", "section": "A"})]}
        cr2 = {"proposal_claims": [dict(_claim(), _source_ref={"file_id": "f2", "section": "B"})]}
        ledger = analyst._aggregate_proposal_claims([cr1, cr2])
        assert len(ledger) == 1
        assert len(ledger[0]["proposal_source_refs"]) == 2

    def test_conflicting_claims_stay_separate(self):
        cr1 = {"proposal_claims": [dict(_claim(value="8"), _source_ref={"file_id": "f1"})]}
        cr2 = {"proposal_claims": [dict(_claim(value="10"), _source_ref={"file_id": "f1"})]}
        ledger = analyst._aggregate_proposal_claims([cr1, cr2])
        assert len(ledger) == 2
        values = {c["value"] for c in ledger}
        assert values == {"8", "10"}

    def test_stable_first_seen_order(self):
        cr1 = {"proposal_claims": [dict(_claim(subject="A"), _source_ref={"file_id": "f1"}),
                                   dict(_claim(subject="B"), _source_ref={"file_id": "f1"})]}
        ledger = analyst._aggregate_proposal_claims([cr1])
        assert [c["subject"] for c in ledger] == ["A", "B"]

    def test_same_inputs_produce_identical_ledger(self):
        cr1 = {"proposal_claims": [dict(_claim(), _source_ref={"file_id": "f1"})]}
        l1 = analyst._aggregate_proposal_claims([cr1])
        l2 = analyst._aggregate_proposal_claims([cr1])
        assert l1 == l2


# ── PACKAGE LEDGER / DIGEST / BUDGET ───────────────────────────────────────

def _alignment_result(claims=None, coverage_complete=True, req_coverage=None, findings=None, observations=None):
    return {
        "status": "complete" if coverage_complete else "incomplete",
        "proposal_claim_ledger": claims or [],
        "requirement_coverage": req_coverage or [],
        "findings": findings or [],
        "proposal_observations": observations or [],
        "coverage_metadata": {"coverage_complete": coverage_complete},
    }


class TestPackageLedgerDeterminism:

    def test_same_inputs_same_digest(self):
        result = _alignment_result(claims=[dict(_claim(), proposal_source_refs=[{"file_id": "f1"}])])
        ledger1 = analyst._build_package_intelligence_ledger(result, [])
        ledger2 = analyst._build_package_intelligence_ledger(result, [])
        assert analyst.package_ledger_digest(ledger1) == analyst.package_ledger_digest(ledger2)

    def test_changed_claim_changes_digest(self):
        r1 = _alignment_result(claims=[dict(_claim(value="8"), proposal_source_refs=[{"file_id": "f1"}])])
        r2 = _alignment_result(claims=[dict(_claim(value="10"), proposal_source_refs=[{"file_id": "f1"}])])
        d1 = analyst.package_ledger_digest(analyst._build_package_intelligence_ledger(r1, []))
        d2 = analyst.package_ledger_digest(analyst._build_package_intelligence_ledger(r2, []))
        assert d1 != d2

    def test_source_registry_has_no_duplicate_refs(self):
        ref = {"file_id": "f1", "section": "A"}
        claims = [dict(_claim(subject="X"), proposal_source_refs=[ref]),
                  dict(_claim(subject="Y"), proposal_source_refs=[ref])]
        result = _alignment_result(claims=claims)
        ledger = analyst._build_package_intelligence_ledger(result, [])
        assert len(ledger["source_registry"]) == 1
        assert ledger["claims"][0]["source_ids"] == ledger["claims"][1]["source_ids"]

    def test_claim_ids_are_stable_and_sequential(self):
        claims = [dict(_claim(subject="A"), proposal_source_refs=[]),
                  dict(_claim(subject="B"), proposal_source_refs=[])]
        result = _alignment_result(claims=claims)
        ledger = analyst._build_package_intelligence_ledger(result, [])
        assert [c["claim_id"] for c in ledger["claims"]] == ["C1", "C2"]


class TestLedgerByteBudget:

    def test_under_budget_keeps_every_claim(self):
        claims = [dict(_claim(subject=f"S{i}"), proposal_source_refs=[]) for i in range(5)]
        result = _alignment_result(claims=claims)
        ledger = analyst._build_package_intelligence_ledger(result, [])
        assert len(ledger["claims"]) == 5

    def test_over_budget_drops_lowest_priority_first(self):
        big_statement = "x" * 2000
        many_claims = []
        # low-priority (OTHER, no req_id, Low confidence) claims first
        for i in range(60):
            many_claims.append(dict(
                _claim(claim_type="OTHER", req_id=None, subject=f"low{i}",
                       statement=big_statement, confidence="Low"),
                proposal_source_refs=[],
            ))
        # one high-priority quantitative claim tied to a mandatory requirement
        many_claims.append(dict(
            _claim(claim_type="STAFFING", req_id="R1", subject="priority-claim",
                   statement="8 coaches", confidence="High"),
            proposal_source_refs=[],
        ))
        result = _alignment_result(claims=many_claims)
        requirements = [{"req_id": "R1", "is_mandatory": True}]
        ledger = analyst._build_package_intelligence_ledger(result, requirements)
        kept_subjects = {c["subject"] for c in ledger["claims"]}
        assert "priority-claim" in kept_subjects
        assert len(ledger["claims"]) < len(many_claims)


# ── PACKAGE REASONING VALIDATION / RECONCILIATION ──────────────────────────

def _ledger_with_two_claims(value_a="8", value_b="10", req_id="R1"):
    claims = [
        dict(_claim(value=value_a, req_id=req_id), proposal_source_refs=[{"file_id": "f1"}]),
        dict(_claim(value=value_b, req_id=req_id), proposal_source_refs=[{"file_id": "f2"}]),
    ]
    result = _alignment_result(claims=claims, coverage_complete=True)
    ledger = analyst._build_package_intelligence_ledger(result, [{"req_id": req_id}])
    return ledger


class TestPackageFindingReconciliation:

    def test_valid_contradiction_is_accepted(self):
        ledger = _ledger_with_two_claims()
        raw = [{"finding_type": "CONTRADICTION", "severity": "High", "req_id": "R1",
               "title": "Conflicting staffing counts", "explanation": "8 vs 10",
               "recommended_action": "Reconcile staffing numbers",
               "supporting_claim_ids": ["C1", "C2"], "supporting_source_ids": ["P1", "P2"]}]
        accepted, rejected = analyst._reconcile_package_findings(raw, ledger, [{"req_id": "R1"}])
        assert rejected == 0
        assert len(accepted) == 1
        assert accepted[0]["proposal_source_refs"] == [{"file_id": "f1"}, {"file_id": "f2"}]

    def test_unknown_claim_id_rejected(self):
        ledger = _ledger_with_two_claims()
        raw = [{"finding_type": "CONTRADICTION", "severity": "High", "req_id": "R1",
               "title": "t", "explanation": "e", "recommended_action": "a",
               "supporting_claim_ids": ["C99"], "supporting_source_ids": []}]
        accepted, rejected = analyst._reconcile_package_findings(raw, ledger, [{"req_id": "R1"}])
        assert accepted == [] and rejected == 1

    def test_unknown_source_id_rejected(self):
        ledger = _ledger_with_two_claims()
        raw = [{"finding_type": "CONTRADICTION", "severity": "High", "req_id": "R1",
               "title": "t", "explanation": "e", "recommended_action": "a",
               "supporting_claim_ids": ["C1"], "supporting_source_ids": ["P99"]}]
        accepted, rejected = analyst._reconcile_package_findings(raw, ledger, [{"req_id": "R1"}])
        assert accepted == [] and rejected == 1

    def test_unknown_req_id_never_fuzzy_resolves(self):
        ledger = _ledger_with_two_claims()
        raw = [{"finding_type": "CONTRADICTION", "severity": "High", "req_id": "R-DOES-NOT-EXIST",
               "title": "t", "explanation": "e", "recommended_action": "a",
               "supporting_claim_ids": ["C1"], "supporting_source_ids": []}]
        accepted, rejected = analyst._reconcile_package_findings(raw, ledger, [{"req_id": "R1"}])
        assert accepted == [] and rejected == 1

    def test_invalid_finding_type_rejected(self):
        ledger = _ledger_with_two_claims()
        raw = [{"finding_type": "MADE_UP_TYPE", "severity": "High", "req_id": "R1",
               "title": "t", "explanation": "e", "recommended_action": "a",
               "supporting_claim_ids": ["C1"], "supporting_source_ids": []}]
        accepted, rejected = analyst._reconcile_package_findings(raw, ledger, [{"req_id": "R1"}])
        assert accepted == [] and rejected == 1

    def test_one_malformed_finding_does_not_fail_the_rest(self):
        ledger = _ledger_with_two_claims()
        raw = [
            {"finding_type": "BOGUS", "severity": "High", "req_id": "R1", "title": "bad",
             "supporting_claim_ids": ["C1"], "supporting_source_ids": []},
            {"finding_type": "CONTRADICTION", "severity": "High", "req_id": "R1", "title": "good",
             "explanation": "e", "recommended_action": "a",
             "supporting_claim_ids": ["C1", "C2"], "supporting_source_ids": []},
        ]
        accepted, rejected = analyst._reconcile_package_findings(raw, ledger, [{"req_id": "R1"}])
        assert rejected == 1 and len(accepted) == 1 and accepted[0]["title"] == "good"

    def test_silence_alone_is_not_treated_as_contradiction(self):
        # A ledger with only ONE claim (no conflicting second claim) --
        # a model that hallucinates a contradiction citing a nonexistent
        # second claim id must be rejected, never accepted on "absence".
        claims = [dict(_claim(), proposal_source_refs=[{"file_id": "f1"}])]
        result = _alignment_result(claims=claims)
        ledger = analyst._build_package_intelligence_ledger(result, [{"req_id": "R1"}])
        raw = [{"finding_type": "CONTRADICTION", "severity": "High", "req_id": "R1",
               "title": "t", "explanation": "e", "recommended_action": "a",
               "supporting_claim_ids": ["C1", "C2"], "supporting_source_ids": []}]
        accepted, rejected = analyst._reconcile_package_findings(raw, ledger, [{"req_id": "R1"}])
        assert accepted == [] and rejected == 1


class TestUnsupportedClaimIncompleteCoverage:

    def test_complete_coverage_permits_validated_unsupported_claim(self):
        claims = [dict(_claim(), proposal_source_refs=[{"file_id": "f1"}])]
        result = _alignment_result(claims=claims, coverage_complete=True)
        ledger = analyst._build_package_intelligence_ledger(result, [{"req_id": "R1"}])
        raw = [{"finding_type": "UNSUPPORTED_CLAIM", "severity": "Medium", "req_id": "R1",
               "title": "t", "explanation": "e", "recommended_action": "a",
               "supporting_claim_ids": ["C1"], "supporting_source_ids": ["P1"]}]
        accepted, rejected = analyst._reconcile_package_findings(raw, ledger, [{"req_id": "R1"}])
        assert rejected == 0 and len(accepted) == 1

    def test_incomplete_coverage_structurally_rejects_unsupported_claim(self):
        claims = [dict(_claim(), proposal_source_refs=[{"file_id": "f1"}])]
        result = _alignment_result(claims=claims, coverage_complete=False)
        ledger = analyst._build_package_intelligence_ledger(result, [{"req_id": "R1"}])
        assert ledger["coverage_complete"] is False
        raw = [{"finding_type": "UNSUPPORTED_CLAIM", "severity": "Medium", "req_id": "R1",
               "title": "t", "explanation": "e", "recommended_action": "a",
               "supporting_claim_ids": ["C1"], "supporting_source_ids": ["P1"]}]
        accepted, rejected = analyst._reconcile_package_findings(raw, ledger, [{"req_id": "R1"}])
        # structurally rejected regardless of what the (mocked) model returned
        assert accepted == [] and rejected == 1

    def test_incomplete_coverage_still_allows_grounded_inconsistency(self):
        claims = [dict(_claim(subject="X"), proposal_source_refs=[{"file_id": "f1"}]),
                  dict(_claim(subject="Y", statement="weekly coaching"), proposal_source_refs=[{"file_id": "f2"}])]
        result = _alignment_result(claims=claims, coverage_complete=False)
        ledger = analyst._build_package_intelligence_ledger(result, [{"req_id": "R1"}])
        raw = [{"finding_type": "INTERNAL_INCONSISTENCY", "severity": "Medium", "req_id": "R1",
               "title": "t", "explanation": "e", "recommended_action": "a",
               "supporting_claim_ids": ["C1", "C2"], "supporting_source_ids": []}]
        accepted, rejected = analyst._reconcile_package_findings(raw, ledger, [{"req_id": "R1"}])
        assert rejected == 0 and len(accepted) == 1


# ── analyze_proposal_package_intelligence (the one new call site) ─────────

class TestAnalyzePackageIntelligenceCallCount:

    def test_exactly_one_call_site_no_per_requirement_calls(self):
        calls = []

        def fake_call(system, user, max_tokens=2500, **kwargs):
            calls.append(kwargs.get("operation"))
            return json.dumps({"package_findings": []})

        claims = [dict(_claim(), proposal_source_refs=[{"file_id": "f1"}])]
        result = _alignment_result(claims=claims)
        orig = analyst._call
        analyst._call = fake_call
        try:
            out = analyst.analyze_proposal_package_intelligence(result, [{"req_id": "R1"}], {"title": "Bid"})
        finally:
            analyst._call = orig
        assert calls == ["package_reasoning"]
        assert out["package_reasoning_status"] == "OK"

    def test_empty_ledger_is_skipped_with_zero_calls(self):
        calls = []

        def fake_call(system, user, max_tokens=2500, **kwargs):
            calls.append(1)
            return json.dumps({"package_findings": []})

        result = _alignment_result(claims=[], req_coverage=[])
        orig = analyst._call
        analyst._call = fake_call
        try:
            out = analyst.analyze_proposal_package_intelligence(result, [], {"title": "Bid"})
        finally:
            analyst._call = orig
        assert calls == []
        assert out["package_reasoning_status"] == "SKIPPED_EMPTY_LEDGER"


class TestPackageCallFailureBehavior:

    def test_provider_failure_preserves_local_result_zero_fabricated_findings(self):
        def failing_call(system, user, max_tokens=2500, **kwargs):
            raise RuntimeError("simulated provider failure")

        claims = [dict(_claim(), proposal_source_refs=[{"file_id": "f1"}])]
        result = _alignment_result(claims=claims)
        orig = analyst._call
        analyst._call = failing_call
        try:
            out = analyst.analyze_proposal_package_intelligence(result, [{"req_id": "R1"}], {"title": "Bid"})
        finally:
            analyst._call = orig
        assert out["package_reasoning_status"] == "FAILED"
        assert out["package_findings"] == []
        # local alignment_result is untouched by this function -- it never
        # mutates its input
        assert result["proposal_claim_ledger"] == claims


# ── PERSISTENCE MAPPING (proposal_intelligence.adapt_package_findings) ────

class TestPackageFindingPersistenceMapping:

    def _package_result(self):
        return {
            "package_findings": [{
                "finding_type": "CONTRADICTION", "severity": "High", "req_id": "R1",
                "title": "Conflicting staffing counts", "explanation": "8 vs 10",
                "recommended_action": "Reconcile", "supporting_claim_ids": ["C1", "C2"],
                "supporting_source_ids": ["P1"],
                "proposal_source_refs": [{"file_id": "f1", "filename": "Tech.pdf"}],
            }],
            "package_reasoning_status": "OK", "package_ledger_digest": "abc123", "rejected_count": 0,
        }

    def test_maps_into_existing_findings_table_payload_shape(self):
        requirements = [{"req_id": "R1", "id": 42, "source_refs": [{"clause": "3.1"}]}]
        rows = pi.adapt_package_findings(self._package_result(), requirements)
        assert len(rows) == 1
        row = rows[0]
        assert row["finding_type"] == "CONTRADICTION"
        assert row["related_requirement_id"] == 42
        assert row["related_req_id"] == "R1"
        assert row["proposal_source_refs"] == [{"file_id": "f1", "filename": "Tech.pdf"}]
        assert row["procurement_source_refs"] == [{"clause": "3.1"}]
        assert row["payload"]["scope"] == "package"
        assert row["payload"]["package_ledger_digest"] == "abc123"

    def test_unresolvable_req_id_leaves_related_requirement_id_none(self):
        rows = pi.adapt_package_findings(self._package_result(), [{"req_id": "OTHER", "id": 1}])
        assert rows[0]["related_requirement_id"] is None

    def test_empty_package_findings_yields_no_rows(self):
        result = {"package_findings": [], "package_reasoning_status": "FAILED"}
        assert pi.adapt_package_findings(result, []) == []


class TestScopeSeparationOnReload:

    def test_local_findings_tagged_local_package_findings_tagged_package(self):
        alignment_result = {
            "status": "complete", "coverage_metadata": {}, "findings": [],
            "mandatory_failures": [], "proposal_observations": [],
        }
        local_rows = pi.adapt_findings(alignment_result, [])
        assert local_rows == []  # nothing to adapt, but confirms no crash

        package_result = {
            "package_findings": [{
                "finding_type": "UNSUPPORTED_CLAIM", "severity": "Medium", "req_id": None,
                "title": "t", "explanation": "e", "recommended_action": "a",
                "supporting_claim_ids": ["C1"], "supporting_source_ids": [],
                "proposal_source_refs": [],
            }],
            "package_ledger_digest": "d1",
        }
        package_rows = pi.adapt_package_findings(package_result, [])
        assert package_rows[0]["payload"]["scope"] == "package"

    def test_reconstruct_legacy_align_result_separates_package_findings(self):
        run = {"status": "COMPLETE", "legacy_result": {}, "coverage_metadata": {}}
        findings = [
            {"finding_type": "CONTRADICTION", "req_id": "R1",
             "payload": {"finding_type": "CONTRADICTION", "title": "pkg finding", "scope": "package"}},
            {"finding_type": "CONTRADICTION", "req_id": "R2",
             "payload": {"finding_type": "CONTRADICTION", "title": "local finding", "scope": "local"}},
        ]
        result = pi.reconstruct_legacy_align_result(run, [], findings)
        assert len(result["package_findings"]) == 1
        assert result["package_findings"][0]["title"] == "pkg finding"
        assert all(f["title"] != "pkg finding" for f in result["findings"])

    def test_historical_run_with_no_package_findings_renders_safely(self):
        run = {"status": "COMPLETE", "legacy_result": {}, "coverage_metadata": {}}
        result = pi.reconstruct_legacy_align_result(run, [], [])
        assert result["package_findings"] == []


# ── ANALYSIS VERSION ────────────────────────────────────────────────────

class TestAnalysisVersionBump:

    def test_current_version_is_v3(self):
        assert pi.PROPOSAL_INTELLIGENCE_ANALYSIS_VERSION == "proposal-intelligence-v3"

    def test_v2_run_reports_analysis_version_changed(self):
        run = {"based_on_procurement_revision": 1, "proposal_package_snapshot_id": 5,
              "analysis_version": "proposal-intelligence-v2"}
        reasons = pi.staleness_reasons(
            run, current_procurement_revision=1, current_package_snapshot_id=5)
        assert pi.STALE_ANALYSIS_VERSION_CHANGED in reasons
        assert not pi.is_current(run, current_procurement_revision=1, current_package_snapshot_id=5)

    def test_v3_run_is_current_on_version(self):
        run = {"based_on_procurement_revision": 1, "proposal_package_snapshot_id": 5,
              "analysis_version": pi.PROPOSAL_INTELLIGENCE_ANALYSIS_VERSION}
        reasons = pi.staleness_reasons(
            run, current_procurement_revision=1, current_package_snapshot_id=5)
        assert pi.STALE_ANALYSIS_VERSION_CHANGED not in reasons


# ── COMMISSIONING HARDENING: 6 targeted regression tests ──────────────────
# ZERO live provider calls -- analyst._call / config.execute_messages_create
# are always mocked here, mirroring the rest of this file's style.

class TestPackageReasoningSingleAttempt:
    """Fix #1: package reasoning is exactly ONE provider attempt -- no
    automatic retry -- unlike the existing chunk/synthesis calls."""

    def test_failure_makes_exactly_one_call_not_two(self):
        call_count = {"n": 0}

        def failing_call(system, user, max_tokens=2500, **kwargs):
            call_count["n"] += 1
            raise RuntimeError("simulated provider failure")

        orig = analyst._call
        analyst._call = failing_call
        try:
            parsed, failure_category = analyst._call_package_reasoning("prompt", bid_id=1)
        finally:
            analyst._call = orig
        assert call_count["n"] == 1
        assert parsed is None
        assert failure_category == analyst._PACKAGE_FAILURE_API_ERROR

    def test_end_to_end_failure_preserves_local_result_after_one_attempt(self):
        call_count = {"n": 0}

        def failing_call(system, user, max_tokens=2500, **kwargs):
            call_count["n"] += 1
            raise RuntimeError("simulated provider failure")

        claims = [dict(_claim(), proposal_source_refs=[{"file_id": "f1"}])]
        result = _alignment_result(claims=claims)
        orig = analyst._call
        analyst._call = failing_call
        try:
            out = analyst.analyze_proposal_package_intelligence(result, [{"req_id": "R1"}], {"title": "Bid"})
        finally:
            analyst._call = orig
        assert call_count["n"] == 1
        assert out["package_reasoning_status"] == "FAILED"


class TestLedgerWideByteBudget:
    """Fix #2: the byte budget is enforced against the FULL serialized
    ledger, not just the claims section -- requirement_evidence rows are
    dropped too when needed, and the actual bytes are re-measured (never
    estimated) after each drop."""

    def test_oversized_requirement_evidence_alone_is_pruned_to_fit_budget(self):
        big_notes = "x" * 3000
        req_coverage = [
            {"req_id": f"R{i}", "coverage": "Fully Addressed", "evidence_strength": "Strong",
             "notes": big_notes, "proposal_source_refs": [{"file_id": f"f{i}"}]}
            for i in range(600)
        ]
        result = _alignment_result(claims=[], req_coverage=req_coverage)
        ledger = analyst._build_package_intelligence_ledger(result, [])
        assert ledger is not None
        model_ledger, bookkeeping = analyst._split_ledger_bookkeeping(ledger)
        assert len(analyst._canonical_json_bytes(model_ledger)) <= analyst._LEDGER_BYTE_BUDGET
        assert len(model_ledger["requirement_evidence"]) < len(req_coverage)
        assert bookkeeping["requirement_evidence_dropped_for_budget"] > 0

    def test_mixed_sections_over_budget_all_stay_under_the_actual_limit(self):
        big_statement = "y" * 2500
        claims = [dict(_claim(claim_type="OTHER", req_id=None, subject=f"c{i}",
                              statement=big_statement, confidence="Low"),
                       proposal_source_refs=[{"file_id": f"cf{i}"}]) for i in range(15)]
        observations = [
            {"observation_type": "DELIVERY_COMMITMENT", "req_id": None, "title": f"D{i}",
             "statement": big_statement, "proposal_source_refs": [{"file_id": f"df{i}"}]}
            for i in range(15)
        ]
        findings = [
            {"deficiency_type": "MISSING", "req_id": None, "title": big_statement,
             "proposal_source_refs": [{"file_id": f"ff{i}"}]}
            for i in range(15)
        ]
        result = _alignment_result(claims=claims, findings=findings, observations=observations)
        ledger = analyst._build_package_intelligence_ledger(result, [])
        assert ledger is not None
        model_ledger, _ = analyst._split_ledger_bookkeeping(ledger)
        assert len(analyst._canonical_json_bytes(model_ledger)) <= analyst._LEDGER_BYTE_BUDGET


class TestPackageLedgerDigestMatchesModelInput:
    """Fix #3: package_ledger_digest hashes ONLY the exact payload sent to
    the model -- bookkeeping/diagnostic fields (e.g. dropped-for-budget
    counters) must never affect it."""

    def test_digest_identical_whether_bookkeeping_attached_or_not(self):
        big_statement = "z" * 2500
        claims = [dict(_claim(claim_type="OTHER", req_id=None, subject=f"c{i}",
                              statement=big_statement, confidence="Low"),
                       proposal_source_refs=[{"file_id": f"cf{i}"}]) for i in range(40)]
        result = _alignment_result(claims=claims)
        raw_ledger = analyst._build_package_intelligence_ledger(result, [])
        assert raw_ledger is not None
        assert "_budget_bookkeeping" in raw_ledger
        model_ledger, bookkeeping = analyst._split_ledger_bookkeeping(raw_ledger)
        assert "_budget_bookkeeping" not in model_ledger
        assert bookkeeping.get("claims_dropped_for_budget", 0) > 0
        assert analyst.package_ledger_digest(raw_ledger) == analyst.package_ledger_digest(model_ledger)

    def test_changing_only_bookkeeping_does_not_change_digest(self):
        ledger = {"coverage_complete": True, "claims": [], "requirement_evidence": [],
                  "delivery_commitments": [], "commercial_exposures": [], "local_deficiencies": [],
                  "source_registry": []}
        d1 = analyst.package_ledger_digest(dict(ledger, _budget_bookkeeping={"claims_dropped_for_budget": 0}))
        d2 = analyst.package_ledger_digest(dict(ledger, _budget_bookkeeping={"claims_dropped_for_budget": 99}))
        assert d1 == d2

    def test_prompt_never_receives_bookkeeping_key(self):
        big_statement = "w" * 2500
        claims = [dict(_claim(claim_type="OTHER", req_id=None, subject=f"c{i}",
                              statement=big_statement, confidence="Low"),
                       proposal_source_refs=[{"file_id": f"cf{i}"}]) for i in range(40)]
        result = _alignment_result(claims=claims)
        raw_ledger = analyst._build_package_intelligence_ledger(result, [])
        model_ledger, _ = analyst._split_ledger_bookkeeping(raw_ledger)
        prompt = analyst._package_reasoning_prompt("BID: x", model_ledger)
        assert "_budget_bookkeeping" not in prompt


class TestSourceToClaimAssociation:
    """Fix #4: a finding's supporting_source_ids must actually be
    associated with (traceable to) its own supporting_claim_ids -- a real
    claim cited with a real-but-unrelated source must be rejected."""

    def test_source_unrelated_to_cited_claim_is_rejected(self):
        ledger = _ledger_with_two_claims()  # C1 -> P1(f1), C2 -> P2(f2)
        raw = [{"finding_type": "UNSUPPORTED_CLAIM", "severity": "Medium", "req_id": "R1",
               "title": "t", "explanation": "e", "recommended_action": "a",
               "supporting_claim_ids": ["C1"], "supporting_source_ids": ["P2"]}]
        accepted, rejected = analyst._reconcile_package_findings(raw, ledger, [{"req_id": "R1"}])
        assert accepted == [] and rejected == 1

    def test_source_associated_via_any_cited_claim_is_accepted(self):
        ledger = _ledger_with_two_claims()
        raw = [{"finding_type": "CONTRADICTION", "severity": "High", "req_id": "R1",
               "title": "t", "explanation": "e", "recommended_action": "a",
               "supporting_claim_ids": ["C1", "C2"], "supporting_source_ids": ["P1", "P2"]}]
        accepted, rejected = analyst._reconcile_package_findings(raw, ledger, [{"req_id": "R1"}])
        assert rejected == 0 and len(accepted) == 1


class TestContradictionRequiresTwoDistinctClaims:
    """Fix #5: CONTRADICTION requires >=2 DISTINCT valid supporting
    claims; a single claim (even repeated) cannot be a contradiction.
    INTERNAL_INCONSISTENCY's existing >=1-claim requirement is unchanged."""

    def test_single_claim_contradiction_is_rejected(self):
        ledger = _ledger_with_two_claims()
        raw = [{"finding_type": "CONTRADICTION", "severity": "High", "req_id": "R1",
               "title": "t", "explanation": "e", "recommended_action": "a",
               "supporting_claim_ids": ["C1"], "supporting_source_ids": []}]
        accepted, rejected = analyst._reconcile_package_findings(raw, ledger, [{"req_id": "R1"}])
        assert accepted == [] and rejected == 1

    def test_duplicate_claim_id_does_not_satisfy_two_distinct_claims(self):
        ledger = _ledger_with_two_claims()
        raw = [{"finding_type": "CONTRADICTION", "severity": "High", "req_id": "R1",
               "title": "t", "explanation": "e", "recommended_action": "a",
               "supporting_claim_ids": ["C1", "C1"], "supporting_source_ids": []}]
        accepted, rejected = analyst._reconcile_package_findings(raw, ledger, [{"req_id": "R1"}])
        assert accepted == [] and rejected == 1

    def test_two_distinct_claims_contradiction_is_accepted(self):
        ledger = _ledger_with_two_claims()
        raw = [{"finding_type": "CONTRADICTION", "severity": "High", "req_id": "R1",
               "title": "t", "explanation": "e", "recommended_action": "a",
               "supporting_claim_ids": ["C1", "C2"], "supporting_source_ids": []}]
        accepted, rejected = analyst._reconcile_package_findings(raw, ledger, [{"req_id": "R1"}])
        assert rejected == 0 and len(accepted) == 1

    def test_internal_inconsistency_single_claim_still_accepted(self):
        ledger = _ledger_with_two_claims()
        raw = [{"finding_type": "INTERNAL_INCONSISTENCY", "severity": "Medium", "req_id": "R1",
               "title": "t", "explanation": "e", "recommended_action": "a",
               "supporting_claim_ids": ["C1"], "supporting_source_ids": []}]
        accepted, rejected = analyst._reconcile_package_findings(raw, ledger, [{"req_id": "R1"}])
        assert rejected == 0 and len(accepted) == 1


class TestTelemetryWorkflowParameter:
    """Fix #6: analyst._call takes a backward-compatible `workflow` param
    (default "analyst") -- existing call sites are unaffected, and
    package reasoning opts in to workflow="proposal_intelligence"."""

    def _patch_provider(self, monkeypatch):
        captured = []

        class _FakeContent:
            def __init__(self, text):
                self.text = text

        class _FakeResponse:
            def __init__(self, text):
                self.content = [_FakeContent(text)]

        def fake_client():
            return object()

        def fake_execute(client, *, telemetry_context=None, retry_number=0, **kwargs):
            captured.append(telemetry_context)
            return _FakeResponse('{"package_findings": []}')

        monkeypatch.setattr(analyst, "get_anthropic_client", fake_client)
        monkeypatch.setattr(analyst, "execute_messages_create", fake_execute)
        return captured

    def test_ordinary_call_defaults_to_analyst_workflow(self, monkeypatch):
        captured = self._patch_provider(monkeypatch)
        analyst._call("sys", "user", operation="alignment_chunk", bid_id=1)
        assert captured[-1]["workflow"] == "analyst"
        assert captured[-1]["operation"] == "alignment_chunk"

    def test_explicit_workflow_override_is_honored(self, monkeypatch):
        captured = self._patch_provider(monkeypatch)
        analyst._call("sys", "user", operation="package_reasoning", bid_id=1,
                      workflow="proposal_intelligence")
        assert captured[-1]["workflow"] == "proposal_intelligence"
        assert captured[-1]["operation"] == "package_reasoning"

    def test_package_reasoning_call_site_uses_proposal_intelligence_workflow(self, monkeypatch):
        captured = []

        def fake_call(system, user, max_tokens=2500, **kwargs):
            captured.append(kwargs)
            return json.dumps({"package_findings": []})

        orig = analyst._call
        analyst._call = fake_call
        try:
            analyst._call_package_reasoning("prompt", bid_id=1)
        finally:
            analyst._call = orig
        assert captured[-1]["workflow"] == "proposal_intelligence"
        assert captured[-1]["operation"] == "package_reasoning"
