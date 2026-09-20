"""
tests/test_phase5b_redundancy_reduction.py

BI Token Optimization Program, Phase 5B: Zero-Inference Request Context
Deduplication.

Proves, with explicit assertions (never model judgment), that the four
system-prompt trims made this phase (Section Analyzer's _ANALYZER_SYSTEM,
analyst.py's _ALIGN_CHUNK_SYSTEM / _ALIGN_SYNTHESIS_SYSTEM /
_PROCUREMENT_CHANGE_SYSTEM) removed only an exact-redundant "respond with
valid JSON only" sentence -- never any unique instruction, enum, status,
provenance requirement, or analytical distinction -- and that the
corresponding request got measurably smaller.

Zero-inference guarantee (instruction 18): an autouse fixture patches
anthropic.Anthropic to raise immediately if ANY test in this file somehow
tries to construct a real client, so no accidental live call is possible
even if a future edit to this file introduced one.
"""
from unittest.mock import patch

import pytest

import analyst
import section_analyzer as sa
import request_profiling as rp


@pytest.fixture(autouse=True)
def zero_inference_guard():
    """No test in this file may construct a real Anthropic client, let
    alone call messages.create/count_tokens -- every prompt-construction
    function exercised here is pure Python with no network reach, and
    this guard makes that a hard failure instead of an assumption."""
    with patch("anthropic.Anthropic", side_effect=AssertionError(
            "zero-inference guard: no Anthropic client may be constructed in Phase 5B tests")):
        yield


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _section_analyzer_context():
    return {
        "section_title": "Technical Approach", "section_guidance": "Explain your methodology",
        "section_text": "We propose an agile delivery methodology with weekly check-ins.",
        "word_limit": 500,
        "requirements": [
            {"requirement_id": 1, "req_id": "R-1", "category": "Technical",
             "description": "Describe delivery methodology", "evaluation_weight": 20,
             "minimum_score": 3, "response_guideline": "RG-1: explain cadence"},
        ],
        "qualification_mechanisms": [{"semantic_kind": "mandatory", "original_value": "Must have ISO 9001"}],
        "tie_break_rules": [{"rank": 1, "original_value": "Lowest price"}],
        "buyer_intelligence": {"verified_facts": [{"detail": "Buyer prefers agile", "source": "past RFP"}]},
        "procurement_basis": {"procurement_truth_status": "governed", "advisory_intelligence_available": True,
                              "advisory_unavailable_reason": None},
    }


# ---------------------------------------------------------------------------
# Section Analyzer contract preservation
# ---------------------------------------------------------------------------

class TestSectionAnalyzerContractPreserved:

    def test_a_every_required_output_field_still_represented(self):
        prompt = sa._analyzer_prompt(_section_analyzer_context())
        for field in ("direction", "summary", "requirement_assessments",
                      "response_guideline_assessments", "evidence_assessment",
                      "clarity_and_structure", "differentiation", "buyer_context", "top_changes"):
            assert f'"{field}"' in prompt, f"missing required output field: {field}"

    def test_b_every_enum_status_represented_exactly_once(self):
        prompt = sa._ANALYZER_SYSTEM + "\n" + sa._analyzer_prompt(_section_analyzer_context())
        assert prompt.count("ON_TRACK|NEEDS_ADJUSTMENT|HIGH_RISK|INSUFFICIENT_CONTEXT") == 1
        assert prompt.count("COVERED|PARTIAL|MISSING|CONTRADICTED|CANNOT_ASSESS") == 1
        assert prompt.count("ANSWERED|PARTIAL|NOT_ANSWERED") == 1
        assert prompt.count("SPECIFIC|GENERIC|UNSUPPORTED|DIFFERENTIATED") == 1
        assert prompt.count("IN_SECTION|CROSS_REFERENCE_NEEDED|OWNED_BY_OTHER_SECTION|GLOBAL_REQUIREMENT") == 1

    def test_c_unique_semantic_instructions_all_still_present(self):
        system = sa._ANALYZER_SYSTEM
        for instruction in (
            "never invent a procurement requirement",
            "never fabricate an example and present it as real",
            "never convert Buyer",  # Intelligence -> stated evaluation requirement guardrail (item F)
            "Never predict a numeric score",  # no-scoring-behavior guardrail (item G)
            "Never claim a competitor cannot do something",
        ):
            assert instruction in system, f"lost unique semantic instruction: {instruction!r}"

    def test_d_source_provenance_requirement_preserved(self):
        prompt = sa._analyzer_prompt(_section_analyzer_context())
        assert '"section_evidence"' in prompt

    def test_e_no_procurement_facts_disappear_from_context_assembly(self):
        ctx = _section_analyzer_context()
        prompt, components = sa._analyzer_prompt(ctx, return_components=True)
        assert "req_id='R-1'" in components["requirements"]
        assert "evaluation weight: 20" in components["requirements"]
        assert "minimum score: 3" in components["requirements"]
        assert "RG-1: explain cadence" in components["requirements"]

    def test_f_buyer_intelligence_separation_rule_intact(self):
        assert ("never convert Buyer Intelligence (external context) into a stated "
                "evaluation requirement") in sa._ANALYZER_SYSTEM
        prompt = sa._analyzer_prompt(_section_analyzer_context())
        assert "NEVER an evaluation requirement" in prompt  # buyer_context section header

    def test_g_no_scoring_behavior_introduced(self):
        assert "Never predict a numeric score" in sa._ANALYZER_SYSTEM
        prompt = sa._analyzer_prompt(_section_analyzer_context())
        assert '"score"' not in prompt.replace('"minimum score"', "")

    def test_h_context_selection_behavior_unchanged(self):
        """build_section_context's own field selection is untouched by this
        phase -- only the system prompt's trailing sentence changed."""
        ctx = _section_analyzer_context()
        _, components = sa._analyzer_prompt(ctx, return_components=True)
        assert set(components.keys()) == {"section", "requirements", "buyer_intelligence", "instructions"}

    def test_i_request_became_smaller(self):
        profile = rp.build_profile(workflow="section_analyzer", operation="formative_review",
                                   system=sa._ANALYZER_SYSTEM)
        assert profile.system_bytes == 1061  # was 1091 before Phase 5B (-30 bytes)
        assert "Respond with valid JSON only." not in sa._ANALYZER_SYSTEM

    def test_json_response_requirement_still_present_somewhere_in_the_full_request(self):
        """The removed sentence's REQUIREMENT (respond only with JSON) must
        still be enforced -- just once, not twice."""
        prompt = sa._analyzer_prompt(_section_analyzer_context())
        assert "Return ONLY valid JSON in exactly this shape:" in prompt


# ---------------------------------------------------------------------------
# analyst.py contract preservation (the 3 changed system constants)
# ---------------------------------------------------------------------------

class TestAnalystAlignChunkContractPreserved:

    def test_unique_instructions_intact(self):
        system = analyst._ALIGN_CHUNK_SYSTEM
        assert "NEVER assert that something is missing or absent" in system
        assert "only report what you can positively confirm IS present" in system
        assert "Never report truncation, incompleteness, a missing continuation" in system

    def test_json_requirement_still_enforced_via_user_prompt(self):
        prompt = analyst._align_chunk_prompt(
            "Bid: Test", "procurement context", "requirement block",
            {"heading": "Section 1", "index": 0, "total": 1, "text": "chunk text"})
        assert "For THIS SECTION ONLY, return ONLY valid JSON:" in prompt

    def test_request_became_smaller(self):
        profile = rp.build_profile(workflow="analyst", operation="proposal_alignment_chunk",
                                   system=analyst._ALIGN_CHUNK_SYSTEM)
        assert profile.system_bytes == 754  # was 784 before Phase 5B (-30 bytes)


class TestAnalystAlignSynthesisContractPreserved:

    def test_no_scoring_behavior_reassessment_guardrail_intact(self):
        system = analyst._ALIGN_SYNTHESIS_SYSTEM
        assert "You do NOT reassess coverage, scores, or mandatory failures" in system
        assert "ground truth" in system

    def test_json_requirement_still_enforced_via_user_prompt(self):
        prompt_source = analyst._synthesize_narrative.__doc__ or ""
        # The literal instruction lives in the f-string inside the function body;
        # verify via the compiled constant text present in the module source.
        import inspect
        source = inspect.getsource(analyst._synthesize_narrative)
        assert "Return ONLY valid JSON, with EXACTLY these three keys and no others:" in source

    def test_request_became_smaller(self):
        profile = rp.build_profile(workflow="analyst", operation="proposal_alignment_synthesis",
                                   system=analyst._ALIGN_SYNTHESIS_SYSTEM)
        assert profile.system_bytes == 229  # was 259 before Phase 5B (-30 bytes)


class TestAnalystProcurementChangeContractPreserved:

    def test_human_authority_guardrail_intact(self):
        system = analyst._PROCUREMENT_CHANGE_SYSTEM
        assert "you do NOT decide what happens to canonical truth" in system
        assert "a human reviews and approves every proposal" in system

    def test_coverage_list_unique_instruction_intact(self):
        system = analyst._PROCUREMENT_CHANGE_SYSTEM
        for topic in ("deadlines/dates", "mandatory requirements", "evaluation criteria and weights",
                     "pricing/commercial terms", "insurance", "AI/data/privacy requirements"):
            assert topic in system

    def test_json_requirement_still_enforced_via_user_prompt(self):
        prompt = analyst._procurement_change_prompt(
            "Bid: Test", "current requirements", "Amendment", "chunk text", "Section 1", "amendment.pdf")
        assert "Return ONLY valid JSON:" in prompt

    def test_request_became_smaller(self):
        profile = rp.build_profile(workflow="analyst", operation="procurement_change_proposal",
                                   system=analyst._PROCUREMENT_CHANGE_SYSTEM)
        assert profile.system_bytes == 1012  # was 1042 before Phase 5B (-30 bytes)


# ---------------------------------------------------------------------------
# Fast Analysis / Deep Verify: honest "no change" confirmation
# ---------------------------------------------------------------------------

class TestFastAnalysisAndDeepVerifyUnchanged:
    """Phase 5B found no safe, high-confidence redundancy in these two
    workflows (see the final report's findings) -- confirms no byte
    drift occurred despite auditing them, rather than silently skipping."""

    def test_fast_analysis_static_overhead_unchanged(self):
        import fast_analysis as fa
        route = next(iter(fa._ROUTE_SCHEMAS))
        schema_text = fa._ROUTE_SCHEMAS[route]
        prompt = fa._build_prompt(route, "f.pdf", "")
        marker = "\n\nDOCUMENT TO PROCESS (f.pdf):\n"
        header = prompt[: prompt.index(marker)]
        assert len(header.encode("utf-8")) == 3894  # baseline from docs/current/REQUEST_BUDGETS.json

    def test_deep_verify_stage_a_static_overhead_unchanged(self):
        import extractor as ex
        assert len(ex.STAGE_A_FACT_EXTRACTION_PROMPT.encode("utf-8")) == 14688

    def test_deep_verify_stage_d_static_overhead_unchanged(self):
        import stage_d_projection as sdp
        assert len(sdp.SYNTHESIS_PROMPT.encode("utf-8")) == 5722
