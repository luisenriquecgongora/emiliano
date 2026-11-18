"""
Runs the MCP servers configured under `mcp_servers` and offers their tools to Emiliano's own agent loop.

Each tool is exposed as `<server>__<tool>` (e.g. `github__search_issues`), so tools of different servers never
collide with each other or with the built-in read_file/grep/bash. A server that fails to start is reported and
skipped; the others still work.
"""

from __future__ import annotations

import asyncio
import fnmatch
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

from .client import McpHttpClient, McpStdioClient

# Built-in tools of the direct agent; an MCP tool may not take one of these names
BUILTIN_TOOLS = {"read_file", "edit_file", "write_file", "list_dir", "grep", "search", "bash", "mcp_describe"}
_DESCRIPTION_CHARS = 200
# Above this many MCP tools the prompt lists names and short descriptions only; the model fetches a tool's
# parameters with mcp_describe. A big catalog (PlaatoOS has 100+) would otherwise fill a small model's context.
COMPACT_ABOVE = 25
_COMPACT_DESCRIPTION_CHARS = 140
DESCRIBE_TOOL = "mcp_describe"


def is_destructive(tool: Dict[str, Any]) -> bool:
    """MCP puts hints under "annotations"; some servers (PlaatoOS) put them on the tool itself."""
    annotations = tool.get("annotations") if isinstance(tool.get("annotations"), dict) else {}
    return bool(annotations.get("destructiveHint", tool.get("destructiveHint", False)))


def keep_tool(tool: Dict[str, Any], cfg: Any) -> bool:
    """Whether a listed tool passes the server's tools / exclude_tools patterns and destructive setting."""
    name = tool["name"]
    include = list(getattr(cfg, "tools", None) or [])
    exclude = list(getattr(cfg, "exclude_tools", None) or [])
    if include and not any(fnmatch.fnmatchcase(name, p) for p in include):
        return False
    if any(fnmatch.fnmatchcase(name, p) for p in exclude):
        return False
    return bool(getattr(cfg, "allow_destructive", False)) or not is_destructive(tool)


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
    hidden: int = 0  # tools the server offered that its tools / exclude_tools / destructive settings left out


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
        url = getattr(cfg, "url", None)
        provider = None
        if url and getattr(cfg, "auth", None):
            from .auth import TokenProvider
            provider = TokenProvider(name)
        client = (McpHttpClient(name, url, getattr(cfg, "headers", {}), timeout=getattr(cfg, "timeout", 30.0),
                                token_provider=provider)
                  if url else McpStdioClient(name, cfg.command, cfg.args, cfg.env, cwd=self.cwd))
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
        hidden = 0
        for t in listed:
            if not keep_tool(t, cfg):
                hidden += 1
                continue
            qualified = qualify(name, t["name"])
            if qualified in BUILTIN_TOOLS or qualified in self.tools:
                logger.warning(f"[MCP] Skipping tool '{t['name']}' of '{name}': name '{qualified}' is taken")
                continue
            self.tools[qualified] = McpTool(qualified, name, t["name"], (t.get("description") or "").strip(),
                                            t.get("inputSchema") or {})
            names.append(qualified)
        self.statuses[name] = McpServerStatus(name, ok=True, tools=names, hidden=hidden)
        logger.info(f"[MCP] Server '{name}' ready with {len(names)} tools ({hidden} hidden by its filters)")

    @property
    def compact(self) -> bool:
        return len(self.tools) > COMPACT_ABOVE

    def has(self, qualified_name: str) -> bool:
        return qualified_name in self.tools or (qualified_name == DESCRIBE_TOOL and self.compact)

    def describe_one(self, qualified_name: str) -> str:
        """A tool's full description and parameter schema, for mcp_describe."""
        wanted = (qualified_name or "").strip()
        tool = self.tools.get(wanted)
        if tool is None:
            close = [q for q in self.tools if wanted.lower() and wanted.lower() in q]
            hint = f" Similar: {', '.join(close[:8])}." if close else ""
            return f"Error: Unknown tool '{wanted}'.{hint}"
        schema = json.dumps(tool.input_schema, ensure_ascii=False, indent=1)
        return f"{tool.qualified_name}: {tool.description}\nParameters (JSON schema):\n{schema}"

    def call(self, qualified_name: str, arguments: Optional[Dict[str, Any]] = None) -> str:
        if qualified_name == DESCRIBE_TOOL:
            args = arguments or {}
            return self.describe_one(str(args.get("name") or args.get("tool") or ""))
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

    def filter_tools_for_goal(self, goal: Optional[str] = None, max_tools: int = 6) -> List[McpTool]:
        """
        Prunes tools to the most relevant subset for a given goal.
        If goal is empty or total tools <= max_tools, returns all tools.
        Otherwise ranks by token overlap in tool name and description.
        """
        all_tools = list(self.tools.values())
        if not goal or len(all_tools) <= max_tools:
            return all_tools

        import re
        tokens = set(re.findall(r"[a-zA-Z0-9_]{3,}", goal.lower()))
        stop_words = {"the", "and", "for", "with", "this", "that", "from", "you", "your", "our", "please", "can", "could", "would", "help", "need"}
        keywords = {t for t in tokens if t not in stop_words}

        domain_boosters = {
            "site": {"site", "website", "block", "hero", "header", "footer", "theme", "title", "page", "landing"},
            "event": {"event", "ticket", "venue", "booking", "schedule"},
            "menu": {"menu", "dish", "price", "order", "food"},
            "business": {"business", "settings", "company", "info", "config"},
        }
        active_domains = {dom for dom, terms in domain_boosters.items() if any(term in keywords for term in terms)}

        scored: List[Tuple[float, McpTool]] = []
        for tool in all_tools:
            score = 0.0
            tool_name_lower = tool.qualified_name.lower()
            desc_lower = (tool.description or "").lower()

            for kw in keywords:
                if kw in tool_name_lower:
                    score += 5.0
                if kw in desc_lower:
                    score += 1.5

            for dom in active_domains:
                if dom in tool_name_lower:
                    score += 3.0
                if dom in desc_lower:
                    score += 1.0

            if any(w in keywords for w in ("query", "get", "check", "read", "inspect", "show", "list")):
                if any(w in tool_name_lower for w in ("query", "get", "read", "list", "inspect")):
                    score += 2.0

            scored.append((score, tool))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = [t for s, t in scored if s > 0][:max_tools]
        if not top:
            top = [t for t in all_tools if any(k in t.qualified_name.lower() for k in ("query", "list", "get", "status"))][:max_tools]
            if not top:
                top = all_tools[:max_tools]
        return top

    def describe_tools(self, tools: Optional[Iterable[McpTool]] = None) -> str:
        """The tool list for the agent's system prompt, with each tool's parameters ('?' marks optional ones);
        in compact mode names and short descriptions only."""
        tools_list = list(tools) if tools is not None else list(self.tools.values())
        lines = []
        if self.compact:
            for tool in tools_list:
                desc = " ".join(tool.description.split())
                if len(desc) > _COMPACT_DESCRIPTION_CHARS:
                    desc = desc[:_COMPACT_DESCRIPTION_CHARS].rstrip() + "..."
                lines.append(f"- {tool.qualified_name}: {desc}" if desc else f"- {tool.qualified_name}")
            return "\n".join(lines)
        for tool in tools_list:
            props = (tool.input_schema.get("properties") or {}) if isinstance(tool.input_schema, dict) else {}
            required = set(tool.input_schema.get("required") or []) if isinstance(tool.input_schema, dict) else set()
            params = ", ".join(f"{p}{'' if p in required else '?'}: {(spec or {}).get('type', 'any')}"
                               for p, spec in props.items())
            desc = " ".join(tool.description.split())
            if len(desc) > _DESCRIPTION_CHARS:
                desc = desc[:_DESCRIPTION_CHARS].rstrip() + "..."
            lines.append(f"- {tool.qualified_name}({params}): {desc}" if desc else f"- {tool.qualified_name}({params})")
        return "\n".join(lines)

    def prompt_section(self, goal: Optional[str] = None) -> str:
        """Extra system-prompt text that teaches the model to call MCP tools; empty when there are none."""
        if not self.tools:
            return ""
        selected_tools = self.filter_tools_for_goal(goal, max_tools=6) if goal else list(self.tools.values())
        example = selected_tools[0] if selected_tools else next(iter(self.tools.values()))
        example_args = {p: "..." for p in list((example.input_schema.get("properties") or {}))[:1]}
        lookup = ""
        if self.compact:
            describe = json.dumps({"name": DESCRIBE_TOOL, "arguments": {"name": example.qualified_name}})
            lookup = (
                "Their parameter schemas are not listed above to conserve context. "
                "For query or read tools with no required parameters (such as query_business, query_business_site), call them directly with arguments: {}.\n"
                f"For complex modification tools, fetch their schema first with:\n<tool_call>{describe}</tool_call>\n"
            )
        return (
            "\n\nYou also have these external tools (from MCP servers):\n"
            f"{self.describe_tools(selected_tools)}\n"
            f"{lookup}"
            "Call them with the JSON format, passing arguments by name:\n"
            f"<tool_call>{json.dumps({'name': example.qualified_name, 'arguments': example_args})}</tool_call>\n"
        )

    def to_ollama_tools(self, goal: Optional[str] = None, max_tools: int = 6) -> List[Dict[str, Any]]:
        """Converts filtered MCP tools into Ollama/OpenAI standard tool definitions."""
        selected = self.filter_tools_for_goal(goal, max_tools=max_tools) if goal else list(self.tools.values())
        tools: List[Dict[str, Any]] = []
        for t in selected:
            schema = t.input_schema if isinstance(t.input_schema, dict) else {}
            tools.append({
                "type": "function",
                "function": {
                    "name": t.qualified_name,
                    "description": t.description or "",
                    "parameters": schema or {"type": "object", "properties": {}},
                }
            })
        return tools

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
    """The configured local (stdio) servers in ACP's session/new format, so ACP harnesses (Claude Code, Codex) get
    them too. Remote URL servers are left out: an ACP agent only accepts them if it advertises HTTP support, and
    passing one would put the expanded token into the agent's session."""
    return [
        {"name": name, "command": cfg.command, "args": list(cfg.args),
         "env": [{"name": k, "value": v} for k, v in cfg.env.items()]}
        for name, cfg in servers.items() if getattr(cfg, "enabled", True) and getattr(cfg, "command", None)
    ]
