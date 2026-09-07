# Opportunity Intelligence Analyst v1 — Implementation Report

## Scope

Opportunity Intelligence v1 is an optional post-pipeline analyst. It consumes an already-authoritative normalized snapshot and unresolved conflicts and returns a validated Phase 2 `DecisionAnalysis`. Existing Stage A–D, canonical, contract-hygiene, projection, replay, checkpoint, persistence, proposal, prompt, and public API paths do not import or invoke it.

The analyst answers what the documented opportunity looks like. It does not recommend bidding, estimate winning, assess bidder capability, choose pricing, resolve conflicts, or make a decision.

## Implemented computations

The analyst deterministically reports requirement totals and categories, mandatory and optional counts, evidence coverage, total conflicts, evaluation hierarchy depth, weighted and missing-weight criteria, thresholds, submission artifacts, pathways, mandatory artifacts, submission ambiguity, milestone intervals and completeness, clarification-to-submission interval, partial dates, milestone conflicts, verified clause counts, verified/legacy deliverable count, and monetary observation count.

Metrics are emitted individually as `COMPUTED_FACT` statements. There is no composite complexity, pursuit, or probability score. Facts carry no confidence.

## Reasoning boundaries

Version 1 uses deterministic, transparent structural rules to emit constrained `AI_INFERENCE` objects for documented proposal-effort drivers. It creates separate unranked hypotheses for each observed driver. It does not call an LLM, use a prompt, search the web, or query an external system.

Reasoning links only to declared typed entities. Confidence applies to inferences and hypotheses. Assumptions and limitations are explicit. Missing requirement evidence, unresolved conflicts, and ambiguous observations are represented through `AnalystUnknowns`.

Management questions are emitted only when unresolved conflict or submission ambiguity requires prioritization by management. They remain questions and contain no pursuit direction. `recommendations` is always empty.

## Validation rules

Input collections must contain mappings and canonical structures must have their expected container types. The analyst deep-copies input and verifies that the caller's authoritative snapshot was not mutated.

Phase 2 validates analyst identity, output capabilities, evidence categories, evidence closure, conclusion IDs, recommendation references, confidence placement, and typed collection membership. Opportunity-specific validation rejects recommendations and requires every supplied unresolved conflict ID to remain in `unknowns`.

Unknown or missing record IDs receive deterministic analyst-local IDs derived from the section, position, and canonical record representation. Existing requirement, deliverable, clause, criterion, observation, conflict, artifact, and milestone IDs are reused when present. Provenance content is never copied; only typed entity and existing evidence IDs are linked.

## Integration point

`analyze_opportunity(normalized_facts, conflicts, context_id=..., statements=...)` is the optional entry point. Callers invoke it after the authoritative pipeline has completed. When it is not invoked, current behavior is identical.

## Deterministic guarantees

For identical facts, conflicts, context ID, and analyst version, the analysis ID, computed facts, statement IDs, metric ordering, hypotheses, unknowns, and evidence ordering are identical. Execution timestamp is operational metadata and does not participate in the analysis identity.

The implementation sorts metric keys, categories, clause kinds, conflict IDs, evidence links, missing-evidence IDs, and ambiguous-observation IDs. Milestones are ordered by valid calendar date and semantic kind. Partial dates are retained as incomplete and never promoted into interval calculations. No timezone is invented for source dates.

## Known limitations

- Version 1 has no buyer, competitor, market, CRM, pricing, organizational-capability, staffing, or historical-award context.
- Reasoning is deliberately narrow and deterministic; no model-generated thematic analysis is implemented.
- Record types that predate stable IDs receive deterministic analyst-local references rather than changes to the owning pipeline.
- Evidence IDs are linked only when already supplied by an authoritative record. Entity links remain usable when the owning provenance store does not expose a separate evidence ID.
- Timeline computations use valid full dates only.
- No composite complexity or effort estimate is produced.
- Opportunity Intelligence results are not persisted in this phase.

## Performance observations

The analyst performs bounded in-memory passes over requirements, criteria, submission rules, dates, clauses, deliverables, observations, and conflicts. Sorting affects metrics, evidence links, milestones, and diagnostic IDs. Expected runtime is `O(n log n)` and memory is `O(n)` in the supplied authoritative entity count. It performs no network or filesystem I/O.

## Compatibility

No dependency, migration, schema, extraction rule, prompt, model, replay format, checkpoint format, database operation, proposal behavior, or public API changed. The analyst is additive and optional.

## Validation results

- Decision Intelligence, Decision Analyst, and Opportunity Intelligence focused suite: 60 passed.
- Full repository suite: 713 passed, 2 skipped, 19 subtests passed, 0 failures.
- No live AI or network call was used.
