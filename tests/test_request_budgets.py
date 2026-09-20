"""
tests/test_request_budgets.py

Phase 5A instruction 16: deterministic tests that fail when STATIC
prompt/schema/instruction overhead grows materially without deliberate
acknowledgement. These re-measure the live module-level constants
directly (SYSTEM prompts, schema text, fixed instructions) against
docs/current/REQUEST_BUDGETS.json's baseline -- never dynamic
buyer/RFP/proposal text, which naturally varies with real documents and
is intentionally NOT budgeted (see that file's own "methodology" notes).

A failure here means a static constant grew past its warning/hard
threshold -- either a deliberate edit that should update the baseline in
REQUEST_BUDGETS.json, or accidental prompt bloat (e.g. a duplicated
block) that should be fixed instead.
"""
import json
import unittest
from pathlib import Path

_BUDGETS_PATH = Path(__file__).resolve().parents[1] / "docs" / "current" / "REQUEST_BUDGETS.json"


def _load_budgets():
    return json.loads(_BUDGETS_PATH.read_text(encoding="utf-8"))


def _static_bytes_now(workflow: str, operation: str) -> int:
    """Re-measures the CURRENT live static-field bytes for one
    (workflow, operation), independent of the profiler CLI -- reads the
    real module constants directly, the same way REQUEST_BUDGETS.json's
    baseline was originally produced."""
    if workflow == "section_analyzer" and operation == "formative_review":
        import section_analyzer as sa
        ctx = {
            "section_title": "T", "section_guidance": "", "section_text": "", "word_limit": None,
            "requirements": [], "qualification_mechanisms": [], "tie_break_rules": [],
            "buyer_intelligence": {}, "procurement_basis": {"procurement_truth_status": "governed",
                                                             "advisory_intelligence_available": True,
                                                             "advisory_unavailable_reason": None},
        }
        _, components = sa._analyzer_prompt(ctx, return_components=True)
        return len(sa._ANALYZER_SYSTEM.encode("utf-8")) + len(components["instructions"].encode("utf-8"))
    if workflow == "fast_analysis" and operation == "initial":
        import fast_analysis as fa
        route = next(iter(fa._ROUTE_SCHEMAS))
        schema_text = fa._ROUTE_SCHEMAS[route]
        prompt = fa._build_prompt(route, "f.pdf", "")
        marker = "\n\nDOCUMENT TO PROCESS (f.pdf):\n"
        header = prompt[: prompt.index(marker)]
        return len(header.encode("utf-8"))
    if workflow == "deep_verify" and operation == "initial":
        import extractor as ex
        return len(ex.STAGE_A_FACT_EXTRACTION_PROMPT.encode("utf-8"))
    if workflow == "deep_verify" and operation == "stage_d_synthesis":
        import stage_d_projection as sdp
        return len(sdp.SYNTHESIS_PROMPT.encode("utf-8"))
    if workflow == "analyst":
        import analyst
        const_by_operation = {
            "compliance_review": analyst.COMPLIANCE_SYSTEM,
            "missing_evidence": analyst.EVIDENCE_SYSTEM,
            "clarification_questions": analyst.CLARIFICATION_SYSTEM,
            "bid_no_bid_score": analyst.BID_NOBID_SYSTEM,
            "past_proposal_analysis": analyst.PROPOSAL_ANALYZER_SYSTEM,
            "draft_proposal_section": analyst.DRAFTER_SYSTEM,
            "submission_readiness_check": analyst.READINESS_SYSTEM,
            "addendum_analysis": analyst.ADDENDUM_SYSTEM,
            "proposal_alignment_chunk": analyst._ALIGN_CHUNK_SYSTEM,
            "proposal_alignment_synthesis": analyst._ALIGN_SYNTHESIS_SYSTEM,
            "procurement_change_proposal": analyst._PROCUREMENT_CHANGE_SYSTEM,
        }
        return len(const_by_operation[operation].encode("utf-8"))
    raise AssertionError(f"no live measurement wired up for {workflow}/{operation}")


class TestRequestBudgetsFileIsWellFormed(unittest.TestCase):

    def test_budgets_file_exists_and_parses(self):
        budgets = _load_budgets()
        self.assertIn("budgets", budgets)
        self.assertGreater(len(budgets["budgets"]), 0)

    def test_every_entry_has_consistent_thresholds(self):
        for entry in _load_budgets()["budgets"]:
            baseline = entry["baseline_static_bytes"]
            warning = entry["warning_threshold_bytes"]
            hard = entry["hard_regression_threshold_bytes"]
            label = f"{entry['workflow']}/{entry['operation']}"
            self.assertLessEqual(baseline, warning, label)
            self.assertLess(warning, hard, label)


class TestStaticOverheadHasNotRegressed(unittest.TestCase):
    """One test per budgeted (workflow, operation): fails if the live
    static bytes exceed the hard_regression_threshold_bytes recorded in
    docs/current/REQUEST_BUDGETS.json."""

    def test_all_budgeted_operations_are_within_hard_threshold(self):
        failures = []
        for entry in _load_budgets()["budgets"]:
            label = f"{entry['workflow']}/{entry['operation']}"
            current = _static_bytes_now(entry["workflow"], entry["operation"])
            if current > entry["hard_regression_threshold_bytes"]:
                failures.append(
                    f"{label}: current static bytes {current} exceeds hard_regression_threshold_bytes "
                    f"{entry['hard_regression_threshold_bytes']} (baseline was {entry['baseline_static_bytes']})")
        self.assertEqual(failures, [], "\n".join(failures))

    def test_all_budgeted_operations_match_their_recorded_baseline_exactly(self):
        """Tighter than the hard-regression gate: today's static bytes
        should equal the recorded baseline exactly, since these are fixed
        module constants that changed only if someone deliberately edited
        them. A mismatch here is not necessarily a bug -- it may mean
        REQUEST_BUDGETS.json's baseline needs a deliberate update -- but
        it must never pass silently."""
        mismatches = []
        for entry in _load_budgets()["budgets"]:
            label = f"{entry['workflow']}/{entry['operation']}"
            current = _static_bytes_now(entry["workflow"], entry["operation"])
            if current != entry["baseline_static_bytes"]:
                mismatches.append(f"{label}: current={current} baseline={entry['baseline_static_bytes']}")
        self.assertEqual(mismatches, [], "\n".join(mismatches))


if __name__ == "__main__":
    unittest.main()
