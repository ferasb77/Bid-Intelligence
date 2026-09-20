-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 014: Model usage telemetry (BI Context & Token Optimization
-- Program, Phase 4)
-- ═══════════════════════════════════════════════════════════════════════════
-- Additive only. Does not modify migrations 001-013, does not touch any
-- canonical-procurement or analytical-content table. NOT applied to any
-- database in this authorization -- per this repo's existing convention,
-- apply manually via the Supabase SQL editor after separate review.
--
-- ── Why this table exists ───────────────────────────────────────────────
-- Phase 1 of this program found that Fast Analysis has rich per-call
-- telemetry but only an in-memory/summary trace of it survives past a
-- single run; Deep Verify's equivalent per-call capture code exists but
-- was never even activated in its real call path; analyst.py's 11 model-
-- calling workflows and section_analyzer.py have no telemetry at all;
-- Voyage embedding calls are untracked. This table is the one durable,
-- normalized destination for all of them -- see model_telemetry.py for the
-- exact event shape and which module feeds it how (direct
-- `telemetry_context` on config.execute_messages_create for most callers;
-- a one-time bridge from Fast Analysis's / Deep Verify's own existing
-- per-call lists, so a call already captured there is never double-counted).
--
-- This is ANALYTICAL-OUTPUT-ADJACENT ACCOUNTING DATA -- provider call
-- counts, token usage, latency, retries -- never the canonical procurement
-- facts, requirement data, or any prompt/response content itself. It does
-- not belong on bids/requirements/analysis_results, and no prompt or
-- response text is ever written here (enforced in model_telemetry.py: only
-- a small, byte-capped `metadata` jsonb field exists for structured
-- execution context, and callers never pass content through it).
--
-- ── Design notes ─────────────────────────────────────────────────────────
-- * bid_id / analysis_run_id use ON DELETE SET NULL, not CASCADE (unlike
--   most bid-owned child tables in this schema) -- this is accounting/audit
--   history, not analytical content; a later bid or run deletion should not
--   silently erase what usage/cost was actually incurred.
-- * No `organization_id` column -- same established principle as every
--   other bid-owned child table since migration 008: it is derived
--   transitively through `bid_id` -> `bids.organization_id` when a query
--   needs it, never duplicated here.
-- * `section_review_id` is a plain bigint with NO foreign key to
--   `section_reviews` (migration 013) -- migrations 013 and 014 may be
--   applied independently and in either order; a hard FK would create an
--   artificial application-order dependency between two otherwise-
--   unrelated features.
-- * `parent_event_id` self-references this table for a retry/recovery
--   child event, when the caller actually creates one (most retries in
--   this codebase re-use the same call_index with an incremented
--   retry_number instead of a separate parent/child pair -- both patterns
--   are supported, never conflated).
--
-- ── RLS ───────────────────────────────────────────────────────────────────
-- RLS is enabled with NO policies defined here, deliberately -- the same
-- pattern migration 004 originally used for analysis_runs/analysis_results
-- before migration 008 later added scoped policies. With zero policies, no
-- role except service_role (which bypasses RLS entirely, by Postgres
-- definition) can read or write this table: anonymous access is denied,
-- and cross-organization access is denied, trivially and completely, by
-- the absence of any grant rather than by a predicate that could be
-- gotten wrong. A future phase that wants bid-scoped usage visible to an
-- authenticated user can add a `using (public.can_access_bid(bid_id))`
-- select policy then, mirroring analysis_results_select_bid_access
-- exactly -- not needed by anything built in this phase.
-- ═══════════════════════════════════════════════════════════════════════════

create table if not exists model_usage_events (
    id                     bigserial primary key,
    schema_version         text not null default '1.0',

    bid_id                 bigint references bids(id) on delete set null,
    analysis_run_id        bigint references analysis_runs(id) on delete set null,
    section_review_id      bigint,

    workflow               text not null,
    operation              text not null,
    provider               text not null,
    model                  text not null,

    call_index             int,
    retry_number           int not null default 0,
    parent_event_id        bigint references model_usage_events(id) on delete set null,
    document_id            text,

    request_bytes          int,
    input_chars            int,

    -- Provider-reported ONLY. Never derived from request_bytes/input_chars
    -- -- see model_telemetry.py's module docstring. Null means "provider
    -- did not report this metric for this call", never "zero usage".
    input_tokens           int,
    output_tokens          int,
    cache_creation_tokens  int,
    cache_read_tokens      int,
    reasoning_tokens       int,

    latency_ms             int,
    stop_reason            text,

    status                 text not null check (status in ('SUCCESS', 'FAILURE')),
    error_category         text,
    parse_status            text,

    -- Small, structured execution context ONLY -- never prompt/response
    -- content. model_telemetry.py enforces a byte ceiling and drops
    -- anything larger rather than truncate-and-store.
    metadata                jsonb,

    created_at              timestamptz not null default now()
);

create index if not exists idx_model_usage_events_bid
    on model_usage_events (bid_id, created_at desc);
create index if not exists idx_model_usage_events_run
    on model_usage_events (analysis_run_id);
create index if not exists idx_model_usage_events_workflow
    on model_usage_events (workflow, created_at desc);
create index if not exists idx_model_usage_events_created_at
    on model_usage_events (created_at desc);

alter table model_usage_events enable row level security;
