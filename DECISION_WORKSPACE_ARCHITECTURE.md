# Decision Workspace Architecture

## Purpose

Decision Workspace is an immutable presentation model for validated `DecisionAnalysis` outputs. It arranges the source analyses into stable sections that let a human reviewer inspect evidence, computed facts, findings, assumptions, unknowns, alternative interpretations, considerations, questions, and limitations. It performs no extraction, computation, synthesis, scoring, ranking, recommendation, or decision-making.

## Relationship to analysts

Analysts own every fact and reasoning object shown in the workspace. The workspace preserves each object's original typed representation and groups it by `analyst_id` and `analysis_id`. It never merges conclusions between analysts. Computed facts are displayed exactly as supplied, and all hypotheses remain visible.

The builder receives a metadata catalog alongside analyses. The current default catalog contains Opportunity Intelligence v1. Additional analysts are enabled by supplying their existing `DecisionAnalystMetadata`; no workspace contract change is required. An analyst is accepted only when its identifier is registered and its exact metadata version appears in the supported-version map.

## Relationship to human judgment

The workspace exposes management questions without answering them. Findings may also appear in the considerations view as the same unchanged `AnalystReasoning` objects, allowing deliberation without creating a new conclusion. The workspace has no recommendation, score, rank, or decision field.

## Deterministic behavior

Analyses are ordered by analyst ID and analysis ID. Evidence is deduplicated and ordered by typed entity category, entity ID, and evidence IDs. Evidence categories and unknown groups use stable lexical ordering. Content inside each analysis remains in analyst-produced order so that the workspace does not reinterpret it.

The workspace identity is derived from the workspace version and the ordered analyst/version/analysis identities. Operational timestamps are absent. The JSON renderer serializes the immutable model with sorted keys and compact deterministic separators, so identical input produces identical output.

## Validation

Construction fails closed for non-`DecisionAnalysis` inputs, duplicate analysis IDs, missing evidence links, unknown analysts, unsupported analyst versions, and analyses containing recommendations. Existing Phase 2 objects enforce typed conclusions, evidence closure, confidence placement, unique conclusion IDs, and valid question references before workspace construction.

## Extension strategy

New analysts register through metadata supplied to `build_decision_workspace`. Each analysis receives its own entry in every view, including empty entries, which keeps analyst boundaries explicit and makes absence distinguishable from omission. New presentation views should expose existing typed content directly and must not derive a score, preference, priority, merged conclusion, or decision.

## Doctrine compliance

The workspace preserves authority and reasoning boundaries. It does not alter canonical facts, resolve conflicts, suppress uncertainty, select hypotheses, or convert analyst findings into source facts. Evidence coverage is a count and organization of declared references, not an assessment of evidence quality. Human reviewers retain responsibility for judgment and action.
