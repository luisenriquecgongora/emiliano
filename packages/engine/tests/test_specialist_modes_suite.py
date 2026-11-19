"""
Test Suite: Domain Specialist Modes in Emiliano Engine & Desktop
Verifies /api/modes endpoint, mode resolution, prompt injection, and preferred skills scoping.
"""
import pytest
from fastapi.testclient import TestClient

from emiliano.server.app import app
from emiliano.history.api import MODES, SPECIALIST_MODE_CONFIGS, resolve_mode


@pytest.fixture(scope="module")
def test_client():
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        yield client


class TestSpecialistModesSuite:
    """Validates domain specialist mode discovery, resolution, and system instructions."""

    def test_01_api_modes_endpoint_structure(self, test_client):
        """Verifies GET /api/modes returns registered specialist modes with metadata."""
        resp = test_client.get("/api/modes")
        assert resp.status_code == 200
        data = resp.json()
        assert "modes" in data
        modes = {m["id"]: m for m in data["modes"]}

        # Must include all primary domain modes
        expected_modes = ["coding", "financial", "design", "outreach", "antigravity"]
        for mode_id in expected_modes:
            assert mode_id in modes, f"Missing specialist mode: {mode_id}"
            m = modes[mode_id]
            assert "title" in m and len(m["title"]) > 0
            assert "badge" in m and len(m["badge"]) > 0
            assert "description" in m and len(m["description"]) > 0
            assert "preferred_skills" in m and isinstance(m["preferred_skills"], list)

    def test_02_mode_resolution_mappings(self):
        """Verifies resolve_mode handles all built-in and specialist modes."""
        for mode_id in ("auto", "coding", "financial", "design", "outreach", "antigravity", "direct"):
            policy, harness = resolve_mode(mode_id)
            if mode_id == "antigravity":
                assert harness == "agy"
            elif mode_id == "direct":
                assert policy == "local"
            else:
                assert harness is None

        # Unknown mode safely falls back to auto
        fallback_policy, fallback_harness = resolve_mode("unknown_quantum_mode")
        assert (fallback_policy, fallback_harness) == (None, None)

    def test_03_financial_mode_metadata_and_skills(self):
        """Verifies Financial mode metadata focuses on PlaatoOS financial analytics."""
        cfg = SPECIALIST_MODE_CONFIGS["financial"]
        assert "Financial" in cfg["title"]
        assert "Finances" in cfg["badge"]
        assert "plaatoos__query_finances" in cfg["system_prompt"]
        assert "plaatoos__query_business" in cfg["system_prompt"]
        assert any("finances" in s for s in cfg["preferred_skills"])

    def test_04_coding_mode_metadata_and_skills(self):
        """Verifies Coding mode metadata prioritizes filesystem, git, and architecture."""
        cfg = SPECIALIST_MODE_CONFIGS["coding"]
        assert "Coding" in cfg["title"]
        assert "Files" in cfg["badge"]
        assert any("filesystem" in s for s in cfg["preferred_skills"])
        assert any("git" in s for s in cfg["preferred_skills"])

    def test_05_design_mode_metadata_and_skills(self):
        """Verifies Design mode metadata focuses on Tailwind, UI/UX, and component styling."""
        cfg = SPECIALIST_MODE_CONFIGS["design"]
        assert "Design" in cfg["title"]
        assert "Canvas" in cfg["badge"]
        assert any("tailwind" in s for s in cfg["preferred_skills"])

    def test_06_outreach_mode_metadata_and_skills(self):
        """Verifies Outreach mode metadata focuses on PlaatoOS lead generation and CRM."""
        cfg = SPECIALIST_MODE_CONFIGS["outreach"]
        assert "Outreach" in cfg["title"]
        assert "Growth" in cfg["badge"]
        assert any("outreach" in s for s in cfg["preferred_skills"])

    def test_07_specialist_prompt_injection_logic(self):
        """Simulates conversation message preparation and confirms specialist prompt is prepended."""
        conv_msgs = [{"role": "user", "content": "What is our net revenue this week?"}]

        mode_key = "financial"
        spec_cfg = SPECIALIST_MODE_CONFIGS[mode_key]
        spec_prompt = spec_cfg["system_prompt"]

        # Ensure no system prompt yet
        assert not any(m.get("role") == "system" for m in conv_msgs)

        # Inject prompt as api.py does
        spec_guideline = f"Active Domain Mode: [{spec_cfg['title']}]\n{spec_prompt}"
        enriched_msgs = [{"role": "system", "content": spec_guideline}] + conv_msgs

        assert len(enriched_msgs) == 2
        assert enriched_msgs[0]["role"] == "system"
        assert "Financial & Business Operations" in enriched_msgs[0]["content"]
        assert "plaatoos__query_finances" in enriched_msgs[0]["content"]
        assert enriched_msgs[1]["role"] == "user"

    def test_08_fnb_menu_mode_metadata_and_recipe_costing(self):
        """Verifies F&B Menu Engineer mode focuses on cocktail margins, recipe costing, and QR menus."""
        cfg = SPECIALIST_MODE_CONFIGS["fnb_menu"]
        assert cfg["category"] == "hospitality"
        assert "Food & Beverage Menu" in cfg["title"]
        assert "recipe costing" in cfg["system_prompt"].lower()
        assert "pour cost" in cfg["system_prompt"].lower()
        assert "cocktail_engineering" in cfg["preferred_skills"]

    def test_09_concierge_and_reservations_mode(self):
        """Verifies Concierge mode focuses on karaoke room bookings and VIP guest arrival flows."""
        cfg = SPECIALIST_MODE_CONFIGS["concierge"]
        assert cfg["category"] == "hospitality"
        assert "Reservations" in cfg["title"]
        assert "karaoke rooms" in cfg["system_prompt"].lower()
        assert "room_bookings" in cfg["preferred_skills"]

    def test_10_inventory_and_purchasing_mode(self):
        """Verifies Inventory mode focuses on par levels, beverage audits, and supplier price comparison."""
        cfg = SPECIALIST_MODE_CONFIGS["inventory"]
        assert cfg["category"] == "finance"
        assert "Inventory" in cfg["title"]
        assert "par level" in cfg["system_prompt"].lower()
        assert "par_levels" in cfg["preferred_skills"]

    def test_11_shifts_roster_and_labor_cost_mode(self):
        """Verifies Shifts mode focuses on employee scheduling, tip distribution, and labor cost %."""
        cfg = SPECIALIST_MODE_CONFIGS["shifts"]
        assert cfg["category"] == "operations"
        assert "Staff Roster" in cfg["title"]
        assert "tip distribution" in cfg["system_prompt"].lower()
        assert "labor_cost_percent" in cfg["preferred_skills"]

    def test_12_reviews_and_reputation_mode(self):
        """Verifies Reviews mode focuses on Google Maps, sentiment analysis, and response drafting."""
        cfg = SPECIALIST_MODE_CONFIGS["reviews"]
        assert cfg["category"] == "growth"
        assert "Reviews" in cfg["title"]
        assert "google maps" in cfg["system_prompt"].lower()
        assert "response_drafting" in cfg["preferred_skills"]

    def test_13_retention_and_vip_loyalty_mode(self):
        """Verifies VIP Retention mode focuses on regulars, birthday perks, and WhatsApp/SMS re-engagement."""
        cfg = SPECIALIST_MODE_CONFIGS["retention"]
        assert cfg["category"] == "growth"
        assert "VIP Loyalty" in cfg["title"]
        assert "birthday" in cfg["system_prompt"].lower()
        assert "vip_clubs" in cfg["preferred_skills"]

    def test_14_compliance_and_licensing_mode(self):
        """Verifies Compliance mode focuses on alcohol permits, HACCP hygiene, and safety audits."""
        cfg = SPECIALIST_MODE_CONFIGS["compliance"]
        assert cfg["category"] == "operations"
        assert "Compliance" in cfg["title"]
        assert "alcohol licensing" in cfg["system_prompt"].lower()
        assert "haccp_checklists" in cfg["preferred_skills"]

    def test_15_all_14_small_business_modes_in_api_modes_endpoint(self, test_client):
        """Verifies that GET /api/modes returns all 14 modes with correct categories."""
        resp = test_client.get("/api/modes")
        assert resp.status_code == 200
        data = resp.json()
        modes = {m["id"]: m for m in data["modes"]}

        all_14_ids = [
            "auto", "financial", "fnb_menu", "concierge", "inventory",
            "shifts", "marketing", "outreach", "reviews", "retention",
            "compliance", "coding", "design", "antigravity"
        ]
        assert len(modes) == 14
        for mid in all_14_ids:
            assert mid in modes
            assert "category" in modes[mid]
            assert "badge" in modes[mid]
            assert "title" in modes[mid]
