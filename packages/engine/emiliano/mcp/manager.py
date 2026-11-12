"""
Runs the MCP servers configured under `mcp_servers` and offers their tools to Emiliano's own agent loop.

Each tool is exposed as `<server>__<tool>` (e.g. `github__search_issues`), so tools of different servers never
collide with each other or with the built-in read_file/grep/bash. A server that fails to start is reported and
skipped; the others still work.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")

from .client import McpStdioClient

# Built-in tools of the direct agent; an MCP tool may not take one of these names
BUILTIN_TOOLS = {"read_file", "edit_file", "write_file", "list_dir", "grep", "search", "bash"}
_DESCRIPTION_CHARS = 200


@dataclass
class McpTool:
    qualified_name: str      # what the model calls: "server__tool"
    server: str
    name: str                # the name the server knows
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)


@dataclass
class McpServerStatus:
    name: str
    ok: bool
    tools: List[str] = field(default_factory=list)
    error: str = ""


def qualify(server: str, tool: str) -> str:
    """'GitHub', 'search-issues' -> 'github__search_issues': a name every model can write in a tool call."""
    def clean(s: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_]+", "_", s).strip("_").lower()
    return f"{clean(server)}__{clean(tool)}"


class McpManager:
    """Starts configured servers on first use and keeps them running until close()."""

    def __init__(self, servers: Dict[str, Any], cwd: Optional[str] = None):
        # servers: name -> McpServerConfig (or any object with command/args/env/enabled/timeout)
        self.servers = {name: cfg for name, cfg in servers.items() if getattr(cfg, "enabled", True)}
        self.cwd = cwd
        self.clients: Dict[str, McpStdioClient] = {}
        self.tools: Dict[str, McpTool] = {}
        self.statuses: Dict[str, McpServerStatus] = {}
        self._lock = threading.Lock()
        self._started = False

    @property
    def configured(self) -> bool:
        return bool(self.servers)

    def start(self) -> None:
        """Starts every server not running yet and lists its tools. Safe to call again: dead servers restart."""
        with self._lock:
            for name, cfg in self.servers.items():
                client = self.clients.get(name)
                if client and client.is_alive():
                    continue
                self._start_server(name, cfg)
            self._started = True

    def _start_server(self, name: str, cfg: Any) -> None:
        for qualified in [q for q, t in self.tools.items() if t.server == name]:
            del self.tools[qualified]
        client = McpStdioClient(name, cfg.command, cfg.args, cfg.env, cwd=self.cwd)
        try:
            client.start()
            listed = client.list_tools()
        except Exception as e:
            client.close()
            self.clients.pop(name, None)
            self.statuses[name] = McpServerStatus(name, ok=False, error=str(e))
            logger.warning(f"[MCP] Server '{name}' unavailable: {e}")
            return
        self.clients[name] = client
        names = []
        for t in listed:
            qualified = qualify(name, t["name"])
            if qualified in BUILTIN_TOOLS or qualified in self.tools:
                logger.warning(f"[MCP] Skipping tool '{t['name']}' of '{name}': name '{qualified}' is taken")
                continue
            self.tools[qualified] = McpTool(qualified, name, t["name"], (t.get("description") or "").strip(),
                                            t.get("inputSchema") or {})
            names.append(qualified)
        self.statuses[name] = McpServerStatus(name, ok=True, tools=names)
        logger.info(f"[MCP] Server '{name}' ready with {len(names)} tools")

    def has(self, qualified_name: str) -> bool:
        return qualified_name in self.tools

    def call(self, qualified_name: str, arguments: Optional[Dict[str, Any]] = None) -> str:
        tool = self.tools.get(qualified_name)
        if tool is None:
            return f"Error: Unknown tool '{qualified_name}'."
        client = self.clients.get(tool.server)
        if client is None or not client.is_alive():
            with self._lock:
                self._start_server(tool.server, self.servers[tool.server])
            client = self.clients.get(tool.server)
            if client is None:
                return f"Error: MCP server '{tool.server}' is not running: {self.statuses[tool.server].error}"
        try:
            return client.call_tool(tool.name, arguments or {}, timeout=getattr(self.servers[tool.server], "timeout", 60.0))
        except Exception as e:
            return f"Error: {e}"

    async def astart(self) -> None:
        await asyncio.to_thread(self.start)

    async def acall(self, qualified_name: str, arguments: Optional[Dict[str, Any]] = None) -> str:
        return await asyncio.to_thread(self.call, qualified_name, arguments)

    def describe_tools(self) -> str:
        """The tool list for the agent's system prompt, with each tool's parameters ('?' marks optional ones)."""
        lines = []
        for tool in self.tools.values():
            props = (tool.input_schema.get("properties") or {}) if isinstance(tool.input_schema, dict) else {}
            required = set(tool.input_schema.get("required") or []) if isinstance(tool.input_schema, dict) else set()
            params = ", ".join(f"{p}{'' if p in required else '?'}: {(spec or {}).get('type', 'any')}"
                               for p, spec in props.items())
            desc = " ".join(tool.description.split())
            if len(desc) > _DESCRIPTION_CHARS:
                desc = desc[:_DESCRIPTION_CHARS].rstrip() + "..."
            lines.append(f"- {tool.qualified_name}({params}): {desc}" if desc else f"- {tool.qualified_name}({params})")
        return "\n".join(lines)

    def prompt_section(self) -> str:
        """Extra system-prompt text that teaches the model to call MCP tools; empty when there are none."""
        if not self.tools:
            return ""
        example = next(iter(self.tools.values()))
        example_args = {p: "..." for p in list((example.input_schema.get("properties") or {}))[:1]}
        return (
            "\n\nYou also have these external tools (from MCP servers):\n"
            f"{self.describe_tools()}\n"
            "Call them with the JSON format, passing arguments by name:\n"
            f"<tool_call>{json.dumps({'name': example.qualified_name, 'arguments': example_args})}</tool_call>\n"
        )

    def close(self) -> None:
        with self._lock:
            for client in self.clients.values():
                try:
                    client.close()
                except Exception:
                    pass
            self.clients.clear()
            self._started = False


def acp_server_list(servers: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The configured servers in ACP's session/new format, so ACP harnesses (Claude Code, Codex) get them too."""
    return [
        {"name": name, "command": cfg.command, "args": list(cfg.args),
         "env": [{"name": k, "value": v} for k, v in cfg.env.items()]}
        for name, cfg in servers.items() if getattr(cfg, "enabled", True)
    ]
