"""
tests/test_anthropic_client_config.py

Deterministic tests for the workspace-scoped-API-key fix: every runtime
path that talks to the Anthropic API must obtain its client through
config.get_anthropic_client() -- the single place that knows how to set
the `anthropic-workspace-id` header a workspace-scoped API key requires
-- never by constructing anthropic.Anthropic(...) directly. No live
network calls anywhere in this file; the anthropic SDK's own Anthropic
class is patched at the point config.py imports it, so these tests
observe exactly what arguments the real get_anthropic_client() logic
would pass to the SDK, without ever making a request.
"""
import os
import unittest
from unittest.mock import MagicMock, patch

import config
import analyst


class TestGetAnthropicClientWorkspaceHeader(unittest.TestCase):
    """config.get_anthropic_client() is the single source of truth for
    the anthropic-workspace-id header. Both branches (configured /
    unconfigured workspace) must produce a valid, working client."""

    def setUp(self):
        # Isolate from whatever the real environment/.env happens to have.
        self._env_patch = patch.dict(os.environ, {}, clear=False)
        self._env_patch.start()
        for var in ("ANTHROPIC_WORKSPACE_ID", "ANTHROPIC_API_KEY", "ANTHROPIC_CUSTOM_HEADERS"):
            os.environ.pop(var, None)

    def tearDown(self):
        self._env_patch.stop()

    @patch("anthropic.Anthropic")
    def test_configured_workspace_id_sets_the_header(self, mock_anthropic_cls):
        os.environ["ANTHROPIC_WORKSPACE_ID"] = "wrkspc_test123"
        config.get_anthropic_client(api_key="sk-ant-test")

        mock_anthropic_cls.assert_called_once()
        _, kwargs = mock_anthropic_cls.call_args
        self.assertEqual(kwargs.get("api_key"), "sk-ant-test")
        self.assertIsNotNone(kwargs.get("default_headers"))
        self.assertEqual(kwargs["default_headers"].get("anthropic-workspace-id"), "wrkspc_test123")

    @patch("anthropic.Anthropic")
    def test_no_workspace_id_configured_omits_the_header_and_still_works(self, mock_anthropic_cls):
        """Requirement: behavior remains valid when no workspace ID is
        configured -- a plain (non-workspace-scoped) API key must still
        produce a usable client, with no anthropic-workspace-id header
        forced onto a request that doesn't need or expect one."""
        config.get_anthropic_client(api_key="sk-ant-test")

        mock_anthropic_cls.assert_called_once()
        _, kwargs = mock_anthropic_cls.call_args
        self.assertEqual(kwargs.get("api_key"), "sk-ant-test")
        # No headers at all were configured -- default_headers must be
        # None (falsy), never an empty dict pretending to be "configured".
        self.assertIsNone(kwargs.get("default_headers"))

    @patch("anthropic.Anthropic")
    def test_custom_headers_merge_alongside_workspace_header(self, mock_anthropic_cls):
        os.environ["ANTHROPIC_WORKSPACE_ID"] = "wrkspc_test123"
        os.environ["ANTHROPIC_CUSTOM_HEADERS"] = '{"x-extra": "1"}'
        config.get_anthropic_client(api_key="sk-ant-test")

        _, kwargs = mock_anthropic_cls.call_args
        headers = kwargs["default_headers"]
        self.assertEqual(headers.get("anthropic-workspace-id"), "wrkspc_test123")
        self.assertEqual(headers.get("x-extra"), "1")


class TestAnalystUsesCentralAnthropicClient(unittest.TestCase):
    """analyst._call() -- and therefore every analyst.py function built
    on top of it, including the CHECK-stage Proposal Alignment Analyzer
    -- must obtain its client exclusively through
    config.get_anthropic_client(), never by constructing
    anthropic.Anthropic(...) itself. This is what actually failed live:
    a workspace-scoped key hit analyst.py's own bypassed construction
    and got a 400 with no anthropic-workspace-id header."""

    def test_analyst_module_has_no_direct_anthropic_import(self):
        """analyst.py must not import the anthropic SDK module at all --
        the only supported way to reach it is through config.py's single
        configured client. Guards against the bypass being reintroduced."""
        self.assertFalse(hasattr(analyst, "anthropic"),
                          "analyst.py must not import the anthropic SDK directly")
        self.assertTrue(hasattr(analyst, "get_anthropic_client"),
                         "analyst.py must import get_anthropic_client from config")

    @patch("analyst.get_anthropic_client")
    def test_call_obtains_its_client_through_get_anthropic_client(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="ok")]
        )
        mock_get_client.return_value = mock_client

        result = analyst._call("system prompt", "user prompt", max_tokens=123)

        mock_get_client.assert_called_once_with()
        mock_client.messages.create.assert_called_once()
        _, kwargs = mock_client.messages.create.call_args
        self.assertEqual(kwargs["model"], "claude-haiku-4-5-20251001")
        self.assertEqual(kwargs["max_tokens"], 123)
        self.assertEqual(kwargs["system"], "system prompt")
        self.assertEqual(result, "ok")

    @patch("anthropic.Anthropic")
    @patch("analyst.get_anthropic_client")
    def test_alignment_audit_never_constructs_an_unconfigured_client(self, mock_get_client, mock_anthropic_cls):
        """The exact live failure scenario: CHECK -> Proposal Alignment
        Analyzer -> analyze_proposal_alignment() -> _call() (x2). Proves
        the whole call chain goes through the mocked, centrally-
        configured client and the raw anthropic.Anthropic(...)
        constructor is never touched anywhere along the way."""
        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="{}")]
        )
        mock_get_client.return_value = mock_client

        result = analyst.analyze_proposal_alignment(
            proposal_text="Our proposal addresses all requirements.",
            requirements=[{"req_id": "M1", "category": "Mandatory", "description": "x"}],
            rfp_text="RFP text here.",
            bid_info={"title": "Test Bid", "client": "Test Client"},
        )

        self.assertIsInstance(result, dict)
        self.assertGreaterEqual(mock_get_client.call_count, 2)  # one per _call() (two-call audit)
        mock_anthropic_cls.assert_not_called()


class TestAnthropicRequestSanitizationAndClassification(unittest.TestCase):
    """Guards against regressions in model parameter stripping and error classification."""

    def test_sanitize_anthropic_kwargs_strips_sampling_parameters(self):
        kwargs = {
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 4000,
            "temperature": 0.0,
            "top_p": 0.9,
            "top_k": 40,
            "messages": [{"role": "user", "content": "hello"}],
        }
        sanitized = config.sanitize_anthropic_kwargs(kwargs)
        self.assertNotIn("temperature", sanitized)
        self.assertNotIn("top_p", sanitized)
        self.assertNotIn("top_k", sanitized)
        self.assertEqual(sanitized["model"], "claude-haiku-4-5-20251001")
        self.assertEqual(sanitized["max_tokens"], 4000)
        self.assertEqual(sanitized["messages"], kwargs["messages"])

    def test_execute_messages_create_delegates_without_sampling_keys(self):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(id="msg_123")

        resp = config.execute_messages_create(
            mock_client,
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            temperature=0.0,
            top_p=1.0,
            messages=[{"role": "user", "content": "ping"}],
        )

        self.assertEqual(resp.id, "msg_123")
        mock_client.messages.create.assert_called_once()
        _, passed_kwargs = mock_client.messages.create.call_args
        self.assertNotIn("temperature", passed_kwargs)
        self.assertNotIn("top_p", passed_kwargs)
        self.assertEqual(passed_kwargs["model"], "claude-haiku-4-5-20251001")

    def test_classify_anthropic_error_categories(self):
        import anthropic
        import httpx

        fake_request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        fake_response = httpx.Response(status_code=401, request=fake_request)

        # 1. Authentication error
        auth_err = anthropic.AuthenticationError(
            message="Invalid API key", response=fake_response, body=None
        )
        res = config.classify_anthropic_error(auth_err)
        self.assertEqual(res["category"], "AUTHENTICATION")
        self.assertIn("authentication", res["message"].lower())

        # 2. Rate limit error
        rl_err = anthropic.RateLimitError(
            message="Rate limit exceeded", response=fake_response, body=None
        )
        res = config.classify_anthropic_error(rl_err)
        self.assertEqual(res["category"], "RATE_LIMIT")

        # 3. Not found error
        nf_err = anthropic.NotFoundError(
            message="Model not found", response=fake_response, body=None
        )
        res = config.classify_anthropic_error(nf_err)
        self.assertEqual(res["category"], "NOT_FOUND")

        # 4. TypeError for temperature
        type_err = TypeError("Messages.create() got an unexpected keyword argument 'temperature'")
        res = config.classify_anthropic_error(type_err)
        self.assertEqual(res["category"], "INVALID_REQUEST")

        # 5. Generic Bad Request error
        br_err = anthropic.BadRequestError(
            message="Bad request", response=fake_response, body=None
        )
        res = config.classify_anthropic_error(br_err)
        self.assertEqual(res["category"], "INVALID_REQUEST")

        # 6. Generic unclassified error
        other_err = ValueError("JSON corruption")
        res = config.classify_anthropic_error(other_err)
        self.assertEqual(res["category"], "PROCESSING_ERROR")


if __name__ == "__main__":
    unittest.main()
