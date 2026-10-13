"""Configuration loaded from environment variables (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    owner_telegram_id: int
    owner_name: str
    llm_provider: str
    gemini_api_key: str
    gemini_model: str
    groq_api_key: str
    groq_model: str
    anthropic_api_key: str
    anthropic_model: str
    ollama_base_url: str
    ollama_model: str
    timezone: str
    db_path: str
    history_limit: int
    log_level: str


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def load_config(require_telegram: bool = True) -> Config:
    load_dotenv()

    token = _env("TELEGRAM_BOT_TOKEN")
    owner_raw = _env("OWNER_TELEGRAM_ID", "0")
    if require_telegram:
        if not token:
            raise ConfigError("TELEGRAM_BOT_TOKEN is missing in .env")
        if not owner_raw.isdigit() or int(owner_raw) == 0:
            raise ConfigError("OWNER_TELEGRAM_ID must be your numeric Telegram user ID")

    provider = _env("LLM_PROVIDER", "gemini").lower()
    if provider not in {"gemini", "groq", "anthropic", "ollama"}:
        raise ConfigError(f"Unknown LLM_PROVIDER: {provider}")

    return Config(
        telegram_bot_token=token,
        owner_telegram_id=int(owner_raw) if owner_raw.isdigit() else 0,
        owner_name=_env("OWNER_NAME", "gazda"),
        llm_provider=provider,
        gemini_api_key=_env("GEMINI_API_KEY"),
        gemini_model=_env("GEMINI_MODEL", "gemini-2.5-flash"),
        groq_api_key=_env("GROQ_API_KEY"),
        groq_model=_env("GROQ_MODEL", "llama-3.3-70b-versatile"),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        anthropic_model=_env("ANTHROPIC_MODEL", "claude-haiku-5-5"),
        ollama_base_url=_env("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        ollama_model=_env("OLLAMA_MODEL", "qwen2.5:7b"),
        timezone=_env("TIMEZONE", "Europe/Belgrade"),
        db_path=_env("DB_PATH", "data/jarvis.db"),
        history_limit=int(_env("HISTORY_LIMIT", "20")),
        log_level=_env("LOG_LEVEL", "INFO"),
    )
