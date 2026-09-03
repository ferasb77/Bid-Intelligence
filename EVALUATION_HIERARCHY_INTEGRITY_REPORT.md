# EVALUATION HIERARCHY & WEIGHTING INTEGRITY — VERIFICATION & AUDIT REPORT

**Date:** 2026-09-03  
**Repository:** `ferasb77/Bid-Intelligence`  
**Branch:** `fix/evaluation-hierarchy-integrity`  
**Base Commit:** `712111297124e861d676b174bd66c3d31c1ac49c` (PR #8 merged)  
**Initial Production Baseline:** `92451a6d8a579b768added7fec68774f23f836c1`  
**Replay Code SHA:** `7de2bc6ab954456b73b66f3c3f80ca0f3ea8dd2d`  
**Status:** REMEDIATED, TESTED & INDEPENDENTLY REPLAYED — READY FOR FINAL REVIEW  

---

## 1. Executive Summary & Defect Remediation

### 1.1 Root Cause of the Original Defect (140% / 160% Double-Counting)
The evaluation model previously flattened all extracted evaluation criteria into a single list and computed overall evaluation weights by summing every row indiscriminately.
In complex procurement packages like the British Council benchmark:
- Scored award criteria (Social Value 10%, Experience 15%, Scope/Delivery 35%, Commercial 40%) were extracted alongside summary headings or sub-components (e.g., Commercial 40% and Pricing Approach 40%, or scoring scale points 10, 7, 5, 3, 0).
- Flattening these elements resulted in an erroneous overall total of 140% or 160%, double-counting parent allocations and treating nested/scale metrics as top-level overall weights.

### 1.2 The Pre-PR Replay Finding: Failed Baseline Replay vs Fresh Replay
During the initial review pass at commit `92451a6`, the live extraction replay produced:
- `status`: `UNRESOLVED_HIERARCHY`
- `overall_total`: `null`
- 13 unresolved criteria because criteria referencing parent categories like `Award Criteria`, `Scoring Model`, and `Conditions of Participation` could not link to a physically extracted parent criterion row.

**Remediation implemented in this pass:**
1. **Derived Structural Containers:** When child criteria explicitly reference a parent category (e.g. `Award Criteria`, `Scoring Model`) and no physical row exists, a derived `Structural Container` is created deterministically with no invented weights, deriving provenance strictly from its children.
2. **Recursive Hierarchy:** Full multi-level nesting ($1 \to 2 \to 3$) is supported and formatted with progressive indentation without dropping nodes.
3. **Weight Unit vs. Weight Basis Decoupling:** `parse_evaluation_weight` parses numeric values and explicit units, leaving ambiguous basis as `Unknown`. Bare numbers are parsed as `Other` / `Unknown` (never assumed to be percentages).
4. **Enforced Weight Basis in Overall Totals:** Only criteria with `weight_basis == Overall` contribute to overall arithmetic. `Within Parent`, `Unknown`, `Scoring Scale`, and `Qualification / Gate` items are strictly non-additive overall.
5. **Evaluation Roles:** Distinct controlled taxonomy (`Award Criterion`, `Subcriterion`, `Qualification / Gate`, `Scoring Scale`, `Process / Methodology`, `Structural Container`, `Unknown`). Narrative process headings (e.g. `Commercial Evaluation`, `Moderation`) are classified as `Process / Methodology` rather than unweighted award criteria.
6. **Material Identity Independent of Weight Observations:** Logical identity is determined by title, parent, level, and role. Conflicting weight observations (e.g. 70 points vs 60 points) merge into one criterion with `weight_conflict = True` and preserved observations.
7. **Status Precedence:** `UNRESOLVED_HIERARCHY` $\to$ `MIXED_UNITS` $\to$ `SOURCE_DISCREPANCY` $\to$ `INSUFFICIENT_DATA` $\to$ `VALID`.
8. **No Database Migration:** Schema baseline at Migration 003 is preserved. No Migration 004 created.

---

## 2. Benchmark Comparison: Current vs Corrected Replay

| Metric / Dimension | Initial Attempt Replay (`92451a6`) | Fresh Production Replay (`7de2bc6`) | Acceptance Criteria Met? |
|---|---|---|---|
| **Code SHA** | `92451a6d8a579b768added7fec68774f23f836c1` | `7de2bc6ab954456b73b66f3c3f80ca0f3ea8dd2d` | **YES** (Fresh run) |
| **Pipeline Status** | `UNRESOLVED_HIERARCHY` (FAILED) | **`VALID`** | **YES** |
| **Overall Award Total** | `null` | **`100.0%`** | **YES** (Clean 100%) |
| **Overall Unit** | `None` | **`Percent`** | **YES** |
| **Unresolved Count** | 13 unresolved | **0 unresolved** | **YES** (All resolved) |
| **Root Count** | 0 roots (all orphan) | **12 structured roots** | **YES** |
| **Award Criteria Container**| Missing / unresolved | **`100.0%` derived from 4 children** | **YES** |
| **Award Subcriteria Breakdown** | Unresolved | **Social Value (10%), Experience (15%), Scope/Delivery (35%), Commercial (40%)** | **YES** |
| **Commercial Double-Count** | N/A (unresolved) | **40% total (no 80% double count)** | **YES** |
| **Scoring Scale (10/7/5 pts)**| Flattened / unresolved | **Preserved under Scoring Model, non-additive** | **YES** |
| **Conditions of Participation** | Flattened / unresolved | **Preserved as Qualification / Gate, non-additive**| **YES** |
| **Process / Methodology Stages**| Flattened / unresolved | **Preserved as Process / Methodology, non-additive**| **YES** |
| **Total Pipeline Timing** | 750.49s | **522.52s** (Stage A: 432.40s, B: 0.0438s, C: 0.0154s, D: 90.06s) | **YES** (Accurately reported) |

---

## 3. Fresh Production Replay Execution Details

- **Artifact File:** [`tests/acceptance/results/bc_evaluation_hierarchy_replay.json`](file:///C:/Users/feras/Documents/Projects/Bid-Intelligence/tests/acceptance/results/bc_evaluation_hierarchy_replay.json)
- **Execution Timestamp:** `2026-09-03T16:49:23.968467+00:00`
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
    {"stage": "Stage 1: Tender Completion Check", "evaluation_role": "Process / Methodology", "weight_value": null},
    {"stage": "Stage 2: Selection Questionnaire Review", "evaluation_role": "Process / Methodology", "weight_value": null},
    {"stage": "Stage 3: Detailed Tender Response Evaluation", "evaluation_role": "Process / Methodology", "weight_value": null},
    {"stage": "Scoring Scale - Response Quality Assessment", "evaluation_role": "Scoring Scale", "weight_value": null},
    {"stage": "Commercial Evaluation", "evaluation_role": "Process / Methodology", "weight_value": null},
    {"stage": "Moderation and Application of Weightings", "evaluation_role": "Process / Methodology", "weight_value": null},
    {"stage": "Winning Tender Determination", "evaluation_role": "Process / Methodology", "weight_value": null},
    {"stage": "Part 1: Your information and the bidding model", "evaluation_role": "Structural Container", "weight_value": null},
    {"stage": "Part 2: Additional exclusions information", "evaluation_role": "Structural Container", "weight_value": null},
    {"stage": "Part 3: Conditions of participation", "evaluation_role": "Qualification / Gate", "weight_value": null},
    {"stage": "Award Criteria", "evaluation_role": "Structural Container", "weight_value": 100.0, "derived_from_children": true},
    {"stage": "Scoring Model", "evaluation_role": "Scoring Scale", "weight_value": null}
  ],
  "child_details": {
    "Award Criteria": {
      "count": 4,
      "subtotal": 100.0,
      "units": ["Percent"],
      "bases": ["Overall"]
    },
    "Scoring Model": {
      "count": 3,
      "subtotal": 22.0,
      "units": ["Points"],
      "bases": ["Unknown"]
    }
  },
  "warnings": []
}
```

---

## 4. Comprehensive Test Results

### 4.1 Mandated Scenarios A through S ([`tests/test_evaluation_hierarchy_integrity.py`](file:///C:/Users/feras/Documents/Projects/Bid-Intelligence/tests/test_evaluation_hierarchy_integrity.py))
- **Test A:** Explicit missing parent label creates structural container $\to$ **PASS**
- **Test B:** Structural container has no invented weight or threshold $\to$ **PASS**
- **Test C:** Award Criteria structural container + 10/15/35/40 children gives 100 VALID $\to$ **PASS**
- **Test D:** Scoring Model structural container + point-scale children does not affect overall total $\to$ **PASS**
- **Test E:** Conditions of Participation structural container with thresholds does not affect overall total $\to$ **PASS**
- **Test F:** Three-level hierarchy ($1 \to 2 \to 3$) is fully preserved/displayed $\to$ **PASS**
- **Test G:** Duplicate parent titles without explicit disambiguation $\to$ unresolved $\to$ **PASS**
- **Test H:** 40% with no explicit basis $\to$ basis Unknown in parser $\to$ **PASS**
- **Test I:** Bare '40' is NOT Percent $\to$ **PASS**
- **Test J:** Root weight with basis Unknown is NOT added overall $\to$ **PASS**
- **Test K:** Root weight with basis Within Parent is NOT added overall $\to$ **PASS**
- **Test L:** Same logical criterion 40% repeated across docs $\to$ one criterion + merged refs $\to$ **PASS**
- **Test M:** Same logical criterion 40% vs 50% $\to$ one logical criterion + conflict, not 90% $\to$ **PASS**
- **Test N:** Parent 60% children 30%+40% Overall $\to$ `SOURCE_DISCREPANCY` $\to$ **PASS**
- **Test O:** Parent 60% children 50%+50% Within Parent $\to$ valid child allocation $\to$ **PASS**
- **Test P:** Process/gate roots with no weights do not invalidate a complete 100% award weighting $\to$ **PASS**
- **Test Q:** Missing weight on actual Award Criterion $\to$ `INSUFFICIENT_DATA` even when other award criteria sum to 100% $\to$ **PASS**
- **Test R:** Stage D authoritative rebuild survives an intentionally flattened LLM response $\to$ **PASS**
- **Test S:** No source numbers are silently normalized (genuine 110% retained) $\to$ **PASS**

### 4.2 Full Regression Test Suite Discovery
- **Unit Tests:** 317 discovered, **317 passed**, 0 failed, 0 skipped.
- **Smoke Tests:** 12 discovered, **12 passed**, 0 failed, 0 skipped.
- **Integration Tests:** 6 discovered, **5 passed**, 0 failed, **1 skipped** (live AI test skipped by design without `--live-ai` flag).
- **Grand Total Discovered:** **335 tests**
- **Grand Total Passed:** **334 passed, 1 skipped, 0 failed**.

---

## 5. Summary of Deliverables & Git State
- **Branch:** `fix/evaluation-hierarchy-integrity`
- **Base:** `712111297124e861d676b174bd66c3d31c1ac49c`
- **Committed Replay Code SHA:** `7de2bc6ab954456b73b66f3c3f80ca0f3ea8dd2d`
- **No Schema Migration:** Migrations 001–003 intact; no Migration 004 created.
- **No British Council-specific production hardcoding:** All rules implemented as pure, tender-agnostic procurement logic.
- **No PR opened** in compliance with instructions.
