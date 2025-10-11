import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot import router
from config import settings
from services import Monitor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("lotsearch")


async def main() -> None:
    settings.validate()

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(router)

    monitor = Monitor(bot)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        monitor.check_new_items,
        "interval",
        minutes=settings.CHECK_INTERVAL_MINUTES,
        coalesce=True,
    )
    scheduler.start()

    logger.info(
        "Bot started. Monitoring every %s minutes for %s URLs",
        settings.CHECK_INTERVAL_MINUTES,
        len(settings.MONITOR_URLS),
    )
    logger.info("Monitoring URLs: %s", settings.MONITOR_URLS)

    await monitor.check_new_items()
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception:
        logger.exception("Fatal error")
