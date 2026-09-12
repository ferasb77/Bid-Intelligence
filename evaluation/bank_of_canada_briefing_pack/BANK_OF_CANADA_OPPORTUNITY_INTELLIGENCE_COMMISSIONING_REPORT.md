# Bank of Canada RFP 2026-026 — Opportunity Intelligence Commissioning Report

**Commissioning run ID (authoritative, post-fix):** `oppint-boc-2026-026-20260912T161717Z-50ab1a`
**Pre-fix diagnostic run (superseded):** `oppint-boc-2026-026-20260912T161309Z-339310`
**Artifact directory:** `evaluation/bank_of_canada_briefing_pack/opportunity_intelligence_commissioning/oppint-boc-2026-026-20260912T161717Z-50ab1a/`

## A. Metadata

| | |
|---|---|
| Phase 1 (Stage A, frozen) | `phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5` |
| Stage B (regenerated, canonical-term-fix) | `phase2-boc-2026-026-stageb-canonterm-fix-20260912T142551Z-34a031` |
| Stage C (refreshed) | `phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8` |
| Canonical Opportunity (accepted) | `canonopp-boc-2026-026-20260912T142551Z-34a031` |
| Opportunity Structure (accepted) | `oppstruct-boc-2026-026-20260912T144353Z-dd4b10` |
| Production entry point | `opportunity_intelligence.analyze_opportunity(normalized_facts, conflicts, context_id=...)` → `OpportunityIntelligenceAnalyst.analyze()` → `DecisionAnalysis` |
| Analyst ID / version | `opportunity-intelligence` / `1.0.0` |
| Model used | **none — 100% deterministic** |
| Runtime | 0.136s |
| Tokens / cost | not applicable — 0 |

## 1/B. Implementation inspection and dependency trace

Read in full before anything was run: `opportunity_intelligence.py` (422 lines), `decision_intelligence.py` (299 lines, the generic typed-contract framework), `decision_analyst.py` (421 lines, the analyst registry/validation layer), plus `tests/test_opportunity_intelligence.py`, `scripts/probe_opportunity_intelligence.py`, `scripts/continue_opportunity_intelligence.py`.

**No LLM is used anywhere in this boundary.** Confirmed by direct code inspection: zero references to `anthropic`, `client.messages`, or `get_anthropic_client` in `opportunity_intelligence.py`, `decision_intelligence.py`, or `decision_analyst.py`. The entire `analyze()` method is pure Python (`Counter`, arithmetic, date math, set operations). **Section 21 of the audit spec (one real LLM commissioning run with telemetry) does not apply — there is no model to commission.** This is stated here rather than assumed from the module name.

**Production entry point:** `analyze_opportunity(normalized_facts, conflicts=(), *, context_id, statements=())`, a thin wrapper that builds an `OpportunityAnalysisContext` and calls `OpportunityIntelligenceAnalyst().analyze(context)`.

**Exact inputs:**
- `normalized_facts`: the *full* Stage B/C `normalized_facts` mapping — reads `requirements`, `deliverables`, `commercial_clauses`, `evaluation_criteria`, `submission_rules`, `dates`, and `_canonical_opportunity` (`observations`, `resolved`, `conflicts`). Does **not** read `_contract_hygiene` or `_provenance_rejections` directly (those already shaped `deliverables`/`commercial_clauses` upstream in Stage B).
- `conflicts`: a tuple of conflict mappings — **in every real production invocation this is Stage C's own governed `conflicts` return value** (confirmed by both `scripts/probe_opportunity_intelligence.py` and `scripts/continue_opportunity_intelligence.py`, which load `stage-c-conflicts.json` directly), which already has canonical opportunity's own conflicts merged in by `reconcile_package_facts()`.
- `context_id`: caller-supplied; in the real downstream pipeline (per `continue_opportunity_intelligence.py`) this is the deterministic identity of the published Canonical Opportunity object, not an arbitrary label.

**Exact output type:** `DecisionAnalysis` (from `decision_analyst.py`) — a frozen dataclass: `analysis_id, analyst_id, execution_timestamp, overall_confidence, evidence_used, computed_facts, inferences, hypotheses, recommendations, limitations, assumptions, unanswered_questions, unknowns`.

**Does NOT consume:**
- **Opportunity Structure's 692-record ledger** — `opportunity_structure.py` is never imported by `opportunity_intelligence.py`. Opportunity Intelligence is a **sibling** consumer of the same Stage B/C `normalized_facts`, not a downstream consumer of Opportunity Structure. It independently recomputes its own record identities from the same raw `requirements`/`evaluation_criteria`/etc. sections using the *same* `_record_id` function Opportunity Structure imports *from* this module (confirmed identical by cross-referencing entity IDs directly, Section P).
- **Stage D synthesis** — no reference anywhere.
- **Raw evidence catalog objects** (`evidence.py`) — not imported; `_evidence_ids()` only reads an `evidence_id` string if a record happens to already carry one (Stage A does not populate this field in this corpus, so in practice every `EvidenceSupport.evidence_ids` is empty).

**Provenance requirements:** Opportunity Intelligence does **not** independently re-validate `source_refs` against corpus text the way Canonical Opportunity's and Opportunity Structure's `_validate_ref` do — it is never imported here. It relies entirely on records already having passed Stage B's own upstream filtering (e.g. `commercial_clauses`/`deliverables` already restricted to `evidence_state: VERIFIED` + legacy records by Stage B itself) and on `_canonical_opportunity`'s own `provenance_status` field for observations specifically. This is a real, honest architectural gap documented in Section F, not a violation on its own.

**Confidence model:** `Confidence` enum has exactly 4 values: `LOW, MODERATE, HIGH, UNKNOWN`. This analyst's code path can only ever emit `MODERATE` (for its one inference and derived hypotheses) or `UNKNOWN` (`overall_confidence` when no inferences fire). **`HIGH` and `LOW` are never used anywhere in this implementation.**

**Inference rules:** exactly one, entirely deterministic and threshold-based: if `len(requirements) >= 20`, `len(submission_rules) >= 5`, `len(submission_pathways) > 1`, or `hierarchy_depth >= 2`, each contributes a named "driver" to a single `AI_INFERENCE`-typed statement ("The documented structure contains potential proposal-effort drivers: …") plus one `AnalystHypothesis` per driver.

**Validators (`validate_opportunity_analysis`):**
- Forbids any `recommendations` (raises if non-empty) and any `HUMAN_DECISION`-typed statement.
- Re-derives the full set of `allowed_evidence` from the *same* authoritative `context.normalized_facts`/`context.conflicts` and asserts `output.evidence_used` is a subset — no evidence can be invented.
- **Asserts `expected_conflicts.issubset(output.unknowns.unresolved_conflict_ids)`** where `expected_conflicts` is derived from every conflict in `context.conflicts` — this is a hard, enforced guarantee that **every conflict passed in must appear in the output's unresolved list**; the function that computed the analysis also re-checks it never mutated its own input (`before != after` digest comparison raises `ContractValidationError`).
- The generic `DecisionAnalystRegistry.validate_output` additionally enforces that the analyst never emits a statement type or evidence entity type it didn't declare in its own `METADATA`.

**Failure behavior:** any contract violation raises `ContractValidationError` (a `ValueError` subclass) — fails closed, never silently degrades.

**Downstream consumers today:** **none in the live application.** Confirmed by an exhaustive repository-wide search: `analyze_opportunity`/`OpportunityIntelligenceAnalyst` appear only in `opportunity_intelligence.py` itself, its own tests, and standalone commissioning/probe scripts (`scripts/continue_opportunity_intelligence.py`, `scripts/probe_opportunity_intelligence.py`) — zero references in `pages/`, `pages_extra.py`, `database.py`, or `analyst.py`. This is an intentional, tested invariant (`tests/test_opportunity_intelligence.py::test_optional_integration_does_not_import_into_existing_pipeline`), matching the module's own docstring: "Optional post-pipeline integration point; existing pipeline calls remain unchanged."

## 3. Input dependency lock

| Consumed? | Source |
|---|---|
| 692 Opportunity Structure records | **No** — not consumed at all (separate, sibling boundary) |
| Canonical Opportunity (`_canonical_opportunity`) | **Yes** — `observations`, `resolved`, `conflicts` all read directly |
| The 8 Stage C conflicts | **Yes** — passed as the `conflicts` parameter |
| The 4 Opportunity Structure conflicts | **No** — Opportunity Structure's own `struct_conf_*` conflicts are never generated by or passed into this boundary in the real pipeline |
| Provenance status (VERIFIED/PARTIAL/UNVERIFIED) | Partially — only for `_canonical_opportunity.observations` (via `ambiguous_observation_ids`); not independently computed for requirements/deliverables/clauses/submission_rules |
| Stage D | **No** |
| Raw evidence catalog objects | **No** — only a record's own (usually absent) `evidence_id` field |

**Locked to:** `phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8/stage_c_normalized_facts.json` and `stage_c_conflicts.json` — the latest, refreshed artifacts, not the superseded 7-conflict Stage C run. No Stage A rerun. No Stage D invocation.

## 4/C. Real Opportunity Intelligence schema

Using the analyst's actual, real terminology (not invented categories):

| Object family | Type | Required/optional | Meaning | Confidence | Status/reasoning | Scope | Conflict linkage | Downstream |
|---|---|---|---|---|---|---|---|---|
| `computed_facts` | `DecisionStatement` (`statement_type=COMPUTED_FACT`) | 0..n, each requires non-empty `evidence_support` | a deterministic count/aggregate derived directly from governed records | **always `None`** (schema forbids confidence on non-reasoning statements) | `ReasoningStatus.VALIDATED` | via `EvidenceSupport.entity_type`/`entity_id` | none directly, but `total_conflicts`/`unresolved_milestone_conflicts` summarize conflict counts | none live today |
| `inferences` | `AnalystReasoning` wrapping a `DecisionStatement` (`statement_type=AI_INFERENCE`) | 0..n, requires `confidence` + non-empty `evidence_support` | an interpretive conclusion beyond a raw count | `MODERATE` or `UNKNOWN` only (never `HIGH`/`LOW` in this implementation) | `ReasoningStatus.PROPOSED` | via `assumptions`/`limitations` fields | none | none live today |
| `hypotheses` | `AnalystHypothesis` | 0..n, requires `supporting_evidence` or `contradicting_evidence` | one candidate explanatory factor for an inference, explicitly **unranked** relative to its siblings | `MODERATE` | `SupportStatus.PARTIALLY_SUPPORTED` | — | — | none live today |
| `recommendations` | `AnalystRecommendation` | **always empty — validator forbids any** | n/a | n/a | n/a | n/a | n/a | n/a |
| `unknowns` | `AnalystUnknowns` | always present | `missing_evidence` (bidder-evidence-readiness gaps), `unresolved_conflict_ids` (validator-enforced superset of every passed conflict), `ambiguous_observation_ids` (canonical observations that are non-VERIFIED or unparsed) | n/a | n/a | n/a | **this is the primary, validated conflict-preservation mechanism** | — |
| `assumptions` | `AnalystAssumption` | 0..n | a named premise the one inference depends on | n/a | n/a | — | — | — |
| `unanswered_questions` | `ManagementQuestion` | 0..n | a question for a human decision-maker, linked to specific analysis conclusions | n/a | n/a | — | — | — |
| `limitations` | tuple of strings | 0..n | plain-language caveats about what this analysis cannot claim | n/a | n/a | — | — | — |

No richer schema was invented for this commissioning.

## 5/E. Fact vs. inference vs. decision-signal audit

Using the schema's own terminology: **`COMPUTED_FACT` (FACT)**, **`AI_INFERENCE` (INFERENCE)**, and **there is no `RECOMMENDATION`/decision-signal category populated at all** — `output.recommendations` is validator-enforced to be empty for this analyst (`METADATA.supported_statement_types` does not include `RECOMMENDATION`). Opportunity Intelligence v1's contract explicitly excludes decision signals; only FACT and INFERENCE (plus the unranked HYPOTHESIS sub-category and UNKNOWN/uncertainty statements) exist.

Every one of the 28 conclusion-bearing items produced in this run was individually classified:

| Category | Count | Notes |
|---|---:|---|
| FACT (`COMPUTED_FACT`) | 23 | pure counts/aggregates, no interpretation (full list in Section D below) |
| INFERENCE (`AI_INFERENCE`) | 1 | "The documented structure contains potential proposal-effort drivers…" — explicitly hedged (`MODERATE`, `PROPOSED`, `PARTIALLY_SUPPORTED`, carries its own `assumptions`/`limitations`) |
| HYPOTHESIS | 4 | one per driver named in the inference, each independently `MODERATE`/`PARTIALLY_SUPPORTED`, explicitly documented as unranked |
| RECOMMENDATION / decision signal | 0 | not part of this analyst's contract |
| UNCERTAINTY/GAP (`unknowns`) | 3 collections | `missing_evidence` (427 items), `unresolved_conflict_ids` (8), `ambiguous_observation_ids` (33) |

**No inference masquerades as a sourced fact.** The one `AI_INFERENCE` is never given `ReasoningStatus.VALIDATED` (reserved for facts) — it is `PROPOSED`, and its `SourceType` is `SPECIALIST_ANALYST`, never `AUTHORITATIVE_SOURCE` (a type-mismatch there is itself schema-enforced and would raise `ContractValidationError`).

## D. Complete intelligence inventory

**All 23 computed facts (verbatim):**
```
clarification_to_submission_days=null
criteria_missing_weights=46
deliverable_count=23
evaluation_hierarchy_depth=2
mandatory_artifact_count=58
mandatory_requirements=314
milestone_completeness={"dated":7,"observed":16}
milestone_intervals_days=[["PUBLICATION_DATE","AMENDMENT_DATE",1],["AMENDMENT_DATE","AMENDMENT_DATE",4],
  ["AMENDMENT_DATE","CLARIFICATION_DEADLINE",9],["CLARIFICATION_DEADLINE","AMENDMENT_DATE",11],
  ["AMENDMENT_DATE","INTENT_TO_BID_DEADLINE",7],["INTENT_TO_BID_DEADLINE","SUBMISSION_DEADLINE",2]]
monetary_observation_count=0
optional_requirements=0
partial_date_count=0
requirement_category_counts={"FINANCIAL":1,"GENERAL COMPLIANCE":1,"MANDATORY":314,"RATED":89,
  "SUBMISSION COMPLIANCE":13,"SUPPORTING":9}
requirement_evidence_coverage={"ready":0,"total":427}
submission_artifact_count=68
submission_pathway_count=4
threshold_count=10
total_conflicts=8                        <- corrected this commissioning, was 12 pre-fix
total_requirements=427
undated_milestone_labels=[9 labels, e.g. "Agreement Commencement Date", "Submission Deadline"]
unresolved_milestone_conflicts=1          <- corrected this commissioning, was 0 pre-fix
unresolved_submission_ambiguity=2
verified_clause_counts={20 clause_kind buckets summing to 91}
weighted_criteria=37
```

**The 1 inference:** *"The documented structure contains potential proposal-effort drivers: requirement volume, submission artifact volume, multiple submission pathways, evaluation hierarchy depth."* — `MODERATE` confidence, `PROPOSED`, `PARTIALLY_SUPPORTED`, assumption: *"Structural volume is a relevant effort indicator"*, limitation: *"No staffing or effort-rate model is available"*.

**The 4 hypotheses** (each `MODERATE`/`PARTIALLY_SUPPORTED`, limitation *"The explanation is not ranked against other drivers"*):
1. "The apparent proposal effort may be explained by requirement volume."
2. "…by submission artifact volume."
3. "…by multiple submission pathways."
4. "…by evaluation hierarchy depth."

**1 assumption**, **1 management question** ("Which documented uncertainties require management escalation before allocating internal effort?"), **4 limitations** (including a dynamically-generated one naming all 9 undated milestones).

Full raw dump (all statement/evidence-support detail): `opportunity_intelligence_full.json` in the artifact directory.

## F. Provenance-status dependency (VERIFIED / PARTIAL / UNVERIFIED)

**Opportunity Intelligence does not independently compute or expose a VERIFIED/PARTIAL/UNVERIFIED provenance tier for requirements, deliverables, commercial clauses, or submission rules at all** — that re-validation (`canonical_opportunity._validate_ref`) is never imported here; it belongs exclusively to Canonical Opportunity and Opportunity Structure. The only place this tier exists in Opportunity Intelligence's output is `unknowns.ambiguous_observation_ids`, computed from `_canonical_opportunity.observations[*].provenance_status` directly (33 of 120 observations: the union of 23 `PARTIAL` + 2 `UNVERIFIED` + a handful of `VERIFIED`-but-`UNPARSED` ones).

**Does any computed fact/inference depend on an UNVERIFIED item as sole support?**
- The one inference and its 4 hypotheses cite `req_links` — `EvidenceSupport` entries for **every** requirement record regardless of any provenance tier — but the claim itself is a **volume/count-based structural observation** ("there are ≥20 requirement records"), not a claim about any single requirement's content. Counting how many records were extracted is true regardless of whether any individual record's own citation could be independently verified; it is not the kind of "convert weak evidence into a confident factual assertion" the acceptance criteria warns against.
- Non-requirement computed facts (milestone/date/monetary-derived) are attributed to the generic root `CANONICAL_FACT` context link, **not** to individual observations — so they do not make an individually-unverifiable claim look independently certain either.
- **`HIGH` confidence is never used anywhere in this implementation** — the ceiling for any interpretive statement is `MODERATE`, and it always ships with explicit `assumptions`/`limitations` disclosing exactly what is not known. There is no code path by which an UNVERIFIED record alone could produce a high-confidence conclusion, because no confidence tier above `MODERATE` exists in this analyst's real output.

**The 3 fully UNVERIFIED Opportunity Structure records** (1 `COMMERCIAL_CLAUSE`, 1 `SUBMISSION_RULE`, 1 `EVALUATION_CRITERION` with empty/blank `source_refs`, from the prior commissioning) were traced end-to-end: none of them is a canonical-opportunity observation (they belong to the separate `requirements`/`evaluation_criteria`/`commercial_clauses`/`submission_rules` families), so they do not appear in `ambiguous_observation_ids` either (that field only covers `_canonical_opportunity.observations`). They are counted, undifferentiated, within the plain `total_requirements`/`submission_artifact_count`/`verified_clause_counts`(the commercial clause itself has no `clause_kind` distinction lost) aggregates — **no intelligence conclusion singles any of them out or treats any one of them as decisive**, since every conclusion in this run operates at the aggregate/volume level, never citing one specific record's content as an asserted fact.

**Conclusion: no defect found under the provenance-severity rule.** The real gap — Opportunity Intelligence's total blindness to the VERIFIED/PARTIAL/UNVERIFIED tier for 4 of 5 record families — is an honest architectural limitation, not a violation, and is recorded here for future hardening rather than treated as a commissioning failure (there is no false confidence being manufactured today).

## G/7. Eight Stage C conflict trace

`unknowns.unresolved_conflict_ids` (verified against the actual output, not merely the validator's guarantee):
```
['CONF-EVAL-1', 'CONF-EVAL-2', 'CONF-EVAL-3', 'CONF-EVAL-4',
 'conf_64da8f52…' (contract_term), 'conf_68a3a3a5…' (client),
 'conf_8c65820f…' (file_number), 'conf_a06e6957…' (title)]
```
**All 8 present — exact match, none missing, none extra.**

| Conflict | Classification |
|---|---|
| `CONF-EVAL-1..4` (evaluation weight discrepancies) | **A — explicitly represented as uncertainty** (in `unresolved_conflict_ids`) |
| `title`/`client`/`file_number` conflicts | **A** |
| **`contract_term` conflict (new)** | **A** — present in `unresolved_conflict_ids`; separately, the corrected `unresolved_milestone_conflicts=1` computed fact now also reflects it numerically (Section H below) |

**Zero conflicts fall into category D.** Opportunity Intelligence never asserts a single agreement duration, buyer name, title, or file number as settled fact anywhere in its computed facts, inference, or hypotheses — it has no field for any of these at all (Section I/J below).

## H. Confirmed defects, root cause, and fix

Two computed-fact correctness defects were found and fixed during this commissioning (not schema/validator weaknesses — both are pure statistical-accuracy bugs in derived numbers):

**Defect 1 — `total_conflicts` double-counted canonical conflicts.** `reconcile_package_facts()` (the real Stage C) always merges `_canonical_opportunity`'s own conflicts into the list it returns, so the `conflicts` parameter already contains them in every real invocation. The old code computed `len(conflicts) + len(canonical.get("conflicts", []))`, double-counting the 4 canonical conflicts (title/client/file_number/contract_term) that appear in both places. Observed on real data: reported **12** when the true distinct count is **8**.
*Fix:* count the union of distinct conflict identities (`_record_id`-based, the same identity scheme already used for `unresolved_conflict_ids`) across both sources — correct regardless of whether a caller's `conflicts` argument already includes canonical's or not.

**Defect 2 — `unresolved_milestone_conflicts` was dead code.** The check tested whether a conflicted resolved-field's *state dict* (`{"status": "CONFLICTED", "value": None, "conflict_ids": [...], ...}`), stringified, contained the words `DATE`/`DEADLINE`/`TERM` — but a state dict's own keys and (null) values never literally spell those words, so this could never match any real conflict, including the new `contract_term` one. Observed on real data: reported **0** despite `contract_term` being genuinely `CONFLICTED`.
*Fix:* check the resolved **field name** (`"contract_term".upper()` contains `TERM`; `"submission_deadline"`/`"clarification_deadline"` contain `DEADLINE`) instead of the state dict's content — a one-line, minimally-scoped correction.

**Constitutional impact:** neither defect caused a conflict to be silently *resolved* or *hidden* — the validator-enforced `unresolved_conflict_ids` guarantee (Section G) was intact and correct throughout, independent of these two bugs. Both were auxiliary, redundant *summary statistics* reporting a wrong number alongside an otherwise-correct, fully-preserved conflict list. They are still real defects (a wrong count is misleading on its own) and were fixed at root, not weakened around.

**Regression tests added** (`tests/test_opportunity_intelligence.py`, +4):
- `test_total_conflicts_does_not_double_count_canonical_conflicts_already_merged`
- `test_total_conflicts_still_correct_when_conflicts_do_not_already_include_canonical`
- `test_unresolved_milestone_conflicts_counts_conflicted_term_and_deadline_fields`
- `test_unresolved_milestone_conflicts_ignores_conflicted_non_date_fields`

**Validation:**
```
py_compile opportunity_intelligence.py tests/test_opportunity_intelligence.py  -> COMPILE_OK
git diff --check                                                                -> clean
pytest tests/test_opportunity_intelligence.py -q                                -> 21 passed
pytest -q (full repository suite)                                               -> 1198 passed, 2 skipped
```

Opportunity Intelligence was then recommissioned from the identical frozen artifacts (zero LLM, zero Stage A/B/C rerun): `total_conflicts` now reads **8**, `unresolved_milestone_conflicts` now reads **1** — both verified directly against the real corpus, not merely asserted.

## I/8. Opportunity Structure's 4 local conflicts (evaluation-role ambiguity)

**Category C — outside this analyst's current vocabulary, not silently resolved.** Opportunity Intelligence does not consume Opportunity Structure's output at all (Section 3), so it never sees the `struct_conf_*` role-ambiguity conflicts as conflict objects. More specifically, checked directly: `opportunity_intelligence.py` computes `weighted_criteria`, `criteria_missing_weights`, `threshold_count`, `evaluation_hierarchy_depth` from `evaluation_criteria` records, but **never reads the `role`, `role_conflict`, `role_observations`, or `is_structural_container` fields anywhere** — confirmed by exhaustive search of the module. It therefore neither preserves, lowers confidence for, nor silently chooses among `Award Criterion`/`Structural Container`/`Unknown` for the 4 affected criteria — the dimension is simply absent from every computed fact, inference, and hypothesis. This is a legitimate category-C outcome under the acceptance framework (only D — silently choosing a role — would be a failure), not a violation, though it is worth noting this specific role-ambiguity signal that Opportunity Structure surfaces is not yet visible anywhere in Opportunity Intelligence v1.

## J/9. Contract-term safety

Searched all 23 computed facts, the 1 inference, and the 4 hypotheses (full text, Section D) for `"12 weeks"`, `"3 years"`/`"three years"`, `"agreement duration"`, `"contract duration"`, `"engagement period"`, `"HR Advisory"`. **Zero hits, in any of the 28 conclusion-bearing items.** `contract_term` is not among the fields `opportunity_intelligence.py` reads from `_canonical_opportunity.resolved` at all (only `clarification_deadline` and `submission_deadline` are individually extracted for the `clarification_to_submission_days` computation). **The 12-week/HR-Advisory and 3-year facts are not represented anywhere in this analyst's output — there is no risk of a scoped fact masquerading as opportunity-wide, or of the contract-term ambiguity being silently resolved, because neither value is asserted at all.** The `contract_term` conflict's *existence* (not its content) is correctly represented via `unresolved_conflict_ids` and the now-fixed `unresolved_milestone_conflicts=1` (Section H) — that is the full extent of this analyst's current awareness of the contract-term dispute, and it is accurate.

## K/10. Procurement-model intelligence

Same exhaustive text search for `"multi-vendor"`, `"call-off"`, `"standing offer"`, `"panel agreement"`, `"single contract"`, `"procurement model"`. **Zero hits.** `opportunity_intelligence.py` never reads `resolved["procurement_model"]` or `resolved["opportunity_type"]`, and has no `PROCUREMENT_MECHANIC`-family handling at all (that family belongs exclusively to `canonical_opportunity.py`'s typed observations, which this analyst does not iterate by family the way `canonical_opportunity.py` itself does). **Opportunity Intelligence makes no procurement-model-related claim, inference, or implication whatsoever — so there is nothing to check for consistency with, or contradiction of, Canonical Opportunity's `"Multi-vendor Call-off"` resolution, and nothing resembling external procurement-mechanics knowledge (e.g. "competition may continue post-award") appears anywhere.**

## L/11. Buyer intent / priority inference

**None exists.** The complete, exhaustively-reviewed inventory of interpretive content (1 inference + 4 hypotheses, Section D) concerns exclusively the **bidder's own potential proposal effort** ("requirement volume," "submission artifact volume," "multiple submission pathways," "evaluation hierarchy depth") — an inward-facing structural observation about how much extracted material exists, never a claim about what the Bank of Canada values, prioritizes, or is likely to emphasize in evaluation. No mandatory criterion is characterized as a "top priority." No weight/threshold value is used to infer buyer emphasis. No boilerplate contract language (e.g. the 91 commercial clauses) is characterized as strategic intent. **This is a clean, complete compliance result: zero buyer-intent inferences of any kind exist in this analyst's real output**, confirming this v1 implementation's actual scope is narrower and more conservative than "opportunity intelligence" might suggest from the name alone.

## M/12. Evaluation intelligence

`weighted_criteria=37`, `criteria_missing_weights=46` (of 83 total — a container node legitimately has no weight, so this is a descriptive count, not an anomaly claim), `threshold_count=10`, `evaluation_hierarchy_depth=2`. **No statement anywhere claims "X is the most important criterion"** or ranks criteria against each other — there is no such computed fact, inference, or hypothesis in this analyst's real vocabulary. Category-specific weights are never summed or flattened globally: `weighted_criteria` is a plain count of how many of the 83 records carry *some* weight value, not an aggregate weight total, so no cross-category arithmetic occurs that could conflate a service-category-specific weight with an opportunity-wide one. Unresolved role/weight ambiguities (the 4 `role_conflict` records, Section I; the 4 `CONF-EVAL-*` cross-record title-collision conflicts, Section G) are never resolved into a clean scoring conclusion — because no scoring conclusion of any kind is produced by this analyst at all. Threshold (pass/fail gate) facts and weighted-award-criteria facts remain structurally distinct in the underlying `evaluation_criteria` records (their own `threshold`/`weight_value` fields), and this analyst does not conflate them into one metric.

## N/13. Commercial / contract intelligence

`verified_clause_counts` (Section D) — a plain count of the 91 verified clauses grouped by their **already-assigned** `clause_kind` (assigned upstream by `contract_hygiene.py`, not invented here). **No risk severity, obligation-vs-risk distinction, or "high risk" label of any kind is produced anywhere in this analyst's output** — `opportunity_intelligence.py` contains no risk-assessment logic, no severity vocabulary, and no legal-advice content. This is a purely structural tally.

## O/14. Deliverable / delivery intelligence

`deliverable_count=23` — a plain count. **No complexity, workload, delivery-pressure, resource-implication, sequencing-constraint, or implementation-risk inference is produced anywhere.** No quantity/timeframe field from the 23 deliverables is used as the basis for any interpretive claim in this analyst's real output.

## P. Master RFP contribution

Cross-referenced directly against Opportunity Structure's independently-published master-RFP-sourced record set, using the fact that both modules share the exact same `_record_id` identity scheme (`opportunity_structure.py` imports `_record_id` *from* `opportunity_intelligence.py`):

- **218 of 692 records Opportunity Structure attributes to the master RFP are all present in Opportunity Intelligence's `evidence_used` pool** (218/218 overlap — full coverage, nothing dropped).
- **105 of those are actually cited by a computed fact or the inference** (matching Opportunity Structure's own master-RFP `REQUIREMENT`-family count of 105 exactly) — the rest are declared-available evidence not specifically drawn on by any of the 23 counting statistics.
- **No implicit master-RFP authority boost exists** — `opportunity_intelligence.py` never branches on `source_doc` or document role anywhere; every record contributes to its aggregate count identically regardless of which of the 16 documents it came from.

## Q/19. Unsupported-external-knowledge audit

Every one of the 28 conclusion-bearing items (Section D) was read in full. **None references Bank of Canada culture, Canadian procurement practice, industry norms, incumbent vendors, typical pricing, or regulatory expectations not present in the corpus.** The entire interpretive surface area is four generic, domain-neutral structural labels ("requirement volume," "submission artifact volume," "multiple submission pathways," "evaluation hierarchy depth") applied via fixed numeric thresholds (`>=20`, `>=5`, `>1`, `>=2`) — no external reference point is consulted or required to produce them. **Unsupported external-knowledge count: 0.**

## R/20. Rejected-record safety

The 2 Stage B `ZERO_VALID_PROVENANCE` rejected records (`dlv_8c3cbc83de79a8d001e888f5`, `clause_8e80706aeb773fb11116b130`) were searched by exact identity against all 821 `evidence_used` entity IDs.
```
REJECTED RECORD RE-ENTRY: 0
```

## O/18. Confidence calibration

**Mechanism:** rule-based/deterministic, not model-generated (there is no model). Confidence is assigned by fixed code paths, not computed from any statistical or learned function.

**Distribution across this real run:** `overall_confidence: MODERATE` (only because the one inference fired); all 5 reasoning-type statements (1 inference + 4 hypotheses) are `MODERATE`; all 23 computed facts have `confidence: None` (schema-mandated — confidence applies only to reasoning statements, never to plain facts). `HIGH` and `LOW` are used zero times, in this run or in this implementation's code at all.

**Calibration-violation checks:**
- High confidence supported only by UNVERIFIED input: **not possible** — `HIGH` is never emitted by this analyst.
- High confidence dependent on an unresolved conflict: **not possible**, same reason; and separately, the one `MODERATE` inference does not depend on any specific conflict at all (it is a volume-based structural observation, unrelated to the 8 governed conflicts).
- High confidence on a single weak source where corroboration is required: not applicable — the one inference is deliberately multi-driver (any 1 of 4 possible drivers triggers it) and is capped at `MODERATE`, never escalated for multiple corroborating drivers.
- Low confidence despite multiple clean corroborating facts: not observed — no `LOW` is ever used, so this cannot occur either way.
- Confidence populated without rationale: not observed — every reasoning statement carries `assumptions`/`limitations` text alongside its confidence value, and the schema (`DecisionStatement.__post_init__`) mechanically requires this pairing.

**No confidence-framework redesign was performed or warranted** — the two fixed defects were count-accuracy bugs, not confidence-assignment bugs, and the confidence mechanism itself showed no violation on real data.

## S. Validation / anomalies summary

| Check | Result |
|---|---|
| Evidence used exceeds authoritative context | 0 — validator passed |
| Conflict silently resolved or omitted | 0 — all 8 present in `unresolved_conflict_ids` |
| Recommendation/decision emitted | 0 — validator forbids and none attempted |
| Input mutated during analysis | 0 — digest-compared before/after, unchanged |
| Statement-type/evidence-type capability violation | 0 — registry validation passed |
| Duplicate statement/conflict IDs | 0 |
| Determinism (built twice in-memory) | identical `analysis_id`, `computed_facts`, `inferences`, `hypotheses`, `unknowns` both times |
| Rejected-record re-entry | 0 |
| Unsupported external knowledge | 0 |
| Buyer-intent inference | 0 |
| Contract-term / procurement-model misrepresentation | 0 (neither is represented at all) |
| Defects found (count-accuracy only) | 2, both root-caused and fixed |

Existing regression suite: 21/21 passed (17 pre-existing + 4 new).

## T. Artifact index

- `evaluation/bank_of_canada_briefing_pack/opportunity_intelligence_commissioning/oppint-boc-2026-026-20260912T161717Z-50ab1a/` (authoritative, post-fix)
  - `run_metadata.json`, `determinism_check.json`, `opportunity_intelligence_full.json` (complete raw dump — all facts/inferences/hypotheses/unknowns)
- `evaluation/bank_of_canada_briefing_pack/opportunity_intelligence_commissioning/oppint-boc-2026-026-20260912T161309Z-339310/` (pre-fix diagnostic run, superseded — retained for the before/after comparison in Section H)
- Code changed: [opportunity_intelligence.py](../../opportunity_intelligence.py) (`total_conflicts` dedup, `unresolved_milestone_conflicts` field-name fix), [tests/test_opportunity_intelligence.py](../../tests/test_opportunity_intelligence.py) (+4 tests)
- Commissioning script: [scripts/commission_opportunity_intelligence_bank_of_canada.py](../../scripts/commission_opportunity_intelligence_bank_of_canada.py)

---

## Human-readable intelligence view — what Bid Intelligence has legitimately learned

**FACT** (23 computed, deterministic counts — see Section D for the complete verbatim list):
427 requirements (314 Mandatory, 89 Rated, 13 Submission Compliance, 9 Supporting, 1 Financial, 1 General Compliance) · 83 evaluation criteria (37 weighted, 46 without a weight — largely structural containers, hierarchy depth 2, 10 thresholds) · 68 submission artifacts across 4 pathways (58 mandatory, 2 with unresolved mandatory/channel/format ambiguity) · 23 deliverables · 91 verified commercial clauses across 20 clause kinds · 8 total governed conflicts, 1 of them term/deadline-related · 0 monetary observations · 0 requirements with bidder-evidence marked "ready" (no bidder-capability data exists in this system) · 9 named contract milestones with no confirmed date.

**INFERENCE** (1, `MODERATE` confidence, explicitly hedged):
*"The documented structure contains potential proposal-effort drivers: requirement volume, submission artifact volume, multiple submission pathways, evaluation hierarchy depth."*
— Assumption: structural volume is a relevant effort indicator. Limitation: no staffing or effort-rate model is available.

**HYPOTHESIS** (4, each `MODERATE`, unranked relative to each other):
Requirement volume · Submission artifact volume · Multiple submission pathways · Evaluation hierarchy depth — each independently offered as a *possible* (not confirmed, not ranked) explanation for the apparent effort signal above.

**IMPLICATION / DECISION SIGNAL:** none — this analyst's contract does not produce this category.

**UNCERTAINTY / GAP:**
- 8 unresolved governed conflicts (4 evaluation-weight discrepancies; title, client, file number, and contract term all unresolved) — none silently resolved.
- 33 canonical observations are provenance-ambiguous (partial, unverified, or unparsed) — explicitly flagged, not folded into any confident claim.
- 427 requirements have no confirmed bidder-evidence-readiness status (a bidder-capability gap, not a source-text gap).
- 1 open management question: *"Which documented uncertainties require management escalation before allocating internal effort?"*

Nothing above was authored as new prose for this report — every sentence is either a verbatim `statement` string from the real `DecisionAnalysis` object or a direct restatement of its structured fields.

---

## FINAL RESPONSE

- **UPSTREAM INPUT LOCK: PASS**
- **OPPORTUNITY INTELLIGENCE EXECUTION: PASS**
- **INTELLIGENCE PROVENANCE VALIDATION: PASS**
- **CONFLICT PRESERVATION: PASS**
- **CONFIDENCE CALIBRATION: PASS**
- **OPPORTUNITY INTELLIGENCE COMMISSIONING: PASS**
- **Run ID:** `oppint-boc-2026-026-20260912T161717Z-50ab1a`
- **Production function:** `opportunity_intelligence.analyze_opportunity()` → `OpportunityIntelligenceAnalyst.analyze()`
- **Actual dependencies consumed:** Stage C's `normalized_facts` (requirements/deliverables/commercial_clauses/evaluation_criteria/submission_rules/dates/_canonical_opportunity) + Stage C's 8 governed conflicts. Not Opportunity Structure, not Stage D, not raw evidence objects.
- **LLM used?** No — 100% deterministic, confirmed by full code inspection
- **Model/call count:** n/a
- **Token usage / API cost:** n/a / $0
- **Intelligence item count:** 28 conclusion-bearing items (23 facts + 1 inference + 4 hypotheses) + 3 uncertainty collections
- **Fact count:** 23
- **Inference count:** 1
- **Implication/decision-signal count:** 0 (not part of this analyst's contract)
- **Uncertainty/gap count:** 8 unresolved conflicts + 33 ambiguous observations + 427 bidder-evidence gaps + 9 undated milestones + 1 management question
- **Confidence distribution:** MODERATE ×5 (1 inference + 4 hypotheses), UNKNOWN available but unused this run, HIGH/LOW never used anywhere in this implementation
- **Items dependent on UNVERIFIED inputs:** 0 items singling out an UNVERIFIED record as decisive support; the one inference is volume-based, not content-specific
- **Items dependent on PARTIAL inputs:** same — volume-based aggregates only, no individually-cited PARTIAL record drives any conclusion alone
- **8 Stage C conflict outcomes:** all 8 category A (explicitly represented in `unresolved_conflict_ids`), 0 category D
- **4 Opportunity Structure conflict outcomes:** category C (outside this analyst's current vocabulary — role/role_conflict/is_structural_container fields are never read) — not silently resolved, simply not yet represented
- **Contract-term outcome:** not represented anywhere in this analyst's output — zero risk of scope-flattening or false resolution because nothing is asserted
- **Procurement-model outcome:** not represented anywhere — cannot contradict or corroborate Canonical Opportunity's `"Multi-vendor Call-off"`
- **Unsupported external-knowledge count:** 0
- **Rejected-record re-entry count:** 0
- **Provenance error count:** 0 (fabricated/dangling); real limitation: no independent VERIFIED/PARTIAL/UNVERIFIED tier for 4 of 5 record families (documented, not a violation)
- **Defects found/fixed:** 2 — `total_conflicts` double-counting (12→8), `unresolved_milestone_conflicts` dead-code keyword check (0→1)
- **Tests added:** 4
- **Full-suite result:** 1198 passed, 2 skipped
- **Runtime:** 0.136s
- **Report path:** [evaluation/bank_of_canada_briefing_pack/BANK_OF_CANADA_OPPORTUNITY_INTELLIGENCE_COMMISSIONING_REPORT.md](evaluation/bank_of_canada_briefing_pack/BANK_OF_CANADA_OPPORTUNITY_INTELLIGENCE_COMMISSIONING_REPORT.md)
- **Raw artifact paths:** `evaluation/bank_of_canada_briefing_pack/opportunity_intelligence_commissioning/oppint-boc-2026-026-20260912T161717Z-50ab1a/`

Per instruction, this commissioning stops here. **Buyer Brief and Executive Opportunity Brief have not been started.**
