# Bid Intelligence — Phase 6 Generalization Release Notes

**Release date:** 2026-09-15 (UTC)
**Tag:** `bid-intelligence-generalized-v2`
**Supersedes:** `bid-intelligence-generic-v1`

## Summary

Phase 6 ran a genuine third-procurement holdout — City of Calgary (Design and Delivery Services for Leadership Learning and Development), a corpus never previously analyzed or inspected — against the frozen two-procurement generic-assembly baseline. The holdout **failed on first contact** (`run_id = 6`), which is the intended, correct outcome of a real holdout test: it surfaced a genuine generalization defect that the first two corpora (Bank of Canada, CDA-AMC) had not exposed. The defect was diagnosed, corrected at the extraction-schema layer, and live-revalidated across two further authorized Calgary runs, culminating in a fully accepted final run (`run_id = 8`).

## What was found

Calgary's commercial pricing section contains a weighted formula that blends resource rates into a single price figure (55% / 35% / 10%). The frozen Fast Analysis evaluation-extraction schema had no semantic distinction between a weight that **scores a bidder** (a genuine evaluation criterion, e.g. "Technical 80%, Price 20%") and a weight that only **calculates a bidder's own price** (a pricing-calculation mechanism). The pricing formula was misclassified as an evaluation criterion. A related defect was also found: the scoped-date ambiguity wording assumed every multi-date finding was category-scoped, which produced misleading phrasing for Calgary's non-category-scoped date data.

## What changed

- `_EVAL_SCHEMA` and `_EVAL_FOCUSED_SCHEMA` (`fast_analysis.py`) now carry an explicit, procurement-agnostic semantic-role distinction between bidder-scoring weights and price-calculating weights, so a pricing-calculation weight is never extracted as an evaluation criterion.
- `_IDENTITY_EVAL_REQ_SCHEMA` gained a fourth `requirements` topic so a weight excluded from evaluation is still captured, verbatim, as a commercial/requirements fact rather than silently lost. This sub-refinement was self-identified during live validation (`run_id = 7` showed the weight correctly excluded from evaluation, but the values were absent from the record entirely) and was live-revalidated in `run_id = 8`.
- Pricing formula is now retained commercially: captured verbatim, with document-level source attribution, in Calgary's requirements/commercial content.
- The `CATEGORY_DATE_DISTINCTION` ambiguity wording (`scripts/fast_analysis_report_adapter.py`) is now conditional on whether the underlying occurrences carry real category/lot/component scope data, instead of always assuming category-scoped dates. Bank of Canada's genuine category-scoped wording is unchanged (verified by regression).
- Nine new regression tests (`tests/test_fast_analysis_pricing_evaluation_separation.py`) lock in both directions of the fix across four extraction-shape cases plus a mixed cross-domain case, and assert the schema text stays procurement-agnostic (no Calgary-specific names, numbers, or filenames).

## Validated live

- `run_id = 6`: original holdout failure (pricing formula misclassified as evaluation).
- `run_id = 7`: confirmed the core misclassification fixed; surfaced the value-loss sub-defect.
- `run_id = 8`: final accepted run — pricing formula excluded from evaluation, retained commercially with the exact 55%/35%/10% values present exactly once each, no fabricated evaluation table, scoped-date wording corrected, zero cross-corpus leakage, report regeneration without extraction confirmed.

## No regressions

Bank of Canada (20 = 7 + 7 + 6 evaluation criteria, ambiguity states unchanged) and CDA-AMC (11 = 10 Technical + 1 Financial, 0 fabricated categories, 0 leakage) were re-verified deterministically at every checkpoint in this phase. Neither corpus was re-run live in Phase 6; no engine or adapter change altered their existing regression-test expectations.

## Full detail

For the complete holdout methodology, root-cause trace, and all three run telemetry records, see `BID_INTELLIGENCE_PHASE6_THIRD_PROCUREMENT_HOLDOUT_REPORT.md`.
