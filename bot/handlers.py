"""
Bot command handlers
"""
import logging
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

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
    
    await message.answer(
        "✅ <b>Бот активирован!</b>\n\n"
        "Теперь бот начнёт мониторить лоты и отправлять уведомления о новых поступлениях.",
        parse_mode='HTML'
    )
