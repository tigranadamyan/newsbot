"""APScheduler tasks — fetch RSS → AI filter → push + daily digests."""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.bot.telegram import push_news
from app.config import config
from app.services.digest import DigestService
from app.services.news_analyzer import NewsAnalyzer
from app.services.rss_fetcher import RssFetcher

logger = logging.getLogger(__name__)


def create_scheduler(bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")

    fetcher = RssFetcher()
    analyzer = NewsAnalyzer()
    digest_svc = DigestService(bot)

    # --- Core loop: fetch → filter → push (every N seconds) ---
    async def fetch_filter_push() -> None:
        logger.debug("Fetching RSS...")
        new_entries = await fetcher.fetch()
        if not new_entries:
            return

        logger.info("Fetched %d new entries, filtering...", len(new_entries))
        pushed = 0
        for news in new_entries:
            try:
                result = await analyzer.filter_interesting(news)
                if result.interesting:
                    await push_news(news, result.reason)
                    # Mark as analyzed so it appears in /news and digests
                    news.importance_score = max(news.importance_score, 80)
                    async with _get_session() as session:
                        await session.merge(news)
                        await session.commit()
                    pushed += 1
                else:
                    # Mark as processed with low score
                    news.importance_score = max(news.importance_score, 10)
                    async with _get_session() as session:
                        await session.merge(news)
                        await session.commit()
            except Exception:
                logger.exception("Failed to filter/push news id=%d", news.id)

        if pushed:
            logger.info("Pushed %d interesting news", pushed)

    scheduler.add_job(
        fetch_filter_push,
        trigger=IntervalTrigger(seconds=config.fetch_interval_seconds),
        id="fetch_filter_push",
        name="Fetch RSS → AI filter → push",
        replace_existing=True,
    )

    # --- Daily digests ---
    scheduler.add_job(
        digest_svc.send_morning_digest,
        trigger=CronTrigger(hour=config.morning_digest_hour, minute=0),
        id="morning_digest",
        name="Send morning digest",
        replace_existing=True,
    )

    scheduler.add_job(
        digest_svc.send_evening_digest,
        trigger=CronTrigger(hour=config.evening_digest_hour, minute=0),
        id="evening_digest",
        name="Send evening digest",
        replace_existing=True,
    )

    logger.info(
        "Scheduler: fetch+filter every %ds, digest at %02d:00 / %02d:00 UTC",
        config.fetch_interval_seconds,
        config.morning_digest_hour,
        config.evening_digest_hour,
    )

    return scheduler


def _get_session():
    """Lazy import to avoid circular deps in scheduler scope."""
    from app.database.db import async_session
    return async_session()
