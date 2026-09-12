# Document Metadata

| Field | Value |
|---|---|
| Document | `PRODUCTION_OPTIMIZATION_PROGRAM.md` |
| Title | Production Optimization Program — Bid Intelligence Pipeline |
| Authority Level | Level 5 — Operational Record |
| Version | 1.0.0 |
| Status | Draft — Planning Only, No Implementation Authorized |
| Purpose | Design a phased, risk-classified optimization program that reduces production cost and latency while preserving every constitutional boundary established in `MANIFESTO.md`, `ANTI_GOALS.md`, and `AGENT.md`. |
| Higher Authority | [`GOVERNANCE.md`](GOVERNANCE.md), [`AGENT.md`](AGENT.md) |
| Governed Documents | None directly. This document authorizes no code change; each phase's actual implementation, when undertaken, must separately satisfy `AGENT.md`'s "Before implementation" test. |
| Related Documents | [`PRODUCTION_ECONOMICS_AUDIT.md`](PRODUCTION_ECONOMICS_AUDIT.md) (source of all findings cited below), [`MANIFESTO.md`](MANIFESTO.md), [`ANTI_GOALS.md`](ANTI_GOALS.md), [`AGENT.md`](AGENT.md) |

**Scope discipline.** This document is a planning artifact. It changes no code, prompt, test, schema, or architecture, and it authorizes no implementation. Every opportunity below is identified and risk-classified, not built. Where an opportunity would touch a governed interface (prompts, projection schemas, replay formats — per `AGENT.md`'s "Protect compatibility deliberately"), that fact is stated explicitly as a precondition for any future implementation, not waived.

---

## Grounding: what the audit established

This program is built entirely on `PRODUCTION_ECONOMICS_AUDIT.md`. Five facts from that audit constrain everything below:

1. Exactly two files call an LLM in production: `extractor.py` (Stage A extraction, Stage D synthesis) and `analyst.py` (nine workspace-assistant functions). Every constitutional/evidence/publication module is deterministic and carries zero marginal provider cost — optimization has no legitimate target outside these two files.
2. Stage A dominates wall-clock time (81% on the one clean measured run; effectively 100% when Stage D never dispatches). Stage D dominates per-call size (up to ~580,000 characters, close to Claude Haiku's 200K-token window).
3. A meaningful share of Stage D's expensive context is explicitly unused by the model (the seven "authoritative sections" it is told never to emit).
4. No token or dollar telemetry exists anywhere in the repository. Every cost/benefit estimate in this program is therefore an **engineering range**, not a measured figure, and Part 1 of this program's own roadmap (Phase 1) exists specifically to replace these ranges with real numbers before larger investments are made.
5. The Bank of Canada "corrected" corpus run did not complete successfully end-to-end — Stage D repeatedly failed closed on live citation/evidence-ownership validation. This matters directly to Part 6 below.

---

## Part 1 — Optimization Opportunity Inventory

Fourteen opportunities were identified. Each is anchored to a specific location already documented in the audit. "Expected benefit" is directional (see Part 3 for ranges); this table is the map, not the estimate.

| ID | Location | Current behavior | Why it is expensive | Expected benefit | Complexity | Architectural risk | Constitutional risk |
|---|---|---|---|---|---|---|---|
| **O1** | `extractor.py:2766,4225`; `analyst.py:21` | No `usage.input_tokens`/`usage.output_tokens` capture anywhere; only wall-clock stage duration is recorded | N/A directly — but blocks measuring every other opportunity's real ROI, and blocks diagnosing the unexplained 9x Stage A throughput variance | Enables accurate cost/latency measurement for all subsequent work; diagnostic value for existing instability | LOW | None | None |
| **O2** | `requirements.txt:2` | `anthropic` SDK unpinned | Not directly expensive, but exposes retry/timeout defaults and feature availability (caching, batching) to silent drift on redeploy | Stability precondition for O3, O4, O11 | LOW | None | None |
| **O3** | `extractor.py:2759-2771` | 14,728-character fixed Stage A instruction block retransmitted, fully billed, on every chunk call (15–25+ calls/package) | Identical static content billed at full input-token rate N times per package | Reduces input-token cost of the single most repeated identical payload in the system | LOW–MEDIUM | LOW — no change to what is asked or returned | None — transport/billing mechanism only |
| **O4** | `stage_d_projection.py:1077`; `extractor.py:4203-4229` | On Stage D's second (retry) attempt, the full up-to-580,000-char context is resent for a request differing only by a short correction string | Full-context resend on retry is the single most expensive avoidable repeat in the system | Could make a Stage D retry cost a fraction of a fresh call | MEDIUM — must isolate the byte-identical portion from the varying correction suffix; cache write/read timing must be verified | LOW | None |
| **O5** | `extractor.py:2814` (Stage A per-document loop); `extractor.py:4194-4220` (guard check, currently evaluated only after Stage A–C complete) | The Stage D context-size guard is only checked after all Stage A work is done — confirmed cost: 2,929.66s of Stage A time spent before `StageDContextTooLargeError` on the 8-doc run | Worst possible failure shape: full expensive-stage cost paid, zero usable output | Could detect an oversized package earlier — once cumulative projected size makes the guard's failure mathematically certain — saving a fraction of remaining Stage A cost | MEDIUM — must prove monotonicity (facts only accumulate, never shrink, across Stage A/B/C) | MEDIUM — touches a fail-closed guard path directly; must never produce a false-positive early abort | LOW, provided the identical failure code/semantics are preserved and nothing is silently dropped |
| **O6** | `extractor.py:2814-2896` (chunk loop); `extractor.py:4300-4316` (document loop) | Fully sequential; zero concurrency anywhere in the repository (confirmed by repo-wide search) | Wall-clock time is the straight sum of every independent call's latency | Chunks within a document and documents within a package have no data dependency — bounded concurrency could reduce wall-clock time roughly in proportion to concurrency factor (does **not** reduce token/dollar cost) | MEDIUM–HIGH — must prove `aggregate_stage_a_facts` order-independence, make checkpoint writes thread-safe, and handle provider rate limits under concurrent load | **HIGH** — audit explicitly names this as a top architectural-risk area (checkpoint/aggregation ordering) | LOW if order-independence is proven, not assumed — requires explicit verification before deployment |
| **O7** | `extractor.py:2293` (`_STAGE_A_MAX_CHUNK_CHARS`); `extractor.py:2818-2896` (recovery logic) | 12,000-char chunks against an 8,000-token output ceiling; truncation-triggered recovery is a recurring, designed-for path, plausibly implicated in the 9x Stage A variance | Every recovery pass re-pays the full fixed-prompt tax and adds sequential latency | Evidence-based chunk/ceiling tuning (using O1 data) could reduce recovery-triggered extra calls without changing extraction fidelity | LOW–MEDIUM, but depends on O1 for evidence rather than guesswork | LOW–MEDIUM — changes chunk boundaries; must be validated against Stage A reliability tests | LOW, provided fidelity is validated unchanged, not assumed |
| **O8** | `extractor.py:4225-4229` | Temperature unset (provider default) for Stage D, unlike Stage A's explicit `0.0` | Plausibly contributes to the live validation-failure rate that triggers full-context retries (observed repeatedly on the corrected-corpus run) | Lower, pinned temperature could reduce output variance and therefore retry rate — each avoided retry saves a full up-to-580,000-char resend | LOW — one parameter | LOW | LOW–MODERATE — must verify no degradation of the genuinely generative surface (executive summary, outline quality) via quality evaluation, not cost metrics alone |
| **O9** | `stage_d_projection.py:382` (`build_stage_d_synthesis_projection`); `extractor.py:3925` (`apply_stage_d_authoritative_sections`) | Facts backing the seven authoritative sections — which the model is told never to emit — are still serialized into the up-to-580,000-char context, because the same facts also ground citations | Single largest identified gap between what is transmitted and what is used; direct cause of how tightly the context guard is sized | Potentially the largest token-reduction opportunity in the system | **HIGH** — must distinguish "needed to ground a citation" from "serialized because it lives in the same structure," without breaking `validate_stage_d_response` or the `PROJECTION_VERSION`/digest integrity contract | **HIGH** — audit names this code path as already failing closed under current conditions, with "little slack for change without careful validation" | MODERATE — no evidence is deleted from the *system*, only from one call's input; a mistake here self-detects as a new validation failure rather than silent evidence loss, but still demands rigorous testing |
| **O10** | `extractor.py:58-111,183` (closed-enum taxonomies) | A single LLM call both identifies a fact from free text and classifies it against a closed enum | Not directly expensive; represents unbundled potential — a narrower sub-task (enum classification) riding inside a broader one (open extraction) | Speculative — uncertain net token savings, since extraction must still emit enough raw signal for any downstream classifier | **HIGH** — requires building and validating an entirely new deterministic/ML component with its own accuracy bar | **HIGH** — new non-LLM component with unbounded regression risk without extensive evaluation data | MODERATE — classification accuracy changes could alter what counts as a "Mandatory + Supplier Qualification" gate; needs the same rigor as any change to a controlled vocabulary. **Research spike only — not committed roadmap work.** |
| **O11** | `extractor.py:2766` (call site) | Synchronous, real-time call inside a blocking `st.spinner` | Batch-tolerant workloads are typically priced well below synchronous real-time pricing; Stage A's chunk calls are architecturally independent and don't need sub-second responsiveness | Potentially the largest *dollar* reduction per token of any item on this list | **HIGH** — product/UX redesign (async processing, polling/notification instead of a blocking button), checkpoint/resume semantics change substantially | MODERATE — doesn't touch evidence/provenance/authority, but materially changes product flow | LOW technically, but a synchronous-to-asynchronous product change needs product-owner sign-off, not just engineering judgment. **Defer past Phase 5.** |
| **O12** | `analyst.py` (all nine functions); `pages/stage_check.py`, `pages/stage_decide.py`, `pages/stage_build.py`, `pages_extra.py` | Each function independently re-embeds the full requirements register and/or full draft text; nothing is cached or reused across functions within one session | A user touching several workspace stages in one sitting may retransmit the same large context repeatedly | Session-scoped caching of the largest stable inputs could reduce redundant input-token spend proportional to workspace usage per sitting | MEDIUM — needs a cache-key design tied to draft/requirement mutation state, with correct invalidation | LOW–MEDIUM | LOW, **provided** invalidation is correct — stale cached context could cause an assistant function to reason from out-of-date requirements; must pair with a visible "based on data as of X" signal if implemented |
| **O13** | `analyst.py:126-761` (`max_tokens` 2,048–4,096 across nine functions) | Ceilings appear to be round-number defaults, not measured against actual output distributions | Not a direct cost driver (Anthropic bills actual output, not the ceiling); an undersized ceiling causes truncation/retries, an untuned one offers no signal either way | Primarily a **latency and reliability** benefit — reduces worst-case variance and truncation-driven retries | LOW, but strictly depends on O1 | None | None |
| **O14** | `extractor.py:2768,4226` (`max_tokens=8000` for both Stage A and D) | Same rationale as O13, applied to the two dominant stages | Same as O13 | Same as O13, at higher aggregate impact given Stage A/D's call volume/size | LOW, strictly depends on O1 | None | None — provided ceilings are only ever raised toward or set at the largest legitimate observed completion size, never guessed downward |

### Ranked execution sequence

Ranking reflects recommended sequencing (dependency order and risk-adjusted value), not raw benefit magnitude alone — several high-benefit items (O9, O11) rank low because they require Phase-1 evidence and a stable baseline (Part 6) before they can be responsibly attempted.

| Rank | ID | Rationale for position |
|---|---|---|
| 1 | O1 | Prerequisite for measuring every other item; zero risk |
| 2 | O2 | Trivial hygiene; stabilizes the foundation O3/O4/O11 depend on |
| 3 | O3 | High benefit-to-effort ratio; purely transport-level, semantically inert |
| 4 | O4 | Directly targets the single most expensive avoidable repeat identified |
| 5 | O8 | Cheap to try, plausible retry-rate benefit; needs quality validation before being called done |
| 6 | O13/O14 | Cheap, but only meaningful once O1 supplies real distributions |
| 7 | O7 | Meaningful, evidence-dependent, moderate validation burden |
| 8 | O5 | Meaningful on the specific failure mode that already occurred in production |
| 9 | O12 | Real benefit for heavy-usage sessions; invalidation correctness is the gating concern |
| 10 | O6 | Large latency win, but the audit's own highest-flagged architectural-risk item |
| 11 | O9 | Potentially the largest token win in the system, and the highest-rigor item to get right |
| 12 | O11 | Largest possible dollar win, but a product decision, not just an engineering one |
| 13 | O10 | Uncertain net benefit; treat as a research spike, not a roadmap commitment |

---

## Part 2 — Risk Classification

Per the definition supplied: **SAFE** = no constitutional owner changes, no semantic changes, no evidence changes, no publication changes, no governance changes.

| Classification | Items | Basis |
|---|---|---|
| **SAFE** | O1, O2, O3, O4, O13, O14 | Telemetry, dependency pinning, and prompt/context caching change *transport and measurement*, never *content, semantics, evidence, or authority*. Output-ceiling right-sizing (O13/O14) is safe only when driven by measured data and only ever raised to or set at the largest legitimate completion size — never shrunk speculatively. |
| **MODERATE** | O5, O7, O8, O12 | Each changes system *behavior* (control flow, chunk boundaries, sampling temperature, caching with invalidation) without touching evidence/publication/governance boundaries directly — but each requires empirical validation against existing test suites or new quality checks before being considered complete, not just deployed. |
| **HIGH RISK** | O6, O9, O10, O11 | Each either touches a code path the audit already flagged as fragile under current production conditions (O6's checkpoint/aggregation ordering, O9's already-failing-closed context construction), introduces an entirely new unvalidated component (O10), or requires a product-level UX change outside pure engineering discretion (O11). |

---

## Part 3 — Impact Estimates (engineering ranges — no invented precision)

| ID | Latency reduction | Token reduction | API cost reduction | Implementation effort |
|---|---|---|---|---|
| O1 | None directly (adds negligible overhead) | None | None directly — enabling only | Low (days) |
| O2 | None | None | None | Low (hours) |
| O3 | Small–moderate (fewer bytes to transmit/process per call) | **Moderate–large** on the cached-prefix portion specifically (rough order: the fixed block is a large fraction of total Stage A input per short chunk, shrinking toward a smaller fraction as chunk content grows) | Moderate, concentrated in packages with many small-to-medium chunks | Low–Medium (days) |
| O4 | Small on the common path; **large** on the retry path specifically | Large on retries only (retries are rare per the audit's own reporting) | Moderate in expectation (weighted by observed retry frequency, currently unmeasured) | Medium (days–1–2 weeks) |
| O5 | **Large** on oversized packages specifically (up to most of the wasted Stage A tail observed on the 8-doc run); none on packages that fit | None | Moderate–large on oversized packages specifically | Medium (1–2 weeks incl. monotonicity proof) |
| O6 | **Large** — potentially a large fraction of total Stage A wall-clock time, bounded by chosen concurrency factor and provider rate limits | None (same total tokens, executed in parallel) | None directly (may indirectly increase 429/backoff overhead if concurrency exceeds rate limits) | High (2–4+ weeks incl. correctness proof, checkpoint thread-safety, rate-limit handling) |
| O7 | Small–moderate (fewer recovery passes) | Small–moderate | Small–moderate | Low–Medium (days), gated on O1 |
| O8 | Indirect — moderate, via reduced retry rate | Indirect — moderate, via fewer full-context resends | Indirect — moderate | Low (days) + quality validation cycle |
| O9 | Small direct; moderate indirect (smaller payload to serialize/transmit) | **Large** — audit identifies this as the largest context-size driver | **Large**, concentrated on medium-to-large packages | High (2–4+ weeks incl. citation-contract validation, projection versioning) |
| O10 | Uncertain | Uncertain, possibly small net (offset by new classifier overhead) | Uncertain | High (weeks, research spike) |
| O11 | **Negative for turnaround latency** (batch APIs trade latency for cost — this is a deliberate tradeoff, not a defect) | None | Potentially **large** (batch pricing is typically well below synchronous pricing for tolerant workloads) | High (weeks, product + engineering) |
| O12 | Small–moderate for multi-stage sessions | Small–moderate for multi-stage sessions | Small–moderate | Medium (1–2 weeks incl. invalidation design) |
| O13 | Small (fewer truncation-driven retries) | None directly | None directly | Low (days), gated on O1 |
| O14 | Small–moderate (fewer truncation-driven recovery passes on Stage A/D) | None directly | None directly | Low (days), gated on O1 |

**Reading this table.** No figure above is a percentage promise. "Large," "moderate," and "small" are relative orderings across this specific set of opportunities, derived from the audit's own measured character-count and timing data — they are the correct inputs for *sequencing* decisions, not for a cost-savings commitment to any external stakeholder. Part 6 explains why converting these ranges into real numbers is itself Phase 1's job.

---

## Part 4 — Phased Optimization Roadmap

### Phase 1 — Observability
**Objective:** Replace every "ESTIMATE" in the audit with a measured number, and give future phases a way to prove their own impact.
**Contains:** O1, O2.
**Preserves correctness by:** adding pure read-side instrumentation (`usage.input_tokens`, `usage.output_tokens`, per-call and per-retry timing, retry/recovery-path counters) with no change to any request, prompt, schema, or validation path; pinning a dependency version with no functional change.
**Independently deployable:** yes — has no dependency on any other phase and no product-visible behavior change.
**Success criteria:**
- Every Stage A chunk call, every Stage D attempt, and every `analyst.py` function call logs input/output token counts and latency.
- The 9x Stage A throughput variance between the two audit-cited runs can be explained (or newly characterized) from logged data rather than inferred from wall-clock totals alone.
- Actual recovery/retry trigger rates (Stage A truncation/failure recovery, Stage D 2-attempt retries) are known numbers, not "unmeasured."
- `anthropic` has a pinned version in `requirements.txt`, verified against the caching/batching features later phases will depend on.

### Phase 2 — Stage A efficiency
**Objective:** Reduce Stage A's repeated fixed-cost overhead and improve its latency predictability, using Phase 1 data to guide tuning rather than guessing.
**Contains:** O3, O7, O14, O5.
**Preserves correctness by:** requiring every change in this phase to pass the existing Stage A extraction reliability test suite unmodified, and requiring O5 specifically to preserve the exact `StageDContextTooLargeError` failure code and "no requirements silently omitted" guarantee, only detected earlier.
**Independently deployable:** yes, and each of O3/O7/O14/O5 can ship separately from the others.
**Success criteria:**
- Stage A prompt-caching cache-hit rate is measured and non-trivial (target to be set from Phase 1 baseline, not assumed in advance).
- Stage A reliability test suite passes unchanged after any chunk-size/ceiling tuning.
- On a package sized like the 8-document/559-requirement run, the system detects that Stage D will be blocked well before Stage A's full wall-clock cost is paid, while producing the identical error.

### Phase 3 — Stage D efficiency
**Objective:** Reduce Stage D's per-call size and retry cost — the highest-value, highest-rigor phase.
**Contains:** O4, O8 first; O9 only after O4/O8 are validated in production and only with its own dedicated review (see gating note below).
**Preserves correctness by:** requiring every Stage D projection/citation test in the existing suite to pass unmodified; requiring O8 to be validated by human quality review of generated executive summaries/outlines, not cost metrics alone; requiring O9 to preserve the full evidence-ownership and citation contract enforced by `validate_stage_d_response`, with `PROJECTION_VERSION` bumped and reviewed as a governed-interface change per `AGENT.md`.
**Independently deployable:** O4 and O8 are independently deployable from each other and from O9. O9 is intentionally the largest, most gated unit of work in this entire program and should be treated as its own sub-phase (3b) with its own go/no-go review, not bundled into a single release with O4/O8.
**Success criteria:**
- Measured Stage D retry rate (from Phase 1 telemetry) decreases or is shown unaffected by O8 without any decrease in generated-content quality (human-reviewed).
- A Stage D retry's measured cost (from Phase 1 telemetry) is materially lower after O4 than before, on the same class of package.
- If O9 proceeds: 100% of the existing Stage D projection/validation test suite continues to pass, and the corrected Bank of Canada corpus (413 requirements) demonstrates successful, non-retried live synthesis — not merely a passing context guard.

### Phase 4 — Workspace optimization
**Objective:** Reduce redundant context transmission across the Check/Decide/Build/Submit workspace functions.
**Contains:** O12, O13.
**Preserves correctness by:** requiring any cached context to carry a visible "as-of" marker to the user, and requiring invalidation to be proven correct (a stale-cache regression test) before shipping.
**Independently deployable:** yes, and separable from all other phases.
**Success criteria:**
- No workspace assistant function ever reasons from requirements/draft data the user has since edited without a visible staleness indicator.
- Measured redundant-context transmission (from Phase 1 data) decreases for multi-stage sessions.

### Phase 5 — Concurrency
**Objective:** Reduce Stage A wall-clock latency by exploiting the independence between chunks and documents — the highest-complexity, highest-architectural-risk phase, undertaken last and only atop a stable, measured, already-optimized sequential baseline.
**Contains:** O6, evaluated only after Phases 1–4 are in production and measured.
**Preserves correctness by:** requiring a formal proof (or exhaustive test evidence) that `aggregate_stage_a_facts` produces identical output regardless of chunk/document completion order; requiring checkpoint writes to be made safe under concurrent execution without changing the on-disk replay format; requiring provider rate-limit behavior under concurrency to be characterized before any default concurrency factor is chosen.
**Independently deployable:** yes, but deliberately sequenced last because it is the item the audit itself flags as carrying the highest architectural risk, and because Phases 1–4 substantially reduce the *volume* of work concurrency would otherwise need to parallelize.
**Success criteria:**
- Aggregation output is byte-identical between sequential and concurrent execution across the full existing Stage A test corpus.
- Checkpoint replay remains fully reproducible under concurrent execution.
- No increase in provider 429/rate-limit errors beyond an agreed tolerance at the chosen concurrency factor.
- Measured wall-clock Stage A time decreases materially on the reference packages used throughout this program.

**Explicitly out of this roadmap** (research spikes only, revisit after Phase 5 with fresh evidence): O10 (deterministic enum classifier split), O11 (Batches API migration for Stage A). Both require decisions (new component accuracy bar; product UX change) that this engineering program should surface but not resolve unilaterally.

---

## Part 5 — Opportunities That Must Never Be Attempted

1. **Weakening or bypassing Stage D's citation/evidence-ownership validation (`validate_stage_d_response`) to reduce the retry rate.** This validation is the mechanism enforcing `MANIFESTO.md`'s "preserve evidence before inference." A retry-rate reduction achieved by accepting less-grounded output is not an optimization — it is a correctness regression wearing a cost metric.
2. **Truncating, sampling, or silently omitting requirements/facts from Stage D's context to fit inside the size guard.** The existing behavior — fail closed with `StageDContextTooLargeError`, explicitly stating "No requirements were silently omitted" — must never be replaced with silent truncation, even though truncation would trivially "solve" the context-size problem. This directly violates `AGENT.md`'s "Prefer explicit failure to silent truncation, repair, coercion, or unsupported certainty."
3. **Caching or reusing LLM context or output across different procurement packages, buyers, or tenants.** Caching within a single request's retry (O4) or a single document's repeated static instruction text (O3) is transport-level and content-inert. Caching *across* packages would risk one buyer's confidential procurement content leaking into another's context or output — a direct provenance and confidentiality violation, not merely a cost risk.
4. **Letting the LLM generate, influence, or shortcut any of Stage D's seven "authoritative sections."** These must remain exclusively rebuilt by deterministic code from verified facts. Any latency shortcut of the form "let the model draft it and validate after" reintroduces inference into a boundary the architecture deliberately keeps fact-only.
5. **Touching the human-judgment-sovereignty boundary in the name of speed or cost — including in `bid_no_bid_score` and any similarly interpretive `analyst.py` function.** Nothing in this program authorizes removing framing, disclaimers, or the non-decisional posture these functions are required to maintain under `MANIFESTO.md`'s "Human judgment" principle, regardless of any token savings such a change might yield.
6. **Skipping or weakening Stage B normalization or Stage C conflict detection to save time.** Both are already fully deterministic and consume a combined ~0.001–0.4 seconds even on the largest measured run — there is no economically rational argument for touching them, and doing so would remove fail-closed conflict surfacing for a saving indistinguishable from zero.
7. **Shrinking `max_tokens` ceilings (O13/O14) below the largest legitimate observed completion size, or making any output-size change without measured evidence.** A ceiling reduction that causes a legitimate large package's requirements or brief content to be truncated rather than explicitly failing is a silent-truncation violation identical in kind to item 2.
8. **Introducing concurrency (O6) in any form that could make aggregation order-dependent or checkpoint replay non-reproducible.** Replay and checkpoint formats are governed interfaces under `AGENT.md`; concurrency is permitted only when it provably preserves their determinism, never when it merely appears to in testing.
9. **Adopting a cheaper or faster model tier, or reducing model capability in any call site, without equivalent-or-better validated accuracy against the existing Stage A/D reliability and projection test suites.** Cost reduction is never sufficient justification on its own for a change that could reduce extraction or synthesis fidelity.
10. **Treating this program's cost/latency metrics as a substitute for the doctrine's correctness metrics.** A change that reduces measured cost while correctness regresses in ways not yet covered by existing tests is not a success under this program — it is an undetected failure.

---

## Part 6 — Should Optimization Begin Before Commissioning Is Complete?

**Recommendation: Phase 1 (observability and dependency hygiene) should begin immediately, in parallel with ongoing commissioning work. Every other phase — anything classified MODERATE or HIGH RISK in Part 2 — should wait until (a) at least one fully successful end-to-end production run exists as a reproducible baseline, (b) the Bank of Canada corpus regenerates successfully through actual Stage D synthesis (not merely a passing context guard), and (c) a successful Executive Brief generation exists downstream of that synthesis.**

**Support:**

- The audit's own evidence shows commissioning is not yet complete in the sense that matters for this recommendation: the corrected Bank of Canada corpus (413 requirements, context guard passed at 559,401/580,000 characters) still failed live Stage D synthesis repeatedly, on exactly the kind of strict validation (`WRONG_EVIDENCE_OWNER`, `MISSING_POINTER`, `UNCITED_OUTPUT_FIELD`) this program's Phase 3 (O8, O9) would directly touch. Optimizing those code paths before root-causing that failure conflates two separate investigations: is a given change improving efficiency, or is it accidentally masking (or worsening) an unresolved correctness defect? Neither question can be answered cleanly while the other is unresolved.
- Without a passing, reproducible baseline, there is no stable reference to measure any optimization's effect against. A retry-rate "improvement" measured against a baseline that was already failing for unrelated reasons is not a valid measurement — it is noise dressed as a result. This is the same discipline `AGENT.md` asks of any implementation: "Report architectural impact, validation, compatibility effects, and known limitations accurately. Never claim evidence, CI, live behavior, or external validation that did not occur."
- Phase 1 is deliberately exempt from this constraint because it changes no behavior, model output, or code path that commissioning depends on — it only observes. It is also directly useful *to* commissioning: the telemetry it adds is very likely necessary to root-cause the corrected-corpus Stage D failures and the unexplained 9x Stage A variance in the first place. Running Phase 1 now is not "optimizing before commissioning" — it is instrumenting the exact commissioning problem still open.
- SAFE-classified items beyond O1/O2 (O3, O4, O13, O14) carry a weaker version of the same caveat: because they are transport-level and content-inert, they are lower-risk to run before full commissioning completes, but this program still recommends holding even these until Phase 1 telemetry confirms the baseline they would be measured against, so that their reported impact is real rather than assumed.
- Once (a)–(c) above are satisfied, the ranking and phasing in Parts 1 and 4 should be revisited with real Phase 1 data before Phases 2–5 proceed, since several of this program's own impact estimates (Part 3) are explicitly provisional pending that data.

---

## Summary for Executive Planning

This program identifies fourteen concrete optimization opportunities, all confined to the two files the audit already isolated as the system's entire provider-cost surface. Six are classified SAFE and can be sequenced immediately after a brief observability phase; four are MODERATE and require empirical validation before being called complete; four are HIGH RISK and require either extensive correctness proof (concurrency, context trimming) or a decision outside pure engineering discretion (a new classification component, a synchronous-to-asynchronous product change). Ten specific practices are named as never to be attempted regardless of their cost benefit, because each would trade a constitutional guarantee — evidence integrity, fail-closed behavior, human judgment sovereignty, or replay determinism — for savings this program does not consider a legitimate trade. The recommended sequencing starts with measurement, not modification, and holds every behavior-changing phase until commissioning produces a stable, successful baseline to measure against.
