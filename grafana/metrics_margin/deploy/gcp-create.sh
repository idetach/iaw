#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# gcp-create.sh — Provision GCP infrastructure for metrics_margin
#
# Prerequisites:
#   - gcloud CLI installed and authenticated (`gcloud auth login`)
#   - A GCP project already exists
#
# Usage:
#   ./deploy/gcp-create.sh                     # uses defaults
#   GCP_PROJECT=my-proj GCP_ZONE=europe-west1-b ./deploy/gcp-create.sh
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Configuration (override via env vars) ──
GCP_PROJECT="${GCP_PROJECT:?Set GCP_PROJECT to your Google Cloud project ID}"
GCP_ZONE="${GCP_ZONE:-europe-west1-b}"
GCP_REGION="${GCP_ZONE%-*}"
VM_NAME="${VM_NAME:-metrics-margin}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-small}"
BOOT_DISK_SIZE="${BOOT_DISK_SIZE:-20GB}"
STATIC_IP_NAME="${STATIC_IP_NAME:-metrics-margin-ip}"

echo "==> Using project: $GCP_PROJECT  zone: $GCP_ZONE"
gcloud config set project "$GCP_PROJECT"

# ── 1. Reserve static external IP ──
if gcloud compute addresses describe "$STATIC_IP_NAME" --region="$GCP_REGION" &>/dev/null; then
  echo "==> Static IP '$STATIC_IP_NAME' already exists"
else
  echo "==> Reserving static IP '$STATIC_IP_NAME' in $GCP_REGION ..."
  gcloud compute addresses create "$STATIC_IP_NAME" --region="$GCP_REGION"
fi

STATIC_IP=$(gcloud compute addresses describe "$STATIC_IP_NAME" \
  --region="$GCP_REGION" --format='value(address)')
echo "==> Static IP: $STATIC_IP  ← whitelist this in Binance API settings"

# ── 2. Firewall rules ──
for RULE in allow-http allow-https allow-ssh; do
  case $RULE in
    allow-http)
      PORT=80;  TAG=metrics-margin ;;
    allow-https)
      PORT=443; TAG=metrics-margin ;;
    allow-ssh)
      PORT=22;  TAG=metrics-margin ;;
  esac
  RULE_NAME="${VM_NAME}-${RULE}"
  if gcloud compute firewall-rules describe "$RULE_NAME" &>/dev/null; then
    echo "==> Firewall rule '$RULE_NAME' already exists"
  else
    echo "==> Creating firewall rule '$RULE_NAME' (tcp:$PORT) ..."
    gcloud compute firewall-rules create "$RULE_NAME" \
      --allow="tcp:$PORT" \
      --target-tags="$TAG" \
      --source-ranges="0.0.0.0/0" \
      --description="Allow inbound tcp:$PORT for $VM_NAME"
  fi
done

# ── 3. Create VM ──
if gcloud compute instances describe "$VM_NAME" --zone="$GCP_ZONE" &>/dev/null; then
  echo "==> VM '$VM_NAME' already exists"
else
  echo "==> Creating VM '$VM_NAME' ($MACHINE_TYPE, $BOOT_DISK_SIZE disk) ..."
  gcloud compute instances create "$VM_NAME" \
    --zone="$GCP_ZONE" \
    --machine-type="$MACHINE_TYPE" \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size="$BOOT_DISK_SIZE" \
    --boot-disk-type=pd-balanced \
    --address="$STATIC_IP_NAME" \
    --tags=metrics-margin \
    --metadata=startup-script='#!/bin/bash
      echo "VM created — run vm-setup.sh to install Docker"'
fi

echo ""
echo "══════════════════════════════════════════════════════════"
echo "  VM:        $VM_NAME"
echo "  Zone:      $GCP_ZONE"
echo "  Static IP: $STATIC_IP"
echo "  SSH:       gcloud compute ssh $VM_NAME --zone=$GCP_ZONE"
echo "══════════════════════════════════════════════════════════"
echo ""
echo "Next steps:"
echo "  1. Whitelist $STATIC_IP in your Binance API key settings"
echo "  2. SSH into the VM and run vm-setup.sh"
echo "  3. Run deploy.sh from your local machine to push the stack"
