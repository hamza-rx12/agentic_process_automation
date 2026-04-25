# Single-stage on the Playwright base (multi-stage isn't worth it here:
# the playwright base ships its own Python, and a venv built on
# python:3.12-slim ends up with symlinks to /usr/local/bin/python3.12
# which doesn't exist in the noble runtime → exec failure).
#
# We still keep the two big size wins:
#   1. Drop the browsers we never use (~800 MB).
#   2. Don't leave the uv build cache in the final image (~300 MB).
FROM mcr.microsoft.com/playwright:v1.50.0-noble

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    BROWSER_HEADLESS=true

# Drop browsers we never use: webkit, firefox, ffmpeg, chromium_headless_shell.
# Keep only full chromium — we run it with --headless ourselves.
RUN rm -rf \
        /ms-playwright/webkit-* \
        /ms-playwright/firefox-* \
        /ms-playwright/ffmpeg-* \
        /ms-playwright/chromium_headless_shell-* \
        /var/lib/apt/lists/* \
        /root/.npm \
        /root/.cache

RUN uv venv /app/.venv

RUN CHROME_PATH=$(find /ms-playwright -name "chrome" -path "*/chrome-linux/*" | head -1) && \
    printf '#!/bin/sh\nexport BROWSER_EXECUTABLE=%s\nexec /app/.venv/bin/python -m app\n' "$CHROME_PATH" > /entrypoint.sh && \
    chmod +x /entrypoint.sh

COPY requirements.txt .
RUN uv pip install --no-cache --python /app/.venv/bin/python -r requirements.txt

COPY app/ app/

ENTRYPOINT ["/entrypoint.sh"]
