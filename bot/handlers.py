"""
Bot command handlers
"""
import logging
from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from bot.filters import IsAdmin
from config import settings

logger = logging.getLogger(__name__)

# Create router for handlers
router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """
    Handler for /start command
    
    Args:
        message: Incoming message
    """
    logger.info(f"User {message.from_user.id} started the bot")
    
    # Check if user is admin
    is_admin = message.from_user.id in settings.ADMIN_CHAT_IDS
    
    if is_admin:
        await message.answer(
            "✅ <b>Бот активирован!</b>\n\n"
            "Теперь бот начнёт мониторить лоты и отправлять уведомления о новых поступлениях.\n\n"
            "📋 Доступные команды:\n"
            "/start - Запустить бота\n"
            "/status - Статус мониторинга\n"
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
    logger.info(f"Admin {message.from_user.id} requested status")
    
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
    logger.info(f"Admin {message.from_user.id} requested help")
    
    help_text = (
        "📖 <b>Помощь по боту</b>\n\n"
        "Этот бот автоматически мониторит указанные URL и отправляет уведомления "
        "о новых лотах всем администраторам.\n\n"
        "<b>Доступные команды:</b>\n"
        "/start - Запустить бота и увидеть приветствие\n"
        "/status - Посмотреть текущий статус мониторинга\n"
        "/help - Показать эту справку\n\n"
        "💡 Бот работает автоматически в фоновом режиме и проверяет новые лоты "
        f"каждые {settings.CHECK_INTERVAL_MINUTES} минут."
    )
    
    await message.answer(help_text, parse_mode='HTML')

