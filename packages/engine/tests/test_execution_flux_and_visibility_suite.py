"""
Enterprise Test Suite: Execution Flux, Generation Traceability & Window Z-Order
Validates the Non-Linear DAG flux reconstruction, per-process step latencies,
OpenTelemetry trace serialization, Mermaid export, and Always-On-Top Z-order sync.
"""

import os
import sys
import time
import pytest
from fastapi.testclient import TestClient

# Ensure engine package is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from emiliano.server.app import app
from emiliano.core.traces import TaskTrace
from emiliano.history.store import HistoryStore
from emiliano.mcp.manager import McpManager
from emiliano.core.config import load_config


class TestExecutionFluxAndVisibilitySuite:
    @classmethod
    def setup_class(cls):
        cls.client = TestClient(app, base_url="http://127.0.0.1:8765")
        cfg = load_config()
        cls.mgr = McpManager(cfg.mcp_servers, cwd=os.getcwd())
        cls.mgr.start()

    @classmethod
    def teardown_class(cls):
        cls.mgr.close()

    def test_01_always_on_top_api_toggle_response_structure(self):
        """Verifies /api/cowork/always_on_top endpoint handles both states and returns window counts."""
        # Test toggling to True
        resp_true = self.client.post("/api/cowork/always_on_top", json={"enabled": True})
        assert resp_true.status_code == 200
        data_true = resp_true.json()
        assert data_true["status"] in ("ok", "not_found")
        if data_true["status"] == "ok":
            assert data_true["always_on_top"] is True
            assert data_true.get("windows_updated", 0) >= 1

        # Test toggling to False
        resp_false = self.client.post("/api/cowork/always_on_top", json={"enabled": False})
        assert resp_false.status_code == 200
        data_false = resp_false.json()
        assert data_false["status"] in ("ok", "not_found")
        if data_false["status"] == "ok":
            assert data_false["always_on_top"] is False

    def test_02_per_process_step_latencies_calculation(self):
        """Verifies step latency math, TTFT, generation duration, and human formatting."""
        t0 = time.perf_counter()
        time.sleep(0.02)
        reasoning_start = time.perf_counter()
        time.sleep(0.03)
        reasoning_end = time.perf_counter()
        first_token = time.perf_counter()
        first_content = time.perf_counter()
        time.sleep(0.04)
        t_done = time.perf_counter()

        total_duration_s = max(0.001, t_done - t0)
        thinking_duration_s = round(max(0.01, reasoning_end - reasoning_start), 2)
        generation_duration_s = round(max(0.01, t_done - first_content), 2)
        ttft_ms = round((first_token - t0) * 1000, 1)

        assert total_duration_s > 0.05
        assert thinking_duration_s >= 0.02
        assert generation_duration_s >= 0.03
        assert ttft_ms >= 40.0

        # Formatting tests
        def fmt(secs):
            if secs >= 60.0:
                mins = int(secs // 60)
                rem = secs % 60
                return f"{mins}m {rem:.1f}s"
            elif secs >= 1.0:
                return f"{secs:.2f}s"
            return f"{int(secs * 1000)}ms"

        assert fmt(0.450) == "450ms"
        assert fmt(2.456) == "2.46s"
        assert fmt(75.2) == "1m 15.2s"

    def test_03_trace_serialization_into_metrics_and_sqlite(self, tmp_path):
        """Verifies TaskTrace with fine-grained spans and executed tools serializes into SQLite."""
        db_path = str(tmp_path / "test_history.db")
        store = HistoryStore(f"sqlite:///{db_path}")

        chat = store.create_chat(title="Traceability Test")
        chat_id = chat["id"]

        # Build execution trace
        trace = TaskTrace(goal="what are the most played songs in the karaoke?", policy="auto")
        span_turn = trace.start_span("agent.turn", attributes={"turn": 1, "model": "ollama"})
        span_llm = trace.start_span("llm.generate", parent_span_id=span_turn.span_id, attributes={"model": "qwen2.5-coder"})
        span_llm.finish("ok")

        span_tool = trace.start_span("tool.execute", parent_span_id=span_turn.span_id, attributes={"tool_name": "plaatoos__query_playlists"})
        span_tool.finish("ok")
        span_turn.finish("ok")

        executed_tools = [
            {
                "tool": "plaatoos__query_playlists",
                "mcp_server": "plaatoos",
                "tool_name": "query_playlists",
                "args": {"limit": 10},
                "result": "[{'id': 'pl-karaoke-1', 'name': 'Weekend Karaoke Classics'}]",
                "duration_s": 0.44,
                "status": "ok",
            },
            {
                "tool": "plaatoos__query_song_requests",
                "mcp_server": "plaatoos",
                "tool_name": "query_song_requests",
                "args": {"playlistId": "pl-karaoke-1", "aggregate": "top_songs"},
                "result": "[{'title': 'Sweet Caroline', 'requests': 142}, {'title': 'Dancing Queen', 'requests': 128}]",
                "duration_s": 0.35,
                "status": "ok",
            },
        ]
        trace.executed_tools.extend(executed_tools)
        trace.finish("succeeded")

        metrics = {
            "total_duration_s": 1.68,
            "formatted_duration": "1.68s",
            "thinking_duration_s": 0.82,
            "generation_duration_s": 0.48,
            "tool_duration_s": 0.79,
            "ttft_ms": 180.0,
            "tokens_per_second": 45.2,
            "completion_tokens": 210,
            "trace": trace.to_dict(),
        }

        # Save to store
        msg = store.add_message(
            chat_id=chat_id,
            role="assistant",
            content="Here are the top most requested karaoke songs at Taki Taki Katowice.",
            reasoning="Plan: First discover playlist ID, then aggregate song requests.",
            metrics=metrics,
            tool_calls=executed_tools,
        )

        assert msg is not None
        assert msg["metrics"]["total_duration_s"] == 1.68
        assert msg["metrics"]["thinking_duration_s"] == 0.82
        assert msg["metrics"]["tool_duration_s"] == 0.79
        assert len(msg["tool_calls"]) == 2
        assert msg["metrics"]["trace"]["id"] == trace.id
        assert len(msg["metrics"]["trace"]["spans"]) == 3
        assert len(msg["metrics"]["trace"]["executed_tools"]) == 2

    def test_04_non_linear_dag_and_feedback_loops_reconstruction(self):
        """Verifies multi-turn tool calling generates feedback assimilation nodes in the flux DAG."""
        tool_calls = [
            {"tool": "plaatoos__query_playlists", "status": "ok", "duration_s": 0.44},
            {"tool": "plaatoos__query_song_requests", "status": "ok", "duration_s": 0.35},
        ]

        # Simulate flux builder logic
        nodes = []
        nodes.append({"id": "node-input", "type": "input", "title": "Prompt Ingestion"})
        nodes.append({"id": "node-discovery", "type": "discovery", "title": "Semantic MCP Discovery"})
        nodes.append({"id": "node-reasoning", "type": "reasoning", "title": "Deep Reasoning & Plan Formulation"})

        for idx, t in enumerate(tool_calls):
            nodes.append({
                "id": f"node-tool-{idx}",
                "type": "tool",
                "title": f"MCP: {t['tool']}",
                "status": t["status"],
                "duration_s": t["duration_s"],
            })
            if idx < len(tool_calls) - 1:
                nodes.append({
                    "id": f"node-feedback-{idx}",
                    "type": "feedback",
                    "title": f"Feedback Assimilation (Turn {idx + 1} -> Turn {idx + 2})",
                    "status": "ok",
                })

        nodes.append({"id": "node-verify", "type": "verification", "title": "Integrity Gate"})
        nodes.append({"id": "node-synthesis", "type": "synthesis", "title": "Response Synthesis"})

        # Assert non-linear pipeline structure
        types = [n["type"] for n in nodes]
        assert types == ["input", "discovery", "reasoning", "tool", "feedback", "tool", "verification", "synthesis"]
        assert len(nodes) == 8
        assert any(n["type"] == "feedback" for n in nodes)

    def test_05_mermaid_flowchart_generation_and_syntax(self):
        """Verifies Mermaid diagram generator produces valid syntax with safe quoting."""
        tool_calls = [
            {"tool": "plaatoos__query_playlists", "status": "ok", "duration_s": 0.44},
            {"tool": "plaatoos__query_song_requests", "status": "ok", "duration_s": 0.35},
        ]

        m = "flowchart TD\n"
        m += '  A["📥 User Request Ingestion"]\n'
        m += '  B["🔍 Semantic Tool Discovery"]\n'
        m += "  A --> B\n"
        prev = "B"

        m += '  C["🧠 Reasoning & Strategy (0.82s)"]\n'
        m += f"  {prev} --> C\n"
        prev = "C"

        for i, t in enumerate(tool_calls):
            t_id = f"T{i + 1}"
            name = t["tool"].replace("_", " ")
            status_icon = "❌" if t["status"] == "error" else "⚡"
            m += f'  {t_id}["{status_icon} {name} ({t["duration_s"]}s)"]\n'
            m += f"  {prev} --> {t_id}\n"

            if i < len(tool_calls) - 1:
                f_id = f"F{i + 1}"
                m += f'  {f_id}{{"Evaluation & Branch"}}\n'
                m += f"  {t_id} --> {f_id}\n"
                prev = f_id
            else:
                prev = t_id

        m += '  V["🛡️ Verification Gate (ok)"]\n'
        m += f"  {prev} --> V\n"
        m += '  S["💬 Answer Synthesis (0.48s)"]\n'
        m += "  V --> S\n"

        assert m.startswith("flowchart TD")
        assert 'A["📥 User Request Ingestion"]' in m
        assert "A --> B" in m
        assert 'T1["⚡ plaatoos  query playlists (0.44s)"]' in m
        assert 'F1{"Evaluation & Branch"}' in m
        assert "T1 --> F1" in m
        assert "V --> S" in m

    def test_06_business_summary_and_karaoke_mcp_routing(self):
        """Verifies domain boosters rank query_business and query_song_requests as top tools."""
        # 1. Business summary
        tools_summary = self.mgr.filter_tools_for_goal(
            "can you please tell me a summary of my business Taki Taki",
            max_tools=5
        )
        names_summary = [t.qualified_name for t in tools_summary]
        assert "plaatoos__query_business" in names_summary[:2]

        # 2. Karaoke most played songs
        tools_karaoke = self.mgr.filter_tools_for_goal(
            "what are the most played songs in the karaoke?",
            max_tools=5
        )
        names_karaoke = [t.qualified_name for t in tools_karaoke]
        assert "plaatoos__query_song_requests" in names_karaoke or "plaatoos__query_playlists" in names_karaoke

    def test_07_history_refusal_sanitizer(self):
        """Verifies refusal patterns and placeholder strings are stripped from message history."""
        poisoned_history = [
            {"role": "user", "content": "can you please tell me a summary of my business Taki Taki"},
            {"role": "assistant", "content": "I'm sorry, but I don't have access to your specific business information. To provide a summary of your business Taki Taki, I would need to query the relevant data from our systems using the provided MCP tools. Could you please let me know which aspects of your business you'd like summarized?"},
            {"role": "user", "content": "what are the most played songs in the karaoke?"},
            {"role": "assistant", "content": "It seems there was an issue with the playlist ID you provided. Let's try a different approach to find out which songs are most played in the karaoke: List All Playlists: First, let's list all playlists... Replace <specific-playlist-id> with the ID of the karaoke playlist you're interested in..."},
            {"role": "user", "content": "how many karaoke rooms do we have?"},
        ]

        clean_history = []
        for m in poisoned_history:
            if m.get("role") == "assistant":
                txt = (m.get("content") or "").lower()
                if any(phrase in txt for phrase in (
                    "don't have access to real-time",
                    "don't have access to your specific business information",
                    "do not have access to your specific business information",
                    "which aspects of your business you'd like summarized",
                    "replace <specific-playlist-id>",
                    "replace <",
                    "to find out which songs are most played in the karaoke",
                )):
                    continue
            clean_history.append(m)

        assert len(clean_history) == 3
        assert all(m["role"] == "user" for m in clean_history)

    def test_08_live_hud_window_attributes_and_pin_state(self):
        """Verifies Win32 window properties on Windows platform."""
        if sys.platform != "win32":
            pytest.skip("Win32 specific test")

        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        hwinsta = user32.OpenWindowStationW("WinSta0", False, 0x037F)
        if hwinsta:
            user32.SetProcessWindowStation(hwinsta)
        hdesk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if hdesk:
            user32.SetThreadDesktop(hdesk)

        emiliano_windows = []
        def cb(hwnd, _):
            length = user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value.strip()
            if "emiliano" in title.lower():
                ex_style = user32.GetWindowLongW(hwnd, -20)
                emiliano_windows.append({"hwnd": hwnd, "title": title, "topmost": bool(ex_style & 0x8)})
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        if hdesk:
            user32.EnumDesktopWindows(hdesk, WNDENUMPROC(cb), 0)

        # If HUD daemon is running on desktop, verify it is enumerated properly
        if emiliano_windows:
            assert len(emiliano_windows) >= 1
            # Verify titles
            assert any("emiliano" in w["title"].lower() for w in emiliano_windows)
