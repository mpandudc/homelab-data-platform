"""Platform smoke test: Airflow can reach every data-plane service.

Runs hourly once unpaused; a red run means a dependency is down before any
real pipeline notices. Services whose profile is not running are skipped.
"""

from __future__ import annotations

import os
import urllib.request
from datetime import datetime, timedelta

from airflow.decorators import dag, task
from airflow.exceptions import AirflowSkipException

ENDPOINTS = {
    "clickhouse": (os.environ.get("PLATFORM_CLICKHOUSE_URL", "http://clickhouse:8123") + "/ping", b"Ok."),
    "minio": (os.environ.get("PLATFORM_MINIO_URL", "http://minio:9000") + "/minio/health/live", b""),
    "redpanda": (os.environ.get("PLATFORM_REDPANDA_ADMIN_URL", "http://redpanda:9644") + "/v1/status/ready", b""),
    "metabase": (os.environ.get("PLATFORM_METABASE_URL", "http://metabase:3000") + "/api/health", b"ok"),
}
UNRESOLVED = ("Name or service not known", "Temporary failure in name resolution", "nodename nor servname")


def probe(url: str, expect: bytes) -> str:
    with urllib.request.urlopen(url, timeout=5) as response:
        body = response.read()
        if response.status != 200 or expect not in body:
            raise RuntimeError(f"{url} returned {response.status}: {body[:200]!r}")
        return body[:80].decode(errors="replace")


@dag(
    dag_id="platform_smoke",
    schedule="@hourly",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args={"retries": 1, "retry_delay": timedelta(seconds=30)},
    tags=["platform", "health"],
    doc_md=__doc__,
)
def platform_smoke():
    for name, (url, expect) in ENDPOINTS.items():

        @task(task_id=f"probe_{name}")
        def check(url: str = url, expect: bytes = expect) -> str:
            try:
                return probe(url, expect)
            except OSError as exc:
                # Name resolution fails when the service's profile is not up.
                if any(marker in str(exc) for marker in UNRESOLVED):
                    raise AirflowSkipException(f"{url} not deployed") from exc
                raise

        check()


platform_smoke()
