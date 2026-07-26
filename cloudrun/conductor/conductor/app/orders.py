"""
Resting-order reconciliation (order lifecycle, position-lifecycle-spec).

A resting limit order is a live claim on future exposure whose thesis ages:
the trend can flip before price ever reaches the limit. Bybit has no native
good-till-date, so the conductor simulates it — every tick each *conductor*
order (orderLinkId prefix "conductor-") is re-checked and cancelled when:

  1. TTL expiry      — older than ORDER_TTL_MINUTES (entry window passed)
  2. thesis flip     — reconcile-TF trend structure now points against it
  3. price drift     — price ran > ORDER_MAX_DRIFT_ATR ATRs away from the
                       limit (the pullback never came; order is stale)

Deterministic code, no LLM. Cancelling only ever reduces exposure; a still-
valid setup will simply be re-proposed by a later tick at a fresh level.
Manual orders (no conductor- prefix) are never touched.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import TimeframeSnapshot

ORDER_LINK_PREFIX = "conductor-"


def is_conductor_order(order: dict[str, Any]) -> bool:
    return str(order.get("orderLinkId", "")).startswith(ORDER_LINK_PREFIX)


def _f(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "", "0") else (0.0 if v == "0" else None)
    except (TypeError, ValueError):
        return None


def order_age_minutes(order: dict[str, Any], now: datetime | None = None) -> float | None:
    raw = order.get("createdTime") or order.get("updatedTime")
    try:
        created = datetime.fromtimestamp(int(raw) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError):
        return None
    now = now or datetime.now(timezone.utc)
    return (now - created).total_seconds() / 60.0


def order_risk_usdt(order: dict[str, Any]) -> float:
    """Risk this order would carry if filled: qty * |price - stopLoss|."""
    qty = _f(order.get("qty")) or 0.0
    price = _f(order.get("price")) or 0.0
    stop = _f(order.get("stopLoss"))
    if not qty or not price or stop is None or stop <= 0:
        return 0.0
    return abs(price - stop) * qty


def assess_order(
    order: dict[str, Any],
    *,
    ttl_minutes: float,
    max_drift_atr: float,
    tf_snapshot: TimeframeSnapshot | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Decide KEEP or CANCEL for one resting conductor order.
    Returns {"action": "KEEP"|"CANCEL", "reason": str}.
    """
    side = order.get("side")  # Buy = pending long entry, Sell = pending short

    # 1) TTL expiry — the entry window has passed.
    age = order_age_minutes(order, now)
    if age is not None and age > ttl_minutes:
        return {
            "action": "CANCEL",
            "reason": f"entry window expired ({age:.0f}m > {ttl_minutes:.0f}m TTL)",
        }

    if tf_snapshot is not None:
        # 2) Thesis flip — structure now trends against the pending entry.
        against = "DOWN" if side == "Buy" else "UP"
        if tf_snapshot.trend_dir == against and tf_snapshot.regime in ("TREND", "BREAKOUT"):
            return {
                "action": "CANCEL",
                "reason": f"thesis invalidated: {tf_snapshot.timeframe} structure flipped {against}",
            }

        # 3) Price drift — price ran away from the limit; pullback never came.
        price = _f(order.get("price"))
        if (
            price is not None
            and tf_snapshot.last_close is not None
            and tf_snapshot.atr
            and tf_snapshot.atr > 0
        ):
            drift = abs(tf_snapshot.last_close - price) / tf_snapshot.atr
            if drift > max_drift_atr:
                return {
                    "action": "CANCEL",
                    "reason": (
                        f"stale: price {drift:.1f} ATR from limit "
                        f"(cap {max_drift_atr:.1f})"
                    ),
                }

    return {"action": "KEEP", "reason": f"still valid (age {age:.0f}m)" if age is not None else "still valid"}
