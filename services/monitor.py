"""
Monitoring service for tracking new items
"""
import logging
from typing import Set, List
from aiogram import Bot

from config import settings
from models import Item
from services.parser import Parser

logger = logging.getLogger(__name__)


class Monitor:
    """Monitor for checking new items on websites"""
    
    def __init__(self, bot: Bot):
        self.bot = bot
        self.parser = Parser()
        self.known_items: Set[str] = set()  # Store URLs of known items
    
    async def check_new_items(self) -> None:
        """Check all monitored URLs for new items and send notifications"""
        logger.info("Starting monitoring check...")
        
        for url in settings.MONITOR_URLS:
            try:
                await self._check_url(url)
            except Exception as e:
                logger.error(f"Error checking URL {url}: {e}")
    
    async def _check_url(self, url: str) -> None:
        """
        Check a specific URL for new items
        
        Args:
            url: URL to check
        """
        logger.info(f"Checking URL: {url}")
        
        # Get current items from the page
        current_items = self.parser.get_items_from_url(url)
        
        if not current_items:
            logger.warning(f"No items found at {url}")
            return
        
        # Find new items
        new_items = [
            item for item in current_items 
            if item.url not in self.known_items
        ]
        
        # Send notifications for new items
        for item in new_items:
            await self._send_notification(item)
        
        # Update known items
        self.known_items.update(item.url for item in current_items)
        
        logger.info(f"Found {len(new_items)} new items at {url}")
    
    async def _send_notification(self, item: Item) -> None:
        """
        Send notification about new item
        
        Args:
            item: Item to notify about
        """
        try:
            caption = (
                f"🆕 <b>{item.title}</b>\n"
                f"Цена: {item.price}\n"
                f"🔗 {item.url}"
            )
            
            await self.bot.send_photo(
                chat_id=settings.ADMIN_CHAT_ID,
                photo=item.img_url,
                caption=caption,
                parse_mode='HTML'
            )
            logger.info(f"Notification sent for: {item.title}")
        except Exception as e:
            logger.error(f"Error sending notification for {item.title}: {e}")
