-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 004: Analysis Runs — Fast Analysis / Deep Verify integration
-- ═══════════════════════════════════════════════════════════════════════════
-- Additive only. Does not touch any existing table's data. Safe to apply to
-- a live database with existing bids/requirements/documents/bid_briefs rows
-- (existing rows are untouched; new tables start empty).
--
-- Per this repo's existing convention (see database.py's init_db() docstring
-- and migrations/003's header), this file is NOT auto-applied by any code
-- path. Apply it manually via the Supabase SQL editor / dashboard, the same
-- way migrations 001-003 were applied.
--
-- Introduces:
--   analysis_runs    — durable lifecycle record for one analysis execution
--                       (Fast Analysis or, later, Deep Verify) against one
--                       bid's document corpus.
--   analysis_results — the full structured intelligence output of a
--                       completed run, independent of any single rendering
--                       (PDF, bid_briefs projection, future UI).
--
-- RLS is enabled on both new tables below. Note: supabase_schema.sql's own
-- comment ("RLS: disable for now — single-tenant app with API-key auth")
-- does not reflect the current state of the live Bid-Intelligence Supabase
-- project, so RLS here is not being left disabled "for consistency" with
-- anything. No policies are defined in this migration; that is deliberate
-- and left for separate, explicit review.
-- ═══════════════════════════════════════════════════════════════════════════

create table if not exists analysis_runs (
    id                  bigserial primary key,
    bid_id              bigint not null references bids(id) on delete cascade,

    -- 'FAST' is the default application analysis mode; 'DEEP_VERIFY' remains
    -- a separate, explicit, never-automatic mode (see app.py's existing
    -- extract_procurement_package() call path, which this migration does
    -- not touch).
    analysis_mode       text not null check (analysis_mode in ('FAST', 'DEEP_VERIFY')),

    -- Stable engine/version identifier the run was produced by, independent
    -- of whatever source code happens to be deployed when the run is later
    -- read back (e.g. 'fast-analysis-v4').
    engine_version      text not null,

    status              text not null default 'QUEUED'
                         check (status in ('QUEUED', 'PREPARING', 'ANALYZING',
                                            'ASSEMBLING', 'COMPLETE', 'FAILED')),

    created_at          timestamptz not null default now(),
    started_at          timestamptz,
    completed_at        timestamptz,
    failed_at           timestamptz,
    failure_reason      text,
    failure_detail      jsonb,

    -- Stable corpus snapshot: which persisted `documents` rows (by id and
    -- the version they were at) this run actually analyzed, plus a combined
    -- digest. A later file add/replace does not retroactively change what
    -- an already-created run is attributed to.
    corpus_document_ids jsonb not null default '[]'::jsonb,
    corpus_digest       text,

    -- Compact, non-engineering-facing telemetry summary (duration, call
    -- counts, tokens, retries) -- see analysis_service.py. Never rendered
    -- in the client-facing report.
    telemetry           jsonb,

    -- Storage path (same bucket/convention as `documents.storage_path`) of
    -- the rendered PDF for this run, once ASSEMBLING completes.
    report_storage_path text,

    created_by          text
);

-- At most one non-terminal run per (bid, mode) at a time -- this is the
-- durable, race-safe duplicate-start guard (instruction 7): a second
-- "Start Fast Analysis" click, browser refresh, or network retry cannot
-- create a second expensive run while one is already QUEUED/PREPARING/
-- ANALYZING/ASSEMBLING for the same bid and mode. Once a run reaches
-- COMPLETE or FAILED it drops out of this partial index and a new run may
-- be started.
create unique index if not exists idx_analysis_runs_one_active
    on analysis_runs (bid_id, analysis_mode)
    where status not in ('COMPLETE', 'FAILED');

create index if not exists idx_analysis_runs_bid
    on analysis_runs (bid_id, analysis_mode, created_at desc);

create table if not exists analysis_results (
    id                     bigserial primary key,
    run_id                 bigint not null unique references analysis_runs(id) on delete cascade,
    bid_id                 bigint not null references bids(id) on delete cascade,

    -- The full OpportunityIntelligence structured contract (see
    -- fast_analysis_app_adapter.py): snapshot, procurement scope, dates,
    -- qualification gates, evaluation, response requirements,
    -- pricing/commercial, ambiguities, attention points, source map, and
    -- buyer intelligence when available. Every material fact retains its
    -- source_refs. This is the durable record future UI features read from
    -- -- never require parsing the rendered PDF.
    structured_intelligence jsonb not null,

    -- Per-fact origin metadata carried from V4's reconciliation
    -- (LIVE_FAST_LLM / DETERMINISTIC_FAST_EXTRACTION /
    -- BUYER_INTELLIGENCE_EXTERNAL_LAYER / SAFETY_NET_FALLBACK). Not
    -- rendered to ordinary users; retained for validation, diagnostics,
    -- and future Deep Verify reconciliation.
    fact_origins           jsonb,

    -- A dict-ified snapshot of the exact report-content namespace
    -- (scripts/fast_analysis_report_adapter.build_fast_report_content's
    -- return value) used to render this run's PDF. Persisted so
    -- analysis_service.regenerate_report() can rebuild the PDF from
    -- state alone -- zero extraction calls, and no lossy reconstruction
    -- from the summarized structured_intelligence above (instruction 16).
    report_content_snapshot jsonb,

    created_at              timestamptz not null default now()
);

create index if not exists idx_analysis_results_bid
    on analysis_results (bid_id);

alter table analysis_runs enable row level security;
alter table analysis_results enable row level security;
