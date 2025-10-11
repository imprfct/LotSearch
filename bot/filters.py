"""
Filters for bot handlers
"""
from typing import Union
from aiogram.filters import Filter
from aiogram.types import Message, CallbackQuery

from config import settings


class IsAdmin(Filter):
    """Filter to check if user is admin"""
    
    async def __call__(self, event: Union[Message, CallbackQuery]) -> bool:
        """
        Check if user is in admin list
        
        Args:
            event: Message or CallbackQuery event
            
        Returns:
            True if user is admin, False otherwise
        """
        user_id = event.from_user.id if event.from_user else None
        return user_id in settings.ADMIN_CHAT_IDS
