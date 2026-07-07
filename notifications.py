from datetime import datetime, timezone


def _fmt_time(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def format_alert(url: str, result: dict, previous_status_code: int | None) -> str:
    error = result.get("error") or f"HTTP {result.get('status_code')}"
    previous = f"✅ {previous_status_code} OK" if previous_status_code == 200 else "неизвестен"
    return (
        "🔴 АЛЕРТ: Сайт недоступен!\n"
        f"URL: {url}\n"
        f"Статус: {result.get('status_code') or 'нет ответа'}\n"
        f"Время проверки: {_fmt_time(result['timestamp'])}\n"
        f"Ошибка: {error}\n"
        f"Предыдущий статус: {previous}"
    )


def format_recovery(url: str, result: dict) -> str:
    return (
        "🟢 ВОССТАНОВЛЕНО: Сайт снова доступен!\n"
        f"URL: {url}\n"
        f"Статус: {result.get('status_code')} OK\n"
        f"Время отклика: {result.get('response_time'):.2f}s\n"
        f"Время проверки: {_fmt_time(result['timestamp'])}"
    )


def format_check_result(url: str, result: dict) -> str:
    if result.get("is_ok"):
        return (
            f"✅ {url}\n"
            f"Статус: {result['status_code']} OK\n"
            f"Время отклика: {result['response_time']:.2f}s"
        )
    return (
        f"❌ {url}\n"
        f"Статус: {result.get('status_code') or 'нет ответа'}\n"
        f"Ошибка: {result.get('error')}"
    )


def format_daily_report(results: list[tuple[str, dict]], report_time: datetime | None = None) -> str:
    report_time = report_time or datetime.now(timezone.utc)
    ok = [(url, r) for url, r in results if r.get("is_ok")]
    bad = [(url, r) for url, r in results if not r.get("is_ok")]

    lines = ["📊 ОТЧЕТ О СТАТУСЕ", f"Дата: {report_time.strftime('%d.%m.%Y %H:%M')}", ""]

    lines.append(f"✅ Работают ({len(ok)}):")
    for url, r in ok:
        lines.append(f"  • {url} - {r['status_code']} OK ({r['response_time']:.2f}s)")

    lines.append("")
    lines.append(f"❌ Проблемы ({len(bad)}):")
    for url, r in bad:
        detail = r.get("error") or f"{r.get('status_code')} Error"
        lines.append(f"  • {url} - {detail}")

    return "\n".join(lines)
