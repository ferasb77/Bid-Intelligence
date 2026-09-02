# Submission Document Provenance Report

**Branch:** `fix/submission-document-provenance`  
**Base:** `main` at `1caf136353b1853370d2a58b3fd4c5b45ab59bb3`  
**Date:** 2026-09-02 (Finalized)

---

## 1. Executive Summary & Defect Remediation

Bid Intelligence previously suffered from two major defects regarding submission documents:

1. **Invented Default Fallback:** `extract_procurement_package()` manufactured synthetic document records (`Technical Proposal.pdf` and `Financial Envelope.pdf`) whenever no documents were extracted. These names lacked source evidence.
2. **Classifier Inversion & False Document Projections:** Earlier classifier iterations either projected too many rules (treating process rules, embedded form fields, and workbook tabs as documents) or relied too heavily on lexical noun tokens (`confirmation`, `declaration`, `form`) without requiring standalone file/package semantics.

The classifier has been finalized to make **structural format evidence authoritative**.

---

## 2. Four-Tier Classification Architecture

The projection question is: *"Does this normalized rule establish a discrete, independently tracked submission artefact?"* Standalone file/package semantics dominate over superficial noun tokens.

The classifier `_is_concrete_submission_document(item, fmt, details)` in `extractor.py` implements a four-tier deterministic hierarchy:

```
+-------------------------------------------------------------------------+
| Priority 1: Hard Negative Signals (EXCLUDE)                             |
| - Embedded markers: "form entry", "integrated", "embedded"              |
| - Ambiguous mixed formats: "Embedded or Separate File",                 |
|   "Separate Files or Embedded", "Integrated or attached"                |
| - Checklist columns: "proponent response column", "yes/no confirmation" |
| - Portal containers: "electronic bid submission"                        |
| - Reference-only / process / formatting: "available for reference",     |
|   "will not be evaluated", "page limit", "response format"              |
| - Workbook tabs: tabs or worksheets of a parent workbook                |
+-------------------------------------------------------------------------+
                                    |
                                    v (passed negatives)
+-------------------------------------------------------------------------+
| Priority 2: Explicit Independent-File Format (INCLUDE)                  |
| Format explicitly establishes a standalone file/package:                |
| - "Separate File", "Separate Files", "Separate Submission",             |
|   "Separate Document", "Single Document", "Standalone Document",        |
|   "Attachment", "Attachments", "Attached File", "Attached Files",       |
|   "Attached samples", "PDF", "DOCX", "XLSX", "Spreadsheet",             |
|   "Excel Workbook", "Excel Spreadsheet"                                 |
+-------------------------------------------------------------------------+
                                    |
                                    v (format not explicitly independent)
+-------------------------------------------------------------------------+
| Priority 3: Standalone Artifact Identity (INCLUDE conditionally)        |
| Generic document format ("Document") or unspecified format paired with  |
| strong standalone submission package nouns:                             |
| - forms, proposals, questionnaires, templates, annexes, schedules,      |
|   pricing forms, rate cards, work plans (with singular/plural support)  |
+-------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------+
| Priority 4: Conservative Fallback (EXCLUDE)                             |
| Weak/ambiguous formats ("Written documentation", "Supporting            |
| documentation", "Electronic") or unconfirmed artifact nouns             |
| (confirmation, declaration, resume, report) are omitted from documents. |
| They remain accessible in submission_rules for Stage D and UNDERSTAND.  |
+-------------------------------------------------------------------------+
```

### Key Policy Decisions:
- **Written Content is Not a File by Default:** Phrases such as `Written documentation`, `Supporting documentation`, `Written confirmation`, `Declaration`, and `Confirmation` do not prove that a separate file is required. Without explicit independent-file evidence, they are not projected into the document checklist.
- **Ambiguous Mixed Formats are Excluded:** Formats permitting either embedded or separate submission (`Embedded or Separate File`, `Separate Files or Embedded`) are treated conservatively and not projected as required independent files.
- **Word-Boundary & Morphology Matching:** Regex `` word boundaries prevent substring matching errors (`form` matching `information` or `format`), while supporting controlled singular/plural morphology (`profile` / `profiles`, `sample` / `samples`, `resume` / `resumes`, `form` / `forms`).

---

## 3. End-to-End Handling of Unknown Mandatory Status

Mandatory status is strictly preserved from normalized facts:
- `mandatory = 1` -> `[REQUIRED]` (Red tag)
- `mandatory = 0` -> `[OPTIONAL]` (Gray tag)
- `mandatory` absent / `None` -> `[UNKNOWN — review status]` (Amber tag)

In `pages/stage_submit.py`:
- Documents with `mandatory=None` are not silently promoted to `REQUIRED` (avoiding false blockers) nor converted to `OPTIONAL`.
- Visibly tagged as `[UNKNOWN — review status]`.
- Surfaces a warning gate: `READY WITH WARNINGS (Unverified Gates)`.
- *Note on Governance:* Definitive final-gate treatment and human resolution workflows are deferred to the planned Submit-state consistency branch.

---

## 4. Bank of Canada Frozen Replay Results

**Fixture:** `tests/acceptance/results/boc_2026_026_normalized_facts.json` (40 normalized submission rules).  
*No Stage A/B/C re-run. No Anthropic API call.*

### Resulting Classification: 10 Projected Documents, 30 Excluded Rules

#### Projected Discrete Submission Documents (10):
1. **Thought Leadership Samples** (`fmt: Attached samples`, mandatory=1, Submission)
2. **ESG Questionnaire Response** (`fmt: Spreadsheet`, mandatory=0, Submission)
3. **Appendix A Submission Form** (`fmt: Separate File`, mandatory=1, Submission)
4. **Minimum Qualification Requirements Response** (`fmt: Separate submission per Appendix C1`, mandatory=1, Submission)
5. **Rated Criteria Response Form** (`fmt: Document`, mandatory=1, Submission)
6. **Work or Product Samples** (`fmt: Separate Files`, mandatory=0, Submission)
7. **Response Document** (`fmt: Single Document`, mandatory=1, Submission)
8. **Resumes or Professional Profiles** (`fmt: Separate Submission`, mandatory=0, Submission)
9. **Work or Product Samples** (`fmt: Separate Submission`, mandatory=1, Submission)
10. **Pricing Form - All Applicable Sections** (`fmt: Excel Spreadsheet`, mandatory=1, Financial)

#### Excluded Non-File / Embedded / Process Rules (30):
- **Written documentation without standalone-file evidence (2):**
  - `Bilingualism Confirmation` (`fmt: Written documentation`)
  - `Security Clearance Declaration` (`fmt: Written documentation`)
- **Embedded / integrated narrative content (6):**
  - `Key Personnel Profiles` (`fmt: Integrated in response`)
  - `Key Personnel Profiles` (`fmt: Embedded or Separate File`)
  - `Key Personnel Profiles` (`fmt: Embedded in Response`)
  - `Thought Leadership Samples` (`fmt: Separate Files or Embedded`)
  - `Resumes or Professional Profiles` (`fmt: Separate Files or Embedded`)
  - `Case Study References` (`fmt: Integrated in response with contact details`)
- **Supporting documentation notes without explicit standalone format (3):**
  - `Resumes or Professional Profiles` (`fmt: Supporting Documentation`)
  - `Work or Product Samples` (`fmt: Supporting Documentation`)
  - `External References` (`fmt: Embedded in Response`)
- **Embedded form fields inside Appendix A (4):**
  - `Proponent Information` (`fmt: Form Entry`)
  - `Conflict of Interest Declaration` (`fmt: Form Entry`)
  - `Compliance Certifications` (`fmt: Form Entry`)
  - `Addenda Acknowledgement` (`fmt: Form Entry`)
- **Checklist columns & confirmation fields (2):**
  - `Minimum Qualification Response` (`fmt: Proponent Response column (Yes/No format)`)
  - `Minimum qualification requirements response` (`fmt: Yes / No confirmation`)
- **Portal packaging containers (2):**
  - `Envelope 1 - Identity & Proposal` (`fmt: Electronic Bid Submission`)
  - `Envelope 2 - Pricing` (`fmt: Electronic Bid Submission`)
- **Page limit & format rules (2):**
  - `Response Format and Page Limit` (`fmt: Separate document`, format/page instruction)
  - `Response Format` (`fmt: PDF / Separate Files`, format/page instruction)
- **Reference-only & evaluation restrictions (3):**
  - `RFP Main Document` (`fmt: Electronic`, details: available for reference)
  - `External Links` (`fmt: Not permitted`)
  - `External Links and References` (`fmt: Supporting Documentation`, details: links not evaluated)
- **Workbook tabs within pricing workbook (4):**
  - `Category Selection Tab` (`fmt: Excel Spreadsheet`)
  - `Service Category Rate Card Tab` (`fmt: Excel Spreadsheet`)
  - `Evaluated Pricing Scenario Tab` (`fmt: Excel Spreadsheet`)
  - `Value-Added Services Tab (Optional)` (`fmt: Excel Spreadsheet`)
- **Pricing rules (2):**
  - `Currency and Tax Treatment` (`fmt: Excel Spreadsheet`)
  - `Assumptions and Restrictions Documentation` (`fmt: Excel Spreadsheet`)

*Note on Benchmarking:* This projection count is derived deterministically from the authoritative format evidence rules. No claim of absolute source truth is asserted without an independent human ground-truth benchmark.

---

## 5. Verification & Test Suite

```
================================================================================
FULL REGRESSION SUITE
================================================================================
1. tests/test_stage_c_refinement.py:                60 /  60 PASSED
2. tests/test_streamlined_workflow.py:              27 /  27 PASSED
3. tests/test_stage_d_completeness.py:              52 /  52 PASSED
4. tests/test_submission_document_provenance.py:    75 /  75 PASSED
   - TestWordBoundaryMatching:                         4 /   4
   - TestClassifierRegressions (cases A-I, A-F, etc): 32 /  32
   - TestBuildSubmissionDocuments (cases A-H, mand): 15 /  15
   - TestBoCFrozenSubmissionReplay (semantic):       23 /  23
   - TestOrchestratorEmptyDocumentState (mocked):     1 /   1
5. tests/integration/:                              5 /   5 PASSED (1 live AI skipped)
6. tests/smoke/ + live Supabase:                   12 /  12 PASSED
================================================================================
TOTAL DISCOVERED:                                 232
TOTAL PASSED:                                     231
TOTAL SKIPPED:                                      1 (live AI integration)
TOTAL FAILED / ERRORS:                              0
================================================================================
```

---

## 6. Modified Files

| File | Changes |
|---|---|
| `extractor.py` | Finalized `_is_concrete_submission_document()` with authoritative structural format evidence, four-tier decision hierarchy, mixed/embedded negative filters, and workbook tab exclusion. |
| `pages/stage_submit.py` | Updated UNKNOWN mandatory tag to `[UNKNOWN — review status]` and preserved non-blocking warning gate. |
| `pages/stage_understand.py` | Factual copy for empty-state submission documents view. |
| `tests/test_submission_document_provenance.py` | 69 offline deterministic unit tests covering generic regression cases A-I, word boundaries, format evidence, workbook tabs, orchestrator mock, and BoC semantic replay. |
| `SUBMISSION_DOCUMENT_PROVENANCE_REPORT.md` | Full architecture, four-tier hierarchy, and BoC classification report. |
