FROM python:3.12-slim

WORKDIR /app

COPY webhook_server/requirements-webhook.txt .
RUN pip install --no-cache-dir -r requirements-webhook.txt

COPY webhook_server /app/webhook_server
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8080
CMD ["uvicorn", "webhook_server.app:app", "--host", "0.0.0.0", "--port", "8080"]
