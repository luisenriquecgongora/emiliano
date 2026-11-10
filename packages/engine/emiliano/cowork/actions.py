"""
OS Action Synthesizer for Desktop Cowork.
Executes mouse movements, clicks, typing, and window focus with safety guardrails,
HWND window pinning, and 400ms shadow countdown previews.
"""

from __future__ import annotations

import time
from typing import Callable, Optional
from loguru import logger

from .pinning import WindowPinManager, SafetyInterruptedError
from .uia import UiaReader


def _pyautogui():
    """Import pyautogui on first use: it needs a display, so a module-level
    import breaks the engine (and its tests) on headless machines."""
    import pyautogui

    # Set safety settings for pyautogui
    pyautogui.FAILSAFE = True  # Moving cursor to any screen corner triggers FailSafeException
    pyautogui.PAUSE = 0.05     # 50ms pause between actions
    return pyautogui


class ActionSynthesizer:
    def __init__(
        self,
        pin_manager: Optional[WindowPinManager] = None,
        uia_reader: Optional[UiaReader] = None,
        ghost_mode: bool = True,
    ):
        self._paused = False
        self.pin_manager = pin_manager or WindowPinManager()
        self.uia_reader = uia_reader
        self.ghost_mode = ghost_mode
        self.preview_delay_seconds: float = 0.4  # 400ms safety preview window

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        logger.info(f"[Action] Synthesizer paused state set to {paused}")

    def is_paused(self) -> bool:
        return self._paused

    def click(
        self,
        x: float,
        y: float,
        button: str = "left",
        clicks: int = 1,
        on_preview: Optional[Callable[[float, float, float], None]] = None,
    ) -> None:
        """
        Executes a synthetic click with HWND safety checks and shadow countdown.

        Args:
            x: Target X coordinate
            y: Target Y coordinate
            button: 'left', 'right', or 'middle'
            clicks: Number of clicks
            on_preview: Optional callback(x, y, remaining_seconds) before clicking
        """
        if self._paused:
            logger.warning("[Action] Aborted click: synthesizer is currently paused.")
            raise SafetyInterruptedError("Synthesizer is paused")

        # Invariant 1: Target must be inside pinned application window
        if not self.pin_manager.is_point_within_pinned_window(x, y):
            msg = f"Click target ({x}, {y}) is outside pinned window bounds!"
            logger.error(f"[Action] {msg}")
            raise SafetyInterruptedError(msg)

        # Invariant 2: Target window must be in foreground
        if not self.pin_manager.verify_active(auto_focus=True):
            msg = "Target pinned window lost foreground focus and could not be focused!"
            logger.error(f"[Action] {msg}")
            raise SafetyInterruptedError(msg)

        # Check Ghost UIA programmatic invocation (no mouse cursor movement)
        if self.ghost_mode and button == "left" and clicks == 1 and self.uia_reader and self.uia_reader.available:
            if self.uia_reader.invoke_at(int(x), int(y)):
                logger.info(f"[Action] Ghost invoked control at ({x}, {y}) without moving mouse cursor")
                return
            logger.debug(f"[Action] Ghost invoke not supported at ({x}, {y}); falling back to synthetic cursor click")

        # Invariant 3: 400ms Shadow preview countdown (listen for pause/Esc)
        if self.preview_delay_seconds > 0:
            if on_preview:
                on_preview(x, y, self.preview_delay_seconds)

            steps = int(self.preview_delay_seconds / 0.05)
            for _ in range(steps):
                if self._paused:
                    logger.warning("[Action] Action aborted by user during shadow preview window!")
                    raise SafetyInterruptedError("Aborted by user during shadow preview")
                time.sleep(0.05)

        logger.info(f"[Action] Clicking at ({x}, {y}) button={button} clicks={clicks}")
        # Smoothly move to target before clicking for human-like visual tracking
        _pyautogui().moveTo(x, y, duration=0.15)
        _pyautogui().click(x=x, y=y, button=button, clicks=clicks)

    def type_text(
        self,
        text: str,
        x: Optional[float] = None,
        y: Optional[float] = None,
        interval: float = 0.02,
    ) -> None:
        """Types text safely into the pinned active window. Uses ghost SetValue when coordinates are provided."""
        if self._paused:
            logger.warning("[Action] Aborted type: synthesizer is currently paused.")
            raise SafetyInterruptedError("Synthesizer is paused")

        if not self.pin_manager.verify_active(auto_focus=True):
            msg = "Target pinned window lost focus before typing!"
            logger.error(f"[Action] {msg}")
            raise SafetyInterruptedError(msg)

        if self.ghost_mode and x is not None and y is not None and self.uia_reader and self.uia_reader.available:
            if self.pin_manager.is_point_within_pinned_window(x, y):
                if self.uia_reader.set_value_at(int(x), int(y), text):
                    logger.info(f"[Action] Ghost set value on control at ({x}, {y}) without synthetic keystrokes")
                    return
                logger.debug(f"[Action] Ghost set_value not supported at ({x}, {y}); falling back to synthetic keystrokes")

        logger.info(f"[Action] Typing: {text[:20]}... (length={len(text)})")
        _pyautogui().typewrite(text, interval=interval)

    def press_key(self, key: str) -> None:
        """Presses a single key."""
        if self._paused:
            return
        if not self.pin_manager.verify_active(auto_focus=True):
            raise SafetyInterruptedError("Target window lost focus before key press")
        logger.info(f"[Action] Pressing key: {key}")
        _pyautogui().press(key)

    def hotkey(self, *keys: str) -> None:
        """Executes a key combination (e.g. Ctrl+C)."""
        if self._paused:
            return
        if not self.pin_manager.verify_active(auto_focus=True):
            raise SafetyInterruptedError("Target window lost focus before hotkey")
        logger.info(f"[Action] Hotkey: {keys}")
        _pyautogui().hotkey(*keys)
