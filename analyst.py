"""
Bid Intelligence — AI Compliance, Strategy, and Proposal Analyst.
Provides decision-oriented intelligence across the bid lifecycle:
  1. compliance_review         — draft section vs requirements gap analysis
  2. missing_evidence          — scan matrix for at-risk items and qualification gaps
  3. clarification_qs          — generate strategic, RFP-derived clarification questions
  4. bid_no_bid                — multi-dimensional pursuit evaluation with blocker detection
  5. past_proposal_analyzer    — extract reusable modular blocks and team capabilities
  6. section_drafter           — evidence-based proposal section drafting
  7. submission_readiness_check— final gate check before proposal submission
  8. addendum_analyzer         — scan amendments and supplementary documents for changes
  9. proposal_alignment        — two-call comprehensive proposal alignment audit
"""
import concurrent.futures
import json
import re
from typing import Any
from config import get_anthropic_client, execute_messages_create
from requirement_semantics import has_supplier_qualification_evidence


def _call(system: str, user: str, max_tokens: int = 2048) -> str:
    client = get_anthropic_client()
    response = execute_messages_create(
        client,
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text.strip()


def _parse_json(raw: str) -> dict | list:
    """
    Robustly parse JSON from a model response.
    Handles: markdown fences (complete OR truncated), trailing commentary,
    and JSON cut mid-stream before closing braces.
    """
    # 1. Aggressive fence removal
    text = raw.strip()
    text = re.sub(r"^```[a-z]*\s*\n?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n?```\s*$", "", text)
    text = text.strip()

    # 2. Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 3. Bracket-match: find first { or [ and scan for balanced close
    def _scan(src, open_ch, close_ch):
        start = src.find(open_ch)
        if start == -1:
            return None
        depth, in_str, esc = 0, False, False
        for i, ch in enumerate(src[start:], start):
            if esc:
                esc = False
                continue
            if ch == "\\" and in_str:
                esc = True
                continue
            if ch == '"' and not esc:
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(src[start:i + 1])
                    except json.JSONDecodeError:
                        return None
        return None

    for oc, cc in [('{', '}'), ('[', ']')]:
        result = _scan(text, oc, cc)
        if result is not None:
            return result

    # 4. Truncation repair: JSON cut before model finished writing it.
    start_idx = text.find('{')
    if start_idx == -1:
        start_idx = text.find('[')
    if start_idx != -1:
        fragment = text[start_idx:]
        for end_pos in range(len(fragment) - 1, 0, -1):
            if fragment[end_pos] not in ('}', ']', '"', '0123456789'):
                continue
            chunk = fragment[:end_pos + 1]
            for oc2, cc2 in [('{', '}'), ('[', ']')]:
                diff = chunk.count(oc2) - chunk.count(cc2)
                chunk += cc2 * max(diff, 0)
            try:
                result = json.loads(chunk)
                if isinstance(result, (dict, list)):
                    if isinstance(result, dict):
                        result["_truncated"] = True
                    return result
            except json.JSONDecodeError:
                continue

    # 5. Fallback: recover scalar key/value pairs as flat dict
    pairs = re.findall(r'"([^"]+)"\s*:\s*"([^"]*)"', text)
    numbers = re.findall(r'"([^"]+)"\s*:\s*(-?\d+(?:\.\d+)?)', text)
    if pairs or numbers:
        recovered = dict(pairs)
        recovered.update({k: float(v) if '.' in v else int(v) for k, v in numbers})
        recovered["_truncated"] = True
        return recovered

    raise ValueError(
        f"Could not parse model response as JSON after all repair attempts.\n"
        f"First 300 chars: {raw[:300]}"
    )


# ── 1. Compliance Review ──────────────────────────────────────────────────────
COMPLIANCE_SYSTEM = """You are a senior proposal reviewer and compliance auditor.
Your job is to compare a draft proposal section against the RFP requirements it is meant to address
and identify compliance gaps, weak arguments, and missing evidence. Be specific, direct, and actionable."""

def compliance_review(draft_text: str, requirements: list[dict]) -> dict:
    """Compare draft text against requirements; return structured feedback."""
    reqs_text = "\n".join(
        f"- [{r.get('req_id','')}] ({r.get('category','')}) {r.get('description','')} "
        f"| Evidence required: {r.get('evidence') or 'not specified'}"
        for r in requirements
    )

    prompt = f"""REQUIREMENTS FROM RFP:
{reqs_text}

DRAFT PROPOSAL TEXT:
{draft_text}

Analyze how well the draft addresses each requirement. Return ONLY valid JSON:
{{
  "overall_score": <integer 0-100>,
  "summary": "<2-3 sentence overall assessment>",
  "addressed": [
    {{"req_id": "M1", "finding": "how it is addressed with evidence"}}
  ],
  "weak": [
    {{"req_id": "R3", "finding": "what is present but insufficient", "suggestion": "specific improvement"}}
  ],
  "missing": [
    {{"req_id": "R5", "finding": "completely absent", "suggestion": "what must be added"}}
  ],
  "critical_gaps": ["<most urgent gap 1>", "<most urgent gap 2>"]
}}"""

    raw = _call(COMPLIANCE_SYSTEM, prompt, max_tokens=2048)
    return _parse_json(raw)


# ── 2. Missing Evidence & Qualification Risk Detection ────────────────────────
EVIDENCE_SYSTEM = """You are a senior bid compliance controller. You scan requirement registers and qualification matrices for risk.
Be blunt about what is at risk. Prioritize mandatory pass/fail qualification conditions above all else."""

def missing_evidence(requirements: list[dict], bid_info: dict) -> dict:
    """Scan matrix and surface at-risk items and unassigned requirements."""
    sub_deadline = bid_info.get("submission_deadline", "unknown")
    clar_deadline = bid_info.get("clarification_deadline", "unknown")

    reqs_text = "\n".join(
        f"[{r.get('req_id','')}] {r.get('category','')} | "
        f"Status: {r.get('status','')} | Qual: {r.get('qual_status','UNKNOWN')} | "
        f"Owner: {r.get('owner') or 'UNASSIGNED'} | "
        f"Deadline: {r.get('deadline') or 'not set'} | "
        f"Evidence: {r.get('evidence') or 'not specified'} | "
        f"Description: {r.get('description','')[:120]}"
        for r in requirements
    )

    prompt = f"""BID: {bid_info.get('title','')} — {bid_info.get('client','')}
Submission deadline: {sub_deadline}
Clarification deadline: {clar_deadline}

COMPLIANCE & QUALIFICATION MATRIX:
{reqs_text}

Identify all at-risk and unverified qualification items. Return ONLY valid JSON:
{{
  "risk_level": "High|Medium|Low",
  "summary": "<blunt 2-sentence assessment of where this bid stands>",
  "critical": [
    {{
      "req_id": "M1",
      "reason": "why this is critical or disqualifying",
      "action": "specific action needed",
      "by_when": "suggested internal deadline"
    }}
  ],
  "at_risk": [
    {{
      "req_id": "R3",
      "reason": "why at risk or unverified",
      "action": "action needed"
    }}
  ],
  "unassigned": ["list of req_ids with no owner"],
  "recommendation": "<single most important priority action today>"
}}"""

    raw = _call(EVIDENCE_SYSTEM, prompt, max_tokens=2048)
    return _parse_json(raw)


# ── 3. Strategic Clarification Question Generator ─────────────────────────────
CLARIFICATION_SYSTEM = """You are a senior bid strategist and procurement advisor with extensive experience in competitive tendering.
Your job is to generate clarification questions that:
1. STRATEGICALLY CRITICAL — resolve ambiguities that could cause disqualification or alter the bid/no-bid decision.
2. ELIGIBILITY & SCOPE CLEAR — clarify mandatory qualification thresholds, deliverables, volumes, and service levels.
3. COMMERCIALLY PROTECTIVE — confirm pricing structures, indexation, travel policies, and change-order rules.
4. COMPETITIVELY NEUTRAL — protect the bidder's commercial strategy; never reveal internal weaknesses.

Questions must be:
- Phrased as a neutral, professional request for clarification referencing specific RFP sections.
- Formulated to elicit a definitive, binding answer from the procurement authority.
- Grounded strictly in ambiguities in the tender documentation provided.

For each question, provide a private rationale (for internal bid team use only) explaining the strategic intent."""

def generate_clarification_questions(bid_info: dict, requirements: list[dict],
                                      rfp_context: str = "", firm_concerns: str = "") -> dict:
    """Generate ranked, submission-ready clarification questions derived from the RFP."""
    req_lines = []
    for r in requirements:
        wt_str = f" {r['weight']*100:.0f}%" if r.get('weight') else ""
        req_lines.append(
            f"[{r.get('req_id','')}] ({r.get('category','')}{wt_str}) "
            f"{r.get('description','')[:180]} | "
            f"Ref: {r.get('rfso_ref','') or 'not specified'} | Evidence: {r.get('evidence','') or 'not specified'}"
        )
    reqs_text = "\n".join(req_lines)

    sub_deadline = bid_info.get("submission_deadline", "Not stated")
    clar_deadline = bid_info.get("clarification_deadline", "Not stated")
    client = bid_info.get("client", "Procurement Authority")
    title = bid_info.get("title", "Competitive Opportunity")
    notes = bid_info.get("notes", "")[:600]

    prompt = f"""PROCUREMENT DETAILS:
Client: {client}
Opportunity: {title}
Enquiry deadline: {clar_deadline}
Submission deadline: {sub_deadline}
Summary: {notes}

REQUIREMENT REGISTER:
{reqs_text}

{f'ADDITIONAL RFP CONTEXT / EXCERPTS:\n{rfp_context[:4000]}' if rfp_context else ''}
{f'BIDDER INTERNAL CONCERNS (use to shape questions but do not disclose directly):\n{firm_concerns[:1500]}' if firm_concerns else ''}

Generate 8-12 prioritized clarification questions addressing genuine ambiguities in mandatory qualification criteria, scope boundaries, evaluation scoring, commercial mechanics, or contractual risks.
Keep each field concise (under 250 characters). Return ONLY valid JSON:
{{
  "questions": [
    {{
      "id": "Q1",
      "question": "Neutral, professional question referencing the RFP section. Under 200 chars.",
      "rationale": "Internal strategic rationale explaining why this matters. Under 150 chars.",
      "priority": "Critical|High|Medium",
      "risk_if_unanswered": "Commercial or compliance risk if unclarified. Under 100 chars.",
      "relates_to": ["M1"],
      "category": "Eligibility|Scope|Commercial|Evaluation|Contract"
    }}
  ],
  "submission_notes": "Advice on how and when to submit these clarification requests. Under 150 chars.",
  "critical_count": 0,
  "deadline_note": "Deadline reminder note. Under 80 chars."
}}"""

    raw = _call(CLARIFICATION_SYSTEM, prompt, max_tokens=4096)
    result = _parse_json(raw)
    for q in result.get("questions", []):
        q.setdefault("id", "")
        q.setdefault("question", "")
        q.setdefault("rationale", "")
        q.setdefault("priority", "Medium")
        q.setdefault("risk_if_unanswered", "")
        q.setdefault("relates_to", [])
        q.setdefault("category", "General")
    return result


# ── 4. Bid / No-Bid Pursuit Scoring ───────────────────────────────────────────
BID_NOBID_SYSTEM = """You are a senior executive partner evaluating whether to commit resources to pursue a competitive bid.
You are objective, unsentimental, and focused on win probability, delivery capability, qualification certainty, and return on effort.
Base your recommendation strictly on the RFP requirements, qualification status, and bidder capability profile provided."""

def bid_no_bid_score(bid_info: dict, requirements: list[dict],
                     firm_context: str = "",
                     qualification_requirements: list[dict] | None = None) -> dict:
    """Produce a structured pursuit recommendation across five strategic dimensions."""
    from requirement_semantics import is_supplier_qualification, normalize_requirement_identity_text

    def _req_key(r: dict) -> Any:
        # Use database id if present; else normalized material description if present; else object identity
        if r.get("id") is not None:
            return ("id", r["id"])
        norm_desc = normalize_requirement_identity_text(r.get("description"))
        if norm_desc:
            return ("desc", norm_desc)
        return ("obj", id(r))

    # Separate true supplier qualification gates from other procurement requirements
    if qualification_requirements is not None:
        qual_reqs = qualification_requirements
        qual_pks = {_req_key(r) for r in qual_reqs}
        other_reqs = [r for r in requirements if _req_key(r) not in qual_pks]
    else:
        qual_reqs = [r for r in requirements if is_supplier_qualification(r)]
        qual_pks = {_req_key(r) for r in qual_reqs}
        other_reqs = [r for r in requirements if _req_key(r) not in qual_pks]

    if qual_reqs:
        qual_summary = "\n".join(
            f"- [GATE: {r.get('req_id','')}] ({r.get('category','')}) Status: {r.get('qual_status','UNKNOWN')} | "
            f"Evidence: {r.get('evidence_status','MISSING')} | "
            f"{r.get('description','')[:150]}"
            for r in qual_reqs
        )
    else:
        qual_summary = "None identified. No explicit pass/fail bidder qualification gates found."

    if other_reqs:
        other_summary = "\n".join(
            f"- [{r.get('req_id','')}] ({r.get('category','')}) Type: {r.get('requirement_type','General')} | "
            f"Qual: {r.get('qual_status','UNKNOWN')} | "
            f"Weight: {str(round(r['weight']*100)) + '%' if r.get('weight') else 'n/a'} | "
            f"{r.get('description','')[:120]}"
            for r in other_reqs
        )
    else:
        other_summary = "None."

    prompt = f"""OPPORTUNITY UNDER EVALUATION:
Title: {bid_info.get('title','')}
Client: {bid_info.get('client','')}
Submission deadline: {bid_info.get('submission_deadline','unknown')}
Summary: {bid_info.get('notes','')[:500]}

TRUE SUPPLIER QUALIFICATION GATES (Pass/Fail Bidder Eligibility):
{qual_summary}

OTHER PROCUREMENT REQUIREMENTS (Technical, Submission, SLA, Commercial, Scored):
{other_summary}

BIDDER PROFILE & CAPABILITIES:
{firm_context[:1000] if firm_context else 'Assess feasibility based on requirement standards.'}

Score this opportunity across five strategic dimensions (0-10 each) and provide an actionable pursuit recommendation.
CRITICAL EVALUATION RULES:
- A qualification FAIL is a hard blocker to participation.
- A qualification UNKNOWN may justify NEEDS MORE INFORMATION or a condition; missing bidder information is NOT evidence of PASS.
- Technical, submission, SLA, and commercial requirements influence feasibility, staffing, risk, and pursuit conditions, but must NOT be described as supplier eligibility failures unless they are genuine qualification gates.
Return ONLY valid JSON:
{{
  "recommendation": "GO|GO WITH CONDITIONS|NO-GO|NEEDS MORE INFORMATION",
  "confidence": "High|Medium|Low",
  "overall_score": <integer 0-100>,
  "summary": "<3-4 sentence executive summary of the recommendation>",
  "dimensions": {{
    "strategic_fit": {{
      "score": <0-10>,
      "rationale": "Alignment with firm strategy and core offerings",
      "evidence": "Supporting factors"
    }},
    "capability_fit": {{
      "score": <0-10>,
      "rationale": "Ability to deliver scope and satisfy mandatory qualifications",
      "evidence": "Identified strengths or capability gaps"
    }},
    "competitive_position": {{
      "score": <0-10>,
      "rationale": "Likely positioning vs. competitor landscape and differentiators",
      "evidence": "Value proposition edge"
    }},
    "resource_availability": {{
      "score": <0-10>,
      "rationale": "Capacity to write proposal and staff delivery team before deadline",
      "evidence": "Timeline considerations"
    }},
    "risk": {{
      "score": <0-10>,
      "rationale": "Assessment of commercial, legal, and operational risks",
      "evidence": "Specific risk factors or contract liabilities"
    }}
  }},
  "hard_blockers": ["<mandatory qualification failure or disqualification factor if any>"],
  "conditions": ["<critical condition that must be resolved to proceed, if any>"],
  "win_themes": ["<strongest competitive differentiator 1>", "<strongest differentiator 2>"],
  "red_flags": ["<critical pursuit risk or weakness 1>", "<risk 2>"]
}}"""

    raw = _call(BID_NOBID_SYSTEM, prompt, max_tokens=2048)
    return _parse_json(raw)


# ── 5. Past Proposal Content Ingestion ────────────────────────────────────────
PROPOSAL_ANALYZER_SYSTEM = """You are an expert proposal knowledge manager.
Your task is to analyze submitted past proposal documents and extract high-value, reusable content blocks
(methodologies, case studies, team credentials, governance frameworks, quality policies, and executive summaries)
for a firm's content library."""

def analyze_past_proposal(text: str, bid_context: dict) -> dict:
    """Extract modular reusable content and team qualifications from a past proposal document."""
    prompt = f"""CURRENT BID CONTEXT:
Client: {bid_context.get('client','')}
Title: {bid_context.get('title','')}
Notes: {bid_context.get('notes','')[:300]}

PAST PROPOSAL TEXT EXCERPT (first 12,000 characters):
{text[:12000]}

Extract all reusable proposal content blocks and key personnel profiles. Return ONLY valid JSON:
{{
  "proposal_summary": {{
    "client": "Client or buyer name from the past proposal",
    "year": "Year submitted if visible",
    "service_type": "Type of service or solution proposed",
    "outcome": "Won|Lost|Unknown"
  }},
  "library_items": [
    {{
      "title": "Descriptive title of content block",
      "category": "Methodology|Case Study|Executive Summary|Technical Architecture|Team Qualification|Governance|Quality Assurance|IDEA / ESG Statement|Pricing Structure|Other",
      "content": "Verbatim or polished reusable proposal text block.",
      "relevance_to_current": "How this content maps to typical competitive requirements",
      "tags": "comma-separated tags e.g. consulting,transformation,public_sector,enterprise"
    }}
  ],
  "team_members_found": [
    {{
      "name": "Full Name",
      "credentials": "Key degrees, certifications, or professional designations",
      "role": "Role or specialty",
      "sectors": "Key industry sectors mentioned",
      "languages": "Languages mentioned if any",
      "cv_summary": "Concise summary of experience and qualification profile"
    }}
  ],
  "gaps": ["Content categories or evidence areas that this proposal does not cover"]
}}"""

    raw = _call(PROPOSAL_ANALYZER_SYSTEM, prompt, max_tokens=4096)
    result = _parse_json(raw)
    if not isinstance(result, dict):
        result = {}
    result.setdefault("proposal_summary", {})
    result.setdefault("library_items", [])
    result.setdefault("team_members_found", [])
    result.setdefault("gaps", [])

    if not isinstance(result["library_items"], list):
        result["library_items"] = []
    result["library_items"] = [i for i in result["library_items"] if isinstance(i, dict)]

    return result


# ── 6. Proposal Section Drafter ───────────────────────────────────────────────
DRAFTER_SYSTEM = """You are a senior proposal writer. Write proposal sections that are specific, evidence-based,
persuasive, and directly responsive to stated evaluation criteria.
Every paragraph must demonstrate verified capability or directly answer a requirement.
Write in professional first-person plural (we / our) from the bidding firm's perspective."""

def draft_proposal_section(section_title: str, requirements: list,
                            library_items: list, bid_context: dict,
                            firm_context: str = "", word_limit: int = 500) -> dict:
    """Draft a tailored proposal section incorporating relevant requirements and library content."""
    reqs_text = "\n".join(
        f"- [{r.get('req_id','')}] {r.get('description','')} "
        f"(Evidence required: {r.get('evidence') or 'not specified'})"
        for r in requirements
    )
    lib_text = "\n\n".join(
        f"[{item.get('category','')}] {item.get('title','')}\n{item.get('content','')[:600]}"
        for item in library_items[:6]
    ) if library_items else "No library content supplied — draft tailored response based on requirements and context."

    prompt = f"""PROPOSAL SECTION TO DRAFT: {section_title}
TARGET WORD COUNT: approximately {word_limit} words

BID CONTEXT:
Client: {bid_context.get('client','')}
Opportunity: {bid_context.get('title','')}
Client Context: {bid_context.get('notes','')[:300]}

REQUIREMENTS THIS SECTION MUST ADDRESS:
{reqs_text}

AVAILABLE REUSABLE ASSETS & EVIDENCE:
{lib_text}

BIDDER FIRM CONTEXT:
{firm_context[:800] if firm_context else 'Professional services firm specializing in strategic advisory, program delivery, and transformation.'}

Draft the section now. Return ONLY valid JSON:
{{
  "section_title": "{section_title}",
  "draft": "Full drafted section text formatted into cohesive paragraphs with clear headings if helpful.",
  "requirements_addressed": ["list of req_ids explicitly addressed"],
  "requirements_missing": ["req_ids requiring further factual evidence"],
  "word_count": <approximate word count>,
  "strength_rating": <integer 1-5 where 5 is publication-ready>,
  "improvement_notes": "Specific suggestions to strengthen score against evaluation criteria"
}}"""

    raw = _call(DRAFTER_SYSTEM, prompt, max_tokens=3000)
    return _parse_json(raw)


# ── 7. Final Submission Readiness Check ───────────────────────────────────────
READINESS_SYSTEM = """You are a bid compliance director conducting a final pre-submission quality audit.
Examine the submission package for any missing forms, unverified requirements, formatting defects, or blockers that could risk disqualification."""

def submission_readiness_check(bid: dict, requirements: list,
                                documents: list, outline: list) -> dict:
    """Final pre-submission gate check."""
    mandatory_status = [
        f"[{r.get('req_id','')}] {r.get('description','')[:80]} → Status: {r.get('status','')} | Qual: {r.get('qual_status','UNKNOWN')}"
        for r in requirements if r.get('category') == 'Mandatory'
    ]
    def _format_doc_mand(m):
        if m in (1, True, "1", "true"):
            return "REQUIRED"
        elif m in (0, False, "0", "false"):
            return "OPTIONAL"
        return "UNKNOWN"

    doc_status = [
        f"{d.get('name','')} (Mandatory: {_format_doc_mand(d.get('mandatory'))}) → {d.get('status','')}"
        for d in documents if d.get('doc_type') in ('Submission', 'Financial')
    ]
    section_status = [
        f"[{s.get('section_num','')}] {s.get('title','')} → {s.get('status','')}"
        for s in outline
    ]

    prompt = f"""BID: {bid.get('title','')} — {bid.get('client','')}
Submission deadline: {bid.get('submission_deadline','UNKNOWN')}
Clarification deadline: {bid.get('clarification_deadline','UNKNOWN')}

MANDATORY REQUIREMENTS STATUS:
{chr(10).join(mandatory_status) or 'None recorded'}

SUBMISSION DOCUMENTS STATUS:
{chr(10).join(doc_status) or 'None recorded'}

PROPOSAL SECTIONS STATUS:
{chr(10).join(section_status) or 'None recorded'}

Conduct the final readiness gate check. Return ONLY valid JSON:
{{
  "go_no_go": "GO|NO GO|CONDITIONAL GO",
  "readiness_score": <integer 0-100>,
  "summary": "2-3 sentence overall readiness assessment",
  "blockers": [
    {{
      "item": "Specific blocked item or missing mandatory submission element",
      "severity": "Critical|High|Medium",
      "action": "Immediate corrective action required",
      "by_when": "Suggested deadline"
    }}
  ],
  "warnings": ["non-critical warnings or polish items"],
  "submission_checklist": [
    {{"item": "Checklist item", "status": "Ready|Pending|Blocked"}}
  ],
  "recommended_submission_time": "Suggested target time prior to hard deadline"
}}"""

    raw = _call(READINESS_SYSTEM, prompt, max_tokens=2048)
    return _parse_json(raw)


# ── 8. Addendum & Amendment Analyzer ──────────────────────────────────────────
ADDENDUM_SYSTEM = """You are an expert bid analyst reviewing a tender addendum, bulletin, or amendment document.
Identify what has changed, new requirements introduced, modifications to existing requirements, deadline shifts, and formal Q&A answers."""

def analyze_addendum(text: str, existing_requirements: list, bid_info: dict) -> dict:
    """Analyze supplementary tender documents and extract modifications."""
    existing_summary = "\n".join(
        f"[{r.get('req_id','')}] {r.get('description','')[:100]}"
        for r in existing_requirements[:30]
    )

    prompt = f"""BID: {bid_info.get('title','')} — {bid_info.get('client','')}
Current submission deadline: {bid_info.get('submission_deadline','')}
Current clarification deadline: {bid_info.get('clarification_deadline','')}

EXISTING COMPLIANCE MATRIX (sample):
{existing_summary}

ADDENDUM / AMENDMENT DOCUMENT TEXT:
{text[:10000]}

Analyze all changes introduced by this document. Return ONLY valid JSON:
{{
  "document_type": "Addendum|Bulletin|Amendment|Clarification Q&A|Specification Update",
  "document_number": "e.g. Addendum No. 1",
  "summary": "1-2 sentence summary of what this document changes",
  "deadline_changes": {{
    "submission_deadline": "new YYYY-MM-DD date or null if unchanged",
    "clarification_deadline": "new YYYY-MM-DD date or null if unchanged",
    "other_dates": "any other date changes"
  }},
  "new_requirements": [
    {{
      "req_id": "A1-M1",
      "category": "Mandatory|Rated|Financial|Supporting",
      "description": "Description of the new requirement",
      "rfso_ref": "Section reference",
      "weight": null,
      "evidence": "Evidence required",
      "owner": null,
      "deadline": null,
      "status": "Not Started",
      "qual_status": "UNKNOWN",
      "gap_action": "Action to confirm compliance",
      "notes": "Added via addendum"
    }}
  ],
  "modified_requirements": [
    {{
      "req_id": "M1",
      "change_description": "Exact description of what changed",
      "new_text": "Updated requirement wording"
    }}
  ],
  "clarifications": [
    {{
      "topic": "Topic clarified",
      "clarification": "Key clarification answer",
      "affects_req_ids": ["M1"]
    }}
  ],
  "key_changes": ["Major change item 1", "Major change item 2"]
}}"""

    raw = _call(ADDENDUM_SYSTEM, prompt, max_tokens=4096)
    return _parse_json(raw)


# ── 9. Comprehensive Proposal Alignment Audit ─────────────────────────────────
# Correctness remediation (bounded, separate from Phase 8 Package 3 auth/
# tenancy/RLS work, which is closed and untouched by this change). The
# previous implementation truncated the proposal to its first 8,000
# characters and the "RFP context" to bid.notes (a short free-text field,
# not the tender corpus), made a single ~3,500-token-budget model call for
# score+findings, and silently substituted a hardcoded 50/REVISE BEFORE
# SUBMITTING result whenever that call's JSON failed to parse as a dict --
# with no distinction shown to the user between "the model found nothing"
# and "the audit never actually completed." requirement_coverage and
# next_steps were computed but never rendered.
#
# This replacement:
#   * analyzes the WHOLE proposal via bounded, traceable section chunking
#     (never a single unbounded mega-prompt) -- see the parameters below.
#   * uses canonical, already-extracted procurement intelligence (the
#     caller's `rfp_text` argument is expected to be built from bid_briefs
#     + the compliance matrix, never bid.notes -- see stage_check.py).
#   * computes the numeric score DETERMINISTICALLY from aggregated
#     per-requirement coverage (see _compute_score) -- the model is used
#     only to assert POSITIVE evidence per section (never absence, since
#     no single section can know what's missing elsewhere) and, in one
#     final bounded pass, to write narrative prose over the already-fixed
#     deterministic results. The model can never move the score.
#   * can never produce a numeric score from a malformed/truncated/
#     incomplete response -- a chunk whose response is `_truncated` or
#     otherwise fails validation is retried once, then marked skipped
#     (counted honestly in coverage_metadata), never trusted.
#   * distinguishes "Not Addressed" (confirmed absent -- only valid when
#     proposal coverage is complete) from "Cannot Assess" (coverage was
#     incomplete, so absence cannot be confirmed) -- unknown absence is
#     never silently reinterpreted as confirmed absence.
#   * surfaces Mandatory-category "Not Addressed" requirements as a
#     separate, score-overriding `mandatory_failures` list -- a high
#     numeric score can never make a mandatory failure look acceptable.
#   * returns `status: "incomplete"` (no numeric score at all) only when
#     every section failed to analyze or the result fails the strict
#     contract validator -- never a plausible-looking default.

# ── Chunking / call-budget parameters (documented, not tuned silently) ──
# Target chunk size: 9,000 characters of proposal text per analyzed
# section -- large enough for a section to carry real context, small
# enough to keep each per-chunk call's response comfortably inside its
# token budget (avoiding the exact truncation failure mode this
# remediation exists to fix).
_ALIGN_TARGET_CHUNK_CHARS = 9000
# Overlap used only by the deterministic fixed-window fallback splitter
# (used when headings can't be reliably detected), so a fact split
# exactly across a window boundary is still visible to at least one chunk.
_ALIGN_OVERLAP_CHARS = 400
# Hard ceiling on chunks analyzed per audit -- bounds the worst-case call
# count regardless of document (or, for a package, whole-package) size. A
# single document beyond the ceiling is analyzed via evenly-spaced
# representative sampling across its full length (never just "the first N
# chunks"); a multi-file PACKAGE beyond the ceiling uses
# _allocate_package_chunk_budget()'s fair, size-proportional allocation
# across files instead of a single even stride (see that function). In
# both cases the shortfall is disclosed honestly via coverage_metadata,
# never silently dropped, and forces status="incomplete" (never a score
# presented as though the sample were the whole submission).
#
# Call budget: 1 model call per analyzed chunk (with at most 1 bounded
# retry for a chunk whose response fails validation) + 1 final bounded
# narrative-synthesis call. Raised from 16 to 24 chunks to accommodate a
# genuine multi-document submission package (technical proposal +
# schedules + CVs + declarations), not just one document -- worst case
# (every chunk needs its one retry) is bounded at 2 * 24 + 1 = 49 calls,
# regardless of how large or how many files the source package contains.
_ALIGN_MAX_CHUNKS = 24
# A requirement may only be concluded "Not Addressed" (vs "Cannot
# Assess") when proposal coverage is at least this complete AND zero
# chunks failed or were sampled out by the ceiling.
_ALIGN_COVERAGE_COMPLETE_THRESHOLD = 99.0
# Safety cap on the shared procurement-intelligence context repeated in
# every chunk prompt -- defensive only; canonical, already-extracted
# intelligence (bid_briefs + the compliance matrix) is inherently compact
# structured text, not a raw document, so this should not normally bind.
_ALIGN_MAX_PROCUREMENT_CONTEXT_CHARS = 12000
# Chunk calls are independent (each sees only its own section) and are
# executed with bounded thread concurrency -- a conservative limit, not
# unbounded parallelism -- to cut wall-clock latency without changing the
# total number of calls made, the deterministic aggregation order, each
# chunk's isolated retry behavior, or the fail-closed treatment of a
# chunk that ultimately fails. The final narrative-synthesis call is
# never parallelized -- it must wait for deterministic aggregation to
# finish, since it summarizes the fixed, already-computed results.
_ALIGN_CHUNK_CONCURRENCY = 4

_HEADING_RE = re.compile(
    r'^(?:'
    r'#{1,6}\s+.{2,100}'                            # markdown heading
    r'|\d+(?:\.\d+)*[\.\)]?\s+[A-Z][^\n]{2,100}'     # "1. Title" / "2.3 Title"
    r'|SECTION\s+\d+[:\.]?\s*.{0,80}'                # "SECTION 3: ..."
    r'|[A-Z][A-Z0-9 \-&,/]{5,79}'                    # short ALL-CAPS line
    r')\s*$',
    re.MULTILINE,
)


def _detect_headings(text: str) -> list[tuple[int, str]]:
    out = []
    for m in _HEADING_RE.finditer(text):
        line = m.group(0).strip()
        if line:
            out.append((m.start(), line[:100]))
    return out


def _fixed_window_sections(text: str, start: int, end: int) -> list[tuple[int, int, str]]:
    """Deterministic overlapping fixed-size windows over text[start:end].
    Every character in [start, end) is covered by at least one window."""
    sections = []
    pos = start
    step = max(_ALIGN_TARGET_CHUNK_CHARS - _ALIGN_OVERLAP_CHARS, 1)
    while pos < end:
        win_end = min(pos + _ALIGN_TARGET_CHUNK_CHARS, end)
        sections.append((pos, win_end, f"Characters {pos:,}-{win_end:,}"))
        if win_end >= end:
            break
        pos += step
    return sections


def _union_chars_covered(ranges: list[tuple[int, int]]) -> int:
    """Distinct characters covered by a set of (start, end) ranges,
    counting an overlap (from the fixed-window fallback's deliberate
    _ALIGN_OVERLAP_CHARS) only once -- a naive sum of (end - start)
    double-counts overlapping regions and can report >100% coverage."""
    if not ranges:
        return 0
    ordered = sorted(ranges)
    total = 0
    cur_start, cur_end = ordered[0]
    for s, e in ordered[1:]:
        if s <= cur_end:
            cur_end = max(cur_end, e)
        else:
            total += cur_end - cur_start
            cur_start, cur_end = s, e
    total += cur_end - cur_start
    return total


def _split_proposal_into_sections(text: str) -> list[dict]:
    """Section-aware split (numbered/markdown/ALL-CAPS heading detection)
    with a deterministic overlapping-window fallback when headings can't
    be reliably identified. Every character of `text` is accounted for
    in exactly one raw section at this stage -- nothing is dropped here;
    the chunk-count ceiling is applied later, explicitly, in
    _merge_and_bound_sections."""
    n = len(text)
    if n == 0:
        return []

    headings = _detect_headings(text)
    # Require several headings spread through the document (not all
    # clustered in the first 30%) before trusting heading-based
    # splitting -- otherwise a false-positive-heavy detection (e.g. a
    # proposal with no real headings) would silently degrade to
    # analyzing mostly the front of the document again.
    if len(headings) < 3 or headings[-1][0] < n * 0.3:
        raw = _fixed_window_sections(text, 0, n)
        return [{"start": s, "end": e, "heading": h, "text": text[s:e]} for s, e, h in raw]

    bounds = [h[0] for h in headings]
    labels = [h[1] for h in headings]
    if bounds[0] > 0:
        bounds = [0] + bounds
        labels = ["Preamble"] + labels
    bounds.append(n)

    raw_sections = []
    for i in range(len(bounds) - 1):
        s, e = bounds[i], bounds[i + 1]
        if e <= s:
            continue
        raw_sections.append({"start": s, "end": e, "heading": labels[i], "text": text[s:e]})
    return raw_sections


_XLSX_SHEET_MARKER_RE = re.compile(
    r"\[\[SOURCE:\s*(?P<file>[^|\]]+?)\s*\|\s*SHEET:\s*(?P<sheet>[^|\]]+?)\s*\|\s*ROWS:\s*[\d]+-[\d]+\]\]\n"
)


def _split_structured_sheets_into_sections(text: str) -> list[dict]:
    """XLSX/XLS raw split: one section per worksheet, using the exact
    sheet name from the deterministic [[SOURCE: file | SHEET: name |
    ROWS: a-b]] marker extract_xlsx_with_metadata()/extract_xls_with_
    metadata() already embed in the text -- never inferred from content,
    never re-detected via the generic prose heading regex (which would
    risk mis-splitting tabular data). A sheet larger than the target
    chunk size is further windowed with the same deterministic
    overlapping-window fallback used for prose. Falls back to the
    generic splitter only if no sheet markers are present at all (e.g. an
    XML-fallback extraction that produced a single unmarked blob)."""
    matches = list(_XLSX_SHEET_MARKER_RE.finditer(text))
    if not matches:
        return _split_proposal_into_sections(text)

    raw: list[dict] = []
    for i, m in enumerate(matches):
        seg_start = m.start()
        seg_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        heading = f"Sheet: {m.group('sheet').strip()}"
        seg_text = text[seg_start:seg_end]
        if len(seg_text) <= _ALIGN_TARGET_CHUNK_CHARS:
            raw.append({"start": seg_start, "end": seg_end, "heading": heading, "text": seg_text})
        else:
            for s, e, _ in _fixed_window_sections(seg_text, 0, len(seg_text)):
                raw.append({"start": seg_start + s, "end": seg_start + e, "heading": heading, "text": seg_text[s:e]})
    return raw


def _even_stride_sample_indices(n: int, k: int) -> list[int]:
    """k deterministic, evenly-spaced indices across range(n) (never just
    the first k) -- shared by the legacy single-document ceiling and the
    package-wide per-file quota sampling below."""
    if k <= 0 or n <= 0:
        return []
    if k >= n:
        return list(range(n))
    if k == 1:
        return [0]
    return sorted({round(i * (n - 1) / (k - 1)) for i in range(k)})


def _combine_heading_parts(parts: list[str], max_shown: int = 3) -> str:
    """Caps a merged chunk's displayed heading/provenance to the first
    `max_shown` constituent section headings plus a '+N more section(s)'
    tail, instead of an ever-growing '+'-joined string -- keeps
    provenance genuinely useful rather than unreadable for a chunk that
    greedily absorbed many small sections."""
    if len(parts) <= max_shown:
        return " + ".join(parts)
    shown = " + ".join(parts[:max_shown])
    return f"{shown} (+{len(parts) - max_shown} more section(s))"


def _merge_and_size_bound_sections(raw_sections: list[dict]) -> list[dict]:
    """Merges adjacent sections and splits oversized ones down to the
    target chunk size. Applies NO chunk-count ceiling -- callers decide
    how/where to bound the total: _merge_and_bound_sections below applies
    the ceiling immediately for a single document, while the package
    pipeline (_allocate_package_chunk_budget) bounds ACROSS all of a
    package's files together after collecting each file's bounded
    sections from this function.

    Merge strategy: greedy bin-packing toward _ALIGN_TARGET_CHUNK_CHARS
    (not merely "buffer is still under the much lower
    _ALIGN_MIN_MERGE_CHARS floor") -- a section keeps absorbing the next
    adjacent section as long as the COMBINED size still fits under the
    target. The prior floor-only condition stopped absorbing as soon as
    the buffer alone crossed _ALIGN_MIN_MERGE_CHARS (2,500 chars), even
    when the buffer was still well under the 9,000-char target and the
    next section was small -- leaving many chunks in that 2,500-9,000
    "dead zone" that a real bin-pack would have combined. This never
    merges across a file boundary (each call here only ever receives one
    file's own raw sections)."""
    if not raw_sections:
        return []

    merged: list[dict] = []
    buf = None
    for sec in raw_sections:
        if buf is None:
            buf = dict(sec)
            buf["_heading_parts"] = [sec["heading"]]
            continue
        if len(buf["text"]) + len(sec["text"]) <= _ALIGN_TARGET_CHUNK_CHARS:
            buf["end"] = sec["end"]
            buf["text"] = buf["text"] + sec["text"]
            buf["_heading_parts"].append(sec["heading"])
        else:
            buf["heading"] = _combine_heading_parts(buf.pop("_heading_parts"))
            merged.append(buf)
            buf = dict(sec)
            buf["_heading_parts"] = [sec["heading"]]
    if buf is not None:
        buf["heading"] = _combine_heading_parts(buf.pop("_heading_parts"))
        merged.append(buf)

    bounded: list[dict] = []
    for sec in merged:
        if len(sec["text"]) <= _ALIGN_TARGET_CHUNK_CHARS:
            bounded.append(sec)
            continue
        for s, e, _ in _fixed_window_sections(sec["text"], 0, len(sec["text"])):
            bounded.append({
                "start": sec["start"] + s, "end": sec["start"] + e,
                "heading": sec["heading"], "text": sec["text"][s:e],
            })
    return bounded


def _merge_and_bound_sections(raw_sections: list[dict]) -> dict:
    """Single-document path (unchanged behavior/contract): merge/size-
    bound via the shared helper above, then apply the hard
    _ALIGN_MAX_CHUNKS ceiling via even-stride sampling across the WHOLE
    document (never just the first N chunks) -- a document beyond the
    safe ceiling still gets representative, not front-loaded, coverage,
    and the shortfall is recorded in `skipped_ranges` rather than
    silently dropped."""
    if not raw_sections:
        return {"chunks": [], "chars_total": 0, "skipped_ranges": []}

    chars_total = raw_sections[-1]["end"]
    bounded = _merge_and_size_bound_sections(raw_sections)

    skipped_ranges = []
    if len(bounded) > _ALIGN_MAX_CHUNKS:
        n = len(bounded)
        idx = _even_stride_sample_indices(n, _ALIGN_MAX_CHUNKS)
        kept_set = set(idx)
        skipped_ranges = [
            {"start": bounded[i]["start"], "end": bounded[i]["end"], "heading": bounded[i]["heading"]}
            for i in range(n) if i not in kept_set
        ]
        bounded = [bounded[i] for i in idx]

    for i, c in enumerate(bounded):
        c["index"] = i
    for c in bounded:
        c["total"] = len(bounded)

    return {"chunks": bounded, "chars_total": chars_total, "skipped_ranges": skipped_ranges}


def _allocate_package_chunk_budget(
    per_file_sections: list[tuple[dict, list[dict]]], ceiling: int
) -> tuple[list[dict], list[dict]]:
    """Package-wide chunk-count ceiling with FAIR allocation across
    files (instruction 8: "do not silently sacrifice an entire small
    file because a large primary proposal consumed most of the package
    budget"). `per_file_sections` is a list of (file_dict,
    size_bounded_raw_sections) pairs in package order.

    Allocation:
      1. If the package's total section count already fits under
         `ceiling`, everything is kept -- no sampling, nothing skipped.
      2. Otherwise every file with at least one section is first
         guaranteed exactly 1 kept chunk (as long as there are no more
         files than the ceiling allows).
      3. Remaining budget is distributed proportionally to each file's
         own section count beyond its guaranteed one (largest-remainder
         method, deterministic -- bigger files legitimately get more of
         the remaining budget, "prioritizing substantive content", but
         never zero).
      4. Within each file, its quota is even-stride sampled from that
         file's OWN sections (never just the front) -- reusing the same
         technique the single-document ceiling already uses.
      5. Pathological case: more analyzable files than the ceiling
         allows even one chunk each -- the `ceiling` largest files each
         get one representative (middle) chunk; the rest get none
         (fully present in `skipped`, which -- like any non-empty skip
         list -- forces the caller's existing fail-closed incomplete-
         audit path, never a silently degraded score).

    Returns (kept_chunks, skipped_sections); each chunk/section dict is
    tagged with source_file_id/source_filename, and kept_chunks carries
    package-wide, contiguous index/total fields (order: by file in
    package order, then by that file's own original section order --
    fully deterministic)."""
    files_with_sections = [(f, secs) for f, secs in per_file_sections if secs]
    total = sum(len(secs) for _, secs in files_with_sections)

    def _finalize(kept: list[dict]) -> list[dict]:
        for i, c in enumerate(kept):
            c["index"] = i
        for c in kept:
            c["total"] = len(kept)
        return kept

    if total <= ceiling:
        kept = [
            {**sec, "source_file_id": f["file_id"], "source_filename": f["filename"]}
            for f, secs in files_with_sections for sec in secs
        ]
        return _finalize(kept), []

    n_files = len(files_with_sections)

    if n_files >= ceiling:
        ordered = sorted(files_with_sections, key=lambda fs: -len(fs[1]))
        kept, skipped = [], []
        for f, secs in ordered[:ceiling]:
            mid = secs[len(secs) // 2]
            kept.append({**mid, "source_file_id": f["file_id"], "source_filename": f["filename"]})
            skipped.extend(
                {**s, "source_file_id": f["file_id"], "source_filename": f["filename"]}
                for s in secs if s is not mid
            )
        for f, secs in ordered[ceiling:]:
            skipped.extend(
                {**s, "source_file_id": f["file_id"], "source_filename": f["filename"]}
                for s in secs
            )
        return _finalize(kept), skipped

    quota = {f["file_id"]: 1 for f, _ in files_with_sections}
    remaining = ceiling - n_files
    extra_pool = {f["file_id"]: len(secs) - 1 for f, secs in files_with_sections}
    total_extra = sum(extra_pool.values())

    if remaining > 0 and total_extra > 0:
        raw_shares = {fid: remaining * (extra_pool[fid] / total_extra) for fid in extra_pool}
        floors = {fid: min(int(raw_shares[fid]), extra_pool[fid]) for fid in raw_shares}
        leftover = remaining - sum(floors.values())
        # Largest-remainder method: hand out the leftover units to the
        # files with the biggest fractional remainder first, deterministic
        # tie-break on file_id.
        remainder_order = sorted(
            (fid for fid in raw_shares if floors[fid] < extra_pool[fid]),
            key=lambda fid: (-(raw_shares[fid] - floors[fid]), fid),
        )
        i = 0
        while leftover > 0 and remainder_order:
            fid = remainder_order[i % len(remainder_order)]
            if floors[fid] < extra_pool[fid]:
                floors[fid] += 1
                leftover -= 1
            i += 1
            if i > 10000:
                break
        for fid in quota:
            quota[fid] += floors.get(fid, 0)

    kept, skipped = [], []
    for f, secs in files_with_sections:
        fid = f["file_id"]
        q = min(quota.get(fid, 1), len(secs))
        keep_idx = set(_even_stride_sample_indices(len(secs), q))
        for i, sec in enumerate(secs):
            tagged = {**sec, "source_file_id": fid, "source_filename": f["filename"]}
            (kept if i in keep_idx else skipped).append(tagged)

    return _finalize(kept), skipped


_ALIGN_CHUNK_SYSTEM = (
    "You are a senior proposal reviewer auditing ONE section of a larger proposal "
    "against a compliance matrix and canonical procurement intelligence. You can "
    "only see this section -- you cannot see the rest of the proposal, so NEVER "
    "assert that something is missing or absent; only report what you can "
    "positively confirm IS present in this section. Derive all conclusions "
    "strictly from the provided section text and procurement intelligence. "
    "This input is an excerpt/chunk taken from a larger source document -- "
    "the point where the supplied excerpt ends is NOT evidence that the source "
    "document itself ends there. Never report truncation, incompleteness, a "
    "missing continuation, or a cut-off table solely because the excerpt you "
    "were given ends at that point. "
    "Respond with valid JSON only."
)


def _align_chunk_prompt(bid_header: str, procurement_context: str, req_block: str, chunk: dict) -> str:
    return f"""{bid_header}

=== CANONICAL PROCUREMENT INTELLIGENCE (already extracted for this bid) ===
{procurement_context}

=== COMPLIANCE MATRIX (requirements to check for evidence of) ===
{req_block}

=== PROPOSAL SECTION BEING REVIEWED ===
Section: {chunk['heading']} (part {chunk['index'] + 1} of {chunk['total']})
{chunk['text']}

For THIS SECTION ONLY, return ONLY valid JSON:
{{
  "chunk_findings": [
    {{
      "severity": "Critical|High|Medium|Low",
      "stage": "Proposal Submission|Negotiation / Shortlist|Contract Execution|Contractual Obligation",
      "category": "<category>",
      "req_id": "<req_id or null>",
      "title": "<finding title>",
      "issue": "<a SUBSTANTIVE gap, risk, or content-quality deficiency actually VISIBLE in THIS section's own text -- e.g. specific wording that is unclear, incomplete, unsigned, or non-compliant>",
      "recommendation": "<actionable fix>",
      "effort": "Minor edit|Moderate rewrite|Major addition|Post-submission action"
    }}
  ],
  "requirement_assertions": [
    {{
      "req_id": "<req_id>",
      "coverage": "Fully Addressed|Partially Addressed",
      "confidence": "High|Medium|Low",
      "evidence": "<short quote or precise paraphrase from THIS section ONLY -- describe positively what IS present; never mention what this section does or does not contain relative to the rest of the document, never mention truncation, and never mention section/chunk/excerpt boundaries>"
    }}
  ]
}}
CRITICAL RULES for chunk_findings:
- Only include a chunk_finding for a SUBSTANTIVE deficiency you can see WITHIN this section's own text (unclear wording, an unsigned field, incomplete content, a real compliance gap). Whether a requirement/artifact is present ANYWHERE ELSE in the proposal is unknowable from this section alone and is decided later, after every section has been reviewed -- do NOT create a chunk_finding whose issue is that something is "not present," "not addressed," "not visible," or "cannot be seen" in this section/excerpt/chunk. That is not useful signal at package level and is discarded.
- Do NOT create a chunk_finding that merely restates a requirement is satisfied, has no gap, or needs no action ("No gap identified", "Requirement satisfied", "Maintain current documentation") -- if there is nothing wrong, do not emit a finding for it at all.
Only include a requirement_assertion when THIS section actually contains evidence for it -- do not list requirements this section does not address."""


_CHUNK_FAILURE_API_ERROR = "api_error"
_CHUNK_FAILURE_PARSE_ERROR = "parse_error"
_CHUNK_FAILURE_MALFORMED_RESPONSE = "malformed_response"
_CHUNK_FAILURE_TRUNCATED_RESPONSE = "truncated_response"
_CHUNK_FAILURE_UNKNOWN = "unknown_error"


def _call_alignment_chunk(prompt: str, max_tokens: int = 2000) -> tuple[dict | None, str | None]:
    """One attempt plus one bounded retry. Returns (validated per-chunk
    result, None) on success, or (None, failure_category) if both
    attempts failed or were truncated -- the caller marks the chunk
    skipped rather than trusting partial data. failure_category is a
    small, safe, closed-vocabulary label (never the prompt, proposal
    text, or raw exception body) so the caller can surface WHY a chunk
    failed without exposing anything sensitive."""
    last_category = _CHUNK_FAILURE_UNKNOWN
    for _attempt in range(2):
        try:
            raw = _call(_ALIGN_CHUNK_SYSTEM, prompt, max_tokens=max_tokens)
        except Exception:
            last_category = _CHUNK_FAILURE_API_ERROR
            continue
        try:
            parsed = _parse_json(raw)
        except Exception:
            last_category = _CHUNK_FAILURE_PARSE_ERROR
            continue
        if not isinstance(parsed, dict):
            last_category = _CHUNK_FAILURE_MALFORMED_RESPONSE
            continue
        if parsed.get("_truncated"):
            last_category = _CHUNK_FAILURE_TRUNCATED_RESPONSE
            continue  # a partially-recovered chunk result is never trusted
        if "chunk_findings" not in parsed or "requirement_assertions" not in parsed:
            last_category = _CHUNK_FAILURE_MALFORMED_RESPONSE
            continue
        if not isinstance(parsed["chunk_findings"], list) or not isinstance(parsed["requirement_assertions"], list):
            last_category = _CHUNK_FAILURE_MALFORMED_RESPONSE
            continue
        return parsed, None
    return None, last_category


_COVERAGE_RANK = {"Fully Addressed": 2, "Partially Addressed": 1}
_COVERAGE_SCORE_MAP = {"Fully Addressed": 100.0, "Partially Addressed": 50.0, "Not Addressed": 0.0}


def _aggregate_requirement_coverage(requirements: list[dict], chunk_results: list[dict],
                                     coverage_complete: bool) -> list[dict]:
    """Deterministic aggregation: the strongest positive assertion for a
    requirement across all successfully-analyzed chunks wins. Absence
    (no positive assertion anywhere) becomes 'Not Addressed' ONLY when
    proposal coverage is complete; otherwise 'Cannot Assess' -- unknown
    absence must never be silently reinterpreted as confirmed absence."""
    assertions_by_req: dict[str, dict] = {}
    for cr in chunk_results:
        chunk_label = cr["chunk_label"]
        for a in cr.get("requirement_assertions", []):
            rid = a.get("req_id")
            cov = a.get("coverage")
            if not rid or cov not in _COVERAGE_RANK:
                continue
            existing = assertions_by_req.get(rid)
            if existing is None or _COVERAGE_RANK[cov] > _COVERAGE_RANK[existing["coverage"]]:
                assertions_by_req[rid] = {
                    "coverage": cov,
                    "confidence": a.get("confidence", "Medium"),
                    "evidence": (a.get("evidence") or "")[:300],
                    "location": chunk_label,
                }

    rows = []
    for r in requirements:
        rid = r.get("req_id") or ""
        hit = assertions_by_req.get(rid)
        base = {
            "req_id": rid, "category": r.get("category", ""),
            "description": (r.get("description") or "")[:160],
            # Computed once here, against the FULL original requirement
            # dict (not the truncated description above) -- see
            # _compute_score()/_extract_mandatory_failures() for why this
            # exists and how it's used; stripped before the result is
            # ever returned to a caller.
            "_is_qualification_gate": has_supplier_qualification_evidence(r),
        }
        if hit:
            rows.append({
                **base,
                "coverage": hit["coverage"], "confidence": hit["confidence"],
                "evidence_location": hit["location"], "notes": hit["evidence"],
            })
        elif coverage_complete:
            rows.append({
                **base,
                "coverage": "Not Addressed", "confidence": "High",
                "evidence_location": "", "notes": "No supporting evidence found anywhere in the analyzed proposal.",
            })
        else:
            rows.append({
                **base,
                "coverage": "Cannot Assess", "confidence": "Low",
                "evidence_location": "", "notes": "Proposal coverage is incomplete -- absence cannot be confirmed.",
            })
    return rows


_ALIGN_SCORE_BASIS_BUYER_WEIGHTED = "Buyer-weighted evaluation criteria"
_ALIGN_SCORE_BASIS_NO_BUYER_WEIGHTS = "Internal equal-weight evaluation criteria — buyer weights unavailable"
_ALIGN_SCORE_BASIS_INCOMPLETE_WEIGHTS = "Internal equal-weight evaluation criteria — buyer weighting incomplete"
_ALIGN_SCORE_BASIS_NO_EVALUATION_CRITERIA = "No evaluative criteria identified"

# Categories that are, by procurement convention, the buyer's numerically
# evaluated/rated criteria -- the ONLY set eligible for the Evaluation
# Alignment Score by default. "Mandatory" requirements are qualification
# gates, evaluated pass/fail, never part of a numeric average (instruction
# 1.B). Anything else (Supporting, Commercial, Contractual, etc.) joins the
# evaluation set ONLY if the procurement itself made it evaluative, i.e. the
# buyer gave it an explicit weight -- never assumed, never equal-weighted in
# by category alone (instruction 1.C).
_ALIGN_EVALUATIVE_CATEGORIES = {"rated", "financial"}


def _valid_weight(w) -> bool:
    return isinstance(w, (int, float)) and not isinstance(w, bool) and w > 0


def _compute_score(requirement_coverage: list[dict]) -> dict:
    """Evaluation Alignment Score -- instruction 1's corrected scoring
    universe. Three requirement classes are kept strictly separate:

      A. Evaluation criteria (category Rated/Financial, OR any other
         category the buyer explicitly gave a valid weight to -- that
         weight IS the procurement making it evaluative). This is the
         ONLY set the numeric score is computed from.
      B. Mandatory/qualification requirements -- ALWAYS excluded from
         the numeric average regardless of any weight value; they are
         gates, handled separately by _extract_mandatory_failures() /
         _derive_recommendation()'s override. This is category-based
         (category == Mandatory) OR semantic (the requirement's own
         text carries supplier-qualification/eligibility cues, per
         requirement_semantics.has_supplier_qualification_evidence() --
         the same governed cue-detection already used for DECIDE/CHECK's
         own Qualification Gates KPI) -- so a qualification/eligibility
         gate is excluded from the score regardless of what category it
         happens to be filed under, and regardless of any stray weight.
      C. Everything else (Supporting, Commercial, Contractual, etc.
         with no buyer weight) -- stays in requirement_coverage/
         findings for visibility, but is never an equal-weight
         contributor to the score merely by existing.

    Scoring rubric: Fully Addressed = 100, Partially Addressed = 50,
    Not Addressed = 0. 'Cannot Assess' rows are excluded from the
    calculation entirely (neither numerator nor denominator) -- unknown
    coverage must never silently lower the score.

    Buyer weights are used, and mathematically normalized if they do
    not already sum to 1, ONLY when EVERY evaluation-set requirement
    carries a valid weight (a positive, non-boolean numeric `weight`
    field -- no other field is ever treated as a weight). If weighting
    is missing entirely or only partial/ambiguous, the score falls back
    to an explicitly labelled internal equal-weight average across the
    same evaluation set -- no weight is ever invented for a requirement
    that doesn't have one, and no requirement that DOES have one is
    ever silently dropped just because a neighbor lacks one.

    If the resulting evaluation set is empty -- a procurement with real
    requirements but no legitimate rated/evaluative criteria at all
    (only mandatory/qualification/commercial/supporting items) -- no
    score is invented from that non-evaluative set; overall_score is
    None with score_basis _ALIGN_SCORE_BASIS_NO_EVALUATION_CRITERIA."""
    evaluation_set = [
        r for r in requirement_coverage
        if (r["category"] or "").strip().lower() != "mandatory"
        and not r.get("_is_qualification_gate")
        and r["coverage"] in _COVERAGE_SCORE_MAP
        and (
            (r["category"] or "").strip().lower() in _ALIGN_EVALUATIVE_CATEGORIES
            or _valid_weight(r.get("_weight"))
        )
    ]
    if not evaluation_set:
        return {"overall_score": None, "score_basis": _ALIGN_SCORE_BASIS_NO_EVALUATION_CRITERIA}

    weights = [r.get("_weight") for r in evaluation_set]
    valid_flags = [_valid_weight(w) for w in weights]

    if all(valid_flags):
        total_w = sum(weights)  # normalized mathematically via division, not assumed to sum to 1
        score = sum(_COVERAGE_SCORE_MAP[r["coverage"]] * w for r, w in zip(evaluation_set, weights)) / total_w
        basis = _ALIGN_SCORE_BASIS_BUYER_WEIGHTED
    elif any(valid_flags):
        # Incomplete/ambiguous buyer weighting -- do not invent the
        # missing weights and do not drop the requirements that have
        # them either; fall back to equal weight across the whole set.
        score = sum(_COVERAGE_SCORE_MAP[r["coverage"]] for r in evaluation_set) / len(evaluation_set)
        basis = _ALIGN_SCORE_BASIS_INCOMPLETE_WEIGHTS
    else:
        score = sum(_COVERAGE_SCORE_MAP[r["coverage"]] for r in evaluation_set) / len(evaluation_set)
        basis = _ALIGN_SCORE_BASIS_NO_BUYER_WEIGHTS

    return {"overall_score": round(score, 1), "score_basis": basis}


def _extract_mandatory_failures(requirement_coverage: list[dict]) -> list[dict]:
    """A requirement surfaces as a mandatory/qualification risk when it
    is Mandatory-category OR semantically a supplier-qualification/
    eligibility gate (see _compute_score()'s docstring -- the same
    signal, so a gate is excluded from the score AND flagged as a risk
    consistently, never one without the other) AND was not addressed."""
    return [
        {
            "req_id": r["req_id"], "category": r["category"], "description": r["description"],
            "coverage": r["coverage"],
            "reason": r["notes"] or "Mandatory/qualification requirement not addressed in the analyzed proposal.",
        }
        for r in requirement_coverage
        if ((r["category"] or "").strip().lower() == "mandatory" or r.get("_is_qualification_gate"))
        and r["coverage"] == "Not Addressed"
    ]


_ALIGN_REC_NO_EVALUATIVE_CRITERIA = "REVIEW — NO EVALUATIVE CRITERIA IDENTIFIED"


def _derive_recommendation(overall_score: float | None, mandatory_failures: list[dict]) -> tuple[str, str]:
    """Mandatory failures always override the recommendation -- a high
    numeric score can never make a mandatory failure look acceptable.

    A None score with NO mandatory failures is the zero-evaluation-
    universe case (instruction 2): a procurement can be genuinely,
    completely audited and simply contain no legitimate rated/
    evaluative criteria at all (only mandatory/commercial/supporting
    requirements, all of which are otherwise fine). That is not a
    failure, and must not be presented as one -- it gets its own
    distinct, non-alarming recommendation value rather than being
    forced into "MAJOR REVISION NEEDED", which would misrepresent a
    clean, complete audit as a problem."""
    if mandatory_failures:
        return (
            "MAJOR REVISION NEEDED",
            f"{len(mandatory_failures)} mandatory/qualification requirement(s) have no supporting evidence "
            f"in the analyzed proposal -- this overrides the numeric score.",
        )
    if overall_score is None:
        return (
            _ALIGN_REC_NO_EVALUATIVE_CRITERIA,
            "This procurement's requirements contain no legitimate rated/evaluative criteria to score "
            "(only mandatory, qualification, commercial, or supporting requirements were found, and none "
            "of them failed) -- there is no numeric Evaluation Alignment Score to compute, by design, not "
            "because the audit failed.",
        )
    if overall_score >= 85:
        return ("SUBMIT AS-IS", f"{overall_score:.0f}/100 structured alignment score.")
    if overall_score >= 60:
        return ("REVISE BEFORE SUBMITTING", f"{overall_score:.0f}/100 structured alignment score.")
    return ("MAJOR REVISION NEEDED", f"{overall_score:.0f}/100 structured alignment score.")


_FINDING_SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


def _theme_has(text: str, *patterns: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _classify_finding_theme(finding: dict) -> str:
    """Deterministic finding-theme classifier (no LLM call) -- gives
    dedup a real axis to cluster on beyond bare requirement ID, so a
    requirement with several genuinely different gaps (e.g. incomplete
    pricing vs. unclear expense assumptions vs. an unsigned declaration)
    stays as separate findings instead of over-merging."""
    text = f"{finding.get('title', '')} {finding.get('issue', '')}"
    pricing_kw = _theme_has(text, r"\bpric(e|ing)\b", r"\bcost\b", r"\bfee\b", r"\brate\b", r"\bexpense\b")
    if _theme_has(text, r"\bmissing\b", r"not\s+(provided|included|found|submitted|attached)", r"does\s+not\s+exist"):
        return "Missing required artifact"
    if _theme_has(text, r"\bsignature\b", r"\bsigned\b", r"sign[- ]off", r"\bunsigned\b"):
        return "Mandatory form/signature"
    if pricing_kw and _theme_has(text, r"\bincomplete\b", r"\bmissing\b", r"not\s+(provided|included)"):
        return "Pricing completeness"
    if pricing_kw and _theme_has(text, r"\bunclear\b", r"\bambiguous\b", r"\bvague\b", r"\bassumption\b"):
        return "Pricing clarity"
    if _theme_has(text, r"\binsufficient\b", r"\bweak(ness)?\b", r"\binadequate\b", r"lacks?\s+(detail|evidence|specificity)"):
        return "Evidence weakness"
    if _theme_has(text, r"\bmethodolog(y|ies)\b"):
        return "Methodology gap"
    if _theme_has(text, r"\bqualificat", r"\beligib", r"\bcertif", r"\baccredit", r"\bcompliance\b"):
        return "Qualification/compliance"
    if _theme_has(text, r"\bformat\b", r"\bformality\b", r"\badministrat", r"\bchecklist\b", r"\bpage\s+limit\b", r"\btemplate\b"):
        return "Administrative/formality"
    if _theme_has(text, r"\bprivacy\b", r"data\s+protection", r"\bsecurity\b", r"\bsafeguard", r"\bconfidential"):
        return "Data/privacy safeguard"
    if _theme_has(text, r"\bincomplete\b", r"\bpartial\b", r"not\s+fully"):
        return "Incomplete content"
    return "Other"


def _aggregate_findings(chunk_results: list[dict]) -> list[dict]:
    findings = []
    for cr in chunk_results:
        for f in cr.get("chunk_findings", []):
            f = dict(f)
            f["proposal_location"] = cr["chunk_label"]
            f["finding_type"] = _classify_finding_theme(f)
            findings.append(f)
    findings.sort(key=lambda f: _FINDING_SEVERITY_ORDER.get(f.get("severity", "Medium"), 2))
    return findings


# ── PACKAGE-LEVEL FINDING RECONCILIATION ──────────────────────────────────
# A chunk only ever sees its own section -- it cannot know what evidence
# exists elsewhere in the proposal/package, so a chunk-level "this is
# missing" observation is only ever a LOCAL opinion, never package-level
# truth. Package-level truth is what _aggregate_requirement_coverage()
# already computed deterministically from every chunk's positive
# assertions. Reconciliation cross-checks the two and never lets a local
# opinion contradict the deterministic package-wide result.

_EXISTENCE_ABSENCE_RE = re.compile(
    r"\b(is\s+missing|not\s+(provided|included|found|present|submitted|attached)|"
    r"does\s+not\s+exist|no\s+(copy|evidence|document|schedule|form|certificate|declaration)\b|"
    r"could\s+not\s+(locate|find)|\babsent\b|not\s+attached|"
    r"was\s+not\s+(included|provided|submitted))\b",
    re.IGNORECASE,
)

_BOUNDARY_ARTIFACT_RE = re.compile(
    r"\b(appears?\s+truncated|response\s+is\s+incomplete|table\s+is\s+cut\s*off|"
    r"document\s+(appears?\s+to\s+)?(ends?|stops?)\s+(mid[- ]sentence|abruptly)|"
    r"section\s+[\w\s]{0,25}?(appears?\s+(?:to\s+be\s+)?)?(cut\s*off|truncated)|"
    r"text\s+(appears?\s+)?truncated|"
    r"ends?\s+abruptly|incomplete\s+response|content\s+continues?\s+beyond\s+this\s+excerpt|"
    r"cannot\s+confirm\s+(beyond|past)\s+this\s+(point|section|excerpt)|"
    r"(this|the)\s+(chunk|excerpt|section)\s+ends?\s+(at|after)\s+[\d,]+\s+characters?|"
    r"cuts?\s+off\s+mid[- ](table|sentence|paragraph)|"
    r"table\s+[\w\s]{0,15}?cuts?\s+off)\b",
    re.IGNORECASE,
)

# A finding/coverage-note phrase that scopes an absence claim to THIS
# excerpt/chunk specifically ("not present in this section excerpt") --
# distinct from _BOUNDARY_ARTIFACT_RE (which flags outright truncation
# claims): this is a local-scope existence claim, stripped from
# requirement_coverage's own gap/evidence text whenever the row already
# carries real (Fully/Partially Addressed) package-wide evidence, since
# "not present in THIS excerpt" is a true-but-irrelevant local
# observation once OTHER evidence has already been found for the same
# requirement.
_LOCAL_EXCERPT_ABSENCE_RE = re.compile(
    r"\b(not\s+present\s+in\s+this\s+(?:section\s+excerpt|section|excerpt|chunk)|"
    r"not\s+(?:addressed|visible|found|included)\s+in\s+this\s+(?:section\s+excerpt|section|excerpt|chunk)|"
    r"cannot\s+be\s+seen\s+(?:here|in\s+this\s+(?:section|excerpt|chunk))|"
    r"(?:is\s+)?absent\s+from\s+this\s+(?:section\s+excerpt|section|excerpt|chunk)|"
    r"excluded\s+from\s+this\s+(?:section\s+excerpt|section|excerpt|chunk))\b",
    re.IGNORECASE,
)

# A record that is not a finding at all -- purely positive/no-issue
# chunk output that should never have been emitted into chunk_findings
# in the first place. Matched against the WHOLE (stripped) title or
# issue text, not a substring, so it only catches genuinely empty
# "findings" rather than a real finding that happens to mention one of
# these phrases in passing.
_NON_FINDING_RE = re.compile(
    r"^(no\s+(?:gap|issue|deficiency|concern)s?\s+(?:identified|found|noted)|"
    r"requirement\s+(?:is\s+)?satisfied|"
    r"maintain\s+current\s+documentation|"
    r"fully\s+compliant|"
    r"no\s+action\s+(?:required|needed))\s*\.?\s*$",
    re.IGNORECASE,
)

# A genuine, structured, SOURCE-level signal -- never a bare "chunk
# failed" or "file is in unusable_files" alone (analysis-engine failure
# and physical source-document corruption are different things; only
# the extractor's OWN reported reason text, cross-checked against this
# finding's own source filename, counts as real evidence).
_TRUNCATION_SOURCE_EVIDENCE_RE = re.compile(
    r"truncat|corrupt|unreadable|could\s+not\s+be\s+parsed|parsing\s+failed|damaged|incomplete\s+workbook",
    re.IGNORECASE,
)

_INTERNAL_CHUNK_LANGUAGE_RE = re.compile(
    r"\b(this\s+(chunk|excerpt|section\s+alone)|first\s+[\d,]+\s+characters?|"
    r"within\s+this\s+(chunk|excerpt)|in\s+this\s+excerpt)\b",
    re.IGNORECASE,
)


def _finding_is_existence_absence_claim(finding: dict) -> bool:
    text = f"{finding.get('title', '')} {finding.get('issue', '')}"
    return bool(_EXISTENCE_ABSENCE_RE.search(text))


# Vocabulary that describes the CLAIM ("missing", "not provided") rather
# than the ARTIFACT being claimed missing ("Schedule A", "signature") --
# stripped out when extracting artifact keywords for the evidence-aware
# contradiction check below, so "missing" itself never counts as a
# spurious keyword match against unrelated evidence text.
_ABSENCE_CLAIM_VOCAB = {
    "missing", "absent", "provided", "included", "found", "present", "submitted",
    "attached", "exist", "exists", "locate", "confirm", "confirmed", "documented", "mentioned",
}


def _extract_artifact_keywords(text: str) -> frozenset:
    """Keywords describing the ARTIFACT/EVIDENCE at stake, never the
    absence-claim vocabulary itself. When `text` contains an existence/
    absence cue phrase (the finding side, e.g. "...is missing"), ONLY
    the words BEFORE that cue are used -- the grammatical subject of "X
    is missing/absent/not provided". This deliberately excludes words
    AFTER the cue, which are typically a location/container modifier
    ("missing FROM the declaration form") rather than the actual absent
    element ("the signature") -- without this, a finding like "The
    signature is missing from the declaration form" would spuriously
    match evidence that only proves the FORM exists, not that it is
    signed. When `text` has no such cue (the evidence side -- a
    coverage row's own evidence_location + notes, which only ever
    reports positive findings), the whole text is used."""
    match = _EXISTENCE_ABSENCE_RE.search(text)
    subject_text = text[:match.start()] if match else text
    return _issue_keywords(subject_text) - _ABSENCE_CLAIM_VOCAB


def _package_evidence_contradicts_absence_claim(finding: dict, coverage_row: dict) -> bool:
    """Deterministic, no-LLM evidence-aware check for a 'Partially
    Addressed' requirement: does the coverage row's OWN positive
    evidence (its evidence_location + notes -- the manifest/source
    filename identity and the aggregated evidence text) specifically
    name the same artifact the finding claims is absent? 'Partially
    Addressed' alone is never sufficient justification to suppress --
    a requirement can be partially addressed for a completely different,
    still-real reason than the one a specific finding names (e.g. the
    form exists but isn't signed; some pricing exists but a required
    schedule is genuinely absent). Only a real keyword overlap between
    what the finding says is missing and what the coverage row's own
    evidence actually names counts as a contradiction."""
    finding_terms = _extract_artifact_keywords(f"{finding.get('title', '')} {finding.get('issue', '')}")
    if not finding_terms:
        return False
    evidence_text = f"{coverage_row.get('evidence_location', '')} {coverage_row.get('notes', '')}"
    evidence_terms = _extract_artifact_keywords(evidence_text)
    return bool(finding_terms & evidence_terms)


def _finding_is_chunk_boundary_artifact(finding: dict) -> bool:
    text = f"{finding.get('title', '')} {finding.get('issue', '')}"
    return bool(_BOUNDARY_ARTIFACT_RE.search(text))


def _finding_source_filename(finding: dict) -> str | None:
    loc = finding.get("proposal_location") or ""
    if " — " in loc:
        return loc.split(" — ", 1)[0]
    return None


def _has_source_level_truncation_evidence(filename: str | None, unusable_files: list[dict]) -> bool:
    if not filename:
        return False
    for uf in unusable_files:
        if uf.get("filename") == filename and _TRUNCATION_SOURCE_EVIDENCE_RE.search(uf.get("reason") or ""):
            return True
    return False


def _strip_internal_chunk_language(text: str) -> str:
    cleaned = _INTERNAL_CHUNK_LANGUAGE_RE.sub("", text or "")
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _finding_is_non_finding(finding: dict) -> bool:
    """A record that carries no actual gap/issue -- 'No gap identified',
    'Requirement satisfied', 'Maintain current documentation', etc.
    Positive evidence belongs in requirement_coverage/strengths, never
    in AUDIT FINDINGS."""
    for text in (finding.get("title") or "", finding.get("issue") or ""):
        if _NON_FINDING_RE.match(text.strip()):
            return True
    return False


def _split_compound_req_ids(raw_req_id: str, canonical_req_ids: set) -> list[str]:
    """Normalizes a possibly-compound req_id string ("M5, M6", "M5/M6",
    "R5, R6, R7") into the list of individual CANONICAL req_ids it
    actually references. A bare single req_id that's already canonical
    returns as a one-item list unchanged. Any fragment that isn't a
    known canonical req_id is dropped (never invents a requirement)."""
    if not raw_req_id:
        return []
    if raw_req_id in canonical_req_ids:
        return [raw_req_id]
    parts = re.split(r"\s*(?:,|/|&|\band\b)\s*", raw_req_id.strip())
    return [p for p in parts if p in canonical_req_ids]


# Deterministic, filename-based canonical-artifact identity -- covers
# the small set of near-universally-named procurement submission
# artifacts explicitly called out in this remediation. Never claims an
# artifact exists based on chunk/model text, only on the Submission
# Package Manifest's own file list.
_CANONICAL_ARTIFACT_PATTERNS = {
    "technical proposal": [r"technical\s+proposal"],
    "financial proposal": [r"financial\s+proposal", r"pricing\s+proposal", r"price\s+proposal"],
    "schedule a": [r"schedule\s*a\b", r"ai\s+disclosure"],
    "submission form": [r"submission\s+form", r"supplement\s+a\b"],
}


def _build_artifact_existence_map(package_files: list[dict]) -> dict[str, bool]:
    """Deterministic artifact-existence map built ONLY from the
    Submission Package's own included, analyzable files (never from
    chunk/model text) -- filename + package_path matched against a
    small set of canonical, near-universally-named procurement
    artifacts. Presence here means the FILE is in the package; it says
    nothing about that file's content compliance, signature, format, or
    completeness -- see _finding_claims_absent_artifact_present_in_
    manifest()'s docstring for why that distinction matters."""
    present = {name: False for name in _CANONICAL_ARTIFACT_PATTERNS}
    for f in package_files or []:
        if not f.get("analyzable"):
            continue
        haystack = f"{f.get('filename', '')} {f.get('package_path', '')}"
        for name, patterns in _CANONICAL_ARTIFACT_PATTERNS.items():
            if present[name]:
                continue
            if any(re.search(p, haystack, re.IGNORECASE) for p in patterns):
                present[name] = True
    return present


def _finding_claims_absent_artifact_present_in_manifest(finding: dict, artifact_map: dict) -> bool:
    """A STRONGER, manifest-only suppression signal alongside the per-
    req_id evidence-aware check: if a finding is an existence/absence
    claim and names one of the canonical artifacts BY NAME, and that
    exact file is confirmed present in the Submission Package Manifest,
    the claim is false regardless of req_id matching (covers findings
    with no/wrong req_id). Never suppresses a CONTENT-quality finding
    (e.g. "signature is blank on Supplement A") -- artifact presence
    does not prove content compliance, only that the file exists."""
    if not artifact_map or not _finding_is_existence_absence_claim(finding):
        return False
    text = f"{finding.get('title', '')} {finding.get('issue', '')}".lower()
    return any(is_present and name in text for name, is_present in artifact_map.items())


def _clean_coverage_row_text(text: str) -> str:
    """Strips chunk-boundary and local-excerpt-scoped absence language
    from a requirement_coverage row's own notes/evidence text -- see
    _reconcile_requirement_coverage_text()'s docstring for why this
    field (unlike findings) was never cleaned before."""
    cleaned = _BOUNDARY_ARTIFACT_RE.sub("", text or "")
    cleaned = _LOCAL_EXCERPT_ABSENCE_RE.sub("", cleaned)
    cleaned = _strip_internal_chunk_language(cleaned)
    cleaned = re.sub(r"\s*[,;]\s*(?=[,;.]|$)", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.;")
    return cleaned or "Evidence confirmed elsewhere in the analyzed submission package."


def _reconcile_requirement_coverage_text(requirement_coverage: list[dict]) -> list[dict]:
    """Package-level reconciliation for requirement_coverage ROWS
    THEMSELVES, not only findings. A row's 'notes' field is the winning
    chunk assertion's own free-text 'evidence' string, verbatim -- the
    model can write self-contradictory LOCAL-scope language into that
    field even for a genuinely positive (Fully/Partially Addressed)
    assertion, e.g. "Financial Proposal addressed with cost detail, but
    not present in this section excerpt" or "...Section 6 appears
    truncated". The row's own COVERAGE STATE is already deterministically
    correct (the strongest assertion across every chunk, computed in
    _aggregate_requirement_coverage) -- what needs cleaning is only the
    accompanying text, which must never contradict that state by
    implying the artifact is absent or that the SOURCE document itself
    is truncated (both are artifacts of what ONE excerpt could see, not
    package-level facts). Cannot Assess / Not Addressed rows already
    carry a fixed, safe, deterministic fallback string (never chunk-
    generated) and are left untouched -- mutates and returns the same
    list for convenience."""
    for row in requirement_coverage:
        if row.get("coverage") in ("Fully Addressed", "Partially Addressed"):
            row["notes"] = _clean_coverage_row_text(row.get("notes", ""))
    return requirement_coverage


def _build_unresolved_items(requirement_coverage: list[dict]) -> list[dict]:
    """One deterministic item per requirement the package COULDN'T
    confirm (coverage == 'Cannot Assess') -- must be called BEFORE
    `_is_qualification_gate` is popped from the rows, so mandatory/
    qualification-gate items can still be identified here. This is the
    single source of truth for "needs verification" -- chunk-level
    findings tied to the same req_id are dropped during reconciliation
    rather than duplicated here."""
    items = []
    for r in requirement_coverage:
        if r.get("coverage") != "Cannot Assess":
            continue
        is_mandatory_or_gate = (
            (r.get("category") or "").strip().lower() == "mandatory" or bool(r.get("_is_qualification_gate"))
        )
        desc = r.get("description") or "this requirement"
        items.append({
            "req_id": r.get("req_id"), "category": r.get("category", ""),
            "description": r.get("description", ""),
            "is_mandatory_or_qualification": is_mandatory_or_gate,
            "reason": (
                f"{r.get('req_id', '')} — {desc} could not be assessed because relevant package "
                "sections were not successfully analyzed."
            ),
        })
    return items


def _reconcile_findings_with_package_evidence(
    findings: list[dict], requirement_coverage: list[dict], unusable_files: list[dict],
    requirements: list[dict] | None = None, artifact_existence_map: dict | None = None,
) -> list[dict]:
    """Deterministic, no-LLM reconciliation between chunk-local findings
    and the already-final package-wide requirement_coverage:

      * Non-findings ("No gap identified", "Requirement satisfied", ...)
        are dropped outright -- positive evidence belongs in coverage/
        strengths, never in AUDIT FINDINGS.
      * A compound req_id ("M5, M6", "M5/M6") is split against the
        canonical requirement IDs before every check below; if EVERY
        referenced requirement is Cannot Assess, the finding is dropped
        (the uncertainty is already represented once, per requirement,
        in unresolved_items) rather than surviving because the literal
        string "M5, M6" never matched a single coverage row.
      * Cannot Assess (single req_id) -- same drop, for the same reason.
      * Fully Addressed -- an EXISTENCE/absence claim (e.g. "Schedule A
        is missing") is suppressed unconditionally, because the
        deterministic package-level result already establishes full
        coverage for this requirement.
      * Partially Addressed -- "Partially Addressed" ALONE never proves
        the specific artifact a finding names actually exists (the
        requirement can be partially addressed for a completely
        different, still-real reason -- e.g. a declaration FORM exists
        but isn't SIGNED, or some pricing exists but a required
        schedule is genuinely absent). An existence/absence claim is
        suppressed here ONLY when
        _package_evidence_contradicts_absence_claim() finds the
        coverage row's OWN evidence (evidence_location + notes) names
        the SAME artifact the finding claims is missing -- a real,
        deterministic keyword-level contradiction, not the bare
        Partially-Addressed status.
      * Manifest-aware suppression (independent of req_id matching): if
        `artifact_existence_map` confirms a canonical artifact (e.g.
        "Technical Proposal") is present in the Submission Package, any
        existence/absence claim naming that artifact is suppressed --
        this catches findings with no/wrong req_id that the per-row
        check above can't reach. Never suppresses a content-quality
        claim about that same artifact (artifact presence doesn't prove
        signature/format/completeness).
      * A CONTENT-QUALITY finding (e.g. "safeguards described are
        insufficient") is NOT an existence claim and is always kept --
        it describes something coverage aggregation doesn't already
        capture.
      * Chunk-boundary artifacts ("appears truncated", "ends abruptly",
        etc.) are suppressed unless this finding's own source file has a
        genuine, structured extraction-level truncation/corruption
        signal -- never a bare failed-chunk or unusable-file membership
        alone.
      * Category canonicalization: when a finding's (single) req_id
        matches a canonical requirement, its displayed category is
        overwritten from that canonical requirement's own category --
        never trusts arbitrary per-chunk category wording, so the same
        requirement can't appear under inconsistent categories.
    """
    coverage_by_req = {r["req_id"]: r for r in requirement_coverage if r.get("req_id")}
    category_by_req = {r.get("req_id"): r.get("category") for r in (requirements or []) if r.get("req_id")}
    canonical_req_ids = set(coverage_by_req.keys())
    artifact_existence_map = artifact_existence_map or {}

    reconciled = []
    for f in findings:
        if _finding_is_non_finding(f):
            continue

        if _finding_is_chunk_boundary_artifact(f):
            src = _finding_source_filename(f)
            if not _has_source_level_truncation_evidence(src, unusable_files):
                continue

        if _finding_claims_absent_artifact_present_in_manifest(f, artifact_existence_map):
            continue

        raw_req_id = f.get("req_id") or ""
        req_ids = _split_compound_req_ids(raw_req_id, canonical_req_ids)

        if len(req_ids) > 1:
            # Compound reference (e.g. "M5, M6") -- if EVERY referenced
            # requirement is Cannot Assess, this is the exact same
            # uncertainty unresolved_items already represents once per
            # requirement; drop rather than let the compound string
            # dodge the single-req_id check below.
            states = [coverage_by_req[rid].get("coverage") for rid in req_ids]
            if states and all(s == "Cannot Assess" for s in states):
                continue
        elif len(req_ids) == 1:
            cov_row = coverage_by_req.get(req_ids[0])
            if cov_row is not None:
                cov_state = cov_row.get("coverage")
                if cov_state == "Cannot Assess":
                    continue
                if _finding_is_existence_absence_claim(f):
                    if cov_state == "Fully Addressed":
                        continue
                    if cov_state == "Partially Addressed" and _package_evidence_contradicts_absence_claim(f, cov_row):
                        continue

        f = dict(f)
        f["issue"] = _strip_internal_chunk_language(f.get("issue", "")) or f.get("issue", "")
        if len(req_ids) == 1 and category_by_req.get(req_ids[0]):
            f["category"] = category_by_req[req_ids[0]]
        reconciled.append(f)
    return reconciled


def _findings_describe_same_theme(a: dict, b: dict) -> bool:
    if (a.get("req_id"), a.get("category"), a.get("finding_type")) != (b.get("req_id"), b.get("category"), b.get("finding_type")):
        return False
    ka, kb = _issue_keywords(a.get("issue", "")), _issue_keywords(b.get("issue", ""))
    if not ka or not kb:
        return (a.get("issue", "") or "").strip().lower() == (b.get("issue", "") or "").strip().lower()
    overlap = len(ka & kb) / len(ka | kb)
    return overlap >= 0.5


_DEDUP_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "this", "that", "in", "on", "for", "to",
    "of", "and", "or", "not", "it", "be", "as", "with", "at", "by", "from", "section",
    "here", "file", "has", "have", "been", "will", "would", "could", "should",
}


def _issue_keywords(text: str) -> frozenset:
    words = re.findall(r"[a-z]{4,}", (text or "").lower())
    return frozenset(w for w in words if w not in _DEDUP_STOPWORDS)


def _deduplicate_findings(findings: list[dict]) -> list[dict]:
    """Deterministic, theme-aware consolidation (no LLM call): findings
    only cluster when req_id, category, AND the deterministic finding
    theme all match, AND their issue-text keyword overlap clears a fixed
    threshold -- so a requirement with several genuinely different gaps
    (e.g. incomplete pricing vs. unclear assumptions vs. an unsigned
    declaration, all tied to the same req_id) stays as distinct findings,
    while repeated local observations of the SAME underlying problem
    across different chunks/files collapse into one. Keeps the
    strongest-severity version, merges distinct evidence locations
    (capped, with a '+N more' tail), and strips internal chunk-local
    language from the surviving issue text."""
    clusters: list[list[dict]] = []
    for f in findings:
        placed = False
        for cluster in clusters:
            if _findings_describe_same_theme(cluster[0], f):
                cluster.append(f)
                placed = True
                break
        if not placed:
            clusters.append([f])

    deduped = []
    for cluster in clusters:
        best = min(cluster, key=lambda f: _FINDING_SEVERITY_ORDER.get(f.get("severity", "Medium"), 2))
        merged = dict(best)
        merged["issue"] = _strip_internal_chunk_language(merged.get("issue", "")) or merged.get("issue", "")
        locations, seen = [], set()
        for f in cluster:
            loc = f.get("proposal_location")
            if loc and loc not in seen:
                seen.add(loc)
                locations.append(loc)
        if len(locations) > 1:
            shown = locations[:3]
            extra = len(locations) - len(shown)
            merged["proposal_location"] = "; ".join(shown) + (f" (+{extra} more)" if extra > 0 else "")
        deduped.append(merged)

    deduped.sort(key=lambda f: _FINDING_SEVERITY_ORDER.get(f.get("severity", "Medium"), 2))
    return deduped


def _select_priority_actions(mandatory_failures: list[dict], findings: list[dict], max_n: int = 10) -> list[dict]:
    """Deterministic "Priority Actions Before Submission" selector:
    established mandatory/qualification failures first (Critical, by
    definition -- they already override any score), then Proposal-
    Submission-stage findings by severity (Critical, then High, then
    Medium only if space remains). Deliberately excludes negotiation-
    stage, execution-stage, and contractual-obligation-stage findings
    (not actionable before submission), and Cannot-Assess/unresolved
    items (not established defects)."""
    actions: list[dict] = []
    used_req_ids = set()

    for mf in mandatory_failures:
        if len(actions) >= max_n:
            return actions[:max_n]
        actions.append({
            "source": "mandatory_failure", "severity": "Critical", "req_id": mf.get("req_id"),
            "title": f'{mf.get("req_id", "")} — Mandatory requirement not addressed',
            "detail": mf.get("reason", ""),
        })
        used_req_ids.add(mf.get("req_id"))

    submission_findings = [f for f in findings if (f.get("stage") or "") == "Proposal Submission"]
    for sev in ("Critical", "High", "Medium"):
        for f in submission_findings:
            if len(actions) >= max_n:
                return actions[:max_n]
            if f.get("severity") != sev:
                continue
            if f.get("req_id") and f.get("req_id") in used_req_ids:
                continue
            actions.append({
                "source": "finding", "severity": sev, "req_id": f.get("req_id"),
                "title": f.get("title", ""), "detail": f.get("issue", ""),
                "recommendation": f.get("recommendation", ""),
            })
    return actions[:max_n]


_PARTIAL_AUDIT_HEADLINE = "This is a partial audit. No reliable overall alignment score is available."


def _build_partial_audit_summary(
    requirement_coverage: list[dict], unresolved_items: list[dict], coverage_metadata: dict,
    priority_actions: list[dict], failed_chunks_count: int, ceiling_skipped_count: int,
) -> dict:
    """Deterministic Partial Audit Summary (no LLM call) -- built purely
    from already-computed structured results, generated only when
    status == 'incomplete'. Distinguishes CONFIRMED gaps (Fully/
    Partially Addressed counts, established mandatory/qualification
    failures -- structurally always empty here, since 'Not Addressed'
    can only be assigned once coverage IS complete) from genuine
    UNKNOWNS (Cannot Assess count, unresolved mandatory/qualification
    items) rather than blending the two."""
    fully = sum(1 for r in requirement_coverage if r.get("coverage") == "Fully Addressed")
    partially = sum(1 for r in requirement_coverage if r.get("coverage") == "Partially Addressed")
    cannot_assess = sum(1 for r in requirement_coverage if r.get("coverage") == "Cannot Assess")
    unresolved_mandatory = [u for u in unresolved_items if u.get("is_mandatory_or_qualification")]
    return {
        "headline": _PARTIAL_AUDIT_HEADLINE,
        "coverage_percentage": coverage_metadata.get("percentage_covered", 0.0),
        "sections_analyzed": f'{coverage_metadata.get("successful_chunks", 0)}/{coverage_metadata.get("chunk_count", 0)}',
        "sections_failed": failed_chunks_count,
        "sections_ceiling_skipped": ceiling_skipped_count,
        "requirements_fully_addressed": fully,
        "requirements_partially_addressed": partially,
        "requirements_cannot_assess": cannot_assess,
        "established_mandatory_qualification_failures": [],
        "unresolved_mandatory_qualification_items": unresolved_mandatory,
        "priority_actions": priority_actions,
    }


_ALIGN_SYNTHESIS_SYSTEM = (
    "You write a concise executive narrative summarizing an already-completed, "
    "deterministic proposal alignment audit. You do NOT reassess coverage, "
    "scores, or mandatory failures -- those are fixed and provided to you as "
    "ground truth. Respond with valid JSON only."
)


def _synthesize_narrative(bid_header: str, overall_score: float | None, recommendation: str,
                           mandatory_failures: list[dict], requirement_coverage: list[dict],
                           findings: list[dict], coverage_meta: dict) -> dict | None:
    """One bounded final call over the already-fixed deterministic
    results. It may only produce narrative prose -- it never has the
    ability to alter coverage classifications, mandatory-failure status,
    the numeric score, or buyer weights, because none of those are
    passed to it as anything other than fixed, already-decided facts."""
    cov_counts = {
        c: sum(1 for r in requirement_coverage if r["coverage"] == c)
        for c in ("Fully Addressed", "Partially Addressed", "Not Addressed", "Cannot Assess")
    }
    finding_lines = "\n".join(
        f'- [{f.get("severity", "")}] {f.get("title", "")}: {f.get("issue", "")}' for f in findings[:25]
    ) or "None."

    prompt = f"""{bid_header}

Deterministic audit results (already final -- do not alter):
Score: {overall_score if overall_score is not None else "N/A"}/100 | Recommendation: {recommendation}
Requirement coverage counts: {cov_counts}
Mandatory failures: {len(mandatory_failures)}
Proposal coverage analyzed: {coverage_meta['percentage_covered']}% ({coverage_meta['successful_chunks']}/{coverage_meta['chunk_count']} sections)

Findings:
{finding_lines}

Write a concise executive narrative reflecting the results above exactly as given. Do NOT include a
score, recommendation, coverage percentage, weights, or mandatory-status field in your response --
those are fixed and rendered separately; restate them in prose only, never as separate JSON fields.
Return ONLY valid JSON, with EXACTLY these three keys and no others:
{{
  "executive_summary": "<max 300 chars, must be consistent with the score/recommendation above>",
  "strengths": ["<strength 1>", "<strength 2>", "<strength 3>"],
  "next_steps": [
    {{"priority": 1, "action": "<action>", "rationale": "<why it matters>",
      "when": "Before submission|If shortlisted|Before contract execution|Upon contract award"}}
  ]
}}"""
    try:
        raw = _call(_ALIGN_SYNTHESIS_SYSTEM, prompt, max_tokens=1500)
        parsed = _parse_json(raw)
    except Exception:
        return None
    if not isinstance(parsed, dict) or parsed.get("_truncated"):
        return None
    if not all(k in parsed for k in ("executive_summary", "strengths", "next_steps")):
        return None
    # Structural guarantee, not just prompt discipline: even if the model
    # ignores the instruction above and includes extra fields (a
    # score/recommendation/coverage/weight it invented), only these three
    # narrative keys are ever read out of its response -- everything else
    # is discarded here, never reaching the deterministic result.
    return {
        "executive_summary": parsed["executive_summary"],
        "strengths": parsed["strengths"],
        "next_steps": parsed["next_steps"],
    }


_ALIGNMENT_REQUIRED_KEYS = (
    "status", "overall_score", "score_basis", "score_rationale", "recommendation",
    "executive_summary", "strengths", "findings", "mandatory_failures",
    "requirement_coverage", "next_steps", "coverage_metadata",
)


def _validate_alignment_contract(result: dict) -> bool:
    """The minimum result contract. Missing keys and legitimate empty
    values are NOT equivalent -- this checks presence and shape, not
    that arrays are non-empty (an empty findings list can be a
    legitimate, complete result)."""
    if not isinstance(result, dict):
        return False
    for key in _ALIGNMENT_REQUIRED_KEYS:
        if key not in result:
            return False
    for list_key in ("strengths", "findings", "mandatory_failures", "requirement_coverage", "next_steps"):
        if not isinstance(result[list_key], list):
            return False
    if not isinstance(result["coverage_metadata"], dict):
        return False
    return True


_ALIGN_INCOMPLETE_MESSAGE = "Alignment audit incomplete — no reliable score available"


def _process_chunks_concurrently(chunks: list[dict], bid_header: str, procurement_context: str,
                                  req_block: str) -> tuple[dict[int, dict], set[int], dict[int, dict]]:
    """Runs each chunk's (already internally retry-bounded)
    _call_alignment_chunk() call under a small, bounded thread pool --
    chunk calls are independent (each sees only its own section text),
    so concurrency changes only wall-clock latency, never the total call
    count, the deterministic aggregation order (the caller re-sorts by
    original chunk index, never completion order), or a failed chunk's
    fail-closed treatment (still recorded, still excluded from
    coverage). Returns (index -> parsed result, set of failed indices,
    index -> safe failure diagnostic {"filename","section","category",
    "attempts"} -- never the prompt, proposal text, or raw exception
    body)."""
    outputs: dict[int, dict] = {}
    failed: set[int] = set()
    diagnostics: dict[int, dict] = {}

    def _run_one(chunk: dict):
        # Package chunks (tagged by _allocate_package_chunk_budget with
        # source_filename) always carry the source filename in their
        # location label -- filename-qualified evidence locations are a
        # hard requirement for the multi-file submission package.
        # Legacy single-document chunks (no source_filename) keep their
        # original label format unchanged, preserving existing tests.
        if chunk.get("source_filename"):
            chunk_label = f'{chunk["source_filename"]} — {chunk["heading"]}'
        else:
            chunk_label = f'{chunk["heading"]} (section {chunk["index"] + 1}/{chunk["total"]})'
        prompt = _align_chunk_prompt(bid_header, procurement_context, req_block, chunk)
        try:
            parsed, failure_category = _call_alignment_chunk(prompt)
        except Exception:
            parsed, failure_category = None, _CHUNK_FAILURE_API_ERROR
        return chunk["index"], chunk_label, parsed, failure_category, chunk.get("source_filename")

    max_workers = max(1, min(_ALIGN_CHUNK_CONCURRENCY, len(chunks)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_run_one, c) for c in chunks]
        for future in concurrent.futures.as_completed(futures):
            idx, label, parsed, failure_category, source_filename = future.result()
            if parsed is None:
                failed.add(idx)
                diagnostics[idx] = {
                    "filename": source_filename, "section": label,
                    "category": failure_category or _CHUNK_FAILURE_UNKNOWN, "attempts": 2,
                }
            else:
                parsed["chunk_label"] = label
                outputs[idx] = parsed

    return outputs, failed, diagnostics


def analyze_proposal_alignment(
    proposal_text: str,
    requirements: list[dict],
    rfp_text: str,
    bid_info: dict,
) -> dict:
    """
    Multi-pass, chunk-traceable proposal alignment audit. Replaces the
    earlier single-call, first-8,000-characters-only version -- see the
    module-level comment above this section for the full remediation
    rationale.

    `rfp_text` is expected to be the caller's CANONICAL PROCUREMENT
    INTELLIGENCE context (bid_briefs + the compliance matrix), never raw
    bid notes -- see pages/stage_check.py's `_build_procurement_context`.

    Scoring is entirely deterministic (see _compute_score); the model is
    used only for (a) per-section positive-evidence assertions and
    findings -- never absence, since no single section can know what's
    missing elsewhere -- and (b) one final bounded narrative-synthesis
    pass over the already-fixed deterministic results.
    """
    text = proposal_text or ""
    chars_total = len(text)

    split = _merge_and_bound_sections(_split_proposal_into_sections(text))
    chunks = split["chunks"]

    if not chunks:
        return {
            "status": "incomplete",
            "message": _ALIGN_INCOMPLETE_MESSAGE,
            "reason": "No proposal text was available to analyze.",
            "coverage_metadata": {
                "chars_total": chars_total, "chars_processed": 0, "percentage_covered": 0.0,
                "chunk_count": 0, "successful_chunks": 0, "failed_or_skipped_chunks": 0,
                "sections": [], "coverage_complete": False,
            },
        }

    bid_header = f"BID: {bid_info.get('title', '')} | CLIENT: {bid_info.get('client', '')}"

    req_lines = []
    for r in requirements:
        cat = r.get("category", "")
        rid = r.get("req_id", "")
        desc = (r.get("description") or "")[:120]
        wt = f"{r['weight'] * 100:.0f}%" if r.get("weight") else ""
        ev = (r.get("evidence") or "")[:60]
        req_lines.append(f"[{cat}] {rid} {wt}: {desc} | Evidence: {ev}")
    req_block = "\n".join(req_lines) if req_lines else "No requirements loaded."

    procurement_context = (rfp_text or "")[:_ALIGN_MAX_PROCUREMENT_CONTEXT_CHARS] or \
        "No canonical procurement intelligence has been extracted for this bid yet."

    chunk_outputs, failed_indices, failure_diagnostics = _process_chunks_concurrently(
        chunks, bid_header, procurement_context, req_block
    )
    # Deterministic aggregation order: iterate `chunks` in their original,
    # stable order -- never the (nondeterministic) order concurrent
    # futures happen to complete in.
    chunk_results = [chunk_outputs[c["index"]] for c in chunks if c["index"] in chunk_outputs]
    successful_chunks = len(chunk_results)

    chars_processed = _union_chars_covered(
        [(c["start"], c["end"]) for c in chunks if c["index"] not in failed_indices]
    )
    percentage_covered = round(min(chars_processed / chars_total, 1.0) * 100, 1) if chars_total else 0.0
    coverage_complete = (
        percentage_covered >= _ALIGN_COVERAGE_COMPLETE_THRESHOLD
        and not failed_indices
        and not split["skipped_ranges"]
    )

    ceiling_diagnostics = [
        {"filename": None, "section": s.get("heading"), "category": "beyond_analysis_ceiling", "attempts": 0}
        for s in split["skipped_ranges"]
    ]
    failed_chunk_diagnostics = list(failure_diagnostics.values()) + ceiling_diagnostics

    coverage_metadata = {
        "chars_total": chars_total,
        "chars_processed": chars_processed,
        "percentage_covered": percentage_covered,
        "chunk_count": len(chunks) + len(split["skipped_ranges"]),
        "successful_chunks": successful_chunks,
        "failed_or_skipped_chunks": len(failed_indices) + len(split["skipped_ranges"]),
        "sections": [
            {"index": c["index"], "heading": c["heading"], "chars": c["end"] - c["start"]}
            for c in chunks
        ],
        "coverage_complete": coverage_complete,
        "failed_chunk_diagnostics": failed_chunk_diagnostics,
    }

    if successful_chunks == 0:
        return {
            "status": "incomplete",
            "message": _ALIGN_INCOMPLETE_MESSAGE,
            "reason": "Every proposal section failed to analyze (malformed or truncated model responses).",
            "coverage_metadata": coverage_metadata,
        }

    # Positive evidence already gathered (findings, requirement
    # assertions) is valid regardless of whether coverage is complete --
    # a chunk that WAS successfully analyzed really did find what it
    # found. What is NOT valid without complete coverage is a numeric
    # score or a recommendation: those would present a partial sample as
    # though it were a finished audit. So aggregate coverage/findings
    # unconditionally, but gate scoring, the mandatory-failure
    # determination, the recommendation, and narrative synthesis behind
    # `coverage_complete` -- fail closed rather than let a >ceiling or
    # partially-failed run look like a complete scored audit (instruction
    # 2). This also applies to a document beyond the chunk ceiling:
    # `coverage_complete` is already False whenever `skipped_ranges` is
    # non-empty, so it falls into this same fail-closed path, not a
    # silent partial score.
    requirement_coverage = _aggregate_requirement_coverage(requirements, chunk_results, coverage_complete)
    findings = _aggregate_findings(chunk_results)
    # Package-level reconciliation (before _is_qualification_gate is
    # popped from the rows, so unresolved_items can still tell a
    # mandatory/qualification-gate requirement apart): neither a chunk-
    # local finding NOR a requirement_coverage row's own notes text is
    # ever allowed to contradict the deterministic, package-wide result
    # it was aggregated into.
    unresolved_items = _build_unresolved_items(requirement_coverage)
    requirement_coverage = _reconcile_requirement_coverage_text(requirement_coverage)
    findings = _reconcile_findings_with_package_evidence(
        findings, requirement_coverage, unusable_files=[], requirements=requirements,
    )
    findings = _deduplicate_findings(findings)

    if not coverage_complete:
        for row in requirement_coverage:
            row.pop("_is_qualification_gate", None)
        priority_actions = _select_priority_actions([], findings)
        partial_summary = _build_partial_audit_summary(
            requirement_coverage, unresolved_items, coverage_metadata, priority_actions,
            failed_chunks_count=len(failed_indices), ceiling_skipped_count=len(split["skipped_ranges"]),
        )
        return {
            "status": "incomplete",
            "message": _ALIGN_INCOMPLETE_MESSAGE,
            "reason": (
                "Proposal coverage did not reach the full-audit threshold "
                f"({percentage_covered}% analyzed, {len(failed_indices)} chunk(s) failed, "
                f"{len(split['skipped_ranges'])} section(s) beyond the analysis ceiling) -- "
                "no reliable score can be shown. The findings and requirement coverage "
                "established from the sections that WERE successfully analyzed are preserved below."
            ),
            "overall_score": None,
            "score_basis": None,
            "score_rationale": None,
            "recommendation": None,
            "executive_summary": None,
            "strengths": [],
            "findings": findings,
            "unresolved_items": unresolved_items,
            "mandatory_failures": [],
            "requirement_coverage": requirement_coverage,
            "next_steps": [],
            "priority_actions": priority_actions,
            "partial_summary": partial_summary,
            "coverage_metadata": coverage_metadata,
        }

    weight_by_req = {r.get("req_id"): r.get("weight") for r in requirements}
    for row in requirement_coverage:
        row["_weight"] = weight_by_req.get(row["req_id"])

    score_info = _compute_score(requirement_coverage)
    mandatory_failures = _extract_mandatory_failures(requirement_coverage)
    for row in requirement_coverage:
        row.pop("_weight", None)
        row.pop("_is_qualification_gate", None)
    recommendation, score_rationale = _derive_recommendation(score_info["overall_score"], mandatory_failures)
    priority_actions = _select_priority_actions(mandatory_failures, findings)

    narrative = _synthesize_narrative(
        bid_header, score_info["overall_score"], recommendation, mandatory_failures,
        requirement_coverage, findings, coverage_metadata,
    )
    if narrative is None:
        executive_summary = (
            "Narrative synthesis unavailable — the deterministic requirement-level audit "
            "below is valid and complete."
        )
        strengths, next_steps = [], []
    else:
        executive_summary = narrative.get("executive_summary", "")
        strengths = narrative.get("strengths", [])
        next_steps = narrative.get("next_steps", [])

    result = {
        "status": "complete",
        "overall_score": score_info["overall_score"],
        "score_basis": score_info["score_basis"],
        "score_rationale": score_rationale,
        "recommendation": recommendation,
        "executive_summary": executive_summary,
        "strengths": strengths,
        "findings": findings,
        "unresolved_items": unresolved_items,
        "mandatory_failures": mandatory_failures,
        "requirement_coverage": requirement_coverage,
        "next_steps": next_steps,
        "priority_actions": priority_actions,
        "coverage_metadata": coverage_metadata,
    }

    if not _validate_alignment_contract(result):
        return {
            "status": "incomplete",
            "message": _ALIGN_INCOMPLETE_MESSAGE,
            "reason": "Internal result failed contract validation.",
            "coverage_metadata": coverage_metadata,
        }

    return result


def analyze_proposal_alignment_package(
    package_files: list[dict],
    requirements: list[dict],
    rfp_text: str,
    bid_info: dict,
) -> dict:
    """Package-wide proposal alignment audit -- the multi-file Submission
    Package extension of analyze_proposal_alignment() above (which
    remains unchanged and is kept for any single-string caller).

    `package_files` must contain ONLY files the caller has already
    decided to INCLUDE (the user's include/exclude choice is applied by
    the caller -- see extractor.build_alignment_submission_package();
    duplicates and user-excluded files must never be passed here). Each
    entry: {"file_id", "filename", "package_path", "file_type", "text",
    "analyzable", "unusable_reason", "extraction_meta"}.

    An INCLUDED file with analyzable=False (failed extraction, or a
    format this version cannot parse) forces the whole audit incomplete
    -- the same fail-closed contract a failed/sampled-out chunk already
    has, just at the whole-file level (instruction 4: "Included
    substantive files that fail extraction do make the audit
    incomplete"). This function only decides completeness from what it's
    given; the caller decides inclusion.

    Chunking is per-file (XLSX/XLS split by worksheet via
    _split_structured_sheets_into_sections(), everything else via the
    existing prose splitter), merged/size-bounded per file (never across
    a file boundary), then the package-wide _ALIGN_MAX_CHUNKS ceiling is
    applied fairly across all included files via
    _allocate_package_chunk_budget() -- never a single global stride that
    could zero out a small file. Every downstream step (deterministic
    aggregation, scoring, mandatory-failure detection, fail-closed
    incomplete handling, narrative synthesis) reuses the exact same
    helpers as the single-document path unchanged.
    """
    unusable_files = [f for f in package_files if not f.get("analyzable")]
    analyzable_files = [f for f in package_files if f.get("analyzable") and (f.get("text") or "")]

    per_file_chars_total = {f["file_id"]: len(f["text"]) for f in analyzable_files}
    chars_total = sum(per_file_chars_total.values())

    per_file_bounded_sections = []
    for f in analyzable_files:
        if f.get("file_type") in ("xlsx", "xls"):
            raw = _split_structured_sheets_into_sections(f["text"])
        else:
            raw = _split_proposal_into_sections(f["text"])
        bounded = _merge_and_size_bound_sections(raw)
        per_file_bounded_sections.append((f, bounded))

    kept_chunks, skipped_sections = _allocate_package_chunk_budget(per_file_bounded_sections, _ALIGN_MAX_CHUNKS)

    if not kept_chunks:
        return {
            "status": "incomplete",
            "message": _ALIGN_INCOMPLETE_MESSAGE,
            "reason": "No proposal package text was available to analyze."
                      if not unusable_files else
                      f"{len(unusable_files)} included file(s) could not be analyzed and no other "
                      "included file provided any analyzable text.",
            "coverage_metadata": {
                "chars_total": chars_total, "chars_processed": 0, "percentage_covered": 0.0,
                "chunk_count": 0, "successful_chunks": 0, "failed_or_skipped_chunks": 0,
                "sections": [], "coverage_complete": False,
                "files": [
                    {"file_id": f["file_id"], "filename": f["filename"], "char_count": len(f.get("text") or ""),
                     "chars_processed": 0, "chunk_count": 0, "analyzable": f.get("analyzable"),
                     "unusable_reason": f.get("unusable_reason")}
                    for f in package_files
                ],
                "unusable_files": [
                    {"filename": f["filename"], "reason": f.get("unusable_reason")} for f in unusable_files
                ],
                "skipped_files": [],
                "sampled": False,
                "failed_chunk_diagnostics": [],
            },
            "unresolved_items": [],
            "priority_actions": [],
            "partial_summary": _build_partial_audit_summary(
                [], [], {"percentage_covered": 0.0, "successful_chunks": 0, "chunk_count": 0}, [],
                failed_chunks_count=0, ceiling_skipped_count=0,
            ),
        }

    bid_header = f"BID: {bid_info.get('title', '')} | CLIENT: {bid_info.get('client', '')}"

    req_lines = []
    for r in requirements:
        cat = r.get("category", "")
        rid = r.get("req_id", "")
        desc = (r.get("description") or "")[:120]
        wt = f"{r['weight'] * 100:.0f}%" if r.get("weight") else ""
        ev = (r.get("evidence") or "")[:60]
        req_lines.append(f"[{cat}] {rid} {wt}: {desc} | Evidence: {ev}")
    req_block = "\n".join(req_lines) if req_lines else "No requirements loaded."

    procurement_context = (rfp_text or "")[:_ALIGN_MAX_PROCUREMENT_CONTEXT_CHARS] or \
        "No canonical procurement intelligence has been extracted for this bid yet."

    chunk_outputs, failed_indices, failure_diagnostics = _process_chunks_concurrently(
        kept_chunks, bid_header, procurement_context, req_block
    )
    chunk_results = [chunk_outputs[c["index"]] for c in kept_chunks if c["index"] in chunk_outputs]
    successful_chunks = len(chunk_results)

    per_file_chars_processed: dict[str, list[tuple[int, int]]] = {fid: [] for fid in per_file_chars_total}
    for c in kept_chunks:
        if c["index"] not in failed_indices:
            per_file_chars_processed.setdefault(c["source_file_id"], []).append((c["start"], c["end"]))
    per_file_chars_processed_totals = {
        fid: _union_chars_covered(ranges) for fid, ranges in per_file_chars_processed.items()
    }

    chars_processed = sum(per_file_chars_processed_totals.values())
    percentage_covered = round(min(chars_processed / chars_total, 1.0) * 100, 1) if chars_total else 0.0

    coverage_complete = (
        percentage_covered >= _ALIGN_COVERAGE_COMPLETE_THRESHOLD
        and not failed_indices
        and not skipped_sections
        and not unusable_files
    )

    file_manifest_metrics = []
    for f in package_files:
        fid = f["file_id"]
        file_chunk_count = sum(1 for c in kept_chunks if c.get("source_file_id") == fid)
        file_manifest_metrics.append({
            "file_id": fid, "filename": f["filename"],
            "char_count": per_file_chars_total.get(fid, len(f.get("text") or "")),
            "chars_processed": per_file_chars_processed_totals.get(fid, 0),
            "chunk_count": file_chunk_count,
            "analyzable": bool(f.get("analyzable")),
            "unusable_reason": f.get("unusable_reason"),
        })

    # Explicit skipped-file visibility (never leave the user to infer
    # which file was omitted from a >ceiling package): a file that HAD
    # analyzable content but ended up with zero kept chunks after
    # _allocate_package_chunk_budget()'s package-wide ceiling was
    # applied -- e.g. the pathological "more analyzable files than the
    # ceiling allows" case -- is named explicitly here, surfaced by both
    # the CHECK UI and the exported PDF manifest.
    skipped_files = [
        {"file_id": m["file_id"], "filename": m["filename"]}
        for m in file_manifest_metrics
        if m["analyzable"] and m["char_count"] > 0 and m["chunk_count"] == 0
    ]

    ceiling_diagnostics = [
        {"filename": s.get("source_filename"), "section": s.get("heading"),
         "category": "beyond_analysis_ceiling", "attempts": 0}
        for s in skipped_sections
    ]
    failed_chunk_diagnostics = list(failure_diagnostics.values()) + ceiling_diagnostics
    unusable_files_meta = [
        {"filename": f["filename"], "reason": f.get("unusable_reason")} for f in unusable_files
    ]

    coverage_metadata = {
        "chars_total": chars_total,
        "chars_processed": chars_processed,
        "percentage_covered": percentage_covered,
        "chunk_count": len(kept_chunks) + len(skipped_sections),
        "successful_chunks": successful_chunks,
        "failed_or_skipped_chunks": len(failed_indices) + len(skipped_sections),
        "sections": [
            {"index": c["index"], "heading": c["heading"], "chars": c["end"] - c["start"],
             "filename": c.get("source_filename")}
            for c in kept_chunks
        ],
        "coverage_complete": coverage_complete,
        "files": file_manifest_metrics,
        "unusable_files": unusable_files_meta,
        "skipped_files": skipped_files,
        "sampled": bool(skipped_sections),
        "failed_chunk_diagnostics": failed_chunk_diagnostics,
    }

    if successful_chunks == 0:
        return {
            "status": "incomplete",
            "message": _ALIGN_INCOMPLETE_MESSAGE,
            "reason": "Every analyzed section failed to process (malformed or truncated model responses).",
            "coverage_metadata": coverage_metadata,
        }

    requirement_coverage = _aggregate_requirement_coverage(requirements, chunk_results, coverage_complete)
    findings = _aggregate_findings(chunk_results)
    # Package-level reconciliation (before _is_qualification_gate is
    # popped, so unresolved_items can still tell a mandatory/
    # qualification-gate requirement apart): neither a chunk-local
    # finding NOR a requirement_coverage row's own notes text is ever
    # allowed to contradict package-wide evidence confirmed elsewhere in
    # the submission package.
    unresolved_items = _build_unresolved_items(requirement_coverage)
    requirement_coverage = _reconcile_requirement_coverage_text(requirement_coverage)
    artifact_existence_map = _build_artifact_existence_map(package_files)
    findings = _reconcile_findings_with_package_evidence(
        findings, requirement_coverage, unusable_files_meta,
        requirements=requirements, artifact_existence_map=artifact_existence_map,
    )
    findings = _deduplicate_findings(findings)

    if not coverage_complete:
        for row in requirement_coverage:
            row.pop("_is_qualification_gate", None)
        reasons = []
        if unusable_files:
            reasons.append(
                f"{len(unusable_files)} included file(s) could not be analyzed "
                f"({', '.join(f['filename'] for f in unusable_files)})"
            )
        if failed_indices:
            reasons.append(f"{len(failed_indices)} chunk(s) failed to analyze")
        if skipped_sections:
            reasons.append(f"{len(skipped_sections)} section(s) beyond the package analysis ceiling")
        if skipped_files:
            reasons.append(
                f"{len(skipped_files)} included file(s) received NO analyzed sections at all due to the "
                f"package ceiling ({', '.join(f['filename'] for f in skipped_files)})"
            )
        reason_text = (
            f"Proposal package coverage did not reach the full-audit threshold ({percentage_covered}% analyzed)"
            + (f" -- {'; '.join(reasons)}" if reasons else "")
            + " -- no reliable score can be shown. The findings and requirement coverage established from "
              "the sections that WERE successfully analyzed are preserved below."
        )
        priority_actions = _select_priority_actions([], findings)
        partial_summary = _build_partial_audit_summary(
            requirement_coverage, unresolved_items, coverage_metadata, priority_actions,
            failed_chunks_count=len(failed_indices), ceiling_skipped_count=len(skipped_sections),
        )
        return {
            "status": "incomplete",
            "message": _ALIGN_INCOMPLETE_MESSAGE,
            "reason": reason_text,
            "overall_score": None,
            "score_basis": None,
            "score_rationale": None,
            "recommendation": None,
            "executive_summary": None,
            "strengths": [],
            "findings": findings,
            "unresolved_items": unresolved_items,
            "mandatory_failures": [],
            "requirement_coverage": requirement_coverage,
            "next_steps": [],
            "priority_actions": priority_actions,
            "partial_summary": partial_summary,
            "coverage_metadata": coverage_metadata,
        }

    weight_by_req = {r.get("req_id"): r.get("weight") for r in requirements}
    for row in requirement_coverage:
        row["_weight"] = weight_by_req.get(row["req_id"])

    score_info = _compute_score(requirement_coverage)
    mandatory_failures = _extract_mandatory_failures(requirement_coverage)
    for row in requirement_coverage:
        row.pop("_weight", None)
        row.pop("_is_qualification_gate", None)
    recommendation, score_rationale = _derive_recommendation(score_info["overall_score"], mandatory_failures)
    priority_actions = _select_priority_actions(mandatory_failures, findings)

    narrative = _synthesize_narrative(
        bid_header, score_info["overall_score"], recommendation, mandatory_failures,
        requirement_coverage, findings, coverage_metadata,
    )
    if narrative is None:
        executive_summary = (
            "Narrative synthesis unavailable — the deterministic requirement-level audit "
            "below is valid and complete."
        )
        strengths, next_steps = [], []
    else:
        executive_summary = narrative.get("executive_summary", "")
        strengths = narrative.get("strengths", [])
        next_steps = narrative.get("next_steps", [])

    result = {
        "status": "complete",
        "overall_score": score_info["overall_score"],
        "score_basis": score_info["score_basis"],
        "score_rationale": score_rationale,
        "recommendation": recommendation,
        "executive_summary": executive_summary,
        "strengths": strengths,
        "findings": findings,
        "unresolved_items": unresolved_items,
        "mandatory_failures": mandatory_failures,
        "requirement_coverage": requirement_coverage,
        "next_steps": next_steps,
        "priority_actions": priority_actions,
        "coverage_metadata": coverage_metadata,
    }

    if not _validate_alignment_contract(result):
        return {
            "status": "incomplete",
            "message": _ALIGN_INCOMPLETE_MESSAGE,
            "reason": "Internal result failed contract validation.",
            "coverage_metadata": coverage_metadata,
        }

    return result


# ── 10. Procurement Change Proposal (migration 010 governance foundation) ──
# Compares a buyer-issued update document against the CURRENT governed
# procurement truth and PROPOSES changes -- it never applies them. This is
# a PURE function: it makes zero database writes and never imports
# `database` or `tenancy` (structurally verified by
# tests/test_procurement_revision_governance.py, the same source-inspection
# pattern already used to guarantee pdf_alignment.py makes no LLM calls).
# A human reviews and approves every proposal via
# tenancy.record_change_review_decision_for_organization() before anything
# reaches canonical truth through
# tenancy.apply_procurement_update_review_for_organization().

_PROCUREMENT_CHANGE_SYSTEM = (
    "You are a senior procurement analyst comparing a buyer-issued update document "
    "against the CURRENT governed procurement truth for this opportunity. You "
    "identify what the update changes, clarifies, or confirms unchanged -- you do "
    "NOT decide what happens to canonical truth; a human reviews and approves every "
    "proposal you make before it can ever be applied. Cover at minimum: "
    "deadlines/dates, submission instructions, mandatory requirements, supplier "
    "qualification/eligibility, evaluation criteria and weights, pricing/commercial "
    "terms, scope/deliverables, contractual obligations, required forms/schedules, "
    "insurance, AI/data/privacy requirements, clarification answers, and "
    "administrative requirements. Never use unsupported external knowledge -- every "
    "proposal must be grounded in the supplied document text. This input may be one "
    "section/chunk of a larger buyer document -- the point where this excerpt ends "
    "is not evidence the document itself ends there; never propose a change based on "
    "an assumed truncation. Respond with valid JSON only."
)


def _procurement_change_prompt(bid_header: str, current_requirements_block: str, buyer_update_type: str,
                                chunk_text: str, chunk_label: str, filename: str) -> str:
    return f"""{bid_header}
Buyer update type: {buyer_update_type}

=== CURRENT GOVERNED PROCUREMENT TRUTH (requirements) ===
{current_requirements_block}

=== BUYER-ISSUED UPDATE DOCUMENT: {filename} -- {chunk_label} ===
{chunk_text}

Compare this document content against the current governed truth above. Return ONLY valid JSON:
{{
  "proposals": [
    {{
      "entity_type": "requirement|bid_brief_field",
      "entity_id": "<req_id, or bid_brief field name (opportunity_type|contract_term|procurement_model|commercial_structure|submission_requirements|key_dates)>",
      "change_type": "ADDED|MODIFIED|SUPERSEDED|REMOVED|CLARIFIED|UNCHANGED",
      "canonical_effect": "canonical_change|evidence_only",
      "previous_value": {{"description": "<current value verbatim from the truth block above, or null if ADDED>"}},
      "new_value": {{"description": "<proposed value>", "category": "<Mandatory|Rated|Financial|Supporting -- ONLY for a new requirement>", "weight": null}},
      "physical_source_ref": "<section/page reference from THIS document>",
      "extraction_evidence": {{"sources": [{{"page": <int or null>, "section": "<str or null>", "excerpt": "<short verbatim quote from THIS document>"}}]}}
    }}
  ]
}}
Rules:
- change_type UNCHANGED must have canonical_effect "evidence_only".
- change_type ADDED, MODIFIED, SUPERSEDED, or REMOVED must have canonical_effect "canonical_change".
- change_type CLARIFIED: set canonical_effect to "canonical_change" ONLY if this clarification changes how a requirement should be interpreted going forward; otherwise "evidence_only".
- Only propose a change when THIS document's text actually supports it -- never invent, never infer from outside knowledge.
- If this section contains nothing relevant to procurement truth, return an empty "proposals" array."""


def propose_procurement_changes(
    review_documents: list[dict],
    current_requirements: list[dict],
    bid_info: dict,
    buyer_update_type: str,
) -> list[dict]:
    """Deterministic-shape, LLM-assisted proposal generator for the
    Procurement Documents & Addenda governance workflow. PURE FUNCTION:
    makes zero database writes, never mutates requirements/bid_briefs/
    conflicts/procurement_revision -- it only ever RETURNS a list of
    proposal dicts shaped for procurement_changes rows. The caller
    (tenancy.propose_procurement_changes_for_organization) is responsible
    for persisting them as pending rows and for filling in
    target_requirement_id where a proposal's entity_id resolves to an
    existing requirement.

    `review_documents`: [{"document_id", "filename", "content_hash",
    "role", "text"}] -- every document in the review, not just the
    primary one.
    `current_requirements`: the FULL current governed compliance matrix
    (already lifecycle_status='active'-filtered by the caller) -- every
    proposal is compared against this, never against the original RFP
    alone, and never a truncated sample.

    Reuses the existing Alignment chunking helpers unchanged
    (_split_proposal_into_sections / _merge_and_size_bound_sections /
    _even_stride_sample_indices / _ALIGN_MAX_CHUNKS) so a large buyer
    document is chunked and bounded exactly like a proposal document is
    for Alignment -- no new chunking logic, no change to those functions.
    """
    bid_header = f"BID: {bid_info.get('title', '')} | CLIENT: {bid_info.get('client', '')}"
    req_lines = []
    for r in current_requirements:
        req_lines.append(
            f"[{r.get('category', '')}] {r.get('req_id', '')}: {(r.get('description') or '')[:200]} "
            f"(weight: {r.get('weight')}, rfso_ref: {r.get('rfso_ref')})"
        )
    current_requirements_block = "\n".join(req_lines) if req_lines else "No requirements currently governed."

    all_proposals: list[dict] = []
    for doc in review_documents:
        text = doc.get("text") or ""
        if not text.strip():
            continue
        sections = _merge_and_size_bound_sections(_split_proposal_into_sections(text))
        if not sections:
            continue
        if len(sections) > _ALIGN_MAX_CHUNKS:
            idx = _even_stride_sample_indices(len(sections), _ALIGN_MAX_CHUNKS)
            sections = [sections[i] for i in idx]

        for i, chunk in enumerate(sections):
            chunk_label = f"{chunk['heading']} (part {i + 1}/{len(sections)})"
            prompt = _procurement_change_prompt(
                bid_header, current_requirements_block, buyer_update_type,
                chunk["text"], chunk_label, doc.get("filename", ""),
            )
            try:
                raw = _call(_PROCUREMENT_CHANGE_SYSTEM, prompt, max_tokens=2500)
                parsed = _parse_json(raw)
            except Exception:
                continue
            if not isinstance(parsed, dict) or parsed.get("_truncated"):
                continue
            proposals = parsed.get("proposals")
            if not isinstance(proposals, list):
                continue

            for p in proposals:
                if not isinstance(p, dict):
                    continue
                p = dict(p)
                evidence = p.get("extraction_evidence") or {}
                sources = evidence.get("sources") if isinstance(evidence, dict) else None
                if isinstance(sources, list):
                    for s in sources:
                        if isinstance(s, dict):
                            s["document_id"] = doc.get("document_id")
                            s["document_hash"] = doc.get("content_hash")
                p["extraction_evidence"] = evidence
                p["source_document_id"] = doc.get("document_id")
                p["source_document_hash"] = doc.get("content_hash")
                if not p.get("physical_source_ref"):
                    p["physical_source_ref"] = f"{doc.get('filename', '')} — {chunk_label}"
                all_proposals.append(p)

    return all_proposals
