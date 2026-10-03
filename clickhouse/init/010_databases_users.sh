#!/bin/bash
# Runs once on an empty data volume. Creates the layered databases used by
# dbt-clickhouse-marts and postgres-cdc-redpanda, plus two scoped users:
#   dbt       read/write on the modelling layers, nothing else
#   metabase  read-only on marts and ops (BI never sees raw or CDC tables)
#             readonly = 2, not 1: Metabase's ClickHouse driver sets per-session
#             settings (async_insert, ...), which readonly = 1 rejects.
set -euo pipefail

clickhouse client --host 127.0.0.1 --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery <<SQL
CREATE DATABASE IF NOT EXISTS raw;
CREATE DATABASE IF NOT EXISTS staging;
CREATE DATABASE IF NOT EXISTS intermediate;
CREATE DATABASE IF NOT EXISTS marts;
CREATE DATABASE IF NOT EXISTS cdc;
CREATE DATABASE IF NOT EXISTS ops;
-- dbt-clickhouse creates the profile's default schema on connect; provide it
-- so the dbt user never needs CREATE DATABASE.
CREATE DATABASE IF NOT EXISTS analytics;

CREATE USER IF NOT EXISTS dbt IDENTIFIED WITH sha256_password BY '${CLICKHOUSE_DBT_PASSWORD}';
GRANT SELECT, INSERT, ALTER, CREATE TABLE, CREATE VIEW, DROP TABLE, DROP VIEW, TRUNCATE, OPTIMIZE, SHOW
  ON raw.* TO dbt;
GRANT SELECT, INSERT, ALTER, CREATE TABLE, CREATE VIEW, DROP TABLE, DROP VIEW, TRUNCATE, OPTIMIZE, SHOW
  ON staging.* TO dbt;
GRANT SELECT, INSERT, ALTER, CREATE TABLE, CREATE VIEW, DROP TABLE, DROP VIEW, TRUNCATE, OPTIMIZE, SHOW
  ON intermediate.* TO dbt;
GRANT SELECT, INSERT, ALTER, CREATE TABLE, CREATE VIEW, DROP TABLE, DROP VIEW, TRUNCATE, OPTIMIZE, SHOW
  ON marts.* TO dbt;
GRANT SELECT, INSERT, ALTER, CREATE TABLE, CREATE VIEW, DROP TABLE, DROP VIEW, TRUNCATE, OPTIMIZE, SHOW
  ON ops.* TO dbt;
GRANT SELECT, INSERT, ALTER, CREATE TABLE, CREATE VIEW, DROP TABLE, DROP VIEW, TRUNCATE, OPTIMIZE, SHOW
  ON analytics.* TO dbt;
GRANT SELECT ON cdc.* TO dbt;
-- dbt-clickhouse reads system tables for introspection.
GRANT SELECT ON system.* TO dbt;

CREATE USER IF NOT EXISTS metabase IDENTIFIED WITH sha256_password BY '${CLICKHOUSE_METABASE_PASSWORD}'
  SETTINGS readonly = 2;
GRANT SELECT ON marts.* TO metabase;
GRANT SELECT ON ops.* TO metabase;
SQL

echo "clickhouse databases and users ready"
