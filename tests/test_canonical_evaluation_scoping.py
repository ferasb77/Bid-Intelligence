"""
CI-1.1: Canonical Evaluation Prompt Scoping + Scope Extraction Coverage.

Two material gaps CI-1 left open:

  1. `deterministic_criterion_response_prompts` was keyed by the criterion
     LABEL alone, so a label a buyer scores independently in several
     service categories collapsed to whichever document/section happened
     to be scanned first.
  2. Category scope was correct-but-empty: CI-1 stopped evaluation prompts
     from masquerading as scope but added no positive, source-grounded
     SOW/service-scope extraction.

Every test here is fully deterministic and synthetic: no live provider
call, no live database, no file I/O. The Bank of Canada-shaped fixtures
reproduce the real corpus's STRUCTURE (three "Appendix D<n>" categories
sharing criterion labels such as "Corporate Profile") from inline text,
never from the live corpus.
"""
from __future__ import annotations

import canonical_procurement as canon
import procurement_normalization as pn


# ---------------------------------------------------------------------------
# Fixtures: one document shaped like a real multi-category rated-criteria
# response form -- three category headings, overlapping criterion labels.
# ---------------------------------------------------------------------------

CAT_1 = "Appendix D1 – Learning & Development Programs and Assessments"
CAT_2 = "Appendix D2 - HR Advisory"
CAT_3 = "Appendix D3 – Facilitation and Team Effectiveness"

MULTI_CATEGORY_RESPONSE_FORM = f"""
{CAT_1}

Corporate Profile
Proponents are to describe their organisation's learning and development
practice, including the number of years delivering curriculum design.

Curriculum & Program Design Capability
Proponents must demonstrate their instructional design methodology and
provide two examples of curricula designed for a central bank. Attach
curriculum vitae for the named designers. Responses must not exceed 5 pages.

{CAT_2}

Corporate Profile
Proponents are to describe their HR advisory practice, including the
advisory engagements completed in the last three years.

Methodology and Advisory Approach
Proponents must outline their advisory methodology and framework.

Thought Leadership & Innovation
Proponents should describe their published thought leadership.

{CAT_3}

Corporate Profile
Proponents are to describe their facilitation practice and its governance.

Facilitation Methodology
Proponents must explain their facilitation methodology and provide
examples of team effectiveness sessions facilitated remotely.

Price
Proponents are to submit the pricing schedule.
"""

SOW_DOCUMENT = f"""
{CAT_1}

The services will include the design, development and delivery of
leadership curricula, learning needs assessments, and the updating of
existing programs on an annual basis.

{CAT_2}

The Contractor will provide organisational design advice, compensation
review support and change-management advisory services on a call-off
basis.

{CAT_3}

Proponents are to describe their facilitation practice in detail and
demonstrate how they would run a session.
"""

KNOWN_LABELS = [
    "Corporate Profile", "Curriculum & Program Design Capability",
    "Methodology and Advisory Approach", "Thought Leadership & Innovation",
    "Facilitation Methodology", "Price",
]
KNOWN_CATEGORIES = [CAT_1, CAT_2, CAT_3]


def _scoped_prompts(doc_text=MULTI_CATEGORY_RESPONSE_FORM):
    return pn.extract_scoped_criterion_response_prompts(
        doc_text, KNOWN_LABELS, KNOWN_CATEGORIES)


def _occurrences():
    return [
        {"criterion_label": "Corporate Profile", "weight": "5 points",
         "category_scope": CAT_1, "source_doc": "RFP 2026-026.pdf", "source_refs": ["p.12"]},
        {"criterion_label": "Curriculum & Program Design Capability", "weight": "35 points",
         "category_scope": CAT_1, "source_doc": "RFP 2026-026.pdf"},
        {"criterion_label": "Corporate Profile", "weight": "5 points",
         "category_scope": CAT_2, "source_doc": "RFP 2026-026.pdf"},
        {"criterion_label": "Methodology and Advisory Approach", "weight": "35 points",
         "category_scope": CAT_2, "source_doc": "RFP 2026-026.pdf"},
        {"criterion_label": "Thought Leadership & Innovation", "weight": "5 points",
         "category_scope": CAT_2, "source_doc": "RFP 2026-026.pdf"},
        {"criterion_label": "Corporate Profile", "weight": "10 points", "minimum_score": "6 points",
         "category_scope": CAT_3, "source_doc": "RFP 2026-026.pdf"},
        {"criterion_label": "Facilitation Methodology", "weight": "30 points",
         "category_scope": CAT_3, "source_doc": "RFP 2026-026.pdf"},
        {"criterion_label": "Price", "weight": "25 points",
         "category_scope": None, "source_doc": "RFP 2026-026.pdf"},
    ]


# ---------------------------------------------------------------------------
# 1. Scoped identity
# ---------------------------------------------------------------------------

class TestScopedCriterionIdentity:

    def test_same_label_in_three_categories_yields_three_keys(self):
        keys = {canon.scoped_criterion_map_key(c, "Corporate Profile")
                for c in (CAT_1, CAT_2, CAT_3)}
        assert len(keys) == 3

    def test_key_round_trips(self):
        key = canon.scoped_criterion_map_key(CAT_2, "Corporate Profile")
        cat, crit = canon.split_scoped_criterion_map_key(key)
        assert crit == "corporate profile"
        assert "d2" in cat

    def test_unscoped_criterion_keys_with_empty_category(self):
        assert canon.scoped_criterion_map_key(None, "Price").startswith("||")


class TestIdenticalLabelsRemainSeparate:

    def test_three_corporate_profile_prompts_survive(self):
        scoped = _scoped_prompts()
        corporate = {k: v for k, v in scoped.items() if v["criterion"] == "Corporate Profile"}
        assert len(corporate) == 3
        categories = sorted(v["category"] for v in corporate.values())
        assert categories == sorted([CAT_1, CAT_2, CAT_3])

    def test_label_keyed_extraction_demonstrates_the_collapse_being_fixed(self):
        """The pre-CI-1.1 label-keyed function keeps ONE entry for a label
        restated under three categories -- the exact defect."""
        flat = pn.extract_criterion_response_prompts(
            MULTI_CATEGORY_RESPONSE_FORM, KNOWN_LABELS)
        assert len([k for k in flat if k == "Corporate Profile"]) == 1
        assert len(_scoped_prompts()) > len(flat)

    def test_no_criterion_disappears_because_its_label_repeats(self):
        scoped = _scoped_prompts()
        found = {(v["category"], v["criterion"]) for v in scoped.values()}
        assert (CAT_1, "Curriculum & Program Design Capability") in found
        assert (CAT_2, "Methodology and Advisory Approach") in found
        assert (CAT_2, "Thought Leadership & Innovation") in found
        assert (CAT_3, "Facilitation Methodology") in found


class TestPromptsNeverOverwriteEachOther:

    def test_each_category_keeps_its_own_corporate_profile_text(self):
        scoped = _scoped_prompts()
        p1 = scoped[canon.scoped_criterion_map_key(CAT_1, "Corporate Profile")]["response_prompt"]
        p2 = scoped[canon.scoped_criterion_map_key(CAT_2, "Corporate Profile")]["response_prompt"]
        p3 = scoped[canon.scoped_criterion_map_key(CAT_3, "Corporate Profile")]["response_prompt"]
        assert "learning and development" in p1.lower()
        assert "hr advisory" in p2.lower()
        assert "facilitation" in p3.lower()
        assert len({p1, p2, p3}) == 3

    def test_body_never_bleeds_across_a_category_boundary(self):
        scoped = _scoped_prompts()
        p1 = scoped[canon.scoped_criterion_map_key(CAT_1, "Corporate Profile")]["response_prompt"]
        assert "hr advisory" not in p1.lower()

    def test_criterion_before_any_category_heading_stays_unscoped(self):
        text = "Corporate Profile\nProponents are to describe their firm.\n"
        scoped = pn.extract_scoped_criterion_response_prompts(
            text, KNOWN_LABELS, KNOWN_CATEGORIES)
        assert list(scoped) == ["||corporate profile"]
        assert scoped["||corporate profile"]["category"] == ""


class TestRequestedEvidenceStaysScoped:

    def test_records_carry_scoped_evidence_facets(self):
        records = pn.build_scoped_criterion_records(_occurrences(), _scoped_prompts())
        design = records[canon.scoped_criterion_map_key(
            CAT_1, "Curriculum & Program Design Capability")]
        assert design["required_examples"]
        assert design["personnel_requirements"]
        assert design["methodology_requirements"]
        assert design["constraints"]
        assert design["requested_evidence"]

        d2_profile = records[canon.scoped_criterion_map_key(CAT_2, "Corporate Profile")]
        assert not d2_profile["required_examples"]

    def test_evidence_elements_absent_when_prompt_does_not_state_them(self):
        facets = canon.extract_requested_evidence_elements(
            "Proponents are to describe their organisation.")
        assert facets["required_examples"] == []
        assert facets["constraints"] == []

    def test_retention_contract_fields_present(self):
        records = pn.build_scoped_criterion_records(_occurrences(), _scoped_prompts())
        rec = records[canon.scoped_criterion_map_key(CAT_3, "Corporate Profile")]
        for field in ("category_scope", "criterion", "weight", "minimum_score",
                      "response_prompt", "requested_evidence", "required_examples",
                      "personnel_requirements", "methodology_requirements",
                      "constraints", "authoritative_source", "provenance_version"):
            assert field in rec
        assert rec["weight"] == "10 points"
        assert rec["minimum_score"] == "6 points"

    def test_weights_stay_scoped_not_merged(self):
        records = pn.build_scoped_criterion_records(_occurrences(), _scoped_prompts())
        assert records[canon.scoped_criterion_map_key(CAT_1, "Corporate Profile")]["weight"] == "5 points"
        assert records[canon.scoped_criterion_map_key(CAT_3, "Corporate Profile")]["weight"] == "10 points"


class TestEvaluationAgentReadContract:

    def test_category_request_returns_only_that_category(self):
        records = pn.build_scoped_criterion_records(_occurrences(), _scoped_prompts())
        only_d2 = pn.criteria_for_category(records, CAT_2)
        assert only_d2
        assert all(r["category_scope"] == CAT_2 for r in only_d2)
        labels = sorted(r["criterion"] for r in only_d2)
        assert labels == ["Corporate Profile", "Methodology and Advisory Approach",
                          "Thought Leadership & Innovation"]

    def test_dash_variant_of_a_category_name_still_matches(self):
        records = pn.build_scoped_criterion_records(_occurrences(), _scoped_prompts())
        hyphenated = CAT_1.replace("–", "-")
        assert pn.criteria_for_category(records, hyphenated)


class TestAmendedCriterionSourceAuthority:

    def test_response_form_outranks_amendment_and_primary(self):
        occurrences = [
            {"criterion_label": "Corporate Profile", "weight": "5 points",
             "category_scope": CAT_1, "source_doc": "RFP 2026-026.pdf"},
            {"criterion_label": "Corporate Profile", "weight": "8 points",
             "category_scope": CAT_1, "source_doc": "RFP 2026-026 Addendum 2.pdf"},
            {"criterion_label": "Corporate Profile", "weight": "8 points",
             "category_scope": CAT_1, "source_doc": "Appendix D - Rated Criteria response form.pdf"},
        ]
        rec = pn.build_scoped_criterion_records(occurrences)[
            canon.scoped_criterion_map_key(CAT_1, "Corporate Profile")]
        assert rec["authoritative_source"] == "Appendix D - Rated Criteria response form.pdf"
        assert rec["authoritative_source_role"] == canon.IDENTITY_ROLE_RESPONSE_FORM

    def test_amendment_outranks_primary_when_no_response_form_exists(self):
        occurrences = [
            {"criterion_label": "Corporate Profile", "category_scope": CAT_1,
             "source_doc": "RFP 2026-026.pdf"},
            {"criterion_label": "Corporate Profile", "category_scope": CAT_1,
             "source_doc": "RFP 2026-026 Addendum 2.pdf"},
        ]
        rec = pn.build_scoped_criterion_records(occurrences)[
            canon.scoped_criterion_map_key(CAT_1, "Corporate Profile")]
        assert rec["authoritative_source_role"] == canon.IDENTITY_ROLE_AMENDMENT

    def test_conflicting_stated_weights_are_preserved_not_silently_resolved(self):
        occurrences = [
            {"criterion_label": "Corporate Profile", "weight": "5 points",
             "category_scope": CAT_1, "source_doc": "RFP 2026-026.pdf"},
            {"criterion_label": "Corporate Profile", "weight": "8 points",
             "category_scope": CAT_1, "source_doc": "RFP 2026-026 Addendum 2.pdf"},
        ]
        rec = pn.build_scoped_criterion_records(occurrences)[
            canon.scoped_criterion_map_key(CAT_1, "Corporate Profile")]
        assert rec["weight_variants"] == ["5 points", "8 points"]


# ---------------------------------------------------------------------------
# 2. Positive, source-grounded scope extraction
# ---------------------------------------------------------------------------

class TestResponsePromptNeverBecomesScope:

    def test_prompt_text_is_not_usable_as_scope(self):
        prompt = ("Proponents are to describe their organisation's learning and "
                  "development practice and the services they deliver.")
        assert canon.classify_semantic_type(prompt) == canon.SEMANTIC_RESPONSE_PROMPT
        assert not canon.is_usable_as_scope(prompt)

    def test_response_form_document_produces_no_scope_items(self):
        items = pn.extract_category_scope_items(
            [("Appendix D - Rated Criteria response form.pdf", MULTI_CATEGORY_RESPONSE_FORM)],
            KNOWN_CATEGORIES)
        assert all(not bucket for bucket in items.values()), items

    def test_scope_extraction_rejects_the_prompt_paragraph_inside_a_sow_document(self):
        items = pn.extract_category_scope_items(
            [("sow.pdf", SOW_DOCUMENT)], KNOWN_CATEGORIES)
        texts = [i["text"] for bucket in items.values() for i in bucket]
        assert not any("Proponents are to describe" in t for t in texts)

    def test_every_emitted_item_carries_a_scope_semantic_type(self):
        items = pn.extract_category_scope_items([("sow.pdf", SOW_DOCUMENT)], KNOWN_CATEGORIES)
        for bucket in items.values():
            for item in bucket:
                assert item["semantic_type"] in canon.SCOPE_SEMANTIC_TYPES


class TestRealSowTextProducesScopeItems:

    def test_categories_with_real_sow_prose_are_populated(self):
        items = pn.extract_category_scope_items([("sow.pdf", SOW_DOCUMENT)], KNOWN_CATEGORIES)
        assert pn.scope_items_for_category(items, CAT_1)
        assert pn.scope_items_for_category(items, CAT_2)
        assert "curricula" in pn.scope_items_for_category(items, CAT_1)[0]["text"]
        assert "advisory" in pn.scope_items_for_category(items, CAT_2)[0]["text"]

    def test_scope_agent_read_contract_is_category_isolated(self):
        items = pn.extract_category_scope_items([("sow.pdf", SOW_DOCUMENT)], KNOWN_CATEGORIES)
        for item in pn.scope_items_for_category(items, CAT_2):
            assert item["category_scope"] == CAT_2
            assert "curricula" not in item["text"]

    def test_scope_items_carry_their_source_document(self):
        items = pn.extract_category_scope_items([("sow.pdf", SOW_DOCUMENT)], KNOWN_CATEGORIES)
        assert all(i["source_doc"] == "sow.pdf"
                   for i in pn.scope_items_for_category(items, CAT_1))


#: The other real-world SOW convention: a "Statement of work" section
#: whose service categories are named by ORDINAL ("CATEGORY 2: ...") while
#: the evaluation tables name the same categories by form id ("Appendix
#: D2 - ..."), with the services themselves stated as enumerated items.
ORDINAL_SOW_DOCUMENT = """
4.1 Statement of work

The Bank may require services including but not limited to the following:

CATEGORY 1: LEARNING & DEVELOPMENT PROGRAMS AND ASSESSMENTS
Requirements
▪ Bank-wide leadership and management development programmes
▪ Custom curriculum and instructional design

CATEGORY 2: HR ADVISORY
Requirements
▪ Competency framework development and validation
▪ Succession planning design and facilitation

4.2 Rated criteria

Corporate Profile
Proponents are to describe their organisation and its services.
▪ Profile and history of the organisation
"""


class TestOrdinalSowConvention:

    def test_ordinal_headings_bind_to_the_form_identified_category(self):
        items = pn.extract_category_scope_items(
            [("rfp.pdf", ORDINAL_SOW_DOCUMENT)], KNOWN_CATEGORIES)
        d1 = [i["text"] for i in pn.scope_items_for_category(items, CAT_1)]
        d2 = [i["text"] for i in pn.scope_items_for_category(items, CAT_2)]
        assert any("instructional design" in t for t in d1)
        assert any("Competency framework" in t for t in d2)
        assert not any("Competency framework" in t for t in d1)

    def test_enumerated_services_are_typed_as_services(self):
        items = pn.extract_category_scope_items(
            [("rfp.pdf", ORDINAL_SOW_DOCUMENT)], KNOWN_CATEGORIES)
        assert all(i["semantic_type"] == canon.SEMANTIC_SERVICE
                   for i in pn.scope_items_for_category(items, CAT_2))

    def test_bullets_after_the_rated_criteria_heading_are_not_scope(self):
        items = pn.extract_category_scope_items(
            [("rfp.pdf", ORDINAL_SOW_DOCUMENT)], KNOWN_CATEGORIES)
        texts = [i["text"] for bucket in items.values() for i in bucket]
        assert not any("Profile and history" in t for t in texts)

    def test_scoring_table_and_certification_boilerplate_are_rejected(self):
        doc = """
4.1 Statement of work

CATEGORY 1: LEARNING
Corporate Profile 5 points Key Personnel and Roster 15 points Curriculum 35 points
The proponent certifies that it has a clear knowledge of the statement of work required.
The Bank is under no obligation to award a contract and may alter the scope of the
statement of work at any time during the RFP process.
"""
        items = pn.extract_category_scope_items([("rfp.pdf", doc)], KNOWN_CATEGORIES)
        assert pn.scope_items_for_category(items, CAT_1) == []


class TestScopeStaysEmptyRatherThanFabricated:

    def test_category_with_only_evaluation_material_stays_empty(self):
        items = pn.extract_category_scope_items(
            [("form.pdf", MULTI_CATEGORY_RESPONSE_FORM)], KNOWN_CATEGORIES)
        assert pn.scope_items_for_category(items, CAT_3) == []

    def test_summary_reports_unavailable_when_nothing_qualifies(self):
        weights = {CAT_3: [{"criterion": "Corporate Profile", "weight": "10 points"}]}
        summaries = pn.derive_category_scope_summaries(
            weights, _scoped_prompts(), None, {})
        assert summaries[CAT_3]["summary_available"] is False
        assert summaries[CAT_3]["source_scope_items"] == []
        # The rejected prompt is preserved, correctly labelled -- not discarded.
        assert summaries[CAT_3]["response_prompts_not_scope"]

    def test_summary_becomes_available_with_genuine_source_scope(self):
        weights = {CAT_1: [{"criterion": "Corporate Profile", "weight": "5 points"}]}
        items = pn.extract_category_scope_items([("sow.pdf", SOW_DOCUMENT)], KNOWN_CATEGORIES)
        summaries = pn.derive_category_scope_summaries(weights, _scoped_prompts(), None, items)
        assert summaries[CAT_1]["summary_available"] is True
        assert summaries[CAT_1]["source_scope_items"]

    def test_summary_uses_this_categorys_own_scoped_prompt(self):
        weights = {CAT_2: [{"criterion": "Corporate Profile", "weight": "5 points"}]}
        summaries = pn.derive_category_scope_summaries(weights, _scoped_prompts(), None, {})
        rejected = summaries[CAT_2]["response_prompts_not_scope"]
        assert len(rejected) == 1
        assert "hr advisory" in rejected[0]["response_prompt"].lower()


# ---------------------------------------------------------------------------
# 3. End-to-end wiring through FastAnalysisResult and its consumers
# ---------------------------------------------------------------------------

def _wired_result():
    """A FastAnalysisResult populated exactly the way run_fast_analysis_corpus
    step 5 populates it, without running the engine (no provider call)."""
    from fast_analysis import FastAnalysisResult

    result = FastAnalysisResult()
    result.evaluation_occurrences = _occurrences()
    result.scoped_criterion_response_prompts = _scoped_prompts()
    for label, entry in pn.extract_criterion_response_prompts(
            MULTI_CATEGORY_RESPONSE_FORM, KNOWN_LABELS).items():
        result.deterministic_criterion_response_prompts[label] = entry
    result.scoped_criterion_evaluation = pn.build_scoped_criterion_records(
        result.evaluation_occurrences, result.scoped_criterion_response_prompts)
    result.category_scope_items = pn.extract_category_scope_items(
        [("sow.pdf", SOW_DOCUMENT)], KNOWN_CATEGORIES)
    return result


class TestFastAnalysisResultWiring:

    def test_snapshot_round_trip_preserves_the_new_fields(self):
        import fast_analysis as fa

        payload = fa.serialize_fast_analysis_result(_wired_result(), engine_version="test")
        assert payload["schema_version"] == "1.2"
        restored = fa.deserialize_fast_analysis_result(payload)
        assert restored.scoped_criterion_response_prompts == _wired_result().scoped_criterion_response_prompts
        assert restored.scoped_criterion_evaluation
        assert restored.category_scope_items

    def test_older_snapshot_without_the_new_fields_still_deserializes(self):
        import fast_analysis as fa

        payload = fa.serialize_fast_analysis_result(_wired_result(), engine_version="test")
        for removed in ("scoped_criterion_response_prompts", "scoped_criterion_evaluation",
                        "category_scope_items"):
            payload["result"].pop(removed)
        payload["schema_version"] = "1.1"
        restored = fa.deserialize_fast_analysis_result(payload)
        assert restored.scoped_criterion_response_prompts == {}
        assert restored.category_scope_items == {}

    def test_app_adapter_attaches_this_occurrences_own_prompt(self):
        import fast_analysis_app_adapter as app_adapter

        result = _wired_result()
        by_scope = {}
        for occ in result.evaluation_occurrences:
            if occ["criterion_label"] != "Corporate Profile":
                continue
            entry = app_adapter._scoped_prompt_entry(result, occ)
            by_scope[occ["category_scope"]] = entry.get("response_prompt")
        assert "learning and development" in by_scope[CAT_1].lower()
        assert "hr advisory" in by_scope[CAT_2].lower()
        assert "facilitation" in by_scope[CAT_3].lower()

    def test_app_adapter_never_falls_back_across_categories(self):
        """A scoped MISS must yield nothing -- never another category's
        prompt via the legacy label-keyed map."""
        import fast_analysis_app_adapter as app_adapter

        result = _wired_result()
        result.scoped_criterion_response_prompts.pop(
            canon.scoped_criterion_map_key(CAT_2, "Corporate Profile"))
        entry = app_adapter._scoped_prompt_entry(
            result, {"criterion_label": "Corporate Profile", "category_scope": CAT_2})
        assert entry == {}

    def test_report_rg_evidence_map_is_category_scoped(self):
        import scripts.fast_analysis_report_adapter as report_adapter

        result = _wired_result()
        rows_d1 = report_adapter._rg_evidence_map(
            result, [("Corporate Profile", "5 points")], category=CAT_1)
        rows_d2 = report_adapter._rg_evidence_map(
            result, [("Corporate Profile", "5 points")], category=CAT_2)
        assert "learning and development" in rows_d1[0][2].lower()
        assert "hr advisory" in rows_d2[0][2].lower()


# ---------------------------------------------------------------------------
# 4. Downstream regressions (Section Analyzer / PI-3A / PI-3D1)
# ---------------------------------------------------------------------------

class TestDownstreamConsumersUnaffected:

    def test_section_analyzer_still_matches_a_requirement_to_its_criterion(self):
        import section_analyzer

        criteria = [{"criterion_label": "Facilitation Methodology"},
                    {"criterion_label": "Methodology and Advisory Approach"}]
        matched = section_analyzer._match_evaluation_criterion(
            {"category": "Facilitation", "description":
             "Describe the facilitation methodology used for team sessions."},
            criteria)
        assert matched is not None
        assert matched["criterion_label"] == "Facilitation Methodology"

    def test_pi3a_drafting_brief_receives_scoped_criterion_and_evidence(self):
        import section_drafting

        records = pn.build_scoped_criterion_records(_occurrences(), _scoped_prompts())
        criterion = records[canon.scoped_criterion_map_key(
            CAT_1, "Curriculum & Program Design Capability")]
        brief = section_drafting.build_brief(
            organization_id="org-1", bid_id=8,
            requirement={"id": 1, "req_id": "R1", "category": "Learning",
                         "description": "Design and deliver leadership curricula.",
                         "source_refs": ["p.12"]},
            evaluation_criterion=criterion)
        assert brief.evaluation is not None
        # A scoped canonical record drops straight into PI-3A's existing
        # EvaluationContext -- no parallel evaluation model, and the weight
        # it carries is THIS category's, not another's.
        assert brief.evaluation.criterion_label == "Curriculum & Program Design Capability"
        assert brief.evaluation.weight == "35 points"
        # The scoped record itself retains the category and the typed
        # evidence facets the future Evaluation Agent reads.
        assert criterion["category_scope"] == CAT_1
        assert criterion["required_examples"]

    def test_pi3d1_outline_generation_still_works(self):
        import proposal_outline

        requirements = [
            {"id": 1, "req_id": "R1", "category": "Learning", "description": "Design curricula."},
            {"id": 2, "req_id": "R2", "category": "Learning", "description": "Deliver training."},
            {"id": 3, "req_id": "R3", "category": "Advisory", "description": "Provide advice."},
        ]
        sections = proposal_outline.derive_outline_sections(requirements)
        assert [s["title"] for s in sections][:1] == ["Learning"]
        assert sum(len(s["requirement_ids"]) for s in sections) == 3


class TestScoreCellIsNotAResponsePrompt:
    """A criterion label also appears as a row in the weights table, where
    the only text following it is that row's own score cell."""

    def test_weights_table_row_produces_no_prompt(self):
        doc = f"""
{CAT_2}

Methodology and Advisory Approach
35 points

Value-add
5 points

Presentations
PASS / FAIL
"""
        scoped = pn.extract_scoped_criterion_response_prompts(
            doc, KNOWN_LABELS + ["Value-add", "Presentations"], KNOWN_CATEGORIES)
        assert scoped == {}

    def test_a_genuine_prompt_that_mentions_points_is_kept(self):
        doc = f"""
{CAT_2}

Value-add
Proponents are to describe any additional value-added services worth 5 points.
"""
        scoped = pn.extract_scoped_criterion_response_prompts(
            doc, KNOWN_LABELS + ["Value-add"], KNOWN_CATEGORIES)
        assert len(scoped) == 1


class TestPerCategoryFormDocuments:
    """A document that IS one category's own response form states its
    criteria without repeating the category heading inside it."""

    STANDALONE_D2_FORM = """
Corporate Profile
Proponents are to describe their HR advisory organisation.

Methodology and Advisory Approach
Proponents must outline their advisory methodology and framework.
"""

    def test_category_is_derived_from_the_filename(self):
        assert pn.category_for_document_name(
            "OriginalRevision/RFP 2026-026 - Appendix D2 - Rated Criteria Response Form.docx",
            KNOWN_CATEGORIES) == CAT_2
        assert pn.category_for_document_name("RFP 2026-026.pdf", KNOWN_CATEGORIES) == ""

    def test_standalone_form_prompts_are_scoped_to_its_category(self):
        scoped = pn.extract_scoped_criterion_response_prompts(
            self.STANDALONE_D2_FORM, KNOWN_LABELS, KNOWN_CATEGORIES,
            default_category=CAT_2)
        assert set(scoped) == {
            canon.scoped_criterion_map_key(CAT_2, "Corporate Profile"),
            canon.scoped_criterion_map_key(CAT_2, "Methodology and Advisory Approach"),
        }

    def test_response_form_outranks_the_primary_solicitation_for_prompts(self):
        key = canon.scoped_criterion_map_key(CAT_2, "Corporate Profile")
        candidates = {key: [
            {"category": CAT_2, "criterion": "Corporate Profile",
             "response_prompt": "from the main RFP", "truncated": False,
             "source_doc": "RFP 2026-026.pdf"},
            {"category": CAT_2, "criterion": "Corporate Profile",
             "response_prompt": "from the response form", "truncated": False,
             "source_doc": "RFP 2026-026 - Appendix D2 - Rated Criteria Response Form.docx"},
        ]}
        chosen = pn.select_authoritative_prompts(candidates)
        assert chosen[key]["response_prompt"] == "from the response form"

    def test_selection_is_deterministic_when_authority_ties(self):
        key = canon.scoped_criterion_map_key(CAT_2, "Corporate Profile")
        candidates = {key: [
            {"response_prompt": "first", "source_doc": "RFP a.pdf"},
            {"response_prompt": "second", "source_doc": "RFP b.pdf"},
        ]}
        assert pn.select_authoritative_prompts(candidates)[key]["response_prompt"] == "first"
