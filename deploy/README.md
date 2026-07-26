# iaw deployment & tick scheduling

## Tick scheduling — three ways

| Where | Mechanism | Setup |
|-------|-----------|-------|
| Local (simplest) | **Internal ticker** inside the conductor | web_app → Settings → Conductor Tick → "Tick cadence (minutes)". 0 = off. No cron needed. |
| Local (launchd) | macOS LaunchAgent → `POST /v1/loop/tick` | `cp deploy/local/com.iaw.conductor.tick.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.iaw.conductor.tick.plist` (edit repo path + interval in the plist). Plain crontab alternative: `*/15 * * * * /Users/juril/Developer/iaw/deploy/local/tick.sh` |
| Cloud (production) | **Cloud Scheduler → Cloud Run** (low budget: scheduler free tier + scale-to-zero; you pay only for tick seconds) | `PROJECT=... REGION=... ./deploy/setup_scheduler.sh` (defaults to every 15 min, OIDC-authenticated invoker SA). Change cadence later from web_app → Settings → Conductor Tick → "Cloud tick cadence" (ADR-0009). |

Overlap safety: the conductor holds a tick lock — a tick fired while another
runs returns 409 / is skipped, on every path (HTTP, SSE, internal ticker).
On Cloud Run keep `TICK_INTERVAL_MINUTES=0` (deploy script enforces this
default) and let Scheduler drive; the conductor must run `--max-instances 1`.

## Deploy scripts

All scripts read the service's local `.env` and pass an explicit allowlist of
env vars to the container — when you add a new var, add it to the `VARS` list
in the script.

```bash
# one-time: enable APIs + put secrets in Secret Manager
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  secretmanager.googleapis.com cloudscheduler.googleapis.com
gcloud secrets create ANTHROPIC_API_KEY --data-file=- <<< "$ANTHROPIC_API_KEY"
gcloud secrets create BYBIT_API_KEY     --data-file=- <<< "$BYBIT_API_KEY"
gcloud secrets create BYBIT_API_SECRET  --data-file=- <<< "$BYBIT_API_SECRET"

PROJECT=my-proj REGION=europe-west1 ./deploy/deploy_bybit_trading.sh
# note the printed URL, set BYBIT_TRADING_URL in cloudrun/conductor/.env
PROJECT=my-proj REGION=europe-west1 ./deploy/deploy_conductor.sh
# REQUIRED for autonomous cloud ticks (conductor runs TICK_INTERVAL_MINUTES=0):
PROJECT=my-proj REGION=europe-west1 ./deploy/setup_scheduler.sh
# set VITE_* URLs in web_app/.env to the deployed service URLs, then:
PROJECT=my-proj REGION=europe-west1 ./deploy/deploy_web_app.sh
```

`setup_scheduler.sh` is **not optional on Cloud Run**: the internal ticker is
off there, so Cloud Scheduler is the only thing that fires ticks. It creates the
`conductor-tick-invoker` service account, grants it `run.invoker`, and creates
an OIDC-authenticated job (default every 15 min). Pause it any time with
`gcloud scheduler jobs pause conductor-tick --location <region>`.

Key vars carried by the scripts (recent additions):

- bybit_trading: `BYBIT_DEMO` (demo-trading toggle), radar thresholds
- conductor: `TICK_INTERVAL_MINUTES`, `MODEL_GATE/SYNTHESIS/REFLECTION`,
  `CASES_PREFIX=cases-auto`, `PERSIST_CASES`, `INCLUDE_RECENT_OUTCOMES`,
  `ORDER_TTL_MINUTES`, `ORDER_MAX_DRIFT_ATR`, `ORDER_RECONCILE_TIMEFRAME`,
  risk caps + breakers
- web_app: `VITE_CONDUCTOR_URL` (baked at build time — rebuild to change)

## Cloud Run service-to-service authentication

`bybit_trading` and `conductor` both deploy `--no-allow-unauthenticated`. The
conductor must authenticate to `bybit_trading` with **two** tokens:

1. A Google IAM identity token in `Authorization: Bearer <id_token>` for Cloud Run.
2. The shared application secret in `X-Internal-Token: <BYBIT_TRADING_TOKEN>`.

After deploying `bybit_trading`, grant the conductor service account permission
to invoke it:

```bash
# Default Cloud Run service account for the conductor revision.
PROJECT=iawwai
REGION=europe-west1
SA="884594452381-compute@developer.gserviceaccount.com"

gcloud run services add-iam-policy-binding bybit-trading \
  --project "$PROJECT" --region "$REGION" \
  --member="serviceAccount:$SA" \
  --role="roles/run.invoker"
```

If you later configure a custom `--service-account` for conductor, grant that
account instead.

## Notes

- conductor deploys `--no-allow-unauthenticated`; the scheduler invokes it via
  OIDC. The browser reaches it **same-origin** through the `iaw-web` reverse
  proxy (`/api/conductor/*`), which verifies the user's Firebase token and
  injects a Google identity token. `deploy_web_app.sh` wires this up and grants
  the `iaw-web` service account `run.invoker` on the conductor. So the conductor
  never needs to be public — see ADR-0008.
- Runtime settings changed in the UI persist to GCS and survive redeploys
  (they override env values; `GET /v1/settings` shows which fields).
- See `vault/02-decisions/ADR-0008-cloud-run-service-to-service-auth.md` for the
  full rationale.
