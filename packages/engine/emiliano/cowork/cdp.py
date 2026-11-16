"""
Chrome DevTools Protocol (CDP) Bridge for Emiliano Desktop Cowork.
Enables attaching to real authenticated Chrome user profiles over remote debugging port (9222),
executing in-page JavaScript, extracting DOM text, and deterministic page navigation.
Licensed under PolyForm Shield 1.0.0. Uses open-source MIT/BSD primitives (websockets, urllib).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional
from loguru import logger

try:
    import websockets
except ImportError:
    websockets = None  # type: ignore

DEFAULT_CDP_PORT = 9222
DEFAULT_CDP_HOST = "127.0.0.1"


def find_chrome_executable() -> Optional[str]:
    """Finds Google Chrome executable path on Windows."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def get_chrome_user_data_dir() -> Path:
    """Returns the default Chrome User Data directory on Windows."""
    return Path(os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data"))


def list_chrome_profiles() -> List[str]:
    """Lists available local Chrome profile directories (Default, Profile 1, etc.)."""
    user_data = get_chrome_user_data_dir()
    if not user_data.exists():
        return []

    profiles: List[str] = []
    try:
        for entry in os.listdir(user_data):
            if entry in ("Default", "Guest Profile") or entry.startswith("Profile "):
                profile_path = user_data / entry
                if profile_path.is_dir() and (profile_path / "Preferences").exists():
                    profiles.append(entry)
    except Exception as e:
        logger.warning(f"[CDP] Error listing Chrome profiles: {e}")

    return sorted(profiles)


def is_cdp_available(host: str = DEFAULT_CDP_HOST, port: int = DEFAULT_CDP_PORT) -> bool:
    """Checks if a Chrome remote debugging endpoint is currently responding."""
    url = f"http://{host}:{port}/json/version"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Emiliano-CDP"})
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            return resp.status == 200
    except Exception:
        return False


def get_cdp_tabs(host: str = DEFAULT_CDP_HOST, port: int = DEFAULT_CDP_PORT) -> List[Dict[str, Any]]:
    """Retrieves active pages/tabs from the Chrome debugging endpoint."""
    url = f"http://{host}:{port}/json/list"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Emiliano-CDP"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data)
    except Exception as e:
        logger.debug(f"[CDP] Failed to fetch tabs from {url}: {e}")
        return []


def get_cowork_profile_dir() -> Path:
    """Returns the dedicated, persistent profile directory for Emiliano Cowork."""
    path = Path(os.path.expandvars(r"%LOCALAPPDATA%\Emiliano\ChromeProfile"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def launch_chrome_with_cdp(
    profile_dir: Optional[Path] = None,
    port: int = DEFAULT_CDP_PORT,
    url: Optional[str] = None,
    non_activating: bool = True,
) -> Optional[subprocess.Popen]:
    """
    Launches Chrome with remote debugging enabled using a dedicated persistent profile.
    Can launch in non-activating background mode so the user's active window is not interrupted.
    """
    chrome_path = find_chrome_executable()
    if not chrome_path:
        logger.error("[CDP] Chrome executable not found on system.")
        return None

    user_data = str(profile_dir or get_cowork_profile_dir())
    args = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if url:
        args.append(url)

    logger.info(f"[CDP] Launching Chrome on port {port} with profile at {user_data}")
    try:
        startupinfo = None
        if non_activating and sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 4  # SW_SHOWNOACTIVATE

        proc = subprocess.Popen(args, startupinfo=startupinfo)
        return proc
    except Exception as e:
        logger.error(f"[CDP] Failed to launch Chrome: {e}")
        return None


async def ensure_cowork_browser(port: int = DEFAULT_CDP_PORT, url: Optional[str] = None) -> bool:
    """
    Ensures Chrome is running with remote debugging enabled.
    If not already listening, automatically launches the dedicated Cowork Chrome instance.
    """
    if is_cdp_available(port=port):
        return True

    launch_chrome_with_cdp(port=port, url=url or "https://www.instagram.com")
    for _ in range(20):
        await asyncio.sleep(0.3)
        if is_cdp_available(port=port):
            logger.info(f"[CDP] Successfully connected to auto-launched Chrome on port {port}")
            return True

    logger.warning(f"[CDP] Chrome launch timed out waiting for port {port}")
    return False


class ChromeDevToolsClient:
    """
    Lightweight, asynchronous Chrome DevTools Protocol (CDP) WebSocket client.
    Allows in-page DOM evaluation, JavaScript execution, and tab control.
    """

    def __init__(self, host: str = DEFAULT_CDP_HOST, port: int = DEFAULT_CDP_PORT):
        self.host = host
        self.port = port
        self._ws: Optional[Any] = None
        self._msg_id = 1
        self._connected = False
        self._target_id: Optional[str] = None

    @property
    def is_connected(self) -> bool:
        return self._connected and self._ws is not None

    async def connect(self, target_url_keyword: Optional[str] = None) -> bool:
        """
        Finds the matching active tab and connects to its WebSocket debugger URL.
        """
        if websockets is None:
            logger.error("[CDP] 'websockets' library is required for CDP communication.")
            return False

        tabs = get_cdp_tabs(self.host, self.port)
        if not tabs:
            logger.warning(f"[CDP] No open tabs found at http://{self.host}:{self.port}")
            return False

        # Filter for normal page targets (ignore background services/extensions)
        pages = [t for t in tabs if t.get("type") == "page"]
        if not pages:
            pages = tabs

        target_tab = None
        if target_url_keyword:
            for p in pages:
                if target_url_keyword.lower() in (p.get("url") or "").lower():
                    target_tab = p
                    break

        if not target_tab:
            target_tab = pages[0]

        ws_url = target_tab.get("webSocketDebuggerUrl")
        if not ws_url:
            logger.error("[CDP] Target tab has no webSocketDebuggerUrl.")
            return False

        self._target_id = target_tab.get("id")
        logger.info(f"[CDP] Connecting to tab: '{target_tab.get('title')}' ({target_tab.get('url')})")

        try:
            self._ws = await websockets.connect(ws_url, max_size=10 * 1024 * 1024)
            self._connected = True
            logger.info("[CDP] Successfully connected to Chrome DevTools Protocol.")
            return True
        except Exception as e:
            logger.error(f"[CDP] WebSocket connection to {ws_url} failed: {e}")
            self._connected = False
            return False

    async def send_command(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Sends a JSON-RPC command over CDP and returns the response."""
        if not self.is_connected:
            raise RuntimeError("CDP client is not connected.")

        current_id = self._msg_id
        self._msg_id += 1

        payload = {
            "id": current_id,
            "method": method,
            "params": params or {},
        }

        await self._ws.send(json.dumps(payload))

        while True:
            resp_raw = await self._ws.recv()
            resp = json.loads(resp_raw)
            if resp.get("id") == current_id:
                if "error" in resp:
                    raise RuntimeError(f"CDP Error ({method}): {resp['error']}")
                return resp.get("result", {})

    async def evaluate(self, expression: str) -> Any:
        """
        Executes arbitrary JavaScript expression in the current page context.
        """
        result = await self.send_command(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
        val = result.get("result", {})
        return val.get("value")

    async def get_page_text(self) -> str:
        """Extracts visible text content from the document body."""
        js = "document.body ? document.body.innerText : ''"
        text = await self.evaluate(js)
        return str(text or "")

    async def capture_screenshot(self, format: str = "png", quality: Optional[int] = None) -> bytes:
        """Captures a screenshot of the page directly from the Chrome rendering engine without window focus."""
        params: Dict[str, Any] = {"format": format}
        if quality is not None and format in ("jpeg", "webp"):
            params["quality"] = quality
        result = await self.send_command("Page.captureScreenshot", params)
        data_base64 = result.get("data", "")
        import base64
        return base64.b64decode(data_base64)

    async def click_element(self, selector: str) -> bool:
        """Clicks an element in the DOM by CSS selector in the background."""
        js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (el) {{
                el.scrollIntoView({{ behavior: 'instant', block: 'center' }});
                el.click();
                return true;
            }}
            return false;
        }})()
        """
        return bool(await self.evaluate(js))

    async def click_by_text(self, text: str, tag: str = "*") -> bool:
        """Clicks an element containing text in the background."""
        js = f"""
        (() => {{
            const elements = Array.from(document.querySelectorAll({json.dumps(tag)}));
            const target = elements.find(el => el.textContent && el.textContent.trim().toLowerCase().includes({json.dumps(text.lower())}));
            if (target) {{
                target.scrollIntoView({{ behavior: 'instant', block: 'center' }});
                target.click();
                return true;
            }}
            return false;
        }})()
        """
        return bool(await self.evaluate(js))

    async def type_into(self, selector: str, text: str) -> bool:
        """Types text into an input or contenteditable element in the DOM."""
        js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return false;
            el.focus();
            if ('value' in el) {{
                el.value = {json.dumps(text)};
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }} else {{
                el.innerText = {json.dumps(text)};
                el.dispatchEvent(new InputEvent('input', {{ bubbles: true }}));
            }}
            return true;
        }})()
        """
        return bool(await self.evaluate(js))

    async def wait_for_selector(self, selector: str, timeout_seconds: float = 10.0) -> bool:
        """Waits until an element matching the selector appears in the DOM."""
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout_seconds:
            found = await self.evaluate(f"Boolean(document.querySelector({json.dumps(selector)}))")
            if found:
                return True
            await asyncio.sleep(0.5)
        return False

    async def is_page_404(self) -> bool:
        """Detects Instagram 404 or page unavailable states in the DOM."""
        text = await self.get_page_text()
        low = text.lower()
        return any(phrase in low for phrase in [
            "link you followed may be broken",
            "page isn't available",
            "sorry, this page isn't available",
            "przepraszamy, ta strona jest niedostępna",
        ])

    async def navigate(self, url: str) -> None:
        """Navigates the tab to a URL."""
        await self.send_command("Page.navigate", {"url": url})

    async def close(self) -> None:
        """Closes the WebSocket connection."""
        if self._ws:
            await self._ws.close()
            self._ws = None
        self._connected = False
        logger.info("[CDP] Closed CDP connection.")
