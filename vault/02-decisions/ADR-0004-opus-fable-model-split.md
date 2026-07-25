---
title: "ADR-0004: Two-tier model routing — Fable for cadence, Opus for decisions"
tags: [adr, models, cost]
status: accepted
date: 2026-07-25
---

# ADR-0004: Opus + Fable model split

## Status
Accepted.

## Context
Running a capable model on every tick and every open position would be expensive
and unnecessary. Research on multi-agent trading (FinCon's manager–analyst
hierarchy) shows a cheap analyst tier plus an expensive decision/reflection tier
is both effective and cost-efficient ([[research-landscape]]). The owner wants the
loop wired with Opus and Fable models.

## Decision
Route by stakes and frequency:

| Step | Model | Frequency |
|------|-------|-----------|
| Candidate pre-filter | **Fable 5** | Every tick, every candidate |
| Position monitoring / "still valid?" | **Fable 5** | Every tick, every open position |
| Entry/exit synthesis (Pass-2) | **Opus 5** | Only survivors of the Fable gate |
| Post-trade reflection | **Opus 5** | Only on closed positions |

Opus spend is therefore proportional to *trades*, not *ticks*.

## Consequences
- Positive: bounded, predictable token cost; high-stakes reasoning still gets the
  strong model; cheap layer absorbs the high-frequency load.
- Negative: two prompt/toolchains to maintain; a weak Fable gate could either
  waste Opus calls (too permissive) or miss setups (too strict) — must be tuned.
- Follow-ups: track per-tier token cost in Grafana; tune the Fable gate threshold
  as an experiment (log to `05-templates/experiment-log`).

## Alternatives considered
- **Single model everywhere**: simpler but costly and slower at cadence.
- **Opus only on entries, no reflection**: cheaper but discards the compounding
  value of post-mortems that research highlights.
