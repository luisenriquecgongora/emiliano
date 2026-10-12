import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from emiliano.core.config import EmilianoConfig
from emiliano.core.single_instance import SingleInstanceGuard
from emiliano.harnesses.base import ClaudeCodeHarness, AntigravityHarness, OpenCodeHarness, CodexHarness


class TestEmilianoCore(unittest.TestCase):
    def test_single_instance_guard(self):
        port = 51899  # Isolated test port
        guard1 = SingleInstanceGuard(port=port)
        guard2 = SingleInstanceGuard(port=port)

        self.assertTrue(guard1.acquire())
        self.assertFalse(guard2.acquire())

        guard1.release()
        self.assertTrue(guard2.acquire())
        guard2.release()

    def test_config_defaults(self):
        cfg = EmilianoConfig()
        self.assertEqual(cfg.models.default_provider, "ollama")
        self.assertEqual(len(cfg.models.fallback_chain), 3)
        self.assertEqual(cfg.harnesses.claude_code_cmd, "claude")
        self.assertEqual(cfg.harnesses.antigravity_cmd, "agy")

    def test_harness_adapters_instantiation(self):
        claude = ClaudeCodeHarness(command="claude")
        self.assertEqual(claude.name, "claude_code")
        self.assertEqual(claude.command, "claude")

        agy = AntigravityHarness(command="agy")
        self.assertEqual(agy.name, "antigravity")
        self.assertEqual(agy.command, "agy")

        opencode = OpenCodeHarness(command="opencode")
        self.assertEqual(opencode.name, "opencode")

        codex = CodexHarness(command="codex")
        self.assertEqual(codex.name, "codex")


if __name__ == "__main__":
    unittest.main()
