CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ── margin_pairs (reference table, not a hypertable) ────────────────
CREATE TABLE IF NOT EXISTS margin_pairs (
    symbol TEXT PRIMARY KEY,
    base_asset TEXT NOT NULL,
    quote_asset TEXT NOT NULL,
    is_margin_trade BOOLEAN NOT NULL DEFAULT TRUE,
    is_buy_allowed BOOLEAN NOT NULL DEFAULT TRUE,
    is_sell_allowed BOOLEAN NOT NULL DEFAULT TRUE,
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_margin_pairs_base ON margin_pairs (base_asset);
CREATE INDEX IF NOT EXISTS idx_margin_pairs_quote ON margin_pairs (quote_asset);

-- ── spot_klines ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS spot_klines (
    symbol TEXT NOT NULL,
    open_time TIMESTAMPTZ NOT NULL,
    close_time TIMESTAMPTZ NOT NULL,
    open NUMERIC(30, 12) NOT NULL,
    high NUMERIC(30, 12) NOT NULL,
    low NUMERIC(30, 12) NOT NULL,
    close NUMERIC(30, 12) NOT NULL,
    volume NUMERIC(30, 12) NOT NULL,
    quote_volume NUMERIC(30, 12),
    trade_count INTEGER,
    taker_buy_base_volume NUMERIC(30, 12),
    taker_buy_quote_volume NUMERIC(30, 12),
    raw_payload JSONB NOT NULL,
    PRIMARY KEY (symbol, open_time)
);
SELECT create_hypertable('spot_klines', 'open_time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_spot_klines_symbol_close_time ON spot_klines (symbol, close_time DESC);

-- ── margin_available_inventory_snapshots ─────────────────────────────
CREATE TABLE IF NOT EXISTS margin_available_inventory_snapshots (
    collected_at TIMESTAMPTZ NOT NULL,
    endpoint TEXT NOT NULL,
    asset TEXT,
    symbol TEXT,
    request_params JSONB NOT NULL,
    raw_payload JSONB NOT NULL,
    parsed_payload JSONB NOT NULL,
    available_inventory NUMERIC(30, 12),
    borrow_enabled BOOLEAN,
    unique_key TEXT NOT NULL,
    PRIMARY KEY (collected_at, unique_key)
);
SELECT create_hypertable('margin_available_inventory_snapshots', 'collected_at', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_margin_available_inventory_asset_time ON margin_available_inventory_snapshots (asset, collected_at DESC);

-- ── margin_price_index_snapshots ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS margin_price_index_snapshots (
    collected_at TIMESTAMPTZ NOT NULL,
    endpoint TEXT NOT NULL,
    asset TEXT,
    symbol TEXT,
    request_params JSONB NOT NULL,
    raw_payload JSONB NOT NULL,
    parsed_payload JSONB NOT NULL,
    price NUMERIC(30, 12),
    unique_key TEXT NOT NULL,
    PRIMARY KEY (collected_at, unique_key)
);
SELECT create_hypertable('margin_price_index_snapshots', 'collected_at', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_margin_price_index_symbol_time ON margin_price_index_snapshots (symbol, collected_at DESC);

-- ── isolated_margin_tier_snapshots ───────────────────────────────────
CREATE TABLE IF NOT EXISTS isolated_margin_tier_snapshots (
    collected_at TIMESTAMPTZ NOT NULL,
    endpoint TEXT NOT NULL,
    asset TEXT,
    symbol TEXT,
    request_params JSONB NOT NULL,
    raw_payload JSONB NOT NULL,
    parsed_payload JSONB NOT NULL,
    tier INTEGER,
    effective_multiple NUMERIC(30, 12),
    initial_risk_ratio NUMERIC(30, 12),
    liquidation_risk_ratio NUMERIC(30, 12),
    base_asset_max_borrowable NUMERIC(30, 12),
    quote_asset_max_borrowable NUMERIC(30, 12),
    fingerprint TEXT NOT NULL,
    unique_key TEXT NOT NULL,
    PRIMARY KEY (collected_at, unique_key)
);
SELECT create_hypertable('isolated_margin_tier_snapshots', 'collected_at', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_isolated_tier_symbol_time ON isolated_margin_tier_snapshots (symbol, collected_at DESC);

-- ── cross_margin_collateral_ratio_snapshots ──────────────────────────
CREATE TABLE IF NOT EXISTS cross_margin_collateral_ratio_snapshots (
    collected_at TIMESTAMPTZ NOT NULL,
    endpoint TEXT NOT NULL,
    asset TEXT,
    symbol TEXT,
    request_params JSONB NOT NULL,
    raw_payload JSONB NOT NULL,
    parsed_payload JSONB NOT NULL,
    collateral_ratio NUMERIC(30, 12),
    discount_rate NUMERIC(30, 12),
    fingerprint TEXT NOT NULL,
    unique_key TEXT NOT NULL,
    PRIMARY KEY (collected_at, unique_key)
);
SELECT create_hypertable('cross_margin_collateral_ratio_snapshots', 'collected_at', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_cross_collateral_asset_time ON cross_margin_collateral_ratio_snapshots (asset, collected_at DESC);

-- ── risk_based_liquidation_ratio_snapshots ───────────────────────────
CREATE TABLE IF NOT EXISTS risk_based_liquidation_ratio_snapshots (
    collected_at TIMESTAMPTZ NOT NULL,
    endpoint TEXT NOT NULL,
    asset TEXT,
    symbol TEXT,
    request_params JSONB NOT NULL,
    raw_payload JSONB NOT NULL,
    parsed_payload JSONB NOT NULL,
    liquidation_ratio NUMERIC(30, 12),
    warning_ratio NUMERIC(30, 12),
    fingerprint TEXT NOT NULL,
    unique_key TEXT NOT NULL,
    PRIMARY KEY (collected_at, unique_key)
);
SELECT create_hypertable('risk_based_liquidation_ratio_snapshots', 'collected_at', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_risk_liq_asset_time ON risk_based_liquidation_ratio_snapshots (asset, collected_at DESC);

-- ── derived_metrics ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS derived_metrics (
    collected_at TIMESTAMPTZ NOT NULL,
    asset TEXT NOT NULL,
    symbol TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value DOUBLE PRECISION,
    window_label TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (collected_at, asset, symbol, metric_name, window_label)
);
SELECT create_hypertable('derived_metrics', 'collected_at', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_derived_metrics_lookup ON derived_metrics (asset, symbol, metric_name, collected_at DESC);

-- ── config_change_events ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS config_change_events (
    collected_at TIMESTAMPTZ NOT NULL,
    asset TEXT,
    symbol TEXT,
    source_table TEXT NOT NULL,
    event_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    previous_payload JSONB NOT NULL,
    current_payload JSONB NOT NULL,
    event_fingerprint TEXT NOT NULL,
    PRIMARY KEY (collected_at, event_fingerprint)
);
SELECT create_hypertable('config_change_events', 'collected_at', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_config_change_asset_time ON config_change_events (asset, symbol, collected_at DESC);
