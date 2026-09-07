"""Opportunity Intelligence Analyst v1.

The analyst computes structural characteristics from an already-authoritative
procurement snapshot. It performs no extraction, model call, search, decision,
or pursuit recommendation.
"""
from __future__ import annotations

import copy
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json
import re
from typing import Mapping

from decision_intelligence import (
    AnalystContext, Confidence, ContractValidationError, DecisionStatement,
    EvidenceSupport, ReasoningStatus, SourceType, StatementSource,
    StatementType, SupportedEntityType,
)
from decision_analyst import (
    AnalystAssumption, AnalystHypothesis, AnalystReasoning, AnalystUnknowns,
    DecisionAnalysis, DecisionAnalystMetadata, DecisionAnalystRegistry,
    ManagementQuestion, SupportStatus,
)


ANALYST_ID = "opportunity-intelligence"
ANALYST_VERSION = "1.0.0"


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _id(prefix: str, value) -> str:
    return prefix + sha256(_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class OpportunityAnalysisContext:
    analyst_context: AnalystContext
    normalized_facts: Mapping
    conflicts: tuple[Mapping, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.analyst_context, AnalystContext):
            raise ContractValidationError("analyst_context must be AnalystContext")
        if not isinstance(self.normalized_facts, Mapping):
            raise ContractValidationError("normalized_facts must be a mapping")
        if any(not isinstance(item, Mapping) for item in self.conflicts):
            raise ContractValidationError("conflicts must contain mappings")


METADATA = DecisionAnalystMetadata(
    ANALYST_ID, "Opportunity Intelligence Analyst", ANALYST_VERSION,
    "opportunity-characterization",
    frozenset({StatementType.COMPUTED_FACT, StatementType.AI_INFERENCE,
               StatementType.HYPOTHESIS, StatementType.UNKNOWN}),
    frozenset({SupportedEntityType.CANONICAL_FACT, SupportedEntityType.REQUIREMENT,
               SupportedEntityType.COMMERCIAL_CLAUSE, SupportedEntityType.DELIVERABLE,
               SupportedEntityType.OBSERVATION, SupportedEntityType.FUTURE_ENTITY}),
)


def _record_id(section: str, record: Mapping, index: int) -> str:
    keys = {
        "requirements": ("requirement_id", "req_id"),
        "deliverables": ("deliverable_id",),
        "commercial_clauses": ("clause_id",),
        "evaluation_criteria": ("criterion_id",),
        "observations": ("observation_id",),
        "conflicts": ("conflict_id",),
        "submission_rules": ("submission_rule_id", "artifact_id"),
        "dates": ("date_id", "milestone_id"),
    }.get(section, ())
    for key in keys:
        if isinstance(record.get(key), str) and record[key].strip():
            return record[key]
    return _id(f"oi-{section}-", {"index": index, "record": record})


def _evidence_ids(record: Mapping) -> tuple[str, ...]:
    found = []
    if isinstance(record.get("evidence_id"), str):
        found.append(record["evidence_id"])
    for ref in record.get("source_refs", []) or []:
        if isinstance(ref, Mapping) and isinstance(ref.get("evidence_id"), str):
            found.append(ref["evidence_id"])
    return tuple(sorted(set(found)))


def _entity_type(section: str) -> SupportedEntityType:
    return {
        "requirements": SupportedEntityType.REQUIREMENT,
        "deliverables": SupportedEntityType.DELIVERABLE,
        "commercial_clauses": SupportedEntityType.COMMERCIAL_CLAUSE,
        "observations": SupportedEntityType.OBSERVATION,
    }.get(section, SupportedEntityType.FUTURE_ENTITY)


def _date_value(value):
    if isinstance(value, Mapping):
        value = value.get("date")
    if not isinstance(value, str):
        return None, False
    text = value.strip()
    partial = bool(re.fullmatch(r"\d{4}(?:-\d{2})?", text))
    try:
        return date.fromisoformat(text[:10]), False
    except (ValueError, TypeError):
        return None, partial


class OpportunityIntelligenceAnalyst:
    metadata = METADATA

    def analyze(self, context: OpportunityAnalysisContext) -> DecisionAnalysis:
        if not isinstance(context, OpportunityAnalysisContext):
            raise ContractValidationError("OpportunityAnalysisContext is required")
        before = _json({"facts": context.normalized_facts, "conflicts": context.conflicts})
        facts = copy.deepcopy(dict(context.normalized_facts))
        conflicts = copy.deepcopy(list(context.conflicts))
        root = EvidenceSupport(SupportedEntityType.CANONICAL_FACT,
                               context.analyst_context.context_id)
        links = {("root", 0): root}

        sections = ("requirements", "deliverables", "commercial_clauses",
                    "evaluation_criteria", "submission_rules", "dates")
        records = {}
        for section in sections:
            value = facts.get(section, []) or []
            if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
                raise ContractValidationError(f"{section} must contain mappings")
            records[section] = value
            for index, item in enumerate(value):
                links[(section, index)] = EvidenceSupport(
                    _entity_type(section), _record_id(section, item, index), _evidence_ids(item))

        canonical = facts.get("_canonical_opportunity") or {}
        if not isinstance(canonical, Mapping):
            raise ContractValidationError("canonical opportunity must be a mapping")
        observations = canonical.get("observations", []) or []
        if not isinstance(observations, list) or any(not isinstance(item, Mapping) for item in observations):
            raise ContractValidationError("canonical observations must contain mappings")
        for index, item in enumerate(observations):
            links[("observations", index)] = EvidenceSupport(
                SupportedEntityType.OBSERVATION, _record_id("observations", item, index),
                _evidence_ids(item))
        for index, item in enumerate(conflicts):
            links[("conflicts", index)] = EvidenceSupport(
                SupportedEntityType.FUTURE_ENTITY, _record_id("conflicts", item, index),
                _evidence_ids(item))

        requirements = records["requirements"]
        categories = Counter(str(item.get("category") or "UNKNOWN").strip().upper()
                             for item in requirements)
        mandatory = sum(1 for item in requirements if str(item.get("category") or "").casefold() == "mandatory")
        optional = sum(1 for item in requirements if str(item.get("category") or "").casefold() == "optional")
        evidence_ready = sum(1 for item in requirements
                             if item.get("evidence_status") in {"READY", "NOT REQUIRED"})
        req_links = tuple(dict.fromkeys(
            links[("requirements", i)] for i in range(len(requirements))
        )) or (root,)

        criteria = records["evaluation_criteria"]
        weighted = sum(1 for item in criteria if item.get("weight_value") is not None or item.get("weight") not in (None, ""))
        missing_weights = len(criteria) - weighted
        thresholds = sum(1 for item in criteria if item.get("threshold") not in (None, ""))
        hierarchy_depth = max((int(item.get("hierarchy_level") or 0) for item in criteria), default=0)

        rules = records["submission_rules"]
        pathways = {str(item.get("submission_channel")).strip() for item in rules
                    if item.get("submission_channel") not in (None, "")}
        mandatory_artifacts = sum(1 for item in rules if item.get("mandatory") in (True, 1, "1", "true", "Required"))
        submission_ambiguity = sum(1 for item in rules if item.get("mandatory") is None
                                   or item.get("mandatory_conflict") is True
                                   or item.get("submission_channel_conflict") is True
                                   or item.get("file_format_conflict") is True)

        milestones = []
        partial_dates = 0
        for item in observations:
            if item.get("family") != "MILESTONE":
                continue
            parsed, partial = _date_value(item.get("date") or item.get("normalized_value"))
            partial_dates += int(partial or item.get("precision") in {"MONTH", "YEAR", "UNKNOWN"})
            if parsed:
                milestones.append((str(item.get("semantic_kind") or "MILESTONE"), parsed))
        for item in records["dates"]:
            parsed, partial = _date_value(item.get("date"))
            partial_dates += int(partial)
            if parsed:
                milestones.append((str(item.get("milestone") or "MILESTONE"), parsed))
        milestones = sorted(set(milestones), key=lambda pair: (pair[1], pair[0]))
        intervals = tuple((milestones[i - 1][0], milestones[i][0],
                           (milestones[i][1] - milestones[i - 1][1]).days)
                          for i in range(1, len(milestones)))
        resolved = canonical.get("resolved", {}) if isinstance(canonical.get("resolved", {}), Mapping) else {}
        clarification, _ = _date_value((resolved.get("clarification_deadline") or {}).get("value")
                                       if isinstance(resolved.get("clarification_deadline"), Mapping) else None)
        submission, _ = _date_value((resolved.get("submission_deadline") or {}).get("value")
                                    if isinstance(resolved.get("submission_deadline"), Mapping) else None)
        clarification_interval = (submission - clarification).days if submission and clarification else None
        milestone_conflicts = sum(1 for value in resolved.values()
                                  if isinstance(value, Mapping) and value.get("status") == "CONFLICTED"
                                  and any(word in str(value).upper() for word in ("DATE", "DEADLINE", "TERM")))
        milestone_conflicts += sum(1 for item in conflicts
                                   if "DATE" in str(item.get("conflict_type") or "").upper())

        clauses = [item for item in records["commercial_clauses"]
                   if item.get("evidence_state") == "VERIFIED" or "clause_id" not in item]
        clause_counts = Counter(str(item.get("clause_kind") or item.get("topic") or "LEGACY").upper()
                                for item in clauses)
        deliverables = [item for item in records["deliverables"]
                        if item.get("evidence_state") == "VERIFIED" or "deliverable_id" not in item]
        monetary = [item for item in observations if item.get("family") == "MONETARY"]

        values = {
            "total_requirements": len(requirements),
            "requirement_category_counts": dict(sorted(categories.items())),
            "mandatory_requirements": mandatory,
            "optional_requirements": optional,
            "requirement_evidence_coverage": {"ready": evidence_ready, "total": len(requirements)},
            "total_conflicts": len(conflicts) + len(canonical.get("conflicts", []) or []),
            "evaluation_hierarchy_depth": hierarchy_depth,
            "weighted_criteria": weighted,
            "criteria_missing_weights": missing_weights,
            "threshold_count": thresholds,
            "submission_artifact_count": len(rules),
            "submission_pathway_count": len(pathways),
            "mandatory_artifact_count": mandatory_artifacts,
            "unresolved_submission_ambiguity": submission_ambiguity,
            "milestone_intervals_days": intervals,
            "clarification_to_submission_days": clarification_interval,
            "milestone_completeness": {"dated": len(milestones), "observed": sum(1 for item in observations if item.get("family") == "MILESTONE") + len(records["dates"])},
            "partial_date_count": partial_dates,
            "unresolved_milestone_conflicts": milestone_conflicts,
            "verified_clause_counts": dict(sorted(clause_counts.items())),
            "deliverable_count": len(deliverables),
            "monetary_observation_count": len(monetary),
        }

        computed = []
        for key, value in sorted(values.items()):
            support = req_links if key.startswith("requirement") or key in {"total_requirements", "mandatory_requirements", "optional_requirements"} else (root,)
            sid = f"oi-computed-{key}"
            computed.append(DecisionStatement(
                sid, StatementType.COMPUTED_FACT, f"{key}={_json(value)}",
                StatementSource(SourceType.DETERMINISTIC_COMPUTATION, f"{ANALYST_ID}/{ANALYST_VERSION}:{key}"),
                None, ReasoningStatus.VALIDATED,
                tuple(sorted({eid for link in support for eid in link.evidence_ids})),
                tuple(link.entity_id for link in support), support,
            ))

        inferences = []
        hypotheses = []
        assumptions = ()
        if requirements or rules or criteria:
            drivers = []
            if len(requirements) >= 20:
                drivers.append("requirement volume")
            if len(rules) >= 5:
                drivers.append("submission artifact volume")
            if len(pathways) > 1:
                drivers.append("multiple submission pathways")
            if hierarchy_depth >= 2:
                drivers.append("evaluation hierarchy depth")
            if drivers:
                support = tuple(dict.fromkeys((*req_links, root)))
                statement = DecisionStatement(
                    "oi-inference-proposal-effort", StatementType.AI_INFERENCE,
                    "The documented structure contains potential proposal-effort drivers: " + ", ".join(drivers) + ".",
                    StatementSource(SourceType.SPECIALIST_ANALYST, ANALYST_ID),
                    Confidence.MODERATE, ReasoningStatus.PROPOSED,
                    tuple(sorted({eid for link in support for eid in link.evidence_ids})),
                    tuple(item.statement_id for item in computed if item.statement_id in {
                        "oi-computed-total_requirements", "oi-computed-submission_artifact_count",
                        "oi-computed-submission_pathway_count", "oi-computed-evaluation_hierarchy_depth"}),
                    support, assumptions=("Structural volume is a relevant effort indicator",),
                    limitations=("No staffing or effort-rate model is available",),
                )
                inferences.append(AnalystReasoning(statement, SupportStatus.PARTIALLY_SUPPORTED))
                assumptions = (AnalystAssumption("oi-assumption-effort-indicators",
                                                  "Structural volume is a relevant effort indicator"),)
                for index, driver in enumerate(drivers, 1):
                    hypotheses.append(AnalystHypothesis(
                        f"oi-hypothesis-effort-{index}",
                        f"The apparent proposal effort may be explained by {driver}.",
                        support, (), Confidence.MODERATE, SupportStatus.PARTIALLY_SUPPORTED,
                        ("The explanation is not ranked against other drivers",),
                    ))

        conflict_ids = tuple(sorted({_record_id("conflicts", item, i) for i, item in enumerate(conflicts)}))
        missing_evidence = tuple(sorted({_record_id("requirements", item, i)
                                        for i, item in enumerate(requirements)
                                        if item.get("evidence_status") not in {"READY", "NOT REQUIRED"}}))
        unknowns = AnalystUnknowns(
            missing_evidence=missing_evidence,
            unresolved_conflict_ids=conflict_ids,
            ambiguous_observation_ids=tuple(sorted({_record_id("observations", item, i)
                for i, item in enumerate(observations)
                if item.get("provenance_status") != "VERIFIED" or item.get("normalization_state") in {"UNPARSED", "EMPTY"}})),
        )
        questions = []
        if conflict_ids or submission_ambiguity:
            related = tuple(item.statement.statement_id for item in inferences)
            questions.append(ManagementQuestion(
                "oi-question-uncertainty-priority",
                "Which documented uncertainties require management escalation before allocating internal effort?",
                related,
            ))
        limitations = tuple(value for value in (
            "Analysis uses only the supplied authoritative opportunity context.",
            "No buyer, competitor, market, pricing, CRM, or organizational capability data is available.",
            "No composite complexity or pursuit score is produced.",
        ))
        output = DecisionAnalysis(
            _id("oi-analysis-", {"context": context.analyst_context.context_id,
                                  "facts": facts, "conflicts": conflicts}),
            ANALYST_ID, datetime.now().astimezone(),
            Confidence.UNKNOWN if not inferences else Confidence.MODERATE,
            tuple(sorted(set(links.values()), key=lambda item: (item.entity_type.value, item.entity_id))),
            tuple(computed), tuple(inferences), tuple(hypotheses), (), limitations,
            assumptions, tuple(questions), unknowns,
        )
        validate_opportunity_analysis(context, output)
        if before != _json({"facts": context.normalized_facts, "conflicts": context.conflicts}):
            raise ContractValidationError("authoritative input mutation")
        return output


def validate_opportunity_analysis(context: OpportunityAnalysisContext,
                                  output: DecisionAnalysis) -> DecisionAnalysis:
    if output.recommendations:
        raise ContractValidationError("Opportunity Intelligence v1 cannot emit recommendations")
    if any(item.statement_type == StatementType.HUMAN_DECISION for item in output.computed_facts):
        raise ContractValidationError("Opportunity Intelligence cannot emit decisions")
    registry = DecisionAnalystRegistry()
    registry.register(OpportunityIntelligenceAnalyst())
    registry.validate_output(ANALYST_ID, output)
    allowed_evidence = {
        EvidenceSupport(SupportedEntityType.CANONICAL_FACT,
                        context.analyst_context.context_id)
    }
    for section in ("requirements", "deliverables", "commercial_clauses",
                    "evaluation_criteria", "submission_rules", "dates"):
        records = context.normalized_facts.get(section, []) or []
        if isinstance(records, list):
            allowed_evidence.update(
                EvidenceSupport(_entity_type(section), _record_id(section, record, index),
                                _evidence_ids(record))
                for index, record in enumerate(records) if isinstance(record, Mapping)
            )
    canonical = context.normalized_facts.get("_canonical_opportunity") or {}
    observations = canonical.get("observations", []) or [] if isinstance(canonical, Mapping) else []
    if isinstance(observations, list):
        allowed_evidence.update(
            EvidenceSupport(SupportedEntityType.OBSERVATION,
                            _record_id("observations", record, index), _evidence_ids(record))
            for index, record in enumerate(observations) if isinstance(record, Mapping)
        )
    allowed_evidence.update(
        EvidenceSupport(SupportedEntityType.FUTURE_ENTITY,
                        _record_id("conflicts", record, index), _evidence_ids(record))
        for index, record in enumerate(context.conflicts)
    )
    if not set(output.evidence_used).issubset(allowed_evidence):
        raise ContractValidationError("analysis references evidence absent from authoritative context")
    expected_conflicts = {_record_id("conflicts", item, i) for i, item in enumerate(context.conflicts)}
    if not expected_conflicts.issubset(set(output.unknowns.unresolved_conflict_ids)):
        raise ContractValidationError("analysis resolved or omitted an unresolved conflict")
    return output


def analyze_opportunity(normalized_facts: Mapping, conflicts=(), *, context_id: str,
                        statements=()) -> DecisionAnalysis:
    """Optional post-pipeline integration point; existing pipeline calls remain unchanged."""
    context = OpportunityAnalysisContext(
        AnalystContext(context_id, (context_id,), tuple(statements)),
        normalized_facts, tuple(conflicts),
    )
    return OpportunityIntelligenceAnalyst().analyze(context)
