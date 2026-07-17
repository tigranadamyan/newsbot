"""Digest service — generates morning/evening news summaries."""

import logging
from datetime import datetime

from sqlalchemy import select

from app.database.db import async_session
from app.database.models import News

logger = logging.getLogger(__name__)

DIGEST_HEADER_MORNING = "☀️ <b>Доброе утро!</b>\n\nГлавные события:\n\n"
DIGEST_HEADER_EVENING = "🌙 <b>Добрый вечер!</b>\n\nГлавные события за день:\n\n"


class DigestService:
    """Generates and sends daily digests."""

    def __init__(self, bot) -> None:
        self._bot = bot

    async def _get_user_id(self) -> int:
        """Get user ID from DB (lazy import to avoid circular dependency)."""
        from app.bot.telegram import get_user_id
        return await get_user_id()

    async def send_morning_digest(self) -> None:
        """Generate and send morning digest."""
        digest = await self.build_digest(hours_back=24, header=DIGEST_HEADER_MORNING)
        if digest:
            await self._send(digest)
            logger.info("Morning digest sent")
        else:
            logger.info("No important news for morning digest")

    async def send_evening_digest(self) -> None:
        """Generate and send evening digest."""
        digest = await self.build_digest(hours_back=12, header=DIGEST_HEADER_EVENING)
        if digest:
            await self._send(digest)
            logger.info("Evening digest sent")
        else:
            logger.info("No important news for evening digest")

    async def build_digest(self, hours_back: int, header: str) -> str | None:
        """Build a digest message from important recent news (public API)."""
        from datetime import timedelta, timezone

        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours_back)

        async with async_session() as session:
            result = await session.execute(
                select(News)
                .where(
                    News.importance_score >= 70,
                    News.created_at >= cutoff,
                    News.is_digested == False,  # noqa: E712
                )
                .order_by(News.importance_score.desc())
                .limit(5)
            )
            entries = result.scalars().all()

        if not entries:
            return None

        lines = [header]
        for i, news in enumerate(entries, 1):
            lines.append(f"<b>{i}. {self._escape(news.title)}</b>")
            if news.summary:
                lines.append(f"\n{self._escape(news.summary)}")
            lines.append(f"\nИсточник: {news.source}")
            if news.url:
                lines.append(f"\n<a href='{news.url}'>Читать</a>")
            lines.append("\n")

        # Mark as digested
        ids = [n.id for n in entries]
        async with async_session() as session:
            for nid in ids:
                news_obj = await session.get(News, nid)
                if news_obj:
                    news_obj.is_digested = True
            await session.commit()

        return "\n".join(lines)

    async def _send(self, text: str) -> None:
        """Send digest to the user."""
        from aiogram.enums import ParseMode

        uid = await self._get_user_id()
        if not uid:
            logger.warning("No user ID — cannot send digest")
            return

        try:
            await self._bot.send_message(
                chat_id=uid,
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=False,
            )
        except Exception:
            logger.exception("Failed to send digest")

    @staticmethod
    def _escape(text: str) -> str:
        """Escape HTML special chars for Telegram."""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
