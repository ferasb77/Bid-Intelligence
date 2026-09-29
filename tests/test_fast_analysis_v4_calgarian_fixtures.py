"""Deterministic V4 regressions from exact Calgary source excerpts.

These tests never call a provider and do not use benchmark prose as product
input; they lock the structural boundaries that the production corpus exposed.
"""

import fast_analysis
import procurement_normalization


APPENDIX_C = """B. EVALUATION OF RATED CRITERIA
1. Firm Experience & Capabilities (30%)
Provide three (3) examples and include outcomes and project team composition.
2. Team Experience and Qualifications – Weight (10 %)
Identify the lead personnel, credentials, availability, and issue resolution.
3. Service Delivery – Weight (30%)
Describe intake, matching, delivery logistics, reporting, and confidentiality.
4. Social Procurement
Complete the Social Procurement Questionnaire.
C.
EVALUATION OF PRICING
Price
Pricing will be scored by a relative pricing formula.
"""


def test_appendix_c_keeps_each_criterion_and_never_keys_summary_price():
    labels = ["Firm Experience & Capabilities", "Team Experience and Qualifications",
              "Service Delivery", "Social Procurement", "Price"]
    prompts = procurement_normalization.extract_scoped_criterion_response_prompts(
        APPENDIX_C, labels)
    assert set(prompts) == {
        "||firm experience & capabilities", "||team experience and qualifications",
        "||service delivery", "||social procurement",
    }
    assert "three (3) examples" in prompts["||firm experience & capabilities"]["response_prompt"]
    assert "availability" in prompts["||team experience and qualifications"]["response_prompt"]
    assert "intake" in prompts["||service delivery"]["response_prompt"]
    assert all(entry["complete"] for entry in prompts.values())


def test_split_weight_line_is_a_team_heading_boundary():
    text = """B. EVALUATION OF RATED CRITERIA
2. Team Experience and Qualifications –
Weight (10 %)
Identify the lead personnel and their availability.
3. Service Delivery – Weight (30%)
Describe the delivery method.
"""
    prompts = procurement_normalization.extract_scoped_criterion_response_prompts(
        text, ["Team Experience and Qualifications", "Service Delivery"])
    assert "||team experience and qualifications" in prompts
    assert "availability" in prompts["||team experience and qualifications"]["response_prompt"]


def test_explicit_budget_volume_and_mst_timetable_are_separate_facts():
    excerpt = """ESTIMATED BUDGET FOR CONSULTING/PROFESSIONAL FEES
$ 150,000 - $ 200,000 per year
The City anticipates a total volume of approximately 65-100 coaching sessions per year.
Session duration typically consists of Five (5) – ten (10) 1-hour sessions.
RFP issue date
2026 September 25
Deadline for Issuing Addenda
2026 October 20
Submission Deadline
2026 October 22
16:00:59 (MST)
Rectification Period
Three (3) Business Days
"""
    facts = fast_analysis.extract_deterministic_procurement_facts(excerpt, "RFP.pdf")
    by_kind = {fact["semantic_kind"]: fact for fact in facts}
    assert by_kind["ESTIMATED_BUDGET"]["value"] == {
        "currency": "CAD", "minimum": 150000, "maximum": 200000, "period": "year"}
    assert by_kind["ANNUAL_SESSION_VOLUME"]["value"]["minimum"] == 65
    assert by_kind["ANNUAL_SESSION_VOLUME"]["value"]["maximum"] == 100
    assert any(f["semantic_kind"] == "SESSION_VOLUME_RANGE" and
               f["value"]["minimum"] == 5 and f["value"]["maximum"] == 10
               for f in facts)
    assert by_kind["RFP_ISSUE_DATE"]["value"] == "2026 September 25"
    assert "MST" in by_kind["SUBMISSION_DEADLINE"]["value"]
    assert by_kind["RECTIFICATION_PERIOD"]["value"] == "Three (3) Business Days"
