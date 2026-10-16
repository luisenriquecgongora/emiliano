"""
Tests for Emiliano CLI components, including SlashCommandCompleter.
"""

import unittest
from unittest.mock import MagicMock
from emiliano.cli import SlashCommandCompleter


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


if __name__ == "__main__":
    unittest.main()
