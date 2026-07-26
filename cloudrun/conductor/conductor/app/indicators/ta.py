"""
Pure technical-analysis functions over CLOSED candles.

No external TA dependency: every function is a small, unit-testable pure
function over lists of floats / OHLCV. Candles are expected OLDEST-FIRST.
See vault/01-architecture/autonomous-data-path.md.
"""
from __future__ import annotations

import math
from datetime import timezone

from ..models import OHLCV


# ---------------------------------------------------------------------------
# Moving averages / oscillators
# ---------------------------------------------------------------------------

def sma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    window_sum = sum(values[:period])
    out[period - 1] = window_sum / period
    for i in range(period, len(values)):
        window_sum += values[i] - values[i - period]
        out[i] = window_sum / period
    return out


def ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    k = 2.0 / (period + 1.0)
    prev = sum(values[:period]) / period  # seed with SMA
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1.0 - k)
        out[i] = prev
    return out


def macd(
    values: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Returns (macd_line, signal_line, histogram)."""
    ema_fast = ema(values, fast)
    ema_slow = ema(values, slow)
    macd_line: list[float | None] = [
        (f - s) if (f is not None and s is not None) else None
        for f, s in zip(ema_fast, ema_slow)
    ]
    valid = [(i, v) for i, v in enumerate(macd_line) if v is not None]
    signal_line: list[float | None] = [None] * len(values)
    if len(valid) >= signal:
        idxs = [i for i, _ in valid]
        vals = [v for _, v in valid]
        sig = ema(vals, signal)
        for j, i in enumerate(idxs):
            signal_line[i] = sig[j]
    hist: list[float | None] = [
        (m - s) if (m is not None and s is not None) else None
        for m, s in zip(macd_line, signal_line)
    ]
    return macd_line, signal_line, hist


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period + 1:
        return out
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        d = values[i] - values[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    avg_gain = gains / period
    avg_loss = losses / period
    out[period] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(period + 1, len(values)):
        d = values[i] - values[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(d, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-d, 0.0)) / period
        out[i] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


# ---------------------------------------------------------------------------
# Volatility
# ---------------------------------------------------------------------------

def atr(candles: list[OHLCV], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(candles)
    if len(candles) < period + 1:
        return out
    trs: list[float] = [0.0]
    for i in range(1, len(candles)):
        c, p = candles[i], candles[i - 1]
        tr = max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close))
        trs.append(tr)
    prev = sum(trs[1 : period + 1]) / period  # Wilder seed
    out[period] = prev
    for i in range(period + 1, len(candles)):
        prev = (prev * (period - 1) + trs[i]) / period
        out[i] = prev
    return out


# ---------------------------------------------------------------------------
# VWAP (anchored to UTC day)
# ---------------------------------------------------------------------------

def daily_vwap(candles: list[OHLCV]) -> list[float | None]:
    """VWAP anchored at each UTC day boundary, using typical price."""
    out: list[float | None] = [None] * len(candles)
    cum_pv = 0.0
    cum_vol = 0.0
    current_day = None
    for i, c in enumerate(candles):
        day = c.start.astimezone(timezone.utc).date()
        if day != current_day:
            current_day = day
            cum_pv = 0.0
            cum_vol = 0.0
        typical = (c.high + c.low + c.close) / 3.0
        cum_pv += typical * c.volume
        cum_vol += c.volume
        out[i] = (cum_pv / cum_vol) if cum_vol > 0 else None
    return out


# ---------------------------------------------------------------------------
# Structure: swings and key levels
# ---------------------------------------------------------------------------

def swing_points(
    candles: list[OHLCV], left: int = 3, right: int = 3
) -> tuple[list[int], list[int]]:
    """Indexes of confirmed swing highs and swing lows (fractal pivots)."""
    highs: list[int] = []
    lows: list[int] = []
    for i in range(left, len(candles) - right):
        h = candles[i].high
        l = candles[i].low
        if all(h > candles[j].high for j in range(i - left, i)) and all(
            h >= candles[j].high for j in range(i + 1, i + right + 1)
        ):
            highs.append(i)
        if all(l < candles[j].low for j in range(i - left, i)) and all(
            l <= candles[j].low for j in range(i + 1, i + right + 1)
        ):
            lows.append(i)
    return highs, lows


def key_levels(
    candles: list[OHLCV],
    *,
    max_levels: int = 6,
    cluster_atr_mult: float = 0.5,
) -> list[float]:
    """
    Cluster swing highs/lows into deduplicated horizontal levels, nearest to
    current price first. Levels closer than cluster_atr_mult*ATR merge.
    """
    if not candles:
        return []
    highs_idx, lows_idx = swing_points(candles)
    prices = sorted(
        [candles[i].high for i in highs_idx] + [candles[i].low for i in lows_idx]
    )
    if not prices:
        return []
    atr_series = atr(candles)
    last_atr = next((v for v in reversed(atr_series) if v is not None), None)
    tol = (last_atr or (prices[-1] * 0.005)) * cluster_atr_mult

    clusters: list[list[float]] = []
    for p in prices:
        if clusters and p - clusters[-1][-1] <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    levels = [sum(c) / len(c) for c in clusters]

    last_close = candles[-1].close
    levels.sort(key=lambda lv: abs(lv - last_close))
    return [round(lv, 8) for lv in levels[:max_levels]]


def trend_structure(candles: list[OHLCV], left: int = 3, right: int = 3) -> str:
    """
    UP if last two swing highs and lows are both ascending,
    DOWN if both descending, else NEUTRAL.
    """
    highs_idx, lows_idx = swing_points(candles, left, right)
    if len(highs_idx) < 2 or len(lows_idx) < 2:
        return "NEUTRAL"
    h1, h2 = candles[highs_idx[-2]].high, candles[highs_idx[-1]].high
    l1, l2 = candles[lows_idx[-2]].low, candles[lows_idx[-1]].low
    if h2 > h1 and l2 > l1:
        return "UP"
    if h2 < h1 and l2 < l1:
        return "DOWN"
    return "NEUTRAL"


def bollinger_bandwidth(values: list[float], period: int = 20) -> list[float | None]:
    """(upper-lower)/middle — used as a squeeze/expansion gauge for regime."""
    out: list[float | None] = [None] * len(values)
    mids = sma(values, period)
    for i in range(period - 1, len(values)):
        mid = mids[i]
        if mid is None or mid == 0:
            continue
        window = values[i - period + 1 : i + 1]
        var = sum((v - mid) ** 2 for v in window) / period
        sd = math.sqrt(var)
        out[i] = (4.0 * sd) / mid  # (mid+2sd)-(mid-2sd) over mid
    return out
