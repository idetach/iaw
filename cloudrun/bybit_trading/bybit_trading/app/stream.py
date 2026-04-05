from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from pybit.unified_trading import WebSocket

from .config import get_settings

router = APIRouter(prefix="/v1/stream", tags=["stream"])
_log = logging.getLogger("bybit_trading.stream")

# ---------------------------------------------------------------------------
# Per-symbol SSE hub
# ---------------------------------------------------------------------------
# Maps symbol -> {"subscribers": set[asyncio.Queue], "ws": WebSocket | None,
#                 "lock": threading.Lock, "last_msg": dict | None}
_hubs: dict[str, dict[str, Any]] = {}
_hubs_lock = threading.Lock()


def _get_or_create_hub(symbol: str, loop: asyncio.AbstractEventLoop) -> dict[str, Any]:
    with _hubs_lock:
        if symbol not in _hubs:
            _hubs[symbol] = {
                "subscribers": set(),
                "ws": None,
                "lock": threading.Lock(),
                "last_msg": None,
                "loop": loop,
            }
        return _hubs[symbol]


def _ws_message_handler(symbol: str, message: dict) -> None:
    with _hubs_lock:
        hub = _hubs.get(symbol)
    if hub is None:
        return

    hub["last_msg"] = message
    loop: asyncio.AbstractEventLoop = hub["loop"]
    subscribers: set[asyncio.Queue] = hub["subscribers"]

    for q in list(subscribers):
        try:
            asyncio.run_coroutine_threadsafe(q.put(message), loop)
        except Exception:
            pass


def _ensure_ws_running(symbol: str, hub: dict[str, Any], settings) -> None:
    with hub["lock"]:
        if hub.get("ws") is not None:
            return

        def _handler(msg: dict) -> None:
            _ws_message_handler(symbol, msg)

        ws = WebSocket(
            testnet=settings.bybit_testnet,
            channel_type="linear",
        )
        ws.ticker_stream(
            symbol=symbol,
            callback=_handler,
        )
        hub["ws"] = ws
        _log.info("WebSocket ticker stream started for %s", symbol)


def _stop_ws_if_no_subscribers(symbol: str, hub: dict[str, Any]) -> None:
    with hub["lock"]:
        if hub["subscribers"]:
            return
        ws = hub.pop("ws", None)
        if ws is not None:
            try:
                ws.exit()
            except Exception:
                pass
            _log.info("WebSocket ticker stream stopped for %s (no subscribers)", symbol)


# ---------------------------------------------------------------------------
# SSE endpoint
# ---------------------------------------------------------------------------

@router.get("/price/{symbol}")
async def stream_price(
    symbol: str,
    request: Request,
    heartbeat_seconds: int = Query(default=15, ge=5, le=60),
) -> StreamingResponse:
    """
    Server-Sent Events stream of real-time ticker updates for *symbol*.

    Each event:
      event: ticker
      data: {"symbol": "...", "lastPrice": "...", "markPrice": "...",
             "fundingRate": "...", "openInterest": "...", "ts": ...}

    A `heartbeat` event is emitted every `heartbeat_seconds` when there is no
    ticker activity to keep the connection alive.
    """
    settings = get_settings()
    loop = asyncio.get_event_loop()
    hub = _get_or_create_hub(symbol, loop)
    _ensure_ws_running(symbol, hub, settings)

    q: asyncio.Queue = asyncio.Queue(maxsize=256)
    hub["subscribers"].add(q)

    # Immediately send the last known message so the client has data right away.
    if hub.get("last_msg") is not None:
        await q.put(hub["last_msg"])

    async def gen():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=heartbeat_seconds)
                    data = _extract_ticker_fields(symbol, msg)
                    yield f"event: ticker\ndata: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    yield f"event: heartbeat\ndata: {json.dumps({'ts': int(time.time() * 1000)})}\n\n"
        finally:
            hub["subscribers"].discard(q)
            _stop_ws_if_no_subscribers(symbol, hub)

    return StreamingResponse(gen(), media_type="text/event-stream")


def _extract_ticker_fields(symbol: str, msg: dict) -> dict[str, Any]:
    data = msg.get("data", {})
    return {
        "symbol": symbol,
        "lastPrice": data.get("lastPrice"),
        "markPrice": data.get("markPrice"),
        "indexPrice": data.get("indexPrice"),
        "highPrice24h": data.get("highPrice24h"),
        "lowPrice24h": data.get("lowPrice24h"),
        "volume24h": data.get("volume24h"),
        "turnover24h": data.get("turnover24h"),
        "price24hPcnt": data.get("price24hPcnt"),
        "fundingRate": data.get("fundingRate"),
        "nextFundingTime": data.get("nextFundingTime"),
        "openInterest": data.get("openInterest"),
        "openInterestValue": data.get("openInterestValue"),
        "bid1Price": data.get("bid1Price"),
        "ask1Price": data.get("ask1Price"),
        "ts": msg.get("ts"),
    }
