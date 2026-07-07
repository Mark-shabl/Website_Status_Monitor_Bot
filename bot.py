import asyncio
import logging

from telegram import Update
from telegram.ext import Application, ContextTypes

import database
import monitor
import notifications
from config import Settings

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "Доступные команды:\n"
    "/start - приветствие и инструкция\n"
    "/add <url> [название] --label <label> - добавить сайт для мониторинга\n"
    "/remove <url> - удалить сайт из мониторинга\n"
    "/list - показать все отслеживаемые сайты\n"
    "/status - текущий статус всех сайтов\n"
    "/check <url> - разовая проверка конкретного сайта\n"
    "/config <url> <минуты> - настроить интервал проверки\n"
    "/help - справка по командам"
)


def _extract_label(args: list[str]) -> tuple[list[str], str | None]:
    """Pulls "--label <value...>" out of args, returning the rest and the value.

    Everything after --label is treated as the label (it's always the last
    part of the command), so labels can contain spaces.
    """
    if "--label" not in args:
        return args, None
    idx = args.index("--label")
    if idx + 1 >= len(args):
        return args[:idx], None
    label = " ".join(args[idx + 1 :])
    rest = args[:idx]
    return rest, label


def _job_name(site_id: int) -> str:
    return f"site_check_{site_id}"


def schedule_site_job(application: Application, site, settings: Settings) -> None:
    for job in application.job_queue.get_jobs_by_name(_job_name(site.id)):
        job.schedule_removal()
    application.job_queue.run_repeating(
        check_site_job,
        interval=site.check_interval,
        first=site.check_interval,
        name=_job_name(site.id),
        data={
            "site_id": site.id,
            "url": site.url,
            "chat_id": site.chat_id,
            "label": site.label.name,
        },
    )


def unschedule_site_job(application: Application, site_id: int) -> None:
    for job in application.job_queue.get_jobs_by_name(_job_name(site_id)):
        job.schedule_removal()


async def check_site_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data
    settings: Settings = context.application.bot_data["settings"]

    result = await _run_check(data["url"], settings)
    previous = database.get_last_status(data["site_id"])
    database.record_check(data["site_id"], result)

    if previous is None:
        return

    if previous.is_ok and not result["is_ok"]:
        text = notifications.format_alert(
            data["url"], result, previous.status_code, data.get("label")
        )
        await context.bot.send_message(chat_id=data["chat_id"], text=text)
    elif not previous.is_ok and result["is_ok"]:
        text = notifications.format_recovery(data["url"], result, data.get("label"))
        await context.bot.send_message(chat_id=data["chat_id"], text=text)


async def daily_report_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    sites = database.list_sites()

    by_chat: dict[str, list] = {}
    for site in sites:
        if site.is_active:
            by_chat.setdefault(site.chat_id, []).append(site)

    for chat_id, chat_sites in by_chat.items():
        results = []
        for site in chat_sites:
            result = await _run_check(site.url, settings)
            database.record_check(site.id, result)
            results.append((site.url, result, site.label.name))
        text = notifications.format_daily_report(results)
        await context.bot.send_message(chat_id=chat_id, text=text)


async def _run_check(url: str, settings: Settings) -> dict:
    return await asyncio.to_thread(
        monitor.check_website, url, settings.timeout_seconds, settings.user_agent
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Я слежу за доступностью сайтов и уведомляю об изменениях статуса.\n\n"
        + HELP_TEXT
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT)


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Использование: /add <url> [название] --label <label>")
        return

    url = context.args[0]
    rest_args, label_name = _extract_label(context.args[1:])
    if not label_name:
        await update.message.reply_text(
            "Укажите label: /add <url> [название] --label <label>"
        )
        return

    name = " ".join(rest_args) if rest_args else None

    if not monitor.is_valid_url(url):
        await update.message.reply_text("Некорректный URL. Разрешены только http/https.")
        return

    chat_id = update.effective_chat.id
    settings: Settings = context.application.bot_data["settings"]

    if database.get_site(url, chat_id):
        await update.message.reply_text("Этот сайт уже отслеживается.")
        return

    site = database.add_site(
        url=url,
        chat_id=chat_id,
        check_interval=settings.default_check_interval,
        label_name=label_name,
        name=name,
    )
    schedule_site_job(context.application, site, settings)
    await update.message.reply_text(f"Сайт добавлен: [{label_name}] {url}")


async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Использование: /remove <url>")
        return

    url = context.args[0]
    chat_id = update.effective_chat.id
    site = database.get_site(url, chat_id)
    if site is None:
        await update.message.reply_text("Сайт не найден в списке мониторинга.")
        return

    unschedule_site_job(context.application, site.id)
    database.remove_site(url, chat_id)
    await update.message.reply_text(f"Сайт удален: {url}")


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    sites = database.list_sites(chat_id)
    if not sites:
        await update.message.reply_text("Список отслеживаемых сайтов пуст.")
        return

    lines = ["Отслеживаемые сайты:"]
    for site in sites:
        status = "активен" if site.is_active else "выключен"
        name = f" ({site.name})" if site.name else ""
        lines.append(
            f"• [{site.label.name}] {site.url}{name} - каждые {site.check_interval // 60} мин, {status}"
        )
    await update.message.reply_text("\n".join(lines))


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    sites = database.list_sites(chat_id)
    if not sites:
        await update.message.reply_text("Список отслеживаемых сайтов пуст.")
        return

    settings: Settings = context.application.bot_data["settings"]
    results = []
    for site in sites:
        result = await _run_check(site.url, settings)
        database.record_check(site.id, result)
        results.append((site.url, result, site.label.name))

    await update.message.reply_text(notifications.format_daily_report(results))


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Использование: /check <url>")
        return

    url = context.args[0]
    if not monitor.is_valid_url(url):
        await update.message.reply_text("Некорректный URL. Разрешены только http/https.")
        return

    settings: Settings = context.application.bot_data["settings"]
    result = await _run_check(url, settings)
    await update.message.reply_text(notifications.format_check_result(url, result))


async def config_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /config <url> <минуты>")
        return

    url, minutes_str = context.args[0], context.args[1]
    try:
        minutes = int(minutes_str)
        if minutes <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Интервал должен быть положительным числом минут.")
        return

    chat_id = update.effective_chat.id
    settings: Settings = context.application.bot_data["settings"]
    site = database.update_site_interval(url, chat_id, minutes * 60)
    if site is None:
        await update.message.reply_text("Сайт не найден в списке мониторинга.")
        return

    schedule_site_job(context.application, site, settings)
    await update.message.reply_text(f"Интервал проверки {url} установлен на {minutes} мин.")
