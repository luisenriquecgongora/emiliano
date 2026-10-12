"""
OS Action Synthesizer for Desktop Cowork.
Executes mouse movements, clicks, typing, and window focus with safety guardrails.
"""

from __future__ import annotations

import time
from typing import Optional
from loguru import logger
import pyautogui

# Set safety settings for pyautogui
pyautogui.FAILSAFE = True  # Moving cursor to any screen corner triggers FailSafeException
pyautogui.PAUSE = 0.05     # 50ms pause between actions


class ActionSynthesizer:
    def __init__(self):
        self._paused = False

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        logger.info(f"[Action] Synthesizer paused state set to {paused}")

    def click(self, x: float, y: float, button: str = "left", clicks: int = 1) -> None:
        if self._paused:
            logger.warning("[Action] Aborted click: synthesizer is currently paused.")
            return
        logger.info(f"[Action] Clicking at ({x}, {y}) button={button} clicks={clicks}")
        # Smoothly move to target before clicking for natural human-like visual tracking
        pyautogui.moveTo(x, y, duration=0.2)
        pyautogui.click(x=x, y=y, button=button, clicks=clicks)

    def type_text(self, text: str, interval: float = 0.02) -> None:
        if self._paused:
            logger.warning("[Action] Aborted type: synthesizer is currently paused.")
            return
        logger.info(f"[Action] Typing: {text[:20]}... (length={len(text)})")
        pyautogui.typewrite(text, interval=interval)

    def press_key(self, key: str) -> None:
        if self._paused:
            return
        logger.info(f"[Action] Pressing key: {key}")
        pyautogui.press(key)

    def hotkey(self, *keys: str) -> None:
        if self._paused:
            return
        logger.info(f"[Action] Hotkey: {keys}")
        pyautogui.hotkey(*keys)
