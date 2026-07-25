---
title: Autonomous Data Path (Indicator-Based, Cloud)
tags: [architecture, data]
updated: 2026-07-25
status: proposed
---

# Autonomous Data Path

**Decision (owner):** the autonomous loop must run **fully in the cloud** using
**direct market-data indicators via an API platform** — *no local machine and no
screenshot workers*. See [[ADR-0002-direct-market-data-indicators]].

This replaces the vision Pass-1 (which reads indicators off chart images) with a
numeric indicator engine that computes the same features from OHLCV. It is
cheaper (text-only LLM calls), reproducible, and cloud-native.

## Pipeline

```
market-data API  -->  OHLCV per timeframe  -->  indicator engine  -->  snapshot JSON  -->  LLM Pass-2
   (provider)          (4h,1h,30m,15m,5m,1m)     (numeric)            (mirrors Pass-1)     (Opus)
```

## Indicator snapshot (numeric replacement for vision Pass-1)

Per timeframe, compute the same vocabulary the vision rulebook already uses so the
downstream prompt/schema barely changes:

- **regime**: TREND / RANGE / BREAKOUT / CHOP (from swing structure + ATR/BB width)
- **trend_dir**: UP / DOWN / NEUTRAL (EMA stack + higher-highs/lower-lows test)
- **vwap_state**: ABOVE / BELOW / AROUND (+ distance in ATRs = "stretched")
- **macd_state**: BULLISH / BEARISH / CROSSING_UP / CROSSING_DOWN / FLAT
- **key_levels**: swing highs/lows, prior-day H/L, round numbers
- **volatility**: ATR, realized vol; used for sizing and stop distance
- **notes**: templated summary string (keeps the Pass-2 prompt format identical)

This snapshot is the numeric analog of `pass1_observations.json`, so
`case_graph_analytics` ingestion and the `TradeProposal` schema are unaffected.

## Provider abstraction

Wrap the data source behind a small interface so we can start simple and swap
later without touching the Conductor:

```python
class MarketDataProvider(Protocol):
    def klines(self, symbol: str, timeframe: str, limit: int) -> list[OHLCV]: ...
    def instrument(self, symbol: str) -> InstrumentFilters: ...  # tick/lot size
```

- **Phase 1 (now):** implement over **Bybit v5 klines** — already reachable via
  `bybit_trading`; zero new vendor, mainnet data even in demo mode.
- **Phase 2 (later):** add a dedicated market-data API platform (e.g. a candles/
  indicators vendor) behind the same interface if we need broader coverage,
  higher rate limits, or normalized cross-exchange data.

## Why not keep vision for the autonomous path

- Screenshots require a desktop session / always-on Mac — explicitly rejected.
- Vision calls are more expensive and less reproducible than numeric features.
- Numeric indicators are exactly what the vision model was *estimating* anyway.

Vision mode remains available for manual research where a human wants the model to
"look at the chart."

## Risks & mitigations

- **Indicator ≠ price action nuance.** Mitigate: keep multi-TF confluence + the
  abstain rubric; log disagreements for later study; optionally spot-check with a
  vision pass on high-conviction setups.
- **Data gaps / API outage.** Mitigate: provider health check each tick; on stale
  data, skip entries and only manage/close existing positions.
- **Look-ahead / repainting bugs.** Mitigate: only use *closed* candles; unit-test
  indicator math against known fixtures (reuse `metrics_margin/tests` pattern).
