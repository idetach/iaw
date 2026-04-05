from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.config import Settings
from app.utils import json_fingerprint

def _find_sql_dir() -> Path:
    candidates = [
        Path(__file__).resolve().parents[1] / "sql",
        Path(__file__).resolve().parents[2] / "sql",
        Path("/app/sql"),
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]

_SQL_DIR = _find_sql_dir()


class Database:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.log = logging.getLogger("metrics_margin.db")

    @contextmanager
    def connection(self):
        with psycopg.connect(self.settings.dsn, row_factory=dict_row) as conn:
            yield conn

    def ensure_schema(self) -> None:
        sql_file = _SQL_DIR / "001_init.sql"
        if sql_file.exists():
            sql = sql_file.read_text(encoding="utf-8")
            with self.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql)
                conn.commit()
            self.log.info("schema_applied file=%s", sql_file)
        else:
            with self.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")
                    cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
                conn.commit()
            self.log.warning("schema_sql_not_found path=%s using_fallback", sql_file)

    def fetch_one(self, query: str, params: dict[str, Any] | tuple[Any, ...]) -> dict[str, Any] | None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return cur.fetchone()

    def fetch_all(self, query: str, params: dict[str, Any] | tuple[Any, ...]) -> list[dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return list(cur.fetchall())

    def execute(self, query: str, params: dict[str, Any] | tuple[Any, ...] | None = None) -> None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params or {})
            conn.commit()

    def executemany(self, query: str, rows: Iterable[dict[str, Any] | tuple[Any, ...]]) -> None:
        rows = list(rows)
        if not rows:
            return
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(query, rows)
            conn.commit()

    def insert_json_snapshot(
        self,
        *,
        table: str,
        collected_at: datetime,
        endpoint: str,
        asset: str | None,
        symbol: str | None,
        request_params: dict[str, Any],
        raw_payload: dict[str, Any] | list[Any],
        parsed: dict[str, Any],
        unique_key: str,
    ) -> None:
        query = f"""
            INSERT INTO {table} (
                collected_at, endpoint, asset, symbol, request_params, raw_payload, parsed_payload, unique_key
            ) VALUES (
                %(collected_at)s, %(endpoint)s, %(asset)s, %(symbol)s, %(request_params)s::jsonb,
                %(raw_payload)s::jsonb, %(parsed_payload)s::jsonb, %(unique_key)s
            )
            ON CONFLICT (collected_at, unique_key) DO NOTHING
        """
        self.execute(
            query,
            {
                "collected_at": collected_at,
                "endpoint": endpoint,
                "asset": asset,
                "symbol": symbol,
                "request_params": json.dumps(request_params, sort_keys=True, default=str),
                "raw_payload": json.dumps(raw_payload, sort_keys=True, default=str),
                "parsed_payload": json.dumps(parsed, sort_keys=True, default=str),
                "unique_key": unique_key,
            },
        )

    def upsert_margin_pairs(self, rows: list[dict[str, Any]]) -> None:
        query = """
            INSERT INTO margin_pairs (
                symbol, base_asset, quote_asset, is_margin_trade, is_buy_allowed, is_sell_allowed,
                discovered_at, last_seen_at
            ) VALUES (
                %(symbol)s, %(base_asset)s, %(quote_asset)s, %(is_margin_trade)s,
                %(is_buy_allowed)s, %(is_sell_allowed)s, NOW(), NOW()
            )
            ON CONFLICT (symbol) DO UPDATE SET
                is_margin_trade = EXCLUDED.is_margin_trade,
                is_buy_allowed = EXCLUDED.is_buy_allowed,
                is_sell_allowed = EXCLUDED.is_sell_allowed,
                last_seen_at = NOW()
        """
        self.executemany(query, rows)

    def get_tracked_pairs(self, quote_assets: tuple[str, ...] = ("USDC", "USDT", "FDUSD")) -> list[dict[str, str]]:
        return self.fetch_all(
            """
            SELECT symbol, base_asset, quote_asset
            FROM margin_pairs
            WHERE quote_asset = ANY(%(quotes)s) AND is_margin_trade = TRUE
            ORDER BY symbol
            """,
            {"quotes": list(quote_assets)},
        )

    def insert_spot_klines(self, rows: list[dict[str, Any]]) -> None:
        query = """
            INSERT INTO spot_klines (
                symbol, open_time, close_time, open, high, low, close, volume, quote_volume,
                trade_count, taker_buy_base_volume, taker_buy_quote_volume, raw_payload
            ) VALUES (
                %(symbol)s, %(open_time)s, %(close_time)s, %(open)s, %(high)s, %(low)s, %(close)s,
                %(volume)s, %(quote_volume)s, %(trade_count)s, %(taker_buy_base_volume)s,
                %(taker_buy_quote_volume)s, %(raw)s::jsonb
            )
            ON CONFLICT (symbol, open_time) DO UPDATE SET
                close_time = EXCLUDED.close_time,
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume,
                quote_volume = EXCLUDED.quote_volume,
                trade_count = EXCLUDED.trade_count,
                taker_buy_base_volume = EXCLUDED.taker_buy_base_volume,
                taker_buy_quote_volume = EXCLUDED.taker_buy_quote_volume,
                raw_payload = EXCLUDED.raw_payload
        """
        formatted = []
        for row in rows:
            formatted.append({**row, "raw": json.dumps(row["raw"], default=str)})
        self.executemany(query, formatted)

    def upsert_available_inventory(self, rows: list[dict[str, Any]]) -> None:
        query = """
            INSERT INTO margin_available_inventory_snapshots (
                collected_at, endpoint, asset, symbol, request_params, raw_payload, parsed_payload,
                available_inventory, borrow_enabled, unique_key
            ) VALUES (
                %(collected_at)s, %(endpoint)s, %(asset)s, %(symbol)s, %(request_params)s::jsonb,
                %(raw_payload)s::jsonb, %(parsed_payload)s::jsonb, %(available_inventory)s,
                %(borrow_enabled)s, %(unique_key)s
            )
            ON CONFLICT (collected_at, unique_key) DO NOTHING
        """
        self.executemany(query, rows)

    def upsert_price_index(self, rows: list[dict[str, Any]]) -> None:
        query = """
            INSERT INTO margin_price_index_snapshots (
                collected_at, endpoint, asset, symbol, request_params, raw_payload, parsed_payload,
                price, unique_key
            ) VALUES (
                %(collected_at)s, %(endpoint)s, %(asset)s, %(symbol)s, %(request_params)s::jsonb,
                %(raw_payload)s::jsonb, %(parsed_payload)s::jsonb, %(price)s, %(unique_key)s
            )
            ON CONFLICT (collected_at, unique_key) DO NOTHING
        """
        self.executemany(query, rows)

    def upsert_isolated_tiers(self, rows: list[dict[str, Any]]) -> None:
        query = """
            INSERT INTO isolated_margin_tier_snapshots (
                collected_at, endpoint, asset, symbol, request_params, raw_payload, parsed_payload,
                tier, effective_multiple, initial_risk_ratio, liquidation_risk_ratio,
                base_asset_max_borrowable, quote_asset_max_borrowable, fingerprint, unique_key
            ) VALUES (
                %(collected_at)s, %(endpoint)s, %(asset)s, %(symbol)s, %(request_params)s::jsonb,
                %(raw_payload)s::jsonb, %(parsed_payload)s::jsonb, %(tier)s, %(effective_multiple)s,
                %(initial_risk_ratio)s, %(liquidation_risk_ratio)s, %(base_asset_max_borrowable)s,
                %(quote_asset_max_borrowable)s, %(fingerprint)s, %(unique_key)s
            )
            ON CONFLICT (collected_at, unique_key) DO NOTHING
        """
        self.executemany(query, rows)

    def upsert_cross_collateral(self, rows: list[dict[str, Any]]) -> None:
        query = """
            INSERT INTO cross_margin_collateral_ratio_snapshots (
                collected_at, endpoint, asset, symbol, request_params, raw_payload, parsed_payload,
                collateral_ratio, discount_rate, fingerprint, unique_key
            ) VALUES (
                %(collected_at)s, %(endpoint)s, %(asset)s, %(symbol)s, %(request_params)s::jsonb,
                %(raw_payload)s::jsonb, %(parsed_payload)s::jsonb, %(collateral_ratio)s,
                %(discount_rate)s, %(fingerprint)s, %(unique_key)s
            )
            ON CONFLICT (collected_at, unique_key) DO NOTHING
        """
        self.executemany(query, rows)

    def upsert_risk_liquidation(self, rows: list[dict[str, Any]]) -> None:
        query = """
            INSERT INTO risk_based_liquidation_ratio_snapshots (
                collected_at, endpoint, asset, symbol, request_params, raw_payload, parsed_payload,
                liquidation_ratio, warning_ratio, fingerprint, unique_key
            ) VALUES (
                %(collected_at)s, %(endpoint)s, %(asset)s, %(symbol)s, %(request_params)s::jsonb,
                %(raw_payload)s::jsonb, %(parsed_payload)s::jsonb, %(liquidation_ratio)s,
                %(warning_ratio)s, %(fingerprint)s, %(unique_key)s
            )
            ON CONFLICT (collected_at, unique_key) DO NOTHING
        """
        self.executemany(query, rows)

    def latest_fingerprint(self, table: str, *, asset: str | None, symbol: str | None) -> str | None:
        query = f"""
            SELECT fingerprint
            FROM {table}
            WHERE asset IS NOT DISTINCT FROM %(asset)s
              AND symbol IS NOT DISTINCT FROM %(symbol)s
            ORDER BY collected_at DESC
            LIMIT 1
        """
        row = self.fetch_one(query, {"asset": asset, "symbol": symbol})
        return None if row is None else row["fingerprint"]

    def insert_change_event(
        self,
        *,
        collected_at: datetime,
        asset: str | None,
        symbol: str | None,
        source_table: str,
        event_type: str,
        summary: str,
        previous_payload: dict[str, Any] | None,
        current_payload: dict[str, Any] | None,
    ) -> None:
        query = """
            INSERT INTO config_change_events (
                collected_at, asset, symbol, source_table, event_type, summary,
                previous_payload, current_payload, event_fingerprint
            ) VALUES (
                %(collected_at)s, %(asset)s, %(symbol)s, %(source_table)s, %(event_type)s, %(summary)s,
                %(previous_payload)s::jsonb, %(current_payload)s::jsonb, %(event_fingerprint)s
            )
            ON CONFLICT (collected_at, event_fingerprint) DO NOTHING
        """
        fingerprint = json_fingerprint({
            "collected_at": collected_at.isoformat(),
            "asset": asset,
            "symbol": symbol,
            "source_table": source_table,
            "event_type": event_type,
            "summary": summary,
            "current_payload": current_payload,
        })
        self.execute(
            query,
            {
                "collected_at": collected_at,
                "asset": asset,
                "symbol": symbol,
                "source_table": source_table,
                "event_type": event_type,
                "summary": summary,
                "previous_payload": json.dumps(previous_payload or {}, sort_keys=True, default=str),
                "current_payload": json.dumps(current_payload or {}, sort_keys=True, default=str),
                "event_fingerprint": fingerprint,
            },
        )

    def latest_inventory_window(self, asset: str, hours: int) -> list[dict[str, Any]]:
        query = """
            SELECT collected_at, available_inventory
            FROM margin_available_inventory_snapshots
            WHERE asset = %(asset)s
              AND collected_at >= NOW() - (%(hours)s || ' hours')::interval
            ORDER BY collected_at ASC
        """
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, {"asset": asset, "hours": hours})
                return list(cur.fetchall())

    def upsert_derived_metrics(self, rows: list[dict[str, Any]]) -> None:
        query = """
            INSERT INTO derived_metrics (
                collected_at, asset, symbol, metric_name, metric_value, window_label, metadata
            ) VALUES (
                %(collected_at)s, %(asset)s, %(symbol)s, %(metric_name)s, %(metric_value)s,
                %(window_label)s, %(metadata)s::jsonb
            )
            ON CONFLICT (collected_at, asset, symbol, metric_name, window_label) DO UPDATE SET
                metric_value = EXCLUDED.metric_value,
                metadata = EXCLUDED.metadata
        """
        formatted = []
        for row in rows:
            formatted.append({**row, "metadata": json.dumps(row.get("metadata") or {}, sort_keys=True, default=str)})
        self.executemany(query, formatted)
