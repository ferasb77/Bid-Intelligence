# Bank of Canada RFP 2026-026 — Stage A Live Telemetry Report

**Classification: NON_AUTHORITATIVE_TELEMETRY_RUN.** This report documents one measurement-only
live Stage A execution. It does not replace, extend, or feed into the frozen, commissioned
`bid-intelligence-rc2` baseline. No Stage A optimization is implemented here — this run
produces evidence only.

## A. Run metadata

| Field | Value |
|---|---|
| Run ID | `stagea-perf-boc-2026-026-20260912T224533Z-cf5a4d` |
| Run classification | `NON_AUTHORITATIVE_TELEMETRY_RUN` |
| Output directory | `evaluation/bank_of_canada_briefing_pack/performance_telemetry/stagea-perf-boc-2026-026-20260912T224533Z-cf5a4d/` |
| Frozen baseline reference (git tag) | `bid-intelligence-rc2` |
| Authoritative Phase 1 run ID | `phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5` |
| Script | `scripts/commission_stage_a_live_telemetry_bank_of_canada.py` |
| Analysis script | `scripts/analyze_stage_a_live_telemetry.py` |
| Instrumentation file changed | `extractor.py` (additive `telemetry` parameter only) |
| Downstream promotion | None — Stage B/C/Canonical Opportunity/Structure/EOB/Pack were not regenerated from this run |

## B. Instrumentation validation

Before any paid call was made, `tests/test_stage_a_extraction_reliability.py::TestStageATelemetryCapture`
(7 tests) was run and passed, confirming:

- Telemetry capture does not alter the returned extraction result (`test_telemetry_capture_does_not_change_returned_result`).
- Missing `response.usage` attributes are tolerated without raising (`test_telemetry_tolerates_missing_usage_attribute`).
- `telemetry=None` (the default for every other caller) is a complete no-op (`test_telemetry_default_none_is_a_complete_no_op`).
- Call identity/request shape (model, temperature, `call_index`, `call_kind`, `chunk_chars`, `request_bytes`, `parse_status`, ISO timestamps) is captured correctly (`test_telemetry_captures_call_identity_and_request_shape`).
- `call_index` is monotonic and globally unique across multiple chunk calls for one document (`test_telemetry_call_index_is_monotonic_across_multiple_calls`).
- Recovery sub-chunk calls are labeled distinctly from the initial call (`test_telemetry_labels_recovery_subchunk_calls_distinctly_from_initial`).
- An API exception is recorded into telemetry (token/parse fields null, `error` populated) and then **re-raised unchanged** — telemetry never swallows an error (`test_telemetry_records_exception_and_reraises_unchanged`).

**Result: STAGE A INSTRUMENTATION: PASS.** The live run then captured, for all 54 calls: document
identity, chunk/call identity (`call_index`, `call_kind`), model, temperature, request bytes,
chunk characters, input/output tokens, stop reason, API latency, call start/end timestamps,
and parse/recovery status — matching the full 14-field checklist from the authorization.

## C. Corpus identity

Verified **before** `get_api_key()` was called (fail-closed):

- Manifest digest: `5493933d2bba7ce80ede3c367e865635c4bd410d702b64a103d916d4573b95f2` — matches frozen baseline exactly.
- Document count: 16/16.
- Per-file SHA-256 digests: all 16 match the frozen manifest exactly.

No fallback to the superseded 15-document fixture occurred. The run would have raised
`RuntimeError` and stopped before any spend if any of the above had mismatched.

## D. Whole Stage A totals (measured)

| Metric | Value |
|---|---|
| Stage A wall time | 2213.868837 s |
| Total API-active time | 2207.813499 s (99.73% of wall time) |
| Corpus parsing time (pre-loop, deterministic) | 1.062356 s |
| Artifact serialization time (post-loop) | 0.013643 s |
| Total LLM calls | 54 |
| Total input tokens | 279,835 |
| Total output tokens | 307,265 |
| Total Stage A records | 912 |
| Documents processed | 16 / 16 |
| Zero-output documents | 0 |
| Calls with errors | 0 |
| Documents requiring recovery | 4 |

## E. 16-document telemetry table

Columns: File bytes | Parsed chars | Calls | Input tok | Output tok | API sec | Wall sec | Records | Recovery | In-tok/1000-parsed-chars | Out-tok/record | Sec/record | API-sec/1000-in-tok | % wall time | % input tokens

| # | Document | Bytes | Chars | Calls | In tok | Out tok | API s | Wall s | Recs | Status | Tok/1k chars | Out/rec | Sec/rec | APIs/1k-in | %Wall | %In |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | abstract.pdf | 119,394 | 7,733 | 4 | 21,984 | 22,770 | 139.81 | 140.21 | 76 | RECOVERED_TRUNCATED | 2842.88 | 299.61 | 1.845 | 6.36 | 6.33 | 7.86 |
| 2 | Amendment1/Appendix D2 - Rated Criteria REVISED.docx | 50,745 | 5,323 | 1 | 5,157 | 7,529 | 33.89 | 34.11 | 22 | VERIFIED_ADEQUATE | 968.81 | 342.23 | 1.551 | 6.57 | 1.54 | 1.84 |
| 3 | OriginalRevision/Annexe F - Questionnaire ESG.xlsx | 28,985 | 2,077 | 1 | 4,758 | 1,497 | 14.84 | 15.08 | 3 | VERIFIED_ADEQUATE | 2290.80 | 499.00 | 5.027 | 3.12 | 0.68 | 1.70 |
| 4 | OriginalRevision/Appendix A - Submission Form.docx | 48,269 | 6,505 | 1 | 5,758 | 6,023 | 47.86 | 48.11 | 18 | VERIFIED_ADEQUATE | 885.17 | 334.61 | 2.673 | 8.31 | 2.17 | 2.06 |
| 5 | OriginalRevision/Appendix B1 - Mandatory criteria.xlsx | 14,247 | 1,161 | 1 | 4,399 | 4,548 | 34.54 | 34.78 | 15 | VERIFIED_ADEQUATE | 3788.98 | 303.20 | 2.319 | 7.85 | 1.57 | 1.57 |
| 6 | OriginalRevision/Appendix B2 - Mandatory criteria.xlsx | 13,999 | 757 | 1 | 4,301 | 2,761 | 22.00 | 22.26 | 9 | VERIFIED_ADEQUATE | 5681.64 | 306.78 | 2.473 | 5.12 | 1.01 | 1.54 |
| 7 | OriginalRevision/Appendix B3 - Mandatory criteria.xlsx | 14,240 | 1,144 | 1 | 4,397 | 4,389 | 33.34 | 33.58 | 15 | VERIFIED_ADEQUATE | 3843.53 | 292.60 | 2.238 | 7.58 | 1.52 | 1.57 |
| 8 | OriginalRevision/Appendix C1 - Minimum qualification.xlsx | 14,007 | 962 | 1 | 4,345 | 2,900 | 14.99 | 15.24 | 9 | VERIFIED_ADEQUATE | 4516.63 | 322.22 | 1.693 | 3.45 | 0.69 | 1.55 |
| 9 | OriginalRevision/Appendix C2 - Minimum qualification.xlsx | 14,104 | 1,108 | 1 | 4,389 | 3,060 | 23.93 | 24.17 | 10 | VERIFIED_ADEQUATE | 3961.19 | 306.00 | 2.417 | 5.45 | 1.09 | 1.57 |
| 10 | OriginalRevision/Appendix C3 - Minimum qualification.xlsx | 13,965 | 865 | 1 | 4,325 | 2,867 | 22.90 | 23.15 | 9 | VERIFIED_ADEQUATE | 5000.00 | 318.56 | 2.572 | 5.30 | 1.05 | 1.55 |
| 11 | OriginalRevision/Appendix D1 - Rated criteria response form.docx | 58,679 | 6,159 | 4 | 18,944 | 23,705 | 157.51 | 158.15 | 77 | RECOVERED_TRUNCATED | 3075.82 | 307.86 | 2.054 | 8.32 | 7.14 | 6.77 |
| 12 | OriginalRevision/Appendix D2 - Rated Criteria Response Form.docx | 55,852 | 5,326 | 1 | 5,161 | 7,761 | 59.31 | 59.55 | 23 | VERIFIED_ADEQUATE | 969.02 | 337.43 | 2.589 | 11.49 | 2.69 | 1.84 |
| 13 | OriginalRevision/Appendix D3 - Rated Criteria Response Form.docx | 52,110 | 4,648 | 1 | 5,048 | 7,180 | 56.49 | 56.73 | 24 | VERIFIED_ADEQUATE | 1086.06 | 299.17 | 2.364 | 11.19 | 2.56 | 1.80 |
| 14 | OriginalRevision/Appendix E - Pricing Form.xlsx | 44,836 | 18,457 | 5 | 27,308 | 30,181 | 244.13 | 244.42 | 76 | VERIFIED_ADEQUATE | 1479.55 | 397.12 | 3.216 | 8.94 | 11.04 | 9.76 |
| 15 | OriginalRevision/Appendix G - Form of Agreement.docx | 67,727 | 32,452 | 13 | 66,740 | 77,890 | 598.13 | 599.11 | 245 | RECOVERED_TRUNCATED | 2056.58 | 317.92 | 2.445 | 8.96 | 27.06 | 23.85 |
| 16 | RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf (master RFP) | 376,615 | 52,145 | 17 | 92,821 | 102,204 | 704.15 | 705.19 | 281 | RECOVERED_TRUNCATED | 1780.06 | 363.72 | 2.510 | 7.59 | 31.85 | 33.17 |

**% of total cost:** `API COST: NOT AUTHORITATIVELY AVAILABLE` for every row (see Section N).

## F. Complete LLM call inventory

Persisted verbatim, one JSON object per line, exact call sequence preserved (no aggregation) at:

`evaluation/bank_of_canada_briefing_pack/performance_telemetry/stagea-perf-boc-2026-026-20260912T224533Z-cf5a4d/stage_a_llm_calls.jsonl`

54 lines total. Each record: `call_index`, `call_kind`, `filename`, `model`, `temperature`,
`request_bytes`, `chunk_chars`, `call_started_at`, `call_ended_at`, `latency_seconds`,
`input_tokens`, `output_tokens`, `stop_reason`, `parse_status`, `error`.

## G. Token distribution (ranked, cumulative %)

| Rank | Document | Input tokens | % | Cum % |
|---|---|---|---|---|
| 1 | Master RFP (Talent, Learning and OD Services.pdf) | 92,821 | 33.17% | 33.17% |
| 2 | Appendix G - Form of Agreement.docx | 66,740 | 23.85% | 57.02% ← crosses 50% |
| 3 | Appendix E - Pricing Form.xlsx | 27,308 | 9.76% | 66.78% |
| 4 | abstract.pdf | 21,984 | 7.86% | 74.63% |
| 5 | Appendix D1 - Rated criteria response form.docx | 18,944 | 6.77% | 81.40% ← crosses 80% |
| 6–9 | Appendix A, D2 (OriginalRevision), D2 (Amendment1), D3 | 5,758 / 5,161 / 5,157 / 5,048 | 2.06 / 1.84 / 1.84 / 1.80% | up to 88.95% |
| 10–13 | Annexe F, B1, B3, C2 | 4,758 / 4,399 / 4,397 / 4,389 | ~1.6–1.7% each | up to 95.36% ← crosses 95% |
| 14–16 | C1, C3, B2 | 4,345 / 4,325 / 4,301 | ~1.55% each | 100.00% |

**Documents accounting for the first 50% of tokens:** top 2 (master RFP + Appendix G).
**First 80%:** top 5. **First 95%:** top 13 of 16.

## H. Wall-time distribution (ranked, cumulative %)

| Rank | Document | Wall s | % | Cum % |
|---|---|---|---|---|
| 1 | Master RFP | 705.19 | 31.85% | 31.85% |
| 2 | Appendix G | 599.11 | 27.06% | 58.92% ← crosses 50% |
| 3 | Appendix E - Pricing Form.xlsx | 244.42 | 11.04% | 69.96% |
| 4 | Appendix D1 | 158.15 | 7.14% | 77.10% |
| 5 | abstract.pdf | 140.21 | 6.33% | 83.43% ← crosses 80% |
| 6–10 | D2 (OrigRevision), D3, Appendix A, B1, D2 (Amendment1) | — | ~1.5–2.7% each | up to 93.97% |
| 11 | Appendix B3 | 33.58 | 1.52% | 95.49% ← crosses 95% |
| 12–16 | C2, C3, B2, C1, Annexe F | — | ~0.68–1.09% each | 100.00% |

**Documents accounting for the first 50% of wall time:** top 2. **First 80%:** top 5. **First 95%:** top 11 of 16.

The same two documents (master RFP, Appendix G) dominate both token consumption and wall time —
consistent, since API latency for this model scales primarily with token volume, not file type.

## I. Recovery tax

Per-document breakdown (the 4 `RECOVERED_TRUNCATED` documents):

| Document | Initial in/out tok | Recovery in/out tok | Initial lat (s) | Recovery lat (s) | % tokens from recovery | % time from recovery | Records |
|---|---|---|---|---|---|---|---|
| abstract.pdf | 6,916 / 8,000 | 15,068 / 14,770 | 58.86 | 80.96 | 66.67% | 57.9% | 76 |
| Appendix D1 | 5,327 / 8,000 | 13,617 / 15,705 | 61.42 | 96.10 | 68.75% | 61.0% | 77 |
| Appendix G | 23,066 / 25,582 | 43,674 / 52,308 | 190.00 | 408.13 | 66.36% | 68.2% | 245 |
| Master RFP | 33,467 / 39,175 | 59,354 / 63,029 | 309.15 | 395.01 | 62.75% | 56.1% | 281 |

*(Per-document figures reproduced verbatim from a fresh run of `scripts/analyze_stage_a_live_telemetry.py`
against `stage_a_document_telemetry.json` / `stage_a_llm_calls.jsonl`. "Initial" aggregates every
call in the document labeled `call_kind="initial"` — a large document like Appendix G or the
master RFP is split across multiple main-loop chunks, so it has more than one `initial` call, one
per chunk, each of which can independently trigger its own `recovery_subchunk_truncated`
follow-up calls; "recovery" aggregates every non-`initial` call.)*

**Corpus-wide recovery tax:**

- `RECOVERY TOKEN TAX (input)`: 131,713 / 279,835 = **47.07%**
- `RECOVERY TOKEN TAX (output)`: 145,812 / 307,265 = **47.45%**
- `RECOVERY TIME TAX`: 980.19 / 2207.81 = **44.4%**
- `RECOVERY COST TAX`: **NOT AUTHORITATIVELY AVAILABLE** (no authoritative per-token pricing in the repository; the token tax above is the closest measured proxy)

**Root cause, unambiguous and measured:** every single call whose `parse_status` became
`RECOVERED_TRUNCATED` had `stop_reason: "max_tokens"`. 100% of recoveries in this run were
triggered by hitting the 8,000-token output ceiling — never by malformed/incomplete JSON for
any other reason.

**Total recovery call count (corpus-wide): 30** of 54 calls (`call_kind != "initial"`); 24 calls
were `initial`. **A note on document-level counting:** the historical baseline's "4 recovered
documents" figure tracks the document-level `RECOVERED_TRUNCATED` diagnostic, which this fresh
run reproduces exactly (abstract.pdf, Appendix D1, Appendix G, master RFP). A 5th document —
Appendix E (Pricing Form.xlsx) — also triggered `recovery_subchunk_truncated` calls (3 of its 5
calls) after one of its 2 main chunks hit `max_tokens`, but its recovery cascade fully resolved
that chunk (`end_turn`) and the document-level diagnostic ended as `VERIFIED_ADEQUATE`, not
`RECOVERED_TRUNCATED` — the diagnostic flags documents where recovery was needed AND the final
coverage check still found a gap, not merely "a recovery call fired." This is reported for full
transparency; it does not change the "4 recovered documents, matching historical" comparison in
Section N, which is about the document-level diagnostic specifically.

## J. Wall-time accounting (no double-counting)

| Component | Seconds | Share of total script time |
|---|---|---|
| Corpus parsing (pre-loop, deterministic, no LLM) | 1.062356 | 0.05% |
| Stage A wall time (the extraction loop) | 2213.868837 | 99.94% |
| — of which: total API-active time | 2207.813499 | 99.67% of total |
| — of which: local processing (parsing responses, validation, per-doc bookkeeping, incremental writes) | 6.055338 (= 2213.868837 − 2207.813499) | 0.27% of total |
| Artifact serialization (post-loop, final JSON write) | 0.013643 | 0.0006% |
| **Complete wall clock (script total)** | **2214.944836** | **100%** |

**Finding: model/API latency overwhelmingly dominates.** 99.67% of the entire script's wall
clock is time spent waiting on the Anthropic API; local Python-side processing (JSON parsing,
validation, bookkeeping) accounts for barely a quarter of one percent. Any optimization that
does not reduce the number or size of API calls cannot meaningfully improve Stage A wall time.

## K. Concurrency behavior

- **Configured concurrency:** none. `extractor.py` and `scripts/commission_stage_a_live_telemetry_bank_of_canada.py` contain no `asyncio`, `ThreadPoolExecutor`, or `concurrent.futures` usage (confirmed by repo-wide grep, unchanged from the Performance Baseline phase's finding).
- **Observed max simultaneous requests: 1.** `call_index` is strictly monotonic and increases by exactly one call at a time; every document's constituent calls (`call_indices`) are a contiguous block that completes in full before the next document's first call begins (confirmed directly from `stage_a_document_telemetry.json`'s `call_indices` field — no interleaving across documents anywhere in the 54-call sequence).
- **Idle gaps:** total API-active time (2207.81s) vs. Stage A wall time (2213.87s) leaves only 6.06s of non-API time across the whole run — i.e., essentially no idle gap; the loop moves to the next call/document immediately after the prior one returns.
- This run did not change concurrency in any way; the above is a measurement of existing, unmodified production behavior.

## L. Master RFP deep trace

| Metric | Value | Historical (Phase 1) |
|---|---|---|
| Parsed characters | 52,145 | 52,145 (identical — parsing is deterministic) |
| Input tokens | 92,821 | — |
| Output tokens | 102,204 | — |
| Calls | 17 | — |
| Latency (wall) | 705.187394 s | — |
| Records | 281 | 288 |
| Recovery status | RECOVERED_TRUNCATED | RECOVERED_TRUNCATED (matches) |
| % of total Stage A wall time | 31.85% | — |
| % of total Stage A input tokens | 33.17% | — |
| Stop reasons across its 17 calls | 4× `max_tokens`, 13× `end_turn` | — |

The master RFP alone accounts for roughly a third of the entire corpus's tokens and wall time —
the single largest document by a wide margin, consistent with its file size (376,615 bytes, more
than 3× the next-largest document).

## M. Historical 4 recovery-document trace

All 4 documents that required recovery in the frozen Phase 1 baseline **recovered again** in this
fresh run — none succeeded first-pass and none failed in a new way.

| Document | Calls | Call-kind / stop-reason sequence (in order) | Doc-level status |
|---|---|---|---|
| abstract.pdf | 4 | initial(max_tokens) → recovery(max_tokens) → recovery(end_turn) → recovery(end_turn) | RECOVERED_TRUNCATED |
| Appendix D1 | 4 | initial(max_tokens) → recovery(end_turn) → recovery(max_tokens) → recovery(end_turn) | RECOVERED_TRUNCATED |
| Appendix G | 13 | 4 chunks, each `initial` followed by its own recovery cascade: initial(max_tokens)→recovery(max_tokens)→recovery(max_tokens)→recovery(end_turn) \| initial(max_tokens)→recovery(max_tokens)→recovery(max_tokens)→recovery(end_turn) \| initial(max_tokens)→recovery(max_tokens)→recovery(max_tokens, still COMPLETE)→recovery(end_turn) \| initial(end_turn, no recovery needed) | RECOVERED_TRUNCATED |
| Master RFP | 17 | 5 chunks: initial(max_tokens)→recovery(end_turn)→recovery(end_turn)→recovery(end_turn) \| initial(end_turn, no recovery needed) \| initial(max_tokens)→recovery(end_turn)→recovery(end_turn)→recovery(end_turn) \| initial(max_tokens)→recovery(end_turn)→recovery(end_turn)→recovery(end_turn) \| initial(max_tokens)→recovery(max_tokens)→recovery(end_turn)→recovery(end_turn) | RECOVERED_TRUNCATED |

Each of these 4 documents is split into multiple main-loop chunks (one `initial` call per chunk);
a chunk that hits `max_tokens` triggers its own bounded `recovery_subchunk_truncated` cascade
until that chunk's continuation completes (`end_turn`) or the recovery bound is exhausted. The
document-level `RECOVERED_TRUNCATED` diagnostic is set once for the document as a whole whenever
at least one of its chunks needed recovery — it does not mean every chunk needed it (e.g. Appendix
G's 4th chunk and the master RFP's 2nd chunk both completed on the first call, no recovery). Exact
per-call `call_index`/tokens/latency for all 4 documents are in the raw `stage_a_llm_calls.jsonl`
and were verified via `scripts/analyze_stage_a_live_telemetry.py` during this run's analysis.

## N. Historical Phase 1 comparison

| Metric | Fresh (this run) | Historical (Phase 1) | Delta |
|---|---|---|---|
| Stage A wall time | 2213.868837 s | 2245.556 s | −31.687 s (−1.41%) |
| Total records | 912 | 916 | −4 (−0.44%) |
| Documents recovered (RECOVERED_TRUNCATED) | 4 | 4 | 0 — identical set: abstract.pdf, Appendix D1, Appendix G, master RFP |
| Document coverage | 16/16 | 16/16 | 0 |
| Zero-output documents | 0 | 0 | 0 |
| Calls with errors | 0 | — (not previously instrumented) | n/a |

The −0.44% record-count delta (912 vs. 916) is well within expected stochastic variance for an
LLM-backed extraction stage — temperature is 0.0, but Claude's output is not guaranteed
byte-identical across independent API calls even at temperature 0, and Stage A's own design
(chunk-boundary-dependent recovery) means small differences in exactly where a chunk truncates
can shift a handful of records between adjacent extraction calls. No category-count anomaly or
major structural difference was found. This is expected and consistent with the explicit
authorization that Stage A output need not be byte-identical between runs — only Phase 1's own
frozen artifact remains the correctness reference; this fresh run is not compared for byte
identity and does not replace it.

## O. Cost

`API COST: NOT AUTHORITATIVELY AVAILABLE`

No authoritative per-token pricing exists anywhere in this repository (confirmed by the
Performance Baseline phase's `PRODUCTION_ECONOMICS_AUDIT.md`, and reconfirmed here — the
Anthropic SDK response objects captured in telemetry do not expose billed-dollar amounts, only
token counts). No pricing figure has been invented or estimated. Token counts in Sections D–I
are the authoritative, measured proxy for cost until an authoritative pricing source is added.

## P. Outliers

- **Appendix G and the master RFP** are the two clear outliers by both tokens and wall time
  (57.02% of tokens, 58.92% of wall time between them). Mechanically explained: they are the
  largest documents by parsed character count (32,452 and 52,145 chars respectively, vs. a
  median of ~1,600 chars for the other 14), so they require the most chunks, and both also
  triggered `max_tokens` recovery multiple times, compounding their share further. This is not a
  defect — it is the expected, telemetry-supported consequence of document size interacting with
  a fixed per-call output ceiling.
- **Appendix E (Pricing Form.xlsx)** has the highest `out-tok/record` ratio among non-recovered
  documents (397.12) and required one `max_tokens` stop mid-sequence without ultimately being
  classified `RECOVERED_TRUNCATED` — its coverage-guard / sub-chunk recovery cascade evidently
  resolved it within the same document-level pass. This is a mechanically consistent, not
  anomalous, telemetry pattern (a transient max_tokens stop on one chunk, recovered by the next
  call in sequence, without tripping the document-level `RECOVERED_TRUNCATED` diagnostic).
- **Annexe F - Questionnaire ESG.xlsx** has the lowest wall time (15.08s) and lowest output/record
  ratio's absolute output tokens, consistent with being the smallest parsed document (2,077
  chars) among small documents extracting only 3 records — no anomaly, direct function of size.
- No outlier here is labeled a defect merely for being expensive; every outlier above is
  explained by a measured, mechanical property (document size, chunk count, or an observed
  `max_tokens` stop) already present in the telemetry.

## Q. Ranked Stage A optimization candidates (analysis only — none implemented)

| Candidate | Expected benefit | Correctness risk | Engineering complexity | Validation burden | Rank |
|---|---|---|---|---|---|
| **Recovery-path reduction** (raise `max_tokens` and/or split large chunks pre-emptively so fewer calls hit the 8,000-token ceiling) | HIGH — eliminates up to 47% of tokens and 44% of wall time, evidenced by 100% of recoveries being `stop_reason: max_tokens` | LOW-MEDIUM — changes an existing, already-tested recovery path; requires re-verifying recovered output is still complete/correct | LOW-MEDIUM — likely a `max_tokens` bump plus chunk-size tuning, both existing knobs | MEDIUM — needs a fresh live run + record-count/coverage comparison | **1 — HIGH BENEFIT / LOW-MEDIUM RISK** |
| **Prompt/context reduction** (shrink or cache the 14,688-char fixed prompt resent on every call) | HIGH on token/cost (measured 76.02% of every request's raw bytes is the fixed prompt) but not on wall time (prompt tokens are cheap to process relative to full round-trip latency) | MEDIUM — any prompt wording change risks altering extraction behavior/output shape; requires careful equivalence testing | MEDIUM — needs prompt-compression work or provider-side prompt caching (if supported) without changing extraction semantics | HIGH — every extraction test and Stage A output shape must be re-verified | 2 — HIGH BENEFIT (cost) / MEDIUM RISK |
| **Concurrency** (parallelize independent per-document/per-chunk calls) | MEDIUM-HIGH on wall time only (calls are confirmed fully independent and serial today; parallelizing could cut wall time roughly in proportion to concurrency level) — zero token/cost benefit | LOW — no shared mutable state observed between document extractions; ordering is not semantically required for Stage A (each document's facts are independent) | MEDIUM — needs a bounded worker pool, rate-limit handling, and incremental-persistence logic updated for concurrent writes | MEDIUM — needs concurrency-safety tests plus a repeat live run to confirm output is unaffected | 3 — MEDIUM-HIGH BENEFIT (latency only) / LOW RISK |
| **Chunk-size strategy** (tune `_STAGE_A_MAX_CHUNK_CHARS` to reduce chunk count or recovery frequency) | MEDIUM — overlaps significantly with recovery-path reduction; could reduce recovery frequency as a side effect of better-sized chunks | MEDIUM — directly changes what data is visible to each call, closer to changing extraction behavior itself | LOW — single constant to tune, but requires empirical sweep | MEDIUM — needs multiple live runs to find a good value, real API spend to validate | 4 — MEDIUM BENEFIT / MEDIUM RISK |
| **Document-specific handling** (special-case very large documents like the master RFP and Appendix G) | MEDIUM — targets exactly the 2 documents responsible for ~57-59% of tokens/time, but the "special case" itself needs a general mechanism (likely folds into chunk-size or recovery-path work) | MEDIUM — creates a second code path, meaning correctness must be verified for a smaller/less-exercised branch | MEDIUM-HIGH — a distinct path with its own tests and failure modes | HIGH — dual-path validation | 5 — MEDIUM BENEFIT / MEDIUM RISK |
| **Duplicate-context removal** (avoid resending already-processed chunk context on recovery calls) | LOW-MEDIUM — telemetry shows recovery calls resend the full fixed prompt but only the same chunk's text, not accumulated prior chunks, so there is little already-duplicated context to remove at the request level; benefit would mainly overlap with prompt reduction | LOW — if implemented as scoped prompt trimming | MEDIUM | MEDIUM | 6 — LOW-MEDIUM BENEFIT / LOW RISK |
| **Model routing** (route smaller/simpler documents to a cheaper/faster model, larger ones stay on the current model) | LOW-MEDIUM — no per-model cost data exists to quantify savings (Section O), and correctness across a second model would need full re-validation against the extraction schema | HIGH — introduces a second model's output-quality variance into a schema-critical pipeline stage | HIGH — needs model-selection logic, a second model's prompt/temperature tuning, and dual-model regression testing | HIGH | 7 — LOW-MEDIUM BENEFIT / HIGH RISK |

## Recommended Optimization Package 2

**Recovery-path reduction.** This is the single candidate supported by the strongest, most
unambiguous measured evidence: 47.07% of input tokens, 47.45% of output tokens, and 44.4% of
API-active time in this live run were consumed by recovery calls, and **100%** of those recoveries
were triggered by an identical, single mechanical cause — `stop_reason: "max_tokens"` on an
8,000-token output ceiling. Unlike concurrency (which only helps wall time, not cost) or prompt
reduction (which requires touching wording that risks behavior drift), recovery-path reduction
directly targets the dominant, root-caused inefficiency with the lowest risk of altering
extraction semantics, since the recovery mechanism itself is already a tested, existing code
path whose triggering frequency — not its logic — would be the target of Package 2.

**No implementation has been made.** This is a ranked recommendation only, per the explicit
instruction to analyze without implementing.
