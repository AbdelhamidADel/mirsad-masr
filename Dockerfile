# ── Builder stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /build

COPY pyproject.toml README.md ./
COPY src/ src/

# Install production deps into an isolated prefix (no dev extras)
RUN uv pip install --system --no-cache --prefix /install .

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Copy only the installed packages from the builder
COPY --from=builder /install /usr/local

# Non-root user
RUN addgroup --system mirsad && adduser --system --ingroup mirsad mirsad

WORKDIR /app
COPY src/ src/

USER mirsad

ENV HOME=/tmp
ENV XDG_CACHE_HOME=/tmp/.cache

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD sh -c 'python -c "import urllib.request; urllib.request.urlopen(\"http://localhost:${PORT:-8000}/v1/health\")"'

CMD ["sh", "-c", "exec uvicorn egxdesk.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
