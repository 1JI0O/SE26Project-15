#!/usr/bin/env bash
# Sample container resources and PostgreSQL state during a server stress scenario.
#
# Usage: bash monitoring/collect_server.sh results/s1_60 [interval_seconds]
# Stop with Ctrl-C; every sample is appended so a partial run is still usable.
#
# Env:
#   PG_CONTAINER   postgres container name (default tlstress-postgres-1)
#   PG_USER        postgres role (default tracelab)
#   PG_DB          database (default tracelab)
#   DOCKER_TARGETS space-separated container names for docker stats
#                  (default: the three tlstress containers)
set -uo pipefail

OUT_DIR="${1:?usage: collect_server.sh <out_dir> [interval_seconds]}"
INTERVAL="${2:-5}"
PG_CONTAINER="${PG_CONTAINER:-tlstress-postgres-1}"
PG_USER="${PG_USER:-tracelab}"
PG_DB="${PG_DB:-tracelab}"
DOCKER_TARGETS="${DOCKER_TARGETS:-tlstress-api-1 tlstress-postgres-1 tlstress-worker-1}"

# Fail loudly on a wrong container name. Every psql probe below redirects stderr, so
# an unreachable container otherwise yields empty CSVs for the whole run and the
# mistake only surfaces when the numbers are needed and no longer reproducible.
if ! docker exec "$PG_CONTAINER" true >/dev/null 2>&1; then
  echo "[collect] cannot exec into '$PG_CONTAINER'." >&2
  echo "[collect] running containers: $(docker ps --format '{{.Names}}' | tr '\n' ' ')" >&2
  echo "[collect] set PG_CONTAINER=<name> and re-run." >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
PROBES="$(cd "$(dirname "$0")" && pwd)/pg_probes.sql"

echo "[collect] out=$OUT_DIR interval=${INTERVAL}s pg=$PG_CONTAINER"
echo "[collect] Ctrl-C to stop."

# Reset statement stats so slow-query output covers this scenario only. Ignored if
# the extension is absent.
docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -qtAc \
  "SELECT pg_stat_statements_reset();" >/dev/null 2>&1 \
  || echo "[collect] pg_stat_statements unavailable; slow-query probe will be empty."

run_probe() {
  local tag="$1" file="$2"
  # Extract the block following "-- probe: <tag>" up to the next probe marker.
  awk -v tag="-- probe: $tag" '
    $0 == tag { grab = 1; next }
    grab && /^-- probe: / { exit }
    grab { print }
  ' "$PROBES" \
    | docker exec -i "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" \
        --csv -q >> "$OUT_DIR/$file" 2>>"$OUT_DIR/pg_errors.log"
}

trap 'echo; echo "[collect] stopped; samples in $OUT_DIR"; exit 0' INT TERM

while true; do
  timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  # shellcheck disable=SC2086
  if [ -n "$DOCKER_TARGETS" ]; then
    docker stats --no-stream --format \
      "$timestamp,{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}},{{.NetIO}},{{.BlockIO}}" \
      $DOCKER_TARGETS >> "$OUT_DIR/docker_stats.csv" 2>/dev/null
  else
    docker stats --no-stream --format \
      "$timestamp,{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}},{{.NetIO}},{{.BlockIO}}" \
      >> "$OUT_DIR/docker_stats.csv" 2>/dev/null
  fi

  run_probe connections     "pg_connections.csv"
  run_probe lock_wait_count "pg_lock_wait_count.csv"
  run_probe lock_waits      "pg_lock_waits.csv"

  sleep "$INTERVAL"
done
