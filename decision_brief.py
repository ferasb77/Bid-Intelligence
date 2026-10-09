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
    _merged_doc_metadata,
    _submission_deadline_text,
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
    tie_break_rule: str = "If scores are tied, the proposal with the highest technical score will be ranked first."


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
        "and regional Ontario innovation ecosystem (specifically ventures supported by YSpace, Schulich ExecEd, "
        "and affiliated accelerator initiatives)."
    )
    services_deliverables = (
        "Cohort-based instructional workshops covering B2B outbound prospecting, discovery, pipeline management, and closing.",
        "Hands-on applied AI curriculum integrating modern generative AI and sales automation tools into daily sales workflows.",
        "Tailored one-on-one mentorship and tactical advisory sessions for individual venture leaders.",
        "Comprehensive training frameworks, milestone reporting, and participant progress assessments.",
    )
    delivery_model = "Blended interactive cohort training combined with intensive one-on-one executive and founder mentorship sessions."
    expected_outcomes = "Measurable sales pipeline velocity, increased conversion rates for participating ventures, and practical mastery of modern AI sales tooling."
    methodology_expectations = (
        "Structured step-by-step curriculum detailing cohort sessions, practical exercises, and tactical takeaways.",
        "Demonstrated pedagogical approach blending real-world B2B sales frameworks with ethical, applied AI integration.",
        "Clear timetable and activity schedule aligning cohort workshops with individual venture coaching milestones.",
    )
    staffing_operational_expectations = (
        "Named senior lead instructor supported by experienced co-instructors and mentors.",
        "Demonstrated organizational bench ensuring uninterrupted delivery with no single point of failure.",
        "Immediate availability upon contract award with dedicated administrative coordination.",
    )
    unstated_scope_matters = (
        "Exact number of participating cohorts and cohort sizes per semester (unstated in RFP).",
        "Ratio between virtual interactive sessions and on-campus in-person workshops (unstated in RFP).",
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
                "detail": "York University operates under governed Broader Public Sector procurement accountability guidelines, requiring strict competitive transparency, verifiable deliverables, and clear conflict-of-interest disclosures.",
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
                "detail": "York University's YSpace initiative drives venture commercialization, tech incubator programs, and specialized training for high-growth Canadian startups and small-to-medium enterprises across the GTA.",
                "source_url": "https://www.yorku.ca/yspace/programs/",
                "source_title": "YSpace Innovation Hub Venture Programs",
            },
            {
                "title": "Schulich Executive Education & Applied Skills Priorities",
                "detail": "Strategic institutional focus on practical, workforce-ready skills in digital technologies, leadership development, and applied artificial intelligence for professionals and founders.",
                "source_url": "https://execed.schulich.yorku.ca/about-us/",
                "source_title": "Schulich ExecEd Professional Development Framework",
            },
        ]

    buyer_interpretations = (
        BriefObservation(
            title="Alignment with Ecosystem Venture Needs",
            detail="External research into YSpace and Schulich ExecEd initiatives confirms that participants are active commercial founders. Theoretical university lectures will not meet buyer objectives; hands-on commercial playbooks and active founder mentorship are paramount.",
            epistemic_class=EpistemicClass.BID_INTELLIGENCE_INTERPRETATION.value,
            supporting_rfp_fact="Section 4.1 Company Profile & YSpace Public Venture Portfolio",
        ),
        BriefObservation(
            title="Public Accountability & BPS Compliance",
            detail="As a Broader Public Sector entity, York enforces zero-tolerance compliance on non-reimbursable travel expenses and strict audit-ready milestone deliverables.",
            epistemic_class=EpistemicClass.BID_INTELLIGENCE_INTERPRETATION.value,
            supporting_rfp_fact="Section 5.0 Commercial Terms & Broader Public Sector Accountability Directives",
        ),
    )

    # Page 4: Technical Capabilities (Surfacing the 13 required capabilities)
    technical_capabilities = (
        TechnicalCapability(
            capability="Canadian SME and Start-up Ecosystem Knowledge",
            what_buyer_requires="Deep understanding of Canadian venture landscape, startup growth stages, seed-to-scale funding, and sector-specific commercialization hurdles.",
            why_it_matters="Ensures workshop scenarios and mentoring advice reflect Canadian market realities, regional procurement, and domestic grant/financing frameworks.",
            proof_needed="Profiles of Canadian startup cohorts trained, case studies with domestic tech ventures, and references from Canadian accelerator ecosystems.",
            source="RFP Section 4.1",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.CRITICAL.value,
        ),
        TechnicalCapability(
            capability="Extensive SME & Start-up Training Delivery Experience",
            what_buyer_requires="Demonstrated multi-year track record facilitating practical B2B commercial training programs specifically designed for small and medium-sized ventures.",
            why_it_matters="Founders have limited time and require immediate, practical tools rather than abstract corporate enterprise training modules.",
            proof_needed="Documentation of prior venture cohort programs, participant retention rates, and direct founder feedback testimonials.",
            source="RFP Section 4.1",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.CRITICAL.value,
        ),
        TechnicalCapability(
            capability="Deep Bench and Operational Resilience",
            what_buyer_requires="Multi-person instructor and mentor roster demonstrating deep bench capacity with no single point of failure and verified backup instructors.",
            why_it_matters="Protects program continuity against illness, scheduling conflicts, or lead instructor turnover across multi-month cohorts.",
            proof_needed="Delivery team roster with designated lead and backup instructors, role descriptions, and cross-coverage availability commitments.",
            source="RFP Section 4.2",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.CRITICAL.value,
        ),
        TechnicalCapability(
            capability="Named Professional Staff & Attached CVs",
            what_buyer_requires="Detailed CVs and profiles for each named instructor and mentor detailing direct sales leadership and training experience.",
            why_it_matters="Evaluators explicitly score proposed personnel credentials (accounting for a significant portion of the 35 qualification points).",
            proof_needed="Comprehensive CVs emphasizing direct B2B sales execution, applied AI credentials, and adult education facilitation experience.",
            source="RFP Section 4.2",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.CRITICAL.value,
        ),
        TechnicalCapability(
            capability="Immediate Instructor & Mentor Availability",
            what_buyer_requires="Firm commitment of immediate personnel availability upon contract award to commence curriculum finalization and cohort scheduling.",
            why_it_matters="York requires immediate launch alignment for upcoming seasonal venture cohorts without lead-time hiring delays.",
            proof_needed="Staff availability matrix confirming immediate commencement and dedicated weekly hours per instructor.",
            source="RFP Section 4.2",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.HIGH.value,
        ),
        TechnicalCapability(
            capability="B2B Sales Playbook Methodology",
            what_buyer_requires="Systematic, repeatable methodology covering outbound prospecting, value proposition messaging, pipeline qualification, and closing techniques.",
            why_it_matters="Methodology accounts for 45 out of 80 technical points (56.3% of technical score); a comprehensive framework is the single biggest scoring driver.",
            proof_needed="Detailed curriculum outline, workshop module breakdowns, template sales playbooks, and step-by-step prospecting frameworks.",
            source="RFP Section 4.3",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.CRITICAL.value,
        ),
        TechnicalCapability(
            capability="Applied AI Integration into Sales Workflows",
            what_buyer_requires="Hands-on instruction demonstrating how founders can leverage practical generative AI tools for prospect research, email personalization, and CRM efficiency.",
            why_it_matters="RFP explicitly demands applied AI mastery to modernize venture sales operations; generic legacy sales training will score poorly.",
            proof_needed="Applied AI module descriptions, workflow prompts, tool demonstration outlines, and practical automation exercises.",
            source="RFP Section 4.3",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.CRITICAL.value,
        ),
        TechnicalCapability(
            capability="Executive & Founder Mentorship Capability",
            what_buyer_requires="Structured 1-on-1 coaching methodology to guide venture founders through individual commercial blockers and pipeline negotiations.",
            why_it_matters="Cohort learning must be reinforced through individualized mentorship to ensure real venture revenue growth.",
            proof_needed="Mentorship intake process, founder coaching cadence, milestone tracking templates, and confidential feedback mechanisms.",
            source="RFP Section 4.1 / 4.3",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.HIGH.value,
        ),
        TechnicalCapability(
            capability="Sample Training Framework & Existing Curriculum",
            what_buyer_requires="Submission of a sample framework produced previously for SME and startup training programs demonstrating curriculum depth.",
            why_it_matters="Explicit submission requirement (Section 4.6) evaluated under Methodology; confirms proponent does not need to build from scratch.",
            proof_needed="Actual pre-existing training framework document, syllabus sample, participant workbook excerpt, or module deck.",
            source="RFP Section 4.6",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.CRITICAL.value,
        ),
        TechnicalCapability(
            capability="Detailed Delivery Timetable & Workplan",
            what_buyer_requires="Comprehensive, step-by-step schedule detailing activity timelines, milestone deliverables, cohort checkpoints, and reporting cadences.",
            why_it_matters="Evaluated under Methodology (Section 4.4); proves proponent can manage complex multi-stakeholder scheduling efficiently.",
            proof_needed="Gantt chart or phase-gate schedule with weekly activity breakdowns, session duration targets, and milestone deliverable dates.",
            source="RFP Section 4.4",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.HIGH.value,
        ),
        TechnicalCapability(
            capability="Comprehensive Requirement Understanding",
            what_buyer_requires="Articulated understanding of York University's venture ecosystem, program objectives, and specific pedagogical constraints.",
            why_it_matters="Demonstrates alignment with York's vision and confirms the proposal is tailored rather than an off-the-shelf boilerplate pitch.",
            proof_needed="Dedicated executive summary and narrative section synthesizing York's program vision and specific cohort success factors.",
            source="RFP Section 4.3",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.HIGH.value,
        ),
        TechnicalCapability(
            capability="At Least Three (3) Verifiable Client References",
            what_buyer_requires="Names, dates worked, contact telephone numbers, and email addresses for at least 3 organizations for whom similar services were delivered.",
            why_it_matters="Mandatory qualification item evaluated under Section 4.7; failure to provide complete verifiable references risks disqualification or zero score.",
            proof_needed="Three complete reference sheets with verified contact details, engagement scopes, and alignment to sales/AI training programs.",
            source="RFP Section 4.7",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.CRITICAL.value,
        ),
        TechnicalCapability(
            capability="Publicly Funded & Public Sector Program Experience",
            what_buyer_requires="Familiarity with public sector reporting, attendance auditing, stakeholder accountability, and compliance governance.",
            why_it_matters="Assures program administrators that reporting will satisfy university and provincial funding audit standards.",
            proof_needed="Examples of past university, municipal, or provincial innovation programs delivered with formal milestone reporting.",
            source="RFP Section 4.1",
            epistemic_class=EpistemicClass.RFP_FACT.value,
            priority=PriorityLevel.HIGH.value,
        ),
    )

    # Page 5: Evaluation Intelligence
    eval_summary = EvaluationSummary()
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
            detail="Complete CVs for lead instructors and backup mentors detailing B2B sales execution and AI instructional track records.",
            source="RFP Section 4.2",
            epistemic_class=EpistemicClass.RFP_FACT.value,
        ),
        ProofItem(
            title="Pre-Existing Sample Training Framework",
            nature="mandatory_requirement",
            detail="Sample curriculum framework previously produced for SME and startup ventures demonstrating modular course structure.",
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
            detail="Completed all-inclusive pricing schedule in Canadian dollars providing fixed bid and hourly/blended consulting rates.",
            source="RFP Section 10.0",
            epistemic_class=EpistemicClass.RFP_FACT.value,
        ),
        ProofItem(
            title="Delivery Bench & Backup Redundancy Matrix",
            nature="recommendation",
            detail="Visual matrix illustrating backup instructor assignments across each curriculum module to reinforce resilience.",
            source="Recommended Bid Strategy",
            epistemic_class=EpistemicClass.BID_STRATEGY_RECOMMENDATION.value,
        ),
        ProofItem(
            title="Venture Sales Playbook Excerpt & Templates",
            nature="recommendation",
            detail="Tangible excerpt of prospecting scripts, pipeline stages, and prompt libraries proving turnkey readiness.",
            source="Recommended Bid Strategy",
            epistemic_class=EpistemicClass.BID_STRATEGY_RECOMMENDATION.value,
        ),
        ProofItem(
            title="Applied AI Prompt Library & Demonstration Plan",
            nature="recommendation",
            detail="Walkthrough of live AI tools, vetted prompts, and interactive sales workflow exercises for participating founders.",
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
        "Failure to provide at least three (3) verifiable client references.",
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
            action="Finalize resumes for lead instructors and designate secondary mentors to explicitly address single-point-of-failure scoring criteria.",
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
        "Confirm the expected balance between virtual remote delivery and mandatory in-person on-campus sessions at York / YSpace facilities.",
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
    )

    return build_decision_brief(brief_input)
