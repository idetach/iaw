"""
MarketDataProvider abstraction (ADR-0002, autonomous-data-path).

Phase 1: BybitTradingProvider — fetches klines through the existing
bybit_trading service (/v1/market/futures/{symbol}). Phase 2 can add a
dedicated market-data vendor behind the same Protocol without touching the
Conductor loop.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

import httpx
from fastapi import HTTPException

from .auth import id_token_for_cloud_run
from .config import Settings
from .models import OHLCV, TIMEFRAME_TO_INTERVAL


class MarketDataProvider(Protocol):
    async def klines(self, symbol: str, timeframe: str, limit: int) -> list[OHLCV]: ...
    async def ticker(self, symbol: str) -> dict[str, Any]: ...


class BybitTradingProvider:
    """Reads market data via the bybit_trading service."""

    def __init__(self, settings: Settings):
        self._settings = settings

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        # Cloud Run IAM uses the Authorization header for identity tokens.
        id_token = id_token_for_cloud_run(self._settings.bybit_trading_url)
        if id_token:
            h["Authorization"] = f"Bearer {id_token}"
        if self._settings.bybit_trading_token:
            h["X-Internal-Token"] = self._settings.bybit_trading_token
        return h

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self._settings.bybit_trading_url.rstrip('/')}{path}"
        timeout = httpx.Timeout(self._settings.bybit_trading_timeout, connect=10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url, params=params, headers=self._headers())
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"bybit_trading request failed: {type(exc).__name__}: {exc}",
            )
        if resp.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"bybit_trading {path} HTTP {resp.status_code}: {resp.text[:300]}",
            )
        return resp.json()

    async def klines(self, symbol: str, timeframe: str, limit: int) -> list[OHLCV]:
        interval = TIMEFRAME_TO_INTERVAL.get(timeframe)
        if interval is None:
            raise HTTPException(status_code=400, detail=f"Unknown timeframe: {timeframe}")
        data = await self._get(
            f"/v1/market/futures/{symbol}",
            params={"interval": interval, "kline_limit": limit},
        )
        raw = data.get("klines", [])
        candles = [_parse_bybit_kline(row) for row in raw]
        candles.sort(key=lambda c: c.start)  # Bybit returns newest-first
        # Drop the currently-forming candle: only CLOSED candles enter the engine.
        return candles[:-1] if candles else []

    async def ticker(self, symbol: str) -> dict[str, Any]:
        data = await self._get(f"/v1/market/overview/{symbol}")
        return data.get("ticker", data)


def _parse_bybit_kline(row: list[Any]) -> OHLCV:
    """Bybit v5 kline row: [startTime(ms), open, high, low, close, volume, turnover]."""
    return OHLCV(
        start=datetime.fromtimestamp(int(row[0]) / 1000.0, tz=timezone.utc),
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
        turnover=float(row[6]) if len(row) > 6 else 0.0,
    )
