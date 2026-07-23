#!/usr/bin/env bash
set -euo pipefail

if [[ "${ALLOW_ACTIVE_RUN_DISRUPTION:-0}" == "1" ]]; then
  echo "WARNING: active-run deployment protection was explicitly bypassed." >&2
  exit 0
fi

postgres_container="$(docker compose ps --status running -q postgres 2>/dev/null || true)"
if [[ -z "$postgres_container" ]]; then
  exit 0
fi

set +e
table_name="$(
  docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT to_regclass('\''public.benchmark_runs'\'');"' \
    2>/dev/null
)"
query_status=$?
set -e
if [[ $query_status -ne 0 ]]; then
  echo "Deployment blocked: could not inspect the running benchmark database." >&2
  echo "Set ALLOW_ACTIVE_RUN_DISRUPTION=1 only if interrupting runs is intentional." >&2
  exit 1
fi
if [[ "$table_name" != "benchmark_runs" ]]; then
  exit 0
fi

set +e
active_count="$(
  docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM benchmark_runs WHERE status::text IN ('\''queued'\'','\''preparing'\'','\''running'\'','\''scoring'\'');"' \
    2>/dev/null
)"
query_status=$?
set -e
if [[ $query_status -ne 0 || ! "$active_count" =~ ^[0-9]+$ ]]; then
  echo "Deployment blocked: could not determine whether benchmark runs are active." >&2
  echo "Set ALLOW_ACTIVE_RUN_DISRUPTION=1 only if interrupting runs is intentional." >&2
  exit 1
fi
if [[ "$active_count" == "0" ]]; then
  exit 0
fi

echo "Deployment blocked: $active_count queued or active benchmark run(s) would be interrupted." >&2
docker compose exec -T postgres sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -P pager=off -c "SELECT id, status, stage, started_at FROM benchmark_runs WHERE status::text IN ('\''queued'\'','\''preparing'\'','\''running'\'','\''scoring'\'') ORDER BY created_at;"' \
  >&2
echo "Wait for them to finish or cancel them from the WebUI." >&2
echo "A paused run is still in memory and is not safe to interrupt." >&2
echo "To abandon them deliberately, set ALLOW_ACTIVE_RUN_DISRUPTION=1." >&2
exit 1
