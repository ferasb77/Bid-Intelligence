# Decision Intelligence Framework — Phase 1

## Architecture philosophy

Decision Intelligence is an internal evidence and reasoning contract. AI may gather and organize evidence, compute patterns, expose reasoning, record assumptions, present alternative hypotheses, identify uncertainty, and recommend considerations. AI does not create an accountable human decision.

Phase 1 defines structures only. It contains no specialist business rules, procurement inference, prompt, model call, persistence, search, scoring, moderation, or UI behavior.

## Core principles

1. Every statement has one and only one declared category.
2. Source and computed facts do not carry confidence. Confidence describes reasoning, never evidence authority.
3. Evidence is linked by existing stable IDs; provenance is not copied into this layer.
4. AI inference preserves assumptions, alternatives, limitations, and explicit evidence gaps.
5. A recommendation is advisory output. A human decision is a separate accountable record.
6. Invalid state combinations fail deterministically at contract construction.
7. Future analysts share one output boundary without sharing business logic.
8. The framework does not alter existing pipeline objects or public responses.

## Object model

`DecisionStatement` is the central immutable object. It contains a stable statement ID, exactly one `StatementType`, statement text, typed source, reasoning status, optional reasoning confidence, evidence IDs, supporting fact IDs, entity links, assumptions, alternative hypotheses, limitations, recommendation scope, and structured reasoning gaps.

Supported statement categories are:

- `SOURCE_FACT`
- `COMPUTED_FACT`
- `AI_INFERENCE`
- `HYPOTHESIS`
- `RECOMMENDATION`
- `HUMAN_DECISION`
- `UNKNOWN`

`EvidenceSupport` points to an existing canonical fact, requirement, commercial clause, deliverable, observation, or future entity. It holds only IDs. Existing provenance remains authoritative in the owning subsystem.

`ReasoningGaps` can expose missing evidence, documents, history, known uncertainty, and validation limitations. `AlternativeHypothesis` gives each alternative its own stable ID and evidence links without generating any hypothesis.

`HumanDecisionRecord` records the decision, rationale, decision maker, timezone-aware timestamp, and accepted or rejected recommendation IDs. A recommendation cannot be both accepted and rejected.

## Confidence and state rules

`LOW`, `MODERATE`, `HIGH`, and `UNKNOWN` are available only to reasoning statements. Source facts, computed facts, and human decisions reject confidence values. AI inferences, hypotheses, and recommendations require both confidence and a substantive reasoning status. `UNKNOWN` cannot claim positive confidence and remains unresolved or not applicable.

Recommendation scope exists only on `RECOMMENDATION` statements and is required there. Source type must agree with statement type: authoritative source, deterministic computation, specialist analyst, or human.

## Extension points

`SpecialistAnalyst` is a protocol consuming `AnalystContext` and returning `AnalystOutput`. Future Buyer, Competition, Capability, Commercial, Pricing, Risk, and Proposal Strategy analysts may implement it. Phase 1 does not provide implementations or register named analysts.

`AnalystModerator` consumes `ModeratorInput` and returns `ModeratorOutput`. The output can represent agreement groups, disagreement groups, unresolved questions, and decision considerations. It performs no reasoning in Phase 1.

These protocols allow later orchestration without coupling the core contract to procurement or to a model provider.

## Relationship to the existing pipeline

The framework is additive and disconnected from production execution. Stage A extraction, Stage B normalization, Stage C conflict detection, Stage D synthesis and projection, Canonical Opportunity, Contract Hygiene, replay, checkpoints, provenance, XLS ingestion, proposal generation, persistence, and the public API remain unchanged.

Future adapters may reference existing requirement, observation, clause, deliverable, canonical, and evidence IDs. They must not duplicate or reinterpret the owning subsystem's provenance. Existing authoritative reapplication continues to define procurement output authority.

The workflow remains:

```text
UNDERSTAND → DECIDE → BUILD → CHECK → SUBMIT
```

## Future analyst architecture

Future analysts should:

1. receive an explicitly bounded context;
2. reference existing facts and evidence by stable ID;
3. emit only typed statements;
4. disclose assumptions and missing information;
5. preserve alternative explanations;
6. distinguish inference from recommendation;
7. leave decisions to `HumanDecisionRecord`;
8. pass outputs to a moderator contract without permitting the moderator to manufacture authority.

The moderator may organize consensus and disagreement, but unresolved questions remain unresolved. Decision considerations are not decisions.

## Compatibility

No existing module imports this framework. No database table, migration, serialized pipeline object, public API, prompt, model call, or UI route changes in Phase 1. Existing behavior remains the compatibility baseline.

## Phase boundary

AI assists reasoning. Humans make decisions.

Phase 1 establishes reusable internal contracts only. Buyer Intelligence, Bid/No-Bid reasoning, market search, procurement-specific inference, specialist implementations, moderation logic, persistence, and user-facing behavior remain outside this phase.
