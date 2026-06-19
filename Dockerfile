# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Operations Command Center — production image.
# Lean Python base wrapped in a gunicorn WSGI layer.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install Python dependencies first to maximize layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application source.
COPY . .

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Entrypoint applies migrations / seed then launches gunicorn.
COPY --chown=appuser:appuser docker-entrypoint.sh /app/docker-entrypoint.sh

# Invoke via `sh` so the script runs even if the executable bit is missing
# (Windows-authored files often lose it), then exec gunicorn.
ENTRYPOINT ["/bin/sh", "/app/docker-entrypoint.sh"]
# Shell form so $PORT (injected by Render/any PaaS) and worker count expand at
# runtime. Honors GUNICORN_WORKERS, else Render's WEB_CONCURRENCY, else 3.
# Keep workers low (1) when using SQLite to avoid write-lock contention.
CMD ["sh", "-c", "gunicorn --workers ${GUNICORN_WORKERS:-${WEB_CONCURRENCY:-3}} --bind 0.0.0.0:${PORT:-8000} --timeout 60 wsgi:app"]
