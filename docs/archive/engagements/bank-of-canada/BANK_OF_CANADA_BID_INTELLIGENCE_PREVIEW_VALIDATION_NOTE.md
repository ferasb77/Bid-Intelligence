# Validation Note — Bid Intelligence Preview (Bank of Canada RFP 2026-026)

Internal note, not part of the client-facing PDF. Records which governed artifact supplied each
section of `BANK_OF_CANADA_RFP_2026_026_BID_INTELLIGENCE_PREVIEW.pdf`, so any figure in the
preview can be traced back to its source without re-deriving it.

**Primary source of truth used throughout:** the validated 16-document concurrency run
`stagea-concurrency2-full-boc-2026-026-20260913T054732Z-48564b` and its deterministic
Stage B → Stage C → Canonical Opportunity shadow (built fresh for this task via
`normalize_package_facts` / `reconcile_package_facts`, the same production code already used and
accepted in the Package 4 full-validation report — no new Stage A extraction, no new LLM calls).

| PDF Section | Governed Artifact(s) / External Source(s) Used | Notes |
|---|---|---|
| Cover | — | No factual content. |
| 1. Executive Opportunity Snapshot | Canonical Opportunity `resolved` block (`submission_deadline`, `procurement_model`, `contract_term`) from the concurrency-run shadow; raw Stage A `doc_metadata` for the clarification deadline | `title`/`client`/`file_number` show as `CONFLICTED` at the strict canonical layer; inspected the actual competing values (see below) and presented the plain, unambiguous form since the variance is wording-only, not substantive |
| 2. Buyer Intelligence (**new**) | Procurement package: none (this section deliberately does not draw on the RFP corpus, to keep buyer research and procurement facts separate). External: six bankofcanada.ca primary pages + the Bank of Canada Act, fetched live for this update — see the dedicated section below for full sourcing, fact/signal/interpretation breakdown, and URLs. | Everything in this section is either an external, cited public fact/signal, or explicitly labeled interpretation — never presented as the RFP's own content or as a stated evaluation criterion. |
| 3. What Is Being Procured? | Master RFP raw Stage A `requirements` (Category 1/2/3 scope descriptions, pp. 12–13) and `deliverables`; canonical `procurement_model` and `contract_term` | Deliberately did NOT reuse the earlier `01_EXECUTIVE_OPPORTUNITY_BRIEF.md` (built from the superseded Phase 1 Stage A run) — spot-checked several of its specific figures (21 cohorts, 420 leaders, 20 Bank documents, 15 stakeholder interviews) against this run's data and found no supporting text, so they were not carried forward |
| 4. Critical Dates & Bid Mechanics | Master RFP raw Stage A `dates`/`requirements` (p. 3, "1.2 RFP Timetable"); `Presentations — Service Category 1/3` typed observations | The two presentation dates come from the same conflict record used in Section 8 (Ambiguity 3), but are presented here as scheduling facts, not as an ambiguity |
| 5. Evaluation | Master RFP raw Stage A `evaluation_criteria` (per-category weight tables, not the Stage B-deduplicated view, which nulls weights where the same criterion label recurs with different values across sections) | The Stage-B-deduplicated `evaluation_criteria` list was deliberately NOT used for the weight tables, since its conservative null-on-conflict behavior would have shown "no weight" for nearly every criterion; the per-category raw tables are the correct, non-conflicting slice |
| 6. Response Requirements | Master RFP + Appendix A/B/C/D1/D2/D3/E/F/G raw Stage A `requirements`/`submission_rules` | D1/D2/D3 page limits taken directly from each appendix's own header requirement text |
| 7. Commercial & Contractual Considerations | Whole-corpus normalized `commercial_clauses` (Stage B output) from the concurrency-run shadow | Grouped by `clause_kind`; one representative topic shown per row, not every clause |
| 8. Important Ambiguities | Stage C `conflicts` from the concurrency-run shadow: 4 `EVALUATION_CONFLICT` records (internal scoring-value discrepancies) + 1 `DATE_CONFLICT` record (internal presentation-date discrepancy) | Same conflict objects already classified in the Package 4 full-validation report; re-read here for their `source_a`/`source_b` competing values, not re-detected |
| 9. Bid Team Attention Points | Synthesized from Sections 2–8 above | No new source facts; this section is judgment applied to the validated facts, written directly for this report (not a rerun LLM synthesis) |
| 10. Source Map / Reference Appendix | `source_refs` (page/section) attached to specific Stage A requirement records already cited above | Page numbers shown are the actual `page` field captured by Stage A's provenance validation, not estimated |

## Buyer Intelligence sourcing (Section 2) — full detail

**Starting point:** the already-commissioned `evaluation/bank_of_canada_briefing_pack/02_BUYER_BRIEF.md`
(evidence cutoff 2026-09-08), which cites six bankofcanada.ca pages plus the Bank of Canada Act.
That brief's own URLs were treated as a lead, not copied on trust — every one was re-fetched live
for this update, and content was re-verified/expanded against the live pages rather than assumed
current.

### Procurement-document sources (used elsewhere in the PDF, not in Section 2)

None. Section 2 is deliberately built only from external Bank of Canada sources, kept separate
from the RFP corpus, so the reader never has to wonder whether a "buyer fact" is secretly drawn
from — or attributed to — the solicitation itself.

### External buyer-intelligence sources (all fetched live from bankofcanada.ca / laws-lois.justice.gc.ca for this update)

| Source | URL |
|---|---|
| About the Bank of Canada | https://www.bankofcanada.ca/about/ |
| Bank of Canada Act | https://laws-lois.justice.gc.ca/PDF/B-2.pdf |
| 2025–27 Strategic Plan | https://www.bankofcanada.ca/about/governance-documents/the-bank-of-canadas-2025-27-strategic-plan/ |
| Equipping our workforce for the future (2025–27 Strategic Plan) | https://www.bankofcanada.ca/about/governance-documents/the-bank-of-canadas-2025-27-strategic-plan/equipping-our-workforce-for-the-future/ |
| Annual Report 2025 | https://www.bankofcanada.ca/2026/04/annual-report-2025/ |
| Procurement Policy Statement | https://www.bankofcanada.ca/about/governance-documents/procurement-policy-statement/ |
| 2026–28 Accessibility Plan | https://www.bankofcanada.ca/accessibility/2026-28-accessibility-plan/ |

**Checked and deliberately excluded:** third-party employee-headcount estimates (Revelio Labs,
LeadIQ, ZoomInfo, PitchBook) were reviewed and found to disagree substantially (figures ranging
from ~2,600 to ~3,650, depending on source and date). The Bank does not publish a current
headcount on its own site. Per the explicit instruction to prefer the Bank's own primary sources
over generic web summaries, no headcount figure is used anywhere in the preview — Section 2 notes
this gap explicitly rather than filling it with an unreliable number.

### Which statements are verified facts (Section 2, "Verified Buyer Facts")

Every row in that table is a direct, attributable statement from one of the primary sources
above — legal status/mandate, core functions, and governance structure from "About the Bank of
Canada"; the current strategic plan's name and five themes from the Strategic Plan page and
Annual Report 2025; the 15%-by-2028 cost-reduction commitment quoted directly from Annual Report
2025; the procurement-policy commitment from the Procurement Policy Statement; and the
accessibility/procurement and disability-hiring-rate figures from the 2026–28 Accessibility Plan.
None of these is inferred — each is a direct paraphrase or quotation of the source page.

### Which statements are signals (Section 2, "Relevant Buyer Signals")

The six rows are all direct paraphrases of stated commitments on the "Equipping our workforce for
the future" strategic-plan page (new leadership program, refreshed competencies, renewed talent
management, updated EDI strategy, culture vision, engagement-measurement renewal, updated
bilingualism policy, training for emerging capabilities) plus the Annual Report's cost-reduction
commitment, repeated here because of its direct relevance to bid strategy. These are still facts
about what the Bank has publicly stated — the "signal" framing exists only to separate
organization-wide priorities from the more narrowly organizational facts in the tier above, not
because they are less certain.

### Which statements are interpretation (Section 2, "Bid Relevance / Interpretation" and the "What This Means for the Bid Team" panel)

Every item in these two blocks is explicitly hedged ("may suggest," "is consistent with," "the
RFP itself does not confirm the link," "not a confirmed evaluation weighting") and is clearly
authored judgment connecting a verified fact/signal to bid strategy — never presented as the
Bank's stated intent, and never presented as an RFP evaluation criterion unless the RFP itself
says so. The panel's final item is explicit about this: "None of the above is stated or implied
to be an evaluation criterion by the RFP itself."

## What was checked and excluded

- The pre-existing `01_EXECUTIVE_OPPORTUNITY_BRIEF.md` and `02_BUYER_BRIEF.md` (built earlier from
  the superseded Phase 1 Stage A run) state **"Procurement model: Single Contract."** The current,
  validated canonical resolution states **"Multi-vendor Call-off"** (`resolution_basis:
  EXPLICIT_MECHANICS`). This is a direct contradiction between the old and new artifacts. The
  preview uses the current, validated value and does not reference the older documents' framing.
- Several specific figures in the old Executive Opportunity Brief (21 learning cohorts, 420
  leaders, 20 Bank documents, 15 stakeholder interviews, a 90-minute executive presentation) were
  checked against the current validated Stage A output for the master RFP and found no supporting
  text. They were not carried into the preview.
- `title`, `client` (buyer name), and `file_number` (solicitation number) are flagged
  `CONFLICTED` at the strict canonical layer. Inspected the actual competing values:
  - Title: "RFP 2026-026 - Talent, Learning and Organizational Development Services" vs. "Talent,
    Learning and Organization Development" (missing "-al" and "Services") vs. "Talent, Learning
    and Organizational Development Services" — a typo/truncation variant, not a different title.
  - Client: "bank of canada" vs. "bank" vs. "the bank" — standard legal drafting shorthand
    ("hereinafter the Bank"), not a different buyer.
  - File number: "2026-026" vs. "RFP 2026-026" — a prefix variant of the same number.
  These are presented plainly in the preview (using the fullest, standard form) rather than as
  ambiguities, since none of them is a genuine, material discrepancy a bid team would need to
  resolve. The three ambiguities that ARE presented (Section 8) were selected because they involve
  genuinely different values (different point allocations, different dates), not wording variants.

## Remaining ambiguity that materially affects the report

The evaluation-weighting discrepancy (Ambiguity 1) is the single most consequential open item:
it directly affects how a bid team should allocate proposal-writing effort across sections, and
it was not possible to determine from the source material alone which of the several stated point
allocations for "Corporate Profile," "Key Personnel," and "Methodology" is authoritative. This is
presented to the reader rather than resolved, per the explicit instruction never to silently
resolve a governed ambiguity.
