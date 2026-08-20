from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.ext import Application

import bot
from config import Settings


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


def _make_update(args=None, chat_id=123):
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.message.reply_text = AsyncMock()
    update.args = args or []
    return update


def _make_context(app_settings):
    context = MagicMock()
    application = MagicMock(spec=Application)
    application.bot_data = {
        "settings": app_settings,
        "http_client": MagicMock(),
        "rate_limiter": MagicMock(),
    }
    application.job_queue.get_jobs_by_name.return_value = []
    context.application = application
    context.bot = MagicMock()
    context.bot.username = "TestBot"
    context.args = []
    return context


@pytest.mark.asyncio
async def test_start_command(app_settings):
    update = _make_update()
    context = _make_context(app_settings)
    await bot.start_command(update, context)
    update.message.reply_text.assert_awaited_once()
    assert "Site Health Checker" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_add_command_requires_label(app_settings):
    update = _make_update(args=["https://example.com"])
    context = _make_context(app_settings)
    context.args = update.args
    await bot.add_command(update, context)
    text = update.message.reply_text.await_args.args[0]
    assert "label" in text.lower() or "label" in text


@pytest.mark.asyncio
async def test_add_command_success(mocker, app_settings):
    mocker.patch("bot.database.get_site", AsyncMock(return_value=None))
    mock_add_site = mocker.patch("bot.database.add_site", AsyncMock())
    mocker.patch("bot.security.is_safe_url", AsyncMock(return_value=(True, None)))

    site = MagicMock()
    site.id = 1
    site.is_active = True
    site.check_interval = 300
    site.url = "https://example.com"
    site.chat_id = "123"
    site.label.name = "prod"
    mock_add_site.return_value = site

    update = _make_update(args=["https://example.com", "--label", "prod"])
    context = _make_context(app_settings)
    context.args = update.args

    await bot.add_command(update, context)
    assert "добавлен" in update.message.reply_text.await_args.args[0].lower()


@pytest.mark.asyncio
@patch("bot.database.list_sites", AsyncMock(return_value=[]))
async def test_list_command_empty(app_settings):
    update = _make_update()
    context = _make_context(app_settings)
    await bot.list_command(update, context)
    assert "пуст" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
@patch("bot.database.purge_old_history", AsyncMock(return_value=7))
async def test_clean_history_command(app_settings):
    update = _make_update()
    context = _make_context(app_settings)
    await bot.clean_history_command(update, context)
    text = update.message.reply_text.await_args.args[0]
    assert "7" in text


@pytest.mark.asyncio
async def test_set_topic_command_requires_topic(app_settings):
    update = _make_update()
    update.message.is_topic_message = False
    context = _make_context(app_settings)
    await bot.set_topic_command(update, context)
    text = update.message.reply_text.await_args.args[0]
    assert "тем" in text.lower()


@pytest.mark.asyncio
async def test_set_topic_command_sets_thread(mocker, app_settings):
    mock_set = mocker.patch("bot.database.set_chat_thread_id", AsyncMock())
    update = _make_update()
    update.message.is_topic_message = True
    update.message.message_thread_id = 42
    context = _make_context(app_settings)
    await bot.set_topic_command(update, context)
    mock_set.assert_awaited_once_with(123, 42)
    text = update.message.reply_text.await_args.args[0]
    assert "установлена" in text.lower()


@pytest.mark.asyncio
async def test_set_topic_command_reset(mocker, app_settings):
    mock_set = mocker.patch("bot.database.set_chat_thread_id", AsyncMock())
    update = _make_update(args=["general"])
    update.message.is_topic_message = False
    context = _make_context(app_settings)
    context.args = update.args
    await bot.set_topic_command(update, context)
    mock_set.assert_awaited_once_with(123, None)
    text = update.message.reply_text.await_args.args[0]
    assert "сброшена" in text.lower()
