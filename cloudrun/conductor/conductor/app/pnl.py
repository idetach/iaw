"""
Closed-PnL aggregation for the risk governor (risk-governor-spec).

Pure functions over Bybit closed-pnl records:
  - realized PnL today (UTC day) and this week (rolling 7d) -> loss breakers
  - symbols closed within the cooldown window -> per-symbol cooldown
  - recent per-symbol outcome summaries -> optional LLM context
    (INCLUDE_RECENT_OUTCOMES, off by default)

Bybit record fields used: symbol, closedPnl, updatedTime (ms).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def _record_time(rec: dict[str, Any]) -> datetime | None:
    raw = rec.get("updatedTime") or rec.get("createdTime")
    try:
        return datetime.fromtimestamp(int(raw) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def _record_pnl(rec: dict[str, Any]) -> float:
    try:
        return float(rec.get("closedPnl") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def aggregate(
    records: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    cooldown_hours: float = 4.0,
) -> dict[str, Any]:
    """
    Returns:
      realized_today   — sum of closedPnl since UTC midnight
      realized_week    — sum of closedPnl over the last 7 days
      cooldown_symbols — symbols with a close within cooldown_hours
    """
    now = now or datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)
    cooldown_start = now - timedelta(hours=cooldown_hours)

    realized_today = 0.0
    realized_week = 0.0
    cooldown_symbols: set[str] = set()

    for rec in records:
        ts = _record_time(rec)
        if ts is None:
            continue
        pnl = _record_pnl(rec)
        if ts >= week_start:
            realized_week += pnl
        if ts >= day_start:
            realized_today += pnl
        if ts >= cooldown_start and rec.get("symbol"):
            cooldown_symbols.add(rec["symbol"])

    return {
        "realized_today": realized_today,
        "realized_week": realized_week,
        "cooldown_symbols": sorted(cooldown_symbols),
    }


def recent_outcomes_summary(
    records: list[dict[str, Any]],
    symbol: str,
    *,
    max_items: int = 5,
) -> str:
    """
    Compact per-symbol trade history for optional LLM context, newest first:
    'SHORT closed 2026-07-25T14:02Z pnl -12.40; LONG closed ... pnl +33.10'
    """
    items: list[tuple[datetime, str]] = []
    for rec in records:
        if rec.get("symbol") != symbol:
            continue
        ts = _record_time(rec)
        if ts is None:
            continue
        side = rec.get("side", "?")  # Bybit: side of the CLOSING order
        direction = "LONG" if side == "Sell" else "SHORT" if side == "Buy" else "?"
        pnl = _record_pnl(rec)
        items.append((ts, f"{direction} closed {ts.strftime('%Y-%m-%dT%H:%MZ')} pnl {pnl:+.2f}"))
    items.sort(key=lambda x: x[0], reverse=True)
    return "; ".join(text for _, text in items[:max_items])
