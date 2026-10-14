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
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")

from .pty_mgr import SubprocessPTYSession


class BaseHarness(ABC):
    def __init__(self, name: str, command: str, display_name: str = ""):
        self.name = name
        self.command = command
        self.display_name = display_name or name
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

    def run_task(
        self,
        prompt: str,
        cwd: Optional[str] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
        timeout: float = 180.0,
    ) -> Tuple[int, str, str]:
        """
        Executes a task non-interactively, capturing stdout/stderr and streaming chunks safely.
        """
        exe = self.resolve_executable()
        if not exe:
            return 1, "", f"Harness executable '{self.command}' not found."

        cmd_args = self.build_task_command(prompt)
        use_shell = sys.platform == "win32" and exe.lower().endswith((".cmd", ".bat"))

        logger.info(f"[Harness] Running {self.name}: {cmd_args[:2]}...")
        stdout_chunks: List[str] = []
        stderr_chunks: List[str] = []

        try:
            proc = subprocess.Popen(
                cmd_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                cwd=cwd or os.getcwd(),
                shell=use_shell,
                bufsize=1,
            )

            # Read stdout line by line
            if proc.stdout:
                for line in iter(proc.stdout.readline, ""):
                    stdout_chunks.append(line)
                    if on_chunk:
                        on_chunk(line)
                proc.stdout.close()

            stderr_out = proc.stderr.read() if proc.stderr else ""
            if stderr_out:
                stderr_chunks.append(stderr_out)
            if proc.stderr:
                proc.stderr.close()

            proc.wait(timeout=timeout)
            return proc.returncode or 0, "".join(stdout_chunks), "".join(stderr_chunks)

        except subprocess.TimeoutExpired:
            if proc:
                proc.kill()
            return 124, "".join(stdout_chunks), f"Task timed out after {timeout} seconds."
        except Exception as e:
            return 1, "".join(stdout_chunks), str(e)

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
    def __init__(self, command: str = "claude"):
        super().__init__(name="claude_code", command=command, display_name="Claude Code")

    def check_authentication(self) -> Tuple[bool, str]:
        # 1. Direct API key
        if os.environ.get("ANTHROPIC_API_KEY"):
            return True, "API Key configured via ANTHROPIC_API_KEY"

        # 2. Claude Code account in ~/.claude.json
        claude_json = Path.home() / ".claude.json"
        if claude_json.exists():
            try:
                data = json.loads(claude_json.read_text(encoding="utf-8"))
                if data.get("oauthAccount") or data.get("sessionKey") or data.get("primaryApiKey"):
                    return True, "OAuth / Session authenticated via ~/.claude.json"
            except Exception:
                pass

        # 3. Claude profile directory
        if (Path.home() / ".claude").is_dir():
            return True, "Profile directory exists (~/.claude)"

        return False, "Not authenticated (run 'claude login' or set ANTHROPIC_API_KEY)"

    def build_task_command(self, prompt: str) -> List[str]:
        exe = self.resolve_executable() or self.command
        # Claude Code non-interactive print mode
        return [exe, "-p", prompt]


class CodexHarness(BaseHarness):
    def __init__(self, command: str = "codex"):
        super().__init__(name="codex", command=command, display_name="Codex")

    def check_authentication(self) -> Tuple[bool, str]:
        # 1. API key in env
        if os.environ.get("CODEX_API_KEY") or os.environ.get("OPENAI_API_KEY"):
            return True, "API Key configured via environment"

        # 2. Stored auth in ~/.codex/auth.json
        auth_file = Path.home() / ".codex" / "auth.json"
        if auth_file.exists():
            try:
                data = json.loads(auth_file.read_text(encoding="utf-8"))
                if data.get("tokens") or data.get("api_key") or data.get("auth_mode"):
                    return True, "Authenticated via ~/.codex/auth.json"
            except Exception:
                pass

        # 3. Check ~/.codex config
        if (Path.home() / ".codex").is_dir():
            return True, "Codex home configured (~/.codex)"

        return False, "Not authenticated (run 'codex login')"

    def build_task_command(self, prompt: str) -> List[str]:
        exe = self.resolve_executable() or self.command
        # Codex non-interactive exec mode
        return [exe, "exec", prompt]


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
        return [exe, prompt]


class OpenCodeHarness(BaseHarness):
    def __init__(self, command: str = "opencode"):
        super().__init__(name="opencode", command=command, display_name="OpenCode")

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
