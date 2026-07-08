import bot


def test_parse_mention_command_with_slash():
    result = bot.parse_mention_command(
        "@SiteBot /add https://example.com --label prod",
        "SiteBot",
    )
    assert result == ("add", ["https://example.com", "--label", "prod"])


def test_parse_mention_command_without_slash():
    result = bot.parse_mention_command(
        "@SiteBot add https://example.com --label prod",
        "SiteBot",
    )
    assert result == ("add", ["https://example.com", "--label", "prod"])


def test_parse_mention_command_with_bot_suffix():
    result = bot.parse_mention_command(
        "@SiteBot /add@SiteBot https://example.com --label prod",
        "SiteBot",
    )
    assert result == ("add", ["https://example.com", "--label", "prod"])


def test_parse_mention_command_empty_shows_help():
    assert bot.parse_mention_command("@SiteBot", "SiteBot") == ("help", [])


def test_parse_mention_command_wrong_bot():
    assert bot.parse_mention_command("@OtherBot add https://x.com", "SiteBot") is None
