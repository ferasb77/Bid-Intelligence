-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 007: Authentication & tenancy foundation — Phase 8 remediation
-- package 2
-- ═══════════════════════════════════════════════════════════════════════════
-- Additive-and-backfill only. Does not touch migrations 001-006. Does not
-- create any RLS policy (that is Phase 8 remediation package 3's job --
-- this migration only enables RLS, fail-closed, on the two new tables,
-- exactly like migration 004/006 did for their own new/reopened tables).
-- Does not modify Fast Analysis, Deep Verify, or any existing procurement
-- data beyond the single, deterministic organization_id backfill below.
--
-- Establishes the minimum schema to represent:
--   Authenticated User (auth.users, Supabase Auth -- already provisioned,
--   currently 0 rows) -> Organization Membership -> Organization -> Bid,
-- with every existing bid-owned table continuing to inherit its tenant
-- boundary transitively through its existing `bid_id` foreign key to
-- `bids` -- no redundant `organization_id` column is added to any of
-- those tables. See BID_INTELLIGENCE_PHASE8_AUTH_TENANCY_FOUNDATION.md
-- §1/§13 for the full dependency map this design is based on (every
-- `bid_id`-referencing table confirmed live via information_schema).
--
-- ── 1. organizations ─────────────────────────────────────────────────────
create table if not exists public.organizations (
    id          uuid primary key default gen_random_uuid(),
    name        text not null,
    slug        text not null,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    constraint organizations_slug_unique unique (slug)
);

-- ── 2. organization_members ──────────────────────────────────────────────
-- user_id references auth.users directly -- Supabase Auth is the selected
-- (and already-provisioned) identity source for this project; no separate
-- application-level users table is introduced.
create table if not exists public.organization_members (
    organization_id uuid not null references public.organizations(id) on delete cascade,
    user_id         uuid not null references auth.users(id) on delete cascade,
    role            text not null default 'member'
                    check (role in ('owner', 'admin', 'member')),
    created_at      timestamptz not null default now(),
    primary key (organization_id, user_id)
);

create index if not exists idx_organization_members_user
    on public.organization_members (user_id);

-- ── 3. bids.organization_id (added nullable; made NOT NULL below, only ──
--       after every existing bid is confirmed backfilled)
alter table public.bids
    add column if not exists organization_id uuid references public.organizations(id);

create index if not exists idx_bids_organization
    on public.bids (organization_id);

-- ── 4. legacy organization + deterministic backfill ──────────────────────
-- No UUID is hardcoded here -- Postgres generates it (organizations.id's
-- own default), and every reference below goes through the unique,
-- deterministic slug instead. Safe to re-run: the insert no-ops via
-- ON CONFLICT, and the backfill UPDATE only ever touches rows that are
-- still NULL, so a second run of this migration (e.g. after a partial
-- earlier failure) finds nothing left to do.
insert into public.organizations (name, slug)
values ('Enable My Growth Internal', 'emg-internal')
on conflict (slug) do nothing;

update public.bids
set organization_id = (select id from public.organizations where slug = 'emg-internal')
where organization_id is null;

-- ── 5. make organization ownership mandatory, but only if the backfill ──
--       above actually reached every row -- fails the whole migration
--       (and, being inside the same script, rolls back everything above
--       with it) rather than silently leaving an orphaned bid.
do $$
declare
    orphaned_count bigint;
begin
    select count(*) into orphaned_count from public.bids where organization_id is null;
    if orphaned_count > 0 then
        raise exception
            'Migration 007 aborted: % bid(s) still have a NULL organization_id after backfill -- not making the column NOT NULL',
            orphaned_count;
    end if;
end $$;

alter table public.bids
    alter column organization_id set not null;

-- ── 6. firm_profiles: organization-owned (see decision in
--       BID_INTELLIGENCE_PHASE8_AUTH_TENANCY_FOUNDATION.md §14). The live
--       table has 0 rows (confirmed immediately before this migration was
--       written), so this is a pure additive, nullable column with no
--       backfill risk -- left nullable rather than forced NOT NULL,
--       because no authenticated/tenant-aware write path exists yet to
--       populate it; enforcing NOT NULL here would only be able to do so
--       by inventing a value, which this migration does not do.
alter table public.firm_profiles
    add column if not exists organization_id uuid references public.organizations(id);

-- ── 7. analysis_runs: add a distinct, nullable identity column rather ───
--       than reinterpreting the existing `created_by` text column (whose
--       historical values, e.g. 'app-ui', represent execution origin/
--       channel, not a user identity, and must not be treated as one).
--       `created_by` is left completely unchanged. This new column has no
--       backfill -- historical runs correctly remain unattributed to any
--       real user, because none exists for them.
alter table public.analysis_runs
    add column if not exists created_by_user_id uuid references auth.users(id) on delete set null;

-- ── 8. RLS on the two new tables: enabled, fail-closed, zero policies ────
--       (Phase 8 remediation package 3 will add real tenant policies to
--       these plus every other table -- this migration deliberately does
--       not, per its own explicit scope boundary.)
alter table public.organizations       enable row level security;
alter table public.organization_members enable row level security;
