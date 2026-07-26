from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

Timeframe = Literal["4h", "1h", "30m", "15m", "5m", "1m"]

# Bybit v5 kline interval strings
TIMEFRAME_TO_INTERVAL: dict[str, str] = {
    "4h": "240",
    "1h": "60",
    "30m": "30",
    "15m": "15",
    "5m": "5",
    "1m": "1",
}


class OHLCV(BaseModel):
    """One CLOSED candle. Open/streaming candles must never enter the engine."""

    start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover: float = 0.0


# ---------------------------------------------------------------------------
# Indicator snapshot (numeric analog of vision pass1_observations)
# ---------------------------------------------------------------------------

Regime = Literal["TREND", "RANGE", "BREAKOUT", "CHOP", "UNKNOWN"]
TrendDir = Literal["UP", "DOWN", "NEUTRAL", "UNKNOWN"]
VwapState = Literal["ABOVE", "BELOW", "AROUND", "UNKNOWN"]
MacdState = Literal["BULLISH", "BEARISH", "CROSSING_UP", "CROSSING_DOWN", "FLAT", "UNKNOWN"]


class TimeframeSnapshot(BaseModel):
    timeframe: str
    regime: Regime = "UNKNOWN"
    trend_dir: TrendDir = "UNKNOWN"
    vwap_state: VwapState = "UNKNOWN"
    vwap_distance_atr: float | None = None  # |price - vwap| in ATRs ("stretched" gauge)
    macd_state: MacdState = "UNKNOWN"
    key_levels: list[float] = Field(default_factory=list)
    atr: float | None = None
    last_close: float | None = None
    ema_fast: float | None = None
    ema_slow: float | None = None
    rsi: float | None = None
    notes: str = ""


class IndicatorSnapshot(BaseModel):
    """Full multi-timeframe snapshot for one symbol at one moment."""

    symbol: str
    timestamp_utc: datetime
    timeframes: list[TimeframeSnapshot]
    ticker: dict[str, Any] = Field(default_factory=dict)

    def by_tf(self, tf: str) -> TimeframeSnapshot | None:
        for s in self.timeframes:
            if s.timeframe == tf:
                return s
        return None


# ---------------------------------------------------------------------------
# Governor
# ---------------------------------------------------------------------------

GovernorAction = Literal["APPROVE", "RESIZE", "REJECT"]

RejectReason = Literal[
    "loop_disabled",
    "breaker_daily",
    "breaker_weekly",
    "too_many_positions",
    "aggregate_risk_cap",
    "margin_cap",
    "cooldown",
    "low_confidence",
    "no_stop",
    "invalid_proposal",
    "leverage_cap",
    "risk_cap",
]


class PortfolioState(BaseModel):
    """Inputs the governor needs; assembled by the loop from bybit_trading."""

    equity_usdt: float
    total_margin_used_usdt: float = 0.0
    open_positions: list[dict[str, Any]] = Field(default_factory=list)
    open_orders: list[dict[str, Any]] = Field(default_factory=list)  # resting conductor entry orders
    orders_error: str | None = None  # non-fatal, but must be surfaced in tick output
    open_risk_usdt: float = 0.0  # positions qty*|entry-stop| + resting orders qty*|price-stop|
    realized_pnl_today_usdt: float = 0.0
    realized_pnl_week_usdt: float = 0.0
    symbols_on_cooldown: list[str] = Field(default_factory=list)


class GovernorDecision(BaseModel):
    action: GovernorAction
    qty: float | None = None
    leverage: float | None = None
    reasons: list[str] = Field(default_factory=list)
    reject_reason: RejectReason | None = None
    audit: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------

class TickResult(BaseModel):
    started_at: datetime
    finished_at: datetime
    execution_mode: str
    candidates_scanned: int = 0
    passed_gate: int = 0
    proposals: int = 0
    approved: int = 0
    executed: int = 0
    positions_managed: int = 0
    orders_reconciled: int = 0
    orders_cancelled: int = 0
    errors: list[str] = Field(default_factory=list)
    detail: list[dict[str, Any]] = Field(default_factory=list)
