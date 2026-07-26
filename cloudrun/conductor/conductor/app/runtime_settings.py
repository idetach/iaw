"""
Runtime-editable conductor settings (ADR-0006).

Two classes of settings:

- EDITABLE (behavioral): model routing, watchlist, candidate flow, order
  reconciliation, LLM memory, min confidence, shadow<->demo mode. Changed at
  runtime via PUT /v1/settings (web_app Settings -> Conductor Tick) and
  persisted best-effort to GCS so they survive restarts.

- GUARDED (risk caps): risk fraction, slots, aggregate risk, leverage/margin
  caps, breakers, cooldown. Env-only by design — changing risk limits must be
  a deliberate act (redeploy + experiment log/ADR), never a UI click. Exposed
  read-only for display.

`live` execution mode can NOT be set through this API (go-live checklist,
ADR-0003); only shadow <-> demo switching is allowed here.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from . import gcs
from .config import Settings, get_settings

router = APIRouter(prefix="/v1/settings", tags=["settings"])
_log = logging.getLogger("conductor.settings")

MODEL_OPTIONS = [
    "claude-fable-5",
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-haiku-4-5-20251001",
]

# field -> coercion type
EDITABLE_FIELDS: dict[str, type] = {
    "model_gate": str,
    "model_synthesis": str,
    "model_reflection": str,
    "execution_mode": str,  # shadow|demo only via API
    "watchlist": str,
    "radar_enabled": bool,
    "max_candidates_per_tick": int,
    "timeframes": str,
    "min_confidence": float,
    "include_recent_outcomes": bool,
    "order_ttl_minutes": float,
    "order_max_drift_atr": float,
    "order_reconcile_timeframe": str,
    "persist_cases": bool,
    "tick_interval_minutes": float,  # 0 = internal ticker off (use Cloud Scheduler)
}

GUARDED_FIELDS = [
    "risk_fraction",
    "max_concurrent_positions",
    "max_aggregate_open_risk",
    "max_total_margin_fraction",
    "max_leverage",
    "max_margin_percent",
    "symbol_cooldown_hours",
    "daily_loss_breaker_fraction",
    "weekly_loss_breaker_fraction",
]

_overrides: dict[str, Any] = {}


def _persist_path(s: Settings) -> str:
    return f"{s.cases_prefix.rstrip('/')}/_settings/runtime.json"


def _coerce(field: str, value: Any) -> Any:
    typ = EDITABLE_FIELDS[field]
    try:
        if typ is bool:
            if isinstance(value, bool):
                return value
            return str(value).lower() in ("1", "true", "yes", "on")
        return typ(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"invalid value for {field}: {value!r}")


def _validate(field: str, value: Any) -> Any:
    value = _coerce(field, value)
    if field == "execution_mode" and value not in ("shadow", "demo"):
        raise HTTPException(
            status_code=422,
            detail="execution_mode via API is limited to shadow|demo; live requires env + go-live checklist (ADR-0003)",
        )
    if field in ("model_gate", "model_synthesis", "model_reflection") and not value:
        raise HTTPException(status_code=422, detail=f"{field} must be non-empty")
    if field == "min_confidence" and not (0.0 <= value <= 1.0):
        raise HTTPException(status_code=422, detail="min_confidence must be in [0,1]")
    if field in ("order_ttl_minutes", "order_max_drift_atr", "max_candidates_per_tick") and value <= 0:
        raise HTTPException(status_code=422, detail=f"{field} must be > 0")
    if field == "tick_interval_minutes" and value != 0 and value < 1:
        raise HTTPException(status_code=422, detail="tick_interval_minutes must be 0 (off) or >= 1")
    return value


def apply_overrides(s: Settings, overrides: dict[str, Any]) -> list[str]:
    applied = []
    for field, value in overrides.items():
        if field in EDITABLE_FIELDS:
            setattr(s, field, value)
            applied.append(field)
    return applied


def load_persisted(s: Settings) -> None:
    """Best-effort: restore persisted overrides at startup."""
    if not s.gcs_bucket:
        return
    try:
        client = gcs._get_client()
        blob = client.bucket(s.gcs_bucket).blob(_persist_path(s))
        if not blob.exists(client):
            return
        data = json.loads(blob.download_as_bytes())
        valid = {k: _validate(k, v) for k, v in data.items() if k in EDITABLE_FIELDS}
        _overrides.update(valid)
        applied = apply_overrides(s, valid)
        _log.info("restored runtime settings: %s", applied)
    except Exception as exc:
        _log.warning("could not restore runtime settings: %s", exc)


@router.get("")
def get_runtime_settings() -> dict[str, Any]:
    s = get_settings()
    return {
        "editable": {f: getattr(s, f) for f in EDITABLE_FIELDS},
        "guarded": {f: getattr(s, f) for f in GUARDED_FIELDS},
        "overridden": sorted(_overrides.keys()),
        "model_options": MODEL_OPTIONS,
        "note": "guarded risk caps are env-only (ADR-0006); live mode requires env (ADR-0003)",
    }


@router.put("")
def update_runtime_settings(body: dict[str, Any]) -> dict[str, Any]:
    s = get_settings()
    unknown = [k for k in body if k not in EDITABLE_FIELDS]
    if unknown:
        guarded = [k for k in unknown if k in GUARDED_FIELDS]
        raise HTTPException(
            status_code=422,
            detail=(
                f"not editable at runtime: {unknown}"
                + (" (risk caps are env-only by design, see ADR-0006)" if guarded else "")
            ),
        )
    validated = {k: _validate(k, v) for k, v in body.items()}
    applied = apply_overrides(s, validated)
    _overrides.update(validated)
    if s.gcs_bucket:
        gcs.write_json(s.gcs_bucket, _persist_path(s), _overrides)
    _log.warning("runtime settings updated: %s", validated)
    return {"applied": applied, "editable": {f: getattr(s, f) for f in EDITABLE_FIELDS}}
