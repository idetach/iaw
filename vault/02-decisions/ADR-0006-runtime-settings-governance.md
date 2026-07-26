---
title: "ADR-0006: Runtime settings governance — behavioral settings UI-editable, risk caps env-only"
tags: [adr, settings, risk, ui]
status: accepted
date: 2026-07-26
---

# ADR-0006: Runtime settings governance

## Status
Accepted.

## Context
Operating the Conductor requires frequent tuning of *behavioral* parameters
(model routing, watchlist, order TTL, LLM-memory toggle) — forcing a redeploy
for each change slows iteration. But the same convenience applied to *risk
limits* would let a bad afternoon turn into a UI click that doubles risk per
trade. The web_app Settings page previously covered only the (currently
inactive) desktop-vision pipeline.

## Decision
Split settings into two governance classes:

1. **Editable (behavioral)** — via conductor `GET/PUT /v1/settings`, whitelisted:
   model_gate/synthesis/reflection, watchlist, timeframes, radar toggle,
   max candidates, min_confidence, include_recent_outcomes, persist_cases,
   order TTL / drift / reconcile TF, and execution_mode **restricted to
   shadow↔demo** (live stays env-only per [[ADR-0003-bybit-demo-trading-first]]).
   Overrides mutate the running instance and persist best-effort to GCS
   (`{cases_prefix}/_settings/runtime.json`), restored at startup.
2. **Guarded (risk caps)** — env-only, exposed read-only in the UI:
   risk_fraction, position slots, aggregate risk, margin/leverage caps,
   breakers, cooldown. Changing them requires a redeploy plus an experiment
   log or ADR. The API rejects them with an explanatory 422.

UI: the Settings page becomes a **collapsible side menu** (icons when
collapsed) with two sections — **Conductor Tick** (new, default) and
**Desktop Vision** (existing controls, unchanged).

## Consequences
- Positive: fast behavioral iteration without redeploys; risk limits keep a
  deliberate, auditable change path; settings survive restarts via GCS.
- Negative: runtime overrides are per-instance state (max-instances=1 already
  required); env values and persisted overrides can diverge — the API reports
  which fields are overridden.
- Follow-ups: surface per-tier token cost next to model dropdowns; consider
  audit-logging settings changes into the case stream.

## Alternatives considered
- **Everything editable in UI**: rejected — risk caps must not be one click away.
- **Everything env-only**: rejected — behavioral tuning cadence is too high.
- **Tabs instead of side menu**: owner prefers collapsible side menu; also
  scales better as sections grow.
