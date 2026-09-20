# BID INTELLIGENCE — STAGE C CONFLICT RECONCILIATION REFINEMENT REPORT

**Project:** Bid Intelligence  
**Branch:** `fix/stage-c-conflict-reconciliation`  
**Base Commit:** `089546e709500bfc68c265e50e494cad109bc9ae` (Bid Intelligence RC1 on `main`)  
**Status:** **READY FOR PR RE-REVIEW**

---

## 1. Executive Summary

Following the initial PR review for Stage C cross-document reconciliation, this patch remediates all code review findings across `extractor.py::detect_document_conflicts` and `extractor.py::reconcile_package_facts`.

Key remediations implemented:
1. **Evaluation Criteria — Compare Same Metric Only:** Only compare weights and point allocations when records represent the *same* normalized evaluation metric or criterion identity (overall technical weight, specific criterion identity, e.g., methodology, team experience, corporate track record). Distinct criteria (e.g. Technical Approach 30 pts vs Team Experience 20 pts) are not compared.
2. **Mandatory Requirement Subject Identity:** Requirements are partitioned not only by operational category/stream scope but also by normalized role/subject identity (`ROLE_PROJECT_MANAGER`, `ROLE_FACILITATOR`, `ROLE_EXECUTIVE_COACH`, `SUBJECT_BIDDER_CORPORATE`, or specific requirement references). Different thresholds for different roles within the same category are recognized as complementary.
3. **Source-Aware Opposing Pair Selection:** `select_opposing_pair()` enforces that selected opposing records belong to different physical documents (`source_a.doc != source_b.doc`) for cross-document `TRUE_CONFLICT`. If contradictory values exist within the same document, they are isolated as internal inconsistencies (`REVIEW_ITEM`).
4. **Submission Dimension Precedence:** `PORTAL_REQUIREMENT` patterns (e.g. `"merx registration required"`, `"maintain a MERX account"`) evaluate strictly before generic `SUBMISSION_CHANNEL` patterns (e.g. `"merx"`), avoiding spurious channel conflicts against email-only transmission.
5. **Scope / Deliverable Identity Normalization:** Deliverables are reconciled like-with-like based on deliverable identity and normalized `(quantity, unit)`. Distinct deliverable types (e.g. Leadership cohort: 20 participants vs Executive coaching: 10 sessions) produce no conflict.
6. **Panel & Commercial Cap Normalization:** Commercial terms are partitioned by specific commercial topic (`PANEL_VENDOR_CAP`, `RATE_CAP`, `ANNUAL_ESCALATION_CAP`, `CONTRACT_VALUE_CAP`, `INSURANCE_REQUIREMENT`, `OTHER_COMMERCIAL_TERM`). Differing types of commercial caps are not compared against each other.
7. **Documentation Integrity:** All local Windows file URIs have been removed from committed release documentation.

All changes strictly preserve the RC1 architecture, extraction prompts, submission gating, and database schema (Migration 003).

---

## 2. RC1 Known Failure Modes & Root Cause Analysis

During the RC1 blind acceptance test against Bank of Canada RFP 2026-026, 3 candidate conflicts were generated:

| RC1 Conflict ID | Topic | RC1 Classification | Assessment in RC1 Review | Root Cause & Resolution |
| :--- | :--- | :--- | :--- | :--- |
| `CONF-DATE-1` | Question Deadline (Sep 10) vs Closing Date (Sep 30) | `DATE_CONFLICT` | **False Positive** | Substring filter matched `"deadline"` in Question Acceptance Deadline before checking for `"question"`, grouping both under `submission_deadline`. Resolved via semantic event priority mapping. |
| `CONF-SUB-2` | Electronic Submission vs Excel Spreadsheet | `SUBMISSION_RULE_CONFLICT` | **False Positive** | Rule formats were compared globally across documents without distinguishing transmission channels from file format types. Resolved via submission dimension classification. |
| `CONF-MAND-3` | Appendix B3 Bilingual Gate vs General Scope | `MANDATORY_REQUIREMENT_CONFLICT` | **Heuristic Artifact** | An ad-hoc keyword check searched for `"bilingual"` and flagged an untyped conflict against a synthesized `"General RFP Overview"` label because the requirement appeared in fewer than all documents. Removed in favor of generic, scope-aware criteria reconciliation. |

---

## 3. Source-Aware Opposing Pair Selection (`select_opposing_pair`)

In multi-source packages with 3+ records containing duplicate values (e.g., Doc A: 10 pages, Doc B: 15 pages, Doc C: 10 pages), detectors must guarantee that `source_a` and `source_b` display differing values AND originate from differing physical documents.

The helper in `extractor.py::select_opposing_pair` supports source awareness:

```python
def select_opposing_pair(
    records: list,
    value_fn,
    source_fn=None,
    require_different_sources: bool = False
) -> tuple | None:
    """
    Find two records record_a and record_b such that value_fn(record_a) != value_fn(record_b).
    If require_different_sources=True and source_fn is provided, also enforces source_fn(record_a) != source_fn(record_b).
    Returns (record_a, record_b) or None if no such pair exists.
    """
```

**Applied Across All Reconciliation Modules:**
- `DATE_CONFLICT`: Selects records representing differing dates across distinct documents; same-document date discrepancies are isolated as `REVIEW_ITEM`.
- `EVALUATION_CONFLICT`: Selects records representing differing weights for the exact same evaluation metric.
- `PAGE_LIMIT`: Selects records representing differing page limits across distinct files.
- `MANDATORY_REQUIREMENT_CONFLICT`: Selects records representing differing thresholds for the same role/subject within the same category.
- `COMMERCIAL_TERM_CONFLICT`: Selects records representing differing caps or insurance limits for the same commercial term.
- `SCOPE_CONFLICT`: Selects records representing differing deliverable quantities for the same deliverable identity.

For every cross-document `TRUE_CONFLICT`, `source_a.text != source_b.text` AND `source_a.doc != source_b.doc` are guaranteed.

---

## 4. Evaluation Criteria — Same Metric Only

Evaluation criteria are normalized using `_extract_eval_criterion_identity()`:
- `OVERALL_TECHNICAL_WEIGHT`: Overall technical/financial ratio (e.g. 70/30 vs 75/25, or 75 pts vs 70 pts total technical score).
- `CRITERION_METHODOLOGY`: Technical approach, methodology, work plan.
- `CRITERION_TEAM_EXPERIENCE`: Team experience, key personnel, resource qualifications.
- `CRITERION_CORPORATE_EXPERIENCE`: Firm track record, past performance, company experience.
- `CRITERION_FINANCIAL_WEIGHT`: Pricing, cost, financial scoring weight.
- `CRITERION_PRESENTATION_WEIGHT`: Interview, oral presentation, demonstration.
- `CRITERION_INDIGENOUS_WEIGHT`: Procurement strategy for Indigenous business (PSAB / PSIB).
- `CRITERION_ESG_WEIGHT`: Sustainability, environmental score.

**Reconciliation Rules:**
- Technical Approach = 30 points vs Team Experience = 20 points $\rightarrow$ `NO CONFLICT` (distinct criteria).
- Overall Technical Weight = 75% vs Overall Technical Weight = 70% $\rightarrow$ `TRUE_CONFLICT` (same metric).
- Criterion Methodology = 25 points vs Methodology = 30 points $\rightarrow$ `TRUE_CONFLICT` (same criterion).

---

## 5. Mandatory Requirement Subject Identity & Clearance Priority

### A. Scope and Subject Normalization
Requirements are partitioned by operational scope (`_extract_requirement_scope()`) and role/subject identity (`_extract_requirement_subject()`):
- **Scopes:** `CATEGORY_1`, `CATEGORY_2`, `CATEGORY_3`, `STREAM_1`, `STREAM_2`, `STREAM_3`, `GENERAL_SCOPE`.
- **Subjects:** `ROLE_PROJECT_MANAGER`, `ROLE_FACILITATOR`, `ROLE_EXECUTIVE_COACH`, `ROLE_SENIOR_ADVISOR`, `ROLE_CONSULTANT`, `ROLE_INSTRUCTIONAL_DESIGNER`, `SUBJECT_BIDDER_CORPORATE`, or specific requirement references (`REF_M1`, `REF_M2`).

**Reconciliation Rules:**
- Category 1 Project Manager (10 yrs) vs Category 1 Facilitator (5 yrs) $\rightarrow$ `NO CONFLICT` (different roles).
- Category 1 Project Manager (10 yrs) vs Category 1 Addendum Project Manager (7 yrs) $\rightarrow$ `TRUE_CONFLICT` (same role, same category).
- Project Manager (Secret) vs Consultant (Reliability) $\rightarrow$ `NO CONFLICT` (different roles).
- Project Manager (Secret) vs Project Manager (Top Secret) $\rightarrow$ `TRUE_CONFLICT` (same role).

### B. Security Clearance Priority
Clearance levels are classified using `classify_security_clearance()` with strict priority:
1. `TOP_SECRET` (checked first)
2. `SECRET` (checked second)
3. `RELIABILITY` (checked third)

---

## 6. Dimension Normalization Model & Precedence (Submission Rules)

Submission rules are classified using `classify_submission_rule_dimension()` with strict pattern precedence:

1. `ENVELOPE_STRUCTURE`: Separate vs Combined proposal packages.
2. `PAGE_LIMIT`: Response page caps (excluding per-sample, resume, or profile sub-caps; partitioned by service category).
3. `PORTAL_REQUIREMENT`: Vendor registration, MERX account setup, digital keys (evaluated *before* generic submission channel patterns).
4. `SUBMISSION_CHANNEL`: Portal bid upload vs Email submission only vs Physical courier delivery.
5. `SIGNATURE_REQUIREMENT`: Authorized signing officer, digital signatures.
6. `FILE_FORMAT`: PDF, DOCX, XLSX, searchable PDF.
7. `DOCUMENT_REQUIREMENT`: Specific form checklists (Appendix A, ESG questionnaire, Pricing Form).

**Reconciliation Rules:**
- `"MERX registration required"` $\rightarrow$ `PORTAL_REQUIREMENT`.
- `"MERX registration required"` + `"Submit proposal by email only"` $\rightarrow$ `NO CONFLICT` (portal setup does not contradict email transmission).
- `"Upload bid through MERX"` + `"Submit proposal by email only"` $\rightarrow$ `TRUE_CONFLICT` (contradictory transmission channels).

---

## 7. Like-With-Like Commercial Caps & Insurance Normalization

### A. Commercial Cap Normalization
Commercial clauses are classified into standardized topics via `classify_commercial_topic()`:
- `PANEL_VENDOR_CAP`: Maximum standing offer suppliers or panel awards.
- `RATE_CAP`: Maximum per diem or hourly rate caps.
- `ANNUAL_ESCALATION_CAP`: Maximum annual rate increase percentage.
- `CONTRACT_VALUE_CAP`: Maximum total expenditure or contract ceiling.
- `INSURANCE_REQUIREMENT`: Commercial insurance coverage.
- `OTHER_COMMERCIAL_TERM`: General commercial conditions.

**Reconciliation Rules:**
- Max panel vendors = 5 vs Max annual rate increase = 3% $\rightarrow$ `NO CONFLICT` (differing commercial topics).
- Max panel vendors = 5 vs Max panel vendors = 8 $\rightarrow$ `TRUE_CONFLICT` (contradictory panel caps).

### B. Insurance Coverage & Monetary Limit Parsing
Insurance clauses are classified via `classify_insurance_class()` (`COMMERCIAL_GENERAL_LIABILITY`, `PROFESSIONAL_LIABILITY`, `CYBER_LIABILITY`, `AUTOMOBILE_LIABILITY`, `WORKERS_COMPENSATION`).
- Monetary limits are parsed using `extract_monetary_amount()`: `$2M` and `$2,000,000` both normalize to `2000000.0` $\rightarrow$ `NO CONFLICT`.
- CGL `$2M` vs CGL `$5M` $\rightarrow$ `TRUE_CONFLICT`.
- Isolated years (e.g. `"Policy effective in 2026"`, `"RFP 2026-026"`) are protected from being parsed as monetary amounts.

---

## 8. Like-With-Like Deliverable Scope Reconciliation

Deliverables are normalized by identity (`_extract_deliverable_identity()`) and quantity/unit (`_extract_deliverable_quantity()`):
- `DELIVERABLE_COHORT`: Training cohorts, leadership cohorts.
- `DELIVERABLE_EXECUTIVE_COACHING`: Executive coaching sessions/hours.
- `DELIVERABLE_WORKSHOP`: Workshops, seminars.
- `DELIVERABLE_ADVISORY_REPORT`: Advisory assessments, evaluation reports.

**Reconciliation Rules:**
- Leadership cohort (20 participants) vs Executive coaching (10 sessions) $\rightarrow$ `NO CONFLICT` (distinct deliverable types).
- Leadership cohorts (20 cohorts) vs Leadership cohorts (12 cohorts) $\rightarrow$ `TRUE_CONFLICT` (differing quantities for the same deliverable).

---

## 9. Source Validity & Provenance Grounding Architecture

Every candidate conflict is audited against `package_files` via `validate_conflict_source_validity()`:
* **`PHYSICAL_BOTH`**: Both cited filenames resolve to physical files in `package_files`. Eligible for `classification: TRUE_CONFLICT`.
* **`PHYSICAL_PARTIAL`**: One source is a physical document and one source is a package-level overview or scope observation. Automatically classified as `classification: REVIEW_ITEM`.
* **`SYNTHESIZED`**: Neither source is a verified physical file. Automatically downgraded or suppressed.

---

## 10. Verification Test Suite Matrix

```
================================================================================
FULL RC1 + STAGE C TEST SUITE EXECUTION SUMMARY
================================================================================
1. tests/test_stage_c_refinement.py:             60 / 60 PASSED  (0.021s)
   • Bank of Canada Regression Tests (A, B, C):   3 / 3 PASSED
   • Evaluation Criteria Same-Metric & ID Tests:  8 / 8 PASSED
   • Mandatory Subject & Role Identity Tests:     6 / 6 PASSED
   • Source-Aware Opposing Pair Selection Tests:  7 / 7 PASSED
   • Internal Commercial/Insurance/Deliverable Tests: 3 / 3 PASSED
   • Submission Dimension Precedence Tests:       3 / 3 PASSED
   • Scope Deliverable Identity & Scope Tests:    4 / 4 PASSED
   • Commercial Cap Normalization Tests:          3 / 3 PASSED
   • Security Clearance Priority Tests:           1 / 1 PASSED
   • Insurance Monetary Normalization Tests:      4 / 4 PASSED
   • Source Validity & Provenance Tests:          3 / 3 PASSED
   • Pipeline-Realistic Integration Test:         1 / 1 PASSED
   • Frozen Bank of Canada Replay Test:           1 / 1 PASSED
   • Generic Scope Extraction Tests (NEW):       13 / 13 PASSED
2. tests/test_streamlined_workflow.py:            27 / 27 PASSED  (0.257s)
3. tests/integration/test_procurement_package_ingestion.py: 5 / 5 PASSED (1 skipped live AI)
4. tests/smoke/test_all_pages_runtime.py + live Supabase:  12 / 12 PASSED (62.130s)
================================================================================
TOTAL TESTS DISCOVERED:                         105
TOTAL PASSED:                                   104
TOTAL SKIPPED:                                    1 (Live AI integration smoke)
TOTAL FAILED / ERRORS:                            0
================================================================================
```

---

## 11. Bank of Canada Frozen Replay Summary

Replaying `reconcile_package_facts()` against `tests/acceptance/results/boc_2026_026_normalized_facts.json`:

* **RC1 Pre-Refinement Discrepancies:** 3 candidates (2 false positives, 1 heuristic artifact)
* **Refined Stage C Discrepancies:** 0 candidates (`[]`)
* **Precision Assessment:** **0 known false positives remained in the frozen Bank of Canada replay.**

Documented in detail in: `tests/acceptance/results/STAGE_C_RC1_RECONCILIATION_REPLAY.md`.

---

## 12. Final Verdict

```
================================================================================
FINAL VERDICT: READY FOR FINAL PR APPROVAL
================================================================================
Branch fix/stage-c-conflict-reconciliation has passed all deterministic regression
tests, evaluation metric isolation tests, mandatory subject identity checks,
source-aware pair selection verifications, internal inconsistency handling for
envelopes, channels, commercial terms, insurance and deliverables, pipeline-realistic
integration tests, live Supabase checks, and the frozen Bank of Canada replay.

Ready for final PR approval.
================================================================================
```
