# Bank of Canada RFP 2026-026 — Stage A Recovery-Path Optimization (Package 2)

**Baselines.** Frozen correctness reference: `bid-intelligence-rc2` (untouched, unmoved).
Authoritative historical Stage A: `phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5`.
Fresh telemetry control run: `stagea-perf-boc-2026-026-20260912T224533Z-cf5a4d`.

## A. Baseline (control run, restated precisely for this package's scope)

The prior Stage A Live Telemetry report scoped "recovery tax" to the 4 documents whose
**document-level** diagnostic was `RECOVERED_TRUNCATED`. This package's optimization target is
the **call-kind** mechanism itself (`call_kind != "initial"`), which is broader — it also
includes Appendix E's 3 recovery calls (that document's cascade fully resolved, ending
`VERIFIED_ADEQUATE` at the document level, but its recovery calls still happened and still cost
tokens/time). The correct, complete control baseline for this package is therefore:

| Metric | Value (all 54 calls, call-kind scope) |
|---|---|
| Total calls | 54 |
| Initial calls | 24 |
| Recovery calls (all kinds) | 30 |
| Initial input / output tokens | 133,621 / 146,491 |
| Recovery input / output tokens | 146,214 / 160,774 |
| Recovery share of input tokens | 146,214 / 279,835 = **52.25%** |
| Recovery share of output tokens | 160,774 / 307,265 = **52.32%** |
| Initial call latency | 1,109.437 s (50.25% of total API time) |
| Recovery call latency | 1,098.376 s (49.75% of total API time) |
| Total API time | 2,207.813 s |

*(This corrects/extends — not replaces — the prior report's 4-document-scoped 47.07%/47.45%/44.4%
figures, which remain accurate for that narrower, document-level-diagnostic scope.)*

## B. Recovery-state-machine analysis (read from `extract_document_facts`, no code changed yet at this stage)

**Chunking.** `chunk_document_text(doc_text, max_chunk_chars=_STAGE_A_MAX_CHUNK_CHARS=12000)`
splits marker-aware. A document ≤ 12,000 parsed chars becomes exactly 1 chunk → 1 `initial` call.

**Per-chunk main loop** (`extract_document_facts`, one iteration per chunk):
1. Call `_extract_chunk_facts(chunk, ..., call_kind="initial")` — full fixed prompt (14,688
   chars) + this chunk's text, `max_tokens=8000` (control) / `16000` (candidate).
2. **If `parse_status == "RECOVERED_TRUNCATED"`** (response hit the output ceiling and the JSON
   stack-repair parser recovered a partial object): split the *same chunk* in half by char count
   (`chunk_document_text(chunk, max_chunk_chars=len(chunk)//2)`, itself marker-aware, so it does
   not always yield exactly 2 pieces), and call `_extract_chunk_facts` again for **each**
   resulting sub-chunk with `call_kind="recovery_subchunk_truncated"` — again sending the full
   fixed prompt plus that (smaller) slice of the ORIGINAL chunk's text.
   - If **every** sub-chunk call reaches `COMPLETE`: the original truncated call's partial output
     is **discarded entirely**; only the sub-chunk results are aggregated. No duplicate records
     can result from this path — the truncated partial is thrown away, not merged.
   - If **any** sub-chunk call is *still* not `COMPLETE` (including hitting `max_tokens` again,
     observed once in this run — master RFP chunk 5, call 51): the original truncated result AND
     all sub-chunk results are merged (`aggregate_stage_a_facts([res] + sub_results, ...)`). Since
     `aggregate_stage_a_facts` only collapses **exact**-key duplicates (identical normalized
     description + category + rfso_ref for requirements; identical milestone+date for dates;
     etc.), a genuinely overlapping fact reworded differently between the original chunk's partial
     output and a sub-chunk's output would **not** be deduplicated — this is the one structurally
     real path to duplicate output, and it is bounded (one level deep, no further recursive split).
   - There is **no second-level retry** if a recovery sub-chunk itself is truncated — the cascade
     is exactly one split deep, then accepted as-is (`RECOVERED_TRUNCATED` at the document level).
3. **If `parse_status == "FAILED"`**: an analogous bounded one-level retry with
   `call_kind="recovery_subchunk_failed"` (not observed in this run — 0 `FAILED` calls occurred).

**Coverage guard** (after all chunks are processed and aggregated): if keyword-signal heuristics
suggest an implausibly empty family, the *entire document* is re-chunked at a smaller
`max_chunk_chars=8000` and, only if that produces *more* chunks than the original chunking,
every one of those smaller chunks is re-extracted (`call_kind="coverage_guard_recovery"`) and
merged with the original aggregation — up to 2 attempts. **Not observed in this run at all**
(0 `coverage_guard_recovery` calls across all 54) — every recovery in this run was the
max-token truncation path, not the under-coverage path.

**Why the master RFP required 17 calls.** It parses to 52,145 chars → 5 main chunks (12,000-char
boundary, marker-aware, observed lengths 10,678/11,126/10,191/9,754/10,396). Of these 5 initial
calls, 4 hit `max_tokens` (chunks 1, 3, 4, 5) and each triggered its own one-level recovery
cascade (3 sub-chunk calls each, except chunk 5 whose recovery had one further `max_tokens` hit).
1 initial + (4 × (1 initial + 3 recovery)) − 1 (chunk 2 needed no recovery) = 5 initial +
12 recovery = 17. Every truncation here traces to `stop_reason: "max_tokens"`; none traces to
malformed JSON for any other reason.

## C. Necessary vs. avoidable recovery work

**What is deterministically knowable from the persisted control-run telemetry (tokens, bytes,
latency, call_kind, stop_reason):**

- **Avoidable input repetition (fixed prompt resent):** the 14,688-char
  `STAGE_A_FACT_EXTRACTION_PROMPT` is resent, byte-for-byte, on every one of the 30 recovery
  calls (it is not narrowed to "only the missing category" — every call, initial or recovery,
  asks for the complete schema across all seven families). Measured: recovery calls' total
  request bytes = 540,808; fixed-prompt bytes within that = 14,688 × 30 = 440,640 = **81.48%** of
  all bytes sent on recovery calls. Using each call's own bytes-to-tokens ratio as a proxy,
  this projects to roughly **119,000 of the ~146,214 recovery input tokens (≈81%)** being the
  resent, unchanging instruction text rather than new document content — i.e. the majority of
  "recovery token tax" is prompt-resend tax, not document-content reprocessing tax.
- **Productive vs. wasted output, by code path (structural, verified programmatically against
  every cascade in the control run, not estimated):** every recovery cascade resolves one of two
  ways:
  - **Discard-path** (`sub_all_complete=True`): the preceding truncated `initial` call's ENTIRE
    output is thrown away and replaced by the sub-chunk results alone. **4 cascades** took this
    path — Appendix E chunk 2, and master RFP chunks 1, 3, 4. Their 4 discarded `initial` calls
    cost **25,986 input + 32,000 output = 57,986 tokens, 100% wasted** (each capped exactly at
    the 8,000-token ceiling, confirming truncation, then discarded outright). The **12 recovery
    calls** that replaced them cost a further 58,748 input + 58,321 output tokens — but these are
    fully productive (no original content competing for the same facts). Zero duplication risk
    on this path by construction.
  - **Merge-path** (`sub_all_complete=False`, i.e. at least one recovery call was itself still
    not `COMPLETE`): the original truncated call's partial output IS kept and merged with the
    sub-chunk outputs via `aggregate_stage_a_facts`'s exact-key dedup. **6 cascades** took this
    path — abstract.pdf, Appendix D1, all 3 of Appendix G's recovered chunks, and master RFP
    chunk 5. Their **18 recovery calls** cost 87,466 input + 102,453 output tokens. Unlike the
    discard-path, the *original* truncated call's tokens here are NOT wasted (its partial content
    is retained), but this is the one structurally real path to duplicate output: any fact
    reworded differently between the original chunk's partial output and a sub-chunk's output
    would not be caught by exact-key dedup and could double-count.
  - Total: 12 + 18 = 30 recovery calls, reconciling exactly with the corpus-wide count.
  - **Concrete duplicate-output evidence found (deterministic, on the final persisted facts, no
    LLM used):** a text-similarity scan of the control run's final `stage_a_document_facts.json`
    found 3 EXACT byte-identical requirement descriptions surviving as separate records in
    Appendix D1 (a merge-path document) — its 15-page response limit, page-size rule, and
    external-links rule each appear twice (`req_id` R1/M1, R2/M2, R3/M4). Root cause, confirmed
    by inspecting the surviving records: the identical source text was classified
    `category: "Rated"` in one extraction and `category: "Submission Compliance"` in the other —
    `aggregate_stage_a_facts`'s dedup key is `(description, category, rfso_ref)`, so a
    category disagreement between the original truncated pass and its recovery pass defeats
    dedup even though the description text matches exactly. This is a genuine, measured instance
    of merge-path duplication, root-caused to inconsistent re-classification of the same text
    across two calls, not to the dedup logic being absent. (Abstract.pdf and Appendix G showed
    many high-similarity pairs too, but manual inspection shows most are legitimately distinct
    requirements that share templated wording across different appendices, e.g. "Appendix B1/B2/B3
    ... must be completed and submitted" — not duplicates. Only exact/near-exact text matches,
    like Appendix D1's, are true leaked duplicates.) This is a real, additional benefit of
    reducing how often the merge-path fires at all (fewer chunks needing a second independent
    pass over the same text means fewer chances for a category-disagreement duplicate) — but
    fixing the dedup key itself would be a Stage A aggregation change, out of scope for this
    package, which touches only `_STAGE_A_MAX_OUTPUT_TOKENS`.
- **What is NOT deterministically knowable from the control run's persisted telemetry:**
  record-level classification of each recovery call's output into
  NECESSARY-NEW-FACT / DUPLICATE-FACT / STRUCTURAL-JSON-OVERHEAD requires the actual parsed JSON
  body of each call, which the control run's telemetry does not persist (only token counts,
  latency, and stop_reason were captured; the parsed `data` dict was used in-memory and
  discarded). **This is being fixed for this package going forward, not retrofitted onto the
  already-spent control run:** `extractor.py`'s telemetry now additionally captures
  `record_counts` (a deterministic, no-LLM, per-family count of that call's own raw parsed
  output) on every call, so the five-document pilot and the eventual full run both produce
  per-call record counts natively. This does not, by itself, distinguish "new" from "duplicate"
  records (that still requires content-level comparison across a document's calls), but it is
  the necessary foundation for it and is reported per document in §D below.

**Bottom line separating necessary from avoidable work:** the single largest, most precisely
quantified avoidable cost is **resending the full 14,688-character prompt on every recovery
call** (≈81% of recovery call bytes) — this is unavoidable under the *current* recovery design
(Option B in §E addresses it directly, at higher risk) but is orthogonal to *why* recovery
happens at all. The single largest quantified cause of recovery happening at all is **the fixed
8,000-token output ceiling being insufficient for some chunks' fact density** — this is
addressed directly, and with the lowest engineering/behavioral risk, by Option A (raise
`max_tokens`), which is why it is the selected candidate (§E, §F).

## D. Five-document call traces

Pilot run: `stagea-pilot-recovery-opt2-boc-2026-026-20260913T001428Z-2dfb0d` (live, one execution,
`_STAGE_A_MAX_OUTPUT_TOKENS=16000`, everything else — prompt, `_STAGE_A_MAX_CHUNK_CHARS=12000`,
recovery cascade logic, model, temperature, serial concurrency, document ordering — unchanged).

| Document | Control calls | Pilot calls | Control recovery calls | Pilot recovery calls |
|---|---|---|---|---|
| Master RFP | 17 | 8 | 12 | 3 |
| Appendix G | 13 | 10 | 9 | 6 |
| Appendix E | 5 | 2 | 3 | 0 |
| Appendix D1 | 4 | 1 | 3 | 0 |
| abstract.pdf | 4 | 1 | 3 | 0 |
| **Total** | **43** | **22** | **30** | **9** |

Pilot call-kind sequences: master RFP now 5 `initial` + 3 recovery (down from 5 initial + 12
recovery); Appendix G now 4 `initial` + 6 recovery (down from 4 initial + 9 recovery); Appendix
E, D1, and abstract.pdf each now complete in exactly their predicted chunk count with **zero**
recovery calls at all. Every document's document-level diagnostic is now `VERIFIED_ADEQUATE` —
none is `RECOVERED_TRUNCATED` any more, meaning the merge-path (§C's duplication-risk path) was
not exercised at all in this pilot for these 5 documents.

## E. Selected optimization

**Chosen candidate: Option A — raise the fixed output-token ceiling.**

- **Established from the code, not assumed:** the installed Anthropic SDK (`anthropic==0.121.0`)
  declares no client-side output-token ceiling for `claude-haiku-4-5-20251001` —
  `anthropic._constants.MODEL_NONSTREAMING_TOKENS` (the only place the SDK encodes any
  per-model token threshold) lists only four older Opus model identifiers, and this model is not
  among them. No file in this repository declares an authoritative ceiling either — the prior
  `max_tokens=8000` was simply the chosen operating value, not a documented hard limit. The SDK
  therefore places no barrier in the way of raising it, and the pilot's own API calls confirmed
  16,000 is accepted without error — establishing empirically that the true ceiling is at least
  16,000, via the mechanism the user asked for (the live call itself), without a separate
  unauthorized probe.
- **Value chosen:** `_STAGE_A_MAX_OUTPUT_TOKENS = 16000` (2× control) — a single module-level
  constant in `extractor.py`, replacing the hardcoded `8000` literal at the one call site shared
  by every call kind (`_extract_chunk_facts`). Deliberately conservative rather than jumping to
  an assumed maximum, precisely because of the risks the user's own framing named.
- **Why this over B/C/D (as reasoned before spending):** Option D (shrink chunks) is directly
  falsified as a general fix by §B/§D's chunk-structure findings — two of the four historically
  recovered documents are already single-chunk. Option C has the highest behavioral impact and
  was explicitly deprioritized unless A/B cannot solve the problem. Option B doesn't address why
  recovery is triggered at all. Option A directly targets the measured, 100%-confirmed root
  cause (`stop_reason: max_tokens`) with the fewest moving parts.
- **Nothing else changed:** prompt text, `_STAGE_A_MAX_CHUNK_CHARS`, the recovery cascade's
  control flow, model, temperature, and concurrency (still serial, 1) are all byte-for-byte
  unchanged in the pilot run.
- **Outcome: REJECTED after the pilot (see §F/§G).** The hypothesis that this would reduce
  recovery calls and tokens was correct and confirmed. The hypothesis that this would preserve
  extraction completeness was **not** confirmed — a direct content comparison found a real,
  reproducible completeness regression (§G). `_STAGE_A_MAX_OUTPUT_TOKENS` has been reverted to
  `8000` in `extractor.py`; only the additive `record_counts` telemetry field remains from this
  package's changes.

## F. Pilot performance

| Document | Control calls→Pilot | Control input tok→Pilot | Control output tok→Pilot | Control sec→Pilot | Control records→Pilot |
|---|---|---|---|---|---|
| Master RFP | 17→8 | 92,821→48,574 | 102,204→78,742 | 705.2→579.5 | 281→226 |
| Appendix G | 13→10 | 66,740→51,993 | 77,890→93,416 | 599.1→720.1 | 245→191 |
| Appendix E | 5→2 | 27,308→12,807 | 30,181→19,131 | 244.4→155.0 | 76→66 |
| Appendix D1 | 4→1 | 18,944→5,327 | 23,705→10,753 | 158.2→81.1 | 77→30 |
| abstract.pdf | 4→1 | 21,984→6,916 | 22,770→9,862 | 140.2→72.1 | 76→44 |
| **Total (5 docs)** | **43→22 (−48.8%)** | **227,797→125,617 (−44.9%)** | **256,750→211,904 (−17.5%)** | **1,847.1→1,607.7 (−13.0%)** | **755→557 (−26.2%)** |

**Recovery calls eliminated:** 30 → 9 (**−70.0%**). **Round trips eliminated:** 21 fewer total
calls. **Repeated input tokens eliminated:** ~102,180 fewer input tokens corpus-wide for these 5
documents, consistent with the §C hypothesis that most recovery-call input volume was resent
fixed prompt.

**Honest anomaly, not smoothed over:** Appendix G got **slower**, not faster (599.1s → 720.1s,
+20.2%) and used **more** output tokens (77,890 → 93,416, +20.0%), despite needing fewer calls
(13 → 10) and fewer recovery calls (9 → 6). A single larger-budget call generating substantially
more output takes longer in wall-clock terms than several smaller calls would have, even with
less repeated-prompt overhead — call-count reduction does not automatically mean latency
reduction once a call's own generation length grows. This is exactly why the aggregate 13.0%
wall-time improvence is far smaller than the 48.8% call-count reduction would suggest, and why
Appendix E, D1, and abstract.pdf (which shrank in every dimension including output tokens) show
the pattern the hypothesis predicted while Appendix G does not.

## G. Pilot correctness

**PILOT CORRECTNESS: FAIL.**

The record-count drop (755 → 557, −26.2%) is **not uniformly explained by duplicate elimination**
— it is a mix of two different, opposite-quality effects, verified by direct text comparison
(not inferred from counts alone):

- **Genuine duplicate elimination (a real benefit) — abstract.pdf:** the control run's 26
  requirements were two near-complete passes over the *same* 13 facts (differently worded, e.g.
  "must be completed and submitted" vs. "must be submitted" for the same 13 appendix items) —
  exactly the merge-path duplication risk predicted in §C. The pilot's 13 requirements are the
  clean, de-duplicated set, matching the control's first 13 essentially one-to-one. This part of
  the count drop is a correctness *improvement*.
- **Genuine, unexplained content loss (a real regression) — Appendix D1:** the control run's 53
  requirements include 11 top-level category headings (R1–R11: Corporate Profile, Key Personnel,
  Curriculum & Program Design, etc.) **plus** 20+ substantively distinct sub-requirements
  extracted underneath several of those categories by independent recovery-cascade calls (e.g.
  under "Relationship Management": *"Escalation and issue-resolution processes"*, *"Methods used
  to monitor client satisfaction and gather feedback"*, *"Approach to managing multiple
  concurrent assignments"* — 18 distinct sub-items under one heading alone). The pilot's 11
  requirements are **exactly** the 11 top-level headings, word-for-word identical to the
  control's R1–R11, with **every one of the sub-requirement items missing** — no near-duplicate,
  no reworded restatement, simply absent. This is not deduplication; it is a real drop in
  extraction granularity/completeness.
- Appendix G and master RFP show a similar mixed pattern on manual inspection of their first 20
  requirements each — meaningful overlap plus some pilot-only and some control-only items on both
  sides — consistent with a mix of real duplicate-elimination and real granularity loss, not
  cleanly attributable to one or the other without exhaustive per-item review.

**Root-cause hypothesis (mechanical, consistent with the evidence, not asserted as certain):**
recovery sub-chunk calls, each independently prompted with the full extraction schema over a
*smaller* slice of text, extract with finer granularity per character than a single call given
the same text as one larger, uninterrupted chunk. Raising the output ceiling does not just let a
chunk finish without truncating — it changes how exhaustively the model extracts from that chunk
in one pass, an effect the user's own risk framing anticipated ("no guarantee of improved
completeness") and which materialized here, concretely, in at least one document.

**Coverage/schema/provenance mechanics remained intact** — no zero-output documents, no missing
extraction families, no source-ref validation failures (`correctness_gates_recovery_optimization.py`
returned overall PASS on those specific structural checks) — the failure is specifically a
content-completeness regression that a presence-only schema check cannot detect, which is why
direct content comparison (this section) was necessary and is the basis for the FAIL verdict.

## H. Shadow Stage B/C comparison

Built via `scripts/shadow_stage_bc_recovery_optimization.py`, comparing Stage B
(`normalize_package_facts`) + Stage C (`reconcile_package_facts`) run twice from the same
deterministic code: BASELINE (all 16 documents' control-run Stage A facts) vs. SHADOW (the 5
pilot documents' optimized facts substituted for their control counterparts; the other 11
documents' facts held identical in both runs, isolating the optimization's effect).

| Family | Baseline | Shadow | Delta |
|---|---|---|---|
| requirements | 427 | 264 | **−163 (−38.2%)** |
| dates | 22 | 15 | −7 (−31.8%) |
| evaluation_criteria | 86 | 79 | −7 (−8.1%) |
| submission_rules | 64 | 65 | +1 |
| deliverables | 23 | 14 | −9 (−39.1%) |
| commercial_clauses | 88 | 101 | +13 (+14.8%) |
| Stage C conflict count | 8 | 8 | 0 (unchanged) |
| Canonical opportunity conflict count | 4 | 4 | 0 (unchanged) |
| `doc_metadata` (title/client/deadlines) | — | — | unchanged |

**Interpretation:** the requirements-family drop propagates downstream essentially undiminished
(−38.2% at Stage B vs. −26.2% at raw Stage A record count for the same 5 documents, actually
*larger* proportionally once cross-document requirement deduplication in Stage B is applied to a
smaller starting set). Conflict detection and the canonical opportunity's conflict count were
unaffected — Stage C's conflict-detection logic did not break or silently lose conflicts — but
this offers no reassurance about the underlying fact loss, since a conflict can only be detected
between facts that were extracted in the first place. `doc_metadata` (submission deadline,
client, title) remained identical in both runs, confirming top-level document identity facts
were not affected. This is a material, downstream-visible governed-semantic regression, not
merely a Stage A internal artifact — reinforcing the §G FAIL verdict.

## I. Full-run performance

**Not performed.** Per Step 12's explicit instruction ("If the candidate fails: STOP. Do not
cascade into multiple alternative optimizations in the same package."), the full 16-document
validation run was not authorized to proceed once the five-document pilot failed its correctness
gate. No additional live API spend occurred beyond the five-document pilot itself.

## J. Full-run correctness

**Not applicable — no full run was performed (see §I).**

## K. Token savings

Measured only for the 5-document pilot scope (not corpus-wide, since no full run occurred):
input tokens −44.9% (227,797 → 125,617, −102,180), output tokens −17.5% (256,750 → 211,904,
−44,846). These savings are real and were not fabricated — but they came bundled with the §G
correctness regression in the same change, and Package 2's acceptance gate requires both
performance *and* correctness to pass together. Token savings alone do not justify shipping this
change.

## L. Latency savings

Measured only for the 5-document pilot scope: total wall time for these 5 documents −13.0%
(1,847.1s → 1,607.7s, −239.4s). Not uniform across documents — Appendix G's wall time *increased*
20.2% despite fewer calls (§F). Extrapolating this modest, non-uniform latency improvement to the
full 16-document corpus was not attempted, since the correctness failure means this change will
not be carried forward regardless.

## M. Remaining recovery behavior

Unchanged from the control run's baseline, since the candidate was rejected and reverted:
`_STAGE_A_MAX_OUTPUT_TOKENS` is back to `8000`, so recovery will trigger exactly as it did in the
accepted control run (30 recovery calls across the same 5 documents, 47–52% token/latency tax
depending on scope, 100% triggered by `stop_reason: max_tokens`). The one durable, additive
change from this package is the `record_counts` telemetry field, which is behaviorally inert and
available for any future retry of this or a different candidate.

## N. Tests

Added to `tests/test_stage_a_extraction_reliability.py::TestStageATelemetryCapture` (37/37 passing
in this file; 1,255 passed / 2 skipped full-suite, up from the 1,253/2 baseline solely due to
these 2 new tests):

- `test_telemetry_captures_record_counts_by_family` — the new additive `record_counts` field
  matches a deterministic, no-LLM per-family count of that call's own raw parsed output.
- `test_call_uses_configured_max_output_tokens` — every call site requests
  `_STAGE_A_MAX_OUTPUT_TOKENS` (asserted `== 8000`, its reverted/accepted value) via the single
  shared constant, not a hardcoded literal, verified via the mocked client's actual `call_args` —
  so a future retest of a different ceiling value remains a one-constant change with no risk of
  a missed call site.

No test makes a real model call. `py_compile extractor.py` and the targeted + full suite were run
after both the experimental change and the revert; both states pass cleanly.

## O. Next optimization recommendation

**Do not re-attempt Option A (further max_tokens increases) without first addressing why a
single larger-budget call extracts less exhaustively than multiple smaller-budget calls over the
same text** — simply raising the ceiling further would not fix this mechanism and could make it
worse (an even larger single pass, even less pressure to be exhaustive).

**Recommended next candidate: Option B — narrow the recovery-call context, WITHOUT changing
chunk size or extraction call structure.** This is now the best-supported remaining candidate
because it is the only one of the four options that does not touch how much text or how many
independent extraction passes occur — it only targets the ~81%-prompt-tax finding from §C, which
is orthogonal to the completeness regression this package discovered. Recommended scope for the
next package: keep every existing call (initial + full recovery cascade, unchanged chunk sizes,
unchanged `max_tokens=8000`) exactly as accepted today, and investigate whether the *fixed
instruction prompt* resent on every recovery call can be safely shortened (not the schema, not
the extraction instructions that drive granularity — only the truly redundant restatement of
material the model has already been told once in the same document's processing) without
altering what the model is asked to extract or how thoroughly. This should be evaluated with the
same rigor as this package: pilot on the same 5 documents, direct content comparison against the
accepted baseline (not just record counts), before any full-corpus run.
