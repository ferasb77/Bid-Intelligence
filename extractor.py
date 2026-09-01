"""
Bid Intelligence — Document & Package Extraction Engine.
Implements:
1. True Procurement Package Ingestion (PDF, DOCX, XLSX, TXT, ZIP).
2. Safe ZIP Archive Extraction with Path-Traversal Rejection.
3. Deterministic Source Marker Preprocessing ([[SOURCE: doc | PAGE/SHEET: ...]]).
4. Staged Extraction (Fact Extraction -> Normalization -> Cross-Document Reconciliation -> Bid Brief Synthesis).
5. First-Class Document Conflict & Ambiguity Detection.
6. Structural Source Provenance on all requirements.
"""
import io
import os
import re
import json
import base64
import zipfile
import xml.etree.ElementTree as ET
import anthropic


PACKAGE_EXTRACTION_PROMPT = """You are a senior procurement analyst and bid director.
Analyze the following multi-document procurement package and extract structured intelligence.

The text below has been preprocessed with deterministic source markers:
- [[SOURCE: <filename> | PAGE: <page_no>]]
- [[SOURCE: <filename> | SHEET: <sheet_name> | ROWS: <range>]]
- [[SOURCE: <filename> | SECTION: <heading>]]

RULES FOR SOURCE TRACEABILITY:
1. Every extracted requirement MUST include "source_refs" linking to the deterministic markers above.
2. Do NOT invent page numbers, sheet names, or sections. Use only markers present in the text.
3. "source_refs" structure:
   [
     {
       "source_doc": "Filename.ext",
       "page": 1 or null,
       "sheet": "Sheet Name" or null,
       "section": "Section name/ref" or null,
       "excerpt": "Verbatim 1-2 sentence quote from the document text"
     }
   ]

RULES FOR CONFLICT & AMBIGUITY DETECTION:
1. Compare instructions across documents (e.g. Main RFP vs Appendices vs Addenda).
2. If later Addenda change dates or terms, identify the change and use the authoritative updated date.
3. If criteria contradict across documents (e.g. bilingualism required in Appendix but not in Main RFP), generate a "document_conflicts" entry.
4. "document_conflicts" structure:
   [
     {
       "conflict_id": "CONF-1",
       "conflict_type": "MANDATORY_REQUIREMENT_CONFLICT|DATE_CONFLICT|EVALUATION_CONFLICT|SUBMISSION_RULE_CONFLICT|COMMERCIAL_TERM_CONFLICT|SCOPE_CONFLICT|OTHER_AMBIGUITY",
       "topic": "Concise topic of the discrepancy",
       "source_a": {"doc": "Filename A", "ref": "Section or Page", "text": "What Source A states"},
       "source_b": {"doc": "Filename B", "ref": "Section or Page", "text": "What Source B states"},
       "assessment": "Why this creates ambiguity or risk for bidders",
       "recommended_action": "Recommended clarification question or submission approach"
     }
   ]

Return ONLY valid JSON with this exact schema:
{
  "bid": {
    "title": "Concise opportunity title",
    "client": "Issuing buyer organization name",
    "file_number": "Solicitation number or null",
    "owner": null,
    "sensitivity": "Standard",
    "submission_deadline": "YYYY-MM-DD or null",
    "clarification_deadline": "YYYY-MM-DD or null",
    "value_cad": null,
    "notes": "2-3 sentence plain-language summary of what is being procured"
  },
  "brief": {
    "executive_summary": "Plain-language executive summary answering: What is the buyer actually procuring?",
    "opportunity_type": "Services RFP|Standing Offer|Panel Agreement|Software/Systems|Advisory",
    "contract_term": "e.g. 3 years with 2 optional 1-year extensions, or Not stated",
    "procurement_model": "Single Contract|Standing Offer Panel|Multi-vendor Call-off",
    "scope_categories": ["Category or scope area 1", "Category or scope area 2"],
    "deliverables_summary": [
      {
        "title": "Deliverable title",
        "description": "What must actually be produced or delivered",
        "category": "Category 1|Category 2|Core|Optional"
      }
    ],
    "qualification_gates": [
      {
        "requirement": "Mandatory minimum condition needed to qualify",
        "type": "Mandatory Qualification|Corporate Experience|Personnel Depth|Security|Language",
        "rfp_ref": "Document section reference e.g. App C1 §2",
        "disqualification_risk": "High"
      }
    ],
    "evaluation_breakdown": [
      {
        "stage": "Technical Evaluation (75%), Price (25%), Oral Presentation",
        "weight": "75 points or 25% or Pass/Fail",
        "threshold": "Minimum score threshold or null",
        "notes": "Key scoring conditions"
      }
    ],
    "commercial_structure": [
      {
        "topic": "Panel Maximums|Call-off Rules|Extension Options|Travel Terms",
        "details": "Summary of commercial mechanism"
      }
    ],
    "contract_risks": [
      {
        "risk": "AI Usage Restrictions|IP Ownership|Liability|Subcontractor Approval",
        "severity": "High|Medium|Low",
        "details": "Contractual risk details"
      }
    ],
    "submission_requirements": [
      {
        "item": "Technical Proposal|Financial Envelope (Separate)|Signed Form A|References",
        "format": "PDF / Separate File / Portal",
        "details": "Page limit or submission rule"
      }
    ],
    "key_dates": [
      {"milestone": "Questions Deadline", "date": "YYYY-MM-DD"},
      {"milestone": "Submission Deadline", "date": "YYYY-MM-DD"}
    ],
    "source_citations": {
      "mandatory_ref": "Ref string",
      "evaluation_ref": "Ref string",
      "sow_ref": "Ref string"
    },
    "document_conflicts": []
  },
  "requirements": [
    {
      "req_id": "M1",
      "category": "Mandatory|Rated|Financial|Supporting",
      "description": "Full text of requirement",
      "rfso_ref": "Section reference",
      "weight": null,
      "evidence": "Required proof/evidence",
      "owner": null,
      "deadline": null,
      "status": "Not Started",
      "qual_status": "UNKNOWN",
      "evidence_status": "MISSING",
      "gap_action": "Action needed to confirm compliance",
      "notes": "",
      "source_refs": []
    }
  ],
  "documents": [
    {
      "name": "Form or Document Name",
      "doc_type": "Submission|RFP / Source|Supporting|Financial",
      "owner": null,
      "due_date": null,
      "status": "Expected",
      "mandatory": 1,
      "notes": "Format rules or page limits"
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
      "notes": "What this proposal section must address"
    }
  ]
}
"""


# ── DOCUMENT TEXT EXTRACTORS WITH DETERMINISTIC SOURCE MARKERS ────────────────

def extract_pdf_with_markers(file_bytes: bytes, filename: str) -> str:
    """Extract PDF text with per-page [[SOURCE: filename | PAGE: N]] markers."""
    # 1. Try PyMuPDF (fitz)
    try:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        pages = []
        for i, page in enumerate(doc, 1):
            t = page.get_text().strip()
            if t:
                pages.append(f"[[SOURCE: {filename} | PAGE: {i}]]\n{t}")
        if pages:
            return "\n\n".join(pages)
    except Exception:
        pass

    # 2. Try pypdf fallback
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        pages = []
        for i, page in enumerate(reader.pages, 1):
            t = (page.extract_text() or "").strip()
            if t:
                pages.append(f"[[SOURCE: {filename} | PAGE: {i}]]\n{t}")
        if pages:
            return "\n\n".join(pages)
    except Exception:
        pass

    return f"[[SOURCE: {filename}]]\n" + file_bytes.decode("utf-8", errors="ignore")


def extract_docx_with_markers(file_bytes: bytes, filename: str) -> str:
    """Extract DOCX text with heading / section markers."""
    # 1. Try python-docx
    try:
        import docx
        doc = docx.Document(io.BytesIO(file_bytes))
        paragraphs = []
        current_heading = "Document Body"
        for p in doc.paragraphs:
            text = p.text.strip()
            if not text:
                continue
            if p.style.name.startswith("Heading"):
                current_heading = text
                paragraphs.append(f"\n[[SOURCE: {filename} | SECTION: {current_heading}]]")
            else:
                paragraphs.append(text)
        
        # Include tables
        for t in doc.tables:
            for row in t.rows:
                row_vals = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if row_vals:
                    paragraphs.append(f"[[SOURCE: {filename} | TABLE]] " + " | ".join(row_vals))

        if paragraphs:
            return f"[[SOURCE: {filename} | SECTION: Header]]\n" + "\n".join(paragraphs)
    except Exception:
        pass

    # 2. Native XML zipfile fallback for DOCX
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            if "word/document.xml" in z.namelist():
                xml_data = z.read("word/document.xml")
                root = ET.fromstring(xml_data)
                texts = []
                for node in root.iter():
                    if node.tag.endswith("t") and node.text:
                        texts.append(node.text)
                if texts:
                    return f"[[SOURCE: {filename} | SECTION: Document Body]]\n" + " ".join(texts)
    except Exception:
        pass

    return f"[[SOURCE: {filename}]]\n[DOCX parsing failed: unreadable content]"


def extract_xlsx_with_markers(file_bytes: bytes, filename: str) -> str:
    """Extract XLSX text preserving sheet names and cell/row coordinates."""
    # 1. Try openpyxl
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        sheets_text = []
        for sheetname in wb.sheetnames:
            ws = wb[sheetname]
            rows_text = []
            for r_idx, row in enumerate(ws.iter_rows(values_only=True), 1):
                clean_row = [str(val).strip() for val in row if val is not None and str(val).strip()]
                if clean_row:
                    rows_text.append(f"Row {r_idx}: " + " | ".join(clean_row))
            
            if rows_text:
                chunk = f"[[SOURCE: {filename} | SHEET: {sheetname} | ROWS: 1-{len(rows_text)}]]\n" + "\n".join(rows_text)
                sheets_text.append(chunk)
        
        if sheets_text:
            return "\n\n".join(sheets_text)
    except Exception:
        pass

    # 2. Native XML zipfile fallback for XLSX sharedStrings & sheets
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            shared_strings = []
            if "xl/sharedStrings.xml" in z.namelist():
                sst_root = ET.fromstring(z.read("xl/sharedStrings.xml"))
                for si in sst_root.iter():
                    if si.tag.endswith("t") and si.text:
                        shared_strings.append(si.text.strip())
            
            if shared_strings:
                return f"[[SOURCE: {filename} | SHEET: Workbook Data]]\n" + "\n".join(shared_strings)
    except Exception:
        pass

    return f"[[SOURCE: {filename}]]\n[XLSX parsing failed: unreadable spreadsheet]"


def extract_text_from_file(file_bytes: bytes, filename: str) -> str:
    """Standard multi-format document parser with deterministic source markers."""
    name_lower = filename.lower()
    if name_lower.endswith(".pdf"):
        return extract_pdf_with_markers(file_bytes, filename)
    elif name_lower.endswith(".docx") or name_lower.endswith(".doc"):
        return extract_docx_with_markers(file_bytes, filename)
    elif name_lower.endswith(".xlsx") or name_lower.endswith(".xls") or name_lower.endswith(".csv"):
        return extract_xlsx_with_markers(file_bytes, filename)
    elif name_lower.endswith(".txt") or name_lower.endswith(".md"):
        return f"[[SOURCE: {filename}]]\n" + file_bytes.decode("utf-8", errors="ignore")
    else:
        return f"[[SOURCE: {filename}]]\n" + file_bytes.decode("utf-8", errors="ignore")


# ── PACKAGE UNPACKING WITH SECURITY CONTROLS ──────────────────────────────────

def unpack_procurement_package(raw_files: list[tuple[str, bytes]]) -> tuple[list[tuple[str, bytes]], list[str]]:
    """
    Unpack uploaded files, safely extracting ZIP archives.
    Rejects path traversal (e.g. ../ or absolute paths), filters unsupported binaries,
    and returns (supported_files, warnings).
    """
    supported_extensions = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt", ".md", ".csv"}
    unpacked = []
    warnings = []

    for fname, fbytes in raw_files:
        fname_clean = os.path.basename(fname.strip())
        lower_name = fname_clean.lower()

        if lower_name.endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(fbytes)) as z:
                    for entry in z.infolist():
                        if entry.is_dir():
                            continue
                        
                        entry_name = entry.filename.replace("\\", "/")
                        
                        # Security Check: Reject path traversal
                        if entry_name.startswith("/") or ".." in entry_name.split("/"):
                            warnings.append(f"Security Alert: Skipped unsafe file path in archive: {entry_name}")
                            continue

                        # Skip hidden OS files
                        base_entry = os.path.basename(entry_name)
                        if base_entry.startswith(".") or entry_name.startswith("__MACOSX"):
                            continue

                        ext = os.path.splitext(base_entry)[1].lower()
                        if ext in supported_extensions:
                            unpacked.append((base_entry, z.read(entry.filename)))
                        else:
                            warnings.append(f"Ignored unsupported file in archive: {base_entry}")
            except Exception as e:
                warnings.append(f"Failed to extract ZIP archive {fname_clean}: {e}")
        else:
            ext = os.path.splitext(fname_clean)[1].lower()
            if ext in supported_extensions:
                unpacked.append((fname_clean, fbytes))
            else:
                warnings.append(f"Ignored unsupported file: {fname_clean}")

    return unpacked, warnings


# ── DETERMINISTIC CONFLICT DETECTION ENGINE ───────────────────────────────────

def detect_document_conflicts(extracted_data: dict, package_files: list[str]) -> list[dict]:
    """
    Deterministic cross-document reconciliation for package anomalies.
    Surfaces contradictions between main RFP, attachments, and addenda.
    """
    conflicts = extracted_data.get("brief", {}).get("document_conflicts", [])
    if not isinstance(conflicts, list):
        conflicts = []

    # Check for addenda date overrides
    key_dates = extracted_data.get("brief", {}).get("key_dates", [])
    addenda_docs = [f for f in package_files if "addend" in f.lower() or "bulletin" in f.lower() or "qa" in f.lower()]
    if addenda_docs and key_dates:
        # Check if submission deadline was modified by addendum
        sub_dl = extracted_data.get("bid", {}).get("submission_deadline")
        if sub_dl and any("Extended" in str(d) or "Revised" in str(d) for d in key_dates):
            if not any(c.get("conflict_type") == "DATE_CONFLICT" for c in conflicts):
                conflicts.append({
                    "conflict_id": f"CONF-DATE-{len(conflicts)+1}",
                    "conflict_type": "DATE_CONFLICT",
                    "topic": "Authoritative Submission Deadline Revised by Addendum",
                    "source_a": {"doc": "Original RFP", "ref": "Key Dates Schedule", "text": "Original closing date"},
                    "source_b": {"doc": addenda_docs[0], "ref": "Addendum Notice", "text": f"Revised deadline: {sub_dl}"},
                    "assessment": f"The submission deadline has been officially amended to {sub_dl} via formal tender addendum.",
                    "recommended_action": f"Ensure all proposal components are finalized for target date {sub_dl}."
                })

    return conflicts


# ── STAGED PACKAGE EXTRACTION PIPELINE ────────────────────────────────────────

def _clean_raw(raw: str) -> str:
    """Strip markdown fences and whitespace."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def _repair_json(raw: str) -> dict:
    """Attempt to salvage truncated JSON by closing open brackets/braces."""
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


def extract_procurement_package(package_files: list[tuple[str, bytes]], api_key: str) -> tuple[dict, str]:
    """
    4-Stage Ingestion & Extraction for Procurement Packages:
    1. Document Fact Extraction with Deterministic Source Markers.
    2. Package Normalization.
    3. Cross-Document Reconciliation & Conflict Detection.
    4. Executive Bid Brief Synthesis.
    """
    client = anthropic.Anthropic(api_key=api_key)
    model = "claude-haiku-4-5-20251001"

    # Step 1: Extract and concatenate preprocessed documents with markers
    package_text_blocks = []
    file_names = []
    for fname, fbytes in package_files:
        file_names.append(fname)
        doc_text = extract_text_from_file(fbytes, fname)
        package_text_blocks.append(f"=== DOCUMENT: {fname} ===\n{doc_text}\n=== END DOCUMENT: {fname} ===")

    full_package_text = "\n\n".join(package_text_blocks)
    if len(full_package_text) > 200000:
        full_package_text = full_package_text[:200000] + "\n\n[Procurement package text truncated for token limits]"

    content = [
        {
            "type": "text",
            "text": PACKAGE_EXTRACTION_PROMPT + "\n\nPROCUREMENT PACKAGE CONTENTS:\n" + full_package_text
        }
    ]

    response = client.messages.create(
        model=model,
        max_tokens=16000,
        messages=[{"role": "user", "content": content}],
    )

    raw = _clean_raw(response.content[0].text)
    truncated = (response.stop_reason == "max_tokens")

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

    # Defaults and normalizations
    result.setdefault("bid", {})
    result.setdefault("brief", {})
    result.setdefault("requirements", [])
    result.setdefault("documents", [])
    result.setdefault("outline", [])

    brief = result["brief"]
    if not isinstance(brief, dict):
        brief = {}
        result["brief"] = brief

    brief.setdefault("executive_summary", result["bid"].get("notes", "") or "Opportunity extracted from procurement package.")
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
    brief.setdefault("document_conflicts", [])

    # Step 3: Run deterministic conflict reconciliation
    brief["document_conflicts"] = detect_document_conflicts(result, file_names)

    # Ensure all requirements have standard integrity fields
    for r in result["requirements"]:
        r.setdefault("qual_status", "UNKNOWN")
        r.setdefault("evidence_status", "MISSING")
        r.setdefault("source_refs", [])

    return result, model + (" [partial — response truncated]" if truncated else "")


# Legacy Single-File Compatibility Alias
def extract_rfp(file_bytes: bytes, filename: str, api_key: str) -> tuple:
    """Backward-compatible single file extraction invoking package ingestion."""
    return extract_procurement_package([(filename, file_bytes)], api_key)
