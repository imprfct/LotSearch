"""Utilities for notifying administrators about critical errors."""
from __future__ import annotations

import asyncio
import logging
import sys
import traceback
from datetime import UTC, datetime
from typing import Sequence

from aiogram import Bot


MAX_ALERT_LENGTH = 3500


async def send_critical_alert(bot: Bot, admin_chat_ids: Sequence[int], message: str, tag_user: str | None = None) -> None:
    """Send critical alert to all admins, optionally tagging a user.
    
    Args:
        bot: Telegram bot instance
        admin_chat_ids: List of admin chat IDs
        message: Alert message to send
        tag_user: Optional username to tag (e.g., "@imprfctone")
    """
    if not admin_chat_ids:
        return
    
    full_message = f"🚨 <b>КРИТИЧЕСКИЙ АЛЕРТ</b>\n\n{message}"
    if tag_user:
        full_message += f"\n\n{tag_user}"
    
    for chat_id in admin_chat_ids:
        try:
            await bot.send_message(chat_id, full_message, parse_mode="HTML")
        except Exception as exc:
            sys.stderr.write(f"Failed to send critical alert to {chat_id}: {exc!r}\n")


class AdminAlertHandler(logging.Handler):
    """Logging handler that forwards error messages to Telegram admins."""

    def __init__(
        self,
        bot: Bot,
        admin_chat_ids: Sequence[int],
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        super().__init__(level=logging.ERROR)
        self._bot = bot
        self._admin_chat_ids = tuple(admin_chat_ids)
        self._loop = loop
        self.setFormatter(logging.Formatter("%(message)s"))

    async def _notify(self, message: str) -> None:
        if not self._admin_chat_ids:
            return

        for chat_id in self._admin_chat_ids:
            try:
                await self._bot.send_message(chat_id, message)
            except Exception as exc:  # pragma: no cover - best-effort logging
                sys.stderr.write(
                    f"Failed to notify admin {chat_id}: {exc!r}\n"
                )

    def _build_message(self, record: logging.LogRecord) -> str:
        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S %Z")
        location = f"{record.pathname}:{record.lineno}"

        if record.exc_info:
            details = "".join(traceback.format_exception(*record.exc_info))
        elif record.stack_info:
            details = record.stack_info
        else:
            details = self.format(record)

        details = details[-MAX_ALERT_LENGTH:]
        header = (
            f"⚠️ Ошибка уровня {record.levelname}\n"
            f"Время: {timestamp}\n"
            f"Логгер: {record.name}\n"
            f"Источник: {location}\n\n"
        )
        return f"{header}{details}"

    def emit(self, record: logging.LogRecord) -> None:
        if not self._admin_chat_ids or record.levelno < logging.ERROR:
            return

        message = self._build_message(record)
        coroutine = self._notify(message)

        loop = self._loop
        if loop is None or loop.is_closed():
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

        if loop and loop.is_running():
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None

            if current_loop is loop:
                loop.call_soon(asyncio.create_task, coroutine)
            else:
                loop.call_soon_threadsafe(asyncio.create_task, coroutine)
        else:
            asyncio.run(coroutine)


__all__ = ["AdminAlertHandler", "MAX_ALERT_LENGTH", "send_critical_alert"]
