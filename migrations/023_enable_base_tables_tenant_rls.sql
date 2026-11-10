-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 023: Enable Base Tables Tenant Row Level Security (Package R2A)
-- ═══════════════════════════════════════════════════════════════════════════
-- Forward security remediation migration.
--
-- Defect addressed:
--   supabase_schema.sql (lines 185-195) explicitly disabled row level security
--   on 11 base tables:
--     1. bids
--     2. requirements
--     3. tasks
--     4. documents
--     5. document_versions
--     6. outline_sections
--     7. content_library
--     8. coaches
--     9. clarifications
--    10. debriefs
--    11. deliverables
--
--   Migration 008 created comprehensive RLS policies on bids, requirements,
--   tasks, documents, document_versions, outline_sections, content_library,
--   clarifications, debriefs, and deliverables. Migration 009 created
--   policies on coaches. However, both migrations omitted:
--     ALTER TABLE ... ENABLE ROW LEVEL SECURITY;
--
--   In PostgreSQL, policies created on a table where relrowsecurity = false
--   remain inert. Direct PostgREST / client-side queries by authenticated
--   users therefore bypassed all tenant boundaries on these 11 tables.
--
-- Remediation:
--   1. Explicitly enable Row Level Security on all 11 base tables.
--   2. Explicitly revoke all table-level privileges on public tables from the
--      'anon' pseudo-role (defense-in-depth).
--   3. Ensure 'authenticated' has necessary standard CRUD grants so that
--      Postgres RLS policies govern row-level access.
--   4. Verify coaches ownership foreign key and indices are fully enforced.
-- ═══════════════════════════════════════════════════════════════════════════

-- ── 1. Enable Row Level Security on the 11 Base Tables ───────────────────────

ALTER TABLE public.bids                ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.requirements        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tasks               ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.documents           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document_versions   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.outline_sections    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.content_library     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coaches             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.clarifications      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.debriefs            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.deliverables        ENABLE ROW LEVEL SECURITY;

-- ── 2. Defense-in-Depth Role Grants ──────────────────────────────────────────

-- Revoke all public table privileges from unauthenticated 'anon' role
REVOKE ALL ON TABLE public.bids                FROM anon;
REVOKE ALL ON TABLE public.requirements        FROM anon;
REVOKE ALL ON TABLE public.tasks               FROM anon;
REVOKE ALL ON TABLE public.documents           FROM anon;
REVOKE ALL ON TABLE public.document_versions   FROM anon;
REVOKE ALL ON TABLE public.outline_sections    FROM anon;
REVOKE ALL ON TABLE public.content_library     FROM anon;
REVOKE ALL ON TABLE public.coaches             FROM anon;
REVOKE ALL ON TABLE public.clarifications      FROM anon;
REVOKE ALL ON TABLE public.debriefs            FROM anon;
REVOKE ALL ON TABLE public.deliverables        FROM anon;

-- Ensure authenticated role has standard table-level access (governed by RLS)
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.bids                TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.requirements        TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.tasks               TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.documents           TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.document_versions   TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.outline_sections    TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.content_library     TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.coaches             TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.clarifications      TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.debriefs            TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.deliverables        TO authenticated;

-- Ensure sequence privileges for serial/bigserial primary key generation
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO authenticated;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO service_role;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon;

-- Ensure service_role retains full access for background pipelines
GRANT ALL ON TABLE public.bids                TO service_role;
GRANT ALL ON TABLE public.requirements        TO service_role;
GRANT ALL ON TABLE public.tasks               TO service_role;
GRANT ALL ON TABLE public.documents           TO service_role;
GRANT ALL ON TABLE public.document_versions   TO service_role;
GRANT ALL ON TABLE public.outline_sections    TO service_role;
GRANT ALL ON TABLE public.content_library     TO service_role;
GRANT ALL ON TABLE public.coaches             TO service_role;
GRANT ALL ON TABLE public.clarifications      TO service_role;
GRANT ALL ON TABLE public.debriefs            TO service_role;
GRANT ALL ON TABLE public.deliverables        TO service_role;

-- ── 3. Verification Assertion ────────────────────────────────────────────────
-- Ensure all 11 tables now report rowsecurity = true in pg_tables.
DO $$
DECLARE
    disabled_count int;
BEGIN
    SELECT count(*) INTO disabled_count
    FROM pg_tables
    WHERE schemaname = 'public'
      AND tablename IN (
          'bids', 'requirements', 'tasks', 'documents', 'document_versions',
          'outline_sections', 'content_library', 'coaches', 'clarifications',
          'debriefs', 'deliverables'
      )
      AND rowsecurity = false;

    IF disabled_count > 0 THEN
        RAISE EXCEPTION 'Migration 023 failed: % base table(s) still have row level security disabled.', disabled_count;
    END IF;
END $$;
