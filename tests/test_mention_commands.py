import pytest
from unittest.mock import AsyncMock, MagicMock

from telegram import MessageEntity

import bot
from config import Settings


def test_parse_mention_command_with_slash():
    result = bot.parse_mention_command(
        "@SiteBot /add https://example.com --label prod",
        "SiteBot",
    )
    assert result == ("add", ["https://example.com", "--label", "prod"])


def test_parse_mention_command_without_slash():
    result = bot.parse_mention_command(
        "@SiteBot add https://example.com --label prod",
        "SiteBot",
    )
    assert result == ("add", ["https://example.com", "--label", "prod"])


def test_parse_mention_command_with_bot_suffix():
    result = bot.parse_mention_command(
        "@SiteBot /add@SiteBot https://example.com --label prod",
        "SiteBot",
    )
    assert result == ("add", ["https://example.com", "--label", "prod"])


def test_parse_mention_command_empty_shows_help():
    assert bot.parse_mention_command("@SiteBot", "SiteBot") == ("help", [])


def test_parse_mention_command_wrong_bot():
    assert bot.parse_mention_command("@OtherBot add https://x.com", "SiteBot") is None


@pytest.mark.asyncio
async def test_mention_slash_add_command_responds(app_settings):
    """@Bot /add ... is ignored by CommandHandler (command offset != 0)."""
    update = MagicMock()
    update.message.text = "@SiteBot /add https://example.com"
    update.message.entities = [
        MagicMock(type=MessageEntity.MENTION, offset=0, length=8),
        MagicMock(type=MessageEntity.BOT_COMMAND, offset=9, length=4),
    ]
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.bot.username = "SiteBot"
    context.args = []

    await bot.mention_command_handler(update, context)

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0]
    assert "label" in text.lower()


@pytest.fixture
def app_settings():
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
