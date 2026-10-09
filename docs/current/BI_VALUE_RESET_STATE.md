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
- **BI-VALUE-3**: **COMPLETE** (Decision-Brief Synthesis Engine & Output Delivery)

## Epistemic Grounding Contract (BI-VALUE-1.1 through BI-VALUE-3)
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
- Architecture Note: `docs/current/DECISION_BRIEF_RECONSTRUCTION_ARCHITECTURE.md`
- Decision Brief Synthesis Engine: `decision_brief.py`
- Executive Report Renderer: `decision_brief_report.py`
- Benchmark Test Suite: `tests/test_york_decision_brief_benchmark.py` (21 deterministic tests)
- Decision Brief Test Suite: `tests/test_decision_brief.py` (20 deterministic tests)
- Auto Identity Test Suite: `tests/test_procurement_identity.py` (13 deterministic tests)
- Governed Buyer Research Test Suite: `tests/test_buyer_research.py` (17 deterministic tests)
- Buyer Source Authority Test Suite: `tests/test_buyer_source_authority.py` (20 deterministic tests)
- Migration: `migrations/026_buyer_research_runs.sql` (APPLIED LIVE; durable buyer research runs table)
- Output Artifacts: `output/YORK_P27_070_DECISION_BRIEF.pdf` & `output/YORK_P27_070_DECISION_BRIEF.md`

## Verification Status
- Branch: `feature/bi-value-reset-v2`.
- Targeted Value Reset Tests: 99/99 passed (21 benchmark + 20 decision brief + 13 identity + 17 research + 20 authority + 8 understand brief).
- Benchmark Integrity: Bid 1522 verified 100% untouched and preserved (Pre-state SHA-256 == Post-state SHA-256 `296959b3335b94c3c8143b1bc7b4f521e846c8217aae2fce1867a61f0d11258e`; 0 mutations).

## BI-VALUE-2.4 (frozen)

source-authority-policy/3: OFFICIAL_BUYER requires positive ownership proof (buyer-reflecting procurement-package domain, registrable-root page self-identity, copyright notice, or @domain contact email). Research constrained to site:<canonical root>. Foreign .gov rejected for Canadian buyers. Live York commissioning (disposable bid 1614, deleted): COMPLETE, 3 searches, 6 pages, 14 signals, verified domain yorku.ca, 0 york.ac.uk/york.edu hits; new-process reuse REUSED_COMPLETE with 0 provider calls; Bid 1522 snapshot unchanged. Full suite: 3934 passed.

## BI-VALUE-3 (COMPLETE)

Reconstructed the primary Bid Intelligence Decision Brief:
- **Architecture**: `decision_brief.py` normalized contract (`DecisionBriefInput`), deterministic synthesis and selection engine (`build_decision_brief`, `build_decision_brief_from_analysis`), post-synthesis claim validation (`validate_claims`), and `decision_brief_report.py` executive 8-page ReportLab renderer.
- **Decision Denseness**: Exactly 8 pages, 2,912 words answering all 8 core decision-maker questions:
  1. What the buyer is buying: Substantive scope (venture beneficiaries, B2B sales/applied AI workshops, 1-on-1 mentorship).
  2. Why it matters: Strategic context (YSpace accelerator hub, Schulich ExecEd workforce initiative, BPS directives).
  3. Kind of provider: Commercial B2B practitioner with pre-existing curriculum and deep bench (backup instructors).
  4. Technical capabilities: All 13 core York technical capabilities surfaced with exact requirements, proof needed, scoring impact.
  5. How proposals are judged: Exact mathematical model: Written = 100 (Technical = 80 [Methodology 45, Qualifications 35], Financial = 20), conditional Short List Presentation = +20; explicit confirmation of no unstated threshold.
  6. What must be proven: Strict separation of mandatory RFP facts (3 references, named CVs, sample framework, Form 9.0, price schedule) from recommended strategies (bench redundancy matrix, prompt library).
  7. Blockers & Commercial risks: Highlighted MERX gate, 6 Bonfire PDF files, non-reimbursable travel expenses, advance subcontractor approval.
  8. Pre-writing resolutions: Top 6 prioritized actionable next steps and targeted Bonfire clarification questions.
- **Output Metrics**: 8 pages, 2,912 words, 22 source items, 4 interpretations, 3 recommendations, 4 unknowns.
- **Benchmark Acceptance**: Passes all 21 gates of `test_york_decision_brief_benchmark.py` and all 20 gates of `test_decision_brief.py`. Zero provider calls, zero DB mutations on Bid 1522.

