# Playwright's official image already ships Chromium plus all the OS-level
# deps it needs, which saves a lot of pain compared to installing them
# ourselves on a slim base image.
FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV DB_PATH=/app/data/leads.db
ENV CACHE_PATH=/app/data/cache.json

EXPOSE 8000

# Render (and most free hosts) inject $PORT at runtime, so bind to that
# instead of a hardcoded port.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-access-log"]
