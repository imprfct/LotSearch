"""Monitoring service for tracking new items."""
from __future__ import annotations

import asyncio
import logging
import re
from html import escape, unescape

from aiogram import Bot
from aiogram.types import InputMediaPhoto
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)

from config import settings
from models import Item
from services.parser import Parser
from services.storage import ItemRepository, TrackedPageRepository

logger = logging.getLogger(__name__)


def _build_notification_caption(
    item: Item,
    tracking_label: str | None,
    tracking_url: str | None,
) -> str:
    title = escape(item.title)
    url = escape(item.url, quote=True)
    raw_price = (item.price or "").strip()
    has_price = raw_price and raw_price.casefold() != "цена не указана"
    price_value = escape(raw_price) if has_price else "Цена не указана"
    price_line = f"💰 <b>{price_value}</b>" if has_price else "💰 <i>Цена не указана</i>"

    lines = [
        "🔥 <b>Новый лот!</b>",
        f"<b>{title}</b>",
    ]

    if tracking_label:
        tracking = escape(tracking_label)
        if tracking_url:
            url_ref = escape(tracking_url, quote=True)
            lines.append(f"📰 Страница: <a href=\"{url_ref}\"><b>{tracking}</b></a>")
        else:
            lines.append(f"📰 Страница: <b>{tracking}</b>")

    lines.extend(
        [
            "",
            price_line,
            f"🔗 <a href=\"{url}\">Перейти к лоту</a>",
        ]
    )

    return "\n".join(lines)


class Monitor:
    """Monitor for checking new items on websites."""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.parser = Parser()
        self.repository = ItemRepository()
        self.tracked_pages = TrackedPageRepository()
        self._chat_locks: dict[int, asyncio.Lock] = {}
    
    async def check_new_items(self) -> None:
        """Check all monitored URLs for new items and send notifications."""
        logger.info("Starting monitoring check…")

        pages = self.tracked_pages.get_enabled_pages()
        for page in pages:
            try:
                await self._check_url(page.url, page.label)
            except Exception:
                logger.exception("Error checking URL %s", page.url)
    
    async def _check_url(self, url: str, tracking_label: str | None = None) -> None:
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
            await self._send_notification(item, tracking_label, url)

        notified = len(new_items)

        self.repository.save_items(current_items, source_url=url)
        logger.info("Found %s new items at %s", len(new_items), url)
        logger.info("Sent %s notifications for %s", notified, url)
    
    async def _send_notification(
        self,
        item: Item,
        tracking_label: str | None = None,
        tracking_url: str | None = None,
    ) -> None:
        """Send notification about new item to all admins."""
        caption = _build_notification_caption(item, tracking_label, tracking_url)

        raw_urls = getattr(item, "image_urls", None) or ()
        media_urls: list[str] = [url for url in raw_urls if url]
        if not media_urls and item.img_url:
            media_urls = [item.img_url]

        for chat_id in settings.ADMIN_CHAT_IDS:
            lock = self._chat_locks.get(chat_id)
            if lock is None:
                lock = asyncio.Lock()
                self._chat_locks[chat_id] = lock
            async with lock:
                await self._deliver_notification(chat_id, item, media_urls, caption)
                await asyncio.sleep(1.0 if len(media_urls) > 1 else 0.5)

    async def _deliver_notification(
        self,
        chat_id: int,
        item: Item,
        media_urls: list[str],
        caption: str,
    ) -> None:
        attempts = 0
        parse_mode: str | None = "HTML"
        fallback_applied = False
        while attempts < 5:
            attempts += 1
            try:
                await self._send_to_chat(chat_id, media_urls, caption, parse_mode)
                logger.info("Notification sent to %s for: %s", chat_id, item.title)
                return
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after + 1)
            except TelegramForbiddenError:
                logger.warning("Skipping chat %s: bot blocked or chat inaccessible", chat_id)
                return
            except TelegramBadRequest as exc:
                message = exc.message.lower() if exc.message else ""
                if "chat not found" in message:
                    logger.warning("Skipping chat %s: chat not found", chat_id)
                    return
                if "can't parse entities" in message and not fallback_applied:
                    caption = _strip_html(caption)
                    parse_mode = None
                    fallback_applied = True
                    continue
                logger.warning("Bad request when sending to %s: %s", chat_id, exc)
                return
            except Exception:
                logger.exception("Error sending notification to %s for %s", chat_id, item.title)
                return
        logger.error("Failed to send notification to %s for %s after retries", chat_id, item.title)

    async def _send_to_chat(
        self,
        chat_id: int,
        media_urls: list[str],
        caption: str,
        parse_mode: str | None,
    ) -> None:
        if len(media_urls) > 1:
            media_group = []
            for index, media_url in enumerate(media_urls[:10]):
                if index == 0:
                    media_group.append(
                        InputMediaPhoto(
                            media=media_url,
                            caption=caption,
                            parse_mode=parse_mode,
                        )
                    )
                else:
                    media_group.append(InputMediaPhoto(media=media_url))
            await self.bot.send_media_group(
                chat_id=chat_id,
                media=media_group,
            )
            return

        kwargs = {}
        if parse_mode:
            kwargs["parse_mode"] = parse_mode

        if media_urls:
            await self.bot.send_photo(
                chat_id=chat_id,
                photo=media_urls[0],
                caption=caption,
                **kwargs,
            )
            return

        await self.bot.send_message(
            chat_id=chat_id,
            text=caption,
            **kwargs,
        )


def _strip_html(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", "", value)
    return unescape(without_tags)
