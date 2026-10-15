FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/app/data/dialogs.sqlite3

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
VOLUME ["/app/data"]

# Переменные BOT_TOKEN, OPERATOR_CHAT_ID, ANTHROPIC_API_KEY передаются через --env-file .env
CMD ["python", "-m", "support_bot"]
