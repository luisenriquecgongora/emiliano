"""Terminal model picking: /models report lines, /model numbered choices, and parsing what was typed."""

import unittest
from unittest.mock import MagicMock

from emiliano.cli import SlashCommandCompleter
from emiliano.cli_models import format_local_report, model_choices, resolve_pick, split_command
from emiliano.core.capabilities import Capability, CapabilityStatus, ExecutionType

GB = 1024 ** 3
REPORT = {
    "hardware": {"gpuName": "GTX 1650", "vramBytes": 4 * GB, "ramBytes": 16 * GB},
    "models": [
        {"name": "qwen3:8b", "sizeBytes": 5 * GB, "tools": True, "fit": "slow", "recommended": False,
         "loaded": False, "vramBytes": 0},
        {"name": "qwen3.5:2b", "sizeBytes": int(2.6 * GB), "tools": True, "fit": "fits_gpu", "recommended": True,
         "loaded": True, "vramBytes": 2 * GB},
    ],
    "suggestions": [{"name": "qwen3:4b", "sizeGb": 2.5, "fit": "fits_gpu", "note": "small", "pull": "ollama pull qwen3:4b"}],
}
CAPS = {
    "ollama": Capability(name="ollama", display_name="Ollama (Local)", execution_type=ExecutionType.DIRECT_MODEL,
                         status=CapabilityStatus.READY, available_models=["qwen3:8b", "qwen3.5:2b"]),
    "anthropic": Capability(name="anthropic", display_name="Anthropic (Claude)",
                            execution_type=ExecutionType.DIRECT_MODEL, status=CapabilityStatus.READY,
                            available_models=["claude-opus-5-5"]),
    "openai": Capability(name="openai", display_name="OpenAI (GPT)", execution_type=ExecutionType.DIRECT_MODEL,
                         status=CapabilityStatus.UNAUTHENTICATED, available_models=["gpt-4o"]),
    "claude_code": Capability(name="claude_code", display_name="Claude Code",
                              execution_type=ExecutionType.AGENT_HARNESS, status=CapabilityStatus.READY),
}


class TestCliModels(unittest.TestCase):
    def test_models_is_not_model(self):
        # "/models" used to match the "/model" handler and only print its usage line
        self.assertEqual(split_command("/models"), ("/models", ""))
        self.assertEqual(split_command("/model  qwen3:4b "), ("/model", "qwen3:4b"))
        self.assertEqual(split_command(""), ("", ""))

    def test_report_lines(self):
        text = "\n".join(format_local_report(REPORT))
        self.assertIn("GTX 1650, 4.0 GB VRAM", text)
        self.assertIn("✅ qwen3.5:2b", text)
        self.assertIn("★ recommended", text)
        self.assertIn("in memory", text)
        self.assertIn("⚠️ qwen3:8b", text)
        self.assertIn("ollama pull qwen3:4b", text)

    def test_choices_put_recommended_first_and_skip_unready(self):
        choices = model_choices(CAPS, REPORT)
        self.assertEqual([(c["provider"], c["model"]) for c in choices],
                         [("ollama", "qwen3.5:2b"), ("ollama", "qwen3:8b"), ("anthropic", "claude-opus-5-5")])

    def test_choices_without_report_use_installed_names(self):
        self.assertEqual([c["model"] for c in model_choices(CAPS, None)][:2], ["qwen3:8b", "qwen3.5:2b"])

    def test_resolve_pick(self):
        choices = model_choices(CAPS, REPORT)
        self.assertEqual(resolve_pick(choices, "1")["model"], "qwen3.5:2b")
        self.assertEqual(resolve_pick(choices, "QWEN3:8B")["model"], "qwen3:8b")
        self.assertEqual(resolve_pick(choices, "anthropic/claude-opus-5-5")["provider"], "anthropic")
        self.assertIsNone(resolve_pick(choices, "0"))
        self.assertIsNone(resolve_pick(choices, "9"))
        self.assertIsNone(resolve_pick(choices, "llama3"))

    def test_completer_offers_model_names(self):
        completer = SlashCommandCompleter()
        completer.model_names = ["qwen3.5:2b", "llama3.1:8b"]
        for typed in ("/model q", "/load q", "/unload q"):
            doc = MagicMock()
            doc.text_before_cursor = typed
            with self.subTest(typed=typed):
                self.assertEqual([c.text for c in completer.get_completions(doc)], ["qwen3.5:2b"])


if __name__ == "__main__":
    unittest.main()
