from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from config import settings
from models import Item
from services.monitor import Monitor


@pytest.mark.asyncio
async def test_monitor_first_run_sends_single_notification(temp_db):
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

    assert monitor._send_notification.await_count == 1
    sent_item = monitor._send_notification.await_args_list[0].args[0]
    assert sent_item.url == items[0].url

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
