from __future__ import annotations

import logging
import traceback
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .trader import router as trader_router

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=_SERVICE_ROOT / ".env")

logging.basicConfig(level=logging.INFO)
_log = logging.getLogger("agent_trading")

app = FastAPI(
    title="agent_trading",
    version="0.1.0",
    description=(
        "Trading execution layer: reads proposals from GCS, "
        "places orders via bybit_trading, persists results."
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

app.include_router(trader_router)


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
    return JSONResponse(content={"ok": True, "service": "agent_trading"})


@app.get("/v1/config")
def get_config() -> JSONResponse:
    s = get_settings()
    return JSONResponse(
        content={
            "bybit_trading_url": s.bybit_trading_url,
            "gcs_bucket": s.gcs_bucket,
            "cases_prefix": s.cases_prefix,
        }
    )
