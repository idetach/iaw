from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from .client import get_http_client
from .config import get_settings

router = APIRouter(prefix="/v1/radar", tags=["radar"])
_log = logging.getLogger("bybit_trading.radar")


def _raise_if_bybit_error(resp: dict) -> dict:
    ret_code = resp.get("retCode", 0)
    if ret_code != 0:
        raise HTTPException(
            status_code=400,
            detail=f"Bybit error {ret_code}: {resp.get('retMsg', 'unknown')}",
        )
    return resp


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Extreme price & volume events
# ---------------------------------------------------------------------------

@router.get("/extreme-events")
def get_extreme_events(
    price_change_pct_threshold: float | None = Query(
        default=None,
        description="Override RADAR_PRICE_CHANGE_PCT_THRESHOLD from settings",
    ),
    volume_threshold_usdt: float | None = Query(
        default=None,
        description="Override RADAR_VOLUME_THRESHOLD_USDT from settings",
    ),
    limit: int = Query(default=50, ge=1, le=500, description="Max symbols to scan"),
) -> dict[str, Any]:
    """
    Scan all linear perpetual tickers and return symbols with:
    - Extreme price moves: |price_24h_change_pct| >= threshold
    - Extreme volume: turnover_24h >= threshold (USDT)

    Results are sorted by absolute price change descending.
    """
    settings = get_settings()
    session = get_http_client(settings)
    category = settings.bybit_category

    price_thresh = price_change_pct_threshold if price_change_pct_threshold is not None else settings.radar_price_change_pct_threshold
    vol_thresh = volume_threshold_usdt if volume_threshold_usdt is not None else settings.radar_volume_threshold_usdt

    try:
        resp = session.get_tickers(category=category)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Bybit request failed: {exc}")

    _raise_if_bybit_error(resp)

    tickers: list[dict] = resp.get("result", {}).get("list", [])

    extreme_price: list[dict[str, Any]] = []
    extreme_volume: list[dict[str, Any]] = []

    for t in tickers:
        symbol = t.get("symbol", "")
        price_pct = _safe_float(t.get("price24hPcnt")) * 100  # Bybit returns as decimal e.g. 0.035
        turnover = _safe_float(t.get("turnover24h"))
        last_price = _safe_float(t.get("lastPrice"))
        volume_24h = _safe_float(t.get("volume24h"))

        entry: dict[str, Any] = {
            "symbol": symbol,
            "lastPrice": t.get("lastPrice"),
            "price24hPcnt": t.get("price24hPcnt"),
            "price24hPctAbs": round(abs(price_pct), 4),
            "direction": "up" if price_pct > 0 else "down",
            "high24h": t.get("highPrice24h"),
            "low24h": t.get("lowPrice24h"),
            "volume24h": t.get("volume24h"),
            "turnover24h": t.get("turnover24h"),
            "openInterest": t.get("openInterest"),
            "fundingRate": t.get("fundingRate"),
        }

        if abs(price_pct) >= price_thresh:
            extreme_price.append(entry)

        if turnover >= vol_thresh:
            extreme_volume.append(entry)

    extreme_price.sort(key=lambda x: x["price24hPctAbs"], reverse=True)
    extreme_volume.sort(key=lambda x: _safe_float(x.get("turnover24h")), reverse=True)

    return {
        "thresholds": {
            "price_change_pct": price_thresh,
            "volume_usdt": vol_thresh,
        },
        "extreme_price_moves": extreme_price[:limit],
        "extreme_volume": extreme_volume[:limit],
        "scanned_symbols": len(tickers),
    }


# ---------------------------------------------------------------------------
# Extreme negative funding rate positions
# ---------------------------------------------------------------------------

@router.get("/negative-funding")
def get_negative_funding_positions(
    funding_rate_threshold: float | None = Query(
        default=None,
        description="Override RADAR_FUNDING_RATE_THRESHOLD from settings (should be negative)",
    ),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    """
    Scan all linear perpetual tickers and return symbols where:
    - funding_rate <= threshold (extreme negative funding — shorts pay longs)

    Sorted by funding rate ascending (most negative first).
    """
    settings = get_settings()
    session = get_http_client(settings)
    category = settings.bybit_category

    funding_thresh = (
        funding_rate_threshold
        if funding_rate_threshold is not None
        else settings.radar_funding_rate_threshold
    )

    try:
        resp = session.get_tickers(category=category)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Bybit request failed: {exc}")

    _raise_if_bybit_error(resp)

    tickers: list[dict] = resp.get("result", {}).get("list", [])
    flagged: list[dict[str, Any]] = []

    for t in tickers:
        funding_rate = _safe_float(t.get("fundingRate"), default=float("nan"))
        if funding_rate != funding_rate:  # NaN check
            continue
        if funding_rate <= funding_thresh:
            flagged.append(
                {
                    "symbol": t.get("symbol"),
                    "lastPrice": t.get("lastPrice"),
                    "fundingRate": t.get("fundingRate"),
                    "nextFundingTime": t.get("nextFundingTime"),
                    "openInterest": t.get("openInterest"),
                    "openInterestValue": t.get("openInterestValue"),
                    "price24hPcnt": t.get("price24hPcnt"),
                    "volume24h": t.get("volume24h"),
                    "turnover24h": t.get("turnover24h"),
                }
            )

    flagged.sort(key=lambda x: _safe_float(x.get("fundingRate")))

    return {
        "threshold": funding_thresh,
        "flagged": flagged[:limit],
        "flagged_count": len(flagged),
        "scanned_symbols": len(tickers),
    }


# ---------------------------------------------------------------------------
# Open positions with extreme negative funding (requires auth)
# ---------------------------------------------------------------------------

@router.get("/negative-funding/positions")
def get_open_positions_with_negative_funding(
    funding_rate_threshold: float | None = Query(default=None),
    symbol: str | None = Query(default=None, description="Filter to a single symbol"),
) -> dict[str, Any]:
    """
    Fetch your open positions and annotate each with current funding rate.
    Returns positions that are on symbols with extreme negative funding,
    highlighting the cost/benefit of holding vs closing.

    Requires API credentials.
    """
    settings = get_settings()
    if not settings.has_credentials:
        raise HTTPException(status_code=401, detail="API credentials required for position data")

    session = get_http_client(settings)
    category = settings.bybit_category

    funding_thresh = (
        funding_rate_threshold
        if funding_rate_threshold is not None
        else settings.radar_funding_rate_threshold
    )

    try:
        pos_kwargs: dict[str, Any] = {"category": category, "settleCoin": "USDT"}
        if symbol:
            pos_kwargs["symbol"] = symbol
        positions_resp = session.get_positions(**pos_kwargs)
        tickers_resp = session.get_tickers(category=category)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Bybit request failed: {exc}")

    _raise_if_bybit_error(positions_resp)
    _raise_if_bybit_error(tickers_resp)

    tickers_list: list[dict] = tickers_resp.get("result", {}).get("list", [])
    funding_by_symbol: dict[str, float] = {}
    ticker_by_symbol: dict[str, dict] = {}
    for t in tickers_list:
        sym = t.get("symbol", "")
        funding_by_symbol[sym] = _safe_float(t.get("fundingRate"), default=float("nan"))
        ticker_by_symbol[sym] = t

    positions: list[dict] = positions_resp.get("result", {}).get("list", [])
    flagged: list[dict[str, Any]] = []

    for pos in positions:
        size = _safe_float(pos.get("size", "0"))
        if size == 0:
            continue
        sym = pos.get("symbol", "")
        funding_rate = funding_by_symbol.get(sym, float("nan"))
        if funding_rate != funding_rate:
            continue
        if funding_rate <= funding_thresh:
            ticker = ticker_by_symbol.get(sym, {})
            flagged.append(
                {
                    "symbol": sym,
                    "side": pos.get("side"),
                    "size": pos.get("size"),
                    "avgPrice": pos.get("avgPrice"),
                    "markPrice": pos.get("markPrice"),
                    "unrealisedPnl": pos.get("unrealisedPnl"),
                    "leverage": pos.get("leverage"),
                    "positionValue": pos.get("positionValue"),
                    "fundingRate": ticker.get("fundingRate"),
                    "nextFundingTime": ticker.get("nextFundingTime"),
                    "openInterest": ticker.get("openInterest"),
                    "positionIdx": pos.get("positionIdx"),
                    "liqPrice": pos.get("liqPrice"),
                    "stopLoss": pos.get("stopLoss"),
                    "takeProfit": pos.get("takeProfit"),
                }
            )

    flagged.sort(key=lambda x: _safe_float(x.get("fundingRate")))

    return {
        "threshold": funding_thresh,
        "flagged_positions": flagged,
        "flagged_count": len(flagged),
        "total_open_positions": len([p for p in positions if _safe_float(p.get("size", "0")) > 0]),
    }
