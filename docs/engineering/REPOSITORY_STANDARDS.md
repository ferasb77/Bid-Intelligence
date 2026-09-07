# Document Metadata

| Field | Value |
|---|---|
| Document | `docs/engineering/REPOSITORY_STANDARDS.md` |
| Title | Repository Engineering Standards |
| Authority Level | Level 5 — Engineering Doctrine |
| Version | 1.0.0 |
| Status | Ratified |
| Purpose | Define technology-independent standards for structure, contracts, compatibility, documentation, and review. |
| Higher Authority | Constitutional layer: [`MANIFESTO.md`](../../MANIFESTO.md), [`AGENT.md`](../../AGENT.md), [`GOVERNANCE.md`](../../GOVERNANCE.md), [`ANTI_GOALS.md`](../../ANTI_GOALS.md). All documents in [`docs/product/`](../product/PRODUCT_VISION.md) and [`docs/architecture/`](../architecture/ARCHITECTURE.md). |
| Governed Documents | Repository structure, engineering designs, component contracts, version policies, and code reviews. |
| Related Documents | [`CONTRIBUTING.md`](CONTRIBUTING.md), [`TESTING_PHILOSOPHY.md`](TESTING_PHILOSOPHY.md), [`FOUNDING_DECISIONS.md`](FOUNDING_DECISIONS.md) |

# Repository Engineering Standards

## Module boundaries

Modules and services are bounded by domain responsibility and information authority. Evidence acquisition, canonical reconciliation, intelligence analysis, compliance, organizational learning, presentation, persistence, and human decision records must not collapse into one implicit pipeline.

A dependency points toward an explicitly accepted contract. Reverse dependencies, circular authority, and convenience imports that allow a downstream layer to mutate an upstream layer are rejected.

## Immutable contracts

Authority-bearing inputs and outputs are immutable across component boundaries. A transformation creates a new value and retains references to its inputs. Contracts define required fields, allowed semantic types, validation, version, and failure behavior.

Immutability includes semantic immutability: a copied or serialized value must not acquire a different meaning merely because its representation changes.

## Stable identifiers

Evidence, canonical entities, analytical statements, conflicts, decisions, and other durable records use stable identities appropriate to their domain. Identifiers do not depend on display order, transient execution state, or mutable prose when avoidable.

Deduplication identifies equivalence; it does not discard meaningful occurrences. References fail closed when an identifier cannot be resolved.

## Layer isolation

Each layer enforces its own safety at its entry boundary. A downstream consumer does not assume every input passed through the newest upstream path, because replay, import, and future integration may enter elsewhere.

Presentation cannot reason. Analysis cannot rewrite evidence. Persistence cannot silently reinterpret a contract. Optional components cannot change existing behavior merely by being present.

## Optional components

Optional capabilities are additive, explicitly invoked, and behaviorally absent when not invoked. Their dependencies do not leak into the core path. They declare supported inputs and versions and reject incompatible material.

An optional component earns integration through a stable contract, not through hidden global state or automatic discovery that changes behavior unexpectedly.

## Traceability

Every meaningful derived result retains a path to its authoritative inputs. Provenance is structured, inspectable, and preserved through reconciliation, projection, analysis, presentation, replay, and export.

Diagnostic detail may live outside a compact view, but the authoritative record must remain complete. Free-text citation is not a substitute for typed identity and evidence closure.

## Minimal hidden state

Material behavior depends on explicit inputs, governed configuration, and declared versions. Time, environment, cache state, process history, and external services must not silently alter semantic output.

Where operational state is necessary, its role is visible and kept separate from domain identity.

## Backward compatibility

Compatibility protects meaning, not merely readability. Changes assess public contracts, stored records, replay, checkpoints, projections, integrations, and user workflows. A compatible reader preserves the semantics of supported historical records.

When meaning must change, use an explicit version, adapter, or migration governed by architecture review. Never reinterpret old data in place or rely on incidental field shape.

## Semantic versioning

Governed contracts and doctrine use semantic versions:

- **PATCH:** clarification or compatible correction without changed meaning;
- **MINOR:** additive compatible capability;
- **MAJOR:** incompatible meaning, authority, or boundary change.

Consumers declare what they support and reject unknown incompatible versions. Version numbers do not excuse a constitutional or architectural violation.

## Documentation requirements

Documentation states authority, purpose, scope, ownership, and relationships at the appropriate hierarchy level. Architecture documents explain durable boundaries; specifications define contracts; reports preserve evidence of implementation or validation.

Avoid copying higher-level doctrine into lower-level files. Cross-reference the authority instead. Update documentation in the same reviewed change when a governed contract or behavior changes.

## Cross-reference standards

References identify the exact governing document or contract and use consistent canonical terminology. Links are maintained as part of the change. A document must not claim authority through an ambiguous phrase such as “the architecture” when a precise source exists.

## Architectural review

Review is required when a change affects authority boundaries, domain meaning, public contracts, evidence flow, canonical rules, analyst capabilities, persistence semantics, replay, human decision ownership, or an anti-goal boundary.

The review states the proposed transition, alternatives considered, compatibility plan, failure behavior, and tests that will prove the invariant. Architecture review precedes implementation approval; it is not retrospective justification.

## Code review

Reviewers assess, in order:

1. constitutional and product fit;
2. architecture and domain authority;
3. correctness and failure behavior;
4. evidence, traceability, compatibility, and security;
5. tests and validation claims;
6. clarity and maintainability.

Tests passing does not close a finding in an earlier category. Review comments should name the violated invariant and the concrete trigger, not merely express preference.

## Definition of engineering quality

Engineering quality is the ability to change the system without weakening trust. A quality contribution is correctly bounded, evidence-preserving, deterministic where possible, fail-closed, compatible by design, understandable to reviewers, and useful in the customer workflow. It leaves future contributors a clearer contract than it found.
