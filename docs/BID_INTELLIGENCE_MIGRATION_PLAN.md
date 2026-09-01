# BID INTELLIGENCE — MIGRATION PLAN

**Document Reference:** `docs/BID_INTELLIGENCE_MIGRATION_PLAN.md`  
**Date:** September 2026  
**Product:** Bid Intelligence (Enable My Growth)  
**Status:** Approved Migration Roadmap

---

## 1. Feature Mapping (Old Module $\rightarrow$ New Architecture)

| Legacy Module / Screen | New Location | Transformation Strategy |
|---|---|---|
| `Dashboard` | `Dashboard` | Preserved; enhanced with decision status badges and deadline countdowns. |
| `All Bids` | `Bids` | Preserved; enhanced with qualification status and pipeline sorting. |
| `New Bid` | `New Bid` | Redesigned extraction pipeline producing a structured `Bid Brief` immediately upon completion. |
| `Bid Overview` | `UNDERSTAND (Bid Brief)` | Merged into Bid Brief header and commercial summary. |
| `Compliance Matrix` | `DECIDE` & `CHECK` | Retained in full detail as an interactive control sheet and exportable PDF. |
| `Tasks` | `BUILD` & `DECIDE` | Contextualized around qualification gaps and section drafting; board retained as secondary view. |
| `Documents` | `BUILD` & `SUBMIT` | Working documents in Build; addenda analysis in Check; final package verification in Submit. |
| `Deliverables` | `UNDERSTAND` & `BUILD` | Extracted deliverables summarized in Bid Brief and managed in Build. Tender-specific auto-generation removed. |
| `Proposal Outline` | `BUILD` | Integrated as the master skeleton of the Proposal Workspace. |
| `AI Analyst (Review)` | `CHECK (Bid Review)` | Embedded into Bid Review and section editing. |
| `AI Analyst (Evidence)` | `DECIDE` & `CHECK` | Embedded into Qualification table and Bid Review. |
| `AI Analyst (Clarifications)` | `DECIDE` | Merged with Clarification Tracker; dynamic question generation from RFP ambiguity. |
| `AI Analyst (Bid/No-Bid)` | `DECIDE` | Embedded as the core Bid Decision Console with human override. |
| `Clarifications` | `DECIDE` | Unified with clarification engine; hardcoded CDA-AMC prompts removed. |
| `Section Drafter` | `BUILD` | Embedded directly within proposal sections in the Proposal Workspace. |
| `Proposal Analyzer` | `Content Library` & `BUILD` | Moved to Content Library ingestion and Proposal Workspace content reuse. |
| `Coach Roster` | `Team & Resource Library` | Abstracted to generic expert/team management under Content Library. Existing records preserved. |
| `Submission Assembler` | `SUBMIT (Submission Control)` | Redesigned into Submission Control with dynamic checklists and go-live gates. |
| `Debrief` | Contextual Post-Submission | Revealed automatically when bid is `Submitted`, `Won`, `Lost`, or `Withdrawn`. |
| `Executive View` | `Executive View` | Preserved; generalized to remove hardcoded company names. |

---

## 2. Database Changes & Backwards Compatibility

All database changes are **strictly additive**. No existing tables, columns, constraints, or rows will be dropped or renamed.

### SQL Migration Script: `migrations/002_streamlined_workflow.sql`

```sql
-- Migration 002: Additive schema enhancements for streamlined bid workflow

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
```

---

## 3. Implementation Sequence

1. **Step 1: Database Migration File:**
   - Create `migrations/002_streamlined_workflow.sql`.
   - Update `database.py` with helper functions for `bid_briefs`, `qualification_assessments`, `bid_decisions`, and `firm_profiles`.
2. **Step 2: Service Layer & RFP Extraction Pipeline:**
   - Enhance `extractor.py` to extract structured `bid`, `brief`, `requirements`, `documents`, and `outline`.
   - Generalize prompts in `analyst.py` (remove Phoenix, CDA-AMC, Hogan, Ottawa/Beirut hardcoded strings).
3. **Step 3: UI Redesign (The 5 Workflow Stages):**
   - Create modular page components:
     - `page_understand` (`Bid Brief`)
     - `page_decide` (`Qualification & Pursuit Decision`)
     - `page_build` (`Proposal Workspace`)
     - `page_check` (`Bid Review & Alignment`)
     - `page_submit` (`Submission Control`)
     - `page_debrief` (Contextual)
   - Update `app.py` navigation and routing to use the 5 primary stages.
4. **Step 4: Global Screens & Genericization:**
   - Update `Dashboard`, `Bids`, `Content Library`, `Executive View`, and `Settings`.
5. **Step 5: Testing & Verification:**
   - Create automated test suite in `tests/`.
   - Verify extraction, qualification logic, decision overrides, legacy bid backward compatibility, and app stability.
6. **Step 6: Documentation & Walkthrough:**
   - Update `README.md`.
   - Generate `TEST_REPORT_STREAMLINED_WORKFLOW.md`.

---
