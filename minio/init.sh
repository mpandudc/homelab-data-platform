#!/bin/sh
# Idempotent MinIO bootstrap: buckets, lifecycle, and a least-privilege
# service user that ClickHouse uses for BACKUP/RESTORE.
set -eu

mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null

for bucket in bronze silver ch-backups; do
  mc mb --ignore-existing "local/$bucket"
done

# Raw landing data is replayable from source; keep 90 days.
if ! mc ilm rule ls local/bronze 2>/dev/null | grep -q "90"; then
  mc ilm rule add --expire-days 90 local/bronze
fi
mc version enable local/ch-backups

mc admin policy create local clickhouse-backup /bootstrap/policies/clickhouse-backup.json
if ! mc admin user info local "$CH_BACKUP_ACCESS_KEY" >/dev/null 2>&1; then
  mc admin user add local "$CH_BACKUP_ACCESS_KEY" "$CH_BACKUP_SECRET_KEY"
fi
mc admin policy attach local clickhouse-backup --user "$CH_BACKUP_ACCESS_KEY" 2>/dev/null || true

echo "minio bootstrap complete"
