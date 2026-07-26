"""
Indicator engine: OHLCV -> TimeframeSnapshot / IndicatorSnapshot.

Numeric replacement for vision Pass-1 (ADR-0002). Uses the same vocabulary as
the vision rulebook (regime / trend_dir / vwap_state / macd_state / key_levels)
so downstream prompts and case artifacts keep their shape.

Only CLOSED candles may be passed in — the provider is responsible for
dropping the currently-forming candle.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..models import OHLCV, IndicatorSnapshot, TimeframeSnapshot
from . import ta

EMA_FAST = 20
EMA_SLOW = 50
MIN_CANDLES = 60  # below this, snapshot fields stay UNKNOWN


def build_timeframe_snapshot(timeframe: str, candles: list[OHLCV]) -> TimeframeSnapshot:
    snap = TimeframeSnapshot(timeframe=timeframe)
    if len(candles) < MIN_CANDLES:
        snap.notes = f"insufficient candles ({len(candles)} < {MIN_CANDLES})"
        return snap

    closes = [c.close for c in candles]
    last_close = closes[-1]
    snap.last_close = last_close

    # --- volatility ---------------------------------------------------------
    atr_series = ta.atr(candles)
    last_atr = atr_series[-1]
    snap.atr = round(last_atr, 8) if last_atr else None

    # --- trend --------------------------------------------------------------
    ema_fast_series = ta.ema(closes, EMA_FAST)
    ema_slow_series = ta.ema(closes, EMA_SLOW)
    ef, es = ema_fast_series[-1], ema_slow_series[-1]
    snap.ema_fast = round(ef, 8) if ef is not None else None
    snap.ema_slow = round(es, 8) if es is not None else None

    structure = ta.trend_structure(candles)
    if ef is not None and es is not None:
        ema_dir = "UP" if ef > es else "DOWN" if ef < es else "NEUTRAL"
        if structure == ema_dir and structure in ("UP", "DOWN"):
            snap.trend_dir = structure  # structure + EMA stack agree
        elif structure == "NEUTRAL":
            snap.trend_dir = "NEUTRAL"
        else:
            snap.trend_dir = "NEUTRAL"  # disagreement -> no clear trend
    else:
        snap.trend_dir = structure  # fall back to structure only

    # --- VWAP ---------------------------------------------------------------
    vwap_series = ta.daily_vwap(candles)
    vwap = vwap_series[-1]
    if vwap is not None and last_atr:
        dist_atr = (last_close - vwap) / last_atr
        snap.vwap_distance_atr = round(dist_atr, 3)
        if abs(dist_atr) <= 0.25:
            snap.vwap_state = "AROUND"
        elif dist_atr > 0:
            snap.vwap_state = "ABOVE"
        else:
            snap.vwap_state = "BELOW"

    # --- MACD ---------------------------------------------------------------
    macd_line, signal_line, hist = ta.macd(closes)
    m, s = macd_line[-1], signal_line[-1]
    m_prev, s_prev = macd_line[-2], signal_line[-2]
    if m is not None and s is not None and m_prev is not None and s_prev is not None:
        crossed_up = m_prev <= s_prev and m > s
        crossed_down = m_prev >= s_prev and m < s
        h = hist[-1] or 0.0
        flat_band = 0.05 * (last_atr or 1.0)
        if crossed_up:
            snap.macd_state = "CROSSING_UP"
        elif crossed_down:
            snap.macd_state = "CROSSING_DOWN"
        elif abs(h) < flat_band:
            snap.macd_state = "FLAT"
        elif m > s:
            snap.macd_state = "BULLISH"
        else:
            snap.macd_state = "BEARISH"

    # --- RSI ----------------------------------------------------------------
    rsi_series = ta.rsi(closes)
    r = rsi_series[-1]
    snap.rsi = round(r, 2) if r is not None else None

    # --- key levels ---------------------------------------------------------
    snap.key_levels = ta.key_levels(candles)

    # --- regime -------------------------------------------------------------
    snap.regime = _classify_regime(candles, snap, closes, last_atr)

    snap.notes = _notes(snap)
    return snap


def _classify_regime(
    candles: list[OHLCV],
    snap: TimeframeSnapshot,
    closes: list[float],
    last_atr: float | None,
) -> str:
    bw_series = ta.bollinger_bandwidth(closes)
    bw = bw_series[-1]
    bw_valid = [v for v in bw_series if v is not None]
    bw_median = sorted(bw_valid)[len(bw_valid) // 2] if bw_valid else None

    # Breakout: last close pushed beyond the nearest key level by > 0.5 ATR
    # with expanding bandwidth.
    if last_atr and snap.key_levels and bw is not None and bw_median:
        nearest = snap.key_levels[0]
        pushed = abs(closes[-1] - nearest) > 0.5 * last_atr
        expanding = bw > 1.25 * bw_median
        if pushed and expanding and snap.trend_dir in ("UP", "DOWN"):
            return "BREAKOUT"

    if snap.trend_dir in ("UP", "DOWN"):
        return "TREND"

    # Range vs chop: contracting/normal bandwidth with neutral structure is a
    # range; erratic overlap (very low bandwidth AND flat MACD) reads as chop.
    if bw is not None and bw_median is not None:
        if bw < 0.75 * bw_median and snap.macd_state in ("FLAT", "UNKNOWN"):
            return "CHOP"
        return "RANGE"
    return "UNKNOWN"


def _notes(s: TimeframeSnapshot) -> str:
    parts: list[str] = []
    parts.append(f"{s.timeframe}: {s.regime} {s.trend_dir}")
    if s.vwap_state != "UNKNOWN":
        stretched = (
            " (stretched)" if s.vwap_distance_atr and abs(s.vwap_distance_atr) > 2 else ""
        )
        parts.append(f"price {s.vwap_state} VWAP {s.vwap_distance_atr} ATRs{stretched}")
    if s.macd_state != "UNKNOWN":
        parts.append(f"MACD {s.macd_state}")
    if s.rsi is not None:
        parts.append(f"RSI {s.rsi}")
    if s.key_levels:
        parts.append(f"levels near: {s.key_levels[:3]}")
    return "; ".join(parts)


def build_snapshot(
    symbol: str,
    candles_by_tf: dict[str, list[OHLCV]],
    ticker: dict[str, Any] | None = None,
) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        symbol=symbol,
        timestamp_utc=datetime.now(timezone.utc),
        timeframes=[
            build_timeframe_snapshot(tf, candles) for tf, candles in candles_by_tf.items()
        ],
        ticker=ticker or {},
    )
