# Fast Analysis — Minimum Viable Intelligence Audit

**Scope: research and design only. No code was modified to produce this audit.** Target product
output: the 13-page `BANK_OF_CANADA_RFP_2026_026_BID_INTELLIGENCE_PREVIEW.pdf`. Every fact traced
below is checked against the currently accepted, validated corpus run
(`stagea-concurrency2-full-boc-2026-026-20260913T054732Z-48564b`) and its Stage B → Stage C →
Canonical Opportunity shadow — the same artifacts that generated the PDF — plus the corpus
manifest (`corrected_corpus_manifest.json`) for document-level metadata (size, page count, role).

## A. Method

For every substantive statement/table in the PDF's content module
(`scripts/boc_bid_intelligence_preview_content.py`), I identified: what fact it asserts, which
Stage A family/field actually supplied it (verified against the real, persisted JSON — not
assumed from the schema), which physical document that field came from, how precise the fact
needs to be to keep the PDF correct, and whether the atomic, occurrence-preserving extraction the
current pipeline performs is actually load-bearing for that specific statement or a narrower
extraction would do.

## B. Section-by-section trace matrix

| Report section | Required fact(s) | Source document(s) | Current pipeline source | Required precision | Deep atomic extraction actually necessary? |
|---|---|---|---|---|---|
| Cover | — | — | — | — | No content |
| **1. Snapshot** — buyer/title/solicitation number | Name strings | Master RFP (+ corroborated everywhere) | `typed_observations` IDENTITY family; Canonical resolution | Low — any one high-confidence mention suffices | **No.** A single targeted read of the master RFP's own header is sufficient; the corpus-wide IDENTITY corroboration (75 occurrences) is what *causes* the harmless title/client "CONFLICTED" status seen in Canonical Opportunity — valuable for governance, not for this fact |
| **1. Snapshot** — submission deadline (date+time) | Exact date/time | Master RFP p. 3, "1.2 RFP Timetable" | `doc_metadata.submission_deadline` + `typed_observations` MILESTONE; Canonical resolution (`EXACT_AGREEMENT`) | **High** — exact value, must be right | **Narrow, not deep.** One well-scoped extraction over the master RFP's timetable section; no other document needs to be touched for this fact |
| **1. Snapshot** — clarification deadline | Exact date | Master RFP + abstract.pdf (2 corroborating mentions) | `doc_metadata.clarification_deadline` | Medium | No — one source is enough; the second is a nice-to-have cross-check |
| **1. Snapshot** — procurement model | "Multi-vendor call-off" | Master RFP | `typed_observations` PROCUREMENT_MECHANIC + Canonical resolution (`EXPLICIT_MECHANICS`) | **High** — this is the single fact most likely to be silently mis-stated (see Package 2/4 history: this value changed between an earlier, less-remediated pipeline run and the current one) | **Yes, but narrowly.** Needs the governed resolution logic (multiple PROCUREMENT_MECHANIC mentions reconciled into one value), not the full 8-family schema |
| **1. Snapshot** — contract term | 3yr + 2×1yr options; nested 12-week HR Advisory example | Master RFP | `typed_observations` CONTRACT_TERM (5 occurrences) + Canonical resolution (`STRUCTURED_COMPONENTS`) | High | Yes, narrowly — same reasoning as procurement model |
| **1. Snapshot** — category cards (name / form / page limit / presentation stage) | 3× (name, page limit, presentation Y/N) | Master RFP pp. 12–13; D1/D2/D3 headers | `requirements` (category scope) + `submission_rules` (page limits) | High for page limits | **No for page limits** (regex/keyword-extractable from each form's own header — see §E); **narrow LLM pass** for category names/presentation-stage facts |
| **2. Buyer Intelligence** (entire section) | Organizational facts/signals about the Bank | *External* — bankofcanada.ca, Bank of Canada Act | **None** — zero Stage A/B/C dependency by design | N/A | **N/A — not a Stage A concern at all.** This section is a one-time, cacheable external-research artifact, not a per-RFP extraction |
| **3. What Is Being Procured?** — category descriptions | 3× multi-item scope lists | Master RFP pp. 12–13, §4.1 Category 1/2/3 | `requirements` (category scope items) | Medium-high (need the real enumerated sub-items) | Narrow — one scoped pass over §4.1 of the master RFP; does not need the universal 8-family schema or any other document |
| **3. What Is Being Procured?** — structural/call-off narrative | Submission-structure and call-off mechanics | Master RFP | `requirements` + `typed_observations` CONTRACT_TERM | Medium | Narrow |
| **4. Critical Dates** — 4 dates | Exact dates + labels | Master RFP only | `typed_observations` MILESTONE / `dates` | High | Narrow — one "list all named deadlines/dates" pass over the master RFP |
| **4. Bid Mechanics** — 4 bullets | Submission-channel rules | Master RFP §1 | `requirements` | Medium | Narrow |
| **5. Evaluation** — stage structure (Stage 1–5) | Structure/labels | Master RFP | `requirements` / `evaluation_criteria` | Medium | Narrow |
| **5. Evaluation** — qualification-gate examples (×3) | Exact thresholds ("5 years", "10 engagements") | Appendix C1/C2/C3 (or master RFP) | `evaluation_criteria` (`Qualification / Gate` role, `threshold` field) | High | Narrow — scoped to gate-role criteria only, not the full evaluation hierarchy |
| **5. Evaluation** — rated-criteria weight tables (×3, ~18 rows) | Exact point values per category | Master RFP §4.1 scoring tables (D1/D2/D3 sections) | `evaluation_criteria` **raw, per-occurrence** (explicitly NOT the Stage B-deduplicated view, which nulls weight when a label repeats with different values) | **Very high** — exact numbers, and every distinct occurrence must be preserved | **Yes — this is the one place genuine atomic, non-deduplicated, occurrence-preserving extraction is load-bearing.** Collapsing to "one weight per criterion name" would silently destroy Ambiguity 1, the single highest-value finding in the whole PDF |
| **6. Response Requirements** — 9-row checklist | Which appendix, brief description, page limits | All 16 documents *nominally*, but empirically: master RFP's own "each proposal must include..." list already states 8 of the 9 rows; only page limits are genuinely appendix-specific | `submission_rules` / `requirements` | High for page limits, low for the rest | **No.** 12 of the 16 documents contribute almost nothing to this checklist beyond restating what the master RFP already says about them — see §D |
| **6. Response Requirements** — "Also Required" bullets | Bilingual/security/accessibility/external-link rules | Master RFP mandatory-criteria section | `requirements` | Medium | Narrow |
| **7. Commercial & Contractual** — 10-row table | Representative clause per topic | **Overwhelmingly Appendix G** (58 of ~88 corpus-wide `commercial_clauses`) | `commercial_clauses` | Medium-high (need real clause language, not paraphrase) | **Yes, for Appendix G specifically** — this is the other place deep extraction is genuinely earning its cost |
| **8. Ambiguities** — evaluation-weight conflict | Competing point values for the same criterion label | Master RFP (internal, multiple sections) | Stage C `EVALUATION_CONFLICT`, built from raw `evaluation_criteria` occurrences | Very high | **Yes** — same atomic-preservation requirement as the weight tables above; this *is* that requirement's payoff |
| **8. Ambiguities** — price-double-count question | Structural observation about two evaluation stages | Master RFP | Authored directly from the raw weight-table data (§5) | Medium | No — this is an analytical observation over already-narrow data, not a separate extraction |
| **8. Ambiguities** — presentation-date conflict | Two dates, two category labels | Master RFP (internal) | Stage C `DATE_CONFLICT`, built from raw `typed_observations`/`dates` occurrences | High | **Yes**, same reasoning — occurrence-level date extraction, not canonicalized-to-one-value extraction |
| **9. Attention Points** | — | — | Pure synthesis of Sections 1–8 | — | No new extraction |
| **10. Source Map** | Page/section pointers for ~7 headline facts | Whichever document each fact came from | `source_refs` on the specific records above; Stage B `validate_source_refs` | Medium (must exist and be correct, not exhaustive) | **No** — provenance validation is a cheap, deterministic, local check against already-parsed document metadata; it should be *kept*, not deepened |

## C. Stage A family/field classification

Classified against what this specific report actually draws on, verified empirically against the
persisted run (not assumed from the schema definition).

| Family / field | Corpus-wide records (this run) | Classification | Basis |
|---|---|---|---|
| `doc_metadata` (title, client, file_number, submission_deadline, clarification_deadline) | 16 (one per doc) | **REQUIRED FOR FAST ANALYSIS** | Directly used for Section 1's headline facts |
| `doc_metadata.notes` | 16 | USEFUL BUT DEFERABLE | Never quoted in the PDF; useful color for a human reviewer, not load-bearing |
| `evaluation_criteria` (raw, per-occurrence) | 86 | **REQUIRED FOR FAST ANALYSIS** | Section 5's weight tables and 2 of 3 Section 8 ambiguities depend directly on this family's occurrence-level fidelity |
| `evaluation_criteria.evaluation_role`, `.threshold` | subset of above | **REQUIRED FOR FAST ANALYSIS** | Qualification-gate examples (Section 5) |
| `evaluation_criteria.weight_basis` (Overall/Within Parent/Unknown) | subset | USEFUL BUT DEFERABLE | Informs the Section 5 note about Price appearing inside vs. outside category tables, but the PDF's own text was authored by reasoning over raw weight values, not by mechanically branching on this field |
| `requirements` (category-scope, submission-mechanics subset) | ~120 of 427 actually referenced | **REQUIRED FOR FAST ANALYSIS**, narrowly | Only the master RFP's own category-scope and mandatory-submission requirements are used — see §D for why the other 15 documents' `requirements` records are largely redundant |
| `requirements.requirement_type` (controlled enum) | 427 | USEFUL BUT DEFERABLE | Never surfaced as a distinguishing structure in the PDF; the report's own prose groups things narratively, not by this enum |
| `requirements.weight` | 427 (mostly null) | CURRENTLY UNUSED | Weight lives in `evaluation_criteria`, not `requirements`, for every record that matters to this report |
| `submission_rules` (item, mandatory, details) | 64 | **REQUIRED FOR FAST ANALYSIS**, narrowly | Powers the Section 6 checklist and D1/D2/D3 page limits, but only a handful of the 64 records are genuinely distinct — most restate the master RFP's own appendix list |
| `submission_rules.artifact_type` / `.file_format` / `.submission_channel` (controlled enums) | 64 | USEFUL BUT DEFERABLE | Never surfaced; the PDF's checklist column text was authored directly, not templated from these enums |
| `dates` (milestone, date, source_doc) | 23 | **CURRENTLY UNUSED** (redundant) | Every date actually used in the PDF traces to `typed_observations` MILESTONE (22 records, near-identical coverage), not to this separate, older family |
| `deliverables` | 20 | **CURRENTLY UNUSED** | Verified: no PDF statement traces to this family. Populated (Appendix E: 11, Appendix G: 5, master RFP: 4) but never drawn on for this report — plausibly useful for a future "what you'll deliver" section, not this one |
| `commercial_clauses` | ~88 | **REQUIRED FOR FAST ANALYSIS** | Powers all of Section 7; concentrated almost entirely in one document (Appendix G, 58 of 88) |
| `contract_risks` | **0** | **CURRENTLY UNUSED** | Confirmed empirically: this family has never once been populated across any run of this corpus. The RFP's own "Contract Hygiene Rules" explicitly forbid risk-judgment language, so it is structurally guaranteed to stay empty for this buyer's documents |
| `typed_observations` family: IDENTITY (75), MILESTONE (22), CONTRACT_TERM (5), PROCUREMENT_MECHANIC (29) | 131 | **REQUIRED FOR FAST ANALYSIS** | These four sub-families directly feed Canonical Opportunity's `procurement_model`, `contract_term`, and deadline resolution — arguably the single most load-bearing family in the schema for this report |
| `typed_observations` family: MONETARY (3) | 3 | USEFUL BUT DEFERABLE | Barely populated; the one dollar figure used in the PDF (Appendix G's $3M CGL insurance minimum) is sourced from `commercial_clauses`, not confirmed to trace through this family |
| `typed_observations` family: DOCUMENT_ROLE (17) | 17 | DEEP VERIFY ONLY | Not surfaced anywhere in the PDF directly, but plausibly supports amendment-precedence logic (deciding the Amendment 1 D2 supersedes the original D2) invisibly — worth keeping for Deep Verify's correctness, not needed for Fast Analysis's own output |
| `typed_observations.supersession` block | rare | DEEP VERIFY ONLY | Same reasoning — governs amendment precedence, a correctness concern beyond what Fast Analysis promises to resolve |

## D. Document classification by extraction type actually required

Verified against real per-document `role`, byte size, and populated-family data from the accepted
run — not assumed from the universal schema.

| # | Document | Bytes | Manifest role | Fast Analysis treatment | Why |
|---|---|---|---|---|---|
| 1 | RFP main document | 376,615 | `MASTER_RFP` | **DEEP, schema-narrowed** (identity + milestones + evaluation_criteria + scoped requirements; drop commercial_clauses/deliverables) | Sole source of buyer identity, deadlines, evaluation structure/weights, and all 3 ambiguities |
| 2 | abstract.pdf | 119,394 | `NOTICE_AND_DOCUMENT_INVENTORY` | **SKIP** (or single light corroboration pass) | Its own manifest role says it is an index/notice; empirically restates master RFP content |
| 3 | Amendment 1 — Appendix D2 | 50,745 | `AMENDMENT` | **LIGHT, narrow** (evaluation_criteria only) | This is the *authoritative current* D2 |
| 4 | OriginalRevision Appendix D2 | 55,852 | `PROCUREMENT_ATTACHMENT` | **SKIP** | Superseded by #3; the manifest itself already flags one as an amendment of the other |
| 5 | Annexe F (ESG Questionnaire) | 28,985 | `PROCUREMENT_ATTACHMENT` | **SKIP** (filename-derivable) | Only fact used anywhere: "a mandatory ESG questionnaire exists" — needs no LLM call at all |
| 6 | Appendix A (Submission Form) | 48,269 | `PROCUREMENT_ATTACHMENT` | **SKIP** | Its content is restated in the master RFP's own mandatory-requirements list, verified directly |
| 7–9 | Appendix B1/B2/B3 (Mandatory Criteria) | ~14,000 each | `PROCUREMENT_ATTACHMENT` | **LIGHT, narrow, batchable** (evaluation_criteria/gate only) | Genuinely new gate thresholds, not restated elsewhere; small enough that all three fit in one combined call well under the chunk boundary |
| 10–12 | Appendix C1/C2/C3 (Minimum Qualification) | ~14,000 each | `PROCUREMENT_ATTACHMENT` | **LIGHT, narrow, batchable** | Same reasoning as B1–3; batchable with B1–3 into the same combined call |
| 13 | Appendix D1 | 58,679 | `PROCUREMENT_ATTACHMENT` | **LIGHT-MEDIUM, narrow** (evaluation_criteria weight table only; page limit via regex, not LLM) | Its fine-grained rated-criteria response guidance (the 30–77-record content investigated at length in Package 2) is never surfaced anywhere in this PDF — only its point weights and page limit are |
| 14 | Appendix D3 | 52,110 | `PROCUREMENT_ATTACHMENT` | **LIGHT-MEDIUM, narrow** | Same as D1 |
| 15 | Appendix E (Pricing Form) | 44,836 | `PROCUREMENT_ATTACHMENT` | **LIGHT, narrow** (typed_observations CONTRACT_TERM/PROCUREMENT_MECHANIC + a handful of requirements) | Only the pricing-structure narrative and the illustrative 12-week duration are used; its 41 detailed requirement records are not |
| 16 | Appendix G (Form of Agreement) | 67,727 | `PROCUREMENT_ATTACHMENT` | **MEDIUM-DEEP, schema-narrowed** (commercial_clauses primary; drop requirements — 163 records, almost none of which reach the PDF) | The sole substantive source for all of Section 7 |

**Page-limit facts specifically (D1/D2/D3: 15/12/10 pages)** do not require an LLM call at all in
Fast Analysis. Verified directly against all three forms' actual text: D1 reads "Responses must
not exceed 15 pages (excluding resumes or professional profiles, and work or product...)"; D3
reads "...not exceed ten (10) pages (excluding resumes or professional profiles, and work or
pr...)"; the current (Amendment 1) D2 reads "...not exceed twelve (12) pages (excluding resumes
or professional profiles, and work or...)". The shared prefix and clause structure are identical
across all three (only the number — sometimes digit-only, sometimes spelled-word-plus-digit —
varies), which a single deterministic regex over the already-parsed document text can extract
reliably, with no LLM call.

## E. Which processing layers are genuinely required to reproduce this PDF

| Layer | Required for this PDF? | Notes |
|---|---|---|
| Stage A extraction (narrowed) | **Yes** | The only irreducible LLM cost; everything downstream is deterministic |
| Stage B normalize/dedup | **Yes, but cheap** | Pure Python, no LLM; must be kept for cross-document requirement/rule deduplication and `source_refs` provenance validation (Section 10 depends on this) |
| Stage C conflict detection | **Yes, but cheap** | Pure Python; this is what *produces* Section 8's three ambiguities from the raw occurrence data — cannot be skipped without losing the ambiguity-detection promise |
| Canonical Opportunity resolution | **Yes, but cheap** | Pure Python (`governed_reference_resolution.py`); resolves `procurement_model`/`contract_term`/deadlines into the single values Section 1 needs |
| Opportunity Structure Publication | **No** | Never read for this PDF (confirmed in the validation note for the prior task) |
| Opportunity Intelligence Publication | **No** | Same |
| Executive Opportunity Understanding | **No** | Same |
| Executive Opportunity Brief (Stage D synthesis, LLM-based) | **No** | The existing EOB was checked against this PDF's facts and found to contain at least one materially stale figure (`procurement_model: Single Contract`, contradicted by the current canonical resolution) — not just unnecessary but actively risky to reuse uncritically |
| Buyer Brief (existing) | **No** | Superseded for this task by fresh external research (previous task); not a Stage A/B/C dependency either way |
| Executive Briefing Pack composition | **No** | Never touched |

**Bottom line:** of the roughly 9–10 stages in the full commissioned pipeline, only 4 are load-bearing
for this specific PDF (Stage A extraction, Stage B, Stage C, Canonical resolution) — and of those
four, only Stage A carries meaningful cost. The other 5–6 stages can be fully bypassed in a Fast
Analysis path without losing any content this PDF actually presents.

## F. Minimal Fast Analysis schema

A narrowed Stage A response schema, used only for Fast Analysis (Deep Verify keeps the existing
full 8-family schema unchanged):

```
{
  "doc_metadata": { "title": null, "client": null, "file_number": null,
                     "submission_deadline": null, "clarification_deadline": null },
  "typed_observations": [
    // family restricted to IDENTITY | MILESTONE | CONTRACT_TERM | PROCUREMENT_MECHANIC only
    // MONETARY and DOCUMENT_ROLE omitted from the Fast Analysis prompt entirely
  ],
  "evaluation_criteria": [
    // UNCHANGED shape and UNCHANGED atomic/occurrence-preserving behavior —
    // this is the one family Fast Analysis must not simplify, per §B/§C
  ],
  "requirements": [
    // requested ONLY for the master RFP (category-scope + mandatory-submission
    // sections) — omitted entirely from the Fast Analysis prompt for every
    // other document
  ],
  "submission_rules": [
    // requested ONLY where a document's own page-limit sentence cannot be
    // reliably regex-matched (fallback path); Appendix A/F omitted entirely
  ],
  "commercial_clauses": [
    // requested ONLY for Appendix G
  ]
  // dates, deliverables, contract_risks: OMITTED from the Fast Analysis prompt
  // entirely (see §C for why each is redundant or empty)
}
```

Two structural rules alongside the schema itself:
1. **Page limits are extracted deterministically (regex over parsed text), never via LLM**, for
   every D1/D2/D3-shaped form.
2. **Small, single-purpose documents are batched into one call** where their combined parsed text
   still fits inside the existing 12,000-character chunk boundary — concretely, B1+B2+B3+C1+C2+C3
   (each ~750–1,200 parsed characters) fit comfortably together in one call, replacing 6 separate
   calls with 1.

## G. Estimated reductions (Fast Analysis vs. the accepted full-corpus baseline)

Baseline: `stagea-concurrency2-full-boc-2026-026-20260913T054732Z-48564b` — 54 calls, 279,835
input tokens, 306,629 output tokens, 30 recovery calls, ~899 extracted records, 1,227.5s wall time
at the already-validated concurrency=2.

| Metric | Baseline | Fast Analysis estimate | Est. reduction |
|---|---|---|---|
| LLM calls | 54 | **~16–19** (4 docs skipped entirely; 6 tiny docs batched into 1; D1/D2/D3/E narrowed to 1 call each; Appendix G narrowed to ~5–6; master RFP narrowed to ~6–8) | **~65–70%** |
| Output tokens | 306,629 | **~100,000–140,000** (narrower schema cuts per-call output on every remaining document; skipped documents contribute zero) | **~55–65%** |
| Input tokens | 279,835 | **~55,000–75,000** (fewer calls × a shorter, narrower-schema prompt — both levers compound, since ~76–81% of input is the fixed prompt resent per call) | **~75–80%** |
| Recovery calls | 30 | **~4–8** (100% of observed recoveries were caused by hitting the 8,000-token output ceiling; narrower per-call output makes hitting that ceiling far less likely) | **~75–85%** |
| Extracted records | ~899 | **~430–470** (two families dropped entirely — `dates`, `deliverables`; two more narrowed hard — `requirements`, `submission_rules`; the two genuinely load-bearing families — `evaluation_criteria`, `commercial_clauses` — kept close to full) | **~45–55%** |
| Pipeline stages exercised | ~9–10 (full commissioned chain, when available) | **4** (Stage A–narrowed, Stage B, Stage C, Canonical resolution) | **~55–70%** (Stage A always ran anyway; the reduction is in what runs *after* it) |
| Elapsed time | 1,227.5s (~20.5 min) at concurrency=2 | **~2.5–4 min at concurrency=2**; plausibly **≤2 min at concurrency=4–6** (untested at that level, but document independence was already proven concurrency-agnostic in the Package 4 validation) | **~80–90%**, with the final push to strictly ≤2 min requiring a new, cheap concurrency-level validation, not a new architecture |

These are estimates, not measurements — validating them requires an actual pilot run, which this
audit deliberately does not perform.

## H. Proposed architecture

```
                         ┌─────────────────────────────┐
                         │   16-document corpus, RFP    │
                         └──────────────┬──────────────┘
                                        │
                     ┌──────────────────┴──────────────────┐
                     │                                      │
                     ▼                                      ▼
        ┌────────────────────────┐            ┌─────────────────────────────┐
        │      FAST ANALYSIS      │            │        DEEP VERIFY           │
        │  target: ≤2 min, sync   │            │  existing pipeline, async    │
        └────────────────────────┘            └─────────────────────────────┘
        1. Skip abstract.pdf, Appendix A,        1. Full 16-document corpus,
           Annexe F, superseded D2 (§D)             unmodified universal
        2. Deterministic regex pass for              8-family schema (unchanged)
           D1/D2/D3 page limits — no LLM           2. Full recovery cascade,
        3. Batch B1+B2+B3+C1+C2+C3 into 1             full atomic extraction,
           call (narrow: evaluation_criteria          zero schema narrowing
           gate examples only)                     3. Full Stage A → B → C →
        4. 1 narrow call each: Amendment-D2,           Canonical → Structure →
           D1, D3, E (schema per §F)                   Intelligence → EOU →
        5. Appendix G: narrowed to                     EOB → Buyer Brief →
           commercial_clauses-primary                  Briefing Pack chain,
           schema, concurrency unchanged                exactly as already
        6. Master RFP: narrowed schema                  commissioned/accepted
           (drop commercial_clauses/                4. Bounded document-level
           deliverables), same chunking                concurrency=2 (already
        7. Concurrency=2 (validated) as a               validated, Package 4)
           floor; a fresh, cheap validation          5. Produces the existing,
           of concurrency=4–6 is the                    fully-commissioned
           single highest-leverage next                 artifact lineage —
           step to comfortably clear ≤2 min             unchanged, not replaced
        8. Stage B → Stage C → Canonical
           resolution (unchanged, cheap,
           deterministic — not narrowed)
        9. Render the same 13-page PDF
           template directly from the
           narrowed Stage A/B/C output
                     │                                      │
                     ▼                                      ▼
        ┌────────────────────────┐            ┌─────────────────────────────┐
        │  Bid Intelligence       │            │  Full governed lineage:      │
        │  Preview PDF (this      │            │  Canonical Opportunity,       │
        │  document), produced    │            │  Opportunity Structure/       │
        │  in ≤2 min              │            │  Intelligence, EOU, EOB,      │
        │                         │            │  Buyer Brief, Briefing Pack   │
        └────────────────────────┘            └─────────────────────────────┘
```

**Design principle:** Fast Analysis is not a lower-rigor replacement for the existing pipeline —
it is a *different, narrower question asked of the same documents*, using a schema sized to
exactly what this one report needs (§B), while preserving the one property that must never be
narrowed away: atomic, occurrence-level extraction of `evaluation_criteria` and date/milestone
observations, because that is the sole mechanism that produced this PDF's highest-value finding
(the evaluation-weighting ambiguity). Deep Verify remains available, unmodified, as an
asynchronous, optional, higher-cost pass over the same corpus — a user who wants the full governed
lineage (Canonical Opportunity, Opportunity Structure/Intelligence, EOU, EOB, Buyer Brief,
Briefing Pack) still gets it, on the existing terms, without Fast Analysis ever standing in the
way of that path.

**Not implemented.** This audit produces no code changes. The next step, if authorized, would be
a narrow, single-package pilot (one narrowed-schema live run on the batched-and-skip document set
above, measured with the same rigor as Packages 2–4) before any production integration.
