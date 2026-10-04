"""Deterministic specification and acceptance tests for York P27-070 Decision-Brief Benchmark.

Part of BI-VALUE-1.1: Establishes evidence-safe acceptance testing and epistemic discipline
for the Bid Intelligence UNDERSTAND decision brief.

Ensures that any future brief generator will FAIL quality gating if it:
- Blurs RFP facts, external facts, interpretations, and proof recommendations
- Injects unmentioned third-party vendor or tool brands
- Uses predictive evaluator guarantees ("evaluators will reject/penalize")
- Claims unstated passing score thresholds
- Treats extraction defects as buyer omissions
- Omits verified technical capabilities from the York RFP

Constraints:
- 0 provider calls
- 0 database mutations
- Deterministic execution
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pytest


# ==============================================================================
# 1. BENCHMARK QUALITY GATE SPECIFICATION & VALIDATOR
# ==============================================================================

FORBIDDEN_LEAKED_PATTERNS = [
    re.compile(r"\bREQ-\d+\b", re.I),
    re.compile(r"\bSPECIALIST_[A-Z0-9_:]+", re.I),
    re.compile(r"\bEVALUATION_INTELLIGENCE:\d+\b", re.I),
    re.compile(r"\bSCOPE_DELIVERABLES:\d+\b", re.I),
    re.compile(r"\bOBL-\d+\b", re.I),
    re.compile(r"\bIDENT-\d+\b", re.I),
]

FORBIDDEN_EXTRACTION_FAILURE_EXCUSES = [
    "the buyer did not specify this requirement",
    "not specified by buyer",
    "buyer omitted this information",
    "buyer did not state requirements",
]

FORBIDDEN_UNMENTIONED_BRANDS = [
    re.compile(r"\b(Claude|ChatGPT|Apollo|Clay|Salesforce|Hubspot)\b", re.I),
]

FORBIDDEN_PREDICTIVE_EVALUATOR_CLAIMS = [
    re.compile(r"\bevaluators will (reject|penalize)\b", re.I),
    re.compile(r"\bwill lose points\b", re.I),
    re.compile(r"\bmassive scoring edge\b", re.I),
    re.compile(r"\bdisqualifies solo practitioners\b", re.I),
    re.compile(r"\bacademic courseware fails\b", re.I),
    re.compile(r"\bwin theme\b", re.I),
]

FORBIDDEN_INVENTED_THRESHOLDS = [
    re.compile(r"\bpassing threshold of \d+", re.I),
    re.compile(r"\bminimum (passing )?score of \d+", re.I),
    re.compile(r"\bthreshold of (75%?|60/80|80%?)\b", re.I),
]

VALID_EPISTEMIC_CLASSES = {
    "RFP FACT",
    "EXTERNAL BUYER FACT",
    "BID INTELLIGENCE INTERPRETATION",
    "BID STRATEGY / PROOF RECOMMENDATION",
    "UNKNOWN",
}

MANDATORY_YORK_TECHNICAL_CAPABILITIES = [
    ("sme_startup_experience", [r"\bsme\b", r"\bstart-up\b", r"\bstartup\b", r"\bsmall and medium\b"]),
    ("deep_bench", [r"\bdeep bench\b", r"\bsingle point of failure\b", r"\bbackup instructor\b", r"\bteam capacity\b"]),
    ("sales_playbook", [r"\bsales playbook\b", r"\bsales framework\b", r"\bb2b sales\b"]),
    ("ai_integration", [r"\bai\b", r"\bartificial intelligence\b", r"\bapplied ai\b", r"\bai tools\b"]),
    ("leadership_development", [r"\bleadership\b", r"\bfounder coaching\b", r"\bexecutive mentorship\b"]),
    ("existing_curriculum", [r"\bexisting curriculum\b", r"\bsample framework\b", r"\bcurriculum library\b", r"\bpre-existing\b"]),
    ("publicly_funded_delivery", [r"\bpublicly funded\b", r"\bpublic sector\b", r"\bgovernment-funded\b", r"\bgrant-funded\b"]),
    ("methodology_workplan", [r"\bmethodology\b", r"\bworkplan\b", r"\bwork plan\b", r"\bactivity schedule\b"]),
]


@dataclass
class BenchmarkValidationResult:
    is_valid: bool
    failures: list[str] = field(default_factory=list)


def validate_york_decision_brief(brief_data: dict[str, Any]) -> BenchmarkValidationResult:
    """Validates whether a decision brief meets the York P27-070 evidence benchmark specification.

    Enforces all quality gates and epistemic rules defined in
    docs/current/YORK_P27_070_DECISION_BRIEF_BENCHMARK.md.
    """
    failures: list[str] = []

    all_strings = _extract_all_strings(brief_data)
    all_text = " ".join(all_strings)
    lower_text = all_text.lower()

    # 1. Leaked Specialist / Internal IDs
    for pattern in FORBIDDEN_LEAKED_PATTERNS:
        matches = pattern.findall(all_text)
        if matches:
            failures.append(f"Gate 9 Violated: Leaked internal debug/specialist IDs found: {matches}")

    # 2. Extraction Failure Excuses
    for excuse in FORBIDDEN_EXTRACTION_FAILURE_EXCUSES:
        if excuse in lower_text:
            failures.append(f"Epistemic Rule Violated: Extraction failure treated as buyer omission: '{excuse}'")

    # 3. Unmentioned Technology Brands
    for pattern in FORBIDDEN_UNMENTIONED_BRANDS:
        matches = pattern.findall(all_text)
        if matches:
            failures.append(f"Gate 3 Violated: Unmentioned commercial technology brand injected: {matches}")

    # 4. Predictive Evaluator Language
    for pattern in FORBIDDEN_PREDICTIVE_EVALUATOR_CLAIMS:
        matches = pattern.findall(all_text)
        if matches:
            failures.append(f"Gate 2 Violated: Predictive evaluator claim detected: {matches}")

    # 5. Invented Evaluation Thresholds
    for pattern in FORBIDDEN_INVENTED_THRESHOLDS:
        matches = pattern.findall(all_text)
        if matches:
            failures.append(f"Gate Violated: Invented unstated technical passing threshold: {matches}")

    # 6. Epistemic Classification Check on Structured Items
    for section_name in ("technical_capabilities", "proof_items", "observations"):
        items = brief_data.get(section_name) or []
        for idx, item in enumerate(items):
            if isinstance(item, dict):
                eclass = item.get("epistemic_class")
                if not eclass:
                    failures.append(f"Epistemic Rule Violated: Missing epistemic_class in {section_name}[{idx}]")
                elif eclass not in VALID_EPISTEMIC_CLASSES:
                    failures.append(f"Epistemic Rule Violated: Invalid epistemic_class '{eclass}' in {section_name}[{idx}]")

    # 7. Proof Recommendations Masquerading as Mandatory Buyer Requirements
    proof_items = brief_data.get("proof_items") or []
    for item in proof_items:
        if isinstance(item, dict):
            nature = item.get("nature")
            eclass = item.get("epistemic_class")
            if nature == "recommendation" and eclass == "RFP FACT":
                failures.append(f"Epistemic Rule Violated: Proof recommendation masquerading as RFP FACT: {item.get('title')}")

    # 8. Mandatory York Technical Capabilities
    tech_requirements = brief_data.get("technical_capabilities") or []
    tech_text = " ".join(_extract_all_strings(tech_requirements)).lower()

    for cap_id, patterns in MANDATORY_YORK_TECHNICAL_CAPABILITIES:
        if not any(re.search(pat, tech_text, re.I) for pat in patterns):
            failures.append(f"Gate Violated: Omitted mandatory York technical capability: {cap_id} (patterns: {patterns})")

    # 9. Priority Inversion (Technical vs Administrative Space)
    commercial_items = brief_data.get("commercial_clauses") or []
    submission_items = brief_data.get("submission_mechanics") or []
    admin_count = len(commercial_items) + len(submission_items)
    tech_count = len(tech_requirements)

    if tech_count == 0:
        failures.append("Gate 7 Violated: Technical capability section is completely empty, displaced by administrative content.")
    elif tech_count < 4 and admin_count >= 6:
        failures.append(f"Gate 7 Violated: Priority inversion detected: {admin_count} administrative items vs only {tech_count} technical requirements.")

    # 10. Evaluation Criteria Duplication & Math
    criteria = brief_data.get("evaluation_criteria") or []
    seen_criteria = set()
    for c in criteria:
        name = str(c.get("name") or "").strip().lower()
        if not name:
            continue
        if name in seen_criteria:
            failures.append(f"Gate 8 Violated: Duplicate evaluation criterion detected: '{name}'")
        seen_criteria.add(name)

    # 11. Buyer Intelligence Grounding & Metadata
    buyer_intel = brief_data.get("buyer_intelligence") or {}
    if buyer_intel:
        claimed_signals = buyer_intel.get("signals") or []
        for signal in claimed_signals:
            if not signal.get("source_url") or not signal.get("source_title"):
                failures.append("Gate 5 Violated: External Buyer Intelligence missing verified source URL and title metadata.")

    # 12. Methodology Weight Dominance (45 Points)
    methodology_found = False
    for c in criteria:
        name = str(c.get("name") or "").lower()
        weight_str = str(c.get("weight") or "")
        if "methodology" in name or "workplan" in name:
            methodology_found = True
            if "45" not in weight_str and "56" not in weight_str:
                failures.append(f"Gate Violated: Methodology & Workplan weight incorrect or understated ({weight_str} vs required 45 pts).")
    if not methodology_found and criteria:
        failures.append("Gate Violated: Methodology & Workplan missing from evaluation criteria.")

    return BenchmarkValidationResult(is_valid=(len(failures) == 0), failures=failures)


def _extract_all_strings(obj: Any) -> list[str]:
    strings: list[str] = []
    if isinstance(obj, str):
        strings.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            strings.extend(_extract_all_strings(v))
    elif isinstance(obj, (list, tuple, set)):
        for item in obj:
            strings.extend(_extract_all_strings(item))
    return strings


# ==============================================================================
# 2. TEST FIXTURES
# ==============================================================================

@pytest.fixture
def compliant_york_brief() -> dict[str, Any]:
    """A model of a fully evidence-safe, compliant York P27-070 Decision Brief."""
    return {
        "buyer": "York University",
        "solicitation": "P27-070",
        "opportunity": "Instructor for Sales and AI Training and Mentorship Program",
        "observations": [
            {
                "title": "Integrated SME Practitioner Profile",
                "detail": "The RFP combines SME ecosystem knowledge with applied AI and sales training, indicating a preference for practitioner-led delivery.",
                "epistemic_class": "BID INTELLIGENCE INTERPRETATION",
                "supporting_rfp_fact": "Section 4.1 and Section 6.3",
            }
        ],
        "technical_capabilities": [
            {
                "capability": "Knowledge of Canadian SME and start-up ecosystem",
                "detail": "Demonstrated understanding of nuances across sectors, cities, and regions.",
                "source": "RFP Section 4.1",
                "epistemic_class": "RFP FACT",
            },
            {
                "capability": "Extensive experience delivering SME and start-up training",
                "detail": "Proven track record facilitating training programs for small and medium-sized ventures.",
                "source": "RFP Section 4.1",
                "epistemic_class": "RFP FACT",
            },
            {
                "capability": "Deep bench and operational resilience",
                "detail": "Multi-person delivery team demonstrating capacity with no single point of failure and backup instructors.",
                "source": "RFP Section 4.2",
                "epistemic_class": "RFP FACT",
            },
            {
                "capability": "B2B sales playbook methodology",
                "detail": "Repeatable framework for sales development, prospecting, and conversion.",
                "source": "RFP Section 4.3",
                "epistemic_class": "RFP FACT",
            },
            {
                "capability": "Applied AI integration into sales workflows",
                "detail": "Hands-on instruction on modern AI tools for lead research, outreach drafting, and sales productivity.",
                "source": "RFP Section 4.3",
                "epistemic_class": "RFP FACT",
            },
            {
                "capability": "Executive and founder leadership development",
                "detail": "Mentorship for founder-led teams on sales discipline and commercial growth.",
                "source": "RFP Section 4.1",
                "epistemic_class": "RFP FACT",
            },
            {
                "capability": "Existing curriculum library and sample framework",
                "detail": "Sample framework previously produced for SME/start-up training reflecting Section 6.3 scope.",
                "source": "RFP Section 4.6",
                "epistemic_class": "RFP FACT",
            },
            {
                "capability": "Publicly funded delivery experience",
                "detail": "Fluency in milestone reporting and accountability standard in public programs.",
                "source": "RFP Section 4.1",
                "epistemic_class": "RFP FACT",
            },
            {
                "capability": "Detailed delivery methodology and workplan",
                "detail": "Step-by-step activity schedule detailing cohort workshops and mentorship milestones.",
                "source": "RFP Section 4.3 / 4.4",
                "epistemic_class": "RFP FACT",
            },
        ],
        "proof_items": [
            {
                "title": "Three Client References",
                "nature": "mandatory_requirement",
                "detail": "Names, dates, phone, and email of at least 3 organizations certifying similar work.",
                "epistemic_class": "RFP FACT",
            },
            {
                "title": "Delivery Bench Chart",
                "nature": "recommendation",
                "detail": "Visual organizational chart illustrating role redundancies across key modules.",
                "epistemic_class": "BID STRATEGY / PROOF RECOMMENDATION",
            },
        ],
        "evaluation_criteria": [
            {"name": "Methodology & Workplan", "weight": "45.0 points (56.3% of technical)"},
            {"name": "Qualifications & Experience", "weight": "35.0 points (43.7% of technical)"},
            {"name": "Pricing Schedule", "weight": "20.0 points"},
            {"name": "Shortlist Presentation (Conditional)", "weight": "20.0 points"},
        ],
        "buyer_intelligence": {
            "signals": [
                {
                    "title": "York University Procurement Policy",
                    "source_url": "https://www.yorku.ca/procurement/policies",
                    "source_title": "York University Official Procurement Guidelines",
                }
            ]
        },
        "submission_mechanics": [
            {"item": "MERX Registration", "requirement": "Mandatory direct acquisition prior to closing."},
            {"item": "Bonfire Upload Slots", "requirement": "6 distinct PDF files."},
        ],
        "commercial_clauses": [
            {"topic": "Expense Prohibition", "detail": "All-inclusive pricing; zero hospitality/travel reimbursement under Ontario directive."},
            {"topic": "Subcontracting", "detail": "Prior written consent required."},
        ],
    }


# ==============================================================================
# 3. UNIT TESTS FOR BENCHMARK GATES
# ==============================================================================

def test_compliant_benchmark_passes(compliant_york_brief):
    """The compliant fixture satisfies all York P27-070 quality gates."""
    result = validate_york_decision_brief(compliant_york_brief)
    assert result.is_valid is True, f"Compliant brief unexpectedly failed: {result.failures}"


def test_rejects_unmentioned_vendor_brands(compliant_york_brief):
    """Fails if unmentioned commercial brands (Claude, ChatGPT, Apollo, Clay) are injected."""
    compliant_york_brief["technical_capabilities"][4]["detail"] += " utilizing Claude and Apollo.io"
    result = validate_york_decision_brief(compliant_york_brief)
    assert result.is_valid is False
    assert any("Gate 3 Violated: Unmentioned commercial technology brand" in f for f in result.failures)


def test_rejects_predictive_evaluator_guarantees(compliant_york_brief):
    """Fails if predictive evaluator claims ('evaluators will reject/penalize') are present."""
    compliant_york_brief["observations"][0]["detail"] = "Evaluators will reject solo practitioners without deep bench."
    result = validate_york_decision_brief(compliant_york_brief)
    assert result.is_valid is False
    assert any("Gate 2 Violated: Predictive evaluator claim detected" in f for f in result.failures)


def test_rejects_invented_evaluation_thresholds(compliant_york_brief):
    """Fails if an unstated passing score threshold (e.g. 75% or 60/80) is asserted."""
    compliant_york_brief["evaluation_criteria"][0]["detail"] = "Requires minimum passing score of 75% to proceed."
    result = validate_york_decision_brief(compliant_york_brief)
    assert result.is_valid is False
    assert any("Invented unstated technical passing threshold" in f for f in result.failures)


def test_rejects_unlabelled_epistemic_classes(compliant_york_brief):
    """Fails if structured decision elements lack explicit epistemic classification."""
    del compliant_york_brief["technical_capabilities"][0]["epistemic_class"]
    result = validate_york_decision_brief(compliant_york_brief)
    assert result.is_valid is False
    assert any("Missing epistemic_class in technical_capabilities[0]" in f for f in result.failures)


def test_rejects_proof_recommendation_masquerading_as_requirement(compliant_york_brief):
    """Fails if response strategy recommendation is mislabelled as an RFP FACT."""
    compliant_york_brief["proof_items"][1]["epistemic_class"] = "RFP FACT"  # Delivery Bench Chart is recommendation
    result = validate_york_decision_brief(compliant_york_brief)
    assert result.is_valid is False
    assert any("Proof recommendation masquerading as RFP FACT" in f for f in result.failures)


def test_rejects_phantom_buyer_intelligence(compliant_york_brief):
    """Fails if external Buyer Intelligence lacks source URL and title metadata."""
    compliant_york_brief["buyer_intelligence"]["signals"] = [
        {"title": "York University is expanding AI initiatives"}  # Missing source_url and source_title
    ]
    result = validate_york_decision_brief(compliant_york_brief)
    assert result.is_valid is False
    assert any("Gate 5 Violated: External Buyer Intelligence missing verified source URL" in f for f in result.failures)


def test_rejects_treating_extraction_failure_as_buyer_omission(compliant_york_brief):
    """Fails if system excuses missing extraction as buyer omission."""
    compliant_york_brief["technical_capabilities"][0]["detail"] = "The buyer did not specify this requirement in the RFP."
    result = validate_york_decision_brief(compliant_york_brief)
    assert result.is_valid is False
    assert any("Epistemic Rule Violated: Extraction failure treated as buyer omission" in f for f in result.failures)


def test_rejects_leaked_internal_ids(compliant_york_brief):
    """Fails if internal debug keys or specialist identifiers leak into text."""
    compliant_york_brief["technical_capabilities"][0]["detail"] += " Reference: REQ-13 and SPECIALIST_FULL:4"
    result = validate_york_decision_brief(compliant_york_brief)
    assert result.is_valid is False
    assert any("Gate 9 Violated: Leaked internal debug/specialist IDs found" in f for f in result.failures)


def test_rejects_omission_of_sme_ecosystem(compliant_york_brief):
    """Fails if Canadian SME / start-up ecosystem capability is omitted."""
    compliant_york_brief["technical_capabilities"] = [
        c for c in compliant_york_brief["technical_capabilities"]
        if not re.search(r"\b(sme|start-up|startup|small and medium)\b", c.get("capability", "") + " " + c.get("detail", ""), re.I)
    ]
    result = validate_york_decision_brief(compliant_york_brief)
    assert result.is_valid is False
    assert any("sme_startup_experience" in f for f in result.failures)


def test_rejects_omission_of_deep_bench(compliant_york_brief):
    """Fails if deep-bench / no single point of failure requirement is omitted."""
    compliant_york_brief["technical_capabilities"] = [
        c for c in compliant_york_brief["technical_capabilities"]
        if "deep bench" not in c["capability"].lower()
    ]
    result = validate_york_decision_brief(compliant_york_brief)
    assert result.is_valid is False
    assert any("deep_bench" in f for f in result.failures)


def test_rejects_omission_of_sales_playbook(compliant_york_brief):
    """Fails if sales playbook capability is omitted."""
    compliant_york_brief["technical_capabilities"] = [
        c for c in compliant_york_brief["technical_capabilities"]
        if "sales playbook" not in c["capability"].lower()
    ]
    result = validate_york_decision_brief(compliant_york_brief)
    assert result.is_valid is False
    assert any("sales_playbook" in f for f in result.failures)


def test_rejects_omission_of_ai_integration(compliant_york_brief):
    """Fails if AI integration capability is omitted."""
    compliant_york_brief["technical_capabilities"] = [
        c for c in compliant_york_brief["technical_capabilities"]
        if not re.search(r"\bai\b", c["capability"], re.I)
    ]
    result = validate_york_decision_brief(compliant_york_brief)
    assert result.is_valid is False
    assert any("ai_integration" in f for f in result.failures)


def test_rejects_omission_of_leadership_development(compliant_york_brief):
    """Fails if leadership development capability is omitted."""
    compliant_york_brief["technical_capabilities"] = [
        c for c in compliant_york_brief["technical_capabilities"]
        if "leadership" not in c["capability"].lower()
    ]
    result = validate_york_decision_brief(compliant_york_brief)
    assert result.is_valid is False
    assert any("leadership_development" in f for f in result.failures)


def test_rejects_omission_of_existing_curriculum(compliant_york_brief):
    """Fails if preference for existing curriculum library is omitted."""
    compliant_york_brief["technical_capabilities"] = [
        c for c in compliant_york_brief["technical_capabilities"]
        if "curriculum" not in c["capability"].lower()
    ]
    result = validate_york_decision_brief(compliant_york_brief)
    assert result.is_valid is False
    assert any("existing_curriculum" in f for f in result.failures)


def test_rejects_omission_of_publicly_funded_delivery(compliant_york_brief):
    """Fails if publicly funded delivery experience is omitted."""
    compliant_york_brief["technical_capabilities"] = [
        c for c in compliant_york_brief["technical_capabilities"]
        if "publicly funded" not in c["capability"].lower()
    ]
    result = validate_york_decision_brief(compliant_york_brief)
    assert result.is_valid is False
    assert any("publicly_funded_delivery" in f for f in result.failures)


def test_rejects_omission_of_methodology_workplan(compliant_york_brief):
    """Fails if detailed methodology and workplan is omitted."""
    compliant_york_brief["technical_capabilities"] = [
        c for c in compliant_york_brief["technical_capabilities"]
        if "methodology" not in c["capability"].lower()
    ]
    result = validate_york_decision_brief(compliant_york_brief)
    assert result.is_valid is False
    assert any("methodology_workplan" in f for f in result.failures)


def test_rejects_priority_inversion(compliant_york_brief):
    """Fails if technical requirements are displaced by administrative / insurance terms."""
    compliant_york_brief["technical_capabilities"] = []
    compliant_york_brief["commercial_clauses"] = [
        {"topic": f"Commercial Term {i}", "detail": "Standard clause"} for i in range(10)
    ]
    result = validate_york_decision_brief(compliant_york_brief)
    assert result.is_valid is False
    assert any("Gate 7 Violated: Technical capability section is completely empty" in f for f in result.failures)


def test_rejects_duplicate_evaluation_criteria(compliant_york_brief):
    """Fails if duplicate evaluation criteria rows are produced."""
    compliant_york_brief["evaluation_criteria"].append(
        {"name": "Methodology & Workplan", "weight": "45%"}
    )
    result = validate_york_decision_brief(compliant_york_brief)
    assert result.is_valid is False
    assert any("Gate 8 Violated: Duplicate evaluation criterion detected" in f for f in result.failures)


def test_rejects_understated_methodology_scoring(compliant_york_brief):
    """Fails if Methodology & Workplan weight is understated or missing 45 points."""
    compliant_york_brief["evaluation_criteria"][0] = {
        "name": "Methodology & Workplan",
        "weight": "15 points",  # Understated
    }
    result = validate_york_decision_brief(compliant_york_brief)
    assert result.is_valid is False
    assert any("Gate Violated: Methodology & Workplan weight incorrect or understated" in f for f in result.failures)


def test_legacy_brief_format_fails_benchmark_gates():
    """Confirms that the legacy report format (as delivered in Bid 1522) fails the benchmark.

    The legacy brief model had zero technical capabilities, an empty buyer intelligence section,
    and priority inversion with multiple administrative/commercial clauses displacing technical substance.
    """
    legacy_brief_data = {
        "buyer": "York University",
        "solicitation": "P27-070",
        "opportunity": "Instructor for Sales and AI Training and Mentorship Program",
        # Technical capabilities omitted in legacy output
        "technical_capabilities": [],
        "evaluation_criteria": [
            {"name": "Methodology and Workplan", "weight": "Not evaluated"},
            {"name": "General Evaluation", "weight": "100%"},
        ],
        "buyer_intelligence": {
            "signals": []
        },
        "submission_mechanics": [
            {"item": "Bonfire Portal", "requirement": "Upload documents to yorku.bonfirehub.ca"},
            {"item": "Key Dates", "requirement": "Closing date October 26, 2026"},
        ],
        "commercial_clauses": [
            {"topic": "Business registration", "detail": "Vendor must be registered"},
            {"topic": "Insurance", "detail": "Standard commercial general liability"},
            {"topic": "Governing law", "detail": "Province of Ontario"},
            {"topic": "Subcontracting", "detail": "No subcontracting without consent"},
        ],
    }

    result = validate_york_decision_brief(legacy_brief_data)
    assert result.is_valid is False
    assert any("Gate 7 Violated: Technical capability section is completely empty" in f for f in result.failures)
    assert any("Gate Violated: Omitted mandatory York technical capability: sme_startup_experience" in f for f in result.failures)
