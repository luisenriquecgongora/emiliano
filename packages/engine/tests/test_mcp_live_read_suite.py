"""
Live MCP Read Tool Evaluation Test Suite for PlaatoOS & Emiliano.
Tests read queries across all major business telemetry domains against the active PlaatoOS MCP server.
Includes rate-limit compliant pacing to stay well within the 60 req/min tenant budget.
"""

import os
import sys
import json
import time
import unittest
from pathlib import Path

# Add engine package to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from emiliano.core.config import load_config
from emiliano.mcp import McpManager


class TestMcpLiveReadSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = load_config()
        cls.mgr = McpManager(cfg.mcp_servers, cwd=os.getcwd())
        cls.mgr.start()
        # Verify server loaded
        if "plaatoos" not in cls.mgr.statuses or not cls.mgr.statuses["plaatoos"].ok:
            raise unittest.SkipTest("PlaatoOS live MCP server not configured or offline")

    @classmethod
    def tearDownClass(cls):
        cls.mgr.close()

    def setUp(self):
        # Throttle between tests to honor the 60 requests/min rate limiter
        time.sleep(0.35)

    def _call(self, tool_name: str, args: dict = None) -> dict:
        qname = f"plaatoos__{tool_name}"
        res = self.mgr.call(qname, args or {})
        self.assertIsInstance(res, str, f"{tool_name} returned non-string result")
        self.assertFalse(res.startswith("Error: Unknown tool"), f"Tool '{tool_name}' is not registered on MCP server")
        # Ensure not rate-limited
        self.assertNotIn("rate limit exceeded", res.lower(), f"Tenant rate limit triggered on {tool_name}")
        try:
            return json.loads(res)
        except json.JSONDecodeError:
            self.fail(f"{tool_name} returned non-JSON string: {res[:200]}")

    def test_01_query_business_profile(self):
        """Query core business profile and venue addresses."""
        data = self._call("query_business", {"includeVenues": True, "includeStats": True})
        self.assertIn("business", data)
        biz = data["business"]
        self.assertEqual(biz.get("name"), "Taki Taki Katowice")
        self.assertEqual(biz.get("_id"), "69ca4850715529f18d18727a")
        self.assertIn("address", biz)
        self.assertTrue(biz.get("venues") or data.get("venues") or biz.get("address"))

    def test_02_query_business_settings(self):
        """Query venue operating hours, tax details, and configuration."""
        data = self._call("query_business_settings")
        self.assertIn("settings", data)
        settings = data["settings"]
        self.assertEqual(settings.get("_id"), "69ca4850715529f18d18727a")

    def test_03_query_business_site_and_blocks(self):
        """Query website pages, navigation, and block schema."""
        data = self._call("query_business_site")
        self.assertIn("settings", data)
        self.assertIn("pages", data)
        self.assertEqual(data["settings"].get("siteName"), "Taki Taki Katowice")

    def test_04_query_finances_and_revenue(self):
        """Query monthly financial summary, revenue columns, and closed shifts."""
        data = self._call("query_finances")
        self.assertIn("month", data)
        self.assertIn("total", data)
        self.assertIsInstance(data["total"], (int, float))

    def test_05_query_cash_boxes(self):
        """Query safe boxes and cash register ledgers."""
        data = self._call("query_cash_boxes")
        self.assertIn("boxes", data)
        self.assertIsInstance(data["boxes"], list)
        self.assertGreaterEqual(len(data["boxes"]), 1)
        self.assertEqual(data["boxes"][0].get("key"), "cash_taki")

    def test_06_query_shift_money_till(self):
        """Query daily shift till reconciliations and card/cash breakdowns."""
        data = self._call("query_shift_money")
        self.assertIn("from", data)
        self.assertIn("to", data)

    def test_07_query_menu_items(self):
        """Query catalog drinks, cocktails, beers, and group tags."""
        data = self._call("query_menu", {"limit": 50})
        self.assertIn("items", data)
        self.assertIsInstance(data["items"], list)
        self.assertGreater(len(data["items"]), 0)
        item_names = [i.get("name") for i in data["items"]]
        self.assertIn("Aperol Spritz", item_names)

    def test_08_find_duplicate_menu_items(self):
        """Audit menu catalog for exact and fuzzy duplicate items."""
        data = self._call("find_duplicate_menu_items")
        self.assertIn("exactDuplicates", data)
        self.assertIn("similarNames", data)

    def test_09_query_inventory_products(self):
        """Query warehouse inventory items and suppliers."""
        data = self._call("query_inventory")
        self.assertIn("products", data)
        self.assertIsInstance(data["products"], list)

    def test_10_query_events_and_parties(self):
        """Query scheduled nightlife parties, karaoke sessions, and concerts."""
        data = self._call("query_events")
        self.assertIn("events", data)
        self.assertIsInstance(data["events"], list)
        self.assertGreater(len(data["events"]), 0)

    def test_11_query_tickets(self):
        """Query event ticket tiers, pricing, and sold counts."""
        data = self._call("query_tickets")
        self.assertIn("tickets", data)
        self.assertIsInstance(data["tickets"], list)

    def test_12_query_playlists_and_karaoke(self):
        """Query room playlists and track queues."""
        data = self._call("query_playlists")
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)

    def test_13_query_calendar_schedule(self):
        """Query master multi-week business calendar."""
        data = self._call("query_calendar")
        self.assertIn("from", data)
        self.assertIn("to", data)
        self.assertIn("items", data)

    def test_14_query_staff_users(self):
        """Query staff roster, managers, and permission roles."""
        data = self._call("query_users", {"limit": 10})
        self.assertIn("users", data)
        self.assertIsInstance(data["users"], list)
        self.assertGreater(len(data["users"]), 0)
        emails = [u.get("email") for u in data["users"]]
        self.assertIn("luisenriquecgongora@gmail.com", emails)

    def test_15_predict_revenue_ml(self):
        """Forecast today's business revenue with predictive ML models."""
        data = self._call("predict_revenue")
        self.assertEqual(data.get("scope"), "today")
        self.assertEqual(data.get("businessName"), "Taki Taki Katowice")
        self.assertIn("forecast", data)


if __name__ == "__main__":
    unittest.main()
