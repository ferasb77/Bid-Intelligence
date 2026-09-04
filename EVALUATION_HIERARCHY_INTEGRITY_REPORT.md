# EVALUATION HIERARCHY & WEIGHTING INTEGRITY — VERIFICATION & AUDIT REPORT

**Date:** 2026-09-04  
**Repository:** `ferasb77/Bid-Intelligence`  
**Branch:** `fix/evaluation-hierarchy-integrity`  
**Base Commit:** `712111297124e861d676b174bd66c3d31c1ac49c` (PR #8 merged)  
**Safety Pass Replay SHA:** `3a73b01b5a856afc32b5e3934c80a6590e7ff6eb`  
**Status:** REMEDIATED, HARDENED, TESTED & REPLAY VERIFIED — READY FOR PR REVIEW  

---

## 1. Executive Summary & Defect Remediation

### 1.1 Root Cause of the Original Defect (140% / 160% Double-Counting)
The evaluation model previously flattened all extracted evaluation criteria into a single list and computed overall evaluation weights by summing every row indiscriminately.
In complex procurement packages like the British Council benchmark:
- Scored award criteria (Social Value 10%, Experience 15%, Scope/Delivery 35%, Commercial 40%) were extracted alongside summary headings or sub-components (e.g., Commercial 40% and Pricing Approach 40%, or scoring scale points 10, 7, 5, 3, 0).
- Flattening these elements resulted in an erroneous overall total of 140% or 160%, double-counting parent allocations and treating nested/scale metrics as top-level overall weights.

### 1.2 The PR-Close Safety Pass Hardening
In this final PR-close safety pass, five generic integrity corrections were applied and verified:
1. **Enforce Evaluation Role in Arithmetic (Directive 1):** Direct overall arithmetic accepts ONLY additive award roles (`ROLE_AWARD_CRITERION`, and `ROLE_SUBCRITERION` only when structurally appropriate). Non-additive roles (`ROLE_QUALIFICATION_GATE`, `ROLE_SCORING_SCALE`, `ROLE_PROCESS_STAGE`, `ROLE_STRUCTURAL_CONTAINER`, `ROLE_UNKNOWN`) are strictly non-additive directly. Structural container derives contribution exclusively from appropriate additive children (`derived_from_children = True`).
2. **Conservative Role Conflict Resolution (Directive 2):** Disagreements between additive and non-additive observations for the same logical criterion do NOT promote to additive; they resolve conservatively to `ROLE_UNKNOWN` with `role_conflict = True` and are treated as non-additive.
3. **Never Sum Mixed Weight Bases (Directive 3):** Subcriteria are grouped and totaled strictly by basis (`Overall`, `Within Parent`, `Unknown`). Sibling mixtures of `Overall` and `Within Parent` or known and `Unknown` trigger `STATUS_SOURCE_DISCREPANCY` and are never indiscriminately combined into an arithmetic subtotal.
4. **Stage A Failed Parse Recovery & Diagnostics (Directive 4):** Bounded chunk retries are executed for `FAILED` parses. Unrecovered parse failures set `has_parse_failure = True` and output `_extraction_diagnostic["status"] = "PARSE_FAILURE"`, never `VERIFIED_ADEQUATE`.
5. **Portable Benchmark Runner (Directive 5):** `run_bc_eval_replay.py` dynamically anchors to `PROJECT_ROOT`, verifies fixture presence upfront, and fails cleanly if local benchmark fixtures are missing.

---

## 2. Benchmark Comparison: Current vs Corrected Replay

| Metric / Dimension | Initial Attempt Replay (`92451a6`) | Intermediate Replay (`98b3e66`) | PR-Close Safety Pass Replay (`3a73b01`) | Acceptance Criteria Met? |
|---|---|---|---|---|
| **Code SHA** | `92451a6d8a579b768added7fec68774f23f836c1` | `98b3e66103e8bb686698ee43f6333041107e18c9` | **`3a73b01b5a856afc32b5e3934c80a6590e7ff6eb`** | **YES** |
| **Pipeline Status** | `UNRESOLVED_HIERARCHY` (FAILED) | `VALID` | **`VALID`** | **YES** |
| **Overall Award Total** | `null` | `100.0%` | **`100.0%`** | **YES** (Clean 100%) |
| **Overall Unit** | `None` | `Percent` | **`Percent`** | **YES** |
| **Unresolved Count** | 13 unresolved | 0 unresolved | **0 unresolved** | **YES** (All resolved) |
| **Root Count** | 0 roots (all orphan) | 14 structured roots | **13 structured roots** | **YES** |
| **Award Criteria Container**| Missing / unresolved | `100.0%` with 4 children | **`100.0%` derived from 4 children (`derived_from_children: true`)** | **YES** |
| **Award Subcriteria Breakdown** | Unresolved | Social Value (10%), Experience (15%), Scope/Delivery (35%), Commercial (40%) | **Social Value (10%), Experience (15%), Scope/Delivery (35%), Commercial (40%)** | **YES** |
| **Commercial Double-Count** | N/A (unresolved) | 40% total | **40% total (no double count, no duplicate rows)** | **YES** |
| **Scoring Scale (10/7/5 pts)**| Flattened / unresolved | Preserved under Scoring Model, non-additive | **Preserved under Scoring Model, non-additive** | **YES** |
| **Conditions of Participation** | Flattened / unresolved | Preserved as Qualification / Gate, non-additive | **Preserved as Qualification / Gate, non-additive** | **YES** |
| **Process / Methodology Stages**| Flattened / unresolved | Preserved as Process / Methodology, non-additive | **Preserved as Process / Methodology, non-additive** | **YES** |
| **Total Pipeline Timing** | 750.49s | 862.23s | **852.00s** (Stage A: 760.11s, B: 0.0799s, C: 0.0238s, D: 91.79s) | **YES** |

---

## 3. Fresh Production Replay Execution Details

- **Artifact File:** [`tests/acceptance/results/bc_evaluation_hierarchy_replay.json`](file:///C:/Users/feras/Documents/Projects/Bid-Intelligence/tests/acceptance/results/bc_evaluation_hierarchy_replay.json)
- **Execution Timestamp:** `2026-09-04T07:24:50.037928+00:00`
- **Model:** `claude-haiku-4-5-20251001`
- **Source Documents:**
  - `itt_-_ir67tvet42026_-_smart_classroom_setup_-_updated.pdf` (60,210 chars, SHA-256: `607e6634ed36f440bc88a6dd2c2103973d46a6112f00aacc1c0e3f5c6fd268b7`)
  - `annex_2_-_procurement_specific_questionnaire_1.docx` (24,452 chars, SHA-256: `08970b7e7c7356d40529121d51d50238659a22a7555bb9a63ae69c87b8a239e6`)

### Verified Production Output Structure:
```json
{
  "status": "VALID",
  "overall_total": 100.0,
  "overall_unit": "Percent",
  "root_details": [
    {"stage": "Conditions of Participation (PSQ)", "evaluation_role": "Qualification / Gate", "weight_value": null, "derived_from_children": false},
    {"stage": "Financial Standing Assessment", "evaluation_role": "Qualification / Gate", "weight_value": null, "derived_from_children": false},
    {"stage": "Stage 1: Tender Completion and Compliance Check", "evaluation_role": "Process / Methodology", "weight_value": null, "derived_from_children": false},
    {"stage": "Stage 2: Selection Questionnaire and Supplier Qualification Review", "evaluation_role": "Process / Methodology", "weight_value": null, "derived_from_children": false},
    {"stage": "Stage 3: Detailed Tender Response Evaluation", "evaluation_role": "Process / Methodology", "weight_value": null, "derived_from_children": false},
    {"stage": "Award Criteria", "evaluation_role": "Structural Container", "weight_value": 100.0, "weight_unit": "Percent", "derived_from_children": true},
    {"stage": "Scoring Model (Non-Commercial Criteria)", "evaluation_role": "Scoring Scale", "weight_value": null, "derived_from_children": false},
    {"stage": "Scoring Scale - Response Quality Assessment", "evaluation_role": "Scoring Scale", "weight_value": null, "derived_from_children": false},
    {"stage": "Commercial Evaluation", "evaluation_role": "Process / Methodology", "weight_value": null, "derived_from_children": false},
    {"stage": "Moderation and Application of Weightings", "evaluation_role": "Process / Methodology", "weight_value": null, "derived_from_children": false},
    {"stage": "Winning Tender Determination", "evaluation_role": "Process / Methodology", "weight_value": null, "derived_from_children": false},
    {"stage": "Part 1: Your information and the bidding model", "evaluation_role": "Qualification / Gate", "weight_value": null, "derived_from_children": false},
    {"stage": "Part 2: Additional exclusions information", "evaluation_role": "Qualification / Gate", "weight_value": null, "derived_from_children": false}
  ],
  "child_details": {
    "Conditions of Participation (PSQ)": {"count": 2, "subtotal": null, "overall_subtotal": null, "within_parent_subtotal": null, "units": [], "bases": ["Unknown"]},
    "Award Criteria": {"count": 4, "subtotal": 100.0, "overall_subtotal": 100.0, "within_parent_subtotal": null, "units": ["Percent"], "bases": ["Overall"]},
    "Scoring Model (Non-Commercial Criteria)": {"count": 3, "subtotal": null, "overall_subtotal": null, "within_parent_subtotal": null, "units": ["Points"], "bases": ["Unknown"]},
    "Part 1: Your information and the bidding model": {"count": 1, "subtotal": null, "overall_subtotal": null, "within_parent_subtotal": null, "units": [], "bases": ["Unknown"]},
    "Part 2: Additional exclusions information": {"count": 1, "subtotal": null, "overall_subtotal": null, "within_parent_subtotal": null, "units": [], "bases": ["Unknown"]}
  },
  "warnings": []
}
```

---

## 4. Comprehensive Test Results

### 4.1 Mandated Scenarios & Safety Pass Tests
- **Directive 1 Tests:** Direct overall arithmetic accepts ONLY additive award roles; non-additive roles (Gate, Scoring Scale, Process, Unknown) contribute `None`; structural containers derive contribution only from additive children $\to$ **PASS**
- **Directive 2 Tests:** Conservative role conflict resolution (disagreement between additive and non-additive yields `Unknown` with `role_conflict = True`); arbitrary nesting arithmetic validation $\to$ **PASS**
- **Directive 3 Tests:** Sibling subcriteria mixing Overall (30%) and Within Parent (70%) triggers `STATUS_SOURCE_DISCREPANCY`; observation identity includes `(value, unit, basis)` $\to$ **PASS**
- **Directive 4 Tests:** Permutation-invariant role observation deduplication; Stage A parse failure handling via bounded retries and `PARSE_FAILURE` diagnostic status $\to$ **PASS**
- **Directive 5 Tests:** Portable repo root detection and fixture presence validation in replay runner $\to$ **PASS**

### 4.2 Full Regression Test Suite Discovery
- **Discovered Tests:** **377 tests**
- **Passed Tests:** **376 passed (plus 19 subtests passed)**
- **Skipped Tests:** **1 skipped** (`test_live_document_extraction` skipped without `--run-live-ai-tests`)
- **Failed Tests:** **0 failed**

---

## 5. Summary of Deliverables & Git State
- **Branch:** `fix/evaluation-hierarchy-integrity`
- **Base:** `712111297124e861d676b174bd66c3d31c1ac49c`
- **Replay Code SHA:** `98b3e66103e8bb686698ee43f6333041107e18c9`
- **No Schema Migration:** Migrations 001–003 intact; no Migration 004 created.
- **No British Council-specific production hardcoding:** Pure, generic procurement logic.
- **No PR opened** in compliance with instructions.
