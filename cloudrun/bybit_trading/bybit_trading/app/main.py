from __future__ import annotations

import logging
import traceback
from pathlib import Path

import secrets

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .market import router as market_router
from .radar import router as radar_router
from .stream import router as stream_router
from .trade import router as trade_router

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=_SERVICE_ROOT / ".env")

logging.basicConfig(level=logging.INFO)
_log = logging.getLogger("bybit_trading")
logging.getLogger("pybit").setLevel(logging.WARNING)

app = FastAPI(
    title="bybit_trading",
    version="0.1.0",
    description=(
        "Bybit v5 trading service: market data, real-time streaming, "
        "radar alerts, and order/position management."
    ),
)

_settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(market_router)
app.include_router(stream_router)
app.include_router(radar_router)
app.include_router(trade_router)

_UNPROTECTED_PATHS = {"/health", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect", "/v1/config"}


@app.middleware("http")
async def bearer_token_middleware(request: Request, call_next):
    token = _settings.bybit_trading_token
    if not token:
        return await call_next(request)
    if request.url.path in _UNPROTECTED_PATHS:
        return await call_next(request)
    auth = request.headers.get("Authorization", "")
    provided = auth.removeprefix("Bearer ").strip()
    if not provided or not secrets.compare_digest(provided, token):
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    return await call_next(request)


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    _log.error("Unhandled exception on %s %s: %s", request.method, request.url.path, exc)
    _log.error(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "detail": f"{type(exc).__name__}: {exc}",
        },
    )


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse(content={"ok": True, "service": "bybit_trading"})


@app.get("/v1/config")
def get_config() -> JSONResponse:
    """Return non-sensitive runtime config for the frontend."""
    s = get_settings()
    return JSONResponse(
        content={
            "testnet": s.bybit_testnet,
            "category": s.bybit_category,
            "has_credentials": s.has_credentials,
            "radar_thresholds": {
                "price_change_pct": s.radar_price_change_pct_threshold,
                "volume_usdt": s.radar_volume_threshold_usdt,
                "funding_rate": s.radar_funding_rate_threshold,
            },
        }
    )
