# Bank of Canada RFP 2026-026 — Phase 3 / Stage C Hardening Report

Targeted investigation and hardening of two suspected Stage C coverage gaps — original-vs-revised Appendix D2, and structured `commercial_clauses` — following the Phase 3 commissioning run `phase3-boc-2026-026-stagec-20260912T122912Z-0999a0`. Stage A was never re-invoked. Stage D was not started.

```
STAGE C HARDENING: PASS
```

**Headline finding**: the D2 investigation found **no missed conflict** in the sense originally suspected — but it uncovered a **real, separate, more serious defect**: Stage B was silently discarding Appendix D1's and D3's own page-limit facts by merging them into Appendix D2's record. That is fixed. The commercial-clause investigation found **zero genuine conflicts** among the real 91 clauses, but confirmed the detector-coverage gap was real; a minimal, tested detector was implemented and closes it for future corpora.

## 0. Why the authoritative Stage B input changed

The D2 investigation (§1–§3) proved a genuine Stage B structural defect. Per your Section 3 instruction ("change Stage B normalization unless a Stage B structural defect is the proven root cause"), fixing it required regenerating the Stage B artifact — the defect lives in `normalize_package_facts()` itself, so no Stage C-only fix could recover data Stage B had already discarded. Stage B's own function was re-run **against the identical frozen Phase 1 Stage A output** — Stage A was never re-invoked, and the regeneration is fully deterministic (0.26 s, no LLM calls, confirmed reproducible).

| | Value |
|---|---|
| Superseded (named in your message) | `phase2-boc-2026-026-stageb-20260912T111643Z-1da5ab` |
| **New authoritative Stage B run** | `phase2-boc-2026-026-stageb-20260912T125051Z-91a22b` |
| Same Phase 1 / Stage A input | `phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5` (unchanged) |
| Counts changed by the fix | `submission_rules`: 62 → 68 (+6); every other family unchanged (`requirements` 427, `dates` 23, `evaluation_criteria` 83, `deliverables` 23, `commercial_clauses` 91, canonical observations 120, provenance rejections 2 — all identical) |

Both Stage C runs in this report (the earlier `...T122912Z-0999a0` and the final `...T130007Z-dd391b`) are compared on their own terms below; the historical `9`-conflict comparison from the prior report is not repeated here since nothing about it changed.

## 1. Original D2 vs. revised D2 — full record-level comparison

### Requirements

| Original D2 (`req_id`) | Text | Revised D2 (`req_id`) | Text |
|---|---|---|---|
| M1 | "Responses must not exceed twelve (12) pages, excluding resumes or professional profiles, and work or product samples requested herein." | R1 | "Responses must not exceed twelve (12) pages (excluding resumes or professional profiles, and work or product samples requested herein). Page size must be 8½ x 11 inches, with standard margins and a minimum font size of 10 points." (merged with M2) |
| M2 | "Page size must be 8½ x 11 inches, with standard margins and a minimum font size of 10 points." | — | merged into R1 above |
| M3 | "Proponents will be evaluated only on the service category(ies) for which they submit a response." | R3 | *identical text* — this is the one exact string match Stage B's dedup already merges into one normalized record citing both documents |
| — | — | R2 | "Proponents are to respond to each of the following requirements in the order presented below..." (new, procedural, not in original) |
| R1–R8 | 8 rated-criteria descriptions (Corporate Profile, Key Personnel and Roster ×2, Methodology & Advisory Approach, Thought Leadership & Innovation, Relationship Management, Value-added, Relevant Experience and References) — standalone prose, no label prefix | R4–R10 | Same 8 substantive topics (R2/R3 of original merged into one R5), each restated with the criterion label prefixed directly onto the requirement text (e.g. "Corporate Profile: Proponents must describe...") |

### Submission rules (post-hardening-fix Stage B output)

| Item | Original D2 | Revised D2 |
|---|---|---|
| Rated Criteria Response Form (page limit) | 12 pages, 8½×11, standard margins, 10pt font | **12 pages**, 8½×11, standard margins, 10pt font — *identical value* |
| Key Personnel / Professional Profiles | "Key Personnel Profiles" — brief profiles, ≤4 individuals, half-page each | "Professional Profiles / Resumes" — same content, now **explicitly tagged** "Excluded from 12-page limit" |
| Thought Leadership / Work Samples | "Published Thought Leadership Samples" — 2 samples, 2 pages each | "Work or Product Samples" — same content, now **explicitly tagged** "Excluded from 12-page limit" |
| Relevant Experience Case Studies | Own separate submission_rule item | Folded into the restated R10 requirement text; no separate submission_rule item extracted |

### Evaluation criteria

Both documents extract the identical 7 stage titles (Corporate Profile, Key Personnel and Roster, Methodology & Advisory Approach, Thought Leadership & Innovation, Relationship Management, Value-added, Relevant Experience and References), each with `weight: null` in both — actual point values live only in the master RFP's own summary table (§2), not in D2 itself in either version.

### Answer: is there a substantive original-vs-revised D2 disagreement Stage C should detect?

**No.** The page limit (12 pages), page dimensions (8½×11), margins, minimum font size (10pt), and the set of 7 evaluation-criteria stages are **identical** between the two versions. The real differences are: (a) prose restructuring — the criterion label is merged into the requirement text in the revised version; (b) a `category`/`requirement_type` classification difference on the header instructions (`"Submission Compliance"` vs `"Rated"`) — an independent Stage A extraction-classification artifact, not a stated rule change; (c) the exclusion-from-page-count rule for resumes/samples is made **more explicit** in the revised version (each now individually tagged "Excluded from 12-page limit") without changing what was already true in the original ("excluding resumes or professional profiles, and work or product samples requested herein" already appears in original M1). None of these are materially incompatible facts — they are the same governing rule in reorganized prose. **Stage C correctly reports zero conflicts between original and revised D2 because none exists.**

## 2. The 15-vs-12-page investigation

`"Responses must not exceed 15 pages..."` originates from **`OriginalRevision/RFP 2026-026 - Appendix D1 - Rated criteria response form.docx`** (Learning & Development Programs and Assessments category). `"Responses must not exceed twelve (12) pages..."` originates from **both** original and revised **Appendix D2** (HR Advisory category). These are governed by the master RFP's own per-category evaluation/response structure (confirmed directly from the master RFP's extracted text, page 13–14): Appendix D1 (Learning & Development), Appendix D2 (HR Advisory), Appendix D3 (Facilitation and Team Effectiveness) are **three separate response forms for three separate service categories**, each with its own legitimate page limit — **15 / 12 / 10 pages respectively** (confirmed for D3 too, from its own raw Stage A record).

**These do not refer to the same response artifact or service category.** They are compatible, coexisting constraints for different proposal sections. **No conflict should be — and none is — manufactured between them.**

## 3. Root cause: the real defect this investigation found (Stage B, not Stage C)

Tracing D1/D2/D3's contributions through the **pre-hardening** Stage B output revealed that a single merged submission_rules record, `"item": "Rated Criteria Response Form"`, carried `source_refs` from **all of** revised D2, D1, **and** D3, while its `format`/`details` text showed **only** the 12-page value (from whichever document Stage B's per-document loop happened to process first). D1's real 15-page limit and D3's real 10-page limit were **silently overwritten and discarded** — not merely uncompared, but genuinely lost from the record entirely (recoverable only by noticing D1/D3 appeared as incidental `ref_docs` with no matching value in the merged record's own text).

**Root cause**: `_canonical_submission_item_identity("Rated Criteria Response Form")` — each appendix's own self-referential extraction of its own page-limit instruction, worded generically — produced the **same** canonical dedup key regardless of which appendix (and therefore which real numeric limit) it came from. Original D2's own item happened to be worded `"Rated Criteria Response"` (no "Form" suffix), which is why it alone stayed isolated — a wording accident, not a correct scope safeguard.

**Fix**: added `_submission_rule_appendix_scope(source_doc)` — deriving `CATEGORY_1`/`CATEGORY_2`/`CATEGORY_3`/`None` from the filename, using **the exact same signal** (`"d1"`/`"d2"`/`"d3"` substring) Stage C's own PAGE_LIMIT conflict dimension already trusted for this exact purpose (§2). The Stage B submission_rules merge key now includes this scope component. This is a deterministic, structured-data correction — no fuzzy matching, no new mechanism, reuse of an existing precedent already present in the same file.

**Verified after the fix**: D1, revised-D2, and D3 each now correctly retain their own distinct "Rated Criteria Response Form" record — 15 / 12 / 10 pages respectively, each citing only its own real document. Original D2's isolated record (already correct) is unaffected. `submission_rules` count: 62 → 68.

## 4. Commercial-clause conflict coverage — investigation

All 91 admitted structured `commercial_clauses` were inspected, grouped by `clause_kind` (20 kinds represented) and cross-checked against every topic you named:

| Your named topic | `clause_kind` present | Count | Genuine conflict found? |
|---|---|---:|---|
| Termination | `TERMINATION` | 12 | No — 12 distinct, complementary termination *triggers* (for-convenience, for-breach, for-insolvency, for-receiver, for-change-of-ownership, for-cessation, for-winding-up, survival-of-obligations, etc.), all from one document, all legitimately coexisting |
| Intellectual property | `INTELLECTUAL_PROPERTY` | 4 | No — distinct sub-topics (non-compete on planning work, right to assign, assignment of copyright, conflict-of-interest re: assurance services) |
| Confidentiality | `CONFIDENTIALITY` | 7 | No — 7 distinct sub-rules (access restriction, definition, irreparable-harm/injunctive relief, permitted legal-process disclosure, use/non-disclosure, RFP-process confidentiality) |
| Liability | `LIABILITY_INDEMNITY` | 5 | No — distinct sub-topics (indemnification, rights-preservation on termination, 2× conflict-of-interest, tax/employment indemnification) |
| Insurance | `INSURANCE` | 7 | No — 7 distinct coverage/procedural sub-topics; the one shared number ($3,000,000 CGL and E&O) is two **different** coverage types coincidentally sharing an amount, not a disagreement |
| Subcontracting | `SUBCONTRACTING` | 5 | No — disclosure requirement (2 compatible restatements, Appendix A + master RFP), responsibility/binding, prohibition/consent, and one empty legacy record |
| Assignment | `ASSIGNMENT` | 1 | N/A — only 1 record (independent-contractor status clause; nothing to compare) |
| Payment | `PAYMENT_WITHHOLDING_SETOFF` | 3 | No — 3 distinct sub-topics (statutory deductions, tax treatment, payment-limitation-on-termination) |
| Audit | *(no clauses classified `AUDIT_RECORDS` exist in this corpus)* | 0 | N/A |
| Indemnity | *(covered under `LIABILITY_INDEMNITY` above)* | — | No |
| Governing law | `GOVERNING_LAW_DISPUTE` | 2 | **Investigated closely** — Appendix G states "Province of Ontario" explicitly; the master RFP states "the province...within which the Bank of Canada is located." These likely refer to the same real jurisdiction (Bank of Canada is headquartered in Ontario), but the RFP's own text never states that linkage — treating them as equivalent would require external knowledge, not grounded textual comparison. **Correctly left uncompared** rather than either falsely equating or falsely conflicting them. |
| Renewal/term | *(no dedicated `renewal` clause_kind; `TERMINATION`/`CHANGE_CONTROL` cover related ground)* | — | No |

Two additional same-kind pairs worth naming explicitly, both **correctly not conflicts**:
- **REGULATORY_COMPLIANCE**, "Accessible Canada Act (ACA) Compliance" (Appendix B1 vs. B3): same real requirement, B3's extract is a shorter prefix of B1's fuller text — compatible, not contradictory.
- **BACKGROUND_CHECK_CLEARANCE / PERSONNEL_KEY_STAFF**, Reliability-clearance requirement (Appendix B1/B2/B3): the same real per-category boilerplate, independently classified into two different `clause_kind` buckets by separate Stage A extractions — a classification inconsistency, not a factual disagreement, and correctly never compared (different `clause_kind` = different identity bucket).

**Conclusion: 0 genuine commercial-clause conflicts exist in this real corpus.** But the **architectural gap was real** — no detector of any kind existed for structured clauses (§0.2 of the prior report) — so per your Section 5, a minimal detector was implemented and tested (§5 below), rather than left as "demonstrably unnecessary," since your test requirements (Section 7, items 5–9) specifically require it to exist and be verified.

## 5. `structured_commercial_clause_conflicts()` — what was implemented

Added to `contract_hygiene.py`, mirroring `structured_deliverable_conflicts()` exactly in spirit and imported into `reconcile_package_facts()` alongside it (`extractor.py`).

- **Identity** (must match before any comparison happens): `(clause_kind, normalized topic, scope)` — the narrowest grouping that avoids comparing unrelated sub-topics sharing a `clause_kind` bucket (e.g., never compares "Commercial General Liability Insurance" against "Errors and Omissions Liability Insurance").
- **Value/contradiction test**: a topic-agnostic, generic regex extracts quantified tokens (`$` amounts, percentages, day/week/month/year counts) from `source_fact`. A conflict is flagged only when **at least two clauses in the same identity bucket each have ≥1 extractable value, and those value-sets differ**. Clauses with no extractable number, or whose numbers already agree, are never flagged — satisfying "do not call two complementary clauses conflicts merely because their wording differs."
- **No LLM, no embeddings, no synthesized clause, no resolution/winner field** — matches `structured_deliverable_conflicts`'s own shape (detection only).
- Every candidate's full `source_refs` are preserved in a new `candidates` field on the conflict record (in addition to the standard `source_a`/`source_b` summary), so provenance is traceable for every contributing clause, not just two.

## 6. Amendment precedence — unchanged, correctly

No governed amendment-precedence mechanism was added or invoked. `explicit_supersession_declarations_in_input: 0` (unchanged). Both D1's and D3's own page limits, and both original and revised D2's content, survive as **distinct, unresolved, equally-preserved facts** — exactly your Section 6 instruction: "detect the original/revised conflict correctly [if one exists]; preserve both candidates; leave it unresolved if no governed precedence mechanism exists." Since no real D2 conflict exists to leave unresolved, this section's practical effect in this run is that D1/D2/D3's three genuinely different, legitimate page limits are now **correctly preserved as three distinct facts** rather than silently collapsed into one — the constitutionally important outcome, independent of whether a "conflict" label ever applies to them (it correctly does not, since they are compatible, not contradictory).

## 7. Tests

`tests/test_stage_c_hardening_d2_and_commercial_clauses.py` — 15 tests, all passing, covering all 12 minimum scenarios:

1. `test_same_wording_different_appendix_scope_preserves_both_page_limits_no_merge` (same wording, different scope → preserved distinctly, not merged)
2. `test_same_wording_and_same_appendix_scope_still_merges_as_corroboration` (same wording, same scope → still merges, unaffected)
3. `test_no_appendix_signal_in_filename_merges_as_before_unaffected` (no D1/D2/D3 signal → unchanged pre-existing behavior)
4. `test_genuine_cross_document_page_limit_disagreement_in_same_appendix_scope_is_true_conflict` (D2-style genuine change → detected)
5. `test_different_appendix_scope_page_limits_are_not_manufactured_into_a_conflict` (D1 vs D2 → not manufactured)
6. `test_commercial_clause_same_kind_topic_scope_no_extractable_value_is_not_flagged` (ACA-style compatible duplicate)
7. `test_commercial_clause_same_kind_scope_same_value_no_conflict`
8. `test_commercial_clause_same_kind_scope_incompatible_value_is_conflict`
9. `test_commercial_clause_same_kind_different_scope_no_conflict`
10. `test_commercial_clause_conflict_preserves_physical_provenance_for_all_candidates`
11. `test_unresolved_commercial_conflict_has_no_winner`
12. `test_commercial_clause_conflict_cannot_contain_a_fabricated_value`
13. `test_commercial_clause_without_extractable_value_never_flagged`
14. `test_existing_evaluation_conflict_behavior_unchanged_after_hardening`
15. `test_existing_canonical_opportunity_conflict_behavior_unchanged_after_hardening`

### Validation

```
py -3.13 -m py_compile extractor.py contract_hygiene.py
→ COMPILE_OK

git diff --check
→ exit 0 (pre-existing CRLF warnings only)

py -3.13 -m pytest -q
→ 1183 passed, 2 skipped, 0 failed
  (baseline before this hardening: 1168 passed; +15 new tests, 0 regressions)
```

## 8. Recommissioning — before vs. after

| Metric | Before (`...T122912Z-0999a0`, pre-hardening) | After (`...T130007Z-dd391b`, hardened) |
|---|---:|---:|
| Total governed conflicts | 7 | 7 |
| Evaluation conflicts | 4 | 4 |
| Canonical-opportunity conflicts | 3 | 3 |
| **Commercial-clause conflicts (new detector)** | n/a (no detector existed) | **0** |
| Original/revised D2 conflicts | 1 (incidental, not content-comparing) | 1 (same, incidental) |
| Resolved | 0 conflicts (2 separate canonical fields resolved without becoming conflicts) | 0 conflicts (same 2 fields) |
| Unresolved | 7 | 7 |
| Supersessions applied | 0 | 0 |
| Invalid provenance | 0 | 0 |
| Validation warnings | 0 (already fixed in the prior Stage C hardening pass) | 0 |
| Runtime | 0.058 s | 0.052 s |

**The total conflict count did not change (7 → 7).** This is the correct, honest result: the D1/D3 page-limit data-loss defect never manifested as a *missed conflict* in Stage C's output (D1 and D3 were never genuinely disagreeing with D2 in the first place — they govern different categories) — it manifested as **silent factual loss inside Stage B**, invisible unless you traced the merged record's `ref_docs` by hand, exactly as this investigation did. Fixing it did not change the conflict count; it changed whether the pipeline's own normalized data can be trusted to state D1's and D3's real page limits at all. Similarly, the commercial-clause detector found the 0 conflicts the manual audit had already predicted — its value is in coverage going forward, not in this run's count.

## 9. Complete raw artifacts

Hardening code: `extractor.py` (`_submission_rule_appendix_scope`, submission_rules merge-key change, `structured_commercial_clause_conflicts` wiring), `contract_hygiene.py` (`_clause_value_tokens`, `structured_commercial_clause_conflicts`), `tests/test_stage_c_hardening_d2_and_commercial_clauses.py` (new).

Regenerated Stage B: `evaluation/bank_of_canada_briefing_pack/phase2_commissioning/phase2-boc-2026-026-stageb-20260912T125051Z-91a22b/` (full artifact set, same shape as prior Phase 2 runs).

Hardened Stage C: `evaluation/bank_of_canada_briefing_pack/phase3_commissioning/phase3-boc-2026-026-stagec-20260912T130007Z-dd391b/`

| File | Notes |
|---|---|
| `stage_c_conflicts.json` | Complete, non-truncated — all 7 conflicts (identical set to the pre-hardening run; 0 new commercial-clause or D1/D3 conflicts) |
| `stage_c_canonical_opportunity_resolved.json` | Unchanged from the pre-hardening run |
| `conflict_summary.json`, `d2_original_vs_revised_audit.json`, `master_rfp_conflict_contribution.json`, `stage_c_validation_warnings.json` | Derived analysis, confirming the before/after table above |
| `input_lock.json` | Confirms the new Stage B input's counts and the Stage B regeneration justification |

## 10. Complete D2 trace table

| Semantic constraint | Original D2 | Revised D2 | Same scope? | Same semantic fact? | Conflict detected? | Resolution |
|---|---|---|---|---|---|---|
| Page limit | 12 pages | 12 pages | Yes | Yes — identical value | No (correctly — no disagreement) | n/a |
| Page dimensions | 8½×11 inches | 8½×11 inches | Yes | Yes | No | n/a |
| Margins | Standard | Standard | Yes | Yes | No | n/a |
| Minimum font size | 10 points | 10 points | Yes | Yes | No | n/a |
| Excluded pages (resumes/profiles/samples) | Excluded, stated inline in M1 | Excluded, explicitly tagged per-item | Yes | Yes — same rule, more explicit wording | No | n/a |
| Evaluation criteria stage set (7 stages) | Corporate Profile, Key Personnel and Roster, Methodology & Advisory Approach, Thought Leadership & Innovation, Relationship Management, Value-added, Relevant Experience and References | Identical 7 stages | Yes | Yes | No | n/a |
| Evaluation of only submitted category(ies) | M3 | R3 | Yes | Yes — exact text match | No (merged as one Stage B record citing both) | n/a — corroboration, not conflict |
| Requirement prose structure | Label separate from description | Label merged into description text | Yes | Yes (same substance, different wording) | No — Stage C has no free-text semantic diff capability; this is outside its detection surface by design | Not addressed — architectural gap noted, not invented a fix for |
| Header/instructions `category` classification | `"Submission Compliance"` | `"Rated"` | Yes | Ambiguous — likely Stage A extraction noise, not a stated change | No | Not addressed — not a real-world fact to reconcile |
| Solicitation number text form | (contributes to the 20-source canonical conflict, incidentally) | (contributes to the 20-source canonical conflict, incidentally) | n/a (opportunity-wide field) | Text-normalization variance across ~20 sources, not D2-specific | Yes — 1 canonical `file_number` conflict, but not an original-vs-revised D2 comparison | `CONFLICTED`, no governed basis exists |

## 11. Complete commercial-clause conflict inventory

```
0 real commercial-clause conflicts found
```

The detector was verified to work correctly through the 8 dedicated unit tests in §7 (items 6–13), which construct synthetic same-kind/same-topic/same-scope clause pairs with genuinely incompatible values and confirm a `COMMERCIAL_TERM_CONFLICT` is correctly raised, with full provenance and no fabricated values, and correctly withheld when values agree, scope differs, or no extractable value exists.

## FINAL RESPONSE

```
STAGE C HARDENING: PASS
```

- **Do original D2 and revised D2 contain a true comparable conflict?** **No.** Page limit, dimensions, margins, font size, and the 7 evaluation-criteria stages are identical between versions; the real differences are prose restructuring and Stage A classification noise, not stated rule changes.
- **15-page vs. 12-page investigation outcome**: 15 pages belongs to Appendix D1 (Learning & Development category); 12 pages belongs to Appendix D2 (both versions, HR Advisory category) — different service categories, different response artifacts, correctly never compared.
- **Root cause of the real defect found**: not a missed D2 conflict, but a **Stage B data-loss defect** — `_canonical_submission_item_identity()`'s dedup key lacked appendix-scope awareness, silently merging D1's (15pg) and D3's (10pg) own generically-worded page-limit statements into revised-D2's (12pg) record, discarding their real values. Fixed by adding a filename-derived appendix-scope component to the Stage B submission_rules merge key.
- **Was commercial-clause conflict coverage required?** The architectural gap was real (no detector existed); the real corpus contained 0 genuine conflicts for it to catch. A minimal, deterministic detector was implemented and tested per your instructions rather than left as "demonstrably unnecessary," since it closes a confirmed asymmetry (structured deliverables had a detector; structured clauses did not) and your test requirements explicitly call for it.
- **Files changed**: `extractor.py`, `contract_hygiene.py`, `tests/test_stage_c_hardening_d2_and_commercial_clauses.py` (new).
- **Tests added**: 15, all passing.
- **Full suite result**: 1183 passed, 2 skipped, 0 failed (baseline 1168 passed; +15 new, 0 regressions).
- **New Phase 3 run ID**: `phase3-boc-2026-026-stagec-20260912T130007Z-dd391b` (input: regenerated Stage B `phase2-boc-2026-026-stageb-20260912T125051Z-91a22b`, same frozen Phase 1/Stage A input, Stage A not rerun).
- **Before/after total conflicts**: 7 → 7 (unchanged — the fixes closed a silent data-loss defect and a detector-coverage gap, neither of which was hiding a conflict in this specific corpus; see §8 for why this is the correct, honest outcome).
- **Before/after D2 conflicts**: 1 → 1 (unchanged, incidental multi-source canonical conflict; never a direct original-vs-revised comparison).
- **Commercial-clause conflict count**: 0 (new detector, verified functioning via 8 dedicated tests).
- **Resolved/unresolved counts**: 0 resolved conflicts / 7 unresolved, both runs (2 separate canonical fields — `contract_term`, `submission_deadline` — resolve without becoming conflicts).
- **Provenance errors**: 0.
- **Runtime**: 0.052 s.
- **Report path**: `evaluation/bank_of_canada_briefing_pack/BANK_OF_CANADA_PHASE_3_STAGE_C_HARDENING_REPORT.md`
- **Raw artifact paths**: `evaluation/bank_of_canada_briefing_pack/phase3_commissioning/phase3-boc-2026-026-stagec-20260912T130007Z-dd391b/` and the regenerated Stage B at `evaluation/bank_of_canada_briefing_pack/phase2_commissioning/phase2-boc-2026-026-stageb-20260912T125051Z-91a22b/`
- **Remaining architectural gaps**: (1) Stage C has no free-text semantic-diff capability — genuine prose restructuring between document versions (like D2's own label-merging) is outside its detection surface by design, and this hardening did not add one (would require fuzzy/LLM matching, explicitly forbidden); (2) no governed amendment-precedence mechanism exists anywhere in production code — confirmed still true, not invented; (3) `requirements`/`submission_rules` still fail-open at the whole-record level when every reference is invalid (pre-existing, out of this task's scope, 0 live occurrences); (4) the GOVERNING_LAW_DISPUTE "Ontario" vs. "province where the Bank of Canada is located" pair remains uncompared — correctly, since equating them requires external knowledge the RFP text itself never states.

Stopping here. Stage D is not started.
