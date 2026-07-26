from __future__ import annotations

import asyncio
from typing import Any

import pytest

from conductor.app import loop
from conductor.app.config import Settings


def make_settings() -> Settings:
    return Settings(_env_file=None, GCS_BUCKET="", EXECUTION_MODE="shadow")


BALANCE = {"totalEquity": "100037.18", "usdt": {"equity": "100037.18"}}
POSITIONS = {"positions": []}
ORDERS = {
    "orders": [
        {
            "orderId": "857dfb17",
            "orderLinkId": "conductor-aaa",
            "symbol": "SOLUSDT",
            "side": "Sell",
            "price": "75.47",
            "qty": "496.8",
            "stopLoss": "76.15",
            "createdTime": "1782476711000",
        },
        {  # manual order — must be excluded
            "orderId": "m1",
            "orderLinkId": "",
            "symbol": "BTCUSDT",
            "side": "Buy",
            "price": "60000",
            "qty": "0.1",
            "createdTime": "1782476711000",
        },
    ]
}


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_portfolio_includes_conductor_orders(monkeypatch):
    async def fake_get(s, path, params=None):
        if path == "/v1/trade/balance":
            return BALANCE
        if path == "/v1/trade/positions":
            return POSITIONS
        if path == "/v1/trade/orders":
            return ORDERS
        if path == "/v1/trade/closed-pnl":
            return {"records": []}
        raise AssertionError(path)

    monkeypatch.setattr(loop, "_bybit_get", fake_get)
    portfolio, err, _ = run(loop._portfolio_state(make_settings()))
    assert err is None
    assert portfolio.orders_error is None
    assert len(portfolio.open_orders) == 1  # manual order filtered out
    assert portfolio.open_orders[0]["symbol"] == "SOLUSDT"
    # risk from resting order: 496.8 * |75.47 - 76.15| ≈ 337.8
    assert portfolio.open_risk_usdt == pytest.approx(496.8 * 0.68, rel=1e-3)


def test_orders_fetch_failure_is_loud_not_silent(monkeypatch):
    async def fake_get(s, path, params=None):
        if path == "/v1/trade/balance":
            return BALANCE
        if path == "/v1/trade/positions":
            return POSITIONS
        if path == "/v1/trade/orders":
            raise RuntimeError("Bybit error 10001: symbol or settleCoin needed")
        if path == "/v1/trade/closed-pnl":
            return {"records": []}
        raise AssertionError(path)

    monkeypatch.setattr(loop, "_bybit_get", fake_get)
    portfolio, err, _ = run(loop._portfolio_state(make_settings()))
    assert err is None  # balance/positions fine — entries not blocked
    assert portfolio.orders_error is not None  # ...but the failure is surfaced
    assert "10001" in portfolio.orders_error
    assert portfolio.open_orders == []
