-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 013: Section Analyzer — durable requirement mapping & review history
-- ═══════════════════════════════════════════════════════════════════════════
-- Additive only. Does not modify migrations 001-012, does not touch
-- bids/requirements/outline_sections/analysis_runs/analysis_results columns,
-- does not backfill, does not change any existing policy or GRANT.
--
-- Per this repo's existing convention (migrations 001-012), this file is
-- NOT auto-applied by any code path and is NOT executed as part of this
-- authorization. Apply it manually via the Supabase SQL editor / dashboard,
-- after separate review, the same way migrations 004-012 were applied.
--
-- ── Why these tables exist ───────────────────────────────────────────────
-- The Section Analyzer (a formative, in-BUILD review of one proposal
-- section against its relevant procurement criteria) needs two things this
-- schema does not yet have:
--
--   1. A DURABLE section<->requirement mapping. The current "Mapped
--      Requirements" multiselect in pages/stage_build.py
--      (`st.multiselect(..., key=f"req_map_{section_id}")`) lives only in
--      Streamlit session state -- it resets on every browser session and
--      is never reproducible. A Section Analyzer review must be
--      reopenable later with the same mapping it was actually run against.
--
--   2. Persisted review history. A Section Analyzer result is proposal
--      intelligence a writer will want to reopen, compare, and rely on --
--      not transient chat output. It must be immutable (a later review
--      never overwrites an earlier one) and must record exactly what text
--      and what procurement basis it was run against, so staleness can be
--      detected later without guessing.
--
-- Both tables key off `bid_id` directly (not `organization_id` -- same
-- established principle as every other bid-owned child table since
-- migration 008: RLS is inherited transitively through `can_access_bid`,
-- so no `organization_id` column is duplicated here).
--
-- ── outline_section_requirements ─────────────────────────────────────────
-- The durable replacement for the session-state-only multiselect. One row
-- per (section, requirement) mapping. section_analyzer.py and
-- tenancy.py's Category A wrappers use REPLACE-ALL semantics per section
-- (delete then reinsert) to match the multiselect's own UX exactly --
-- this table is not intended to track per-mapping history, only current
-- state; review immutability is what section_reviews is for.
--
-- ── section_reviews ───────────────────────────────────────────────────────
-- One immutable row per Section Analyzer run. Never updated after insert,
-- never deleted by application code except via bid cascade. Records:
--   * section_content_hash / section_content_snapshot -- the EXACT text
--     that was reviewed (the live editor text, not necessarily what's
--     saved to outline_sections.notes), so re-opening a review later shows
--     precisely what it was run against, and so staleness can be detected
--     by comparing the CURRENT editor text's hash against this column
--     without re-sending the full text anywhere.
--   * mapped_requirement_ids -- a snapshot of which requirement ids this
--     review was run against, independent of outline_section_requirements'
--     current (possibly since-changed) state.
--   * based_on_procurement_revision / based_on_procurement_truth_status --
--     the bid's procurement governance state at review time (see
--     database.get_bid_procurement_state), so a later governed-baseline
--     change can be detected as making the review stale.
--   * based_on_analysis_run_id / based_on_analysis_result_id -- which Fast
--     Analysis run's raw snapshot (migration 012) advisory intelligence, if
--     any, contributed to this review. ON DELETE SET NULL, not CASCADE --
--     a section_reviews row is proposal-team history and must survive even
--     if the analytical run it referenced is later removed; it simply loses
--     that one traceability link, never its own review content.
--   * raw_snapshot_schema_version -- fast_analysis.FAST_ANALYSIS_RAW_SNAPSHOT_SCHEMA_VERSION
--     at the time this review consumed it, for future compatibility auditing.
--   * review_schema_version -- section_analyzer's own structured-output
--     schema version (independent of the raw snapshot's), so a future
--     schema change can be told apart from an older stored shape.
--   * direction / review_result -- the structured analyzer output itself
--     (see section_analyzer.py's SECTION_REVIEW_SCHEMA_VERSION and its
--     docstring for the exact JSON shape); direction is pulled out as its
--     own indexed column since it's the one field every review-history list
--     view needs to show without unpacking the jsonb payload.
--   * created_by_user_id -- uuid references auth.users(id), matching the
--     established post-Phase-8 convention (migration 010's
--     reviewed_by_user_id / applied_by_user_id / decided_by_user_id), not
--     the older pre-auth analysis_runs.created_by text column.
-- ═══════════════════════════════════════════════════════════════════════════

create table if not exists outline_section_requirements (
    id             bigserial primary key,
    bid_id         bigint not null references bids(id) on delete cascade,
    section_id     bigint not null references outline_sections(id) on delete cascade,
    requirement_id bigint not null references requirements(id) on delete cascade,
    created_at     timestamptz not null default now(),
    unique (section_id, requirement_id)
);

create index if not exists idx_outline_section_requirements_section
    on outline_section_requirements (section_id);
create index if not exists idx_outline_section_requirements_bid
    on outline_section_requirements (bid_id);

create table if not exists section_reviews (
    id                             bigserial primary key,
    bid_id                         bigint not null references bids(id) on delete cascade,
    section_id                     bigint not null references outline_sections(id) on delete cascade,

    section_content_snapshot       text not null,
    section_content_hash           text not null,
    mapped_requirement_ids         jsonb not null default '[]'::jsonb,

    based_on_procurement_revision      int,
    based_on_procurement_truth_status  text,
    based_on_analysis_run_id       bigint references analysis_runs(id) on delete set null,
    based_on_analysis_result_id    bigint references analysis_results(id) on delete set null,
    raw_snapshot_schema_version    text,

    review_schema_version          text not null,
    direction                      text not null
                                    check (direction in ('ON_TRACK', 'NEEDS_ADJUSTMENT',
                                                          'HIGH_RISK', 'INSUFFICIENT_CONTEXT')),
    review_result                  jsonb not null,

    created_by_user_id             uuid references auth.users(id),
    created_at                     timestamptz not null default now()
);

create index if not exists idx_section_reviews_section
    on section_reviews (section_id, created_at desc);
create index if not exists idx_section_reviews_bid
    on section_reviews (bid_id);
-- Idempotency lookup (section_analyzer.py's "is there already a review for
-- this exact state" check before spending a model call) -- see its
-- find_matching_review()/analyze_section() docstrings.
create index if not exists idx_section_reviews_idempotency
    on section_reviews (section_id, section_content_hash);

alter table outline_section_requirements enable row level security;
alter table section_reviews enable row level security;

-- Same transitive-bid_id-scoping pattern as every table migration 008
-- already governs (using public.can_access_bid(bid_id), defined there).
-- Full CRUD for outline_section_requirements (Category A: mirrors
-- outline_sections' own migration-008 policy set exactly, since the
-- mapping is edited by the same in-session writer as the section itself).
-- section_reviews is INSERT+SELECT only -- no UPDATE/DELETE policy, since
-- application code never updates or deletes a review directly (immutability
-- is enforced at the RLS layer, not just by convention: an authenticated
-- user literally cannot issue an UPDATE/DELETE that Postgres will accept).

create policy outline_section_requirements_select_bid_access
    on public.outline_section_requirements for select to authenticated
    using (public.can_access_bid(bid_id));
create policy outline_section_requirements_insert_bid_access
    on public.outline_section_requirements for insert to authenticated
    with check (public.can_access_bid(bid_id));
create policy outline_section_requirements_delete_bid_access
    on public.outline_section_requirements for delete to authenticated
    using (public.can_access_bid(bid_id));

create policy section_reviews_select_bid_access
    on public.section_reviews for select to authenticated
    using (public.can_access_bid(bid_id));
create policy section_reviews_insert_bid_access
    on public.section_reviews for insert to authenticated
    with check (public.can_access_bid(bid_id));
