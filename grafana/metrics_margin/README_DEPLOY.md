# Deploying metrics_margin to Google Cloud (Compute Engine)

All three services (TimescaleDB, Collector, Grafana) run on a single GCP Compute Engine VM via Docker Compose. A reserved static IP is used for Binance API whitelisting.

## Architecture

```
┌──────────────────────────────────────────────────────┐
│   Google Compute Engine  (e2-small, ~$15-20/month)   │
│   Static IP: 34.x.x.x  (whitelisted on Binance)     │
│                                                      │
│   ┌──────────────┐  ┌──────────────┐  ┌───────────┐ │
│   │  TimescaleDB │◄─┤  Collector   │  │  Grafana  │ │
│   │  :5432       │  │  (Python)    │  │  :3005    │ │
│   └──────────────┘  └──────────────┘  └───────────┘ │
│         ▲                                    │       │
│         └────────────────────────────────────┘       │
│                (internal Docker network)              │
│                                                      │
│   UFW: only 22/tcp + 3005/tcp open                   │
└──────────────────────────────────────────────────────┘
```

## Prerequisites

- **gcloud CLI** installed and authenticated (`gcloud auth login`)
- An existing **GCP project** (set via `GCP_PROJECT` env var)
- Your **`.env`** file with production credentials (see `.env.example`)
- Binance API key that supports IP whitelisting

## Files overview

```
deploy/
  gcp-create.sh              # Step 1: Provision GCP infra (IP, firewall, VM)
  vm-setup.sh                # Step 2: Bootstrap VM (Docker, UFW, swap)
  deploy.sh                  # Step 3+: Push code & manage the stack
  docker-compose.prod.yml    # Production overrides (restart: always)
```

---

## Step 1: Provision GCP infrastructure

Run from your **local machine**:

```bash
cd grafana/metrics_margin

# Set your GCP project ID (required)
export GCP_PROJECT="your-gcp-project-id"

# Optional overrides (defaults shown):
# export GCP_ZONE="europe-west1-b"
# export VM_NAME="metrics-margin"
# export MACHINE_TYPE="e2-small"
# export BOOT_DISK_SIZE="20GB"

./deploy/gcp-create.sh

# Optional: if necessary to change firewall, for example add ports for Caddy: 
gcloud compute firewall-rules create metrics-margin-allow-http --allow=tcp:80 --target-tags=metrics-margin --source-ranges=0.
-rules create metrics-margin-allow-https --allow=tcp:443 --target-tags=metrics-margin --source-ranges=0.0.0.0/0 --description="Allow HTTPS for Caddy" 2>&1

# Optional: and then update UFW on VM and deploy: 
gcloud compute ssh metrics-margin --zone=europe-west1-b --command='sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw deny 3005/tcp && sudo ufw status'

# Optional: then deploy after these changes: 
./deploy/deploy.sh
```

This script:
1. Reserves a **static external IP** address
2. Creates **firewall rules** for SSH (22) and Grafana (3005)
3. Creates an **e2-small VM** with Ubuntu 22.04 and the static IP attached

Output will show the static IP — **save it for the next step**.

## Step 2: Whitelist the static IP on Binance

1. Go to [Binance API Management](https://www.binance.com/en/my/settings/api-management)
2. Select your API key
3. Click **Edit restrictions** → **IP access restrictions**
4. Add the static IP printed by `gcp-create.sh`
5. Save

## Step 3: Bootstrap the VM

SSH into the VM and run the setup script:

```bash
# SSH into the VM
gcloud compute ssh metrics-margin --zone=europe-west1-b

# On the VM: download and run setup (or scp it first)
# Option A: copy-paste the script
sudo bash
# ... paste contents of deploy/vm-setup.sh ...

# Option B: from local machine, scp then run
gcloud compute scp deploy/vm-setup.sh metrics-margin:/tmp/ --zone=europe-west1-b
gcloud compute ssh metrics-margin --zone=europe-west1-b --command="sudo bash /tmp/vm-setup.sh"
```

This script installs:
- Docker CE + Docker Compose plugin
- UFW firewall (ports 22, 3005 only)
- 2 GB swap file (useful for e2-small with 2 GB RAM)
- Project directory at `/opt/metrics_margin`

**Important:** Log out and back in after setup for Docker group membership.

## Step 4: Upload .env file

The `.env` file contains secrets and is **never synced** by `deploy.sh`. Upload it once:

```bash
# From local machine
./deploy/deploy.sh env
```

Or manually:

```bash
gcloud compute scp .env metrics-margin:/opt/metrics_margin/.env --zone=europe-west1-b
```

Verify the `.env` has production-ready values:

```env
POSTGRES_DB=metrics_margin
POSTGRES_USER=metrics_margin
POSTGRES_PASSWORD=<strong-random-password>
POSTGRES_HOST=timescaledb
POSTGRES_PORT=5432

GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=<strong-random-password>

TG_IAW_METRICS_ALERTS_BOT_TOKEN=<your-bot-token>
TG_IAW_METRICS_ALERTS_BOT_CHAT_ID=<your-chat-id>

PRICE_POLL_SECONDS=300
INVENTORY_POLL_SECONDS=900
CONFIG_POLL_SECONDS=3600
BACKFILL_HOURS=168
PRICE_KLINE_INTERVAL=5m
REQUEST_TIMEOUT_SECONDS=20
MAX_RETRIES=4
RETRY_BACKOFF_SECONDS=1.5
LOG_LEVEL=INFO
APP_NAME=metrics_margin
```

## Step 5: Deploy the stack

```bash
# From local machine
./deploy/deploy.sh
```

This will:
1. Create a tarball of the project (excluding `.env`, tests, docs)
2. Upload it to the VM at `/opt/metrics_margin`
3. Run `docker compose up --build -d` with the production override
4. Print the Grafana URL

First deploy takes 2-3 minutes (building the collector image). Subsequent deploys are faster due to Docker layer caching.

## Managing the stack

All commands run from your **local machine** via `deploy/deploy.sh`:

```bash
./deploy/deploy.sh deploy    # Sync files and (re)start (default)
./deploy/deploy.sh restart   # Full stop + start
./deploy/deploy.sh stop      # Stop all containers
./deploy/deploy.sh logs      # Tail logs from all services
./deploy/deploy.sh status    # Show container status
./deploy/deploy.sh ssh       # Open SSH session to VM
./deploy/deploy.sh env       # Upload local .env to VM
```

Override VM name or zone:

```bash
VM_NAME=metrics-margin GCP_ZONE=europe-west1-b ./deploy/deploy.sh status
```

## Verify deployment

1. **Check containers:**
   ```bash
   ./deploy/deploy.sh status
   ```
   All three services should show `Up` and `(healthy)` for timescaledb.

2. **Open Grafana:**
   ```
   http://<STATIC_IP>:3005
   ```
   Log in with the `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` from `.env`.

3. **Check collector logs:**
   ```bash
   ./deploy/deploy.sh logs
   ```
   Look for successful Binance API calls and DB inserts.

## Granting readonly access

### Public dashboard (no login required, live data)

1. Open the dashboard in Grafana
2. **Share** → **Public dashboard**
3. Toggle **Enable public dashboard**
4. Copy the public URL

### Viewer users (login required)

1. **Administration** → **Users** → **Invite**
2. Enter email, set role to **Viewer**
3. Click **Invite**

### Public snapshot (static, point-in-time)

1. Open dashboard → **Share** → **Snapshot**
2. Set expiration → **Publish**
3. Copy URL (does not update with live data)

## Backups

TimescaleDB data lives in a Docker volume on the VM's boot disk. To back up:

```bash
# SSH into VM
./deploy/deploy.sh ssh

# Dump the database
docker exec metrics_margin_timescaledb \
  pg_dump -U metrics_margin -d metrics_margin -Fc > /opt/metrics_margin/backup_$(date +%Y%m%d).dump
```

To restore:

```bash
docker exec -i metrics_margin_timescaledb \
  pg_restore -U metrics_margin -d metrics_margin --clean < /opt/metrics_margin/backup_20250415.dump
```

Consider adding a cron job on the VM for automated backups:

```bash
# On the VM
crontab -e
# Add: daily backup at 3am
0 3 * * * docker exec metrics_margin_timescaledb pg_dump -U metrics_margin -d metrics_margin -Fc > /opt/metrics_margin/backup_$(date +\%Y\%m\%d).dump && find /opt/metrics_margin -name 'backup_*.dump' -mtime +7 -delete
```

## Cost estimate

| Resource | Monthly cost |
|----------|-------------|
| Compute Engine e2-small (2 vCPU, 2 GB) | ~$15-18 |
| 20 GB pd-balanced boot disk | ~$2 |
| Static external IP (attached to running VM) | Free |
| **Total** | **~$17-20/month** |

> Static IPs are free when attached to a running VM. Charged ~$3/month if reserved but unattached.

## Teardown

To remove all GCP resources:

```bash
export GCP_PROJECT="your-gcp-project-id"
GCP_ZONE="europe-west1-b"
GCP_REGION="${GCP_ZONE%-*}"

# Stop and delete VM (destroys all data!)
gcloud compute instances delete metrics-margin --zone=$GCP_ZONE

# Release static IP
gcloud compute addresses delete metrics-margin-ip --region=$GCP_REGION

# Delete firewall rules
gcloud compute firewall-rules delete metrics-margin-allow-grafana
gcloud compute firewall-rules delete metrics-margin-allow-ssh
```

## Troubleshooting

**Collector can't reach Binance API:**
- Verify the static IP is whitelisted in Binance settings
- Check: `./deploy/deploy.sh ssh` then `curl -s https://api.binance.com/api/v3/ping`

**Grafana not accessible:**
- Check UFW: `sudo ufw status` (port 3005 must be open)
- Check GCP firewall: `gcloud compute firewall-rules list --filter="name:metrics-margin"`
- Check container: `docker logs metrics_margin_grafana`

**TimescaleDB out of disk:**
- Check disk: `df -h`
- Resize boot disk in GCP Console and expand filesystem:
  ```bash
  sudo growpart /dev/sda 1
  sudo resize2fs /dev/sda1
  ```

**Containers not starting after VM reboot:**
- Docker daemon should auto-start. Verify: `systemctl is-enabled docker`
- Production compose uses `restart: always` — containers auto-recover

**Track only major selected assets:**
```bash
gcloud compute ssh metrics-margin --zone=europe-west1-b --command="cd /opt/metrics_margin && docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml stop collector && echo 'TRACKED_SYMBOLS=BTCUSDC,ETHUSDC,SOLUSDC,BNBUSDC,XRPUSDC,DOGEUSDC,ADAUSDC,AVAXUSDC,LINKUSDC,LTCUSDC' >> .env && docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d collector"
```

**Change polling interval example command gcloud:**
```bash
gcloud compute ssh metrics-margin --zone=europe-west1-b --command="cd /opt/metrics_margin && docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml stop collector && sed -i 's/PRICE_POLL_SECONDS=300/PRICE_POLL_SECONDS=900/' .env && docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d collector"
```

**Diagnose vps resources:**
```bash
gcloud compute ssh metrics-margin --zone=europe-west1-b --command="echo '=== Memory ===' && free -h && echo '' && echo '=== CPU ===' && nproc && echo '' && echo '=== Docker stats (snapshot) ===' && docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}' && echo '' && echo '=== Swap ===' && swapon --show && echo '' && echo '=== Load average ===' && uptime"
```

**Upgrade vps resources:**
```bash
gcloud compute instances stop metrics-margin --zone=europe-west1-b && gcloud compute instances set-machine-type metrics-margin --zone=europe-west1-b --machine-type=e2-medium && gcloud compute instances start metrics-margin --zone=europe-west1-b && echo "=== Resized and restarted ==="
```

**Verify vps resources (expected zero swap usage on e2-medium):**
```bash
sleep 20 && gcloud compute ssh metrics-margin --zone=europe-west1-b --command="echo '=== Machine Type ===' && curl -s -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/machine-type 2>/dev/null | awk -F/ '{print \$NF}' && echo '' && echo '=== Memory ===' && free -h && echo '' && echo '=== Containers ===' && docker ps --format 'table {{.Names}}\t{{.Status}}'"
```

**Check swap usage:**
```bash
sleep 120 && gcloud compute ssh metrics-margin --zone=europe-west1-b --command="docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}' && echo '' && docker logs metrics_margin_collector --tail=20 2>&1 | grep -E 'skipped|executed|backfill_skipped|Running job|collector_started'"
```

**Check backfill status (no backfill shall be done if db has been migrated in 15 min):**
```bash
sleep 300 && gcloud compute ssh metrics-margin --zone=europe-west1-b --command="docker logs metrics_margin_collector --tail=30 2>&1 | grep -E 'skipped|executed|Running job|collector_started|polled'"

gcloud compute ssh metrics-margin --zone=europe-west1-b --command="docker logs metrics_margin_collector --tail=50 2>&1"
```

**Check gap in time series data and vps status:**
```bash
gcloud compute ssh metrics-margin --zone=europe-west1-b --command="docker exec metrics_margin_timescaledb psql -U metrics_margin -d metrics_margin -c \"
SELECT 'inventory' AS table_name, MIN(collected_at) AS oldest, MAX(collected_at) AS newest, COUNT(*) AS rows FROM margin_available_inventory_snapshots
UNION ALL SELECT 'klines', MIN(close_time), MAX(close_time), COUNT(*) FROM spot_klines
UNION ALL SELECT 'price_index', MIN(collected_at), MAX(collected_at), COUNT(*) FROM margin_price_index_snapshots
UNION ALL SELECT 'derived', MIN(collected_at), MAX(collected_at), COUNT(*) FROM derived_metrics
ORDER BY 1;
\""

gcloud compute ssh metrics-margin --zone=europe-west1-b --command="docker exec metrics_margin_timescaledb psql -U metrics_margin -d metrics_margin -c \"
SELECT time_bucket('1 hour', collected_at) AS hour, COUNT(*) AS rows
FROM margin_available_inventory_snapshots
WHERE collected_at >= NOW() - INTERVAL '24 hours'
GROUP BY hour ORDER BY hour;
\""

gcloud compute ssh metrics-margin --zone=europe-west1-b --command="docker logs metrics_margin_collector --tail=10 2>&1 | grep -E 'skipped|executed|Running|polled'"
```

**Pricing of higher capacity vps:**
- e2-medium: 2 vCPUs, 4 GB RAM, 10 GB SSD, $27/month
- e2-standard-2: 2 vCPUs, 8 GB RAM, 10 GB SSD, $36/month
- e2-standard-4: 4 vCPUs, 16 GB RAM, 10 GB SSD, $72/month
- e2-standard-8: 8 vCPUs, 32 GB RAM, 10 GB SSD, $144/month
- e2-standard-16: 16 vCPUs, 64 GB RAM, 10 GB SSD, $288/month

```bash
gcloud compute machine-types list --zones=europe-west1-b --filter="name:(e2-standard-2 OR n2d-standard-2 OR n2d-highcpu-2 OR c3d-standard-2 OR t2d-standard-2)" --format="table(name,guestCpus,memoryMb,description)"
```

**Logs via gcloud (collector only):**
```bash
gcloud compute ssh metrics-margin --zone=europe-west1-b -- \
  "cd /opt/metrics_margin && docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml logs -f --tail=50 collector"
```


