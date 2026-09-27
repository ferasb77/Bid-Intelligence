-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 022: Durable CHECK (proposal assurance) runs -- CHECK-2B
-- ═══════════════════════════════════════════════════════════════════════════
-- STATUS: APPLIED_AND_COMMISSIONED by CHECK-2B.1 (live durable-run
-- commissioning, project whonalbdpbubaqhpzrnw). Written by CHECK-2B, which
-- did not apply it. CHECK-2B.1's pre-application review against the live
-- schema and the Python payloads found no schema/payload mismatch; the ONLY
-- pre-application edit was this STATUS comment (no SQL changed). Immutable
-- from first application onward. No code path auto-applies it.
--
-- Does NOT modify migrations 001-021 (their files are byte-for-byte
-- unchanged). Like migration 020 it WIDENS one live CHECK constraint on
-- analysis_runs (adds the 'CHECK' analysis_mode -- every existing FAST /
-- DEEP_VERIFY / FULL row remains valid), adds one nullable column + two
-- constraints + two partial indexes to analysis_runs, one nullable column to
-- analysis_results, four new tables, one guard trigger and three
-- service_role-only functions.
--
-- ── Why REUSE analysis_runs / analysis_results (MA-2A precedent) ─────────
-- analysis_runs is already the durable run-lifecycle record (status,
-- timestamps, failure reason/detail, telemetry summary, created_by, bid-scoped
-- RLS via can_access_bid), already carries the race-safe one-active-run guard
-- idx_analysis_runs_one_active on (bid_id, analysis_mode) -- which gives CHECK
-- its own single active slot per bid with no new index -- and already carries
-- migration 020's input_fingerprint / source_analysis_run_id /
-- last_progress_at columns and its (id, bid_id) composite key.
-- model_usage_events.analysis_run_id (migration 014) already FKs to it, so a
-- CHECK run's provider calls link to the run with ZERO new telemetry schema
-- (workflow='check_coverage'). analysis_results already holds one immutable
-- result per run (unique run_id). What they cannot represent, added here:
--   * analysis_mode 'CHECK'
--   * the bidder side of the input identity: source_package_snapshot_id, a
--     COMPOSITE (id, bid_id) FK to proposal_package_snapshots (migration 015)
--     -- a CHECK run can never evaluate another bid's submission package
--   * the run-level CheckCoverageResult (analysis_results.check_coverage_result)
--   * one immutable row per final buyer-object adjudication
--     (check_adjudications) -- the CHECK-2A contract, structured lists kept
--     as jsonb arrays, never flattened
--   * a DB-enforced bidder-evidence link per cited evidence id
--     (check_adjudication_evidence): a composite FK into migration 021's
--     submission_evidence_items (bid_id, package_snapshot_id, evidence_id)
--     makes it IMPOSSIBLE for a persisted verdict to cite an unknown id, a
--     buyer-source id (REQ-* / CRIT-* / CE#), another bid's evidence or another
--     package snapshot's evidence -- the whole finalize transaction aborts
--   * per-semantic-batch diagnosis rows (check_semantic_batches): objects,
--     candidate evidence ids, structured model output, reconciled output,
--     provider stop_reason / parse_status, EFFECTIVE batch status
--   * an append-only, strictly-sequenced execution event log
--     (check_run_events) -- execution STATE and counts only
-- migration 020's full_analysis_events / full_analysis_specialist_results
-- were considered and rejected: their event_type / specialist_id CHECK
-- vocabularies and RPCs are FULL-specific (record_full_analysis_event refuses
-- any non-FULL run), and a CHECK adjudication is not a specialist result.
--
-- ── Write discipline (identical to migrations 015/017/018/020/021) ───────
-- RLS: authenticated SELECT only (can_access_bid), no write policy on any new
-- table. Every CHECK-run write goes through exactly three SECURITY DEFINER
-- functions, revoked from public/anon/authenticated, granted to service_role:
--   start_check_run()        -- advisory-locked idempotent get-or-create
--   record_check_run_event() -- sequenced event (+ semantic batch row)
--   finalize_check_run()     -- atomic result + adjudications + evidence links
--                               + terminal status + terminal event
-- Triggers keep events append-only, batch / adjudication / evidence rows
-- write-once, and a terminal CHECK run immutable -- even for service_role.
-- ═══════════════════════════════════════════════════════════════════════════

-- ── 1. analysis_runs vocabulary + CHECK identity ──────────────────────────
alter table public.analysis_runs drop constraint if exists analysis_runs_analysis_mode_check;
alter table public.analysis_runs add constraint analysis_runs_analysis_mode_check
    check (analysis_mode in ('FAST', 'DEEP_VERIFY', 'FULL', 'CHECK'));

alter table public.analysis_runs
    add column if not exists source_package_snapshot_id bigint;

-- The evaluated bidder package must be a snapshot of the SAME bid.
alter table public.analysis_runs drop constraint if exists analysis_runs_source_package_snapshot_fkey;
alter table public.analysis_runs add constraint analysis_runs_source_package_snapshot_fkey
    foreign key (source_package_snapshot_id, bid_id)
    references public.proposal_package_snapshots (id, bid_id) on delete cascade;

alter table public.analysis_runs drop constraint if exists analysis_runs_check_requires_identity;
alter table public.analysis_runs add constraint analysis_runs_check_requires_identity
    check (analysis_mode <> 'CHECK' or (input_fingerprint is not null
                                        and source_analysis_run_id is not null
                                        and source_package_snapshot_id is not null));

-- Composite key so CHECK child rows prove same-bid AND same-snapshot
-- ownership of their run.
alter table public.analysis_runs drop constraint if exists analysis_runs_id_bid_snapshot_unique;
alter table public.analysis_runs add constraint analysis_runs_id_bid_snapshot_unique
    unique (id, bid_id, source_package_snapshot_id);

-- At most ONE completed CHECK per (bid, fingerprint): identical semantic
-- input reuses the canonical completed adjudication instead of re-running it.
create unique index if not exists idx_analysis_runs_check_complete_fingerprint
    on public.analysis_runs (bid_id, input_fingerprint)
    where analysis_mode = 'CHECK' and status = 'COMPLETE';

create index if not exists idx_analysis_runs_check_fingerprint
    on public.analysis_runs (bid_id, input_fingerprint, created_at desc)
    where analysis_mode = 'CHECK';

-- ── 2. analysis_results: the run-level CheckCoverageResult ─────────────────
-- Counts, digests, versions, fingerprint inputs and the batch log. The
-- per-object adjudications live in check_adjudications (never duplicated).
alter table public.analysis_results
    add column if not exists check_coverage_result jsonb;

-- ── 3. Semantic batch diagnosis rows ───────────────────────────────────────
create table if not exists public.check_semantic_batches (
    id                      bigserial primary key,
    run_id                  bigint not null,
    bid_id                  bigint not null references public.bids(id) on delete cascade,
    package_snapshot_id     bigint not null,
    batch_id                text not null check (batch_id ~ '^B[0-9]{1,3}$'),
    domain                  text,
    buyer_object_ids        jsonb not null check (jsonb_typeof(buyer_object_ids) = 'array'),
    candidate_evidence_ids  jsonb not null check (jsonb_typeof(candidate_evidence_ids) = 'array'),
    alias_to_evidence       jsonb not null default '{}'::jsonb check (jsonb_typeof(alias_to_evidence) = 'object'),
    -- the model's STRUCTURED (parsed JSON) output, and the fail-closed
    -- reconciled per-object outcome. Never the prompt (prompt_sha256 only).
    structured_output       jsonb,
    reconciled_output       jsonb not null default '{}'::jsonb,
    provider                text,
    model                   text,
    stop_reason             text,
    parse_status            text,
    -- COMPLETE only when the provider finished normally, the output parsed
    -- completely and every object of the batch was adjudicated. A
    -- max_tokens stop is PARTIAL (usable rows survived) or FAILED (none).
    effective_status        text not null check (effective_status in ('COMPLETE', 'PARTIAL', 'FAILED')),
    failure_reason          text,
    input_tokens            integer,
    output_tokens           integer,
    latency_seconds         numeric,
    prompt_chars            integer,
    prompt_sha256           text,
    created_at              timestamptz not null default now(),
    unique (run_id, batch_id),
    foreign key (run_id, bid_id, package_snapshot_id)
        references public.analysis_runs (id, bid_id, source_package_snapshot_id) on delete cascade
);
create index if not exists idx_check_semantic_batches_bid on public.check_semantic_batches (bid_id);

-- ── 4. Append-only execution event log ─────────────────────────────────────
create table if not exists public.check_run_events (
    id                  bigserial primary key,
    run_id              bigint not null,
    bid_id              bigint not null references public.bids(id) on delete cascade,
    sequence            integer not null,
    event_type          text not null check (event_type in (
                            'RUN_CREATED', 'RUN_STARTED', 'BUYER_SCOPE_CLASSIFIED',
                            'CANDIDATE_RETRIEVAL_COMPLETE', 'DETERMINISTIC_ADJUDICATION_COMPLETE',
                            'SEMANTIC_BATCH_STARTED', 'SEMANTIC_BATCH_COMPLETED', 'SEMANTIC_BATCH_FAILED',
                            'EVIDENCE_ASSURANCE_COMPLETE',
                            'RUN_COMPLETED', 'RUN_PARTIAL', 'RUN_FAILED')),
    batch_id            text,
    status              text check (status is null or status in (
                            'QUEUED', 'RUNNING', 'COMPLETE', 'PARTIAL', 'FAILED')),
    duration_seconds    numeric,
    failure_summary     text,
    -- Bounded execution metadata ONLY (counts, digests, versions). Never
    -- prompts, model text, bidder prose or buyer wording.
    detail              jsonb not null default '{}'::jsonb,
    occurred_at         timestamptz not null default now(),
    unique (run_id, sequence),
    foreign key (run_id, bid_id) references public.analysis_runs (id, bid_id) on delete cascade,
    check (octet_length(detail::text) <= 4000)
);
create index if not exists idx_check_run_events_run on public.check_run_events (run_id, sequence);

-- ── 5. Final buyer-object adjudications (CHECK-2A contract) ────────────────
create table if not exists public.check_adjudications (
    id                          bigserial primary key,
    run_id                      bigint not null,
    bid_id                      bigint not null references public.bids(id) on delete cascade,
    package_snapshot_id         bigint not null,
    ordinal                     integer not null,          -- canonical buyer-object order
    buyer_object_id             text not null,
    buyer_object_type           text not null check (buyer_object_type in (
                                    'CANONICAL_REQUIREMENT', 'SCOPED_EVALUATION_CRITERION')),
    assurance_scope             text not null check (assurance_scope in (
                                    'SUBMISSION_RESPONSE_REQUIRED', 'SUBMISSION_EVIDENCE_REQUIRED',
                                    'EVALUATION_RESPONSE', 'PORTAL_NATIVE', 'POST_AWARD_OBLIGATION',
                                    'BUYER_PROCESS', 'INFORMATIONAL', 'DEEMED_BY_SUBMISSION',
                                    'NOT_APPLICABLE', 'HUMAN_REVIEW_REQUIRED')),
    scope_basis                 text not null default '',
    status                      text not null check (status in (
                                    'ADDRESSED', 'PARTIALLY_ADDRESSED', 'NOT_ADDRESSED', 'NOT_APPLICABLE',
                                    'NOT_VERIFIABLE_FROM_FILES', 'HUMAN_REVIEW_REQUIRED')),
    buyer_expectation           text not null,              -- verbatim buyer wording
    buyer_label                 text,
    buyer_category              text,
    expected_evidence_roles     jsonb not null default '[]'::jsonb check (jsonb_typeof(expected_evidence_roles) = 'array'),
    evidence_ids                jsonb not null default '[]'::jsonb check (jsonb_typeof(evidence_ids) = 'array'),
    -- per cited evidence id: submission_document_id / logical_artifact_id /
    -- document_role / kind / filename / locator (exact provenance relation)
    evidence_refs               jsonb not null default '[]'::jsonb check (jsonb_typeof(evidence_refs) = 'array'),
    evidence_summary            text not null default '',
    addressed_elements          jsonb not null default '[]'::jsonb check (jsonb_typeof(addressed_elements) = 'array'),
    missing_elements            jsonb not null default '[]'::jsonb check (jsonb_typeof(missing_elements) = 'array'),
    unverifiable_elements       jsonb not null default '[]'::jsonb check (jsonb_typeof(unverifiable_elements) = 'array'),
    ambiguity_or_review_reason  text,
    buyer_weight                text,
    buyer_weight_variants       jsonb not null default '[]'::jsonb check (jsonb_typeof(buyer_weight_variants) = 'array'),
    buyer_threshold             text,
    adjudication_method         text not null check (adjudication_method in (
                                    'SCOPE_GATE', 'DETERMINISTIC', 'MODEL', 'DERIVED_FROM_LINKED_REQUIREMENTS')),
    batch_id                    text,
    linked_requirement_ids      jsonb not null default '[]'::jsonb check (jsonb_typeof(linked_requirement_ids) = 'array'),
    search_basis                jsonb not null default '{}'::jsonb,
    validation                  jsonb not null default '{}'::jsonb,
    source_provenance           jsonb not null default '{}'::jsonb,
    applicability               text,
    applicability_condition     text,
    created_at                  timestamptz not null default now(),
    unique (run_id, buyer_object_id),
    unique (run_id, ordinal),
    foreign key (run_id, bid_id, package_snapshot_id)
        references public.analysis_runs (id, bid_id, source_package_snapshot_id) on delete cascade,
    -- CHECK-2A contract, enforced by the database as well:
    -- a positive verdict must cite bidder evidence
    check (status not in ('ADDRESSED', 'PARTIALLY_ADDRESSED') or jsonb_array_length(evidence_ids) > 0),
    -- a non-submission object is never a proposal gap
    check (assurance_scope not in ('POST_AWARD_OBLIGATION', 'BUYER_PROCESS', 'INFORMATIONAL',
                                   'DEEMED_BY_SUBMISSION', 'NOT_APPLICABLE') or status = 'NOT_APPLICABLE'),
    -- NOT_ADDRESSED only on a response-bearing scope
    check (status <> 'NOT_ADDRESSED' or assurance_scope in (
               'SUBMISSION_RESPONSE_REQUIRED', 'SUBMISSION_EVIDENCE_REQUIRED', 'EVALUATION_RESPONSE')),
    -- a model verdict names its semantic batch
    check (adjudication_method <> 'MODEL' or batch_id is not null)
);
create index if not exists idx_check_adjudications_bid on public.check_adjudications (bid_id, run_id);

-- ── 6. DB-enforced bidder-evidence links ────────────────────────────────────
create table if not exists public.check_adjudication_evidence (
    id                  bigserial primary key,
    run_id              bigint not null,
    bid_id              bigint not null references public.bids(id) on delete cascade,
    package_snapshot_id bigint not null,
    buyer_object_id     text not null,
    evidence_id         text not null,
    reference_kind      text not null check (reference_kind in ('VERDICT', 'ELEMENT')),
    unique (run_id, buyer_object_id, evidence_id),
    foreign key (run_id, buyer_object_id)
        references public.check_adjudications (run_id, buyer_object_id) on delete cascade,
    foreign key (run_id, bid_id, package_snapshot_id)
        references public.analysis_runs (id, bid_id, source_package_snapshot_id) on delete cascade,
    -- the cited id must be a REAL bidder evidence row of the SAME bid and the
    -- SAME package snapshot the run evaluated (migration 021)
    foreign key (bid_id, package_snapshot_id, evidence_id)
        references public.submission_evidence_items (bid_id, package_snapshot_id, evidence_id)
);
create index if not exists idx_check_adjudication_evidence_run on public.check_adjudication_evidence (run_id);

-- ── 7. Immutability (applies to service_role too) ──────────────────────────
create or replace function public.check_run_reject_mutation()
returns trigger language plpgsql set search_path = public as $$
begin
    raise exception '% rows are immutable', tg_table_name;
end;
$$;

drop trigger if exists trg_check_run_events_append_only on public.check_run_events;
create trigger trg_check_run_events_append_only
    before update or delete on public.check_run_events
    for each row execute function public.check_run_reject_mutation();

drop trigger if exists trg_check_semantic_batches_write_once on public.check_semantic_batches;
create trigger trg_check_semantic_batches_write_once
    before update on public.check_semantic_batches
    for each row execute function public.check_run_reject_mutation();

drop trigger if exists trg_check_adjudications_write_once on public.check_adjudications;
create trigger trg_check_adjudications_write_once
    before update on public.check_adjudications
    for each row execute function public.check_run_reject_mutation();

drop trigger if exists trg_check_adjudication_evidence_write_once on public.check_adjudication_evidence;
create trigger trg_check_adjudication_evidence_write_once
    before update on public.check_adjudication_evidence
    for each row execute function public.check_run_reject_mutation();

create or replace function public.analysis_runs_guard_check_run()
returns trigger language plpgsql set search_path = public as $$
begin
    if old.analysis_mode = 'CHECK' then
        if old.status in ('COMPLETE', 'PARTIAL', 'FAILED') then
            raise exception 'check run % is terminal (%) and immutable', old.id, old.status;
        end if;
        if new.analysis_mode is distinct from old.analysis_mode
           or new.bid_id is distinct from old.bid_id
           or new.input_fingerprint is distinct from old.input_fingerprint
           or new.source_analysis_run_id is distinct from old.source_analysis_run_id
           or new.source_package_snapshot_id is distinct from old.source_package_snapshot_id then
            raise exception 'check run % identity columns are immutable', old.id;
        end if;
    elsif new.analysis_mode = 'CHECK' then
        raise exception 'an existing run cannot be converted to CHECK';
    end if;
    return new;
end;
$$;

drop trigger if exists trg_analysis_runs_guard_check_run on public.analysis_runs;
create trigger trg_analysis_runs_guard_check_run
    before update on public.analysis_runs
    for each row execute function public.analysis_runs_guard_check_run();

-- ── 8. RLS ──────────────────────────────────────────────────────────────────
alter table public.check_semantic_batches enable row level security;
alter table public.check_run_events enable row level security;
alter table public.check_adjudications enable row level security;
alter table public.check_adjudication_evidence enable row level security;

create policy check_semantic_batches_select_bid_access
    on public.check_semantic_batches for select to authenticated
    using (public.can_access_bid(bid_id));
create policy check_run_events_select_bid_access
    on public.check_run_events for select to authenticated
    using (public.can_access_bid(bid_id));
create policy check_adjudications_select_bid_access
    on public.check_adjudications for select to authenticated
    using (public.can_access_bid(bid_id));
create policy check_adjudication_evidence_select_bid_access
    on public.check_adjudication_evidence for select to authenticated
    using (public.can_access_bid(bid_id));
-- Deliberately no INSERT/UPDATE/DELETE policy: only service_role writes,
-- and only through the functions below.

-- ═══════════════════════════════════════════════════════════════════════════
-- start_check_run -- idempotent, advisory-locked get-or-create
-- ═══════════════════════════════════════════════════════════════════════════
-- Returns jsonb {"outcome": <text>, "run": <analysis_runs row>}:
--   ACTIVE_RUN_EXISTS  a CHECK run for this bid is QUEUED/RUNNING (any
--                      fingerprint) -- returned, never duplicated
--   REUSED_COMPLETE    a COMPLETE CHECK run with this exact fingerprint exists
--                      (zero model spend)
--   EXISTING_FAILED /  the latest CHECK run with this fingerprint ended
--   EXISTING_PARTIAL   FAILED / PARTIAL and p_retry is false -- returned, NOT
--                      re-run (no silent retry of paid adjudication)
--   CREATED            a new QUEUED run (plus its RUN_CREATED event)
create or replace function public.start_check_run(
    p_bid_id bigint,
    p_source_analysis_run_id bigint,
    p_package_snapshot_id bigint,
    p_input_fingerprint text,
    p_engine_version text,
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
    if p_bid_id is null or p_source_analysis_run_id is null or p_package_snapshot_id is null
       or p_input_fingerprint is null or p_engine_version is null then
        raise exception 'start_check_run: bid_id, source run, package snapshot, fingerprint and engine_version are required';
    end if;

    perform pg_advisory_xact_lock(hashtext('check_run:' || p_bid_id::text));

    select * into v_source from public.analysis_runs where id = p_source_analysis_run_id;
    if not found or v_source.bid_id <> p_bid_id or v_source.analysis_mode <> 'FAST'
       or v_source.status <> 'COMPLETE' then
        raise exception 'start_check_run: source run % is not a COMPLETE FAST run of bid %',
            p_source_analysis_run_id, p_bid_id;
    end if;

    if not exists (select 1 from public.proposal_package_snapshots
                   where id = p_package_snapshot_id and bid_id = p_bid_id) then
        raise exception 'start_check_run: package snapshot % does not belong to bid %',
            p_package_snapshot_id, p_bid_id;
    end if;
    if not exists (select 1 from public.submission_documents
                   where bid_id = p_bid_id and package_snapshot_id = p_package_snapshot_id) then
        raise exception 'start_check_run: package snapshot % has no persisted submission evidence registry',
            p_package_snapshot_id;
    end if;

    select * into v_run from public.analysis_runs
    where bid_id = p_bid_id and analysis_mode = 'CHECK'
      and status not in ('COMPLETE', 'PARTIAL', 'FAILED')
    order by created_at desc, id desc limit 1;
    if found then
        return jsonb_build_object('outcome', 'ACTIVE_RUN_EXISTS', 'run', to_jsonb(v_run));
    end if;

    select * into v_run from public.analysis_runs
    where bid_id = p_bid_id and analysis_mode = 'CHECK' and status = 'COMPLETE'
      and input_fingerprint = p_input_fingerprint
    order by created_at desc, id desc limit 1;
    if found then
        return jsonb_build_object('outcome', 'REUSED_COMPLETE', 'run', to_jsonb(v_run));
    end if;

    if not coalesce(p_retry, false) then
        select * into v_run from public.analysis_runs
        where bid_id = p_bid_id and analysis_mode = 'CHECK'
          and input_fingerprint = p_input_fingerprint
        order by created_at desc, id desc limit 1;
        if found then
            return jsonb_build_object('outcome', 'EXISTING_' || v_run.status, 'run', to_jsonb(v_run));
        end if;
    end if;

    insert into public.analysis_runs (
        bid_id, analysis_mode, engine_version, status, corpus_document_ids, corpus_digest,
        created_by_user_id, input_fingerprint, source_analysis_run_id, source_package_snapshot_id,
        last_progress_at
    ) values (
        p_bid_id, 'CHECK', p_engine_version, 'QUEUED', '[]'::jsonb, v_source.corpus_digest,
        p_created_by_user_id, p_input_fingerprint, p_source_analysis_run_id, p_package_snapshot_id,
        now()
    ) returning * into v_run;

    insert into public.check_run_events (run_id, bid_id, sequence, event_type, status, detail)
    values (v_run.id, p_bid_id, 1, 'RUN_CREATED', 'QUEUED', coalesce(p_detail, '{}'::jsonb));

    return jsonb_build_object('outcome', 'CREATED', 'run', to_jsonb(v_run));
end;
$$;

revoke all on function public.start_check_run(bigint, bigint, bigint, text, text, uuid, boolean, jsonb) from public;
revoke all on function public.start_check_run(bigint, bigint, bigint, text, text, uuid, boolean, jsonb) from anon, authenticated;
grant execute on function public.start_check_run(bigint, bigint, bigint, text, text, uuid, boolean, jsonb) to service_role;

-- ═══════════════════════════════════════════════════════════════════════════
-- record_check_run_event -- one sequenced event (+ semantic batch row)
-- ═══════════════════════════════════════════════════════════════════════════
-- Sequence numbers are assigned here under a per-run advisory lock (gap-free,
-- strictly increasing). Refuses a run that is not an active CHECK run of this
-- bid, so a late thread of a run already marked FAILED/stuck can never append
-- to or resurrect it. Terminal RUN_* events are written only by
-- finalize_check_run. A batch row's candidate / aliased evidence ids must all
-- be bidder evidence of the run's own bid + package snapshot.
create or replace function public.record_check_run_event(
    p_run_id bigint,
    p_bid_id bigint,
    p_event_type text,
    p_batch_id text default null,
    p_status text default null,
    p_duration_seconds numeric default null,
    p_failure_summary text default null,
    p_detail jsonb default '{}'::jsonb,
    p_batch_result jsonb default null
) returns public.check_run_events
language plpgsql
security definer
set search_path = public
as $$
declare
    v_run public.analysis_runs;
    v_event public.check_run_events;
    v_seq integer;
    v_effective text;
begin
    if p_event_type in ('RUN_CREATED', 'RUN_COMPLETED', 'RUN_PARTIAL', 'RUN_FAILED') then
        raise exception 'record_check_run_event: % is written only by start/finalize', p_event_type;
    end if;

    perform pg_advisory_xact_lock(hashtext('check_run_events:' || p_run_id::text));

    select * into v_run from public.analysis_runs where id = p_run_id;
    if not found or v_run.bid_id <> p_bid_id or v_run.analysis_mode <> 'CHECK' then
        raise exception 'record_check_run_event: run % is not a CHECK run of bid %', p_run_id, p_bid_id;
    end if;
    if v_run.status in ('COMPLETE', 'PARTIAL', 'FAILED') then
        raise exception 'record_check_run_event: run % is terminal (%)', p_run_id, v_run.status;
    end if;

    select coalesce(max(sequence), 0) + 1 into v_seq
    from public.check_run_events where run_id = p_run_id;

    insert into public.check_run_events (
        run_id, bid_id, sequence, event_type, batch_id, status,
        duration_seconds, failure_summary, detail
    ) values (
        p_run_id, p_bid_id, v_seq, p_event_type, p_batch_id, p_status,
        p_duration_seconds, left(p_failure_summary, 500), coalesce(p_detail, '{}'::jsonb)
    ) returning * into v_event;

    if p_batch_result is not null then
        if p_event_type not in ('SEMANTIC_BATCH_COMPLETED', 'SEMANTIC_BATCH_FAILED') or p_batch_id is null then
            raise exception 'record_check_run_event: a batch result may only accompany SEMANTIC_BATCH_COMPLETED/FAILED';
        end if;
        v_effective := p_batch_result->>'effective_status';
        if (p_event_type = 'SEMANTIC_BATCH_FAILED') <> (v_effective = 'FAILED') then
            raise exception 'record_check_run_event: event % disagrees with effective batch status %',
                p_event_type, v_effective;
        end if;
        if exists (
            select 1 from jsonb_array_elements_text(coalesce(p_batch_result->'candidate_evidence_ids', '[]'::jsonb)) e(eid)
            where not exists (select 1 from public.submission_evidence_items s
                              where s.bid_id = p_bid_id and s.package_snapshot_id = v_run.source_package_snapshot_id
                                and s.evidence_id = e.eid))
           or exists (
            select 1 from jsonb_each_text(coalesce(p_batch_result->'alias_to_evidence', '{}'::jsonb)) a(alias, eid)
            where not exists (select 1 from public.submission_evidence_items s
                              where s.bid_id = p_bid_id and s.package_snapshot_id = v_run.source_package_snapshot_id
                                and s.evidence_id = a.eid)) then
            raise exception 'record_check_run_event: batch % references evidence outside bid % snapshot %',
                p_batch_id, p_bid_id, v_run.source_package_snapshot_id;
        end if;
        insert into public.check_semantic_batches (
            run_id, bid_id, package_snapshot_id, batch_id, domain, buyer_object_ids,
            candidate_evidence_ids, alias_to_evidence, structured_output, reconciled_output,
            provider, model, stop_reason, parse_status, effective_status, failure_reason,
            input_tokens, output_tokens, latency_seconds, prompt_chars, prompt_sha256
        ) values (
            p_run_id, p_bid_id, v_run.source_package_snapshot_id, p_batch_id, p_batch_result->>'domain',
            coalesce(p_batch_result->'buyer_object_ids', '[]'::jsonb),
            coalesce(p_batch_result->'candidate_evidence_ids', '[]'::jsonb),
            coalesce(p_batch_result->'alias_to_evidence', '{}'::jsonb),
            p_batch_result->'structured_output',
            coalesce(p_batch_result->'reconciled_output', '{}'::jsonb),
            p_batch_result->>'provider', p_batch_result->>'model',
            p_batch_result->>'stop_reason', p_batch_result->>'parse_status', v_effective,
            left(p_batch_result->>'failure_reason', 500),
            nullif(p_batch_result->>'input_tokens', '')::integer,
            nullif(p_batch_result->>'output_tokens', '')::integer,
            nullif(p_batch_result->>'latency_seconds', '')::numeric,
            nullif(p_batch_result->>'prompt_chars', '')::integer,
            p_batch_result->>'prompt_sha256'
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

revoke all on function public.record_check_run_event(bigint, bigint, text, text, text, numeric, text, jsonb, jsonb) from public;
revoke all on function public.record_check_run_event(bigint, bigint, text, text, text, numeric, text, jsonb, jsonb) from anon, authenticated;
grant execute on function public.record_check_run_event(bigint, bigint, text, text, text, numeric, text, jsonb, jsonb) to service_role;

-- ═══════════════════════════════════════════════════════════════════════════
-- finalize_check_run -- atomic result + adjudications + evidence links +
-- terminal status + terminal event (one transaction: all or nothing)
-- ═══════════════════════════════════════════════════════════════════════════
-- COMPLETE is accepted only when the result itself says run_integrity =
-- 'COMPLETE', every planned semantic batch has a persisted row, and NO batch
-- row has an effective_status other than COMPLETE -- a truncated or failed
-- batch can never masquerade as a complete CHECK. COMPLETE / PARTIAL require
-- the result and exactly one adjudication per buyer object. Every cited
-- evidence id (verdict AND element level) is inserted into
-- check_adjudication_evidence, whose FK into submission_evidence_items
-- aborts the whole call for an unknown / buyer-source / cross-bid /
-- cross-snapshot id: an invalid in-memory adjudication never becomes durable.
-- Also the path for an explicit stuck-run FAILED marking.
create or replace function public.finalize_check_run(
    p_run_id bigint,
    p_bid_id bigint,
    p_status text,
    p_result jsonb default null,
    p_adjudications jsonb default null,
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
    v_adj jsonb;
    v_ord bigint;
    v_oid text;
    v_eid text;
begin
    if p_status not in ('COMPLETE', 'PARTIAL', 'FAILED') then
        raise exception 'finalize_check_run: invalid terminal status %', p_status;
    end if;
    if p_status in ('COMPLETE', 'PARTIAL') and (p_result is null or p_adjudications is null
            or jsonb_typeof(p_adjudications) <> 'array' or jsonb_array_length(p_adjudications) = 0) then
        raise exception 'finalize_check_run: % requires a result and adjudications', p_status;
    end if;
    if p_status = 'COMPLETE' and coalesce(p_result->>'run_integrity', '') <> 'COMPLETE' then
        raise exception 'finalize_check_run: result is not COMPLETE; refusing to mark run COMPLETE';
    end if;
    if p_adjudications is not null and p_result is not null
       and jsonb_array_length(p_adjudications) <> coalesce((p_result->'object_counts'->>'total')::integer, -1) then
        raise exception 'finalize_check_run: % adjudications for % buyer objects',
            jsonb_array_length(p_adjudications), p_result->'object_counts'->>'total';
    end if;

    perform pg_advisory_xact_lock(hashtext('check_run_events:' || p_run_id::text));

    select * into v_run from public.analysis_runs where id = p_run_id;
    if not found or v_run.bid_id <> p_bid_id or v_run.analysis_mode <> 'CHECK' then
        raise exception 'finalize_check_run: run % is not a CHECK run of bid %', p_run_id, p_bid_id;
    end if;
    if v_run.status in ('COMPLETE', 'PARTIAL', 'FAILED') then
        raise exception 'finalize_check_run: run % is already terminal (%)', p_run_id, v_run.status;
    end if;

    if p_status = 'COMPLETE' then
        if exists (select 1 from public.check_semantic_batches
                   where run_id = p_run_id and effective_status <> 'COMPLETE') then
            raise exception 'finalize_check_run: a semantic batch is not COMPLETE; refusing to mark run COMPLETE';
        end if;
        if (select count(*) from public.check_semantic_batches where run_id = p_run_id)
           <> coalesce((p_result->>'planned_semantic_batches')::integer, -1) then
            raise exception 'finalize_check_run: persisted semantic batches do not match the plan; refusing COMPLETE';
        end if;
    end if;

    if p_result is not null then
        insert into public.analysis_results (run_id, bid_id, structured_intelligence, fact_origins,
                                             check_coverage_result)
        values (p_run_id, p_bid_id, coalesce(p_summary, '{}'::jsonb), '{}'::jsonb, p_result);
    end if;

    if p_adjudications is not null then
        for v_adj, v_ord in select a.value, a.ordinality
                            from jsonb_array_elements(p_adjudications) with ordinality a loop
            v_oid := v_adj->>'buyer_object_id';
            insert into public.check_adjudications (
                run_id, bid_id, package_snapshot_id, ordinal, buyer_object_id, buyer_object_type,
                assurance_scope, scope_basis, status, buyer_expectation, buyer_label, buyer_category,
                expected_evidence_roles, evidence_ids, evidence_refs, evidence_summary,
                addressed_elements, missing_elements, unverifiable_elements, ambiguity_or_review_reason,
                buyer_weight, buyer_weight_variants, buyer_threshold, adjudication_method, batch_id,
                linked_requirement_ids, search_basis, validation, source_provenance,
                applicability, applicability_condition
            ) values (
                p_run_id, p_bid_id, v_run.source_package_snapshot_id, v_ord::integer, v_oid,
                v_adj->>'buyer_object_type', v_adj->>'assurance_scope', coalesce(v_adj->>'scope_basis', ''),
                v_adj->>'status', v_adj->>'buyer_expectation', v_adj->>'buyer_label', v_adj->>'buyer_category',
                coalesce(v_adj->'expected_evidence_roles', '[]'::jsonb), coalesce(v_adj->'evidence_ids', '[]'::jsonb),
                coalesce(v_adj->'evidence_refs', '[]'::jsonb), coalesce(v_adj->>'evidence_summary', ''),
                coalesce(v_adj->'addressed_elements', '[]'::jsonb), coalesce(v_adj->'missing_elements', '[]'::jsonb),
                coalesce(v_adj->'unverifiable_elements', '[]'::jsonb), v_adj->>'ambiguity_or_review_reason',
                v_adj->>'buyer_weight', coalesce(v_adj->'buyer_weight_variants', '[]'::jsonb),
                v_adj->>'buyer_threshold', v_adj->>'deterministic_or_model', v_adj->>'batch_id',
                coalesce(v_adj->'linked_requirement_ids', '[]'::jsonb), coalesce(v_adj->'search_basis', '{}'::jsonb),
                coalesce(v_adj->'validation', '{}'::jsonb), coalesce(v_adj->'source_provenance', '{}'::jsonb),
                v_adj->>'applicability', v_adj->>'applicability_condition'
            );
            for v_eid in select jsonb_array_elements_text(coalesce(v_adj->'evidence_ids', '[]'::jsonb)) loop
                insert into public.check_adjudication_evidence
                    (run_id, bid_id, package_snapshot_id, buyer_object_id, evidence_id, reference_kind)
                values (p_run_id, p_bid_id, v_run.source_package_snapshot_id, v_oid, v_eid, 'VERDICT')
                on conflict (run_id, buyer_object_id, evidence_id) do nothing;
            end loop;
            for v_eid in
                select jsonb_array_elements_text(coalesce(el->'evidence_ids', '[]'::jsonb))
                from jsonb_array_elements(coalesce(v_adj->'addressed_elements', '[]'::jsonb)
                                          || coalesce(v_adj->'missing_elements', '[]'::jsonb)
                                          || coalesce(v_adj->'unverifiable_elements', '[]'::jsonb)) el
            loop
                insert into public.check_adjudication_evidence
                    (run_id, bid_id, package_snapshot_id, buyer_object_id, evidence_id, reference_kind)
                values (p_run_id, p_bid_id, v_run.source_package_snapshot_id, v_oid, v_eid, 'ELEMENT')
                on conflict (run_id, buyer_object_id, evidence_id) do nothing;
            end loop;
        end loop;
    end if;

    select coalesce(max(sequence), 0) + 1 into v_seq
    from public.check_run_events where run_id = p_run_id;
    insert into public.check_run_events (run_id, bid_id, sequence, event_type, status,
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

revoke all on function public.finalize_check_run(bigint, bigint, text, jsonb, jsonb, jsonb, text, jsonb, jsonb) from public;
revoke all on function public.finalize_check_run(bigint, bigint, text, jsonb, jsonb, jsonb, text, jsonb, jsonb) from anon, authenticated;
grant execute on function public.finalize_check_run(bigint, bigint, text, jsonb, jsonb, jsonb, text, jsonb, jsonb) to service_role;
