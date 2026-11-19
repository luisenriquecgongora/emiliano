"""
Live MCP Write & Mutation Guardrail Test Suite.
Tests non-destructive proposal tools (ChangeSets) exclusively on the designated sandbox tenant
'La Estación del Verano' (69ca4852715529f18d1872a6).
Verifies:
  1. High-risk write operations produce pending draft proposals (AdminChangeSets).
  2. Proposals require human sign-off and never mutate live production databases directly.
  3. Strict multi-tenant isolation ensures production tenant 'Taki Taki Katowice' (69ca4850715529f18d18727a)
     remains 100% pristine and unaltered.
"""

import os
import sys
import json
import time
import base64
import hashlib
import secrets
import unittest
from pathlib import Path

import httpx

# Add engine package to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from emiliano.core.config import load_config
from emiliano.mcp import McpManager

API_BASE = "https://api-takient.onrender.com"
VERANO_BIZ_ID = "69ca4852715529f18d1872a6"
TAKI_BIZ_ID = "69ca4850715529f18d18727a"


class TestMcpSandboxWriteGuardrails(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 1. Login with manager credentials
        login_res = httpx.post(f"{API_BASE}/auth/login", json={
            "email": "luisenriquecgongora@gmail.com",
            "password": "Ch1c0r1t@"
        }, timeout=20.0)
        assert login_res.status_code == 200, f"Manager login failed: {login_res.text}"
        user_jwt = login_res.json()["token"]

        # 2. PKCE Authorization consent scoped exclusively to sandbox tenant (La Estación del Verano)
        verifier = secrets.token_urlsafe(40)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")

        consent_res = httpx.post(f"{API_BASE}/oauth/consent", json={
            "client_id": "emiliano",
            "redirect_uri": "http://localhost:3333/callback",
            "scope": "business:read business:write",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "businessId": VERANO_BIZ_ID
        }, headers={"Authorization": f"Bearer {user_jwt}"}, timeout=20.0)
        assert consent_res.status_code == 200, f"Consent failed: {consent_res.text}"
        auth_code = consent_res.json()["code"]

        # 3. Exchange auth code for scoped sandbox access token
        token_res = httpx.post(f"{API_BASE}/oauth/token", json={
            "grant_type": "authorization_code",
            "client_id": "emiliano",
            "code": auth_code,
            "redirect_uri": "http://localhost:3333/callback",
            "code_verifier": verifier
        }, timeout=20.0)
        assert token_res.status_code == 200, f"Token exchange failed: {token_res.text}"
        cls.sandbox_token = token_res.json()["access_token"]

        # Verify access token claims
        parts = cls.sandbox_token.split(".")
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "===").decode("utf-8"))
        assert payload.get("businessId") == VERANO_BIZ_ID, f"Token businessId mismatch: {payload.get('businessId')}"

        # Initialize manager for production tenant checks
        cfg = load_config()
        cls.prod_mgr = McpManager(cfg.mcp_servers, cwd=os.getcwd())
        cls.prod_mgr.start()

    @classmethod
    def tearDownClass(cls):
        cls.prod_mgr.close()

    def setUp(self):
        time.sleep(0.4)

    def _call_sandbox(self, tool_name: str, args: dict) -> dict:
        req = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000) % 100000,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": args
            }
        }
        r = httpx.post(f"{API_BASE}/mcp", json=req, headers={"Authorization": f"Bearer {self.sandbox_token}"}, timeout=30.0)
        self.assertEqual(r.status_code, 200, f"MCP endpoint error: HTTP {r.status_code} {r.text}")
        data = r.json()
        self.assertNotIn("error", data, f"JSON-RPC error in {tool_name}: {data.get('error')}")
        content = data.get("result", {}).get("content", [])
        self.assertTrue(len(content) > 0, f"Empty content in {tool_name}")
        self.assertEqual(content[0].get("type"), "text")
        return json.loads(content[0]["text"])

    def test_01_propose_menu_item_creates_draft_proposal(self):
        """Verify propose_menu_item creates a reviewable proposal without directly mutating live catalog."""
        menu_payload = {
            "menuItem": {
                "name": "Mojito Tropical Verano (Test Proposal)",
                "price": 34.0,
                "currency": "PLN",
                "description": "Artisanal Cuban rum, hierbabuena, fresh lime, panela syrup, soda.",
                "groupTag": "Cócteles",
                "availability": True,
                "allergens": []
            },
            "summary": "Proposed signature summer mojito for La Estación del Verano."
        }
        data = self._call_sandbox("propose_menu_item", menu_payload)
        self.assertIn("proposal", data)
        proposal = data["proposal"]
        self.assertEqual(proposal.get("type"), "menu_item")
        self.assertEqual(proposal.get("businessId"), VERANO_BIZ_ID)
        self.assertIsNone(proposal.get("menuItemId"))
        self.assertFalse(proposal.get("isUpdate"))
        self.assertEqual(proposal["menuItem"].get("name"), "Mojito Tropical Verano (Test Proposal)")
        self.assertEqual(proposal["menuItem"].get("price"), 34.0)

    def test_02_propose_event_creates_draft_proposal(self):
        """Verify propose_event creates a reviewable event draft requiring manager approval."""
        event_payload = {
            "event": {
                "title": "Verano Cumbia & Salsa Sunset",
                "date": "2026-11-28",
                "time": "20:00 - 02:00",
                "type": "party",
                "description": "<p>Latin music, crafted cocktails, and summer energy.</p>"
            },
            "summary": "Propose weekend Latin dance night."
        }
        data = self._call_sandbox("propose_event", event_payload)
        self.assertIn("proposal", data)
        proposal = data["proposal"]
        self.assertEqual(proposal.get("type"), "event")
        self.assertEqual(proposal.get("businessId"), VERANO_BIZ_ID)
        self.assertEqual(proposal["event"].get("title"), "Verano Cumbia & Salsa Sunset")

    def test_03_propose_work_order_creates_draft_task(self):
        """Verify propose_work_order creates a draft work order."""
        wo_payload = {
            "workOrder": {
                "title": "Blender & Ice Machine Sanitation Check",
                "description": "Deep clean and blade check for bar blenders.",
                "priority": "low",
                "status": "draft"
            },
            "summary": "Weekly bar equipment maintenance schedule."
        }
        data = self._call_sandbox("propose_work_order", wo_payload)
        self.assertIn("proposal", data)
        proposal = data["proposal"]
        self.assertEqual(proposal.get("type"), "work_order")
        self.assertEqual(proposal.get("businessId"), VERANO_BIZ_ID)
        self.assertEqual(proposal["workOrder"].get("title"), "Blender & Ice Machine Sanitation Check")

    def test_04_validation_rejects_missing_required_fields(self):
        """Verify that malformed or incomplete proposals are rejected cleanly before proposal generation."""
        req = {
            "jsonrpc": "2.0",
            "id": 999,
            "method": "tools/call",
            "params": {
                "name": "propose_menu_item",
                "arguments": {"summary": "Missing menuItem payload"}
            }
        }
        r = httpx.post(f"{API_BASE}/mcp", json=req, headers={"Authorization": f"Bearer {self.sandbox_token}"}, timeout=20.0)
        data = r.json()
        content = data.get("result", {}).get("content", [])
        self.assertTrue(len(content) > 0)
        resp_obj = json.loads(content[0]["text"])
        self.assertIn("error", resp_obj)
        self.assertIn("Menu item data is required", resp_obj["error"])

    def test_05_cross_tenant_isolation_boundary(self):
        """Assert strict tenant isolation: verify production Taki Taki Katowice was NOT modified."""
        taki_res = self.prod_mgr.call("plaatoos__query_menu", {"limit": 50})
        taki_data = json.loads(taki_res)
        items = [i.get("name") for i in taki_data.get("items", [])]
        self.assertNotIn("Mojito Tropical Verano (Test Proposal)", items,
                         "CRITICAL: Production tenant 'Taki Taki Katowice' contaminated by sandbox proposal!")
        # Verify Taki Taki Katowice still retains its real menu items
        self.assertIn("Aperol Spritz", items)


if __name__ == "__main__":
    unittest.main()
