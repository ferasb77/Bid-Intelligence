"""
fast_analysis_app_adapter.py

Deterministic, no-LLM adapter: FastAnalysisResult -> (a) the application-
facing OpportunityIntelligence structured contract persisted to
analysis_results.structured_intelligence, and (b) a projection into the
EXISTING bid_briefs table shape that pages/stage_understand.py already
renders unchanged.

Product Integration Phase 1 (instruction 4/11/16). Does not modify
fast_analysis.py's engine behavior or scripts/fast_analysis_report_adapter.py's
PDF-content contract -- both remain frozen (V4 accepted behavior). This
module only maps their already-correct, already-tested output into the
application's persistence and view shapes; it contains no extraction logic
and makes no API calls.
"""
from __future__ import annotations

from fast_analysis import FastAnalysisResult, carry_forward_category_scope
import scripts.fast_analysis_report_adapter as fast_report_adapter

OPPORTUNITY_INTELLIGENCE_CONTRACT_VERSION = "1.0.0"

# Commercial-point topics that materially affect liability, IP, data
# handling, or termination -- used to derive the contract_risks projection
# from the broader commercial_structure. Generic clause-kind vocabulary
# (matches fast_analysis.py's own COMMERCIAL_ONLY schema enum), not tied to
# any specific procurement.
_CONTRACT_RISK_TOPICS = {
    "Liability Indemnity", "Intellectual Property", "Data Protection Privacy",
    "Cybersecurity Security", "Termination", "Insurance", "Governing Law Dispute",
    "Regulatory Compliance",
}


def build_opportunity_intelligence(result: FastAnalysisResult) -> dict:
    """The full, durable, source-traceable structured contract. Independent
    of any one rendering (PDF, bid_briefs projection, a future progressive
    UI) -- this is what instruction 11 means by "the PDF is one rendering
    of the intelligence." Every section carries its own source references
    where the underlying facts do."""
    content = fast_report_adapter.build_fast_report_content(result)

    return {
        "contract_version": OPPORTUNITY_INTELLIGENCE_CONTRACT_VERSION,
        "opportunity_snapshot": {
            "facts": [{"label": k, "value": v} for k, v in content.SNAPSHOT_FACTS],
            "category_cards": [
                {"category": c[0], "name": c[1], "detail": c[2]}
                for c in content.SNAPSHOT_CATEGORY_CARDS
            ],
            "note": content.SNAPSHOT_NOTE,
        },
        "procurement_scope": {
            "intro": content.PROCURED_INTRO,
            "service_categories": [
                {"name": c[0], "tag": c[1], "description": c[2]}
                for c in content.SERVICE_CATEGORIES
            ],
            "structure": content.PROCURED_STRUCTURE,
            "model_note": content.PROCURED_MODEL_NOTE,
        },
        "dates_and_mechanics": {
            "key_dates": [{"date": d[0], "label": d[1]} for d in content.KEY_DATES],
            "mechanics": content.BID_MECHANICS,
            "note": content.DATES_NOTE,
            # Phase 3 commissioning fix: the summarized key_dates rows above
            # (like every other *_STAGES/*_POINTS display tuple from the
            # report adapter) don't carry source_refs -- only occurrence-
            # level data does. Raw MILESTONE-family observations retain
            # their own source_refs, so they're surfaced separately here for
            # a "View Source" expander on the dates section (instruction
            # 12: material facts retain source references), the same way
            # evaluation.raw_occurrences and pricing_and_commercial.
            # raw_pricing_occurrences already do.
            "raw_date_observations": [
                {k: obs.get(k) for k in
                 ("semantic_kind", "original_value", "date", "scope", "source_doc", "source_refs")}
                for obs in result.typed_observations
                if isinstance(obs, dict) and obs.get("family") == "MILESTONE"
            ],
        },
        "evaluation": {
            "stages": [
                {"stage": s[0], "component": s[1], "basis": s[2]}
                for s in content.EVAL_STAGES
            ],
            "gate_examples": content.GATE_EXAMPLES,
            "weights_by_category": {
                label: [{"criterion": c[0], "weight": c[1]} for c in rows]
                for label, rows in content.EVAL_WEIGHTS.items()
            },
            "note": content.EVAL_WEIGHT_NOTE,
            # Raw, occurrence-preserving evaluation facts with full source
            # provenance -- the durable record behind the summarized table
            # above (instruction 12: material facts retain source refs).
            "raw_occurrences": [
                {k: occ.get(k) for k in
                 ("criterion_label", "weight", "category_scope", "evaluation_stage",
                  "parent_heading", "source_doc", "source_refs")}
                for occ in carry_forward_category_scope(result.evaluation_occurrences)
            ],
        },
        "response_requirements": {
            "checklist": [
                {"item": r[0], "description": r[1], "notes": r[2]}
                for r in content.RESPONSE_CHECKLIST
            ],
            "other_requirements": content.RESPONSE_OTHER_REQUIREMENTS,
        },
        "pricing_and_commercial": {
            "points": [{"topic": p[0], "detail": p[1]} for p in content.COMMERCIAL_POINTS],
            "raw_pricing_occurrences": [
                {k: occ.get(k) for k in
                 ("semantic_kind", "raw_wording", "stage", "category_scope",
                  "weight", "source_doc", "source_refs")}
                for occ in result.pricing_occurrences
            ],
        },
        "ambiguities": [
            {
                "type": a.get("_type"),
                "issue": a.get("issue"),
                "why_it_matters": a.get("why"),
                "source": a.get("source"),
                "clarification_question": a.get("question"),
            }
            for a in content.AMBIGUITIES
        ],
        "bid_team_attention_points": content.ATTENTION_POINTS,
        "source_map": {
            "documents": [{"document": d[0], "content": d[1]} for d in content.SOURCE_DOCUMENTS],
            "reference_table": [
                {"finding": r[0], "reference": r[1]} for r in content.SOURCE_REF_TABLE
            ],
            "validation_note": content.VALIDATION_FOOTER_NOTE,
        },
        "buyer_intelligence": {
            "intro": content.BUYER_INTEL_INTRO,
            "verified_facts": [
                {"topic": f[0], "detail": f[1], "source": f[2]}
                for f in content.VERIFIED_BUYER_FACTS
            ],
            "facts_note": content.BUYER_FACTS_NOTE,
            "relevant_signals": [
                {"topic": s[0], "detail": s[1]} for s in content.RELEVANT_BUYER_SIGNALS
            ],
            "bid_relevance": [
                {"signal": b[0], "interpretation": b[1]} for b in content.BID_RELEVANCE_ITEMS
            ],
            "bid_team_panel_title": content.BID_TEAM_PANEL_TITLE,
            "bid_team_panel_items": content.BID_TEAM_PANEL_ITEMS,
            "sources_note": content.BUYER_INTEL_SOURCES_NOTE,
        },
        # Origin metadata is carried at the top level too (instruction 13:
        # "do not throw the information away") in addition to being
        # persisted separately on analysis_results.fact_origins.
        "fact_origins": dict(content.FACT_ORIGINS),
    }


def _procurement_mechanic_label(result: FastAnalysisResult) -> str:
    for obs in result.typed_observations:
        if obs.get("family") == "PROCUREMENT_MECHANIC" and (obs.get("semantic_kind") or "").upper() == "RFP":
            value = obs.get("original_value")
            if value:
                return value
    return "Procurement Opportunity"


def build_bid_brief_projection(result: FastAnalysisResult) -> dict:
    """Deterministic projection into the EXISTING bid_briefs table shape
    pages/stage_understand.py already renders unchanged (instruction 16/17:
    reuse the existing design, don't redesign it in this phase). Does not
    include bid_id -- callers attach that before database.upsert_bid_brief().
    No API calls; pure formatting over content already produced by
    scripts/fast_analysis_report_adapter.py."""
    content = fast_report_adapter.build_fast_report_content(result)
    facts = dict(content.SNAPSHOT_FACTS)

    buyer = facts.get("Buyer", "The buyer")
    opportunity = facts.get("Opportunity", "this opportunity")
    categories = facts.get("Service Categories", "")
    deadline = facts.get("Submission Deadline", "the date stated in the RFP")
    executive_summary = (
        f"{buyer} is procuring {opportunity}"
        + (f" ({categories})" if categories else "")
        + f". Proposals are due {deadline}."
    )

    scope_categories = [c[0] for c in content.SERVICE_CATEGORIES]

    deliverables_summary = [
        {"title": c[0], "category": c[1], "description": c[2]}
        for c in content.SERVICE_CATEGORIES
    ]

    qualification_gates = [
        {"type": "Minimum Qualification", "requirement": g}
        for g in content.GATE_EXAMPLES
    ]

    evaluation_breakdown = [
        {"stage": criterion, "weight": weight, "parent_stage": label}
        for label, rows in content.EVAL_WEIGHTS.items()
        for criterion, weight in rows
    ]

    commercial_structure = [
        {"topic": p[0], "source_fact": p[1]} for p in content.COMMERCIAL_POINTS
    ]
    contract_risks = [
        {"topic": p[0], "source_fact": p[1]}
        for p in content.COMMERCIAL_POINTS if p[0] in _CONTRACT_RISK_TOPICS
    ]

    submission_requirements = (
        [{"item": f"{r[0]} — {r[1]}", "details": r[2]} for r in content.RESPONSE_CHECKLIST]
        + [{"item": item} for item in content.RESPONSE_OTHER_REQUIREMENTS]
    )

    key_dates = [{"milestone": d[1], "date": d[0]} for d in content.KEY_DATES]

    source_citations = {row[0]: row[1] for row in content.SOURCE_REF_TABLE}

    solicitation_ref = facts.get("Solicitation Number", "the RFP")
    document_conflicts = [
        {
            "conflict_type": a.get("_type"),
            "topic": a["issue"],
            "classification": "REVIEW_ITEM",
            "source_a": {"doc": solicitation_ref, "text": a["issue"]},
            "source_b": {"doc": a.get("source", ""), "text": a.get("why", "")},
            "assessment": a.get("why", ""),
            "recommended_action": a.get("question", ""),
        }
        for a in content.AMBIGUITIES
    ]

    return {
        "executive_summary": executive_summary,
        "opportunity_type": _procurement_mechanic_label(result),
        "contract_term": facts.get("Contract Term", "Not stated"),
        "procurement_model": facts.get("Procurement Model", "Not classified"),
        "scope_categories": scope_categories,
        "deliverables_summary": deliverables_summary,
        "qualification_gates": qualification_gates,
        "evaluation_breakdown": evaluation_breakdown,
        "commercial_structure": commercial_structure,
        "contract_risks": contract_risks,
        "submission_requirements": submission_requirements,
        "key_dates": key_dates,
        "source_citations": source_citations,
        "document_conflicts": document_conflicts,
    }
