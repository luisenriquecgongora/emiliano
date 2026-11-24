"""
End-to-end WebSocket and Chat UI Evaluation for Emiliano Desktop & PlaatoOS MCP Tools.
Tests simulated user flows for querying and updating website content (Luis Enrique Builds & La Estación del Verano),
verifying streaming chunks, tool execution badges, proposal generation, and negative routing boundaries.
"""

import asyncio
import sys
import time
from pathlib import Path

# Add engine package to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from emiliano.core.capabilities import Capability, CapabilityStatus, ExecutionType
from emiliano.server.app import app, get_dispatcher


def run_desktop_mcp_evaluation():
    print("================================================================================")
    print("      EMILIANO DESKTOP CHAT & PLAATOOS MCP EVALUATION BENCHMARK               ")
    print("================================================================================")

    client = TestClient(app, base_url="http://127.0.0.1")
    dispatcher = get_dispatcher()

    # Verify MCP server is configured and loaded
    mcp_servers = getattr(dispatcher.config, "mcp_servers", {})
    print(f"📡 Configured MCP Servers: {list(mcp_servers.keys())}")

    # Create a test chat container
    chat_resp = client.post("/api/chats", json={"title": "Site & MCP Evaluation Chat"})
    assert chat_resp.status_code == 201, f"Failed to create chat: {chat_resp.text}"
    chat = chat_resp.json()
    chat_id = chat["id"]
    print(f"💬 Created Test Chat Session: {chat_id}")

    test_scenarios = [
        {
            "id": "eval-1-query-site",
            "title": "Scenario 1: Query Website & Navigation Structure",
            "prompt": "Query our business website title and navigation structure on PlaatoOS",
            "mock_tool": "plaatoos__query_business_site",
            "mock_reply": "Our website 'Taki Taki Katowice' has 4 pages with 'O Taki Taki' as primary navigation.",
            "expect_tool": True,
        },
        {
            "id": "eval-2-update-estacion-verano",
            "title": "Scenario 2: Update La Estación del Verano Summer Hero Block",
            "prompt": "Update La Estacion del Verano site with the latest weekend cocktail schedule",
            "mock_tool": "plaatoos__patch_site_block",
            "mock_reply": "Proposed patch for block 'hero_summer' updating headline to 'La Estación del Verano — Summer 2026 Cocktail Nights'.",
            "expect_tool": True,
        },
        {
            "id": "eval-3-update-luis-enrique-builds",
            "title": "Scenario 3: Update Luis Enrique Builds Portfolio Subpages",
            "prompt": "Update Luis Enrique Builds site with new project subpages and download buttons",
            "mock_tool": "plaatoos__propose_partial_site_update",
            "mock_reply": "Created proposal for adding project subpages 'emiliano-desktop' and 'bobby-spatial-engine' with direct download action buttons.",
            "expect_tool": True,
        },
        {
            "id": "eval-4-negative-greeting",
            "title": "Scenario 4: Negative Boundary — Casual Greeting (No Tool Overhead)",
            "prompt": "Hello Emiliano! How are you doing today?",
            "mock_tool": None,
            "mock_reply": "Hello! I am doing great, ready to help you with your projects, code, or website updates.",
            "expect_tool": False,
        },
        {
            "id": "eval-5-query-finances",
            "title": "Scenario 5: Business Intelligence — Query Monthly Finances & Net Income",
            "prompt": "Query our business finances and monthly income breakdown on PlaatoOS",
            "mock_tool": "plaatoos__query_finances",
            "mock_reply": "Financial report for current month: Gross revenue 84,250 PLN across 16 closed shifts. Net margin: 92%.",
            "expect_tool": True,
        },
        {
            "id": "eval-6-query-shift-money",
            "title": "Scenario 6: Shift Operations — Query Till Cash & Payment Methods",
            "prompt": "Query our shift money breakdown, cash in till, and card payouts on PlaatoOS",
            "mock_tool": "plaatoos__query_shift_money",
            "mock_reply": "Shift report: Cash in till: 4,120 PLN | Card terminal: 8,940 PLN | BLIK: 1,890 PLN | Cash payouts: 350 PLN.",
            "expect_tool": True,
        },
        {
            "id": "eval-7-query-song-requests",
            "title": "Scenario 7: Nightlife Telemetry — Query Top Requested Karaoke Songs",
            "prompt": "What are the top most requested karaoke songs this month on PlaatoOS?",
            "mock_tool": "plaatoos__query_song_requests",
            "mock_reply": "Top requested songs: 1. 'Wehikuł Czasu' (42x), 2. 'I Wanna Dance with Somebody' (38x), 3. 'Przez Twe Oczy Zielone' (29x).",
            "expect_tool": True,
        },
        {
            "id": "eval-8-query-playlists",
            "title": "Scenario 8: Nightlife Telemetry — Query Active Karaoke Playlists & Room Queues",
            "prompt": "Query our active karaoke playlists and room queues on PlaatoOS",
            "mock_tool": "plaatoos__query_playlists",
            "mock_reply": "Active playlists: Main Stage (18 queued tracks), VIP Room A (7 queued tracks), Latin Lounge (12 queued tracks).",
            "expect_tool": True,
        },
        {
            "id": "eval-9-query-business-settings",
            "title": "Scenario 9: General Business Data — Venue Profile, Schedule & Settings",
            "prompt": "Query our venue settings, opening hours, and contact details on PlaatoOS",
            "mock_tool": "plaatoos__query_business_settings",
            "mock_reply": "Venue: 'Taki Taki Katowice' (Mariacka 12, Katowice). Hours: Thu 18:00-02:00, Fri-Sat 18:00-05:00. WiFi: TakiGuest.",
            "expect_tool": True,
        },
        {
            "id": "eval-10-predict-revenue",
            "title": "Scenario 10: Predictive Analytics — Revenue Machine Learning Forecast",
            "prompt": "Forecast our expected revenue for tonight on PlaatoOS using predictive analytics",
            "mock_tool": "plaatoos__predict_revenue",
            "mock_reply": "Tonight's revenue forecast (Friday): P10: 12,400 PLN | P50: 16,800 PLN | P90: 22,100 PLN based on 8 reservations and payday cycle.",
            "expect_tool": True,
        },
    ]

    results = []

    for scenario in test_scenarios:
        print(f"\n▶ Running {scenario['title']}...")
        print(f"  Prompt: '{scenario['prompt']}'")

        # Mock direct model execution to record tool call streaming
        mock_cap = Capability(
            name="ollama",
            display_name="Ollama (Local)",
            execution_type=ExecutionType.DIRECT_MODEL,
            status=CapabilityStatus.READY,
            selected_model="qwen2.5-coder:32b",
        )

        async def fake_execute_task(**kwargs):
            if kwargs.get("on_route_selected"):
                kwargs["on_route_selected"](mock_cap)

            goal = kwargs.get("goal", "")
            on_chunk = kwargs.get("on_chunk")

            # Check if goal was detected as tool-enabled
            has_mcp = bool(getattr(dispatcher.config, "mcp_servers", None))
            from emiliano.core.routing import needs_mcp_or_tools
            is_mcp_task = has_mcp and needs_mcp_or_tools(goal)

            if scenario["expect_tool"]:
                assert is_mcp_task, f"Goal '{goal}' should have triggered is_mcp_task=True"
                if on_chunk:
                    on_chunk(f"\n[MCP Tool: {scenario['mock_tool']}]\n")
                    await asyncio.sleep(0.01)
                    on_chunk(scenario["mock_reply"])
            else:
                assert not is_mcp_task, f"Goal '{goal}' should have triggered is_mcp_task=False"
                if on_chunk:
                    on_chunk(scenario["mock_reply"])

            return mock_cap, scenario["mock_reply"]

        with TestClient(app, base_url="http://127.0.0.1") as ws_client:
            with ws_client.websocket_connect("ws://127.0.0.1/api/chat", headers={"host": "127.0.0.1", "origin": "http://tauri.localhost"}) as ws:
                t0 = time.monotonic()
                from unittest.mock import patch
                with patch.object(dispatcher, "execute_task", side_effect=fake_execute_task):
                    ws.send_json({
                        "type": "send",
                        "chat_id": chat_id,
                        "content": scenario["prompt"],
                        "mode": "auto",
                    })

                    _received_route = None
                    chunks = []
                    done_message = None

                    while True:
                        msg = ws.receive_json()
                        m_type = msg.get("type")

                        if m_type == "route":
                            _received_route = msg.get("name")
                        elif m_type == "chunk":
                            chunks.append(msg.get("content", ""))
                        elif m_type == "done":
                            done_message = msg.get("message")
                            break
                        elif m_type == "error":
                            raise RuntimeError(f"Engine error: {msg.get('message')}")

                    duration = round(time.monotonic() - t0, 3)
                    full_content = "".join(chunks)

                    # Verify expectations
                    tool_detected = "[MCP Tool:" in full_content
                    if scenario["expect_tool"]:
                        assert tool_detected, f"Expected [MCP Tool: ...] badge in chunks, got: {full_content}"
                        assert scenario["mock_tool"] in full_content
                        print(f"  ✅ MCP Tool Badge Streamed: [MCP Tool: {scenario['mock_tool']}]")
                    else:
                        assert not tool_detected, f"Did not expect MCP Tool badge in greeting, got: {full_content}"
                        print("  ✅ Conversational Stream (Zero Tool Overhead)")

                    assert done_message is not None, "Missing 'done' message"
                    print(f"  ✅ Done Event Received ({duration}s)")

                    results.append({
                        "id": scenario["id"],
                        "status": "PASSED",
                        "duration_s": duration,
                        "tool_verified": tool_detected == scenario["expect_tool"],
                    })

    # Summary
    print("\n================================================================================")
    print("                         BENCHMARK EVALUATION RESULTS                           ")
    print("================================================================================")
    passed = sum(1 for r in results if r["status"] == "PASSED")
    print(f"Total Scenarios: {len(results)} | Passed: {passed} | Pass Rate: {passed/len(results)*100:.1f}%\n")
    for r in results:
        print(f"  • {r['id']:<32} : {r['status']} ({r['duration_s']}s)")

    # Clean up test chat
    client.delete(f"/api/chats/{chat_id}")
    print(f"\n🧹 Cleaned up test chat {chat_id}.")
    print("================================================================================")


def test_desktop_mcp_evaluation():
    run_desktop_mcp_evaluation()


if __name__ == "__main__":
    run_desktop_mcp_evaluation()
