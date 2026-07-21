FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /opt/tracelab-server
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client rclone \
    && groupadd --gid 10001 tracelab \
    && useradd --uid 10001 --gid 10001 --no-create-home tracelab \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock alembic.ini ./
COPY tracelab_server ./tracelab_server
COPY deploy/backup.sh ./deploy/backup.sh
RUN uv sync --frozen --no-dev --no-editable \
    && chown -R tracelab:tracelab /opt/tracelab-server
ENV PATH="/opt/tracelab-server/.venv/bin:$PATH"
USER tracelab
CMD ["uvicorn", "tracelab_server.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
