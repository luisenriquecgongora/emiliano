"""
Telegram Gateway Adapter for Emiliano Desktop Engine.
Allows the user to query status, trigger background outreach, and review skills from mobile.
"""

from __future__ import annotations

import asyncio
import os
import urllib.request
import json
from typing import Any, Dict, Optional
from loguru import logger

from .base import BaseGateway


class TelegramGateway(BaseGateway):
    """Long-polling Telegram Bot gateway adapter."""

    def __init__(self, token: Optional[str] = None, allowed_chat_id: Optional[str] = None):
        super().__init__(name="telegram")
        self.token = token or os.environ.get("EMILIANO_TELEGRAM_BOT_TOKEN")
        self.allowed_chat_id = allowed_chat_id or os.environ.get("EMILIANO_TELEGRAM_CHAT_ID")
        self._poll_task: Optional[asyncio.Task] = None
        self._last_update_id = 0

    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.allowed_chat_id)

    async def start(self) -> None:
        if not self.is_configured:
            logger.info("[TelegramGateway] Bot token or allowed chat ID not configured. Gateway in standby.")
            return

        self.is_running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(f"[TelegramGateway] Gateway listener started (authorized chat_id: {self.allowed_chat_id}).")

    async def stop(self) -> None:
        self.is_running = False
        if self._poll_task:
            self._poll_task.cancel()
            self._poll_task = None
        logger.info("[TelegramGateway] Gateway listener stopped.")

    async def send_notification(self, recipient_id: str, message: str) -> bool:
        if not self.is_configured:
            return False
        chat_id = recipient_id or self.allowed_chat_id
        if not chat_id:
            return False

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception as e:
            logger.warning(f"[TelegramGateway] Failed to send message: {e}")
            return False

    async def _poll_loop(self) -> None:
        """Polls Telegram getUpdates API for incoming commands."""
        while self.is_running:
            try:
                url = f"https://api.telegram.org/bot{self.token}/getUpdates?offset={self._last_update_id + 1}&timeout=20"
                req = urllib.request.Request(url)
                # Run off the async event loop to avoid blocking
                data = await asyncio.to_thread(self._fetch_updates, req)
                if data and data.get("ok"):
                    for update in data.get("result", []):
                        self._last_update_id = update["update_id"]
                        msg = update.get("message", {})
                        text = msg.get("text", "").strip()
                        chat_id = str(msg.get("chat", {}).get("id", ""))

                        if not self.allowed_chat_id or chat_id != str(self.allowed_chat_id):
                            logger.warning(f"[TelegramGateway] Unauthorized access attempt from chat_id: {chat_id}")
                            continue

                        if text.startswith("/"):
                            await self._handle_command(chat_id, text)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[TelegramGateway] Polling error: {e}")
                await asyncio.sleep(5)

    def _fetch_updates(self, req: urllib.request.Request) -> Optional[Dict[str, Any]]:
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                return json.loads(resp.read().decode())
        except Exception:
            return None

    async def _handle_command(self, chat_id: str, raw_text: str):
        parts = raw_text.split()
        cmd = parts[0].lstrip("/").lower()
        args = parts[1:]

        if cmd in self._command_handlers:
            reply = await self._command_handlers[cmd](chat_id, args)
            if reply:
                await self.send_notification(chat_id, reply)
        elif cmd == "status":
            await self.send_notification(chat_id, "⚡ *Emiliano Engine*: Online\n🖥 *Desktop Cowork*: Ready\n🌐 *Extension Bridge*: Connected")
        elif cmd == "help":
            await self.send_notification(chat_id, "📖 *Available Commands*:\n/status - Engine status\n/skills - Active skill registry\n/crm - Outreach metrics")
