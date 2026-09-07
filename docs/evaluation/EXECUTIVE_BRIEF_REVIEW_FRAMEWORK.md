# Document Metadata

| Field | Value |
|---|---|
| Document | `docs/evaluation/EXECUTIVE_BRIEF_REVIEW_FRAMEWORK.md` |
| Title | Executive Opportunity Brief Review Framework |
| Authority Level | Level 5 — Evaluation Guidance |
| Version | 1.0.0 |
| Status | Active |
| Purpose | Define a repeatable human evaluation of the Executive Opportunity Brief’s usefulness. |
| Higher Authority | [`MANIFESTO.md`](../../MANIFESTO.md), [Product Doctrine](../product/PRODUCT_VISION.md), [Architecture Doctrine](../architecture/ARCHITECTURE.md), [Engineering Doctrine](../engineering/CONTRIBUTING.md) |
| Governed Documents | Executive Opportunity Brief review sessions, scorecards, revision comparisons, and readiness assessments. |
| Related Documents | [`INDIVIDUAL_REVIEW_SCORECARD.md`](templates/INDIVIDUAL_REVIEW_SCORECARD.md), [`CONSOLIDATED_REVIEW_SUMMARY.md`](templates/CONSOLIDATED_REVIEW_SUMMARY.md), [`REVISION_COMPARISON.md`](templates/REVISION_COMPARISON.md) |

# Executive Opportunity Brief Review Framework

## Purpose

This framework evaluates whether an Executive Opportunity Brief helps a real proposal team understand an opportunity and prepare for kickoff. It evaluates the usefulness of the customer deliverable, not its implementation, model, pipeline, or technical architecture.

Reviewers judge the brief against the authoritative procurement package and their actual working needs. They do not judge whether the opportunity should be pursued or whether a proposal is likely to win.

## Review principles

- Human reviewers own all scores, comments, priorities, and acceptance decisions.
- Each evaluation dimension remains visible; no composite score is calculated.
- Evidence traceability and substantive usefulness are assessed separately.
- Disagreement is retained by role and reviewer; consolidation does not manufacture consensus.
- Unknowns and clarification candidates are evaluated for visibility and fidelity, never for whether they support a preferred decision.
- Feedback describes the brief and its use. It must not become procurement advice.
- Revision comparisons use the same opportunity, source package, reviewer task, and criteria wherever practicable.

## Reviewer roles

| Role | Primary review lens |
|---|---|
| CEO / Managing Partner | Executive orientation, readability, decision-preparation value, and internal distributability. |
| Bid Manager | Opportunity completeness, milestones, unknowns, traceability, and kickoff readiness. |
| Proposal Manager | Response-planning usefulness, structure, information needs, and avoidable source searching. |
| Subject Matter Expert | Accuracy of scope, specialist context, evidence access, and clarity of requested contribution. |
| Commercial Lead | Visibility of commercial facts, assumptions, missing information, and matters requiring human review. |

One person may represent more than one role in a boutique firm, but each scorecard records the lens used. A production-readiness cycle should include every role or document why a role was unavailable.

## Evaluation workflow

1. **Select the evaluation case.** Use a real, completed procurement package with a stable authoritative version. Record the opportunity identifier, brief revision, source-package identity, and review date.
2. **Establish the baseline.** Ask reviewers how they would normally understand the opportunity. Record baseline time and materials used before they see the evaluated brief when a clean comparison is possible.
3. **Run an independent review.** Each reviewer reads the brief without group discussion, records time to adequate understanding, completes the [individual scorecard](templates/INDIVIDUAL_REVIEW_SCORECARD.md), and identifies any source material they still had to search.
4. **Verify against evidence.** Reviewers inspect a representative set of traceable claims and any claim they distrust. They record whether the trail reaches the relevant source and whether the brief preserves uncertainty.
5. **Hold the proposal-team discussion.** Use the brief’s management questions, team-information needs, clarification candidates, and known unknowns in a kickoff-style conversation. Record questions the team added, removed, or could not act on.
6. **Consolidate without averaging away dissent.** Transfer results into the [consolidated summary](templates/CONSOLIDATED_REVIEW_SUMMARY.md). Show the distribution for each dimension, role-specific findings, blockers, and minority views. Do not calculate an overall score.
7. **Identify improvement opportunities.** Human reviewers assign priority based on observed customer impact, frequency across reviewers or opportunities, and evidence. Priority applies to improving the brief, never to the procurement opportunity.
8. **Compare revisions.** When a new brief revision exists, use the [revision comparison](templates/REVISION_COMPARISON.md) with the same case and tasks. Record improvements, regressions, unchanged findings, and newly introduced uncertainty.
9. **Make the readiness decision.** An accountable product owner applies the acceptance criteria below and records `READY`, `READY WITH RECORDED LIMITATIONS`, or `NOT READY` with rationale.

## Evaluation dimensions

Use a five-point anchored scale for each dimension. `1` means the brief materially fails the dimension; `3` means usable with significant follow-up; `5` means ready for routine internal use. Reviewers must add evidence for scores of `1`, `2`, or `5`.

| Dimension | What is evaluated | 1 — Material failure | 3 — Usable with follow-up | 5 — Routine internal use |
|---|---|---|---|---|
| Time to understanding | Time required to form an accurate working view | Slower or no clearer than source review | Provides orientation but needs substantial source reading | Rapidly establishes an accurate working view |
| Executive readability | Clarity for a time-constrained leader | Cannot be understood without reconstruction | Main points are understandable with effort | Clear, navigable, and distributable as written |
| Reduction in cognitive effort | Reduction in finding, comparing, and organizing | Adds work or confusion | Reduces some work but leaves major reconstruction | Removes substantial avoidable effort |
| Opportunity understanding | Understanding of purpose, scope, structure, milestones, and obligations | Materially incomplete or misleading | Core opportunity is visible with notable gaps | Produces a coherent, accurate understanding |
| Kickoff preparation | Readiness for a productive proposal-team kickoff | Does not support role assignment or discussion | Supports a basic kickoff with added preparation | Provides a strong common starting point |
| Trustworthiness | Fidelity, restraint, and visible uncertainty | Contains unsupported certainty or material error | Generally reliable with items requiring verification | Consistently distinguishes known, inferred, and unknown |
| Evidence traceability | Ability to inspect source support | Material claims cannot be traced | Important claims are traceable with friction | Material claims lead clearly to relevant evidence |
| Identification of unknowns | Visibility of gaps, ambiguity, and conflict | Hides or resolves uncertainty | Identifies major unknowns but misses useful detail | Makes material uncertainty explicit and usable |
| Management questions | Quality of unanswered questions for human discussion | Prescriptive, irrelevant, or misleading | Some useful questions mixed with generic ones | Specific questions improve accountable discussion |
| Overall usefulness | Value as the first internally circulated document | Would not use | Would use after material editing | Would distribute without significant editing |

Record dimension scores individually. Means, weighted totals, traffic-light summaries, and hidden rankings are prohibited.

## Required qualitative prompts

Every reviewer answers:

- What surprised you?
- What would you remove?
- What information did you still have to search for?
- What section created the greatest value?
- What would prevent you from distributing this document internally?
- What decision did this document help you make?
- Which statement did you trust least, and why?
- Which unknown or ambiguity was missing?
- Which management question improved the discussion?
- What did your role need that the brief did not provide?

The “decision” prompt records human use of the document. The framework does not evaluate whether that decision was correct.

## Improvement priority

Consolidators assign one of three human-owned priorities:

- **P0 — Blocks distribution:** A material accuracy, trust, authority, or usability problem prevents responsible internal circulation.
- **P1 — Material improvement:** The issue repeatedly increases effort or weakens understanding but does not make the brief unsafe to distribute.
- **P2 — Refinement:** The change improves clarity or convenience without addressing a material failure.

Every priority requires reviewer evidence, affected roles, affected dimensions, and an acceptance statement. Frequency informs judgment but does not automatically determine priority.

## Production-readiness acceptance criteria

A brief revision is ready for production use only when all criteria are met:

1. At least one real procurement opportunity has been reviewed by all five role lenses; broader readiness should include multiple opportunities of materially different structure.
2. No P0 issue remains open.
3. No reviewer reports a material factual misrepresentation, invented fact, hidden conflict, answered unknown, procurement recommendation, Bid / No Bid advice, win prediction, or executive conclusion.
4. Every material claim sampled for traceability reaches relevant authoritative evidence.
5. Trustworthiness, evidence traceability, identification of unknowns, and overall usefulness receive no score below `3`.
6. At least four of the five role lenses answer “Yes” to internal distribution, and the Bid Manager must be among them.
7. The kickoff exercise demonstrates that the team can identify immediate information needs, unresolved questions, and clarification candidates without reconstructing the RFP from scratch.
8. Revision comparison shows no unresolved regression in evidence integrity, unknown preservation, role usefulness, or deterministic structure.
9. Dissent, limitations, excluded roles, and unresolved P1/P2 items are recorded in the consolidated summary.
10. A named human product owner records the readiness state and rationale. No score or automated rule makes the decision.

`READY WITH RECORDED LIMITATIONS` may be used only when every safety and trust criterion passes and the remaining limitations are explicit, bounded, and accepted by the product owner. It cannot waive a P0 issue.

## Boundaries

This package creates no new intelligence and evaluates no procurement outcome. It does not score implementation, rank opportunities, recommend product changes automatically, recommend pursuit action, or determine whether a team should bid. Its outputs are human review evidence used to improve one customer deliverable.
