from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any

from app.change_detection import persist_change_event_if_needed
from app.config import Settings
from app.db import Database
from app.exceptions import BinancePermissionError
from app.exchanges import BinanceAdapter
from app.telegram import TelegramNotifier
from app.transforms import build_derived_metric_rows, infer_stress_regime
from app.utils import json_fingerprint, to_decimal, utc_now


class CollectorService:
    def __init__(self, settings: Settings, db: Database, adapter: BinanceAdapter) -> None:
        self.settings = settings
        self.db = db
        self.adapter = adapter
        self.log = logging.getLogger("metrics_margin.collector")
        self._discovered_symbols: dict[str, str] = {}  # symbol -> base_asset
        self.tg = TelegramNotifier(
            bot_token=settings.tg_iaw_metrics_alerts_bot_token,
            chat_id=settings.tg_iaw_metrics_alerts_bot_chat_id,
        )
        self._corr_24h_points = max(2, round((24 * 60 * 60) / self.settings.inventory_poll_seconds))
        self._corr_7d_points = max(2, round((7 * 24 * 60 * 60) / self.settings.inventory_poll_seconds))

    def discover_margin_pairs(self, *, force_api: bool = False) -> None:
        if not force_api and not self._discovered_symbols:
            try:
                db_pairs = self.db.get_tracked_pairs()
                if db_pairs:
                    mapping = {p["symbol"]: p["base_asset"] for p in db_pairs}
                    self.log.info("discover_margin_pairs loaded_from_db count=%d", len(mapping))
                    self._apply_tracked_symbols(mapping)
                    return
            except Exception as exc:
                self.log.warning("discover_margin_pairs_db_read_failed error=%s, trying API", exc)

        try:
            raw_pairs = self.adapter.fetch_all_margin_pairs()
        except Exception as exc:
            self.log.warning("discover_margin_pairs_failed error=%s, falling back to config", exc)
            return

        rows = []
        stable_pairs: dict[str, str] = {}  # symbol -> base_asset for stablecoin-quoted pairs
        preferred_quotes = ("USDC", "USDT", "FDUSD")
        for p in raw_pairs:
            symbol = str(p.get("symbol") or "").upper()
            base = str(p.get("base") or "").upper()
            quote = str(p.get("quote") or "").upper()
            if not symbol or not base or not quote:
                continue
            is_margin = bool(p.get("isMarginTrade", True))
            rows.append({
                "symbol": symbol,
                "base_asset": base,
                "quote_asset": quote,
                "is_margin_trade": is_margin,
                "is_buy_allowed": bool(p.get("isBuyAllowed", True)),
                "is_sell_allowed": bool(p.get("isSellAllowed", True)),
            })
            if quote in preferred_quotes and is_margin:
                stable_pairs[symbol] = base

        try:
            if rows:
                self.db.upsert_margin_pairs(rows)
        except Exception as exc:
            self.log.warning("upsert_margin_pairs_failed error=%s (non-fatal, pairs still tracked in memory)", exc)

        self.log.info("discover_margin_pairs total=%d stablecoin_pairs=%d", len(raw_pairs), len(stable_pairs))
        self._apply_tracked_symbols(stable_pairs)

    def _apply_tracked_symbols(self, discovered: dict[str, str]) -> None:
        if not discovered:
            self.log.warning("no_stablecoin_pairs_discovered, using static config")
            self._discovered_symbols = dict(self.settings.asset_by_symbol)
            return

        override_symbols = set(self.settings.symbols) if self.settings.tracked_symbols.strip() else set()
        if override_symbols:
            filtered = {s: a for s, a in discovered.items() if s in override_symbols}
            if not filtered:
                self.log.warning("override_filter_empty, using all %d discovered USDT pairs", len(discovered))
                filtered = discovered
            self._discovered_symbols = filtered
        else:
            self._discovered_symbols = discovered

        self.log.info("tracked_symbols count=%d", len(self._discovered_symbols))

    @property
    def tracked_symbols(self) -> dict[str, str]:
        if self._discovered_symbols:
            return self._discovered_symbols
        return dict(self.settings.asset_by_symbol)

    @property
    def tracked_assets(self) -> list[str]:
        return list(set(self.tracked_symbols.values()))

    def backfill_price_history(self) -> None:
        now = utc_now()
        start_time = now - timedelta(hours=self.settings.backfill_hours)
        symbols = list(self.tracked_symbols.keys())
        total = len(symbols)

        try:
            existing = self.db.fetch_all(
                """
                SELECT DISTINCT symbol FROM spot_klines
                WHERE close_time >= NOW() - INTERVAL '1 hour'
                """,
                {},
            )
            recent_symbols = {row["symbol"] for row in existing}
        except Exception:
            recent_symbols = set()

        skipped = 0
        for idx, symbol in enumerate(symbols, 1):
            if symbol in recent_symbols:
                skipped += 1
                continue
            try:
                candles = self.adapter.fetch_spot_klines(
                    symbol=symbol,
                    interval=self.settings.price_kline_interval,
                    start_time=start_time,
                    end_time=now,
                    limit=1000,
                )
                self.db.insert_spot_klines(candles)
                self.log.info("spot_klines_backfilled [%d/%d] symbol=%s rows=%s", idx, total, symbol, len(candles))
            except Exception as exc:
                self.log.warning("spot_klines_backfill_failed [%d/%d] symbol=%s error=%s", idx, total, symbol, exc)
            if total > 10:
                time.sleep(0.25)
        if skipped:
            self.log.info("spot_klines_backfill_skipped already_recent=%d/%d", skipped, total)

    def poll_prices(self) -> None:
        now = utc_now()
        for symbol, asset in self.tracked_symbols.items():
            candles = self.adapter.fetch_spot_klines(
                symbol=symbol,
                interval=self.settings.price_kline_interval,
                start_time=now - timedelta(hours=12),
                end_time=now,
                limit=200,
            )
            self.db.insert_spot_klines(candles)
            try:
                payload = self.adapter.fetch_price_index(symbol=symbol)
                price = to_decimal(payload.get("price"))
                row = {
                    "collected_at": now,
                    "endpoint": "/sapi/v1/margin/priceIndex",
                    "asset": asset,
                    "symbol": symbol,
                    "request_params": json.dumps({"symbol": symbol}),
                    "raw_payload": json.dumps(payload, sort_keys=True, default=str),
                    "parsed_payload": json.dumps(payload, sort_keys=True, default=str),
                    "price": price,
                    "unique_key": json_fingerprint({"symbol": symbol, "collected_at": now.isoformat(), "price": str(price)}),
                }
                self.db.upsert_price_index([row])
            except BinancePermissionError:
                self.log.warning("price_index_permission_missing symbol=%s", symbol)
            except Exception as exc:
                self.log.warning("price_index_failed symbol=%s error=%s", symbol, exc)
            try:
                self.compute_derived_metrics(asset=asset, symbol=symbol)
            except Exception as exc:
                self.log.warning("derived_metrics_failed asset=%s symbol=%s error=%s", asset, symbol, exc)

    def poll_available_inventory(self) -> None:
        now = utc_now()
        try:
            payload_rows = self.adapter.fetch_available_inventory(assets=self.tracked_assets)
        except BinancePermissionError:
            self.log.warning("margin_available_inventory_permission_missing")
            return
        except Exception as exc:
            self.log.warning("margin_available_inventory_failed error=%s", exc)
            return

        rows: list[dict[str, Any]] = []
        for item in payload_rows:
            asset = str(item.get("asset") or "").upper()
            available_inventory = to_decimal(
                item.get("amount")
                or item.get("availableInventory")
                or item.get("inventory")
                or item.get("free")
            )
            borrow_enabled = bool(item.get("borrowEnabled", True))
            rows.append(
                {
                    "collected_at": now,
                    "endpoint": "/sapi/v1/margin/available-inventory",
                    "asset": asset,
                    "symbol": None,
                    "request_params": json.dumps({"asset": asset}),
                    "raw_payload": json.dumps(item, sort_keys=True, default=str),
                    "parsed_payload": json.dumps(item, sort_keys=True, default=str),
                    "available_inventory": available_inventory,
                    "borrow_enabled": borrow_enabled,
                    "unique_key": json_fingerprint({"asset": asset, "collected_at": now.isoformat(), "payload": item}),
                }
            )
        self.db.upsert_available_inventory(rows)
        for asset in {row["asset"] for row in rows if row.get("asset")}:
            symbol = next((s for s, a in self.tracked_symbols.items() if a == asset), None)
            if symbol:
                try:
                    self.compute_derived_metrics(asset=asset, symbol=symbol)
                except Exception as exc:
                    self.log.warning("derived_metrics_failed asset=%s symbol=%s error=%s", asset, symbol, exc)
        self.log.info("available_inventory_polled assets=%d rows=%s", len(self.tracked_assets), len(rows))
        try:
            self.check_inventory_drops()
        except Exception as exc:
            self.log.warning("check_inventory_drops_failed error=%s", exc)
        try:
            self.check_inventory_gains()
        except Exception as exc:
            self.log.warning("check_inventory_gains_failed error=%s", exc)
        try:
            self.send_status_report()
        except Exception as exc:
            self.log.warning("status_report_failed error=%s", exc)

    def check_inventory_drops(self) -> None:
        if not self.tg.enabled:
            return
        drop_rows = self.db.fetch_all(
            """
            WITH ranked AS (
                SELECT asset,
                       available_inventory::double precision AS inv,
                       collected_at,
                       ROW_NUMBER() OVER (PARTITION BY asset ORDER BY collected_at DESC) AS rn
                FROM margin_available_inventory_snapshots
            )
            SELECT cur.asset,
                   cur.inv  AS current_inv,
                   prev.inv AS previous_inv,
                   CASE WHEN prev.inv > 0
                        THEN 100.0 * (cur.inv - prev.inv) / prev.inv
                        ELSE NULL
                   END AS pct_change
            FROM ranked cur
            JOIN ranked prev ON cur.asset = prev.asset AND prev.rn = 2
            WHERE cur.rn = 1
              AND prev.inv > 0
              AND 100.0 * (cur.inv - prev.inv) / prev.inv < -5
            ORDER BY 100.0 * (cur.inv - prev.inv) / prev.inv ASC
            """,
            {},
        )
        if not drop_rows:
            return
        lines: list[str] = [f"<b>Inventory drop alert</b> ({len(drop_rows)} assets)"]
        lines.append("")
        for r in drop_rows:
            lines.append(f"  <b>{r['asset']}</b> {r['pct_change']:+.1f}%  ({r['previous_inv']:.2f} → {r['current_inv']:.2f})")
        msg = "\n".join(lines)
        self.tg.send(msg)
        self.log.info("inventory_drop_alert_sent assets=%d", len(drop_rows))

    def check_inventory_gains(self) -> None:
        if not self.tg.enabled:
            return
        gain_rows = self.db.fetch_all(
            """
            WITH ranked AS (
                SELECT asset,
                       available_inventory::double precision AS inv,
                       collected_at,
                       ROW_NUMBER() OVER (PARTITION BY asset ORDER BY collected_at DESC) AS rn
                FROM margin_available_inventory_snapshots
            )
            SELECT cur.asset,
                   cur.inv  AS current_inv,
                   prev.inv AS previous_inv,
                   CASE WHEN prev.inv > 0
                        THEN 100.0 * (cur.inv - prev.inv) / prev.inv
                        ELSE NULL
                   END AS pct_change
            FROM ranked cur
            JOIN ranked prev ON cur.asset = prev.asset AND prev.rn = 2
            WHERE cur.rn = 1
              AND prev.inv > 0
              AND 100.0 * (cur.inv - prev.inv) / prev.inv > 5
            ORDER BY 100.0 * (cur.inv - prev.inv) / prev.inv DESC
            """,
            {},
        )
        if not gain_rows:
            return
        lines: list[str] = [f"<b>Inventory gain alert</b> ({len(gain_rows)} assets)"]
        lines.append("")
        for r in gain_rows:
            lines.append(f"  <b>{r['asset']}</b> {r['pct_change']:+.1f}%  ({r['previous_inv']:.2f} → {r['current_inv']:.2f})")
        msg = "\n".join(lines)
        self.tg.send(msg)
        self.log.info("inventory_gain_alert_sent assets=%d", len(gain_rows))

    def send_status_report(self) -> None:
        if not self.tg.enabled:
            return

        # --- Inventory 4h change for ALL assets ---
        inv_rows = self.db.fetch_all(
            """
            WITH latest AS (
                SELECT DISTINCT ON (asset)
                    asset, available_inventory::double precision AS inv, collected_at
                FROM margin_available_inventory_snapshots
                ORDER BY asset, collected_at DESC
            ),
            past AS (
                SELECT DISTINCT ON (asset)
                    asset, available_inventory::double precision AS inv
                FROM margin_available_inventory_snapshots
                WHERE collected_at <= NOW() - INTERVAL '4 hours'
                ORDER BY asset, collected_at DESC
            )
            SELECT latest.asset,
                   latest.inv AS current_inv,
                   past.inv   AS past_inv,
                   CASE WHEN past.inv > 0
                        THEN 100.0 * (latest.inv - past.inv) / past.inv
                        ELSE NULL
                   END AS pct_change
            FROM latest
            LEFT JOIN past USING (asset)
            ORDER BY pct_change ASC NULLS LAST
            """,
            {},
        )

        # --- Stress regimes ---
        stress_rows = self.db.fetch_all(
            """
            SELECT DISTINCT ON (symbol)
                symbol, metadata->>'label' AS regime
            FROM derived_metrics
            WHERE metric_name = 'stress_regime'
              AND collected_at >= NOW() - INTERVAL '2 hours'
            ORDER BY symbol, collected_at DESC
            """,
            {},
        )

        # --- Rolling correlation extremes ---
        corr_rows = self.db.fetch_all(
            """
            SELECT DISTINCT ON (symbol)
                symbol, metric_value
            FROM derived_metrics
            WHERE metric_name = 'rolling_corr_price_vs_inventory_24h'
              AND collected_at >= NOW() - INTERVAL '2 hours'
            ORDER BY symbol, collected_at DESC
            """,
            {},
        )

        # --- Build message ---
        lines: list[str] = []
        total = len(inv_rows)

        drops = [(r["asset"], r["pct_change"]) for r in inv_rows if r["pct_change"] is not None and r["pct_change"] < -5]
        minor_neg = [(r["asset"], r["pct_change"]) for r in inv_rows if r["pct_change"] is not None and -5 <= r["pct_change"] < 0]
        gains = [(r["asset"], r["pct_change"]) for r in inv_rows if r["pct_change"] is not None and r["pct_change"] > 5]
        minor_pos = [(r["asset"], r["pct_change"]) for r in inv_rows if r["pct_change"] is not None and 0 <= r["pct_change"] <= 5]
        no_data = [r["asset"] for r in inv_rows if r["pct_change"] is None]

        lines.append(f"<b>Inventory 4h report</b> ({total} assets)")
        lines.append("")

        if drops:
            lines.append(f"<b>Drops &gt;5%</b> ({len(drops)}):")
            for asset, pct in drops:
                lines.append(f"  {asset} {pct:+.1f}%")

        if minor_neg:
            lines.append(f"\n<b>Minor drops 0-5%</b> ({len(minor_neg)}): " + ", ".join(f"{a} {p:+.1f}%" for a, p in minor_neg))

        if gains:
            lines.append(f"\n<b>Gains &gt;5%</b> ({len(gains)}):")
            for asset, pct in sorted(gains, key=lambda x: x[1], reverse=True):
                lines.append(f"  {asset} {pct:+.1f}%")

        if minor_pos:
            lines.append(f"\n<b>Stable 0-5%</b> ({len(minor_pos)}): " + ", ".join(f"{a} {p:+.1f}%" for a, p in minor_pos))

        if no_data:
            lines.append(f"\n<i>No 4h baseline</i>: {len(no_data)} assets")

        # Stress
        high_stress = [r["symbol"] for r in stress_rows if r.get("regime") == "high"]
        if high_stress:
            lines.append(f"\n<b>Stress HIGH</b>: {', '.join(high_stress)}")

        # Correlation extremes
        extreme_corr = [(r["symbol"], r["metric_value"]) for r in corr_rows if r.get("metric_value") is not None and abs(r["metric_value"]) > 0.8]
        if extreme_corr:
            parts = [f"{sym} ({val:+.2f})" for sym, val in sorted(extreme_corr, key=lambda x: abs(x[1]), reverse=True)]
            lines.append(f"\n<b>|Corr| &gt; 0.8</b>: {', '.join(parts)}")

        msg = "\n".join(lines)
        self.tg.send(msg)
        self.log.info("status_report_sent len=%d drops=%d gains=%d", len(msg), len(drops), len(gains))

    def poll_config_snapshots(self) -> None:
        now = utc_now()
        for name, fn in [
            ("isolated_tiers", self._poll_isolated_tiers),
            ("cross_collateral", self._poll_cross_collateral),
            ("risk_liquidation", self._poll_risk_liquidation),
        ]:
            try:
                fn(now)
            except Exception as exc:
                self.log.warning("poll_config_%s_failed error=%s", name, exc)

    def _poll_isolated_tiers(self, collected_at: datetime) -> None:
        payloads = self.adapter.fetch_isolated_margin_tiers(symbols=list(self.tracked_symbols.keys()))
        rows: list[dict[str, Any]] = []
        for payload in payloads:
            symbol = str(payload.get("symbol") or "").upper()
            asset = self.tracked_symbols.get(symbol)
            parsed = {
                "tier": payload.get("tier"),
                "effectiveMultiple": payload.get("effectiveMultiple"),
                "initialRiskRatio": payload.get("initialRiskRatio"),
                "liquidationRiskRatio": payload.get("liquidationRiskRatio"),
                "baseAssetMaxBorrowable": payload.get("baseAssetMaxBorrowable"),
                "quoteAssetMaxBorrowable": payload.get("quoteAssetMaxBorrowable"),
            }
            previous = self.db.fetch_one(
                """
                SELECT parsed_payload
                FROM isolated_margin_tier_snapshots
                WHERE symbol = %(symbol)s
                ORDER BY collected_at DESC
                LIMIT 1
                """,
                {"symbol": symbol},
            )
            persist_change_event_if_needed(
                db=self.db,
                source_key="isolated_margin_tier",
                collected_at=collected_at,
                asset=asset,
                symbol=symbol,
                previous_payload=None if previous is None else previous["parsed_payload"],
                current_payload=parsed,
            )
            rows.append(
                {
                    "collected_at": collected_at,
                    "endpoint": "/sapi/v1/margin/isolatedMarginTier",
                    "asset": asset,
                    "symbol": symbol,
                    "request_params": json.dumps({"symbol": symbol}),
                    "raw_payload": json.dumps(payload, sort_keys=True, default=str),
                    "parsed_payload": json.dumps(parsed, sort_keys=True, default=str),
                    "tier": payload.get("tier"),
                    "effective_multiple": to_decimal(payload.get("effectiveMultiple")),
                    "initial_risk_ratio": to_decimal(payload.get("initialRiskRatio")),
                    "liquidation_risk_ratio": to_decimal(payload.get("liquidationRiskRatio")),
                    "base_asset_max_borrowable": to_decimal(payload.get("baseAssetMaxBorrowable")),
                    "quote_asset_max_borrowable": to_decimal(payload.get("quoteAssetMaxBorrowable")),
                    "fingerprint": json_fingerprint(parsed),
                    "unique_key": json_fingerprint({"symbol": symbol, "collected_at": collected_at.isoformat(), "parsed": parsed}),
                }
            )
        self.db.upsert_isolated_tiers(rows)
        self.log.info("isolated_tiers_polled rows=%s", len(rows))

    def _poll_cross_collateral(self, collected_at: datetime) -> None:
        payloads = self.adapter.fetch_cross_margin_collateral_ratios()
        rows: list[dict[str, Any]] = []
        for payload in payloads:
            asset_names = payload.get("assetNames") or []
            collateral_tiers = payload.get("collaterals") or []
            first_tier = collateral_tiers[0] if collateral_tiers else {}
            discount_rate = first_tier.get("discountRate")

            if asset_names:
                for asset_name in asset_names:
                    asset = str(asset_name).upper()
                    parsed = {
                        "asset": asset,
                        "discountRate": discount_rate,
                        "collaterals": collateral_tiers,
                        "borrowCollaterals": payload.get("borrowCollaterals"),
                        "withdrawCollaterals": payload.get("withdrawCollaterals"),
                    }
                    previous = self.db.fetch_one(
                        """
                        SELECT parsed_payload
                        FROM cross_margin_collateral_ratio_snapshots
                        WHERE asset = %(asset)s
                        ORDER BY collected_at DESC
                        LIMIT 1
                        """,
                        {"asset": asset},
                    )
                    persist_change_event_if_needed(
                        db=self.db,
                        source_key="cross_margin_collateral_ratio",
                        collected_at=collected_at,
                        asset=asset,
                        symbol=None,
                        previous_payload=None if previous is None else previous["parsed_payload"],
                        current_payload=parsed,
                    )
                    rows.append(
                        {
                            "collected_at": collected_at,
                            "endpoint": "/sapi/v1/margin/crossMarginCollateralRatio",
                            "asset": asset,
                            "symbol": None,
                            "request_params": json.dumps({}, sort_keys=True),
                            "raw_payload": json.dumps(payload, sort_keys=True, default=str),
                            "parsed_payload": json.dumps(parsed, sort_keys=True, default=str),
                            "collateral_ratio": None,
                            "discount_rate": to_decimal(discount_rate),
                            "fingerprint": json_fingerprint(parsed),
                            "unique_key": json_fingerprint({"asset": asset, "collected_at": collected_at.isoformat(), "parsed": parsed}),
                        }
                    )
            else:
                asset = str(payload.get("asset") or payload.get("coin") or "").upper() or None
                parsed = {
                    "asset": asset,
                    "collateralRatio": payload.get("collateralRatio"),
                    "discountRate": payload.get("discountRate"),
                }
                rows.append(
                    {
                        "collected_at": collected_at,
                        "endpoint": "/sapi/v1/margin/crossMarginCollateralRatio",
                        "asset": asset,
                        "symbol": None,
                        "request_params": json.dumps({}, sort_keys=True),
                        "raw_payload": json.dumps(payload, sort_keys=True, default=str),
                        "parsed_payload": json.dumps(parsed, sort_keys=True, default=str),
                        "collateral_ratio": to_decimal(payload.get("collateralRatio")),
                        "discount_rate": to_decimal(payload.get("discountRate")),
                        "fingerprint": json_fingerprint(parsed),
                        "unique_key": json_fingerprint({"asset": asset, "collected_at": collected_at.isoformat(), "parsed": parsed}),
                    }
                )
        self.db.upsert_cross_collateral(rows)
        self.log.info("cross_collateral_polled rows=%s", len(rows))

    def _poll_risk_liquidation(self, collected_at: datetime) -> None:
        payloads = self.adapter.fetch_risk_based_liquidation_ratios()
        rows: list[dict[str, Any]] = []
        for payload in payloads:
            asset = str(payload.get("asset") or payload.get("coin") or "").upper() or None
            parsed = {
                "asset": asset,
                "liquidationRatio": payload.get("liquidationRatio"),
                "warningRatio": payload.get("warningRatio"),
            }
            previous = self.db.fetch_one(
                """
                SELECT parsed_payload
                FROM risk_based_liquidation_ratio_snapshots
                WHERE asset IS NOT DISTINCT FROM %(asset)s
                ORDER BY collected_at DESC
                LIMIT 1
                """,
                {"asset": asset},
            )
            persist_change_event_if_needed(
                db=self.db,
                source_key="risk_based_liquidation_ratio",
                collected_at=collected_at,
                asset=asset,
                symbol=None,
                previous_payload=None if previous is None else previous["parsed_payload"],
                current_payload=parsed,
            )
            rows.append(
                {
                    "collected_at": collected_at,
                    "endpoint": "/sapi/v1/margin/risk-based-liquidation-ratio",
                    "asset": asset,
                    "symbol": None,
                    "request_params": json.dumps({}, sort_keys=True),
                    "raw_payload": json.dumps(payload, sort_keys=True, default=str),
                    "parsed_payload": json.dumps(parsed, sort_keys=True, default=str),
                    "liquidation_ratio": to_decimal(payload.get("liquidationRatio")),
                    "warning_ratio": to_decimal(payload.get("warningRatio")),
                    "fingerprint": json_fingerprint(parsed),
                    "unique_key": json_fingerprint({"asset": asset, "collected_at": collected_at.isoformat(), "parsed": parsed}),
                }
            )
        self.db.upsert_risk_liquidation(rows)
        self.log.info("risk_liquidation_polled rows=%s", len(rows))

    def compute_derived_metrics(self, *, asset: str, symbol: str) -> None:
        import pandas as pd

        inventory_rows = self.db.fetch_all(
            """
            SELECT collected_at, available_inventory::double precision AS available_inventory
            FROM margin_available_inventory_snapshots
            WHERE asset = %(asset)s
              AND collected_at >= NOW() - INTERVAL '14 days'
            ORDER BY collected_at ASC
            """,
            {"asset": asset},
        )
        price_rows = self.db.fetch_all(
            """
            SELECT close_time AS collected_at, close::double precision AS close_price
            FROM spot_klines
            WHERE symbol = %(symbol)s
              AND close_time >= NOW() - INTERVAL '14 days'
            ORDER BY close_time ASC
            """,
            {"symbol": symbol},
        )
        self.log.debug(
            "derived_metrics_input asset=%s symbol=%s inventory_points=%d price_points=%d",
            asset, symbol, len(inventory_rows), len(price_rows),
        )
        if not inventory_rows or not price_rows:
            return

        inv_df = pd.DataFrame(inventory_rows)
        inv_df["collected_at"] = pd.to_datetime(inv_df["collected_at"], utc=True)
        price_df = pd.DataFrame(price_rows)
        price_df["collected_at"] = pd.to_datetime(price_df["collected_at"], utc=True)

        merged = pd.merge_asof(
            inv_df.sort_values("collected_at"),
            price_df.sort_values("collected_at"),
            on="collected_at",
            direction="nearest",
            tolerance=pd.Timedelta("2h"),
        )
        merged = merged.dropna(subset=["close_price", "available_inventory"])
        points = merged.to_dict("records")
        self.log.debug("derived_metrics_merged asset=%s symbol=%s merged_points=%d", asset, symbol, len(points))

        derived_rows = build_derived_metric_rows(
            asset=asset,
            symbol=symbol,
            points=points,
            corr_24h_points=self._corr_24h_points,
            corr_7d_points=self._corr_7d_points,
        )
        if derived_rows:
            self.db.upsert_derived_metrics(derived_rows)
            latest_stress = next((row for row in reversed(derived_rows) if row["metric_name"] == "stress_proxy_zinv"), None)
            regime = infer_stress_regime(None if latest_stress is None else latest_stress["metric_value"])
            self.db.upsert_derived_metrics(
                [
                    {
                        "collected_at": utc_now(),
                        "asset": asset,
                        "symbol": symbol,
                        "metric_name": "stress_regime",
                        "metric_value": {"low": 0.0, "medium": 1.0, "high": 2.0, "unknown": -1.0}[regime],
                        "window_label": "current",
                        "metadata": {"label": regime},
                    }
                ]
            )
            self.log.debug(
                "derived_metrics_written asset=%s symbol=%s corr_24h_points=%d corr_7d_points=%d",
                asset,
                symbol,
                self._corr_24h_points,
                self._corr_7d_points,
            )
