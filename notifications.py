from datetime import datetime, timezone


def _fmt_time(ts: datetime) -> str:
    return ts.strftime("%d.%m.%Y %H:%M")


def _fmt_response_time(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    return f"{seconds:.2f} сек"


def _label_line(label_name: str | None) -> str:
    if not label_name:
        return ""
    return f"🏷 Проект: {label_name}\n"


def _status_display(result: dict) -> str:
    code = result.get("status_code")
    if code is not None:
        return str(code)
    return "нет ответа"


def _error_detail(result: dict) -> str:
    if result.get("error"):
        return str(result["error"])
    code = result.get("status_code")
    if code is not None:
        return f"HTTP {code}"
    return "Неизвестная ошибка"


def format_alert(
    url: str, result: dict, previous_status_code: int | None, label_name: str | None = None
) -> str:
    previous = (
        f"✅ {previous_status_code} OK"
        if previous_status_code == 200
        else "❓ неизвестно"
    )
    current = f"❌ {_status_display(result)}"
    return (
        "🔴 Сайт недоступен\n"
        "────────────────\n"
        f"{_label_line(label_name)}"
        f"🔗 {url}\n"
        "\n"
        f"📉 Было → стало: {previous} → {current}\n"
        f"⏱ Проверка: {_fmt_time(result['timestamp'])}\n"
        f"💬 {_error_detail(result)}"
    )


def format_recovery(url: str, result: dict, label_name: str | None = None) -> str:
    return (
        "🟢 Сайт восстановлен\n"
        "────────────────\n"
        f"{_label_line(label_name)}"
        f"🔗 {url}\n"
        "\n"
        f"📈 Статус: ✅ {result.get('status_code')} OK\n"
        f"⚡ Отклик: {_fmt_response_time(result.get('response_time'))}\n"
        f"⏱ Проверка: {_fmt_time(result['timestamp'])}"
    )


def format_check_result(url: str, result: dict) -> str:
    if result.get("is_ok"):
        return (
            "✅ Проверка пройдена\n"
            "────────────────\n"
            f"🔗 {url}\n"
            f"📈 Статус: {result['status_code']} OK\n"
            f"⚡ Отклик: {_fmt_response_time(result.get('response_time'))}"
        )
    return (
        "❌ Проблема при проверке\n"
        "────────────────\n"
        f"🔗 {url}\n"
        f"📈 Статус: {_status_display(result)}\n"
        f"💬 {_error_detail(result)}"
    )


def format_status_report(
    results: list[tuple[str, dict, str | None]],
    report_time: datetime | None = None,
    *,
    title: str = "📊 Ежедневный отчёт",
) -> str:
    report_time = report_time or datetime.now(timezone.utc)
    ok = [(url, r, label) for url, r, label in results if r.get("is_ok")]
    bad = [(url, r, label) for url, r, label in results if not r.get("is_ok")]
    total = len(results)

    lines = [
        title,
        "────────────────",
        f"⏱ {_fmt_time(report_time)}",
        f"📦 Всего: {total} · ✅ {len(ok)} · ❌ {len(bad)}",
        "",
    ]

    lines.append(f"── ✅ Работают ({len(ok)}) ──")
    if ok:
        for url, r, label in ok:
            tag = f"[{label}] " if label else ""
            lines.append(
                f"• {tag}{url}\n"
                f"  {r['status_code']} OK · {_fmt_response_time(r.get('response_time'))}"
            )
    else:
        lines.append("  —")

    lines.append("")
    lines.append(f"── ❌ Проблемы ({len(bad)}) ──")
    if bad:
        for url, r, label in bad:
            tag = f"[{label}] " if label else ""
            lines.append(f"• {tag}{url}\n  💬 {_error_detail(r)}")
    else:
        lines.append("  —")

    return "\n".join(lines)


def format_daily_report(
    results: list[tuple[str, dict, str | None]], report_time: datetime | None = None
) -> str:
    return format_status_report(results, report_time, title="📊 Ежедневный отчёт")


def format_site_list_item(
    label: str,
    url: str,
    interval_str: str,
    is_active: bool,
    name: str | None = None,
) -> str:
    icon = "🟢" if is_active else "⏸"
    status = "активен" if is_active else "на паузе"
    lines = [f"{icon} {label}", f"🔗 {url}"]
    if name:
        lines.append(f"📝 {name}")
    lines.append(f"⏱ {interval_str} · {status}")
    return "\n".join(lines)


def format_site_list(items: list[str]) -> str:
    if not items:
        return "📋 Мониторинг пуст\n\nДобавьте сайт командой /add"
    header = f"📋 Мониторинг · {len(items)} сайт(ов)\n────────────────"
    body = "\n\n".join(f"{index}. {item}" for index, item in enumerate(items, 1))
    return f"{header}\n\n{body}"


def format_db_error(message: str) -> str:
    return (
        "⚠️ Проблема с базой данных\n"
        "────────────────\n"
        f"💬 {message}\n"
        "\n"
        "Проверки сайтов продолжаются,\n"
        "но история может не сохраняться."
    )


def format_group_command_hint(bot_username: str, command: str) -> str:
    return (
        f"В группе с несколькими ботами используйте:\n"
        f"/{command}@{bot_username}\n"
        f"@{bot_username} /{command}\n"
        f"@{bot_username} {command}"
    )


def format_welcome(bot_username: str | None = None) -> str:
    return (
        "👋 Site Health Checker Bot\n"
        "────────────────\n"
        "Слежу за доступностью ваших сайтов\n"
        "и сообщаю, если что-то пошло не так.\n"
        "\n"
        + format_help(bot_username)
    )


def format_help(bot_username: str | None = None) -> str:
    group_section = ""
    if bot_username:
        group_section = (
            "\n"
            "👥 Групповой чат (несколько ботов):\n"
            f"/add@{bot_username} <url> --label <label>\n"
            f"@{bot_username} /add <url> --label <label>\n"
            f"@{bot_username} add <url> --label <label>\n"
            "\n"
        )

    return (
        "📖 Команды\n"
        "────────────────\n"
        "Мониторинг:\n"
        "/add <url> [имя] --label <label>\n"
        "/remove <url> · /list · /status\n"
        "/check <url> · /config <url> <мин>\n"
        + group_section
        + "Пауза:\n"
        "/pause <url> · /resume <url>\n"
        "/pause_all · /resume_all\n"
        "\n"
        "Прочее:\n"
        "/clean_history · /help"
    )


def format_usage(example: str) -> str:
    return f"ℹ️ Пример:\n{example}"


def format_info(title: str, body: str) -> str:
    return f"ℹ️ {title}\n\n{body}"


def format_success(title: str, body: str) -> str:
    return f"✅ {title}\n\n{body}"


def format_error(title: str, body: str) -> str:
    return f"❌ {title}\n\n{body}"
