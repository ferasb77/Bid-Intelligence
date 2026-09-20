"""
scripts/request_profile.py -- offline, zero-generation request-size
profiler CLI (BI Token Optimization Program, Phase 5A).

Builds RequestProfile objects for representative calls across BI's live
workflows by driving REAL production prompt-construction code (never
reimplemented) with small synthetic/fixture inputs -- this script makes
NO Anthropic API call of any kind. It prints only sizes; it never prints
prompt, schema, or document content.

Usage:
    python scripts/request_profile.py                       # all workflows, compact table
    python scripts/request_profile.py --workflow analyst
    python scripts/request_profile.py --workflow analyst --operation compliance_review
    python scripts/request_profile.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import request_profiling as rp  # noqa: E402


# ---------------------------------------------------------------------------
# Section Analyzer -- build_section_context / _analyzer_prompt are pure
# functions (no network); real code path, small synthetic fixture input.
# ---------------------------------------------------------------------------
def _profile_section_analyzer() -> rp.RequestProfile:
    import section_analyzer as sa
    from fast_analysis import FastAnalysisResult

    section = {"id": 1, "bid_id": 1, "title": "Approach and Methodology",
              "notes": "Describe delivery model.", "word_limit": 500, "status": "Draft"}
    requirements = [
        {"id": 101, "bid_id": 1, "req_id": "R1", "category": "Approach and Methodology",
         "description": "Describe your delivery methodology.", "weight": None, "source_refs": []},
        {"id": 102, "bid_id": 1, "req_id": "R2", "category": "Account Management and Relationship",
         "description": "Describe your account management approach.", "weight": None, "source_refs": []},
    ]
    raw = FastAnalysisResult()
    raw.evaluation_criteria = [
        {"criterion_label": "Approach and Methodology", "weight": "10 points", "threshold": "6 points"},
        {"criterion_label": "Account Management and Relationship", "weight": "15 points", "threshold": "10 points"},
    ]
    raw.deterministic_response_guidelines = [
        {"id": "RG1", "weight": "10", "minimum_score": "6",
         "evidence_prompts": ["Describe your delivery methodology."], "source_doc": "Appendix_B.docx"},
    ]
    raw.typed_observations = [
        {"family": "QUALIFICATION_MECHANISM", "semantic_kind": "REFERENCE_CHECK",
         "original_value": "Two references required.", "rank": None},
        {"family": "TIE_BREAK_RULE", "semantic_kind": "TIE_BREAK_CRITERION",
         "original_value": "Account Management governs first.", "rank": 1},
    ]
    raw.buyer_intelligence = {
        "intro": "Buyer overview.",
        "verified_facts": [{"topic": "Operations",
                            "detail": "Distributed retail and warehouse workforce.",
                            "source": "public filing"}],
    }
    basis = {"raw_snapshot": raw, "procurement_truth_status": "governed", "procurement_revision": 3,
            "raw_snapshot_unavailable_reason": None}
    section_text = ("We propose an agile delivery methodology with weekly stakeholder "
                    "check-ins and iterative releases.")

    context = sa.build_section_context(section, section_text, requirements, basis)
    _, components = sa._analyzer_prompt(context, return_components=True)
    return rp.build_profile(
        workflow="section_analyzer", operation="formative_review", model=sa._MODEL,
        system=sa._ANALYZER_SYSTEM,
        source_document=components["section"],
        procurement_context=components["requirements"],
        buyer_intelligence=components["buyer_intelligence"],
        other_context=components["instructions"],
        max_tokens=3000,
        notes="synthetic fixture (2 requirements, short section text); "
              "real build_section_context()/_analyzer_prompt() code path",
    )


# ---------------------------------------------------------------------------
# Fast Analysis -- _build_prompt() is a pure function (no network).
# ---------------------------------------------------------------------------
def _profile_fast_analysis() -> rp.RequestProfile:
    import fast_analysis as fa

    route = next(iter(fa._ROUTE_SCHEMAS))
    schema_text = fa._ROUTE_SCHEMAS[route]
    chunk_text = "Sample RFP document text for offline sizing purposes. " * 150  # ~8.4K chars
    filename = "sample_rfp.pdf"
    prompt = fa._build_prompt(route, filename, chunk_text)
    marker = f"\n\nDOCUMENT TO PROCESS ({filename}):\n"
    header = prompt[: prompt.index(marker)]
    instructions_only = header.replace(schema_text, "") if schema_text in header else header
    return rp.build_profile(
        workflow="fast_analysis", operation="initial", model=fa.FAST_MODEL,
        schema=schema_text, other_context=instructions_only, source_document=chunk_text,
        max_tokens=fa.FAST_MAX_OUTPUT_TOKENS,
        notes=f"synthetic {len(chunk_text)}-char chunk, route={route}; real _build_prompt() code path",
    )


# ---------------------------------------------------------------------------
# Deep Verify Stage A -- request_text formula mirrors extractor.py's
# _extract_chunk_facts exactly (a one-line f-string concat around a pure
# module constant; no separate pure helper exists to call directly).
# ---------------------------------------------------------------------------
def _profile_stage_a() -> rp.RequestProfile:
    import extractor as ex

    chunk_text = "Sample RFP clause text for offline sizing purposes. " * 220  # ~11.5K chars
    return rp.build_profile(
        workflow="deep_verify", operation="initial", model="claude-haiku-4-5-20251001",
        other_context=ex.STAGE_A_FACT_EXTRACTION_PROMPT, source_document=chunk_text,
        max_tokens=ex._STAGE_A_MAX_OUTPUT_TOKENS,
        notes=f"synthetic {len(chunk_text)}-char chunk; mirrors extractor.py's "
              "_extract_chunk_facts request_text formula (extractor.py:3176) exactly",
    )


# ---------------------------------------------------------------------------
# Deep Verify Stage D -- projection/schema builders are pure functions.
# ---------------------------------------------------------------------------
def _profile_stage_d() -> rp.RequestProfile:
    import stage_d_projection as sdp

    facts = {
        "requirements": [{"req_id": "R1", "category": "Technical", "description": "Deliver on time",
                          "source_refs": [{"source_doc": "rfp.pdf", "excerpt": "Deliverables due Q1"}]}],
        "deliverables": [{"description": "Final report",
                          "source_refs": [{"source_doc": "rfp.pdf", "excerpt": "Submit a final report"}]}],
    }
    projection = sdp.build_stage_d_synthesis_projection(facts, [])
    finalized = sdp.finalize_stage_d_request(projection, sdp.SYNTHESIS_PROMPT)
    output_config = sdp.stage_d_output_config(projection)
    schema_bytes = len(json.dumps(output_config).encode("utf-8"))
    return rp.build_profile(
        workflow="deep_verify", operation="stage_d_synthesis", model="claude-haiku-4-5-20251001",
        other_context=finalized["request_text"], tool_schema_bytes=schema_bytes,
        max_tokens=8000,
        notes="minimal synthetic facts (1 requirement, 1 deliverable), no conflicts; "
              "real build_stage_d_synthesis_projection()/finalize_stage_d_request()/"
              "stage_d_output_config() code path",
    )


# ---------------------------------------------------------------------------
# analyst.py -- _call() is the sole chokepoint for all 11 operations.
# Patch-and-capture it (same pattern tests/test_anthropic_client_config.py
# already uses to assert call args) so the REAL system/user text for each
# operation is measured without reimplementing any prompt construction.
# ---------------------------------------------------------------------------
class _Captured(Exception):
    def __init__(self, system, user, max_tokens, operation):
        super().__init__(operation)
        self.system, self.user, self.max_tokens, self.operation = system, user, max_tokens, operation


def _capture_first_call(fn) -> "_Captured | None":
    import analyst

    original = analyst._call

    def capturing(system, user, max_tokens=2048, *, operation="unknown", **_kw):
        raise _Captured(system, user, max_tokens, operation)

    analyst._call = capturing
    try:
        fn()
        return None
    except _Captured as captured:
        return captured
    finally:
        analyst._call = original


# Operations reachable through a simple top-level call with a small fixture
# -- covers 8 of the 11 documented operations (analyst.py's module
# docstring / model_telemetry.py's authoritative label list).
def _analyst_simple_operations():
    import analyst

    req = [{"id": 1, "req_id": "R1", "category": "Technical",
           "description": "Deliver on time", "weight": 0.10}]
    bid_info = {"title": "Sample RFP", "client": "Sample Buyer", "id": 1}
    rfp_text = "Sample RFP text describing the requirement in detail."
    return [
        ("compliance_review", lambda: analyst.compliance_review("We will deliver on time.", req)),
        ("missing_evidence", lambda: analyst.missing_evidence(req, bid_info)),
        ("clarification_questions", lambda: analyst.generate_clarification_questions(
            bid_info, req, rfp_text)),
        ("bid_no_bid_score", lambda: analyst.bid_no_bid_score(bid_info, req, rfp_text)),
        ("past_proposal_analysis", lambda: analyst.analyze_past_proposal(
            "Past proposal text with reusable capability statements.", bid_info)),
        ("draft_proposal_section", lambda: analyst.draft_proposal_section(
            "Technical Approach", req,
            [{"category": "Technical", "title": "Delivery methodology",
              "content": "Reusable content describing our standard delivery approach."}],
            bid_info)),
        ("submission_readiness_check", lambda: analyst.submission_readiness_check(
            bid_info, req,
            [{"name": "Technical Proposal.pdf", "mandatory": True}],
            [{"title": "Technical Approach", "status": "Complete"}])),
        ("addendum_analysis", lambda: analyst.analyze_addendum(
            "Addendum 1 changes the delivery date.", req, bid_info)),
    ]


# The remaining 3 operations (proposal_alignment_chunk, proposal_alignment_
# synthesis, procurement_change_proposal) are internal helpers invoked from
# inside a chunking/threading pipeline with a wider parameter surface. This
# pass reports their REAL system-prompt size and REAL max_tokens (both
# exact, from the live module constants/call sites) but does not fabricate
# a representative dynamic user-prompt -- that needs per-chunk fixture
# construction out of scope for this pass (see final report, "remaining
# unknowns").
def _analyst_system_only_operations():
    import analyst

    return [
        ("proposal_alignment_chunk", analyst._ALIGN_CHUNK_SYSTEM, 2000),
        ("proposal_alignment_synthesis", analyst._ALIGN_SYNTHESIS_SYSTEM, 1500),
        ("procurement_change_proposal", analyst._PROCUREMENT_CHANGE_SYSTEM, 2500),
    ]


def _profile_analyst_operations() -> list[rp.RequestProfile]:
    profiles = []
    for operation, fn in _analyst_simple_operations():
        captured = _capture_first_call(fn)
        if captured is None:
            profiles.append(rp.RequestProfile(
                workflow="analyst", operation=operation,
                notes="SKIPPED: analyst._call was not reached with this synthetic fixture"))
            continue
        profiles.append(rp.build_profile(
            workflow="analyst", operation=captured.operation, model="claude-haiku-4-5-20251001",
            system=captured.system, other_context=captured.user,
            max_tokens=captured.max_tokens,
            notes="captured via analyst._call patch (real prompt-construction code path), "
                  "synthetic 1-requirement fixture",
        ))
    for operation, system_const, max_tokens in _analyst_system_only_operations():
        profiles.append(rp.build_profile(
            workflow="analyst", operation=operation, model="claude-haiku-4-5-20251001",
            system=system_const, max_tokens=max_tokens,
            notes="system-prompt/max_tokens only (real constants); dynamic per-chunk "
                  "user-prompt not profiled this pass -- see final report",
        ))
    return profiles


_BUILDERS = {
    ("section_analyzer", "formative_review"): _profile_section_analyzer,
    ("fast_analysis", "initial"): _profile_fast_analysis,
    ("deep_verify", "initial"): _profile_stage_a,
    ("deep_verify", "stage_d_synthesis"): _profile_stage_d,
}


def all_profiles() -> list[rp.RequestProfile]:
    profiles = [builder() for builder in _BUILDERS.values()]
    profiles.extend(_profile_analyst_operations())
    return profiles


def _print_table(profiles: list[rp.RequestProfile]) -> None:
    header = f"{'WORKFLOW':<18} {'OPERATION':<28} {'SYS':>7} {'OTHER':>7} {'SCHEMA':>7} {'REQ BYTES':>10} {'MAX_OUT':>8}"
    print(header)
    print("-" * len(header))
    for p in profiles:
        print(f"{p.workflow:<18} {p.operation:<28} {p.system_chars:>7} {p.other_context_chars:>7} "
              f"{p.schema_chars:>7} {p.request_total_bytes:>10} {str(p.max_tokens or '-'):>8}")


def _print_detail(p: rp.RequestProfile) -> None:
    print(f"{p.workflow.upper()} / {p.operation}")
    print()
    if p.system_chars:
        print(f"System prompt:               {p.system_chars:>8,} chars  ({p.system_bytes:,} bytes)")
    if p.schema_chars or p.tool_schema_bytes:
        print(f"Schema:                      {p.schema_chars:>8,} chars  ({p.schema_bytes or p.tool_schema_bytes:,} bytes)")
    if p.source_document_chars:
        print(f"Source document:             {p.source_document_chars:>8,} chars  ({p.source_document_bytes:,} bytes)")
    if p.procurement_context_chars:
        print(f"Procurement context:         {p.procurement_context_chars:>8,} chars  ({p.procurement_context_bytes:,} bytes)")
    if p.buyer_intelligence_chars:
        print(f"Buyer intelligence:          {p.buyer_intelligence_chars:>8,} chars  ({p.buyer_intelligence_bytes:,} bytes)")
    if p.proposal_content_chars:
        print(f"Proposal content:            {p.proposal_content_chars:>8,} chars  ({p.proposal_content_bytes:,} bytes)")
    if p.other_context_chars:
        print(f"Other context/instructions:  {p.other_context_chars:>8,} chars  ({p.other_context_bytes:,} bytes)")
    print("-" * 45)
    print(f"Total request bytes:         {p.request_total_bytes:>8,}")
    if p.provider_counted_input_tokens is not None:
        print(f"Provider-counted input:      {p.provider_counted_input_tokens:>8,} tokens")
    elif p.estimated_input_tokens is not None:
        print(f"Estimated input (ESTIMATE):  {p.estimated_input_tokens:>8,} tokens  [chars/4 heuristic, not provider-counted]")
    if p.max_tokens:
        print(f"Max output:                  {p.max_tokens:>8,} tokens")
    if p.notes:
        print(f"\nNotes: {p.notes}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", help="Filter to one workflow (e.g. analyst, section_analyzer)")
    parser.add_argument("--operation", help="Filter to one operation")
    parser.add_argument("--fixture", help="Reserved for future fixture-file selection (unused)")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args()

    profiles = all_profiles()
    if args.workflow:
        profiles = [p for p in profiles if p.workflow == args.workflow]
    if args.operation:
        profiles = [p for p in profiles if p.operation == args.operation]

    if not profiles:
        print("No matching workflow/operation.", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps([p.as_dict() for p in profiles], indent=2))
    elif len(profiles) == 1:
        _print_detail(profiles[0])
    else:
        _print_table(profiles)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
