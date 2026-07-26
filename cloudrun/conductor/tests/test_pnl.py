from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from conductor.app import pnl

NOW = datetime(2026, 7, 26, 12, 0, 0, tzinfo=timezone.utc)


def rec(symbol: str, pnl_value: float, hours_ago: float) -> dict:
    ts = NOW - timedelta(hours=hours_ago)
    return {
        "symbol": symbol,
        "closedPnl": str(pnl_value),
        "updatedTime": str(int(ts.timestamp() * 1000)),
        "side": "Sell",
    }


def test_aggregate_today_vs_week():
    records = [
        rec("BTCUSDT", -100.0, hours_ago=2),    # today (after 00:00 UTC)
        rec("ETHUSDT", 50.0, hours_ago=6),      # today
        rec("SOLUSDT", -200.0, hours_ago=30),   # yesterday -> week only
        rec("DOGEUSDT", 25.0, hours_ago=24 * 8),  # 8 days ago -> excluded
    ]
    out = pnl.aggregate(records, now=NOW, cooldown_hours=4)
    assert out["realized_today"] == pytest.approx(-50.0)
    assert out["realized_week"] == pytest.approx(-250.0)


def test_cooldown_symbols_window():
    records = [
        rec("BTCUSDT", -10.0, hours_ago=2),   # within 4h cooldown
        rec("ETHUSDT", 5.0, hours_ago=5),     # outside
    ]
    out = pnl.aggregate(records, now=NOW, cooldown_hours=4)
    assert out["cooldown_symbols"] == ["BTCUSDT"]


def test_aggregate_ignores_malformed_records():
    records = [
        {"symbol": "X", "closedPnl": "not-a-number", "updatedTime": "bad"},
        rec("BTCUSDT", 10.0, hours_ago=1),
    ]
    out = pnl.aggregate(records, now=NOW)
    assert out["realized_today"] == pytest.approx(10.0)


def test_recent_outcomes_summary_newest_first_and_per_symbol():
    records = [
        rec("BTCUSDT", -12.4, hours_ago=10),
        rec("BTCUSDT", 33.1, hours_ago=1),
        rec("ETHUSDT", 99.0, hours_ago=2),
    ]
    text = pnl.recent_outcomes_summary(records, "BTCUSDT")
    assert "ETHUSDT" not in text
    assert text.index("+33.10") < text.index("-12.40")  # newest first


def test_recent_outcomes_summary_empty():
    assert pnl.recent_outcomes_summary([], "BTCUSDT") == ""
