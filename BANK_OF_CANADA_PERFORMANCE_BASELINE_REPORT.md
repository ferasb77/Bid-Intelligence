# Bank of Canada RFP 2026-026 — Performance / Observability Baseline Report

**Scope:** measurement and instrumentation only. No prompts, models, temperatures,
max tokens, batching, concurrency, retry policy, caching, Stage A extraction
behavior, Stage D behavior, schemas, validators, provenance rules, or evidence
payload composition were changed. No optimization was implemented. No new LLM
calls were made to produce this report.

---

## A. Baseline fingerprint

| Field | Value |
|---|---|
| Git tag | `bid-intelligence-rc2` |
| Commissioned code commit | `1526c2cb1199eebb9992b593cf0c322d377af6ca` |
| Final pack ID | `pack-b11fe92992b988d51edba6077dc7f1999d864838a7e01acd7e332b3b3faeb600` |
| Pack revision | `pack-revision-8b3b21c79dd82605e7ea70ad5d622905aae826dddd1ce4b343fdb4ad8e945ebe` |
| Pack digest | `pack-digest-1b119bfe385002e2505b416ece164f5b8c4b28c60dda8d8c726dc4542519f943` |
| Corpus manifest digest | `5493933d2bba7ce80ede3c367e865635c4bd410d702b64a103d916d4573b95f2` |

---

## B. Execution graph (verified against current code, not assumed from commissioning order)

```
corpus ingestion (extract_document_with_metadata × 16, deterministic)
        │
        ▼
Evidence Adapter / Publication (adapt_procurement_corpus, publish_evidence — deterministic)
        │
        ▼
Stage A — extract_document_facts() × 16 documents (extractor.py:2857)
   per document: chunk_document_text() → 1 API call per chunk (_extract_chunk_facts,
   extractor.py:2788) → bounded recovery cascade (up to 2 sub-chunk retries on
   RECOVERED_TRUNCATED/FAILED, up to 2 whole-document coverage-guard recovery passes)
   — SEQUENTIAL, no concurrency (confirmed: zero asyncio/ThreadPoolExecutor/
   concurrent.futures in extractor.py)
        │
        ▼
Stage B (normalize_package_facts) — deterministic
        │
        ▼
Stage C (reconcile_package_facts) — deterministic
        │
        ├──────────────────────────────────────────────────────────────┐
        ▼                                                                │
Canonical Opportunity (build_canonical_opportunity/resolve_canonical_    │
   opportunity) — deterministic                                          │
        │                                                                │
        ▼                                                                ▼
Canonical Opportunity Publication          Stage D — synthesize_bid_brief()
   (evidence_grounding-based binding,      (extractor.py + stage_d_projection.py):
   deterministic)                          1 API call, bounded 2-attempt retry loop,
        │                                  full ~580,000-char context resent on retry
        ▼                                  — genuinely sequential relative to A/B/C,
Opportunity Structure Publication          NOT part of the EOB->Pack chain (Section G)
   (deterministic)
        │
        ▼
Opportunity Intelligence (analyze_opportunity) — deterministic
        │
        ▼
Opportunity Intelligence Publication (support-binding derivation + publish) — deterministic
        │
        ▼
Executive Opportunity Understanding (build_executive_opportunity_understanding) — deterministic
        │
        ▼
Executive Opportunity Brief (build_executive_opportunity_brief) — deterministic
        │                                    Buyer Brief chain (independent):
        │                                    Buyer Evidence (no new fetch) → Canonical
        │                                    Buyer → Buyer Intelligence Analysis →
        │                                    Buyer Brief — all deterministic
        └───────────────────┬────────────────────────┘
                             ▼
              Executive Briefing Pack composition (deterministic, pure Python,
              zero LLM/network — confirmed by grep in the prior pack commissioning report)
```

**Per-stage summary:**

| Stage | Production entry point | Deterministic or LLM | Invocations (this corpus) | Serial/parallel | Existing timing instrumentation | Existing token instrumentation | Existing retry instrumentation | Persisted diagnostics |
|---|---|---|---|---|---|---|---|---|
| Ingestion/Evidence | `extract_document_with_metadata`, `adapt_procurement_corpus`, `publish_evidence` | Deterministic | 1 per corpus | Serial | Boundary-level wall time (commissioning scripts) | N/A | N/A | Yes |
| Stage A | `extract_document_facts` → `_extract_chunk_facts` (`extractor.py:2857,2788`) | **LLM** — `claude-haiku-4-5-20251001` | 16 document-level calls to `extract_document_facts`; internal per-chunk API call count not separately recorded | Serial (chunks within a doc, docs within a package) | Aggregate stage-level only (2245.556s for all 16 docs) | **Now added** (this report), not yet exercised | Bounded recovery cascade exists in code; count not persisted per document | Per-document record counts + recovery status (yes); per-call timing/tokens (no, until now) |
| Stage B/C | `normalize_package_facts`, `reconcile_package_facts` | Deterministic | 1 each | Serial | Sub-second, not independently isolated for this baseline | N/A | N/A | Folded into Stage C commissioning reports |
| Canonical Opportunity (ledger) | `build_canonical_opportunity`/`resolve_canonical_opportunity` | Deterministic | 1 | Serial | Folded into publication timing below | N/A | N/A | Yes |
| Canonical Opportunity Publication | `publish_canonical_opportunity` via `canonical_observation_binding` | Deterministic | 1 | Serial | **Measured this run** (Section D) | N/A | N/A | Yes |
| Opportunity Structure (ledger) + Publication | `build_opportunity_structure`, `publish_opportunity_structure` | Deterministic | 1 each | Serial | **Measured this run** | N/A | N/A | Yes |
| Opportunity Intelligence + Publication | `analyze_opportunity`, `publish_opportunity_intelligence` | Deterministic | 1 each | Serial | **Measured this run** | N/A | N/A | Yes |
| EOU / EOB | `build_executive_opportunity_understanding`, `build_executive_opportunity_brief` | Deterministic | 1 each | Serial | **Measured this run** | N/A | N/A | Yes |
| Buyer Brief chain | `analyze_buyer`, `build_buyer_brief` | Deterministic | 1 each | Serial | **Measured this run** | N/A | N/A | Yes |
| Executive Briefing Pack | `build_executive_briefing_pack` | Deterministic | 1 | Serial | **Measured this run** | N/A | N/A | Yes |
| Stage D | `synthesize_bid_brief` → `_synthesize_projected_bid_brief` (`extractor.py`, `stage_d_projection.py`) | **LLM** — `claude-haiku-4-5-20251001` | 1 call, ≤2 internal attempts | Serial, genuinely sequential after B/C; **not invoked anywhere in the EOB→Pack chain** | Measured (one PASS run, one diagnostic rerun) | **Already existed** (added in a prior audit) | 2-attempt bounded loop; SDK retries explicitly disabled | Yes, full checkpoint bundle for the diagnostic rerun |

**Correction to a possible assumption:** commissioning order (Phase 1 → Phase 2 → … → Executive Briefing Pack) is **not** the runtime dependency graph. Stage D is genuinely independent of the EOB→Pack path — confirmed architecturally decoupled (zero references) in `BANK_OF_CANADA_STAGE_D_NARRATIVE_COMPLETENESS_AUDIT.md`. It is included here only because the user's instructions require covering "Stage D wherever invoked," not because it gates Executive Briefing Pack.

---

## C. Total runtime / cost / tokens

**No single, coherently-timed, end-to-end run of Stage A → Stage D → the deterministic chain exists in this project's history.** Stage A's only measured run against the current 16-document corpus predates the Stage B/C hardening and both remediations (it was never rerun — nothing downstream required it to be). Stage D's only measured runs (one PASS, one token-instrumented diagnostic) used an intermediate, now-superseded Stage B/C snapshot, and Stage D is not part of the EOB→Pack chain at all. The deterministic chain below was freshly, fully re-measured against the **current, frozen, authoritative lineage** as part of this baseline (zero LLM calls, $0).

| Component | Wall time | Lineage | Measured/estimate |
|---|---:|---|---|
| Stage A (16 documents, one-time) | **2245.556 s** (~37.4 min) | Current authoritative corpus, frozen at Phase 1 | MEASURED |
| Stage D, authoritative PASS run | 28.394 s | Superseded intermediate Stage B/C | MEASURED |
| Stage D, token-instrumented diagnostic rerun | 48.638 s | Same superseded snapshot | MEASURED |
| Deterministic chain (Evidence → Pack) | **97.630 s** | **Current frozen authoritative lineage** | MEASURED (this baseline) |
| **Approximate combined total** (NOT one coherent run) | **~2371.58 s (~39.5 min)** | Mixed — see above | Sum of non-contemporaneous MEASURED figures |

- **Total LLM calls:** Stage A internal per-chunk call count **UNAVAILABLE** (never recorded; ≥16, plausibly higher per document chunking — see Section E); Stage D: 1 production call (≤2 internal attempts) + 1 diagnostic call (2 internal attempts, both captured).
- **Total input tokens:** Stage A **UNAVAILABLE** (no telemetry existed when it ran). Stage D: 146,601 + 146,624 = **293,225** input tokens measured (diagnostic rerun only, both attempts).
- **Total output tokens:** Stage A **UNAVAILABLE**. Stage D: 1,411 + 1,535 = **2,946** output tokens measured.
- **Total API cost: UNAVAILABLE.** No authoritative per-token pricing is encoded anywhere in this repository (confirmed in `PRODUCTION_ECONOMICS_AUDIT.md`, itself pre-existing). Reporting a dollar figure here would require inventing a price assumption; per the task's own instruction, this baseline does not do that.
- **Total retries:** Stage A — bounded recovery fired on 4/16 documents (`RECOVERED_TRUNCATED`), retry-call counts not separately persisted. Stage D — 1 of 2 internal attempts used on the diagnostic rerun (both failed); the authoritative PASS run's attempt count is not separately recorded (only final `status: PASS`).
- **Total artifact bytes generated:** Evidence Publication 150 objects; Canonical Opportunity Publication 134 objects; Opportunity Structure Publication 696 objects; Opportunity Intelligence Publication 33 objects; Executive Briefing Pack 2 members. Byte-level artifact sizes are addressed in Section J.

---

## D. Stage-by-stage timing (deterministic chain, freshly measured this baseline)

Run `briefingpack-boc-2026-026-20260912T184942Z-f775ca`, current frozen authoritative lineage, zero LLM calls:

| Stage | Wall seconds | Output |
|---|---:|---|
| Evidence (real corpus, deterministic parse) | 2.467 | 150 objects |
| Canonical Opportunity Publication | 0.327 | 134 objects |
| Opportunity Structure Publication | 2.995 | 696 objects |
| Opportunity Intelligence | 0.195 | 817 evidence_used, 8 unresolved_conflict_ids |
| Opportunity Intelligence Support Binding Derivation | 0.577 | 817 bindings |
| Opportunity Intelligence Publication | 15.105 | 33 objects |
| Executive Opportunity Understanding | 19.062 | 13 index sections, 33 coverage records |
| Executive Opportunity Brief | 55.894 | 13 sections (includes an internal double-build determinism check — see Section Q) |
| Buyer Evidence / Canonical Buyer (no new fetch) | 0.000 | 1 source, 1 document |
| Buyer Intelligence Analysis | 0.003 | 4 buyer facts |
| Buyer Brief | 0.003 | — |
| Executive Briefing Pack (composition) | 1.002 | 2 members |
| **Total** | **97.630** | — |

---

## E. Stage A document-level performance

Sortable table (from `phase1_document_parsing.json` / `phase1_stage_a_report.json`,
run `phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5`):

| # | Document | Type | Bytes | Parsed chars | Stage A records | Recovery status | Input tokens | Output tokens | LLM sec | Total sec | Retries | Cost |
|--:|---|---|--:|--:|--:|---|--:|--:|--:|--:|--:|--:|
| 1 | abstract.pdf | PDF | 119,394 | 7,733 | 76 | **RECOVERED_TRUNCATED** | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL |
| 2 | Amendment1/…D2 REVISED.docx | DOCX | 50,745 | 5,323 | 22 | VERIFIED_ADEQUATE | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL |
| 3 | …Annexe F ESG.xlsx | XLSX | 28,985 | 2,077 | 3 | VERIFIED_ADEQUATE | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL |
| 4 | …Appendix A Submission Form.docx | DOCX | 48,269 | 6,505 | 18 | VERIFIED_ADEQUATE | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL |
| 5 | …Appendix B1 Mandatory criteria.xlsx | XLSX | 14,247 | 1,161 | 15 | VERIFIED_ADEQUATE | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL |
| 6 | …Appendix B2 Mandatory criteria.xlsx | XLSX | 13,999 | 757 | 9 | VERIFIED_ADEQUATE | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL |
| 7 | …Appendix B3 Mandatory criteria.xlsx | XLSX | 14,240 | 1,144 | 15 | VERIFIED_ADEQUATE | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL |
| 8 | …Appendix C1 Min. qual. requirements.xlsx | XLSX | 14,007 | 962 | 8 | VERIFIED_ADEQUATE | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL |
| 9 | …Appendix C2 Min. qual. requirements.xlsx | XLSX | 14,104 | 1,108 | 10 | VERIFIED_ADEQUATE | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL |
| 10 | …Appendix C3 Min. qual. requirement.xlsx | XLSX | 13,965 | 865 | 9 | VERIFIED_ADEQUATE | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL |
| 11 | …Appendix D1 Rated criteria response form.docx | DOCX | 58,679 | 6,159 | 73 | **RECOVERED_TRUNCATED** | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL |
| 12 | …Appendix D2 Rated Criteria Response Form.docx | DOCX | 55,852 | 5,326 | 23 | VERIFIED_ADEQUATE | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL |
| 13 | …Appendix D3 Rated Criteria Response Form.docx | DOCX | 52,110 | 4,648 | 24 | VERIFIED_ADEQUATE | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL |
| 14 | …Appendix E Pricing Form.xlsx | XLSX | 44,836 | 18,457 | 76 | VERIFIED_ADEQUATE | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL |
| 15 | …Appendix G Form of Agreement.docx | DOCX | 67,727 | 32,452 | 247 | **RECOVERED_TRUNCATED** | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL |
| 16 | RFP 2026-026 — Talent, Learning… .pdf | PDF | 376,615 | 52,145 | 288 | **RECOVERED_TRUNCATED** | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL | UNAVAIL |
| **Total** | | | **987,774** | **146,822** | **916** | 4/16 recovered | — | — | — | 2245.556 s (aggregate, all 16) | — | UNAVAIL |

**Per-document time/tokens/cost/retries are genuinely UNAVAILABLE** — this run predates any token/latency instrumentation existing anywhere in Stage A's code path (confirmed: `PRODUCTION_ECONOMICS_AUDIT.md` §Executive Summary Finding 4, and by direct code reading before this baseline's instrumentation was added — see Section Q/instrumentation). Re-deriving them requires a live rerun, which this measurement-only baseline does not perform.

**Calculated from what IS measured:**
- **Fastest/slowest document (by time): UNAVAILABLE.**
- **Highest-token document: UNAVAILABLE.**
- **Highest record-count document:** the main RFP PDF (doc 16), 288 records.
- **Highest parsed-character document:** the main RFP PDF (doc 16), 52,145 chars.
- **Lowest parsed-character document:** Appendix B2 (doc 6), 757 chars.
- **Tokens per parsed character: UNAVAILABLE** (no token counts exist).
- **Time per Stage A record (aggregate only, not per-document):** 2245.556 s ÷ 916 records ≈ **2.4514 s/record**, computed across all 16 documents combined — not a per-document figure.

---

## F. Stage A retries/recovery

4 of 16 documents (25%) show `RECOVERED_TRUNCATED`: `abstract.pdf`, Appendix D1, Appendix G, and the main RFP PDF. Per the boundary summary, `documents_with_warnings: 4`, `zero_output_documents: 0` — every document eventually produced output; none failed outright.

**Call sequence per document: UNAVAILABLE at the granularity requested.** The code path (`extract_document_facts`, `extractor.py:2857`) is read and confirmed to support: exactly 1 chunk call for a small document with no recovery trigger; N chunk calls for a larger document (marker-aware chunking, `chunk_document_text`); up to 2 additional sub-chunk recovery calls per triggering chunk on `RECOVERED_TRUNCATED`/`FAILED`; up to 2 whole-document coverage-guard recovery passes if the aggregated result is still suspicious. **None of this was ever counted per document by the run that produced the current corpus's Stage A data** — the persisted artifact records only the final `RECOVERED_TRUNCATED`/`VERIFIED_ADEQUATE` status, not how many calls that status took to reach.

- **Initial call tokens/time:** UNAVAILABLE.
- **Recovery call tokens/time:** UNAVAILABLE.
- **Recovered record count:** included in the `total_records` figures above (not separately broken out pre/post-recovery in the persisted artifact).
- **% of document runtime in recovery:** UNAVAILABLE.

No fixes were made; this section documents a measurement gap, not a defect.

---

## G. Stage D telemetry

Two real data points exist, both against a **superseded** intermediate Stage B/C snapshot (`phase2-boc-2026-026-stageb-20260912T125051Z-91a22b` / `phase3-boc-2026-026-stagec-20260912T130007Z-dd391b`), not the current frozen lineage. Stage D was not rerun for this baseline (it is architecturally decoupled from the EOB→Pack chain, and rerunning it would cost real tokens for a stage that does not gate the frozen pack).

| | Authoritative PASS run (`phase4-boc-2026-026-staged-20260912T131303Z-2cc8af`) | Diagnostic rerun (`phase4-narrative-diag-boc-2026-026-20260912T133437Z-2a74e2`) |
|---|---|---|
| Status | PASS | FAIL (both internal attempts rejected, `UNKNOWN_EVIDENCE_SELECTOR`) |
| Wall time | 28.394 s | 48.638 s |
| Model | `claude-haiku-4-5-20251001` | same |
| Temperature | not set (provider default) | same |
| Attempt 1 input/output tokens | UNAVAILABLE (token capture did not exist yet) | **146,601 / 1,411** |
| Attempt 2 input/output tokens | n/a (PASS on attempt 1, or not recorded which attempt) | **146,624 / 1,535** |
| Stop reason | UNAVAILABLE | `end_turn` (both attempts) |
| Retry count | UNAVAILABLE (≤2 by contract) | 1 (both of the 2-attempt budget consumed) |
| Validation outcome | PASS | FAILED / `UNKNOWN_EVIDENCE_SELECTOR` (both attempts) |
| Evidence-selector failures | n/a | Attempt 1: 1 bad citation (empty owner catalog); Attempt 2: 4 bad citations (out-of-range selectors) |
| Cost | UNAVAILABLE | UNAVAILABLE (no authoritative pricing) |
| Request payload bytes | UNAVAILABLE (not persisted by either run) | UNAVAILABLE |

**Request payload bytes are genuinely unrecorded for both runs** — `_STAGE_D_CONTEXT_CHAR_LIMIT = 580,000` chars is the code's own guard ceiling, and a separately-measured corrected-corpus context size of 559,401 chars is cited in `PRODUCTION_ECONOMICS_AUDIT.md` for a **different** corrected-corpus attempt (not either run cited here) — reusing that figure for these two specific runs would misattribute a measurement to a run that didn't record it, so it is not repeated here as if it were this run's own number.

---

## H. Stage D payload composition

Real record counts per logical component, from `upstream_downstream_accounting.json`
(same superseded-lineage authoritative PASS run — record counts, unlike bytes/tokens,
are structurally tied to the Stage B/C snapshot content, which the diagnostic rerun
reused unchanged):

| Payload component | Records | Bytes | % of request |
|---|--:|--:|--:|
| Requirements | 427 | UNAVAILABLE | UNAVAILABLE |
| Evaluation criteria | 83 | UNAVAILABLE | UNAVAILABLE |
| Submission rules | 68 | UNAVAILABLE | UNAVAILABLE |
| Deliverables | 23 | UNAVAILABLE | UNAVAILABLE |
| Commercial clauses | 91 | UNAVAILABLE | UNAVAILABLE |
| Dates | 23 | UNAVAILABLE | UNAVAILABLE |
| Canonical observations | 120 | UNAVAILABLE | UNAVAILABLE |
| Conflicts | 7 | UNAVAILABLE | UNAVAILABLE |
| Instructions/schema (`SYNTHESIS_PROMPT` + `stage_d_output_config`) | n/a | UNAVAILABLE | UNAVAILABLE |

Byte-level and token-level breakdowns per component were never captured — only
record *counts* per component exist in the persisted artifact
(`upstream_downstream_accounting.json`). Deriving per-component byte/token shares
would require re-serializing the exact request, which risks drifting from what
was actually sent unless done as a genuine, faithful replay — not attempted here
per the "do not change Stage A/D behavior" constraint and to avoid inventing
figures. Nothing was trimmed or removed.

---

## I. Deterministic stages

All measured in the same freeze-time replay (Section D); repeated here per the
requested minimum list:

| Stage | Runtime | Input records | Output objects | Output bytes |
|---|--:|--:|--:|--:|
| Evidence adapter/publication | 2.467 s | 16 documents | 150 | UNAVAILABLE (not separately measured) |
| Stage B | not isolated this run | — | — | — |
| Stage C | not isolated this run | — | — | — |
| Canonical Opportunity (ledger) | folded into publication below | 120 observations | — | — |
| Canonical Opportunity Publication | 0.327 s | 120 observations | 134 | UNAVAILABLE |
| Opportunity Structure (ledger) | folded into publication below | — | — | — |
| Opportunity Structure Publication | 2.995 s | — | 696 | UNAVAILABLE |
| Opportunity Intelligence | 0.195 s | — | 817 evidence_used | UNAVAILABLE |
| Support binding | 0.577 s | 817 | 817 bindings | UNAVAILABLE |
| Opportunity Intelligence Publication | 15.105 s | — | 33 | UNAVAILABLE |
| EOU | 19.062 s | — | 13 index sections, 33 coverage records | UNAVAILABLE |
| EOB | 55.894 s | — | 13 sections | UNAVAILABLE |
| Buyer Brief chain | 0.006 s combined | — | — | UNAVAILABLE |
| Executive Briefing Pack | 1.002 s | 2 members | 1 pack | 1 manifest |

Output byte sizes were not independently measured per stage for this baseline
(Section J covers whole-artifact serialization/disk figures where they do exist).

---

## J. Serialization / I/O

- The evaluation/ commissioning-artifact tree at freeze time totals **154 MB across 374 files** (measured directly during baseline-freeze commissioning, `du -sh evaluation`).
- JSON serialization time and artifact write time specifically were **not isolated** from the boundary-level wall-clock figures above (each boundary's elapsed_seconds includes any `save()`/`checkpoint.write()` calls within it, not separated out).
- Largest single persisted artifact observed: the Stage A per-document extraction JSONs (16 files under `phase1_commissioning/.../stage_a_documents/`, the ones whose long paths required enabling `core.longpaths` during baseline freeze — individually a few hundred KB each based on typical fact-record volume, not byte-measured here).
- **I/O materiality relative to model latency:** structurally negligible for Stage A/D specifically — a 154 MB commissioning-artifact tree accumulated across dozens of runs is orders of magnitude smaller than the wall-clock cost of Stage A's 2245.556 s of live model calls. I/O is not a plausible optimization target by this evidence; it was not measured more granularly because nothing here suggests it would change that conclusion.

---

## K. Concurrency observations

**Confirmed serial, end to end.** Repository-wide search (repeated for this
baseline; matches `PRODUCTION_ECONOMICS_AUDIT.md`'s own prior finding) for
`asyncio`, `ThreadPoolExecutor`, `concurrent.futures`, `async def`, `await`
in `extractor.py` returns zero matches. Every chunk call within a Stage A
document, every document within the 16-document package, and both Stage D
attempts execute strictly one after another, blocking on
`client.messages.create`.

- **Observed maximum concurrent calls:** 1 (no concurrency exists to observe).
- **Average concurrency:** 1.
- **Idle gaps between calls:** not separately measured (would require per-call
  timestamps, which — per Section E/F — were never captured for the run this
  baseline reads from).

This is measurement/confirmation only; concurrency was not changed.

---

## L. Retry / failure tax

| Stage | Original calls | Retry calls | Success-first-attempt % | Time lost to retries | Tokens lost to retries | Cost lost to retries |
|---|--:|--:|--:|--:|--:|--:|
| Stage A | UNAVAILABLE (per-chunk count not recorded) | UNAVAILABLE | UNAVAILABLE — 12/16 documents (75%) needed **no** document-level recovery (`VERIFIED_ADEQUATE` on the first pass); 4/16 (25%) needed at least one recovery cascade | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE |
| Stage D (diagnostic rerun) | 1 | 1 | 0% (0 of 2 attempts on the diagnostic rerun passed validation) | The 2nd attempt cost the full 146,624-input-token request again — effectively **all** of the diagnostic rerun's 48.638 s and 293,225 combined input tokens is "retry tax" in the sense that neither attempt produced a usable result | 293,225 input / 2,946 output tokens spent, zero usable brief produced | UNAVAILABLE (no pricing) |
| Stage D (authoritative PASS run) | ≤2 by contract | UNAVAILABLE (not recorded which attempt passed) | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE |

**Retry category separation** (per code reading, not this run's own telemetry, since none exists at this granularity): Stage A relies on the Anthropic SDK's default client-level retry policy (unmodified) *plus* its own bounded coverage-guard/sub-chunk recovery (application-level, up to 2+2 extra passes). Stage D explicitly disables SDK retries (`with_options(max_retries=0)`) and owns a single bounded 2-attempt application-level loop with no parser-level recovery distinct from validation failure. No retry policy was altered by this baseline.

---

## M. Wall-time critical path

**Full cross-stage ranking is dominated overwhelmingly by Stage A** (2245.556 s
of the ~2371.58 s approximate combined total — **~94.7%**), consistent with
`PRODUCTION_ECONOMICS_AUDIT.md`'s own prior finding (81% on an earlier,
smaller 15-document run). Stage D contributes ~1.2–2.1% (28.4–48.6 s), and
the fully-deterministic chain contributes ~4.1% (97.63 s).

Deterministic-chain-only ranking (Section D data, since this is the one
component measured fresh, coherently, in one run — useful because Stage A/D
are explicitly out of scope for any near-term change):

| Rank | Stage/call | Wall time | % of deterministic total | Cumulative % |
|--:|---|--:|--:|--:|
| 1 | Executive Opportunity Brief | 55.894 s | 57.25% | 57.25% |
| 2 | Executive Opportunity Understanding | 19.062 s | 19.52% | 76.78% |
| 3 | Opportunity Intelligence Publication | 15.105 s | 15.47% | 92.25% |
| 4 | Opportunity Structure Publication | 2.995 s | 3.07% | 95.31% |
| 5 | Evidence (parse) | 2.467 s | 2.53% | 97.84% |
| 6 | Executive Briefing Pack (composition) | 1.002 s | 1.03% | 98.87% |
| 7 | Support Binding Derivation | 0.577 s | 0.59% | 99.46% |
| 8 | Canonical Opportunity Publication | 0.327 s | 0.33% | 99.79% |
| 9 | Opportunity Intelligence | 0.195 s | 0.20% | 99.99% |
| 10–12 | Buyer Brief chain (3 steps) | 0.006 s combined | ~0.01% | 100.00% |

**Top 50%:** rank 1 alone (Executive Opportunity Brief, 57.25%) exceeds 50%.
**Top 80%:** ranks 1–2 (76.78%). **Top 95%:** ranks 1–5 (97.84%).

Note: the "Executive Opportunity Brief" figure includes this commissioning
script's own internal double-build determinism check
(`build_executive_opportunity_brief` called twice to prove replay stability)
— the single-build cost is plausibly closer to half this figure, but the
script does not separately time each call.

---

## N. Token critical path

- **Stage A:** UNAVAILABLE per-document; the highest-*record*-count document
  (main RFP PDF, 288 records / 52,145 chars) is the most plausible token
  leader by proxy, but this is a proxy, not a measurement.
- **Stage D:** 100% of measured input tokens (293,225 of 293,225 total
  measured across both stages) — Stage D's single large-context call
  dominates token consumption by construction, exactly as
  `PRODUCTION_ECONOMICS_AUDIT.md` already found architecturally (its
  authoritative-section context is re-serialized every attempt).
- **Retry share (tokens):** on the diagnostic rerun, retry (attempt 2) alone
  cost 146,624 of the 293,225 total measured input tokens — **50.0%** of all
  measured input tokens in this report were spent on a single retry attempt
  that failed validation.

| Rank | Stage/call | Input tokens | Output tokens | % of total measured input tokens |
|--:|---|--:|--:|--:|
| 1 | Stage D diagnostic attempt 2 (retry) | 146,624 | 1,535 | 50.01% |
| 2 | Stage D diagnostic attempt 1 | 146,601 | 1,411 | 49.99% |
| — | Stage A (all 16 documents, all chunks) | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE (excluded from the 100% base above since it cannot be measured) |

---

## O. Cost critical path

**Not rankable in dollars — no authoritative pricing exists in this repository
(Section C).** By token volume alone (the only proxy available), Stage D's
two diagnostic-rerun attempts would rank 1 and 2, and Stage A would rank an
unknown but plausibly comparable-or-larger position by call *count* (per
`PRODUCTION_ECONOMICS_AUDIT.md`'s own directional finding that Stage A's
cost is driven by many calls, not one call's size). No cost figures are
fabricated to fill this table.

---

## P. Correctness invariance

```
py_compile extractor.py tests/test_stage_a_extraction_reliability.py   -> COMPILE_OK
git diff --check                                                        -> clean
pytest tests/test_stage_a_extraction_reliability.py                     -> 31 passed
pytest (full repository suite)                                          -> 1249 passed, 2 skipped
```

Deterministic downstream replay (run `briefingpack-boc-2026-026-20260912T184942Z-f775ca`):

| | Before instrumentation | After instrumentation |
|---|---|---|
| Pack ID | `pack-b11fe92992b988d51edba6077dc7f1999d864838a7e01acd7e332b3b3faeb600` | `pack-b11fe92992b988d51edba6077dc7f1999d864838a7e01acd7e332b3b3faeb600` |
| Pack revision | `pack-revision-8b3b21c79dd82605e7ea70ad5d622905aae826dddd1ce4b343fdb4ad8e945ebe` | `pack-revision-8b3b21c79dd82605e7ea70ad5d622905aae826dddd1ce4b343fdb4ad8e945ebe` |
| Pack digest | `pack-digest-1b119bfe385002e2505b416ece164f5b8c4b28c60dda8d8c726dc4542519f943` | `pack-digest-1b119bfe385002e2505b416ece164f5b8c4b28c60dda8d8c726dc4542519f943` |

**Identical.** Instrumentation added (`extractor.py`: `telemetry: list | None
= None` optional parameter on `extract_document_facts`/`_extract_chunk_facts`,
mirroring the pre-existing Stage D `response.usage`-capture pattern) is
confirmed additive and behaviorally inert: default `None` for every existing
caller, no new key in the returned facts dict, no disk I/O, no new
dependency, and never exercised in this baseline (no new LLM calls were
made).

---

## Q. Optimization candidates (identification only — nothing implemented)

Ranked by measured evidence available in this report and the pre-existing
`PRODUCTION_ECONOMICS_AUDIT.md` (which independently arrived at overlapping
conclusions from source-code reading):

| Candidate | Latency impact | Token impact | Cost impact | Correctness risk | Implementation complexity | Label |
|---|---|---|---|---|---|---|
| Add token/latency telemetry to Stage A live (exercise the instrumentation added by this baseline on a real, authorized rerun) | None (measurement only) | None | Cost of one authorized rerun | None — already proven inert | Low (already implemented) | **HIGH BENEFIT / LOW RISK** — precondition for measuring every other Stage A candidate below with real numbers instead of proxies |
| Stage D authoritative-section context redundancy (same facts serialized into the prompt that the model is told not to reproduce) | Directly reduces the dominant per-call token cost (Stage D is ~50–100% of all measured tokens in this report) | High — this is the single largest identified token-reduction opportunity by the pre-existing audit's own architecture reading | High, proportional to token reduction | **Elevated** — touches Stage D's context construction, which the fail-closed evidence-ownership validator depends on; the diagnostic rerun in this report shows that validator already fails closed on legitimate model output under current conditions | Medium–high | **HIGH BENEFIT / MEDIUM RISK** |
| Stage A fixed-prompt resend (14,728-char static instruction block resent unchanged on every chunk call, per prior audit's direct source measurement) | Scales with chunk count; not independently re-measured here | High — repeated identical input on every one of an unknown-but-plausibly-large number of Stage A calls | Proportional | Low — touches no schema, prompt content, or validation logic, only resend mechanics | Low | **HIGH BENEFIT / LOW RISK** (per the prior audit; not independently re-verified with fresh token telemetry in this report) |
| Stage D single retry re-sending 100% of context for a short correction | Halves Stage D's worst-case latency when a retry is needed | Halves Stage D's worst-case token spend when a retry is needed (measured: 50.0% of this report's total measured input tokens was one retry attempt) | Proportional, and directly measured in this report (not just estimated) | Elevated for the same reason as the context-redundancy candidate | Medium | **HIGH BENEFIT / MEDIUM RISK** |
| Deterministic-chain hotspots: Executive Opportunity Brief / Understanding / Opportunity Intelligence Publication (92.25% of deterministic wall time combined, Section M) | Meaningful within the deterministic chain (~90 s of ~97.6 s), but tiny relative to Stage A's ~2245 s | None (no LLM involved) | None (no LLM involved) | **Low** — pure Python, no evidence/provenance/validator logic touched by definition of "deterministic" | Unknown without profiling (not attempted here — measurement only) | **LOW–MEDIUM BENEFIT / LOW RISK** — worth a future profiling pass since it's the only category here with zero correctness risk by construction |
| Stage A concurrency (chunk-level and document-level calls are structurally independent, per prior audit's dependency analysis) | Potentially large (Stage A is ~94.7% of total wall time) | None (same total tokens, redistributed in time) | None | **Elevated** — touches shared-client and any future checkpoint-write ordering | Medium–high | **HIGH BENEFIT / MEDIUM RISK** |
| Caching | Unknown — no cache-hit-rate data exists (Stage A is temperature=0.0, deterministic given identical input, but no memoization exists in the code path per the prior audit) | Potentially high if repeat/near-duplicate documents recur across packages | Potentially high | Low if implemented as pure addition (e.g. content-hash lookup) | Medium | **LOW BENEFIT (unverified) / LOW RISK** — not enough evidence in this corpus (16 distinct documents, no repeats) to rank confidently; flagged as unverified rather than assumed |

**Categories explicitly not ranked** (no measured evidence in this report to support a ranking, only the pre-existing audit's source-level reasoning): Stage A document chunking strategy change, Stage D deterministic projection/call elimination. Both are plausible per prior architectural reading but require Stage A/D-level telemetry (now instrumentable, not yet exercised) before ranking them with confidence rather than speculation.

---

## Future optimization comparison set (per explicit instruction — do not use the pack digest as the only future check)

**Semantic invariants** — must remain byte-identical (or, where noted, digest-identical) across any future optimization experiment for it to be considered non-regressive:

- Stage A semantic outputs: the typed fact records themselves (`requirements`, `dates`, `evaluation_criteria`, `submission_rules`, `deliverables`, `commercial_clauses`, `contract_risks`, `typed_observations`) — their *content*, not the wall-clock/token cost of producing them.
- Stage B normalized outputs: `normalize_package_facts`'s deduplicated, source_refs-aggregated result.
- Stage C governed conflicts: both populations (governed `conf_<hash>` and Stage-C-local advisory `CONF-*`) and their exact identities, per the conflict-identity remediation's own established contract.
- Canonical Opportunity: `input_digest`, `observations`, `conflicts`, `resolved` — the full ledger content and its own hash-based identities.
- Opportunity Structure: `records`, `conflicts`, `input_digest`.
- Opportunity Intelligence: `evidence_used`, `unknowns.unresolved_conflict_ids`, `computed_facts`, `inferences`.
- EOB semantic content: `brief_id`, `sections`, `detail_register`, `coverage_ledger` — i.e. `to_json()` byte-identity, exactly as already verified in this and the prior EOB/pack commissioning reports.
- Buyer Brief semantic content: `brief_id`, facts, evidence register.
- Final pack members: `pack_id`, `pack_revision_id`, `pack_digest`, and each member's `artifact_digest` in the manifest.

**Execution metadata** — may legitimately differ under a future optimization experiment without indicating a regression:

- Wall-clock time at any granularity (this entire report).
- Token counts, model latency, retry counts, stop reasons.
- Concurrency/parallelism shape (number of simultaneous calls, ordering of independent calls).
- Checkpoint/telemetry artifact contents (the `telemetry` list added by this baseline; Stage D's existing `response.json` checkpoint fields).
- API cost.
- Intermediate serialization/disk I/O timing.
- Anything already excluded from pack identity per `EXECUTIVE_BRIEFING_PACK_ARCHITECTURE.md` §7.1/§7.3 (execution time, output filename, storage location, renderer, generation host, operator).

**The rule going forward:** a future optimization experiment is non-regressive only if every item in the semantic-invariants list is byte-identical (or digest-identical, for hash-identified objects) to this baseline's own values, **regardless of** whether any execution-metadata value changed. The pack digest alone is necessary but not sufficient — it does not, by itself, prove every upstream semantic invariant above it was preserved (it proves composition-layer identity, not upstream ledger/observation-level identity); a full optimization-comparison run should check the full list, not the pack digest in isolation.

---

## FINAL RESPONSE

- **OBSERVABILITY INSTRUMENTATION: PASS**
- **CORRECTNESS INVARIANCE: PASS**
- **PERFORMANCE BASELINE: PASS**
- **Baseline run ID:** deterministic chain `briefingpack-boc-2026-026-20260912T184942Z-f775ca`; Stage A `phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5`; Stage D `phase4-boc-2026-026-staged-20260912T131303Z-2cc8af` (PASS) / `phase4-narrative-diag-boc-2026-026-20260912T133437Z-2a74e2` (diagnostic, token-instrumented)
- **Baseline tag:** `bid-intelligence-rc2`
- **Total wall time:** no single coherent run exists; Stage A 2245.556 s + Stage D 28.394–48.638 s + deterministic chain 97.630 s ≈ **~2371.58 s (~39.5 min) approximate, cross-lineage, non-contemporaneous sum**
- **Total LLM calls:** Stage A UNAVAILABLE (≥16, internal chunk count not recorded); Stage D 1 production call + 1 diagnostic call (2 internal attempts each measured for the diagnostic)
- **Total input tokens:** Stage A UNAVAILABLE; Stage D 293,225 (diagnostic, both attempts, measured)
- **Total output tokens:** Stage A UNAVAILABLE; Stage D 2,946 (diagnostic, both attempts, measured)
- **Total API cost:** UNAVAILABLE — no authoritative pricing in this repository
- **Stage A wall time:** 2245.556 s (16 documents, one-time, current authoritative corpus)
- **Stage A input/output tokens:** UNAVAILABLE
- **Stage A cost:** UNAVAILABLE
- **Stage A slowest document:** UNAVAILABLE (per-document time never captured)
- **Stage A highest-token document:** UNAVAILABLE (proxy only: main RFP PDF, 288 records / 52,145 chars)
- **Stage A retries:** 4 of 16 documents (25%) show `RECOVERED_TRUNCATED`; exact call-level retry count UNAVAILABLE
- **Stage D wall time:** 28.394 s (authoritative PASS run) / 48.638 s (diagnostic rerun) — superseded lineage, not part of EOB→Pack chain
- **Stage D calls:** 1 production + 1 diagnostic (2 internal attempts each)
- **Stage D input/output tokens:** 293,225 / 2,946 (diagnostic rerun, both attempts, measured)
- **Stage D cost:** UNAVAILABLE
- **Stage D request bytes:** UNAVAILABLE (never persisted by either measured run)
- **Stage D largest payload components:** by record count — requirements (427), commercial clauses (91), evaluation criteria (83); byte/token shares UNAVAILABLE
- **Deterministic downstream total runtime:** 97.630 s (Evidence through Executive Briefing Pack, current frozen lineage, freshly measured)
- **Total artifact bytes:** evaluation/ commissioning tree 154 MB / 374 files at freeze time; per-stage output bytes mostly UNAVAILABLE (object counts measured instead)
- **Retry time/token/cost tax:** Stage D diagnostic retry (attempt 2) alone = 146,624 input tokens = 50.0% of all measured input tokens in this report, for zero usable output; Stage A retry tax UNAVAILABLE
- **Top 5 wall-time contributors (deterministic chain):** Executive Opportunity Brief (57.25%), Executive Opportunity Understanding (19.52%), Opportunity Intelligence Publication (15.47%), Opportunity Structure Publication (3.07%), Evidence parse (2.53%) — cumulative 97.84%; across ALL stages, Stage A alone is ~94.7% of the approximate combined total
- **Top 5 token contributors:** Stage D diagnostic attempt 2 (50.01% of measured), Stage D diagnostic attempt 1 (49.99% of measured); Stage A UNAVAILABLE and excluded from this ranking's base
- **Top 5 cost contributors:** UNAVAILABLE — no dollar figures fabricated
- **Observed max concurrency:** 1 (confirmed fully serial, zero concurrency primitives found in `extractor.py`)
- **Final pack identity match:** YES — identical before/after instrumentation
- **Full-suite result:** 1249 passed, 2 skipped, 0 failed
- **Instrumentation files changed:** `extractor.py`, `tests/test_stage_a_extraction_reliability.py`
- **Tests added:** 3 (`test_telemetry_capture_does_not_change_returned_result`, `test_telemetry_tolerates_missing_usage_attribute`, `test_telemetry_default_none_is_a_complete_no_op`)
- **Ranked optimization candidates:** 7, listed in Section Q (2 HIGH BENEFIT/LOW RISK, 3 HIGH BENEFIT/MEDIUM RISK, 1 LOW–MEDIUM BENEFIT/LOW RISK, 1 LOW BENEFIT-unverified/LOW RISK) — none implemented
- **Report path:** `BANK_OF_CANADA_PERFORMANCE_BASELINE_REPORT.md`
- **Raw metrics path:** `evaluation/bank_of_canada_briefing_pack/performance_baseline/PERFORMANCE_BASELINE.json`, `stage_timings.json`, `llm_calls.jsonl`

**Per the standing instruction: STOPPING here. No optimization implemented.**
