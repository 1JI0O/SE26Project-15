#!/usr/bin/env bash
# Sample the local backend process during a backend stress scenario (S7/S9).
#
# Usage: bash monitoring/collect_backend.sh results/s7_8 [interval_seconds]
#
# Records RSS, thread count and open handles so pool saturation and leaks are
# visible, plus one optional py-spy snapshot to locate blocking in the small
# thread pools (analysis 2, agent conversation 4, paper parse 1).
#
# Env:
#   BACKEND_PID   uvicorn pid; auto-detected from the port when unset
#   BACKEND_PORT  default 8000
#   PY_SPY        "1" to capture a py-spy flamegraph (pip install py-spy)
set -uo pipefail

OUT_DIR="${1:?usage: collect_backend.sh <out_dir> [interval_seconds]}"
INTERVAL="${2:-5}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
mkdir -p "$OUT_DIR"

detect_pid() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$BACKEND_PORT" -sTCP:LISTEN -t 2>/dev/null | head -n1
  elif command -v netstat >/dev/null 2>&1; then
    # Windows/Git Bash fallback.
    netstat -ano 2>/dev/null | awk -v p=":$BACKEND_PORT" \
      '$0 ~ p && /LISTENING/ { print $NF; exit }'
  fi
}

PID="${BACKEND_PID:-$(detect_pid)}"
if [ -z "${PID:-}" ]; then
  echo "[collect] Could not find the backend pid on port $BACKEND_PORT." >&2
  echo "[collect] Set BACKEND_PID explicitly and retry." >&2
  exit 1
fi

echo "[collect] backend pid=$PID out=$OUT_DIR interval=${INTERVAL}s"
echo "timestamp,rss_kb,threads,handles" >> "$OUT_DIR/backend_process.csv"

if [ "${PY_SPY:-}" = "1" ]; then
  if command -v py-spy >/dev/null 2>&1; then
    echo "[collect] capturing a 60s py-spy profile in the background"
    py-spy record --pid "$PID" --duration 60 --output "$OUT_DIR/backend_flame.svg" \
      >>"$OUT_DIR/py_spy.log" 2>&1 &
  else
    echo "[collect] py-spy not installed; skipping the profile." >&2
  fi
fi

sample_windows() {
  # tasklist reports "Mem Usage" with thousands separators; strip them.
  local raw
  raw="$(tasklist /FI "PID eq $PID" /FO CSV /NH 2>/dev/null | tr -d '"')"
  [ -z "$raw" ] && return 1
  local mem
  mem="$(echo "$raw" | awk -F',' '{ gsub(/[^0-9]/, "", $5); print $5 }')"
  echo "${mem:-0},,"
}

sample_posix() {
  local rss threads handles
  rss="$(ps -o rss= -p "$PID" 2>/dev/null | tr -d ' ')"
  [ -z "$rss" ] && return 1
  threads="$(ps -o nlwp= -p "$PID" 2>/dev/null | tr -d ' ')"
  if command -v lsof >/dev/null 2>&1; then
    handles="$(lsof -p "$PID" 2>/dev/null | wc -l | tr -d ' ')"
  fi
  echo "${rss},${threads:-},${handles:-}"
}

trap 'echo; echo "[collect] stopped; samples in $OUT_DIR"; exit 0' INT TERM

while true; do
  timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if line="$(sample_posix)" || line="$(sample_windows)"; then
    echo "$timestamp,$line" >> "$OUT_DIR/backend_process.csv"
  else
    echo "[collect] pid $PID is gone; stopping." >&2
    exit 1
  fi
  sleep "$INTERVAL"
done
