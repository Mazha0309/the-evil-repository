FROM node:22-bookworm-slim

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        coreutils \
        file \
        git \
        jq \
        postgresql \
        postgresql-client \
        procps \
        python3 \
        python3-venv \
        ripgrep \
        sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /workspace /opt/evil/bin \
    && chown node:node /workspace

COPY --chown=root:root bin/init-workspace /opt/evil/bin/init-workspace
RUN chmod 0755 /opt/evil/bin/init-workspace

USER node
WORKDIR /workspace
ENV HOME=/home/node \
    PGHOST=/workspace/.runtime/postgres-socket \
    PGDATABASE=evil_challenge \
    PGUSER=sandbox \
    NO_COLOR=1

CMD ["sleep", "infinity"]
