---
title: Glossary
tags: [meta, reference]
updated: 2026-07-25
---

# Glossary

- **Conductor** — the new orchestration service running the autonomous loop; the
  "manager" tier. See [[conductor-design]].
- **Risk governor** — code-enforced portfolio risk layer between proposal and
  execution. See [[risk-governor-spec]].
- **Lifecycle manager** — component that monitors, trails, and exits open
  positions. See [[position-lifecycle-spec]].
- **Indicator snapshot** — numeric per-timeframe feature set replacing vision
  Pass-1. See [[autonomous-data-path]].
- **TradeProposal** — the validated decision object (`shared/chart_vision_common`):
  direction, entry window, target, stop, leverage, margin %, duration, strategy,
  confidence, reasons, tags.
- **Case** — a GCS-persisted record of one analysis+trade (request, observations,
  proposal, trade, reflection). Ingested into the graph memory.
- **Reflection** — post-trade post-mortem written by Opus into
  `case_graph_analytics`; the memory that compounds.
- **Abstain rubric** — rules that make the model output `NONE` (no trade); the most
  common correct action.
- **R** — risk unit = distance from entry to stop; "+1R" = one unit of profit.
- **Risk-based sizing** — qty = (equity × risk fraction) / stop distance; makes each
  loss a fixed small fraction of equity.
- **EXECUTION_MODE** — `shadow` (log only), `demo` (Bybit demo funds), `live` (real).
- **Fable / Opus tiers** — Fable 5 = cheap high-cadence (scan, pre-filter, monitor);
  Opus 5 = expensive low-cadence (entry synthesis, reflection). See
  [[ADR-0004-opus-fable-model-split]].
- **Radar** — `bybit_trading` scanner for extreme price/volume/funding events.
- **ADR** — Architecture Decision Record; immutable once accepted, superseded not
  edited.
