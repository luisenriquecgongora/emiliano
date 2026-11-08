"""
Windows UI Automation & Screen Perception Module.
Extracts structured UI tree elements (buttons, inputs) and captures high-resolution screenshots
with DPI-aware coordinate normalization and window inspection.
"""

from __future__ import annotations

import sys
import ctypes
from ctypes import wintypes
from typing import Dict, List, Optional
from PIL import Image, ImageGrab
from loguru import logger

from .pinning import WindowPinManager
from .uia import UiaReader

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    try:
        # Per-monitor DPI awareness V2
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


class ScreenPerceiver:
    def __init__(self, pin_manager: Optional[WindowPinManager] = None, uia_reader: Optional[UiaReader] = None):
        self.pin_manager = pin_manager or WindowPinManager()
        self._user32 = ctypes.windll.user32 if IS_WINDOWS else None
        self._uia = uia_reader or (UiaReader() if IS_WINDOWS else None)

    def capture_screenshot(self, bbox: Optional[tuple] = None) -> Image.Image:
        """Captures primary or multi-monitor display."""
        try:
            return ImageGrab.grab(bbox=bbox)
        except Exception as e:
            logger.error(f"[Perception] Screenshot failed: {e}")
            raise

    def list_windows(self) -> List[Dict]:
        """
        Lists all visible top-level windows on the desktop with their HWND, title, and bounds.
        """
        if not self._user32:
            return []

        windows: List[Dict] = []
        try:
            hdesk = self._user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_ENUMERATE
            enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

            def _cb(hwnd: int, _: int) -> bool:
                if self._user32.IsWindowVisible(hwnd):
                    length = self._user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        self._user32.GetWindowTextW(hwnd, buff, length + 1)
                        title = buff.value.strip()
                        if title:
                            rect = wintypes.RECT()
                            self._user32.GetWindowRect(hwnd, ctypes.byref(rect))
                            width = max(0, rect.right - rect.left)
                            height = max(0, rect.bottom - rect.top)
                            if width > 100 and height > 100:  # Skip tiny system hooks
                                windows.append({
                                    "hwnd": int(hwnd),
                                    "title": title,
                                    "bounds": {
                                        "x": int(rect.left),
                                        "y": int(rect.top),
                                        "width": width,
                                        "height": height,
                                    },
                                    "is_pinned": (self.pin_manager.pinned_hwnd == hwnd),
                                })
                return True

            self._user32.EnumDesktopWindows(hdesk, enum_proc(_cb), 0)
        except Exception as e:
            logger.error(f"[Perception] Failed to enumerate windows: {e}")

        return windows

    def get_ui_elements(self, hwnd: Optional[int] = None) -> List[Dict]:
        """
        Extracts actionable UI elements (buttons, edits, panels) from the target window.
        Defaults to pinned window or active foreground window.
        Uses UI Automation, which sees inside browsers and modern apps; falls back to Win32
        child windows when UIA is unavailable or finds nothing.
        """
        elements: List[Dict] = []
        if not self._user32:
            return elements

        target_hwnd = hwnd or self.pin_manager.pinned_hwnd or self._user32.GetForegroundWindow()
        if not target_hwnd or not self._user32.IsWindow(target_hwnd):
            return elements

        # Get parent window bounds
        parent_rect = wintypes.RECT()
        self._user32.GetWindowRect(target_hwnd, ctypes.byref(parent_rect))
        parent_title = self.pin_manager.get_window_title(target_hwnd)

        elements.append({
            "hwnd": int(target_hwnd),
            "name": parent_title or "Target Window",
            "role": "Window",
            "class": "TopLevelWindow",
            "bounds": {
                "x": int(parent_rect.left),
                "y": int(parent_rect.top),
                "width": max(0, int(parent_rect.right - parent_rect.left)),
                "height": max(0, int(parent_rect.bottom - parent_rect.top)),
            },
            "action": "focus",
        })

        uia_elements = self._uia.elements(target_hwnd) if self._uia else None
        if uia_elements:
            elements.extend(uia_elements)
            return elements

        try:
            enum_child_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

            def _child_cb(child_hwnd: int, _: int) -> bool:
                if self._user32.IsWindowVisible(child_hwnd):
                    # Get class name
                    cls_buff = ctypes.create_unicode_buffer(256)
                    self._user32.GetClassNameW(child_hwnd, cls_buff, 256)
                    cls_name = cls_buff.value

                    # Get control text
                    text_len = self._user32.GetWindowTextLengthW(child_hwnd)
                    text_buff = ctypes.create_unicode_buffer(text_len + 1)
                    if text_len > 0:
                        self._user32.GetWindowTextW(child_hwnd, text_buff, text_len + 1)
                    control_text = text_buff.value.strip()

                    # Get bounding box
                    child_rect = wintypes.RECT()
                    self._user32.GetWindowRect(child_hwnd, ctypes.byref(child_rect))
                    width = max(0, child_rect.right - child_rect.left)
                    height = max(0, child_rect.bottom - child_rect.top)

                    if width > 0 and height > 0:
                        # Map common Win32 control classes to roles
                        role = "Control"
                        action = "click"
                        if "button" in cls_name.lower():
                            role = "Button"
                        elif "edit" in cls_name.lower():
                            role = "TextInput"
                            action = "type"
                        elif "list" in cls_name.lower() or "combo" in cls_name.lower():
                            role = "List"
                            action = "select"

                        elements.append({
                            "hwnd": int(child_hwnd),
                            "name": control_text or cls_name,
                            "role": role,
                            "class": cls_name,
                            "bounds": {
                                "x": int(child_rect.left),
                                "y": int(child_rect.top),
                                "width": width,
                                "height": height,
                            },
                            "action": action,
                        })
                return True

            self._user32.EnumChildWindows(target_hwnd, enum_child_proc(_child_cb), 0)
        except Exception as e:
            logger.debug(f"[Perception] Child element inspection notice: {e}")

        return elements
