"""
Tests for saved chats: the history store's REST API and the streaming chat WebSocket.
"""

import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from emiliano.core.capabilities import Capability, CapabilityStatus, ExecutionType
from emiliano.history import HistoryStore
from emiliano.server.app import app, get_dispatcher

WS_URL = "ws://127.0.0.1/api/chat"
OLLAMA = Capability(name="ollama", display_name="Ollama (Local)", execution_type=ExecutionType.DIRECT_MODEL,
                    status=CapabilityStatus.READY)


class HistoryTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = HistoryStore(f"sqlite:///{os.path.join(self.tmp.name, 'history.db')}")
        self._previous = app.state.get_history_store
        app.state.get_history_store = lambda: self.store
        self.client = TestClient(app, base_url="http://127.0.0.1")

    def tearDown(self):
        app.state.get_history_store = self._previous
        self.store.engine.dispose()
        self.tmp.cleanup()


class TestChatsApi(HistoryTestCase):
    def test_create_list_open_delete(self):
        first = self.client.post("/api/chats", json={}).json()
        second = self.client.post("/api/chats", json={"title": "Plans"}).json()
        self.assertEqual(first["title"], "New chat")
        self.assertEqual([c["id"] for c in self.client.get("/api/chats").json()], [second["id"], first["id"]])

        opened = self.client.get(f"/api/chats/{first['id']}").json()
        self.assertEqual(opened["messages"], [])

        self.assertEqual(self.client.delete(f"/api/chats/{first['id']}").status_code, 204)
        self.assertEqual(self.client.get(f"/api/chats/{first['id']}").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/chats/{first['id']}").status_code, 404)
        self.assertEqual([c["id"] for c in self.client.get("/api/chats").json()], [second["id"]])

    def test_delete_all(self):
        for _ in range(3):
            self.client.post("/api/chats", json={})
        self.assertEqual(self.client.delete("/api/chats").json(), {"deleted": 3})
        self.assertEqual(self.client.get("/api/chats").json(), [])

    def test_foreign_origin_cannot_read_history(self):
        resp = self.client.get("/api/chats", headers={"origin": "https://evil.example"})
        self.assertEqual(resp.status_code, 403)


class TestChatSocket(HistoryTestCase):
    def _receive_until(self, ws, final_types):
        events = []
        while True:
            event = ws.receive_json()
            events.append(event)
            if event["type"] in final_types:
                return events

    def test_reply_is_streamed_and_saved(self):
        chat = self.client.post("/api/chats", json={}).json()
        seen = {}

        async def fake_execute_task(**kwargs):
            seen.update(kwargs)
            kwargs["on_route_selected"](OLLAMA)
            kwargs["on_reasoning"]("thinking...")
            kwargs["on_chunk"]("Hello")
            kwargs["on_chunk"](" there!")
            return OLLAMA, "Hello there!"

        with patch.object(get_dispatcher(), "execute_task", side_effect=fake_execute_task):
            with self.client.websocket_connect(WS_URL) as ws:
                ws.send_json({"type": "send", "chat_id": chat["id"], "content": "hi", "mode": "auto"})
                events = self._receive_until(ws, {"done", "error"})

        self.assertEqual([e["type"] for e in events], ["user_message", "route", "reasoning", "chunk", "chunk", "done"])
        self.assertEqual(seen["messages"], [{"role": "user", "content": "hi"}])
        done = events[-1]
        self.assertEqual(done["message"]["content"], "Hello there!")
        self.assertEqual(done["chat"]["title"], "hi")
        self.assertEqual([m["role"] for m in self.store.get_chat(chat["id"])["messages"]], ["user", "assistant"])

    def test_follow_up_includes_conversation_history(self):
        chat = self.client.post("/api/chats", json={}).json()
        self.store.add_message(chat["id"], "user", "my name is Ana")
        self.store.add_message(chat["id"], "assistant", "Nice to meet you, Ana!")
        seen = {}

        async def fake_execute_task(**kwargs):
            seen.update(kwargs)
            return OLLAMA, "Your name is Ana."

        with patch.object(get_dispatcher(), "execute_task", side_effect=fake_execute_task):
            with self.client.websocket_connect(WS_URL) as ws:
                ws.send_json({"type": "send", "chat_id": chat["id"], "content": "what is my name?", "mode": "claude_code"})
                self._receive_until(ws, {"done", "error"})

        self.assertEqual([m["content"] for m in seen["messages"]],
                         ["my name is Ana", "Nice to meet you, Ana!", "what is my name?"])
        self.assertEqual(seen["harness_override"], "claude")

    def test_cancel_keeps_partial_answer(self):
        chat = self.client.post("/api/chats", json={}).json()

        async def slow_execute_task(**kwargs):
            kwargs["on_chunk"]("Partial")
            await asyncio.sleep(10)
            return OLLAMA, "never"

        with patch.object(get_dispatcher(), "execute_task", side_effect=slow_execute_task):
            with self.client.websocket_connect(WS_URL) as ws:
                ws.send_json({"type": "send", "chat_id": chat["id"], "content": "write an essay"})
                self._receive_until(ws, {"chunk"})
                ws.send_json({"type": "cancel"})
                events = self._receive_until(ws, {"cancelled", "done", "error"})

        self.assertEqual(events[-1]["type"], "cancelled")
        messages = self.store.get_chat(chat["id"])["messages"]
        self.assertEqual(messages[-1]["content"], "Partial\n\n[stopped]")

    def test_unknown_chat_and_empty_message(self):
        with self.client.websocket_connect(WS_URL) as ws:
            ws.send_json({"type": "send", "chat_id": "missing", "content": "hi"})
            self.assertEqual(ws.receive_json()["code"], "CHAT_NOT_FOUND")
            ws.send_json({"type": "send", "chat_id": "missing", "content": "   "})
            self.assertEqual(ws.receive_json()["code"], "EMPTY")

    def test_foreign_origin_cannot_open_chat_socket(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(WS_URL, headers={"origin": "https://evil.example"}):
                pass


if __name__ == "__main__":
    unittest.main()
