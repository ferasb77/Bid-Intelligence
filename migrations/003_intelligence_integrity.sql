-- ============================================================================
-- Migration 003: Intelligence & Governance Integrity
-- Application: Bid Intelligence (Enable My Growth)
--
-- PURPOSE:
-- 1. Evidence readiness status with CHECK constraint (READY, PARTIAL, MISSING, NOT REQUIRED)
-- 2. Structural source provenance / traceability as native JSONB on requirements
-- 3. Cross-document conflict & discrepancy detection as native JSONB on bid briefs
--
-- NOTE: DO NOT EXECUTE AUTOMATICALLY. Leave for explicit user review & approval.
-- ============================================================================

-- 1. Evidence readiness status on requirements with CHECK constraint
ALTER TABLE requirements
ADD COLUMN IF NOT EXISTS evidence_status TEXT DEFAULT 'MISSING';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'check_requirements_evidence_status'
    ) THEN
        ALTER TABLE requirements
        ADD CONSTRAINT check_requirements_evidence_status
        CHECK (evidence_status IN ('READY', 'PARTIAL', 'MISSING', 'NOT REQUIRED'));
    END IF;
END $$;

-- 2. Structural source references / provenance as native JSONB on requirements
ALTER TABLE requirements
ADD COLUMN IF NOT EXISTS source_refs JSONB DEFAULT '[]'::jsonb;

-- 3. Cross-document conflict and discrepancy detection as native JSONB on bid briefs
ALTER TABLE bid_briefs
ADD COLUMN IF NOT EXISTS document_conflicts JSONB DEFAULT '[]'::jsonb;

-- Indices for query performance
CREATE INDEX IF NOT EXISTS idx_requirements_evidence_status ON requirements(bid_id, evidence_status);
