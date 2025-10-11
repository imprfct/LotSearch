"""Monitoring service for tracking new items."""
from __future__ import annotations

import asyncio
import logging
from html import escape

from aiogram import Bot

from config import settings
from models import Item
from services.parser import Parser
from services.storage import ItemRepository, TrackedPageRepository

logger = logging.getLogger(__name__)


class Monitor:
    """Monitor for checking new items on websites."""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.parser = Parser()
        self.repository = ItemRepository()
        self.tracked_pages = TrackedPageRepository()
    
    async def check_new_items(self) -> None:
        """Check all monitored URLs for new items and send notifications."""
        logger.info("Starting monitoring check…")

        urls = self.tracked_pages.get_enabled_urls()
        for url in urls:
            try:
                await self._check_url(url)
            except Exception:
                logger.exception("Error checking URL %s", url)
    
    async def _check_url(self, url: str) -> None:
        """Check a specific URL for new items."""
        logger.info("Checking URL: %s", url)

        loop = asyncio.get_running_loop()
        current_items = await loop.run_in_executor(None, self.parser.get_items_from_url, url)

        if self.parser.last_error is not None:
            logger.warning("Skipping %s due to fetch error: %s", url, self.parser.last_error)
            return

        if not current_items:
            logger.warning("No items found at %s", url)
            return

        known_urls = self.repository.get_known_urls(source_url=url)

        if not known_urls:
            self.repository.save_items(current_items, source_url=url)
            logger.info(
                "Seeded %s existing items for %s; notifications skipped on first run",
                len(current_items),
                url,
            )
            return

        new_items = [item for item in current_items if item.url not in known_urls]

        for item in new_items:
            await self._send_notification(item)

        notified = len(new_items)

        self.repository.save_items(current_items, source_url=url)
        logger.info("Found %s new items at %s", len(new_items), url)
        logger.info("Sent %s notifications for %s", notified, url)
    
    async def _send_notification(self, item: Item) -> None:
        """Send notification about new item to all admins."""
        title = escape(item.title)
        price = escape(str(item.price))
        url = escape(item.url, quote=True)

        caption = (
            f"🆕 <b>{title}</b>\n"
            f"Цена: {price}\n"
            f"🔗 <a href=\"{url}\">{url}</a>"
        )

        for chat_id in settings.ADMIN_CHAT_IDS:
            try:
                if item.img_url:
                    await self.bot.send_photo(
                        chat_id=chat_id,
                        photo=item.img_url,
                        caption=caption,
                        parse_mode='HTML'
                    )
                else:
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=caption,
                        parse_mode='HTML'
                    )
                logger.info("Notification sent to %s for: %s", chat_id, item.title)
            except Exception:
                logger.exception("Error sending notification to %s for %s", chat_id, item.title)
