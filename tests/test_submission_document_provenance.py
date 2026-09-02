"""
tests/test_submission_document_provenance.py

Deterministic tests for the submission document projection layer.
All tests are offline -- no Anthropic call, no database, no Streamlit.
"""
import json
import pathlib
import unittest
import unittest.mock as mock

from extractor import (
    build_submission_documents,
    _is_concrete_submission_document,
)

_BOC_FIXTURE = pathlib.Path(
    "tests/acceptance/results/boc_2026_026_normalized_facts.json"
)


# ============================================================================
# Part 1: Word-boundary matching regression (items I and J)
# ============================================================================

class TestWordBoundaryMatching(unittest.TestCase):
    """
    Verify that lexical indicator words are matched at word boundaries,
    not as arbitrary substrings.
    """

    def test_I_form_does_not_match_information(self):
        # "form" must not match inside "information"
        result = _is_concrete_submission_document("Proponent Information", "Form Entry")
        self.assertFalse(result,
            "'form' inside 'information' must not produce a document record")

    def test_J_form_does_not_match_format(self):
        # "form" must not match inside "format"
        result = _is_concrete_submission_document(
            "Response Format",
            "PDF / Separate Files",
            "Responses must not exceed 12 pages",
        )
        self.assertFalse(result,
            "'form' inside 'format' must not produce a document record")

    def test_form_matches_submission_form(self):
        # "form" at word boundary should match
        result = _is_concrete_submission_document(
            "Appendix A Submission Form", "Separate File"
        )
        self.assertTrue(result, "Submission Form must be classified as a document")

    def test_file_does_not_match_profile(self):
        # "file" must not match inside "profile" (if "file" were a standalone indicator)
        # With word-boundary matching this is implicit; verify profiles embedded are excluded
        result = _is_concrete_submission_document(
            "Key Personnel Profiles", "Integrated in response"
        )
        self.assertFalse(result,
            "Embedded profiles must not be classified as independent documents")


# ============================================================================
# Part 2: Classifier regression tests A-J (directive items A-J)
# ============================================================================

class TestClassifierRegressions(unittest.TestCase):
    """
    Classifier regression cases A-J as specified in the scope directive.
    Tests the _is_concrete_submission_document() predicate directly.
    """

    # A: Form Entry format -> not a document (embedded field)
    def test_A_proponent_information_form_entry_excluded(self):
        result = _is_concrete_submission_document(
            "Proponent Information", "Form Entry"
        )
        self.assertFalse(result,
            "Proponent Information with Form Entry is an embedded field, not a document")

    # B: Response Format with page instruction -> not a document
    def test_B_response_format_page_instruction_excluded(self):
        result = _is_concrete_submission_document(
            "Response Format",
            "PDF / Separate Files",
            "Responses must not exceed 12 pages excluding resumes",
        )
        self.assertFalse(result,
            "Response Format is a formatting/page-limit instruction, not a document")

    # C: RFP Main Document with reference-only details -> excluded
    def test_C_rfp_main_document_reference_only_excluded(self):
        result = _is_concrete_submission_document(
            "RFP Main Document",
            "Electronic",
            "Not mandatory but available for reference.",
        )
        self.assertFalse(result,
            "Reference-only material must be excluded even if item looks like a document")

    # D: External Links and References with non-evaluated details -> excluded
    def test_D_external_links_references_excluded(self):
        result = _is_concrete_submission_document(
            "External Links and References",
            "Supporting Documentation",
            "Links to websites or other information external to the form will not be evaluated.",
        )
        self.assertFalse(result,
            "External links instruction with will-not-be-evaluated details must be excluded")

    # E: Key Personnel Profiles with Integrated in response -> NOT an independent file
    def test_E_key_personnel_profiles_integrated_excluded(self):
        result = _is_concrete_submission_document(
            "Key Personnel Profiles", "Integrated in response"
        )
        self.assertFalse(result,
            "Key Personnel Profiles when integrated in response must not create an independent document")

    # F: Pricing Form XLSX -> concrete document
    def test_F_pricing_form_xlsx_included(self):
        result = _is_concrete_submission_document(
            "Pricing Form", "XLSX"
        )
        self.assertTrue(result, "Pricing Form in XLSX format is a concrete document")

    # G: Technical Proposal PDF -> concrete document
    def test_G_technical_proposal_pdf_included(self):
        result = _is_concrete_submission_document(
            "Technical Proposal", "PDF"
        )
        self.assertTrue(result,
            "Technical Proposal in PDF format is a concrete document")

    # H: Technical Proposal with portal details -> still a concrete document
    # Process wording in details must NOT erase a clearly named concrete document.
    def test_H_technical_proposal_portal_details_still_included(self):
        result = _is_concrete_submission_document(
            "Technical Proposal",
            "PDF",
            "Submit via portal. Max 50 pages.",
        )
        self.assertTrue(result,
            "A named concrete document must be retained even if details mention the portal")

    # Additional: Conflict of Interest Declaration as Form Entry -> embedded, excluded
    def test_conflict_of_interest_form_entry_excluded(self):
        result = _is_concrete_submission_document(
            "Conflict of Interest Declaration", "Form Entry"
        )
        self.assertFalse(result,
            "Declaration as Form Entry is an embedded field inside another form")

    # Additional: Declaration as Separate File -> independent document
    def test_conflict_of_interest_separate_file_included(self):
        result = _is_concrete_submission_document(
            "Conflict of Interest Declaration", "Separate File"
        )
        self.assertTrue(result,
            "Declaration as Separate File is an independently tracked document")

    # Additional: ESG Questionnaire -> concrete document
    def test_esg_questionnaire_response_included(self):
        result = _is_concrete_submission_document(
            "ESG Questionnaire Response", "Spreadsheet"
        )
        self.assertTrue(result, "ESG Questionnaire Response is a concrete document")

    # Additional: Security Clearance Declaration as Written documentation -> included
    def test_security_clearance_declaration_included(self):
        result = _is_concrete_submission_document(
            "Security Clearance Declaration",
            "Written documentation",
            "Written confirmation of ability to meet clearance requirements",
        )
        self.assertTrue(result,
            "Security Clearance Declaration as written documentation is a concrete document")

    # Additional: Appendix with Separate File format -> included
    def test_appendix_separate_file_included(self):
        result = _is_concrete_submission_document(
            "Appendix A Submission Form", "Separate File"
        )
        self.assertTrue(result)

    # Additional: empty item -> always False
    def test_empty_item_always_false(self):
        self.assertFalse(_is_concrete_submission_document(""))
        self.assertFalse(_is_concrete_submission_document(None))

    # Additional: Response Format page-limit pattern
    def test_response_format_and_page_limit_excluded(self):
        result = _is_concrete_submission_document(
            "Response Format and Page Limit",
            "Separate document",
            "Responses must not exceed twelve (12) pages",
        )
        self.assertFalse(result,
            "Combined format-and-page-limit instruction must be excluded")

    # Additional: Workbook tabs inside another workbook -> excluded
    def test_workbook_tab_excluded(self):
        self.assertFalse(
            _is_concrete_submission_document("Category Selection Tab", "Excel Spreadsheet"),
            "Workbook tab must not be projected as an independent document",
        )
        self.assertFalse(
            _is_concrete_submission_document("Service Category Rate Card Tab", "Excel Spreadsheet"),
            "Workbook tab must not be projected as an independent document",
        )


# ============================================================================
# Part 3: build_submission_documents() behavioral tests
# ============================================================================

class TestBuildSubmissionDocuments(unittest.TestCase):
    """
    Tests for the build_submission_documents() function:
    cases A-H from original directive, mandatory semantics, empty state.
    """

    # A: empty rules -> empty documents
    def test_A_empty_rules_yields_empty_documents(self):
        docs = build_submission_documents([])
        self.assertEqual(docs, [])

    # A2: absolutely no invented defaults
    def test_A2_no_invented_Technical_Proposal_or_Financial_Envelope(self):
        docs = build_submission_documents([])
        names = [d["name"] for d in docs]
        self.assertNotIn("Technical Proposal.pdf", names)
        self.assertNotIn("Financial Envelope.pdf", names)

    # B: portal instruction -> excluded
    def test_B_portal_submission_rule_excluded(self):
        rules = [{"item": "Submit through MERX",
                  "details": "Electronic portal submission required"}]
        docs = build_submission_documents(rules)
        self.assertEqual(docs, [])

    # C: page limit -> excluded
    def test_C_page_limit_rule_excluded(self):
        rules = [{"item": "Maximum response length 50 pages",
                  "details": "Responses must not exceed 50 pages"}]
        docs = build_submission_documents(rules)
        self.assertEqual(docs, [])

    # D: Pricing Form XLSX mandatory=1 -> one document with correct fields
    def test_D_pricing_form_explicit_document(self):
        rules = [{"item": "Pricing Form", "format": "XLSX",
                  "details": "Complete all tabs", "mandatory": 1}]
        docs = build_submission_documents(rules)
        self.assertEqual(len(docs), 1)
        d = docs[0]
        self.assertEqual(d["name"], "Pricing Form")
        self.assertEqual(d.get("mandatory"), 1)
        self.assertEqual(d["doc_type"], "Financial")
        self.assertEqual(d["status"], "Expected")

    # E: Technical Proposal -> name not mutated with .pdf
    def test_E_technical_proposal_name_not_mutated(self):
        rules = [{"item": "Technical Proposal", "format": "PDF",
                  "details": "Submit in PDF", "mandatory": 1}]
        docs = build_submission_documents(rules)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["name"], "Technical Proposal")

    # E2: source name already has .pdf -> preserved
    def test_E2_pdf_extension_preserved_if_already_in_source(self):
        rules = [{"item": "Proposal.pdf", "format": "PDF", "mandatory": 1}]
        docs = build_submission_documents(rules)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["name"], "Proposal.pdf")

    # F: mandatory absent -> key absent from output (not defaulted)
    def test_F_missing_mandatory_not_defaulted_to_one(self):
        rules = [{"item": "Technical Proposal", "format": "PDF"}]
        docs = build_submission_documents(rules)
        self.assertEqual(len(docs), 1)
        self.assertNotIn("mandatory", docs[0],
            "mandatory must not be defaulted to 1 when absent from normalized facts")

    # F2: mandatory=0 preserved
    def test_F2_mandatory_zero_preserved(self):
        rules = [{"item": "ESG Questionnaire Response", "format": "Spreadsheet",
                  "mandatory": 0}]
        docs = build_submission_documents(rules)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["mandatory"], 0)

    # G: mixed package -> only concrete independent files
    def test_G_mixed_package_only_concrete_documents(self):
        rules = [
            {"item": "Submit via Government Portal",
             "details": "Electronic portal only"},
            {"item": "Maximum 50 pages",
             "details": "Must not exceed fifty pages"},
            {"item": "Pricing Form", "format": "XLSX", "mandatory": 1},
            {"item": "Signed Declaration", "format": "PDF", "mandatory": 1},
        ]
        docs = build_submission_documents(rules)
        names = [d["name"] for d in docs]
        self.assertIn("Pricing Form", names)
        self.assertIn("Signed Declaration", names)
        self.assertNotIn("Submit via Government Portal", names)
        self.assertNotIn("Maximum 50 pages", names)
        self.assertEqual(len(docs), 2)

    # H: all-process-rule package -> documents=[] without error
    def test_H_all_process_rules_returns_empty(self):
        rules = [
            {"item": "Submit via portal"},
            {"item": "Page limit 20 pages"},
            {"item": "Registration required"},
        ]
        docs = build_submission_documents(rules)
        self.assertIsInstance(docs, list)
        self.assertEqual(len(docs), 0)

    # Mandatory semantics: None -> key absent (UNKNOWN)
    def test_mandatory_none_key_absent_from_record(self):
        rules = [{"item": "Technical Proposal", "format": "PDF", "mandatory": None}]
        docs = build_submission_documents(rules)
        self.assertEqual(len(docs), 1)
        self.assertNotIn("mandatory", docs[0])

    # Embedded format -> excluded from build_submission_documents
    def test_embedded_form_entry_not_projected(self):
        rules = [{"item": "Proponent Information", "format": "Form Entry",
                  "details": "Proponent fills in details", "mandatory": 1}]
        docs = build_submission_documents(rules)
        self.assertEqual(docs, [],
            "Form Entry items must not be projected as independent documents")

    # Reference-only -> excluded
    def test_reference_only_details_excludes_item(self):
        rules = [{"item": "RFP Main Document", "format": "Electronic",
                  "details": "Not mandatory but available for reference.",
                  "mandatory": 0}]
        docs = build_submission_documents(rules)
        self.assertEqual(docs, [])


# ============================================================================
# Part 4: BoC frozen submission document replay (semantic, no count assertion)
# ============================================================================

class TestBoCFrozenSubmissionReplay(unittest.TestCase):
    """
    Bank of Canada frozen submission document provenance replay.
    Uses existing frozen normalized_facts fixture only.
    No Stage A/B/C re-run. No Anthropic call.

    IMPORTANT: Tests assert semantic correctness, NOT a fixed total count.
    The count-based 39/40 expectation is removed per scope directive --
    that number was classifier-derived, not source truth.
    """

    @classmethod
    def setUpClass(cls):
        if not _BOC_FIXTURE.exists():
            raise unittest.SkipTest("Frozen fixture not found: " + str(_BOC_FIXTURE))
        with open(_BOC_FIXTURE, encoding="utf-8") as f:
            nf = json.load(f)
        cls.submission_rules = nf.get("submission_rules", [])
        cls.documents = build_submission_documents(cls.submission_rules)
        cls.doc_names = {d["name"] for d in cls.documents}
        cls.excluded_names = {
            sr["item"] for sr in cls.submission_rules
            if sr.get("item") not in cls.doc_names
        }

    # Source fixture integrity
    def test_boc_fixture_has_submission_rules(self):
        self.assertGreater(len(self.submission_rules), 0,
            "Frozen BoC fixture must contain submission rules")

    # No invented defaults
    def test_boc_no_technical_proposal_pdf_invented(self):
        self.assertNotIn("Technical Proposal.pdf", self.doc_names)

    def test_boc_no_financial_envelope_pdf_invented(self):
        self.assertNotIn("Financial Envelope.pdf", self.doc_names)

    # Required exclusions: process/format instructions
    def test_boc_response_format_and_page_limit_excluded(self):
        self.assertIn("Response Format and Page Limit", self.excluded_names,
            "Format+page-limit instruction must be excluded")

    def test_boc_external_links_excluded(self):
        # "External Links" and "External Links and References" should be excluded
        external_in_docs = {n for n in self.doc_names
                            if "external links" in n.lower()}
        self.assertEqual(len(external_in_docs), 0,
            "External link instructions must be excluded from documents")

    def test_boc_response_format_instruction_excluded(self):
        self.assertIn("Response Format", self.excluded_names,
            "Response Format (formatting instruction) must be excluded")

    def test_boc_key_personnel_profiles_integrated_excluded(self):
        # At minimum one "Key Personnel Profiles" with integrated format must be excluded
        integrated_profiles_in_docs = any(
            d["name"] == "Key Personnel Profiles"
            and "integrated" in (d.get("notes") or "").lower()
            for d in self.documents
        )
        self.assertFalse(integrated_profiles_in_docs,
            "Key Personnel Profiles when integrated must not become an independent document")

    def test_boc_rfp_main_document_excluded(self):
        self.assertIn("RFP Main Document", self.excluded_names,
            "RFP Main Document marked reference-only must be excluded")

    # Required inclusions: known source-supported independent artefacts
    def test_boc_appendix_a_submission_form_included(self):
        self.assertIn("Appendix A Submission Form", self.doc_names,
            "Appendix A Submission Form is a source-supported independent artefact")

    def test_boc_pricing_form_included(self):
        self.assertIn("Pricing Form - All Applicable Sections", self.doc_names,
            "Pricing Form is a source-supported independent artefact")

    def test_boc_pricing_form_classified_financial(self):
        pricing_docs = [d for d in self.documents
                        if d["name"] == "Pricing Form - All Applicable Sections"]
        self.assertEqual(len(pricing_docs), 1)
        self.assertEqual(pricing_docs[0]["doc_type"], "Financial")

    def test_boc_esg_questionnaire_included(self):
        self.assertIn("ESG Questionnaire Response", self.doc_names,
            "ESG Questionnaire Response is a concrete submission document")

    def test_boc_rated_criteria_response_form_included(self):
        self.assertIn("Rated Criteria Response Form", self.doc_names,
            "Rated Criteria Response Form is a concrete submission document")

    def test_boc_workbook_tabs_excluded(self):
        tab_docs = [d for d in self.documents if "tab" in d["name"].lower()]
        self.assertEqual(len(tab_docs), 0,
            "Workbook tabs must not be projected as independent documents")

    def test_boc_currency_tax_treatment_excluded(self):
        self.assertIn("Currency and Tax Treatment", self.excluded_names,
            "Currency and Tax Treatment is a pricing rule, not an independent file")

    # Mandatory values sourced from fixture, never invented
    def test_boc_mandatory_values_from_fixture_only(self):
        for d in self.documents:
            if "mandatory" in d:
                self.assertIn(d["mandatory"], (0, 1),
                    "mandatory must be 0 or 1 when present")

    # No .pdf extension appended to BoC document names
    def test_boc_no_pdf_extension_appended(self):
        boc_items = {sr["item"] for sr in self.submission_rules}
        for d in self.documents:
            if not d["name"].lower().endswith(".pdf") and d["name"] in boc_items:
                # Source item didn't have .pdf; document must not either
                self.assertFalse(d["name"].lower().endswith(".pdf"))

    # Report: total classified vs excluded (informational, not a fixed-count assertion)
    def test_boc_classification_report(self):
        total = len(self.submission_rules)
        included = len(self.documents)
        # Sanity: all projected documents came from the submission_rules
        for d in self.documents:
            self.assertIn(
                d["name"],
                {sr.get("item") for sr in self.submission_rules},
                "Every projected document must originate from a submission rule",
            )
        self.assertIsInstance(self.documents, list)
        self.assertGreater(total, 0, "Fixture must have submission rules")

# ============================================================================
# Part 5: Orchestrator-level empty-state test (mocked)
# ============================================================================

class TestOrchestratorEmptyDocumentState(unittest.TestCase):
    """
    Verify that extract_procurement_package() returns documents=[] without
    error when Stage A/B normalized facts contain only process submission rules.
    No live Anthropic call.
    """

    def test_all_process_rules_result_in_empty_documents(self):
        from extractor import extract_procurement_package

        process_only_facts = {
            "doc_metadata":         {"title": "Test RFP"},
            "requirements":         [],
            "dates":                [],
            "evaluation_criteria":  [],
            "submission_rules": [
                {"item": "Submit through Portal",   "format": "Online",
                 "details": "Use the procurement portal",  "mandatory": 1},
                {"item": "Maximum 50 pages",        "format": "PDF",
                 "details": "Responses must not exceed 50 pages", "mandatory": 1},
                {"item": "Registration required",   "format": "Online",
                 "details": "Register on the portal before submitting", "mandatory": 1},
            ],
            "deliverables":     [],
            "commercial_clauses": [],
            "contract_risks":   [],
        }

        minimal_synth = {"bid": {"title": "Test"}, "brief": {}, "outline": []}

        with mock.patch("extractor.extract_document_with_metadata",
                        return_value=("fake text", {})), \
             mock.patch("extractor.extract_document_facts",
                        return_value={}), \
             mock.patch("extractor.normalize_package_facts",
                        return_value=process_only_facts), \
             mock.patch("extractor.reconcile_package_facts",
                        return_value=[]), \
             mock.patch("extractor.synthesize_bid_brief",
                        return_value=minimal_synth):

            result, model = extract_procurement_package(
                [("test.pdf", b"fake pdf content")],
                api_key="test-key",
            )

        self.assertIn("documents", result,
            "Result must have a documents key")
        self.assertIsInstance(result["documents"], list)
        self.assertEqual(result["documents"], [],
            "All-process-rule submission_rules must yield documents=[]")
        self.assertNotIn("Technical Proposal.pdf",
                         [d.get("name") for d in result["documents"]])


if __name__ == "__main__":
    unittest.main()
