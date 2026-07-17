"""Telegram bot — aiogram handlers + push helper for real-time news."""

import logging

from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command

from app.config import DEFAULT_FILTER_PROMPT, config
from app.database.models import News

logger = logging.getLogger(__name__)

bot = Bot(
    token=config.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

FILTER_KEY = "filter_prompt"


# ---------------------------------------------------------------------------
# Filter persistence (DB-backed, survives restarts)
# ---------------------------------------------------------------------------

async def load_filter_from_db() -> None:
    """Load saved filter prompt from DB into config on startup."""
    from sqlalchemy import select

    from app.database.db import async_session
    from app.database.models import Setting

    async with async_session() as session:
        result = await session.execute(
            select(Setting).where(Setting.key == FILTER_KEY)
        )
        row = result.scalar_one_or_none()
        if row and row.value:
            config.filter_prompt = row.value
            logger.info("Loaded filter prompt from DB")


async def _load_filter_prompt() -> str:
    """Get current filter prompt (from config)."""
    return config.filter_prompt


async def _save_filter_prompt(text: str) -> None:
    """Persist filter prompt to DB."""
    from app.database.db import async_session
    from app.database.models import Setting

    async with async_session() as session:
        setting = await session.get(Setting, FILTER_KEY)
        if setting:
            setting.value = text
        else:
            session.add(Setting(key=FILTER_KEY, value=text))
        await session.commit()


# ---------------------------------------------------------------------------
# Push helper — called by scheduler to send news immediately
# ---------------------------------------------------------------------------

async def push_news(news: News, reason: str) -> None:
    """Send a single news item to the configured user immediately."""
    if not config.telegram_user_id:
        logger.warning("TELEGRAM_USER_ID not set — cannot push")
        return

    cat_emoji = _category_emoji(news.category or "other")
    lines = [
        f"🔔 <b>{_escape(news.title)}</b>",
        "",
    ]
    if reason:
        lines.append(f"💡 {_escape(reason)}")
        lines.append("")
    lines.append(f"📍 {news.source}")
    if news.url:
        lines.append(f"🔗 <a href='{news.url}'>Читать</a>")

    try:
        await bot.send_message(
            chat_id=config.telegram_user_id,
            text="\n".join(lines),
            disable_web_page_preview=True,
        )
    except Exception:
        logger.exception("Failed to push news id=%d", news.id)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

@dp.message(Command("start"))
async def cmd_start(message: types.Message) -> None:
    text = (
        "📰 <b>NewsBot</b> — персональный анти-думскроллинг.\n\n"
        "Я мониторю Meduza RSS и присылаю только те новости, "
        "которые соответствуют твоему фильтру.\n\n"
        "<b>Команды:</b>\n"
        "/news — последние новости\n"
        "/digest — дайджест\n"
        "/filter — посмотреть текущий фильтр\n"
        "/filter текст — обновить фильтр\n"
    )
    await message.answer(text)


@dp.message(Command("filter"))
async def cmd_filter(message: types.Message) -> None:
    """Show or update the AI filter prompt. Persisted in DB across restarts."""
    args = message.text.removeprefix("/filter").strip()

    if not args:
        prompt = await _load_filter_prompt()
        default_note = ""
        if prompt != DEFAULT_FILTER_PROMPT:
            default_note = "\n<i>Сбросить на дефолтный: /filter reset</i>"
        await message.answer(
            f"📋 <b>Текущий фильтр:</b>\n\n{_escape(prompt)}"
            f"{default_note}\n\n"
            f"<i>Изменить: /filter описание новостей которые тебе интересны</i>"
        )
        return

    # Reset to default
    if args.lower() == "reset":
        args = DEFAULT_FILTER_PROMPT

    # Save to DB and update in-memory config
    await _save_filter_prompt(args)
    config.filter_prompt = args
    await message.answer(
        f"✅ <b>Фильтр обновлён и сохранён:</b>\n\n{_escape(args)}\n\n"
        f"<i>Новости будут фильтроваться по этому описанию</i>"
    )


@dp.message(Command("news"))
async def cmd_news(message: types.Message) -> None:
    """Show latest interesting news."""
    from sqlalchemy import select

    from app.database.db import async_session

    async with async_session() as session:
        result = await session.execute(
            select(News)
            .where(News.importance_score >= 30)
            .order_by(News.importance_score.desc(), News.created_at.desc())
            .limit(5)
        )
        entries = result.scalars().all()

    if not entries:
        await message.answer("Пока нет новостей по твоему фильтру.")
        return

    lines = ["📰 <b>Последние новости:</b>\n"]
    for i, news in enumerate(entries, 1):
        cat_emoji = _category_emoji(news.category)
        lines.append(f"{cat_emoji} <b>{i}. {_escape(news.title)}</b>")
        if news.summary:
            lines.append(f"   {_escape(news.summary)}")
        lines.append(f"   📍 {news.source}")
        if news.url:
            lines.append(f"   🔗 <a href='{news.url}'>Читать</a>")
        lines.append("")

    await message.answer("\n".join(lines), disable_web_page_preview=True)


@dp.message(Command("digest"))
async def cmd_digest(message: types.Message) -> None:
    """Generate digest on demand."""
    from datetime import datetime

    from app.services.digest import DigestService

    digest_svc = DigestService(bot)
    now = datetime.now()

    if now.hour < 12:
        header = "☀️ <b>Утренний дайджест (по запросу)</b>\n\nГлавные события:\n\n"
        hours = 24
    else:
        header = "🌙 <b>Вечерний дайджест (по запросу)</b>\n\nГлавные события за день:\n\n"
        hours = 12

    text = await digest_svc.build_digest(hours_back=hours, header=header)
    if text:
        await message.answer(text, disable_web_page_preview=True)
    else:
        await message.answer("Пока нет важных новостей для дайджеста.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _category_emoji(category: str) -> str:
    return {
        "technology": "💻", "economy": "💰", "politics": "🏛️",
        "science": "🔬", "gaming": "🎮", "other": "📌",
    }.get(category, "📌")


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
