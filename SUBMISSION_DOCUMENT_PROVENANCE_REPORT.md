# Submission Document Provenance Report

**Branch:** `fix/submission-document-provenance`  
**Base:** `main` at `1caf136353b1853370d2a58b3fd4c5b45ab59bb3`  
**Date:** 2026-09-02

---

## 1. Original Defect: Invented Submission Documents

`extract_procurement_package()` created two default document records whenever
no documents were derived from normalized submission rules:

```python
if not documents:
    documents = [
        {"name": "Technical Proposal.pdf", "doc_type": "Submission",
         "mandatory": 1, "status": "Expected"},
        {"name": "Financial Envelope.pdf", "doc_type": "Financial",
         "mandatory": 1, "status": "Expected"},
    ]
```

These names were manufactured by the pipeline itself. They had no basis in any
source document. For procurement packages that contain explicit submission
requirements (e.g. named envelopes, specific forms), the invented defaults
masked the real documents.

Additionally, the old loop over submission rules:
- Included **every** normalized rule as a document, including process
  instructions such as "Submit through MERX" or page-limit constraints.
- Defaulted `mandatory` to `1` for any rule that did not state a mandatory
  value, inventing a mandatory status.
- Mutated document names by appending `.pdf` in the fallback.

---

## 2. Semantic Distinction: Document vs. Submission Rule

A normalized submission rule is a concrete submission **document** when it
represents a discrete, submittable artefact — a form, questionnaire, proposal,
declaration, pricing file, signed statement, or similar component.

A normalized submission rule is a **process/format instruction** when it
specifies how submission must happen (portal, deadline, registration) or
constrains the format (page limit, font, margin).

### Examples: NOT documents

| Rule Item | Reason |
|---|---|
| "Submit through MERX" | Portal instruction |
| "Electronic submission only" | Delivery mode instruction |
| "Maximum response length 50 pages" | Quantified format constraint |
| "Registration required" | Process prerequisite |
| "Response Format and Page Limit" | Format constraint |

### Examples: Concrete documents

| Rule Item | Classification |
|---|---|
| "Technical Proposal" | Submission |
| "Pricing Form" | Financial |
| "Appendix A Submission Form" | Submission |
| "Conflict of Interest Declaration" | Submission |
| "ESG Questionnaire Response" | Submission |
| "Addenda Acknowledgement" | Submission |

---

## 3. Implementation: `build_submission_documents()`

A new deterministic helper `build_submission_documents(submission_rules,
submission_deadline)` was added to `extractor.py` with supporting constants
`_DOCUMENT_INDICATOR_WORDS`, `_PROCESS_INDICATOR_WORDS`, and
`_QUANTITY_CONSTRAINT_PATTERN`.

### Detection logic (5 steps, no LLM)

1. **Process-phrase check (item)** — If any phrase from
   `_PROCESS_INDICATOR_WORDS` appears in the item text → excluded.

2. **Quantity-constraint check (item)** — If the item matches the pattern
   `(maximum|max|...) \d+ (pages|words|...)` → excluded.

3. **Document-indicator word check (item)** — If any word from
   `_DOCUMENT_INDICATOR_WORDS` appears in the item text → included.

4. **Document-indicator word check (details)** — If the details field
   contains an indicator word and the item was otherwise ambiguous → included.

5. **Conservative default** — If none of the above match → excluded.
   No document is invented.

### Provenance rules

- **Name:** The normalized `item` text is used as-is. `.pdf` or any other
  extension is NOT appended unless the source text already contains it.
- **mandatory:** Taken from the normalized fact as-is. If absent, the key is
  omitted from the output record — not defaulted to `1`.
- **doc_type:** Classified as `Financial` when the item contains `pricing`,
  `financial`, `rate card`, or `cost`; otherwise `Submission`.
- **Empty result:** A valid state meaning "no concrete submission documents
  were established from the normalized facts." The pipeline does not create
  placeholder documents.

---

## 4. Empty-State Behavior

- `documents = []` is valid throughout the ingestion and database flow.
  `upsert_document()` is called zero times — no error.
- UI empty-state messages updated to factual text:
  - `stage_submit.py`: *"No explicit submission documents were identified in
    the procurement package. Upload submission files below or add them
    manually."*
  - `stage_understand.py`: *"No explicit submission documents were identified
    in the procurement package."*
- Neither message implies the bidder should create a technical or financial
  proposal. No placeholder names are suggested.

---

## 5. Mandatory-Status Handling

| Scenario | Old behavior | New behavior |
|---|---|---|
| `mandatory` present = 1 | passed through | passed through |
| `mandatory` present = 0 | passed through | passed through |
| `mandatory` absent | defaulted to `1` | key omitted from record |

The `mandatory` key is only written when supported by the normalized facts.

---

## 6. Bank of Canada Frozen Submission Document Replay

**Fixture:** `tests/acceptance/results/boc_2026_026_normalized_facts.json`  
**No Stage A/B/C re-run. No Anthropic call.**

| Metric | Value |
|---|---|
| Total normalized submission rules | 40 |
| Classified as concrete documents | 39 |
| Excluded (non-document process rules) | 1 |

**Excluded rule:**

| Item | Reason |
|---|---|
| "Response Format and Page Limit" | Combined format/page-limit constraint |

**Notable concrete documents extracted (representative sample):**

| Document Name | doc_type | mandatory |
|---|---|---|
| Envelope 1 - Identity & Proposal | Submission | 1 |
| Envelope 2 - Pricing | Financial | 1 |
| Appendix A Submission Form | Submission | 1 |
| Pricing Form - All Applicable Sections | Financial | 1 |
| Evaluated Pricing Scenario Tab | Financial | 1 |
| Conflict of Interest Declaration | Submission | 1 |
| ESG Questionnaire Response | Submission | 0 |
| Case Study References | Submission | 1 |
| Bilingualism Confirmation | Submission | 1 |
| Addenda Acknowledgement | Submission | 1 |

No `Technical Proposal.pdf` or `Financial Envelope.pdf` invented.  
All mandatory values sourced from normalized facts (no defaulting).  
No `.pdf` extension appended to any document name.

**Verdict: PASS**

---

## 7. Test Matrix

```
================================================================================
FULL REGRESSION SUITE (post-submission-document-provenance)
================================================================================
1. tests/test_stage_c_refinement.py:                60 /  60 PASSED
2. tests/test_streamlined_workflow.py:              27 /  27 PASSED
3. tests/test_stage_d_completeness.py:              52 /  52 PASSED
4. tests/test_submission_document_provenance.py:    35 /  35 PASSED (NEW)
   TestSubmissionDocumentProvenance (cases A-H):   17 / 17
   TestIsConcreteSubmissionDocument (predicate):   11 / 11
   TestBoCFrozenSubmissionReplay:                   7 /  7
5. tests/integration/:                              5 /   5 PASSED (1 live AI skipped)
6. tests/smoke/ + live Supabase:                   12 /  12 PASSED
================================================================================
TOTAL DISCOVERED:                                 192
TOTAL PASSED:                                     191
TOTAL SKIPPED:                                      1 (live AI integration)
TOTAL FAILED / ERRORS:                              0
================================================================================
```

---

## 8. Files Changed

| File | Change |
|---|---|
| `extractor.py` | Added `_DOCUMENT_INDICATOR_WORDS`, `_PROCESS_INDICATOR_WORDS`, `_QUANTITY_CONSTRAINT_PATTERN`, `_is_concrete_submission_document()`, `build_submission_documents()`; replaced old document loop + invented-default fallback in `extract_procurement_package()` |
| `pages/stage_submit.py` | Updated empty-state message to factual text |
| `pages/stage_understand.py` | Updated empty-state message to factual text |
| `tests/test_submission_document_provenance.py` | New: 35 deterministic tests covering cases A-H, predicate unit tests, and BoC frozen replay |

Not changed: Stage A, Stage B, Stage C, Stage D, database schema,
migrations 001/002/003, submission gating doctrine, five-stage workflow,
RC1 tag, frozen Bank of Canada acceptance artifacts.

---

## 9. Known Out-of-Scope Limitation

The BoC fixture contains duplicate submission-rule items that normalize to the
same item name (e.g. "Key Personnel Profiles" appears three times with
different formats per envelope). These produce distinct document records since
their details differ. Deduplication of same-name submission documents across
envelopes is not addressed in this branch — that is a separate concern for a
future focused branch.
