---
title: "ADR-0005: Gate runs one tier cheaper — cost tiers by call volume × stakes"
tags: [adr, models, cost]
status: accepted
date: 2026-07-26
supersedes: partially ADR-0004
---

# ADR-0005: Three-tier model routing

## Status
Accepted. Refines [[ADR-0004-opus-fable-model-split]].

## Context
ADR-0004 set a two-tier split ("Fable for cadence, Opus for decisions"), written
when Fable was assumed to be the cheap tier. In fact Claude Fable 5 is the
Mythos-class model **above** Opus — the original config was running the most
expensive model on the highest-volume call. Tick telemetry confirms the gate
dominates call volume (every candidate, every tick — 6+ calls/tick) while its
task is the simplest in the pipeline: a binary plausibility verdict over an
already-structured numeric snapshot. Synthesis and reflection run only on gate
survivors and closed trades respectively.

## Decision
Route by (call volume × stakes), defaulting to:

| Step | Volume | Stakes | Default model |
|------|--------|--------|---------------|
| Gate | highest | low (recall-safe: errors → no trade) | **claude-sonnet-5** |
| Synthesis | low | highest | **claude-opus-5** (claude-fable-5 as premium option) |
| Reflection | low | high (compounds into memory) | **claude-opus-5** |

`claude-haiku-4-5` remains a further gate downgrade to test via experiment log.
Models are runtime-selectable per ADR-0006; tier ordering for reference:
Fable > Opus > Sonnet > Haiku.

## Consequences
- Positive: gate cost drops roughly an order of magnitude with minimal expected
  quality loss on a binary task; spend concentrates where decisions are made.
- Negative: a weaker gate may pass more marginal setups through to Opus (cost)
  or miss subtle ones (opportunity); monitor gate pass-rate and tune.
- Follow-ups: log per-tier token cost; A/B sonnet vs haiku gate as an experiment.

## Alternatives considered
- **Fable everywhere**: best quality, cost scales with ticks not trades — rejected.
- **Haiku gate by default**: cheapest; start one notch conservative (Sonnet) and
  measure before downgrading further.
