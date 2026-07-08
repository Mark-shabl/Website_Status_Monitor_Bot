import asyncio
import logging
import time

import httpx
from telegram import Update
from telegram.ext import Application, ContextTypes

import database
import monitor
import notifications
import security
from config import Settings
from database import DatabaseError
from rate_limiter import HostRateLimiter

logger = logging.getLogger(__name__)

DB_NOTIFY_COOLDOWN = 300

HELP_TEXT = (
    "Доступные команды:\n"
    "/start - приветствие и инструкция\n"
    "/add <url> [название] --label <label> - добавить сайт для мониторинга\n"
    "/remove <url> - удалить сайт из мониторинга\n"
    "/list - показать все отслеживаемые сайты\n"
    "/status - текущий статус активных сайтов\n"
    "/check <url> - разовая проверка конкретного сайта\n"
    "/config <url> <минуты> - настроить интервал проверки\n"
    "/pause <url> - приостановить мониторинг сайта\n"
    "/resume <url> - возобновить мониторинг сайта\n"
    "/pause_all - приостановить все сайты в чате\n"
    "/resume_all - возобновить все сайты в чате\n"
    "/clean_history - удалить историю проверок старше 3 дней\n"
    "/help - справка по командам"
)


def _extract_label(args: list[str]) -> tuple[list[str], str | None]:
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


def _get_client(application: Application) -> httpx.AsyncClient:
    return application.bot_data["http_client"]


def _get_rate_limiter(application: Application) -> HostRateLimiter:
    return application.bot_data["rate_limiter"]


def schedule_site_job(application: Application, site, settings: Settings) -> None:
    if not site.is_active:
        unschedule_site_job(application, site.id)
        return
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


async def _notify_db_error(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: str | int,
    message: str,
) -> None:
    notified = context.application.bot_data.setdefault("db_error_notified", {})
    now = time.monotonic()
    key = str(chat_id)
    last = notified.get(key, 0)
    if now - last < DB_NOTIFY_COOLDOWN:
        return
    notified[key] = now
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"⚠️ Ошибка базы данных: {message}\nПроверки продолжаются, но данные могут не сохраняться.",
    )


async def run_check(
    application: Application,
    settings: Settings,
    url: str,
) -> dict:
    client = _get_client(application)
    rate_limiter = _get_rate_limiter(application)
    return await monitor.check_website_with_retry(
        client,
        url,
        settings.timeout_seconds,
        settings.user_agent,
        settings.max_retry_count,
        settings.retry_delay_seconds,
        rate_limiter,
    )


async def _record_check_safe(
    context: ContextTypes.DEFAULT_TYPE,
    site_id: int,
    chat_id: str | int,
    result: dict,
) -> bool:
    try:
        await database.record_check(site_id, result)
        return True
    except DatabaseError as exc:
        logger.error("Failed to record check for site %s: %s", site_id, exc)
        await _notify_db_error(context, chat_id, str(exc))
        return False


async def check_site_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data
    settings: Settings = context.application.bot_data["settings"]

    result = await run_check(context.application, settings, data["url"])

    previous = None
    try:
        previous = await database.get_last_status(data["site_id"])
    except DatabaseError as exc:
        logger.error("Failed to read last status: %s", exc)
        await _notify_db_error(context, data["chat_id"], str(exc))

    await _record_check_safe(context, data["site_id"], data["chat_id"], result)

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
    try:
        sites = await database.list_sites()
    except DatabaseError as exc:
        logger.error("Daily report skipped: %s", exc)
        return

    by_chat: dict[str, list] = {}
    for site in sites:
        if site.is_active:
            by_chat.setdefault(site.chat_id, []).append(site)

    for chat_id, chat_sites in by_chat.items():
        results = []
        for site in chat_sites:
            result = await run_check(context.application, settings, site.url)
            await _record_check_safe(context, site.id, chat_id, result)
            results.append((site.url, result, site.label.name))
        text = notifications.format_daily_report(results)
        await context.bot.send_message(chat_id=chat_id, text=text)


async def purge_history_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    try:
        deleted = await database.purge_old_history(settings.history_retention_days)
        logger.info("Auto-purged %s history records", deleted)
    except DatabaseError as exc:
        logger.error("History purge failed: %s", exc)


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

    safe, reason = await security.is_safe_url(url)
    if not safe:
        await update.message.reply_text(
            f"URL заблокирован по соображениям безопасности: {reason}"
        )
        return

    chat_id = update.effective_chat.id
    settings: Settings = context.application.bot_data["settings"]

    try:
        existing = await database.get_site(url, chat_id)
        if existing:
            await update.message.reply_text("Этот сайт уже отслеживается.")
            return

        site = await database.add_site(
            url=url,
            chat_id=chat_id,
            check_interval=settings.default_check_interval,
            label_name=label_name,
            name=name,
        )
    except DatabaseError as exc:
        await update.message.reply_text(f"Ошибка базы данных: {exc}")
        return

    schedule_site_job(context.application, site, settings)
    await update.message.reply_text(f"Сайт добавлен: [{label_name}] {url}")


async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Использование: /remove <url>")
        return

    url = context.args[0]
    chat_id = update.effective_chat.id
    try:
        site = await database.get_site(url, chat_id)
        if site is None:
            await update.message.reply_text("Сайт не найден в списке мониторинга.")
            return
        unschedule_site_job(context.application, site.id)
        await database.remove_site(url, chat_id)
    except DatabaseError as exc:
        await update.message.reply_text(f"Ошибка базы данных: {exc}")
        return

    await update.message.reply_text(f"Сайт удален: {url}")


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    try:
        sites = await database.list_sites(chat_id)
    except DatabaseError as exc:
        await update.message.reply_text(f"Ошибка базы данных: {exc}")
        return

    if not sites:
        await update.message.reply_text("Список отслеживаемых сайтов пуст.")
        return

    lines = ["Отслеживаемые сайты:"]
    for site in sites:
        status = "активен" if site.is_active else "на паузе"
        name = f" ({site.name})" if site.name else ""
        lines.append(
            f"• [{site.label.name}] {site.url}{name} - каждые {site.check_interval // 60} мин, {status}"
        )
    await update.message.reply_text("\n".join(lines))


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    try:
        sites = await database.list_sites(chat_id)
    except DatabaseError as exc:
        await update.message.reply_text(f"Ошибка базы данных: {exc}")
        return

    active_sites = [site for site in sites if site.is_active]
    if not active_sites:
        await update.message.reply_text("Нет активных сайтов для проверки.")
        return

    settings: Settings = context.application.bot_data["settings"]

    async def check_one(site):
        result = await run_check(context.application, settings, site.url)
        await _record_check_safe(context, site.id, chat_id, result)
        return site.url, result, site.label.name

    results = await asyncio.gather(*(check_one(site) for site in active_sites))
    await update.message.reply_text(notifications.format_daily_report(list(results)))


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Использование: /check <url>")
        return

    url = context.args[0]
    if not monitor.is_valid_url(url):
        await update.message.reply_text("Некорректный URL. Разрешены только http/https.")
        return

    settings: Settings = context.application.bot_data["settings"]
    result = await run_check(context.application, settings, url)
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
    try:
        site = await database.update_site_interval(url, chat_id, minutes * 60)
        if site is None:
            await update.message.reply_text("Сайт не найден в списке мониторинга.")
            return
    except DatabaseError as exc:
        await update.message.reply_text(f"Ошибка базы данных: {exc}")
        return

    schedule_site_job(context.application, site, settings)
    await update.message.reply_text(f"Интервал проверки {url} установлен на {minutes} мин.")


async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Использование: /pause <url>")
        return

    url = context.args[0]
    chat_id = update.effective_chat.id
    try:
        site = await database.set_site_active(url, chat_id, False)
        if site is None:
            await update.message.reply_text("Сайт не найден в списке мониторинга.")
            return
    except DatabaseError as exc:
        await update.message.reply_text(f"Ошибка базы данных: {exc}")
        return

    unschedule_site_job(context.application, site.id)
    await update.message.reply_text(f"Мониторинг приостановлен: {url}")


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Использование: /resume <url>")
        return

    url = context.args[0]
    chat_id = update.effective_chat.id
    settings: Settings = context.application.bot_data["settings"]
    try:
        site = await database.set_site_active(url, chat_id, True)
        if site is None:
            await update.message.reply_text("Сайт не найден в списке мониторинга.")
            return
    except DatabaseError as exc:
        await update.message.reply_text(f"Ошибка базы данных: {exc}")
        return

    schedule_site_job(context.application, site, settings)
    await update.message.reply_text(f"Мониторинг возобновлен: {url}")


async def pause_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    try:
        count = await database.set_all_active(chat_id, False)
        sites = await database.list_sites(chat_id)
    except DatabaseError as exc:
        await update.message.reply_text(f"Ошибка базы данных: {exc}")
        return

    for site in sites:
        unschedule_site_job(context.application, site.id)

    await update.message.reply_text(f"Мониторинг приостановлен для {count} сайтов.")


async def resume_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    settings: Settings = context.application.bot_data["settings"]
    try:
        await database.set_all_active(chat_id, True)
        sites = await database.list_sites(chat_id)
    except DatabaseError as exc:
        await update.message.reply_text(f"Ошибка базы данных: {exc}")
        return

    for site in sites:
        schedule_site_job(context.application, site, settings)

    await update.message.reply_text(f"Мониторинг возобновлен для {len(sites)} сайтов.")


async def clean_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    settings: Settings = context.application.bot_data["settings"]
    try:
        deleted = await database.purge_old_history(
            settings.history_retention_days, chat_id=chat_id
        )
    except DatabaseError as exc:
        await update.message.reply_text(f"Ошибка базы данных: {exc}")
        return

    await update.message.reply_text(
        f"Удалено {deleted} записей истории старше {settings.history_retention_days} дней."
    )
