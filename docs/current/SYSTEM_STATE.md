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

## Architectural fact-type separation

Every subsystem above keeps these categories distinct, never merges them:
**evidence** (what a source document actually says) → **canonical
procurement truth** (`requirements`, governed once a bid is `governed`) →
**intelligence** (AI-derived reasoning, advisory, never silently promoted
to fact). See `AGENT.md` / `MANIFESTO.md` for the full doctrine if a task
requires it.

## Current development freeze

A **context/token optimization program is active** on this branch
(`feature/evidence-explainability`). Do not start new BI product features,
Section Analyzer refinement, Organizational Memory, or Fast Analysis
runtime changes unless a task explicitly lifts the freeze. This file itself
was created under that program (Phase 2).

## Migrations known in this repository (files, not live-database state)

Highest migration file present: **013** (`013_section_analyzer.sql`).
Files 001–013 exist in `migrations/`. This describes what's **written in
the repo**, not what's applied to any Supabase project — see the note
below.

> **LAST VERIFIED EXTERNAL STATE** (as of the audit that wrote this file):
> migration 012 was applied to the project's Supabase database by the repo
> owner. Migration 013 was written but explicitly NOT applied. Treat any
> "is migration N live" question as requiring a fresh check — `git log`
> and this file are not a substitute for asking or checking the live
> database when a task depends on it.

## Where NOT to look first

Do not begin ordinary task orientation by reading the ~99 root-level
`.md` files. Most are historical operational records (implementation
reports, commissioning reports, remediation reports) describing *completed
past work*, not current authoritative architecture. See
[NAVIGATION.md](NAVIGATION.md) and
[ROOT_DOC_INVENTORY.json](ROOT_DOC_INVENTORY.json) before reading any of
them.
