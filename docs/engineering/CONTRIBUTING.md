# Document Metadata

| Field | Value |
|---|---|
| Document | `docs/engineering/CONTRIBUTING.md` |
| Title | Contribution Doctrine |
| Authority Level | Level 5 — Engineering Doctrine |
| Version | 1.0.0 |
| Status | Ratified |
| Purpose | Define the conditions under which a contribution may change Bid Intelligence. |
| Higher Authority | Constitutional layer: [`MANIFESTO.md`](../../MANIFESTO.md), [`AGENT.md`](../../AGENT.md), [`GOVERNANCE.md`](../../GOVERNANCE.md), [`ANTI_GOALS.md`](../../ANTI_GOALS.md). All documents in [`docs/product/`](../product/PRODUCT_VISION.md) and [`docs/architecture/`](../architecture/ARCHITECTURE.md). |
| Governed Documents | Contribution plans, pull requests, implementation reviews, and contributor conduct. |
| Related Documents | [`TESTING_PHILOSOPHY.md`](TESTING_PHILOSOPHY.md), [`REPOSITORY_STANDARDS.md`](REPOSITORY_STANDARDS.md), [`FOUNDING_DECISIONS.md`](FOUNDING_DECISIONS.md) |

# Contribution Doctrine

Contributing to Bid Intelligence means preserving a system of authority, not merely adding behavior. A change is acceptable only when it strengthens the product, respects the customer workflow, preserves human judgment, and can be supported by evidence.

## Required reading order

Before proposing or reviewing a change, read:

1. [`MANIFESTO.md`](../../MANIFESTO.md);
2. [`GOVERNANCE.md`](../../GOVERNANCE.md), [`ANTI_GOALS.md`](../../ANTI_GOALS.md), and, for AI contributors, [`AGENT.md`](../../AGENT.md);
3. [`PRODUCT_VISION.md`](../product/PRODUCT_VISION.md), [`PRODUCT_PRINCIPLES.md`](../product/PRODUCT_PRINCIPLES.md), and the relevant workflow and persona doctrine;
4. [`ARCHITECTURE.md`](../architecture/ARCHITECTURE.md), [`DOMAIN_MODEL.md`](../architecture/DOMAIN_MODEL.md), [`DECISION_DOCTRINE.md`](../architecture/DECISION_DOCTRINE.md), and [`DESIGN_PRINCIPLES.md`](../architecture/DESIGN_PRINCIPLES.md);
5. this Engineering Doctrine and the contracts, specifications, and evidence governing the affected subsystem.

Reading order matters. Lower-level behavior cannot be used to reinterpret higher authority.

## Contribution philosophy

A contribution begins with a customer and architectural reason. It identifies the authoritative inputs, the transformation permitted, the output authority, the responsible human, and the failure behavior before implementation begins.

Contributors should prefer the smallest change that establishes the required invariant. Existing contracts and boundaries are reused unless a reviewed architectural reason justifies their evolution. Convenience, novelty, or generated volume is not product value.

## Compliance gates

### Constitutional compliance

The change must preserve the four pillars, sovereign human judgment, evidence before inference, and the Moneyball principle. It must not advance an anti-goal. A constitutional conflict stops ordinary implementation and follows the amendment process in [`GOVERNANCE.md`](../../GOVERNANCE.md).

### Product compliance

The change must name the customer workflow stage and operational persona it serves. It must reduce a real burden of understanding, comparison, coordination, verification, or learning. Product language and scope must remain consistent with the Level 3 doctrine.

### Architecture compliance

The change must preserve canonical authority, evidence provenance, facts-versus-reasoning boundaries, explicit unknowns, immutable authority transitions, layer isolation, and human decision ownership. Architecture changes require an architectural review before implementation is treated as complete.

## An acceptable pull request

Every pull request must answer explicitly:

1. **Which pillar is strengthened?**
2. **Which customer workflow stage is improved?**
3. **Which cognitive burden is reduced?**
4. **How is human judgment preserved?**
5. **What evidence supports the implementation?**
6. **Which constitutional principles are reinforced?**
7. **What tests were added or changed, and which invariants do they prove?**

It must also:

- state the concrete before-and-after behavior;
- identify affected authority and module boundaries;
- disclose contract, compatibility, replay, persistence, prompt, schema, and migration effects;
- preserve unresolved conflicts and known limitations;
- include focused validation and appropriate regression results;
- distinguish local test evidence from external or live validation;
- update governing documentation when a governed contract changes;
- avoid unrelated cleanup that obscures review;
- leave no accidental generated files, secrets, or hidden dependencies.

Passing tests are necessary evidence, not proof of architectural correctness. Reviewers must inspect the behavior and its authority boundaries.

## Human contributors

Human contributors own the product and architectural rationale for their changes. They must challenge convenient automation that weakens accountability, explain trade-offs, and ensure the change remains useful in the real workflow. Approval carries responsibility for doctrine compliance, not only code quality.

## AI contributors

AI contributors follow [`AGENT.md`](../../AGENT.md) in addition to this document. They must read the governing sources, state architectural impact before implementation, stay within authorized scope, verify claims with repository evidence, and disclose uncertainty. They must not infer permission to change higher-authority contracts from a broad implementation request.

An AI contribution is reviewed to the same standard as a human contribution. Generated speed does not lower the evidence, testing, or judgment threshold.

## Review and completion

Review begins with constitutional and product fit, then architecture, behavior, tests, evidence, and maintainability. A blocking defect remains blocking even when unrelated checks pass. A contribution is complete only when its intended behavior is reviewable, its validation is accurate, its compatibility is understood, and the repository is left in a coherent state.
