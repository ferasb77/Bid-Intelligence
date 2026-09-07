# Document Metadata

| Field | Value |
|---|---|
| Document | `docs/architecture/DESIGN_PRINCIPLES.md` |
| Title | Permanent Architecture and Engineering Principles |
| Authority Level | Level 4 — Architecture Doctrine |
| Version | 1.0.0 |
| Status | Ratified |
| Purpose | Translate product doctrine into enduring design constraints for software and information systems. |
| Higher Authority | [`MANIFESTO.md`](../../MANIFESTO.md), [`AGENT.md`](../../AGENT.md), [`GOVERNANCE.md`](../../GOVERNANCE.md), [`ANTI_GOALS.md`](../../ANTI_GOALS.md), [`PRODUCT_VISION.md`](../product/PRODUCT_VISION.md), [`PRODUCT_PRINCIPLES.md`](../product/PRODUCT_PRINCIPLES.md), [`CUSTOMER_WORKFLOW.md`](../product/CUSTOMER_WORKFLOW.md), [`CUSTOMER_PERSONAS.md`](../product/CUSTOMER_PERSONAS.md), [`COMPETITIVE_POSITIONING.md`](../product/COMPETITIVE_POSITIONING.md), [`PRODUCT_ROADMAP.md`](../product/PRODUCT_ROADMAP.md) |
| Governed Documents | System designs, component boundaries, contracts, validation, implementation plans, and engineering reviews. |
| Related Documents | [`ARCHITECTURE.md`](ARCHITECTURE.md), [`DOMAIN_MODEL.md`](DOMAIN_MODEL.md), [`DECISION_DOCTRINE.md`](DECISION_DOCTRINE.md) |

# Architecture and Engineering Principles

## 1. Evidence before inference

- **Purpose:** Keep analytical claims grounded in inspectable material.
- **Rationale:** Reasoning without evidence cannot support accountable professional judgment.
- **Architectural implications:** Evidence has stable identity and provenance; inferences link to existing evidence; copied prose is not a substitute for a reference.
- **Example:** A statement about a commercial obligation links to the issued clause; an unsupported legal consequence is rejected.

## 2. Deterministic where possible

- **Purpose:** Make reproducible operations predictable and testable.
- **Rationale:** Counts, normalization, reconciliation, ordering, and validation do not benefit from interpretive variability.
- **Architectural implications:** The same authoritative inputs and rules produce the same substantive output; nondeterministic mechanisms are confined to explicitly analytical work.
- **Example:** Requirement counts and date intervals are computed, not estimated by an analyst.

## 3. Fail closed

- **Purpose:** Prevent invalid or unsupported information from acquiring authority.
- **Rationale:** A visible gap is safer than a plausible fabrication.
- **Architectural implications:** Missing identity, provenance, compatibility, or validation stops the affected transition; errors are explicit; unrelated valid material remains available.
- **Example:** A malformed date remains unparsed rather than becoming an invented calendar value.

## 4. Canonical authority

- **Purpose:** Give downstream capabilities one governed account of supported facts.
- **Rationale:** Competing local interpretations create contradiction and drift.
- **Architectural implications:** Canonical facts are reconciled through explicit rules; consumers do not overwrite them; new evidence changes them through a traceable transition.
- **Example:** An analyst reads a canonical deadline but cannot replace it with a preferred date.

## 5. Immutability across authority boundaries

- **Purpose:** Prevent derived work from changing its own evidence.
- **Rationale:** Analysis loses meaning if inputs can be rewritten during interpretation or presentation.
- **Architectural implications:** Inputs cross boundaries by stable reference or immutable value; transformations produce new records; mutation checks protect authoritative state.
- **Example:** Building a Decision Workspace cannot alter any supplied analysis.

## 6. Facts and reasoning remain separate

- **Purpose:** Preserve the epistemic status of every statement.
- **Rationale:** Fluent language can make interpretation appear authoritative unless the distinction is structural.
- **Architectural implications:** Source Facts, Computed Facts, Observations, Inferences, Hypotheses, Recommendations, and Human Decisions use distinct contracts and validation.
- **Example:** A liability amount is a fact; its organizational implication is separately attributed reasoning.

## 7. Transparency is a contract

- **Purpose:** Make important outputs understandable and contestable.
- **Rationale:** Professionals cannot responsibly use a conclusion they cannot inspect.
- **Architectural implications:** Reasoning exposes evidence, assumptions, limitations, confidence, alternatives, and unknowns; hidden composite logic is prohibited.
- **Example:** Structural effort drivers are shown individually rather than concealed in a complexity score.

## 8. Traceability survives transformation

- **Purpose:** Preserve the path from a derived result back to every material source occurrence.
- **Rationale:** Verification, replay, amendment handling, and learning depend on provenance continuity.
- **Architectural implications:** Stable identifiers persist; deduplication preserves occurrences; compact projections retain lossless sidecars where detail is not displayed.
- **Example:** A normalized requirement can be traced to each source reference that supports it.

## 9. Unknowns are first-class

- **Purpose:** Represent the limits of knowledge explicitly.
- **Rationale:** Suppressed uncertainty becomes false confidence downstream.
- **Architectural implications:** Missing evidence, unavailable information, ambiguity, and unresolved conflicts have durable representations and survive presentation.
- **Example:** A partial date remains visible but cannot independently resolve a headline deadline.

## 10. Human judgment remains the terminal authority

- **Purpose:** Keep accountability with experienced professionals.
- **Rationale:** Pursuit, commercial, strategic, and release decisions depend on context and responsibility that information systems do not own.
- **Architectural implications:** Systems may raise questions and present considerations; action requires an explicit human decision and authority.
- **Example:** An executive reviews a prepared workspace and records Bid / No Bid rather than receiving an automated verdict.

## 11. Minimal hidden state

- **Purpose:** Make behavior explainable, replayable, and safe to evolve.
- **Rationale:** Unrecorded context causes identical inputs to produce unaccountable differences.
- **Architectural implications:** Material inputs, versions, assumptions, and transitions are explicit; caches and operational metadata cannot become silent sources of truth.
- **Example:** A replay identifies the evidence and contract version it uses.

## 12. Composability through bounded contracts

- **Purpose:** Allow capabilities to evolve without eroding neighboring authority.
- **Rationale:** Strong boundaries make reuse safer than shared implicit behavior.
- **Architectural implications:** Components declare accepted inputs, produced outputs, versions, and failure rules; optional capabilities do not alter the base workflow when absent.
- **Example:** A new analyst can join a workspace while its findings remain isolated from other analysts.

## 13. Separation of concerns follows decision authority

- **Purpose:** Divide the system according to who may establish, interpret, present, or decide information.
- **Rationale:** Technical convenience is a poor boundary when it mixes incompatible authority.
- **Architectural implications:** Extraction, canonical reconciliation, domain intelligence, compliance, organizational learning, presentation, and human decision records remain distinct responsibilities.
- **Example:** A presentation layer arranges validated hypotheses but never synthesizes a preferred interpretation.

## 14. Compatibility is explicit

- **Purpose:** Protect authoritative meaning as contracts evolve.
- **Rationale:** Silent reinterpretation can corrupt replay and historical learning even when data remains readable.
- **Architectural implications:** Versions declare meaning; consumers reject unsupported versions; migrations and adapters are deliberate; old records retain their original semantics.
- **Example:** A workspace refuses an analyst version it does not understand instead of guessing how to render it.

## 15. Preserve the smallest trustworthy claim

- **Purpose:** Retain useful verified information without widening its meaning.
- **Rationale:** All-or-nothing handling either loses evidence or promotes unsafe conclusions.
- **Architectural implications:** Validation is scoped to the affected entity or field; partial precision is retained as partial; unrelated conflicts do not cause global suppression.
- **Example:** A conflict in submission dates does not suppress a verified clarification date.

These principles apply together. Designs must be reviewed against the information transitions in [`DECISION_DOCTRINE.md`](DECISION_DOCTRINE.md) and the layer boundaries in [`ARCHITECTURE.md`](ARCHITECTURE.md), not selected principle by principle to justify a preferred implementation.
