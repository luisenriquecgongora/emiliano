"""
Multi-Channel Gateway Infrastructure for Emiliano.
Inspired by Nous Research Hermes Agent messaging gateways (Telegram, Discord, Slack, WhatsApp).
Enables headless, remote control and real-time alerts over WebSocket and external chat protocols.
Licensed under PolyForm Shield 1.0.0.
"""

from __future__ import annotations

import abc
from typing import Any, Callable, Dict, List


class BaseGateway(abc.ABC):
    """Abstract interface for external chat/messaging gateways."""

    def __init__(self, name: str):
        self.name = name
        self.is_running = False
        self._command_handlers: Dict[str, Callable[[str, List[str]], Any]] = {}

    def register_command(self, command: str, handler: Callable[[str, List[str]], Any]):
        """Registers a slash command handler (e.g. '/status')."""
        self._command_handlers[command.lower().lstrip("/")] = handler

    @abc.abstractmethod
    async def start(self) -> None:
        """Starts gateway listener loop."""
        pass

    @abc.abstractmethod
    async def stop(self) -> None:
        """Stops gateway listener."""
        pass

    @abc.abstractmethod
    async def send_notification(self, recipient_id: str, message: str) -> bool:
        """Sends an outbound notification/alert to the user."""
        pass
