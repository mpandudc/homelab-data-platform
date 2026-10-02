#!/bin/bash
# One Postgres for platform metadata: separate database and owner per app.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" \
  -v airflow_pw="$AIRFLOW_DB_PASSWORD" -v metabase_pw="$METABASE_DB_PASSWORD" <<'SQL'
CREATE ROLE airflow LOGIN PASSWORD :'airflow_pw';
CREATE DATABASE airflow OWNER airflow;
CREATE ROLE metabase LOGIN PASSWORD :'metabase_pw';
CREATE DATABASE metabase OWNER metabase;
REVOKE ALL ON DATABASE airflow FROM PUBLIC;
REVOKE ALL ON DATABASE metabase FROM PUBLIC;
SQL
