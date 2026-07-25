---
title: "Skill: Run a strategy experiment"
tags: [skill]
updated: 2026-07-25
---

# Skill: Run a strategy experiment

Use when changing any strategy or risk parameter (Fable gate threshold, RISK_FRACTION,
trailing rule, watchlist, etc.). Changes to a trading loop must be measured, not
guessed.

## Steps
1. Copy [[experiment-log]] to `99-meta/experiments/EXP-YYYYMMDD-<slug>.md`.
2. State **one** hypothesis and the single variable you change.
3. Define the metric up front (expectancy after fees, max drawdown, abstain rate,
   Opus cost/trade). Never move the goalposts after seeing results.
4. Run in `demo` (or `shadow`) for a pre-committed sample size / time window.
5. Record results, decision (keep/revert), and any follow-up ADR.
6. If the change is a durable design choice, also write an ADR.

## Rules
- One variable at a time.
- Pre-commit the sample size to avoid stopping on a lucky streak.
- Fees and slippage always included — no paper-perfect fills.
