FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml .
RUN uv sync --no-dev

COPY apa/ apa/

RUN useradd -m agent && chown -R agent:agent /app \
    && mkdir -p /app/logs && chown agent:agent /app/logs

USER agent
VOLUME /app/logs
ENTRYPOINT [".venv/bin/python"]
