"""
Automated unit and integration tests for Emiliano's AI provider detection,
authentication, harness integration, and execution routing.
"""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from emiliano.core.capabilities import Capability, CapabilityStatus, ExecutionType
from emiliano.core.config import EmilianoConfig
from emiliano.core.dispatcher import ExecutionDispatcher, RoutingPolicy
from emiliano.core.registry import CapabilityRegistry
from emiliano.direct.client import UnifiedLLMClient
from emiliano.direct.credentials import CredentialManager, redact_key
from emiliano.direct.ollama import OllamaManager
from emiliano.harnesses.base import (
    AntigravityHarness,
    ClaudeCodeHarness,
    CodexHarness,
    OpenCodeHarness,
)


class TestOllamaDiscovery(unittest.TestCase):
    def test_select_best_model_installed(self):
        mgr = OllamaManager()
        installed = ["qwen3.5:2b", "nomic-embed-text:latest"]

        # Automatic selection picks qwen3.5:2b based on priority keywords
        selected = mgr.select_best_model(installed)
        self.assertEqual(selected, "qwen3.5:2b")

        # Specific request matching installed model
        self.assertEqual(mgr.select_best_model(installed, "qwen3.5"), "qwen3.5:2b")

    def test_select_best_model_empty(self):
        mgr = OllamaManager()
        self.assertIsNone(mgr.select_best_model([]))

    def test_parse_installed_models_success(self):
        mgr = OllamaManager()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "models": [
                {"name": "qwen3.5:2b"},
                {"name": "llama3:8b"},
            ]
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp
            models = asyncio.run(mgr.list_installed_models())
            self.assertEqual(models, ["qwen3.5:2b", "llama3:8b"])

    def test_unreachable_endpoint(self):
        mgr = OllamaManager(base_url="http://localhost:99999")
        with patch("httpx.AsyncClient.get", side_effect=Exception("Connection refused")):
            models = asyncio.run(mgr.list_installed_models())
            self.assertEqual(models, [])
            self.assertFalse(asyncio.run(mgr.is_service_ready()))

    def test_duplicate_instance_avoidance(self):
        mgr = OllamaManager(auto_start=True)
        # If service is already ready, ensure_service_running returns True without spawning process
        with patch.object(mgr, "is_service_ready", new_callable=AsyncMock, return_value=True):
            with patch("subprocess.Popen") as mock_popen:
                ready = asyncio.run(mgr.ensure_service_running())
                self.assertTrue(ready)
                mock_popen.assert_not_called()


class TestCredentialDetection(unittest.TestCase):
    def test_key_redaction(self):
        self.assertEqual(redact_key(None), "[not configured]")
        self.assertEqual(redact_key(""), "[not configured]")
        self.assertEqual(redact_key("short"), "[configured]")
        self.assertEqual(redact_key("sk-ant-api03-123456789xyz"), "sk-a...9xyz")

    def test_credential_detection_and_redaction(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test-key-12345", "OPENAI_API_KEY": ""}, clear=True):
            mgr = CredentialManager()
            anthropic_stat = mgr.check_provider("anthropic")
            self.assertTrue(anthropic_stat["configured"])
            self.assertIn("sk-a...2345", anthropic_stat["redacted_key"])
            self.assertNotIn("test-key", anthropic_stat["redacted_key"])  # Secret not exposed

            openai_stat = mgr.check_provider("openai")
            self.assertFalse(openai_stat["configured"])
            self.assertEqual(openai_stat["redacted_key"], "[not configured]")

    def test_no_keys_in_error_messages(self):
        secret = "sk-secret-password-never-leak"
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": secret}):
            client = UnifiedLLMClient()
            try:
                # Force failure to test exception content
                with patch("litellm.acompletion", side_effect=ValueError("Invalid model")):
                    asyncio.run(
                        client.stream_completion(
                            [{"role": "user", "content": "hi"}],
                            model_name="anthropic/claude-3-7-sonnet",
                        ).__anext__()
                    )
            except Exception as e:
                self.assertNotIn(secret, str(e))


class TestHarnessIntegration(unittest.TestCase):
    def test_harness_missing_versus_installed(self):
        claude = ClaudeCodeHarness()
        with patch("shutil.which", return_value=None):
            self.assertIsNone(claude.resolve_executable())
            usable, ver, err = claude.check_usability()
            self.assertFalse(usable)
            self.assertIn("not found", err)

        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="2.1.295\n", stderr="")
                usable, ver, err = claude.check_usability()
                self.assertTrue(usable)
                self.assertEqual(ver, "2.1.295")

    def test_safe_argument_passing_and_metacharacters(self):
        claude = ClaudeCodeHarness()
        codex = CodexHarness()
        opencode = OpenCodeHarness()
        agy = AntigravityHarness()

        # Complex prompt with quotes, semicolons, pipes, and backticks
        dangerous_prompt = 'echo "hello"; rm -rf / | cat `whoami` $VAR'

        cmd_claude = claude.build_task_command(dangerous_prompt)
        self.assertEqual(cmd_claude[-2:], ["-p", dangerous_prompt])

        cmd_codex = codex.build_task_command(dangerous_prompt)
        self.assertEqual(cmd_codex[-2:], ["exec", dangerous_prompt])

        cmd_opencode = opencode.build_task_command(dangerous_prompt)
        self.assertEqual(cmd_opencode[-2:], ["run", dangerous_prompt])

        cmd_agy = agy.build_task_command(dangerous_prompt)
        self.assertEqual(cmd_agy[-1], dangerous_prompt)

    def test_harness_task_execution_success_and_timeout(self):
        codex = CodexHarness()
        codex._resolved_path = "codex"

        with patch("subprocess.Popen") as mock_popen:
            # Success case
            proc = MagicMock()
            proc.stdout.readline.side_effect = ["Output line 1\n", ""]
            proc.stderr.read.return_value = ""
            proc.returncode = 0
            mock_popen.return_value = proc

            chunks = []
            code, out, err = codex.run_task("test prompt", on_chunk=lambda c: chunks.append(c))
            self.assertEqual(code, 0)
            self.assertEqual(out, "Output line 1\n")
            self.assertEqual(chunks, ["Output line 1\n"])

        with patch("subprocess.Popen") as mock_popen:
            # Timeout case
            import subprocess
            proc = MagicMock()
            proc.stdout.readline.side_effect = [""]
            proc.stderr.read.return_value = ""
            proc.wait.side_effect = subprocess.TimeoutExpired(cmd=["codex"], timeout=1)
            mock_popen.return_value = proc

            code, out, err = codex.run_task("test prompt", timeout=1)
            self.assertEqual(code, 124)
            self.assertIn("timed out", err)


class TestExecutionRoutingAndFallback(unittest.TestCase):
    def test_routing_local_policy(self):
        dispatcher = ExecutionDispatcher()

        mock_caps = {
            "ollama": Capability(
                name="ollama",
                display_name="Ollama (Local)",
                execution_type=ExecutionType.DIRECT_MODEL,
                status=CapabilityStatus.READY,
                available_models=["qwen3.5:2b"],
                selected_model="qwen3.5:2b",
            )
        }

        with patch.object(dispatcher.registry, "discover_all", new_callable=AsyncMock, return_value=mock_caps):
            routes = asyncio.run(dispatcher.route_task("Explain repo", policy="local"))
            self.assertEqual(len(routes), 1)
            self.assertEqual(routes[0].name, "ollama")
            self.assertEqual(routes[0].selected_model, "qwen3.5:2b")

    def test_routing_harness_policy(self):
        dispatcher = ExecutionDispatcher()

        mock_caps = {
            "codex": Capability(
                name="codex",
                display_name="Codex",
                execution_type=ExecutionType.AGENT_HARNESS,
                status=CapabilityStatus.READY,
            ),
            "ollama": Capability(
                name="ollama",
                display_name="Ollama (Local)",
                execution_type=ExecutionType.DIRECT_MODEL,
                status=CapabilityStatus.READY,
            ),
        }

        with patch.object(dispatcher.registry, "discover_all", new_callable=AsyncMock, return_value=mock_caps):
            routes = asyncio.run(dispatcher.route_task("Explain repo", policy="harness"))
            self.assertEqual(len(routes), 1)
            self.assertEqual(routes[0].name, "codex")

    def test_routing_auto_prefers_local_then_harness(self):
        dispatcher = ExecutionDispatcher()

        mock_caps = {
            "ollama": Capability(
                name="ollama",
                display_name="Ollama (Local)",
                execution_type=ExecutionType.DIRECT_MODEL,
                status=CapabilityStatus.READY,
                available_models=["qwen3.5:2b"],
                selected_model="qwen3.5:2b",
            ),
            "codex": Capability(
                name="codex",
                display_name="Codex",
                execution_type=ExecutionType.AGENT_HARNESS,
                status=CapabilityStatus.READY,
            ),
        }

        with patch.object(dispatcher.registry, "discover_all", new_callable=AsyncMock, return_value=mock_caps):
            routes = asyncio.run(dispatcher.route_task("Explain repo", policy="auto"))
            self.assertEqual(routes[0].name, "ollama")
            self.assertEqual(routes[1].name, "codex")

    def test_routing_explicit_harness_override(self):
        dispatcher = ExecutionDispatcher()

        mock_caps = {
            "codex": Capability(
                name="codex",
                display_name="Codex",
                execution_type=ExecutionType.AGENT_HARNESS,
                status=CapabilityStatus.READY,
            ),
            "claude_code": Capability(
                name="claude_code",
                display_name="Claude Code",
                execution_type=ExecutionType.AGENT_HARNESS,
                status=CapabilityStatus.READY,
            ),
        }

        with patch.object(dispatcher.registry, "discover_all", new_callable=AsyncMock, return_value=mock_caps):
            routes = asyncio.run(dispatcher.route_task("Explain repo", harness_override="claude"))
            self.assertEqual(len(routes), 1)
            self.assertEqual(routes[0].name, "claude_code")

    def test_regression_original_failure_skip_unconfigured_api(self):
        """
        Regression test reproducing the original issue:
        Ollama was queried for nonexistent 'qwen2.5-coder:32b',
        then tried deepseek and anthropic without API keys.
        The fix ensures:
        1. It selects installed 'qwen3.5:2b'
        2. It does NOT attempt deepseek or anthropic when keys are missing.
        """
        with patch.dict(os.environ, {}, clear=True):
            client = UnifiedLLMClient()
            with patch.object(client, "list_local_ollama_models", new_callable=AsyncMock, return_value=["qwen3.5:2b"]):
                candidates = asyncio.run(client.get_viable_candidates())
                # Should find ollama/qwen3.5:2b, and NOT include deepseek or anthropic
                models = [c[0] for c in candidates]
                self.assertIn("ollama/qwen3.5:2b", models)
                self.assertNotIn("deepseek/deepseek-chat", models)
                self.assertNotIn("anthropic/claude-3-7-sonnet-20250219", models)


if __name__ == "__main__":
    unittest.main()
