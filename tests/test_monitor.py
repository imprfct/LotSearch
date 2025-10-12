from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import requests

from config import settings
from models import Item
from services.monitor import Monitor


@pytest.mark.asyncio
async def test_monitor_first_run_seeds_without_notifications(temp_db):
    bot = AsyncMock()
    monitor = Monitor(bot)

    items = [
        Item(url="https://example.com/lot3", title="Lot 3", price="300", img_url="https://example.com/img3"),
        Item(url="https://example.com/lot2", title="Lot 2", price="200", img_url="https://example.com/img2"),
        Item(url="https://example.com/lot1", title="Lot 1", price="100", img_url="https://example.com/img1"),
    ]

    monitor.parser.get_items_from_url = lambda url: items
    monitor._send_notification = AsyncMock()

    await monitor._check_url(settings.MONITOR_URLS[0])

    monitor._send_notification.assert_not_awaited()

    stored_urls = monitor.repository.get_known_urls(source_url=settings.MONITOR_URLS[0])
    assert stored_urls == {item.url for item in items}


@pytest.mark.asyncio
async def test_monitor_detects_new_items(temp_db):
    bot = AsyncMock()
    monitor = Monitor(bot)

    initial_items = [
        Item(url="https://example.com/lot3", title="Lot 3", price="300", img_url="https://example.com/img3"),
        Item(url="https://example.com/lot2", title="Lot 2", price="200", img_url="https://example.com/img2"),
    ]

    updated_items = [
        Item(url="https://example.com/lot4", title="Lot 4", price="400", img_url="https://example.com/img4"),
        *initial_items,
    ]

    monitor.parser.get_items_from_url = lambda url: initial_items
    monitor._send_notification = AsyncMock()

    await monitor._check_url(settings.MONITOR_URLS[0])

    monitor.parser.get_items_from_url = lambda url: updated_items
    monitor._send_notification.reset_mock()

    await monitor._check_url(settings.MONITOR_URLS[0])

    assert monitor._send_notification.await_count == 1
    sent_item = monitor._send_notification.await_args_list[0].args[0]
    assert sent_item.url == "https://example.com/lot4"

    stored_urls = monitor.repository.get_known_urls(source_url=settings.MONITOR_URLS[0])
    assert stored_urls == {item.url for item in updated_items}


@pytest.mark.asyncio
async def test_monitor_skips_url_on_fetch_error(temp_db):
    bot = AsyncMock()
    monitor = Monitor(bot)

    def failing_fetch(url: str):
        monitor.parser.last_error = requests.ConnectionError("DNS failure")
        return []

    monitor.parser.get_items_from_url = failing_fetch
    monitor._send_notification = AsyncMock()

    await monitor._check_url(settings.MONITOR_URLS[0])

    monitor._send_notification.assert_not_awaited()
    assert monitor.repository.get_known_urls(source_url=settings.MONITOR_URLS[0]) == set()


@pytest.mark.asyncio
async def test_monitor_send_notification_includes_tracking_label(temp_db):
    bot = AsyncMock()
    monitor = Monitor(bot)

    item = Item(
        url="https://example.com/lot10",
        title="Lot 10",
        price="1000",
        img_url="https://example.com/img10",
    )
    tracking_label = "Coins Tracking"

    await monitor._send_notification(item, tracking_label)

    assert bot.send_photo.await_count == len(settings.ADMIN_CHAT_IDS)
    assert bot.send_media_group.await_count == 0
    assert bot.send_message.await_count == 0

    for call in bot.send_photo.await_args_list:
        kwargs = call.kwargs
        assert "Отслеживаемая страница: <b>Coins Tracking</b>" in kwargs["caption"]


@pytest.mark.asyncio
async def test_monitor_sends_album_when_multiple_images(temp_db):
    bot = AsyncMock()
    monitor = Monitor(bot)

    item = Item(
        url="https://example.com/lot11",
        title="Lot 11",
        price="1100",
        img_url="https://example.com/thumb11",
        image_urls=(
            "https://example.com/full11a",
            "https://example.com/full11b",
            "https://example.com/full11c",
        ),
    )

    await monitor._send_notification(item, None)

    assert bot.send_media_group.await_count == len(settings.ADMIN_CHAT_IDS)
    assert bot.send_photo.await_count == 0
    assert bot.send_message.await_count == 0

    for call in bot.send_media_group.await_args_list:
        kwargs = call.kwargs
        media = kwargs["media"]
        assert len(media) == len(item.image_urls)
        assert media[0].caption and "Lot 11" in media[0].caption
