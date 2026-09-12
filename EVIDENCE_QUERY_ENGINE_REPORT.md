# Evidence Query Engine Report

## Scope

The Evidence Query Engine is an additive, internal, read-only service over an
immutable `EvidenceGraph`. It does not change extraction, normalization,
reconciliation, synthesis, presentation, persistence, or existing outputs.

## Implementation

`evidence_query.py` provides immutable `QueryResult`, `EvidenceTrace`, and
`EvidenceImpact` results. `GraphTraversal` constructs read-only node, type, and
adjacency indexes once per engine. `EvidenceQueryEngine` exposes deterministic
trace, dependency, category, gap, unused-evidence, grouping, impact, and graph
statistics queries.

Expected validation failures are values rather than exceptions. Missing nodes,
type mismatches, incomplete Artifact-to-Requirement chains, snapshot mismatch,
and broken provenance are returned as typed `ValidationFailure` records.

## Authority boundary

The engine follows only graph-declared edges. It never creates relationships,
repairs incomplete chains, changes confidence, or moves ownership. A conflict
without a declared Requirement edge remains an incomplete trace.

## Validation

Coverage includes deterministic traversal, complete and incomplete traces,
empty and large graphs, immutable indexes, duplicate rejection, statistics,
categories, unused evidence, and the frozen Bank of Canada replay.

- Query tests: 7 passed
- Affected Evidence, graph, adapter, and query tests: 42 passed
- Full repository suite: 1,008 passed, 2 skipped, 19 subtests passed
- Python compilation: passed
- `git diff --check`: passed
