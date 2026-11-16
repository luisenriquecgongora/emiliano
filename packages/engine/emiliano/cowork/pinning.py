"""
HWND Window Pinning & Safety Invariant Manager for Desktop Cowork.
Guarantees synthetic mouse and keyboard actions never leak outside the target window.
"""

from __future__ import annotations

import sys
import ctypes
from ctypes import wintypes
from typing import Dict, Optional
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
        self._kernel32 = ctypes.windll.kernel32 if IS_WINDOWS else None

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

    def force_foreground(self, hwnd: Optional[int] = None) -> bool:
        """
        Brings target window to the foreground reliably on Windows by attaching thread input
        and simulating an Alt-key toggle to bypass OS foreground locks.
        """
        target_hwnd = hwnd or self._pinned_hwnd
        if not self._user32 or not target_hwnd or not self._user32.IsWindow(target_hwnd):
            return False

        current_fg = self.get_foreground_hwnd()
        if current_fg == target_hwnd:
            return True

        import time

        # 1. Restore if minimized
        if self._user32.IsIconic(target_hwnd):
            self._user32.ShowWindow(target_hwnd, 9)  # SW_RESTORE
        else:
            self._user32.ShowWindow(target_hwnd, 5)  # SW_SHOW

        # 2. Attach thread input workaround to permit SetForegroundWindow from background
        cur_thread = self._kernel32.GetCurrentThreadId() if self._kernel32 else 0
        fg_thread = self._user32.GetWindowThreadProcessId(current_fg, None) if current_fg else 0
        target_thread = self._user32.GetWindowThreadProcessId(target_hwnd, None)

        if self._user32 and cur_thread and target_thread and cur_thread != target_thread:
            self._user32.AttachThreadInput(cur_thread, target_thread, True)
        if self._user32 and fg_thread and target_thread and fg_thread != target_thread:
            self._user32.AttachThreadInput(fg_thread, target_thread, True)

        # 3. Simulate Alt key toggle
        self._user32.keybd_event(0x12, 0, 0, 0)  # VK_MENU (Alt) down
        self._user32.SetForegroundWindow(target_hwnd)
        self._user32.BringWindowToTop(target_hwnd)
        self._user32.keybd_event(0x12, 0, 2, 0)  # VK_MENU (Alt) up

        # Detach thread input
        if self._user32 and cur_thread and target_thread and cur_thread != target_thread:
            self._user32.AttachThreadInput(cur_thread, target_thread, False)
        if self._user32 and fg_thread and target_thread and fg_thread != target_thread:
            self._user32.AttachThreadInput(fg_thread, target_thread, False)

        time.sleep(0.1)
        return self.get_foreground_hwnd() == target_hwnd

    def send_to_background(self, hwnd: Optional[int] = None) -> bool:
        """
        Pushes target window to the bottom of the Z-order without minimizing it,
        so it remains fully accessible on the taskbar and visible if brought forward,
        without taking keyboard or mouse focus away from the user's active apps.
        """
        target_hwnd = hwnd or self._pinned_hwnd
        if not self._user32 or not target_hwnd or not self._user32.IsWindow(target_hwnd):
            return False
        # HWND_BOTTOM = 1, SWP_NOMOVE = 0x0002, SWP_NOSIZE = 0x0001, SWP_NOACTIVATE = 0x0010
        HWND_BOTTOM = 1
        SWP_FLAGS = 0x0001 | 0x0002 | 0x0010
        res = self._user32.SetWindowPos(target_hwnd, HWND_BOTTOM, 0, 0, 0, 0, SWP_FLAGS)
        return bool(res)

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
            return self.force_foreground(self._pinned_hwnd)

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
