FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN uv venv /app/.venv

COPY requirements.txt .
RUN uv pip install --python /app/.venv/bin/python -r requirements.txt

COPY app/ app/

ENTRYPOINT ["/app/.venv/bin/python", "-m", "app"]
