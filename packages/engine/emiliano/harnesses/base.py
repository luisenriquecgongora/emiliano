"""
Harness Adapters for external CLI agents.
Defines BaseHarness and implementations for Claude Code, Antigravity, OpenCode, and Codex.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Optional
from loguru import logger
from .pty_mgr import SubprocessPTYSession


class BaseHarness(ABC):
    def __init__(self, name: str, command: str):
        self.name = name
        self.command = command
        self.session: Optional[SubprocessPTYSession] = None

    @abstractmethod
    def start_task(
        self,
        prompt: str,
        cwd: Optional[str] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> bool:
        pass

    def send_input(self, text: str) -> None:
        if self.session:
            self.session.write(text + "\n")

    def stop(self) -> None:
        if self.session:
            self.session.terminate()
            self.session = None


class ClaudeCodeHarness(BaseHarness):
    def __init__(self, command: str = "claude"):
        super().__init__(name="claude_code", command=command)

    def start_task(
        self,
        prompt: str,
        cwd: Optional[str] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> bool:
        cmd = f'{self.command} -p "{prompt}"'
        self.session = SubprocessPTYSession(command=cmd, cwd=cwd, on_output=on_chunk)
        return self.session.start()


class AntigravityHarness(BaseHarness):
    def __init__(self, command: str = "agy"):
        super().__init__(name="antigravity", command=command)

    def start_task(
        self,
        prompt: str,
        cwd: Optional[str] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> bool:
        cmd = f'{self.command} "{prompt}"'
        self.session = SubprocessPTYSession(command=cmd, cwd=cwd, on_output=on_chunk)
        return self.session.start()


class OpenCodeHarness(BaseHarness):
    def __init__(self, command: str = "opencode"):
        super().__init__(name="opencode", command=command)

    def start_task(
        self,
        prompt: str,
        cwd: Optional[str] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> bool:
        cmd = f'{self.command} --prompt "{prompt}"'
        self.session = SubprocessPTYSession(command=cmd, cwd=cwd, on_output=on_chunk)
        return self.session.start()


class CodexHarness(BaseHarness):
    def __init__(self, command: str = "codex"):
        super().__init__(name="codex", command=command)

    def start_task(
        self,
        prompt: str,
        cwd: Optional[str] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> bool:
        cmd = f'{self.command} "{prompt}"'
        self.session = SubprocessPTYSession(command=cmd, cwd=cwd, on_output=on_chunk)
        return self.session.start()
