"""Print a .env with fresh random secrets. Usage: python3 scripts/make_env.py [--ports-offset N]

--ports-offset shifts every published port, so a second copy of the platform
(for verification) can run beside the live one on the same host.
"""

from __future__ import annotations

import argparse
import base64
import secrets

PORTS = {
    "MINIO_API_PORT": 9000,
    "MINIO_CONSOLE_PORT": 9001,
    "CLICKHOUSE_HTTP_PORT": 8123,
    "CLICKHOUSE_NATIVE_PORT": 9009,
    "CLICKHOUSE_METRICS_PORT": 9363,
    "REDPANDA_KAFKA_PORT": 19092,
    "REDPANDA_ADMIN_PORT": 9644,
    "AIRFLOW_WEB_PORT": 8080,
    "METABASE_PORT": 3000,
    "REDPANDA_CONSOLE_PORT": 8088,
    "DBT_DOCS_PORT": 8081,
}
SECRETS = [
    "MINIO_ROOT_PASSWORD", "CH_BACKUP_SECRET_KEY", "CLICKHOUSE_ADMIN_PASSWORD", "CLICKHOUSE_DBT_PASSWORD",
    "CLICKHOUSE_METABASE_PASSWORD", "PLATFORM_DB_PASSWORD", "AIRFLOW_DB_PASSWORD", "METABASE_DB_PASSWORD",
    "AIRFLOW_WEBSERVER_SECRET_KEY", "AIRFLOW_ADMIN_PASSWORD", "METABASE_AIRFLOW_PASSWORD",
]


def render(project: str, offset: int) -> str:
    lines = [
        f"COMPOSE_PROJECT_NAME={project}",
        "MINIO_ROOT_USER=platform-admin",
        "CH_BACKUP_ACCESS_KEY=clickhouse-backup",
    ]
    lines += [f"{name}={secrets.token_urlsafe(24)}" for name in SECRETS]
    lines.append(f"AIRFLOW_FERNET_KEY={base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()}")
    lines += [f"{name}={port + offset}" for name, port in PORTS.items()]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="data-platform")
    parser.add_argument("--ports-offset", type=int, default=0)
    args = parser.parse_args()
    print(render(args.project, args.ports_offset), end="")
