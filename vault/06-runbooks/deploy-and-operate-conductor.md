---
title: "Runbook: Deploy & operate the Conductor"
tags: [runbook, ops]
updated: 2026-07-25
status: draft
---

# Runbook: Deploy & operate the Conductor

> The service exists at `cloudrun/conductor/` (see its README for routes and
> env vars). Fill in region/scheduler specifics at first deploy.

## Modes
`EXECUTION_MODE` ∈ `{shadow, demo, live}`. **Default `demo`.** Never set `live`
without completing the go-live checklist below.

## Deploy (demo)
Scripted — see `deploy/README.md`:

1. Secrets to Secret Manager (`ANTHROPIC_API_KEY`, `BYBIT_API_KEY/SECRET`).
2. `PROJECT=... REGION=... ./deploy/deploy_bybit_trading.sh` (carries `BYBIT_DEMO`).
3. Point `BYBIT_TRADING_URL` at the printed URL; `./deploy/deploy_conductor.sh`
   (carries models, cases-auto, order-reconciliation and risk vars;
   forces `TICK_INTERVAL_MINUTES=0` and `--max-instances 1`).
4. `./deploy/setup_scheduler.sh` — Cloud Scheduler → `POST /v1/loop/tick`
   every 15 min via OIDC invoker SA (low budget: scheduler free tier +
   scale-to-zero conductor).
5. `./deploy/deploy_web_app.sh` after setting `VITE_*` URLs (build-time).
6. Verify `/health`, `/v1/config`, `/v1/loop/status`; confirm mode = demo.

## Tick cadence (local testing)
Use the **internal ticker**: Settings → Conductor Tick → "Tick cadence
(minutes)" (0 = off). Alternative: launchd plist / crontab in `deploy/local/`.
A tick lock prevents overlap on every path (HTTP 409 / SSE busy event /
ticker skip).

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
