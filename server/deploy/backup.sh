#!/bin/sh
set -eu

if [ -z "${BACKUP_REMOTE:-}" ]; then
  echo "BACKUP_REMOTE is required" >&2
  exit 2
fi

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
day="$(date -u +%Y-%m-%d)"
week="$(date -u +%G-W%V)"
work_dir="/srv/tracelab/tmp/backup-${stamp}"
mkdir -p "${work_dir}"
trap 'rm -rf "${work_dir}"' EXIT

pg_dump --format=custom --no-owner --file="${work_dir}/postgres.dump"
rclone copyto "${work_dir}/postgres.dump" "${BACKUP_REMOTE}/database/daily/${day}.dump"
rclone copyto "${work_dir}/postgres.dump" "${BACKUP_REMOTE}/database/weekly/${week}.dump"
rclone copy /srv/tracelab/blobs "${BACKUP_REMOTE}/blobs" --immutable
rclone delete "${BACKUP_REMOTE}/database/daily" --min-age 8d --include "*.dump"
rclone delete "${BACKUP_REMOTE}/database/weekly" --min-age 29d --include "*.dump"
