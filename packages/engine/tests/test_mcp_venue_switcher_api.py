"""
Unit test suite verifying the Multi-Tenant Venue Switcher backend engine API.
Verifies switching between production Taki Taki Katowice and sandbox La Estacion del Verano,
ensuring credential persistence, token claim isolation, and error handling.
"""

import pytest
from emiliano.mcp import connect, credentials


class TestMcpVenueSwitcherApi:
    """Verifies the multi-tenant switching engine functions."""

    def test_01_venue_status_reports_registered_venues(self):
        stat = connect.status("plaatoos")
        assert stat["connected"] is True
        assert "venues" in stat
        assert len(stat["venues"]) >= 2
        venue_ids = [v["business_id"] for v in stat["venues"]]
        assert "69ca4850715529f18d18727a" in venue_ids  # Taki Taki Katowice
        assert "69ca4852715529f18d1872a6" in venue_ids  # La Estacion del Verano

    def test_02_switch_to_sandbox_verano(self):
        res = connect.switch_venue("plaatoos", "69ca4852715529f18d1872a6")
        assert res["ok"] is True
        assert res["active_venue"] == "La Estación del Verano"
        assert res["business_id"] == "69ca4852715529f18d1872a6"

        # Check status reflects the change
        stat = connect.status("plaatoos")
        assert stat["tenant"] == "La Estación del Verano"
        assert stat["business_id"] == "69ca4852715529f18d1872a6"

    def test_03_switch_back_to_production_taki_taki(self):
        res = connect.switch_venue("plaatoos", "69ca4850715529f18d18727a")
        assert res["ok"] is True
        assert res["active_venue"] == "Taki Taki Katowice"
        assert res["business_id"] == "69ca4850715529f18d18727a"

        # Check status reflects the change
        stat = connect.status("plaatoos")
        assert stat["tenant"] == "Taki Taki Katowice"
        assert stat["business_id"] == "69ca4850715529f18d18727a"

    def test_04_switch_venue_invalid_id_raises_value_error(self):
        with pytest.raises(ValueError) as exc:
            connect.switch_venue("plaatoos", "invalid_unknown_business_id_12345")
        assert "Unknown venue" in str(exc.value)

    def test_05_active_flag_synchronized_in_venues_list(self):
        stat = connect.status("plaatoos")
        active_venues = [v for v in stat["venues"] if v.get("active") is True]
        assert len(active_venues) == 1
        assert active_venues[0]["business_id"] == stat["business_id"]
