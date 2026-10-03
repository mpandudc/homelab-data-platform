"""Register platform databases in Metabase through its API (idempotent).

Reads the Metabase API key from .metabase_api_key and database passwords from
.env, both on the server; secrets are sent only to Metabase and never printed.

    python3 scripts/metabase_register.py
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_KEY_FILE = ROOT / ".metabase_api_key"


def load_env() -> dict[str, str]:
    pairs = (line.split("=", 1) for line in (ROOT / ".env").read_text().splitlines() if "=" in line)
    return {k.strip(): v.strip() for k, v in pairs}


def databases(env: dict[str, str]) -> list[dict]:
    # Metabase reaches ClickHouse by compose service name on the internal network.
    clickhouse = {
        "host": "clickhouse",
        "port": 8123,
        "user": "metabase",
        "password": env["CLICKHOUSE_METABASE_PASSWORD"],
        "ssl": False,
    }
    airflow = {
        "host": "platform-db",
        "port": 5432,
        "dbname": "airflow",
        "user": "metabase_airflow",
        "password": env["METABASE_AIRFLOW_PASSWORD"],
        "ssl": False,
    }
    return [
        {"name": "ClickHouse marts", "engine": "clickhouse", "details": {**clickhouse, "dbname": "marts"}},
        {"name": "ClickHouse ops", "engine": "clickhouse", "details": {**clickhouse, "dbname": "ops"}},
        {"name": "Airflow metadata", "engine": "postgres", "details": airflow},
    ]


class Metabase:
    def __init__(self, url: str, api_key: str):
        self.url = url.rstrip("/")
        self.headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}

    def call(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, headers=self.headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            # Error bodies can echo request details; keep only the message.
            detail = exc.read().decode(errors="replace")
            try:
                detail = json.loads(detail).get("message", detail)
            except (ValueError, AttributeError):
                pass
            raise SystemExit(f"Metabase {method} {path} -> {exc.code}: {str(detail)[:300]}") from exc


def main() -> None:
    env = load_env()
    mb = Metabase(f"http://localhost:{env.get('METABASE_PORT', '3000')}", API_KEY_FILE.read_text().strip())
    existing = mb.call("GET", "/api/database")
    existing = existing.get("data", existing) if isinstance(existing, dict) else existing
    by_name = {db["name"]: db for db in existing}
    for spec in databases(env):
        if spec["name"] in by_name:
            db_id = by_name[spec["name"]]["id"]
            mb.call("PUT", f"/api/database/{db_id}", spec)
            action = "updated"
        else:
            db_id = mb.call("POST", "/api/database", spec)["id"]
            action = "created"
        mb.call("POST", f"/api/database/{db_id}/sync_schema")
        print(f"{action}: {spec['name']} (id {db_id}, engine {spec['engine']}, dbname {spec['details']['dbname']})")


if __name__ == "__main__":
    main()
