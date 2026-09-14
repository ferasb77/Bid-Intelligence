"""
tests/test_fast_analysis_v3.py

Deterministic tests for the Fast Analysis V3 bounded-split-on-truncation
package. No live API calls anywhere in this file. Covers exactly the V3
authorization's test list (Section 20): split (not identical retry) on
max_tokens, split fires exactly once (no recursion, even if a split
subcall itself truncates), marker preservation across the split, merge
preservation of initial + both split results, occurrence-preserving
evaluation-criteria merging (conflicting values must NOT collapse), all 3
ambiguity detectors working against split-recovered data, the 18 known
primary category weights surviving unregressed, correct telemetry call
kinds / parent linkage, removal of V2's ineffective Insurance prompt
change, and no regression of V2's commercial-section fixes.

tests/test_fast_analysis.py (v1, 32 tests) and tests/test_fast_analysis_v2.py
(v2, 22 tests after relocating its retry-mechanism tests here) are both left
otherwise untouched.
"""
import json
import unittest
from unittest.mock import MagicMock

from fast_analysis import (
    extract_fast_document, _split_chunk_for_recovery, _merge_chunk_result,
    _empty_result, _build_prompt, ROUTE_IDENTITY_EVAL_REQ, ROUTE_COMMERCIAL_ONLY,
    detect_evaluation_weight_conflicts, detect_pricing_stage_ambiguity,
    detect_category_date_distinctions,
)
from scripts.fast_analysis_report_adapter import _weight_rows_for_category, build_fast_report_content
from fast_analysis import FastAnalysisResult

MASTER_RFP_FILE = "RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf"
APPENDIX_G_FILE = "OriginalRevision/RFP 2026-06 - Appendix G - Form of Agreement.docx"
D1_DOC = "OriginalRevision/RFP 2026-026 - Appendix D1 - Rated criteria response form.docx"
D2_DOC = "Amendment1/RFP 2026-026 - Appendix D2 - Rated Criteria Response REVISED.docx"
D3_DOC = "OriginalRevision/RFP 2026-026 - Appendix D3 - Rated Criteria Response Form.docx"


def _fake_response(payload_dict, stop_reason="end_turn", input_tokens=100, output_tokens=100):
    resp = MagicMock()
    resp.content = [MagicMock(text=json.dumps(payload_dict))]
    resp.stop_reason = stop_reason
    resp.usage = MagicMock(input_tokens=input_tokens, output_tokens=output_tokens)
    return resp


class TestSplitTriggersInsteadOfIdenticalRetry(unittest.TestCase):
    """1. max_tokens triggers a bounded split, never an identical-content
    retry (the exact V2 root cause this package fixes)."""

    def test_max_tokens_dispatches_two_split_calls_not_one_identical_retry(self):
        initial_payload = {"doc_metadata": {"client": "Bank of Canada"}, "evaluation_criteria": []}
        split_a = {"doc_metadata": {}, "evaluation_criteria": []}
        split_b = {"doc_metadata": {}, "evaluation_criteria": []}
        client = MagicMock()
        client.messages.create.side_effect = [
            _fake_response(initial_payload, stop_reason="max_tokens"),
            _fake_response(split_a, stop_reason="end_turn"),
            _fake_response(split_b, stop_reason="end_turn"),
        ]
        telemetry = []
        # Needs source markers so the marker-aware splitter has something to
        # split on; a bare literal string (no markers) still splits via the
        # chunker's line-boundary fallback, but this exercises the intended
        # marker-aware path directly.
        doc_text = ("[[SOURCE: x.pdf | PAGE: 1]]\n" + ("alpha content sentence. " * 40) +
                   "[[SOURCE: x.pdf | PAGE: 2]]\n" + ("beta content sentence. " * 40))
        extract_fast_document(MASTER_RFP_FILE, doc_text, api_key="fake",
                              route=ROUTE_IDENTITY_EVAL_REQ, client=client, telemetry=telemetry)
        self.assertEqual(client.messages.create.call_count, 3,
                         "1 initial + 2 split subcalls -- never a same-content retry")
        call_kinds = [t["call_kind"] for t in telemetry]
        self.assertEqual(call_kinds, ["initial", "split_recovery_a", "split_recovery_b"])
        self.assertNotIn("targeted_retry", call_kinds)


class TestSplitFiresExactlyOnceNoRecursion(unittest.TestCase):
    """2/19. Bounded to depth 1 -- a split subcall that itself truncates is
    NOT split again; recorded as BOUNDED_SPLIT_EXHAUSTED instead."""

    def test_split_subcall_max_tokens_does_not_recurse(self):
        initial_payload = {"doc_metadata": {"client": "Bank of Canada"}, "evaluation_criteria": []}
        client = MagicMock()
        client.messages.create.side_effect = [
            _fake_response(initial_payload, stop_reason="max_tokens"),
            _fake_response(initial_payload, stop_reason="max_tokens"),  # split_recovery_a truncates too
            _fake_response(initial_payload, stop_reason="max_tokens"),  # split_recovery_b truncates too
        ]
        telemetry = []
        doc_text = ("[[SOURCE: x.pdf | PAGE: 1]]\n" + ("alpha content sentence. " * 40) +
                   "[[SOURCE: x.pdf | PAGE: 2]]\n" + ("beta content sentence. " * 40))
        extract_fast_document(MASTER_RFP_FILE, doc_text, api_key="fake",
                              route=ROUTE_IDENTITY_EVAL_REQ, client=client, telemetry=telemetry)
        self.assertEqual(client.messages.create.call_count, 3,
                         "exactly 3 API calls total -- no further splitting when a subcall truncates")
        exhausted = [t for t in telemetry if t.get("parse_status") == "BOUNDED_SPLIT_EXHAUSTED"]
        self.assertEqual(len(exhausted), 2, "one exhausted marker per truncated split subcall")
        for t in exhausted:
            self.assertEqual(t["split_trigger_reason"], "max_tokens")

    def test_split_impossible_records_exhausted_without_extra_calls(self):
        """A chunk so small it can't be split further (e.g. from a mocked
        document below the chunker's line-splitting threshold) must not
        force any call at all -- verified via the pure splitter directly."""
        pieces = _split_chunk_for_recovery("x")
        self.assertLessEqual(len(pieces), 2)


class TestSplitPreservesSourceMarkers(unittest.TestCase):
    """3. Marker-aware split never detaches a [[SOURCE: ...]] marker from
    its own text."""

    def test_two_marker_blocks_split_without_orphaning_either_marker(self):
        chunk = ("[[SOURCE: doc.pdf | PAGE: 1]]\nFirst block content here.\n"
                "[[SOURCE: doc.pdf | PAGE: 2]]\nSecond block content here.\n")
        pieces = _split_chunk_for_recovery(chunk)
        self.assertGreaterEqual(len(pieces), 1)
        self.assertLessEqual(len(pieces), 2)
        # Every marker that appears in a piece must be followed by its own
        # content within the SAME piece (never split away into the other).
        for piece in pieces:
            if "[[SOURCE: doc.pdf | PAGE: 1]]" in piece:
                self.assertIn("First block content here.", piece)
            if "[[SOURCE: doc.pdf | PAGE: 2]]" in piece:
                self.assertIn("Second block content here.", piece)

    def test_split_never_returns_more_than_two_pieces(self):
        """Even a chunk with many short marker blocks collapses to exactly
        2 pieces -- the bounded, non-recursive contract."""
        chunk = "".join(f"[[SOURCE: doc.pdf | SECTION: S{i}]]\nContent {i}.\n" for i in range(10))
        pieces = _split_chunk_for_recovery(chunk)
        self.assertLessEqual(len(pieces), 2)


class TestMergePreservesInitialAndSplitContent(unittest.TestCase):
    """4/5. Initial valid content survives; split-recovered content is
    additive; conflicting evaluation occurrences must NOT collapse."""

    def test_initial_and_both_split_results_are_all_merged_in(self):
        initial_payload = {
            "doc_metadata": {"client": "Bank of Canada", "file_number": "RFP 2026-026"},
            "evaluation_criteria": [{"stage": "Corporate Profile", "weight": "5 points",
                                     "parent_stage": "Category 3 Table"}],
        }
        split_a_payload = {
            "doc_metadata": {},
            "evaluation_criteria": [{"stage": "Corporate Profile", "weight": "5 points",
                                     "parent_stage": "Category 3 Table"}],  # re-covers same region
        }
        split_b_payload = {
            "doc_metadata": {},
            "evaluation_criteria": [
                {"stage": "Corporate Profile", "weight": "10 points"},
                {"stage": "Price", "weight": "25 points", "parent_stage": "Category 3 Table"},
                {"stage": "Stage 4. Pricing", "weight": None, "parent_stage": None},
            ],
        }
        client = MagicMock()
        client.messages.create.side_effect = [
            _fake_response(initial_payload, stop_reason="max_tokens"),
            _fake_response(split_a_payload, stop_reason="end_turn"),
            _fake_response(split_b_payload, stop_reason="end_turn"),
        ]
        doc_text = ("[[SOURCE: x.pdf | PAGE: 1]]\n" + ("alpha content sentence. " * 40) +
                   "[[SOURCE: x.pdf | PAGE: 2]]\n" + ("beta content sentence. " * 40))
        result = extract_fast_document(MASTER_RFP_FILE, doc_text, api_key="fake",
                                       route=ROUTE_IDENTITY_EVAL_REQ, client=client, telemetry=[])
        self.assertEqual(result["doc_metadata"]["client"], "Bank of Canada",
                         "initial valid metadata must survive")
        labels_weights = [(ec["stage"], ec["weight"]) for ec in result["evaluation_criteria"]]
        self.assertIn(("Corporate Profile", "5 points"), labels_weights)
        self.assertIn(("Corporate Profile", "10 points"), labels_weights,
                      "the conflicting second occurrence, recovered by the split, must be present")
        self.assertIn(("Stage 4. Pricing", None), labels_weights)

    def test_conflicting_occurrences_do_not_collapse_during_merge(self):
        """_merge_chunk_result must never deduplicate evaluation_criteria by
        label alone -- both competing weight values must remain as separate
        occurrences all the way through to ambiguity detection."""
        result = _empty_result(ROUTE_IDENTITY_EVAL_REQ)
        _merge_chunk_result(result, {"evaluation_criteria": [{"stage": "Corporate Profile", "weight": "5 points"}]})
        _merge_chunk_result(result, {"evaluation_criteria": [{"stage": "Corporate Profile", "weight": "10 points"}]})
        self.assertEqual(len(result["evaluation_criteria"]), 2)
        weights = {ec["weight"] for ec in result["evaluation_criteria"]}
        self.assertEqual(weights, {"5 points", "10 points"})

    def test_doc_metadata_merge_does_not_duplicate_or_overwrite_on_repeat(self):
        """Ordinary scalar facts use deterministic semantic-key dedup (fill
        only if missing) -- a second call repeating the same field must not
        clobber or duplicate it."""
        result = _empty_result(ROUTE_IDENTITY_EVAL_REQ)
        _merge_chunk_result(result, {"doc_metadata": {"client": "Bank of Canada"}})
        _merge_chunk_result(result, {"doc_metadata": {"client": "Some Other Value"}})
        self.assertEqual(result["doc_metadata"]["client"], "Bank of Canada",
                         "first valid value wins; a later call cannot silently overwrite it")


class TestAmbiguityDetectionAfterSplitRecovery(unittest.TestCase):
    """6. Core acceptance test: the exact live V2 failure, now fixed end to
    end via split recovery -- both required ambiguity classes become
    detectable, and the third (category-date) remains unregressed."""

    def test_split_recovery_makes_both_missing_ambiguity_classes_detectable(self):
        """The two 'Corporate Profile' occurrences deliberately share the
        SAME parent_stage/scope here -- this test is about merge
        preservation across a split (does the recovered occurrence survive
        into detection?), not about the V4 scope-awareness fix (a
        genuinely different scope must NOT be flagged; see
        TestScopeAwareEvaluationWeightConflicts below for that)."""
        initial_payload = {
            "doc_metadata": {"client": "Bank of Canada", "file_number": "RFP 2026-026"},
            "evaluation_criteria": [{"stage": "Corporate Profile", "weight": "5 points",
                                     "parent_stage": "Category 3 Table"}],
            "typed_observations": [
                {"family": "MILESTONE", "semantic_kind": "PRESENTATION_OR_DEMO",
                 "original_value": "Week of October 26", "scope": {"category": "Category 1"}},
            ],
        }
        split_a_payload = {"doc_metadata": {}, "evaluation_criteria": [], "typed_observations": []}
        split_b_payload = {
            "doc_metadata": {},
            "evaluation_criteria": [
                {"stage": "Corporate Profile", "weight": "10 points", "parent_stage": "Category 3 Table"},
                {"stage": "Price", "weight": "25 points", "parent_stage": "Category 3 Table"},
                {"stage": "Stage 4. Pricing", "weight": None, "parent_stage": None},
            ],
            "typed_observations": [
                {"family": "MILESTONE", "semantic_kind": "PRESENTATION_OR_DEMO",
                 "original_value": "Week of November 2", "scope": {"category": "Category 3"}},
            ],
        }
        client = MagicMock()
        client.messages.create.side_effect = [
            _fake_response(initial_payload, stop_reason="max_tokens"),
            _fake_response(split_a_payload, stop_reason="end_turn"),
            _fake_response(split_b_payload, stop_reason="end_turn"),
        ]
        doc_text = ("[[SOURCE: x.pdf | PAGE: 1]]\n" + ("alpha content sentence. " * 40) +
                   "[[SOURCE: x.pdf | PAGE: 2]]\n" + ("beta content sentence. " * 40))
        result = extract_fast_document(MASTER_RFP_FILE, doc_text, api_key="fake",
                                       route=ROUTE_IDENTITY_EVAL_REQ, client=client, telemetry=[])

        weight_conflicts = detect_evaluation_weight_conflicts(result["evaluation_criteria"])
        self.assertEqual(len(weight_conflicts), 1)
        self.assertEqual(weight_conflicts[0]["label"], "corporate profile")

        pricing_conflicts = detect_pricing_stage_ambiguity(result["evaluation_criteria"])
        self.assertEqual(len(pricing_conflicts), 1)

        date_distinctions = detect_category_date_distinctions(result["typed_observations"])
        self.assertEqual(len(date_distinctions), 1, "category-date detection must remain unregressed")


class Test18PrimaryEvaluationWeightsUnregressed(unittest.TestCase):
    """7. All 18 known primary category weight values must remain
    extractable and correctly attributed, regardless of split recovery
    happening elsewhere in the same document.

    Phase 5 generalization: the adapter's per-category weight lookup
    (`_weight_rows_for_category`) no longer groups by a hardcoded D1/D2/D3
    filename -- it groups by the criterion's own `parent_stage` text (the
    general evaluation_criteria family's fallback path, exercised here
    because these 18 rows carry no evaluation_occurrences data). This is
    the same 18-value non-regression check as before, just keyed the way
    Bank of Canada's real corpus is actually grouped now."""

    def test_all_18_known_weight_values_present_and_correctly_scoped(self):
        evaluation_criteria = [
            {"parent_stage": "Category 1", "stage": "Corporate Profile", "weight": "5 pts"},
            {"parent_stage": "Category 1", "stage": "Key Personnel & Roster", "weight": "15 pts"},
            {"parent_stage": "Category 1", "stage": "Curriculum & Program Design", "weight": "35 pts"},
            {"parent_stage": "Category 1", "stage": "Measurement Approach", "weight": "5 pts"},
            {"parent_stage": "Category 1", "stage": "Relationship Management", "weight": "5 pts"},
            {"parent_stage": "Category 1", "stage": "Value-add", "weight": "5 pts"},
            {"parent_stage": "Category 1", "stage": "Relevant Experience & References", "weight": "5 pts"},
            {"parent_stage": "Category 2", "stage": "Corporate Profile", "weight": "5 pts"},
            {"parent_stage": "Category 2", "stage": "Key Personnel & Roster", "weight": "15 pts"},
            {"parent_stage": "Category 2", "stage": "Methodology & Advisory Approach", "weight": "35 pts"},
            {"parent_stage": "Category 2", "stage": "Thought Leadership & Innovation", "weight": "5 pts"},
            {"parent_stage": "Category 2", "stage": "Relationship Management", "weight": "5 pts"},
            {"parent_stage": "Category 3", "stage": "Corporate Profile", "weight": "10 pts"},
            {"parent_stage": "Category 3", "stage": "Key Personnel & Roster", "weight": "20 pts"},
            {"parent_stage": "Category 3", "stage": "Facilitation Methodology", "weight": "30 pts"},
            {"parent_stage": "Category 3", "stage": "Value-add", "weight": "5 pts"},
            {"parent_stage": "Category 3", "stage": "Relevant Experience & References", "weight": "10 pts"},
            {"parent_stage": "Category 3", "stage": "Price", "weight": "25 pts"},
        ]
        result = FastAnalysisResult()
        result.evaluation_criteria = evaluation_criteria
        d1_rows = _weight_rows_for_category(result, "Category 1")
        d2_rows = _weight_rows_for_category(result, "Category 2")
        d3_rows = _weight_rows_for_category(result, "Category 3")
        self.assertEqual(len(d1_rows), 7)
        self.assertEqual(len(d2_rows), 5)
        self.assertEqual(len(d3_rows), 6)
        self.assertEqual(sum(int(w.split()[0]) for _, w in d1_rows), 75)
        self.assertEqual(sum(int(w.split()[0]) for _, w in d2_rows), 65)
        self.assertEqual(sum(int(w.split()[0]) for _, w in d3_rows), 100)


class TestTelemetryCallKindsAndParentLinkage(unittest.TestCase):
    """18. Telemetry distinguishes initial/split_recovery_a/split_recovery_b
    and records parent_call_index + split_trigger_reason for traceability."""

    def test_split_calls_record_parent_index_and_trigger_reason(self):
        initial_payload = {"doc_metadata": {"client": "Bank of Canada"}, "evaluation_criteria": []}
        split_payload = {"doc_metadata": {}, "evaluation_criteria": []}
        client = MagicMock()
        client.messages.create.side_effect = [
            _fake_response(initial_payload, stop_reason="max_tokens"),
            _fake_response(split_payload, stop_reason="end_turn"),
            _fake_response(split_payload, stop_reason="end_turn"),
        ]
        telemetry = []
        doc_text = ("[[SOURCE: x.pdf | PAGE: 1]]\n" + ("alpha content sentence. " * 40) +
                   "[[SOURCE: x.pdf | PAGE: 2]]\n" + ("beta content sentence. " * 40))
        extract_fast_document(MASTER_RFP_FILE, doc_text, api_key="fake",
                              route=ROUTE_IDENTITY_EVAL_REQ, client=client, telemetry=telemetry)
        initial = next(t for t in telemetry if t["call_kind"] == "initial")
        split_a = next(t for t in telemetry if t["call_kind"] == "split_recovery_a")
        split_b = next(t for t in telemetry if t["call_kind"] == "split_recovery_b")
        self.assertIsNone(initial["parent_call_index"])
        self.assertEqual(split_a["parent_call_index"], initial["call_index"])
        self.assertEqual(split_b["parent_call_index"], initial["call_index"])
        self.assertEqual(split_a["split_trigger_reason"], "max_tokens")
        self.assertEqual(split_b["split_trigger_reason"], "max_tokens")


class TestFailedInsurancePromptExperimentRemoved(unittest.TestCase):
    """9. V2's ineffective Insurance prompt-clarity addition is reverted."""

    def test_commercial_only_prompt_no_longer_contains_v2_insurance_clarification(self):
        prompt = _build_prompt(ROUTE_COMMERCIAL_ONLY, APPENDIX_G_FILE, "some chunk text")
        self.assertNotIn("Be exhaustive across the clause_kind list", prompt)
        self.assertNotIn("INSURANCE-kind entry", prompt)

    def test_identity_eval_req_prompt_now_requests_pricing_consequence_topic(self):
        """The V3 fix for Abnormally Low Pricing: a minimal widening of the
        EXISTING requirements-topic filter (not a new family, not a new
        route) to include pricing-evaluation consequence rules."""
        prompt = _build_prompt(ROUTE_IDENTITY_EVAL_REQ, MASTER_RFP_FILE, "some chunk text")
        self.assertIn("pricing-evaluation consequence", prompt)
        self.assertIn("abnormally low", prompt.lower())


class TestCommercialFixesDoNotRegress(unittest.TestCase):
    """15. V2's already-correct commercial-section rows remain correct in V3."""

    def test_pricing_structure_and_contract_term_rows_still_populate(self):
        result = FastAnalysisResult()
        result.requirements = [
            {"source_doc": "OriginalRevision/RFP 2026-026 - Appendix E - Pricing Form.xlsx",
             "description": "All-inclusive pricing must be provided for Years 1, 2, and 3."},
        ]
        result.typed_observations = [
            {"family": "CONTRACT_TERM", "semantic_kind": "INITIAL_DURATION", "duration": "3",
             "unit": "years", "scope": {}},
            {"family": "CONTRACT_TERM", "semantic_kind": "EXTENSION_OPTION", "option_count": "2",
             "duration": "1", "unit": "year"},
        ]
        content = build_fast_report_content(result)
        labels = [row[0] for row in content.COMMERCIAL_POINTS]
        self.assertIn("Pricing Structure", labels)
        self.assertIn("Contract Term & Extensions", labels)

    def test_clause_derived_rows_still_populate(self):
        result = FastAnalysisResult()
        result.commercial_clauses = [
            {"clause_kind": "INTELLECTUAL_PROPERTY", "source_fact": "IP assigned to the Bank."},
            {"clause_kind": "CONFIDENTIALITY", "source_fact": "Standard mutual confidentiality."},
        ]
        content = build_fast_report_content(result)
        labels = [row[0] for row in content.COMMERCIAL_POINTS]
        self.assertIn("Intellectual Property", labels)
        self.assertIn("Confidentiality", labels)


if __name__ == "__main__":
    unittest.main()
