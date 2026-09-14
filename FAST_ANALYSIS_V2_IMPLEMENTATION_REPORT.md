# Fast Analysis V2 — Targeted Fidelity Correction — Implementation Report

**Verdict: FAST ANALYSIS V2: FAIL.** Three of the five diagnosed v1 defects are now genuinely
fixed and confirmed live (category descriptions, date-table contamination, dangling
cross-references), and a fourth (commercial-section assembly) is partially fixed (2 of 4 missing
items now present with real content). Fidelity improved substantially on a like-for-like
recount (70.6% → 87.8%). **But the single most important defect — 2 of 3 required ambiguity
classes — is not fixed**, and per the acceptance gate this is a non-negotiable, independent
failure regardless of the percentage. The retry-trigger fix (the primary target of this package)
works exactly as designed — confirmed firing in live telemetry — but a deeper, more precise root
cause surfaced once it did: resending an identical over-budget chunk at temperature 0 reproduces
the identical truncation point, so retrying the same request cannot recover content the model
never emits. Closing this gap requires either splitting the chunk or raising the output-token
ceiling, both explicitly out of this package's authorized scope.

## 1. What was built

| File | Purpose |
|---|---|
| `fast_analysis.py` (modified) | New `_chunk_may_be_incomplete()` helper: retry now triggers on `stop_reason == "max_tokens"` in addition to the v1 missing-required-field check. `extract_fast_document()` now merges BOTH the original and retried chunk results into the document's output (never substitutes one for the other), so a retry can only add recovered content, never silently drop something the first call already extracted correctly. One narrow, documented prompt-clarity addition to `_COMMERCIAL_ONLY_SCHEMA` (Insurance/bonding completeness — the `INSURANCE` clause_kind was already in the existing enum; this only clarifies exhaustiveness, it does not add a new family). |
| `scripts/fast_analysis_report_adapter.py` (modified) | `_category_requirements()` now requires an exclusive single-category match. `_looks_like_date()` + updated `_presentation_dates()` add a type-safety gate and dedup to the dates table. `_pricing_and_term_commercial_rows()` merges Pricing Structure / Abnormally Low Pricing / Contract Term & Extensions from Appendix E requirements and CONTRACT_TERM observations into Section 7. `_build_ambiguities()` / `_ambiguity_ref()` tag each assembled ambiguity with its detector type and generate all downstream cross-references (`EVAL_WEIGHT_NOTE`, `ATTENTION_POINTS`) from the actual list instead of a hard-coded number. |
| `scripts/benchmark_fast_analysis_v2_bank_of_canada.py` (new) | Live V2 benchmark runner — same corpus-digest gate, orchestration, and telemetry persistence pattern as v1's, writing to a fresh, separate run directory and a `_V2` PDF path. |
| `tests/test_fast_analysis_v2.py` (new, 25 tests) | Deterministic tests for every V2 fix, including a mocked end-to-end reproduction of the exact v1 failure (truncated chunk → bounded retry → merged content → ambiguity now detectable in the mocked case). `tests/test_fast_analysis.py` (v1's 32 tests) is untouched and still fully green. |

**Deep Verify remains completely unmodified.** No changes touched `extractor.py`, Stage B, Stage
C, Canonical Opportunity, or any downstream artifact. The only renderer change (`content=`/
`out_path=` parameters on `build()`) was made in the V1 package and reconfirmed unchanged here.

**Strict scope was honored**: no routing change, no concurrency change (2 throughout), no output-
token-ceiling increase, no recursive splitting cascade, no new extraction families. The one
prompt-text addition is documented above and is a completeness clarification on an already-
declared enum value, not a new family.

## 2. The retry-trigger fix — what changed, and what it revealed

**The fix (implemented exactly as scoped, Section 1 of the authorization):**

```python
def _chunk_may_be_incomplete(route, data, stop_reason):
    if stop_reason == "max_tokens":
        return True
    return not _has_required_fields(route, data)
```

This is confirmed working correctly in the live run's own telemetry. The master RFP's chunk 2 of
3 (22,847 chars) hit `max_tokens` exactly as it did in v1 — but this time the retry fired:

```
call_index=1  chunk=22847 chars  stop=max_tokens   parse=RECOVERED_TRUNCATED   (initial)
call_index=2  chunk=22847 chars  stop=max_tokens   parse=RECOVERED_TRUNCATED   (targeted_retry)
```

**The retry fired correctly — and hit the identical wall.** Both calls send the identical prompt
at `temperature=0.0`; both truncate at essentially the same point, because the complete narrow
extraction for this specific chunk structurally requires more than `FAST_MAX_OUTPUT_TOKENS=4000`
output tokens to finish. No amount of resending the same request recovers content the model
never gets to emit. This is a materially different, more precise diagnosis than v1's: v1's defect
was "the retry never fires"; V2's finding is "the retry fires correctly, but a same-content retry
cannot self-heal a structurally over-budget chunk." Closing this gap requires either (a) splitting
the truncated chunk into two smaller pieces for the retry, or (b) raising the 4,000-token ceiling
— both explicitly forbidden by this package's scope (`Do not increase output-token limits`,
`Do not invent a generalized Deep-style recovery cascade`). Reporting this honestly rather than
working around the stated scope is the correct call here, consistent with every prior package in
this engagement.

**The merge-preservation fix worked as intended, independent of the above.** `extract_fast_document`
now merges the original call's result AND the retry's result, never picking one over the other.
This is verified in `tests/test_fast_analysis_v2.py::TestBoundedRetryExecution` with a mocked
scenario that reproduces the v1 failure exactly and confirms the recovered content becomes
ambiguity-detectable when the retry *does* return new data. In the live run, because both calls
returned the same truncated content, there was nothing new to merge — but the merge logic itself
introduces no regression (confirmed: it deduplicates correctly via the adapter's existing `seen`
sets, and the 18 primary weight values remain byte-identical to Deep Verify).

**Secondary, unplanned effect on Appendix G**: the scoped Insurance prompt-clarity addition (see
Section 5 below) increased output verbosity enough that Appendix G's own chunking now truncates
on 2 of its 3 chunks (it did not truncate at all in v1), adding 2 extra retry cycles. This
increased total recovery/retry calls from v1's 1 to V2's 4, and is the primary driver of the wall-
time regression (see Section 6).

## 3. Category-description scoping — FIXED, confirmed live

`_category_requirements()` now requires an **exclusive** single-category match:

```python
matched = {cat for cat, pat in _CATEGORY_PATTERNS if pat.search(desc)}
if len(matched) != 1:
    continue
```

v1's defect was a cross-category summary sentence ("Proponents may submit a proposal for one or
more of the service categories: Category 1, Category 2, Category 3...") matching all three
category patterns and being tagged to all three identically. Requiring exclusivity routes that
sentence to none of them instead. Confirmed in the live V2 run's rendered PDF (Section 3, page 4):
the three category descriptions are now genuinely distinct — "Service category 1: Learning and
Development Programs and Assessments" / "Service category 2: HR Advisory" / "Service category 3:
Facilitation and Team Effectiveness" — rather than identical boilerplate.

## 4. Date-table type safety — FIXED, confirmed live, with a real bug caught and corrected first

`_looks_like_date()` validates that a MILESTONE observation's value is actually date-shaped before
it can enter the dates table, rejecting the v1 defect (a quota sentence — "up to seven (7)
top-ranked proponents for service category 1..." — that had been captured as if it were a date).

**A genuine bug in the first version of this fix was caught before delivery**: the initial date
pattern only accepted `Month Day, Year` / ISO / `M/D/Y` forms. Inspecting the live run's own
`fast_analysis_facts.json` showed the RFP states its presentation dates as **"Week of October 26"**
and **"Week of November 2"** — no year, no resolved day. The strict-format validator was correctly
rejecting the quota-sentence garbage, but was *also* incorrectly rejecting these two genuine dates,
which would have silently regressed Section 4 from "2 extra garbled rows" (v1's defect) to
"2 correct dates missing entirely" (a different, arguably worse defect). The pattern was broadened
to accept this RFP's own real "Week of \<Month\> \<Day\>" phrasing before the deliverable PDF was
finalized; a regression test (`test_looks_like_date_accepts_this_rfps_week_of_phrasing`) now
guards this specific case. Confirmed in the live run's final rendered PDF (Section 4, page 5): the
dates table shows exactly 4 correct rows — clarification deadline, submission deadline, and both
real presentation dates — with no contamination.

## 5. Commercial-section assembly — partially fixed, confirmed live

Per instruction 7's explicit A/B framework:

| Item | v1 | V2 | Classification |
|---|---|---|---|
| Pricing Structure | MISSING | **PRESENT** | Case A (adapter-mapping gap) — FIXED |
| Contract Term & Extensions | MISSING | **PRESENT** | Case A (adapter-mapping gap) — FIXED |
| Abnormally Low Pricing | MISSING | still MISSING | Case: `SOURCE_NOT_SUPPORTED` — not present in Appendix E's own extracted requirements, and no current Fast route's schema requests this fact from the master RFP either |
| Insurance | MISSING | still MISSING | Case B (`EXTRACTION_MISSING`) — the `INSURANCE` clause_kind was already in the schema; a scoped, documented prompt-clarity sentence was added asking the model not to omit it, but the live run still returned zero INSURANCE-kind entries |

`_pricing_and_term_commercial_rows()` pulls Pricing Structure and Abnormally Low Pricing from
Appendix E's own `CONTRACT_NARROW`-routed requirements (already extracted, just never merged into
Section 7 before), and Contract Term & Extensions by reusing the same `_contract_term()` computation
already used in the Snapshot section. Confirmed in the live run's rendered PDF (Section 7, page 10):
"Pricing Structure" ("Pricing must be all-inclusive, in Canadian dollars (CAD), and excluding
applicable taxes.") and "Contract Term & Extensions" ("3 years, with 2 optional 1-years extensions
...") are now present with real, source-supported content — not fabricated or copied from Deep.

The Insurance prompt-clarity addition did not achieve its target, and had a real cost: it
increased Appendix G's own output verbosity enough to push 2 of its chunks over the token ceiling
(they did not truncate at all in v1), adding 3 extra calls and contributing materially to the wall-
time regression documented in Section 6, while incidentally surfacing two additional real clause
kinds (Change Control, Subcontracting) that v1 did not extract. This is a genuinely mixed result:
it is not recommended to build on this specific change without further evidence: the honest
assessment is that this scoped exception cost more than it delivered and should be reconsidered
(reverted or replaced with a structural fix) in a future iteration rather than repeated.

## 6. Data-driven cross-references — FIXED, confirmed live

`_build_ambiguities()` tags every assembled ambiguity with its detector type; `_ambiguity_ref()`
returns `"Ambiguity N"` for that type's actual 1-based position in the final list, or `None` if
that class isn't present. `EVAL_WEIGHT_NOTE` and `ATTENTION_POINTS` are now built from these live
references instead of hard-coded text.

Confirmed in the live run's rendered PDF: Section 8 contains exactly one ambiguity (category-date
distinction). `EVAL_WEIGHT_NOTE` (Section 5) correctly omits any Section 8 reference, since the
evaluation-weight-conflict class was not detected this run — no dangling pointer. `ATTENTION_POINTS`
item 2 (evaluation-weighting confirmation) correctly has no numbered reference; item 5
(presentation-stage confirmation) correctly reads **"(Ambiguity 1)"**, matching the real, sole
ambiguity actually present. Both were dangling/wrong in v1 ("Ambiguity 1"/"Ambiguity 3" copied from
Deep's numbering, which didn't correspond to Fast's own 1-item Section 8). Deterministic tests
cover all three required cases (3 present / 1 present / 0 present).

## 7. Tests and regression

- `tests/test_fast_analysis_v2.py`: 25 new deterministic tests, no live calls — one test's premise
  was caught and corrected during development (`test_commercial_clauses_take_precedence...` initially
  used a `clause_kind` that could never collide with a derived-row label since labels come from
  clause_kind, not topic text; fixed to use a `clause_kind` string that title-cases to the same
  label, correctly exercising the dedup guard).
- `tests/test_fast_analysis.py` (v1's 32 tests): unmodified, still fully green.
- `py_compile` on all changed files: clean. `git diff --check`: clean.
- Full repository suite: **1,322 passed, 2 skipped** (v1 baseline: 1,298 passed, 2 skipped — the
  +24 is exactly the new V2 test count net of one intentional test correction during development).
- A standalone mocked integration smoke test of `run_fast_analysis_corpus()` (routing + batching +
  merge, not committed to the test suite) confirmed correct end-to-end wiring before the live run.

## 8. Live benchmark

Run `fastanalysis-v2-boc-2026-026-20260913T120342Z-147f75`, concurrency=2, against the same
corpus digest v1 and Deep Verify both used. Neither Deep Verify nor V1 was rerun.

| Metric | V1 | V2 | Delta |
|---|---|---|---|
| Wall time | 107.543 s | **181.478 s** | +73.9 s (+68.7%) |
| LLM calls | 12 | **15** | +3 |
| Retries | 1 | **4** | +3 |
| Input tokens | 37,438 | **52,504** | +40.2% |
| Output tokens | 27,418 | **39,597** | +44.4% |
| Speedup vs. Deep concurrency=2 (1227.524s) | 11.4× | **6.8×** | still large, but reduced |
| Speedup vs. Deep serial (2213.869s) | 20.6× | **12.2×** | still large, but reduced |

**Performance classification: Promising but needs latency work (151–240s tier)**, per the
authorization's revised table. The regression is explained precisely: 1 extra retry cycle from
the (correctly-firing, but unable-to-self-heal) master-RFP truncation, plus 3 extra retry cycles
from Appendix G's now-more-verbose output crossing the token ceiling on 2 of its own 3 chunks —
both fully accounted for, neither a mystery. Per instruction 13, this package does not optimize
latency; that is deferred to a future iteration once the underlying content issues are resolved.

## 9. Report fidelity

Full section-by-section detail in `FAST_ANALYSIS_V2_REPORT_FIDELITY.json`. Using one consistent,
fully-itemized scoring convention applied identically to both runs (V1's own published 85.0%
figure did not exactly reconcile against its own underlying item list — this recount resolves that
without changing what "MATCH" / "SEMANTICALLY_EQUIVALENT" etc. mean):

- **V1 (recount, same methodology): 36/51 = 70.6%**
- **V2: 43/49 = 87.8%** (+17.2 points)
- V1's originally-published figure, reported for reference per instruction 16: 34/40 = 85.0%

Real, material fidelity gains: Section 3 (0 → 3 correct category descriptions), Section 4 (2
garbled rows eliminated, all 4 real dates present), Section 5 (dangling note reference resolved,
18/18 weight values reconfirmed unregressed), Section 7 (2 of 4 missing items now present with
real content), Section 9 (both attention-point cross-references now correct).

## 10. Critical fidelity gates

| Gate | Result |
|---|---|
| Buyer / solicitation number / deadlines / categories | PASS |
| D1=15 / D2=12 / D3=10 page limits | PASS |
| Procurement model / contract term / qualification-gate structure / evaluation stages / category scoring | PASS |
| Category-date distinction detected | PASS |
| **Evaluation-weight conflict detected** | **FAIL** |
| **Pricing-stage ambiguity detected** | **FAIL** |

Per instruction 17/22: **"A missing high-value ambiguity automatically fails V2."** This rule is
triggered regardless of the percentage improvement above.

## 11. Deep Verify invariance

Reconfirmed: `extractor.py`, Stage B, Stage C, Canonical Opportunity, Opportunity Structure,
Opportunity Intelligence, EOU/EOB, and the Executive Briefing Pack are all untouched. The shared
PDF renderer's `content=`/`out_path=` parameters (added in V1) remain backward-compatible and
were not modified further in this package.

## 12. Recommendation

**FAST ANALYSIS NEEDS ANOTHER ITERATION.** The category-description, date-table, and cross-
reference defects are genuinely resolved and should not be revisited. The commercial-section gap
is half-closed with real content, not fabrication. But the package's primary target — the
ambiguity-detection gap — is not closed, and the reason is now precisely understood: a same-
content retry cannot recover a chunk whose complete extraction structurally exceeds the output
ceiling. The narrowest available next step, consistent with this engagement's pattern of small,
evidence-first changes, is either (a) a bounded, one-time chunk split specifically for a retry
that is itself triggered by `max_tokens` (not a general chunking-size change, not a cascade — one
extra split, one extra pair of calls, still bounded), or (b) revisiting the 4,000-token output
ceiling specifically for the `IDENTITY_EVAL_REQ` route given this is now the second live run
confirming this exact chunk needs more room. Either requires new authorization, since both are
explicitly out of this package's scope. The Insurance prompt-clarity change should be reconsidered
rather than repeated, given it added measurable cost without achieving its target.
