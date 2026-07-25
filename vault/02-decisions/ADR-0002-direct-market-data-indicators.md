---
title: "ADR-0002: Autonomous path uses direct market-data indicators in the cloud (no screenshots)"
tags: [adr, data]
status: accepted
date: 2026-07-25
---

# ADR-0002: Direct market-data indicators, cloud-only

## Status
Accepted.

## Context
The vision pipeline depends on a macOS screenshot worker that requires a desktop
session / always-on Mac. Full 24/7 autonomy cannot depend on the owner's local
machine. The owner explicitly wants a fully cloud-deployed worker using direct
market-data indicators via an API platform, and does not want to reserve a local
machine or maintain visual screenshot workers.

## Decision
The autonomous loop computes indicators **numerically from OHLCV** obtained via a
market-data API, replacing vision Pass-1 with an **indicator engine**
([[autonomous-data-path]]). Phase 1 uses Bybit v5 klines (already reachable);
Phase 2 may add a dedicated market-data vendor behind a provider interface. The
vision path remains available for manual research only.

## Consequences
- Positive: runs entirely in the cloud; cheaper (text-only LLM calls);
  reproducible; unit-testable indicator math.
- Negative: loses some price-action nuance a vision model might catch; requires
  building and validating an indicator engine.
- Follow-ups: define the indicator snapshot schema; add a Pass-2 prompt variant
  for numeric input; unit-test indicators on closed candles only.

## Alternatives considered
- **Always-on Mac + scheduled screenshots**: rejected — owner does not want to
  reserve a local machine.
- **Headless cloud chart rendering**: more work than numeric indicators for the
  same signal; deferred.
