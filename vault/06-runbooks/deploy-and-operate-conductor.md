---
title: "Runbook: Deploy & operate the Conductor"
tags: [runbook, ops]
updated: 2026-07-25
status: draft
---

# Runbook: Deploy & operate the Conductor

> Draft — fill in exact commands/regions once the `cloudrun/conductor` service
> exists. Structure mirrors the other `cloudrun/*` services.

## Modes
`EXECUTION_MODE` ∈ `{shadow, demo, live}`. **Default `demo`.** Never set `live`
without completing the go-live checklist below.

## Deploy (demo)
1. Ensure `bybit_trading` is deployed and reachable; Bybit demo credentials set.
2. Set env: `EXECUTION_MODE=demo`, `GCS_BUCKET`, `CASES_PREFIX`,
   `BYBIT_TRADING_URL`, risk-governor params, model IDs (Opus 5 / Fable 5).
3. `gcloud run deploy conductor --source . --region <region>`.
4. Verify `/health` and `/v1/config`; confirm mode = demo.

## Operate
- **Start/stop loop**: scheduler trigger (Cloud Scheduler) or the kill switch.
- **Kill switch**: env flag `LOOP_ENABLED=false` + web_app button → no new entries;
  open positions still managed/exited.
- **Monitor**: Grafana panels (open risk, daily PnL, breaker state, per-tier token
  cost); Telegram alerts on entry/exit/breaker.
- **Daily check**: reconcile Bybit positions vs. cases; review reflections.

## Circuit-breaker response
If `HALTED_DAY`/`HALTED_WEEK`: do not override. Review recent losers' reflections,
write a [[postmortem]] if systemic, adjust via [[run-a-strategy-experiment]].

## Go-live checklist (demo → live)
- [ ] Meaningful demo sample with positive expectancy after fees
- [ ] Max drawdown stayed within breaker budget
- [ ] Risk governor rejected the right trades (audit the REJECT log)
- [ ] Lifecycle manager honored stops/time-exits with no unprotected positions
- [ ] Kill switch + breakers tested end to end
- [ ] Live starts at **minimum** size with tightened breakers
- [ ] ADR recorded for the go-live decision
