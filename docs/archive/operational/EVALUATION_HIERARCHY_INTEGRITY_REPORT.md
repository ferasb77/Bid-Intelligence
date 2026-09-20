# EVALUATION HIERARCHY & WEIGHTING INTEGRITY — VERIFICATION & AUDIT REPORT

**Date:** 2026-09-04  
**Repository:** `ferasb77/Bid-Intelligence`  
**Branch:** `fix/evaluation-hierarchy-integrity`  
**Base Commit:** `712111297124e861d676b174bd66c3d31c1ac49c` (PR #8 merged)  
**Replay Code SHA:** `6ff7e7a2a49e7d244fd146d006e03c53bd772ccd`  
**Status:** REMEDIATED, HARDENED, TESTED & REPLAY VERIFIED — READY FOR PR REVIEW  

---

## 1. Executive Summary & Defect Remediation

### 1.1 Root Cause of the Original Defect (140% / 160% Double-Counting)
The evaluation model previously flattened all extracted evaluation criteria into a single list and computed overall evaluation weights by summing every row indiscriminately.
In complex procurement packages like the British Council benchmark:
- Scored award criteria (Social Value 10%, Experience 15%, Scope/Delivery 35%, Commercial 40%) were extracted alongside summary headings or sub-components (e.g., Commercial 40% and Pricing Approach 40%, or scoring scale points 10, 7, 5, 3, 0).
- Flattening these elements resulted in an erroneous overall total of 140% or 160%, double-counting parent allocations and treating nested/scale metrics as top-level overall weights.

### 1.2 Final PR Provenance, Orphan Subcriteria & Container Pass
In this final PR provenance, orphan, and container pass, generic safety corrections were addressed, tested, and verified:
1. **Orphan Subcriteria Unresolved (Pass 1):** In `build_evaluation_hierarchy()`, if `evaluation_role == Subcriterion` and has no resolved parent (`not pid and not pname`), it is placed into `hierarchy["unresolved"]` with reason `"Subcriterion has no resolved parent."`, driving status to `UNRESOLVED_HIERARCHY`. Orphan subcriteria are never promoted to root award contribution. Unknown roots claiming numeric `Overall` weight trigger `SOURCE_DISCREPANCY` (unresolved overall weighting), while known non-additive roles (Process, Qualification, Scoring) remain authoritative and non-blocking.
2. **Structural Container Additive Filtering (Pass 2):** A structural container derives overall contribution exclusively from pure additive children (`Award Criterion` or confirmed `Subcriterion`, conflict-free, `weight_basis == Overall`, compatible unit). Non-additive unweighted children are preserved in `child_details` without blocking derivation. Non-additive children with numeric weights, conflicted children, or Unknown children with numeric weights trigger `SOURCE_DISCREPANCY` and block `VALID` status derivation.
3. **Preserve Evaluation Conflict History across Stage A → Stage B:** `normalize_evaluation_criterion()` preserves and unions incoming `role_observations`, `weight_observations`, `role_conflict`, and `weight_conflict`. A true conflict detected in Stage A is never cleared or downgraded to `False` by a later Stage B re-normalization or consistent observation. When `role_conflict == True`, the role remains `ROLE_UNKNOWN` without erroneous re-inference.
4. **Committed SHA Benchmark Verification & Integrity:** The live British Council replay was executed against the exact committed code SHA (`6ff7e7a2a49e7d244fd146d006e03c53bd772ccd`). The working tree had zero uncommitted code changes during replay execution.

---

## 2. Benchmark Comparison: Current vs Corrected Replay

| Metric / Dimension | Initial Attempt Replay (`92451a6`) | Safety Pass Replay (`3a73b01`) | Final PR Provenance Replay (`6ff7e7a`) | Acceptance Criteria Met? |
|---|---|---|---|---|
| **Code SHA** | `92451a6d8a579b768added7fec68774f23f836c1` | `3a73b01b5a856afc32b5e3934c80a6590e7ff6eb` | **`6ff7e7a2a49e7d244fd146d006e03c53bd772ccd`** | **YES** |
| **Pipeline Status** | `UNRESOLVED_HIERARCHY` (FAILED) | `VALID` | **`VALID`** | **YES** |
| **Overall Award Total** | `null` | `100.0%` | **`100.0%`** | **YES** (Clean 100%) |
| **Overall Unit** | `None` | `Percent` | **`Percent`** | **YES** |
| **Unresolved Count** | 13 unresolved | 0 unresolved | **0 unresolved** | **YES** (All resolved) |
| **Root Count** | 0 roots (all orphan) | 13 structured roots | **14 structured roots** | **YES** |
| **Award Criteria Container**| Missing / unresolved | `100.0%` derived from 4 children | **`100.0%` derived from 4 children (`derived_from_children: true`)** | **YES** |
| **Award Subcriteria Breakdown** | Unresolved | Social Value (10%), Experience (15%), Scope/Delivery (35%), Commercial (40%) | **Social Value (10%), Experience (15%), Scope/Delivery (35%), Commercial (40%)** | **YES** |
| **Commercial Double-Count** | N/A (unresolved) | 40% total | **40% total (no double count, no duplicate rows)** | **YES** |
| **Scoring Scale (10/7/5 pts)**| Flattened / unresolved | Preserved under Scoring Model, non-additive | **Preserved under Scoring Model, non-additive** | **YES** |
| **Conditions of Participation** | Flattened / unresolved | Preserved as Qualification / Gate, non-additive | **Preserved as Qualification / Gate, non-additive** | **YES** |
| **Process / Methodology Stages**| Flattened / unresolved | Preserved as Process / Methodology, non-additive | **Preserved as Process / Methodology, non-additive** | **YES** |
| **Total Pipeline Timing** | 750.49s | 852.00s | **815.53s** (Stage A: 725.91s, B: 0.0701s, C: 0.0227s, D: 89.53s) | **YES** |

---

## 3. Fresh Production Replay Execution Details

- **Artifact File:** [`tests/acceptance/results/bc_evaluation_hierarchy_replay.json`](file:///C:/Users/feras/Documents/Projects/Bid-Intelligence/tests/acceptance/results/bc_evaluation_hierarchy_replay.json)
- **Execution Timestamp:** `2026-09-04T08:36:31.782286+00:00`
- **Replay Code SHA:** `6ff7e7a2a49e7d244fd146d006e03c53bd772ccd`
- **Model:** `claude-haiku-4-5-20251001`
- **Source Documents:**
  - `itt_-_ir67tvet42026_-_smart_classroom_setup_-_updated.pdf` (60,210 chars, SHA-256: `607e6634ed36f440bc88a6dd2c2103973d46a6112f00aacc1c0e3f5c6fd268b7`)
  - `annex_2_-_procurement_specific_questionnaire_1.docx` (24,452 chars, SHA-256: `08970b7e7c7356d40529121d51d50238659a22a7555bb9a63ae69c87b8a239e6`)

### 3.1 Extraction Diagnostics
In the fresh replay, both source document extractions ran cleanly:
- `itt_-_ir67tvet42026_-_smart_classroom_setup_-_updated.pdf`: 157 requirements, 20 evaluation criteria extracted. No parse failure (`has_parse_failure: false`), no unrecovered truncation (`has_recovered_truncation: false`).
- `annex_2_-_procurement_specific_questionnaire_1.docx`: 35 requirements, 3 evaluation criteria extracted. No parse failure (`has_parse_failure: false`), no unrecovered truncation (`has_recovered_truncation: false`).

### 3.2 Verified Production Output Structure
```json
{
  "status": "VALID",
  "overall_total": 100.0,
  "overall_unit": "Percent",
  "root_details": [
    {
      "stage": "Conditions of Participation (PSQ)",
      "weight_value": null,
      "weight_unit": "None",
      "derived_from_children": false,
      "evaluation_role": "Qualification / Gate"
    },
    {
      "stage": "Financial Standing Assessment",
      "weight_value": null,
      "weight_unit": "None",
      "derived_from_children": false,
      "evaluation_role": "Qualification / Gate"
    },
    {
      "stage": "Stage 1: Tender Completion and Compliance Check",
      "weight_value": null,
      "weight_unit": "None",
      "derived_from_children": false,
      "evaluation_role": "Process / Methodology"
    },
    {
      "stage": "Stage 2: Selection Questionnaire and Supplier Qualification Review",
      "weight_value": null,
      "weight_unit": "None",
      "derived_from_children": false,
      "evaluation_role": "Process / Methodology"
    },
    {
      "stage": "Stage 3: Detailed Tender Response Evaluation",
      "weight_value": null,
      "weight_unit": "None",
      "derived_from_children": false,
      "evaluation_role": "Process / Methodology"
    },
    {
      "stage": "Award Criteria",
      "weight_value": 100.0,
      "weight_unit": "Percent",
      "derived_from_children": true,
      "evaluation_role": "Structural Container"
    },
    {
      "stage": "Scoring Model (Non-Commercial Criteria)",
      "weight_value": null,
      "weight_unit": "None",
      "derived_from_children": false,
      "evaluation_role": "Scoring Scale"
    },
    {
      "stage": "Scoring Scale - Response Quality Assessment",
      "weight_value": null,
      "weight_unit": "None",
      "derived_from_children": false,
      "evaluation_role": "Scoring Scale"
    },
    {
      "stage": "Commercial Evaluation",
      "weight_value": null,
      "weight_unit": "None",
      "derived_from_children": false,
      "evaluation_role": "Process / Methodology"
    },
    {
      "stage": "Moderation and Application of Weightings",
      "weight_value": null,
      "weight_unit": "None",
      "derived_from_children": false,
      "evaluation_role": "Process / Methodology"
    },
    {
      "stage": "Winning Tender Determination",
      "weight_value": null,
      "weight_unit": "None",
      "derived_from_children": false,
      "evaluation_role": "Process / Methodology"
    },
    {
      "stage": "Part 1: Your information and the bidding model",
      "weight_value": null,
      "weight_unit": "None",
      "derived_from_children": false,
      "evaluation_role": "Structural Container"
    },
    {
      "stage": "Part 2: Additional exclusions information",
      "weight_value": null,
      "weight_unit": "None",
      "derived_from_children": false,
      "evaluation_role": "Structural Container"
    },
    {
      "stage": "Part 3: Conditions of participation",
      "weight_value": null,
      "weight_unit": "None",
      "derived_from_children": false,
      "evaluation_role": "Qualification / Gate"
    }
  ],
  "child_details": {
    "Conditions of Participation (PSQ)": {
      "count": 2,
      "subtotal": null,
      "overall_subtotal": null,
      "within_parent_subtotal": null,
      "units": [],
      "bases": [
        "Unknown"
      ]
    },
    "Award Criteria": {
      "count": 4,
      "subtotal": 100.0,
      "overall_subtotal": 100.0,
      "within_parent_subtotal": null,
      "units": [
        "Percent"
      ],
      "bases": [
        "Overall"
      ]
    },
    "Scoring Model (Non-Commercial Criteria)": {
      "count": 3,
      "subtotal": null,
      "overall_subtotal": null,
      "within_parent_subtotal": null,
      "units": [
        "Points"
      ],
      "bases": [
        "Unknown"
      ]
    }
  },
  "warnings": []
}
```

---

## 4. Comprehensive Test Results

### 4.1 Mandated Scenarios & Integrity Test Suite
- **Orphan Subcriteria & Unknown Roots Tests (`TestOrphanSubcriteriaAndUnknownRoots`):**
  - Test A: Only orphan Subcriterion 60% yields `UNRESOLVED_HIERARCHY` with reason 'Subcriterion has no resolved parent.' $\to$ **PASS**
  - Test B: Award 60 + Award 40 + orphan Subcriterion 20 yields `UNRESOLVED_HIERARCHY` $\to$ **PASS**
  - Test C: Subcriterion nested under confirmed parent normal hierarchy (100% VALID) $\to$ **PASS**
  - Test D: Award 60 + Award 40 + Unknown 20 Overall yields `SOURCE_DISCREPANCY` $\to$ **PASS**
  - Test E: Award 60 + Award 40 + unweighted Process stage remains `VALID` $\to$ **PASS**
- **Structural Container Additive Filtering Tests (`TestStructuralContainerAdditiveFiltering`):**
  - Test A: Additive children + unweighted Process child derives 100% VALID $\to$ **PASS**
  - Test B: Additive children + weighted non-additive child (20% Overall) yields `SOURCE_DISCREPANCY` $\to$ **PASS**
  - Test C: Additive children + Unknown weighted child (20% Overall) yields `SOURCE_DISCREPANCY` $\to$ **PASS**
  - Test D: Additive children + role-conflicted child yields `SOURCE_DISCREPANCY` $\to$ **PASS**
  - Test E: Pure additive children derive 100% VALID unchanged $\to$ **PASS**
- **Stage A → Stage B Conflict Preservation Tests (`TestStageAToStageBConflictPreservation`):**
  - Test A: Within-document role conflict survives Stage A → Stage B $\to$ **PASS**
  - Test B: Within-document weight conflict survives Stage A → Stage B $\to$ **PASS**
  - Test C: Stage A conflict + consistent Stage B observation does not clear conflict $\to$ **PASS**
  - Test D: Sibling/observation permutation invariance preserves conflict state identically $\to$ **PASS**
- **Prior Directives 1–5 Integrity Tests (`TestEvaluationHierarchyMandatedSuite`, `TestGenericIntegrityCorrectionsPass`, `TestObservationKeyIdentityDeduplication`):**
  - Role arithmetic filtering, scoring scales, qualification gates, conservative conflict resolution, basis separation, chunk retry diagnostics, and portable runner $\to$ **PASS (all 61 tests in suite passed)**

### 4.2 Full Regression Test Suite Discovery
- **Discovered Tests:** **391 tests**
- **Passed Tests:** **390 passed (plus 19 subtests passed)**
- **Skipped Tests:** **1 skipped** (`test_live_document_extraction` skipped without `--run-live-ai-tests`)
- **Failed Tests:** **0 failed**
- **Execution Time:** **59.21s**

---

## 5. Summary of Deliverables & Git State
- **Branch:** `fix/evaluation-hierarchy-integrity`
- **Base:** `712111297124e861d676b174bd66c3d31c1ac49c`
- **Replay Code SHA:** `6ff7e7a2a49e7d244fd146d006e03c53bd772ccd`
- **No Schema Migration:** Migrations 001–003 intact; no Migration 004 created.
- **No British Council-specific production hardcoding:** Pure, generic procurement logic.
- **No PR opened** in compliance with instructions.

