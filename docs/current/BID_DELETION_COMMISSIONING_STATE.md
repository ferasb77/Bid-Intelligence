# Bid Deletion Commissioning State

## Overview
This document records the operational state and verification of the Bid Deletion infrastructure commissioned in production.

## Commissioned Architecture & Migrations
1. **Migration 024 (`migrations/024_fix_bid_cascade_immutability.sql`)**:
   - Status: Applied to live database.
   - Purpose: Implements cascade-aware immutability triggers on append-only/immutable history tables (`full_analysis_events`, `check_run_events`, `procurement_changes`, `procurement_update_reviews`, `procurement_update_review_documents`, `procurement_conflicts`).
   - Invariant: Direct `DELETE` on immutable audit/governance records remains strictly prohibited while parent bid exists; cascade deletion during legitimate parent bid cleanup is permitted.

2. **Tenancy Service Boundary (`tenancy.delete_bid_for_organization`)**:
   - Multi-tenant isolation: Requires explicit `organization_id` matching tenant context.
   - Run Protection: Enforces fail-closed rejection if any analysis run is non-terminal.
   - Storage Inventory: Fail-closed recursive listing of all bid-owned Storage objects under `{bid_id}/`.
   - Post-Delete Verification: Verifies complete deletion from both database tables and Storage bucket.

3. **Customer Routing**:
   - Direct inline deletion action with confirmation exposed on Bids Directory (`page_all_bids`), invoking `tenancy.delete_bid_for_organization` via `database.delete_bid_for_organization`.

## Current Live Inventory State
- Organization ID: `4326b564-8cc5-4463-9304-9a589f08cc91`
- Authoritative Benchmark Opportunity (Preserved):
  - **Bid 1522**: Client "York University", Title "P27 070 Sales and AI Training and Mentorship Program(PDF)", Revision 2, Governed.
    - Runs: Run 55 (FAST, COMPLETE), Run 56 (FULL, PARTIAL), Run 57 (FULL, COMPLETE).
    - Status: Authoritative live York benchmark opportunity. Retained as primary reference.
- Disposable Duplicate Cleanup Note:
  - Bids 1517 and 1547 are blocked from direct parent CASCADE deletion by a foreign key constraint (`procurement_update_review_documents_document_id_fkey`) referencing `public.documents(id)` on delete restrict/no action.
  - Safe deletion of these duplicate opportunities is cataloged pending schema cascade enhancement on that FK constraint.
