import bot


def test_split_message_short():
    assert bot.split_message("hello") == ["hello"]


def test_split_message_by_lines():
    lines = [f"line {i}" for i in range(200)]
    text = "\n".join(lines)
    parts = bot.split_message(text, limit=100)
    assert len(parts) > 1
    assert all(len(part) <= 100 for part in parts)


def test_format_interval_minutes():
    assert bot._format_interval(300) == "каждые 5 мин"


def test_format_interval_seconds():
    assert bot._format_interval(45) == "каждые 45 сек"
