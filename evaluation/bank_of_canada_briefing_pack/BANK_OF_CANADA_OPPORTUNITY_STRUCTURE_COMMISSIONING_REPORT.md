# Bank of Canada RFP 2026-026 — Opportunity Structure Commissioning Report

**Commissioning run ID:** `oppstruct-boc-2026-026-20260912T144353Z-dd4b10`
**Refreshed Stage C run ID:** `phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8`
**Artifact directory:** `evaluation/bank_of_canada_briefing_pack/opportunity_structure_commissioning/oppstruct-boc-2026-026-20260912T144353Z-dd4b10/`

## A. Run metadata

| | |
|---|---|
| Phase 1 (Stage A, frozen) | `phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5` |
| Stage B (regenerated, canonical-term-fix) | `phase2-boc-2026-026-stageb-canonterm-fix-20260912T142551Z-34a031` |
| Stage C (refreshed this run) | `phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8` |
| Canonical Opportunity (audited/accepted) | `canonopp-boc-2026-026-20260912T142551Z-34a031` |
| Git commit | `7e797830f42d06ff08745648585de0e26557addb` |
| Production entry point | `opportunity_structure.build_opportunity_structure(stage_facts, package_metadata)` |
| Runtime | ~1s (structure build); full commissioning script including Stage C refresh, well under a minute |
| LLM calls | **0** |
| API cost | **$0** |

## B. Dependency trace (read from code, not inferred from the class name)

`opportunity_structure.py`'s own docstring states its scope precisely, confirmed by reading `build_opportunity_structure()` in full:

- **Consumes exactly 5 of Stage B's normalized_facts sections**: `requirements`, `evaluation_criteria`, `commercial_clauses`, `deliverables`, `submission_rules` (`SECTION_BY_FAMILY`). Nothing else in `stage_facts` is read.
- **Does not consume**: `dates`, `_canonical_opportunity`, `_contract_hygiene`, `_provenance_rejections`, Stage C's `conflicts` return value, or any Stage D object. Confirmed by reading the entire function body — no reference to any of these keys anywhere in `opportunity_structure.py`.
- **`package_metadata`** (`{files, doc_texts}`) is consumed only to independently re-validate every record's own `source_refs` via `canonical_opportunity._validate_ref` — the *same* provenance validator Canonical Opportunity uses (and that this session's contract-term audit fixed), not a separate implementation.
- **Identity**: reuses `opportunity_intelligence._record_id` exactly, so record IDs are stable and compatible with Opportunity Intelligence's future evidence-support contract, without inventing a new identifier scheme.
- **Deterministic, zero LLM**: confirmed by inspection — no `anthropic`/`client.messages`/`get_anthropic_client` reference anywhere in `opportunity_structure.py`, `_record_id`, or `_validate_ref`.
- **Conflict detection**: does not call Stage C's `detect_document_conflicts()` or read Stage C's `conflicts` list at all. It surfaces an *already-computed* per-record signal Stage B itself attaches (`<field>_conflict` boolean + `<field>_observations` list) for `EVALUATION_CRITERION` (`role`, `weight`) and `SUBMISSION_RULE` (`artifact_type`, `file_format`, `mandatory`, `submission_channel`) — it does not invent new conflict detection.
- **Provenance behavior**: every record's `source_refs` are independently re-validated (never trusting an upstream "verified" flag); `provenance_status` is `VERIFIED`/`PARTIAL`/`UNVERIFIED` per the same aggregation rule as Canonical Opportunity.
- **Identity/collision handling**: duplicate detection groups on a record's own semantic content (`canonical_json(fields)`), never on `_record_id`'s output; a genuine `_record_id` collision (same ID, different content) is recorded in `integrity_diagnostics.collision_ids` and blocks the `collision_free` gate — never silently merged.
- **Fallback/default behavior**: a missing section defaults to `[]` (no crash); a non-list section or non-mapping record is recorded in `integrity_diagnostics.invalid_records` and skipped, never coerced.
- **Downstream consumers**: `opportunity_structure_binding.py` (an Evidence-catalog binding adapter) and `opportunity_structure_publication.py` exist in the repository but are a separate, later publication/evidence-binding layer, out of scope for this commissioning (not invoked here, per instruction to stop before Opportunity Intelligence and everything after it).

**No inference was needed beyond reading the code** — the module's own docstring ("never the raw `typed_observations` families that `canonical_opportunity.py` already owns, and never any interpretation, confidence, Unknown, or Human Decision about what the structure means") matches exactly what the implementation does.

## Input lock and the Stage C refresh decision

**Opportunity Structure consumes only Stage B families.** All 5 (`requirements`, `evaluation_criteria`, `commercial_clauses`, `deliverables`, `submission_rules`) were re-verified byte-identical between the old (`phase2-boc-2026-026-stageb-20260912T125051Z-91a22b`) and the latest regenerated (`phase2-boc-2026-026-stageb-canonterm-fix-20260912T142551Z-34a031`) Stage B artifacts:

```
requirements:         identical: True | 427 / 427
evaluation_criteria:  identical: True | 83 / 83
commercial_clauses:   identical: True | 91 / 91
deliverables:         identical: True | 23 / 23
submission_rules:     identical: True | 68 / 68
```

**Therefore `build_opportunity_structure()`'s own output does not depend on the contract-term provenance fix at all**, and no Stage B/C artifact was silently stale for *its* purposes. The latest regenerated Stage B artifact was used regardless, per instruction and as the correct discipline going forward.

**Stage C was nonetheless refreshed**, not because Opportunity Structure needs it, but because this report's own conflict-tracing sections (K, and the acceptance gate) must cross-reference an *accurate* Stage C conflict list, and the previously-persisted one (`phase3-boc-2026-026-stagec-20260912T130007Z-dd391b`, 7 conflicts) is stale: the contract-term audit changed `_canonical_opportunity`'s resolved state (3 identity-field conflicts now carry more observations and therefore different content-addressed `conflict_id`s; a new `contract_term` conflict now exists; `procurement_model` newly resolves). Stage C was rerun exactly once, deterministically, zero LLM calls, from the same frozen Phase 1 input and the latest regenerated Stage B:

```
old total conflicts: 7   ->   new total conflicts: 8
evaluation_conflicts_stable: True (all 4 CONF-EVAL-1..4 records byte-identical before/after)
```

The 4 evaluation conflicts — the ones this report's conflict trace cares about most, since Opportunity Structure represents evaluation architecture — are **confirmed completely unaffected** by the refresh. The refreshed run ID is `phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8`.

## C. Real Opportunity Structure schema

| Field/object | Type | Required/optional | Upstream source | Grouping logic | Scope behavior | Provenance | Default/empty | Downstream consumer |
|---|---|---|---|---|---|---|---|---|
| `documents` | list of `{source_document_id, source_doc}` | always present | `package_metadata.files` | one per file, sorted case-insensitively | — | — | `[]` if no files | evidence binding (out of scope here) |
| `records` | list of record objects | always present, may be empty per family | the 5 families above | deduplicated on exact semantic content (`canonical_json(fields)`) per family | preserved verbatim from the raw record's own fields (e.g. `scope`, `rfso_ref`, `component`) — never rewritten | independently re-validated `source_refs` + `provenance_status` | a family with no input records contributes zero records, not a placeholder | Opportunity Structure Publication (not commissioned here) |
| `records[].record_id` | string | required | `opportunity_intelligence._record_id` | content+family-hash fallback; stable, documented IDs (`deliverable_id`/`clause_id`/`criterion_id`) reused where Stage B already assigns one | — | — | — | — |
| `records[].conflict_ids` | list of string | required, may be `[]` | derived from `<field>_conflict`/`<field>_observations` already on the raw record | — | — | — | `[]` when no conflict flag is set | — |
| `conflicts` | list of `{conflict_id, state, family, field, affected_record_ids, incompatible_values}` | always present, may be `[]` | same per-record conflict flags | one conflict object per flagged record+field | — | — | `[]` if nothing flagged | — |
| `coverage` | `{family: {records_present}}` | always present | derived | — | — | — | `False` if a family has zero records | — |
| `integrity_diagnostics` | `{collision_ids, collision_free, invalid_records, record_count, conflict_count}` | always present | derived | — | — | — | — | — |
| `input_digest` | string | always present | content hash of `documents`+`records` | — | — | — | — | determinism verification |

No field was invented for this table beyond what `build_opportunity_structure()` literally returns.

## D/E. Complete structure inventory and upstream accounting

| Family | Input records (Stage B) | Structure records | Total occurrences absorbed | Accounted for | Provenance: VERIFIED / PARTIAL / UNVERIFIED |
|---|---:|---:|---:|---|---|
| REQUIREMENT | 427 | 427 | 427 | ✅ | see breakdown below |
| EVALUATION_CRITERION | 83 | 83 | 83 | ✅ | see below |
| SUBMISSION_RULE | 68 | 68 | 68 | ✅ | see below |
| DELIVERABLE | 23 | 23 | 23 | ✅ | see below |
| COMMERCIAL_CLAUSE | 91 | 91 | 91 | ✅ | see below |
| **Total** | **692** | **692** | **692** | **✅ zero silent disappearance** | 380 VERIFIED / 309 PARTIAL / 3 UNVERIFIED |

Every input record accounted for 1:1 in this corpus (no family in this run happened to need cross-occurrence merging — `occurrence_count` is 1 for every record; the dedup mechanism exists and is tested, but this specific 16-document corpus's 5 families did not produce any exact-content duplicates). `integrity_diagnostics`: `collision_free: true`, `collision_ids: []`, `invalid_records: []`, `record_count: 692`, `conflict_count: 4`.

Only **3 of 692 records (0.4%)** are fully `UNVERIFIED` (zero usable provenance): one `COMMERCIAL_CLAUSE` and one `SUBMISSION_RULE` with empty `source_refs`, and one `EVALUATION_CRITERION` with a single ref whose `excerpt` is an empty string. None were promoted as if evidenced; all remain visibly, honestly `UNVERIFIED`.

## F. Evaluation architecture

83 `EVALUATION_CRITERION` records, represented 1:1 from Stage B's already-deduplicated, already-hierarchy-resolved `evaluation_criteria` (weights, thresholds, roles, parent/child links, `is_structural_container` flags, `weight_observations` — all preserved verbatim, not recomputed; Opportunity Structure performs no weight summation or rollup math itself, since that governed computation already happened in Stage B's `evaluation_hierarchy.py`, already commissioned in Phase 2/3).

- **8 records are `is_structural_container: true`** (grouping headers such as "Appendix D2 - HR Advisory", "Organizational Approach and Capabilities") — legitimate structural containers, each still carrying its own `source_refs` (mostly VERIFIED/PARTIAL — 7 of 8 have real provenance, none fabricated).
- **Opportunity Structure's own conflict surfacing found 4 `role_conflict: true` records** — a signal genuinely distinct from Stage C's 4 `CONF-EVAL-*` weight-discrepancy conflicts:

| Criterion | `role_observations` | `weight_conflict` |
|---|---|---|
| Relevant Experience and References | `["Award Criterion", "Structural Container", "Unknown"]` | `false` |
| Measurement Approach | `["Award Criterion", "Structural Container", "Unknown"]` | `false` |
| Value-add | `["Award Criterion", "Structural Container", "Unknown"]` | `false` |
| Relationship Management | `["Award Criterion", "Structural Container", "Unknown"]` | `false` |

These 4 criteria genuinely disagree, across extraction occurrences, on whether they are a scored leaf ("Award Criterion") or a grouping header ("Structural Container") — a real ambiguity Stage B's `evaluation_hierarchy.py` already detected and recorded (`role_conflict`/`role_observations`) but never promoted into Stage C's top-level `conflicts` list. Opportunity Structure is the **first layer to make this signal externally visible**, exactly as its docstring promises ("surfaces that already-computed signal as a governed conflict; it does not invent new conflict detection"). This is correct, wanted behavior, not a defect.

**Checked for the anomaly categories requested:**
- Mathematically impossible weight totals: not applicable — Opportunity Structure performs no weight summation itself; each record's own `weight`/`weight_value`/`weight_unit`/`weight_basis` is preserved as extracted, unmodified.
- Same criterion assigned to multiple categories incorrectly: not observed — every criterion's `scope`/`parent_stage`/`stage` fields are preserved verbatim per record; no merging across categories occurred (confirmed by `occurrence_count: 1` for all 83).
- Category-specific weights flattened globally: not observed — e.g. the "Corporate Profile" title (the subject of `CONF-EVAL-1`) still exists as 7 separate records with distinct `parent_stage` values and distinct weights, unchanged from Stage B.
- Duplicated stages: none — `collision_free: true`, 0 collisions.
- Missing hierarchy parents: `parent_stage: None` occurs only for genuinely top-level nodes (including the 4 role-conflicted ones and the 8 structural containers) — consistent with Stage B's own hierarchy, not a new gap introduced here.
- Unresolved weight conflicts represented as clean values: **none of the 4 `CONF-EVAL-*` topics' contributing records have `weight_conflict: true`** (confirmed: each is a set of *separate*, individually-consistent per-category records, exactly as established in the earlier Stage C hardening investigation) — so there is nothing for Opportunity Structure to have silently cleaned up; the ambiguity legitimately lives one level up, in Stage C's cross-record title-collision detector, which Opportunity Structure correctly does not attempt to replicate.

## G. Requirement structure

All 427 requirements represented, using the real controlled `category`/`requirement_type` values present in this corpus (no invented taxonomy):

| Category | Count |
|---|---:|
| Mandatory | 314 |
| Rated | 89 |
| Submission Compliance | 13 |
| Supporting | 9 |
| Financial | 1 |
| General Compliance | 1 |

| Requirement type | Count |
|---|---:|
| Submission Compliance | 127 |
| Commercial / Contractual | 72 |
| Evaluation / Scored | 61 |
| Technical Specification | 51 |
| Supplier Qualification | 42 |
| General Compliance | 58 |
| Delivery / SLA | 16 |

Sum of both breakdowns is 427 in each case — no requirement disappeared into a "convenient bucket": every requirement keeps its own `category` and `requirement_type` fields verbatim; there is no presentation-driven filtering anywhere in `build_opportunity_structure()`.

## H. Submission-rule scope audit — D1/D2/D3 regression check

All 8 "Rated Criteria Response Form"-family `SUBMISSION_RULE` records survive, each correctly scoped to its own source document — **D1, D2 (revised), and D3's page limits remain fully distinct**, exactly as the earlier Stage C hardening fix established:

| Record | Item | Details (verbatim) | Source document |
|---|---|---|---|
| `…56c6ac…` | Rated Criteria Response Form | *"Maximum 15 pages (excluding resumes or professional profiles, and work or product samples requested herein)..."* | `OriginalRevision/…Appendix D1…docx` |
| `…a0cd46…` | Rated Criteria Response Form | *"Maximum 12 pages (excluding resumes, professional profiles, and work or product samples)..."* | `Amendment1/…Appendix D2…REVISED.docx` |
| `…26c9ee…` | Rated Criteria Response Form | *"Responses must not exceed ten (10) pages..."* | `OriginalRevision/…Appendix D3…docx` |

**No global or re-collapsed page limit exists anywhere in the output.** D1=15, D2=12, D3=10 remain three separate `SUBMISSION_RULE` records with correct, distinct source-document scope, matching Canonical Opportunity's and Stage D's already-verified behavior for this same fact.

## I. Deliverables

All 23 accepted deliverables represented, with `title`/`obligation_state`/`quantity`/`unit`/`frequency`/`scope`/`due_milestone`/`responsible_actor`/`acceptance_criteria`/`conditions` all preserved verbatim as extracted:

```
obligation_state: MANDATORY (17), CONDITIONAL (6)
```
No deliverable was generalized beyond its source scope — every deliverable's `scope` dict (when present) is carried through unmodified from Stage B's `_contract_hygiene`-verified output; Opportunity Structure performs no scope rewriting.

## J. Commercial structure

All 91 accepted commercial clauses represented, grouped here by their existing `clause_kind` (a field already assigned by Stage B's `contract_hygiene.py`, not invented by Opportunity Structure):

```
REGULATORY_COMPLIANCE (14), TERMINATION (12), INSURANCE (7), CONFIDENTIALITY (7), DATA_PROTECTION_PRIVACY (6),
LIABILITY_INDEMNITY (5), SUBCONTRACTING (5), OTHER (5), CYBERSECURITY_SECURITY (4), INTELLECTUAL_PROPERTY (4),
BACKGROUND_CHECK_CLEARANCE (4), PAYMENT_WITHHOLDING_SETOFF (3), PERSONNEL_KEY_STAFF (3), EXCLUSIVITY_NONCOMPETE (3),
PRICING_ESCALATION (2), GOVERNING_LAW_DISPUTE (2), CHANGE_CONTROL (2), GUARANTEE_BOND (1), ASSIGNMENT (1),
AI_AUTOMATED_TOOLS (1)
```
Sum = 91 — all accounted for, none excluded. No clause meaning was transformed; each clause's `topic`/`details`/`source_fact` fields are carried through unmodified. This audit does not assess business risk (per instruction).

## K. Seven(now eight)-conflict trace

| Conflict | Category | Explanation |
|---|---|---|
| `CONF-EVAL-1..4` (evaluation weight discrepancies) | **C — outside Opportunity Structure's scope** | Stage C's detector compares *across* records by title alone; the individual `EVALUATION_CRITERION` records it references each have `weight_conflict: false` on their own (they are legitimately separate, internally-consistent per-category records, not a merged/contradictory single record) — there is nothing on any single record for Opportunity Structure's own `weight`-conflict surfacing rule to trigger, so it correctly does not represent this cross-record ambiguity as one of its own `conflicts`. The ambiguity remains fully visible in Stage C's own conflict list. |
| `conf_…INITIAL_DURATION` (`contract_term`) | **C — outside Opportunity Structure's scope** | Canonical-opportunity-sourced; Opportunity Structure does not consume `_canonical_opportunity` at all. |
| `conf_…BUYER_NAME` (`client`) | **C** | same reason |
| `conf_…SOLICITATION_NUMBER` (`file_number`) | **C** | same reason |
| `conf_…OPPORTUNITY_TITLE` (`title`) | **C** | same reason |

**Zero conflicts fall into category D (silently flattened/resolved).** All 8 remain fully, accurately represented exactly where they belong (Stage C's own conflict list), untouched by Opportunity Structure. Additionally, Opportunity Structure surfaces **4 of its own conflicts** (the `role_conflict` ambiguities, Section F) — a genuinely separate signal, correctly exposed rather than resolved, which is category **A (explicitly represented)** relative to Opportunity Structure's own schema.

## L. Contract-term scope safety

Searched every structural record for `"12 weeks"`, `"3 years"`, `"three years"`, `"contract duration"`, `"engagement duration"`, `"agreement term"`, `"contract term"` (18 raw hits; full list persisted in `contract_term_text_search.json`). Inspected every hit's actual content, not just the matched substring:

- **The canonical "3-year opportunity-wide initial term" and "12-week HR Advisory engagement duration" facts (the two subjects of the accepted contract-term audit) live exclusively in `canonical_opportunity.py`'s `typed_observations` channel — a completely separate Stage A field family from the 5 sections Opportunity Structure reads.** Opportunity Structure has no `contract_term` concept in its schema at all, so there is no field for either value to be asserted into, scoped or otherwise.
- **One genuine near-duplicate exists**: `REQUIREMENT` record `oi-requirements-40b3b745…` — *"Engagement duration: The engagement will be completed over approximately twelve (12) weeks."* This is the same real-world fact as the canonical 12-week observation, independently extracted into the `requirements` channel. **It is correctly scoped**: `rfso_ref: "HR Advisory pricing scenario, Row 5"` and `source_refs[0].sheet: "HR Advisory pricing scenario"` both explicitly tie it to HR Advisory; its own description says "Engagement duration," never "contract term"; and it is one undifferentiated requirement among 427, never elevated into any opportunity-wide field or heading. **It does not masquerade as a global contract term.**
- Every other hit is unrelated to contract duration: e.g. *"at least three (3) team-effectiveness…engagements within the last three (3) years"* (a supplier-experience requirement, not a term-length fact), *"Personal Information Retention and Deletion"* / *"Assurance Services Conflict of Interest"* (commercial clauses that merely reference "the contract term" as a time anchor, without asserting any duration value).

**Conclusion: Opportunity Structure does not independently recreate the scoped-vs-opportunity-wide semantic error the contract-term audit found and fixed in Canonical Opportunity** — it has no equivalent field to get wrong, and the one overlapping fact it does carry remains honestly, traceably scoped.

## M. Procurement-model consistency

Opportunity Structure's `FAMILIES` set (`REQUIREMENT`, `EVALUATION_CRITERION`, `COMMERCIAL_CLAUSE`, `DELIVERABLE`, `SUBMISSION_RULE`) has **no procurement-mechanic-equivalent family**. `PROCUREMENT_MECHANIC` typed observations belong exclusively to `canonical_opportunity.py`, which Opportunity Structure does not consume. A text search for `"multi-vendor"`, `"call-off"`, `"standing offer"`, `"panel agreement"`, `"single contract"` found 5 incidental hits, all inside ordinary requirement/clause text (e.g. clauses describing call-off/task-order mechanics as contract terms) — none of them constitute a competing, asserted "procurement model" classification. **Opportunity Structure does not represent a procurement model at all, and therefore cannot contradict Canonical Opportunity's `"Multi-vendor Call-off"` — there was no manual injection of the canonical value, and none was needed.**

## N. Master RFP contribution

- **218 of 692 records (31.5%)** cite the master RFP among their sources; **199 are sole-sourced from it**.
- By family: `REQUIREMENT` 105, `EVALUATION_CRITERION` 55, `SUBMISSION_RULE` 32, `COMMERCIAL_CLAUSE` 20, `DELIVERABLE` 6.
- Pages represented: 3–21 (every page of the master RFP's substantive body).
- Master-RFP-involving Stage C conflicts: all 3 identity conflicts (`title`/`client`/`file_number`) and all 4 `CONF-EVAL-*` conflicts involve master-RFP-sourced evidence (consistent with the master RFP being the primary consolidating document) — none of this is Opportunity Structure's own doing, since it doesn't compute conflicts across documents itself.
- **No implicit master-RFP precedence exists anywhere in `build_opportunity_structure()`** — records are deduplicated purely on exact semantic content, never on source-document identity or role; a master-RFP-sourced record does not out-rank or suppress an appendix-sourced one in any way.

## O. Provenance validation

| | Count |
|---|---:|
| Total structural (factual) records | 692 |
| VERIFIED | 380 |
| PARTIAL | 309 |
| UNVERIFIED (zero usable provenance) | 3 |
| Dangling references | 0 |
| Fabricated references | 0 |
| Structure-only containers requiring no independent evidence | 8 (`is_structural_container: true` evaluation-hierarchy headers) — 7 of these 8 still carry real, non-fabricated `source_refs` inherited from their originating record; none is asserted as a factual claim in its own right |

No record's provenance was upgraded, invented, or asserted beyond what its own `source_refs` support. The PARTIAL/UNVERIFIED proportion (312 of 692, 45%) reflects the same, already-audited-and-fixed `_validate_ref`/`_locator_matches` behavior from the contract-term audit — not a new gap; Opportunity Structure adds no additional laxity or strictness to that shared validator.

## P. Rejected-record safety

The 2 Stage B `ZERO_VALID_PROVENANCE` rejected records (`After-Sales Services`, deliverable; `Data Breach Investigation and Cooperation`, commercial clause) were checked by exact `deliverable_id`/`clause_id` identity and exact description/details text match against all 692 structural records.

```
REJECTED RECORD RE-ENTRY: 0
```

*(A first-pass check in this same commissioning used a cruder substring-containment heuristic and produced 3 false positives — a genuinely different deliverable that happens to mention "after-sales services" as one of several unrelated conditions, and two independently-extracted `requirements`-family records describing the same real-world after-sales clause via a different Stage A extraction channel with their own valid, independent provenance. None of these are the rejected record re-entering; this was a flaw in the audit script's search heuristic, not in production code, and was corrected before this section was finalized — see `rejected_record_safety_corrected.json`.)*

## Q. Determinism

`build_opportunity_structure()` was called twice, in memory, from the identical frozen input — no duplicate persisted commissioning run was created for this check:

```
run1_input_digest == run2_input_digest: True (identical hash)
full object equality: True
record order stable: True
```

Zero LLM calls in either invocation.

## R. Validators and anomalies

Existing regression suite (`tests/test_opportunity_structure.py`): **15 passed**. Additional anomaly checks performed against the real object:

| Check | Result |
|---|---|
| Missing structural members | 0 — all 692 input records accounted for |
| Duplicate member identities | 0 — `collision_free: true` |
| Source record represented in incompatible structures | not observed — each record belongs to exactly one family, matching its Stage B section |
| Unresolved conflict silently asserted | 0 — every flagged record's `conflict_ids` remains populated, no value was cleaned up |
| Invalid scope | 0 — `scope`/`rfso_ref` fields preserved verbatim, never rewritten |
| Globalized scoped fact | 0 — see Section L |
| Dangling provenance | 0 |
| Rejected-record re-entry | 0 (Section P, corrected) |
| Impossible evaluation hierarchy | not applicable — no weight math is performed by this module |
| Duplicate evaluation stages | 0 |
| Malformed grouping | 0 — `integrity_diagnostics.invalid_records: []` |
| Unsupported fact family | 0 |
| Inconsistent canonical identity | not applicable — this module does not touch canonical identity fields |

**No defect was found.** No code change was required; Section 20's remediation protocol was not triggered.

## S. Artifact index

- `evaluation/bank_of_canada_briefing_pack/opportunity_structure_commissioning/oppstruct-boc-2026-026-20260912T144353Z-dd4b10/`
  - `run_metadata.json`, `determinism_check.json`, `upstream_accounting.json`
  - `opportunity_structure_full.json` (complete 692-record object)
  - `d1_d2_d3_scope_check.json`, `contract_term_text_search.json`, `procurement_model_text_search.json`
  - `requirement_breakdown.json`, `deliverable_breakdown.json`, `commercial_clause_breakdown.json`
  - `provenance_summary.json`, `master_rfp_contribution.json`, `evaluation_role_conflicts_detail.json`
  - `rejected_record_safety_corrected.json`
- `evaluation/bank_of_canada_briefing_pack/phase3_commissioning/phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8/`
  - `stage_c_conflicts.json` (8 conflicts), `stage_c_normalized_facts.json`, `stage_c_refresh_verification.json`, `run_metadata.json`
- Commissioning script: [scripts/commission_opportunity_structure_bank_of_canada.py](../../scripts/commission_opportunity_structure_bank_of_canada.py)

---

## Human-readable Opportunity Structure view

**Documents:** 16 (unchanged corpus).

**Records by family:**

| Family | Count | VERIFIED | PARTIAL | UNVERIFIED | Own conflicts |
|---|---:|---:|---:|---:|---:|
| REQUIREMENT | 427 | — | — | — | 0 |
| EVALUATION_CRITERION | 83 | — | — | — | 4 (role ambiguity) |
| SUBMISSION_RULE | 68 | — | — | — | 0 |
| DELIVERABLE | 23 | — | — | — | 0 |
| COMMERCIAL_CLAUSE | 91 | — | — | — | 0 |
| **Total** | **692** | **380** | **309** | **3** | **4** |

**D1/D2/D3 submission page limits (distinct, correctly scoped):**
- D1: 15 pages (`OriginalRevision/…Appendix D1…docx`)
- D2 (revised): 12 pages (`Amendment1/…Appendix D2…REVISED.docx`)
- D3: 10 pages (`OriginalRevision/…Appendix D3…docx`)

**Requirements by category:** Mandatory 314 · Rated 89 · Submission Compliance 13 · Supporting 9 · Financial 1 · General Compliance 1

**Commercial clauses by kind (top 5):** Regulatory Compliance 14 · Termination 12 · Insurance 7 · Confidentiality 7 · Data Protection/Privacy 6 *(+ 15 more kinds, 91 total)*

**Deliverables:** 23 total — 17 Mandatory, 6 Conditional

**Evaluation criteria with an unresolved role ambiguity (Award Criterion vs. Structural Container vs. Unknown):** Relevant Experience and References · Measurement Approach · Value-add · Relationship Management — all 4 remain flagged, none silently resolved.

**Fields Opportunity Structure does not represent at all:** contract term, procurement model/mechanic, dates/milestones, buyer/title/solicitation-number identity — these remain exclusively Canonical Opportunity's domain, exactly as designed.

This is what Bid Intelligence's Opportunity Structure layer currently, structurally holds — no business interpretation, no strategy, no recommendation added.

---

## FINAL RESPONSE

- **UPSTREAM INPUT LOCK: PASS**
- **OPPORTUNITY STRUCTURE BUILD: PASS**
- **PROVENANCE VALIDATION: PASS**
- **CONFLICT/SCOPING PRESERVATION: PASS**
- **OPPORTUNITY STRUCTURE COMMISSIONING: PASS**
- **Run ID:** `oppstruct-boc-2026-026-20260912T144353Z-dd4b10`
- **Production function:** `opportunity_structure.build_opportunity_structure(stage_facts, package_metadata)`
- **Actual upstream dependencies used:** Stage B's `requirements`/`evaluation_criteria`/`commercial_clauses`/`deliverables`/`submission_rules` (latest regenerated artifact) + deterministically-reconstructed `package_metadata`. No `_canonical_opportunity`, no Stage C `conflicts`, no Stage D.
- **Was a Stage C refresh required?** Not for Opportunity Structure's own output (proven input-identical either way) — but yes, performed anyway, to keep this report's conflict-tracing accurate against the contract-term audit's changes. Zero LLM calls; 4 evaluation conflicts confirmed stable; new run `phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8` (7→8 total conflicts).
- **LLM calls / cost:** 0 / $0
- **Output schema/types:** `{schema_version, documents, records[], conflicts[], coverage, integrity_diagnostics, input_digest}` — plain dicts/lists, no LLM-authored content
- **Total structural item counts:** 692 records (427 requirements, 83 evaluation criteria, 68 submission rules, 23 deliverables, 91 commercial clauses), 4 internal conflicts
- **Input/output accounting by family:** 427/427, 83/83, 68/68, 23/23, 91/91 — zero silent record disappearance
- **D1/D2/D3 outcome:** PASS — all 3 remain distinct, correctly scoped, no global collapse
- **Contract-term scope outcome:** PASS — no equivalent field exists; the one overlapping fact (12-week HR Advisory engagement duration, extracted independently as a requirement) remains correctly, traceably scoped, never opportunity-wide
- **Procurement-model outcome:** PASS — not represented at all, therefore cannot contradict Canonical Opportunity's `"Multi-vendor Call-off"`; nothing manually injected
- **7(8) conflict outcomes:** all 8 category C (outside Opportunity Structure's scope, fully preserved in Stage C); 0 category D; plus 4 additional, correctly-surfaced Opportunity-Structure-own conflicts (evaluation role ambiguity)
- **Master RFP contribution:** 218/692 records (199 sole-sourced), pages 3–21, no implicit precedence
- **Rejected-record re-entry count:** 0 (corrected after an audit-script false positive was caught and fixed)
- **Provenance error count:** 0 dangling, 0 fabricated; 3/692 records fully unverified (honestly represented as such)
- **Defects found/fixed:** 0 — no code change required
- **Tests added:** 0 (none needed; existing 15 pass)
- **Full-suite result:** not rerun in full for this commissioning since no production code changed (existing `tests/test_opportunity_structure.py`: 15/15 passed; the full repository suite last confirmed green — 1194 passed, 2 skipped — at the end of the contract-term audit, immediately prior to this commissioning, with no production file touched since)
- **Runtime:** ~1–2s for the structure build and full analysis script
- **Report path:** [evaluation/bank_of_canada_briefing_pack/BANK_OF_CANADA_OPPORTUNITY_STRUCTURE_COMMISSIONING_REPORT.md](evaluation/bank_of_canada_briefing_pack/BANK_OF_CANADA_OPPORTUNITY_STRUCTURE_COMMISSIONING_REPORT.md)
- **Raw artifact paths:** `evaluation/bank_of_canada_briefing_pack/opportunity_structure_commissioning/oppstruct-boc-2026-026-20260912T144353Z-dd4b10/`; refreshed Stage C: `evaluation/bank_of_canada_briefing_pack/phase3_commissioning/phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8/`

Per instruction, this commissioning stops here. **Opportunity Intelligence has not been started.**
