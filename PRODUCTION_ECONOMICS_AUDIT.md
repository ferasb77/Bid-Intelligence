# Document Metadata

| Field | Value |
|---|---|
| Document | `PRODUCTION_ECONOMICS_AUDIT.md` |
| Title | Production Economics Audit — Bid Intelligence Pipeline |
| Authority Level | Level 5 — Operational Record |
| Version | 1.0.0 |
| Status | Draft — Audit Only |
| Purpose | Establish, with evidence, where production time and cost are actually spent, before any optimization work begins. |
| Higher Authority | [`GOVERNANCE.md`](GOVERNANCE.md) |
| Governed Documents | None. This is a read-only engineering record; it makes no architectural or product claim. |
| Related Documents | [`STAGE_A_EXTRACTION_RELIABILITY_REPORT.md`](STAGE_A_EXTRACTION_RELIABILITY_REPORT.md), [`STAGE_D_SYNTHESIS_PROJECTION_REPORT.md`](STAGE_D_SYNTHESIS_PROJECTION_REPORT.md), [`BANK_OF_CANADA_REAL_WORLD_ACCEPTANCE_REPORT.md`](BANK_OF_CANADA_REAL_WORLD_ACCEPTANCE_REPORT.md), [`SUBMISSION_ARTIFACT_PROJECTION_REPORT.md`](SUBMISSION_ARTIFACT_PROJECTION_REPORT.md), [`evaluation/bank_of_canada_briefing_pack/CORRECTED_CORPUS_REGENERATION_REPORT.md`](evaluation/bank_of_canada_briefing_pack/CORRECTED_CORPUS_REGENERATION_REPORT.md) |

**Scope discipline.** This document changes no code, prompt, test, or architecture. Every implementation-level claim below cites a `file:line`. Every quantitative claim is labeled either **MEASURED** (recorded in an existing commissioning/acceptance report, cited) or **ESTIMATE** (derived by this audit from source-code constants and character counts, using an explicit, stated token-per-character assumption). No dollar cost figures exist anywhere in this repository's history; every cost figure in this report is therefore an estimate built on published Anthropic list pricing for the model actually in use, `claude-haiku-4-5-20251001`.

---

## Executive Summary

1. **The entire system makes LLM calls from exactly two source files.** `extractor.py` (Stage A fact extraction, Stage D synthesis) and `analyst.py` (nine workspace-assistant functions used by the Check/Decide/Build/Submit pages) are the only files in the repository that construct an Anthropic client or call `.messages.create(...)`. Every other constitutional/evidence/publication module — 24 top-level files including `buyer_intelligence.py`, `canonical_opportunity.py`, `evidence*.py`, `evaluation_hierarchy.py`, `opportunity_orchestration.py`, `governed_reference_resolution.py` — is pure deterministic Python with no provider dependency. **The constitutional architecture itself is computationally free.** All production cost and nearly all production latency live in two call sites.

2. **Stage A dominates wall-clock time; Stage D dominates per-call size and fragility.** On the one full, successful, measured production run (the 15-document Bank of Canada package), Stage A consumed 318.65s of the 395.34s total (81%); Stage D consumed 71.23s (18%); Stages B and C — fully deterministic — consumed 0.01s combined (0.003%) (`BANK_OF_CANADA_REAL_WORLD_ACCEPTANCE_REPORT.md:74-80`, MEASURED). On a larger, denser 8-document/559-requirement package, Stage A alone took 2,929.66s (~48.8 minutes) and Stage D never dispatched at all — it was blocked pre-flight because the serialized context (1,045,967 characters) exceeded the 580,000-character guard by 465,967 characters (`SUBMISSION_ARTIFACT_PROJECTION_REPORT.md:174,181-186`, MEASURED).

3. **The user's stated concern — "large prompt sizes are approaching provider limits" — is confirmed in production, not hypothetical.** `_STAGE_D_CONTEXT_CHAR_LIMIT = 580_000` (`extractor.py:3799`) was sized specifically against Claude Haiku's 200K-token window (`STAGE_D_SYNTHESIS_COMPLETENESS_REPORT.md:50`, MEASURED/documented rationale). On the corpus above, the package's real content exceeded that guard by 80%. On a separately re-run "corrected" 16-document/413-requirement version of the same corpus, the context fit the guard (559,401 of 580,000 chars, 20,599 headroom) but every live Stage D synthesis attempt then **failed closed** on strict citation/evidence-ownership validation (`WRONG_EVIDENCE_OWNER`, `MISSING_POINTER`, `UNCITED_OUTPUT_FIELD`) — meaning full-context (~140K-token) live calls were paid for and produced no usable brief (`evaluation/bank_of_canada_briefing_pack/CORRECTED_CORPUS_REGENERATION_REPORT.md:30-37,87-88`, MEASURED).

4. **There is no token or dollar telemetry anywhere in this repository.** Every existing "measurement" in the ~85 markdown reports is wall-clock seconds or character counts; none of the commissioning scripts (`scripts/commission_bank_of_canada.py`, `scripts/measure_canonical_integration.py`, `scripts/measure_stage_d_projection.py`) record `usage.input_tokens` / `usage.output_tokens` from the API response, and one report states this explicitly: *"Token count is null and measurement method UNAVAILABLE. No chars-to-tokens estimate is presented as fact"* (`STAGE_D_SYNTHESIS_PROJECTION_REPORT.md:166`). This is itself the most consequential finding of this audit: **the organization cannot currently know its own API cost from its own data.** Every cost figure below is this audit's own estimate, clearly labeled, and should be replaced with measured `usage` data before any optimization decision is finalized.

5. **A meaningful share of Stage D's expensive input is explicitly unused by design.** The Stage D prompt instructs the model: *"The seven authoritative sections are rebuilt by code; do not emit them"* (`stage_d_projection.py:1103`). Those seven sections (`qualification_gates`, `evaluation_breakdown`, `submission_requirements`, `key_dates`, `commercial_structure`, `contract_risks`, `deliverables_summary`) are assembled deterministically in `apply_stage_d_authoritative_sections` (`extractor.py:3925`) from the same normalized facts that were also serialized into the up-to-580,000-character prompt context. The model is paying full input-token price to read facts it is contractually forbidden to reproduce, in order to ground a much smaller amount of genuinely generated text (an executive summary, a proposal outline, and light field classification). This is the single largest architectural inefficiency identified in this audit (§ Deterministic Opportunity Analysis).

6. **Retry economics are asymmetric and Stage-D retries are disproportionately expensive.** Stage A relies on the Anthropic SDK's default retry policy (unmodified client) plus its own bounded coverage-guard recovery (up to 2 additional recovery passes, each re-chunking and re-calling) (`extractor.py:2807-2896`, `STAGE_A_EXTRACTION_RELIABILITY_REPORT.md` §3.4). Stage D explicitly disables SDK retries (`with_options(max_retries=0)`, `extractor.py:4224`) and owns a single bounded 2-attempt loop — but because each attempt re-serializes and re-sends the **entire** up-to-580,000-character context (`extractor.py:4203-4229`), a single Stage D retry can cost as much as the original call. This is not hypothetical: it is the exact failure mode observed in the corrected-corpus commissioning run (Finding 3).

---

## Pipeline Diagram

### 1. Production stage map

| Stage | Owner module | Production entry point | Production exit point | Downstream consumers | Calls an LLM? |
|---|---|---|---|---|---|
| Ingestion / preprocessing | `extractor.py` | `unpack_procurement_package`, `extract_document_with_metadata` (`extractor.py:735,706`) | Marker-annotated per-document text | Stage A | No |
| **Stage A — Fact Extraction** | `extractor.py` | `extract_document_facts` (`extractor.py:2800`) → per-chunk `_extract_chunk_facts` (`extractor.py:2752`) | Per-document typed fact JSON | Stage B | **Yes** — `claude-haiku-4-5-20251001`, one call per chunk |
| Stage B — Normalization | `extractor.py` | `normalize_package_facts` (`extractor.py:2933`) | Deduplicated, source_refs-aggregated package facts | Stage C, canonical ledger | No |
| Stage C — Reconciliation | `extractor.py` | `reconcile_package_facts` (`extractor.py:3175`) | Typed conflict records (6 conflict types) | Stage D | No |
| Canonical opportunity ledger | `canonical_opportunity.py` | Populated from Stage A/B typed observations | Resolved executive fields + full observation history | Stage D (authoritative overlay), publication layer | No |
| **Stage D — Executive Bid Brief Synthesis** | `extractor.py` + `stage_d_projection.py` | `synthesize_bid_brief` → `_synthesize_projected_bid_brief` (`extractor.py:4177-4273`) | Validated Bid Brief JSON (bid/brief/outline/risk_assessments + citations) | `_assemble_procurement_result`, app UI, publication layer | **Yes** — `claude-haiku-4-5-20251001`, 1 call, bounded 2-attempt retry |
| Assembly | `extractor.py` | `_assemble_procurement_result` (`extractor.py:4336`) | Final `extract_procurement_package` result tuple | `app.py` UI | No |
| Contract hygiene | `contract_hygiene.py` | Deterministic post-pass over commercial clauses | De-duplicated, hygiene-checked clause set | Stage D authoritative risk section | No |
| Evaluation hierarchy | `evaluation_hierarchy.py` | Deterministic weight/hierarchy calculations | Validated evaluation tree | Publication, UI | No |
| Requirement semantics | `requirement_semantics.py` | Deterministic type resolution helpers | Normalized requirement types | Stage A aggregation, Stage B | No |
| Evidence graph / query / explainability | `evidence.py`, `evidence_graph.py`, `evidence_query.py`, `evidence_explainability.py` | Deterministic graph construction and read-only queries over already-extracted evidence | Queryable evidence graph, human-readable path explanations | UI, publication | No |
| Buyer intelligence / evidence / brief / domain | `buyer_intelligence.py`, `buyer_evidence.py`, `buyer_brief.py`, `buyer_domain.py` | Deterministic contract validation and presentation over supplied buyer evidence | Validated Buyer Intelligence contracts and brief presentation | UI, publication | No |
| Decision analyst / intelligence / workspace | `decision_analyst.py`, `decision_intelligence.py`, `decision_workspace.py` | Deterministic typed contracts (`decision_analyst.py` is a `Protocol`, not an implementation) | Decision workspace presentation objects | UI | No |
| Executive Opportunity Understanding / Brief | `executive_opportunity_understanding.py`, `executive_opportunity_brief.py` | Deterministic org-level projection and presentation adapter over Opportunity Intelligence | Executive-facing brief presentation | UI, publication | No |
| Governed reference resolution | `governed_reference_resolution.py` | Deterministic cross-domain reference resolution/verification | Resolved, verified object references | Orchestration | No |
| Opportunity orchestration / publication | `opportunity_orchestration.py`, `opportunity_intelligence_publication.py`, `canonical_opportunity_publication.py` | Deterministic assembly, digesting, and admission-policy validation of owner publications | Immutable, versioned publication bundles | Downstream owners, UI | No |
| Checkpointing / replay | `stage_d_checkpoints.py` | `checkpoint_run`, `resume_procurement_checkpoint` (`stage_d_checkpoints.py:234-277`) | Persisted per-attempt diagnostics; **can itself re-invoke `extractor.extract_document_facts` and `extractor.synthesize_bid_brief` on resume** (`stage_d_checkpoints.py:264,276`) | Stage A/D re-entry | **Indirectly yes** — see note below |
| Workspace assistant (Check/Decide/Build/Submit) | `analyst.py` | `compliance_review`, `missing_evidence`, `generate_clarification_questions`, `bid_no_bid_score`, `analyze_past_proposal`, `draft_proposal_section`, `submission_readiness_check`, `analyze_addendum`, `analyze_proposal_alignment` (`analyst.py:126-761`) | Free-form assistant JSON per function | Streamlit pages (`pages/stage_check.py`, `pages/stage_decide.py`, `pages/stage_build.py`, `pages/stage_submit.py`, `pages_extra.py`) | **Yes** — `claude-haiku-4-5-20251001`, one call per function invocation (two for `analyze_proposal_alignment`) |

**Note on `stage_d_checkpoints.py`:** most of this module (digesting, replay bundling) is deterministic, but its `resume_procurement_checkpoint` path is a genuine, non-obvious re-entry into the two LLM-calling stages — a resumed run can re-trigger live Stage A/D calls. This is the one place outside `extractor.py`/`analyst.py` where an LLM call can originate, and it was not obvious from module naming alone.

### 2. Execution flow (production package analysis, `app.py` → `extractor.extract_procurement_package`)

```
unpack_procurement_package (ZIP/multi-file intake)
        │
        ▼
extract_document_with_metadata × N documents   (deterministic, sequential, ~0.05–0.75s/pkg measured)
        │
        ▼
┌────────────────────────── STAGE A — sequential, per document ──────────────────────────┐
│  for each document:                                                                      │
│      chunk_document_text(max_chunk_chars=12,000)  →  chunks[1..k]                        │
│      for each chunk (sequential, blocking):                                              │
│          _extract_chunk_facts()  →  1 LLM call, temperature=0.0, max_tokens=8000          │
│          on RECOVERED_TRUNCATED or FAILED: re-chunk smaller, re-call (bounded)            │
│      coverage guard: if suspicious, up to 2 more whole-document recovery passes           │
└───────────────────────────────────────────────────────────────────────────────────────────┘
        │  (MEASURED: 318.65s / 15 docs successful run;  2,929.66s / 8 docs dense run)
        ▼
normalize_package_facts (Stage B, deterministic)         — 0.009s / 0.39s measured
        │
        ▼
reconcile_package_facts (Stage C, deterministic)          — 0.001s / 0.05s measured
        │
        ▼
┌────────────────────────── STAGE D — single request, bounded 2-attempt loop ─────────────┐
│  build_stage_d_synthesis_projection()      (deterministic serialization, up to 580,000    │
│                                              chars of normalized facts + evidence)         │
│  finalize_stage_d_request()                (attaches fixed prompt + JSON output schema)   │
│  guard check: total_chars <= 580,000 ?  — else StageDContextTooLargeError, NO API CALL    │
│  attempt 1: client.messages.create(model=haiku-4.5, max_tokens=8000, SDK retries=0)       │
│      on failure (schema/validation): attempt 2, full context re-sent + short correction   │
│  local strict validation: citations, evidence ownership, authoritative-invariant checks   │
└───────────────────────────────────────────────────────────────────────────────────────────┘
        │  (MEASURED: 71.23s successful run;  BLOCKED pre-dispatch on oversized run;
        │   repeated live FAIL CLOSED on corrected-corpus run)
        ▼
_assemble_procurement_result → final package result → app.py UI
```

**No concurrency exists anywhere in this path.** A repository-wide search for `asyncio`, `ThreadPoolExecutor`, `concurrent.futures`, `async def`, and `await` returns zero matches. Every chunk call within a document, every document within a package, and both Stage D attempts execute strictly one after another, blocking on `client.messages.create`.

---

## LLM Usage Analysis

### 1. Complete invocation inventory

| # | Source | Function | Model | Prompt builder | Fixed prompt size | Structured output | `max_tokens` | Temperature | Retry behavior | Timeout behavior |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `extractor.py:2752` | `_extract_chunk_facts` (Stage A, per chunk) | `claude-haiku-4-5-20251001` | `STAGE_A_FACT_EXTRACTION_PROMPT` (`extractor.py:37`) + raw chunk text | **14,728 chars fixed** (`extractor.py:37-256`, measured directly from source) ≈ **ESTIMATE 3,700–4,900 tokens** depending on chars/token ratio, resent unchanged on every call | None (free-form JSON, parsed with a custom recovery parser `_safe_parse_json_with_status`, `extractor.py:2214`) | 8,000 | **0.0** (explicit) | SDK default (client constructed with no `max_retries` override → Anthropic SDK default, documented as 2 retries w/ backoff) **plus** bespoke bounded recovery: up to 2 sub-chunk retries on `RECOVERED_TRUNCATED`/`FAILED`, plus up to 2 whole-document coverage-guard recovery passes (`extractor.py:2814-2896`) | SDK default (no explicit timeout override found) |
| 2 | `extractor.py:4186` | `_synthesize_projected_bid_brief` (Stage D) | `claude-haiku-4-5-20251001` | `SYNTHESIS_PROMPT` (`stage_d_projection.py:1077`, ~3,200–3,500 chars) + serialized `prompt_context` (up to **580,000 chars total request**, `extractor.py:3799`) | Fixed instructions small (~800–875 tokens ESTIMATE); **variable context dominates** — up to **ESTIMATE ~145,000 tokens** at the guard ceiling | **Yes** — native `output_config` JSON schema (`stage_d_output_config`, `stage_d_projection.py:682-746`), itself serialized into the char budget | 8,000 | **Not set** (defaults to provider default, i.e. not pinned to 0 despite the module's own description as needing "strict authoritative output") | SDK retries **explicitly disabled** (`with_options(max_retries=0)`, `extractor.py:4224`); single hand-rolled loop, bounded to **2 total attempts**, each re-sending the **full context** (`extractor.py:4202-4249`) | SDK default |
| 3 | `analyst.py:126` | `compliance_review` | `claude-haiku-4-5-20251001` | Inline system+user prompt built from full draft text + full requirements list | Variable, scales with draft length | No (regex/heuristic JSON recovery via `_parse_json`, `analyst.py:32`) | 2,048 | Not set (provider default) | None beyond SDK default | SDK default |
| 4 | `analyst.py:164` | `missing_evidence` | same | Full requirements + bid_info | Variable, scales with requirement count | No | 2,048 | Not set | None beyond SDK default | SDK default |
| 5 | `analyst.py:228` | `generate_clarification_questions` | same | Full bid_info + requirements | Variable | No | 4,096 | Not set | None beyond SDK default | SDK default |
| 6 | `analyst.py:297` | `bid_no_bid_score` | same | Full bid_info + requirements | Variable | No | 2,048 | Not set | None beyond SDK default | SDK default |
| 7 | `analyst.py:412` | `analyze_past_proposal` | same | Full past-proposal text + bid context | Variable, scales with proposal length | No | 4,096 | Not set | None beyond SDK default | SDK default |
| 8 | `analyst.py:474` | `draft_proposal_section` | same | Section title + requirements + supporting context, **called once per proposal section** | Variable, repeats per section | No | 3,000 | Not set | None beyond SDK default | SDK default |
| 9 | `analyst.py:524` | `submission_readiness_check` | same | Full bid + requirements + submission state | Variable | No | 2,048 | Not set | None beyond SDK default | SDK default |
| 10 | `analyst.py:588` | `analyze_addendum` | same | New addendum text + existing requirements | Variable, scales with requirement register size | No | 4,096 | Not set | None beyond SDK default | SDK default |
| 11 | `analyst.py:653` | `analyze_proposal_alignment` | same | **Two sequential calls**: call 1 (3,500 max_tokens) then conditionally call 2 (3,000 max_tokens) | Variable, both calls carry large shared context | 3,500 then 3,000 | Not set | None beyond SDK default | SDK default |

Every LLM-touching function in the entire repository targets a single model: `claude-haiku-4-5-20251001`. There is no model-tiering (e.g., a cheaper/faster model for simple classification vs. a larger model for synthesis) — one model handles Stage A extraction, Stage D synthesis, and all nine assistant workflows.

### 2. Token-consumption classification (by call site, ENGINEERING ESTIMATE)

| Call site | Frequency per package/session | Per-call size class | Aggregate classification |
|---|---|---|---|
| Stage A `_extract_chunk_facts` | 1 per chunk × N chunks (N scales with document count and size; 15–25+ typical, MEASURED range across cited reports) | Medium per call (~5,000–13,000 input tokens ESTIMATE; ≤8,000 output tokens ceiling) | **HIGH** — driven by call *count*, not per-call size |
| Stage D `_synthesize_projected_bid_brief` | 1–2 per package (2 only on retry) | **Very large per call** — up to ~145,000 input tokens ESTIMATE at the guard ceiling; the largest single request class in the system | **HIGH** — driven by per-call *size* |
| `draft_proposal_section` | 1 per proposal section (multiplies with proposal length) | Medium | **MEDIUM**, scales with proposal size |
| `analyze_proposal_alignment` | 2 calls per invocation | Medium-large (full draft + full requirements twice) | **MEDIUM** |
| `compliance_review`, `missing_evidence`, `submission_readiness_check`, `analyze_addendum` | 1 per user action | Medium, scales with draft/requirement size | **MEDIUM** |
| `generate_clarification_questions`, `bid_no_bid_score`, `analyze_past_proposal` | 1 per user action | Small-medium | **LOW–MEDIUM** |

### 3. Semantic value created (per the doctrine's own AI-and-evidence test — `MANIFESTO.md` §"AI and evidence")

| Call site | Classification | Basis |
|---|---|---|
| Stage A fact extraction | **TRANSFORMATION** | Converts unstructured document prose into structured, typed, provenance-linked facts. The prompt explicitly forbids invention (`"DO NOT hallucinate or guess..."`, `extractor.py:47`) — no fact is added beyond what the source states, so this is not "new knowledge," it is a faithful structural transform. This is the one call site whose output cannot plausibly be produced by regex/heuristics alone (free-text requirement/date/clause identification genuinely needs language understanding). |
| Stage D `bid.*` fields (title, client, file_number, deadlines) | **NO NEW SEMANTIC VALUE / FORMATTING** | The prompt requires these fields to "exactly copy matching metadata key's value or be null" (`stage_d_projection.py:1119`) — the model is asked to copy already-known deterministic values verbatim, with citation, rather than compute or infer anything. |
| Stage D `brief.executive_summary`, `brief.notes` | **SUMMARIZATION** | Genuine prose synthesis of already-extracted, already-validated facts into an executive-readable narrative. This is real generative value. |
| Stage D `brief.opportunity_type`, `brief.procurement_model` | **NORMALIZATION / CLASSIFICATION** | Closed-enum classification of the procurement's shape from context. |
| Stage D `outline` (suggested proposal sections) | **TRANSFORMATION** (mildly generative) | The only place Stage D proposes structure not verbatim present in any single source document — combines scope/requirement signals into a suggested table of contents. Explicitly non-binding ("Suggested headings are proposals, never mandatory buyer artifacts," `stage_d_projection.py:1125`). |
| Stage D `risk_assessments` | **VALIDATION (flagging only)** | Model may only emit `REVIEW` or `UNKNOWN` states, never severity or a conclusion (`stage_d_projection.py:1104-1108`) — this is deliberately value-capped by the doctrine (Anti-Goal: no hidden scoring), and correctly so. |
| Stage D's seven "authoritative sections" | **N/A — never emitted by the model** | Explicitly rebuilt by deterministic code (`stage_d_projection.py:1103`); the LLM is instructed not to produce them, yet their source facts are serialized into its input context regardless (see Deterministic Opportunity Analysis). |
| `compliance_review` | **VALIDATION** | Gap analysis: draft vs. requirements. |
| `missing_evidence` | **VALIDATION** | Scans for at-risk/missing proof items. |
| `generate_clarification_questions` | **NEW KNOWLEDGE (interpretive)** | Genuinely generates questions not present in the source — the most "creative" call site in the system besides Stage D's outline. |
| `bid_no_bid_score` | **NEW KNOWLEDGE (interpretive/judgment-shaped)** | See Risk Assessment — this call site's name and function are in tension with `ANTI_GOALS.md`'s "Win probability engine" / "Executive decision maker" exclusions; noted here only as an economics-relevant call site, not adjudicated by this audit. |
| `analyze_past_proposal` | **TRANSFORMATION** | Extracts reusable modular blocks from unstructured historical proposals. |
| `draft_proposal_section` | **NEW KNOWLEDGE (generative drafting)** | Genuinely authors new proposal prose. |
| `submission_readiness_check` | **VALIDATION** | Final gate check. |
| `analyze_addendum` | **TRANSFORMATION + VALIDATION** | Extracts changes and reconciles against existing requirements. |
| `analyze_proposal_alignment` | **VALIDATION** (two-pass audit) | Comprehensive compliance audit, split across two calls. |

**Observation:** the two highest-cost call sites by aggregate token volume (Stage A, Stage D) are also the two most tightly value-justified by the doctrine — Stage A is irreplaceable free-text extraction, and Stage D's genuinely generative surface (summary + outline) is a small fraction of what it's paying to read. The nine `analyst.py` functions are comparatively cheap per-call but are the ones doing the most interpretive/generative work per token — the opposite of where the token budget concentrates.

---

## Latency Analysis

### 1. Measured dominant latency source

| Run | Corpus | Stage A | Stage B | Stage C | Stage D | Total | Source |
|---|---|---|---|---|---|---|---|
| BoC original, successful | 15 docs, 134,617 chars, 98 requirements | **318.65s (81%)** | 0.009s | 0.001s | 71.23s (18%) | **395.34s (6.5 min)** | `BANK_OF_CANADA_REAL_WORLD_ACCEPTANCE_REPORT.md:74-80` |
| 8-doc dense live replay | 8 docs, 279,258 chars, 559 requirements | **2,929.66s (~48.8 min)** | 0.3897s | 0.0529s | **BLOCKED pre-dispatch** (0s — never called) | ≥48.9 min, no brief produced | `SUBMISSION_ARTIFACT_PROJECTION_REPORT.md:170-186` |
| Corrected 16-doc corpus | 16 docs, 413 requirements | PASS (duration not recorded in report) | n/a | n/a | **Multiple live attempts, all FAIL CLOSED** | Not recorded; ≥2 full-context Stage D round-trips paid for, zero usable output | `evaluation/bank_of_canada_briefing_pack/CORRECTED_CORPUS_REGENERATION_REPORT.md:30-37` |

Stage A is the dominant latency source by wall-clock share on every run where a comparison is possible (81% on the clean run; effectively 100% on the run where Stage D never got to dispatch). Stages B and C are immaterial (fully deterministic, sub-40ms combined even on the largest measured run).

### 2. Why Stage A latency is inconsistent and hard to predict

The two measured full-corpus runs show a **9x throughput discrepancy** that is not explained by document-size ratio alone: 134,617 chars took 318.65s (≈422 chars/s), while 279,258 chars took 2,929.66s (≈95 chars/s) — nearly 4.4x slower per character. The most plausible architectural explanations, all visible in code without needing new measurement:

- **The bounded recovery/coverage-guard cascade** (`extractor.py:2814-2896`) can silently multiply the number of live calls for a single document 2–3x when truncation, parse failure, or suspicious under-coverage is detected — and it does so **sequentially**, each recovery pass paying full network+inference latency again.
- **SDK-level retry backoff** on the (unmodified, default-retry) Stage A client adds unbounded-looking wall-clock time under transient provider errors, with no visibility into how often this fired on either run — the reports record only stage-level wall-clock totals, not per-call or per-retry timing.
- Chunk boundaries are marker-aware, not length-uniform (`chunk_document_text`, `extractor.py:2315-2398`), so packages with more or denser structural markers per character can produce more chunks than a naive char-count model predicts — and every extra chunk pays the full 14,728-character fixed-prompt tax on top of its content.

### 3. Synchronous dependencies and sequential bottlenecks

- **Every chunk call within a document is sequential** (`for chunk in chunks:`, `extractor.py:2814`) — there is no dependency between chunks of the *same* document (each is an independent, stateless extraction over disjoint text) that would architecturally require sequencing.
- **Every document within a package is sequential** at the orchestration layer (per Explore-agent finding B: `extractor.py:4300-4316`) — again, no cross-document dependency exists at Stage A; each document's fact extraction is independent until Stage B's aggregation step.
- **Stage D genuinely must be sequential relative to A/B/C** — it consumes the complete normalized+reconciled model as its context, so it cannot start before Stage C completes. This is a real dependency, not an artifact of implementation.
- **The two Stage D attempts are sequential by construction** (`for attempt in (1, 2):`, `extractor.py:4202`) and cannot be parallelized without changing the retry semantics (attempt 2 depends on attempt 1's failure code to build its correction string).
- No `asyncio`, thread pool, or process pool exists anywhere in the repository (confirmed by repository-wide search) — this applies equally to Stage A's independent per-chunk/per-document calls and to the nine independent `analyst.py` functions, none of which have any cross-call dependency that would require sequential execution.

### 4. Opportunities for safe parallelism (identified, not proposed as implementation)

Per the audit's constraint to identify without designing a fix: the following relationships are **structurally independent** in the current code, meaning nothing about their *data dependencies* requires sequential execution — that is an implementation characteristic, not an architectural one:
- Stage A chunk calls within one document (each chunk is independently extracted; aggregation happens after all chunks return).
- Stage A calls across different documents within one package (no document's Stage A extraction reads another document's output).
- The nine `analyst.py` functions relative to each other, when a user session touches more than one workspace stage in the same sitting.

Stage D's single call, and its dependency on Stages A–C completing, are **not** in this category — they are genuinely sequential.

---

## Cost Analysis

### 1. Top 10 computational hotspots (ranked by ENGINEERING JUDGMENT — no per-call token telemetry exists to rank precisely; see Finding 4)

| Rank | Hotspot | Why it dominates | Cost driver type |
|---|---|---|---|
| 1 | Stage D full-context synthesis call (`extractor.py:4225`) | Single largest request in the system by input size — up to ~580,000 chars (~145K tokens ESTIMATE) in one call | Per-call size |
| 2 | Stage A fixed-prompt resend (`extractor.py:2766`) | 14,728-character static instruction block resent unchanged on **every** chunk call; aggregate overhead scales linearly with chunk count | Repeated identical input |
| 3 | Stage A bounded recovery cascade (`extractor.py:2814-2896`) | Can 2–3x the live call count for any document that trips truncation, parse failure, or the coverage guard — directly implicated in the 9x throughput variance observed between measured runs | Retry multiplication |
| 4 | Stage D bounded retry-on-validation-failure (`extractor.py:4202-4249`) | Each retry resends the **entire** context; empirically triggered repeatedly in the corrected-corpus commissioning run with zero successful output | Retry multiplication at maximum per-call size |
| 5 | `analyze_proposal_alignment` (`analyst.py:653`) | Two sequential calls per invocation, each carrying full draft text + full requirements register | Per-invocation call count |
| 6 | `draft_proposal_section` (`analyst.py:474`) | Called once per proposal section — a 20-section proposal issues 20 separate calls, each re-supplying shared requirement/context state | Frequency scaling |
| 7 | Stage A large single-document fan-out (e.g., a >50,000-character source document) | A single oversized document alone can generate 4–5+ chunk calls, each paying the full fixed-prompt tax | Document-size scaling |
| 8 | `compliance_review` / `missing_evidence` (`analyst.py:126,164`) | Full draft text + full requirements register per call, invoked on the Check page | Per-call size |
| 9 | `generate_clarification_questions` / `bid_no_bid_score` (`analyst.py:228,297`) | Full requirement set per call on the Decide page | Per-call size |
| 10 | `analyze_addendum` (`analyst.py:588`) | Reprocesses the full existing requirements register against each new amendment; frequency scales with amendment count per opportunity | Frequency scaling over opportunity lifetime |

### 2. Cost hotspots explicitly ruled out

Every module listed as "No" in the Pipeline Diagram's LLM column carries **zero** marginal API cost, regardless of package size, evidence volume, or requirement count — including the evidence graph, canonical opportunity ledger, buyer intelligence, decision workspace, and all publication/orchestration layers. Whatever their CPU cost (unmeasured, but these are pure Python dict/dataclass operations with no I/O), it is architecturally incapable of being a provider-cost hotspot.

---

## Deterministic Opportunity Analysis

*(Per instructions: locations are identified; no implementation is proposed or recommended.)*

1. **Stage D's authoritative-section context is fully redundant with information already computed deterministically.** The seven "authoritative sections" are explicitly rebuilt by code and the model is told not to emit them (`stage_d_projection.py:1103`), yet the same underlying normalized facts are serialized into the prompt context that funds those sections' citations. The context-size guard (`_STAGE_D_CONTEXT_CHAR_LIMIT`) exists specifically because this combined payload approaches provider limits (`extractor.py:3799`, `STAGE_D_SYNTHESIS_COMPLETENESS_REPORT.md:50`). This is the clearest instance in the repository of "identical information appears regenerated" in the audit's own terms — the same facts exist deterministically in `normalized_facts`/`canonical_opportunity` and are re-serialized for the LLM to read but not reproduce.

2. **Stage D's `bid.*` field set is copy-through, not synthesis.** `title`, `client`, `file_number`, `submission_deadline`, `clarification_deadline` must "exactly copy matching metadata key's value or be null" (`stage_d_projection.py:1119`) — these values already exist, resolved, in `canonical_opportunity.py`'s executive-field resolution (confirmed deterministic, no LLM touch). The LLM is asked to transcribe already-known values with citation rather than compute anything.

3. **The Stage A fixed instruction prompt (14,728 characters) is identical, byte-for-byte, on every chunk call.** Nothing in `_extract_chunk_facts` varies this text per chunk — only the appended document text changes (`extractor.py:2759-2764`). This is a textbook instance of "repeated LLM work appears possible": the same static classification taxonomy, schema, and rules text is re-transmitted and (per-token) re-priced on every one of the 15–25+ calls a typical package requires.

4. **Stage A's requirement/artifact/clause taxonomies are closed enumerations.** `requirement_type`, `artifact_type`, `file_format`, `submission_channel`, `clause_kind`, `evaluation_role`, `weight_unit`, `weight_basis` are all controlled, fully enumerated vocabularies (`extractor.py:58-111,183`). The *identification* of the underlying fact from free text plausibly requires language understanding; the *classification* of an already-identified fact against a closed enum is a narrower, more deterministic-shaped sub-task than the extraction as a whole — the two are currently fused into one LLM call.

5. **Stage D's second retry attempt re-sends 100% of the first attempt's context for a correction that is a few sentences long.** `finalize_stage_d_request` is called fresh on each attempt with the same `projection` and only a short appended `correction` string (`extractor.py:4203-4204,4248`) — the ~580,000-character context is not incrementally patched or diffed, it is fully re-transmitted.

6. **`analyst.py`'s nine functions share no session state or context reuse.** Each function independently re-embeds relevant shared state (full requirements register, full draft text) inside its own prompt (e.g., `submission_readiness_check` and `analyze_proposal_alignment`, both reachable from `pages_extra.py:1079` in the same tab, each separately re-supply the requirements register). Within a single user sitting that touches multiple workspace stages, the same large context blocks are plausibly transmitted more than once across different calls.

7. **Stage A's max_tokens ceiling (8,000) sits close enough to typical chunk-content density that truncation-triggered recovery is a designed-for, recurring code path** (`RECOVERED_TRUNCATED` handling, `extractor.py:2818-2839`), rather than a rare edge case — this suggests the chunk-size/output-cap relationship itself is a recurring source of duplicated work, independent of any single document's content.

---

## Risk Assessment

| Risk | Evidence | Economic consequence |
|---|---|---|
| **Provider context-limit failure is a real, observed production outcome, not a hypothetical.** | `StageDContextTooLargeError` raised in a live commissioning run, 1,045,967 vs. 580,000-char limit (`SUBMISSION_ARTIFACT_PROJECTION_REPORT.md:181-186`) | Stage A's entire cost (2,929.66s of live API time on that run) was sunk with **zero** Stage D output — the most expensive possible failure shape, since the failure is detected only after the expensive stage completes. |
| **Stage D temperature is unpinned despite requiring strict, citation-exact output.** | No `temperature=` argument at the Stage D call site (`extractor.py:4225-4229`), unlike Stage A's explicit `temperature=0.0` (`extractor.py:2769`) | Higher output variance plausibly increases the live validation-failure rate seen in the corrected-corpus run (repeated `WRONG_EVIDENCE_OWNER`/`MISSING_POINTER`/`UNCITED_OUTPUT_FIELD` failures, `evaluation/bank_of_canada_briefing_pack/CORRECTED_CORPUS_REGENERATION_REPORT.md:34`) — each such failure on a large package costs a full-context retry. |
| **No token/cost telemetry exists.** | Confirmed across all commissioning scripts and ~85 markdown reports (background research, this audit); explicit statement at `STAGE_D_SYNTHESIS_PROJECTION_REPORT.md:166` | Any future optimization program will be flying blind on ROI measurement until `usage.input_tokens`/`usage.output_tokens` capture is added to the two LLM call sites — this is an observability gap, not an architecture gap. |
| **`anthropic` SDK is unpinned in `requirements.txt`.** | `requirements.txt:2` lists `anthropic` with no version constraint | Retry/timeout defaults, and even request/response shapes (e.g., `output_config` structured-output support), are exposed to silent behavior changes on redeploy. |
| **Stage A latency is highly unpredictable (9x variance observed between two real runs) with no per-call instrumentation to explain why.** | See Latency Analysis §2 | Commissioning-time cost/time estimates built from one reference run cannot be safely extrapolated to other packages without more granular telemetry. |
| **`bid_no_bid_score` (`analyst.py:297`) is a named, callable production function.** | `analyst.py:1,7,297-410`; wired into `pages/stage_decide.py:17` | Noted here purely as an economics-relevant call site (frequency/cost); its alignment with `ANTI_GOALS.md`'s "Win probability engine" and "Executive decision maker" exclusions is outside this audit's scope and is not adjudicated here — flagged for separate review. |

---

## Production Economics

### 1. Token economics by package tier

No genuine token counts exist anywhere in this repository (Finding 4). The figures below combine **MEASURED** character counts and wall-clock times from real commissioning runs with an explicit, stated **ESTIMATE** conversion of ~3.5 characters per token (splitting the difference between the repo's own internal working assumption of ~3 chars/token for its Stage D guard, `STAGE_D_SYNTHESIS_COMPLETENESS_REPORT.md:50`, and the ~4 chars/token commonly cited for English prose). Any figure below marked ESTIMATE should be treated as order-of-magnitude, not precise.

| Tier | Corpus (MEASURED) | Extracted chars | Requirements | Stage A calls | Stage A input tokens (ESTIMATE) | Stage D context tokens (ESTIMATE) | Stage A time (MEASURED) | Stage D time / outcome (MEASURED) |
|---|---|---|---|---|---|---|---|---|
| Small (no measured run exists at this tier; interpolated from the smallest documents in the BoC manifest) | ~3–5 docs, ~15,000–30,000 chars | — | ~15–25 | ~4–6 | ESTIMATE ~25,000–40,000 | ESTIMATE ~4,000–9,000 | Not measured; proportionally ESTIMATE 60–120s | Not measured; proportionally ESTIMATE 10–20s, success likely |
| Medium | BoC original, 15 docs | 134,617 | 98 | 15 (per-document; underlying chunk-level call count likely higher — see note) | ESTIMATE ~90,000–140,000 | ESTIMATE ~50,000–65,000 | **318.65s MEASURED** | **71.23s MEASURED, SUCCESS** |
| Large | 8-doc dense replay | 279,258 | 559 | Not disaggregated in source report | ESTIMATE ~250,000–350,000 | ESTIMATE ~260,000 (dispatch blocked before send) | **2,929.66s MEASURED** | **BLOCKED pre-dispatch, StageDContextTooLargeError, MEASURED** |
| Bank of Canada corpus (corrected, 16-doc) | 16 docs | Not stated | 413 | 16 (per-document) | Not derivable from source report | 559,401 chars **MEASURED** (~ESTIMATE 160,000 tokens) | Not recorded | **Guard PASSED; live synthesis FAILED CLOSED on repeated attempts, MEASURED** |

**Note on "Stage A calls":** the cited reports describe Stage A call counts as "one call per document" (15 or 16), but this audit's direct reading of `extract_document_facts` (`extractor.py:2800-2816`) shows each document is itself chunked at 12,000 characters and processed with one API call per chunk — a single 53,248-character document (the largest in the BoC manifest, Appendix G) would require multiple chunk-level calls under the current 12,000-character limit. The reports' "15/16 calls" figure most plausibly counts invocations of the per-document Stage A function, not literal API requests; the true API call count for these runs is very likely higher than reported and cannot be reconstructed without re-instrumenting the code — itself further evidence for the "no telemetry" finding above.

### 2. Commissioning analysis

- **Expected production runtime:** highly package-dependent and not reliably predictable from the two measured data points alone, which differ by ~9x in Stage A throughput for reasons not fully explained by document count or character volume (Latency Analysis §2). A clean, moderate package (BoC original) completes in ~6.5 minutes; a denser package can exceed 48 minutes on Stage A alone and still fail to produce a brief.
- **Expected provider cost:** cannot be stated in dollars with any confidence — no `usage` telemetry exists. Directionally, Stage D's per-call size (up to ~145K input tokens at the guard ceiling) makes it the single most expensive line item per successful call, while Stage A's cost accumulates from call *count* (15–25+ calls per package) rather than any single call's size.
- **Expected retry cost:** asymmetric. Stage A retries are architecturally bounded but can silently 2–3x a document's call count. Stage D retries are capped at one extra attempt, but that one extra attempt is priced identically to the (very large) original — observed in production as a real, uncompensated cost on the corrected-corpus run, where synthesis failed repeatedly with no brief ever produced.
- **Expected throughput:** at the one measured, fully successful, end-to-end run, throughput is one package per ~6.5 minutes of wall-clock (single-threaded, no parallelism, no queueing observed in code). At the observed 48.8-minute Stage-A-only outcome, effective throughput for that package class is worse than one package per hour, before Stage D is even reached.

---

## Optimization Readiness

*(Identification only, per instructions — no solutions proposed.)*

**Highest ROI candidates** (largest gap between observed cost and value; see Cost Analysis + Deterministic Opportunity Analysis):
- The Stage D authoritative-section/context-redundancy pattern (Deterministic Opportunity Analysis #1–2) — the single largest identified gap between what is transmitted and what is used.
- The Stage A fixed-prompt resend pattern (Deterministic Opportunity Analysis #3) — the most mechanically simple repeated-cost pattern identified, present on every single Stage A call without exception.
- The absence of token/cost telemetry (Risk Assessment) — not a cost reduction itself, but the precondition for measuring the ROI of everything else on this list.

**Lowest risk candidates** (localized, do not touch the constitutional authority boundaries the doctrine protects):
- Adding `usage`-field capture/logging at the two existing `client.messages.create` call sites — additive instrumentation, touches no prompt, schema, or validation logic.
- Pinning the `anthropic` SDK version in `requirements.txt` — a dependency-hygiene change with no behavioral intent.

**Highest architectural-risk areas** (any change here interacts with fail-closed validation, provenance, or authority boundaries the doctrine treats as governed):
- Anything touching Stage D's context construction, `output_config` schema, or citation/evidence-ownership validation (`stage_d_projection.py`) — this logic is the mechanism by which the doctrine's "preserve evidence before inference" and "maintain provenance" principles are enforced computationally; the corrected-corpus run shows it is already failing closed under current conditions, meaning it has little slack for change without careful validation.
- Any change to Stage A's coverage-guard/recovery cascade — this is also the mechanism preventing silent under-extraction (a fail-closed safeguard), not incidental retry logic.
- Introducing concurrency into Stage A's per-chunk/per-document loop touches shared-client and checkpoint-write ordering (`checkpoint.write(...)` calls are presently strictly ordered per attempt, `extractor.py:4205-4211`) and would need to preserve the deterministic aggregation and checkpoint semantics those safeguards depend on.

---

## Final Engineering Assessment

**Is the constitutional architecture itself computationally expensive, or is the current implementation strategy the dominant cost?**

The evidence supports the second answer clearly. Every module built to enforce the doctrine's separation of evidence, computation, inference, and decision authority — the canonical opportunity ledger, evidence graph, buyer intelligence contracts, decision workspace, governed reference resolution, all publication and orchestration layers — is pure deterministic Python with zero marginal provider cost (Pipeline Diagram §1, LLM Usage Analysis §1). None of the ~85 markdown architecture and review documents in this repository describe or require an LLM call outside of `extractor.py` and `analyst.py`. The constitutional boundaries the doctrine insists on (facts distinct from inference, provenance preserved, authoritative sections rebuilt by code rather than asserted by the model) are, in this codebase, implemented as reasons *not* to call the LLM, not as reasons to call it more.

The cost instead concentrates in two narrow, identifiable implementation choices within the two LLM-calling files:

1. **Stage A pays a large, fixed, per-call instruction tax on every one of many small calls** (14,728 characters × N chunks), rather than amortizing that instruction cost.
2. **Stage D pays for a very large context primarily to ground a small amount of generated text**, because the same deterministic facts that back its seven authoritative sections are re-serialized into its prompt even though the model is contractually forbidden from reproducing them — and this large context is paid for again, in full, on every retry.

Both patterns are implementation-strategy choices inside otherwise-correct, doctrine-compliant stages — not consequences of the doctrine itself. A narrower Stage A instruction, a smaller Stage D context, or telemetry to measure either would not require weakening any constitutional boundary (evidence/inference separation, human judgment sovereignty, fail-closed validation) this repository's governance model protects. The doctrine and the cost problem are, on this evidence, separable.

**What this audit could not determine**, for lack of existing telemetry: actual dollar cost per package, actual token counts per call, the true (as opposed to reported) API call count per Stage A run, and why Stage A throughput varies 9x between the two real measured runs. These are the concrete gaps a future measurement pass — not an optimization pass — should close first.
