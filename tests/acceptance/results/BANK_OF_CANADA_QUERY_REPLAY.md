# Bank of Canada Evidence Query Replay

## Corpus

The replay consumes the frozen corrected Bank of Canada Stage B normalized
facts and Stage C conflicts. It constructs the immutable graph through the
production `GraphBuilder.from_normalized_replay` path and queries it through
`EvidenceQueryEngine`.

## Deterministic graph

- Nodes: 2,138
- Edges: 1,837
- Artifacts: 16
- Occurrences: 700
- Extracts: 700
- Requirements: 413
- Evaluation criteria: 113
- Submission rules: 66
- Commercial clauses: 91
- Deliverables: 30
- Conflicts: 9
- Graph identity: `egraph-22849733282a9149901753dc97d3a62a45d18bcb6eb5ffc0aed445c54d155bcf`

## Query findings

Every query API executes deterministically against the frozen graph. Evidence
chains declared for requirements resolve through Artifact, Occurrence, and
Extract nodes. The frozen conflict records do not declare Requirement edges;
their trace validation therefore returns structured `MISSING_REQUIREMENT` and
upstream-chain failures rather than inventing relationships. No Bid Brief
Section nodes are present in this frozen graph, so section lookup returns the
structured `MISSING_NODE` result.

Query results include:

- Mandatory requirements: 310
- Financial requirements: 56
- Rated requirements: 80
- Supporting requirements: 9
- Requirements without extracts: 0
- Requirements without occurrences: 0
- Unused extracts: 303
- Unused occurrences: 303
- Source groups: 16
- Category groups: 5
- Snapshot validation: passed
- Provenance validation: passed

The replay performs no Stage C or Stage D integration and changes no existing
artifact.
