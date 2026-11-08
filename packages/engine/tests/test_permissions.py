"""
Tests for agent permission requests: the chat socket relays them to the dock and returns the
user's answer, the dispatcher passes the handler to harnesses, and the fallback-flag setting.
"""

import asyncio
import unittest
from unittest.mock import patch

from emiliano.core.capabilities import Capability, CapabilityStatus, ExecutionType
from emiliano.core.config import EmilianoConfig
from emiliano.core.registry import CapabilityRegistry
from emiliano.harnesses.base import AntigravityHarness, CodexHarness, OpenCodeHarness
from emiliano.history import api as history_api
from emiliano.server.app import get_dispatcher

from test_history import WS_URL, HistoryTestCase

CLAUDE = Capability(name="claude_code", display_name="Claude Code", execution_type=ExecutionType.AGENT_HARNESS,
                    status=CapabilityStatus.READY)
OPTIONS = [
    {"optionId": "yes", "name": "Allow once", "kind": "allow_once"},
    {"optionId": "no", "name": "Reject", "kind": "reject_once"},
]
TOOL_CALL = {"toolCallId": "call_1", "title": "Edit main.py", "kind": "edit"}


class TestPermissionRelay(HistoryTestCase):
    def _run(self, answer_with):
        """Starts a reply whose agent asks one permission; answer_with(ws, request) answers it."""
        chat = self.client.post("/api/chats", json={}).json()

        async def fake_execute_task(**kwargs):
            # Harnesses call the handler from a worker thread, as run_task does
            choice = await asyncio.to_thread(kwargs["on_permission"], TOOL_CALL, OPTIONS)
            return CLAUDE, f"choice={choice}"

        with patch.object(get_dispatcher(), "execute_task", side_effect=fake_execute_task):
            with self.client.websocket_connect(WS_URL) as ws:
                ws.send_json({"type": "send", "chat_id": chat["id"], "content": "edit it", "mode": "claude_code"})
                events = []
                while True:
                    event = ws.receive_json()
                    events.append(event)
                    if event["type"] == "permission_request":
                        answer_with(ws, event)
                    if event["type"] in ("done", "error", "cancelled"):
                        return events

    def test_request_is_relayed_and_answer_returned(self):
        events = self._run(lambda ws, req: ws.send_json(
            {"type": "permission_response", "request_id": req["request_id"], "option_id": "yes"}))
        request = next(e for e in events if e["type"] == "permission_request")
        self.assertEqual(request["title"], "Edit main.py")
        self.assertEqual(request["kind"], "edit")
        self.assertEqual([o["optionId"] for o in request["options"]], ["yes", "no"])
        self.assertEqual(events[-1]["message"]["content"], "choice=yes")

    def test_null_answer_rejects(self):
        events = self._run(lambda ws, req: ws.send_json(
            {"type": "permission_response", "request_id": req["request_id"], "option_id": None}))
        self.assertEqual(events[-1]["message"]["content"], "choice=None")

    def test_unknown_request_id_is_ignored(self):
        def answer(ws, req):
            ws.send_json({"type": "permission_response", "request_id": "perm-999", "option_id": "yes"})
            ws.send_json({"type": "permission_response", "request_id": req["request_id"], "option_id": "no"})

        self.assertEqual(self._run(answer)[-1]["message"]["content"], "choice=no")

    def test_unanswered_request_times_out_as_reject(self):
        with patch.object(history_api, "PERMISSION_TIMEOUT_S", 0.2):
            events = self._run(lambda ws, req: None)
        self.assertIn("permission_closed", [e["type"] for e in events])
        self.assertEqual(events[-1]["message"]["content"], "choice=None")


class TestDispatcherPassesHandler(unittest.TestCase):
    def test_handler_reaches_run_task(self):
        dispatcher = get_dispatcher()
        harness = CodexHarness()
        seen = {}

        def fake_run_task(**kwargs):
            seen.update(kwargs)
            return 0, "done", ""

        handler = lambda tool_call, options: "yes"  # noqa: E731
        cap = Capability(name="codex", display_name="Codex", execution_type=ExecutionType.AGENT_HARNESS,
                         status=CapabilityStatus.READY)
        with patch.object(dispatcher, "route_task", return_value=[cap]), \
             patch.object(dispatcher.registry, "get_harness_instances", return_value={"codex": harness}), \
             patch.object(harness, "run_task", side_effect=fake_run_task):
            asyncio.run(dispatcher.execute_task(goal="fix the bug", on_permission=handler))
        # The dispatcher wraps the handler to record decisions in the task trace; answers still come from it
        self.assertEqual(seen["permission_handler"]({"title": "Edit"}, [{"optionId": "yes"}]), "yes")


class TestHarnessSettings(unittest.TestCase):
    def test_acp_commands_from_config(self):
        config = EmilianoConfig()
        config.harnesses.opencode_acp_cmd = "opencode acp"
        harnesses = CapabilityRegistry(config).get_harness_instances()
        self.assertEqual(harnesses["claude_code"].acp_command, "claude-agent-acp")
        self.assertEqual(harnesses["codex"].acp_command, "codex-acp")
        self.assertEqual(harnesses["opencode"].acp_command, "opencode acp")
        self.assertIsNone(harnesses["antigravity"].acp_command)

    def test_opencode_acp_passes_subcommand(self):
        harness = OpenCodeHarness(acp_command="opencode acp")
        with patch.object(OpenCodeHarness, "resolve_acp_executable", return_value="/bin/opencode"), \
             patch("emiliano.harnesses.base.AcpSession") as session_cls:
            session_cls.return_value.run.return_value = (0, "ok", "")
            harness.run_task("task", cwd=".", timeout=5)
        self.assertEqual(session_cls.call_args.kwargs["args"], ["/bin/opencode", "acp"])

    def test_fallback_flags_on_by_default(self):
        harnesses = CapabilityRegistry(EmilianoConfig()).get_harness_instances()
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", harnesses["codex"].build_invocation("x").args)
        self.assertIn("--dangerously-skip-permissions", harnesses["antigravity"].build_task_command("x"))

    def test_fallback_flags_can_be_turned_off(self):
        config = EmilianoConfig()
        config.harnesses.unattended_fallback = False
        harnesses = CapabilityRegistry(config).get_harness_instances()
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", harnesses["codex"].build_invocation("x").args)
        self.assertNotIn("--dangerously-skip-permissions", harnesses["antigravity"].build_task_command("x"))
        self.assertIsInstance(harnesses["antigravity"], AntigravityHarness)


if __name__ == "__main__":
    unittest.main()
