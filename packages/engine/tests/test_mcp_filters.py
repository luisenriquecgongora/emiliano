"""Choosing which MCP tools models see: name patterns, destructive tools, and the compact list for big catalogs."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from emiliano.core.config import McpServerConfig
from emiliano.mcp import McpManager
from emiliano.mcp.manager import is_destructive, keep_tool

FAKE = str(Path(__file__).with_name("fake_mcp_server.py"))


def server(**kw) -> McpServerConfig:
    return McpServerConfig(command=sys.executable, args=["-u", FAKE], timeout=10, **kw)


class TestKeepTool(unittest.TestCase):
    def test_patterns(self):
        cfg = McpServerConfig(command="x", tools=["query_*", "search_*"], exclude_tools=["query_finances"])
        self.assertTrue(keep_tool({"name": "query_events"}, cfg))
        self.assertTrue(keep_tool({"name": "search_products"}, cfg))
        self.assertFalse(keep_tool({"name": "query_finances"}, cfg))
        self.assertFalse(keep_tool({"name": "propose_event"}, cfg))

    def test_destructive_hidden_unless_allowed(self):
        tool = {"name": "propose_cash_entry", "destructiveHint": True}  # PlaatoOS puts the hint on the tool
        standard = {"name": "drop", "annotations": {"destructiveHint": True}}  # where the MCP spec puts it
        self.assertTrue(is_destructive(tool) and is_destructive(standard))
        self.assertFalse(keep_tool(tool, McpServerConfig(command="x")))
        self.assertTrue(keep_tool(tool, McpServerConfig(command="x", allow_destructive=True)))
        self.assertTrue(keep_tool({"name": "query_events", "readOnlyHint": True}, McpServerConfig(command="x")))


class TestManagerFilters(unittest.TestCase):
    def test_filtered_tools_are_not_offered_or_callable(self):
        manager = McpManager({"fake": server(tools=["echo", "search*"])})
        self.addCleanup(manager.close)
        manager.start()
        self.assertEqual(sorted(manager.tools), ["fake__echo", "fake__search_issues"])
        self.assertEqual(manager.statuses["fake"].hidden, 2)
        self.assertIn("Unknown tool", manager.call("fake__fail"))

    def test_small_catalog_lists_parameters(self):
        manager = McpManager({"fake": server()})
        self.addCleanup(manager.close)
        manager.start()
        self.assertFalse(manager.compact)
        self.assertFalse(manager.has("mcp_describe"))
        self.assertIn("fake__echo(text: string)", manager.prompt_section())

    def test_big_catalog_is_compact_with_lookup(self):
        manager = McpManager({"fake": server()})
        self.addCleanup(manager.close)
        manager.start()
        with patch("emiliano.mcp.manager.COMPACT_ABOVE", 2):
            self.assertTrue(manager.compact)
            section = manager.prompt_section()
            self.assertIn("- fake__echo: Echo the text back.", section)
            self.assertNotIn("text: string", section)  # no parameters until looked up
            self.assertIn('"name": "mcp_describe"', section)
            self.assertTrue(manager.has("mcp_describe"))
            described = manager.call("mcp_describe", {"name": "fake__echo"})
            self.assertIn('"required": [', described)
            self.assertIn("Similar: fake__echo", manager.call("mcp_describe", {"name": "echo"}))
            # The real tools still run as usual
            self.assertEqual(manager.call("fake__echo", {"text": "hi"}), "hi")


if __name__ == "__main__":
    unittest.main()
