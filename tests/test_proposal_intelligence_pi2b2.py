"""
tests/test_proposal_intelligence_pi2b2.py

Proposal Intelligence PI-2B2: Response Guideline coverage and evaluator
usability, added to the SAME single package-reasoning call PI-2B1
established (analyst.analyze_proposal_package_intelligence). ZERO live
provider calls anywhere in this file -- every model-shaped response is a
hand-built dict, and every real call site (analyst._call) is mocked or
never reached. Mirrors tests/test_proposal_intelligence_pi2b1.py's style.
"""
import json

import analyst
import proposal_intelligence as pi


def _claim(claim_type="STAFFING", req_id="R1", subject="coaches", statement="We have 8 coaches",
           value="8", unit="people", confidence="High"):
    return {"claim_type": claim_type, "req_id": req_id, "subject": subject, "statement": statement,
            "value": value, "unit": unit, "confidence": confidence}


def _alignment_result(claims=None, coverage_complete=True, req_coverage=None, findings=None, observations=None):
    return {
        "status": "complete" if coverage_complete else "incomplete",
        "proposal_claim_ledger": claims or [],
        "requirement_coverage": req_coverage or [],
        "findings": findings or [],
        "proposal_observations": observations or [],
        "coverage_metadata": {"coverage_complete": coverage_complete},
    }


def _guideline(gid="RG1", weight="10", minimum_score="3", evidence_prompts=None, source_doc="RFP.pdf"):
    return {"id": gid, "weight": weight, "minimum_score": minimum_score,
            "evidence_prompts": evidence_prompts or ["Describe your onboarding process."],
            "source_doc": source_doc}


def _ledger_with_one_claim_and_guideline(coverage_complete=True, ledger_complete_override=None):
    claims = [dict(_claim(), proposal_source_refs=[{"file_id": "f1"}])]
    result = _alignment_result(claims=claims, coverage_complete=coverage_complete)
    ledger = analyst._build_package_intelligence_ledger(result, [{"req_id": "R1"}], [_guideline()])
    if ledger_complete_override is not None:
        ledger["ledger_complete"] = ledger_complete_override
    return ledger


# ── GUIDELINE LEDGER EXTRACTION / BASIS ────────────────────────────────────

class TestGuidelineLedgerExtraction:

    def test_only_real_guidelines_enter_the_ledger(self):
        ledger = _ledger_with_one_claim_and_guideline()
        assert ledger["response_guidelines"] == [{
            "guideline_id": "G1", "weight": "10", "minimum_score": "3",
            "evidence_prompts": ["Describe your onboarding process."],
            "source_doc": "RFP.pdf",
        }]

    def test_no_guidelines_means_no_fabricated_section(self):
        result = _alignment_result(claims=[dict(_claim(), proposal_source_refs=[{"file_id": "f1"}])])
        ledger = analyst._build_package_intelligence_ledger(result, [{"req_id": "R1"}], [])
        assert "response_guidelines" not in ledger

    def test_no_guidelines_arg_at_all_means_no_fabricated_section(self):
        result = _alignment_result(claims=[dict(_claim(), proposal_source_refs=[{"file_id": "f1"}])])
        ledger = analyst._build_package_intelligence_ledger(result, [{"req_id": "R1"}])
        assert "response_guidelines" not in ledger

    def test_guideline_ids_are_stable_and_sequential(self):
        result = _alignment_result(claims=[dict(_claim(), proposal_source_refs=[{"file_id": "f1"}])])
        ledger = analyst._build_package_intelligence_ledger(
            result, [{"req_id": "R1"}], [_guideline("RG1"), _guideline("RG2")])
        assert [g["guideline_id"] for g in ledger["response_guidelines"]] == ["G1", "G2"]

    def test_malformed_guideline_entry_without_id_is_skipped(self):
        result = _alignment_result(claims=[dict(_claim(), proposal_source_refs=[{"file_id": "f1"}])])
        ledger = analyst._build_package_intelligence_ledger(
            result, [{"req_id": "R1"}], [{"weight": "10"}, _guideline("RG1")])
        assert len(ledger["response_guidelines"]) == 1
        assert ledger["response_guidelines"][0]["guideline_id"] == "G1"


# ── GUIDELINE ASSESSMENT RECONCILIATION ────────────────────────────────────

class TestGuidelineAssessmentReconciliation:

    def test_valid_answered_with_provenance_is_accepted(self):
        ledger = _ledger_with_one_claim_and_guideline()
        raw = [{"guideline_id": "G1", "status": "ANSWERED", "rationale": "Covered in section 2",
               "evaluator_traceability": "CLEAR",
               "supporting_claim_ids": ["C1"], "supporting_source_ids": ["P1"],
               "supporting_observation_ids": []}]
        accepted, rejected = analyst._reconcile_guideline_assessments(raw, ledger)
        assert rejected == 0
        assert len(accepted) == 1
        assert accepted[0]["status"] == "ANSWERED"
        assert accepted[0]["proposal_source_refs"] == [{"file_id": "f1"}]

    def test_partial_with_provenance_is_accepted(self):
        ledger = _ledger_with_one_claim_and_guideline()
        raw = [{"guideline_id": "G1", "status": "PARTIAL", "rationale": "Only staffing addressed",
               "evaluator_traceability": "FRAGMENTED",
               "supporting_claim_ids": ["C1"], "supporting_source_ids": [],
               "supporting_observation_ids": []}]
        accepted, rejected = analyst._reconcile_guideline_assessments(raw, ledger)
        assert rejected == 0 and accepted[0]["status"] == "PARTIAL"

    def test_answered_without_provenance_is_rejected(self):
        ledger = _ledger_with_one_claim_and_guideline()
        raw = [{"guideline_id": "G1", "status": "ANSWERED", "rationale": "Trust me",
               "supporting_claim_ids": [], "supporting_source_ids": [], "supporting_observation_ids": []}]
        accepted, rejected = analyst._reconcile_guideline_assessments(raw, ledger)
        assert accepted == [] and rejected == 1

    def test_partial_with_unknown_claim_id_is_rejected(self):
        ledger = _ledger_with_one_claim_and_guideline()
        raw = [{"guideline_id": "G1", "status": "PARTIAL", "rationale": "x",
               "supporting_claim_ids": ["C99"], "supporting_source_ids": [], "supporting_observation_ids": []}]
        accepted, rejected = analyst._reconcile_guideline_assessments(raw, ledger)
        assert accepted == [] and rejected == 1

    def test_unknown_source_id_not_traceable_to_claim_is_rejected(self):
        # Two claims/sources so an attacker-style pairing of a real claim
        # with an unrelated real source is possible and must be rejected
        # (Fix #4 association rule, reused verbatim from PI-2B1).
        claims = [dict(_claim(subject="A"), proposal_source_refs=[{"file_id": "f1"}]),
                  dict(_claim(subject="B"), proposal_source_refs=[{"file_id": "f2"}])]
        result = _alignment_result(claims=claims)
        ledger = analyst._build_package_intelligence_ledger(result, [{"req_id": "R1"}], [_guideline()])
        # C1 -> P1 (f1), C2 -> P2 (f2); cite C1 with P2 -- not associated.
        raw = [{"guideline_id": "G1", "status": "ANSWERED", "rationale": "x",
               "supporting_claim_ids": ["C1"], "supporting_source_ids": ["P2"],
               "supporting_observation_ids": []}]
        accepted, rejected = analyst._reconcile_guideline_assessments(raw, ledger)
        assert accepted == [] and rejected == 1

    def test_unknown_guideline_id_is_rejected(self):
        ledger = _ledger_with_one_claim_and_guideline()
        raw = [{"guideline_id": "G99", "status": "ANSWERED", "rationale": "x",
               "supporting_claim_ids": ["C1"], "supporting_source_ids": [], "supporting_observation_ids": []}]
        accepted, rejected = analyst._reconcile_guideline_assessments(raw, ledger)
        assert accepted == [] and rejected == 1

    def test_unknown_status_is_rejected(self):
        ledger = _ledger_with_one_claim_and_guideline()
        raw = [{"guideline_id": "G1", "status": "MOSTLY_ANSWERED", "rationale": "x",
               "supporting_claim_ids": ["C1"], "supporting_source_ids": [], "supporting_observation_ids": []}]
        accepted, rejected = analyst._reconcile_guideline_assessments(raw, ledger)
        assert accepted == [] and rejected == 1

    def test_one_malformed_assessment_does_not_fail_the_rest(self):
        ledger = _ledger_with_one_claim_and_guideline()
        raw = [
            {"guideline_id": "G1", "status": "BOGUS", "rationale": "bad"},
            {"guideline_id": "G1", "status": "ANSWERED", "rationale": "good",
             "supporting_claim_ids": ["C1"], "supporting_source_ids": [], "supporting_observation_ids": []},
        ]
        accepted, rejected = analyst._reconcile_guideline_assessments(raw, ledger)
        assert rejected == 1 and len(accepted) == 1 and accepted[0]["rationale"] == "good"

    def test_invalid_evaluator_traceability_value_dropped_to_none_not_rejected(self):
        ledger = _ledger_with_one_claim_and_guideline()
        raw = [{"guideline_id": "G1", "status": "ANSWERED", "rationale": "x",
               "evaluator_traceability": "SUPER_CLEAR",
               "supporting_claim_ids": ["C1"], "supporting_source_ids": [], "supporting_observation_ids": []}]
        accepted, rejected = analyst._reconcile_guideline_assessments(raw, ledger)
        assert rejected == 0
        assert accepted[0]["evaluator_traceability"] is None


class TestGuidelineAbsenceNeverFabricated:

    def test_not_answered_requires_complete_coverage_and_ledger(self):
        ledger = _ledger_with_one_claim_and_guideline(coverage_complete=True)
        assert ledger["coverage_complete"] is True and ledger["ledger_complete"] is True
        raw = [{"guideline_id": "G1", "status": "NOT_ANSWERED", "rationale": "nothing found",
               "supporting_claim_ids": [], "supporting_source_ids": [], "supporting_observation_ids": []}]
        accepted, rejected = analyst._reconcile_guideline_assessments(raw, ledger)
        assert rejected == 0 and accepted[0]["status"] == "NOT_ANSWERED"

    def test_incomplete_coverage_downgrades_not_answered_to_cannot_assess(self):
        ledger = _ledger_with_one_claim_and_guideline(coverage_complete=False)
        assert ledger["coverage_complete"] is False
        raw = [{"guideline_id": "G1", "status": "NOT_ANSWERED", "rationale": "nothing found",
               "supporting_claim_ids": [], "supporting_source_ids": [], "supporting_observation_ids": []}]
        accepted, rejected = analyst._reconcile_guideline_assessments(raw, ledger)
        # downgraded, never rejected outright -- the assessment was genuine
        assert rejected == 0
        assert accepted[0]["status"] == "CANNOT_ASSESS"

    def test_incomplete_ledger_downgrades_not_answered_to_cannot_assess(self):
        ledger = _ledger_with_one_claim_and_guideline(coverage_complete=True, ledger_complete_override=False)
        raw = [{"guideline_id": "G1", "status": "NOT_ANSWERED", "rationale": "nothing found",
               "supporting_claim_ids": [], "supporting_source_ids": [], "supporting_observation_ids": []}]
        accepted, rejected = analyst._reconcile_guideline_assessments(raw, ledger)
        assert rejected == 0
        assert accepted[0]["status"] == "CANNOT_ASSESS"

    def test_incomplete_coverage_still_allows_validated_positive_evidence(self):
        # Genuine positive evidence retained in the ledger despite
        # incompleteness still stands -- incompleteness only blocks
        # concluding NOT_ANSWERED from silence.
        ledger = _ledger_with_one_claim_and_guideline(coverage_complete=False)
        raw = [{"guideline_id": "G1", "status": "ANSWERED", "rationale": "found it",
               "supporting_claim_ids": ["C1"], "supporting_source_ids": ["P1"],
               "supporting_observation_ids": []}]
        accepted, rejected = analyst._reconcile_guideline_assessments(raw, ledger)
        assert rejected == 0 and accepted[0]["status"] == "ANSWERED"

    def test_cannot_assess_needs_no_citations(self):
        ledger = _ledger_with_one_claim_and_guideline(coverage_complete=False)
        raw = [{"guideline_id": "G1", "status": "CANNOT_ASSESS", "rationale": "insufficient coverage",
               "supporting_claim_ids": [], "supporting_source_ids": [], "supporting_observation_ids": []}]
        accepted, rejected = analyst._reconcile_guideline_assessments(raw, ledger)
        assert rejected == 0 and accepted[0]["status"] == "CANNOT_ASSESS"


# ── ledger-wide byte budget covers guidelines too ──────────────────────────

class TestGuidelineLedgerByteBudget:

    def test_guidelines_are_prunable_and_flip_ledger_complete(self):
        big_prompt = "x" * 3000
        many_guidelines = [_guideline(f"RG{i}", evidence_prompts=[big_prompt]) for i in range(60)]
        claims = [dict(_claim(), proposal_source_refs=[{"file_id": "f1"}])]
        result = _alignment_result(claims=claims)
        ledger = analyst._build_package_intelligence_ledger(result, [{"req_id": "R1"}], many_guidelines)
        assert len(ledger.get("response_guidelines") or []) < len(many_guidelines)
        assert ledger["ledger_complete"] is False


# ── analyze_proposal_package_intelligence -- one call, guidelines threaded ─

class TestAnalyzePackageIntelligenceWithGuidelines:

    def test_still_exactly_one_call_site_with_guidelines(self):
        calls = []

        def fake_call(system, user, max_tokens=2500, **kwargs):
            calls.append(kwargs.get("operation"))
            return json.dumps({
                "package_findings": [],
                "guideline_assessments": [
                    {"guideline_id": "G1", "status": "ANSWERED", "rationale": "ok",
                     "evaluator_traceability": "CLEAR",
                     "supporting_claim_ids": ["C1"], "supporting_source_ids": [],
                     "supporting_observation_ids": []},
                ],
            })

        claims = [dict(_claim(), proposal_source_refs=[{"file_id": "f1"}])]
        result = _alignment_result(claims=claims)
        orig = analyst._call
        analyst._call = fake_call
        try:
            out = analyst.analyze_proposal_package_intelligence(
                result, [{"req_id": "R1"}], {"title": "Bid"}, response_guidelines=[_guideline()])
        finally:
            analyst._call = orig
        assert calls == ["package_reasoning"]
        assert out["package_reasoning_status"] == "OK"
        assert len(out["guideline_assessments"]) == 1
        assert out["guideline_assessments"][0]["status"] == "ANSWERED"

    def test_no_guidelines_yields_empty_assessments_no_crash(self):
        def fake_call(system, user, max_tokens=2500, **kwargs):
            return json.dumps({"package_findings": []})

        claims = [dict(_claim(), proposal_source_refs=[{"file_id": "f1"}])]
        result = _alignment_result(claims=claims)
        orig = analyst._call
        analyst._call = fake_call
        try:
            out = analyst.analyze_proposal_package_intelligence(result, [{"req_id": "R1"}], {"title": "Bid"})
        finally:
            analyst._call = orig
        assert out["guideline_assessments"] == []
        assert out["rejected_guideline_count"] == 0

    def test_malformed_guideline_assessments_shape_fails_closed(self):
        def fake_call(system, user, max_tokens=2500, **kwargs):
            return json.dumps({"package_findings": [], "guideline_assessments": "not-a-list"})

        claims = [dict(_claim(), proposal_source_refs=[{"file_id": "f1"}])]
        result = _alignment_result(claims=claims)
        orig = analyst._call
        analyst._call = fake_call
        try:
            out = analyst.analyze_proposal_package_intelligence(
                result, [{"req_id": "R1"}], {"title": "Bid"}, response_guidelines=[_guideline()])
        finally:
            analyst._call = orig
        assert out["package_reasoning_status"] == "FAILED"
        assert out["guideline_assessments"] == []


# ── adapter / persistence / reload (no new model call) ─────────────────────

class TestGuidelineAssessmentAdapter:

    def _package_result(self, status="NOT_ANSWERED", traceability=None):
        return {
            "package_findings": [], "package_reasoning_status": "OK",
            "package_ledger_digest": "digest123", "rejected_count": 0,
            "guideline_assessments": [{
                "guideline_id": "G1", "status": status, "rationale": "why",
                "evaluator_traceability": traceability,
                "supporting_claim_ids": ["C1"], "supporting_source_ids": [],
                "supporting_observation_ids": [], "proposal_source_refs": [{"file_id": "f1"}],
            }],
        }

    def test_not_answered_becomes_response_guideline_gap_finding(self):
        rows = pi.adapt_guideline_assessments(self._package_result(status="NOT_ANSWERED"))
        assert len(rows) == 1
        assert rows[0]["finding_type"] == pi.FINDING_TYPE_RESPONSE_GUIDELINE_GAP
        assert rows[0]["payload"]["kind"] == "guideline_assessment"

    def test_answered_becomes_other_finding_type_not_a_gap(self):
        rows = pi.adapt_guideline_assessments(self._package_result(status="ANSWERED", traceability="CLEAR"))
        assert rows[0]["finding_type"] == pi.FINDING_TYPE_OTHER
        assert rows[0]["payload"]["evaluator_traceability"] == "CLEAR"

    def test_no_guideline_assessments_yields_no_rows(self):
        rows = pi.adapt_guideline_assessments({"guideline_assessments": []})
        assert rows == []

    def test_missing_key_yields_no_rows(self):
        rows = pi.adapt_guideline_assessments({})
        assert rows == []

    def test_roundtrip_through_reconstruct_legacy_align_result(self):
        package_result = self._package_result(status="PARTIAL", traceability="FRAGMENTED")
        findings = pi.adapt_guideline_assessments(package_result)
        run = {"status": "COMPLETE", "legacy_result": {}, "coverage_metadata": {}}
        rebuilt = pi.reconstruct_legacy_align_result(run, [], findings)
        assert len(rebuilt["guideline_assessments"]) == 1
        ga = rebuilt["guideline_assessments"][0]
        assert ga["guideline_id"] == "G1"
        assert ga["status"] == "PARTIAL"
        assert ga["evaluator_traceability"] == "FRAGMENTED"
        # never mixed into general findings or package_findings
        assert rebuilt["findings"] == []
        assert rebuilt["package_findings"] == []

    def test_historical_run_with_no_guideline_data_renders_safely(self):
        run = {"status": "COMPLETE", "legacy_result": {}, "coverage_metadata": {}}
        rebuilt = pi.reconstruct_legacy_align_result(run, [], [])
        assert rebuilt["guideline_assessments"] == []


# ── ANALYSIS_VERSION bump / staleness ───────────────────────────────────────

class TestAnalysisVersionBump:

    def test_version_is_v4(self):
        assert pi.PROPOSAL_INTELLIGENCE_ANALYSIS_VERSION == "proposal-intelligence-v4"

    def test_pre_v4_run_flags_analysis_version_changed(self):
        run = {"based_on_procurement_revision": 1, "proposal_package_snapshot_id": 5,
               "analysis_version": "proposal-intelligence-v3"}
        reasons = pi.staleness_reasons(
            run, current_procurement_revision=1, current_package_snapshot_id=5)
        assert pi.STALE_ANALYSIS_VERSION_CHANGED in reasons

    def test_current_v4_run_is_not_stale_on_version(self):
        run = {"based_on_procurement_revision": 1, "proposal_package_snapshot_id": 5,
               "analysis_version": "proposal-intelligence-v4"}
        reasons = pi.staleness_reasons(
            run, current_procurement_revision=1, current_package_snapshot_id=5)
        assert pi.STALE_ANALYSIS_VERSION_CHANGED not in reasons
