"""
Phoenix Beta: an ungoverned bid has no bid_briefs row (FAST is advisory and
never writes one), so the UNDERSTAND Requirements tab must show what the
saved FAST result extracted instead of reporting that nothing was found.
Shapes below mirror a real saved structured_intelligence (2B OPCO ITB,
analysis run 21). Display-only: no writes, no model calls.
"""
import unittest

import pages.stage_understand as understand


_SI = {
    "response_requirements": {
        "checklist": [
            {"item": "Requirement 1", "notes": "ITB.pdf",
             "description": "Bid submission must be in English only."},
            {"item": "Requirement 2", "notes": "ITB.pdf",
             "description": "Bid Validity shall be for (180 days) after bid closing date."},
        ],
        "other_requirements": ["Bid Bond Value is USD: 15,000.00", "  "],
    },
    "evaluation": {
        "note": "", "stages": [], "raw_occurrences": [],
        "gate_examples": ["Proposal in English: Mandatory compliance required"],
        "weights_by_category": {},
    },
}


class TestFastRequirementFallback(unittest.TestCase):

    def test_extracted_requirements_and_gates_are_shown(self):
        sub_reqs, gates, weights = understand._fast_requirement_fallback(_SI)
        self.assertEqual([r["item"] for r in sub_reqs], [
            "Bid submission must be in English only.",
            "Bid Validity shall be for (180 days) after bid closing date.",
            "Bid Bond Value is USD: 15,000.00",
        ])
        self.assertEqual(sub_reqs[0]["details"], "ITB.pdf")
        self.assertEqual(gates, [{"type": "Mandatory",
                                  "requirement": "Proposal in English: Mandatory compliance required"}])
        self.assertEqual(weights, {})

    def test_published_weights_pass_through_unchanged(self):
        si = {"evaluation": {"weights_by_category": {
            "Rated Criteria": [{"criterion": "Methodology", "weight": "40%"},
                               {"criterion": "Price", "weight": "60%"}],
            "Empty": []}}}
        _, _, weights = understand._fast_requirement_fallback(si)
        self.assertEqual(list(weights), ["Rated Criteria"])
        self.assertEqual(weights["Rated Criteria"][1], {"criterion": "Price", "weight": "60%"})

    def test_nothing_extracted_yields_nothing(self):
        self.assertEqual(understand._fast_requirement_fallback({}), ([], [], {}))

    def test_source_text_is_html_escaped(self):
        si = {"response_requirements": {"checklist": [
            {"description": "Price <script>x</script> & terms", "notes": "a<b"}]}}
        sub_reqs, _, _ = understand._fast_requirement_fallback(si)
        self.assertNotIn("<script>", sub_reqs[0]["item"])
        self.assertIn("&amp;", sub_reqs[0]["item"])
        self.assertEqual(sub_reqs[0]["details"], "a&lt;b")


if __name__ == "__main__":
    unittest.main()
