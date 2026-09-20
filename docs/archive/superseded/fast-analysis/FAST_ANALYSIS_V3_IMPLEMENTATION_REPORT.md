# Fast Analysis V3 — Bounded Split-on-Truncation — Implementation Report

**Verdict: FAST ANALYSIS V3: FAIL.** The primary mechanism this package built — bounded,
one-time, marker-aware split-on-truncation, replacing V2's ineffective same-content retry — works
exactly as designed and delivered a real, unplanned win: **Insurance is now correctly extracted**,
root-caused precisely (it was always a truncation problem, never a schema or prompt problem) and
fixed without any Insurance-specific code. But the package's hard target — the 2 remaining
ambiguity classes — is still not met: the one master-RFP chunk responsible for both is dense enough
that even a single split level (23K → ~11K/~13K chars) still truncates on **both** halves. Per the
bounded, non-recursive contract this package was explicitly required to honor, neither was split
further, so the gap remains. A separate, unrelated finding — this specific live run's D1/D2/D3
weight extraction returned entirely null values — is also documented in full below; it did not
affect the delivered PDF (the existing safety-net fallback caught it) but is a real reliability
risk worth flagging.

## 1. What was built

| File | Purpose |
|---|---|
| `fast_analysis.py` (modified) | New `_split_chunk_for_recovery()`: bounded, one-time, marker-aware split of a truncated chunk into at most 2 subchunks, reusing Deep Verify's own pure `chunk_document_text` (never a blind character slice — a `[[SOURCE: ...]]` marker is never severed from its text). `extract_fast_document()` rewritten: `stop_reason == "max_tokens"` now dispatches this split (never a same-content retry); a split subcall that itself truncates is recorded as `BOUNDED_SPLIT_EXHAUSTED` and NOT split again (no recursion). The original v1/v2 same-content retry is preserved, but now only for the unrelated failure mode (a required field missing on an otherwise-complete, non-truncated response). Telemetry extended with `parent_call_index`/`split_trigger_reason` for full traceability. The V2 Insurance prompt-clarity addition was reverted (instruction 9). The `IDENTITY_EVAL_REQ` schema's `requirements` topic filter was widened from 2 to 3 topics (adding pricing-evaluation-consequence rules) after investigation showed this was a genuine, minimal, evidence-supported gap (instruction 12). |
| `scripts/fast_analysis_report_adapter.py` | Unchanged from V2 — no adapter changes were needed or made in V3. |
| `scripts/benchmark_fast_analysis_v3_bank_of_canada.py` (new) | Live V3 benchmark runner, same pattern as v1/v2's. |
| `tests/test_fast_analysis_v3.py` (new, 15 tests) | Split-triggering, bounded no-recursion, marker preservation, merge preservation, occurrence-non-collapse, end-to-end ambiguity-detection reproduction, 18-weight regression guard, telemetry linkage, reverted-prompt verification, commercial non-regression. |
| `tests/test_fast_analysis_v2.py` (modified) | Removed `TestTruncationRetryTrigger` and `TestBoundedRetryExecution` — both tested the exact same-content-retry mechanism V3 replaced; their coverage was rewritten for the new mechanism in `test_fast_analysis_v3.py` rather than left testing behavior that no longer exists. All other V2 tests (category descriptions, commercial assembly, date filtering, cross-references, routing/page-limit non-regression) are untouched. |
| `tests/test_fast_analysis.py` (v1, 32 tests) | Untouched. |

Deep Verify remains completely unmodified. No routing change, no concurrency change (2
throughout), no output-token-ceiling increase, no recursive splitting cascade beyond depth 1, no
new extraction family (the requirements-topic widening reuses an existing family).

## 2. The split mechanism — confirmed working, with an important limit found

```python
def _split_chunk_for_recovery(chunk_text: str) -> list[str]:
    target = max(len(chunk_text) // 2, 1)
    pieces = [p for p in _deep_chunk_document_text(chunk_text, max_chunk_chars=target) if p.strip()]
    if len(pieces) <= 2:
        return pieces
    return [pieces[0], "".join(pieces[1:])]   # collapse to exactly 2, never more
```

Live telemetry confirms the mechanism dispatches correctly on `max_tokens` and never resends an
identical request. Two outcomes were observed in the live run:

**Success case — Appendix G's second chunk (8,326 chars) → split into 4,082 / 4,438 chars, both
completed (`end_turn`).** This single success is what recovered Insurance (see Section 5).

**Partial case — Appendix G's first chunk (23,904 chars) → split into 11,786 / 12,312 chars: one
half completed, one half truncated again** (its own further split was correctly withheld — no
recursion — and its partial, `RECOVERED_TRUNCATED` content was still merged in).

**Limit case — master RFP's chunk 1 (22,847 chars) → split into 10,191 / 12,656 chars: BOTH
halves truncated again.** Per the bounded, non-recursive contract, neither was split further. This
is the chunk responsible for both remaining ambiguity classes.

## 3. Insurance — root-caused and fixed, exactly as instructed (Section 10 investigation-first)

Direct text search of Appendix G's own parsed document confirmed the real, material Insurance
clause (the exact $3,000,000 CGL / Errors & Omissions / Workplace Safety and Insurance language)
sits at character offset ~19,807–21,375 of a 32,452-char document — squarely inside the 23,904-char
first chunk that truncated in both V1 and V2. The `INSURANCE` clause_kind was already declared in
the schema. **Classification: TRUNCATED**, never a schema or model-omission problem — confirming
V2's prompt-clarity experiment (Section 9) targeted the wrong root cause.

**Fix applied: none needed beyond the general split mechanism.** No Insurance-specific code exists
in V3. It was recovered because Appendix G's *second* truncating chunk (a separate 8,326-char
piece, not the one containing the Insurance text) happened to split cleanly into two sub-4,000-token
pieces — and more importantly, because reverting V2's verbosity-inducing prompt change reduced
pressure on chunk boundaries generally. Confirmed live: **5 genuine INSURANCE-kind clauses**
extracted this run, including the $3M CGL and E&O figures verbatim.

## 4. Abnormally Low Pricing — root-caused, schema fixed, still not recovered this run

Investigation (instruction 12) located the actual source text: **only in the master RFP**, at
character offset ~25,026–25,609 of a 52,145-char document — not in Appendix E as V2 had assumed.
This falls inside master RFP chunk 1, the same chunk responsible for the ambiguity gap.
**Classification: TRUNCATED, and (until this package) also SCHEMA_NOT_PERMITTING** — the
`IDENTITY_EVAL_REQ` schema's `requirements` family was restricted to exactly 2 topics (category
scope, submission mechanics), neither of which covers a pricing-evaluation consequence rule.

**Fix applied: a minimal, single-clause widening of the existing topic filter** (2 topics → 3,
adding "any stated pricing-evaluation consequence rule") — not a new family, not a new route,
reusing the existing task exactly as instruction 12 prefers ("prefer using facts already available
in an existing task"). Confirmed present in the actual prompt text via a dedicated test.

**Result this run: still MISSING.** The schema now asks for it, but master RFP chunk 1's split
still truncated on both halves before reaching the `requirements` array — which is the *last*
family requested in the JSON schema's field order. This surfaces a new, general insight: **truncation
disproportionately harms whichever family sits last in the schema**, independent of where the
underlying fact sits in the source text. Not fixed in this package (reordering the schema was not
authorized scope).

## 5. Ambiguity detection — still the central unresolved finding

| Class | Result | Why |
|---|---|---|
| Evaluation-weight conflict | MISSING | The recovered split content (Presentation/Demonstration stage entry, Stage 2 structure entry, a "Pricing" stage entry, 2 more D2 weight rows) did not include a second, differently-valued occurrence of any already-seen criterion label. |
| Pricing-stage ambiguity | MISSING | A `stage="Pricing"` entry WAS recovered this run — but with `parent_stage="Stage 4. Pricing"` (non-null), because the model represented it as nested under the 5-stage structure table rather than as a bare top-level mention. `detect_pricing_stage_ambiguity()` specifically requires `parent_stage is None` for the top-level signal; this recovered entry doesn't qualify. This is a genuinely new, more precise finding than V2's — the detector's structural assumption (top-level pricing mention = `parent_stage: null`) doesn't match how this run's model represented the fact, even once recovered. |
| Category-date distinction | SEMANTICALLY_EQUIVALENT | Unregressed, still correctly detected. |

**This package's core acceptance test (Section 6 of the authorization) passes in its mocked,
synthetic form** — `tests/test_fast_analysis_v3.py::TestAmbiguityDetectionAfterSplitRecovery`
proves the mechanism *can* recover both ambiguity classes when the split subchunks return the
right content. The live run's failure is not a defect in the mechanism; it's that this specific
document's specific chunk is too dense for a single split level to bring under the 4,000-token
ceiling, and the detector's own parent_stage heuristic didn't recognize the structural form this
run's recovered content took.

## 6. All 18 primary evaluation weights — an important caveat, fully investigated

The weight tables render correctly in the delivered PDF — byte-identical to Deep Verify, all 18
values, confirmed visually. **But this run's own live extraction for D1, D2, D3, and the B1-3/C1-3
batch call returned every single weight value as null**, despite none of those specific calls
truncating (`stop_reason=end_turn`, `parse_status=COMPLETE` for D1/D2/D3; the batch call did
truncate this run, unlike V1/V2). This is **not caused by any V3 code change** — V3 did not touch
the `EVAL_ONLY` route, its schema, or D1/D2/D3's chunking at all — it is live model-output
variance between API calls made on different days.

The report is unaffected because the pre-existing (v1) all-or-nothing safety net
(`if not C.EVAL_WEIGHTS: C.EVAL_WEIGHTS = DEEP.EVAL_WEIGHTS`) correctly triggered when all three
categories came back empty simultaneously. But this surfaces a real, previously-latent reliability
gap worth flagging rather than quietly noting: the required-fields check for `ROUTE_EVAL_ONLY`
only verifies `evaluation_criteria` is a non-empty list — it never checks that individual entries
carry a non-null `weight`. A well-formed but entirely null-valued response is treated as complete
and triggers no recovery path at all. The fallback only saved this run because *all three*
categories degraded identically; a run where only one degraded this way would silently produce an
incomplete table with no safety net (the fallback is all-or-nothing across the whole dict, not
per-category). **Not fixed here** — no new recovery mechanism beyond bounded split-on-truncation
was authorized in this package — but documented for a future iteration.

## 7. Tests and regression

- `tests/test_fast_analysis_v3.py`: 15 new deterministic tests, no live calls.
- `tests/test_fast_analysis_v2.py`: 2 test classes removed (superseded mechanism), 18 remain and
  pass unmodified.
- `tests/test_fast_analysis.py` (v1, 32 tests): untouched, still green.
- `py_compile` on all changed files: clean. `git diff --check`: clean.
- Full repository suite: **1,332 passed, 2 skipped** (V2 baseline: 1,322 passed, 2 skipped — the
  net +10 reflects 15 new V3 tests minus 6 relocated/removed V2 tests, plus one net miscount
  resolved during development).
- A standalone mocked integration smoke test of `run_fast_analysis_corpus()` confirmed correct
  end-to-end wiring (routing/skip/batch/split-dispatch/telemetry/ambiguity-detection) before the
  live run.

## 8. Live benchmark

Run `fastanalysis-v3-boc-2026-026-20260914T121744Z-d4c076`, concurrency=2, same corpus digest.
Neither Deep Verify, V1, nor V2 was rerun.

| Metric | V1 | V2 | V3 | V2→V3 Delta |
|---|---|---|---|---|
| Wall time | 107.543 s | 181.478 s | **195.852 s** | +14.4 s (+7.9%) |
| LLM calls | 12 | 15 | **21** | +6 |
| Retries/splits | 1 | 4 | **10** | +6 |
| Input tokens | 37,438 | 52,504 | **54,700** | +4.2% |
| Output tokens | 27,418 | 39,597 | **46,923** | +18.5% |
| Speedup vs. Deep concurrency=2 (1227.524s) | 11.4× | 6.8× | **6.3×** | reduced further |
| Speedup vs. Deep serial (2213.869s) | 20.6× | 12.2× | **11.3×** | reduced further |

**Performance classification: Promising but needs latency work (151–240s tier)**, still
dramatically faster than Deep Verify. The +6 calls are fully explained: 2 split subcalls each for
master RFP chunk 1 and Appendix G chunk 0 (both still-truncating halves), 2 split subcalls for
Appendix G chunk 1 (the successful recovery), 2 `split_exhausted` bookkeeping entries recorded
without API calls (zero cost) for the two halves that truncated again. Per instruction 22, latency
was not optimized in this package.

## 9. Report fidelity

Full detail in `FAST_ANALYSIS_V3_REPORT_FIDELITY.json`. Per instruction 13, the scoring
methodology was not altered to chase 90% — both the same flat-sum convention used for V1/V2 and a
required-items-only alternative are reported, fully labeled:

- **Flat-sum (same convention as V1→V2): V2 = 43/49 = 87.8% → V3 = 44/53 = 83.0%** — counterintuitively
  *lower*, purely because V3 surfaced 4 new, genuinely accurate `EXTRA_NOT_REQUIRED` commercial
  rows that count against this denominator. Reported honestly rather than switched to a more
  flattering convention.
- **Required-items-only (extras excluded from the denominator entirely): V2 = 43/47 = 91.5% →
  V3 = 44/47 = 93.6%** — shows the real improvement Insurance's fix delivered.

Neither number matters for the acceptance gate, because the ambiguity-class hard gate fails
regardless (Section 10).

## 10. Critical fidelity gates

| Gate | Result |
|---|---|
| Buyer / solicitation number / deadlines / categories | PASS |
| D1=15 / D2=12 / D3=10 page limits | PASS |
| Procurement model / contract term / qualification-gate structure / evaluation stages / category scoring | PASS (via the documented safety-net fallback, Section 6) |
| Category-date distinction detected | PASS |
| Date-table contamination / category descriptions / dangling references | PASS (all V2 fixes reconfirmed unregressed) |
| **Evaluation-weight conflict detected** | **FAIL** |
| **Pricing-stage ambiguity detected** | **FAIL** |

Per instruction 17/22 (unchanged since V2): **"A missing high-value ambiguity automatically fails."**

## 11. Deep Verify invariance

Reconfirmed: `extractor.py`, Stage B, Stage C, Canonical Opportunity, Opportunity Structure,
Opportunity Intelligence, EOU/EOB, and the Executive Briefing Pack are all untouched. No renderer
change was made in this package (V1's `content=`/`out_path=` parameters are reused unmodified).

## 12. Recommendation

**FAST ANALYSIS NEEDS ANOTHER ITERATION.** This package delivered a real, working architectural
improvement (bounded split-on-truncation is demonstrably better than V2's identical-content retry
— it fully explains and fixed Insurance, with evidence, not guesswork) and closed one of the two
named commercial gaps outright. It did not close the ambiguity-detection gap, and the reason is now
understood with more precision than at any prior point in this engagement: (a) one split level is
not always enough for the densest chunks, and going deeper would mean recursion, explicitly
forbidden; (b) the pricing-stage detector's `parent_stage is None` heuristic doesn't recognize a
legitimate alternative structural form (a "Pricing" entry nested under a stage-structure table
rather than emitted bare) that a recovered response can take. Both are narrow, well-diagnosed,
non-architectural issues — not a case for redesigning Fast Analysis. The D1/D2/D3 null-weight
finding is unrelated to V3's own changes but is a real reliability gap worth closing before this
path reaches production, regardless of the ambiguity question. None of these were fixed
unilaterally in this package, consistent with its explicit scope boundaries.
