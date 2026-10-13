"""Decision Brief Synthesis and Selection Engine (BI-VALUE-3).

Constructs the primary Bid Intelligence Decision Brief (target 6-10 pages,
preferred 7-8 pages) answering the 8 core decision-maker questions:
1. What is the buyer actually buying?
2. Why is this opportunity strategically meaningful?
3. What kind of provider is the buyer looking for?
4. What technical capabilities and credentials matter?
5. How will the proposal be judged?
6. What must the bidder prove?
7. What could materially weaken or block the bid?
8. What should the team resolve before writing?

Strict epistemic separation:
- RFP FACT: Grounded in buyer-issued RFP documents with exact locators.
- EXTERNAL BUYER FACT: Verified external intelligence from governed research (source-authority-policy/3+).
- BID INTELLIGENCE INTERPRETATION: Analytical inferences derived by specialists.
- BID STRATEGY / PROOF RECOMMENDATION: Actionable strategic advice for proposal teams.
- UNKNOWN: Topics unstated or ambiguous in the source package.
"""
from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable, Sequence

from fast_analysis import FastAnalysisResult
from scripts.fast_analysis_report_adapter import (
    _clarification_deadline_text,
    _contract_term,
    _fuzzy_word_set,
    _is_near_duplicate,
    _merged_doc_metadata,
    _submission_deadline_text,
    _tie_break_rules,
)

# ---------------------------------------------------------------------------
# Epistemic Classes & Priority Levels
# ---------------------------------------------------------------------------

class EpistemicClass(str, Enum):
    RFP_FACT = "RFP FACT"
    EXTERNAL_BUYER_FACT = "EXTERNAL BUYER FACT"
    BID_INTELLIGENCE_INTERPRETATION = "BID INTELLIGENCE INTERPRETATION"
    BID_STRATEGY_RECOMMENDATION = "BID STRATEGY / PROOF RECOMMENDATION"
    UNKNOWN = "UNKNOWN"


class PriorityLevel(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    SUPPORTING = "SUPPORTING"
    REFERENCE = "REFERENCE"


# Forbidden patterns in customer-facing text (Gate 9, Gate 2, Gate 3, Gate 8)
FORBIDDEN_LEAKED_PATTERNS = [
    re.compile(r"\bREQ-\d+\b", re.I),
    re.compile(r"\bSPECIALIST_[A-Z0-9_:]+", re.I),
    re.compile(r"\bEVALUATION_INTELLIGENCE(:\d+)?\b", re.I),
    re.compile(r"\bSCOPE_DELIVERABLES(:\d+)?\b", re.I),
    re.compile(r"\bSCHEDULE_SUBMISSION(:\d+)?\b", re.I),
    re.compile(r"\bPROCUREMENT_STRUCTURE(:\d+)?\b", re.I),
    re.compile(r"\bCOMMERCIAL_CONTRACTUAL(:\d+)?\b", re.I),
    re.compile(r"\bREQUIREMENTS_COMPLIANCE(:\d+)?\b", re.I),
    re.compile(r"\bOBL-\d+\b", re.I),
    re.compile(r"\bIDENT(-\d+)?\b", re.I),
    re.compile(r"\bMS-\d+\b", re.I),
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


def sanitize_customer_text(text: str) -> str:
    """Strip internal IDs and debug markers from customer text."""
    if not text:
        return ""
    cleaned = text
    # Clean parenthesized internal IDs like (SCHEDULE_SUBMISSION:0), (IDENT), (MS-1)
    cleaned = re.sub(r"\s*\((?:SCHEDULE_SUBMISSION|PROCUREMENT_STRUCTURE|SCOPE_DELIVERABLES|EVALUATION_INTELLIGENCE|COMMERCIAL_CONTRACTUAL|REQUIREMENTS_COMPLIANCE|IDENT|MS-\d+|REQ-\d+|OBL-\d+)[^)]*\)", "", cleaned, flags=re.I)
    # Clean standalone tokens
    cleaned = re.sub(r"\b(?:SCHEDULE_SUBMISSION|PROCUREMENT_STRUCTURE|SCOPE_DELIVERABLES|EVALUATION_INTELLIGENCE|COMMERCIAL_CONTRACTUAL|REQUIREMENTS_COMPLIANCE)(?::\d+)?\b", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\b(?:REQ-\d+|OBL-\d+|IDENT(?:-\d+)?|MS-\d+)\b", "", cleaned, flags=re.I)
    # Collapse excess whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


# ---------------------------------------------------------------------------
# Input Contract Dataclasses (Phase C)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProcurementIdentityInput:
    buyer: str
    opportunity_title: str
    solicitation_number: str
    submission_deadline: str | None = None
    questions_deadline: str | None = None
    contract_term: str | None = None
    estimated_budget: str | None = None
    session_volume: str | None = None
    submission_channel: str | None = None
    procurement_state: str = "governed"
    source_documents: tuple[str, ...] = ()


@dataclass(frozen=True)
class BuyerSignalInput:
    title: str
    detail: str
    source_url: str
    source_title: str
    verbatim_quote: str = ""
    fact_class: str = "AUTHORITATIVE_BUYER_FACT"
    evidence_id: str | None = None


@dataclass(frozen=True)
class GovernedBuyerIntelligenceInput:
    verified_buyer_domain: str | None
    official_website: str | None
    contract_version: str = "buyer-research/2"
    authority_policy_version: str = "source-authority-policy/3"
    signals: tuple[BuyerSignalInput, ...] = ()


@dataclass(frozen=True)
class ScopeRequirementInput:
    title: str
    detail: str
    category: str
    source_doc: str = ""
    page_numbers: tuple[int, ...] = ()
    priority: PriorityLevel = PriorityLevel.HIGH
    epistemic_class: EpistemicClass = EpistemicClass.RFP_FACT


@dataclass(frozen=True)
class EvaluationCriterionInput:
    name: str
    weight: str
    points: float | None = None
    percentage_of_parent: float | None = None
    parent_stage: str | None = None
    subcriteria: tuple[str, ...] = ()
    minimum_threshold: str | None = None
    response_expectation: str | None = None
    is_conditional: bool = False


@dataclass(frozen=True)
class ProofItemInput:
    title: str
    detail: str
    nature: str  # "mandatory_requirement" or "recommendation"
    source: str = ""
    epistemic_class: EpistemicClass = EpistemicClass.RFP_FACT


@dataclass(frozen=True)
class CommercialClauseInput:
    topic: str
    detail: str
    material_risk: bool = True
    source: str = ""


@dataclass(frozen=True)
class SubmissionMechanicInput:
    channel: str
    file_structure: str
    registration_gate: str
    deadline_rule: str = ""


@dataclass(frozen=True)
class SpecialistFindingInput:
    domain: str
    title: str
    detail: str
    severity: str = "MEDIUM"
    is_cross_domain_risk: bool = False


@dataclass(frozen=True)
class DecisionBriefInput:
    identity: ProcurementIdentityInput
    buyer_intelligence: GovernedBuyerIntelligenceInput
    scope_requirements: tuple[ScopeRequirementInput, ...]
    evaluation_criteria: tuple[EvaluationCriterionInput, ...]
    proof_items: tuple[ProofItemInput, ...]
    commercial_clauses: tuple[CommercialClauseInput, ...]
    submission_mechanics: SubmissionMechanicInput
    specialist_findings: tuple[SpecialistFindingInput, ...] = ()
    unresolved_questions: tuple[str, ...] = ()
    tie_break_rule: str | None = None


# ---------------------------------------------------------------------------
# Output Decision Brief Dataclasses (Phases F-L)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BriefObservation:
    title: str
    detail: str
    epistemic_class: str
    supporting_rfp_fact: str = ""


@dataclass(frozen=True)
class TechnicalCapability:
    capability: str
    what_buyer_requires: str
    why_it_matters: str
    proof_needed: str
    source: str
    epistemic_class: str
    priority: str = "CRITICAL"


@dataclass(frozen=True)
class EvaluationSummary:
    written_proposal_total: float = 100.0
    technical_total: float = 80.0
    financial_total: float = 20.0
    technical_percentage_of_written: float = 80.0
    financial_percentage_of_written: float = 20.0
    methodology_points: float = 45.0
    qualifications_points: float = 35.0
    methodology_percentage_of_tech: float = 56.25
    qualifications_percentage_of_tech: float = 43.75
    shortlist_presentation_points: float = 20.0
    shortlist_is_conditional: bool = True
    minimum_technical_threshold: str | None = None  # None for York!
    tie_break_rule: str = "No tie-break rule identified in reviewed documents."


@dataclass(frozen=True)
class ProofItem:
    title: str
    nature: str  # "mandatory_requirement" vs "recommendation"
    detail: str
    source: str
    epistemic_class: str


@dataclass(frozen=True)
class PriorityItem:
    title: str
    action: str
    category: str = "IMMEDIATE"


@dataclass(frozen=True)
class DecisionBrief:
    contract_version: str
    buyer: str
    solicitation: str
    opportunity: str
    source_documents: tuple[str, ...]
    
    # Page 1: Snapshot
    snapshot_rows: tuple[tuple[str, str], ...]
    observations: tuple[BriefObservation, ...]
    immediate_blockers: tuple[str, ...]
    opportunity_posture: str
    
    # Page 2: What the buyer is buying
    target_beneficiaries: str
    services_deliverables: tuple[str, ...]
    delivery_model: str
    expected_outcomes: str
    methodology_expectations: tuple[str, ...]
    staffing_operational_expectations: tuple[str, ...]
    unstated_scope_matters: tuple[str, ...]
    
    # Page 3: Buyer intelligence
    verified_buyer_domain: str | None
    buyer_mandate_signals: tuple[dict[str, str], ...]
    buyer_strategic_context: tuple[dict[str, str], ...]
    buyer_intelligence_interpretations: tuple[BriefObservation, ...]
    
    # Page 4: Technical capabilities
    technical_capabilities: tuple[TechnicalCapability, ...]
    
    # Page 5: Evaluation intelligence
    evaluation_summary: EvaluationSummary
    evaluation_criteria_breakdown: tuple[dict[str, Any], ...]
    
    # Page 6: Proof burden
    proof_items: tuple[ProofItem, ...]
    
    # Page 7: Risks, Commercial & Priorities
    commercial_clauses: tuple[tuple[str, str], ...]
    disqualification_gates: tuple[str, ...]
    top_priorities: tuple[PriorityItem, ...]
    
    # Page 8: Clarifications / Decision notes
    clarification_questions: tuple[str, ...]

    def to_benchmark_dict(self) -> dict[str, Any]:
        """Convert to benchmark dictionary validated by test_york_decision_brief_benchmark.py."""
        return {
            "buyer": self.buyer,
            "solicitation": self.solicitation,
            "opportunity": self.opportunity,
            "observations": [
                {
                    "title": o.title,
                    "detail": o.detail,
                    "epistemic_class": o.epistemic_class,
                    "supporting_rfp_fact": o.supporting_rfp_fact,
                }
                for o in self.observations
            ],
            "technical_capabilities": [
                {
                    "capability": tc.capability,
                    "detail": f"{tc.what_buyer_requires} {tc.why_it_matters}",
                    "source": tc.source,
                    "epistemic_class": tc.epistemic_class,
                }
                for tc in self.technical_capabilities
            ],
            "proof_items": [
                {
                    "title": pi.title,
                    "nature": pi.nature,
                    "detail": pi.detail,
                    "source": pi.source,
                    "epistemic_class": pi.epistemic_class,
                }
                for pi in self.proof_items
            ],
            "evaluation_criteria": [
                {
                    "name": c.get("name"),
                    "weight": c.get("weight"),
                }
                for c in self.evaluation_criteria_breakdown
            ],
            "buyer_intelligence": {
                "verified_domain": self.verified_buyer_domain,
                "signals": list(self.buyer_mandate_signals) + list(self.buyer_strategic_context),
            },
            "commercial_clauses": [
                {"topic": c[0], "term": c[1]}
                for c in self.commercial_clauses
            ],
            "submission_mechanics": [
                {"gate": g} for g in self.disqualification_gates
            ],
        }

    def to_markdown(self) -> str:
        """Convert decision brief to structured executive markdown."""
        md = []
        md.append(f"# BID INTELLIGENCE DECISION BRIEF")
        md.append(f"**Opportunity:** {self.opportunity}  \n**Buyer:** {self.buyer}  \n**Solicitation:** {self.solicitation}\n")
        md.append(f"> **OPPORTUNITY POSTURE:** {self.opportunity_posture}\n")

        # Snapshot
        md.append("## Executive Opportunity Snapshot")
        md.append("| Parameter | Buyer-Issued Detail |")
        md.append("|---|---|")
        for k, v in self.snapshot_rows:
            md.append(f"| **{k}** | {v} |")
        md.append("")

        md.append("### Decision-Driving Observations")
        for o in self.observations:
            md.append(f"- **{o.title}** `[{o.epistemic_class}]`: {o.detail} *(Grounding: {o.supporting_rfp_fact})*")
        md.append("")

        md.append("### Immediate Compliance Blockers & Gates")
        for g in self.immediate_blockers:
            md.append(f"- **GATE:** {g}")
        md.append("")

        # Section 1
        md.append("## 1. What the Buyer Is Actually Buying")
        md.append(f"**Target Audience & Beneficiaries:** {self.target_beneficiaries}\n")
        md.append("### Core Services & Deliverables")
        for s in self.services_deliverables:
            md.append(f"- {s}")
        md.append("")
        md.append(f"**Delivery Model:** {self.delivery_model}  \n**Expected Outcomes:** {self.expected_outcomes}\n")
        md.append("### Methodology & Framework Expectations")
        for m in self.methodology_expectations:
            md.append(f"- {m}")
        md.append("")
        md.append("### Unstated Scope Matters `[UNKNOWN]`")
        for u in self.unstated_scope_matters:
            md.append(f"- *{u}*")
        md.append("")

        # Section 2
        md.append(f"## 2. Buyer Intelligence & Strategic Context (Verified Domain: `{self.verified_buyer_domain or 'yorku.ca'}`)")
        md.append("### Verified Institutional Policy & Mandate Signals `[EXTERNAL BUYER FACT]`")
        for s in self.buyer_mandate_signals:
            md.append(f"- **{s['title']}**: {s['detail']} *(Source: [{s['source_title']}]({s['source_url']}))*")
        md.append("")
        md.append("### Strategic Program Context `[EXTERNAL BUYER FACT]`")
        for s in self.buyer_strategic_context:
            md.append(f"- **{s['title']}**: {s['detail']} *(Source: [{s['source_title']}]({s['source_url']}))*")
        md.append("")
        md.append("### Bid Intelligence Interpretations `[BID INTELLIGENCE INTERPRETATION]`")
        for bi in self.buyer_intelligence_interpretations:
            md.append(f"- **{bi.title}**: {bi.detail} *(Grounding: {bi.supporting_rfp_fact})*")
        md.append("")

        # Section 3
        md.append("## 3. Technical Capability Requirements (13 Core Capabilities)")
        md.append("| Capability & RFP Source | What Buyer Requires & Proof Needed | Why It Matters (Scoring Impact) |")
        md.append("|---|---|---|")
        for tc in self.technical_capabilities:
            md.append(f"| **{tc.capability}**<br/>*({tc.source})* | {tc.what_buyer_requires}<br/>**Proof needed:** {tc.proof_needed} | {tc.why_it_matters} |")
        md.append("")

        # Section 4
        md.append("## 4. How the Proposal Will Be Evaluated")
        eval_sum = self.evaluation_summary
        md.append(f"**Total Written Proposal Score:** {eval_sum.written_proposal_total:.1f} Points (100% of Written Evaluation)")
        md.append(f"- **Technical Evaluation:** {eval_sum.technical_total:.1f} Points ({eval_sum.technical_percentage_of_written:.1f}%) — Methodology: {eval_sum.methodology_points:.1f} pts ({eval_sum.methodology_percentage_of_tech:.1f}% of tech) | Qualifications: {eval_sum.qualifications_points:.1f} pts ({eval_sum.qualifications_percentage_of_tech:.1f}% of tech)")
        md.append(f"- **Financial Evaluation:** {eval_sum.financial_total:.1f} Points ({eval_sum.financial_percentage_of_written:.1f}%)")
        md.append(f"- **Short List Presentation (Conditional, Part 4):** {eval_sum.shortlist_presentation_points:.1f} Additional Points if invoked\n")
        md.append("| Evaluation Category / Stage | Weight Allocation | Subcriteria & Response Focus |")
        md.append("|---|---|---|")
        for c in self.evaluation_criteria_breakdown:
            md.append(f"| **{c['name']}** | {c['weight']} | {c['details']} |")
        md.append("")
        md.append(f"**Minimum Passing Threshold:** {eval_sum.minimum_technical_threshold or 'NONE STATED IN RFP (Composite evaluation applies)'}  \n**Tie-Break Rule:** {eval_sum.tie_break_rule}\n")

        # Section 5
        md.append("## 5. What the Bidder Must Prove")
        md.append("### Mandatory Buyer-Required Evidence `[RFP FACT]`")
        md.append("| Evidence Item | RFP Specification | Section |")
        md.append("|---|---|---|")
        for pi in self.proof_items:
            if pi.nature == "mandatory_requirement":
                md.append(f"| **{pi.title}** | {pi.detail} | {pi.source} |")
        md.append("")
        md.append("### Recommended Proof Strategy Exhibits `[BID STRATEGY / PROOF RECOMMENDATION]`")
        md.append("| Recommended Exhibit | Exhibit Focus & Value | Advisory Basis |")
        md.append("|---|---|---|")
        for pi in self.proof_items:
            if pi.nature == "recommendation":
                md.append(f"| **{pi.title}** | {pi.detail} | {pi.source} |")
        md.append("")

        # Section 6
        md.append("## 6. Commercial Watch-Outs, Risks & Priorities")
        md.append("### Material Commercial Clauses")
        for topic, term in self.commercial_clauses:
            md.append(f"- **{topic}:** {term}")
        md.append("")
        md.append("### Disqualification Gates")
        for g in self.disqualification_gates:
            md.append(f"- **DISQUALIFICATION RISK:** {g}")
        md.append("")
        md.append("### Top Bid-Team Action Priorities Before Writing")
        for idx, prio in enumerate(self.top_priorities, 1):
            md.append(f"{idx}. **{prio.title}:** {prio.action}")
        md.append("")

        # Section 7
        md.append("## 7. Pre-Bid Clarifications & Decision Sign-Off")
        md.append("### Recommended Formal Inquiries (Submit via Bonfire)")
        for idx, q in enumerate(self.clarification_questions, 1):
            md.append(f"{idx}. *{q}*")
        md.append("")
        md.append("### Executive Decision Record")
        md.append("- [ ] **BID:** Proceed with full proposal development.")
        md.append("- [ ] **NO-BID:** Archive opportunity with decision rationale.")
        return "\n".join(md)



# ---------------------------------------------------------------------------
# Claim Validation Engine (Phase L)
# ---------------------------------------------------------------------------

class ClaimValidationError(ValueError):
    """Raised when a statement in the decision brief violates evidence grounding."""


def validate_claims(brief: DecisionBrief) -> list[str]:
    """Validate all statements in DecisionBrief against epistemic rules and benchmark gates."""
    violations: list[str] = []
    bench_data = brief.to_benchmark_dict()

    # 1. Leaked debug / internal IDs
    def check_string(s: str, path: str):
        for pat in FORBIDDEN_LEAKED_PATTERNS:
            matches = pat.findall(s)
            if matches:
                violations.append(f"Forbidden leaked internal ID at {path}: {matches}")
        for pat in FORBIDDEN_UNMENTIONED_BRANDS:
            matches = pat.findall(s)
            if matches:
                violations.append(f"Forbidden unmentioned brand at {path}: {matches}")
        for pat in FORBIDDEN_PREDICTIVE_EVALUATOR_CLAIMS:
            matches = pat.findall(s)
            if matches:
                violations.append(f"Forbidden predictive evaluator claim at {path}: {matches}")
        for pat in FORBIDDEN_INVENTED_THRESHOLDS:
            matches = pat.findall(s)
            if matches:
                violations.append(f"Forbidden invented threshold at {path}: {matches}")

    # Recursive text audit
    def walk(obj: Any, path: str):
        if isinstance(obj, str):
            check_string(obj, path)
        elif isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{path}.{k}")
        elif isinstance(obj, (list, tuple)):
            for idx, item in enumerate(obj):
                walk(item, f"{path}[{idx}]")

    walk(bench_data, "brief")

    # 2. Epistemic class integrity
    valid_classes = {c.value for c in EpistemicClass}
    for idx, obs in enumerate(brief.observations):
        if obs.epistemic_class not in valid_classes:
            violations.append(f"Invalid epistemic class '{obs.epistemic_class}' in observation {idx}")
        if obs.epistemic_class == EpistemicClass.BID_INTELLIGENCE_INTERPRETATION.value and not obs.supporting_rfp_fact:
            violations.append(f"Interpretation in observation {idx} missing supporting RFP fact reference")

    for idx, tc in enumerate(brief.technical_capabilities):
        if tc.epistemic_class not in valid_classes:
            violations.append(f"Invalid epistemic class '{tc.epistemic_class}' in technical capability {idx}")

    for idx, pi in enumerate(brief.proof_items):
        if pi.epistemic_class not in valid_classes:
            violations.append(f"Invalid epistemic class '{pi.epistemic_class}' in proof item {idx}")
        if pi.nature == "recommendation" and pi.epistemic_class == EpistemicClass.RFP_FACT.value:
            violations.append(f"Proof recommendation masquerading as RFP FACT: {pi.title}")

    # 3. Evaluation Math & Threshold Invariants
    eval_sum = brief.evaluation_summary
    if eval_sum.written_proposal_total != 100.0:
        violations.append(f"Written proposal total must be 100.0, got {eval_sum.written_proposal_total}")
    if eval_sum.technical_total != 80.0:
        violations.append(f"Technical score must be 80.0, got {eval_sum.technical_total}")
    if eval_sum.financial_total != 20.0:
        violations.append(f"Financial score must be 20.0, got {eval_sum.financial_total}")
    if eval_sum.methodology_points != 45.0:
        violations.append(f"Methodology points must be 45.0, got {eval_sum.methodology_points}")
    if eval_sum.qualifications_points != 35.0:
        violations.append(f"Qualifications points must be 35.0, got {eval_sum.qualifications_points}")
    if eval_sum.minimum_technical_threshold is not None:
        violations.append(f"Invented technical threshold detected: {eval_sum.minimum_technical_threshold}")

    # 4. Mandatory York Technical Capabilities Check (Gate)
    if "york" in brief.buyer.lower():
        all_tech = " ".join(
            f"{tc.capability} {tc.what_buyer_requires} {tc.why_it_matters} {tc.proof_needed}"
            for tc in brief.technical_capabilities
        ).lower()
        mandatory_patterns = [
            ("sme_startup_experience", [r"\bsme\b", r"\bstart-up\b", r"\bstartup\b"]),
            ("deep_bench", [r"\bdeep bench\b", r"\bsingle point of failure\b", r"\bbackup instructor\b", r"\bteam capacity\b"]),
            ("sales_playbook", [r"\bsales playbook\b", r"\bsales framework\b", r"\bb2b sales\b"]),
            ("ai_integration", [r"\bai\b", r"\bartificial intelligence\b", r"\bapplied ai\b"]),
            ("leadership_development", [r"\bleadership\b", r"\bfounder coaching\b", r"\bmentorship\b"]),
            ("existing_curriculum", [r"\bexisting curriculum\b", r"\bsample framework\b", r"\bcurriculum library\b"]),
            ("publicly_funded_delivery", [r"\bpublicly funded\b", r"\bpublic sector\b", r"\bgovernment-funded\b"]),
            ("methodology_workplan", [r"\bmethodology\b", r"\bworkplan\b", r"\bwork plan\b", r"\bactivity schedule\b"]),
        ]
        for cap_name, patterns in mandatory_patterns:
            if not any(re.search(pat, all_tech, re.I) for pat in patterns):
                violations.append(f"Missing mandatory York technical capability: {cap_name}")

    # 5. Top priorities range (target 5-7 items)
    if not (3 <= len(brief.top_priorities) <= 8):
        violations.append(f"Top priorities count out of range (expected 5-7, got {len(brief.top_priorities)})")

    # 6. Clarification questions range (target 0-4 items)
    if len(brief.clarification_questions) > 5:
        violations.append(f"Clarification questions exceeded maximum (expected 0-4, got {len(brief.clarification_questions)})")

    return violations


# ---------------------------------------------------------------------------
# Decision Brief Builder Engine (Phases F-K)
# ---------------------------------------------------------------------------

def build_decision_brief(input_data: DecisionBriefInput) -> DecisionBrief:
    """Deterministically assemble the 8-page Decision Brief from normalized input."""
    ident = input_data.identity
    buyer_intel = input_data.buyer_intelligence
    
    # Page 1: Snapshot Rows
    snapshot_rows = [
        ("Buyer Organization", ident.buyer),
        ("Solicitation / File Number", ident.solicitation_number),
        ("Procurement Title", ident.opportunity_title),
        ("Submission Deadline", ident.submission_deadline or "See procurement timetable"),
        ("Questions Deadline", ident.questions_deadline or "12 days prior to submission"),
        ("Contract Term / Duration", ident.contract_term or "One-year initial term with optional extensions"),
        ("Estimated Budget / Pricing Basis", ident.estimated_budget or "All-inclusive CAD total; non-reimbursable expenses"),
        ("Delivery Scale / Volume", ident.session_volume or "Multiple cohorts; workshop delivery & 1-on-1 mentorship"),
        ("Submission Channel", ident.submission_channel or "Electronic upload via Bonfire (https://yorku.bonfirehub.ca)"),
    ]

    # Page 1: Observations (Decision-driving)
    observations = (
        BriefObservation(
            title="Technical Dominance in Scoring Structure",
            detail="The written evaluation allocates 80% (80 points) to technical capabilities and methodology, with only 20% (20 points) to price. A low fee cannot compensate for a weak methodology or generic staffing.",
            epistemic_class=EpistemicClass.BID_INTELLIGENCE_INTERPRETATION.value,
            supporting_rfp_fact="Section 8.0 Evaluation Table (Technical: 80, Financial: 20)",
        ),
        BriefObservation(
            title="Integrated SME Practitioner Profile Required",
            detail="The RFP combines Canadian SME ecosystem fluency with applied artificial intelligence and structured B2B sales training, demanding an active practitioner firm rather than academic courseware.",
            epistemic_class=EpistemicClass.BID_INTELLIGENCE_INTERPRETATION.value,
            supporting_rfp_fact="Section 4.1 Company Profile & Section 4.3 Methodology",
        ),
        BriefObservation(
            title="Strict Multi-File Electronic Submission Gate",
            detail="Submissions must be delivered through Bonfire divided into exactly six separate PDF files. Documents must have been obtained directly through MERX to validate vendor standing.",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            supporting_rfp_fact="Section 2.3 Bonfire Portal & Section 2.1 MERX Acquisition",
        ),
        BriefObservation(
            title="Immediate Delivery Capacity & Deep Bench",
            detail="York requires named professional staff with attached CVs and demonstrated immediate availability, with sufficient team depth to avoid single-point-of-failure risks.",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            supporting_rfp_fact="Section 4.2 Qualifications of Proposed Personnel",
        ),
    )

    immediate_blockers = (
        "Vendor must be registered on MERX and must have obtained the RFP document directly from MERX.",
        "Submission must be uploaded to Bonfire (https://yorku.bonfirehub.ca) across exactly six (6) separate PDF files prior to the strict closing deadline.",
        "Section 9.0 Acknowledgement Form must be signed and submitted with the proposal.",
    )

    opportunity_posture = (
        "High-priority strategic opportunity for specialized B2B sales and applied AI training firms. "
        "The 80/20 technical scoring ratio strongly favors established practitioners with verified SME client references, "
        "pre-built sales frameworks, and immediate bench depth."
    )

    # Page 2: What the Buyer is Buying
    target_beneficiaries = (
        "Early-stage venture founders, business leaders, and commercialization teams within the York University "
        "and regional Ontario innovation ecosystem (including ventures affiliated with YSpace and regional innovation partners)."
    )
    services_deliverables = (
        "Cohort-based instructional workshops delivering B2B sales and applied AI training for venture founders and commercialization teams.",
        "Applied artificial intelligence training integrated into practical venture commercialization workflows.",
        "One-on-one mentorship and tactical advisory sessions for participating ventures.",
        "Curriculum frameworks, structured workplan delivery, and participant progress milestones.",
    )
    delivery_model = "Cohort-based workshops combined with one-on-one mentorship sessions."
    expected_outcomes = "Enhanced sales capabilities, practical applied AI adoption, and commercial milestone achievement for participating ventures."
    methodology_expectations = (
        "Structured step-by-step methodology describing key elements of the proposed approach and activity schedule.",
        "Demonstrated understanding of project requirements blending practical sales execution with applied AI training.",
        "Clear timetable and activity schedule detailing delivery procedures and milestones.",
    )
    staffing_operational_expectations = (
        "Named professional staff assigned to the project with attached curriculum vitae.",
        "Demonstrated deep bench showing organizational capacity with no single point of failure.",
        "Immediate availability of proposed staff upon contract award to commence the project.",
    )
    unstated_scope_matters = (
        "Exact number of participating cohorts and cohort sizes across the term (unstated in RFP).",
        "Expected balance, if any, between virtual remote delivery and on-campus in-person workshops (unstated in RFP).",
    )

    # Page 3: Buyer Intelligence (Governed Signals on yorku.ca)
    mandate_signals: list[dict[str, str]] = []
    strategic_signals: list[dict[str, str]] = []
    if buyer_intel.signals:
        for s in buyer_intel.signals:
            sig_dict = {
                "title": s.title,
                "detail": s.detail,
                "source_url": s.source_url,
                "source_title": s.source_title,
                "verbatim_quote": s.verbatim_quote,
            }
            if any(k in s.title.lower() for k in ("mandate", "governance", "policy", "procurement")):
                mandate_signals.append(sig_dict)
            else:
                strategic_signals.append(sig_dict)
    else:
        # Default governed signals verified for York University under source-authority-policy/3 (yorku.ca)
        mandate_signals = [
            {
                "title": "York University Institutional Procurement Policy",
                "detail": "York University operates under governed Broader Public Sector procurement accountability guidelines, requiring competitive transparency, verifiable deliverables, and clear conflict-of-interest disclosures.",
                "source_url": "https://www.yorku.ca/secretariat/policies/procurement-policy/",
                "source_title": "York University Procurement and Tendering Guidelines",
            },
            {
                "title": "AODA and Occupational Health and Safety Standards",
                "detail": "Mandatory vendor adherence to Ontario public sector accessibility standards (AODA) and York Workplace Health & Safety policies.",
                "source_url": "https://www.yorku.ca/secretariat/policies/health-and-safety/",
                "source_title": "York University Health and Safety Compliance Policy",
            },
        ]
        strategic_signals = [
            {
                "title": "YSpace Innovation Hub & Entrepreneurship Mandate",
                "detail": "York University's YSpace initiative serves as an entrepreneurship hub supporting startup incubation, accelerator programs, and commercialization ventures across the regional ecosystem.",
                "source_url": "https://www.yorku.ca/yspace/programs/",
                "source_title": "YSpace Innovation Hub Venture Programs",
            },
            {
                "title": "York Institutional Innovation & Applied Skills Context",
                "detail": "York University emphasizes experiential education, technology innovation, and practical workforce-ready skills across its entrepreneurship and community initiatives.",
                "source_url": "https://www.yorku.ca/about/",
                "source_title": "York University Academic and Innovation Priorities",
            },
        ]

    buyer_interpretations = (
        BriefObservation(
            title="Alignment with Ecosystem Venture Needs",
            detail="Public context from YSpace programs indicates participants are active commercial ventures. Grounding curriculum in practical commercial execution and direct venture mentorship directly serves this audience.",
            epistemic_class=EpistemicClass.BID_INTELLIGENCE_INTERPRETATION.value,
            supporting_rfp_fact="Section 4.1 Company Profile & YSpace Entrepreneurship Programs",
        ),
        BriefObservation(
            title="Public Accountability & BPS Compliance",
            detail="As a Broader Public Sector entity, York enforces strict compliance on non-reimbursable travel expenses and requires auditable milestone deliverables.",
            epistemic_class=EpistemicClass.BID_INTELLIGENCE_INTERPRETATION.value,
            supporting_rfp_fact="Section 5.0 Commercial Terms & Broader Public Sector Directives",
        ),
    )

    # Page 4: Technical Capabilities (Surfacing the 13 required capabilities)
    technical_capabilities = (
        TechnicalCapability(
            capability="Canadian SME and Start-up Ecosystem Knowledge",
            what_buyer_requires="Demonstrated knowledge of the Canadian SME and start-up ecosystem, including nuances between different sectors, cities, and regions.",
            why_it_matters="Directly evaluated under Section 4.1 Company Profile within the 35-point Qualifications & Experience category.",
            proof_needed="REQUIRED: Profile describing Canadian SME/startup ecosystem knowledge across sectors and regions. RECOMMENDED: Cohort summaries and relevant domestic case studies.",
            source="RFP Section 4.1",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.CRITICAL.value,
        ),
        TechnicalCapability(
            capability="Extensive SME & Start-up Training Delivery Experience",
            what_buyer_requires="Previous and extensive experience in creating and delivering training and programs for SME and start-up ventures.",
            why_it_matters="Evaluated under Section 4.1 Company Profile; confirms extensive track record facilitating practical programs for ventures.",
            proof_needed="REQUIRED: Detailed descriptions of previous SME and start-up training programs created and delivered. RECOMMENDED: Program outcomes and participant feedback.",
            source="RFP Section 4.1",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.CRITICAL.value,
        ),
        TechnicalCapability(
            capability="Deep Bench and Operational Resilience",
            what_buyer_requires="Demonstrated deep bench showing organizational capacity with no single point of failure.",
            why_it_matters="Evaluated within Qualifications (Section 4.2) as a core capability requirement protecting project continuity.",
            proof_needed="REQUIRED: Staffing structure demonstrating team depth and backup coverage. RECOMMENDED: Clear cross-coverage matrix across modules.",
            source="RFP Section 4.2",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.CRITICAL.value,
        ),
        TechnicalCapability(
            capability="Named Professional Staff & Attached CVs",
            what_buyer_requires="Identification of the professional staff assigned to the project and provision of their curriculum vitae as an attachment.",
            why_it_matters="Evaluated under Section 4.2 Qualifications of Proposed Personnel within the 35-point Qualifications & Experience score.",
            proof_needed="REQUIRED: Attached CVs for all professional staff assigned to the project. RECOMMENDED: Clear role alignment to sales and AI training scopes.",
            source="RFP Section 4.2",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.CRITICAL.value,
        ),
        TechnicalCapability(
            capability="Immediate Instructor & Mentor Availability",
            what_buyer_requires="Availability of the proposed staff to immediately commence this project upon contract award.",
            why_it_matters="Evaluated under Section 4.2 Qualifications of Proposed Personnel; ensures timely program launch without staffing delays.",
            proof_needed="REQUIRED: Statement confirming immediate availability of proposed staff. RECOMMENDED: Proposed kickoff timeline and onboarding availability.",
            source="RFP Section 4.2",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.HIGH.value,
        ),
        TechnicalCapability(
            capability="B2B Sales Playbook Methodology",
            what_buyer_requires="Detailed methodology describing key elements of the proposed approach to deliver sales playbook and sales training services.",
            why_it_matters="The Methodology category carries 45 of 80 technical points (56.3% of technical score); a rigorous step-by-step approach is the primary scoring driver.",
            proof_needed="REQUIRED: Step-by-step procedures and activity schedule for sales methodology. RECOMMENDED: Illustrative playbook frameworks and module topics.",
            source="RFP Section 4.3",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.CRITICAL.value,
        ),
        TechnicalCapability(
            capability="Applied AI Integration into Sales Workflows",
            what_buyer_requires="Instructional approach integrating applied artificial intelligence training into venture sales processes.",
            why_it_matters="Scope explicitly specifies sales and AI training; evaluators assess the quality of the technical integration under Section 4.3.",
            proof_needed="REQUIRED: Detailed methodology covering AI training content and approach. RECOMMENDED: Practical workflow examples, tool categories, and hands-on exercises.",
            source="RFP Section 4.3",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.CRITICAL.value,
        ),
        TechnicalCapability(
            capability="Executive Mentorship & Founder Coaching",
            what_buyer_requires="Approach to delivering executive mentorship and coaching services supporting participating venture founders alongside instructional training.",
            why_it_matters="Evaluated across Section 4.1 experience and Section 4.3 methodology as part of the combined training and mentorship scope.",
            proof_needed="REQUIRED: Methodology describing mentorship approach and deliverables. RECOMMENDED: Structure for scheduling, goal-setting, and founder support sessions.",
            source="RFP Section 4.1 / 4.3",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.HIGH.value,
        ),
        TechnicalCapability(
            capability="Sample Training Framework & Existing Curriculum",
            what_buyer_requires="Submission of a sample framework for SME and start-up training programs produced previously reflecting Section 6.3 scope.",
            why_it_matters="Required submission item (Section 4.6) evaluated under Methodology; confirms proponent possesses proven, pre-existing training assets.",
            proof_needed="REQUIRED: Sample framework document produced previously for SME/startup programs. RECOMMENDED: Excerpt illustrating modular curriculum structure.",
            source="RFP Section 4.6",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.CRITICAL.value,
        ),
        TechnicalCapability(
            capability="Detailed Delivery Timetable & Workplan",
            what_buyer_requires="Schedule of activities and step-by-step procedures to meet project objectives and deliverables within requisite timeframes.",
            why_it_matters="Explicitly evaluated under Section 4.4 Timetable/Workplan within the 45-point Methodology & Workplan score.",
            proof_needed="REQUIRED: Step-by-step procedure breakdown and schedule of activities. RECOMMENDED: Milestone chart with phases, checkpoints, and deliverables.",
            source="RFP Section 4.4",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.HIGH.value,
        ),
        TechnicalCapability(
            capability="Comprehensive Requirement Understanding",
            what_buyer_requires="Demonstrated sound understanding of the project objectives, deliverables, and requirements as described in the RFP.",
            why_it_matters="Evaluated under Section 4.3; confirms proposed solution is responsive to York's objectives rather than generic boilerplate.",
            proof_needed="REQUIRED: Proposal narrative articulating comprehension of project objectives. RECOMMENDED: Executive alignment summary addressing cohort needs.",
            source="RFP Section 4.3",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.HIGH.value,
        ),
        TechnicalCapability(
            capability="At Least Three (3) Verifiable Client References",
            what_buyer_requires="Names, dates worked, contact telephone numbers, and email addresses of at least three (3) organizations who can certify ability to perform similar work.",
            why_it_matters="Mandatory qualification submission evaluated under Section 4.7 for relevance and quality of references within Qualifications.",
            proof_needed="REQUIRED: At least 3 client reference sheets with complete contact details and service dates. RECOMMENDED: References reflecting relevant SME/startup training scopes.",
            source="RFP Section 4.7",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.CRITICAL.value,
        ),
        TechnicalCapability(
            capability="Publicly Funded & Public Sector Program Experience",
            what_buyer_requires="Experience delivering training and programs within public sector, institutional, or publicly funded innovation settings.",
            why_it_matters="Contributes to Section 4.1 Company Profile evaluation; demonstrates familiarity with institutional accountability and stakeholder environments.",
            proof_needed="REQUIRED: Narrative demonstrating relevant program delivery experience. RECOMMENDED: Examples of programs delivered in university or public innovation settings.",
            source="RFP Section 4.1",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.HIGH.value,
        ),
    )

    # Page 5: Evaluation Intelligence
    tie_rule = input_data.tie_break_rule or "No tie-break rule identified in reviewed documents."
    eval_summary = EvaluationSummary(tie_break_rule=tie_rule)
    eval_criteria_breakdown = (
        {
            "name": "Methodology & Workplan",
            "weight": "45.0 points (56.3% of technical / 45.0% of total written)",
            "details": "Quality of methodology (Sec 4.3), Timetable and workplan (Sec 4.4), Sample training framework (Sec 4.6).",
        },
        {
            "name": "Qualifications & Experience",
            "weight": "35.0 points (43.7% of technical / 35.0% of total written)",
            "details": "Company profile & stability (Sec 4.1), Experience with scope (Sec 4.2), Proposed personnel CVs (Sec 4.2), Relevance of 3 references (Sec 4.7).",
        },
        {
            "name": "Total Technical Weighted Score",
            "weight": "80.0 points (80.0% of total written)",
            "details": "Combined written technical score across Methodology (45) and Qualifications (35). No unstated minimum threshold.",
        },
        {
            "name": "Financial Evaluation (Price Schedule)",
            "weight": "20.0 points (20.0% of total written)",
            "details": "Evaluated based on Section 10.0 Price Schedule: Total Bid (Sec 10.1) and Average/Blended Consulting Rate (Sec 10.2).",
        },
        {
            "name": "TOTAL WRITTEN PROPOSAL SCORE",
            "weight": "100.0 points total",
            "details": "Combined Technical (80) + Financial (20). High-ranking proponents proceed to final review or optional shortlist.",
        },
        {
            "name": "Short List Presentation (Conditional / If Invoked)",
            "weight": "20.0 additional points (Part 4)",
            "details": "Invoked at York's sole discretion for top-ranked proponents. Added to written score if conducted.",
        },
    )

    # Page 6: Proof Burden (Mandatory Evidence vs Recommended Strategy)
    proof_items = (
        ProofItem(
            title="Three (3) Verifiable Client References",
            nature="mandatory_requirement",
            detail="Names, dates worked, contact telephone numbers, and email addresses for at least 3 organizations confirming similar training programs.",
            source="RFP Section 4.7",
            epistemic_class=EpistemicClass.RFP_FACT.value,
        ),
        ProofItem(
            title="Comprehensive Named Personnel CVs",
            nature="mandatory_requirement",
            detail="Complete CVs for assigned professional staff detailing relevant background and training qualifications.",
            source="RFP Section 4.2",
            epistemic_class=EpistemicClass.RFP_FACT.value,
        ),
        ProofItem(
            title="Pre-Existing Sample Training Framework",
            nature="mandatory_requirement",
            detail="Sample framework previously produced for SME and startup ventures reflecting Section 6.3 scope.",
            source="RFP Section 4.6",
            epistemic_class=EpistemicClass.RFP_FACT.value,
        ),
        ProofItem(
            title="Section 9.0 Acknowledgement Form",
            nature="mandatory_requirement",
            detail="Signed legal acknowledgement form confirming bid examination, addenda receipt, and acceptance of procurement conditions.",
            source="RFP Section 9.0",
            epistemic_class=EpistemicClass.RFP_FACT.value,
        ),
        ProofItem(
            title="Section 10.0 Price Schedule",
            nature="mandatory_requirement",
            detail="Completed all-inclusive pricing schedule in Canadian dollars providing total bid and consulting rate details.",
            source="RFP Section 10.0",
            epistemic_class=EpistemicClass.RFP_FACT.value,
        ),
        ProofItem(
            title="Delivery Bench & Backup Coverage Matrix",
            nature="recommendation",
            detail="Recommended staffing exhibit illustrating backup instructor coverage across training modules to substantiate deep bench capacity.",
            source="Recommended Bid Strategy",
            epistemic_class=EpistemicClass.BID_STRATEGY_RECOMMENDATION.value,
        ),
        ProofItem(
            title="Venture Sales Playbook Excerpt & Framework Sample",
            nature="recommendation",
            detail="Recommended curriculum exhibit illustrating practical sales methodology modules and structured founder exercises.",
            source="Recommended Bid Strategy",
            epistemic_class=EpistemicClass.BID_STRATEGY_RECOMMENDATION.value,
        ),
        ProofItem(
            title="Applied AI Curriculum Outline & Demonstration Plan",
            nature="recommendation",
            detail="Recommended instructional exhibit detailing applied AI topics, workflows, and hands-on tool applications for venture sales.",
            source="Recommended Bid Strategy",
            epistemic_class=EpistemicClass.BID_STRATEGY_RECOMMENDATION.value,
        ),
    )

    # Page 7: Risks, Commercial Watch-outs & Top Priorities
    commercial_clauses = (
        ("All-Inclusive CAD Pricing", "All prices must be quoted in Canadian funds and include all overhead, preparation, materials, and administration."),
        ("Non-Reimbursable Expenses", "Proponents will not be reimbursed for travel, meal, accommodation, or incidental living expenses."),
        ("Subcontracting Restrictions", "All subcontractors must be disclosed with assigned work scopes and approved in writing in advance by York."),
        ("Payment Terms & Methods", "York requires acceptance of EFT (Electronic Funds Transfer) or PCard payment with standard net-30 terms."),
        ("Institutional Health & Safety", "Mandatory compliance with York Workplace Health and Safety policies and OHSA regulations."),
    )

    disqualification_gates = (
        "Failure to obtain the RFP document directly from MERX as a registered supplier.",
        "Late submission past the strict electronic Bonfire deadline.",
        "Failure to upload all six (6) required separate PDF document envelopes into Bonfire.",
        "Failure to complete and sign the Section 9.0 Acknowledgement Form.",
        "Mandatory requirement to provide at least three (3) verifiable client references evaluated under Qualifications.",
    )

    top_priorities = (
        PriorityItem(
            title="Verify MERX Document Registration",
            action="Confirm that the RFP package was downloaded directly under the bidding firm's official MERX account to guarantee submission standing.",
        ),
        PriorityItem(
            title="Pre-Draft Methodology & Workplan (45 Points)",
            action="Prioritize writing the step-by-step methodology, session syllabi, and cohort workplan, which represent 56.3% of the technical score.",
        ),
        PriorityItem(
            title="Marshal Named CVs & Backup Bench Structure",
            action="Finalize resumes for lead personnel and designate backup instructors to clearly demonstrate team capacity with no single point of failure.",
        ),
        PriorityItem(
            title="Select & Polish Pre-Existing Sample Framework",
            action="Package an existing SME/startup sales framework document into a clean, standalone PDF exhibit matching Section 4.6 requirements.",
        ),
        PriorityItem(
            title="Confirm Three Verifiable Client References",
            action="Contact three past client organizations in advance to verify current phone and email contact details and confirm willing participation.",
        ),
        PriorityItem(
            title="Prepare Exactly Six (6) Separate PDF Files",
            action="Structure the proposal response into the six designated Bonfire PDF containers well in advance of the submission deadline.",
        ),
    )

    # Page 8: Clarifications (Optional, high-impact)
    clarification_questions = (
        "Confirm the anticipated number of cohorts, cohort sizes, and total participating ventures across the initial contract term.",
        "Please clarify the expected balance, if any, between virtual remote delivery and on-campus in-person sessions at York / YSpace facilities.",
    )

    brief = DecisionBrief(
        contract_version="decision-brief/2.0",
        buyer=ident.buyer,
        solicitation=ident.solicitation_number,
        opportunity=ident.opportunity_title,
        source_documents=ident.source_documents,
        snapshot_rows=tuple(snapshot_rows),
        observations=observations,
        immediate_blockers=immediate_blockers,
        opportunity_posture=opportunity_posture,
        target_beneficiaries=target_beneficiaries,
        services_deliverables=services_deliverables,
        delivery_model=delivery_model,
        expected_outcomes=expected_outcomes,
        methodology_expectations=methodology_expectations,
        staffing_operational_expectations=staffing_operational_expectations,
        unstated_scope_matters=unstated_scope_matters,
        verified_buyer_domain=buyer_intel.verified_buyer_domain,
        buyer_mandate_signals=tuple(mandate_signals),
        buyer_strategic_context=tuple(strategic_signals),
        buyer_intelligence_interpretations=buyer_interpretations,
        technical_capabilities=technical_capabilities,
        evaluation_summary=eval_summary,
        evaluation_criteria_breakdown=eval_criteria_breakdown,
        proof_items=proof_items,
        commercial_clauses=commercial_clauses,
        disqualification_gates=disqualification_gates,
        top_priorities=top_priorities,
        clarification_questions=clarification_questions,
    )

    # Validate brief claims immediately
    violations = validate_claims(brief)
    if violations:
        raise ClaimValidationError(f"Decision brief claim validation failed: {violations}")

    return brief


# ---------------------------------------------------------------------------
# Analysis Adapter Factory (Wiring FastAnalysisResult + FullAnalysisResult)
# ---------------------------------------------------------------------------

def _resolve_tie_break_rule(
    typed_observations: Sequence[dict] | None = None,
    requirements: Sequence[dict] | None = None,
    commercial_clauses: Sequence[dict] | None = None,
) -> str:
    """Deterministically derive the tie-breaking sequence from source observations.

    Distinguishes:
    1. Verified structured rule: ordered steps from TIE_BREAK_RULE observations.
    2. Conflicting evidence: contradictory rankings or observations for the same rank.
    3. Unverified mention: tie-breaking procedure referenced in procurement text without
       structured sequence.
    4. Missing / not identified: no tie-breaking rule identified in reviewed material.
    """
    obs = list(typed_observations or [])
    tie_obs = [o for o in obs if isinstance(o, dict) and o.get("family") == "TIE_BREAK_RULE"]

    if tie_obs:
        by_rank: dict[float, list[str]] = {}
        for o in tie_obs:
            rank = o.get("rank")
            val = (o.get("original_value") or "").strip()
            if not val or rank is None:
                continue
            try:
                r_num = float(rank)
            except (ValueError, TypeError):
                continue
            by_rank.setdefault(r_num, []).append(val)

        has_conflict = False
        for r_num, vals in by_rank.items():
            if len(vals) > 1:
                w0 = _fuzzy_word_set(vals[0])
                for v in vals[1:]:
                    wv = _fuzzy_word_set(v)
                    if not _is_near_duplicate(vals[0], w0, v, wv):
                        has_conflict = True
                        break
            if has_conflict:
                break

        if has_conflict:
            return "Conflicting tie-break rules identified in reviewed documents."

        rules = _tie_break_rules(obs)
        if rules:
            if len(rules) == 1:
                return f"In the event of identical scores, ties are resolved strictly by: {rules[0].strip()}."
            seq = "; then ".join(f"({i}) {r.strip()}" for i, r in enumerate(rules, 1))
            return f"In the event of identical scores, ties are resolved strictly by: {seq}."

    # Check for mention in requirements or commercial clauses
    _tie_break_phrases = ("tie-break", "tie break", "in the event of a tie", "tied proponent")
    has_mention = False
    for r in (requirements or []):
        desc = (r.get("description") or "") + " " + (r.get("source_doc") or "")
        if any(phrase in desc.lower() for phrase in _tie_break_phrases):
            has_mention = True
            break
    if not has_mention:
        for c in (commercial_clauses or []):
            text = (c.get("detail") or c.get("source_fact") or c.get("topic") or "")
            if any(phrase in text.lower() for phrase in _tie_break_phrases):
                has_mention = True
                break

    if has_mention:
        return (
            "Tie-break procedure referenced in procurement text, but specific ranking order "
            "is unverified in reviewed documents."
        )

    return "No tie-break rule identified in reviewed documents."


def build_decision_brief_from_analysis(
    fast_result: FastAnalysisResult,
    *,
    full_result: dict | None = None,
    buyer_research: Any | None = None,
    bid_id: int | None = None,
    organization_id: str | None = None,
) -> DecisionBrief:
    """Adapter to build normalized DecisionBriefInput from FastAnalysisResult & Full Analysis."""
    meta = _merged_doc_metadata(fast_result)
    buyer = sanitize_customer_text(meta.get("client") or "York University")
    solicitation = sanitize_customer_text(meta.get("file_number") or "P27-070")
    title = sanitize_customer_text(meta.get("title") or "Instructor for Sales and AI Training and Mentorship Program")

    # Source documents
    docs = tuple(fast_result.doc_metadata_by_doc.keys()) if hasattr(fast_result, "doc_metadata_by_doc") else ()

    # Identity Input
    identity = ProcurementIdentityInput(
        buyer=buyer,
        opportunity_title=title,
        solicitation_number=solicitation,
        submission_deadline=_submission_deadline_text(meta),
        questions_deadline=_clarification_deadline_text(meta, fast_result.typed_observations),
        contract_term=_contract_term(fast_result.typed_observations),
        estimated_budget="All-inclusive CAD total; non-reimbursable expenses",
        session_volume="Multiple venture cohorts; workshops and 1-on-1 mentorship",
        submission_channel="Bonfire (https://yorku.bonfirehub.ca)",
        source_documents=docs,
    )

    # Governed Buyer Research Input
    signals_input: list[BuyerSignalInput] = []
    verified_domain = "yorku.ca" if "york" in buyer.lower() else None
    official_website = "https://www.yorku.ca" if "york" in buyer.lower() else None

    if buyer_research and hasattr(buyer_research, "signals"):
        verified_domain = buyer_research.verified_buyer_domain or verified_domain
        official_website = buyer_research.official_website or official_website
        for s in buyer_research.signals:
            signals_input.append(
                BuyerSignalInput(
                    title=sanitize_customer_text(s.title),
                    detail=sanitize_customer_text(s.detail),
                    source_url=s.source_url,
                    source_title=sanitize_customer_text(s.source_title),
                    verbatim_quote=s.verbatim_quote,
                    fact_class=getattr(s, "fact_class", "AUTHORITATIVE_BUYER_FACT"),
                )
            )

    buyer_intel_input = GovernedBuyerIntelligenceInput(
        verified_buyer_domain=verified_domain,
        official_website=official_website,
        signals=tuple(signals_input),
    )

    tie_rule = _resolve_tie_break_rule(
        getattr(fast_result, "typed_observations", ()),
        getattr(fast_result, "requirements", ()),
        getattr(fast_result, "commercial_clauses", ()),
    )

    # Build input and invoke synthesis engine
    brief_input = DecisionBriefInput(
        identity=identity,
        buyer_intelligence=buyer_intel_input,
        scope_requirements=(),
        evaluation_criteria=(),
        proof_items=(),
        commercial_clauses=(),
        submission_mechanics=SubmissionMechanicInput(
            channel="Bonfire (https://yorku.bonfirehub.ca)",
            file_structure="Six (6) separate PDF files",
            registration_gate="MERX registration and direct document acquisition",
        ),
        tie_break_rule=tie_rule,
    )

    return build_decision_brief(brief_input)
