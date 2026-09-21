"""
tests/test_fast_analysis_remediation_report.py -- Full-Package Analysis
Integrity Remediation, report-rendering wiring (task section 10/15
"Report" category). Calls scripts/fast_analysis_report_adapter.py's own
functions directly against a synthetic FastAnalysisResult -- no live API
call, no live database.
"""
import unittest

from fast_analysis import FastAnalysisResult
from scripts.fast_analysis_report_adapter import (
    _service_category_rows, _rg_evidence_map, _NOT_EXTRACTED, build_fast_report_content,
)


def _result(**overrides) -> FastAnalysisResult:
    r = FastAnalysisResult()
    for k, v in overrides.items():
        setattr(r, k, v)
    return r


class TestServiceCategoryRowsDefectD(unittest.TestCase):

    def test_falls_back_to_criterion_response_prompts_when_no_literal_match(self):
        """Root cause reproduced: the category label never appears
        verbatim inside any requirement description (the real Bank of
        Canada failure mode) -- must now fall back to Defect A's captured
        response prompts instead of rendering _NOT_EXTRACTED."""
        result = _result(
            requirements=[{"category": "Rated", "description": "Describe your delivery methodology."}],
            evaluation_occurrences=[
                {"criterion_label": "Curriculum Design", "weight": "35 points",
                 "category_scope": "Category 1 — Learning & Development", "parent_heading": "Category 1 — Learning & Development"},
            ],
            deterministic_criterion_response_prompts={
                "Curriculum Design": {"response_prompt": "Describe your approach to curriculum design and delivery.", "truncated": False},
            },
        )
        rows = _service_category_rows(result, ["Category 1 — Learning & Development"])
        self.assertEqual(len(rows), 1)
        label, _tag, desc = rows[0]
        self.assertNotEqual(desc, _NOT_EXTRACTED)
        self.assertIn("curriculum design", desc.lower())

    def test_still_not_extracted_when_genuinely_no_signal(self):
        result = _result(requirements=[], evaluation_occurrences=[], deterministic_criterion_response_prompts={})
        rows = _service_category_rows(result, ["Category 1 — Unknown"])
        self.assertEqual(rows[0][2], _NOT_EXTRACTED)

    def test_literal_substring_match_still_takes_priority_when_present(self):
        """The pre-existing literal-match path is untouched -- still tried
        first, and used when it succeeds."""
        result = _result(
            requirements=[{"category": "Rated", "description": "Category 1 — Learning & Development scope covers X."}],
        )
        rows = _service_category_rows(result, ["Category 1 — Learning & Development"])
        self.assertIn("scope covers", rows[0][2])


class TestRgEvidenceMapDefectA(unittest.TestCase):

    def test_prefers_exact_criterion_label_response_prompt(self):
        result = _result(
            requirements=[],
            deterministic_response_guidelines=[],
            deterministic_criterion_response_prompts={
                "Corporate Profile": {"response_prompt": "Describe your organisation's history and structure.", "truncated": False},
            },
        )
        rows = _rg_evidence_map(result, [("Corporate Profile", "5 points")])
        self.assertEqual(len(rows), 1)
        _rg_id, label, evidence = rows[0]
        self.assertEqual(label, "Corporate Profile")
        self.assertIn("organisation's history", evidence)

    def test_falls_back_to_ordinal_response_guideline_when_no_exact_label_match(self):
        result = _result(
            requirements=[],
            deterministic_response_guidelines=[
                {"id": "RG1", "weight": "5 points", "minimum_score": None,
                 "evidence_prompts": ["Describe your team structure."], "source_doc": "x"},
            ],
            deterministic_criterion_response_prompts={},
        )
        rows = _rg_evidence_map(result, [("Team Structure", "5 points")])
        self.assertIn("team structure", rows[0][2].lower())

    def test_not_extracted_when_none_of_the_three_sources_have_it(self):
        result = _result(requirements=[], deterministic_response_guidelines=[], deterministic_criterion_response_prompts={})
        rows = _rg_evidence_map(result, [("Some Criterion", "5 points")])
        self.assertEqual(rows[0][2], _NOT_EXTRACTED)

    def test_pricing_criterion_is_skipped_entirely(self):
        result = _result(requirements=[], deterministic_response_guidelines=[], deterministic_criterion_response_prompts={})
        rows = _rg_evidence_map(result, [("Pricing", "25 points")])
        self.assertEqual(rows, [])


class TestPackageCompletenessWarningRendering(unittest.TestCase):

    def test_warning_surfaces_in_report_content_when_present(self):
        result = _result(package_completeness={"is_complete": False, "warning": "Possible incomplete procurement package: test."})
        content = build_fast_report_content(result)
        self.assertEqual(content.PACKAGE_COMPLETENESS_WARNING, "Possible incomplete procurement package: test.")

    def test_no_warning_when_package_is_complete(self):
        result = _result(package_completeness={"is_complete": True, "warning": None})
        content = build_fast_report_content(result)
        self.assertIsNone(content.PACKAGE_COMPLETENESS_WARNING)

    def test_no_warning_when_completeness_never_computed(self):
        result = _result(package_completeness=None)
        content = build_fast_report_content(result)
        self.assertIsNone(content.PACKAGE_COMPLETENESS_WARNING)


class TestValidationFooterNoteAccuracy(unittest.TestCase):
    """FAST vs FULL analysis contract (task section 9): the disclaimer
    must remain honest about FAST-mode coverage -- no claim of exhaustive
    per-document reading."""

    def test_disclaimer_still_states_targeted_extraction(self):
        result = _result()
        content = build_fast_report_content(result)
        self.assertIn("targeted extraction", content.VALIDATION_FOOTER_NOTE.lower())
        self.assertIn("deduplicated", content.VALIDATION_FOOTER_NOTE.lower())
