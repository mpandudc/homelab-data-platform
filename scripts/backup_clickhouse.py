"""Back up a ClickHouse database to MinIO (S3 API) and optionally restore it.

    python3 scripts/backup_clickhouse.py backup marts
    python3 scripts/backup_clickhouse.py restore marts <backup-name> --as marts_restore

Uses the least-privilege `clickhouse-backup` MinIO user, never the root key.
Reads connection settings from .env (or the file given by ENV_FILE).
"""

from __future__ import annotations

import argparse
import base64
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> dict[str, str]:
    path = Path(os.environ.get("ENV_FILE", ROOT / ".env"))
    pairs = (line.split("=", 1) for line in path.read_text().splitlines() if "=" in line and not line.startswith("#"))
    return {k.strip(): v.strip() for k, v in pairs}


def clickhouse(env: dict[str, str], query: str) -> str:
    url = f"http://localhost:{env['CLICKHOUSE_HTTP_PORT']}/"
    token = base64.b64encode(f"admin:{env['CLICKHOUSE_ADMIN_PASSWORD']}".encode()).decode()
    request = urllib.request.Request(url, data=query.encode(), headers={"Authorization": f"Basic {token}"})
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return response.read().decode().strip()
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"ClickHouse error: {exc.read().decode()[:500]}") from exc


def s3(env: dict[str, str], name: str) -> str:
    # Inside the compose network ClickHouse reaches MinIO by service name.
    key, secret = env["CH_BACKUP_ACCESS_KEY"], env["CH_BACKUP_SECRET_KEY"]
    return f"S3('http://minio:9000/ch-backups/{name}', '{key}', '{secret}')"


def backup(env: dict[str, str], database: str) -> str:
    name = f"{database}/{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    status = clickhouse(env, f"BACKUP DATABASE {database} TO {s3(env, name)}")
    if "BACKUP_CREATED" not in status:
        raise SystemExit(f"backup failed: {status}")
    return name


def restore(env: dict[str, str], database: str, name: str, target: str) -> None:
    status = clickhouse(env, f"RESTORE DATABASE {database} AS {target} FROM {s3(env, name)}")
    if "RESTORED" not in status:
        raise SystemExit(f"restore failed: {status}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("database")
    parser.add_argument("name", nargs="?")
    parser.add_argument("--as", dest="target")
    args = parser.parse_args()
    env = load_env()
    if args.action == "backup":
        print(backup(env, args.database))
    else:
        if not args.name or not args.target:
            parser.error("restore needs <backup-name> and --as <database>")
        restore(env, args.database, args.name, args.target)
        print(f"restored {args.name} as {args.target}")


if __name__ == "__main__":
    main()
