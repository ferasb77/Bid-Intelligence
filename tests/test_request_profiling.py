"""
tests/test_request_profiling.py

Deterministic tests for request_profiling.py (Phase 5A: Offline Request
Profiling & Token Budgeting) and for the component-exposure refactor in
section_analyzer.py's _analyzer_prompt(). No live API calls anywhere in
this file except test_try_count_tokens_* which use a MagicMock, never a
real client.
"""
import unittest
from unittest.mock import MagicMock

import request_profiling as rp
import section_analyzer as sa


class TestMeasureAndHash(unittest.TestCase):

    def test_build_profile_measures_each_component_independently(self):
        profile = rp.build_profile(
            workflow="w", operation="o", model="m",
            system="abc", schema="{}", source_document="hello world",
        )
        self.assertEqual(profile.system_chars, 3)
        self.assertEqual(profile.system_bytes, 3)
        self.assertEqual(profile.schema_chars, 2)
        self.assertEqual(profile.source_document_chars, 11)
        # absent components stay exactly zero, never fabricated
        self.assertEqual(profile.procurement_context_chars, 0)
        self.assertEqual(profile.buyer_intelligence_bytes, 0)

    def test_multibyte_text_bytes_exceed_chars(self):
        profile = rp.build_profile(workflow="w", operation="o", system="café")
        self.assertEqual(profile.system_chars, 4)
        self.assertEqual(profile.system_bytes, 5)  # 'é' is 2 bytes in utf-8

    def test_system_excluded_from_messages_total_chars(self):
        profile = rp.build_profile(
            workflow="w", operation="o", system="X" * 100,
            source_document="Y" * 50,
        )
        self.assertEqual(profile.messages_total_chars, 50)
        self.assertNotEqual(profile.messages_total_chars, profile.system_chars + 50)

    def test_request_total_bytes_includes_tool_schema_bytes(self):
        profile = rp.build_profile(
            workflow="w", operation="o", source_document="hi", tool_schema_bytes=40,
        )
        self.assertEqual(profile.request_total_bytes, 2 + 40)

    def test_no_component_text_is_retained_on_the_profile(self):
        profile = rp.build_profile(workflow="w", operation="o", system="SECRET-PROMPT-TEXT")
        dumped = str(profile.as_dict())
        self.assertNotIn("SECRET-PROMPT-TEXT", dumped)

    def test_hash_component_deterministic_and_never_returns_text(self):
        h1 = rp.hash_component("some prompt text")
        h2 = rp.hash_component("some prompt text")
        self.assertEqual(h1, h2)
        self.assertNotIn("some prompt text", h1)
        self.assertIsNone(rp.hash_component(None))
        self.assertIsNone(rp.hash_component(""))

    def test_component_hashes_only_present_for_supplied_components(self):
        profile = rp.build_profile(workflow="w", operation="o", system="x", schema=None)
        self.assertIn("system", profile.component_hashes)
        self.assertNotIn("schema", profile.component_hashes)

    def test_hash_components_false_disables_hashing(self):
        profile = rp.build_profile(workflow="w", operation="o", system="x", hash_components=False)
        self.assertEqual(profile.component_hashes, {})


class TestEstimateLabeling(unittest.TestCase):

    def test_estimate_is_a_rough_chars_over_4_heuristic(self):
        self.assertEqual(rp.estimate_tokens_from_chars(400), 100)
        self.assertEqual(rp.estimate_tokens_from_chars(3), 0)

    def test_build_profile_always_sets_estimated_input_tokens_never_provider_field(self):
        profile = rp.build_profile(workflow="w", operation="o", source_document="x" * 40)
        self.assertIsNotNone(profile.estimated_input_tokens)
        self.assertIsNone(profile.provider_counted_input_tokens)

    def test_provider_counted_tokens_only_set_when_explicitly_passed(self):
        profile = rp.build_profile(workflow="w", operation="o", provider_counted_input_tokens=123)
        self.assertEqual(profile.provider_counted_input_tokens, 123)


class TestDuplicateContextMap(unittest.TestCase):

    def test_identical_component_text_across_profiles_is_grouped(self):
        p1 = rp.build_profile(workflow="fast_analysis", operation="chunk_1", system="SAME SYSTEM")
        p2 = rp.build_profile(workflow="fast_analysis", operation="chunk_2", system="SAME SYSTEM")
        p3 = rp.build_profile(workflow="fast_analysis", operation="chunk_3", system="DIFFERENT")
        dup_map = rp.duplicate_context_map([p1, p2, p3])
        self.assertIn("system", dup_map)
        (digest, labels), = [(d, l) for d, l in dup_map["system"].items()]
        self.assertEqual(set(labels), {"fast_analysis/chunk_1", "fast_analysis/chunk_2"})

    def test_unique_components_produce_no_entries(self):
        p1 = rp.build_profile(workflow="w", operation="a", system="one")
        p2 = rp.build_profile(workflow="w", operation="b", system="two")
        self.assertEqual(rp.duplicate_context_map([p1, p2]), {})

    def test_no_prompt_text_leaks_into_the_duplicate_map(self):
        p1 = rp.build_profile(workflow="w", operation="a", system="CONFIDENTIAL RFP TEXT")
        p2 = rp.build_profile(workflow="w", operation="b", system="CONFIDENTIAL RFP TEXT")
        dup_map = rp.duplicate_context_map([p1, p2])
        self.assertNotIn("CONFIDENTIAL RFP TEXT", str(dup_map))


class TestCacheCandidacy(unittest.TestCase):

    def test_provider_counted_above_floor_is_a_candidate(self):
        self.assertEqual(rp.cache_candidacy(prefix_chars=0, counted_tokens=5000), "CACHE_CANDIDATE")

    def test_provider_counted_below_floor_is_not_a_candidate(self):
        self.assertEqual(rp.cache_candidacy(prefix_chars=0, counted_tokens=100), "NOT_CANDIDATE")

    def test_small_estimate_without_a_count_is_ruled_out(self):
        self.assertEqual(rp.cache_candidacy(prefix_chars=200), "NOT_CANDIDATE")

    def test_estimate_near_the_floor_without_a_count_is_unknown_not_a_candidate(self):
        # A generous chars/4 estimate near the floor must never be
        # promoted to CACHE_CANDIDATE without a real provider count.
        near_floor_chars = rp.MIN_CACHEABLE_PREFIX_TOKENS * rp.CHARS_PER_TOKEN_ESTIMATE
        self.assertEqual(rp.cache_candidacy(prefix_chars=near_floor_chars), "UNKNOWN")


class TestTryCountTokens(unittest.TestCase):

    def test_success_returns_tokens_and_no_error(self):
        client = MagicMock()
        client.messages.count_tokens.return_value = MagicMock(input_tokens=42)
        tokens, error = rp.try_count_tokens(client, model="claude-haiku-4-5-20251001", system="s")
        self.assertEqual(tokens, 42)
        self.assertIsNone(error)
        client.messages.count_tokens.assert_called_once()

    def test_failure_returns_none_and_error_category_without_raising(self):
        client = MagicMock()
        client.messages.count_tokens.side_effect = RuntimeError("credit balance too low")
        tokens, error = rp.try_count_tokens(client, model="claude-haiku-4-5-20251001")
        self.assertIsNone(tokens)
        self.assertEqual(error, "RuntimeError")

    def test_exactly_one_call_no_internal_retry(self):
        client = MagicMock()
        client.messages.count_tokens.side_effect = RuntimeError("boom")
        rp.try_count_tokens(client, model="m")
        self.assertEqual(client.messages.count_tokens.call_count, 1)


class TestSectionAnalyzerComponentExposure(unittest.TestCase):
    """Phase 5A instruction 3: prompt-builder component boundaries must be
    exposable WITHOUT changing the final prompt text byte-for-byte."""

    @staticmethod
    def _context():
        return {
            "section_title": "Technical Approach",
            "section_guidance": "Explain your methodology",
            "section_text": "We propose an agile delivery methodology with weekly check-ins.",
            "word_limit": 500,
            "requirements": [
                {"requirement_id": 1, "req_id": "R-1", "category": "Technical",
                 "description": "Describe delivery methodology", "evaluation_weight": 20,
                 "minimum_score": 3, "response_guideline": "RG-1: explain cadence"},
                {"requirement_id": 2, "req_id": "R-2", "category": "Technical",
                 "description": "Describe risk management", "evaluation_weight": None,
                 "minimum_score": None, "response_guideline": None},
            ],
            "qualification_mechanisms": [{"semantic_kind": "mandatory", "original_value": "Must have ISO 9001"}],
            "tie_break_rules": [{"rank": 1, "original_value": "Lowest price"}],
            "buyer_intelligence": {"verified_facts": [{"detail": "Buyer prefers agile", "source": "past RFP"}]},
            "procurement_basis": {"procurement_truth_status": "governed",
                                  "advisory_intelligence_available": True,
                                  "advisory_unavailable_reason": None},
        }

    def test_return_components_false_is_byte_identical_to_default(self):
        ctx = self._context()
        default = sa._analyzer_prompt(ctx)
        explicit_false = sa._analyzer_prompt(ctx, return_components=False)
        self.assertEqual(default, explicit_false)
        self.assertIsInstance(default, str)

    def test_return_components_true_prompt_matches_default_prompt(self):
        ctx = self._context()
        default = sa._analyzer_prompt(ctx)
        prompt_with_components, components = sa._analyzer_prompt(ctx, return_components=True)
        self.assertEqual(default, prompt_with_components)
        self.assertEqual(
            {"section", "requirements", "buyer_intelligence", "instructions"},
            set(components.keys()),
        )

    def test_components_concatenate_back_to_the_exact_final_prompt(self):
        ctx = self._context()
        prompt, components = sa._analyzer_prompt(ctx, return_components=True)
        reassembled = (
            components["section"] + "\n\n" + components["requirements"] + "\n\n"
            + components["buyer_intelligence"] + "\n\n" + components["instructions"]
        )
        self.assertEqual(reassembled, prompt)

    def test_components_are_usable_by_the_profiler_without_changing_output(self):
        ctx = self._context()
        _, components = sa._analyzer_prompt(ctx, return_components=True)
        profile = rp.build_profile(
            workflow="section_analyzer", operation="formative_review",
            system=sa._ANALYZER_SYSTEM,
            source_document=components["section"],
            procurement_context=components["requirements"],
            buyer_intelligence=components["buyer_intelligence"],
            other_context=components["instructions"],
        )
        self.assertGreater(profile.system_chars, 0)
        self.assertGreater(profile.source_document_chars, 0)
        self.assertGreater(profile.procurement_context_chars, 0)
        self.assertGreater(profile.buyer_intelligence_chars, 0)


if __name__ == "__main__":
    unittest.main()
