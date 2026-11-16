FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY webhook_server/requirements-webhook.txt .
RUN pip install --no-cache-dir -r requirements-webhook.txt

# Copy webhook server code
# We copy the entire repo structure to preserve import paths if needed?
# Actually, we need 'webhook_server' valid python package.
# Easiest is to copy it into /app/webhook_server
COPY webhook_server /app/webhook_server

# Set PYTHONPATH to include /app so "import webhook_server" works
ENV PYTHONPATH=/app

# Run uvicorn
CMD ["uvicorn", "webhook_server.app:app", "--host", "0.0.0.0", "--port", "8080"]
