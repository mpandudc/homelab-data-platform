"""Failure alerts to a Discord-compatible webhook (the homelab's Hermes channel).

Disabled unless the Airflow Variable `alert_webhook_url` is set, so a fresh
checkout never posts anywhere.
"""

from __future__ import annotations

import json
import logging
import urllib.request

log = logging.getLogger(__name__)


def build_payload(dag_id: str, task_id: str, ds: str, try_number: int, log_url: str, error: str) -> dict:
    return {
        "username": "airflow",
        "content": (
            f"**{dag_id}.{task_id}** failed for `{ds}` (try {try_number})\n"
            f"> {error[:300]}\n{log_url}"
        ),
    }


def on_failure(context: dict) -> None:
    from airflow.models import Variable

    url = Variable.get("alert_webhook_url", default_var=None)
    ti = context["task_instance"]
    payload = build_payload(
        ti.dag_id, ti.task_id, context["ds"], ti.try_number, ti.log_url, str(context.get("exception", ""))
    )
    if not url:
        log.warning("alert_webhook_url not set; failure alert only logged: %s", payload["content"])
        return
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        urllib.request.urlopen(request, timeout=10).close()
    except OSError as exc:  # alerting must never mask the original failure
        log.error("failure alert could not be sent: %s", exc)
