import datetime as dt
import logging

import httpx
from telegram.ext import Application, CommandHandler

import bot
import database
from config import load_settings, resolve_timezone
from monitor import build_http_client
from rate_limiter import HostRateLimiter

logger = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    settings = application.bot_data["settings"]
    application.bot_data["http_client"] = build_http_client(settings.user_agent)
    application.bot_data["rate_limiter"] = HostRateLimiter(settings.host_rate_limit_seconds)
    application.bot_data["db_error_notified"] = {}

    available = await database.init_db(settings.database_url)
    if not available:
        logger.error("Database unavailable at startup; bot will run without persistence")
    else:
        for site in await database.list_sites():
            if site.is_active:
                bot.schedule_site_job(application, site, settings)

    tz = resolve_timezone(settings.report_timezone)
    if str(tz) != settings.report_timezone:
        logger.warning(
            "Invalid REPORT_TIMEZONE %r, falling back to UTC", settings.report_timezone
        )

    application.job_queue.run_daily(
        bot.daily_report_job,
        time=dt.time(
            hour=settings.report_hour,
            minute=settings.report_minute,
            tzinfo=tz,
        ),
        name="daily_report",
    )
    application.job_queue.run_daily(
        bot.purge_history_job,
        time=dt.time(
            hour=settings.purge_hour,
            minute=settings.purge_minute,
            tzinfo=tz,
        ),
        name="purge_history",
    )


async def post_shutdown(application: Application) -> None:
    client: httpx.AsyncClient | None = application.bot_data.get("http_client")
    if client is not None:
        await client.aclose()
    await database.close_db()


def main() -> None:
    settings = load_settings()

    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )

    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.bot_data["settings"] = settings

    handlers = [
        ("start", bot.start_command),
        ("help", bot.help_command),
        ("add", bot.add_command),
        ("remove", bot.remove_command),
        ("list", bot.list_command),
        ("status", bot.status_command),
        ("check", bot.check_command),
        ("config", bot.config_command),
        ("pause", bot.pause_command),
        ("resume", bot.resume_command),
        ("pause_all", bot.pause_all_command),
        ("resume_all", bot.resume_all_command),
        ("clean_history", bot.clean_history_command),
    ]
    for name, callback in handlers:
        application.add_handler(CommandHandler(name, callback))

    application.run_polling()


if __name__ == "__main__":
    main()
