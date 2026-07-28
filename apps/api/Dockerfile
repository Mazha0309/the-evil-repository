FROM python:3.12-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.8.14 /uv /uvx /bin/
WORKDIR /app
COPY apps/api/pyproject.toml apps/api/uv.lock apps/api/README.md ./
RUN uv sync --frozen --no-dev --no-editable --no-install-project
COPY apps/api/app ./app

FROM debian:bookworm-slim AS antigravity

ARG TARGETARCH
ARG ANTIGRAVITY_CLI_VERSION=1.1.7
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && target_arch="${TARGETARCH:-$(dpkg --print-architecture)}" \
    && case "${target_arch}" in \
         amd64) \
           archive="agy_cli_linux_x64.tar.gz"; \
           checksum="946cd06258d0ede72d0311550c914315798821f6a397f53ac760919826a19af4" ;; \
         arm64) \
           archive="agy_cli_linux_arm64.tar.gz"; \
           checksum="0d6d488851745e80e69b8935d063e742945811b47111994b1a6dbd27df3010d5" ;; \
         *) echo "Unsupported Antigravity CLI architecture: ${target_arch}" >&2; exit 1 ;; \
       esac \
    && curl --fail --location --retry 3 \
         "https://github.com/google-antigravity/antigravity-cli/releases/download/${ANTIGRAVITY_CLI_VERSION}/${archive}" \
         --output /tmp/agy.tar.gz \
    && echo "${checksum}  /tmp/agy.tar.gz" | sha256sum --check --strict \
    && tar -xzf /tmp/agy.tar.gz -C /tmp \
    && install -m 0755 /tmp/antigravity /usr/local/bin/agy \
    && /usr/local/bin/agy --version

FROM python:3.12-slim

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system evil \
    && adduser --system --ingroup evil evil \
    && install -d -o evil -g evil -m 0700 \
         /var/lib/evil-repository/antigravity-home \
         /var/lib/evil-repository/antigravity-work
WORKDIR /app
COPY --from=antigravity /usr/local/bin/agy /usr/local/bin/agy
COPY --from=builder --chown=evil:evil /app /app
COPY --chown=evil:evil scenarios /scenarios
COPY --chown=evil:evil suites /suites
USER evil
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
