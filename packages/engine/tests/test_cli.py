"""
Tests for Emiliano CLI components, including SlashCommandCompleter.
"""

import unittest
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from emiliano.cli import SlashCommandCompleter, cli
from emiliano.core.capabilities import Capability, ExecutionType
from emiliano.core.dispatcher import ExecutionDispatcher


class TestSlashCommandCompleter(unittest.TestCase):
    def setUp(self):
        self.completer = SlashCommandCompleter()

    def _get_completions(self, text_before_cursor: str):
        doc = MagicMock()
        doc.text_before_cursor = text_before_cursor
        return list(self.completer.get_completions(doc, complete_event=None))

    def test_root_slash_yields_all_commands(self):
        completions = self._get_completions("/")
        texts = [c.text for c in completions]
        self.assertIn("/switch", texts)
        self.assertIn("/policy", texts)
        self.assertIn("/model", texts)
        self.assertIn("/doctor", texts)
        self.assertIn("/models", texts)
        self.assertIn("/harnesses", texts)
        self.assertIn("/clear", texts)
        self.assertIn("/history", texts)
        self.assertIn("/help", texts)
        self.assertIn("/exit", texts)
        self.assertEqual(len(completions), len(SlashCommandCompleter.COMMANDS))

    def test_prefix_slash_command(self):
        completions = self._get_completions("/sw")
        texts = [c.text for c in completions]
        self.assertEqual(texts, ["/switch"])

    def test_switch_subarguments(self):
        completions = self._get_completions("/switch ")
        texts = [c.text for c in completions]
        self.assertIn("agy", texts)
        self.assertIn("claude", texts)
        self.assertIn("codex", texts)
        self.assertIn("ollama", texts)
        self.assertIn("auto", texts)

        # Prefix filtering for /switch
        filtered = self._get_completions("/switch cl")
        self.assertEqual([c.text for c in filtered], ["claude"])

    def test_policy_subarguments(self):
        completions = self._get_completions("/policy ")
        texts = [c.text for c in completions]
        self.assertIn("auto", texts)
        self.assertIn("local", texts)
        self.assertIn("harness", texts)
        self.assertIn("api", texts)

        # Prefix filtering for /policy
        filtered = self._get_completions("/policy lo")
        self.assertEqual([c.text for c in filtered], ["local"])

    def test_normal_text_does_not_trigger_completions(self):
        completions = self._get_completions("write a python script to parse logs")
        self.assertEqual(completions, [])


class TestRunCommand(unittest.TestCase):
    def test_run_executes_goal_through_dispatcher(self):
        cap = Capability(name="ollama", display_name="Ollama (Local)", execution_type=ExecutionType.DIRECT_MODEL)

        async def fake_execute_task(**kwargs):
            kwargs["on_route_selected"](cap)
            kwargs["on_chunk"]("pong")
            return cap, "pong"

        with patch.object(ExecutionDispatcher, "__init__", return_value=None), \
                patch.object(ExecutionDispatcher, "execute_task", side_effect=fake_execute_task) as mock_exec:
            result = CliRunner().invoke(cli, ["run", "say pong", "--provider", "ollama"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("pong", result.output)
        self.assertEqual(mock_exec.call_args.kwargs["goal"], "say pong")


if __name__ == "__main__":
    unittest.main()
