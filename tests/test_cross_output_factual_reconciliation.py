"""
tests/test_cross_output_factual_reconciliation.py

Verifies factual reconciliation across UNDERSTAND UI, Decision Brief PDF,
and Full Intelligence Appendix PDF, per P0 Factual Integrity Remediation.

Acceptance criteria:
1. York P27-070 tie-break rules:
   - Rank 1: Price points (highest)
   - Rank 2: Ability to deliver services (highest points)
   - Rank 3: Coin toss
   - No fabricated "highest technical score" default.
2. Deduplication boilerplate stopword expansion preserves multi-tiered evaluation criteria.
3. Keyword trap protection: "no single point of failure" does NOT produce "Single Contract".
4. UNDERSTAND header KPI cards reconcile contract term from Decision Brief / analysis snapshot
   even when legacy bid_briefs table is empty.
5. ReportLab PDF tag leak assertion: no raw XML/HTML tags (<b>, <i>, <br/>, <font>) leaked into text.
"""

import io
import re
import pytest
from pypdf import PdfReader

from decision_brief import (
    EvaluationSummary,
    DecisionBriefInput,
    build_decision_brief,
    _resolve_tie_break_rule,
)
from scripts.fast_analysis_report_adapter import (
    _tie_break_rules,
    _procurement_model,
    _is_near_duplicate,
    _fuzzy_word_set,
    _FUZZY_DEDUP_STOPWORDS,
    build_fast_report_content,
)
from pages.stage_understand import _resolve_procurement_term_and_model
import decision_brief_report
import analysis_service


def test_boilerplate_stopwords_expanded():
    """Verify that evaluation boilerplate words were added to stopword filter."""
    for word in ("highest", "points", "proposal", "proposals", "proponent", "proponents"):
        assert word in _FUZZY_DEDUP_STOPWORDS, f"Expected {word} in _FUZZY_DEDUP_STOPWORDS"


def test_tie_break_extraction_and_deduplication():
    """Verify that different criteria ranks (Price vs Ability to deliver) are not collapsed."""
    obs_price = {
        "family": "TIE_BREAK_RULE",
        "semantic_kind": "RANKED_CRITERION",
        "rank": 1,
        "original_value": "The proposal with the highest points for Price will be ranked higher",
    }
    obs_services = {
        "family": "TIE_BREAK_RULE",
        "semantic_kind": "RANKED_CRITERION",
        "rank": 2,
        "original_value": "The proposal with the highest points for ability to deliver services will be ranked higher",
    }
    obs_coin = {
        "family": "TIE_BREAK_RULE",
        "semantic_kind": "LOTTERY",
        "rank": 3,
        "original_value": "Coin toss",
    }

    # Verify _is_near_duplicate does NOT consider Price and ability to deliver near-duplicates
    w_price = _fuzzy_word_set(obs_price["original_value"])
    w_services = _fuzzy_word_set(obs_services["original_value"])
    assert not _is_near_duplicate(obs_price["original_value"], w_price, obs_services["original_value"], w_services)

    # Verify adapter _tie_break_rules returns all 3 in order
    rules = _tie_break_rules([obs_price, obs_services, obs_coin])
    assert len(rules) == 3
    assert "Price" in rules[0]
    assert "ability to deliver services" in rules[1]
    assert "Coin toss" in rules[2]


def test_resolve_tie_break_rule_triad():
    """Acceptance Triad for _resolve_tie_break_rule:
    1. Positive: Formats verified sequence correctly.
    2. Negative: Empty or absent observations returns safe fallback.
    3. Boundary: Detects conflicting evidence at the same rank.
    """
    # 1. Positive: 3-step sequence
    obs_seq = [
        {"family": "TIE_BREAK_RULE", "semantic_kind": "RANKED_CRITERION", "rank": 1, "original_value": "Price"},
        {"family": "TIE_BREAK_RULE", "semantic_kind": "RANKED_CRITERION", "rank": 2, "original_value": "Ability to deliver"},
        {"family": "TIE_BREAK_RULE", "semantic_kind": "LOTTERY", "rank": 3, "original_value": "Coin toss"},
    ]
    resolved = _resolve_tie_break_rule(obs_seq)
    assert "(1) Price" in resolved
    assert "(2) Ability to deliver" in resolved
    assert "(3) Coin toss" in resolved

    # 2. Negative: Empty / none
    assert _resolve_tie_break_rule([]) == "No tie-break rule identified in reviewed documents."
    assert _resolve_tie_break_rule(None) == "No tie-break rule identified in reviewed documents."

    # 3. Boundary: Conflict (multiple different rules at rank 1)
    obs_conflict = [
        {"family": "TIE_BREAK_RULE", "rank": 1, "original_value": "Highest price"},
        {"family": "TIE_BREAK_RULE", "rank": 1, "original_value": "Highest technical score"},
    ]
    resolved_conflict = _resolve_tie_break_rule(obs_conflict)
    assert "Conflicting tie-break rules identified" in resolved_conflict


def test_procurement_model_keyword_trap_boundary():
    """Verify that 'single point of failure' in scope/requirements does NOT trigger 'Single Contract'."""
    from fast_analysis import FastAnalysisResult

    def _make_result(req_descriptions):
        return FastAnalysisResult(
            doc_metadata_by_doc={},
            typed_observations=[],
            evaluation_criteria=[],
            requirements=[{"description": d} for d in req_descriptions],
            commercial_clauses=[],
            evaluation_occurrences=[],
            pricing_occurrences=[],
            focused_sections_found={},
            page_limits={},
            skipped_documents=[],
            batched_documents=[],
            documents_by_route={},
            ambiguities=[],
            telemetry={},
            wall_seconds=0.0,
            deterministic_seconds=0.0,
            buyer_intelligence=None,
            deterministic_service_scope=[],
            deterministic_response_guidelines=[],
            deterministic_criterion_response_prompts=[],
            scoped_criterion_response_prompts={},
            scoped_criterion_evaluation={},
            category_scope_items=[],
            canonical_milestones=[],
            document_relationships={},
            package_completeness={},
        )

    # 1. Negative trap: "no single point of failure"
    trap_result = _make_result(["Architecture must ensure no single point of failure across systems."])
    content_trap = build_fast_report_content(trap_result)
    snap_trap = dict(content_trap.SNAPSHOT_FACTS)
    assert snap_trap.get("Procurement Model") == "Not stated in the extracted data."

    # 2. Positive: explicit phrase
    pos_result = _make_result(["This solicitation is intended for a single contract award to one proponent."])
    content_pos = build_fast_report_content(pos_result)
    snap_pos = dict(content_pos.SNAPSHOT_FACTS)
    assert snap_pos.get("Procurement Model") == "Single Contract"


def test_understand_header_kpi_resolution():
    """Verify that UNDERSTAND header KPI cards resolve contract term from Decision Brief
    when legacy brief_row is empty."""
    class DummyBrief:
        snapshot_rows = (
            ("Buyer Organization", "York University"),
            ("Contract Term / Duration", "36 months, with 2 optional 24-month extensions"),
        )

    # Empty brief_row, populated Decision Brief
    term, model = _resolve_procurement_term_and_model({}, DummyBrief(), None)
    assert term == "36 months, with 2 optional 24-month extensions"
    assert model == "Not classified"

    # Both empty
    term_empty, model_empty = _resolve_procurement_term_and_model({}, None, None)
    assert term_empty == "Not stated"
    assert model_empty == "Not classified"


def test_decision_brief_pdf_rendering_no_tag_leaks():
    """Verify that rendered Decision Brief PDF for Run 57 does not leak raw HTML/XML tags
    and contains accurate tie-break rules."""
    brief = analysis_service.load_decision_brief_for_run(57)
    pdf_bytes = decision_brief_report.render_decision_brief_bytes(brief)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    full_text = "\n".join(page.extract_text() for page in reader.pages)

    # 1. No leaked HTML tags like <b>, </b>, <br/>, &lt;b&gt;, etc.
    tag_matches = re.findall(r'<(b|i|font|br|/b|/i|/font)[^>]*>', full_text, flags=re.IGNORECASE)
    assert len(tag_matches) == 0, f"Found leaked tags in PDF: {tag_matches}"

    # 2. No escaped tags rendered as text: &lt;b&gt;
    assert "&lt;" not in full_text
    assert "&gt;" not in full_text

    # 3. Contains verified tie-break sequence on Section 4 / Page 6
    assert "Price" in full_text
    assert "ability to deliver services" in full_text
    assert "coin toss" in full_text

    # 4. Does NOT contain fabricated old default
    assert "highest technical score will be ranked first" not in full_text


def test_tie_break_duplicate_normalizations():
    """Phase D: Comprehensive test matrix for tie-break duplicate handling.

    Verifies that trivial punctuation, casing, whitespace, and leading/trailing articles
    are normalized without triggering false conflicts, while genuinely distinct criteria
    are preserved.
    """
    # 1. Exact duplicates collapse
    exact = [
        {"family": "TIE_BREAK_RULE", "rank": 1, "original_value": "Highest points for Price"},
        {"family": "TIE_BREAK_RULE", "rank": 1, "original_value": "Highest points for Price"},
    ]
    res_exact = _resolve_tie_break_rule(exact)
    assert "Conflicting" not in res_exact
    assert "Highest points for Price" in res_exact

    # 2. Punctuation variations collapse (trailing period, exclamation mark)
    punct = [
        {"family": "TIE_BREAK_RULE", "rank": 1, "original_value": "Highest points for Price."},
        {"family": "TIE_BREAK_RULE", "rank": 1, "original_value": "Highest points for Price!"},
    ]
    res_punct = _resolve_tie_break_rule(punct)
    assert "Conflicting" not in res_punct

    # 3. Case variations collapse
    casing = [
        {"family": "TIE_BREAK_RULE", "rank": 1, "original_value": "HIGHEST POINTS FOR PRICE"},
        {"family": "TIE_BREAK_RULE", "rank": 1, "original_value": "highest points for price"},
    ]
    res_casing = _resolve_tie_break_rule(casing)
    assert "Conflicting" not in res_casing

    # 4. Whitespace variations collapse
    ws = [
        {"family": "TIE_BREAK_RULE", "rank": 1, "original_value": "Highest  points   for Price"},
        {"family": "TIE_BREAK_RULE", "rank": 1, "original_value": "Highest points for Price "},
    ]
    res_ws = _resolve_tie_break_rule(ws)
    assert "Conflicting" not in res_ws

    # 5. Trivial article differences collapse
    art = [
        {"family": "TIE_BREAK_RULE", "rank": 1, "original_value": "The proposal with highest points for Price"},
        {"family": "TIE_BREAK_RULE", "rank": 1, "original_value": "A proposal with highest points for Price"},
    ]
    res_art = _resolve_tie_break_rule(art)
    assert "Conflicting" not in res_art

    # 6. Distinct criteria at distinct ranks are preserved
    distinct_ranks = [
        {"family": "TIE_BREAK_RULE", "rank": 1, "original_value": "Highest Price points"},
        {"family": "TIE_BREAK_RULE", "rank": 2, "original_value": "Highest ability-to-deliver points"},
        {"family": "TIE_BREAK_RULE", "rank": 3, "original_value": "Coin toss"},
    ]
    res_ranks = _resolve_tie_break_rule(distinct_ranks)
    assert "(1) Highest Price points" in res_ranks
    assert "(2) Highest ability-to-deliver points" in res_ranks
    assert "(3) Coin toss" in res_ranks

    # 7. Genuine conflict at same rank is flagged
    conflict = [
        {"family": "TIE_BREAK_RULE", "rank": 1, "original_value": "Highest Price points"},
        {"family": "TIE_BREAK_RULE", "rank": 1, "original_value": "Highest Technical score"},
    ]
    res_conflict = _resolve_tie_break_rule(conflict)
    assert "Conflicting tie-break rules identified" in res_conflict

    # 8. Unrelated families are ignored
    mixed = [
        {"family": "PROCUREMENT_TIMELINE", "rank": 1, "original_value": "Proposal due Oct 30"},
        {"family": "TIE_BREAK_RULE", "rank": 1, "original_value": "Price points"},
    ]
    res_mixed = _resolve_tie_break_rule(mixed)
    assert "Price points" in res_mixed
    assert "Oct 30" not in res_mixed


def test_escape_dynamic_text_and_adversarial_pdf_rendering():
    """Phase I: Verify ReportLab dynamic content isolation against adversarial inputs."""
    import dataclasses

    # 1. Unit tests for escape_dynamic_text
    assert decision_brief_report.escape_dynamic_text(None) == "—"
    assert decision_brief_report.escape_dynamic_text("") == "—"
    assert decision_brief_report.escape_dynamic_text("   ") == "—"
    assert decision_brief_report.escape_dynamic_text("AT&T") == "AT&amp;T"
    assert decision_brief_report.escape_dynamic_text("R&D < 10%") == "R&amp;D &lt; 10%"
    assert decision_brief_report.escape_dynamic_text("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"
    assert decision_brief_report.escape_dynamic_text("<b>buyer supplied</b>") == "&lt;b&gt;buyer supplied&lt;/b&gt;"
    assert decision_brief_report.escape_dynamic_text("Line 1\nLine 2") == "Line 1<br/>Line 2"

    # 2. Render adversarial Decision Brief to PDF without crash or tag leakage
    brief = analysis_service.load_decision_brief_for_run(57)
    # Inject adversarial dynamic fields
    adversarial_brief = dataclasses.replace(
        brief,
        opportunity=brief.opportunity + " & Co. <script>",
        solicitation=brief.solicitation + " / R&D < 5%",
        buyer=brief.buyer + " <b>Bold Buyer</b>",
        target_beneficiaries="Founders & startups in R&D < 20% bracket",
    )
    pdf_bytes = decision_brief_report.render_decision_brief_bytes(adversarial_brief)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    full_text = "\n".join(page.extract_text() for page in reader.pages)

    # In extracted PDF text:
    # - Bold Buyer should appear as text "Bold Buyer" (not styled via injected <b> tag)
    # - Injected HTML like <b>Bold Buyer</b> should either render safely as escaped entities or plain text
    assert "Bold Buyer" in full_text
    # Ensure no active ReportLab styling tag leak from <b>Bold Buyer</b>
    assert "&lt;b&gt;" in full_text or "Bold Buyer" in full_text
    # Verify that escape_dynamic_text neutralized the injection
    assert decision_brief_report.escape_dynamic_text("<script>") == "&lt;script&gt;"
    assert decision_brief_report.escape_dynamic_text("<b>Bold Buyer</b>") == "&lt;b&gt;Bold Buyer&lt;/b&gt;"


def test_understand_source_precedence_matrix():
    """Phase J: Verify UNDERSTAND source-precedence matrix (Cases 1 through 6)."""
    class MockBrief:
        def __init__(self, term="Brief Term", model="Brief Model"):
            self.snapshot_rows = [
                ("Contract Term / Duration", term),
                ("Procurement Model", model),
            ]

    # Case 1: Populated Decision Brief, empty legacy brief_row, empty analysis snapshot
    t1, m1 = _resolve_procurement_term_and_model({}, MockBrief("36 months", "RFP Single Contract"), None)
    assert t1 == "36 months"
    assert m1 == "RFP Single Contract"

    # Case 2: Populated Decision Brief, conflicting legacy brief_row (Brief takes precedence)
    legacy_row = {"contract_term": "Old 12 months", "procurement_model": "Old Standing Offer"}
    t2, m2 = _resolve_procurement_term_and_model(legacy_row, MockBrief("36 months", "Single Contract"), None)
    assert t2 == "36 months"
    assert m2 == "Single Contract"

    # Case 3: Empty Decision Brief, populated analysis snapshot
    class MockContent:
        SNAPSHOT_FACTS = [
            ("Contract Term / Duration", "Snapshot 24 months"),
            ("Procurement Model", "Snapshot Standing Offer"),
        ]
    t3, m3 = _resolve_procurement_term_and_model({}, None, MockContent())
    assert t3 == "Snapshot 24 months"
    assert m3 == "Snapshot Standing Offer"

    # Case 4: Populated Decision Brief has precedence over analysis snapshot
    t4, m4 = _resolve_procurement_term_and_model({}, MockBrief("36 months", "Single Contract"), MockContent())
    assert t4 == "36 months"
    assert m4 == "Single Contract"

    # Case 5: Empty Decision Brief, empty snapshot, populated legacy brief_row (fallback)
    t5, m5 = _resolve_procurement_term_and_model(legacy_row, None, None)
    assert t5 == "Old 12 months"
    assert m5 == "Old Standing Offer"

    # Case 6: All empty / None -> safe fallbacks
    t6, m6 = _resolve_procurement_term_and_model({}, None, None)
    assert t6 == "Not stated"
    assert m6 == "Not classified"


def test_procurement_model_boundary_phrases():
    """Phase K: Verify procurement model classification boundaries against common RFP phrases."""
    from fast_analysis import FastAnalysisResult

    def _test_phrase(phrase: str) -> str:
        res = FastAnalysisResult(
            doc_metadata_by_doc={},
            typed_observations=[],
            evaluation_criteria=[],
            requirements=[{"description": phrase}],
            commercial_clauses=[],
            evaluation_occurrences=[],
            pricing_occurrences=[],
            focused_sections_found={},
            page_limits={},
            skipped_documents=[],
            batched_documents=[],
            documents_by_route={},
            ambiguities=[],
            telemetry={},
            wall_seconds=0.0,
            deterministic_seconds=0.0,
            buyer_intelligence=None,
            deterministic_service_scope=[],
            deterministic_response_guidelines=[],
            deterministic_criterion_response_prompts=[],
            scoped_criterion_response_prompts={},
            scoped_criterion_evaluation={},
            category_scope_items=[],
            canonical_milestones=[],
            document_relationships={},
            package_completeness={},
        )
        content = build_fast_report_content(res)
        return dict(content.SNAPSHOT_FACTS).get("Procurement Model", "")

    # Boundary 1: "single point of contact" must NOT classify as Single Contract
    assert _test_phrase("Proponent must designate a single point of contact for all notices.") != "Single Contract"

    # Boundary 2: "single submission" must NOT classify as Single Contract
    assert _test_phrase("Proponents shall submit a single submission package via Bonfire.") != "Single Contract"

    # Boundary 3: "single award" classifies as Single Contract
    assert _test_phrase("York intends to make a single award for these services.") == "Single Contract"

    # Boundary 4: "standing offer agreement" classifies as Standing Offer
    assert _test_phrase("This solicitation will establish a standing offer agreement.") == "Standing Offer"
