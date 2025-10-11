"""
Main application entry point
"""
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import settings
from bot import router
from services import Monitor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def start_monitoring(monitor: Monitor):
    """Start the monitoring task"""
    await monitor.check_new_items()


async def main():
    """Main function to start the bot"""
    try:
        # Validate settings
        settings.validate()
        
        # Initialize bot and dispatcher
        bot = Bot(
            token=settings.BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        dp = Dispatcher()
        
        # Register handlers
        dp.include_router(router)
        
        # Initialize monitor
        monitor = Monitor(bot)
        
        # Setup scheduler for periodic monitoring
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            start_monitoring,
            'interval',
            minutes=settings.CHECK_INTERVAL_MINUTES,
            args=[monitor]
        )
        scheduler.start()
        
        logger.info(f"Bot started. Monitoring every {settings.CHECK_INTERVAL_MINUTES} minutes")
        logger.info(f"Monitoring URLs: {settings.MONITOR_URLS}")
        
        # Run initial check
        await monitor.check_new_items()
        
        # Start polling
        await dp.start_polling(bot)
        
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        raise


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
