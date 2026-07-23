#!/usr/bin/env bash
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker CLI is not installed." >&2
  exit 1
fi

security_options="$(docker info --format '{{json .SecurityOptions}}' 2>/dev/null || true)"
if [[ "$security_options" != *'"name=rootless"'* ]]; then
  echo "The active Docker context is not Rootless Docker." >&2
  echo "Current context: $(docker context show 2>/dev/null || echo unavailable)" >&2
  exit 1
fi

docker run --rm \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --pids-limit 32 \
  --memory 64m \
  --cpus 0.25 \
  --tmpfs /tmp:rw,noexec,nosuid,size=8m \
  alpine:3.20 \
  sh -c 'test ! -e /var/run/docker.sock && touch /tmp/preflight'

echo "Rootless Docker sandbox preflight passed."
