-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 024: Platform Super Admin authority + administrative audit trail
-- (Super Admin MVP)
-- ═══════════════════════════════════════════════════════════════════════════
-- Additive only. Does not modify any existing table, policy, function, or
-- grant. Does not change tenant isolation or Storage.
--
-- 1. public.platform_admins -- the ONLY source of platform-level (cross-
--    organization) administrative authority. Deliberately separate from
--    public.organization_members: an organization 'owner'/'admin' role is
--    tenant-scoped and is NEVER evidence of platform authority.
--    Rows are created out-of-band by the platform owner (SQL, see the
--    Super Admin MVP report's bootstrap step). The Super Admin console has
--    no feature that writes this table, so no UI path can grant platform
--    authority -- including to oneself.
--
-- 2. public.platform_admin_audit_log -- append-only record of every
--    administrative action attempted through platform_admin.py (success,
--    denied, and error outcomes). Never stores passwords, tokens, setup
--    links, or keys.
--
-- Both tables: RLS enabled with ZERO policies (this codebase's
-- RLS-via-absence-of-policy pattern) and every privilege revoked from
-- anon/authenticated, so only the server-side service role can read or
-- write them. Browsers (anon key / user JWT through PostgREST) get nothing.
-- ═══════════════════════════════════════════════════════════════════════════

create table if not exists public.platform_admins (
    user_id     uuid primary key references auth.users(id) on delete cascade,
    granted_at  timestamptz not null default now(),
    granted_by  text not null,
    note        text
);

create table if not exists public.platform_admin_audit_log (
    id               bigserial primary key,
    occurred_at      timestamptz not null default now(),
    actor_user_id    uuid,
    actor_email      text,
    action           text not null,
    outcome          text not null check (outcome in ('success', 'denied', 'error')),
    target_user_id   uuid,
    target_email     text,
    organization_id  uuid,
    details          jsonb not null default '{}'::jsonb
);

create index if not exists idx_platform_admin_audit_log_occurred
    on public.platform_admin_audit_log (occurred_at desc);
create index if not exists idx_platform_admin_audit_log_target
    on public.platform_admin_audit_log (target_user_id);

-- ── Append-only enforcement (applies to every role, including service_role)
create or replace function public.platform_admin_audit_log_immutable()
returns trigger
language plpgsql
set search_path = public
as $$
begin
    raise exception 'platform_admin_audit_log is append-only (% rejected)', tg_op;
end;
$$;

drop trigger if exists platform_admin_audit_log_no_update_delete
    on public.platform_admin_audit_log;
create trigger platform_admin_audit_log_no_update_delete
    before update or delete on public.platform_admin_audit_log
    for each row execute function public.platform_admin_audit_log_immutable();

drop trigger if exists platform_admin_audit_log_no_truncate
    on public.platform_admin_audit_log;
create trigger platform_admin_audit_log_no_truncate
    before truncate on public.platform_admin_audit_log
    for each statement execute function public.platform_admin_audit_log_immutable();

revoke all on function public.platform_admin_audit_log_immutable() from public;

-- ── Fail-closed access: RLS on, zero policies, no browser-role privileges
alter table public.platform_admins          enable row level security;
alter table public.platform_admin_audit_log enable row level security;

revoke all on table public.platform_admins          from anon, authenticated;
revoke all on table public.platform_admin_audit_log from anon, authenticated;
revoke all on sequence public.platform_admin_audit_log_id_seq from anon, authenticated;

grant select, insert, update, delete on table public.platform_admins to service_role;
grant select, insert on table public.platform_admin_audit_log to service_role;
grant usage, select on sequence public.platform_admin_audit_log_id_seq to service_role;
