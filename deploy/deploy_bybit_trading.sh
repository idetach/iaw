#!/usr/bin/env bash
# Deploy bybit_trading to Cloud Run.
# Usage: PROJECT=my-proj REGION=europe-west1 ./deploy/deploy_bybit_trading.sh
# Reads env values from cloudrun/bybit_trading/.env.
set -euo pipefail

PROJECT="${PROJECT:?set PROJECT=<gcp project id>}"
REGION="${REGION:-europe-west1}"
SERVICE="${SERVICE:-bybit-trading}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/cloudrun/bybit_trading/.env"
[ -f "$ENV_FILE" ] || { echo "missing $ENV_FILE"; exit 1; }
set -a; source "$ENV_FILE"; set +a

# Non-secret env vars (BYBIT_API_KEY/SECRET go through Secret Manager).
# BYBIT_DEMO is the new demo-trading toggle — must reach the container.
VARS=(
  BYBIT_TESTNET BYBIT_DEMO BYBIT_CATEGORY
  BYBIT_TRADING_TOKEN
  FRONTEND_CORS_ORIGINS
  RADAR_PRICE_CHANGE_PCT_THRESHOLD RADAR_VOLUME_THRESHOLD_USDT RADAR_FUNDING_RATE_THRESHOLD
)

ENV_ARGS=""
for v in "${VARS[@]}"; do
  val="${!v:-}"
  [ -n "$val" ] && ENV_ARGS="${ENV_ARGS}${ENV_ARGS:+,}${v}=${val}"
done

IMAGE="gcr.io/$PROJECT/$SERVICE"
echo ">>> building $IMAGE"
gcloud builds submit "$REPO_ROOT" \
  --project "$PROJECT" \
  --config "$REPO_ROOT/deploy/cloudbuild-service.yaml" \
  --substitutions "_DOCKERFILE=cloudrun/bybit_trading/Dockerfile,_IMAGE=$IMAGE"

echo ">>> deploying $SERVICE to $PROJECT/$REGION (secrets: BYBIT_API_KEY, BYBIT_API_SECRET)"
gcloud run deploy "$SERVICE" \
  --project "$PROJECT" \
  --region "$REGION" \
  --image "$IMAGE" \
  --port 8080 \
  --max-instances 1 \
  --min-instances 0 \
  --memory 512Mi \
  --no-allow-unauthenticated \
  --set-env-vars "$ENV_ARGS" \
  --set-secrets "BYBIT_API_KEY=BYBIT_API_KEY:latest,BYBIT_API_SECRET=BYBIT_API_SECRET:latest" \
  --labels app=iaw,component=bybit-trading

echo ">>> done. Point the conductor's BYBIT_TRADING_URL at this service URL."
