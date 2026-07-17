"""RSS fetcher — pulls news from Meduza RSS with deduplication."""

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser
from sqlalchemy import select

from app.config import config
from app.database.db import async_session
from app.database.models import News

logger = logging.getLogger(__name__)


@dataclass
class RawEntry:
    source: str
    title: str
    url: str
    content: str | None
    published_at: datetime | None


class RssFetcher:
    """Fetches Meduza RSS and stores unique entries in the database."""

    def __init__(self) -> None:
        self._url = config.meduza_rss_url

    async def fetch(self) -> list[News]:
        """Fetch RSS, save new entries. Returns list of newly saved News objects."""
        loop = asyncio.get_running_loop()
        feed = await loop.run_in_executor(None, feedparser.parse, self._url)

        if feed.bozo and not feed.entries:
            logger.warning("RSS parse warning: %s", feed.bozo_exception)
            return []

        entries = self._parse(feed.entries)
        return await self._save_new(entries)

    def _parse(self, raw_entries: list[dict]) -> list[RawEntry]:
        result: list[RawEntry] = []
        for entry in raw_entries:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            if not title or not link:
                continue

            content = entry.get("summary") or entry.get("description", "")
            published = self._parse_date(entry)

            result.append(
                RawEntry(
                    source="Meduza",
                    title=title,
                    url=link,
                    content=content if content else None,
                    published_at=published,
                )
            )
        return result

    @staticmethod
    def _parse_date(entry: dict) -> datetime | None:
        parsed = entry.get("published_parsed")
        if parsed:
            try:
                from time import mktime
                return datetime.fromtimestamp(mktime(parsed), tz=timezone.utc)
            except (OverflowError, OSError):
                pass

        published_str = entry.get("published", "")
        if published_str:
            try:
                from email.utils import parsedate_to_datetime
                return parsedate_to_datetime(published_str)
            except (ValueError, TypeError):
                pass

        return None

    @staticmethod
    def _make_hash(url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()

    async def _save_new(self, entries: list[RawEntry]) -> list[News]:
        saved: list[News] = []
        async with async_session() as session:
            for entry in entries:
                url_hash = self._make_hash(entry.url)

                existing = await session.execute(
                    select(News.id).where(News.hash == url_hash)
                )
                if existing.scalar() is not None:
                    continue

                news = News(
                    source=entry.source,
                    source_message_id=0,
                    title=entry.title,
                    url=entry.url,
                    content=entry.content,
                    published_at=entry.published_at,
                    hash=url_hash,
                )
                session.add(news)
                saved.append(news)

            if saved:
                await session.commit()
                # Re-fetch to get DB-assigned IDs
                for i, n in enumerate(saved):
                    result = await session.execute(
                        select(News).where(News.hash == n.hash)
                    )
                    saved[i] = result.scalar_one()

        return saved
