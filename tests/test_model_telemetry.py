"""
tests/test_model_telemetry.py

Deterministic tests for model_telemetry.py, config.execute_messages_create's
telemetry_context instrumentation, and the callers wired to it (analyst.py,
section_analyzer.py, extractor.py, analysis_service.py, embeddings.py).
No live API calls anywhere in this file -- every provider response is a
mocked object carrying realistic Anthropic `usage` fields.
"""
import unittest
from unittest.mock import MagicMock, patch

import model_telemetry as mt


def _mock_anthropic_response(input_tokens=100, output_tokens=50, stop_reason="end_turn",
                             cache_creation=None, cache_read=None, thinking_tokens=None):
    resp = MagicMock()
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    usage.cache_creation_input_tokens = cache_creation
    usage.cache_read_input_tokens = cache_read
    if thinking_tokens is not None:
        details = MagicMock()
        details.thinking_tokens = thinking_tokens
        usage.output_tokens_details = details
    else:
        usage.output_tokens_details = None
    resp.usage = usage
    resp.stop_reason = stop_reason
    resp.content = [MagicMock(text='{"ok": true}')]
    return resp


class TestBuildUsageEvent(unittest.TestCase):

    def test_minimal_success_event(self):
        event = mt.build_usage_event(workflow="analyst", operation="compliance_review",
                                     provider="anthropic", model="claude-haiku-4-5-20251001",
                                     status="SUCCESS", input_tokens=100, output_tokens=50)
        self.assertEqual(event["workflow"], "analyst")
        self.assertEqual(event["operation"], "compliance_review")
        self.assertEqual(event["input_tokens"], 100)
        self.assertEqual(event["output_tokens"], 50)
        self.assertEqual(event["schema_version"], mt.TELEMETRY_SCHEMA_VERSION)
        self.assertIn("created_at", event)

    def test_invalid_status_rejected(self):
        with self.assertRaises(ValueError):
            mt.build_usage_event(workflow="x", operation="y", provider="anthropic",
                                 model="m", status="MAYBE")

    def test_missing_usage_fields_stay_none_not_zero(self):
        event = mt.build_usage_event(workflow="x", operation="y", provider="anthropic",
                                     model="m", status="SUCCESS")
        self.assertIsNone(event["input_tokens"])
        self.assertIsNone(event["output_tokens"])
        self.assertIsNone(event["cache_creation_tokens"])
        self.assertIsNone(event["cache_read_tokens"])
        self.assertIsNone(event["reasoning_tokens"])

    def test_metadata_over_size_ceiling_is_dropped(self):
        huge = {"blob": "x" * 5000}
        event = mt.build_usage_event(workflow="x", operation="y", provider="anthropic",
                                     model="m", status="SUCCESS", metadata=huge)
        self.assertIsNone(event["metadata"])

    def test_small_metadata_preserved(self):
        small = {"route": "ROUTE_EVAL_ONLY"}
        event = mt.build_usage_event(workflow="x", operation="y", provider="anthropic",
                                     model="m", status="SUCCESS", metadata=small)
        self.assertEqual(event["metadata"], small)

    def test_no_prompt_or_response_field_exists_in_schema(self):
        event = mt.build_usage_event(workflow="x", operation="y", provider="anthropic",
                                     model="m", status="SUCCESS")
        for forbidden in ("prompt", "response", "text", "system", "messages", "content"):
            self.assertNotIn(forbidden, event)


class TestExtractAnthropicUsage(unittest.TestCase):

    def test_all_fields_present(self):
        resp = _mock_anthropic_response(input_tokens=1000, output_tokens=200,
                                        cache_creation=50, cache_read=30, thinking_tokens=15)
        fields = mt._extract_anthropic_usage(resp)
        self.assertEqual(fields["input_tokens"], 1000)
        self.assertEqual(fields["output_tokens"], 200)
        self.assertEqual(fields["cache_creation_tokens"], 50)
        self.assertEqual(fields["cache_read_tokens"], 30)
        self.assertEqual(fields["reasoning_tokens"], 15)
        self.assertEqual(fields["stop_reason"], "end_turn")

    def test_cache_and_reasoning_fields_absent_stay_none(self):
        resp = _mock_anthropic_response(input_tokens=100, output_tokens=50)
        fields = mt._extract_anthropic_usage(resp)
        self.assertIsNone(fields["cache_creation_tokens"])
        self.assertIsNone(fields["cache_read_tokens"])
        self.assertIsNone(fields["reasoning_tokens"])

    def test_never_derives_tokens_from_anything_but_usage_object(self):
        """A response with a huge text body but a small reported usage
        must report exactly the small reported usage -- never inflated
        from content length."""
        resp = _mock_anthropic_response(input_tokens=5, output_tokens=3)
        resp.content = [MagicMock(text="x" * 100000)]
        fields = mt._extract_anthropic_usage(resp)
        self.assertEqual(fields["input_tokens"], 5)
        self.assertEqual(fields["output_tokens"], 3)


class TestRecordUsageEvent(unittest.TestCase):

    @patch("database.create_model_usage_event")
    def test_success_persists_and_clears_last_error(self, mock_create):
        mock_create.return_value = {"id": 1}
        event = mt.build_usage_event(workflow="x", operation="y", provider="anthropic",
                                     model="m", status="SUCCESS")
        row = mt.record_usage_event(event)
        self.assertEqual(row, {"id": 1})
        self.assertIsNone(mt.get_last_persistence_error())

    @patch("database.create_model_usage_event")
    def test_persistence_failure_never_raises_and_is_visible(self, mock_create):
        mock_create.side_effect = RuntimeError("db unavailable")
        event = mt.build_usage_event(workflow="x", operation="y", provider="anthropic",
                                     model="m", status="SUCCESS")
        row = mt.record_usage_event(event)  # must not raise
        self.assertIsNone(row)
        self.assertIsNotNone(mt.get_last_persistence_error())
        self.assertIn("db unavailable", mt.get_last_persistence_error())


class TestRecordFromAnthropicResponse(unittest.TestCase):

    @patch("database.create_model_usage_event")
    def test_one_call_creates_exactly_one_event(self, mock_create):
        mock_create.return_value = {"id": 1}
        resp = _mock_anthropic_response()
        context = {"workflow": "analyst", "operation": "compliance_review", "bid_id": 7}
        mt.record_from_anthropic_response(context, "claude-haiku-4-5-20251001", resp, 250)
        mock_create.assert_called_once()
        inserted = mock_create.call_args[0][0]
        self.assertEqual(inserted["workflow"], "analyst")
        self.assertEqual(inserted["operation"], "compliance_review")
        self.assertEqual(inserted["bid_id"], 7)
        self.assertEqual(inserted["status"], "SUCCESS")
        self.assertEqual(inserted["input_tokens"], 100)
        self.assertEqual(inserted["latency_ms"], 250)

    @patch("database.create_model_usage_event")
    def test_retry_number_attributed(self, mock_create):
        mock_create.return_value = {"id": 2}
        resp = _mock_anthropic_response()
        mt.record_from_anthropic_response({"workflow": "x", "operation": "y"}, "m", resp, 100,
                                          retry_number=1)
        inserted = mock_create.call_args[0][0]
        self.assertEqual(inserted["retry_number"], 1)


class TestRecordFailure(unittest.TestCase):

    @patch("database.create_model_usage_event")
    def test_failure_never_records_fake_usage(self, mock_create):
        mock_create.return_value = {"id": 3}
        import anthropic
        exc = anthropic.RateLimitError("rate limited", response=MagicMock(), body=None)
        mt.record_failure({"workflow": "analyst", "operation": "missing_evidence"}, "m", exc, 50)
        inserted = mock_create.call_args[0][0]
        self.assertEqual(inserted["status"], "FAILURE")
        self.assertIsNone(inserted["input_tokens"])
        self.assertIsNone(inserted["output_tokens"])
        self.assertEqual(inserted["error_category"], "RATE_LIMIT")


class TestExecuteMessagesCreateInstrumentation(unittest.TestCase):
    """config.execute_messages_create's telemetry_context parameter."""

    def test_omitting_telemetry_context_is_a_complete_no_op(self):
        from config import execute_messages_create
        mock_client = MagicMock()
        mock_client.messages.create.return_value = "raw response"
        with patch("model_telemetry.record_usage_event") as mock_record:
            result = execute_messages_create(mock_client, model="m", max_tokens=10,
                                            messages=[{"role": "user", "content": "hi"}])
        self.assertEqual(result, "raw response")
        mock_record.assert_not_called()

    def test_telemetry_context_never_reaches_the_api_call(self):
        from config import execute_messages_create
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_anthropic_response()
        with patch("database.create_model_usage_event", return_value={"id": 1}):
            execute_messages_create(mock_client, model="m", max_tokens=10,
                                    messages=[{"role": "user", "content": "hi"}],
                                    telemetry_context={"workflow": "x", "operation": "y"})
        call_kwargs = mock_client.messages.create.call_args.kwargs
        self.assertNotIn("telemetry_context", call_kwargs)
        self.assertNotIn("retry_number", call_kwargs)

    def test_one_successful_call_creates_exactly_one_event(self):
        from config import execute_messages_create
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_anthropic_response()
        with patch("database.create_model_usage_event", return_value={"id": 1}) as mock_create:
            execute_messages_create(mock_client, model="m", max_tokens=10,
                                    messages=[{"role": "user", "content": "hi"}],
                                    telemetry_context={"workflow": "x", "operation": "y"})
        mock_create.assert_called_once()

    def test_failure_creates_exactly_one_failure_event_and_reraises(self):
        from config import execute_messages_create
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = RuntimeError("boom")
        with patch("database.create_model_usage_event", return_value={"id": 1}) as mock_create:
            with self.assertRaises(RuntimeError):
                execute_messages_create(mock_client, model="m", max_tokens=10,
                                        messages=[{"role": "user", "content": "hi"}],
                                        telemetry_context={"workflow": "x", "operation": "y"})
        mock_create.assert_called_once()
        inserted = mock_create.call_args[0][0]
        self.assertEqual(inserted["status"], "FAILURE")

    def test_sanitization_of_disallowed_sampling_kwargs_still_happens_with_telemetry(self):
        from config import execute_messages_create
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_anthropic_response()
        with patch("database.create_model_usage_event", return_value={"id": 1}):
            execute_messages_create(mock_client, model="m", max_tokens=10, temperature=0.7,
                                    messages=[{"role": "user", "content": "hi"}],
                                    telemetry_context={"workflow": "x", "operation": "y"})
        call_kwargs = mock_client.messages.create.call_args.kwargs
        self.assertNotIn("temperature", call_kwargs)

    def test_no_request_content_in_recorded_event(self):
        from config import execute_messages_create
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_anthropic_response()
        with patch("database.create_model_usage_event", return_value={"id": 1}) as mock_create:
            execute_messages_create(mock_client, model="m", max_tokens=10,
                                    system="SECRET SYSTEM PROMPT TEXT",
                                    messages=[{"role": "user", "content": "SECRET USER TEXT"}],
                                    telemetry_context={"workflow": "x", "operation": "y"})
        inserted = mock_create.call_args[0][0]
        serialized = str(inserted)
        self.assertNotIn("SECRET SYSTEM PROMPT TEXT", serialized)
        self.assertNotIn("SECRET USER TEXT", serialized)


class TestAnalystWorkflowAttribution(unittest.TestCase):
    """Every one of analyst.py's 11 model-calling functions must attribute
    its own distinct operation -- never a collapsed 'analyst' bucket."""

    def _mock_and_call(self, fn, *args, **kwargs):
        with patch("analyst.get_anthropic_client"), \
             patch("analyst.execute_messages_create") as mock_exec, \
             patch("database.create_model_usage_event", return_value={"id": 1}) as mock_create:
            mock_exec.return_value = _mock_anthropic_response()
            mock_exec.side_effect = None
            # analyst._call parses JSON from the response text for most
            # callers -- give it valid JSON matching each function's needs
            # is out of scope here; we only assert on the telemetry
            # context passed to execute_messages_create, not on parsing.
            try:
                fn(*args, **kwargs)
            except Exception:
                pass
            return mock_exec

    def test_call_helper_passes_operation_through(self):
        import analyst
        with patch("analyst.get_anthropic_client"), patch("analyst.execute_messages_create") as mock_exec:
            mock_exec.return_value = _mock_anthropic_response()
            analyst._call("system", "user", operation="compliance_review", bid_id=5)
        _, kwargs = mock_exec.call_args
        self.assertEqual(kwargs["telemetry_context"]["workflow"], "analyst")
        self.assertEqual(kwargs["telemetry_context"]["operation"], "compliance_review")
        self.assertEqual(kwargs["telemetry_context"]["bid_id"], 5)

    def test_default_operation_is_not_silently_generic_when_unset(self):
        """If a call site forgets `operation=`, it must be visibly
        'unknown', not silently blank or 'analyst' -- a cheap regression
        guard against future call sites losing attribution."""
        import analyst
        with patch("analyst.get_anthropic_client"), patch("analyst.execute_messages_create") as mock_exec:
            mock_exec.return_value = _mock_anthropic_response()
            analyst._call("system", "user")
        _, kwargs = mock_exec.call_args
        self.assertEqual(kwargs["telemetry_context"]["operation"], "unknown")

    def test_every_call_site_in_analyst_py_passes_a_named_operation(self):
        """Structural guard: every `_call(...)` invocation in analyst.py's
        source (other than _call's own definition) must include an
        `operation=` keyword -- catches a future call site added without
        attribution before it ships."""
        import inspect
        import re
        import analyst
        src = inspect.getsource(analyst)
        call_sites = re.findall(r"(?<!def )_call\(([^)]*(?:\([^)]*\)[^)]*)*)\)", src)
        # Filter out the definition line itself and any nested nested nested
        # parens artifacts; every real call site must mention operation=.
        real_sites = [c for c in call_sites if "system" in c or "_SYSTEM" in c]
        self.assertGreater(len(real_sites), 5)
        for site in real_sites:
            self.assertIn("operation=", site, msg=f"call site missing operation=: {site[:80]}")


class TestSectionAnalyzerAttribution(unittest.TestCase):

    def test_call_attributes_workflow_and_operation(self):
        import section_analyzer as sa
        with patch("section_analyzer.get_anthropic_client"), \
             patch("section_analyzer.execute_messages_create") as mock_exec:
            mock_exec.return_value = _mock_anthropic_response()
            mock_exec.return_value.content = [MagicMock(text='{"direction": "ON_TRACK", '
                                                            '"summary": "", "requirement_assessments": [], '
                                                            '"response_guideline_assessments": [], "top_changes": []}')]
            sa._call_section_analyzer("prompt", set(), bid_id=8, section_id=101)
        _, kwargs = mock_exec.call_args
        self.assertEqual(kwargs["telemetry_context"]["workflow"], "section_analyzer")
        self.assertEqual(kwargs["telemetry_context"]["operation"], "formative_review")
        self.assertEqual(kwargs["telemetry_context"]["bid_id"], 8)

    def test_idempotent_reuse_creates_zero_telemetry_events(self):
        """The existing idempotency guard (find_matching_review) already
        prevents a redundant model call -- confirm that also means zero
        telemetry events, not a phantom one."""
        import section_analyzer as sa
        section = {"id": 1, "bid_id": 1, "title": "T", "notes": "", "word_limit": 100}
        current_hash = sa.content_hash("text")
        existing = {"id": 1, "section_content_hash": current_hash, "mapped_requirement_ids": [],
                   "based_on_procurement_revision": 1, "based_on_procurement_truth_status": "ungoverned",
                   "based_on_analysis_result_id": None}
        with patch("database.get_section_reviews", return_value=[existing]), \
             patch("database.get_requirements_by_ids", return_value=[]), \
             patch("section_analyzer.procurement_basis", return_value={
                 "procurement_revision": 1, "procurement_truth_status": "ungoverned",
                 "raw_snapshot": None, "raw_snapshot_run_id": None,
                 "raw_snapshot_result_id": None, "raw_snapshot_unavailable_reason": "x"}), \
             patch("section_analyzer.execute_messages_create") as mock_exec, \
             patch("database.create_model_usage_event") as mock_telemetry:
            sa.analyze_section(bid_id=1, section=section, section_text="text", mapped_requirement_ids=[])
        mock_exec.assert_not_called()
        mock_telemetry.assert_not_called()


class TestFastAnalysisBridgeNoDoubleCounting(unittest.TestCase):

    def test_bridge_creates_exactly_one_event_per_telemetry_entry(self):
        telemetry = [
            {"call_index": 0, "call_kind": "single", "filename": "a.pdf", "model": "m",
             "input_tokens": 100, "output_tokens": 50, "latency_seconds": 1.5,
             "stop_reason": "end_turn", "parse_status": "COMPLETE", "error": None,
             "request_bytes": 500, "chunk_chars": 2000},
            {"call_index": 1, "call_kind": "batch", "filename": "b.pdf+c.pdf", "model": "m",
             "input_tokens": 200, "output_tokens": 80, "latency_seconds": 2.0,
             "stop_reason": "end_turn", "parse_status": "COMPLETE", "error": None,
             "request_bytes": 800, "chunk_chars": 3000},
        ]
        with patch("database.create_model_usage_event", return_value={"id": 1}) as mock_create:
            recorded = mt.bridge_fast_analysis_telemetry(telemetry, bid_id=1, analysis_run_id=13)
        self.assertEqual(mock_create.call_count, 2)
        self.assertEqual(len(recorded), 2)

    def test_fast_analysis_py_never_passes_telemetry_context_itself(self):
        """Structural guard against double-counting: fast_analysis.py's own
        execute_messages_create call sites must never pass
        telemetry_context -- only the post-hoc bridge in
        analysis_service.py may turn its telemetry list into events."""
        import inspect
        import fast_analysis
        src = inspect.getsource(fast_analysis)
        self.assertNotIn("telemetry_context", src)

    def test_analysis_service_bridges_after_result_is_complete(self):
        import inspect
        import analysis_service
        src = inspect.getsource(analysis_service._execute_fast_analysis_run)
        self.assertIn("bridge_fast_analysis_telemetry", src)


class TestDeepVerifyTelemetry(unittest.TestCase):

    def test_bridge_creates_one_event_per_stage_a_entry(self):
        telemetry = [
            {"call_index": 0, "call_kind": "initial", "filename": "rfp.pdf", "model": "m",
             "input_tokens": 500, "output_tokens": 100, "latency_seconds": 3.0,
             "stop_reason": "end_turn", "parse_status": "COMPLETE", "error": None,
             "request_bytes": 1000, "chunk_chars": 4000, "record_counts": {"requirements": 5}},
        ]
        with patch("database.create_model_usage_event", return_value={"id": 1}) as mock_create:
            mt.bridge_deep_verify_telemetry(telemetry, bid_id=None)
        mock_create.assert_called_once()
        inserted = mock_create.call_args[0][0]
        self.assertEqual(inserted["workflow"], "deep_verify")

    def test_stage_a_telemetry_list_is_now_activated_in_extract_procurement_package(self):
        """Regression guard for the Phase 1 finding: extract_document_facts
        was called without a telemetry list, so Stage A's own capture code
        was dormant. Confirm the real orchestration now passes one."""
        import inspect
        import extractor
        src = inspect.getsource(extractor._extract_procurement_package)
        self.assertIn("telemetry=telemetry", src)
        self.assertIn("bridge_deep_verify_telemetry", src)

    def test_stage_d_call_site_has_telemetry_context(self):
        import inspect
        import extractor
        src = inspect.getsource(extractor._synthesize_projected_bid_brief)
        self.assertIn('"workflow": "deep_verify"', src)
        self.assertIn('"operation": "stage_d_synthesis"', src)


class TestEmbeddingTelemetry(unittest.TestCase):

    def test_success_records_total_tokens_when_sdk_reports_it(self):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.embeddings = [[0.1, 0.2]]
        mock_result.total_tokens = 42
        mock_client.embed.return_value = mock_result
        with patch("embeddings._get_voyage_client", return_value=mock_client), \
             patch("database.create_model_usage_event", return_value={"id": 1}) as mock_create:
            import embeddings
            embeddings.embed_text("some content library text")
        mock_create.assert_called_once()
        inserted = mock_create.call_args[0][0]
        self.assertEqual(inserted["provider"], "voyage")
        self.assertEqual(inserted["input_tokens"], 42)
        self.assertEqual(inserted["status"], "SUCCESS")

    def test_missing_total_tokens_stays_null_not_estimated(self):
        mock_client = MagicMock()
        mock_result = MagicMock(spec=["embeddings"])  # no total_tokens attribute at all
        mock_result.embeddings = [[0.1, 0.2]]
        mock_client.embed.return_value = mock_result
        with patch("embeddings._get_voyage_client", return_value=mock_client), \
             patch("database.create_model_usage_event", return_value={"id": 1}) as mock_create:
            import embeddings
            embeddings.embed_text("some content library text")
        inserted = mock_create.call_args[0][0]
        self.assertIsNone(inserted["input_tokens"])
        self.assertIn("input_chars", inserted)
        self.assertIsNotNone(inserted["input_chars"])

    def test_failure_records_failure_status_and_returns_none(self):
        mock_client = MagicMock()
        mock_client.embed.side_effect = RuntimeError("voyage down")
        with patch("embeddings._get_voyage_client", return_value=mock_client), \
             patch("database.create_model_usage_event", return_value={"id": 1}) as mock_create:
            import embeddings
            result = embeddings.embed_text("text")
        self.assertIsNone(result)  # existing degrade-gracefully contract preserved
        inserted = mock_create.call_args[0][0]
        self.assertEqual(inserted["status"], "FAILURE")
        self.assertIsNone(inserted["input_tokens"])

    def test_no_client_available_records_no_event(self):
        with patch("embeddings._get_voyage_client", return_value=None), \
             patch("database.create_model_usage_event") as mock_create:
            import embeddings
            result = embeddings.embed_text("text")
        self.assertIsNone(result)
        mock_create.assert_not_called()


class TestAggregation(unittest.TestCase):

    def test_summarize_events_sums_correctly(self):
        events = [
            {"input_tokens": 100, "output_tokens": 50, "cache_creation_tokens": None,
             "cache_read_tokens": None, "reasoning_tokens": None, "latency_ms": 200,
             "retry_number": 0, "status": "SUCCESS"},
            {"input_tokens": 200, "output_tokens": 80, "cache_creation_tokens": 10,
             "cache_read_tokens": 5, "reasoning_tokens": None, "latency_ms": 300,
             "retry_number": 1, "status": "SUCCESS"},
            {"input_tokens": None, "output_tokens": None, "cache_creation_tokens": None,
             "cache_read_tokens": None, "reasoning_tokens": None, "latency_ms": None,
             "retry_number": 0, "status": "FAILURE"},
        ]
        summary = mt._summarize_events(events)
        self.assertEqual(summary["calls"], 3)
        self.assertEqual(summary["failures"], 1)
        self.assertEqual(summary["retries"], 1)
        self.assertEqual(summary["input_tokens"], 300)
        self.assertEqual(summary["output_tokens"], 130)
        self.assertEqual(summary["cache_creation_tokens"], 10)
        self.assertEqual(summary["cache_read_tokens"], 5)

    def test_field_with_zero_contributing_events_stays_none(self):
        events = [{"input_tokens": 100, "output_tokens": 50, "cache_creation_tokens": None,
                  "cache_read_tokens": None, "reasoning_tokens": None, "latency_ms": None,
                  "retry_number": 0, "status": "SUCCESS"}]
        summary = mt._summarize_events(events)
        self.assertIsNone(summary["cache_creation_tokens"])
        self.assertIsNone(summary["reasoning_tokens"])

    @patch("database.get_model_usage_events")
    def test_summarize_for_run_filters_correctly(self, mock_get):
        mock_get.return_value = [{"input_tokens": 10, "output_tokens": 5, "cache_creation_tokens": None,
                                  "cache_read_tokens": None, "reasoning_tokens": None,
                                  "latency_ms": 100, "retry_number": 0, "status": "SUCCESS"}]
        mt.summarize_for_run(42)
        mock_get.assert_called_once_with(analysis_run_id=42, limit=10000)

    @patch("database.get_model_usage_events")
    def test_summarize_for_bid_breaks_down_by_workflow(self, mock_get):
        mock_get.return_value = [
            {"workflow": "fast_analysis", "input_tokens": 10, "output_tokens": 5,
             "cache_creation_tokens": None, "cache_read_tokens": None, "reasoning_tokens": None,
             "latency_ms": 100, "retry_number": 0, "status": "SUCCESS"},
            {"workflow": "section_analyzer", "input_tokens": 20, "output_tokens": 10,
             "cache_creation_tokens": None, "cache_read_tokens": None, "reasoning_tokens": None,
             "latency_ms": 200, "retry_number": 0, "status": "SUCCESS"},
        ]
        result = mt.summarize_for_bid(1083)
        self.assertEqual(set(result.keys()), {"fast_analysis", "section_analyzer"})
        self.assertEqual(result["fast_analysis"]["input_tokens"], 10)
        self.assertEqual(result["section_analyzer"]["input_tokens"], 20)

    @patch("database.get_model_usage_events")
    def test_top_operations_sorted_by_total_tokens_desc(self, mock_get):
        mock_get.return_value = [
            {"operation": "small_op", "input_tokens": 10, "output_tokens": 5,
             "cache_creation_tokens": None, "cache_read_tokens": None, "reasoning_tokens": None,
             "latency_ms": 100, "retry_number": 0, "status": "SUCCESS"},
            {"operation": "big_op", "input_tokens": 1000, "output_tokens": 500,
             "cache_creation_tokens": None, "cache_read_tokens": None, "reasoning_tokens": None,
             "latency_ms": 100, "retry_number": 0, "status": "SUCCESS"},
        ]
        top = mt.top_operations_for_workflow("fast_analysis")
        self.assertEqual(top[0][0], "big_op")
        self.assertEqual(top[1][0], "small_op")


class TestReportCLI(unittest.TestCase):

    @patch("model_telemetry.summarize_for_run")
    def test_run_id_mode_invokes_summarize_for_run(self, mock_summarize):
        mock_summarize.return_value = {"calls": 5, "failures": 0, "retries": 1,
                                       "input_tokens": 100, "output_tokens": 50,
                                       "cache_creation_tokens": None, "cache_read_tokens": None,
                                       "reasoning_tokens": None, "latency_ms": 500}
        import subprocess
        import sys as _sys
        # Import-and-call directly (no subprocess) to keep this fast and
        # avoid spawning a real process for a unit test.
        import importlib
        report_mod = importlib.import_module("scripts.model_usage_report")
        with patch.object(_sys, "argv", ["model_usage_report.py", "--run-id", "42"]):
            report_mod.main()
        mock_summarize.assert_called_once_with(42)

    def test_no_args_errors_cleanly(self):
        import importlib
        report_mod = importlib.import_module("scripts.model_usage_report")
        import sys as _sys
        with patch.object(_sys, "argv", ["model_usage_report.py"]):
            with self.assertRaises(SystemExit):
                report_mod.main()


class TestPrivacy(unittest.TestCase):

    def test_model_usage_event_keys_never_include_content_fields(self):
        import database
        forbidden = {"prompt", "response", "system", "messages", "content", "text",
                    "api_key", "authorization"}
        self.assertFalse(forbidden & set(database._MODEL_USAGE_EVENT_KEYS))

    def test_create_model_usage_event_drops_unknown_keys(self):
        import database as db
        mock_sb = MagicMock()
        mock_sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": 1}])
        with patch("database.get_client", return_value=mock_sb):
            db.create_model_usage_event({
                "workflow": "x", "operation": "y", "provider": "anthropic", "model": "m",
                "status": "SUCCESS", "prompt_text_leaked_by_mistake": "SECRET",
            })
        inserted = mock_sb.table.return_value.insert.call_args[0][0]
        self.assertNotIn("prompt_text_leaked_by_mistake", inserted)


class TestMigration014Contract(unittest.TestCase):
    """Static assertions on the migration file's own SQL text -- mirrors
    the convention in tests/test_tenant_rls_enforcement.py."""

    def setUp(self):
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "migrations",
                            "014_model_usage_events.sql")
        with open(path, encoding="utf-8") as f:
            self.sql = f.read().lower()

    def test_rls_is_enabled(self):
        self.assertIn("enable row level security", self.sql)

    def test_no_policy_grants_anon_or_authenticated_access(self):
        """Zero policies means anonymous and cross-organization access are
        both denied by the absence of any grant -- not by a predicate that
        could be wrong."""
        self.assertNotIn("create policy", self.sql)
        self.assertNotIn("to anon", self.sql)
        self.assertNotIn("to authenticated", self.sql)

    def test_no_prompt_or_response_column(self):
        """Check only the CREATE TABLE column definitions, not the file's
        own explanatory comments (which legitimately discuss why no such
        column exists -- checking raw text would false-positive on that
        prose)."""
        ddl_lines = [l for l in self.sql.splitlines() if not l.strip().startswith("--")]
        ddl_only = "\n".join(ddl_lines)
        for forbidden in ("prompt ", "response_text ", "request_text ", "api_key "):
            self.assertNotIn(forbidden, ddl_only)

    def test_does_not_touch_prior_migrations(self):
        self.assertNotIn("alter table analysis_results", self.sql)
        self.assertNotIn("alter table requirements", self.sql)
        self.assertNotIn("alter table bids", self.sql)


if __name__ == "__main__":
    unittest.main()
