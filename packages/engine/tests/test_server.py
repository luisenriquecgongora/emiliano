"""
Unit tests for Emiliano Engine WebSocket IPC Server.
Tests endpoints, WebSocket lifecycle, task dispatching, and task cancellation.
"""

import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from emiliano.core.capabilities import Capability, CapabilityStatus, ExecutionType
from emiliano.server.app import app, get_dispatcher


class TestServerIPC(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, base_url="http://127.0.0.1")

    def test_health_endpoint(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok", "service": "emiliano-engine"})

    def test_api_models_endpoint(self):
        mock_cap = Capability(
            name="ollama",
            display_name="Ollama (Local)",
            execution_type=ExecutionType.DIRECT_MODEL,
            status=CapabilityStatus.READY,
            selected_model="qwen3.5:2b",
            available_models=["qwen3.5:2b"],
        )
        dispatcher = get_dispatcher()
        with patch.object(dispatcher.registry, "discover_all", new_callable=AsyncMock) as mock_disc:
            mock_disc.return_value = {"ollama": mock_cap}
            resp = self.client.get("/api/models")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("models", data)
            self.assertEqual(len(data["models"]), 1)
            self.assertEqual(data["models"][0]["name"], "ollama")

    def test_websocket_ping_pong(self):
        with self.client.websocket_connect("ws://127.0.0.1/ws") as ws:
            ws.send_text(json.dumps({"type": "PING"}))
            msg = json.loads(ws.receive_text())
            self.assertEqual(msg["type"], "PONG")

    def test_websocket_get_capabilities(self):
        mock_cap = Capability(
            name="agy",
            display_name="Antigravity (AGY)",
            execution_type=ExecutionType.AGENT_HARNESS,
            status=CapabilityStatus.READY,
        )
        dispatcher = get_dispatcher()
        with patch.object(dispatcher.registry, "discover_all", new_callable=AsyncMock) as mock_disc:
            mock_disc.return_value = {"agy": mock_cap}
            with self.client.websocket_connect("ws://127.0.0.1/ws") as ws:
                ws.send_text(json.dumps({"type": "GET_CAPABILITIES"}))
                msg = json.loads(ws.receive_text())
                self.assertEqual(msg["type"], "CAPABILITIES_RESPONSE")
                caps = msg["payload"]["capabilities"]
                self.assertEqual(len(caps), 1)
                self.assertEqual(caps[0]["name"], "agy")

    def test_websocket_task_start_and_completion(self):
        mock_cap = Capability(
            name="ollama",
            display_name="Ollama (Local)",
            execution_type=ExecutionType.DIRECT_MODEL,
            status=CapabilityStatus.READY,
            selected_model="qwen3.5:2b",
        )

        dispatcher = get_dispatcher()

        async def fake_execute_task(**kwargs):
            if kwargs.get("on_route_selected"):
                kwargs["on_route_selected"](mock_cap)
            await asyncio.sleep(0.02)
            if kwargs.get("on_chunk"):
                kwargs["on_chunk"]("Thinking... ")
            await asyncio.sleep(0.02)
            return mock_cap, "Task result completed"

        with patch.object(dispatcher, "execute_task", side_effect=fake_execute_task):
            with self.client.websocket_connect("ws://127.0.0.1/ws") as ws:
                ws.send_text(json.dumps({
                    "type": "TASK_START",
                    "payload": {
                        "taskId": "task-test-1",
                        "goal": "Test goal execution",
                        "harnessPreference": "auto"
                    }
                }))

                received_types = []
                completed_found = False
                for _ in range(8):
                    try:
                        raw = ws.receive_text()
                        msg = json.loads(raw)
                        received_types.append(msg["type"])
                        if msg["type"] == "DAG_UPDATE" and msg["payload"].get("status") == "completed":
                            self.assertEqual(msg["payload"]["output"], "Task result completed")
                            completed_found = True
                        if completed_found and "THOUGHT_STREAM" in received_types:
                            break
                    except Exception:
                        break

                self.assertTrue(completed_found)
                self.assertIn("DAG_UPDATE", received_types)
                self.assertIn("THOUGHT_STREAM", received_types)

    def test_websocket_task_cancel(self):
        dispatcher = get_dispatcher()

        async def slow_execute_task(**kwargs):
            await asyncio.sleep(10.0)
            return MagicMock(), "Never reached"

        with patch.object(dispatcher, "execute_task", side_effect=slow_execute_task):
            with self.client.websocket_connect("ws://127.0.0.1/ws") as ws:
                ws.send_text(json.dumps({
                    "type": "TASK_START",
                    "payload": {
                        "taskId": "task-slow",
                        "goal": "Slow task",
                    }
                }))

                # Read initial running DAG_UPDATE
                first_msg = json.loads(ws.receive_text())
                self.assertEqual(first_msg["type"], "DAG_UPDATE")
                self.assertEqual(first_msg["payload"]["status"], "running")

                # Send cancel
                ws.send_text(json.dumps({
                    "type": "TASK_CANCEL",
                    "payload": {"taskId": "task-slow"}
                }))

                # Expect paused/cancelled update
                cancelled = False
                for _ in range(4):
                    try:
                        msg = json.loads(ws.receive_text())
                        if msg["type"] == "DAG_UPDATE" and msg["payload"].get("status") == "paused":
                            cancelled = True
                            break
                    except Exception:
                        break

                self.assertTrue(cancelled)


class TestWebSocketOriginCheck(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, base_url="http://127.0.0.1")

    def _ping(self, origin):
        headers = {"origin": origin} if origin is not None else {}
        with self.client.websocket_connect("ws://127.0.0.1/ws", headers=headers) as ws:
            ws.send_text(json.dumps({"type": "PING"}))
            return json.loads(ws.receive_text())["type"]

    def test_desktop_origins_and_local_clients_allowed(self):
        for origin in ("http://tauri.localhost", "tauri://localhost", "http://localhost:5173", "http://127.0.0.1:5173/", None):
            with self.subTest(origin=origin):
                self.assertEqual(self._ping(origin), "PONG")

    def test_foreign_and_null_origins_rejected(self):
        for origin in ("https://evil.example", "http://localhost:3000", "null", "file://"):
            with self.subTest(origin=origin):
                with self.assertRaises(WebSocketDisconnect):
                    self._ping(origin)

    def test_rejected_origin_cannot_start_task(self):
        dispatcher = get_dispatcher()
        with patch.object(dispatcher, "execute_task", new_callable=AsyncMock) as mock_exec:
            with self.assertRaises(WebSocketDisconnect):
                with self.client.websocket_connect("ws://127.0.0.1/ws", headers={"origin": "https://evil.example"}) as ws:
                    ws.send_text(json.dumps({"type": "TASK_START", "payload": {"goal": "rm -rf ~"}}))
            mock_exec.assert_not_called()

    def test_allowed_origins_env_override(self):
        with patch.dict(os.environ, {"EMILIANO_ALLOWED_ORIGINS": "app://emiliano, http://localhost:4000"}):
            self.assertEqual(self._ping("app://emiliano"), "PONG")
            with self.assertRaises(WebSocketDisconnect):
                self._ping("http://localhost:5173")


class TestStartup(unittest.TestCase):
    def test_discovery_warms_up_at_startup(self):
        with patch.object(get_dispatcher(), "warm_up", new_callable=AsyncMock) as warm_up:
            with TestClient(app, base_url="http://127.0.0.1") as client:  # "with" runs startup
                client.get("/health")
        warm_up.assert_awaited_once()


class TestHttpRequestChecks(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, base_url="http://127.0.0.1")

    def test_rebinding_host_is_rejected(self):
        # A DNS-rebinding page reaches 127.0.0.1 but sends its own domain as Host
        resp = self.client.get("/health", headers={"host": "evil.example:8765"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.client.get("/health", headers={"host": "localhost:8765"}).status_code, 200)

    def test_foreign_origin_is_rejected(self):
        self.assertEqual(self.client.get("/health", headers={"origin": "https://evil.example"}).status_code, 403)
        self.assertEqual(self.client.get("/health", headers={"origin": "http://tauri.localhost"}).status_code, 200)

    def test_desktop_app_cors_preflight(self):
        resp = self.client.options("/health", headers={
            "origin": "http://tauri.localhost",
            "access-control-request-method": "DELETE",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("access-control-allow-origin"), "http://tauri.localhost")


if __name__ == "__main__":
    unittest.main()
