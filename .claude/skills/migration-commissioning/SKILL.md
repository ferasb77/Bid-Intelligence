---
name: migration-commissioning
description: >-
  Checklist for bringing one migrations/*.sql file live and verifying it,
  in this repo where migrations are applied manually via the Supabase
  dashboard, never by agent-executed DDL. Use this whenever a task needs
  to confirm or bring about live-database state for a migration, instead
  of re-deriving the procedure (repeated for migrations 004, 008, 014).
---

# Migration Commissioning

## Before assuming anything
- A migration **file** in `migrations/` is never evidence it is applied.
  Check the live database explicitly (e.g. a column-name probe query)
  before any task depends on its schema existing.
- Record what you found in `docs/current/SYSTEM_STATE.md`'s "LAST
  VERIFIED EXTERNAL STATE" note so the next task doesn't re-derive it.

## Applying
- This repo's convention: the repo owner applies DDL manually via the
  Supabase dashboard. Do not attempt to run DDL yourself (the
  `supabase-py` REST client cannot run it anyway, and there is no
  psycopg2 connection by default). If a migration needs to go live, say
  so and ask, rather than finding a workaround.

## Verifying, once live
- Confirm RLS is enabled and enumerate policies. This codebase's pattern
  for a service-role/tenant-scoped table is **RLS-via-absence-of-policy**
  (zero policies = anonymous/cross-org access denied by the absence of
  any grant, not by a predicate) — verify that's actually the case, don't
  assume it from the migration file's intent.
- Run one full synthetic round-trip: insert → read back and verify every
  field → delete → confirm zero rows remain. Do this **before** spending
  any real budget (API credits, production data) on the feature the
  migration supports.
- Clean up every synthetic row you created. Never leave test data behind
  in a live table.
