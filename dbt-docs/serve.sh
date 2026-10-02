#!/bin/sh
# Generate the dbt docs site against the live ClickHouse (so the catalog shows
# real column types and row counts), then serve it. Regenerates every
# DOCS_REFRESH_SECONDS so new models appear without a restart.
set -eu

OUT=/tmp/dbt-docs
REFRESH="${DOCS_REFRESH_SECONDS:-3600}"
mkdir -p "$OUT"
cd /opt/dbt-project/dbt

generate() {
  dbt docs generate --static --profiles-dir profiles --target-path /tmp/dbt-target --log-path /tmp/dbt-logs \
    && cp /tmp/dbt-target/static_index.html "$OUT/index.html.tmp" \
    && mv "$OUT/index.html.tmp" "$OUT/index.html"
}

until generate; do
  echo "dbt docs generate failed; retrying in 15s" >&2
  sleep 15
done

(while sleep "$REFRESH"; do generate || echo "refresh failed; keeping previous site" >&2; done) &
exec python -m http.server 8080 --directory "$OUT" --bind 0.0.0.0
