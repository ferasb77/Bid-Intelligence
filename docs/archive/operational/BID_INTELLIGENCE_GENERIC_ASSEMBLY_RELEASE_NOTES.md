# Bid Intelligence — Generic Assembly Release Notes

**From:** `bid-intelligence-commissioned-v1`
**To:** `bid-intelligence-generic-v1`

Fast Analysis V4's engine is unchanged in intelligence semantics except one additive extraction path (below). This release is about the layer between the engine and the product: report/application assembly is now procurement-agnostic, validated live against a second, materially different real procurement (Canada's Drug Agency) without regressing the first (Bank of Canada).

## Cross-procurement generalization

The report/application adapter (`scripts/fast_analysis_report_adapter.py`, `fast_analysis_app_adapter.py`) previously derived buyer identity, evaluation category structure, response-requirement checklists, and commercial content from a mix of live extraction and hardcoded Bank-of-Canada content, falling back to that hardcoded content whenever a fact was genuinely unextracted. Every one of those fallbacks has been removed. The adapter now:

- Derives buyer/title/dates/evaluation/response/commercial content entirely from the current procurement's own `FastAnalysisResult`.
- Discovers evaluation category/lot structure generically (zero, one, or many categories — never assumed), using one canonical "substantive evaluation row" rule shared by discovery, row-counting, and rendering.
- Preserves criteria whose candidate category didn't have enough company to qualify, in a data-driven "Other Rated Criteria" section — pruned of near-duplicate and restated-total rows using the same procurement-agnostic, structural logic (no vocabulary, no hardcoded names).
- Renders response requirements as a data-driven checklist with real per-item source attribution, with no Appendix-letter assumptions.
- Shows Buyer Intelligence (the one external, hand-curated content layer this release does not redesign) only when the current procurement's own extracted buyer actually matches its one supported buyer — never for any other buyer.

## Commercial extraction (`commercial_supplement`)

Diagnosed root cause: the generic identity/evaluation extraction route explicitly skips commercial clauses (correct when a corpus has a dedicated commercial document, wrong when a corpus's only documents bundle commercial terms alongside everything else). Fixed with one additive, procurement-agnostic Fast Analysis task: for every document that falls back to the generic route, one extra commercial-only extraction pass runs, merging only into that document's commercial output. Never modifies a document's own existing extraction. The progress tracker's `COMMERCIAL_READY` milestone now correctly waits for every commercial-contributing task on a corpus (previously assumed exactly one).

Commercial facts extracted this way now carry real page-level provenance through to the UI's View Source panel (previously dropped when clauses were collapsed into display rows).

## Contamination protections

A permanent regression suite proves one procurement's rendered report can never contain another's identity or content — verified deterministically and confirmed live: zero Bank-of-Canada content in any CDA-AMC surface (persisted structured intelligence, `bid_briefs`, the UI, or the generated PDF) across four independent live runs.

## CDA-AMC commissioning

Canada's Drug Agency's Coaching Services RFSO — a real procurement with no scored category/lot structure, a different document-naming convention, and different real ambiguities — is now commissioned as the second validated procurement. Live commissioning surfaced and fixed, in order: fabricated multi-category structure from stray section/stage labels, missing commercial provenance, a narrower discovery/render-divergence variant of the category defect, and a leftover-bucket defect that let duplicate/restated-total rows through as if they were distinct criteria. Each was diagnosed, classified, fixed deterministically, and re-validated — live where a genuinely new extraction path needed it, from persisted state everywhere else.

## Bank of Canada non-regression

Confirmed unchanged throughout: 20 total evaluation criteria (7 + 7 + 6), Value-add and Relevant Experience & References present, correct ambiguity profile. No Bank of Canada content was live-re-extracted during this work — every regression check used the existing, commissioned Phase 3 baseline deterministically.

## Final category-coherence / leftover-bucket correction

The last defect found: a scope group could pass category discovery on raw occurrence count while collapsing to fewer rows at render time, and separately, the leftover bucket for rejected candidate groups could surface rows that were themselves duplicates or restated section/stage totals rather than genuinely distinct criteria. Both are fixed by one canonical substantive-row predicate shared everywhere a row's inclusion is decided, plus a small, structural (label/weight-only) pruning step scoped to the leftover bucket alone.

## Not in this release

No new visual design, no scoring, no proposal generation, no CRM, no authentication/tenancy changes, no Buyer Intelligence redesign, no Deep Verify changes, no new orchestration architecture, no vector retrieval. Full detail on every decision and every test in `BID_INTELLIGENCE_PHASE4_GENERALIZATION_REPORT.md` and `BID_INTELLIGENCE_PHASE5_GENERIC_ASSEMBLY_REPORT.md`.
