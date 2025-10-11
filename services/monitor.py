"""Monitoring service for tracking new items."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from config import settings
from models import Item
from services.parser import Parser

logger = logging.getLogger(__name__)


class Monitor:
    """Monitor for checking new items on websites."""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.parser = Parser()
        self.known_items: set[str] = set()
    
    async def check_new_items(self) -> None:
        """Check all monitored URLs for new items and send notifications."""
        logger.info("Starting monitoring check…")

        for url in settings.MONITOR_URLS:
            try:
                await self._check_url(url)
            except Exception:
                logger.exception("Error checking URL %s", url)
    
    async def _check_url(self, url: str) -> None:
        """Check a specific URL for new items."""
        logger.info("Checking URL: %s", url)

        loop = asyncio.get_running_loop()
        current_items = await loop.run_in_executor(None, self.parser.get_items_from_url, url)

        if not current_items:
            logger.warning("No items found at %s", url)
            return

        new_items = [item for item in current_items if item.url not in self.known_items]

        for item in new_items:
            await self._send_notification(item)

        self.known_items.update(item.url for item in current_items)
        logger.info("Found %s new items at %s", len(new_items), url)
    
    async def _send_notification(self, item: Item) -> None:
        """Send notification about new item to all admins."""
        caption = (
            f"🆕 <b>{item.title}</b>\n"
            f"Цена: {item.price}\n"
            f"🔗 {item.url}"
        )

        for chat_id in settings.ADMIN_CHAT_IDS:
            try:
                await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=item.img_url,
                    caption=caption,
                    parse_mode='HTML'
                )
                logger.info("Notification sent to %s for: %s", chat_id, item.title)
            except Exception as e:
                logger.exception("Error sending notification to %s for %s", chat_id, item.title)
