---
title: Strategy Spec — Multi-Timeframe Confluence Swing Trader
tags: [strategy]
updated: 2026-07-25
status: proposed
---

# Strategy Spec — Multi-Timeframe Confluence Swing Trader

The autonomous strategy is a **discretionary-style, multi-timeframe confluence
swing/position trader** on Bybit USDT perps. It is deliberately the strategy the
existing vision pipeline already encodes, made autonomous and risk-governed.

## Behavioral contract (human-like, non-exploitative)

The strategy MUST behave like a disciplined human swing trader and MUST NOT do any
of the following (hard prohibitions, enforced in code + prompt):

- ❌ High-frequency trading, tick scalping, latency/statistical arbitrage
- ❌ Gambling-style or all-in position sizing
- ❌ Martingale / unbounded averaging-down / abusive hedging
- ❌ Trading without a pre-defined stop and invalidation level
- ❌ Chasing extended moves far from VWAP without structure

It SHOULD:

- ✅ Operate on a **minutes-scale cadence** (5–15m ticks), holding HOUR→SWING
- ✅ Enter only on **multi-timeframe agreement** (higher TFs set bias, lower TFs
  time entry)
- ✅ **Abstain by default** — no trade is the most common correct action
- ✅ Size by **risk, not by margin** (fixed fraction of equity at stop)
- ✅ Prefer liquid instruments; avoid thin/illiquid symbols

## Setups (what counts as an edge)

1. **Trend-pullback continuation.** Higher-TF trend intact; enter on a pullback to
   a level/VWAP with lower-TF confirmation. Stop beyond the pullback swing.
2. **Mean-reversion at levels.** Price stretched from VWAP into a strong
   support/resistance with exhaustion; fade back toward VWAP. Stop beyond the
   level.
3. **Break-and-retest.** Clean break of a key level, enter on the retest holding.
   Stop below the retest.

All three require: a clear invalidation level, a defined target, and multi-TF
confluence. If any is missing → **NONE** (abstain rubric already in the vision
rulebook applies to the numeric path too).

## Inputs

Numeric indicator snapshot per timeframe (see [[autonomous-data-path]]): regime,
trend_dir, vwap_state (+ATR distance), macd_state, key_levels, ATR/volatility.
Optional context: `case_graph_analytics` similar past setups; `metrics_margin`
regime/correlation.

## Output

A standard `TradeProposal` (`shared/chart_vision_common`): direction, entry
window, target, stop, `position_duration`, `position_strategy`, confidence,
reasons, tags. `position_strategy=SCALP` is **disabled** for the autonomous path
per the behavioral contract; DCA is allowed but **bounded** by the risk governor.

## Success criteria (evaluate on demo)

Judge on **risk-adjusted** behavior, not raw return:

- Positive expectancy after fees on a meaningful sample of trades
- Max drawdown within the configured circuit-breaker budget
- High abstain rate on chop; entries concentrated in clean setups
- Reflections show the loop learning from losers (fewer repeated mistakes)

The honest expectation (see [[research-landscape]]): the edge is **discipline and
consistency**, not outsized returns.
