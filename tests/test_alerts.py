import asyncio
import logging
from typing import List, Tuple, cast

import pytest

from aiogram import Bot

from services.alerts import AdminAlertHandler, send_critical_alert


class DummyBot:
    def __init__(self) -> None:
        self.sent: List[Tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, parse_mode: str | None = None) -> None:  # pragma: no cover - exercised in tests
        self.sent.append((chat_id, text))


@pytest.mark.asyncio
async def test_admin_alert_handler_sends_messages() -> None:
    bot = DummyBot()
    handler = AdminAlertHandler(cast(Bot, bot), (1, 2), loop=asyncio.get_running_loop())

    logger = logging.getLogger("test.alerts.sends")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.propagate = False

    logger.critical("Boom")
    await asyncio.sleep(0.01)

    assert len(bot.sent) == 2
    assert bot.sent[0][0] == 1
    assert "Boom" in bot.sent[0][1]

    logger.removeHandler(handler)


@pytest.mark.asyncio
async def test_admin_alert_handler_sends_on_error() -> None:
    bot = DummyBot()
    handler = AdminAlertHandler(cast(Bot, bot), (1,), loop=asyncio.get_running_loop())

    logger = logging.getLogger("test.alerts.ignore")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.propagate = False

    logger.error("Not critical")
    await asyncio.sleep(0.01)

    assert len(bot.sent) == 1
    assert bot.sent[0][0] == 1
    assert "Not critical" in bot.sent[0][1]

    logger.removeHandler(handler)


@pytest.mark.asyncio
async def test_send_critical_alert_basic() -> None:
    bot = DummyBot()
    
    await send_critical_alert(cast(Bot, bot), (1, 2), "Test critical message")
    
    assert len(bot.sent) == 2
    assert bot.sent[0][0] == 1
    assert "КРИТИЧЕСКИЙ АЛЕРТ" in bot.sent[0][1]
    assert "Test critical message" in bot.sent[0][1]
    assert bot.sent[1][0] == 2


@pytest.mark.asyncio
async def test_send_critical_alert_with_tag() -> None:
    bot = DummyBot()
    
    await send_critical_alert(cast(Bot, bot), (1,), "Error occurred", tag_user="@testuser")
    
    assert len(bot.sent) == 1
    assert bot.sent[0][0] == 1
    assert "КРИТИЧЕСКИЙ АЛЕРТ" in bot.sent[0][1]
    assert "Error occurred" in bot.sent[0][1]
    assert "@testuser" in bot.sent[0][1]


@pytest.mark.asyncio
async def test_send_critical_alert_empty_admins() -> None:
    bot = DummyBot()
    
    await send_critical_alert(cast(Bot, bot), [], "Should not send")
    
    assert len(bot.sent) == 0
