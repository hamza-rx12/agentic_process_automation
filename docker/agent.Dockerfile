FROM mcr.microsoft.com/playwright:v1.50.0-noble

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml .
RUN uv sync --no-dev

COPY apa/ apa/

RUN CHROME_PATH=$(find /ms-playwright -name "chrome" -path "*/chrome-linux/*" | head -1) \
    && printf '%s' "$CHROME_PATH" > /tmp/chrome_path

ENV BROWSER_HEADLESS=true

RUN useradd -m agent && chown -R agent:agent /app \
    && mkdir -p /app/logs && chown agent:agent /app/logs

RUN printf '#!/bin/sh\nexport BROWSER_EXECUTABLE=$(cat /tmp/chrome_path)\nexec .venv/bin/python "$@"\n' > /entrypoint.sh \
    && chmod +x /entrypoint.sh

USER agent
VOLUME /app/logs
ENTRYPOINT ["/entrypoint.sh"]
