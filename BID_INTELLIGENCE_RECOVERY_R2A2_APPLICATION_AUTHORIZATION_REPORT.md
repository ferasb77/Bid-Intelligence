# Bid Intelligence — Historical Baseline Recovery
# Package R2A.2: Phoenix Beta Application Authorization Report

**Document Version:** 1.0.0  
**Date:** November 11, 2026  
**Status:** Completed & Ready for Independent Acceptance  
**Target Environment:** Phoenix Consulting Beta Foundation  
**Worktree:** `C:\Users\feras\Documents\Projects\Bid-Intelligence-Recovery`  
**Branch:** `recovery/r2a-tenant-security`  
**Predecessor Baseline:** `b788023` (Package R2A.1 GO accepted in `BID_INTELLIGENCE_RECOVERY_R2A1_FINAL_INDEPENDENT_VERIFICATION.md`)

---

## Executive Summary

Package R2A.2 eliminates the application-layer authorization vulnerabilities that previously blocked a controlled Phoenix Consulting beta deployment. Where Package R2A.1 established database-layer Row Level Security (RLS) policies on the base tables, R2A.2 establishes explicit, tenant-scoped application authorization boundaries around all Storage and Document operations, remediates unsafe service-role operations, removes caller-controlled Storage path manipulation, enforces document-to-bid relational integrity, and validates that privileged actions cannot be performed across tenant boundaries.

This package was implemented strictly as a beta-enabling security package rather than a broad architectural redesign. The existing Fast Analysis, Full Analysis, report generation, and RFP extraction workflows remain intact, preserving full compatibility with the recovered September 29, 2026 architecture.

---

## 1. Document & Storage Authorization Analysis & Architecture

### 1.1 The Vulnerability Surface in the Historical Baseline

In the baseline recovery codebase, document reads from `documents` and `document_versions` were gated by PostgREST Row Level Security (RLS) under Migration 008/023 (Category A: authenticated read). However, document and storage writes/deletions were deliberately retained as service-role-only operations (Category B: server-write-only) because the Supabase `bid-documents` storage bucket is managed via service-role API credentials.

This architectural division left critical gaps at the application boundary:
1. **Generic Unscoped Signed URLs (`db.get_signed_url`):** The function `database.get_signed_url(storage_path: str, expires_in: int = 3600)` accepted an arbitrary storage path string from any caller and generated a time-limited signed URL using the service-role client. If an adversary in Organization A learned or guessed a Storage path belonging to Organization B (e.g., `8/uuid.pdf`), calling this function directly generated a valid signed URL allowing unauthorized access to Organization B's documents.
2. **Direct Storage Path Downloads (`db.download_file`):** `database.download_file(storage_path: str)` directly fetched file bytes from Supabase Storage using the service-role client without verifying whether the requesting user's organization owned the underlying bid or document.
3. **Cross-Tenant Document Version Tampering:** `tenancy.upload_document_for_organization(bid_id, organization_id, filename, file_bytes, doc_id=doc_id)` verified that `bid_id` was owned by `organization_id`, but when `doc_id` was supplied (for version replacement/archiving), it never verified that `doc_id` actually belonged to `bid_id`. An attacker owning Bid 10 could pass `doc_id=202` (belonging to Organization B's Bid 20) and overwrite Organization B's document while archiving its previous version.
4. **Bare Service-Role UI Operations:** In `app.py` (`page_documents`, `page_bid_overview`), document uploads, metadata updates, and deletions (`delete_document(eid)`) directly called bare `database.py` functions using the service-role client instead of passing through tenant authorization gates.
5. **Report & Appendix Downloads:** In `pages/stage_understand.py`, analysis appendix downloads directly passed `run["report_storage_path"]` to `database.download_file()` rather than validating run-to-bid and bid-to-tenant ownership.

### 1.2 Remediated Architecture & Interfaces

To close these gaps without breaking beta functionality, R2A.2 implements strict authorization wrappers in `tenancy.py` and hardens `database.py`:

```
+---------------------------------------------------------------------------------------------------+
|                                      APPLICATION UI LAYER                                         |
|  app.py (page_bid_overview, page_documents) | pages/stage_understand.py (Fast/Deep Analysis)      |
+---------------------------------------------------------------------------------------------------+
                                                  |
                    (Strictly passes verified AuthContext.organization_id)
                                                  v
+---------------------------------------------------------------------------------------------------+
|                                 TENANCY AUTHORIZATION BOUNDARY                                    |
|                                         (tenancy.py)                                              |
|                                                                                                   |
|  1. require_bid_access(bid_id, organization_id) -> Fails closed if org != bid.owner               |
|  2. verify document_id.bid_id == bid_id          -> Fails closed on foreign document IDs          |
|  3. verify run_id.bid_id == bid_id               -> Fails closed on foreign analysis run IDs      |
|  4. extract verified internal storage_path       -> Never trusts caller-controlled paths          |
+---------------------------------------------------------------------------------------------------+
                                                  |
                    (Authorized execution via service role client)
                                                  v
+---------------------------------------------------------------------------------------------------+
|                                   DATA & STORAGE ADAPTER                                          |
|                                       (database.py)                                               |
|                                                                                                   |
|  - get_document(doc_id): Single document primary-key retrieval.                                   |
|  - get_document_signed_url(doc_id, organization_id): Tenant-validated signing interface.          |
|  - save_upload(..., doc_id=...): Defense-in-depth relational check (doc.bid_id == bid_id).         |
|  - delete_document(doc_id, bid_id=...): Defense-in-depth deletion check.                          |
|  - download_file(path) / get_signed_url(path): Path sanitization (blocks traversal/leading slash).|
+---------------------------------------------------------------------------------------------------+
```

#### New Authorized Tenancy Primitives:
- `download_document_for_organization(bid_id: int, doc_id: int, organization_id: str) -> bytes | None`: Verifies tenant bid ownership and document-to-bid association, extracts the stored `storage_path`, and retrieves file bytes.
- `get_signed_url_for_document_for_organization(bid_id: int, doc_id: int, organization_id: str, expires_in: int = 3600) -> str`: Generates a signed URL only for a verified document belonging to an authorized bid.
- `delete_document_for_organization(bid_id: int, doc_id: int, organization_id: str) -> None`: Authorizes deletion of a document and its version history.
- `download_analysis_report_for_organization(bid_id: int, run_id: int, organization_id: str) -> bytes | None`: Verifies tenant bid ownership and run-to-bid association before downloading analysis reports.
- `get_signed_url_for_analysis_report_for_organization(bid_id: int, run_id: int, organization_id: str, expires_in: int = 3600) -> str`: Generates a signed URL only for verified analysis reports.
- `upsert_document_for_organization(bid_id: int, organization_id: str, data: dict) -> None`: Authorizes document metadata updates, ensuring `doc_id` belongs to `bid_id`.
- `create_expected_document_for_organization(bid_id: int, organization_id: str, name: str, doc_type: str, ...) -> int | None`: Scoped creation of expected placeholder documents.
- `get_document_for_organization(bid_id: int, doc_id: int, organization_id: str) -> dict | None`: Read-only authorized single-document metadata lookup.

---

## 2. Complete Inventory of Service-Role Operations

All operations that utilize the service-role client (`database.get_client()`) have been audited. In the application architecture:

| Operation Category | Low-Level Service Function | Tenancy Authorization Boundary | Application Call Sites | Tenancy Verification Mechanism |
|---|---|---|---|---|
| **Document Upload** | `db.save_upload` | `tenancy.upload_document_for_organization` | `app.py:454`, `app.py:682`, `app.py:1227`, `app.py:1325`, `stage_build.py:613`, `stage_submit.py:97` | `require_bid_access(bid_id, org_id)` + verify `doc_id.bid_id == bid_id` |
| **Document Download** | `db.download_file` | `tenancy.download_document_for_organization` | `app.py:1388`, `pages/stage_understand.py:350` | `require_bid_access(bid_id, org_id)` + verify `doc_id.bid_id == bid_id` |
| **Document Deletion** | `db.delete_document` | `tenancy.delete_document_for_organization` | `app.py:1298` | `require_bid_access(bid_id, org_id)` + verify `doc_id.bid_id == bid_id` |
| **Document Metadata Upsert** | `db.upsert_document` | `tenancy.upsert_document_for_organization`, `tenancy.set_document_mandatory_for_organization`, `tenancy.create_document_record_for_organization` | `app.py:1060`, `app.py:1291`, `app.py:1332`, `pages/stage_submit.py` | `require_bid_access(bid_id, org_id)` + verify `data.id.bid_id == bid_id` |
| **Expected Document Creation** | `db.create_expected_document` | `tenancy.create_expected_document_for_organization` | `app.py:1020`, `app.py:1352` | `require_bid_access(bid_id, org_id)` |
| **Analysis Report Download** | `db.download_file` | `tenancy.download_analysis_report_for_organization` | `pages/stage_understand.py:301` | `require_bid_access(bid_id, org_id)` + verify `run_id.bid_id == bid_id` |
| **Analysis Report URL Signing** | `db.get_signed_url` | `tenancy.get_signed_url_for_analysis_report_for_organization` | Export / download links | `require_bid_access(bid_id, org_id)` + verify `run_id.bid_id == bid_id` |
| **Fast Analysis Execution** | `analysis_service.start_fast_analysis` | `tenancy.start_fast_analysis_for_organization` | `app.py:459`, `pages/stage_understand.py:270` | `require_bid_access(bid_id, org_id)` |
| **Full Analysis Execution** | `full_analysis_service.start_full_analysis` | `tenancy.start_full_analysis_for_organization` | `pages/stage_full_analysis.py` | `require_bid_access(bid_id, org_id)` |
| **Report PDF Generation** | `analysis_service.regenerate_report` | `tenancy.get_report_for_organization`, `tenancy.get_raw_snapshot_report_for_organization` | `pages/stage_understand.py` | `require_bid_access(bid_id, org_id)` + verify `run_id.bid_id == bid_id` |
| **Brief PDF Generation** | `analysis_service.generate_bid_intelligence_brief_from_raw_snapshot` | `tenancy.export_bid_intelligence_brief_for_organization` | `pages/stage_understand.py:292` | `require_bid_access(bid_id, org_id)` + verify `run_id.bid_id == bid_id` |
| **Check Run Execution** | `check_run_service.start_check_run` | `tenancy.start_check_run_for_organization` | `pages/stage_check.py` | `require_bid_access(bid_id, org_id)` |
| **Section Analysis** | `section_analyzer.analyze_section` | `tenancy.analyze_section_for_organization` | `pages/stage_build.py` | `require_bid_access(bid_id, org_id)` + verify `section_id.bid_id == bid_id` |
| **Organizational Memory Ingestion** | `db.ingest_organizational_source_document` | `tenancy.ingest_organizational_source_document_for_organization` | `pages/stage_memory.py` | `organization_id` strictly validated; upload content-addressed under `org/{org_id}/sources` |

**Fail-Closed Invariant:** `tenancy.require_bid_access(bid_id, organization_id)` and `tenancy.get_bid_for_organization(bid_id, organization_id)` immediately return `None` / raise `AccessDeniedError` if either `organization_id` or `bid_id` is missing, empty, or `None`, preventing any accidental execution against unverified caller contexts.

---

## 3. Actual Authentication and API Boundaries Environment Status

Per explicit instruction in the R2A.2 specification:
> *"Establish isolated tests using real Supabase Auth-issued JWTs and PostgREST requests for at least two organizations and distinct user identities if local PostgREST/Supabase runtime is available. If an actual Auth/PostgREST environment is unavailable, report the limitation honestly and leave the corresponding acceptance criteria open. Do not substitute PostgreSQL SET ROLE simulation and claim full API verification."*

### Confirmed Environmental Status:
- `supabase` CLI is not installed or available on system `PATH`.
- `postgrest` binary is not installed or available on system `PATH`.
- `docker` engine is not installed or running.
- **Reporting Status:** Honest disclosure. Full end-to-end HTTP PostgREST API and Supabase Auth JWT token-verification acceptance is **reported as unavailable in the local environment and left open** as a deployment/commissioning gate. It is not simulated or claimed as closed via SQL `SET ROLE` shortcuts.

The database-level RLS policies and catalog privileges were previously verified under native PostgreSQL 17 in R2A.1 (`scripts/test_r2a_tenant_isolation.py`), confirming that when roles are assumed, tenant isolation holds across all 11 tables.

---

## 4. Security Regression Test Suite

A dedicated security regression test suite was authored in `tests/test_storage_document_authorization.py`, containing 20 automated tests validating negative controls, defense-in-depth protections, and positive controls:

| Test Identifier | Control Type | Description | Result |
|---|---|---|---|
| `test_cross_tenant_document_download_denied` | Negative Control | Org A attempting to download Org B's document raises `AccessDeniedError`; Storage is not touched. | **PASSED** |
| `test_foreign_document_id_download_denied` | Negative Control | Caller owns Bid A, but passes `doc_id` belonging to Bid B. Access denied. | **PASSED** |
| `test_authorized_document_download_success` | Positive Control | Authorized organization successfully downloads its own document file bytes. | **PASSED** |
| `test_cross_tenant_signed_url_denied` | Negative Control | Org A attempting to generate signed URL for Org B's document raises `AccessDeniedError`. | **PASSED** |
| `test_foreign_document_id_signed_url_denied` | Negative Control | Org A passes foreign `doc_id` for signed URL generation. Access denied. | **PASSED** |
| `test_authorized_signed_url_success` | Positive Control | Authorized organization successfully generates temporary signed URL. | **PASSED** |
| `test_cross_tenant_document_delete_denied` | Negative Control | Org A attempting to delete Org B's document raises `AccessDeniedError`. | **PASSED** |
| `test_foreign_document_id_delete_denied` | Negative Control | Org A attempts to delete document with foreign `doc_id`. Access denied. | **PASSED** |
| `test_authorized_document_delete_success` | Positive Control | Authorized organization deletes own document and associated versions. | **PASSED** |
| `test_cross_tenant_document_replacement_denied` | Negative Control | Org A attempts version replacement specifying Org B's `doc_id`. Access denied. | **PASSED** |
| `test_authorized_document_replacement_success` | Positive Control | Authorized organization uploads new version for own document. | **PASSED** |
| `test_cross_tenant_analysis_report_download_denied` | Negative Control | Org A attempting to download Org B's analysis appendix report raises `AccessDeniedError`. | **PASSED** |
| `test_foreign_run_id_analysis_report_download_denied` | Negative Control | Org A passes `run_id` belonging to foreign bid. Access denied. | **PASSED** |
| `test_authorized_analysis_report_download_success` | Positive Control | Authorized organization downloads analysis report bytes. | **PASSED** |
| `test_storage_path_manipulation_defense` | Negative Control | Verifies `download_file` and `get_signed_url` reject path traversal (`../`) and leading slashes. | **PASSED** |
| `test_database_get_document_signed_url_cross_tenant_denied` | Negative Control | Direct call to `db.get_document_signed_url` across tenant boundary fails closed (empty string). | **PASSED** |
| `test_database_get_document_signed_url_authorized` | Positive Control | Direct call to `db.get_document_signed_url` with valid org and document succeeds. | **PASSED** |
| `test_database_save_upload_mismatched_bid_and_doc_id_raises` | Defense in Depth | Direct call to `db.save_upload` with mismatched `bid_id` and `doc_id` raises `ValueError`. | **PASSED** |
| `test_missing_caller_context_fails_closed` | Negative Control | Empty string or `None` organization context fails closed before reaching database client. | **PASSED** |
| `test_upsert_document_cross_tenant_denied` | Negative Control | Org A attempting to update document metadata of Org B's document raises `AccessDeniedError`. | **PASSED** |

### Existing Suite Verification:
- `test_final_interactive_cutover.py`: **22/22 PASSED**
- `test_auth_tenancy.py`: **56/56 PASSED**
- `test_migration_023_base_rls.py`: **6/6 PASSED**
- `test_tenant_rls_enforcement.py`: **45/45 PASSED**
- `test_r2a_tenant_isolation.py`: **100% PASSED** (Live PostgreSQL 17 disposable instance acceptance matrix)
- `test_app_analysis_panel.py`, `test_fast_analysis_raw_snapshot.py`, `test_full_analysis_ma2a.py`: **111/111 PASSED**

---

## 5. Beta Functionality Preservation

All critical user workflows required for the Phoenix Consulting beta were inspected and preserved:
1. **User Authentication & Session Resolution:** Handled through `auth_session.py` and `tenancy.resolve_organization_context`, ensuring a clean fail-closed gate at startup.
2. **Bid Creation:** Supports both manual creation and AI-assisted extraction intake via `tenancy.create_bid_for_organization()`.
3. **RFP & Document Ingestion:** Fully operational through `tenancy.upload_document_for_organization()`.
4. **Fast Analysis Execution:** Analysis service starts cleanly via `tenancy.start_fast_analysis_for_organization()`, populates intelligence cards, and computes readiness metrics.
5. **Full Analysis Execution:** Multi-specialist analysis engine runs via `tenancy.start_full_analysis_for_organization()`.
6. **Report Generation & Download:** Bid Intelligence Brief export and Full Intelligence Appendix download remain fully functional through tenant-scoped boundaries.

---

## 6. Verification and Acceptance Summary

| Check Item | Requirement | Status | Evidence |
|---|---|---|---|
| **Document/Storage Authorization** | Require authentication, org membership, and bid/doc ownership | **COMPLETE** | `tenancy.py` (8 new authorized primitives) |
| **Caller-Controlled Storage Paths** | Prevent path manipulation and bypass | **COMPLETE** | Path validation & traversal rejection in `database.py` |
| **Service-Role Inventory** | Ensure authorization precedes execution | **COMPLETE** | Section 2 inventory & full code cutover |
| **API Boundary Status** | Report local Auth/PostgREST runtime status honestly | **REPORTED OPEN** | Section 3 honest disclosure |
| **Security Regression Tests** | Full negative/positive controls | **COMPLETE** | `tests/test_storage_document_authorization.py` (20/20 passing) |
| **Beta Functionality** | Preserved core intake, analysis, reports | **COMPLETE** | Zero regressions in test suites |
| **Repository Discipline** | Work strictly in isolated recovery worktree | **COMPLIANT** | `C:\Users\feras\Documents\Projects\Bid-Intelligence-Recovery` |

### Handoff Notice:
Package R2A.2 implementation is complete on branch `recovery/r2a-tenant-security`. All changes have passed strict static and dynamic checks. This report and worktree are hereby submitted to Codex for independent verification review.
