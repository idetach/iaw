---
title: Risk Governor Spec
tags: [strategy, risk]
updated: 2026-07-25
status: proposed
---

# Risk Governor Spec

The risk governor is the **manager tier** that sits between a `TradeProposal` and
execution. Research ([[research-landscape]]) is consistent: this layer — not the
entry model — is where autonomous trading value comes from. Every rule here is
enforced in **code**, never left to an LLM.

## Position sizing — risk-based, not margin-based

Replace the current `balance × margin% × leverage / entry` sizing with
**stop-distance risk sizing**:

```
risk_per_trade   = equity * RISK_FRACTION           # e.g. 0.5%–1.0% of equity
stop_distance    = |entry - stop_loss|
qty              = risk_per_trade / stop_distance    # snapped to lot step
```

Then clamp by the existing caps (`max_leverage`, `max_margin_percent`) and by
instrument filters. This makes each loss ≈ a fixed small fraction of equity — the
core of human-like risk discipline, and structurally anti-"all-in."

## Portfolio-level gates (checked before every entry)

| Gate | Default | Rationale |
|------|---------|-----------|
| Max concurrent positions | 3–5 | Avoid over-diversification / attention spread |
| Max total margin deployed | ≤ 40% equity | Keep dry powder; survive gaps |
| Max risk per single trade | 0.5–1.0% equity | Bounded loss per idea |
| Max aggregate open risk | ≤ 3% equity | Sum of per-trade risks at stop |
| Correlation cap | ≤ 2 correlated same-direction | via `metrics_margin`; avoid hidden concentration |
| Per-symbol cooldown | e.g. 4h after close | Anti-overtrading / anti-tilt |
| Daily realized-loss breaker | e.g. -3% equity/day | Halt new entries → drop to `shadow` |
| Weekly realized-loss breaker | e.g. -6% equity/week | Escalated halt + human review |

## Bounded averaging (no martingale)

`position_strategy=DCA` is permitted only within limits: at most **one** add, at a
**better** price, with **total** position risk still ≤ the per-trade cap. Adds that
would breach the cap are rejected. `ADD_UP` (pyramiding into winners) allowed only
after the stop is moved to break-even.

## Decision output

For each proposal the governor returns one of:

- `APPROVE` (with final sized qty),
- `RESIZE` (qty reduced to fit caps),
- `REJECT` (with a machine-readable reason: `too_many_positions`,
  `correlation_cap`, `daily_breaker`, `cooldown`, `risk_cap`, `illiquid`, ...).

Every decision is logged to the case for audit and reflection.

## Circuit breaker state machine

```
NORMAL  --daily loss > limit-->  HALTED_DAY (shadow only, resets next UTC day)
NORMAL  --weekly loss > limit--> HALTED_WEEK (requires human ack)
any     --kill switch-->         STOPPED (no new entries; may still manage/exit)
```

Breakers only ever *reduce* activity. They never increase size or loosen limits.
