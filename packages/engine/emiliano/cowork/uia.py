"""
Windows UI Automation (UIA) reader.
Reads a window's control tree through UIAutomationCore (via comtypes): names, control types,
automation IDs and screen bounds. Unlike Win32 child-window enumeration, this sees inside
Chrome, Electron (VS Code), WPF, WinUI and UWP apps, which draw their controls without HWNDs.

All COM calls run on one dedicated thread, which owns the UIA objects, so callers on any thread
(FastAPI's worker pool, the event loop) are safe. A hung target app cannot block the caller for
longer than the timeout.
"""

from __future__ import annotations

import concurrent.futures
import sys
import time
from typing import Any, Dict, List, Optional

from loguru import logger

IS_WINDOWS = sys.platform == "win32"

# UIA property ids (UIAutomationClient.h); fetched in one cross-process call with a cache request
PROPS = {
    "name": 30005,
    "control_type": 30003,
    "bounds": 30001,
    "automation_id": 30011,
    "class_name": 30012,
    "enabled": 30010,
    "offscreen": 30022,
}

# UIA control type ids -> role names. Roles the dock already knew keep their old names.
CONTROL_TYPES = {
    50000: "Button", 50001: "Calendar", 50002: "CheckBox", 50003: "List", 50004: "TextInput",
    50005: "Hyperlink", 50006: "Image", 50007: "ListItem", 50008: "List", 50009: "Menu",
    50010: "MenuBar", 50011: "MenuItem", 50012: "ProgressBar", 50013: "RadioButton",
    50014: "ScrollBar", 50015: "Slider", 50016: "Spinner", 50017: "StatusBar", 50018: "Tab",
    50019: "TabItem", 50020: "Text", 50021: "ToolBar", 50022: "ToolTip", 50023: "Tree",
    50024: "TreeItem", 50025: "Custom", 50026: "Group", 50027: "Thumb", 50028: "DataGrid",
    50029: "DataItem", 50030: "Document", 50031: "SplitButton", 50032: "Window", 50033: "Pane",
    50034: "Header", 50035: "HeaderItem", 50036: "Table", 50037: "TitleBar", 50038: "Separator",
    50039: "SemanticZoom", 50040: "AppBar",
}

# Containers and decoration: listed only when they have a name, since unnamed ones are noise
STRUCTURAL = {"Pane", "Group", "Custom", "Separator", "Thumb", "ScrollBar", "TitleBar", "ToolTip", "Image"}

ACTIONS = {"TextInput": "type", "Document": "type", "List": "select", "Window": "focus"}

# Chromium and Electron apps build their accessibility tree only after the first UIA request,
# so the first read of such a window finds almost nothing; read it again after this pause
CHROMIUM_CLASS_PREFIX = "Chrome_WidgetWin"
CHROMIUM_WARMUP_S = 0.5

DEFAULT_TIMEOUT_S = 5.0
DEFAULT_MAX_ELEMENTS = 400


def to_element(raw: Dict[str, Any], hwnd: int) -> Optional[Dict[str, Any]]:
    """Turns raw UIA properties into the dock's element shape, or None to skip the element."""
    left, top, right, bottom = raw["bounds"]
    width, height = max(0, right - left), max(0, bottom - top)
    if raw.get("offscreen") or width == 0 or height == 0:
        return None
    role = CONTROL_TYPES.get(raw["control_type"], "Control")
    name = (raw.get("name") or "").strip()
    if role in STRUCTURAL and not name:
        return None
    return {
        "hwnd": int(hwnd),
        "name": name or raw.get("automation_id") or role,
        "role": role,
        "class": raw.get("class_name") or "",
        "automation_id": raw.get("automation_id") or "",
        "enabled": bool(raw.get("enabled", True)),
        "bounds": {"x": int(left), "y": int(top), "width": int(width), "height": int(height)},
        "action": ACTIONS.get(role, "click"),
        "source": "uia",
    }


class UiaReader:
    """Reads UI elements of a window through UI Automation. Windows only."""

    def __init__(self) -> None:
        self._executor: Optional[concurrent.futures.ThreadPoolExecutor] = None
        self._uia = None
        self._mod = None
        self._cache_request = None
        self._warmed: set = set()  # Chromium windows already read once
        self._unavailable: Optional[str] = None if IS_WINDOWS else "not Windows"

    @property
    def available(self) -> bool:
        return self._unavailable is None

    def elements(self, hwnd: int, max_elements: int = DEFAULT_MAX_ELEMENTS,
                 timeout: float = DEFAULT_TIMEOUT_S) -> Optional[List[Dict[str, Any]]]:
        """Elements of the window, or None when UIA is unavailable, fails or times out."""
        if not self.available:
            return None
        if self._executor is None:
            self._executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="uia", initializer=_co_initialize)
        try:
            future = self._executor.submit(self._read, int(hwnd), max_elements)
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            # The worker stays busy until the target app answers; later calls queue behind it
            logger.warning(f"[UIA] Reading HWND={hwnd} timed out after {timeout}s")
        except Exception as e:
            logger.warning(f"[UIA] Reading HWND={hwnd} failed: {e}")
        return None

    def close(self) -> None:
        """Shuts down the background UIA worker executor."""
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    def __del__(self) -> None:
        self.close()

    # --- runs on the UIA thread -----------------------------------------------------------

    def _ensure(self) -> bool:
        if self._uia is not None:
            return True
        try:
            import comtypes.client as cc

            self._mod = cc.GetModule("UIAutomationCore.dll")
            self._uia = cc.CreateObject(self._mod.CUIAutomation, interface=self._mod.IUIAutomation)
            request = self._uia.CreateCacheRequest()
            for prop_id in PROPS.values():
                request.AddProperty(prop_id)
            self._cache_request = request
            return True
        except Exception as e:  # comtypes missing, or UIA not registered
            self._unavailable = str(e)
            logger.warning(f"[UIA] UI Automation unavailable, using Win32 fallback: {e}")
            return False

    def _read(self, hwnd: int, max_elements: int) -> Optional[List[Dict[str, Any]]]:
        if not self._ensure():
            return None
        root = self._uia.ElementFromHandle(hwnd)
        if hwnd not in self._warmed and (root.CurrentClassName or "").startswith(CHROMIUM_CLASS_PREFIX):
            self._warmed.add(hwnd)
            root.FindAllBuildCache(self._mod.TreeScope_Children, self._uia.ControlViewCondition, self._cache_request)
            time.sleep(CHROMIUM_WARMUP_S)
        found = root.FindAllBuildCache(self._mod.TreeScope_Descendants, self._uia.ControlViewCondition,
                                       self._cache_request)
        elements: List[Dict[str, Any]] = []
        for i in range(found.Length):
            el = found.GetElement(i)
            rect = el.CachedBoundingRectangle
            item = to_element({
                "name": el.CachedName,
                "control_type": el.CachedControlType,
                "bounds": (rect.left, rect.top, rect.right, rect.bottom),
                "automation_id": el.CachedAutomationId,
                "class_name": el.CachedClassName,
                "enabled": el.CachedIsEnabled,
                "offscreen": el.CachedIsOffscreen,
            }, hwnd)
            if item:
                elements.append(item)
                if len(elements) >= max_elements:
                    break
        return elements


def _co_initialize() -> None:
    """Initializes COM on the UIA thread. Importing comtypes may already have done it (in a
    different mode), which COM reports as an error; any mode works for reading UIA."""
    try:
        import comtypes

        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
    except Exception:
        pass
