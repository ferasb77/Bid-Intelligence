# Document Metadata

| Field | Value |
|---|---|
| Document | `docs/engineering/TESTING_PHILOSOPHY.md` |
| Title | Testing Philosophy |
| Authority Level | Level 5 — Engineering Doctrine |
| Version | 1.0.0 |
| Status | Ratified |
| Purpose | Define why and what Bid Intelligence tests across authority, evidence, behavior, and change. |
| Higher Authority | Constitutional layer: [`MANIFESTO.md`](../../MANIFESTO.md), [`AGENT.md`](../../AGENT.md), [`GOVERNANCE.md`](../../GOVERNANCE.md), [`ANTI_GOALS.md`](../../ANTI_GOALS.md). All documents in [`docs/product/`](../product/PRODUCT_VISION.md) and [`docs/architecture/`](../architecture/ARCHITECTURE.md). |
| Governed Documents | Test strategies, validation plans, regression criteria, fixtures, and test evidence. |
| Related Documents | [`CONTRIBUTING.md`](CONTRIBUTING.md), [`REPOSITORY_STANDARDS.md`](REPOSITORY_STANDARDS.md), [`DECISION_DOCTRINE.md`](../architecture/DECISION_DOCTRINE.md) |

# Testing Philosophy

Testing protects the credibility of Decision Preparation. A defect that changes authority, loses evidence, hides uncertainty, or creates nondeterministic meaning can mislead an accountable professional even when the interface appears functional. Tests therefore protect product doctrine as well as software behavior.

## Testing objectives

Tests should establish that:

- authoritative inputs retain identity, provenance, and meaning;
- deterministic transformations are reproducible;
- invalid transitions fail explicitly and at the correct boundary;
- facts, reasoning, recommendations, and human decisions remain separate;
- unknowns and conflicts survive every relevant transformation;
- contracts accept supported inputs and reject unsupported ones;
- replay preserves the original semantic contract;
- optional components do not alter the base workflow when absent;
- regressions cannot reopen previously demonstrated integrity failures.

## Determinism is a product requirement

Deterministic behavior lets professionals trust that the same authoritative record will not acquire a different meaning because it was processed twice. It makes evidence review repeatable, conflict handling predictable, replay credible, and defects diagnosable.

Determinism applies wherever interpretation is unnecessary: identity, ordering, parsing rules, normalization, computation, reconciliation, validation, projection, and presentation. Tests should compare substantive outputs, ordering, and identifiers for identical inputs. Operational timestamps or execution metadata must not silently become semantic inputs.

## Fail-closed testing

Success-path tests show what the platform can process. Fail-closed tests show what it refuses to misrepresent. Both are required for authority-bearing behavior.

Boundary tests should supply malformed values, absent evidence, unknown identifiers, unsupported versions, incomplete precision, contradictory observations, and invalid references. They should prove that the affected result stops or remains unresolved without suppressing unrelated verified information.

## Canonical authority

Tests must demonstrate that canonical facts govern downstream behavior and that downstream analysis, projection, presentation, or replay cannot mutate them. Reconciliation tests should distinguish equivalence, conflict, and verified supersession. Rule order or observation count must never serve as accidental conflict resolution.

## Evidence integrity

Evidence integrity is tested independently of AI reasoning because the authority of evidence cannot depend on the quality of an interpretation. Tests should verify stable identity, occurrence preservation, provenance closure, valid references, exact locator behavior, and rejection of unsupported evidence.

An analyst may produce a plausible statement and still fail evidence validation. Conversely, authoritative evidence remains valid even when no inference can safely be made. Separate tests preserve that distinction.

## Contract validation

Contracts define what a layer may consume and emit. Tests should cover required fields, typed categories, version compatibility, unique identifiers, reference closure, immutability, prohibited output types, and unsupported extensions. A consumer must reject a version or capability it does not understand rather than guess.

## Replay validation

Replay proves more than deserialization. It demonstrates that retained records can traverse the current supported path without changing their original meaning or bypassing current safety boundaries.

Replay tests should include older valid records, historically plausible partial records, and checkpoints that bypass fresh normalization. Projection and presentation must be independently robust because replay may enter downstream of earlier safeguards.

## Regression protection

A regression test captures the smallest input that once violated an invariant and asserts the required behavior directly. It should fail under the defective behavior and remain meaningful if the implementation is rewritten.

Regression coverage is retained while the invariant remains governed. Tests should not be weakened merely because a new implementation passes by a different route.

## Architectural invariants

Architectural tests protect enduring boundaries such as:

- no alternate path bypasses authoritative normalization;
- analysts cannot mutate canonical facts or resolve conflicts;
- presentation layers perform no reasoning;
- evidence links close against declared authoritative entities;
- human decisions remain explicitly human;
- optional capabilities remain isolated from existing production paths.

These tests are often more valuable than tests that mirror a particular internal function.

## Behavioral invariants

Behavioral tests protect user-visible and domain-visible outcomes: every requirement is retained, a deadline is a valid full date, coverage reflects an actual response, alternatives remain visible, or a submission rule is applied exactly. They should be stated in domain language and include material boundary cases.

## AI-assisted behavior

AI reasoning is tested through its contract and allowed semantic space: evidence ownership, supported claims, prohibited decisions, explicit uncertainty, structured outputs, and deterministic post-validation. Tests do not need to assert a single preferred prose rendering when the contract permits variation.

Live model tests answer whether a provider contract works in the deployed environment. They are separate from deterministic repository tests, clearly identified, and never claimed unless actually run. Model success cannot compensate for broken evidence integrity.

## Test evidence

Report focused and full-suite results accurately, including failures, skips, subtests, environment limits, and whether external systems were exercised. A numeric total without the invariant it supports is weak evidence. The purpose of testing is confidence grounded in observable behavior, not a ceremonial green result.
