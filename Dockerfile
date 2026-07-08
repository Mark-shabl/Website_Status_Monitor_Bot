FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py main.py bot.py monitor.py security.py rate_limiter.py database.py models.py notifications.py ./

RUN mkdir -p /app/data

ENV PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite+aiosqlite:////app/data/sites.db

CMD ["python", "main.py"]
