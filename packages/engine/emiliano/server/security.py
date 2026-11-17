"""
Request origin and authorization checks for the engine's local server.
"""

from __future__ import annotations

import hmac
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


def get_ipc_token() -> Optional[str]:
    """Retrieves the expected ephemeral IPC token from the environment, if configured."""
    token = os.environ.get("EMILIANO_IPC_TOKEN")
    return token.strip() if token and token.strip() else None


def verify_ipc_token(provided_token: Optional[str]) -> bool:
    """Constant-time verification of the provided IPC bearer token."""
    expected = get_ipc_token()
    if not expected:
        # If no token is configured in environment, allow local invocation
        return True
    if not provided_token:
        return False
    return hmac.compare_digest(provided_token.strip(), expected)


def get_allowed_extension_ids() -> Set[str]:
    """Whitelisted Chrome extension IDs. If empty, allows extension when no whitelist is defined."""
    raw = os.environ.get("EMILIANO_ALLOWED_EXTENSIONS")
    if not raw:
        return set()
    return {ext.strip().lower() for ext in raw.split(",") if ext.strip()}


def is_origin_allowed(origin: Optional[str]) -> bool:
    if origin is None:
        return True
    origin = origin.rstrip("/")
    # Chrome extensions connecting via local WebSocket have origins like chrome-extension://<id>
    if origin.startswith("chrome-extension://"):
        allowed_ids = get_allowed_extension_ids()
        if not allowed_ids:
            return True
        ext_id = origin.replace("chrome-extension://", "").split("/")[0].lower()
        return ext_id in allowed_ids
    # "null" (sandboxed iframes, data: URLs) is deliberately not allowed
    return origin in get_allowed_origins()
