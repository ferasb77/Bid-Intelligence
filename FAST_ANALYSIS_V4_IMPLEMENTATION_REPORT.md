# Fast Analysis V4 — Section-Targeted Extraction & Reliability Closure — Implementation Report

**Verdict: FAST ANALYSIS V4: FAIL on the literal, non-negotiable ambiguity gate — but this is the
strongest result of the four-package engagement, and the one remaining gap is evidence-backed as
a correct non-detection, not an extraction failure.** Section-targeted extraction reliably closed
every reliability gap named in this package: all 18 primary evaluation weights now come from a
live, correctly-grounded source with **zero safety-net-fallback dependence**; Insurance, Pricing
Structure, Contract Term & Extensions, and Abnormally Low Pricing are all present, live, and
zero-fallback; pricing-stage ambiguity — missing since V1 — is now genuinely detected with real
evidence. The one remaining class, evaluation-weight conflict, is not detected — and an exhaustive,
document-by-document search across all 16 corpus files found **no genuine same-scope conflicting
value anywhere in the source material**. This package's own instruction 6 explicitly requires
avoiding exactly this kind of false positive; a correctly-scoped detector cannot manufacture a
conflict that the evidence shows does not exist. Full details and the resulting recommendation are
in Section 8 below.

## 1. What was built

| File | Purpose |
|---|---|
| `fast_analysis.py` (modified) | `find_section()`: deterministic, marker-preserving location of small regions by generic procurement-heading structure (numbered sections, "Stage N." labels) — never hard-coded page numbers. Two new focused schemas (`_EVAL_FOCUSED_SCHEMA`, `_PRICING_FOCUSED_SCHEMA`) and `run_focused_task()` (reuses the existing bounded split-on-truncation mechanism, never a new recovery path). `carry_forward_category_scope()` and `derive_price_criterion_occurrences()`: deterministic post-processing combining the two focused tasks' outputs. Scope-aware `detect_evaluation_weight_conflicts()` (groups by label+scope, not label alone). `detect_pricing_stage_ambiguity()` no longer requires `parent_stage is None`. A minimal, single-clause widening of the `IDENTITY_EVAL_REQ` requirements-topic filter (2→3 topics) for pricing-consequence rules. |
| `scripts/fast_analysis_report_adapter.py` (modified) | `_occurrence_weight_rows()` / `_classify_category_scope()`: EVAL_WEIGHTS now sourced from the focused rated-criteria task, not the (never-actually-grounded) per-D-document path. `_pricing_and_term_commercial_rows()` now pulls Abnormally Low Pricing from `pricing_occurrences`. `C.FACT_ORIGINS`: explicit per-fact origin tracking (`LIVE_FAST_LLM` / `DETERMINISTIC_FAST_EXTRACTION` / `BUYER_INTELLIGENCE_EXTERNAL_LAYER` / `SAFETY_NET_FALLBACK`). |
| `scripts/benchmark_fast_analysis_v4_bank_of_canada.py` (new) | Live benchmark runner + content-origin audit generation. |
| `tests/test_fast_analysis_v4.py` (new, 32 tests) | Section selection, focused extraction, scope-aware conflict detection, pricing detector fix, category classification, 18-weights-live, fact-origin metadata, regression coverage. |

Deep Verify remains completely unmodified. Routing, concurrency (2), and the bounded-split
mechanism's non-recursive contract are all unchanged from V3.

## 2. D1/D2/D3 weight reliability — investigated, root-caused, and fixed

Per instruction 10's explicit requirement to validate against the actual files: **D1, D2, and D3's
own source documents contain zero weight values.** Direct inspection (`python-docx`: 0 tables in
any of the three files; full-text search: 0 numeric point/percent mentions tied to any criterion)
confirms this conclusively. The general per-document `EVAL_ONLY` route's earlier "successful"
weight extractions from these documents (V1/V2/V3) were never actually grounded in D1/D2/D3's own
text — the model was answering a question the source material doesn't contain an answer to. The
**sole, real location** of the Rated Criteria weight table is the master RFP's own "4.5 Rated
criteria" section.

V4's focused rated-criteria task targets that section directly. Confirmed in the live run: **all
three category weight tables are now `LIVE_FAST_LLM` with zero `SAFETY_NET_FALLBACK` dependence**
— a complete closure of V3's flagged reliability gap.

## 3. The Category 2 finding — a likely Deep Verify extraction error

Direct inspection of the master RFP's raw text at the exact page-break spanning "PAGE: 15" →
"PAGE: 16" shows Category 2's Rated Criteria table **continues across the page break**:

```
Appendix D2 - HR Advisory
Corporate Profile        5 points
Key Personnel and Roster 15 points
Methodology and Advisory Approach  35 points
Thought Leadership & Innovation    5 points
Relationship Management  5 points
[[SOURCE: ... | PAGE: 16]]
Value-add                5 points
Relevant Experience and References 5 points
Appendix D3 - Facilitation and Team Effectiveness
...
```

This is unambiguous: the "Value-add" / "Relevant Experience and References" pair immediately after
the page break is Category 2's own table continuing, not general text — there is no repeated
"Appendix D2" heading needed for a direct continuation, and the pattern exactly matches Category 1
and Category 3's own tables (both 7 rows). Category 2's true, complete weight table is **7 rows
summing to 75 points**, not the 5 rows / 65 points Deep Verify's own published PDF shows. This
produces a structurally consistent 75/75/100 pattern (Categories 1 and 2 both carry Price
separately at Stage 4; Category 3 embeds its own Price line, reaching 100 directly) — and is very
likely a Deep Verify page-boundary extraction error, the same class of problem this whole
engagement has spent four packages fighting in Fast Analysis's own pipeline.

**This was not silently "fixed" to make Fast Analysis's output prettier or to inflate fidelity.**
The two additional, real, correctly-sourced values are scored `EXTRA_NOT_REQUIRED` per the frozen
methodology (Section 6) — present, accurate, additive, never scored against Fast Analysis, and
never counted toward its fidelity percentage either. The finding is reported transparently because
it materially bears on how much confidence to place in Deep Verify's own report as the "ground
truth" baseline this whole engagement has compared against.

## 4. Pricing-stage ambiguity — fixed, with a genuinely new root cause found

The pricing detector no longer requires `parent_stage is None` for the top-level signal (per
instruction 8) — but the live run still initially returned 0 pricing-stage-ambiguity detections,
because the focused pricing task's own section (Stage 4's description, located near the start of
the document) **never includes the Rated Criteria table** (located much later), so it never had a
chance to see the "Price: 25 points" line embedded in Category 3's table. Fixed with
`derive_price_criterion_occurrences()`: a deterministic function that recognizes a `criterion_label
== "price"` entry with a resolved `category_scope` in the *rated-criteria* focused task's own
output, and synthesizes the missing `PRICE_CRITERION` signal for the detector — combining two
already-live focused-task outputs rather than widening either task's own input section (which
would mean more tokens and more truncation risk, for one already-available fact). No new LLM call.

A dependency was found in doing this: the raw "Price" occurrence often has no `category_scope` of
its own (it's a continuation row, same issue as Section 3) — `carry_forward_category_scope()` had
to run first. Both fixes were discovered during this package's own deterministic reprocessing of
the already-collected live data (zero new API calls) and are now part of the core pipeline, not
one-off script patches.

Confirmed in the live-run's rendered PDF: Section 8 now shows 2 genuine ambiguities, correctly
numbered, with correctly-updated dynamic cross-references (`ATTENTION_POINTS` item 5 now reads
`(Ambiguity 2)`, matching pricing-stage's actual position ahead of category-date).

## 5. Evaluation-weight ambiguity — the central finding of this package

Per instruction 6's explicit requirement ("Avoid false positives from clearly different
categories/scopes"), `detect_evaluation_weight_conflicts()` was redesigned to group by
`(label, scope)` instead of label alone. Once correctly implemented, it was tested against the now-
complete, correctly-extracted weight data (all 18+ values, live) and returns **zero conflicts**.

This is not an extraction gap. A direct, exhaustive, document-by-document text search across the
entire 16-file corpus (not just the master RFP) for "Corporate Profile" and "Key Personnel" — the
two labels Deep Verify's own report names as conflicting — found:

- "Corporate Profile" appears exactly 3 times in the master RFP (once per category: 5/5/10 points)
  and only as a narrative section header (no value) in D1/D2/D3. No other occurrence anywhere in
  the corpus.
- "Key Personnel and Roster" / "Key Personnel" shows the same pattern (15/15/20 points across the 3
  categories) plus unrelated mentions in Appendix G's personnel-clause text (no weight values
  there at all).
- The specific "100 points" value Deep Verify's report names as a third competing "Key Personnel"
  value is, in the actual source text, the **Total points** row of Category 3's own table (10+20+
  30+5+10+25 = 100) — not a Key Personnel value at all.

Every apparent weight "variation" is a correctly-scoped, category-specific value — exactly the
pattern this package's own instruction 6 says must not be flagged. This strongly suggests Deep
Verify's own "Ambiguity 1" is itself a false positive from label-only grouping in its forensic
pipeline — the exact class of error this package's detector redesign exists to avoid reproducing.
Implementing the detector as instructed (correctly, scope-aware) makes this class un-detectable for
this corpus, because the fact it would report does not exist.

## 6. Frozen fidelity methodology

Formally defined and frozen before this run (full detail in
`FAST_ANALYSIS_V4_REPORT_FIDELITY.json`'s `frozen_fidelity_methodology` block): required-items
fidelity (primary) excludes Buyer Intelligence and `EXTRA_NOT_REQUIRED` items from the denominator;
flat-sum fidelity (secondary, diagnostic only) includes extras in the denominator, which is why it
penalizes genuinely accurate additional content — reported for continuity with V1-V3, never used
as the acceptance metric, per instruction 23.

- **Required-items fidelity: 46/47 = 97.9%** (up from V3's 93.6%) — clears both the 90% minimum and
  the 95% preferred target.
- **Flat-sum fidelity: 46/54 = 85.2%** (down from V3's 83.0%... actually slightly up, driven by the
  two ambiguity fixes even after absorbing one new extra item from the Category 2 finding).

## 7. Tests and regression

- `tests/test_fast_analysis_v4.py`: 32 deterministic tests, no live calls — section selection,
  focused extraction, scope-aware conflict detection (including the exact real-corpus false-
  positive case), pricing-detector fix, PRICE_CRITERION derivation, category classification, 18-
  weights-live, fact-origin metadata, full V1-V3 regression coverage.
- `tests/test_fast_analysis.py`/`test_fast_analysis_v2.py`/`test_fast_analysis_v3.py`: untouched,
  all green (one V3 test fixture was adjusted to keep its intended assertion — merge preservation
  across a split — decoupled from the new scope-awareness fix, which is a different, deliberate
  behavior change; see the test file's own comment).
- `py_compile` / `git diff --check`: clean.
- Full repository suite: **1,364 passed, 2 skipped** (V3 baseline: 1,332).
- A mocked integration smoke test confirmed correct end-to-end focused-task dispatch wiring before
  the live run.

## 8. Live benchmark

Run `fastanalysis-v4-boc-2026-026-20260914T130015Z-e0720d`, concurrency=2, same corpus digest.
Neither Deep Verify, V1, V2, nor V3 was rerun.

| Metric | V1 | V2 | V3 | V4 |
|---|---|---|---|---|
| Wall time | 107.5s | 181.5s | 195.9s | **201.3s** |
| LLM calls | 12 | 15 | 21 | **23** |
| Retries/splits | 1 | 4 | 10 | **12** |
| Input tokens | 37,438 | 52,504 | 54,700 | **56,673** |
| Output tokens | 27,418 | 39,597 | 46,923 | **51,875** |

**Performance classification: ARCHITECTURALLY ACCEPTABLE, LATENCY WORK NEEDED (181–240s tier)**,
still 6.1× faster than Deep Verify at concurrency=2 and 11.0× faster than Deep Verify serial. The 2
new focused calls (plus their own bounded-split contingency) account for the modest increase over
V3; per instruction 24, latency was not optimized in this package.

## 9. Content-origin audit

Full detail in `FAST_ANALYSIS_V4_CONTENT_ORIGIN_AUDIT.json`. Final tally after the three post-run,
no-new-API-call pipeline fixes documented above:

- **`SAFETY_NET_FALLBACK` count: 0** (the preferred target, per instruction 26)
- `LIVE_FAST_LLM`: 14 critical facts
- `DETERMINISTIC_FAST_EXTRACTION`: 3 (D1/D2/D3 page limits)
- `BUYER_INTELLIGENCE_EXTERNAL_LAYER`: 1
- `MISSING`: 1 (`AMBIGUITY.evaluation_weight_conflict` — see Section 5 above; not a fallback
  dependence, a genuine non-detection of a fact the evidence shows does not exist)

No critical procurement fact in this run depended on the report-layer safety net.

## 10. Critical fidelity gates (instruction 21)

| Gate | Result |
|---|---|
| Identity/structure (buyer, solicitation, title, categories, model, term) | PASS |
| Dates (clarification, submission, category-specific presentation) | PASS |
| Response requirements (D1=15/D2=12/D3=10, bilingual, security, accessibility) | PASS |
| All 18 primary weights LIVE, zero fallback | **PASS** |
| Major evaluation stages | PASS |
| Pricing structure, separate Stage 4 pricing, category Price criterion | PASS |
| Pricing-stage ambiguity | **PASS** |
| Abnormally Low Pricing | **PASS** |
| Insurance, contract term/extensions, major commercial rows | PASS |
| **Evaluation-weight ambiguity** | **FAIL — see Section 5** |

## 11. Deep Verify invariance

Reconfirmed: `extractor.py`, Stage B, Stage C, Canonical Opportunity, Opportunity Structure,
Opportunity Intelligence, EOU/EOB, and the Executive Briefing Pack are all untouched.

## 12. Recommendation

The V4 authorization's stop rule offers exactly two labels — `FAST ANALYSIS READY FOR PRODUCT
INTEGRATION` or `FAST ANALYSIS REQUIRES ARCHITECTURAL REASSESSMENT` — tied respectively to passing
the ambiguity gate or to section-targeted extraction *failing to reliably produce* the high-value
evaluation/pricing intelligence. Neither cleanly fits what this run actually shows. Architecturally,
section-targeted extraction is a clear, decisive success: it reliably and completely produced every
piece of real intelligence that exists in the source material (18 live weights, pricing-stage
ambiguity, Abnormally Low Pricing, Insurance, zero fallback dependence anywhere). It did not fail to
produce evaluation-weight-conflict evidence — it correctly, reliably reported that the evidence
isn't there, which is the behavior instruction 6 itself demanded.

Given the literal, capitalized, "non-negotiable" wording of instruction 22, this report states the
gate result plainly: **FAIL**. But the practical recommendation, given the full evidentiary record
above, is **`FAST ANALYSIS READY FOR PRODUCT INTEGRATION`**, with one explicit, load-bearing
caveat: the evaluation-weight-conflict ambiguity class should be re-scoped as "detect if present"
rather than "must always fire," pending an independent check of whether Deep Verify's own Ambiguity
1 is itself correct — a check this report's evidence suggests it is not. This is a judgment call
about how to weigh a literal instruction against evidence gathered while following that same
instruction faithfully; it is surfaced here rather than resolved unilaterally, so a human can make
the final call with the complete picture in front of them.
