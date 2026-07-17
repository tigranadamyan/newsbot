"""News analyzer + AI filter — categorizes, scores, and filters by user prompt."""

import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy import select

from app.config import config
from app.database.db import async_session
from app.database.models import News

logger = logging.getLogger(__name__)


@dataclass
class FilterResult:
    interesting: bool
    reason: str


# ---------------------------------------------------------------------------
# Keywords (fallback when no LLM)
# ---------------------------------------------------------------------------

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "technology": [
        "ai", "artificial intelligence", "machine learning", "software", "app",
        "startup", "google", "apple", "microsoft", "amazon", "meta", "chip",
        "cyber", "crypto", "bitcoin", "blockchain", "robot", "tesla", "spacex",
        "nvidia", "openai", "smartphone", "gadget", "нейро", "ии",
        "искусственный интеллект",
    ],
    "economy": [
        "economy", "inflation", "stock", "market", "gdp", "recession", "bank",
        "interest rate", "trade", "tariff", "oil price", "unemployment", "budget",
        "debt", "investment", "экономик", "инфляц", "рынок", "биржа", "ввп",
    ],
    "politics": [
        "president", "election", "congress", "senate", "parliament", "vote",
        "government", "minister", "law", "bill", "legislation", "policy",
        "protest", "sanction", "diplomat", "nato", "treaty", "war", "conflict",
        "президент", "выбор", "правительств", "закон", "санкц", "протест",
    ],
    "science": [
        "scientist", "research", "study", "discovery", "nasa", "space",
        "climate", "environment", "dna", "gene", "vaccine", "health",
        "medicine", "physics", "quantum", "исследован", "открыти", "учен",
        "космос", "здоров", "вакцин",
    ],
    "gaming": [
        "game", "gaming", "playstation", "xbox", "nintendo", "steam",
        "esport", "twitch", "игр",
    ],
}

IMPORTANCE_SIGNALS: dict[str, list[str]] = {
    "high": [
        "breaking", "urgent", "crisis", "war", "attack", "deadly", "killed",
        "emergency", "resign", "impeach", "coup", "collapse", "crash",
        "срочно", "кризис", "война", "атака", "погиб", "жертв", "отставк",
    ],
    "medium": [
        "announce", "deal", "agreement", "sanction", "protest", "strike",
        "verdict", "election", "vote", "launch", "major",
        "соглашени", "сделк", "запуск", "объявил",
    ],
}

CLICKBAIT_PATTERNS: list[re.Pattern] = [
    re.compile(r"you won'?t believe", re.IGNORECASE),
    re.compile(r"what happened next", re.IGNORECASE),
    re.compile(r"shocking", re.IGNORECASE),
    re.compile(r"goes viral", re.IGNORECASE),
    re.compile(r"шок", re.IGNORECASE),
    re.compile(r"вы не поверите", re.IGNORECASE),
    re.compile(r"взорвал.*сеть", re.IGNORECASE),
]

SOURCE_WEIGHT: dict[str, int] = {"Meduza": 20}


# ---------------------------------------------------------------------------
# LLM Provider
# ---------------------------------------------------------------------------

class LLMProvider(ABC):
    """Abstract adapter for LLM-based analysis and filtering."""

    @abstractmethod
    async def filter_news(self, title: str, content: str | None) -> FilterResult:
        """Check if news matches user's interests based on custom prompt."""
        ...

    @abstractmethod
    async def analyze(self, title: str, content: str | None) -> dict:
        """Return {"category": str, "score": int, "summary": str}."""
        ...


class NoOpProvider(LLMProvider):
    async def filter_news(self, title: str, content: str | None) -> FilterResult:
        return FilterResult(interesting=False, reason="LLM not configured")

    async def analyze(self, title: str, content: str | None) -> dict:
        return {"category": "other", "score": 0, "summary": ""}


class OpenAIProvider(LLMProvider):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            api_key=api_key or config.openai_api_key,
            base_url=base_url,
        )
        self._model = model or config.llm_model or "gpt-4o-mini"

    async def filter_news(self, title: str, content: str | None) -> FilterResult:
        text = f"Title: {title}\nContent: {content or title}"
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a personal news filter. The user has described what "
                        "news they want and don't want. Read their description, then "
                        "decide if this news item matches their interests.\n\n"
                        "Return JSON: {\"interesting\": true/false, \"reason\": \"why in Russian, max 60 chars\"}\n\n"
                        "USER'S FILTER DESCRIPTION:\n" + config.filter_prompt
                    ),
                },
                {"role": "user", "content": text},
            ],
            response_format={"type": "json_object"},
            max_tokens=150,
        )
        try:
            data = json.loads(response.choices[0].message.content or "{}")
        except json.JSONDecodeError:
            return FilterResult(interesting=False, reason="parse error")
        return FilterResult(
            interesting=data.get("interesting", False),
            reason=data.get("reason", ""),
        )

    async def analyze(self, title: str, content: str | None) -> dict:
        text = f"Title: {title}\nContent: {content or title}"
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Return JSON: "
                        '{"category": "technology|economy|politics|science|gaming|other",'
                        ' "score": 0-100, "summary": "one sentence in Russian why this matters"}'
                    ),
                },
                {"role": "user", "content": text},
            ],
            response_format={"type": "json_object"},
            max_tokens=200,
        )
        try:
            return json.loads(response.choices[0].message.content or "{}")
        except json.JSONDecodeError:
            return {"category": "other", "score": 50, "summary": ""}


class OllamaProvider(LLMProvider):
    def __init__(self) -> None:
        import httpx
        self._base_url = config.ollama_base_url.rstrip("/")
        self._model = config.llm_model or config.ollama_model or "llama3.2"
        self._client = httpx.AsyncClient(timeout=30.0)

    async def _call(self, system_prompt: str, user_text: str) -> dict:
        prompt = f"{system_prompt}\n\nReturn ONLY valid JSON, no markdown.\n\nNews: {user_text}"
        response = await self._client.post(
            f"{self._base_url}/api/generate",
            json={"model": self._model, "prompt": prompt, "stream": False},
        )
        response.raise_for_status()
        data = response.json()
        text_out = data.get("response", "{}")
        match = re.search(r"\{.*\}", text_out, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return {}

    async def filter_news(self, title: str, content: str | None) -> FilterResult:
        system = (
            "You are a personal news filter. User's interests:\n"
            + config.filter_prompt
            + "\n\nReturn JSON: {\"interesting\": true/false, \"reason\": \"why in Russian, max 60 chars\"}"
        )
        text = f"Title: {title}\nContent: {content or title}"
        data = await self._call(system, text)
        return FilterResult(
            interesting=data.get("interesting", False),
            reason=data.get("reason", ""),
        )

    async def analyze(self, title: str, content: str | None) -> dict:
        system = (
            "Return JSON: "
            '{"category": "technology|economy|politics|science|gaming|other",'
            ' "score": 0-100, "summary": "one sentence in Russian why this matters"}'
        )
        text = f"Title: {title}\nContent: {content or title}"
        return await self._call(system, text)


def _create_llm_provider() -> LLMProvider:
    match config.llm_provider:
        case "openai":
            logger.info("LLM: OpenAI / model=%s", config.llm_model or "gpt-4o-mini")
            return OpenAIProvider()
        case "deepseek":
            logger.info("LLM: DeepSeek / model=%s", config.llm_model or "deepseek-chat")
            return OpenAIProvider(
                api_key=config.deepseek_api_key,
                base_url="https://api.deepseek.com/v1",
                model=config.llm_model or "deepseek-chat",
            )
        case "ollama":
            logger.info("LLM: Ollama / model=%s", config.llm_model or config.ollama_model or "llama3.2")
            return OllamaProvider()
        case _:
            return NoOpProvider()


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class NewsAnalyzer:
    """Analyzes news: AI filtering, categorization, importance scoring."""

    def __init__(self) -> None:
        self._llm = _create_llm_provider()

    # -- AI Filter (the main new feature) --

    async def filter_interesting(self, news: News) -> FilterResult:
        """Use LLM to check if news matches user's custom filter prompt."""
        if not config.use_llm:
            # Fallback: rule-based — pass if importance score >= 50
            score = self._score(news.title, news.content, news.source)
            news.importance_score = score
            interesting = score >= 50
            return FilterResult(
                interesting=interesting,
                reason=f"Rule-based score: {score}/100" if interesting else "",
            )

        return await self._llm.filter_news(news.title, news.content)

    # -- Batch analysis (for digests) --

    async def analyze_unprocessed(self) -> int:
        """Score and categorize all unprocessed news."""
        async with async_session() as session:
            result = await session.execute(
                select(News).where(News.importance_score == 0)
            )
            unprocessed = result.scalars().all()

        count = 0
        for news in unprocessed:
            try:
                await self._analyze_one(news)
                count += 1
            except Exception:
                logger.exception("Failed to analyze news id=%d", news.id)

        logger.info("Analyzed %d news entries", count)
        return count

    async def _analyze_one(self, news: News) -> None:
        if self._is_clickbait(news.title):
            news.importance_score = -1
            async with async_session() as session:
                await session.merge(news)
                await session.commit()
            return

        if config.use_llm:
            result = await self._llm.analyze(news.title, news.content)
            category = result.get("category", "other")
            score = result.get("score", 50)
            summary = result.get("summary", "")
        else:
            category = self._classify(news.title, news.content)
            score = self._score(news.title, news.content, news.source)
            summary = ""

        news.category = category
        news.importance_score = score
        news.summary = summary

        async with async_session() as session:
            await session.merge(news)
            await session.commit()

    # ---- Rule-based helpers ----

    @staticmethod
    def _is_clickbait(title: str) -> bool:
        letters = [c for c in title if c.isalpha()]
        if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.5:
            return True
        if title.count("!") > 2 or title.count("?") > 2:
            return True
        for pattern in CLICKBAIT_PATTERNS:
            if pattern.search(title):
                return True
        return False

    @staticmethod
    def _classify(title: str, content: str | None) -> str:
        text = (title + " " + (content or "")).lower()
        scores: dict[str, int] = {}
        for category, keywords in CATEGORY_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text)
            if score:
                scores[category] = score
        if not scores:
            return "other"
        return max(scores, key=lambda k: scores[k])

    @staticmethod
    def _score(title: str, content: str | None, source: str) -> int:
        text = (title + " " + (content or "")).lower()
        score = SOURCE_WEIGHT.get(source, 15)
        for signal in IMPORTANCE_SIGNALS["high"]:
            if signal in text:
                score += 20
                break
        medium_matches = sum(1 for s in IMPORTANCE_SIGNALS["medium"] if s in text)
        score += min(medium_matches * 10, 30)
        return min(score, 100)
