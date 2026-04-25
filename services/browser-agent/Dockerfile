# ── Builder: build the venv on a slim base, no Playwright weight here ──
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1

RUN uv venv /app/.venv

COPY requirements.txt .
RUN uv pip install --no-cache --python /app/.venv/bin/python -r requirements.txt

# ── Runtime: Playwright base, but with only chromium kept ──
FROM mcr.microsoft.com/playwright:v1.50.0-noble

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    BROWSER_HEADLESS=true \
    PATH="/app/.venv/bin:$PATH"

# Drop browsers we never use: webkit, firefox, ffmpeg, headless_shell.
# Keep only full chromium — we run it with --headless ourselves.
RUN rm -rf \
        /ms-playwright/webkit-* \
        /ms-playwright/firefox-* \
        /ms-playwright/ffmpeg-* \
        /ms-playwright/chromium_headless_shell-* \
        /var/lib/apt/lists/* \
        /root/.npm \
        /root/.cache

COPY --from=builder /app/.venv /app/.venv

RUN CHROME_PATH=$(find /ms-playwright -name "chrome" -path "*/chrome-linux/*" | head -1) && \
    printf '#!/bin/sh\nexport BROWSER_EXECUTABLE=%s\nexec /app/.venv/bin/python -m app\n' "$CHROME_PATH" > /entrypoint.sh && \
    chmod +x /entrypoint.sh

COPY app/ app/

ENTRYPOINT ["/entrypoint.sh"]
