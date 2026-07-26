#!/usr/bin/env bash
# Deploy web_app to Cloud Run (Vite build + Node static/proxy serve, ADR-0008).
# Usage: PROJECT=my-proj REGION=europe-west1 ./deploy/deploy_web_app.sh
#
# The browser talks to the conductor SAME-ORIGIN via this service's reverse
# proxy (/api/conductor/*), so VITE_CONDUCTOR_URL is forced to /api/conductor.
# The proxy needs the PRIVATE conductor URL at RUNTIME (CONDUCTOR_URL) and the
# Firebase project id (FIREBASE_PROJECT_ID) to verify user tokens.
set -euo pipefail

PROJECT="${PROJECT:-iawwai}"
REGION="${REGION:-europe-west1}"
SERVICE="${SERVICE:-iaw-web}"
CONDUCTOR_SERVICE="${CONDUCTOR_SERVICE:-conductor}"
IMAGE="gcr.io/$PROJECT/$SERVICE"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/web_app/.env"
[ -f "$ENV_FILE" ] || { echo "missing $ENV_FILE"; exit 1; }
set -a; source "$ENV_FILE"; set +a

# Resolve the private conductor URL for the runtime proxy target.
CONDUCTOR_URL="$(gcloud run services describe "$CONDUCTOR_SERVICE" \
  --project "$PROJECT" --region "$REGION" --format='value(status.url)')"
[ -n "$CONDUCTOR_URL" ] || { echo "conductor service not found — deploy it first"; exit 1; }

# Force same-origin conductor access through the proxy (overrides .env).
VITE_CONDUCTOR_URL="/api/conductor"

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

echo ">>> deploying $SERVICE (proxy -> $CONDUCTOR_URL)"
gcloud run deploy "$SERVICE" \
  --project "$PROJECT" \
  --region "$REGION" \
  --image "$IMAGE" \
  --port 8080 \
  --max-instances 2 \
  --min-instances 0 \
  --memory 256Mi \
  --allow-unauthenticated \
  --set-env-vars "CONDUCTOR_URL=$CONDUCTOR_URL,FIREBASE_PROJECT_ID=${VITE_FIREBASE_PROJECT_ID:-}" \
  --labels app=iaw,component=web

# Allow this service's runtime SA to invoke the private conductor (ADR-0008).
WEB_SA="$(gcloud run services describe "$SERVICE" \
  --project "$PROJECT" --region "$REGION" \
  --format='value(spec.template.spec.serviceAccountName)')"
if [ -z "$WEB_SA" ]; then
  PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
  WEB_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
fi
echo ">>> granting $WEB_SA run.invoker on $CONDUCTOR_SERVICE"
gcloud run services add-iam-policy-binding "$CONDUCTOR_SERVICE" \
  --project "$PROJECT" --region "$REGION" \
  --member="serviceAccount:$WEB_SA" \
  --role="roles/run.invoker"

echo ">>> done."
