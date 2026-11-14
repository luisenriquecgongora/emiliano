"""MCP host: the stdio client, the manager that names and routes tools, and the agent and config wiring."""

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from emiliano.core.config import EmilianoConfig, McpServerConfig
from emiliano.core.registry import CapabilityRegistry
from emiliano.direct.agent import DirectAgentLoop, parse_tool_calls
from emiliano.mcp import McpError, McpManager, McpStdioClient, acp_server_list, qualify
from emiliano.mcp.client import MAX_RESULT_CHARS, format_tool_result

FAKE = str(Path(__file__).with_name("fake_mcp_server.py"))


def fake_server(**env) -> McpServerConfig:
    return McpServerConfig(command=sys.executable, args=["-u", FAKE], env=env, timeout=10)


class TestClient(unittest.TestCase):
    def setUp(self):
        self.client = McpStdioClient("fake", sys.executable, ["-u", FAKE])
        self.client.start(timeout=20)
        self.addCleanup(self.client.close)

    def test_handshake_and_paginated_tools(self):
        self.assertEqual(self.client.server_info["name"], "fake")
        names = [t["name"] for t in self.client.list_tools()]
        self.assertEqual(names, ["echo", "fail", "roots", "search-issues"])

    def test_call_and_error(self):
        self.assertEqual(self.client.call_tool("echo", {"text": "hola"}), "hola")
        self.assertEqual(self.client.call_tool("fail"), "Error: something broke")
        with self.assertRaises(McpError):
            self.client.call_tool("nope")

    def test_answers_server_requests(self):
        # The server asks the client for roots/list in the middle of a tool call
        self.assertEqual(self.client.call_tool("roots"), "workspace")


class TestManager(unittest.TestCase):
    def test_tools_are_qualified_and_routed(self):
        manager = McpManager({"Fake Srv": fake_server()})
        self.addCleanup(manager.close)
        manager.start()
        self.assertTrue(manager.statuses["Fake Srv"].ok)
        self.assertIn("fake_srv__search_issues", manager.tools)
        self.assertEqual(manager.call("fake_srv__search_issues", {"query": "crash"}), "found 2 issues for crash")
        self.assertIn("Unknown tool", manager.call("fake_srv__missing"))
        description = manager.describe_tools()
        self.assertIn("- fake_srv__echo(text: string): Echo the text back.", description)
        self.assertIn("fake_srv__search_issues(query: string, limit?: integer)", description)
        self.assertIn('<tool_call>{"name": "fake_srv__echo"', manager.prompt_section())

    def test_broken_server_is_reported_and_others_still_work(self):
        manager = McpManager({"bad": fake_server(FAKE_MCP_CRASH="1"), "good": fake_server(),
                              "off": McpServerConfig(command="nothing", enabled=False)})
        self.addCleanup(manager.close)
        manager.start()
        self.assertFalse(manager.statuses["bad"].ok)
        self.assertIn("crashing on purpose", manager.statuses["bad"].error)
        self.assertTrue(manager.statuses["good"].ok)
        self.assertNotIn("off", manager.statuses)

    def test_dead_server_restarts_on_next_call(self):
        manager = McpManager({"fake": fake_server()})
        self.addCleanup(manager.close)
        manager.start()
        manager.clients["fake"].proc.kill()
        manager.clients["fake"].proc.wait(timeout=5)
        self.assertEqual(manager.call("fake__echo", {"text": "back"}), "back")

    def test_async_api(self):
        manager = McpManager({"fake": fake_server()})
        self.addCleanup(manager.close)

        async def go():
            await manager.astart()
            return await manager.acall("fake__echo", {"text": "async"})

        self.assertEqual(asyncio.run(go()), "async")


class TestHelpers(unittest.TestCase):
    def test_qualify(self):
        self.assertEqual(qualify("GitHub", "search-issues"), "github__search_issues")

    def test_result_formatting(self):
        self.assertEqual(format_tool_result({"content": [{"type": "text", "text": "a"}, {"type": "image"}]}),
                         "a\n[image content omitted]")
        self.assertEqual(format_tool_result({"structuredContent": {"n": 1}}), '{"n": 1}')
        self.assertIn("more characters", format_tool_result({"content": [{"type": "text", "text": "x" * (MAX_RESULT_CHARS + 5)}]}))

    def test_config_and_acp_format(self):
        config = EmilianoConfig(mcp_servers={"gh": {"command": "npx", "args": ["-y", "srv"], "env": {"T": "1"}},
                                             "off": {"command": "x", "enabled": False}})
        self.assertEqual(acp_server_list(config.mcp_servers),
                         [{"name": "gh", "command": "npx", "args": ["-y", "srv"], "env": [{"name": "T", "value": "1"}]}])
        harness = CapabilityRegistry(config=config).get_harness_instances()["claude_code"]
        self.assertEqual(harness.mcp_servers[0]["name"], "gh")


class TestAgentUsesMcpTools(unittest.TestCase):
    def test_model_calls_mcp_tool(self):
        manager = McpManager({"fake": fake_server()})
        self.addCleanup(manager.close)
        manager.start()

        replies = iter(['<tool_call>{"name": "fake__echo", "arguments": {"text": "from mcp"}}</tool_call>', "Done."])
        prompts = []

        async def stream_completion(messages, **kwargs):
            prompts.append([dict(m) for m in messages])
            yield next(replies)

        client = MagicMock()
        client.stream_completion = stream_completion
        client.last_usage = None
        agent = DirectAgentLoop(client=client, model_id="ollama/x", auto_verify=False, mcp=manager)
        with tempfile.TemporaryDirectory() as ws:
            asyncio.run(agent.run("echo something", workspace=ws))

        self.assertIn("fake__echo(text: string)", prompts[0][0]["content"])
        self.assertIn('<tool_response name="fake__echo">\nfrom mcp\n</tool_response>', prompts[1][-1]["content"])

    def test_json_call_parses_any_tool_name(self):
        calls = parse_tool_calls('<tool_call>{"name": "gh__search", "arguments": {"q": "x"}}</tool_call>')
        self.assertEqual(calls, [{"tool": "gh__search", "args": {"q": "x"}}])


if __name__ == "__main__":
    unittest.main()
