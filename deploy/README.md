# iaw deployment & tick scheduling

## Tick scheduling — three ways

| Where | Mechanism | Setup |
|-------|-----------|-------|
| Local (simplest) | **Internal ticker** inside the conductor | web_app → Settings → Conductor Tick → "Tick cadence (minutes)". 0 = off. No cron needed. |
| Local (launchd) | macOS LaunchAgent → `POST /v1/loop/tick` | `cp deploy/local/com.iaw.conductor.tick.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.iaw.conductor.tick.plist` (edit repo path + interval in the plist). Plain crontab alternative: `*/15 * * * * /Users/juril/Developer/iaw/deploy/local/tick.sh` |
| Cloud (production) | **Cloud Scheduler → Cloud Run** (low budget: scheduler free tier + scale-to-zero; you pay only for tick seconds) | `PROJECT=... REGION=... ./deploy/setup_scheduler.sh` (defaults to every 15 min, OIDC-authenticated invoker SA) |

Overlap safety: the conductor holds a tick lock — a tick fired while another
runs returns 409 / is skipped, on every path (HTTP, SSE, internal ticker).
On Cloud Run keep `TICK_INTERVAL_MINUTES=0` (deploy script enforces this
default) and let Scheduler drive; the conductor must run `--max-instances 1`.

## Deploy scripts

All scripts read the service's local `.env` and pass an explicit allowlist of
env vars to the container — when you add a new var, add it to the `VARS` list
in the script.

```bash
# one-time: put secrets in Secret Manager
gcloud secrets create ANTHROPIC_API_KEY --data-file=- <<< "$ANTHROPIC_API_KEY"
gcloud secrets create BYBIT_API_KEY     --data-file=- <<< "$BYBIT_API_KEY"
gcloud secrets create BYBIT_API_SECRET  --data-file=- <<< "$BYBIT_API_SECRET"

PROJECT=my-proj REGION=europe-west1 ./deploy/deploy_bybit_trading.sh
# note the printed URL, set BYBIT_TRADING_URL in cloudrun/conductor/.env
PROJECT=my-proj REGION=europe-west1 ./deploy/deploy_conductor.sh
PROJECT=my-proj REGION=europe-west1 ./deploy/setup_scheduler.sh
# set VITE_* URLs in web_app/.env to the deployed service URLs, then:
PROJECT=my-proj REGION=europe-west1 ./deploy/deploy_web_app.sh
```

Key vars carried by the scripts (recent additions):

- bybit_trading: `BYBIT_DEMO` (demo-trading toggle), radar thresholds
- conductor: `TICK_INTERVAL_MINUTES`, `MODEL_GATE/SYNTHESIS/REFLECTION`,
  `CASES_PREFIX=cases-auto`, `PERSIST_CASES`, `INCLUDE_RECENT_OUTCOMES`,
  `ORDER_TTL_MINUTES`, `ORDER_MAX_DRIFT_ATR`, `ORDER_RECONCILE_TIMEFRAME`,
  risk caps + breakers
- web_app: `VITE_CONDUCTOR_URL` (baked at build time — rebuild to change)

Notes:
- conductor deploys `--no-allow-unauthenticated`; the scheduler invokes it via
  OIDC. For the web_app UI to reach a private conductor you must either allow
  unauthenticated on the conductor (simplest for demo phase) or put both
  behind IAP/a proxy — decide at go-live.
- Runtime settings changed in the UI persist to GCS and survive redeploys
  (they override env values; `GET /v1/settings` shows which fields).
