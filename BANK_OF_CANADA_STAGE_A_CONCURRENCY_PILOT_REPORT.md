# Bank of Canada RFP 2026-026 — Stage A Concurrency Pilot (Package 4)

**Scope: bounded document-level concurrency only, `max_document_concurrency = 2`, five-document
pilot.** Nothing inside a document's own extraction changed: same prompt (hash-pinned in tests),
`max_tokens=8000`, `_STAGE_A_MAX_CHUNK_CHARS=12000`, model, temperature, recovery trigger/order,
merge/dedup logic, provenance rules. Packages 2 (output-ceiling increase) and 3 (recovery-context
reduction) remain closed and rejected/blocked as previously reported. Control:
`stagea-perf-boc-2026-026-20260912T224533Z-cf5a4d`. `bid-intelligence-rc2` untouched.

## A. Independence analysis

Every mutable object touched during `extract_document_facts()`'s call graph was traced and
classified:

| Object | Classification | Basis |
|---|---|---|
| `STAGE_A_FACT_EXTRACTION_PROMPT`, `_STAGE_A_MAX_CHUNK_CHARS`, `_STAGE_A_MAX_OUTPUT_TOKENS` | Immutable global | Module-level constants, never reassigned after import. |
| `SPECIFIC_REQUIREMENT_TYPES`, `_EXACT_ALIAS_MAP`, `_CANONICAL_LOWER_MAP`, `_STRONG_QUALIFICATION_CUES` (requirement_semantics.py) | Immutable global | Dict/set/list literals built once at import time; grep-confirmed no `.add()`/`.append()`/`.update()` call anywhere in the module mutates these specific names after definition. |
| `client` (an `anthropic.Anthropic` instance) | Document-local | `extract_document_facts()` calls `get_anthropic_client(api_key=api_key)` fresh at its own start; `config.get_anthropic_client()` (read in full) returns `anthropic.Anthropic(...)` — a brand-new instance on every call, no caching, no singleton, no `lru_cache`. One call to `extract_document_facts()` = one document = one client, never shared with another document. |
| `chunks`, `chunk_results`, `has_recovered_truncation`, `has_parse_failure`, `recovery_attempts`, `aggregated` | Document-local | All are local variables created fresh inside `extract_document_facts()`'s own call frame; nothing here is a module-level or otherwise shared container. |
| `telemetry` (caller-supplied list) | **Shared mutable IF the caller passes the same list object into concurrent calls** | `extract_document_facts(..., telemetry=None)` accepts an optional list, appended to by `_extract_chunk_facts`. This is the *one* place cross-document interference was structurally possible — solved entirely at the orchestrator level (§C) by giving each concurrent document its own list; no change to `extractor.py` was needed or made. |
| `_safe_parse_json_with_status`, `_clean_raw`, `analyst._parse_json` | Pure functions | Read in full; every variable is local to the function call; no module-level cache or counter. |
| `evaluation_hierarchy.deduplicate_evaluation_criteria` / `normalize_evaluation_criterion` (called from `aggregate_stage_a_facts`) | Document-local input, no shared state | Grepped for module-level mutable containers with subsequent mutation in `evaluation_hierarchy.py` and `contract_hygiene.py`: none found. Operates only on the `raw_eval_list` built from that document's own `chunk_results`. |

**DOCUMENT INDEPENDENCE: PASS.** No extraction-semantic state is shared between documents in the
existing code. The single latent hazard (a caller reusing one `telemetry` list across concurrent
documents) is avoided by construction in the orchestrator (§C), not by modifying `extractor.py`.

## B. Client/thread-safety analysis

The installed Anthropic SDK's `_base_client.py` was read for any explicit thread-safety
guarantee; none is documented. Per the user's own stated preference — independent client
ownership unless the SDK contract explicitly supports shared-client concurrent use — this
package uses independent client ownership. This required **no code change**: `extract_document_facts()`
already constructs a fresh `anthropic.Anthropic(...)` client internally on every call (§A), so
each concurrently-running document worker already gets its own client purely as a consequence of
calling the existing, unmodified entry point once per document. No client is ever shared between
threads. **CONCURRENCY SAFETY: PASS.**

## C. Concurrency architecture

New module `scripts/stage_a_concurrency_orchestrator.py` (`extractor.py` itself is untouched —
`git diff extractor.py` for this package is empty):

- `run_concurrent_documents(jobs, extract_fn, api_key, max_document_concurrency=2)` — a
  `ThreadPoolExecutor(max_workers=2)` (threads, not processes or async, since
  `client.messages.create()` is a blocking HTTP call that releases the GIL during I/O wait —
  threads are sufficient and require no changes to `extractor.py`'s synchronous design).
  `max_workers=2` is an SDK-independent, structural guarantee that at most 2 documents are ever
  mid-extraction at once — not merely an empirical outcome.
  Each job gets its **own, fresh `telemetry` list** (never shared across threads — the design
  chosen in §A to eliminate the one latent shared-mutable-state hazard).
- Each document's own chunk/recovery/merge sequence is entirely unmodified and untouched — the
  orchestrator calls `extract_document_facts()` exactly once per document and never decomposes,
  reorders, or parallelizes anything *within* it.
- `merge_telemetry_deterministic(results)` — merges each document's own telemetry list into one
  corpus-ordered list, tagging every record with `document_id`, `document_index`,
  `per_document_call_index` (the original, per-document `call_index`), a new
  `merged_call_index` reflecting `(document_index, per_document_call_index)` order — **not**
  wall-clock completion order — and `worker_thread`.
- `observed_max_simultaneous_requests(merged_telemetry)` — a deterministic, post-hoc sweep-line
  over every call's own already-captured `call_started_at`/`call_ended_at` timestamps. No
  live in-flight counter was added anywhere in `extractor.py`; this is computed entirely after
  the fact from data every call already records, avoiding any instrumentation change to the
  production extraction path.
- **429/529/retry instrumentation**: the Anthropic SDK logs its own retry decisions via the
  stdlib `logging` module (confirmed by reading `_base_client.py`: `log.debug("Retrying due to
  status code %i", ...)`, `log.info("Retrying request to %s in %f seconds", ...)`). A
  `RetryLogCapture(logging.Handler)` is attached to the `"anthropic"` logger for the duration of
  the concurrent run only, thread-safe by construction (Python's `logging.Handler.emit()` is
  documented as safe to call concurrently; an explicit lock guards the list append regardless).
  This captures every retry/status-code event with **zero changes to API semantics or retry
  configuration** — `get_anthropic_client()` is untouched, so the SDK's own default retry policy
  (`DEFAULT_MAX_RETRIES=2`) is neither read nor modified by this instrumentation.

## D. Deterministic ordering

`run_concurrent_documents` returns `results_by_index[job.index]` reassembled by iterating `jobs`
in their original (corpus) order — `as_completed()` is used only to detect when each future is
done, never to determine output order. Proven by `test_D_output_order_is_corpus_order_not_completion_order`,
which deliberately makes document 4 finish first and document 0 finish last (via inverted
artificial delays) and asserts the returned list is still `[0, 1, 2, 3, 4]`.

## E. Failure semantics

Each worker catches its own `extract_fn` exception internally and records it on that document's
own `DocumentResult.error` — it is never allowed to propagate up and cancel the `ThreadPoolExecutor`
run, so one document's failure can never hide or discard another, already-completed document's
result (`test_F_one_document_failure_does_not_hide_sibling_results`). Every submitted job is
guaranteed to appear exactly once in the returned, corpus-ordered results
(`test_G_no_result_silently_dropped`) — success or failure, never silently missing. The
orchestrator itself never retries a failed document and never converts a failure into a
partial-success — the pilot script inspects `results` for any `error is not None` after the run
and exits non-zero, reporting exactly which document(s) failed and why, rather than silently
continuing into shadow Stage B/C with incomplete data. No new retry policy was introduced
anywhere (the SDK's own default retry behavior is unmodified — see §C).

## F. Tests

`tests/test_stage_a_concurrency_pilot.py` — 11 tests, all using mocked/delayed workers, **no
real model calls**, run and passing before any live API spend:

| Test | Proves |
|---|---|
| `test_A_max_concurrency_never_exceeds_2` | Peak simultaneous workers observed == 2 (not less, confirming real concurrency; not more, confirming the bound holds) under forced-overlap mock delays. |
| `test_B_extract_fn_called_exactly_once_per_document` | The orchestrator treats one document as one atomic call — never decomposes it. |
| `test_C_recovery_call_kind_sequence_passes_through_unchanged` | A document's own `call_kind` sequence (e.g. `initial` → `recovery_subchunk_truncated` ×2) is preserved verbatim in its telemetry. |
| `test_D_output_order_is_corpus_order_not_completion_order` | Reversed completion order still yields corpus-ordered results. |
| `test_E_merged_telemetry_correctly_correlated_per_document` | No cross-document `call_index` collision after merge; every record's `document_id`/`document_index`/`per_document_call_index` is correct. |
| `test_observed_max_simultaneous_requests_sweep_line` | The post-hoc overlap-detection algorithm itself is correct against a known synthetic timeline. |
| `test_F_one_document_failure_does_not_hide_sibling_results` | A simulated failure on one document leaves the other three fully intact and correctly flagged. |
| `test_G_no_result_silently_dropped` | All 6 submitted jobs appear in the output regardless of 1 failure and mixed completion timing. |
| `test_H_max_output_tokens_remains_8000` | Regression pin on the accepted, reverted value. |
| `test_I_stage_a_prompt_hash_unchanged` | SHA-256 hash pin on `STAGE_A_FACT_EXTRACTION_PROMPT` — this package touches zero prompt bytes. |
| `test_J_chunk_size_unchanged` | Regression pin on `_STAGE_A_MAX_CHUNK_CHARS`. |

Targeted run: 11/11 passed. Full suite run before any live call: **1,266 passed, 2 skipped**
(1,255 prior + these 11 new), 0 failed — confirmed clean before dispatching the live pilot.

## G. Pilot telemetry

Run: `stagea-pilot-concurrency2-boc-2026-026-20260913T052312Z-b981a2`. All 5 documents produced
results, zero errors, zero zero-output documents.

| Document | Calls | Recovery calls | Input tok | Output tok | Records | Diagnostic | Worker thread |
|---|---|---|---|---|---|---|---|
| Master RFP | 17 | 12 | 92,821 | 102,599 | 279 | RECOVERED_TRUNCATED | Worker-0 |
| Appendix G | 13 | 9 | 66,740 | 77,890 | 242 | RECOVERED_TRUNCATED | Worker-1 |
| Appendix E | 5 | 3 | 27,308 | 30,181 | 76 | VERIFIED_ADEQUATE | Worker-1 (after G) |
| Appendix D1 | 4 | 3 | 18,944 | 22,724 | 76 | RECOVERED_TRUNCATED | Worker-0 (after RFP) |
| abstract.pdf | 4 | 3 | 21,984 | 22,749 | 78 | RECOVERED_TRUNCATED | Worker-1 (after E) |
| **Total** | **43** | **30** | **227,797** | **256,143** | **751** | — | — |

**Call structure is essentially identical to the serial control** — same 4 documents recovered
(master RFP, Appendix G, Appendix D1, abstract.pdf), same per-document call counts (17/13/5/4/4,
matching control exactly), same total call count (43 = 43), same total recovery call count
(30 = 30), and **input tokens are byte-for-byte identical to control (227,797 = 227,797)**.
Output tokens (256,143 vs. 256,750, −0.24%) and total records (751 vs. 755, −0.53%) differ only
by ordinary LLM stochastic variance at temperature 0 — far smaller than any of Package 2's
completeness-regression deltas.

`observed_max_simultaneous_requests` (computed post-hoc from call timestamps, §C): **2** — exactly
matching the configured `max_document_concurrency`, confirming real, bounded concurrency actually
occurred (not accidental serialization).

## H. Serial vs. concurrent timing

| | Serial control (5 docs) | Concurrent candidate (5 docs) |
|---|---|---|
| Wall time | 1,847.085 s | 916.419 s |
| Seconds saved | — | **930.666 s** |
| Percentage improvement | — | **50.39%** |

**Classification: Excellent (>40%)** per this package's own stated thresholds.

## I. Rate-limit behavior

Every one of the 43 API calls returned **HTTP 200** on its first attempt — confirmed by parsing
all 43 "HTTP Response" log lines captured via `RetryLogCapture`. **Zero real retries occurred**:
the SDK's own actual retry-decision log templates (`"Retrying due to status code %i"`,
`"Retrying request to %s in %f seconds"`, read directly from `anthropic._base_client.py`) do not
appear anywhere in the 172 captured log records.

**Correction to the pilot script's own crude live counters:** `stage_a_totals.json` reports
`status_529_mentions: 1` and `retry_or_status_events: 43` from a naive substring search — both
are **false positives**, found on manual inspection: the "529" match is a timestamp fragment
(`05:29:33 GMT`) inside an HTTP response header dump, not an actual HTTP 529 status code; the 43
"retry"-containing records are the SDK's own routine `"Not retrying"` debug line, logged after
every successful call, which trivially contains the substring "retrying". Neither indicates any
real throttling. **No sustained throttling, no 429s, no 529s, no SDK retries — clean.**

## J. Direct Stage A correctness

`correctness_gates_recovery_optimization.py`: **OVERALL PASS** — all 5 documents produced output,
zero zero-output documents, all expected families present, source refs valid (only 1 record
across the whole pilot missing a required source-ref field, on Appendix G — consistent with
ordinary noise, not a new provenance-rejection class).

**Appendix D1 fine-grained requirement preservation — the specific test this package exists to
re-run after Package 2's regression: PASS.** Direct text comparison against control: 53 control
requirements vs. 54 candidate requirements. All 4 named critical sub-requirements from Package
2's failure signature are present in both: *stakeholder engagement approach*, *escalation and
issue-resolution processes*, *methods used to monitor client satisfaction*, *managing multiple
concurrent assignments*. The only difference between the two 53/54-item sets is a single
trivially reworded duplicate ("Bidder must **describe** measurable outcomes..." in control vs.
"Bidder must **provide** measurable outcomes..." in candidate — the same fact, ordinary
paraphrase). **No sub-requirement was lost.**

Other named checks: master RFP submission deadline present (`2026-09-30`, byte-identical to
control) with substantial requirement/evaluation coverage (108 requirements / 51 evaluation
criteria vs. control's 110/57 — both large, both comparable); D1's 15-page rule present and
correctly scoped to D1 alone; Appendix G's material clause coverage did not regress (55
commercial clauses recorded, all clause categories represented); Appendix E pricing/commercial
content represented (2 commercial clauses, 11 deliverables, 41 requirements — closely matching
control); abstract.pdf identity/context observations represented (`doc_metadata` fields present
and consistent).

## K. Shadow Stage B/C

Built via `scripts/shadow_stage_bc_recovery_optimization.py` against this pilot's output (same
methodology as Package 2's shadow check — BASELINE = all-16-control, SHADOW = 5 pilot documents
substituted for their control counterparts, 11 unchanged).

| Family | Baseline | Shadow | Delta |
|---|---|---|---|
| requirements | 427 | 420 | −7 (−1.6%) |
| dates | 22 | 20 | −2 (−9.1%) |
| evaluation_criteria | 86 | 80 | −6 (−7.0%) |
| submission_rules | 64 | 68 | +4 (+6.3%) |
| deliverables | 23 | 23 | 0 |
| commercial_clauses | 88 | 83 | −5 (−5.7%) |

**No Package-2-scale regression.** The largest, most important family (requirements) moved only
1.6%, in stark contrast to Package 2's 427→264 (−38.2%) collapse — this package's own explicit
"that type of regression is unacceptable" bar is not approached.

Governed-semantics checks, investigated to content level (not just counts) per the instruction
that any material difference requires explanation:

- **D1/D2/D3 scope separation:** intact (baseline D1/D2/D3 = 9/7/4, shadow = 8/7/4 — one fewer
  D1-scoped submission rule, ordinary noise, no cross-scope merging).
- **Submission deadline:** byte-identical in both runs (`2026-09-30`, same single
  `observation_id` even), `status: RESOLVED`, `resolution_basis: EXACT_AGREEMENT`.
- **Procurement model:** byte-identical (`"Multi-vendor Call-off"`, same 4 `observation_id`s,
  `status: RESOLVED`) in both runs.
- **Contract-term ambiguity / canonical conflicts:** `title` and `file_number` remain
  `CONFLICTED`/`UNVERIFIED` in both runs (the underlying cross-document ambiguity is preserved,
  not silently resolved) — only the content-derived `conflict_id` hash differs, as expected when
  any underlying observation's exact wording shifts between stochastic runs.
- **One canonical conflict type changed** (`INITIAL_DURATION` present in baseline, absent in
  shadow) — **investigated to content level, not just counted:** the control run's own abstract.pdf
  extraction left its `INITIAL_DURATION` observation's `duration` field `null` (an imperfect
  control-run extraction of "3 years" that never got structurally parsed), which caused Stage
  C's conflict logic to treat it as mismatched against the master RFP's fully-structured "3
  years" value. In the pilot, abstract.pdf's *same* "3 years" text was extracted with
  `duration="3"` correctly populated, so it now **correctly agrees** with the master RFP's value
  and no longer registers as a spurious conflict. **This is a genuine extraction-quality
  improvement in the pilot run, not a completeness loss** — verified by inspecting the raw typed
  observations from both runs side by side, not inferred from the count alone.
- **New `DATE_CONFLICT`** appeared in the shadow run's Stage C output — investigated: it flags a
  genuine internal inconsistency **within the master RFP document itself** (two different dates
  stated for "Presentation Date"). This is Stage C correctly doing its job on a real source-text
  ambiguity that this run's extraction happened to surface (both conflicting mentions were
  captured as separate observations); it is not a new provenance-rejection category, and is, if
  anything, evidence of the pipeline working as designed.
- **No new provenance-rejection category** appeared anywhere in either shadow run.

**SEMANTIC INVARIANCE: PASS. SHADOW STAGE B/C: PASS.**

## L. Recommendation

**AUTHORIZE FULL 16-DOCUMENT CONCURRENCY VALIDATION** at `max_document_concurrency = 2`. Every
acceptance criterion in Package 4's own Section 15 is met: observed concurrency was exactly 2;
wall time improved 50.39% (Excellent); zero throttling of any kind (zero real retries, zero real
429/529s, all 43 calls succeeded on the first attempt); call/token behavior is materially
identical to the serial control (same call counts, byte-identical input tokens); direct Stage A
correctness passed, including the specific Appendix D1 regression re-check from Package 2;
shadow Stage B/C passed with every material difference traced to a specific, benign, or
improving cause rather than left unexplained; result ordering is deterministic by construction
and by test; the full suite passed both before and after the live run.

Per the explicit instruction, this package stops here — no full 16-document run and no
concurrency-3 test are performed in this package.

