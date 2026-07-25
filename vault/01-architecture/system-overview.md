---
title: System Overview
tags: [architecture]
updated: 2026-07-25
---

# System Overview

iaw is a **vision + autonomous trading system** for Bybit USDT perpetual futures.
Today it runs **human-in-the-loop**; the autonomous path (see [[conductor-design]])
wraps the same building blocks in a supervised runtime loop.

## Two operating modes

| Mode | Trigger | Data | Decision | Execution |
|------|---------|------|----------|-----------|
| **Vision (today)** | Human | TradingView screenshots (6 TFs) | 2-pass vision LLM | Human clicks "execute" |
| **Autonomous (target)** | Scheduler/loop | Direct market-data indicators via cloud API | Fable pre-filter → Opus synthesis | Risk governor → auto-execute (Bybit demo first) |

The vision mode stays useful as a manual/research cockpit. The autonomous mode is
data-first and cloud-native — no local machine, no screenshots (see
[[autonomous-data-path]] and [[ADR-0002-direct-market-data-indicators]]).

## Component map (current repo)

```
mac/agent_charts_screen        macOS capture worker (screenshots → crop → upload)   [vision mode only]
cloudrun/agent_charts_signal   2-pass vision inference → validated TradeProposal
shared/chart_vision_common     TradeProposal pydantic schema + constants
cloudrun/agent_trading         proposal → qty sizing → order placement
cloudrun/bybit_trading         Bybit v5 API: market, radar, trade, price stream
cloudrun/case_graph_analytics  Neo4j + embeddings over past cases (memory/reflection)
grafana/metrics_margin         market-wide correlation/funding metrics + Grafana + alerts
web_app                        React cockpit for case review + manual/auto execution
```

## End-to-end flow (target autonomous loop)

```
                +------------------ Conductor (new) ------------------+
                |                                                     |
  radar scan -->| 1. select candidates (Fable)                       |
  market API -->| 2. fetch multi-TF OHLCV -> indicator snapshot       |
                | 3. cheap setup pre-filter (Fable)                   |
                | 4. Pass-2 synthesis -> TradeProposal (Opus)         |
                | 5. RISK GOVERNOR: caps, correlation, sizing         |
                | 6. execute via agent_trading -> bybit_trading (demo) |
                | 7. lifecycle: monitor / trail / partial / exit      |
                | 8. reflection -> case_graph_analytics (memory)      |
                +-----------------------------------------------------+
```

Steps 1, 4, 6, 8 reuse existing services almost unchanged. Steps 2, 3, 5, 7 are
the genuinely new work — and per [[research-landscape]], steps 5 and 7 (risk +
lifecycle) are where the value actually lives.

## Key existing assets that make this cheap

- `TradeProposal` schema already models direction, target, stop, leverage,
  margin %, entry/exit **time windows**, `position_duration` (HOUR/DAY/SWING),
  `position_strategy` (ADD_UP/DCA/CONTRARIAN/SCALP/HOLD), confidence, and an
  **abstain rubric**. The autonomous loop emits the same object.
- `bybit_trading` already exposes balance, positions, orders, order placement,
  SL/TP (full + partial), close, and a **radar** scanner — everything the
  Conductor needs to act and monitor.
- `case_graph_analytics` already ingests case artifacts into a graph with
  embeddings — a ready-made reflection/memory substrate.
- Risk caps (`max_leverage=10`, `max_margin_percent=25`) already exist in config.

See [[reusable-modules]] for the per-module reuse plan.
