"""
Request origin checks for the engine's local server.
"""

from __future__ import annotations

import os
from typing import Optional, Set

# Origins allowed to open the IPC WebSocket: the Tauri desktop app (http(s)://tauri.localhost
# on Windows, tauri://localhost on macOS/Linux) and the Vite dev server in development.
# Browsers always send Origin on a WebSocket handshake and pages cannot forge it, so this
# stops any website or local HTML file from driving the daemon (WebSockets are not covered
# by CORS). Requests without an Origin header come from local non-browser clients.
# Override with EMILIANO_ALLOWED_ORIGINS (comma-separated).
DEFAULT_ALLOWED_ORIGINS = (
    "http://tauri.localhost",
    "https://tauri.localhost",
    "tauri://localhost",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def get_allowed_origins() -> Set[str]:
    raw = os.environ.get("EMILIANO_ALLOWED_ORIGINS")
    origins = raw.split(",") if raw else DEFAULT_ALLOWED_ORIGINS
    return {o.strip().rstrip("/") for o in origins if o.strip()}


def is_origin_allowed(origin: Optional[str]) -> bool:
    if origin is None:
        return True
    # "null" (sandboxed iframes, data: URLs) is deliberately not allowed
    return origin.rstrip("/") in get_allowed_origins()
