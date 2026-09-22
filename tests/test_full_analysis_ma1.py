"""
MA-1: Bounded Specialist Full Analysis.

Every test here is fully deterministic and synthetic: ZERO live provider
calls (every model call is mocked), no live database, no file I/O. The
Bank of Canada-shaped fixture reproduces the real corpus's STRUCTURE --
three service categories sharing criterion labels, a main RFP plus an
amendment, category-specific demonstration dates, a typed Assignment
clause next to a typed Indemnity clause -- from inline data, never from
the live corpus.
"""
from __future__ import annotations

import json
from types import SimpleNamespace, MappingProxyType

import pytest

import canonical_procurement as canon
import full_analysis as fa


# ---------------------------------------------------------------------------
# Fixtures: a Bank of Canada-SHAPED canonical Fast Analysis result
# ---------------------------------------------------------------------------

CAT_1 = "Appendix D1 - Learning and Development"
CAT_2 = "Appendix D2 - HR Advisory"
CAT_3 = "Appendix D3 - Facilitation"

MAIN_RFP = "RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf"
ADDENDUM = "Amendment1/RFP 2026-026 - Addendum 1.pdf"
FORM_D2 = "Amendment1/RFP 2026-026 - Appendix D2 - Rated Criteria Response REVISED.docx"


def _occ(category, label, weight, doc):
    return {"criterion_label": label, "category_scope": category, "weight": weight,
            "minimum_score": None, "evaluation_stage": "Stage 3 - Rated criteria",
            "source_doc": doc, "source_refs": [f"{doc} p.3"]}


def make_result(**overrides):
    """A FastAnalysisResult-shaped object (duck-typed SimpleNamespace --
    build_canonical_package only reads attributes, never constructs one)."""
    base = dict(
        doc_metadata_by_doc={
            MAIN_RFP: {"title": "Talent, Learning and Organizational Development Services",
                       "client": "Bank of Canada", "file_number": "RFP 2026-026",
                       "submission_deadline": "2026-10-30",
                       "clarification_deadline": "2026-10-09"},
            ADDENDUM: {"title": "Addendum 1", "client": "Bank of Canada"},
            FORM_D2: {"title": "Appendix D2 Rated Criteria Response"},
        },
        typed_observations=[
            {"family": "MILESTONE", "semantic_kind": "Demonstration",
             "original_value": "2026-11-16", "scope": {"category": "Category 1"},
             "source_refs": [f"{MAIN_RFP} p.9"]},
            {"family": "MILESTONE", "semantic_kind": "Demonstration",
             "original_value": "2026-11-20", "scope": {"category": "Category 3"},
             "source_refs": [f"{MAIN_RFP} p.9"]},
            {"family": "PROCUREMENT_MECHANIC",
             "original_value": "multi-vendor call-off arrangement",
             "source_refs": [f"{MAIN_RFP} p.4"]},
        ],
        evaluation_criteria=[],
        evaluation_occurrences=[
            _occ(CAT_1, "Corporate Profile", "5", FORM_D2),
            _occ(CAT_2, "Corporate Profile", "5", FORM_D2),
            _occ(CAT_3, "Corporate Profile", "10", FORM_D2),
            _occ(CAT_1, "Key Personnel", "15", FORM_D2),
            _occ(CAT_2, "Methodology and Advisory Approach", "20", FORM_D2),
        ],
        scoped_criterion_response_prompts={
            canon.scoped_criterion_map_key(CAT_1, "Corporate Profile"): {
                "response_prompt": "Proponents are to describe their learning practice. "
                                   "Attach curriculum vitae for named designers."},
        },
        requirements=[
            {"description": "The proponent must deliver services in both official languages "
                            "(bilingualism) for Category 2 engagements.",
             "requirement_type": "MANDATORY", "source_doc": MAIN_RFP,
             "category_scope": "Category 2", "source_refs": [f"{MAIN_RFP} p.12"]},
            {"description": "All materials must conform to WCAG 2.1 Level AA accessibility "
                            "standards and applies to all categories.",
             "requirement_type": "MANDATORY", "source_doc": MAIN_RFP,
             "source_refs": [f"{MAIN_RFP} p.13"]},
            {"description": "Proposals must be submitted through the electronic tendering "
                            "portal before the closing time.",
             "requirement_type": "SUBMISSION", "source_doc": MAIN_RFP,
             "source_refs": [f"{MAIN_RFP} p.6"]},
        ],
        commercial_clauses=[
            {"clause_text": "The Supplier shall not assign this Agreement without the prior "
                            "written consent of the Bank.",
             "heading": "Assignment", "source_doc": "Appendix G - Form of Agreement.docx",
             "source_refs": ["Appendix G p.8"]},
            {"clause_text": "The Supplier shall indemnify and save harmless the Bank from any "
                            "loss or damage arising from the Services.",
             "heading": "Indemnity", "source_doc": "Appendix G - Form of Agreement.docx",
             "source_refs": ["Appendix G p.9"]},
            {"clause_text": "Rates shall remain firm for the initial term; any price increase "
                            "shall not exceed the consumer price index.",
             "heading": "Pricing", "source_doc": "Appendix E - Pricing Form.xlsx",
             "source_refs": ["Appendix E Sheet1"]},
        ],
        category_scope_items={
            CAT_1: [{"text": "The Contractor shall provide curriculum design, facilitation "
                             "and evaluation services for leadership programs.",
                     "semantic_type": canon.SEMANTIC_SCOPE_ITEM, "source_doc": MAIN_RFP}],
            CAT_2: [{"text": "The services will include organizational design advice, job "
                             "evaluation support and change management advisory.",
                     "semantic_type": canon.SEMANTIC_SCOPE_ITEM, "source_doc": MAIN_RFP}],
            CAT_3: [{"text": "Scope of work: facilitation of team effectiveness sessions and "
                             "offsite retreats delivered on site.",
                     "semantic_type": canon.SEMANTIC_SCOPE_ITEM, "source_doc": MAIN_RFP}],
        },
        page_limits={FORM_D2: 5},
        skipped_documents=[], batched_documents=[], documents_by_route={},
        ambiguities={}, telemetry=[], wall_seconds=1.0, deterministic_seconds=0.1,
        buyer_intelligence=None, deterministic_service_scope=None,
        deterministic_response_guidelines=[],
        deterministic_criterion_response_prompts={},
        scoped_criterion_evaluation={}, canonical_milestones=[],
        document_relationships={}, package_completeness={"status": "SUFFICIENT"},
        pricing_occurrences=[], focused_sections_found={},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def package():
    return fa.build_canonical_package(make_result(), bid_id=8, analysis_run_id=19)


# ---------------------------------------------------------------------------
# Mock model infrastructure -- no provider call ever happens in this suite.
# ---------------------------------------------------------------------------

class _Response:
    def __init__(self, payload):
        self.content = [SimpleNamespace(text=json.dumps(payload))]
        self.usage = SimpleNamespace(input_tokens=1200, output_tokens=300)
        self.stop_reason = "end_turn"


class MockClient:
    """Records every prompt it is asked to send and returns a scripted
    structured response. `fail_for` makes exactly one specialist's call
    raise, so failure isolation can be tested without a live provider."""

    def __init__(self, payload_for=None, fail_for=()):
        self.prompts: list[str] = []
        self.payload_for = payload_for or (lambda prompt: {"findings": []})
        self.fail_for = tuple(fail_for)
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        prompt = kwargs["messages"][0]["content"][0]["text"]
        self.prompts.append(prompt)
        for marker in self.fail_for:
            if marker in prompt:
                raise RuntimeError("simulated provider failure")
        return _Response(self.payload_for(prompt))


def finding(ftype, title, ids, **extra):
    base = {"finding_type": ftype, "title": title, "detail": title + " detail",
            "canonical_ids": ids, "category_scope": "", "severity": "MEDIUM",
            "human_confirmation_required": False}
    base.update(extra)
    return base


def _first_id(package, attr):
    return getattr(package, attr)[0]["canonical_id"]


# ═══════════════════════════════════════════════════════════════════════
# 1. Canonical package assembly
# ═══════════════════════════════════════════════════════════════════════

def test_package_is_immutable_and_deterministic():
    pkg_a = fa.build_canonical_package(make_result(), bid_id=8)
    pkg_b = fa.build_canonical_package(make_result(), bid_id=8)
    assert pkg_a.package_digest == pkg_b.package_digest
    with pytest.raises(Exception):
        pkg_a.requirements = ()          # frozen dataclass
    with pytest.raises(TypeError):
        pkg_a.identity["fields"] = {}    # read-only mapping


def test_package_derives_missing_ci1_fields_without_reextraction(package):
    # The fixture supplies NO scoped_criterion_evaluation / canonical_milestones /
    # document_relationships -- exactly like an older raw snapshot. They are
    # re-derived from the frozen Layer 1/2 functions, not invented.
    assert len(package.scoped_criteria) == 5
    assert len(package.milestones) == 2
    assert {d["relationship"] for d in package.document_relationships}


def test_amendment_never_becomes_the_identity_document(package):
    roles = {d["document"]: d["identity_role"] for d in package.document_roles}
    assert roles[ADDENDUM] == canon.IDENTITY_ROLE_AMENDMENT
    assert roles[MAIN_RFP] == canon.IDENTITY_ROLE_PRIMARY_SOLICITATION
    assert package.identity["fields"]["file_number"]["source_doc"] == MAIN_RFP


# ═══════════════════════════════════════════════════════════════════════
# 2. Strict input boundaries (task section 3 / 19)
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("specialist_id", fa.SPECIALIST_IDS)
def test_each_specialist_receives_only_permitted_canonical_object_types(package, specialist_id):
    payload = fa.build_specialist_input(package, specialist_id)
    permitted = fa.SPECIALIST_INPUT_TYPES[specialist_id]
    assert set(payload["objects"]) <= permitted
    assert set(payload["objects"]) <= set(fa.CANONICAL_OBJECT_TYPES)


def test_specialists_cannot_mutate_canonical_input(package):
    payload = fa.build_specialist_input(package, fa.SPECIALIST_REQUIREMENTS_COMPLIANCE)
    requirement = payload["objects"][fa.OBJ_CANONICAL_REQUIREMENT][0]
    assert isinstance(requirement, MappingProxyType)
    with pytest.raises(TypeError):
        requirement["description"] = "rewritten by an agent"
    with pytest.raises(TypeError):
        payload["objects"] = {}
    # the canonical package itself is untouched
    assert package.requirements[0]["description"].startswith("The proponent must deliver")


def test_unknown_specialist_id_fails_closed(package):
    with pytest.raises(fa.CanonicalBoundaryError):
        fa.build_specialist_input(package, "SOMETHING_ELSE")


def test_source_ids_outside_canonical_input_fail_closed(package):
    payload = fa.build_specialist_input(package, fa.SPECIALIST_REQUIREMENTS_COMPLIANCE)
    permitted = fa.slice_canonical_ids(payload)
    accepted, rejected = fa.validate_findings(
        [finding(fa.FINDING_FACT, "Real", [sorted(permitted)[0]]),
         finding(fa.FINDING_RISK, "Invented", ["REQ-9999"]),
         finding(fa.FINDING_FACT, "Hallucinated doc", ["DOC-some-other-rfp"])],
        permitted, produced_by="X")
    assert [f["title"] for f in accepted] == ["Real"]
    assert {r["reason"] for r in rejected} == {"UNCITED_OR_UNKNOWN_CANONICAL_ID"}


def test_specialist_may_not_cite_an_object_it_was_not_given(package):
    """A commercial obligation id is real in the package but was never shown
    to the Schedule specialist -- citing it still fails closed."""
    schedule_ids = fa.slice_canonical_ids(
        fa.build_specialist_input(package, fa.SPECIALIST_SCHEDULE_SUBMISSION))
    obligation_id = _first_id(package, "commercial_obligations")
    assert obligation_id in package.canonical_ids
    accepted, rejected = fa.validate_findings(
        [finding(fa.FINDING_FACT, "Cross-domain leak", [obligation_id])],
        schedule_ids, produced_by=fa.SPECIALIST_SCHEDULE_SUBMISSION)
    assert accepted == []
    assert rejected[0]["reason"] == "UNCITED_OR_UNKNOWN_CANONICAL_ID"


def test_no_specialist_input_contains_raw_document_text(package):
    for specialist_id in fa.SPECIALIST_IDS:
        prompt = fa._build_specialist_prompt(
            specialist_id, fa.build_specialist_input(package, specialist_id))
        # Bounded canonical objects only: nothing carries the source-marker
        # syntax that raw parsed document text always carries.
        assert "[[SOURCE:" not in prompt
        assert len(prompt) < 60000


def test_no_specialist_can_reach_om_ingestion_or_drafting():
    """The module physically imports none of the systems a specialist is
    forbidden to reach (task section 3 / 21 / 22)."""
    source = open(fa.__file__, encoding="utf-8").read()
    for forbidden in ("import organizational_memory", "import section_drafting",
                      "import proposal_outline", "import evidence_query",
                      "import extractor\n", "extract_document_with_metadata",
                      "run_fast_analysis_corpus", "import database"):
        assert forbidden not in source, forbidden


# ═══════════════════════════════════════════════════════════════════════
# 3. Domain-correct slices (task sections 5-9 / 19)
# ═══════════════════════════════════════════════════════════════════════

def test_evaluation_specialist_keeps_d1_d2_d3_scoped(package):
    payload = fa.build_specialist_input(package, fa.SPECIALIST_EVALUATION_INTELLIGENCE)
    criteria = payload["objects"][fa.OBJ_SCOPED_EVALUATION_CRITERION]
    corporate = [c for c in criteria if c["criterion"] == "Corporate Profile"]
    assert len(corporate) == 3
    assert {c["category_scope"] for c in corporate} == {CAT_1, CAT_2, CAT_3}
    assert {c["weight"] for c in corporate} == {"5", "10"}
    assert len({c["canonical_id"] for c in corporate}) == 3


def test_scope_specialist_cannot_consume_response_prompt_objects(package):
    payload = fa.build_specialist_input(package, fa.SPECIALIST_SCOPE_DELIVERABLES)
    assert fa.OBJ_SCOPED_EVALUATION_CRITERION not in payload["objects"]
    prompt = fa._build_specialist_prompt(fa.SPECIALIST_SCOPE_DELIVERABLES, payload)
    assert "response_prompt" not in prompt
    for item in payload["objects"][fa.OBJ_CATEGORY_SCOPE_ITEM]:
        assert item["semantic_type"] in canon.SCOPE_SEMANTIC_TYPES


def test_response_prompt_material_is_type_gated_out_of_scope_items():
    """Even if upstream material claiming to be scope is really an
    evaluation instruction, the agent boundary rejects it."""
    result = make_result(category_scope_items={
        CAT_1: [{"text": "Proponents are to describe their approach to curriculum design "
                         "and demonstrate their instructional methodology.",
                 "semantic_type": canon.SEMANTIC_SCOPE_ITEM, "source_doc": MAIN_RFP}]})
    pkg = fa.build_canonical_package(result, bid_id=8)
    assert pkg.category_scope_items == ()


def test_scope_categories_stay_separated(package):
    payload = fa.build_specialist_input(package, fa.SPECIALIST_SCOPE_DELIVERABLES)
    by_cat = {}
    for item in payload["objects"][fa.OBJ_CATEGORY_SCOPE_ITEM]:
        by_cat.setdefault(item["category_scope"], []).append(item["text"])
    assert set(by_cat) == {CAT_1, CAT_2, CAT_3}
    assert "curriculum design" in by_cat[CAT_1][0]
    assert "organizational design" in by_cat[CAT_2][0]
    assert "facilitation of team effectiveness" in by_cat[CAT_3][0]


def test_requirements_specialist_preserves_category_applicability(package):
    payload = fa.build_specialist_input(package, fa.SPECIALIST_REQUIREMENTS_COMPLIANCE)
    reqs = list(payload["objects"][fa.OBJ_CANONICAL_REQUIREMENT])
    bilingual = next(r for r in reqs if "bilingualism" in r["description"])
    assert bilingual["applicability"] == canon.APPLICABILITY_CATEGORY_SPECIFIC
    assert list(bilingual["applicable_category_ids"]) == ["CATEGORY 2"]
    accessibility = next(r for r in reqs if "WCAG" in r["description"])
    assert accessibility["applicability"] == canon.APPLICABILITY_ALL_CATEGORIES


def test_commercial_specialist_consumes_typed_canonical_obligations(package):
    payload = fa.build_specialist_input(package, fa.SPECIALIST_COMMERCIAL_CONTRACTUAL)
    topics = {o["heading"]: o["topic"] for o in payload["objects"][fa.OBJ_COMMERCIAL_OBLIGATION]}
    # CI-1 Defect G: an Assignment clause is not misbound to Indemnity.
    assert topics["Assignment"] == canon.TOPIC_ASSIGNMENT
    assert topics["Indemnity"] == canon.TOPIC_INDEMNITY
    assert topics["Pricing"] == canon.TOPIC_PRICING_ESCALATION


def test_schedule_specialist_treats_category_demos_as_distinct_not_conflicting(package):
    payload = fa.build_specialist_input(package, fa.SPECIALIST_SCHEDULE_SUBMISSION)
    demos = [m for m in payload["objects"][fa.OBJ_SCOPED_MILESTONE]]
    assert len(demos) == 2
    assert {tuple(m["scope_key"]) for m in demos} == {("CATEGORY 1",), ("CATEGORY 3",)}
    assert all(m["ambiguity_state"] == "resolved" for m in demos)
    prompt = fa._build_specialist_prompt(fa.SPECIALIST_SCHEDULE_SUBMISSION, payload)
    assert "is NOT a conflict" in prompt


# ═══════════════════════════════════════════════════════════════════════
# 4. Typed findings and interpretation-vs-fact separation (section 10)
# ═══════════════════════════════════════════════════════════════════════

def test_interpretation_is_never_presented_as_fact(package):
    permitted = fa.slice_canonical_ids(
        fa.build_specialist_input(package, fa.SPECIALIST_EVALUATION_INTELLIGENCE))
    accepted, _ = fa.validate_findings(
        [finding(fa.FINDING_INTERPRETATION, "Points likely concentrate here", []),
         finding(fa.FINDING_FACT, "Corporate Profile is worth 5", [sorted(permitted)[0]])],
        permitted, produced_by="E")
    interpretation = accepted[0]
    assert interpretation["authority"] == fa.AUTHORITY_SPECIALIST
    assert interpretation["support_status"] == fa.SUPPORT_UNSUPPORTED
    assert interpretation["human_confirmation_required"] is True
    assert accepted[1]["authority"] == fa.AUTHORITY_CANONICAL


def test_canonical_procurement_mechanic_reaches_the_structure_specialist(package):
    """The buyer's own statement of the contracting model (multi-vendor
    call-off) is canonical Layer-2 material and must be interpretable by
    the Procurement Structure specialist -- without that specialist ever
    reading a document."""
    mechanics = package.identity["procurement_mechanics"]
    assert [m["statement"] for m in mechanics] == ["multi-vendor call-off arrangement"]
    prompt = fa._build_specialist_prompt(
        fa.SPECIALIST_PROCUREMENT_STRUCTURE,
        fa.build_specialist_input(package, fa.SPECIALIST_PROCUREMENT_STRUCTURE))
    assert "multi-vendor call-off arrangement" in prompt
    # and it is NOT leaked into a domain that has no business with it
    scope_prompt = fa._build_specialist_prompt(
        fa.SPECIALIST_COMMERCIAL_CONTRACTUAL,
        fa.build_specialist_input(package, fa.SPECIALIST_COMMERCIAL_CONTRACTUAL))
    assert "procurement_mechanics" in scope_prompt  # identity object is shared
    assert fa.OBJ_SCOPED_MILESTONE not in fa.SPECIALIST_INPUT_TYPES[
        fa.SPECIALIST_COMMERCIAL_CONTRACTUAL]


def test_every_specialist_prompt_states_the_closed_finding_taxonomy(package):
    for specialist_id in fa.SPECIALIST_IDS:
        prompt = fa._build_specialist_prompt(
            specialist_id, fa.build_specialist_input(package, specialist_id))
        for finding_type in fa.FINDING_TYPES:
            assert finding_type in prompt
        assert "is DISCARDED" in prompt


def test_unknown_finding_type_is_rejected_not_bucketed(package):
    accepted, rejected = fa.validate_findings(
        [finding("OPINION", "Not in the taxonomy", [])], {"REQ-0"}, produced_by="X")
    assert accepted == []
    assert rejected[0]["reason"] == "UNKNOWN_FINDING_TYPE"


# ═══════════════════════════════════════════════════════════════════════
# 5. Orchestration, parallelism, failure isolation (sections 11 / 14)
# ═══════════════════════════════════════════════════════════════════════

def _payload_for(prompt: str) -> dict:
    """Scripted specialist output: each specialist cites the first canonical
    id that appears in its own prompt, so findings are genuinely grounded
    in that specialist's own slice."""
    ids = sorted(set(__import__("re").findall(r'"canonical_id": "([A-Z0-9][^"]*)"', prompt)))
    if "RECONCILIATION" in prompt:
        return {"cross_domain_risks": [
                    {"title": "Schedule and evaluation interact", "detail": "d",
                     "severity": "HIGH", "domains": [fa.SPECIALIST_SCHEDULE_SUBMISSION],
                     "canonical_ids": [ids[0]] if ids else [], "finding_ids": []}],
                "contradictions": [],
                "unresolved_ambiguities": [],
                "human_confirmation_required": [],
                "completeness_note": "All domains reported."}
    return {"findings": [finding(fa.FINDING_FACT, "Grounded fact", ids[:3]),
                         finding(fa.FINDING_RISK, "Grounded risk", ids[:3]),
                         finding(fa.FINDING_INTERPRETATION, "Analytical read", [])]}


def test_full_analysis_makes_exactly_seven_bounded_calls(package):
    client = MockClient(payload_for=_payload_for)
    result = fa.run_full_analysis(package, client=client)
    assert len(client.prompts) == 7                      # 6 specialists + 1 reconciliation
    assert result.usage["total_calls"] == 7
    assert result.completeness_status == fa.COMPLETENESS_COMPLETE
    assert set(result.specialist_statuses) == set(fa.SPECIALIST_IDS)
    assert set(result.specialist_statuses.values()) == {fa.STATUS_COMPLETE}
    assert result.canonical_snapshot_digest == package.package_digest
    assert result.analysis_version == fa.FULL_ANALYSIS_VERSION


def test_no_specialist_receives_the_whole_package(package):
    client = MockClient(payload_for=_payload_for)
    fa.run_full_analysis(package, client=client)
    specialist_prompts = [p for p in client.prompts if "RECONCILIATION" not in p]
    assert len(specialist_prompts) == 6
    for prompt in specialist_prompts:
        present = [t for t in fa.CANONICAL_OBJECT_TYPES if f'"{t}"' in prompt or f"'{t}'" in prompt]
        assert len(present) < len(fa.CANONICAL_OBJECT_TYPES)
    # Token discipline: no specialist prompt is anywhere near a whole-package prompt.
    whole = json.dumps({t: [dict(o) for o in package.objects_of_type(t)]
                        for t in fa.CANONICAL_OBJECT_TYPES}, default=str)
    assert max(len(p) for p in specialist_prompts) < len(whole)


def test_bounded_concurrency_and_zero_retries(package):
    assert fa.SPECIALIST_RETRY_ATTEMPTS == 0
    assert 1 <= fa.MAX_SPECIALIST_CONCURRENCY <= len(fa.SPECIALIST_IDS)
    client = MockClient(payload_for=_payload_for)
    result = fa.run_full_analysis(package, client=client, max_concurrency=2)
    # exactly one call per specialist: no silent retry, no cascade
    for spec in result.specialist_results:
        assert spec["usage"]["calls"] == 1


def test_one_specialist_failure_does_not_destroy_other_outputs(package):
    client = MockClient(payload_for=_payload_for, fail_for=("COMMERCIAL & CONTRACTUAL specialist",))
    result = fa.run_full_analysis(package, client=client)
    statuses = result.specialist_statuses
    assert statuses[fa.SPECIALIST_COMMERCIAL_CONTRACTUAL] == fa.STATUS_FAILED
    assert all(v == fa.STATUS_COMPLETE for k, v in statuses.items()
               if k != fa.SPECIALIST_COMMERCIAL_CONTRACTUAL)
    assert result.completeness_status == fa.COMPLETENESS_PARTIAL
    survivors = [s for s in result.specialist_results
                 if s["specialist_id"] != fa.SPECIALIST_COMMERCIAL_CONTRACTUAL]
    assert all(s["findings"] for s in survivors)


def test_failed_specialist_is_not_substituted_with_generic_reasoning(package):
    client = MockClient(payload_for=_payload_for, fail_for=("COMMERCIAL & CONTRACTUAL specialist",))
    result = fa.run_full_analysis(package, client=client)
    failed = next(s for s in result.specialist_results
                  if s["specialist_id"] == fa.SPECIALIST_COMMERCIAL_CONTRACTUAL)
    assert failed["findings"] == []
    assert failed["confidence"] == "NONE"
    assert "simulated provider failure" in failed["failure_reason"]


def test_reconciliation_marks_incomplete_domain(package):
    client = MockClient(payload_for=_payload_for, fail_for=("COMMERCIAL & CONTRACTUAL specialist",))
    result = fa.run_full_analysis(package, client=client)
    incomplete = result.reconciliation["incomplete_domains"]
    assert [d["specialist_id"] for d in incomplete] == [fa.SPECIALIST_COMMERCIAL_CONTRACTUAL]
    # and the reconciliation stage is TOLD the domain is incomplete
    reconciliation_prompt = next(p for p in client.prompts if "RECONCILIATION" in p)
    payload = json.loads(reconciliation_prompt.split("CANONICAL INDEX:\n", 1)[1])
    commercial = next(d for d in payload["domains"]
                      if d["specialist_id"] == fa.SPECIALIST_COMMERCIAL_CONTRACTUAL)
    assert commercial["domain_complete"] is False
    assert any(g["title"].startswith("Incomplete domain") for g in result.unresolved_gaps)


def test_full_analysis_never_claims_complete_when_a_domain_failed(package):
    client = MockClient(payload_for=_payload_for, fail_for=("EVALUATION INTELLIGENCE specialist",))
    result = fa.run_full_analysis(package, client=client)
    assert result.completeness_status != fa.COMPLETENESS_COMPLETE


# ═══════════════════════════════════════════════════════════════════════
# 6. Reconciliation behavior (section 13)
# ═══════════════════════════════════════════════════════════════════════

def test_reconciliation_never_rereads_the_rfp(package):
    client = MockClient(payload_for=_payload_for)
    fa.run_full_analysis(package, client=client)
    reconciliation_prompt = next(p for p in client.prompts if "RECONCILIATION" in p)
    assert "[[SOURCE:" not in reconciliation_prompt
    payload = json.loads(reconciliation_prompt.split("CANONICAL INDEX:\n", 1)[1])
    # index carries ids/labels only -- no clause text, no response prompts
    serialized = json.dumps(payload["canonical_index"])
    assert "indemnify and save harmless" not in serialized
    assert "Proponents are to describe" not in serialized


def test_duplicate_specialist_findings_are_consolidated(package):
    a = fa.SpecialistResult(specialist_id=fa.SPECIALIST_EVALUATION_INTELLIGENCE)
    b = fa.SpecialistResult(specialist_id=fa.SPECIALIST_REQUIREMENTS_COMPLIANCE)
    common = {"finding_type": fa.FINDING_RISK, "title": "Bilingual delivery capacity is a risk",
              "detail": "d", "canonical_ids": ["REQ-0"], "category_scope": "",
              "severity": "HIGH", "support_status": fa.SUPPORT_CANONICAL,
              "authority": fa.AUTHORITY_SPECIALIST, "human_confirmation_required": False,
              "rejected_canonical_ids": []}
    a.findings = [dict(common, finding_id="E:0", produced_by=[a.specialist_id])]
    b.findings = [dict(common, finding_id="R:0", produced_by=[b.specialist_id],
                       canonical_ids=["REQ-1"])]
    merged, duplicates = fa.consolidate_findings([a, b])
    assert len(merged) == 1
    assert sorted(merged[0]["produced_by"]) == sorted(
        [fa.SPECIALIST_EVALUATION_INTELLIGENCE, fa.SPECIALIST_REQUIREMENTS_COMPLIANCE])
    assert sorted(merged[0]["canonical_ids"]) == ["REQ-0", "REQ-1"]
    assert len(duplicates) == 1


def test_consolidation_never_merges_across_categories(package):
    a = fa.SpecialistResult(specialist_id=fa.SPECIALIST_EVALUATION_INTELLIGENCE)
    common = {"finding_type": fa.FINDING_RISK, "title": "Corporate Profile evidence burden",
              "detail": "d", "canonical_ids": ["CRIT-x"], "severity": "HIGH",
              "support_status": fa.SUPPORT_CANONICAL, "authority": fa.AUTHORITY_SPECIALIST,
              "human_confirmation_required": False, "rejected_canonical_ids": []}
    a.findings = [dict(common, finding_id="E:0", category_scope=CAT_1, produced_by=["E"]),
                  dict(common, finding_id="E:1", category_scope=CAT_3, produced_by=["E"])]
    merged, _ = fa.consolidate_findings([a])
    assert len(merged) == 2


def test_reconciliation_preserves_canonical_authority_over_agent_interpretation(package):
    """A specialist FACT that assigns a canonical Category 3 criterion to
    Category 1 is demoted -- canonical scope wins, and the demotion is
    recorded rather than silently applied."""
    criterion = next(c for c in package.scoped_criteria if c["category_scope"] == CAT_3)
    spec = fa.SpecialistResult(specialist_id=fa.SPECIALIST_EVALUATION_INTELLIGENCE)
    spec.findings = [{
        "finding_id": "E:0", "finding_type": fa.FINDING_FACT,
        "title": "Corporate Profile is scored under Category 1", "detail": "d",
        "canonical_ids": [criterion["canonical_id"]], "category_scope": CAT_1,
        "severity": "MEDIUM", "support_status": fa.SUPPORT_CANONICAL,
        "authority": fa.AUTHORITY_CANONICAL, "human_confirmation_required": False,
        "rejected_canonical_ids": [], "produced_by": [spec.specialist_id]}]
    merged, overrides = fa.enforce_canonical_authority(
        fa.consolidate_findings([spec])[0], package)
    assert merged[0]["authority"] == fa.AUTHORITY_SPECIALIST
    assert merged[0]["human_confirmation_required"] is True
    assert overrides[0]["canonical_categories"] == [CAT_3]


def test_reconciliation_does_not_majority_vote_facts(package):
    """Three specialists asserting the same wrong category still lose to
    canonical scope -- agreement count is never consulted."""
    criterion = next(c for c in package.scoped_criteria if c["category_scope"] == CAT_3)
    specs = []
    for i, sid in enumerate(fa.SPECIALIST_IDS[:3]):
        spec = fa.SpecialistResult(specialist_id=sid)
        spec.findings = [{
            "finding_id": f"{sid}:0", "finding_type": fa.FINDING_FACT,
            "title": "Corporate Profile sits in Category 1", "detail": "d",
            "canonical_ids": [criterion["canonical_id"]], "category_scope": CAT_1,
            "severity": "MEDIUM", "support_status": fa.SUPPORT_CANONICAL,
            "authority": fa.AUTHORITY_CANONICAL, "human_confirmation_required": False,
            "rejected_canonical_ids": [], "produced_by": [sid]}]
        specs.append(spec)
    merged, overrides = fa.enforce_canonical_authority(fa.consolidate_findings(specs)[0], package)
    assert len(merged) == 1 and overrides
    assert merged[0]["authority"] == fa.AUTHORITY_SPECIALIST


def test_reconciliation_surfaces_orphaned_requirements(package):
    spec = fa.SpecialistResult(specialist_id=fa.SPECIALIST_REQUIREMENTS_COMPLIANCE)
    spec.status = fa.STATUS_COMPLETE
    spec.findings = [{"finding_id": "R:0", "finding_type": fa.FINDING_FACT, "title": "t",
                      "detail": "d", "canonical_ids": ["REQ-0"], "category_scope": "",
                      "severity": "LOW", "support_status": fa.SUPPORT_CANONICAL,
                      "authority": fa.AUTHORITY_CANONICAL,
                      "human_confirmation_required": False, "rejected_canonical_ids": [],
                      "produced_by": ["R"]}]
    orphans = fa.detect_orphaned_requirements(package, [spec])
    assert {o["canonical_id"] for o in orphans} == {"REQ-1", "REQ-2"}


def test_reconciliation_model_failure_preserves_deterministic_assurance(package):
    client = MockClient(payload_for=_payload_for, fail_for=("RECONCILIATION",))
    result = fa.run_full_analysis(package, client=client)
    assert result.reconciliation["status"] == fa.STATUS_FAILED
    assert result.reconciled_findings                 # specialist work survives
    assert result.completeness_status == fa.COMPLETENESS_PARTIAL


def test_reconciliation_output_citing_unknown_ids_is_dropped(package):
    def payload(prompt):
        if "RECONCILIATION" in prompt:
            return {"cross_domain_risks": [
                        {"title": "Invented", "detail": "d", "severity": "HIGH",
                         "domains": [], "canonical_ids": ["REQ-31337"], "finding_ids": []}],
                    "contradictions": [], "unresolved_ambiguities": [],
                    "human_confirmation_required": [], "completeness_note": "n"}
        return {"findings": []}
    client = MockClient(payload_for=payload)
    result = fa.run_full_analysis(package, client=client)
    assert result.cross_domain_risks == []


def test_evaluation_vs_scope_mismatch_is_detected():
    result = make_result(category_scope_items={CAT_1: [
        {"text": "The Contractor shall provide curriculum design services for leadership "
                 "programs across the enterprise.",
         "semantic_type": canon.SEMANTIC_SCOPE_ITEM, "source_doc": MAIN_RFP}]})
    pkg = fa.build_canonical_package(result, bid_id=8)
    mismatches = fa.detect_evaluation_scope_mismatches(pkg)
    assert {m["category"] for m in mismatches} == {CAT_2, CAT_3}
    assert all(m["issue"] == "EVALUATED_CATEGORY_WITH_NO_CANONICAL_SCOPE_ITEMS"
               for m in mismatches)


def test_category_scope_inconsistency_is_detected(package):
    spec = fa.SpecialistResult(specialist_id=fa.SPECIALIST_EVALUATION_INTELLIGENCE)
    spec.findings = [{"finding_id": "E:0", "finding_type": fa.FINDING_RISK, "title": "t",
                      "detail": "d", "canonical_ids": [], "category_scope": "Category 9",
                      "severity": "LOW", "support_status": fa.SUPPORT_CANONICAL,
                      "authority": fa.AUTHORITY_SPECIALIST,
                      "human_confirmation_required": False, "rejected_canonical_ids": [],
                      "produced_by": ["E"]}]
    issues = fa.detect_category_scope_inconsistencies(package, [spec])
    assert issues[0]["issue"] == "CATEGORY_NOT_CANONICAL"


# ═══════════════════════════════════════════════════════════════════════
# 7. Full Analysis result contract (section 15) and Fast Analysis isolation
# ═══════════════════════════════════════════════════════════════════════

def test_full_analysis_result_carries_the_required_contract(package):
    client = MockClient(payload_for=_payload_for)
    result = fa.run_full_analysis(package, client=client).as_dict()
    for key in ("bid_id", "analysis_version", "canonical_snapshot_digest",
                "specialist_statuses", "specialist_results", "reconciliation",
                "reconciled_findings", "unresolved_gaps", "cross_domain_risks",
                "ambiguities", "completeness_status", "human_confirmation_required",
                "source_refs", "wall_seconds", "usage", "telemetry"):
        assert key in result, key
    assert result["bid_id"] == 8
    assert result["source_refs"]
    json.dumps(result)                                   # JSON-safe end to end


def test_specialist_result_carries_the_shared_contract(package):
    client = MockClient(payload_for=_payload_for)
    spec = fa.run_full_analysis(package, client=client).specialist_results[0]
    for key in ("specialist_id", "specialist_version", "bid_id", "input_digest",
                "canonical_objects_consumed", "findings", "risks", "ambiguities",
                "gaps", "attention_items", "source_refs", "confidence",
                "human_confirmation_required", "status", "duration_seconds", "usage"):
        assert key in spec, key
    assert spec["specialist_version"] == fa.SPECIALIST_VERSION
    assert spec["usage"]["input_tokens"] > 0


def test_token_discipline_is_measured_per_specialist(package):
    client = MockClient(payload_for=_payload_for)
    result = fa.run_full_analysis(package, client=client)
    by_specialist = result.usage["by_specialist"]
    assert set(by_specialist) == set(fa.SPECIALIST_IDS)
    for usage in by_specialist.values():
        assert usage["request_bytes"] > 0 and usage["calls"] == 1
    for row in result.telemetry:
        assert row["model"] == fa.FULL_ANALYSIS_MODEL
        assert row["provider_call_attempted"] is True
        assert row["latency_seconds"] >= 0


def test_fast_analysis_remains_unaffected():
    """Full Analysis is an explicit, separate mode: the Fast Analysis
    engine neither imports nor dispatches any specialist work."""
    import fast_analysis
    import analysis_service
    fast_source = open(fast_analysis.__file__, encoding="utf-8").read()
    assert "full_analysis" not in fast_source
    assert "import full_analysis" not in open(
        analysis_service.__file__, encoding="utf-8").read().split(
        "def run_full_analysis_for_run")[0]
    assert analysis_service.FAST_ANALYSIS_ENGINE_VERSION == "fast-analysis-v4"
    assert fast_analysis.FAST_MODEL == "claude-haiku-4-5-20251001"
