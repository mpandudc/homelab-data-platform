#!/bin/sh
# Idempotent read-only access for Metabase to platform metadata:
#   - Postgres role metabase_airflow: SELECT on Airflow run metadata only
#     (no connection, variable, ab_* users, session, xcom, log, dag_code tables)
#   - ClickHouse views in ops (SQL SECURITY DEFINER admin) with storage and
#     daily query aggregates; no query text, so no literals or secrets leak.
# Secrets are generated here, kept in .env and never printed.
set -eu
cd "$(dirname "$0")/.."
COMPOSE="docker compose --profile core --profile orchestration --profile bi"

if ! grep -q '^METABASE_AIRFLOW_PASSWORD=' .env; then
  echo "METABASE_AIRFLOW_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')" >> .env
fi
PW=$(grep '^METABASE_AIRFLOW_PASSWORD=' .env | cut -d= -f2-)
export PW

$COMPOSE exec -T -e PW platform-db sh -c 'psql -q -v ON_ERROR_STOP=1 -U postgres -d airflow -v pw="$PW"' <<'SQL'
SELECT format('CREATE ROLE metabase_airflow LOGIN PASSWORD %L', :'pw')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'metabase_airflow') \gexec
ALTER ROLE metabase_airflow PASSWORD :'pw';
ALTER ROLE metabase_airflow SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE airflow TO metabase_airflow;
GRANT USAGE ON SCHEMA public TO metabase_airflow;
GRANT SELECT ON dag, dag_run, task_instance, task_fail, task_reschedule, job,
  import_error, dag_tag, dag_run_note, sla_miss TO metabase_airflow;
SQL
echo "postgres: metabase_airflow read-only on Airflow run metadata"

$COMPOSE exec -T clickhouse sh -c 'clickhouse client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery' <<'SQL'
CREATE OR REPLACE VIEW ops.ch_table_storage
DEFINER = admin SQL SECURITY DEFINER AS
SELECT
    database,
    table,
    sum(rows) AS rows,
    sum(bytes_on_disk) AS bytes_on_disk,
    count() AS active_parts,
    max(modification_time) AS last_modified
FROM system.parts
WHERE active AND database NOT IN ('system', 'INFORMATION_SCHEMA', 'information_schema')
GROUP BY database, table;

CREATE OR REPLACE VIEW ops.ch_query_daily
DEFINER = admin SQL SECURITY DEFINER AS
SELECT
    event_date,
    user,
    query_kind,
    count() AS queries,
    countIf(type IN ('ExceptionBeforeStart', 'ExceptionWhileProcessing')) AS failed,
    round(avg(query_duration_ms)) AS avg_ms,
    quantile(0.95)(query_duration_ms) AS p95_ms,
    sum(read_rows) AS read_rows,
    max(memory_usage) AS peak_memory_bytes
FROM system.query_log
WHERE type != 'QueryStart'
GROUP BY event_date, user, query_kind;
SQL
echo "clickhouse: ops.ch_table_storage, ops.ch_query_daily"
