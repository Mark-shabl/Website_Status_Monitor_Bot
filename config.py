import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    default_check_interval: int
    max_retry_count: int
    retry_delay_seconds: int
    timeout_seconds: int
    user_agent: str
    database_url: str
    log_level: str
    host_rate_limit_seconds: int
    history_retention_days: int
    report_timezone: str
    report_hour: int
    report_minute: int
    purge_hour: int
    purge_minute: int


def resolve_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def load_settings() -> Settings:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and fill it in."
        )

    return Settings(
        telegram_bot_token=token,
        default_check_interval=int(os.environ.get("DEFAULT_CHECK_INTERVAL", "300")),
        max_retry_count=int(os.environ.get("MAX_RETRY_COUNT", "3")),
        retry_delay_seconds=int(os.environ.get("RETRY_DELAY_SECONDS", "5")),
        timeout_seconds=int(os.environ.get("TIMEOUT_SECONDS", "10")),
        user_agent=os.environ.get("USER_AGENT", "SiteMonitorBot/1.0"),
        database_url=os.environ.get("DATABASE_URL", "sqlite:///sites.db"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        host_rate_limit_seconds=int(os.environ.get("HOST_RATE_LIMIT_SECONDS", "30")),
        history_retention_days=int(os.environ.get("HISTORY_RETENTION_DAYS", "3")),
        report_timezone=os.environ.get("REPORT_TIMEZONE", "Europe/Moscow"),
        report_hour=int(os.environ.get("REPORT_HOUR", "9")),
        report_minute=int(os.environ.get("REPORT_MINUTE", "0")),
        purge_hour=int(os.environ.get("PURGE_HOUR", "3")),
        purge_minute=int(os.environ.get("PURGE_MINUTE", "0")),
    )
