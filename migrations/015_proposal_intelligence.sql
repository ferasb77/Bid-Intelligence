-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 015: Proposal Intelligence — durable PI-1 foundation
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
--      inclusion state, and role -- see proposal_intelligence.py's
--      compute_package_digest() for the exact canonicalization. Two
--      uploads that differ in bytes, inclusion, or role always produce a
--      different digest; re-submitting the identical package produces the
--      identical digest, and create_proposal_package_snapshot() reuses the
--      existing row instead of duplicating it (unique on bid_id+digest).
--      `manifest` stores only the report-safe per-file fields
--      (extractor.build_report_manifest()'s shape) -- never raw extracted
--      proposal text, matching Fast Analysis's raw-snapshot precedent of
--      never storing prompt/response content redundantly.
--
--   2. proposal_intelligence_runs -- one immutable row per Proposal
--      Alignment execution, tied to BOTH an exact package snapshot AND an
--      exact procurement_revision/procurement_truth_status (the same
--      based_on_procurement_revision/based_on_procurement_truth_status
--      stamping pattern section_reviews already established). status is
--      COMPLETE/INCOMPLETE/FAILED, mirroring the analyzer's own existing
--      status vocabulary ("complete"/"incomplete") plus FAILED for a
--      provider/model exception with no usable result at all.
--      analysis_version is proposal_intelligence.py's own PI analytical-
--      contract version (NOT the model name) -- see its module docstring.
--      legacy_result preserves the analyzer's existing overall_score/
--      recommendation/executive_summary/strengths/next_steps for backward-
--      compatible CHECK rendering; PI-1 does NOT promote a "proposal
--      quality score" into a first-class column of the new domain.
--
--   3. proposal_requirement_assessments -- one durable row per procurement
--      requirement the run assessed, normalizing analyst.py's EXISTING
--      requirement_coverage vocabulary (Fully Addressed/Partially
--      Addressed/Not Addressed/Cannot Assess) rather than inventing a
--      second one -- see proposal_intelligence.py's adapter for the exact,
--      documented mapping.
--
--   4. proposal_intelligence_findings -- cross-cutting/requirement-related
--      findings normalized from the analyzer's existing findings/
--      mandatory_failures/unresolved_items into the bounded finding_type
--      taxonomy in proposal_intelligence.py (REQUIREMENT_COVERAGE,
--      MISSING_REQUIREMENT, WEAK_EVIDENCE, UNSUPPORTED_CLAIM,
--      CONTRADICTION, RESPONSE_GUIDELINE_GAP, SUBMISSION_ARTIFACT_GAP,
--      INTERNAL_INCONSISTENCY, DELIVERY_COMMITMENT, COMMERCIAL_EXPOSURE,
--      OTHER). Rows are immutable outputs of one run -- no mutable
--      workflow/status management around findings in PI-1.
--
-- All four tables key off bid_id directly (not organization_id) -- the
-- same established principle as every bid-owned child table since
-- migration 008: RLS is inherited transitively through can_access_bid.
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
-- 014's model_usage_events precedent (RLS enabled, no write policies ->
-- only service_role, which bypasses RLS by Postgres definition, can write;
-- anonymous and cross-org writes are denied trivially by the absence of
-- any grant, not by a predicate that could be misconfigured). RLS fails
-- closed: an authenticated client literally cannot issue an INSERT/UPDATE/
-- DELETE against these tables that Postgres will accept.
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
    unique (bid_id, package_version)
);

create index if not exists idx_proposal_package_snapshots_bid
    on proposal_package_snapshots (bid_id, package_version desc);

create table if not exists proposal_intelligence_runs (
    id                                  bigserial primary key,
    bid_id                              bigint not null references bids(id) on delete cascade,
    proposal_package_snapshot_id        bigint not null references proposal_package_snapshots(id) on delete cascade,

    based_on_procurement_revision       int,
    based_on_procurement_truth_status   text,

    analysis_version                    text not null,
    status                              text not null
                                         check (status in ('COMPLETE', 'INCOMPLETE', 'FAILED')),
    failure_reason                      text,

    coverage_metadata                   jsonb,
    legacy_result                       jsonb,

    started_at                          timestamptz not null default now(),
    completed_at                        timestamptz,
    created_by_user_id                  uuid references auth.users(id),
    created_at                          timestamptz not null default now()
);

create index if not exists idx_proposal_intelligence_runs_bid
    on proposal_intelligence_runs (bid_id, created_at desc);
create index if not exists idx_proposal_intelligence_runs_snapshot
    on proposal_intelligence_runs (proposal_package_snapshot_id);

create table if not exists proposal_requirement_assessments (
    id                          bigserial primary key,
    run_id                      bigint not null references proposal_intelligence_runs(id) on delete cascade,
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

    created_at                  timestamptz not null default now()
);

create index if not exists idx_proposal_requirement_assessments_run
    on proposal_requirement_assessments (run_id);
create index if not exists idx_proposal_requirement_assessments_bid
    on proposal_requirement_assessments (bid_id);
create index if not exists idx_proposal_requirement_assessments_requirement
    on proposal_requirement_assessments (requirement_id);

create table if not exists proposal_intelligence_findings (
    id                          bigserial primary key,
    run_id                      bigint not null references proposal_intelligence_runs(id) on delete cascade,
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

    created_at                  timestamptz not null default now()
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
-- service_role (bypasses RLS by Postgres definition) may write.
