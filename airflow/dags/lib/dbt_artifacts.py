"""Turn dbt's run_results.json into rows for ops.dbt_run_results, so model and
test outcomes per run are queryable (e.g. from Metabase) instead of living
only in task logs."""

from __future__ import annotations

import json
from pathlib import Path

DDL = (
    "CREATE TABLE IF NOT EXISTS ops.dbt_run_results ("
    " ds Date, run_id String, invocation_id String, unique_id String,"
    " resource_type LowCardinality(String), status LowCardinality(String),"
    " execution_time Float64, rows_affected Nullable(Int64), message String,"
    " generated_at DateTime64(3, 'UTC'))"
    " ENGINE = ReplacingMergeTree(generated_at) ORDER BY (ds, unique_id)"
)
COLUMNS = (
    "ds", "run_id", "invocation_id", "unique_id", "resource_type", "status",
    "execution_time", "rows_affected", "message", "generated_at",
)


def rows_from_run_results(payload: dict, ds: str, run_id: str) -> list[dict]:
    meta = payload.get("metadata", {})
    generated_at = meta.get("generated_at", "").replace("T", " ").rstrip("Z")[:23]
    rows = []
    for result in payload.get("results", []):
        unique_id = result["unique_id"]
        rows.append({
            "ds": ds,
            "run_id": run_id,
            "invocation_id": meta.get("invocation_id", ""),
            "unique_id": unique_id,
            "resource_type": unique_id.split(".", 1)[0],
            "status": str(result.get("status", "")),
            "execution_time": float(result.get("execution_time") or 0.0),
            "rows_affected": (result.get("adapter_response") or {}).get("rows_affected"),
            "message": str(result.get("message") or "")[:1000],
            "generated_at": generated_at,
        })
    return rows


def load_rows(path: Path, ds: str, run_id: str) -> list[dict]:
    if not path.exists():
        return []
    return rows_from_run_results(json.loads(path.read_text(encoding="utf-8")), ds, run_id)


def to_json_each_row(rows: list[dict]) -> str:
    return "\n".join(json.dumps(row, separators=(",", ":")) for row in rows)
