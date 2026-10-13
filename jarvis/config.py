"""Configuration loaded from environment variables (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import find_dotenv, load_dotenv


class ConfigError(Exception):
    pass


PROVIDERS = {"gemini", "groq", "anthropic", "ollama"}


@dataclass(frozen=True)
class Config:
    # --- owner / locale ---
    owner_name: str = "gazda"
    timezone: str = "Europe/Belgrade"
    city: str = "Novi Sad"
    city_lat: float = 45.2671
    city_lon: float = 19.8335
    default_country_code: str = "381"

    # --- LLM ---
    llm_provider: str = "gemini"
    llm_fallbacks: tuple[str, ...] = ("groq",)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_stt_model: str = "whisper-large-v3-turbo"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-5-5"
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen2.5:7b"

    # --- HUD (main interface, runs on the phone) ---
    hud_host: str = "127.0.0.1"
    hud_port: int = 8765
    hud_token: str = ""

    # --- Telegram (optional, secondary) ---
    telegram_bot_token: str = ""
    owner_telegram_id: int = 0

    # --- phone (Android / Termux:API) ---
    phone_mode: str = "auto"  # auto | on | off
    followup_channel: str = "auto"  # auto (same as the call) | sms | whatsapp
    calls_poll_seconds: int = 20
    sms_poll_seconds: int = 30

    # --- WhatsApp ---
    whatsapp_mode: str = "notifications"  # notifications | bridge | off
    whatsapp_bridge_url: str = "http://127.0.0.1:8766"
    whatsapp_bridge_token: str = ""
    whatsapp_poll_seconds: int = 10
    include_groups: bool = False

    # --- Google (Gmail + Calendar) ---
    google_client_id: str = ""
    google_client_secret: str = ""
    gmail_enabled: bool = False
    gmail_query: str = "is:unread category:primary newer_than:2d"
    gmail_poll_seconds: int = 120
    calendar_enabled: bool = False

    # --- schedule ---
    briefing_time: str = "08:00"
    evening_summary_time: str = "21:00"  # empty = off
    quiet_hours: str = "23:00-08:00"  # empty = off

    # --- voice ---
    tts_voice: str = "sr-RS-NicholasNeural"

    # --- storage ---
    db_path: str = "data/jarvis.db"
    backup_keep: int = 7
    history_limit: int = 20
    log_level: str = "INFO"


    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.owner_telegram_id)

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _bool(name: str, default: bool) -> bool:
    raw = _env(name, "1" if default else "0").lower()
    return raw in {"1", "true", "yes", "da", "on"}


def _int(name: str, default: int) -> int:
    raw = _env(name, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def load_config() -> Config:
    # .env from the folder Jarvis is started in (falls back to searching upwards).
    load_dotenv(find_dotenv(usecwd=True))

    provider = _env("LLM_PROVIDER", "gemini").lower()
    if provider not in PROVIDERS:
        raise ConfigError(f"Unknown LLM_PROVIDER: {provider}")
    fallbacks = tuple(
        p for p in (x.strip().lower() for x in _env("LLM_FALLBACKS", "groq").split(",")) if p and p != provider
    )
    for p in fallbacks:
        if p not in PROVIDERS:
            raise ConfigError(f"Unknown provider in LLM_FALLBACKS: {p}")

    owner_tg = _env("OWNER_TELEGRAM_ID", "0")
    if owner_tg and not owner_tg.isdigit():
        raise ConfigError("OWNER_TELEGRAM_ID must be your numeric Telegram user ID")

    whatsapp_mode = _env("WHATSAPP_MODE", "notifications").lower()
    if whatsapp_mode not in {"notifications", "bridge", "off"}:
        raise ConfigError("WHATSAPP_MODE must be notifications, bridge or off")

    return Config(
        owner_name=_env("OWNER_NAME", "gazda"),
        timezone=_env("TIMEZONE", "Europe/Belgrade"),
        city=_env("CITY", "Novi Sad"),
        city_lat=float(_env("CITY_LAT", "45.2671")),
        city_lon=float(_env("CITY_LON", "19.8335")),
        default_country_code=_env("DEFAULT_COUNTRY_CODE", "381"),
        llm_provider=provider,
        llm_fallbacks=fallbacks,
        gemini_api_key=_env("GEMINI_API_KEY"),
        gemini_model=_env("GEMINI_MODEL", "gemini-2.5-flash"),
        groq_api_key=_env("GROQ_API_KEY"),
        groq_model=_env("GROQ_MODEL", "llama-3.3-70b-versatile"),
        groq_stt_model=_env("GROQ_STT_MODEL", "whisper-large-v3-turbo"),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        anthropic_model=_env("ANTHROPIC_MODEL", "claude-haiku-5-5"),
        ollama_base_url=_env("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        ollama_model=_env("OLLAMA_MODEL", "qwen2.5:7b"),
        hud_host=_env("HUD_HOST", "127.0.0.1"),
        hud_port=_int("HUD_PORT", 8765),
        hud_token=_env("HUD_TOKEN"),
        telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
        owner_telegram_id=int(owner_tg or "0"),
        phone_mode=_env("PHONE_MODE", "auto").lower(),
        followup_channel=_env("FOLLOWUP_CHANNEL", "auto").lower(),
        calls_poll_seconds=_int("CALLS_POLL_SECONDS", 20),
        sms_poll_seconds=_int("SMS_POLL_SECONDS", 30),
        whatsapp_mode=whatsapp_mode,
        whatsapp_bridge_url=_env("WHATSAPP_BRIDGE_URL", "http://127.0.0.1:8766"),
        whatsapp_bridge_token=_env("WHATSAPP_BRIDGE_TOKEN"),
        whatsapp_poll_seconds=_int("WHATSAPP_POLL_SECONDS", 10),
        include_groups=_bool("INCLUDE_GROUPS", False),
        google_client_id=_env("GOOGLE_CLIENT_ID"),
        google_client_secret=_env("GOOGLE_CLIENT_SECRET"),
        gmail_enabled=_bool("GMAIL_ENABLED", False),
        gmail_query=_env("GMAIL_QUERY", "is:unread category:primary newer_than:2d"),
        gmail_poll_seconds=_int("GMAIL_POLL_SECONDS", 120),
        calendar_enabled=_bool("CALENDAR_ENABLED", False),
        briefing_time=_env("BRIEFING_TIME", "08:00"),
        evening_summary_time=_env("EVENING_SUMMARY_TIME", "21:00"),
        quiet_hours=_env("QUIET_HOURS", "23:00-08:00"),
        tts_voice=_env("TTS_VOICE", "sr-RS-NicholasNeural"),
        db_path=_env("DB_PATH", "data/jarvis.db"),
        backup_keep=_int("BACKUP_KEEP", 7),
        history_limit=_int("HISTORY_LIMIT", 20),
        log_level=_env("LOG_LEVEL", "INFO"),
    )
