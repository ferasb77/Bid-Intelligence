# Fast Analysis V4 — Source-Truth Reconciliation

**Zero new API calls in this package.** Everything below is deterministic reconciliation over the
already-persisted V4 run (`fastanalysis-v4-boc-2026-026-20260914T130015Z-e0720d`) and direct,
independent re-inspection of the authoritative 16-document corpus text. No extraction code, routing,
concurrency, or Deep Verify behavior was touched.

## 1. Evaluation table reconciled against source truth

Direct text search of the master RFP (with page-marker mapping) confirms the true structure of the
"4.5 Rated criteria" table, spanning pages 15–16:

| Category | Form | Criteria | Total | Source pages |
|---|---|---|---|---|
| 1 — Learning & Development | D1 | 7 | 75 pts | 15 |
| 2 — HR Advisory | D2 | **7** | **75 pts** | 15–16 (continues across a page break) |
| 3 — Facilitation & Team Effectiveness | D3 | 6 | 100 pts (incl. 25-pt Price) | 16 |

Category 2's own table **does** continue across the page 15→16 boundary with "Value-add: 5 points"
and "Relevant Experience and References: 5 points" — confirmed by exact character-offset inspection:
this pair sits directly after Category 2's "Relationship Management" row and directly before
"Appendix D3" begins, with no repeated "Appendix D2" heading needed for a same-table continuation
(exactly matching how Category 1's and Category 3's own tables are structured). **V4's report was
already correct on this point** — its live extraction (not a fallback) already showed all 7 rows.

Full per-criterion record (category, name, weight, source document, source page) is in
`BANK_OF_CANADA_SOURCE_TRUTH_REPORT_BASELINE.json`.

## 2. Authoritative primary evaluation count

**`AUTHORITATIVE_PRIMARY_EVALUATION_COUNT = 20`** (7 + 7 + 6), not the historical `18`. The 18-item
gate — inherited from Deep Verify's own published Category 2 table (5 rows) and used as the
acceptance target since Fast Analysis V1 — is **retired** in favor of this source-verified count.

## 3. Reassessment of the historical "evaluation-weight ambiguity"

Occurrence-by-occurrence, using explicit category context from the same source table:

| Label | Occurrences found | Scope | Classification |
|---|---|---|---|
| Corporate Profile | 5 (D1), 5 (D2), 10 (D3) | Each explicitly scoped to its own category | LEGITIMATE_CATEGORY_SCOPING |
| Key Personnel and Roster | 15 (D1), 15 (D2), 20 (D3) | Each explicitly scoped | LEGITIMATE_CATEGORY_SCOPING |
| "Methodology" (as named by the historical report) | "Methodology and Advisory Approach: 35" (D2) and "Facilitation Methodology: 30" (D3) — two **differently-named** criteria, not one repeated label | Each scoped to its own category | LEGITIMATE_CATEGORY_SCOPING (and a label-conflation error in the historical claim — these aren't even the same criterion name) |
| "100 points" (historical report's claimed 3rd Key Personnel value) | Confirmed: this is Category 3's own **"Total points: 100 points"** row, not a Key Personnel value at all | N/A | Historical misattribution |
| A "Methodology: 5 points" value (as historical report claims) | Searched exhaustively across the full master RFP text — **does not exist anywhere in the corpus** | N/A | Historical fabrication/error |

**No genuine same-scope conflict was found anywhere in the 16-document corpus.**

**Classification: `FALSE_POSITIVE_FROM_SCOPE_CONFLATION`.** Retired from the Bank of Canada report
per instruction 3.

## 4. Redefined ambiguity acceptance gate

The old gate ("all 3 ambiguity classes must fire") is replaced with **AMBIGUITY ASSESSMENT
ACCURACY** — correctly classifying each class's true evidence state, not requiring every class to
be `PRESENT`:

| Class | Source-supported expected state | V4's actual result | Correct? |
|---|---|---|---|
| Evaluation-weight conflict | `NOT_PRESENT` | `NOT_PRESENT` (0 detected) | ✅ |
| Pricing-stage ambiguity | `PRESENT` | `PRESENT` (1 detected, correct evidence) | ✅ |
| Category-date distinction | `PRESENT` (scoped difference) | `PRESENT` (1 detected, correctly framed as scoped, not a conflict) | ✅ |

**Ambiguity assessment accuracy: 3/3 = 100%.**

## 5. Capability regression tests preserved

`tests/test_fast_analysis_v4.py::TestScopeAwareEvaluationWeightConflicts::test_same_scope_conflict_detected`
already proves the detector correctly flags a genuine same-scope conflict using a synthetic fixture
(`{"criterion_label": "Corporate Profile", "weight": "5 points", "category_scope": "Appendix D1"}` vs
the same label/scope with `"10 points"`) — independent of what this specific corpus happens to
contain. This is a `CAPABILITY TEST`; the live corpus's `NOT_PRESENT` result (Section 3 above) is a
separate `LIVE CORPUS EXPECTED RESULT`. No test was weakened or removed; the two were already
correctly separated when the detector was built in V4, and this reconciliation confirms that
separation holds.

## 6. Corrected client-facing report

`BANK_OF_CANADA_RFP_2026_026_BID_INTELLIGENCE_PREVIEW_SOURCE_CORRECTED.pdf` was built from the
already-persisted V4 facts, with **no new model calls**. Because V4's own live extraction was
already correct on every point this reconciliation checked (the 20-criterion evaluation table, the
absence of a false evaluation-weight ambiguity, the presence of the genuine pricing-stage and
category-date findings), the report's factual content is **unchanged from the already-delivered V4
PDF** — this reconciliation confirms that content is correct rather than needing to alter it. The
one change made: the validation footer note (Section 10) was rewritten in plain, client-appropriate
language to transparently disclose the Category 2 correction and the retirement of the false
ambiguity, without engineering terminology.

Visually confirmed (15 pages, unchanged page count): Section 5's Category 2 table shows all 7 rows
(75 points); Section 8 shows exactly 2 ambiguities, correctly numbered ("Ambiguity 1" = pricing-
stage, "Ambiguity 2" = category-date); Section 9's cross-references correctly reference "(Ambiguity
2)" for the presentation-stage confirmation item and carry no reference for the evaluation-weighting
item (since no ambiguity of that class exists); no dangling references anywhere.

## 7/8. Pricing-stage and category-date findings preserved

Both retained exactly as V4 produced them — full evidence, source references, why-it-matters text,
and (for pricing-stage) a clarification question. Category-date continues to be described as
scoped/category-specific scheduling, "not a true conflict, but worth confirming," per the existing
(and now reconfirmed-correct) phrasing.

## 9. Source-truth baseline created

`BANK_OF_CANADA_SOURCE_TRUTH_REPORT_BASELINE.json` — 45 required items across identity, dates,
response requirements, the full 20-criterion evaluation table, pricing/commercial facts, and the 3
ambiguity expected states, each with source document, source page, and classification. This becomes
the benchmark truth set for this corpus going forward, superseding the Deep-derived PDF wherever
the two disagree.

## 10. Fidelity recomputed against source truth

| | Deep-report-relative (prior) | Source-truth-relative (this reconciliation) |
|---|---|---|
| Required-items fidelity | 97.9% (46/47) | **100% (45/45)** |

Full item-by-item detail in `FAST_ANALYSIS_V4_SOURCE_TRUTH_FIDELITY.json`. V4's extraction output
was not changed to produce this number — it was already correct; this is a comparison against a
more accurate target, not a retuning of the extraction.

## 11. V4 acceptance, reassessed

| Gate | Against Deep-derived report | Against source truth |
|---|---|---|
| Critical facts | PASS | **PASS** |
| Evaluation tables | Flagged extra content (Category 2, +2 rows) | **PASS — confirmed correct, not extra** |
| Ambiguity classifications | FAIL (literal "all 3 must fire" rule) | **PASS (3/3 correctly classified under the redefined gate)** |
| Source traceability | PASS | PASS |
| Safety-net dependency | 0 critical facts | 0 critical facts |

**V4 correctly reflects the actual procurement source documents.** Under the redefined, source-
truth-grounded acceptance criteria, it is not failed for a prior report's error.

## 12. Validation note correction

The corrected PDF's Section 10 validation note now explicitly states (in client-appropriate
language, no engineering terminology): the Category 2 scoring correction (2 additional criteria,
10 additional points, sourced directly from the RFP's own table), and that a previously-flagged
scoring inconsistency was re-examined against the RFP text and found to reflect intentional,
category-specific weighting rather than a genuine conflict. Nothing is concealed.

## Historical Deep Verify report errors found

1. **Category 2 (HR Advisory) rated-criteria table**: published as 5 rows / 65 points; the source
   RFP's own table states 7 rows / 75 points (Value-add and Relevant Experience & References,
   5 points each, are present in the source and were omitted).
2. **Evaluation-weight ambiguity ("Ambiguity 1")**: false positive. No genuine same-scope conflict
   exists in the source material. The claimed evidence itself contains errors — a "100 points" value
   attributed to Key Personnel is actually Category 3's Total row, and a claimed "Methodology: 5
   points" occurrence does not exist anywhere in the corpus.

Both are documented transparently in `BANK_OF_CANADA_PREVIOUS_PREVIEW_CORRECTIONS.md`.
