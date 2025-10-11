"""Telegram command handlers for the bot."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from bot.filters import IsAdmin
from config import settings
from services.parser import Parser

logger = logging.getLogger(__name__)
router = Router()
parser = Parser()


async def _fetch_items(url: str):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, parser.get_items_from_url, url)


def _extract_user_id(message: Message) -> int | None:
    user = message.from_user
    return user.id if user else None


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """
    Handler for /start command
    
    Args:
        message: Incoming message
    """
    user_id = _extract_user_id(message)
    logger.info("User %s started the bot", user_id)

    is_admin = user_id in settings.ADMIN_CHAT_IDS if user_id else False

    if is_admin:
        await message.answer(
            "✅ <b>Бот активирован!</b>\n\n"
            "Теперь бот начнёт мониторить лоты и отправлять уведомления о новых поступлениях.\n\n"
            "📋 Доступные команды:\n"
            "/start - Запустить бота\n"
            "/status - Статус мониторинга\n"
            "/test <url> - Протестировать парсинг URL\n"
            "/help - Помощь",
            parse_mode='HTML'
        )
    else:
        await message.answer(
            "👋 Привет! Этот бот предназначен только для администраторов.",
            parse_mode='HTML'
        )


@router.message(Command("status"), IsAdmin())
async def cmd_status(message: Message) -> None:
    """
    Handler for /status command (admin only)
    
    Args:
        message: Incoming message
    """
    user_id = _extract_user_id(message)
    logger.info("Admin %s requested status", user_id)

    status_text = (
        "📊 <b>Статус мониторинга</b>\n\n"
        f"⏱ Интервал проверки: {settings.CHECK_INTERVAL_MINUTES} минут\n"
        f"🔗 Количество URL: {len(settings.MONITOR_URLS)}\n"
        f"👥 Количество админов: {len(settings.ADMIN_CHAT_IDS)}\n\n"
        "<b>Отслеживаемые URL:</b>\n"
    )
    
    for i, url in enumerate(settings.MONITOR_URLS, 1):
        status_text += f"{i}. {url}\n"
    
    await message.answer(status_text, parse_mode='HTML')


@router.message(Command("help"), IsAdmin())
async def cmd_help(message: Message) -> None:
    """
    Handler for /help command (admin only)
    
    Args:
        message: Incoming message
    """
    user_id = _extract_user_id(message)
    logger.info("Admin %s requested help", user_id)

    help_text = (
        "📖 <b>Помощь по боту</b>\n\n"
        "Этот бот автоматически мониторит указанные URL и отправляет уведомления "
        "о новым лотам всем администраторам.\n\n"
        "<b>Доступные команды:</b>\n"
        "/start - Запустить бота и увидеть приветствие\n"
        "/status - Посмотреть текущий статус мониторинга\n"
        "/test <url> - Протестировать парсинг URL\n"
        "/help - Показать эту справку\n\n"
        "💡 Бот работает автоматически в фоновом режиме и проверяет новые лоты "
        f"каждые {settings.CHECK_INTERVAL_MINUTES} минут."
    )
    
    await message.answer(help_text, parse_mode='HTML')


@router.message(Command("test"), IsAdmin())
async def cmd_test(message: Message) -> None:
    """
    Handler for /test command (admin only)
    Test parsing a specific URL
    
    Args:
        message: Incoming message
    """
    user_id = _extract_user_id(message)
    logger.info("Admin %s requested test", user_id)

    bot = message.bot

    if not user_id or bot is None:
        await message.answer(
            "❌ <b>Ошибка!</b>\n\n"
            "Не удалось определить пользователя.",
            parse_mode='HTML'
        )
        return

    command_parts = (message.text or "").split(maxsplit=1)

    if len(command_parts) < 2:
        await bot.send_message(
            chat_id=user_id,
            text=(
                "❌ <b>Ошибка!</b>\n\n"
                "Использование: <code>/test URL</code>\n\n"
                "Пример:\n"
                "<code>/test https://coins.ay.by/sssr/yubilejnye/iz-dragocennyh-metallov/</code>"
            ),
            parse_mode='HTML'
        )
        return

    url = command_parts[1].strip()

    if not url.startswith('http'):
        await bot.send_message(
            chat_id=user_id,
            text=(
                "❌ <b>Ошибка!</b>\n\n"
                "URL должен начинаться с http:// или https://"
            ),
            parse_mode='HTML'
        )
        return

    status_msg = await bot.send_message(
        chat_id=user_id,
        text=(
            "⏳ <b>Проверяю URL...</b>\n"
            f"URL: <code>{url}</code>"
        ),
        parse_mode='HTML'
    )

    try:
        items = await _fetch_items(url)

        if not items:
            await status_msg.edit_text(
                "⚠️ <b>Результат теста</b>\n\n"
                f"URL: <code>{url}</code>\n\n"
                "❌ Не найдено ни одного товара!\n"
                "Возможно, структура сайта изменилась или страница пуста.",
                parse_mode='HTML'
            )
            return
        
        summary_text = (
            "✅ <b>Результат теста</b>\n\n"
            f"URL: <code>{url}</code>\n"
            f"📦 Найдено товаров: <b>{len(items)}</b>\n\n"
            "Отправляю информацию о товарах..."
        )
        await status_msg.edit_text(summary_text, parse_mode='HTML')

        for i, item in enumerate(items, 1):
            try:
                caption = (
                    f"🔹 <b>Товар {i}/{len(items)}</b>\n\n"
                    f"<b>{item.title}</b>\n"
                    f"💰 Цена: {item.price}\n"
                    f"🔗 {item.url}"
                )
                
                await bot.send_photo(
                    chat_id=user_id,
                    photo=item.img_url,
                    caption=caption,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.exception("Error sending item %s", i)
                await bot.send_message(
                    chat_id=user_id,
                    text=f"❌ Ошибка отправки товара {i}: {item.title}",
                    parse_mode='HTML'
                )

        await bot.send_message(
            chat_id=user_id,
            text=(
                f"✅ <b>Тест завершён!</b>\n\n"
                f"Отправлено: {len(items)} товар(ов)"
            ),
            parse_mode='HTML'
        )
    except Exception as e:
        logger.exception("Error in test command")
        await status_msg.edit_text(
            "❌ <b>Ошибка!</b>\n\n"
            f"Не удалось получить данные с URL:\n"
            f"<code>{url}</code>\n\n"
            f"Ошибка: {str(e)}",
            parse_mode='HTML'
        )

    if message.chat.id != user_id:
        await message.reply(
            "📬 Результаты отправлены вам в личные сообщения.",
            quote=True
        )


