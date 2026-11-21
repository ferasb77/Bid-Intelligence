-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 027: Intelligence engine runs (dual-analyst evidence register)
-- ═══════════════════════════════════════════════════════════════════════════
-- Additive only: one new table, one trigger function, RLS policies. No
-- existing table, function or row is modified.
--
-- NOT auto-applied by any code path. Apply manually via the Supabase SQL
-- editor after review and explicit deployment authorization
-- (docs/current/ENGINE_REBUILD_CONSTRAINTS.md C4). Until applied, the engine
-- service reports that persistence is unavailable and the existing FAST/FULL
-- workflow is unaffected.
--
-- Tenant isolation (constraint C1):
--   * every row carries bid_id AND organization_id; a trigger rejects any row
--     whose organization_id is not the bid's own organization, so a run can
--     never be attributed to another tenant;
--   * authenticated users may only SELECT rows of bids they can access
--     (can_access_bid, migration 008); there is no write policy -- writes come
--     from the server (service role) after tenancy.require_bid_access();
--   * the run's register, reports and PDFs are stored in the existing
--     bid-documents bucket under {bid_id}/engine/{run_id}/, the bid-scoped
--     prefix the bucket's existing policies already govern.
-- Nothing here creates a cross-tenant or global store of client content.
-- ═══════════════════════════════════════════════════════════════════════════

create table if not exists public.engine_runs (
    id                bigserial primary key,
    bid_id            bigint not null references public.bids(id) on delete cascade,
    organization_id   uuid   not null,
    status            text   not null default 'QUEUED'
                      check (status in ('QUEUED', 'RUNNING', 'COMPLETE', 'FAILED')),
    verification      text
                      check (verification is null or verification in
                             ('INDEPENDENTLY_VERIFIED', 'VERIFIED_WITH_LIMITATIONS', 'SINGLE_ANALYST',
                              'SYNTHETIC', 'FAILED')),
    engine_version    text   not null,
    package_hash      text   not null,
    documents         jsonb  not null default '[]'::jsonb,   -- manifest: names, sha256, upload time
    model_config      jsonb  not null default '{}'::jsonb,   -- models and settings of every role
    record            jsonb  not null default '{}'::jsonb,   -- stages, limitations, usage and cost
    result_path       text,                                  -- {bid_id}/engine/{id}/result.json
    fast_pdf_path     text,
    full_pdf_path     text,
    previous_run_id   bigint references public.engine_runs(id) on delete set null,
    failure_reason    text,
    created_by        text,
    created_at        timestamptz not null default now(),
    started_at        timestamptz,
    completed_at      timestamptz,
    last_progress_at  timestamptz
);

create index if not exists idx_engine_runs_bid on public.engine_runs (bid_id, created_at desc);
create unique index if not exists idx_engine_runs_one_active
    on public.engine_runs (bid_id) where status in ('QUEUED', 'RUNNING');

create or replace function public.engine_runs_enforce_tenant()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
    owner uuid;
begin
    select organization_id into owner from public.bids where id = new.bid_id;
    if owner is null or owner <> new.organization_id then
        raise exception 'engine_runs: organization % does not own bid %', new.organization_id, new.bid_id;
    end if;
    if tg_op = 'UPDATE' and (new.bid_id <> old.bid_id or new.organization_id <> old.organization_id) then
        raise exception 'engine_runs: bid and organization of a run are immutable';
    end if;
    if new.result_path is not null and new.result_path not like new.bid_id::text || '/engine/%' then
        raise exception 'engine_runs: storage path outside the bid prefix';
    end if;
    return new;
end;
$$;

drop trigger if exists trg_engine_runs_tenant on public.engine_runs;
create trigger trg_engine_runs_tenant
    before insert or update on public.engine_runs
    for each row execute function public.engine_runs_enforce_tenant();

alter table public.engine_runs enable row level security;
revoke all on table public.engine_runs from anon;
revoke insert, update, delete on table public.engine_runs from authenticated;
grant select on table public.engine_runs to authenticated;

drop policy if exists engine_runs_select on public.engine_runs;
create policy engine_runs_select on public.engine_runs
    for select to authenticated
    using (public.can_access_bid(bid_id));

revoke all on function public.engine_runs_enforce_tenant() from public, anon, authenticated;
