# Site Health Checker Bot — Setup

Подробная документация: [README.md](README.md)

## Setup

```bash
python -m venv venv
venv\Scripts\activate      # Windows
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` and fill in `TELEGRAM_BOT_TOKEN` (from @BotFather).

## Run

```bash
python main.py
```

This creates `sites.db` (SQLite) on first run and starts polling Telegram for commands.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -v
```

## Notes

- Fully async stack: httpx + SQLAlchemy async (aiosqlite)
- Daily report at configured timezone (default 09:00 Europe/Moscow)
- History auto-purged daily (default 03:00, retention 3 days)
- Bot survives database outages (useful in Docker)
