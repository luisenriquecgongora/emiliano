"""
Model Context Protocol (MCP) client over stdio.

Starts an MCP server as a subprocess and talks JSON-RPC 2.0 to it, one JSON message per line: initialize, then
tools/list and tools/call. Emiliano is the host: it decides which tools a model sees and runs the calls the model
asks for. Threads and a plain subprocess (like the ACP client) rather than asyncio, so one server keeps running
across the terminal chat's turns, each of which runs its own event loop.
Spec: https://modelcontextprotocol.io/specification
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")

from .. import __version__

PROTOCOL_VERSION = "2025-06-18"
METHOD_NOT_FOUND = -32601
# A tool result longer than this is cut, so one call cannot flood a small model's context
MAX_RESULT_CHARS = 20_000


INITIALIZE_PARAMS = {
    "protocolVersion": PROTOCOL_VERSION,
    "capabilities": {"roots": {"listChanged": False}},
    "clientInfo": {"name": "emiliano", "title": "Emiliano", "version": __version__},
}


class McpError(RuntimeError):
    """The server returned a JSON-RPC error, broke the protocol, or exited."""


class _McpClient:
    """What every transport shares: listing and calling tools on top of request()."""

    name: str

    def request(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 30.0) -> Dict[str, Any]:
        raise NotImplementedError

    def list_tools(self, timeout: float = 30.0) -> List[Dict[str, Any]]:
        tools: List[Dict[str, Any]] = []
        cursor = None
        for _ in range(50):  # pages; a guard against a server that never stops paging
            result = self.request("tools/list", {"cursor": cursor} if cursor else {}, timeout=timeout)
            tools.extend(t for t in result.get("tools", []) if isinstance(t, dict) and t.get("name"))
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    def call_tool(self, tool: str, arguments: Optional[Dict[str, Any]] = None, timeout: float = 60.0) -> str:
        """Runs a tool and returns its result as text for the model; a failed tool reads "Error: ..."."""
        result = self.request("tools/call", {"name": tool, "arguments": arguments or {}}, timeout=timeout)
        text = format_tool_result(result)
        return f"Error: {text}" if result.get("isError") else text


class McpStdioClient(_McpClient):
    """One MCP server process."""

    def __init__(self, name: str, command: str, args: Optional[List[str]] = None,
                 env: Optional[Dict[str, str]] = None, cwd: Optional[str] = None):
        self.name = name
        self.command = command
        self.args = list(args or [])
        self.env = dict(env or {})
        self.cwd = os.path.abspath(cwd or os.getcwd())
        self.proc: Optional[subprocess.Popen] = None
        self.server_info: Dict[str, Any] = {}
        self._next_id = 0
        self._id_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._pending: Dict[int, Dict[str, Any]] = {}  # id -> {"event": Event, "msg": response}
        self._stderr: deque = deque(maxlen=40)

    # --- transport -------------------------------------------------------------------------

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _send(self, message: Dict[str, Any]) -> None:
        message["jsonrpc"] = "2.0"
        line = json.dumps(message, ensure_ascii=False) + "\n"
        with self._write_lock:
            if not self.is_alive():
                raise McpError(f"MCP server '{self.name}' is not running.{self._stderr_hint()}")
            self.proc.stdin.write(line)
            self.proc.stdin.flush()

    def request(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 30.0) -> Dict[str, Any]:
        with self._id_lock:
            req_id = self._next_id
            self._next_id += 1
        slot: Dict[str, Any] = {"event": threading.Event(), "msg": None}
        self._pending[req_id] = slot
        try:
            self._send({"id": req_id, "method": method, "params": params or {}})
            deadline = time.monotonic() + timeout
            while not slot["event"].wait(timeout=0.25):
                if not self.is_alive():
                    raise McpError(f"MCP server '{self.name}' exited during {method}.{self._stderr_hint()}")
                if time.monotonic() > deadline:
                    raise McpError(f"MCP server '{self.name}' did not answer {method} within {timeout:.0f}s.")
        finally:
            self._pending.pop(req_id, None)
        msg = slot["msg"] or {}
        if "error" in msg:
            err = msg["error"] or {}
            raise McpError(f"{self.name}: {method} failed: {err.get('message', err)}")
        return msg.get("result") or {}

    def _notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        message: Dict[str, Any] = {"method": method}
        if params:
            message["params"] = params
        self._send(message)

    def _read_stdout(self) -> None:
        for line in iter(self.proc.stdout.readline, ""):
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                logger.debug(f"[MCP:{self.name}] Ignoring non-JSON line: {line[:120]}")
                continue
            if not isinstance(msg, dict):
                continue
            if "method" in msg:
                if "id" in msg:
                    try:
                        self._answer_server_request(msg)
                    except Exception as e:  # never let one bad message kill the reader
                        logger.warning(f"[MCP:{self.name}] Failed to answer {msg.get('method')}: {e}")
                continue  # notifications (logging, progress, list_changed) need no answer
            slot = self._pending.get(msg.get("id"))
            if slot is not None:
                slot["msg"] = msg
                slot["event"].set()

    def _read_stderr(self) -> None:
        for line in iter(self.proc.stderr.readline, ""):
            self._stderr.append(line.rstrip())

    def _stderr_hint(self) -> str:
        tail = " | ".join(line for line in list(self._stderr)[-3:] if line)
        return f" Server said: {tail}" if tail else ""

    def _answer_server_request(self, msg: Dict[str, Any]) -> None:
        """Servers may ask the host things too; answer the simple ones, decline the rest."""
        method = msg.get("method")
        if method == "ping":
            self._send({"id": msg["id"], "result": {}})
        elif method == "roots/list":
            self._send({"id": msg["id"], "result": {"roots": [{"uri": Path(self.cwd).as_uri(), "name": "workspace"}]}})
        else:
            self._send({"id": msg["id"], "error": {"code": METHOD_NOT_FOUND, "message": f"Unsupported: {method}"}})

    # --- lifecycle ---------------------------------------------------------------------------

    def start(self, timeout: float = 60.0) -> None:
        """Spawns the server and performs the initialize handshake. The first `npx -y` run downloads the package,
        so the default timeout is generous."""
        if self.is_alive():
            return
        exe = shutil.which(self.command) or self.command
        env = {**os.environ, **self.env, "PYTHONUNBUFFERED": "1"}
        self.proc = subprocess.Popen(
            [exe, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=self.cwd,
            # npm installs .cmd shims on Windows, which only run through the shell
            shell=sys.platform == "win32" and exe.lower().endswith((".cmd", ".bat")),
            bufsize=1,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        for target in (self._read_stdout, self._read_stderr):
            threading.Thread(target=target, name=f"mcp-{self.name}", daemon=True).start()

        try:
            init = self.request("initialize", INITIALIZE_PARAMS, timeout=timeout)
        except Exception:
            self.close()
            raise
        self.server_info = init.get("serverInfo") or {}
        self._notify("notifications/initialized")

    def close(self) -> None:
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
            from ..harnesses.acp import _kill_tree
            _kill_tree(self.proc)


_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand_env(value: str) -> str:
    """'Bearer ${PLAATOOS_TOKEN}' -> 'Bearer pak_...'. A variable that is not set is an error, so a missing token
    is reported as such instead of being sent as an empty header."""
    def sub(m: "re.Match[str]") -> str:
        name = m.group(1)
        if name not in os.environ:
            raise McpError(f"environment variable {name} is not set (used in an MCP header)")
        return os.environ[name]
    return _ENV_REF.sub(sub, value)


def _parse_sse(body: str) -> List[Dict[str, Any]]:
    """JSON-RPC messages from a text/event-stream body: each event's data lines joined."""
    messages, data = [], []
    for line in body.replace("\r\n", "\n").split("\n") + [""]:
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif line == "" and data:
            try:
                msg = json.loads("\n".join(data))
                if isinstance(msg, dict):
                    messages.append(msg)
            except ValueError:
                pass
            data = []
    return messages


class McpHttpClient(_McpClient):
    """
    A remote MCP server over Streamable HTTP: each JSON-RPC message is a POST to one URL; the reply is plain JSON or
    a short event stream. Keeps the session id the server may assign. Certificates are checked against the operating
    system's store, which also trusts the TLS-inspecting proxies some networks use.
    """

    def __init__(self, name: str, url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 30.0):
        self.name = name
        self.url = url
        self.raw_headers = dict(headers or {})
        self.timeout = timeout
        self.server_info: Dict[str, Any] = {}
        self.protocol_version: Optional[str] = None
        self.session_id: Optional[str] = None
        self._client = None
        self._next_id = 0
        self._lock = threading.Lock()

    def is_alive(self) -> bool:
        return self._client is not None

    def _headers(self) -> Dict[str, str]:
        headers = {k: expand_env(v) for k, v in self.raw_headers.items()}
        headers.update({"Accept": "application/json, text/event-stream", "Content-Type": "application/json"})
        if self.protocol_version:
            headers["MCP-Protocol-Version"] = self.protocol_version
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    def _post(self, message: Dict[str, Any], timeout: float):
        import httpx
        message["jsonrpc"] = "2.0"
        try:
            res = self._client.post(self.url, json=message, headers=self._headers(), timeout=timeout)
        except httpx.HTTPError as e:
            raise McpError(f"MCP server '{self.name}' unreachable at {self.url}: {e}") from e
        if res.headers.get("mcp-session-id"):
            self.session_id = res.headers["mcp-session-id"]
        if res.status_code in (401, 403):
            raise McpError(f"MCP server '{self.name}' refused the credentials (HTTP {res.status_code}). "
                           "Check the token in its headers.")
        return res

    def request(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 30.0) -> Dict[str, Any]:
        if self._client is None:
            raise McpError(f"MCP server '{self.name}' is not connected.")
        with self._lock:
            req_id = self._next_id
            self._next_id += 1
        res = self._post({"id": req_id, "method": method, "params": params or {}}, timeout)
        if res.headers.get("content-type", "").startswith("text/event-stream"):
            replies = [m for m in _parse_sse(res.text) if m.get("id") == req_id]
            msg = replies[-1] if replies else {}
        else:
            try:
                msg = res.json()
            except ValueError:
                raise McpError(f"{self.name}: {method} returned HTTP {res.status_code} without JSON") from None
        if not isinstance(msg, dict) or ("result" not in msg and "error" not in msg):
            raise McpError(f"{self.name}: {method} returned HTTP {res.status_code} with no JSON-RPC answer")
        if "error" in msg:
            err = msg["error"] or {}
            raise McpError(f"{self.name}: {method} failed: {err.get('message', err)}")
        return msg.get("result") or {}

    def start(self, timeout: float = 30.0) -> None:
        if self._client is not None:
            return
        import ssl

        import httpx
        self._client = httpx.Client(verify=ssl.create_default_context(), follow_redirects=True)
        try:
            init = self.request("initialize", INITIALIZE_PARAMS, timeout=timeout)
            self.server_info = init.get("serverInfo") or {}
            self.protocol_version = init.get("protocolVersion") or PROTOCOL_VERSION
            self._post({"method": "notifications/initialized"}, timeout)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self._client is not None:
            try:
                if self.session_id:  # tell the server the session is over; ignore failures
                    self._client.delete(self.url, headers=self._headers(), timeout=5)
            except Exception:
                pass
            self._client.close()
            self._client = None
        self.session_id = None


def format_tool_result(result: Dict[str, Any]) -> str:
    """The text of a tools/call result: text parts as-is, other parts as short placeholders."""
    parts: List[str] = []
    for item in result.get("content") or []:
        kind = item.get("type")
        if kind == "text":
            parts.append(item.get("text", ""))
        elif kind == "resource":
            res = item.get("resource") or {}
            parts.append(res.get("text") or f"[resource {res.get('uri', '')}]")
        elif kind == "resource_link":
            parts.append(f"[resource {item.get('uri', '')}]")
        else:
            parts.append(f"[{kind} content omitted]")
    if not parts and result.get("structuredContent") is not None:
        parts.append(json.dumps(result["structuredContent"], ensure_ascii=False))
    text = "\n".join(parts).strip() or "(no output)"
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + f"\n[... cut: {len(text) - MAX_RESULT_CHARS} more characters]"
    return text
