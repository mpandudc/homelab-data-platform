# Migrating LXC 206 `~/data-stack` to this platform

The running stack (MinIO, ClickHouse, Airflow 2.10.5 + Postgres, Sep 2026)
binds the same default ports, so the two cannot run side by side with
defaults. Plan a short maintenance window.

1. **Snapshot first:** `vzdump 206 --mode snapshot --compress zstd` on the
   Proxmox host (backup disk, see homeserver runbook).
2. **Inventory data worth keeping:**
   - ClickHouse: `SELECT database, name, total_rows FROM system.tables WHERE database NOT IN ('system','INFORMATION_SCHEMA','information_schema')`.
   - MinIO: `mc du --depth 1 old/`.
   - Airflow: DAG files in `~/data-stack/dags`; metadata history is optional.
3. **Export:**
   - ClickHouse: `BACKUP DATABASE <db> TO File('/var/lib/clickhouse/backup/<db>')`
     on the old server (needs `backups.allowed_path`), or `INSERT INTO FUNCTION s3(...)`.
   - MinIO: `mc mirror old/<bucket> ./export/<bucket>`.
4. **Stop the old stack:** `cd ~/data-stack && docker compose down` (keep volumes).
5. **Start the platform:** `make env up`, then restore: `RESTORE DATABASE ... FROM ...`,
   `mc mirror ./export/<bucket> new/<bucket>`, copy DAGs into `airflow/dags/`.
6. **Point clients at the new credentials** (`dbt`, `metabase` users instead of the
   old single user).
7. **Edge + monitoring:** `make up-edge`; append `monitoring/prometheus-scrape.yml`
   on LXC 207 and reload Prometheus.
8. **Rollback:** `make down`, `cd ~/data-stack && docker compose up -d`; the old
   volumes were never touched.
