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
# After session/cancel the agent gets this long to stop on its own before it is killed
CANCEL_GRACE_S = 3.0

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
    """One agent process, supporting session persistence across prompt turns."""

    def __init__(
        self,
        args: List[str],
        cwd: str,
        on_chunk: Optional[Callable[[str], None]] = None,
        permission_handler: Optional[PermissionHandler] = None,
        shell: bool = False,
        enable_fs: bool = False,
        mcp_servers: Optional[List[Dict[str, Any]]] = None,
        keep_alive: bool = False,
    ):
        self.args = args
        self.cwd = os.path.abspath(cwd)
        self.on_chunk = on_chunk
        self.permission_handler = permission_handler or allow_once_policy
        self.shell = shell
        self.enable_fs = enable_fs
        self.mcp_servers = mcp_servers or []
        self.keep_alive = keep_alive
        self.written_files: set[str] = set()
        self.proc: Optional[subprocess.Popen] = None
        self.session_id: Optional[str] = None
        self._next_id = 0
        self._responses: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._write_lock = threading.Lock()
        self._text: List[str] = []
        self._stderr: List[str] = []
        self._readers: List[threading.Thread] = []
        self._cancelled = threading.Event()

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
        elif method == "fs/read_text_file" and self.enable_fs:
            self._handle_read_file(msg.get("id"), params)
        elif method == "fs/write_text_file" and self.enable_fs:
            self._handle_write_file(msg.get("id"), params)
        elif "id" in msg:
            # fs/* and terminal/* are rejected with METHOD_NOT_FOUND when unadvertised
            self._send({"id": msg["id"], "error": {"code": METHOD_NOT_FOUND, "message": f"Unsupported method: {method}"}})

    def _handle_read_file(self, req_id: Any, params: Dict[str, Any]) -> None:
        path = params.get("path", "")
        full_path = os.path.abspath(path if os.path.isabs(path) else os.path.join(self.cwd, path))
        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            self._send({"id": req_id, "result": {"content": content}})
        except Exception as e:
            logger.warning(f"[ACP] Failed to read '{path}': {e}")
            self._send({"id": req_id, "error": {"code": -32001, "message": f"Read failed: {e}"}})

    def _handle_write_file(self, req_id: Any, params: Dict[str, Any]) -> None:
        path = params.get("path", "")
        content = params.get("content", "")
        full_path = os.path.abspath(path if os.path.isabs(path) else os.path.join(self.cwd, path))
        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            self.written_files.add(full_path)
            self._emit(f"\n  📝 [File written: {os.path.basename(path)}]\n")
            self._send({"id": req_id, "result": {}})
        except Exception as e:
            logger.warning(f"[ACP] Failed to write '{path}': {e}")
            self._send({"id": req_id, "error": {"code": -32002, "message": f"Write failed: {e}"}})

    def _decide_permission(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if self._cancelled.is_set():
            return {"outcome": "cancelled"}  # the spec's answer for requests during cancellation
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
        if self._cancelled.is_set() or choice not in valid:
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

    def is_alive(self) -> bool:
        """Returns True if the subprocess is running and has an active session."""
        return self.proc is not None and self.proc.poll() is None and self.session_id is not None

    def start(self, timeout: float = 30.0) -> None:
        """Spawns the agent process and performs initialize + session/new handshake."""
        if self.is_alive():
            return
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
        self._readers = [
            threading.Thread(target=self._read_stdout, daemon=True),
            threading.Thread(target=self._read_stderr, daemon=True),
        ]
        for r in self._readers:
            r.start()

        init = self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "clientCapabilities": {
                "fs": {"readTextFile": self.enable_fs, "writeTextFile": self.enable_fs},
                "terminal": False,
            },
            # version is required: OpenCode rejects initialize without it ("Invalid params")
            "clientInfo": {"name": "emiliano", "title": "Emiliano", "version": __version__},
        }, deadline)
        if init.get("protocolVersion") != PROTOCOL_VERSION:
            raise AcpError(f"Unsupported ACP protocol version {init.get('protocolVersion')}")

        session_res = self._request("session/new", {
            "cwd": self.cwd,
            "mcpServers": self.mcp_servers or [],
        }, deadline)
        self.session_id = session_res.get("sessionId")
        if not self.session_id:
            raise AcpError("session/new returned no sessionId")

    def prompt(self, prompt: str, timeout: float = 180.0) -> Tuple[int, str, str]:
        """Sends one prompt turn to the session without shutting down the process."""
        deadline = time.monotonic() + timeout
        self._text.clear()
        self._cancelled.clear()

        try:
            if not self.is_alive():
                self.start(timeout=min(timeout, 30.0))

            result = self._request("session/prompt", {
                "sessionId": self.session_id,
                "prompt": [{"type": "text", "text": prompt}],
            }, deadline)
            stop = result.get("stopReason", "end_turn")
            text = "".join(self._text)
            if self._cancelled.is_set():
                return 130, text, "Task stopped by user."
            if stop in ("end_turn", "max_tokens", "max_turn_requests"):
                return 0, text, ""
            return 1, text, f"Agent stopped: {stop}"
        except TimeoutError:
            self._cancel()
            return 124, "".join(self._text), f"Task timed out after {timeout} seconds."
        except (AcpError, OSError) as e:
            if self._cancelled.is_set():
                return 130, "".join(self._text), "Task stopped by user."
            # OSError: the agent exited and closed its stdin before we could write to it
            if isinstance(e, OSError):
                e = AcpError(f"Agent exited during startup: {e}")
            return 1, "".join(self._text), f"{e}\n{''.join(self._stderr)}".strip()

    def run(self, prompt: str, timeout: float = 180.0, keep_alive: Optional[bool] = None) -> Tuple[int, str, str]:
        """Runs one prompt turn. If keep_alive is False, closes the session on exit."""
        should_keep_alive = self.keep_alive if keep_alive is None else keep_alive
        try:
            return self.prompt(prompt, timeout=timeout)
        finally:
            if not should_keep_alive:
                self.close()

    def close(self) -> None:
        """Terminates the running agent session and process cleanly."""
        self._shutdown(self._readers)
        self.session_id = None
        self._readers.clear()

    def __del__(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.close()

    def cancel(self) -> None:
        """Stops the turn from another thread: asks the agent to cancel, then kills it if it does not stop."""
        if self._cancelled.is_set():
            return
        self._cancelled.set()
        logger.info("[ACP] Cancelling task")
        self._cancel()
        timer = threading.Timer(CANCEL_GRACE_S, self._force_kill)
        timer.daemon = True
        timer.start()

    def _force_kill(self) -> None:
        proc = self.proc
        if proc and proc.poll() is None:
            logger.info("[ACP] Agent ignored cancel; killing it")
            _kill_tree(proc)

    def _cancel(self) -> None:
        if self.session_id and self.proc and self.proc.poll() is None:
            try:
                self._send({"method": "session/cancel", "params": {"sessionId": self.session_id}})
            except OSError:
                pass

    def _shutdown(self, readers: Optional[List[threading.Thread]] = None) -> None:
        if not self.proc:
            return
        try:
            if self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _kill_tree(self.proc)
        target_readers = readers if readers is not None else self._readers
        for r in target_readers:
            if r.is_alive():
                r.join(timeout=2)


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kills the process and its children (on Windows an npm .cmd shim leaves node running otherwise)."""
    if sys.platform == "win32":
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        proc.kill()
    except OSError:
        pass
