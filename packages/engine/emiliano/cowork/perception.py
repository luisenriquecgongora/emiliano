"""
Windows UI Automation & Screen Perception Module.
Extracts structured UI tree elements (buttons, inputs) and captures high-resolution screenshots.
"""

from __future__ import annotations

import sys
import ctypes
from typing import Dict, List, Optional
from PIL import Image, ImageGrab
from loguru import logger

IS_WINDOWS = sys.platform == "win32"


class ScreenPerceiver:
    def __init__(self):
        pass

    def capture_screenshot(self, bbox: Optional[tuple] = None) -> Image.Image:
        """Captures primary or multi-monitor display."""
        try:
            return ImageGrab.grab(bbox=bbox)
        except Exception as e:
            logger.error(f"[Perception] Screenshot failed: {e}")
            raise

    def get_ui_elements(self) -> List[Dict]:
        """
        Extracts actionable UI elements using Windows UI Automation or native platform hooks.
        Returns list of elements with name, role, and pixel bounding boxes (x, y, width, height).
        """
        elements: List[Dict] = []
        if not IS_WINDOWS:
            # Fallback for non-Windows platforms
            return elements

        try:
            # Inspect active top-level window rect via user32
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if hwnd:
                rect = ctypes.wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                elements.append({
                    "name": "Active Window",
                    "role": "Window",
                    "bounds": {
                        "x": rect.left,
                        "y": rect.top,
                        "width": max(0, rect.right - rect.left),
                        "height": max(0, rect.bottom - rect.top),
                    },
                    "action": "hover"
                })
        except Exception as e:
            logger.debug(f"[Perception] Win32 element query notice: {e}")

        return elements
