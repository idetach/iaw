#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# deploy.sh — Push the metrics_margin stack to the GCP VM and start it
#
# Run from your LOCAL machine (not on the VM).
#
# Usage:
#   ./deploy/deploy.sh                          # uses defaults
#   VM_NAME=metrics-margin GCP_ZONE=europe-west1-b ./deploy/deploy.sh
#   ./deploy/deploy.sh restart                  # full restart
#   ./deploy/deploy.sh logs                     # tail logs
#   ./deploy/deploy.sh status                   # check containers
#   ./deploy/deploy.sh ssh                      # open SSH session
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

VM_NAME="${VM_NAME:-metrics-margin}"
GCP_ZONE="${GCP_ZONE:-europe-west1-b}"
REMOTE_DIR="/opt/metrics_margin"

SSH_CMD="gcloud compute ssh $VM_NAME --zone=$GCP_ZONE"
SCP_CMD="gcloud compute scp --zone=$GCP_ZONE"
DC="docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml"

ACTION="${1:-deploy}"

# ── Helper: run command on VM ──
vm_exec() {
  $SSH_CMD --command="$1"
}

# ── Helper: sync files to VM ──
sync_files() {
  echo "==> Syncing project files to $VM_NAME:$REMOTE_DIR ..."

  # Create a temp tarball excluding unnecessary files
  local tmptar="/tmp/metrics_margin_deploy.tar.gz"
  COPYFILE_DISABLE=1 tar -czf "$tmptar" \
    -C "$PROJECT_DIR" \
    --exclude='.DS_Store' \
    --exclude='._*' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.env' \
    --exclude='collector/backups/*' \
    --exclude='deploy/gcp-create.sh' \
    --exclude='deploy/vm-setup.sh' \
    --exclude='deploy/deploy.sh' \
    --exclude='docs' \
    --exclude='tests' \
    --exclude='README*.md' \
    --exclude='.env.example' \
    .

  # Upload and extract
  $SCP_CMD "$tmptar" "$VM_NAME:$REMOTE_DIR/deploy.tar.gz"
  vm_exec "cd $REMOTE_DIR && tar -xzf deploy.tar.gz && rm deploy.tar.gz"
  rm -f "$tmptar"

  echo "==> Files synced."
}

# ── Helper: ensure .env exists on VM ──
check_env() {
  if ! vm_exec "test -f $REMOTE_DIR/.env" 2>/dev/null; then
    echo ""
    echo "ERROR: .env file not found on VM at $REMOTE_DIR/.env"
    echo ""
    echo "Create it by running:"
    echo "  $SSH_CMD"
    echo "  nano $REMOTE_DIR/.env"
    echo ""
    echo "Or upload your local .env:"
    echo "  $SCP_CMD $PROJECT_DIR/.env $VM_NAME:$REMOTE_DIR/.env"
    echo ""
    exit 1
  fi
}

case "$ACTION" in
  deploy)
    sync_files
    check_env
    echo "==> Building and starting stack ..."
    vm_exec "cd $REMOTE_DIR && $DC up --build -d"
    echo ""
    echo "==> Waiting for services to start ..."
    sleep 5
    vm_exec "cd $REMOTE_DIR && $DC ps"

    STATIC_IP=$(gcloud compute instances describe "$VM_NAME" \
      --zone="$GCP_ZONE" \
      --format='value(networkInterfaces[0].accessConfigs[0].natIP)' 2>/dev/null || echo "???")
    echo ""
    echo "══════════════════════════════════════════════════════════"
    echo "  Deployed! Grafana: http://$STATIC_IP"
    echo "══════════════════════════════════════════════════════════"
    ;;

  restart)
    echo "==> Restarting stack ..."
    vm_exec "cd $REMOTE_DIR && $DC down && $DC up --build -d"
    sleep 5
    vm_exec "cd $REMOTE_DIR && $DC ps"
    ;;

  stop)
    echo "==> Stopping stack ..."
    vm_exec "cd $REMOTE_DIR && $DC down"
    ;;

  logs)
    vm_exec "cd $REMOTE_DIR && $DC logs -f --tail=100"
    ;;

  status)
    vm_exec "cd $REMOTE_DIR && $DC ps"
    ;;

  ssh)
    exec $SSH_CMD
    ;;

  env)
    echo "==> Uploading .env to VM ..."
    if [ ! -f "$PROJECT_DIR/.env" ]; then
      echo "ERROR: No local .env file found at $PROJECT_DIR/.env"
      exit 1
    fi
    $SCP_CMD "$PROJECT_DIR/.env" "$VM_NAME:$REMOTE_DIR/.env"
    echo "==> .env uploaded."
    ;;

  *)
    echo "Usage: $0 [deploy|restart|stop|logs|status|ssh|env]"
    echo ""
    echo "  deploy   Sync files and (re)start the stack (default)"
    echo "  restart  Stop and start the stack"
    echo "  stop     Stop the stack"
    echo "  logs     Tail logs from all services"
    echo "  status   Show container status"
    echo "  ssh      Open SSH session to the VM"
    echo "  env      Upload local .env to the VM"
    exit 1
    ;;
esac
