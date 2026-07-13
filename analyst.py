"""
Phase 2 — AI Compliance Analyst
Four capabilities:
  1. compliance_review   — draft section vs requirements gap analysis
  2. missing_evidence    — scan matrix for at-risk items
  3. clarification_qs    — generate strategic clarification questions
  4. bid_no_bid          — scored bid/no-bid recommendation
"""
import json, re
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
    Handles: markdown fences, trailing commentary, truncated output.
    """
    import re as _re

    # 1. Strip markdown fences
    raw = _re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = _re.sub(r"\s*```$", "", raw).strip()

    # 2. Direct parse (clean response)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 3. Extract first complete JSON object or array by bracket matching
    def extract_first(text, open_ch, close_ch):
        start = text.find(open_ch)
        if start == -1:
            return None
        depth, in_str, esc = 0, False, False
        for i, ch in enumerate(text[start:], start):
            if esc:           esc = False; continue
            if ch == "\\":  esc = True;  continue
            if ch == "\"" and not esc:
                in_str = not in_str; continue
            if in_str:        continue
            if ch == open_ch:  depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:    return json.loads(candidate)
                    except: return None
        return None

    for open_ch, close_ch in [('{', '}'), ('[', ']')]:
        result = extract_first(raw, open_ch, close_ch)
        if result is not None:
            return result

    # 4. Repair truncated JSON: walk backward from end to find last valid object close
    # Try progressively shorter slices ending at } or ]
    for end_char in ('}', ']'):
        pos = len(raw) - 1
        while pos >= 0:
            pos = raw.rfind(end_char, 0, pos + 1)
            if pos == -1:
                break
            candidate = raw[:pos + 1]
            # Count opens vs closes — only try if balanced-ish
            for oc, cc in [('{', '}'), ('[', ']')]:
                opens = candidate.count(oc) - candidate.count(cc)
                candidate += cc * max(opens, 0)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pos -= 1

    # 5. Nuclear option: find last complete inner object and wrap it
    # Walk back finding any parseable sub-object
    inner = _re.findall(r'\{[^{}]+\}', raw)
    if inner:
        try:
            # Reassemble as a questions array from whatever objects we got
            objects = [json.loads(o) for o in inner if _re.search(r'"question"', o)]
            if objects:
                return {"questions": objects, "submission_notes": "",
                        "critical_count": 0, "deadline_note": ""}
        except Exception:
            pass

    raise ValueError(
        f"Could not parse model response as JSON after all repair attempts.\n"
        f"First 300 chars: {raw[:300]}"
    )


# ── 1. Compliance Review ──────────────────────────────────────────────────────
COMPLIANCE_SYSTEM = """You are a senior proposal reviewer. Your job is to compare a draft proposal 
section against the RFP requirements it is meant to address and identify gaps, weaknesses, and 
missing evidence. Be specific, direct, and actionable. Do not be encouraging — identify real problems."""

def compliance_review(draft_text: str, requirements: list[dict]) -> dict:
    """
    Compare a draft proposal section against the compliance matrix.
    Returns structured feedback with addressed/weak/missing items.
    """
    reqs_text = "\n".join(
        f"- [{r.get('req_id','')}] ({r.get('category','')}) {r.get('description','')} "
        f"| Evidence required: {r.get('evidence') or 'not specified'}"
        for r in requirements
    )

    prompt = f"""REQUIREMENTS FROM RFP:
{reqs_text}

DRAFT PROPOSAL TEXT:
{draft_text}

Analyse how well the draft addresses each requirement. Return ONLY valid JSON:
{{
  "overall_score": <integer 0-100>,
  "summary": "<2-3 sentence overall assessment>",
  "addressed": [
    {{"req_id": "M1", "finding": "how it is addressed"}}
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


# ── 2. Missing Evidence Detection ─────────────────────────────────────────────
EVIDENCE_SYSTEM = """You are a bid compliance controller. You scan compliance matrices for risk. 
Be blunt about what is at risk. Prioritise mandatory items above all else."""

def missing_evidence(requirements: list[dict], bid_info: dict) -> dict:
    """
    Scan the full compliance matrix and surface at-risk items.
    Returns prioritised risk list with recommended actions.
    """
    sub_deadline = bid_info.get("submission_deadline", "unknown")
    clar_deadline = bid_info.get("clarification_deadline", "unknown")

    reqs_text = "\n".join(
        f"[{r.get('req_id','')}] {r.get('category','')} | "
        f"Status: {r.get('status','')} | "
        f"Owner: {r.get('owner') or 'UNASSIGNED'} | "
        f"Deadline: {r.get('deadline') or 'not set'} | "
        f"Evidence: {r.get('evidence') or 'not specified'} | "
        f"Description: {r.get('description','')[:120]}"
        for r in requirements
    )

    prompt = f"""BID: {bid_info.get('title','')} — {bid_info.get('client','')}
Submission deadline: {sub_deadline}
Clarification deadline: {clar_deadline}

COMPLIANCE MATRIX:
{reqs_text}

Identify all at-risk items. Return ONLY valid JSON:
{{
  "risk_level": "High|Medium|Low",
  "summary": "<blunt 2-sentence assessment of where this bid stands>",
  "critical": [
    {{
      "req_id": "M1",
      "reason": "why this is critical",
      "action": "specific action needed",
      "by_when": "suggested internal deadline"
    }}
  ],
  "at_risk": [
    {{
      "req_id": "R3",
      "reason": "why at risk",
      "action": "action needed"
    }}
  ],
  "unassigned": ["list of req_ids with no owner"],
  "recommendation": "<single most important thing to do today>"
}}"""

    raw = _call(EVIDENCE_SYSTEM, prompt, max_tokens=2048)
    return _parse_json(raw)


# ── 3. Clarification Question Generator ───────────────────────────────────────
CLARIFICATION_SYSTEM = """You are a senior bid strategist with deep experience in 
Canadian federal procurement and professional-services consulting RFPs.

Your job is to generate clarification questions that are:
1. STRATEGICALLY CRITICAL — could change the bid/no-bid decision or prevent disqualification
2. ELIGIBILITY-CLARIFYING — resolve ambiguities about who can bid and how
3. SCOPE-DEFINING — nail down volume, geography, language, subcontracting rules
4. COMMERCIALLY PROTECTIVE — confirm pricing assumptions and change-order rules
5. COMPETITIVELY NEUTRAL — never reveal the bidder's weaknesses or strategy

Questions must be:
- Phrased as a neutral request for clarification, not an argument
- Specific enough to get a definitive yes/no or quantified answer
- Grounded in an actual ambiguity in the RFP — never ask what's already answered
- Submitted before the enquiry deadline (answers go to ALL bidders, so phrase carefully)

For each question, provide a private rationale (internal use only) explaining the 
strategic importance and what answer Phoenix needs to proceed confidently."""

def generate_clarification_questions(bid_info: dict, requirements: list[dict],
                                      rfp_context: str = "") -> dict:
    """Generate ranked, submission-ready clarification questions from the RFP."""

    reqs_text = "\n".join(
        f"[{r.get('req_id','')}] ({r.get('category','')} "
        f"{f'{r["weight"]*100:.0f}%' if r.get('weight') else ''}) "
        f"{r.get('description','')[:180]} | "
        f"Evidence: {r.get('evidence','') or 'not specified'}"
        for r in requirements
    )

    sub_deadline  = bid_info.get("submission_deadline","")
    clar_deadline = bid_info.get("clarification_deadline","")
    client        = bid_info.get("client","")
    title         = bid_info.get("title","")
    notes         = bid_info.get("notes","")[:600]

    prompt = f"""PROCUREMENT DETAILS:
Client: {client}
Opportunity: {title}
Enquiry deadline: {clar_deadline} (14:00 Ottawa local time)
Submission deadline: {sub_deadline}
Summary: {notes}

FULL REQUIREMENT REGISTER:
{reqs_text}

{f'ADDITIONAL RFP CONTEXT (read carefully for ambiguities):\n{rfp_context[:4000]}' if rfp_context else ''}

KNOWN RISK AREAS TO PROBE (generate questions targeting these if applicable):
- Coach location: RFP says work at "contractor's facilities in Canada" — does this bar non-Canadian coaches?
- Subcontracting: Are international coaches acceptable as subcontractors under Appendix B Part B?
- Language: Is French bilingual capacity mandatory or an asset only?
- Volume: No guaranteed call-up volume — what is the estimated number of engagements per year?
- Coach substitution: 5-business-day rule — what happens if no suitable substitute exists?
- Optional services: Are Hogan or other psychometric assessments acceptable under §4.6 V?
- Insurance: Must $2M coverage be in force at submission, or only at SOA execution?
- References: Can internal CDA-AMC references be pre-approved before the enquiry deadline?
- AI disclosure: Does administrative AI use (scheduling, internal tools) require disclosure?
- PCHO clause: Which other organizations may access this SOA and what is the estimated scope?
- Pricing: Is HST applicable to services provided by a non-Canadian supplier?
- Evaluation: Will short-listed bidders receive individual evaluation scores before presentations?

Generate 10-12 clarification questions. Be concise — keep each field under 200 characters. Return ONLY valid JSON with no trailing commas:
{{
  "questions": [
    {{
      "id": "Q1",
      "question": "Complete question text referencing the RFSO section. Under 200 chars.",
      "rationale": "Internal rationale. Under 150 chars.",
      "priority": "Critical",
      "risk_if_unanswered": "Risk. Under 100 chars.",
      "relates_to": ["M1"],
      "category": "Eligibility"
    }}
  ],
  "submission_notes": "Brief submission advice. Under 150 chars.",
  "critical_count": 0,
  "deadline_note": "Deadline reminder. Under 80 chars."
}}

Order: Critical first, then High, then Medium.
IMPORTANT: Keep ALL string values concise. Do not let any single string exceed 250 characters."""

    raw = _call(CLARIFICATION_SYSTEM, prompt, max_tokens=4096)
    result = _parse_json(raw)
    # Ensure all questions have required keys
    for q in result.get("questions", []):
        q.setdefault("id", "")
        q.setdefault("question", "")
        q.setdefault("rationale", "")
        q.setdefault("priority", "Medium")
        q.setdefault("risk_if_unanswered", "")
        q.setdefault("relates_to", [])
        q.setdefault("category", "Other")
    return result


# ── 4. Bid / No-Bid Scoring ───────────────────────────────────────────────────
BID_NOBID_SYSTEM = """You are a senior partner at a consulting firm evaluating whether to pursue 
a bid. You are experienced, unsentimental, and focused on winning probability and resource efficiency. 
Base your assessment on the evidence provided. Do not be encouraging if the case is weak."""

def bid_no_bid_score(bid_info: dict, requirements: list[dict],
                     firm_context: str = "") -> dict:
    """
    Produce a structured bid/no-bid recommendation with scored dimensions.
    firm_context: optional free-text about the bidding firm's capabilities.
    """
    reqs_summary = "\n".join(
        f"- [{r.get('req_id','')}] ({r.get('category','')}) "
        f"Weight: {str(round(r['weight']*100)) + '%' if r.get('weight') else 'n/a'} | "
        f"{r.get('description','')[:120]}"
        for r in requirements
    )

    prompt = f"""BID UNDER EVALUATION:
Title: {bid_info.get('title','')}
Client: {bid_info.get('client','')}
Submission deadline: {bid_info.get('submission_deadline','unknown')}
Summary: {bid_info.get('notes','')[:500]}

REQUIREMENTS AND EVALUATION CRITERIA:
{reqs_summary}

BIDDER CONTEXT:
{firm_context[:1000] if firm_context else 'Not provided — assess based on requirements alone.'}

Score this bid across five dimensions (0-10 each) and give a final recommendation.
Return ONLY valid JSON:
{{
  "recommendation": "BID|NO BID|CONDITIONAL BID",
  "confidence": "High|Medium|Low",
  "overall_score": <0-100>,
  "summary": "<3-4 sentence executive summary of the recommendation>",
  "dimensions": {{
    "strategic_fit": {{
      "score": <0-10>,
      "rationale": "why this score",
      "evidence": "what supports this"
    }},
    "capability_fit": {{
      "score": <0-10>,
      "rationale": "assessment of ability to deliver",
      "evidence": "gaps or strengths"
    }},
    "competitive_position": {{
      "score": <0-10>,
      "rationale": "likely position vs competitors",
      "evidence": "differentiators or weaknesses"
    }},
    "resource_availability": {{
      "score": <0-10>,
      "rationale": "can the team be staffed",
      "evidence": "deadline and effort considerations"
    }},
    "risk": {{
      "score": <0-10>,
      "rationale": "compliance and delivery risk",
      "evidence": "specific risk factors"
    }}
  }},
  "conditions": ["<condition if CONDITIONAL BID, else empty list>"],
  "win_themes": ["<strongest differentiator 1>", "<strongest differentiator 2>"],
  "red_flags": ["<critical risk or weakness 1>", "<risk 2>"]
}}"""

    raw = _call(BID_NOBID_SYSTEM, prompt, max_tokens=2048)
    return _parse_json(raw)


# ── 5. Past Proposal Analyzer ─────────────────────────────────────────────────
PROPOSAL_ANALYZER_SYSTEM = """You are an expert proposal analyst reviewing past submitted proposals 
to extract reusable content for a consulting firm's knowledge library. Extract structured, 
verbatim-quality content that can be directly reused or adapted in future proposals."""

def analyze_past_proposal(text: str, bid_context: dict) -> dict:
    """
    Extract reusable content blocks from a past proposal document.
    Returns structured library items ready to store.
    """
    prompt = f"""CURRENT BID CONTEXT:
Client: {bid_context.get('client','')}
Title: {bid_context.get('title','')}
Notes: {bid_context.get('notes','')[:300]}

PAST PROPOSAL TEXT (first 12,000 chars):
{text[:12000]}

Extract all reusable content. Return ONLY valid JSON:
{{
  "proposal_summary": {{
    "client": "client name from the past proposal",
    "year": "year submitted if visible",
    "service_type": "type of service proposed",
    "outcome": "Won/Lost/Unknown"
  }},
  "library_items": [
    {{
      "title": "Short descriptive title",
      "category": "one of: Coaching Philosophy|Methodology|Case Study|Team Qualification|IDEA Statement|ESG Statement|Reconciliation Statement|Executive Summary|Sector Experience|Reference|CV Summary|Pricing Structure|Other",
      "content": "The actual reusable text content — verbatim or lightly edited for reuse. Be thorough.",
      "relevance_to_current": "How this content maps to the current bid requirements",
      "tags": "comma-separated tags e.g. coaching,executive,healthcare,NFP"
    }}
  ],
  "coaches_found": [
    {{
      "name": "Coach name",
      "credentials": "Listed credentials",
      "icf_level": "ICF level if mentioned e.g. PCC, MCC, ACC",
      "sectors": "sectors mentioned",
      "languages": "languages mentioned",
      "cv_summary": "Brief CV summary from the proposal"
    }}
  ],
  "gaps": ["Content that the current bid needs but this proposal doesn't provide"]
}}

Extract as many library_items as possible — be thorough. Minimum 5 items if content allows."""

    raw = _call(PROPOSAL_ANALYZER_SYSTEM, prompt, max_tokens=4096)
    return _parse_json(raw)


# ── 6. Proposal Section Drafter ───────────────────────────────────────────────
DRAFTER_SYSTEM = """You are a senior proposal writer for a consulting firm. 
Write proposal sections that are specific, evidence-based, and directly responsive 
to the evaluation criteria. Never use generic filler language. Every sentence 
should either demonstrate capability or directly address a stated requirement. 
Write in first-person plural (we/our) from the bidding firm's perspective."""

def draft_proposal_section(section_title: str, requirements: list,
                            library_items: list, bid_context: dict,
                            firm_context: str = "", word_limit: int = 500) -> dict:
    """Draft a proposal section using requirements and library content."""

    reqs_text = "\n".join(
        f"- [{r.get('req_id','')}] {r.get('description','')} "
        f"(Evidence required: {r.get('evidence') or 'not specified'})"
        for r in requirements
    )
    lib_text = "\n\n".join(
        f"[{item.get('category','')}] {item.get('title','')}\n{item.get('content','')[:600]}"
        for item in library_items[:6]
    ) if library_items else "No library content available — draft from scratch."

    prompt = f"""PROPOSAL SECTION TO DRAFT: {section_title}
TARGET WORD COUNT: approximately {word_limit} words

BID CONTEXT:
Client: {bid_context.get('client','')}
Opportunity: {bid_context.get('title','')}
Client context: {bid_context.get('notes','')[:300]}

REQUIREMENTS THIS SECTION MUST ADDRESS:
{reqs_text}

AVAILABLE REUSABLE CONTENT FROM PAST PROPOSALS:
{lib_text}

FIRM CONTEXT:
{firm_context[:800] if firm_context else 'Phoenix Consulting International — authorised Hogan distributor for GCC, executive coaching and leadership development specialists.'}

Write the section now. Return ONLY valid JSON:
{{
  "section_title": "{section_title}",
  "draft": "The full drafted section text with proper paragraphs. Use professional proposal language.",
  "requirements_addressed": ["req_id list of requirements explicitly addressed"],
  "requirements_missing": ["req_ids not yet addressed — need more content"],
  "word_count": <approximate word count>,
  "strength_rating": <1-5 where 5 is publication-ready>,
  "improvement_notes": "What would make this stronger — specific additions or evidence needed"
}}"""

    raw = _call(DRAFTER_SYSTEM, prompt, max_tokens=3000)
    return _parse_json(raw)


# ── 7. Submission Readiness Check ─────────────────────────────────────────────
READINESS_SYSTEM = """You are a bid compliance controller doing a final pre-submission 
check. You are looking for anything that could cause disqualification, score reduction, 
or last-minute problems. Be precise and unsparing."""

def submission_readiness_check(bid: dict, requirements: list,
                                documents: list, outline: list) -> dict:
    """Final gate check before submission."""

    mandatory_status = [
        f"[{r.get('req_id','')}] {r.get('description','')[:80]} → {r.get('status','')}"
        for r in requirements if r.get('category') == 'Mandatory'
    ]
    doc_status = [
        f"{d.get('name','')} → {d.get('status','')}"
        for d in documents if d.get('doc_type') == 'Submission'
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

PROPOSAL OUTLINE SECTION STATUS:
{chr(10).join(section_status) or 'None recorded'}

Perform a final pre-submission readiness check. Return ONLY valid JSON:
{{
  "go_no_go": "GO|NO GO|CONDITIONAL GO",
  "readiness_score": <0-100>,
  "summary": "2-3 sentence assessment",
  "blockers": [
    {{
      "item": "what is blocked",
      "severity": "Critical|High|Medium",
      "action": "exact action needed",
      "by_when": "suggested deadline"
    }}
  ],
  "warnings": ["non-critical issues to watch"],
  "submission_checklist": [
    {{"item": "checklist item", "status": "Ready|Pending|Blocked"}}
  ],
  "recommended_submission_time": "suggested time to submit (before hard deadline)"
}}"""

    raw = _call(READINESS_SYSTEM, prompt, max_tokens=2048)
    return _parse_json(raw)
