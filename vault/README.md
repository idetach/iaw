---
title: iaw Project Vault — Home
tags: [moc, home]
updated: 2026-07-25
---

# iaw — Project Vault (Map of Content)

This is the knowledge base and agentic-development workspace for **iaw**, the
chart-vision + autonomous trading system for Bybit perpetual futures. Open this
folder as an Obsidian vault (`Open folder as vault → iaw/vault`).

The vault is the durable memory of *why* the system is built the way it is, so
that both humans and coding agents can act with full context.

## How to use this vault

- **Starting new work?** Read [[system-overview]] then the relevant strategy or
  architecture note.
- **Making a design choice?** Record it as an ADR in `02-decisions/` using
  [[_adr-template]]. Never change an accepted ADR — supersede it with a new one.
- **Writing a doc?** Copy a template from `05-templates/`.
- **Running/deploying?** See `06-runbooks/`.

## Map

### 01 — Architecture
- [[system-overview]] — what exists today, end to end
- [[reusable-modules]] — inventory of modules and how the autonomous loop reuses them
- [[conductor-design]] — the autonomous orchestrator (the new component)
- [[autonomous-data-path]] — cloud, indicator-based market data (no screenshots)

### 02 — Decisions (ADRs)
- [[ADR-0001-conductor-merge-over-rebuild]]
- [[ADR-0002-direct-market-data-indicators]]
- [[ADR-0003-bybit-demo-trading-first]]
- [[ADR-0004-opus-fable-model-split]]

### 03 — Strategy
- [[strategy-spec]] — the multi-timeframe confluence swing strategy
- [[risk-governor-spec]] — portfolio risk rules (the real edge)
- [[position-lifecycle-spec]] — how positions are managed and exited
- [[research-landscape]] — what the field actually supports (with sources)

### 04 — Skills (agent playbooks)
- [[04-skills/README]]

### 05 — Templates
Design doc, ADR, experiment log, runbook, postmortem.

### 06 — Runbooks
- [[deploy-and-operate-conductor]]

### 99 — Meta
- [[glossary]]

## Guiding principles

1. **Reuse before rebuild.** ~80% of an autonomous system already exists here.
2. **The edge is process, not prediction.** Risk governance and reflection beat a
   cleverer entry model. See [[research-landscape]].
3. **Human-like, never exploitative.** No HFT, tick scalping, latency arbitrage,
   gambling-style or all-in trading, or abusive hedging. Every position has a
   pre-defined stop and invalidation.
4. **Demo before capital.** Prove the loop on Bybit demo trading first.
5. **Every decision leaves a trace** — an ADR, an experiment log, or a case in the
   graph memory.
