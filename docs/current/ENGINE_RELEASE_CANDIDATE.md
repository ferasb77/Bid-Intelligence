# Intelligence Engine — Beta Release Candidate (not deployed)

Branch `feature/intelligence-engine-rebuild`. Constraints: `ENGINE_REBUILD_CONSTRAINTS.md` (C1–C4, release-blocking).
Phoenix Beta is unchanged; migration 027 is not applied anywhere.

## 1. Architecture

```
bid source documents (tenant-scoped, require_bid_access)
  -> package.py      pages/sections/sheets with provenance + readability (READ/OCR/NEAR_EMPTY/UNREADABLE/MISSING)
  -> extraction.py   analyst A (Claude Opus 5.5) and analyst B (OpenAI, gated) extract independently,
                     in parallel units; every location must be accounted for
  -> verify.py       quotes located word-for-word; statement figures/e-mails/URLs must come from the quote
  -> register.py     reconciliation by verified source span: AGREED / DISPUTED / SINGLE_x / UNVERIFIED
  -> adjudicate.py   bounded adjudication (Opus); corrections accepted only with a verifying quote
  -> conflicts.py    amendments only with a verified authority quote; otherwise UNRESOLVED + clarification question
  -> reports.py      FAST and FULL composed from the register; omission ledger accounts for every entry;
                     model-written summary/analysis must cite entries and add no figures
  -> review.py       deterministic checks + independent final review; evidence-backed corrections only
  -> pipeline.py     computed verification status; FAIL CLOSED on any required-stage failure
  -> render.py       PDF; service.py / tenancy wrappers / pages/stage_engine.py (flag ENGINE_UI_ENABLED=1)
```

Fail-closed: a run is `FAILED` (no reports, never verified) when primary or independent extraction fails for any
page, a configured and authorized independent analyst fails, provider account errors occur (credit, quota, key,
permission), adjudication or conflict classification fails, an entry is unverified, the omission ledger has a
violation, or analysis/final review fail. Unauthorized/unconfigured independent analyst ⇒ `SINGLE_ANALYST`.
Verification labels are computed: `INDEPENDENTLY_VERIFIED` requires two different providers, both complete, and no
limitation.

## 2. Models and configuration

| Role | Model | Setting |
|---|---|---|
| Primary analyst, adjudicator, analysis writer, final reviewer | `claude-opus-5-5` | adaptive thinking, effort high, structured JSON output, streaming |
| Independent analyst | `ENGINE_OPENAI_MODEL` (not yet provided) | Responses API, strict json_schema, `store=False`; refuses client data unless `ENGINE_OPENAI_CLIENT_DATA_AUTHORIZED=yes` |

Environment: `ENGINE_ANTHROPIC_API_KEY` (dedicated key; falls back to the app key), `ENGINE_OPENAI_MODEL`,
`OPENAI_API_KEY`, `ENGINE_OPENAI_CLIENT_DATA_AUTHORIZED`, `ENGINE_OPENAI_PRICE_IN/OUT`, `ENGINE_CONCURRENCY` (4),
`ENGINE_UNIT_CHARS` (10000), `ENGINE_COST_LEDGER` (JSONL), `ENGINE_UI_ENABLED`.

## 3. Files and database

New: `engine/*`, `pages/stage_engine.py`, `migrations/027_engine_runs.sql`, `scripts/engine_run.py`,
`scripts/engine_validate.py`, `scripts/engine_rerender.py`, `scripts/engine_fetch_bid_documents.py` (prepared,
requires owner authorization), `tests/test_engine.py`, `tests/test_engine_constraints.py`,
`tests/engine_synthetic.py`, `tests/fixtures/engine_synth/`.
Changed (additive): `database.py` (engine_runs helpers, `upload_bytes_object`), `tenancy.py` (engine wrappers),
`app.py` (flag-gated nav entry), `tests/test_full_analysis_ma2a.py` (027 in the migration sequence).
Migration 027: `engine_runs` (tenant trigger: org must own the bid; bid/org immutable; result paths under
`{bid_id}/engine/`; RLS select via `can_access_bid`; no authenticated writes; one active run per bid).

## 4. Validation (Opus 5.5 primary; independent analyst not authorized for client data ⇒ SINGLE_ANALYST)

Human-written source-truth checklists (evaluation only; production code cannot import them — enforced by test).

| Case | Pages | Engine | Existing engine | Time | Cost |
|---|---|---|---|---|---|
| LAU (client, local copy) | 8 | 25/28 automated; 27/28 after manual review of checker false positives | 14/28 (1 misinterpretation) | 6.0 min | $1.95 |
| Synthetic ITB + annex + clarifications (unfamiliar) | 9 locations | 15/15 | n/a | 3.5 min | $0.82 |
| Public consulting-panel RFP (unfamiliar) | 15 | 21/22 | n/a | 11.2 min* | $2.44 |
| Public ICFR consulting RFP (unfamiliar) | 16 | 20/21 | n/a | 10.2 min* | $2.18 |
| Public software-development RFP (unfamiliar) | 26 | 21/22 (1 FULL-only) | n/a | 13.2 min* | $5.02 |

\* before parallel extraction units (LAU went from 11.4 to 6.0 min with them).
2B OPCO (189 pp.): not run — retrieval from live Phoenix storage awaits explicit owner authorization.
Total rebuild API spend to date: $15.88 (separate ledger `.engine_runs/cost_ledger.jsonl`).

## 5. Known limitations

- Independent dual-model verification has not run on any real document (OpenAI model ID, key and client-data
  authorization outstanding). All real-document reports are SINGLE_ANALYST.
- Missed: a contradiction inside a form template (TECH form vs instructions) and a section listed in a table of
  contents but absent from the package. Missing-referenced-content detection is not implemented.
- FAST is long on large packages (up to 9 pages) because every CRITICAL mandatory provision must appear.
- Some provisions are restated sentence-by-sentence (verbatim-adjacent), which is faithful but verbose.
- Run time 6–13 minutes per package; 189-page packages are untested for time and cost.
- Buyer research is wired in `service.py` but was not exercised in local validation runs.

## 6. Deployment (when separately authorized) and rollback

1. Apply `migrations/027_engine_runs.sql` via the Supabase dashboard (migration-commissioning checklist).
2. Deploy the branch image with `ENGINE_UI_ENABLED` unset (no user-visible change); verify.
3. Set `ENGINE_ANTHROPIC_API_KEY`; enable `ENGINE_UI_ENABLED=1` for the Beta tenant only.
Rollback: unset `ENGINE_UI_ENABLED` (page disappears; existing FAST/FULL untouched); previous image tag;
`engine_runs` is additive and may remain.
