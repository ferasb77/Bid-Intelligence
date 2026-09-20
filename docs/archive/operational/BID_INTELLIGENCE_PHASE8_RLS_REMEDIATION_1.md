# Bid Intelligence — Phase 8 Remediation Package 1: Close Open RLS Tables

**Date:** 2026-09-15 (UTC)
**Scope:** Enable row level security (no policies, no tenancy, no behavior change) on the three tables Phase 8's audit found with RLS disabled. Nothing else.
**Baseline going in:** commit `f6a6d25d9d906a44c378ff465afbedfb54cfe158`, tag `bid-intelligence-generalized-v2`, engine `fast-analysis-v4`, regression baseline `1529 passed, 2 skipped`.
**Live project:** `whonalbdpbubaqhpzrnw` ("Bid-Intelligence") — confirmed by name/URL match against this app's `.env` before any change was made.

---

## 1. Preconditions (verified before any change)

| Precondition | Verified | Evidence |
|---|---|---|
| Application uses the Supabase service-role key server-side | TRUE | `database.py:get_client()` is the sole `create_client()` call site in the entire repo (repo-wide grep, excluding tests); always resolves `SUPABASE_SERVICE_KEY`. |
| No browser/client code receives the service-role key | TRUE | Bid Intelligence is a server-rendered Streamlit app; the key is read server-side into Python process memory and never returned to the browser. No second client-construction site exists anywhere (repo-wide grep for `create_client`, `SUPABASE_ANON_KEY`, `anon_key` returned zero real matches — a handful of `canon_key`/`canonical` false-positive substring hits in `extractor.py` were the only grep noise). |
| No current production path depends on anon/authenticated Supabase access to these three tables | TRUE | Same single-client-site finding — nothing in the app ever constructs an anon/authenticated client, so nothing could depend on it. |
| No RLS policies currently exist on these three tables | TRUE | Live query: `select count(*) from pg_policies where schemaname='public' and tablename in ('bid_briefs','bid_decisions','firm_profiles')` → 0 for each, re-confirmed immediately before applying the migration. |
| RLS is currently disabled on all three, live | TRUE | Live query against `pg_class.relrowsecurity`, re-confirmed immediately before applying the migration: all three `false`. |

All five preconditions held. Proceeded.

## 2. Migration

**Path:** `migrations/006_close_open_rls_tables.sql`
**Does not modify:** migrations 001–005 (confirmed via `git status --porcelain` on each of those five files, both before and after this package — empty in both cases).

**Full contents:**

```sql
-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 006: Close open RLS tables — Phase 8 remediation package 1
-- ═══════════════════════════════════════════════════════════════════════════
-- Additive only. Does not touch migrations 001-005, does not create any
-- policy, does not add any tenancy column, does not alter grants or table
-- ownership, does not use FORCE ROW LEVEL SECURITY, and does not modify any
-- row of data. Exactly one operation on exactly three tables.
--
-- Phase 8's live production-readiness audit (see
-- BID_INTELLIGENCE_PHASE8_PRODUCTION_READINESS_AUDIT.md) found that
-- `bid_briefs`, `bid_decisions`, and `firm_profiles` were the only three
-- application-facing tables in this project with row level security
-- disabled -- every other table (bids, requirements, tasks, documents,
-- document_versions, outline_sections, content_library, coaches,
-- clarifications, debriefs, deliverables, analysis_runs, analysis_results)
-- already has RLS enabled with zero policies, live-confirmed via direct
-- pg_catalog query and Supabase's own security advisor.
--
-- With RLS enabled and zero policies defined, these three tables become
-- fail-closed to the `anon` and `authenticated` Postgres roles: neither
-- role gets any implicit access, by Postgres's own RLS semantics (a table
-- with RLS enabled and no policy denies all rows to any role not exempted
-- from RLS). This is intentional and matches the eleven already-enabled
-- tables' current state -- these three should not have been any different.
--
-- This does not change current application behavior. The application
-- (database.py:get_client()) connects exclusively with the Supabase
-- service-role key, server-side only, and the service-role role bypasses
-- RLS by definition -- it is exempt regardless of whether RLS is enabled
-- or disabled, or whether any policy exists. No application code path
-- today uses an anon or authenticated key against any table, so there is
-- nothing for this change to break.
--
-- User/tenant-scoped RLS policies (so that an eventual authenticated,
-- non-service-role client can be safely introduced for browser-facing
-- reads) are explicitly NOT part of this migration -- they require the
-- organization/tenancy model that does not exist yet, and are deferred to
-- a later, separate remediation package (Phase 8 remediation package 2 and
-- beyond).
-- ═══════════════════════════════════════════════════════════════════════════

alter table public.bid_briefs    enable row level security;
alter table public.bid_decisions enable row level security;
alter table public.firm_profiles enable row level security;
```

## 3. Static Review (performed before applying)

| Check | Result |
|---|---|
| Touches exactly 3 tables | PASS — `bid_briefs`, `bid_decisions`, `firm_profiles`, one `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` each |
| No destructive DDL | PASS |
| No `DROP` | PASS |
| No data mutation | PASS — zero `INSERT`/`UPDATE`/`DELETE`/`TRUNCATE` statements |
| No policy creation | PASS — zero `CREATE POLICY` statements |
| No grant changes | PASS — zero `GRANT`/`REVOKE` statements |
| No `FORCE ROW LEVEL SECURITY` | PASS — the string appears only inside the explanatory comment, describing what was deliberately *not* done |
| Migrations 001–005 untouched | PASS — confirmed via `git status --porcelain` on each file, empty |

## 4. Regression Before Live Apply

Run immediately before applying migration 006 to the live project:

- `py_compile fast_analysis.py scripts/fast_analysis_report_adapter.py database.py analysis_service.py` → `COMPILE_OK`
- `git diff --check` → exit 0, clean
- `pytest tests/ -q` → **1529 passed, 2 skipped**, 126 warnings, 19 subtests passed, 78.64s — exactly the expected baseline, no new migration-specific tests were added (none were required or written for this package). No live LLM calls made.

## 5. Live Apply

Applied via Supabase's tracked migration mechanism (`apply_migration`, not a raw one-off `execute_sql`), against project `whonalbdpbubaqhpzrnw`. Migrations 001–005 were not re-run.

**Confirmed present in Supabase's tracked migration history** (`list_migrations`):

```
20260914141656  analysis_runs                (migration 004)
20260914150228  analysis_run_progress        (migration 005)
20260915065714  006_close_open_rls_tables    (migration 006 — new)
```

Migrations 004 and 005 are unchanged (same version identifiers, same names, still present).

## 6. Live Post-Remediation State

Live query (`pg_class.relrowsecurity` joined with a `pg_policies` count), re-run immediately after applying migration 006:

| Table | RLS enabled | RLS forced | Policy count |
|---|---|---|---|
| `bid_briefs` | **YES** | NO | **0** |
| `bid_decisions` | **YES** | NO | **0** |
| `firm_profiles` | **YES** | NO | **0** |

A second query across **all 16** `public` application tables confirms no side effects: all 16 now show `rls_enabled = true, policy_count = 0` — the 13 tables that were already correct are unchanged, and exactly the 3 target tables flipped from `false` to `true`. Nothing else moved.

## 7. Service-Role Application Smoke Test

Performed through the application's own code path (`database.py`'s existing functions — the same ones `app.py`/`pages/stage_understand.py` call), not raw SQL, and using only pre-existing real data (no throwaway rows created):

| Table | Method | Result |
|---|---|---|
| `bid_briefs` | `db.get_bid_brief(bid_id)` for bid_id 1, 3, 8, 81 | Real rows read successfully for bids 1, 3, 8 (`executive_summary` lengths 148/161/262 chars); bid 81 has a row with an empty summary (consistent with it never having had Fast Analysis run — expected, not an error). |
| `bid_decisions` | `db.get_bid_decision(bid_id)` for bid_id 1, 3, 8, 81 | Real row read successfully for bid 8 (`ai_recommendation = 'NEEDS MORE INFORMATION'`); bids 1, 3, 81 correctly return `None` (no decision recorded yet for those bids — expected, not an error). |
| `firm_profiles` | `db.get_firm_profile()` | Live table has 0 rows (`select count(*) from public.firm_profiles` → 0). The function returned successfully with the coded default profile (`company_name = 'Enable My Growth'`) — this proves the read path executes cleanly post-RLS-enable with no exception, but is the documented default-fallback behavior, not a live-row read, since no row exists to read. Per instruction 8's own allowance ("If safe existing rows do not exist for a table, test the application path deterministically instead"), also confirmed deterministically: `db.get_bid_brief(999999)` and `db.get_bid_decision(999999)` both correctly return `None` with no exception, for a bid_id that cannot exist. |

**`SERVICE-ROLE APPLICATION ACCESS: PASS`** — every read path exercised (two with real data, one via documented default-fallback plus a deterministic no-row check) completed successfully with zero exceptions, confirming the service-role client is unaffected by RLS now being enabled on these three tables, exactly as Postgres's RLS-bypass semantics for the service-role predict.

## 8. Fail-Closed Verification

Verified by SQL introspection rather than a live anon-key request: this environment has no anon/publishable Supabase key configured anywhere (only `SUPABASE_SERVICE_KEY` exists in `.env`/Streamlit secrets), and creating one or an anon-authenticated test session was explicitly out of scope for this package. Given that, the practical verification available is:

- `pg_class.relrowsecurity = true` for all three tables (§6), and
- `pg_policies` returns 0 rows for all three (§6),

which together are the complete, standard Postgres condition for "no role except one exempted from RLS (table owner, or a role with `BYPASSRLS`, which `service_role` has) can see or modify any row" — there is no policy that could grant `anon` or `authenticated` any access, and none was created. This is the intended state and matches the prior, unquestioned state of the other 13 already-RLS-enabled tables.

## 9. Security Advisor

Re-ran Supabase's own security advisor (`get_advisors`, type `security`) immediately after applying migration 006.

- **Prior `rls_disabled_in_public` ERROR-level findings for `bid_briefs`, `bid_decisions`, `firm_profiles` — CLEARED.** The advisor no longer reports this lint at all (0 findings of this type, down from 3).
- **Remaining findings (unrelated to this package, reported but not remediated per instruction 11):** `rls_enabled_no_policy`, INFO level, now count **16** (up from 13 — the three newly-closed tables joined the list, exactly as expected and intended, since "RLS enabled, no policy yet" is this package's deliberate end state, not a defect). No other advisor finding exists. This INFO-level lint is exactly what Phase 8's audit already characterized as the safe, fail-closed baseline — not something this package was asked to address, and it was not touched.

## 10. Regression After Live Apply

Re-ran the full suite after the live migration was applied, to confirm the live database change caused no test regression (some tests do exercise live Supabase connectivity):

- `pytest tests/ -q` → **1529 passed, 2 skipped**, 126 warnings, 19 subtests passed, 79.80s — identical to the pre-apply baseline.
- `git status --porcelain` → clean except the new `migrations/006_close_open_rls_tables.sql` file itself and the same pre-existing untracked generated PDFs from earlier phases; no other file touched.

---

## Summary

Exactly the three intended tables changed, exactly one operation each, zero policies, zero data touched, zero application code touched, zero test-count change, zero advisor findings introduced, and the three targeted ERROR-level advisor findings are gone.
