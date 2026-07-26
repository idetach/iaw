from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from conductor.app.indicators import ta
from conductor.app.indicators.engine import build_timeframe_snapshot
from conductor.app.models import OHLCV


def make_candles(closes: list[float], start: datetime | None = None, spread: float = 0.5) -> list[OHLCV]:
    start = start or datetime(2026, 7, 1, tzinfo=timezone.utc)
    out = []
    prev = closes[0]
    for i, c in enumerate(closes):
        o = prev
        h = max(o, c) + spread
        l = min(o, c) - spread
        out.append(
            OHLCV(
                start=start + timedelta(hours=i),
                open=o, high=h, low=l, close=c,
                volume=100.0, turnover=100.0 * c,
            )
        )
        prev = c
    return out


# ---------------------------------------------------------------------------
# sma / ema
# ---------------------------------------------------------------------------

def test_sma_known_values():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    out = ta.sma(vals, 3)
    assert out[:2] == [None, None]
    assert out[2] == pytest.approx(2.0)
    assert out[4] == pytest.approx(4.0)


def test_ema_seeds_with_sma_and_converges():
    vals = [10.0] * 50
    out = ta.ema(vals, 10)
    assert out[8] is None
    assert out[9] == pytest.approx(10.0)
    assert out[-1] == pytest.approx(10.0)


def test_ema_rises_with_uptrend():
    vals = [float(i) for i in range(1, 61)]
    out = ta.ema(vals, 10)
    assert out[-1] > out[-10] > out[-20]


# ---------------------------------------------------------------------------
# macd / rsi
# ---------------------------------------------------------------------------

def test_macd_positive_in_uptrend_negative_in_downtrend():
    up = [float(i) for i in range(1, 101)]
    m_up, _, _ = ta.macd(up)
    assert m_up[-1] > 0
    down = [float(i) for i in range(100, 0, -1)]
    m_down, _, _ = ta.macd(down)
    assert m_down[-1] < 0


def test_rsi_bounds_and_direction():
    up = [float(i) for i in range(1, 41)]
    r = ta.rsi(up)
    assert r[-1] == pytest.approx(100.0)
    down = [float(i) for i in range(40, 0, -1)]
    r2 = ta.rsi(down)
    assert r2[-1] == pytest.approx(0.0)
    flatish = [10.0, 11.0] * 20
    r3 = ta.rsi(flatish)
    assert 0.0 < r3[-1] < 100.0


# ---------------------------------------------------------------------------
# atr / vwap
# ---------------------------------------------------------------------------

def test_atr_reflects_range_size():
    calm = make_candles([100.0] * 40, spread=0.5)
    wild = make_candles([100.0] * 40, spread=5.0)
    atr_calm = ta.atr(calm)[-1]
    atr_wild = ta.atr(wild)[-1]
    assert atr_calm is not None and atr_wild is not None
    assert atr_wild > atr_calm * 5


def test_daily_vwap_resets_at_utc_day_boundary():
    day1 = make_candles([10.0] * 24, start=datetime(2026, 7, 1, tzinfo=timezone.utc))
    day2 = make_candles([20.0] * 24, start=datetime(2026, 7, 2, tzinfo=timezone.utc))
    vwap = ta.daily_vwap(day1 + day2)
    # After reset, day-2 VWAP should be near 20, unpolluted by day-1's 10s.
    assert vwap[-1] == pytest.approx(20.0, abs=1.0)
    assert vwap[23] == pytest.approx(10.0, abs=1.0)


# ---------------------------------------------------------------------------
# structure
# ---------------------------------------------------------------------------

def test_swing_points_find_obvious_pivot():
    closes = [10, 11, 12, 13, 20, 13, 12, 11, 10, 9, 8, 7, 6, 5, 6, 7, 8]
    candles = make_candles([float(c) for c in closes], spread=0.1)
    highs, lows = ta.swing_points(candles)
    assert any(abs(i - 4) <= 1 for i in highs)  # peak at index 4
    assert any(abs(i - 13) <= 1 for i in lows)  # trough at index 13


def test_trend_structure_up_down():
    up = make_candles([float(i) + (3 if i % 6 == 0 else 0) for i in range(1, 60)], spread=0.2)
    assert ta.trend_structure(up) in ("UP", "NEUTRAL")
    down = make_candles([60.0 - i + (3 if i % 6 == 0 else 0) for i in range(1, 60)], spread=0.2)
    assert ta.trend_structure(down) in ("DOWN", "NEUTRAL")


def test_key_levels_sorted_by_proximity():
    closes = [10, 11, 12, 13, 20, 13, 12, 11, 10, 9, 8, 7, 6, 5, 6, 7, 8] * 4
    candles = make_candles([float(c) for c in closes], spread=0.1)
    levels = ta.key_levels(candles)
    if len(levels) >= 2:
        last = candles[-1].close
        assert abs(levels[0] - last) <= abs(levels[1] - last)


# ---------------------------------------------------------------------------
# engine
# ---------------------------------------------------------------------------

def test_snapshot_insufficient_data_stays_unknown():
    snap = build_timeframe_snapshot("1h", make_candles([10.0] * 10))
    assert snap.regime == "UNKNOWN"
    assert "insufficient" in snap.notes


def test_snapshot_uptrend_is_classified():
    closes = []
    v = 100.0
    for i in range(120):
        v += 1.0 if i % 5 else -1.5  # rising with pullbacks
        closes.append(v)
    snap = build_timeframe_snapshot("1h", make_candles(closes, spread=0.3))
    assert snap.last_close is not None
    assert snap.atr is not None
    assert snap.trend_dir in ("UP", "NEUTRAL")
    assert snap.regime in ("TREND", "RANGE", "BREAKOUT", "CHOP")
    assert snap.notes
