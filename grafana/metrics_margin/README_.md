# metrics_margin

`metrics_margin` is a self-hosted Grafana + TimescaleDB + Python collector project for tracking Binance exchange-level margin pool stress proxies versus spot price for selected assets.

It focuses on Binance margin pool availability, not your personal account balances or liabilities.

## What it collects

- `GET /sapi/v1/margin/available-inventory`
- `GET /sapi/v1/margin/priceIndex`
- `GET /sapi/v1/margin/isolatedMarginTier`
- `GET /sapi/v1/margin/crossMarginCollateralRatio`
- `GET /sapi/v1/margin/risk-based-liquidation-ratio`
- `GET /api/v3/klines`

## Architecture

- `collector/`
  - Python 3.12 collector using APScheduler
  - Binance adapter with HMAC signing for `USER_DATA` endpoints
  - Designed around an exchange adapter interface so Bybit can be added later
- `sql/`
  - PostgreSQL / TimescaleDB schema
- `grafana/provisioning/`
  - datasource, dashboard, and alert provisioning
- `grafana/dashboards/`
  - ready-made dashboard JSON
- `tests/`
  - basic transform/calculation tests

## Data model

Tables created:

- `spot_klines`
- `margin_available_inventory_snapshots`
- `margin_price_index_snapshots`
- `isolated_margin_tier_snapshots`
- `cross_margin_collateral_ratio_snapshots`
- `risk_based_liquidation_ratio_snapshots`
- `derived_metrics`
- `config_change_events`

Each snapshot stores:

- `collected_at`
- `source endpoint`
- `request parameters`
- `raw JSON payload`
- parsed columns
- `asset` and/or `symbol`

## Formulas used

### Borrow-pressure proxy

Default method: `negative inventory z-score`

For hourly resampled available inventory series `I_t`:

- rolling mean: `mean(I)` over the lookback window
- rolling stddev: `std(I)` over the lookback window
- inventory z-score: `z_t = (I_t - mean(I)) / std(I)`
- stress proxy: `stress_t = -z_t`

Interpretation:

- lower-than-normal inventory produces a higher stress score
- higher-than-normal inventory produces a lower stress score
- this is a proxy for tighter platform borrow supply, not an exact borrowed amount

### Normalized comparison

Both price and inventory are normalized to `100` at the start of the displayed range:

- `normalized_t = (x_t / x_0) * 100`

Interpretation:

- values above `100` are above the range start
- values below `100` are below the range start
- this makes divergence/convergence visually obvious on one panel

### Rolling correlation

The dashboard uses derived metrics based on hourly aligned series.

- price returns: `r_price_t = price_t / price_{t-1} - 1`
- inventory changes: `r_inv_t = inventory_t / inventory_{t-1} - 1`
- rolling correlation: `corr(r_price, r_inv)` over the selected window

Implemented windows:

- `24h rolling correlation`
- `7d rolling correlation`

## Configuration change tracking

The collector stores periodic snapshots for configuration-style endpoints and writes a row into `config_change_events` whenever the parsed payload changes from the previous snapshot.

These events are surfaced in Grafana as annotations and as a table.

## Requirements

- Docker Compose
- Binance API key and secret in `.env`
- Margin permissions enabled for the key if you want signed margin endpoints to succeed

If margin permissions are missing, the collector logs warnings and continues collecting public data where possible.

## Quick start

1. Copy environment file:

```bash
cp grafana/metrics_margin/.env.example grafana/metrics_margin/.env
```

2. Fill in Binance credentials in `grafana/metrics_margin/.env`

3. Start the stack:

```bash
docker compose -f grafana/metrics_margin/docker-compose.yml --env-file grafana/metrics_margin/.env up --build
```

4. Open Grafana:

```text
http://localhost:3005
```

Default credentials are controlled by:

- `GRAFANA_ADMIN_USER`
- `GRAFANA_ADMIN_PASSWORD`

## Operations

All commands assume you are in the repo root (`iaw/`).

### start.sh commands

```bash
./grafana/metrics_margin/start.sh up        # build and start all services
./grafana/metrics_margin/start.sh down      # stop and remove all containers
./grafana/metrics_margin/start.sh restart   # full down + up --build cycle
./grafana/metrics_margin/start.sh logs      # tail logs from all services (Ctrl+C to stop)
./grafana/metrics_margin/start.sh status    # show running containers
```

### Restart individual containers

```bash
docker restart metrics_margin_collector
docker restart metrics_margin_grafana
docker restart metrics_margin_timescaledb
```

> **Note:** `docker restart` preserves volume mounts and picks up code changes for the collector (Python is mounted read-only). For docker-compose config changes (new volumes, env vars, ports), use `start.sh restart` instead.

### Logs

```bash
# Last 20 lines from collector
docker logs metrics_margin_collector 2>&1 | tail -20

# Follow live logs
docker logs -f metrics_margin_collector

# Logs from the last 2 minutes
docker logs metrics_margin_collector --since 2m 2>&1

# Grafana logs
docker logs metrics_margin_grafana --since 5m 2>&1 | tail -20
```

### Filtered debug logs

```bash
# Warnings and errors only
docker logs metrics_margin_collector 2>&1 | grep -iE "WARNING|ERROR" | tail -20

# Startup and health check
docker logs metrics_margin_collector 2>&1 | grep -iE "collector_started|schema_applied|loaded_from_db|backfill_skipped" | tail -10

# Polling cycle health
docker logs metrics_margin_collector --since 10m 2>&1 | grep -iE "inventory_polled|cross_collateral|isolated_tiers|spot_klines_polled" | tail -15

# Check for known issues
docker logs metrics_margin_collector --since 10m 2>&1 | grep -iE "FutureWarning|Pair not found|permission|rate.limit" | tail -15

# Backfill progress (during initial startup)
docker logs metrics_margin_collector 2>&1 | grep "backfilled" | tail -10
```

### Database queries

```bash
# Connect to TimescaleDB
docker exec -it metrics_margin_timescaledb psql -U metrics_margin -d metrics_margin

# Or run a one-off query
docker exec metrics_margin_timescaledb psql -U metrics_margin -d metrics_margin -c "SELECT COUNT(*) FROM spot_klines;"
```

Useful queries:

```sql
-- How many symbols are tracked
SELECT COUNT(*) FROM margin_pairs WHERE is_margin_trade = TRUE AND quote_asset IN ('USDC','USDT','FDUSD');

-- Latest kline per symbol
SELECT symbol, MAX(close_time) AS latest FROM spot_klines GROUP BY symbol ORDER BY latest DESC LIMIT 10;

-- Current stress regime for a symbol
SELECT collected_at, metric_value, metadata FROM derived_metrics
WHERE symbol = 'BTCUSDC' AND metric_name = 'stress_regime'
ORDER BY collected_at DESC LIMIT 1;

-- Recent inventory for an asset
SELECT collected_at, available_inventory::double precision
FROM margin_available_inventory_snapshots
WHERE asset = 'BTC' ORDER BY collected_at DESC LIMIT 5;

-- Config changes in the last 24h
SELECT collected_at, source_table, event_type, summary
FROM config_change_events WHERE collected_at > NOW() - INTERVAL '24 hours'
ORDER BY collected_at DESC;

-- Table sizes
SELECT relname AS table, pg_size_pretty(pg_total_relation_size(relid)) AS size
FROM pg_catalog.pg_statio_user_tables ORDER BY pg_total_relation_size(relid) DESC;
```

### Data retention / cleanup

```sql
-- Delete klines older than 30 days
SELECT drop_chunks('spot_klines', older_than => INTERVAL '30 days');

-- Delete derived metrics older than 30 days
SELECT drop_chunks('derived_metrics', older_than => INTERVAL '30 days');

-- Delete inventory snapshots older than 30 days
SELECT drop_chunks('margin_available_inventory_snapshots', older_than => INTERVAL '30 days');
```

### Volume management

```bash
# List volumes
docker volume ls | grep metrics_margin

# Danger: wipe all data and start fresh
./grafana/metrics_margin/start.sh down
docker volume rm metrics_margin_timescaledb_data metrics_margin_grafana_data
./grafana/metrics_margin/start.sh up
```

## Local dev workflow

### Run tests

```bash
python -m pytest grafana/metrics_margin/tests
```

### Collector-only local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r grafana/metrics_margin/collector/requirements.txt
export $(grep -v '^#' grafana/metrics_margin/.env | xargs)
python -m app.main
```

Run that from `grafana/metrics_margin/collector` as the working directory.

## Ports

- Grafana: `3005`
- TimescaleDB: `5434`

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Collector exits immediately | TimescaleDB not ready | Check `docker logs metrics_margin_timescaledb`. The healthcheck should gate startup, but if the DB volume is corrupted, wipe and recreate. |
| `backfill_failed` for many symbols | Binance rate limiting | Reduce `BACKFILL_HOURS` in `.env` or increase `RETRY_BACKOFF_SECONDS`. The collector sleeps 250ms between symbols. |
| Dashboard shows "No data" | Wrong asset/symbol selected | Check the asset dropdown. Some assets only have USDC pairs. Also verify data exists: `SELECT COUNT(*) FROM spot_klines WHERE symbol = 'BTCUSDC';` |
| `Pair not found` in logs | Symbol doesn't support isolated margin | Expected for ~30% of symbols. Logged at debug level, safe to ignore. |
| Grafana login fails | Wrong credentials | Check `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` in `.env`. Default is `admin`/`admin`. |
| Stale data after restart | Collector still backfilling | Check `docker logs metrics_margin_collector 2>&1 \| grep backfilled \| tail -5`. Backfill of 267 symbols takes ~2 minutes. |
| `permission denied` on Binance endpoints | API key missing margin perms | Enable margin permissions in Binance API management. The collector continues with public data if perms are missing. |

## Screenshot placeholder

Save a screenshot after startup here if you want to document the running dashboard:

```text
grafana/metrics_margin/docs/screenshot-dashboard.png
```

## Notes and assumptions

- Binance historical price series uses spot klines as the authoritative time series.
- `priceIndex` is treated as live/reference data and stored as snapshots.
- `available-inventory` is treated as exchange/platform pool availability.
- It is a stress proxy, not a direct exchange-wide borrowed amount.
- Config endpoints are naturally snapshot-oriented, so the project persists periodic snapshots and change events.

## Future extension

A minimal exchange adapter abstraction is already in place under `collector/app/exchanges/` so Bybit can be added later without rewriting the collector orchestration.
