# Bid Deletion Commissioning State

## Status: Commissioned & Frozen

This document records the operational state, schema contracts, and verification of the Bid Deletion infrastructure commissioned in production.

## Commissioned Architecture & Live Migrations
1. **Migration 024 (`migrations/024_fix_bid_cascade_immutability.sql`)**:
   - Status: Applied to live database.
   - Purpose: Implements cascade-aware immutability triggers on append-only/immutable history tables (`full_analysis_events`, `check_run_events`, `procurement_changes`, `procurement_update_reviews`, `procurement_conflicts`).
   - Invariant: Direct `DELETE` on immutable audit/governance records remains strictly prohibited while parent bid exists; cascade deletion during legitimate parent bid cleanup is permitted.

2. **Migration 025 (`migrations/025_bid_purge_referential_closure.sql`)**:
   - Status: Applied to live database.
   - Purpose: Closes governed-bid purge foreign key relationships and makes applied review-document immutability bid-cascade-aware:
     - `procurement_update_review_documents.document_id` -> `documents.id` `ON DELETE CASCADE`
     - `procurement_changes.source_document_id` -> `documents.id` `ON DELETE CASCADE`
     - `procurement_conflicts.target_requirement_id` -> `requirements.id` `ON DELETE SET NULL`
     - `procurement_changes.target_requirement_id` -> `requirements.id` `ON DELETE SET NULL`
     - `prevent_applied_review_document_mutation()`: Checks parent review status + bid_id existence. Rejects UPDATE and direct DELETE while parent bid exists; allows cascading delete during whole-bid purge.

3. **Tenancy Service Boundary (`tenancy.delete_bid_for_organization`)**:
   - Multi-tenant isolation: Requires explicit `organization_id` matching tenant context.
   - Run Protection: Enforces fail-closed rejection if any analysis run is non-terminal.
   - Storage Inventory: Fail-closed recursive listing of all bid-owned Storage objects under `{bid_id}/`.
   - Post-Delete Verification: Verifies complete deletion from both database tables and Storage bucket.

4. **Customer Routing**:
   - Direct inline deletion action with confirmation exposed on Bids Directory (`page_all_bids`), invoking `tenancy.delete_bid_for_organization` via `database.delete_bid_for_organization`.

## Final Commissioning Verification Results
- **Bid 1517 Production Deletion**: **PASS**
  - Database records: 0 rows remaining across all bid-scoped tables.
  - Storage prefix `1517/`: 0 files remaining.
- **Bid 1547 Production Deletion**: **PASS**
  - Database records: 0 rows remaining across all bid-scoped tables.
  - Storage prefix `1547/`: 0 files remaining.
- **Bid 1522 Benchmark Preservation**: **PASS**
  - All identity fields, governed status (Revision 2), requirements, runs (Run 57 FULL COMPLETE), reviews (Review 5 applied), changes, and Storage objects verified 100% UNCHANGED.
- **Global Orphan Audit**: **PASS**
  - Zero orphan rows detected across the database.
- **Live Bid Directory**:
  - Exactly ONE opportunity exists: Bid 1522 (`York University` — `P27 070 Sales and AI Training and Mentorship Program(PDF)`).

## Operational Rule
Deletion architecture is **FROZEN**. Do not add further deletion features, hooks, or speculative hardening unless a genuine production defect appears.
