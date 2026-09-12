# Bank of Canada Explainability Replay

## Scope

This acceptance replay builds the frozen corrected Bank of Canada Evidence
Graph and explains it through the production Evidence Query and Explainability
engines. It does not invoke or modify Stage A through Stage D.

## Result

Requirements, commercial clauses, submission requirements, deliverables,
evaluation criteria, extracts, artifacts, the Evidence snapshot, and graph
statistics produce deterministic explanations backed by immutable graph
references.

The frozen graph contains no Bid Brief Section nodes and does not declare
Requirement-to-Conflict edges. Those explanations correctly return
`EXPLANATION_INCOMPLETE` with structured missing-node or missing-chain reasons.
The engine does not invent either relationship.

Complete replay results:

- Requirements: 413 complete
- Evaluation criteria: 113 complete
- Submission requirements: 66 complete
- Commercial clauses: 91 complete
- Deliverables: 28 complete, 2 incomplete because their evidence chains are absent
- Artifacts: 16 complete
- Extracts: 700 complete
- Conflicts: 9 incomplete because no Requirement relationship is declared
- Evidence snapshot: complete
- Graph statistics: complete
- Bid Brief dependency: incomplete because no Bid Brief Section node is published
