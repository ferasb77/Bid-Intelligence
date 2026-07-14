import json, re, base64
import fitz  # pymupdf
import anthropic

EXTRACTION_PROMPT = """You are an expert bid analyst. Read the RFP/tender document and extract structured information.

Return ONLY valid JSON — no markdown, no explanation, no code fences. Use exactly this schema:

{
  "bid": {
    "title": "short opportunity title",
    "client": "issuing organisation name",
    "file_number": "reference/file number if present, else null",
    "owner": null,
    "sensitivity": "Standard",
    "submission_deadline": "YYYY-MM-DD or null",
    "clarification_deadline": "YYYY-MM-DD or null",
    "value_cad": null,
    "notes": "2-3 sentence summary of what is being procured"
  },
  "requirements": [
    {
      "req_id": "M1",
      "category": "Mandatory",
      "description": "Full description of the requirement",
      "rfso_ref": "section reference e.g. §3.1",
      "weight": null,
      "evidence": "what must be submitted as evidence",
      "owner": null,
      "deadline": null,
      "status": "Not Started",
      "notes": ""
    }
  ],
  "documents": [
    {
      "name": "document name",
      "doc_type": "Submission",
      "owner": null,
      "due_date": null,
      "status": "Not Started",
      "notes": ""
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
      "notes": "what this section must address"
    }
  ]
}

Rules:
- requirements: extract EVERY mandatory requirement (category="Mandatory"), every rated/scored criterion (category="Rated", include weight as decimal e.g. 0.40 for 40%), every financial requirement (category="Financial"), and key supporting documents (category="Supporting").
- For rated requirements include the evaluation weight as a decimal (e.g. 0.10 for 10%).
- documents: list every document that must be submitted as part of the proposal package.
- outline: suggest a logical proposal section structure based on what the RFP requires.
- Use ISO date format YYYY-MM-DD for all dates. If a year is not stated assume 2026.
- Keep all text values concise (under 200 characters) to avoid truncation.
- If a field cannot be determined, use null.
- Keep ALL string values concise — under 250 characters each.
- Output ONLY the JSON object. No markdown, no explanation, nothing else."""


def _clean_raw(raw: str) -> str:
    """Strip markdown fences and whitespace."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def _repair_json(raw: str) -> dict:
    """
    Attempt to salvage truncated JSON by closing any open structures.
    Works for the common case where the response was cut mid-array/object.
    """
    # Count open brackets
    opens = raw.count('{') - raw.count('}')
    arr_opens = raw.count('[') - raw.count(']')

    # Close any open string — find last complete value boundary
    # Trim to last comma or closing bracket that makes a clean break
    trimmed = raw.rstrip()

    # Remove trailing incomplete key-value pair (e.g. `"key": "partial val`)
    trimmed = re.sub(r',?\s*"[^"]*"\s*:\s*"[^"]*$', '', trimmed)
    trimmed = re.sub(r',?\s*"[^"]*"\s*:\s*$', '', trimmed)
    trimmed = re.sub(r',\s*$', '', trimmed)

    # Close open arrays and objects
    trimmed += ']' * max(arr_opens, 0)
    trimmed += '}' * max(opens, 0)

    return json.loads(trimmed)


def extract_rfp(file_bytes: bytes, filename: str, api_key: str) -> tuple:
    client = anthropic.Anthropic(api_key=api_key)
    model  = "claude-haiku-4-5-20251001"

    if filename.lower().endswith(".pdf"):
        b64 = base64.standard_b64encode(file_bytes).decode("utf-8")
        content = [
            {
                "type": "document",
                "source": {
                    "type":       "base64",
                    "media_type": "application/pdf",
                    "data":       b64,
                },
            },
            {
                "type": "text",
                "text": EXTRACTION_PROMPT,
            },
        ]
    else:
        text = file_bytes.decode("utf-8", errors="ignore")
        if len(text) > 180000:
            text = text[:180000] + "\n\n[Document truncated]"
        content = [{"type": "text",
                    "text": EXTRACTION_PROMPT + "\n\nDOCUMENT:\n" + text}]

    response = client.messages.create(
        model=model,
        max_tokens=16000,         # large RFPs need more tokens
        messages=[{"role": "user", "content": content}],
    )

    raw = _clean_raw(response.content[0].text)
    stop_reason = response.stop_reason
    truncated   = (stop_reason == "max_tokens")

    # Use the same robust parser as analyst.py
    try:
        from analyst import _parse_json
        result = _parse_json(raw)
    except Exception:
        # Absolute fallback — try the old repair function
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = _repair_json(raw)

    # Ensure all top-level keys exist
    result.setdefault("bid",          {})
    result.setdefault("requirements", [])
    result.setdefault("documents",    [])
    result.setdefault("outline",      [])

    return result, model + (" [partial — response truncated]" if truncated else "")
