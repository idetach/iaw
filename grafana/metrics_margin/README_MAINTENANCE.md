# Maintenance Guide

## Rewrite historical rolling correlation rows

This guide covers the one-off maintenance flow for rewriting historical correlation rows in `derived_metrics` so the `corr_24h` and `corr_7d` chart lines match the current collector logic.

### Scope

The maintenance utility affects only these metric names:

- `rolling_corr_price_vs_inventory_24h`
- `rolling_corr_price_vs_inventory_7d`

and only rows with:

- `collected_at < 2026-04-06 11:37:59-03:00`
- equivalent UTC cutoff: `2026-04-06 08:37:59+00:00`

The backup cutoff stays at the original timestamp above.

The rewrite flow uses an additional delta:

- `CUTOFF_DELTA = 45 minutes`
- effective rewrite cutoff: `2026-04-06 09:22:59+00:00`

It does not modify:

- `margin_available_inventory_snapshots`
- `spot_klines`
- `stress_proxy_zinv`
- `stress_regime`
- `normalized_price_100`
- `normalized_inventory_100`
- Grafana dashboards

## Files involved

- Maintenance script: `collector/app/maintenance/rewrite_corr_history.py`
- Backup directory: `collector/backups/`
- Collector bind mount: `./collector/backups:/app/backups`

## Script modes

The maintenance utility supports three modes:

- `backup`
- `rewrite`
- `restore`

Run it inside the collector container with:

```bash
python -m app.maintenance.rewrite_corr_history <mode>
```

## Prerequisite

If the collector container has not yet been recreated after the `/app/backups` mount was added, recreate it first:

```bash
docker compose up -d --force-recreate collector
```

Run this from:

```bash
/Users/juril/Developer/iaw/grafana/metrics_margin
```

## Step 1: Create backup

Create a JSON backup of the targeted pre-cutoff correlation rows:

```bash
docker exec metrics_margin_collector python -m app.maintenance.rewrite_corr_history backup
```

Expected result:

- a file is written under `collector/backups/`
- filename example:

```bash
collector/backups/derived_metrics_corr_pre_20260406T083759Z_20260406T085819Z.json
```

The backup contains:

- cutoff + 03:00
- UTC cutoff
- rewrite UTC cutoff
- row count
- original rows for restore

## Step 2: Rewrite old rows

Rewrite only the targeted historical correlation rows using the current correlation logic:

```bash
docker exec metrics_margin_collector python -m app.maintenance.rewrite_corr_history rewrite
```

Expected output example:

```bash
rewrite_complete pairs=204 rows_rewritten=0 corr_24h_points=96 corr_7d_points=672 cutoff_utc=2026-04-06T08:37:59+00:00
```

### Meaning of `rows_rewritten=0`

If `rows_rewritten=0`, the script still deleted the targeted old rows before the cutoff, but the current logic did not produce replacement rows for that historical period.

With `CUTOFF_DELTA = 30 minutes`, the rewrite step recomputes using source data available up to 30 minutes later than the original backup cutoff, while the backup still preserves the original pre-cutoff rows.

This can happen when correlation is now configured with strict full-window behavior:

- `corr_24h` requires a full 24h window
- `corr_7d` requires a full 7d window

With strict logic, older pre-cutoff data may no longer qualify to produce any historical rows.

## Step 3: Restore from backup

If you want to revert, restore from the backup file:

```bash
docker exec metrics_margin_collector python -m app.maintenance.rewrite_corr_history restore --file /app/backups/derived_metrics_corr_pre_20260406T083759Z_20260406T085819Z.json
```

Replace the filename with the actual backup you created.

## Recommended safe sequence

```bash
docker compose up -d --force-recreate collector
docker exec metrics_margin_collector python -m app.maintenance.rewrite_corr_history backup
docker exec metrics_margin_collector python -m app.maintenance.rewrite_corr_history rewrite
```

## Dashboard refresh

After rewrite or restore:

- refresh Grafana in the browser first
- if needed, recreate Grafana:

```bash
docker compose up -d --force-recreate grafana
```

## Notes on correlation semantics

The collector now computes true time-based rolling windows from `INVENTORY_POLL_SECONDS`.

With:

```bash
INVENTORY_POLL_SECONDS=900
```

this means:

- `corr_24h` uses `96` points
- `corr_7d` uses `672` points

If `compute_rolling_correlation()` uses:

```python
min_periods=points
```

then the chart will only show values after the full window is available.

If it uses a smaller `min_periods`, values can appear earlier as partial-window correlations.

## Recovery verification

After restore, confirm the dashboard visually and, if needed, inspect the backup JSON row count and the script output to verify the expected number of rows was restored.
