# Bid Intelligence — Commissioned Baseline 1

**Tag:** `commissioned-baseline-2026-09-12`
**Status:** frozen release-candidate checkpoint. Not yet pushed unless the normal workflow already authorizes it.

## What was commissioned

The complete, real-corpus, constitutional pipeline was commissioned end to
end, in staged, user-gated phases, against a single real procurement corpus
— not fixtures:

Evidence → Stage A → Stage B → Stage C → Canonical Opportunity → Canonical
Opportunity Publication → Opportunity Structure → Opportunity Structure
Publication → Opportunity Intelligence → Opportunity Intelligence
Publication → Executive Opportunity Understanding → Executive Opportunity
Brief, together with the independent Buyer Brief chain (Buyer Evidence →
Canonical Buyer → Buyer Intelligence → Buyer Brief), composed into one
Executive Briefing Pack.

## Real corpus used

**Bank of Canada RFP 2026-026** ("Talent, Learning and Organizational
Development Services"), corrected 16-document corpus (real PDF/DOCX/XLSX
files, no synthetic fixtures). Full per-file SHA-256 manifest is frozen in
`evaluation/bank_of_canada_briefing_pack/COMMISSIONED_BASELINE_MANIFEST.json`.

## Major correctness defects found and fixed during commissioning

1. **DOCX provenance-granularity defect.** DOCX documents in the real
   corpus carry very sparse real markers relative to their length (e.g. one
   32,000-character document with only 4 real markers). Stage A correctly
   cited real clause headings that were never emitted as their own
   markers, causing Opportunity Structure Publication to fail. Root-caused
   to duplicated, independently-evolving grounding logic across two binding
   adapters; fixed by centralizing into a single shared module
   (`evidence_grounding.py`) implementing a scoped, SECTION-only,
   excerpt-verified hierarchical grounding model. 21 new regression tests.
2. **Unrelated float/DECIMAL serialization gap**, discovered only once the
   provenance fix let commissioning reach further than any prior attempt:
   `opportunity_structure_publication.py`'s semantic-value serializer had
   never encountered a raw Python `float` (an `EVALUATION_CRITERION`
   weight) before. Fixed with a minimal, deterministic `Decimal`-based
   rendering, matching the existing MONETARY-value convention elsewhere in
   the codebase.
3. **Conflict-identity contract defect.** Stage C's own cross-document
   reconciliation pass produces ordinal, Stage-C-local "advisory" conflict
   ids (`CONF-EVAL-1`..`4`, etc.) — proven, by direct test, to be positional
   rather than content-derived and never published as governed objects
   anywhere. These were incorrectly cited by Opportunity Intelligence as if
   they required a governed reference, blocking Executive Opportunity
   Brief. Fixed by distinguishing the two conflict populations (governed
   vs. advisory) at the one point they're cited, with zero information loss
   — every conflict remains fully visible. 20 new regression tests.

Each defect was root-caused to its specific, minimal fix — no validator was
weakened, no evidence was fabricated, and no defect was patched by pattern-
matching on corpus-specific text.

## Final test result

```
1246 passed, 2 skipped, 0 failed, 19 subtests passed
```

## Final pack identity

| Field | Value |
|---|---|
| Pack ID | `pack-b11fe92992b988d51edba6077dc7f1999d864838a7e01acd7e332b3b3faeb600` |
| Pack revision | `pack-revision-8b3b21c79dd82605e7ea70ad5d622905aae826dddd1ce4b343fdb4ad8e945ebe` |
| Pack digest | `pack-digest-1b119bfe385002e2505b416ece164f5b8c4b28c60dda8d8c726dc4542519f943` |

Reproduced identically across two independent process invocations at two
different timestamps.

## Known debt (frozen with this baseline, not fixed here)

Stage D's per-call token volume (~146k input tokens observed), Opportunity
Intelligence's lack of independent VERIFIED/PARTIAL/UNVERIFIED
understanding for most fact families, Opportunity Intelligence's lack of a
live application consumer, Buyer Brief v1's intentionally-empty
procurement-context sections, `DetailRegister.conflicts`'s dead/unrouted
field, the legacy 15-document `scripts/commission_executive_briefing_pack.py`
harness, the Evidence Adapter's continued DOCX coarseness relative to
semantic section labels, and `CONF-EVAL-N`'s permanent advisory (non-
governed) identity. Full detail in
`evaluation/bank_of_canada_briefing_pack/COMMISSIONED_BASELINE.md` §7–8.

## What is explicitly NOT part of this release

- Optimization of any kind
- Latency improvements
- Token reduction
- Prompt compression
- Model, batching, concurrency, caching, or API-routing changes
- Architecture redesign
- Executive Briefing Pack rendering (Markdown/DOCX/PDF) — no renderer exists yet, by design (v1.0.0 scope)
- Any change to Stage A or Stage D

This baseline exists to freeze exactly the behavior that was commissioned —
nothing more. Optimization work begins only under separate, explicit
authorization.
