# Evidence Explainability Report

## Scope

The Explainability Engine is an additive, internal formatter over the immutable
Evidence Graph and Evidence Query Engine. It performs no reasoning, inference,
repair, graph mutation, or pipeline integration.

## Contract

Each explanation contains an exact subject summary, declared evidence-path
edges, supporting artifact, occurrence, extract and requirement identities,
the weakest declared edge confidence, citations, and structured validation.
Incomplete paths return `EXPLANATION_INCOMPLETE` with typed reasons.

## Validation

Tests cover complete and incomplete traces, every supported explanation type,
determinism, immutability, duplicate citations, cycles, confidence propagation,
snapshot mismatch, and the frozen Bank of Canada graph replay.

- Explainability tests: 7 passed
- Affected Evidence, graph, query, and explainability tests: 49 passed
- Full repository suite: 1,015 passed, 2 skipped, 19 subtests passed
- Python compilation: passed
- `git diff --check`: passed
