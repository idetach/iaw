---
title: Position Lifecycle Spec
tags: [strategy, execution]
updated: 2026-07-25
status: proposed
---

# Position Lifecycle Spec

## Order lifecycle (resting entries) — added 2026-07-26

A resting limit order is a live claim on future exposure whose thesis ages.
Bybit has no good-till-date, so the Conductor simulates it: every tick, each
of its own resting orders (`orderLinkId` prefix `conductor-`) is re-checked
in code (no LLM) and cancelled when any of these hold:

1. **TTL expiry** — older than `ORDER_TTL_MINUTES` (default 120): the entry
   window has passed.
2. **Thesis flip** — the reconcile-TF (default 1h) structure now trends
   *against* the pending entry with `TREND`/`BREAKOUT` regime.
3. **Price drift** — price is more than `ORDER_MAX_DRIFT_ATR` (default 2) ATRs
   from the limit: the pullback never came; the order is stale.

Supporting rules: resting orders **occupy position slots** in the governor and
their at-stop risk counts toward the aggregate risk cap; candidate selection
excludes any symbol with an open position **or** a surviving resting order
(one claim per symbol — no stacked entries across ticks, which is exactly the
failure observed on demo 2026-07-26 with two stacked SOLUSDT shorts).
Cancellation only ever reduces exposure; a still-valid setup is simply
re-proposed by a later tick at a fresh level. Manual orders are never touched.

How the Conductor manages a position from fill to close. Runs on the **Fable**
cadence (cheap, frequent); escalates to **Opus** only for genuine exit-decision
ambiguity. This is the other half of the value layer alongside the
[[risk-governor-spec|risk governor]].

## States

```
PENDING (limit resting) --> OPEN --> [SCALED] --> CLOSED
                       \--> EXPIRED (entry window passed, cancel)
OPEN --> STOPPED_OUT | TARGET_HIT | TIME_EXIT | INVALIDATED | MANUAL_CLOSE
```

## On entry (atomic)

Place the order **with SL and TP attached** in one call (`bybit_trading` supports
this). Never hold an unprotected position. Persist `trade.json` to the case.

## Each monitoring tick (Fable)

For every open position:

1. **Reconcile** against Bybit (positions are source of truth).
2. **Invalidation check**: does the current indicator snapshot still support the
   thesis? If structure has flipped against the position (e.g. trend break on the
   entry TF), flag for exit even before the stop.
3. **Trailing**: once price reaches +1R, move stop to break-even; then trail
   behind structure/ATR (never widen a stop — trailing is monotonic toward less
   risk).
4. **Partial TP**: optionally take partial profit at a defined level, move stop to
   break-even on the remainder.
5. **Time-based exit**: honor the proposal's `exit_time_from/to` window and
   `position_duration`. A HOUR trade that is flat well past its window is closed —
   capital and attention are freed. This enforces human-like patience *and*
   decisiveness.

## Escalation to Opus

Only when the Fable check is ambiguous (e.g. "thesis weakening but not broken near
a decision level"). Opus makes the hold/exit call. This keeps Opus spend tied to
real decisions.

## On close (any reason)

1. Write final PnL + exit reason to the case.
2. Trigger **reflection** (Opus): what was the thesis, what actually happened, was
   the entry/stop/size correct, what to do differently. Store to
   `case_graph_analytics` so future setups can retrieve it.
3. Apply per-symbol **cooldown** in the risk governor.

## Hard rules

- No position without an active stop, ever.
- Stops move only toward **less** risk (break-even, then trail).
- Time-exit and invalidation can close a position early; they never *add* risk.
- All modifications idempotent and logged.
