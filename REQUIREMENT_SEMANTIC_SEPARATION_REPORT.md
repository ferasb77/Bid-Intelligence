# Requirement Semantic Separation Report

**Repository:** `ferasb77/Bid-Intelligence`  
**Branch:** `fix/requirement-semantic-separation`  
**Base Commit:** `39d237527822190da98bb1d6e306c95b26d90ad4`  
**Date:** 2026-09-03  
**Status:** `READY FOR FINAL REVIEW`

---

## 1. Executive Summary

British Council Acceptance Test #2 demonstrated that Bid Intelligence previously conflated two distinct procurement concepts:

1. **Mandatory** (`category == "Mandatory"`) — Describes whether compliance is compulsory (i.e. not optional or rated).
2. **Supplier Qualification Gate** — Describes pass/fail bidder eligibility, legal standing, financial standing, certifications, OEM authorization, and conditions of participation that determine whether the vendor is legally and operationally qualified to bid.

A procurement package contains mandatory requirements across multiple functional domains:
- Supplier eligibility / qualification conditions
- Technical specifications
- Submission instructions and checklists
- Delivery obligations and SLAs
- Commercial, liability, and contract terms
- General mandatory compliance obligations

Under the previous implementation, all 35 mandatory requirements in the British Council procurement package were treated as qualification gates on the DECIDE and CHECK pages. This led to false alarms where technical specifications (e.g. 75" LED display 4K UHD) and submission checklist forms were counted as supplier qualification blockers.

This branch introduces orthogonal semantic typing (`requirement_type`) across Stage A, Stage B, and Stage D, confines `qualification_gates` strictly to genuine supplier qualification requirements, preserves full mandatory blocking at the submission gate (`SUBMIT`), ensures conflict-safe, order-independent semantic type merging, provides exact description-based gate matching, and creates clear separation throughout the user interface.

---

## 2. Core Architectural Principles & Scope Boundaries

### 2.1 Decoupling Category from Requirement Type
- `category` continues to use the existing controlled enum:
  - `Mandatory`
  - `Rated`
  - `Financial`
  - `Supporting`
- `requirement_type` is an orthogonal controlled enum:
  - `Supplier Qualification`: Genuine pass/fail bidder eligibility, legal standing, financial standing, certifications, OEM authorizations, required references, conditions of participation.
  - `Technical Specification`: Property or characteristic of the offered solution, product, technology, or technical response.
  - `Submission Compliance`: Forms, signatures, packaging, portal, formats, attachments, submission checklists.
  - `Delivery / SLA`: Implementation, response times, maintenance, uptime, training, delivery obligations.
  - `Commercial / Contractual`: Pricing mechanics, payment, insurance during contract, liability, IP, terms.
  - `Evaluation / Scored`: Scored/rated criteria or scoring mechanics.
  - `General Compliance`: Mandatory obligations that do not safely fit the above.

### 2.2 DECIDE vs. SUBMIT Separation
- **DECIDE Stage Qualification Gating is Narrowed:**
  - `qualification_gates` in the Bid Brief and DECIDE KPI cards now evaluate **only** requirements where:
    $$\text{category} == \text{"Mandatory"} \quad \land \quad \text{requirement\_type} == \text{"Supplier Qualification"}$$
  - The DECIDE matrix is renamed to **Requirement Assessment Matrix**, displaying all mandatory and scored requirements with semantic type badges without mislabeling technical specs as qualification gates.
- **SUBMIT Compliance Remains Strict:**
  - `evaluate_submission_state()` in `pages/stage_submit.py` was **not weakened**. All mandatory requirements (technical, submission, SLA, commercial) must still achieve `PASS` to enable proposal submission.

### 2.3 Database Integrity (No Migration 004)
- No database migration was introduced. The schema remains at Migration 003.
- No `requirement_type` database column was added.
- The semantic typing is preserved across Stage A, Stage B, and Stage D normalized models, and persisted indirectly via `bid_briefs.qualification_gates` JSON.

---

## 3. Implementation Details & Safety Remediations

### 3.1 Conservative Type Normalization (`requirement_semantics.py`)
- Removed arbitrary substring matching from `normalize_requirement_type()`.
- Accepts only:
  - Exact canonical enum values (case-insensitive, normalized whitespace/separators)
  - Explicit exact aliases from `_EXACT_ALIAS_MAP`
- Ambiguous compounds (such as `Technical Qualification`, `Qualification / Technical`, `Submission Qualification`, `Commercial Qualification`, `Random Qualification String`) strictly return `None` rather than guessing `Supplier Qualification`.

### 3.2 Hard-Gate Evidence Safety Barrier (`has_supplier_qualification_evidence`)
- **False-Positive Discovery:** Final review of the British Council production replay revealed a real false-positive in `qualification_gates`:
  > *"All items must be brand new and not refurbished, used, or end-of-life hardware."*
  This was extracted with candidate `requirement_type == "Supplier Qualification"`. Because early logic trusted valid explicit `Supplier Qualification` labels unconditionally, it was admitted into the authoritative qualification gates.
- **Safeguard Implementation:** Introduced `has_supplier_qualification_evidence(requirement)` in [`requirement_semantics.py`](file:///C:/Users/feras/Documents/Projects/Bid-Intelligence/requirement_semantics.py). A requirement can become an authoritative qualification gate (`is_supplier_qualification()`) only when:
  1. `category == "Mandatory"`
  2. Resolved `requirement_type == "Supplier Qualification"`
  3. **AND** the material requirement text contains deterministic evidence that the condition concerns bidder/supplier participation, eligibility, standing, authorization, capability, or exclusion.
- Candidate labels from Stage A are treated as candidate semantics, not sufficient proof of a hard gate. Product and hardware specifications (e.g. brand new hardware, 4K display, HDMI ports) are blocked from qualification gates regardless of candidate label.

### 3.3 True N-Way Order-Independent Semantic Merging (`resolve_candidate_requirement_types`)
- **Associativity Remediation:** Sequential pairwise use of `merge_requirement_types()` could lose conflict history when processing 3+ observations (e.g. $A + B \to \text{General}$, then $\text{General} + A \to A$).
- **N-Way Resolution:** Implemented `resolve_candidate_requirement_types(candidate_types)`:
  - For each material requirement identity during Stage A chunk aggregation and Stage B normalization, an internal candidate set `_specific_types: set[str]` accumulates all normalized observed specific semantic types.
  - `General Compliance` and `None` are ignored as specific evidence.
  - If zero specific types exist: `General Compliance`.
  - If exactly one distinct specific type exists: that specific type.
  - If two or more distinct specific types exist: `General Compliance`.
  - Conflict state is irreversible: once conflicting distinct types occur, subsequent duplicate observations cannot resurrect a specific type.
  - Fully order-independent and associative across all permutations of chunks and documents.
  - Internal candidate tracking set is stripped before returning facts, ensuring no schema leakage.

### 3.4 DECIDE Matrix User Terminology Update (`pages/stage_decide.py`)
- In Tab 1 ("Requirement Assessment Matrix"), user-facing terminology for the PASS/CONCERN/FAIL/UNKNOWN evaluation of general procurement requirements was updated from *"Qualification Status"* to **"Compliance Status"**.
- Updated filter label, table column header, edit button tooltip, form field label, and linked evidence textarea placeholder.
- Underlying database field `qual_status` remains intact without requiring Migration 004.
- Supplier Qualification-specific KPI metric cards and hard-gate warning alerts continue using qualification gate terminology.

### 3.5 Exact Qualification Gate Matching (`select_qualification_requirements`)
- Removed fuzzy substring matching from `select_qualification_requirements()`.
- Uses full normalized description identity (`normalize_requirement_identity_text`).
- Shorter gate descriptions that happen to be substrings of unrelated longer mandatory requirements strictly result in **no match**.

### 3.6 Zero-Gate UI State (`get_qualification_gate_ui_alert`)
- When `q_total == 0` in Stage 2 (DECIDE), the console never displays `"ALL QUALIFICATION GATES VERIFIED"`.
- Instead, it renders a neutral informational state:
  > *"No explicit pass/fail supplier qualification gates were identified. Mandatory compliance requirements remain tracked separately."*

### 3.7 Bid / No-Bid Requirement Partition (`analyst.py`)
- In `bid_no_bid_score()`, requirements are partitioned using database `id` when present, or normalized material description identity when no database ID exists.
- Does not use `req_id` alone. Requirements sharing the same `req_id` (e.g. `M1` Supplier Qualification and `M1` Technical Specification) are correctly partitioned without collision.

---

## 4. Fresh British Council Production Replay (Stage A → B → C → D)

A completely fresh benchmark execution was performed directly from the source procurement documents through the production pipeline using current Anthropic configuration at committed code revision `REPLAY_CODE_SHA`:

### 4.1 Provenance & Input Verification
- **Code SHA (`REPLAY_CODE_SHA`):** `1eaa10c2f4b9264aef865e983daf4787ddf805c1`
- **Run Started At:** `2026-09-03T13:45:11.354030+00:00`
- **Model:** `claude-haiku-4-5-20251001` (`temperature=0.0`)
- **Input Files & Hashes:**
  - `itt_-_ir67tvet42026_-_smart_classroom_setup_-_updated.pdf` (60,210 chars)  
    `SHA-256: 607e6634ed36f440bc88a6dd2c2103973d46a6112f00aacc1c0e3f5c6fd268b7`
  - `annex_2_-_procurement_specific_questionnaire_1.docx` (24,452 chars)  
    `SHA-256: 08970b7e7c7356d40529121d51d50238659a22a7555bb9a63ae69c87b8a239e6`

### 4.2 Replay Execution Timings
- **Stage A Execution Time:** 683.12s
- **Stage B Execution Time:** 0.0680s
- **Stage C Execution Time:** 0.0209s
- **Stage D Execution Time:** 89.89s
- **Total Pipeline Execution Time:** 773.10s (~12.9 minutes)

### 4.3 Requirement Counts & Semantic Breakdown
- **Raw Extracted Requirements:**
  - Primary ITT (`itt_-_ir67tvet42026...pdf`): 121
  - Annex 2 PSQ (`annex_2_-_procurement...docx`): 26
  - Total Raw: 147
- **Normalized Requirements:** 147
  - `Mandatory`: 136
  - `Rated`: 4
  - `Financial`: 0
  - `Supporting`: 7
- **Semantic Type Distribution:**
  - `Supplier Qualification`: 29
  - `Technical Specification`: 6
  - `Submission Compliance`: 46
  - `Delivery / SLA`: 12
  - `Commercial / Contractual`: 13
  - `Evaluation / Scored`: 4
  - `General Compliance`: 37
- **Authoritative `qualification_gates` Count:** **25** (Strict semantic subset of the 136 Mandatory requirements; deduplicated and verified against actor- and qualification-bound hard-gate evidence cues).

### 4.4 Human Review & Verification of All Resulting Qualification Gates
Every one of the 25 resulting qualification gates was individually reviewed:

1. `M1` (Sec 2.1): *"Vendors must be authorized by the respective OEM, certified, and have demonstrable experience in executing similar comprehensive IT projects."* (OEM authorization & certified standing)
2. `M1` (Sec 2.1): *"Vendors must be authorized by the respective OEM (Original Equipment Manufacturer)"* (OEM authorization)
3. `M2` (Sec 2.1): *"Vendors must be certified"* (Certified bidder standing)
4. `M3` (Sec 2.1): *"Vendors must have demonstrable experience in executing similar comprehensive IT projects"* (Demonstrable bidder experience)
5. `M4` (Sec 2.1): *"Suppliers must be eligible and reputable firms"* (Supplier eligibility condition)
6. `M4` (PAGE 15): *"Vendor must be able to demonstrate proof of authorized Partner/Reseller/Manufacturer status. British Council reserves the right to seek proof in the form of OEM certificates or Manufacturer Authorization letter."* (OEM/Partner authorization)
7. `M1` (Sec 9.1 & 10.1): *"Confirm compliance with qualification requirements as set out at Annex 2 (Procurement Specific Questionnaire). Failure to comply with one or more qualification requirements shall entitle British Council to reject tender response in full."* (Conditions of participation compliance & rejection consequence)
8. `M1` (Sec 15.1, PSQ Q1): *"Participant must confirm legal eligibility and authorization to perform services in all specified cities (Peshawar, Haripur, D.I Khan, Gilgit, Skardu, Quetta), including compliance with all applicable tax registration and regulatory requirements."* (Legal eligibility & tax registration)
9. `M2` (Sec 15.1, PSQ Q1): *"Participant must confirm organizational capability to supply, install, and provide after-sales support in all listed cities (Peshawar, Haripur, D.I Khan, Gilgit, Skardu, Quetta)."* (Organizational capability with PSQ context)
10. `M3` (Sec 15.1, PSQ Q2): *"Participant must provide valid Original Equipment Manufacturer (OEM) Authorization Letters or equivalent documentary evidence confirming authorization to supply, install, support, and provide warranty services for all proposed solution components."* (OEM authorization letters)
11. `M4` (Sec 15.3): *"Participant must achieve minimum pass score for ALL Conditions of Participation questions. Failure to achieve minimum pass score on any question results in exclusion from event and rejection of submission."* (Conditions of participation minimum score & exclusion)
12. `M5` (Sec 15.2): *"Participant must provide information on two most recent accounts and, upon request, provide copies of most recent audited accounts or up-to-date financial statements to facilitate British Council's assessment of economic and financial standing, including turnover relative to contract value, solvency ratios, and profitability ratios."* (Economic & financial standing)
13. `M7` (Sec 14.4, 14.5): *"Where participant intends to sub-contract performance of part or all of contract, sub-contractor details must be completed in Procurement Specific Questionnaire. Sub-contractors will be assessed for Excluded or Excludable status. If sub-contractor is deemed Excluded or Excludable, the Participant will be treated as Excluded or Excludable."* (Sub-contractor assessment for Excluded/Excludable status & exclusion)
14. `M16` (Sec 18.1 Stage 2): *"Stage 2 Evaluation: The completed Selection Questionnaire will be reviewed to confirm that the potential supplier meets all qualification criteria set out in the questionnaire. Suppliers meeting qualification criteria will proceed to Stage 3. Suppliers not meeting qualification criteria may be excluded and their tender response rejected in full."* (Selection questionnaire qualification criteria & exclusion)
15. `M2` (Part 1 - Q5): *"Supplier must not be on the debarment list. Question 5 requires confirmation of debarment status."* (Debarment list exclusion)
16. `M4` (Part 2 - Q7, 8, 9): *"If relying on associated persons (consortium members or key sub-contractors relied upon to meet conditions of participation), those associated persons must be registered on CDP and have shared their information as PDF download, including basic information, economic and financial standing information (if relied upon for financial capacity), associated person information, and exclusion grounds information."* (Associated persons meeting conditions of participation & financial capacity)
17. `M5` (Part 2 - Q10): *"Associated persons must not be on the debarment list. Question 10 requires confirmation of debarment status for all associated persons."* (Associated persons debarment status)
18. `M7` (Part 2 - Q13): *"No intended sub-contractor may be on the debarment list. Question 13 requires confirmation of debarment status for all intended sub-contractors."* (Sub-contractor debarment status)
19. `M8` (Part 3A - Q14): *"Supplier must satisfy minimum financial requirements set as conditions of participation: Operating Profit Margin > 20%; Current Ratio (Liquidity) > 1; Debt Ratio < 0.8. Question 14 requires confirmation of compliance with these minimum requirements."* (Minimum financial conditions of participation)
20. `M14` (Part 3A - Q15): *"If relying on another supplier to act as a guarantor, supplier must provide the guarantor's name and evidence of their economic and financial standing."* (Guarantor economic & financial standing)
21. `M1` (Sec 17.1): *"Bidder must confirm legal eligibility and authorization to perform services in each specified city, including compliance with all applicable tax registration and regulatory requirements."* (Legal eligibility & tax registration)
22. `M3` (Sec 17.2): *"Bidder must provide valid Original Equipment Manufacturer (OEM) Authorization Letters or equivalent documentary evidence confirming authorization to supply, install, support, and provide warranty services for all proposed solution components."* (OEM authorization letters)
23. `M4` (Sec 18): *"Bidder must confirm that human and technical resources are in place, or will be in place by contract award, to perform the contract and ensure compliance with UK General Data Protection Regulation and protection of data subject rights. Authority has right to exclude any supplier answering 'No' to this section."* (Explicit right to exclude based on resource & compliance confirmation)
24. `M5` (Sec 19): *"Bidder must provide details of at least three contracts demonstrating technical ability from past three years (public or private sector, including grant-funded work)... Authority has right to exclude any supplier unable to provide at least one example or reasonable explanation."* (Explicit right to exclude based on technical ability demonstration)
25. `M7` (Sec 21): *"Bidder must provide details of how organizational qualifications or standards specified in conditions of participation are met, or provide details of other equivalent standards that equal or exceed what has been requested."* (Conditions of participation organizational standards)

### 4.5 Specific Verification Invariants
- **Hardware/Product requirements absent:** Confirmed brand-new hardware is strictly absent from `qualification_gates`.
- **Solution technical capability statements absent:** Pure solution capability statements lacking actor or qualification context are strictly absent.
- **Ordinary bidding-model disclosure absent:** Bidding model structure disclosure is strictly absent.
- **Submission mechanics absent:** Formatting, document completion, signing, caveats, and response receipt times are tracked in the Requirements Register and SUBMIT gate, not in `qualification_gates`.
- **SLA obligations absent:** Warranty periods and SLA response times are not in `qualification_gates`.
- **Commercial terms absent:** Commercial pricing terms, liabilities, and payments are not in `qualification_gates`.
- **Genuine conditions of participation retained:** Debarment checks, financial liquidity and debt ratios, OEM authorizations, and statutory exclusion grounds are strictly preserved.

---

## 5. Test Coverage & Regression Suite

### 5.1 Expanded Test Suite
[`tests/test_requirement_semantic_separation.py`](file:///C:/Users/feras/Documents/Projects/Bid-Intelligence/tests/test_requirement_semantic_separation.py) (37 tests):
- Prompt & Taxonomy:
  - `test_allowed_types_contains_all_seven_types`
  - `test_stage_a_prompt_defines_requirement_type`
  - `test_stage_d_prompt_separates_mandatory_from_qualification`
  - `test_compact_requirement_preserves_requirement_type`
- Normalization & Fallback Resolution:
  - `test_normalize_requirement_type_exact_and_aliases`
  - `test_ambiguous_type_labels_return_none_not_supplier_qualification`
  - `test_normalize_requirement_type_invalid_returns_none`
  - `test_mandatory_alone_does_not_default_to_supplier_qualification`
  - `test_condition_of_participation_resolves_to_supplier_qualification`
  - `test_financial_standing_resolves_to_supplier_qualification`
  - `test_oem_authorization_for_participation_resolves_to_supplier_qualification`
  - `test_hard_gate_evidence_safety_barrier_cases` (A, B, C, D, E, F coverage + narrowed negative and positive context tests + capability actor/qualification-bound tests)
  - `test_technical_specification_is_non_gate`
  - `test_signed_submission_form_is_non_gate`
  - `test_incident_sla_response_is_non_gate`
  - `test_liability_payment_clause_is_non_gate`
  - `test_generic_mandatory_compliance_is_non_gate`
  - `test_rated_category_is_never_supplier_qualification`
- Conflict-Safe Semantic Merging & Transient History:
  - `test_same_specific_types_preserve_type`
  - `test_none_or_general_with_specific_preserves_specific`
  - `test_conflicting_different_specific_types_resolves_to_general_compliance`
  - `test_all_permutations_commutative`
  - `test_n_way_candidate_aggregation_all_permutations` (All 6 permutations resolve to General Compliance)
  - `test_n_way_candidate_aggregation_with_general_and_duplicates` (Order and duplicate independence)
  - `test_stage_a_aggregation_missing_explicit_type_preserves_financial_qualification` (Test A)
  - `test_stage_a_aggregation_missing_explicit_type_preserves_technical_specification` (Test B)
  - `test_stage_a_conflict_retained_and_prevents_stage_b_resurrection` (Test C)
  - `test_stage_b_all_document_permutations_preserve_conflict` (Test D)
  - `test_stage_b_final_requirements_contain_no_internal_semantic_candidates` (Test E)
- Stage D Authoritative Rebuild & Gate Filtering:
  - `test_only_supplier_qualification_mandatory_becomes_qualification_gate`
  - `test_hardware_product_spec_with_supplier_qual_label_not_rebuilt_as_gate`
- Gate-to-Requirement Matching & UI Helpers:
  - `test_select_qualification_requirements_matching`
  - `test_select_qualification_requirements_empty_gates_returns_empty`
  - `test_select_qualification_requirements_does_not_match_non_mandatory`
  - `test_substring_containment_does_not_falsely_match`
  - `test_zero_gate_ui_alert_state`
  - `test_partition_by_material_description_when_no_db_id`

### 5.2 Full Regression Suite Totals
- `tests/test_requirement_semantic_separation.py`: **37 / 37 passed**
- `tests/test_stage_d_completeness.py`: **52 / 52 passed**
- `tests/test_stage_a_extraction_reliability.py`: **20 / 20 passed**
- `tests/test_stage_b_requirement_dedup_integrity.py`: **8 / 8 passed**
- Full unit test discovery (`tests/test_*.py`): **304 / 304 passed**
- Smoke test suite (`tests/smoke/`): **12 / 12 passed**
- Integration test suite (`tests/integration/`): **6 discovered / 5 passed / 1 skipped (live AI) / 0 failed**
- **Grand Total:** **322 discovered / 321 passed / 1 skipped live AI / 0 failed**

---

## 6. Git Summary

- **Branch:** `fix/requirement-semantic-separation`
- **Files Created:**
  - `requirement_semantics.py`
  - `tests/test_requirement_semantic_separation.py`
  - `REQUIREMENT_SEMANTIC_SEPARATION_REPORT.md`
- **Files Modified:**
  - `extractor.py`
  - `analyst.py`
  - `pages/stage_understand.py`
  - `pages/stage_decide.py`
  - `pages/stage_check.py`
  - `tests/test_stage_d_completeness.py`
  - `tests/acceptance/results/bc_benchmark_replay_stage_a_b_d.json`
