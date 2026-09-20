-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 015: Proposal Intelligence — durable PI-1 foundation
-- (PI-1.1 hardening: cross-bid integrity + atomic bundle persistence)
-- ═══════════════════════════════════════════════════════════════════════════
-- Additive only. Does not modify migrations 001-014, does not touch
-- bids/requirements/analysis_runs/analysis_results/section_reviews columns,
-- does not backfill, does not change any existing policy or GRANT.
--
-- Per this repo's existing convention (migrations 001-014), this file is
-- NOT auto-applied by any code path and is NOT executed as part of this
-- authorization. Apply it manually via the Supabase SQL editor / dashboard,
-- after separate review, the same way migrations 004-014 were applied.
-- Migration 013 (Section Analyzer) remains unapplied and is not a
-- dependency of this one; migration 014 (model_usage_events) is a
-- separate telemetry migration and is also not a dependency.
--
-- Because this migration has never been applied live, PI-1.1 hardens it
-- IN PLACE rather than adding a migration 016 to repair an unapplied one
-- -- there is no live schema drift to reconcile.
--
-- ── Why these tables exist ───────────────────────────────────────────────
-- CHECK-stage Proposal Alignment (analyst.py's analyze_proposal_alignment/
-- analyze_proposal_alignment_package) currently produces a rich result --
-- requirement coverage, findings, mandatory failures, an executive
-- narrative -- that lives ONLY in Streamlit st.session_state. It is lost
-- on session end and cannot be reopened, compared across proposal
-- revisions, or reconciled against a later procurement-truth change. This
-- migration gives that same analytical engine (NO new LLM call, NO prompt/
-- schema/scoring change -- see proposal_intelligence.py's adapter) a
-- durable, immutable, provenance-aware home: "Proposal Intelligence" --
-- what the proposal actually says, demonstrates, covers, contradicts,
-- fails to evidence, or omits relative to the procurement. It is advisory
-- intelligence, exactly like Fast Analysis's raw snapshot and Section
-- Analyzer's reviews -- never canonical procurement truth, never silently
-- authoritative merely because it is persisted.
--
-- Four tables, in dependency order:
--
--   1. proposal_package_snapshots -- an immutable identity for the EXACT
--      proposal package a run was analyzed against. package_digest folds
--      in every analysis-relevant file identity (file_id/content_hash),
--      inclusion state, and role, computed over the FULL SUBMITTED
--      manifest (not just the analyzer's included-file subset) -- see
--      proposal_intelligence.py's compute_package_digest() docstring for
--      the exact canonicalization and for why "excluded file present" and
--      "file never supplied" are deliberately different snapshots (PI-1.1
--      instruction 6). `manifest` stores the FULL submitted package's
--      report-safe per-file fields (extractor.build_report_manifest()'s
--      shape, covering included AND excluded/duplicate/rejected/
--      unsupported files) -- never raw extracted proposal text, matching
--      Fast Analysis's raw-snapshot precedent of never storing prompt/
--      response content redundantly. get_or_create_proposal_package_
--      snapshot() below is the only supported way to create one --
--      concurrency-safe get-or-create (PI-1.1 instruction 4).
--
--   2. proposal_intelligence_runs -- one immutable row per Proposal
--      Alignment execution, tied to BOTH an exact package snapshot AND an
--      exact procurement_revision/procurement_truth_status (the same
--      based_on_procurement_revision/based_on_procurement_truth_status
--      stamping pattern section_reviews already established), enforced by
--      a composite foreign key against the snapshot's OWN bid_id (see
--      "Cross-bid integrity" below) -- never just a same-table bid_id
--      column trusted on faith. status is COMPLETE/INCOMPLETE/FAILED,
--      mirroring the analyzer's own existing status vocabulary
--      ("complete"/"incomplete") plus FAILED for a provider/model
--      exception with no usable result at all. analysis_version is
--      proposal_intelligence.py's own PI analytical-contract version (NOT
--      the model name) -- see its module docstring. legacy_result
--      preserves the analyzer's existing overall_score/recommendation/
--      executive_summary/strengths/next_steps for backward-compatible
--      CHECK rendering; PI-1 does NOT promote a "proposal quality score"
--      into a first-class column of the new domain. started_at/
--      completed_at are supplied explicitly by the caller (PI-1.1
--      instruction 7) -- started_at is captured by the application BEFORE
--      invoking the analyzer, not defaulted at INSERT time (which would
--      be after analysis already ran).
--
--   3. proposal_requirement_assessments -- one durable row per procurement
--      requirement the run assessed, normalizing analyst.py's EXISTING
--      requirement_coverage vocabulary (Fully Addressed/Partially
--      Addressed/Not Addressed/Cannot Assess) rather than inventing a
--      second one -- see proposal_intelligence.py's adapter for the exact,
--      documented mapping. Cross-bid integrity enforced against the
--      OWNING run's bid_id, not trusted independently.
--
--   4. proposal_intelligence_findings -- cross-cutting/requirement-related
--      findings normalized from the analyzer's existing findings/
--      mandatory_failures/unresolved_items into the bounded finding_type
--      taxonomy in proposal_intelligence.py (REQUIREMENT_COVERAGE,
--      MISSING_REQUIREMENT, WEAK_EVIDENCE, UNSUPPORTED_CLAIM,
--      CONTRADICTION, RESPONSE_GUIDELINE_GAP, SUBMISSION_ARTIFACT_GAP,
--      INTERNAL_INCONSISTENCY, DELIVERY_COMMITMENT, COMMERCIAL_EXPOSURE,
--      OTHER). Rows are immutable outputs of one run -- no mutable
--      workflow/status management around findings in PI-1. Cross-bid
--      integrity enforced against the OWNING run's bid_id.
--
-- All four tables key off bid_id directly (not organization_id) -- the
-- same established principle as every bid-owned child table since
-- migration 008: RLS is inherited transitively through can_access_bid.
--
-- ── Cross-bid integrity (PI-1.1 instruction 2) ───────────────────────────
-- A plain `bid_id bigint references bids(id)` column on each child table,
-- independent of its parent-row FK, PROVES NOTHING about consistency
-- between the two -- application code could (accidentally or via a bug)
-- insert an assessment for bid A that points at a run actually owned by
-- bid B, and the database would silently accept it. Every child table
-- here therefore carries a UNIQUE (id, bid_id) constraint on its parent,
-- and every reference to that parent is a COMPOSITE foreign key against
-- BOTH columns together -- not a second, independent, unenforced bid_id
-- FK. This makes "run for bid A referencing a snapshot from bid B" (and
-- the equivalent for assessments/findings) a constraint the database
-- itself rejects, not merely an application-level convention.
--
-- ── Atomic bundle persistence (PI-1.1 instruction 3) ─────────────────────
-- create_proposal_intelligence_bundle() below inserts one run plus all of
-- its assessment and finding rows inside a single function invocation --
-- a PL/pgSQL function body executes as one implicit transaction, so any
-- failure partway through (a constraint violation, a malformed payload)
-- rolls back everything the function did, including the run row already
-- inserted. There is no code path where a run can exist with partially-
-- inserted or missing assessments/findings. The function trusts bid_id
-- from the run payload ONLY -- every assessment/finding row it inserts is
-- forced to that same bid_id, never whatever (possibly wrong) bid_id a
-- caller might have included in an individual assessment/finding payload,
-- closing off cross-bid injection even before the composite FK would
-- catch it.
--
-- ── RLS: deliberately stricter than section_reviews ──────────────────────
-- section_reviews (migration 013) grants authenticated INSERT because its
-- review is created by an authenticated user's own in-session action. PI-1
-- is model-generated intelligence explicitly required (this phase's own
-- authorization) to be written ONLY by privileged, authorization-boundary-
-- checked server code (tenancy.py's *_for_organization wrappers, which
-- call require_bid_access() before ever reaching database.py's service-
-- role client) -- never directly by client-issued INSERT/UPDATE/DELETE.
-- All four tables therefore get an authenticated SELECT policy (transitive
-- bid ownership, same as every other bid-owned child table) but NO
-- authenticated INSERT/UPDATE/DELETE policy at all -- mirroring migration
-- 014's model_usage_events precedent.
--
-- PI-1.1 correction (instruction 11): the write protection here is RLS
-- ENABLED plus the ABSENCE OF A WRITE POLICY for the authenticated/anon
-- roles -- when row-level security is enabled on a table and no policy
-- grants a given command to a given role, Postgres denies that command
-- for that role outright, regardless of the table's own GRANT privileges.
-- This is NOT "protected by the absence of a table GRANT" (a different,
-- separately-configurable Postgres mechanism this migration does not
-- rely on or alter) -- RLS is the actual, sole enforcement boundary here,
-- and it fails closed: an authenticated client literally cannot issue an
-- INSERT/UPDATE/DELETE against these tables that Postgres will accept,
-- however that role's table-level GRANTs happen to be configured.
-- service_role bypasses row level security entirely by Postgres's own
-- definition of that role, which is how the privileged RPCs below (and
-- database.py's direct service-role client) can write at all.
-- ═══════════════════════════════════════════════════════════════════════════

create table if not exists proposal_package_snapshots (
    id                  bigserial primary key,
    bid_id              bigint not null references bids(id) on delete cascade,
    package_version     integer not null,
    package_digest      text not null,
    manifest            jsonb not null default '[]'::jsonb,
    created_by_user_id  uuid references auth.users(id),
    created_at          timestamptz not null default now(),
    unique (bid_id, package_digest),
    unique (bid_id, package_version),
    -- Lets every downstream child table enforce "my bid_id matches my
    -- parent's bid_id" via a composite FK against this pair.
    unique (id, bid_id)
);

create index if not exists idx_proposal_package_snapshots_bid
    on proposal_package_snapshots (bid_id, package_version desc);

create table if not exists proposal_intelligence_runs (
    id                                  bigserial primary key,
    bid_id                              bigint not null references bids(id) on delete cascade,
    proposal_package_snapshot_id        bigint not null,

    based_on_procurement_revision       int,
    based_on_procurement_truth_status   text,

    analysis_version                    text not null,
    status                              text not null
                                         check (status in ('COMPLETE', 'INCOMPLETE', 'FAILED')),
    failure_reason                      text,

    coverage_metadata                   jsonb,
    legacy_result                       jsonb,

    -- Supplied explicitly by the application, captured BEFORE the
    -- analyzer is invoked (PI-1.1 instruction 7) -- never defaulted here,
    -- since a default fires at INSERT time, which is after analysis
    -- already completed or failed. `not null default now()` remains only
    -- as a safety net against a caller that forgets to pass one; the
    -- application must always pass it explicitly.
    started_at                          timestamptz not null default now(),
    completed_at                        timestamptz,
    created_by_user_id                  uuid references auth.users(id),
    created_at                          timestamptz not null default now(),

    unique (id, bid_id),
    -- Cross-bid integrity: this run's snapshot must be a snapshot that
    -- ACTUALLY belongs to this run's own bid_id -- not merely any
    -- existing snapshot id. Replaces a plain single-column FK to
    -- proposal_package_snapshots(id), which could not express this.
    foreign key (proposal_package_snapshot_id, bid_id)
        references proposal_package_snapshots (id, bid_id) on delete cascade
);

create index if not exists idx_proposal_intelligence_runs_bid
    on proposal_intelligence_runs (bid_id, created_at desc);
create index if not exists idx_proposal_intelligence_runs_snapshot
    on proposal_intelligence_runs (proposal_package_snapshot_id);
-- Latest-USABLE-run lookup (status in COMPLETE/INCOMPLETE) is a common,
-- latency-sensitive query (CHECK reload) -- a partial index keeps it cheap
-- without indexing FAILED rows that query never matches.
create index if not exists idx_proposal_intelligence_runs_bid_usable
    on proposal_intelligence_runs (bid_id, created_at desc)
    where status in ('COMPLETE', 'INCOMPLETE');

create table if not exists proposal_requirement_assessments (
    id                          bigserial primary key,
    run_id                      bigint not null,
    bid_id                      bigint not null references bids(id) on delete cascade,

    requirement_id              bigint references requirements(id) on delete set null,
    req_id                      text,
    category                    text,
    description                 text,

    assessment_status           text not null
                                 check (assessment_status in
                                     ('Fully Addressed', 'Partially Addressed',
                                      'Not Addressed', 'Cannot Assess')),
    confidence                  text,
    explanation                 text,

    proposal_source_refs        jsonb not null default '[]'::jsonb,
    procurement_source_refs     jsonb not null default '[]'::jsonb,
    evidence_strength           text,

    created_at                  timestamptz not null default now(),

    -- Cross-bid integrity: this assessment's run must be a run that
    -- ACTUALLY belongs to this assessment's own bid_id.
    foreign key (run_id, bid_id)
        references proposal_intelligence_runs (id, bid_id) on delete cascade
);

create index if not exists idx_proposal_requirement_assessments_run
    on proposal_requirement_assessments (run_id);
create index if not exists idx_proposal_requirement_assessments_bid
    on proposal_requirement_assessments (bid_id);
create index if not exists idx_proposal_requirement_assessments_requirement
    on proposal_requirement_assessments (requirement_id);

create table if not exists proposal_intelligence_findings (
    id                          bigserial primary key,
    run_id                      bigint not null,
    bid_id                      bigint not null references bids(id) on delete cascade,

    finding_type                text not null
                                 check (finding_type in
                                     ('REQUIREMENT_COVERAGE', 'MISSING_REQUIREMENT', 'WEAK_EVIDENCE',
                                      'UNSUPPORTED_CLAIM', 'CONTRADICTION', 'RESPONSE_GUIDELINE_GAP',
                                      'SUBMISSION_ARTIFACT_GAP', 'INTERNAL_INCONSISTENCY',
                                      'DELIVERY_COMMITMENT', 'COMMERCIAL_EXPOSURE', 'OTHER')),
    severity                    text,

    title                       text not null,
    message                     text,
    explanation                 text,

    related_requirement_id      bigint references requirements(id) on delete set null,
    related_req_id              text,

    proposal_source_refs        jsonb not null default '[]'::jsonb,
    procurement_source_refs     jsonb not null default '[]'::jsonb,
    payload                     jsonb,

    created_at                  timestamptz not null default now(),

    -- Cross-bid integrity: this finding's run must be a run that ACTUALLY
    -- belongs to this finding's own bid_id.
    foreign key (run_id, bid_id)
        references proposal_intelligence_runs (id, bid_id) on delete cascade
);

create index if not exists idx_proposal_intelligence_findings_run
    on proposal_intelligence_findings (run_id);
create index if not exists idx_proposal_intelligence_findings_bid
    on proposal_intelligence_findings (bid_id, created_at desc);
create index if not exists idx_proposal_intelligence_findings_type
    on proposal_intelligence_findings (finding_type);

alter table proposal_package_snapshots enable row level security;
alter table proposal_intelligence_runs enable row level security;
alter table proposal_requirement_assessments enable row level security;
alter table proposal_intelligence_findings enable row level security;

create policy proposal_package_snapshots_select_bid_access
    on public.proposal_package_snapshots for select to authenticated
    using (public.can_access_bid(bid_id));

create policy proposal_intelligence_runs_select_bid_access
    on public.proposal_intelligence_runs for select to authenticated
    using (public.can_access_bid(bid_id));

create policy proposal_requirement_assessments_select_bid_access
    on public.proposal_requirement_assessments for select to authenticated
    using (public.can_access_bid(bid_id));

create policy proposal_intelligence_findings_select_bid_access
    on public.proposal_intelligence_findings for select to authenticated
    using (public.can_access_bid(bid_id));

-- Deliberately no INSERT/UPDATE/DELETE policy on any of the four tables --
-- see "RLS: deliberately stricter than section_reviews" above. Only
-- service_role (bypasses RLS by Postgres definition) may write, and in
-- practice only through the two functions below.

-- ═══════════════════════════════════════════════════════════════════════════
-- get_or_create_proposal_package_snapshot -- concurrency-safe snapshot
-- get-or-create (PI-1.1 instruction 4)
-- ═══════════════════════════════════════════════════════════════════════════
-- Two simultaneous requests for the SAME bid (whether the same package --
-- reuse -- or two DIFFERENT packages uploaded at nearly the same moment --
-- both need distinct, non-colliding package_version numbers) are
-- serialized by a transaction-scoped advisory lock keyed on the bid_id, a
-- lightweight, built-in Postgres mechanism (not a distributed-lock
-- service) that is automatically released at transaction end regardless
-- of success or failure. The (bid_id, package_version) and (bid_id,
-- package_digest) UNIQUE constraints on the table remain the final
-- authority -- even if this function were somehow bypassed, the database
-- itself would still reject a colliding version or a duplicate digest
-- row, never silently overwrite one.
create or replace function public.get_or_create_proposal_package_snapshot(
    p_bid_id bigint,
    p_package_digest text,
    p_manifest jsonb,
    p_created_by_user_id uuid default null
) returns public.proposal_package_snapshots
language plpgsql
security definer
set search_path = public
as $$
declare
    v_snapshot public.proposal_package_snapshots;
    v_next_version integer;
begin
    if p_bid_id is null or p_package_digest is null then
        raise exception 'get_or_create_proposal_package_snapshot: bid_id and package_digest are required';
    end if;

    perform pg_advisory_xact_lock(hashtext('proposal_package_snapshot:' || p_bid_id::text));

    select * into v_snapshot
    from public.proposal_package_snapshots
    where bid_id = p_bid_id and package_digest = p_package_digest;

    if found then
        return v_snapshot;
    end if;

    select coalesce(max(package_version), 0) + 1 into v_next_version
    from public.proposal_package_snapshots
    where bid_id = p_bid_id;

    insert into public.proposal_package_snapshots
        (bid_id, package_version, package_digest, manifest, created_by_user_id)
    values (p_bid_id, v_next_version, p_package_digest, coalesce(p_manifest, '[]'::jsonb), p_created_by_user_id)
    returning * into v_snapshot;

    return v_snapshot;
end;
$$;

revoke all on function public.get_or_create_proposal_package_snapshot(bigint, text, jsonb, uuid) from public;
revoke all on function public.get_or_create_proposal_package_snapshot(bigint, text, jsonb, uuid) from anon, authenticated;
grant execute on function public.get_or_create_proposal_package_snapshot(bigint, text, jsonb, uuid) to service_role;

-- ═══════════════════════════════════════════════════════════════════════════
-- create_proposal_intelligence_bundle -- atomic run + assessments + findings
-- (PI-1.1 instruction 3)
-- ═══════════════════════════════════════════════════════════════════════════
-- Inserts exactly one run, then every assessment and finding row, in a
-- single function invocation (one implicit transaction -- any exception
-- rolls back everything, including the run row). Never UPDATEs an
-- existing run, never DELETEs prior history, never touches requirements/
-- bids or any other table -- procurement truth is untouched. Table names
-- are fixed in the function body, never caller-supplied; only DATA is
-- parameterized via jsonb. Execution is restricted to service_role only.
create or replace function public.create_proposal_intelligence_bundle(
    p_run jsonb,
    p_assessments jsonb default '[]'::jsonb,
    p_findings jsonb default '[]'::jsonb
) returns public.proposal_intelligence_runs
language plpgsql
security definer
set search_path = public
as $$
declare
    v_run public.proposal_intelligence_runs;
    v_bid_id bigint;
    v_item jsonb;
begin
    v_bid_id := (p_run->>'bid_id')::bigint;
    if v_bid_id is null then
        raise exception 'create_proposal_intelligence_bundle: run.bid_id is required';
    end if;
    if p_run->>'proposal_package_snapshot_id' is null then
        raise exception 'create_proposal_intelligence_bundle: run.proposal_package_snapshot_id is required';
    end if;
    if p_run->>'analysis_version' is null or p_run->>'status' is null then
        raise exception 'create_proposal_intelligence_bundle: run.analysis_version and run.status are required';
    end if;

    insert into public.proposal_intelligence_runs (
        bid_id, proposal_package_snapshot_id,
        based_on_procurement_revision, based_on_procurement_truth_status,
        analysis_version, status, failure_reason,
        coverage_metadata, legacy_result,
        started_at, completed_at, created_by_user_id
    ) values (
        v_bid_id, (p_run->>'proposal_package_snapshot_id')::bigint,
        (p_run->>'based_on_procurement_revision')::int, p_run->>'based_on_procurement_truth_status',
        p_run->>'analysis_version', p_run->>'status', p_run->>'failure_reason',
        p_run->'coverage_metadata', p_run->'legacy_result',
        coalesce((p_run->>'started_at')::timestamptz, now()), (p_run->>'completed_at')::timestamptz,
        (p_run->>'created_by_user_id')::uuid
    ) returning * into v_run;

    -- bid_id is ALWAYS v_bid_id (the run's own), never re-read from an
    -- individual assessment/finding payload -- see "Atomic bundle
    -- persistence" above.
    for v_item in select * from jsonb_array_elements(coalesce(p_assessments, '[]'::jsonb))
    loop
        insert into public.proposal_requirement_assessments (
            run_id, bid_id, requirement_id, req_id, category, description,
            assessment_status, confidence, explanation,
            proposal_source_refs, procurement_source_refs, evidence_strength
        ) values (
            v_run.id, v_bid_id, (v_item->>'requirement_id')::bigint, v_item->>'req_id',
            v_item->>'category', v_item->>'description',
            v_item->>'assessment_status', v_item->>'confidence', v_item->>'explanation',
            coalesce(v_item->'proposal_source_refs', '[]'::jsonb),
            coalesce(v_item->'procurement_source_refs', '[]'::jsonb), v_item->>'evidence_strength'
        );
    end loop;

    for v_item in select * from jsonb_array_elements(coalesce(p_findings, '[]'::jsonb))
    loop
        insert into public.proposal_intelligence_findings (
            run_id, bid_id, finding_type, severity, title, message, explanation,
            related_requirement_id, related_req_id,
            proposal_source_refs, procurement_source_refs, payload
        ) values (
            v_run.id, v_bid_id, v_item->>'finding_type', v_item->>'severity',
            v_item->>'title', v_item->>'message', v_item->>'explanation',
            (v_item->>'related_requirement_id')::bigint, v_item->>'related_req_id',
            coalesce(v_item->'proposal_source_refs', '[]'::jsonb),
            coalesce(v_item->'procurement_source_refs', '[]'::jsonb), v_item->'payload'
        );
    end loop;

    return v_run;
end;
$$;

revoke all on function public.create_proposal_intelligence_bundle(jsonb, jsonb, jsonb) from public;
revoke all on function public.create_proposal_intelligence_bundle(jsonb, jsonb, jsonb) from anon, authenticated;
grant execute on function public.create_proposal_intelligence_bundle(jsonb, jsonb, jsonb) to service_role;
