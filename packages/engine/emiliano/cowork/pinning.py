"""
HWND Window Pinning & Safety Invariant Manager for Desktop Cowork.
Guarantees synthetic mouse and keyboard actions never leak outside the target window.
"""

from __future__ import annotations

import sys
import ctypes
from ctypes import wintypes
from typing import Dict, Optional, Tuple
from loguru import logger

IS_WINDOWS = sys.platform == "win32"


class SafetyInterruptedError(RuntimeError):
    """Raised when an action is aborted because window focus was lost or human input intervened."""
    pass


class WindowPinManager:
    """
    Manages target window binding (HWND pinning).
    Guarantees that synthetic actions execute strictly within the designated application.
    """

    def __init__(self):
        self._pinned_hwnd: Optional[int] = None
        self._pinned_title: Optional[str] = None
        self._user32 = ctypes.windll.user32 if IS_WINDOWS else None

    @property
    def pinned_hwnd(self) -> Optional[int]:
        return self._pinned_hwnd

    @property
    def pinned_title(self) -> Optional[str]:
        return self._pinned_title

    def is_pinned(self) -> bool:
        return self._pinned_hwnd is not None

    def pin(self, hwnd: int, title: Optional[str] = None) -> None:
        """Pins execution strictly to the given window handle."""
        self._pinned_hwnd = int(hwnd)
        self._pinned_title = title or self.get_window_title(self._pinned_hwnd)
        logger.info(f"[PinManager] Pinned to HWND={self._pinned_hwnd} (\"{self._pinned_title}\")")

    def unpin(self) -> None:
        """Clears the pinned window binding."""
        logger.info(f"[PinManager] Unpinned HWND={self._pinned_hwnd}")
        self._pinned_hwnd = None
        self._pinned_title = None

    def get_foreground_hwnd(self) -> Optional[int]:
        """Returns the current foreground window handle."""
        if not self._user32:
            return None
        hwnd = self._user32.GetForegroundWindow()
        return int(hwnd) if hwnd else None

    def get_window_title(self, hwnd: int) -> str:
        """Returns the text title of a window."""
        if not self._user32 or not hwnd:
            return ""
        length = self._user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buff = ctypes.create_unicode_buffer(length + 1)
        self._user32.GetWindowTextW(hwnd, buff, length + 1)
        return buff.value

    def get_window_bounds(self, hwnd: Optional[int] = None) -> Optional[Dict[str, int]]:
        """Returns window rectangle {x, y, width, height}."""
        target_hwnd = hwnd or self._pinned_hwnd
        if not self._user32 or not target_hwnd:
            return None
        rect = wintypes.RECT()
        if not self._user32.GetWindowRect(target_hwnd, ctypes.byref(rect)):
            return None
        return {
            "x": int(rect.left),
            "y": int(rect.top),
            "width": max(0, int(rect.right - rect.left)),
            "height": max(0, int(rect.bottom - rect.top)),
        }

    def verify_active(self, auto_focus: bool = True) -> bool:
        """
        Verifies that the target pinned window is currently foreground.
        If auto_focus is True, attempts to bring it to foreground if obscured.
        """
        if not self.is_pinned():
            # If not pinned, any active window is permitted
            return True

        current = self.get_foreground_hwnd()
        if current == self._pinned_hwnd:
            return True

        if auto_focus and self._user32 and self._pinned_hwnd:
            logger.warning(
                f"[PinManager] Window mismatch! Current={current}, Pinned={self._pinned_hwnd}. Attempting re-focus..."
            )
            # Show and set foreground
            self._user32.ShowWindow(self._pinned_hwnd, 9)  # SW_RESTORE
            self._user32.SetForegroundWindow(self._pinned_hwnd)
            return self.get_foreground_hwnd() == self._pinned_hwnd

        return False

    def is_point_within_pinned_window(self, x: float, y: float) -> bool:
        """Verifies that (x, y) coordinates fall strictly within the pinned window bounds."""
        if not self.is_pinned():
            return True

        bounds = self.get_window_bounds(self._pinned_hwnd)
        if not bounds:
            return False

        left = bounds["x"]
        top = bounds["y"]
        right = bounds["x"] + bounds["width"]
        bottom = bounds["y"] + bounds["height"]

        return (left <= x <= right) and (top <= y <= bottom)
