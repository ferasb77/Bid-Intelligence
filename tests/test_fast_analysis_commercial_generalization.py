"""
tests/test_fast_analysis_commercial_generalization.py

Deterministic tests for the Product Integration Phase 5 commercial-
extraction generalization fix in fast_analysis.py (run_fast_analysis_corpus
step 2c). No live API calls -- the Anthropic client is mocked via
`fast_analysis.get_anthropic_client`.

Root cause (diagnosed, not assumed -- see the Phase 5 report S7):
_IDENTITY_EVAL_REQ_SCHEMA explicitly instructs the model "do not extract
commercial clauses". This is correct for Bank of Canada's own master RFP,
whose commercial terms live entirely in a separate ROUTE_COMMERCIAL_ONLY
document (Appendix G). For any corpus with no DOCUMENT_ROUTING match at
all (confirmed live in Phase 4 against a real, different procurement),
EVERY document -- including whichever one bundles its own commercial
clauses alongside its identity/evaluation content -- is routed to
ROUTE_IDENTITY_EVAL_REQ, so those commercial facts were never requested by
any schema and never extracted.

The fix adds exactly one additional, UNMODIFIED ROUTE_COMMERCIAL_ONLY pass
(same schema, same extract_fast_document machinery) per
ROUTE_IDENTITY_EVAL_REQ-routed document. These tests prove it is dispatched,
merges only into commercial_clauses, and does not touch or duplicate that
document's own existing ROUTE_IDENTITY_EVAL_REQ extraction.
"""
import unittest
from unittest.mock import MagicMock, patch

from fast_analysis import (
    run_fast_analysis_corpus, ROUTE_IDENTITY_EVAL_REQ, ROUTE_COMMERCIAL_ONLY,
    ROUTE_EVAL_ONLY,
)

GENERIC_DOC = "document1.pdf"  # not in DOCUMENT_ROUTING -> ROUTE_IDENTITY_EVAL_REQ
D1_DOC = "OriginalRevision/RFP 2026-026 - Appendix D1 - Rated criteria response form.docx"  # ROUTE_EVAL_ONLY
APPENDIX_G = "OriginalRevision/RFP 2026-06 - Appendix G - Form of Agreement.docx"  # ROUTE_COMMERCIAL_ONLY


def _route_specific_stub(name, text, api_key, *, route=None, client=None, telemetry=None):
    """Stand-in for fast_analysis.extract_fast_document -- returns a
    minimal, route-shaped payload so the merge logic in
    run_fast_analysis_corpus has something real to work with, without any
    live API call. Distinguishes the additive commercial_supplement pass
    (route=ROUTE_COMMERCIAL_ONLY) from a document's own natural route by
    the `route` kwarg the dispatcher actually passed."""
    if telemetry is not None:
        telemetry.append({"call_index": len(telemetry), "call_kind": "initial", "filename": name,
                          "route": route, "model": "stub", "request_bytes": 0, "chunk_chars": len(text),
                          "call_started_at": None, "call_ended_at": None, "latency_seconds": 0.0,
                          "input_tokens": 10, "output_tokens": 10, "stop_reason": "end_turn",
                          "parse_status": "OK", "error": None,
                          "parent_call_index": None, "split_trigger_reason": None})
    if route == ROUTE_COMMERCIAL_ONLY:
        return {"commercial_clauses": [{"clause_kind": "INSURANCE",
                                        "source_fact": f"Insurance clause from {name}"}]}
    if route == ROUTE_IDENTITY_EVAL_REQ:
        return {"doc_metadata": {"client": "Example Agency", "title": "Example Opportunity"},
               "typed_observations": [], "evaluation_criteria": [{"stage": "Fees", "weight": "20%"}],
               "requirements": [{"category": "Mandatory", "description": "Submit by email"}]}
    if route == ROUTE_EVAL_ONLY:
        return {"evaluation_criteria": [{"stage": "Corporate Profile", "weight": "5 pts"}]}
    return {}


class TestCommercialSupplementDispatch(unittest.TestCase):

    @patch("fast_analysis.get_anthropic_client")
    @patch("fast_analysis.extract_fast_document", side_effect=_route_specific_stub)
    def test_identity_routed_document_gets_an_additive_commercial_pass(self, mock_extract, mock_get_client):
        mock_get_client.return_value = MagicMock()

        result = run_fast_analysis_corpus([(GENERIC_DOC, "some procurement text")],
                                          api_key="fake", max_document_concurrency=1)

        routes_called = sorted(c.kwargs.get("route") for c in mock_extract.call_args_list)
        self.assertEqual(routes_called, sorted([ROUTE_IDENTITY_EVAL_REQ, ROUTE_COMMERCIAL_ONLY]))
        self.assertEqual(len(result.commercial_clauses), 1)
        self.assertEqual(result.commercial_clauses[0]["clause_kind"], "INSURANCE")
        self.assertEqual(result.commercial_clauses[0]["source_doc"], GENERIC_DOC)

    @patch("fast_analysis.get_anthropic_client")
    @patch("fast_analysis.extract_fast_document", side_effect=_route_specific_stub)
    def test_identity_document_s_own_fields_are_unaffected_by_the_supplement(self, mock_extract, mock_get_client):
        """The additive pass must not alter or duplicate anything the
        document's own, unmodified ROUTE_IDENTITY_EVAL_REQ call already
        contributed -- doc_metadata/evaluation_criteria/requirements come
        only from that one, original call."""
        mock_get_client.return_value = MagicMock()

        result = run_fast_analysis_corpus([(GENERIC_DOC, "some procurement text")],
                                          api_key="fake", max_document_concurrency=1)

        self.assertEqual(result.doc_metadata_by_doc[GENERIC_DOC]["client"], "Example Agency")
        self.assertEqual(len(result.evaluation_criteria), 1)
        self.assertEqual(len(result.requirements), 1)

    @patch("fast_analysis.get_anthropic_client")
    @patch("fast_analysis.extract_fast_document", side_effect=_route_specific_stub)
    def test_dedicated_commercial_only_document_does_not_get_a_redundant_second_pass(self, mock_extract, mock_get_client):
        """A document that already has its own ROUTE_COMMERCIAL_ONLY route
        (Bank of Canada's own Appendix G) must not also receive the
        additive supplement -- that would be a real duplicate call, not
        merely a no-op. Only ROUTE_IDENTITY_EVAL_REQ documents get it."""
        mock_get_client.return_value = MagicMock()

        run_fast_analysis_corpus([(APPENDIX_G, "commercial terms text")],
                                 api_key="fake", max_document_concurrency=1)

        calls_for_appendix_g = [c for c in mock_extract.call_args_list if c.args[0] == APPENDIX_G]
        self.assertEqual(len(calls_for_appendix_g), 1)
        self.assertEqual(calls_for_appendix_g[0].kwargs.get("route"), ROUTE_COMMERCIAL_ONLY)

    @patch("fast_analysis.get_anthropic_client")
    @patch("fast_analysis.extract_fast_document", side_effect=_route_specific_stub)
    def test_eval_only_document_does_not_get_a_commercial_supplement(self, mock_extract, mock_get_client):
        """Only the broad ROUTE_IDENTITY_EVAL_REQ fallback needs the
        supplement -- a narrowly-routed EVAL_ONLY document (e.g. Bank of
        Canada's own D1/D2/D3 forms) was never asked to skip commercial
        content in the first place (its schema doesn't request identity or
        commercial data at all), so it gets no additional pass."""
        mock_get_client.return_value = MagicMock()

        run_fast_analysis_corpus([(D1_DOC, "rated criteria text")],
                                 api_key="fake", max_document_concurrency=1)

        calls_for_d1 = [c for c in mock_extract.call_args_list if c.args[0] == D1_DOC]
        self.assertEqual(len(calls_for_d1), 1)
        self.assertEqual(calls_for_d1[0].kwargs.get("route"), ROUTE_EVAL_ONLY)

    @patch("fast_analysis.get_anthropic_client")
    @patch("fast_analysis.extract_fast_document", side_effect=_route_specific_stub)
    def test_commercial_supplement_reaches_on_task_done_with_its_own_kind(self, mock_extract, mock_get_client):
        mock_get_client.return_value = MagicMock()
        seen_kinds = []

        def _on_task_done(kind, payload, task_result):
            seen_kinds.append(kind)

        run_fast_analysis_corpus([(GENERIC_DOC, "some procurement text")], api_key="fake",
                                 max_document_concurrency=1, on_task_done=_on_task_done)

        self.assertIn("commercial_supplement", seen_kinds)

    @patch("fast_analysis.get_anthropic_client")
    @patch("fast_analysis.extract_fast_document", side_effect=_route_specific_stub)
    def test_multiple_identity_routed_documents_each_get_their_own_supplement(self, mock_extract, mock_get_client):
        """Confirms the additive pass is per-document, not a single global
        extra call -- matters for a corpus (like CDA-AMC's) where several
        documents all fall back to ROUTE_IDENTITY_EVAL_REQ."""
        mock_get_client.return_value = MagicMock()

        result = run_fast_analysis_corpus(
            [(GENERIC_DOC, "text one"), ("document2.pdf", "text two")],
            api_key="fake", max_document_concurrency=2)

        commercial_calls = [c for c in mock_extract.call_args_list
                            if c.kwargs.get("route") == ROUTE_COMMERCIAL_ONLY]
        self.assertEqual(len(commercial_calls), 2)
        self.assertEqual(len(result.commercial_clauses), 2)


if __name__ == "__main__":
    unittest.main()
