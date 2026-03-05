from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import threading
import time
import traceback
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import Body, FastAPI, HTTPException, Path as ApiPath, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from dotenv import load_dotenv

from chart_vision_common.constants import TIMEFRAMES_ORDER
from chart_vision_common.models import CaseAnalyzeRequest, CaseCreateResponse, LiquidationHeatmapObservations, TradeProposal

from .case_store import (
    CasePaths,
    build_case_paths,
    create_case_upload_urls,
    new_case_id,
    read_case_json,
    write_case_json,
)
from .config import Caps, Settings
from .gcs import blob_exists, delete_blob_prefix, download_bytes, get_storage_client, sign_get_url
from .llm.factory import build_provider
from .sse import EventBroker


app = FastAPI(title="agent_charts_signal", version="0.1.0")

_cors_origins_raw = os.environ.get("FRONTEND_CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173")
_cors_origins = [origin.strip() for origin in _cors_origins_raw.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_broker = EventBroker()

_CASE_SUMMARIES_CACHE_TTL_SECONDS = 300.0
_case_summaries_cache: dict[str, Any] = {
    "bucket": None,
    "cases_prefix": None,
    "expires_at": 0.0,
    "summaries_for_sort": [],
    "completed_case_ids": set(),
}
_case_summaries_lock = threading.Lock()
_LIST_PAGE_METADATA_WORKERS = 12
_list_metadata_executor = concurrent.futures.ThreadPoolExecutor(max_workers=_LIST_PAGE_METADATA_WORKERS)

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=_SERVICE_ROOT / ".env")

logging.basicConfig(level=logging.INFO)
_log = logging.getLogger("agent_charts_signal")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def _normalize_google_application_credentials_path() -> None:
    p = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not p:
        return
    path = Path(p)
    if path.is_absolute():
        return
    # Make relative paths work regardless of process CWD.
    # repo_root/cloudrun/agent_charts_signal/agent_charts_signal/app/main.py
    repo_root = Path(__file__).resolve().parents[4]
    abs_path = (repo_root / path).resolve()
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(abs_path)


def _invalidate_case_summaries_cache() -> None:
    _case_summaries_cache["expires_at"] = 0.0


def _get_sorted_case_summaries_for_list(*, client, settings: Settings) -> list[dict[str, Any]]:
    now = time.monotonic()
    if (
        _case_summaries_cache.get("bucket") == settings.gcs_bucket
        and _case_summaries_cache.get("cases_prefix") == settings.cases_prefix
        and now < float(_case_summaries_cache.get("expires_at") or 0.0)
    ):
        return list(_case_summaries_cache.get("summaries_for_sort") or [])

    with _case_summaries_lock:
        now = time.monotonic()
        if (
            _case_summaries_cache.get("bucket") == settings.gcs_bucket
            and _case_summaries_cache.get("cases_prefix") == settings.cases_prefix
            and now < float(_case_summaries_cache.get("expires_at") or 0.0)
        ):
            return list(_case_summaries_cache.get("summaries_for_sort") or [])

        by_case_id = _list_case_prefixes(client=client, bucket=settings.gcs_bucket, cases_prefix=settings.cases_prefix)
        summaries_for_sort: list[dict[str, Any]] = []
        for case_id, prefix in by_case_id.items():
            parts = prefix.split("/")
            if len(parts) < 3:
                continue
            date_str = parts[-2]
            summaries_for_sort.append(
                {
                    "case_id": case_id,
                    "date": date_str,
                    "prefix": prefix,
                    "symbol": None,
                    "timestamp_utc": None,
                }
            )

        summaries_for_sort.sort(
            key=lambda item: (
                item.get("date") or "",
                item.get("case_id") or "",
            ),
            reverse=True,
        )

        completed_case_ids: set[str] = set()
        bucket_ref = client.bucket(settings.gcs_bucket)
        prefix = f"{settings.cases_prefix.rstrip('/')}/"
        try:
            proposal_iter = client.list_blobs(bucket_ref, prefix=prefix, match_glob="**/proposal_validated.json")
        except TypeError:
            proposal_iter = client.list_blobs(bucket_ref, prefix=prefix)
        for blob in proposal_iter:
            blob_name = blob.name
            if not blob_name.endswith("/proposal_validated.json"):
                continue
            case_prefix = _case_prefix_from_blob_name(blob_name, settings.cases_prefix)
            if case_prefix is None:
                continue
            case_id = case_prefix.split("/")[-1]
            if case_id:
                completed_case_ids.add(case_id)

        _case_summaries_cache.update(
            {
                "bucket": settings.gcs_bucket,
                "cases_prefix": settings.cases_prefix,
                "expires_at": now + _CASE_SUMMARIES_CACHE_TTL_SECONDS,
                "summaries_for_sort": summaries_for_sort,
                "completed_case_ids": completed_case_ids,
            }
        )
        return list(summaries_for_sort)


_normalize_google_application_credentials_path()

_FRONTEND_CHART_ORDER = ["1m", "5m", "15m", "30m", "1h", "4h"]
_PROVIDER_MODEL_FIELDS = {
    "claude": {
        "pass1": "claude_model_pass1",
        "pass2": "claude_model_pass2",
        "fallbacks": "claude_model_fallbacks",
    },
    "openai": {
        "pass1": "openai_model_pass1",
        "pass2": "openai_model_pass2",
        "fallbacks": "openai_model_fallbacks",
    },
    "gemini": {
        "pass1": "gemini_model_pass1",
        "pass2": "gemini_model_pass2",
        "fallbacks": "gemini_model_fallbacks",
    },
}


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    _log.error("Unhandled exception on %s %s: %s", request.method, request.url.path, exc)
    _log.error(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "detail": f"{type(exc).__name__}: {exc}",
        },
    )


def _settings() -> Settings:
    try:
        return Settings()
    except Exception as e:
        raise RuntimeError(f"Invalid settings: {e}")


def _case_prefix_from_blob_name(blob_name: str, cases_prefix: str) -> str | None:
    normalized = cases_prefix.strip("/")
    needle = f"{normalized}/"
    if not blob_name.startswith(needle):
        return None
    parts = blob_name.split("/")
    if len(parts) < 4:
        return None
    if parts[0] != normalized:
        return None
    # {cases_prefix}/{YYYY-MM-DD}/{case_id}/...
    return "/".join(parts[:3])


def _list_child_prefixes(*, client, bucket: str, prefix: str) -> list[str]:
    bucket_ref = client.bucket(bucket)
    iterator = client.list_blobs(bucket_ref, prefix=prefix, delimiter="/")
    prefixes: set[str] = set()
    for page in iterator.pages:
        for child_prefix in page.prefixes:
            if isinstance(child_prefix, str) and child_prefix:
                prefixes.add(child_prefix)
    return sorted(prefixes)


def _list_case_prefixes(*, client, bucket: str, cases_prefix: str) -> dict[str, str]:
    root_prefix = f"{cases_prefix.rstrip('/')}/"
    date_prefixes = _list_child_prefixes(client=client, bucket=bucket, prefix=root_prefix)

    by_case_id: dict[str, str] = {}
    for date_prefix in date_prefixes:
        case_prefixes = _list_child_prefixes(client=client, bucket=bucket, prefix=date_prefix)
        for raw_case_prefix in case_prefixes:
            case_prefix = raw_case_prefix.rstrip("/")
            parts = case_prefix.split("/")
            if len(parts) < 3:
                continue
            if parts[0] != cases_prefix.strip("/"):
                continue
            case_id = parts[-1]
            if not case_id:
                continue
            by_case_id[case_id] = case_prefix

    if by_case_id:
        return by_case_id

    # Fallback to blob-name extraction for environments where delimiters/prefixes are unavailable.
    bucket_ref = client.bucket(bucket)
    for blob in client.list_blobs(bucket_ref, prefix=root_prefix):
        blob_name = blob.name
        prefix = _case_prefix_from_blob_name(blob_name, cases_prefix)
        if prefix is None:
            continue
        case_id = prefix.split("/")[-1]
        by_case_id[case_id] = prefix
    return by_case_id


def _resolve_case_paths(*, client, settings: Settings, case_id: str) -> CasePaths:
    # Fast path for same-day writes/reads (existing behavior).
    default_paths = build_case_paths(cases_prefix=settings.cases_prefix, case_id=case_id)
    if blob_exists(
        client=client,
        bucket=settings.gcs_bucket,
        blob_name=default_paths.file_blob("request.json"),
    ):
        return default_paths

    by_case_id = _list_case_prefixes(client=client, bucket=settings.gcs_bucket, cases_prefix=settings.cases_prefix)
    case_prefix = by_case_id.get(case_id)
    if not case_prefix:
        raise HTTPException(status_code=404, detail=f"case not found: {case_id}")
    return CasePaths(case_prefix=case_prefix)


def _try_read_case_json(*, client, bucket: str, paths: CasePaths, name: str) -> Any | None:
    blob_name = paths.file_blob(name)
    try:
        return read_case_json(gcs_client=client, bucket=bucket, paths=paths, name=name)
    except Exception:
        _log.debug("Failed reading %s", blob_name)
        return None


def _provider_models(settings: Settings) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for provider, fields in _PROVIDER_MODEL_FIELDS.items():
        pass1 = getattr(settings, fields["pass1"])
        pass2 = getattr(settings, fields["pass2"])
        fallbacks_raw = getattr(settings, fields["fallbacks"])
        fallback_models = [m.strip() for m in fallbacks_raw.split(",") if m.strip()]
        available_models = list(dict.fromkeys([pass1, pass2, *fallback_models]))
        out[provider] = {
            "pass1_default": pass1,
            "pass2_default": pass2,
            "available_models": available_models,
        }
    return out


def _signed_chart_urls(*, client, settings: Settings, paths: CasePaths) -> dict[str, str]:
    urls: dict[str, str] = {}
    for tf in _FRONTEND_CHART_ORDER:
        blob_name = paths.charts_blob(tf)
        if blob_exists(client=client, bucket=settings.gcs_bucket, blob_name=blob_name):
            urls[tf] = sign_get_url(
                client=client,
                bucket=settings.gcs_bucket,
                blob_name=blob_name,
                ttl_seconds=settings.signed_url_ttl_seconds,
            )
    return urls


def _signed_liquidation_heatmap_url(*, client, settings: Settings, paths: CasePaths) -> str | None:
    blob_name = paths.liquidation_heatmap_blob()
    if not blob_exists(client=client, bucket=settings.gcs_bucket, blob_name=blob_name):
        return None
    return sign_get_url(
        client=client,
        bucket=settings.gcs_bucket,
        blob_name=blob_name,
        ttl_seconds=settings.signed_url_ttl_seconds,
    )


def _read_generation_status(*, client, bucket: str, paths: CasePaths) -> dict[str, Any] | None:
    status_obj = _try_read_case_json(client=client, bucket=bucket, paths=paths, name="generate_status.json")
    if isinstance(status_obj, dict):
        return status_obj
    return None


def _write_generation_status(
    *,
    client,
    settings: Settings,
    paths: CasePaths,
    state: str,
    detail: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "state": state,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if detail:
        payload["detail"] = detail
    if extra:
        payload.update(extra)
    write_case_json(
        gcs_client=client,
        bucket=settings.gcs_bucket,
        paths=paths,
        name="generate_status.json",
        obj=payload,
    )


def _is_stale_generation_state(*, settings: Settings, generation_status_obj: dict[str, Any] | None) -> bool:
    if not isinstance(generation_status_obj, dict):
        return False
    state_raw = generation_status_obj.get("state")
    if not isinstance(state_raw, str):
        return False
    state = state_raw.strip().lower()
    if state not in {"queued", "running"}:
        return False

    updated_raw = generation_status_obj.get("updated_at")
    if not isinstance(updated_raw, str) or not updated_raw.strip():
        return False
    try:
        normalized = updated_raw.replace("Z", "+00:00")
        updated_at = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)

    stale_minutes = max(1, int(settings.generation_stale_minutes or 20))
    deadline = updated_at + timedelta(minutes=stale_minutes)
    return datetime.now(timezone.utc) >= deadline


def _derive_generation_state(
    *,
    settings: Settings,
    proposal_obj: Any,
    generation_status_obj: dict[str, Any] | None,
) -> str:
    if proposal_obj:
        if isinstance(generation_status_obj, dict):
            state = generation_status_obj.get("state")
            if isinstance(state, str) and state.strip().lower() == "failed":
                return "failed"
        return "completed"

    if isinstance(generation_status_obj, dict):
        if _is_stale_generation_state(settings=settings, generation_status_obj=generation_status_obj):
            return "failed"
        state = generation_status_obj.get("state")
        if isinstance(state, str) and state.strip():
            return state.strip()
    return "created"


def _capture_worker_url_for_path(settings: Settings, path: str) -> str:
    base_url = settings.capture_worker_url
    if not base_url:
        raise HTTPException(
            status_code=503,
            detail=(
                "CAPTURE_WORKER_URL is not configured. Set CAPTURE_WORKER_URL to an HTTP endpoint "
                "that starts your mac capture_and_upload pipeline for a given case_id."
            ),
        )

    parsed = urlsplit(base_url)
    target_path = path if path.startswith("/") else f"/{path}"
    return urlunsplit((parsed.scheme, parsed.netloc, target_path, "", ""))


async def _call_capture_worker(
    settings: Settings,
    *,
    path: str,
    method: str = "POST",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status_code, content, content_type = await _call_capture_worker_raw(
        settings,
        path=path,
        method=method,
        payload=payload,
    )
    if status_code == 204 or not content:
        return {"ok": True}
    if content_type and "application/json" not in content_type.lower():
        return {"raw": content.decode("utf-8", errors="replace")}
    try:
        data = json.loads(content)
    except ValueError:
        data = {"raw": content.decode("utf-8", errors="replace")}
    if isinstance(data, dict):
        return data
    return {"response": data}


async def _call_capture_worker_raw(
    settings: Settings,
    *,
    path: str,
    method: str = "POST",
    payload: dict[str, Any] | None = None,
) -> tuple[int, bytes, str | None]:
    worker_url = _capture_worker_url_for_path(settings, path)

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if settings.capture_worker_token:
        headers["Authorization"] = f"Bearer {settings.capture_worker_token}"

    timeout = httpx.Timeout(settings.capture_worker_timeout_seconds, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method.upper(), worker_url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"capture worker request failed: {type(exc).__name__}: {exc}")

    if response.status_code >= 400:
        text = response.text if response.text is not None else response.content.decode("utf-8", errors="replace")
        raise HTTPException(
            status_code=502,
            detail=(
                f"capture worker ({path}) returned HTTP {response.status_code}: "
                f"{(text or '').strip()[:400]}"
            ),
        )
    return response.status_code, response.content or b"", response.headers.get("content-type")


async def _trigger_capture_worker(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    return await _call_capture_worker(settings, path="/trigger-capture", method="POST", payload=payload)


def _validate_caps(proposal: TradeProposal, caps: Caps) -> TradeProposal:
    if proposal.long_short_none in ("LONG", "SHORT"):
        if proposal.leverage is None or proposal.margin_percent is None:
            raise ValueError("leverage and margin_percent must be provided for LONG/SHORT")
        if proposal.leverage > caps.max_leverage:
            raise ValueError("leverage exceeds MAX_LEVERAGE")
        if proposal.margin_percent > caps.max_margin_percent:
            raise ValueError("margin_percent exceeds MAX_MARGIN_PERCENT")
    return proposal


@app.get("/v1/frontend/meta")
async def frontend_meta() -> JSONResponse:
    settings = _settings()
    payload = {
        "default_provider": settings.vision_provider,
        "providers": _provider_models(settings),
        "timeframes": _FRONTEND_CHART_ORDER,
        "charts_enabled_defaults": {
            "liquidation_heatmap": True,
            "timeframes": _FRONTEND_CHART_ORDER,
        },
    }
    return JSONResponse(content=payload)


@app.get("/v1/cases")
def list_cases(
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    settings = _settings()
    client = get_storage_client()
    summaries_for_sort = _get_sorted_case_summaries_for_list(client=client, settings=settings)

    total_cases = len(summaries_for_sort)
    page_records = summaries_for_sort[offset : offset + limit]
    completed_case_ids = _case_summaries_cache.get("completed_case_ids") or set()

    def _read_case_list_metadata(record: dict[str, Any]) -> dict[str, Any]:
        case_prefix_paths = CasePaths(case_prefix=record["prefix"])
        generate_request_obj = _try_read_case_json(
            client=client,
            bucket=settings.gcs_bucket,
            paths=case_prefix_paths,
            name="generate_request.json",
        ) or {}
        if not isinstance(generate_request_obj, dict):
            generate_request_obj = {}

        generate_status_obj = _read_generation_status(
            client=client,
            bucket=settings.gcs_bucket,
            paths=case_prefix_paths,
        )
        status_state = ""
        if isinstance(generate_status_obj, dict):
            state_raw = generate_status_obj.get("state")
            if isinstance(state_raw, str):
                status_state = state_raw

        symbol = generate_request_obj.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            symbol = None

        model = generate_request_obj.get("vision_model_pass2")
        if not isinstance(model, str) or not model.strip():
            model = None

        requested_at = generate_request_obj.get("requested_at")
        if not isinstance(requested_at, str) or not requested_at.strip():
            requested_at = None

        return {
            "case_id": record["case_id"],
            "symbol": symbol,
            "model": model,
            "timestamp_utc": requested_at,
            "status": status_state,
        }

    metadata_by_case_id: dict[str, dict[str, Any]] = {}
    future_by_case_id: dict[str, concurrent.futures.Future[dict[str, Any]]] = {}
    for record in page_records:
        future = _list_metadata_executor.submit(_read_case_list_metadata, record)
        future_by_case_id[record["case_id"]] = future

    for case_id, future in future_by_case_id.items():
        try:
            metadata_by_case_id[case_id] = future.result(timeout=6.0)
        except Exception:
            metadata_by_case_id[case_id] = {}

    summaries: list[dict[str, Any]] = []
    for record in page_records:
        case_id = record["case_id"]
        date_str = record["date"]
        metadata = metadata_by_case_id.get(case_id) or {}
        status = metadata.get("status")
        if not isinstance(status, str) or not status.strip():
            status = "completed" if case_id in completed_case_ids else "created"
        generation_state = status
        summaries.append(
            {
                "case_id": case_id,
                "date": date_str,
                "symbol": metadata.get("symbol"),
                "model": metadata.get("model"),
                "timestamp_utc": metadata.get("timestamp_utc") or f"{date_str}T00:00:00Z",
                "status": generation_state,
                "generation_state": generation_state,
                "direction": None,
                "confidence": None,
            }
        )

    summaries.sort(
        key=lambda item: (
            item.get("timestamp_utc") or f"{item.get('date', '')}T00:00:00Z",
            item.get("case_id") or "",
        ),
        reverse=True,
    )

    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in summaries:
        by_date[item.get("date") or "unknown"].append(item)

    groups = []
    for date_str in sorted(by_date.keys(), reverse=True):
        items = sorted(
            by_date[date_str],
            key=lambda item: item.get("timestamp_utc") or "",
            reverse=True,
        )
        groups.append({"date": date_str, "items": items})

    next_offset = offset + len(page_records)
    has_more = next_offset < total_cases
    return JSONResponse(
        content={
            "groups": groups,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "next_offset": next_offset,
                "has_more": has_more,
                "total": total_cases,
            },
        }
    )


@app.get("/v1/cases/stream")
async def stream_cases(request: Request) -> StreamingResponse:
    q = await _broker.subscribe()

    async def gen():
        try:
            while True:
                if await request.is_disconnected():
                    break
                ev = await q.get()
                payload = {
                    "type": ev.type,
                    "case_id": ev.case_id,
                    "ts": ev.ts.isoformat(),
                    "data": ev.data,
                }
                yield f"event: {ev.type}\n".encode("utf-8")
                yield f"data: {json.dumps(payload)}\n\n".encode("utf-8")
        finally:
            await _broker.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/v1/cases/{case_id}")
async def get_case(case_id: str = ApiPath(..., min_length=6)) -> JSONResponse:
    settings = _settings()
    client = get_storage_client()
    paths = _resolve_case_paths(client=client, settings=settings, case_id=case_id)

    request_obj = _try_read_case_json(client=client, bucket=settings.gcs_bucket, paths=paths, name="request.json")
    proposal_obj = _try_read_case_json(client=client, bucket=settings.gcs_bucket, paths=paths, name="proposal_validated.json")
    pass2_obj = _try_read_case_json(client=client, bucket=settings.gcs_bucket, paths=paths, name="llm_raw_pass2.json")
    pass1_obj = _try_read_case_json(client=client, bucket=settings.gcs_bucket, paths=paths, name="llm_raw_pass1.json")
    pass1_observations_obj = _try_read_case_json(
        client=client,
        bucket=settings.gcs_bucket,
        paths=paths,
        name="pass1_observations.json",
    )
    liquidation_obj = _try_read_case_json(
        client=client,
        bucket=settings.gcs_bucket,
        paths=paths,
        name="llm_raw_liquidation_heatmap.json",
    )
    liquidation_observations_obj = _try_read_case_json(
        client=client,
        bucket=settings.gcs_bucket,
        paths=paths,
        name="liquidation_heatmap_observations.json",
    )
    trade_obj = _try_read_case_json(client=client, bucket=settings.gcs_bucket, paths=paths, name="trade.json")
    generation_status_obj = _read_generation_status(client=client, bucket=settings.gcs_bucket, paths=paths)
    generation_state = _derive_generation_state(
        settings=settings,
        proposal_obj=proposal_obj,
        generation_status_obj=generation_status_obj,
    )

    payload = {
        "case_id": case_id,
        "prefix": paths.case_prefix,
        "request": request_obj,
        "proposal_validated": proposal_obj,
        "llm_raw_pass2": pass2_obj,
        "llm_raw_pass1": pass1_obj,
        "pass1_observations": pass1_observations_obj,
        "llm_raw_liquidation_heatmap": liquidation_obj,
        "liquidation_heatmap_observations": liquidation_observations_obj,
        "trade": trade_obj,
        "generation_status": generation_status_obj,
        "generation_state": generation_state,
        "chart_urls": _signed_chart_urls(client=client, settings=settings, paths=paths),
        "liquidation_heatmap_url": _signed_liquidation_heatmap_url(client=client, settings=settings, paths=paths),
    }
    return JSONResponse(content=payload)


@app.delete("/v1/cases/{case_id}")
async def delete_case(case_id: str = ApiPath(..., min_length=6)) -> JSONResponse:
    settings = _settings()
    client = get_storage_client()
    paths = _resolve_case_paths(client=client, settings=settings, case_id=case_id)
    _invalidate_case_summaries_cache()

    deleted_count = delete_blob_prefix(
        client=client,
        bucket=settings.gcs_bucket,
        prefix=f"{paths.case_prefix.rstrip('/')}/",
    )
    await _broker.publish("case_deleted", case_id, {"deleted": deleted_count})
    return JSONResponse(content={"ok": True, "case_id": case_id, "deleted": deleted_count})


@app.post("/v1/cases/{case_id}/resize-windows-dismiss-tv-banner")
async def resize_windows_dismiss_tv_banner_for_case(
    case_id: str = ApiPath(..., min_length=6),
    body: dict[str, Any] = Body(default={}),
) -> JSONResponse:
    settings = _settings()
    client = get_storage_client()
    paths = _resolve_case_paths(client=client, settings=settings, case_id=case_id)

    request_obj = _try_read_case_json(client=client, bucket=settings.gcs_bucket, paths=paths, name="request.json") or {}
    symbol = body.get("symbol")
    if not isinstance(symbol, str) or not symbol.strip():
        symbol = request_obj.get("symbol") if isinstance(request_obj, dict) else None
    normalized_symbol = symbol.strip() if isinstance(symbol, str) and symbol.strip() else None

    payload = {
        "symbol": normalized_symbol,
        "tv_resize_and_dismiss_banner": body.get("tv_resize_and_dismiss_banner"),
        "tv_calibrate_window_size": body.get("tv_calibrate_window_size"),
        "show_tv_window_on_calibration": body.get("show_tv_window_on_calibration"),
        "dismiss_tv_banner": body.get("dismiss_tv_banner"),
        "tv_window_width": body.get("tv_window_width"),
        "tv_window_height": body.get("tv_window_height"),
        "tv_window_resize_wait_seconds": body.get("tv_window_resize_wait_seconds"),
        "window_owner": body.get("window_owner"),
        "window_title_template": body.get("window_title_template"),
        "debug_env": body.get("debug_env"),
    }

    worker_response = await _call_capture_worker(
        settings,
        path="/resize-windows-dismiss-tv-banner",
        method="POST",
        payload=payload,
    )
    await _broker.publish("windows_resized", case_id, worker_response)
    return JSONResponse(content={"ok": True, "case_id": case_id, "worker_response": worker_response})


@app.post("/v1/cases/{case_id}/trade")
async def save_case_trade(
    case_id: str = ApiPath(..., min_length=6),
    body: dict[str, Any] = Body(...),
) -> JSONResponse:
    settings = _settings()
    client = get_storage_client()
    paths = _resolve_case_paths(client=client, settings=settings, case_id=case_id)

    write_case_json(
        gcs_client=client,
        bucket=settings.gcs_bucket,
        paths=paths,
        name="trade.json",
        obj=body,
    )
    await _broker.publish("trade_saved", case_id, {"ok": True})
    return JSONResponse(content={"ok": True})


@app.post("/v1/cases/{case_id}/generate")
async def trigger_case_generation(
    case_id: str = ApiPath(..., min_length=6),
    body: dict[str, Any] = Body(...),
) -> JSONResponse:
    settings = _settings()
    client = get_storage_client()
    paths = _resolve_case_paths(client=client, settings=settings, case_id=case_id)

    request_payload = {
        **body,
        "case_id": case_id,
        "requested_at": datetime.now(timezone.utc).isoformat(),
    }
    write_case_json(
        gcs_client=client,
        bucket=settings.gcs_bucket,
        paths=paths,
        name="generate_request.json",
        obj=request_payload,
    )
    _write_generation_status(
        client=client,
        settings=settings,
        paths=paths,
        state="queued",
        detail="Generation request received",
    )
    await _broker.publish("generate_requested", case_id, request_payload)

    _write_generation_status(
        client=client,
        settings=settings,
        paths=paths,
        state="running",
        detail="Capture worker trigger in progress",
    )
    await _broker.publish("generation_started", case_id, {"phase": "worker_trigger"})
    try:
        worker_response = await _trigger_capture_worker(settings, request_payload)
    except HTTPException as exc:
        _write_generation_status(
            client=client,
            settings=settings,
            paths=paths,
            state="failed",
            detail=str(exc.detail),
        )
        await _broker.publish("generation_failed", case_id, {"detail": str(exc.detail)})
        raise

    _write_generation_status(
        client=client,
        settings=settings,
        paths=paths,
        state="running",
        detail="Capture worker accepted request",
        extra={"worker_response": worker_response},
    )
    await _broker.publish("generation_triggered", case_id, {"worker_response": worker_response})
    return JSONResponse(content={"ok": True, "queued": True, "worker_response": worker_response})


@app.post("/v1/cases/{case_id}/upload-urls")
async def create_case_upload_urls_for_existing_case(case_id: str = ApiPath(..., min_length=6)) -> JSONResponse:
    settings = _settings()
    client = get_storage_client()
    _resolve_case_paths(client=client, settings=settings, case_id=case_id)

    _, upload_urls, extra_upload_urls = create_case_upload_urls(
        gcs_client=client,
        bucket=settings.gcs_bucket,
        cases_prefix=settings.cases_prefix,
        case_id=case_id,
        ttl_seconds=settings.signed_url_ttl_seconds,
        timeframes=TIMEFRAMES_ORDER,
    )
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.signed_url_ttl_seconds)
    return JSONResponse(
        content={
            "case_id": case_id,
            "upload_urls": upload_urls,
            "extra_upload_urls": extra_upload_urls,
            "analyze_url": f"/v1/cases/{case_id}/analyze",
            "expires_at": expires_at.isoformat(),
        }
    )


@app.post("/v1/worker/capture/trigger")
async def trigger_capture_worker_endpoint(body: dict[str, Any] = Body(...)) -> JSONResponse:
    case_id_raw = body.get("case_id")
    case_id = case_id_raw if isinstance(case_id_raw, str) else ""
    if not case_id:
        raise HTTPException(status_code=400, detail="case_id is required")

    settings = _settings()
    client = get_storage_client()
    paths = _resolve_case_paths(client=client, settings=settings, case_id=case_id)

    _write_generation_status(
        client=client,
        settings=settings,
        paths=paths,
        state="running",
        detail="Capture worker trigger in progress",
    )
    await _broker.publish("generation_started", case_id, {"phase": "worker_trigger"})
    worker_response = await _trigger_capture_worker(settings, body)
    _write_generation_status(
        client=client,
        settings=settings,
        paths=paths,
        state="running",
        detail="Capture worker accepted request",
        extra={"worker_response": worker_response},
    )
    await _broker.publish("generation_triggered", case_id, {"worker_response": worker_response})
    return JSONResponse(content={"ok": True, "worker_response": worker_response})


@app.get("/v1/worker/tradingview/windows")
async def list_tradingview_windows_endpoint() -> Response:
    settings = _settings()
    status_code, content, content_type = await _call_capture_worker_raw(
        settings,
        path="/tradingview/windows",
        method="GET",
    )
    return Response(content=content, status_code=status_code, media_type=content_type or "application/json")


@app.post("/v1/worker/tradingview/windows/arrange")
async def arrange_tradingview_windows_endpoint(body: dict[str, Any] = Body(...)) -> Response:
    settings = _settings()
    status_code, content, content_type = await _call_capture_worker_raw(
        settings,
        path="/tradingview/windows/arrange",
        method="POST",
        payload=body,
    )
    return Response(content=content, status_code=status_code, media_type=content_type or "application/json")


@app.post("/v1/cases/create", response_model=CaseCreateResponse)
async def create_case() -> CaseCreateResponse:
    settings = _settings()
    client = get_storage_client()
    case_id = new_case_id()
    _invalidate_case_summaries_cache()

    try:
        paths, upload_urls, extra_upload_urls = create_case_upload_urls(
            gcs_client=client,
            bucket=settings.gcs_bucket,
            cases_prefix=settings.cases_prefix,
            case_id=case_id,
            ttl_seconds=settings.signed_url_ttl_seconds,
            timeframes=TIMEFRAMES_ORDER,
        )
    except Exception as e:
        _log.error("Failed to create signed upload URLs: %s", e)
        _log.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to create signed GCS upload URLs. "
                "This usually means the server credentials cannot sign URLs. "
                "For local dev, set GOOGLE_APPLICATION_CREDENTIALS to a service-account key JSON that has access to the bucket "
                "(or run this service on Cloud Run with a service account). "
                f"Underlying error: {type(e).__name__}: {e}"
            ),
        )

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.signed_url_ttl_seconds)

    analyze_url = f"/v1/cases/{case_id}/analyze"

    write_case_json(
        gcs_client=client,
        bucket=settings.gcs_bucket,
        paths=paths,
        name="request.json",
        obj={"case_id": case_id, "created_at": datetime.now(timezone.utc).isoformat()},
    )
    write_case_json(
        gcs_client=client,
        bucket=settings.gcs_bucket,
        paths=paths,
        name="label.json",
        obj={},
    )
    _write_generation_status(
        client=client,
        settings=settings,
        paths=paths,
        state="created",
        detail="Case created; awaiting generation request",
    )

    await _broker.publish("created", case_id, {"upload_tfs": TIMEFRAMES_ORDER})

    return CaseCreateResponse(
        case_id=case_id,
        upload_urls=upload_urls,
        extra_upload_urls=extra_upload_urls,
        analyze_url=analyze_url,
        expires_at=expires_at,
    )


@app.post("/v1/cases/{case_id}/analyze", response_model=TradeProposal)
async def analyze_case(
    case_id: str = ApiPath(..., min_length=6),
    body: CaseAnalyzeRequest = Body(...),
) -> TradeProposal:
    settings = _settings()
    provider = build_provider(
        settings,
        provider_override=body.vision_provider,
        model_pass1_override=body.vision_model_pass1,
        model_pass2_override=body.vision_model_pass2,
    )
    liquidation_heatmap_horizon_hours = (
        body.liquidation_heatmap_time_horizon_hours or settings.liquidation_heatmap_time_horizon_hours
    )
    client = get_storage_client()
    paths = build_case_paths(cases_prefix=settings.cases_prefix, case_id=case_id)

    if body.timeframes_order != TIMEFRAMES_ORDER:
        raise HTTPException(status_code=400, detail="timeframes_order must match the fixed order")

    images_by_tf: dict[str, bytes] = {}
    for tf in TIMEFRAMES_ORDER:
        try:
            images_by_tf[tf] = download_bytes(
                client=client, bucket=settings.gcs_bucket, blob_name=paths.charts_blob(tf)
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"missing chart image for {tf}: {e}")

    liquidation_heatmap_png: bytes | None = None
    liquidation_heatmap_obs: LiquidationHeatmapObservations | None = None
    if body.include_liquidation_heatmap:
        try:
            liquidation_heatmap_png = download_bytes(
                client=client,
                bucket=settings.gcs_bucket,
                blob_name=paths.liquidation_heatmap_blob(),
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"missing liquidation heatmap image: {e}")

    write_case_json(
        gcs_client=client,
        bucket=settings.gcs_bucket,
        paths=paths,
        name="request.json",
        obj={
            "case_id": case_id,
            "symbol": body.symbol,
            "timestamp_utc": body.timestamp_utc.isoformat(),
            "timeframes_order": body.timeframes_order,
            "vision_provider": body.vision_provider or settings.vision_provider,
            "vision_model_pass1": body.vision_model_pass1,
            "vision_model_pass2": body.vision_model_pass2,
            "include_liquidation_heatmap": body.include_liquidation_heatmap,
            "liquidation_heatmap_time_horizon_hours": liquidation_heatmap_horizon_hours,
        },
    )
    _write_generation_status(
        client=client,
        settings=settings,
        paths=paths,
        state="running",
        detail="Analyze pipeline started",
    )

    await _broker.publish("uploaded", case_id, {"ok": True})

    p1, raw1 = await provider.pass1(
        symbol=body.symbol,
        timestamp_utc=body.timestamp_utc,
        images_by_tf=images_by_tf,
    )
    write_case_json(
        gcs_client=client,
        bucket=settings.gcs_bucket,
        paths=paths,
        name="llm_raw_pass1.json",
        obj=raw1,
    )
    write_case_json(
        gcs_client=client,
        bucket=settings.gcs_bucket,
        paths=paths,
        name="pass1_observations.json",
        obj=json.loads(p1.model_dump_json()),
    )

    if liquidation_heatmap_png is not None:
        liquidation_heatmap_obs, liquidation_heatmap_raw = await provider.pass_liquidation_heatmap(
            symbol=body.symbol,
            timestamp_utc=body.timestamp_utc,
            liquidation_heatmap_png=liquidation_heatmap_png,
            time_horizon_hours=liquidation_heatmap_horizon_hours,
        )
        write_case_json(
            gcs_client=client,
            bucket=settings.gcs_bucket,
            paths=paths,
            name="llm_raw_liquidation_heatmap.json",
            obj=liquidation_heatmap_raw,
        )
        write_case_json(
            gcs_client=client,
            bucket=settings.gcs_bucket,
            paths=paths,
            name="liquidation_heatmap_observations.json",
            obj=json.loads(liquidation_heatmap_obs.model_dump_json()),
        )

    p2, raw2 = await provider.pass2(
        symbol=body.symbol,
        timestamp_utc=body.timestamp_utc,
        images_by_tf=images_by_tf,
        pass1=p1,
        liquidation_heatmap=liquidation_heatmap_obs,
    )
    write_case_json(
        gcs_client=client,
        bucket=settings.gcs_bucket,
        paths=paths,
        name="llm_raw_pass2.json",
        obj=raw2,
    )

    try:
        caps = Caps(max_leverage=settings.max_leverage, max_margin_percent=settings.max_margin_percent)
        validated = _validate_caps(p2, caps)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"proposal validation failed: {e}")

    write_case_json(
        gcs_client=client,
        bucket=settings.gcs_bucket,
        paths=paths,
        name="proposal_validated.json",
        obj=json.loads(validated.model_dump_json()),
    )
    _write_generation_status(
        client=client,
        settings=settings,
        paths=paths,
        state="completed",
        detail="Proposal validated and ready",
    )

    await _broker.publish(
        "analyzed",
        case_id,
        {"long_short_none": validated.long_short_none, "confidence": validated.confidence},
    )

    return validated


@app.post("/v1/cases/{case_id}/label")
async def label_case(case_id: str, body: dict[str, Any] = Body(...)) -> JSONResponse:
    settings = _settings()
    client = get_storage_client()
    paths = build_case_paths(cases_prefix=settings.cases_prefix, case_id=case_id)

    write_case_json(
        gcs_client=client,
        bucket=settings.gcs_bucket,
        paths=paths,
        name="label.json",
        obj=body,
    )

    await _broker.publish("labeled", case_id, {})
    return JSONResponse(content={"ok": True})


