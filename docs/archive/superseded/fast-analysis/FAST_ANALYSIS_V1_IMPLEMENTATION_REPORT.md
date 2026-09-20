# Fast Analysis V1 — Implementation Report

**Verdict: FAST ANALYSIS NEEDS ANOTHER ITERATION.** Performance is excellent (108.7s total,
"Target achieved" tier, 11.4× faster than Deep Verify at the same concurrency level) and most
report content reproduces correctly, including the single most valuable fact in the whole
report (the rated-criteria weight tables, byte-identical to Deep Verify). But the live benchmark
found a real, root-caused defect: **2 of the 3 required ambiguity classes were not detected in
this run**, which the design contract treats as a non-negotiable, independent success criterion.
This report documents exactly what was built, what the live run measured, and the specific,
narrow fix the next iteration needs — not a redesign.

Design contract: `FAST_ANALYSIS_MINIMUM_VIABLE_INTELLIGENCE_AUDIT.md`. This package implements
directly from that audit's matrix and classifications; no scope was independently expanded.

## 1. What was built

| File | Purpose |
|---|---|
| `fast_analysis.py` | New sibling module. Document routing, deterministic page-limit regex extraction, four narrow per-route prompt schemas, bounded single-retry calling logic, an independent (non-Deep-Verify-orchestrator) bounded-concurrency dispatcher, and the three targeted ambiguity detectors. |
| `scripts/fast_analysis_report_adapter.py` | Deterministic, no-LLM adapter mapping `FastAnalysisResult` into the same content-module shape `boc_bid_intelligence_preview_content.py` uses, so the existing PDF renderer produces a directly comparable output. |
| `scripts/build_boc_bid_intelligence_preview_pdf.py` (modified) | `build()` now accepts optional `content=`/`out_path=` parameters, defaulting to the exact prior Deep Verify behavior. Verified byte-for-byte page-count identical (13 pages) after the change — a safe, behavior-preserving refactor of the *renderer*, not of Deep Verify's governed pipeline. |
| `scripts/benchmark_fast_analysis_bank_of_canada.py` | Live benchmark runner: corpus-digest gate, orchestration, telemetry persistence, PDF generation. |
| `tests/test_fast_analysis.py` | 32 deterministic tests, no live calls. |

**Deep Verify was not modified, simplified, or touched** beyond the additive, default-preserving
`build()` parameter change above. `extractor.py`, `fast_analysis.py`'s own import surface from
it (`chunk_document_text`, `_safe_parse_json_with_status` — both pure, side-effect-free
utilities), and the Deep Verify orchestrator (`scripts/stage_a_concurrency_orchestrator.py`) are
all untouched. Fast Analysis's own concurrency dispatcher in `fast_analysis.py` is a fresh,
independent `ThreadPoolExecutor` — it does not import or depend on the Deep Verify orchestrator.

## 2. Document routing (implemented exactly per audit S D)

| Route | Documents | Count |
|---|---|---|
| `SKIP` | abstract.pdf, Appendix A, Annexe F (ESG), superseded pre-amendment D2 | 4 |
| `EVAL_ONLY` (batched into 1 call) | Appendix B1/B2/B3, C1/C2/C3 | 6 |
| `EVAL_ONLY` (individual) | Amendment-1 D2, D1, D3 | 3 |
| `CONTRACT_NARROW` | Appendix E | 1 |
| `COMMERCIAL_ONLY` | Appendix G | 1 |
| `IDENTITY_EVAL_REQ` (deep, narrowed) | Master RFP | 1 |

**Deterministic (no-LLM) page-limit extraction** ran for D1/D2/D3 and returned the correct values
in the live run: D1=15, D2=12, D3=10 — matching Deep Verify exactly, at zero LLM cost
(`deterministic_extraction_seconds: 0.000078`).

## 3. Tests and Deep Verify regression check

- `tests/test_fast_analysis.py`: 32/32 passed (routing, page-limit regex, minimal-schema
  validation, source-reference retention, batching, skip rules, all three ambiguity detectors,
  deterministic report assembly).
- One test bug was caught and fixed during development (`test_identity_eval_req_prompt_omits_
  contract_risks_and_deliverables` initially flagged the prompt's own *exclusion* instruction —
  "do not extract deliverables" — as if it were a request for that field; fixed to check actual
  JSON schema keys instead of any substring match).
- An integration smoke test with mocked API responses confirmed correct end-to-end wiring
  (routing/skip/batch/dispatch/telemetry/page-limits/ambiguity-detection) before any live spend.
- Full suite after implementation: **1,298 passed, 2 skipped** — unchanged from the pre-Fast-Analysis
  baseline plus the 32 new tests; Deep Verify's own test suite is fully green.

## 4. Live benchmark

One authorized live run, `fastanalysis-v1-boc-2026-026-20260913T094132Z-5de413`, concurrency=2,
against the same corpus digest Deep Verify's accepted baseline used. Deep Verify was **not**
rerun; the existing accepted numbers were used as the comparison baseline, as instructed.

| Metric | Deep Verify (concurrency=2) | Fast Analysis V1 | Reduction |
|---|---|---|---|
| Total LLM calls | 54 | **12** | 77.8% |
| Input tokens | 279,835 | **37,438** | 86.6% |
| Output tokens | 306,629 | **27,418** | 91.1% |
| Recovery/retry calls | 30 | **1** | 96.7% |
| Extracted records | ~899 | **123** | 86.3% |
| Wall time | 1,227.524 s | **107.543 s** (108.659 s incl. parsing + report assembly) | 91.2% |

**Speedup: 11.4× vs. Deep Verify at concurrency=2; 20.6× vs. the original serial baseline.**
**Classification: Target achieved (61–120s tier).**

## 5. The ambiguity-detection gap — root cause

`category_date_distinctions: 1` (correct — the known Oct 26 / Nov 2 presentation-date split was
found). `evaluation_weight_conflicts: 0` and `pricing_stage_ambiguity: 0` — both **should** have
fired, since the underlying master RFP genuinely contains the conflicting scoring language Deep
Verify found.

Direct inspection of the master RFP's own call telemetry in this run:

```
call_index=0  chunk_chars=21804  stop=end_turn        parse=COMPLETE
call_index=1  chunk_chars=22847  stop=max_tokens       parse=RECOVERED_TRUNCATED   <-- here
call_index=2  chunk_chars=7494   stop=end_turn         parse=COMPLETE
```

Chunk 1 of 3 hit `FAST_MAX_OUTPUT_TOKENS=4000` and was truncated. `_has_required_fields()` for
the `IDENTITY_EVAL_REQ` route only checks that `doc_metadata` is non-empty (audit S 8's own
example of a "required field"); it does not check whether `evaluation_criteria` is *complete* for
that chunk. Since `doc_metadata` was already present, the bounded single retry never fired, and
whatever evaluation-criteria occurrences were in the truncated tail of that response — very
plausibly including the second, conflicting mention of "Corporate Profile" / "Methodology" that
Deep Verify's exhaustive extraction found — were silently lost. This is not a flaw in the
detection logic itself (`detect_evaluation_weight_conflicts` is unit-tested and works correctly
against the data it's given, and does correctly filter out the null-weight entries the smaller
appendix forms return); the gap is upstream, in what data reached it.

**This is exactly the failure mode the design contract most wanted to guard against** — audit
S 8 explicitly named "prove it is required" before adding any retry, and this run supplies that
proof directly: a truncation on the one document responsible for all three known ambiguities
silently cost two of them.

**Recommended fix for the next iteration (not implemented in this package, per the explicit stop
instruction):** extend `_REQUIRED_FIELDS_BY_ROUTE[ROUTE_IDENTITY_EVAL_REQ]` to also require a
non-trivial `evaluation_criteria` count (or, more precisely, trigger the bounded retry whenever
`stop_reason == "max_tokens"` regardless of which fields are already non-empty — this is a
narrower, more targeted signal than field-presence and directly matches what actually happened
here). This is a small, scoped change to the existing bounded-retry condition, not a return to
Deep Verify's recursive splitting cascade.

## 6. Other content-fidelity findings (full detail in `FAST_ANALYSIS_V1_REPORT_FIDELITY.json`)

- **Section 3 (What Is Being Procured?):** the three category-scope descriptions show identical,
  generic cross-category boilerplate instead of differentiated content — the adapter's
  category-tagging regex matched a summary sentence that mentions all three categories at once,
  rather than category-specific scope text.
- **Section 4 (Critical Dates):** the 4 correct, required dates are all present and accurate, but
  2 extra, garbled rows appear (a quota sentence — "up to seven (7) top-ranked proponents...—"
  was captured as if it were a MILESTONE date).
- **Section 5 (Evaluation):** the weight tables — the report's single most valuable content — are
  **byte-identical** to Deep Verify across all 18 point values in 3 categories. One dangling
  cross-reference ("see Ambiguity 1 in Section 8") no longer points at anything real in this run's
  own Section 8.
- **Section 7 (Commercial):** 8 of 10 Deep Verify topics have a real, semantically equivalent
  Fast Analysis counterpart (genuine Appendix G clause text). Insurance (the named $3M CGL/E&O/
  WSIB figures) is **missing** — confirmed empirically, zero `INSURANCE`-kind clauses were
  extracted in this run — along with three pricing/contract-term rows that Deep Verify sourced
  from other families the Commercial section's narrow schema doesn't merge in.

## 7. What worked exactly as designed

- Routing, skip rules, and batching matched the audit's matrix exactly, with zero deviation.
- Deterministic page-limit extraction was 100% correct and cost zero LLM tokens.
- The narrow, per-route schemas measurably worked: output tokens per call dropped enough that
  only 1 of 12 calls needed any recovery at all (vs. 30 of 54 for Deep Verify).
- The report adapter successfully reused Buyer Intelligence unchanged (verified byte-identical)
  and produced a directly comparable PDF with zero new rendering code.
- Concurrency=2 was reused successfully with no new validation needed, exactly as scoped.

## 8. Recommendation

**FAST ANALYSIS NEEDS ANOTHER ITERATION.** The performance case is fully proven — this package
should not be re-litigated on speed. What remains is a narrow, well-diagnosed fix to the
bounded-retry trigger condition (S 5 above) plus two smaller adapter fixes (category-description
tagging in S 6, and merging Insurance/pricing facts into Section 7). None of these require a
different architecture, a larger schema, or Deep Verify's recovery cascade — they require making
the existing bounded-retry condition sensitive to the one signal (`stop_reason: max_tokens`) that
this run's own telemetry shows is the actual cause, exactly as the audit anticipated.
