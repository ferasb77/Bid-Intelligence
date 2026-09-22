"""
CI-1: Typed & Scoped Canonical Procurement Intelligence -- deterministic
tests for the shared canonical contract and the four wiring points that
consume it.

Entirely synthetic and deterministic: no live database, no Anthropic
call, no file I/O. Nothing here is keyed to a real buyer's content --
Bank of Canada shapes are reproduced structurally (a category-scoped
response form, an addendum, two categories' demo dates) with invented
text, exactly as the task requires ("Do not hard-code Bank of Canada
content").
"""
from __future__ import annotations

import canonical_procurement as cp
import procurement_normalization as pn
from fast_analysis import detect_category_date_distinctions


# ═══════════════════════════════════════════════════════════════════════
# Section 3 / Defect A + section 15 -- opportunity identity & authority
# ═══════════════════════════════════════════════════════════════════════

class TestOpportunityIdentity:

    def test_main_solicitation_is_the_identity_source(self):
        roles = cp.classify_identity_roles([
            "RFP 2026-026 Request for Proposal.pdf",
            "RFP 2026-026 Addendum #2.pdf",
            "RFP 2026-026 - Appendix D1 - Rated criteria response form.docx",
            "RFP 2026-026 - Appendix G - Form of Agreement.docx",
        ])
        assert roles["RFP 2026-026 Request for Proposal.pdf"] == cp.IDENTITY_ROLE_PRIMARY_SOLICITATION
        assert roles["RFP 2026-026 Addendum #2.pdf"] == cp.IDENTITY_ROLE_AMENDMENT
        assert roles["RFP 2026-026 - Appendix D1 - Rated criteria response form.docx"] == cp.IDENTITY_ROLE_RESPONSE_FORM
        assert roles["RFP 2026-026 - Appendix G - Form of Agreement.docx"] == cp.IDENTITY_ROLE_CONTRACT_INSTRUMENT

    def test_addendum_never_becomes_the_canonical_identity(self):
        """The exact live failure: an addendum listed FIRST, carrying its
        own truncated buyer string and its own title."""
        merged = cp.merge_identity_fields({
            "RFP 2026-026 Addendum #2.pdf": {
                "client": "Bank", "title": "RFP 2026-026 Addendum #2", "file_number": "2026-026"},
            "RFP 2026-026 Request for Proposal.pdf": {
                "client": "Bank of Canada",
                "title": "Request for Proposal for Talent, Learning and Organizational Development Services",
                "file_number": "2026-026"},
        })
        assert merged["client"] == "Bank of Canada"
        assert merged["title"].startswith("Request for Proposal for Talent")
        assert merged["file_number"] == "2026-026"

    def test_amendment_retains_clause_authority(self):
        """An addendum has no IDENTITY authority but is the FIRST
        authority for the clauses it actually changes."""
        meta = {
            "RFP 2026-026 Addendum #2.pdf": {"closing_date": "2026-11-15"},
            "RFP 2026-026 Request for Proposal.pdf": {"closing_date": "2026-10-01"},
        }
        assert cp.merge_identity_fields(meta, "clause")["closing_date"] == "2026-11-15"
        assert cp.merge_identity_fields(meta, "identity")["closing_date"] == "2026-10-01"

    def test_amendment_only_package_still_yields_an_answer(self):
        merged = cp.merge_identity_fields({
            "Addendum #1.pdf": {"client": "Some Buyer"},
        })
        assert merged["client"] == "Some Buyer"

    def test_identity_provenance_is_traceable(self):
        with_prov = cp.merge_identity_fields_with_provenance({
            "Addendum #2.pdf": {"client": "Bank"},
            "Request for Proposal.pdf": {"client": "Bank of Canada"},
        })
        assert with_prov["client"] == ("Bank of Canada", "Request for Proposal.pdf")


# ═══════════════════════════════════════════════════════════════════════
# Section 4 / Defect B -- semantic typing
# ═══════════════════════════════════════════════════════════════════════

class TestSemanticTyping:

    def test_response_prompt_cannot_become_scope(self):
        text = "Proponents are to describe their organisation and its learning and development services."
        assert cp.classify_semantic_type(text) == cp.SEMANTIC_RESPONSE_PROMPT
        assert cp.is_usable_as_scope(text) is False

    def test_scope_item_is_not_an_evaluation_prompt(self):
        text = "The Services will include providing curriculum design, facilitation and coaching."
        assert cp.classify_semantic_type(text) == cp.SEMANTIC_SCOPE_ITEM
        assert cp.is_usable_as_scope(text) is True

    def test_structural_hint_never_overrides_a_response_prompt(self):
        text = "Proponents should provide details of their methodology."
        assert cp.classify_semantic_type(text, hint=cp.SEMANTIC_SCOPE_ITEM) == cp.SEMANTIC_RESPONSE_PROMPT

    def test_structural_hint_is_honoured_otherwise(self):
        assert cp.classify_semantic_type(
            "Relationship Management", hint=cp.SEMANTIC_EVALUATION_CRITERION
        ) == cp.SEMANTIC_EVALUATION_CRITERION

    def test_requested_evidence_is_distinct_from_scope(self):
        text = "Attach curricula vitae for each proposed facilitator."
        assert cp.classify_semantic_type(text) == cp.SEMANTIC_REQUESTED_EVIDENCE
        assert cp.is_usable_as_scope(text) is False

    def test_unclassifiable_text_is_never_treated_as_scope(self):
        assert cp.classify_semantic_type("Miscellaneous.") == cp.SEMANTIC_UNKNOWN
        assert cp.is_usable_as_scope("Miscellaneous.") is False


# ═══════════════════════════════════════════════════════════════════════
# Section 5 / Defect C -- category applicability
# ═══════════════════════════════════════════════════════════════════════

class TestCategoryApplicability:

    def test_category_one_requirement_stays_category_one(self):
        a = cp.derive_requirement_applicability({
            "description": "Minimum five years of learning and development delivery experience.",
            "source_doc": "OriginalRevision/RFP 2026-026 - Appendix C1 - Minimum qualification requirements.xlsx",
        })
        assert a["applicability"] == cp.APPLICABILITY_CATEGORY_SPECIFIC
        assert a["category_ids"] == ["C1"]
        assert a["basis"] == "source_document"

    def test_global_requirement_can_apply_across_all_categories(self):
        a = cp.derive_requirement_applicability({
            "description": "This requirement applies to all three categories without exception.",
            "source_doc": "RFP.pdf",
        })
        assert a["applicability"] == cp.APPLICABILITY_ALL_CATEGORIES

    def test_shared_summary_document_does_not_imply_global(self):
        """Task section 5's explicit prohibition."""
        a = cp.derive_requirement_applicability({
            "description": "Senior human resources consulting resources must be available.",
            "source_doc": "RFP 2026-026 Summary of Requirements.pdf",
        })
        assert a["applicability"] == cp.APPLICABILITY_UNKNOWN
        assert a["applicability"] != cp.APPLICABILITY_ALL_CATEGORIES

    def test_submission_and_contract_wide_applicability(self):
        sub = cp.derive_requirement_applicability({
            "description": "Proposals must be received before the closing date and time.",
            "source_doc": "RFP.pdf"})
        assert sub["applicability"] == cp.APPLICABILITY_SUBMISSION_WIDE
        con = cp.derive_requirement_applicability({
            "description": "The Contractor shall indemnify and save harmless the Buyer.",
            "source_doc": "RFP.pdf"})
        assert con["applicability"] == cp.APPLICABILITY_CONTRACT_WIDE

    def test_same_text_different_category_does_not_merge(self):
        reqs = [
            {"category": "Mandatory", "description": "Provide a facilitation methodology statement.",
             "source_doc": "Appendix C1 - Minimum qualification requirements.xlsx", "source_refs": []},
            {"category": "Mandatory", "description": "Provide a facilitation methodology statement.",
             "source_doc": "Appendix C3 - Minimum qualification requirement.xlsx", "source_refs": []},
        ]
        canon = pn.canonicalize_requirements(reqs)
        assert len(canon) == 2
        assert {c["applicable_category_ids"][0] for c in canon} == {"C1", "C3"}

    def test_unscoped_restatement_still_merges_with_a_scoped_one(self):
        """Silence is not a conflicting scope -- the main RFP's unscoped
        restatement of a category form's obligation is one obligation."""
        reqs = [
            {"category": "Mandatory", "description": "Security clearance required.",
             "source_doc": "RFP.pdf", "source_refs": []},
            {"category": "Mandatory", "description": "Security clearance required.",
             "source_doc": "Appendix C2 - Minimum qualification requirements.xlsx", "source_refs": []},
        ]
        canon = pn.canonicalize_requirements(reqs)
        assert len(canon) == 1
        assert canon[0]["applicable_category_ids"] == ["C2"]
        assert set(canon[0]["source_docs"]) == {
            "RFP.pdf", "Appendix C2 - Minimum qualification requirements.xlsx"}


# ═══════════════════════════════════════════════════════════════════════
# Sections 6 / 7 -- Defects D and E, scoped criterion identity
# ═══════════════════════════════════════════════════════════════════════

class TestScopedEvaluationCriteria:

    def test_same_label_in_two_categories_is_two_criteria(self):
        k1 = cp.scoped_criterion_key("Category 1 — Learning & Development", "Relevant Experience")
        k2 = cp.scoped_criterion_key("Category 2 — HR Advisory", "Relevant Experience")
        assert k1 != k2

    def test_criterion_identity_ignores_whitespace_and_case(self):
        assert cp.scoped_criterion_key("Category 1", "Relevant  Experience") == \
               cp.scoped_criterion_key(" category 1 ", "relevant experience")

    def test_label_present_in_a_category_is_not_a_global_criterion(self):
        scoped = [("category 1 — learning & development", "relationship management"),
                  ("category 2 — hr advisory", "relevant experience")]
        assert cp.is_genuinely_global_criterion("Relationship Management", scoped) is False
        assert cp.is_genuinely_global_criterion("Relevant Experience", scoped) is False

    def test_a_truly_uncategorized_criterion_survives(self):
        scoped = [("category 1", "curriculum design")]
        assert cp.is_genuinely_global_criterion("Corporate Social Responsibility", scoped) is True

    def test_unscoped_criteria_do_not_block_a_global_criterion(self):
        scoped = [("", "relationship management")]
        assert cp.is_genuinely_global_criterion("Relationship Management", scoped) is True


# ═══════════════════════════════════════════════════════════════════════
# Section 8 / Defect F -- scoped milestone identity
# ═══════════════════════════════════════════════════════════════════════

def _milestone(kind, value, date, scope):
    obs = {"family": "MILESTONE", "semantic_kind": kind, "original_value": value,
           "date": date, "source_refs": []}
    if scope:
        obs["scope"] = {"category": scope}
    return obs


class TestScopedMilestones:

    def test_two_categories_two_demo_dates_is_not_an_ambiguity(self):
        obs = [
            _milestone("PRESENTATION_OR_DEMO", "Week of October 26", "2026-10-26", "Category 1"),
            _milestone("PRESENTATION_OR_DEMO", "Week of November 2", "2026-11-02", "Category 3"),
        ]
        assert detect_category_date_distinctions(obs) == []

    def test_conflicting_dates_for_the_same_scoped_event_is_an_ambiguity(self):
        obs = [
            _milestone("PRESENTATION_OR_DEMO", "Week of October 26", "2026-10-26", "Category 1"),
            _milestone("PRESENTATION_OR_DEMO", "Week of November 2", "2026-11-02", "Category 1"),
        ]
        found = detect_category_date_distinctions(obs)
        assert len(found) == 1
        assert found[0]["milestone_kind"] == "PRESENTATION_OR_DEMO"

    def test_unscoped_conflicting_dates_still_flagged(self):
        obs = [
            _milestone("SUBMISSION_DEADLINE", "2026-10-01", "2026-10-01", None),
            _milestone("SUBMISSION_DEADLINE", "2026-10-08", "2026-10-08", None),
        ]
        assert len(detect_category_date_distinctions(obs)) == 1

    def test_alternate_wordings_of_one_date_are_not_a_disagreement(self):
        """'Week of October 26' and '2026-10-26' for the SAME scoped
        event are two representations of one date, not a conflict."""
        obs = [
            _milestone("PRESENTATION_OR_DEMO", "Week of October 26", None, "Category 1"),
            _milestone("PRESENTATION_OR_DEMO", "2026-10-26", "2026-10-26", "Category 1"),
        ]
        assert detect_category_date_distinctions(obs) == []

    def test_non_overlapping_wordings_are_still_a_real_conflict(self):
        """The alternate-representation reconciliation above must not
        swallow a genuine disagreement: a 'Week of' window that does not
        contain the competing exact date is still flagged."""
        obs = [
            _milestone("PRESENTATION_OR_DEMO", "Week of October 26", None, "Category 1"),
            _milestone("PRESENTATION_OR_DEMO", "2026-11-02", "2026-11-02", "Category 1"),
        ]
        assert len(detect_category_date_distinctions(obs)) == 1

    def test_scope_key_normalizes_equivalent_category_wordings(self):
        a = cp.milestone_scope_key({"scope": {"category": "Category 1"}})
        b = cp.milestone_scope_key({"category_scope": "category 1 - learning & development"})
        assert a == b

    def test_original_wording_preserved_by_canonicalization(self):
        canon = pn.canonicalize_milestones([
            _milestone("PRESENTATION_OR_DEMO", "Week of October 26", None, "Category 1"),
            _milestone("PRESENTATION_OR_DEMO", "2026-10-26", "2026-10-26", "Category 1"),
        ], assumed_year=2026)
        assert len(canon) == 1
        assert "Week of October 26" in canon[0]["original_wording"]


# ═══════════════════════════════════════════════════════════════════════
# Section 9 / Defect G -- commercial taxonomy
# ═══════════════════════════════════════════════════════════════════════

class TestCommercialTaxonomy:

    def test_decline_engagement_clause_is_not_assignment(self):
        text = ("The Supplier may decline any individual engagement or work request "
                "without penalty; the Buyer does not guarantee any volume of work.")
        assert cp.classify_commercial_topic(text) == cp.TOPIC_CALL_OFF_ACCEPTANCE
        assert cp.clause_supports_topic(text, cp.TOPIC_ASSIGNMENT) is False

    def test_tax_remittance_clause_is_not_indemnity(self):
        text = ("The Contractor is responsible for all income tax, Canada Pension Plan "
                "and employment insurance remittances and for workplace insurance coverage, "
                "and shall indemnify the Buyer for any failure to remit.")
        assert cp.classify_commercial_topic(text) == cp.TOPIC_TAX_STATUTORY
        assert cp.clause_supports_topic(text, cp.TOPIC_INDEMNITY) is False

    def test_genuine_indemnity_clause_still_classifies_as_indemnity(self):
        text = "The Contractor shall indemnify and save harmless the Buyer from any loss or damage."
        assert cp.classify_commercial_topic(text) == cp.TOPIC_INDEMNITY
        assert cp.clause_supports_topic(text, cp.TOPIC_INDEMNITY) is True

    def test_explicit_heading_wins_over_body_prose(self):
        body = "The parties shall keep confidential information confidential."
        assert cp.classify_commercial_topic(body) == cp.TOPIC_CONFIDENTIALITY
        assert cp.classify_commercial_topic(body, heading="14.3 Assignment of this Agreement") == cp.TOPIC_ASSIGNMENT

    def test_genuine_assignment_clause_classifies_as_assignment(self):
        text = "The Contractor must not assign this Agreement without prior written consent."
        assert cp.classify_commercial_topic(text) == cp.TOPIC_ASSIGNMENT

    def test_unclassifiable_clause_is_not_forced_into_a_topic(self):
        text = "The parties will meet quarterly to review progress."
        assert cp.classify_commercial_topic(text) == cp.TOPIC_UNCLASSIFIED
        # ... and is therefore left where upstream extraction put it,
        # rather than discarded.
        assert cp.clause_supports_topic(text, cp.TOPIC_TERMINATION) is True


# ═══════════════════════════════════════════════════════════════════════
# Section 10 / Defect H -- attention-point evidence binding
# ═══════════════════════════════════════════════════════════════════════

class TestAttentionPointBinding:

    def test_reference_check_cannot_bind_bilingualism_evidence(self):
        bilingual = ("Bilingualism - Each proposal must confirm the ability to deliver "
                     "all services in both English and French.")
        assert cp.attention_evidence_supports_topic("REFERENCE_CHECK", bilingual) is False
        assert cp.select_supporting_facts("REFERENCE_CHECK", [bilingual]) == []

    def test_reference_check_binds_genuine_reference_evidence(self):
        fact = "Three referees will be contacted and scored on a pass/fail basis."
        assert cp.select_supporting_facts("REFERENCE_CHECK", [fact]) == [fact]

    def test_correct_fact_selected_from_a_mixed_list(self):
        facts = ["Bilingual delivery in both official languages is required.",
                 "A reference check of three referees applies."]
        assert cp.select_supporting_facts("REFERENCE_CHECK", facts) == [facts[1]]
        assert cp.select_supporting_facts("BILINGUALISM", facts) == [facts[0]]

    def test_unknown_topic_is_never_auto_bound(self):
        assert cp.attention_evidence_supports_topic("NOT_A_TOPIC", "anything at all") is False


# ═══════════════════════════════════════════════════════════════════════
# Section 11 / Defect I -- semantic deduplication
# ═══════════════════════════════════════════════════════════════════════

class TestSemanticDeduplication:

    def test_semantically_equivalent_accessibility_requirements_merge(self):
        reqs = [
            {"category": "Mandatory", "source_doc": "RFP.pdf", "source_refs": [{"page": 4}],
             "description": "All digital learning materials must conform to WCAG 2.1 Level AA accessibility."},
            {"category": "Mandatory", "source_doc": "Appendix E.pdf", "source_refs": [{"page": 9}],
             "description": "Course content delivered electronically shall meet WCAG 2.1 AA, ensuring accessibility for all learners."},
        ]
        canon = pn.canonicalize_requirements(reqs)
        assert len(canon) == 1
        assert len(canon[0]["source_variants"]) == 2
        assert canon[0]["source_refs_all"] == [{"page": 4}, {"page": 9}]

    def test_differently_scoped_accessibility_requirements_remain_distinct(self):
        reqs = [
            {"category": "Mandatory", "source_refs": [],
             "source_doc": "Appendix C1 - Minimum qualification requirements.xlsx",
             "description": "Materials must conform to WCAG 2.1 Level AA accessibility."},
            {"category": "Mandatory", "source_refs": [],
             "source_doc": "Appendix C3 - Minimum qualification requirement.xlsx",
             "description": "Materials shall meet WCAG 2.1 AA accessibility standards."},
        ]
        assert len(pn.canonicalize_requirements(reqs)) == 2

    def test_different_standards_are_never_merged(self):
        reqs = [
            {"category": "Mandatory", "source_doc": "RFP.pdf", "source_refs": [],
             "description": "Content must conform to WCAG 2.1 Level AA accessibility."},
            {"category": "Mandatory", "source_doc": "RFP.pdf", "source_refs": [],
             "description": "Systems shall satisfy ISO 27001 information security certification."},
        ]
        assert len(pn.canonicalize_requirements(reqs)) == 2

    def test_all_source_refs_survive_a_merge(self):
        reqs = [
            {"category": "Mandatory", "source_doc": "A.pdf", "source_refs": [{"page": 1}],
             "description": "Proposals must be submitted in English."},
            {"category": "Mandatory", "source_doc": "B.pdf", "source_refs": [{"page": 2}],
             "description": "Proposals must be submitted in English."},
        ]
        canon = pn.canonicalize_requirements(reqs)
        assert len(canon) == 1
        assert canon[0]["source_refs_all"] == [{"page": 1}, {"page": 2}]
        assert canon[0]["duplicate_count"] == 2


# ═══════════════════════════════════════════════════════════════════════
# Section 12 / Defect J -- canonical document identity
# ═══════════════════════════════════════════════════════════════════════

class TestCanonicalDocumentIdentity:

    def test_revised_form_precedence_preserved(self):
        import document_provenance as dp
        rels = dp.classify_document_relationships([
            "OriginalRevision/RFP 2026-026 - Appendix D2 - Rated criteria response form.docx",
            "Amendment2/RFP 2026-026 - Appendix D2 - Rated criteria response form REVISED.docx",
        ])
        revised = "Amendment2/RFP 2026-026 - Appendix D2 - Rated criteria response form REVISED.docx"
        assert rels[revised]["relationship"] == dp.RELATIONSHIP_AMENDS

    def test_category_specific_forms_are_never_collapsed(self):
        import document_provenance as dp
        names = [
            "Appendix D1 - Rated criteria response form.docx",
            "Appendix D2 - Rated criteria response form.docx",
            "Appendix D3 - Rated criteria response form.docx",
        ]
        rels = dp.classify_document_relationships(names)
        assert all(r["relationship"] == dp.RELATIONSHIP_INDEPENDENT_SOURCE for r in rels.values())

    def test_identity_role_and_relationship_are_separate_axes(self):
        """A document can be a RESPONSE_FORM (identity-role axis) and a
        DUPLICATE_REPRESENTATION (source-relationship axis) at once --
        CI-1 keeps the two axes independent rather than overloading one."""
        assert cp.classify_identity_role(
            "Appendix B - Proposal Response Form.docx") == cp.IDENTITY_ROLE_RESPONSE_FORM
        assert cp.classify_identity_role(
            "Appendix B - Proposal Response Form.pdf") == cp.IDENTITY_ROLE_RESPONSE_FORM
