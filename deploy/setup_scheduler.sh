#!/usr/bin/env bash
# Low-budget cloud cron: Cloud Scheduler -> POST conductor /v1/loop/tick.
# Scheduler jobs are free (first 3 per project); the conductor scales to zero
# between ticks, so you only pay for tick execution seconds.
#
# Usage:
#   PROJECT=my-proj REGION=europe-west1 [CRON="*/15 * * * *"] ./deploy/setup_scheduler.sh
set -euo pipefail

PROJECT="${PROJECT:-iawwai}"
REGION="${REGION:-europe-west1}"
SERVICE="${SERVICE:-conductor}"
JOB="${JOB:-conductor-tick}"
CRON="${CRON:-*/15 * * * *}"   # every 15 minutes — swing cadence
SA_NAME="${SA_NAME:-conductor-tick-invoker}"
SA_EMAIL="$SA_NAME@$PROJECT.iam.gserviceaccount.com"

CONDUCTOR_URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')"
[ -n "$CONDUCTOR_URL" ] || { echo "conductor service not found — deploy it first"; exit 1; }

echo ">>> service account for OIDC invocation"
gcloud iam service-accounts create "$SA_NAME" --project "$PROJECT" 2>/dev/null || true
gcloud run services add-iam-policy-binding "$SERVICE" \
  --project "$PROJECT" --region "$REGION" \
  --member "serviceAccount:$SA_EMAIL" \
  --role roles/run.invoker

echo ">>> scheduler job: $JOB ($CRON) -> $CONDUCTOR_URL/v1/loop/tick"
if gcloud scheduler jobs describe "$JOB" --project "$PROJECT" --location "$REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$JOB" \
    --project "$PROJECT" --location "$REGION" \
    --schedule "$CRON" \
    --uri "$CONDUCTOR_URL/v1/loop/tick" \
    --http-method POST \
    --oidc-service-account-email "$SA_EMAIL" \
    --oidc-token-audience "$CONDUCTOR_URL" \
    --attempt-deadline 540s
else
  gcloud scheduler jobs create http "$JOB" \
    --project "$PROJECT" --location "$REGION" \
    --schedule "$CRON" \
    --uri "$CONDUCTOR_URL/v1/loop/tick" \
    --http-method POST \
    --oidc-service-account-email "$SA_EMAIL" \
    --oidc-token-audience "$CONDUCTOR_URL" \
    --attempt-deadline 540s
fi

echo ">>> done. Pause with: gcloud scheduler jobs pause $JOB --location $REGION"
