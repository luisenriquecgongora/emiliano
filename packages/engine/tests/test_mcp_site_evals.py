"""
Unit and Eval tests for Emiliano MCP site tools, intent routing, and site update workflows.
"""

import asyncio
import sys
from pathlib import Path
import unittest

# Ensure engine package root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from emiliano.core.config import EmilianoConfig, McpServerConfig
from emiliano.core.dispatcher import ExecutionDispatcher
from emiliano.core.routing import needs_mcp_or_tools, needs_workspace
from emiliano.evals.runner import EvalRunner, Target, load_suite


class TestMcpSiteRouting(unittest.TestCase):
    def test_mcp_intent_detection(self):
        # Positive site & business action queries
        positive = [
            "Query our business website title and navigation structure on PlaatoOS",
            "Query the business profile and venue details on PlaatoOS",
            "Check our website pages and hero block on PlaatoOS",
            "Update the hero block on the website to announce Summer 2026 events",
            "Apply cinematic teal and amber design tokens to our website theme",
            "Update Luis Enrique Builds site with new project subpages",
            "Update La Estacion del Verano site with the latest weekend cocktail schedule",
            "Propose a new FAQ page for our website on PlaatoOS",
            "What is our website title on PlaatoOS?",
            "Patch site block for the homepage banner",
            "Propose theme colors for our store",
            "Show me the menu items on our site",
        ]
        for goal in positive:
            with self.subTest(goal=goal):
                self.assertTrue(
                    needs_mcp_or_tools(goal),
                    f"Expected needs_mcp_or_tools to be True for: '{goal}'",
                )

    def test_mcp_negative_detection(self):
        # Pure conversation or plain questions without site/tool actions
        negative = [
            "Hello Emiliano, how are you today?",
            "Explain what a mutex is in computer science",
            "What is the capital of France?",
            "Good morning!",
        ]
        for goal in negative:
            with self.subTest(goal=goal):
                self.assertFalse(
                    needs_mcp_or_tools(goal),
                    f"Expected needs_mcp_or_tools to be False for: '{goal}'",
                )


class TestMcpSuiteEval(unittest.TestCase):
    def test_eval_suite_mcp_site_routing(self):
        suite = load_suite("mcp-site")
        self.assertEqual(suite["name"], "mcp-site")

        # Create runner with live dispatcher's routing logic
        runner = EvalRunner()
        report = asyncio.run(runner.run_suite(suite, Target.parse("ollama")))

        failed = [r for r in report.results if r.status != "passed"]
        failure_msg = "\n".join([f"- {r.id}: status={r.status}, detail={r.detail}" for r in failed])
        self.assertEqual(
            len(failed), 0,
            f"Eval suite mcp-site had {len(failed)} failures:\n{failure_msg}",
        )
        self.assertEqual(report.pass_rate, 1.0)


class TestDispatcherMcpTaskGating(unittest.TestCase):
    def test_is_task_activated_when_mcp_configured(self):
        cfg = EmilianoConfig(
            mcp_servers={"plaatoos": McpServerConfig(url="https://api-takient.onrender.com/mcp")}
        )
        dispatcher = ExecutionDispatcher(config=cfg)

        site_goal = "Update the hero block on our website"
        # Should NOT require local workspace (not local code)
        self.assertFalse(needs_workspace(site_goal))
        # BUT should require MCP tools
        self.assertTrue(needs_mcp_or_tools(site_goal))

        # Check dispatcher logic:
        has_mcp = bool(getattr(dispatcher.config, "mcp_servers", None))
        is_task = dispatcher.requires_agent_harness(site_goal) or (has_mcp and needs_mcp_or_tools(site_goal))
        self.assertTrue(is_task)

    def test_is_task_bypassed_for_casual_chat(self):
        cfg = EmilianoConfig(
            mcp_servers={"plaatoos": McpServerConfig(url="https://api-takient.onrender.com/mcp")}
        )
        dispatcher = ExecutionDispatcher(config=cfg)

        chat_goal = "Hello Emiliano!"
        has_mcp = bool(getattr(dispatcher.config, "mcp_servers", None))
        is_task = dispatcher.requires_agent_harness(chat_goal) or (has_mcp and needs_mcp_or_tools(chat_goal))
        self.assertFalse(is_task)


if __name__ == "__main__":
    unittest.main()
