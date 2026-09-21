"""
tests/test_document_provenance.py -- Full-Package Analysis Integrity
Remediation Defect E (document identity/version relationships) + task
section 8 (package completeness). Pure-domain tests, no I/O, no model
call. Fixtures mirror REAL Bank of Canada bid-8 filenames (live-verified
during this task) without depending on the live database.
"""
import document_provenance as dp


class TestClassifyDocumentRelationships:

    def test_amendment_directory_amends_original_revision_counterpart(self):
        names = [
            "Amendment1/RFP 2026-026 - Appendix D2 - Rated Criteria Response REVISED.docx",
            "OriginalRevision/RFP 2026-026 - Appendix D2 - Rated Criteria Response Form.docx",
        ]
        result = dp.classify_document_relationships(names)
        assert result[names[0]]["relationship"] == dp.RELATIONSHIP_AMENDS
        assert result[names[0]]["related_to"] == names[1]
        assert result[names[1]]["relationship"] == dp.RELATIONSHIP_AMENDED_BY
        assert result[names[1]]["related_to"] == names[0]

    def test_amendment_never_pairs_with_the_wrong_sibling_category(self):
        """The distinguishing D1/D2/D3-style short identifier must never
        be lost to the >=4-character significant-word filter -- an
        Amendment to D2 must never be paired with D1's original."""
        names = [
            "Amendment1/RFP 2026-026 - Appendix D2 - Rated Criteria Response REVISED.docx",
            "OriginalRevision/RFP 2026-026 - Appendix D1 - Rated criteria response form.docx",
            "OriginalRevision/RFP 2026-026 - Appendix D2 - Rated Criteria Response Form.docx",
        ]
        result = dp.classify_document_relationships(names)
        assert result[names[0]]["related_to"] == names[2]
        assert result[names[1]]["relationship"] == dp.RELATIONSHIP_INDEPENDENT_SOURCE

    def test_duplicate_representation_of_main_rfp_in_two_formats(self):
        names = [
            "RFP 2026-026 - Talent, Learning _ Organizational Development Services(DOCX).pdf",
            "RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf",
        ]
        result = dp.classify_document_relationships(names)
        assert result[names[0]]["relationship"] == dp.RELATIONSHIP_DUPLICATE_REPRESENTATION
        assert result[names[1]]["relationship"] == dp.RELATIONSHIP_DUPLICATE_REPRESENTATION

    def test_c1_and_c2_never_falsely_matched_as_duplicates_of_each_other(self):
        """Real defect caught live: two genuinely different appendices
        ("C1"/"C2" Minimum Qualification Requirements) share enough
        generic wording to cross a naive similarity threshold -- their
        own distinguishing short identifiers must prevent that."""
        names = [
            "Appendix C1 - Minimum Qualification Requirements",
            "Appendix C2 - Minimum Qualification Requirements",
        ]
        result = dp.classify_document_relationships(names)
        assert result[names[0]]["relationship"] == dp.RELATIONSHIP_INDEPENDENT_SOURCE
        assert result[names[1]]["relationship"] == dp.RELATIONSHIP_INDEPENDENT_SOURCE

    def test_c1_still_matches_its_own_original_revision_counterpart(self):
        names = [
            "Appendix C1 - Minimum Qualification Requirements",
            "OriginalRevision/RFP 2026-026 - Appendix C1 - Minimum qualification requirements.xlsx",
            "Appendix C2 - Minimum Qualification Requirements",
            "OriginalRevision/RFP 2026-026 - Appendix C2 - Minimum qualification requirements.xlsx",
        ]
        result = dp.classify_document_relationships(names)
        assert result[names[0]]["related_to"] == names[1]
        assert result[names[2]]["related_to"] == names[3]

    def test_unrelated_document_defaults_to_independent_source(self):
        names = ["RFP 2026-026 - Main Solicitation.pdf", "Appendix G - Form of Agreement.docx"]
        result = dp.classify_document_relationships(names)
        assert result["Appendix G - Form of Agreement.docx"]["relationship"] == dp.RELATIONSHIP_INDEPENDENT_SOURCE

    def test_generic_short_filename_with_no_overlap_stays_independent(self):
        """Fails conservatively: a short, generic filename with no real
        basename overlap with anything else (e.g. "abstract.pdf" alone in
        a corpus) is never guessed into REDUNDANT_DERIVATIVE."""
        names = ["abstract.pdf", "RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf"]
        result = dp.classify_document_relationships(names)
        assert result["abstract.pdf"]["relationship"] == dp.RELATIONSHIP_INDEPENDENT_SOURCE

    def test_every_input_name_gets_exactly_one_entry(self):
        names = ["a.pdf", "b.pdf", "c.pdf"]
        result = dp.classify_document_relationships(names)
        assert set(result.keys()) == set(names)

    def test_empty_corpus_returns_empty(self):
        assert dp.classify_document_relationships([]) == {}


class TestAssessPackageCompleteness:

    def test_complete_package_with_main_rfp_present_no_warning(self):
        typed_obs = [
            {"family": "IDENTITY", "semantic_kind": "OPPORTUNITY_TITLE", "original_value": "RFP 2026-026"},
            {"family": "IDENTITY", "semantic_kind": "BUYER_NAME", "original_value": "Bank of Canada"},
        ]
        requirements = [{"category": "Mandatory", "description": "x"}]
        names = ["RFP 2026-026 - Main.pdf", "Appendix A - Submission Form.docx"]
        result = dp.assess_package_completeness(typed_obs, requirements, True, names)
        assert result["is_complete"] is True
        assert result["warning"] is None

    def test_addendum_without_main_rfp_triggers_warning(self):
        names = [
            "Amendment1/Appendix D2 - Rated Criteria Response REVISED.docx",
            "Appendix B1 - Mandatory Criteria.xlsx",
            "Addendum 3 - Clarifications.pdf",
        ]
        result = dp.assess_package_completeness([], [], False, names)
        assert result["is_complete"] is False
        assert "incomplete procurement package" in result["warning"]

    def test_no_identity_signal_but_mixed_filenames_does_not_force_warning(self):
        """A corpus with no confident IDENTITY signal AND filenames that
        are not exclusively supporting-document-shaped (e.g. a plain,
        unlabeled main document) should not be flagged purely on the
        identity-signal miss -- only the "supporting docs only" signal
        combined with no identity forces the warning."""
        names = ["Main Solicitation.pdf"]
        result = dp.assess_package_completeness([], [], False, names)
        assert result["is_complete"] is True

    def test_empty_document_list_never_warns(self):
        result = dp.assess_package_completeness([], [], False, [])
        assert result["is_complete"] is True
        assert result["warning"] is None

    def test_never_blocks_only_warns(self):
        """The function itself has no concept of "blocking" -- it only
        returns data; this test documents that contract explicitly."""
        result = dp.assess_package_completeness([], [], False, ["Addendum 1.pdf"])
        assert isinstance(result, dict)
        assert "is_complete" in result and "warning" in result
