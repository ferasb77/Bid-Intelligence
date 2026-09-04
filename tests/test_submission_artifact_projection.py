"""
tests/test_submission_artifact_projection.py

Unit and regression test suite for Submission Artifact Projection Integrity:
- Orthogonal separation of Artifact Identity, File Format, and Submission Channel.
- Tests A through U as specified in the remediation directive.
- Legacy format string compatibility and classifier robustness.
- Provenance preservation and merging across chunks and documents.
- State-Submit checklist and readiness invariants.
"""
import unittest

from extractor import (
    classify_submission_rule,
    _is_concrete_submission_document,
    build_submission_documents,
    aggregate_stage_a_facts,
    normalize_package_facts,
    apply_stage_d_authoritative_sections,
)


class TestSubmissionArtifactProjectionMandated(unittest.TestCase):
    """
    Mandated Tests A through U covering all semantic and orthogonal boundary cases.
    """

    # Test A: Pure portal delivery instruction with no artifact noun -> PROCESS_ONLY -> excluded
    def test_A_pure_portal_delivery_instruction(self):
        rule = {"item": "Submit via portal", "format": "Portal", "details": "All bids via portal"}
        classification = classify_submission_rule(**rule)
        self.assertEqual(classification["classification"], "PROCESS_ONLY")
        self.assertFalse(classification["is_concrete_document"])
        docs = build_submission_documents([rule])
        self.assertEqual(len(docs), 0)

    # Test B: Named annex with Portal channel -> ARTIFACT -> included
    def test_B_named_annex_with_portal_channel(self):
        rule = {"item": "Annex 3 (Supplier Response)", "format": "Portal", "mandatory": 1}
        classification = classify_submission_rule(**rule)
        self.assertEqual(classification["classification"], "ARTIFACT")
        self.assertTrue(classification["is_concrete_document"])
        docs = build_submission_documents([rule])
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["name"], "Annex 3 (Supplier Response)")
        self.assertEqual(docs[0]["submission_channel"], "Portal")

    # Test C: Legacy format="Portal" with artifact evidence -> channel normalized, artifact preserved
    def test_C_legacy_format_portal_with_artifact_evidence(self):
        rule = {
            "item": "Annex 3 (Supplier Response)",
            "format": "Portal/Email",
            "details": "Completed tender responses in accordance with ITT requirements",
            "mandatory": 1,
        }
        classification = classify_submission_rule(**rule)
        self.assertEqual(classification["classification"], "ARTIFACT")
        self.assertTrue(classification["is_concrete_document"])
        docs = build_submission_documents([rule])
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["name"], "Annex 3 (Supplier Response)")

    # Test D: Explicit pricing XLSX via portal -> ARTIFACT, format=XLSX, channel=Portal -> doc_type=Financial
    def test_D_pricing_xlsx_via_portal(self):
        rule = {
            "item": "Pricing Approach",
            "format": "XLSX",
            "details": "Submit pricing spreadsheet via e-tendering portal",
            "mandatory": 1,
        }
        classification = classify_submission_rule(**rule)
        self.assertEqual(classification["classification"], "ARTIFACT")
        self.assertTrue(classification["is_concrete_document"])
        self.assertEqual(classification["file_format"], "XLSX")
        self.assertEqual(classification["submission_channel"], "Portal")
        docs = build_submission_documents([rule])
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["doc_type"], "Financial")
        self.assertEqual(docs[0]["name"], "Pricing Approach")

    # Test E: Pure email instruction -> PROCESS_ONLY -> excluded
    def test_E_pure_email_instruction(self):
        rule = {"item": "Email submission to moiz.khalid@britishcouncil.org", "format": "Email"}
        classification = classify_submission_rule(**rule)
        self.assertEqual(classification["classification"], "PROCESS_ONLY")
        self.assertFalse(classification["is_concrete_document"])
        docs = build_submission_documents([rule])
        self.assertEqual(len(docs), 0)

    # Test F: Signed declaration via email -> ARTIFACT, channel=Email -> included
    def test_F_signed_declaration_via_email(self):
        rule = {
            "item": "Signed Declaration of Compliance",
            "format": "PDF",
            "details": "Email signed scan to procurement officer",
            "mandatory": 1,
        }
        classification = classify_submission_rule(**rule)
        self.assertEqual(classification["classification"], "ARTIFACT")
        self.assertTrue(classification["is_concrete_document"])
        self.assertEqual(classification["submission_channel"], "Email")
        docs = build_submission_documents([rule])
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["name"], "Signed Declaration of Compliance")

    # Test G: Embedded portal form entry (no standalone file) -> EMBEDDED_RESPONSE -> excluded
    def test_G_embedded_portal_form_entry(self):
        rule = {
            "item": "Proponent Information Form",
            "format": "Form Entry",
            "details": "Complete online form directly in the portal",
            "mandatory": 1,
        }
        classification = classify_submission_rule(**rule)
        self.assertEqual(classification["classification"], "EMBEDDED_RESPONSE")
        self.assertFalse(classification["is_concrete_document"])
        docs = build_submission_documents([rule])
        self.assertEqual(len(docs), 0)

    # Test H: Portal in details text does not override explicit PDF format -> ARTIFACT, format=PDF, channel=Portal
    def test_H_portal_in_details_does_not_override_pdf(self):
        rule = {
            "item": "Technical Proposal",
            "format": "PDF",
            "details": "Upload PDF file to MERX portal before deadline",
            "mandatory": 1,
        }
        classification = classify_submission_rule(**rule)
        self.assertEqual(classification["classification"], "ARTIFACT")
        self.assertTrue(classification["is_concrete_document"])
        self.assertEqual(classification["file_format"], "PDF")
        self.assertIn("Portal", classification["submission_channel"])
        docs = build_submission_documents([rule])
        self.assertEqual(len(docs), 1)

    # Test I: Portal in format field does not kill strong standalone artifact -> ARTIFACT
    def test_I_portal_in_format_does_not_kill_artifact(self):
        rule = {
            "item": "Annex 4 (Pricing Approach)",
            "format": "Electronic Portal or Email",
            "details": "Submit complete Annex 4 document",
            "mandatory": 1,
        }
        classification = classify_submission_rule(**rule)
        self.assertEqual(classification["classification"], "ARTIFACT")
        self.assertTrue(classification["is_concrete_document"])
        docs = build_submission_documents([rule])
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["name"], "Annex 4 (Pricing Approach)")

    # Test J: Page limit instruction in item text -> PROCESS_ONLY -> excluded
    def test_J_page_limit_instruction_excluded(self):
        rule = {"item": "Maximum 20 pages for Technical Response", "format": "PDF"}
        classification = classify_submission_rule(**rule)
        self.assertEqual(classification["classification"], "PROCESS_ONLY")
        self.assertFalse(classification["is_concrete_document"])
        docs = build_submission_documents([rule])
        self.assertEqual(len(docs), 0)

    # Test K: Workbook tab inside another submitted workbook -> EMBEDDED_RESPONSE -> excluded
    def test_K_workbook_tab_inside_workbook_excluded(self):
        rule = {
            "item": "Requirements Costs Tab",
            "format": "Excel Sheet (yellow-highlighted fields)",
            "details": "Insert costs into Requirements Costs tab",
            "mandatory": 1,
        }
        classification = classify_submission_rule(**rule)
        self.assertFalse(classification["is_concrete_document"])
        docs = build_submission_documents([rule])
        self.assertEqual(len(docs), 0)

    # Test L: Reference document not submitted -> REFERENCE_ONLY / PROCESS_ONLY -> excluded
    def test_L_reference_only_document_excluded(self):
        rule = {
            "item": "RFP Terms and Conditions",
            "format": "Electronic",
            "details": "Not mandatory but available for reference",
            "mandatory": 0,
        }
        classification = classify_submission_rule(**rule)
        self.assertFalse(classification["is_concrete_document"])
        docs = build_submission_documents([rule])
        self.assertEqual(len(docs), 0)

    # Test M: Attached evidence item (e.g. audited accounts) -> ARTIFACT -> included
    def test_M_attached_evidence_item_included(self):
        rule = {
            "item": "Audited Financial Accounts",
            "format": "Separate Document",
            "details": "Two years of audited financial accounts",
            "mandatory": 1,
        }
        classification = classify_submission_rule(**rule)
        self.assertEqual(classification["classification"], "ARTIFACT")
        self.assertTrue(classification["is_concrete_document"])
        docs = build_submission_documents([rule])
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["name"], "Audited Financial Accounts")

    # Test N: Online questionnaire completed in portal -> EMBEDDED_RESPONSE -> excluded
    def test_N_online_questionnaire_in_portal_excluded(self):
        rule = {
            "item": "Supplier Background Questionnaire",
            "format": "Form Entry",
            "details": "Direct questionnaire in portal",
            "mandatory": 1,
        }
        classification = classify_submission_rule(**rule)
        self.assertEqual(classification["classification"], "EMBEDDED_RESPONSE")
        self.assertFalse(classification["is_concrete_document"])
        docs = build_submission_documents([rule])
        self.assertEqual(len(docs), 0)

    # Test O: Multiple artifacts sharing the same channel -> all projected independently
    def test_O_multiple_artifacts_same_channel_projected_independently(self):
        rules = [
            {"item": "Annex 2 (Procurement Specific Questionnaire)", "format": "Portal/Email", "mandatory": 1},
            {"item": "Annex 3 (Supplier Response)", "format": "Portal/Email", "mandatory": 1},
            {"item": "Annex 4 (Pricing Approach)", "format": "Portal/Email", "mandatory": 1},
        ]
        docs = build_submission_documents(rules)
        self.assertEqual(len(docs), 3)
        doc_names = [d["name"] for d in docs]
        self.assertIn("Annex 2 (Procurement Specific Questionnaire)", doc_names)
        self.assertIn("Annex 3 (Supplier Response)", doc_names)
        self.assertIn("Annex 4 (Pricing Approach)", doc_names)

    # Test P: Channel in details only -> channel captured without affecting artifact projection
    def test_P_channel_in_details_only(self):
        rule = {
            "item": "Annex 2a (Ratio Analysis)",
            "format": "Spreadsheet",
            "details": "Upload to TCS portal by 5pm",
            "mandatory": 1,
        }
        classification = classify_submission_rule(**rule)
        self.assertTrue(classification["is_concrete_document"])
        self.assertEqual(classification["file_format"], "Spreadsheet")
        self.assertEqual(classification["submission_channel"], "Portal")
        docs = build_submission_documents([rule])
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["submission_channel"], "Portal")

    # Test Q: Document name from source not mutated with invented extension
    def test_Q_no_invented_extension(self):
        rule = {"item": "Technical Response Document", "format": "PDF", "mandatory": 1}
        docs = build_submission_documents([rule])
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["name"], "Technical Response Document")
        self.assertFalse(docs[0]["name"].endswith(".pdf"))

    # Test R: Missing mandatory field -> mandatory key omitted from projected document
    def test_R_missing_mandatory_key_omitted(self):
        rule = {"item": "Supplier Response Annex", "format": "Separate Document"}
        docs = build_submission_documents([rule])
        self.assertEqual(len(docs), 1)
        self.assertNotIn("mandatory", docs[0])

    # Test S: mandatory=0 -> mandatory=0 preserved
    def test_S_mandatory_zero_preserved(self):
        rule = {
            "item": "Appendix A (Confidential Information Declaration)",
            "format": "Separate Document",
            "mandatory": 0,
        }
        docs = build_submission_documents([rule])
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["mandatory"], 0)

    # Test T: Source references merged on duplicate artifacts
    def test_T_source_refs_merged_on_duplicate_artifacts(self):
        rules = [
            {
                "item": "Annex 3 (Supplier Response)",
                "format": "Portal/Email",
                "mandatory": 1,
                "source_refs": [{"source_doc": "itt.pdf", "page": 10}],
            },
            {
                "item": "Annex 3 (Supplier Response)",
                "format": "Portal/Email",
                "mandatory": 1,
                "source_refs": [{"source_doc": "annex_3.docx", "page": 1}],
            },
        ]
        docs = build_submission_documents(rules)
        self.assertEqual(len(docs), 1)
        srefs = docs[0].get("source_refs", [])
        self.assertEqual(len(srefs), 2)
        s_docs = {s["source_doc"] for s in srefs}
        self.assertEqual(s_docs, {"itt.pdf", "annex_3.docx"})

    # Test U: Package containing both process instructions and artifacts on same channel
    def test_U_mixed_process_and_artifacts_same_channel(self):
        rules = [
            {"item": "Submission Portal", "format": "Portal/Email", "details": "Submit at https://tap.tcsapps.com"},
            {"item": "Annex 3 (Supplier Response)", "format": "Portal/Email", "mandatory": 1},
            {"item": "Portal Submission", "format": "Electronic Portal or Email", "details": "All bids via portal"},
        ]
        docs = build_submission_documents(rules)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["name"], "Annex 3 (Supplier Response)")


class TestSubmissionProvenancePipeline(unittest.TestCase):
    """
    Tests ensuring preservation across Stage A, Stage B, and Stage D.
    """

    def test_stage_a_aggregation_preserves_orthogonal_fields(self):
        chunks = [
            {
                "submission_rules": [
                    {
                        "item": "Annex 3 (Supplier Response)",
                        "format": "Portal/Email",
                        "artifact_type": "Proposal / Response",
                        "file_format": "DOCX",
                        "submission_channel": "Portal",
                        "mandatory": 1,
                        "source_refs": [{"source_doc": "chunk1.docx", "page": 1}],
                    }
                ]
            },
            {
                "submission_rules": [
                    {
                        "item": "Annex 3 (Supplier Response)",
                        "format": "Portal/Email",
                        "mandatory": 1,
                        "source_refs": [{"source_doc": "chunk2.docx", "page": 2}],
                    }
                ]
            },
        ]
        aggregated = aggregate_stage_a_facts(chunks, "doc1.docx")
        self.assertEqual(len(aggregated["submission_rules"]), 1)
        sr = aggregated["submission_rules"][0]
        self.assertEqual(sr["artifact_type"], "Proposal / Response")
        self.assertEqual(sr["file_format"], "DOCX")
        self.assertEqual(sr["submission_channel"], "Portal")
        self.assertEqual(len(sr["source_refs"]), 2)

    def test_stage_b_normalization_preserves_and_merges_across_documents(self):
        doc1_facts = {
            "submission_rules": [
                {
                    "item": "Annex 3 (Supplier Response)",
                    "format": "Portal/Email",
                    "artifact_type": "Proposal / Response",
                    "file_format": "DOCX",
                    "submission_channel": "Portal",
                    "mandatory": 1,
                    "source_doc": "doc1.docx",
                    "source_refs": [{"source_doc": "doc1.docx", "page": 1}],
                }
            ]
        }
        doc2_facts = {
            "submission_rules": [
                {
                    "item": "Annex 3 (Supplier Response)",
                    "format": "Portal/Email",
                    "mandatory": 1,
                    "source_doc": "doc2.docx",
                    "source_refs": [{"source_doc": "doc2.docx", "page": 4}],
                }
            ]
        }
        normalized = normalize_package_facts([doc1_facts, doc2_facts], {"files": ["doc1.docx", "doc2.docx"]})
        self.assertEqual(len(normalized["submission_rules"]), 1)
        sr = normalized["submission_rules"][0]
        self.assertEqual(sr["artifact_type"], "Proposal / Response")
        self.assertEqual(len(sr["source_refs"]), 2)

    def test_stage_d_authoritative_rebuild_preserves_orthogonal_fields(self):
        normalized_facts = {
            "submission_rules": [
                {
                    "item": "Annex 3 (Supplier Response)",
                    "format": "Portal/Email",
                    "details": "Complete supplier response",
                    "mandatory": 1,
                    "artifact_type": "Proposal / Response",
                    "file_format": "DOCX",
                    "submission_channel": "Portal",
                    "source_refs": [{"source_doc": "annex_3.docx", "page": 1}],
                }
            ]
        }
        mock_synth = {
            "bid": {},
            "brief": {
                # Hallucinated submission_requirements missing the annex
                "submission_requirements": [
                    {"item": "Hallucinated Generic Document", "format": "PDF"}
                ]
            },
        }
        rebuilt = apply_stage_d_authoritative_sections(mock_synth, normalized_facts)
        sub_reqs = rebuilt["brief"]["submission_requirements"]
        self.assertEqual(len(sub_reqs), 1)
        self.assertEqual(sub_reqs[0]["item"], "Annex 3 (Supplier Response)")
        self.assertEqual(sub_reqs[0]["artifact_type"], "Proposal / Response")
        self.assertEqual(sub_reqs[0]["file_format"], "DOCX")
        self.assertEqual(sub_reqs[0]["submission_channel"], "Portal")
