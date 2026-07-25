---
title: Skills — Agent Playbooks
tags: [skills, moc]
updated: 2026-07-25
---

# Skills — Agent Playbooks

Reusable, repo-specific playbooks a coding agent (or human) follows to do common
iaw tasks the same way every time. These are prose procedures, not code. Keep them
short, imperative, and current.

> Distinct from Cowork/Claude *Skills* packages. These are project conventions.
> When one stabilizes, it can be promoted into a real Skill later.

## Available
- [[add-a-cloudrun-service]] — scaffold a new Cloud Run FastAPI service the iaw way
- [[write-an-adr]] — record an architectural decision
- [[run-a-strategy-experiment]] — change a strategy/risk parameter safely and measure it

## Conventions every agent should follow

- **Read before writing.** Start from [[system-overview]] and the relevant spec.
- **Decisions get ADRs.** Any non-trivial choice → `02-decisions/` via
  [[_adr-template]]. Never edit an accepted ADR; supersede it.
- **Demo-first.** Never point execution at `live` without the go-live checklist
  ([[deploy-and-operate-conductor]]).
- **Safety rails are code, not prompts.** Risk limits, caps, and breakers live in
  the risk governor, not in an LLM instruction.
- **Every service** has: `config.py` (pydantic settings), `/health`, `/v1/config`,
  a `README.md`, `run_local.sh`, `start.sh`, and a Dockerfile — match the existing
  `cloudrun/*` pattern.
- **Only closed candles** in indicator math; unit-test against fixtures.
