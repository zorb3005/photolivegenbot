import os
from dataclasses import dataclass
from typing import Tuple


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")

def _env_int_list(name: str) -> Tuple[int, ...]:
    raw = os.getenv(name, "") or ""
    items = [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]
    out: list[int] = []
    for item in items:
        try:
            out.append(int(item))
        except ValueError:
            continue
    return tuple(out)

@dataclass(frozen=True)
class Settings:
    # DB
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/motionportrait_bot_v2"
    )

    # App
    BASE_URL: str = os.getenv("BASE_URL", "http://localhost:8000")  # публичный URL API (для return_url)
    ENV: str = os.getenv("ENV", "dev")

    # Telegram
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    TELEGRAM_VERIFY_SSL: bool = _env_bool("TELEGRAM_VERIFY_SSL", False)
    TELEGRAM_CA_BUNDLE: str | None = os.getenv("TELEGRAM_CA_BUNDLE") or None

    # YooKassa
    YK_SHOP_ID: str = os.getenv("YK_SHOP_ID", "")
    YK_SECRET_KEY: str = os.getenv("YK_SECRET_KEY", "")
    YK_API_URL: str = os.getenv("YK_API_URL", "https://api.yookassa.ru/v3")

    # Платёжные пресеты (демо)
    TOKENS_LIGHT: int = int(os.getenv("TOKENS_LIGHT", "300"))
    PRICE_LIGHT_RUB: str = os.getenv("PRICE_LIGHT_RUB", "90.00")

    # Referral
    BOT_USERNAME: str = os.getenv("BOT_USERNAME", "")
    REFERRAL_INVITER_BONUS: int = int(os.getenv("REFERRAL_INVITER_BONUS", "200"))
    REFERRAL_INVITEE_BONUS: int = int(os.getenv("REFERRAL_INVITEE_BONUS", "200"))
    STEOS_API_TOKEN: str = os.getenv("STEOS_API_TOKEN", "")
    STEOS_DEFAULT_VOICE_ID: str = os.getenv("STEOS_DEFAULT_VOICE_ID", "")
    ELEVENLABS_DEFAULT_VOICE_ID: str = os.getenv("ELEVENLABS_DEFAULT_VOICE_ID", "")
    TOPMEDIAI_API_KEY: str = os.getenv("TOPMEDIAI_API_KEY", "")
    SPEECHIFY_API_KEY: str = os.getenv("SPEECHIFY_API_KEY", "")
    ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")
    VOICE_CLONE_COST_TOKENS: int = int(os.getenv("VOICE_CLONE_COST_TOKENS", "50000"))
    SUBSCRIBE_CHANNEL_URL: str = os.getenv("SUBSCRIBE_CHANNEL_URL", "")
    SUBSCRIBE_CHANNEL_URL_1: str = os.getenv("SUBSCRIBE_CHANNEL_URL_1", "")
    SUBSCRIBE_CHANNEL_URL_2: str = os.getenv("SUBSCRIBE_CHANNEL_URL_2", "")
    FREE_TIER_BONUS_TOKENS: int = int(os.getenv("FREE_TIER_BONUS_TOKENS", "100"))
    SUBSCRIBE_CHANNEL_ID_1: str = os.getenv("SUBSCRIBE_CHANNEL_ID_1", "")
    SUBSCRIBE_CHANNEL_ID_2: str = os.getenv("SUBSCRIBE_CHANNEL_ID_2", "")

    # KlingAI
    KLINGAI_ACCESS_KEY: str = os.getenv("KLINGAI_ACCESS_KEY", "")
    KLINGAI_SECRET_KEY: str = os.getenv("KLINGAI_SECRET_KEY", "")
    KLINGAI_BASE_URL: str = os.getenv("KLINGAI_BASE_URL", "https://api-singapore.klingai.com")

    # API cost tracking (per generation)
    KLINGAI_COST_USD: str = os.getenv("KLINGAI_COST_USD", "0")
    USD_RATE_RUB: str = os.getenv("USD_RATE_RUB", "100")

    # Admins
    ADMIN_IDS: Tuple[int, ...] = _env_int_list("ADMIN_IDS")
    HARDCODED_ADMIN_IDS: Tuple[int, ...] = _env_int_list("HARDCODED_ADMIN_IDS")
settings = Settings()
