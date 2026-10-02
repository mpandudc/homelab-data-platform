"""Offline compose policy checks (no Docker needed):

- every long-running service has mem_limit and the sum fits the LXC budget
- every long-running service has a healthcheck
- no :latest images; every published port is overridable via ${VAR:-default}
- secrets come from the environment, never literals
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUDGET_MB = 6656  # 6.5 GiB of the 8 GiB LXC; the rest is OS + page cache for ClickHouse
ONE_SHOT = {"minio-init", "airflow-init"}
NO_HEALTHCHECK = {"cloudflared"}  # outbound-only tunnel, no local port to probe


def services(text: str) -> dict[str, str]:
    body = text.split("\nservices:\n", 1)[1].split("\nvolumes:\n", 1)[0]
    parts = re.split(r"^  ([a-z0-9-]+):\n", body, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def to_mb(value: str) -> int:
    number, unit = int(value[:-1]), value[-1].lower()
    return number * 1024 if unit == "g" else number


def main() -> int:
    text = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    errors: list[str] = []
    total = 0
    for name, block in services(text).items():
        if name in ONE_SHOT:
            continue
        limit = re.search(r"^    mem_limit: (\d+[mg])$", block, flags=re.M)
        if not limit:
            errors.append(f"{name}: no mem_limit")
        else:
            total += to_mb(limit.group(1))
        if name not in NO_HEALTHCHECK and "healthcheck:" not in block:
            errors.append(f"{name}: no healthcheck")
    if total > BUDGET_MB:
        errors.append(f"memory budget exceeded: {total} MB > {BUDGET_MB} MB")
    if re.search(r"image: [^\s]+:latest", text):
        errors.append("an image uses :latest")
    for port in re.findall(r'^\s+- "([^"]+)"$', text, flags=re.M):
        if ":" in port and not port.startswith("${"):
            errors.append(f"published port not overridable: {port}")
    if re.search(r"(PASSWORD|SECRET|KEY): (?!\$\{)[^\s]+", text):
        errors.append("literal secret in compose.yaml")

    for error in errors:
        print("ERROR", error)
    print(f"long-running memory limits: {total} MB of {BUDGET_MB} MB budget; {'ok' if not errors else 'FAILED'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
