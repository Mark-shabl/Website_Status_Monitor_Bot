# Site Health Checker Bot

MVP implementation per the spec in the repo root `readme.md`.

## Setup

```bash
python -m venv venv
venv\Scripts\activate      # Windows
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` and fill in `TELEGRAM_BOT_TOKEN` (from @BotFather) and `ADMIN_CHAT_ID`.

## Run

```bash
python main.py
```

This creates `sites.db` (SQLite) on first run and starts polling Telegram for commands.

## Commands

- `/start` - greeting and instructions
- `/add <url> [name]` - start monitoring a URL
- `/remove <url>` - stop monitoring a URL
- `/list` - list your monitored URLs
- `/status` - run an on-demand check of all your URLs
- `/check <url>` - one-off check of any URL
- `/config <url> <minutes>` - change the check interval for a URL
- `/help` - command reference

## Notes / scope

This is the core MVP from the spec (sections 2-5): monitoring, all commands,
SQLite storage, alert/recovery notifications, and a daily report (sent at
09:00 server time to every chat with active sites). Retry/rate-limit hardening
(section 6), SSRF/whitelist protections (section 7), and the v2.0 extras
(section 11) are not implemented yet.
