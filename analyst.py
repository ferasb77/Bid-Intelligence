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
import json
import re
import anthropic
from config import get_api_key


def _call(system: str, user: str, max_tokens: int = 2048) -> str:
    client = anthropic.Anthropic(api_key=get_api_key())
    response = client.messages.create(
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
                     firm_context: str = "") -> dict:
    """Produce a structured pursuit recommendation across five strategic dimensions."""
    reqs_summary = "\n".join(
        f"- [{r.get('req_id','')}] ({r.get('category','')}) Qual: {r.get('qual_status','UNKNOWN')} | "
        f"Weight: {str(round(r['weight']*100)) + '%' if r.get('weight') else 'n/a'} | "
        f"{r.get('description','')[:120]}"
        for r in requirements
    )

    prompt = f"""OPPORTUNITY UNDER EVALUATION:
Title: {bid_info.get('title','')}
Client: {bid_info.get('client','')}
Submission deadline: {bid_info.get('submission_deadline','unknown')}
Summary: {bid_info.get('notes','')[:500]}

REQUIREMENTS & QUALIFICATION GATES:
{reqs_summary}

BIDDER PROFILE & CAPABILITIES:
{firm_context[:1000] if firm_context else 'Assess feasibility based on requirement standards.'}

Score this opportunity across five strategic dimensions (0-10 each) and provide an actionable pursuit recommendation.
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
def analyze_proposal_alignment(
    proposal_text: str,
    requirements: list[dict],
    rfp_text: str,
    bid_info: dict,
) -> dict:
    """
    Two-call comprehensive alignment analysis scoring the proposal against RFP documents.
    Call 1: Overall score, findings by procurement stage, strengths, and next steps.
    Call 2: Per-requirement coverage breakdown.
    """
    rfp_snippet = (rfp_text or "")[:4000]
    proposal_snip = (proposal_text or "")[:8000]

    req_lines = []
    for r in requirements:
        cat = r.get("category", "")
        rid = r.get("req_id", "")
        desc = (r.get("description") or "")[:120]
        wt = f"{r['weight']*100:.0f}%" if r.get("weight") else ""
        ev = (r.get("evidence") or "")[:60]
        req_lines.append(f"[{cat}] {rid} {wt}: {desc} | Evidence: {ev}")
    req_block = "\n".join(req_lines) if req_lines else "No requirements loaded."

    bid_header = f"BID: {bid_info.get('title','')} | CLIENT: {bid_info.get('client','')}"

    SYSTEM = (
        "You are a senior proposal reviewer with expertise in competitive procurement. "
        "Assess how well the proposal satisfies the specific tender requirements. "
        "Derive ALL conclusions strictly from the tender documents and proposal text provided. "
        "Classify findings into accurate procurement stages: Proposal Submission, Negotiation / Shortlist, "
        "Contract Execution, or Contractual Obligation. Respond with valid JSON only."
    )

    prompt1 = f"""{bid_header}

=== TENDER DOCUMENTS ===
{rfp_snippet}

=== COMPLIANCE MATRIX ===
{req_block}

=== PROPOSAL TEXT ===
{proposal_snip}

Review the proposal against the tender requirements. Score 0-100 based on proposal submission criteria.
Return ONLY valid JSON:
{{
  "overall_score": <0-100>,
  "score_rationale": "<max 100 chars>",
  "recommendation": "SUBMIT AS-IS|REVISE BEFORE SUBMITTING|MAJOR REVISION NEEDED",
  "executive_summary": "<max 200 chars>",
  "strengths": ["<strength 1>", "<strength 2>", "<strength 3>"],
  "findings": [
    {{
      "severity": "Critical|High|Medium|Low",
      "stage": "Proposal Submission|Negotiation / Shortlist|Contract Execution|Contractual Obligation",
      "category": "<category>",
      "req_id": "<req_id or null>",
      "title": "<finding title>",
      "issue": "<concise explanation of gap>",
      "recommendation": "<actionable fix>",
      "proposal_location": "<section or N/A>",
      "effort": "Minor edit|Moderate rewrite|Major addition|Post-submission action"
    }}
  ],
  "next_steps": [
    {{
      "priority": 1,
      "action": "<action description>",
      "rationale": "<why it matters>",
      "when": "Before submission|If shortlisted|Before contract execution|Upon contract award"
    }}
  ]
}}"""

    raw1 = _call(SYSTEM, prompt1, max_tokens=3500)
    result = _parse_json(raw1)
    if not isinstance(result, dict):
        result = {"overall_score": 50, "recommendation": "REVISE BEFORE SUBMITTING", "findings": [], "strengths": [], "next_steps": []}

    # Call 2: Requirement Coverage
    cov_lines = [f"{r.get('req_id','')} [{r.get('category','')}]: {(r.get('description') or '')[:80]}" for r in requirements]
    cov_block = "\n".join(cov_lines) if cov_lines else "No requirements."

    prompt2 = f"""{bid_header}

=== REQUIREMENTS TO ASSESS ===
{cov_block}

=== PROPOSAL TEXT ===
{proposal_snip}

Assess per-requirement coverage. Return ONLY valid JSON:
{{
  "requirement_coverage": [
    {{
      "req_id": "<req_id>",
      "category": "<category>",
      "description": "<concise description>",
      "coverage": "Fully Addressed|Partially Addressed|Not Addressed|Cannot Assess",
      "confidence": "High|Medium|Low",
      "notes": "<one sentence note>"
    }}
  ]
}}"""

    try:
        raw2 = _call(SYSTEM, prompt2, max_tokens=3000)
        coverage_result = _parse_json(raw2)
        if isinstance(coverage_result, dict):
            result["requirement_coverage"] = coverage_result.get("requirement_coverage", [])
        else:
            result["requirement_coverage"] = []
    except Exception:
        result["requirement_coverage"] = []

    return result
