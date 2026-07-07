import datetime as dt
import logging

from telegram.ext import Application, CommandHandler

import bot
import database
from config import load_settings


def main() -> None:
    settings = load_settings()

    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )

    database.init_db(settings.database_url)

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.bot_data["settings"] = settings

    application.add_handler(CommandHandler("start", bot.start_command))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CommandHandler("add", bot.add_command))
    application.add_handler(CommandHandler("remove", bot.remove_command))
    application.add_handler(CommandHandler("list", bot.list_command))
    application.add_handler(CommandHandler("status", bot.status_command))
    application.add_handler(CommandHandler("check", bot.check_command))
    application.add_handler(CommandHandler("config", bot.config_command))

    for site in database.list_sites():
        if site.is_active:
            bot.schedule_site_job(application, site, settings)

    application.job_queue.run_daily(
        bot.daily_report_job,
        time=dt.time(hour=9, minute=0),
        name="daily_report",
    )

    application.run_polling()


if __name__ == "__main__":
    main()
