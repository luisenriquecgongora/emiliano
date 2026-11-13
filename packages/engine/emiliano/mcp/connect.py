"""
One-step connections to known MCP services (PlaatoOS), used by `emiliano connect` and the dock's Connect button:
sign in (or store a token), add the server to the config file, and check that its tools load.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

import yaml

from . import auth

SERVICES: Dict[str, Dict[str, Any]] = {
    "plaatoos": {"title": "PlaatoOS", "url": auth.PLAATOOS["mcp_url"], "api": auth.PLAATOOS["api"]},
}


def config_path() -> Path:
    """The file Emiliano reads its settings from (./emiliano.yaml if present, else ~/.emiliano/config.yaml)."""
    from ..core.config import get_default_config_path
    return Path(get_default_config_path())


def _read(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a settings file (expected a mapping at the top).")
    return data


def _write(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def set_server(name: str, entry: Optional[Dict[str, Any]], path: Optional[Path] = None) -> Path:
    """Adds or replaces (entry) or removes (None) one mcp_servers entry, keeping the rest of the file."""
    path = path or config_path()
    data = _read(path)
    servers = data.get("mcp_servers") or {}
    if entry is None:
        servers.pop(name, None)
    else:
        servers[name] = entry
    if servers:
        data["mcp_servers"] = servers
    else:
        data.pop("mcp_servers", None)
    _write(path, data)
    return path


def check(name: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    """Starts the server once: {"ok", "tools", "hidden", "error"}."""
    from ..core.config import McpServerConfig
    from .manager import McpManager
    manager = McpManager({name: McpServerConfig(**entry)})
    try:
        manager.start()
        status = manager.statuses[name]
        return {"ok": status.ok, "tools": len(status.tools), "hidden": status.hidden, "error": status.error}
    finally:
        manager.close()


def connect(service: str, token: Optional[str] = None, on_url: Optional[Callable[[str], None]] = None,
            open_browser: Optional[Callable[[str], Any]] = None) -> Dict[str, Any]:
    """
    Connects a known service: with a token stores it, otherwise runs the browser sign-in; then writes the config
    entry and checks the tools. Returns {"service", "auth", "config", "ok", "tools", "hidden", "error"}.
    """
    if service not in SERVICES:
        raise ValueError(f"Unknown service '{service}'. Known: {', '.join(SERVICES)}")
    info = SERVICES[service]
    if token:
        auth.save_static_token(service, token)
        mode = "token"
    else:
        kwargs: Dict[str, Any] = {"server": service, "api_base": info["api"], "on_url": on_url}
        if open_browser is not None:
            kwargs["open_browser"] = open_browser
        auth.login(**kwargs)
        mode = "oauth"
    entry = {"url": info["url"], "auth": mode}
    path = set_server(service, entry)
    return {"service": service, "auth": mode, "config": str(path), **check(service, entry)}


def disconnect(service: str) -> Dict[str, Any]:
    """Signs out (revoking the sign-in on the server), forgets the credentials and removes the config entry."""
    had_credentials = auth.logout(service)
    path = set_server(service, None)
    return {"service": service, "removed_credentials": had_credentials, "config": str(path)}


def status(service: str) -> Dict[str, Any]:
    """Whether a service is connected, without contacting it."""
    from . import credentials
    record = credentials.load(service) or {}
    configured = service in (_read(config_path()).get("mcp_servers") or {})
    return {"service": service, "connected": bool(record) and configured, "auth": record.get("kind")}
