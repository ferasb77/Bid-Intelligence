-- ============================================================================
-- Migration 003: Intelligence & Governance Integrity
-- Application: Bid Intelligence (Enable My Growth)
--
-- PURPOSE:
-- 1. Separate qualification status from evidence readiness (evidence_status)
-- 2. Add structural source provenance / traceability to extracted requirements
-- 3. Add first-class document conflict & ambiguity storage to Bid Briefs
-- 4. Add explicit timestamping for human pursuit decisions
--
-- NOTE: DO NOT EXECUTE AUTOMATICALLY. Leave for explicit user review & approval.
-- ============================================================================

-- 1. Evidence readiness status on requirements (READY / PARTIAL / MISSING / NOT REQUIRED)
ALTER TABLE requirements
ADD COLUMN IF NOT EXISTS evidence_status TEXT DEFAULT 'MISSING';

-- 2. Structural source references / provenance on requirements
ALTER TABLE requirements
ADD COLUMN IF NOT EXISTS source_refs JSONB DEFAULT '[]'::jsonb;

-- 3. Cross-document conflict and discrepancy detection on bid briefs
ALTER TABLE bid_briefs
ADD COLUMN IF NOT EXISTS document_conflicts JSONB DEFAULT '[]'::jsonb;

-- 4. Timestamp for official human pursuit decisions
ALTER TABLE bid_decisions
ADD COLUMN IF NOT EXISTS decided_at TIMESTAMPTZ;

-- Indices for performance
CREATE INDEX IF NOT EXISTS idx_requirements_evidence_status ON requirements(bid_id, evidence_status);
