# Submission Document Provenance Report

**Branch:** `fix/submission-document-provenance`  
**Base:** `main` at `1caf136353b1853370d2a58b3fd4c5b45ab59bb3`  
**Date:** 2026-09-02 (Updated post review corrections)

---

## 1. Executive Summary & Defect Remediation

Bid Intelligence previously suffered from two major defects regarding submission documents:

1. **Invented Default Fallback:** `extract_procurement_package()` created manufactured document records (`Technical Proposal.pdf` and `Financial Envelope.pdf`) whenever no documents were produced from normalized facts. These names were hallucinated by the pipeline and lacked source evidence.
2. **Over-Projection of Rules as Files:** An earlier naive classifier treated almost every submission rule (39 out of 40 in the Bank of Canada fixture) as an independent document. It matched arbitrary substrings (e.g. `"form"` matching inside `"information"` or `"format"`), ignored the structured `format` field, and projected form fields, embedded narrative sections, workbook tabs, and format instructions into the `documents` table.

Both defects have been eliminated. The pipeline strictly aligns the `documents` table with its intended product semantics: **a checklist of discrete, independently tracked submission files and package deliverables**.

---

## 2. Semantic Framework: Categorizing Submission Rules

To avoid turning every procurement rule into a required file blocker, the system cleanly distinguishes four categories of normalized submission requirements:

### A. Independent Submission Documents / Files (Projected)
Discrete artefacts that a bid team must prepare, upload, or sign off as a standalone deliverable:
- Standalone forms (e.g., `"Appendix A Submission Form"`, format: `Separate File`)
- Pricing workbooks (e.g., `"Pricing Form - All Applicable Sections"`, format: `Excel Spreadsheet`)
- Technical response documents (e.g., `"Rated Criteria Response Form"`, format: `Document`)
- Standalone questionnaires (e.g., `"ESG Questionnaire Response"`, format: `Spreadsheet`)
- Standalone written certificates or declarations (e.g., `"Bilingualism Confirmation"`, format: `Written documentation`)

### B. Embedded Response Components (Excluded from Documents Checklist)
Content required inside another submitted document or form:
- **Form entries:** `"Proponent Information"`, `"Conflict of Interest Declaration"`, `"Compliance Certifications"`, `"Addenda Acknowledgement"` (format: `Form Entry` inside Appendix A).
- **Embedded sections:** `"Key Personnel Profiles"`, `"Case Study References"` (format: `Integrated in response` or `Embedded in response`).
- **Workbook tabs:** `"Category Selection Tab"`, `"Service Category Rate Card Tab"`, `"Evaluated Pricing Scenario Tab"` (individual worksheets within the parent pricing workbook).
*Note:* These remain fully visible in Stage D synthesis and the Stage 2 (UNDERSTAND) view via the normalized `submission_rules` collection.

### C. Process & Format Instructions (Excluded)
Directives governing how, where, or under what formatting constraints proposals are submitted:
- **Delivery mode / portal:** `"Submit through MERX"`, `"Electronic submission only"`, `"Registration required"`.
- **Portal packaging containers:** `"Envelope 1 - Identity & Proposal"`, `"Envelope 2 - Pricing"` (format: `Electronic Bid Submission` containers on the electronic portal, which hold the component files rather than being files themselves).
- **Format & page limits:** `"Response Format and Page Limit"`, `"Maximum response length 50 pages"`, font and margin rules.
- **Checklist columns:** `"Minimum Qualification Response"` (format: `Proponent Response column (Yes/No format)`).

### D. Reference-Only Material & Restrictions (Excluded)
- **Reference documents:** `"RFP Main Document"` (details: *"Not mandatory but available for reference"*).
- **Evaluation restrictions:** `"External Links and References"` (details: *"links external to the form will not be evaluated"*).
- **Pricing rules:** `"Currency and Tax Treatment"` (rules regarding Canadian dollars and tax inclusion).

---

## 3. Implementation: Hardened Deterministic Classifier

The classifier `_is_concrete_submission_document(item, fmt, details)` and projection function `build_submission_documents(submission_rules, submission_deadline)` in `extractor.py` implement this framework deterministically (no LLM call):

1. **Word-Boundary Token Matching:**
   Replaced `if word in item_lower` with compiled regex `` word-boundary tokens (`_ARTEFACT_TOKEN_RE`). This guarantees:
   - `"form"` matches `"Submission Form"` and `"Pricing Form"`.
   - `"form"` will **NOT** match `"Proponent Information"` or `"Response Format"`.
2. **Material Format Evidence:**
   - **Exclusion triggers:** Phrases like `Form Entry`, `Integrated in response`, `Embedded in response`, `Proponent Response column`, `Yes/No confirmation`, `Electronic Bid Submission`, `Reference only` immediately exclude the item.
   - **Inclusion triggers:** Format signals like `Separate File`, `Separate Submission`, `Spreadsheet`, `PDF`, `XLSX`, `Written documentation` provide positive evidence for standalone artefacts.
3. **Workbook Tab Exclusion:**
   `_WORKBOOK_TAB_RE` (`(?:tabs?|worksheets?)`) prevents individual workbook tabs from spawning separate file checklist records.
4. **Details Inspection:**
   Examines `details` for process/reference phrases (`"available for reference"`, `"will not be evaluated"`). If reference-only intent is detected, the item is excluded regardless of title.
5. **Process wording does not erase named artefacts:**
   If an item is a clearly named concrete document (e.g., `"Technical Proposal"`, format: `PDF`), mentioning `"Submit via portal"` in the details does not erase the document.

---

## 4. End-to-End Handling of Unknown Mandatory Status

Mandatory status is strictly preserved without hallucinated defaults:

| Normalized Fact | Database / Record Value | Stage Submit UI Tag | Final Gate Impact |
|---|---|---|---|
| `mandatory = 1` | `1` | `[REQUIRED]` (Red) | Blocker if missing |
| `mandatory = 0` | `0` | `[OPTIONAL]` (Gray) | Non-blocking |
| `mandatory` absent / `None` | Key omitted (`None`) | `[UNKNOWN — resolve before submission]` (Amber) | Triggers `READY WITH WARNINGS` gate |

In `pages/stage_submit.py`:
- Documents with `mandatory=None` are **not** silently converted to `REQUIRED` (avoiding false blockers).
- Documents with `mandatory=None` are **not** silently converted to `OPTIONAL` (avoiding accidental submission of missing files).
- The gate status transitions to `READY WITH WARNINGS (Unverified Gates)` until a human reviewer resolves the status.

---

## 5. Bank of Canada Frozen Replay (boc_2026_026_normalized_facts.json)

**Source Input:** 40 normalized submission rules. No Stage A/B/C re-run, no Anthropic API call.

### Classified as Discrete Submission Documents (6):
1. **Appendix A Submission Form** (`Separate File`, mandatory=1, Submission)
2. **Pricing Form - All Applicable Sections** (`Excel Spreadsheet`, mandatory=1, Financial)
3. **Rated Criteria Response Form** (`Document`, mandatory=1, Submission)
4. **ESG Questionnaire Response** (`Spreadsheet`, mandatory=0, Submission)
5. **Bilingualism Confirmation** (`Written documentation`, mandatory=1, Submission)
6. **Security Clearance Declaration** (`Written documentation`, mandatory=1, Submission)

### Excluded Non-File Rules (34):
- **Portal packaging containers (2):** `Envelope 1 - Identity & Proposal`, `Envelope 2 - Pricing` (portal submission containers).
- **Embedded form fields (4):** `Proponent Information`, `Conflict of Interest Declaration`, `Compliance Certifications`, `Addenda Acknowledgement` (fields inside Appendix A).
- **Embedded narrative content (6):** `Key Personnel Profiles` (3 instances), `Thought Leadership Samples` (2 instances), `Case Study References` (integrated into proposal response).
- **Page limit & format rules (3):** `Response Format and Page Limit`, `Response Format`, `Response Document`.
- **Workbook tabs (4):** `Category Selection Tab`, `Service Category Rate Card Tab`, `Evaluated Pricing Scenario Tab`, `Value-Added Services Tab (Optional)` (sheets inside the pricing workbook).
- **Checklist / response columns (3):** `Minimum Qualification Requirements Response`, `Minimum Qualification Response`, `Minimum qualification requirements response` (Yes/No table columns).
- **Reference & links (3):** `RFP Main Document` (reference-only), `External Links`, `External Links and References` (not evaluated).
- **Supporting documentation notes (6):** `Resumes or Professional Profiles` (3 instances), `Work or Product Samples` (3 instances) when listed as page limit exclusions or embedded samples.
- **Pricing instructions (3):** `Currency and Tax Treatment`, `Assumptions and Restrictions Documentation`.

*Verdict:* Exact alignment with source truth. No preconceived count assertions.

---

## 6. Verification & Test Suite

```
================================================================================
FULL REGRESSION SUITE
================================================================================
1. tests/test_stage_c_refinement.py:                60 /  60 PASSED
2. tests/test_streamlined_workflow.py:              27 /  27 PASSED
3. tests/test_stage_d_completeness.py:              52 /  52 PASSED
4. tests/test_submission_document_provenance.py:    53 /  53 PASSED (NEW)
   - TestWordBoundaryMatching (cases I, J):           4 /   4
   - TestClassifierRegressions (cases A-H, tabs):    15 /  15
   - TestBuildSubmissionDocuments (cases A-H, mand): 15 /  15
   - TestBoCFrozenSubmissionReplay (semantic):       18 /  18
   - TestOrchestratorEmptyDocumentState (mocked):     1 /   1
5. tests/integration/:                              5 /   5 PASSED (1 live AI skipped)
6. tests/smoke/ + live Supabase:                   12 /  12 PASSED
================================================================================
TOTAL DISCOVERED:                                 210
TOTAL PASSED:                                     209
TOTAL SKIPPED:                                      1 (live AI integration)
TOTAL FAILED / ERRORS:                              0
================================================================================
```

---

## 7. Modified Files

| File | Changes |
|---|---|
| `extractor.py` | Hardened `_is_concrete_submission_document()` with word-boundary regex (``), format-field evidence checking, workbook tab exclusion (`_WORKBOOK_TAB_RE`), and details inspection; `build_submission_documents()` with three-state mandatory semantics (`1`, `0`, `None`). |
| `pages/stage_submit.py` | Implemented three-state mandatory gate evaluation (`REQUIRED`, `OPTIONAL`, `UNKNOWN — resolve before submission`) and warning gate status for unverified documents. |
| `pages/stage_understand.py` | Updated empty-state message to factual copy. |
| `tests/test_submission_document_provenance.py` | Comprehensive offline test suite (53 tests) covering word boundaries, format evidence, mandatory semantics, orchestrator mock, and BoC semantic replay. |
| `SUBMISSION_DOCUMENT_PROVENANCE_REPORT.md` | Full architecture and semantic classification report. |
