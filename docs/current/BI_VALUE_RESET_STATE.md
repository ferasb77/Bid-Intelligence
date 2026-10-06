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
- **BI-VALUE-3**: **NEXT** (Decision-Brief Synthesis Engine & Output Delivery)

## Epistemic Grounding Contract (BI-VALUE-1.1 & BI-VALUE-2)
The benchmark strictly enforces separation of truth classes across every section:
1. `RFP FACT`: Explicitly stated facts grounded in buyer-issued documents with exact locators.
2. `EXTERNAL BUYER FACT`: Factual intelligence regarding the buyer verified from public records outside the RFP via bounded, governed buyer research (Max 3 searches, Max 6 accepted official pages, verbatim extract verification).
3. `BID INTELLIGENCE INTERPRETATION`: Analytical inferences derived by Bid Intelligence specialists from facts.
4. `BID STRATEGY / PROOF RECOMMENDATION`: Actionable advisory recommendations for proposal teams.
5. `UNKNOWN / UNSTATED`: Topics where information was not provided in RFP documents.

## Authoritative Artifacts
- Benchmark Document: `docs/current/YORK_P27_070_DECISION_BRIEF_BENCHMARK.md`
- Gap Analysis: `docs/current/YORK_P27_070_CURRENT_REPORT_GAP_ANALYSIS.md`
- Benchmark Test Suite: `tests/test_york_decision_brief_benchmark.py` (21 deterministic tests)
- Auto Identity Test Suite: `tests/test_procurement_identity.py` (9 deterministic tests)
- Governed Buyer Research Test Suite: `tests/test_buyer_research.py` (7 deterministic tests)

## Verification Status
- Branch: `feature/bi-value-reset-v2`.
- Test Suite: 37/37 value reset tests passing; repository test suite passing with zero failures and zero provider calls during tests.
- Live Commissioning: Isolated live check of York University official procurement sources verified (Max 2 searches, Max 2 pages, 6 verbatim signals, 0 searches on exact cache reuse). Bid 1522 verified untouched.
