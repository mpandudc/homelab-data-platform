"""Minimal ClickHouse HTTP client (stdlib only, no provider package needed)."""

from __future__ import annotations

import base64
import os
import urllib.error
import urllib.request


class ClickHouse:
    def __init__(self, url: str, user: str, password: str, timeout: float = 60):
        self.url = url.rstrip("/") + "/"
        self.timeout = timeout
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}"}

    @classmethod
    def from_env(cls) -> ClickHouse:
        return cls(
            os.environ.get("CLICKHOUSE_URL", "http://clickhouse:8123"),
            os.environ.get("CLICKHOUSE_USER", "dbt"),
            os.environ.get("CLICKHOUSE_PASSWORD", "dbt"),
        )

    def execute(self, query: str) -> str:
        request = urllib.request.Request(self.url, data=query.encode(), headers=self.headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read().decode()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"ClickHouse error: {exc.read().decode()[:500]}") from exc

    def scalar(self, query: str) -> str:
        return self.execute(query).strip()

    def ping(self) -> bool:
        try:
            with urllib.request.urlopen(self.url + "ping", timeout=5) as response:
                return response.read().strip() == b"Ok."
        except OSError:
            return False
