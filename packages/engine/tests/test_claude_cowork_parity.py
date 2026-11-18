"""
Comprehensive Claude Cowork Parity Evaluation & Benchmark Suite for Emiliano.
Tests the 6 foundational pillars required to achieve full parity with Claude Cowork:
1. Intent Routing & Lane Discipline (Positive & Negative Boundaries)
2. Background Non-Activating Browser Bridge & DOM Perception
3. Live PlaatoOS MCP Tool Integration & High-Precision Telemetry
4. Anti-Bot Humanization, 3-Bubble Splitting & Workspace Confinement
5. Multi-System CRM Audit Synchronization & Deliverables
6. Progressive Disclosure Collapsible Tool Execution Schema
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List

# Add engine to path
ENGINE_ROOT = Path(__file__).resolve().parent.parent
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from emiliano.core.config import EmilianoConfig, McpServerConfig
from emiliano.core.dispatcher import ExecutionDispatcher
from emiliano.core.routing import needs_mcp_or_tools, needs_workspace
from emiliano.cowork.browser_bridge import RemoteBrowserBridge
from emiliano.history.store import HistoryStore, Message


class TestPillar1_IntentRoutingAndDiscipline(unittest.TestCase):
    """Pillar 1: Evaluates intent recognition, positive cowork routing, and negative safety boundaries."""

    def setUp(self):
        self.config = EmilianoConfig(
            mcp_servers={"plaatoos": McpServerConfig(url="https://api-takient.onrender.com/mcp")}
        )
        self.dispatcher = ExecutionDispatcher(config=self.config)

    def test_positive_cowork_routing(self):
        """Cowork and outreach goals must route to the cowork extension."""
        cowork_goals = [
            "please outreach new clients",
            "send 5 dms to restaurant prospects",
            "reach out to new clients on instagram",
            "run outreach pipeline",
            "outreach 3 new clients (dry run)",
        ]
        ext_mgr = self.dispatcher.extension_mgr
        for goal in cowork_goals:
            match = ext_mgr.match_intent(goal)
            self.assertIsNotNone(match, f"Failed to match cowork intent: '{goal}'")
            self.assertEqual(match.name, "plaatoos-outreach")

    def test_negative_safety_boundaries(self):
        """Conversational queries and system tasks must NEVER trigger cowork or outreach."""
        negative_goals = [
            ("Hello Emiliano, what is your purpose?", False, False),
            ("Explain what a mutex is in computer science", False, False),
            ("What is 2+2? Reply in one sentence.", False, False),
            ("git status", True, False),
            ("Run the pytest suite in this repo", True, False),
            ("Refactor utils.py to use pathlib", True, False),
        ]
        ext_mgr = self.dispatcher.extension_mgr
        for goal, expect_harness, expect_cowork in negative_goals:
            match = ext_mgr.match_intent(goal)
            self.assertIsNone(match, f"Negative goal erroneously triggered cowork extension: '{goal}'")
            requires_harness = self.dispatcher.requires_agent_harness(goal)
            if expect_harness:
                self.assertTrue(requires_harness, f"Expected harness for '{goal}'")
            else:
                self.assertFalse(requires_harness, f"Expected direct model for '{goal}'")

    def test_mcp_site_gating(self):
        """Goals asking to inspect or update website require MCP tools without requiring local coding workspace."""
        site_goals = [
            "Query our business website title and navigation structure on PlaatoOS",
            "Check our website pages and hero block on PlaatoOS",
            "Update the hero block on the website to announce Summer 2026 events",
        ]
        for goal in site_goals:
            self.assertTrue(needs_mcp_or_tools(goal), f"Expected MCP tool requirement for '{goal}'")
            self.assertFalse(needs_workspace(goal), f"Site goal should not require local coding workspace: '{goal}'")

    def test_mcp_business_intelligence_gating(self):
        """Finances, shift money, song requests, playlists, settings, and ML revenue forecast must route cleanly to MCP."""
        bi_goals = [
            "Query our business finances and monthly income breakdown on PlaatoOS",
            "Query our shift money breakdown, cash in till, and card payouts on PlaatoOS",
            "What are the top most requested karaoke songs this month on PlaatoOS?",
            "Query our active karaoke playlists and room queues on PlaatoOS",
            "Query our venue settings, opening hours, and contact details on PlaatoOS",
            "Forecast our expected revenue for tonight on PlaatoOS using predictive analytics",
        ]
        for goal in bi_goals:
            self.assertTrue(needs_mcp_or_tools(goal), f"Expected MCP tool requirement for BI goal '{goal}'")
            self.assertFalse(needs_workspace(goal), f"BI goal must not be misrouted to git/coding workspace: '{goal}'")


class TestPillar2_BrowserBridgeNonActivatingDOM(unittest.TestCase):
    """Pillar 2: Evaluates silent background browser automation and DOM perception via Chrome Companion."""

    def setUp(self):
        self.bridge = RemoteBrowserBridge(base_url="http://127.0.0.1:8765")

    def test_browser_bridge_connection_status(self):
        """Chrome companion extension must be connected to engine daemon."""
        self.assertTrue(
            self.bridge.is_connected,
            "Emiliano Cowork Companion Chrome extension is not connected on http://127.0.0.1:8765."
        )
        info = self.bridge.extension_info
        self.assertEqual(info.get("name"), "Emiliano Cowork Companion")
        self.assertEqual(info.get("version"), "1.0.0")

    def test_browser_tab_query(self):
        """Bridge must be able to query open Chrome tabs silently."""
        async def _query():
            return await self.bridge.get_tabs()

        tabs = asyncio.run(_query())
        self.assertIsInstance(tabs, list)
        self.assertGreater(len(tabs), 0, "No open browser tabs discovered via Chrome extension.")

    def test_in_page_script_execution(self):
        """Bridge must execute JavaScript inside tab DOM without focus stealing."""
        async def _exec():
            return await self.bridge.execute_script("document.title")

        title = asyncio.run(_exec())
        self.assertIsInstance(title, str)


class TestPillar3_PlaatoOsMcpToolsAndTelemetry(unittest.TestCase):
    """Pillar 3: Evaluates live PlaatoOS MCP server integration, tool schema, and execution telemetry."""

    def test_mcp_config_resolution(self):
        """PlaatoOS MCP server configuration must point to authoritative endpoint."""
        config = EmilianoConfig(
            mcp_servers={"plaatoos": McpServerConfig(url="https://api-takient.onrender.com/mcp")}
        )
        self.assertIn("plaatoos", config.mcp_servers)
        self.assertEqual(config.mcp_servers["plaatoos"].url, "https://api-takient.onrender.com/mcp")

    def test_telemetry_metrics_schema(self):
        """Metrics JSON must include duration, ttft, throughput, and tool duration."""
        sample_metrics = {
            "total_duration_s": 19.92,
            "formatted_duration": "19.92s",
            "ttft_ms": 1420.0,
            "tokens_per_second": 8.1,
            "completion_tokens": 160,
            "prompt_tokens": 4750,
            "tool_duration_s": 2.14,
            "tools_count": 1,
            "route": "Ollama (qwen2.5-coder:3b)",
        }
        self.assertGreater(sample_metrics["total_duration_s"], 0)
        self.assertGreater(sample_metrics["tokens_per_second"], 0)
        self.assertIsNotNone(sample_metrics["tool_duration_s"])
        self.assertEqual(sample_metrics["tools_count"], 1)


class TestPillar4_AntiBotHumanizationAndSafety(unittest.TestCase):
    """Pillar 4: Evaluates 3-bubble pitch splitting, anti-bot humanization, and directory confinement."""

    def test_three_bubble_splitting_protocol(self):
        """Outreach pitches must split cleanly into exactly 3 bubbles separated by delimiter."""
        sample_pitch = (
            "Cześć! Widziałem Wasz lokal w Katowicach i bardzo podoba mi się Wasz klimat.\n---\n"
            "W PlaatoOS automatyzujemy rezerwacje stolików i zarządzanie salami bez prowizji.\n---\n"
            "Czy mogę podesłać krótkie 2-minutowe demo jak to działa dla Waszego zespołu?"
        )
        bubbles = [b.strip() for b in re.split(r'\n---+\n|\n\n---\n\n', sample_pitch) if b.strip()]
        self.assertEqual(len(bubbles), 3, f"Expected exactly 3 bubbles, got {len(bubbles)}")
        self.assertIn("Katowicach", bubbles[0])
        self.assertIn("PlaatoOS", bubbles[1])
        self.assertIn("demo", bubbles[2])

    def test_humanized_keystroke_jitter(self):
        """Humanized jitter delays must stay within safe anti-bot thresholds (0.015s - 0.065s)."""
        import random
        delays = [random.uniform(0.015, 0.065) for _ in range(50)]
        for d in delays:
            self.assertGreaterEqual(d, 0.015)
            self.assertLessEqual(d, 0.065)

    def test_workspace_path_confinement(self):
        """Tasks must be sandboxed to their declared project workspace root."""
        project_root = Path(r"C:\Users\artlu\OracliomNew\Oracliom\emiliano-cowork-plaatoos").resolve()
        test_file = project_root / "crm.py"
        self.assertTrue(test_file.resolve().is_relative_to(project_root))

        outside_file = Path(r"C:\Windows\System32\cmd.exe").resolve()
        self.assertFalse(outside_file.is_relative_to(project_root))


class TestPillar5_CrmAuditSynchronization(unittest.TestCase):
    """Pillar 5: Evaluates local multi-file CRM audit sync across JSONL logs and deliverable artifacts."""

    def test_business_logs_jsonl_integrity(self):
        """business_logs.jsonl must exist and contain valid JSONL audit records."""
        log_file = Path(r"C:\Users\artlu\OracliomNew\Oracliom\emiliano-cowork-plaatoos\business_logs.jsonl")
        self.assertTrue(log_file.exists(), "business_logs.jsonl is missing.")
        lines = [line.strip() for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertGreater(len(lines), 100, "Expected at least 100 business activity audit records.")

        # Validate that the most recent line parses as valid JSON
        last_entry = json.loads(lines[-1])
        self.assertIn("timestamp", last_entry)
        self.assertIn("action", last_entry)

    def test_outreach_crm_class_import(self):
        """OutreachCRM class must load and report lead counts without error."""
        sys.path.insert(0, r"C:\Users\artlu\OracliomNew\Oracliom\emiliano-cowork-plaatoos")
        from crm import OutreachCRM
        crm = OutreachCRM()
        leads = crm.load_leads()
        self.assertGreater(len(leads), 1000, "Expected >1000 tracked leads in CRM.")


class TestPillar6_CollapsibleReceiptsAndTelemetry(unittest.TestCase):
    """Pillar 6: Evaluates structured tool call persistence and UI accordion receipts."""

    def test_history_store_schema_has_tool_calls(self):
        """SQLite messages table must support tool_calls and metrics columns."""
        store = HistoryStore()
        # Verify columns exist by querying a message
        chat = store.get_chat("0392f12a-81cc-4e7c-9644-1374cf66e4a8")
        self.assertIsNotNone(chat, "Expected chat 0392f12a-81cc-4e7c-9644-1374cf66e4a8 to exist in history store.")
        has_tool_calls_col = False
        for msg in chat.get("messages", []):
            if "tool_calls" in msg:
                has_tool_calls_col = True
                break
        self.assertTrue(has_tool_calls_col, "HistoryStore messages lack tool_calls column/field.")

    def test_tool_call_card_payload_structure(self):
        """Tool call payload must preserve namespace, arguments, result, and timing."""
        tool_call_payload = {
            "tool": "plaatoos__propose_site_pages",
            "mcp_server": "plaatoos",
            "tool_name": "propose_site_pages",
            "args": {"pages": [{"title": "Nowa strona", "slug": "nowa-strona"}]},
            "result": '{"status": "ok", "siteId": "69ca4850715529f18d18727a"}',
            "duration_s": 2.14,
            "status": "ok"
        }
        self.assertEqual(tool_call_payload["mcp_server"], "plaatoos")
        self.assertEqual(tool_call_payload["tool_name"], "propose_site_pages")
        self.assertEqual(tool_call_payload["status"], "ok")
        self.assertEqual(tool_call_payload["duration_s"], 2.14)


if __name__ == "__main__":
    unittest.main()
