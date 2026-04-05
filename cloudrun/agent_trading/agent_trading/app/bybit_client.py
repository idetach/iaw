from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException

from .config import Settings


def _headers(settings: Settings) -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if settings.bybit_trading_token:
        h["Authorization"] = f"Bearer {settings.bybit_trading_token}"
    return h


def _timeout(settings: Settings) -> httpx.Timeout:
    return httpx.Timeout(settings.bybit_trading_timeout, connect=10.0)


def _url(settings: Settings, path: str) -> str:
    base = settings.bybit_trading_url.rstrip("/")
    path = path if path.startswith("/") else f"/{path}"
    return f"{base}{path}"


async def call(
    settings: Settings,
    *,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = _url(settings, path)
    try:
        async with httpx.AsyncClient(timeout=_timeout(settings)) as client:
            resp = await client.request(
                method.upper(),
                url,
                json=body,
                params=params,
                headers=_headers(settings),
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"bybit_trading request failed: {type(exc).__name__}: {exc}",
        )

    if resp.status_code >= 400:
        text = resp.text or ""
        raise HTTPException(
            status_code=502,
            detail=f"bybit_trading {path} returned HTTP {resp.status_code}: {text[:400]}",
        )

    if not resp.content:
        return {"ok": True}
    try:
        data = resp.json()
    except Exception:
        return {"raw": resp.text}
    return data if isinstance(data, dict) else {"response": data}


async def get_balance(settings: Settings) -> dict[str, Any]:
    return await call(settings, method="GET", path="/v1/trade/balance")


async def set_leverage(settings: Settings, *, symbol: str, leverage: int) -> dict[str, Any]:
    return await call(
        settings,
        method="POST",
        path="/v1/trade/leverage",
        body={"symbol": symbol, "leverage": leverage},
    )


async def place_order(settings: Settings, body: dict[str, Any]) -> dict[str, Any]:
    return await call(settings, method="POST", path="/v1/trade/order", body=body)


async def get_instrument_info(settings: Settings, symbol: str) -> dict[str, Any]:
    return await call(settings, method="GET", path=f"/v1/market/instrument/{symbol}")
