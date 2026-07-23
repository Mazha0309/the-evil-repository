FROM python:3.12-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.8.14 /uv /uvx /bin/
WORKDIR /app
COPY apps/api/pyproject.toml apps/api/uv.lock apps/api/README.md ./
RUN uv sync --frozen --no-dev --no-editable --no-install-project
COPY apps/api/app ./app

FROM python:3.12-slim

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system evil \
    && adduser --system --ingroup evil evil
WORKDIR /app
COPY --from=builder --chown=evil:evil /app /app
COPY --chown=evil:evil scenarios /scenarios
COPY --chown=evil:evil suites /suites
USER evil
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
