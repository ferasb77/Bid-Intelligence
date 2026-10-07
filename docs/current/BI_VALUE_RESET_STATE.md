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
- **BI-VALUE-2.3**: **COMPLETE & ACCEPTED** (Buyer Source Authority & Disambiguation Closure: Eliminated token-based matching, content-driven domain verification, strict jurisdiction defense against same-name cross-country entities, cache invalidation via source-authority-policy/2 and buyer-research/2)
- **BI-VALUE-3**: **NEXT** (Decision-Brief Synthesis Engine & Output Delivery)

## Epistemic Grounding Contract (BI-VALUE-1.1 through BI-VALUE-2.3)
The benchmark strictly enforces separation of truth classes across every section:
1. `RFP FACT`: Explicitly stated facts grounded in buyer-issued documents with exact locators.
2. `EXTERNAL BUYER FACT`: Factual intelligence regarding the buyer verified from public records outside the RFP via bounded, governed buyer research (Max 3 searches, Max 6 accepted official pages, verbatim extract verification, durable database persistence in `buyer_research_runs`). Strictly factual; evaluative advice, strategy, or win probabilities are strictly prohibited.
   - **Source Authority & Identity Discipline**: Official buyer domains must be verified against resolved buyer identity, institutional domain ownership, and jurisdiction alignment (`buyer_source_authority.py`).
   - **Cross-Jurisdiction Disambiguation**: Unrelated institutions with identical or similar names (e.g. `york.ac.uk` in the UK or `york.edu` in Nebraska) are rejected as `DIFFERENT_ORGANIZATION` when researching Canadian entities (`yorku.ca`).
   - **Government Oversight Authority**: Domains like `ontario.ca` and `canada.ca` are classified as `GOVERNMENT_AUTHORITY`, strictly distinguished from `OFFICIAL_BUYER`.
3. `BID INTELLIGENCE INTERPRETATION`: Analytical inferences derived by Bid Intelligence specialists from facts.
4. `BID STRATEGY / PROOF RECOMMENDATION`: Actionable advisory recommendations for proposal teams.
5. `UNKNOWN / UNSTATED`: Topics where information was not provided in RFP documents.

## Authoritative Artifacts
- Benchmark Document: `docs/current/YORK_P27_070_DECISION_BRIEF_BENCHMARK.md`
- Gap Analysis: `docs/current/YORK_P27_070_CURRENT_REPORT_GAP_ANALYSIS.md`
- Benchmark Test Suite: `tests/test_york_decision_brief_benchmark.py` (21 deterministic tests)
- Auto Identity Test Suite: `tests/test_procurement_identity.py` (13 deterministic tests)
- Governed Buyer Research Test Suite: `tests/test_buyer_research.py` (17 deterministic tests)
- Buyer Source Authority Test Suite: `tests/test_buyer_source_authority.py` (20 deterministic tests)
- Migration: `migrations/026_buyer_research_runs.sql` (APPLIED LIVE; durable buyer research runs table)

## Verification Status
- Branch: `feature/bi-value-reset-v2`.
- Test Suite: 71/71 targeted value reset tests passing; full repository test suite (3934 passed, 16 skipped, 0 failures, 0 provider calls in automated test runs).
- Live Commissioning: Verified on live disposable Bid 1605. Auto-identity cleanly resolved York University with Canadian jurisdiction (`CA`, `CA-ON`); governed buyer research executed via Anthropic tools (3 searches, 2 accepted pages, 6 signals on verified domain `execed.schulich.yorku.ca`); zero contaminated pages from `york.ac.uk` or `york.edu`. Durable row persisted in `buyer_research_runs` (ID 4, status `COMPLETE`, contract `buyer-research/2`).
- New-Process Exact Reuse: Verified in independent Python process executing with 0 searches, 0 fetches, 0 provider calls (`REUSED_COMPLETE`, `cached_reuse=True`, `run_id=4`).
- Cascade Deletion & Cleanup: Disposable Bid 1605 deleted via `tenancy.delete_bid_for_organization(...)`; verified 100% cascade cleanup across `bids`, `buyer_research_runs`, and Supabase Storage (0 orphan records).
- Benchmark Integrity: Bid 1522 verified 100% untouched and preserved (governed rev 2, Run 57 COMPLETE, 2 storage objects in `bid-documents`, 0 unverified mutations).
- Migration 026: **APPLIED LIVE** to Supabase.

## BI-VALUE-2.4 (frozen)

source-authority-policy/3: OFFICIAL_BUYER requires positive ownership proof (buyer-reflecting procurement-package domain, registrable-root page self-identity, copyright notice, or @domain contact email). Research constrained to site:<canonical root>. Foreign .gov rejected for Canadian buyers. Live York commissioning (disposable bid 1614, deleted): COMPLETE, 3 searches, 6 pages, 14 signals, verified domain yorku.ca, 0 york.ac.uk/york.edu hits; new-process reuse REUSED_COMPLETE with 0 provider calls; Bid 1522 snapshot unchanged. Full suite: 3934 passed.

