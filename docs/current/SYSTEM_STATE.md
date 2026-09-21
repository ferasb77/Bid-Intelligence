# System State

The smallest current-state snapshot a fresh agent needs. Not a history, not
an architecture explanation — see [NAVIGATION.md](NAVIGATION.md) for where
to read either of those when a task actually requires them.

## Product lifecycle

`UNDERSTAND → DECIDE → BUILD → CHECK → SUBMIT`

One Streamlit page per stage under `pages/stage_*.py`. This lifecycle is
implemented, not aspirational — it replaced an earlier flat, fragmented
navigation (see `docs/BID_INTELLIGENCE_STREAMLINING_AUDIT.md` if the task
needs that history).

## Current major subsystems

- **Fast Analysis** (`fast_analysis.py`, orchestrated by `analysis_service.py`) — the
  primary, LLM-driven procurement extraction engine. Advisory only; never
  writes canonical procurement truth.
- **Procurement governance** — `requirements`/`bids.procurement_revision`/
  `bids.procurement_truth_status` (`governed` | `ungoverned`). Canonical
  requirement facts (description/category/rfso_ref/weight) can only change
  through the governed review RPCs once a bid is `governed`
  (`database._guard_canonical_requirement_write`).
- **Raw FastAnalysisResult persistence** — `fast_analysis.serialize_fast_analysis_result()`
  / `deserialize_fast_analysis_result()`, written to
  `analysis_results.fast_analysis_result_snapshot`. Lets a completed run's
  minimum-score thresholds, qualification mechanisms, tie-break ranks, and
  deterministic service-scope/Response-Guideline parses be regenerated into
  a report with zero further LLM calls.
- **Buyer Intelligence** — external, advisory context attached to a
  `FastAnalysisResult`, always kept visibly separate from procurement
  requirement facts in every consumer.
- **BUILD workspace** (`pages/stage_build.py`) — the Proposal Outline &
  Integrated Section Drafter.
- **Section Analyzer** (`section_analyzer.py`) — a *formative*, per-section
  review inside BUILD ("is this section heading in the right direction?"),
  distinct from the later, holistic CHECK-stage audit below.
- **CHECK / Proposal Alignment** (`analyst.py`'s `analyze_proposal_alignment*`
  family) — the holistic, whole-package submission-readiness audit.
- **Proposal Intelligence** (`proposal_intelligence.py` +
  `migrations/015_proposal_intelligence.sql`, **live and commissioned** —
  see below) — the durable, immutable, provenance-aware persistence layer
  for CHECK's Proposal Alignment output: what the proposal actually says,
  demonstrates, covers, contradicts, fails to evidence, or omits relative
  to the procurement. Advisory intelligence, never canonical procurement
  truth. Adds NO new LLM call — a pure adapter over the existing
  `analyze_proposal_alignment_package()` result, persisted via
  `tenancy.run_proposal_intelligence_for_organization()`.
  `PROPOSAL_INTELLIGENCE_ANALYSIS_VERSION` is `proposal-intelligence-v2`
  (PI-2A): the analyzer's existing per-chunk schema now also carries
  structured, deterministically-attached proposal-side provenance
  (`ProposalSourceRef` — file_id/content_hash/filename/package_path/
  file_type/section/char_start/char_end, built entirely from chunk
  metadata the application already has, never from the model),
  procurement-side provenance (a requirement's own canonical
  `source_refs`), a closed-vocabulary evidence-strength rating (STRONG/
  MODERATE/WEAK), locally-safe typed findings (WEAK_EVIDENCE/
  UNSUPPORTED_CLAIM/CONTRADICTION/INTERNAL_INCONSISTENCY — only ever
  established from within one chunk's own visible passage), and separate
  `proposal_observations` (DELIVERY_COMMITMENT/COMMERCIAL_EXPOSURE) —
  all additive to the unchanged chunk request/response call topology
  (still exactly one call per chunk plus the existing optional narrative
  synthesis call).
  `PROPOSAL_INTELLIGENCE_ANALYSIS_VERSION` is now `proposal-intelligence-v3`
  (PI-2B1, implemented, **NOT live-provider commissioned** — every
  provider-call site is exercised only against mocked/frozen responses in
  tests; the real `_call_package_reasoning` code path has never been
  invoked against the live Anthropic API): a whole-package reasoning layer
  on top of PI-2A's per-chunk output. Each chunk call now also extracts
  `proposal_claims` (a closed-vocabulary, provenance-bearing affirmative
  proposal statement — EXPERIENCE/CAPABILITY/RESOURCE/CREDENTIAL/
  METHODOLOGY/DELIVERY/QUANTITY/DATE/DURATION/STAFFING/COMMERCIAL/PRICING/
  COMPLIANCE/OTHER), deterministically deduped into a package-wide
  `proposal_claim_ledger` (`analyst._aggregate_proposal_claims`) — never
  merging claims that actually conflict (e.g. "8 coaches" vs "10
  coaches" stay two claims). `analyst._build_package_intelligence_ledger`
  compresses the claim ledger + requirement evidence + observations +
  local deficiencies into a compact ledger addressed only by short IDs
  (`C#` claims, `P#` sources) — the raw proposal is NEVER resent.
  `analyst.analyze_proposal_package_intelligence()` issues exactly ONE
  new bounded provider call (`_call_package_reasoning`, telemetry
  workflow="proposal_intelligence" operation="package_reasoning") per
  completed alignment run, asking only for CONTRADICTION/
  INTERNAL_INCONSISTENCY/UNSUPPORTED_CLAIM findings that cite ledger IDs;
  every returned finding is individually validated fail-closed
  (`analyst._reconcile_package_findings` — unknown claim/source id, an
  unrecognized finding_type/severity, or a non-ledger-verbatim req_id
  rejects that finding only) and an UNSUPPORTED_CLAIM is structurally
  rejected outright whenever local coverage is incomplete, regardless of
  what the model returned. A package-call failure never destroys the
  already-valid local PI-2A result — it's recorded as
  `coverage_metadata.package_intelligence.package_reasoning_status =
  "FAILED"` alongside zero fabricated findings. Package findings persist
  into the SAME `proposal_intelligence_findings` table (no migration —
  CONTRADICTION/INTERNAL_INCONSISTENCY/UNSUPPORTED_CLAIM were already in
  migration 015's enum) tagged `payload.scope = "package"` (a local
  finding is now tagged `payload.scope = "local"` for the same reason);
  CHECK's "Proposal Intelligence" section renders them in their own
  "Whole-Package Consistency" cards, labeled "Package-level", from
  persisted rows only (no rerun). PI-2B2 (Response Guideline coverage /
  evaluator usability), a proposal quality score, win probability, and
  proposal rewriting remain explicitly deferred (not implemented). See
  [NAVIGATION.md](NAVIGATION.md) for the full file map.

## Architectural fact-type separation

Every subsystem above keeps these categories distinct, never merges them:
**evidence** (what a source document actually says) → **canonical
procurement truth** (`requirements`, governed once a bid is `governed`) →
**intelligence** (AI-derived reasoning, advisory, never silently promoted
to fact). See `AGENT.md` / `MANIFESTO.md` for the full doctrine if a task
requires it.

## Current development state

The **BI Token/Context Optimization Program is complete for now** (Phases
2–5E.1) — its development freeze on BI product features no longer applies.
Live A/B experiments identified by that program (density-aware chunking,
the compact provenance wire format) remain **not activated**, pending paid
credits; do not activate them without a task explicitly requesting it.

**Proposal Intelligence development is explicitly active** (PI-1
established the durable domain foundation on this branch; PI-2A added
richer per-chunk evidence/provenance/observation depth on top of it, with
no new model call). PI-2A.1 hardened the deterministic post-response dedup
in `analyst._deduplicate_findings()`/`_aggregate_proposal_observations()`
so it never collapses findings across different `deficiency_type` values
or observations with matching statements but different implications, and
always unions (never drops) distinct structured `proposal_source_refs`
across a merged cluster (exact-match-per-field; stable first-seen order).
PI-2B1 (cross-document/whole-package claim, contradiction, and consistency
reasoning) is now **implemented** (analysis_version
`proposal-intelligence-v3`) but **NOT live-provider commissioned** — see
above. PI-2B2 (Response Guideline coverage / evaluator usability) is
explicitly NOT started. Future work should build on PI-2A/PI-2A.1/PI-2B1,
not re-litigate their schema/adapter/ledger design without cause.

Absent an explicit task instruction otherwise, still do not: apply
migration 013, alter/reapply migration 015, activate the compact-wire
prototype, change chunk sizes/max_tokens/model routing/caching, or merge
`main`/deploy.

## Migrations known in this repository (files, not live-database state)

Highest migration file present: **015** (`015_proposal_intelligence.sql`).
Files 001–015 exist in `migrations/`. This describes what's **written in
the repo**, not what's applied to any Supabase project — see the note
below.

> **LAST VERIFIED EXTERNAL STATE** (as of the audit that wrote this file):
> migration 012 was applied to the project's Supabase database by the repo
> owner. Migration 013 (Section Analyzer) was written but explicitly NOT
> applied — still true. Migration 014 (`model_usage_events`, telemetry)
> was found already live during Phase 5's commissioning work. Migration
> 015 (Proposal Intelligence, PI-1) was applied live on 2026-09-20 and is
> formally recorded in Supabase's migration ledger as
> `20260920205721 proposal_intelligence`. Live PI-1 commissioning also
> passed on 2026-09-20: service-role RPC execution, snapshot reuse/versioning,
> atomic bundle rollback, composite cross-bid rejection, authenticated RLS
> read isolation/write denial, latest-usable-run semantics, and disposable
> cleanup were all exercised against the real project. The ledger also
> contains `20260920211025 proposal_intelligence_commissioning`, a
> commissioning-only assertion run with no lasting schema or data changes
> and no corresponding numbered repo migration file. Migration 013 remains
> unapplied. PI-2A added richer per-chunk evidence/provenance/observation
> fields on top of the SAME live migration 015 schema — no new migration
> was needed or created. PI-2B1 (whole-package reasoning) reuses the same
> migration 015 `proposal_intelligence_findings` table/enum again — its
> CONTRADICTION/INTERNAL_INCONSISTENCY/UNSUPPORTED_CLAIM finding_type
> values already existed there from PI-1's forward-looking taxonomy — so
> no new migration was needed for PI-2B1 either. Treat any future "is migration N live"
> question as requiring a fresh check — `git log` and this file are not a
> substitute for checking the live database when a task depends on it.

## Where NOT to look first

Do not begin ordinary task orientation by reading the ~99 root-level
`.md` files. Most are historical operational records (implementation
reports, commissioning reports, remediation reports) describing *completed
past work*, not current authoritative architecture. See
[NAVIGATION.md](NAVIGATION.md) and
[ROOT_DOC_INVENTORY.json](ROOT_DOC_INVENTORY.json) before reading any of
them.
