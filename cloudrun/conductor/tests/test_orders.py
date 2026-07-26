from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from conductor.app import orders
from conductor.app.models import TimeframeSnapshot

NOW = datetime(2026, 7, 26, 16, 0, 0, tzinfo=timezone.utc)


def order(side="Buy", price="100", qty="1", stop="95", age_minutes=10.0, link="conductor-abc"):
    created = NOW - timedelta(minutes=age_minutes)
    return {
        "orderId": "oid1",
        "orderLinkId": link,
        "symbol": "SOLUSDT",
        "side": side,
        "price": price,
        "qty": qty,
        "stopLoss": stop,
        "createdTime": str(int(created.timestamp() * 1000)),
    }


def snap(trend="NEUTRAL", regime="RANGE", last_close=100.0, atr=2.0):
    return TimeframeSnapshot(
        timeframe="1h", trend_dir=trend, regime=regime, last_close=last_close, atr=atr
    )


def test_is_conductor_order_prefix():
    assert orders.is_conductor_order(order()) is True
    assert orders.is_conductor_order(order(link="manual-x")) is False
    assert orders.is_conductor_order({}) is False


def test_ttl_expiry_cancels():
    v = orders.assess_order(order(age_minutes=180), ttl_minutes=120, max_drift_atr=2.0, now=NOW)
    assert v["action"] == "CANCEL"
    assert "expired" in v["reason"]


def test_fresh_valid_order_kept():
    v = orders.assess_order(
        order(age_minutes=10), ttl_minutes=120, max_drift_atr=2.0, tf_snapshot=snap(), now=NOW
    )
    assert v["action"] == "KEEP"


def test_trend_flip_cancels_pending_long():
    v = orders.assess_order(
        order(side="Buy", age_minutes=10),
        ttl_minutes=120,
        max_drift_atr=2.0,
        tf_snapshot=snap(trend="DOWN", regime="TREND"),
        now=NOW,
    )
    assert v["action"] == "CANCEL"
    assert "flipped DOWN" in v["reason"]


def test_trend_flip_cancels_pending_short():
    v = orders.assess_order(
        order(side="Sell", age_minutes=10),
        ttl_minutes=120,
        max_drift_atr=2.0,
        tf_snapshot=snap(trend="UP", regime="TREND"),
        now=NOW,
    )
    assert v["action"] == "CANCEL"


def test_trend_against_but_range_not_cancelled():
    # NEUTRAL/RANGE against-side drift is not a confirmed flip
    v = orders.assess_order(
        order(side="Buy", age_minutes=10),
        ttl_minutes=120,
        max_drift_atr=2.0,
        tf_snapshot=snap(trend="DOWN", regime="RANGE"),
        now=NOW,
    )
    assert v["action"] == "KEEP"


def test_price_drift_cancels():
    # limit at 100, price at 106, ATR 2 -> 3 ATR drift > 2 cap
    v = orders.assess_order(
        order(age_minutes=10),
        ttl_minutes=120,
        max_drift_atr=2.0,
        tf_snapshot=snap(last_close=106.0, atr=2.0),
        now=NOW,
    )
    assert v["action"] == "CANCEL"
    assert "stale" in v["reason"]


def test_order_risk_usdt():
    assert orders.order_risk_usdt(order(price="100", qty="2", stop="95")) == pytest.approx(10.0)
    assert orders.order_risk_usdt(order(stop=None)) == 0.0
