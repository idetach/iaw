#!/usr/bin/env bash
# Deploy web_app to Cloud Run (Vite build baked with VITE_* vars, nginx serve).
# Usage: PROJECT=my-proj REGION=europe-west1 ./deploy/deploy_web_app.sh
# Reads VITE_* values from web_app/.env — set them to the deployed service URLs
# (VITE_API_BASE_URL, VITE_AGENT_TRADING_URL, VITE_CONDUCTOR_URL) BEFORE deploy:
# Vite vars are build-time, not runtime.
set -euo pipefail

PROJECT="${PROJECT:?set PROJECT=<gcp project id>}"
REGION="${REGION:-europe-west1}"
SERVICE="${SERVICE:-iaw-web}"
IMAGE="gcr.io/$PROJECT/$SERVICE"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/web_app/.env"
[ -f "$ENV_FILE" ] || { echo "missing $ENV_FILE"; exit 1; }
set -a; source "$ENV_FILE"; set +a

SUBS="_IMAGE=$IMAGE"
for v in VITE_API_BASE_URL VITE_AGENT_TRADING_URL VITE_CONDUCTOR_URL \
         VITE_FIREBASE_API_KEY VITE_FIREBASE_AUTH_DOMAIN VITE_FIREBASE_PROJECT_ID \
         VITE_FIREBASE_STORAGE_BUCKET VITE_FIREBASE_MESSAGING_SENDER_ID \
         VITE_FIREBASE_APP_ID VITE_FIREBASE_MEASUREMENT_ID; do
  SUBS="$SUBS,_$v=${!v:-}"
done

echo ">>> building $IMAGE (VITE vars baked at build time)"
gcloud builds submit "$REPO_ROOT" \
  --project "$PROJECT" \
  --config "$REPO_ROOT/deploy/cloudbuild-web-app.yaml" \
  --substitutions "$SUBS"

echo ">>> deploying $SERVICE"
gcloud run deploy "$SERVICE" \
  --project "$PROJECT" \
  --region "$REGION" \
  --image "$IMAGE" \
  --port 8080 \
  --max-instances 2 \
  --min-instances 0 \
  --memory 256Mi \
  --allow-unauthenticated \
  --labels app=iaw,component=web

echo ">>> done."
