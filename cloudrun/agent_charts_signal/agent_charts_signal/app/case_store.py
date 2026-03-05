from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from chart_vision_common.constants import TIMEFRAMES_ORDER

from .gcs import download_bytes, sign_put_url, upload_json_bytes


@dataclass(frozen=True)
class CasePaths:
    case_prefix: str

    def charts_blob(self, tf: str) -> str:
        return f"{self.case_prefix}/charts/{tf}.png"

    def liquidation_heatmap_blob(self) -> str:
        return f"{self.case_prefix}/charts/liquidation_heatmap.png"

    def file_blob(self, name: str) -> str:
        return f"{self.case_prefix}/{name}"


def new_case_id() -> str:
    return uuid.uuid4().hex


def case_prefix(*, cases_prefix: str, case_id: str, now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    day = dt.strftime("%Y-%m-%d")
    return f"{cases_prefix}/{day}/{case_id}"


def build_case_paths(*, cases_prefix: str, case_id: str) -> CasePaths:
    return CasePaths(case_prefix=case_prefix(cases_prefix=cases_prefix, case_id=case_id))


def create_case_upload_urls(
    *,
    gcs_client,
    bucket: str,
    cases_prefix: str,
    case_id: str,
    ttl_seconds: int,
    timeframes: list[str] | None = None,
) -> tuple[CasePaths, dict[str, str], dict[str, str]]:
    tfs = timeframes or TIMEFRAMES_ORDER
    paths = build_case_paths(cases_prefix=cases_prefix, case_id=case_id)
    urls: dict[str, str] = {}
    for tf in tfs:
        urls[tf] = sign_put_url(
            client=gcs_client,
            bucket=bucket,
            blob_name=paths.charts_blob(tf),
            ttl_seconds=ttl_seconds,
            content_type="image/png",
        )
    extra_urls = {
        "liquidation_heatmap": sign_put_url(
            client=gcs_client,
            bucket=bucket,
            blob_name=paths.liquidation_heatmap_blob(),
            ttl_seconds=ttl_seconds,
            content_type="image/png",
        )
    }
    return paths, urls, extra_urls


def write_case_json(
    *,
    gcs_client,
    bucket: str,
    paths: CasePaths,
    name: str,
    obj: object,
) -> None:
    data = json.dumps(obj, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    upload_json_bytes(client=gcs_client, bucket=bucket, blob_name=paths.file_blob(name), data=data)


def read_case_json(*, gcs_client, bucket: str, paths: CasePaths, name: str) -> object:
    data = download_bytes(client=gcs_client, bucket=bucket, blob_name=paths.file_blob(name))
    return json.loads(data.decode("utf-8"))
