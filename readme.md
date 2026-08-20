# Site Health Checker Bot

Telegram-бот для мониторинга доступности сайтов. Периодически проверяет HTTP/HTTPS URL, отправляет алерты при смене статуса и ежедневный отчёт.

## Возможности

- Периодический мониторинг с настраиваемым интервалом
- Группировка сайтов по label (проект/категория)
- Алерты при падении и восстановлении
- Retry перед алертом (transient ошибки)
- SSRF-защита и rate limiting по хосту
- Пауза/возобновление мониторинга (один сайт или все)
- Автоочистка истории проверок (3 дня)
- Устойчивость к сбоям БД (бот не падает)

## Стек

- **Python 3.11+**
- **python-telegram-bot** — Telegram API + JobQueue
- **httpx** — async HTTP-проверки
- **SQLAlchemy 2.0 + aiosqlite** — async SQLite
- **pytest** — тесты, GitHub Actions CI

## Быстрый старт

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/macOS

pip install -r requirements.txt
copy .env.example .env           # Windows
# cp .env.example .env         # Linux/macOS
```

Заполните `TELEGRAM_BOT_TOKEN` в `.env` (получить у [@BotFather](https://t.me/BotFather)).

```bash
python main.py
```

При первом запуске создаётся `sites.db`.

## Команды

| Команда | Описание |
|---------|----------|
| `/start`, `/help` | Приветствие и справка |
| `/add <url> [название] --label <label>` | Добавить сайт (label обязателен) |
| `/remove <url>` | Удалить сайт |
| `/list` | Список сайтов |
| `/status` | Проверить активные сайты |
| `/check <url>` | Разовая проверка |
| `/config <url> <минуты>` | Интервал проверки |
| `/pause <url>` | Приостановить мониторинг |
| `/resume <url>` | Возобновить мониторинг |
| `/pause_all` | Пауза для всех сайтов чата |
| `/resume_all` | Возобновить все сайты |
| `/clean_history` | Удалить историю старше 3 дней |
| `/set_topic` | Слать уведомления в текущую тему (топик) группы |
| `/set_topic general` | Сбросить тему на основной чат (General) |

## Групповой чат (несколько ботов)

Добавьте бота в группу и вызывайте команды **с указанием бота**:

```
/add@YourBotName https://example.com --label prod
@YourBotName /add https://example.com --label prod
@YourBotName add https://example.com --label prod
```

Telegram покажет команды этого бота в меню `/` после регистрации.  
Каждая группа хранит **свой** список сайтов и label'ов.

## Переменные окружения

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `TELEGRAM_BOT_TOKEN` | — | Токен бота (обязателен) |
| `DEFAULT_CHECK_INTERVAL` | `300` | Интервал по умолчанию (сек) |
| `MAX_RETRY_COUNT` | `3` | Повторных попыток после первой (всего 1 + N) |
| `RETRY_DELAY_SECONDS` | `5` | Пауза между retry |
| `TIMEOUT_SECONDS` | `10` | Таймаут HTTP |
| `USER_AGENT` | `SiteMonitorBot/1.0` | User-Agent |
| `HOST_RATE_LIMIT_SECONDS` | `30` | Мин. интервал между запросами к одному хосту |
| `HISTORY_RETENTION_DAYS` | `3` | Хранение истории проверок |
| `REPORT_TIMEZONE` | `Europe/Moscow` | Timezone отчёта и purge |
| `REPORT_HOUR` | `9` | Час ежедневного отчёта |
| `REPORT_MINUTE` | `0` | Минута отчёта |
| `PURGE_HOUR` | `3` | Час автоочистки истории |
| `PURGE_MINUTE` | `0` | Минута автоочистки |
| `DATABASE_URL` | `sqlite:///sites.db` | URL БД |
| `LOG_LEVEL` | `INFO` | Уровень логирования |

## Docker

### Быстрый старт (docker compose)

```bash
cp .env.example .env
# заполните TELEGRAM_BOT_TOKEN в .env

docker compose up -d --build
docker compose logs -f site-health-checker
```

База SQLite хранится в Docker volume `site-health-checker-data` (`/app/data/sites.db` внутри контейнера).

### Остановка

```bash
docker compose down
```

Данные сохраняются в volume. Чтобы удалить и volume:

```bash
docker compose down -v
```

### Запуск без compose

```bash
docker build -t site-health-checker .
docker run -d --name site-health-checker \
  --env-file .env \
  -e DATABASE_URL=sqlite+aiosqlite:////app/data/sites.db \
  -v site-health-checker-data:/app/data \
  --restart unless-stopped \
  site-health-checker
```

При недоступной БД бот продолжает работать и уведомляет чаты об ошибках (не чаще раза в 5 минут).

## Разработка

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest -v
```

CI запускается на push/PR (Python 3.11, 3.12) — см. `.github/workflows/ci.yml`.

## Структура проекта

```
├── main.py           # Точка входа, post_init/post_shutdown
├── bot.py            # Команды и JobQueue
├── monitor.py        # Async HTTP-проверки + retry
├── security.py       # SSRF-защита
├── rate_limiter.py   # Rate limit по хосту
├── database.py       # Async SQLAlchemy
├── models.py         # ORM-модели
├── notifications.py  # Форматирование сообщений
├── config.py         # Настройки из .env
├── Dockerfile        # Образ для деплоя
├── docker-compose.yml
└── tests/            # pytest-тесты
```
