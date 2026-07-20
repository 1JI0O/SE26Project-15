#!/bin/sh
set -eu

# Explicit destructive maintenance command. It is intentionally excluded from
# normal startup and requires an exact operator confirmation.
if [ "${CONFIRM_REBUILD_CLOUD:-}" != "delete-cloud-postgres-and-blob-data" ]; then
  echo "Set CONFIRM_REBUILD_CLOUD=delete-cloud-postgres-and-blob-data to continue" >&2
  exit 2
fi

compose="docker compose --env-file .env.cloud"
$compose stop api worker
$compose exec -T postgres psql -U "${POSTGRES_USER:-tracelab}" -d "${POSTGRES_DB:-tracelab}" \
  -v ON_ERROR_STOP=1 -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'

echo "PostgreSQL cloud schema was rebuilt. Blob files were not deleted automatically."
echo "Review /srv/tracelab/blobs separately, then run: $compose up -d migrator api worker"
