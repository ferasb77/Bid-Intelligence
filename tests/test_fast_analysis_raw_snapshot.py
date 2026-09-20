"""
tests/test_fast_analysis_raw_snapshot.py

Deterministic tests for the raw Fast-Analysis-result durability feature
(migrations/012_fast_analysis_result_snapshot.sql,
fast_analysis.serialize_fast_analysis_result /
deserialize_fast_analysis_result, and analysis_service.py's persist-before-
lossy-transformation and zero-LLM-call regeneration path). No live API
calls, no live Supabase connection anywhere in this file.

Covers the durability gap discovered during the Phoenix offline closure
task: a completed run's FastAnalysisResult (minimum-score thresholds,
qualification mechanisms, tie-break ranks, deterministic service-scope and
Response-Guideline parses, and every field's own provenance) was being
computed, used to build the lossy structured_intelligence/
report_content_snapshot, and then discarded -- with no durable way to
reconstruct it for a future report regeneration or acceptance run without
another live LLM call.
"""
import unittest
from unittest.mock import MagicMock, patch

from fast_analysis import (
    FastAnalysisResult,
    serialize_fast_analysis_result,
    deserialize_fast_analysis_result,
    RawSnapshotSchemaError,
    FAST_ANALYSIS_RAW_SNAPSHOT_SCHEMA_VERSION,
)


def _rich_result() -> FastAnalysisResult:
    """A FastAnalysisResult exercising every field the raw snapshot must
    preserve, including the specific shapes that motivated this feature:
    minimum-score thresholds, qualification mechanisms, tie-break ranks
    (each with their own source_refs provenance), and the two deterministic
    (zero-LLM) structural parsers' output."""
    r = FastAnalysisResult()
    r.doc_metadata_by_doc = {
        "RFP.pdf": {"title": "Coaching Services RFP", "client": "Some Buyer", "file_number": "RFP-1"},
    }
    r.typed_observations = [
        {"family": "QUALIFICATION_MECHANISM", "semantic_kind": "REFERENCE_CHECK",
         "original_value": "At least two positive references required to remain eligible.",
         "source_refs": [{"doc": "RFP.pdf", "page": 12}], "rank": None},
        {"family": "TIE_BREAK_RULE", "semantic_kind": "TIE_BREAK_CRITERION",
         "original_value": "Account Management & Relationship score governs first.",
         "source_refs": [{"doc": "RFP.pdf", "page": 14}], "rank": 1},
        {"family": "TIE_BREAK_RULE", "semantic_kind": "TIE_BREAK_CRITERION",
         "original_value": "Approach & Methodology score governs next.",
         "source_refs": [{"doc": "RFP.pdf", "page": 14}], "rank": 2},
    ]
    r.evaluation_criteria = [
        {"criterion_label": "Approach and Methodology", "weight": "10 points",
         "threshold": "6 points", "evaluation_role": "Award Criterion",
         "source_refs": [{"doc": "RFP.pdf", "page": 9}]},
    ]
    r.requirements = [{"description": "Submit a completed Appendix B.", "source_refs": []}]
    r.commercial_clauses = [{"clause_type": "Term", "text": "2 years", "source_refs": []}]
    r.evaluation_occurrences = [{"criterion_label": "Approach", "weight": "10 points"}]
    r.pricing_occurrences = [{"line_item": "Hourly Rate", "weight": "15 points"}]
    r.focused_sections_found = {"rated_criteria": ["RFP.pdf"]}
    r.page_limits = {"RFP.pdf": 40}
    r.skipped_documents = ["Terms_and_Conditions_Boilerplate.pdf"]
    r.batched_documents = ["Appendix_C.pdf", "Appendix_D.pdf"]
    r.documents_by_route = {"ROUTE_IDENTITY_EVAL_REQ": ["RFP.pdf"]}
    r.ambiguities = {"OTHER_DATE": []}
    r.telemetry = [
        {"call_kind": "initial", "filename": "RFP.pdf", "input_tokens": 1000, "output_tokens": 200},
        {"call_kind": "recovery", "filename": "RFP.pdf", "input_tokens": 300, "output_tokens": 50},
    ]
    r.wall_seconds = 238.99
    r.deterministic_seconds = 1.23
    r.buyer_intelligence = {"buyer_identity": "Some Buyer", "source_refs": []}
    r.deterministic_service_scope = {
        "trigger_sentence": "The Services will include providing the following:",
        "items": ["Coaching", "Resources", "Group Sessions"],
        "source_page": 4,
    }
    r.deterministic_response_guidelines = [
        {"id": "RG1", "weight": "10", "minimum_score": "6",
         "evidence_prompts": ["Describe your approach."], "source_doc": "Appendix_B.docx"},
    ]
    return r


class TestSerializeDeserializeRoundTrip(unittest.TestCase):

    def test_full_round_trip_preserves_every_field(self):
        original = _rich_result()
        payload = serialize_fast_analysis_result(original, engine_version="fast-analysis-v4")
        restored = deserialize_fast_analysis_result(payload)

        self.assertEqual(restored.doc_metadata_by_doc, original.doc_metadata_by_doc)
        self.assertEqual(restored.typed_observations, original.typed_observations)
        self.assertEqual(restored.evaluation_criteria, original.evaluation_criteria)
        self.assertEqual(restored.requirements, original.requirements)
        self.assertEqual(restored.commercial_clauses, original.commercial_clauses)
        self.assertEqual(restored.evaluation_occurrences, original.evaluation_occurrences)
        self.assertEqual(restored.pricing_occurrences, original.pricing_occurrences)
        self.assertEqual(restored.focused_sections_found, original.focused_sections_found)
        self.assertEqual(restored.page_limits, original.page_limits)
        self.assertEqual(restored.skipped_documents, original.skipped_documents)
        self.assertEqual(restored.batched_documents, original.batched_documents)
        self.assertEqual(restored.documents_by_route, original.documents_by_route)
        self.assertEqual(restored.ambiguities, original.ambiguities)
        self.assertEqual(restored.wall_seconds, original.wall_seconds)
        self.assertEqual(restored.deterministic_seconds, original.deterministic_seconds)
        self.assertEqual(restored.buyer_intelligence, original.buyer_intelligence)

    def test_deterministic_service_scope_survives_round_trip(self):
        original = _rich_result()
        payload = serialize_fast_analysis_result(original, engine_version="fast-analysis-v4")
        restored = deserialize_fast_analysis_result(payload)
        self.assertEqual(restored.deterministic_service_scope, original.deterministic_service_scope)
        self.assertEqual(restored.deterministic_service_scope["items"],
                         ["Coaching", "Resources", "Group Sessions"])

    def test_deterministic_response_guidelines_survive_round_trip(self):
        original = _rich_result()
        payload = serialize_fast_analysis_result(original, engine_version="fast-analysis-v4")
        restored = deserialize_fast_analysis_result(payload)
        self.assertEqual(restored.deterministic_response_guidelines,
                         original.deterministic_response_guidelines)
        self.assertEqual(restored.deterministic_response_guidelines[0]["minimum_score"], "6")

    def test_minimum_score_threshold_survives_round_trip(self):
        original = _rich_result()
        payload = serialize_fast_analysis_result(original, engine_version="fast-analysis-v4")
        restored = deserialize_fast_analysis_result(payload)
        self.assertEqual(restored.evaluation_criteria[0]["threshold"], "6 points")

    def test_qualification_mechanism_survives_round_trip(self):
        original = _rich_result()
        payload = serialize_fast_analysis_result(original, engine_version="fast-analysis-v4")
        restored = deserialize_fast_analysis_result(payload)
        qual = [o for o in restored.typed_observations if o["family"] == "QUALIFICATION_MECHANISM"]
        self.assertEqual(len(qual), 1)
        self.assertEqual(qual[0]["semantic_kind"], "REFERENCE_CHECK")
        self.assertIn("references", qual[0]["original_value"])

    def test_tie_break_rank_survives_round_trip(self):
        original = _rich_result()
        payload = serialize_fast_analysis_result(original, engine_version="fast-analysis-v4")
        restored = deserialize_fast_analysis_result(payload)
        tie_breaks = sorted(
            (o for o in restored.typed_observations if o["family"] == "TIE_BREAK_RULE"),
            key=lambda o: o["rank"])
        self.assertEqual([t["rank"] for t in tie_breaks], [1, 2])
        self.assertIn("Account Management", tie_breaks[0]["original_value"])

    def test_provenance_source_refs_survive_round_trip(self):
        original = _rich_result()
        payload = serialize_fast_analysis_result(original, engine_version="fast-analysis-v4")
        restored = deserialize_fast_analysis_result(payload)
        self.assertEqual(restored.typed_observations[0]["source_refs"],
                         [{"doc": "RFP.pdf", "page": 12}])
        self.assertEqual(restored.evaluation_criteria[0]["source_refs"],
                         [{"doc": "RFP.pdf", "page": 9}])

    def test_telemetry_is_not_stored_verbatim_only_summarized(self):
        original = _rich_result()
        payload = serialize_fast_analysis_result(original, engine_version="fast-analysis-v4")
        self.assertNotIn("telemetry", payload["result"])
        summary = payload["telemetry_summary"]
        self.assertEqual(summary["total_calls"], 2)
        self.assertEqual(summary["input_tokens"], 1300)
        self.assertEqual(summary["output_tokens"], 250)
        restored = deserialize_fast_analysis_result(payload)
        self.assertEqual(restored.telemetry, [])  # never reconstructed from a summary

    def test_envelope_carries_schema_version_and_engine_version(self):
        payload = serialize_fast_analysis_result(_rich_result(), engine_version="fast-analysis-v4")
        self.assertEqual(payload["schema_version"], FAST_ANALYSIS_RAW_SNAPSHOT_SCHEMA_VERSION)
        self.assertEqual(payload["analysis_engine_version"], "fast-analysis-v4")
        self.assertIn("created_at", payload)


class TestBackwardAndForwardCompatibility(unittest.TestCase):

    def test_missing_optional_fields_fall_back_to_dataclass_defaults(self):
        payload = {
            "schema_version": "1.0",
            "created_at": "2026-01-01T00:00:00+00:00",
            "analysis_engine_version": "fast-analysis-v4",
            "telemetry_summary": {},
            "result": {"wall_seconds": 100.0},  # everything else absent
        }
        restored = deserialize_fast_analysis_result(payload)
        self.assertEqual(restored.wall_seconds, 100.0)
        self.assertEqual(restored.typed_observations, [])
        self.assertIsNone(restored.buyer_intelligence)
        self.assertEqual(restored.deterministic_response_guidelines, [])

    def test_unknown_future_fields_in_result_are_ignored_not_fatal(self):
        payload = {
            "schema_version": "1.0",
            "created_at": "2026-01-01T00:00:00+00:00",
            "analysis_engine_version": "fast-analysis-v4",
            "telemetry_summary": {},
            "result": {"wall_seconds": 50.0, "a_field_added_by_a_future_minor_version": "xyz"},
        }
        restored = deserialize_fast_analysis_result(payload)
        self.assertEqual(restored.wall_seconds, 50.0)
        self.assertFalse(hasattr(restored, "a_field_added_by_a_future_minor_version"))

    def test_unsupported_future_major_schema_version_fails_safely(self):
        payload = {
            "schema_version": "99.0",
            "created_at": "2026-01-01T00:00:00+00:00",
            "analysis_engine_version": "fast-analysis-v4",
            "telemetry_summary": {},
            "result": {},
        }
        with self.assertRaises(RawSnapshotSchemaError):
            deserialize_fast_analysis_result(payload)

    def test_missing_envelope_entirely_fails_safely(self):
        with self.assertRaises(RawSnapshotSchemaError):
            deserialize_fast_analysis_result({"result": {}})  # no schema_version
        with self.assertRaises(RawSnapshotSchemaError):
            deserialize_fast_analysis_result({"schema_version": "1.0"})  # no result
        with self.assertRaises(RawSnapshotSchemaError):
            deserialize_fast_analysis_result("not even a dict")

    def test_result_not_a_dict_fails_safely(self):
        payload = {"schema_version": "1.0", "result": ["not", "a", "dict"]}
        with self.assertRaises(RawSnapshotSchemaError):
            deserialize_fast_analysis_result(payload)


class TestNoMasquerading(unittest.TestCase):
    """structured_intelligence and report_content_snapshot are real,
    already-persisted dicts on the same analysis_results row this feature
    adds a column to -- they use entirely different, downstream schemas and
    must never be silently accepted as if they were a raw snapshot."""

    def test_report_content_snapshot_shape_cannot_masquerade(self):
        # Real shape confirmed live against Phoenix run 13's persisted
        # report_content_snapshot: TITLE/SUBTITLE_1/EVAL_WEIGHTS/... keys,
        # no schema_version, no 'result' envelope.
        report_content_snapshot = {
            "TITLE": "Bid Intelligence Preview", "SUBTITLE_1": "Coaching Services RFP",
            "EVAL_WEIGHTS": {"Category 1": [["Approach", "10 points"]]},
            "GATE_EXAMPLES": ["Proposal in English: Mandatory compliance required"],
            "SERVICE_CATEGORIES": [],
        }
        with self.assertRaises(RawSnapshotSchemaError):
            deserialize_fast_analysis_result(report_content_snapshot)

    def test_structured_intelligence_shape_cannot_masquerade(self):
        # Real shape confirmed live against Phoenix run 13's persisted
        # structured_intelligence: evaluation/source_map/ambiguities/
        # fact_origins/... keys, an entirely different downstream schema.
        structured_intelligence = {
            "evaluation": {"weighted_criteria": []},
            "source_map": {"documents": []},
            "ambiguities": [],
            "fact_origins": {},
            "opportunity_snapshot": {"buyer": "Some Buyer"},
        }
        with self.assertRaises(RawSnapshotSchemaError):
            deserialize_fast_analysis_result(structured_intelligence)


class TestAnalysisServiceRawSnapshotPersistence(unittest.TestCase):
    """analysis_service.py integration -- mocked database.py, no live
    Supabase connection, same convention as tests/test_analysis_service.py."""

    def _docs(self):
        return [{"id": 10, "bid_id": 1, "name": "RFP.pdf", "doc_type": "RFP / Source",
                 "version": 1, "storage_path": "1/abc.pdf"}]

    @patch("model_telemetry.bridge_fast_analysis_telemetry")
    @patch("analysis_service.db")
    @patch("analysis_service.extract_document_with_metadata")
    @patch("analysis_service.run_fast_analysis_corpus")
    def test_raw_snapshot_is_persisted_before_completion(self, mock_run, mock_extract, mock_db,
                                                          mock_bridge):
        import analysis_service as svc
        mock_db.download_file.return_value = b"bytes"
        mock_extract.return_value = ("text", {})
        mock_run.return_value = _rich_result()
        mock_db.upload_analysis_report.return_value = "path.pdf"
        mock_db.create_analysis_result.return_value = {"fast_analysis_result_snapshot": {"ok": True}}

        svc._execute_fast_analysis_run(run_id=1, bid_id=1, docs=self._docs(), api_key="fake")

        mock_db.create_analysis_result.assert_called_once()
        _, kwargs = mock_db.create_analysis_result.call_args
        snapshot = kwargs["fast_analysis_result_snapshot"]
        self.assertEqual(snapshot["schema_version"], FAST_ANALYSIS_RAW_SNAPSHOT_SCHEMA_VERSION)
        self.assertEqual(snapshot["result"]["deterministic_service_scope"]["items"],
                         ["Coaching", "Resources", "Group Sessions"])

        statuses = [c.args[1].get("status") for c in mock_db.update_analysis_run.call_args_list
                   if "status" in c.args[1]]
        self.assertIn("COMPLETE", statuses)

    @patch("model_telemetry.bridge_fast_analysis_telemetry")
    @patch("analysis_service.db")
    @patch("analysis_service.extract_document_with_metadata")
    @patch("analysis_service.run_fast_analysis_corpus")
    def test_raw_snapshot_persistence_failure_fails_the_run_not_complete(
        self, mock_run, mock_extract, mock_db, mock_bridge
    ):
        """Fail-closed (instruction 6): create_analysis_result 'succeeding'
        with no actual snapshot value on the returned row must mark the run
        FAILED, never COMPLETE -- a silently lossy durability guarantee is
        worse than a visibly failed run."""
        import analysis_service as svc
        mock_db.download_file.return_value = b"bytes"
        mock_extract.return_value = ("text", {})
        mock_run.return_value = _rich_result()
        mock_db.upload_analysis_report.return_value = "path.pdf"
        mock_db.create_analysis_result.return_value = {"fast_analysis_result_snapshot": None}

        svc._execute_fast_analysis_run(run_id=1, bid_id=1, docs=self._docs(), api_key="fake")

        statuses = [c.args[1].get("status") for c in mock_db.update_analysis_run.call_args_list
                   if "status" in c.args[1]]
        self.assertIn("FAILED", statuses)
        self.assertNotIn("COMPLETE", statuses)

    @patch("model_telemetry.bridge_fast_analysis_telemetry")
    @patch("analysis_service.db")
    @patch("analysis_service.extract_document_with_metadata")
    @patch("analysis_service.run_fast_analysis_corpus")
    def test_create_analysis_result_returning_none_also_fails_the_run(
        self, mock_run, mock_extract, mock_db, mock_bridge
    ):
        import analysis_service as svc
        mock_db.download_file.return_value = b"bytes"
        mock_extract.return_value = ("text", {})
        mock_run.return_value = _rich_result()
        mock_db.upload_analysis_report.return_value = "path.pdf"
        mock_db.create_analysis_result.return_value = None

        svc._execute_fast_analysis_run(run_id=1, bid_id=1, docs=self._docs(), api_key="fake")

        statuses = [c.args[1].get("status") for c in mock_db.update_analysis_run.call_args_list
                   if "status" in c.args[1]]
        self.assertIn("FAILED", statuses)
        self.assertNotIn("COMPLETE", statuses)


class TestLoadRawFastAnalysisResult(unittest.TestCase):

    @patch("analysis_service.db")
    def test_old_run_with_no_snapshot_is_explicitly_unavailable(self, mock_db):
        """Phoenix run 13's exact situation: an analysis_results row exists,
        but was created before this column did."""
        import analysis_service as svc
        mock_db.get_analysis_result.return_value = {
            "structured_intelligence": {"evaluation": {}}, "report_content_snapshot": {"TITLE": "x"},
            "fast_analysis_result_snapshot": None,
        }
        result = svc.load_raw_fast_analysis_result(run_id=13)
        self.assertEqual(result, svc.RAW_FAST_ANALYSIS_SNAPSHOT_UNAVAILABLE)

    @patch("analysis_service.db")
    def test_no_analysis_result_row_at_all_is_explicitly_unavailable(self, mock_db):
        import analysis_service as svc
        mock_db.get_analysis_result.return_value = None
        result = svc.load_raw_fast_analysis_result(run_id=999)
        self.assertEqual(result, svc.RAW_FAST_ANALYSIS_SNAPSHOT_UNAVAILABLE)

    @patch("analysis_service.db")
    def test_compatible_snapshot_reconstructs_a_real_result(self, mock_db):
        import analysis_service as svc
        payload = serialize_fast_analysis_result(_rich_result(), engine_version="fast-analysis-v4")
        mock_db.get_analysis_result.return_value = {"fast_analysis_result_snapshot": payload}
        result = svc.load_raw_fast_analysis_result(run_id=1)
        self.assertIsInstance(result, FastAnalysisResult)
        self.assertEqual(result.deterministic_service_scope["items"],
                         ["Coaching", "Resources", "Group Sessions"])

    @patch("analysis_service.db")
    def test_incompatible_schema_version_raises_not_treated_as_unavailable(self, mock_db):
        """A present-but-incompatible snapshot is a different failure mode
        from an absent one -- must raise, never silently collapse to the
        same sentinel as 'no snapshot at all'."""
        import analysis_service as svc
        mock_db.get_analysis_result.return_value = {
            "fast_analysis_result_snapshot": {"schema_version": "99.0", "result": {}},
        }
        with self.assertRaises(RawSnapshotSchemaError):
            svc.load_raw_fast_analysis_result(run_id=1)


class TestRegenerateReportFromRawSnapshot(unittest.TestCase):

    @patch("analysis_service.db")
    @patch("analysis_service.run_fast_analysis_corpus")
    def test_regeneration_makes_zero_provider_calls(self, mock_run, mock_db):
        import analysis_service as svc
        payload = serialize_fast_analysis_result(_rich_result(), engine_version="fast-analysis-v4")
        mock_db.get_analysis_run.return_value = {"id": 1, "status": "COMPLETE"}
        mock_db.get_analysis_result.return_value = {"fast_analysis_result_snapshot": payload}

        pdf_bytes = svc.regenerate_report_from_raw_snapshot(run_id=1)

        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        mock_run.assert_not_called()

    @patch("analysis_service.db")
    def test_regeneration_rejects_incomplete_run(self, mock_db):
        import analysis_service as svc
        mock_db.get_analysis_run.return_value = {"id": 1, "status": "ANALYZING"}
        with self.assertRaises(ValueError):
            svc.regenerate_report_from_raw_snapshot(run_id=1)

    @patch("analysis_service.db")
    def test_regeneration_rejects_run_with_no_snapshot(self, mock_db):
        """This is exactly Phoenix run 13's situation -- COMPLETE, but no
        durable raw snapshot exists, so regeneration must refuse rather
        than fabricate or fall back to the lossy structured_intelligence/
        report_content_snapshot."""
        import analysis_service as svc
        mock_db.get_analysis_run.return_value = {"id": 13, "status": "COMPLETE"}
        mock_db.get_analysis_result.return_value = {"fast_analysis_result_snapshot": None}
        with self.assertRaises(ValueError) as ctx:
            svc.regenerate_report_from_raw_snapshot(run_id=13)
        self.assertIn(svc.RAW_FAST_ANALYSIS_SNAPSHOT_UNAVAILABLE, str(ctx.exception))

    @patch("analysis_service._render_pdf_bytes", return_value=b"%PDF-fake")
    @patch("analysis_service.build_fast_report_content")
    @patch("analysis_service.db")
    def test_buyer_intelligence_override_is_applied(self, mock_db, mock_build, mock_render):
        import analysis_service as svc
        result = _rich_result()
        result.buyer_intelligence = None
        payload = serialize_fast_analysis_result(result, engine_version="fast-analysis-v4")
        mock_db.get_analysis_run.return_value = {"id": 1, "status": "COMPLETE"}
        mock_db.get_analysis_result.return_value = {"fast_analysis_result_snapshot": payload}

        override = {"buyer_identity": "Overridden Buyer", "source_refs": []}
        svc.regenerate_report_from_raw_snapshot(run_id=1, buyer_intelligence=override)

        passed_result = mock_build.call_args[0][0]
        self.assertEqual(passed_result.buyer_intelligence, override)


class TestTenantIsolationThroughNormalServiceBoundary(unittest.TestCase):
    """The raw snapshot must be reachable ONLY through the same
    require_bid_access + run-belongs-to-bid double-check every other
    privileged analysis_service call goes through (tenancy.py) -- never a
    new, unguarded path."""

    def test_raw_snapshot_functions_never_call_get_client_directly(self):
        """analysis_service.py's raw-snapshot functions must read only
        through database.py's public accessors (db.get_analysis_run /
        db.get_analysis_result) -- the same access path, and therefore the
        same access boundary, as every other analysis-result read in this
        codebase. A function that reached into database.get_client() or a
        raw table() call directly would bypass that boundary."""
        import inspect
        import analysis_service as svc
        src = inspect.getsource(svc.load_raw_fast_analysis_result)
        src += inspect.getsource(svc.regenerate_report_from_raw_snapshot)
        self.assertNotIn("get_client", src)
        self.assertNotIn(".table(", src)

    @patch("tenancy.db.get_client")
    def test_unauthorized_org_cannot_reach_raw_snapshot_at_all(self, mock_get_client):
        import tenancy
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = \
            MagicMock(data=[])  # bid not owned by this organization
        mock_get_client.return_value = sb

        with patch("analysis_service.regenerate_report_from_raw_snapshot") as mock_regen:
            with self.assertRaises(tenancy.AccessDeniedError):
                tenancy.get_raw_snapshot_report_for_organization(8, 6, "org-999-unrelated")
            mock_regen.assert_not_called()

    @patch("tenancy.db.get_analysis_run")
    @patch("tenancy.db.get_client")
    def test_authorized_org_but_run_from_different_bid_is_denied(self, mock_get_client, mock_get_run):
        import tenancy
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = \
            MagicMock(data=[{"id": 8, "organization_id": "org-1"}])  # caller owns bid 8
        mock_get_client.return_value = sb
        mock_get_run.return_value = {"id": 6, "bid_id": 999}  # but run 6 belongs to bid 999

        with patch("analysis_service.regenerate_report_from_raw_snapshot") as mock_regen:
            with self.assertRaises(tenancy.AccessDeniedError):
                tenancy.get_raw_snapshot_report_for_organization(8, 6, "org-1")
            mock_regen.assert_not_called()

    @patch("tenancy.db.get_analysis_run")
    @patch("tenancy.db.get_client")
    def test_authorized_org_and_matching_bid_succeeds(self, mock_get_client, mock_get_run):
        import tenancy
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = \
            MagicMock(data=[{"id": 8, "organization_id": "org-1"}])
        mock_get_client.return_value = sb
        mock_get_run.return_value = {"id": 6, "bid_id": 8}

        with patch("analysis_service.regenerate_report_from_raw_snapshot",
                   return_value=b"%PDF-fake") as mock_regen:
            result = tenancy.get_raw_snapshot_report_for_organization(8, 6, "org-1")
            self.assertEqual(result, b"%PDF-fake")
            mock_regen.assert_called_once_with(6, buyer_intelligence=None)


if __name__ == "__main__":
    unittest.main()
