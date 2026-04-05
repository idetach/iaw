from __future__ import annotations

import hashlib
import hmac
import logging
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import Settings
from app.exceptions import BinancePermissionError, BinanceRateLimitError
from app.exchanges.base import ExchangeAdapter
from app.utils import normalize_symbol


class BinanceAdapter(ExchangeAdapter):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.log = logging.getLogger("metrics_margin.binance")
        self.client = httpx.Client(base_url=settings.binance_base_url, timeout=settings.request_timeout_seconds)

    def close(self) -> None:
        self.client.close()

    def _apikey_request(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.settings.binance_api_key:
            raise BinancePermissionError("Binance API key is not configured")
        headers = {"X-MBX-APIKEY": self.settings.binance_api_key}
        return self._request(method, path, params=params, headers=headers)

    def _signed_request(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.settings.binance_api_key or not self.settings.binance_api_secret:
            raise BinancePermissionError("Binance API credentials are not configured for signed endpoints")

        payload = dict(params or {})
        payload["timestamp"] = int(time.time() * 1000)
        payload["recvWindow"] = 10_000
        query = urlencode(payload, doseq=True)
        signature = hmac.new(
            self.settings.binance_api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        payload["signature"] = signature
        headers = {"X-MBX-APIKEY": self.settings.binance_api_key}
        return self._request(method, path, params=payload, headers=headers)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self.settings.max_retries + 1):
            try:
                response = self.client.request(method, path, params=params, headers=headers)
                if response.status_code in {418, 429}:
                    raise BinanceRateLimitError(f"Binance rate limited request to {path}: {response.text}")
                if response.status_code in {401, 403}:
                    raise BinancePermissionError(f"Binance permission error for {path}: {response.text}")
                if response.status_code >= 400:
                    self.log.debug("binance_http_error path=%s status=%s body=%s", path, response.status_code, response.text[:500])
                response.raise_for_status()
                return response.json()
            except BinancePermissionError:
                raise
            except BinanceRateLimitError as exc:
                last_error = exc
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {401, 403}:
                    raise BinancePermissionError(str(exc)) from exc
                if exc.response.status_code in {418, 429}:
                    last_error = BinanceRateLimitError(str(exc))
                elif exc.response.status_code == 400:
                    raise
                else:
                    last_error = exc
            except Exception as exc:
                last_error = exc
            sleep_seconds = self.settings.retry_backoff_seconds ** attempt
            self.log.warning("request_retry path=%s attempt=%s sleep=%.2f error=%s", path, attempt, sleep_seconds, last_error)
            time.sleep(sleep_seconds)
        assert last_error is not None
        raise last_error

    def fetch_all_margin_pairs(self) -> list[dict[str, Any]]:
        payload = self._apikey_request("GET", "/sapi/v1/margin/allPairs")
        if not isinstance(payload, list):
            self.log.warning("unexpected_margin_pairs_response type=%s", type(payload).__name__)
            return []
        return payload

    def fetch_available_inventory(self, *, assets: list[str]) -> list[dict[str, Any]]:
        payload = self._signed_request("GET", "/sapi/v1/margin/available-inventory", params={"type": "MARGIN"})
        rows: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            inner = payload.get("assets") or payload.get("data") or payload
            if isinstance(inner, dict):
                for key, value in inner.items():
                    asset_name = str(key).upper()
                    if asset_name in assets:
                        rows.append({"asset": asset_name, "amount": value})
            elif isinstance(inner, list):
                for item in inner:
                    if isinstance(item, dict):
                        asset_name = str(item.get("asset") or "").upper()
                        if asset_name and asset_name in assets:
                            rows.append(item)
        elif isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    asset_name = str(item.get("asset") or "").upper()
                    if asset_name and asset_name in assets:
                        rows.append(item)
        self.log.info("available_inventory_fetched raw_type=%s matched=%s", type(payload).__name__, len(rows))
        return rows

    def fetch_price_index(self, *, symbol: str) -> dict[str, Any]:
        return self._apikey_request("GET", "/sapi/v1/margin/priceIndex", params={"symbol": normalize_symbol(symbol)})

    def fetch_spot_klines(
        self,
        *,
        symbol: str,
        interval: str,
        start_time: datetime | None,
        end_time: datetime | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"symbol": normalize_symbol(symbol), "interval": interval, "limit": limit}
        if start_time is not None:
            params["startTime"] = int(start_time.astimezone(UTC).timestamp() * 1000)
        if end_time is not None:
            params["endTime"] = int(end_time.astimezone(UTC).timestamp() * 1000)
        payload = self._request("GET", "/api/v3/klines", params=params)
        candles: list[dict[str, Any]] = []
        for row in payload:
            candles.append(
                {
                    "symbol": normalize_symbol(symbol),
                    "open_time": datetime.fromtimestamp(row[0] / 1000, tz=UTC),
                    "open": row[1],
                    "high": row[2],
                    "low": row[3],
                    "close": row[4],
                    "volume": row[5],
                    "close_time": datetime.fromtimestamp(row[6] / 1000, tz=UTC),
                    "quote_volume": row[7],
                    "trade_count": row[8],
                    "taker_buy_base_volume": row[9],
                    "taker_buy_quote_volume": row[10],
                    "raw": row,
                }
            )
        return candles

    def fetch_isolated_margin_tiers(self, *, symbols: list[str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for symbol in symbols:
            try:
                payload = self._signed_request(
                    "GET",
                    "/sapi/v1/margin/isolatedMarginTier",
                    params={"symbol": normalize_symbol(symbol)},
                )
                if isinstance(payload, list):
                    rows.extend(payload)
                else:
                    rows.append(payload)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 400:
                    self.log.debug("isolated_margin_tier_not_found symbol=%s", symbol)
                    continue
                raise
        return rows

    def fetch_cross_margin_collateral_ratios(self) -> list[dict[str, Any]]:
        payload = self._signed_request("GET", "/sapi/v1/margin/crossMarginCollateralRatio")
        return payload if isinstance(payload, list) else [payload]

    def fetch_risk_based_liquidation_ratios(self) -> list[dict[str, Any]]:
        payload = self._signed_request("GET", "/sapi/v1/margin/risk-based-liquidation-ratio")
        return payload if isinstance(payload, list) else [payload]
