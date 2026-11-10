"""
Harness Adapters for external CLI agents.
Defines BaseHarness and implementations for Claude Code, Antigravity, OpenCode, and Codex.
Provides executable resolution, non-destructive usability checks, authentication detection,
and safe execution without shell injection.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple
import click

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")

from .acp import AcpSession, PermissionHandler
from .pty_mgr import SubprocessPTYSession

# Characters cmd.exe interprets even inside list2cmdline quoting. npm-installed CLIs are
# .cmd shims on Windows, so any argument containing these could inject shell commands.
CMD_METACHARS = frozenset('"&|<>^%!\r\n')


@dataclass
class HarnessInvocation:
    """How to launch a task: command-line args, optional prompt on stdin, and temp files to clean up."""
    args: List[str]
    stdin_text: Optional[str] = None
    temp_files: List[str] = field(default_factory=list)


def _read_json(path: Path) -> dict:
    """Reads a JSON object from path; returns {} if it is missing, unreadable or not an object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


class BaseHarness(ABC):
    def __init__(self, name: str, command: str, display_name: str = "", acp_command: Optional[str] = None):
        self.name = name
        self.command = command
        self.display_name = display_name or name
        # ACP agent command line ("binary [args]"); when the binary resolves, run_task talks ACP
        self.acp_command = acp_command
        self.permission_handler: Optional[PermissionHandler] = None
        # Fallback (non-ACP) runs pass the CLI's skip-approval flag, since nobody can answer prompts
        self.unattended = True
        # The task run_task is executing, so cancel() can stop it from another thread
        self._active_proc: Optional[subprocess.Popen] = None
        self._active_acp: Optional[AcpSession] = None
        self._cancel_requested = threading.Event()
        self.session: Optional[SubprocessPTYSession] = None
        self._resolved_path: Optional[str] = None

    def resolve_executable(self) -> Optional[str]:
        """Resolves the executable on PATH or platform-specific installation paths."""
        found = shutil.which(self.command)
        if found:
            self._resolved_path = found
            return found

        # Platform-specific fallbacks
        candidates: List[Path] = []
        if sys.platform == "win32":
            local_appdata = os.environ.get("LOCALAPPDATA", "")
            appdata = os.environ.get("APPDATA", "")
            if local_appdata:
                candidates.extend([
                    Path(local_appdata) / "Programs" / self.command / f"{self.command}.exe",
                    Path(local_appdata) / self.command / "bin" / f"{self.command}.exe",
                ])
            if appdata:
                candidates.extend([
                    Path(appdata) / "npm" / f"{self.command}.cmd",
                    Path(appdata) / "npm" / f"{self.command}.exe",
                ])
        else:
            candidates.extend([
                Path(f"/usr/local/bin/{self.command}"),
                Path(f"/usr/bin/{self.command}"),
                Path.home() / ".local" / "bin" / self.command,
            ])

        for c in candidates:
            if c.is_file():
                self._resolved_path = str(c)
                return str(c)

        return None

    def resolve_acp_executable(self) -> Optional[str]:
        """Resolves the ACP agent binary on PATH, or None when this harness has none."""
        if not self.acp_command or not self.acp_command.split():
            return None
        binary = self.acp_command.split()[0]
        found = shutil.which(binary)
        if found:
            return found
        if sys.platform == "win32" and os.environ.get("APPDATA"):
            shim = Path(os.environ["APPDATA"]) / "npm" / f"{binary}.cmd"
            if shim.is_file():
                return str(shim)
        return None

    def check_usability(self, timeout: float = 10.0) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Runs a non-destructive command (e.g. --version) to verify the tool is functional.
        Returns: (is_usable, version_string, error_message)
        """
        exe = self.resolve_executable()
        if not exe:
            return False, None, f"Executable '{self.command}' not found on PATH"

        version_cmd = self.get_version_command()
        try:
            # On Windows, executing .cmd/.bat requires shell=True
            use_shell = sys.platform == "win32" and exe.lower().endswith((".cmd", ".bat"))
            res = subprocess.run(
                version_cmd,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=timeout,
                shell=use_shell,
            )
            if res.returncode == 0:
                out = res.stdout.strip() or res.stderr.strip()
                # Return first line of version output
                ver = out.splitlines()[0] if out else "installed"
                return True, ver, None
            else:
                err = res.stderr.strip() or res.stdout.strip() or f"Exit code {res.returncode}"
                return False, None, err
        except subprocess.TimeoutExpired:
            return False, None, f"Command timed out after {timeout}s"
        except Exception as e:
            return False, None, str(e)

    def get_version_command(self) -> List[str]:
        exe = self.resolve_executable() or self.command
        return [exe, "--version"]

    @abstractmethod
    def check_authentication(self) -> Tuple[bool, str]:
        """
        Inspects whether the harness has valid credentials/auth configured.
        Returns: (is_authenticated, status_description)
        """
        pass

    @abstractmethod
    def build_task_command(self, prompt: str) -> List[str]:
        """Builds safe command-line arguments for task execution."""
        pass

    def build_invocation(self, prompt: str) -> HarnessInvocation:
        """
        Builds the invocation used by run_task. Harnesses that can read the prompt from
        stdin or a file override this so the prompt never appears on the command line.
        """
        return HarnessInvocation(args=self.build_task_command(prompt))

    def run_task(
        self,
        prompt: str,
        cwd: Optional[str] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
        timeout: float = 180.0,
        permission_handler: Optional[PermissionHandler] = None,
    ) -> Tuple[int, str, str]:
        """
        Executes a task non-interactively, capturing stdout/stderr and streaming chunks safely.
        Both pipes are drained on background threads so the timeout is always enforced.
        Uses ACP when the harness's ACP agent is installed, so tool calls and permission
        requests arrive as structured messages.
        """
        self._cancel_requested.clear()
        acp_exe = self.resolve_acp_executable()
        if acp_exe:
            logger.info(f"[Harness] Running {self.name} over ACP: {acp_exe}")
            target_cwd = os.path.abspath(cwd or os.getcwd())
            session = self._active_acp
            if session is None or not session.is_alive() or session.cwd != target_cwd:
                if session is not None:
                    session.close()
                session = AcpSession(
                    args=[acp_exe, *self.acp_command.split()[1:]],
                    cwd=target_cwd,
                    on_chunk=on_chunk,
                    permission_handler=permission_handler or self.permission_handler,
                    shell=sys.platform == "win32" and acp_exe.lower().endswith((".cmd", ".bat")),
                    enable_fs=True,
                    keep_alive=True,
                )
                self._active_acp = session
            else:
                session.on_chunk = on_chunk
                session.permission_handler = permission_handler or self.permission_handler

            try:
                return session.run(prompt, timeout=timeout)
            except Exception:
                if self._active_acp:
                    self._active_acp.close()
                    self._active_acp = None
                raise

        exe = self.resolve_executable()
        if not exe:
            return 1, "", f"Harness executable '{self.command}' not found."

        inv = self.build_invocation(prompt)
        use_shell = sys.platform == "win32" and exe.lower().endswith((".cmd", ".bat"))

        stdout_chunks: List[str] = []
        stderr_chunks: List[str] = []
        proc: Optional[subprocess.Popen] = None

        try:
            if use_shell and any(ch in CMD_METACHARS for arg in inv.args[1:] for ch in arg):
                return 1, "", (
                    f"Refusing to run {self.display_name}: it is a .cmd script on Windows and the prompt "
                    "would pass through cmd.exe, which interprets characters like \" & | < > ^ % !. "
                    "Remove those characters or use a different harness."
                )

            env = dict(os.environ)
            env["FORCE_COLOR"] = "1"
            env["COLORTERM"] = "truecolor"
            env["PYTHONUNBUFFERED"] = "1"

            logger.info(f"[Harness] Running {self.name}: {inv.args[:2]}...")
            proc = subprocess.Popen(
                inv.args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE if inv.stdin_text is not None else subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=cwd or os.getcwd(),
                shell=use_shell,
                bufsize=1,
                env=env,
            )
            self._active_proc = proc
            if self._cancel_requested.is_set():  # cancel() ran before the process existed
                self._kill_process_tree(proc)

            final_response: List[str] = []
            agent_text_parts: List[str] = []

            def _pump_stdout() -> None:
                for line in iter(proc.stdout.readline, ""):
                    stripped = line.strip()
                    if stripped.startswith('{"') and ('"event"' in stripped or '"step_update"' in stripped):
                        try:
                            data = json.loads(stripped)
                            if data.get("event") == "step_update":
                                step = data.get("step_update", {})
                                stype = step.get("step_type")
                                state = step.get("state")
                                if stype == "tool" and state == "ACTIVE":
                                    tname = step.get("tool_name") or step.get("tool_info", {}).get("name", "tool")
                                    params = step.get("tool_info", {}).get("parameters", {})
                                    target = params.get("CommandLine") or params.get("AbsolutePath") or params.get("path") or params.get("query") or ""
                                    summary = f" {target[:80]}" if target else ""
                                    badge = (
                                        click.style("\n  ⚡ [Tool: ", fg="yellow", bold=True)
                                        + click.style(tname, fg="cyan", bold=True)
                                        + click.style(f"]{summary}\n", fg="bright_black")
                                    )
                                    if on_chunk:
                                        on_chunk(badge)
                                elif stype == "agent_response":
                                    delta = step.get("text_delta", "")
                                    if delta:
                                        agent_text_parts.append(delta)
                                        if on_chunk:
                                            on_chunk(delta)
                                continue
                            elif data.get("event") in ("init", "user_input", "ping"):
                                # Internal protocol metadata events - swallow cleanly
                                continue
                            elif data.get("event") == "result":
                                res = data.get("result", {})
                                resp = res.get("response", "")
                                if resp:
                                    final_response.append(resp)
                                continue
                        except Exception:
                            pass

                    stdout_chunks.append(line)
                    if on_chunk:
                        on_chunk(line)

            def _pump_stderr() -> None:
                stderr_chunks.append(proc.stderr.read())

            def _feed_stdin() -> None:
                try:
                    proc.stdin.write(inv.stdin_text)
                    proc.stdin.close()
                except OSError:
                    pass  # Process exited before reading its input; its exit code reports why

            workers = [threading.Thread(target=_pump_stdout, daemon=True), threading.Thread(target=_pump_stderr, daemon=True)]
            if inv.stdin_text is not None:
                workers.append(threading.Thread(target=_feed_stdin, daemon=True))
            for w in workers:
                w.start()

            proc.wait(timeout=timeout)
            for w in workers:
                w.join(timeout=5)
            if self._cancel_requested.is_set():
                return 130, "".join(stdout_chunks), "Task stopped by user."
            full_output = "".join(final_response) if final_response else ("".join(agent_text_parts) if agent_text_parts else "".join(stdout_chunks))
            return proc.returncode, full_output, "".join(stderr_chunks)

        except subprocess.TimeoutExpired:
            self._kill_process_tree(proc)
            return 124, "".join(stdout_chunks), f"Task timed out after {timeout} seconds."
        except (KeyboardInterrupt, SystemExit):
            if proc:
                self._kill_process_tree(proc)
            raise
        except Exception as e:
            if proc:
                self._kill_process_tree(proc)
            return 1, "".join(stdout_chunks), str(e)
        finally:
            self._active_proc = None
            for path in inv.temp_files:
                try:
                    os.remove(path)
                except OSError:
                    pass

    def cancel(self) -> None:
        """Stops the task run_task is executing. Safe to call from any thread, and when nothing runs."""
        self._cancel_requested.set()
        session = self._active_acp
        if session:
            session.cancel()
        proc = self._active_proc
        if proc and proc.poll() is None:
            logger.info(f"[Harness] Stopping {self.name} (pid {proc.pid})")
            self._kill_process_tree(proc)

    def close(self) -> None:
        """Shuts down any running persistent ACP session."""
        if self._active_acp is not None:
            self._active_acp.close()
            self._active_acp = None

    def __del__(self) -> None:
        self.close()

    @staticmethod
    def _kill_process_tree(proc: Optional[subprocess.Popen]) -> None:
        """Kills the process and its children (on Windows, killing cmd.exe alone leaves node running)."""
        if not proc:
            return
        if sys.platform == "win32" and isinstance(proc.pid, int):
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=5)
            except Exception:
                pass
        try:
            proc.kill()
        except OSError:
            pass

    def start_task(
        self,
        prompt: str,
        cwd: Optional[str] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """Legacy / PTY session launcher for interactive CLI agents."""
        cmd_args = self.build_task_command(prompt)
        # Quote command safely for winpty
        cmd_str = subprocess.list2cmdline(cmd_args)
        self.session = SubprocessPTYSession(command=cmd_str, cwd=cwd, on_output=on_chunk)
        return self.session.start()

    def send_input(self, text: str) -> None:
        if self.session:
            self.session.write(text + "\n")

    def stop(self) -> None:
        if self.session:
            self.session.terminate()
            self.session = None


class ClaudeCodeHarness(BaseHarness):
    def __init__(self, command: str = "claude", acp_command: Optional[str] = "claude-agent-acp"):
        super().__init__(name="claude_code", command=command, display_name="Claude Code", acp_command=acp_command)

    def check_authentication(self) -> Tuple[bool, str]:
        # 1. API key or long-lived OAuth token (from `claude setup-token`)
        if os.environ.get("ANTHROPIC_API_KEY"):
            return True, "API Key configured via ANTHROPIC_API_KEY"
        if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
            return True, "OAuth token configured via CLAUDE_CODE_OAUTH_TOKEN"

        # 2. Logged-in account recorded in ~/.claude.json
        data = _read_json(Path.home() / ".claude.json")
        if data.get("oauthAccount") or data.get("primaryApiKey"):
            return True, "Logged in (account in ~/.claude.json)"

        # 3. Stored OAuth credentials (Windows/Linux; macOS keeps them in the Keychain)
        config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
        if _read_json(config_dir / ".credentials.json").get("claudeAiOauth"):
            return True, f"Logged in (credentials in {config_dir})"

        # A bare ~/.claude folder only means Claude Code was launched once, not that it is logged in
        return False, "Not authenticated (run 'claude' and log in, or set ANTHROPIC_API_KEY)"

    def build_task_command(self, prompt: str) -> List[str]:
        exe = self.resolve_executable() or self.command
        # Claude Code non-interactive print mode
        return [exe, "-p", prompt]

    def build_invocation(self, prompt: str) -> HarnessInvocation:
        # `claude -p` reads the prompt from stdin when no prompt argument is given
        exe = self.resolve_executable() or self.command
        return HarnessInvocation(args=[exe, "-p"], stdin_text=prompt)


class CodexHarness(BaseHarness):
    def __init__(self, command: str = "codex", acp_command: Optional[str] = "codex-acp"):
        super().__init__(name="codex", command=command, display_name="Codex", acp_command=acp_command)

    def check_authentication(self) -> Tuple[bool, str]:
        # 1. API key in env
        if os.environ.get("CODEX_API_KEY") or os.environ.get("OPENAI_API_KEY"):
            return True, "API Key configured via environment"

        # 2. Stored ChatGPT login or API key in $CODEX_HOME/auth.json (default ~/.codex)
        codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        data = _read_json(codex_home / "auth.json")
        if data.get("tokens") or data.get("OPENAI_API_KEY") or data.get("api_key"):
            return True, f"Logged in (credentials in {codex_home / 'auth.json'})"

        # A bare ~/.codex folder only means Codex was launched once, not that it is logged in
        return False, "Not authenticated (run 'codex login')"

    def build_task_command(self, prompt: str) -> List[str]:
        exe = self.resolve_executable() or self.command
        # Codex non-interactive exec mode
        return [exe, "exec", prompt]

    def build_invocation(self, prompt: str) -> HarnessInvocation:
        # `codex exec -` reads the prompt from stdin
        exe = self.resolve_executable() or self.command
        skip = ["--dangerously-bypass-approvals-and-sandbox"] if self.unattended else []
        return HarnessInvocation(
            args=[exe, "exec", "--color", "always", *skip, "-"],
            stdin_text=prompt
        )


class AntigravityHarness(BaseHarness):
    def __init__(self, command: str = "agy"):
        super().__init__(name="antigravity", command=command, display_name="Antigravity (AGY)")

    def check_authentication(self) -> Tuple[bool, str]:
        # 1. Settings file in ~/.gemini/antigravity-cli/settings.json
        settings = Path.home() / ".gemini" / "antigravity-cli" / "settings.json"
        if settings.exists():
            return True, "Configured via ~/.gemini/antigravity-cli/settings.json"

        # 2. General Google / Vertex creds
        if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            return True, "Credentials found in environment"

        return False, "Not authenticated (run 'agy' to login)"

    def build_task_command(self, prompt: str) -> List[str]:
        exe = self.resolve_executable() or self.command
        skip = ["--dangerously-skip-permissions"] if self.unattended else []
        return [exe, *skip, "--output-format", "stream-json", "-p", prompt]


class OpenCodeHarness(BaseHarness):
    def __init__(self, command: str = "opencode", acp_command: Optional[str] = None):
        super().__init__(name="opencode", command=command, display_name="OpenCode", acp_command=acp_command)

    def get_version_command(self) -> List[str]:
        exe = self.resolve_executable() or self.command
        return [exe, "-v"]

    def check_authentication(self) -> Tuple[bool, str]:
        auth_file = Path.home() / ".local" / "share" / "opencode" / "auth.json"
        if auth_file.exists():
            try:
                data = json.loads(auth_file.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data:
                    return True, "Credentials configured in ~/.local/share/opencode/auth.json"
            except Exception:
                pass

        # Provider API keys that opencode supports
        if any(os.environ.get(k) for k in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY"]):
            return True, "AI Provider key configured in environment"

        return False, "Not authenticated (run 'opencode auth login')"

    def build_task_command(self, prompt: str) -> List[str]:
        exe = self.resolve_executable() or self.command
        # opencode run <prompt>
        return [exe, "run", prompt]

    def build_invocation(self, prompt: str) -> HarnessInvocation:
        # `opencode run` has no stdin mode, so pass the prompt as an attached file.
        # The message goes before -f because -f is an array option and would swallow it.
        exe = self.resolve_executable() or self.command
        fd, path = tempfile.mkstemp(prefix="emiliano-prompt-", suffix=".md")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(prompt)
        return HarnessInvocation(
            args=[exe, "run", "Follow the instructions in the attached file.", "-f", path],
            temp_files=[path],
        )
