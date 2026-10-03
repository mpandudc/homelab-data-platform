"""Post-build data quality gates for one logical date.

dbt tests prove the marts are internally consistent; these checks prove the
run for *this* date actually produced data, which a green dbt build alone does
not guarantee (an empty source passes every uniqueness test).
"""

from __future__ import annotations

import operator
from dataclasses import dataclass
from datetime import date

OPS = {">": operator.gt, "==": operator.eq, ">=": operator.ge}


@dataclass(frozen=True)
class Check:
    name: str
    sql: str
    op: str
    threshold: int

    def passes(self, value: int) -> bool:
        return OPS[self.op](value, self.threshold)


def checks_for(ds: date) -> list[Check]:
    day = f"toDate('{ds.isoformat()}')"
    return [
        Check("raw_trades_loaded", f"select count() from raw.trades where trade_date = {day}", ">", 0),
        Check(
            "fact_complete_for_day",
            f"select (select uniqExact(trade_id) from raw.trades where trade_date = {day})"
            f" - (select count() from marts.fact_trades where trade_date = {day})",
            "==",
            0,
        ),
        Check("fact_has_no_duplicates", "select count() - uniqExact(trade_id) from marts.fact_trades", "==", 0),
        Check("pnl_covers_day", f"select countIf(as_of_date = {day}) from marts.fct_daily_pnl", ">", 0),
        Check(
            "pnl_not_ahead_of_prices",
            "select (select max(as_of_date) from marts.fct_daily_pnl) > (select max(price_date) from raw.prices)",
            "==",
            0,
        ),
    ]


def evaluate(results: dict[str, int], checks: list[Check]) -> list[str]:
    """Return human-readable failures; empty means the gate passes."""
    failures = []
    for check in checks:
        value = results[check.name]
        if not check.passes(value):
            failures.append(f"{check.name}: got {value}, expected {check.op} {check.threshold}")
    return failures
