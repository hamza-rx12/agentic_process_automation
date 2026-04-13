FROM mcr.microsoft.com/playwright:v1.50.0-noble

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN uv venv /app/.venv

RUN CHROME_PATH=$(find /ms-playwright -name "chrome" -path "*/chrome-linux/*" | head -1) && \
    printf '#!/bin/sh\nexport BROWSER_EXECUTABLE=%s\nexec /app/.venv/bin/python -m app\n' "$CHROME_PATH" > /entrypoint.sh && \
    chmod +x /entrypoint.sh

COPY requirements.txt .
RUN uv pip install --python /app/.venv/bin/python -r requirements.txt

COPY app/ app/

ENV BROWSER_HEADLESS=true

ENTRYPOINT ["/entrypoint.sh"]
