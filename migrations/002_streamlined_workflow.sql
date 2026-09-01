-- ============================================================
-- Migration 002: Additive schema enhancements for streamlined bid workflow
-- Run this in Supabase SQL Editor
-- ============================================================

-- 1. Bid Briefs (Structured intelligence cache)
CREATE TABLE IF NOT EXISTS bid_briefs (
    id                      BIGSERIAL PRIMARY KEY,
    bid_id                  BIGINT NOT NULL REFERENCES bids(id) ON DELETE CASCADE,
    executive_summary       TEXT,
    opportunity_type        TEXT,
    contract_term           TEXT,
    procurement_model       TEXT,
    scope_categories        TEXT,         -- JSON array string
    deliverables_summary    TEXT,         -- JSON array string
    qualification_gates     TEXT,         -- JSON array string
    evaluation_breakdown    TEXT,         -- JSON array string
    commercial_structure    TEXT,         -- JSON array string
    contract_risks          TEXT,         -- JSON array string
    submission_requirements TEXT,         -- JSON array string
    key_dates               TEXT,         -- JSON array string
    source_citations        TEXT,         -- JSON object string
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT bid_briefs_bid_id_unique UNIQUE(bid_id)
);

-- 2. Qualification Assessment & Evidence Tracking (Additive columns to requirements)
ALTER TABLE requirements
    ADD COLUMN IF NOT EXISTS qual_status TEXT DEFAULT 'UNKNOWN',
    ADD COLUMN IF NOT EXISTS gap_action TEXT,
    ADD COLUMN IF NOT EXISTS qual_notes TEXT;

-- 3. Bid Decision & Human Override History
CREATE TABLE IF NOT EXISTS bid_decisions (
    id                  BIGSERIAL PRIMARY KEY,
    bid_id              BIGINT NOT NULL REFERENCES bids(id) ON DELETE CASCADE,
    ai_recommendation   TEXT,             -- GO | GO WITH CONDITIONS | NO-GO | NEEDS MORE INFO
    ai_confidence       TEXT,             -- High | Medium | Low
    overall_score       NUMERIC,
    dimension_scores    TEXT,             -- JSON object string
    hard_blockers       TEXT,             -- JSON array string
    conditions          TEXT,             -- JSON array string
    win_themes          TEXT,             -- JSON array string
    red_flags           TEXT,             -- JSON array string
    human_decision      TEXT,             -- Official pursuit decision recorded by user
    override_reason     TEXT,             -- Justification if overriding AI recommendation
    decided_by          TEXT,
    decided_at          TIMESTAMPTZ DEFAULT NOW(),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- 4. Generic Firm Profile (Bidding Entity Capabilities)
CREATE TABLE IF NOT EXISTS firm_profiles (
    id                  BIGSERIAL PRIMARY KEY,
    company_name        TEXT NOT NULL DEFAULT 'Enable My Growth',
    overview            TEXT,
    core_capabilities   TEXT,             -- JSON array or text
    key_sectors         TEXT,
    languages           TEXT,
    locations           TEXT,
    certifications      TEXT,
    insurance_defaults  TEXT,
    ai_disclosure_policy TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Disable RLS for new tables (consistent with existing schema design)
ALTER TABLE bid_briefs       DISABLE ROW LEVEL SECURITY;
ALTER TABLE bid_decisions    DISABLE ROW LEVEL SECURITY;
ALTER TABLE firm_profiles    DISABLE ROW LEVEL SECURITY;
