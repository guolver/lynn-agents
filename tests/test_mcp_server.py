"""mcp_server 纯逻辑与 HTTP 客户端单测（不依赖 mcp SDK 与真实网络）。"""

import io
import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from agent_hub.mcp_server import (
    PlatformClient,
    PlatformInvocationError,
    PlatformUnavailableError,
    build_tool_specs,
    normalize_input_schema,
    sanitize_tool_name,
)

DESCRIBED_AGENT = {
    "agent_id": "global-part-time",
    "name": "全球兼职职位匹配 Agent",
    "actions": [
        {
            "name": "list_sources",
            "description": "列出已登记来源",
            "mode": "read",
            "risk_level": "low",
            "requires_idempotency_key": False,
            "input_schema": {"type": "object"},
        },
        {
            "name": "send_digest",
            "description": "发送已经批准的通知草稿",
            "mode": "write",
            "risk_level": "high",
            "requires_idempotency_key": True,
            "input_schema": {"required": ["notification_id"]},
        },
    ],
}


class SanitizeToolNameTest(unittest.TestCase):
    def test_dashes_and_underscores_kept(self):
        self.assertEqual(
            sanitize_tool_name("global-part-time__list_sources"), "global-part-time__list_sources"
        )

    def test_illegal_chars_replaced(self):
        self.assertEqual(sanitize_tool_name("a.b/c d"), "a_b_c_d")

    def test_truncated_to_64(self):
        self.assertEqual(len(sanitize_tool_name("x" * 100)), 64)


class NormalizeInputSchemaTest(unittest.TestCase):
    def test_none_becomes_empty_object_schema(self):
        self.assertEqual(normalize_input_schema(None), {"type": "object", "properties": {}})

    def test_required_preserved_and_type_added(self):
        schema = normalize_input_schema({"required": ["candidate_id"]})
        self.assertEqual(schema["type"], "object")
        self.assertEqual(schema["required"], ["candidate_id"])
        self.assertEqual(schema["properties"], {})

    def test_existing_keys_not_overwritten(self):
        schema = normalize_input_schema({"type": "object", "properties": {"a": {"type": "string"}}})
        self.assertEqual(schema["properties"], {"a": {"type": "string"}})


class BuildToolSpecsTest(unittest.TestCase):
    def test_read_only_by_default(self):
        specs = build_tool_specs([DESCRIBED_AGENT])
        self.assertEqual([s.action for s in specs], ["list_sources"])

    def test_expose_write_includes_all_actions(self):
        specs = build_tool_specs([DESCRIBED_AGENT], expose_write=True)
        self.assertEqual([s.action for s in specs], ["list_sources", "send_digest"])

    def test_tool_name_joins_agent_and_action(self):
        specs = build_tool_specs([DESCRIBED_AGENT])
        self.assertEqual(specs[0].name, "global-part-time__list_sources")

    def test_description_carries_mode_and_risk(self):
        spec = build_tool_specs([DESCRIBED_AGENT], expose_write=True)[1]
        self.assertIn("mode=write", spec.description)
        self.assertIn("risk=high", spec.description)

    def test_idempotency_flag_passthrough(self):
        specs = build_tool_specs([DESCRIBED_AGENT], expose_write=True)
        self.assertFalse(specs[0].requires_idempotency_key)
        self.assertTrue(specs[1].requires_idempotency_key)


def _http_response(payload):
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    context = MagicMock()
    context.__enter__.return_value = response
    context.__exit__.return_value = False
    return context


class PlatformClientTest(unittest.TestCase):
    def setUp(self):
        self.client = PlatformClient("http://api.test/", actor="mcp-test")

    @patch("agent_hub.mcp_server.urlopen")
    def test_invoke_posts_payload_with_actor_header(self, urlopen_mock):
        urlopen_mock.return_value = _http_response({"result": {"ok": True}})
        result = self.client.invoke("global-part-time", "list_sources", {"a": 1})
        self.assertEqual(result, {"result": {"ok": True}})
        request = urlopen_mock.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "http://api.test/platform/v1/agents/global-part-time/actions/list_sources",
        )
        self.assertEqual(request.get_header("X-actor"), "mcp-test")
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"payload": {"a": 1}})
        self.assertIsNone(request.get_header("Idempotency-key"))

    @patch("agent_hub.mcp_server.urlopen")
    def test_invoke_sends_idempotency_key_when_given(self, urlopen_mock):
        urlopen_mock.return_value = _http_response({})
        self.client.invoke("global-part-time", "find_matches", {}, idempotency_key="k" * 8)
        request = urlopen_mock.call_args.args[0]
        self.assertEqual(request.get_header("Idempotency-key"), "k" * 8)

    @patch("agent_hub.mcp_server.urlopen")
    def test_http_error_maps_to_invocation_error_with_detail(self, urlopen_mock):
        urlopen_mock.side_effect = HTTPError(
            "http://api.test",
            422,
            "Unprocessable",
            None,
            io.BytesIO(json.dumps({"detail": "payload.candidate_id required"}).encode()),
        )
        with self.assertRaises(PlatformInvocationError) as ctx:
            self.client.invoke("global-part-time", "find_matches", {})
        self.assertIn("payload.candidate_id required", str(ctx.exception))
        self.assertIn("422", str(ctx.exception))

    @patch("agent_hub.mcp_server.urlopen")
    def test_network_error_maps_to_unavailable(self, urlopen_mock):
        urlopen_mock.side_effect = URLError("connection refused")
        with self.assertRaises(PlatformUnavailableError):
            self.client.list_agent_ids()

    @patch("agent_hub.mcp_server.urlopen")
    def test_list_agent_ids(self, urlopen_mock):
        urlopen_mock.return_value = _http_response([{"agent_id": "global-part-time"}])
        self.assertEqual(self.client.list_agent_ids(), ["global-part-time"])
        request = urlopen_mock.call_args.args[0]
        self.assertEqual(request.full_url, "http://api.test/platform/v1/agents")


if __name__ == "__main__":
    unittest.main()
