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
from emiliano.core.dispatcher import ExecutionDispatcher
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
        self.assertEqual(cmd_agy[-2:], ["-p", dangerous_prompt])

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

    def test_harness_stream_json_tool_and_text_streaming(self):
        agy = AntigravityHarness()
        agy._resolved_path = "agy"

        sample_lines = [
            '{"event":"step_update","step_update":{"step_type":"tool","state":"ACTIVE","tool_name":"run_command","tool_info":{"parameters":{"CommandLine":"Get-ChildItem"}}}}\n',
            '{"event":"step_update","step_update":{"step_type":"agent_response","text_delta":"Found 22 files"}}\n',
            '{"event":"result","result":{"status":"SUCCESS","response":"Found 22 files"}}\n',
            "",
        ]

        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.stdout.readline.side_effect = sample_lines
            proc.stderr.read.return_value = ""
            proc.returncode = 0
            mock_popen.return_value = proc

            chunks = []
            code, out, err = agy.run_task("check files", on_chunk=lambda c: chunks.append(c))
            self.assertEqual(code, 0)
            self.assertEqual(out, "Found 22 files")
            self.assertTrue(any("Tool:" in c and "run_command" in c for c in chunks))
            self.assertTrue(any("Get-ChildItem" in c for c in chunks))
            self.assertIn("Found 22 files", chunks)


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


class _FakeStream:
    """Async iterator mimicking a LiteLLM streaming response."""

    def __init__(self, deltas):
        self._chunks = [MagicMock(choices=[MagicMock(delta=d)]) for d in deltas]

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


def _delta(content=None, reasoning=None):
    d = MagicMock()
    d.content = content
    d.reasoning_content = reasoning
    return d


async def _collect(agen):
    return [c async for c in agen]


class TestRoutingRegressions(unittest.TestCase):
    def test_remote_model_not_rerouted_to_ollama(self):
        client = UnifiedLLMClient()
        with patch.object(client, "list_local_ollama_models", new_callable=AsyncMock, return_value=["qwen3.5:2b"]):
            candidates = asyncio.run(client.get_viable_candidates("claude-sonnet-5-5"))
            self.assertEqual(candidates, [("claude-sonnet-5-5", None)])
            # A bare name that really is installed still resolves locally
            candidates = asyncio.run(client.get_viable_candidates("qwen3.5"))
            self.assertEqual(candidates, [("ollama/qwen3.5:2b", client.ollama_base_url)])

    def test_dispatcher_qualifies_model_with_provider(self):
        def cap(name, model):
            return Capability(name=name, display_name=name, execution_type=ExecutionType.DIRECT_MODEL, selected_model=model)

        self.assertEqual(ExecutionDispatcher._litellm_model_id(cap("anthropic", "claude-sonnet-5-5")), "anthropic/claude-sonnet-5-5")
        self.assertEqual(ExecutionDispatcher._litellm_model_id(cap("ollama", "qwen3.5:2b")), "ollama/qwen3.5:2b")
        self.assertEqual(ExecutionDispatcher._litellm_model_id(cap("ollama", "hf.co/org/model")), "ollama/hf.co/org/model")
        self.assertEqual(ExecutionDispatcher._litellm_model_id(cap("openai", "openai/gpt-5")), "openai/gpt-5")

    def test_harness_override_aliases(self):
        dispatcher = ExecutionDispatcher()
        mock_caps = {
            "antigravity": Capability(
                name="antigravity",
                display_name="Antigravity (AGY)",
                execution_type=ExecutionType.AGENT_HARNESS,
                status=CapabilityStatus.READY,
            )
        }
        with patch.object(dispatcher.registry, "discover_all", new_callable=AsyncMock, return_value=mock_caps):
            routes = asyncio.run(dispatcher.route_task("x", harness_override="agy"))
            self.assertEqual(routes[0].name, "antigravity")

    def test_config_keys_used_without_touching_environ(self):
        cfg = EmilianoConfig()
        cfg.models.anthropic_api_key = "sk-from-config-file-123"
        with patch.dict(os.environ, {}, clear=True):
            client = UnifiedLLMClient(config=cfg)
            stream = _FakeStream([_delta(content="hello")])
            with patch("litellm.acompletion", new_callable=AsyncMock, return_value=stream) as mock_acompletion:
                out = asyncio.run(_collect(client.stream_completion([{"role": "user", "content": "hi"}], model_name="anthropic/claude-sonnet-5-5")))
            self.assertEqual(out, ["hello"])
            self.assertEqual(mock_acompletion.call_args.kwargs["api_key"], "sk-from-config-file-123")
            self.assertNotIn("ANTHROPIC_API_KEY", os.environ)

    def test_reasoning_only_response_is_a_failure(self):
        client = UnifiedLLMClient()
        stream = _FakeStream([_delta(reasoning="Thinking..."), _delta(reasoning="still thinking")])
        with patch("litellm.acompletion", new_callable=AsyncMock, return_value=stream):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(_collect(client.stream_completion([{"role": "user", "content": "hi"}], model_name="ollama/qwen3.5:2b")))
        self.assertIn("empty response", str(ctx.exception))
        self.assertIn("reasoning", str(ctx.exception))

    def test_empty_harness_output_is_a_failure(self):
        dispatcher = ExecutionDispatcher()
        codex_cap = Capability(name="codex", display_name="Codex", execution_type=ExecutionType.AGENT_HARNESS, status=CapabilityStatus.READY)
        with patch.object(dispatcher, "route_task", new_callable=AsyncMock, return_value=[codex_cap]):
            with patch.object(CodexHarness, "run_task", return_value=(0, "", "")):
                with self.assertRaises(RuntimeError) as ctx:
                    asyncio.run(dispatcher.execute_task("x"))
        self.assertIn("no output", str(ctx.exception))


class TestHarnessPromptSafety(unittest.TestCase):
    PROMPT = 'fix it" & calc & "'

    def test_prompt_sent_via_stdin_not_argv(self):
        for harness in (ClaudeCodeHarness(), CodexHarness()):
            harness._resolved_path = "C:\\fake\\tool.cmd"
            with patch.object(harness, "resolve_executable", return_value="C:\\fake\\tool.cmd"):
                inv = harness.build_invocation(self.PROMPT)
            self.assertEqual(inv.stdin_text, self.PROMPT)
            self.assertFalse(any(self.PROMPT in a for a in inv.args))

    def test_opencode_prompt_sent_via_temp_file_and_cleaned_up(self):
        oc = OpenCodeHarness()
        with patch.object(oc, "resolve_executable", return_value="opencode"):
            inv = oc.build_invocation(self.PROMPT)
        try:
            self.assertFalse(any(self.PROMPT in a for a in inv.args))
            path = inv.args[inv.args.index("-f") + 1]
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), self.PROMPT)
        finally:
            for p in inv.temp_files:
                os.remove(p)

        # run_task removes the temp file afterwards
        with patch.object(oc, "resolve_executable", return_value="opencode"):
            with patch("subprocess.Popen") as mock_popen:
                proc = MagicMock()
                proc.stdout.readline.side_effect = ["done\n", ""]
                proc.stderr.read.return_value = ""
                proc.returncode = 0
                mock_popen.return_value = proc
                oc.run_task(self.PROMPT)
                used_path = mock_popen.call_args.args[0][-1]
        self.assertFalse(os.path.exists(used_path))

    def test_cmd_shim_refuses_metacharacters_on_argv(self):
        agy = AntigravityHarness()  # passes the prompt as an argument
        with patch("sys.platform", "win32"), patch.object(agy, "resolve_executable", return_value="C:\\fake\\agy.cmd"):
            with patch("subprocess.Popen") as mock_popen:
                code, _, err = agy.run_task(self.PROMPT)
        self.assertEqual(code, 1)
        self.assertIn("cmd.exe", err)
        mock_popen.assert_not_called()

    def test_run_task_writes_prompt_to_stdin(self):
        claude = ClaudeCodeHarness()
        with patch.object(claude, "resolve_executable", return_value="claude"):
            with patch("subprocess.Popen") as mock_popen:
                proc = MagicMock()
                proc.stdout.readline.side_effect = ["ok\n", ""]
                proc.stderr.read.return_value = ""
                proc.returncode = 0
                mock_popen.return_value = proc
                code, out, _ = claude.run_task(self.PROMPT)
        self.assertEqual((code, out), (0, "ok\n"))
        proc.stdin.write.assert_called_once_with(self.PROMPT)
        self.assertEqual(mock_popen.call_args.args[0], ["claude", "-p"])

    def test_run_task_keyboard_interrupt_kills_process(self):
        claude = ClaudeCodeHarness()
        with patch.object(claude, "resolve_executable", return_value="claude"):
            with patch("subprocess.Popen") as mock_popen:
                proc = MagicMock()
                proc.pid = 12345
                proc.wait.side_effect = KeyboardInterrupt("Interrupted")
                mock_popen.return_value = proc
                with patch.object(claude, "_kill_process_tree") as mock_kill:
                    with self.assertRaises(KeyboardInterrupt):
                        claude.run_task("do work")
                    mock_kill.assert_called_once_with(proc)

    def test_chat_command_help_and_exit(self):
        from click.testing import CliRunner
        from emiliano.cli import chat

        runner = CliRunner()
        # Verify --help works
        help_result = runner.invoke(chat, ["--help"])
        self.assertEqual(help_result.exit_code, 0)
        self.assertIn("interactive terminal coworking session", help_result.output)

        # Verify /help and exit in interactive session
        chat_result = runner.invoke(chat, input="/help\nexit\n")
        self.assertEqual(chat_result.exit_code, 0)
        self.assertIn("Available Slash Commands", chat_result.output)
        self.assertIn("Exiting Emiliano. Goodbye!", chat_result.output)

    def test_requires_agent_harness_classification(self):
        dispatcher = ExecutionDispatcher()
        # Coding / filesystem tasks
        self.assertTrue(dispatcher.requires_agent_harness("can u chekc our files on this folder and check whether will compile and what is missing?"))
        self.assertTrue(dispatcher.requires_agent_harness("inspect files in this directory"))
        self.assertTrue(dispatcher.requires_agent_harness("will this compile?"))
        self.assertTrue(dispatcher.requires_agent_harness("run tests with pytest"))
        self.assertTrue(dispatcher.requires_agent_harness("check our files"))

        # General conceptual / conversational tasks
        self.assertFalse(dispatcher.requires_agent_harness("hi"))
        self.assertFalse(dispatcher.requires_agent_harness("what is backpropagation?"))
        self.assertFalse(dispatcher.requires_agent_harness("write a python function to compute fibonacci"))

    def test_auto_routing_prioritizes_harness_for_filesystem_tasks(self):
        dispatcher = ExecutionDispatcher()
        mock_caps = {
            "ollama": Capability(
                name="ollama",
                display_name="Ollama (Local)",
                execution_type=ExecutionType.DIRECT_MODEL,
                status=CapabilityStatus.READY,
                selected_model="qwen3.5:2b",
                priority=10,
            ),
            "codex": Capability(
                name="codex",
                display_name="Codex",
                execution_type=ExecutionType.AGENT_HARNESS,
                status=CapabilityStatus.READY,
                priority=16,
            ),
        }
        with patch.object(dispatcher.registry, "discover_all", new_callable=AsyncMock, return_value=mock_caps):
            # 1. Filesystem task routes to agent harness first
            routes_coding = asyncio.run(dispatcher.route_task("check our files in this folder and compile", policy="auto"))
            self.assertEqual(routes_coding[0].name, "codex")
            self.assertEqual(routes_coding[1].name, "ollama")

            # 2. Conceptual task routes to local Ollama first
            routes_conceptual = asyncio.run(dispatcher.route_task("Explain repo", policy="auto"))
            self.assertEqual(routes_conceptual[0].name, "ollama")
            self.assertEqual(routes_conceptual[1].name, "codex")


if __name__ == "__main__":
    unittest.main()
