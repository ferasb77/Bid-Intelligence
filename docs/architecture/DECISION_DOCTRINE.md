# Document Metadata

| Field | Value |
|---|---|
| Document | `docs/architecture/DECISION_DOCTRINE.md` |
| Title | Decision Information Doctrine |
| Authority Level | Level 4 — Architecture Doctrine |
| Version | 1.0.0 |
| Status | Ratified |
| Purpose | Govern how information changes from evidence of reality into accountable human decisions. |
| Higher Authority | [`MANIFESTO.md`](../../MANIFESTO.md), [`AGENT.md`](../../AGENT.md), [`GOVERNANCE.md`](../../GOVERNANCE.md), [`ANTI_GOALS.md`](../../ANTI_GOALS.md), [`PRODUCT_VISION.md`](../product/PRODUCT_VISION.md), [`PRODUCT_PRINCIPLES.md`](../product/PRODUCT_PRINCIPLES.md), [`CUSTOMER_WORKFLOW.md`](../product/CUSTOMER_WORKFLOW.md), [`CUSTOMER_PERSONAS.md`](../product/CUSTOMER_PERSONAS.md), [`COMPETITIVE_POSITIONING.md`](../product/COMPETITIVE_POSITIONING.md), [`PRODUCT_ROADMAP.md`](../product/PRODUCT_ROADMAP.md) |
| Governed Documents | Decision contracts, analyst specifications, validation rules, workspace designs, and decision records. |
| Related Documents | [`ARCHITECTURE.md`](ARCHITECTURE.md), [`DOMAIN_MODEL.md`](DOMAIN_MODEL.md), [`DESIGN_PRINCIPLES.md`](DESIGN_PRINCIPLES.md) |

# Decision Information Doctrine

Decision Preparation depends on preserving the authority of information as it evolves:

```text
Reality
  ↓ represented by
Evidence
  ↓ supports
Source Facts
  ↓ enable
Computed Facts and Observations
  ↓ may support
Inferences and Hypotheses
  ↓ expose
Management Questions
  ↓ inform
Human Deliberation
  ↓ produces
Human Decision
```

This is not a ladder of increasing truth. Each stage has a different purpose and authority. Later stages depend on earlier ones but do not replace them.

## Reality to Evidence

Reality is larger than the platform’s record. Evidence captures attributable representations of it. The transition is valid when the source, occurrence, and location remain identifiable and when extraction does not invent missing content.

Evidence may be incomplete, duplicated, ambiguous, superseded, or contradictory. Those conditions are retained because they are properties of what the platform knows.

## Evidence to Source Facts

A Source Fact states only what authoritative evidence supports. It may normalize form, but not add interpretation. Its provenance and stable identity remain available.

Multiple evidence occurrences may support the same fact. Reconciliation may identify equivalence or verified supersession, but disagreement remains explicit until the governing evidence rule resolves it.

## Source Facts to Computed Facts

A Computed Fact applies a declared, reproducible operation to identified facts. Counts, intervals, and item-level coverage are examples. The operation and its inputs must be inspectable.

Computation does not receive confidence. Given the same valid inputs and rule, it should produce the same result. If the inputs are insufficient, the result is unavailable or qualified; the system does not estimate silently.

## Facts to Observations

An Observation records a typed occurrence or measurable characteristic. It allows facts to be organized across a domain without claiming an explanation. Observations preserve evidence links and do not inherit causal meaning from proximity or frequency.

An observation can be useful even when no inference is justified.

## Facts and Observations to Inferences

An Inference interprets documented evidence. It must identify supporting evidence, reasoning status, confidence, assumptions, limitations, and gaps appropriate to the claim. Confidence belongs to the reasoning, never to the source fact.

An inference cannot modify its evidence, resolve a canonical conflict, infer buyer intent without support, or conceal a contradictory observation. It remains attributable to the analyst that produced it.

## Inferences to Hypotheses

A Hypothesis is an explicitly provisional explanation. Competing hypotheses remain available. Supporting evidence and contradicting evidence are both material; absence of contradiction does not prove the hypothesis.

The platform does not rank alternatives unless a separately governed capability is explicitly authorized to do so. Under the current Constitution, hidden ranking and winner prediction are excluded.

## Unknowns to Management Questions

Unknowns are carried alongside every transition. When an unknown requires organizational judgment rather than more deterministic processing, an analyst may express it as a Management Question.

A Management Question must remain unanswered by the system. Its wording may clarify the decision dependency but may not embed a recommended answer.

## Human Deliberation

Human Deliberation is the accountable consideration of facts, computations, interpretations, assumptions, alternatives, values, constraints, and consequences. The Decision Workspace may organize these materials but performs no additional reasoning or prioritization.

People may disagree, request more evidence, accept uncertainty, or defer action. The architecture must allow those states to be represented without manufacturing consensus.

## Human Decision

A Human Decision is made by an identified, authorized person. It records the choice and should retain its rationale, conditions, time, and relationship to the information considered.

A decision does not retroactively convert an inference into fact. Later Outcomes may test assumptions and support Organizational Learning, but they do not erase the original information state.

## Recommendations

A recommendation, where a governed analyst is permitted to produce one, is advice with evidence, scope, confidence, limitations, and alternatives. It has no executive authority. It must remain distinguishable from a Human Decision and cannot trigger commitment merely because it exists.

Some analysts and workspaces intentionally prohibit recommendations. A consumer must respect the producing contract rather than infer permission from the broader type system.

## Prohibited transitions

The following transitions may never occur silently:

- evidence becoming fact without source identity;
- a fact becoming opinion through paraphrase;
- an inference being stored or displayed as a fact;
- an unknown disappearing because a downstream view omits it;
- a conflict being resolved through rule order, narrative confidence, or convenience;
- a hypothesis becoming a prediction without new governed evidence and authority;
- a recommendation becoming an action or Human Decision;
- an AI output being attributed to a human decision-maker;
- a Human Decision being used as proof that its underlying assumptions were true;
- correlation being presented as causation;
- validation failure being repaired by inventing content.

## Continuity and learning

Decision records and Outcomes create evidence for later Organizational Intelligence. Learning compares what was known, what was inferred, what humans decided, and what occurred. It preserves temporal context so later knowledge does not rewrite earlier judgment unfairly.

The purpose of this continuity is better inquiry and institutional memory, not automated prediction. Human judgment remains sovereign at the end of every cycle.
