"""
Tests for the ACP client against a fake ACP agent (tests/fake_acp_agent.py).
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from emiliano.harnesses.acp import AcpSession, allow_once_policy
from emiliano.harnesses.base import ClaudeCodeHarness

FAKE_AGENT = str(Path(__file__).with_name("fake_acp_agent.py"))
AGENT_ARGS = [sys.executable, FAKE_AGENT]


class TestAcpSession(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.tmp.name, "log.jsonl")
        self.env = patch.dict(os.environ, {"FAKE_ACP_LOG": self.log})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def _received(self):
        with open(self.log, encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def test_streams_text_and_returns_it(self):
        chunks = []
        code, out, err = AcpSession(AGENT_ARGS, cwd=self.tmp.name, on_chunk=chunks.append).run("hi", timeout=20)
        self.assertEqual((code, out, err), (0, "Hello world", ""))
        self.assertEqual(chunks, ["Hello ", "world"])

    def test_handshake_and_prompt_off_argv(self):
        AcpSession(AGENT_ARGS, cwd=self.tmp.name).run("secret prompt", timeout=20)
        methods = [m.get("method") for m in self._received() if "method" in m]
        self.assertEqual(methods, ["initialize", "session/new", "session/prompt"])
        init, new = self._received()[0]["params"], self._received()[1]["params"]
        self.assertEqual(init["protocolVersion"], 1)
        self.assertFalse(init["clientCapabilities"]["terminal"])
        self.assertTrue(init["clientInfo"]["version"])
        self.assertTrue(os.path.isabs(new["cwd"]))
        self.assertNotIn("secret prompt", " ".join(AGENT_ARGS))

    def test_default_policy_allows_once(self):
        code, out, _ = AcpSession(AGENT_ARGS, cwd=self.tmp.name).run("edit", timeout=20)
        self.assertEqual(code, 0)
        self.assertEqual(out, "outcome=selected:yes")

    def test_handler_rejection_selects_reject_option(self):
        session = AcpSession(AGENT_ARGS, cwd=self.tmp.name, permission_handler=lambda tc, opts: None)
        _, out, _ = session.run("edit", timeout=20)
        self.assertEqual(out, "outcome=selected:no")

    def test_handler_receives_tool_call(self):
        seen = []

        def handler(tool_call, options):
            seen.append(tool_call["title"])
            return "yes"

        AcpSession(AGENT_ARGS, cwd=self.tmp.name, permission_handler=handler).run("edit", timeout=20)
        self.assertEqual(seen, ["Edit main.py"])

    def test_failing_handler_rejects(self):
        def handler(tool_call, options):
            raise ValueError("boom")

        _, out, _ = AcpSession(AGENT_ARGS, cwd=self.tmp.name, permission_handler=handler).run("edit", timeout=20)
        self.assertEqual(out, "outcome=selected:no")

    def test_timeout_sends_cancel(self):
        code, _, err = AcpSession(AGENT_ARGS, cwd=self.tmp.name).run("hang", timeout=3)
        self.assertEqual(code, 124)
        self.assertIn("timed out", err)
        self.assertIn("session/cancel", [m.get("method") for m in self._received()])

    def test_missing_agent_reports_failure(self):
        code, _, err = AcpSession([sys.executable, "-c", "pass"], cwd=self.tmp.name).run("hi", timeout=10)
        self.assertEqual(code, 1)
        self.assertIn("exited during", err)

    def test_session_persistence_across_multiple_prompts(self):
        session = AcpSession(AGENT_ARGS, cwd=self.tmp.name)
        self.assertFalse(session.is_alive())

        # Turn 1
        code1, out1, _ = session.prompt("hi", timeout=20)
        self.assertEqual(code1, 0)
        self.assertEqual(out1, "Hello world")
        self.assertTrue(session.is_alive())

        # Turn 2 on the same running process and session
        code2, out2, _ = session.prompt("hi", timeout=20)
        self.assertEqual(code2, 0)
        self.assertEqual(out2, "Hello world")
        self.assertTrue(session.is_alive())

        session.close()
        self.assertFalse(session.is_alive())

        # Verify handshake occurred once, but prompt occurred twice
        methods = [m.get("method") for m in self._received() if "method" in m]
        self.assertEqual(methods, ["initialize", "session/new", "session/prompt", "session/prompt"])

    def test_fs_capabilities_write_and_read(self):
        session = AcpSession(AGENT_ARGS, cwd=self.tmp.name, enable_fs=True)
        code, out, _ = session.run("fs_test", timeout=20)
        self.assertEqual(code, 0)
        self.assertEqual(out, "read=persisted-data")

        target_file = os.path.join(self.tmp.name, "test.txt")
        self.assertTrue(os.path.isfile(target_file))
        with open(target_file, encoding="utf-8") as f:
            self.assertEqual(f.read(), "persisted-data")
        self.assertIn(os.path.abspath(target_file), session.written_files)

    def test_mcp_servers_forwarded(self):
        servers = [{"name": "db", "command": "uvx", "args": ["mcp-server-sqlite"]}]
        session = AcpSession(AGENT_ARGS, cwd=self.tmp.name, mcp_servers=servers)
        session.run("hi", timeout=20)
        new_params = self._received()[1]["params"]
        self.assertEqual(new_params["mcpServers"], servers)


class TestAllowOncePolicy(unittest.TestCase):
    def test_prefers_allow_once(self):
        opts = [{"optionId": "a", "kind": "allow_always"}, {"optionId": "b", "kind": "allow_once"}]
        self.assertEqual(allow_once_policy({}, opts), "b")

    def test_none_without_allow_option(self):
        self.assertIsNone(allow_once_policy({}, [{"optionId": "r", "kind": "reject_once"}]))


class TestClaudeCodeAcpSelection(unittest.TestCase):
    def test_uses_acp_when_adapter_installed(self):
        harness = ClaudeCodeHarness(acp_command="fake-acp")
        with patch.object(ClaudeCodeHarness, "resolve_acp_executable", return_value="fake-acp"), \
             patch("emiliano.harnesses.base.AcpSession") as session_cls:
            session_cls.return_value.run.return_value = (0, "ok", "")
            self.assertEqual(harness.run_task("task", cwd=".", timeout=5), (0, "ok", ""))
        self.assertEqual(session_cls.call_args.kwargs["args"], ["fake-acp"])

    def test_falls_back_without_adapter(self):
        harness = ClaudeCodeHarness(acp_command=None)
        self.assertIsNone(harness.resolve_acp_executable())
        with patch("emiliano.harnesses.base.AcpSession") as session_cls, \
             patch.object(ClaudeCodeHarness, "resolve_executable", return_value=None):
            code, _, err = harness.run_task("task", timeout=5)
        session_cls.assert_not_called()
        self.assertEqual(code, 1)
        self.assertIn("not found", err)

    def test_harness_reuses_active_session(self):
        harness = ClaudeCodeHarness(acp_command="fake-acp")
        mock_session = MagicMock()
        mock_session.is_alive.return_value = True
        mock_session.cwd = os.path.abspath(".")
        mock_session.run.return_value = (0, "ok", "")

        with patch.object(ClaudeCodeHarness, "resolve_acp_executable", return_value="fake-acp"), \
             patch("emiliano.harnesses.base.AcpSession", return_value=mock_session) as session_cls:
            # Turn 1
            code1, out1, _ = harness.run_task("turn 1", cwd=".")
            self.assertEqual(code1, 0)
            self.assertEqual(session_cls.call_count, 1)

            # Turn 2
            code2, out2, _ = harness.run_task("turn 2", cwd=".")
            self.assertEqual(code2, 0)
            # Reused session, so constructor not called again
            self.assertEqual(session_cls.call_count, 1)
            self.assertEqual(mock_session.run.call_count, 2)

            harness.close()
            mock_session.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
