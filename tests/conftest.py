import pytest

import database
from config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        telegram_bot_token="test-token",
        default_check_interval=300,
        max_retry_count=3,
        retry_delay_seconds=0,
        timeout_seconds=5,
        user_agent="TestBot/1.0",
        database_url="sqlite+aiosqlite:///:memory:",
        log_level="INFO",
        host_rate_limit_seconds=0,
        history_retention_days=3,
        report_timezone="UTC",
        report_hour=9,
        report_minute=0,
        purge_hour=3,
        purge_minute=0,
    )


@pytest.fixture
async def db(settings):
    await database.close_db()
    ok = await database.init_db(settings.database_url)
    assert ok
    yield
    await database.close_db()
