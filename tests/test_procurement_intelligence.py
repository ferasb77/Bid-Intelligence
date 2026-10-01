"""tests/test_procurement_intelligence.py -- Tests for the Deterministic Procurement Intelligence Foundation."""
import pytest
import procurement_intelligence as pi


def test_budget_volume_and_timetable_extraction():
    sample_text = """
    ESTIMATED BUDGET FOR CONSULTING/PROFESSIONAL FEES
    CAD 150,000 - $ 200,000 per year
    The City anticipates a total volume of approximately 65-100 coaching sessions per year.
    Session duration typically consists of Five (5) – ten (10) 1-hour sessions.
    RFP issue date
    2026 September 25
    Deadline for Proponent
    Questions
    Prior to 16:00:59 (MST) on
    2026 October 19
    Deadline for Issuing Addenda
    2026 October 20
    Submission Deadline
    2026 October 22
    16:00:59 (MST)
    Rectification Period
    Three (3) Business Days
    """
    facts = pi.extract_deterministic_procurement_facts(sample_text, "RFP.pdf")
    by_kind = {f["semantic_kind"]: f for f in facts}

    assert by_kind["ESTIMATED_BUDGET"]["value"] == {
        "currency": "CAD", "minimum": 150000, "maximum": 200000, "period": "year"
    }
    assert by_kind["ANNUAL_SESSION_VOLUME"]["value"]["minimum"] == 65
    assert by_kind["ANNUAL_SESSION_VOLUME"]["value"]["maximum"] == 100
    assert any(
        f["semantic_kind"] == "SESSION_VOLUME_RANGE" and
        f["value"]["minimum"] == 5 and f["value"]["maximum"] == 10
        for f in facts
    )
    assert by_kind["RFP_ISSUE_DATE"]["value"] == "2026 September 25"
    assert "2026 October 19" in by_kind["QUESTION_DEADLINE"]["value"]
    assert "MST" in by_kind["SUBMISSION_DEADLINE"]["value"]
    assert by_kind["RECTIFICATION_PERIOD"]["value"] == "Three (3) Business Days"


def test_coaching_objectives_extraction():
    text = """
    1.1 Coaching Objectives
    Primary objectives will achieve the following:
    • Support leaders in navigating complex organizational change.
    • Enhance executive presence and strategic communication across all departments.
    • Foster continuous improvement and leadership resilience.
    The agreement term will be three years.
    """
    facts = pi.extract_deterministic_procurement_facts(text, "RFP.pdf")
    objectives = [f["value"] for f in facts if f["family"] == "OBJECTIVE"]
    assert len(objectives) == 3
    assert "Support leaders in navigating" in objectives[0]
    assert "Enhance executive presence" in objectives[1]
    assert "Foster continuous improvement" in objectives[2]


def test_page_limit_extraction():
    assert pi.extract_page_limit_deterministic("Technical response must not exceed 20 pages.") == 20
    assert pi.extract_page_limit_deterministic("There is a maximum of twenty (20) pages for Appendix C.") == 20
    assert pi.extract_page_limit_deterministic("No restriction stated.") is None


def test_complete_criterion_response_prompt_retention():
    long_prompt = "Demonstrate extensive experience. " * 100  # > 3000 chars
    text = f"1. Firm Experience & Capabilities (30%)\n{long_prompt}\n2. Price\nStandard pricing formula."
    prompts = pi.extract_criterion_response_prompts(text, ["Firm Experience & Capabilities", "Price"])
    assert "Firm Experience & Capabilities" in prompts
    entry = prompts["Firm Experience & Capabilities"]
    assert entry["complete"] is True
    assert entry["truncated"] is True  # signals > 1500 threshold
    assert len(entry["response_prompt"]) > 2500  # full passage preserved


def test_summary_table_isolation():
    text = """
    Summary Table:
    Firm Experience & Capabilities 30% 70%
    Team Experience and Qualifications 10%
    Service Delivery 30%
    Price 20%

    B. EVALUATION OF RATED CRITERIA
    1. Firm Experience & Capabilities (30%)
    Provide 3 past projects.
    2. Team Experience and Qualifications –
    Weight (10 %)
    Provide team bios and credentials.
    """
    scoped = pi.extract_scoped_criterion_response_prompts(
        text, ["Firm Experience & Capabilities", "Team Experience and Qualifications"]
    )
    assert "||firm experience & capabilities" in scoped
    assert "Provide 3 past projects." == scoped["||firm experience & capabilities"]["response_prompt"]
    assert "||team experience and qualifications" in scoped
    assert "Provide team bios and credentials." == scoped["||team experience and qualifications"]["response_prompt"]
