# Risk / Deliverable Hygiene Phase 1 Evidence

## Baseline and branch

- Base: `5410b06586315ff3edb3328a69c547294e29911b`
- Branch: `fix/risk-deliverable-hygiene`
- Baseline regression: 580 passed, 1 skipped, 19 subtests passed, 0 failures
- Internal contract: `contract-hygiene/1`

## Architecture and doctrine

The implementation separates physical source occurrences, exact logical records, and optional AI-assisted interpretations. Source occurrences carry the evidence. Logical records group only identical structured facts and retain every physical occurrence. Interpretations link to verified clause IDs and never become source facts.

Fresh Stage A no longer requests `contract_risks`, `High|Medium|Low`, or inferred consequences. It extracts supplier-produced contract deliverables and objective contract clauses. Exact source wording remains in `source_refs[].excerpt`; normalized fields contain concise factual statements.

## Files changed

- `contract_hygiene.py`
- `extractor.py`
- `stage_d_projection.py`
- `pages/stage_understand.py`
- `tests/test_contract_hygiene.py`
- `tests/test_stage_d_projection.py`

## Fresh Stage A contracts

Deliverables contain title, description, obligation state, decimal-string quantity, unit, controlled frequency, scope, due milestone, acceptance criteria, responsible actor, conditions, and source refs. Only supplier-produced contract outputs enter the verified authoritative summary.

Clauses contain controlled `clause_kind`, topic, normalized `source_fact`, conditions, scope, linked canonical observation IDs, and source refs. The Phase 1 taxonomy covers liability, insurance, IP, AI, privacy, cybersecurity, confidentiality, subcontracting, personnel, clearances, termination, suspension, payment, pricing, bonds, penalties, warranty, acceptance, audit, change control, assignment, disputes, exclusivity, continuity, regulatory compliance, and `OTHER`.

## Provenance, identity, and deduplication

Fresh records require source refs that pass the existing package validator, include an exact excerpt, and are marked verified. Unverified fresh records remain diagnostic occurrences and cannot enter authoritative executive factual sections.

IDs use SHA-256 content identities with `dlo_`, `dlv_`, `clo_`, `clause_`, and `ra_` prefixes. Physical identity includes source coordinates. Logical identity includes all relevant structured factual dimensions. Processing order is excluded.

Overlapping-chunk copies of the same physical occurrence collapse. The same exact logical fact in different documents becomes one logical record with both occurrences. Differences in lot, phase, component, location, quantity, frequency, condition, status, actor, due milestone, or material acceptance criteria remain separate. No fuzzy semantic deduplication is used.

## Stage C

Fresh structured deliverables bypass the legacy prose regex path. Stage C compares only verified, commensurable structured records. Different explicit quantities in the same scope and mandatory-versus-explicitly-optional disagreement produce a deterministic conflict. Different lot, location, phase, condition, or frequency does not. Legacy records retain the existing compatibility path, and frozen Bank expectations were not retuned.

Clause facts link to canonical observations where applicable. Canonical opportunity remains authoritative for money, dates, term, procurement mechanics, and pricing mechanics. Phase 1 does not add a generic legal contradiction engine.

## Stage D rules and authoritative shapes

Verified logical clauses receive prompt-local `x…` aliases mapped to full stable clause IDs in the sidecar. The occurrence ledger is not duplicated in the prompt.

The model may emit only `REVIEW` or `UNKNOWN`, with `AI_ASSISTED`, a null user decision, exactly one visible clause alias, and the matching controlled clause kind. `MATERIAL`, severity, unknown links, mismatched kinds, multiple-clause ambiguity, and invented user decisions are rejected. Source facts are absent from the model output contract, so Stage D cannot mutate them.

Authoritative reapplication preserves deliverable and clause IDs, structured factual fields, source refs, evidence state, and retained occurrences. `brief.contract_risks` is assembled from verified clauses plus any validated assessment. Fresh objects contain no severity.

## UI and persistence

Deliverable, commercial-clause, and risk cards show evidence state and compact existing locator details. Risk cards separate source facts from system interpretation. There is no severity fallback. The empty state says that no source-grounded clauses were identified and explicitly does not claim none exist. Legacy records are labeled `UNVERIFIED` / `LEGACY EXTRACTION`.

The existing `bid_briefs` text columns round-trip nested lists and objects through `format_bid_brief_payload()` and `_ensure_list()` without a schema change. Extracted deliverables are not mapped into the proposal-production `deliverables` table.

## Stage A measurement and live smoke

- Previous instruction size: 12,463 characters
- Current instruction size: 14,688 characters
- Difference: +2,225 characters
- Model: unchanged `claude-haiku-4-5-20251001`
- Live source: one small synthetic page with submission-artifact, contract-output, technical-capability, conditional-training, IP, liability, subcontracting, AI, insurance, and no-guaranteed-volume statements
- Result: monthly report and conditional call-off training retained; tender implementation plan and dashboard capability excluded; five cited clauses retained; no fresh `contract_risks`; no severity; valid JSON returned without a truncation failure
- The direct smoke harness did not persist the provider response byte count or stop metadata. This is a measurement limitation; the returned object was complete and parseable, and no retry/recovery exception occurred.

## Stage D capacity measurements

The guard remains 580,000 characters.

| Case | Before | After | Difference | Headroom |
|---|---:|---:|---:|---:|
| Bank retained replay | 120,494 | 122,366 | +1,872 | 457,634 |
| British Council Attempt 2 retained replay | 49,163 | 51,035 | +1,872 | 528,965 |
| Synthetic 20 deliverables + 20 clauses | 15,800 | 24,578 | +8,778 | 555,422 |
| Synthetic 250 deliverables + 250 clauses | 79,756 | 165,365 | +85,609 | 414,635 |

The high-cardinality case remains 414,635 characters below the unchanged guard. The sidecar retains occurrences; the prompt contains compact logical records and evidence aliases.

## Live Stage D smoke

A D-only structured synthetic package contained one verified monthly deliverable, three verified clauses, and one supporting requirement. The final successful dispatch produced linked `REVIEW` assessments for AI, IP, and unlimited liability. Clause aliases resolved to full IDs; source facts and source refs were preserved; no `MATERIAL`, severity, or user decision appeared; authoritative assembly passed. No Stage A/B/C calls occurred in this D-only run.

Earlier development smoke failures exposed and led to correction of a missing `clause_id` alias mapping and then verified the mismatch validator. They are not presented as successful contract evidence.

## Retained replays

- Bank retained normalized data replayed without a live extraction: 43 deliverables, 11 commercial clauses, and 30 risks remain visible through legacy/unverified compatibility.
- British Council Attempt 2 replayed without a live extraction: 9 deliverables, 13 commercial clauses, and 17 risks remain visible through legacy/unverified compatibility.
- No retained artifact was rewritten or enriched from benchmark knowledge.

## Validation

- Focused canonical/hygiene/Stage A/Stage B/Stage C/Stage D/persistence/XLS suite: 343 passed, 5 subtests passed, 0 failures
- Full repository suite: 634 passed, 1 skipped, 19 subtests passed, 0 failures
- Python compilation and `git diff --check`: passed
- No GitHub CI result is claimed.

## Limitations

- Legacy records remain semantically coarse and unverified until separately re-extracted; compatibility does not upgrade them.
- Phase 1 does not infer missing clauses, implement coverage diagnostics, perform fuzzy deduplication, or build a general legal contradiction engine.
- Stage D interpretation validation enforces identity, kind, state, and authority boundaries. It cannot prove the legal quality of free-text explanation, which remains explicitly AI-assisted.
- Amendment-aware structured deliverable replacement depends on explicit supersession data already available to the pipeline; Phase 1 does not add a second supersession framework.
- Full British Council acceptance is not claimed. Frozen Bank acceptance was not rerun.

**NO MIGRATION 004**

**NO MODEL CHANGE**

**FULL BRITISH COUNCIL ACCEPTANCE NOT CLAIMED**

**FROZEN BANK ACCEPTANCE NOT RERUN**
