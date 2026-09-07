# Document Metadata

| Field | Value |
|---|---|
| Document | `AGENT.md` |
| Title | Instructions for AI Contributors |
| Authority Level | Level 2 — Repository Governance |
| Version | 1.0.0 |
| Status | Ratified |
| Purpose | Translate the Constitution into mandatory working rules for AI contributors. |
| Higher Authority | [`MANIFESTO.md`](MANIFESTO.md) |
| Governed Documents | AI-authored plans, code, tests, prompts, schemas, reports, reviews, and documentation. |
| Related Documents | [`GOVERNANCE.md`](GOVERNANCE.md), [`ANTI_GOALS.md`](ANTI_GOALS.md), [`README.md`](README.md) |

# Instructions for AI Contributors

Read [`MANIFESTO.md`](MANIFESTO.md) before proposing, reviewing, or implementing work. Then read [`ANTI_GOALS.md`](ANTI_GOALS.md) and the architecture governing the affected subsystem. Implementation serves the product philosophy, not the reverse.

## Before implementation

State which pillar the work strengthens and which human burden it reduces. Explain its architectural impact, including authority boundaries, evidence flow, public contracts, persistence, replay, and failure behavior where relevant.

Reject or reframe work that violates an anti-goal. Do not create a technical workaround for a product choice the repository has constitutionally excluded. When a request conflicts with the Constitution, identify the conflict plainly and follow [`GOVERNANCE.md`](GOVERNANCE.md).

## While contributing

- Preserve human judgment. Never introduce autonomous Bid / No Bid decisions, executive decisions, hidden rankings, or unexplained recommendations.
- Preserve evidence before inference. Keep authoritative facts, deterministic computations, AI reasoning, hypotheses, recommendations, and human decisions typed and separate.
- Do not invent evidence, suppress conflicts, conceal uncertainty, or turn correlation into causation.
- Maintain provenance and stable identifiers. Derived views must not silently mutate authoritative inputs.
- Prefer explicit failure to silent truncation, repair, coercion, or unsupported certainty.
- Keep changes within scope. Read current contracts before adding parallel abstractions.
- Protect compatibility deliberately. Treat schemas, migrations, checkpoints, replay formats, prompts, and public APIs as governed interfaces.
- Add tests that exercise the claimed invariant and failure paths. Passing tests do not excuse a doctrine violation.
- Use external AI or data only when the authority model permits it. Distinguish supplied evidence from external information.

## Before completion

Verify that the implementation answers its pillar question without answering a question reserved for management. Report architectural impact, validation, compatibility effects, and known limitations accurately. Never claim evidence, CI, live behavior, or external validation that did not occur.

## Architectural drift

Architectural drift includes changes that gradually weaken a constitutional boundary: treating inference as fact, adding implicit scores, bypassing canonical authority, omitting alternatives, allowing presentation layers to reason, or expanding proposal generation into the product’s competitive center.

When drift is detected, stop the affected implementation, name the governing principle, and return to the smallest design consistent with [`MANIFESTO.md`](MANIFESTO.md). Constitutional change requires an amendment; it must never arrive disguised as routine code.
