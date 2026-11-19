"""
Unit test suite verifying the Expanded Keyword Domain Boosters and Parameter Sanitizers.
Ensures that queries across cash, drinks, inventory, staff, playlists, and website
consistently rank the correct tools and strip invalid array filters.
"""

import os
from emiliano.core.config import load_config
from emiliano.mcp.manager import McpManager


class TestMcpQueryExpansionSuite:
    """Verifies domain ranking and argument sanitization in McpManager."""

    @classmethod
    def setup_class(cls):
        cfg = load_config()
        cls.mgr = McpManager(cfg.mcp_servers, cwd=os.getcwd())
        cls.mgr.start()

    @classmethod
    def teardown_class(cls):
        cls.mgr.close()

    def test_01_cash_query_ranks_cash_boxes_first(self):
        tools = self.mgr.filter_tools_for_goal("what is the current cash in taki taki katowice", max_tools=5)
        names = [t.qualified_name for t in tools]
        assert "plaatoos__query_cash_boxes" in names[:2]

    def test_02_drinks_and_cocktails_ranks_query_menu(self):
        tools = self.mgr.filter_tools_for_goal("show me all cocktails, beers, and drinks on the menu", max_tools=5)
        names = [t.qualified_name for t in tools]
        assert "plaatoos__query_menu" in names[:2]

    def test_03_inventory_and_stock_ranks_inventory_products(self):
        tools = self.mgr.filter_tools_for_goal("check our inventory stock levels in the warehouse", max_tools=5)
        names = [t.qualified_name for t in tools]
        assert any("inventory" in n or "product" in n for n in names)

    def test_04_staff_and_employees_ranks_users(self):
        tools = self.mgr.filter_tools_for_goal("who are the registered staff users and employees", max_tools=5)
        names = [t.qualified_name for t in tools]
        assert any("user" in n or "staff" in n for n in names)

    def test_05_playlist_and_music_ranks_playlists(self):
        tools = self.mgr.filter_tools_for_goal("what karaoke songs and music playlists are loaded", max_tools=5)
        names = [t.qualified_name for t in tools]
        assert any("playlist" in n or "karaoke" in n for n in names)

    def test_06_sanitize_tool_args_strips_invalid_group_tag_array(self):
        args = {"groupTag": ["Drinks", "Beers", "Cocktails"], "limit": 50, "hasRecipe": False}
        sanitized = self.mgr._sanitize_tool_args("plaatoos__query_menu", args)
        # Array with > 1 element should be popped to allow broad search
        assert "groupTag" not in sanitized
        # hasRecipe: False should be stripped
        assert "hasRecipe" not in sanitized
        assert sanitized["limit"] == 50

    def test_07_sanitize_tool_args_preserves_single_string_group_tag(self):
        args = {"groupTag": ["Drinks"], "limit": 25}
        sanitized = self.mgr._sanitize_tool_args("plaatoos__query_menu", args)
        # Single element array converted to string
        assert sanitized["groupTag"] == "Drinks"
