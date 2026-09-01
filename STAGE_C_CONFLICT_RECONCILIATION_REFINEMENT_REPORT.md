# BID INTELLIGENCE — STAGE C CONFLICT RECONCILIATION REFINEMENT REPORT

**Project:** Bid Intelligence  
**Branch:** `fix/stage-c-conflict-reconciliation`  
**Base Commit:** `089546e709500bfc68c265e50e494cad109bc9ae` (Bid Intelligence RC1 on `main`)  
**Status:** **READY FOR PR REVIEW**

---

## 1. Executive Summary

Following the merge of Bid Intelligence RC1 to `main` and subsequent quality reviews, this patch refines the **Stage C Cross-Document Reconciliation Engine** (`extractor.py::detect_document_conflicts` and `extractor.py::reconcile_package_facts`).

The refinement:
1. Eliminates false-positive candidate discrepancies identified during the Bank of Canada RFP 2026-026 blind acceptance test.
2. Introduces mandatory requirement **scope normalization** so differing criteria across distinct service categories (e.g. Category 1 vs Category 2) are recognized as complementary rather than contradictory.
3. Implements strict priority-ordered **security clearance classification** (`TOP_SECRET` $\rightarrow$ `SECRET` $\rightarrow$ `RELIABILITY`).
4. Introduces normalized **monetary amount extraction** for commercial insurance limits (comparing `$2M` vs `$2,000,000` with varying prose without false positives).
5. Handles **internal document date inconsistencies** as `REVIEW_ITEM`.
6. Audits conflict citations against physical package files.

All changes strictly preserve the RC1 architecture, extraction prompts, submission gating, and database schema (Migration 003) with zero breaking changes.

---

## 2. RC1 Known Failure Modes & Root Cause Analysis

During the RC1 blind acceptance test against Bank of Canada RFP 2026-026, 3 candidate conflicts were generated:

| RC1 Conflict ID | Topic | RC1 Classification | Assessment in RC1 Review | Root Cause & Resolution |
| :--- | :--- | :--- | :--- | :--- |
| `CONF-DATE-1` | Question Deadline (Sep 10) vs Closing Date (Sep 30) | `DATE_CONFLICT` | **False Positive** | Substring filter matched `"deadline"` in Question Acceptance Deadline before checking for `"question"`, grouping both under `submission_deadline`. Resolved via semantic event priority mapping. |
| `CONF-SUB-2` | Electronic Submission vs Excel Spreadsheet | `SUBMISSION_RULE_CONFLICT` | **False Positive** | Rule formats were compared globally across documents without distinguishing transmission channels from file format types. Resolved via submission dimension classification. |
| `CONF-MAND-3` | Appendix B3 Bilingual Gate vs General Scope | `MANDATORY_REQUIREMENT_CONFLICT` | **Heuristic Artifact** | An ad-hoc keyword check searched for `"bilingual"` and flagged an untyped conflict against a synthesized `"General RFP Overview"` label because the requirement appeared in fewer than all documents. Removed in favor of generic, scope-aware criteria reconciliation. |

---

## 3. Semantic Event Model (Date Classification)

Dates extracted in Stage B are classified using priority-ordered regex patterns in `classify_date_milestone()`:

```python
DATE_EVENT_PATTERNS = [
    ("QUESTION_DEADLINE", [r"question", r"clarification", r"enquir", r"inquir", r"rfi", r"q&a", ...]),
    ("INTENT_TO_BID_DATE", [r"intent\s+to\s+bid", r"bid\s+intent", r"confirmation\s+of\s+intent", ...]),
    ("PUBLICATION_DATE", [r"solicitation\s+publication", r"publication\s+date", r"date\s+issued", ...]),
    ("AMENDMENT_DATE", [r"amendment\s+no", r"amendment\s+published", r"addendum\s+published", ...]),
    ("EXPERIENCE_TIMEFRAME", [r"recent\s+engagements", r"experience\s+timeframe", ...]),
    ("SITE_VISIT_DATE", [r"site\s+visit", r"site\s+walkthrough", r"bidders\s+conference", ...]),
    ("PRESENTATION_DATE", [r"presentation", r"interview", r"demonstration", r"oral", ...]),
    ("AWARD_DATE", [r"award", r"selection", r"intent\s+to\s+award", r"notification\s+of\s+award", ...]),
    ("CONTRACT_START", [r"contract\s+start", r"commencement", r"start\s+date", ...]),
    ("CONTRACT_END", [r"contract\s+end", r"completion", r"expiry", r"expiration", ...]),
    ("VALIDITY_DATE", [r"validity", r"valid\s+until", r"proposal\s+valid", ...]),
    ("SUBMISSION_DEADLINE", [r"submission", r"closing", r"due\s+date", r"rfp\s+due", r"tender\s+close", ...])
]
```

**Reconciliation Rules:**
- Dates are only compared when they share the exact same actionable semantic milestone.
- **Cross-Document Contradiction:** Differing dates across distinct physical documents for the same milestone $\rightarrow$ `classification: TRUE_CONFLICT`.
- **Same-Document Inconsistency:** Differing dates within the same physical document for the same milestone $\rightarrow$ `classification: REVIEW_ITEM` (reason: internal source inconsistency).
- Sequential milestones across different events are suppressed.

---

## 4. Mandatory Requirement Scope Normalization & Clearance Priority

### A. Scope Normalization
Requirements are partitioned by operational scope using `_extract_requirement_scope()`:
- `CATEGORY_1`, `CATEGORY_2`, `CATEGORY_3`, `STREAM_1`, `STREAM_2`, `STREAM_3`, or `GENERAL_SCOPE`.

Thresholds (e.g. years of experience or certifications) are only compared when they apply to the **same operational scope**:
- Category 1 (5 years) vs Category 2 (10 years) $\rightarrow$ `NO CONFLICT` (independent work streams).
- Category 1 (5 years) vs Category 1 Addendum (10 years) $\rightarrow$ `TRUE CONFLICT` (direct contradiction).

### B. Security Clearance Priority
Clearance requirements are classified with strict priority:
1. `TOP_SECRET` (checked first)
2. `SECRET` (checked second)
3. `RELIABILITY` (checked third)

---

## 5. Dimension Normalization Model (Submission Rules)

Submission rules are classified using `classify_submission_rule_dimension()` into operational dimensions:

1. `ENVELOPE_STRUCTURE`: Separate vs Combined proposal packages.
2. `PAGE_LIMIT`: Response page caps (excluding per-sample, resume, or profile sub-caps; partitioned by service category).
3. `SUBMISSION_CHANNEL`: MERX / BuyAndSell portal upload vs Direct Email vs Physical Courier.
4. `PORTAL_REQUIREMENT`: Vendor registration, e-procurement digital keys.
5. `SIGNATURE_REQUIREMENT`: Authorized signing officer, digital signatures.
6. `FILE_FORMAT`: PDF, DOCX, XLSX, searchable PDF.
7. `DOCUMENT_REQUIREMENT`: Specific form checklists (Appendix A, ESG questionnaire, Pricing Form).

**Comparison Rules:**
- Only rules belonging to the **same operational dimension** are compared.
- Complementary rules (e.g. `SUBMISSION_CHANNEL` + `FILE_FORMAT`) are suppressed.
- Direct contradictions within a dimension (e.g. `MERX` vs `Email Only`, or `Separate Envelopes` vs `Single Combined PDF`) trigger `TRUE_CONFLICT`.

---

## 6. Like-With-Like Commercial & Insurance Normalization

Commercial insurance clauses are categorized using `classify_insurance_class()` into standardized coverage classes:
- `COMMERCIAL_GENERAL_LIABILITY` (CGL, general liability, comprehensive liability)
- `PROFESSIONAL_LIABILITY` (E&O, errors and omissions, professional indemnity)
- `CYBER_LIABILITY` (cyber, data breach, network security)
- `AUTOMOBILE_LIABILITY` (motor vehicle, fleet)
- `WORKERS_COMPENSATION` (workers comp, WSIB)

### Monetary Limit Parsing
Monetary thresholds are extracted via `extract_monetary_amount()`:
- `$2,000,000` and `$2M including bodily injury` both normalize to `2000000.0` $\rightarrow$ `NO CONFLICT`.
- `$2M` vs `$5M` within the same insurance class $\rightarrow$ `classification: TRUE_CONFLICT`.
- If amounts cannot be reliably parsed but wording varies $\rightarrow$ `classification: REVIEW_ITEM` (no spurious `TRUE_CONFLICT` based purely on prose differences).

---

## 7. Source Validity & Provenance Grounding Architecture

Every candidate conflict or review item is audited against `package_files` via `validate_conflict_source_validity()`:

* **`PHYSICAL_BOTH`**: Both cited filenames resolve to physical package files in `package_files`. Eligible for `classification: TRUE_CONFLICT`. *(Note: Validates physical filename presence in procurement package; does not perform coordinate-level source_refs validation).*
* **`PHYSICAL_PARTIAL`**: One source is a physical document and one source is a package-level overview or scope observation. Automatically classified as `classification: REVIEW_ITEM`.
* **`SYNTHESIZED`**: Neither source is a verified physical file. Automatically downgraded or suppressed.

---

## 8. Output Model & Schema Compatibility

The output model maintains 100% backward compatibility with Supabase Migration 003, JSONB columns, and UI pages while adding new rich metadata:

```json
{
  "conflict_id": "CONF-DATE-1",
  "conflict_type": "DATE_CONFLICT",
  "classification": "TRUE_CONFLICT",
  "confidence": "HIGH",
  "reason": "Conflicting dates detected for the same semantic milestone (Submission Deadline) across documents.",
  "source_validity": "PHYSICAL_BOTH",
  "topic": "Differing dates for Submission Deadline",
  "source_a": {"doc": "Main_RFP.pdf", "ref": "Bid Closing Date", "text": "2026-09-15"},
  "source_b": {"doc": "Addendum_1.pdf", "ref": "Bid Closing Date", "text": "2026-09-30"},
  "assessment": "Conflicting target dates detected across documents: 2026-09-15, 2026-09-30.",
  "recommended_action": "Verify if the latest Addendum or Bulletin formally extends this deadline."
}
```

---

## 9. Verification Test Suite Matrix

```
================================================================================
FULL RC1 + STAGE C TEST SUITE EXECUTION SUMMARY
================================================================================
1. tests/test_stage_c_refinement.py:             22 / 22 PASSED  (0.012s)
   • Bank of Canada Regression Tests (A, B, C):   3 / 3 PASSED
   • Mandatory Scope Normalization Tests:         2 / 2 PASSED
   • Security Clearance Priority Tests:           3 / 3 PASSED
   • Insurance Monetary Normalization Tests:      4 / 4 PASSED
   • Same-Document Date Inconsistency Test:       1 / 1 PASSED
   • Positive True Conflict Tests (A, B, C, E):   4 / 4 PASSED
   • Source Validity & Provenance Tests:          4 / 4 PASSED
   • Frozen Bank of Canada Replay Test:           1 / 1 PASSED
2. tests/test_streamlined_workflow.py:            27 / 27 PASSED  (0.242s)
3. tests/integration/test_package_ingestion.py:    5 / 5 PASSED   (1 skipped live AI)
4. tests/smoke/test_live_supabase_migration_003:   5 / 5 PASSED   (25.055s)
5. tests/smoke/test_all_pages_runtime.py:          7 / 7 PASSED   (28.464s)
================================================================================
TOTAL TESTS DISCOVERED:                          67
TOTAL PASSED:                                    66
TOTAL SKIPPED:                                   1 (Live AI integration smoke)
TOTAL FAILED / ERRORS:                           0
================================================================================
```

---

## 10. Bank of Canada Frozen Replay Summary

Replaying `reconcile_package_facts()` against `tests/acceptance/results/boc_2026_026_normalized_facts.json`:

* **RC1 Pre-Refinement Discrepancies:** 3 candidates (2 false positives, 1 heuristic artifact)
* **Refined Stage C Discrepancies:** 0 candidates
* **Precision Assessment:** **0 known false positives remained in the frozen Bank of Canada replay.**

Documented in detail in: `tests/acceptance/results/STAGE_C_RC1_RECONCILIATION_REPLAY.md`.

---

## 11. Final Recommendation

```
================================================================================
FINAL VERDICT: READY FOR PR REVIEW
================================================================================
Branch fix/stage-c-conflict-reconciliation has passed all deterministic regression
tests, scope normalization tests, security clearance priority verifications,
monetary parsing tests, provenance audits, live Supabase checks, UI runtime
executions, and frozen Bank of Canada replay verifications.

Ready for PR review.
================================================================================
```
