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


class TestGenericIntegrityPass(unittest.TestCase):
    """
    Tests covering Pre-PR Generic Integrity Pass items:
    1. Authoritative Orthogonal Fields
    2. Separation of Physical Format from Independence Signals
    3. Removal of Channel Language from Hard Negatives
    4. Controlled Channel Normalization
    5. No Synthetic / Manufactured Source Provenance
    6. Sheet-Aware Provenance Identity
    7. Preservation of Observation Conflicts Across Stage A -> B
    8. Canonical Item Identity
    9. Use artifact_type for doc_type
    """

    # Item 1: Authoritative Orthogonal Fields
    def test_item1_authoritative_process_instruction_with_format_pdf(self):
        # item="Submission Naming Convention", artifact_type="Process Instruction", file_format="PDF" -> PROCESS_ONLY
        res = classify_submission_rule(
            item="Submission Naming Convention",
            artifact_type="Process Instruction",
            file_format="PDF",
        )
        self.assertEqual(res["classification"], "PROCESS_ONLY")
        self.assertFalse(res["is_concrete_document"])

    def test_item1_authoritative_online_form_embedded_response(self):
        # item="Supplier Questionnaire", artifact_type="Questionnaire / Workbook", file_format="Online Form", channel="Portal"
        res = classify_submission_rule(
            item="Supplier Questionnaire",
            artifact_type="Questionnaire / Workbook",
            file_format="Online Form",
            submission_channel="Portal",
        )
        self.assertEqual(res["classification"], "EMBEDDED_RESPONSE")
        self.assertFalse(res["is_concrete_document"])

    def test_item1_authoritative_signed_declaration(self):
        # item="Signed Declaration", artifact_type="Declaration / Certification", file_format="PDF", channel="Email"
        res = classify_submission_rule(
            item="Signed Declaration",
            artifact_type="Declaration / Certification",
            file_format="PDF",
            submission_channel="Email",
        )
        self.assertEqual(res["classification"], "ARTIFACT")
        self.assertTrue(res["is_concrete_document"])

    def test_item1_authoritative_evidence_attachment_unspecified_format(self):
        # item="OEM Authorization Letter", artifact_type="Evidence / Attachment", file_format="Unspecified", channel="Portal"
        res = classify_submission_rule(
            item="OEM Authorization Letter",
            artifact_type="Evidence / Attachment",
            file_format="Unspecified",
            submission_channel="Portal",
        )
        self.assertEqual(res["classification"], "ARTIFACT")
        self.assertTrue(res["is_concrete_document"])

    # Item 2: Separation of Physical Format from Independence Signals
    def test_item2_separate_document_not_in_file_format(self):
        res = classify_submission_rule(
            item="Annex 3",
            fmt="Separate Document",
        )
        self.assertEqual(res["classification"], "ARTIFACT")
        self.assertTrue(res["is_concrete_document"])
        self.assertEqual(res["file_format"], "Unspecified")

    def test_item2_pdf_separate_document_format_precedence(self):
        res = classify_submission_rule(
            item="Annex 3",
            fmt="PDF / Separate Document",
        )
        self.assertEqual(res["classification"], "ARTIFACT")
        self.assertTrue(res["is_concrete_document"])
        self.assertEqual(res["file_format"], "PDF")

    def test_item2_xlsx_vs_xls_precedence(self):
        res = classify_submission_rule(
            item="Pricing Schedule",
            fmt="xlsx",
        )
        self.assertEqual(res["file_format"], "XLSX")

    # Item 3: Channel language in legacy format
    def test_item3_annex_electronic_bid_submission_format(self):
        res = classify_submission_rule(
            item="Annex 3 Supplier Response",
            fmt="Electronic Bid Submission",
        )
        self.assertEqual(res["classification"], "ARTIFACT")
        self.assertTrue(res["is_concrete_document"])
        self.assertIn(res["submission_channel"], ("Portal", "Upload", "E-procurement"))

    def test_item3_pure_electronic_bid_submission_header(self):
        res = classify_submission_rule(
            item="Electronic Bid Submission",
            fmt="Electronic Bid Submission",
        )
        self.assertEqual(res["classification"], "PROCESS_ONLY")
        self.assertFalse(res["is_concrete_document"])

    # Item 4: Deterministic controlled channel mapping
    def test_item4_upload_channel_mapping(self):
        res = classify_submission_rule(
            item="Pricing Document",
            fmt="Upload",
            details="upload file to system",
        )
        self.assertEqual(res["submission_channel"], "Upload")

    def test_item4_merx_maps_to_portal(self):
        res = classify_submission_rule(
            item="Proposal Document",
            submission_channel="merx",
            file_format="PDF",
        )
        self.assertEqual(res["submission_channel"], "Portal")

    # Item 5: No synthetic / manufactured source provenance
    def test_item5_no_synthetic_source_refs_projected(self):
        rules = [
            {
                "item": "Annex 3 Supplier Response",
                "artifact_type": "Proposal / Response",
                "file_format": "DOCX",
                "submission_channel": "Portal",
                "source_refs": [],
            }
        ]
        docs = build_submission_documents(rules)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["source_refs"], [])
        self.assertEqual(docs[0]["provenance_state"], "UNVERIFIED")

    def test_item5_valid_source_refs_projected_verified(self):
        rules = [
            {
                "item": "Annex 3 Supplier Response",
                "artifact_type": "Proposal / Response",
                "file_format": "DOCX",
                "submission_channel": "Portal",
                "source_refs": [{"source_doc": "tender.pdf", "page": 5, "sheet": None, "section": "3.1", "excerpt": "Submit Annex 3"}],
            }
        ]
        docs = build_submission_documents(rules)
        self.assertEqual(len(docs), 1)
        self.assertEqual(len(docs[0]["source_refs"]), 1)
        self.assertEqual(docs[0]["provenance_state"], "VERIFIED")

    # Item 6: Sheet-aware provenance identity
    def test_item6_sheet_aware_provenance_distinct_sheets(self):
        df = {
            "submission_rules": [
                {
                    "item": "Pricing Schedule",
                    "artifact_type": "Pricing / Financial",
                    "file_format": "XLSX",
                    "source_refs": [
                        {"source_doc": "wb.xlsx", "page": None, "sheet": "Sheet1", "section": "Summary", "excerpt": "Costs"},
                        {"source_doc": "wb.xlsx", "page": None, "sheet": "Sheet2", "section": "Details", "excerpt": "Rates"},
                    ],
                }
            ]
        }
        meta = {"files": ["wb.xlsx"], "doc_metadata": {"wb.xlsx": {"sheets": ["Sheet1", "Sheet2"]}}}
        normalized = normalize_package_facts([df], meta)
        srefs = normalized["submission_rules"][0]["source_refs"]
        self.assertEqual(len(srefs), 2)
        sheets = {s.get("sheet") for s in srefs}
        self.assertEqual(sheets, {"Sheet1", "Sheet2"})

    # Item 7: Preservation of Observation Conflicts Across Stage A -> B
    def test_item7_observation_conflicts_tracking(self):
        doc1_facts = {
            "submission_rules": [
                {
                    "item": "Annex 3 (Supplier Response)",
                    "artifact_type": "Proposal / Response",
                    "file_format": "DOCX",
                    "submission_channel": "Portal",
                    "mandatory": 1,
                    "source_refs": [{"source_doc": "doc1.docx", "page": 1}],
                }
            ]
        }
        doc2_facts = {
            "submission_rules": [
                {
                    "item": "Annex 3 (Supplier Response)",
                    "artifact_type": "Proposal / Response",
                    "file_format": "PDF",
                    "submission_channel": "Email",
                    "mandatory": 0,
                    "source_refs": [{"source_doc": "doc2.docx", "page": 2}],
                }
            ]
        }
        normalized = normalize_package_facts([doc1_facts, doc2_facts], {"files": ["doc1.docx", "doc2.docx"]})
        self.assertEqual(len(normalized["submission_rules"]), 1)
        sr = normalized["submission_rules"][0]
        self.assertTrue(sr["file_format_conflict"])
        self.assertTrue(sr["submission_channel_conflict"])
        self.assertTrue(sr["mandatory_conflict"])
        self.assertFalse(sr["artifact_type_conflict"])
        self.assertIn("DOCX", sr["file_format_observations"])
        self.assertIn("PDF", sr["file_format_observations"])

    # Item 8: Canonical item identity merges variants
    def test_item8_canonical_identity_merges_instruction_variants(self):
        doc1_facts = {
            "submission_rules": [
                {
                    "item": "Annex 3 (Supplier Response)",
                    "format": "DOCX",
                    "details": "Upload completed form to portal",
                }
            ]
        }
        doc2_facts = {
            "submission_rules": [
                {
                    "item": "Annex 3 - Supplier Response",
                    "format": "Email",
                    "details": "Also send copy by email",
                }
            ]
        }
        normalized = normalize_package_facts([doc1_facts, doc2_facts], {"files": []})
        self.assertEqual(len(normalized["submission_rules"]), 1)

    # Item 9: Use artifact_type for doc_type
    def test_item9_artifact_type_pricing_financial_sets_financial(self):
        rules = [
            {
                "item": "Annex 4",
                "artifact_type": "Pricing / Financial",
                "file_format": "XLSX",
                "submission_channel": "Portal",
            }
        ]
        docs = build_submission_documents(rules)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["doc_type"], "Financial")

    # Conflict Integrity & Permutation Invariance Tests A-H
    def test_conflict_A_consistent_format_no_conflict(self):
        rules = [
            {"item": "Proposal", "file_format": "PDF", "source_refs": [{"source_doc": "a.pdf"}]},
            {"item": "Proposal", "file_format": "PDF", "source_refs": [{"source_doc": "b.pdf"}]},
        ]
        docs = build_submission_documents(rules)
        self.assertEqual(len(docs), 1)
        doc = docs[0]
        self.assertEqual(doc["file_format"], "PDF")
        self.assertFalse(doc["file_format_conflict"])
        self.assertEqual(doc["file_format_observations"], ["PDF"])

    def test_conflict_B_format_conflict_multiple_mixed_and_permutation(self):
        rules_order1 = [
            {"item": "Proposal", "file_format": "PDF"},
            {"item": "Proposal", "file_format": "DOCX"},
        ]
        rules_order2 = [
            {"item": "Proposal", "file_format": "DOCX"},
            {"item": "Proposal", "file_format": "PDF"},
        ]
        docs1 = build_submission_documents(rules_order1)
        docs2 = build_submission_documents(rules_order2)
        for docs in (docs1, docs2):
            self.assertEqual(len(docs), 1)
            doc = docs[0]
            self.assertEqual(doc["file_format"], "Multiple / Mixed")
            self.assertTrue(doc["file_format_conflict"])
            self.assertEqual(set(doc["file_format_observations"]), {"PDF", "DOCX"})

    def test_conflict_C_channel_conflict_unspecified_and_permutation(self):
        rules_order1 = [
            {"item": "Submission Form", "submission_channel": "Portal"},
            {"item": "Submission Form", "submission_channel": "Email"},
        ]
        rules_order2 = [
            {"item": "Submission Form", "submission_channel": "Email"},
            {"item": "Submission Form", "submission_channel": "Portal"},
        ]
        docs1 = build_submission_documents(rules_order1)
        docs2 = build_submission_documents(rules_order2)
        for docs in (docs1, docs2):
            self.assertEqual(len(docs), 1)
            doc = docs[0]
            self.assertEqual(doc["submission_channel"], "Unspecified")
            self.assertTrue(doc["submission_channel_conflict"])
            self.assertEqual(set(doc["submission_channel_observations"]), {"Portal", "Email"})

    def test_conflict_D_mandatory_conflict_omits_key_and_permutation(self):
        rules_order1 = [
            {"item": "Safety Policy Document", "file_format": "PDF", "mandatory": 1},
            {"item": "Safety Policy Document", "file_format": "PDF", "mandatory": 0},
        ]
        rules_order2 = [
            {"item": "Safety Policy Document", "file_format": "PDF", "mandatory": 0},
            {"item": "Safety Policy Document", "file_format": "PDF", "mandatory": 1},
        ]
        docs1 = build_submission_documents(rules_order1)
        docs2 = build_submission_documents(rules_order2)
        for docs in (docs1, docs2):
            self.assertEqual(len(docs), 1)
            doc = docs[0]
            self.assertNotIn("mandatory", doc)
            self.assertTrue(doc["mandatory_conflict"])
            self.assertEqual(set(doc["mandatory_observations"]), {0, 1})

    def test_conflict_E_artifact_type_conflict_unknown_doc_type_no_arbitrary_winner(self):
        rules_order1 = [
            {"item": "Annex 3", "artifact_type": "Form / Annex"},
            {"item": "Annex 3", "artifact_type": "Pricing / Financial"},
        ]
        rules_order2 = [
            {"item": "Annex 3", "artifact_type": "Pricing / Financial"},
            {"item": "Annex 3", "artifact_type": "Form / Annex"},
        ]
        docs1 = build_submission_documents(rules_order1)
        docs2 = build_submission_documents(rules_order2)
        for docs in (docs1, docs2):
            self.assertEqual(len(docs), 1)
            doc = docs[0]
            self.assertEqual(doc["artifact_type"], "Unknown")
            self.assertTrue(doc["artifact_type_conflict"])
            self.assertEqual(set(doc["artifact_type_observations"]), {"Form / Annex", "Pricing / Financial"})
            # "Annex 3" has no pricing keywords, so doc_type falls back to Submission, not arbitrary Pricing
            self.assertEqual(doc["doc_type"], "Submission")

    def test_conflict_F_artifact_type_conflict_with_pricing_keyword_sets_financial(self):
        rules = [
            {"item": "Pricing Schedule", "artifact_type": "Form / Annex"},
            {"item": "Pricing Schedule", "artifact_type": "Evidence / Attachment"},
        ]
        docs = build_submission_documents(rules)
        self.assertEqual(len(docs), 1)
        doc = docs[0]
        self.assertEqual(doc["artifact_type"], "Unknown")
        self.assertTrue(doc["artifact_type_conflict"])
        self.assertEqual(doc["doc_type"], "Financial")

    def test_conflict_G_duplicate_consistent_observations_no_false_conflict(self):
        rules = [
            {"item": "Doc A", "file_format": "PDF", "submission_channel": "Portal", "mandatory": 1, "artifact_type": "Proposal / Response"},
            {"item": "Doc A", "file_format": "PDF", "submission_channel": "Portal", "mandatory": 1, "artifact_type": "Proposal / Response"},
        ]
        docs = build_submission_documents(rules)
        self.assertEqual(len(docs), 1)
        doc = docs[0]
        self.assertFalse(doc["file_format_conflict"])
        self.assertFalse(doc["submission_channel_conflict"])
        self.assertFalse(doc["mandatory_conflict"])
        self.assertFalse(doc["artifact_type_conflict"])
        self.assertEqual(doc["file_format"], "PDF")
        self.assertEqual(doc["submission_channel"], "Portal")
        self.assertEqual(doc["mandatory"], 1)
        self.assertEqual(doc["artifact_type"], "Proposal / Response")

    def test_conflict_H_apply_stage_d_authoritative_sections_preserves_conflicts(self):
        normalized_facts = {
            "submission_rules": [
                {
                    "item": "Annex 3",
                    "file_format": "Multiple / Mixed",
                    "file_format_conflict": True,
                    "file_format_observations": ["PDF", "DOCX"],
                    "submission_channel": "Unspecified",
                    "submission_channel_conflict": True,
                    "submission_channel_observations": ["Portal", "Email"],
                    "artifact_type": "Unknown",
                    "artifact_type_conflict": True,
                    "artifact_type_observations": ["Form / Annex", "Pricing / Financial"],
                    "mandatory_conflict": True,
                    "mandatory_observations": [0, 1],
                    "source_refs": [{"source_doc": "a.docx"}],
                }
            ]
        }
        synth_data = {"brief": {}}
        rebuilt = apply_stage_d_authoritative_sections(synth_data, normalized_facts)
        sub_reqs = rebuilt["brief"]["submission_requirements"]
        self.assertEqual(len(sub_reqs), 1)
        req = sub_reqs[0]
        self.assertTrue(req["file_format_conflict"])
        self.assertEqual(req["file_format_observations"], ["PDF", "DOCX"])
        self.assertTrue(req["submission_channel_conflict"])
        self.assertEqual(req["submission_channel_observations"], ["Portal", "Email"])
        self.assertTrue(req["artifact_type_conflict"])
        self.assertEqual(req["artifact_type_observations"], ["Form / Annex", "Pricing / Financial"])
        self.assertTrue(req["mandatory_conflict"])
        self.assertEqual(req["mandatory_observations"], [0, 1])

