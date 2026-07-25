---
title: "ADR-0003: Roll out on Bybit demo trading before any real capital"
tags: [adr, risk, rollout]
status: accepted
date: 2026-07-25
---

# ADR-0003: Bybit demo trading first

## Status
Accepted.

## Context
Autonomous execution over real funds is the highest-risk part of the system.
Industry practice in 2026 keeps serious capital in the semi-autonomous band and
validates loops in sandboxes first ([[research-landscape]]). The owner chose
**Bybit demo trading** as the first execution target.

## Decision
The Conductor ships with `EXECUTION_MODE` ∈ `{shadow, demo, live}`, defaulting to
**demo**. Demo uses Bybit's demo-trading account (real mainnet market data,
virtual funds). Promotion to `live` requires a documented go-live checklist and a
review of demo performance and risk-governor behavior over a meaningful sample.

## Consequences
- Positive: validates real order mechanics, fills, SL/TP, and the full loop
  without capital risk; safe place to tune the risk governor and lifecycle.
- Negative: demo fills/slippage do not perfectly match live; a later small-capital
  live phase is still needed before scaling.
- Follow-ups: implement the mode switch and a go-live checklist runbook; add a
  `shadow` mode that logs intended trades without placing orders.

## Alternatives considered
- **Live with tiny capital immediately**: real fills but unnecessary early risk.
- **Backtest only**: no order-mechanics validation; deferred as a complement, not
  a replacement.
