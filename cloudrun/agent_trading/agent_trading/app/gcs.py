from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from google.cloud import storage


def get_storage_client() -> storage.Client:
    return storage.Client()


def _case_prefix(*, cases_prefix: str, case_id: str) -> str:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{cases_prefix}/{day}/{case_id}"


def _resolve_case_prefix(
    *, client: storage.Client, bucket: str, cases_prefix: str, case_id: str
) -> str:
    """
    Try today's prefix first (fast path). If not found, scan all date
    prefixes to locate the case (same approach as agent_charts_signal).
    """
    default_prefix = _case_prefix(cases_prefix=cases_prefix, case_id=case_id)
    b = client.bucket(bucket)
    probe = b.blob(f"{default_prefix}/request.json")
    if probe.exists(client):
        return default_prefix

    root = f"{cases_prefix.rstrip('/')}/"
    iterator = client.list_blobs(b, prefix=root, delimiter="/")
    date_prefixes: list[str] = []
    for page in iterator.pages:
        date_prefixes.extend(page.prefixes or [])

    for date_prefix in date_prefixes:
        case_prefix = f"{date_prefix.rstrip('/')}/{case_id}"
        probe = b.blob(f"{case_prefix}/request.json")
        if probe.exists(client):
            return case_prefix

    raise KeyError(f"case not found: {case_id}")


def read_case_json(
    *,
    client: storage.Client,
    bucket: str,
    cases_prefix: str,
    case_id: str,
    name: str,
    case_prefix: str | None = None,
) -> Any:
    prefix = case_prefix or _resolve_case_prefix(
        client=client, bucket=bucket, cases_prefix=cases_prefix, case_id=case_id
    )
    b = client.bucket(bucket)
    blob = b.blob(f"{prefix}/{name}")
    data = blob.download_as_bytes()
    return json.loads(data.decode("utf-8"))


def write_case_json(
    *,
    client: storage.Client,
    bucket: str,
    cases_prefix: str,
    case_id: str,
    name: str,
    obj: Any,
    case_prefix: str | None = None,
) -> None:
    prefix = case_prefix or _resolve_case_prefix(
        client=client, bucket=bucket, cases_prefix=cases_prefix, case_id=case_id
    )
    b = client.bucket(bucket)
    blob = b.blob(f"{prefix}/{name}")
    data = json.dumps(obj, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    blob.upload_from_string(data, content_type="application/json")
