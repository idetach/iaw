#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# migrate-data.sh — Full lift-and-shift of local TimescaleDB to GCP VM
#
# Creates a complete pg_dump (schema + data + TimescaleDB catalog)
# inside the local Docker container (PG16→PG16), uploads it to the VM,
# drops & recreates the remote database, and restores the full dump.
#
# Usage (from local machine):
#   ./deploy/migrate-data.sh
#
# Prerequisites:
#   - Local TimescaleDB container running
#   - GCP VM running with metrics_margin stack deployed
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Settings ──
LOCAL_CONTAINER="${LOCAL_CONTAINER:-metrics_margin_timescaledb}"
LOCAL_DB="${LOCAL_DB:-metrics_margin}"
LOCAL_USER="${LOCAL_USER:-metrics_margin}"

VM_NAME="${VM_NAME:-metrics-margin}"
GCP_ZONE="${GCP_ZONE:-europe-west1-b}"
REMOTE_DIR="/opt/metrics_margin"
DC="docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml"

SSH_CMD="gcloud compute ssh $VM_NAME --zone=$GCP_ZONE"
SCP_CMD="gcloud compute scp --zone=$GCP_ZONE"

DUMP_FILE="/tmp/metrics_margin_full.dump"

TABLES=(
  margin_pairs
  spot_klines
  margin_available_inventory_snapshots
  margin_price_index_snapshots
  isolated_margin_tier_snapshots
  cross_margin_collateral_ratio_snapshots
  risk_based_liquidation_ratio_snapshots
  derived_metrics
  config_change_events
)

echo "══════════════════════════════════════════════════════════"
echo "  Full DB migration: local → GCP VM"
echo "══════════════════════════════════════════════════════════"
echo ""

# ── Step 1: Verify local DB ──
echo "==> Checking local database ..."
docker exec "$LOCAL_CONTAINER" pg_isready -U "$LOCAL_USER" -d "$LOCAL_DB" >/dev/null 2>&1 \
  || { echo "ERROR: Local container '$LOCAL_CONTAINER' not running"; exit 1; }

echo "==> Local row counts:"
for t in "${TABLES[@]}"; do
  count=$(docker exec "$LOCAL_CONTAINER" \
    psql -U "$LOCAL_USER" -d "$LOCAL_DB" -t -A -c "SELECT COUNT(*) FROM $t;")
  printf "    %-50s %s rows\n" "$t" "$count"
done
echo ""

# ── Step 2: Full pg_dump inside local container ──
echo "==> Creating full database dump (inside container, PG16) ..."
docker exec "$LOCAL_CONTAINER" \
  pg_dump -U "$LOCAL_USER" -d "$LOCAL_DB" \
    -Fc --no-owner --no-privileges \
    -f /tmp/db.dump

docker cp "$LOCAL_CONTAINER":/tmp/db.dump "$DUMP_FILE"
docker exec "$LOCAL_CONTAINER" rm -f /tmp/db.dump

DUMP_SIZE=$(du -h "$DUMP_FILE" | cut -f1)
echo "==> Dump created: $DUMP_SIZE"

# ── Step 3: Upload to VM ──
echo "==> Uploading dump to VM ..."
$SCP_CMD "$DUMP_FILE" "$VM_NAME:/tmp/db.dump"
echo "==> Upload complete."
rm -f "$DUMP_FILE"

# ── Step 4: Restore on remote ──
echo ""
echo "==> Restoring on remote VM ..."
$SSH_CMD --command="
  set -e
  cd $REMOTE_DIR

  POSTGRES_USER=\$(grep '^POSTGRES_USER=' .env | cut -d= -f2)
  POSTGRES_DB=\$(grep '^POSTGRES_DB=' .env | cut -d= -f2)
  POSTGRES_PASSWORD=\$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2)

  # Stop collector and grafana so nothing writes to the DB
  echo '==> Stopping collector & grafana ...'
  $DC stop collector grafana 2>/dev/null || true

  # Copy dump into the timescaledb container
  docker cp /tmp/db.dump metrics_margin_timescaledb:/tmp/db.dump

  # Drop and recreate the database
  echo '==> Dropping and recreating database ...'
  docker exec -e PGPASSWORD=\"\$POSTGRES_PASSWORD\" metrics_margin_timescaledb \
    psql -U \"\$POSTGRES_USER\" -d postgres -c \
    \"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='\$POSTGRES_DB' AND pid<>pg_backend_pid();\" 2>/dev/null || true

  docker exec -e PGPASSWORD=\"\$POSTGRES_PASSWORD\" metrics_margin_timescaledb \
    psql -U \"\$POSTGRES_USER\" -d postgres -c \"DROP DATABASE IF EXISTS \$POSTGRES_DB;\"

  docker exec -e PGPASSWORD=\"\$POSTGRES_PASSWORD\" metrics_margin_timescaledb \
    psql -U \"\$POSTGRES_USER\" -d postgres -c \"CREATE DATABASE \$POSTGRES_DB OWNER \$POSTGRES_USER;\"

  # Enable extensions before restore
  docker exec -e PGPASSWORD=\"\$POSTGRES_PASSWORD\" metrics_margin_timescaledb \
    psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -c \
    \"CREATE EXTENSION IF NOT EXISTS timescaledb; CREATE EXTENSION IF NOT EXISTS pgcrypto;\"

  # Restore the full dump
  echo '==> Running pg_restore ...'
  docker exec -e PGPASSWORD=\"\$POSTGRES_PASSWORD\" metrics_margin_timescaledb \
    pg_restore -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" \
      --no-owner --no-privileges \
      --clean --if-exists \
      /tmp/db.dump 2>&1 | tail -5 || true

  # Verify row counts
  echo ''
  echo '==> Remote row counts after restore:'
  docker exec -e PGPASSWORD=\"\$POSTGRES_PASSWORD\" metrics_margin_timescaledb \
    psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -t -A -c \"
      SELECT 'margin_pairs', COUNT(*) FROM margin_pairs
      UNION ALL SELECT 'spot_klines', COUNT(*) FROM spot_klines
      UNION ALL SELECT 'margin_available_inventory_snapshots', COUNT(*) FROM margin_available_inventory_snapshots
      UNION ALL SELECT 'margin_price_index_snapshots', COUNT(*) FROM margin_price_index_snapshots
      UNION ALL SELECT 'isolated_margin_tier_snapshots', COUNT(*) FROM isolated_margin_tier_snapshots
      UNION ALL SELECT 'cross_margin_collateral_ratio_snapshots', COUNT(*) FROM cross_margin_collateral_ratio_snapshots
      UNION ALL SELECT 'risk_based_liquidation_ratio_snapshots', COUNT(*) FROM risk_based_liquidation_ratio_snapshots
      UNION ALL SELECT 'derived_metrics', COUNT(*) FROM derived_metrics
      UNION ALL SELECT 'config_change_events', COUNT(*) FROM config_change_events
      ORDER BY 1;
    \"

  # Restart the full stack
  echo '==> Restarting all services ...'
  $DC up -d

  # Cleanup
  rm -f /tmp/db.dump
  docker exec metrics_margin_timescaledb rm -f /tmp/db.dump
"

echo ""
echo "══════════════════════════════════════════════════════════"
echo "  Migration complete!"
echo "  Verify in Grafana: http://$(gcloud compute instances describe $VM_NAME \
  --zone=$GCP_ZONE --format='value(networkInterfaces[0].accessConfigs[0].natIP)' 2>/dev/null):3005"
echo "══════════════════════════════════════════════════════════"
