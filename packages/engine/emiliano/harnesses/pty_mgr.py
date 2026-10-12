"""
Virtual Pseudo-Terminal (PTY) Manager.
Enables programmatic interaction with interactive CLI agents (Claude Code, Antigravity, OpenCode, Codex).
Uses pywinpty on Windows and ptyprocess on Unix/Linux/macOS.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Callable, Optional
from loguru import logger

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    try:
        from winpty import PtyProcess
    except ImportError:
        PtyProcess = None
else:
    try:
        from ptyprocess import PtyProcess
    except ImportError:
        PtyProcess = None


class SubprocessPTYSession:
    def __init__(
        self,
        command: str,
        cwd: Optional[str] = None,
        on_output: Optional[Callable[[str], None]] = None,
    ):
        self.command = command
        self.cwd = cwd or os.getcwd()
        self.on_output = on_output
        self.proc: Optional[PtyProcess] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> bool:
        if PtyProcess is None:
            logger.error("[PTY] PtyProcess is not available on this platform. Please install pywinpty (Windows) or ptyprocess (Unix).")
            return False

        try:
            logger.info(f"[PTY] Spawning: {self.command} in {self.cwd}")
            self.proc = PtyProcess.spawn(self.command, cwd=self.cwd)
            self._running = True
            self._reader_thread = threading.Thread(
                target=self._read_loop, name=f"PTYReader-{self.command[:10]}", daemon=True
            )
            self._reader_thread.start()
            return True
        except Exception as e:
            logger.exception(f"[PTY] Failed to spawn {self.command}: {e}")
            return False

    def write(self, data: str) -> None:
        """Sends keystrokes or commands to the interactive CLI process."""
        if self.proc and self._running:
            try:
                self.proc.write(data)
            except Exception as e:
                logger.error(f"[PTY] Error writing to process: {e}")

    def terminate(self) -> None:
        self._running = False
        if self.proc:
            try:
                self.proc.terminate(force=True)
            except Exception:
                pass
            self.proc = None

    def _read_loop(self) -> None:
        while self._running and self.proc and self.proc.isalive():
            try:
                output = self.proc.read(1024)
                if output and self.on_output:
                    self.on_output(output)
            except EOFError:
                break
            except Exception as e:
                logger.debug(f"[PTY] Read loop exception: {e}")
                break
        self._running = False
        logger.info(f"[PTY] Process {self.command} terminated.")
