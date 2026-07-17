"""Entry point — launch aiogram bot + scheduler."""

import asyncio
import logging
import sys

from app.bot.telegram import bot, dp
from app.database.db import init_db
from app.scheduler.tasks import create_scheduler


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)


async def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("Initializing database...")
    await init_db()

    # Restore saved filter from DB
    from app.bot.telegram import load_filter_from_db
    await load_filter_from_db()

    logger.info("Starting scheduler...")
    scheduler = create_scheduler(bot)
    scheduler.start()

    logger.info("Starting Telegram bot...")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
