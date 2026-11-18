"""
Emiliano Desktop Cowork Module: HWND pinning, screen perception, and action synthesis.
"""

from .pinning import WindowPinManager, SafetyInterruptedError
from .perception import ScreenPerceiver
from .actions import ActionSynthesizer
from .uia import UiaReader
from .agent import CoworkAgentLoop
from .cdp import ChromeDevToolsClient, find_chrome_executable, list_chrome_profiles, is_cdp_available

__all__ = [
    "WindowPinManager",
    "SafetyInterruptedError",
    "ScreenPerceiver",
    "ActionSynthesizer",
    "UiaReader",
    "CoworkAgentLoop",
    "ChromeDevToolsClient",
    "find_chrome_executable",
    "list_chrome_profiles",
    "is_cdp_available",
]
