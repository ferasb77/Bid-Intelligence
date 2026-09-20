# Bank of Canada RFP 2026-026 — Stage A Recovery-Context Optimization (Package 3)

**Outcome: no safe candidate identified. No code changed. No live API call made. Reported per
the user's own explicit stop condition:** *"If you cannot establish a safe reduction without
weakening the extraction contract, STOP and report that recovery-prompt minimization is not
safe."*

Frozen correctness reference `bid-intelligence-rc2` untouched. Production behavior unchanged in
every respect — `_STAGE_A_MAX_OUTPUT_TOKENS` remains `8000` (Package 2's rejected 16,000
experiment stays reverted); chunking, concurrency, model, temperature, the initial Stage A
prompt, and the recovery cascade's trigger logic are all exactly as accepted. The failed 16K
pilot (`stagea-pilot-recovery-opt2-boc-2026-026-20260913T001428Z-2dfb0d`) is used only as forensic
evidence per the user's instruction, never as an accepted baseline. Control:
`stagea-perf-boc-2026-026-20260912T224533Z-cf5a4d`.

## 1. Recovery prompt anatomy (byte-mapped, deterministic — no intuition)

`STAGE_A_FACT_EXTRACTION_PROMPT` is 14,688 bytes, resent unchanged on every call regardless of
`call_kind`. Its content decomposes exactly (sums to the full 14,688 bytes with no gap or
overlap):

| Section | Bytes | % of prompt |
|---|---|---|
| General framing + source-marker description | 365 | 2.5% |
| Source-traceability instructions | 495 | 3.4% |
| Requirement-classification instructions | 2,101 | 14.3% |
| Evaluation instructions | 1,633 | 11.1% |
| Submission instructions | 2,195 | 14.9% |
| JSON output schema (all 8 families) | 4,951 | 33.7% |
| Typed-observation instructions | 1,925 | 13.1% |
| Deliverable/commercial hygiene instructions | 1,023 | 7.0% |
| **Recovery-specific instructions** | **0** | **0.0%** |

The JSON schema section itself, broken down per family:

| Family | Bytes |
|---|---|
| doc_metadata | 319 |
| requirements | 486 |
| dates | 104 |
| evaluation_criteria | 583 |
| submission_rules | 642 |
| deliverables | 822 |
| commercial_clauses | 820 |
| typed_observations | 1,124 |

**Critical finding: there is no recovery-specific instruction block to trim.** `request_text =
STAGE_A_FACT_EXTRACTION_PROMPT + "\n\nDOCUMENT TO PROCESS (...)\n" + chunk_text` is the exact
same expression for every one of the 4 call kinds (`initial`, `recovery_subchunk_truncated`,
`recovery_subchunk_failed`, `coverage_guard_recovery`) — the prompt carries no branch, flag, or
text conditioned on `call_kind` at all. Every byte in the prompt is general-purpose extraction
instruction or schema, identical to what the initial call needs.

This decomposition is identical for every recovery call kind, since they all send the exact same
fixed prompt — there is no per-kind variation to map separately.

## 2. Recovery call semantics (established from code, not assumed)

Read directly from `extract_document_facts` / `_extract_chunk_facts`:

| Call kind | What it actually is | Prior-call context passed in? | Families it could legitimately emit |
|---|---|---|---|
| `recovery_subchunk_truncated` | A full, stateless re-extraction of a smaller sub-chunk of the *same physical chunk text* that just truncated. `chunk_document_text(chunk, max_chunk_chars=len(chunk)//2)` splits along source markers by character length — **not** by content family. | None. `_extract_chunk_facts(sc, filename, api_key, ..., call_kind="recovery_subchunk_truncated")` takes no prior-response argument; it is exactly as stateless as an `initial` call. | **All 8** — the sub-chunk is an arbitrary character-bounded slice of source text that can contain any mix of requirements, dates, evaluation criteria, submission rules, deliverables, commercial clauses, or typed observations. |
| `recovery_subchunk_failed` | Same structure as above, triggered by `parse_status == "FAILED"` instead of `RECOVERED_TRUNCATED`. | None. | **All 8**, same reasoning. |
| `coverage_guard_recovery` | Triggered when `inspect_stage_a_coverage()` flags a *specific* family as suspiciously empty relative to keyword-signal counts — but the recovery call itself re-chunks the **entire document** at a smaller `max_chunk_chars=8000` and re-extracts everything from those chunks. `coverage["suspicious_families"]` is computed and stored in the final diagnostic, but **is never passed to `_extract_chunk_facts`** — grep-confirmed: `suspicious_families` appears only at its computation site and in the diagnostic dict written to output, never as an argument to any extraction call. | None. | **All 8** — confirmed by the code, not inferred: even the one recovery path that is nominally motivated by a specific family's suspected absence does not narrow its own request to that family. |

**None of the three recovery call kinds is a continuation, and none is family-specific.** All
three are full, stateless, schema-unrestricted re-extractions of an arbitrary character-bounded
slice of the same document text — structurally identical in *purpose* to the `initial` call,
differing only in which (possibly smaller) slice of text they process.

## 3. Attempting to define a minimal equivalent recovery contract

For a family's instructions/schema to be safely removable from a recovery call, the code must
prove that call **cannot** emit that family. Per §2, no such proof exists for any of the three
recovery call kinds, because:

- Chunking (`chunk_document_text`) partitions strictly by character count along `[[SOURCE: ...]]`
  marker boundaries — it has no concept of content family. A recovery sub-chunk can span any
  physical region of the document (a paragraph of commercial clauses, a table of evaluation
  weights, a list of submission rules, a milestone date — in any combination), exactly as an
  `initial` chunk can.
- The one call kind motivated by a specific family's suspected absence
  (`coverage_guard_recovery`) does not narrow its request to that family in the code, and
  narrowing it now would be a *behavioral* change to the recovery trigger/request logic, which
  this package is explicitly barred from touching ("Do NOT change the number or trigger logic of
  recovery passes").
- No family's instruction block is severable independent of the others: source-traceability
  rules, controlled enums, classification rules, and JSON shape are each entangled with the
  general framing that a stateless call needs to correctly attribute `source_refs` to whatever it
  finds in its slice, regardless of family.
- Package 2 already produced a concrete, measured demonstration that a much *smaller*, purely
  behavioral change to recovery calls (only enlarging `max_tokens`, not touching schema or
  instructions at all) caused an undetected, real extraction-completeness regression (Appendix
  D1 lost 20+ distinct sub-requirements). Removing actual instruction/schema content — a strictly
  larger and less predictable intervention than changing a numeric ceiling — carries at least
  that much risk, with no comparable mechanism (like the API's own acceptance/rejection of a
  numeric parameter) to validate the change before spending on a live pilot.

**No instruction or schema block can be proven irrelevant to any recovery call kind under the
current, character-based, family-agnostic chunking architecture.** The only bytes that are not
general-purpose, all-family instructions are 0 (§1) — there is no severable "recovery-only"
padding, no vague "follow the same rules as before" shorthand present to trim, and no per-kind
prompt variation to differentiate in the first place.

**Conclusion: recovery-prompt minimization is not safe under the current architecture, and no
candidate was implemented.** Per the user's own explicit instruction, this is reported as a stop,
not forced past with a low-confidence guess.

## 4. What was NOT done, and why (per the user's own gating)

- No code was changed in `extractor.py` beyond what Package 2 already left in place (the
  additive `record_counts` telemetry field; `_STAGE_A_MAX_OUTPUT_TOKENS` remains `8000`).
- No new unit tests were added — there is no new recovery-prompt-builder logic to test, since no
  such logic was written. Writing tests for a design that was never implemented would test
  nothing real.
- No five-document pilot was run — there is no candidate to pilot. No live API spend occurred in
  this package.
- No shadow Stage B/C comparison was run — there is nothing to compare against the control shadow
  without a candidate's Stage A output.
- The full test suite was re-run to confirm the repository remains in exactly its accepted,
  post-Package-2 state (see §6).

## 5. Next recommendation

Both of the two lowest-engineering-complexity Stage A optimization candidates identified in the
original live-telemetry report are now closed on evidence:

- **Option A (raise `max_tokens`)** — tested, rejected (Package 2): real completeness regression.
- **Option B (narrow recovery context)** — analyzed, blocked at preflight (this package): no
  safe reduction exists under the current chunking architecture.

The remaining candidates from that original ranking are:
- **Concurrency** — orthogonal to extraction content entirely (touches only wall-clock
  scheduling of already-independent calls, not what is asked of the model or how much text it
  sees per call), previously ranked MEDIUM-HIGH BENEFIT (latency only) / LOW RISK. This is now
  the most promising remaining lever precisely because it cannot reproduce either of the two
  failure modes already found (Package 2's density-dependent completeness loss, or a hypothetical
  content-removal regression) — it changes *when* calls happen, never *what* is sent or *how
  much* text a single call must process.
- **Chunk-size strategy** and **document-specific handling** remain MEDIUM benefit / MEDIUM risk,
  unchanged from the original ranking, and would need to be re-evaluated in light of Package 2's
  finding that extraction granularity is sensitive to how much text a single call processes —
  meaning any chunk-size change (in either direction) now carries a demonstrated, non-hypothetical
  completeness risk that must be checked with the same direct-content-comparison rigor used here.
- **A genuinely family-aware chunker** (splitting recovery sub-chunks so a given recovery call
  can be proven to only see, say, a table of evaluation criteria) would make Option B viable, but
  is a chunking-architecture change, explicitly out of scope for a "reduction-only" package, and
  substantially higher engineering complexity than either A or B.

Per the user's explicit instruction not to switch into concurrency within this package, no
concurrency change is implemented here — it is named only as the recommended target for the next
package.

## 6. Verification

`py_compile extractor.py`: clean (no changes made). Full suite: **1,255 passed, 2 skipped**
(identical to the post-Package-2 accepted state — no regression, no change, because no code was
touched). `git diff extractor.py` for this package is empty.

## Final response fields

- **RECOVERY CONTEXT FORENSICS: PASS** — prompt content fully byte-mapped by section (§1);
  recovery call semantics established from code, not assumed (§2).
- **FIVE-DOCUMENT PILOT: NOT RUN** — no candidate existed to pilot; no live API call was made in
  this package.
- **SEMANTIC INVARIANCE: N/A** — no candidate to evaluate.
- **SHADOW STAGE B/C: N/A** — no candidate output exists to build a shadow package from.
- **STAGE A RECOVERY CONTEXT OPTIMIZATION: FAIL (blocked at preflight, by design — not a live
  failure)** — no safe reduction could be established without weakening the extraction contract,
  so none was attempted, per the user's own explicit stop condition.
- Control recovery input tokens: 146,214 (unchanged, all 30 corpus-wide recovery calls).
- Candidate recovery input tokens: **146,214 (unchanged — no candidate implemented)**.
- Tokens saved: **0**.
- Percentage recovery-input reduction: **0%**.
- Control/candidate total pilot input tokens: N/A — no pilot run.
- Control/candidate wall time: N/A — no pilot run.
- Calls/recovery calls before and after: unchanged, 43/30 for the five documents named in this
  request (identical to the accepted control run — no candidate ran).
- Appendix D1 fine-grained requirement preservation: **PASS (trivially — production behavior is
  byte-for-byte unchanged from the accepted control run; nothing was altered that could affect
  it)**.
- Shadow Stage B requirements before/after: N/A — no shadow run performed.
- Other material semantic differences: **none — no production behavior changed in this package**.
- Files changed: **none** (`extractor.py` remains exactly as Package 2 left it: additive
  `record_counts` telemetry only, `_STAGE_A_MAX_OUTPUT_TOKENS = 8000`).
- Tests added: **0** (no new logic exists to test).
- Full-suite result: **1,255 passed, 2 skipped** (unchanged).
- Recommendation: **DO NOT AUTHORIZE** — not because a candidate failed live, but because no
  candidate could be safely constructed; recommend the next package target concurrency instead
  (§5), since both content-side levers (output-ceiling size, recovery-prompt content) are now
  closed on hard evidence and concurrency is the one remaining candidate that cannot reproduce
  either failure mode already found.
- Report path: `BANK_OF_CANADA_STAGE_A_RECOVERY_CONTEXT_OPTIMIZATION_REPORT.md`
- Raw pilot path: N/A — no pilot was run in this package. (The Package 2 pilot,
  `stagea-pilot-recovery-opt2-boc-2026-026-20260913T001428Z-2dfb0d`, was used only as forensic
  input per the user's instruction, not re-run or extended here.)
