import asyncio
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot import router
from config import settings
from services import Monitor
from services.runtime import configure_scheduler

# ensure logs are recorded both to stdout and to a rotating file
def configure_logging() -> None:
    log_dir = Path(os.getenv("LOG_DIR", "logs"))
    if not log_dir.is_absolute():
        log_dir = Path.cwd() / log_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "bot.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            RotatingFileHandler(
                log_file,
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            ),
        ],
        force=True,
    )


configure_logging()
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
    monitor_job = scheduler.add_job(
        monitor.check_new_items,
        "interval",
        minutes=settings.CHECK_INTERVAL_MINUTES,
        coalesce=True,
    )
    configure_scheduler(scheduler, monitor_job)
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
