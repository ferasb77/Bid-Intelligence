-- ============================================================================
-- Migration 026: Durable Governed Buyer Research Runs
-- ============================================================================
--
-- STATUS: UNAPPLIED (Written for BI-VALUE-2.1; requires manual dashboard run).
--
-- Purpose:
-- Establishes a durable, bid/organization-scoped persistence layer for governed
-- buyer research runs. Guarantees that exact COMPLETE research reuse survives
-- process restarts, Streamlit reruns, and multi-worker deployments with:
--   - 0 searches
--   - 0 page fetches
--   - 0 model calls
--
-- Invariants:
-- 1. Scoped to bid_id and organization_id with ON DELETE CASCADE on bids.
-- 2. Unique constraint on (organization_id, research_fingerprint) where
--    status = 'COMPLETE', preventing duplicate work within the same tenant.
-- 3. Row-level security (RLS) enabled: SELECT accessible to authenticated members
--    via can_access_bid(bid_id); write access restricted to service_role.
-- ============================================================================

create table if not exists public.buyer_research_runs (
    id bigserial primary key,
    bid_id bigint not null references public.bids(id) on delete cascade,
    organization_id uuid not null references public.organizations(id) on delete cascade,
    research_fingerprint text not null,
    contract_version text not null default 'buyer-research/1',
    status text not null check (status in ('RUNNING', 'COMPLETE', 'PARTIAL', 'UNAVAILABLE', 'FAILED')),
    resolved_buyer_name text not null,
    solicitation_number text,
    context_digest text,
    search_count integer not null default 0,
    accepted_page_count integer not null default 0,
    provider text not null default 'anthropic_server_tools',
    payload jsonb not null default '{}'::jsonb,
    error_reason text,
    started_at timestamptz not null default timezone('utc'::text, now()),
    completed_at timestamptz,
    created_at timestamptz not null default timezone('utc'::text, now())
);

-- Index for bid-level lookups
create index if not exists idx_buyer_research_runs_bid
    on public.buyer_research_runs (bid_id);

-- Organization-scoped unique completed fingerprint boundary
create unique index if not exists idx_buyer_research_runs_org_fingerprint_complete
    on public.buyer_research_runs (organization_id, research_fingerprint)
    where status = 'COMPLETE';

-- Enable Row Level Security
alter table public.buyer_research_runs enable row level security;

-- Authenticated tenant access policy
drop policy if exists buyer_research_runs_select_bid_access on public.buyer_research_runs;
create policy buyer_research_runs_select_bid_access
    on public.buyer_research_runs for select
    to authenticated
    using (public.can_access_bid(bid_id));
