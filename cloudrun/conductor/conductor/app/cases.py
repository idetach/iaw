"""
List / read persisted conductor cases from GCS (cases-auto prefix).

Blob layout (written by loop.py):
  {CASES_PREFIX}/{YYYY-MM-DD}/{tick_id}/_tick.json
  {CASES_PREFIX}/{YYYY-MM-DD}/{tick_id}/{SYMBOL}.json

case_id used by the API/frontend = "{date}/{tick_id}/{SYMBOL}" (path-shaped,
stable, sortable). Sync (def) routes: FastAPI runs them in its threadpool, so
GCS I/O does not block the event loop.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from .config import get_settings
from .gcs import _get_client

router = APIRouter(prefix="/v1/cases", tags=["cases"])
_log = logging.getLogger("conductor.cases")


def _derive_status(case: dict[str, Any]) -> str:
    """One terminal status word per case — mirrors the roadmap stations."""
    if case.get("error"):
        return "error"
    execution = case.get("execution")
    if execution is not None:
        return "executed" if execution.get("placed") else "exec_failed"
    gov = case.get("governor")
    if gov is not None:
        return "approved" if gov.get("action") in ("APPROVE", "RESIZE") else "gov_rejected"
    proposal = case.get("proposal")
    if proposal is not None:
        return "proposed" if proposal.get("long_short_none") in ("LONG", "SHORT") else "abstained"
    gate = case.get("gate")
    if gate is not None:
        return "gate_passed" if gate.get("plausible") else "gate_rejected"
    if case.get("snapshot") is not None:
        return "scanned"
    return "queued"


def _item_from_case(case_id: str, case: dict[str, Any]) -> dict[str, Any]:
    """Shape matches the manual pipeline's case-list items so the frontend can
    reuse the exact same rendering (symbol / direction / status / model)."""
    proposal = case.get("proposal") or {}
    direction = proposal.get("long_short_none")
    return {
        "case_id": case_id,
        "symbol": case.get("symbol"),
        "date": case_id.split("/", 1)[0],
        "timestamp_utc": case.get("timestamp_utc"),
        "direction": direction if direction in ("LONG", "SHORT") else None,
        "status": _derive_status(case),
        "executed": bool((case.get("execution") or {}).get("placed")),
        "model": case.get("source"),  # rendered in the small gray slot
        "tick_id": case.get("tick_id"),
        "execution_mode": case.get("execution_mode"),
    }


@router.get("")
def list_cases(
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    s = get_settings()
    if not s.gcs_bucket:
        return {"items": [], "count": 0, "note": "GCS_BUCKET not configured"}

    root = f"{s.cases_prefix.rstrip('/')}/"
    try:
        client = _get_client()
        names = [
            b.name
            for b in client.list_blobs(s.gcs_bucket, prefix=root)
            if b.name.endswith(".json") and not b.name.endswith("_tick.json")
        ]
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GCS list failed: {exc}")

    # {prefix}/{date}/{tick_id}/{SYMBOL}.json — name sorts newest-last; reverse.
    names.sort(reverse=True)
    page = names[offset : offset + limit]

    items: list[dict[str, Any]] = []
    bucket = client.bucket(s.gcs_bucket)
    for name in page:
        case_id = name[len(root) : -len(".json")]
        try:
            case = json.loads(bucket.blob(name).download_as_bytes())
            items.append(_item_from_case(case_id, case))
        except Exception as exc:
            _log.warning("failed to read case %s: %s", name, exc)
            items.append(
                {"case_id": case_id, "symbol": case_id.rsplit("/", 1)[-1], "status": "unreadable"}
            )

    return {
        "items": items,
        "count": len(items),
        "total": len(names),
        "hasMore": offset + limit < len(names),
    }


@router.get("/{date}/{tick_id}/{symbol}")
def get_case(date: str, tick_id: str, symbol: str) -> dict[str, Any]:
    s = get_settings()
    if not s.gcs_bucket:
        raise HTTPException(status_code=404, detail="GCS_BUCKET not configured")
    name = f"{s.cases_prefix.rstrip('/')}/{date}/{tick_id}/{symbol}.json"
    try:
        client = _get_client()
        blob = client.bucket(s.gcs_bucket).blob(name)
        if not blob.exists(client):
            raise HTTPException(status_code=404, detail=f"case not found: {name}")
        return json.loads(blob.download_as_bytes())
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GCS read failed: {exc}")
