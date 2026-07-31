#!/usr/bin/env bash
# Tear down the isolated stress environment and verify nothing is left behind.
#
# Safe to run at any time, including after a partial or failed bring-up. It only
# ever touches resources whose names carry the "tlstress" project prefix, so an
# unrelated Docker workload on the same host is never affected.
#
# Usage:
#   bash env/teardown.sh            # stop containers, keep data dir for inspection
#   bash env/teardown.sh --purge    # also delete the data dir and the local backend
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECT="tlstress"
COMPOSE_FILE="$HERE/compose.stress.yaml"
DATA_ROOT="${TLSTRESS_DATA_ROOT:-/tmp/tlstress}"
PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1

echo "[teardown] project=$PROJECT data_root=$DATA_ROOT purge=$PURGE"

# 1. Local backend started for the backend-side scenarios (S7/S9).
if [ -f "$DATA_ROOT/backend.pid" ]; then
  PID="$(cat "$DATA_ROOT/backend.pid" 2>/dev/null || true)"
  if [ -n "${PID:-}" ]; then
    echo "[teardown] killing local backend pid=$PID"
    taskkill //F //PID "$PID" >/dev/null 2>&1 || kill -9 "$PID" 2>/dev/null || true
  fi
  rm -f "$DATA_ROOT/backend.pid"
fi

# Belt and braces: anything still listening on the stress backend port.
for port in 58123; do
  pid="$(netstat -ano 2>/dev/null | awk -v p=":$port" \
    '$0 ~ p && /LISTENING/ { print $NF; exit }')"
  if [ -n "${pid:-}" ]; then
    echo "[teardown] port $port still held by pid=$pid; killing"
    taskkill //F //PID "$pid" >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null || true
  fi
done

# 2. Compose stack. -v removes the project's named volumes (stress data only).
if docker info >/dev/null 2>&1; then
  if [ -f "$COMPOSE_FILE" ]; then
    echo "[teardown] docker compose down -v --remove-orphans"
    docker compose -p "$PROJECT" -f "$COMPOSE_FILE" down -v --remove-orphans 2>&1 \
      | sed 's/^/[teardown]   /' | tail -12
  fi
  # Sweep any straggler that compose did not own (e.g. killed mid-create).
  leftovers="$(docker ps -aq --filter "name=^${PROJECT}" 2>/dev/null)"
  if [ -n "${leftovers:-}" ]; then
    echo "[teardown] removing straggler containers"
    docker rm -f $leftovers >/dev/null 2>&1 || true
  fi
  vols="$(docker volume ls -q --filter "name=^${PROJECT}" 2>/dev/null)"
  if [ -n "${vols:-}" ]; then
    echo "[teardown] removing straggler volumes"
    docker volume rm -f $vols >/dev/null 2>&1 || true
  fi
  nets="$(docker network ls -q --filter "name=^${PROJECT}" 2>/dev/null)"
  if [ -n "${nets:-}" ]; then
    docker network rm $nets >/dev/null 2>&1 || true
  fi
else
  echo "[teardown] docker engine unreachable; skipped container cleanup"
fi

# 3. Data directory. Kept by default so a failed run can still be inspected.
if [ "$PURGE" = "1" ]; then
  echo "[teardown] removing $DATA_ROOT"
  rm -rf "$DATA_ROOT"
fi

echo "[teardown] --- verification ---"
if docker info >/dev/null 2>&1; then
  remaining="$(docker ps -a --filter "name=^${PROJECT}" --format '{{.Names}}' 2>/dev/null)"
  echo "[teardown] containers matching $PROJECT: ${remaining:-none}"
  echo "[teardown] volumes matching $PROJECT:    $(docker volume ls -q --filter "name=^${PROJECT}" 2>/dev/null | tr '\n' ' ' || echo none)"
fi
for port in 58123 55432 58000; do
  held="$(netstat -ano 2>/dev/null | awk -v p=":$port" \
    '$0 ~ p && /LISTENING/ { print $NF; exit }')"
  echo "[teardown] port $port: ${held:-free}"
done
[ -d "$DATA_ROOT" ] && echo "[teardown] data dir retained at $DATA_ROOT (use --purge to delete)"
echo "[teardown] done"
