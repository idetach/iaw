---
title: Conductor Design
tags: [architecture, design]
updated: 2026-07-25
status: in-progress   # scaffold implemented at cloudrun/conductor (2026-07-25)
---

# Conductor Design

> **Implementation status:** scaffold exists at `cloudrun/conductor/` — indicator
> engine, risk governor, lifecycle decisions, model routing (claude-fable-5 /
> claude-opus-5), shadow/demo/live modes, 25 passing unit tests. Remaining TODOs
> in its README (PnL breaker inputs, cooldowns, case persistence, reflection
> persistence, Opus escalation).

The **Conductor** is the new orchestration service that turns iaw's existing
building blocks into a supervised autonomous trader. It is the "manager" in the
manager–analyst hierarchy that research ([[research-landscape]]) shows is where
autonomous trading value comes from.

Design goals: **human-like discretionary behavior, bounded risk, full
auditability, cheap to run.** It must be structurally incapable of HFT, tick
scalping, latency arbitrage, gambling/all-in, or abusive hedging.

## Runtime shape

A single Cloud Run service (or Cloud Run Job on a schedule) running an async loop.
Stateless between ticks; all state lives in GCS cases + Bybit account + Neo4j.

```
tick (every N minutes, e.g. 5–15m — swing cadence, NOT sub-second):
  A. Gather
     - radar candidates (bybit_trading /v1/radar)  [Fable]
     - watchlist symbols (config)
  B. Analyze each candidate
     - fetch multi-TF OHLCV (4h..15m; 5m/1m optional)
     - compute indicator snapshot (see autonomous-data-path)
     - Fable pre-filter: "is there a plausible setup?" -> drop most  [cost gate]
  C. Decide (only survivors)
     - Opus Pass-2 synthesis -> TradeProposal (reuse schema)          [Opus]
  D. Govern (risk-governor-spec)
     - portfolio caps, correlation, daily-loss breaker
     - risk-based sizing (fraction of equity at stop)
     - approve / resize / reject
  E. Execute (approved only)
     - agent_trading -> bybit_trading (DEMO), atomic order + SL + TP
  F. Manage open positions (position-lifecycle-spec)                  [Fable]
     - invalidation check, trailing, partial TP, time-based exit
  G. Reflect on closed positions
     - Opus writes post-mortem -> case_graph_analytics                [Opus]
```

## Model routing (Opus 5 + Fable 5) — see [[ADR-0004-opus-fable-model-split]]

| Step | Model | Why |
|------|-------|-----|
| B pre-filter | **Fable** | High frequency, cheap, discard obvious no-trades |
| C synthesis | **Opus** | Rare, high-stakes entry decision + risk reasoning |
| F monitoring | **Fable** | Frequent, routine "still valid?" checks |
| G reflection | **Opus** | Quality post-mortems compound into better decisions |

Opus is only invoked on candidates that survive the Fable gate and for closed
positions — keeping token spend bounded and roughly proportional to *trades*, not
*ticks*.

## Concurrency & safety rails (hard, non-LLM)

These are enforced in code, not left to a model:

- **Global kill switch** (env flag + web_app button) halts all new entries.
- **Demo-first**: `EXECUTION_MODE=demo|shadow|live`, defaults to `demo`.
- **Idempotent orders** via `orderLinkId` derived from case id.
- **One in-flight decision per symbol**; positions keyed by symbol.
- **Circuit breaker**: daily realized-loss limit → mode drops to `shadow`.
- **Reconciliation** at each tick: Bybit positions are the source of truth, not
  local state.

## Interfaces

- Reads: `bybit_trading` (market/radar/positions/balance), config watchlist,
  `case_graph_analytics` (similar past setups), `metrics_margin` (correlation).
- Writes: GCS cases (request/observations/proposal/trade/reflection), Bybit demo
  orders, Neo4j reflections.
- Observability: structured logs + Grafana panels + Telegram alerts on
  entry/exit/breaker.

## Open design questions

- Data source for OHLCV: Bybit klines vs. a dedicated market-data API platform.
  See [[autonomous-data-path]]. Start with Bybit klines (already wired), abstract
  behind a provider interface.
- Watchlist strategy: pure radar-driven vs. fixed liquid majors + radar overlay.
  Start with liquid majors + radar overlay to avoid illiquid traps.
