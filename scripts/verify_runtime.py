"""Runtime verification of the whole platform, run beside the live stack.

Brings every profile up under project `hdp-verify` with all ports shifted by
+20000 and fresh secrets, proves each service works and is scoped correctly,
then tears it down. The live `data-stack` on the same host is never touched.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / "verify.env"
PROFILES = ["core", "stream", "orchestration", "bi", "docs"]
LONG_RUNNING = 9  # every profile but edge; minio-init and airflow-init are one-shot


def sh(*args: str, check: bool = True, env: dict | None = None) -> subprocess.CompletedProcess:
    print("+", " ".join(args[:12]), flush=True)
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, env=env)
    if check and result.returncode != 0:
        print(result.stdout[-3000:], result.stderr[-3000:], sep="\n")
        raise SystemExit(f"command failed: {' '.join(args[:12])}")
    return result


def compose(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    profiles = [x for p in PROFILES for x in ("--profile", p)]
    return sh("docker", "compose", "--env-file", str(ENV_FILE), *profiles, *args, check=check)


def http(url: str, user: str | None = None, password: str | None = None, data: str | None = None) -> tuple[int, str]:
    headers = {}
    if user:
        headers["Authorization"] = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
    req = urllib.request.Request(url, data=data.encode() if data else None, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, response.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")


def expect(condition: bool, message: str) -> None:
    print(("PASS " if condition else "FAIL ") + message, flush=True)
    if not condition:
        raise SystemExit(message)


def main() -> None:
    ENV_FILE.write_text(sh("python3", "scripts/make_env.py", "--project", "hdp-verify",
                           "--ports-offset", "20000").stdout)
    env = dict(line.split("=", 1) for line in ENV_FILE.read_text().splitlines())
    port = {k: int(v) for k, v in env.items() if k.endswith("_PORT")}
    evidence: dict = {"started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}

    compose("down", "--volumes", "--remove-orphans")
    started = time.monotonic()
    # Not `up --wait`: it treats a finished one-shot job (minio-init) as a failure.
    compose("up", "-d", "--build")
    deadline = time.monotonic() + 900
    while True:
        states = [json.loads(line) for line in compose("ps", "-a", "--format", "json").stdout.splitlines()]
        if sum(s.get("Health") == "healthy" for s in states) == LONG_RUNNING or time.monotonic() > deadline:
            break
        time.sleep(5)
    evidence["cold_start_seconds"] = round(time.monotonic() - started, 1)

    healthy = sorted(s["Service"] for s in states if s.get("Health") == "healthy")
    evidence["healthy_services"] = healthy
    expect(len(healthy) == LONG_RUNNING, f"{len(healthy)}/{LONG_RUNNING} long-running services healthy")
    inits = {s["Service"]: s["ExitCode"] for s in states if s["Service"] in ("minio-init", "airflow-init")}
    expect(inits == {"minio-init": 0, "airflow-init": 0}, f"bootstrap jobs exited 0 {inits}")

    # MinIO bootstrap
    mc = compose("run", "--rm", "--entrypoint", "sh", "minio-init", "-c",
                 'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null && '
                 "mc ls local && mc ilm rule ls local/bronze && mc admin user info local clickhouse-backup").stdout
    expect(all(b in mc for b in ("bronze/", "silver/", "ch-backups/")), "buckets bronze, silver, ch-backups exist")
    expect("90" in mc and "clickhouse-backup" in mc, "bronze 90-day expiry and scoped backup user exist")

    # ClickHouse scoping
    ch = f"http://localhost:{port['CLICKHOUSE_HTTP_PORT']}/"
    admin = ("admin", env["CLICKHOUSE_ADMIN_PASSWORD"])
    for statement in (
        "CREATE TABLE marts.smoke (id UInt32, v String) ENGINE = MergeTree ORDER BY id",
        "INSERT INTO marts.smoke SELECT number, toString(number) FROM numbers(10000)",
        "CREATE TABLE raw.secret (id UInt32) ENGINE = MergeTree ORDER BY id",
    ):
        code, body = http(ch, *admin, data=statement)
        expect(code == 200, f"admin: {statement[:40]}... ({body[:80].strip()})")
    mb = ("metabase", env["CLICKHOUSE_METABASE_PASSWORD"])
    dbt = ("dbt", env["CLICKHOUSE_DBT_PASSWORD"])
    expect(http(ch, *mb, data="SELECT count() FROM marts.smoke")[1].strip() == "10000", "metabase reads marts")
    expect(http(ch, *mb, data="INSERT INTO marts.smoke VALUES (1, 'x')")[0] != 200, "metabase cannot write")
    expect(http(ch, *mb, data="SELECT count() FROM raw.secret")[0] != 200, "metabase cannot read raw")
    expect(http(ch, *dbt, data="CREATE TABLE staging.t (id UInt8) ENGINE = Memory")[0] == 200, "dbt creates in staging")
    expect(http(ch, *dbt, data="CREATE DATABASE rogue")[0] != 200, "dbt cannot create databases")

    # Backup to MinIO and restore
    backup_env = {**os.environ, "ENV_FILE": str(ENV_FILE)}
    name = sh("python3", "scripts/backup_clickhouse.py", "backup", "marts", env=backup_env).stdout.strip()
    sh("python3", "scripts/backup_clickhouse.py", "restore", "marts", name, "--as", "marts_restore", env=backup_env)
    restored = http(ch, *admin, data="SELECT count(), sum(id) FROM marts_restore.smoke")[1].split()
    expect(restored == ["10000", "49995000"], f"backup {name} restored with identical rows")
    evidence["backup_name"] = name

    # Redpanda
    compose("exec", "-T", "redpanda", "rpk", "topic", "create", "smoke", "-p", "1")
    compose("exec", "-T", "redpanda", "sh", "-c", "echo hello-platform | rpk topic produce smoke")
    consumed = compose("exec", "-T", "redpanda", "rpk", "topic", "consume", "smoke", "-n", "1", "-f", "%v").stdout
    expect("hello-platform" in consumed, "redpanda produce/consume round trip")

    # Web UIs that edge/config.yml publishes on *.cahyo.tech
    uis = {
        "airflow": (f"http://localhost:{port['AIRFLOW_WEB_PORT']}/health", "healthy"),
        "metabase": (f"http://localhost:{port['METABASE_PORT']}/api/health", "ok"),
        "minio-console": (f"http://localhost:{port['MINIO_CONSOLE_PORT']}/", "MinIO"),
        "clickhouse-play": (f"http://localhost:{port['CLICKHOUSE_HTTP_PORT']}/play", "ClickHouse"),
        "redpanda-console": (f"http://localhost:{port['REDPANDA_CONSOLE_PORT']}/", "Redpanda"),
        "dbt-docs": (f"http://localhost:{port['DBT_DOCS_PORT']}/", "dbt"),
    }
    evidence["web_ui_status"] = {}
    for ui, (url, marker) in uis.items():
        code, body = http(url)
        evidence["web_ui_status"][ui] = code
        expect(code == 200 and marker.lower() in body.lower(), f"web UI {ui} serves ({code})")

    # Prometheus endpoints for LXC 207
    for service, url, marker in (
        ("clickhouse", f"http://localhost:{port['CLICKHOUSE_METRICS_PORT']}/metrics", "ClickHouseProfileEvents"),
        ("redpanda", f"http://localhost:{port['REDPANDA_ADMIN_PORT']}/public_metrics", "redpanda_"),
        ("minio", f"http://localhost:{port['MINIO_API_PORT']}/minio/v2/metrics/cluster", "minio_"),
    ):
        code, body = http(url)
        expect(code == 200 and marker in body, f"{service} exposes Prometheus metrics")

    # Airflow reaches every service
    smoke = compose("exec", "-T", "airflow-scheduler", "airflow", "dags", "test", "platform_smoke", check=False)
    output = smoke.stdout + smoke.stderr
    expect(smoke.returncode == 0 and "state=success" in output.replace(" ", ""), "platform_smoke DAG run succeeds")
    expect("skipped" not in output.lower().split("dagrun finished")[-1], "no probe skipped")

    # Edge ingress rules route each hostname to the intended service
    rules = sh("docker", "run", "--rm", "-v", f"{ROOT / 'edge'}:/e:ro", "cloudflare/cloudflared:2026.9.3",
               "tunnel", "--config", "/e/config.example.yml", "ingress", "rule", "https://dbt.cahyo.tech",
               check=False)
    expect("dbt-docs:8080" in rules.stdout + rules.stderr, "cloudflared ingress maps dbt.cahyo.tech -> dbt-docs")

    stats = compose("stats", "--no-stream", "--format", "{{.Name}}\t{{.MemUsage}}").stdout
    evidence["memory_usage"] = [line for line in stats.splitlines() if line.strip()]
    evidence["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    out = ROOT / "results" / "verification.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(evidence, indent=2) + "\n")
    compose("down", "--volumes", "--remove-orphans")
    ENV_FILE.unlink()
    print(f"evidence written to {out.relative_to(ROOT)}; verification stack removed")


if __name__ == "__main__":
    main()
