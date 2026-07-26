"""
Position Lifecycle Manager (position-lifecycle-spec).

Runs on the Fable cadence. Bybit positions are the source of truth; this module
reconciles them against indicator snapshots and applies monotonic risk
reduction (break-even move, trailing). Stops are NEVER widened.

Scaffold status: decision logic implemented; order-modification calls are
routed through bybit_trading and are no-ops in shadow mode.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from .config import Settings
from .models import IndicatorSnapshot

_log = logging.getLogger("conductor.lifecycle")

LifecycleAction = Literal[
    "HOLD",
    "MOVE_STOP_BREAKEVEN",
    "TRAIL_STOP",
    "EXIT_INVALIDATED",
    "EXIT_TIME",
    "ESCALATE_OPUS",
]


def assess_position(
    *,
    settings: Settings,
    position: dict[str, Any],
    snapshot: IndicatorSnapshot,
    proposal: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Decide the next lifecycle action for one open position.
    Returns {"action": LifecycleAction, "new_stop": float|None, "reason": str}.
    """
    side = position.get("side")  # "Buy" | "Sell"
    entry = _f(position.get("avgPrice"))
    stop = _f(position.get("stopLoss"))
    mark = _f(position.get("markPrice")) or _f(position.get("lastPrice"))

    if side not in ("Buy", "Sell") or entry is None or mark is None:
        return _res("HOLD", None, "position fields incomplete; reconcile next tick")

    # A position must always have a stop. If missing, that is an incident:
    # re-arm it immediately at the proposal stop (or exit if unavailable).
    if stop is None:
        proposal_stop = _f((proposal or {}).get("stop_loss"))
        if proposal_stop is not None:
            return _res("TRAIL_STOP", proposal_stop, "re-arming missing stop (incident)")
        return _res("EXIT_INVALIDATED", None, "no stop and no proposal stop — exit")

    r = abs(entry - stop)
    if r <= 0:
        return _res("HOLD", None, "zero R; skip")

    in_profit_r = ((mark - entry) / r) if side == "Buy" else ((entry - mark) / r)

    # 1) Invalidation: entry-TF structure flipped against the position.
    entry_tf = _entry_timeframe(proposal)
    tf_snap = snapshot.by_tf(entry_tf)
    if tf_snap is not None:
        against = "DOWN" if side == "Buy" else "UP"
        if tf_snap.trend_dir == against and tf_snap.regime in ("TREND", "BREAKOUT"):
            return _res("EXIT_INVALIDATED", None, f"{entry_tf} structure flipped {against}")
        if tf_snap.regime == "CHOP" and in_profit_r < 0:
            return _res("ESCALATE_OPUS", None, "thesis weakening in chop while underwater")

    # 2) Break-even at +1R (monotonic; only if stop not already at/past entry).
    if in_profit_r >= 1.0 and _stop_behind_entry(side, stop, entry):
        return _res("MOVE_STOP_BREAKEVEN", entry, "reached +1R; protect at break-even")

    # 3) Trail behind structure/ATR once past +1.5R. Never widen.
    if in_profit_r >= 1.5 and tf_snap is not None and tf_snap.atr:
        trail = mark - 1.5 * tf_snap.atr if side == "Buy" else mark + 1.5 * tf_snap.atr
        if _tightens(side, trail, stop):
            return _res("TRAIL_STOP", round(trail, 8), "ATR trail past +1.5R")

    # 4) Time-based exit per proposal exit window.
    if _past_exit_window(proposal, snapshot) and in_profit_r < 0.5:
        return _res("EXIT_TIME", None, "past exit window without progress")

    return _res("HOLD", None, f"thesis intact ({in_profit_r:+.2f}R)")


def _res(action: LifecycleAction, new_stop: float | None, reason: str) -> dict[str, Any]:
    out = {"action": action, "new_stop": new_stop, "reason": reason}
    _log.info("lifecycle: %s", out)
    return out


def _entry_timeframe(proposal: dict[str, Any] | None) -> str:
    duration = (proposal or {}).get("position_duration") or "DAY"
    return {"HOUR": "15m", "DAY": "1h", "SWING": "4h"}.get(duration, "1h")


def _stop_behind_entry(side: str, stop: float, entry: float) -> bool:
    return stop < entry if side == "Buy" else stop > entry


def _tightens(side: str, new_stop: float, old_stop: float) -> bool:
    """True only if the new stop reduces risk (monotonic tightening)."""
    return new_stop > old_stop if side == "Buy" else new_stop < old_stop


def _past_exit_window(proposal: dict[str, Any] | None, snapshot: IndicatorSnapshot) -> bool:
    from datetime import datetime

    raw = (proposal or {}).get("exit_time_to")
    if not raw:
        return False
    try:
        exit_to = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    return snapshot.timestamp_utc > exit_to


def _f(v: Any) -> float | None:
    try:
        f = float(v)
        return f if f != 0 else None  # Bybit uses "0" for unset SL
    except (TypeError, ValueError):
        return None
