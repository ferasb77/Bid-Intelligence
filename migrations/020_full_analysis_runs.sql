-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 020: Full Analysis runs & progress events — MA-2A
-- ═══════════════════════════════════════════════════════════════════════════
-- Does NOT modify migrations 001-019 (all applied migration FILES are left
-- byte-for-byte unchanged). It ALTERS two live CHECK constraints and one
-- live partial unique index on analysis_runs (dropping and re-adding them
-- with a strictly wider vocabulary), adds nullable columns, and adds two new
-- tables and three service-role-only functions. Existing FAST / DEEP_VERIFY
-- rows are untouched and remain valid under every new constraint.
--
-- Per this repo's established convention, this file is NOT auto-applied by
-- any code path and is NOT executed as part of MA-2A's implementation task.
-- Apply it manually via the Supabase SQL editor / dashboard, after
-- separate review; live commissioning is an explicitly separate task.
--
-- ── Why REUSE analysis_runs / analysis_results (not a parallel framework) ──
-- analysis_runs is already this repo's durable run-lifecycle record
-- (status, timestamps, failure reason/detail, telemetry summary, created_by,
-- bid-scoped RLS via can_access_bid -- migration 008) and already carries
-- the race-safe duplicate-start guard (idx_analysis_runs_one_active).
-- model_usage_events.analysis_run_id (migration 014) already FKs to it, so
-- Full Analysis provider-call telemetry links to a FULL run with zero new
-- telemetry schema. analysis_results already holds one immutable result
-- per run with bid-scoped RLS. What they could NOT represent, and what this
-- migration adds:
--   * analysis_mode 'FULL' (migration 004 constrained it to FAST/DEEP_VERIFY)
--   * run statuses RUNNING and PARTIAL (PARTIAL is TERMINAL: a Full Analysis
--     where >=1 specialist or the reconciliation stage failed; it must never
--     be reported as COMPLETE)
--   * an input fingerprint + source Fast Analysis run + last-progress time
--   * the structured FullAnalysisResult (analysis_results.full_analysis_result)
--   * durable per-specialist results written AS EACH SPECIALIST FINISHES
--     (full_analysis_specialist_results) -- so a process that dies mid-run
--     still leaves every already-finished specialist's work durable
--   * an append-only, strictly-sequenced execution event log
--     (full_analysis_events) -- execution STATE only, never model reasoning
--
-- ── Write discipline ─────────────────────────────────────────────────────
-- RLS: authenticated SELECT only (can_access_bid), no write policy on the
-- new tables -- identical to migrations 015/017/018. Every FULL-run write
-- goes through exactly three SECURITY DEFINER functions, revoked from
-- anon/authenticated, granted to service_role only:
--   start_full_analysis_run()      -- advisory-locked idempotent get-or-create
--   record_full_analysis_event()   -- sequenced event (+ specialist result)
--   finalize_full_analysis_run()   -- atomic result + terminal status + event
-- Triggers make the event log and specialist results append-only and a
-- terminal FULL run immutable, even for service_role.
-- ═══════════════════════════════════════════════════════════════════════════

-- ── 1. analysis_runs vocabulary ─────────────────────────────────────────────
alter table public.analysis_runs drop constraint if exists analysis_runs_analysis_mode_check;
alter table public.analysis_runs add constraint analysis_runs_analysis_mode_check
    check (analysis_mode in ('FAST', 'DEEP_VERIFY', 'FULL'));

alter table public.analysis_runs drop constraint if exists analysis_runs_status_check;
alter table public.analysis_runs add constraint analysis_runs_status_check
    check (status in ('QUEUED', 'PREPARING', 'ANALYZING', 'ASSEMBLING',
                      'RUNNING', 'COMPLETE', 'PARTIAL', 'FAILED'));

-- PARTIAL is terminal, so it must drop out of the one-active-run guard just
-- like COMPLETE/FAILED. Semantics for FAST are unchanged (FAST never writes
-- PARTIAL).
drop index if exists public.idx_analysis_runs_one_active;
create unique index if not exists idx_analysis_runs_one_active
    on public.analysis_runs (bid_id, analysis_mode)
    where status not in ('COMPLETE', 'PARTIAL', 'FAILED');

-- ── 2. analysis_runs FULL-run columns ───────────────────────────────────────
alter table public.analysis_runs
    add column if not exists input_fingerprint text,
    add column if not exists source_analysis_run_id bigint
        references public.analysis_runs(id) on delete set null,
    add column if not exists last_progress_at timestamptz;

alter table public.analysis_runs drop constraint if exists analysis_runs_full_requires_fingerprint;
alter table public.analysis_runs add constraint analysis_runs_full_requires_fingerprint
    check (analysis_mode <> 'FULL' or (input_fingerprint is not null
                                       and source_analysis_run_id is not null));

-- Composite key so child tables can prove same-bid ownership of their run.
alter table public.analysis_runs drop constraint if exists analysis_runs_id_bid_unique;
alter table public.analysis_runs add constraint analysis_runs_id_bid_unique unique (id, bid_id);

-- At most ONE completed Full Analysis per (bid, fingerprint): identical
-- input reuses the canonical completed result instead of re-running it.
create unique index if not exists idx_analysis_runs_full_complete_fingerprint
    on public.analysis_runs (bid_id, input_fingerprint)
    where analysis_mode = 'FULL' and status = 'COMPLETE';

create index if not exists idx_analysis_runs_full_fingerprint
    on public.analysis_runs (bid_id, input_fingerprint, created_at desc)
    where analysis_mode = 'FULL';

-- ── 3. analysis_results: the structured FullAnalysisResult ─────────────────
-- structured_intelligence stays NOT NULL (FAST consumers rely on it); a
-- FULL row writes a compact summary there and the full structured result
-- here. Never raw RFP text, never the canonical package (only its digests).
alter table public.analysis_results
    add column if not exists full_analysis_result jsonb;

-- ── 4. Durable per-specialist results ──────────────────────────────────────
create table if not exists public.full_analysis_specialist_results (
    id                   bigserial primary key,
    run_id               bigint not null,
    bid_id               bigint not null references public.bids(id) on delete cascade,
    specialist_id        text not null check (specialist_id in (
                             'PROCUREMENT_STRUCTURE', 'REQUIREMENTS_COMPLIANCE',
                             'EVALUATION_INTELLIGENCE', 'SCOPE_DELIVERABLES',
                             'COMMERCIAL_CONTRACTUAL', 'SCHEDULE_SUBMISSION')),
    status               text not null check (status in ('COMPLETE', 'FAILED', 'SKIPPED')),
    specialist_version   text not null,
    input_digest         text,
    duration_seconds     numeric,
    failure_reason       text,
    -- SpecialistResult.as_dict(): typed/validated findings, canonical ids,
    -- rejected findings, source refs, usage. References canonical objects by
    -- id only -- the canonical package itself is never copied here.
    result               jsonb not null,
    created_at           timestamptz not null default now(),
    unique (run_id, specialist_id),
    foreign key (run_id, bid_id) references public.analysis_runs (id, bid_id) on delete cascade
);
create index if not exists idx_full_analysis_specialist_results_bid
    on public.full_analysis_specialist_results (bid_id);

-- ── 5. Append-only execution event log ─────────────────────────────────────
create table if not exists public.full_analysis_events (
    id                   bigserial primary key,
    run_id               bigint not null,
    bid_id               bigint not null references public.bids(id) on delete cascade,
    sequence             integer not null,
    event_type           text not null check (event_type in (
                             'RUN_CREATED', 'CANONICAL_PACKAGE_READY',
                             'SPECIALIST_QUEUED', 'SPECIALIST_STARTED',
                             'SPECIALIST_COMPLETED', 'SPECIALIST_FAILED',
                             'RECONCILIATION_STARTED', 'RECONCILIATION_COMPLETED',
                             'RECONCILIATION_FAILED',
                             'RUN_COMPLETED', 'RUN_PARTIAL', 'RUN_FAILED')),
    specialist_id        text check (specialist_id is null or specialist_id in (
                             'PROCUREMENT_STRUCTURE', 'REQUIREMENTS_COMPLIANCE',
                             'EVALUATION_INTELLIGENCE', 'SCOPE_DELIVERABLES',
                             'COMMERCIAL_CONTRACTUAL', 'SCHEDULE_SUBMISSION')),
    status               text check (status is null or status in (
                             'QUEUED', 'RUNNING', 'COMPLETE', 'PARTIAL', 'FAILED', 'SKIPPED')),
    duration_seconds     numeric,
    failure_summary      text,
    -- Bounded execution metadata ONLY (counts, digests, versions). Never
    -- prompts, model output text, or reasoning.
    detail               jsonb not null default '{}'::jsonb,
    occurred_at          timestamptz not null default now(),
    unique (run_id, sequence),
    foreign key (run_id, bid_id) references public.analysis_runs (id, bid_id) on delete cascade,
    check (octet_length(detail::text) <= 4000)
);
create index if not exists idx_full_analysis_events_run
    on public.full_analysis_events (run_id, sequence);

-- ── 6. Immutability triggers (apply to service_role too) ───────────────────
create or replace function public.full_analysis_reject_mutation()
returns trigger language plpgsql set search_path = public as $$
begin
    raise exception '% rows are append-only', tg_table_name;
end;
$$;

drop trigger if exists trg_full_analysis_events_append_only on public.full_analysis_events;
create trigger trg_full_analysis_events_append_only
    before update or delete on public.full_analysis_events
    for each row execute function public.full_analysis_reject_mutation();

drop trigger if exists trg_full_analysis_specialist_results_write_once on public.full_analysis_specialist_results;
create trigger trg_full_analysis_specialist_results_write_once
    before update on public.full_analysis_specialist_results
    for each row execute function public.full_analysis_reject_mutation();

create or replace function public.analysis_runs_guard_full_run()
returns trigger language plpgsql set search_path = public as $$
begin
    if old.analysis_mode = 'FULL' then
        if old.status in ('COMPLETE', 'PARTIAL', 'FAILED') then
            raise exception 'full analysis run % is terminal (%) and immutable', old.id, old.status;
        end if;
        if new.analysis_mode is distinct from old.analysis_mode
           or new.bid_id is distinct from old.bid_id
           or new.input_fingerprint is distinct from old.input_fingerprint
           or new.source_analysis_run_id is distinct from old.source_analysis_run_id then
            raise exception 'full analysis run % identity columns are immutable', old.id;
        end if;
    elsif new.analysis_mode = 'FULL' then
        raise exception 'an existing run cannot be converted to FULL';
    end if;
    return new;
end;
$$;

drop trigger if exists trg_analysis_runs_guard_full_run on public.analysis_runs;
create trigger trg_analysis_runs_guard_full_run
    before update on public.analysis_runs
    for each row execute function public.analysis_runs_guard_full_run();

-- ── 7. RLS ──────────────────────────────────────────────────────────────────
alter table public.full_analysis_specialist_results enable row level security;
alter table public.full_analysis_events enable row level security;

create policy full_analysis_specialist_results_select_bid_access
    on public.full_analysis_specialist_results for select to authenticated
    using (public.can_access_bid(bid_id));
create policy full_analysis_events_select_bid_access
    on public.full_analysis_events for select to authenticated
    using (public.can_access_bid(bid_id));
-- Deliberately no INSERT/UPDATE/DELETE policy: only service_role writes,
-- and only through the functions below.

-- ═══════════════════════════════════════════════════════════════════════════
-- start_full_analysis_run -- idempotent, advisory-locked get-or-create
-- ═══════════════════════════════════════════════════════════════════════════
-- Returns jsonb {"outcome": <text>, "run": <analysis_runs row>}:
--   ACTIVE_RUN_EXISTS  a FULL run for this bid is QUEUED/RUNNING (any
--                      fingerprint) -- returned, never duplicated
--   REUSED_COMPLETE    a COMPLETE run with this exact fingerprint exists
--   EXISTING_FAILED /  the latest run with this fingerprint ended FAILED /
--   EXISTING_PARTIAL   PARTIAL and p_retry is false -- returned, NOT re-run
--                      (no silent retry of an expensive analysis)
--   CREATED            a new QUEUED run (plus its RUN_CREATED event)
create or replace function public.start_full_analysis_run(
    p_bid_id bigint,
    p_source_analysis_run_id bigint,
    p_input_fingerprint text,
    p_engine_version text,
    p_corpus_digest text default null,
    p_created_by_user_id uuid default null,
    p_retry boolean default false,
    p_detail jsonb default '{}'::jsonb
) returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_run public.analysis_runs;
    v_source public.analysis_runs;
begin
    if p_bid_id is null or p_source_analysis_run_id is null
       or p_input_fingerprint is null or p_engine_version is null then
        raise exception 'start_full_analysis_run: bid_id, source run, fingerprint and engine_version are required';
    end if;

    perform pg_advisory_xact_lock(hashtext('full_analysis_run:' || p_bid_id::text));

    select * into v_source from public.analysis_runs where id = p_source_analysis_run_id;
    if not found or v_source.bid_id <> p_bid_id or v_source.analysis_mode <> 'FAST'
       or v_source.status <> 'COMPLETE' then
        raise exception 'start_full_analysis_run: source run % is not a COMPLETE FAST run of bid %',
            p_source_analysis_run_id, p_bid_id;
    end if;

    select * into v_run from public.analysis_runs
    where bid_id = p_bid_id and analysis_mode = 'FULL'
      and status not in ('COMPLETE', 'PARTIAL', 'FAILED')
    order by created_at desc, id desc limit 1;
    if found then
        return jsonb_build_object('outcome', 'ACTIVE_RUN_EXISTS', 'run', to_jsonb(v_run));
    end if;

    select * into v_run from public.analysis_runs
    where bid_id = p_bid_id and analysis_mode = 'FULL' and status = 'COMPLETE'
      and input_fingerprint = p_input_fingerprint
    order by created_at desc, id desc limit 1;
    if found then
        return jsonb_build_object('outcome', 'REUSED_COMPLETE', 'run', to_jsonb(v_run));
    end if;

    if not coalesce(p_retry, false) then
        select * into v_run from public.analysis_runs
        where bid_id = p_bid_id and analysis_mode = 'FULL'
          and input_fingerprint = p_input_fingerprint
        order by created_at desc, id desc limit 1;
        if found then
            return jsonb_build_object('outcome', 'EXISTING_' || v_run.status, 'run', to_jsonb(v_run));
        end if;
    end if;

    insert into public.analysis_runs (
        bid_id, analysis_mode, engine_version, status, corpus_document_ids, corpus_digest,
        created_by_user_id, input_fingerprint, source_analysis_run_id, last_progress_at
    ) values (
        p_bid_id, 'FULL', p_engine_version, 'QUEUED', '[]'::jsonb, p_corpus_digest,
        p_created_by_user_id, p_input_fingerprint, p_source_analysis_run_id, now()
    ) returning * into v_run;

    insert into public.full_analysis_events (run_id, bid_id, sequence, event_type, status, detail)
    values (v_run.id, p_bid_id, 1, 'RUN_CREATED', 'QUEUED', coalesce(p_detail, '{}'::jsonb));

    return jsonb_build_object('outcome', 'CREATED', 'run', to_jsonb(v_run));
end;
$$;

revoke all on function public.start_full_analysis_run(bigint, bigint, text, text, text, uuid, boolean, jsonb) from public;
revoke all on function public.start_full_analysis_run(bigint, bigint, text, text, text, uuid, boolean, jsonb) from anon, authenticated;
grant execute on function public.start_full_analysis_run(bigint, bigint, text, text, text, uuid, boolean, jsonb) to service_role;

-- ═══════════════════════════════════════════════════════════════════════════
-- record_full_analysis_event -- one sequenced event (+ specialist result)
-- ═══════════════════════════════════════════════════════════════════════════
-- Sequence numbers are assigned here under a per-run advisory lock, so
-- concurrently-finishing specialist threads always produce a gap-free,
-- strictly increasing order. Refuses to write to a run that is not an
-- active FULL run of this bid (a late thread of a run already marked
-- FAILED/stuck can never append to or resurrect it). Terminal RUN_* events
-- are written only by finalize_full_analysis_run.
create or replace function public.record_full_analysis_event(
    p_run_id bigint,
    p_bid_id bigint,
    p_event_type text,
    p_specialist_id text default null,
    p_status text default null,
    p_duration_seconds numeric default null,
    p_failure_summary text default null,
    p_detail jsonb default '{}'::jsonb,
    p_specialist_result jsonb default null
) returns public.full_analysis_events
language plpgsql
security definer
set search_path = public
as $$
declare
    v_run public.analysis_runs;
    v_event public.full_analysis_events;
    v_seq integer;
begin
    if p_event_type in ('RUN_CREATED', 'RUN_COMPLETED', 'RUN_PARTIAL', 'RUN_FAILED') then
        raise exception 'record_full_analysis_event: % is written only by start/finalize', p_event_type;
    end if;

    perform pg_advisory_xact_lock(hashtext('full_analysis_events:' || p_run_id::text));

    select * into v_run from public.analysis_runs where id = p_run_id;
    if not found or v_run.bid_id <> p_bid_id or v_run.analysis_mode <> 'FULL' then
        raise exception 'record_full_analysis_event: run % is not a FULL run of bid %', p_run_id, p_bid_id;
    end if;
    if v_run.status in ('COMPLETE', 'PARTIAL', 'FAILED') then
        raise exception 'record_full_analysis_event: run % is terminal (%)', p_run_id, v_run.status;
    end if;

    select coalesce(max(sequence), 0) + 1 into v_seq
    from public.full_analysis_events where run_id = p_run_id;

    insert into public.full_analysis_events (
        run_id, bid_id, sequence, event_type, specialist_id, status,
        duration_seconds, failure_summary, detail
    ) values (
        p_run_id, p_bid_id, v_seq, p_event_type, p_specialist_id, p_status,
        p_duration_seconds, left(p_failure_summary, 500), coalesce(p_detail, '{}'::jsonb)
    ) returning * into v_event;

    if p_specialist_result is not null then
        if p_event_type not in ('SPECIALIST_COMPLETED', 'SPECIALIST_FAILED') or p_specialist_id is null then
            raise exception 'record_full_analysis_event: a specialist result may only accompany SPECIALIST_COMPLETED/FAILED';
        end if;
        insert into public.full_analysis_specialist_results (
            run_id, bid_id, specialist_id, status, specialist_version, input_digest,
            duration_seconds, failure_reason, result
        ) values (
            p_run_id, p_bid_id, p_specialist_id,
            case when p_event_type = 'SPECIALIST_COMPLETED' then 'COMPLETE' else 'FAILED' end,
            coalesce(p_specialist_result->>'specialist_version', 'unknown'),
            p_specialist_result->>'input_digest', p_duration_seconds,
            p_specialist_result->>'failure_reason', p_specialist_result
        );
    end if;

    update public.analysis_runs
    set status = 'RUNNING',
        started_at = coalesce(started_at, now()),
        last_progress_at = now()
    where id = p_run_id;

    return v_event;
end;
$$;

revoke all on function public.record_full_analysis_event(bigint, bigint, text, text, text, numeric, text, jsonb, jsonb) from public;
revoke all on function public.record_full_analysis_event(bigint, bigint, text, text, text, numeric, text, jsonb, jsonb) from anon, authenticated;
grant execute on function public.record_full_analysis_event(bigint, bigint, text, text, text, numeric, text, jsonb, jsonb) to service_role;

-- ═══════════════════════════════════════════════════════════════════════════
-- finalize_full_analysis_run -- atomic result + terminal status + event
-- ═══════════════════════════════════════════════════════════════════════════
-- COMPLETE is accepted only when the result itself says
-- completeness_status = 'COMPLETE' -- a run with a failed domain cannot
-- masquerade as complete. PARTIAL/COMPLETE require a result; FAILED may
-- carry one (e.g. reconciliation-only failure still has specialist work)
-- or none. Also the path for an explicit stuck-run FAILED marking.
create or replace function public.finalize_full_analysis_run(
    p_run_id bigint,
    p_bid_id bigint,
    p_status text,
    p_result jsonb default null,
    p_summary jsonb default '{}'::jsonb,
    p_failure_reason text default null,
    p_failure_detail jsonb default null,
    p_telemetry jsonb default null
) returns public.analysis_runs
language plpgsql
security definer
set search_path = public
as $$
declare
    v_run public.analysis_runs;
    v_seq integer;
begin
    if p_status not in ('COMPLETE', 'PARTIAL', 'FAILED') then
        raise exception 'finalize_full_analysis_run: invalid terminal status %', p_status;
    end if;
    if p_status in ('COMPLETE', 'PARTIAL') and p_result is null then
        raise exception 'finalize_full_analysis_run: % requires a result', p_status;
    end if;
    if p_status = 'COMPLETE' and coalesce(p_result->>'completeness_status', '') <> 'COMPLETE' then
        raise exception 'finalize_full_analysis_run: result is not COMPLETE; refusing to mark run COMPLETE';
    end if;

    perform pg_advisory_xact_lock(hashtext('full_analysis_events:' || p_run_id::text));

    select * into v_run from public.analysis_runs where id = p_run_id;
    if not found or v_run.bid_id <> p_bid_id or v_run.analysis_mode <> 'FULL' then
        raise exception 'finalize_full_analysis_run: run % is not a FULL run of bid %', p_run_id, p_bid_id;
    end if;
    if v_run.status in ('COMPLETE', 'PARTIAL', 'FAILED') then
        raise exception 'finalize_full_analysis_run: run % is already terminal (%)', p_run_id, v_run.status;
    end if;

    if p_result is not null then
        insert into public.analysis_results (run_id, bid_id, structured_intelligence, fact_origins,
                                             full_analysis_result)
        values (p_run_id, p_bid_id, coalesce(p_summary, '{}'::jsonb), '{}'::jsonb, p_result);
    end if;

    select coalesce(max(sequence), 0) + 1 into v_seq
    from public.full_analysis_events where run_id = p_run_id;
    insert into public.full_analysis_events (run_id, bid_id, sequence, event_type, status,
                                             failure_summary, detail)
    values (p_run_id, p_bid_id, v_seq,
            case p_status when 'COMPLETE' then 'RUN_COMPLETED'
                          when 'PARTIAL' then 'RUN_PARTIAL' else 'RUN_FAILED' end,
            p_status, left(p_failure_reason, 500), coalesce(p_summary, '{}'::jsonb));

    update public.analysis_runs
    set status = p_status,
        completed_at = case when p_status in ('COMPLETE', 'PARTIAL') then now() else completed_at end,
        failed_at = case when p_status = 'FAILED' then now() else failed_at end,
        failure_reason = coalesce(p_failure_reason, failure_reason),
        failure_detail = coalesce(p_failure_detail, failure_detail),
        telemetry = coalesce(p_telemetry, telemetry),
        started_at = coalesce(started_at, now()),
        last_progress_at = now()
    where id = p_run_id
    returning * into v_run;

    return v_run;
end;
$$;

revoke all on function public.finalize_full_analysis_run(bigint, bigint, text, jsonb, jsonb, text, jsonb, jsonb) from public;
revoke all on function public.finalize_full_analysis_run(bigint, bigint, text, jsonb, jsonb, text, jsonb, jsonb) from anon, authenticated;
grant execute on function public.finalize_full_analysis_run(bigint, bigint, text, jsonb, jsonb, text, jsonb, jsonb) to service_role;
