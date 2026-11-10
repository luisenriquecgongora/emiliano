"""
Emiliano Desktop Cowork Module: HWND pinning, screen perception, and action synthesis.
"""

from .pinning import WindowPinManager, SafetyInterruptedError
from .perception import ScreenPerceiver
from .actions import ActionSynthesizer
from .uia import UiaReader
from .agent import CoworkAgentLoop

__all__ = [
    "WindowPinManager",
    "SafetyInterruptedError",
    "ScreenPerceiver",
    "ActionSynthesizer",
    "UiaReader",
    "CoworkAgentLoop",
]
