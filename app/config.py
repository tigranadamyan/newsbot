"""Application configuration loaded from environment variables."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

DEFAULT_FILTER_PROMPT = (
    "Меня интересуют: технологии, наука, значимые политические события, "
    "экономика. Не присылай: катастрофы, криминал, сплетни, спорт, "
    "развлекательные новости, погоду, курсы валют."
)


@dataclass
class Config:
    """Centralized configuration for the news bot."""

    # --- Telegram Bot ---
    bot_token: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", ""))

    # --- RSS Source ---
    meduza_rss_url: str = field(
        default_factory=lambda: os.getenv(
            "MEDUZA_RSS_URL", "https://meduza.io/rss/all"
        )
    )

    # --- Database ---
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL", "sqlite+aiosqlite:///data/news.db"
        )
    )

    # --- LLM ---
    llm_provider: str = field(
        default_factory=lambda: os.getenv("LLM_PROVIDER", "none")
    )
    llm_model: str = field(
        default_factory=lambda: os.getenv("LLM_MODEL", "gpt-4o-mini")
    )
    openai_api_key: str = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY", "")
    )
    deepseek_api_key: str = field(
        default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", "")
    )
    ollama_base_url: str = field(
        default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    ollama_model: str = field(
        default_factory=lambda: os.getenv("OLLAMA_MODEL", "llama3.2")
    )

    # --- AI Filter ---
    filter_prompt: str = field(
        default_factory=lambda: os.getenv(
            "FILTER_PROMPT", DEFAULT_FILTER_PROMPT
        )
    )

    # --- Scheduler ---
    fetch_interval_seconds: int = field(
        default_factory=lambda: int(os.getenv("FETCH_INTERVAL_SECONDS", "60"))
    )
    morning_digest_hour: int = field(
        default_factory=lambda: int(os.getenv("MORNING_DIGEST_HOUR", "9"))
    )
    evening_digest_hour: int = field(
        default_factory=lambda: int(os.getenv("EVENING_DIGEST_HOUR", "20"))
    )

    # --- User ---
    telegram_user_id: int = field(
        default_factory=lambda: int(os.getenv("TELEGRAM_USER_ID", "0"))
    )

    @property
    def use_llm(self) -> bool:
        return self.llm_provider not in ("none", "")


config = Config()
