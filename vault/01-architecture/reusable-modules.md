---
title: Reusable Modules Inventory
tags: [architecture, reuse]
updated: 2026-07-25
---

# Reusable Modules Inventory

How each existing module is reused, extended, or bypassed by the autonomous
[[conductor-design|Conductor]]. This is the basis of the "merge, don't rebuild"
decision ([[ADR-0001-conductor-merge-over-rebuild]]).

| Module | Role today | Autonomous reuse | Change needed |
|--------|-----------|------------------|---------------|
| `bybit_trading` | Bybit v5 API wrapper (market, radar, trade, stream) | **Core execution + market data + monitoring** | Add demo-trading base URL toggle; expose OHLCV klines endpoint for indicator computation |
| `shared/chart_vision_common` | `TradeProposal` schema | **Unchanged** — autonomous path emits the same object | None (maybe add `source: vision|indicators` field) |
| `agent_charts_signal` | 2-pass **vision** inference | Reused **only in vision mode**. Autonomous mode uses an indicator-based Pass-2 (text) | New `indicators` provider path; Pass-2 prompt variant for numeric input |
| `agent_trading` | proposal → qty → order | **Reused**, but upgrade sizing to risk-based (stop-distance) | Add risk-based sizing alongside existing margin×leverage sizing |
| `case_graph_analytics` | Neo4j + embeddings over cases | **Reused as reflection/memory** | Add reflection artifact type; query API for "similar past setups" |
| `metrics_margin` | market correlation/funding metrics | **Reused by risk governor** for correlation caps | Expose a correlation lookup the governor can call |
| `mac/agent_charts_screen` | screenshot capture worker | **Not used** by autonomous loop | None — stays for manual vision mode |
| `web_app` | manual cockpit | **Reused** as monitoring/override UI | Add autonomous-loop status + kill switch view |

## New components (the only real build)

| New | Responsibility | Home |
|-----|----------------|------|
| **Conductor** | Orchestration loop, scheduling, model routing | `cloudrun/conductor/` (new) |
| **Indicators** | OHLCV → VWAP/MACD/EMA/RSI/ATR/levels/regime snapshot | `cloudrun/conductor/indicators/` or extend `bybit_trading` |
| **Risk Governor** | Portfolio caps, correlation, risk-based sizing, circuit breaker | inside Conductor; see [[risk-governor-spec]] |
| **Lifecycle Manager** | Monitor/trail/partial-TP/invalidation/time-exit | inside Conductor; see [[position-lifecycle-spec]] |

## Reuse ratio

Roughly **80% reuse / 20% new**. The 20% (indicators + risk + lifecycle) is
deliberately the high-value part per [[research-landscape]].
