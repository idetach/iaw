---
title: "ADR-0001: Build autonomy as a Conductor over existing modules (merge, not rebuild)"
tags: [adr, architecture]
status: accepted
date: 2026-07-25
---

# ADR-0001: Conductor merge over rebuild

## Status
Accepted.

## Context
We want a *fully autonomous* trading strategy that behaves like a human
discretionary trader with proper risk management. The repo already contains a
vision→proposal→execution pipeline, an exchange wrapper with a radar scanner, a
graph memory, and market metrics. Options ranged from a thin orchestrator over
these modules to a greenfield multi-agent framework or an off-the-shelf agent bot.
See comparison in [[research-landscape]] and [[reusable-modules]].

## Decision
Build a thin **Conductor** service ([[conductor-design]]) that orchestrates the
existing modules in a supervised loop, adding only an **indicator engine**, a
**risk governor**, and a **position lifecycle manager**. Do not rebuild the
analysis brain or exchange layer, and do not adopt an opaque third-party agent.

## Consequences
- Positive: ~80% code reuse; fastest path to a demo-tradeable loop; fully
  auditable; concentrates new effort on the risk/reflection layer that research
  says actually adds value.
- Negative: Conductor becomes a critical orchestration point — needs strong
  safety rails (kill switch, circuit breaker, reconciliation).
- Follow-ups: define indicator snapshot, risk governor, lifecycle manager;
  demo-first rollout.

## Alternatives considered
- **Independent multi-agent framework** (port TradingAgents/FinCon): strong
  research pedigree but duplicates our vision brain and delays go-live.
- **Off-the-shelf "AI agent" bot**: opaque, unauditable, and embodies exactly the
  gambling-style hype risk we are avoiding.
- **Event-driven microservice mesh**: over-engineered for a single-user system now.
