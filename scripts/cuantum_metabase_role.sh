#!/bin/sh
# Run on LXC 205 `db`. Creates/updates a read-only role metabase_ro on the
# Cuantum `trading` database for Metabase. The password is read from stdin
# (never on the command line) and passed to the container via the environment.
#
#   grep '^CUANTUM_METABASE_PASSWORD=' .env | cut -d= -f2- | ssh db 'sh -s' < this-script
#
# Tables holding credentials or security-sensitive data are excluded. New
# tables are NOT granted automatically (no default privileges), so a future
# secrets table cannot leak; re-run this script after migrations.
set -eu
read -r PW
export PW
docker exec -i -e PW cuantum-db-postgres-1 sh -c 'psql -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d trading -v pw="$PW"' <<'SQL'
SELECT format('CREATE ROLE metabase_ro LOGIN PASSWORD %L', :'pw')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'metabase_ro') \gexec
ALTER ROLE metabase_ro PASSWORD :'pw';
ALTER ROLE metabase_ro SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE trading TO metabase_ro;
GRANT USAGE ON SCHEMA public TO metabase_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO metabase_ro;
REVOKE SELECT ON api_credentials, app_users, password_reset_tokens, app_settings,
  notification_targets, whitelisted_addresses, audit_events, audit_log FROM metabase_ro;
SQL
echo "metabase_ro: read-only on trading (sensitive tables excluded)"
