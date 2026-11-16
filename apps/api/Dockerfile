# GutHub API (ADR-0016): FastAPI on Cloud Run. Also runs the maintenance jobs (python -m guthub_api.maintenance).
FROM ghcr.io/astral-sh/uv:0.10.12 AS uv

FROM python:3.12-slim AS build
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 GUTHUB_ENVIRONMENT=production
# Unprivileged user; Cloud Run sets PORT.
USER 65532:65532
CMD ["sh", "-c", "exec uvicorn guthub_api.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips='*'"]
