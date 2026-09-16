"""
tests/test_proposal_alignment_analyzer.py

Deterministic tests for the Proposal Alignment Analyzer correctness
remediation (CHECK -> Proposal Alignment Analyzer). No live LLM calls --
analyst._call() is mocked everywhere. Covers:

  * TestChunkingAndCoverage -- the whole proposal is analyzed (not just
    the first 8,000 characters), coverage metadata is accurate, and the
    per-audit call count is bounded regardless of document size.
  * TestScoringDeterminism -- the score formula is exact, deterministic,
    respects legitimate buyer weights, never invents a weight, and never
    reinterprets an unrelated numeric field as one.
  * TestQualificationGateExclusion -- a requirement that is semantically
    a supplier-qualification/eligibility gate (per the same governed
    cue-detection DECIDE/CHECK's own Qualification Gates KPI already
    uses) never joins the numeric score, regardless of its category or
    any stray weight, while staying visible in coverage/findings and
    still able to force MAJOR REVISION NEEDED if unaddressed.
  * TestZeroEvaluationUniverse -- a procurement with real requirements
    but no legitimate rated/evaluative criteria at all is a genuinely
    COMPLETE audit with no invented score, not an incomplete one and
    not treated as a failure.
  * TestFailClosedBehavior -- no malformed/truncated/incomplete response
    can produce a numeric score; the literal old 50/REVISE fallback no
    longer exists in the source at all.
  * TestCoverageSemantics -- "Not Addressed" is only ever concluded when
    proposal coverage is complete; otherwise absence is "Cannot Assess".
  * TestNarrativeSynthesisResilience -- a failed synthesis call degrades
    gracefully without discarding a valid deterministic audit.
  * TestStageCheckUsesCanonicalIntelligence -- bid.notes is no longer
    used as tender context; bid_briefs + the compliance matrix are.
  * TestStageCheckRendering -- a complete result renders every required
    section; an incomplete result renders the fail-closed message and
    nothing else.
"""
import inspect
import json
import os
import unittest
from unittest.mock import MagicMock, patch

import analyst
import pages.stage_check as stage_check
from requirement_semantics import has_supplier_qualification_evidence


def _req(req_id, category="Rated", description="desc", weight=None):
    return {"req_id": req_id, "category": category, "description": description, "weight": weight}


def _chunk_response(assertions=None, findings=None):
    return json.dumps({
        "chunk_findings": findings or [],
        "requirement_assertions": assertions or [],
    })


def _synthesis_response(summary="ok", strengths=None, next_steps=None):
    return json.dumps({
        "executive_summary": summary,
        "strengths": strengths or [],
        "next_steps": next_steps or [],
    })


class TestChunkingAndCoverage(unittest.TestCase):
    def _build_proposal(self, total_chars, marker, marker_pos):
        filler = "Our proposed methodology addresses the stated requirements in detail. "
        body = (filler * (total_chars // len(filler) + 1))[:total_chars]
        return body[:marker_pos] + marker + body[marker_pos:]

    def test_full_120k_proposal_is_not_reduced_to_first_8k_chars(self):
        marker = "UNIQUE_MARKER_BEYOND_OLD_8K_CUTOFF_XYZ"
        proposal = self._build_proposal(124110, marker, 100000)
        seen_prompts = []

        def fake_call(system, user, max_tokens=2048):
            seen_prompts.append(user)
            if "requirement_assertions" in user:
                return _chunk_response()
            return _synthesis_response()

        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment(proposal, [_req("R1")], "context", {"title": "T", "client": "C"})

        self.assertEqual(result["status"], "complete")
        self.assertTrue(any(marker in p for p in seen_prompts),
                         "a marker planted at ~char 100,000 never reached any chunk prompt -- "
                         "proves the old proposal_text[:8000] behavior is gone")

    def test_complete_character_accounting_for_the_live_example_size(self):
        proposal = self._build_proposal(124110, "M", 100000)

        def fake_call(system, user, max_tokens=2048):
            if "requirement_assertions" in user:
                return _chunk_response()
            return _synthesis_response()

        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment(proposal, [], "context", {"title": "T", "client": "C"})

        cov = result["coverage_metadata"]
        self.assertEqual(cov["chars_total"], len(proposal))
        self.assertEqual(cov["chars_processed"], cov["chars_total"])
        self.assertEqual(cov["percentage_covered"], 100.0)
        self.assertEqual(cov["failed_or_skipped_chunks"], 0)
        self.assertTrue(cov["coverage_complete"])

    def test_bounded_call_count_regardless_of_document_size(self):
        """A document far larger than the safe ceiling must still bound
        the number of model calls -- representative sampling, not an
        unbounded per-section call for every section found."""
        huge_proposal = self._build_proposal(400000, "M", 200000)
        call_count = {"n": 0}

        def fake_call(system, user, max_tokens=2048):
            call_count["n"] += 1
            if "requirement_assertions" in user:
                return _chunk_response()
            return _synthesis_response()

        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment(huge_proposal, [], "context", {"title": "T", "client": "C"})

        # chunk calls bounded at _ALIGN_MAX_CHUNKS + 1 synthesis call, with
        # at most one retry per chunk in the worst case.
        self.assertLessEqual(call_count["n"], 2 * analyst._ALIGN_MAX_CHUNKS + 1)
        self.assertLess(result["coverage_metadata"]["percentage_covered"], 100.0)
        self.assertFalse(result["coverage_metadata"]["coverage_complete"])

    def test_ceiling_exceeded_sampling_is_representative_not_front_loaded(self):
        """When a document exceeds the safe ceiling, the analyzed chunks
        must be spread across the whole document, not just the first N --
        proven by a marker near the very end still being reachable."""
        marker = "END_OF_DOCUMENT_MARKER_ZZZ"
        huge_proposal = self._build_proposal(400000, "", 0)
        huge_proposal = huge_proposal[:-len(marker)] + marker
        seen_prompts = []

        def fake_call(system, user, max_tokens=2048):
            seen_prompts.append(user)
            if "requirement_assertions" in user:
                return _chunk_response()
            return _synthesis_response()

        with patch("analyst._call", side_effect=fake_call):
            analyst.analyze_proposal_alignment(huge_proposal, [], "context", {"title": "T", "client": "C"})

        self.assertTrue(any(marker in p for p in seen_prompts),
                         "a marker at the very end of an oversized document never reached any "
                         "chunk prompt -- sampling is front-loaded, not representative")


class TestScoringDeterminism(unittest.TestCase):
    """Instruction 1's corrected scoring universe: the Evaluation
    Alignment Score is computed ONLY from Rated/Financial (or
    explicitly buyer-weighted) requirements. Mandatory requirements are
    ALWAYS excluded from the numeric average -- they are gates, handled
    separately -- and an unweighted mandatory requirement must never
    cause legitimate buyer evaluation weights on the rated set to be
    discarded."""

    def test_unweighted_formula_is_exact(self):
        coverage = [
            {"req_id": "A", "category": "Rated", "coverage": "Fully Addressed", "_weight": None},
            {"req_id": "B", "category": "Rated", "coverage": "Partially Addressed", "_weight": None},
            {"req_id": "C", "category": "Rated", "coverage": "Not Addressed", "_weight": None},
        ]
        score_info = analyst._compute_score(coverage)
        # (100 + 50 + 0) / 3 = 50.0 exactly
        self.assertEqual(score_info["overall_score"], 50.0)
        self.assertEqual(score_info["score_basis"], analyst._ALIGN_SCORE_BASIS_NO_BUYER_WEIGHTS)

    def test_buyer_weights_are_respected_when_all_scored_requirements_have_them(self):
        coverage = [
            {"req_id": "A", "category": "Rated", "coverage": "Fully Addressed", "_weight": 0.8},
            {"req_id": "B", "category": "Rated", "coverage": "Not Addressed", "_weight": 0.2},
        ]
        score_info = analyst._compute_score(coverage)
        # (100*0.8 + 0*0.2) / 1.0 = 80.0
        self.assertEqual(score_info["overall_score"], 80.0)
        self.assertEqual(score_info["score_basis"], analyst._ALIGN_SCORE_BASIS_BUYER_WEIGHTED)

    def test_buyer_weights_not_summing_to_one_are_mathematically_normalized(self):
        coverage = [
            {"req_id": "A", "category": "Rated", "coverage": "Fully Addressed", "_weight": 40},
            {"req_id": "B", "category": "Rated", "coverage": "Not Addressed", "_weight": 10},
        ]
        score_info = analyst._compute_score(coverage)
        # normalized: (100*40 + 0*10) / 50 = 80.0
        self.assertEqual(score_info["overall_score"], 80.0)
        self.assertEqual(score_info["score_basis"], analyst._ALIGN_SCORE_BASIS_BUYER_WEIGHTED)

    def test_incomplete_buyer_weighting_falls_back_to_equal_weight_never_invented(self):
        coverage = [
            {"req_id": "A", "category": "Rated", "coverage": "Fully Addressed", "_weight": 0.9},
            {"req_id": "B", "category": "Rated", "coverage": "Not Addressed", "_weight": None},
        ]
        score_info = analyst._compute_score(coverage)
        self.assertEqual(score_info["score_basis"], analyst._ALIGN_SCORE_BASIS_INCOMPLETE_WEIGHTS)
        self.assertEqual(score_info["overall_score"], 50.0)  # (100 + 0) / 2, weight never invented for B

    def test_cannot_assess_excluded_from_score_entirely(self):
        coverage = [
            {"req_id": "A", "category": "Rated", "coverage": "Fully Addressed", "_weight": None},
            {"req_id": "B", "category": "Rated", "coverage": "Cannot Assess", "_weight": None},
        ]
        score_info = analyst._compute_score(coverage)
        self.assertEqual(score_info["overall_score"], 100.0)  # B excluded entirely, not counted as 0

    def test_unrelated_numeric_fields_are_never_treated_as_weights(self):
        """A requirement's dict may carry unrelated numeric fields (e.g.
        a pricing formula percentage under some other key) -- only the
        literal 'weight' field may ever influence the score."""
        requirements = [
            {"req_id": "A", "category": "Rated", "description": "x",
             "weight": None, "price_formula_pct": 0.65, "discount_pct": 0.10},
        ]
        coverage = analyst._aggregate_requirement_coverage(requirements, [], coverage_complete=True)
        weight_by_req = {r.get("req_id"): r.get("weight") for r in requirements}
        for row in coverage:
            row["_weight"] = weight_by_req.get(row["req_id"])
        score_info = analyst._compute_score(coverage)
        self.assertEqual(score_info["score_basis"], analyst._ALIGN_SCORE_BASIS_NO_BUYER_WEIGHTS)

    def test_boolean_weight_value_is_never_treated_as_valid(self):
        coverage = [{"req_id": "A", "category": "Rated", "coverage": "Fully Addressed", "_weight": True}]
        score_info = analyst._compute_score(coverage)
        self.assertEqual(score_info["score_basis"], analyst._ALIGN_SCORE_BASIS_NO_BUYER_WEIGHTS)

    def test_mandatory_requirements_always_excluded_from_score_even_if_weighted(self):
        """Mandatory is pass/fail by nature -- even a stray weight on a
        Mandatory-category row must never pull it into the numeric
        average (instruction 1.B: 'Keep mandatory ... outside the
        numeric evaluation average', unconditionally)."""
        coverage = [
            {"req_id": "M1", "category": "Mandatory", "coverage": "Not Addressed", "_weight": 0.5},
            {"req_id": "R1", "category": "Rated", "coverage": "Fully Addressed", "_weight": None},
        ]
        score_info = analyst._compute_score(coverage)
        self.assertEqual(score_info["overall_score"], 100.0)  # M1 excluded entirely
        self.assertEqual(score_info["score_basis"], analyst._ALIGN_SCORE_BASIS_NO_BUYER_WEIGHTS)

    def test_supporting_category_without_weight_does_not_join_evaluation_score(self):
        coverage = [
            {"req_id": "R1", "category": "Rated", "coverage": "Fully Addressed", "_weight": None},
            {"req_id": "S1", "category": "Supporting", "coverage": "Not Addressed", "_weight": None},
        ]
        score_info = analyst._compute_score(coverage)
        self.assertEqual(score_info["overall_score"], 100.0)  # S1 (Supporting, no weight) excluded

    def test_supporting_category_with_explicit_buyer_weight_does_join_evaluation_score(self):
        """The procurement itself made this Supporting item evaluative
        by assigning it a real weight -- instruction 1.C."""
        coverage = [
            {"req_id": "S1", "category": "Supporting", "coverage": "Not Addressed", "_weight": 1.0},
        ]
        score_info = analyst._compute_score(coverage)
        self.assertEqual(score_info["overall_score"], 0.0)
        self.assertEqual(score_info["score_basis"], analyst._ALIGN_SCORE_BASIS_BUYER_WEIGHTED)

    def test_mixed_weighted_rated_plus_unweighted_mandatory_procurement(self):
        """The exact scenario instruction 1 calls out: a real
        procurement with buyer-weighted rated criteria AND unweighted
        mandatory requirements together. The mandatory item must not
        cause the legitimate rated weights to be discarded."""
        requirements = [
            _req("R1", category="Rated", weight=0.6),
            _req("R2", category="Rated", weight=0.4),
            _req("M1", category="Mandatory", weight=None),
        ]
        chunk_results = [{
            "chunk_label": "S1",
            "requirement_assertions": [
                {"req_id": "R1", "coverage": "Fully Addressed", "confidence": "High", "evidence": "e"},
                {"req_id": "R2", "coverage": "Partially Addressed",
                 "confidence": "Medium", "evidence": "e"},
                # M1 gets no assertion -- with complete coverage this resolves to "Not Addressed"
            ],
        }]
        requirement_coverage = analyst._aggregate_requirement_coverage(requirements, chunk_results, coverage_complete=True)
        weight_by_req = {r.get("req_id"): r.get("weight") for r in requirements}
        for row in requirement_coverage:
            row["_weight"] = weight_by_req.get(row["req_id"])
        score_info = analyst._compute_score(requirement_coverage)
        mandatory_failures = analyst._extract_mandatory_failures(requirement_coverage)

        # Score computed ONLY from R1/R2 using their real buyer weights:
        # (100*0.6 + 50*0.4) / 1.0 = 80.0 -- M1 has zero influence on it.
        self.assertEqual(score_info["overall_score"], 80.0)
        self.assertEqual(score_info["score_basis"], analyst._ALIGN_SCORE_BASIS_BUYER_WEIGHTED)
        # M1 is surfaced as a separate mandatory failure, not folded into the average.
        self.assertEqual(len(mandatory_failures), 1)
        self.assertEqual(mandatory_failures[0]["req_id"], "M1")
        # And it still overrides the recommendation despite the high score.
        rec, _ = analyst._derive_recommendation(score_info["overall_score"], mandatory_failures)
        self.assertEqual(rec, "MAJOR REVISION NEEDED")

    def test_mandatory_failure_overrides_recommendation_regardless_of_score(self):
        rec, rationale = analyst._derive_recommendation(98.0, [{"req_id": "M1"}])
        self.assertEqual(rec, "MAJOR REVISION NEEDED")
        self.assertIn("mandatory", rationale.lower())

    def test_high_score_without_mandatory_failure_recommends_submit(self):
        rec, _ = analyst._derive_recommendation(90.0, [])
        self.assertEqual(rec, "SUBMIT AS-IS")


_QUALIFICATION_GATE_TEXT = "Bidder must meet minimum qualifications including proof of insurance."


class TestQualificationGateExclusion(unittest.TestCase):
    """Instruction 1: a requirement that is semantically a supplier-
    qualification/eligibility gate must never contribute to the numeric
    Evaluation Alignment Score, REGARDLESS of what category it is filed
    under or whether it carries a stray weight -- reusing the same
    governed cue-detection (requirement_semantics.
    has_supplier_qualification_evidence) already used for DECIDE/CHECK's
    own Qualification Gates KPI, rather than inventing a new detector."""

    def _coverage_row(self, requirements, chunk_results, coverage_complete=True):
        rows = analyst._aggregate_requirement_coverage(requirements, chunk_results, coverage_complete)
        weight_by_req = {r.get("req_id"): r.get("weight") for r in requirements}
        for row in rows:
            row["_weight"] = weight_by_req.get(row["req_id"])
        return rows

    def test_qualification_gate_detected_regardless_of_category(self):
        """The exact governed cue-detector correctly flags a gate even
        when it is NOT filed under category == Mandatory."""
        self.assertTrue(has_supplier_qualification_evidence(
            {"description": _QUALIFICATION_GATE_TEXT, "rfso_ref": ""}
        ))

    def test_qualification_gate_with_non_mandatory_category_excluded_from_score(self):
        requirements = [
            _req("Q1", category="Rated", description=_QUALIFICATION_GATE_TEXT, weight=None),
            _req("R1", category="Rated", description="Describe methodology", weight=None),
        ]
        chunk_results = [{
            "chunk_label": "S1",
            "requirement_assertions": [
                {"req_id": "Q1", "coverage": "Fully Addressed", "confidence": "High", "evidence": "e"},
                {"req_id": "R1", "coverage": "Fully Addressed", "confidence": "High", "evidence": "e"},
            ],
        }]
        rows = self._coverage_row(requirements, chunk_results)
        score_info = analyst._compute_score(rows)
        # If Q1 (Rated category!) were NOT excluded, both would be
        # Fully Addressed and the score would still read 100 -- so this
        # test also checks the exclusion took effect via evaluation-set
        # membership directly, not just the final number.
        evaluation_req_ids = {
            r["req_id"] for r in rows
            if (r["category"] or "").lower() != "mandatory"
            and not r.get("_is_qualification_gate")
            and (r["category"] or "").lower() in analyst._ALIGN_EVALUATIVE_CATEGORIES
        }
        self.assertNotIn("Q1", evaluation_req_ids)
        self.assertIn("R1", evaluation_req_ids)
        self.assertEqual(score_info["overall_score"], 100.0)

    def test_qualification_gate_with_numeric_weight_still_excluded(self):
        """A stray numeric weight on a qualification gate must not make
        it evaluative -- the exclusion is unconditional."""
        requirements = [
            _req("Q1", category="Supporting", description=_QUALIFICATION_GATE_TEXT, weight=0.9),
            _req("R1", category="Rated", description="Describe methodology", weight=None),
        ]
        chunk_results = [{
            "chunk_label": "S1",
            "requirement_assertions": [
                {"req_id": "Q1", "coverage": "Fully Addressed", "confidence": "High", "evidence": "e"},
                {"req_id": "R1", "coverage": "Partially Addressed", "confidence": "High", "evidence": "e"},
            ],
        }]
        rows = self._coverage_row(requirements, chunk_results)
        score_info = analyst._compute_score(rows)
        # If Q1's weight were honored, a weighted average with Q1=100 at
        # weight 0.9 would dominate and push the score near 100. Instead
        # the score must come from R1 alone (Partially Addressed = 50),
        # proving Q1's weight had zero influence.
        self.assertEqual(score_info["overall_score"], 50.0)
        self.assertEqual(score_info["score_basis"], analyst._ALIGN_SCORE_BASIS_NO_BUYER_WEIGHTS)

    def test_qualification_gate_remains_visible_in_requirement_coverage(self):
        requirements = [_req("Q1", category="Rated", description=_QUALIFICATION_GATE_TEXT, weight=None)]
        rows = self._coverage_row(requirements, [], coverage_complete=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["req_id"], "Q1")
        self.assertEqual(rows[0]["coverage"], "Not Addressed")

    def test_unaddressed_qualification_gate_surfaces_as_mandatory_risk_and_forces_major_revision(self):
        requirements = [
            _req("Q1", category="Rated", description=_QUALIFICATION_GATE_TEXT, weight=None),
            _req("R1", category="Rated", description="Describe methodology", weight=None),
        ]
        chunk_results = [{
            "chunk_label": "S1",
            "requirement_assertions": [
                {"req_id": "R1", "coverage": "Fully Addressed", "confidence": "High", "evidence": "e"},
                # Q1 gets no positive assertion anywhere -> Not Addressed (coverage complete)
            ],
        }]
        rows = self._coverage_row(requirements, chunk_results)
        score_info = analyst._compute_score(rows)
        mandatory_failures = analyst._extract_mandatory_failures(rows)

        self.assertEqual(len(mandatory_failures), 1)
        self.assertEqual(mandatory_failures[0]["req_id"], "Q1")
        rec, _ = analyst._derive_recommendation(score_info["overall_score"], mandatory_failures)
        self.assertEqual(rec, "MAJOR REVISION NEEDED")
        # And the score itself is still computed purely from R1 (100.0),
        # unaffected by Q1's absence -- the failure is surfaced
        # separately, not folded into the average.
        self.assertEqual(score_info["overall_score"], 100.0)


class TestZeroEvaluationUniverse(unittest.TestCase):
    """Instruction 2: a procurement can have real, persisted
    requirements yet contain no legitimate rated/evaluative criteria at
    all -- only mandatory, qualification, commercial, or supporting
    items. That is a genuinely COMPLETE audit, not an incomplete one
    (distinct from TestFailClosedBehavior's coverage-incomplete case),
    and must not invent a numeric score from the non-evaluative set."""

    def test_no_evaluative_criteria_produces_no_score_not_an_invented_one(self):
        coverage = [
            {"req_id": "M1", "category": "Mandatory", "coverage": "Fully Addressed", "_weight": None},
            {"req_id": "C1", "category": "Commercial", "coverage": "Fully Addressed", "_weight": None},
            {"req_id": "S1", "category": "Supporting", "coverage": "Partially Addressed", "_weight": None},
        ]
        score_info = analyst._compute_score(coverage)
        self.assertIsNone(score_info["overall_score"])
        self.assertEqual(score_info["score_basis"], analyst._ALIGN_SCORE_BASIS_NO_EVALUATION_CRITERIA)

    def test_zero_evaluation_universe_is_not_treated_as_a_failure(self):
        """With no mandatory failures either, the recommendation must be
        the distinct, non-alarming 'no evaluative criteria' value -- NOT
        MAJOR REVISION NEEDED, which would misrepresent a clean audit."""
        rec, rationale = analyst._derive_recommendation(None, [])
        self.assertEqual(rec, analyst._ALIGN_REC_NO_EVALUATIVE_CRITERIA)
        self.assertNotEqual(rec, "MAJOR REVISION NEEDED")
        self.assertIn("no numeric", rationale.lower())

    def test_mandatory_failure_still_overrides_even_with_zero_evaluation_universe(self):
        rec, _ = analyst._derive_recommendation(None, [{"req_id": "M1"}])
        self.assertEqual(rec, "MAJOR REVISION NEEDED")

    def test_end_to_end_zero_evaluation_universe_is_a_complete_not_incomplete_audit(self):
        """Full orchestration: requirements exist, coverage is complete,
        but none are evaluative -- status must be 'complete', with
        preserved coverage/findings and a clear score_basis, never an
        'incomplete audit' message."""
        requirements = [
            _req("M1", category="Mandatory", description="Provide insurance certificate", weight=None),
            _req("C1", category="Commercial", description="Accept net-30 payment terms", weight=None),
        ]

        def fake_call(system, user, max_tokens=2048):
            if "requirement_assertions" in user:
                return _chunk_response(assertions=[
                    {"req_id": "M1", "coverage": "Fully Addressed", "confidence": "High", "evidence": "e"},
                    {"req_id": "C1", "coverage": "Fully Addressed", "confidence": "High", "evidence": "e"},
                ])
            return _synthesis_response(summary="No rated criteria in this procurement; all gates satisfied.")

        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment("x" * 5000, requirements, "context", {"title": "T", "client": "C"})

        self.assertEqual(result["status"], "complete")
        self.assertIsNone(result["overall_score"])
        self.assertEqual(result["score_basis"], analyst._ALIGN_SCORE_BASIS_NO_EVALUATION_CRITERIA)
        self.assertEqual(result["recommendation"], analyst._ALIGN_REC_NO_EVALUATIVE_CRITERIA)
        self.assertEqual(result["mandatory_failures"], [])
        # Coverage for both non-evaluative requirements is still preserved.
        self.assertEqual(len(result["requirement_coverage"]), 2)
        self.assertTrue(all(r["coverage"] == "Fully Addressed" for r in result["requirement_coverage"]))


class TestFailClosedBehavior(unittest.TestCase):
    def test_no_literal_synthetic_fallback_remains_in_source(self):
        source = inspect.getsource(analyst)
        self.assertNotIn('"overall_score": 50', source)
        self.assertNotIn("'overall_score': 50", source)

    def test_malformed_chunk_response_is_retried_then_skipped_not_trusted(self):
        attempts = {"n": 0}

        def fake_call(system, user, max_tokens=2048):
            if "requirement_assertions" in user:
                attempts["n"] += 1
                return "not valid json at all {{{"
            return _synthesis_response()

        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment("x" * 5000, [], "context", {"title": "T", "client": "C"})

        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["message"], analyst._ALIGN_INCOMPLETE_MESSAGE)
        self.assertGreaterEqual(attempts["n"], 2)  # one attempt + one bounded retry

    def test_truncated_chunk_response_is_never_trusted(self):
        def fake_call(system, user, max_tokens=2048):
            if "requirement_assertions" in user:
                return json.dumps({"chunk_findings": [], "requirement_assertions": [], "_truncated": True})
            return _synthesis_response()

        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment("x" * 5000, [], "context", {"title": "T", "client": "C"})

        self.assertEqual(result["status"], "incomplete")

    def test_partial_chunk_failure_fails_closed_but_preserves_partial_findings(self):
        """Instruction 2: any required chunk failing means coverage is
        not complete, so the result must be status=incomplete with no
        numeric score -- but findings/coverage successfully established
        from the chunks that DID succeed are still preserved and
        returned, not discarded."""
        import threading
        lock = threading.Lock()
        call_n = {"n": 0}

        def fake_call(system, user, max_tokens=2048):
            if "requirement_assertions" in user:
                with lock:
                    call_n["n"] += 1
                    n = call_n["n"]
                if n <= 2:  # one chunk's attempt + its one bounded retry both fail
                    return "garbage"
                return _chunk_response(
                    assertions=[{"req_id": "R1", "coverage": "Fully Addressed", "confidence": "High", "evidence": "e"}]
                )
            return _synthesis_response()

        proposal = "SECTION ONE\n" + ("x" * 9500) + "\nSECTION TWO\n" + ("y" * 9500)
        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment(proposal, [_req("R1")], "context", {"title": "T", "client": "C"})

        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result["overall_score"])
        self.assertGreater(result["coverage_metadata"]["failed_or_skipped_chunks"], 0)
        self.assertFalse(result["coverage_metadata"]["coverage_complete"])
        # The chunk that DID succeed still contributed real, preserved evidence.
        self.assertTrue(any(r["req_id"] == "R1" and r["coverage"] == "Fully Addressed"
                             for r in result["requirement_coverage"]))

    def test_ceiling_exceeded_sampled_proposal_cannot_expose_a_normal_score(self):
        """A document beyond the chunk ceiling is sampled representatively
        for diagnostic value, but since effective coverage never reaches
        the full-audit threshold, the result must be visibly incomplete
        -- no numeric score, no recommendation."""
        filler = "Our proposed methodology addresses the stated requirements in detail. "
        huge_proposal = (filler * (400000 // len(filler) + 1))[:400000]

        def fake_call(system, user, max_tokens=2048):
            if "requirement_assertions" in user:
                return _chunk_response()
            return _synthesis_response()

        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment(huge_proposal, [_req("R1")], "context", {"title": "T", "client": "C"})

        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result.get("overall_score"))
        self.assertIsNone(result.get("recommendation"))
        self.assertFalse(result["coverage_metadata"]["coverage_complete"])

    def test_missing_required_contract_field_fails_validation(self):
        incomplete = {
            "status": "complete", "overall_score": 80, "score_basis": "unweighted_structured",
            "score_rationale": "x", "recommendation": "SUBMIT AS-IS",
            "executive_summary": "x", "strengths": [], "findings": [],
            # "mandatory_failures" deliberately missing
            "requirement_coverage": [], "next_steps": [], "coverage_metadata": {},
        }
        self.assertFalse(analyst._validate_alignment_contract(incomplete))

    def test_empty_arrays_are_a_legitimate_complete_result(self):
        complete = {
            "status": "complete", "overall_score": 80, "score_basis": "unweighted_structured",
            "score_rationale": "x", "recommendation": "SUBMIT AS-IS",
            "executive_summary": "x", "strengths": [], "findings": [],
            "mandatory_failures": [], "requirement_coverage": [], "next_steps": [],
            "coverage_metadata": {},
        }
        self.assertTrue(analyst._validate_alignment_contract(complete))

    def test_empty_proposal_text_fails_closed(self):
        result = analyst.analyze_proposal_alignment("", [_req("R1")], "context", {"title": "T", "client": "C"})
        self.assertEqual(result["status"], "incomplete")


class TestCoverageSemantics(unittest.TestCase):
    def test_not_addressed_only_when_coverage_complete(self):
        requirements = [_req("R1"), _req("R2")]
        rows = analyst._aggregate_requirement_coverage(requirements, [], coverage_complete=True)
        self.assertTrue(all(r["coverage"] == "Not Addressed" for r in rows))

    def test_cannot_assess_when_coverage_incomplete(self):
        requirements = [_req("R1"), _req("R2")]
        rows = analyst._aggregate_requirement_coverage(requirements, [], coverage_complete=False)
        self.assertTrue(all(r["coverage"] == "Cannot Assess" for r in rows))

    def test_positive_evidence_wins_regardless_of_coverage_completeness(self):
        requirements = [_req("R1")]
        chunk_results = [{
            "chunk_label": "Section 1",
            "requirement_assertions": [{"req_id": "R1", "coverage": "Fully Addressed", "confidence": "High", "evidence": "e"}],
        }]
        rows = analyst._aggregate_requirement_coverage(requirements, chunk_results, coverage_complete=False)
        self.assertEqual(rows[0]["coverage"], "Fully Addressed")

    def test_strongest_assertion_across_chunks_wins(self):
        requirements = [_req("R1")]
        chunk_results = [
            {"chunk_label": "S1", "requirement_assertions": [{"req_id": "R1", "coverage": "Partially Addressed", "confidence": "Low", "evidence": "e1"}]},
            {"chunk_label": "S2", "requirement_assertions": [{"req_id": "R1", "coverage": "Fully Addressed", "confidence": "High", "evidence": "e2"}]},
        ]
        rows = analyst._aggregate_requirement_coverage(requirements, chunk_results, coverage_complete=True)
        self.assertEqual(rows[0]["coverage"], "Fully Addressed")
        self.assertEqual(rows[0]["evidence_location"], "S2")


class TestNarrativeSynthesisResilience(unittest.TestCase):
    def test_synthesis_failure_preserves_valid_deterministic_audit(self):
        def fake_call(system, user, max_tokens=2048):
            if "requirement_assertions" in user:
                return _chunk_response(assertions=[{"req_id": "R1", "coverage": "Fully Addressed", "confidence": "High", "evidence": "e"}])
            return "not valid json {{{"  # synthesis call fails

        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment("x" * 5000, [_req("R1")], "context", {"title": "T", "client": "C"})

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["overall_score"], 100.0)
        self.assertIn("unavailable", result["executive_summary"].lower())
        self.assertEqual(result["requirement_coverage"][0]["coverage"], "Fully Addressed")

    def test_extra_score_and_recommendation_fields_from_synthesis_are_ignored(self):
        """Instruction 4: the synthesis call must not be able to
        redefine the deterministic score/recommendation/coverage/
        mandatory-status fields. Even if the model includes them in its
        JSON response (ignoring the prompt's instruction not to), they
        must never reach the final result -- only the three permitted
        narrative keys may."""
        def fake_call(system, user, max_tokens=2048):
            if "requirement_assertions" in user:
                return _chunk_response(assertions=[{"req_id": "R1", "coverage": "Fully Addressed", "confidence": "High", "evidence": "e"}])
            # Synthesis response deliberately includes extra, forbidden fields.
            return json.dumps({
                "executive_summary": "legit summary",
                "strengths": ["legit strength"],
                "next_steps": [],
                "overall_score": 12,
                "recommendation": "MAJOR REVISION NEEDED",
                "score_basis": "Buyer-weighted evaluation criteria",
                "coverage_metadata": {"percentage_covered": 3},
                "mandatory_failures": [{"req_id": "FAKE"}],
            })

        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment("x" * 5000, [_req("R1")], "context", {"title": "T", "client": "C"})

        self.assertEqual(result["status"], "complete")
        # The real, deterministic score (100.0, since R1 was Fully
        # Addressed and is the only evaluation-set requirement) must win
        # -- never the synthesis call's invented 12.
        self.assertEqual(result["overall_score"], 100.0)
        self.assertNotEqual(result["overall_score"], 12)
        self.assertEqual(result["recommendation"], "SUBMIT AS-IS")
        self.assertNotEqual(result["mandatory_failures"], [{"req_id": "FAKE"}])
        self.assertEqual(result["executive_summary"], "legit summary")
        self.assertEqual(result["strengths"], ["legit strength"])

    def test_synthesize_narrative_return_value_has_only_the_three_permitted_keys(self):
        def fake_call(system, user, max_tokens=2048):
            return json.dumps({
                "executive_summary": "x", "strengths": [], "next_steps": [],
                "overall_score": 99, "recommendation": "SUBMIT AS-IS",
            })

        with patch("analyst._call", side_effect=fake_call):
            narrative = analyst._synthesize_narrative(
                "BID: T", 80.0, "SUBMIT AS-IS", [], [], [],
                {"percentage_covered": 100.0, "successful_chunks": 1, "chunk_count": 1},
            )
        self.assertEqual(set(narrative.keys()), {"executive_summary", "strengths", "next_steps"})


class TestConcurrentChunkProcessing(unittest.TestCase):
    """Instruction 3: chunk assessments run under bounded concurrency
    (not serial, not unbounded) -- proven by forcing artificial overlap
    via short sleeps and tracking the maximum number of simultaneously
    in-flight calls, while the total call count, deterministic
    aggregation order, and isolated per-chunk retry/fail-closed
    treatment are all unchanged."""

    def test_chunk_calls_run_concurrently_not_serially(self):
        import threading
        import time as _time

        lock = threading.Lock()
        state = {"current": 0, "max_seen": 0}

        def fake_call(system, user, max_tokens=2048):
            if "requirement_assertions" not in user:
                return _synthesis_response()
            with lock:
                state["current"] += 1
                state["max_seen"] = max(state["max_seen"], state["current"])
            _time.sleep(0.05)  # hold the "in-flight" window open so overlap is observable
            with lock:
                state["current"] -= 1
            return _chunk_response()

        proposal = "\n\n".join(f"SECTION {i}\n" + ("x" * 9000) for i in range(1, 9))  # 8 sections
        with patch("analyst._call", side_effect=fake_call):
            analyst.analyze_proposal_alignment(proposal, [], "context", {"title": "T", "client": "C"})

        self.assertGreater(state["max_seen"], 1, "chunk calls ran strictly serially -- no concurrency observed")
        self.assertLessEqual(state["max_seen"], analyst._ALIGN_CHUNK_CONCURRENCY,
                              "concurrency exceeded the configured bound")

    def test_total_call_count_is_unchanged_by_concurrency(self):
        """Concurrency must change wall-clock time only, never how many
        calls are made in total."""
        call_count = {"n": 0}

        def fake_call(system, user, max_tokens=2048):
            call_count["n"] += 1
            if "requirement_assertions" in user:
                return _chunk_response()
            return _synthesis_response()

        proposal = "\n\n".join(f"SECTION {i}\n" + ("x" * 9000) for i in range(1, 9))
        with patch("analyst._call", side_effect=fake_call):
            analyst.analyze_proposal_alignment(proposal, [], "context", {"title": "T", "client": "C"})

        # 8 sections -> up to 8 chunks (deterministic split may merge/differ
        # slightly), plus exactly 1 synthesis call, no retries needed.
        chunk_calls = call_count["n"] - 1
        self.assertGreaterEqual(chunk_calls, 1)
        self.assertLessEqual(call_count["n"], 2 * analyst._ALIGN_MAX_CHUNKS + 1)

    def test_aggregation_order_is_deterministic_regardless_of_completion_order(self):
        """Chunks must complete out of order under concurrency (later
        sections finishing before earlier ones) without corrupting the
        deterministic, index-ordered aggregation."""
        import random

        def fake_call(system, user, max_tokens=2048):
            if "requirement_assertions" not in user:
                return _synthesis_response()
            import time as _t
            _t.sleep(random.uniform(0, 0.03))  # randomize completion order
            return _chunk_response()

        proposal = "\n\n".join(f"SECTION {i}\n" + ("x" * 9000) for i in range(1, 7))
        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment(proposal, [], "context", {"title": "T", "client": "C"})

        sections = result["coverage_metadata"]["sections"]
        indices = [s["index"] for s in sections]
        self.assertEqual(indices, sorted(indices), "section metadata is not in deterministic index order")

    def test_one_chunk_failure_does_not_crash_concurrent_batch(self):
        def fake_call(system, user, max_tokens=2048):
            if "requirement_assertions" not in user:
                return _synthesis_response()
            if "SECTION 2" in user:
                raise RuntimeError("simulated transient failure")
            return _chunk_response()

        proposal = "\n\n".join(f"SECTION {i}\n" + ("x" * 9000) for i in range(1, 5))
        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment(proposal, [], "context", {"title": "T", "client": "C"})

        # One chunk erroring must not raise out of the whole batch --
        # it's isolated, recorded as failed, and the run still completes
        # (as incomplete, since coverage is now < 100%) rather than crashing.
        self.assertIn(result["status"], ("incomplete", "complete"))
        self.assertGreater(result["coverage_metadata"]["failed_or_skipped_chunks"], 0)


class TestStageCheckUsesCanonicalIntelligence(unittest.TestCase):
    def test_source_no_longer_passes_bid_notes_as_rfp_text(self):
        source = inspect.getsource(stage_check)
        self.assertNotIn('rfp_text=bid.get("notes"', source)

    def test_build_procurement_context_uses_brief_row_not_notes(self):
        brief_row = {
            "opportunity_type": "Standing Offer",
            "qualification_gates": ["Must hold ISO 9001"],
            "commercial_structure": "Fixed price with milestone payments",
        }
        context = stage_check._build_procurement_context(brief_row, [_req("M1", category="Mandatory")])
        self.assertIn("Standing Offer", context)
        self.assertIn("ISO 9001", context)
        self.assertIn("Mandatory Requirements Count: 1", context)

    def test_build_procurement_context_handles_empty_brief_gracefully(self):
        context = stage_check._build_procurement_context({}, [])
        self.assertTrue(context)
        self.assertIn("No canonical procurement intelligence", context)


def _mock_cols(spec, *args, **kwargs):
    count = spec if isinstance(spec, int) else (len(spec) if isinstance(spec, list) else 2)
    cols = []
    for _ in range(count):
        col = MagicMock()
        col.button.return_value = False
        col.form_submit_button.return_value = False
        col.checkbox.return_value = False
        col.download_button.return_value = False
        cols.append(col)
    return cols


def _mock_tabs(tab_list, *args, **kwargs):
    return [MagicMock() for _ in range(len(tab_list))]


_FAKE_TOKEN_AND_ORG = ("fake-access-token", "fake-organization-id")


class TestStageCheckRendering(unittest.TestCase):
    """Behavioral: calls the REAL page_check(bid_id) with a pre-stored
    align_result in session_state (st.button mocked False, so no new
    analysis is triggered -- only the stored result is rendered), proving
    the actual production rendering code -- not a stand-in -- shows each
    required section for a complete result, and only the fail-closed
    message for an incomplete one."""

    def setUp(self):
        import streamlit as st
        st.session_state.pop(stage_check._align_result_key(1), None)
        st.session_state.pop(stage_check._align_result_snapshot_key(1), None)

    def _render(self, align_data):
        import streamlit as st
        st.session_state[stage_check._align_result_key(1)] = align_data
        calls = []
        self.download_calls = []

        def fake_markdown(text, *a, **k):
            calls.append(str(text))

        def mock_cols_capturing(spec, *args, **kwargs):
            cols = _mock_cols(spec, *args, **kwargs)
            for col in cols:
                col.markdown.side_effect = fake_markdown
            return cols

        def fake_download_button(label, *args, **kwargs):
            self.download_calls.append({"label": label, "file_name": kwargs.get("file_name"), "data": kwargs.get("data")})
            return False

        with patch("streamlit.markdown", side_effect=fake_markdown), \
             patch("streamlit.columns", side_effect=mock_cols_capturing), \
             patch("streamlit.tabs", side_effect=_mock_tabs), \
             patch("streamlit.button", return_value=False), \
             patch("streamlit.download_button", side_effect=fake_download_button), \
             patch("streamlit.file_uploader", return_value=None), \
             patch("pages.stage_check.tenancy.get_bid_authenticated") as mock_bid, \
             patch("pages.stage_check.tenancy.get_requirements_authenticated", return_value=[]), \
             patch("pages.stage_check.tenancy.get_documents_authenticated", return_value=[]), \
             patch("pages.stage_check.tenancy.get_outline_authenticated", return_value=[]), \
             patch("pages.stage_check.tenancy.get_clarifications_authenticated", return_value=[]), \
             patch("pages.stage_check.tenancy.get_bid_brief_authenticated", return_value={}), \
             patch("pages.stage_check._current_access_token_and_org", return_value=_FAKE_TOKEN_AND_ORG), \
             patch("pdf_export.generate_compliance_pdf", return_value=b""):
            mock_bid.return_value = {
                "id": 1, "client": "Test Buyer", "title": "Test RFP", "stage": "Check",
                "sensitivity": "Standard", "submission_deadline": None, "clarification_deadline": None,
                "value_cad": None, "owner": None,
            }
            stage_check.page_check(1)
        return "\n".join(calls)

    def test_incomplete_result_shows_fail_closed_message_and_no_score(self):
        rendered = self._render({"status": "incomplete", "message": "x", "reason": "totally failed", "coverage_metadata": {}})
        self.assertIn("no reliable score available", rendered)
        self.assertIn("totally failed", rendered)
        self.assertNotIn("Alignment Score", rendered)
        # Export must still be offered for an incomplete result.
        self.assertEqual(len(self.download_calls), 1)
        self.assertIn("Download Alignment Audit Report", self.download_calls[0]["label"])

    def test_incomplete_result_still_shows_preserved_partial_findings_and_coverage(self):
        """Instruction 2: partial positive findings/coverage established
        from successfully-analyzed sections are preserved and shown even
        when the overall audit is incomplete -- just without a score."""
        align_data = {
            "status": "incomplete", "message": "x", "reason": "coverage below threshold",
            "overall_score": None, "recommendation": None, "executive_summary": None,
            "strengths": [], "next_steps": [], "mandatory_failures": [],
            "findings": [{"title": "Partial finding from analyzed section", "issue": "gap"}],
            "requirement_coverage": [{"req_id": "R1", "coverage": "Fully Addressed"}],
            "coverage_metadata": {"percentage_covered": 40.0, "chunk_count": 5, "successful_chunks": 2},
        }
        rendered = self._render(align_data)
        self.assertNotIn("Alignment Score", rendered)
        self.assertIn("Partial finding from analyzed section", rendered)
        self.assertIn("Fully Addressed", rendered)

    def test_incomplete_result_names_files_skipped_by_the_package_ceiling(self):
        """Pre-commit hardening item 4: a file the package-wide chunk
        ceiling gave zero analyzed sections to must be named explicitly
        in the CHECK UI -- never left for the user to infer from counts
        alone."""
        align_data = {
            "status": "incomplete", "message": "x", "reason": "coverage below threshold",
            "overall_score": None, "recommendation": None, "executive_summary": None,
            "strengths": [], "next_steps": [], "mandatory_failures": [],
            "findings": [], "requirement_coverage": [],
            "coverage_metadata": {
                "percentage_covered": 40.0, "chunk_count": 24, "successful_chunks": 24,
                "skipped_files": [{"file_id": "f9", "filename": "Team CVs.pdf"}],
            },
        }
        rendered = self._render(align_data)
        self.assertIn("Not fully analyzed", rendered)
        self.assertIn("Team CVs.pdf", rendered)

    def test_findings_section_renamed_to_audit_findings_with_severity_counts_and_new_sections(self):
        """Findings-layer remediation: 'Critical Findings' is renamed to
        'Audit Findings' (the list contains Critical/High/Medium/Low, not
        only Critical) with a severity summary count line; Priority
        Actions Before Submission and Needs Verification / Cannot Assess
        render as their own distinct sections."""
        align_data = {
            "status": "complete", "overall_score": 78.0, "score_basis": "Buyer-weighted evaluation criteria",
            "score_rationale": "78/100.", "recommendation": "REVISE BEFORE SUBMITTING",
            "executive_summary": "Solid overall.",
            "findings": [{"severity": "Medium", "stage": "Proposal Submission", "title": "Weak safeguards",
                          "issue": "Safeguards described are insufficient.", "req_id": "M2",
                          "proposal_location": "Schedule A.pdf", "recommendation": "Strengthen safeguards.",
                          "effort": "Moderate rewrite"}],
            "unresolved_items": [{"req_id": "M5", "category": "Mandatory", "description": "Insurance declaration",
                                   "reason": "M5 — Insurance declaration could not be assessed because relevant "
                                             "package sections were not successfully analyzed."}],
            "priority_actions": [{"source": "finding", "severity": "Medium", "req_id": "M2",
                                   "title": "Weak safeguards", "detail": "Safeguards described are insufficient.",
                                   "recommendation": "Strengthen safeguards."}],
            "mandatory_failures": [],
            "requirement_coverage": [{"req_id": "M2", "category": "Mandatory", "coverage": "Partially Addressed",
                                       "confidence": "Medium", "evidence_location": "Schedule A.pdf", "notes": "x"}],
            "strengths": [], "next_steps": [],
            "coverage_metadata": {"chars_total": 1000, "chars_processed": 1000, "percentage_covered": 100.0,
                                   "chunk_count": 1, "successful_chunks": 1, "failed_or_skipped_chunks": 0},
        }
        rendered = self._render(align_data)
        self.assertIn("Audit Findings", rendered)
        self.assertNotIn("Critical Findings", rendered)
        self.assertIn("Priority Actions Before Submission", rendered)
        self.assertIn("Needs Verification", rendered)
        self.assertIn("Insurance declaration", rendered)

    def test_complete_result_renders_every_required_section(self):
        align_data = {
            "status": "complete", "overall_score": 72.0, "score_basis": "unweighted_structured",
            "score_rationale": "72/100 structured alignment score.", "recommendation": "REVISE BEFORE SUBMITTING",
            "executive_summary": "Overall solid alignment with some gaps.",
            "findings": [{"severity": "High", "title": "Missing insurance evidence", "issue": "no cert found",
                          "req_id": "M2", "proposal_location": "Section 3", "recommendation": "attach cert", "effort": "Minor edit"}],
            "mandatory_failures": [{"req_id": "M1", "description": "Insurance certificate", "reason": "not found anywhere"}],
            "requirement_coverage": [{"req_id": "R1", "category": "Rated", "coverage": "Fully Addressed",
                                       "confidence": "High", "evidence_location": "Section 2", "notes": "covered"}],
            "strengths": ["Clear methodology"],
            "next_steps": [{"priority": 1, "action": "Add insurance certificate", "rationale": "mandatory gap", "when": "Before submission"}],
            "coverage_metadata": {"chars_total": 1000, "chars_processed": 1000, "percentage_covered": 100.0,
                                   "chunk_count": 1, "successful_chunks": 1, "failed_or_skipped_chunks": 0},
        }
        rendered = self._render(align_data)
        self.assertIn("Overall solid alignment with some gaps.", rendered)
        self.assertIn("Missing insurance evidence", rendered)
        self.assertIn("MANDATORY", rendered)
        self.assertIn("not found anywhere", rendered)
        self.assertIn("Fully Addressed", rendered)
        self.assertIn("Clear methodology", rendered)
        self.assertIn("Add insurance certificate", rendered)
        self.assertEqual(len(self.download_calls), 1)
        download_pdf_bytes = self.download_calls[0]["data"]
        self.assertTrue(download_pdf_bytes.startswith(b"%PDF-"))
        self.assertTrue(self.download_calls[0]["file_name"].startswith("Alignment_Audit_Test_Buyer"))
        self.assertTrue(self.download_calls[0]["file_name"].endswith(".pdf"))

    def test_zero_evaluation_universe_renders_as_understandable_not_an_error(self):
        """Instruction 2: renders as a real 'complete' result -- score
        card shows N/A with the distinct, non-alarming recommendation
        text -- never the fail-closed 'no reliable score available'
        message, which is reserved for genuinely incomplete audits."""
        align_data = {
            "status": "complete", "overall_score": None,
            "score_basis": analyst._ALIGN_SCORE_BASIS_NO_EVALUATION_CRITERIA,
            "score_rationale": "No evaluative criteria in this procurement.",
            "recommendation": analyst._ALIGN_REC_NO_EVALUATIVE_CRITERIA,
            "executive_summary": "No rated criteria in this procurement; all gates satisfied.",
            "findings": [], "mandatory_failures": [],
            "requirement_coverage": [{"req_id": "M1", "category": "Mandatory", "coverage": "Fully Addressed",
                                       "confidence": "High", "evidence_location": "Section 1", "notes": "covered"}],
            "strengths": [], "next_steps": [],
            "coverage_metadata": {"chars_total": 1000, "chars_processed": 1000, "percentage_covered": 100.0,
                                   "chunk_count": 1, "successful_chunks": 1, "failed_or_skipped_chunks": 0},
        }
        rendered = self._render(align_data)
        self.assertNotIn("no reliable score available", rendered)
        self.assertIn("N/A", rendered)
        self.assertIn(analyst._ALIGN_SCORE_BASIS_NO_EVALUATION_CRITERIA, rendered)
        self.assertIn("Fully Addressed", rendered)


if __name__ == "__main__":
    unittest.main()
