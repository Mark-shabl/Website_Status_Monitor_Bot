import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    admin_chat_id: str
    default_check_interval: int
    max_retry_count: int
    timeout_seconds: int
    user_agent: str
    database_url: str
    log_level: str


def load_settings() -> Settings:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and fill it in."
        )

    return Settings(
        telegram_bot_token=token,
        admin_chat_id=os.environ.get("ADMIN_CHAT_ID", ""),
        default_check_interval=int(os.environ.get("DEFAULT_CHECK_INTERVAL", "300")),
        max_retry_count=int(os.environ.get("MAX_RETRY_COUNT", "3")),
        timeout_seconds=int(os.environ.get("TIMEOUT_SECONDS", "10")),
        user_agent=os.environ.get("USER_AGENT", "SiteMonitorBot/1.0"),
        database_url=os.environ.get("DATABASE_URL", "sqlite:///sites.db"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
