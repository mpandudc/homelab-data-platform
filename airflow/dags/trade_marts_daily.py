"""Daily trade marts: load one logical day, dbt build that window, gate on
data quality, record an audit row.

Every task is idempotent for its logical date, so retries, reruns and
backfills (`airflow dags backfill`) converge to the same marts.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from airflow.decorators import dag, task
from airflow.exceptions import AirflowFailException
from airflow.operators.bash import BashOperator
from airflow.sensors.python import PythonSensor
from lib.clickhouse import ClickHouse
from lib.dbt_artifacts import DDL as DBT_RESULTS_DDL
from lib.dbt_artifacts import load_rows, to_json_each_row
from lib.notify import on_failure
from lib.quality import checks_for, evaluate

DBT_PROJECT = os.environ.get("DBT_PROJECT_DIR", "/opt/dbt-project")
DBT_BIN = "/opt/dbt-venv/bin"
RUN_DIR = "/tmp/dbt/{{ run_id | replace(':', '_') | replace('+', '_') }}"
# On homelab-data-platform the databases are provisioned up front and the dbt
# user is not allowed CREATE DATABASE (not even IF NOT EXISTS), so skip those.
PLATFORM_MANAGED_DATABASES = os.environ.get("PLATFORM_MANAGED_DATABASES") == "1"

default_args = {
    "owner": "data-platform",
    "retries": 2,
    "retry_delay": timedelta(minutes=1),
    "execution_timeout": timedelta(minutes=20),
    "on_failure_callback": on_failure,
}


def clickhouse_is_up() -> bool:
    return ClickHouse.from_env().ping()


@dag(
    dag_id="trade_marts_daily",
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    # dbt rebuilds whole mart tables; two concurrent runs would race on the swap.
    max_active_runs=1,
    default_args=default_args,
    tags=["dbt", "clickhouse", "marts"],
    doc_md=__doc__,
)
def trade_marts_daily():
    clickhouse_ready = PythonSensor(
        task_id="clickhouse_ready",
        python_callable=clickhouse_is_up,
        poke_interval=10,
        timeout=300,
        mode="reschedule",
    )

    @task
    def ensure_raw_schema() -> int:
        """Apply the dbt project's raw DDL (all IF NOT EXISTS) so a fresh
        ClickHouse needs no manual bootstrap."""
        ddl = Path(DBT_PROJECT, "clickhouse", "init", "001_raw.sql").read_text(encoding="utf-8")
        body = "\n".join(line for line in ddl.splitlines() if not line.lstrip().startswith("--"))
        statements = [s.strip() for s in body.split(";") if s.strip()]
        ch = ClickHouse.from_env()
        if PLATFORM_MANAGED_DATABASES:
            statements = [s for s in statements if not s.upper().startswith("CREATE DATABASE")]
        for statement in statements:
            ch.execute(statement)
        return len(statements)

    load_raw = BashOperator(
        task_id="load_raw",
        bash_command=f"{DBT_BIN}/python {DBT_PROJECT}/scripts/load_raw.py --start {{{{ ds }}}} --days 1",
    )

    # Per-run target/log paths keep retries from tripping over each other's
    # artifacts and leave the baked-in project directory read-only.
    dbt_build = BashOperator(
        task_id="dbt_build",
        cwd=f"{DBT_PROJECT}/dbt",
        bash_command=(
            f"{DBT_BIN}/dbt build --profiles-dir profiles "
            f"--target-path {RUN_DIR}/target --log-path {RUN_DIR}/logs "
            "--vars '{start_date: \"{{ ds }}\", end_date: \"{{ ds }}\"}'"
        ),
    )

    @task
    def data_quality(ds: str | None = None) -> dict:
        ch = ClickHouse.from_env()
        checks = checks_for(date.fromisoformat(ds))
        results = {c.name: int(ch.scalar(c.sql)) for c in checks}
        failures = evaluate(results, checks)
        if failures:
            # Bad data does not get better on retry.
            raise AirflowFailException("data quality gate failed: " + "; ".join(failures))
        return results

    @task
    def record_run(results: dict, ds: str | None = None, run_id: str | None = None) -> None:
        ch = ClickHouse.from_env()
        if not PLATFORM_MANAGED_DATABASES:
            ch.execute("CREATE DATABASE IF NOT EXISTS ops")
        ch.execute(
            "CREATE TABLE IF NOT EXISTS ops.pipeline_runs ("
            " dag_id LowCardinality(String), ds Date, run_id String, metrics String,"
            " recorded_at DateTime64(3, 'UTC') DEFAULT now64(3))"
            " ENGINE = ReplacingMergeTree(recorded_at) ORDER BY (dag_id, ds)"
        )
        metrics = json.dumps(results, sort_keys=True).replace("'", "\\'")
        safe_run_id = (run_id or "").replace("'", "\\'")
        ch.execute(
            "INSERT INTO ops.pipeline_runs (dag_id, ds, run_id, metrics) VALUES "
            f"('trade_marts_daily', toDate('{ds}'), '{safe_run_id}', '{metrics}')"
        )

    # all_done: a failed build's results (which test failed) are the most useful ones.
    @task(trigger_rule="all_done")
    def load_dbt_results(ds: str | None = None, run_id: str | None = None) -> int:
        safe = (run_id or "").replace(":", "_").replace("+", "_")
        rows = load_rows(Path(f"/tmp/dbt/{safe}/target/run_results.json"), ds, run_id or "")
        if not rows:
            return 0
        ch = ClickHouse.from_env()
        if not PLATFORM_MANAGED_DATABASES:
            ch.execute("CREATE DATABASE IF NOT EXISTS ops")
        ch.execute(DBT_RESULTS_DDL)
        ch.execute("INSERT INTO ops.dbt_run_results FORMAT JSONEachRow\n" + to_json_each_row(rows))
        return len(rows)

    quality = data_quality()
    clickhouse_ready >> ensure_raw_schema() >> load_raw >> dbt_build >> quality
    dbt_build >> load_dbt_results()
    record_run(quality)


trade_marts_daily()
