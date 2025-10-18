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
from services.alerts import send_critical_alert

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
        "",
    ]

    if tracking_label:
        tracking = escape(tracking_label)
        if tracking_url:
            url_ref = escape(tracking_url, quote=True)
            lines.append(f"📰 Страница: <a href=\"{url_ref}\"><b>{tracking}</b></a>")
        else:
            lines.append(f"📰 Страница: <b>{tracking}</b>")
        lines.append("")

    lines.extend([price_line, ""])

    # Check if we have description content
    has_table = bool(item.description_table and len(item.description_table) > 0)
    has_text = bool(item.description_text and item.description_text.strip())
    has_any_description = has_table or has_text
    
    # Only show description section if we have table AND text, or just text
    # If only table - show it without header and top separator
    if has_any_description:
        # Show header and top separator only if we have text (with or without table)
        if has_text:
            lines.append("━━━━━━━━━━━━━━━━━━")
            lines.append("<b>📋 Описание лота</b>")
            lines.append("")
        
        # Add table if available
        if has_table and item.description_table:
            for key, value in item.description_table.items():
                key_escaped = escape(key)
                value_escaped = escape(value)
                lines.append(f"<b>{key_escaped}:</b> {value_escaped}")
            lines.append("")
        
        # Add description text if available
        if has_text and item.description_text:
            desc_escaped = escape(item.description_text)
            # Limit description length to avoid message being too long
            max_desc_length = 400
            was_truncated = len(desc_escaped) > max_desc_length
            if was_truncated:
                desc_escaped = desc_escaped[:max_desc_length].rstrip() + "..."
            
            lines.append(f"<i>{desc_escaped}</i>")
            
            if was_truncated:
                lines.append("")
                lines.append("💬 <i>Описание обрезано. Полный текст на странице лота.</i>")
        
        # Always add bottom separator if we have any description
        lines.append("━━━━━━━━━━━━━━━━━━")
        lines.append("")

    lines.append(f"🌐 <a href=\"{url}\">Перейти к лоту</a>")

    return "\n".join(lines)


class Monitor:
    """Monitor for checking new items on websites."""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.parser = Parser()
        self.repository = ItemRepository()
        self.tracked_pages = TrackedPageRepository()
        self._chat_locks: dict[int, asyncio.Lock] = {}
        self._failed_pages: dict[str, list[float]] = {}
        self._max_retry_attempts = 3
        self._retry_backoff_minutes = 5
    
    async def check_new_items(self) -> None:
        """Check all monitored URLs for new items and send notifications."""
        logger.info("Starting monitoring check…")
        
        total_pages = 0
        successful_pages = 0
        failed_pages = 0

        pages = self.tracked_pages.get_enabled_pages()
        for page in pages:
            total_pages += 1
            try:
                success = await self._check_url(page.url, page.label)
                if success:
                    successful_pages += 1
                    if page.url in self._failed_pages:
                        del self._failed_pages[page.url]
                        logger.info("✅ Page %s recovered after previous failures", page.url)
                else:
                    failed_pages += 1
                    self._track_failure(page.url)
            except asyncio.CancelledError:
                logger.info("Monitoring task cancelled for %s (bot shutdown)", page.url)
                raise
            except Exception as exc:
                failed_pages += 1
                self._track_failure(page.url)
                logger.exception("Error checking URL %s", page.url)
                error_msg = (
                    f"⚠️ Критическая ошибка при проверке страницы!\n\n"
                    f"URL: {page.url}\n"
                    f"Метка: {page.label or 'Нет'}\n"
                    f"Ошибка: {exc}\n\n"
                    f"Проверка провалена, монеты могли быть упущены!"
                )
                await send_critical_alert(self.bot, settings.ADMIN_CHAT_IDS, error_msg, tag_user="@imprfctone")
        
        logger.info(
            "Monitoring check completed: %d total, %d successful, %d failed",
            total_pages, successful_pages, failed_pages
        )
    
    def _track_failure(self, url: str) -> None:
        """Track page load failure."""
        import time
        if url not in self._failed_pages:
            self._failed_pages[url] = []
        self._failed_pages[url].append(time.time())
        
        # Keep only recent failures
        cutoff = time.time() - (self._retry_backoff_minutes * 60 * self._max_retry_attempts)
        self._failed_pages[url] = [t for t in self._failed_pages[url] if t > cutoff]
        
        failure_count = len(self._failed_pages[url])
        if failure_count >= self._max_retry_attempts:
            logger.error(
                "❌ Page %s has failed %d times in a row - may need attention!",
                url, failure_count
            )
    
    async def _check_url(self, url: str, tracking_label: str | None = None) -> bool:
        """Check a specific URL for new items. Returns True if successful."""
        logger.info("Checking URL: %s", url)

        loop = asyncio.get_running_loop()
        current_items = await loop.run_in_executor(None, self.parser.get_items_from_url, url)

        if self.parser.last_page_load_failed:
            error_msg = (
                f"⚠️ Не удалось загрузить страницу мониторинга!\n\n"
                f"URL: {url}\n"
                f"Ошибка: {self.parser.last_error}\n\n"
                f"Проверка пропущена, монеты могли быть упущены!"
            )
            await send_critical_alert(self.bot, settings.ADMIN_CHAT_IDS, error_msg, tag_user="@imprfctone")
            logger.warning("Skipping %s due to page fetch error: %s", url, self.parser.last_error)
            return False

        if not current_items:
            logger.warning("No items found at %s", url)
            return False

        # Check for gallery load errors after all retries exhausted
        if self.parser.gallery_load_errors:
            error_details = "\n".join(
                f"- {item_url}: {exc}" 
                for item_url, exc in self.parser.gallery_load_errors[:5]
            )
            if len(self.parser.gallery_load_errors) > 5:
                error_details += f"\n... и ещё {len(self.parser.gallery_load_errors) - 5}"
            
            error_msg = (
                f"⚠️ Ошибки загрузки галерей после всех retry!\n\n"
                f"Страница: {url}\n"
                f"Метка: {tracking_label or 'Нет'}\n"
                f"Ошибок: {len(self.parser.gallery_load_errors)}\n\n"
                f"Детали:\n{error_details}\n\n"
                f"⚠️ Монеты сохранены, но могут быть без полных галерей"
            )
            await send_critical_alert(self.bot, settings.ADMIN_CHAT_IDS, error_msg, tag_user="@imprfctone")


        known_urls = self.repository.get_known_urls(source_url=url)

        if not known_urls:
            self.repository.save_items(current_items, source_url=url)
            logger.info(
                "Seeded %s existing items for %s; notifications skipped on first run",
                len(current_items),
                url,
            )
            return True

        new_items = [item for item in current_items if item.url not in known_urls]

        for item in new_items:
            await self._send_notification(item, tracking_label, url)

        notified = len(new_items)

        self.repository.save_items(current_items, source_url=url)
        logger.info("Found %s new items at %s", len(new_items), url)
        
        return True
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
                await self._alert_notification_failure(chat_id, item, f"Telegram Bad Request: {exc}")
                return
            except Exception as exc:
                logger.exception("Error sending notification to %s for %s", chat_id, item.title)
                await self._alert_notification_failure(chat_id, item, f"Неожиданная ошибка: {exc}")
                return
        logger.error("Failed to send notification to %s for %s after retries", chat_id, item.title)
        await self._alert_notification_failure(chat_id, item, "Исчерпаны все попытки отправки")
    
    async def _alert_notification_failure(self, chat_id: int, item: Item, reason: str) -> None:
        """Send critical alert when notification delivery fails."""
        error_msg = (
            f"⚠️ Не удалось отправить уведомление о новой монете!\n\n"
            f"Чат: {chat_id}\n"
            f"Монета: {item.title}\n"
            f"URL: {item.url}\n"
            f"Причина: {reason}"
        )
        await send_critical_alert(self.bot, settings.ADMIN_CHAT_IDS, error_msg, tag_user="@imprfctone")

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
