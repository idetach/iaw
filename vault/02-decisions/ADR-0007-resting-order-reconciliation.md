---
title: "ADR-0007: Resting entry orders are reconciled exposure, not fire-and-forget"
tags: [adr, risk, orders]
status: accepted
date: 2026-07-26
---

# ADR-0007: Resting-order reconciliation

## Status
Accepted.

## Context
Live demo testing (2026-07-26) produced four resting limit orders across ticks,
including two stacked SOLUSDT shorts — because candidate selection excluded
open *positions* but not open *orders*, and nothing ever cancelled an unfilled
entry whose thesis had aged. Market-microstructure practice is clear: a stale
resting limit is adverse-selection bait — it fills exactly when the move is
against you. Bybit offers no good-till-date, so expiry must be simulated.

## Decision
The Conductor treats its resting entry orders (`orderLinkId` prefix
`conductor-`) as reconciled exposure, in deterministic code (no LLM):

1. **Every tick, every conductor order is re-checked** and cancelled on any of:
   TTL expiry (`ORDER_TTL_MINUTES`, default 120), reconcile-TF trend flip
   against the pending entry (TREND/BREAKOUT regime only), or price drift
   beyond `ORDER_MAX_DRIFT_ATR` (default 2) ATRs from the limit.
2. **Orders occupy governor slots** and their at-stop risk counts toward the
   aggregate risk cap.
3. **One claim per symbol**: symbols with an open position or surviving order
   are excluded from candidates — entries can never stack across ticks.
4. **Fail-safe direction**: cancellation only reduces exposure; a still-valid
   setup is re-proposed later at a fresh level. On reconcile errors the order's
   exposure claim is kept (conservative). Manual orders are never touched.
5. **Loud degradation**: if the open-orders fetch fails, the tick emits an
   explicit error event ("reconciliation skipped") — never a silent empty list.
   (Learned the hard way: Bybit v5 realtime-orders requires `settleCoin` for
   linear; the missing param made reconciliation silently see zero orders.)

## Consequences
- Positive: no stacked entries; exposure accounting includes pending claims;
  stale theses die on schedule; failures are visible in the tick stream.
- Negative: extra klines fetch per resting order per tick (cheap); a cancelled
  order that would have filled favorably is a lost opportunity — accepted as
  the safe side of the trade-off.
- Follow-ups: optional Fable second opinion before cancel (config-gated);
  metrics on cancel reasons.

## Alternatives considered
- **Amend price instead of cancel** (cancel-replace): more complex state; the
  re-propose path achieves the same with existing machinery.
- **LLM decides cancels**: rejected — exposure hygiene is a safety rail and
  belongs in code (consistent with risk-governor-spec).
