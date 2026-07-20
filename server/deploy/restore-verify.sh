#!/bin/sh
set -eu

# Restore only into a separately provisioned, empty validation database and an
# empty directory. This script intentionally never cleans a production target.
if [ -z "${RESTORE_DB_DUMP_REMOTE:-}" ] || [ -z "${RESTORE_BLOB_REMOTE:-}" ]; then
  echo "RESTORE_DB_DUMP_REMOTE and RESTORE_BLOB_REMOTE are required" >&2
  exit 2
fi
if [ -z "${RESTORE_DATABASE_URL:-}" ] || [ -z "${RESTORE_BLOB_ROOT:-}" ]; then
  echo "RESTORE_DATABASE_URL and RESTORE_BLOB_ROOT are required" >&2
  exit 2
fi
if [ -e "${RESTORE_BLOB_ROOT}" ] && [ -n "$(find "${RESTORE_BLOB_ROOT}" -mindepth 1 -print -quit)" ]; then
  echo "RESTORE_BLOB_ROOT must be empty" >&2
  exit 2
fi

work_dir="$(mktemp -d /tmp/tracelab-restore-verify.XXXXXX)"
trap 'rm -rf "${work_dir}"' EXIT
mkdir -p "${RESTORE_BLOB_ROOT}"
rclone copyto "${RESTORE_DB_DUMP_REMOTE}" "${work_dir}/postgres.dump"
pg_restore --exit-on-error --no-owner --dbname="${RESTORE_DATABASE_URL}" "${work_dir}/postgres.dump"
rclone copy "${RESTORE_BLOB_REMOTE}" "${RESTORE_BLOB_ROOT}"

psql "${RESTORE_DATABASE_URL}" -Atc \
  "SELECT storage_key FROM blob_object WHERE status='ready' ORDER BY storage_key" \
  > "${work_dir}/storage-keys.txt"
while IFS= read -r storage_key; do
  case "${storage_key}" in
    sha256/*) ;;
    *) echo "unsafe storage key in restored database: ${storage_key}" >&2; exit 3 ;;
  esac
  if [ ! -f "${RESTORE_BLOB_ROOT}/${storage_key}" ]; then
    echo "missing restored blob: ${storage_key}" >&2
    exit 3
  fi
done < "${work_dir}/storage-keys.txt"

psql "${RESTORE_DATABASE_URL}" -Atc \
  "SELECT json_build_object('users',(SELECT count(*) FROM user_account),'workspaces',(SELECT count(*) FROM workspace),'ready_blobs',(SELECT count(*) FROM blob_object WHERE status='ready'))"
echo "restore verification passed"
