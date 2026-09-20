# Decision Analyst Contract — Phase 2

## Relationship to Phase 1

Phase 1 defines the universal statement, evidence-link, reasoning-gap, human-decision, and moderator protocols. Phase 2 extends that foundation without changing it. It defines how a future specialist analyst declares its capability and returns a domain-neutral analysis.

No production module imports Phase 2. It changes no extraction, validation, synthesis, replay, checkpoint, persistence, proposal, schema, prompt, or public API behavior.

## Analyst philosophy

Analysts advise. Analysts never decide. They gather existing validated evidence links, express computed facts and reasoning through typed contracts, expose assumptions and unknowns, retain competing hypotheses, and issue advisory recommendations.

Analysts never mutate canonical facts. Analysts never bypass PhysValid or Contextual validation. Analysts operate only on validated evidence supplied through a bounded context.

## Analyst lifecycle

1. An analyst publishes immutable identity, semantic version, domain, supported statement types, and supported evidence entity types.
2. The deterministic registry accepts one analyst per stable ID and exposes metadata in ID order.
3. An orchestrator supplies a Phase 1 `AnalystContext` containing permitted entity IDs and statements.
4. The analyst returns one immutable `DecisionAnalysis`.
5. Contract validation checks evidence declaration, category separation, unique IDs, recommendation support, timestamp precision, and reasoning state.
6. A future moderator may consume several validated analyses through `DecisionAnalysisCollection`.

Phase 2 implements only steps 1, 2, and the data boundaries for steps 3–6. It contains no reasoning implementation or orchestration.

## Reasoning boundaries

`SUPPORTED`, `PARTIALLY_SUPPORTED`, `NOT_SUPPORTED`, and `UNKNOWN` describe analyst reasoning. They never qualify source facts.

Computed facts use Phase 1 `COMPUTED_FACT` statements and deterministic-computation sources. Inferences use `AI_INFERENCE` statements and specialist-analyst sources. Both must reference existing `EvidenceSupport` values declared by the containing analysis.

Hypotheses preserve supporting and contradicting evidence independently. Multiple hypotheses remain in supplied order. There is no rank, score, preferred hypothesis, or winner.

Unknowns separately expose missing evidence, unavailable datasets, unavailable history, unresolved conflicts, and ambiguous observations. Limitations and assumptions remain explicit objects rather than hidden prose conventions.

## Recommendation boundaries

An `AnalystRecommendation` contains a stable ID, type, rationale, supporting analysis IDs, confidence, and support status. Supporting IDs must resolve to a computed fact, inference, or hypothesis in the same analysis.

Recommendations contain no decision field, decision maker, approval, or execution authority. Accountable decisions remain exclusively represented by the Phase 1 `HumanDecisionRecord`.

## Registry

`DecisionAnalystRegistry` is a small in-process registry. It performs no module discovery, plugin loading, dependency injection, networking, model calls, or persistence.

Discovery is deterministically ordered by `analyst_id`. Duplicate IDs fail. Versions use `MAJOR.MINOR.PATCH`; compatibility requires the same major version and an available version greater than or equal to the required version.

Capability metadata prevents future orchestration from assuming that an analyst supports a statement or evidence category it did not declare. Analysts are forbidden from declaring support for `SOURCE_FACT` or `HUMAN_DECISION` output.

## Relationship to a future Moderator

`DecisionAnalysisCollection` groups complete analyst outputs without synthesizing them. `AgreementGroup`, `DisagreementGroup`, `OpenQuestionGroup`, and `ManagementConsiderationGroup` contain validated references to existing analyses and conclusions.

These objects allow a future moderator to expose consensus, disagreement, open questions, and management considerations. Phase 2 does not compare analyses, generate groups, resolve disagreement, select hypotheses, or make a decision.

## Extension guidelines

Future Buyer, Opportunity, Competition, Capability, Commercial, Compliance, Pricing, Risk, and Proposal Strategy analysts should:

1. implement the `DecisionAnalyst` protocol;
2. keep a stable analyst ID and semantic version;
3. declare only capabilities they actually emit;
4. consume only authorized, validated evidence;
5. reuse canonical, observation, clause, requirement, deliverable, and evidence IDs;
6. never copy source provenance into analyst objects;
7. emit computed facts and inferences under their correct Phase 1 categories;
8. expose assumptions, limitations, unknowns, and competing hypotheses;
9. link every recommendation to analysis in the same output;
10. leave all accountable decisions to humans.

This phase provides the reusable architectural contract only. It does not implement Buyer Intelligence, Opportunity Intelligence, Competition Intelligence, Bid/No-Bid, search, prompts, model calls, or procurement-specific reasoning.
