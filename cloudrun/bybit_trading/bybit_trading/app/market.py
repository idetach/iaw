from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from .client import get_http_client
from .config import get_settings

router = APIRouter(prefix="/v1/market", tags=["market"])


def _raise_if_bybit_error(resp: dict) -> dict:
    ret_code = resp.get("retCode", 0)
    if ret_code != 0:
        raise HTTPException(
            status_code=400,
            detail=f"Bybit error {ret_code}: {resp.get('retMsg', 'unknown')}",
        )
    return resp


# ---------------------------------------------------------------------------
# Futures trading data
# ---------------------------------------------------------------------------

@router.get("/futures/{symbol}")
def get_futures_data(
    symbol: str,
    interval: str = Query(default="60", description="Kline interval: 1,3,5,15,30,60,120,240,360,720,D,M,W"),
    kline_limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    """
    Fetch futures trading data for a symbol:
    - Recent klines (OHLCV)
    - Level-2 orderbook (depth 25)
    - Recent public trades
    - Current ticker snapshot
    """
    settings = get_settings()
    session = get_http_client(settings)
    category = settings.bybit_category

    try:
        klines_resp = session.get_kline(
            category=category,
            symbol=symbol,
            interval=interval,
            limit=kline_limit,
        )
        orderbook_resp = session.get_orderbook(
            category=category,
            symbol=symbol,
            limit=25,
        )
        trades_resp = session.get_public_trade_history(
            category=category,
            symbol=symbol,
            limit=50,
        )
        ticker_resp = session.get_tickers(
            category=category,
            symbol=symbol,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Bybit request failed: {exc}")

    _raise_if_bybit_error(klines_resp)
    _raise_if_bybit_error(orderbook_resp)
    _raise_if_bybit_error(trades_resp)
    _raise_if_bybit_error(ticker_resp)

    tickers = ticker_resp.get("result", {}).get("list", [])
    ticker = tickers[0] if tickers else {}

    return {
        "symbol": symbol,
        "interval": interval,
        "klines": klines_resp.get("result", {}).get("list", []),
        "orderbook": {
            "bids": orderbook_resp.get("result", {}).get("b", []),
            "asks": orderbook_resp.get("result", {}).get("a", []),
            "ts": orderbook_resp.get("result", {}).get("ts"),
            "seq": orderbook_resp.get("result", {}).get("seq"),
        },
        "recent_trades": trades_resp.get("result", {}).get("list", []),
        "ticker": ticker,
    }


# ---------------------------------------------------------------------------
# Overview data
# ---------------------------------------------------------------------------

@router.get("/overview/{symbol}")
def get_overview(symbol: str) -> dict[str, Any]:
    """
    Fetch symbol overview:
    - Ticker (last price, 24h change, volume, high/low)
    - Open interest
    - Funding rate history (last 3 entries)
    - Long/short ratio (if available via index tickers)
    - Mark price & index price
    """
    settings = get_settings()
    session = get_http_client(settings)
    category = settings.bybit_category

    try:
        ticker_resp = session.get_tickers(category=category, symbol=symbol)
        oi_resp = session.get_open_interest(
            category=category,
            symbol=symbol,
            intervalTime="1h",
            limit=3,
        )
        funding_resp = session.get_funding_rate_history(
            category=category,
            symbol=symbol,
            limit=3,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Bybit request failed: {exc}")

    _raise_if_bybit_error(ticker_resp)
    _raise_if_bybit_error(oi_resp)
    _raise_if_bybit_error(funding_resp)

    tickers = ticker_resp.get("result", {}).get("list", [])
    ticker = tickers[0] if tickers else {}

    return {
        "symbol": symbol,
        "ticker": ticker,
        "last_price": ticker.get("lastPrice"),
        "mark_price": ticker.get("markPrice"),
        "index_price": ticker.get("indexPrice"),
        "price_24h_change_pct": ticker.get("price24hPcnt"),
        "high_24h": ticker.get("highPrice24h"),
        "low_24h": ticker.get("lowPrice24h"),
        "volume_24h": ticker.get("volume24h"),
        "turnover_24h": ticker.get("turnover24h"),
        "open_interest": ticker.get("openInterest"),
        "open_interest_value": ticker.get("openInterestValue"),
        "funding_rate": ticker.get("fundingRate"),
        "next_funding_time": ticker.get("nextFundingTime"),
        "bid1_price": ticker.get("bid1Price"),
        "ask1_price": ticker.get("ask1Price"),
        "open_interest_history": oi_resp.get("result", {}).get("list", []),
        "funding_rate_history": funding_resp.get("result", {}).get("list", []),
    }


# ---------------------------------------------------------------------------
# Instrument info
# ---------------------------------------------------------------------------

@router.get("/instrument/{symbol}")
def get_instrument_info(symbol: str) -> dict[str, Any]:
    """
    Fetch instrument specification: tick size, lot size, min/max order qty,
    leverage filters, settlement currency.
    """
    settings = get_settings()
    session = get_http_client(settings)
    category = settings.bybit_category

    try:
        resp = session.get_instruments_info(category=category, symbol=symbol)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Bybit request failed: {exc}")

    _raise_if_bybit_error(resp)
    instruments = resp.get("result", {}).get("list", [])
    instrument = instruments[0] if instruments else {}
    return {"symbol": symbol, "instrument": instrument}
