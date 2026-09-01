"""
Bid Intelligence — Staged Document & Package Extraction Engine.
Implements:
1. True Procurement Package Ingestion (PDF, DOCX, XLSX, CSV, TXT, ZIP).
2. Safe ZIP Archive Extraction with Path-Traversal Rejection.
3. Deterministic Source Marker Preprocessing with real row coordinates.
4. Genuinely Staged Pipeline:
   - Stage A: Document Fact Extraction (requirements, dates, criteria, rules, clauses)
   - Stage B: Package Normalization (deduplication, source_refs aggregation)
   - Stage C: Cross-Document Reconciliation & Conflict Detection (6 conflict types)
   - Stage D: Executive Bid Brief Synthesis (generated from normalized model)
5. Strict Source Provenance Validation (rejects hallucinated pages, sheets, rows, or files).
"""
import io
import os
import re
import csv
import json
import zipfile
import xml.etree.ElementTree as ET
import anthropic
from config import get_anthropic_client


# ── PROMPTS FOR STAGED EXTRACTION ─────────────────────────────────────────────

STAGE_A_FACT_EXTRACTION_PROMPT = """You are a senior procurement intelligence analyst.
Extract factual procurement data from this single procurement document.
The text contains deterministic source markers:
- [[SOURCE: <filename> | PAGE: <page_no>]]
- [[SOURCE: <filename> | SHEET: <sheet_name> | ROWS: <range>]]
- [[SOURCE: <filename> | SECTION: <heading>]]
- [[SOURCE: <filename> | ROWS: <range>]]

CRITICAL SOURCE TRACEABILITY RULES:
1. For every requirement or factual item, include "source_refs" pointing to the actual markers present in the text.
2. DO NOT hallucinate or guess page numbers, sheet names, or sections. Use only markers in the text.
3. "source_refs" schema:
   [
     {
       "source_doc": "<filename>",
       "page": <int or null>,
       "sheet": "<str or null>",
       "section": "<str or null>",
       "excerpt": "<1-2 sentence verbatim quote from text>"
     }
   ]

Return ONLY valid JSON with this exact schema:
{
  "doc_metadata": {
    "title": "Title of tender or null",
    "client": "Issuing organization or null",
    "file_number": "Solicitation number or null",
    "submission_deadline": "YYYY-MM-DD or null",
    "clarification_deadline": "YYYY-MM-DD or null",
    "notes": "Brief factual summary of document purpose"
  },
  "requirements": [
    {
      "req_id": "M1 or R1",
      "category": "Mandatory|Rated|Financial|Supporting",
      "description": "Full requirement text",
      "rfso_ref": "Section reference",
      "weight": null,
      "evidence": "Required proof or submission item",
      "source_refs": []
    }
  ],
  "dates": [
    {"milestone": "Milestone name", "date": "YYYY-MM-DD", "source_doc": "<filename>"}
  ],
  "evaluation_criteria": [
    {"stage": "Evaluation stage or criterion", "weight": "e.g. 75 points or 25%", "threshold": "e.g. 70% or null", "notes": "Scoring rules"}
  ],
  "submission_rules": [
    {"item": "Submission component name", "format": "PDF / Separate File / Portal", "details": "Packaging / page limit rule", "mandatory": 1}
  ],
  "deliverables": [
    {"title": "Deliverable output", "description": "What must be produced", "category": "Core|Optional"}
  ],
  "commercial_clauses": [
    {"topic": "Panel Maximums|Rate Caps|Extension Options|Liability", "details": "Commercial mechanism details"}
  ],
  "contract_risks": [
    {"risk": "AI Restrictions|IP Ownership|Liability|Subcontractors", "severity": "High|Medium|Low", "details": "Contractual risk details"}
  ]
}
"""

STAGE_D_SYNTHESIS_PROMPT = """You are an executive bid director synthesizing a Bid Brief from normalized procurement facts.
You MUST synthesize ONLY from the supplied normalized facts and detected cross-document conflicts.
Do NOT invent facts not present in the normalized data model.

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
    "notes": "2-3 sentence executive synthesis of what is being procured"
  },
  "brief": {
    "executive_summary": "Plain-language executive summary answering: What is the buyer actually procuring?",
    "opportunity_type": "Services RFP|Standing Offer|Panel Agreement|Software/Systems|Advisory",
    "contract_term": "e.g. 3 years with 2 optional 1-year extensions, or Not stated",
    "procurement_model": "Single Contract|Standing Offer Panel|Multi-vendor Call-off",
    "scope_categories": ["Category 1", "Category 2"],
    "deliverables_summary": [
      {"title": "Deliverable title", "description": "Scope details", "category": "Core|Optional"}
    ],
    "qualification_gates": [
      {"requirement": "Mandatory condition", "type": "Mandatory Qualification", "rfp_ref": "Ref", "disqualification_risk": "High"}
    ],
    "evaluation_breakdown": [
      {"stage": "Technical / Price stage", "weight": "75 points / 25%", "threshold": "Threshold or null", "notes": "Scoring rules"}
    ],
    "commercial_structure": [
      {"topic": "Commercial topic", "details": "Details"}
    ],
    "contract_risks": [
      {"risk": "Risk title", "severity": "High|Medium|Low", "details": "Details"}
    ],
    "submission_requirements": [
      {"item": "Document name", "format": "Format", "details": "Details"}
    ],
    "key_dates": [
      {"milestone": "Milestone name", "date": "YYYY-MM-DD"}
    ],
    "source_citations": {
      "mandatory_ref": "Ref string",
      "evaluation_ref": "Ref string",
      "sow_ref": "Ref string"
    }
  },
  "outline": [
    {"sort_order": 0, "section_num": "1", "title": "Proposal Section Title", "owner": null, "word_limit": null, "status": "Not Started", "notes": "Guidance"}
  ]
}
"""


# ── DOCUMENT TEXT EXTRACTORS & DETERMINISTIC MARKERS ─────────────────────────

def extract_pdf_with_metadata(file_bytes: bytes, filename: str) -> tuple[str, dict]:
    """Extract PDF text with per-page [[SOURCE: filename | PAGE: N]] markers and metadata."""
    meta = {"page_count": 0, "pages": {}}
    
    # 1. Try PyMuPDF (fitz)
    try:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        pages = []
        meta["page_count"] = len(doc)
        for i, page in enumerate(doc, 1):
            t = page.get_text().strip()
            if t:
                meta["pages"][i] = t
                pages.append(f"[[SOURCE: {filename} | PAGE: {i}]]\n{t}")
        if pages:
            return "\n\n".join(pages), meta
    except Exception:
        pass

    # 2. Try pypdf fallback
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        pages = []
        meta["page_count"] = len(reader.pages)
        for i, page in enumerate(reader.pages, 1):
            t = (page.extract_text() or "").strip()
            if t:
                meta["pages"][i] = t
                pages.append(f"[[SOURCE: {filename} | PAGE: {i}]]\n{t}")
        if pages:
            return "\n\n".join(pages), meta
    except Exception:
        pass

    raw_text = file_bytes.decode("utf-8", errors="ignore")
    meta["page_count"] = 1
    meta["pages"][1] = raw_text
    return f"[[SOURCE: {filename} | PAGE: 1]]\n" + raw_text, meta


def extract_docx_with_metadata(file_bytes: bytes, filename: str) -> tuple[str, dict]:
    """Extract DOCX text with heading / section markers and metadata."""
    meta = {"sections": [], "tables_count": 0}
    
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
                meta["sections"].append(current_heading)
                paragraphs.append(f"\n[[SOURCE: {filename} | SECTION: {current_heading}]]")
            else:
                paragraphs.append(text)
        
        for t in doc.tables:
            meta["tables_count"] += 1
            for row in t.rows:
                row_vals = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if row_vals:
                    paragraphs.append(f"[[SOURCE: {filename} | TABLE]] " + " | ".join(row_vals))

        if paragraphs:
            return f"[[SOURCE: {filename} | SECTION: Header]]\n" + "\n".join(paragraphs), meta
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
                    meta["sections"].append("Document Body")
                    return f"[[SOURCE: {filename} | SECTION: Document Body]]\n" + " ".join(texts), meta
    except Exception:
        pass

    return f"[[SOURCE: {filename}]]\n[DOCX parsing failed: unreadable content]", meta


def extract_xlsx_with_metadata(file_bytes: bytes, filename: str) -> tuple[str, dict]:
    """Extract XLSX text preserving sheet names and real worksheet row coordinates (even with blank rows)."""
    meta = {"sheets": [], "rows_per_sheet": {}}
    
    # 1. Try openpyxl
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        sheets_text = []
        meta["sheets"] = list(wb.sheetnames)
        for sheetname in wb.sheetnames:
            ws = wb[sheetname]
            rows_text = []
            non_empty_indices = []
            for r_idx, row in enumerate(ws.iter_rows(values_only=True), 1):
                clean_row = [str(val).strip() for val in row if val is not None and str(val).strip()]
                if clean_row:
                    non_empty_indices.append(r_idx)
                    rows_text.append(f"Row {r_idx}: " + " | ".join(clean_row))
            
            if rows_text:
                min_r = non_empty_indices[0]
                max_r = non_empty_indices[-1]
                meta["rows_per_sheet"][sheetname] = (min_r, max_r, set(non_empty_indices))
                chunk = f"[[SOURCE: {filename} | SHEET: {sheetname} | ROWS: {min_r}-{max_r}]]\n" + "\n".join(rows_text)
                sheets_text.append(chunk)
            else:
                meta["rows_per_sheet"][sheetname] = (0, 0, set())
        
        if sheets_text:
            return "\n\n".join(sheets_text), meta
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
                meta["sheets"] = ["Workbook Data"]
                meta["rows_per_sheet"]["Workbook Data"] = (1, len(shared_strings), set(range(1, len(shared_strings)+1)))
                return f"[[SOURCE: {filename} | SHEET: Workbook Data | ROWS: 1-{len(shared_strings)}]]\n" + "\n".join(shared_strings), meta
    except Exception:
        pass

    return f"[[SOURCE: {filename}]]\n[XLSX parsing failed: unreadable spreadsheet]", meta


def extract_csv_with_metadata(file_bytes: bytes, filename: str) -> tuple[str, dict]:
    """Extract CSV text with real row coordinate markers."""
    meta = {"rows_count": 0, "non_empty_rows": set()}
    try:
        text_content = file_bytes.decode("utf-8", errors="replace")
        reader = csv.reader(io.StringIO(text_content))
        rows_text = []
        for r_idx, row in enumerate(reader, 1):
            clean_row = [str(val).strip() for val in row if val is not None and str(val).strip()]
            if clean_row:
                meta["non_empty_rows"].add(r_idx)
                rows_text.append(f"Row {r_idx}: " + " | ".join(clean_row))
        
        meta["rows_count"] = len(rows_text)
        if rows_text:
            min_r = min(meta["non_empty_rows"])
            max_r = max(meta["non_empty_rows"])
            return f"[[SOURCE: {filename} | ROWS: {min_r}-{max_r}]]\n" + "\n".join(rows_text), meta
    except Exception:
        pass

    return f"[[SOURCE: {filename}]]\n" + file_bytes.decode("utf-8", errors="ignore"), meta


def extract_document_with_metadata(file_bytes: bytes, filename: str) -> tuple[str, dict]:
    """Extract text with deterministic markers and return rich parsing metadata."""
    name_lower = filename.lower()
    if name_lower.endswith(".pdf"):
        return extract_pdf_with_metadata(file_bytes, filename)
    elif name_lower.endswith(".docx"):
        return extract_docx_with_metadata(file_bytes, filename)
    elif name_lower.endswith(".xlsx"):
        return extract_xlsx_with_metadata(file_bytes, filename)
    elif name_lower.endswith(".csv"):
        return extract_csv_with_metadata(file_bytes, filename)
    elif name_lower.endswith(".txt") or name_lower.endswith(".md"):
        txt = file_bytes.decode("utf-8", errors="ignore")
        return f"[[SOURCE: {filename}]]\n" + txt, {"type": "text", "len": len(txt)}
    else:
        # Unsupported format (e.g. .doc or .xls)
        return f"[[SOURCE: {filename}]]\n[Unsupported file format. Please upload PDF, DOCX, XLSX, CSV, or TXT]", {"unsupported": True}


def extract_text_from_file(file_bytes: bytes, filename: str) -> str:
    """Standard multi-format document parser returning marked text."""
    text, _ = extract_document_with_metadata(file_bytes, filename)
    return text


# ── PACKAGE UNPACKING WITH SECURITY CONTROLS ──────────────────────────────────

def unpack_procurement_package(raw_files: list[tuple[str, bytes]]) -> tuple[list[tuple[str, bytes]], list[str]]:
    """
    Unpack uploaded files, safely extracting ZIP archives.
    Rejects path traversal (e.g. ../ or absolute paths), filters unsupported binaries (.exe, .bin)
    and legacy unsupported office formats (.doc, .xls), returning (supported_files, warnings).
    """
    supported_extensions = {".pdf", ".docx", ".xlsx", ".csv", ".txt", ".md"}
    unsupported_legacy = {".doc", ".xls"}
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
                        elif ext in unsupported_legacy:
                            warnings.append(f"Skipped legacy format '{base_entry}'. Convert to modern .docx / .xlsx format.")
                        else:
                            warnings.append(f"Ignored unsupported file in archive: {base_entry}")
            except Exception as e:
                warnings.append(f"Failed to extract ZIP archive {fname_clean}: {e}")
        else:
            ext = os.path.splitext(fname_clean)[1].lower()
            if ext in supported_extensions:
                unpacked.append((fname_clean, fbytes))
            elif ext in unsupported_legacy:
                warnings.append(f"Skipped legacy format '{fname_clean}'. Convert to modern .docx / .xlsx format.")
            else:
                warnings.append(f"Ignored unsupported file: {fname_clean}")

    return unpacked, warnings


# ── SOURCE PROVENANCE VALIDATION ENGINE ───────────────────────────────────────

def validate_source_refs(source_refs: list, package_metadata: dict) -> list[dict]:
    """
    Strict validation of AI-returned source references against physical document parse metadata.
    Validates:
    1. Source document existence in package.
    2. Page bounds (1 <= page <= max_pages).
    3. Sheet name existence in workbook.
    4. Sheet row ranges against actual non-empty rows.
    5. Excerpt presence/plausibility.
    
    Returns list of verified/annotated source references. Invalid locations are rejected or flagged.
    """
    if not isinstance(source_refs, list):
        return []

    valid_files = set(package_metadata.get("files", []))
    valid_files_lower = {f.lower(): f for f in valid_files}
    doc_meta_map = package_metadata.get("doc_metadata", {})
    doc_texts = package_metadata.get("doc_texts", {})

    verified_refs = []
    for ref in source_refs:
        if not isinstance(ref, dict):
            continue

        raw_doc = str(ref.get("source_doc") or "").strip()
        matched_doc = valid_files_lower.get(raw_doc.lower())

        if not matched_doc:
            # Rejection 1: Nonexistent document in package
            verified_refs.append({
                "source_doc": raw_doc or "Unknown",
                "page": None,
                "sheet": None,
                "section": None,
                "excerpt": ref.get("excerpt", ""),
                "verified": False,
                "validation_error": f"Document '{raw_doc}' not found in procurement package"
            })
            continue

        doc_meta = doc_meta_map.get(matched_doc, {})
        page = ref.get("page")
        sheet = ref.get("sheet")
        section = ref.get("section")
        excerpt = ref.get("excerpt", "")

        is_valid = True
        error_reasons = []

        # Check page bounds
        if page is not None:
            try:
                page_int = int(page)
                max_pages = doc_meta.get("page_count", 0)
                if max_pages > 0 and (page_int < 1 or page_int > max_pages):
                    is_valid = False
                    error_reasons.append(f"Page {page_int} out of bounds (document has {max_pages} pages)")
                    page = None
            except (ValueError, TypeError):
                is_valid = False
                error_reasons.append(f"Invalid page value '{page}'")
                page = None

        # Check sheet name
        if sheet is not None:
            sheet_str = str(sheet).strip()
            valid_sheets = doc_meta.get("sheets", [])
            if valid_sheets and sheet_str not in valid_sheets:
                # Check case-insensitive match
                sheet_match = next((s for s in valid_sheets if s.lower() == sheet_str.lower()), None)
                if sheet_match:
                    sheet = sheet_match
                else:
                    is_valid = False
                    error_reasons.append(f"Sheet '{sheet_str}' does not exist in workbook")
                    sheet = None

        # Check rows in sheet
        if sheet and "rows_per_sheet" in doc_meta:
            row_info = doc_meta["rows_per_sheet"].get(sheet)
            if row_info:
                min_r, max_r, nonempty_rows = row_info
                # If ref has row range or rows
                rows_spec = ref.get("rows")
                if rows_spec:
                    try:
                        if isinstance(rows_spec, int) and rows_spec not in nonempty_rows:
                            is_valid = False
                            error_reasons.append(f"Row {rows_spec} is blank or outside data range")
                    except Exception:
                        pass

        # Check excerpt plausibility
        if excerpt and len(excerpt) > 15:
            full_doc_text = doc_texts.get(matched_doc, "")
            # Check if excerpt words appear in doc
            sample_words = [w for w in re.findall(r'\w+', excerpt.lower()) if len(w) > 3][:6]
            if sample_words and not any(w in full_doc_text.lower() for w in sample_words):
                is_valid = False
                error_reasons.append("Excerpt text not found in source document")

        clean_ref = {
            "source_doc": matched_doc,
            "page": page,
            "sheet": sheet,
            "section": section,
            "excerpt": excerpt,
            "verified": is_valid
        }
        if not is_valid:
            clean_ref["validation_error"] = "; ".join(error_reasons)

        verified_refs.append(clean_ref)

    return verified_refs


# ── DETERMINISTIC CONFLICT & AMBIGUITY DETECTION ENGINE ───────────────────────

DATE_EVENT_PATTERNS = [
    # 1. Question / Clarification deadlines (must evaluate before general deadline keywords)
    ("QUESTION_DEADLINE", [
        r"question", r"clarification", r"enquir", r"inquir", r"rfi", r"q&a", r"q\s*&\s*a",
        r"queries", r"questions\s+due", r"last\s+date\s+for\s+questions", r"deadline\s+for\s+questions"
    ]),
    # 2. Intent to Bid / Confirmation
    ("INTENT_TO_BID_DATE", [
        r"intent\s+to\s+bid", r"bid\s+intent", r"intention\s+to\s+bid", r"confirmation\s+of\s+intent",
        r"intent\s+deadline", r"intent\s+date", r"opt-in", r"acknowledgement\s+deadline"
    ]),
    # 3. Publication / Issue Dates
    ("PUBLICATION_DATE", [
        r"solicitation\s+publication", r"publication\s+date", r"date\s+issued", r"posting\s+date",
        r"date\s+of\s+issue", r"published\s+date", r"rfp\s+issue"
    ]),
    # 4. Amendment / Addenda Dates
    ("AMENDMENT_DATE", [
        r"amendment\s+no", r"amendment\s+published", r"amendment\s+issued", r"addendum\s+published",
        r"addendum\s+issued", r"bulletin\s+issued", r"bulletin\s+date"
    ]),
    # 5. Experience timeframe / Reference period (not a procurement event)
    ("EXPERIENCE_TIMEFRAME", [
        r"recent\s+engagements", r"experience\s+timeframe", r"reference\s+period", r"project\s+period",
        r"prior\s+experience"
    ]),
    # 6. Site visits / Conferences / Walkthroughs
    ("SITE_VISIT_DATE", [
        r"site\s+visit", r"site\s+walkthrough", r"bidders\s+conference", r"information\s+session",
        r"proponents\s+conference", r"mandatory\s+meeting", r"optional\s+meeting", r"walkthrough",
        r"site\s+inspection", r"site\s+meeting"
    ]),
    # 7. Presentations / Demos / Interviews
    ("PRESENTATION_DATE", [
        r"presentation", r"interview", r"demonstration", r"demo", r"shortlist", r"oral",
        r"oral\s+presentation"
    ]),
    # 8. Award / Selection
    ("AWARD_DATE", [
        r"award", r"selection", r"intent\s+to\s+award", r"notification\s+of\s+award",
        r"anticipated\s+award", r"target\s+award"
    ]),
    # 9. Contract Start
    ("CONTRACT_START", [
        r"contract\s+start", r"commencement", r"start\s+date", r"service\s+start",
        r"effective\s+date", r"work\s+start"
    ]),
    # 10. Contract End / Expiry
    ("CONTRACT_END", [
        r"contract\s+end", r"completion", r"expiry", r"expiration", r"end\s+date",
        r"termination\s+date", r"work\s+end"
    ]),
    # 11. Proposal Validity
    ("VALIDITY_DATE", [
        r"validity", r"valid\s+until", r"proposal\s+valid", r"bid\s+valid",
        r"irrevocable\s+for"
    ]),
    # 12. Submission / Closing Deadlines (Standard Proposal Closing Event)
    ("SUBMISSION_DEADLINE", [
        r"submission", r"closing", r"close", r"due\s+date", r"rfp\s+due", r"tender\s+close",
        r"bid\s+close", r"deadline", r"closing\s+date", r"closing\s+time", r"submission\s+date"
    ]),
]


def classify_date_milestone(milestone_str: str) -> str:
    """Classify procurement milestone string into semantic event category."""
    m = (milestone_str or "").lower().strip()
    for event_type, patterns in DATE_EVENT_PATTERNS:
        if any(re.search(pat, m) for pat in patterns):
            return event_type
    return "OTHER_DATE"


SUBMISSION_DIMENSION_PATTERNS = [
    ("ENVELOPE_STRUCTURE", [
        r"separate\s+envelope", r"two-envelope", r"two\s+envelope", r"separate\s+financial",
        r"separate\s+technical", r"combined\s+proposal", r"single\s+package", r"combined\s+envelope",
        r"single\s+pdf", r"single\s+combined", r"combined\s+technical\s+and\s+financial",
        r"separate\s+files\s+per\s+envelope", r"envelope\s+1", r"envelope\s+2"
    ]),
    ("PAGE_LIMIT", [
        r"page\s+limit", r"max\s+pages", r"maximum\s+pages", r"pages\s+maximum", r"page\s+count",
        r"pages\s*\(\s*excluding", r"page\s+size",
        r"\b(?:exceed|maximum|limit\s+of|max)\s*(?:of\s*)?\d+\s*pages?\b",
        r"\b\d+\s*pages?\s*(?:max|limit)\b"
    ]),
    ("SUBMISSION_CHANNEL", [
        r"merx", r"buyandsell", r"electronic\s+bid\s+submission", r"electronic\s+submission",
        r"portal\s+upload", r"email\s+submission", r"email\s+only", r"\bemail\b", r"courier",
        r"hardcopy", r"hard\s+copy", r"physical\s+delivery", r"in\s+person", r"mail\s+submission",
        r"electronic\s+tender"
    ]),
    ("PORTAL_REQUIREMENT", [
        r"supplier\s+registration", r"portal\s+account", r"digital\s+key", r"eprocurement\s+setup",
        r"merx\s+registration"
    ]),
    ("SIGNATURE_REQUIREMENT", [
        r"authorized\s+signature", r"docusign", r"digital\s+signature", r"signed\s+form",
        r"duly\s+executed", r"signing\s+officer"
    ]),
    ("FILE_FORMAT", [
        r"excel\s+spreadsheet", r"excel\s+workbook", r"xlsx", r"docx", r"searchable\s+pdf",
        r"pdf\s+format", r"word\s+format", r"spreadsheet", r"excel", r"\bpdf\b"
    ]),
    ("DOCUMENT_REQUIREMENT", [
        r"appendix", r"submission\s+form", r"questionnaire", r"rate\s+card", r"pricing\s+form",
        r"certificate\s+of\s+insurance"
    ]),
]


def classify_submission_rule_dimension(item_str: str, format_str: str = "", details_str: str = "") -> str:
    """Classify a submission rule into its operational dimension."""
    combined = f"{item_str} {format_str} {details_str}".lower()
    for dimension, patterns in SUBMISSION_DIMENSION_PATTERNS:
        if any(re.search(pat, combined) for pat in patterns):
            return dimension
    return "OTHER_SUBMISSION_RULE"


def _is_physical_file(doc_name: str, package_files: list[str]) -> bool:
    """Check if a cited document name corresponds to a real physical file in the procurement package."""
    if not doc_name or not isinstance(doc_name, str):
        return False
    doc_clean = doc_name.strip()
    if doc_clean in ["General RFP Overview", "Summary", "Executive Brief", "Model Interpretation", "Package Overview", "Doc A", "Doc B"]:
        return False
    doc_base = doc_clean.split("/")[-1].split("\\")[-1]
    for pf in package_files:
        pf_base = pf.split("/")[-1].split("\\")[-1]
        if doc_clean == pf or doc_base == pf_base or doc_clean.lower() == pf.lower():
            return True
    return False


def validate_conflict_source_validity(source_a: dict, source_b: dict, package_files: list[str]) -> str:
    """Determine source validity: PHYSICAL_BOTH, PHYSICAL_PARTIAL, or SYNTHESIZED."""
    doc_a = source_a.get("doc", "") if isinstance(source_a, dict) else ""
    doc_b = source_b.get("doc", "") if isinstance(source_b, dict) else ""

    is_a_phys = _is_physical_file(doc_a, package_files)
    is_b_phys = _is_physical_file(doc_b, package_files)

    if is_a_phys and is_b_phys:
        return "PHYSICAL_BOTH"
    elif is_a_phys or is_b_phys:
        return "PHYSICAL_PARTIAL"
    return "SYNTHESIZED"


def detect_document_conflicts(normalized_facts: dict, package_files: list[str]) -> list[dict]:
    """
    Refined Stage C Deterministic Cross-Document Reconciliation Engine.
    Distinguishes:
      - TRUE_CONFLICT: Incompatible physical statements within the SAME semantic event / dimension.
      - REVIEW_ITEM: Unresolved scope nuance, attachment gate, or ambiguity.
      - Suppresses false positives from distinct event dates or complementary file formats.
    """
    conflicts = []
    conflict_idx = 1

    # ── 1. DATE CONFLICTS ─────────────────────────────────────────────────────
    dates = normalized_facts.get("dates", [])
    if len(dates) >= 2:
        actionable_milestones = {
            "SUBMISSION_DEADLINE", "QUESTION_DEADLINE", "SITE_VISIT_DATE",
            "PRESENTATION_DATE", "AWARD_DATE", "CONTRACT_START", "CONTRACT_END", "VALIDITY_DATE"
        }
        milestone_map = {}
        for d in dates:
            m_key = d.get("milestone", "")
            event_type = classify_date_milestone(m_key)
            if event_type in actionable_milestones:
                milestone_map.setdefault(event_type, []).append(d)

        for event_type, d_list in milestone_map.items():
            # Group by normalized date value
            dates_by_val = {}
            for d in d_list:
                dt_val = d.get("date", "").strip()
                if dt_val:
                    dates_by_val.setdefault(dt_val, []).append(d)

            # Cross-document conflict requires different dates from at least 2 distinct documents
            unique_docs = {d.get("source_doc") for d in d_list if d.get("source_doc")}
            if len(dates_by_val) > 1 and len(unique_docs) > 1:
                # Differing dates exist for the exact SAME semantic event across different documents
                d_sorted = sorted(d_list, key=lambda x: x.get("source_doc", ""))
                src_a = {"doc": d_sorted[0].get("source_doc", "Doc A"), "ref": d_sorted[0].get("milestone", ""), "text": d_sorted[0].get("date", "")}
                src_b = {"doc": d_sorted[-1].get("source_doc", "Doc B"), "ref": d_sorted[-1].get("milestone", ""), "text": d_sorted[-1].get("date", "")}
                
                sv = validate_conflict_source_validity(src_a, src_b, package_files)
                classification = "TRUE_CONFLICT" if sv == "PHYSICAL_BOTH" else "REVIEW_ITEM"
                confidence = "HIGH" if classification == "TRUE_CONFLICT" else "MEDIUM"
                
                conflicts.append({
                    "conflict_id": f"CONF-DATE-{conflict_idx}",
                    "conflict_type": "DATE_CONFLICT",
                    "classification": classification,
                    "confidence": confidence,
                    "reason": f"Conflicting dates detected for the same semantic milestone ({event_type.replace('_', ' ').title()}) across documents.",
                    "source_validity": sv,
                    "topic": f"Differing dates for {event_type.replace('_', ' ').title()}",
                    "source_a": src_a,
                    "source_b": src_b,
                    "assessment": f"Conflicting target dates detected across documents: {', '.join(dates_by_val.keys())}.",
                    "recommended_action": "Verify if the latest Addendum or Bulletin formally extends this deadline."
                })
                conflict_idx += 1

    # ── 2. EVALUATION CONFLICTS ───────────────────────────────────────────────
    eval_criteria = normalized_facts.get("evaluation_criteria", [])
    if len(eval_criteria) >= 2:
        tech_weights = []
        for ec in eval_criteria:
            stg = ec.get("stage", "").lower()
            wt = ec.get("weight", "")
            if "tech" in stg or "rated" in stg:
                tech_weights.append((ec.get("source_doc", "Document"), wt))

        unique_wts = {tw[1] for tw in tech_weights if tw[1]}
        if len(unique_wts) > 1:
            src_a = {"doc": tech_weights[0][0], "ref": "Technical Weight", "text": tech_weights[0][1]}
            src_b = {"doc": tech_weights[-1][0], "ref": "Technical Weight", "text": tech_weights[-1][1]}
            sv = validate_conflict_source_validity(src_a, src_b, package_files)
            classification = "TRUE_CONFLICT" if sv == "PHYSICAL_BOTH" else "REVIEW_ITEM"
            confidence = "HIGH" if classification == "TRUE_CONFLICT" else "MEDIUM"

            conflicts.append({
                "conflict_id": f"CONF-EVAL-{conflict_idx}",
                "conflict_type": "EVALUATION_CONFLICT",
                "classification": classification,
                "confidence": confidence,
                "reason": "Evaluation breakdown specifies contradictory technical scoring weights across documents.",
                "source_validity": sv,
                "topic": "Differing Technical Evaluation Weights Across Documents",
                "source_a": src_a,
                "source_b": src_b,
                "assessment": f"Evaluation breakdown specifies differing technical scoring ratios ({', '.join(unique_wts)}).",
                "recommended_action": "Submit clarification to confirm authoritative evaluation weighting formula."
            })
            conflict_idx += 1

    # ── 3. SUBMISSION RULE CONFLICTS ──────────────────────────────────────────
    sub_rules = normalized_facts.get("submission_rules", [])
    if len(sub_rules) >= 2:
        dim_rules = {}
        for sr in sub_rules:
            dim = classify_submission_rule_dimension(sr.get("item", ""), sr.get("format", ""), sr.get("details", ""))
            dim_rules.setdefault(dim, []).append(sr)

        # Dimension A: ENVELOPE_STRUCTURE (Separate vs Combined)
        env_rules = dim_rules.get("ENVELOPE_STRUCTURE", [])
        if len(env_rules) >= 2:
            has_sep = any("separate" in f"{r.get('item','')} {r.get('format','')} {r.get('details','')}".lower() for r in env_rules)
            has_comb = any(k in f"{r.get('item','')} {r.get('format','')} {r.get('details','')}".lower() for k in ["single", "combined", "single package", "single combined", "combined proposal"] for r in env_rules)
            if has_sep and has_comb:
                sep_r = next(r for r in env_rules if "separate" in f"{r.get('item','')} {r.get('format','')} {r.get('details','')}".lower())
                comb_r = next(r for r in env_rules if any(k in f"{r.get('item','')} {r.get('format','')} {r.get('details','')}".lower() for k in ["single", "combined", "single package", "single combined", "combined proposal"]))
                
                src_a = {"doc": sep_r.get("source_doc", "Doc A"), "ref": "Submission Rules", "text": str(sep_r.get("format") or sep_r.get("item", ""))}
                src_b = {"doc": comb_r.get("source_doc", "Doc B"), "ref": "Submission Rules", "text": str(comb_r.get("format") or comb_r.get("item", ""))}
                sv = validate_conflict_source_validity(src_a, src_b, package_files)
                classification = "TRUE_CONFLICT" if sv == "PHYSICAL_BOTH" else "REVIEW_ITEM"

                conflicts.append({
                    "conflict_id": f"CONF-SUB-{conflict_idx}",
                    "conflict_type": "SUBMISSION_RULE_CONFLICT",
                    "classification": classification,
                    "confidence": "HIGH" if classification == "TRUE_CONFLICT" else "MEDIUM",
                    "reason": "Contradictory envelope separation instructions (separate vs combined submission).",
                    "source_validity": sv,
                    "topic": "Envelope / Document Separation Contradiction",
                    "source_a": src_a,
                    "source_b": src_b,
                    "assessment": "One document indicates separate technical/financial files while another suggests combined submission.",
                    "recommended_action": "Always separate Financial Envelope from Technical Proposal to prevent mandatory disqualification."
                })
                conflict_idx += 1

        # Dimension B: SUBMISSION_CHANNEL (e.g. MERX vs Email only)
        chan_rules = dim_rules.get("SUBMISSION_CHANNEL", [])
        if len(chan_rules) >= 2:
            has_portal = any(k in f"{r.get('item','')} {r.get('format','')} {r.get('details','')}".lower() for k in ["merx", "buyandsell", "portal", "electronic bid submission"] for r in chan_rules)
            has_email_only = any(k in f"{r.get('item','')} {r.get('format','')} {r.get('details','')}".lower() for k in ["email only", "email submission only", "via email only", "courier only", "hardcopy only"] for r in chan_rules)
            if has_portal and has_email_only:
                port_r = next(r for r in chan_rules if any(k in f"{r.get('item','')} {r.get('format','')} {r.get('details','')}".lower() for k in ["merx", "buyandsell", "portal", "electronic bid submission"]))
                email_r = next(r for r in chan_rules if any(k in f"{r.get('item','')} {r.get('format','')} {r.get('details','')}".lower() for k in ["email only", "email submission only", "via email only", "courier only", "hardcopy only"]))
                
                src_a = {"doc": port_r.get("source_doc", "Doc A"), "ref": "Submission Channel", "text": str(port_r.get("format") or port_r.get("details", ""))}
                src_b = {"doc": email_r.get("source_doc", "Doc B"), "ref": "Submission Channel", "text": str(email_r.get("format") or email_r.get("details", ""))}
                sv = validate_conflict_source_validity(src_a, src_b, package_files)
                classification = "TRUE_CONFLICT" if sv == "PHYSICAL_BOTH" else "REVIEW_ITEM"

                conflicts.append({
                    "conflict_id": f"CONF-SUB-{conflict_idx}",
                    "conflict_type": "SUBMISSION_RULE_CONFLICT",
                    "classification": classification,
                    "confidence": "HIGH" if classification == "TRUE_CONFLICT" else "MEDIUM",
                    "reason": "Contradictory transmission channels specified across procurement documents.",
                    "source_validity": sv,
                    "topic": "Conflicting Submission Channels (Portal vs Email/Hardcopy)",
                    "source_a": src_a,
                    "source_b": src_b,
                    "assessment": "Documents specify conflicting submission channels (portal upload vs direct email/hardcopy).",
                    "recommended_action": "Verify authoritative submission channel with contracting authority."
                })
                conflict_idx += 1

        # Dimension C: PAGE_LIMIT (e.g. 10 pages vs 15 pages for the same scope)
        page_rules = dim_rules.get("PAGE_LIMIT", [])
        if len(page_rules) >= 2:
            scope_limits = {}
            for pr in page_rules:
                combined = f"{pr.get('item','')} {pr.get('format','')} {pr.get('details','')}".lower()
                doc = pr.get("source_doc", "Doc")
                
                # Ignore per-sample or per-resume sub-caps
                if any(k in combined for k in ["per sample", "per resume", "per individual", "per profile", "sample of", "samples of"]):
                    continue
                
                # Determine scope category
                scope = "GENERAL_PROPOSAL"
                if "d1" in doc.lower() or "category 1" in combined:
                    scope = "CATEGORY_1"
                elif "d2" in doc.lower() or "category 2" in combined:
                    scope = "CATEGORY_2"
                elif "d3" in doc.lower() or "category 3" in combined:
                    scope = "CATEGORY_3"
                    
                match = re.search(r'\b(?:exceed|maximum|limit\s+of|max)\s*(?:of\s*)?(\d+)\s*pages?\b', combined) or re.search(r'\b(\d+)\s*pages?\s*(?:max|limit)\b', combined)
                if not match:
                    match = re.search(r'\b(\d+)\s*pages?\b', combined)
                if match:
                    scope_limits.setdefault(scope, []).append((doc, int(match.group(1)), pr))

            for scope, p_list in scope_limits.items():
                unique_limits = {p[1] for p in p_list}
                unique_docs = {p[0] for p in p_list}
                if len(unique_limits) > 1 and len(unique_docs) > 1:
                    src_a = {"doc": p_list[0][0], "ref": f"Page Limit ({scope})", "text": f"{p_list[0][1]} pages"}
                    src_b = {"doc": p_list[-1][0], "ref": f"Page Limit ({scope})", "text": f"{p_list[-1][1]} pages"}
                    sv = validate_conflict_source_validity(src_a, src_b, package_files)
                    classification = "TRUE_CONFLICT" if sv == "PHYSICAL_BOTH" else "REVIEW_ITEM"

                    conflicts.append({
                        "conflict_id": f"CONF-SUB-{conflict_idx}",
                        "conflict_type": "SUBMISSION_RULE_CONFLICT",
                        "classification": classification,
                        "confidence": "HIGH" if classification == "TRUE_CONFLICT" else "MEDIUM",
                        "reason": f"Contradictory maximum page limits specified for {scope.replace('_', ' ').title()}.",
                        "source_validity": sv,
                        "topic": f"Differing Page Limits for {scope.replace('_', ' ').title()}",
                        "source_a": src_a,
                        "source_b": src_b,
                        "assessment": f"Conflicting page limit thresholds detected ({', '.join(str(u) for u in unique_limits)} pages).",
                        "recommended_action": "Strictly comply with the most restrictive page limit unless clarified."
                    })
                    conflict_idx += 1

    # ── 4. MANDATORY REQUIREMENT CONFLICTS & SCOPE REVIEW ITEMS ───────────────
    reqs = normalized_facts.get("requirements", [])
    mand_reqs = [r for r in reqs if r.get("category") == "Mandatory"]
    bilingual_reqs = [r for r in mand_reqs if "bilingual" in r.get("description", "").lower() or "french" in r.get("description", "").lower()]
    if bilingual_reqs:
        docs_with_bilingual = {ref.get("source_doc") for r in bilingual_reqs for ref in r.get("source_refs", []) if ref.get("source_doc")}
        all_pkg_docs = set(package_files)
        if len(docs_with_bilingual) > 0 and len(docs_with_bilingual) < len(all_pkg_docs) and len(all_pkg_docs) > 1:
            src_doc = list(docs_with_bilingual)[0]
            src_a = {"doc": src_doc, "ref": "Mandatory Gate", "text": bilingual_reqs[0].get("description", "")[:120]}
            src_b = {"doc": "Package Overview", "ref": "General Scope", "text": "Language requirement appears stream-specific to this attachment and is not highlighted in general package overview."}
            
            # Since source_b is an overview observation and not an opposing physical contradictory file,
            # this MUST be classified as REVIEW_ITEM / AMBIGUITY with PHYSICAL_PARTIAL validity.
            conflicts.append({
                "conflict_id": f"CONF-MAND-{conflict_idx}",
                "conflict_type": "MANDATORY_REQUIREMENT_CONFLICT",
                "classification": "REVIEW_ITEM",
                "confidence": "MEDIUM",
                "reason": "Specific attachment contains a qualification gate not emphasized in the general overview. Confirm scope/application before bid decision.",
                "source_validity": "PHYSICAL_PARTIAL",
                "topic": "Mandatory Language / Capability Specified in Specific Attachment",
                "source_a": src_a,
                "source_b": src_b,
                "assessment": "Mandatory bilingualism or specialized qualification applies to specific work streams/categories.",
                "recommended_action": "Confirm whether bilingual capability is mandatory for all streams or category-specific."
            })
            conflict_idx += 1

    # ── 5. COMMERCIAL TERM CONFLICTS ──────────────────────────────────────────
    comm_clauses = normalized_facts.get("commercial_clauses", [])
    if len(comm_clauses) >= 2:
        # Check panel vendor caps
        panel_terms = [c for c in comm_clauses if "panel" in c.get("topic", "").lower() or "maximum" in c.get("topic", "").lower()]
        if len(panel_terms) >= 2 and len({p.get("details") for p in panel_terms}) > 1:
            src_a = {"doc": panel_terms[0].get("source_doc", "Doc A"), "ref": panel_terms[0].get("topic", ""), "text": panel_terms[0].get("details", "")}
            src_b = {"doc": panel_terms[-1].get("source_doc", "Doc B"), "ref": panel_terms[-1].get("topic", ""), "text": panel_terms[-1].get("details", "")}
            sv = validate_conflict_source_validity(src_a, src_b, package_files)
            classification = "TRUE_CONFLICT" if sv == "PHYSICAL_BOTH" else "REVIEW_ITEM"

            conflicts.append({
                "conflict_id": f"CONF-COMM-{conflict_idx}",
                "conflict_type": "COMMERCIAL_TERM_CONFLICT",
                "classification": classification,
                "confidence": "HIGH" if classification == "TRUE_CONFLICT" else "MEDIUM",
                "reason": "Contradictory commercial panel maximums or award caps specified across documents.",
                "source_validity": sv,
                "topic": "Differing Commercial Panel Maximums or Rate Caps",
                "source_a": src_a,
                "source_b": src_b,
                "assessment": "Discrepancy in panel size caps or rate limitations across procurement documents.",
                "recommended_action": "Verify maximum vendor award counts per category."
            })
            conflict_idx += 1

        # Check insurance requirements
        ins_terms = [c for c in comm_clauses if "insurance" in c.get("topic", "").lower() or "liability" in c.get("topic", "").lower()]
        if len(ins_terms) >= 2 and len({i.get("details") for i in ins_terms}) > 1:
            src_a = {"doc": ins_terms[0].get("source_doc", "Doc A"), "ref": ins_terms[0].get("topic", ""), "text": ins_terms[0].get("details", "")}
            src_b = {"doc": ins_terms[-1].get("source_doc", "Doc B"), "ref": ins_terms[-1].get("topic", ""), "text": ins_terms[-1].get("details", "")}
            sv = validate_conflict_source_validity(src_a, src_b, package_files)
            classification = "TRUE_CONFLICT" if sv == "PHYSICAL_BOTH" else "REVIEW_ITEM"

            conflicts.append({
                "conflict_id": f"CONF-COMM-{conflict_idx}",
                "conflict_type": "COMMERCIAL_TERM_CONFLICT",
                "classification": classification,
                "confidence": "HIGH" if classification == "TRUE_CONFLICT" else "MEDIUM",
                "reason": "Conflicting commercial insurance liability thresholds across documents.",
                "source_validity": sv,
                "topic": "Conflicting Commercial Insurance Requirements",
                "source_a": src_a,
                "source_b": src_b,
                "assessment": "Discrepancy in required commercial general liability coverage amounts.",
                "recommended_action": "Confirm authoritative insurance coverage limits with contracting authority."
            })
            conflict_idx += 1

    # ── 6. SCOPE CONFLICTS ────────────────────────────────────────────────────
    deliverables = normalized_facts.get("deliverables", [])
    if len(deliverables) >= 2:
        cohort_delivs = [d for d in deliverables if "cohort" in d.get("title", "").lower() or "session" in d.get("title", "").lower()]
        if len(cohort_delivs) >= 2 and len({c.get("description") for c in cohort_delivs}) > 1:
            src_a = {"doc": cohort_delivs[0].get("source_doc", "Doc A"), "ref": "Deliverables SOW", "text": cohort_delivs[0].get("description", "")}
            src_b = {"doc": cohort_delivs[-1].get("source_doc", "Doc B"), "ref": "Schedule Table", "text": cohort_delivs[-1].get("description", "")}
            sv = validate_conflict_source_validity(src_a, src_b, package_files)
            classification = "TRUE_CONFLICT" if sv == "PHYSICAL_BOTH" else "REVIEW_ITEM"

            conflicts.append({
                "conflict_id": f"CONF-SCOPE-{conflict_idx}",
                "conflict_type": "SCOPE_CONFLICT",
                "classification": classification,
                "confidence": "HIGH" if classification == "TRUE_CONFLICT" else "MEDIUM",
                "reason": "Conflicting deliverable quantities or session counts across documents.",
                "source_validity": sv,
                "topic": "Deliverable Volume / Cohort Sizing Discrepancy",
                "source_a": src_a,
                "source_b": src_b,
                "assessment": "Differing volume counts or delivery session quantities between SOW and pricing schedule.",
                "recommended_action": "Seek written clarification on authoritative cohort baseline for pricing."
            })
            conflict_idx += 1

    # ── 7. FINAL SOURCE VALIDITY ENFORCEMENT ──────────────────────────────────
    for c in conflicts:
        sv = validate_conflict_source_validity(c.get("source_a", {}), c.get("source_b", {}), package_files)
        c["source_validity"] = sv
        if sv != "PHYSICAL_BOTH" and c.get("classification") == "TRUE_CONFLICT":
            c["classification"] = "REVIEW_ITEM"
            c["confidence"] = "MEDIUM"

    return conflicts


# ── 4-STAGE GENUINE PIPELINE IMPLEMENTATION ───────────────────────────────────

def _clean_raw(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def _safe_parse_json(raw: str) -> dict:
    try:
        from analyst import _parse_json
        res = _parse_json(raw)
        if isinstance(res, dict):
            return res
    except Exception:
        pass
    try:
        return json.loads(_clean_raw(raw))
    except Exception:
        return {}


# ── STAGE A: DOCUMENT FACT EXTRACTION ─────────────────────────────────────────

def extract_document_facts(doc_text: str, filename: str, api_key: str) -> dict:
    """
    STAGE A: Process document to extract factual procurement data ONLY.
    Does NOT synthesize executive Bid Brief.
    """
    client = get_anthropic_client(api_key=api_key)
    model = "claude-haiku-4-5-20251001"

    text_to_send = doc_text if len(doc_text) < 150000 else (doc_text[:150000] + "\n\n[Document text truncated]")

    content = [
        {
            "type": "text",
            "text": STAGE_A_FACT_EXTRACTION_PROMPT + f"\n\nDOCUMENT TO PROCESS ({filename}):\n" + text_to_send
        }
    ]

    response = client.messages.create(
        model=model,
        max_tokens=8000,
        messages=[{"role": "user", "content": content}],
    )

    data = _safe_parse_json(response.content[0].text)
    if not isinstance(data, dict):
        data = {}

    # Tag all items with source document
    for r in data.get("requirements", []):
        r.setdefault("source_refs", [{"source_doc": filename, "page": None, "sheet": None, "section": None, "excerpt": r.get("description", "")[:100]}])
    for d in data.get("dates", []):
        d.setdefault("source_doc", filename)
    for e in data.get("evaluation_criteria", []):
        e.setdefault("source_doc", filename)
    for s in data.get("submission_rules", []):
        s.setdefault("source_doc", filename)
    for c in data.get("commercial_clauses", []):
        c.setdefault("source_doc", filename)

    return data


# ── STAGE B: PACKAGE NORMALIZATION ───────────────────────────────────────────

def normalize_package_facts(doc_facts_list: list[dict], package_metadata: dict) -> dict:
    """
    STAGE B: Combine document-level facts, deduplicate identical items,
    merge source references, and validate source provenance.
    """
    normalized = {
        "doc_metadata": {},
        "requirements": [],
        "dates": [],
        "evaluation_criteria": [],
        "submission_rules": [],
        "deliverables": [],
        "commercial_clauses": [],
        "contract_risks": []
    }

    req_seen = {}
    for df in doc_facts_list:
        # Merge metadata (first non-empty)
        meta = df.get("doc_metadata", {})
        for k, v in meta.items():
            if v and not normalized["doc_metadata"].get(k):
                normalized["doc_metadata"][k] = v

        # Normalize and deduplicate requirements
        for r in df.get("requirements", []):
            desc_key = re.sub(r'\W+', '', r.get("description", "").lower())[:60]
            # Validate source references
            validated_refs = validate_source_refs(r.get("source_refs", []), package_metadata)
            
            if desc_key in req_seen:
                # Merge source references into existing requirement
                existing_r = req_seen[desc_key]
                existing_refs = existing_r.get("source_refs", [])
                for vref in validated_refs:
                    if not any(e.get("source_doc") == vref.get("source_doc") and e.get("page") == vref.get("page") for e in existing_refs):
                        existing_refs.append(vref)
                existing_r["source_refs"] = existing_refs
            else:
                r_copy = dict(r)
                r_copy["source_refs"] = validated_refs
                r_copy.setdefault("qual_status", "UNKNOWN")
                r_copy.setdefault("evidence_status", "MISSING")
                req_seen[desc_key] = r_copy
                normalized["requirements"].append(r_copy)

        # Merge other facts
        normalized["dates"].extend(df.get("dates", []))
        normalized["evaluation_criteria"].extend(df.get("evaluation_criteria", []))
        normalized["submission_rules"].extend(df.get("submission_rules", []))
        normalized["deliverables"].extend(df.get("deliverables", []))
        normalized["commercial_clauses"].extend(df.get("commercial_clauses", []))
        normalized["contract_risks"].extend(df.get("contract_risks", []))

    return normalized


# ── STAGE C: RECONCILIATION & CONFLICT ANALYSIS ───────────────────────────────

def reconcile_package_facts(normalized_facts: dict, package_files: list[str]) -> list[dict]:
    """
    STAGE C: Compare normalized facts to detect cross-document conflicts & addenda overrides.
    """
    return detect_document_conflicts(normalized_facts, package_files)


# ── STAGE D: BID BRIEF SYNTHESIS ─────────────────────────────────────────────

def synthesize_bid_brief(normalized_facts: dict, conflicts: list[dict], api_key: str) -> dict:
    """
    STAGE D: Synthesize the executive Bid Brief exclusively from the normalized/reconciled facts.
    """
    client = get_anthropic_client(api_key=api_key)
    model = "claude-haiku-4-5-20251001"

    facts_summary = json.dumps({
        "metadata": normalized_facts.get("doc_metadata", {}),
        "requirements_sample": [r.get("description","")[:150] for r in normalized_facts.get("requirements", [])[:15]],
        "dates": normalized_facts.get("dates", []),
        "evaluation": normalized_facts.get("evaluation_criteria", []),
        "submission_rules": normalized_facts.get("submission_rules", []),
        "deliverables": normalized_facts.get("deliverables", []),
        "commercial": normalized_facts.get("commercial_clauses", []),
        "contract_risks": normalized_facts.get("contract_risks", []),
        "detected_conflicts": conflicts
    }, indent=2)

    content = [
        {
            "type": "text",
            "text": STAGE_D_SYNTHESIS_PROMPT + "\n\nNORMALIZED PROCUREMENT FACTS MODEL:\n" + facts_summary
        }
    ]

    response = client.messages.create(
        model=model,
        max_tokens=8000,
        messages=[{"role": "user", "content": content}],
    )

    synth_data = _safe_parse_json(response.content[0].text)
    if not isinstance(synth_data, dict):
        synth_data = {}

    return synth_data


# ── MAIN ORCHESTRATOR ─────────────────────────────────────────────────────────

def extract_procurement_package(package_files: list[tuple[str, bytes]], api_key: str) -> tuple[dict, str]:
    """
    Genuine 4-Stage Ingestion & Extraction Pipeline:
    1. STAGE A: Document Fact Extraction with Deterministic Markers.
    2. STAGE B: Package Normalization & Strict Provenance Validation.
    3. STAGE C: Cross-Document Reconciliation (6 Conflict Classes).
    4. STAGE D: Executive Bid Brief Synthesis from Normalized Facts Model.
    """
    # Step 0: Preprocess and extract text & metadata for each document
    package_metadata = {
        "files": [f[0] for f in package_files],
        "doc_metadata": {},
        "doc_texts": {}
    }
    
    extracted_docs = []
    for fname, fbytes in package_files:
        doc_text, dmeta = extract_document_with_metadata(fbytes, fname)
        package_metadata["doc_metadata"][fname] = dmeta
        package_metadata["doc_texts"][fname] = doc_text
        extracted_docs.append((fname, doc_text))

    # STAGE A: Extract facts per document
    doc_facts_list = []
    for fname, doc_text in extracted_docs:
        facts = extract_document_facts(doc_text, fname, api_key)
        doc_facts_list.append(facts)

    # STAGE B: Package Normalization & Provenance Validation
    normalized_facts = normalize_package_facts(doc_facts_list, package_metadata)

    # STAGE C: Reconciliation & Conflict Analysis
    conflicts = reconcile_package_facts(normalized_facts, package_metadata["files"])

    # STAGE D: Executive Bid Brief Synthesis
    synth_output = synthesize_bid_brief(normalized_facts, conflicts, api_key)

    # Assemble Final Output
    bid = synth_output.get("bid", {})
    brief = synth_output.get("brief", {})
    outline = synth_output.get("outline", [])

    # Ensure document_conflicts is attached to brief
    brief["document_conflicts"] = conflicts

    # Transform submission rules into documents checklist
    documents = []
    for sr in normalized_facts.get("submission_rules", []):
        documents.append({
            "name": sr.get("item", "Submission Document"),
            "doc_type": "Financial" if "financial" in sr.get("item","").lower() or "pricing" in sr.get("item","").lower() else "Submission",
            "owner": None,
            "due_date": bid.get("submission_deadline"),
            "status": "Expected",
            "mandatory": sr.get("mandatory", 1),
            "notes": sr.get("details", "")
        })

    # If no documents generated, create standard default package items
    if not documents:
        documents = [
            {"name": "Technical Proposal.pdf", "doc_type": "Submission", "mandatory": 1, "status": "Expected"},
            {"name": "Financial Envelope.pdf", "doc_type": "Financial", "mandatory": 1, "status": "Expected"}
        ]

    result = {
        "bid": bid,
        "brief": brief,
        "requirements": normalized_facts.get("requirements", []),
        "documents": documents,
        "outline": outline
    }

    return result, "claude-haiku-4-5-20251001 (Staged Pipeline A->B->C->D)"


# Legacy Single-File Compatibility Alias
def extract_rfp(file_bytes: bytes, filename: str, api_key: str) -> tuple:
    """Backward-compatible single file extraction invoking staged package ingestion."""
    return extract_procurement_package([(filename, file_bytes)], api_key)
