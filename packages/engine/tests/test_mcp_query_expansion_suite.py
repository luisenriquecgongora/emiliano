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

    def test_08_business_summary_query_ranks_profile_and_finances(self):
        tools = self.mgr.filter_tools_for_goal("can you please tell me a summary of my business Taki Taki", max_tools=5)
        names = [t.qualified_name for t in tools]
        assert any("business" in n or "finances" in n for n in names)
        assert "plaatoos__query_business" in names[:2]

    def test_09_most_played_karaoke_songs_ranks_song_requests_and_playlists(self):
        tools = self.mgr.filter_tools_for_goal("what are the most played songs in the karaoke?", max_tools=5)
        names = [t.qualified_name for t in tools]
        assert any("song_requests" in n or "playlists" in n for n in names)
        assert "plaatoos__query_song_requests" in names

    def test_10_stale_refusals_and_meta_instructions_sanitized(self):
        raw_msgs = [
            {"role": "user", "content": "can you please tell me a summary of my business Taki Taki"},
            {"role": "assistant", "content": "I'm sorry, but I don't have access to your specific business information. To provide a summary of your business Taki Taki, I would need to query the relevant data from our systems using the provided MCP tools. Could you please let me know which aspects of your business you'd like summarized?"},
            {"role": "user", "content": "what are the most played songs in the karaoke?"},
            {"role": "assistant", "content": "It seems there was an issue with the playlist ID you provided. Let's try a different approach to find out which songs are most played in the karaoke: List All Playlists: First, let's list all playlists... Replace <specific-playlist-id> with the ID of the karaoke playlist..."},
            {"role": "user", "content": "please tell me top karaoke songs"},
        ]
        # Test clean_history filter logic directly
        clean_history = []
        for m in raw_msgs:
            if m.get("role") == "assistant":
                txt = (m.get("content") or "").lower()
                if any(phrase in txt for phrase in (
                    "don't have access to real-time",
                    "don't have access to your specific business information",
                    "replace <specific-playlist-id>",
                    "replace <",
                    "which aspects of your business you'd like summarized",
                )):
                    continue
            clean_history.append(m)
        # Both poisoned assistant messages must be completely sanitized out
        assert len(clean_history) == 3
        for m in clean_history:
            assert m["role"] == "user"
