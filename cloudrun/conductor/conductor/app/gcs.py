"""
Best-effort GCS case persistence (cases-auto prefix, ADR-0002/ADR-0003).

Layout (same bucket as manual vision cases, separate prefix so streams stay
cleanly separable and case_graph_analytics can ingest either):

  {CASES_PREFIX}/{YYYY-MM-DD}/{tick_id}/_tick.json          — tick summary
  {CASES_PREFIX}/{YYYY-MM-DD}/{tick_id}/{symbol}.json       — per-candidate case

Persistence must NEVER break the trading loop: every write is wrapped and
failures are logged + reported in the tick event stream as a non-fatal error.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

_log = logging.getLogger("conductor.gcs")

_client = None


def _get_client():
    global _client
    if _client is None:
        from google.cloud import storage  # deferred import

        _client = storage.Client()
    return _client


def tick_prefix(cases_prefix: str, tick_id: str, now: datetime | None = None) -> str:
    day = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    return f"{cases_prefix.rstrip('/')}/{day}/{tick_id}"


def write_json(bucket: str, path: str, obj: dict[str, Any]) -> str | None:
    """Write one JSON blob. Returns the gcs path on success, None on failure."""
    if not bucket:
        return None
    try:
        client = _get_client()
        blob = client.bucket(bucket).blob(path)
        blob.upload_from_string(
            json.dumps(obj, default=str, indent=1),
            content_type="application/json",
        )
        return f"gs://{bucket}/{path}"
    except Exception as exc:
        _log.warning("GCS write failed for %s: %s", path, exc)
        return None
