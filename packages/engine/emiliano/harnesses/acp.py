"""
Agent Client Protocol (ACP) client.
Runs an ACP agent (e.g. claude-agent-acp) as a subprocess and talks JSON-RPC 2.0 to it over
stdio, one JSON message per line. Emiliano is the client: it opens a session, sends one prompt,
streams the agent's updates and answers its permission requests.
Spec: https://agentclientprotocol.com
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")

from .. import __version__

PROTOCOL_VERSION = 1
METHOD_NOT_FOUND = -32601

# (tool_call, options) -> chosen optionId, or None to reject
PermissionHandler = Callable[[Dict[str, Any], List[Dict[str, Any]]], Optional[str]]


class AcpError(RuntimeError):
    """The agent returned a JSON-RPC error or broke the protocol."""


def allow_once_policy(tool_call: Dict[str, Any], options: List[Dict[str, Any]]) -> Optional[str]:
    """Approves each request once. Matches the pre-ACP behavior, where approvals were disabled."""
    for kind in ("allow_once", "allow_always"):
        for opt in options:
            if opt.get("kind") == kind:
                return opt.get("optionId")
    return None


def _pick_reject(options: List[Dict[str, Any]]) -> Optional[str]:
    for kind in ("reject_once", "reject_always"):
        for opt in options:
            if opt.get("kind") == kind:
                return opt.get("optionId")
    return None


class AcpSession:
    """One agent process, one session, one prompt turn."""

    def __init__(
        self,
        args: List[str],
        cwd: str,
        on_chunk: Optional[Callable[[str], None]] = None,
        permission_handler: Optional[PermissionHandler] = None,
        shell: bool = False,
    ):
        self.args = args
        self.cwd = os.path.abspath(cwd)
        self.on_chunk = on_chunk
        self.permission_handler = permission_handler or allow_once_policy
        self.shell = shell
        self.proc: Optional[subprocess.Popen] = None
        self.session_id: Optional[str] = None
        self._next_id = 0
        self._responses: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._write_lock = threading.Lock()
        self._text: List[str] = []
        self._stderr: List[str] = []

    # --- transport -------------------------------------------------------------------------

    def _send(self, message: Dict[str, Any]) -> None:
        message["jsonrpc"] = "2.0"
        line = json.dumps(message, ensure_ascii=False) + "\n"
        with self._write_lock:
            self.proc.stdin.write(line)
            self.proc.stdin.flush()

    def _request(self, method: str, params: Dict[str, Any], deadline: float) -> Dict[str, Any]:
        req_id = self._next_id
        self._next_id += 1
        self._send({"id": req_id, "method": method, "params": params})
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(method)
            try:
                msg = self._responses.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                if self.proc.poll() is not None and self._responses.empty():
                    raise AcpError(f"Agent exited during {method} (code {self.proc.returncode})")
                continue
            if msg.get("id") != req_id:
                continue
            if "error" in msg:
                err = msg["error"] or {}
                raise AcpError(f"{method} failed: {err.get('message', err)}")
            return msg.get("result") or {}

    def _read_stdout(self) -> None:
        for line in iter(self.proc.stdout.readline, ""):
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                logger.debug(f"[ACP] Ignoring non-JSON line: {line[:120]}")
                continue
            if not isinstance(msg, dict):
                continue
            if "method" in msg:
                try:
                    self._handle_agent_message(msg)
                except Exception as e:  # never let one bad message kill the reader
                    logger.warning(f"[ACP] Failed to handle {msg.get('method')}: {e}")
            elif "id" in msg:
                self._responses.put(msg)

    def _read_stderr(self) -> None:
        self._stderr.append(self.proc.stderr.read())

    # --- agent -> client -------------------------------------------------------------------

    def _handle_agent_message(self, msg: Dict[str, Any]) -> None:
        method = msg.get("method")
        params = msg.get("params") or {}
        if method == "session/update":
            self._handle_update(params.get("update") or {})
        elif method == "session/request_permission":
            self._send({"id": msg.get("id"), "result": {"outcome": self._decide_permission(params)}})
        elif "id" in msg:
            # fs/* and terminal/* are not advertised, so the agent should not call them
            self._send({"id": msg["id"], "error": {"code": METHOD_NOT_FOUND, "message": f"Unsupported method: {method}"}})

    def _decide_permission(self, params: Dict[str, Any]) -> Dict[str, Any]:
        tool_call = params.get("toolCall") or {}
        options = params.get("options") or []
        try:
            choice = self.permission_handler(tool_call, options)
        except Exception as e:
            logger.warning(f"[ACP] Permission handler failed, rejecting: {e}")
            choice = None
        if choice is None:
            choice = _pick_reject(options)
        valid = {opt.get("optionId") for opt in options}
        title = tool_call.get("title") or tool_call.get("toolCallId") or "tool call"
        if choice not in valid:
            logger.info(f"[ACP] Permission cancelled: {title}")
            return {"outcome": "cancelled"}
        logger.info(f"[ACP] Permission '{choice}' for: {title}")
        return {"outcome": "selected", "optionId": choice}

    def _handle_update(self, update: Dict[str, Any]) -> None:
        kind = update.get("sessionUpdate")
        if kind == "agent_message_chunk":
            content = update.get("content") or {}
            if content.get("type") == "text":
                text = content.get("text", "")
                self._text.append(text)
                self._emit(text)
        elif kind == "tool_call":
            title = update.get("title") or "tool"
            self._emit(f"\n  ⚡ [Tool: {update.get('kind', 'other')}] {title[:80]}\n")
        elif kind == "tool_call_update" and update.get("status") == "failed":
            self._emit(f"\n  ✗ [Tool failed] {update.get('toolCallId', '')}\n")

    def _emit(self, text: str) -> None:
        if self.on_chunk and text:
            self.on_chunk(text)

    # --- lifecycle -------------------------------------------------------------------------

    def run(self, prompt: str, timeout: float) -> Tuple[int, str, str]:
        """Runs one prompt turn. Returns (exit_code, agent_text, stderr) like BaseHarness.run_task."""
        deadline = time.monotonic() + timeout
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        self.proc = subprocess.Popen(
            self.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=self.cwd,
            shell=self.shell,
            bufsize=1,
            env=env,
        )
        readers = [threading.Thread(target=self._read_stdout, daemon=True), threading.Thread(target=self._read_stderr, daemon=True)]
        for r in readers:
            r.start()

        try:
            init = self._request("initialize", {
                "protocolVersion": PROTOCOL_VERSION,
                "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
                # version is required: OpenCode rejects initialize without it ("Invalid params")
                "clientInfo": {"name": "emiliano", "title": "Emiliano", "version": __version__},
            }, deadline)
            if init.get("protocolVersion") != PROTOCOL_VERSION:
                raise AcpError(f"Unsupported ACP protocol version {init.get('protocolVersion')}")

            self.session_id = self._request("session/new", {"cwd": self.cwd, "mcpServers": []}, deadline).get("sessionId")
            if not self.session_id:
                raise AcpError("session/new returned no sessionId")

            result = self._request("session/prompt", {
                "sessionId": self.session_id,
                "prompt": [{"type": "text", "text": prompt}],
            }, deadline)
            stop = result.get("stopReason", "end_turn")
            text = "".join(self._text)
            if stop in ("end_turn", "max_tokens", "max_turn_requests"):
                return 0, text, ""
            return 1, text, f"Agent stopped: {stop}"
        except TimeoutError:
            self._cancel()
            return 124, "".join(self._text), f"Task timed out after {timeout} seconds."
        except (AcpError, OSError) as e:
            # OSError: the agent exited and closed its stdin before we could write to it
            if isinstance(e, OSError):
                e = AcpError(f"Agent exited during startup: {e}")
            return 1, "".join(self._text), f"{e}\n{''.join(self._stderr)}".strip()
        finally:
            self._shutdown(readers)

    def _cancel(self) -> None:
        if self.session_id and self.proc and self.proc.poll() is None:
            try:
                self._send({"method": "session/cancel", "params": {"sessionId": self.session_id}})
            except OSError:
                pass

    def _shutdown(self, readers: List[threading.Thread]) -> None:
        if not self.proc:
            return
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)], capture_output=True, timeout=5)
            self.proc.kill()
        for r in readers:
            r.join(timeout=2)
