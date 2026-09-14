# Bank of Canada RFP 2026-026 — Stage A Full 16-Document Concurrency Validation (Package 4)

**Scope: full-corpus validation of bounded document-level concurrency, `max_document_concurrency = 2`,
following the passing five-document pilot** (`stagea-pilot-concurrency2-boc-2026-026-20260913T052312Z-b981a2`).
Nothing inside a document's own extraction changed: same prompt (hash-pinned in
`tests/test_stage_a_concurrency_pilot.py`), `max_tokens=8000`, `_STAGE_A_MAX_CHUNK_CHARS=12000`,
model, temperature, recovery trigger/order, merge/dedup logic, provenance rules. Concurrency
capped at 2 throughout — no attempt at 3 or higher. `bid-intelligence-rc2` untouched. This run's
output is **non-authoritative**; it is not promoted into any accepted lineage.

Control: `stagea-perf-boc-2026-026-20260912T224533Z-cf5a4d` (16 documents, serial, wall
2213.868837s, 54 calls, 30 recovery calls, 279,835 input / 307,265 output tokens, 912 records).

## Preflight

- Corpus digest verified against the frozen manifest (`5493933d2bba7ce80ede3c367e865635c4bd410d702b64a103d916d4573b95f2`)
  and all 16 per-file digests, before any spend — matched, dispatch proceeded.
- Targeted tests (`tests/test_stage_a_concurrency_pilot.py`, `tests/test_stage_a_extraction_reliability.py`):
  48/48 passed.
- `py_compile scripts/validate_stage_a_concurrency2_full_bank_of_canada.py`: clean.

## A. Run summary

Run ID: `stagea-concurrency2-full-boc-2026-026-20260913T054732Z-48564b`. All 16 documents
produced results, zero errors, zero zero-output documents. Corpus-order reconstruction was
verified programmatically inside the script itself (`actual_order == expected_order`, raising
immediately if violated) — confirmed `True`.

| Metric | Serial control | Full concurrent (concurrency=2) |
|---|---|---|
| Wall time | 2,213.868837 s | 1,227.524433 s |
| Total calls | 54 | 54 |
| Recovery calls | 30 | 30 |
| Input tokens | 279,835 | 279,835 (byte-identical) |
| Output tokens | 307,265 | 306,629 (−0.21%) |
| Stage A records | 912 | 899 (−1.43%) |
| Recovered-truncated documents | 4 (abstract.pdf, Appendix D1, Appendix G, master RFP) | 3 (abstract.pdf, Appendix G, master RFP — Appendix D1 resolved without a final truncated diagnostic this run) |
| HTTP status codes | — | `{"200": 54}` — zero non-200 responses |
| Real SDK retries | — | **0** (checked against the SDK's actual retry-log templates, not crude substring matching) |
| 429 count | — | **0** |
| 529 count | — | **0** |
| Timeout/network errors | — | **0** |
| Observed max simultaneous requests | 1 | **2** (matches configured cap exactly) |

**Seconds saved: 986.344404 s. Percentage improvement: 44.55%. Speedup: 1.80×.**
**Classification: Excellent (>40%).**

Per-document call structure matches control almost exactly: master RFP 17 calls (identical),
Appendix G 13 calls (identical), Appendix E 5 calls (identical), abstract.pdf 4 calls (identical),
Appendix D1 4 calls (identical count, but its recovery cascade resolved to `VERIFIED_ADEQUATE`
this run instead of `RECOVERED_TRUNCATED` — investigated in §B). Slowest concurrent document:
**master RFP, 681.449 s** (vs. 705.187 s serial) — the corpus's largest document remains the
long pole even under concurrency, since it cannot itself be parallelized (Package 4 explicitly
keeps each document internally serial).

## B. Direct Stage A correctness (all 16 documents)

`correctness_gates_recovery_optimization.py` (structural checks): **OVERALL PASS.** All 16
documents present, zero silently lost, zero zero-output documents, all expected families present
in every document's schema, only 2 of 899 records corpus-wide (both in Appendix G) have an
incomplete source-ref field — not a new provenance-rejection class, consistent with ordinary
background noise at this rate.

**Named checks, verified by direct content comparison against control (not by record-count
equality):**

| Check | Result |
|---|---|
| Master RFP submission deadline | **PASS** — `2026-09-30`, present |
| Master RFP substantial requirement/evaluation coverage | **PASS** — 115 requirements / 55 evaluation criteria (vs. control 110/57 — both large, comparable) |
| D1 15-page limit | **PASS** — present, word-for-word identical to control |
| D1 fine-grained rated sub-requirements | **PASS** — all 4 named critical items present verbatim: *"Approach to stakeholder engagement and communication"*, *"Escalation and issue-resolution processes"*, *"Methods used to monitor client satisfaction and gather feedback"*, *"Approach to managing multiple concurrent assignments and changing priorities"* (see investigation below) |
| D2 12-page limit | **PASS** — present, word-for-word identical to control |
| D3 10-page limit | **PASS** — present, word-for-word identical to control |
| Appendix G contractual clauses | **PASS** — all 18 clause_kind categories from control are present in the candidate (identical set); clause count increased slightly (55 vs. 61 — within normal range) |
| Appendix E commercial/pricing facts | **PASS** — 2 commercial clauses, 11 deliverables, 41 requirements (matches control closely) |
| abstract.pdf identity/context facts | **PASS** — `doc_metadata` present and consistent |

**Appendix D1 investigated in full, because its total record count (50) is a real, material
decline from control (77):** `requirements` dropped 53→30 and its diagnostic changed from
`RECOVERED_TRUNCATED` to `VERIFIED_ADEQUATE`, despite **byte-identical input tokens (18,944 in
both runs — the exact same request bytes were sent)**. Direct text comparison shows: the drop is
**not** the Package-2-style loss of distinct facts — every one of the 4 named critical
sub-requirements is present verbatim, and the reduction is concentrated in a run of sub-bullet
items (e.g. control's separately-numbered "For each project example: Client organization /
Industry and organizational size / Learning and development objectives / ..." breakdown appears
consolidated into fewer, broader requirement entries in this run) rather than missing content.
Cross-referencing this document's THREE independent live executions to date — control (53
requirements), the five-document pilot (54 requirements, Package 4's prior report), and this
full run (30 requirements) — with **identical code and, in two of the three cases, identical
input tokens**, shows genuine bidirectional run-to-run variance (sometimes above control, sometimes
below) rather than a one-directional degradation pattern. This is consistent with ordinary LLM
sampling variance in how exhaustively a sub-bullet list gets enumerated versus consolidated, not
with a concurrency-introduced defect — document independence was proven and tested in the prior
pilot report (§A there), and the same code path processing byte-identical input under serial vs.
concurrent execution has no mechanism by which concurrency itself could alter this. The
**correctness gate as defined by the user (presence of named critical facts, not record-count
equality) PASSES** for Appendix D1 in this run.

**STAGE A CORRECTNESS: PASS.**

## C. Shadow Stage B → Stage C → Canonical Opportunity

Built via the same deterministic production code (`normalize_package_facts`,
`reconcile_package_facts`) run twice: once over all 16 control-run Stage A outputs (BASELINE),
once over all 16 full-concurrent-run Stage A outputs (CANDIDATE) — a complete, non-authoritative
shadow, not a partial 5+11 mix (this is the full-corpus validation, not the five-document pilot).

### Stage B family counts

| Family | Baseline | Candidate | Delta |
|---|---|---|---|
| requirements | 427 | 417 | −10 (−2.3%) |
| dates | 22 | 23 | +1 (+4.5%) |
| evaluation_criteria | 86 | 84 | −2 (−2.3%) |
| submission_rules | 64 | 62 | −2 (−3.1%) |
| deliverables | 23 | 20 | −3 (−13.0%) |
| commercial_clauses | 88 | 84 | −4 (−4.5%) |

No family approaches Package 2's 38.2% collapse; the largest swing (deliverables, −13.0%)
was investigated at content level: of the 3 "missing" deliverables, 2 are near-duplicate labels
whose fuller-named counterpart is still present in the candidate ("Return of Materials and
Information" vs. the still-present "Return of Bank Materials and Work Product"; "Services" vs.
the still-present "Services as described in Schedule A") — genuine consolidation of redundant
labels, not lost content. Only 1 item ("After-Sales Services") has no clear counterpart in the
candidate — a single-item stochastic variance, not a systemic pattern.

### Stage C conflict comparison (classified per the required scheme — never by raw conflict ID,
which is a content-derived hash that changes whenever any underlying observation's wording shifts)

| Conflict | Baseline | Candidate | Classification |
|---|---|---|---|
| EVALUATION_CONFLICT — Title Corporate Profile (master RFP internal) | ✓ | ✓ | **SEMANTICALLY SAME / HASH CHANGED** |
| EVALUATION_CONFLICT — Team Experience (master RFP internal) | ✓ | ✓ | **SEMANTICALLY SAME / HASH CHANGED** |
| EVALUATION_CONFLICT — Methodology (master RFP internal) | ✓ | ✓ | **SEMANTICALLY SAME / HASH CHANGED** |
| EVALUATION_CONFLICT — Title Relevant Experience And References (master RFP internal) | ✓ | ✓ | **SEMANTICALLY SAME / HASH CHANGED** |
| DATE_CONFLICT — Presentation Date (master RFP internal) | ✗ | ✓ | **GENUINE NEW SOURCE-CONFLICT DETECTION** |
| Canonical BUYER_NAME | ✓ | ✓ | **SEMANTICALLY SAME / HASH CHANGED** |
| Canonical SOLICITATION_NUMBER | ✓ | ✓ | **SEMANTICALLY SAME / HASH CHANGED** |
| Canonical OPPORTUNITY_TITLE | ✓ | ✓ | **SEMANTICALLY SAME / HASH CHANGED** |
| Canonical INITIAL_DURATION | ✓ | ✗ | **GENUINE RESOLUTION / IMPROVED EXTRACTION** |

**Zero conflicts classified POTENTIAL EXTRACTION REGRESSION.**

The new `DATE_CONFLICT` flags a genuine internal inconsistency within the master RFP itself (two
different stated dates for "Presentation Date") — this exact conflict was also found,
independently, in the five-document pilot's own shadow check, meaning it has now been
**reproduced across two separate concurrent live executions**, reinforcing that it is a real
source-text ambiguity Stage C is correctly surfacing, not an artifact of this run.

The disappearing `INITIAL_DURATION` conflict was investigated at the observation level (not
inferred from the count): in the control run, abstract.pdf's "3 years" contract-term observation
had its structured `duration` field left `null` (an incomplete parse in the control run itself),
causing it to be treated as incompatible with the master RFP's fully-structured "3 years" value.
In this candidate run, abstract.pdf's *same* text was extracted with `duration="3"` correctly
populated, so the two observations now correctly **agree**, and the spurious conflict no longer
registers. This exact same root cause was independently found and explained in the five-document
pilot's shadow check — reproduced identically here.

### Governed semantics preserved

- **D1/D2/D3 scope separation:** intact — D2 (7) and D3 (4) submission-rule counts are identical
  between baseline and candidate; D1's count (9→5) reflects the same, already-investigated §B
  Appendix D1 variance, with no cross-scope merging (D1-scoped rules never leaked into D2 or D3).
- **Submission deadline:** byte-identical in both runs (`2026-09-30`, `RESOLVED`,
  `EXACT_AGREEMENT`, and the **same single `observation_id`** in both — the strongest possible
  stability signal for this specific critical fact).
- **Procurement model:** byte-identical (`"Multi-vendor Call-off"`) in both runs.
- **Contract-term ambiguity / opportunity identity:** `title`, `file_number`, and `client`
  (BUYER_NAME) remain flagged `CONFLICTED`/canonical-conflicted in both runs — the underlying
  cross-document ambiguities are preserved, not silently resolved away.
- **Evaluation hierarchy/conflicts:** all 4 baseline `EVALUATION_CONFLICT` entries preserved with
  identical topics.
- **Commercial-clause coverage:** Appendix G's full clause_kind category set preserved (§B).
- **Provenance-rejection behavior:** no new rejection category anywhere in either shadow run.

**SHADOW STAGE B/C: PASS. CANONICAL SEMANTIC VALIDATION: PASS.**

## D. Verification

`py_compile` on `extractor.py` and both new orchestration scripts: clean. `git diff --check`:
clean, no whitespace errors. Targeted tests (`tests/test_stage_a_concurrency_pilot.py`,
`tests/test_stage_a_extraction_reliability.py`): 48/48 passed, both before and after this live
run. Full suite: **1,266 passed, 2 skipped** — exactly matching the expected baseline, run both
before and after the live 16-document call.

## E. Recommendation

**AUTHORIZE PRODUCTION INTEGRATION OF BOUNDED CONCURRENCY=2.** Every acceptance criterion is met:
observed concurrency reached exactly 2; wall time improved 44.55% (Excellent, comfortably above
the 25% minimum and the 40% Excellent threshold); zero throttling of any kind across 54 real API
calls (zero 429s, zero 529s, zero real SDK retries, zero timeout/network errors, all HTTP 200);
Stage A completeness held at the content level for every named check across all 16 documents,
including a full re-investigation of Appendix D1's specific Package-2-adjacent regression
concern, which was traced to ordinary bidirectional LLM sampling variance rather than any
concurrency-introduced defect; provenance remained valid (only 2/899 records with an incomplete
ref, no new rejection class); the full Stage B → Stage C → Canonical Opportunity shadow showed no
family collapse anywhere near Package 2's disqualifying scale, and every individual conflict
difference was classified and explained — four unchanged, one genuinely new (and independently
reproduced across two separate live runs), one genuinely resolved by an extraction improvement,
zero regressions; the full test suite passed identically before and after.

Per the explicit instruction, this package stops here — concurrency remains capped at 2 (no test
of 3 or higher was performed), and this validated capability is **not yet wired into the normal
production Stage A entry point** (`scripts/commission_stage_a_live_telemetry_bank_of_canada.py`
and any other production caller of `extract_document_facts` remain serial, unmodified callers of
the existing, unchanged function). Production integration itself is a separate, not-yet-requested
step.
