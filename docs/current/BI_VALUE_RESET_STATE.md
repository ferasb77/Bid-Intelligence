# Bid Intelligence Value Reset State

## Overview
This document records the baseline state of the Bid Intelligence Value Reset (BI-VALUE-1 & BI-VALUE-1.1), tracking the benchmark contract, gap analysis, and epistemic boundaries established for the York University RFP P27-070 decision brief.

## Deletion Infrastructure Status: Complete & Frozen
- Migrations 024 and 025 applied live and verified.
- Disposable duplicate opportunities (Bids 1517 and 1547) successfully deleted with zero orphaned database rows or Storage objects.
- Deletion and cascade architecture is **FROZEN**. Do not return to deletion, cascade, or governance infrastructure unless an actual production defect appears.

## Authoritative Live Benchmark
- **Bid ID**: `1522`
- **Buyer / Client**: York University
- **Title**: P27 070 Sales and AI Training and Mentorship Program(PDF)
- **Governance State**: `governed` (Procurement Revision 2)
- **Analysis Baseline**: Run 57 (`FULL`, `COMPLETE`)
- **Preservation Status**: Verified 100% untouched and unchanged through multi-stage deletion commissioning.

## BI-VALUE Roadmap Status
- **BI-VALUE-1**: **COMPLETE** (York Decision-Brief Benchmark & Product Contract)
- **BI-VALUE-1.1**: **COMPLETE** (Benchmark Evidence Discipline & Truth Boundary Classification)
- **BI-VALUE-2**: **COMPLETE** (Auto Procurement Identity + Governed Buyer Research)
- **BI-VALUE-2.1**: **COMPLETE** (Durable Research Persistence, SSRF Defense & Provider Governance)
- **BI-VALUE-2.2**: **COMPLETE & ACCEPTED** (Live Durability Commissioning, Anthropic Defaults, Deterministic Identity Metadata & Final Product Boundary)
- **BI-VALUE-3**: **NEXT** (Decision-Brief Synthesis Engine & Output Delivery)

## Epistemic Grounding Contract (BI-VALUE-1.1, BI-VALUE-2, BI-VALUE-2.1, BI-VALUE-2.2)
The benchmark strictly enforces separation of truth classes across every section:
1. `RFP FACT`: Explicitly stated facts grounded in buyer-issued documents with exact locators.
2. `EXTERNAL BUYER FACT`: Factual intelligence regarding the buyer verified from public records outside the RFP via bounded, governed buyer research (Max 3 searches, Max 6 accepted official pages, verbatim extract verification, durable database persistence in `buyer_research_runs`). Strictly factual; evaluative advice, strategy, or win probabilities are strictly prohibited.
3. `BID INTELLIGENCE INTERPRETATION`: Analytical inferences derived by Bid Intelligence specialists from facts.
4. `BID STRATEGY / PROOF RECOMMENDATION`: Actionable advisory recommendations for proposal teams.
5. `UNKNOWN / UNSTATED`: Topics where information was not provided in RFP documents.

## Authoritative Artifacts
- Benchmark Document: `docs/current/YORK_P27_070_DECISION_BRIEF_BENCHMARK.md`
- Gap Analysis: `docs/current/YORK_P27_070_CURRENT_REPORT_GAP_ANALYSIS.md`
- Benchmark Test Suite: `tests/test_york_decision_brief_benchmark.py` (21 deterministic tests)
- Auto Identity Test Suite: `tests/test_procurement_identity.py` (13 deterministic tests)
- Governed Buyer Research Test Suite: `tests/test_buyer_research.py` (17 deterministic tests)
- Migration: `migrations/026_buyer_research_runs.sql` (APPLIED LIVE; durable buyer research runs table)

## Verification Status
- Branch: `feature/bi-value-reset-v2`.
- Test Suite: 51/51 targeted value reset tests passing; full repository test suite (3914 passed, 0 failures, 0 provider calls in automated test runs).
- Live Commissioning: Verified on live disposable Bid 1600. Auto-identity cleanly resolved York University; governed buyer research executed via Anthropic tools (3 searches, 6 accepted pages, 18 signals); durable row persisted in `buyer_research_runs` (ID 3, status `COMPLETE`).
- New-Process Exact Reuse: Verified in independent Python process executing with 0 searches, 0 fetches, 0 provider calls (`REUSED_COMPLETE`, `cached_reuse=True`, `run_id=3`).
- Cascade Deletion & Cleanup: Disposable Bid 1600 deleted via `tenancy.delete_bid_for_organization(...)`; verified 100% cascade cleanup across `bids`, `buyer_research_runs`, and Supabase Storage.
- Benchmark Integrity: Bid 1522 verified 100% untouched and preserved (governed rev 2, Run 57 COMPLETE, 46 events, 12 specialist results, 2 storage objects in `bid-documents`).
- Migration 026: **APPLIED LIVE** to Supabase.
