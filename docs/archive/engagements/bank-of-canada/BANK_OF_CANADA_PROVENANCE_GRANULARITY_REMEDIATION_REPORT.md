# Bank of Canada RFP 2026-026 — Provenance Granularity Remediation Report

**Scope:** dedicated audit and remediation of the DOCX provenance-granularity
defect exposed during Executive Opportunity Brief commissioning (run
`eob-boc-2026-026-20260912T163804Z-af7d20`, which failed at Opportunity
Structure Publication). No Stage A rerun. No LLM calls anywhere in this
remediation. Frozen, authoritative lineage:
`phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5`.

---

## A. Validator map

| Module / function | Used by | Validates locator against | Validates excerpt against | Missing-granularity behavior | Failure state |
|---|---|---|---|---|---|
| `extractor.validate_source_refs` | Stage B `requirements`/`submission_rules`/`dates`/`evaluation_criteria` directly; `deliverables`/`commercial_clauses` indirectly via `contract_hygiene._verified_refs` | page bounds, sheet existence, row ranges (never `section`) | any 1 of up to 6 sampled words (>3 chars) anywhere in the full doc text | permissive — `section` is passed through unvalidated | sets `verified: bool` on the ref |
| `contract_hygiene._verified_refs` | Stage B `deliverables`/`commercial_clauses` `evidence_state` | delegates entirely to `validate_source_refs` | delegates entirely | same as above | filters to `verified is True` |
| `canonical_opportunity._validate_ref` / `_locator_matches` / `_source_segment` / `_grounding_norm` | `build_canonical_opportunity` (typed_observations); reused directly by `opportunity_structure.build_opportunity_structure` for all 5 families | walks the SAME real `[[SOURCE: ...]]` markers in `doc_texts`; a marker that does not publish `section`/`sheet` at all cannot refute a citation against it (first-match, not best-match) | whitespace-stripped verbatim containment in the segment following the first `_locator_matches`-satisfying marker | permissive on the locator dimension by design (pre-existing, already-accepted fix); first-match search, not exhaustive | sets `provenance_status`: VERIFIED (grounded AND locator), PARTIAL (either), UNVERIFIED (neither) |
| `evidence_grounding.match_refs` (NEW, this remediation) | `canonical_observation_binding.build_observation_bindings`, `opportunity_structure_binding.build_structure_bindings` | exact dictionary lookup against real, already-published `EvidenceOccurrence` objects; SECTION-only coarser fallback searches ALL occurrences in the artifact | whitespace-stripped verbatim containment, re-confirmed against the resolved occurrence's own `EvidenceExtract` | fails closed unless excerpt uniquely, verbatim grounds exactly one real occurrence (SECTION only) | raises `ObservationBindingError`/`StructureBindingError` via caller's `fail` callback |
| `stage_d_projection.validate_stage_d_response` | Stage D | consumes already-computed `provenance_status`/support pointers; not an independent grounding implementation | n/a | n/a | not part of the duplicated-logic population |

**Duplication found and eliminated:** `canonical_observation_binding.py` and
`opportunity_structure_binding.py` previously carried independent,
near-identical copies of locator/excerpt matching (confirmed structurally
identical — `opportunity_structure_binding.py`'s own docstring said "Mirrors
canonical_observation_binding.py exactly"). A fix applied to one
(`canonical_observation_binding.py`'s whitespace-stripping excerpt fix,
mid-EOB-commissioning) left the other's copy stale — a demonstrated defect
source, not a hypothetical risk. Both now import a single shared
implementation, `evidence_grounding.py` (see Section G).

`canonical_opportunity.py`'s own `_validate_ref`/`_locator_matches` was
**not** touched. It sets the ledger's own `provenance_status` and was already
validated by the earlier, accepted contract-term audit; its "unpublished
dimension cannot refute a citation" relaxation is load-bearing for that
audit's conclusions. See Section E/F for why this file was deliberately left
out of scope.

---

## B. Physical evidence contract per source type (from the real corpus, not inference)

- **PDF** (`abstract.pdf`, main RFP PDF): one `EvidenceOccurrence` per real
  `PAGE:` marker; fine-grained, bounded, enumerable. Sections are never the
  real locator dimension for these documents.
- **XLSX** (10 files): one `EvidenceOccurrence` per real `SHEET:`+`ROWS:` (or
  bare `ROWS:`) marker; bounded, enumerable (Stage B's `validate_source_refs`
  already checks sheet existence and row bounds independently).
- **DOCX** (6 files: Appendix A, D1, D2, D2-REVISED, D3, G): real markers are
  extremely sparse relative to document length. Appendix G has exactly 4 real
  markers for a 32,000+ character document: 3 bare `TABLE` flags (5–37 chars
  of following content each — table-cell artifacts, not prose) and 1
  `SECTION: Header` marker whose extract is the entire remaining document
  body (32,035 chars). Appendix D1 has 1 real marker total. Stage A's
  extraction frequently cites a real, human-readable clause heading visible
  *within* that large chunk's prose (e.g. "Payment", "Force Majeure",
  "Property Rights") as a `section` value — but that heading was never
  itself emitted as a distinct `SECTION:` marker. This is the entire,
  confirmed physical shape of the defect; it is not hypothetical and was
  verified by direct document-text inspection, not inferred.

---

## C. Classification of DOCX source_refs whose locator has no exact real-occurrence match

Computed by `scripts/diagnose_provenance_granularity_bank_of_canada.py`
against the frozen lineage (no Stage A rerun), deduplicated across both
Canonical Opportunity observations and Opportunity Structure records.
Persisted at
`evaluation/bank_of_canada_briefing_pack/provenance_granularity_remediation/classification.json`.

| Class | Definition | Count |
|---|---|---|
| **A** — exact physical match | locator resolves to exactly one real `EvidenceOccurrence` | 257 |
| **B** — coarser, uniquely grounded (the legitimate case) | no exact locator match, but the excerpt is verbatim in exactly one real occurrence's extract | 103 |
| **C** — coarser, ambiguously grounded | excerpt verbatim in more than one real occurrence | **0** |
| **D** — invalid / not grounded anywhere real | excerpt not verbatim in any real occurrence for the document | 42 |

403 distinct DOCX refs classified (one additional ref carries neither an
exact locator nor an excerpt and is excluded from this table by
construction — it fails the strict exact-locator path directly, unaffected
by this remediation).

**Critical, empirically-confirmed finding:** of the 42 Class D refs, **all
42 (100%) already carry an upstream entity-level `provenance_status` of
PARTIAL**, none VERIFIED. `canonical_opportunity.py`'s own, independent
`_validate_ref`/`_source_segment` check — which walks the same real markers
against the same `doc_texts` — already fails to ground these excerpts and
correctly does not mark them VERIFIED. **No separate upstream
over-verification defect exists for Class D.** The binding layer's
pre-existing PARTIAL/UNVERIFIED graceful-fallback-to-empty-binding policy
already covered every genuinely-ungrounded case correctly, with zero code
change required. This was verified empirically, not assumed (see Section I).

Of the 103 Class B refs, 102 belong to entities whose overall
`provenance_status` is PARTIAL (grounded via this specific ref, but pulled
down by a sibling ref elsewhere in the same observation/record) and 1
belongs to an entity that is fully VERIFIED — that single entity is the one
whose unresolvable binding actually halted the original EOB run (a single
raised exception stops the whole publication on first failure, so the
original run never surfaced a count).

---

## D. Appendix G forensic table (representative — full table in `appendix_g_forensic.json`)

Real markers in Appendix G: 3× `OTHER_EXACT:exact:TABLE` (5–37 chars each) +
1× `SECTION:section:Header` (32,035 chars — the entire remaining document).
156 distinct (section, excerpt) citations against this document were
evaluated:

| Correct status | Count |
|---|---|
| EXACT (Class A) | 99 |
| VERIFIED-BY-COARSER-GROUNDING (Class B) | 32 |
| UNGROUNDED (Class D) — must not bind | 25 |

Representative rows:

| Stage A `section` | Excerpt (truncated) | Published marker/extract | Text grounded? | Section physically represented? | Correct status |
|---|---|---|---|---|---|
| Payment | "The amounts payable by the Bank under this Agreement do not include an…" | `SECTION:section:Header` (coarse, whole-document) | YES, uniquely | NO (no `SECTION: Payment` marker exists) | Class B — bind to the coarser real occurrence, do not fabricate a "Payment" locator |
| Property Rights | "The Service Provider hereby assigns and transfers to the Bank the worl…" | `SECTION:section:Header` | YES, uniquely | NO | Class B |
| Confidentiality | "The Service Provider shall keep the Confidential Information strictly…" | none | NO — not verbatim anywhere real | NO | Class D — must fail closed; correctly left PARTIAL upstream, correctly produces an empty binding |
| (various, exact) | (various) | matching real marker exactly | YES | YES | Class A — unaffected by this remediation |

**Conclusion from Appendix G:** the defect is **adapter under-granularity**
interacting with **Stage A's use of real, semantically-correct headings that
were never emitted as markers** — not Stage A over-specificity (Stage A's
citations are, in the Class B cases, accurate reflections of the real
document structure; the adapter simply never materialized that structure as
enumerable markers) and not a validator that is wrong to reject an
unsupported label — see Section E for the precise root-cause split.

---

## E. Root causes (kept separate, not collapsed into one "citation bug")

- **(A) Evidence Adapter granularity defect — primary, confirmed root cause.**
  `procurement_evidence_adapter.py` materializes one `EvidenceOccurrence` per
  real marker only; for DOCX documents with sparse markers, this produces
  occurrences far coarser than the semantic structure Stage A correctly
  perceives in the prose. This is not fixed in this remediation (fixing the
  adapter to synthesize finer-grained occurrences from unmarked headings
  would itself require inventing evidence structure that was never really
  emitted — out of scope and explicitly the kind of fabrication this
  remediation exists to prevent). Instead, the binding layer is taught to
  correctly attribute a citation to the coarser real occurrence that
  actually, uniquely proves it (Model 2).
- **(B) Stage A provenance-shape defect — not confirmed.** Stage A's
  `section` citations in the Class B population are accurate descriptions of
  real document content; this is not a Stage A defect.
- **(C) Validator semantic defect — confirmed, in `canonical_opportunity.py`,
  left unfixed by design.** `_source_segment` stops at the *first* marker
  satisfying `_locator_matches` rather than searching all candidates; a
  citation whose true grounding lives past a different, later real marker
  could in principle be under-verified (marked PARTIAL/UNVERIFIED when a
  fuller search would find it VERIFIED). This is the *opposite* direction
  from the crisis being remediated (under- not over-verification) and does
  not compromise fail-closed safety. Documented as a remaining limitation
  (Section O), not fixed here per "do not blindly refactor" and to avoid
  disturbing the already-accepted contract-term audit's dependency on this
  function's current behavior.
- **(D) Validator over-permissiveness defect — confirmed, but proven benign
  for this population.** `_locator_matches`'s "an unpublished dimension
  cannot refute a citation" relaxation is what allows Class B AND Class D
  refs alike to reach the excerpt-grounding check. Empirically (Section C),
  every Class D ref is still correctly kept at PARTIAL by the excerpt check
  — the permissiveness never manifests as a VERIFIED-but-fabricated status
  for genuinely ungrounded content in this corpus. Not changed in this
  remediation.
- **(E) Duplicate validator implementations — confirmed, primary defect
  source, fixed.** `canonical_observation_binding.py` and
  `opportunity_structure_binding.py` carried independently-evolving copies
  of the same matching algorithm; one already went stale relative to the
  other mid-way through EOB commissioning (Defect 1). Eliminated by
  centralizing into `evidence_grounding.py` (Section G).

---

## F. Chosen granularity model: **MODEL 2 (HIERARCHICAL)**

Implemented in the binding/publication layer (`evidence_grounding.py`), not
by further modifying `canonical_opportunity.py`. A finer semantic label
Stage A cites may bind to a coarser real physical occurrence only when:

1. no exact locator match exists, **and**
2. the ref carries an excerpt, **and**
3. the ref's locator dimension is `SECTION` specifically (never `PAGE` or
   `RECORD` — those are bounded, enumerable, and already independently
   validated by Stage B's `validate_source_refs`; a page/row mismatch is
   always a genuine citation error, never coarser precision), **and**
4. the excerpt is verbatim (whitespace-insensitive) in exactly one real
   occurrence's extract for that artifact — ambiguity (more than one owner)
   fails closed, never picks arbitrarily.

MODEL 1 (strict exact-match-only) was rejected: it is what the pipeline
already did, and it is what crashed. MODEL 3 (excerpt-alone, locator
irrelevant) was rejected as too permissive: it would let a genuinely
mismatched locator be silently ignored whenever any excerpt happens to
appear somewhere in the document, which is exactly the wrong-PAGE-rescue bug
caught and fixed during this remediation's own test regression (Section J).
Model 2, scoped strictly to the free-text SECTION dimension, is the model
actually supported by the confirmed defect shape in Section B/D.

The locator label itself never substitutes for or coerces a different
locator's identity — only the excerpt's own unambiguous verbatim presence
establishes the coarser-occurrence relationship (see
`evidence_grounding.match_refs` docstring).

---

## G. Centralization

`evidence_grounding.py` (new module) is now the single implementation of
locator/excerpt matching for both `canonical_observation_binding.py` and
`opportunity_structure_binding.py`. Each caller supplies its own `fail`
callback so `ObservationBindingError` / `StructureBindingError` remain
distinct, caller-owned exception types — public contracts unchanged.

**Shared grounding implementation created: YES.**

`canonical_opportunity.py`'s own `_validate_ref`/`_locator_matches` was
deliberately **not** merged into this shared module — it operates on raw
`doc_texts` (pre-Evidence-Adapter), not on published `EvidenceOccurrence`/
`EvidenceExtract` objects, and its output (`provenance_status`) is a
different, already-validated contract this remediation does not disturb. Per
Section E(C), a documented, non-fabricating divergence remains between it
and `evidence_grounding.py` (first-match vs. exhaustive search); centralizing
these two would require redesigning `canonical_opportunity.py`'s own
contract-term-audit-dependent behavior, which is explicitly out of scope.

---

## H. Text-normalization contract (formalized, tested)

- `normalize_locator_text(value)` = whitespace-collapse (preserves word
  boundaries) + casefold. Used for locator/section/sheet-name identity
  comparison only.
- `normalize_excerpt_text(value)` = whitespace-**strip** (no separator) +
  casefold. Used for excerpt verbatim-content comparison only — tolerates
  PDF/DOCX line-wrap hyphenation ("one-\nyear" ↔ "one-year") and
  missing-space-after-punctuation artifacts ("Duration:3 years" ↔
  "Duration: 3 years") without reordering or dropping words. A genuine
  word-order change or word-content difference (tested: "eleven" vs "ten")
  never passes — this is substring containment of normalized text, never
  fuzzy or semantic matching.

Both functions are pure, deterministic, and unit-tested directly (Section
J).

---

## I. Provenance status: before / after

**Upstream `provenance_status` (set by `canonical_opportunity.py` /
`opportunity_structure.py`, both unmodified by this remediation) is
IDENTICAL before and after** — this remediation deliberately does not touch
that determination (Section E/F). This is itself an important, verified
negative result: **no bulk re-verification occurred as a side effect of the
binding-layer fix.**

Current (= unchanged) counts, from
`evaluation/bank_of_canada_briefing_pack/provenance_granularity_remediation/provenance_status_counts.json`:

| Ledger | VERIFIED | PARTIAL | UNVERIFIED |
|---|---|---|---|
| Canonical Opportunity observations | 95 | 23 | 2 |
| Opportunity Structure records | 380 | 309 | 3 |

**What did change: binding-layer outcome**, measured against the same
frozen evidence:

| | Before (exact-locator-only) | After (Model 2 / SECTION fallback) |
|---|---|---|
| Canonical Opportunity Publication | **FAIL** (StructureBindingError-equivalent on the single VERIFIED, Class-B entity — see Section C) | **PASS** — 134 objects |
| Opportunity Structure Publication | **FAIL** (StructureBindingError, halted the entire EOB run at this boundary) | **PASS** — 696 objects |

No 350-record bulk over-verification exists in the corrected classification
(Section C); the earlier, pre-remediation triage estimate of "350/692
records" was an ephemeral, non-persisted scan and is superseded by the
rigorous, reproducible count in this report (257/103/0/42, 403 total DOCX
refs).

---

## J. Tests

**21 new tests** in `tests/test_evidence_grounding.py` (all pass), exercising
`evidence_grounding.match_refs` directly against Appendix-G-shaped fixtures:
exact SECTION match; case/whitespace-normalized exact match; Class-B coarser
fallback success (finer requested section, absent requested section);
coarse-marker-but-ungrounded-excerpt failure; absent-section-and-ungrounded
failure; hyphenated line-wrap grounding through the fallback;
missing-space-after-punctuation grounding through the fallback; word-order
change rejected; different-word (singular/plural-adjacent) rejected; XLSX
sheet+rows exact match unaffected; **PDF page mismatch not rescued by excerpt
content elsewhere** (the regression this remediation's own fallback-scoping
bug required — see below); same guardrail for RECORD (sheet+rows); duplicate
exact section names fail deterministically as ambiguous (checked twice for
determinism); multiple coarse extracts independently containing the same
excerpt fail as ambiguous (synthetic Class-C case, since the real corpus has
zero); grounding result stability across repeated evaluation; unrelated
excerpt sharing only a short substring rejected; `normalize_excerpt_text`/
`normalize_locator_text` unit checks; and two cross-adapter consistency
tests proving `canonical_observation_binding` and `opportunity_structure_binding`
resolve the identical exact ref and the identical Class-B fallback ref to
the same governed object identities.

**Self-caught regression during this remediation:** the first version of the
SECTION-only fallback guard was written as `elif has_excerpt:` (unscoped by
locator kind). This incorrectly rescued a wrong `page="99"` citation in 5
pre-existing tests whenever the excerpt happened to also appear in the
document's real `page:1` occurrence. Fixed by adding
`and locator is not None and locator[0] == "SECTION"` to the guard. This is
now permanently covered by `test_exact_page_mismatch_is_not_rescued_by_excerpt_present_elsewhere`
and `test_exact_record_mismatch_is_not_rescued_by_excerpt_present_elsewhere`.

**53 tests pass** across `tests/test_evidence_grounding.py` (21),
`tests/test_canonical_observation_binding.py` (24, unchanged), and
`tests/test_opportunity_structure_binding.py` (8, unchanged) — zero
regressions in either binding adapter's pre-existing behavior.

---

## K. Full suite result

```
py_compile evidence_grounding.py canonical_observation_binding.py
           opportunity_structure_binding.py opportunity_structure_publication.py
           tests/test_evidence_grounding.py tests/test_canonical_observation_binding.py
           tests/test_opportunity_structure_binding.py                -> COMPILE_OK

pytest tests/test_evidence_grounding.py tests/test_canonical_observation_binding.py
       tests/test_opportunity_structure_binding.py                    -> 53 passed

pytest tests/test_canonical_opportunity_publication.py
       tests/test_opportunity_structure.py tests/test_opportunity_structure_publication.py
       tests/test_stage_d_projection.py                               -> 137 passed, 1 skipped

git diff --check                                                       -> exit 0 (line-ending
                                                                            warnings only, no
                                                                            whitespace errors)

pytest (full repository suite)                                         -> 1222 passed, 2 skipped,
                                                                            19 subtests passed
```

---

## L. Refreshed deterministic artifacts

No Stage A rerun; no new Stage B/C/Canonical-Opportunity/Opportunity-
Structure run IDs were required. `canonical_opportunity.py` and
`opportunity_structure.py` were not modified, so their own output is
byte-identical given the same frozen `stage_c_normalized_facts.json`
(`PHASE3_RUN_ID = phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8`).
The fix lives entirely in the binding/publication layer, which is rebuilt
fresh, deterministically, on every commissioning run from that same frozen
input — there is nothing to "refresh" upstream of it. What changed is the
**result** of running the existing, unmodified
`scripts/commission_executive_opportunity_brief_bank_of_canada.py` against
the same frozen lineage, now producing new Canonical Opportunity Publication
and Opportunity Structure Publication run artifacts (Sections M/N).

`opportunity_structure_publication.py`'s `_semantic_value` gained float/
DECIMAL support (Section N) — this is downstream-only serialization logic,
not upstream ledger content; it does not change any structure record's
fields, only how an already-present float field (an EVALUATION_CRITERION
`weight`) is now representable at all.

---

## M. Canonical Opportunity Publication: **PASS**

Run embedded in `eob-boc-2026-026-20260912T170835Z-d69370` (boundary
"Canonical Opportunity Publication"): 134 objects published, evidence and
provenance bindings closed for every VERIFIED observation, no fabricated
granularity, no silent citation upgrades (every binding is either an exact
match or a Section-F-compliant Model-2 coarser match with its own real,
verbatim-excerpt proof).

## N. Opportunity Structure Publication: **PASS**

Same run, boundary "Opportunity Structure Publication": 696 objects
published. This boundary is what originally failed
(`eob-boc-2026-026-20260912T163804Z-af7d20`, `StructureBindingError`) and
then failed again on a second, unrelated pre-existing defect once the
provenance-granularity fix let it proceed
(`eob-boc-2026-026-20260912T170659Z-92ea9f`: `OpportunityStructurePublicationError:
unsupported structure semantic value type: float` — an EVALUATION_CRITERION
`weight` field, a raw Python `float`, had never before reached
`_semantic_value`'s serializer because every earlier run crashed upstream of
it). Fixed by adding `float` → `SemanticValueKind.DECIMAL` support to
`opportunity_structure_publication.py._semantic_value` (rendered via
`Decimal(str(value))`, matching `canonical_opportunity.py`'s own MONETARY
convention, for deterministic, cross-platform-stable text — never a raw
float repr). This fix is unrelated to provenance granularity; it is a
pre-existing gap shared by 6 other publication modules' own independent
`_semantic_value` copies (canonical_opportunity_publication.py,
opportunity_intelligence_publication.py, buyer_intelligence_publication.py,
canonical_buyer_publication.py, buyer_evidence_publication.py,
evidence_publication.py — none currently support `float` either), simply
never previously exercised. **Not fixed in those other 6 modules** — out of
scope for this remediation, flagged as a follow-up (see below).

## O. Executive Opportunity Brief recommission: **FAIL — blocked by a new, unrelated defect**

Both required gates (Sections M/N) now pass. The full chain was then
attempted end-to-end (`eob-boc-2026-026-20260912T170835Z-d69370`) and
progressed further than ever before — through Evidence, Canonical
Opportunity Publication, Opportunity Structure Publication, and Opportunity
Intelligence itself — before failing at "Opportunity Intelligence Support
Binding Derivation" (a step inside the commissioning script, downstream of
Opportunity Intelligence Publication's own admission gate):

```
4 evidence_used entities have no governed reference in any admitted
publication and 0 are ambiguous; refusing to invent or guess bindings
```

The four unresolved entities (`CONF-EVAL-1`..`CONF-EVAL-4`,
`entity_type: FUTURE_ENTITY`) are literal, human-readable `conflict_id`
strings taken directly from Stage C's own `stage_c_conflicts.json` — a
completely different identity scheme from the hashed `conf_...` conflict
identities Canonical Opportunity / Opportunity Structure themselves
publish. `analysis.evidence_used` (from `opportunity_intelligence.
analyze_opportunity`) cites these raw Stage C labels as `FUTURE_ENTITY`
support, but no admitted publication (Evidence, Canonical Opportunity,
Opportunity Structure) ever publishes a governed object under that literal
string identity, so the support-binding step correctly, fail-closedly
refuses to invent one.

**This is not a provenance-granularity or evidence-grounding defect.** It
is a distinct, pre-existing identity-scheme mismatch between Stage C's raw
conflict list and the constitutional publication layer's own conflict
identity — invisible until now only because every previous run crashed
earlier in the chain (first at Opportunity Structure Publication, then at
the unrelated float bug). It requires its own dedicated investigation and a
deliberate architectural decision (e.g. whether `FUTURE_ENTITY` support with
no `evidence_ids` should get the same PARTIAL/UNVERIFIED-style graceful
empty-reference fallback the binding adapters already have, or whether Stage
C's conflict identity needs to be reconciled with Opportunity Structure's
own hashed conflict identity) that is explicitly outside this remediation's
authorization. **EOB itself was never reached in this run.**

Per this remediation's explicit, standing instruction, work stops here.
**Executive Briefing Pack is not attempted.**

---

## P. Artifact index

**Code changed:**
- `evidence_grounding.py` — new shared grounding module (Sections F/G/H).
- `canonical_observation_binding.py` — rewritten to use the shared module.
- `opportunity_structure_binding.py` — rewritten to use the shared module.
- `opportunity_structure_publication.py` — added `float`/DECIMAL support to
  `_semantic_value` (Section N).

**Tests added:**
- `tests/test_evidence_grounding.py` — 21 new tests (Section J).

**Diagnostics (new, persisted, reproducible):**
- `scripts/diagnose_provenance_granularity_bank_of_canada.py`
- `evaluation/bank_of_canada_briefing_pack/provenance_granularity_remediation/classification.json`
- `evaluation/bank_of_canada_briefing_pack/provenance_granularity_remediation/appendix_g_forensic.json`
- `evaluation/bank_of_canada_briefing_pack/provenance_granularity_remediation/provenance_status_counts.json`
- `evaluation/bank_of_canada_briefing_pack/provenance_granularity_remediation/binding_outcome_before_after.json`

**Commissioning run artifacts:**
- `evaluation/bank_of_canada_briefing_pack/executive_opportunity_brief_commissioning/eob-boc-2026-026-20260912T170659Z-92ea9f/` — first post-fix attempt; Canonical Opportunity Publication PASS, Opportunity Structure Publication FAIL (float bug, since fixed).
- `evaluation/bank_of_canada_briefing_pack/executive_opportunity_brief_commissioning/eob-boc-2026-026-20260912T170835Z-d69370/` — final attempt this remediation; Canonical Opportunity Publication PASS, Opportunity Structure Publication PASS, Opportunity Intelligence PASS, Support Binding Derivation FAIL (new, unrelated defect, Section O). Contains `unresolved_support.json` with the 4 `CONF-EVAL-*` entities.

**Remaining warnings / follow-ups (not fixed in this remediation, flagged separately):**
1. Stage C conflict-identity vs. governed-publication-identity mismatch
   blocking Opportunity Intelligence Support Binding Derivation (Section O)
   — blocks EOB recommission entirely; needs its own audit.
2. `canonical_opportunity.py`'s `_source_segment` stops at the first
   `_locator_matches`-satisfying marker rather than searching exhaustively
   — a documented, safe-direction (under-, not over-verification)
   divergence from `evidence_grounding.py`'s exhaustive search (Section E/G).
3. `float`/DECIMAL support is still missing from 6 other publication
   modules' own independent `_semantic_value` copies (Section N) — latent
   until a float value reaches one of them.

---

## FINAL RESPONSE

- **PROVENANCE GRANULARITY REMEDIATION: PASS** (for its own defined scope —
  see below for the separately-discovered, out-of-scope EOB blocker)
- **Physical evidence model for DOCX:** MODEL 2 (HIERARCHICAL), SECTION-only,
  implemented in the binding/publication layer (Section F)
- **Total affected records (DOCX source_refs without an exact locator
  match):** 403 evaluated (145 non-exact: 103 Class B + 42 Class D; 257
  Class A exact; 0 Class C)
- **Class A/B/C/D counts:** A = 257, B = 103, C = 0, D = 42
- **Correct status semantics for coarse-locator cases:** a coarse SECTION
  marker may ground a finer, real, cited heading only via the excerpt's own
  unambiguous verbatim presence; upstream `provenance_status` (VERIFIED/
  PARTIAL/UNVERIFIED) is unchanged and unaffected by this remediation — see
  Section I for why that is correct, not an oversight
- **Appendix G outcome:** 4 real markers (3 bare TABLE, 1 whole-document
  SECTION:Header); of 156 distinct citations, 99 exact, 32 Class B (now
  correctly bind to the coarser real occurrence), 25 Class D (correctly
  remain ungrounded, fail closed)
- **Root causes:** (A) Evidence Adapter granularity — primary, addressed via
  binding-layer Model 2; (B) Stage A provenance-shape — not confirmed; (C)
  validator semantic defect (first-match search) — confirmed, safe
  direction, left as documented limitation; (D) validator
  over-permissiveness — confirmed, proven benign for this population,
  unchanged; (E) duplicate validator implementations — confirmed, primary
  defect source, fixed via centralization
- **Duplicated validators found:** YES —
  `canonical_observation_binding._match_refs` and
  `opportunity_structure_binding._match_refs` (structurally identical copies)
- **Shared grounding implementation created:** YES — `evidence_grounding.py`
- **Files changed:** `evidence_grounding.py` (new),
  `canonical_observation_binding.py`, `opportunity_structure_binding.py`,
  `opportunity_structure_publication.py`
- **Tests added:** 21 (`tests/test_evidence_grounding.py`)
- **Full suite result:** 1222 passed, 2 skipped, 0 failed (full repository);
  53 passed (binding-layer suites specifically); `git diff --check` clean
- **Before/after VERIFIED/PARTIAL/UNVERIFIED counts:** unchanged (by design
  — see Section I): Canonical Opportunity observations VERIFIED 95 / PARTIAL
  23 / UNVERIFIED 2; Opportunity Structure records VERIFIED 380 / PARTIAL
  309 / UNVERIFIED 3, both before and after
- **Refreshed run IDs:** no new Stage A/B/C run required;
  `eob-boc-2026-026-20260912T170659Z-92ea9f` (first post-fix attempt) and
  `eob-boc-2026-026-20260912T170835Z-d69370` (final attempt this
  remediation)
- **Canonical Opportunity Publication: PASS** (134 objects)
- **Opportunity Structure Publication: PASS** (696 objects)
- **EOB recommission: FAIL** — blocked before reaching EOB by a newly-exposed,
  separate, unrelated defect (Stage C conflict-identity vs. governed-
  publication-identity mismatch, Section O); not a provenance-granularity
  issue
- **EOB run ID if reached:** not reached
- **Remaining warnings:** 3, listed in Section P
- **Report path:** `BANK_OF_CANADA_PROVENANCE_GRANULARITY_REMEDIATION_REPORT.md`
- **Raw artifact paths:** listed in full in Section P

**Per the standing instruction: stopping here. Executive Briefing Pack is
not attempted.** The Stage C conflict-identity defect blocking EOB itself
(Section O) is a new, separate finding requiring its own dedicated audit and
explicit authorization before any further commissioning is attempted.
