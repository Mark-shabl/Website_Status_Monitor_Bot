from datetime import datetime, timezone

import notifications


def test_format_alert():
    result = {
        "status_code": 503,
        "error": None,
        "timestamp": datetime(2026, 7, 6, 14, 30, tzinfo=timezone.utc),
    }
    text = notifications.format_alert("https://example.com", result, 200, "prod")
    assert "АЛЕРТ" in text
    assert "[prod]" in text
    assert "503" in text


def test_format_recovery():
    result = {
        "status_code": 200,
        "response_time": 0.45,
        "timestamp": datetime(2026, 7, 6, 14, 35, tzinfo=timezone.utc),
    }
    text = notifications.format_recovery("https://example.com", result, "prod")
    assert "ВОССТАНОВЛЕНО" in text
    assert "0.45s" in text


def test_format_daily_report():
    results = [
        ("https://ok.com", {"is_ok": True, "status_code": 200, "response_time": 0.3}, "a"),
        ("https://bad.com", {"is_ok": False, "status_code": 503, "error": None}, "b"),
    ]
    text = notifications.format_daily_report(results)
    assert "Работают (1)" in text
    assert "Проблемы (1)" in text
