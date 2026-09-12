# Bank of Canada RFP 2026-026 — Executive Opportunity Brief Commissioning Report

**Commissioning run ID:** `eob-boc-2026-026-20260912T163804Z-af7d20` (post-Defect-1-fix attempt; did not complete — see Section D)
**Artifact directory:** `evaluation/bank_of_canada_briefing_pack/executive_opportunity_brief_commissioning/eob-boc-2026-026-20260912T163804Z-af7d20/`
**Outcome: EXECUTIVE OPPORTUNITY BRIEF COMMISSIONING: FAIL (blocked before EOB construction) — reported honestly rather than forced.**

## A. Metadata

| | |
|---|---|
| Phase 1 (Stage A, frozen) | `phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5` |
| Stage B (regenerated, canonical-term-fix) | `phase2-boc-2026-026-stageb-canonterm-fix-20260912T142551Z-34a031` |
| Stage C (refreshed) | `phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8` |
| Canonical Opportunity (accepted) | `canonopp-boc-2026-026-20260912T142551Z-34a031` |
| Opportunity Structure (accepted) | `oppstruct-boc-2026-026-20260912T144353Z-dd4b10` |
| Opportunity Intelligence (accepted) | `oppint-boc-2026-026-20260912T161717Z-50ab1a` |
| Production entry points reached | `procurement_evidence_adapter.adapt_procurement_corpus` → `evidence_publication.publish_evidence` → `canonical_observation_binding.build_observation_bindings` → `canonical_opportunity_publication.publish_canonical_opportunity` → `opportunity_structure.build_opportunity_structure` → `opportunity_structure_binding.build_structure_bindings` **(fails here)** |
| Production entry points never reached | `opportunity_structure_publication.publish_opportunity_structure`, `opportunity_intelligence_publication.publish_opportunity_intelligence`, `executive_opportunity_understanding.build_executive_opportunity_understanding`, `executive_opportunity_brief.build_executive_opportunity_brief`, `render_executive_opportunity_brief` |
| Model used | none — 100% deterministic chain, confirmed by full code inspection before execution |
| Runtime to failure | ~2.4s |

## 1/B. Architecture and dependency trace (established before any code change)

Read in full before executing anything: `executive_opportunity_brief.py` (288 lines), `executive_opportunity_understanding.py` (628 lines), `opportunity_intelligence_publication.py` (963 lines, structurally scanned), `scripts/continue_opportunity_intelligence.py` (the one existing, working end-to-end wiring example).

**`build_executive_opportunity_brief(understanding: ExecutiveOpportunityUnderstanding) -> ExecutiveOpportunityBrief` is a pure, deterministic presentation adapter over exactly one input: an already-validated `ExecutiveOpportunityUnderstanding`.** It adds no content — it only organizes already-published, already-governed objects into 13 fixed sections (`SECTION_ORDER`) and renders references it never re-interprets.

**`ExecutiveOpportunityUnderstanding` is built from exactly one input: `ExecutiveUnderstandingInput(opportunity_id, publication: OpportunityIntelligencePublication)`.** It resolves every reference the publication declares against a fixed rule table (`_RULES`) mapping published object classes (`analysis`, `computed-fact`, `inference`, `hypothesis`/`alternative-hypothesis`, `assumption`, `unknowns`, `limitations`, `management-question`) to one of 11 `DetailRegister` collections and 0–1 of the 13 executive sections. **`unresolved_conflict_ids` (all 8 current Stage C conflicts) are embedded, verbatim, as a semantic field inside the single published `"unknowns"` object — not published as 8 separate objects — and that one object is indexed into the `CONFLICTS_UNKNOWNS_AND_EVIDENCE_GAPS` section.**

**Confirmed, exact dependency answers** (established by exhaustive code reading, not inferred from names):

| Dependency | Answer | Basis |
|---|---|---|
| `BUYER BRIEF DEPENDENCY` | **NO** | Zero references to "buyer" anywhere in `executive_opportunity_brief.py`, `executive_opportunity_understanding.py`, or `opportunity_intelligence_publication.py` — confirmed by exhaustive grep before any assumption was made |
| `OPPORTUNITY INTELLIGENCE DEPENDENCY` | **YES** | The sole real content source — every EOB claim ultimately traces to a published Opportunity Intelligence `DecisionAnalysis` object |
| `OPPORTUNITY STRUCTURE DEPENDENCY` | **YES, indirectly** | Opportunity Structure Publication is one of three snapshots (`evidence_publication`, `canonical_opportunity_publication`, `structure_publication`) the resolution context needs to resolve Opportunity Intelligence's evidence-support links against real governed references |
| `CANONICAL OPPORTUNITY DEPENDENCY` | **YES, indirectly** | same reason |
| `STAGE D DEPENDENCY` | **NO** | Not referenced anywhere in this chain |

No boundary was manually injected to "connect the architecture" — this dependency graph is exactly what the real, working reference pipeline (`scripts/continue_opportunity_intelligence.py`) already implements, pointed at this session's latest, accepted lineage instead of the superseded original-corpus one.

## 3. Input lock

| Artifact | Source | Verified |
|---|---|---|
| 16-document corpus | `evaluation/bank_of_canada_briefing_pack/corrected_procurement_corpus/` | byte-identical SHA-256 match against `corrected_corpus_manifest.json`, which was itself independently verified byte-identical to Phase 1's own `phase1_source_manifest.json` before use |
| Stage C normalized facts + conflicts | `phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8` | the current, accepted, 8-conflict, canonical-term-fixed lineage — not the superseded 7-conflict artifact |
| Canonical Opportunity | embedded in the same Stage C artifact | `input_digest` present and well-formed |

No stale artifact, no 15-document corpus, no historical `corrected_pipeline` output, no Stage A rerun, no Stage D invocation.

## Execution trace

```
Evidence (real corpus, deterministic parse):         PASS — 150 objects
Canonical Opportunity Publication:                    PASS — 134 objects (after Defect fix, Section below)
Opportunity Structure Publication:                    FAIL — StructureBindingError
```

**Everything past this point (Opportunity Structure Publication completion, Opportunity Intelligence Support Binding, Opportunity Intelligence Publication, Executive Opportunity Understanding, Executive Opportunity Brief) was never reached.** No EOB object was ever constructed. Sections D (actual EOB output), E (claim inventory), and most of F–Z below are therefore reported as "not reached" rather than fabricated or inferred.

## Defect 1 (found and fixed): excerpt-grounding whitespace brittleness in `canonical_observation_binding.py`

**Root cause:** `canonical_observation_binding.py`'s `_match_refs()` — a *separate, independent* re-verification of Canonical Opportunity's observation provenance, performed during Evidence/Canonical-Opportunity Publication — used a plain whitespace-*collapsing* (not whitespace-*insensitive*) comparison (`_normalize_text`) for its excerpt-verbatim check. This is the exact same class of defect already found and fixed once in `canonical_opportunity.py` during the contract-term audit (a hyphenated PDF line-wrap and a missing space after label punctuation), but in a **different module with its own independent implementation** that did not inherit that fix. Concretely: the abstract.pdf "Duration: 3 years" observation — already correctly `VERIFIED` by `canonical_opportunity.py`'s own (already-fixed) grounding check — could not be independently re-confirmed by this module's stricter, un-fixed check, and because the observation's status was `VERIFIED` (not `PARTIAL`/`UNVERIFIED`), this module's designed graceful-degradation path did not apply, and it raised `ObservationBindingError` instead of silently excluding the record.

**Constitutional impact:** an observation Canonical Opportunity had already correctly, honestly established as VERIFIED was being blocked from publication entirely — not silently mis-stated, but unable to proceed at all, which would have blocked the whole Canonical Opportunity Publication boundary over a real, non-fabricated fact.

**Fix:** added `_normalize_excerpt_text()` (whitespace-*stripping*, mirroring `canonical_opportunity._grounding_norm` exactly), used only for the excerpt-verbatim comparison; locator normalization (`_normalize_text`, used for section/sheet names) was left untouched.

**Regression tests added** (`tests/test_canonical_observation_binding.py`, +3): hyphenated line-wrap still binds, missing-space-after-punctuation still binds, genuinely absent excerpt still fails closed (gracefully, via the PARTIAL/UNVERIFIED path).

**Validation:** `py_compile` clean; `git diff --check` clean; targeted suite 24/24 passed; full repository suite **1201 passed, 2 skipped**. Canonical Opportunity Publication was recommissioned and passed (134 objects) after this fix.

## Defect 2 (found, root-caused, NOT fixed — blocking, large-scope, requires dedicated follow-up)

**What was found:** `opportunity_structure_binding.py`'s independent re-verification (structurally identical in design to `canonical_observation_binding.py`) failed on `oi-requirements-32123fdc…` — a requirement whose `source_refs[0].section` is `"TABLE"`, sourced from `OriginalRevision/RFP 2026-06 - Appendix G - Form of Agreement.docx` — with `"no Evidence occurrence matches SECTION:section:table"`.

**Root cause, confirmed by direct inspection of the real document text (not inferred):** this document contains **exactly 4 real `[[SOURCE: …]]` markers total** — one `SECTION: Header` marker and three bare `TABLE` flag markers (not a `SECTION:` attribute) — covering the entire document. Yet Stage A's extraction cites **11 distinct, specific, human-readable "section" values** for this one document alone (`Header`, `Payment`, `General`, `Representations`, `Services`, `Confidentiality`, `Key Personnel`, `Property Rights`, `Permits, Taxes and Royalties`, `Force Majeure`, `No Publicity`, `Disclosure of Contract`, `TABLE`) — clause headings genuinely present as prose *within* those few large chunks, but never emitted as their own real source markers. The same pattern was independently confirmed for `Appendix D1` (**1 real marker for the whole document**, yet 51 distinct section citations including `Corporate Profile`, `Measurement Approach`, `Relevant Experience and References`, etc. — real clause/subsection headings visible in the text, not real markers).

**Scale, measured directly against the real Evidence snapshot (not estimated):**
```
Distinct affected records: 350 of 692 (50.6%)
Total mismatched source_refs: 388
Affected documents (all .docx, none .pdf/.xlsx): Appendix A, Appendix D1, Appendix D2 (both versions), Appendix D3, Appendix G
By family: requirements 246, commercial_clauses 62, submission_rules 24, evaluation_criteria 12, deliverables 6
```

**This is not a fabrication or a fresh problem introduced by any Stage — it is a genuine, systemic mismatch between Stage A's citation precision and the real marker granularity `procurement_evidence_adapter.py` produces for coarsely-chunked DOCX documents.** For documents with only 1–4 real markers covering their entire content, Stage A evidently uses the clause's own visible heading text as a natural, human-readable "section" label when citing a fact — real, genuine text, but not a marker the Evidence-publication pipeline ever independently emitted, so the strictest, most-downstream verification layer correctly cannot corroborate it.

**A precise, important interaction with this session's own earlier work:** replaying the pre-fix `_locator_matches()` logic against this exact record shows that **before the contract-term audit's Defect-1 fix, this specific class of citation would have correctly resolved to `PARTIAL`/`UNVERIFIED` provenance** (a `TABLE`-flag marker publishes no `section` value at all, and the old, stricter code treated "marker publishes nothing" as a mismatch against any non-null requested section) — which would have let `opportunity_structure_binding.py`'s designed graceful-degradation path apply (empty binding, no raise), exactly as it is designed to do for genuinely weak provenance. **The contract-term audit's fix — correct and already validated for its intended, narrow case (2 real observations with a genuinely accurate page+section citation against a page-only PDF marker) — has the broader, unintended side effect of promoting this much larger class of DOCX citations (a real heading, but not a real marker) from `PARTIAL`/`UNVERIFIED` to `VERIFIED`, which removes the safety net that would otherwise have let Opportunity Structure Publication proceed past these 350 records with an honest, empty provenance binding rather than a hard failure.**

**Why this was not fixed in this session:** the two options available — (a) further narrowing `canonical_opportunity.py`'s `_locator_matches` relaxation to distinguish "a marker that genuinely lacks section granularity" from "a marker that is a generic flag/placeholder unrelated to the requested section text," or (b) changing how coarsely-marked DOCX documents are chunked/marked upstream — both require careful, dedicated design and verification against the *already-accepted, already-tested* contract-term audit fix, at a scale (350 records, 6 documents) far beyond "smallest root cause" for this commissioning pass. Attempting a rushed fix here risks either regressing the already-validated contract-term audit result or introducing a new, insufficiently-verified special case. Per instruction ("do not weaken validators," "do not modify upstream truth solely to simplify presentation"), this was not attempted.

**Recommendation:** a dedicated, separately-scoped audit of `_locator_matches`'s section/sheet relaxation is needed — specifically, distinguishing "the marker publishes no section info, but the ref's section value is independently plausible for this document" (safe, the contract-term audit's real case) from "the marker publishes no section info because it is a flag/placeholder marker with no substructure at all, and the ref's section value doesn't correspond to any real marker text" (unsafe, this finding's case). Until that is done, Opportunity Structure Publication — and therefore Executive Opportunity Brief — cannot complete for this corpus without either fabricating provenance or (correctly) failing closed, which is what happened here.

## D–Z. Sections not reached

Because `ExecutiveOpportunityBrief` was never constructed, the following sections cannot be populated with real product output — populating them now would mean inventing content the system itself never produced, which this audit's entire purpose is to prevent:

**D (actual EOB output), E (claim inventory), F (source-type separation), G (Buyer Brief contribution — moot, confirmed zero dependency), H (Opportunity Intelligence contribution), I (8-conflict trace within EOB), J (4 Opportunity Structure ambiguity trace within EOB), K (contract-term safety within EOB), L (D1/D2/D3 safety within EOB), M (procurement-model safety within EOB), N (evaluation-priority safety within EOB), O (buyer-intent audit within EOB), P (commercial/legal compression), Q (missing-information handling within EOB), R (recommendation safety within EOB), S (master RFP contribution within EOB), T (evidence ownership within EOB), U (compression audit), V (external-knowledge audit within EOB), W (rejected-record safety within EOB), X (identity/revision/digest for the EOB object itself).**

What *can* be reported honestly from the boundaries that did complete:
- **Rejected-record safety, Evidence and Canonical Opportunity Publication layers:** the 2 Stage B `ZERO_VALID_PROVENANCE` records were not touched by anything in this chain up to the point of failure (confirmed — Canonical Opportunity Publication's 134 objects derive from the same 120-observation ledger already audited clean in the Canonical Opportunity commissioning; `REJECTED RECORD RE-ENTRY: 0` holds for everything reached).
- **8-conflict / 4-Opportunity-Structure-ambiguity preservation up to the point reached:** Opportunity Intelligence itself (already independently commissioned and accepted) correctly represents all 8 conflicts in `unresolved_conflict_ids`; this was re-confirmed reachable in this chain (`analyze_opportunity()` was re-invoked identically) before the pipeline failed at a later, unrelated boundary (Opportunity Structure Publication, which does not consume Opportunity Intelligence's conflict list at all).

## Y. Validation / anomalies

| Check | Result |
|---|---|
| Evidence Publication | PASS, 150 objects |
| Canonical Opportunity Publication | PASS, 134 objects (after Defect 1 fix) |
| Opportunity Structure Publication | **FAIL** — `StructureBindingError`, 350/692 records affected |
| Opportunity Intelligence Support Binding | not reached |
| Opportunity Intelligence Publication | not reached |
| Executive Opportunity Understanding | not reached |
| Executive Opportunity Brief | not reached |
| Rejected-record re-entry (boundaries reached) | 0 |
| Determinism (boundaries reached) | Evidence/Canonical Opportunity Publication are deterministic, zero LLM, confirmed by code reading |
| Defects found | 2 (1 fixed, 1 root-caused but deliberately not fixed — see above) |
| Tests added | 3 (`tests/test_canonical_observation_binding.py`) |
| Full-suite result | 1201 passed, 2 skipped |

## Z. Artifact index

- `evaluation/bank_of_canada_briefing_pack/executive_opportunity_brief_commissioning/eob-boc-2026-026-20260912T163804Z-af7d20/boundaries.json` — the complete, real execution trace up to and including the failure
- Code changed: [canonical_observation_binding.py](../../canonical_observation_binding.py) (`_normalize_excerpt_text`, Defect 1 fix), [tests/test_canonical_observation_binding.py](../../tests/test_canonical_observation_binding.py) (+3 tests)
- Diagnostic scans (not persisted as formal commissioning artifacts, reproducible from the commands in this report): the 388-mismatch scan against the real Evidence snapshot, the real-marker counts for Appendix D1 and Appendix G
- Commissioning script: [scripts/commission_executive_opportunity_brief_bank_of_canada.py](../../scripts/commission_executive_opportunity_brief_bank_of_canada.py)

---

## FINAL RESPONSE

- **UPSTREAM INPUT LOCK: PASS**
- **EOB EXECUTION: FAIL** (blocked at Opportunity Structure Publication; EOB itself never constructed)
- **EOB FACTUAL GROUNDING: N/A** — no EOB object exists to audit
- **SOURCE-TYPE SEPARATION: N/A**
- **CONFLICT PRESERVATION: N/A for EOB itself; PASS for every boundary actually reached** (Opportunity Intelligence's 8-conflict representation was re-confirmed intact before the unrelated downstream failure)
- **COMPRESSION SAFETY: N/A**
- **EOB COMMISSIONING: FAIL**
- **Run ID:** `eob-boc-2026-026-20260912T163804Z-af7d20` (terminated with a raised exception rather than a clean artifact directory close; `boundaries.json` records the real execution trace up to the failure)
- **Production function:** chain confirmed through `opportunity_structure_binding.build_structure_bindings`; `executive_opportunity_brief.build_executive_opportunity_brief` never invoked
- **Actual dependencies:** Opportunity Intelligence (yes, sole content source), Canonical Opportunity + Opportunity Structure (yes, indirectly, via publication snapshots), Buyer Brief (no), Stage D (no) — all confirmed by code reading, not assumption
- **Buyer Brief dependency:** NO
- **Opportunity Intelligence dependency:** YES
- **Opportunity Structure dependency:** YES (indirect, via publication)
- **Stage D dependency:** NO
- **LLM used?** No — 100% deterministic chain up to the point of failure
- **Model/call count / tokens / cost:** n/a — 0
- **Total claim count / procurement fact count / buyer fact count / computed fact count / inference count / hypothesis count / uncertainty count / recommendation count:** not applicable — EOB was never constructed
- **Unsupported buyer-intent count:** 0 (nothing was generated to contain one)
- **Unsupported external-knowledge count:** 0
- **Evidence ownership error count:** 0 in the boundaries reached; the blocking failure is itself a *correct*, fail-closed evidence-ownership rejection, not a laundering incident
- **Compression material-change count:** n/a
- **All 8 conflict outcomes:** not applicable to EOB (never built); re-confirmed intact (category A, explicitly represented) at the Opportunity Intelligence layer immediately before the unrelated downstream failure
- **Contract-term outcome:** not applicable — EOB never built
- **D1/D2/D3 outcome:** not applicable — EOB never built
- **Procurement-model outcome:** not applicable — EOB never built
- **Rejected-record re-entry count:** 0 (for every boundary actually reached)
- **Defects found/fixed:** 2 found; 1 fixed (`canonical_observation_binding.py` excerpt-grounding whitespace brittleness); 1 root-caused but deliberately left unfixed pending dedicated follow-up (see "Defect 2" above) — a 350-of-692-record-scale interaction between Stage A's DOCX section-citation precision and this session's own earlier, already-accepted `_locator_matches` fix
- **Tests added:** 3
- **Full-suite result:** 1201 passed, 2 skipped
- **Runtime:** ~2.4s to failure
- **EOB identity/revision/digest:** not applicable — no `ExecutiveOpportunityBrief` object was ever constructed
- **Report path:** [evaluation/bank_of_canada_briefing_pack/BANK_OF_CANADA_EXECUTIVE_OPPORTUNITY_BRIEF_COMMISSIONING_REPORT.md](evaluation/bank_of_canada_briefing_pack/BANK_OF_CANADA_EXECUTIVE_OPPORTUNITY_BRIEF_COMMISSIONING_REPORT.md)
- **Raw artifact paths:** `evaluation/bank_of_canada_briefing_pack/executive_opportunity_brief_commissioning/eob-boc-2026-026-20260912T163804Z-af7d20/`

**Recommendation: DO NOT AUTHORIZE Executive Briefing Pack.** Executive Opportunity Brief itself is currently blocked, not merely unauthorized. A dedicated, carefully-scoped fix to the section/sheet-locator matching asymmetry between `canonical_opportunity.py`'s upstream provenance check and the independent Evidence-Publication binding layer (`canonical_observation_binding.py`/`opportunity_structure_binding.py`) is required before this boundary can be recommissioned — this affects roughly half of Opportunity Structure's records across 6 DOCX-sourced documents and should not be resolved under time pressure within a single commissioning pass. Per instruction, this commissioning stops here regardless.
