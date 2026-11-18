"""
Tests for saved chats: the history store's REST API and the streaming chat WebSocket.
"""

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

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

    def test_chat_context_metrics(self):
        chat = self.client.post("/api/chats", json={"title": "Context Test"}).json()
        self.store.add_message(chat["id"], "user", "Hello assistant!")
        self.store.add_message(chat["id"], "assistant", "Hello! How can I help you today?")
        resp = self.client.get(f"/api/chats/{chat['id']}/context")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["chat_id"], chat["id"])
        self.assertGreater(data["total_tokens"], 0)
        self.assertIn(data["status"], ["GOOD", "MODERATE", "HIGH", "CRITICAL"])
        self.assertEqual(data["message_count"], 2)

    def test_chat_compact(self):
        chat = self.client.post("/api/chats", json={"title": "Compact Test"}).json()
        for i in range(6):
            role = "user" if i % 2 == 0 else "assistant"
            self.store.add_message(chat["id"], role, f"Message turn {i} with some content to summarize")
        # Stub the summarizer: the real one calls an LLM, which made this test take minutes
        summary = {"role": "system", "content": "Summary of earlier turns"}
        summarizer = get_dispatcher().context_manager.summarizer
        with patch.object(summarizer, "summarize", new_callable=AsyncMock, return_value=summary) as summarize:
            resp = self.client.post(f"/api/chats/{chat['id']}/compact")
        summarize.assert_awaited_once()
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "compacted")
        self.assertEqual(data["message_count"], 5)  # 1 summary + 4 retained messages
        self.assertGreaterEqual(data["tokens_saved"], 0)
        self.assertEqual(data["summary"], "Summary of earlier turns")


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

    def test_picked_model_overrides_mode(self):
        chat = self.client.post("/api/chats", json={}).json()
        seen = {}

        async def fake_execute_task(**kwargs):
            seen.update(kwargs)
            return OLLAMA, "ok"

        with patch.object(get_dispatcher(), "execute_task", side_effect=fake_execute_task):
            with self.client.websocket_connect(WS_URL) as ws:
                ws.send_json({"type": "send", "chat_id": chat["id"], "content": "hi", "mode": "claude_code",
                              "provider": "ollama", "model": "qwen3:8b"})
                self._receive_until(ws, {"done", "error"})

        self.assertEqual(seen["provider_override"], "ollama")
        self.assertEqual(seen["model_override"], "qwen3:8b")
        self.assertIsNone(seen["harness_override"])
        self.assertIsNone(seen["policy"])

    def test_no_picked_model_keeps_routing(self):
        chat = self.client.post("/api/chats", json={}).json()
        seen = {}

        async def fake_execute_task(**kwargs):
            seen.update(kwargs)
            return OLLAMA, "ok"

        with patch.object(get_dispatcher(), "execute_task", side_effect=fake_execute_task):
            with self.client.websocket_connect(WS_URL) as ws:
                ws.send_json({"type": "send", "chat_id": chat["id"], "content": "hi", "mode": "direct", "model": "x"})
                self._receive_until(ws, {"done", "error"})

        self.assertIsNone(seen["provider_override"])
        self.assertIsNone(seen["model_override"])
        self.assertEqual(seen["policy"], "local")

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

    def test_project_and_artifact_lifecycle(self):
        # Create Project
        proj_res = self.client.post("/api/projects", json={
            "name": "PlaatoOS Test",
            "root_path": "C:/projects/plaatoos",
            "description": "B2B Outreach engine",
            "system_prompt": "Follow PolyForm Shield guidelines.",
        })
        self.assertEqual(proj_res.status_code, 201)
        proj = proj_res.json()
        proj_id = proj["id"]
        self.assertEqual(proj["name"], "PlaatoOS Test")
        self.assertEqual(proj["root_path"], "C:/projects/plaatoos")

        # Update Project
        patch_res = self.client.patch(f"/api/projects/{proj_id}", json={
            "description": "Updated outreach description",
        })
        self.assertEqual(patch_res.status_code, 200)
        self.assertEqual(patch_res.json()["description"], "Updated outreach description")

        # Create Chat scoped to Project
        chat_res = self.client.post("/api/chats", json={"title": "Scoped Task", "project_id": proj_id})
        self.assertEqual(chat_res.status_code, 201)
        chat = chat_res.json()
        self.assertEqual(chat["project_id"], proj_id)

        # Create Artifact
        art_res = self.client.post("/api/artifacts", json={
            "title": "Campaign Flowchart",
            "kind": "diagram",
            "content": "graph TD; A-->B;",
            "project_id": proj_id,
            "chat_id": chat["id"],
        })
        self.assertEqual(art_res.status_code, 201)
        art = art_res.json()
        self.assertEqual(art["project_id"], proj_id)
        self.assertEqual(art["kind"], "diagram")

        # List Artifacts by project
        list_res = self.client.get(f"/api/artifacts?project_id={proj_id}")
        self.assertEqual(len(list_res.json()), 1)

        # Cleanup
        self.assertEqual(self.client.delete(f"/api/artifacts/{art['id']}").status_code, 204)
        self.assertEqual(self.client.delete(f"/api/projects/{proj_id}").status_code, 204)

    def test_chat_scoped_to_project_sets_workspace_and_guidelines(self):
        proj = self.store.create_project(
            name="Workspace Proj",
            root_path="C:/workspace/test",
            system_prompt="Must execute autonomously.",
        )
        chat = self.client.post("/api/chats", json={"project_id": proj["id"]}).json()
        seen = {}

        async def fake_execute_task(**kwargs):
            seen.update(kwargs)
            return OLLAMA, "done"

        with patch.object(get_dispatcher(), "execute_task", side_effect=fake_execute_task):
            with self.client.websocket_connect(WS_URL) as ws:
                ws.send_json({"type": "send", "chat_id": chat["id"], "content": "analyze files"})
                self._receive_until(ws, {"done", "error"})

        self.assertEqual(seen["workspace"], "C:/workspace/test")
        self.assertTrue(any("Must execute autonomously." in m.get("content", "") for m in seen["messages"]))
        self.store.delete_project(proj["id"])

    def test_clear_chat_context_api_and_slash_commands(self):
        chat = self.client.post("/api/chats", json={"title": "Test Clear"}).json()
        chat_id = chat["id"]

        self.store.add_message(chat_id, "user", "Message 1")
        self.store.add_message(chat_id, "assistant", "Response 1")
        self.assertEqual(len(self.store.get_chat(chat_id)["messages"]), 2)

        # 1. Test POST /api/chats/{chat_id}/clear
        res = self.client.post(f"/api/chats/{chat_id}/clear")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "cleared")
        self.assertEqual(len(self.store.get_chat(chat_id)["messages"]), 0)

        # 2. Test websocket slash command /clear
        self.store.add_message(chat_id, "user", "Hello again")
        with self.client.websocket_connect(WS_URL) as ws:
            ws.send_json({"type": "send", "chat_id": chat_id, "content": "/clear"})
            events = self._receive_until(ws, {"done"})
            self.assertEqual(events[-1]["type"], "done")
            self.assertIn("Context Flushed", events[-1]["message"]["content"])
        self.assertEqual(len(self.store.get_chat(chat_id)["messages"]), 0)

        # 3. Test websocket slash command /compact
        for i in range(6):
            self.store.add_message(chat_id, "user" if i % 2 == 0 else "assistant", f"Turn message {i}")
        self.assertEqual(len(self.store.get_chat(chat_id)["messages"]), 6)

        summary = {"role": "system", "content": "Summarized conversation."}
        summarizer = get_dispatcher().context_manager.summarizer
        with patch.object(summarizer, "summarize", new_callable=AsyncMock, return_value=summary):
            with self.client.websocket_connect(WS_URL) as ws:
                ws.send_json({"type": "send", "chat_id": chat_id, "content": "/compact"})
                events = self._receive_until(ws, {"done"})
                self.assertEqual(events[-1]["type"], "done")
                self.assertIn("Context Compacted", events[-1]["message"]["content"])

        messages = self.store.get_chat(chat_id)["messages"]
        self.assertTrue(any("Summarized conversation." in m["content"] for m in messages))


if __name__ == "__main__":
    unittest.main()
