"""
tests/test_stage_b_requirement_dedup_integrity.py

Focused tests for Stage B requirement deduplication integrity:
1. Pure Stage B requirement normalization tests (A through F):
   A. Long common prefix (>60 normalized chars), different suffix -> 2 normalized requirements.
   B. Exact material duplicate in same document -> 1 normalized requirement.
   C. Exact material duplicate across different physical documents -> 1 normalized requirement with both validated source refs.
   D. Same req_id, different descriptions -> 2 requirements.
   E. Punctuation/case-only variation -> 1 requirement.
   F. Empty/missing description -> safe handling, no collision key merging unrelated malformed records.

2. Cross-stage regression (Section 4):
   - Proving Stage A -> Stage B handoff preserves two distinct long-prefix requirements.
"""
import unittest
from extractor import normalize_package_facts, aggregate_stage_a_facts


class TestStageBRequirementDedupIntegrity(unittest.TestCase):
    """Test suite for Stage B requirement deduplication integrity."""

    def setUp(self):
        self.pkg_meta = {
            "files": ["doc_a.pdf", "doc_b.pdf"],
            "doc_metadata": {
                "doc_a.pdf": {"page_count": 20},
                "doc_b.pdf": {"page_count": 20},
            },
            "doc_texts": {
                "doc_a.pdf": "doc a text with ISO 9001 and security protocols and hardware assembly",
                "doc_b.pdf": "doc b text with ISO 9001 and security protocols and software testing",
            }
        }

    def test_A_long_common_prefix_different_suffix(self):
        """Two requirements with identical first >60 normalized chars but different suffixes must NOT collapse."""
        prefix = "The contractor and all dedicated team members shall strictly maintain certification under ISO 9001 "
        norm_prefix = "".join(c for c in prefix.lower() if c.isalnum())
        self.assertGreater(len(norm_prefix), 60, "Prefix must exceed 60 normalized characters")

        r1_desc = prefix + "specifically covering hardware manufacturing and assembly facilities."
        r2_desc = prefix + "specifically covering software quality assurance and continuous deployment."

        df = {
            "requirements": [
                {
                    "req_id": "M1",
                    "category": "Mandatory",
                    "description": r1_desc,
                    "source_refs": [{"source_doc": "doc_a.pdf", "page": 2, "excerpt": "hardware assembly"}]
                },
                {
                    "req_id": "M1",
                    "category": "Mandatory",
                    "description": r2_desc,
                    "source_refs": [{"source_doc": "doc_a.pdf", "page": 4, "excerpt": "software quality"}]
                },
            ]
        }

        normalized = normalize_package_facts([df], self.pkg_meta)
        reqs = normalized.get("requirements", [])
        self.assertEqual(len(reqs), 2, "Both requirements sharing >60 char prefix must survive Stage B normalization")
        self.assertEqual(reqs[0]["description"], r1_desc)
        self.assertEqual(reqs[1]["description"], r2_desc)

    def test_B_exact_material_duplicate_in_same_document(self):
        """Exact material duplicate within the same document must collapse to 1 requirement."""
        desc = "The supplier shall provide a dedicated bilingual project manager."
        df = {
            "requirements": [
                {
                    "req_id": "M1",
                    "category": "Mandatory",
                    "description": desc,
                    "source_refs": [{"source_doc": "doc_a.pdf", "page": 3, "excerpt": "dedicated bilingual"}]
                },
                {
                    "req_id": "M2",
                    "category": "Mandatory",
                    "description": desc,
                    "source_refs": [{"source_doc": "doc_a.pdf", "page": 3, "excerpt": "dedicated bilingual"}]
                },
            ]
        }

        normalized = normalize_package_facts([df], self.pkg_meta)
        reqs = normalized.get("requirements", [])
        self.assertEqual(len(reqs), 1, "Duplicate requirement must collapse to 1")
        self.assertEqual(len(reqs[0]["source_refs"]), 1)

    def test_C_exact_material_duplicate_across_different_physical_documents(self):
        """Exact material duplicate across different physical documents collapses to 1 requirement with both source refs."""
        desc = "The contractor must carry minimum $5,000,000 commercial general liability insurance."
        df1 = {
            "requirements": [
                {
                    "req_id": "M1",
                    "category": "Mandatory",
                    "description": desc,
                    "source_refs": [{"source_doc": "doc_a.pdf", "page": 5, "excerpt": "liability insurance"}]
                }
            ]
        }
        df2 = {
            "requirements": [
                {
                    "req_id": "M3",
                    "category": "Mandatory",
                    "description": desc,
                    "source_refs": [{"source_doc": "doc_b.pdf", "page": 12, "excerpt": "liability insurance"}]
                }
            ]
        }

        normalized = normalize_package_facts([df1, df2], self.pkg_meta)
        reqs = normalized.get("requirements", [])
        self.assertEqual(len(reqs), 1, "Duplicate across documents must collapse to 1")
        refs = reqs[0].get("source_refs", [])
        self.assertEqual(len(refs), 2, "Must preserve both distinct document references")
        docs = {r.get("source_doc") for r in refs}
        self.assertEqual(docs, {"doc_a.pdf", "doc_b.pdf"})

    def test_D_same_req_id_different_descriptions(self):
        """Different requirements sharing identical local req_id must NOT collapse."""
        df = {
            "requirements": [
                {
                    "req_id": "M1",
                    "category": "Mandatory",
                    "description": "Supplier must provide 3 client references.",
                    "source_refs": [{"source_doc": "doc_a.pdf", "page": 1, "excerpt": "3 client references"}]
                },
                {
                    "req_id": "M1",
                    "category": "Mandatory",
                    "description": "Supplier must provide audited financial statements for last 2 years.",
                    "source_refs": [{"source_doc": "doc_a.pdf", "page": 6, "excerpt": "audited financial"}]
                },
            ]
        }

        normalized = normalize_package_facts([df], self.pkg_meta)
        reqs = normalized.get("requirements", [])
        self.assertEqual(len(reqs), 2, "Distinct requirements sharing same req_id M1 must not collapse")

    def test_E_punctuation_case_only_variation(self):
        """Punctuation and case-only variation is normalized as materially identical."""
        desc1 = "The Supplier SHALL deliver all equipment, FOB Destination!"
        desc2 = "the supplier shall deliver all equipment fob destination"

        df = {
            "requirements": [
                {
                    "req_id": "M1",
                    "category": "Mandatory",
                    "description": desc1,
                    "source_refs": [{"source_doc": "doc_a.pdf", "page": 2, "excerpt": "deliver all equipment"}]
                },
                {
                    "req_id": "M2",
                    "category": "Mandatory",
                    "description": desc2,
                    "source_refs": [{"source_doc": "doc_a.pdf", "page": 7, "excerpt": "deliver all equipment"}]
                },
            ]
        }

        normalized = normalize_package_facts([df], self.pkg_meta)
        reqs = normalized.get("requirements", [])
        self.assertEqual(len(reqs), 1, "Case/punctuation variation must collapse as materially identical")

    def test_F_empty_missing_description(self):
        """Empty or missing description records must be safely ignored without creating collision keys."""
        df = {
            "requirements": [
                {"req_id": "M1", "category": "Mandatory", "description": ""},
                {"req_id": "M2", "category": "Rated", "description": "   "},
                {"req_id": "M3", "category": "Mandatory", "description": None},
                {"req_id": "M4", "category": "Mandatory", "description": "Valid requirement statement."},
            ]
        }

        normalized = normalize_package_facts([df], self.pkg_meta)
        reqs = normalized.get("requirements", [])
        self.assertEqual(len(reqs), 1, "Only valid non-empty requirement must be normalized")
        self.assertEqual(reqs[0]["description"], "Valid requirement statement.")


class TestCrossStageRequirementHandoff(unittest.TestCase):
    """Section 4: Cross-stage regression proving Stage A -> Stage B preserves distinct long-prefix requirements."""

    def test_stage_a_to_stage_b_preserves_distinct_long_prefix_requirements(self):
        prefix = "All proponents and their sub-contractors participating in this procurement must strictly adhere to the security screening policy "
        norm_prefix = "".join(c for c in prefix.lower() if c.isalnum())
        self.assertGreater(len(norm_prefix), 60, "Prefix must exceed 60 normalized characters")

        r1_desc = prefix + "which mandates Level 2 Secret clearance for all onsite personnel."
        r2_desc = prefix + "which mandates Reliability Status clearance for all remote personnel."

        chunk1 = {
            "requirements": [{
                "req_id": "M1",
                "category": "Mandatory",
                "rfso_ref": "Section 3.1",
                "description": r1_desc,
                "source_refs": [{"source_doc": "doc_a.pdf", "page": 3, "excerpt": "Level 2 Secret"}]
            }]
        }
        chunk2 = {
            "requirements": [{
                "req_id": "M1",
                "category": "Mandatory",
                "rfso_ref": "Section 3.1",
                "description": r2_desc,
                "source_refs": [{"source_doc": "doc_a.pdf", "page": 8, "excerpt": "Reliability Status"}]
            }]
        }

        # Step 1: Stage A aggregation
        stage_a_facts = aggregate_stage_a_facts([chunk1, chunk2], "doc_a.pdf")
        self.assertEqual(len(stage_a_facts["requirements"]), 2, "Stage A must preserve both distinct requirements")

        # Step 2: Stage B package normalization
        pkg_meta = {
            "files": ["doc_a.pdf"],
            "doc_metadata": {"doc_a.pdf": {"page_count": 20}},
            "doc_texts": {"doc_a.pdf": "doc a text containing security screening policy Level 2 Secret Reliability Status"}
        }
        stage_b_facts = normalize_package_facts([stage_a_facts], pkg_meta)

        # Step 3: Assert both remain through Stage B
        stage_b_reqs = stage_b_facts.get("requirements", [])
        self.assertEqual(len(stage_b_reqs), 2, "Stage B must NOT collapse distinct requirements sharing >60 char prefix")
        self.assertEqual(stage_b_reqs[0]["description"], r1_desc)
        self.assertEqual(stage_b_reqs[1]["description"], r2_desc)


if __name__ == "__main__":
    unittest.main()
