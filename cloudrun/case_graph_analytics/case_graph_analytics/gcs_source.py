from __future__ import annotations

import json
import logging
from typing import Any

from google.cloud import storage

_LOG = logging.getLogger(__name__)

_ARTIFACT_NAMES = [
    "request.json",
    "generate_status.json",
    "pass1_observations.json",
    "liquidation_heatmap_observations.json",
    "proposal_validated.json",
    "trade.json",
]


def get_storage_client() -> storage.Client:
    return storage.Client()


def list_case_prefixes(*, client: storage.Client, bucket: str, cases_prefix: str) -> dict[str, str]:
    base = cases_prefix.strip("/")
    if not base:
        raise ValueError("cases_prefix cannot be empty")

    result: dict[str, str] = {}
    b = client.bucket(bucket)
    prefix = f"{base}/"

    for blob in client.list_blobs(b, prefix=prefix):
        name = blob.name
        if not name.startswith(prefix):
            continue
        suffix = name[len(prefix) :]
        parts = suffix.split("/")
        if len(parts) < 2:
            continue
        date_part, case_id = parts[0], parts[1]
        case_prefix = f"{base}/{date_part}/{case_id}"
        result[case_id] = case_prefix
    return result


def _blob_exists(*, client: storage.Client, bucket: str, blob_name: str) -> bool:
    b = client.bucket(bucket)
    return b.blob(blob_name).exists(client)


def _read_json(*, client: storage.Client, bucket: str, blob_name: str) -> Any | None:
    b = client.bucket(bucket)
    data = b.blob(blob_name).download_as_bytes()
    return json.loads(data.decode("utf-8"))


def read_case_artifacts(*, client: storage.Client, bucket: str, case_prefix: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in _ARTIFACT_NAMES:
        blob_name = f"{case_prefix}/{name}"
        if not _blob_exists(client=client, bucket=bucket, blob_name=blob_name):
            continue
        try:
            out[name] = _read_json(client=client, bucket=bucket, blob_name=blob_name)
        except Exception as exc:
            _LOG.warning("failed to parse artifact %s: %s", blob_name, exc)
    return out
