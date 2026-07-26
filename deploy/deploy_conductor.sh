#!/usr/bin/env bash
# Deploy conductor to Cloud Run (build image from its Dockerfile, then deploy).
# Usage: PROJECT=my-proj REGION=europe-west1 ./deploy/deploy_conductor.sh
# Reads env values from cloudrun/conductor/.env (create from .env.example).
set -euo pipefail

PROJECT="${PROJECT:-iawwai}"
REGION="${REGION:-europe-west1}"
SERVICE="${SERVICE:-conductor}"
IMAGE="gcr.io/$PROJECT/$SERVICE"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/cloudrun/conductor/.env"
[ -f "$ENV_FILE" ] || { echo "missing $ENV_FILE"; exit 1; }
set -a; source "$ENV_FILE"; set +a

# Every non-secret env var the service understands. Adding a var? Add it here.
VARS=(
  EXECUTION_MODE LOOP_ENABLED
  GCS_BUCKET CASES_PREFIX PERSIST_CASES
  INCLUDE_RECENT_OUTCOMES
  BYBIT_TRADING_URL BYBIT_TRADING_TOKEN BYBIT_TRADING_TIMEOUT AGENT_TRADING_URL
  MODEL_GATE MODEL_SYNTHESIS MODEL_REFLECTION
  WATCHLIST RADAR_ENABLED MAX_CANDIDATES_PER_TICK
  TICK_INTERVAL_MINUTES
  TIMEFRAMES KLINE_LIMIT
  RISK_FRACTION MAX_CONCURRENT_POSITIONS MAX_TOTAL_MARGIN_FRACTION
  MAX_AGGREGATE_OPEN_RISK MAX_LEVERAGE MAX_MARGIN_PERCENT
  SYMBOL_COOLDOWN_HOURS DAILY_LOSS_BREAKER_FRACTION WEEKLY_LOSS_BREAKER_FRACTION
  MIN_CONFIDENCE
  ORDER_TTL_MINUTES ORDER_MAX_DRIFT_ATR ORDER_RECONCILE_TIMEFRAME
  FRONTEND_CORS_ORIGINS
)

ENV_YAML="$(mktemp /tmp/conductor-env.XXXXXX.yaml)"
trap 'rm -f "$ENV_YAML"' EXIT

for v in "${VARS[@]}"; do
  val="${!v:-}"
  if [ -n "$val" ]; then
    # YAML single-quoted scalar; escape embedded single quotes
    val_escaped="${val//\'/\'\'}"
    echo "$v: '$val_escaped'" >> "$ENV_YAML"
  fi
done

# On Cloud Run the internal ticker stays OFF (Cloud Scheduler drives ticks);
# scale-to-zero would kill a background ticker anyway.
if ! grep -q '^TICK_INTERVAL_MINUTES:' "$ENV_YAML" >/dev/null 2>&1; then
  echo "TICK_INTERVAL_MINUTES: '0'" >> "$ENV_YAML"
fi

echo ">>> building $IMAGE"
gcloud builds submit "$REPO_ROOT" \
  --project "$PROJECT" \
  --config "$REPO_ROOT/deploy/cloudbuild-service.yaml" \
  --substitutions "_DOCKERFILE=cloudrun/conductor/Dockerfile,_IMAGE=$IMAGE"

echo ">>> deploying $SERVICE (secrets: ANTHROPIC_API_KEY)"
gcloud run deploy "$SERVICE" \
  --project "$PROJECT" \
  --region "$REGION" \
  --image "$IMAGE" \
  --port 8080 \
  --max-instances 1 \
  --min-instances 0 \
  --memory 512Mi \
  --timeout 600 \
  --no-allow-unauthenticated \
  --env-vars-file "$ENV_YAML" \
  --set-secrets "ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest" \
  --labels app=iaw,component=conductor

echo ">>> done. Next: ./deploy/setup_scheduler.sh to create the tick cron."
