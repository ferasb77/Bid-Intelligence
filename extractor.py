import json
import re
import base64
import anthropic

EXTRACTION_PROMPT = """You are a senior bid strategist and expert procurement analyst.
Read the RFP / tender document and extract structured intelligence.

Return ONLY valid JSON — no markdown fences, no explanatory text, no preamble. Use exactly this schema:

{
  "bid": {
    "title": "Concise opportunity title",
    "client": "Issuing organization / buyer name",
    "file_number": "Reference or solicitation number if present, else null",
    "owner": null,
    "sensitivity": "Standard",
    "submission_deadline": "YYYY-MM-DD or null",
    "clarification_deadline": "YYYY-MM-DD or null",
    "value_cad": null,
    "notes": "2-3 sentence plain-language summary of what is being procured"
  },
  "brief": {
    "executive_summary": "Plain-language executive summary answering: What is the buyer actually procuring? Avoid excessive procurement jargon.",
    "opportunity_type": "e.g. Services RFP, Framework Agreement, Software/Systems, Advisory, Standing Offer",
    "contract_term": "e.g. 3 years with 2 optional 1-year extensions, or Not stated",
    "procurement_model": "e.g. Single Contract, Framework Agreement, Standing Offer, Panel, Multi-vendor Call-off",
    "scope_categories": [
      "Major scope or solution area 1",
      "Major scope or solution area 2"
    ],
    "deliverables_summary": [
      {
        "title": "Deliverable title",
        "description": "What must actually be produced or delivered (e.g. workshops, reports, software, advisory sessions)",
        "category": "Core Service|Optional Service|Reporting|Call-off Mechanic"
      }
    ],
    "qualification_gates": [
      {
        "requirement": "Specific mandatory condition or minimum experience needed to qualify",
        "type": "Mandatory Qualification|Eligibility|Certification|Security|Language|Insurance",
        "rfp_ref": "Section reference e.g. §3.1 or M1",
        "disqualification_risk": "High|Medium"
      }
    ],
    "evaluation_breakdown": [
      {
        "stage": "e.g. Mandatory Compliance Gate, Technical Evaluation (70%), Financial Evaluation (30%), Oral Presentation",
        "weight": "e.g. 70% or Pass/Fail",
        "threshold": "Minimum threshold if stated e.g. 75% on technical, or null",
        "notes": "Key scoring conditions"
      }
    ],
    "commercial_structure": [
      {
        "topic": "e.g. Pricing Model, Volume Guarantees, Call-up Rules, Extension Options, Travel Terms",
        "details": "Summary of commercial mechanism"
      }
    ],
    "contract_risks": [
      {
        "risk": "e.g. IP Ownership, Data Residency, AI Use Restrictions, Subcontracting Limits, Liability Cap, Payment Terms",
        "severity": "High|Medium|Low",
        "details": "What the bidder should watch out for before committing resources"
      }
    ],
    "submission_requirements": [
      {
        "item": "e.g. Technical Proposal, Financial Proposal (Separate Envelope), Signatures, Form A, CVs, References",
        "format": "e.g. Searchable PDF, Separate File, Portal Upload",
        "details": "Page limits, signature rules, or file naming requirements"
      }
    ],
    "key_dates": [
      {
        "milestone": "e.g. Clarification Deadline, Addenda Cut-off, Submission Deadline, Award Date",
        "date": "YYYY-MM-DD or date description"
      }
    ],
    "source_citations": {
      "mandatory_ref": "Section reference for mandatory criteria",
      "evaluation_ref": "Section reference for scoring",
      "sow_ref": "Section reference for scope of work"
    }
  },
  "requirements": [
    {
      "req_id": "M1",
      "category": "Mandatory|Rated|Financial|Supporting",
      "description": "Full description of the requirement",
      "rfso_ref": "Section reference e.g. §3.1",
      "weight": null,
      "evidence": "What must be submitted as evidence",
      "owner": null,
      "deadline": null,
      "status": "Not Started",
      "qual_status": "UNKNOWN",
      "gap_action": "Initial action needed to confirm compliance or prepare evidence",
      "notes": ""
    }
  ],
  "documents": [
    {
      "name": "Document or Form Name",
      "doc_type": "Submission|RFP / Source|Supporting|Financial",
      "owner": null,
      "due_date": null,
      "status": "Expected",
      "mandatory": 1,
      "notes": "Submission rules or format instructions"
    }
  ],
  "outline": [
    {
      "sort_order": 0,
      "section_num": "1",
      "title": "Section title",
      "owner": null,
      "word_limit": null,
      "status": "Not Started",
      "notes": "What this proposal section must address based on the RFP"
    }
  ]
}

Extraction Rules:
1. Distinguish MANDATORY qualification conditions (pass/fail, disqualification risk) from RATED criteria (scored points).
2. Distinguish CONTRACT deliverables (what the client is buying) from SUBMISSION documents (what must be handed in with the proposal).
3. Do not invent details not present in the document; use "Not stated" or "Unknown" where appropriate.
4. Extract every mandatory requirement into the "requirements" list with category="Mandatory" and qual_status="UNKNOWN".
5. Extract rated criteria with category="Rated" and include decimal weight (e.g. 0.40 for 40%) where available.
6. Keep individual string values concise and crisp (under 250 characters each) to prevent response truncation.
7. Return ONLY the JSON object."""


def _clean_raw(raw: str) -> str:
    """Strip markdown fences and whitespace."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def _repair_json(raw: str) -> dict:
    """
    Attempt to salvage truncated JSON by closing any open structures.
    Works for the common case where the response was cut mid-array/object.
    """
    try:
        from analyst import _parse_json
        res = _parse_json(raw)
        if isinstance(res, dict):
            return res
    except Exception:
        pass

    opens = raw.count('{') - raw.count('}')
    arr_opens = raw.count('[') - raw.count(']')

    trimmed = raw.rstrip()
    trimmed = re.sub(r',?\s*"[^"]*"\s*:\s*"[^"]*$', '', trimmed)
    trimmed = re.sub(r',?\s*"[^"]*"\s*:\s*$', '', trimmed)
    trimmed = re.sub(r',?\s*"[^"]*$', '', trimmed)
    trimmed = re.sub(r',\s*$', '', trimmed)

    trimmed += ']' * max(arr_opens, 0)
    trimmed += '}' * max(opens, 0)

    try:
        return json.loads(trimmed)
    except Exception:
        return {}


def extract_text_from_file(file_bytes: bytes, filename: str) -> str:
    """Extract raw text from PDF, DOCX, TXT with multi-library fallback."""
    name_lower = filename.lower()
    if name_lower.endswith(".pdf"):
        # 1. Try PyMuPDF (fitz)
        try:
            import fitz
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            return "\n".join(page.get_text() for page in doc)
        except Exception:
            pass

        # 2. Try pypdf
        try:
            import pypdf
            import io
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            pages_text = []
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    pages_text.append(t)
            return "\n".join(pages_text)
        except Exception:
            pass

    return file_bytes.decode("utf-8", errors="ignore")


def extract_rfp(file_bytes: bytes, filename: str, api_key: str) -> tuple:
    client = anthropic.Anthropic(api_key=api_key)
    model = "claude-haiku-4-5-20251001"

    if filename.lower().endswith(".pdf"):
        b64 = base64.standard_b64encode(file_bytes).decode("utf-8")
        content = [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": b64,
                },
            },
            {
                "type": "text",
                "text": EXTRACTION_PROMPT,
            },
        ]
    else:
        text = extract_text_from_file(file_bytes, filename)
        if len(text) > 180000:
            text = text[:180000] + "\n\n[Document truncated]"
        content = [{"type": "text", "text": EXTRACTION_PROMPT + "\n\nDOCUMENT:\n" + text}]

    response = client.messages.create(
        model=model,
        max_tokens=16000,
        messages=[{"role": "user", "content": content}],
    )

    raw = _clean_raw(response.content[0].text)
    stop_reason = response.stop_reason
    truncated = (stop_reason == "max_tokens")

    try:
        from analyst import _parse_json
        result = _parse_json(raw)
    except Exception:
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = _repair_json(raw)

    if not isinstance(result, dict):
        result = {}

    # Ensure all top-level keys exist with sensible defaults
    result.setdefault("bid", {})
    result.setdefault("brief", {})
    result.setdefault("requirements", [])
    result.setdefault("documents", [])
    result.setdefault("outline", [])

    # Ensure structured brief has all sub-fields
    brief = result["brief"]
    if not isinstance(brief, dict):
        brief = {}
        result["brief"] = brief

    brief.setdefault("executive_summary", result["bid"].get("notes", "") or "Opportunity extracted from tender document.")
    brief.setdefault("opportunity_type", "Competitive Tender")
    brief.setdefault("contract_term", "Not stated")
    brief.setdefault("procurement_model", "Standard Procurement")
    brief.setdefault("scope_categories", [])
    brief.setdefault("deliverables_summary", [])
    brief.setdefault("qualification_gates", [])
    brief.setdefault("evaluation_breakdown", [])
    brief.setdefault("commercial_structure", [])
    brief.setdefault("contract_risks", [])
    brief.setdefault("submission_requirements", [])
    brief.setdefault("key_dates", [])
    brief.setdefault("source_citations", {})

    return result, model + (" [partial — response truncated]" if truncated else "")
