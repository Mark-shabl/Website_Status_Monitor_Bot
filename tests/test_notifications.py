from datetime import datetime, timezone

import notifications


def test_format_alert():
    result = {
        "status_code": 503,
        "error": None,
        "timestamp": datetime(2026, 7, 6, 14, 30, tzinfo=timezone.utc),
    }
    text = notifications.format_alert("https://example.com", result, 200, "prod")
    assert "Сайт недоступен" in text
    assert "prod" in text
    assert "503" in text
    assert "Было → стало" in text


def test_format_recovery():
    result = {
        "status_code": 200,
        "response_time": 0.45,
        "timestamp": datetime(2026, 7, 6, 14, 35, tzinfo=timezone.utc),
    }
    text = notifications.format_recovery("https://example.com", result, "prod")
    assert "восстановлен" in text.lower()
    assert "0.45 сек" in text


def test_format_daily_report():
    results = [
        ("https://ok.com", {"is_ok": True, "status_code": 200, "response_time": 0.3}, "a"),
        ("https://bad.com", {"is_ok": False, "status_code": 503, "error": None}, "b"),
    ]
    text = notifications.format_daily_report(results)
    assert "Ежедневный отчёт" in text
    assert "Работают (1)" in text
    assert "Проблемы (1)" in text


def test_format_status_report_custom_title():
    results = [
        ("https://ok.com", {"is_ok": True, "status_code": 200, "response_time": 0.3}, None),
    ]
    text = notifications.format_status_report(results, title="📊 Текущий статус")
    assert "Текущий статус" in text


def test_format_check_result_ok():
    result = {"is_ok": True, "status_code": 200, "response_time": 0.5}
    text = notifications.format_check_result("https://example.com", result)
    assert "Проверка пройдена" in text


def test_format_site_list_empty():
    assert "пуст" in notifications.format_site_list([]).lower()
