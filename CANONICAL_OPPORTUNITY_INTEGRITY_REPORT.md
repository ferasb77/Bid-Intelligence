# Canonical Opportunity / Date / Commercial Integrity — Phase 1

## Scope and architecture

Base `main` was verified at `e8b20238afc75e57185a705ff09f43d1db016831` before work began. The implementation adds the versioned `canonical-opportunity/1` in-memory contract:

1. Stage A emits atomic typed observations for identity, milestones, contract term, money, procurement mechanics, and document role.
2. Stage B builds an immutable observation ledger with deterministic SHA-256 observation, normalized-identity, source-document, occurrence, conflict, and input IDs.
3. Stage C applies explicit supersession, exact agreement resolution, and field-linked conflicts.
4. Stage D receives a compact resolved/status summary and verified mechanics. The complete ledger remains in the authoritative sidecar/checkpoints.
5. Deterministic fields are removed from the model response before legacy citation validation and reapplied from the canonical ledger after validation.

The public extraction result remains `bid`, `brief`, `requirements`, `documents`, and `outline`. The internal canonical object is not persisted or returned as a new public top-level field.

## Files changed

- `canonical_opportunity.py`: canonical schema, IDs, provenance validation, resolution, field-linked conflicts, compact projection, and authoritative reapplication.
- `extractor.py`: Stage A schema, Stage A observation aggregation, Stage B/C integration, checkpoint artifacts, and post-Stage-D reapplication.
- `stage_d_projection.py`: internal-field registry, compact canonical prompt summary, field-local conflict constraints, and legacy replay fallback.
- `pages/stage_understand.py`: null classifications display as `Not classified`.
- `tests/test_canonical_opportunity.py`: canonical contract and regression coverage.
- `scripts/run_canonical_contract_smokes.py`: small live Haiku Stage A/Stage D contract smoke.
- `scripts/measure_canonical_integration.py`: retained-fixture and synthetic Stage D size measurements.
- `tests/acceptance/results/canonical_opportunity_live_contract_smokes.json`: sanitized live evidence.
- `tests/acceptance/results/canonical_opportunity_stage_d_measurements.json`: offline size evidence.

## Observation contract

Every accepted logical observation retains its original and normalized values, normalization state, stable source-document identity, source refs, provenance status, document role and basis, source state/pointer, explicit scope, supersession state, conflict IDs, and extraction occurrences. Repeated extraction of the same physical occurrence collapses into one logical observation while retaining separate occurrence records. Distinct source coordinates produce distinct observations.

Identity resolution excludes `DOCUMENT_TITLE` from opportunity title and `DOCUMENT_REFERENCE_NUMBER` from solicitation number. Empty and weakly grounded candidates remain in the ledger but cannot independently resolve an executive field. Source order, filename order, processing order, and document role do not choose a winner.

Dates use milestone kind and explicit component/lot/category scope. Opportunity-level submission and clarification deadlines resolve independently. Scoped pricing, technical, or lot deadlines stay in the ledger and do not compete for the headline deadline.

Term observations keep initial duration, dates, options, maximum term, and conditions separate. Optional extensions are displayed as optional components. Exact month/year duration versus start/end inconsistencies create a conflict linked only to `/resolved/contract_term`.

Money uses decimal strings and explicit currency. Estimated value, ceiling, budget, scenario values, rate caps, and spend guarantees remain distinct. Only an unscoped, verified, explicitly denominated `ESTIMATED_CONTRACT_VALUE` can resolve the internal headline value. `value_cad` remains automatically null.

Procurement mechanics stay atomic. Tier 1 maps only explicit verified mechanics. RFP alone does not classify principal subject matter. Stage D Tier 2 remains permitted when Tier 1 is `NOT_CLASSIFIED`.

## Provenance verification

Locator presence alone never produces `VERIFIED`. The validator selects the cited deterministic source-marker segment and requires the excerpt to occur there after whitespace-only normalization. A valid document with only a locator or only a grounded excerpt is `PARTIAL`; fabricated documents, locators, and excerpts are retained as weak evidence and cannot resolve executive values.

## Supersession and conflicts

Only the controlled explicit supersession bases are accepted, and only with verified provenance and explicit observation targets. Superseded observations remain in the ledger. Cycle detection prevents application of cyclic supersession.

New conflicts carry stable IDs, state, semantic kind, scope, affected field pointers, affected observations, incompatible values, source refs, link status, and resolution fields. Submission, clarification, and term conflicts suppress only their linked field. Unrelated or unlinked conflicts remain visible without suppressing dates or term. Old retained checkpoints without typed observations keep the former compatibility behavior; the pipeline does not invent canonical observations from benchmark knowledge.

## Stage D authority and capacity

The existing seven authoritative sections are unchanged. Canonical title, client, solicitation number, independently resolved dates, structured term, internal headline value, and Tier 1 classifications are reapplied after validated synthesis. Stage D cannot override them. `value_cad` remains null.

The 580,000-character guard is unchanged. Exact measurements include output schema size:

| Fixture | Before | After | Difference | Headroom |
|---|---:|---:|---:|---:|
| Bank of Canada retained facts | 120,478 | 121,795 | +1,317 | 458,205 |
| British Council Attempt 2 retained facts | 49,147 | 50,455 | +1,308 | 529,545 |
| Native synthetic canonical package | 10,197 | 11,763 | +1,566 | 568,237 |

The complete canonical ledger was absent from every prompt measurement and present only in authoritative runtime/sidecar state. All cases remained comfortably below the guard.

## Live contract smokes

The model remained `claude-haiku-4-5-20251001`.

Generic Stage A smoke:

- 10 typed observations, all deterministically verified
- title, buyer, solicitation number, submission and clarification deadlines, initial term, optional extension, estimated CAD value, RFP, and single-supplier award remained distinct
- 0 recovery attempts; no truncation signal
- serialized Stage A result: 8,015 characters

Adversarial Stage A smoke:

- 9 typed observations, all deterministically verified
- two deadline occurrences were retained
- framework ceiling and evaluation-scenario value remained separate
- framework, multiple-supplier award, call-off, no-guaranteed-volume, and rate-card mechanics remained atomic
- 0 recovery attempts; no truncation signal
- serialized Stage A result: 9,940 characters

The Stage A instruction text increased from 9,414 to 11,904 characters. No Stage A token limit, chunk size, retry, or recovery setting changed. The live response sizes above showed no truncation/recovery regression. A same-model pre-change response-size comparison was not rerun because that would add calls solely for historical comparison.

The Stage D-only canonical smoke dispatched successfully. JSON parsing/citation validation, authoritative reapplication, and final assembly passed. An unrelated envelope conflict left the resolved submission deadline intact. The request was 14,071 characters with 565,929 characters of headroom.

## Retained replays

Bank of Canada retained facts predate typed observations. The replay path remains compatible and the retained artifacts were not modified. Deterministic canonical tests prove that submission conflict affects submission only, clarification remains independent, term conflict affects term only, and unlinked conflicts suppress nothing. A new blind acceptance run is not claimed.

British Council Attempt 2 retained facts also predate typed observations. Existing requirements and provenance remain projectable, but canonical identity, term, money, and mechanic improvements blocked by missing Stage A observations are not synthesized from benchmark knowledge. The full Stage A package was not rerun.

**FULL BRITISH COUNCIL ACCEPTANCE NOT CLAIMED.**

## Validation

- Focused canonical/Stage D suite: 96 passed
- Broader focused canonical/Stage A/Stage D suite before remediation: 122 passed; the remediation-specific focused run then passed 96/96
- Full repository suite: 535 passed, 1 skipped, 19 subtests passed, 0 failures
- GitHub CI: not run/claimed

Requirements, evaluation hierarchy, submission projection, and the seven authoritative sections passed the unchanged repository regression suite. Checkpoint modes remain `off`, `best_effort`, and `required`.

## Persistence and remaining work

**NO MIGRATION 004.** Migrations 001–003 remain the live schema baseline. No database schema changed, and the canonical ledger is not persisted to database tables. Phase 2 can design lossless persistence for amount kind, currency, tax basis, guarantee status, scopes, resolved states, and observation/conflict provenance before any safe legacy-value population is considered.

Legacy checkpoints cannot gain source observations that Stage A never extracted. Maximum-potential term is accepted only when explicitly observed in Phase 1; automatic arithmetic across multiple option observations remains conservative. Calendar consistency checks cover exact month/year durations with exact start/end dates and do not approximate days or infer time zones.

## Final-review remediation

Final review identified and closed the following gaps:

- Source markers are now parsed into named components. Pages compare as exact integers; sheet and section use whitespace-normalized exact equality; row and cell coordinates use explicit interval containment. Digit or field-name substrings cannot validate a locator.
- Stage A supersession now emits source-level family, semantic kind, old/new value, scope, and evidence. Stage B resolves that relationship to canonical IDs only when verified evidence and one normalized target identity establish the match. Missing or ambiguous targets remain unresolved, and cycle detection remains active.
- Canonical coverage is explicit per executive field. When a field lacks typed coverage, deterministic legacy deadline/term conflicts suppress only the field identified by the legacy topic/type. Envelope, bilingual, and unlinked conflicts suppress no unrelated field.
- Extension and renewal observations are repeatable. Different unsequenced options coexist; contradictory values for the same explicit option sequence or ID conflict. Display formatting renders duration, optionality, count, and conditions as text without Python object representations.
- Verified canonical mechanic observations receive prompt-local `o*` aliases and ordinary evidence aliases. Only their visible fields are citable. The existing validator rejects unknown aliases, hidden fields, and evidence owned by another entity. Tier-2 classification requires canonical mechanic support when the canonical path permits Tier 2.
- Family/kind combinations use controlled sets. Invalid combinations are retained as non-authoritative integrity diagnostics.
- Date precision is controlled, `DAY` normalizes to `DATE`, ISO calendar dates and 24-hour times are validated, and timezone remains null unless supplied.
- Extraction occurrences use stable content digests and counts rather than list positions. All same-document observation-order permutations produce identical canonical objects and authoritative input digests.
- Verified `BUYER_NAME` observations own client resolution. `ISSUING_AUTHORITY` is a fallback only when no eligible buyer observation exists.
- The remaining global-conflict sentence was removed from the Stage D prompt and replaced with field-linked conflict instructions.

### Final live evidence

The explicit amendment package produced two Stage A deadline observations. Haiku emitted a source-level relationship without canonical IDs; Stage B/C marked `2030-03-01` `SUPERSEDED`, kept `2030-03-05` `ACTIVE`, and resolved the submission deadline to `2030-03-05`. All Stage A smoke paths completed with zero recovery attempts.

The adversarial money source emitted both `FRAMEWORK_CEILING` and `EVALUATION_SCENARIO_VALUE` as separate observations. No-guaranteed-volume and pricing mechanics remained separate observations.

The final Stage D smoke was retried only from the immutable required-mode sidecar after a model citation-format failure; Stage A/B/C call counts were zero. Tier-2 `Advisory` passed with five canonical observation supports. Citation validation, authoritative reapplication, and final assembly passed, and an unrelated conflict left the independently resolved clarification deadline intact.

### Final capacity measurements

| Fixture | Before | After | Difference | Headroom |
|---|---:|---:|---:|---:|
| Bank of Canada retained facts | 120,494 | 122,215 | +1,721 | 457,785 |
| British Council Attempt 2 retained facts | 49,163 | 50,875 | +1,712 | 529,125 |
| Native synthetic canonical package | 10,213 | 12,167 | +1,954 | 567,833 |

The full canonical ledger remains sidecar-only. The prompt contains only resolved/coverage summaries and the verified mechanic observations made visible for Tier-2 citations. The guard remains 580,000 characters.

### Final validation totals

- Focused canonical, Stage A, Stage D, and completeness suites: 191 passed, 5 subtests passed
- Full repository suite: 550 passed, 1 skipped, 19 subtests passed, 0 failures
- GitHub CI: not run or claimed

The final remediation does not change migrations, database schema, model, Stage A chunking/retry/recovery, or the Stage D guard. Full British Council acceptance remains unclaimed.

## Final pre-PR safety correction

Two deterministic safety gaps were corrected after the final remediation review.

Canonical conflict coverage is no longer inferred from the presence of any typed observation. A mapped legacy submission, clarification, or contract-term conflict keeps that field unresolved unless the canonical field is already conflicted or a verified source-level supersession accounts for both legacy alternatives. A lone typed October 1 submission deadline therefore cannot override a legacy October 1 versus October 3 disagreement. A verified October 1 to October 3 amendment continues to resolve October 3. Clarification remains independent, and envelope/bilingual conflicts suppress no dates or term.

Headline submission and clarification deadlines now require day-level authority. `DATE` requires strict `YYYY-MM-DD` and a valid calendar date. `DATETIME` requires the same valid date plus a valid 24-hour time; its date component may resolve the headline. `MONTH`, `YEAR`, and `UNKNOWN` precision observations remain in the ledger but cannot independently resolve an executive deadline. Invalid dates and times remain `UNPARSED`, and timezone is never inferred.

No live AI calls were needed because neither correction changes the provider contract.

Validation after this correction:

- Focused canonical/Stage C/Stage D suites: 236 passed, 5 subtests passed
- Full repository suite: 555 passed, 1 skipped, 19 subtests passed, 0 failures
- Database schema and migrations: unchanged; no Migration 004
- Model, Stage A chunking/retry/recovery, and Stage D guard: unchanged
