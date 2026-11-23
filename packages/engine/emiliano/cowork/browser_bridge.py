"""
Browser Bridge Module for Emiliano Desktop Cowork.
Manages communication with the Emiliano Chrome Extension via local WebSocket or REST proxy,
allowing deterministic, non-activating background browser automation (DOM manipulation,
virtual input, navigation, and screenshots) without moving the OS mouse cursor.
Licensed under PolyForm Shield 1.0.0.
"""

from __future__ import annotations

import asyncio
import base64
import json
import urllib.request
import uuid
from typing import Any, Dict, List, Optional
from loguru import logger


class BaseBrowserBridge:
    """Abstract base interface for browser automation commands."""

    @property
    def is_connected(self) -> bool:
        raise NotImplementedError

    @property
    def extension_info(self) -> Dict[str, Any]:
        return {}

    async def send_command(self, action: str, params: Optional[Dict[str, Any]] = None, timeout: float = 20.0) -> Any:
        raise NotImplementedError

    async def get_tabs(self, query: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Returns list of open tabs matching query."""
        res = await self.send_command("get_tabs", {"query": query or {}})
        return res or []

    async def navigate(self, url: str, target_url_match: Optional[str] = None, background: bool = True) -> Dict[str, Any]:
        """Navigates an existing matching tab or opens a new tab silently."""
        return await self.send_command("navigate", {
            "url": url,
            "targetUrlMatch": target_url_match,
            "background": background,
        })

    async def execute_script(self, code: str, target_url_match: Optional[str] = None) -> Any:
        """Executes JavaScript expression in the matching tab DOM."""
        return await self.send_command("execute_script", {
            "code": code,
            "targetUrlMatch": target_url_match,
        })

    async def type_into(self, selector: str, text: str, target_url_match: Optional[str] = None) -> bool:
        """Types text into an input or contenteditable element in the page."""
        return bool(await self.send_command("type_into", {
            "selector": selector,
            "text": text,
            "targetUrlMatch": target_url_match,
        }))

    async def click_element(self, selector: str, target_url_match: Optional[str] = None) -> bool:
        """Clicks an element matching the CSS selector."""
        return bool(await self.send_command("click_element", {
            "selector": selector,
            "targetUrlMatch": target_url_match,
        }))

    async def click_by_text(self, text: str, tag: str = "*", target_url_match: Optional[str] = None) -> bool:
        """Clicks an element containing the given text."""
        return bool(await self.send_command("click_by_text", {
            "text": text,
            "tag": tag,
            "targetUrlMatch": target_url_match,
        }))

    async def capture_screenshot(self, target_url_match: Optional[str] = None) -> bytes:
        """Takes a screenshot of the target tab and returns PNG bytes."""
        res = await self.send_command("capture_screenshot", {"targetUrlMatch": target_url_match})
        # res is data URI or base64 string
        data_b64 = res.split(",")[-1] if isinstance(res, str) else ""
        return base64.b64decode(data_b64)

    async def send_cdp_command(self, method: str, params: Optional[Dict[str, Any]] = None, target_url_match: Optional[str] = None) -> Any:
        """Invokes a Chrome DevTools Protocol method via chrome.debugger inside the extension."""
        return await self.send_command("cdp_command", {
            "method": method,
            "params": params or {},
            "targetUrlMatch": target_url_match,
        })


class BrowserBridge(BaseBrowserBridge):
    """Singleton bridge that routes automation requests to connected Chrome and Firefox extensions via direct WebSocket."""

    _instance: Optional[BrowserBridge] = None

    def __init__(self) -> None:
        self._active_ws = None
        self._active_connections: Dict[Any, Dict[str, Any]] = {}
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()
        self._extension_info: Dict[str, Any] = {}

    @classmethod
    def get_instance(cls) -> BrowserBridge:
        if cls._instance is None:
            cls._instance = BrowserBridge()
        return cls._instance

    @property
    def is_connected(self) -> bool:
        return bool(self._active_connections or self._active_ws)

    @property
    def extension_info(self) -> Dict[str, Any]:
        return self._extension_info

    @property
    def connected_browsers(self) -> List[Dict[str, Any]]:
        """Returns list of currently connected browser extensions."""
        return list(self._active_connections.values())

    async def handle_connection(self, websocket) -> None:
        """Handles the lifecycle of an incoming browser extension WebSocket connection."""
        self._active_ws = websocket
        self._active_connections[websocket] = {"connected_at": asyncio.get_event_loop().time()}
        logger.info("[BrowserBridge] Browser extension connected successfully.")
        try:
            while True:
                raw_data = await websocket.receive_text()
                try:
                    data = json.loads(raw_data)
                    msg_type = data.get("type")
                    msg_id = data.get("id")

                    if msg_type == "EXTENSION_HANDSHAKE":
                        info = data.get("payload", {})
                        self._extension_info = info
                        self._active_connections[websocket] = info
                        browser_name = info.get("browser", "Browser")
                        logger.info(f"[BrowserBridge] {browser_name} extension handshake: {info}")
                        await websocket.send_text(json.dumps({"type": "HANDSHAKE_ACK", "id": msg_id, "status": "ok"}))
                    elif msg_type == "PING":
                        await websocket.send_text(json.dumps({"type": "PONG"}))
                    elif msg_type == "PONG":
                        pass
                    elif msg_id and msg_id in self._pending_requests:
                        future = self._pending_requests.pop(msg_id)
                        if not future.done():
                            if data.get("error"):
                                future.set_exception(RuntimeError(data["error"]))
                            else:
                                future.set_result(data.get("result"))
                    else:
                        logger.debug(f"[BrowserBridge] Received unhandled message: {data}")
                except json.JSONDecodeError:
                    logger.warning(f"[BrowserBridge] Invalid JSON received: {raw_data}")
        except Exception as e:
            logger.info(f"[BrowserBridge] Browser extension connection closed: {e}")
        finally:
            self._active_connections.pop(websocket, None)
            if self._active_ws == websocket:
                self._active_ws = next(iter(self._active_connections.keys())) if self._active_connections else None
                self._extension_info = self._active_connections.get(self._active_ws, {}) if self._active_ws else {}
            for future in self._pending_requests.values():
                if not future.done():
                    future.set_exception(ConnectionResetError("Browser extension disconnected."))
            self._pending_requests.clear()

    async def send_command(self, action: str, params: Optional[Dict[str, Any]] = None, timeout: float = 20.0, browser: Optional[str] = None) -> Any:
        """Sends an RPC command to the connected extension and awaits the result."""
        target_ws = None
        if browser and self._active_connections:
            for ws, info in self._active_connections.items():
                if info.get("browser", "").lower() == browser.lower():
                    target_ws = ws
                    break
        if target_ws is None:
            target_ws = self._active_ws

        if not self.is_connected or target_ws is None:
            raise RuntimeError("Browser extension is not connected. Open Chrome or Firefox with the Emiliano extension installed.")

        req_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending_requests[req_id] = future

        message = {
            "id": req_id,
            "action": action,
            "params": params or {},
        }

        try:
            await target_ws.send_text(json.dumps(message))
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_requests.pop(req_id, None)
            raise TimeoutError(f"Browser command '{action}' timed out after {timeout}s")
        except Exception:
            self._pending_requests.pop(req_id, None)
            raise


class RemoteBrowserBridge(BaseBrowserBridge):
    """Proxy bridge that communicates with the BrowserBridge inside the Emiliano daemon via REST."""

    def __init__(self, base_url: str = "http://127.0.0.1:8765"):
        self.base_url = base_url.rstrip("/")

    @property
    def is_connected(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base_url}/api/browser/status")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return bool(data.get("connected"))
        except Exception:
            return False

    @property
    def extension_info(self) -> Dict[str, Any]:
        try:
            req = urllib.request.Request(f"{self.base_url}/api/browser/status")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("extension_info", {})
        except Exception:
            return {}

    async def send_command(self, action: str, params: Optional[Dict[str, Any]] = None, timeout: float = 20.0) -> Any:
        loop = asyncio.get_running_loop()

        def _do_post():
            payload = json.dumps({"action": action, "params": params or {}, "timeout": timeout}).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base_url}/api/browser/command",
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=timeout + 2.0) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                return res_data.get("result")

        return await loop.run_in_executor(None, _do_post)


def get_browser_bridge(allow_remote: bool = True) -> BaseBrowserBridge:
    """Returns local singleton BrowserBridge if connected; falls back to RemoteBrowserBridge."""
    local = BrowserBridge.get_instance()
    if local.is_connected:
        return local
    if allow_remote:
        remote = RemoteBrowserBridge()
        if remote.is_connected:
            return remote
    return local
