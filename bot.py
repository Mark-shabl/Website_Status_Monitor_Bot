import asyncio
import logging
import re
import time

import httpx
from telegram import BotCommand, MessageEntity, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

import database
import monitor
import notifications
import security
from config import Settings
from database import DatabaseError
from rate_limiter import HostRateLimiter

logger = logging.getLogger(__name__)

DB_NOTIFY_COOLDOWN = 300
TELEGRAM_MESSAGE_LIMIT = 4096


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


def _is_bot_mentioned(message, bot_username: str) -> bool:
    if not message.text or not message.entities:
        return False
    needle = f"@{bot_username}".lower()
    for entity in message.entities:
        if entity.type == MessageEntity.MENTION:
            fragment = message.text[entity.offset : entity.offset + entity.length]
            if fragment.lower() == needle:
                return True
    return False


def parse_mention_command(text: str, bot_username: str) -> tuple[str, list[str]] | None:
    mention_pattern = re.compile(rf"@{re.escape(bot_username)}\s*", re.IGNORECASE)
    if not mention_pattern.search(text):
        return None

    rest = mention_pattern.sub("", text, count=1).strip()
    if not rest:
        return "help", []

    if rest.startswith("/"):
        rest = rest[1:]

    parts = rest.split()
    if not parts:
        return "help", []

    command = parts[0].split("@")[0].lower()
    return command, parts[1:]


def _get_client(application: Application) -> httpx.AsyncClient:
    return application.bot_data["http_client"]


def _get_rate_limiter(application: Application) -> HostRateLimiter:
    return application.bot_data["rate_limiter"]


def _format_interval(seconds: int) -> str:
    if seconds >= 60:
        return f"каждые {seconds // 60} мин"
    return f"каждые {seconds} сек"


def split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in text.split("\n"):
        line_len = len(line) + (1 if current else 0)
        if line_len > limit:
            if current:
                parts.append("\n".join(current))
                current = []
                current_len = 0
            for i in range(0, len(line), limit):
                parts.append(line[i : i + limit])
            continue

        if current_len + line_len > limit:
            parts.append("\n".join(current))
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += line_len

    if current:
        parts.append("\n".join(current))
    return parts


def _get_site_check_lock(application: Application, site_id: int) -> asyncio.Lock:
    locks: dict[int, asyncio.Lock] = application.bot_data.setdefault(
        "site_check_locks", {}
    )
    if site_id not in locks:
        locks[site_id] = asyncio.Lock()
    return locks[site_id]


async def _get_thread_id(chat_id: str | int) -> int | None:
    try:
        return await database.get_chat_thread_id(chat_id)
    except DatabaseError as exc:
        logger.error("Failed to read chat thread setting for %s: %s", chat_id, exc)
        return None


async def _send_long_message(bot, chat_id: str | int, text: str) -> None:
    thread_id = await _get_thread_id(chat_id)
    for chunk in split_message(text):
        await bot.send_message(chat_id=chat_id, text=chunk, message_thread_id=thread_id)


async def _reply_long_message(update: Update, text: str) -> None:
    for chunk in split_message(text):
        await update.message.reply_text(chunk)


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
    thread_id = await _get_thread_id(chat_id)
    await context.bot.send_message(
        chat_id=chat_id,
        text=notifications.format_db_error(message),
        message_thread_id=thread_id,
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
    site_id = data["site_id"]
    lock = _get_site_check_lock(context.application, site_id)
    if lock.locked():
        logger.debug("Skipping overlapping check for site %s", site_id)
        return

    async with lock:
        settings: Settings = context.application.bot_data["settings"]

        result = await run_check(context.application, settings, data["url"])

        previous = None
        try:
            previous = await database.get_last_status(site_id)
        except DatabaseError as exc:
            logger.error("Failed to read last status: %s", exc)
            await _notify_db_error(context, data["chat_id"], str(exc))

        await _record_check_safe(context, site_id, data["chat_id"], result)

        if previous is None:
            return

        if previous.is_ok and not result["is_ok"]:
            text = notifications.format_alert(
                data["url"], result, previous.status_code, data.get("label")
            )
            thread_id = await _get_thread_id(data["chat_id"])
            await context.bot.send_message(
                chat_id=data["chat_id"], text=text, message_thread_id=thread_id
            )
        elif not previous.is_ok and result["is_ok"]:
            text = notifications.format_recovery(data["url"], result, data.get("label"))
            thread_id = await _get_thread_id(data["chat_id"])
            await context.bot.send_message(
                chat_id=data["chat_id"], text=text, message_thread_id=thread_id
            )


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
        await _send_long_message(context.bot, chat_id, text)


async def purge_history_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    try:
        deleted = await database.purge_old_history(settings.history_retention_days)
        logger.info("Auto-purged %s history records", deleted)
    except DatabaseError as exc:
        logger.error("History purge failed: %s", exc)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = context.bot.username
    await _reply_long_message(update, notifications.format_welcome(username))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(notifications.format_help(context.bot.username))


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            notifications.format_usage("/add https://example.com My Site --label prod")
        )
        return

    url = context.args[0]
    rest_args, label_name = _extract_label(context.args[1:])
    if not label_name:
        await update.message.reply_text(
            notifications.format_info(
                "Нужен label",
                "Укажите группу для сайта:\n/add <url> [имя] --label <label>",
            )
        )
        return

    name = " ".join(rest_args) if rest_args else None

    if not monitor.is_valid_url(url):
        await update.message.reply_text(
            notifications.format_error(
                "Некорректный URL",
                "Разрешены только адреса с http:// или https://",
            )
        )
        return

    safe, reason = await security.is_safe_url(url)
    if not safe:
        await update.message.reply_text(
            notifications.format_error("URL заблокирован", reason or "небезопасный адрес")
        )
        return

    chat_id = update.effective_chat.id
    settings: Settings = context.application.bot_data["settings"]

    try:
        existing = await database.get_site(url, chat_id)
        if existing:
            await update.message.reply_text(
                notifications.format_info("Уже в списке", f"Сайт уже отслеживается:\n{url}")
            )
            return

        site = await database.add_site(
            url=url,
            chat_id=chat_id,
            check_interval=settings.default_check_interval,
            label_name=label_name,
            name=name,
        )
    except DatabaseError as exc:
        await update.message.reply_text(notifications.format_db_error(str(exc)))
        return

    schedule_site_job(context.application, site, settings)
    body = f"🏷 {label_name}\n🔗 {url}\n⏱ каждые {settings.default_check_interval // 60} мин"
    if name:
        body = f"📝 {name}\n" + body
    await update.message.reply_text(notifications.format_success("Сайт добавлен", body))


async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(notifications.format_usage("/remove https://example.com"))
        return

    url = context.args[0]
    chat_id = update.effective_chat.id
    try:
        site = await database.get_site(url, chat_id)
        if site is None:
            await update.message.reply_text(
                notifications.format_info("Не найден", f"Сайт не в мониторинге:\n{url}")
            )
            return
        unschedule_site_job(context.application, site.id)
        await database.remove_site(url, chat_id)
    except DatabaseError as exc:
        await update.message.reply_text(notifications.format_db_error(str(exc)))
        return

    await update.message.reply_text(
        notifications.format_success("Сайт удалён", f"🔗 {url}\nМониторинг остановлен.")
    )


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    try:
        sites = await database.list_sites(chat_id)
    except DatabaseError as exc:
        await update.message.reply_text(notifications.format_db_error(str(exc)))
        return

    if not sites:
        await update.message.reply_text(notifications.format_site_list([]))
        return

    items = [
        notifications.format_site_list_item(
            site.label.name,
            site.url,
            _format_interval(site.check_interval),
            site.is_active,
            site.name,
        )
        for site in sites
    ]
    await _reply_long_message(update, notifications.format_site_list(items))


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    try:
        sites = await database.list_sites(chat_id)
    except DatabaseError as exc:
        await update.message.reply_text(notifications.format_db_error(str(exc)))
        return

    active_sites = [site for site in sites if site.is_active]
    if not active_sites:
        await update.message.reply_text(
            notifications.format_info(
                "Нет активных сайтов",
                "Все сайты на паузе или список пуст.\n/resume <url> — возобновить мониторинг",
            )
        )
        return

    settings: Settings = context.application.bot_data["settings"]

    async def check_one(site):
        result = await run_check(context.application, settings, site.url)
        await _record_check_safe(context, site.id, chat_id, result)
        return site.url, result, site.label.name

    results = await asyncio.gather(*(check_one(site) for site in active_sites))
    await _reply_long_message(
        update,
        notifications.format_status_report(
            list(results),
            title="📊 Текущий статус",
        ),
    )


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(notifications.format_usage("/check https://example.com"))
        return

    url = context.args[0]
    if not monitor.is_valid_url(url):
        await update.message.reply_text(
            notifications.format_error(
                "Некорректный URL",
                "Разрешены только адреса с http:// или https://",
            )
        )
        return

    settings: Settings = context.application.bot_data["settings"]
    result = await run_check(context.application, settings, url)
    await update.message.reply_text(notifications.format_check_result(url, result))


async def config_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.message.reply_text(
            notifications.format_usage("/config https://example.com 10")
        )
        return

    url, minutes_str = context.args[0], context.args[1]
    try:
        minutes = int(minutes_str)
        if minutes <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            notifications.format_error(
                "Неверный интервал",
                "Укажите положительное число минут, например: 5 или 30",
            )
        )
        return

    chat_id = update.effective_chat.id
    settings: Settings = context.application.bot_data["settings"]
    try:
        site = await database.update_site_interval(url, chat_id, minutes * 60)
        if site is None:
            await update.message.reply_text(
                notifications.format_info("Не найден", f"Сайт не в мониторинге:\n{url}")
            )
            return
    except DatabaseError as exc:
        await update.message.reply_text(notifications.format_db_error(str(exc)))
        return

    schedule_site_job(context.application, site, settings)
    await update.message.reply_text(
        notifications.format_success(
            "Интервал обновлён",
            f"🔗 {url}\n⏱ проверка каждые {minutes} мин",
        )
    )


async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(notifications.format_usage("/pause https://example.com"))
        return

    url = context.args[0]
    chat_id = update.effective_chat.id
    try:
        site = await database.set_site_active(url, chat_id, False)
        if site is None:
            await update.message.reply_text(
                notifications.format_info("Не найден", f"Сайт не в мониторинге:\n{url}")
            )
            return
    except DatabaseError as exc:
        await update.message.reply_text(notifications.format_db_error(str(exc)))
        return

    unschedule_site_job(context.application, site.id)
    await update.message.reply_text(
        notifications.format_info(
            "Мониторинг на паузе",
            f"🔗 {url}\n/resume {url} — возобновить",
        )
    )


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(notifications.format_usage("/resume https://example.com"))
        return

    url = context.args[0]
    chat_id = update.effective_chat.id
    settings: Settings = context.application.bot_data["settings"]
    try:
        site = await database.set_site_active(url, chat_id, True)
        if site is None:
            await update.message.reply_text(
                notifications.format_info("Не найден", f"Сайт не в мониторинге:\n{url}")
            )
            return
    except DatabaseError as exc:
        await update.message.reply_text(notifications.format_db_error(str(exc)))
        return

    schedule_site_job(context.application, site, settings)
    await update.message.reply_text(
        notifications.format_success(
            "Мониторинг возобновлён",
            f"🔗 {url}\n⏱ {_format_interval(site.check_interval)}",
        )
    )


async def pause_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    try:
        count = await database.set_all_active(chat_id, False)
        sites = await database.list_sites(chat_id)
    except DatabaseError as exc:
        await update.message.reply_text(notifications.format_db_error(str(exc)))
        return

    for site in sites:
        unschedule_site_job(context.application, site.id)

    await update.message.reply_text(
        notifications.format_info(
            "Все сайты на паузе",
            f"⏸ Приостановлено: {count} сайт(ов)\n/resume_all — возобновить все",
        )
    )


async def resume_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    settings: Settings = context.application.bot_data["settings"]
    try:
        await database.set_all_active(chat_id, True)
        sites = await database.list_sites(chat_id)
    except DatabaseError as exc:
        await update.message.reply_text(notifications.format_db_error(str(exc)))
        return

    for site in sites:
        schedule_site_job(context.application, site, settings)

    await update.message.reply_text(
        notifications.format_success(
            "Мониторинг возобновлён",
            f"🟢 Активных сайтов: {len(sites)}",
        )
    )


async def clean_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    settings: Settings = context.application.bot_data["settings"]
    try:
        deleted = await database.purge_old_history(
            settings.history_retention_days, chat_id=chat_id
        )
    except DatabaseError as exc:
        await update.message.reply_text(notifications.format_db_error(str(exc)))
        return

    await update.message.reply_text(
        notifications.format_success(
            "История очищена",
            f"🗑 Удалено записей: {deleted}\n"
            f"📅 Старше {settings.history_retention_days} дней",
        )
    )


async def set_topic_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    chat_id = update.effective_chat.id

    if context.args and context.args[0].lower() in ("general", "reset", "сброс"):
        try:
            await database.set_chat_thread_id(chat_id, None)
        except DatabaseError as exc:
            await message.reply_text(notifications.format_db_error(str(exc)))
            return
        await message.reply_text(
            notifications.format_success(
                "Тема сброшена",
                "Уведомления снова будут приходить в основной чат (General).",
            )
        )
        return

    if not getattr(message, "is_topic_message", False):
        await message.reply_text(
            notifications.format_error(
                "Нужна тема",
                "Выполните эту команду внутри темы (топика), куда должны "
                "приходить уведомления.\n"
                "Чтобы сбросить на основной чат: /set_topic general",
            )
        )
        return

    thread_id = message.message_thread_id
    try:
        await database.set_chat_thread_id(chat_id, thread_id)
    except DatabaseError as exc:
        await message.reply_text(notifications.format_db_error(str(exc)))
        return

    await message.reply_text(
        notifications.format_success(
            "Тема установлена",
            "Уведомления и отчёты теперь будут приходить в эту тему.",
        )
    )


COMMAND_HANDLERS = {
    "start": start_command,
    "help": help_command,
    "add": add_command,
    "remove": remove_command,
    "list": list_command,
    "status": status_command,
    "check": check_command,
    "config": config_command,
    "pause": pause_command,
    "resume": resume_command,
    "pause_all": pause_all_command,
    "resume_all": resume_all_command,
    "clean_history": clean_history_command,
    "set_topic": set_topic_command,
}


async def mention_command_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.message
    if message is None or not message.text:
        return

    bot_username = context.bot.username
    if not bot_username or not _is_bot_mentioned(message, bot_username):
        return

    parsed = parse_mention_command(message.text, bot_username)
    if parsed is None:
        return

    command, args = parsed
    handler = COMMAND_HANDLERS.get(command)
    if handler is None:
        await message.reply_text(
            notifications.format_error(
                "Неизвестная команда",
                notifications.format_group_command_hint(bot_username, "help"),
            )
        )
        return

    context.args = args
    await handler(update, context)


def register_handlers(application: Application) -> None:
    # @BotName /add ... has the mention at offset 0, so CommandHandler ignores it
    # and ~filters.COMMAND skips the mention handler. Handle mentions first.
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.Entity(MessageEntity.MENTION),
            mention_command_handler,
        )
    )
    for name, callback in COMMAND_HANDLERS.items():
        application.add_handler(CommandHandler(name, callback))


BOT_COMMANDS = [
    BotCommand("start", "Приветствие и инструкция"),
    BotCommand("help", "Справка по командам"),
    BotCommand("add", "Добавить сайт для мониторинга"),
    BotCommand("remove", "Удалить сайт"),
    BotCommand("list", "Список сайтов"),
    BotCommand("status", "Проверить активные сайты"),
    BotCommand("check", "Разовая проверка URL"),
    BotCommand("config", "Интервал проверки в минутах"),
    BotCommand("pause", "Приостановить мониторинг сайта"),
    BotCommand("resume", "Возобновить мониторинг сайта"),
    BotCommand("pause_all", "Пауза для всех сайтов"),
    BotCommand("resume_all", "Возобновить все сайты"),
    BotCommand("clean_history", "Очистить старую историю"),
    BotCommand("set_topic", "Куда слать уведомления (тема группы)"),
]


async def setup_bot_commands(application: Application) -> None:
    await application.bot.set_my_commands(BOT_COMMANDS)
